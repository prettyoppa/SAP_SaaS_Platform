/**
 * 홈 히어로 «사용 안내» — Markdown 평문 타이핑 → 렌더 유지 → 반복 (KO/EN)
 */
(function () {
  "use strict";

  var root = document.querySelector("[data-home-guide-text-demo]");
  if (!root) return;

  var typingEl = root.querySelector(".home-guide-text-typing");
  var finalTpl = root.querySelector(".home-guide-text-final");
  var viewport = root.querySelector(".home-guide-text-viewport");
  var bundleEl = document.getElementById("home-guide-text-bundle-json");
  if (!typingEl || !finalTpl || !viewport || !bundleEl) return;

  var BUNDLE;
  try {
    BUNDLE = JSON.parse(bundleEl.textContent || "{}");
  } catch (e) {
    BUNDLE = {};
  }

  var CHAR_MS = 28;
  var LINE_PAUSE_MS = 80;
  var HOLD_MS = 10000;
  var runGen = 0;

  function siteLang() {
    return localStorage.getItem("lang") === "en" ? "en" : "ko";
  }

  function hasContent(block) {
    if (!block || !Array.isArray(block.lines)) return false;
    return block.lines.some(function (ln) {
      return String(ln || "").trim().length > 0;
    });
  }

  function pickLocaleBlock(lang) {
    var ko = BUNDLE.ko || { lines: [], html: "" };
    var en = BUNDLE.en || { lines: [], html: "" };
    if (lang === "en" && hasContent(en)) return en;
    if (hasContent(ko)) return ko;
    if (lang === "en" && hasContent(en)) return en;
    return hasContent(en) ? en : ko;
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function renderTyping(doneLines, partialLine, partialLen, showCursor) {
    var parts = doneLines.slice();
    if (partialLine !== null && partialLine !== undefined) {
      parts.push(esc(String(partialLine).slice(0, partialLen)));
    }
    var html = parts
      .map(function (ln) {
        return ln === "" ? "<br>" : esc(ln);
      })
      .join("<br>");
    if (showCursor) {
      html += '<span class="home-guide-text-cursor" aria-hidden="true"></span>';
    }
    typingEl.innerHTML = html;
    typingEl.classList.remove("d-none");
    finalTpl.classList.add("d-none");
    finalTpl.setAttribute("hidden", "hidden");
    finalTpl.setAttribute("aria-hidden", "true");
    viewport.scrollTop = viewport.scrollHeight;
  }

  function showFinal(html) {
    typingEl.innerHTML = "";
    typingEl.classList.add("d-none");
    finalTpl.innerHTML = html || "";
    finalTpl.classList.remove("d-none");
    finalTpl.removeAttribute("hidden");
    finalTpl.setAttribute("aria-hidden", "false");
    viewport.scrollTop = 0;
  }

  async function runLoop(gen) {
    var block = pickLocaleBlock(siteLang());
    var LINES = block.lines || [];
    var FINAL_HTML = block.html || "";
    if (!hasContent(block)) return;

    var doneLines = [];
    renderTyping([], "", 0, true);
    viewport.scrollTop = 0;
    await sleep(350);
    if (gen !== runGen) return;

    for (var i = 0; i < LINES.length; i++) {
      if (gen !== runGen) return;
      var line = String(LINES[i]);
      if (!line) {
        doneLines.push("");
        renderTyping(doneLines, null, 0, true);
        await sleep(LINE_PAUSE_MS * 2);
        continue;
      }
      for (var c = 0; c <= line.length; c++) {
        if (gen !== runGen) return;
        renderTyping(doneLines, line, c, true);
        await sleep(CHAR_MS);
      }
      doneLines.push(line);
      renderTyping(doneLines, null, 0, true);
      await sleep(LINE_PAUSE_MS);
    }

    if (gen !== runGen) return;
    renderTyping(doneLines, null, 0, false);
    await sleep(400);
    if (gen !== runGen) return;
    showFinal(FINAL_HTML);
    await sleep(HOLD_MS);
    if (gen !== runGen) return;
    finalTpl.classList.add("d-none");
    finalTpl.setAttribute("hidden", "hidden");
    runLoop(gen);
  }

  function start() {
    runGen += 1;
    var gen = runGen;
    runLoop(gen);
  }

  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    showFinal(pickLocaleBlock(siteLang()).html || "");
    return;
  }

  start();

  document.addEventListener("app:langchange", function () {
    start();
  });
})();
