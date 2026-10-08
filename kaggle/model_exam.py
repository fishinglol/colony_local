"""Same exam for every model on the Kaggle Ollama server, through Colony's own stack.

usage: exam.py <kaggle url> [model ...]
Talks to a throwaway Colony (port 8769) so nothing of the owner's data is touched.
"""
import json
import os
import sys
import time
import urllib.request

B = "http://127.0.0.1:8769/api"
KAGGLE = sys.argv[1].rstrip("/")
MODELS = sys.argv[2:] or ["qwen3.5:9b", "gemma4:12b", "scb10x/typhoon2.1-gemma3-12b", "ornith:9b", "lfm2.5:8b"]
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = HERE + "/proj"

PROMPTS = [
    ("chat-th", "วันนี้เหนื่อยจังเลย งานเยอะมาก ไม่อยากทำอะไรเลย"),
    ("write-th", "ช่วยเขียนแคปชันขายเสื้อยืดสีขาวเรียบๆ ราคา 199 บาท สั้นๆ สำหรับ Instagram"),
    ("think-th", "ร้านกาแฟเล็กๆ ควรเปิดสาขาสองหรือเก็บเงินไว้เป็นทุนสำรอง ช่วยชั่งข้อดีข้อเสียและแนะนำมา 1 ข้อ"),
    ("code", "Write a Python function that returns the second largest unique number in a list, or None. Code only."),
    ("facts-th", "เมืองหลวงของประเทศญี่ปุ่นคืออะไร และมีประชากรประมาณกี่คน ตอบสั้นๆ"),
]


def call(path, body=None, method=None, timeout=900):
    req = urllib.request.Request(B + path, None if body is None else json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=timeout))


call("/settings", {"kaggle_base_url": KAGGLE})
call("/workspaces/local", {"folder": PROJECT}, "PATCH")
results = {}
for model in MODELS:
    tid = "kaggle/" + model
    roles = call("/roles")["roles"]
    for r in roles:
        r["model"] = tid
        r["tools"] = {"read": "allow", "write": "allow", "bash": "off"} if r["id"] == "coding" else {}
    call("/roles", {"roles": roles}, "PUT")
    out = {}
    for name, text in PROMPTS:
        t = time.time()
        try:
            d = call("/messages", {"message": text, "role_id": "chitchat", "channel": "chitchat"})
            out[name] = {"s": round(time.time() - t, 1), "reply": d["reply"]}
        except Exception as exc:
            out[name] = {"s": round(time.time() - t, 1), "reply": f"ERROR {exc}"}
        print(model, name, out[name]["s"], "s", flush=True)
    t = time.time()
    target = f"{PROJECT}/tool-{model.replace('/', '_').replace(':', '_')}.txt"
    try:
        d = call("/messages", {"message": f"Use your write tool to create the file {target.rsplit('/', 1)[1]} containing exactly: สวัสดี",
                               "role_id": "coding", "channel": "coding"})
        out["tools"] = {"s": round(time.time() - t, 1), "reply": d["reply"]}
    except Exception as exc:
        out["tools"] = {"s": round(time.time() - t, 1), "reply": f"ERROR {exc}"}
    try:
        out["tools"]["file"] = open(target, encoding="utf-8").read()
    except OSError:
        out["tools"]["file"] = None
    print(model, "tools", out["tools"]["s"], "s file=", out["tools"]["file"], flush=True)
    results[model] = out
    json.dump(results, open(HERE + "/exam-results.json", "w"), ensure_ascii=False, indent=1)
