/**
 * Colony's MCP connectors for Pi. Loaded by colony/engine/pi.py with `pi -e` when an agent may use connectors.
 *
 * pi-mcp-adapter normally merges MCP config files from many places (~/.config/mcp, ~/.agents, and the project's own
 * .mcp.json / .pi/mcp.json — which would let any folder you open start programs). Handing it a `config` object makes it
 * use ONLY that: the servers Colony wrote to COLONY_MCP_FILE for this turn.
 */
import { readFileSync } from "node:fs";
import { createMcpAdapter } from "pi-mcp-adapter";

export default createMcpAdapter({ config: JSON.parse(readFileSync(String(process.env.COLONY_MCP_FILE), "utf8")) });
