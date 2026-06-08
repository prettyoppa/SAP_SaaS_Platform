/* SAP Dev Hub – main.js */

/** 임시저장 플로팅 — AI 문의(우하단) 스택 위에 붙이거나, 없으면 우하단 고정 */
function hoistDraftFloatLaunchers(chatRoot) {
  const chat =
    chatRoot instanceof HTMLElement
      ? chatRoot
      : document.querySelector('.abap-float-chat');
  document.querySelectorAll('.draft-float-launcher[data-draft-float-root]').forEach((el) => {
    if (!(el instanceof HTMLElement)) return;
    if (el.dataset.draftFloatHoisted === '1') return;

    if (chat) {
      const launcher = chat.querySelector('.abap-float-chat-launcher');
      if (launcher) {
        chat.insertBefore(el, launcher);
      } else {
        chat.appendChild(el);
      }
      el.classList.add('draft-float-launcher--in-chat');
    } else {
      document.body.appendChild(el);
      el.classList.remove('draft-float-launcher--in-chat');
    }
    el.dataset.draftFloatHoisted = '1';
  });
}

window.hoistDraftFloatLaunchers = hoistDraftFloatLaunchers;

/* ── Enter 제출 방지 + 통화(₩) 입력 포맷 ──────────────────────────────────────── */

function _digitsOnly(s) {
  return String(s || '').replace(/[^\d]/g, '');
}

function _formatKrw(s) {
  const d = _digitsOnly(s);
  if (!d) return '';
  try {
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(Number(d));
  } catch (_) {
    return d.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }
}

function _formatUsd(s, { padDecimals = false } = {}) {
  const raw = String(s || '').replace(/,/g, '').replace(/[^\d.]/g, '');
  if (!raw) return '';
  const dotIdx = raw.indexOf('.');
  let intStr = dotIdx >= 0 ? raw.slice(0, dotIdx) : raw;
  let decStr = dotIdx >= 0 ? raw.slice(dotIdx + 1).replace(/\./g, '') : '';
  intStr = intStr.replace(/^0+(?=\d)/, '');
  if (!intStr && (dotIdx >= 0 || decStr)) intStr = '0';
  if (!intStr) return '';
  decStr = decStr.slice(0, 2);
  let intNum = parseInt(intStr, 10);
  if (!Number.isFinite(intNum)) intNum = 0;
  let intFmt;
  try {
    intFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(intNum);
  } catch (_) {
    intFmt = intStr.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }
  if (padDecimals) {
    return intFmt + '.' + (decStr + '00').slice(0, 2);
  }
  if (dotIdx >= 0) {
    return decStr.length ? intFmt + '.' + decStr : intFmt + '.';
  }
  return intFmt;
}

function _applyUsdFormat(el, opts) {
  if (!(el instanceof HTMLInputElement)) return;
  const before = el.value;
  const formatted = _formatUsd(before, opts || {});
  if (formatted === before) return;
  const atEnd = el.selectionStart === before.length && el.selectionEnd === before.length;
  el.value = formatted;
  if (atEnd) {
    try {
      el.setSelectionRange(formatted.length, formatted.length);
    } catch (_) {
      /* ignore */
    }
  }
}

function _applyKrwFormat(el) {
  if (!(el instanceof HTMLInputElement)) return;
  const before = el.value;
  const formatted = _formatKrw(before);
  if (formatted === before) return;
  // 간단한 caret 유지: 끝에서 입력하는 케이스 우선
  const atEnd = el.selectionStart === before.length && el.selectionEnd === before.length;
  el.value = formatted;
  if (atEnd) {
    try {
      el.setSelectionRange(formatted.length, formatted.length);
    } catch (_) {
      /* ignore */
    }
  }
}

