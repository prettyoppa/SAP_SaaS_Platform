/**
 * ABAP 소스 + 행 번호 열 (SE38 작업실·납품 개발코드 공통).
 * 읽기 전용: 단일 스크롤 컨테이너(행 번호·소스가 함께 움직임).
 * 편집: 동일 타이포 + scrollTop 동기화(줄바꿈 없음).
 */
(function () {
  function bindLineEditor(editor) {
    if (editor.dataset.dwLineEditorBound === "1") return;
    editor.dataset.dwLineEditorBound = "1";

    var nums = editor.querySelector(".dw-line-nums");
    var ta = editor.querySelector(".dw-source-input");
    var view = editor.querySelector(".dw-source-view");
    var scrollOuter = editor.querySelector(".dw-source-scroll");

    if (scrollOuter) {
      if (ta) {
        ta.addEventListener("input", function () {
          refreshNums(ta, nums);
        });
        refreshNums(ta, nums);
      }
      return;
    }

    var scrollEl = ta || view;
    if (!nums || !scrollEl) return;

    var syncing = false;

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
      ta.addEventListener("input", function () {
        refreshNums(ta, nums);
      });
      refreshNums(ta, nums);
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

  function refreshNums(ta, nums) {
    if (!ta || !nums) return;
    var lines = (ta.value || "").split("\n");
    var n = Math.max(1, lines.length);
    var width = String(n).length;
    var buf = [];
    for (var i = 1; i <= n; i++) {
      buf.push(String(i).padStart(width, " "));
    }
    nums.textContent = buf.join("\n");
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
