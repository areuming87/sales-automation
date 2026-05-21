"""
═══════════════════════════════════════════════════════════════
  BPMS 자동화 브리지 서버 (FastAPI)
  ───────────────────────────────────────────────────────────
  웹앱(bpms.html)이 'BPMS 불러오기' 버튼을 누르면 이 서버에
  요청을 보내고, 서버는 bpms_download.py 를 백그라운드로 실행.

  실행 방법: bridge.bat 더블클릭 (포트 8765 에서 대기)
═══════════════════════════════════════════════════════════════
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import subprocess
import threading
import time
import sys
import os

# ──── 환경 ────────────────────────────────────────────────
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"C:\playwright_browsers")
SCRIPT_DIR = Path(__file__).parent
DOWNLOAD_SCRIPT = SCRIPT_DIR / "bpms_download.py"

app = FastAPI(title="BPMS Automation Bridge", version="1.0")

# CORS — github.io 와 file:// 와 localhost 모두 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://areuming87.github.io",
        "http://localhost",
        "http://127.0.0.1",
        "null",  # file:// 프로토콜
    ],
    allow_origin_regex=r"(https://.*\.github\.io|http://localhost.*|http://127\.0\.0\.1.*)",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ──── 작업 상태 ────────────────────────────────────────────
state = {
    "status": "idle",        # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "log": [],               # 최근 로그 라인들
    "exit_code": None,
}
state_lock = threading.Lock()


def _push_log(line: str):
    line = line.rstrip("\r\n")
    if not line:
        return
    with state_lock:
        state["log"].append({"time": time.strftime("%H:%M:%S"), "msg": line})
        # 최근 300 라인만 유지
        if len(state["log"]) > 300:
            state["log"] = state["log"][-300:]
    print(f"[BPMS] {line}", flush=True)


def _run_script_background():
    """별도 스레드에서 bpms_download.py --auto 실행하고
    stdout 을 한 줄씩 로그로 기록."""
    with state_lock:
        state["status"] = "running"
        state["started_at"] = time.time()
        state["finished_at"] = None
        state["exit_code"] = None
        state["log"] = []

    _push_log("🚀 BPMS 자동화 시작...")

    try:
        # Python 실행 — utf-8 stdout 강제
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        proc = subprocess.Popen(
            [sys.executable, "-u", str(DOWNLOAD_SCRIPT), "--auto"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(SCRIPT_DIR),
            env=env,
            bufsize=1,
        )

        for line in proc.stdout:
            _push_log(line)

        proc.wait()
        with state_lock:
            state["exit_code"] = proc.returncode
            state["status"] = "done" if proc.returncode == 0 else "error"
            state["finished_at"] = time.time()
        _push_log(f"✅ 종료 (exit code: {proc.returncode})")

    except Exception as e:
        with state_lock:
            state["status"] = "error"
            state["finished_at"] = time.time()
        _push_log(f"❌ 오류: {e}")


# ──── 엔드포인트 ──────────────────────────────────────────
@app.get("/health")
def health():
    """브리지가 살아있는지 확인 (웹앱에서 핑)"""
    return {"status": "ok", "version": "1.0"}


@app.get("/status")
def get_status():
    """현재 작업 진행 상태 + 로그 (웹앱이 1초마다 폴링)"""
    with state_lock:
        return {
            "status": state["status"],
            "started_at": state["started_at"],
            "finished_at": state["finished_at"],
            "exit_code": state["exit_code"],
            "log": state["log"][-50:],  # 최근 50 라인만 반환
        }


@app.post("/run")
def run_automation():
    """BPMS 자동 다운로드 + 업로드 실행"""
    with state_lock:
        if state["status"] == "running":
            return {"ok": False, "error": "이미 실행 중입니다."}

    threading.Thread(target=_run_script_background, daemon=True).start()
    return {"ok": True, "message": "작업이 시작되었습니다."}


@app.post("/cancel")
def cancel():
    """진행 중인 작업 취소 — 미구현 (자식 프로세스 kill 필요)"""
    return {"ok": False, "error": "취소 기능 준비 중"}


# ──── 메인 (직접 실행 시) ─────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print(" BPMS Automation Bridge Server")
    print("=" * 60)
    print(f" 📂 스크립트: {DOWNLOAD_SCRIPT}")
    print(f" 🌐 주소: http://localhost:8765")
    print(f" 💡 이 창을 켜둔 상태로 웹앱의 [BPMS 불러오기] 사용 가능")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
