#!/usr/bin/env python3
"""Report Gajae Code (gjc) token usage to the Mac mini receiver and GitHub data branch.

Gajae Code persists every assistant message to session JSONL at
  ~/.gjc/agent/sessions/--<cwd>--/<ts>_<id>.jsonl
Each `message` entry carries {provider, model, usage{input,output,cacheRead,cacheWrite,cost}}.

- anthropic / openai (active OAuth subscription): reported to subscription series
  (Claude Code 구독 / Codex 구독)
- google / gemini: reported to Gemini metered API usage_series + 30d billing
  (since Google has no organization usage Admin API)

Even when the Mac mini OTel receiver (usage.jehyunlee.dev / 100.114.66.16:4318)
is unreachable, this script writes local OTel bin files and publishes
`data/gjc_macbook.json` + merged `data/tokens.json` directly to the `data`
branch of `jehyunlee/dashboards` so the live dashboard stays up to date.
"""
from __future__ import annotations

import glob
import json
import os
import socket
import sqlite3
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
SESS_DIR = Path(os.environ.get("GJC_SESS_DIR", str(Path.home() / ".gjc" / "agent" / "sessions")))
GJC_DB = Path(os.environ.get("GJC_AGENT_DB", str(Path.home() / ".gjc" / "agent" / "agent.db")))
ENDPOINTS = [
    e.strip()
    for e in os.environ.get(
        "PC_GJC_USAGE_ENDPOINTS",
        os.environ.get("PC_GJC_USAGE_ENDPOINT", "http://localhost:4318/gjc/usage"),
    ).split(",")
    if e.strip()
]
PC_ENDPOINTS = [
    e.replace("/gjc/usage", "/pc/usage") if "/gjc/usage" in e else e
    for e in ENDPOINTS
]
TOKEN_FILE = Path(os.environ.get("PC_GJC_USAGE_TOKEN_FILE", str(Path.home() / "pc_agent" / "otel" / "usage_token")))
STATE = Path(os.environ.get("GJC_REPORTER_STATE", str(Path.home() / "pc_agent" / "otel" / "gjc_reporter_state.json")))
OTEL_USAGE = Path(os.environ.get("PC_OTEL_USAGE", str(Path.home() / "pc_agent" / "otel" / "usage_local.json")))
OTEL_USAGE_API = Path(os.environ.get("PC_OTEL_USAGE_API", str(Path.home() / "pc_agent" / "otel" / "usage_api_local.json")))
DASHBOARD_DATA_REPO = Path(os.environ.get("DASHBOARD_REPO", str(Path.home() / "pc_agent" / "dashboards-data")))
DASHBOARD_BRANCH = os.environ.get("DASHBOARD_BRANCH", "data")

BIN_SECONDS = 300
SPAN_MINUTES = 24 * 60
BACKFILL_SECONDS = 30 * 86400  # 30 days for 30d billing + 24h series
RETENTION_SECONDS = 31 * 86400
GEMINI_CLI_DIR = Path(os.environ.get("GEMINI_CLI_DIR", str(Path.home() / ".gemini" / "tmp")))
SUB_PROVIDERS = {"anthropic", "openai", "gemini_sub"}
ALL_PROVIDERS = {"anthropic", "openai", "gemini", "gemini_sub"}
CRED_PROVIDERS = {
    "anthropic": ("anthropic",),
    "openai": ("openai-codex", "openai"),
    "gemini_sub": ("google-antigravity", "google-gemini-cli", "google"),
}


def normalize_provider(provider: str, api: str = "", active: set[str] | None = None) -> str | None:
    p = (provider or "").lower().strip()
    a = (api or "").lower().strip()
    if p == "anthropic" or p.startswith("anthropic-"):
        return "anthropic"
    if p == "openai" or p.startswith("openai-") or p in {"codex", "openai-codex"}:
        return "openai"
    if p in {"google-antigravity", "google-gemini-cli"} or a == "google-gemini-cli":
        return "gemini_sub"
    if p in {"google", "gemini"} or p.startswith("google-") or p.startswith("gemini-"):
        if active is not None and "gemini_sub" in active and a != "google-generative-ai":
            return "gemini_sub"
        return "gemini"
    return None

