// "Connect a tool": the window (opened from the agent editor) where an agent is given the tools it needs and nothing more.
// Left: everything it could use (project files, commands, web search, ~100 apps through Composio, your own connectors).
// Right: what the tool lets it do, what it will ask you first, and how freely it may act.
//
// It edits a `draft` of the agent's tools: {read, write, bash, mcp, mcp_servers, mcp_apps, web_search}. The editor saves it.
import { api } from './api.js';
import { roleColor } from './avatar.js';
import { $, el, toast } from './dom.js';
import { renderSidebar, selectTarget } from './sidebar.js';
import { currentWorkspace, state } from './state.js';
import { APP_CATEGORIES, APPS, logoSlug } from './apps-catalog.js';

const CATEGORIES = ['Files & storage', 'Browser & web', 'Communication', 'Productivity', 'Data & spreadsheets', 'Design & creative',
  'Developer tools', 'Sales & marketing', 'Finance & commerce', 'Social & media', 'Custom / API'];
const ASK = { v: 'ask', label: 'Ask each time' }, ALLOW = { v: 'allow', label: 'Allow freely' };
const EVERY_APP = 'app:*';

/* ── the draft ─────────────────────────────────────────────────────────────────────────── */
export const emptyTools = () => ({ read: 'off', write: 'off', bash: 'off', mcp: 'off', mcp_servers: [], mcp_apps: [], web_search: false });

export function toolsFromRole(r) {
  const t = r.tools || {};
  return { read: t.read || 'off', write: t.write || 'off', bash: t.bash || 'off', mcp: t.mcp || 'off',
    mcp_servers: t.mcp_servers === undefined ? null : t.mcp_servers, mcp_apps: t.mcp_apps || [], web_search: !!r.web_search };
}

export function toolsForSave(d) {
  return { web_search: d.web_search, tools: { read: d.read, write: d.write, bash: d.bash, mcp: d.mcp, mcp_servers: d.mcp_servers, mcp_apps: d.mcp_apps } };
}

let servers = {};                                   // the connectors set up in Connectors (from /api/mcp); secrets are masked
export async function loadServers() { try { servers = (await api('/mcp')).servers; } catch { servers = {}; } return servers; }
const enabledNames = () => Object.keys(servers).filter((n) => servers[n].enabled);
const serverList = (d) => (d.mcp === 'off' ? [] : d.mcp_servers === null ? enabledNames() : d.mcp_servers);
const hasComposio = () => !!servers.composio && servers.composio.enabled;

// What is switched on, as the rows the editor shows: {id, name, scope}.
export function toolRows(d) {
  const rows = [], mcpScope = d.mcp === 'allow' ? 'Allowed freely' : 'Asks you each time';
  if (d.read !== 'off') rows.push({ id: 'read', name: 'Read project files', scope: 'Project folder' });
  if (d.write !== 'off') rows.push({ id: 'write', name: 'Create & edit files', scope: d.write === 'allow' ? 'Allowed freely' : 'Asks you each time' });
  if (d.bash !== 'off') rows.push({ id: 'bash', name: 'Run commands', scope: d.bash === 'allow' ? 'Allowed freely' : 'Asks you each time' });
  if (d.web_search) rows.push({ id: 'web', name: 'Search the web', scope: 'Sources listed under replies' });
  const names = serverList(d);
  if (names.includes('composio')) {
    if (d.mcp_apps.length) d.mcp_apps.forEach((a) => rows.push({ id: `app:${a}`, name: a, scope: `via Composio · ${mcpScope}` }));
    else rows.push({ id: EVERY_APP, name: 'Every app in Composio', scope: mcpScope });
  }
  names.filter((n) => n !== 'composio').forEach((n) => rows.push({ id: `srv:${n}`, name: n, scope: `Connector · ${mcpScope}` }));
  return rows;
}

function normalise(d) {
  if (d.mcp_servers !== null && !d.mcp_servers.length) { d.mcp = 'off'; d.mcp_apps = []; }
  if (d.mcp === 'off') { d.mcp_servers = []; d.mcp_apps = []; }
  if (!(d.mcp_servers || []).includes('composio')) d.mcp_apps = [];
  return d;
}

