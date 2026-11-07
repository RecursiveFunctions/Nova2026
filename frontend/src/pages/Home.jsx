import { api, usePoll } from "../api.js";

const RESERVED = new Set([
  "screen", "pickup", "simulator", "courier", "customer",
  "boxes", "orders", "demo", "health", "docs", "assets", "api", "static", "p",
]);

function branchBase() {
  const segs = window.location.pathname.split("/").filter(Boolean);
  if (segs[0] === "p" && segs[1]) return "/" + segs[1];
  if (segs[0] && !RESERVED.has(segs[0])) return "/" + segs[0];
  return "";
}

export default function Home() {
  const { data: boxes, error } = usePoll(() => api("GET", "/boxes"), 3000, "home");
  const base = branchBase();
  const origin = window.location.origin;
  return (
    <main className="page">
      <h1>Smart Pickup Box</h1>
      <p className="muted">Open each link on the device that plays that role.</p>
      <section className="card">
        <h2>Order simulator &amp; ledger</h2>
        <a href={`${base}/simulator`}>{base}/simulator</a>
      </section>
      <section className="card">
        <h2>Courier dashboard <span className="muted small">(demo only: shows pickup codes)</span></h2>
        <a href={`${base}/courier`}>{base}/courier</a>
      </section>
      <section className="card">
        <h2>Boxes</h2>
        {error && <p className="error">{error.message}</p>}
        {!boxes && !error && <p className="muted">Loading…</p>}
        {boxes && (
          <table className="table">
            <thead>
              <tr><th>Box</th><th>Box screen</th><th>QR code URL (courier + staff page)</th></tr>
            </thead>
            <tbody>
              {boxes.map((b) => {
                const pickupPath = `${base}/pickup/${b.box_id}`;
                return (
                  <tr key={b.box_id}>
                    <td>{b.box_id}</td>
                    <td><a href={`${base}/screen/${encodeURIComponent(b.box_id)}`}>{base}/screen/{b.box_id}</a></td>
                    <td>
                      <a href={pickupPath}>
                        {origin}{pickupPath}
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="muted">
          Public demos use https://novabox.recursivefunctions.dev{base || ""}/pickup/BOX-01
          (not a LAN IP).
        </p>
      </section>
    </main>
  );
}
