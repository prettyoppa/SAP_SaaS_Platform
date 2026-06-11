/** 홈(/) 공지 팝업 — 오늘 하루 안보기(localStorage) / 닫기(세션) */
(function () {
  var modalEl = document.getElementById('homeNoticePopupModal');
  if (!modalEl || typeof bootstrap === 'undefined' || !bootstrap.Modal) return;

  var noticeId = (modalEl.getAttribute('data-notice-id') || '').trim();
  if (!noticeId) return;

  var hideDayKey = 'home_notice_popup_hide_' + noticeId;
  var sessionKey = 'home_notice_popup_session_' + noticeId;

  function localToday() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  try {
    if (localStorage.getItem(hideDayKey) === localToday()) return;
    if (sessionStorage.getItem(sessionKey) === '1') return;
  } catch (e) {
    /* private mode — still show popup */
  }

  var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  modal.show();

  var hideDayBtn = document.getElementById('homeNoticePopupHideDay');
  if (hideDayBtn) {
    hideDayBtn.addEventListener('click', function () {
      try {
        localStorage.setItem(hideDayKey, localToday());
      } catch (e) { /* ignore */ }
      modal.hide();
    });
  }

  var closeBtn = document.getElementById('homeNoticePopupClose');
  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      try {
        sessionStorage.setItem(sessionKey, '1');
      } catch (e) { /* ignore */ }
    });
  }
})();
