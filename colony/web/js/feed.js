// The message feed: which messages are shown (mix chat vs an agent's direct chat),
// sending, and the "Ask another agent" menu.
//
// Every message is tagged with the room it was typed in ("auto" = group chat, or an agent id).
// The feed shows ONE room at a time, but the server still gives every agent the whole
// conversation as context — rooms only change what you see here.
import { api } from './api.js';
import { openAgentModal } from './agent-editor.js';
import { fileUrl, pendingUploads, tagOf, takeAttached } from './attachments.js';
import { avatar } from './avatar.js';
import { refreshContext } from './context.js';
import { $, el, shortModel, timeOf, toast } from './dom.js';
import { renderMarkdown } from './markdown.js';
import { renderWork } from './work.js';
import { currentWorkspace, state } from './state.js';

const currentChannel = () => state.target || 'auto';
const channelOf = (m) => (m.role === 'user' ? m.channel : (m.metadata || {}).channel) || 'auto';

function scrollDown() { const f = $('feed'); f.scrollTop = f.scrollHeight; }

// Draw the current room from state.messages (plus a typing indicator if a reply is on its way here).
export function renderFeed() {
  const inner = $('feedInner'); inner.innerHTML = '';
  const channel = currentChannel();
  const shown = state.messages.map((m, i) => [m, i]).filter(([m]) => channelOf(m) === channel);
  const waiting = state.pending && state.pending.channel === channel;
  if (!shown.length && !waiting) { showEmpty(); return; }
  let lastQuestion = '', lastFiles = [];
  shown.forEach(([m]) => {
    if (m.role === 'user') { lastQuestion = m.content; lastFiles = m.attachments || []; addOwner(m.content, m.created_at, lastFiles); }
    else addAgent(m.content, m.metadata || {}, m.created_at, lastQuestion, lastFiles);
  });
  if (waiting) { addTyping(state.pending.roleId); state.approvals.forEach(addApproval); }
}

function showEmpty() {
  const inner = $('feedInner'); inner.innerHTML = '';
  const box = el('div', 'empty');
  const role = state.roles.find((r) => r.id === state.target);
  if (role) {
    box.append(el('h1', null, `Direct chat with ${role.name}`),
      el('p', null, `Just you and ${role.name} in this room. ${role.name} still sees your group chat and everything you've told the other agents, so you never have to repeat yourself.`));
  } else {
    const ws = currentWorkspace();
    box.append(el('h1', null, ws ? ws.name : 'One workspace. Every AI.'),
      el('p', null, 'Everything in this workspace shares one conversation and one memory. Laya routes each message here to the right agent, or open an agent to talk to it directly — it still sees everything.'));
    const agents = el('div', 'empty-agents');
    state.roles.forEach((r) => {
      const chip = el('button', 'chip-btn'); chip.append(avatar(r), el('span', null, `${r.name} · ${shortModel(r.model)}`));
      chip.onclick = () => openAgentModal(r.id);
      agents.appendChild(chip);
    });
    box.appendChild(agents);
  }
  inner.appendChild(box);
}

function addOwner(text, iso, files = []) {
  const inner = $('feedInner'); if (inner.querySelector('.empty')) inner.innerHTML = '';
  const msg = el('div', 'msg owner'), col = el('div', 'msg-col'), head = el('div', 'msg-head');
  head.append(el('span', 'msg-name', 'You'), el('span', 'msg-time', timeOf(iso)));
  col.appendChild(head);
  if (files.length) {
    const row = el('div', 'owner-files');
    files.forEach((f) => {
      if (f.kind === 'image') { const img = el('img'); img.src = fileUrl(f); img.alt = f.name; img.title = f.name; row.appendChild(img); return; }
      const chip = el('div', 'attach'); chip.append(el('div', 'ico', tagOf(f.kind)), el('div', 'meta', null));
      chip.lastChild.appendChild(el('div', 'fname', f.name)); row.appendChild(chip);
    });
    col.appendChild(row);
  }
  col.appendChild(el('div', 'owner-bubble', text));
  msg.appendChild(col); inner.appendChild(msg); scrollDown();
}

