// Connectors: the MCP servers agents may use (Composio for 1000+ apps, or any other MCP server), and links that open in the
// real browser. The list lives on the server (~/.colony/mcp-servers.json); secrets come back masked and are never shown here.
import { api } from './api.js';
import { $, closeModal, el, openModal, toast } from './dom.js';

// From the connector list of Colony's web app (frontend/src/lib/store/storeConnectors.ts). Composio Connect knows many more.
const APPS = ['Gmail', 'Google Drive', 'Google Calendar', 'Notion', 'Slack', 'GitHub', 'Linear', 'Jira', 'HubSpot', 'Airtable', 'Stripe', 'Figma', 'Outlook'];
let servers = {};

async function save(next, done) {
  $('connectorsError').textContent = '';
  try { servers = (await api('/mcp', { method: 'PUT', body: JSON.stringify({ servers: next }) })).servers; render(); if (done) toast(done); }
  catch (err) { $('connectorsError').textContent = err.message; }
}

function renderComposio() {
  const box = $('composioBox'); box.innerHTML = '';
  box.appendChild(el('label', null, 'Composio · 1000+ apps in one connection'));
  if (servers.composio) {
    box.appendChild(el('small', null, servers.composio.enabled ? 'Connected with your consumer key. Agents connect each app the first time they need it.' : 'Turned off.'));
    return;
  }
  const row = el('div', 'input-row'), key = el('input'), add = el('button', 'btn', 'Add Composio');
  key.type = 'password'; key.placeholder = 'Consumer key (starts with ck_)'; key.autocomplete = 'off';
  add.onclick = async () => {
    $('connectorsError').textContent = '';
    try { servers = (await api('/mcp/composio', { method: 'POST', body: JSON.stringify({ key: key.value }) })).servers; render(); toast('Composio added'); }
    catch (err) { $('connectorsError').textContent = err.message; }
  };
  row.append(key, add); box.appendChild(row);
  box.appendChild(el('small', null, 'Sign in at composio.dev, open the dashboard and copy your consumer key. It is sent only to Composio.'));
}

function renderList() {
  const list = $('connectorList'); list.innerHTML = '';
  const names = Object.keys(servers);
  if (!names.length) { list.appendChild(el('small', null, 'None yet.')); return; }
  names.forEach((name) => {
    const s = servers[name], row = el('div', 'connector-row');
    row.append(el('span', 'cname', name), el('span', 'sub', s.url || `${s.command} ${(s.args || []).join(' ')}`.trim()));
    const on = el('button', 'btn small', s.enabled ? 'On' : 'Off');
    on.onclick = () => save({ ...servers, [name]: { ...s, enabled: !s.enabled } });
    const del = el('button', 'btn small danger', 'Remove');
    del.onclick = () => { const { [name]: _gone, ...rest } = servers; save(rest, `${name} removed`); };
    row.append(on, del); list.appendChild(row);
  });
}

function render() { renderComposio(); renderList(); }

function renderApps() {
  const chips = $('appChips'); chips.innerHTML = '';
  APPS.forEach((app) => {
    const b = el('button', 'chip-btn', app);
    b.onclick = () => { closeModal('connectorsModal'); const box = $('prompt'); box.value = `Connect my ${app} account so you can use it.`; box.focus(); };
    chips.appendChild(b);
  });
}

// "KEY=value" lines for a program, "Header: value" lines for an address.
function secretsFrom(text, isUrl) {
  const out = {}, split = isUrl ? ':' : '=';
  text.split('\n').map((l) => l.trim()).filter(Boolean).forEach((line) => {
    const at = line.indexOf(split);
    if (at > 0) out[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  });
  return out;
}

async function addCustom() {
  const name = $('cName').value.trim().toLowerCase(), target = $('cTarget').value.trim();
  if (!name || !target) { $('connectorsError').textContent = 'Give it a name and an address or command.'; return; }
  const isUrl = target.startsWith('http://') || target.startsWith('https://'), secrets = secretsFrom($('cSecrets').value, isUrl);
  const [command, ...args] = target.split(' ').filter(Boolean);
  const server = isUrl ? { url: target, headers: secrets } : { command, args, env: secrets };
  await save({ ...servers, [name]: server }, `${name} added`);
  if (!$('connectorsError').textContent) { $('cName').value = ''; $('cTarget').value = ''; $('cSecrets').value = ''; }
}

export async function openConnectors() {
  $('connectorsError').textContent = '';
  try { servers = (await api('/mcp')).servers; } catch (err) { servers = {}; $('connectorsError').textContent = err.message; }
  render(); openModal('connectorsModal');
}

export function initConnectors() {
  renderApps();
  $('addConnectorBtn').onclick = addCustom;
  // A link in a reply (a sign-in page, a source) opens in the real browser, not inside this window.
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a || !(a.href.startsWith('http://') || a.href.startsWith('https://')) || a.origin === location.origin) return;
    e.preventDefault();
    api('/open-url', { method: 'POST', body: JSON.stringify({ url: a.href }) }).catch(() => window.open(a.href, '_blank', 'noopener'));
  });
}
