"""Estimate prep time for an order with the laptop llama-server.

Experimental: the deterministic latest-safe-start scheduler in logic.py is unchanged. This only
fills in `estimated_prep_minutes` and records which model produced it, so the box screen can show
"Time estimated by <model>".

Uses the same laptop llama-server as triage.py (config.PREP_LLM_*), off by default: set
PREP_ENABLED=1 to try it. Standard library only (urllib), matching config.py. Every failure path
returns None so the caller falls back to the submitted prep time and an order never fails to
ingest because the laptop model is down, slow, or chatty.
"""
import json
import logging
import urllib.error
import urllib.request

import config

log = logging.getLogger("pickupbox.prep")

# A model that returns garbage must not wreck the queue order. Anything outside this range falls
# back to the submitted value.
MIN_MINUTES = 1
MAX_MINUTES = 240


def estimate(items: list, platform: str = "") -> tuple | None:
    """Return (minutes, model_name) for an order's items, or None to keep the submitted prep time.

    Reads its settings from config on every call so .env changes need no import tricks.
    Never raises.
    """
    if not config.PREP_ENABLED or not items:
        return None
    lines = "; ".join(f"{i['quantity']}x {i['name']}" for i in items)
    prompt = (
        "You estimate kitchen preparation time for a restaurant order about to be handed to a "
        f"delivery courier.{f' Platform: {platform}.' if platform else ''}\n"
        f"Order: {lines}\n"
        "Reply with ONLY a JSON object like {\"prep_minutes\": 12} - a whole number of minutes "
        f"between {MIN_MINUTES} and {MAX_MINUTES} for this order alone, no explanation."
    )
    body = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 60,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    headers = {"Content-Type": "application/json"}
    if config.PREP_LLM_API_KEY:
        headers["Authorization"] = "Bearer " + config.PREP_LLM_API_KEY
    request = urllib.request.Request(f"{config.PREP_LLM_BASE_URL}/chat/completions",
                                     data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=config.PREP_LLM_TIMEOUT) as response:
            payload = json.loads(response.read())
        content = payload["choices"][0]["message"]["content"] or ""
        if not content:
            # Gemma on llama-server writes its answer into reasoning_content unless thinking is
            # disabled; triage.py hit the same thing. Ask for no thinking and read both fields.
            content = payload["choices"][0]["message"].get("reasoning_content") or ""
        model_used = payload.get("model") or config.PREP_LLM_MODEL or "laptop model"
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as err:
        log.warning("prep estimate unavailable (%s); using submitted prep time", err)
        return None
    return _parse(content, model_used)


def _parse(content: str, model_used: str) -> tuple | None:
    """Extract the minute count from a model reply that may not be clean JSON."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        minutes = json.loads(text).get("prep_minutes")
    except (ValueError, AttributeError):
        minutes = None
    if minutes is None:
        digits = "".join(ch for ch in text if ch.isdigit())
        minutes = int(digits) if digits else None
    if not isinstance(minutes, int) or not MIN_MINUTES <= minutes <= MAX_MINUTES:
        log.warning("prep estimate out of range or unparseable (%r); using submitted prep time", content)
        return None
    return minutes, model_used