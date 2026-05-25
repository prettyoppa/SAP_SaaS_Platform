(function () {
  function syncEditor(editor) {
    var nums = editor.querySelector(".dw-line-nums");
    var ta = editor.querySelector(".dw-source-input");
    if (!nums || !ta) return;
    function refreshNums() {
      var lines = (ta.value || "").split("\n");
      var n = Math.max(1, lines.length);
      var width = String(n).length;
      var buf = [];
      for (var i = 1; i <= n; i++) {
        buf.push(String(i).padStart(width, " "));
      }
      nums.textContent = buf.join("\n");
    }
    function syncScroll() {
      nums.scrollTop = ta.scrollTop;
    }
    ta.addEventListener("input", refreshNums);
    ta.addEventListener("scroll", syncScroll);
    refreshNums();
  }

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
    root.querySelectorAll("[data-dw-source-editor]").forEach(syncEditor);
    root.querySelectorAll("[data-dw-diff-panel]").forEach(bindDiffPanel);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