function connect(d, id, scope) {
  if (id === 'read') d.read = 'allow';
  else if (id === 'write') d.write = scope;
  else if (id === 'bash') d.bash = scope;
  else if (id === 'web') d.web_search = true;
  else {
    d.mcp = scope;
    const names = d.mcp_servers === null ? enabledNames() : [...d.mcp_servers];
    const server = id.startsWith('srv:') ? id.slice(4) : 'composio';
    if (!names.includes(server)) names.push(server);
    d.mcp_servers = names;
    if (id === EVERY_APP) d.mcp_apps = [];
    else if (id.startsWith('app:') && !d.mcp_apps.includes(id.slice(4))) d.mcp_apps = [...d.mcp_apps, id.slice(4)];
  }
  return normalise(d);
}

export function disconnect(d, id) {
  if (id === 'read') d.read = 'off';
  else if (id === 'write') d.write = 'off';
  else if (id === 'bash') d.bash = 'off';
  else if (id === 'web') d.web_search = false;
  else if (id.startsWith('srv:')) d.mcp_servers = serverList(d).filter((n) => n !== id.slice(4));
  else if (id === EVERY_APP) d.mcp_servers = serverList(d).filter((n) => n !== 'composio');
  else {
    d.mcp_apps = d.mcp_apps.filter((a) => a !== id.slice(4));
    if (!d.mcp_apps.length) d.mcp_servers = serverList(d).filter((n) => n !== 'composio');
  }
  return normalise(d);
}

const isOn = (d, id) => toolRows(d).some((r) => r.id === id);

/* ── the catalogue ─────────────────────────────────────────────────────────────────────── */
function catalogue() {
  const items = [
    { id: 'read', kind: 'file', name: 'Read project files', category: 'Files & storage', blurb: 'Read and search files in the project folder.' },
    { id: 'write', kind: 'file', name: 'Create & edit files', category: 'Files & storage', blurb: 'Write new files and change existing ones in the project folder.' },
    { id: 'bash', kind: 'file', name: 'Run commands', category: 'Developer tools', blurb: 'Run shell commands in the project folder.' },
    { id: 'web', kind: 'web', name: 'Search the web', category: 'Browser & web', blurb: 'Look things up online and cite the pages it used.' },
    { id: EVERY_APP, kind: 'app', name: 'Every app in Composio', category: 'Productivity', blurb: 'One connection to 1000+ apps; connects each one the first time it is needed.' },
  ];
  APPS.forEach(([name, category, blurb]) => items.push({ id: `app:${name}`, kind: 'app', name, category, blurb }));
  items.push({ id: 'new', kind: 'add', name: 'Add a connector', category: 'Custom / API', blurb: 'Connect any MCP server by its address or command.' });
  Object.keys(servers).filter((n) => n !== 'composio').forEach((n) => items.push({
    id: `srv:${n}`, kind: 'server', name: n, category: 'Custom / API', blurb: servers[n].url || `${servers[n].command} ${(servers[n].args || []).join(' ')}`.trim() }));
  return items;
}

/* ── the window ────────────────────────────────────────────────────────────────────────── */
let ctx = null, category = 'All', query = '', selected = 'read', scope = 'ask', touched = false;

// The little square for a tool: its real logo when there is one, a symbol for Colony's own tools, else the first letter.
const GLYPHS = { read: '▤', write: '✎', bash: '›_', web: '⌕', new: '＋' };
export function toolLogo(item) {
  const tile = el('div', 'tp-logo');
  if (GLYPHS[item.id]) { tile.classList.add('glyph'); tile.textContent = GLYPHS[item.id]; return tile; }
  const letter = () => { tile.className = 'tp-logo'; tile.style.background = roleColor(item.name.toLowerCase()); tile.textContent = item.name.slice(0, 1).toUpperCase(); };
  const slug = item.id === EVERY_APP ? 'composio' : item.id.startsWith('app:') && !item.custom ? logoSlug(item.name) : null;
  if (!slug) { letter(); return tile; }
  tile.classList.add('img');
  const img = el('img'); img.alt = ''; img.loading = 'lazy'; img.src = `https://logos.composio.dev/api/${slug}`;
  img.onerror = () => { img.remove(); letter(); };
  tile.appendChild(img);
  return tile;
};

