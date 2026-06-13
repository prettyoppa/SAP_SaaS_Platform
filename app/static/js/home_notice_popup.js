/** 홈(/) 공지 팝업 — 최대 2건, 오늘 하루 안보기(localStorage) / 닫기(세션) */
(function () {
  var layer = document.getElementById('homeNoticePopupLayer');
  if (!layer) return;

  var cards = layer.querySelectorAll('.home-notice-popup-card');
  if (!cards.length) return;

  function localToday() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  function storageKeys(noticeId) {
    return {
      hideDay: 'home_notice_popup_hide_' + noticeId,
      session: 'home_notice_popup_session_' + noticeId,
    };
  }

  function shouldShow(noticeId) {
    try {
      var keys = storageKeys(noticeId);
      if (localStorage.getItem(keys.hideDay) === localToday()) return false;
      if (sessionStorage.getItem(keys.session) === '1') return false;
    } catch (e) {
      /* private mode — still show popup */
    }
    return true;
  }

  function hideCard(card) {
    card.classList.add('d-none');
    card.setAttribute('aria-hidden', 'true');
    if (!layer.querySelector('.home-notice-popup-card:not(.d-none)')) {
      closeLayer();
    }
  }

  function closeLayer() {
    layer.classList.remove('is-open');
    layer.setAttribute('hidden', '');
    document.body.classList.remove('home-notice-popup-open');
  }

  function openLayer() {
    layer.removeAttribute('hidden');
    layer.classList.add('is-open');
    document.body.classList.add('home-notice-popup-open');
  }

  function dismissNotice(noticeId, mode) {
    try {
      var keys = storageKeys(noticeId);
      if (mode === 'day') {
        localStorage.setItem(keys.hideDay, localToday());
      } else {
        sessionStorage.setItem(keys.session, '1');
      }
    } catch (e) { /* ignore */ }
  }

  var visibleCount = 0;
  cards.forEach(function (card) {
    var noticeId = (card.getAttribute('data-notice-id') || '').trim();
    if (!noticeId || !shouldShow(noticeId)) {
      card.classList.add('d-none');
      card.setAttribute('aria-hidden', 'true');
      return;
    }
    visibleCount += 1;
  });

  if (!visibleCount) return;

  openLayer();

  layer.addEventListener('click', function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;

    var hideDayBtn = target.closest('.home-notice-popup-hide-day');
    if (hideDayBtn) {
      var hideId = (hideDayBtn.getAttribute('data-notice-id') || '').trim();
      if (!hideId) return;
      dismissNotice(hideId, 'day');
      var hideCardEl = layer.querySelector('.home-notice-popup-card[data-notice-id="' + hideId + '"]');
      if (hideCardEl) hideCard(hideCardEl);
      return;
    }

    var closeBtn = target.closest('.home-notice-popup-close, .home-notice-popup-dismiss');
    if (closeBtn) {
      var closeId = (closeBtn.getAttribute('data-notice-id') || '').trim();
      if (!closeId) return;
      dismissNotice(closeId, 'session');
      var closeCardEl = layer.querySelector('.home-notice-popup-card[data-notice-id="' + closeId + '"]');
      if (closeCardEl) hideCard(closeCardEl);
    }
  });
})();
