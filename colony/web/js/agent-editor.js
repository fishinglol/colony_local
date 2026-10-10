// The agent settings window: profile, personality (SOUL.md), tools, memory; save and delete.
import { api } from './api.js';
import { roleColor } from './avatar.js';
import { ensureModels, findModel } from './model-picker.js';
import { reasoningLevels, reasoningOptions } from './reasoning.js';
import { refreshContext } from './context.js';
import { $, closeModal, el, openModal, toast } from './dom.js';
import { renderFeed } from './feed.js';
import { renderSidebar } from './sidebar.js';
import { disconnect, emptyTools, loadServers, openToolPicker, toolLogo, toolRows, toolsForSave, toolsFromRole } from './tool-picker.js';
import { currentWorkspace, state } from './state.js';

// Starting points for "Add agent". Everything is editable after picking one.
const PRESETS = [
  { name: 'Research', model: 'ollama/gpt-oss:120b',
    when: 'Looking things up, current events, fact-finding, comparing sources, market or competitor research.',
    instructions: 'Search the web. Cite your sources with links. Separate facts from your own opinion. End with a short summary.' },
  { name: 'Presentation', model: 'ollama/nemotron-3-super',
    when: 'Making slide decks, presentations, pitches, or talk outlines.',
    instructions: 'Reply as a slide-by-slide outline: slide title, 3–5 short bullets, then speaker notes. Keep each bullet under 12 words.' },
  { name: 'Coder', model: 'ollama/gpt-oss:120b',
    when: 'Writing, debugging or explaining code, technical design, math.',
    instructions: 'Show the code first, then a short explanation. Point out edge cases.' },
  { name: 'Writer', model: 'ollama/gemma4:31b',
    when: 'Writing, editing, summarizing, translating, drafting emails or documents.',
    instructions: 'Write clearly and match the tone the user asks for.' },
  { name: 'Chitchat', model: 'ollama/nemotron-3-nano:30b',
    when: 'Casual conversation, greetings, opinions, quick factual questions.',
    instructions: 'Be friendly and brief.' },
];
const DEFAULT_MODEL = 'ollama/nemotron-3-super';

// The model is chosen in the picker window (model-picker.js); this keeps the chosen id and the button that shows it.
let pickedModel = DEFAULT_MODEL;
let pickedReasoning = 'default';

export const getModelField = () => pickedModel;

export function setModel(id) {
  pickedModel = id.trim();
  showModel();
  syncToolLock();
}

function showModel() {
  const m = findModel(pickedModel);
  $('modelBtnLabel').textContent = m ? m.label : (pickedModel || 'Pick a model');
  $('modelBtnId').textContent = pickedModel;
  $('modelNote').textContent = m ? '' : 'Not in the suggested list: any Ollama model id works (ollama/<name>). Use "Test this model" to check it.';
  showModelIcon();
  renderReasoning();
}

// Level buttons for the chosen model: only what it supports (from /api/models); hidden when it can't reason.
function renderReasoning() {
  const options = reasoningOptions(pickedModel), levels = reasoningLevels(pickedModel);
  $('reasoningField').style.display = options.length ? '' : 'none';
  if (options.length && !options.some((o) => o.value === pickedReasoning)) pickedReasoning = 'default';   // this model lacks that level
  const seg = $('reasoningSeg'); seg.innerHTML = '';
  options.forEach((o) => {
    const b = el('button', 'seg-btn' + (o.value === pickedReasoning ? ' active' : ''), o.label); b.type = 'button';
    b.onclick = () => { pickedReasoning = o.value; renderReasoning(); };
    seg.appendChild(b);
  });
  $('reasoningNote').textContent = 'Higher = deeper thinking, but slower and more tokens.' + (levels && !levels.can_turn_off ? ' This model always thinks, so it has no Off.' : '');
}

// A small badge for the model's maker (first letter, colour from the provider id) next to the dropdown.
function showModelIcon() {
  const maker = pickedModel.split('/')[0].replace('~', '') || '?';
  const icon = $('modelIcon');
  icon.textContent = maker.slice(0, 1).toUpperCase();
  icon.style.background = roleColor(maker);
}

// The agent's tools are edited in the "Connect a tool" window (tool-picker.js); the editor keeps the draft and lists what is on.
let toolDraft = emptyTools();
let toolsLocked = false;      // the chosen model can't use tools (the model list says so)
let toolCheck = 0;