def active_subscription_providers() -> set[str] | None:
    """Dashboard provider ids whose gjc credential is an active OAuth login."""
    try:
        db = sqlite3.connect(f"file:{GJC_DB}?mode=ro", uri=True)
        try:
            rows = db.execute(
                "SELECT provider, credential_type, disabled_cause FROM auth_credentials"
            ).fetchall()
        finally:
            db.close()
    except Exception as e:
        print(f"gjc_usage_reporter: cannot read auth state ({e}); reporting all providers", flush=True)
        return None
    active: set[str] = set()
    for provider, cred_type, disabled_cause in rows:
        for dash_id, names in CRED_PROVIDERS.items():
            if provider in names and cred_type == "oauth" and not disabled_cause:
                active.add(dash_id)
    return active


def load_state() -> dict[str, Any]:
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(st, dict) and st.get("schema_version") == SCHEMA_VERSION:
            return st
    except Exception:
        pass
    return {"schema_version": SCHEMA_VERSION, "offsets": {}, "bins": {}}


def save_state(s: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s), encoding="utf-8")
    tmp.replace(STATE)


def _usage_token() -> str | None:
    try:
        return TOKEN_FILE.read_text().strip()
    except Exception:
        return None


def post_with_circuit_breaker(rec: dict[str, Any], endpoints: list[str], dead_endpoints: set[str]) -> bool:
    data = json.dumps(rec).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "gjc-usage-reporter/2.0"}
    token = _usage_token()
    if token:
        headers["X-Usage-Token"] = token
    for endpoint in endpoints:
        if endpoint in dead_endpoints:
            continue
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=2.5) as r:
                r.read()
            return True
        except Exception as e:
            dead_endpoints.add(endpoint)
            print(f"post fail ({endpoint}): {e}", flush=True)
    return False


def to_seconds(ts: Any) -> float:
    if isinstance(ts, (int, float)):
        return float(ts) / 1000.0 if ts > 1e12 else float(ts)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


def write_local_otel_files(bins: dict[str, dict[str, Any]]) -> None:
    """Write ~/pc_agent/otel/usage_local.json and usage_api_local.json in token_status.py format."""
    sub_bins: dict[str, dict[str, Any]] = {}
    api_bins: dict[str, dict[str, Any]] = {}
    for bkey, prov_map in bins.items():
        if not isinstance(prov_map, dict):
            continue
        for prov, rec in prov_map.items():
            if not isinstance(rec, dict):
                continue
            tok = (
                int(rec.get("input") or 0)
                + int(rec.get("output") or 0)
                + int(rec.get("cacheRead") or 0)
                + int(rec.get("cacheCreation") or 0)
            )
            cost = float(rec.get("cost") or 0.0)
            if tok <= 0:
                continue
            entry = {
                "tokens": tok,
                "cost": round(cost, 6),
                "by_type": {
                    "input": int(rec.get("input") or 0),
                    "output": int(rec.get("output") or 0),
                    "cacheRead": int(rec.get("cacheRead") or 0),
                    "cacheCreation": int(rec.get("cacheCreation") or 0),
                },
            }
            if prov in SUB_PROVIDERS:
                out_prov = "gemini" if prov == "gemini_sub" else prov
                sub_bins.setdefault(bkey, {})[out_prov] = entry
            elif prov == "gemini":
                api_bins.setdefault(bkey, {})["gemini"] = entry

    for path, payload_bins in ((OTEL_USAGE, sub_bins), (OTEL_USAGE_API, api_bins)):
        try:
            existing: dict[str, Any] = {}
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
            merged_bins = existing.get("bins", {}) if isinstance(existing, dict) else {}
            for bkey, pmap in payload_bins.items():
                dest = merged_bins.setdefault(bkey, {})
                for prov, entry in pmap.items():
                    prev = dest.get(prov)
                    if not isinstance(prev, dict) or int(entry["tokens"]) >= int(prev.get("tokens") or 0):
                        dest[prov] = entry
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"bins": merged_bins}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except Exception as e:
            print(f"gjc_usage_reporter: failed writing {path}: {e}", flush=True)


