"""Business logic for the Smart Pickup Box backend.

Scheduling, box allocation, state transitions and pickup-code handling.
No web-framework imports: every function takes a sqlite3 connection that is already
inside a transaction (see db.write_tx / db.read_tx), which keeps the rules testable
without HTTP and keeps main.py a thin routing layer.

Queue priority (who gets the next free box) is a plain scheduling algorithm, no model:
  1. latest safe start - smallest (pickup_due_at - estimated_prep_minutes) first;
  2. creation time     - oldest created_at first on a tie.
Everything is in pick_next() if you want to change it.
"""
import hashlib
import hmac
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

import config

log = logging.getLogger("pickupbox")

ACTIVE_ORDER_STATES = ("PREPARING", "READY", "PICKUP_AUTHORIZED")
ORDER_STATES = ("QUEUED",) + ACTIVE_ORDER_STATES + ("COLLECTED",)
DISPLAY_MODE = {
    "AVAILABLE": "IDLE",
    "PREPARING": "PREPARING",
    "READY": "READY",
    "UNLOCKED": "AUTHORIZED",
}
GENERIC_CODE_ERROR = "Invalid or expired pickup credential"
NO_READY_ORDER_ERROR = "No order is ready for pickup at this box"


class ApiError(Exception):
    """Returned to the client as {"error": <message>, **extra} with this HTTP status."""

    def __init__(self, status_code: int, error: str, **extra):
        super().__init__(error)
        self.status_code = status_code
        self.body = {"error": error, **extra}


# --------------------------------------------------------------------------- helpers

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """UTC ISO 8601 with a fixed width, so stored timestamps sort correctly as text."""
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


_KNOWN_PLATFORMS = {"doordash": "DoorDash", "ubereats": "Uber Eats", "grubhub": "Grubhub"}
_ID_PREFIX = {"doordash": "DD", "ubereats": "UE", "grubhub": "GH"}


def platform_key(platform: str) -> str:
    return re.sub(r"[^a-z0-9]", "", platform.lower())


def canonical_platform(platform: str) -> str:
    platform = platform.strip()
    return _KNOWN_PLATFORMS.get(platform_key(platform), platform)


def _id_prefix(platform: str) -> str:
    return _ID_PREFIX.get(platform_key(platform)) or (re.sub(r"[^A-Za-z]", "", platform).upper()[:2] or "OR")


def abbreviate_name(name: str) -> str:
    """'Alex Morgan' -> 'Alex M.'. Already-abbreviated and single names pass through."""
    parts = name.split()
    if len(parts) < 2:
        return name.strip()
    last = parts[-1]
    if last.endswith(".") and len(last) <= 2:
        return " ".join(parts)
    return f"{parts[0]} {last[0].upper()}."


def normalize_uid(uid: str) -> str:
    """RFID readers format UIDs differently ('04:a1:b2' / '04A1B2'): compare normalised."""
    return re.sub(r"[\s:\-]", "", uid).upper()


def _pluralize(name: str, qty: int) -> str:
    if qty == 1:
        return name
    low = name.lower()
    if low.endswith("s"):
        return name
    if low.endswith(("x", "z", "ch", "sh")):
        return name + "es"
    if low.endswith("y") and len(low) > 1 and low[-2] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def summarize_items(items: list, max_parts: int = 4) -> str:
    """[{'Veg Burger',2},{'Fries',1}] -> '2 Veg Burgers · 1 Fries'."""
    parts = [f"{i['quantity']} {_pluralize(i['name'], i['quantity'])}" for i in items]
    if len(parts) > max_parts:
        parts = parts[:max_parts] + [f"+{len(items) - max_parts} more"]
    return " · ".join(parts)


# ----------------------------------------------------------------------- pickup codes
# The code is derived from (secret, order_id, nonce) so the courier dashboard can show it
# while the database holds only the nonce and an HMAC of the code - a copy of the database
# alone reveals neither. Without PICKUP_CODE_SECRET the code cannot be recomputed.

def _hmac(*parts: str) -> bytes:
    return hmac.new(config.PICKUP_CODE_SECRET, ":".join(parts).encode("utf-8"), hashlib.sha256).digest()


def derive_code(order_id: str, nonce: str) -> str:
    return f"{int.from_bytes(_hmac('code', order_id, nonce)[:8], 'big') % 1_000_000:06d}"


def hash_code(order_id: str, code: str) -> str:
    return _hmac("verify", order_id, code).hex()


# ------------------------------------------------------------------------- scheduling

