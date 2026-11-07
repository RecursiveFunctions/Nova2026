# Smart Pickup Box: backend (Person A)

FastAPI + SQLite. The backend is the single source of truth for orders and boxes.
Business rules live in `logic.py` (no web imports); `main.py` is only routing.

## Run

Keep the database **outside OneDrive** (set `DATABASE_PATH` in `.env`): OneDrive syncing SQLite's WAL
files can cause lock errors or corruption. A database from the old price-based scheduler is cleared of
orders automatically on startup.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then edit DEMO_API_KEY etc.
uvicorn main:app --host 0.0.0.0 --port 8000
```

- Interactive docs: `http://<laptop-LAN-IP>:8000/docs`
- Health check: `GET /health`
- Check everything end to end (wipes orders, needs the server running):
  `python smoke_test.py --demo-key change-me` (defaults to `http://127.0.0.1:8000`; on Windows avoid
  `localhost`, which adds ~1 s per request and makes the 429 check skip)
- Rehearsal reset with the six demo orders: `curl -X POST -H "X-Demo-Key: change-me" "http://localhost:8000/demo/reset?seed=true"`
- NFC tag URL for the no-build fallback page: `http://<laptop-LAN-IP>:8000/pickup/BOX-01`

## Changes to the contract B / C / D need to know about

| Change | Why / what to do |
|---|---|
| `POST /orders` follows the tech sheet: `estimated_prep_minutes` (1-240) and `pickup_due_at` (with UTC offset) are **required**. `order_id` is optional (generated if missing). `total_price` is no longer used (ignored if sent). | Queue priority is the sheet's latest safe start. |
| `GET /boxes/{id}` returns `display_mode` and `lock_state` in every state, and has a 4th state `UNLOCKED` (shows `order_id`, `customer_display_name`, `summary`). | **C** drives the lock from `lock_state`; **B** shows the "authorized" screen for `UNLOCKED`. |
| `display_mode` values: `IDLE`, `PREPARING`, `READY`, `AUTHORIZED`. | Mirrors box status. |
| `verify-pickup` can also answer **429** (retry shortly). | **B:** treat any non-200 as "not authorized"; read `error`. |
| `GET /orders` adds `latest_start_at` (= `pickup_due_at - estimated_prep_minutes`) and `queue_position` (1 = next to get a box; null if not queued). | For the "calculated priority order" demo step. |
| New: `GET /health`, `POST /demo/seed`, `POST /demo/staff`, `POST /demo/reset?seed=true`, fallback page at `GET /pickup/{box_id}`. | Convenience. |

Every backend error is `{"error": "..."}` (plus `authorized`/`confirmed`/`collected: false` where relevant).
Request validation errors are FastAPI's standard 422 `{"detail": [...]}`.

## API

| Method | Endpoint | Notes |
|---|---|---|
| POST | `/orders` | 201 + order. Normalises platform name and abbreviates the customer name. If a box is free the order is assigned immediately. 409 on duplicate `order_id`. |
| GET | `/orders?status=` | Ledger, oldest first. |
| GET | `/boxes` | Box records: `box_id, status, order_id, display_mode, lock_state`. |
| GET | `/boxes/{box_id}` | Display-safe view. `PREPARING`: `items` only. `READY`/`UNLOCKED`: `order_id, customer_display_name, summary`. Never a pickup code. Poll every second. |
| POST | `/boxes/{box_id}/staff-confirm` | `{"rfid_uid": "..."}`. 200 confirmed (duplicate tap = 200, `already_confirmed: true`, nothing changes); 403 unknown card; 409 nothing being prepared. Unknown UIDs are printed in the server log with the command to register them. |
| POST | `/boxes/{box_id}/verify-pickup` | `{"pickup_code": "583216"}`. 200 `{"authorized": true, "order_id", "unlock": true}`; 403 wrong/expired/used; 409 box not READY; 429 retry shortly. Denials never change order or box state. |
| POST | `/boxes/{box_id}/complete-pickup` | Bridge or supervised button. Only valid in `UNLOCKED`; marks `COLLECTED`, frees the box and assigns the next queued order (`next_order_id`). 409 otherwise. |
| GET | `/pickup/{box_id}` | Minimal phone page (code entry). B's React page can replace it. |
| GET | `/demo/courier-orders` | **Demo only.** Assignments plus pickup codes. |
| POST | `/demo/reset` | **Demo only.** Whole-system reset (`?seed=true` also inserts the demo orders). |
| POST | `/demo/seed` | **Demo only.** Six orders from three platforms inserted as one batch. |
| POST | `/demo/staff` | **Demo only.** `{"rfid_uid": "...", "staff_name": "..."}`. |

`/demo/*` needs the header `X-Demo-Key: <DEMO_API_KEY>` (or, with no key configured, a request from the API machine itself:
the caller and every `X-Forwarded-For` hop must be loopback, so the frontend's dev-server proxy does not count as local).
The frontend's `/courier` page is the courier dashboard built on these endpoints.

## States

```
Order: QUEUED -> PREPARING -> READY -> PICKUP_AUTHORIZED -> COLLECTED
Box:   AVAILABLE -> PREPARING -> READY -> UNLOCKED -> AVAILABLE
```

| Box status | `lock_state` | `display_mode` | What the screen shows |
|---|---|---|---|
| AVAILABLE | UNLOCKED | IDLE | idle |
| PREPARING | UNLOCKED | PREPARING | items and quantities only |
| READY | **LOCKED** | READY | order ID, abbreviated name, summary |
| UNLOCKED | UNLOCKED | AUTHORIZED | "pickup authorized" |

Hardware bridge: poll `GET /boxes/{id}`; engage the lock when `lock_state` is `LOCKED`, release it when it becomes `UNLOCKED`.
Call `complete-pickup` only after the door/sensor confirms removal (or from the supervised button). Nothing becomes
`COLLECTED` because a code was correct.

## Scheduling (who gets the next free box)

A scheduling algorithm (no model), as in the tech sheet:

1. **Latest safe start:** smallest `pickup_due_at - estimated_prep_minutes` first (stored as `latest_start_at`).
2. **Tie-break:** oldest `created_at` first.

`/demo/seed` is built so the last order to arrive (UE-202, short on time) jumps the queue.

Allocation runs inside one SQLite `BEGIN IMMEDIATE` transaction, so simultaneous requests cannot double-assign. A unique
index also stops two active orders sharing a box. When orders arrive one at a time, a free box takes whatever is there;
priority decides among orders that are waiting together (use `/demo/seed` to show it). Change the rule in `pick_next()`.

## Pickup codes

- Issued when staff confirm (`READY`), 6 digits, expire after `PICKUP_CODE_TTL_MINUTES` (default 15), one use.
- The database stores only a nonce and an HMAC of the code, never the code. The demo dashboard recomputes it with
  `PICKUP_CODE_SECRET`, which is not in the database (auto-generated to `data/.pickup_secret` if unset).
- Attempts are unlimited, but after a wrong code the next attempt on that order gets 429 for
  `FAILED_ATTEMPT_COOLDOWN_SECONDS`, which caps guessing at about 1 per second.
- An expired code cannot be re-issued; use `/demo/reset` or raise the TTL for rehearsals.

## Known limits (be upfront in the demo)

- Without a lock, this is logical verification only; it cannot stop physical theft.
- Codes are demo credentials issued through the simulated courier dashboard; they do not prove real courier identity.
- `PICKUP_AUTHORIZED` does not time out by itself; the bridge can re-lock, and `/demo/reset` clears a stuck box.
- Plain HTTP is fine on an isolated Wi-Fi demo; use HTTPS for anything credential-bearing beyond that.