function visible() {
  const q = query.trim().toLowerCase();
  const list = catalogue().filter((i) => (category === 'All' || i.category === category)
    && (!q || `${i.name} ${i.blurb} ${i.category}`.toLowerCase().includes(q)));
  const exact = catalogue().some((i) => i.name.toLowerCase() === q);
  if (q && !exact && (category === 'All' || category === 'Productivity')) {       // any other app Composio knows, by name
    const name = query.trim();
    list.unshift({ id: `app:${name}`, kind: 'app', name, category: 'Productivity', blurb: `Use “${name}” through Composio (it supports 1000+ apps).`, custom: true });
  }
  return list;
}

function lockedFor(item) { return ctx.locked && item.kind !== 'web' && item.kind !== 'add'; }

function statusOf(item) {
  if (item.kind === 'add') return { text: 'Available', cls: '' };
  if (isOn(ctx.draft, item.id)) return { text: 'Connected', cls: 'on' };
  if (lockedFor(item)) return { text: "Model can't use tools", cls: 'warn' };
  if (item.kind === 'file' && !ctx.folder) return { text: 'Needs a project folder', cls: 'warn' };
  if (item.kind === 'app' && !hasComposio()) return { text: 'Needs Composio key', cls: 'warn' };
  return { text: 'Available', cls: '' };
}

function pickScopeFor(item) {
  const d = ctx.draft;
  const current = item.id === 'write' ? d.write : item.id === 'bash' ? d.bash : item.kind === 'app' || item.kind === 'server' ? d.mcp : 'ask';
  return current === 'allow' ? 'allow' : 'ask';
}

function select(id) { selected = id; const item = catalogue().find((i) => i.id === id) || visible().find((i) => i.id === id); scope = item ? pickScopeFor(item) : 'ask'; renderList(); renderDetail(); }

function renderPills() {
  const box = $('tpPills'); box.innerHTML = '';
  ['All', ...CATEGORIES].forEach((c) => {
    const b = el('button', 'tp-pill' + (c === category ? ' on' : ''), c); b.type = 'button';
    b.onclick = () => { category = c; renderPills(); renderList(); };
    box.appendChild(b);
  });
}

function renderList() {
  const box = $('tpList'); box.innerHTML = '';
  const items = visible();
  if (!items.length) { box.appendChild(el('div', 'tp-empty', 'Nothing matches. Try another word.')); return; }
  items.forEach((item) => {
    const b = el('button', 'tp-item' + (item.id === selected ? ' sel' : '')); b.type = 'button';
    const text = el('div'), st = statusOf(item);
    text.append(el('div', 'tp-name', item.name), el('div', 'tp-blurb', item.blurb), el('div', `tp-status ${st.cls}`, st.text));
    b.append(toolLogo(item), text);
    b.onclick = () => select(item.id);
    box.appendChild(b);
  });
}

function bullets(items, cls) {
  const box = el('div');
  items.forEach((t) => { const li = el('div', 'tp-li'); li.append(el('span', cls, cls === 'ck' ? '✓' : ''), el('span', null, t)); box.appendChild(li); });
  return box;
}

