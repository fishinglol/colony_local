// Shared mutable UI state. Modules import `state` and read/write its fields.
export const state = {
  roles: [],            // the open workspace's agents (from /api/roles)
  target: null,         // null = #auto (Jev picks); otherwise an agent id
  workspaces: [],       // every workspace (from /api/workspaces)
  workspaceId: null,    // the open workspace; its team is `roles`, its one conversation is `messages`
  messages: [],         // every message of the open workspace, all rooms (mix chat + direct chats)
  pending: null,        // {channel, roleId} while a reply is on its way
  editingId: null,      // agent id being edited; '' = a new agent
  busy: false,          // a reply is in flight
  attached: [],         // files in the chat box, waiting to be sent: {key, name, size, kind, id, preview, status}
  approvals: [],        // actions an agent is waiting for a yes/no on (from /api/approvals, while a reply is pending)
  modelCatalog: false,  // true when /api/models returned its list
  modelPool: [],        // every model the picker offers, with capabilities (from /api/models; loaded on first use)
};

export const currentWorkspace = () => state.workspaces.find((w) => w.id === state.workspaceId);
