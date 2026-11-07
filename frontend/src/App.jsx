import BoxScreen from "./pages/BoxScreen.jsx";
import CourierDashboard from "./pages/CourierDashboard.jsx";
import Home from "./pages/Home.jsx";
import PickupPage from "./pages/PickupPage.jsx";
import Simulator from "./pages/Simulator.jsx";
import CustomerPage from "./pages/CustomerPage.jsx";

// Three fixed routes, so a tiny path matcher instead of a router dependency.
//   /screen/:boxId   box display (the screen mounted on the box)
//   /pickup/:boxId   courier verification page (URL written on the box's NFC tag)
//   /simulator       mock order source, ledger and simulated hardware buttons
//   /courier         DEMO ONLY courier dashboard: pickup codes, reset/seed, staff cards
export default function App() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  let m;
  if ((m = path.match(/^\/screen\/([^/]+)$/))) return <BoxScreen boxId={decodeURIComponent(m[1])} />;
  if ((m = path.match(/^\/pickup\/([^/]+)$/))) return <PickupPage boxId={decodeURIComponent(m[1])} />;
  if (path === "/simulator") return <Simulator />;
  if (path === "/courier") return <CourierDashboard />;
  return <Home />;
}