def latest_start(pickup_due_at: datetime, estimated_prep_minutes: int) -> datetime:
    """The last moment preparation can start and still make the pickup deadline."""
    return pickup_due_at - timedelta(minutes=estimated_prep_minutes)


def _priority_key(order: dict):
    # Stored timestamps are fixed-width UTC strings, so they compare correctly as text.
    return (order["latest_start_at"], order["created_at"], order["seq"])


def pick_next(queued: list) -> dict:
    """The queued order that should get the next free box. queued: non-empty list of order dicts."""
    return min(queued, key=_priority_key)


def project_queue(queued: list) -> dict:
    """{order_id: position} - the order in which free boxes would be handed out right now.
    Uses the same priority as the real allocator, so position 1 is the next real assignment."""
    return {o["order_id"]: i for i, o in enumerate(sorted(queued, key=_priority_key), start=1)}


def _queued(conn) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM orders WHERE status = 'QUEUED'")]


def allocate_boxes(conn) -> list:
    """For every AVAILABLE box, assign the highest-priority QUEUED order (box and order both
    become PREPARING). Must run inside write_tx, which makes it atomic. Returns [(box_id, order_id)]."""
    assignments = []
    free = [r["box_id"] for r in conn.execute(
        "SELECT box_id FROM boxes WHERE status = 'AVAILABLE' AND order_id IS NULL ORDER BY box_id")]
    for box_id in free:
        queued = _queued(conn)
        if not queued:
            break
        order = pick_next(queued)
        claimed = conn.execute(
            "UPDATE orders SET status = 'PREPARING', box_id = ?, assigned_at = ? "
            "WHERE order_id = ? AND status = 'QUEUED'",
            (box_id, iso(now_utc()), order["order_id"]))
        filled = conn.execute(
            "UPDATE boxes SET status = 'PREPARING', order_id = ?, display_mode = ?, lock_state = 'UNLOCKED' "
            "WHERE box_id = ? AND status = 'AVAILABLE' AND order_id IS NULL",
            (order["order_id"], DISPLAY_MODE["PREPARING"], box_id))
        if claimed.rowcount != 1 or filled.rowcount != 1:  # cannot happen inside BEGIN IMMEDIATE
            raise ApiError(409, "Allocation conflict, please retry")
        assignments.append((box_id, order["order_id"]))
        log.info("%s -> %s PREPARING (%s, latest start %s)", order["order_id"], box_id, order["platform"],
                 order["latest_start_at"])
    return assignments


# ----------------------------------------------------------------------------- orders

def _new_order_id(conn, platform: str) -> str:
    prefix = _id_prefix(platform)
    n = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] + 101
    while conn.execute("SELECT 1 FROM orders WHERE order_id = ?", (f"{prefix}-{n}",)).fetchone():
        n += 1
    return f"{prefix}-{n}"


def ingest_orders(conn, payloads: list) -> list:
    """Normalise and insert validated order payloads as QUEUED. Returns the order IDs.
    Call allocate_boxes() afterwards (kept separate so a batch is prioritised as a whole)."""
    ids = []
    for p in payloads:
        platform = canonical_platform(p["platform"])
        order_id = p.get("order_id") or _new_order_id(conn, platform)
        if conn.execute("SELECT 1 FROM orders WHERE order_id = ?", (order_id,)).fetchone():
            raise ApiError(409, f"Order {order_id} already exists")
        created = p.get("created_at") or now_utc()
        due = p["pickup_due_at"]
        prep = int(p["estimated_prep_minutes"])
        start = latest_start(due, prep)
        items = [{"name": i["name"], "quantity": int(i["quantity"])} for i in p["items"]]
        conn.execute(
            "INSERT INTO orders (order_id, platform, customer_display_name, items_json, estimated_prep_minutes, "
            "pickup_due_at, latest_start_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, platform, abbreviate_name(p["customer_display_name"]), json.dumps(items),
             prep, iso(due), iso(start), iso(created)))
        ids.append(order_id)
        log.info("%s queued (%s, latest start %s)", order_id, platform, iso(start))
    return ids


def _order_dict(row, queue_position=None) -> dict:
    return {
        "order_id": row["order_id"],
        "platform": row["platform"],
        "customer_display_name": row["customer_display_name"],
        "items": json.loads(row["items_json"]),
        "estimated_prep_minutes": row["estimated_prep_minutes"],
        "pickup_due_at": row["pickup_due_at"],
        "latest_start_at": row["latest_start_at"],
        "created_at": row["created_at"],
        "status": row["status"],
        "box_id": row["box_id"],
        "queue_position": queue_position,
    }


