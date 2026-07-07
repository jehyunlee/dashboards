#!/usr/bin/env python3
"""Report Gajae Code (gjc, https://github.com/Yeachan-Heo/gajae-code) subscription token usage to the local OTLP receiver.

Gajae Code persists every assistant message to session JSONL at
  ~/.gjc/agent/sessions/--<cwd>--/<ts>_<id>.jsonl
Each `message` entry carries {provider, model, usage{input,output,cacheRead,cacheWrite}}.
Account/OAuth-logged Gajae Code usage is subscription-billed but invisible to both the
Claude Code OTel path and the org Admin API, so the dashboard's 구독 row misses it.

This reporter scans the session files, aggregates NEW assistant-message usage into
5-min bins by provider, and POSTs them to the receiver's /gjc/usage endpoint
(subscription bucket -> usage_local.json). Provider anthropic -> Claude Code 구독,
openai -> Codex 구독. Per-file byte offsets are tracked to avoid double counting;
append-only session files make offset tracking safe.
"""
import glob
import json
import os
import time
import urllib.request
from pathlib import Path

SESS_DIR = Path(os.environ.get("GJC_SESS_DIR", str(Path.home() / ".gjc" / "agent" / "sessions")))
ENDPOINT = os.environ.get("PC_GJC_USAGE_ENDPOINT", "http://localhost:4318/gjc/usage")
STATE = Path(os.environ.get("GJC_REPORTER_STATE", str(Path.home() / "pc_agent" / "otel" / "gjc_reporter_state.json")))
BIN_SECONDS = 300
BACKFILL_SECONDS = 12 * 3600  # on first run, only backfill sessions touched within this window
PROVIDERS = {"anthropic", "openai"}  # 구독 rows: anthropic=Claude Code, openai=Codex


def normalize_provider(provider: str) -> str | None:
    provider = provider.lower()
    if provider == "anthropic" or provider.startswith("anthropic-"):
        return "anthropic"
    if provider == "openai" or provider.startswith("openai-") or provider in {"codex", "openai-codex"}:
        return "openai"
    return None


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"offsets": {}}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s), encoding="utf-8")
    tmp.replace(STATE)


def post(rec: dict) -> bool:
    data = json.dumps(rec).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return True
    except Exception as e:
        print("post fail:", e, flush=True)
        return False


def to_seconds(ts) -> float:
    if isinstance(ts, (int, float)):
        return float(ts) / 1000.0 if ts > 1e12 else float(ts)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


def main() -> None:
    st = load_state()
    offsets = st.setdefault("offsets", {})
    first_run = not bool(offsets)
    cutoff = time.time() - BACKFILL_SECONDS
    files = glob.glob(str(SESS_DIR / "**" / "*.jsonl"), recursive=True)

    agg: dict = {}  # (bstart, provider) -> {input,output,cacheRead,cacheCreation}
    for f in files:
        try:
            size = os.path.getsize(f)
        except OSError:
            continue
        off = offsets.get(f)
        if off is None:
            if first_run and os.path.getmtime(f) < cutoff:
                offsets[f] = size  # skip ancient backfill on first run
                continue
            off = 0
        if off > size:
            off = 0  # file truncated/replaced
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
            continue  # no complete line yet
        chunk = data[: last_nl + 1]
        offsets[f] = off + len(chunk)
        for line in chunk.split(b"\n"):
            line = line.strip()
            if not line:
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
            prov = normalize_provider(str(m.get("provider", "")))
            if prov not in PROVIDERS:
                continue
            u = m.get("usage") or {}
            inp = int(u.get("input") or 0)
            out = int(u.get("output") or 0)
            cr = int(u.get("cacheRead") or 0)
            cw = int(u.get("cacheWrite") or 0)
            if (inp + out + cr + cw) <= 0:
                continue
            sec = to_seconds(m.get("timestamp") or e.get("timestamp"))
            bstart = int(sec // BIN_SECONDS) * BIN_SECONDS
            d = agg.setdefault((bstart, prov), {"input": 0, "output": 0, "cacheRead": 0, "cacheCreation": 0})
            d["input"] += inp
            d["output"] += out
            d["cacheRead"] += cr
            d["cacheCreation"] += cw

    ok = 0
    for (bstart, prov), bt in sorted(agg.items()):
        if post({"provider": prov, "by_type": bt, "ts": bstart}):
            ok += 1
    save_state(st)
    if agg:
        print(f"gjc_usage_reporter: posted {ok}/{len(agg)} bin-records", flush=True)


if __name__ == "__main__":
    main()
