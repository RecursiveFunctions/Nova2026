# Smart Pickup Box (DoorDash × Nova Hackathon)

Orders from mock delivery apps enter one ledger, are scheduled by latest safe start, shown on a box
screen while being prepared, marked ready by a staff RFID tap, and released only after the courier
enters an order-specific one-time code on the page opened by the box's NFC tag.

## Start everything (one command)

Needs Python 3.11+ and Node 18+.

```bash
powershell -ExecutionPolicy Bypass -File .\start.ps1     # Windows: opens two windows
./start.sh                                               # macOS / Linux: Ctrl+C stops both
```

First run installs the backend venv and the frontend packages. The script prints every URL with this
laptop's LAN IP. Before the demo, copy `backend/.env.example` to `backend/.env` and set at least
`DATABASE_PATH` (outside OneDrive/Dropbox) and, if the courier dashboard is used from another device,
`DEMO_API_KEY`.

## Network

| Port | Service | Who connects |
|---|---|---|
| 8000 | FastAPI backend (`backend/`) | Frontend proxy, hardware bridge, `/docs` |
| 5173 | Vite frontend (`frontend/`) | Box screens, courier phones, simulator, dashboard |

All devices on the same Wi-Fi. Allow both ports through the API laptop's firewall. Phones and NFC tags
use `http://<LAN-IP>:5173/...`, never `localhost`. Plain HTTP is for an isolated demo network only.

## Pages

| URL | Purpose | Owner |
|---|---|---|
| `/screen/BOX-01`, `/screen/BOX-02` | Box display (items only while preparing; pickup details when ready) | B |
| `/pickup/BOX-01`, `/pickup/BOX-02` | Courier code entry (NFC tag URL) | B |
| `/simulator` | Mock orders, unified ledger, simulated staff tap, supervised Complete pickup | B |
| `/courier` | **Demo only:** pickup codes, reset & seed, staff card registration | D |
| `:8000/docs` | Interactive API docs | A |

## Ownership

| Person | Area | Folder / branch |
|---|---|---|
| A | Backend: ledger, scheduler, allocator, state machine, pickup codes | `backend/` · `backend` |
| B | Box screens, courier page, order simulator | `frontend/` · `frontend` |
| C | Hardware bridge: RFID, display, lock, NFC tags | `hardware/` · `hardware` |
| D | Integration, tests, courier dashboard, demo | `integration` |

Work on your branch; merge into `main` only after `python backend/smoke_test.py` passes against a
running backend. A owns the API contract: do not rename fields or statuses without them.

## API contract (summary)

| Method | Endpoint | Notes |
|---|---|---|
| POST | `/orders` | `platform`, `customer_display_name`, `items[{name, quantity}]`, `estimated_prep_minutes`, `pickup_due_at` (with offset); `order_id` optional |
| GET | `/orders` | Ledger with `latest_start_at` and `queue_position` |
| GET | `/boxes`, `/boxes/{id}` | Box list; display-safe screen view (never a code) |
| POST | `/boxes/{id}/staff-confirm` | `{"rfid_uid": "..."}` PREPARING -> READY, issues the code |
| POST | `/boxes/{id}/verify-pickup` | `{"pickup_code": "123456"}` READY -> UNLOCKED on success only |
| POST | `/boxes/{id}/complete-pickup` | UNLOCKED -> AVAILABLE, next order assigned |
| GET/POST | `/demo/courier-orders`, `/demo/reset`, `/demo/seed`, `/demo/staff` | Demo only, `X-Demo-Key` or API laptop |

Full details: [backend/README.md](backend/README.md). Frontend: [frontend/README.md](frontend/README.md).
Hardware: [hardware/README.md](hardware/README.md).

## Testing

```bash
python backend/smoke_test.py --demo-key <DEMO_API_KEY>   # wipes orders; covers acceptance tests T1-T14
```

## Prototype boundaries (say these in the demo)

- Order data is simulated; codes are demo credentials, not real courier identity.
- Without a physical lock this is logical verification only.
- An expired code cannot be re-issued (use reset); `PICKUP_AUTHORIZED` has no timeout.
