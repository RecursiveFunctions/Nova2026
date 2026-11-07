"""Classify a free-text customer complaint with the laptop llama-server.

Default target is Gemma 4 26B-A4B HauhauCS Q4_K_M on yeetcoder-wsl :8790
(OpenAI-compatible /v1/chat/completions).
"""
import json
import re
import urllib.error
import urllib.request

import config
from logic import ApiError

_CATEGORIES = ("missing_item", "wrong_order", "quality", "other")
_SEVERITIES = ("low", "medium", "high")

_PROMPT = (
    "You triage pickup-box customer complaints for restaurant staff.\n"
    "Reply with one JSON object and nothing else:\n"
    '{"category":"missing_item|wrong_order|quality|other",'
    '"severity":"low|medium|high","action":"one short sentence"}\n'
    "A missing utensil is low: apologize. A completely wrong order is high: refund or remake.\n"
    "Customer text:\n"
)


def _request(method: str, path: str, payload: dict = None):
    url = config.TRIAGE_LLM_BASE_URL.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if config.TRIAGE_LLM_API_KEY:
        headers["Authorization"] = "Bearer " + config.TRIAGE_LLM_API_KEY
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=config.TRIAGE_LLM_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        raise ApiError(502, f"LLM HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ApiError(502, f"LLM unreachable: {exc}") from exc


def _prefer_gemma(ids: list) -> str:
    lowered = [(i, i.lower()) for i in ids]
    for raw, name in lowered:
        if "gemma" in name and ("26" in name or "hauhau" in name):
            return raw
    for raw, name in lowered:
        if "gemma" in name:
            return raw
    raise ApiError(502, "laptop llama-server is not serving Gemma 4 26B-A4B")


def _model() -> str:
    if config.TRIAGE_LLM_MODEL:
        return config.TRIAGE_LLM_MODEL
    listed = _request("GET", "/models")
    ids = [m.get("id") for m in listed.get("data") or [] if m.get("id")]
    return _prefer_gemma(ids)


def _parse(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S | re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ApiError(502, "LLM did not return JSON")
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ApiError(502, "LLM returned invalid JSON") from exc
    category = str(obj.get("category") or "other").strip().lower()
    severity = str(obj.get("severity") or "medium").strip().lower()
    action = str(obj.get("action") or "Review with staff.").strip()[:240]
    if category not in _CATEGORIES:
        category = "other"
    if severity not in _SEVERITIES:
        severity = "medium"
    return {"category": category, "severity": severity, "action": action}


def classify(description: str) -> dict:
    model = _model()
    data = _request("POST", "/chat/completions", {
        "model": model,
        "temperature": 0,
        "max_tokens": 80,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": _PROMPT + description.strip()}],
    })
    try:
        message = data["choices"][0]["message"]
        content = message.get("content") or message.get("reasoning_content") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise ApiError(502, "LLM response missing message content") from exc
    result = _parse(content)
    result["model"] = model
    return result