function initCurrencyAndEnterGuards(root) {
  const scope = root instanceof HTMLElement ? root : document;

  // KRW 천단위 자동 포맷
  scope.querySelectorAll('input.js-currency-krw').forEach((el) => {
    if (!(el instanceof HTMLInputElement)) return;
    if (el.dataset.currencyInit === '1') return;
    el.dataset.currencyInit = '1';
    _applyKrwFormat(el);
    el.addEventListener('input', () => _applyKrwFormat(el));
    el.addEventListener('blur', () => _applyKrwFormat(el));
  });

  scope.querySelectorAll('input.js-currency-usd').forEach((el) => {
    if (!(el instanceof HTMLInputElement)) return;
    if (el.dataset.currencyInit === '1') return;
    el.dataset.currencyInit = '1';
    _applyUsdFormat(el, { padDecimals: false });
    el.addEventListener('input', () => _applyUsdFormat(el, { padDecimals: false }));
    el.addEventListener('blur', () => _applyUsdFormat(el, { padDecimals: true }));
  });

  // Enter 키로 폼 자동 제출 방지 (data-no-enter-submit 폼 안에서만)
  document.addEventListener(
    'keydown',
    (e) => {
      if (e.key !== 'Enter') return;
      const t = e.target;
      if (!(t instanceof HTMLElement)) return;
      if (t instanceof HTMLTextAreaElement) return;
      if (t instanceof HTMLButtonElement) return;
      if (t instanceof HTMLInputElement) {
        const ty = (t.type || '').toLowerCase();
        if (ty === 'submit' || ty === 'button' || ty === 'image') return;
      }
      const form = t.closest('form');
      if (!form) return;
      if (form.getAttribute('data-no-enter-submit') !== '1') return;
      e.preventDefault();
      e.stopPropagation();
    },
    true
  );
}

/* ── 전역 “처리 중” 오버레이 ─────────────────────────────────────────────────── */

function _busyOverlay() {
  return document.getElementById('global-busy-overlay');
}

function _effectiveUiLang() {
  const el = document.documentElement;
  const eff = (el && el.getAttribute('data-effective-lang')) || '';
  if (eff === 'en' || eff === 'ko') return eff;
  try {
    const stored = localStorage.getItem('lang');
    if (stored === 'en' || stored === 'ko') return stored;
  } catch (_) { /* ignore */ }
  return 'ko';
}

