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

});