def list_orders(conn, status: str = None) -> list:
    """The ledger, oldest first. QUEUED orders carry queue_position (1 = next to get a box)."""
    rows = conn.execute("SELECT * FROM orders ORDER BY created_at, seq").fetchall()
    positions = project_queue(_queued(conn))
    out = [_order_dict(r, positions.get(r["order_id"])) for r in rows]
    return [o for o in out if o["status"] == status] if status else out


def get_order(conn, order_id: str) -> dict:
    return next(o for o in list_orders(conn) if o["order_id"] == order_id)


# ------------------------------------------------------------------------------ boxes

def _get_box(conn, box_id: str, **error_extra):
    box = conn.execute("SELECT * FROM boxes WHERE box_id = ?", (box_id,)).fetchone()
    if box is None:
        raise ApiError(404, "Unknown box", **error_extra)
    return box


def box_record(box) -> dict:
    return {
        "box_id": box["box_id"],
        "status": box["status"],
        "order_id": box["order_id"],
        "display_mode": box["display_mode"],
        "lock_state": box["lock_state"],
    }


def list_boxes(conn) -> list:
    return [box_record(b) for b in conn.execute("SELECT * FROM boxes ORDER BY box_id")]


def box_screen_view(conn, box_id: str) -> dict:
    """Display-safe view for the box screen / hardware bridge. Never contains a pickup code,
    and in PREPARING shows food items only (no customer, platform or order ID)."""
    box = _get_box(conn, box_id)
    view = {
        "box_id": box["box_id"],
        "status": box["status"],
        "display_mode": box["display_mode"],
        "lock_state": box["lock_state"],
        "pickup_url": config.public_pickup_url(box["box_id"]),
    }
    if box["order_id"] and box["status"] in ("PREPARING", "READY", "UNLOCKED"):
        order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (box["order_id"],)).fetchone()
        if order is not None:
            items = json.loads(order["items_json"])
            if box["status"] == "PREPARING":
                view["items"] = items
            else:
                view["order_id"] = order["order_id"]
                view["customer_display_name"] = order["customer_display_name"]
                view["summary"] = summarize_items(items)
    return view


# ------------------------------------------------------------- staff confirm (-> READY)

def seed_defaults(conn) -> None:
    for box_id in config.BOX_IDS:
        conn.execute("INSERT OR IGNORE INTO boxes (box_id) VALUES (?)", (box_id,))
    for uid in config.STAFF_RFID_UIDS:
        conn.execute("INSERT OR IGNORE INTO staff_credentials (rfid_uid, staff_name) VALUES (?, 'Demo staff')",
                     (normalize_uid(uid),))


def register_staff(conn, rfid_uid: str, staff_name: str = None) -> dict:
    uid = normalize_uid(rfid_uid)
    if not uid:
        raise ApiError(422, "rfid_uid is empty")
    conn.execute(
        "INSERT INTO staff_credentials (rfid_uid, staff_name, active) VALUES (?, ?, 1) "
        "ON CONFLICT(rfid_uid) DO UPDATE SET active = 1, "
        "staff_name = COALESCE(excluded.staff_name, staff_credentials.staff_name)",
        (uid, staff_name))
    return {"registered": True, "rfid_uid": uid}


def staff_confirm(conn, box_id: str, rfid_uid: str) -> dict:
    """Staff taps a registered RFID card: PREPARING -> READY, and a one-time pickup code is
    issued (never returned here). A repeat tap on an already READY box is a harmless no-op."""
    box = _get_box(conn, box_id, confirmed=False)
    uid = normalize_uid(rfid_uid)
    staff = conn.execute("SELECT 1 FROM staff_credentials WHERE rfid_uid = ? AND active = 1", (uid,)).fetchone()
    if staff is None:
        log.warning("Unknown RFID UID %r tapped on %s. To register it: POST /demo/staff {\"rfid_uid\": \"%s\"}",
                    rfid_uid, box_id, rfid_uid)
        raise ApiError(403, "Unknown staff credential", confirmed=False)

    if box["status"] == "READY" and box["order_id"]:
        return {"confirmed": True, "already_confirmed": True, "box_id": box_id,
                "order_id": box["order_id"], "status": "READY"}
    if box["status"] != "PREPARING" or not box["order_id"]:
        raise ApiError(409, "This box has no order being prepared", confirmed=False)

    order_id = box["order_id"]
    moved = conn.execute("UPDATE orders SET status = 'READY' WHERE order_id = ? AND status = 'PREPARING'", (order_id,))
    if moved.rowcount != 1:
        raise ApiError(409, "Order is not in preparation", confirmed=False)
    conn.execute(
        "UPDATE boxes SET status = 'READY', display_mode = ?, lock_state = 'LOCKED' WHERE box_id = ?",
        (DISPLAY_MODE["READY"], box_id))

    now = now_utc()
    nonce = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO pickup_credentials (order_id, box_id, code_nonce, pickup_code_hash, issued_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (order_id, box_id, nonce, hash_code(order_id, derive_code(order_id, nonce)), iso(now),
         iso(now + timedelta(minutes=config.PICKUP_CODE_TTL_MINUTES))))
    log.info("%s %s READY, pickup code issued (expires in %g min)", box_id, order_id, config.PICKUP_CODE_TTL_MINUTES)
    return {"confirmed": True, "already_confirmed": False, "box_id": box_id, "order_id": order_id, "status": "READY"}


