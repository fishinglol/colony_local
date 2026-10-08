// Settings (API key) and the shared-memory viewer.
import { api } from './api.js';
import { $, closeModal, openModal, toast } from './dom.js';
import { currentWorkspace, state } from './state.js';
import { ensureModels } from './model-picker.js';

export async function refreshHealth() {
  const h = await api('/health');
  $('keyDot').style.background = h.has_openrouter_key ? 'var(--ok)' : 'var(--warn)';
  $('keyDot').title = h.has_openrouter_key ? 'API key set' : 'No API key yet';
  $('dataDir').textContent = h.data_dir;
  state.tools = h.tools || {};
  return h;
}

export async function checkOpenClawGateway() {
  const pill = $('openclawPill');
  const dot = $('openclawDot');
  const label = $('openclawLabel');
  if (!pill || !dot || !label) return;

  try {
    const status = await api('/openclaw/status');
    if (status.available) {
      dot.className = 'openclaw-dot online';
      label.textContent = 'OpenClaw Gateway 🟢';
      pill.title = `OpenClaw Gateway Connected (${status.url})`;
    } else {
      dot.className = 'openclaw-dot offline';
      label.textContent = 'OpenClaw Gateway 🔴';
      pill.title = `OpenClaw Gateway Offline (${status.url}). Run 'pnpm openclaw gateway' in Terminal.`;
    }
  } catch {
    dot.className = 'openclaw-dot offline';
    label.textContent = 'OpenClaw Gateway 🔴';
    pill.title = 'OpenClaw Gateway Offline';
  }
}

export async function openSettings() {
  const s = await api('/settings');
  $('fKey').value = '';
  $('fKaggle').value = s.kaggle_base_url;
  $('fOllamaUrl').value = s.ollama_base_url || '';
  $('fOllamaKey').value = '';
  $('fOpenclawUrl').value = s.openclaw_gateway_url || '';
  $('fOpenclawToken').value = '';
  $('keyStatus').textContent = s.has_openrouter_key ? `Current key: ${s.openrouter_key_masked}` : 'No key set yet.';
  $('ollamaKeyStatus').textContent = s.has_ollama_key ? `Current key: ${s.ollama_key_masked}` : 'No key set.';
  $('openclawTokenStatus').textContent = s.has_openclaw_token ? `Current token: ${s.openclaw_token_masked}` : 'No token set (optional).';
  $('settingsError').textContent = '';
  openModal('settingsModal');
}

export async function saveSettings() {
  try {
    await api('/settings', {
      method: 'POST',
      body: JSON.stringify({
        openrouter_api_key: $('fKey').value,
        kaggle_base_url: $('fKaggle').value,
        ollama_base_url: $('fOllamaUrl').value,
        ollama_api_key: $('fOllamaKey').value,
        openclaw_gateway_url: $('fOpenclawUrl').value,
        openclaw_gateway_token: $('fOpenclawToken').value,
      }),
    });
    closeModal('settingsModal'); toast('Saved'); refreshHealth();
    checkOpenClawGateway();
    state.modelPool = []; ensureModels();   // reload so the Kaggle/Ollama server's models show up in the picker
  } catch (err) { $('settingsError').textContent = err.message; }
}

export async function openMemory() {
  const ws = currentWorkspace();
  $('memoryHint').textContent = `What every agent in ${ws ? ws.name : 'this workspace'} knows about you (Curated MEMORY.md, Episodic Daily Notes & Dreaming). Say "remember …" in chat to add to it.`;
  const [ctxRes, dailyRes, dreamsRes] = await Promise.all([
    api(`/memory/context?workspace_id=${encodeURIComponent(state.workspaceId)}`),
    api(`/memory/daily?workspace_id=${encodeURIComponent(state.workspaceId)}`).catch(() => ({ notes: [] })),
    api(`/memory/dreams?workspace_id=${encodeURIComponent(state.workspaceId)}`).catch(() => ({ dreams: '' })),
  ]);

  let display = ctxRes.context || '';
  if (dailyRes.notes && dailyRes.notes.length > 0) {
    display += (display ? '\n\n' : '') + '═══ Recent Episodic Notes (Daily) ═══\n';
    for (const n of dailyRes.notes.slice(0, 3)) {
      display += `\n📅 ${n.date}:\n${n.content.trim()}\n`;
    }
  }
  if (dreamsRes.dreams && dreamsRes.dreams.trim()) {
    display += (display ? '\n\n' : '') + '═══ Dreaming Consolidation Log (DREAMS.md) ═══\n' + dreamsRes.dreams.trim();
  }

  $('memoryView').textContent = display || 'Nothing yet. Chat a bit, or say "remember that …".';
  openModal('memoryModal');
}
