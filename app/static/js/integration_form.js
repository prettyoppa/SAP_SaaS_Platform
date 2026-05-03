/* SAP 연동 개발 요청 폼 — 첨부(신규개발과 동일 ID)·요약 */

let _intNotePrefill = null;
function loadIntegrationNotePrefill() {
  const el = document.getElementById('integration-notes-prefill');
  if (!el) return;
  try {
    _intNotePrefill = JSON.parse(el.textContent);
  } catch (_) {
    _intNotePrefill = null;
  }
}

function intSetFilesOnInput(input, files) {
  const list = Array.from(files || []).filter(f => f && f.name && f.size > 0);
  const addCopy = (dt, f) => {
    const body = f.size > 0 ? f.slice(0, f.size) : new Blob();
    dt.items.add(
      new File([body], f.name, {
        type: f.type || 'application/octet-stream',
        lastModified: f.lastModified,
      }),
    );
  };
  const dt = new DataTransfer();
  for (const f of list) {
    try {
      dt.items.add(f);
    } catch (_) {
      try {
        addCopy(dt, f);
      } catch (e2) {
        console.warn('intSetFilesOnInput: skip', f.name, e2);
      }
    }
  }
  input.files = dt.files;
  if (list.length && input.files.length !== list.length) {
    const dt2 = new DataTransfer();
    for (const f of list) {
      try {
        addCopy(dt2, f);
      } catch (_) {}
    }
    if (dt2.files.length) input.files = dt2.files;
  }
}

function openAttachmentPreview(file) {
  const name = (file && file.name) || '';
  const mime = (file && file.type) || '';
  const textish =
    /^text\//i.test(mime) ||
    /(^|\.)(txt|log|md|csv|tsv|json|xml|yml|yaml|ini|env|sh|bat|cmd|sql|abap|properties|gitignore)$/i.test(
      name,
    );
  const maxText = 10 * 1024 * 1024;
  if (textish && file.size > 0 && file.size <= maxText) {
    const reader = new FileReader();
    reader.onload = () => {
      const blob = new Blob([reader.result], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => URL.revokeObjectURL(url), 180000);
    };
    reader.onerror = () => {
      const url = URL.createObjectURL(file);
      window.open(url, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => URL.revokeObjectURL(url), 180000);
    };
    reader.readAsText(file, 'UTF-8');
    return;
  }
  const url = URL.createObjectURL(file);
  window.open(url, '_blank', 'noopener,noreferrer');
  window.setTimeout(() => URL.revokeObjectURL(url), 180000);
}

function intCollectNoteValues(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const el = document.querySelector(`#attachment-list input[name="note_${i}"]`);
    out.push(el ? el.value : '');
  }
  return out;
}

function intFilterEmptyAttachmentsBeforeSubmit(input, maxFiles) {
  const raw = Array.from(input.files || []);
  const kept = [];
  const mapIdx = [];
  raw.forEach((f, i) => {
    if (f && f.name && f.size > 0) {
      kept.push(f);
      mapIdx.push(i);
    }
  });
  if (kept.length === raw.length) return;
  const prev = intCollectNoteValues(maxFiles);
  const newNotes = mapIdx.map(j => prev[j] || '');
  intSetFilesOnInput(input, kept);
  intRenderAttachmentRows(input, maxFiles, newNotes);
}

