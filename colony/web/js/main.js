// Entry point: wire the page's buttons to the modules, then load the initial data.
import { deleteAgent, getModelField as getPickedModel, openAgentModal, openTools, saveAgent, setModel, testModel } from './agent-editor.js';
import { initAttachments } from './attachments.js';
import { initLinks } from './links.js';
import { initToolPicker, openConnectors } from './tool-picker.js';
import { initContext } from './context.js';
import { initModelPicker, openModelPicker } from './model-picker.js';
import { initMode } from './mode.js';
import { $, closeModal } from './dom.js';
import { autosize, closeMenu, send } from './feed.js';
import { checkOpenClawGateway, openMemory, openSettings, refreshHealth, saveSettings } from './settings.js';
import { selectTarget } from './sidebar.js';
import { state } from './state.js';
import { browseFolder, deleteWorkspace, loadWorkspaces, openFolderMenu, openWorkspace, openWorkspaceMenu, saveWorkspace } from './workspaces.js';

$('autoRow').onclick = () => selectTarget(null);
$('wsBtn').onclick = (e) => openWorkspaceMenu(e.currentTarget);
$('saveWorkspaceBtn').onclick = saveWorkspace;
$('browseFolderBtn').onclick = browseFolder;
$('deleteWorkspaceBtn').onclick = deleteWorkspace;
$('addAgentBtn').onclick = () => openAgentModal('');
$('editAgentBtn').onclick = () => openAgentModal(state.target);
$('saveAgentBtn').onclick = saveAgent;
$('modelBtn').onclick = () => openModelPicker(setModel, getPickedModel());
$('connectToolBtn').onclick = () => openTools();
$('testModelBtn').onclick = testModel;
$('deleteAgentBtn').onclick = deleteAgent;
$('settingsBtn').onclick = openSettings;
$('saveSettingsBtn').onclick = saveSettings;
$('openclawPill').onclick = openSettings;
$('memoryBtn').onclick = openMemory;
$('connectorsBtn').onclick = openConnectors;
$('folderBtn').onclick = (e) => openFolderMenu(e.currentTarget);
$('menuBtn').onclick = () => $('sidebar').classList.toggle('show');
$('sendBtn').onclick = send;
$('prompt').addEventListener('input', autosize);
$('prompt').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
document.querySelectorAll('[data-close]').forEach((b) => { b.onclick = () => closeModal(b.dataset.close); });
document.querySelectorAll('.overlay').forEach((o) => { o.addEventListener('click', (e) => { if (e.target === o) closeModal(o.id); }); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') document.querySelectorAll('.overlay.open').forEach((o) => closeModal(o.id)); });
document.addEventListener('click', (e) => { if (!e.target.closest('.menu') && !e.target.closest('.msg-actions') && !e.target.closest('.ws-switch') && !e.target.closest('.reasoning-pill') && !e.target.closest('#modeBtn') && !e.target.closest('#folderBtn') && !e.target.closest('#addBtn')) closeMenu(); });

(async function init() {
  initContext();
  initMode();
  initLinks();
  initToolPicker();
  initAttachments();
  initModelPicker();
  await loadWorkspaces();
  await openWorkspace(null);   // the last workspace you used, else the first
  const h = await refreshHealth();
  checkOpenClawGateway();
  setInterval(checkOpenClawGateway, 10000);
  if (!h.has_openrouter_key && !h.mock_mode) openSettings();
})();
