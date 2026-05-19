/**
 * 지식갤러리 키워드 일괄 초안 — 백그라운드 작업 폴링.
 */
(function () {
  function progressText(j) {
    var ok = j.ok_count || 0;
    var fail = j.fail_count || 0;
    var total = j.total || 0;
    var cur = (j.current_keyword || '').trim();
    var base = '완료 ' + ok + ' / ' + total;
    if (fail) base += ' · 실패 ' + fail;
    if (cur) base += ' · 진행: ' + cur;
    return base;
  }

  function progressTextEn(j) {
    var ok = j.ok_count || 0;
    var fail = j.fail_count || 0;
    var total = j.total || 0;
    var cur = (j.current_keyword || '').trim();
    var base = 'Done ' + ok + ' / ' + total;
    if (fail) base += ' · failed ' + fail;
    if (cur) base += ' · now: ' + cur;
    return base;
  }

  function initModal(modalEl) {
    if (!modalEl || modalEl.dataset.kbBatchBound === '1') return;
    modalEl.dataset.kbBatchBound = '1';
    var statusUrl = (modalEl.dataset.kbBatchStatusUrl || '').trim();
    var progressEl = modalEl.querySelector('.kb-batch-progress-line');
    var autoShow = modalEl.dataset.kbBatchAutoShow === '1';

    async function fetchStatus() {
      if (!statusUrl) return null;
      try {
        var r = await fetch(statusUrl, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        if (!r.ok) return null;
        return await r.json();
      } catch (e) {
        return null;
      }
    }

    function updateLine(j) {
      if (!progressEl || !j) return;
      var ko = progressText(j);
      var en = progressTextEn(j);
      progressEl.innerHTML =
        '<span class="nav-ko">' +
        ko +
        '</span><span class="nav-en" style="display:none">' +
        en +
        '</span>';
    }

    function onDone(j) {
      var q =
        '/admin/kb?generate_ok=' +
        encodeURIComponent(String(j.ok_count || 0)) +
        '&generate_fail=' +
        encodeURIComponent(String(j.fail_count || 0));
      if (j.errors) q += '&generate_errors=' + encodeURIComponent(String(j.errors).slice(0, 1500));
      window.location.href = q;
    }

    if (statusUrl) {
      fetchStatus().then(function (j) {
        if (j) updateLine(j);
        if (j && j.done) onDone(j);
      });
      setInterval(async function () {
        var j = await fetchStatus();
        if (!j) return;
        updateLine(j);
        if (j.done) onDone(j);
      }, 4000);
    }

    if (autoShow && typeof bootstrap !== 'undefined') {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.kb-gallery-batch-modal').forEach(initModal);
  });
})();
