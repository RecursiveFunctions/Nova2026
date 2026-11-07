# Smart Pickup Box (DoorDash × Nova Hackathon)

Delivery orders from mock apps land in one queue. The box closest to its deadline gets filled first.
The box screen shows the food while it is being prepared, staff tap their ID to mark it ready and lock
the latch, and the courier opens the box by typing a one-time code into the page behind the box's QR code.

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

## Folders

| Folder | What is in it |
|---|---|
| `backend/` | FastAPI + SQLite: the queue, the scheduler, the box states, the pickup codes |
| `frontend/` | React screens: box display, courier page, simulator, courier dashboard |
| `hardware/` | Raspberry Pi bridge: LCD, motor latch, QR codes |
| `display/` | The public online demo: backend + a simple box screen served from one port |
| `deploy/` | Hosting on our own machine: production plus a live preview per branch |
| `interface/` | Dead-end first draft of the customer page, kept for reference |

`start.sh` / `start.ps1` only run `backend/` and `frontend/`. `display/` and `deploy/` run on the demo
server instead; `interface/` is not run by anything.

## Network

| Port | What runs there |
|---|---|
| 8000 | Backend API (`backend/`), plus `/docs` |
| 5173 | React app (`frontend/`): box screens, courier phones, simulator, dashboard |
| 8081 | Public demo (`display/app.py`): API and box screen from one process, no CORS |
| 8090 | Preview router (`deploy/preview-router.py`): sends `/` to the demo and `/p/<branch>/` to that branch's preview |

For the on-site demo every device is on the same Wi-Fi. Open both ports in the laptop's firewall and put
`http://<LAN-IP>:5173/...` in the QR codes, never `localhost`. Plain HTTP is only for the isolated demo network.

## Pages

Open these on the React app (`http://<LAN-IP>:5173`):

| URL | What it is for | Owner |
|---|---|---|
| `/screen/BOX-01`, `/screen/BOX-02` | The screen on the box: food items while preparing, pickup details when ready | B |
| `/pickup/BOX-01`, `/pickup/BOX-02` | The page the QR code opens: staff mark ready, courier enters the code | B |
| `/simulator` | Create mock orders, watch the queue, press the fake hardware buttons | B |
| `/courier` | **Demo only:** read out pickup codes, reset and seed, register staff IDs | D |
| `/customer/<order-id>` | Customer side: confirm the food arrived, report a problem (UI only, nothing is saved) | B |
| anything else | Home page: links to every screen plus a live box table | B |

Two more on the backend (`http://<LAN-IP>:8000`): `/docs` for interactive API docs, and
`/pickup/BOX-01`, the same courier page with no build step, for when the React app is not running.

## Picking up an order

The screens and the hardware bridge only ever read `GET /boxes/{id}`, once per second. That response
decides what the screen shows and whether the latch is engaged:

| Box state | Latch | Screen shows |
|---|---|---|
| AVAILABLE | open | idle |
| PREPARING | open | food items and quantities, and nothing else: no name, no platform, no order ID |
| READY | locked | order ID, the customer's short name, an item summary |
| UNLOCKED | open | "pickup authorized" |

Step by step:

1. An order arrives (`POST /orders`) and joins the queue.
2. A free box takes the order that has the least slack: `pickup_due_at - estimated_prep_minutes`, so the
   order that must start soonest wins. Ties go to whoever queued first.
3. Staff tap their ID on the box (`staff-confirm`). The order becomes READY, the latch locks, and a
   6-digit code is created. The code is never sent to the box screen.
4. The courier opens the QR page and types the code (`verify-pickup`). Correct: the latch opens. Wrong,
   used, or expired: nothing changes. A wrong code means the next try on that order waits a second.
5. `complete-pickup` says the food physically left. Only now is the order COLLECTED, the box frees up,
   and the next order in the queue moves in. A correct code on its own never collects an order.

The code is single-use and expires after `PICKUP_CODE_TTL_MINUTES` (15 by default). The database only ever
holds a hash of it, so a stolen database file does not leak active codes; the courier dashboard
recalculates them from `PICKUP_CODE_SECRET`, which is stored separately.

## Configuration (`backend/.env`)

