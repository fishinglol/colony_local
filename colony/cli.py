#!/usr/bin/env python3
"""Colony Local CLI.

Usage (after `pip install -e .`):
    colony              # start the local server and open the app
    colony --no-open    # start without opening a browser
    colony --reload     # development: restart automatically when the code changes

The desktop window (desktop/) starts this with --exit-with-parent so the server never outlives it.
"""
import argparse


def _stop_when_stdin_closes() -> None:
    """The desktop window keeps our stdin open; when it dies (even by force-quit) the pipe closes."""
    import os
    import signal
    import sys
    import threading

    def watch() -> None:
        try:
            sys.stdin.buffer.read()
        finally:
            os.kill(os.getpid(), signal.SIGTERM)  # a normal, graceful uvicorn shutdown

    threading.Thread(target=watch, daemon=True).start()


LAYA_PORT = 8790


def _start_laya() -> None:
    """Run the local Laya decider next to the server when laya-runtime/ is installed (see its requirements.txt)."""
    import os
    import subprocess
    from pathlib import Path

    runtime = Path(__file__).resolve().parent.parent / "laya-runtime"
    python = runtime / ".venv" / "bin" / "python"
    from .config import get_settings
    if get_settings().jev_api_key:
        print("🧭  Jev decides through its API (JEV_API_KEY) — not starting the local Laya.")
        return
    if os.environ.get("LAYA_URL") or not python.exists():
        return
    env = {**os.environ, "LAYA_HOST": "127.0.0.1", "LAYA_PORT": str(LAYA_PORT), "LAYA_DEVICE": "cpu",
           "LAYA_MODELS": "multilingual", "LAYA_MAX_LOADED": "1", "LAYA_THREADS": "2", "LAYA_LOG_LEVEL": "warning"}
    log = open(Path.home() / ".colony" / "laya.log", "w")
    # The pipe on stdin is Laya's lifeline: it stops when this process ends, however it ends (runtime/serve.py).
    # Deliberately never closed or waited on.
    subprocess.Popen([str(python), str(runtime / "serve.py")], env=env, stdin=subprocess.PIPE,
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    os.environ["LAYA_URL"] = f"http://127.0.0.1:{LAYA_PORT}"
    print(f"🧭  Laya (who answers in # mix) starting on port {LAYA_PORT} …")


OPENCLAW_PORT = 18789


def _start_openclaw() -> None:
    """Run the OpenClaw Gateway from openclaw-main 2/ unless something already answers on its port; stop it with us."""
    import os
    import shutil
    import socket
    import subprocess
    import threading
    import time
    import urllib.request
    from pathlib import Path

    from .config import get_settings

    settings = get_settings()
    if settings.mock_mode or not settings.openclaw_gateway_enabled:
        return
    source = Path(__file__).resolve().parent.parent / "openclaw-main 2"
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", OPENCLAW_PORT)) == 0:
            print(f"🦞  OpenClaw Gateway already running on port {OPENCLAW_PORT} — using it.")
            return
    if not (source / "openclaw.mjs").exists() or not shutil.which("node"):
        print("⚠️  OpenClaw Gateway not started: needs Node (>=24.16) and openclaw-main 2/ (see memory-bank/techContext.md).")
        return
    log_path = Path.home() / ".colony" / "openclaw.log"

    def spawn() -> "subprocess.Popen":
        gateway = subprocess.Popen(["node", "openclaw.mjs", "gateway", "run", "--allow-unconfigured"], cwd=source,
                                   env={**os.environ, "COLONY_URL": f"http://{settings.host}:{settings.port}"},   # for colony-gate.ts
                                   stdout=open(log_path, "a"), stderr=subprocess.STDOUT, start_new_session=True)
        # Uvicorn re-raises SIGTERM, so atexit never runs: a tiny shell watches our pid and stops the gateway after us.
        subprocess.Popen(["sh", "-c", f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 2; done; kill -TERM -{gateway.pid}"],
                         start_new_session=True)
        return gateway

    open(log_path, "w").close()
    gateway = spawn()
    print(f"🦞  OpenClaw Gateway starting on port {OPENCLAW_PORT} (takes ~50 s; chat shows a not-ready notice until then) …")

    def watchdog() -> None:
        """The Gateway has died twice on its own (its state-lock heartbeat starved when the Mac was overloaded, then it could not
        take the lock back). Start it again, at most 3 times in 10 minutes so a Gateway that cannot start does not loop."""
        nonlocal gateway
        restarts: list[float] = []
        while True:
            time.sleep(5)
            if gateway.poll() is None:
                continue
            now = time.monotonic()
            restarts = [t for t in restarts if now - t < 600]
            if len(restarts) >= 3:
                print(f"⚠️  OpenClaw Gateway keeps dying — not restarting it again. See {log_path}")
                return
            restarts.append(now)
            print(f"⚠️  OpenClaw Gateway exited (code {gateway.returncode}) — starting it again.")
            gateway = spawn()

    def warm_up() -> None:
        """The first turn after a start took ~100 s on this Mac (measured 2026-10-11, later ones ~5 s): pay it now, not on the first message."""
        try:
            from .core.workspaces import list_workspaces
            from .engine import openclaw
            openclaw.ping_model(settings, list_workspaces()[0].roles[0].model)
            print("🦞  OpenClaw warmed up.")
        except Exception as exc:    # a failed warm-up only means the first message is slow
            print(f"⚠️  OpenClaw warm-up failed: {exc}")

    def report() -> None:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{OPENCLAW_PORT}/readyz", timeout=1)
                print("🦞  OpenClaw Gateway ready.")
                warm_up()
                return
            except OSError:
                time.sleep(2)
        print(f"⚠️  OpenClaw Gateway still not ready after 2 min — see {log_path}")

    threading.Thread(target=report, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="colony",
        description="Colony Local — multi-AI assistant with shared context.",
    )
    parser.add_argument(
        "--host", default=None,
        help="Host to bind (default: 127.0.0.1 from config)",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="Port to listen on (default: 8765 from config)",
    )
    parser.add_argument(
        "--no-open", action="store_true",
        help="Don't open the browser after the server starts",
    )
    parser.add_argument(
        "--reload", action="store_true",
        help="Development: restart the server automatically when the code changes",
    )
    parser.add_argument(
        "--exit-with-parent", action="store_true",
        help="Stop when stdin is closed (used by the desktop window, so the server can't outlive it)",
    )
    args = parser.parse_args()

    # Apply CLI overrides before importing settings (lru_cache not called yet).
    import os
    if args.host:
        os.environ["HOST"] = args.host
    if args.port:
        os.environ["PORT"] = str(args.port)
    from .config import ensure_env_file, get_settings
    ensure_env_file()
    _start_laya()
    _start_openclaw()

    if not args.no_open:
        import threading
        import webbrowser
        s = get_settings()
        url = f"http://{s.host}:{s.port}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"🌐  Opening browser at {url} …")

    if args.exit_with_parent:
        _stop_when_stdin_closes()

    from .app import run
    run(reload=args.reload)


if __name__ == "__main__":
    main()
