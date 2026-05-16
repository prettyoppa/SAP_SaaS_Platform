/* 개발코드·FS 생성 시작 전: 드롭존에 대기 중인 FS .md 를 먼저 업로드 */

(function () {
  function uploadUrlForForm(form) {
    const zone = document.querySelector('[data-fs-supplement-dropzone]');
    if (zone && zone.getAttribute('data-upload-url')) {
      return zone.getAttribute('data-upload-url');
    }
    return form.getAttribute('data-fs-upload-url') || '';
  }

  function returnToForForm(form) {
    const zone = document.querySelector('[data-fs-supplement-dropzone]');
    if (zone && zone.getAttribute('data-return-to')) {
      return zone.getAttribute('data-return-to');
    }
    return form.getAttribute('data-fs-return-to') || window.location.pathname + window.location.search + window.location.hash;
  }

  async function preflightThenSubmit(form) {
    const api = window.fsSupplementDropzone;
    if (!api || !api.getPendingFiles || !api.uploadPending) {
      form.submit();
      return;
    }
    const pending = api.getPendingFiles();
    if (!pending.length) {
      form.submit();
      return;
    }
    const uploadUrl = uploadUrlForForm(form);
    if (!uploadUrl) {
      alert('FS 첨부 업로드 경로를 찾을 수 없습니다. 페이지를 새로고침해 주세요.');
      return;
    }
    const btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    try {
      const res = await api.uploadPending(uploadUrl, returnToForForm(form));
      if (!res.ok) {
        alert('FS 첨부 저장에 실패했습니다. 파일 형식(.md)과 용량(파일당 20MB)을 확인해 주세요.');
        if (btn) btn.disabled = false;
        return;
      }
      form.submit();
    } catch (e) {
      alert('FS 첨부 저장 중 오류가 발생했습니다.');
      if (btn) btn.disabled = false;
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-preflight-fs-upload]').forEach(function (form) {
      form.addEventListener('submit', function (ev) {
        const api = window.fsSupplementDropzone;
        if (!api || !api.getPendingFiles) return;
        if (!api.getPendingFiles().length) return;
        ev.preventDefault();
        preflightThenSubmit(form);
      });
    });
  });
})();
