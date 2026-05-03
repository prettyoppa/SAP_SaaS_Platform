/* SAP Dev Hub – main.js */

/* ── 전역 “처리 중” 오버레이 ─────────────────────────────────────────────────── */

function _busyOverlay() {
  return document.getElementById('global-busy-overlay');
}

function _busyDefaults() {
  const root = _busyOverlay();
  if (!root) return { titleKo: '', titleEn: '', hintKo: '', hintEn: '' };
  return {
    titleKo: root.getAttribute('data-default-title-ko') || '처리 중입니다…',
    titleEn: root.getAttribute('data-default-title-en') || 'Processing…',
    hintKo: root.getAttribute('data-default-hint-ko') || '잠시만 기다려 주세요.',
    hintEn: root.getAttribute('data-default-hint-en') || 'Please wait.',
  };
}

function _setBusyTitles(titleKo, titleEn) {
  const titles = document.querySelectorAll('#global-busy-overlay .global-busy-title');
  titles.forEach((el) => {
    if (el.classList.contains('nav-ko')) el.textContent = titleKo;
    if (el.classList.contains('nav-en')) el.textContent = titleEn;
  });
}

function _setBusyHints(hintKo, hintEn) {
  const hints = document.querySelectorAll('#global-busy-overlay .global-busy-hint');
  hints.forEach((el) => {
    if (el.classList.contains('nav-ko')) el.textContent = hintKo;
    if (el.classList.contains('nav-en')) el.textContent = hintEn;
  });
}

function _clearAgentLines() {
  const ko = document.getElementById('global-busy-agent-lines-ko');
  const en = document.getElementById('global-busy-agent-lines-en');
  const card = document.getElementById('global-busy-card');
  if (ko) {
    ko.innerHTML = '';
    ko.classList.add('d-none');
  }
  if (en) {
    en.innerHTML = '';
    en.classList.add('d-none');
  }
  if (card) card.classList.remove('has-agent-lines');
}

function _agentSentence(row) {
  const ak = (row.agentKo || '').trim();
  const dk = (row.doingKo || '').trim();
  const ae = (row.agentEn || '').trim();
  const de = (row.doingEn || '').trim();
  const ko = ak && dk ? `${ak} 에이전트가 ${dk}` : dk || ak || '';
  const en = ae && de ? `${ae} is ${de}` : de || ae || ko;
  return { ko, en };
}

/**
 * @param {{ agents?: Array<{agentKo?:string,doingKo?:string,agentEn?:string,doingEn?:string}>|null,
 *          titleKo?:string,titleEn?:string,hintKo?:string,hintEn?:string}|null|undefined} meta
 */
function showGlobalBusy(meta) {
  const el = _busyOverlay();
  if (!el) return;
  const d = _busyDefaults();
  _clearAgentLines();
  const agents = meta && Array.isArray(meta.agents) && meta.agents.length ? meta.agents : null;

  if (agents) {
    const listKo = document.getElementById('global-busy-agent-lines-ko');
    const listEn = document.getElementById('global-busy-agent-lines-en');
    const card = document.getElementById('global-busy-card');
    if (card) card.classList.add('has-agent-lines');
    const titleKo = (meta && meta.titleKo) || '에이전트 작업을 진행하고 있습니다…';
    const titleEn = (meta && meta.titleEn) || 'Running agent tasks…';
    const hintKo = (meta && meta.hintKo) || '완료되면 화면이 바뀝니다. 창을 닫지 마세요.';
    const hintEn = (meta && meta.hintEn) || 'The page will update when finished. Please keep this tab open.';
    _setBusyTitles(titleKo, titleEn);
    _setBusyHints(hintKo, hintEn);
    agents.forEach((row) => {
      const { ko, en } = _agentSentence(row);
      if (!ko && !en) return;
      if (listKo && ko) {
        const li = document.createElement('li');
        li.textContent = ko;
        listKo.appendChild(li);
      }
      if (listEn && en) {
        const li2 = document.createElement('li');
        li2.textContent = en;
        listEn.appendChild(li2);
      }
    });
    if (listKo && listKo.childElementCount) listKo.classList.remove('d-none');
    if (listEn && listEn.childElementCount) listEn.classList.remove('d-none');
  } else {
    const titleKo = (meta && meta.titleKo) || d.titleKo;
    const titleEn = (meta && meta.titleEn) || d.titleEn;
    const hintKo = (meta && meta.hintKo) || d.hintKo;
    const hintEn = (meta && meta.hintEn) || d.hintEn;
    _setBusyTitles(titleKo, titleEn);
    _setBusyHints(hintKo, hintEn);
  }
  el.removeAttribute('hidden');
}

function hideGlobalBusy() {
  const el = _busyOverlay();
  if (el) el.setAttribute('hidden', '');
  const d = _busyDefaults();
  _setBusyTitles(d.titleKo, d.titleEn);
  _setBusyHints(d.hintKo, d.hintEn);
  _clearAgentLines();
}

function _readDatasetBusy(form, submitter) {
  const pick = (key) => {
    if (submitter && submitter.dataset && submitter.dataset[key] != null && submitter.dataset[key] !== '') {
      return submitter.dataset[key];
    }
    if (form && form.dataset && form.dataset[key] != null && form.dataset[key] !== '') {
      return form.dataset[key];
    }
    return '';
  };
  const rawAgents = pick('busyAgents');
  if (rawAgents && rawAgents.trim()) {
    try {
      const parsed = JSON.parse(rawAgents);
      if (Array.isArray(parsed) && parsed.length) {
        return { agents: parsed };
      }
    } catch (_) {
      /* ignore */
    }
  }
  const titleKo = pick('busyTitleKo');
  const titleEn = pick('busyTitleEn');
  const hintKo = pick('busyHintKo');
  const hintEn = pick('busyHintEn');
  if (titleKo || titleEn || hintKo || hintEn) {
    return { titleKo: titleKo || undefined, titleEn: titleEn || undefined, hintKo: hintKo || undefined, hintEn: hintEn || undefined };
  }
  return null;
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
      const meta = _readDatasetBusy(form, e.submitter);
      /* 캡처에서 바로 showGlobalBusy 하면 onsubmit="return confirm…" 취소 후에도 오버레이가 켜짐.
         버블 + microtask: 동기 핸들러(확인 취소 등)까지 반영된 defaultPrevented 를 본 뒤 표시. */
      queueMicrotask(() => {
        if (e.defaultPrevented) return;
        showGlobalBusy(meta);
      });
    },
    false,
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
      const meta = _readDatasetBusy(a, a);
      showGlobalBusy(meta);
    },
    true,
  );

  window.addEventListener('pageshow', (ev) => {
    if (ev.persisted) hideGlobalBusy();
  });
});
