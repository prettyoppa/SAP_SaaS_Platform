/* SAP Dev Hub – main.js */

/* ── 테마 토글 ──────────────────────────────── */
function _applyThemeIcon(theme) {
  const icon = document.getElementById('themeIcon');
  if (!icon) return;
  if (theme === 'light') {
    icon.className = 'fa-solid fa-sun';
  } else {
    icon.className = 'fa-solid fa-moon';
  }
}

function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  _applyThemeIcon(next);
}

document.addEventListener('DOMContentLoaded', () => {
  /* 저장된 테마 적용 (아이콘 동기화) */
  const savedTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  _applyThemeIcon(savedTheme);

  /* Drag-over highlight on file drop zone */
  const dz = document.getElementById('drop-zone');
  if (dz) {
    ['dragenter', 'dragover'].forEach(ev => {
      dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(ev => {
      dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('dragover'); });
    });
    dz.addEventListener('drop', e => {
      const file = e.dataTransfer.files[0];
      if (file) {
        const dt = new DataTransfer();
        dt.items.add(file);
        document.getElementById('attachment').files = dt.files;
        showFileSelected(file.name);
      }
    });
  }

});

function showFileSelected(name) {
  document.getElementById('drop-content').classList.add('d-none');
  document.getElementById('file-selected').classList.remove('d-none');
  document.getElementById('file-name-display').textContent = name;
}
