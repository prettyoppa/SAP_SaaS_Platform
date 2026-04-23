/* SAP Dev Hub – RFP Form (program ID, multi-attach, review, local ref code) */

let _rfpNotePrefill = null;
function loadRfpNotePrefill() {
  const el = document.getElementById('rfp-notes-prefill');
  if (!el) return;
  try {
    _rfpNotePrefill = JSON.parse(el.textContent);
  } catch (_) {
    _rfpNotePrefill = null;
  }
}

function setupMaxSelect(cls, countId, max) {
  const inputs = document.querySelectorAll('.' + cls);
  const countEl = document.getElementById(countId);
  function update() {
    const checked = document.querySelectorAll('.' + cls + ':checked').length;
    if (countEl) countEl.textContent = checked + ' / ' + max;
    inputs.forEach(inp => {
      if (!inp.checked) inp.disabled = (checked >= max);
    });
  }
  inputs.forEach(inp => inp.addEventListener('change', update));
  update();
}

function setFilesOnInput(input, files) {
  const dt = new DataTransfer();
  for (const f of files) {
    try {
      dt.items.add(f);
    } catch (_) {
      try {
        dt.items.add(new File([f], f.name, { type: f.type || 'application/octet-stream' }));
      } catch (_) {
        dt.items.add(new File([], f.name, { type: f.type || 'application/octet-stream' }));
      }
    }
  }
  input.files = dt.files;
  if (input.files.length !== files.length && files.length) {
    const dt2 = new DataTransfer();
    for (const f of files) {
      dt2.items.add(new File([f], f.name, { type: f.type || 'application/octet-stream' }));
    }
    input.files = dt2.files;
  }
}

function collectNoteValues(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const el = document.querySelector(`#attachment-list input[name="note_${i}"]`);
    out.push(el ? el.value : '');
  }
  return out;
}

function renderAttachmentRows(input, maxFiles, notePreset) {
  const listEl = document.getElementById('attachment-list');
  const dropContent = document.getElementById('drop-content');
  if (!listEl || !input) return;

  const files = Array.from(input.files || []);
  let notes;
  if (notePreset != null) {
    notes = notePreset.slice(0, files.length);
    while (notes.length < files.length) notes.push('');
  } else {
    const prev = collectNoteValues(maxFiles);
    const fb = Array.isArray(_rfpNotePrefill) ? _rfpNotePrefill : [];
    notes = files.map((_, i) => (prev[i] || fb[i] || ''));
  }

  listEl.innerHTML = '';
  if (!files.length) {
    if (dropContent) dropContent.classList.remove('d-none');
    return;
  }
  if (dropContent) dropContent.classList.add('d-none');

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
    nameEl.title = file.name;

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
      const prevNotes = collectNoteValues(maxFiles);
      const keptNotes = prevNotes.filter((_, j) => j !== idx);
      setFilesOnInput(input, next);
      renderAttachmentRows(input, maxFiles, keptNotes);
      input.dispatchEvent(new Event('change', { bubbles: true }));
      updateReview();
    });
  });
}

function initAttachmentDropZone() {
  const dz = document.getElementById('drop-zone');
  const input = document.getElementById('attachments') || document.getElementById('attachment');
  if (!dz || !input) return;

  const maxFiles = parseInt(dz.getAttribute('data-max-files') || '5', 10) || 5;

  dz.addEventListener('click', e => {
    if (e.target.closest('.rfp-att-remove')) return;
    if (e.target.closest('input[name^="note_"]')) return;
    e.preventDefault();
    input.click();
  });

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
    const incoming = Array.from(e.dataTransfer.files || []);
    if (!incoming.length) return;
    const existing = Array.from(input.files || []);
    const merged = [...existing, ...incoming].slice(0, maxFiles);
    setFilesOnInput(input, merged);
    renderAttachmentRows(input, maxFiles);
    input.dispatchEvent(new Event('change', { bubbles: true }));
    updateReview();
  });

  input.addEventListener('change', () => {
    const picked = Array.from(input.files || []).slice(0, maxFiles);
    if (picked.length !== input.files.length) setFilesOnInput(input, picked);
    renderAttachmentRows(input, maxFiles);
    updateReview();
  });

  renderAttachmentRows(input, maxFiles);
}

