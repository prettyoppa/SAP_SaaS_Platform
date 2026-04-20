/* SAP Dev Hub – RFP Form logic */
document.addEventListener('DOMContentLoaded', () => {

  /* Character counter */
  const desc = document.getElementById('description');
  const counter = document.getElementById('char-count');
  if (desc && counter) {
    desc.addEventListener('input', () => { counter.textContent = desc.value.length; });
  }

  /* File input change (다중 첨부) */
  const fileInput = document.getElementById('attachments') || document.getElementById('attachment');
  if (fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length) {
        const names = Array.from(fileInput.files).map(f => f.name).slice(0, 5);
        showFileSelected(names.join(', '));
      }
    });
  }

  /* Live review panel update */
  updateReview();
  document.querySelectorAll('.chip-input').forEach(cb => {
    cb.addEventListener('change', updateReview);
  });
  if (fileInput) fileInput.addEventListener('change', updateReview);

  /* Progress bar activation on scroll */
  activateProgressOnScroll();

  /* Submit guard */
  const form = document.getElementById('rfp-form');
  const submitBtn = document.getElementById('submit-btn');
  if (form && submitBtn) {
    form.addEventListener('submit', () => {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Submitting...';
    });
  }
});

function updateReview() {
  const modules = [...document.querySelectorAll('input[name="sap_modules"]:checked')].map(el => el.value);
  const types   = [...document.querySelectorAll('input[name="dev_types"]:checked')].map(el => el.value);
  const fileInput = document.getElementById('attachments') || document.getElementById('attachment');

  const noSel  = currentLang === 'ko' ? '선택 없음' : 'None selected';
  const noFile = currentLang === 'ko' ? '파일 없음'  : 'No file attached';

  const rmEl = document.getElementById('review-modules');
  const rtEl = document.getElementById('review-types');
  const rfEl = document.getElementById('review-file');

  if (rmEl) rmEl.innerHTML = modules.length
    ? modules.map(m => `<span class="badge-module">${m}</span>`).join('')
    : `<em class="text-muted">${noSel}</em>`;

  if (rtEl) rtEl.innerHTML = types.length
    ? types.map(d => `<span class="badge-devtype">${d.replace(/_/g,' ')}</span>`).join('')
    : `<em class="text-muted">${noSel}</em>`;

  if (rfEl) {
    if (fileInput && fileInput.files && fileInput.files.length) {
      const names = Array.from(fileInput.files).map(f => f.name);
      rfEl.innerHTML = `<i class="fa-solid fa-file me-1"></i>${names.join(', ')}`;
    } else {
      rfEl.innerHTML = `<em class="text-muted">${noFile}</em>`;
    }
  }
}

function activateProgressOnScroll() {
  const sections = ['section-1','section-2','section-3','section-4'];
  const steps    = ['prog-1','prog-2','prog-3','prog-4'];
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
