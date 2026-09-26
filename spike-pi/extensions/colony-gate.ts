/**
 * Colony's tool gate for Pi. Loaded with `pi -e`.
 *
 * COLONY_POLICY (JSON, set per turn by Colony) says what each tool may do for the agent that is answering:
 *   { "write": "ask", "edit": "ask", "bash": "deny" }      "allow" | "ask" | "deny"; a tool not listed is "ask".
 * Whatever the policy, file tools are blocked from paths outside the workspace folder (the folder Pi runs in).
 * (bash can't be fenced this way: keep it "deny" or "ask" unless the whole app runs in a sandbox.)
 * "ask" shows the user what is about to happen and waits for an answer; no answer means no.
 *
 * COLONY_AGENT (the answering agent's name) is stamped on its replies as "[Name] ", so when another agent
 * later reads the shared conversation it can tell who said what.
 */
import { isAbsolute, relative, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const READ_ONLY = ["read", "grep", "find", "ls"];

function describe(tool: string, input: Record<string, unknown>): string {
  if (tool === "bash") return `Run command:\n${String(input.command)}`;
  const path = String(input.path ?? input.file_path ?? "");
  if (tool === "write") return `Write ${path}:\n${String(input.content ?? "").slice(0, 600)}`;
  return `${tool} ${path}:\n${JSON.stringify(input).slice(0, 600)}`;
}

/** True when `path` (relative to the workspace, or absolute) points outside the workspace folder. */
function escapesWorkspace(workspace: string, path: unknown): boolean {
  if (typeof path !== "string" || path === "") return false;
  const rel = relative(workspace, resolve(workspace, path.startsWith("@") ? path.slice(1) : path));
  return rel === ".." || rel.startsWith("..") || isAbsolute(rel);
}

export default function (pi: ExtensionAPI) {
  const agent = process.env.COLONY_AGENT ?? "";
  const label = `[${agent}] `;
  const policy: Record<string, string> = JSON.parse(process.env.COLONY_POLICY ?? "{}");

  pi.on("tool_call", async (event, ctx) => {
    // Pi's own file tools will happily touch any path the user can; agents stay inside the workspace folder.
    const input = event.input as Record<string, unknown>;
    if (escapesWorkspace(ctx.cwd, input.path ?? input.file_path)) {
      return { block: true, reason: "That path is outside the workspace folder, so it is off limits." };
    }
    if (READ_ONLY.includes(event.toolName)) return undefined;
    const rule = policy[event.toolName] ?? "ask";
    if (rule === "allow") return undefined;
    if (rule === "deny") return { block: true, reason: `The ${event.toolName} tool is not allowed for this agent.` };
    if (!ctx.hasUI) return { block: true, reason: "Needs approval but nobody is there to give it." };
    const ok = await ctx.ui.confirm(`Allow ${event.toolName}?`, describe(event.toolName, event.input as Record<string, unknown>), { timeout: 120000 });
    return ok ? undefined : { block: true, reason: "The user did not approve this action." };
  });

  if (agent) {
    pi.on("message_end", async (event) => {
      const message = event.message as { role: string; content?: unknown };
      if (message.role !== "assistant" || !Array.isArray(message.content)) return undefined;
      let stamped = false;
      const content = message.content.map((part: { type: string; text?: string }) => {
        if (stamped || part.type !== "text" || !part.text) return part;
        stamped = true;
        // the model sometimes copies the label from earlier turns; keep exactly one
        const text = part.text.startsWith(label) ? part.text.slice(label.length) : part.text;
        return { ...part, text: label + text };
      });
      return { message: { ...event.message, content } as typeof event.message };
    });
  }
}
