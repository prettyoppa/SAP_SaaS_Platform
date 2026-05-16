/* 컨설턴트 FS .md 첨부 — 요청서 첨부와 동일한 드래그·드롭·파일 선택 UX */

(function () {
  function setFilesOnInput(input, files) {
    const list = Array.from(files || []).filter(function (f) { return f && f.name && f.size > 0; });
    const dt = new DataTransfer();
    list.forEach(function (f) {
      try {
        dt.items.add(f);
      } catch (_) {
        try {
          const body = f.size > 0 ? f.slice(0, f.size) : new Blob();
          dt.items.add(new File([body], f.name, { type: f.type || 'text/markdown', lastModified: f.lastModified }));
        } catch (e2) {
          console.warn('fs supplement: skip', f.name, e2);
        }
      }
    });
    input.files = dt.files;
  }

  function renderFsStagingRows(zone, input, maxFiles) {
    const listEl = zone.querySelector('[data-fs-staging-list]');
    const hit = zone.querySelector('[data-fs-drop-hit]');
    const dropContent = zone.querySelector('[data-fs-drop-content]');
    if (!listEl || !input) return;

    const files = Array.from(input.files || []);
    listEl.innerHTML = '';
    if (!files.length) {
      if (hit) hit.classList.remove('d-none');
      else if (dropContent) dropContent.classList.remove('d-none');
      return;
    }
    if (hit) hit.classList.add('d-none');
    else if (dropContent) dropContent.classList.add('d-none');

    files.forEach(function (file, i) {
      const row = document.createElement("div");
      row.className = 'rfp-attachment-row d-flex flex-wrap align-items-center gap-2 w-100 py-2 border-bottom';
      row.style.borderColor = 'var(--border)';

      const nameEl = document.createElement('span');
      nameEl.className = 'flex-grow-1 text-break small fw-medium';
      nameEl.textContent = file.name + ' (개발코드 생성 시 저장)';

      const rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'btn btn-sm btn-outline-danger flex-shrink-0';
      rm.textContent = '제거';
      rm.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const next = Array.from(input.files).filter(function (_, j) { return j !== i; });
        setFilesOnInput(input, next);
        renderFsStagingRows(zone, input, maxFiles);
      });

      row.appendChild(nameEl);
      row.appendChild(rm);
      listEl.appendChild(row);
    });
  }

  function initZone(zone) {
    const input = zone.querySelector('[data-fs-file-input]');
    if (!input) return;
    const maxFiles = parseInt(zone.getAttribute('data-max-files') || '15', 10) || 15;

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
      const incoming = Array.from(e.dataTransfer.files || []).filter(function (f) {
        return f && f.name && f.size > 0;
      });
      if (!incoming.length) return;
      const existing = Array.from(input.files || []);
      const merged = existing.concat(incoming).slice(0, maxFiles);
      setFilesOnInput(input, merged);
      renderFsStagingRows(zone, input, maxFiles);
    });

    input.addEventListener('change', function () {
      const picked = Array.from(input.files || []).filter(function (f) {
        return f && f.name && f.size > 0;
      }).slice(0, maxFiles);
      setFilesOnInput(input, picked);
      renderFsStagingRows(zone, input, maxFiles);
    });

    renderFsStagingRows(zone, input, maxFiles);
  }

  function getStagingInput() {
    const zone = document.querySelector('[data-fs-supplement-dropzone]');
    return zone ? zone.querySelector('[data-fs-file-input]') : null;
  }

  function getPendingFiles() {
    const input = getStagingInput();
    if (!input) return [];
    return Array.from(input.files || []).filter(function (f) {
      return f && f.name && f.size > 0 && (f.name || '').toLowerCase().endsWith('.md');
    });
  }

  function clearStaging() {
    const input = getStagingInput();
    const zone = document.querySelector('[data-fs-supplement-dropzone]');
    if (!input || !zone) return;
    setFilesOnInput(input, []);
    const maxFiles = parseInt(zone.getAttribute('data-max-files') || '15', 10) || 15;
    renderFsStagingRows(zone, input, maxFiles);
  }

  async function uploadPending(uploadUrl, returnTo) {
    const files = getPendingFiles();
    if (!files.length) return { ok: true, uploaded: 0 };
    const fd = new FormData();
    files.forEach(function (f) { fd.append('files', f, f.name); });
    if (returnTo) fd.append('return_to', returnTo);
    const r = await fetch(uploadUrl, {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      redirect: 'manual',
    });
    if (r.type === 'opaqueredirect' || (r.status >= 300 && r.status < 400) || r.ok) {
      clearStaging();
      return { ok: true, uploaded: files.length };
    }
    return { ok: false, uploaded: 0, status: r.status };
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-fs-supplement-dropzone]').forEach(initZone);
  });

  window.fsSupplementDropzone = {
    getPendingFiles: getPendingFiles,
    uploadPending: uploadPending,
    clearStaging: clearStaging,
  };
})();