def build_series_from_bins(
    bins: dict[str, dict[str, Any]],
    provider_id: str,
    now_dt: datetime,
    source: str,
    span_min: int = SPAN_MINUTES,
    bin_min: int = 5,
) -> dict[str, Any]:
    step = bin_min * 60
    end = (int(now_dt.timestamp()) // step) * step
    n = span_min // bin_min
    points = []
    total = 0
    cost = 0.0
    for i in range(n):
        bstart = end - step * (n - 1 - i)
        rec = (bins.get(str(bstart)) or {}).get(provider_id)
        if isinstance(rec, dict):
            tok = (
                int(rec.get("input") or 0)
                + int(rec.get("output") or 0)
                + int(rec.get("cacheRead") or 0)
                + int(rec.get("cacheCreation") or 0)
            )
            c = float(rec.get("cost") or 0.0)
        else:
            tok = 0
            c = 0.0
        total += tok
        cost += c
        points.append({
            "t": datetime.fromtimestamp(bstart, timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"),
            "tokens": tok,
        })
    return {
        "available": True,
        "source": source,
        "bin_seconds": step,
        "span_minutes": span_min,
        "points": points,
        "window_tokens": int(total),
        "window_cost": round(cost, 4),
    }


def build_gemini_30d_billing(bins: dict[str, dict[str, Any]], now_ts: float) -> dict[str, Any]:
    cutoff = now_ts - 30 * 86400
    inp = out = cr = cw = 0
    cost = 0.0
    for bkey, pmap in bins.items():
        try:
            bts = int(bkey)
        except ValueError:
            continue
        if bts < cutoff or not isinstance(pmap, dict):
            continue
        rec = pmap.get("gemini")
        if not isinstance(rec, dict):
            continue
        inp += int(rec.get("input") or 0)
        out += int(rec.get("output") or 0)
        cr += int(rec.get("cacheRead") or 0)
        cw += int(rec.get("cacheCreation") or 0)
        cost += float(rec.get("cost") or 0.0)
    total = inp + out + cr + cw
    return {
        "available": True,
        "source": "Gajae Code Gemini API telemetry (last 30d)",
        "window": "last_30d",
        "month_to_date_cost": round(cost, 4),
        "currency": "usd",
        "cost_available": True,
        "usage": {
            "available": True,
            "source": "Gajae Code Gemini session telemetry",
            "total_tokens": total,
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read_tokens": cr,
            "cache_creation_tokens": cw,
        },
    }


def merge_series_points(base_series: dict[str, Any] | None, overlay_series: dict[str, Any]) -> dict[str, Any]:
    """Merge two 5-minute series onto the 24h (288-bin) grid of overlay_series using per-bin max."""
    base_map: dict[str, int] = {}
    if isinstance(base_series, dict):
        for p in base_series.get("points") or []:
            if isinstance(p, dict) and p.get("t"):
                base_map[str(p["t"])] = int(p.get("tokens") or 0)
    merged_points = []
    total = 0
    for p in overlay_series.get("points") or []:
        t = str(p["t"])
        v = max(int(p.get("tokens") or 0), int(base_map.get(t) or 0))
        merged_points.append({"t": t, "tokens": v})
        total += v
    out = dict(overlay_series)
    out["points"] = merged_points
    out["window_tokens"] = total
    base_cost = float((base_series or {}).get("window_cost") or 0.0) if isinstance(base_series, dict) else 0.0
    over_cost = float(overlay_series.get("window_cost") or 0.0)
    out["window_cost"] = round(max(base_cost, over_cost), 4)
    return out


def expand_series_to_24h(existing_series: dict[str, Any] | None, cached_series: dict[str, Any] | None, now_dt: datetime) -> dict[str, Any] | None:
    """Ensure API usage_series has a full 24h (288-bin) window even if Mac mini published 6h (72 bins)."""
    if not isinstance(existing_series, dict) or not existing_series.get("available"):
        return existing_series
    step = 300
    end = (int(now_dt.timestamp()) // step) * step
    n = SPAN_MINUTES // 5
    point_map: dict[str, int] = {}
    if isinstance(cached_series, dict):
        for p in cached_series.get("points") or []:
            if isinstance(p, dict) and p.get("t"):
                point_map[str(p["t"])] = max(point_map.get(str(p["t"]), 0), int(p.get("tokens") or 0))
    for p in existing_series.get("points") or []:
        if isinstance(p, dict) and p.get("t"):
            point_map[str(p["t"])] = max(point_map.get(str(p["t"]), 0), int(p.get("tokens") or 0))
    points = []
    total = 0
    for i in range(n):
        bstart = end - step * (n - 1 - i)
        t = datetime.fromtimestamp(bstart, timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z")
        v = point_map.get(t, 0)
        points.append({"t": t, "tokens": v})
        total += v
    res = dict(existing_series)
    res["bin_seconds"] = step
    res["span_minutes"] = SPAN_MINUTES
    res["points"] = points
    res["window_tokens"] = total
    return res


def run_git(cmd: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DASHBOARD_ALLOW_LOCAL_COMMIT"] = "1"
    env.setdefault("HOME", str(Path.home()))
    env.setdefault("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin")
    env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=8 -o ControlMaster=no -o ControlPath=none"
    return subprocess.run(cmd, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)


def publish_to_github_data(bins: dict[str, dict[str, Any]], now_dt: datetime, _retry: bool = False) -> None:
    if not (DASHBOARD_DATA_REPO / ".git").exists():
        return
    try:
        run_git(["git", "rebase", "--abort"], DASHBOARD_DATA_REPO, timeout=10)
        f = run_git(["git", "fetch", "origin", DASHBOARD_BRANCH], DASHBOARD_DATA_REPO, timeout=25)
        if f.returncode == 0:
            run_git(["git", "reset", "--hard", f"origin/{DASHBOARD_BRANCH}"], DASHBOARD_DATA_REPO, timeout=15)
    except Exception as e:
        print(f"gjc_usage_reporter: git sync failed: {e}", flush=True)

    tokens_path = DASHBOARD_DATA_REPO / "data" / "tokens.json"
    macbook_path = DASHBOARD_DATA_REPO / "data" / "gjc_macbook.json"

    try:
        tokens_data = json.loads(tokens_path.read_text(encoding="utf-8")) if tokens_path.exists() else {}
    except Exception:
        tokens_data = {}
    try:
        prev_mb = json.loads(macbook_path.read_text(encoding="utf-8")) if macbook_path.exists() else {}
    except Exception:
        prev_mb = {}

    now_iso = now_dt.isoformat().replace("+00:00", "Z")
    sub_source = "Claude Code / Codex / Gajae Code OpenTelemetry (subscription)"
    gem_source = "Pipeline + Gajae Code Gemini API usage"

    openai_sub = build_series_from_bins(bins, "openai", now_dt, sub_source)
    anthropic_sub = build_series_from_bins(bins, "anthropic", now_dt, sub_source)
    gemini_sub = build_series_from_bins(bins, "gemini_sub", now_dt, sub_source)
    gemini_api = build_series_from_bins(bins, "gemini", now_dt, gem_source)
    gemini_billing = build_gemini_30d_billing(bins, now_dt.timestamp())

    # Check if tokens.json currently lacks MacBook data or has 6h truncated series
    need_tokens_patch = False
    providers_list = tokens_data.get("providers") or []
    prev_mb_provs = (prev_mb.get("providers") or {}) if isinstance(prev_mb, dict) else {}

    cached_api_series: dict[str, Any] = {}
    for p in providers_list:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if pid in ("openai", "anthropic"):
            target_sub = openai_sub if pid == "openai" else anthropic_sub
            cur_sub = p.get("subscription_series") or {}
            if (
                int(cur_sub.get("window_tokens") or 0) < int(target_sub["window_tokens"])
                or len(cur_sub.get("points") or []) < 288
            ):
                need_tokens_patch = True
            p["subscription_series"] = merge_series_points(cur_sub, target_sub)

            cur_api = p.get("usage_series")
            if isinstance(cur_api, dict) and len(cur_api.get("points") or []) < 288:
                need_tokens_patch = True
            prev_cached_api = (prev_mb_provs.get(pid) or {}).get("usage_series")
            expanded_api = expand_series_to_24h(cur_api, prev_cached_api, now_dt)
            if expanded_api:
                p["usage_series"] = expanded_api
                cached_api_series[pid] = expanded_api
        elif pid == "gemini":
            cur_sub = p.get("subscription_series") or {}
            if (
                int(cur_sub.get("window_tokens") or 0) < int(gemini_sub["window_tokens"])
                or len(cur_sub.get("points") or []) < 288
            ):
                need_tokens_patch = True
            p["subscription_series"] = merge_series_points(cur_sub, gemini_sub)

            cur_api = p.get("usage_series") or {}
            if (
                int(cur_api.get("window_tokens") or 0) < int(gemini_api["window_tokens"])
                or len(cur_api.get("points") or []) < 288
                or not (p.get("billing") or {}).get("available")
            ):
                need_tokens_patch = True
            p["usage_series"] = merge_series_points(cur_api, gemini_api)
            p["billing"] = gemini_billing

    # Check if MacBook token totals changed compared to prev_mb
    def _mb_sig(mb_obj: dict[str, Any]) -> tuple:
        pr = (mb_obj.get("providers") or {}) if isinstance(mb_obj, dict) else {}
        return (
            ((pr.get("openai") or {}).get("subscription_series") or {}).get("window_tokens"),
            ((pr.get("anthropic") or {}).get("subscription_series") or {}).get("window_tokens"),
            ((pr.get("gemini") or {}).get("subscription_series") or {}).get("window_tokens"),
            ((pr.get("gemini") or {}).get("usage_series") or {}).get("window_tokens"),
            (((pr.get("gemini") or {}).get("billing") or {}).get("usage") or {}).get("total_tokens"),
        )

    new_mb = {
        "host": socket.gethostname(),
        "updated_at": now_iso,
        "bin_seconds": BIN_SECONDS,
        "span_minutes": SPAN_MINUTES,
        "providers": {
            "openai": {
                "subscription_series": openai_sub,
                "usage_series": cached_api_series.get("openai"),
            },
            "anthropic": {
                "subscription_series": anthropic_sub,
                "usage_series": cached_api_series.get("anthropic"),
            },
            "gemini": {
                "billing": gemini_billing,
                "subscription_series": gemini_sub,
                "usage_series": gemini_api,
            },
        },
    }

    # Also check if tokens.json is stale (> 10 minutes old, e.g. Mac mini offline)
    tokens_age_sec = 0.0
    try:
        t_up = str(tokens_data.get("updated_at") or "")
        if t_up:
            tokens_age_sec = now_dt.timestamp() - datetime.fromisoformat(t_up.replace("Z", "+00:00")).timestamp()
    except Exception:
        tokens_age_sec = 999999.0

    mb_changed = _mb_sig(prev_mb) != _mb_sig(new_mb)
    if not mb_changed and not need_tokens_patch and tokens_age_sec < 600:
        return

    if tokens_age_sec >= 600 or mb_changed:
        tokens_data["updated_at"] = now_iso
        tokens_data["overall"] = "ok"

    macbook_path.parent.mkdir(parents=True, exist_ok=True)
    macbook_path.write_text(json.dumps(new_mb, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if providers_list:
        tokens_path.write_text(json.dumps(tokens_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        run_git(["git", "config", "user.name", "MacBook GJC Token Reporter"], DASHBOARD_DATA_REPO, timeout=10)
        run_git(["git", "config", "user.email", "tokens@jehyunlee.dev"], DASHBOARD_DATA_REPO, timeout=10)
        run_git(["git", "add", "data/gjc_macbook.json", "data/tokens.json"], DASHBOARD_DATA_REPO, timeout=15)
        st = run_git(["git", "status", "--short", "data/gjc_macbook.json", "data/tokens.json"], DASHBOARD_DATA_REPO, timeout=15)
        if st.stdout.strip():
            c = run_git(["git", "commit", "--no-verify", "-q", "-m", f"tokens: macbook gjc usage {now_iso}"], DASHBOARD_DATA_REPO, timeout=20)
            if c.returncode != 0:
                print("gjc_usage_reporter: git commit failed:", c.stdout.strip(), flush=True)
                return
            p = run_git(["git", "push", "origin", DASHBOARD_BRANCH], DASHBOARD_DATA_REPO, timeout=30)
            if p.returncode != 0 and not _retry:
                publish_to_github_data(bins, now_dt, _retry=True)
                return
            print(f"gjc_usage_reporter: published to origin/{DASHBOARD_BRANCH} (openai={openai_sub['window_tokens']}, anthropic={anthropic_sub['window_tokens']}, gemini_sub={gemini_sub['window_tokens']}, gemini_api={gemini_api['window_tokens']})", flush=True)
    except Exception as e:
        print(f"gjc_usage_reporter: git publish failed: {e}", flush=True)


def main() -> None:
    st = load_state()
    offsets: dict[str, int] = st.setdefault("offsets", {})
    bins: dict[str, dict[str, Any]] = st.setdefault("bins", {})
    next_offsets = dict(offsets)
    first_run = not bool(offsets)
    now_ts = time.time()
    cutoff = now_ts - BACKFILL_SECONDS

    files = glob.glob(str(SESS_DIR / "**" / "*.jsonl"), recursive=True)
    active = active_subscription_providers()
    if active is not None:
        skipped = sorted(SUB_PROVIDERS - active)
        if skipped:
            print(f"gjc_usage_reporter: skipping non-subscription auth providers: {', '.join(skipped)}", flush=True)

    new_records = 0
    for f in files:
        try:
            size = os.path.getsize(f)
            mtime = os.path.getmtime(f)
        except OSError:
            continue
        off = offsets.get(f)
        if off is None:
            if first_run and mtime < cutoff:
                next_offsets[f] = size
                continue
            off = 0
        if off > size:
            off = 0
        if off >= size:
            continue
        try:
            with open(f, "rb") as fh:
                fh.seek(off)
                data = fh.read()
        except OSError:
            continue
        last_nl = data.rfind(b"\n")
        if last_nl < 0:
            continue
        chunk = data[: last_nl + 1]
        next_offsets[f] = off + len(chunk)
        for line in chunk.split(b"\n"):
            line = line.strip()
            if not line or b"\"assistant\"" not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") != "message":
                continue
            m = e.get("message") or {}
            if m.get("role") != "assistant":
                continue
            prov = normalize_provider(str(m.get("provider", "")), str(m.get("api", "")), active)
            if prov not in ALL_PROVIDERS:
                continue
            if prov in {"anthropic", "openai"} and active is not None and prov not in active:
                continue
            u = m.get("usage") or {}
            inp = int(u.get("input") or 0)
            out = int(u.get("output") or 0)
            cr = int(u.get("cacheRead") or 0)
            cw = int(u.get("cacheWrite") or 0)
            tot = inp + out + cr + cw
            if tot <= 0:
                continue
            cost_obj = u.get("cost")
            cost_val = float(cost_obj.get("total") or 0.0) if isinstance(cost_obj, dict) else 0.0
            sec = to_seconds(m.get("timestamp") or e.get("timestamp"))
            if sec < cutoff:
                continue
            bstart = int(sec // BIN_SECONDS) * BIN_SECONDS
            bmap = bins.setdefault(str(bstart), {})
            d = bmap.setdefault(
                prov,
                {"input": 0, "output": 0, "cacheRead": 0, "cacheCreation": 0, "cost": 0.0, "sent_tokens": 0},
            )
            d["input"] = int(d.get("input") or 0) + inp
            d["output"] = int(d.get("output") or 0) + out
            d["cacheRead"] = int(d.get("cacheRead") or 0) + cr
            d["cacheCreation"] = int(d.get("cacheCreation") or 0) + cw
            d["cost"] = round(float(d.get("cost") or 0.0) + cost_val, 6)
            new_records += 1

    # Also scan Gemini CLI (~/.gemini/tmp/**/chats/session-*.jsonl) OAuth subscription logs
    for gf in glob.glob(str(GEMINI_CLI_DIR / "**" / "chats" / "session-*.jsonl"), recursive=True):
        try:
            gsize = os.path.getsize(gf)
            gmtime = os.path.getmtime(gf)
        except OSError:
            continue
        goff = offsets.get(gf)
        if goff is None:
            if first_run and gmtime < cutoff:
                next_offsets[gf] = gsize
                continue
            goff = 0
        if goff > gsize:
            goff = 0
        if goff >= gsize:
            continue
        try:
            with open(gf, "rb") as fh:
                fh.seek(goff)
                gdata = fh.read()
        except OSError:
            continue
        glast_nl = gdata.rfind(b"\n")
        if glast_nl < 0:
            continue
        gchunk = gdata[: glast_nl + 1]
        next_offsets[gf] = goff + len(gchunk)
        for gline in gchunk.split(b"\n"):
            gline = gline.strip()
            if not gline or b"\"gemini\"" not in gline:
                continue
            try:
                ge = json.loads(gline)
            except Exception:
                continue
            if not isinstance(ge, dict) or ge.get("type") != "gemini":
                continue
            gtok = ge.get("tokens") or {}
            if not isinstance(gtok, dict):
                continue
            ginp = int(gtok.get("input") or 0)
            gout = int(gtok.get("output") or 0) + int(gtok.get("thoughts") or 0)
            gcr = int(gtok.get("cached") or 0)
            gtot = ginp + gout + gcr
            if gtot <= 0:
                continue
            gsec = to_seconds(ge.get("timestamp"))
            if gsec < cutoff:
                continue
            gbstart = int(gsec // BIN_SECONDS) * BIN_SECONDS
            gbmap = bins.setdefault(str(gbstart), {})
            gd = gbmap.setdefault(
                "gemini_sub",
                {"input": 0, "output": 0, "cacheRead": 0, "cacheCreation": 0, "cost": 0.0, "sent_tokens": 0},
            )
            gd["input"] = int(gd.get("input") or 0) + ginp
            gd["output"] = int(gd.get("output") or 0) + gout
            gd["cacheRead"] = int(gd.get("cacheRead") or 0) + gcr
            new_records += 1

    # Prune bins older than RETENTION_SECONDS
    prune_before = int(now_ts - RETENTION_SECONDS)
    for bkey in list(bins.keys()):
        try:
            if int(bkey) < prune_before:
                del bins[bkey]
        except ValueError:
            del bins[bkey]

    st["offsets"] = next_offsets
    save_state(st)
    write_local_otel_files(bins)

    # Best-effort POST of recent 24h unsent bins to Mac mini receiver (with circuit breaker)
    recent_cut = int(now_ts - 86400)
    dead_sub: set[str] = set()
    dead_pc: set[str] = set()
    posted = 0
    attempted = 0
    for bkey in sorted(bins.keys()):
        try:
            bstart = int(bkey)
        except ValueError:
            continue
        if bstart < recent_cut:
            continue
        pmap = bins[bkey]
        if not isinstance(pmap, dict):
            continue
        for prov, d in pmap.items():
            if not isinstance(d, dict):
                continue
            tot = (
                int(d.get("input") or 0)
                + int(d.get("output") or 0)
                + int(d.get("cacheRead") or 0)
                + int(d.get("cacheCreation") or 0)
            )
            sent = int(d.get("sent_tokens") or 0)
            if tot <= sent:
                continue
            attempted += 1
            if prov in SUB_PROVIDERS:
                if len(dead_sub) >= len(ENDPOINTS):
                    continue
                bt = {
                    "input": int(d.get("input") or 0),
                    "output": int(d.get("output") or 0),
                    "cacheRead": int(d.get("cacheRead") or 0),
                    "cacheCreation": int(d.get("cacheCreation") or 0),
                }
                out_prov = "gemini" if prov == "gemini_sub" else prov
                if post_with_circuit_breaker({"provider": out_prov, "by_type": bt, "ts": bstart}, ENDPOINTS, dead_sub):
                    d["sent_tokens"] = tot
                    posted += 1
            elif prov == "gemini":
                if len(dead_pc) >= len(PC_ENDPOINTS):
                    continue
                bt_pc = {
                    "input": int(d.get("input") or 0),
                    "output": int(d.get("output") or 0),
                    "cached": int(d.get("cacheRead") or 0) + int(d.get("cacheCreation") or 0),
                }
                if post_with_circuit_breaker({"provider": "gemini", "by_type": bt_pc, "ts": bstart}, PC_ENDPOINTS, dead_pc):
                    d["sent_tokens"] = tot
                    posted += 1

    if posted > 0:
        save_state(st)
        print(f"gjc_usage_reporter: posted {posted}/{attempted} recent bin-records to receiver", flush=True)

    # Always ensure GitHub data branch has the latest MacBook usage (including when Mac mini is disconnected)
    publish_to_github_data(bins, datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
