/**
 * Admin KB: show/hide English fields when "also_english" is checked.
 */
(function () {
  function syncPanel(cb) {
    const panelId = cb.getAttribute('data-kb-en-panel');
    const panel = panelId ? document.getElementById(panelId) : null;
    if (!panel) return;
    if (cb.checked) {
      panel.classList.remove('d-none');
    } else {
      panel.classList.add('d-none');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.kb-also-english-cb').forEach(function (cb) {
      syncPanel(cb);
      cb.addEventListener('change', function () {
        syncPanel(cb);
      });
    });
  });
})();
