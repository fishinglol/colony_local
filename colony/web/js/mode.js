// The mode pill in the chat box: how freely agents that have tools may change things in this workspace.
// The server applies it on top of each agent's own permissions (core/agents.py apply_mode).
import { api } from './api.js';
import { $, el, toast } from './dom.js';
import { closeMenu } from './feed.js';
import { currentWorkspace, state } from './state.js';

export const MODES = [
  { id: 'auto', name: 'Auto', desc: "Each agent uses its own permissions" },
  { id: 'manual', name: 'Manual', desc: 'Always ask before making changes' },
  { id: 'accept_edits', name: 'Accept edits', desc: 'Edit files without asking; still ask before commands' },
  { id: 'plan', name: 'Plan', desc: 'Read only: agents make a plan and change nothing' },
  { id: 'bypass', name: 'Bypass permissions', desc: 'Everything an agent may do goes through, no questions', danger: true },
];

const modeOf = () => MODES.find((m) => m.id === (currentWorkspace() || {}).mode) || MODES[0];

export function renderMode() {
  const mode = modeOf();
  const ws = currentWorkspace(), folder = ws && ws.effective_folder;
  const folderBtn = $('folderBtn');
  const name = folder ? folder.split('/').filter(Boolean).pop() : 'Choose folder';
  $('folderName').textContent = name;
  folderBtn.className = 'folder-btn ' + (folder ? 'ready' : 'missing');
  folderBtn.title = folder ? `${folder}\nChange project folder` : 'Choose a project folder to enable tools in this workspace';
  $('modeName').textContent = folder ? mode.name : 'Chat only';
  $('modeBtn').className = 'mode-btn' + (!folder ? ' chat-only' : mode.id === 'plan' ? ' plan' : mode.id === 'bypass' ? ' bypass' : '');
  $('modeBtn').disabled = !folder;
  $('modeBtn').title = folder ? 'How freely agents with tools may change things' : 'Choose a project folder to enable tools';
}

async function setMode(id) {
  const ws = currentWorkspace();
  if (!ws || ws.mode === id) return;
  if (id === 'bypass' && !confirm('Bypass permissions lets agents with tools change files and run commands without asking you. Only use it in a project you trust. Turn it on?')) return;
  try {
    ws.mode = (await api(`/workspaces/${ws.id}`, { method: 'PATCH', body: JSON.stringify({ mode: id }) })).mode;
    renderMode();
    toast(`Mode: ${modeOf().name}`);
  } catch (err) { toast(err.message); }
}

export function openModeMenu(anchor) {
  const open = document.querySelector('.menu.mode-menu');
  closeMenu();
  if (open) return;   // the pill toggles it
  const menu = el('div', 'menu mode-menu');
  menu.appendChild(el('div', 'menu-title', 'Mode'));
  MODES.forEach((m, i) => {
    const b = el('button', (m.id === modeOf().id ? 'current ' : '') + (m.danger ? 'danger' : ''));
    b.append(el('span', 'name', m.name), el('span', 'desc', m.desc), el('span', 'key', m.id === modeOf().id ? `✓  ${i + 1}` : String(i + 1)));
    b.onclick = () => { closeMenu(); setMode(m.id); };
    menu.appendChild(b);
  });
  menu.appendChild(el('div', 'menu-note', 'Applies to agents that have tools. Agents without tools just chat.'));
  document.body.appendChild(menu);
  const box = anchor.getBoundingClientRect();
  menu.style.left = box.left + 'px'; menu.style.top = (box.top - menu.offsetHeight - 8) + 'px';
}

export function initMode() {
  $('modeBtn').onclick = (e) => openModeMenu(e.currentTarget);
  document.addEventListener('keydown', (e) => {   // 1–5 pick a mode while the menu is open
    const mode = document.querySelector('.menu.mode-menu') && MODES[Number(e.key) - 1];
    if (mode) { e.preventDefault(); closeMenu(); setMode(mode.id); }
  });
}
