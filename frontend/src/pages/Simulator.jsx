import { useState } from "react";
import { api, boxPath, formatTime, summarize, usePoll } from "../api.js";

const PLATFORMS = ["DoorDash", "Uber Eats", "Grubhub", "Other"];
const MENU = ["Veg Burger", "Fries", "Chicken Wrap", "Lemonade", "Pad Thai", "Spring Roll",
  "Margherita Pizza", "Burrito Bowl", "Chips", "Sushi Roll", "Caesar Salad", "Iced Tea"];
const NAMES = ["Alex Morgan", "Priya Shah", "Jordan Kim", "Sam Rivera", "Taylor Brooks", "Morgan Lee",
  "Casey Nguyen", "Riley Patel"];
const STATUS_RANK = { QUEUED: 0, PREPARING: 1, READY: 2, PICKUP_AUTHORIZED: 3, COLLECTED: 4 };

const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
const randInt = (lo, hi) => lo + Math.floor(Math.random() * (hi - lo + 1));

function emptyForm() {
  return { platform: "DoorDash", otherPlatform: "", orderId: "", customer: "", prep: 12, dueIn: 30,
    items: [{ name: "", quantity: 1 }] };
}

function randomForm() {
  const names = [...MENU].sort(() => Math.random() - 0.5).slice(0, randInt(1, 3));
  return { ...emptyForm(), platform: pick(PLATFORMS.slice(0, 3)), customer: pick(NAMES),
    prep: randInt(5, 25), dueIn: randInt(15, 60), items: names.map((name) => ({ name, quantity: randInt(1, 3) })) };
}

export default function Simulator() {
  const ledger = usePoll(() => api("GET", "/orders"), 1500, "orders");
  const boxes = usePoll(() => api("GET", "/boxes"), 1000, "boxes");
  const refreshAll = () => { ledger.reload(); boxes.reload(); };

  return (
    <main className="page wide">
      <header className="sim-header">
        <h1>Order simulator</h1>
        <a href="/">All links</a>
      </header>
      <div className="sim-grid">
        <OrderForm onCreated={refreshAll} />
        <BoxPanel boxes={boxes} onChange={refreshAll} />
      </div>
      <Ledger ledger={ledger} />
    </main>
  );
}

// --------------------------------------------------------------------------- order form

