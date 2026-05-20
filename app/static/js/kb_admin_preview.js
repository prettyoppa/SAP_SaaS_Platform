/**
 * Admin KB: inline body preview (Markdown or HTML 본문).
 */
(function () {
  async function renderBody(bodyMd, bodyFormat) {
    const fd = new FormData();
    fd.append('body_md', bodyMd || '');
    fd.append('body_format', bodyFormat || 'markdown');
    const r = await fetch('/admin/api/kb/render-markdown', {
      method: 'POST',
      credentials: 'same-origin',
      body: fd,
    });
    if (!r.ok) throw new Error('render_failed');
    const j = await r.json();
    return j.html || '';
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.kb-inline-preview-btn-en').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const aid = btn.getAttribute('data-kb-preview-en');
        const ta = document.getElementById('kb-body-en-' + aid);
        const box = document.getElementById('kb-preview-en-' + aid);
        if (!ta || !box) return;
        if (!box.classList.contains('d-none')) {
          box.classList.add('d-none');
          box.setAttribute('aria-hidden', 'true');
          return;
        }
        box.classList.remove('d-none');
        box.setAttribute('aria-hidden', 'false');
        box.innerHTML = '<p class="text-muted small mb-0">…</p>';
        try {
          const fmt =
            document.querySelector('#kb-req-rich-' + aid + ' .req-rich-fmt-input')?.value ||
            'markdown';
          box.innerHTML = await renderBody(ta.value, fmt);
        } catch (e) {
          box.innerHTML = '<p class="text-danger small">Preview failed.</p>';
        }
      });
    });

    document.querySelectorAll('.kb-inline-preview-btn').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const rootId = btn.getAttribute('data-kb-preview-root');
        const root = rootId ? document.getElementById(rootId) : null;
        if (!root) return;
        const hidden = root.querySelector('.req-rich-hidden-body');
        const fmtInput = root.querySelector('.req-rich-fmt-input');
        const aid = rootId.indexOf('kb-req-rich-') === 0 ? rootId.slice('kb-req-rich-'.length) : 'new';
        const box = document.getElementById('kb-preview-' + aid);
        if (!hidden || !fmtInput || !box) return;
        if (!box.classList.contains('d-none')) {
          box.classList.add('d-none');
          box.setAttribute('aria-hidden', 'true');
          return;
        }
        box.classList.remove('d-none');
        box.setAttribute('aria-hidden', 'false');
        box.innerHTML = '<p class="text-muted small mb-0">…</p>';
        try {
          box.innerHTML = await renderBody(hidden.value, fmtInput.value);
        } catch (e) {
          box.innerHTML = '<p class="text-danger small">Preview failed.</p>';
        }
      });
    });
  });
})();
