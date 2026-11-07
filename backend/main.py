"""Smart Pickup Box - FastAPI backend (HTTP routes only; the rules live in logic.py).

Run (from the backend/ folder):
    uvicorn main:app --host 0.0.0.0 --port 8000
Interactive docs: http://<this-machine>:8000/docs
"""
import hmac
import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

import config
import db
import logic
from logic import ApiError
from pickup_page import render_pickup_page, render_unknown_box_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pickupbox")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    with db.write_tx() as conn:
        logic.seed_defaults(conn)
        logic.allocate_boxes(conn)
    if config.DEMO_API_KEY:
        log.info("/demo/* endpoints require the X-Demo-Key header")
    else:
        log.warning("DEMO_API_KEY is not set: /demo/* endpoints only accept requests from this machine")
    log.info("Database: %s | boxes: %s | pickup code TTL: %g min",
             config.DATABASE_PATH, ", ".join(config.BOX_IDS), config.PICKUP_CODE_TTL_MINUTES)
    yield


app = FastAPI(
    title="Smart Pickup Box API",
    version="1.0.0",
    description="Order ledger, scheduler, box allocator and pickup verification. "
                "The backend is the single source of truth for orders and boxes.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"  # screens poll every second; never serve stale state
    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(exc.body, status_code=exc.status_code)


@app.exception_handler(sqlite3.OperationalError)
async def db_error_handler(request: Request, exc: sqlite3.OperationalError):
    log.exception("Database error")
    return JSONResponse({"error": "Database unavailable, please retry"}, status_code=503)


def require_demo_access(request: Request, x_demo_key: Optional[str] = Header(default=None)):
    """Protects /demo/*: X-Demo-Key header if DEMO_API_KEY is set, otherwise local requests only."""
    if config.DEMO_API_KEY:
        if not x_demo_key or not hmac.compare_digest(x_demo_key.encode("utf-8"), config.DEMO_API_KEY.encode("utf-8")):
            raise ApiError(403, "Missing or invalid X-Demo-Key header")
    else:
        host = request.client.host if request.client else ""
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ApiError(403, "Demo endpoints are local-only. Set DEMO_API_KEY to allow remote use")


# ------------------------------------------------------------------------------ models

class ItemIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=1, le=99)