function updateReview() {
  const progEl = document.getElementById('program_id');
  const progId = progEl && progEl.value ? progEl.value : '';
  const rp = document.getElementById('review-program');
  if (rp) rp.innerHTML = progId || '<em class="text-muted">미입력</em>';

  const modules = [...document.querySelectorAll('.module-chip:checked')].map(c => c.value);
  const rm = document.getElementById('review-modules');
  const noSel = typeof currentLang !== 'undefined' && currentLang === 'en' ? 'None selected' : '선택 없음';
  if (rm) {
    rm.innerHTML = modules.length
      ? modules.map(m => `<span class="badge-module me-1">${m}</span>`).join('')
      : `<em class="text-muted">${noSel}</em>`;
  }

  const types = [...document.querySelectorAll('.devtype-chip:checked')].map(c => {
    const lbl = c.closest('.chip-label') && c.closest('.chip-label').querySelector('.chip');
    return lbl ? lbl.textContent.trim() : c.value;
  });
  const rt = document.getElementById('review-types');
  if (rt) {
    rt.innerHTML = types.length
      ? types.map(t => `<span class="badge-devtype me-1">${t}</span>`).join('')
      : `<em class="text-muted">${noSel}</em>`;
  }

  const fileInput = document.getElementById('attachments') || document.getElementById('attachment');
  const rf = document.getElementById('review-file');
  const noFile = typeof currentLang !== 'undefined' && currentLang === 'en' ? 'No file attached' : '없음';
  if (rf) {
    if (fileInput && fileInput.files && fileInput.files.length) {
      const names = Array.from(fileInput.files).map(f => f.name);
      rf.innerHTML = names.map(n => `<div class="small mb-0"><i class="fa-solid fa-file me-1"></i>${n}</div>`).join('');
    } else {
      rf.innerHTML = `<em class="text-muted">${noFile}</em>`;
    }
  }

  const rr = document.getElementById('review-ref-code');
  if (rr && typeof window.countRfpRefCodeSlotsFilled === 'function') {
    const n = window.countRfpRefCodeSlotsFilled();
    rr.innerHTML = n
      ? `${n}건 <span class="small text-muted">(이 브라우저에만 저장, 서버 미전송)</span>`
      : '<em class="text-muted">없음</em>';
  }
}

window.updateReview = updateReview;

function activateProgressOnScroll() {
  const sections = ['section-1', 'section-2', 'section-3', 'section-ref-code', 'section-5'];
  const steps = ['prog-1', 'prog-2', 'prog-3', 'prog-4', 'prog-5'];
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
  }, { threshold: 0.4 });

  sections.forEach(id => {
    const el = document.getElementById(id);
    if (el) observer.observe(el);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  loadRfpNotePrefill();

  const desc = document.getElementById('description');
  const counter = document.getElementById('char-count');
  if (desc && counter) {
    counter.textContent = desc.value.length;
    desc.addEventListener('input', () => { counter.textContent = desc.value.length; });
  }

  setupMaxSelect('module-chip', 'module-count', 3);
  setupMaxSelect('devtype-chip', 'devtype-count', 3);

  if (window.initSapPidTcodePair) {
    window.initSapPidTcodePair({
      programEl: document.getElementById('program_id'),
      transactionEl: document.getElementById('transaction_code'),
      feedbackPid: document.getElementById('program-id-feedback'),
      feedbackTc: document.getElementById('transaction-code-feedback'),
      maxPid: 40,
      maxTc: 20,
      mirrorTc: true,
      onChange: updateReview,
    });
  }

  initAttachmentDropZone();

  if (window.initRfpLocalRefCode) window.initRfpLocalRefCode();

  document.querySelectorAll('.module-chip, .devtype-chip').forEach(c => {
    c.addEventListener('change', updateReview);
  });

  updateReview();

  activateProgressOnScroll();

  const form = document.getElementById('rfp-form');
  const submitBtn = document.getElementById('submit-btn');
  if (form && submitBtn) {
    form.addEventListener('submit', () => {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Submitting...';
    });
  }
});