| Setting | Default | What it does |
|---|---|---|
| `DATABASE_PATH` | a file in `backend/data` | Must not be inside OneDrive/Dropbox, or SQLite locks up |
| `DEMO_API_KEY` | empty | With no key set, `/demo/*` only answers to the API laptop itself |
| `BOX_IDS` | `BOX-01,BOX-02` | Boxes created at startup |
| `STAFF_RFID_UIDS` | `STAFF-TAG-01` | Staff IDs that already work at startup |
| `PICKUP_CODE_TTL_MINUTES` | `15` | How long a pickup code stays valid |
| `FAILED_ATTEMPT_COOLDOWN_SECONDS` | `1` | Wait after a wrong code |
| `PICKUP_CODE_SECRET` | generated | Needed to show codes on the courier dashboard |
| `CORS_ORIGINS` | `*` | Narrow this down once the demo leaves the isolated network |

## API (summary)

| Method | Endpoint | Notes |
|---|---|---|
| POST | `/orders` | `platform`, `customer_display_name`, `items[{name, quantity}]`, `estimated_prep_minutes`, `pickup_due_at` (with offset); `order_id` optional |
| GET | `/orders` | The queue, with `latest_start_at` and `queue_position`; filter with `?status=` |
| GET | `/boxes`, `/boxes/{id}` | Box list; the screen view described above (never a code) |
| POST | `/boxes/{id}/staff-confirm` | `{"rfid_uid": "<staff ID>"}` (field name kept) PREPARING -> READY, issues the code |
| POST | `/boxes/{id}/verify-pickup` | `{"pickup_code": "123456"}` READY -> UNLOCKED on success only |
| POST | `/boxes/{id}/complete-pickup` | UNLOCKED -> AVAILABLE, next order assigned |
| GET | `/health` | Is the backend up? Used by the deploy scripts |
| GET | `/pickup/{box_id}` | No-build courier page, what the QR tag points at |
| GET/POST | `/demo/courier-orders`, `/demo/reset`, `/demo/seed`, `/demo/staff` | Demo only, needs `X-Demo-Key` or the API laptop |

Full details: [backend/README.md](backend/README.md). Frontend: [frontend/README.md](frontend/README.md).
Hardware: [hardware/README.md](hardware/README.md).

## Public demo and branch previews (`display/`, `deploy/`)

`https://novabox.recursivefunctions.dev/` runs without Vite. `display/app.py` loads the backend app, swaps
its JSON root page for `display/index.html`, and serves both from port 8081, so a phone can open the screen
and poll the API on the same origin. `display/serve.sh` puts it behind a Cloudflare tunnel
(`NOVABOX_HOSTNAME` selects the named tunnel).

`deploy/preview-router.py` on port 8090 splits traffic by path: `/` goes to the demo on 8081, and
`/p/<slug>/...` has its prefix removed and goes to the port that branch listens on, as listed in
`routes.json` (`SIGHUP` reloads it). `deploy-main.sh` restarts the demo and checks `/health`;
`deploy-preview.sh upsert|destroy` checks out a branch with its own `DATABASE_PATH` and serves it.
`install-host.sh` installs the systemd `--user` services. GitHub Actions (`deploy-main.yml`,
`deploy-preview.yml`) drive this on the self-hosted `nova-box` runner. Details: [deploy/README.md](deploy/README.md).

## Ownership

| Person | Area | Folder / branch |
|---|---|---|
| A | Backend: ledger, scheduler, allocator, state machine, pickup codes | `backend/` · `backend` |
| B | Box screens, courier page, order simulator | `frontend/` · `frontend` |
| C | Raspberry Pi bridge: 3.5" LCD, DC motor latch, QR codes | `hardware/` · `hardware` |
| D | Integration, tests, courier dashboard, demo | `integration` |

Work on your branch; merge into `main` only after `python backend/smoke_test.py` passes against a
running backend. A owns the API contract: do not rename fields or statuses without them.

## Testing

```bash
python backend/smoke_test.py --demo-key <DEMO_API_KEY>   # wipes orders; covers acceptance tests T1-T14
```

## Prototype boundaries (say these in the demo)

- Order data is simulated; codes are demo credentials, not real courier identity.
- Without a physical lock this is logical verification only.
- An expired code cannot be re-issued (use reset); `PICKUP_AUTHORIZED` has no timeout.
- The customer page only looks finished: confirming receipt and reporting a problem save nothing.