class OrderIn(BaseModel):
    """Normalised order from a (mock) delivery platform. Unknown fields are ignored."""
    model_config = ConfigDict(str_strip_whitespace=True)
    order_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,40}$",
                                    description="Optional. Generated (e.g. DD-104) if omitted.")
    platform: str = Field(min_length=1, max_length=40, examples=["DoorDash"])
    customer_display_name: str = Field(min_length=1, max_length=80, examples=["Alex M."])
    items: list[ItemIn] = Field(min_length=1, max_length=50)
    estimated_prep_minutes: int = Field(ge=1, le=240, examples=[12])
    pickup_due_at: datetime = Field(description="Must include a UTC offset. Queue priority is "
                                                "pickup_due_at - estimated_prep_minutes, smallest first.")
    created_at: Optional[datetime] = Field(default=None, description="Defaults to now. Must include a UTC offset.")

    @field_validator("created_at", "pickup_due_at")
    @classmethod
    def _needs_utc_offset(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone offset, e.g. 2026-11-07T13:30:00-05:00")
        return value


class StaffConfirmIn(BaseModel):
    rfid_uid: str = Field(min_length=1, max_length=64, examples=["STAFF-TAG-01"])


class VerifyPickupIn(BaseModel):
    pickup_code: str = Field(max_length=32, examples=["583216"])


class DemoStaffIn(BaseModel):
    rfid_uid: str = Field(min_length=1, max_length=64)
    staff_name: Optional[str] = Field(default=None, max_length=80)


# ------------------------------------------------------------------------------ routes

@app.get("/", include_in_schema=False)
def root():
    return {"service": "Smart Pickup Box API", "docs": "/docs"}


@app.get("/health")
def health():
    with db.read_tx() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.post("/orders", status_code=201)
def create_order(order: OrderIn):
    """Ingest one normalised order. If a box is free it is assigned immediately."""
    with db.write_tx() as conn:
        order_id = logic.ingest_orders(conn, [order.model_dump()])[0]
        logic.allocate_boxes(conn)
        return logic.get_order(conn, order_id)


@app.get("/orders")
def list_orders(status: Optional[str] = Query(default=None, description="Filter, e.g. QUEUED")):
    """The unified ledger, oldest first. Every order has latest_start_at; QUEUED orders also have
    queue_position (1 = next free box)."""
    if status is not None and status.upper() not in logic.ORDER_STATES:
        raise ApiError(422, "status must be one of " + ", ".join(logic.ORDER_STATES))
    with db.read_tx() as conn:
        return logic.list_orders(conn, status.upper() if status else None)


@app.get("/boxes")
def list_boxes():
    with db.read_tx() as conn:
        return logic.list_boxes(conn)


@app.get("/boxes/{box_id}")
def get_box(box_id: str):
    """Display-safe view for the box screen and hardware bridge (no pickup code, ever)."""
    with db.read_tx() as conn:
        return logic.box_screen_view(conn, box_id)


@app.post("/boxes/{box_id}/staff-confirm")
def staff_confirm(box_id: str, body: StaffConfirmIn):
    """Registered staff RFID tap: PREPARING -> READY. Repeat taps return 200 and change nothing."""
    with db.write_tx() as conn:
        return logic.staff_confirm(conn, box_id, body.rfid_uid)


@app.post("/boxes/{box_id}/verify-pickup")
def verify_pickup(box_id: str, body: VerifyPickupIn):
    """Check the courier's one-time code. 200 = authorized (bridge may unlock); 403/409/429 = denied."""
    with db.write_tx() as conn:
        status, payload = logic.verify_pickup(conn, box_id, body.pickup_code)
    headers = {"Retry-After": "1"} if status == 429 else None
    return JSONResponse(payload, status_code=status, headers=headers)


@app.post("/boxes/{box_id}/complete-pickup")
def complete_pickup(box_id: str):
    """Sensor/bridge or supervised demo button confirms handoff: COLLECTED, box freed, next order assigned."""
    with db.write_tx() as conn:
        return logic.complete_pickup(conn, box_id)


@app.get("/pickup/{box_id}", response_class=HTMLResponse)
def pickup_page(box_id: str):
    """Courier verification page (the URL stored on the box's NFC tag). Fallback to the React page."""
    with db.read_tx() as conn:
        exists = conn.execute("SELECT 1 FROM boxes WHERE box_id = ?", (box_id,)).fetchone() is not None
    if not exists:
        return HTMLResponse(render_unknown_box_page(box_id), status_code=404)
    return HTMLResponse(render_pickup_page(box_id))


# --------------------------------------------------------------------- demo-only routes

@app.get("/demo/courier-orders", dependencies=[Depends(require_demo_access)])
def demo_courier_orders():
    """DEMO ONLY: box assignments with their pickup codes, for the simulated courier dashboard."""
    with db.read_tx() as conn:
        return logic.courier_orders(conn)


@app.post("/demo/reset", dependencies=[Depends(require_demo_access)])
def demo_reset(seed: bool = Query(default=False, description="Also insert the six demo orders")):
    """Wipe all orders/codes and free every box (staff cards and boxes are kept)."""
    with db.write_tx() as conn:
        logic.reset_all(conn)
        seeded = logic.seed_demo_orders(conn) if seed else []
        return {"reset": True, "seeded_order_ids": seeded, "boxes": logic.list_boxes(conn)}


@app.post("/demo/seed", dependencies=[Depends(require_demo_access)])
def demo_seed():
    """Insert six demo orders (3 platforms) as one batch; the free boxes are filled by latest safe start."""
    with db.write_tx() as conn:
        seeded = logic.seed_demo_orders(conn)
        return {"seeded_order_ids": seeded, "orders": logic.list_orders(conn)}


@app.post("/demo/staff", dependencies=[Depends(require_demo_access)])
def demo_register_staff(body: DemoStaffIn):
    """Register a staff RFID card (e.g. the real one, once the reader shows its UID)."""
    with db.write_tx() as conn:
        return logic.register_staff(conn, body.rfid_uid, body.staff_name)
