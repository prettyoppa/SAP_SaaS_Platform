/* SAP Dev Hub – main.js */

/* ── 테마 토글 (슬라이드 스위치 + role="switch") ──────────────────────────────── */
function _syncThemeSwitchAria(theme) {
  const btn = document.getElementById('themeToggleBtn');
  if (!btn) return;
  btn.setAttribute('aria-checked', theme === 'light' ? 'true' : 'false');
}

function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  _syncThemeSwitchAria(next);
}

document.addEventListener('DOMContentLoaded', () => {
  const savedTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  _syncThemeSwitchAria(savedTheme);

  /* Drag-over highlight on file drop zone (단일/다중 첨부) */
  const dz = document.getElementById('drop-zone');
  if (dz) {
    ['dragenter', 'dragover'].forEach(ev => {
      dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(ev => {
      dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('dragover'); });
    });
    dz.addEventListener('drop', async e => {
      const rawFiles = Array.from(e.dataTransfer.files || []);
      if (!rawFiles.length) return;
      const maxFiles = parseInt(dz.getAttribute('data-max-files') || '1', 10) || 1;
      const files = rawFiles.slice(0, maxFiles);
      const input = document.getElementById('attachments') || document.getElementById('attachment');
      if (!input) return;
      try {
        const dt = new DataTransfer();
        for (const file of files) {
          const buf = await file.arrayBuffer();
          const copy = new File([buf], file.name, { type: file.type || 'application/octet-stream' });
          dt.items.add(copy);
        }
        input.files = dt.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
        const label = files.map(f => f.name).join(', ');
        if (typeof showFileSelected === 'function') showFileSelected(label);
      } catch (err) {
        console.error('drop attach', err);
      }
    });
  }

});

function showFileSelected(name) {
  document.getElementById('drop-content').classList.add('d-none');
  document.getElementById('file-selected').classList.remove('d-none');
  document.getElementById('file-name-display').textContent = name;
}