# ------------------------------------------------------ courier verification (-> UNLOCKED)

def verify_pickup(conn, box_id: str, submitted_code: str):
    """Returns (http_status, body). Credential problems are returned, not raised, so that a
    failed-attempt counter update is committed. A wrong, expired or reused code never changes
    the order or the box."""
    box = _get_box(conn, box_id, authorized=False)
    not_ready = (409, {"authorized": False, "error": NO_READY_ORDER_ERROR})
    if box["status"] != "READY" or not box["order_id"]:
        return not_ready
    order_id = box["order_id"]
    cred = conn.execute("SELECT * FROM pickup_credentials WHERE order_id = ?", (order_id,)).fetchone()
    order = conn.execute("SELECT status, box_id FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if (cred is None or order is None or order["status"] != "READY"
            or order["box_id"] != box_id or cred["box_id"] != box_id):
        return not_ready

    now = now_utc()
    if cred["last_failed_at"]:
        wait = config.FAILED_ATTEMPT_COOLDOWN_SECONDS - (now - parse_iso(cred["last_failed_at"])).total_seconds()
        if wait > 0:
            return 429, {"authorized": False, "error": "Too many attempts, wait a moment and try again",
                         "retry_after_seconds": round(wait, 2)}
    if cred["used_at"] is not None or now > parse_iso(cred["expires_at"]):
        return 403, {"authorized": False, "error": GENERIC_CODE_ERROR}

    if not hmac.compare_digest(hash_code(order_id, (submitted_code or "").strip()), cred["pickup_code_hash"]):
        conn.execute(
            "UPDATE pickup_credentials SET failed_attempts = failed_attempts + 1, last_failed_at = ? "
            "WHERE order_id = ?", (iso(now), order_id))
        log.info("%s wrong pickup code for %s (attempt %d)", box_id, order_id, cred["failed_attempts"] + 1)
        return 403, {"authorized": False, "error": GENERIC_CODE_ERROR}

    stamp = iso(now)
    redeemed = conn.execute(
        "UPDATE pickup_credentials SET used_at = ?, authorized_at = ? WHERE order_id = ? AND used_at IS NULL",
        (stamp, stamp, order_id))
    if redeemed.rowcount != 1:
        return 403, {"authorized": False, "error": GENERIC_CODE_ERROR}
    conn.execute("UPDATE orders SET status = 'PICKUP_AUTHORIZED' WHERE order_id = ? AND status = 'READY'", (order_id,))
    conn.execute(
        "UPDATE boxes SET status = 'UNLOCKED', display_mode = ?, lock_state = 'UNLOCKED' WHERE box_id = ?",
        (DISPLAY_MODE["UNLOCKED"], box_id))
    log.info("%s %s pickup AUTHORIZED, box UNLOCKED", box_id, order_id)
    return 200, {"authorized": True, "order_id": order_id, "unlock": True}


# --------------------------------------------------- handoff confirmed (-> AVAILABLE, next)

