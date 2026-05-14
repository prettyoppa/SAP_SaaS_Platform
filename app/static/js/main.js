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
  const ring = el.querySelector('.busy-spinner-ring');
  if (ring) ring.classList.remove('busy-spinner-ring--agents-mascot');
  const agents = meta && Array.isArray(meta.agents) && meta.agents.length ? meta.agents : null;

  if (agents) {
    if (ring) ring.classList.add('busy-spinner-ring--agents-mascot');
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
  if (el) {
    const ring = el.querySelector('.busy-spinner-ring');
    if (ring) ring.classList.remove('busy-spinner-ring--agents-mascot');
    el.setAttribute('hidden', '');
  }
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

/**
 * 브라우저 기본 confirm(페이지 출처 표시) 대체 — Bootstrap 모달.
 * @param {string} message
 * @returns {Promise<boolean>}
 */
function appConfirm(message) {
  const text = message != null && message !== '' ? String(message) : '';
  return new Promise((resolve) => {
    const modalEl = document.getElementById('appConfirmModal');
    if (!modalEl || typeof bootstrap === 'undefined') {
      resolve(window.confirm(text));
      return;
    }
    const body = document.getElementById('appConfirmModalBody');
    if (body) body.textContent = text;
    const inst = bootstrap.Modal.getOrCreateInstance(modalEl);
    let resolved = false;
    const finish = (v) => {
      if (resolved) return;
      resolved = true;
      resolve(v);
    };
    const okBtn = document.getElementById('appConfirmModalOk');
    const onHidden = () => {
      if (okBtn) okBtn.removeEventListener('click', onOkClick);
      finish(false);
    };
    const onOkClick = (ev) => {
      ev.preventDefault();
      modalEl.removeEventListener('hidden.bs.modal', onHidden);
      if (okBtn) okBtn.removeEventListener('click', onOkClick);
      inst.hide();
      finish(true);
    };
    modalEl.addEventListener('hidden.bs.modal', onHidden, { once: true });
    if (okBtn) okBtn.addEventListener('click', onOkClick);
    inst.show();
  });
}
window.appConfirm = appConfirm;

/* ── 테마 토글 (슬라이드 스위치 + role="switch") ──────────────────────────────── */
function _syncThemeSwitchAria(theme, doc) {
  const d = doc || document;
  const btn = d.getElementById('themeToggleBtn');
  if (!btn) return;
  btn.setAttribute('aria-checked', theme === 'light' ? 'true' : 'false');
}

const _LOGO_LIGHT = '/static/img/catch_lab_sap_dev_hub_logo.png?v=20260428cat';
const _LOGO_DARK = '/static/img/catch_lab_sap_dev_hub_logo_dark.png?v=20260428cat';

function _syncFaviconForThemeInDoc(doc, theme) {
  if (!doc) return;
  const href = theme === 'dark' ? _LOGO_DARK : _LOGO_LIGHT;
  const fi = doc.getElementById('site-favicon');
  const ai = doc.getElementById('site-apple-icon');
  if (fi) fi.href = href;
  if (ai) ai.href = href;
}

function _syncFaviconForTheme(theme) {
  _syncFaviconForThemeInDoc(document, theme);
}

/**
 * 같은 문서 루트에 data-theme 과 파비 등을 적용합니다.
 * @param {Document} doc
 * @param {string} theme
 */
function applyThemeToDoc(doc, theme) {
  if (!doc || !doc.documentElement) return;
  const t = (theme == null ? '' : String(theme)).trim() || 'dark';
  doc.documentElement.setAttribute('data-theme', t);
  _syncFaviconForThemeInDoc(doc, t);
  _syncThemeSwitchAria(t, doc);
}

/** 부모 페이지에 있는 같은 출처 iframe(요청 Console 미리보기 등)에 테마 반영 */
function syncThemeToChildIframes(theme) {
  document.querySelectorAll('iframe').forEach((ifr) => {
    try {
      const d = ifr.contentDocument;
      if (d) applyThemeToDoc(d, theme);
    } catch (_) {
      /* cross-origin */
    }
  });
}

/** iframe 이 로드될 때마다 부모와 동일한 테마로 맞춤 */
function wireIframeThemeSyncFromParent(ifr) {
  if (!(ifr instanceof HTMLIFrameElement)) return;
  if (ifr.dataset.sapThemeIframeSync === '1') return;
  ifr.dataset.sapThemeIframeSync = '1';
  ifr.addEventListener('load', () => {
    try {
      const d = ifr.contentDocument;
      const t =
        document.documentElement.getAttribute('data-theme') ||
        localStorage.getItem('theme') ||
        'dark';
      if (d) applyThemeToDoc(d, t);
    } catch (_) {
      /* cross-origin */
    }
  });
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  applyThemeToDoc(document, next);
  localStorage.setItem('theme', next);
  syncThemeToChildIframes(next);
}

/** 프로필(쿠키 viewer_tz) 또는 브라우저 타임존으로 UTC(data-utc) 시각 표시 */
function formatLocalDateTimes() {
  const rawTz = (document.documentElement.getAttribute('data-user-timezone') || '').trim();
  let browserTz = 'UTC';
  try {
    browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch (_) {
    /* ignore */
  }
  const tz = rawTz || browserTz;
  const lang = document.documentElement.getAttribute('lang') || 'ko';
  const locale = lang === 'en' ? 'en-US' : 'ko-KR';

  document.querySelectorAll('.local-dt[data-utc]').forEach((el) => {
    const raw = el.getAttribute('data-utc');
    if (!raw) return;
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return;
    const fmt = (el.getAttribute('data-fmt') || 'datetime').trim();
    let text = '';
    try {
      if (fmt === 'date') {
        text = new Intl.DateTimeFormat(locale, {
          timeZone: tz,
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
        }).format(d);
      } else if (fmt === 'date_dots') {
        const ca = new Intl.DateTimeFormat('en-CA', {
          timeZone: tz,
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
        }).format(d);
        text = ca.replace(/-/g, '.');
      } else {
        text = new Intl.DateTimeFormat(locale, {
          timeZone: tz,
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
        }).format(d);
      }
    } catch (_) {
      text = d.toLocaleString(locale);
    }
    el.textContent = text;
  });
}

/** AI 후속 질문: 전역 busy 대신 패널 안 로컬 오버레이 + 제출 후 패널 유지(sessionStorage). */
const _KEEP_AI_LAUNCHER_KEY = 'keepAiPanelOpenLauncher';

document.addEventListener(
  'submit',
  (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.classList.contains('offer-inquiry-form')) {
      const msg =
        (form.dataset && form.dataset.offerInquiryBusyKo) ||
        '전송 중입니다…';
      const prog = form.querySelector('.offer-inquiry-progress');
      if (prog) {
        prog.textContent = msg;
        prog.classList.remove('d-none');
      }
      return;
    }
    if (!form.classList.contains('abap-followup-form')) return;
    if (form.dataset.noBusy !== 'true' && form.dataset.noBusy !== '') return;
    const panel = form.closest('.abap-float-chat-panel');
    const busy = panel && panel.querySelector('.abap-float-chat-local-busy');
    if (busy) busy.removeAttribute('hidden');
    const root = panel && panel.closest('.abap-float-chat');
    const launcher = root && root.querySelector('.abap-float-chat-launcher');
    if (launcher && launcher.id) {
      try {
        sessionStorage.setItem(_KEEP_AI_LAUNCHER_KEY, launcher.id);
      } catch (_) {
        /* ignore */
      }
    }
  },
  true,
);

document.addEventListener('DOMContentLoaded', () => {
  try {
    const lid = sessionStorage.getItem(_KEEP_AI_LAUNCHER_KEY);
    if (lid) {
      sessionStorage.removeItem(_KEEP_AI_LAUNCHER_KEY);
      const launcher = document.getElementById(lid);
      const cid = launcher && launcher.getAttribute('aria-controls');
      const panel = cid ? document.getElementById(cid) : null;
      if (launcher && panel && panel.hasAttribute('hidden')) {
        panel.removeAttribute('hidden');
        launcher.setAttribute('aria-expanded', 'true');
        window.dispatchEvent(new Event('resize'));
      }
    }
  } catch (_) {
    /* ignore */
  }

  document.addEventListener(
    'submit',
    (e) => {
      const form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (form.dataset.appConfirmBypass === '1') {
        delete form.dataset.appConfirmBypass;
        return;
      }
      let msg = form.getAttribute('data-app-confirm');
      const i18nKey = form.getAttribute('data-app-confirm-i18n');
      if ((!msg || !String(msg).trim()) && i18nKey && typeof window.t === 'function') {
        const tr = window.t(i18nKey);
        if (tr != null && String(tr).trim()) msg = String(tr);
      }
      if (!msg || !String(msg).trim()) return;
      e.preventDefault();
      e.stopPropagation();
      appConfirm(String(msg)).then((ok) => {
        if (!ok) return;
        form.dataset.appConfirmBypass = '1';
        if (typeof form.requestSubmit === 'function') form.requestSubmit();
        else form.submit();
      });
    },
    true,
  );

  window.addEventListener('storage', (e) => {
    if (e.key !== 'theme') return;
    const next =
      (e.newValue || localStorage.getItem('theme') || 'dark').trim() ||
      'dark';
    applyThemeToDoc(document, next);
  });

  const savedTheme = localStorage.getItem('theme') || 'dark';
  applyThemeToDoc(document, savedTheme);
  document.querySelectorAll('iframe').forEach((ifr) =>
    wireIframeThemeSyncFromParent(ifr),
  );
  formatLocalDateTimes();

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
        /* 첨부 다운로드(/…/attachment): 같은 탭에서 파일만 받거나 R2 프리사인으로 나가도
           전체 네비게이션이 없어 pageshow 가 없고 오버레이가 꺼지지 않음 */
        if (u.pathname.endsWith('/attachment')) return;
        /* 파일 다운로드(xlsx/pdf 등) 또는 /download 라우트는 네비게이션 없이 내려받을 수 있어
           오버레이가 영구적으로 남을 수 있음 */
        const p = (u.pathname || '').toLowerCase();
        if (p.endsWith('.xlsx') || p.endsWith('.csv') || p.endsWith('.pdf') || p.endsWith('.zip')) return;
        if (p.endsWith('/download') || p.includes('/download/')) return;
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
    document.querySelectorAll('.abap-float-chat-local-busy').forEach((el) => {
      el.setAttribute('hidden', '');
    });
  });
});

/* 참고·개발 코드 등: 잠금 영역에서 복사/잘라내기 차단(허용 사용자는 .code-asset-locked 없음) */
document.addEventListener(
  'copy',
  (e) => {
    const t = e.target;
    if (!t || typeof t.closest !== 'function') return;
    if (t.closest('textarea, input, [contenteditable="true"]')) return;
    if (t.closest('.code-asset-locked')) e.preventDefault();
  },
  true,
);
document.addEventListener(
  'cut',
  (e) => {
    const t = e.target;
    if (!t || typeof t.closest !== 'function') return;
    if (t.closest('textarea, input, [contenteditable="true"]')) return;
    if (t.closest('.code-asset-locked')) e.preventDefault();
  },
  true,
);
