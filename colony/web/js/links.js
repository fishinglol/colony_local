// A link in a reply (a sign-in page, a source) opens in the real browser, not inside this window.
import { api } from './api.js';

export function initLinks() {
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a || !(a.href.startsWith('http://') || a.href.startsWith('https://')) || a.origin === location.origin) return;
    e.preventDefault();
    api('/open-url', { method: 'POST', body: JSON.stringify({ url: a.href }) }).catch(() => window.open(a.href, '_blank', 'noopener'));
  });
}
