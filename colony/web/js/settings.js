// Settings (API key, OpenClaw Plugins Manager) and the shared-memory viewer.
import { api } from './api.js';
import { $, closeModal, el, openModal, toast } from './dom.js';
import { currentWorkspace, state } from './state.js';
import { ensureModels } from './model-picker.js';

let cachedPlugins = [];

export async function refreshHealth() {
  const h = await api('/health');
  $('keyDot').style.background = h.has_ollama_key ? 'var(--ok)' : 'var(--warn)';
  $('keyDot').title = h.has_ollama_key ? 'Ollama key set' : 'No Ollama key (fine for a local Ollama)';
  $('dataDir').textContent = h.data_dir;
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
      label.textContent = 'OpenClaw';
      pill.title = `OpenClaw Gateway Connected (${status.url})`;
      if ($('gwStatusOnline')) $('gwStatusOnline').textContent = 'Online';
    } else {
      dot.className = 'openclaw-dot offline';
      label.textContent = 'OpenClaw offline';
      pill.title = `OpenClaw Gateway Offline (${status.url}). Run 'pnpm openclaw gateway' in Terminal.`;
      if ($('gwStatusOnline')) $('gwStatusOnline').textContent = 'Offline';
    }
  } catch {
    dot.className = 'openclaw-dot offline';
    label.textContent = 'OpenClaw offline';
    pill.title = 'OpenClaw Gateway Offline';
    if ($('gwStatusOnline')) $('gwStatusOnline').textContent = 'Offline';
  }
}

function initSettingsTabs() {
  const tabs = [
    { btnId: 'tabBtnPlugins', paneId: 'tabPlugins' },
    { btnId: 'tabBtnProviders', paneId: 'tabProviders' },
    { btnId: 'tabBtnGateway', paneId: 'tabGateway' },
  ];

  tabs.forEach(({ btnId, paneId }) => {
    const btn = $(btnId);
    if (!btn) return;
    btn.onclick = () => {
      tabs.forEach((t) => {
        $(t.btnId)?.classList.remove('active');
        $(t.paneId)?.classList.remove('active');
      });
      btn.classList.add('active');
      $(paneId)?.classList.add('active');
    };
  });
}

export async function loadOpenClawPlugins() {
  const container = $('pluginsCatalogContainer');
  const countBadge = $('pluginsCountBadge');
  if (!container) return;

  try {
    const res = await api('/openclaw/plugins');
    cachedPlugins = res.plugins || [];
    if (countBadge) {
      countBadge.textContent = `${res.total_active} / ${res.total_available} ปลั๊กอินเปิดใช้งานอยู่`;
    }
    renderPluginCategories(res.categories, cachedPlugins, container);
  } catch (err) {
    container.innerHTML = `<div style="color:var(--err);padding:14px">โหลดปลั๊กอินไม่สำเร็จ: ${err.message}</div>`;
  }
}

function renderPluginCategories(categories, plugins, container) {
  container.innerHTML = '';

  (categories || []).forEach((cat) => {
    const catPlugins = plugins.filter((p) => p.category === cat.id);
    if (!catPlugins.length) return;

    const section = el('div', 'plugin-category-section');
    const header = el('div', 'plugin-category-title', cat.title);
    const grid = el('div', 'plugin-cards-grid');

    catPlugins.forEach((plugin) => {
      const card = el('div', 'plugin-card');
      const left = el('div', 'plugin-card-left');
      const icon = el('div', 'plugin-icon', plugin.icon || '🧩');
      const info = el('div', 'plugin-info');

      // Title row with badge
      const titleRow = el('div', 'plugin-title-row');
      const name = el('span', 'plugin-name', plugin.name);
      const badge = el('span', `plugin-badge ${plugin.recommendation}`, plugin.recommendation_label);
      titleRow.append(name, badge);

      const desc = el('div', 'plugin-desc', plugin.description);
      const reason = el('div', 'plugin-reason', `💡 ${plugin.recommendation_reason}`);
      info.append(titleRow, desc, reason);
      left.append(icon, info);

      // Switch
      const switchLabel = el('label', 'switch-label');
      const input = el('input');
      input.type = 'checkbox';
      input.checked = plugin.enabled;
      input.onchange = async () => {
        const nextState = input.checked;
        try {
          await api('/openclaw/plugins', {
            method: 'POST',
            body: JSON.stringify({ plugin_id: plugin.id, enabled: nextState }),
          });
          plugin.enabled = nextState;
          toast(`${plugin.name}: ${nextState ? 'เปิดแล้ว' : 'ปิดแล้ว'}`);
          checkOpenClawGateway();
          const activeCount = cachedPlugins.filter((p) => p.enabled).length;
          $('pluginsCountBadge').textContent = `${activeCount} / ${cachedPlugins.length} ปลั๊กอินเปิดใช้งานอยู่`;
        } catch (err) {
          input.checked = !nextState; // revert
          toast(`เกิดข้อผิดพลาด: ${err.message}`);
        }
      };

      const slider = el('span', 'switch-slider');
      switchLabel.append(input, slider);

      card.append(left, switchLabel);
      grid.appendChild(card);
    });

    section.append(header, grid);
    container.appendChild(section);
  });
}

