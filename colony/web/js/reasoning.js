// Reasoning level per agent: which levels a model supports (from OpenRouter's catalog), and the quick menu on
// the sidebar so a level can be changed without opening the editor.
import { api } from './api.js';
import { el, toast } from './dom.js';
import { closeMenu } from './feed.js';
import { findModel } from './model-picker.js';
import { renderSidebar } from './sidebar.js';
import { state } from './state.js';

export const LABELS = { default: 'Default', off: 'Off', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'X-High', max: 'Max' };

// {efforts, default, can_turn_off} for a model that can reason, or null (it can't, or we don't know its levels).
export function reasoningLevels(modelId) {
  return ((findModel(modelId) || {}).capabilities || {}).reasoning_levels || null;
}

// The choices for a model, in display order: Default (with the model's own level), Off if allowed, then its levels.
export function reasoningOptions(modelId) {
  const levels = reasoningLevels(modelId);
  if (!levels) return [];
  const options = [{ value: 'default', label: levels.default ? `Default (${LABELS[levels.default] || levels.default})` : 'Default' }];
  if (levels.can_turn_off) options.push({ value: 'off', label: 'Off' });
  levels.efforts.forEach((v) => options.push({ value: v, label: LABELS[v] || v }));
  return options;
}

// The level an agent really uses: what it chose, unless its model doesn't offer that (then the model's default).
export function effectiveReasoning(role) {
  const options = reasoningOptions(role.model);
  return options.some((o) => o.value === role.reasoning) ? role.reasoning : 'default';
}

export async function setReasoning(role, value) {
  const next = state.roles.map((r) => (r.id === role.id ? { ...r, reasoning: value } : r));
  try {
    state.roles = (await api(`/roles?workspace_id=${encodeURIComponent(state.workspaceId)}`, { method: 'PUT', body: JSON.stringify({ roles: next }) })).roles;
    renderSidebar();
    toast(`${role.name}: reasoning ${LABELS[value].toLowerCase()}`);
  } catch (err) { toast(err.message); }
}

// The small menu under a sidebar pill.
export function openReasoningMenu(anchor, role) {
  const open = document.querySelector('.menu.reasoning-menu');
  closeMenu();
  if (open) return;   // the pill toggles it
  const current = effectiveReasoning(role);
  const menu = el('div', 'menu reasoning-menu');
  menu.appendChild(el('div', 'menu-title', `Reasoning · ${role.name}`));
  reasoningOptions(role.model).forEach((o) => {
    const b = el('button', o.value === current ? 'current' : '', o.label);
    b.onclick = () => { closeMenu(); if (o.value !== current) setReasoning(role, o.value); };
    menu.appendChild(b);
  });
  menu.appendChild(el('div', 'menu-note', 'Higher = deeper thinking, but slower and more tokens.'));
  document.body.appendChild(menu);
  const box = anchor.getBoundingClientRect();
  menu.style.left = box.left + 'px'; menu.style.top = (box.bottom + 6) + 'px'; menu.style.minWidth = '210px';
}
