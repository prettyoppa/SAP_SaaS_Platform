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

  /* Drag-over highlight on file drop zone */
  const dz = document.getElementById('drop-zone');
  if (dz) {
    ['dragenter', 'dragover'].forEach(ev => {
      dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(ev => {
      dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('dragover'); });
    });
    dz.addEventListener('drop', async e => {
      const file = e.dataTransfer.files[0];
      if (!file) return;
      // DataTransfer에 원본 File만 넣으면 일부 브라우저에서 multipart 전송 시 0바이트가 될 수 있어
      // ArrayBuffer로 복사한 새 File을 넣는다.
      try {
        const buf = await file.arrayBuffer();
        const copy = new File([buf], file.name, { type: file.type || 'application/octet-stream' });
        const dt = new DataTransfer();
        dt.items.add(copy);
        const input = document.getElementById('attachment');
        input.files = dt.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
        showFileSelected(file.name);
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
