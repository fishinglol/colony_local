import { el } from './dom.js';

// Calm, neutral initials: one tone per agent (by id, so deleting or reordering agents never changes anyone's), no bright colors.
const TONES = ['#3f3f46', '#52525b', '#44403c', '#3f4a46', '#46404a', '#404a52'];

export function roleColor(id) {
  let h = 0;
  for (const c of id || '') h = (h * 31 + c.charCodeAt(0)) % 997;
  return TONES[h % TONES.length];
}

export function avatar(role, large) {
  const a = el('span', 'avatar' + (large ? ' lg' : ''), (role?.name || '?').slice(0, 1).toUpperCase());
  a.style.background = role ? roleColor(role.id) : '#3f3f46';
  if (!large) a.appendChild(el('span', 'status'));
  return a;
}