function addAgent(text, meta, iso, question, files = []) {
  const inner = $('feedInner'); if (inner.querySelector('.empty')) inner.innerHTML = '';
  const role = state.roles.find((r) => r.id === meta.role_id) || (meta.role_name ? { id: meta.role_id, name: meta.role_name } : null);
  const msg = el('div', 'msg'), col = el('div', 'msg-col'), head = el('div', 'msg-head');
  head.append(el('span', 'msg-name', meta.role_name || 'AI'), el('span', 'msg-time', timeOf(iso)));
  if (meta.model && meta.model !== 'none') head.append(el('span', 'tag', shortModel(meta.model)));
  if (meta.decided_by === 'ollama') {
    head.append(el('span', 'tag', `Nemotron ${Math.round((meta.confidence || 0) * 100)}%`));
  } else if (meta.decided_by === 'jev') {
    head.append(el('span', 'tag', `Jev ${Math.round((meta.confidence || 0) * 100)}%`));
  } else if (meta.decided_by === 'laya') {
    head.append(el('span', 'tag', `Laya ${Math.round((meta.confidence || 0) * 100)}%`));
  }
  if (meta.decided_by === 'fallback') {
    const t = el('span', 'tag warn', 'Decider unavailable — default agent');
    t.title = 'The decider (Jev, Laya or Nemotron) could not be reached, so the first agent answered.'; head.append(t);
  }
  if (meta.memory_saved) head.append(el('span', 'tag mem', 'Saved to memory'));
  const body = el('div', 'md'); body.innerHTML = renderMarkdown(text);

  const work = renderWork(meta.steps || [], { thinking: meta.thinking || '', workedS: meta.worked_s });
  if (work) col.dataset.hasWork = '1';

  const actions = el('div', 'msg-actions'), copy = el('button', null, 'Copy');
  copy.onclick = async () => { await navigator.clipboard.writeText(text); toast('Copied'); };
  actions.appendChild(copy);
  if (question && meta.role_id) {
    const other = el('button', null, 'Ask another agent ▾');
    other.onclick = (e) => openAskMenu(e.currentTarget, question, meta.role_id, files);
    actions.appendChild(other);
  }
  col.append(head);
  if (work) col.appendChild(work);
  col.append(body, actions);
  msg.append(avatar(role, true), col); inner.appendChild(msg); scrollDown();
}

function addTyping(roleId) {
  const msg = el('div', 'msg'); msg.id = 'typing';
  const act = state.activity || {};
  const agentName = act.agent_name || (state.roles.find((r) => r.id === roleId)?.name);
  const role = state.roles.find((r) => r.id === (roleId || (act.agent_name ? state.roles.find((x) => x.name === act.agent_name)?.id : null)));
  const col = el('div', 'msg-col'), head = el('div', 'msg-head');

  let title = 'Deciding which agent answers…';
  if (act.step === 'routing') title = 'Choosing who answers…';
  else if (agentName) title = `${agentName} is working…`;

  head.append(el('span', 'msg-name', title));
  if (act.model) head.append(el('span', 'tag', shortModel(act.model)));

  const dots = el('div', 'typing'); dots.append(el('span'), el('span'), el('span'));

  // Live real-time activity card
  const liveCard = el('div', 'live-activity-card');
  const statusRow = el('div', 'live-status-row');
  const pulse = el('span', 'live-pulse');
  const detail = el('span', 'live-detail', act.detail || 'Processing request through Colony architecture…');
  statusRow.append(pulse, detail);
  liveCard.appendChild(statusRow);

  const work = renderWork(act.steps || [], { live: true });
  col.append(head, dots, liveCard);
  if (work) col.appendChild(work);
  msg.append(avatar(role, true), col);
  $('feedInner').appendChild(msg); scrollDown();
}

// An agent with tools stops and asks before it writes a file or runs a command. Shown under its typing indicator.
const WANTS = { write: 'create a file', edit: 'edit a file', bash: 'run a command', mcp: 'use a connected app' };

function addApproval(a) {
  const card = el('div', 'approval');
  card.append(el('div', 'approval-title', `${a.agent} wants to ${WANTS[a.tool] || 'use ' + a.tool}`), el('pre', 'approval-what', a.message));
  const row = el('div', 'approval-actions'), allow = el('button', 'btn primary', 'Allow'), deny = el('button', 'btn', 'Deny');
  allow.onclick = () => answerApproval(a.id, true);
  deny.onclick = () => answerApproval(a.id, false);
  row.append(allow, deny); card.appendChild(row);
  $('feedInner').appendChild(card); scrollDown();
}

