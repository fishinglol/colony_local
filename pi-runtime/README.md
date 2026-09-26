# Pi runtime

The [Pi](https://github.com/earendil-works/pi) coding-agent engine (pinned, MIT, needs Node >= 22.19) that runs the
tools of Colony agents that have tools switched on. Colony's Python side (`colony/engine/pi.py`) starts it;
you never run it yourself.

```bash
cd local/pi-runtime && npm install     # once
```

`colony` looks for Pi in this order: `PI_BIN` (env / `.env`), `local/pi-runtime/node_modules/.bin/pi`, then `pi` on PATH.

How agents use it, what is locked down, and what was verified: `local/spike-pi/README.md` (the experiment) and
`colony/engine/colony-gate.ts` (the approval gate + workspace fence).