// What each kind of tool can do, and what it asks first (truthful to how Colony really behaves).
function describe(item) {
  const app = item.name;
  if (item.id === 'read') return { can: ['Read files inside the project folder', 'List folders and search text in files'], ask: [], scopes: [{ v: 'allow', label: 'Project folder only' }], fixed: true,
    note: 'Reading never asks, and it can never leave the project folder.' };
  if (item.id === 'write') return { can: ['Create new files in the project folder', 'Edit files that are already there'], ask: ['Creating or changing any file'], scopes: [ASK, ALLOW],
    note: 'Always limited to the project folder.' };
  if (item.id === 'bash') return { can: ['Run commands in the project folder'], ask: ['Every command it wants to run'], scopes: [ASK, ALLOW],
    warn: 'A command can do anything your account can do. Keep “Ask each time” unless you fully trust this agent.' };
  if (item.id === 'web') return { can: ['Search the web for every message it answers', 'List the pages it used as Sources under the reply'], ask: [], scopes: [{ v: 'allow', label: 'Every message' }], fixed: true,
    note: 'About $0.007 per message through OpenRouter’s web search, even on free models, so it needs credits.' };
  if (item.id === EVERY_APP) return { can: ['Use any of the 1000+ apps in Composio', 'Connect a new app the first time it needs it (you sign in through a link)'],
    ask: ['Every action in an app: sending, creating, editing, deleting'], scopes: [ASK, ALLOW], apps: true };
  if (item.kind === 'app') return { can: [`Look up your ${app} data once you have signed in`, `Create or change things in ${app} when it helps`, `Sign-in happens the first time it needs ${app}; you get a link to open`],
    ask: [`Every action in ${app}`, 'Anything that sends, edits or deletes'], scopes: [ASK, ALLOW], apps: true,
    note: `The agent is told to stay within ${app} and the other apps you connect to it. Every action still shows you what it will do.` };
  return { can: ['Use the tools this connector offers'], ask: ['Every tool it calls'], scopes: [ASK, ALLOW] };
}

function renderDetail() {
  const box = $('tpDetail'); box.innerHTML = '';
  const item = catalogue().find((i) => i.id === selected) || visible().find((i) => i.id === selected);
  if (!item) { $('tpGo').disabled = true; return; }
  if (item.kind === 'add') { renderAddForm(box, item); return; }
  $('tpGo').style.display = '';
  const info = describe(item), on = isOn(ctx.draft, item.id), st = statusOf(item);
  const head = el('div', 'tp-d-head'), title = el('div');
  title.append(el('h4', null, item.name), el('span', 'tp-badge ' + (on ? 'on' : st.cls), on ? 'Connected' : st.text));
  head.append(toolLogo(item), title); box.appendChild(head);
  box.append(el('div', 'tp-sec', 'This agent can'), bullets(info.can, 'ck'));
  box.append(el('div', 'tp-sec', 'Needs approval before'));
  box.appendChild(scope === 'ask' && info.ask.length ? bullets(info.ask, 'dot') : el('div', 'tp-note', info.ask.length ? 'Nothing: with “Allow freely” it acts without asking.' : 'Nothing. This one never asks.'));
  box.append(el('div', 'tp-sec', 'Access scope'));
  const row = el('div', 'tp-scopes');
  info.scopes.forEach((s) => {
    const b = el('button', 'tp-scope' + (info.fixed || s.v === scope ? ' on' : ''), s.label); b.type = 'button'; b.disabled = !!info.fixed;
    b.onclick = () => { scope = s.v; renderDetail(); };
    row.appendChild(b);
  });
  box.appendChild(row);
  if (!info.fixed) box.appendChild(el('div', 'tp-note', 'Recommended default: Ask each time.' + (info.apps || item.kind === 'server' ? ' This applies to all the connected apps of this agent.' : '')));
  if (info.note) box.appendChild(el('div', 'tp-note', info.note));
  if (info.warn) box.appendChild(el('div', 'tp-note warn', info.warn));
  if (item.kind === 'file' && !ctx.folder) box.appendChild(el('div', 'tp-note warn', 'This workspace has no project folder yet. Choose one (Workspace settings) before the agent can use it.'));
  if (lockedFor(item)) box.appendChild(el('div', 'tp-note warn', "This agent's model can't use tools (OpenRouter lists no tool support for it). Pick another model first."));
  if (item.kind === 'app' && !hasComposio()) box.appendChild(composioSetup());
  if (on && ctx.standalone && item.kind === 'app' && item.id !== EVERY_APP) {
    const signIn = el('button', 'btn small', `Sign in to ${item.name}`); signIn.type = 'button'; signIn.style.marginTop = '16px';
    signIn.title = 'Puts a request in the chat; the agent answers with a sign-in link.';
    signIn.onclick = () => { const id = ctx.roleId; closeToolPicker(); selectTarget(id); $('prompt').value = `Connect my ${item.name} account so you can use it.`; $('prompt').focus(); };
    box.appendChild(signIn);
  }
  if (on) {
    const off = el('button', 'tp-link', `Disconnect ${item.name} from ${ctx.agentName || 'this agent'}`); off.type = 'button';
    off.onclick = () => { ctx.draft = disconnect(ctx.draft, item.id); changed(`${item.name} disconnected`); };
    box.appendChild(off);
  }
  const removable = item.kind === 'server' ? item.id.slice(4) : item.id === EVERY_APP && hasComposio() ? 'composio' : null;
  if (removable) {
    const gone = el('button', 'tp-link', `Remove ${removable === 'composio' ? 'the Composio key' : item.name} from Colony`); gone.type = 'button';
    gone.onclick = () => removeServer(removable);
    box.appendChild(gone);
  }
  const go = $('tpGo');
  go.textContent = on ? 'Save changes' : 'Connect tool';
  go.disabled = lockedFor(item) || (item.kind === 'app' && !hasComposio());
  go.onclick = () => { ctx.draft = connect(ctx.draft, item.id, info.fixed ? 'allow' : scope); changed(`${item.name} connected`); };
}

