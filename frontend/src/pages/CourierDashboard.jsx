import { useState } from "react";
import { api, formatTime, summarize, usePoll } from "../api.js";

// DEMO ONLY (Person D): stands in for the delivery platforms' courier apps. It shows the one-time
// pickup codes, so it must never be opened on a box screen or projected during the "public" part
// of the demo. Every /demo/* call carries X-Demo-Key when one is entered (needed whenever the
// backend has DEMO_API_KEY set, or when this page is opened from another device).
const KEY_STORAGE = "pickupbox.demoKey";

function loadKey() {
  try {
    return sessionStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

function saveKey(value) {
  try {
    sessionStorage.setItem(KEY_STORAGE, value);
  } catch {
    /* storage blocked: the key just isn't remembered */
  }
}

export default function CourierDashboard() {
  const [key, setKey] = useState(loadKey);
  const headers = key ? { "X-Demo-Key": key } : undefined;
  const demo = (method, path, body) => api(method, path, body, headers);

  const couriers = usePoll(() => demo("GET", "/demo/courier-orders"), 1500, `couriers:${key}`);
  const ledger = usePoll(() => api("GET", "/orders"), 2000, "ledger");
  const refreshAll = () => { couriers.reload(); ledger.reload(); };
  const denied = couriers.error?.status === 403;

  return (
    <main className="page wide">
      <header className="sim-header">
        <h1>Courier dashboard</h1>
        <span>
          <a href="/simulator">Simulator</a> · <a href="/">All links</a>
        </span>
      </header>
      <p className="warn">
        Demo only: this page shows pickup codes. Never open it on a box screen.
      </p>

      <section className="card">
        <label className="small">
          Demo key (X-Demo-Key){" "}
          <span className="muted">— needed if the backend sets DEMO_API_KEY or you are not on the API laptop</span>
          <input type="password" value={key} autoComplete="off" placeholder="leave empty on the API laptop with no key set"
            onChange={(e) => { setKey(e.target.value); saveKey(e.target.value); }} />
        </label>
        {denied && <p className="error">{couriers.error.message}</p>}
      </section>

      <CourierAssignments couriers={couriers} />
      <div className="sim-grid">
        <DemoControls demo={demo} onChange={refreshAll} />
        <StaffCards demo={demo} />
      </div>
      <OrderList ledger={ledger} />
    </main>
  );
}

// ------------------------------------------------------------ assignments + codes

function CourierAssignments({ couriers }) {
  const rows = couriers.data || [];
  const now = Date.now();
  return (
    <section className="card">
      <div className="row space">
        <h2>Courier assignments</h2>
        <span className="muted small">Codes are issued when staff mark the order READY</span>
      </div>
      {couriers.error && couriers.error.status !== 403 && <p className="error">{couriers.error.message}</p>}
      {rows.length === 0 ? (
        <p className="muted">No orders are in a box right now.</p>
      ) : (
        <div className="courier-grid">
          {rows.map((r) => {
            const expiresIn = r.code_expires_at ? Math.round((new Date(r.code_expires_at) - now) / 1000) : null;
            const expired = expiresIn !== null && expiresIn <= 0;
            return (
              <div className={`courier-card state-${r.status.toLowerCase()}`} key={r.order_id}>
                <div className="row space">
                  <strong>{r.platform}</strong>
                  <span className={`pill status-${r.status.toLowerCase()}`}>{r.status}</span>
                </div>
                <p className="courier-order">{r.order_id} · {r.customer_display_name}</p>
                <p className="small muted">Go to <strong>{r.box_id}</strong></p>
                {r.pickup_code ? (
                  <>
                    <p className={`courier-code ${r.code_used || expired ? "dead" : ""}`}>{r.pickup_code}</p>
                    <p className="small">
                      {r.code_used
                        ? "Code used: pickup authorized"
                        : expired
                          ? "Code expired (use Reset to start over)"
                          : `Expires in ${formatCountdown(expiresIn)} (${formatTime(r.code_expires_at)})`}
                    </p>
                    {!r.code_used && !expired && (
                      <a className="small" href={`/pickup/${encodeURIComponent(r.box_id)}`} target="_blank" rel="noreferrer">
                        Open {r.box_id} pickup page
                      </a>
                    )}
                  </>
                ) : (
                  <p className="courier-code pending">Waiting for staff…</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function formatCountdown(seconds) {
  const m = Math.floor(seconds / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

// ------------------------------------------------------------------ reset / seed

function DemoControls({ demo, onChange }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function run(label, method, path, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await demo(method, path);
      const seeded = res.seeded_order_ids?.length ? ` · seeded ${res.seeded_order_ids.join(", ")}` : "";
      setMsg({ ok: true, text: `${label} done${seeded}` });
      onChange();
    } catch (err) {
      setMsg({ ok: false, text: err.message });
    } finally {
      setBusy(false);
    }
  }

  const wipe = "This deletes every order and pickup code and frees all boxes. Continue?";
  return (
    <section className="card">
      <h2>Demo data</h2>
      <div className="row wrap">
        <button className="btn primary" disabled={busy}
          onClick={() => run("Reset + seed", "POST", "/demo/reset?seed=true", wipe)}>
          Reset &amp; seed 6 orders
        </button>
        <button className="btn warn-btn" disabled={busy} onClick={() => run("Reset", "POST", "/demo/reset", wipe)}>
          Reset only
        </button>
        <button className="btn" disabled={busy} onClick={() => run("Seed", "POST", "/demo/seed")}>
          Add the 6 demo orders
        </button>
      </div>
      {msg && <p className={msg.ok ? "ok-text" : "error"}>{msg.text}</p>}
      <p className="muted small">Boxes and registered staff cards are kept on reset.</p>
    </section>
  );
}

// -------------------------------------------------------------- staff RFID cards

function StaffCards({ demo }) {
  const [uid, setUid] = useState("");
  const [name, setName] = useState("");
  const [msg, setMsg] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setMsg(null);
    try {
      const res = await demo("POST", "/demo/staff", { rfid_uid: uid.trim(), staff_name: name.trim() || null });
      setMsg({ ok: true, text: `Registered ${res.rfid_uid}` });
      setUid("");
      setName("");
    } catch (err) {
      setMsg({ ok: false, text: err.message });
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>Register a staff RFID card</h2>
      <p className="muted small">
        Tap an unknown card on the reader: the backend log prints its UID. Enter it here.
      </p>
      <div className="fields two">
        <label>
          RFID UID
          <input value={uid} onChange={(e) => setUid(e.target.value)} required maxLength={64} placeholder="04:A1:B2:C3" />
        </label>
        <label>
          Staff name <span className="muted">(optional)</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
        </label>
      </div>
      <button className="btn" type="submit" disabled={!uid.trim()}>Register card</button>
      {msg && <p className={msg.ok ? "ok-text" : "error"}>{msg.text}</p>}
    </form>
  );
}

// ---------------------------------------------------------------------- order list

function OrderList({ ledger }) {
  const rows = ledger.data || [];
  const counts = rows.reduce((acc, o) => ({ ...acc, [o.status]: (acc[o.status] || 0) + 1 }), {});
  return (
    <section className="card">
      <div className="row space">
        <h2>All orders</h2>
        <span className="muted small">
          {["QUEUED", "PREPARING", "READY", "PICKUP_AUTHORIZED", "COLLECTED"]
            .map((s) => `${s.toLowerCase().replace("_", " ")} ${counts[s] || 0}`).join(" · ")}
        </span>
      </div>
      {ledger.error && <p className="error">{ledger.error.message}</p>}
      {rows.length === 0 ? (
        <p className="muted">No orders yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>Order</th><th>Platform</th><th>Customer</th><th>Items</th><th>Latest start</th><th>Queue</th><th>Status</th><th>Box</th></tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <tr key={o.order_id} className={o.status === "COLLECTED" ? "dim" : ""}>
                  <td>{o.order_id}</td>
                  <td>{o.platform}</td>
                  <td>{o.customer_display_name}</td>
                  <td>{summarize(o.items)}</td>
                  <td>{formatTime(o.latest_start_at)}</td>
                  <td>{o.queue_position ?? ""}</td>
                  <td><span className={`pill status-${o.status.toLowerCase()}`}>{o.status}</span></td>
                  <td>{o.box_id || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
