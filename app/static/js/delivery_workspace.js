(function () {
  function debounce(fn, ms) {
    var t;
    return function () {
      var self = this;
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function () {
        fn.apply(self, args);
      }, ms);
    };
  }

  function bindDiffPanel(panel) {
    var url = panel.getAttribute("data-dw-diff-url");
    var view = panel.querySelector(".dw-diff-view");
    var origTa = panel.querySelector("[data-dw-diff-original]");
    if (!url || !view || !origTa) return;
    var form = panel.closest("form");
    if (!form) return;
    var sugTa = form.querySelector('textarea[name="suggested_source"]');
    if (!sugTa) return;

    var pending = false;
    function refresh() {
      if (pending) return;
      pending = true;
      var body = new FormData();
      body.append("original_source", origTa.value || "");
      body.append("suggested_source", sugTa.value || "");
      fetch(url, { method: "POST", body: body, credentials: "same-origin" })
        .then(function (r) {
          if (!r.ok) throw new Error("diff");
          return r.json();
        })
        .then(function (data) {
          if (data && typeof data.html === "string") {
            view.innerHTML = data.html;
          }
        })
        .catch(function () { /* keep last render */ })
        .finally(function () {
          pending = false;
        });
    }

    sugTa.addEventListener("input", debounce(refresh, 400));
  }

  function init() {
    var root = document.getElementById("delivery-workspace");
    if (!root) return;
    if (typeof window.initAbapLineEditors === "function") {
      window.initAbapLineEditors(root);
    }
    root.querySelectorAll("[data-dw-diff-panel]").forEach(bindDiffPanel);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
