# Runs laya-serve for Colony (started by colony/cli.py) and stops it, with its worker processes, as soon as
# Colony goes away: Colony holds our stdin open, so the pipe closes even when Colony is force-quit.
import os
import signal
import sys
import threading

from laya.serve import main


def _stop_with_colony() -> None:
    sys.stdin.buffer.read()
    os.killpg(0, signal.SIGKILL)   # our own process group only (Colony starts us in a new session)


threading.Thread(target=_stop_with_colony, daemon=True).start()
main()
