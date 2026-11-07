import { useState } from "react";
import { api, boxPath, usePoll } from "../api.js";

// Opened by scanning the box's QR code. While the order is being prepared, staff use it to mark
// the order ready with their staff ID (this replaces an RFID tap; the API field is still rfid_uid).
// Once it is ready, the courier types the one-time code from their (simulated) courier app.
// The backend decides both. Anything but a 200 is "not authorized".
export default function PickupPage({ boxId }) {
  const { data: box, error: boxError, reload } = usePoll(() => api("GET", boxPath(boxId)), 2000, boxId);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // {ok: true, orderId} | {ok: false, message}

  if (boxError?.status === 404) {
    return (
      <main className="page narrow">
        <h1>Unknown box</h1>
        <p>No box called {boxId} exists. Check the QR code.</p>
      </main>
    );
  }

  async function submit(e) {
    e.preventDefault();
    if (busy || code.length !== 6) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await api("POST", `${boxPath(boxId)}/verify-pickup`, { pickup_code: code });
      if (res && res.authorized === true) {
        setResult({ ok: true, orderId: res.order_id });
      } else {
        setResult({ ok: false, message: "Not authorized" });
      }
    } catch (err) {
      const message =
        err.status === 0
          ? "Could not reach the server. Nothing was unlocked; try again."
          : err.status === 429
            ? "Too many attempts. Wait a moment and try again."
            : err.message;
      setResult({ ok: false, message });
    } finally {
      setBusy(false);
      setCode("");
    }
  }

  if (result?.ok) {
    return (
      <main className="page narrow">
        <div className="result ok">
          <h1>Pickup authorized</h1>
          <p className="big">{result.orderId}</p>
          <p>{boxId} is unlocked. Take the order and close the door.</p>
        </div>
      </main>
    );
  }

  const status = box?.status;
  const canSubmit = !box || status === "READY"; // if status is unknown (offline) let the backend decide

  return (
    <main className="page narrow">
      <p className="muted">Smart Pickup Box</p>
      <h1>Pickup at {boxId}</h1>

      {status === "READY" && (
        <div className="card">
          <p className="muted">Order ready</p>
          <p className="big">{box.order_id}</p>
          <p>{box.customer_display_name}</p>
        </div>
      )}
      {(status === "AVAILABLE" || status === "PREPARING") && (
        <p className="warn">No order is ready at this box yet. This page updates automatically.</p>
      )}
      {status === "UNLOCKED" && <p className="warn">This box is already unlocked for a pickup.</p>}
      {boxError && box && <p className="warn">Connection problem: status may be out of date.</p>}
      {boxError && !box && <p className="warn">Cannot reach the server. Check you are on the demo Wi-Fi.</p>}

      {status === "PREPARING" ? <StaffReadyForm boxId={boxId} onDone={reload} /> : (
      <form onSubmit={submit} className="card">
        <label htmlFor="code">One-time pickup code</label>
        <input
          id="code"
          className="code-input"
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="••••••"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          disabled={!canSubmit || busy}
        />
        <button type="submit" className="btn primary wide" disabled={!canSubmit || busy || code.length !== 6}>
          {busy ? "Checking…" : "Verify pickup"}
        </button>
        <p className="muted small">The code is in your courier app. It is never shown on the box.</p>
      </form>
      )}

      {result && !result.ok && (
        <div className="result fail" role="alert">
          <h2>Not authorized</h2>
          <p>{result.message}</p>
        </div>
      )}
    </main>
  );
}

function StaffReadyForm({ boxId, onDone }) {
  const [staffId, setStaffId] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (busy || !staffId.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await api("POST", `${boxPath(boxId)}/staff-confirm`, { rfid_uid: staffId.trim() });
      setMsg({ ok: true, text: `${res.order_id} marked ready. The box is locked.` });
      onDone();
    } catch (err) {
      setMsg({ ok: false, text: err.status === 0 ? "Could not reach the server; nothing changed." : err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card">
      <p className="muted">Staff only</p>
      <h2>Food is in the box?</h2>
      <label htmlFor="staff">Staff ID</label>
      <input id="staff" type="password" autoComplete="current-password" value={staffId}
        onChange={(e) => setStaffId(e.target.value)} disabled={busy} />
      <button type="submit" className="btn primary wide" disabled={busy || !staffId.trim()}>
        {busy ? "Saving…" : "Mark ready & lock"}
      </button>
      {msg && <p className={msg.ok ? "ok-text" : "error"}>{msg.text}</p>}
    </form>
  );
}
