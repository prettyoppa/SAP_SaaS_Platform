/* 요청자 제안서 .md 첨부 — 선택 시 즉시 서버 저장 */

(function () {
  var ERR_MSG = {
    prop_bad_ext: 'Markdown(.md) 파일만 업로드할 수 있습니다.',
    prop_too_large: '파일당 최대 20MB까지 업로드할 수 있습니다.',
    prop_upload_limit: '요청당 첨부는 최대 15개까지입니다.',
    prop_upload_batch_limit: '한 번에 최대 15개까지 선택할 수 있습니다.',
    prop_upload_empty: '업로드할 파일이 없습니다.',
    prop_upload_no_name: '파일 이름을 확인할 수 없습니다.',
  };

  function setStatus(zone, text, isError) {
    var el = zone.querySelector('[data-proposal-upload-status]');
    if (!el) return;
    el.textContent = text || '';
    el.classList.toggle('text-danger', !!isError);
    el.classList.toggle('text-muted', !isError);
  }

  function uploadFiles(zone, files) {
    var uploadUrl = zone.getAttribute('data-upload-url');
    var returnTo = zone.getAttribute('data-return-to') || '';
    if (!uploadUrl || !files.length) return Promise.resolve();

    setStatus(zone, '저장 중…', false);
    var fd = new FormData();
    Array.from(files).forEach(function (f) {
      fd.append('files', f, f.name);
    });
    if (returnTo) fd.append('return_to', returnTo);

    return fetch(uploadUrl, {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'fetch' },
    })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, body: j };
        });
      })
      .then(function (res) {
        if (!res.ok || !res.body || !res.body.ok) {
          var code = (res.body && res.body.error) || '';
          setStatus(zone, ERR_MSG[code] || '저장에 실패했습니다. 다시 시도해 주세요.', true);
          return;
        }
        setStatus(zone, res.body.uploaded + '개 파일을 저장했습니다.', false);
        window.location.reload();
      })
      .catch(function () {
        setStatus(zone, '저장 중 오류가 발생했습니다.', true);
      });
  }

  function filterMd(files) {
    return Array.from(files || []).filter(function (f) {
      return f && f.name && f.size > 0 && /\.md$/i.test(f.name);
    });
  }

  function initZone(zone) {
    var input = zone.querySelector('[data-proposal-file-input]');
    if (!input) return;
    var maxFiles = parseInt(zone.getAttribute('data-max-files') || '15', 10) || 15;

    function onPick(fileList) {
      var picked = filterMd(fileList).slice(0, maxFiles);
      if (!picked.length) {
        setStatus(zone, 'Markdown(.md) 파일을 선택해 주세요.', true);
        return;
      }
      uploadFiles(zone, picked);
      try {
        input.value = '';
      } catch (_) {}
    }

    ['dragenter', 'dragover'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.add('dragover');
      });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        e.preventDefault();
        e.stopPropagation();
        zone.classList.remove('dragover');
      });
    });

    zone.addEventListener('drop', function (e) {
      onPick(e.dataTransfer.files);
    });

    input.addEventListener('change', function () {
      onPick(input.files);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-proposal-supplement-dropzone]').forEach(initZone);
  });
})();
