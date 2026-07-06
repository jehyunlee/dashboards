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
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(os.environ.get("DASHBOARD_REPO", str(Path.home() / "pc_agent" / "dashboards-data"))).expanduser()
BRANCH = os.environ.get("DASHBOARD_BRANCH", "data")
DATA = REPO / "data" / "tokens.json"
HISTORY = REPO / "data" / "tokens_history.json"
HISTORY_MAX = int(os.environ.get("PC_TOKENS_HISTORY_MAX", "720"))
KEYS_ENV = Path(os.environ.get("PC_KEYS_ENV", str(Path.home() / "pc_agent" / "keys.env"))).expanduser()
LOCAL_KEYS = Path(os.environ.get("PC_LOCAL_KEYS", str(Path.home() / "Documents" / "paper-curation" / "docs" / "_local_keys.json"))).expanduser()
DASHBOARD_KEYS = Path(os.environ.get("PC_DASHBOARD_KEYS", str(Path.home() / "pc_agent" / "dashboard_keys.json"))).expanduser()
OTEL_USAGE = Path(os.environ.get("PC_OTEL_USAGE", str(Path.home() / "pc_agent" / "otel" / "usage_local.json"))).expanduser()
OTEL_USAGE_API = Path(os.environ.get("PC_OTEL_USAGE_API", str(Path.home() / "pc_agent" / "otel" / "usage_api_local.json"))).expanduser()

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
def number_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None




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
    if DASHBOARD_KEYS.exists():
        try:
            for key, value in json.loads(DASHBOARD_KEYS.read_text(encoding="utf-8")).items():
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
            detail = "Organization cost not shown: configured key cannot access the OpenAI cost endpoint."
        elif resp.get("error"):
            detail = resp["error"]
        return {"available": False, "status_code": resp["status_code"], "detail": detail}
    data = resp.get("json", {})
    total = 0.0
    currency = None
    rows = 0
    buckets = data.get("data", []) if isinstance(data, dict) else []
    for bucket in buckets:
        for item in bucket.get("results", []) or []:
            rows += 1
            amount = item.get("amount", {}) if isinstance(item, dict) else {}
            value = number_value(amount.get("value"))
            if value is not None:
                total += value
            currency = currency or amount.get("currency")
    return {"available": True, "month_to_date_cost": round(total, 4), "currency": currency or "usd", "rows": rows, "buckets": len(buckets)}
