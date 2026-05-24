/**
 * FS·납품 코드 생성 진행 모달 — 제안서 생성 패널과 동일한 단계·아이콘 UX.
 * data-delivery-gen-status-url 폴링. 페이지 로드 시에는 compact hint만 표시하고,
 * .hub-delivery-gen-hint-open 클릭 시 모달을 연다 (auto-show=0).
 */
(function () {
  var LOG_POLL_MS = 2500;

  function activateSteps(container, activeIndex) {
    if (!container) return;
    container.querySelectorAll('.generating-step[data-step-index]').forEach(function (el) {
      var idx = parseInt(el.getAttribute('data-step-index') || '0', 10);
      el.classList.toggle('active', idx === activeIndex);
    });
  }

  function applyJobLogPayload(j) {
    if (!j) return;
    var fsPre = document.getElementById('hubJobLogFs');
    var dcPre = document.getElementById('hubJobLogDc');
    var fsB = document.getElementById('hubJobLogFsBadge');
    var dcB = document.getElementById('hubJobLogDcBadge');
    var fsEmptyKo = '(아직 FS 작업 로그 없음)';
    var fsEmptyEn = '(No FS job log yet)';
    var dcEmptyKo = '(아직 납품 코드 작업 로그 없음)';
    var dcEmptyEn = '(No delivered code job log yet)';
    var lang = document.documentElement.getAttribute('lang') || 'ko';
    var fsEmpty = lang === 'en' ? fsEmptyEn : fsEmptyKo;
    var dcEmpty = lang === 'en' ? dcEmptyEn : dcEmptyKo;
    if (fsPre) {
      fsPre.textContent =
        j.fs_job_log && String(j.fs_job_log).trim() ? j.fs_job_log : fsEmpty;
    }
    if (dcPre) {
      dcPre.textContent =
        j.delivered_job_log && String(j.delivered_job_log).trim()
          ? j.delivered_job_log
          : dcEmpty;
    }
    if (fsB) fsB.textContent = 'fs: ' + (j.fs_status || 'none');
    if (dcB) dcB.textContent = 'code: ' + (j.delivered_code_status || 'none');
  }

  function initJobLogPanel(statusUrl) {
    var logPanel = document.getElementById('hubDeliveryJobLogPanel');
    if (!logPanel || logPanel.dataset.hubLogBound === '1') return null;
    logPanel.dataset.hubLogBound = '1';
    var logTimer = null;

    function isLogPanelOpen() {
      return logPanel && !logPanel.classList.contains('d-none');
    }

    async function pollJobLog() {
      if (!statusUrl) return null;
      try {
        var r = await fetch(statusUrl, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        if (!r.ok) return null;
        var j = await r.json();
        applyJobLogPayload(j);
        return j;
      } catch (e) {
        return null;
      }
    }

    function openDeliveryJobLogPanel() {
      logPanel.classList.remove('d-none');
      logPanel.setAttribute('aria-hidden', 'false');
      pollJobLog();
      if (logTimer) clearInterval(logTimer);
      logTimer = setInterval(pollJobLog, LOG_POLL_MS);
    }

    function closeDeliveryJobLogPanel() {
      logPanel.classList.add('d-none');
      logPanel.setAttribute('aria-hidden', 'true');
      if (logTimer) {
        clearInterval(logTimer);
        logTimer = null;
      }
    }

    logPanel.addEventListener('click', function (e) {
      if (e.target.closest('[data-close-hub-delivery-log="1"]')) {
        closeDeliveryJobLogPanel();
      }
    });

    document.addEventListener(
      'keydown',
      function (e) {
        if (e.key !== 'Escape') return;
        if (isLogPanelOpen()) {
          closeDeliveryJobLogPanel();
          e.stopPropagation();
        }
      },
      true
    );

    return {
      open: openDeliveryJobLogPanel,
      close: closeDeliveryJobLogPanel,
      poll: pollJobLog,
      isOpen: isLogPanelOpen,
    };
  }

  function initModal(modalEl) {
    if (!modalEl || modalEl.dataset.deliveryGenBound === '1') return;
    modalEl.dataset.deliveryGenBound = '1';

    var statusUrl = (modalEl.dataset.deliveryGenStatusUrl || '').trim();
    var fsStart = modalEl.dataset.deliveryGenFsBusy === '1';
    var dcStart = modalEl.dataset.deliveryGenDcBusy === '1';
    var autoShow = modalEl.dataset.deliveryGenAutoShow === '1';

    var jobLog = initJobLogPanel(statusUrl);

    modalEl.querySelectorAll('.hub-delivery-gen-log-open').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (jobLog) jobLog.open();
      });
    });

    var stepsWrap = modalEl.querySelector('.hub-delivery-gen-steps');
    var pipeline = stepsWrap ? stepsWrap.getAttribute('data-pipeline') || '' : '';
    if (!pipeline && dcStart) pipeline = 'dc';
    if (!pipeline && fsStart) pipeline = 'fs';
    var stepCount = pipeline === 'dc' ? 3 : 1;
    var stepIdx = 0;
    var animTimer = null;

    if (stepsWrap && stepCount > 1) {
      var elapsed = 0;
      animTimer = setInterval(function () {
        elapsed += 1;
        if (elapsed % 25 === 0 && stepIdx < stepCount - 1) {
          stepIdx++;
          activateSteps(stepsWrap, stepIdx);
        }
      }, 1000);
    }

    async function fetchStatus() {
      if (!statusUrl) return null;
      try {
        var r = await fetch(statusUrl, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        if (!r.ok) return null;
        var j = await r.json();
        if (jobLog && jobLog.isOpen()) applyJobLogPayload(j);
        return j;
      } catch (e) {
        return null;
      }
    }

    async function checkDone() {
      var j = await fetchStatus();
      if (!j) return false;
      var fsSt = String(j.fs_status || '').trim();
      var dcSt = String(j.delivered_code_status || '').trim();
      if (fsStart && fsSt === 'generating') return false;
      if (dcStart && dcSt === 'generating') return false;
      return true;
    }

    function onDone() {
      if (animTimer) clearInterval(animTimer);
      window.location.reload();
    }

    if (statusUrl) {
      checkDone().then(function (done) {
        if (done) onDone();
      });
      setInterval(async function () {
        if (await checkDone()) onDone();
      }, 5000);
    }

    if (autoShow && typeof bootstrap !== 'undefined') {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  function bindHintButtons() {
    document.querySelectorAll('.hub-delivery-gen-hint-open').forEach(function (btn) {
      if (btn.dataset.deliveryGenHintBound === '1') return;
      btn.dataset.deliveryGenHintBound = '1';
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-delivery-gen-modal') || 'hubDeliveryProgressModal';
        var modal = document.getElementById(id);
        if (!modal || typeof bootstrap === 'undefined') return;
        bootstrap.Modal.getOrCreateInstance(modal).show();
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (typeof hideGlobalBusy === 'function') hideGlobalBusy();
    document.querySelectorAll('.hub-delivery-gen-modal').forEach(initModal);
    bindHintButtons();
  });
})();
