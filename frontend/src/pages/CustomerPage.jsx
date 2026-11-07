import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const labels = {
  missing_item: "Missing item",
  wrong_order: "Wrong order",
  quality: "Food quality",
  other: "Something else",
};

const categories = [
  "This isn’t my order",
  "An item is missing",
  "An item is incorrect",
  "Food quality",
  "Something else",
];

// Customer-only UI prototype. Replace local confirmations with backend calls
// after the customer API and access rules have been agreed with the backend team.
export default function CustomerPage({ orderId }) {
  const [page, setPage] = useState("order");
  const [received, setReceived] = useState(false);
  const [category, setCategory] = useState(categories[0]);
  const [description, setDescription] = useState("");
  const [photo, setPhoto] = useState(null);
  const [preview, setPreview] = useState("");
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const heading = useRef(null);

  useEffect(() => {
    if (!photo) {
      setPreview("");
      return;
    }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  useEffect(() => {
    heading.current?.focus();
  }, [page]);

  function navigate(next) {
    setError("");
    setPage(next);
  }

  function selectPhoto(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/") || file.size > 10 * 1024 * 1024) {
      setError("Choose an image smaller than 10 MB.");
      event.target.value = "";
      return;
    }
    setError("");
    setPhoto(file);
  }

  function confirmReceipt() {
    // TODO: await backend receipt confirmation before showing success.
    setReceived(true);
    navigate("received");
  }

  async function saveReport(event) {
    event.preventDefault();
    if (!description.trim()) {
      setError("Please describe the problem.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const triage = await api("POST", "/reports/triage", {
        order_id: orderId || "1042",
        description: description.trim(),
        category,
      });
      setSaved({ description: description.trim(), photoName: photo?.name, triage });
      navigate("saved");
    } catch (err) {
      setError(err.message || "Could not classify this report.");
    } finally {
      setBusy(false);
    }
  }

  const titles = {
    order: "Your order",
    confirm: "Received your order?",
    received: "Receipt confirmed",
    report: "Report a problem",
    saved: "Report classified",
  };

  return (
    <main className="nova-customer">
      <header className="nc-header">
        <strong>NOVA <span>✳</span></strong>
        <span>Customer</span>
      </header>

      {page !== "order" && (
        <button className="nc-back" onClick={() => navigate("order")}>
          ← Back to order
        </button>
      )}

      <h1 ref={heading} tabIndex={-1}>{titles[page]}</h1>
      <p className="nc-notice">Problem reports are classified by the laptop model. Receipt confirmation stays in this tab.</p>

      <section className="nc-card" aria-label="Order information">
        <strong>Order #{orderId || "1042"}</strong>
        <p>{received ? "Receipt confirmed in this demo" : "Awaiting receipt · demo"}</p>
        {!orderId ? (
          <p>Sample order: Harvest bowl · Iced tea</p>
        ) : (
          <p>Order details will load after backend integration.</p>
        )}
      </section>

      {page === "order" && (
        <>
          {!received && <button className="nc-primary" onClick={() => navigate("confirm")}>Confirm received</button>}
          <button className="nc-secondary" onClick={() => navigate("report")}>Report a problem</button>
          {saved && <button className="nc-secondary" onClick={() => navigate("saved")}>View saved demo report</button>}
        </>
      )}

      {page === "confirm" && (
        <>
          <p>Confirm that the delivery was handed to you. You can still report a problem afterward.</p>
          <button className="nc-primary" onClick={confirmReceipt}>Confirm receipt · demo</button>
        </>
      )}

      {page === "received" && (
        <>
          <p className="nc-success" role="status">✓ Recorded in this tab only.</p>
          <button className="nc-primary" onClick={() => navigate("report")}>Report a problem</button>
        </>
      )}

      {page === "report" && (
        <form onSubmit={saveReport}>
          <label htmlFor="nc-category">Problem type</label>
          <select id="nc-category" value={category} onChange={event => setCategory(event.target.value)}>
            {categories.map(option => <option key={option}>{option}</option>)}
          </select>

          <label htmlFor="nc-description">What happened?</label>
          <textarea id="nc-description" value={description} maxLength={2000} required
            onChange={event => setDescription(event.target.value)} placeholder="Describe the problem with your order." />

          <label htmlFor="nc-photo">Add a photo · optional</label>
          <input id="nc-photo" type="file" accept="image/*" onChange={selectPhoto} />
          {preview && <img className="nc-photo" src={preview} alt="Selected problem photo" />}
          {photo && <button type="button" className="nc-secondary" onClick={() => {
            setPhoto(null);
            const input = document.getElementById("nc-photo");
            if (input) input.value = "";
          }}>Remove photo</button>}
          {error && <p className="nc-error" role="alert">{error}</p>}
          <button className="nc-primary" type="submit" disabled={busy}>{busy ? "Classifying…" : "Classify report"}</button>
        </form>
      )}

      {page === "saved" && saved && (
        <section className="nc-card" role="status">
          <h2>{labels[saved.triage.category] || saved.triage.category}</h2>
          <p><span className={`nc-severity ${saved.triage.severity}`}>{saved.triage.severity}</span></p>
          <p>{saved.triage.action}</p>
          <p className="nc-description">{saved.description}</p>
          {saved.photoName && <p>Photo selected: {saved.photoName}</p>}
        </section>
      )}
    </main>
  );
}
