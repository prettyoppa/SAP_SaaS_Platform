/**
 * 홈 사용 안내 Markdown — 단일 textarea, 사이트 KO/EN 토글과 연동.
 */
(function () {
  'use strict';

  function currentLang() {
    return localStorage.getItem('lang') === 'en' ? 'en' : 'ko';
  }

  function initRoot(root) {
    if (!root || root.dataset.homeGuideTextBound === '1') return;
    root.dataset.homeGuideTextBound = '1';

    var editor = root.querySelector('[data-home-guide-text-editor]');
    var hidKo = root.querySelector('[data-home-guide-text-ko]');
    var hidEn = root.querySelector('[data-home-guide-text-en]');
    if (!editor || !hidKo || !hidEn) return;

    var store = {
      ko: hidKo.value || '',
      en: hidEn.value || '',
    };
    var activeLang = currentLang();

    function flushEditor() {
      store[activeLang] = editor.value;
    }

    function applyLang(lang) {
      flushEditor();
      activeLang = lang === 'en' ? 'en' : 'ko';
      editor.value = store[activeLang] || '';
    }

    function syncHidden() {
      flushEditor();
      hidKo.value = store.ko || '';
      hidEn.value = store.en || '';
    }

    applyLang(activeLang);

    editor.addEventListener('input', function () {
      store[activeLang] = editor.value;
    });

    document.addEventListener('app:langchange', function (ev) {
      var lang = (ev && ev.detail && ev.detail.lang) || currentLang();
      applyLang(lang);
    });

    var form = root.closest('form');
    if (form) {
      form.addEventListener('submit', syncHidden);
    }

    root.homeGuideTextSync = syncHidden;
    return syncHidden;
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-home-guide-text-md-root]').forEach(initRoot);
  });

  window.homeGuideTextAdminSyncAll = function () {
    document.querySelectorAll('[data-home-guide-text-md-root]').forEach(function (root) {
      if (typeof root.homeGuideTextSync === 'function') root.homeGuideTextSync();
    });
  };
})();
