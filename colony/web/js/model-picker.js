// The "Select model" window: search, models grouped by maker, and a card on hover that says what the model can do.
// Capabilities (tools, images, reasoning, context) come from /api/models.
import { api } from './api.js';
import { $, el } from './dom.js';
import { LABELS } from './reasoning.js';
import { state } from './state.js';

const HINT = 'Hover a model to see what it can do. Not listed? Type its id, like provider/model-name.';
const READS = { text: 'text', image: 'images', file: 'files (PDF)', video: 'video', audio: 'audio' };
let onPick = () => {};
let currentId = '';
let currentTab = 'all';
let rows = [];      // the visible model buttons, in order (for the arrow keys)
let active = -1;

export function modelSource(m) {
  if (m.source) return m.source;
  if (m.id.startsWith('ollama/') || m.provider === 'ollama') return 'ollama';
  return 'ollama';
}

export function modelSourceLabel(m) {
  if (m.source_label) return m.source_label;
  const s = modelSource(m);
  if (s === 'ollama') return 'Ollama Cloud / Local';
  return 'Ollama Cloud / Local';
}

// The list is fetched once (the server's list of Ollama models); until it arrives the picker shows a hint.
export async function ensureModels() {
  if (!state.modelPool.length) {
    const data = await api('/models');
    state.modelPool = data.models; state.modelCatalog = data.catalog;
  }
  return state.modelPool;
}

export const findModel = (id) => state.modelPool.find((m) => m.id === id);

// One row per fact, label on the left and value on the right (like a small spec table).
function capRows(m) {
  const c = m.capabilities || {};
  const known = (v, yes) => (v === true ? yes : v === false ? 'No' : 'Unknown');
  return [
    ['Model', m.label],
    ['Source', modelSourceLabel(m)],
    ['Provider', m.provider_name],
    ['Inputs', c.inputs ? c.inputs.map((x) => READS[x] || x).join(', ') : 'Unknown'],
    ['Tools', known(c.tools, 'Yes: project files and commands')],
    ['Reasoning', c.reasoning_levels ? `${c.reasoning_levels.efforts.map((x) => LABELS[x] || x).join(', ')}${c.reasoning_levels.can_turn_off ? '' : ' (always on)'}` : known(c.reasoning, 'Allows reasoning')],
    ['Context', c.context ? c.context.toLocaleString('en-US') : 'Unknown'],
  ];
}

function capNote(m) {
  const c = m.capabilities || {};
  if (!c.inputs) {
    return "Not in the suggested list. Use “Test this model” to check that Ollama can run it.";
  }
  return c.inputs.some((x) => x !== 'text') ? 'Images you attach are sent to this model as they are; other files are pasted as text when they are text.' : '';
}

function fill(node, m) {
  node.innerHTML = '';
  const grid = el('div', 'cap');
  capRows(m).forEach(([k, v]) => grid.append(el('span', 'cap-k', k), el('span', 'cap-v', v)));
  node.appendChild(grid);
  if (capNote(m)) node.appendChild(el('div', 'cap-note', capNote(m)));
}

// Wide screens: the window shifts left and a card floats beside it (like a tooltip). Narrow screens: the same table
// fills a reserved area under the list, so the list never changes size while you move the mouse over it.
const SIDE_MIN = 990;   // the window (620) + the card (330) + gaps
const layout = () => $('modelPicker').classList.toggle('side', window.innerWidth >= SIDE_MIN);

function showTip(button, m) {
  const tip = $('modelTip'), foot = $('pickerFoot');
  if (!$('modelPicker').classList.contains('side')) { foot.classList.add('info'); fill(foot, m); return; }
  fill(tip, m); tip.classList.add('open');
  placeTip(button);
}

function placeTip(button) {
  const tip = $('modelTip'), picker = document.querySelector('.picker').getBoundingClientRect(), row = button.getBoundingClientRect();
  tip.style.left = (picker.right + 10) + 'px';
  tip.style.top = Math.max(8, Math.min(row.top, window.innerHeight - tip.offsetHeight - 8)) + 'px';
}

function hideTip() {
  $('modelTip').classList.remove('open');
  const foot = $('pickerFoot'); foot.classList.remove('info'); foot.textContent = HINT;
}

function renderTabs() {
  const container = $('pickerTabs');
  if (!container) return;
  container.innerHTML = '';

  const ollamaCount = state.modelPool.filter((m) => modelSource(m) === 'ollama').length;

  const tabs = [
    { id: 'all', label: `All (${state.modelPool.length})` },
    { id: 'ollama', label: `🦙 Ollama (${ollamaCount})` },
  ];

  tabs.forEach((t) => {
    const tabBtn = el('button', 'picker-tab' + (currentTab === t.id ? ' active' : ''), t.label);
    tabBtn.type = 'button';
    tabBtn.onclick = () => {
      currentTab = t.id;
      renderTabs();
      render();
    };
    container.appendChild(tabBtn);
  });
}

