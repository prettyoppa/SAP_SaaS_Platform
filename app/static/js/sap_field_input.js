/**
 * SAP 프로그램 ID / 트랜잭션 코드 입력 공통
 * - CJK: beforeinput 차단 + 메시지 (기존 유효 문자 유지)
 * - 붙여넣기: CJK 제거 후 메시지
 * - 소문자 → 대문자, ASCII 인쇄 가능 문자만
 */
(function (global) {
  'use strict';

  var RFP_CJK = /[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]/;
  var MSG_CJK =
    '한글·일본어·중국어는 입력할 수 없습니다. 영문·숫자·기호(공백 제외)만 사용해 주세요.';
  var MSG_BAD = '허용되지 않는 문자가 있습니다. 인쇄되는 영문·숫자·기호만 사용할 수 있습니다.';

  function initSapPidTcodePair(opts) {
    var pid = opts.programEl;
    var tc = opts.transactionEl;
    var fbPid = opts.feedbackPid;
    var fbTc = opts.feedbackTc;
    var maxPid = opts.maxPid || 40;
    var maxTc = opts.maxTc || 20;
    var mirrorTc = !!opts.mirrorTc;
    var onChange = opts.onChange || function () {};

    if (!pid || !tc) return;

    var tcTouched = (tc.value || '').trim().length > 0;

    function refreshTcCopy() {
      if (!mirrorTc) return;
      var p = pid.value.trim();
      if (!tcTouched && p) {
        tc.value = p
          .toUpperCase()
          .replace(/[^\x21-\x7E]/g, '')
          .slice(0, maxTc);
      }
    }

    function runOne(el, fb, maxLen, isTc) {
      if (isTc) tcTouched = (tc.value || '').trim().length > 0;

      var msg = '';
      var raw = el.value;
      if (RFP_CJK.test(raw)) {
        el.value = raw.replace(RFP_CJK, '');
        msg = MSG_CJK;
      }
      el.value = el.value.replace(/[a-z]/g, function (c) {
        return c.toUpperCase();
      });
      var cleaned = el.value.replace(/[^\x21-\x7E]/g, '');
      if (cleaned !== el.value) {
        el.value = cleaned;
        if (!msg) msg = MSG_BAD;
      }
      if (el.value.length > maxLen) {
        el.value = el.value.slice(0, maxLen);
        msg = maxLen + '자 이내로 입력해 주세요.';
      }
      if (fb) fb.textContent = msg;

      if (isTc) tcTouched = (tc.value || '').trim().length > 0;
      refreshTcCopy();
      onChange();
    }

    pid.addEventListener('beforeinput', function (e) {
      if (e.isComposing) return;
      if (e.data && RFP_CJK.test(e.data)) {
        e.preventDefault();
        if (fbPid) fbPid.textContent = MSG_CJK;
      }
    });
    tc.addEventListener('beforeinput', function (e) {
      if (e.isComposing) return;
      if (e.data && RFP_CJK.test(e.data)) {
        e.preventDefault();
        if (fbTc) fbTc.textContent = MSG_CJK;
      }
    });

    pid.addEventListener('input', function () {
      runOne(pid, fbPid, maxPid, false);
    });
    tc.addEventListener('input', function () {
      runOne(tc, fbTc, maxTc, true);
    });

    pid.addEventListener('compositionend', function () {
      runOne(pid, fbPid, maxPid, false);
    });
    tc.addEventListener('compositionend', function () {
      runOne(tc, fbTc, maxTc, true);
    });

    pid.addEventListener('paste', function () {
      setTimeout(function () {
        runOne(pid, fbPid, maxPid, false);
      }, 0);
    });
    tc.addEventListener('paste', function () {
      setTimeout(function () {
        runOne(tc, fbTc, maxTc, true);
      }, 0);
    });

    pid.addEventListener('blur', refreshTcCopy);

    if (mirrorTc && (pid.value || '').trim() && !(tc.value || '').trim()) {
      refreshTcCopy();
    }
  }

  global.initSapPidTcodePair = initSapPidTcodePair;
  global.SAP_FIELD_MSG_CJK = MSG_CJK;
})(typeof window !== 'undefined' ? window : this);
