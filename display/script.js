
const order = {
  id: 1042,
  priority: "HIGH",
  eta: "04:00",
  status: "READY"
};

function updateDisplay() {
  document.getElementById("order-id").textContent =
    "#" + order.id;

  document.getElementById("priority").textContent =
    order.priority + " PRIORITY";

  document.getElementById("eta").textContent =
    order.eta;

  document.getElementById("status").textContent =
    order.status;
}

updateDisplay();
