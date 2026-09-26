// Files in the chat box: the + menu, drag and drop, paste, the chips above the text, and a heads-up when an
// agent can't read what is attached (the server enforces the same rule; this just tells you before you send).
import { api } from './api.js';
import { $, el, toast } from './dom.js';
import { closeMenu } from './feed.js';
import { findModel } from './model-picker.js';
import { currentWorkspace, state } from './state.js';
import { openWorkspaceModal } from './workspaces.js';

const MAX_FILES = 10, MAX_MB = 20;
const NEEDS = { image: 'image', pdf: 'file', video: 'video', audio: 'audio' };   // what OpenRouter lists a model as accepting
const LABEL = { image: 'images', pdf: 'PDFs', video: 'video', audio: 'audio' };
const TAG = { image: 'IMG', pdf: 'PDF', video: 'VID', audio: 'AUD', text: 'TXT', file: 'FILE' };

const guessKind = (f) => (f.type.startsWith('image/') ? 'image' : f.type.startsWith('video/') ? 'video' : f.type.startsWith('audio/') ? 'audio'
  : f.type === 'application/pdf' ? 'pdf' : f.type.startsWith('text/') ? 'text' : 'file');
const size = (n) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);
const labels = (kinds) => kinds.map((k) => LABEL[k]).join(' and ');

export const fileUrl = (ref) => `/api/workspaces/${encodeURIComponent(state.workspaceId)}/attachments/${ref.id}`;
export const tagOf = (kind) => TAG[kind] || 'FILE';

// Which of these kinds of file can this agent's model not read? (An agent with tools reads images and text only.)
export function unreadableBy(role, kinds) {
  const t = role.tools || {};
  const hasFolder = Boolean((currentWorkspace() || {}).effective_folder);   // without a project folder, tools stay off
  const withTools = hasFolder && (t.read === 'allow' || (t.write && t.write !== 'off') || (t.bash && t.bash !== 'off'));
  const inputs = ((findModel(role.model) || {}).capabilities || {}).inputs;
  return kinds.filter((k) => NEEDS[k] && ((withTools && k !== 'image') || (inputs && !inputs.includes(NEEDS[k]))));
}

export const pendingUploads = () => state.attached.some((a) => a.status === 'uploading');

// The files ready to send (their ids), leaving the chat box empty.
export function takeAttached() {
  const ready = state.attached.filter((a) => a.status === 'ready');
  state.attached.forEach((a) => a.preview && URL.revokeObjectURL(a.preview));
  state.attached = [];
  renderAttachments();
  return ready.map(({ id, name, kind, size: bytes }) => ({ id, name, kind, size: bytes }));
}

function drop(key) {
  const gone = state.attached.find((a) => a.key === key);
  if (gone && gone.preview) URL.revokeObjectURL(gone.preview);
  state.attached = state.attached.filter((a) => a.key !== key);
  renderAttachments();
}

export function renderAttachments() {
  const row = $('attachRow'); row.innerHTML = '';
  row.classList.toggle('has', state.attached.length > 0);
  state.attached.forEach((a) => {
    const chip = el('div', 'attach' + (a.status === 'uploading' ? ' busy' : ''));
    if (a.preview) { const img = el('img'); img.src = a.preview; img.alt = a.name; chip.appendChild(img); }
    else chip.appendChild(el('div', 'ico', TAG[a.kind] || 'FILE'));
    const meta = el('div', 'meta');
    meta.append(el('div', 'fname', a.name), el('div', 'fsub', a.status === 'uploading' ? 'Adding…' : size(a.size)));
    const x = el('button', 'x', '×'); x.title = 'Remove'; x.onclick = () => drop(a.key);
    chip.append(meta, x); row.appendChild(chip);
  });
  renderNote();
}

