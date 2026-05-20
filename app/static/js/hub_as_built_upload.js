/**
 * 최종 구현 산출물 — 단일 파일 드래그·드롭 (요청 폼 첨부 UI와 동일 패턴).
 */
(function () {
  function setFilesOnInput(input, files) {
    try {
      const dt = new DataTransfer();
      (files || []).forEach(f => {
        if (f && f.name && f.size > 0) dt.items.add(f);
      });
      input.files = dt.files;
    } catch (e) {
      /* ignore */
    }
  }

  function renderRow(input, listEl, hit, dropContent) {
    const files = Array.from(input.files || []).filter(f => f && f.name && f.size > 0);
    if (!listEl) return;
    listEl.innerHTML = '';
    if (!files.length) {
      if (hit) hit.classList.remove('d-none');
      else if (dropContent) dropContent.classList.remove('d-none');
      return;
    }
    if (hit) hit.classList.add('d-none');
    else if (dropContent) dropContent.classList.add('d-none');

    const file = files[0];
    const row = document.createElement('div');
    row.className =
      'rfp-attachment-row d-flex flex-wrap align-items-center gap-2 w-100 py-2 border-bottom';
    row.style.borderColor = 'var(--border)';

    const iconWrap = document.createElement('div');
    iconWrap.className = 'flex-shrink-0';
    iconWrap.innerHTML = '<i class="fa-solid fa-file text-muted"></i>';

    const nameEl = document.createElement('a');
    nameEl.href = '#';
    nameEl.className = 'flex-grow-1 text-break small fw-medium as-built-att-open';
    nameEl.textContent = file.name;
    nameEl.title = file.name;
    nameEl.addEventListener('click', ev => {
      ev.preventDefault();
      ev.stopPropagation();
      if (typeof window.openAttachmentPreview === 'function') {
        window.openAttachmentPreview(file);
      }
    });

    const rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'btn btn-sm btn-outline-danger flex-shrink-0';
    rm.setAttribute('aria-label', 'Remove');
    const rmKo = document.createElement('span');
    rmKo.className = 'nav-ko';
    rmKo.textContent = '제거';
    const rmEn = document.createElement('span');
    rmEn.className = 'nav-en';
    rmEn.style.display = 'none';
    rmEn.textContent = 'Remove';
    rm.appendChild(rmKo);
    rm.appendChild(rmEn);
    rm.addEventListener('click', ev => {
      ev.preventDefault();
      ev.stopPropagation();
      setFilesOnInput(input, []);
      renderRow(input, listEl, hit, dropContent);
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });

    row.appendChild(iconWrap);
    row.appendChild(nameEl);
    row.appendChild(rm);
    listEl.appendChild(row);
  }

  function initPanel(panel) {
    const dz = panel.querySelector('.as-built-drop-zone');
    const input = panel.querySelector('.as-built-file-input');
    if (!dz || !input) return;

    const listEl = panel.querySelector('.as-built-attachment-list');
    const hit = panel.querySelector('.as-built-drop-hit-target');
    const dropContent = panel.querySelector('.as-built-drop-content');

    ['dragenter', 'dragover'].forEach(ev => {
      dz.addEventListener(ev, e => {
        e.preventDefault();
        e.stopPropagation();
        dz.classList.add('dragover');
      });
    });
    ['dragleave', 'drop'].forEach(ev => {
      dz.addEventListener(ev, e => {
        e.preventDefault();
        e.stopPropagation();
        dz.classList.remove('dragover');
      });
    });

    dz.addEventListener('drop', e => {
      const incoming = Array.from(e.dataTransfer.files || []).filter(
        f => f && f.name && f.size > 0
      );
      if (!incoming.length) return;
      setFilesOnInput(input, [incoming[0]]);
      renderRow(input, listEl, hit, dropContent);
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });

    input.addEventListener('change', () => {
      const picked = Array.from(input.files || [])
        .filter(f => f && f.name && f.size > 0)
        .slice(0, 1);
      setFilesOnInput(input, picked);
      renderRow(input, listEl, hit, dropContent);
    });

    const form = panel.querySelector('form.as-built-upload-form');
    if (form) {
      form.addEventListener('submit', e => {
        const f = input.files && input.files[0];
        if (!f || !f.size) {
          e.preventDefault();
          alert(
            typeof window.t === 'function'
              ? window.t('hub.asBuiltNeedFile')
              : '등록할 파일을 선택해 주세요.'
          );
        }
      });
    }

    renderRow(input, listEl, hit, dropContent);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.hub-as-built-panel').forEach(initPanel);
  });
})();
