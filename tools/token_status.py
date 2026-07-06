#!/usr/bin/env python3
"""Publish provider API/token-limit status for the dashboards repo.

This script intentionally writes only sanitized status metadata. It never writes
API keys, request bodies containing secrets, or full provider error payloads.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(os.environ.get("DASHBOARD_REPO", str(Path.home() / "pc_agent" / "dashboards-data"))).expanduser()
BRANCH = os.environ.get("DASHBOARD_BRANCH", "data")
DATA = REPO / "data" / "tokens.json"
KEYS_ENV = Path(os.environ.get("PC_KEYS_ENV", str(Path.home() / "pc_agent" / "keys.env"))).expanduser()
LOCAL_KEYS = Path(os.environ.get("PC_LOCAL_KEYS", str(Path.home() / "Documents" / "paper-curation" / "docs" / "_local_keys.json"))).expanduser()

SENSITIVE_RE = re.compile(r"(sk-(?:proj-)?[^\s'\"},]+|AIza[^\s'\"},]+|[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,})")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize(value: Any, max_len: int = 360) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ")
    text = re.sub(r"Incorrect API key provided: .*?https://platform\.openai\.com/account/api-keys\.?", "Incorrect API key provided: ***.", text)
    text = re.sub(r"Incorrect API key provided: [^'\"}]+", "Incorrect API key provided: ***.", text)
    text = SENSITIVE_RE.sub("***", text)
    text = re.sub(r"\*\*\*[A-Za-z0-9]{2,12}", "***", text)
    return text[:max_len]


def run(cmd: list[str], timeout: int = 30):
    try:
        return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except Exception as exc:  # pragma: no cover - status publishing must not crash on git glitches
        class R:
            pass
        r = R()
        r.returncode = 999
        r.stdout = str(exc)
        return r


def load_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    if KEYS_ENV.exists():
        for line in KEYS_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            name, value = line.split("=", 1)
            keys[name.strip()] = value.strip().strip('"').strip("'")
    if LOCAL_KEYS.exists():
        try:
            local = json.loads(LOCAL_KEYS.read_text(encoding="utf-8"))
            for key, value in local.items():
                if isinstance(value, str):
                    keys[key] = value
        except Exception:
            pass
    for key, value in os.environ.items():
        if key.endswith("API_KEY") or key in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"}:
            keys.setdefault(key, value)
    return keys


def request_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: Any = None, timeout: int = 45) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers or {}, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
            latency_ms = int((time.time() - started) * 1000)
            text = raw.decode("utf-8", "replace")
            try:
                parsed = json.loads(text) if text else {}
            except Exception:
                parsed = {"raw": sanitize(text)}
            return {
                "ok": 200 <= resp.status < 300,
                "status_code": resp.status,
                "latency_ms": latency_ms,
                "headers": {k.lower(): v for k, v in resp.headers.items()},
                "json": parsed,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.time() - started) * 1000)
        text = exc.read(2000).decode("utf-8", "replace")
        try:
            parsed = json.loads(text) if text else {}
        except Exception:
            parsed = {"raw": sanitize(text)}
        return {
            "ok": False,
            "status_code": exc.code,
            "latency_ms": latency_ms,
            "headers": {k.lower(): v for k, v in exc.headers.items()},
            "json": parsed,
            "error": sanitize(parsed.get("error", parsed) if isinstance(parsed, dict) else text),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": int((time.time() - started) * 1000),
            "headers": {},
            "json": {},
            "error": sanitize(f"{type(exc).__name__}: {exc}"),
        }


def auth_status(status_code: int | None) -> str:
    if status_code in {401, 403}:
        return "auth_error"
    if status_code == 429:
        return "rate_limited"
    if status_code and status_code >= 500:
        return "provider_error"
    return "error"


def header_token_window(headers: dict[str, str], provider: str) -> dict[str, Any]:
    def pick(*names: str):
        for name in names:
            if name.lower() in headers:
                return headers[name.lower()]
        return None

    if provider == "openai":
        limit = pick("x-ratelimit-limit-tokens")
        remaining = pick("x-ratelimit-remaining-tokens")
        reset = pick("x-ratelimit-reset-tokens")
        req_limit = pick("x-ratelimit-limit-requests")
        req_remaining = pick("x-ratelimit-remaining-requests")
        req_reset = pick("x-ratelimit-reset-requests")
    elif provider == "anthropic":
        limit = pick("anthropic-ratelimit-tokens-limit", "x-ratelimit-limit-tokens")
        remaining = pick("anthropic-ratelimit-tokens-remaining", "x-ratelimit-remaining-tokens")
        reset = pick("anthropic-ratelimit-tokens-reset", "x-ratelimit-reset-tokens")
        req_limit = pick("anthropic-ratelimit-requests-limit", "x-ratelimit-limit-requests")
        req_remaining = pick("anthropic-ratelimit-requests-remaining", "x-ratelimit-remaining-requests")
        req_reset = pick("anthropic-ratelimit-requests-reset", "x-ratelimit-reset-requests")
    else:
        limit = pick("x-ratelimit-limit-tokens", "x-ratelimit-limit")
        remaining = pick("x-ratelimit-remaining-tokens", "x-ratelimit-remaining")
        reset = pick("x-ratelimit-reset-tokens", "x-ratelimit-reset")
        req_limit = pick("x-ratelimit-limit-requests")
        req_remaining = pick("x-ratelimit-remaining-requests")
        req_reset = pick("x-ratelimit-reset-requests")

    available = any(v is not None for v in [limit, remaining, reset, req_limit, req_remaining, req_reset])
    return {
        "available": available,
        "source": "response rate-limit headers",
        "tokens": {"limit": limit, "remaining": remaining, "reset": reset},
        "requests": {"limit": req_limit, "remaining": req_remaining, "reset": req_reset},
    }


def extract_openai_costs(resp: dict[str, Any]) -> dict[str, Any]:
    if not resp["ok"]:
        detail = "Cost endpoint unavailable."
        if resp["status_code"] in {401, 403}:
            detail = "Cost endpoint unavailable: invalid or non-admin OpenAI key."
        elif resp.get("error"):
            detail = resp["error"]
        return {"available": False, "status_code": resp["status_code"], "detail": detail}
    data = resp.get("json", {})
    total = 0.0
    currency = None
    for bucket in data.get("data", []) if isinstance(data, dict) else []:
        for item in bucket.get("results", []) or []:
            amount = item.get("amount", {}) if isinstance(item, dict) else {}
            value = amount.get("value")
            if isinstance(value, (int, float)):
                total += float(value)
            currency = currency or amount.get("currency")
    return {"available": True, "month_to_date_cost": round(total, 4), "currency": currency or "usd"}


def make_provider(provider_id: str, label: str) -> dict[str, Any]:
    return {
        "id": provider_id,
        "label": label,
        "status": "unknown",
        "connection": {"ok": False, "detail": "Not checked."},
        "model_probe": {},
        "token_window": {"available": False, "source": "not checked"},
        "billing": {"available": False, "detail": "Not checked."},
        "notes": [],
    }


def probe_openai(keys: dict[str, str]) -> dict[str, Any]:
    p = make_provider("openai", "OpenAI")
    key = keys.get("OPENAI_API_KEY") or keys.get("openai_key")
    if not key:
        p["status"] = "missing"
        p["connection"] = {"ok": False, "detail": "OPENAI_API_KEY/openai_key not found on Mac mini."}
        return p
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
    resp = request_json("https://api.openai.com/v1/chat/completions", method="POST", headers=headers, body=body)
    p["model_probe"] = {"model": "gpt-4o-mini", "status_code": resp["status_code"], "latency_ms": resp["latency_ms"]}
    p["token_window"] = header_token_window(resp["headers"], "openai")
    if resp["ok"]:
        p["status"] = "ok"
        p["connection"] = {"ok": True, "detail": "Generation API responded."}
    else:
        p["status"] = auth_status(resp["status_code"])
        detail = "Invalid OpenAI API key configured on Mac mini." if resp["status_code"] in {401, 403} else (resp.get("error") or f"HTTP {resp['status_code']}")
        p["connection"] = {"ok": False, "detail": detail}

    start = int(datetime(datetime.now(timezone.utc).year, datetime.now(timezone.utc).month, 1, tzinfo=timezone.utc).timestamp())
    costs = request_json(f"https://api.openai.com/v1/organization/costs?start_time={start}&bucket_width=1d&limit=31", headers={"Authorization": f"Bearer {key}"})
    p["billing"] = extract_openai_costs(costs)
    if not p["token_window"].get("available"):
        p["notes"].append("Token remaining/reset was not exposed in this response. A valid key or a billable model response is usually required.")
    return p


def probe_anthropic(keys: dict[str, str]) -> dict[str, Any]:
    p = make_provider("anthropic", "Anthropic")
    key = keys.get("ANTHROPIC_API_KEY") or keys.get("anthropic_key")
    if not key:
        p["status"] = "missing"
        p["connection"] = {"ok": False, "detail": "ANTHROPIC_API_KEY/anthropic_key not found on Mac mini."}
        return p
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    model = os.environ.get("ANTHROPIC_STATUS_MODEL", "claude-3-5-haiku-20241022")
    body = {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]}
    resp = request_json("https://api.anthropic.com/v1/messages", method="POST", headers=headers, body=body)
    p["model_probe"] = {"model": model, "status_code": resp["status_code"], "latency_ms": resp["latency_ms"]}
    p["token_window"] = header_token_window(resp["headers"], "anthropic")
    if resp["ok"]:
        p["status"] = "ok"
        p["connection"] = {"ok": True, "detail": "Messages API responded."}
    else:
        p["status"] = auth_status(resp["status_code"])
        detail = "Invalid Anthropic API key configured on Mac mini." if resp["status_code"] in {401, 403} else (resp.get("error") or f"HTTP {resp['status_code']}")
        p["connection"] = {"ok": False, "detail": detail}
    p["billing"] = {"available": False, "detail": "Anthropic billing/usage totals require Admin API access; no admin key configured."}
    if not p["token_window"].get("available"):
        p["notes"].append("Token remaining/reset headers were not available because the model request did not succeed or the provider omitted them.")
    return p


def choose_gemini_model(models_resp: dict[str, Any]) -> str:
    preferred = ["models/gemini-2.5-flash", "models/gemini-2.0-flash", "models/gemini-1.5-flash"]
    models = models_resp.get("json", {}).get("models", []) if isinstance(models_resp.get("json"), dict) else []
    names = {m.get("name") for m in models if isinstance(m, dict)}
    for name in preferred:
        if name in names:
            return name
    for model in models:
        if not isinstance(model, dict):
            continue
        methods = model.get("supportedGenerationMethods") or []
        if "generateContent" in methods and model.get("name"):
            return model["name"]
    return "models/gemini-2.5-flash"


def probe_gemini(keys: dict[str, str]) -> dict[str, Any]:
    p = make_provider("gemini", "Gemini")
    key = keys.get("GOOGLE_API_KEY") or keys.get("GEMINI_API_KEY") or keys.get("google_api_key") or keys.get("gemini_api_key")
    if not key:
        p["status"] = "missing"
        p["connection"] = {"ok": False, "detail": "GOOGLE_API_KEY/GEMINI_API_KEY not found on Mac mini."}
        return p
    models = request_json(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}")
    model = choose_gemini_model(models) if models["ok"] else "models/gemini-2.5-flash"
    body = {"contents": [{"parts": [{"text": "ping"}]}], "generationConfig": {"maxOutputTokens": 1}}
    resp = request_json(f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={key}", method="POST", headers={"Content-Type": "application/json"}, body=body)
    usage = resp.get("json", {}).get("usageMetadata", {}) if isinstance(resp.get("json"), dict) else {}
    p["model_probe"] = {"model": model.replace("models/", ""), "status_code": resp["status_code"], "latency_ms": resp["latency_ms"], "usage": usage}
    p["token_window"] = header_token_window(resp["headers"], "gemini")
    if resp["ok"]:
        p["status"] = "ok"
        p["connection"] = {"ok": True, "detail": "Generative Language API responded."}
    else:
        p["status"] = auth_status(resp["status_code"])
        detail = "Invalid Gemini API key configured on Mac mini." if resp["status_code"] in {401, 403} else (resp.get("error") or f"HTTP {resp['status_code']}")
        p["connection"] = {"ok": False, "detail": detail}
    p["billing"] = {"available": False, "detail": "Gemini API keys do not expose project quota remaining through this endpoint; use Google Cloud quota APIs with project credentials for exact remaining quota."}
    if not p["token_window"].get("available"):
        p["notes"].append("No rate-limit token headers were exposed. The page shows API connectivity and per-probe token usage instead.")
    return p


def status_rank(status: str) -> int:
    return {"ok": 0, "rate_limited": 1, "missing": 2, "auth_error": 3, "provider_error": 3, "error": 3}.get(status, 2)


def load_prev_events() -> list[dict[str, str]]:
    try:
        return json.loads(DATA.read_text(encoding="utf-8")).get("events", [])[-20:]
    except Exception:
        return []


def main() -> None:
    keys = load_keys()
    updated = now_iso()
    providers = [probe_openai(keys), probe_anthropic(keys), probe_gemini(keys)]
    worst = max((status_rank(p["status"]) for p in providers), default=2)
    overall = "ok" if worst == 0 else "warn" if worst <= 2 else "bad"
    connected = sum(1 for p in providers if p.get("connection", {}).get("ok"))
    events = load_prev_events()
    data = {
        "host": socket.gethostname(),
        "updated_at": updated,
        "overall": overall,
        "summary": f"{connected}/{len(providers)} provider APIs connected.",
        "providers": providers,
        "events": (events + [{"time": updated, "message": f"tokens overall={overall}, connected={connected}/{len(providers)}"}])[-20:],
    }

    DATA.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "config", "user.name", "Mac mini Token Status"], 10)
    run(["git", "config", "user.email", "tokens@jehyunlee.dev"], 10)
    run(["git", "pull", "--rebase", "origin", BRANCH], 60)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cp = run(["git", "status", "--short", "data/tokens.json"], 20)
    if cp.stdout.strip():
        run(["git", "add", "data/tokens.json"], 20)
        commit = run(["git", "commit", "-q", "-m", f"tokens: provider status {updated}"], 30)
        if commit.returncode != 0:
            print("commit failed:", sanitize(commit.stdout))
        push = run(["git", "push", "origin", BRANCH], 60)
        if push.returncode != 0:
            print("push failed; pulling/retrying:", sanitize(push.stdout))
            run(["git", "pull", "--rebase", "origin", BRANCH], 60)
            push = run(["git", "push", "origin", BRANCH], 60)
        print(push.stdout.strip())
    print(json.dumps({"updated_at": updated, "overall": overall, "connected": connected, "providers": {p["id"]: p["status"] for p in providers}}, ensure_ascii=False))


if __name__ == "__main__":
    os.chdir(REPO)
    main()
