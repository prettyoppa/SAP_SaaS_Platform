/**
 * Admin KB: inline markdown preview for body textarea.
 */
(function () {
  async function renderMarkdown(bodyMd) {
    const fd = new FormData();
    fd.append('body_md', bodyMd || '');
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
    document.querySelectorAll('.kb-inline-preview-btn').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        const taId = btn.getAttribute('data-kb-preview-for');
        const ta = taId ? document.getElementById(taId) : null;
        if (!ta) return;
        const previewId = taId.replace('body-md-', 'kb-preview-');
        const box = document.getElementById(previewId);
        if (!box) return;
        if (!box.classList.contains('d-none')) {
          box.classList.add('d-none');
          box.setAttribute('aria-hidden', 'true');
          return;
        }
        box.classList.remove('d-none');
        box.setAttribute('aria-hidden', 'false');
        box.innerHTML = '<p class="text-muted small mb-0">…</p>';
        try {
          box.innerHTML = await renderMarkdown(ta.value);
        } catch (e) {
          box.innerHTML = '<p class="text-danger small">Preview failed.</p>';
        }
      });
    });
  });
})();