function syncCapabilityCheckboxes() {
  const cbWeb = $('capWebSearch');
  const cbRead = $('capReadFile');
  const cbWrite = $('capWriteFile');
  const cbBash = $('capBashExec');

  if (cbWeb) {
    cbWeb.checked = !!toolDraft.web_search;
    $('capCardWeb')?.classList.toggle('selected', cbWeb.checked);
  }
  if (cbRead) {
    cbRead.checked = toolDraft.read !== 'off';
    $('capCardRead')?.classList.toggle('selected', cbRead.checked);
  }
  if (cbWrite) {
    cbWrite.checked = toolDraft.write !== 'off';
    $('capCardWrite')?.classList.toggle('selected', cbWrite.checked);
  }
  if (cbBash) {
    cbBash.checked = toolDraft.bash !== 'off';
    $('capCardBash')?.classList.toggle('selected', cbBash.checked);
  }
}

function bindCapabilityEvents() {
  const cbWeb = $('capWebSearch');
  const cbRead = $('capReadFile');
  const cbWrite = $('capWriteFile');
  const cbBash = $('capBashExec');
  const btnPreset = $('applyRolePresetBtn');

  if (cbWeb && !cbWeb._bound) {
    cbWeb._bound = true;
    cbWeb.onchange = () => {
      toolDraft.web_search = cbWeb.checked;
      renderToolRows();
    };
  }
  if (cbRead && !cbRead._bound) {
    cbRead._bound = true;
    cbRead.onchange = () => {
      toolDraft.read = cbRead.checked ? 'allow' : 'off';
      renderToolRows();
    };
  }
  if (cbWrite && !cbWrite._bound) {
    cbWrite._bound = true;
    cbWrite.onchange = () => {
      toolDraft.write = cbWrite.checked ? 'allow' : 'off';
      renderToolRows();
    };
  }
  if (cbBash && !cbBash._bound) {
    cbBash._bound = true;
    cbBash.onchange = () => {
      toolDraft.bash = cbBash.checked ? 'allow' : 'off';
      renderToolRows();
    };
  }
  if (btnPreset && !btnPreset._bound) {
    btnPreset._bound = true;
    btnPreset.onclick = applyCurrentRolePreset;
  }
}

function applyCurrentRolePreset() {
  const name = ($('fName').value || '').trim().toLowerCase();
  const id = state.editingId || '';

  if (name.includes('coder') || name.includes('dev') || name.includes('program') || id === 'coding') {
    toolDraft.web_search = true;
    toolDraft.read = 'allow';
    toolDraft.write = 'allow';
    toolDraft.bash = 'allow';
    toast('Coder: เปิดครบชุด (Bash, เขียนไฟล์, อ่านไฟล์, ค้นหาเว็บ) 💻');
  } else if (name.includes('writer') || name.includes('เขียน') || id === 'writing') {
    toolDraft.web_search = true;
    toolDraft.read = 'allow';
    toolDraft.write = 'allow';
    toolDraft.bash = 'off';
    toast('Writer: เปิดเขียนและอ่านไฟล์ + ค้นหาเว็บ (ปิด Bash เพื่อความปลอดภัย) ✍️');
  } else if (name.includes('buddy') || name.includes('chat') || id === 'chitchat') {
    toolDraft.web_search = true;
    toolDraft.read = 'off';
    toolDraft.write = 'off';
    toolDraft.bash = 'off';
    toast('Buddy: เปิดค้นหาเว็บสด (ปิดการเข้าถึงไฟล์ในเครื่อง) 💬');
  } else {
    // Thinker / Default
    toolDraft.web_search = true;
    toolDraft.read = 'allow';
    toolDraft.write = 'off';
    toolDraft.bash = 'off';
    toast('Thinker: เปิดค้นหาเว็บ + อ่านไฟล์เพื่อวิเคราะห์ (ปิดการแก้ไฟล์และรันคำสั่ง) 🧠');
  }

  renderToolRows();
}

