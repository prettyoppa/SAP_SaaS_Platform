(function () {
  function shouldFocusSection6Interview() {
    try {
      var hash = (window.location.hash || '').replace(/^#/, '');
      if (hash === 'proposal-section6-interview') return true;
      var params = new URLSearchParams(window.location.search);
      if (params.has('section6_interview')) return true;
      if (params.get('section6_decisions') === 'ok') return true;
    } catch (e) {}
    return false;
  }
  window.section6InterviewShouldFocus = shouldFocusSection6Interview;

  function focusSection6InterviewPanel() {
    if (!shouldFocusSection6Interview()) return;
    var phaseIds = ['rfp-phase-proposal', 'int-phase-proposal', 'abap-phase-proposal'];
    for (var i = 0; i < phaseIds.length; i++) {
      var phase = document.getElementById(phaseIds[i]);
      if (phase && phase.tagName === 'DETAILS') phase.open = true;
    }
    var root = document.getElementById('proposal-section6-interview');
    if (!root) return;
    var details = root.querySelector('.proposal-section6-interview-details');
    if (details && details.tagName === 'DETAILS') details.open = true;
    root.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      setTimeout(focusSection6InterviewPanel, 80);
    });
  } else {
    setTimeout(focusSection6InterviewPanel, 80);
  }

  var UI = window.InterviewSuggestionUI;
  function buildPayload() {
    var ta = document.getElementById('s6-seq-answer-input');
    var free = ta ? (ta.value || '').trim() : '';
    if (UI) {
      var p = UI.buildPayloadFromRows(document.querySelectorAll('.interview-suggestion-row'));
      p.free = free;
      return p;
    }
    return { v: 1, like: [], dislike: [], free: free };
  }
  function parseS6Json(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent || 'null'); } catch (e) { return null; }
  }
  function isPayloadValid(p) {
    if (!UI) {
      if (!p) return false;
      var text = '';
      if (p.like && p.like.length) text += p.like.join(' ');
      if (p.dislike && p.dislike.length) text += p.dislike.join(' ');
      if (p.free) text += p.free;
      return text.replace(/\s/g, '').length >= 2;
    }
    var groups = parseS6Json('s6-answer-suggestion-groups-data') || [];
    var enabledEl = parseS6Json('s6-interview-suggestion-groups-enabled');
    var groupsEnabled = enabledEl === true || enabledEl === 'true';
    return !UI.validatePayload(p, groupsEnabled ? groups : null, p.free || '');
  }
  function syncHiddenPayload() {
    var hid = document.getElementById('s6-answer-payload-json');
    if (hid) hid.value = JSON.stringify(buildPayload());
  }

  var suggHost = document.getElementById('s6-answer-suggestion-rows');
  var seqIn = document.getElementById('s6-seq-answer-input');
  if (UI && suggHost && seqIn) {
    var flatItems = parseS6Json('s6-answer-suggestions-data') || [];
    var groups = parseS6Json('s6-answer-suggestion-groups-data') || [];
    var enabledEl = parseS6Json('s6-interview-suggestion-groups-enabled');
    var groupsEnabled = enabledEl === true || enabledEl === 'true';
    var draft = parseS6Json('s6-interview-draft-payload') || { v: 1, like: [], dislike: [], free: '' };
    if ((groupsEnabled && groups.length) || (flatItems && flatItems.length)) {
      UI.mount({
        hostId: 's6-answer-suggestion-rows',
        groupsEnabled: groupsEnabled,
        groups: groups,
        flatItems: flatItems,
        draft: draft,
        onSync: syncHiddenPayload,
      });
    }
  }
  if (seqIn) seqIn.addEventListener('input', syncHiddenPayload);
  syncHiddenPayload();

  var seqForm = document.getElementById('s6-iv-seq-form');
  var seqBtn = document.getElementById('s6-seq-next-btn');
  if (seqForm && seqBtn) {
    seqForm.addEventListener('submit', function (e) {
      syncHiddenPayload();
      var p = buildPayload();
      if (!isPayloadValid(p)) {
        e.preventDefault();
        if (UI) alert(UI.alertForCode(UI.validatePayload(p, parseS6Json('s6-answer-suggestion-groups-data') || [], p.free || '') || 'empty'));
        else alert(typeof window.t === 'function' ? window.t('interview.suggest.needAnswer') : '좋아요·싫어요로 선택하거나, 보충/추가 란에 2자 이상 입력해 주세요.');
        return;
      }
      seqBtn.disabled = true;
    });
  }
})();
