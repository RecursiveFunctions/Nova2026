# Smart Pickup Box: frontend (Person B)

React + Vite. Box screens, courier verification page and the mock order simulator.
The backend (`../backend`) is the single source of truth; every page just polls it.

## Run

Start the backend first (`uvicorn main:app --host 0.0.0.0 --port 8000` in `../backend`), then:

```bash
cd frontend
npm install
npm run dev
```

The dev server listens on all interfaces at port 5173 and forwards `/orders`, `/boxes`, `/health` and
`/demo` to the backend (`API_PROXY_TARGET`, default `http://127.0.0.1:8000`). Browsers and phones therefore
need only one address, `http://<laptop-LAN-IP>:5173`, and there is no CORS to configure.

## Pages

| URL | Who looks at it | What it does |
|---|---|---|
| `/screen/BOX-01`, `/screen/BOX-02` | The screen on each box | Polls `GET /boxes/{id}` every second. **Available**, **Preparing** (items and quantities only), **Ready** (order ID, abbreviated name, summary), **Pickup authorized**. Keeps the last state and shows "Connection lost" if the API is unreachable. Never shows a pickup code. |
| `/pickup/BOX-01` | Courier's phone (NFC tag URL) | Asks for the 6-digit one-time code and calls `POST /boxes/{id}/verify-pickup`. Only a 200 shows "authorized"; anything else, including network errors, shows **Not authorized**. |
| `/simulator` | Demo operator | Mock order source (platform, customer, items, prep minutes, due-in minutes, or "Random order") posting to `POST /orders`; the unified ledger with queue position and latest start; per-box **Simulate staff RFID tap** and **Complete pickup (supervised)** buttons. |
| `/courier` | Demo operator (Person D) only | **Demo only, shows pickup codes.** One card per boxed order: platform, order, box, one-time code with expiry countdown / used / expired state. Reset & seed buttons, staff RFID card registration, and an all-orders list with status counts. |
| `/` | Anyone | Links to every page for every box. |

## NFC tags

Write `http://<laptop-LAN-IP>:5173/pickup/BOX-01` (and `.../BOX-02`). `localhost` does not work from a
phone. Allow port 5173 through the Windows firewall on the demo network. If a tag cannot be written,
print a QR code with the same URL.

## Notes

- `/courier` access: on the API laptop with no `DEMO_API_KEY`, it just works. From any other device
  (or whenever the backend sets `DEMO_API_KEY`), type the key into the page; it is kept for the browser
  tab only. The proxy sends `X-Forwarded-For`, and the backend refuses keyless `/demo/*` calls unless
  every hop is this machine, so the proxy does not open the codes to the Wi-Fi.
- Reset buttons ask for confirmation: they delete every order and code.
- The simulator sends `pickup_due_at` as UTC (`...Z`), which satisfies the backend's offset requirement.
- Set `VITE_DEMO_STAFF_UID` in `.env` to pre-fill the staff UID used by the simulated tap button.
- `npm run build && npm run preview` serves the production build on the same port with the same proxy.
