import { useCallback, useEffect, useRef, useState } from "react";

// Empty = same origin (the Vite proxy forwards API paths to the backend).
const BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status; // 0 = network failure
    this.body = body;
  }
}

function errorMessage(body, status) {
  if (body && typeof body.error === "string") return body.error;
  if (body && Array.isArray(body.detail)) {
    // FastAPI 422: [{loc: ["body", "items", 0, "name"], msg: "..."}]
    return body.detail.map((d) => `${(d.loc || []).slice(1).join(".") || "request"}: ${d.msg}`).join("; ");
  }
  return `Request failed (${status})`;
}

/** Calls the backend. Resolves with the JSON body; rejects with ApiError on any non-2xx or network error. */
export async function api(method, path, body, extraHeaders) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      cache: "no-store",
      headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...extraHeaders },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server", null);
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* empty or non-JSON body */
  }
  if (!res.ok) throw new ApiError(res.status, errorMessage(data, res.status), data);
  return data;
}

export const boxPath = (boxId) => `/boxes/${encodeURIComponent(boxId)}`;

/**
 * Polls load() every `ms` (next poll starts after the previous one finishes, so requests never pile up).
 * On failure the last good data is kept and `error` is set, so screens can show "connection lost"
 * without blanking. Returns {data, error, loaded, reload}.
 */
export function usePoll(load, ms, key) {
  const [state, setState] = useState({ data: null, error: null, loaded: false });
  const loadRef = useRef(load);
  loadRef.current = load;
  const kick = useRef(() => {});

  useEffect(() => {
    let alive = true;
    let timer;
    setState({ data: null, error: null, loaded: false });
    const tick = async () => {
      clearTimeout(timer);
      try {
        const data = await loadRef.current();
        if (alive) setState({ data, error: null, loaded: true });
      } catch (error) {
        if (alive) setState((s) => ({ ...s, error, loaded: true }));
      }
      if (alive) timer = setTimeout(tick, ms);
    };
    kick.current = tick;
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [key, ms]);

  const reload = useCallback(() => kick.current(), []);
  return { ...state, reload };
}

export function formatTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function summarize(items) {
  return items.map((i) => `${i.quantity}× ${i.name}`).join(", ");
}
