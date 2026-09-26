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
