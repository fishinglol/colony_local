# Colony Desktop

A native window (Tauri 2) around Colony Local. It starts the Python `colony` server on a free port,
shows a loading page while it boots, then opens the app in the window. Closing the window stops the
server — even if the window is force-quit (the server watches its stdin, see `--exit-with-parent`).

## Run it

```bash
cd local && python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # once: the server
cd desktop && npm install                                                # once: the Tauri CLI
npm run dev                                                              # first run compiles Rust (~7 min)
```

The window looks for the server command in this order: `$COLONY_BIN`, `local/.venv/bin/colony`, `colony` on PATH.

## Not done yet

`npm run build` makes a `.app`, but it does **not** contain Python: it still needs the `colony` command
installed on the machine (and a GUI app doesn't see your shell's PATH, so set `COLONY_BIN` or use the
project venv). Shipping a self-contained app means bundling Python (e.g. PyInstaller as a Tauri
sidecar) — a new dependency that needs sign-off first.
