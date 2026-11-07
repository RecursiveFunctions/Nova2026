import { api, boxPath, usePoll } from "../api.js";

// The public screen on the box. Renders ONLY whitelisted fields for each state:
//   PREPARING -> food names + quantities (no customer, platform, order ID or times)
//   READY     -> order ID, abbreviated customer name, short summary
// It never receives or shows a pickup code.
export default function BoxScreen({ boxId }) {
  const { data: box, error, loaded } = usePoll(() => api("GET", boxPath(boxId)), 1000, boxId);

  if (!box) {
    return (
      <div className="screen state-idle">
        <BoxTag boxId={boxId} />
        <div className="screen-body">
          {!loaded ? (
            <p className="screen-sub">Connecting…</p>
          ) : error?.status === 404 ? (
            <h1 className="screen-title">Unknown box</h1>
          ) : (
            <>
              <h1 className="screen-title">Offline</h1>
              <p className="screen-sub">Cannot reach the server. Retrying…</p>
            </>
          )}
        </div>
      </div>
    );
  }

  const offline = error && error.status !== 404;
  return (
    <div className={`screen state-${box.status.toLowerCase()}`}>
      <BoxTag boxId={box.box_id} />
      {offline && <div className="screen-offline">Connection lost: showing last known state</div>}
      <div className="screen-body">{renderState(box)}</div>
    </div>
  );
}

function renderState(box) {
  switch (box.status) {
    case "PREPARING":
      return (
        <>
          <p className="screen-label">Preparing</p>
          <ul className="screen-items">
            {(box.items || []).map((item, i) => (
              <li key={i}>
                <span className="qty">{item.quantity}</span>
                <span className="name">{item.name}</span>
              </li>
            ))}
          </ul>
        </>
      );
    case "READY":
      return (
        <>
          <p className="screen-label">Ready for pickup</p>
          <h1 className="screen-order">{box.order_id}</h1>
          <p className="screen-name">{box.customer_display_name}</p>
          <p className="screen-summary">{box.summary}</p>
          <p className="screen-hint">Courier: scan the QR code</p>
        </>
      );
    case "UNLOCKED":
      return (
        <>
          <p className="screen-label">Pickup authorized</p>
          <h1 className="screen-order">{box.order_id}</h1>
          <p className="screen-summary">Please take your order and close the door</p>
        </>
      );
    default:
      return (
        <>
          <h1 className="screen-title">Available</h1>
          <p className="screen-sub">Waiting for the next order</p>
        </>
      );
  }
}

function BoxTag({ boxId }) {
  return <div className="screen-tag">{boxId}</div>;
}
