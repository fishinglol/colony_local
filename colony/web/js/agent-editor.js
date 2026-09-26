// The "Add / Edit agent" modal: presets, model dropdown, save and delete.
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
  { name: 'Research', model: 'perplexity/sonar',
    when: 'Looking things up, current events, fact-finding, comparing sources, market or competitor research.',
    instructions: 'Search the web. Cite your sources with links. Separate facts from your own opinion. End with a short summary.' },
  { name: 'Presentation', model: 'qwen/qwen3.8-27b:free',
    when: 'Making slide decks, presentations, pitches, or talk outlines.',
    instructions: 'Reply as a slide-by-slide outline: slide title, 3–5 short bullets, then speaker notes. Keep each bullet under 12 words.' },
  { name: 'Coder', model: 'z-ai/glm-5.2:free',
    when: 'Writing, debugging or explaining code, technical design, math.',
    instructions: 'Show the code first, then a short explanation. Point out edge cases.' },
  { name: 'Writer', model: 'nvidia/nemotron-3-super-120b-a12b:free',
    when: 'Writing, editing, summarizing, translating, drafting emails or documents.',
    instructions: 'Write clearly and match the tone the user asks for.' },
  { name: 'Chitchat', model: 'nvidia/nemotron-3-ultra-550b-a55b:free',
    when: 'Casual conversation, greetings, opinions, quick factual questions.',
    instructions: 'Be friendly and brief.' },
];
const DEFAULT_MODEL = 'qwen/qwen3.8-27b:free';

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
  $('modelNote').textContent = m ? '' : 'Not in the suggested list: any model on openrouter.ai/models works. Use "Test this model" to check it.';
  showModelIcon();
  renderReasoning();
}

// Level buttons for the chosen model: only what it supports (from OpenRouter's catalog); hidden when it can't reason.
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
let toolsLocked = false;      // the chosen model can't use tools (OpenRouter's catalog says so)
let toolCheck = 0;

function renderToolRows() {
  const box = $('toolRows'); box.innerHTML = '';
  const rows = toolRows(toolDraft);
  if (!rows.length) box.appendChild(el('small', null, 'No tools yet. This agent only chats.'));
  rows.forEach((r) => {
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
  const t = state.tools || {}, notes = [];
  if (toolsLocked) notes.push("This model can't use tools (OpenRouter lists no tool support for it), so only web search is available. Pick another model to connect more.");
  else {
    const folder = (currentWorkspace() || {}).effective_folder;
    notes.push(folder ? `File tools work only inside ${folder}.` : 'File tools and commands need a Project folder (Workspace settings, top of the sidebar). Apps and web search do not.');
    if (t.pi_installed === false) notes.push('The Pi engine is not installed yet (npm install in local/pi-runtime).');
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
  renderToolRows();
  loadServers().then(renderToolRows);      // an agent with "every connector" needs the connector list to show its rows
}

export function openAgentModal(id) {
  state.editingId = id;
  const r = state.roles.find((x) => x.id === id) || { name: '', model: DEFAULT_MODEL, when: '', instructions: '' };
  $('agentModalTitle').textContent = id ? `Edit ${r.name}` : 'Add agent';
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
