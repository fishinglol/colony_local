import { el } from './dom.js';

const PALETTE = ['#a78bfa', '#67e8f9', '#fcd34d', '#6ee7b7', '#fda4af', '#7dd3fc', '#bef264', '#fdba74'];

// Color follows the agent's id (not its list position), so deleting or
// reordering agents never changes anyone's color.
export function roleColor(id) {
  let h = 0;
  for (const c of id || '') h = (h * 31 + c.charCodeAt(0)) % 997;
  return PALETTE[h % PALETTE.length];
}

export function avatar(role, large) {
  const a = el('span', 'avatar' + (large ? ' lg' : ''), (role?.name || '?').slice(0, 1).toUpperCase());
  a.style.background = role ? roleColor(role.id) : '#6b7280';
  if (!large) a.appendChild(el('span', 'status'));
  return a;
}
