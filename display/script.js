const BOX_ID = new URLSearchParams(location.search).get("box") || "BOX-01";
const POLL_MS = 1000;
const PREVIEW = location.pathname.match(/^\/p\/([^/]+)/);
const BASE = PREVIEW ? `/p/${PREVIEW[1]}` : "";

const els = {
  id: document.getElementById("order-id"),
  priority: document.getElementById("priority"),
  eta: document.getElementById("eta"),
  status: document.getElementById("status"),
  qr: document.getElementById("qr-area"),
  qrImg: document.querySelector("#qr-area img"),
  verifyText: document.getElementById("verify-text"),
  connected: document.querySelector(".connected"),
};

function setConnected(ok) {
  els.connected.textContent = ok ? "\u25CF CONNECTED" : "\u25CF OFFLINE";
  els.connected.style.color = ok ? "#4ade80" : "#f87171";
}

function showPickupUrl() {
  return `${location.origin}${BASE}/pickup/${encodeURIComponent(BOX_ID)}`;
}

async function poll() {
  try {
    const res = await fetch(`${BASE}/boxes/${encodeURIComponent(BOX_ID)}`, { cache: "no-store" });
    if (!res.ok) throw new Error("bad status " + res.status);
    const box = await res.json();
    setConnected(true);

    els.id.textContent = box.order_id ? "#" + box.order_id : "\u2014";
    els.priority.textContent = box.display_mode === "IDLE" ? "STANDBY" : (box.status || "") + " PRIORITY";
    els.status.textContent = box.status || "UNKNOWN";
    els.eta.textContent = "\u2014";
    els.verifyText.textContent = "SCAN TO VERIFY";
    els.qrImg.src = "order_qr.png";
    els.qrImg.alt = "Pickup QR Code";
  } catch (err) {
    setConnected(false);
  }
}

poll();
setInterval(poll, POLL_MS);
