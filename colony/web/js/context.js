// The context gauge: how full each agent's context window is for the open workspace.
// The numbers come from the server (/api/context): the prompt size OpenClaw reported for each agent's last turn.
import { api } from './api.js';
import { avatar } from './avatar.js';
import { $, el, shortModel } from './dom.js';
import { state } from './state.js';

let agents = [];
let loadError = null;  // set when /api/context can't be read, so the gauge says why instead of showing nothing

function tokens(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k`;
  return String(n);
}
const percentText = (p) => (p < 1 ? '<1%' : `${Math.round(p)}%`);
const level = (p) => (p == null ? '' : p >= 85 ? 'bad' : p >= 60 ? 'warn' : 'ok');

export async function refreshContext() {
  const query = state.workspaceId ? `?workspace_id=${encodeURIComponent(state.workspaceId)}` : '';
  try { agents = (await api('/context' + query)).agents; loadError = null; }
  catch (err) { agents = []; loadError = err.message || 'request failed'; }
  renderContext();
}

export function renderContext() {
  const btn = $('ctxBtn');
  const mine = state.target ? agents.find((a) => a.role_id === state.target) : null;
  // In the mix chat any agent may answer, so show the fullest one.
  const fullest = agents.filter((a) => a.percent != null).sort((a, b) => b.percent - a.percent)[0];
  const shown = mine || fullest;
  btn.className = 'chip-btn ' + level(shown?.percent);
  btn.title = loadError ? 'Could not load context usage' : "How full each agent's context window is";
  if (loadError) { btn.textContent = 'Context ⚠'; }
  else if (!shown) { btn.textContent = 'Context'; }
  else if (shown.percent == null) { btn.textContent = 'Context'; }
  else { btn.textContent = `Context ${mine ? '' : shown.name + ' '}${percentText(shown.percent)}`; }

  const pop = $('ctxPop'); pop.innerHTML = '';
  pop.appendChild(el('div', 'ctx-title', 'Context used per agent'));
  if (loadError) {
    pop.appendChild(el('div', 'ctx-detail', `Couldn't load context usage (${loadError}). The server may be running an older version — stop it (Ctrl+C) and start \`colony\` again, or run \`colony --reload\` so it updates itself.`));
    return;
  }
  agents.forEach((a) => {
    const row = el('div', 'ctx-row');
    const top = el('div', 'ctx-top');
    top.append(avatar({ id: a.role_id, name: a.name }), el('span', 'ctx-name', a.name), el('span', 'ctx-model', shortModel(a.model)),
      el('span', 'ctx-pct ' + level(a.percent), a.percent == null ? 'no turn yet' : percentText(a.percent)));
    row.appendChild(top);
    if (a.percent != null) {
      const track = el('div', 'ctx-track'), fill = el('div', 'ctx-fill ' + level(a.percent));
      fill.style.width = Math.max(a.percent, 1) + '%'; track.appendChild(fill); row.appendChild(track);
    }
    const size = a.used_tokens == null ? `no turn yet · window ${tokens(a.window)} tokens` : `${tokens(a.used_tokens)} of ${tokens(a.window)} tokens`;
    row.appendChild(el('div', 'ctx-detail', size));
    pop.appendChild(row);
  });
  pop.appendChild(el('div', 'ctx-note', 'Real prompt sizes from OpenClaw. When a session gets full, OpenClaw summarises its older part by itself.'));
}

export function initContext() {
  $('ctxBtn').onclick = (e) => { e.stopPropagation(); $('ctxPop').classList.toggle('open'); };
  document.addEventListener('click', (e) => { if (!e.target.closest('.ctx-wrap')) $('ctxPop').classList.remove('open'); });
}
