// "Worked for 17s" under an agent's reply: what it thought and did, step by step (commands with their output, files read,
// memory searches...). Collapsed by default; while the agent is still working the same list is shown live.
import { $, el } from './dom.js';
import { icon, STEP_ICON } from './icons.js';

const secs = (s) => (s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${Math.max(1, Math.round(s))}s`);

function stepRow(step) {
  const row = el('div', 'step' + (step.ok === false ? ' failed' : ''));
  const head = el('button', 'step-head'); head.type = 'button';
  const ico = el('span', 'step-ico'); ico.innerHTML = icon(STEP_ICON[step.kind] || 'settings', 15);
  const title = el('span', 'step-title', step.title), detail = el('span', 'step-detail', step.detail || '');
  head.append(ico, title, detail);
  if (step.ms) head.appendChild(el('span', 'step-ms', step.ms >= 1000 ? `${(step.ms / 1000).toFixed(1)}s` : `${step.ms}ms`));
  row.appendChild(head);
  if (step.kind === 'command' || step.output) {
    const body = el('div', 'step-body');
    if (step.kind === 'command') {
      const cmd = el('div', 'step-cmd'); cmd.append(el('span', 'prompt', '$ '), el('span', null, step.detail || ''));
      body.appendChild(cmd);
    }
    if (step.output) body.appendChild(el('pre', 'step-out', step.output));
    row.appendChild(body);
    head.onclick = () => row.classList.toggle('open');
    if (step.kind === 'command') row.classList.add('open');     // a command is shown with its output, like a terminal
  }
  return row;
}

// steps: [{kind, title, detail, output, ok, ms}], opts: {thinking, workedS, live}
export function renderWork(steps = [], { thinking = '', workedS = null, live = false } = {}) {
  if (!steps.length && !thinking && !live) return null;
  const box = el('div', 'work' + (live ? ' live open' : ''));
  const head = el('button', 'work-head'); head.type = 'button';
  const label = live ? 'Working…' : workedS != null ? `Worked for ${secs(workedS)}` : 'Worked';
  const caret = el('span', 'caret'); caret.innerHTML = icon('chevron', 14);
  head.append(el('span', null, label), caret);
  if (steps.length) head.appendChild(el('span', 'work-count', `${steps.length} step${steps.length > 1 ? 's' : ''}`));
  head.onclick = () => box.classList.toggle('open');
  const body = el('div', 'work-body');
  if (thinking) {
    const t = el('div', 'thought'); t.append(el('div', 'thought-title', 'Thought'), el('div', 'thought-text', thinking));
    body.appendChild(t);
  }
  steps.forEach((s) => body.appendChild(stepRow(s)));
  box.append(head, body);
  return box;
}
