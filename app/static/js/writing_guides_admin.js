/**
 * 요청 폼 — 관리자 전용 작성 가이드 인라인 저장 (POST /admin/api/writing-guide)
 */
(function () {
  function closestAdmin(el) {
    return el && el.closest ? el.closest('[data-wg-key]') : null;
  }

  document.addEventListener('click', function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;

    var toggle = t.closest('.wg-admin-toggle');
    if (toggle) {
      var wrap = closestAdmin(toggle);
      if (!wrap) return;
      var ed = wrap.querySelector('.wg-admin-editor');
      if (!ed) return;
      ed.classList.toggle('d-none');
      return;
    }

    var cancel = t.closest('.wg-admin-cancel');
    if (cancel) {
      var wrap2 = closestAdmin(cancel);
      if (!wrap2) return;
      var ed2 = wrap2.querySelector('.wg-admin-editor');
      if (ed2) ed2.classList.add('d-none');
      return;
    }

    var save = t.closest('.wg-admin-save');
    if (!save) return;
    var wrap3 = closestAdmin(save);
    if (!wrap3) return;
    var key = wrap3.getAttribute('data-wg-key');
    if (!key) return;
    var koTa = wrap3.querySelector('textarea.wg-md-src[data-wg-lang="ko"]');
    var enTa = wrap3.querySelector('textarea.wg-md-src[data-wg-lang="en"]');
    if (!koTa || !enTa) return;

    save.disabled = true;
    fetch('/admin/api/writing-guide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        key: key,
        md_ko: koTa.value,
        md_en: enTa.value,
      }),
    })
      .then(function (r) {
        if (!r.ok) {
          return r.text().then(function (t) {
            try {
              var j = JSON.parse(t);
              throw new Error((j && j.error) || t || r.status);
            } catch (e) {
              if (e instanceof SyntaxError) throw new Error(t || String(r.status));
              throw e;
            }
          });
        }
        return r.json();
      })
      .then(function () {
        window.location.reload();
      })
      .catch(function (e) {
        window.alert(String(e.message || e));
        save.disabled = false;
      });
  });
})();
