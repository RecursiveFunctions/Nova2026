#!/usr/bin/env python3
"""Hardware bridge for one Smart Pickup Box (Person C). Standard library only (+ pyserial for --rfid serial).

The backend is the single source of truth: this bridge only forwards hardware events to it and
mirrors its state onto the box's display and lock. It never decides anything itself.

One-shot simulated events (no hardware needed):
    python bridge.py --box BOX-01 --simulate-staff-tap               # uses STAFF_RFID_UID or STAFF-TAG-01
    python bridge.py --box BOX-01 --simulate-staff-tap --uid 04A1B2C3
    python bridge.py --box BOX-01 --simulate-complete                # supervised "food was taken"

Long-running bridge:
    python bridge.py --box BOX-01 --watch                            # print screen text, drive the lock
    python bridge.py --box BOX-01 --rfid stdin                       # USB "keyboard" RFID reader: UID + Enter
    python bridge.py --box BOX-01 --rfid serial:COM3:9600            # Arduino/ESP printing one UID per line

API address: --api, else API_BASE_URL, else http://127.0.0.1:8000.
Replace Lock / Display below with the real GPIO / screen code once the parts are known.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API = "http://127.0.0.1:8000"
DEBOUNCE_SECONDS = 3.0  # the same card held on the reader must not fire repeatedly
POLL_SECONDS = 1.0


# ---------------------------------------------------------------------------- API client

class Api:
    def __init__(self, base_url: str, box_id: str):
        self.base = base_url.rstrip("/")
        self.box_path = "/boxes/" + urllib.parse.quote(box_id, safe="")

    def call(self, method: str, path: str, body=None, timeout: float = 5.0):
        """Returns (status, json_body). status 0 = backend unreachable (never treated as success)."""
        data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        except (urllib.error.URLError, OSError) as err:
            return 0, {"error": f"backend unreachable: {err}"}
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, {"error": raw.decode("utf-8", "replace")}

    def box(self):
        return self.call("GET", self.box_path)

    def staff_confirm(self, uid: str):
        return self.call("POST", self.box_path + "/staff-confirm", {"rfid_uid": uid})

    def complete_pickup(self):
        return self.call("POST", self.box_path + "/complete-pickup")


# ------------------------------------------------------------------- hardware stand-ins

class Lock:
    """Replace engage()/release() with the real actuator code (relay pin, servo, ...).
    The bridge only follows the backend's lock_state; it never unlocks on its own."""

    def __init__(self):
        self.state = None

    def apply(self, lock_state: str):
        if lock_state == self.state:
            return
        self.state = lock_state
        if lock_state == "LOCKED":
            self.engage()
        else:
            self.release()

    def engage(self):
        log("LOCK: engaged")

    def release(self):
        log("LOCK: released")


class Display:
    """Text version of the box screen, for a microcontroller display that cannot run a browser.
    Same rules as the web screen: PREPARING shows items only, READY shows pickup details,
    and nothing ever shows a pickup code (the backend never sends one here)."""

    def __init__(self):
        self.last = None

    def show(self, lines: list):
        if lines != self.last:
            self.last = lines
            log("SCREEN: " + " | ".join(lines))
            # Real display: clear, then draw each entry of `lines` on its own row.


def screen_lines(box: dict) -> list:
    status = box.get("status")
    if status == "PREPARING":
        return [box["box_id"], "PREPARING"] + [f'{i["quantity"]} x {i["name"]}' for i in box.get("items", [])]
    if status == "READY":
        return [box["box_id"], "READY", box.get("order_id", ""), box.get("customer_display_name", ""),
                box.get("summary", ""), "Tap phone on NFC tag"]
    if status == "UNLOCKED":
        return [box["box_id"], "PICKUP AUTHORIZED", box.get("order_id", ""), "Take order, close door"]
    return [box.get("box_id", "?"), "AVAILABLE"]


# ------------------------------------------------------------------------------ loops

