import BoxScreen from "./pages/BoxScreen.jsx";
import CourierDashboard from "./pages/CourierDashboard.jsx";
import Home from "./pages/Home.jsx";
import PickupPage from "./pages/PickupPage.jsx";
import Simulator from "./pages/Simulator.jsx";
import CustomerPage from "./pages/CustomerPage.jsx";

const RESERVED = new Set([
  "screen", "pickup", "simulator", "courier", "customer",
  "boxes", "orders", "demo", "health", "docs", "assets", "api", "static", "p",
]);

/** Strip /<branch> (or legacy /p/<branch>) so routes work under branch demos. */
function appPath() {
  const raw = window.location.pathname.replace(/\/+$/, "") || "/";
  const segs = raw.split("/").filter(Boolean);
  if (segs[0] === "p" && segs[1]) return "/" + segs.slice(2).join("/") || "/";
  if (segs[0] && !RESERVED.has(segs[0])) return "/" + segs.slice(1).join("/") || "/";
  return raw;
}

// Three fixed routes, so a tiny path matcher instead of a router dependency.
//   /screen/:boxId   box display (the screen mounted on the box)
//   /pickup/:boxId   courier verification page (URL written on the box's NFC tag)
//   /simulator       mock order source, ledger and simulated hardware buttons
//   /courier         DEMO ONLY courier dashboard: pickup codes, reset/seed, staff cards
// Branch demos: /<branch>/pickup/BOX-01 etc.
export default function App() {
  const path = appPath();
  let m;
  if ((m = path.match(/^\/screen\/([^/]+)$/))) return <BoxScreen boxId={decodeURIComponent(m[1])} />;
  if ((m = path.match(/^\/pickup\/([^/]+)$/))) return <PickupPage boxId={decodeURIComponent(m[1])} />;
  if (path === "/simulator") return <Simulator />;
  if (path === "/courier") return <CourierDashboard />;
  if ((m = path.match(/^\/customer\/([^/]+)$/))) {
    const orderId = decodeURIComponent(m[1]);

    return (
      <CustomerPage
        key={orderId}
        orderId={orderId}
      />
    );
  }

  return <Home />;
}
