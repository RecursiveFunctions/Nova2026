#!/usr/bin/env python3
"""End-to-end smoke test for the Smart Pickup Box backend (standard library only).

    python smoke_test.py                                   # http://127.0.0.1:8000
    python smoke_test.py --base-url http://192.168.1.50:8000 --demo-key change-me

WARNING: calls POST /demo/reset before and after the run, which wipes all orders.
Needs the default seed data: BOX-01, BOX-02 and staff card STAFF-TAG-01.
Use 127.0.0.1 rather than localhost on Windows: localhost tries IPv6 first and adds ~1 s per request.
Exit code 0 = everything passed.
"""
import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

PASSED, FAILED = [], []


class Api:
    def __init__(self, base_url: str, demo_key: str):
        self.base, self.demo_key = base_url.rstrip("/"), demo_key

    def call(self, method, path, body=None, demo=False):
        data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
        headers = {"Content-Type": "application/json"} if data else {}
        if demo and self.demo_key:
            headers["X-Demo-Key"] = self.demo_key
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw.decode("utf-8", "replace")


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok or not detail else f"\n          -> {detail}"))
    return ok


def section(title):
    print(f"\n{title}")


# One fixed clock for every order, so latest-start ties in the tests are exact.
BASE = datetime.now(timezone.utc).replace(microsecond=0)


