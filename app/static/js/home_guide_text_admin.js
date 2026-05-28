/**
 * Admin bilingual fields — single visible control, KO/EN in hidden inputs; syncs with site lang toggle.
 */
(function () {
  'use strict';

  function currentLang() {
    return localStorage.getItem('lang') === 'en' ? 'en' : 'ko';
  }

  function initRoot(root) {
    if (!root || root.dataset.bilingualAdminBound === '1') return;
    root.dataset.bilingualAdminBound = '1';

    var editor = root.querySelector('[data-bilingual-editor]');
    var hidKo = root.querySelector('[data-bilingual-ko]');
    var hidEn = root.querySelector('[data-bilingual-en]');
    if (!editor || !hidKo || !hidEn) return;

    var store = {
      ko: hidKo.value != null ? String(hidKo.value) : '',
      en: hidEn.value != null ? String(hidEn.value) : '',
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

    root.bilingualAdminSync = syncHidden;
    return syncHidden;
  }

  function boot() {
    document.querySelectorAll('[data-bilingual-admin-root]').forEach(initRoot);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.homeGuideTextAdminSyncAll = function () {
    document.querySelectorAll('[data-bilingual-admin-root]').forEach(function (root) {
      if (typeof root.bilingualAdminSync === 'function') root.bilingualAdminSync();
    });
  };
})();
