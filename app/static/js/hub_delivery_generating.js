/**
 * FS·납품 코드 생성 진행 모달 — 제안서 생성 패널과 동일한 단계·아이콘 UX.
 * data-delivery-gen-status-url 폴링, .hub-delivery-gen-hint-open 으로 모달 재오픈.
 */
(function () {
  function activateSteps(container, activeIndex) {
    if (!container) return;
    container.querySelectorAll('.generating-step[data-step-index]').forEach(function (el) {
      var idx = parseInt(el.getAttribute('data-step-index') || '0', 10);
      el.classList.toggle('active', idx === activeIndex);
    });
  }

  function initModal(modalEl) {
    if (!modalEl || modalEl.dataset.deliveryGenBound === '1') return;
    modalEl.dataset.deliveryGenBound = '1';

    var statusUrl = (modalEl.dataset.deliveryGenStatusUrl || '').trim();
    var fsStart = modalEl.dataset.deliveryGenFsBusy === '1';
    var dcStart = modalEl.dataset.deliveryGenDcBusy === '1';
    var autoShow = modalEl.dataset.deliveryGenAutoShow === '1';

    var stepsWrap = modalEl.querySelector('.hub-delivery-gen-steps');
    var pipeline = stepsWrap ? stepsWrap.getAttribute('data-pipeline') || '' : '';
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

    async function checkDone() {
      if (!statusUrl) return false;
      try {
        var r = await fetch(statusUrl, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        if (!r.ok) return false;
        var j = await r.json();
        var fsSt = String(j.fs_status || '').trim();
        var dcSt = String(j.delivered_code_status || '').trim();
        if (fsStart && fsSt === 'generating') return false;
        if (dcStart && dcSt === 'generating') return false;
        return true;
      } catch (e) {
        return false;
      }
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
    document.querySelectorAll('.hub-delivery-gen-modal').forEach(initModal);
    bindHintButtons();
  });
})();
