// Safe markdown: escape everything first, then add a small fixed set of tags. No regex.
// Pure functions (no DOM), so it is easy to test and can't run model output as HTML.
function esc(s) {
  return s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}
function unesc(s) {
  return s.replaceAll('&#39;', "'").replaceAll('&quot;', '"').replaceAll('&gt;', '>').replaceAll('&lt;', '<').replaceAll('&amp;', '&');
}
function inline(raw) {
  let s = esc(raw), out = '', i = 0;
  while (i < s.length) {
    if (s[i] === '`') {
      const j = s.indexOf('`', i + 1);
      if (j > i) { out += '<code>' + s.slice(i + 1, j) + '</code>'; i = j + 1; continue; }
    }
    if (s.startsWith('**', i)) {
      const j = s.indexOf('**', i + 2);
      if (j > i + 2) { out += '<strong>' + inline(unesc(s.slice(i + 2, j))) + '</strong>'; i = j + 2; continue; }
    }
    if (s[i] === '[') {
      const close = s.indexOf('](', i);
      const end = close > 0 ? s.indexOf(')', close) : -1;
      if (close > i && end > close) {
        const url = s.slice(close + 2, end);
        if (url.startsWith('http://') || url.startsWith('https://')) {
          out += '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + s.slice(i + 1, close) + '</a>';
          i = end + 1; continue;
        }
      }
    }
    out += s[i]; i++;
  }
  return out;
}
function isOrdered(line) {
  const dot = line.indexOf('. ');
  if (dot < 1 || dot > 3) return false;
  for (const c of line.slice(0, dot)) if (c < '0' || c > '9') return false;
  return true;
}
function isTableSep(line) {
  const t = line.trim();
  if (!t.includes('-') || !t.includes('|')) return false;
  for (const c of t) if (!'|-: '.includes(c)) return false;
  return true;
}
function cells(line) {
  let t = line.trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|')) t = t.slice(0, -1);
  return t.split('|').map((c) => inline(c.trim()));
}

export function renderMarkdown(text) {
  const lines = text.replaceAll('\r\n', '\n').split('\n');
  let html = '', i = 0, para = [];
  const flush = () => { if (para.length) { html += '<p>' + para.map(inline).join('<br>') + '</p>'; para = []; } };
  while (i < lines.length) {
    const line = lines[i], t = line.trim();
    if (t.startsWith('```')) {
      flush(); const code = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) code.push(lines[i++]);
      html += '<pre><code>' + esc(code.join('\n')) + '</code></pre>'; i++; continue;
    }
    if (t === '') { flush(); i++; continue; }
    if (t.startsWith('#')) {
      let level = 0; while (t[level] === '#') level++;
      if (level <= 6 && t[level] === ' ') { flush(); const h = Math.min(level, 3); html += `<h${h}>` + inline(t.slice(level + 1)) + `</h${h}>`; i++; continue; }
    }
    if (t.startsWith('- ') || t.startsWith('* ') || isOrdered(t)) {
      flush(); const ordered = isOrdered(t); const items = [];
      while (i < lines.length) {
        const u = lines[i].trim();
        if (ordered ? isOrdered(u) : (u.startsWith('- ') || u.startsWith('* '))) items.push(u.slice(u.indexOf(' ') + 1));
        else break;
        i++;
      }
      const tag = ordered ? 'ol' : 'ul';
      html += `<${tag}>` + items.map((x) => '<li>' + inline(x) + '</li>').join('') + `</${tag}>`; continue;
    }
    if (t.startsWith('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      flush(); const head = cells(t); i += 2; const body = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) body.push(cells(lines[i++]));
      html += '<table><thead><tr>' + head.map((c) => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>' +
        body.map((r) => '<tr>' + r.map((c) => '<td>' + c + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
      continue;
    }
    if (t.startsWith('> ')) { flush(); html += '<blockquote>' + inline(t.slice(2)) + '</blockquote>'; i++; continue; }
    para.push(line); i++;
  }
  flush();
  return html;
}
