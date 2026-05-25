/**
 * ABAP 소스 + 행 번호 열 (SE38 작업실·납품 개발코드 공통).
 */
(function () {
  function bindLineEditor(editor) {
    var nums = editor.querySelector(".dw-line-nums");
    var ta = editor.querySelector(".dw-source-input");
    var view = editor.querySelector(".dw-source-view");
    var scrollEl = ta || view;
    if (!nums || !scrollEl) return;

    function refreshNums() {
      if (!ta) return;
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
      nums.scrollTop = scrollEl.scrollTop;
    }

    if (ta) {
      ta.addEventListener("input", refreshNums);
      refreshNums();
    }
    scrollEl.addEventListener("scroll", syncScroll);
  }

  function init(root) {
    var scope = root || document;
    scope.querySelectorAll("[data-dw-line-editor]").forEach(bindLineEditor);
  }

  window.initAbapLineEditors = init;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      init(document);
    });
  } else {
    init(document);
  }
})();
