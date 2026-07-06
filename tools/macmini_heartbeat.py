#!/usr/bin/env python3
"""Publish Mac mini status to the dashboards GitHub Pages repo."""
from __future__ import annotations
import json, os, socket, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

AGENT = Path(os.environ.get("PC_AGENT_DIR", str(Path.home()/"pc_agent"/"dashun_wang"))).expanduser()
REPO = Path(os.environ.get("DASHBOARD_REPO", str(Path.home()/"pc_agent"/"dashboards"))).expanduser()
DATA = REPO / "data" / "macmini.json"
LEDGER = AGENT / "curriculum.json"


def run(cmd, timeout=12):
    try:
        return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except Exception as e:
        class R: pass
        r=R(); r.returncode=999; r.stdout=str(e); return r


def ps_lines(substr):
    cp=run(["/bin/ps","-ww","-axo","pid=,etime=,time=,%cpu=,stat=,command="], 10)
    return [l.strip() for l in cp.stdout.splitlines() if substr in l]


def port_open(host, port, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout): return True
    except Exception: return False


def tail(path, n=8):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []


def load_prev_events():
    try:
        return json.loads(DATA.read_text(encoding="utf-8")).get("events", [])[-20:]
    except Exception:
        return []


def main():
    now=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    events=load_prev_events()
    digest=ps_lines("agent_lecture_digest.py")
    watchdog=ps_lines("agent_lecture_watchdog.py")
    ssh_ok=port_open("127.0.0.1",22)

    lecture={"status":"unknown","done":0,"total":0,"current":"ledger missing"}
    if LEDGER.exists():
        led=json.loads(LEDGER.read_text(encoding="utf-8"))
        lecs=led.get("lectures",[])
        done=sum(1 for L in lecs if L.get("status")=="done")
        pending=[L for L in lecs if L.get("status")!="done"]
        cur=pending[0] if pending else None
        lecture={"status":"ok" if not digest else "warn", "done":done, "total":led.get("total",len(lecs)),
                 "current": (f"L{cur['lecture']} {cur['scheduled_at']} {cur['title']}" if cur else "all complete")}

    wd_ok = bool(watchdog) or not digest  # launchd interval job may be absent between runs; logs prove install.
    wd_err = " | ".join(tail(AGENT/"watchdog.launchd.err", 2))
    if wd_err:
        wd_status, wd_detail = "warn", wd_err[:220]
    else:
        wd_status, wd_detail = "ok", "Watchdog launchd installed; interval job may be idle between checks."

    dg_status = "warn" if digest else "ok"
    dg_detail = digest[0][:240] if digest else "No lecture digest currently running."
    if digest and "0:00.0" in digest[0]:
        dg_detail += " (low CPU; watchdog monitors freeze)"

    overall="ok"
    if digest:
        overall="warn"
    if not ssh_ok:
        overall="warn"

    data={
      "host": socket.gethostname(),
      "updated_at": now,
      "overall": overall,
      "summary": "Heartbeat pushed from Mac mini.",
      "checks": {
        "ssh": {"status": "ok" if ssh_ok else "warn", "detail": "Local SSH port 22 is listening." if ssh_ok else "Local SSH port 22 is not reachable."},
        "digest": {"status": dg_status, "detail": dg_detail},
        "watchdog": {"status": wd_status, "detail": wd_detail},
      },
      "lecture": lecture,
      "processes": {"digest": digest[:5], "watchdog": watchdog[:5]},
      "events": (events + [{"time": now, "message": f"heartbeat overall={overall}, digest={'running' if digest else 'idle'}, done={lecture['done']}/{lecture['total']}"}])[-20:],
    }
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    cp=run(["git","status","--short","data/macmini.json"], 20)
    if cp.stdout.strip():
        run(["git","add","data/macmini.json"], 20)
        run(["git","commit","-q","-m",f"heartbeat: macmini {now}"], 30)
        push=run(["git","push","origin","main"], 60)
        print(push.stdout.strip())
    print(json.dumps({"updated_at":now,"overall":overall,"digest_running":bool(digest),"done":lecture["done"],"total":lecture["total"]}, ensure_ascii=False))

if __name__ == "__main__":
    os.chdir(REPO)
    main()
