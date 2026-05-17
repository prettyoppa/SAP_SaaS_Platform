/**
 * 홈 히어로 «사용 안내» — URL 없을 때 ABAP 터미널 타이핑·스크롤 데모
 */
(function () {
  "use strict";

  var root = document.querySelector("[data-home-guide-code-demo]");
  if (!root) return;

  var codeEl = root.querySelector(".home-guide-code-lines code");
  var viewport = root.querySelector(".home-guide-code-viewport");
  if (!codeEl || !viewport) return;

  var LINES = [
    { t: "*&---------------------------------------------------------------------*", c: "cm" },
    { t: "*& Report  ZDEV_HUB_DEMO", c: "cm" },
    { t: "*&---------------------------------------------------------------------*", c: "cm" },
    { t: "REPORT zdev_hub_demo.", c: "kw" },
    { t: "", c: "" },
    { t: "DATA: lv_msg   TYPE string,", c: "kw" },
    { t: "      lv_count TYPE i.", c: "kw" },
    { t: "", c: "" },
    { t: "START-OF-SELECTION.", c: "kw" },
    { t: "  lv_msg = 'Hello, SAP Dev Hub'.", c: "" },
    { t: "  WRITE: / lv_msg.", c: "kw" },
    { t: "", c: "" },
    { t: "  DO 3 TIMES.", c: "kw" },
    { t: "    lv_count = sy-index.", c: "" },
    { t: "    WRITE: / |Agent { lv_count } ready|.", c: "kw" },
    { t: "  ENDDO.", c: "kw" },
    { t: "", c: "" },
    { t: "  PERFORM finalize_output.", c: "kw" },
    { t: "", c: "" },
    { t: "FORM finalize_output.", c: "kw" },
    { t: "  WRITE: / 'Proposal pipeline: OK'.", c: "kw" },
    { t: "ENDFORM.", c: "kw" },
  ];

  var CHAR_MS = 22;
  var LINE_PAUSE_MS = 65;
  var END_PAUSE_MS = 2800;

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function esc(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function highlightLine(line, visibleLen) {
    var raw = line.t.slice(0, visibleLen);
    if (line.c === "cm") {
      return '<span class="home-guide-code-cm">' + esc(raw) + "</span>";
    }
    if (line.c === "kw") {
      return '<span class="home-guide-code-kw">' + esc(raw) + "</span>";
    }
    var m = raw.match(/^(\s*)(.*)$/);
    if (!m) return esc(raw);
    var lead = m[1];
    var rest = m[2];
    var q1 = rest.indexOf("'");
    if (q1 >= 0) {
      var q2 = rest.indexOf("'", q1 + 1);
      if (q2 >= 0) {
        return (
          esc(lead + rest.slice(0, q1)) +
          '<span class="home-guide-code-str">' +
          esc(rest.slice(q1, q2 + 1)) +
          "</span>" +
          esc(rest.slice(q2 + 1))
        );
      }
    }
    return esc(raw);
  }

  function render(doneLines, partialLine, partialLen, showCursor) {
    var parts = doneLines.slice();
    if (partialLine) {
      parts.push(highlightLine(partialLine, partialLen));
    }
    var html = parts.join("\n");
    if (showCursor) {
      html += '<span class="home-guide-code-cursor" aria-hidden="true"></span>';
    }
    codeEl.innerHTML = html;
    viewport.scrollTop = viewport.scrollHeight;
  }

  async function runLoop() {
    var doneLines = [];
    render(doneLines, null, 0, true);
    viewport.scrollTop = 0;
    await sleep(400);

    for (var i = 0; i < LINES.length; i++) {
      var line = LINES[i];
      if (!line.t) {
        doneLines.push("");
        render(doneLines, null, 0, true);
        await sleep(LINE_PAUSE_MS * 2);
        continue;
      }
      for (var c = 0; c <= line.t.length; c++) {
        render(doneLines, line, c, true);
        await sleep(CHAR_MS);
      }
      doneLines.push(highlightLine(line, line.t.length));
      render(doneLines, null, 0, true);
      await sleep(LINE_PAUSE_MS);
    }

    render(doneLines, null, 0, false);
    await sleep(END_PAUSE_MS);
    runLoop();
  }

  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var staticLines = LINES.map(function (ln) {
      return highlightLine(ln, ln.t.length);
    });
    codeEl.innerHTML = staticLines.join("\n");
    viewport.scrollTop = viewport.scrollHeight;
    return;
  }

  runLoop();
})();