def complete_pickup(conn, box_id: str) -> dict:
    """Sensor/bridge (or the supervised demo button) confirms the food left the box:
    order COLLECTED, box AVAILABLE, and the box immediately takes the next queued order."""
    box = _get_box(conn, box_id, collected=False)
    if box["status"] != "UNLOCKED" or not box["order_id"]:
        raise ApiError(409, "No authorized pickup at this box", collected=False)
    order_id = box["order_id"]
    done = conn.execute(
        "UPDATE orders SET status = 'COLLECTED', collected_at = ? WHERE order_id = ? AND status = 'PICKUP_AUTHORIZED'",
        (iso(now_utc()), order_id))
    if done.rowcount != 1:
        raise ApiError(409, "Order is not in an authorized state", collected=False)
    conn.execute(
        "UPDATE boxes SET status = 'AVAILABLE', order_id = NULL, display_mode = ?, lock_state = 'UNLOCKED' "
        "WHERE box_id = ?", (DISPLAY_MODE["AVAILABLE"], box_id))
    log.info("%s %s COLLECTED, box AVAILABLE", box_id, order_id)
    next_order = next((o for b, o in allocate_boxes(conn) if b == box_id), None)
    return {"collected": True, "box_id": box_id, "order_id": order_id, "next_order_id": next_order}


# ----------------------------------------------------------------------- demo helpers

def courier_orders(conn) -> list:
    """DEMO ONLY: assignments with their pickup codes, for the simulated courier dashboard."""
    rows = conn.execute(
        "SELECT o.order_id, o.platform, o.customer_display_name, o.box_id, o.status, "
        "       p.code_nonce, p.expires_at, p.used_at "
        "FROM orders o LEFT JOIN pickup_credentials p ON p.order_id = o.order_id "
        "WHERE o.status IN ('PREPARING','READY','PICKUP_AUTHORIZED') ORDER BY o.box_id, o.seq").fetchall()
    out = []
    for r in rows:
        has_code = r["code_nonce"] is not None
        out.append({
            "order_id": r["order_id"],
            "platform": r["platform"],
            "customer_display_name": r["customer_display_name"],
            "box_id": r["box_id"],
            "status": r["status"],
            "pickup_code": derive_code(r["order_id"], r["code_nonce"]) if has_code else None,
            "code_expires_at": r["expires_at"],
            "code_used": bool(r["used_at"]) if has_code else None,
        })
    return out


def reset_all(conn) -> None:
    """Whole-system reset for rehearsals: wipes orders and pickup codes, frees every box.
    Boxes and registered staff cards are kept."""
    conn.execute("DELETE FROM pickup_credentials")
    conn.execute("DELETE FROM orders")
    conn.execute("UPDATE boxes SET status = 'AVAILABLE', order_id = NULL, display_mode = 'IDLE', "
                 "lock_state = 'UNLOCKED'")
    log.info("Demo reset: all orders cleared, all boxes AVAILABLE")


def demo_seed_orders(now: datetime) -> list:
    """Six orders with deliberately different latest-start times (due - prep, minutes from now):
    UE-201 +10, UE-202 +14, GH-301 +15, DD-101 +18, DD-102 +37, DD-103 +50. UE-202 arrives last
    but is short on time, so it jumps the queue; arrival order alone would get this wrong."""
    def o(order_id, platform, name, items, prep, due_in, minutes_ago):
        return {"order_id": order_id, "platform": platform, "customer_display_name": name,
                "items": [{"name": n, "quantity": q} for n, q in items], "estimated_prep_minutes": prep,
                "pickup_due_at": now + timedelta(minutes=due_in), "created_at": now - timedelta(minutes=minutes_ago)}
    return [
        o("DD-101", "DoorDash", "Alex M.", [("Veg Burger", 2), ("Fries", 1)], 12, 30, 25),
        o("DD-102", "DoorDash", "Priya S.", [("Chicken Wrap", 1), ("Lemonade", 2)], 8, 45, 20),
        o("UE-201", "Uber Eats", "Jordan K.", [("Pad Thai", 1), ("Spring Roll", 2)], 15, 25, 18),
        o("GH-301", "Grubhub", "Sam R.", [("Margherita Pizza", 1)], 20, 35, 12),
        o("DD-103", "DoorDash", "Taylor B.", [("Burrito Bowl", 2), ("Chips", 1)], 10, 60, 8),
        o("UE-202", "Uber Eats", "Morgan L.", [("Sushi Roll", 3)], 6, 20, 3),
    ]


def seed_demo_orders(conn) -> list:
    """Insert the six demo orders (skipping any already present) as one batch, then allocate,
    so the first two boxes are filled by priority rather than by arrival order."""
    existing = {r["order_id"] for r in conn.execute("SELECT order_id FROM orders")}
    ids = ingest_orders(conn, [o for o in demo_seed_orders(now_utc()) if o["order_id"] not in existing])
    allocate_boxes(conn)
    return ids
