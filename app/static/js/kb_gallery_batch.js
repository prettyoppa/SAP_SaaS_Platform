/**
 * 지식갤러리 키워드 일괄 초안 — 백그라운드 작업 폴링·중지(키워드 배치만).
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
    if (j.cancelled) base += ' · 중지됨';
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
    if (j.cancelled) base += ' · stopped';
    return base;
  }

  function initModal(modalEl) {
    if (!modalEl || modalEl.dataset.kbBatchBound === '1') return;
    modalEl.dataset.kbBatchBound = '1';
    var statusUrl = (modalEl.dataset.kbBatchStatusUrl || '').trim();
    var cancelUrl = (modalEl.dataset.kbBatchCancelUrl || '').trim();
    var progressEl = modalEl.querySelector('.kb-batch-progress-line');
    var stopBtn = modalEl.querySelector('.kb-batch-stop-btn');
    var autoShow = modalEl.dataset.kbBatchAutoShow === '1';
    var pollTimer = null;
    var stopRequested = false;

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
      if (stopBtn) {
        var hide =
          !j.can_cancel || j.done || stopRequested || j.cancelled;
        stopBtn.disabled = hide;
        stopBtn.classList.toggle('d-none', hide && !stopRequested);
      }
    }

    function redirectDone(j) {
      var q =
        '/admin/kb?view=new&generate_ok=' +
        encodeURIComponent(String(j.ok_count || 0)) +
        '&generate_fail=' +
        encodeURIComponent(String(j.fail_count || 0));
      if (j.cancelled) q += '&generate_cancelled=1';
      if (j.errors) q += '&generate_errors=' + encodeURIComponent(String(j.errors).slice(0, 1500));
      window.location.href = q;
    }

    function onTerminal(j) {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      redirectDone(j);
    }

    if (stopBtn && cancelUrl) {
      stopBtn.addEventListener('click', function () {
        var msgKo =
          '이미 완료된 초안은 유지하고, 남은 키워드만 생성을 중지합니다. 진행 중인 키워드 1건은 API가 끝날 때까지 계속될 수 있습니다. 계속할까요?';
        var msgEn =
          'Completed drafts stay saved; only remaining keywords are skipped. The keyword currently in flight may finish its API call. Continue?';
        var msg =
          typeof window.t === 'function'
            ? window.t('admin.kb.confirmBatchStop')
            : msgKo;
        var go = function () {
          stopRequested = true;
          stopBtn.disabled = true;
          fetch(cancelUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              Accept: 'application/json',
              'Content-Type': 'application/json',
            },
            body: '{}',
          })
            .then(function (r) {
              return r.json().catch(function () {
                return {};
              });
            })
            .then(function () {
              return fetchStatus();
            })
            .then(function (j) {
              if (j) updateLine(j);
            })
            .catch(function () {
              stopRequested = false;
              if (stopBtn) stopBtn.disabled = false;
            });
        };
        if (typeof window.appConfirm === 'function') {
          window.appConfirm(msg).then(function (ok) {
            if (ok) go();
          });
        } else if (window.confirm(msgKo || msg)) {
          go();
        }
      });
    }

    if (statusUrl) {
      fetchStatus().then(function (j) {
        if (j) updateLine(j);
        if (j && j.done) onTerminal(j);
      });
      pollTimer = setInterval(async function () {
        var j = await fetchStatus();
        if (!j) return;
        updateLine(j);
        if (j.done) onTerminal(j);
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
