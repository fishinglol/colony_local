/**
 * Colony's tool gate for OpenClaw. Loaded as a plugin folder (manifest + this file; plugins.load.paths, set by engine/openclaw.py).
 *
 * Before every tool call except web search and memory lookups (and except in sessions the app runs natively on the Gateway), ask Colony (POST /api/approvals/gate) and do what it says: run it, or block
 * it with the reason. Colony applies the user's permissions, the project-folder fence, and, for "ask", puts the question
 * in front of the user and waits. If Colony cannot be reached the call is blocked: no gate, no action.
 * After each call it also reports the result to POST /api/activity/tool (shown as steps under the reply).
 * COLONY_URL is set by `colony` when it starts the Gateway (a Gateway started by hand falls back to port 8765).
 */
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const FREE = new Set(["web_search", "memory_search", "memory_get"]);   // read-only, and only over the agent's own memory folder
const OWN = "main";   // the Gateway's own default agent is the user's, not Colony's: never gated, so OpenClaw works without Colony too

/** Sessions the app opens straight on the Gateway ("native-..."): the Gateway's own permission mode, project-folder fence and
 *  approvals decide there, so Colony does not ask a second time. Turns that reach OpenClaw any other way are still gated. */
const nativeSession = (key?: string) => typeof key === "string" && key.includes(":native-");

const base = () => process.env.COLONY_URL ?? "http://127.0.0.1:8765";

export default definePluginEntry({
  id: "colony-gate",
  name: "Colony approvals",
  description: "Asks Colony before an agent reads, writes, runs commands or uses a connector.",
  register(api) {
    api.on(
      "before_tool_call",
      async (event, ctx) => {
        if (FREE.has(event.toolName) || ctx.agentId === OWN || nativeSession(ctx.sessionKey)) return;
        const url = base();
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

    // After each tool call: tell Colony what happened, so the chat can show it under the reply (best effort, never blocks the agent).
    api.on("after_tool_call", async (event, ctx) => {
      if (ctx.agentId === OWN) return;
      try {
        await fetch(`${base()}/api/activity/tool`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            agent_id: ctx.agentId, tool: event.toolName, params: event.params,
            result: event.result ?? null, error: event.error ?? null, duration_ms: event.durationMs ?? null,
          }),
          signal: AbortSignal.timeout(3000),
        });
      } catch {
        /* Colony is not there: the step is simply not shown */
      }
    });
  },
});
