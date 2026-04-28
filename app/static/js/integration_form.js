/* SAP 연동 개발 요청 폼 – 첨부·요약·참고 코드 */

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
  const dt = new DataTransfer();
  for (const f of list) {
    try {
      dt.items.add(f);
    } catch (_) {
      try {
        const body = f.slice(0, f.size);
        dt.items.add(
          new File([body], f.name, {
            type: f.type || 'application/octet-stream',
            lastModified: f.lastModified,
          }),
        );
      } catch (e2) {
        console.warn('intSetFilesOnInput: skip', f.name, e2);
      }
    }
  }
  input.files = dt.files;
}

function intCollectNoteValues(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const el = document.querySelector(`#int-attachment-list input[name="note_${i}"]`);
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
  const listEl = document.getElementById('int-attachment-list');
  const dropContent = document.getElementById('int-drop-content');
  const hit = document.getElementById('int-file-drop-hit-target');
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

    const nameEl = document.createElement('div');
    nameEl.className = 'flex-grow-1 text-break small fw-medium';
    nameEl.textContent = file.name;

    const rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'btn btn-sm btn-outline-danger rfp-att-remove flex-shrink-0';
    rm.setAttribute('data-idx', String(i));
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
      updateIntegrationReview();
    });
  });
}

function initIntegrationAttachmentDropZone() {
  const dz = document.getElementById('int-drop-zone');
  const input = document.getElementById('int-attachments');
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
    updateIntegrationReview();
  });

  input.addEventListener('change', () => {
    const picked = Array.from(input.files || []).filter(f => f && f.name && f.size > 0).slice(0, maxFiles);
    if (picked.length !== input.files.length) intSetFilesOnInput(input, picked);
    intRenderAttachmentRows(input, maxFiles);
    updateIntegrationReview();
  });

  intRenderAttachmentRows(input, maxFiles);
}

function updateIntegrationReview() {
  const titleEl = document.getElementById('int-title');
  const title = titleEl && titleEl.value ? titleEl.value.trim() : '';
  const rt = document.getElementById('int-review-title');
  if (rt) rt.innerHTML = title || '<em class="text-muted">미입력</em>';

  const types = [...document.querySelectorAll('.int-impl-type:checked')].map(c => {
    const lbl = c.getAttribute('data-label') || c.value;
    return lbl;
  });
  const rty = document.getElementById('int-review-impl');
  if (rty) {
    rty.innerHTML = types.length
      ? types.map(t => `<span class="badge-devtype me-1">${t}</span>`).join('')
      : '<em class="text-muted">선택 없음</em>';
  }

  const tp = document.getElementById('int-sap-touchpoints');
  const rtp = document.getElementById('int-review-touch');
  if (rtp) {
    const v = tp && tp.value ? tp.value.trim() : '';
    rtp.innerHTML = v ? v.replace(/\n/g, '<br/>') : '<em class="text-muted">없음</em>';
  }

  const fileInput = document.getElementById('int-attachments');
  const rf = document.getElementById('int-review-files');
  if (rf) {
    if (fileInput && fileInput.files && fileInput.files.length) {
      const names = Array.from(fileInput.files).map(f => f.name);
      rf.innerHTML = names.map(n => `<div class="small mb-0"><i class="fa-solid fa-file me-1"></i>${n}</div>`).join('');
    } else {
      rf.innerHTML = '<em class="text-muted">없음</em>';
    }
  }

  const rr = document.getElementById('int-review-ref');
  if (rr && typeof window.countIntegrationRefCodeSlotsFilled === 'function') {
    const n = window.countIntegrationRefCodeSlotsFilled();
    rr.innerHTML = n
      ? `${n}건 <span class="small text-muted">(분석·제안 반영)</span>`
      : '<em class="text-muted">없음</em>';
  }
}

window.updateIntegrationReview = updateIntegrationReview;

function intActivateProgressOnScroll() {
  const sections = ['int-section-1', 'int-section-2', 'int-section-3', 'int-section-ref', 'int-section-5'];
  const steps = ['int-prog-1', 'int-prog-2', 'int-prog-3', 'int-prog-4', 'int-prog-5'];
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const idx = sections.indexOf(entry.target.id);
        steps.forEach((s, i) => {
          const el = document.getElementById(s);
          if (el) el.classList.toggle('active', i <= idx);
        });
      }
    });
  }, { threshold: 0.35 });

  sections.forEach(id => {
    const el = document.getElementById(id);
    if (el) observer.observe(el);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  loadIntegrationNotePrefill();

  const desc = document.getElementById('int-description');
  const counter = document.getElementById('int-char-count');
  if (desc && counter) {
    counter.textContent = desc.value.length;
    desc.addEventListener('input', () => { counter.textContent = desc.value.length; });
  }

  document.querySelectorAll('.int-impl-type').forEach(c => {
    c.addEventListener('change', updateIntegrationReview);
  });
  const titleInp = document.getElementById('int-title');
  if (titleInp) titleInp.addEventListener('input', updateIntegrationReview);
  const touch = document.getElementById('int-sap-touchpoints');
  if (touch) touch.addEventListener('input', updateIntegrationReview);

  initIntegrationAttachmentDropZone();

  if (window.initIntegrationRefCode) window.initIntegrationRefCode();

  updateIntegrationReview();

  intActivateProgressOnScroll();

  const form = document.getElementById('integration-form');
  if (form) {
    form.addEventListener(
      'submit',
      () => {
        const att = document.getElementById('int-attachments');
        const dzEl = document.getElementById('int-drop-zone');
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
