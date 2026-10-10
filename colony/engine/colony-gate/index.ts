/**
 * Colony's tool gate for OpenClaw. Loaded as a plugin folder (manifest + this file; plugins.load.paths, set by engine/openclaw.py).
 *
 * Before every tool call except web search and memory lookups, ask Colony (POST /api/approvals/gate) and do what it says: run it, or block
 * it with the reason. Colony applies the user's permissions, the project-folder fence, and, for "ask", puts the question
 * in front of the user and waits. If Colony cannot be reached the call is blocked: no gate, no action.
 * COLONY_URL is set by `colony` when it starts the Gateway (a Gateway started by hand falls back to port 8765).
 */
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const FREE = new Set(["web_search", "memory_search", "memory_get"]);   // read-only, and only over the agent's own memory folder
const OWN = "main";   // the Gateway's own default agent is the user's, not Colony's: never gated, so OpenClaw works without Colony too

export default definePluginEntry({
  id: "colony-gate",
  name: "Colony approvals",
  description: "Asks Colony before an agent reads, writes, runs commands or uses a connector.",
  register(api) {
    api.on(
      "before_tool_call",
      async (event, ctx) => {
        if (FREE.has(event.toolName) || ctx.agentId === OWN) return;
        const url = process.env.COLONY_URL ?? "http://127.0.0.1:8765";
        try {
          const res = await fetch(`${url}/api/approvals/gate`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ agent_id: ctx.agentId, tool: event.toolName, params: event.params }),
            signal: ctx.abortSignal,
          });
          const verdict = (await res.json()) as { allow?: boolean; reason?: string };
          if (verdict.allow === true) return;
          return { block: true, blockReason: verdict.reason || "Colony did not allow this action." };
        } catch {
          return { block: true, blockReason: "Colony is not running, so nobody can approve this action. Start Colony (the `colony` command) and try again." };
        }
      },
      { priority: 100 },
    );
  },
});
