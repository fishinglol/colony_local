// Settings (API key) and the shared-memory viewer.
import { api } from './api.js';
import { $, closeModal, openModal, toast } from './dom.js';
import { currentWorkspace, state } from './state.js';

export async function refreshHealth() {
  const h = await api('/health');
  $('keyDot').style.background = h.has_openrouter_key ? 'var(--ok)' : 'var(--warn)';
  $('keyDot').title = h.has_openrouter_key ? 'API key set' : 'No API key yet';
  $('dataDir').textContent = h.data_dir;
  state.tools = h.tools || {};
  return h;
}

export async function openSettings() {
  const s = await api('/settings');
  $('fKey').value = '';
  $('keyStatus').textContent = s.has_openrouter_key ? `Current key: ${s.openrouter_key_masked}` : 'No key set yet.';
  $('settingsError').textContent = '';
  openModal('settingsModal');
}

export async function saveSettings() {
  try {
    await api('/settings', { method: 'POST', body: JSON.stringify({ openrouter_api_key: $('fKey').value }) });
    closeModal('settingsModal'); toast('Saved'); refreshHealth();
  } catch (err) { $('settingsError').textContent = err.message; }
}

export async function openMemory() {
  const ws = currentWorkspace();
  $('memoryHint').textContent = `What every agent in ${ws ? ws.name : 'this workspace'} knows about you, whichever model answers. Say "remember …" in chat to add to it. Memory is separate for each workspace.`;
  const { context } = await api(`/memory/context?workspace_id=${encodeURIComponent(state.workspaceId)}`);
  $('memoryView').textContent = context || 'Nothing yet. Chat a bit, or say "remember that …".';
  openModal('memoryModal');
}