function group(title, models) {
  const box = el('div', 'picker-group');
  box.appendChild(el('div', 'picker-group-title', title));
  models.forEach((m) => {
    const b = el('button', 'picker-row' + (m.id === currentId ? ' current' : '')); b.type = 'button'; b.dataset.id = m.id;
    const src = modelSource(m);
    const srcBadge = el('span', `picker-source-badge ${src}`, 'Ollama');
    b.append(srcBadge, el('span', 'picker-name', m.label));
    const tag = m.note || (m.id.endsWith(':free') ? 'Free' : '');
    if (tag) b.appendChild(el('span', 'picker-tag', tag));
    b.onmouseenter = () => highlight(rows.indexOf(b));
    b.onclick = () => choose(m.id);
    rows.push(b); box.appendChild(b);
  });
  return box;
}

function render() {
  const query = $('pickerSearch').value.trim(), q = query.toLowerCase();
  const list = $('pickerList'); list.innerHTML = ''; rows = []; active = -1; hideTip();

  let pool = state.modelPool;
  if (currentTab !== 'all') {
    pool = pool.filter((m) => modelSource(m) === currentTab);
  }

  const shown = pool.filter((m) => !q || `${m.label} ${m.id} ${m.provider_name} ${modelSourceLabel(m)}`.toLowerCase().includes(q));

  const groups = new Map();
  shown.forEach((m) => {
    let title = '';
    title = '🦙 Ollama (Cloud & Local)';
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push(m);
  });

  const orderRank = (t) => {
    if (t.includes('Ollama')) return 1;
    return 10;
  };

  const titles = [...groups.keys()].sort((a, b) => {
    const rA = orderRank(a), rB = orderRank(b);
    if (rA !== rB) return rA - rB;
    return a.localeCompare(b);
  });

  if (query.includes('/') && !state.modelPool.some((m) => m.id === query)) {
    const custom = group('Not in the list', [{ id: query, label: `Use “${query}”`, note: 'Custom model id', provider_name: 'Custom', capabilities: {} }]);
    list.appendChild(custom);
  }

  titles.forEach((t) => list.appendChild(group(t, groups.get(t))));
  if (!rows.length) list.appendChild(el('div', 'picker-empty', state.modelPool.length ? 'No model matches.' : 'Loading models…'));
  $('pickerCount').textContent = state.modelPool.length ? `${shown.length} of ${state.modelPool.length}` : '';
}

// `fromKeys`: scroll the row into view only when it was picked with the arrow keys, never on hover
// (scrolling the list back to the hovered row is what made the list impossible to scroll).
function highlight(i, fromKeys = false) {
  rows.forEach((r) => r.classList.remove('active'));
  active = i;
  if (i < 0 || !rows[i]) { hideTip(); return; }
  rows[i].classList.add('active');
  if (fromKeys) rows[i].scrollIntoView({ block: 'nearest' });
  const m = findModel(rows[i].dataset.id);
  if (m) showTip(rows[i], m); else hideTip();
}

function choose(id) { closeModelPicker(); onPick(id); }

export function closeModelPicker() { $('modelPicker').classList.remove('open'); hideTip(); }

export async function openModelPicker(callback, current) {
  onPick = callback; currentId = current || '';
  $('pickerSearch').value = '';
  currentTab = 'all';
  layout();
  $('modelPicker').classList.add('open');
  renderTabs();
  render(); $('pickerSearch').focus();
  try {
    await ensureModels();
    renderTabs();
    if ($('modelPicker').classList.contains('open')) render();
  } catch {
    $('pickerList').textContent = "Couldn't load the model list.";
  }
}

export function initModelPicker() {
  $('pickerSearch').oninput = render;
  $('modelPicker').addEventListener('click', (e) => { if (e.target === $('modelPicker')) closeModelPicker(); });
  $('pickerList').addEventListener('scroll', () => { if (active >= 0 && $('modelTip').classList.contains('open')) placeTip(rows[active]); });
  window.addEventListener('resize', () => { layout(); hideTip(); });   // the card may no longer fit beside the window
  $('pickerSearch').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); closeModelPicker(); }
    else if (e.key === 'ArrowDown' && rows.length) { e.preventDefault(); highlight((active + 1) % rows.length, true); }
    else if (e.key === 'ArrowUp' && rows.length) { e.preventDefault(); highlight((active - 1 + rows.length) % rows.length, true); }
    else if (e.key === 'Enter') { e.preventDefault(); if (rows[active]) choose(rows[active].dataset.id); else if (rows.length === 1) choose(rows[0].dataset.id); }
  });
}
