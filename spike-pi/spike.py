"""Spike: can Pi be the tool-running engine for Colony's agents?  Run:  python spike.py

Everything is local: Pi talks to fake_llm.py (a pretend model), so no API key and no network.
Each turn starts a fresh `pi --mode rpc` process on the SAME session id, the way Colony would.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
RUN = HERE / "run"
WORK = RUN / "workspace"          # the folder the agents are allowed to work in
PI = HERE / "node_modules" / ".bin" / "pi"
SESSION = "conversation-1"        # in Colony this would be the conversation id


def turn(message, model, persona, tools, policy, approve, session=SESSION, extra=(), agent="", agent_dir=None, provider="fake", timeout=60):
    """One agent turn. `approve(request)` answers the approval questions. Returns what happened."""
    cmd = [str(PI), "--mode", "rpc", "--session-dir", str(RUN / "sessions"), "--session-id", session,
           "--provider", provider, "--model", model, "--system-prompt", persona, "--tools", tools,
           "-e", str(HERE / "extensions" / "colony-gate.ts"), *extra]
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent_dir or HERE / "agent-dir"), "PI_OFFLINE": "1",
           "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0", "COLONY_POLICY": json.dumps(policy), "COLONY_AGENT": agent}
    started = time.time()
    proc = subprocess.Popen(cmd, cwd=WORK, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    send = lambda obj: (proc.stdin.write(json.dumps(obj).encode() + b"\n"), proc.stdin.flush())  # noqa: E731
    send({"id": "p", "type": "prompt", "message": message})
    result = {"reply": "", "tools": [], "asked": [], "seconds": 0, "problems": []}
    deadline = time.time() + timeout
    while time.time() < deadline and (line := proc.stdout.readline()):
        rec = json.loads(line)
        kind = rec.get("type")
        if kind == "extension_ui_request" and rec.get("method") in ("confirm", "select"):
            result["asked"].append(rec.get("title"))
            send({"type": "extension_ui_response", "id": rec["id"], "confirmed": bool(approve(rec))})
        elif kind == "tool_execution_end":
            result["tools"].append((rec["toolName"], "error" if rec.get("isError") else "ok"))
        elif kind in ("auto_retry_start", "auto_retry_end", "extension_error"):
            result["problems"].append({k: v for k, v in rec.items() if k != "type"} | {"event": kind})
        elif kind == "message_end" and rec["message"].get("role") == "assistant":
            m = rec["message"]
            if m.get("stopReason") in ("error", "aborted") or m.get("errorMessage"):
                result["problems"].append({"event": "assistant_" + str(m.get("stopReason")), "error": m.get("errorMessage")})
            parts = rec["message"].get("content", [])
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
            if text:
                result["reply"] = text
        elif kind == "agent_settled":
            break
    result["seconds"] = round(time.time() - started, 2)
    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    result["stderr"] = proc.stderr.read().decode()[-600:]
    return result


def requests():
    return [json.loads(l) for l in (RUN / "requests.jsonl").read_text().splitlines()] if (RUN / "requests.jsonl").exists() else []


results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   ({detail})" if detail else ""))


def main():
    shutil.rmtree(RUN, ignore_errors=True)
    WORK.mkdir(parents=True)
    server = subprocess.Popen([sys.executable, str(HERE / "fake_llm.py")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        run_checks()
    finally:
        server.kill()
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


def run_checks():
    yes, no = (lambda r: True), (lambda r: False)
    coder = "You are Coder. Answer with code first."
    writer = "You are Writer. Be warm and brief."

    print("\n1. A basic turn: Pi talks to a model and answers")
    r = turn("hello team", "fake-a", coder, "read,grep,find,ls", {}, yes)
    check("Pi answered through the fake model", "[fake-a]" in r["reply"], r["reply"][:80] or r["stderr"])
    check("Pi (one process per turn) is fast enough", r["seconds"] < 8, f"{r['seconds']}s")

    r = turn("FAIL", "fake-a", coder, "read", {}, yes)
    check("a provider error (429) is visible to the client, not a silent empty reply", bool(r["problems"]), str(r["problems"])[:160])

    print("\n2. Approval: the user is asked before a file is written")
    r = turn("WRITE approved.txt hello-from-agent", "fake-a", coder, "read,write,edit,bash", {"write": "ask"}, yes)
    check("user was asked", len(r["asked"]) == 1, str(r["asked"]))
    check("after 'yes' the file exists", (WORK / "approved.txt").exists() and "hello-from-agent" in (WORK / "approved.txt").read_text())
    r = turn("WRITE denied.txt nope", "fake-a", coder, "read,write,edit,bash", {"write": "ask"}, no)
    check("after 'no' the file was NOT written", not (WORK / "denied.txt").exists(), str(r["tools"]))
    check("the model was told it was refused", "not approve" in r["reply"] or "not approve" in json.dumps(requests()[-1]), r["reply"][:100])

    print("\n3. Permissions per agent")
    r = turn("WRITE allowed.txt fine", "fake-a", coder, "read,write", {"write": "allow"}, no)
    check("'allow' writes without asking", (WORK / "allowed.txt").exists() and not r["asked"])
    r = turn("WRITE forbidden.txt x", "fake-a", writer, "read,write", {"write": "deny"}, yes)
    check("'deny' blocks without asking", not (WORK / "forbidden.txt").exists() and not r["asked"], str(r["tools"]))
    r = turn("hello", "fake-a", writer, "read,grep,find,ls", {}, yes)
    check("a read-only agent is not even offered write/bash", set(requests()[-1]["tools"]) <= {"read", "grep", "find", "ls"}, str(requests()[-1]["tools"]))

    print("\n4. Two agents (different model + persona) share ONE conversation")
    shutil.rmtree(RUN / "sessions", ignore_errors=True)
    (RUN / "requests.jsonl").unlink()
    turn("my project is called Kaprao", "fake-a", coder, "read,grep", {}, yes, session="shared")
    r = turn("what did I say?", "fake-b", writer, "read", {}, yes, session="shared")
    last = requests()[-1]
    check("second agent runs on the other model", last["model"] == "fake-b", last["model"])
    check("second agent gets ITS OWN persona", any("You are Writer" in s for s in last["system"]) and not any("You are Coder" in s for s in last["system"]), str(last["system"])[:160])
    check("second agent sees the first agent's conversation", "Kaprao" in json.dumps(last["messages"]), r["reply"][:120])

    print("\n4b. Agents can't leave the workspace folder")
    outside = RUN / "outside.txt"
    r = turn("WRITE ../outside.txt escaped", "fake-a", coder, "read,write", {"write": "allow"}, yes)
    check("writing outside the folder is blocked even when 'allow'", not outside.exists() and not r["asked"], str(r["tools"]))
    (RUN / "secret.txt").write_text("TOP-SECRET-TOKEN")
    r = turn(f"READ {RUN / 'secret.txt'}", "fake-a", coder, "read", {}, yes)
    check("reading a file outside the folder (absolute path) is blocked", "TOP-SECRET-TOKEN" not in r["reply"], r["reply"][:100])
    (WORK / "inside.txt").write_text("INSIDE-OK")
    r = turn("READ inside.txt", "fake-a", coder, "read", {}, yes)
    check("reading a file inside the folder still works", "INSIDE-OK" in r["reply"], r["reply"][:100])

    print("\n5. Who said what: replies are stamped with the agent's name")
    shutil.rmtree(RUN / "sessions", ignore_errors=True)
    turn("plan the launch", "fake-a", coder, "read", {}, yes, session="labels", agent="Coder")
    r = turn("summarise it", "fake-b", writer, "read", {}, yes, session="labels", agent="Writer")
    seen = [m["content"] for m in requests()[-1]["messages"] if m["role"] == "assistant"]
    check("Writer sees Coder's earlier reply labelled [Coder]", any(c.startswith("[Coder] ") for c in seen), str(seen)[:140])
    check("Writer's own reply is labelled once", r["reply"].startswith("[Writer] ") and not r["reply"].startswith("[Writer] [Writer]"), r["reply"][:60])

    print("\n6. Pi's own defaults don't leak into every agent")
    (WORK / "CLAUDE.md").write_text("PROJECT RULE: always speak like a pirate")
    turn("hi", "fake-a", writer, "read", {}, yes, session="ctx-on")
    on = " ".join(requests()[-1]["system"])
    turn("hi", "fake-a", writer, "read", {}, yes, session="ctx-off", extra=["--no-context-files"])
    off = " ".join(requests()[-1]["system"])
    check("CLAUDE.md in the folder IS loaded by default (so it must be switched off)", "pirate" in on)
    check("--no-context-files keeps it out", "pirate" not in off)
    print(f"      system prompt with our --system-prompt is {len(off)} chars: {off[:200]!r}")


if __name__ == "__main__":
    main()