// "Coder can't read images — Jev will only choose from the others", or a plain warning when nobody can.
export function renderNote() {
  const note = $('attachNote');
  const kinds = [...new Set(state.attached.map((a) => a.kind).filter((k) => NEEDS[k]))];
  note.className = 'attach-note';
  if (!kinds.length) { note.textContent = ''; return; }
  const blockedFor = (r) => unreadableBy(r, kinds);
  const role = state.roles.find((r) => r.id === state.target);
  const others = state.roles.filter((r) => r !== role && !blockedFor(r).length).map((r) => r.name);
  let text = '', level = 'warn';
  if (role && blockedFor(role).length) {
    text = `${role.name} can't read ${labels(blockedFor(role))}. ` + (others.length ? `Ask ${others.join(', ')} instead, or change its model.` : "Change this agent's model to one that accepts it.");
    level = others.length ? 'warn' : 'bad';
  } else if (!role) {
    const cannot = state.roles.filter((r) => blockedFor(r).length);
    if (cannot.length === state.roles.length) { text = `No agent in this workspace can read ${labels(kinds)}. Change an agent's model first — the model picker's Inputs row shows what each model reads.`; level = 'bad'; }
    else if (cannot.length) text = `${cannot.map((r) => r.name).join(', ')} can't read ${labels(kinds)}, so Jev will only choose among the others.`;
  }
  note.textContent = text;
  if (text) note.classList.add('show', level);
}

async function upload(item, file) {
  try {
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
      reader.onerror = () => reject(new Error(`Couldn't read ${file.name}.`));
      reader.readAsDataURL(file);
    });
    const ref = await api(`/workspaces/${encodeURIComponent(state.workspaceId)}/attachments`, { method: 'POST', body: JSON.stringify({ name: file.name, data }) });
    Object.assign(item, { id: ref.id, kind: ref.kind, size: ref.size, status: 'ready' });
    renderAttachments();
  } catch (err) { toast(err.message); drop(item.key); }
}

export function addFiles(files) {
  for (const file of files) {
    if (state.attached.length >= MAX_FILES) { toast(`At most ${MAX_FILES} files per message.`); break; }
    if (file.size > MAX_MB * 1024 * 1024) { toast(`${file.name} is bigger than ${MAX_MB} MB.`); continue; }
    const item = { key: `${Date.now()}-${Math.random()}`, name: file.name, size: file.size, kind: guessKind(file), status: 'uploading',
                   preview: file.type.startsWith('image/') ? URL.createObjectURL(file) : null };
    state.attached.push(item);
    upload(item, file);
  }
  renderAttachments();
}

function openAddMenu(anchor) {
  const open = document.querySelector('.menu.add-menu');
  closeMenu();
  if (open) return;
  const menu = el('div', 'menu add-menu');
  const files = el('button'); files.append(el('span', null, 'Add files or photos'), el('span', 'kbd', '⌘ U'));
  files.onclick = () => { closeMenu(); $('fileInput').click(); };
  const folder = el('button'); folder.append(el('span', null, 'Add folder'));
  folder.title = "Sets this workspace's project folder, where agents with tools read and write files.";
  folder.onclick = () => { closeMenu(); openWorkspaceModal(true); $('fWsFolder').focus(); };
  menu.append(files, folder);
  document.body.appendChild(menu);
  const box = anchor.getBoundingClientRect();
  menu.style.left = box.left + 'px'; menu.style.top = (box.top - menu.offsetHeight - 8) + 'px';
}

export function initAttachments() {
  $('addBtn').onclick = (e) => openAddMenu(e.currentTarget);
  $('fileInput').onchange = (e) => { addFiles([...e.target.files]); e.target.value = ''; };
  document.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'u') { e.preventDefault(); $('fileInput').click(); } });
  $('prompt').addEventListener('paste', (e) => {
    const files = [...(e.clipboardData ? e.clipboardData.files : [])];
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  // Drag files anywhere over the window to attach them.
  let depth = 0;
  const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes('Files');
  const show = (on) => { $('dropZone').classList.toggle('show', on); $('composer').classList.toggle('dragging', on); };
  document.addEventListener('dragenter', (e) => { if (hasFiles(e)) { e.preventDefault(); depth += 1; show(true); } });
  document.addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener('dragleave', (e) => { if (hasFiles(e)) { depth = Math.max(0, depth - 1); if (!depth) show(false); } });
  document.addEventListener('drop', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault(); depth = 0; show(false);
    if (document.querySelector('.overlay.open')) return;
    const items = [...e.dataTransfer.items].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null));
    if (items.some((entry) => entry && entry.isDirectory)) toast("Folders can't be dropped into the chat. Use + → Add folder to set the project folder.");
    addFiles([...e.dataTransfer.files].filter((f, i) => !(items[i] && items[i].isDirectory)));
  });
}
