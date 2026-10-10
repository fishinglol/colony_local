// Left sidebar (workspace name, agents) and the conversation header.
// Note: sidebar <-> feed <-> agent-editor call each other only inside functions,
// so their import cycles are safe (nothing runs at import time except main.js).
import { api } from './api.js';
import { renderNote } from './attachments.js';
import { avatar } from './avatar.js';
import { icon } from './icons.js';
import { renderContext } from './context.js';
import { openAgentModal } from './agent-editor.js';
import { $, describeTools, el, shortModel } from './dom.js';
import { renderFeed } from './feed.js';
import { renderMode } from './mode.js';
import { currentWorkspace, state } from './state.js';

export function renderSidebar() {
  $('wsName').textContent = (currentWorkspace() || {}).name || '';
  $('autoRow').classList.toggle('active', state.target === null);
  const list = $('agentList'); list.innerHTML = '';
  state.roles.forEach((r) => {
    const row = el('button', 'row' + (state.target === r.id ? ' active' : ''));
    const stack = el('span', 'stack');
    stack.append(el('span', 'name', r.name), el('span', 'sub', shortModel(r.model)));
    row.append(avatar(r), stack);
    const edit = el('span', 'edit'); edit.innerHTML = icon('settings', 14); edit.title = 'Agent settings';
    edit.onclick = (e) => { e.stopPropagation(); openAgentModal(r.id); };
    row.append(edit);
    row.onclick = () => selectTarget(r.id);
    list.appendChild(row);
  });
  renderHeader();
}

export function selectTarget(id) {
  state.target = id;
  $('sidebar').classList.remove('show');
  renderSidebar();
  renderFeed();  // switch to that room's messages
  $('prompt').focus();
}

function renderHeader() {
  renderContext(); renderMode(); renderNote();
  const role = state.roles.find((r) => r.id === state.target);
  const av = $('barAvatar'); av.innerHTML = '';
  if (role) {
    av.appendChild(avatar(role, true));
    $('barTitle').textContent = role.name;
    $('barSub').textContent = `${role.model} · answers every message here directly` + (describeTools(role.tools) ? ` · can ${describeTools(role.tools)}` : '');
    $('prompt').placeholder = `Message ${role.name}…`;
    $('composerHint').textContent = `Talking to ${role.name} directly. Other agents still see this chat.`;
    $('editAgentBtn').style.display = '';
  } else {
    $('barTitle').textContent = 'All agents';
    $('barSub').textContent = `${state.roles.map((r) => r.name).join(' · ')}`;
    $('prompt').placeholder = 'Message the team — the right agent answers…';
    $('composerHint').textContent = 'Every agent in this workspace shares one conversation and its memory, so you never repeat yourself.';
    $('editAgentBtn').style.display = 'none';
  }
}
