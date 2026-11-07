"""SQLite access: connections, transaction helpers and schema."""
import logging
import sqlite3
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS boxes (
    box_id       TEXT PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT 'AVAILABLE'
                 CHECK (status IN ('AVAILABLE','PREPARING','READY','UNLOCKED')),
    order_id     TEXT UNIQUE,
    display_mode TEXT NOT NULL DEFAULT 'IDLE',
    lock_state   TEXT NOT NULL DEFAULT 'UNLOCKED' CHECK (lock_state IN ('LOCKED','UNLOCKED'))
);

CREATE TABLE IF NOT EXISTS orders (
    seq                   INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id              TEXT NOT NULL UNIQUE,
    platform              TEXT NOT NULL,
    customer_display_name TEXT NOT NULL,
    items_json            TEXT NOT NULL,
    estimated_prep_minutes INTEGER NOT NULL CHECK (estimated_prep_minutes > 0),
    pickup_due_at         TEXT NOT NULL,
    latest_start_at       TEXT NOT NULL,  -- pickup_due_at - estimated_prep_minutes (queue priority)
    created_at            TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'QUEUED'
                          CHECK (status IN ('QUEUED','PREPARING','READY','PICKUP_AUTHORIZED','COLLECTED')),
    box_id                TEXT,
    assigned_at           TEXT,
    collected_at          TEXT
);

-- Business rule 1, enforced by the database as well as by the code:
-- a box can hold at most one active order.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_order_per_box
    ON orders (box_id) WHERE status IN ('PREPARING','READY','PICKUP_AUTHORIZED');
CREATE INDEX IF NOT EXISTS orders_status_idx ON orders (status);

CREATE TABLE IF NOT EXISTS staff_credentials (
    rfid_uid   TEXT PRIMARY KEY,
    staff_name TEXT,
    active     INTEGER NOT NULL DEFAULT 1
);

-- Internal only. The code itself is never stored: only its HMAC (pickup_code_hash) and
-- the nonce it is derived from (the derivation also needs PICKUP_CODE_SECRET).
CREATE TABLE IF NOT EXISTS pickup_credentials (
    order_id         TEXT PRIMARY KEY,
    box_id           TEXT NOT NULL,
    code_nonce       TEXT NOT NULL,
    pickup_code_hash TEXT NOT NULL,
    issued_at        TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    used_at          TEXT,
    authorized_at    TEXT,
    failed_attempts  INTEGER NOT NULL DEFAULT 0,
    last_failed_at   TEXT
);
"""


def connect() -> sqlite3.Connection:
    # isolation_level=None -> we issue BEGIN/COMMIT ourselves (see write_tx).
    conn = sqlite3.connect(
        str(config.DATABASE_PATH), timeout=10, isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")  # readers (screen polling) never block the writer
        _drop_outdated_orders(conn)
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def _drop_outdated_orders(conn) -> None:
    """A database from the old price-based scheduler has no latest_start_at column. Its orders
    are demo data only, so drop them (boxes and staff cards are kept) and let SCHEMA recreate them."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)")}
    if cols and "latest_start_at" not in cols:
        logging.getLogger("pickupbox").warning("Old orders table found: clearing orders and pickup codes")
        conn.execute("DROP TABLE orders")
        conn.execute("DROP TABLE IF EXISTS pickup_credentials")
        conn.execute("UPDATE boxes SET status = 'AVAILABLE', order_id = NULL, display_mode = 'IDLE', "
                     "lock_state = 'UNLOCKED'")


@contextmanager
def write_tx():
    """One serialised write transaction (BEGIN IMMEDIATE takes SQLite's write lock up
    front, so two requests can never interleave an allocation). Commits on success,
    rolls back on any exception."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    finally:
        conn.close()


@contextmanager
def read_tx():
    """A consistent read-only snapshot."""
    conn = connect()
    try:
        conn.execute("BEGIN")
        yield conn
    finally:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        conn.close()
