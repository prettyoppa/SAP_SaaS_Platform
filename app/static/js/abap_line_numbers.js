/**
 * ABAP 소스 + 행 번호 열 (SE38 작업실·납품 개발코드 공통).
 * 행 번호·소스는 동일한 max-height 안에서 scrollTop을 맞춘다.
 */
(function () {
  function bindLineEditor(editor) {
    if (editor.dataset.dwLineEditorBound === "1") return;
    editor.dataset.dwLineEditorBound = "1";

    var nums = editor.querySelector(".dw-line-nums");
    var ta = editor.querySelector(".dw-source-input");
    var view = editor.querySelector(".dw-source-view");
    var scrollEl = ta || view;
    if (!nums || !scrollEl) return;

    var syncing = false;

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

    function syncScroll(fromNums) {
      if (syncing) return;
      syncing = true;
      if (fromNums) {
        scrollEl.scrollTop = nums.scrollTop;
        scrollEl.scrollLeft = nums.scrollLeft;
      } else {
        nums.scrollTop = scrollEl.scrollTop;
        nums.scrollLeft = scrollEl.scrollLeft;
      }
      syncing = false;
    }

    if (ta) {
      ta.addEventListener("input", refreshNums);
      refreshNums();
    }
    scrollEl.addEventListener("scroll", function () {
      syncScroll(false);
    }, { passive: true });
    nums.addEventListener("scroll", function () {
      syncScroll(true);
    }, { passive: true });

    if (typeof ResizeObserver !== "undefined") {
      var ro = new ResizeObserver(function () {
        syncScroll(false);
      });
      ro.observe(scrollEl);
    }
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
