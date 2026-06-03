/* SAP Dev Hub – RFP Form (program ID, multi-attach, review, local ref code) */

function rfpT(key, fallback) {
  if (typeof window.t === 'function') {
    var v = window.t(key);
    if (v !== null && v !== undefined && v !== key) return v;
  }
  return fallback != null ? fallback : key;
}

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
        console.warn('setFilesOnInput: skip', f.name, e2);
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

function collectNoteValues(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const el = document.querySelector(`#attachment-list input[name="note_${i}"]`);
    out.push(el ? el.value : '');
  }
  return out;
}

function filterEmptyAttachmentsBeforeSubmit(input, maxFiles) {
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
  const prev = collectNoteValues(maxFiles);
  const newNotes = mapIdx.map(j => prev[j] || '');
  setFilesOnInput(input, kept);
  renderAttachmentRows(input, maxFiles, newNotes);
}

function renderAttachmentRows(input, maxFiles, notePreset) {
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
    const prev = collectNoteValues(maxFiles);
    const fb = Array.isArray(_rfpNotePrefill) ? _rfpNotePrefill : [];
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
    nameEl.title = file.name + rfpT('rfp.attachPreviewSuffix', ' (클릭하여 미리 보기)');
    nameEl.addEventListener('click', ev => {
      ev.preventDefault();
      ev.stopPropagation();
      if (typeof window.openAttachmentPreview === 'function') {
        window.openAttachmentPreview(file);
      }
    });

    const rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'btn btn-sm btn-outline-danger rfp-att-remove flex-shrink-0';
    rm.setAttribute('data-idx', String(i));
    rm.setAttribute('aria-label', rfpT('rfp.attachRemoveAria', '첨부 제거'));
    rm.textContent = rfpT('rfp.attachRemove', '제거');

    const br = document.createElement('div');
    br.className = 'w-100';

    const lbl = document.createElement('label');
    lbl.className = 'small text-muted mb-0 w-100';
    lbl.textContent = rfpT('rfp.attachNoteLabel', '설명 (선택)');

    const noteInput = document.createElement('input');
    noteInput.type = 'text';
    noteInput.className = 'form-control form-control-sm';
    noteInput.name = `note_${i}`;
    noteInput.maxLength = 200;
    noteInput.placeholder = rfpT('rfp.attachNotePlaceholder', '첨부 ' + (i + 1) + ' 설명').replace('{n}', String(i + 1));
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
    setFilesOnInput(input, merged);
    renderAttachmentRows(input, maxFiles);
    input.dispatchEvent(new Event('change', { bubbles: true }));
    updateReview();
  });

  input.addEventListener('change', () => {
    const picked = Array.from(input.files || []).filter(f => f && f.name && f.size > 0).slice(0, maxFiles);
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
      ? `${n}건 <span class="small text-muted">(본 요청 분석·제안서 작성에 반영)</span>`
      : '<em class="text-muted">없음</em>';
  }
}

window.updateReview = updateReview;