function renderToolRows() {
  syncCapabilityCheckboxes();
  const box = $('toolRows'); box.innerHTML = '';
  const rows = toolRows(toolDraft);
  if (!rows.length) box.appendChild(el('small', null, 'ไม่มี Connector ภายนอกเชื่อมต่อเพิ่มเติม'));
  rows.forEach((r) => {
    // Only show custom mcp or connectors in the sub-list
    if (['read', 'write', 'bash', 'web'].includes(r.id)) return;
    const row = el('div', 'tool-row'), logo = toolLogo(r), main = el('div', 'tr-main');
    main.append(el('div', 'tr-name', r.name), el('div', 'tr-scope', r.scope));
    const x = el('button', 'tr-x', '×'); x.type = 'button'; x.title = 'Disconnect';
    x.onclick = (e) => { e.stopPropagation(); toolDraft = disconnect(toolDraft, r.id); renderToolRows(); };
    row.append(logo, main, x);
    row.onclick = () => openTools(r.id);
    box.appendChild(row);
  });
}

export function openTools(select) {
  openToolPicker({
    draft: toolDraft, select, locked: toolsLocked, agentName: $('fName').value.trim(),
    folder: (currentWorkspace() || {}).effective_folder,
    onChange: (d) => { toolDraft = d; renderToolRows(); },
  });
}

async function syncToolLock() {
  const model = getModelField(), ticket = ++toolCheck;
  let supported = null;
  if (model.includes('/')) {
    try { supported = (await api(`/models/tools?model=${encodeURIComponent(model)}`)).supported; } catch { /* unknown: don't lock */ }
  }
  if (ticket !== toolCheck) return;   // another model was picked while we asked
  toolsLocked = supported === false;
  if (toolsLocked) toolDraft = { ...emptyTools(), web_search: toolDraft.web_search };
  renderToolRows();
  const notes = [];
  if (toolsLocked) notes.push("This model can't use tools (Ollama lists no tool support for it), so only web search is available. Pick another model to connect more.");
  else {
    const folder = (currentWorkspace() || {}).effective_folder;
    notes.push(folder ? `File tools work only inside ${folder}.` : 'File tools and commands need a Project folder (Workspace settings, top of the sidebar). Apps and web search do not.');
  }
  $('toolsNote').textContent = notes.join(' ');
}

export async function testModel() {
  const model = getModelField(), out = $('modelTestResult'), btn = $('testModelBtn');
  if (!model) { out.className = 'bad'; out.textContent = 'Pick a model first.'; return; }
  btn.disabled = true; out.className = ''; out.textContent = 'Testing…';
  try {
    const r = await api('/models/test', { method: 'POST', body: JSON.stringify({ model, reasoning: reasoningOptions(model).some((o) => o.value === pickedReasoning) ? pickedReasoning : 'default' }) });
    out.className = r.ok ? 'ok' : 'bad';
    out.textContent = r.ok ? `✓ Works (${r.seconds}s)` : r.message;
  } catch (err) { out.className = 'bad'; out.textContent = err.message; }
  finally { btn.disabled = false; }
}

function fillAgentForm(r) {
  toolDraft = toolsFromRole(r);            // before the model is set: that check may take tools away
  $('fName').value = r.name; pickedReasoning = r.reasoning || 'default'; setModel(r.model); $('fWhen').value = r.when; $('fInstructions').value = r.instructions;
  bindCapabilityEvents();
  renderToolRows();
  loadServers().then(renderToolRows);      // an agent with "every connector" needs the connector list to show its rows
}