def log(msg: str):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def watch(api: Api, stop: threading.Event):
    """Mirror backend state onto the display and lock. On connection loss keep the last state
    (the lock stays as it was) and say so; never assume a pickup happened."""
    display, lock, offline = Display(), Lock(), False
    while not stop.is_set():
        status, body = api.box()
        if status == 200:
            if offline:
                log("backend reachable again")
                offline = False
            display.show(screen_lines(body))
            lock.apply(body.get("lock_state", "LOCKED"))
        elif not offline:
            log(f"cannot read box state ({status}): {body.get('error')}; keeping last state")
            offline = True
        stop.wait(POLL_SECONDS)


def staff_tap(api: Api, uid: str) -> bool:
    status, body = api.staff_confirm(uid)
    if status == 200:
        note = "already ready (duplicate tap)" if body.get("already_confirmed") else "marked READY"
        log(f"RFID {uid}: {body.get('order_id')} {note}")
        return True
    log(f"RFID {uid}: refused ({status}) {body.get('error')}")
    return False


def rfid_lines(source: str):
    """Yields raw UID strings from the reader."""
    if source == "stdin":
        log("RFID: reading UIDs from the keyboard / USB reader (one per line, Ctrl+C to stop)")
        for line in sys.stdin:
            yield line
        return
    if source.startswith("serial:"):
        parts = source.split(":")
        port, baud = parts[1], int(parts[2]) if len(parts) > 2 else 9600
        try:
            import serial  # pyserial
        except ImportError:
            sys.exit("--rfid serial needs pyserial: pip install pyserial")
        log(f"RFID: reading UIDs from {port} at {baud} baud")
        with serial.Serial(port, baud, timeout=1) as ser:
            while True:
                raw = ser.readline()
                if raw:
                    yield raw.decode("utf-8", "replace")
    sys.exit(f"unknown --rfid source {source!r}: use stdin or serial:PORT[:BAUD]")


def run_rfid(api: Api, source: str):
    stop = threading.Event()
    threading.Thread(target=watch, args=(api, stop), daemon=True).start()
    last_uid, last_time = None, 0.0
    try:
        for raw in rfid_lines(source):
            uid = raw.strip()
            if not uid:
                continue
            card = re.sub(r"[\s:\-]", "", uid).upper()  # same normalisation as the backend
            now = time.monotonic()
            if card == last_uid and now - last_time < DEBOUNCE_SECONDS:
                continue  # card still on the reader
            last_uid, last_time = card, now
            staff_tap(api, uid)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()


# -------------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--box", required=True, help="box ID, e.g. BOX-01")
    ap.add_argument("--api", default=os.environ.get("API_BASE_URL") or DEFAULT_API,
                    help="backend URL (env API_BASE_URL); use the API laptop's LAN IP from another device")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--simulate-staff-tap", action="store_true", help="send one staff RFID tap and exit")
    mode.add_argument("--simulate-complete", action="store_true",
                      help="confirm the food was taken (supervised stand-in for a door sensor) and exit")
    mode.add_argument("--watch", action="store_true", help="mirror box state to display + lock until Ctrl+C")
    mode.add_argument("--rfid", metavar="SOURCE", help="stdin or serial:PORT[:BAUD]; also runs --watch")
    ap.add_argument("--uid", default=os.environ.get("STAFF_RFID_UID") or "STAFF-TAG-01",
                    help="UID for --simulate-staff-tap (env STAFF_RFID_UID)")
    args = ap.parse_args()
    api = Api(args.api, args.box)

    if args.simulate_staff_tap:
        sys.exit(0 if staff_tap(api, args.uid) else 1)
    if args.simulate_complete:
        status, body = api.complete_pickup()
        if status == 200:
            log(f"{args.box}: {body['order_id']} collected; next order: {body.get('next_order_id') or 'none'}")
            sys.exit(0)
        log(f"{args.box}: complete-pickup refused ({status}) {body.get('error')}")
        sys.exit(1)
    if args.watch:
        stop = threading.Event()
        try:
            watch(api, stop)
        except KeyboardInterrupt:
            stop.set()
        return
    run_rfid(api, args.rfid)


if __name__ == "__main__":
    main()
