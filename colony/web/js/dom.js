// Small DOM helpers shared by every module.
export const $ = (id) => document.getElementById(id);

export const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

export function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.style.display = 'none'; }, 2200);
}

export function openModal(id) { $(id).classList.add('open'); }
export function closeModal(id) { $(id).classList.remove('open'); }

export function shortModel(model) { return (model || '').split('/').pop(); }

export function timeOf(iso) {
  const d = iso ? new Date(iso) : new Date();
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// "read files, edit files (asks you), run commands" — or '' when an agent has no tools.
export function describeTools(t) {
  if (!t) return '';
  const on = [];
  if (t.read === 'allow') on.push('read files');
  if (t.write && t.write !== 'off') on.push(t.write === 'ask' ? 'edit files (asks you)' : 'edit files');
  if (t.bash && t.bash !== 'off') on.push(t.bash === 'ask' ? 'run commands (asks you)' : 'run commands');
  return on.join(', ');
}
