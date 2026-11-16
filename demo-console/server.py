"""VelocityFraud Live Demo Console - local orchestration server.

Serves a single-page console on http://127.0.0.1:8765 and runs only the demo
steps defined in steps.py: remote steps on the Hetzner server over SSH, local
steps (tunnel, Power BI, live program view) on this laptop.

Safety model:
  * listens on 127.0.0.1 only; Host/Origin headers checked on every request
  * a per-launch token is required on every API call
  * only catalogue steps can run - there is no free-text command input
  * one step at a time; steps that change state ask for confirmation
  * every run is appended to logs/console-YYYY-MM-DD.log

Standard library only. Usage:
    python server.py               start and open the browser
    python server.py --selftest    validate the step catalogue (bash -n on every script)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import steps as S

HERE = Path(__file__).resolve().parent
SETTINGS_FILE = HERE / "settings.json"
STATE_FILE = HERE / "state.json"
LOG_DIR = HERE / "logs"
INDEX_FILE = HERE / "index.html"
IST = timezone(timedelta(hours=5, minutes=30))
TUNNEL_PORTS = {"kafka_ui": 18081, "postgres": 15432, "mlflow": 15000}
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
IPV4 = re.compile(r"^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

DEFAULT_SETTINGS = {
    "server_ip": "",
    "loadgen_ip": "",
    "key_path": str(Path.home() / ".ssh" / "hetzner-key"),
    "pbix_path": str(Path.home() / "Documents" / "Fraud Detection" / "Fraud_Detection_Dashboard_Cloud.pbix"),
}

STEP_BY_ID = S.by_id()
TOKEN = secrets.token_urlsafe(24)
PORT = 8765

# Full test suite (steps 1.0 and 5.8): runs on this laptop against the local
# Docker copy of Redis / PostgreSQL / Kafka - never the demo server. Narration is
# forced to the template and the LLM keys are blanked, so no API quota is used.
VF_DIR = HERE.parent  # the repo root: this console lives in velocityfraud/demo-console
VF_PYTHON = VF_DIR / ".venv" / "Scripts" / "python.exe"
TEST_PORTS = {"Redis": 6379, "PostgreSQL": 5432, "Kafka": 9092}
TEST_ENV = {"NARRATOR_MODE": "template", "GEMINI_API_KEY": "", "GROQ_API_KEY": "",
            "POSTGRES_HOST": "localhost", "POSTGRES_PORT": "5432",
            "REDIS_HOST": "localhost", "REDIS_PORT": "6379", "PYTHONUNBUFFERED": "1"}
TEST_TOTAL = 122
TEST_LINE = re.compile(r"^(tests/\S+?\.py)::.*? (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
TEST_SUMMARY = re.compile(r"^=+ (.*\b(?:passed|failed|error|errors)\b.*?) =+$")
TESTS: dict = {"proc": None, "log": None, "started": ""}


# --------------------------------------------------------------------------- storage

def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update({k: v for k, v in _load_json(SETTINGS_FILE, {}).items() if k in DEFAULT_SETTINGS})
    return s


def now_ist() -> datetime:
    return datetime.now(IST)


def log_line(text: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / f"console-{now_ist():%Y-%m-%d}.log", "a", encoding="utf-8") as f:
        f.write(text + "\n")


# --------------------------------------------------------------------------- runs

class Run:
    def __init__(self, step: dict):
        self.id = secrets.token_hex(6)
        self.step = step
        self.lines: list[str] = []
        self.status = "running"          # running | ok | fail | stopped
        self.exit_code: int | None = None
        self.started = time.time()
        self.ended: float | None = None
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def emit(self, text: str) -> None:
        text = ANSI.sub("", text).rstrip("\r\n")
        with self.lock:
            self.lines.append(text)
        log_line(f"  {text}")

    def finish(self, status: str, code: int | None) -> None:
        with self.lock:
            self.status, self.exit_code, self.ended = status, code, time.time()
        log_line(f"[{now_ist():%H:%M:%S}] END {self.step['id']} status={status} exit={code} "
                 f"duration={self.ended - self.started:.1f}s")

    def snapshot(self, start: int) -> dict:
        with self.lock:
            return {
                "id": self.id, "step_id": self.step["id"], "lines": self.lines[start:],
                "next": len(self.lines), "status": self.status, "exit_code": self.exit_code,
                "duration": round((self.ended or time.time()) - self.started, 1),
            }


RUNS: dict[str, Run] = {}
ACTIVE: dict[str, Run | None] = {"run": None}
GATE = threading.Lock()
STATE_LOCK = threading.Lock()


def record_state(run: Run) -> None:
    with STATE_LOCK:
        state = _load_json(STATE_FILE, {})
        prev = state.get(run.step["id"], {})
        state[run.step["id"]] = {
            "status": run.status,
            "last_run": now_ist().strftime("%H:%M:%S"),
            "duration": round((run.ended or time.time()) - run.started, 1),
            "count": prev.get("count", 0) + 1,
        }
        _save_json(STATE_FILE, state)


def ssh_base(settings: dict, tty: bool = False, ip: str | None = None) -> list[str]:
    ssh = shutil.which("ssh") or "ssh"
    return [ssh, "-i", settings["key_path"], "-t" if tty else "-T",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
            "-o", "LogLevel=ERROR", f"root@{ip or settings['server_ip']}"]


def step_ip(step: dict, settings: dict) -> str:
    """The server a step runs on: the load server for load-server steps, else the demo server."""
    return settings["loadgen_ip"] if step.get("host") == "loadgen" else settings["server_ip"]


def exec_remote(run: Run, settings: dict) -> None:
    step = run.step
    script = S.compose(step, target=settings["server_ip"])
    payload = base64.encodebytes(script.encode("utf-8"))
    timeout = int(step.get("timeout", 120))
    # The script travels base64-encoded over ssh's stdin, never on the command
    # line: Windows OpenSSH truncates long command lines (~8 KB) silently. On the
    # server it is decoded into a temp file and run with stdin closed, so no
    # command inside it can swallow input. `base64 -di` tolerates line endings.
    remote = (f"f=$(mktemp /tmp/vfstep.XXXXXX) && base64 -di > $f && "
              f"timeout -k 5 {timeout} bash $f < /dev/null; rc=$?; rm -f $f; exit $rc")
    try:
        proc = subprocess.Popen(ssh_base(settings, ip=step_ip(step, settings)) + [remote], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=NO_WINDOW)
        proc.stdin.write(payload)
        proc.stdin.close()
    except OSError as e:
        run.emit(f"[FAIL] Could not start ssh: {e}")
        run.finish("fail", None)
        return
    run.proc = proc
    for raw in iter(proc.stdout.readline, b""):
        run.emit(raw.decode("utf-8", errors="replace"))
    code = proc.wait()
    if run.status == "stopped":
        run.finish("stopped", code)
        return
    if code == 124:
        run.emit(f"[FAIL] The step was stopped after its {timeout} s time limit.")
    elif code == 255:
        run.emit("[FAIL] SSH connection failed. Check the server IP and network. If the message mentions "
                 "'REMOTE HOST IDENTIFICATION HAS CHANGED', use Settings > Forget old host key.")
    run.finish("ok" if code == 0 else "fail", code)


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def open_console_window(title: str, ssh_args: list[str]) -> None:
    """Run an ssh command in its own visible PowerShell window."""
    cmd = "& " + " ".join(_ps_quote(a) for a in ssh_args)
    ps = f"$host.UI.RawUI.WindowTitle = {_ps_quote(title)}; {cmd}"
    subprocess.Popen(["powershell.exe", "-NoProfile", "-NoExit", "-Command", ps], creationflags=NEW_CONSOLE)


def tests_start(run: Run) -> bool:
    """Start the full pytest suite in the background; its output goes to logs/pytest-*.log."""
    proc = TESTS["proc"]
    if proc is not None and proc.poll() is None:
        run.emit(f"  [ OK ] The test suite is already running (started {TESTS['started']} IST). Results: step 5.8.")
        return True
    down = [name for name, port in TEST_PORTS.items() if not port_open(port)]
    if down:
        run.emit("[FAIL] The local test services are not running: " + ", ".join(down) + ".")
        run.emit("       Start Docker Desktop and the velocityfraud-dev containers, then run this step again.")
        return False
    if not VF_PYTHON.exists():
        run.emit(f"[FAIL] Project Python not found: {VF_PYTHON}")
        return False
    LOG_DIR.mkdir(exist_ok=True)
    started = now_ist()
    log = LOG_DIR / f"pytest-{started:%Y-%m-%d-%H%M%S}.log"
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(f"# started {started:%H:%M:%S} IST\n")
        fh.flush()
        proc = subprocess.Popen([str(VF_PYTHON), "-m", "pytest", "-v", "-p", "no:cacheprovider", "-p", "no:warnings",
                                 "--color=no"], cwd=VF_DIR, env=os.environ | TEST_ENV, stdin=subprocess.DEVNULL,
                                stdout=fh, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    TESTS.update(proc=proc, log=log, started=f"{started:%H:%M:%S}")
    run.emit(f"  [ OK ] Full test suite started at {started:%H:%M:%S} IST on this laptop: {TEST_TOTAL} tests.")
    run.emit("         58 unit tests + 64 integration tests against a local copy of Redis, PostgreSQL and Kafka.")
    run.emit("         It takes about 5 minutes and runs in the background - the demo continues. Results: step 5.8.")
    return True


def tests_results(run: Run) -> bool:
    """Show the latest pytest run: progress while it runs, the per-file result when it is done."""
    logs = sorted(LOG_DIR.glob("pytest-*.log"))
    if not logs:
        run.emit("[FAIL] No test run yet - run step 1.0 first.")
        return False
    log = logs[-1]
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    started = lines[0].replace("# started", "").strip() if lines and lines[0].startswith("# started") else "?"
    per_file: dict[str, dict[str, int]] = {}
    for line in lines:
        m = TEST_LINE.match(line)
        if m:
            counts = per_file.setdefault(m.group(1), {})
            counts[m.group(2)] = counts.get(m.group(2), 0) + 1
    totals: dict[str, int] = {}
    for counts in per_file.values():
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v
    done = sum(totals.values())
    summary = next((m.group(1) for m in map(TEST_SUMMARY.match, reversed(lines)) if m), None)
    proc = TESTS["proc"]
    running = (proc is not None and TESTS["log"] == log and proc.poll() is None) or time.time() - log.stat().st_mtime < 90
    if summary is None:
        if running:
            bad = totals.get("FAILED", 0) + totals.get("ERROR", 0)
            run.emit(f"  Still running (started {started}): {done} of {TEST_TOTAL} tests finished so far, {bad} failed.")
            run.emit("  Run this step again in a minute.")
            return True
        run.emit(f"[FAIL] The test run started at {started} stopped without a result. Its last lines:")
        for line in lines[-12:]:
            run.emit("  " + line)
        return False
    run.emit("")
    run.emit(f"== Full test suite - started {started}, run on this laptop ==")
    for name, counts in sorted(per_file.items()):
        detail = ", ".join(f"{v} {k.lower()}" for k, v in sorted(counts.items(), key=lambda kv: kv[0] != "PASSED"))
        run.emit(f"  {name.removeprefix('tests/'):<44} {detail}")
    run.emit("")
    clean = totals.get("PASSED", 0) == done and done > 0
    run.emit(f"  {'[ OK ]' if clean else '[WARN]'} {summary}")
    run.emit("         Unit tests plus integration tests against a local copy of Redis, PostgreSQL and Kafka.")
    return True


def exec_local(run: Run, settings: dict) -> None:
    action = run.step["local"]
    ok = True
    try:
        if action == "tests_start":
            ok = tests_start(run)
        elif action == "tests_results":
            ok = tests_results(run)
        elif action == "tunnel":
            up = {k: port_open(p) for k, p in TUNNEL_PORTS.items()}
            if all(up.values()):
                run.emit("  [ OK ] The secure tunnel is already open - no second tunnel started.")
            elif any(up.values()):
                run.emit("[FAIL] A partial tunnel is open (" + ", ".join(k for k, v in up.items() if v) +
                         "). Close the old tunnel window, then run this step again.")
                ok = False
            else:
                args = ssh_base(settings)[:-1] + ["-N", "-o", "ExitOnForwardFailure=yes",
                                                  "-L", "18081:localhost:8081", "-L", "15432:localhost:5432",
                                                  "-L", "15000:localhost:5000", f"root@{settings['server_ip']}"]
                args = [a for a in args if a != "-T"]
                open_console_window("VelocityFraud - secure tunnel (keep open)", args)
                run.emit("  Opening the tunnel window")
                for _ in range(30):
                    if all(port_open(p) for p in TUNNEL_PORTS.values()):
                        break
                    time.sleep(0.5)
                if all(port_open(p) for p in TUNNEL_PORTS.values()):
                    run.emit("  [ OK ] Tunnel open: Kafka UI localhost:18081 | PostgreSQL localhost:15432 | MLflow localhost:15000")
                    run.emit("  Minimise the tunnel window - do not close it.")
                else:
                    run.emit("[FAIL] The tunnel did not come up within 15 s - read the message in the tunnel window.")
                    ok = False
        elif action == "powerbi":
            listing = subprocess.run(["tasklist", "/FI", "IMAGENAME eq PBIDesktop.exe", "/NH"],
                                     capture_output=True, text=True, creationflags=NO_WINDOW).stdout
            path = Path(settings["pbix_path"])
            if "PBIDesktop.exe" in listing:
                run.emit("  [ OK ] Power BI Desktop is already open - not opening a second copy.")
            elif not path.exists():
                run.emit(f"[FAIL] Power BI file not found: {path}")
                ok = False
            else:
                os.startfile(str(path))  # noqa: S606 - opens the configured .pbix with Power BI Desktop
                run.emit(f"  [ OK ] Opening {path.name}")
                if not port_open(TUNNEL_PORTS["postgres"]):
                    run.emit("  [WARN] The tunnel is not open - Power BI needs it (step P2) to reach PostgreSQL.")
                run.emit("  Refresh with Optimize > Refresh visuals (never Home > Refresh).")
        elif action == "tmux":
            args = [a for a in ssh_base(settings, tty=True)] + ["tmux attach -t vf"]
            open_console_window("VelocityFraud - live programs (detach: Ctrl+b then d)", args)
            run.emit("  [ OK ] Opened the live program view in a new window.")
            run.emit("  Switch tab: Ctrl+b then 0-8.  Leave: Ctrl+b then d.  Never press Ctrl+C there.")
        else:
            run.emit(f"[FAIL] Unknown local action {action!r}")
            ok = False
    except OSError as e:
        run.emit(f"[FAIL] {e}")
        ok = False
    run.finish("ok" if ok else "fail", 0 if ok else 1)


def worker(run: Run, settings: dict) -> None:
    where = "load server" if run.step.get("host") == "loadgen" else "server"
    log_line(f"\n[{now_ist():%Y-%m-%d %H:%M:%S}] RUN {run.step['id']} - {run.step['title']} "
             f"({where} {step_ip(run.step, settings)})")
    try:
        if run.step["kind"] == "local":
            exec_local(run, settings)
        else:
            exec_remote(run, settings)
    except Exception as e:  # last-resort guard so the console never hangs
        run.emit(f"[FAIL] Console error: {e}")
        run.finish("fail", None)
    finally:
        record_state(run)
        with GATE:
            if ACTIVE["run"] is run:
                ACTIVE["run"] = None


def start_run(step_id: str, confirmed: bool) -> tuple[int, dict]:
    step = STEP_BY_ID.get(step_id)
    if not step:
        return 404, {"error": "Unknown step."}
    settings = load_settings()
    if not IPV4.match(settings["server_ip"] or ""):
        return 400, {"error": "Set the server IP in Settings first."}
    if step.get("host") == "loadgen" and not IPV4.match(settings["loadgen_ip"] or ""):
        return 400, {"error": "Set the load server IP in Settings first (used by P5, P6, 5.4 and 5.5)."}
    if not Path(settings["key_path"]).exists():
        return 400, {"error": f"SSH key not found: {settings['key_path']}"}
    count = _load_json(STATE_FILE, {}).get(step_id, {}).get("count", 0)
    if (step.get("confirm") or (step.get("confirm_rerun") and count > 0)) and not confirmed:
        return 409, {"error": "Confirmation required."}
    with GATE:
        if ACTIVE["run"] is not None:
            return 409, {"error": f"'{ACTIVE['run'].step['title']}' is still running."}
        run = Run(step)
        RUNS[run.id] = run
        ACTIVE["run"] = run
    threading.Thread(target=worker, args=(run, settings), daemon=True).start()
    return 200, {"run_id": run.id}


def stop_run(run_id: str) -> tuple[int, dict]:
    run = RUNS.get(run_id)
    if not run or run.status != "running":
        return 404, {"error": "No such running step."}
    run.status = "stopped"
    if run.proc and run.proc.poll() is None:
        run.proc.kill()
    run.emit("[WARN] Stopped from the console. Any server-side command still finishes within its time limit.")
    return 200, {"ok": True}


# --------------------------------------------------------------------------- status

def api_health(ip: str) -> dict:
    if not IPV4.match(ip or ""):
        return {"ok": False, "detail": "no server set"}
    try:
        with urllib.request.urlopen(f"http://{ip}:8000/health", timeout=2.5) as r:
            d = json.load(r)
        return {"ok": d.get("status") == "ok" and bool(d.get("model_loaded")),
                "review": d.get("review_thresh"), "block": d.get("block_thresh"),
                "champion": d.get("champion"), "redis": d.get("redis_alive")}
    except Exception as e:
        return {"ok": False, "detail": type(e).__name__}


def status() -> dict:
    settings = load_settings()
    ports = {k: port_open(p) for k, p in TUNNEL_PORTS.items()}
    return {
        "time_ist": now_ist().strftime("%H:%M:%S"),
        "server_ip": settings["server_ip"],
        "api": api_health(settings["server_ip"]),
        "tunnel": "up" if all(ports.values()) else ("partial" if any(ports.values()) else "down"),
        "active_run": ACTIVE["run"].id if ACTIVE["run"] else None,
    }


def config() -> dict:
    settings = load_settings()
    public_steps = []
    for s in S.STEPS:
        public_steps.append({k: s.get(k) for k in ("id", "section", "num", "title", "kind", "purpose", "built", "say", "show",
                                                    "links", "caution", "confirm", "confirm_rerun", "local")}
                            | {"script": s.get("script", "")})
    return {
        "sections": S.SECTIONS, "steps": public_steps, "links": S.LINKS, "kinds": S.KINDS,
        "notes": S.NOTES, "state": _load_json(STATE_FILE, {}), "settings": settings,
        "active_run": ACTIVE["run"].id if ACTIVE["run"] else None,
    }


# --------------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "VFConsole/1.0"

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

    def _send(self, code: int, body, ctype="application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self) -> bool:
        if not self._host_ok() or not self._origin_ok() or self.headers.get("X-VF-Token") != TOKEN:
            self._send(403, {"error": "Forbidden."})
            return False
        return True

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 <= length <= 10_000:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            if not self._host_ok():
                return self._send(403, b"Forbidden", "text/plain")
            html = INDEX_FILE.read_text(encoding="utf-8").replace("__VF_TOKEN__", TOKEN)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if not url.path.startswith("/api/") or not self._authorised():
            return None if url.path.startswith("/api/") else self._send(404, b"Not found", "text/plain")
        if url.path == "/api/config":
            return self._send(200, config())
        if url.path == "/api/status":
            return self._send(200, status())
        if url.path.startswith("/api/run/"):
            run = RUNS.get(url.path.rsplit("/", 1)[-1])
            if not run:
                return self._send(404, {"error": "Unknown run."})
            start = int((parse_qs(url.query).get("from") or ["0"])[0] or 0)
            return self._send(200, run.snapshot(max(0, start)))
        return self._send(404, {"error": "Not found."})

    def do_POST(self):
        url = urlparse(self.path)
        if not self._authorised():
            return None
        body = self._body()
        if url.path == "/api/run":
            code, payload = start_run(str(body.get("step_id", "")), bool(body.get("confirmed")))
            return self._send(code, payload)
        if url.path.startswith("/api/stop/"):
            code, payload = stop_run(url.path.rsplit("/", 1)[-1])
            return self._send(code, payload)
        if url.path == "/api/settings":
            ip = str(body.get("server_ip", "")).strip()
            if not IPV4.match(ip):
                return self._send(400, {"error": "Enter a valid IPv4 address, e.g. 203.0.113.10"})
            settings = load_settings()
            loadgen = str(body.get("loadgen_ip", settings["loadgen_ip"])).strip()
            if loadgen and not IPV4.match(loadgen):
                return self._send(400, {"error": "Enter a valid IPv4 address for the load server, or leave it empty."})
            key = str(body.get("key_path", settings["key_path"])).strip()
            if not Path(key).exists():
                return self._send(400, {"error": f"SSH key not found: {key}"})
            settings.update({"server_ip": ip, "loadgen_ip": loadgen, "key_path": key})
            _save_json(SETTINGS_FILE, settings)
            log_line(f"[{now_ist():%H:%M:%S}] SETTINGS server_ip={ip} loadgen_ip={loadgen or '-'}")
            return self._send(200, {"ok": True, "settings": settings})
        if url.path == "/api/forget-host-key":
            settings = load_settings()
            ips = [ip for ip in (settings["server_ip"], settings["loadgen_ip"]) if IPV4.match(ip or "")]
            if not ips:
                return self._send(400, {"error": "Set the server IP first."})
            outs = [subprocess.run(["ssh-keygen", "-R", ip], capture_output=True, text=True,
                                   creationflags=NO_WINDOW) for ip in ips]
            log_line(f"[{now_ist():%H:%M:%S}] FORGET-HOST-KEY {' '.join(ips)}")
            return self._send(200, {"ok": all(o.returncode == 0 for o in outs),
                                    "message": " ".join((o.stdout + o.stderr).strip() for o in outs).strip() or "Done."})
        if url.path == "/api/reset-state":
            with STATE_LOCK:
                _save_json(STATE_FILE, {})
            log_line(f"[{now_ist():%H:%M:%S}] RESET step marks")
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "Not found."})


# --------------------------------------------------------------------------- self-test

def selftest() -> int:
    problems = S.validate()
    bash = next((p for p in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")) if p and Path(p).exists()), None)
    checked = 0
    if bash:
        for s in S.STEPS:
            if s["kind"] == "local":
                continue
            r = subprocess.run([bash, "-n"], input=S.compose(s).encode("utf-8"), capture_output=True)
            checked += 1
            if r.returncode != 0:
                problems.append(f"{s['id']}: bash syntax error: {r.stderr.decode(errors='replace').strip()}")
    else:
        problems.append("bash not found - script syntax not checked")
    if "__VF_TOKEN__" not in INDEX_FILE.read_text(encoding="utf-8"):
        problems.append("index.html is missing the token placeholder")
    print(f"Steps: {len(S.STEPS)}  |  remote scripts syntax-checked: {checked}")
    for p in problems:
        print("  PROBLEM:", p)
    print("SELFTEST", "PASSED" if not problems else "FAILED")
    return 0 if not problems else 1


def main() -> int:
    global PORT
    ap = argparse.ArgumentParser(description="VelocityFraud Live Demo Console")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    PORT = args.port
    url = f"http://127.0.0.1:{PORT}/"
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Port {PORT} is busy - the console is probably already running. Opening {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 1
    print(f"VelocityFraud Live Demo Console running at {url}")
    print("Keep this window open during the demo. Press Ctrl+C here to stop the console.")
    log_line(f"\n[{now_ist():%Y-%m-%d %H:%M:%S}] CONSOLE STARTED on {url}")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Console stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
