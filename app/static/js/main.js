/* SAP Dev Hub – main.js */

/* ── 전역 “처리 중” 오버레이 ─────────────────────────────────────────────────── */
function showGlobalBusy() {
  const el = document.getElementById('global-busy-overlay');
  if (el) el.removeAttribute('hidden');
}

function hideGlobalBusy() {
  const el = document.getElementById('global-busy-overlay');
  if (el) el.setAttribute('hidden', '');
}

/* ── 테마 토글 (슬라이드 스위치 + role="switch") ──────────────────────────────── */
function _syncThemeSwitchAria(theme) {
  const btn = document.getElementById('themeToggleBtn');
  if (!btn) return;
  btn.setAttribute('aria-checked', theme === 'light' ? 'true' : 'false');
}

const _LOGO_LIGHT = '/static/img/catch_lab_sap_dev_hub_logo.png?v=20260428cat';
const _LOGO_DARK = '/static/img/catch_lab_sap_dev_hub_logo_dark.png?v=20260428cat';

function _syncFaviconForTheme(theme) {
  const href = theme === 'dark' ? _LOGO_DARK : _LOGO_LIGHT;
  const fi = document.getElementById('site-favicon');
  const ai = document.getElementById('site-apple-icon');
  if (fi) fi.href = href;
  if (ai) ai.href = href;
}

function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  _syncThemeSwitchAria(next);
  _syncFaviconForTheme(next);
}

document.addEventListener('DOMContentLoaded', () => {
  const savedTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  _syncThemeSwitchAria(savedTheme);
  _syncFaviconForTheme(savedTheme);

  document.addEventListener(
    'submit',
    (e) => {
      const form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (form.dataset.noBusy === 'true' || form.dataset.noBusy === '') return;
      const t = form.getAttribute('target');
      if (t && t.toLowerCase() === '_blank') return;
      showGlobalBusy();
    },
    true,
  );

  document.addEventListener(
    'click',
    (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
        return;
      }
      const a = e.target.closest('a');
      if (!a || !a.href) return;
      if (a.dataset.noBusy === 'true' || a.dataset.noBusy === '') return;
      if (a.target === '_blank' || a.hasAttribute('download')) return;
      const href = (a.getAttribute('href') || '').trim();
      if (!href || href.startsWith('#') || href.toLowerCase().startsWith('javascript:')) return;
      try {
        const u = new URL(a.href, window.location.href);
        if (u.origin !== window.location.origin) return;
      } catch (_) {
        return;
      }
      showGlobalBusy();
    },
    true,
  );

  window.addEventListener('pageshow', (ev) => {
    if (ev.persisted) hideGlobalBusy();
  });
});