async function enableAllRecommended() {
  const recIds = cachedPlugins.filter((p) => p.recommendation === 'recommended').map((p) => p.id);
  const payload = {};
  recIds.forEach((id) => { payload[id] = true; });

  try {
    await api('/openclaw/plugins/batch', {
      method: 'POST',
      body: JSON.stringify({ plugins: payload }),
    });
    toast('เปิดใช้งานปลั๊กอินแนะนำทั้งหมดแล้ว ✨');
    await loadOpenClawPlugins();
    checkOpenClawGateway();
  } catch (err) {
    toast(`เกิดข้อผิดพลาด: ${err.message}`);
  }
}

export async function openSettings() {
  const s = await api('/settings');
  $('fOllamaUrl').value = s.ollama_base_url || '';
  $('fOllamaKey').value = '';
  $('fOpenclawUrl').value = s.openclaw_gateway_url || '';
  $('fOpenclawToken').value = '';
  $('ollamaKeyStatus').textContent = s.has_ollama_key ? `Current key: ${s.ollama_key_masked}` : 'No key set.';
  $('openclawTokenStatus').textContent = s.has_openclaw_token ? `Current token: ${s.openclaw_token_masked}` : 'No token set (optional).';
  $('settingsError').textContent = '';

  initSettingsTabs();
  const btnAll = $('btnEnableAllRec');
  if (btnAll) btnAll.onclick = enableAllRecommended;

  openModal('settingsModal');
  loadOpenClawPlugins();
  checkOpenClawGateway();
}

export async function saveSettings() {
  try {
    await api('/settings', {
      method: 'POST',
      body: JSON.stringify({
        ollama_base_url: $('fOllamaUrl').value,
        ollama_api_key: $('fOllamaKey').value,
        openclaw_gateway_url: $('fOpenclawUrl').value,
        openclaw_gateway_token: $('fOpenclawToken').value,
      }),
    });
    closeModal('settingsModal'); toast('Saved'); refreshHealth();
    checkOpenClawGateway();
    state.modelPool = []; ensureModels();   // reload so the Ollama server's models show up in the picker
  } catch (err) { $('settingsError').textContent = err.message; }
}

export async function openMemory() {
  const ws = currentWorkspace();
  $('memoryHint').textContent = `What every agent in ${ws ? ws.name : 'this workspace'} knows about you (MEMORY.md, USER.md and daily notes). Say "remember …" in chat to add to it.`;
  const [ctxRes, dailyRes] = await Promise.all([
    api(`/memory/context?workspace_id=${encodeURIComponent(state.workspaceId)}`),
    api(`/memory/daily?workspace_id=${encodeURIComponent(state.workspaceId)}`).catch(() => ({ notes: [] })),
  ]);

  let display = ctxRes.context || '';
  if (dailyRes.notes && dailyRes.notes.length > 0) {
    display += (display ? '\n\n' : '') + '═══ Recent Episodic Notes (Daily) ═══\n';
    for (const n of dailyRes.notes.slice(0, 3)) {
      display += `\n📅 ${n.date}:\n${n.content.trim()}\n`;
    }
  }

  $('memoryView').textContent = display || 'Nothing yet. Chat a bit, or say "remember that …".';
  openModal('memoryModal');
}
