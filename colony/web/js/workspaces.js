// Workspaces: the switcher at the top of the sidebar, the create / settings window, and opening a workspace.
// A workspace = its own team of agents, ONE conversation every agent shares, its own memory and project folder.
import { api } from './api.js';
import { refreshContext } from './context.js';
import { $, closeModal, el, openModal, toast } from './dom.js';
import { closeMenu, renderFeed } from './feed.js';
import { ensureModels } from './model-picker.js';
import { renderSidebar } from './sidebar.js';
import { currentWorkspace, state } from './state.js';

const KEY = 'colony.workspace';
const remembered = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
const remember = (id) => { try { localStorage.setItem(KEY, id); } catch { /* storage blocked: fine */ } };

export async function loadWorkspaces() {
  state.workspaces = (await api('/workspaces')).workspaces;
}

// Open a workspace: its team, its conversation, its context gauge. `id` null = the last one used (or the first).
export async function openWorkspace(id) {
  if (state.busy) { toast('Wait for the reply to finish before switching workspace.'); return; }
  const ws = state.workspaces.find((w) => w.id === (id || remembered())) || state.workspaces[0];
  const [roles, messages] = await Promise.all([api(`/roles?workspace_id=${ws.id}`), api(`/workspaces/${ws.id}/messages`)]);
  state.workspaceId = ws.id; remember(ws.id);
  state.roles = roles.roles; state.messages = messages.messages;
  state.target = null; state.approvals = [];
  $('sidebar').classList.remove('show');
  renderSidebar(); renderFeed(); refreshContext();
  ensureModels().then(renderSidebar).catch(() => {});   // the reasoning pills need the model list (capabilities)
}

/* ── the switcher menu ─────────────────────────────────── */
export function openWorkspaceMenu(anchor) {
  const open = document.querySelector('.menu.ws-menu');
  closeMenu();
  if (open) return;   // the button toggles it
  const menu = el('div', 'menu ws-menu');
  menu.appendChild(el('div', 'menu-title', 'Workspaces'));
  state.workspaces.forEach((w) => {
    const b = el('button', w.id === state.workspaceId ? 'current' : '');
    b.append(el('span', null, w.name), el('span', 'sub', `${w.agents.length} agents`));
    b.onclick = () => { closeMenu(); openWorkspace(w.id); };
    menu.appendChild(b);
  });
  const add = el('button', 'menu-action', '＋ New workspace'); add.onclick = () => { closeMenu(); openWorkspaceModal(false); };
  const edit = el('button', 'menu-action', '⚙ Workspace settings'); edit.onclick = () => { closeMenu(); openWorkspaceModal(true); };
  menu.append(add, edit);
  document.body.appendChild(menu);
  const box = anchor.getBoundingClientRect();
  menu.style.left = box.left + 'px'; menu.style.top = (box.bottom + 6) + 'px'; menu.style.minWidth = box.width + 'px';
}

// The composer exposes the current workspace's folder so chat-only workspaces
// can become tool-ready without making the user hunt through the sidebar.
export function openFolderMenu(anchor) {
  if (state.busy) { toast('Wait for the reply to finish before changing the project folder.'); return; }
  const open = document.querySelector('.menu.folder-menu');
  closeMenu();
  if (open) return;
  const ws = currentWorkspace();
  const menu = el('div', 'menu folder-menu');
  const search = document.createElement('input'); search.className = 'menu-search'; search.placeholder = 'Search projects';
  menu.appendChild(search);
  const list = el('div', 'project-list');
  const draw = () => {
    list.innerHTML = '';
    const query = search.value.trim().toLowerCase();
    state.workspaces.filter((w) => w.name.toLowerCase().includes(query)).forEach((w) => {
      const b = el('button', w.id === ws.id ? 'current' : '');
      b.append(el('span', 'project-mark', '▣'), el('span', null, w.name), el('span', 'sub', w.effective_folder ? 'folder' : 'chat'));
      b.onclick = () => { closeMenu(); openWorkspace(w.id); };
      list.appendChild(b);
    });
  };
  draw(); search.oninput = draw; menu.appendChild(list);
  const create = el('button', 'menu-action', '＋ New project');
  create.onclick = () => { closeMenu(); openProjectModal(); };
  menu.appendChild(create);
  const choose = el('button', 'menu-action', '▣ Add folder');
  choose.onclick = () => { closeMenu(); pickFolder(ws); };
  menu.appendChild(choose);
  if (ws.effective_folder) {
    const chatOnly = el('button', 'menu-action', 'Use chat only');
    chatOnly.onclick = async () => {
      closeMenu();
      try {
        await api(`/workspaces/${ws.id}`, { method: 'PATCH', body: JSON.stringify({ folder: '' }) });
        await loadWorkspaces(); renderSidebar();
        toast('This workspace is now chat only');
      } catch (err) { toast(err.message); }
    };
    menu.appendChild(chatOnly);
  }
  document.body.appendChild(menu);
  const box = anchor.getBoundingClientRect();
  menu.style.left = Math.min(box.left, window.innerWidth - menu.offsetWidth - 12) + 'px';
  menu.style.top = (box.top - menu.offsetHeight - 8) + 'px';
}