function intRenderAttachmentRows(input, maxFiles, notePreset) {
  const listEl = document.getElementById('attachment-list');
  const dropContent = document.getElementById('drop-content');
  const hit = document.getElementById('file-drop-hit-target');
  if (!listEl || !input) return;

  const files = Array.from(input.files || []);
  let notes;
  if (notePreset != null) {
    notes = notePreset.slice(0, files.length);
    while (notes.length < files.length) notes.push('');
  } else {
    const prev = intCollectNoteValues(maxFiles);
    const fb = Array.isArray(_intNotePrefill) ? _intNotePrefill : [];
    notes = files.map((_, i) => (prev[i] || fb[i] || ''));
  }

  listEl.innerHTML = '';
  if (!files.length) {
    if (hit) hit.classList.remove('d-none');
    else if (dropContent) dropContent.classList.remove('d-none');
    return;
  }
  if (hit) hit.classList.add('d-none');
  else if (dropContent) dropContent.classList.add('d-none');

  files.forEach((file, i) => {
    const row = document.createElement('div');
    row.className = 'rfp-attachment-row d-flex flex-wrap align-items-center gap-2 w-100 py-2 border-bottom';
    row.style.borderColor = 'var(--border)';

    const iconWrap = document.createElement('div');
    iconWrap.className = 'flex-shrink-0';
    iconWrap.innerHTML = '<i class="fa-solid fa-file text-muted"></i>';

    const nameEl = document.createElement('a');
    nameEl.href = '#';
    nameEl.className = 'flex-grow-1 text-break small fw-medium rfp-att-open';
    nameEl.textContent = file.name;
    nameEl.title = `${file.name} (클릭하여 미리 보기)`;
    nameEl.addEventListener('click', ev => {
      ev.preventDefault();
      ev.stopPropagation();
      openAttachmentPreview(file);
    });

    const rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'btn btn-sm btn-outline-danger rfp-att-remove flex-shrink-0';
    rm.setAttribute('data-idx', String(i));
    rm.setAttribute('aria-label', '첨부 제거');
    rm.textContent = '제거';

    const br = document.createElement('div');
    br.className = 'w-100';

    const lbl = document.createElement('label');
    lbl.className = 'small text-muted mb-0 w-100';
    lbl.textContent = '설명 (선택)';

    const noteInput = document.createElement('input');
    noteInput.type = 'text';
    noteInput.className = 'form-control form-control-sm';
    noteInput.name = `note_${i}`;
    noteInput.maxLength = 200;
    noteInput.placeholder = `첨부 ${i + 1} 설명`;
    noteInput.value = notes[i] || '';

    row.appendChild(iconWrap);
    row.appendChild(nameEl);
    row.appendChild(rm);
    row.appendChild(br);
    row.appendChild(lbl);
    row.appendChild(noteInput);
    listEl.appendChild(row);
  });

  listEl.querySelectorAll('.rfp-att-remove').forEach(btn => {
    btn.addEventListener('click', ev => {
      ev.preventDefault();
      ev.stopPropagation();
      const idx = parseInt(btn.getAttribute('data-idx'), 10);
      const next = Array.from(input.files).filter((_, j) => j !== idx);
      const prevNotes = intCollectNoteValues(maxFiles);
      const keptNotes = prevNotes.filter((_, j) => j !== idx);
      intSetFilesOnInput(input, next);
      intRenderAttachmentRows(input, maxFiles, keptNotes);
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
}

function initIntegrationAttachmentDropZone() {
  const dz = document.getElementById('drop-zone');
  const input = document.getElementById('attachments');
  if (!dz || !input) return;

  const maxFiles = parseInt(dz.getAttribute('data-max-files') || '5', 10) || 5;

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
    const incoming = Array.from(e.dataTransfer.files || []).filter(f => f && f.name && f.size > 0);
    if (!incoming.length) return;
    const existing = Array.from(input.files || []).filter(f => f && f.name && f.size > 0);
    const merged = [...existing, ...incoming].slice(0, maxFiles);
    intSetFilesOnInput(input, merged);
    intRenderAttachmentRows(input, maxFiles);
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });

  input.addEventListener('change', () => {
    const picked = Array.from(input.files || []).filter(f => f && f.name && f.size > 0).slice(0, maxFiles);
    if (picked.length !== input.files.length) intSetFilesOnInput(input, picked);
    intRenderAttachmentRows(input, maxFiles);
  });

  intRenderAttachmentRows(input, maxFiles);
}

/** integration_ref_code.js 호환 (리뷰 블록 제거 후 noop) */
window.updateIntegrationReview = function () {};

document.addEventListener('DOMContentLoaded', () => {
  loadIntegrationNotePrefill();

  const desc = document.getElementById('int-description');
  const counter = document.getElementById('int-char-count');
  if (desc && counter) {
    counter.textContent = desc.value.length;
    desc.addEventListener('input', () => {
      counter.textContent = desc.value.length;
    });
  }

  initIntegrationAttachmentDropZone();

  if (window.initIntegrationRefCode) window.initIntegrationRefCode();

  const form = document.getElementById('integration-form');
  if (form) {
    form.addEventListener(
      'submit',
      () => {
        const att = document.getElementById('attachments');
        const dzEl = document.getElementById('drop-zone');
        if (att && dzEl) {
          const mf = parseInt(dzEl.getAttribute('data-max-files') || '5', 10) || 5;
          intFilterEmptyAttachmentsBeforeSubmit(att, mf);
        }
      },
      true,
    );
  }

  const submitBtn = document.getElementById('int-submit-btn');
  if (form && submitBtn) {
    form.addEventListener('submit', () => {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>제출 중...';
    });
  }
});
