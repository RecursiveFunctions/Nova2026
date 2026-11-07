
const API_URL = "http://172.26.20.68:8000";
const BOX_ID = "BOX-01";

async function updateDisplay() {
  try {
    const response = await fetch(`${API_URL}/boxes/${BOX_ID}`);

    if (!response.ok) {
      throw new Error("Could not get box data");
    }

    const box = await response.json();

    document.getElementById("order-id").textContent =
      box.order_id ? "#" + box.order_id : "NO ORDER";

    document.getElementById("priority").textContent =
      box.status === "PREPARING" ? "PREPARING" : "NOVA";

    document.getElementById("eta").textContent = "--:--";

    document.getElementById("status").textContent =
      box.status;

    console.log("Live box data:", box);
  } catch (error) {
    console.error("Backend connection error:", error);
    document.getElementById("status").textContent = "OFFLINE";
  }
}

updateDisplay();
setInterval(updateDisplay, 2000);