function _syncBusyOverlayLang() {
  const isKo = _effectiveUiLang() === 'ko';
  const root = _busyOverlay();
  if (!root) return;
  root.querySelectorAll('.nav-ko').forEach((el) => {
    el.style.display = isKo ? '' : 'none';
  });
  root.querySelectorAll('.nav-en').forEach((el) => {
    if (el.classList.contains('d-none') && el.childElementCount === 0) {
      el.style.display = 'none';
      return;
    }
    el.style.display = isKo ? 'none' : '';
  });
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

function _hasAgentBrackets(text) {
  return /[「『]/.test(text) && /[」』]/.test(text);
}

/** agent_display.agent_label_ko — 「대외명」 에이전트 */
function _agentKoLabel(raw) {
  const t = (raw || '').trim();
  if (!t) return '';
  if (t.includes('에이전트')) return t;
  if (_hasAgentBrackets(t)) return `${t} 에이전트`;
  return `「${t}」 에이전트`;
}

/** agent_display.agent_label_en — 「Short」 Agent */
function _agentEnLabel(raw) {
  const t = (raw || '').trim();
  if (!t) return '';
  if (/\bAgent\b/i.test(t)) return t;
  if (_hasAgentBrackets(t)) return `${t} Agent`;
  return `「${t}」 Agent`;
}

function _agentSentence(row) {
  const ak = (row.agentKo || '').trim();
  const dk = (row.doingKo || '').trim();
  const ae = (row.agentEn || '').trim();
  const de = (row.doingEn || '').trim();
  const koLabel = _agentKoLabel(ak);
  const enLabel = _agentEnLabel(ae);
  const ko = koLabel && dk ? `${koLabel}가 ${dk}` : dk || koLabel || '';
  const en = enLabel && de ? `${enLabel} is ${de}` : de || enLabel || ko;
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
  const isKo = _effectiveUiLang() === 'ko';
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
      if (listKo && ko && isKo) {
        const li = document.createElement('li');
        li.textContent = ko;
        listKo.appendChild(li);
      }
      if (listEn && en && !isKo) {
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
  _syncBusyOverlayLang();
  el.removeAttribute('hidden');
}

document.addEventListener('DOMContentLoaded', () => {
  initCurrencyAndEnterGuards(document);
  initHubDeliverableVisibilityControls(document);
});

/** FS·개발코드 summary 내 요청자 공개 토글 — 클릭 시 단계 접기/펼치기 방지 */
function initHubDeliverableVisibilityControls(root) {
  const scope = root && root.querySelectorAll ? root : document;
  scope.querySelectorAll('[data-hub-visibility-control]').forEach((el) => {
    if (el.dataset.hubVisibilityBound === '1') return;
    el.dataset.hubVisibilityBound = '1';
    ['click', 'mousedown', 'mouseup', 'pointerdown', 'pointerup'].forEach((type) => {
      el.addEventListener(
        type,
        (e) => {
          e.stopPropagation();
        },
        true
      );
    });
  });
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

function _resolveAppConfirmMessage(i18nKey, legacyMsg, form) {
  let msg = legacyMsg;
  if (form instanceof HTMLFormElement) {
    const lang =
      typeof currentLang !== 'undefined' && currentLang === 'en' ? 'en' : 'ko';
    const localized = form.getAttribute('data-app-confirm-' + lang);
    if (localized != null && String(localized).trim()) {
      return String(localized).trim();
    }
  }
  if ((!msg || !String(msg).trim()) && i18nKey && typeof window.t === 'function') {
    const tr = window.t(i18nKey);
    if (tr != null && typeof tr === 'object' && !Array.isArray(tr)) {
      const body = tr.body != null ? String(tr.body).trim() : '';
      const title = tr.title != null ? String(tr.title).trim() : '';
      return body || title || '';
    }
    if (tr != null && String(tr).trim()) msg = String(tr);
  }
  return msg != null && String(msg).trim() ? String(msg) : '';
}

/**
 * 브라우저 기본 confirm(페이지 출처 표시) 대체 — Bootstrap 모달.
 * @param {string|{title?: string, body?: string}} message
 * @returns {Promise<boolean>}
 */
function appConfirm(message) {
  let text = '';
  if (message != null && typeof message === 'object' && !Array.isArray(message)) {
    text = message.body != null ? String(message.body).trim() : '';
    if (!text && message.title != null) text = String(message.title).trim();
  } else {
    text = message != null && message !== '' ? String(message).trim() : '';
  }
  return new Promise((resolve) => {
    const modalEl = document.getElementById('appConfirmModal');
    if (!modalEl || typeof bootstrap === 'undefined') {
      resolve(window.confirm(text));
      return;
    }
    const body = document.getElementById('appConfirmModalBody');
    if (body) {
      body.style.whiteSpace = 'pre-line';
      body.textContent = text;
    }
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
const _RESTORE_PAGE_SCROLL_KEY = 'restorePageScrollY';
const _SKIP_HUB_PHASE_SCROLL_KEY = 'restoreSkipHubPhaseScroll';
const _SCROLL_AI_CHAT_END_KEY = 'scrollAiChatToEnd';

function scrollAiChatPanelToEnd(panel) {
  if (!panel) return;
  const body = panel.querySelector('.abap-float-chat-body');
  if (!body) return;
  const go = () => {
    body.scrollTop = body.scrollHeight;
  };
  go();
  requestAnimationFrame(go);
}

window.scrollAiChatPanelToEnd = scrollAiChatPanelToEnd;

function _aiChatLang() {
  return (
    document.documentElement.getAttribute('data-effective-lang') ||
    document.documentElement.getAttribute('data-lang') ||
    document.documentElement.lang ||
    'ko'
  );
}

function showAiChatInlineError(panel, message) {
  if (!panel) return;
  const body = panel.querySelector('.abap-float-chat-body');
  if (!body) return;
  let el = body.querySelector('[data-ai-chat-inline-error]');
  if (message) {
    if (!el) {
      el = document.createElement('div');
      el.className = 'alert alert-warning py-2 small mb-3';
      el.dataset.aiChatInlineError = '1';
      body.insertBefore(el, body.firstChild);
    }
    el.textContent = message;
  } else if (el) {
    el.remove();
  }
}

function applyAiChatLogUpdate(panel, root, data) {
  if (!panel) return;
  showAiChatInlineError(panel, '');
  const body = panel.querySelector('.abap-float-chat-body');
  if (!body) return;
  const html = (data && data.log_html) || '';
  const emptyP = body.querySelector('[data-i18n="chat.noThreadsYet"]');
  let logWrap = body.querySelector('.abap-chat-log');
  if (html.trim()) {
    if (emptyP) emptyP.remove();
    if (!logWrap) {
      logWrap = document.createElement('div');
      logWrap.className = 'abap-chat-log abap-chat-log-panel mb-0';
      body.appendChild(logWrap);
    }
    logWrap.innerHTML = html;
  }
  scrollAiChatPanelToEnd(panel);
  const launcher = root && root.querySelector('.abap-float-chat-launcher');
  if (launcher) {
    const n = (data && data.turn_count) || 0;
    let badge = launcher.querySelector('.abap-float-chat-count');
    if (n > 0) {
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'abap-float-chat-count';
        badge.setAttribute('aria-hidden', 'true');
        launcher.appendChild(badge);
      }
      badge.textContent = String(n);
    } else if (badge) {
      badge.remove();
    }
  }
  if (data && data.limit_reached) {
    const form = panel.querySelector('.abap-followup-form');
    if (form) {
      const footer = form.closest('.abap-float-chat-footer');
      const limitMsg =
        _aiChatLang() === 'en'
          ? 'You have reached the follow-up question limit for this request.'
          : '후속 질문 횟수에 도달했습니다.';
      if (footer) {
        footer.innerHTML = `<p class="small text-muted mb-0">${limitMsg}</p>`;
      }
    }
  }
}

async function submitAbapFollowupAjax(form) {
  const panel = form.closest('.abap-float-chat-panel');
  const root = panel && panel.closest('.abap-float-chat');
  const busy = panel && panel.querySelector('.abap-float-chat-local-busy');
  const submitBtn = form.querySelector('button[type="submit"]');
  if (busy) busy.removeAttribute('hidden');
  if (submitBtn) submitBtn.disabled = true;
  const failMsg =
    _aiChatLang() === 'en'
      ? 'Could not send your message. Please try again.'
      : '전송에 실패했습니다. 잠시 후 다시 시도해 주세요.';
  try {
    const res = await fetch(form.action, {
      method: 'POST',
      body: new FormData(form),
      credentials: 'same-origin',
      headers: { 'X-Abap-Ai-Chat': '1', Accept: 'application/json' },
    });
    let data = { ok: false };
    try {
      data = await res.json();
    } catch (_) {
      /* ignore */
    }
    if (!res.ok || !data.ok) {
      showAiChatInlineError(panel, (data && data.error) || failMsg);
      return;
    }
    applyAiChatLogUpdate(panel, root, data);
    const ta = form.querySelector('textarea');
    if (ta) ta.value = '';
  } catch (_) {
    showAiChatInlineError(panel, failMsg);
  } finally {
    if (busy) busy.setAttribute('hidden', '');
    if (submitBtn) submitBtn.disabled = false;
  }
}

function _captureAiFollowupFormContext(form) {
  try {
    sessionStorage.setItem(_RESTORE_PAGE_SCROLL_KEY, String(window.scrollY));
    sessionStorage.setItem(_SCROLL_AI_CHAT_END_KEY, '1');
  } catch (_) {
    /* ignore */
  }
  const hash = (window.location.hash || '').replace(/^#/, '');
  const anchorInput = form.querySelector('[data-hub-anchor-field]');
  if (anchorInput instanceof HTMLInputElement) {
    if (hash && hash.indexOf('-phase-') !== -1) {
      anchorInput.value = hash;
    } else if (!anchorInput.value && hash) {
      anchorInput.value = hash;
    }
  }
  const phaseInput = form.querySelector('input[name="hub_phase"]');
  if (phaseInput instanceof HTMLInputElement && !phaseInput.value) {
    try {
      const ph = new URL(window.location.href).searchParams.get('phase');
      if (ph) phaseInput.value = ph;
    } catch (_) {
      /* ignore */
    }
  }
}

function lockOfferInquiryForm(form) {
  if (!(form instanceof HTMLFormElement)) return false;
  if (form.dataset.offerInquirySubmitting === '1') return false;
  form.dataset.offerInquirySubmitting = '1';
  form.classList.add('offer-inquiry-form--submitting');
  const btn = form.querySelector('button[type="submit"]');
  if (btn) {
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    const spin = btn.querySelector('.offer-inquiry-submit-spinner');
    if (spin) spin.classList.remove('d-none');
  }
  // Do not disable textarea/inputs: disabled controls are omitted from POST body.
  form.querySelectorAll('textarea').forEach((el) => {
    el.readOnly = true;
  });
  const prog = form.querySelector('.offer-inquiry-progress');
  if (prog) {
    const lang =
      document.documentElement.getAttribute('data-lang') ||
      document.documentElement.lang ||
      'ko';
    const msg =
      (lang === 'en' && form.dataset.offerInquiryBusyEn) ||
      form.dataset.offerInquiryBusyKo ||
      form.dataset.offerInquiryBusyEn ||
      '전송 중입니다…';
    prog.innerHTML = `<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>${msg}`;
    prog.classList.remove('d-none');
  }
  return true;
}

document.addEventListener(
  'submit',
  (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.classList.contains('offer-inquiry-form')) {
      if (form.dataset.offerInquirySubmitting === '1') {
        e.preventDefault();
        return;
      }
      lockOfferInquiryForm(form);
      return;
    }
    if (!form.classList.contains('abap-followup-form')) return;
    e.preventDefault();
    e.stopPropagation();
    if (form.dataset.aiChatSubmitting === '1') return;
    form.dataset.aiChatSubmitting = '1';
    submitAbapFollowupAjax(form).finally(() => {
      delete form.dataset.aiChatSubmitting;
    });
  },
  true,
);

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => hoistDraftFloatLaunchers(), {
    once: true,
  });
} else {
  hoistDraftFloatLaunchers();
}

document.addEventListener('DOMContentLoaded', () => {
  let restoredScrollY = null;
  try {
    const rawY = sessionStorage.getItem(_RESTORE_PAGE_SCROLL_KEY);
    if (rawY != null && rawY !== '') {
      sessionStorage.removeItem(_RESTORE_PAGE_SCROLL_KEY);
      sessionStorage.setItem(_SKIP_HUB_PHASE_SCROLL_KEY, '1');
      const y = parseInt(rawY, 10);
      if (!Number.isNaN(y) && y >= 0) restoredScrollY = y;
    }
  } catch (_) {
    /* ignore */
  }

  try {
    const lid = sessionStorage.getItem(_KEEP_AI_LAUNCHER_KEY);
    const scrollChatEnd = sessionStorage.getItem(_SCROLL_AI_CHAT_END_KEY) === '1';
    if (scrollChatEnd) sessionStorage.removeItem(_SCROLL_AI_CHAT_END_KEY);
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
      if (scrollChatEnd && panel) scrollAiChatPanelToEnd(panel);
    }
  } catch (_) {
    /* ignore */
  }

  if (restoredScrollY != null) {
    const y = restoredScrollY;
    const apply = () => window.scrollTo(0, y);
    apply();
    requestAnimationFrame(apply);
    window.setTimeout(apply, 0);
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
      const i18nKey = form.getAttribute('data-app-confirm-i18n');
      const msg = _resolveAppConfirmMessage(
        i18nKey,
        form.getAttribute('data-app-confirm'),
        form,
      );
      if (!msg) return;
      e.preventDefault();
      e.stopPropagation();
      appConfirm(msg).then((ok) => {
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
  hoistDraftFloatLaunchers();

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
        if (p.endsWith('/download') || p.includes('/download/') || p.endsWith('-download')) {
          hideGlobalBusy();
          return;
        }
        if (a.getAttribute('data-skip-global-busy') === '1') {
          hideGlobalBusy();
          return;
        }
        /* Same page, hash-only — in-page phase jump; no full navigation */
        if (
          u.pathname === window.location.pathname &&
          u.hash &&
          u.search === new URL(window.location.href).search
        ) {
          return;
        }
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

  window.addEventListener('load', () => {
    hideGlobalBusy();
  });

  settleRequestConsoleNavBubble();
});

/** 컨설턴트 네비 말풍선: 5회 통통 튀기 후 정지 */
function settleRequestConsoleNavBubble() {
  const BOBBLE_MS = 2600;
  const MAX_ITER = 5;
  document.querySelectorAll('.nav-request-console-bubble').forEach((bubble) => {
    if (!(bubble instanceof HTMLElement)) return;
    if (bubble.dataset.bobbleSettled === '1') return;

    const stop = () => {
      if (bubble.dataset.bobbleSettled === '1') return;
      bubble.dataset.bobbleSettled = '1';
      bubble.classList.add('nav-request-console-bubble--settled');
      bubble.style.animation = 'none';
    };

    bubble.addEventListener(
      'animationend',
      (e) => {
        if (e.animationName === 'nav-request-console-bobble') stop();
      },
      { once: true },
    );
    window.setTimeout(stop, BOBBLE_MS * MAX_ITER + 50);
  });
}

/* 참고·개발 코드 등: 잠금 영역에서 복사/잘라내기 차단(허용 사용자는 .code-asset-locked 없음) */
function _contentDispositionFilename(cd) {
  if (!cd) return '';
  const star = /filename\*=UTF-8''([^;\s]+)/i.exec(cd);
  if (star) {
    try {
      return decodeURIComponent(star[1]);
    } catch (_) {
      return star[1];
    }
  }
  const plain = /filename="([^"]+)"/i.exec(cd);
  return plain ? plain[1] : '';
}

/** 제안서 PDF — fetch 후 blob 저장(리다이렉트 HTML이 .htm 으로 저장되는 문제 방지). */
document.addEventListener(
  'click',
  (e) => {
    const a = e.target.closest('a[data-proposal-pdf-download]');
    if (!a || e.defaultPrevented || e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const href = (a.getAttribute('href') || '').trim();
    if (!href) return;
    e.preventDefault();
    const fallbackName = (a.getAttribute('download') || 'proposal.pdf').trim() || 'proposal.pdf';
    const failMsg =
      typeof window.t === 'function'
        ? window.t('hub.proposalPdfDownloadFailed')
        : 'Could not download the proposal PDF.';
    (async () => {
      try {
        const res = await fetch(href, { credentials: 'same-origin' });
        const ct = (res.headers.get('content-type') || '').toLowerCase();
        if (!res.ok || !ct.includes('application/pdf')) {
          window.alert(failMsg);
          return;
        }
        const blob = await res.blob();
        const name = _contentDispositionFilename(res.headers.get('content-disposition')) || fallbackName;
        const url = URL.createObjectURL(blob);
        const tmp = document.createElement('a');
        tmp.href = url;
        tmp.download = name;
        tmp.rel = 'noopener';
        document.body.appendChild(tmp);
        tmp.click();
        tmp.remove();
        URL.revokeObjectURL(url);
      } catch (_) {
        window.alert(failMsg);
      }
    })();
  },
  true,
);

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
