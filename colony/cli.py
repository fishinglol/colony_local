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
