import os
import socket
import subprocess
import sys
import time
import urllib.request


def test_server_stops_when_the_desktop_window_goes_away(tmp_path):
    """The desktop window holds the server's stdin open; closing it (or being force-quit) must stop the server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "HOME": str(tmp_path), "MOCK_MODE": "true"}
    server = subprocess.Popen(
        [sys.executable, "-m", "colony.cli", "--no-open", "--exit-with-parent", "--port", str(port)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError("server never came up")
        assert server.poll() is None  # still running while the window holds stdin open
        server.stdin.close()          # what the OS does when the window process dies
        assert server.wait(timeout=10) is not None
    finally:
        if server.poll() is None:
            server.kill()


def _gateway_found_on_a_port(monkeypatch):
    """Something already listens where the Gateway should be. Starting one stops at the Node check, so nothing real is spawned."""
    import shutil

    from colony import cli
    from colony.config import get_settings
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    monkeypatch.setattr(cli, "OPENCLAW_PORT", listener.getsockname()[1])
    monkeypatch.setattr(cli, "OPENCLAW_ADOPT_POLL_S", 0.05)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setenv("MOCK_MODE", "false")
    get_settings.cache_clear()
    return cli, listener


def _until_it_prints(capsys, text: str, out: str = "") -> str:
    """The watcher thread's output so far, once it contains `text` (it must finish while `shutil.which` is still patched)."""
    for _ in range(200):
        out += capsys.readouterr().out
        if text in out:
            return out
        time.sleep(0.05)
    raise AssertionError(f"never printed {text!r}; got: {out!r}")


def test_a_gateway_that_stays_up_is_used_and_not_started_again(monkeypatch, capsys):
    cli, listener = _gateway_found_on_a_port(monkeypatch)
    cli._start_openclaw()
    time.sleep(0.6)                        # many check intervals: it is still there
    out = capsys.readouterr().out
    assert "already running" in out and "is gone" not in out and "not started" not in out
    listener.close()                       # let the watcher finish before the patches are undone
    _until_it_prints(capsys, "not started: needs Node")


def test_a_gateway_that_goes_away_after_being_found_is_replaced(monkeypatch, capsys):
    """A restart: the old Colony's Gateway still answers when the new Colony looks, then its watcher shell stops it."""
    cli, listener = _gateway_found_on_a_port(monkeypatch)
    cli._start_openclaw()
    listener.close()                       # the old Gateway is stopped
    out = _until_it_prints(capsys, "not started: needs Node")      # it went on to start one (stopped at the Node check here)
    assert "already running" in out and "is gone" in out