def make_order(order_id, platform, due_in, prep, minutes_ago, items=None, name="Alex Morgan", **extra):
    """Order due `due_in` minutes from BASE taking `prep` minutes: latest start = BASE + due_in - prep."""
    return {"order_id": order_id, "platform": platform, "customer_display_name": name,
            "items": items or [{"name": "Veg Burger", "quantity": 2}, {"name": "Fries", "quantity": 1}],
            "estimated_prep_minutes": prep, "pickup_due_at": (BASE + timedelta(minutes=due_in)).isoformat(),
            "created_at": (BASE - timedelta(minutes=minutes_ago)).isoformat(), **extra}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--demo-key", default="", help="X-Demo-Key (omit if the server runs without DEMO_API_KEY and you are on the same machine)")
    ap.add_argument("--cooldown", type=float, default=1.0, help="server FAILED_ATTEMPT_COOLDOWN_SECONDS (0 skips the 429 check)")
    args = ap.parse_args()
    api = Api(args.base_url, args.demo_key)

    try:
        status, _ = api.call("GET", "/health")
    except OSError as err:
        sys.exit(f"Cannot reach {args.base_url}: {err}")
    if status != 200:
        sys.exit(f"{args.base_url}/health returned {status}")

    def reset():
        return api.call("POST", "/demo/reset", demo=True)

    def box(box_id):
        return api.call("GET", f"/boxes/{box_id}")[1]

    def orders():
        return {o["order_id"]: o for o in api.call("GET", "/orders")[1]}

    def code_for(order_id):
        for row in api.call("GET", "/demo/courier-orders", demo=True)[1]:
            if row["order_id"] == order_id:
                return row["pickup_code"]
        return None

    def wrong_code(real):
        return "000000" if real != "000000" else "111111"

    section("Setup")
    status, body = reset()
    if not check("POST /demo/reset works", status == 200, f"{status} {body} (is X-Demo-Key right?)"):
        sys.exit(1)
    s, b = api.call("POST", "/boxes/BOX-01/staff-confirm", {"rfid_uid": "STAFF-TAG-01"})
    check("staff tap on an idle box (nothing preparing) -> 409, no state change", s == 409 and box("BOX-01")["status"] == "AVAILABLE", f"{s} {b}")

    # ---- T1 / T3: ingest, one ledger, two boxes
    section("T1/T3  Ingest orders from several platforms; 2 free boxes take exactly 2")
    s1, o1 = api.call("POST", "/orders", make_order("T-1", "DoorDash", 60, 12, 30))
    s2, o2 = api.call("POST", "/orders", make_order("T-2", "doordash", 50, 10, 29, items=[{"name": "Chicken Wrap", "quantity": 1}], name="Priya Shah"))
    check("order 1 created (201)", s1 == 201, f"{s1} {o1}")
    check("latest_start_at = pickup_due_at - estimated_prep_minutes",
          s1 == 201 and datetime.fromisoformat(o1["latest_start_at"]) == BASE + timedelta(minutes=48), str(o1))
    check("first free box takes the first order", s1 == 201 and o1["status"] == "PREPARING" and o1["box_id"] == "BOX-01", str(o1))
    check("second order goes to the second box", s2 == 201 and o2["status"] == "PREPARING" and o2["box_id"] == "BOX-02", str(o2))
    check("platform names are normalised ('doordash' -> 'DoorDash')", s2 == 201 and o2["platform"] == "DoorDash", str(o2))
    check("customer name is abbreviated ('Priya Shah' -> 'Priya S.')", s2 == 201 and o2["customer_display_name"] == "Priya S.", str(o2))

    # latest start (minutes from BASE): T-3 +50, T-4 +10, T-5 +20, T-6 +10 (newer than T-4), T-7 +75
    for o in [make_order("T-3", "DoorDash", 60, 10, 10), make_order("T-4", "uber eats", 30, 20, 9),
              make_order("T-5", "Uber Eats", 25, 5, 20), make_order("T-6", "Grubhub", 40, 30, 5),
              make_order("T-7", "DoorDash", 90, 15, 3)]:
        api.call("POST", "/orders", o)
    ledger = orders()
    check("all 7 orders from 3 platforms are in one ledger", len(ledger) == 7 and {o["platform"] for o in ledger.values()} == {"DoorDash", "Uber Eats", "Grubhub"}, str(sorted(ledger)))
    check("exactly 2 active assignments, 5 queued",
          sum(o["status"] == "PREPARING" for o in ledger.values()) == 2 and sum(o["status"] == "QUEUED" for o in ledger.values()) == 5)

    # ---- T2: priority = earliest latest-start (due - prep), then oldest
    section("T2  Queue priority: earliest latest-start (due - prep), then creation time")
    pos = {oid: o["queue_position"] for oid, o in ledger.items() if o["status"] == "QUEUED"}
    expected = {"T-4": 1, "T-6": 2, "T-5": 3, "T-3": 4, "T-7": 5}
    check("T-6 (due later, 30 min prep) beats T-5 (due sooner, 5 min prep); tie T-4/T-6 -> older T-4 first",
          pos == expected, f"got {dict(sorted(pos.items(), key=lambda kv: kv[1]))}")

    # ---- T4: PREPARING screen
    section("T4  PREPARING screen shows only items and quantities")
    v = box("BOX-01")
    check("status PREPARING with items", v.get("status") == "PREPARING" and v.get("items") == [{"name": "Veg Burger", "quantity": 2}, {"name": "Fries", "quantity": 1}], str(v))
    leaked = {"order_id", "customer_display_name", "platform", "pickup_code", "summary", "pickup_due_at",
              "estimated_prep_minutes", "latest_start_at"} & set(v)
    check("no customer, platform, order ID, pickup time or code", not leaked, f"leaked keys: {leaked}")

    # ---- validation and errors
    section("Validation and errors")
    check("duplicate order_id -> 409", api.call("POST", "/orders", make_order("T-1", "DoorDash", 30, 5, 1))[0] == 409)
    for field in ("estimated_prep_minutes", "pickup_due_at"):
        missing = make_order("T-M", "DoorDash", 30, 5, 1)
        del missing[field]
        check(f"missing {field} -> 422", api.call("POST", "/orders", missing)[0] == 422)
    naive = make_order("T-X", "DoorDash", 30, 5, 1)
    naive["created_at"] = "2026-11-07T13:00:00"
    check("timestamp without UTC offset -> 422", api.call("POST", "/orders", naive)[0] == 422)
    check("empty items -> 422", api.call("POST", "/orders", {**make_order("T-Y", "DoorDash", 30, 5, 1), "items": []})[0] == 422)
    check("unknown box -> 404", api.call("GET", "/boxes/BOX-99")[0] == 404)
    check("/demo/* without the key is refused (skipped if the server has no key)",
          not args.demo_key or api.call("GET", "/demo/courier-orders")[0] == 403)

    # ---- T6 / T5 / T7 / T13: staff RFID
    section("T6  Unknown staff RFID")
    s, b = api.call("POST", "/boxes/BOX-01/staff-confirm", {"rfid_uid": "NOT-A-STAFF-TAG"})
    check("rejected with an error", s == 403 and b.get("confirmed") is False, f"{s} {b}")
    check("box did not change", box("BOX-01")["status"] == "PREPARING")

    section("T5/T7/T13  Registered staff RFID -> READY, pickup details, duplicate tap")
    s, b = api.call("POST", "/boxes/BOX-01/staff-confirm", {"rfid_uid": "STAFF-TAG-01"})
    check("registered tap -> 200 confirmed, READY, not a duplicate", s == 200 and b.get("confirmed") is True and b.get("already_confirmed") is False and b.get("status") == "READY", f"{s} {b}")
    v = box("BOX-01")
    check("BOX-01 is READY and LOCKED", v.get("status") == "READY" and v.get("lock_state") == "LOCKED", str(v))
    check("READY screen: order ID, abbreviated name, summary",
          v.get("order_id") == "T-1" and v.get("customer_display_name") == "Alex M." and v.get("summary") == "2 Veg Burgers · 1 Fries", str(v))
    check("READY screen has no pickup code", "pickup_code" not in v and "items" not in v)
    code1 = code_for("T-1")
    check("courier dashboard shows a 6-digit code", bool(code1) and len(code1) == 6 and code1.isdigit(), str(code1))
    s, b = api.call("POST", "/boxes/BOX-01/staff-confirm", {"rfid_uid": "staff-tag-01"})
    check("second tap -> 200 'already_confirmed', no new state", s == 200 and b.get("already_confirmed") is True, f"{s} {b}")
    check("second tap did not issue a new code", code_for("T-1") == code1)
    check("staff-confirm response contains no pickup code", "pickup_code" not in b and code1 not in json.dumps(b))
    check("BOX-02 is still PREPARING (other box unaffected)", box("BOX-02")["status"] == "PREPARING")

    # ---- T8: NFC page
    section("T8  NFC tag URL")
    s, page = api.call("GET", "/pickup/BOX-01")
    check("GET /pickup/BOX-01 serves the verification page", s == 200 and isinstance(page, str) and "BOX-01" in page and "verify-pickup" in page)
    check("page does not contain the code", not isinstance(page, str) or code1 not in page)
    check("GET /pickup/BOX-99 -> 404", api.call("GET", "/pickup/BOX-99")[0] == 404)

    # ---- T9: wrong code
    section("T9  Wrong code")
    sent = time.monotonic()
    s, b = api.call("POST", "/boxes/BOX-01/verify-pickup", {"pickup_code": wrong_code(code1)})
    check("denied (403) with authorized=false", s == 403 and b.get("authorized") is False, f"{s} {b}")
    v = box("BOX-01")
    check("box stays READY/LOCKED, order not authorized or collected",
          v["status"] == "READY" and v["lock_state"] == "LOCKED" and orders()["T-1"]["status"] == "READY")
    if args.cooldown > 0:
        s, b = api.call("POST", "/boxes/BOX-01/verify-pickup", {"pickup_code": wrong_code(code1)})
        if time.monotonic() - sent < args.cooldown:
            check("an immediate retry is throttled (429)", s == 429 and b.get("authorized") is False, f"{s} {b}")
        else:
            print("  SKIP  429 throttle check: requests are slower than the cooldown (try 127.0.0.1)")
        time.sleep(args.cooldown + 0.3)
    check("garbage code -> denied, no crash", api.call("POST", "/boxes/BOX-01/verify-pickup", {"pickup_code": "abc"})[0] == 403)
    time.sleep(args.cooldown + 0.3)

    section("Wrong box: a valid code only works on its own box")
    api.call("POST", "/boxes/BOX-02/staff-confirm", {"rfid_uid": "STAFF-TAG-01"})
    code2 = code_for("T-2")
    s, b = api.call("POST", "/boxes/BOX-02/verify-pickup", {"pickup_code": code1})
    check("BOX-01's code is refused on BOX-02", s in (403, 409) and b.get("authorized") is False, f"{s} {b}")
    check("BOX-02 unchanged", box("BOX-02")["status"] == "READY")
    time.sleep(args.cooldown + 0.3)

    # ---- T10: valid code
    section("T10  Valid code")
    s, b = api.call("POST", "/boxes/BOX-01/verify-pickup", {"pickup_code": code1})
    check("authorized, unlock=true", s == 200 and b == {"authorized": True, "order_id": "T-1", "unlock": True}, f"{s} {b}")
    v = box("BOX-01")
    check("box UNLOCKED, authorized screen", v["status"] == "UNLOCKED" and v["lock_state"] == "UNLOCKED" and v["display_mode"] == "AUTHORIZED", str(v))
    check("order is PICKUP_AUTHORIZED, not COLLECTED yet", orders()["T-1"]["status"] == "PICKUP_AUTHORIZED")

    # ---- T11: reuse
    section("T11  Reuse of a redeemed code")
    s, b = api.call("POST", "/boxes/BOX-01/verify-pickup", {"pickup_code": code1})
    check("rejected", s in (403, 409) and b.get("authorized") is False, f"{s} {b}")
    check("state unchanged", box("BOX-01")["status"] == "UNLOCKED" and orders()["T-1"]["status"] == "PICKUP_AUTHORIZED")

    # ---- T14 + T12
    section("T14  Handoff is never assumed")
    s, b = api.call("POST", "/boxes/BOX-02/complete-pickup")
    check("complete-pickup on a box that is not authorized -> 409", s == 409 and b.get("collected") is False, f"{s} {b}")
    check("that order is not marked collected", orders()["T-2"]["status"] == "READY" and box("BOX-02")["status"] == "READY")

    section("T12  Complete pickup: box freed and refilled automatically")
    s, b = api.call("POST", "/boxes/BOX-01/complete-pickup")
    check("collected, next queued order assigned (T-4 per the projected queue)", s == 200 and b.get("collected") is True and b.get("next_order_id") == "T-4", f"{s} {b}")
    v, led = box("BOX-01"), orders()
    check("BOX-01 is PREPARING again with the next order's items",
          v["status"] == "PREPARING" and v["lock_state"] == "UNLOCKED" and v.get("items") == [{"name": "Veg Burger", "quantity": 2}, {"name": "Fries", "quantity": 1}], str(v))
    check("T-1 COLLECTED, T-4 PREPARING in BOX-01", led["T-1"]["status"] == "COLLECTED" and led["T-4"]["status"] == "PREPARING" and led["T-4"]["box_id"] == "BOX-01")
    check("second complete-pickup is refused (no double collection)", api.call("POST", "/boxes/BOX-01/complete-pickup")[0] == 409)

    section("Second cycle on the other box (T-2 -> T-6), and old codes stay dead")
    s, b = api.call("POST", "/boxes/BOX-02/verify-pickup", {"pickup_code": code2})
    check("T-2 authorized with its own code", s == 200 and b.get("order_id") == "T-2", f"{s} {b}")
    s, b = api.call("POST", "/boxes/BOX-02/complete-pickup")
    check("collected, next is T-6 (next earliest latest-start)", s == 200 and b.get("next_order_id") == "T-6", f"{s} {b}")
    api.call("POST", "/boxes/BOX-01/staff-confirm", {"rfid_uid": "STAFF-TAG-01"})
    s, b = api.call("POST", "/boxes/BOX-01/verify-pickup", {"pickup_code": code1})
    check("T-1's old code is refused on the reused BOX-01 (now holding T-4)", s == 403 and b.get("authorized") is False, f"{s} {b}")
    check("BOX-01 stays READY for T-4", box("BOX-01")["status"] == "READY" and box("BOX-01")["order_id"] == "T-4")

    # ---- demo seed
    section("Demo seed: six orders from three platforms, boxes filled by priority")
    reset()
    s, b = api.call("POST", "/demo/seed", demo=True)
    check("seed works", s == 200 and len(b.get("seeded_order_ids", [])) == 6, f"{s} {str(b)[:200]}")
    led = orders()
    check("UE-201 and UE-202 (earliest latest-start, though UE-202 arrived last) got the boxes",
          led["UE-201"]["box_id"] == "BOX-01" and led["UE-202"]["box_id"] == "BOX-02", f"{led['UE-201']['box_id']}, {led['UE-202']['box_id']}")
    pos = {oid: o["queue_position"] for oid, o in led.items() if o["status"] == "QUEUED"}
    check("queue: GH-301, DD-101, DD-102, DD-103", pos == {"GH-301": 1, "DD-101": 2, "DD-102": 3, "DD-103": 4}, str(pos))

    # ---- concurrency
    section("Concurrency (rule 6): simultaneous requests never double-assign")
    reset()
    platforms = ["DoorDash", "Uber Eats", "Grubhub"]
    codes = []
    threads = [threading.Thread(target=lambda p=make_order(f"C-{i:02d}", platforms[i % 3], 30 + i, 10, 15 - i): codes.append(api.call("POST", "/orders", p)[0])) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("12 parallel POST /orders all succeed", codes.count(201) == 12, str(codes))
    led = orders()
    prep = [o for o in led.values() if o["status"] == "PREPARING"]
    boxes = {b["box_id"]: b for b in api.call("GET", "/boxes")[1]}
    check("exactly 2 PREPARING, 10 QUEUED", len(prep) == 2 and sum(o["status"] == "QUEUED" for o in led.values()) == 10, str(len(prep)))
    check("the two orders are in two different boxes, and the boxes agree",
          len({o["box_id"] for o in prep}) == 2 and all(boxes[o["box_id"]]["order_id"] == o["order_id"] for o in prep), str(boxes))

    results = []
    taps = [threading.Thread(target=lambda: results.append(api.call("POST", "/boxes/BOX-01/staff-confirm", {"rfid_uid": "STAFF-TAG-01"}))) for _ in range(4)]
    for t in taps:
        t.start()
    for t in taps:
        t.join()
    check("4 simultaneous RFID taps: all 200, exactly one real transition", all(s == 200 for s, _ in results) and sum(1 for _, b in results if b.get("already_confirmed") is False) == 1, str(results))
    first = code_for(prep[0]["order_id"]) if boxes["BOX-01"]["order_id"] == prep[0]["order_id"] else code_for(prep[1]["order_id"])
    check("only one pickup code exists afterwards", first is not None and code_for(boxes["BOX-01"]["order_id"]) == first)

    section("Cleanup")
    check("final reset", reset()[0] == 200)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("Failed: " + "; ".join(FAILED))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
