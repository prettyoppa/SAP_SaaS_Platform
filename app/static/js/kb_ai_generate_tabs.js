/**
 * 지식갤러리 AI 초안 — 키워드 / 키노트 탭 전환.
 */
(function () {
  'use strict';

  var form = document.getElementById('kb-ai-generate-form');
  if (!form) return;

  var modeInput = document.getElementById('kb-ai-source-mode');
  var paneKw = document.getElementById('kb-ai-pane-keywords');
  var paneNote = document.getElementById('kb-ai-pane-keynote');
  var taKw = document.getElementById('kb-ai-keywords');
  var taNote = document.getElementById('kb-ai-keynote');
  var tabs = document.querySelectorAll('#kb-ai-source-tabs [data-kb-ai-mode]');

  function setMode(mode) {
    var isKeynote = mode === 'keynote';
    if (modeInput) modeInput.value = isKeynote ? 'keynote' : 'keywords';
    if (paneKw) paneKw.classList.toggle('d-none', isKeynote);
    if (paneNote) paneNote.classList.toggle('d-none', !isKeynote);
    if (taKw) {
      taKw.disabled = isKeynote;
      if (isKeynote) taKw.removeAttribute('name');
      else taKw.setAttribute('name', 'keywords');
    }
    if (taNote) {
      taNote.disabled = !isKeynote;
      if (isKeynote) taNote.setAttribute('name', 'keynote');
      else taNote.removeAttribute('name');
    }
    form.setAttribute(
      'data-app-confirm-i18n',
      isKeynote ? form.getAttribute('data-app-confirm-i18n-keynote') || 'admin.kb.confirmGenerateKeynote' : 'admin.kb.confirmGenerate'
    );
    tabs.forEach(function (btn) {
      var active = btn.getAttribute('data-kb-ai-mode') === mode;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }

  tabs.forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      setMode(btn.getAttribute('data-kb-ai-mode') || 'keywords');
    });
  });

  setMode((modeInput && modeInput.value) || 'keywords');
})();
