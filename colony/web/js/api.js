// The one place the UI talks to the local server.
export async function api(path, options = {}) {
  const res = await fetch('/api' + path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join('; ') : body.detail;
    throw new Error(detail || res.statusText);
  }
  return body;
}
