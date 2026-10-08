# Colony Local — your own free open-weight models on a Kaggle GPU.
#
# 1. kaggle.com → Code → the arrow next to "New Notebook" → Import Notebook → kaggle/colony_server.ipynb.
#    (Kaggle starts a first run WITHOUT a GPU by itself: open its Logs → Version History → ⋯ → Cancel.)
# 2. Edit → Settings → Accelerator → "GPU T4 x2". Internet must be on (needs a phone-verified account).
# 3. Save Version → "Save & Run All (Commit)" → Advanced Settings → "Run with GPU for this session" → Save.
#    This runs in the background on Kaggle: you can close the tab. (Running the cell in the editor instead
#    made Kaggle drop the session during the big downloads.)
# 4. Open the notebook's Logs tab. After ~7 minutes it prints an https://….trycloudflare.com address:
#    Colony → Settings → "Kaggle server URL" → paste → Save.
# 5. In Colony, edit an agent and pick a model from the "Kaggle (your GPU)" group.
#
# A run lasts up to 12 hours and uses the weekly GPU quota (~30 hours) the whole time, even when idle: stop it from
# Logs → Version History → ⋯ → Cancel when you are done. Each new run has a NEW address to paste into Colony.
# Anyone who knows the address can use these models while it runs, so don't share it.
#
# The slow work runs in a background shell script and this cell only reports on it.

MODELS = ["gemma4:12b", "ornith:9b", "qwen3.5:9b"]   # any names from ollama.com/library that fit 2 x 16 GB
# Together ~21 GB, so all three stay loaded at once (tested 2026-09-30: writing/chat/reasoning = gemma4, code + tools =
# ornith, qwen3.5 = all-rounder with vision). More than ~30 GB makes Ollama swap models in and out (+10-60 s per reply).
PRELOAD = 3
CONTEXT = 16384                                   # keep equal to KAGGLE_CONTEXT_WINDOW in Colony (default 16384)

import os
import subprocess
import time

STATUS = "/tmp/colony-status.txt"
SETUP = f"""
say() {{ echo "$1" >> {STATUS}; }}
if ! command -v ollama > /dev/null; then
  say "Installing Ollama…"
  command -v zstd > /dev/null || apt-get install -y -qq zstd > /dev/null 2>&1
  curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst | tar --zstd -x -C /usr/local || {{ say "FAILED installing Ollama"; exit 1; }}
fi
if ! curl -s http://127.0.0.1:11434/api/version > /dev/null; then
  OLLAMA_HOST=127.0.0.1:11434 OLLAMA_CONTEXT_LENGTH={CONTEXT} OLLAMA_MAX_LOADED_MODELS=3 OLLAMA_KEEP_ALIVE=-1 \\
    nohup ollama serve > /tmp/ollama.log 2>&1 &
  until curl -s http://127.0.0.1:11434/api/version > /dev/null; do sleep 1; done
fi
n=0
for m in {" ".join(MODELS)}; do
  n=$((n+1))
  say "Downloading $m…"
  ollama pull $m > /tmp/pull.log 2>&1 || {{ say "SKIPPED $m (download failed: $(tail -c 200 /tmp/pull.log | tr '\\r\\n' '  '))"; continue; }}
  if [ $n -le {PRELOAD} ]; then
    say "Loading $m into the GPU…"
    curl -s http://127.0.0.1:11434/api/generate -d "{{\\"model\\": \\"$m\\"}}" > /dev/null
  fi
done
say "Opening a public address…"
curl -fsSL -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /tmp/cloudflared
nohup /tmp/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:11434 --http-host-header localhost:11434 \\
  > /tmp/tunnel.log 2>&1 &
say "TUNNEL"
"""


def folder_gb(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total / 1e9


def tunnel_address():
    try:
        words = open("/tmp/tunnel.log").read().split()
    except OSError:
        return ""
    return next((w for w in words if w.startswith("https://") and w.endswith(".trycloudflare.com")), "")


open(STATUS, "w").close()
open("/tmp/setup.sh", "w").write(SETUP)
setup = subprocess.Popen(["bash", "/tmp/setup.sh"], stdout=open("/tmp/setup.log", "w"),
                         stderr=subprocess.STDOUT, start_new_session=True)

shown, address, started = 0, "", time.time()
while True:
    lines = open(STATUS).read().splitlines()
    for line in lines[shown:]:
        if line != "TUNNEL":
            print(line, flush=True)
    shown = len(lines)
    if any(line.startswith("FAILED") for line in lines):   # (a SKIPPED model is only reported; the server still starts)
        print(open("/tmp/setup.log").read()[-2000:])
        break
    if "TUNNEL" in lines and not address:
        address = tunnel_address()
        if address:
            print("\n" + "=" * 70)
            print("Paste this into Colony → Settings → Kaggle server URL:\n")
            print("   ", address)
            print("\nModels:", ", ".join("kaggle/" + m for m in MODELS))
            print("=" * 70, flush=True)
    if address:
        time.sleep(300)
        print(time.strftime("%H:%M"), "still running", flush=True)
    else:
        time.sleep(15)
        print(f"  … {int(time.time() - started)} s, {folder_gb('/root/.ollama'):.1f} GB of models so far", flush=True)