async function answerApproval(id, approve) {
  state.approvals = state.approvals.filter((a) => a.id !== id);   // hide it right away
  renderFeed();
  try { await api(`/approvals/${id}`, { method: 'POST', body: JSON.stringify({ approve }) }); } catch { /* it timed out meanwhile */ }
}

// While a reply is on its way, ask the server for active status and pending approvals.
let approvalTimer = null;
function watchApprovals(on) {
  clearInterval(approvalTimer);
  state.approvals = [];
  state.activity = null;
  if (!on) return;
  approvalTimer = setInterval(async () => {
    try {
      const [appRes, actRes] = await Promise.all([
        api('/approvals').catch(() => ({ approvals: [] })),
        api(`/activity?workspace_id=${encodeURIComponent(state.workspaceId || '')}`).catch(() => ({ active: false })),
      ]);
      const approvals = appRes.approvals || [];
      const ids = (list) => list.map((a) => a.id).join();
      let changed = false;
      if (ids(approvals) !== ids(state.approvals)) {
        state.approvals = approvals;
        changed = true;
      }
      if (JSON.stringify(actRes) !== JSON.stringify(state.activity)) {
        state.activity = actRes;
        changed = true;
      }
      if (changed) renderFeed();
    } catch { /* server busy; try again */ }
  }, 400);
}

export function autosize() { const t = $('prompt'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 200) + 'px'; }

export function send() {
  const box = $('prompt'), text = box.value.trim();
  if (state.busy) return;
  if (pendingUploads()) { toast('Wait for the files to finish adding.'); return; }
  if (!text && !state.attached.length) return;
  box.value = ''; autosize();
  return ask(text, state.target, takeAttached());
}

// Send `text` (and the already-uploaded `files`) to a specific agent (roleId) or let the decider pick (roleId = null).
// The message belongs to the room you're in when you send it, even if you switch rooms while waiting.
async function ask(text, roleId, files = []) {
  if (state.busy) return;
  const channel = currentChannel();
  state.busy = true; $('sendBtn').disabled = true;
  state.pending = { channel, roleId };
  watchApprovals(true);
  state.messages.push({ role: 'user', content: text || 'Please look at the attached file(s).', channel, attachments: files, created_at: new Date().toISOString() });
  renderFeed();
  let reply;
  try {
    const data = await api('/messages', {
      method: 'POST',
      body: JSON.stringify({ message: text, attachments: files.map((f) => f.id), workspace_id: state.workspaceId, role_id: roleId, channel }),
    });
    reply = { role: 'assistant', content: data.reply, created_at: data.created_at, metadata: data };
    refreshContext();
  } catch (err) {
    reply = { role: 'assistant', content: `⚠️ ${err.message}`, metadata: { role_name: 'System', channel } };
  }
  state.pending = null;
  watchApprovals(false);
  state.messages.push(reply);
  renderFeed();
  state.busy = false; $('sendBtn').disabled = false; $('prompt').focus();
}

/* ── "Ask another agent" menu ──────────────────────────── */
export function closeMenu() { document.querySelector('.menu')?.remove(); }

function openAskMenu(anchor, question, currentId, files) {
  closeMenu();
  const menu = el('div', 'menu');
  menu.appendChild(el('div', 'menu-title', 'Ask instead'));
  state.roles.filter((r) => r.id !== currentId).forEach((r) => {
    const b = el('button'); b.append(avatar(r), el('span', null, r.name), el('span', 'sub', shortModel(r.model)));
    b.onclick = () => { closeMenu(); ask(question, r.id, files); };
    menu.appendChild(b);
  });
  if (menu.children.length === 1) menu.appendChild(el('div', 'menu-title', 'Add another agent first'));
  document.body.appendChild(menu);
  const box = anchor.getBoundingClientRect();
  menu.style.left = Math.min(box.left, window.innerWidth - menu.offsetWidth - 12) + 'px';
  const below = box.bottom + 6, fits = below + menu.offsetHeight < window.innerHeight - 8;
  menu.style.top = (fits ? below : box.top - menu.offsetHeight - 6) + 'px';
}
