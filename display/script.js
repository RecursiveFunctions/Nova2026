const BOX_ID = new URLSearchParams(location.search).get("box") || "BOX-01";
const POLL_MS = 1000;

// Branch demos live at /<slug>/... (legacy /p/<slug>/ still redirects).
const RESERVED = new Set([
  "boxes", "pickup", "orders", "demo", "health", "docs",
  "screen", "simulator", "courier", "customer", "assets", "api", "static", "p",
]);
const parts = location.pathname.split("/").filter(Boolean);
const BRANCH = parts[0] && !RESERVED.has(parts[0]) ? parts[0] : (parts[0] === "p" && parts[1] ? parts[1] : "");
const BASE = BRANCH ? `/${BRANCH}` : "";

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

function pickupUrl() {
  return `${location.origin}${BASE}/pickup/${encodeURIComponent(BOX_ID)}`;
}

function setQr(url) {
  const src = `${BASE}/pickup/${encodeURIComponent(BOX_ID)}/qr.png?url=${encodeURIComponent(url)}`;
  if (els.qrImg.dataset.url !== url) {
    els.qrImg.dataset.url = url;
    els.qrImg.src = src;
    els.qrImg.alt = url;
  }
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
    setQr(box.pickup_url || pickupUrl());
  } catch (err) {
    setConnected(false);
  }
}

poll();
setInterval(poll, POLL_MS);