document.addEventListener('DOMContentLoaded', () => {
  loadRfpNotePrefill();

  if (!document.querySelector('.req-rich-field')) {
    const desc = document.getElementById('description');
    const counter = document.getElementById('char-count');
    if (desc && counter) {
      counter.textContent = desc.value.length;
      desc.addEventListener('input', () => { counter.textContent = desc.value.length; });
    }
  }

  setupMaxSelect('module-chip', 'module-count', 3);
  setupMaxSelect('devtype-chip', 'devtype-count', 3);

  (function initSapSystemVersionField() {
    const inp = document.getElementById('sap_system_version');
    if (!inp) return;
    const upperLatin = () => {
      const v = inp.value;
      const n = v.replace(/[a-z]/g, (ch) => ch.toUpperCase());
      if (n !== v) {
        const start = inp.selectionStart;
        const end = inp.selectionEnd;
        inp.value = n;
        if (start != null && end != null) inp.setSelectionRange(start, end);
      }
    };
    inp.addEventListener('input', () => {
      upperLatin();
      if (typeof updateReview === 'function') updateReview();
    });
  })();

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

  ;['rfp-form', 'abap-analysis-form', 'delivery-fs-upload-form'].forEach(fid => {
    const fEl = document.getElementById(fid);
    if (!fEl) return;
    fEl.addEventListener(
      'submit',
      () => {
        const att = document.getElementById('attachments');
        const dzEl = document.getElementById('drop-zone');
        if (!att || !dzEl) return;
        const mf = parseInt(dzEl.getAttribute('data-max-files') || '5', 10) || 5;
        filterEmptyAttachmentsBeforeSubmit(att, mf);
      },
      true,
    );
  });

  ['rfp-form', 'abap-analysis-form'].forEach((fid) => {
    const form = document.getElementById(fid);
    const submitBtn = document.getElementById('submit-btn');
    if (form && submitBtn) {
      form.addEventListener('submit', () => {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>' + rfpT('rfp.submitting', 'Submitting…');
      });
    }
  });

  const MIN_DESC_FOR_AI = 40;
  function rfpDescriptionPlainText() {
    if (typeof window.syncAllReqRichFields === 'function') window.syncAllReqRichFields();
    const root = document.querySelector('.req-rich-field');
    if (root) {
      const fmtInput = root.querySelector('.req-rich-fmt-input');
      const richEl = root.querySelector('.req-rich-surface');
      const plainEl = root.querySelector('.req-rich-plain');
      if (fmtInput && fmtInput.value === 'html' && richEl) {
        return (richEl.innerText || '').replace(/\s+/g, ' ').trim();
      }
      if (plainEl) return (plainEl.value || '').trim();
    }
    const d = document.getElementById('description');
    return d ? (d.value || '').trim() : '';
  }
  function rfpDescriptionForSuggest() {
    const plain = rfpDescriptionPlainText();
    const root = document.querySelector('.req-rich-field');
    const fmtInput = root ? root.querySelector('.req-rich-fmt-input') : null;
    return {
      description: plain,
      description_format: fmtInput ? fmtInput.value : 'html',
    };
  }
  function rfpDescTooShortForAi() {
    return rfpDescriptionPlainText().length < MIN_DESC_FOR_AI;
  }
  function rfpAiInsufficientMsg() {
    const en = typeof currentLang !== 'undefined' && currentLang === 'en';
    return en
      ? 'Enter at least 40 characters in the requirements field (saved draft not required; uses text on screen).'
      : '「요구사항 자유 기술」에 40자 이상 입력해 주세요. (임시저장 없이 화면에 입력된 내용을 사용합니다)';
  }

  async function postRfpSuggest(body) {
    const res = await fetch('/rfp/api/suggest-field', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body),
    });
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    return { res, data };
  }

  const aiTitleBtn = document.getElementById('rfp-ai-title-btn');
  if (aiTitleBtn) {
    aiTitleBtn.addEventListener('click', async () => {
      if (rfpDescTooShortForAi()) {
        alert(rfpAiInsufficientMsg());
        return;
      }
      aiTitleBtn.disabled = true;
      try {
        const descPayload = rfpDescriptionForSuggest();
        const { res, data } = await postRfpSuggest({
          kind: 'title',
          description: descPayload.description,
          description_format: descPayload.description_format,
        });
        if (!res.ok) {
          if (data.error === 'description_insufficient') alert(rfpAiInsufficientMsg());
          else alert(data.error === 'login_required' ? '로그인이 필요합니다.' : '제목 자동 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.');
          return;
        }
        const ti = document.getElementById('title');
        if (ti && data.title) {
          ti.value = data.title;
          ti.dispatchEvent(new Event('input', { bubbles: true }));
        }
        if (typeof window.updateReview === 'function') window.updateReview();
      } finally {
        aiTitleBtn.disabled = false;
      }
    });
  }

  const aiProgBtn = document.getElementById('rfp-ai-program-btn');
  if (aiProgBtn) {
    aiProgBtn.addEventListener('click', async () => {
      const ti = document.getElementById('title');
      if (!ti || !ti.value.trim()) {
        alert(typeof currentLang !== 'undefined' && currentLang === 'en'
          ? 'Enter a request title first (or use AI on the title field).'
          : '요청 제목을 먼저 입력해 주세요.');
        return;
      }
      if (rfpDescTooShortForAi()) {
        alert(rfpAiInsufficientMsg());
        return;
      }
      aiProgBtn.disabled = true;
      try {
        const descPayload = rfpDescriptionForSuggest();
        const { res, data } = await postRfpSuggest({
          kind: 'program_id',
          title: ti.value.trim(),
          description: descPayload.description,
          description_format: descPayload.description_format,
        });
        if (!res.ok) {
          if (data.error === 'description_insufficient') alert(rfpAiInsufficientMsg());
          else if (data.error === 'title_empty') {
            alert('요청 제목을 먼저 입력해 주세요.');
          } else {
            alert('프로그램 ID 자동 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.');
          }
          return;
        }
        const pid = document.getElementById('program_id');
        const tc = document.getElementById('transaction_code');
        if (pid && data.program_id) {
          pid.value = data.program_id;
          pid.dispatchEvent(new Event('input', { bubbles: true }));
        }
        if (data.mirror_transaction && tc && !(tc.value || '').trim() && pid && pid.value) {
          tc.value = pid.value.slice(0, 20);
          tc.dispatchEvent(new Event('input', { bubbles: true }));
        }
        if (typeof window.updateReview === 'function') window.updateReview();
      } finally {
        aiProgBtn.disabled = false;
      }
    });
  }
});