async function pickFolder(ws) {
  const dialog = window.__TAURI__ && window.__TAURI__.dialog;
  if (!dialog) { openWorkspaceModal(true, true); return; }
  try {
    const folder = await dialog.open({ directory: true, multiple: false, title: 'Choose project folder' });
    if (!folder || Array.isArray(folder)) return;
    await api(`/workspaces/${ws.id}`, { method: 'PATCH', body: JSON.stringify({ folder }) });
    await loadWorkspaces(); renderSidebar();
    toast('Project folder selected');
  } catch (err) { toast(err.message || 'Could not open the folder picker.'); }
}

export function openProjectModal() { openWorkspaceModal(false, false, true); }

/* ── create / settings window ──────────────────────────── */
let editing = false;

function folderStatus(ws) {
  return ws.effective_folder
    ? `Agents with tools work only inside ${ws.effective_folder} (${ws.folder_source}).`
    : 'No folder yet. This workspace can chat, but agents cannot use file or command tools until you choose one.';
}

export function openWorkspaceModal(edit, focusFolder = false, project = false) {
  editing = edit;
  const ws = currentWorkspace();
  $('workspaceModalTitle').textContent = edit ? 'Workspace settings' : project ? 'Create a project' : 'New workspace';
  $('saveWorkspaceBtn').textContent = edit ? 'Save' : project ? 'Create project' : 'Create';
  $('fWsName').value = edit ? ws.name : '';
  $('fWsFolder').value = edit ? (ws.folder || '') : '';
  $('wsFolderStatus').textContent = edit ? folderStatus(ws) : 'Agents with tools can only touch files inside this folder. You can set it later.';
  $('wsCopyField').style.display = edit || project ? 'none' : '';
  $('deleteWorkspaceBtn').style.visibility = edit ? 'visible' : 'hidden';
  const copy = $('fWsCopy'); copy.innerHTML = '';
  const fromDefault = document.createElement('option'); fromDefault.value = ''; fromDefault.textContent = 'The default team (Thinker, Buddy, Writer, Coder)';
  copy.appendChild(fromDefault);
  state.workspaces.forEach((w) => {
    const o = document.createElement('option'); o.value = w.id; o.textContent = `A copy of ${w.name}'s agents`; copy.appendChild(o);
  });
  $('workspaceError').textContent = '';
  openModal('workspaceModal'); (focusFolder ? $('fWsFolder') : $('fWsName')).focus();
}

export async function saveWorkspace() {
  const name = $('fWsName').value.trim(), folder = $('fWsFolder').value.trim();
  if (!name) { $('workspaceError').textContent = 'Give the workspace a name.'; return; }
  try {
    if (editing) {
      await api(`/workspaces/${state.workspaceId}`, { method: 'PATCH', body: JSON.stringify({ name, folder }) });
      await loadWorkspaces(); renderSidebar();
      closeModal('workspaceModal'); toast('Workspace saved');
    } else {
      const made = await api('/workspaces', { method: 'POST', body: JSON.stringify({ name, folder: folder || null, copy_agents_from: $('fWsCopy').value || null }) });
      await loadWorkspaces();
      closeModal('workspaceModal');
      await openWorkspace(made.id); toast(`Workspace "${made.name}" created`);
    }
  } catch (err) { $('workspaceError').textContent = err.message; }
}

export async function deleteWorkspace() {
  const ws = currentWorkspace();
  if (state.busy) { $('workspaceError').textContent = 'Wait for the reply to finish first.'; return; }
  if (state.workspaces.length <= 1) { $('workspaceError').textContent = 'Keep at least one workspace.'; return; }
  if (!confirm(`Delete "${ws.name}" with its conversation and memory? This cannot be undone.`)) return;
  try {
    await api(`/workspaces/${ws.id}`, { method: 'DELETE' });
    await loadWorkspaces();
    closeModal('workspaceModal');
    await openWorkspace(state.workspaces[0].id); toast('Workspace deleted');
  } catch (err) { $('workspaceError').textContent = err.message; }
}