// Tabs of the agent settings window.
export function showAgentTab(name) {
  document.querySelectorAll('#agentTabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('#agentModal .tab-pane').forEach((p) => p.classList.toggle('active', p.dataset.pane === name));
}

function filePreview(title, text, hint) {
  const box = el('details', 'file');
  const sum = el('summary'); sum.append(el('span', 'file-title', title), el('span', 'file-hint', hint || ''));
  box.append(sum, el('pre', 'file-text', text || 'Empty yet.'));
  return box;
}

// What OpenClaw actually has for this agent: its soul/identity/rules, and the memory it shares with the team.
async function loadAgentFiles(id) {
  const soul = $('soulFiles'), mem = $('memoryPane');
  soul.innerHTML = mem.innerHTML = '';
  if (!id) {
    soul.appendChild(el('p', 'hint', 'The files appear after this agent is saved and has answered once.'));
    mem.appendChild(el('p', 'hint', 'Memory appears after this agent is saved.'));
    return;
  }
  let f;
  try { f = await api(`/roles/${encodeURIComponent(id)}/files?workspace_id=${encodeURIComponent(state.workspaceId)}`); }
  catch (err) { soul.appendChild(el('p', 'hint', `Could not load the files (${err.message}).`)); return; }
  if (!f.started) soul.appendChild(el('p', 'hint', 'This is a preview: the files are written when the agent answers for the first time.'));
  soul.append(filePreview('SOUL.md', f.soul, 'who it is'), filePreview('IDENTITY.md', f.identity, 'its name'), filePreview('AGENTS.md', f.rules, 'how memory works'));
  mem.append(
    el('p', 'hint', 'The whole team shares USER.md, MEMORY.md and the daily notes. Notes OpenClaw promotes while dreaming stay with this agent.'),
    filePreview('USER.md', f.user, 'what the team knows about you'),
    filePreview('MEMORY.md', f.memory, 'lasting facts, shared'),
    filePreview('Daily notes', f.daily.map((d) => `# ${d.date}\n${d.content}`).join('\n\n'), 'shared, newest first'),
    filePreview('This agent’s own MEMORY.md', f.private_memory, 'promoted by dreaming'),
    filePreview('DREAMS.md', f.dreams, 'what dreaming consolidated'),
  );
}

export function openAgentModal(id) {
  state.editingId = id;
  showAgentTab('profile');
  loadAgentFiles(id);
  const r = state.roles.find((x) => x.id === id) || { name: '', model: DEFAULT_MODEL, when: '', instructions: '' };
  $('agentModalTitle').textContent = id ? r.name : 'New agent';
  bindCapabilityEvents();

  const presets = $('presets'); presets.innerHTML = '';
  if (!id) {
    presets.appendChild(el('span', 'label', 'Start from'));
    PRESETS.forEach((p) => {
      const b = el('button', 'chip-btn', p.name); b.onclick = () => fillAgentForm(p); presets.appendChild(b);
    });
  }
  presets.style.display = id ? 'none' : '';
  fillAgentForm(r);
  $('deleteAgentBtn').style.visibility = id ? 'visible' : 'hidden';
  $('agentError').textContent = '';
  $('modelTestResult').textContent = '';
  openModal('agentModal'); $('fName').focus();
  ensureModels().then(showModel).catch(() => {});   // the model list arrives a moment later; then show its proper name
}

function slug(name) {
  let s = '';
  for (const c of name.toLowerCase()) s += (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ? c : '-';
  return (s.split('-').filter(Boolean).join('-') || 'agent').slice(0, 30);
}

async function saveRoles(next, errorBox) {
  try {
    state.roles = (await api(`/roles?workspace_id=${encodeURIComponent(state.workspaceId)}`, { method: 'PUT', body: JSON.stringify({ roles: next }) })).roles;
    if (state.target && !state.roles.some((r) => r.id === state.target)) state.target = null;
    renderSidebar();
    refreshContext();
    renderFeed();
    return true;
  } catch (err) { $(errorBox).textContent = err.message; return false; }
}

export async function saveAgent() {
  const draft = {
    name: $('fName').value.trim(), model: getModelField(),
    reasoning: reasoningOptions(pickedModel).length || !state.modelPool.length ? pickedReasoning : 'default',
    when: $('fWhen').value.trim(), instructions: $('fInstructions').value.trim(),
    ...toolsForSave(toolDraft),
  };
  if (!draft.name || !draft.model || !draft.when) { $('agentError').textContent = 'Name, model and "when" are required.'; return; }
  let next;
  if (state.editingId) next = state.roles.map((r) => r.id === state.editingId ? { ...r, ...draft } : r);
  else {
    let id = slug(draft.name), n = 2;
    while (state.roles.some((r) => r.id === id)) id = `${slug(draft.name)}-${n++}`;
    next = [...state.roles, { id, ...draft }];
  }
  if (await saveRoles(next, 'agentError')) { closeModal('agentModal'); toast('Agent saved'); }
}

export async function deleteAgent() {
  if (state.roles.length <= 1) { $('agentError').textContent = 'Keep at least one agent.'; return; }
  if (!confirm('Delete this agent?')) return;
  if (await saveRoles(state.roles.filter((r) => r.id !== state.editingId), 'agentError')) { closeModal('agentModal'); toast('Agent deleted'); }
}