def openai_admin_inventory(admin_key: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {admin_key}"}
    projects_resp = request_json("https://api.openai.com/v1/organization/projects?limit=100", headers=headers)
    if not projects_resp["ok"]:
        return {"available": False, "detail": projects_resp.get("error") or f"HTTP {projects_resp['status_code']}"}
    projects = projects_resp.get("json", {}).get("data", [])
    project_count = len(projects) if isinstance(projects, list) else 0
    api_key_count = 0
    service_account_count = 0
    for project in projects if isinstance(projects, list) else []:
        project_id = project.get("id")
        if not project_id:
            continue
        keys_resp = request_json(f"https://api.openai.com/v1/organization/projects/{project_id}/api_keys?limit=100", headers=headers, timeout=20)
        if keys_resp["ok"]:
            api_key_count += len(keys_resp.get("json", {}).get("data", []) or [])
        service_resp = request_json(f"https://api.openai.com/v1/organization/projects/{project_id}/service_accounts?limit=100", headers=headers, timeout=20)
        if service_resp["ok"]:
            service_account_count += len(service_resp.get("json", {}).get("data", []) or [])
    return {
        "available": True,
        "project_count": project_count,
        "api_key_count": api_key_count,
        "service_account_count": service_account_count,
    }
def openai_spend_alerts(admin_key: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {admin_key}"}
    resp = request_json("https://api.openai.com/v1/organization/spend_alerts", headers=headers, timeout=20)
    if not resp["ok"]:
        return {"available": False, "detail": resp.get("error") or f"HTTP {resp['status_code']}"}
    alerts = []
    for item in resp.get("json", {}).get("data", []) or []:
        cents = item.get("threshold_amount")
        amount_usd = (float(cents) / 100.0) if isinstance(cents, (int, float)) else None
        alerts.append({
            "id": item.get("id"),
            "interval": item.get("interval"),
            "currency": item.get("currency") or "USD",
            "threshold_usd": amount_usd,
        })
    return {"available": True, "alerts": alerts}


def extract_openai_usage(resp: dict[str, Any]) -> dict[str, Any]:
    if not resp["ok"]:
        return {"available": False, "status_code": resp["status_code"], "detail": resp.get("error") or f"HTTP {resp['status_code']}"}
    data = resp.get("json", {})
    rows = 0
    metrics: dict[str, float] = {}
    buckets = data.get("data", []) if isinstance(data, dict) else []
    for bucket in buckets:
        for item in bucket.get("results", []) or []:
            rows += 1
            if not isinstance(item, dict):
                continue
            for key, value in item.items():
                if key in {"start_time", "end_time"}:
                    continue
                if isinstance(value, (int, float)):
                    metrics[key] = metrics.get(key, 0) + float(value)
    return {"available": True, "rows": rows, "buckets": len(buckets), "metrics": metrics}


def openai_month_usage(admin_key: str, start: int) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {admin_key}"}
    endpoints = {
        "completions": "/v1/organization/usage/completions",
        "embeddings": "/v1/organization/usage/embeddings",
        "audio_speeches": "/v1/organization/usage/audio_speeches",
    }
    by_endpoint: dict[str, Any] = {}
    for name, path in endpoints.items():
        resp = request_json(f"https://api.openai.com{path}?start_time={start}&bucket_width=1d&limit=31", headers=headers, timeout=45)
        by_endpoint[name] = extract_openai_usage(resp)

    completions = by_endpoint.get("completions", {}).get("metrics", {})
    embeddings = by_endpoint.get("embeddings", {}).get("metrics", {})
    speeches = by_endpoint.get("audio_speeches", {}).get("metrics", {})

    completion_input = int(completions.get("input_tokens", 0))
    completion_output = int(completions.get("output_tokens", 0))
    embedding_input = int(embeddings.get("input_tokens", 0))
    speech_characters = int(speeches.get("characters", 0))
    total_requests = int(
        sum((endpoint.get("metrics", {}).get("num_model_requests", 0) or endpoint.get("metrics", {}).get("num_requests", 0) or 0) for endpoint in by_endpoint.values())
    )
    total_tokens = completion_input + completion_output + embedding_input
    rows = sum(int(endpoint.get("rows", 0) or 0) for endpoint in by_endpoint.values())
    return {
        "available": any(endpoint.get("available") for endpoint in by_endpoint.values()),
        "source": "OpenAI organization usage endpoints",
        "rows": rows,
        "total_tokens": total_tokens,
        "total_requests": total_requests,
        "completion_input_tokens": completion_input,
        "completion_output_tokens": completion_output,
        "embedding_input_tokens": embedding_input,
        "audio_speech_characters": speech_characters,
        "endpoints": by_endpoint,
    }






def _bin_key(dt: datetime, bin_min: int) -> str:
    m = (dt.minute // bin_min) * bin_min
    return dt.replace(minute=m, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:00Z")


def _empty_bins(now: datetime, span_min: int, bin_min: int) -> dict[str, int]:
    end = now.replace(second=0, microsecond=0)
    end = end.replace(minute=(end.minute // bin_min) * bin_min)
    n = span_min // bin_min
    bins: dict[str, int] = {}
    for i in range(n):
        t = end - timedelta(minutes=bin_min * (n - 1 - i))
        bins[t.strftime("%Y-%m-%dT%H:%M:00Z")] = 0
    return bins


def openai_usage_series(admin_key: str, now: datetime, span_min: int = 180, bin_min: int = 5) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {admin_key}"}
    start = int((now - timedelta(minutes=span_min)).timestamp())
    bins = _empty_bins(now, span_min, bin_min)
    ok = False
    for ep in ("completions", "embeddings"):
        resp = request_json(f"https://api.openai.com/v1/organization/usage/{ep}?start_time={start}&bucket_width=1m&limit={span_min}", headers=headers, timeout=45)
        if not resp["ok"]:
            continue
        ok = True
        for bucket in resp.get("json", {}).get("data", []) or []:
            st = bucket.get("start_time")
            if st is None:
                continue
            key = _bin_key(datetime.fromtimestamp(st, timezone.utc), bin_min)
            if key not in bins:
                continue
            for r in bucket.get("results", []) or []:
                bins[key] += int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0)
    return {"available": ok, "bin_seconds": bin_min * 60, "span_minutes": span_min, "points": [{"t": k, "tokens": v} for k, v in sorted(bins.items())]}


def anthropic_usage_series(admin_key: str, now: datetime, span_min: int = 180, bin_min: int = 5) -> dict[str, Any]:
    headers = {"x-api-key": admin_key, "anthropic-version": "2023-06-01"}
    base = {"starting_at": (now - timedelta(minutes=span_min)).strftime("%Y-%m-%dT%H:%M:00Z"), "bucket_width": "1m", "limit": "60"}
    bins = _empty_bins(now, span_min, bin_min)
    url = "https://api.anthropic.com/v1/organizations/usage_report/messages?" + urllib.parse.urlencode(base)
    ok = False
    pages = 0
    while url and pages < 8:
        resp = request_json(url, headers=headers, timeout=45)
        if not resp["ok"]:
            break
        ok = True
        body = resp.get("json", {})
        for bucket in body.get("data", []) or []:
            st = bucket.get("starting_at")
            if not st:
                continue
            try:
                bt = datetime.strptime(st, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            key = _bin_key(bt, bin_min)
            if key not in bins:
                continue
            for r in bucket.get("results", []) or []:
                bins[key] += int(r.get("uncached_input_tokens") or 0) + int(r.get("output_tokens") or 0) + int(r.get("cache_read_input_tokens") or 0)
                cc = r.get("cache_creation") or {}
                if isinstance(cc, dict):
                    bins[key] += int(cc.get("ephemeral_1h_input_tokens") or 0) + int(cc.get("ephemeral_5m_input_tokens") or 0)
        if body.get("has_more") and body.get("next_page"):
            nxt = dict(base)
            nxt["page"] = body["next_page"]
            url = "https://api.anthropic.com/v1/organizations/usage_report/messages?" + urllib.parse.urlencode(nxt)
            pages += 1
        else:
            url = None
    return {"available": ok, "bin_seconds": bin_min * 60, "span_minutes": span_min, "points": [{"t": k, "tokens": v} for k, v in sorted(bins.items())]}

def _bins_series(path: Path, provider_id: str, now: datetime, source: str, span_min: int = 180, bin_min: int = 5) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "detail": "No telemetry data yet."}
    bins = state.get("bins", {})
    step = bin_min * 60
    end = (int(now.timestamp()) // step) * step
    n = span_min // bin_min
    points = []
    total = 0.0
    cost = 0.0
    for i in range(n):
        bstart = end - step * (n - 1 - i)
        rec = bins.get(str(bstart), {}).get(provider_id)
        tok = int(rec.get("tokens", 0)) if rec else 0
        if rec:
            cost += float(rec.get("cost", 0) or 0)
        total += tok
        points.append({"t": datetime.fromtimestamp(bstart, timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"), "tokens": tok})
    return {
        "available": True,
        "source": source,
        "bin_seconds": step,
        "span_minutes": span_min,
        "points": points,
        "window_tokens": int(total),
        "window_cost": round(cost, 4),
    }


def subscription_series(provider_id: str, now: datetime) -> dict[str, Any]:
    return _bins_series(OTEL_USAGE, provider_id, now, "Claude Code / Codex / Gemini CLI OpenTelemetry (subscription)")


def pipeline_api_series(provider_id: str, now: datetime) -> dict[str, Any]:
    return _bins_series(OTEL_USAGE_API, provider_id, now, "Pipeline-instrumented API usage")

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
    admin_key = keys.get("OPENAI_ADMIN_API_KEY") or keys.get("OPENAI_ADMIN_KEY")
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

    start = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp())
    billing_key = admin_key or key
    costs = request_json(f"https://api.openai.com/v1/organization/costs?start_time={start}&bucket_width=1d&limit=31", headers={"Authorization": f"Bearer {billing_key}"})
    p["billing"] = extract_openai_costs(costs)
    p["billing"]["window"] = "last_30d"
    if p["billing"].get("available"):
        p["billing"]["source"] = "OpenAI organization costs endpoint"
        if admin_key:
            usage = openai_month_usage(admin_key, start)
            p["billing"]["usage"] = usage
            p["billing"]["account_token_quota"] = {
                "available": False,
                "detail": "OpenAI API accounts do not expose a fixed cumulative account-token allowance or remaining-token balance through the Admin API. The available account-level controls are rate limits, usage/cost reporting, prepaid billing UI, and spend alerts.",
            }
            p["billing"]["spend_alerts"] = openai_spend_alerts(admin_key)
            p["usage_series"] = openai_usage_series(admin_key, datetime.now(timezone.utc))
            if usage.get("total_tokens", 0) > 0 and p["billing"].get("month_to_date_cost") == 0:
                p["billing"]["detail"] = "Usage endpoint shows month-to-date OpenAI API activity, but the cost endpoint currently returns 0 USD/no cost rows. Treat token usage as the reliable signal here; cost may lag or be hidden by billing setup."
                p["billing"]["confidence"] = "usage_visible_cost_zero"
        if admin_key:
            inventory = openai_admin_inventory(admin_key)
            p["billing"]["admin_inventory"] = inventory
            if (
                p["billing"].get("month_to_date_cost") == 0
                and inventory.get("available")
                and inventory.get("api_key_count") == 0
                and inventory.get("service_account_count") == 0
            ):
                p["billing"]["detail"] = "Admin key cost endpoint is reachable, but this OpenAI organization has 0 project API keys and 0 service accounts. The displayed 0 USD is probably for the wrong/empty organization, not the heavy Gajae Code workload."
                p["billing"]["confidence"] = "suspect_org_mismatch"
    elif not admin_key:
        p["billing"]["detail"] = "Organization cost not shown: OPENAI_ADMIN_API_KEY/OPENAI_ADMIN_KEY is not configured; rate-limit data above is from the normal API key."
    if not p["token_window"].get("available"):
        p["notes"].append("Token remaining/reset was not exposed in this response. A valid key or a billable model response is usually required.")
    return p


def anthropic_admin_usage_cost(admin_key: str, start_iso: str) -> dict[str, Any]:
    headers = {"x-api-key": admin_key, "anthropic-version": "2023-06-01"}
    cost_url = "https://api.anthropic.com/v1/organizations/cost_report?" + urllib.parse.urlencode({"starting_at": start_iso})
    cost_resp = request_json(cost_url, headers=headers, timeout=45)
    total_cost = 0.0
    for bucket in (cost_resp.get("json", {}).get("data", []) or []) if cost_resp["ok"] else []:
        for r in bucket.get("results", []) or []:
            v = number_value(r.get("amount"))
            if v is not None:
                total_cost += v
    usage_url = "https://api.anthropic.com/v1/organizations/usage_report/messages?" + urllib.parse.urlencode({"starting_at": start_iso, "bucket_width": "1d"})
    usage_resp = request_json(usage_url, headers=headers, timeout=45)
    input_tokens = output_tokens = cache_read = cache_creation = 0
    for bucket in (usage_resp.get("json", {}).get("data", []) or []) if usage_resp["ok"] else []:
        for r in bucket.get("results", []) or []:
            input_tokens += int(r.get("uncached_input_tokens") or 0)
            output_tokens += int(r.get("output_tokens") or 0)
            cache_read += int(r.get("cache_read_input_tokens") or 0)
            cc = r.get("cache_creation") or {}
            if isinstance(cc, dict):
                cache_creation += int(cc.get("ephemeral_1h_input_tokens") or 0) + int(cc.get("ephemeral_5m_input_tokens") or 0)
    total_tokens = input_tokens + output_tokens + cache_read + cache_creation
    if not cost_resp["ok"] and not usage_resp["ok"]:
        detail = cost_resp.get("error") or usage_resp.get("error") or "Anthropic admin report unavailable."
        return {"available": False, "detail": detail}
    return {
        "available": True,
        "source": "Anthropic organization cost/usage report",
        "window": "last_30d",
        "month_to_date_cost": round(total_cost, 4),
        "currency": "usd",
        "cost_available": cost_resp["ok"],
        "usage": {
            "available": usage_resp["ok"],
            "total_tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_creation,
        },
    }


def probe_anthropic(keys: dict[str, str]) -> dict[str, Any]:
    p = make_provider("anthropic", "Anthropic")
    key = keys.get("ANTHROPIC_API_KEY") or keys.get("anthropic_key")
    if not key:
        p["status"] = "missing"
        p["connection"] = {"ok": False, "detail": "ANTHROPIC_API_KEY/anthropic_key not found on Mac mini."}
        return p
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    model = os.environ.get("ANTHROPIC_STATUS_MODEL", "claude-haiku-4-5-20251001")
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
    admin_key = keys.get("ANTHROPIC_ADMIN_API_KEY") or keys.get("ANTHROPIC_ADMIN_KEY")
    if admin_key:
        start_iso = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
        report = anthropic_admin_usage_cost(admin_key, start_iso)
        if report.get("available"):
            p["billing"] = report
        else:
            p["billing"] = {"available": False, "detail": f"Anthropic admin usage/cost unavailable: {report.get('detail')}"}
        p["usage_series"] = anthropic_usage_series(admin_key, datetime.now(timezone.utc))
    else:
        p["billing"] = {"available": False, "detail": "Monthly usage/cost not shown: Anthropic Admin API key is not configured; Messages API connectivity and rate-limit headers above are valid."}
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


def build_history_entry(providers: list[dict[str, Any]], t: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"t": t}
    for p in providers:
        tw = (p.get("token_window") or {}).get("tokens") or {}
        api_limit = number_value(tw.get("limit"))
        api_remaining = number_value(tw.get("remaining"))
        api_used = None
        if api_limit is not None and api_remaining is not None:
            api_used = max(0, int(round(api_limit - api_remaining)))
        usage = (p.get("billing") or {}).get("usage") or {}
        account_tokens = usage.get("total_tokens") if usage.get("available") else None
        entry[p["id"]] = {
            "connected": 1 if (p.get("connection") or {}).get("ok") else 0,
            "account_tokens": account_tokens,
            "api_used": api_used,
            "api_limit": int(api_limit) if api_limit is not None else None,
        }
    return entry


def load_history() -> list[dict[str, Any]]:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8")).get("samples", [])
    except Exception:
        return []


def main() -> None:
    keys = load_keys()
    updated = now_iso()
    providers = [probe_openai(keys), probe_anthropic(keys), probe_gemini(keys)]
    _sub_now = datetime.now(timezone.utc)
    for _p in providers:
        if _p["id"] in ("anthropic", "openai"):
            _p["subscription_series"] = subscription_series(_p["id"], _sub_now)
        if _p["id"] == "gemini":
            # Gemini has no admin usage API; the metered (API) series comes from
            # pipeline instrumentation reported to the local usage receiver.
            _p["usage_series"] = pipeline_api_series("gemini", _sub_now)
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
    samples = load_history()
    samples.append(build_history_entry(providers, updated))
    samples = samples[-HISTORY_MAX:]
    history = {"updated_at": updated, "interval_seconds": 300, "max_samples": HISTORY_MAX, "samples": samples}
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    HISTORY.write_text(json.dumps(history, ensure_ascii=False) + "\n", encoding="utf-8")
    run(["git", "add", "data/tokens.json", "data/tokens_history.json"], 20)
    cp = run(["git", "status", "--short", "data/tokens.json", "data/tokens_history.json"], 20)
    if cp.stdout.strip():
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
