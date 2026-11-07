#!/usr/bin/env python3
"""Raspberry Pi bridge for one Smart Pickup Box (Person C).

Hardware: Raspberry Pi 3/4, 3.5" 480x320 SPI LCD (HannStar HSD035577B5 panel), a 2-wire DC motor
driving the latch through an H-bridge, and a QR code that opens the box's web page.

The backend is the single source of truth. This bridge only mirrors it:
  * the LCD shows the box state (items only while PREPARING; order ID, name, summary and the QR
    code when READY), and never a pickup code (the backend never sends one here);
  * the motor locks the latch when the backend says LOCKED (order READY) and unlocks it only
    when the backend says UNLOCKED (after a valid pickup code). It never decides by itself.

Run on the Pi:
    python3 bridge.py --box BOX-01 --api http://<API-laptop-IP>:8000 --public-url http://<API-laptop-IP>:5173
Try the screen without a Pi (writes PNG previews instead of drawing on the LCD):
    python bridge.py --box BOX-01 --display png --lock none
One-shot simulated events:
    python bridge.py --box BOX-01 --simulate-staff-ready          # staff ID from --staff-id / STAFF_ID
    python bridge.py --box BOX-01 --simulate-complete              # supervised "food was taken"

Every option also has an environment variable (shown in --help), so a systemd service only needs
an EnvironmentFile. Pi packages: sudo apt install python3-pil python3-qrcode python3-gpiozero
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

POLL_SECONDS = 1.0


# ------------------------------------------------------------------------------ API client

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

    def staff_confirm(self, staff_id: str):
        # The API field is still called rfid_uid (contract); it holds the staff ID now.
        return self.call("POST", self.box_path + "/staff-confirm", {"rfid_uid": staff_id})

    def complete_pickup(self):
        return self.call("POST", self.box_path + "/complete-pickup")


def log(msg: str):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ----------------------------------------------------------------------------- the screen

W, H = 480, 320
COLORS = {  # status -> accent colour (bar + label)
    "AVAILABLE": (110, 118, 129),
    "PREPARING": (255, 176, 32),
    "READY": (61, 123, 255),
    "UNLOCKED": (47, 208, 111),
}
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Raspberry Pi OS
    "C:/Windows/Fonts/segoeuib.ttf",                         # previews on Windows
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",     # previews on macOS
]


def _font(size: int):
    from PIL import ImageFont
    for path in FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _fit(draw, text: str, max_width: int, start: int, minimum: int = 14):
    """Largest font (from `start` down) at which `text` fits in max_width; truncates if needed."""
    size = start
    while size > minimum and draw.textlength(text, font=_font(size)) > max_width:
        size -= 2
    font = _font(size)
    while text and draw.textlength(text, font=font) > max_width:
        text = text[:-2] + "…"
    return text, font


def _wrap(draw, text: str, font, max_width: int, max_lines: int, sep: str = " ") -> list:
    """Word wrap; with sep=" · " each summary entry ("2 Spring Rolls") stays on one line."""
    words, lines, line = text.split(sep), [], ""
    for word in words:
        trial = f"{line}{sep}{word}" if line else word
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ·") + " …"
    return lines


def render(box: dict, pickup_url: str, offline: bool = False):
    """The 480x320 screen image for one backend box view (GET /boxes/{id})."""
    from PIL import Image, ImageDraw
    status = box.get("status", "AVAILABLE")
    accent = COLORS.get(status, COLORS["AVAILABLE"])
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=accent)
    d.text((16, 20), box.get("box_id", "?"), font=_font(18), fill=(154, 161, 171))

    if status == "PREPARING":
        # Items and quantities only: no customer, platform, order ID or times.
        d.text((16, 46), "PREPARING", font=_font(24), fill=accent)
        items = box.get("items", [])
        size = 34 if len(items) <= 4 else 26 if len(items) <= 6 else 20
        y, line_h = 86, size + 10
        for i, item in enumerate(items):
            if y + line_h > H - 6:
                d.text((16, y), f"+{len(items) - i} more", font=_font(size), fill=(207, 211, 217))
                break
            qty = f'{item["quantity"]}×'
            d.text((16, y), qty, font=_font(size), fill=accent)
            name, font = _fit(d, item["name"], W - 106, size, minimum=max(18, size - 10))
            d.text((90, y + (size - font.size)), name, font=font, fill=(255, 255, 255))  # same baseline
            y += line_h

    elif status == "READY":
        qr_size = 190
        d.text((16, 46), "READY FOR PICKUP", font=_font(22), fill=accent)
        text_w = W - qr_size - 40
        order, font = _fit(d, box.get("order_id", ""), text_w, 48)
        d.text((16, 80), order, font=font, fill=(255, 255, 255))
        name, font = _fit(d, box.get("customer_display_name", ""), text_w, 30)
        d.text((16, 140), name, font=font, fill=(255, 255, 255))
        small = _font(18)
        for i, line in enumerate(_wrap(d, box.get("summary", ""), small, text_w, 4, sep=" · ")):
            d.text((16, 186 + i * 24), line, font=small, fill=(207, 211, 217))
        if pickup_url:
            qr = make_qr(pickup_url, qr_size)
            img.paste(qr, (W - qr_size - 14, 52))
            d.text((W - qr_size - 14, 52 + qr_size + 6), "Courier: scan to collect", font=_font(15),
                   fill=(154, 161, 171))

    elif status == "UNLOCKED":
        d.text((16, 56), "PICKUP AUTHORIZED", font=_font(28), fill=accent)
        order, font = _fit(d, box.get("order_id", ""), W - 32, 64)
        d.text((16, 110), order, font=font, fill=(255, 255, 255))
        d.text((16, 200), "Take your order and close the door", font=_font(22), fill=(207, 211, 217))

    else:
        d.text((16, 110), "Available", font=_font(60), fill=(255, 255, 255))
        d.text((16, 190), "Waiting for the next order", font=_font(24), fill=(154, 161, 171))

    if offline:
        d.rectangle([0, H - 34, W, H], fill=(198, 40, 40))
        d.text((12, H - 29), "Connection lost: showing last known state", font=_font(18), fill=(255, 255, 255))
    return img


def make_qr(url: str, size: int):
    """White-background QR image of exactly size x size pixels. Every module is a whole number of
    pixels (uneven modules scan badly on a small LCD); leftover pixels become extra quiet zone."""
    import qrcode
    from PIL import Image
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2, box_size=1)
    qr.add_data(url)
    qr.make(fit=True)
    modules = qr.modules_count + 2 * qr.border
    qr.box_size = max(1, size // modules)
    code = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    out = Image.new("RGB", (size, size), (255, 255, 255))
    out.paste(code, ((size - code.width) // 2, (size - code.height) // 2))
    return out


def to_rgb565(img) -> bytes:
    """Little-endian RGB565 (what fbtft LCDs expect), using only basic Pillow operations: newer
    Pillow releases dropped the "BGR;16" raw encoder. The two bytes per pixel are built separately
    (their bit fields never overlap, so adding them is a bitwise OR) and interleaved low, high."""
    from PIL import Image, ImageChops
    r, g, b = img.convert("RGB").split()
    high = ImageChops.add(r.point(lambda v: v & 0xF8), g.point(lambda v: v >> 5))
    low = ImageChops.add(g.point(lambda v: ((v >> 2) & 0x07) << 5), b.point(lambda v: v >> 3))
    return Image.merge("LA", (low, high)).tobytes()


class FramebufferDisplay:
    """Draws straight onto the LCD's Linux framebuffer (/dev/fb1 from the fbtft driver; see README).
    No desktop or browser needed. Handles 16-bit (RGB565) and 32-bit framebuffers and portrait panels."""

    def __init__(self, device: str, rotate: int):
        name = os.path.basename(device)
        sysfs = f"/sys/class/graphics/{name}"
        try:
            with open(f"{sysfs}/virtual_size") as f:
                self.width, self.height = (int(v) for v in f.read().strip().split(","))
            with open(f"{sysfs}/bits_per_pixel") as f:
                self.bpp = int(f.read().strip())
        except OSError as err:
            sys.exit(f"Cannot read {sysfs}: {err}. Is the LCD driver installed? (see hardware/README.md)")
        self.device = device
        # A 320x480 (portrait) framebuffer gets the landscape image turned automatically.
        self.rotate = rotate if rotate else (90 if self.height > self.width else 0)
        log(f"LCD {device}: {self.width}x{self.height}, {self.bpp} bpp, rotate {self.rotate}")

    def show(self, img):
        from PIL import Image
        if self.rotate:
            img = img.rotate(self.rotate, expand=True)
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height), Image.BILINEAR)
        if self.bpp == 16:
            data = to_rgb565(img)
        else:
            data = img.convert("RGBA").tobytes("raw", "BGRA")
        with open(self.device, "wb") as fb:
            fb.write(data)


class PngDisplay:
    """For testing away from the Pi: writes each new screen to screen-<box>.png."""

    def __init__(self, box_id: str):
        self.path = os.path.abspath(f"screen-{box_id}.png")
        log(f"Screen previews -> {self.path}")

    def show(self, img):
        img.save(self.path)


# ------------------------------------------------------------------------------- the lock

class NoLock:
    def apply(self, lock_state: str):
        pass

    def close(self):
        pass


class MotorLock:
    """2-wire DC motor turning a latch, through an H-bridge (L298N / L9110S / TB6612 / DRV8833).

    Locking = motor forward, unlocking = motor backward, each for --lock-seconds at --lock-speed
    against a mechanical stop. If limit switches are wired (--locked-switch / --unlocked-switch)
    the motor stops as soon as the switch closes, and --lock-seconds becomes a safety timeout.
    Swap the two motor wires if it turns the wrong way. Never power the motor from the Pi."""

    def __init__(self, in1: int, in2: int, enable, seconds: float, speed: float,
                 locked_switch=None, unlocked_switch=None):
        from gpiozero import Button, Motor
        self.motor = Motor(forward=in1, backward=in2, enable=enable, pwm=True)
        self.seconds, self.speed = seconds, speed
        self.switch = {
            "LOCKED": Button(locked_switch) if locked_switch is not None else None,
            "UNLOCKED": Button(unlocked_switch) if unlocked_switch is not None else None,
        }
        self.state = None  # unknown at start: the first backend state drives the latch there once
        self.lock = threading.Lock()

    def apply(self, lock_state: str):
        target = "LOCKED" if lock_state == "LOCKED" else "UNLOCKED"
        if target == self.state:
            return
        with self.lock:
            switch = self.switch[target]
            if switch is not None and switch.is_pressed:
                self.state = target
                return
            log(f"LOCK: {'locking' if target == 'LOCKED' else 'unlocking'}")
            (self.motor.forward if target == "LOCKED" else self.motor.backward)(self.speed)
            deadline = time.monotonic() + self.seconds
            while time.monotonic() < deadline and not (switch is not None and switch.is_pressed):
                time.sleep(0.01)
            self.motor.stop()
            if switch is not None and not switch.is_pressed:
                log(f"LOCK: WARNING limit switch not reached within {self.seconds}s, check the latch")
            self.state = target
            log(f"LOCK: {target.lower()}")

    def close(self):
        self.motor.stop()


# -------------------------------------------------------------------------------- the loop

def run(api: Api, display, lock, pickup_url: str):
    """Mirror backend state onto the screen and the lock. On connection loss keep the last state
    (the latch stays where it is) and show a banner; never assume a pickup happened."""
    last_box, last_key, offline = None, None, False
    try:
        while True:
            status, body = api.box()
            if status == 200:
                if offline:
                    log("backend reachable again")
                last_box, offline = body, False
                lock.apply(body.get("lock_state", "LOCKED"))
            elif not offline:
                log(f"cannot read box state ({status}): {body.get('error')}; keeping last state")
                offline = True
            if last_box is not None or offline:
                shown = last_box or {"box_id": api.box_path.rsplit("/", 1)[-1], "status": "AVAILABLE"}
                key = json.dumps([shown, offline], sort_keys=True)
                if key != last_key:  # redraw only on change: SPI screens are slow
                    display.show(render(shown, pickup_url, offline))
                    last_key = key
                    log(f"SCREEN: {shown.get('status')}{' (offline)' if offline else ''}")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        lock.close()


# -------------------------------------------------------------------------------- main

def env(name, default=None):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--box", default=env("BOX_ID"), help="box ID, e.g. BOX-01 (env BOX_ID)")
    ap.add_argument("--api", default=env("API_BASE_URL", "https://novabox.recursivefunctions.dev"),
                    help="backend URL (env API_BASE_URL)")
    ap.add_argument("--public-url",
                    default=env("PUBLIC_URL", "https://novabox.recursivefunctions.dev"),
                    help="origin phones open, optionally /<branch> (env PUBLIC_URL); "
                         "QR points to <public-url>/pickup/<box>")
    ap.add_argument("--display", choices=["fb", "png", "none"], default=env("DISPLAY_MODE", "fb"),
                    help="fb = draw on the LCD, png = preview files (env DISPLAY_MODE)")
    ap.add_argument("--fb", default=env("FB_DEVICE", "/dev/fb1"), help="LCD framebuffer (env FB_DEVICE)")
    ap.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=int(env("ROTATE", 0)),
                    help="rotate the image if the screen is mounted differently (env ROTATE)")
    ap.add_argument("--lock", choices=["motor", "none"], default=env("LOCK_MODE", "motor"),
                    help="motor = drive the latch, none = screen only (env LOCK_MODE)")
    ap.add_argument("--motor-in1", type=int, default=int(env("MOTOR_IN1", 5)), help="BCM pin (env MOTOR_IN1)")
    ap.add_argument("--motor-in2", type=int, default=int(env("MOTOR_IN2", 6)), help="BCM pin (env MOTOR_IN2)")
    ap.add_argument("--motor-enable", type=int, default=int(env("MOTOR_ENABLE", -1)),
                    help="BCM pin wired to the driver's enable input, held high; -1 = none / jumper fitted (env MOTOR_ENABLE)")
    ap.add_argument("--lock-seconds", type=float, default=float(env("LOCK_SECONDS", 0.6)),
                    help="how long the motor runs per lock/unlock (env LOCK_SECONDS)")
    ap.add_argument("--lock-speed", type=float, default=float(env("LOCK_SPEED", 0.6)),
                    help="0-1 motor power (env LOCK_SPEED)")
    ap.add_argument("--locked-switch", type=int, default=env("LOCKED_SWITCH"),
                    help="optional BCM pin of a limit switch closed when locked (env LOCKED_SWITCH)")
    ap.add_argument("--unlocked-switch", type=int, default=env("UNLOCKED_SWITCH"),
                    help="optional BCM pin of a limit switch closed when unlocked (env UNLOCKED_SWITCH)")
    ap.add_argument("--staff-id", default=env("STAFF_ID"), help="for --simulate-staff-ready (env STAFF_ID)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--simulate-staff-ready", action="store_true", help="mark the box's order READY and exit")
    mode.add_argument("--simulate-complete", action="store_true",
                      help="confirm the food was taken (supervised stand-in for a door sensor) and exit")
    args = ap.parse_args()
    if not args.box:
        ap.error("--box (or BOX_ID) is required")
    api = Api(args.api, args.box)

    if args.simulate_staff_ready:
        if not args.staff_id:
            ap.error("--staff-id (or STAFF_ID) is required")
        status, body = api.staff_confirm(args.staff_id)
        ok = status == 200
        log(f"{args.box}: {body.get('order_id')} {'already ready' if body.get('already_confirmed') else 'marked READY'}"
            if ok else f"{args.box}: staff confirm refused ({status}) {body.get('error')}")
        sys.exit(0 if ok else 1)
    if args.simulate_complete:
        status, body = api.complete_pickup()
        if status == 200:
            log(f"{args.box}: {body['order_id']} collected; next order: {body.get('next_order_id') or 'none'}")
            sys.exit(0)
        log(f"{args.box}: complete-pickup refused ({status}) {body.get('error')}")
        sys.exit(1)

    pickup_url = f"{args.public_url.rstrip('/')}/pickup/{urllib.parse.quote(args.box, safe='')}" if args.public_url else ""
    if not pickup_url:
        log("WARNING: no --public-url / PUBLIC_URL, so no QR code on the screen")
    elif "localhost" in pickup_url or "127.0.0.1" in pickup_url:
        log("WARNING: QR points to localhost; use https://novabox.recursivefunctions.dev[/branch]")

    if args.display == "fb":
        display = FramebufferDisplay(args.fb, args.rotate)
    elif args.display == "png":
        display = PngDisplay(args.box)
    else:
        display = type("NoDisplay", (), {"show": lambda self, img: None})()

    if args.lock == "motor":
        enable = None if args.motor_enable < 0 else args.motor_enable
        lock = MotorLock(args.motor_in1, args.motor_in2, enable, args.lock_seconds, args.lock_speed,
                         args.locked_switch, args.unlocked_switch)
    else:
        lock = NoLock()

    log(f"{args.box}: following {args.api}" + (f", QR -> {pickup_url}" if pickup_url else ""))
    run(api, display, lock, pickup_url)


if __name__ == "__main__":
    main()