function composioSetup() {
  const box = el('div', 'tp-setup');
  box.append(el('div', 'tp-li', 'Apps come through Composio. Paste your Composio consumer key once (from the consumer dashboard at composio.dev; it starts with ck_). It is stored only on this computer.'));
  const row = el('div', 'input-row'), key = el('input'), add = el('button', 'btn', 'Add Composio');
  key.type = 'password'; key.autocomplete = 'off'; key.placeholder = 'ck_…'; add.type = 'button';
  add.onclick = async () => {
    try { servers = (await api('/mcp/composio', { method: 'POST', body: JSON.stringify({ key: key.value }) })).servers; toast('Composio added'); renderList(); renderDetail(); }
    catch (err) { toast(err.message); }
  };
  row.append(key, add); box.appendChild(row);
  return box;
}

function changed(message) {
  touched = true;
  ctx.onChange(ctx.draft);
  $('tpGuard').textContent = message;
  $('tpCancel').textContent = 'Done';
  renderList(); renderDetail();
}

// "KEY=value" lines for a program, "Header: value" lines for an address.
function secretsFrom(text, isUrl) {
  const out = {}, split = isUrl ? ':' : '=';
  text.split('\n').map((l) => l.trim()).filter(Boolean).forEach((line) => {
    const at = line.indexOf(split);
    if (at > 0) out[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  });
  return out;
}

async function putServers(next) {
  servers = (await api('/mcp', { method: 'PUT', body: JSON.stringify({ servers: next }) })).servers;
}

async function removeServer(name) {
  if (!confirm(`Remove ${name === 'composio' ? 'Composio' : name} from Colony? Agents will lose access to it.`)) return;
  try {
    const { [name]: _gone, ...rest } = servers;
    await putServers(rest);
    ctx.draft = disconnect(ctx.draft, name === 'composio' ? EVERY_APP : `srv:${name}`);
    changed(`${name} removed`); select('read');
  } catch (err) { toast(err.message); }
}

function renderAddForm(box) {
  $('tpGo').style.display = 'none';
  const head = el('div', 'tp-d-head'), title = el('div');
  title.append(el('h4', null, 'Add a connector'), el('span', 'tp-badge', 'Any MCP server'));
  head.append(toolLogo({ id: 'new', name: 'Add a connector' }), title); box.appendChild(head);
  box.append(el('div', 'tp-sec', 'What it is'), el('div', 'tp-note', 'A connector is an MCP server: a program on this computer (for example npx -y some-mcp-server) or a web address (https://…). Once added, it appears in this list and you can connect it to an agent.'));
  const field = (label, control) => { const w = el('div', 'tp-field'); w.append(el('label', null, label), control); return w; };
  const name = el('input'), target = el('input'), secrets = el('textarea');
  name.placeholder = 'e.g. github'; name.maxLength = 40;
  target.placeholder = 'https://example.com/mcp   or   npx -y some-mcp-server'; target.autocomplete = 'off';
  secrets.rows = 3; secrets.placeholder = 'Optional secrets, one per line.\nFor an address:  Authorization: Bearer …\nFor a command:  API_KEY=…';
  box.append(field('Name', name), field('Address or command', target), field('Secrets', secrets));
  const err = el('div', 'tp-note warn'), add = el('button', 'btn primary', 'Add connector'); add.type = 'button'; add.style.marginTop = '14px';
  add.onclick = async () => {
    const n = name.value.trim().toLowerCase(), t = target.value.trim();
    if (!n || !t) { err.textContent = 'Give it a name and an address or command.'; return; }
    const isUrl = t.startsWith('http://') || t.startsWith('https://'), extra = secretsFrom(secrets.value, isUrl);
    const [command, ...args] = t.split(' ').filter(Boolean);
    try { await putServers({ ...servers, [n]: isUrl ? { url: t, headers: extra } : { command, args, env: extra } }); changed(`${n} added`); select(`srv:${n}`); }
    catch (e) { err.textContent = e.message; }
  };
  box.append(err, add);
}

function fillAgentPicker() {
  const sel = $('tpAgentSel'); sel.innerHTML = '';
  state.roles.forEach((r) => { const o = el('option', null, r.name); o.value = r.id; o.selected = r.id === ctx.roleId; sel.appendChild(o); });
  $('tpAgentPick').style.display = ctx.standalone ? '' : 'none';
  $('tpAgent').style.display = ctx.standalone ? 'none' : '';
}

function show(guard) {
  category = 'All'; query = ''; touched = false;
  $('tpSearch').value = '';
  $('tpSub').textContent = `Give ${ctx.agentName || 'this agent'} access to only what it needs.`;
  $('tpAgent').textContent = `Agent · ${ctx.agentName || 'New agent'}`;
  $('tpGuard').textContent = guard || 'Agents ask before editing, sending, deleting or sharing unless you choose “Allow freely”.';
  $('tpCancel').textContent = ctx.standalone ? 'Close' : 'Cancel';
  fillAgentPicker();
  selected = ctx.select || 'read'; scope = 'ask';
  renderPills(); select(selected);
  $('toolPicker').classList.add('open');
}

// Opened from the agent editor: edits the editor's draft; the editor saves it.
export async function openToolPicker(options) {
  ctx = { ...options, draft: JSON.parse(JSON.stringify(options.draft)) };
  await loadServers();
  show(); $('tpSearch').focus();
}

// Opened from the sidebar's Connectors button: works on an agent that already exists and saves right away.
async function loadAgent(role) {
  let locked = false;
  try { locked = (await api(`/models/tools?model=${encodeURIComponent(role.model)}`)).supported === false; } catch { /* unknown: don't lock */ }
  ctx = { standalone: true, roleId: role.id, agentName: role.name, draft: toolsFromRole(role), locked,
    folder: (currentWorkspace() || {}).effective_folder, onChange: saveRole };
}

async function saveRole(draft) {
  const next = state.roles.map((r) => (r.id === ctx.roleId ? { ...r, ...toolsForSave(draft) } : r));
  try {
    state.roles = (await api(`/roles?workspace_id=${encodeURIComponent(state.workspaceId)}`, { method: 'PUT', body: JSON.stringify({ roles: next }) })).roles;
    renderSidebar();
  } catch (err) { toast(err.message); }
}

export async function openConnectors() {
  if (!state.roles.length) return;
  await loadServers();
  await loadAgent(state.roles.find((r) => r.id === state.target) || state.roles[0]);
  show(); $('tpSearch').focus();
}

export function closeToolPicker() { $('toolPicker').classList.remove('open'); ctx = null; }

export function initToolPicker() {
  $('tpAgentSel').onchange = async () => {
    const role = state.roles.find((r) => r.id === $('tpAgentSel').value);
    if (role) { await loadAgent(role); show(); }
  };
  $('tpSearch').addEventListener('input', () => { query = $('tpSearch').value; renderList(); const first = visible()[0]; if (first && query.trim()) select(first.id); });
  $('tpSearch').addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); closeToolPicker(); } });
  ['tpCancel', 'tpClose', 'tpBack'].forEach((id) => { $(id).onclick = closeToolPicker; });
  $('toolPicker').addEventListener('click', (e) => { if (e.target === $('toolPicker')) closeToolPicker(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('toolPicker').classList.contains('open')) { e.stopPropagation(); closeToolPicker(); } }, true);
}

export { APP_CATEGORIES };
