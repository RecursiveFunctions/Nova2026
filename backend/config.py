"""Runtime settings, read from environment variables (and backend/.env if present).

Standard library only, so this module is safe to import from anywhere.
Real environment variables always win over values in the .env file.
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader: KEY=VALUE per line, '#' comments, optional quotes."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


def _csv(name: str, default: str) -> list:
    return [p.strip() for p in (os.environ.get(name) or default).split(",") if p.strip()]


def _path(name: str, default: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    path = Path(raw) if raw else default
    return path if path.is_absolute() else BASE_DIR / path


DATABASE_PATH = _path("DATABASE_PATH", BASE_DIR / "data" / "pickup_box.db")

# Shared secret for /demo/* endpoints (header X-Demo-Key). If empty, /demo/* is
# restricted to requests coming from the machine running the API (loopback).
DEMO_API_KEY = (os.environ.get("DEMO_API_KEY") or "").strip()

PICKUP_CODE_TTL_MINUTES = float(os.environ.get("PICKUP_CODE_TTL_MINUTES") or 15)

# After a wrong code, further attempts on the same order are refused (HTTP 429) for
# this long. Attempts are never locked out permanently.
FAILED_ATTEMPT_COOLDOWN_SECONDS = float(os.environ.get("FAILED_ATTEMPT_COOLDOWN_SECONDS") or 1)

BOX_IDS = _csv("BOX_IDS", "BOX-01,BOX-02")
STAFF_RFID_UIDS = _csv("STAFF_RFID_UIDS", "STAFF-TAG-01")
CORS_ORIGINS = _csv("CORS_ORIGINS", "*")


def _pickup_secret() -> bytes:
    """Key used to derive and hash pickup codes. Never stored in the database."""
    from_env = (os.environ.get("PICKUP_CODE_SECRET") or "").strip()
    if from_env:
        return from_env.encode("utf-8")
    path = DATABASE_PATH.parent / ".pickup_secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip().encode("utf-8")
    value = secrets.token_hex(32)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value.encode("utf-8")


PICKUP_CODE_SECRET = _pickup_secret()