function OrderForm({ onCreated }) {
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // {ok, text}

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setItem = (i, patch) => set({ items: form.items.map((it, j) => (j === i ? { ...it, ...patch } : it)) });

  const due = new Date(Date.now() + Number(form.dueIn || 0) * 60000);
  const latestStart = new Date(due.getTime() - Number(form.prep || 0) * 60000);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const platform = form.platform === "Other" ? form.otherPlatform.trim() : form.platform;
    const body = {
      platform,
      customer_display_name: form.customer.trim(),
      items: form.items.filter((i) => i.name.trim()).map((i) => ({ name: i.name.trim(), quantity: Number(i.quantity) })),
      estimated_prep_minutes: Number(form.prep),
      // Recomputed at submit time; toISOString() is UTC with a "Z" offset, as the backend requires.
      pickup_due_at: new Date(Date.now() + Number(form.dueIn) * 60000).toISOString(),
    };
    if (form.orderId.trim()) body.order_id = form.orderId.trim();
    try {
      const o = await api("POST", "/orders", body);
      const where = o.box_id ? `assigned to ${o.box_id}` : `queued at position ${o.queue_position}`;
      setMsg({ ok: true, text: `${o.order_id} (${o.platform}) ${where}` });
      setForm((f) => ({ ...emptyForm(), platform: f.platform, otherPlatform: f.otherPlatform }));
      onCreated();
    } catch (err) {
      setMsg({ ok: false, text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <div className="row space">
        <h2>New order</h2>
        <button type="button" className="btn" onClick={() => setForm(randomForm())}>Random order</button>
      </div>

      <div className="fields">
        <label>
          Platform
          <select value={form.platform} onChange={(e) => set({ platform: e.target.value })}>
            {PLATFORMS.map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        {form.platform === "Other" && (
          <label>
            Platform name
            <input value={form.otherPlatform} onChange={(e) => set({ otherPlatform: e.target.value })} required maxLength={40} />
          </label>
        )}
        <label>
          Customer name
          <input value={form.customer} onChange={(e) => set({ customer: e.target.value })} required maxLength={80}
            placeholder="Alex Morgan (shown as Alex M.)" />
        </label>
        <label>
          Order ID <span className="muted">(optional)</span>
          <input value={form.orderId} onChange={(e) => set({ orderId: e.target.value })} maxLength={40}
            pattern="[A-Za-z0-9._\-]+" placeholder="auto, e.g. DD-104" />
        </label>
      </div>

      <fieldset className="items">
        <legend>Items</legend>
        {form.items.map((it, i) => (
          <div className="row" key={i}>
            <input className="qty-input" type="number" min={1} max={99} value={it.quantity}
              onChange={(e) => setItem(i, { quantity: e.target.value })} aria-label="Quantity" required />
            <input list="menu" value={it.name} onChange={(e) => setItem(i, { name: e.target.value })}
              placeholder="Item name" aria-label="Item name" maxLength={80} required={i === 0} />
            <button type="button" className="btn ghost" aria-label="Remove item" disabled={form.items.length === 1}
              onClick={() => set({ items: form.items.filter((_, j) => j !== i) })}>✕</button>
          </div>
        ))}
        <datalist id="menu">{MENU.map((m) => <option key={m} value={m} />)}</datalist>
        <button type="button" className="btn ghost" onClick={() => set({ items: [...form.items, { name: "", quantity: 1 }] })}>
          + Add item
        </button>
      </fieldset>

      <div className="fields two">
        <label>
          Prep time (min)
          <input type="number" min={1} max={240} value={form.prep} onChange={(e) => set({ prep: e.target.value })} required />
        </label>
        <label>
          Pickup due in (min)
          <input type="number" min={0} max={1440} value={form.dueIn} onChange={(e) => set({ dueIn: e.target.value })} required />
        </label>
      </div>
      <p className="muted small">
        Due {formatTime(due.toISOString())} · latest safe start {formatTime(latestStart.toISOString())}
      </p>

      <button type="submit" className="btn primary wide" disabled={busy}>{busy ? "Sending…" : "Send order"}</button>
      {msg && <p className={msg.ok ? "ok-text" : "error"}>{msg.text}</p>}
    </form>
  );
}

// ------------------------------------------------------- boxes + simulated hardware events

function BoxPanel({ boxes, onChange }) {
  const [uid, setUid] = useState(import.meta.env.VITE_DEMO_STAFF_UID || "");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(null);

  async function act(boxId, action, body) {
    setBusy(boxId + action);
    setMsg(null);
    try {
      const res = await api("POST", `${boxPath(boxId)}/${action}`, body);
      setMsg({ ok: true, text: action === "staff-confirm"
        ? `${boxId}: ${res.already_confirmed ? "already ready" : "marked READY"} (${res.order_id})`
        : `${boxId}: ${res.order_id} collected${res.next_order_id ? `, next ${res.next_order_id}` : ", box free"}` });
      onChange();
    } catch (err) {
      setMsg({ ok: false, text: `${boxId}: ${err.message}` });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card">
      <h2>Boxes</h2>
      <label className="small">
        Staff ID for simulated "mark ready"
        <input value={uid} onChange={(e) => setUid(e.target.value)} placeholder="staff ID" />
      </label>
      {boxes.error && <p className="error">{boxes.error.message}</p>}
      <div className="box-list">
        {(boxes.data || []).map((b) => (
          <div className={`box-card state-${b.status.toLowerCase()}`} key={b.box_id}>
            <div className="row space">
              <strong>{b.box_id}</strong>
              <span className="pill">{b.status}</span>
            </div>
            <p className="small muted">
              {b.order_id || "no order"} · lock {b.lock_state.toLowerCase()}
            </p>
            <div className="row wrap">
              <button className="btn" disabled={b.status !== "PREPARING" || !uid.trim() || busy}
                onClick={() => act(b.box_id, "staff-confirm", { rfid_uid: uid.trim() })}>
                Mark ready (staff)
              </button>
              <button className="btn warn-btn" disabled={b.status !== "UNLOCKED" || busy}
                onClick={() => act(b.box_id, "complete-pickup")}>
                Complete pickup (supervised)
              </button>
            </div>
            <p className="small">
              <a href={`/screen/${encodeURIComponent(b.box_id)}`} target="_blank" rel="noreferrer">screen</a>
              {" · "}
              <a href={`/pickup/${encodeURIComponent(b.box_id)}`} target="_blank" rel="noreferrer">courier page</a>
            </p>
          </div>
        ))}
      </div>
      {msg && <p className={msg.ok ? "ok-text" : "error"}>{msg.text}</p>}
      <p className="muted small">
        "Complete pickup" stands in for a door sensor: press it only after watching the courier take the food.
      </p>
    </section>
  );
}

// -------------------------------------------------------------------------------- ledger

function Ledger({ ledger }) {
  const rows = [...(ledger.data || [])].sort((a, b) =>
    (STATUS_RANK[a.status] - STATUS_RANK[b.status]) ||
    ((a.queue_position ?? 0) - (b.queue_position ?? 0)) ||
    a.created_at.localeCompare(b.created_at));

  return (
    <section className="card">
      <div className="row space">
        <h2>Unified ledger</h2>
        <span className="muted small">Queue order = earliest latest-start (due − prep), then oldest</span>
      </div>
      {ledger.error && <p className="error">{ledger.error.message}</p>}
      {rows.length === 0 ? (
        <p className="muted">No orders yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Queue</th><th>Order</th><th>Platform</th><th>Customer</th><th>Items</th>
                <th>Prep</th><th>Due</th><th>Latest start</th><th>Status</th><th>Box</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <tr key={o.order_id} className={o.status === "COLLECTED" ? "dim" : ""}>
                  <td>{o.queue_position ?? ""}</td>
                  <td>{o.order_id}</td>
                  <td>{o.platform}</td>
                  <td>{o.customer_display_name}</td>
                  <td>{summarize(o.items)}</td>
                  <td>
                    {o.estimated_prep_minutes}m
                    {o.prep_estimated_by && (
                      <div className="muted small">by {o.prep_estimated_by}</div>
                    )}
                  </td>
                  <td>{formatTime(o.pickup_due_at)}</td>
                  <td><strong>{formatTime(o.latest_start_at)}</strong></td>
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
