/**
 * Colony's tool gate for Pi. Loaded by colony/engine/pi.py with `pi -e`.
 *
 * COLONY_POLICY (JSON, set per turn from the agent's permissions) says what each tool may do:
 *   { "write": "ask", "edit": "ask", "bash": "off" }    "allow" | "ask" | "off"; a tool not listed is "ask".
 * "ask" shows the user what is about to happen and waits for the answer; no answer means no.
 *
 * Whatever the policy, file tools are blocked from paths outside the workspace folder (the folder Pi runs in).
 * bash can't be fenced this way: it can do anything the user's account can, so "allow" for bash is a big trust.
 *
 * The approval question's `title` is the tool name (write, edit, bash, mcp); `message` says what it wants to do.
 *
 * Connectors (pi-mcp-adapter's single `mcp` tool): looking around (search, describe, connect) is allowed whenever the
 * agent may use connectors at all; only actually CALLING a connector's tool asks. Anything that would change the
 * connector setup itself (install, auth, a url) is refused: the list of connectors is Colony's, not the agent's.
 */
import { isAbsolute, relative, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const READ_ONLY = ["read", "grep", "find", "ls"];
const SHOWN = 600; // characters of file content / command shown in an approval question

/** True when `path` (relative to the workspace, or absolute) points outside the workspace folder. */
function escapesWorkspace(workspace: string, path: unknown): boolean {
  if (typeof path !== "string" || path === "") return false;
  const rel = relative(workspace, resolve(workspace, path.startsWith("@") ? path.slice(1) : path));
  return rel === ".." || rel.startsWith("../") || isAbsolute(rel);
}

function describe(tool: string, input: Record<string, unknown>): string {
  const path = String(input.path ?? input.file_path ?? "");
  if (tool === "mcp") {
    const args = typeof input.args === "string" ? input.args : JSON.stringify(input.args ?? {});
    return `Use connector tool ${String(input.tool)}${input.server ? ` (server ${String(input.server)})` : ""}:\n${args.slice(0, SHOWN)}`;
  }
  if (tool === "bash") return `Run this command:\n${String(input.command).slice(0, SHOWN)}`;
  if (tool === "write") return `Write ${path}:\n${String(input.content ?? "").slice(0, SHOWN)}`;
  if (tool === "edit" && Array.isArray(input.edits)) {
    const changes = input.edits
      .map((e: { oldText?: string; newText?: string }) => `- ${String(e.oldText ?? "").slice(0, 200)}\n+ ${String(e.newText ?? "").slice(0, 200)}`)
      .join("\n");
    return `Edit ${path}:\n${changes.slice(0, SHOWN)}`;
  }
  return `${tool} ${path}:\n${JSON.stringify(input).slice(0, SHOWN)}`;
}

export default function (pi: ExtensionAPI) {
  const policy: Record<string, string> = JSON.parse(process.env.COLONY_POLICY ?? "{}");
  const timeout = Number(process.env.COLONY_APPROVAL_TIMEOUT_MS ?? 120000);

  pi.on("tool_call", async (event, ctx) => {
    const input = event.input as Record<string, unknown>;
    if (escapesWorkspace(ctx.cwd, input.path ?? input.file_path)) {
      return { block: true, reason: "That path is outside the workspace folder, so it is off limits." };
    }
    if (READ_ONLY.includes(event.toolName)) return undefined;
    const rule = policy[event.toolName] ?? "ask";
    if (event.toolName === "mcp") {
      if (rule === "off") return { block: true, reason: "Connectors are not allowed for this agent." };
      if (input.action !== undefined || input.url !== undefined) {
        return { block: true, reason: "Connectors are set up by the user in Colony's settings; an agent can't install or sign in to them." };
      }
      if (input.tool === undefined) return undefined;   // search / describe / connect: only looks
    }
    if (rule === "allow") return undefined;
    if (rule === "off") return { block: true, reason: `The ${event.toolName} tool is not allowed for this agent.` };
    if (!ctx.hasUI) return { block: true, reason: "Needs approval but nobody is there to give it." };
    const ok = await ctx.ui.confirm(event.toolName, describe(event.toolName, input), { timeout });
    return ok ? undefined : { block: true, reason: "The user did not approve this action." };
  });
}
