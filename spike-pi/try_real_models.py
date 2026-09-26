"""Do YOUR free OpenRouter models call Pi's tools reliably?  Run in a terminal that has your key:

    export OPENROUTER_API_KEY=sk-or-...        # your own; this script only passes it to Pi via the environment
    python try_real_models.py                  # or:  python try_real_models.py z-ai/glm-5.2:free

Each model gets two turns in a scratch folder (run/real-workspace): write a file, then read it back.
That is about 4 requests per model, so 16 in total against the free-model daily limit.
"""
import os
import shutil
import sys
from pathlib import Path

import spike

MODELS = ["qwen/qwen3.8-27b:free", "nvidia/nemotron-3-ultra-550b-a55b:free",
          "nvidia/nemotron-3-super-120b-a12b:free", "z-ai/glm-5.2:free"]

if not os.environ.get("OPENROUTER_API_KEY"):
    sys.exit("Set OPENROUTER_API_KEY in this terminal first (see the top of this file).")

work = spike.RUN / "real-workspace"
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)
spike.WORK = work
persona = "You are a careful assistant. Use your tools to do file work, then say briefly what you did."
agent_dir = Path(__file__).parent / "agent-dir-openrouter"
everything_ok = True

for model in sys.argv[1:] or MODELS:
    name = model.split("/")[-1].split(":")[0]
    print(f"\n=== {model}")
    kw = dict(provider="openrouter-free", agent_dir=agent_dir, timeout=180, session=f"real-{name}", extra=["--no-context-files"])
    a = spike.turn(f"Create a file named {name}.txt containing exactly: hi from {name}", model, persona, "read,write,edit",
                   {"write": "allow", "edit": "allow"}, lambda r: True, **kw)
    wrote = (work / f"{name}.txt").exists()
    b = spike.turn(f"What does {name}.txt say? Read it with your tool and quote it.", model, persona, "read,write,edit",
                   {"write": "allow", "edit": "allow"}, lambda r: True, **kw)
    ok = wrote and any(t[0] == "read" for t in b["tools"])
    everything_ok &= ok
    print(f"  wrote the file with the write tool : {'YES' if wrote else 'NO'}   tools used: {a['tools']}   ({a['seconds']}s)")
    print(f"  read it back with the read tool    : {'YES' if any(t[0] == 'read' for t in b['tools']) else 'NO'}   tools used: {b['tools']}   ({b['seconds']}s)")
    print(f"  reply: {b['reply'][:160]!r}")
    for label, r in (("write turn", a), ("read turn", b)):
        for problem in r["problems"]:
            print(f"  {label} problem: {problem}")
print("\nALL MODELS OK" if everything_ok else "\nSome models did not use tools — see above.")
