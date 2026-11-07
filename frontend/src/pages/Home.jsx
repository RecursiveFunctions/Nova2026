import { api, usePoll } from "../api.js";

export default function Home() {
  const { data: boxes, error } = usePoll(() => api("GET", "/boxes"), 3000, "home");
  return (
    <main className="page">
      <h1>Smart Pickup Box</h1>
      <p className="muted">Open each link on the device that plays that role.</p>
      <section className="card">
        <h2>Order simulator &amp; ledger</h2>
        <a href="/simulator">/simulator</a>
      </section>
      <section className="card">
        <h2>Courier dashboard <span className="muted small">(demo only: shows pickup codes)</span></h2>
        <a href="/courier">/courier</a>
      </section>
      <section className="card">
        <h2>Boxes</h2>
        {error && <p className="error">{error.message}</p>}
        {!boxes && !error && <p className="muted">Loading…</p>}
        {boxes && (
          <table className="table">
            <thead>
              <tr><th>Box</th><th>Box screen</th><th>Courier page (NFC tag URL)</th></tr>
            </thead>
            <tbody>
              {boxes.map((b) => (
                <tr key={b.box_id}>
                  <td>{b.box_id}</td>
                  <td><a href={`/screen/${encodeURIComponent(b.box_id)}`}>/screen/{b.box_id}</a></td>
                  <td>
                    <a href={`/pickup/${encodeURIComponent(b.box_id)}`}>
                      {window.location.origin}/pickup/{b.box_id}
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" ? (
          <p className="warn">
            You are on {window.location.hostname}. A phone cannot open that: write the NFC tag with this
            computer's LAN address instead (e.g. http://192.168.x.x:5173/pickup/BOX-01).
          </p>
        ) : null}
      </section>
    </main>
  );
}
