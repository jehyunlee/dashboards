#!/usr/bin/env python3
"""Publish Mac mini lecture-mailer workflow status to the dashboards repo."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT = Path(os.environ.get("PC_AGENT_DIR", str(Path.home() / "pc_agent" / "dashun_wang"))).expanduser()
REPO = Path(os.environ.get("DASHBOARD_REPO", str(Path.home() / "pc_agent" / "dashboards"))).expanduser()
DATA = REPO / "data" / "macmini.json"
BRANCH = os.environ.get("DASHBOARD_BRANCH", "data")
LEDGER = AGENT / "curriculum.json"
SCHEDULE_FMT = "%Y-%m-%d %H:%M"

TASKS = [
    ("schedule", "예약 확인", "하루 2회 launchd 예약 시각 확인"),
    ("start", "프로세스 시작", "launchd 또는 watchdog이 digest 실행"),
    ("evidence", "논문 근거 수집", "핵심 논문·연결 그래프 수집"),
    ("report", "리포트·HTML 제작", "Deeper Research, 그림, 논문 연결 지도"),
    ("script", "오디오 대본 생성", "분할 대본 병렬 생성"),
    ("tts", "TTS·MP3 변환", "Gemini TTS 호출과 MP3 인코딩"),
    ("image", "메일 이미지 첨부", "커리큘럼 진도 PNG 생성"),
    ("email", "메일 발송", "HTML과 오디오 파일 전송"),
    ("ledger", "완료 기록·휴식", "ledger 저장 후 다음 예약까지 대기"),
]
ORDER = [item[0] for item in TASKS]


def run(cmd, timeout=12):
    try:
        return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except Exception as e:
        class R:
            pass

        r = R()
        r.returncode = 999
        r.stdout = str(e)
        return r


def ps_lines(substr):
    cp = run(["/bin/ps", "-ww", "-axo", "pid=,etime=,time=,%cpu=,stat=,command="], 10)
    return [line.strip() for line in cp.stdout.splitlines() if substr in line]


def port_open(host, port, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def read_lines(path, n=80):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_prev_events():
    events = load_json(DATA, {}).get("events", [])[-20:]
    return [e for e in events if "workflow=" in str(e.get("message", ""))][-10:]


def parse_local_dt(value):
    try:
        return datetime.strptime(value or "", SCHEDULE_FMT)
    except Exception:
        return None


def iso_local(value):
    if not value:
        return None
    return value.strftime(SCHEDULE_FMT)


def lecture_no(item):
    try:
        return int(item.get("lecture", 0))
    except Exception:
        return 0


def extract_ps_lecture(lines):
    for line in lines:
        m = re.search(r"--lecture\s+(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def latest_log_for_lecture(number):
    candidates = []
    patterns = [
        f"l{number}.log",
        f"l{number}_*.log",
        f"watchdog_l{number:02d}.log",
        "launchd.out",
        "launchd.err",
    ]
    for pattern in patterns:
        candidates.extend(p for p in AGENT.glob(pattern) if p.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def recent_watchdog_retry(number, local_now):
    lines = read_lines(AGENT / "watchdog.log", 30)
    recent = []
    for line in lines:
        if f"lecture {number}" not in line and f"lecture={number}" not in line:
            continue
        recent.append(line)
    for line in reversed(recent):
        if "starting lecture" not in line and "duplicate cleanup" not in line and "killing digest" not in line:
            continue
        m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
        if not m:
            return line
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except Exception:
            return line
        if local_now - ts <= timedelta(minutes=20):
            return line
    return ""


def blank_steps():
    return [
        {"id": sid, "label": label, "detail": detail, "status": "ready", "current": False}
        for sid, label, detail in TASKS
    ]


def set_status(steps, sid, status, detail=None, current=False):
    for step in steps:
        if step["id"] == sid:
            step["status"] = status
            if detail:
                step["detail"] = detail
            step["current"] = current
            return


def mark_done_through(steps, sid):
    if sid not in ORDER:
        return
    end = ORDER.index(sid)
    for step in steps[: end + 1]:
        step["status"] = "done"
        step["current"] = False


def current_stage_from_log(lines):
    text = "\n".join(lines)
    if not text:
        return "start", "on_progress", "프로세스 로그를 기다리는 중"

    lower = text.lower()
    retry = "tts retry" in lower or "retry" in lower or "재시작" in text
    failed = "traceback" in lower or "exception" in lower or "error" in lower or "실패" in text and "진도 이미지 생성 실패" not in text

    if "[agent]" in text:
        stage, status, detail = "start", "done", "digest 프로세스가 시작됨"
    else:
        stage, status, detail = "start", "on_progress", "digest 프로세스 시작 확인 중"

    if "1) 근거 수집" in text:
        stage, status, detail = "evidence", "on_progress", "핵심 논문과 연결 그래프 수집 중"
    if re.search(r"근거 [\d,]+자", text):
        mark = re.search(r"근거 [\d,]+자.*", text)
        stage, status, detail = "report", "on_progress", mark.group(0) if mark else "근거 수집 완료"
    if "2) Deeper Research" in text:
        stage, status, detail = "report", "on_progress", "Gemini 리포트 합성 중"
    if re.search(r"리포트 [\d,]+자", text):
        mark = re.search(r"리포트 [\d,]+자.*", text)
        stage, status, detail = "script", "on_progress", mark.group(0) if mark else "리포트·HTML 제작 완료"
    if "3) 오디오 생성" in text:
        stage, status, detail = "script", "on_progress", "오디오 대본 생성 시작"
    if "대본 병렬 생성" in text:
        mark = re.findall(r"대본 병렬 생성.*", text)
        stage, status, detail = "script", "on_progress", mark[-1].strip() if mark else "대본 병렬 생성 중"
    if re.search(r"대본 \d+/\d+", text):
        mark = re.findall(r"대본 \d+/\d+.*", text)
        stage, status, detail = "script", "on_progress", mark[-1].strip()
    if "TTS " in text:
        mark = re.findall(r"TTS .*", text)
        stage, status, detail = "tts", "on_progress", mark[-1].strip() if mark else "TTS 변환 중"
    if re.search(r"\[\d+/\d+\]", text):
        mark = re.findall(r"\[\d+/\d+\]", text)
        stage, status, detail = "tts", "on_progress", f"TTS chunks {mark[-1]}"
    if re.search(r"\d+(?:\.\d+)?MB.*분", text):
        mark = re.findall(r".*\d+(?:\.\d+)?MB.*분.*", text)
        stage, status, detail = "image", "on_progress", mark[-1].strip() if mark else "MP3 생성 완료"
    if "진도 이미지 생성" in text:
        stage, status, detail = "email", "on_progress", "진도 이미지 생성 완료, 메일 발송 준비"
    if "4) 이메일 발송" in text:
        stage, status, detail = "email", "on_progress", "Resend API로 메일 발송 중"
    if "이메일 성공" in text:
        stage, status, detail = "ledger", "on_progress", "메일 발송 성공, 완료 기록 중"
    if "done 기록" in text:
        stage, status, detail = "ledger", "done", "완료 기록 저장됨"
    if "이메일 실패" in text:
        stage, status, detail = "email", "fail", "메일 발송 실패"

    if retry and status == "on_progress":
        status = "retry"
        detail += " · retry 감지"
    if failed and status not in {"done", "fail"}:
        status = "fail"
        detail += " · 실패 로그 감지"
    return stage, status, detail


def build_workflow(ledger, digest_lines, ssh_ok):
    local_now = datetime.now()
    lectures = ledger.get("lectures", []) if ledger else []
    total = ledger.get("total", len(lectures)) if ledger else 0
    pending = [item for item in lectures if item.get("status") != "done"]
    done = [item for item in lectures if item.get("status") == "done"]

    ps_lecture = extract_ps_lecture(digest_lines)
    if ps_lecture:
        target = next((item for item in lectures if lecture_no(item) == ps_lecture), None)
    else:
        due = [item for item in pending if (parse_local_dt(item.get("scheduled_at")) or local_now) <= local_now]
        target = min(due, key=lambda item: item.get("scheduled_at", "")) if due else (pending[0] if pending else None)

    last_done = max(done, key=lambda item: parse_local_dt(item.get("completed_at") or item.get("scheduled_at")) or datetime.min) if done else None
    scheduled = parse_local_dt(target.get("scheduled_at")) if target else None
    overdue = int((local_now - scheduled).total_seconds() // 60) if scheduled and local_now >= scheduled else 0
    running = bool(digest_lines)

    steps = blank_steps()
    log_path = latest_log_for_lecture(lecture_no(target)) if target else None
    log_lines = read_lines(log_path, 100) if log_path else []
    log_age = None
    if log_path:
        log_age = int(datetime.now().timestamp() - log_path.stat().st_mtime)

    current_step = "schedule"
    mode = "idle"
    wf_status = "ok"
    summary = "다음 자동 발송 예약을 기다리는 중입니다."

    if not target:
        mark_done_through(steps, "ledger")
        current_step = "ledger"
        mode = "complete"
        summary = "모든 예약 작업이 끝났습니다."
    elif running:
        mark_done_through(steps, "start")
        current_step, stage_status, detail = current_stage_from_log(log_lines)
        mark_index = max(0, ORDER.index(current_step) - 1)
        for step in steps[:mark_index + 1]:
            step["status"] = "done"
        set_status(steps, current_step, stage_status, detail=detail, current=True)
        mode = "running"
        wf_status = "warn"
        summary = f"제{lecture_no(target)}강 제작·발송 프로세스가 진행 중입니다."
        if log_age is not None and log_age > 30 * 60 and stage_status in {"on_progress", "retry"}:
            set_status(steps, current_step, "fail", detail=f"{detail} · {log_age // 60}분 동안 로그 진전 없음", current=True)
            mode = "stuck"
            wf_status = "bad"
            summary = f"제{lecture_no(target)}강이 {steps[ORDER.index(current_step)]['label']} 단계에서 stuck 가능성이 있습니다."
        retry_line = recent_watchdog_retry(lecture_no(target), local_now)
        if retry_line and mode != "stuck":
            mode = "retry"
            wf_status = "warn"
            set_status(steps, current_step, "retry", detail=steps[ORDER.index(current_step)]["detail"] + " · watchdog retry", current=True)
            summary = f"watchdog 재시작 후 제{lecture_no(target)}강을 다시 진행 중입니다."
    elif target.get("status") == "done":
        mark_done_through(steps, "ledger")
        current_step = "ledger"
        mode = "idle"
        summary = f"제{lecture_no(target)}강 발송 완료 후 쉬는 중입니다."
    elif overdue > 7:
        set_status(steps, "schedule", "fail", detail=f"예약 시각 {overdue}분 경과, digest 미실행", current=True)
        current_step = "schedule"
        mode = "stuck"
        wf_status = "bad"
        summary = f"제{lecture_no(target)}강 예약 시각이 지났지만 digest 프로세스가 보이지 않습니다."
    elif overdue > 0:
        set_status(steps, "schedule", "on_progress", detail=f"예약 시각 도달 후 {overdue}분, launchd 시작 확인 중", current=True)
        current_step = "schedule"
        mode = "ready"
        wf_status = "warn"
        summary = f"제{lecture_no(target)}강 자동 시작을 확인 중입니다."
    else:
        set_status(steps, "schedule", "ready", detail=f"다음 예약 {target.get('scheduled_at')}", current=True)
        current_step = "schedule"
        mode = "idle"
        summary = f"할 일을 다 하고 쉬는 중입니다. 다음 작업은 제{lecture_no(target)}강 {target.get('scheduled_at')}입니다."

    if not ssh_ok and wf_status == "ok":
        wf_status = "warn"

    return {
        "status": wf_status,
        "mode": mode,
        "summary": summary,
        "current_step": current_step,
        "target": {
            "lecture": lecture_no(target) if target else None,
            "title": target.get("title") if target else "all complete",
            "scheduled_at": target.get("scheduled_at") if target else None,
            "overdue_minutes": overdue,
            "running": running,
        },
        "last_completed": {
            "lecture": lecture_no(last_done) if last_done else None,
            "title": last_done.get("title") if last_done else None,
            "completed_at": last_done.get("completed_at") or last_done.get("scheduled_at") if last_done else None,
        },
        "course": ledger.get("course", "Dashun Wang 연구 흐름 따라잡기") if ledger else "Dashun Wang 연구 흐름 따라잡기",
        "steps": steps,
        "log": {
            "path": str(log_path) if log_path else None,
            "age_seconds": log_age,
            "tail": log_lines[-8:],
        },
    }


def main():
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    events = load_prev_events()
    digest = ps_lines("agent_lecture_digest.py")
    watchdog = ps_lines("agent_lecture_watchdog.py")
    ssh_ok = port_open("127.0.0.1", 22)
    ledger = load_json(LEDGER, {}) if LEDGER.exists() else {}
    workflow = build_workflow(ledger, digest, ssh_ok)

    wd_ok = bool(watchdog) or not digest
    wd_err = " | ".join(read_lines(AGENT / "watchdog.launchd.err", 2))
    if wd_err:
        wd_status, wd_detail = "warn", wd_err[:220]
    elif wd_ok:
        wd_status, wd_detail = "ok", "Watchdog launchd installed; interval job may be idle between checks."
    else:
        wd_status, wd_detail = "warn", "Digest is running but watchdog process is not visible between interval checks."

    dg_status = "warn" if digest else "ok"
    dg_detail = digest[0][:240] if digest else "No lecture digest currently running."
    overall = "bad" if workflow["status"] == "bad" else ("warn" if workflow["status"] == "warn" or digest or not ssh_ok else "ok")

    data = {
        "host": socket.gethostname(),
        "updated_at": now,
        "overall": overall,
        "summary": workflow["summary"],
        "checks": {
            "ssh": {"status": "ok" if ssh_ok else "warn", "detail": "Local SSH port 22 is listening." if ssh_ok else "Local SSH port 22 is not reachable."},
            "digest": {"status": dg_status, "detail": dg_detail},
            "watchdog": {"status": wd_status, "detail": wd_detail},
        },
        "workflow": workflow,
        "processes": {"digest": digest[:5], "watchdog": watchdog[:5]},
        "events": (events + [{"time": now, "message": f"workflow={workflow['mode']}, current={workflow['current_step']}, target=L{workflow['target']['lecture']}"}])[-20:],
    }

    DATA.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "config", "user.name", "Mac mini Heartbeat"], 10)
    run(["git", "config", "user.email", "heartbeat@jehyunlee.dev"], 10)
    run(["git", "pull", "--rebase", "origin", BRANCH], 60)
    prev = load_json(DATA, {})
    ssh_history = list(prev.get("ssh_history", []))
    ssh_history.append({"time": now, "status": "pass" if ssh_ok else "fail"})
    data["ssh_history"] = ssh_history[-288:]

    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cp = run(["git", "status", "--short", "data/macmini.json"], 20)
    if cp.stdout.strip():
        run(["git", "add", "data/macmini.json"], 20)
        commit = run(["git", "commit", "-q", "-m", f"heartbeat: macmini {now}"], 30)
        if commit.returncode != 0:
            print("commit failed:", commit.stdout.strip())
        push = run(["git", "push", "origin", BRANCH], 60)
        if push.returncode != 0:
            print("push failed; pulling/retrying:", push.stdout.strip())
            run(["git", "pull", "--rebase", "origin", BRANCH], 60)
            push = run(["git", "push", "origin", BRANCH], 60)
        print(push.stdout.strip())
    print(json.dumps({"updated_at": now, "overall": overall, "workflow": workflow["mode"], "current": workflow["current_step"]}, ensure_ascii=False))


if __name__ == "__main__":
    os.chdir(REPO)
    main()
