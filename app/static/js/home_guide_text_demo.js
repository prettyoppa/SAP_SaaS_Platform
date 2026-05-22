/**
 * 홈 타이핑 텍스트 — «사용 안내» 패널·서비스 타일 설명 (KO/EN, 인스턴스별)
 */
(function () {
  "use strict";

  var CHAR_MS = 110;
  var LINE_PAUSE_MS = 320;
  var HOLD_MS = 10000;
  var START_PAUSE_MS = 550;

  function siteLang() {
    return localStorage.getItem("lang") === "en" ? "en" : "ko";
  }

  function hasContent(block) {
    if (!block || !block.lines) return false;
    return block.lines.some(function (ln) {
      return String(ln || "").trim().length > 0;
    });
  }

  function pickLocaleBlock(bundle, lang) {
    var ko = bundle.ko || { lines: [] };
    var en = bundle.en || { lines: [] };
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

  function initTypingRoot(root) {
    var stage = root.querySelector(".home-guide-text-lines");
    var viewport = root.querySelector(".home-guide-text-viewport");
    var bundleEl = root.querySelector("script.home-typing-bundle");
    if (!stage || !viewport || !bundleEl) return;

    var bundle;
    try {
      bundle = JSON.parse(bundleEl.textContent || "{}");
    } catch (e) {
      bundle = {};
    }

    var holdMs = HOLD_MS;
    var holdAttr = root.getAttribute("data-typing-hold-ms");
    if (holdAttr) {
      var parsed = parseInt(holdAttr, 10);
      if (!isNaN(parsed) && parsed >= 0) holdMs = parsed;
    }

    var runGen = 0;

    function clearStage() {
      stage.innerHTML = "";
    }

    function showAllLines(lines) {
      clearStage();
      (lines || []).forEach(function (ln) {
        var el = document.createElement("div");
        el.className = "home-guide-text-line";
        el.textContent = ln || "";
        stage.appendChild(el);
      });
    }

    function setViewportLive(on) {
      viewport.classList.toggle("is-live", !!on);
      root.classList.toggle("is-typing-active", !!on);
    }

    async function typeLine(lineEl, text, gen) {
      lineEl.classList.add("is-typing");
      lineEl.textContent = "";
      for (var i = 0; i < text.length; i++) {
        if (gen !== runGen) return;
        var ch = document.createElement("span");
        ch.className = "home-guide-text-char";
        ch.textContent = text.charAt(i);
        lineEl.appendChild(ch);
        void ch.offsetWidth;
        ch.classList.add("is-visible");
        await sleep(CHAR_MS);
      }
      lineEl.classList.remove("is-typing");
    }

    async function runTyping(gen) {
      var block = pickLocaleBlock(bundle, siteLang());
      var lines = block.lines || [];
      if (!hasContent(block)) return;

      clearStage();
      viewport.scrollTop = 0;
      setViewportLive(true);
      try {
        await sleep(START_PAUSE_MS);
        if (gen !== runGen) return;

        for (var li = 0; li < lines.length; li++) {
          if (gen !== runGen) return;
          var text = String(lines[li] || "");
          var lineEl = document.createElement("div");
          lineEl.className = "home-guide-text-line";
          if (li === 0) lineEl.classList.add("is-lead");
          stage.appendChild(lineEl);

          if (!text.trim()) {
            lineEl.textContent = "";
            await sleep(LINE_PAUSE_MS);
            continue;
          }

          await typeLine(lineEl, text, gen);
          if (gen !== runGen) return;
          await sleep(LINE_PAUSE_MS);
          viewport.scrollTop = viewport.scrollHeight;
        }

        await sleep(holdMs);
      } finally {
        if (gen === runGen) setViewportLive(false);
      }
    }

    function start() {
      runGen += 1;
      var gen = runGen;
      (async function loop() {
        while (gen === runGen) {
          await runTyping(gen);
        }
      })();
    }

    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      showAllLines(pickLocaleBlock(bundle, siteLang()).lines || []);
      return;
    }

    start();

    document.addEventListener("app:langchange", function () {
      start();
    });
  }

  var roots = document.querySelectorAll("[data-home-typing-text]");
  roots.forEach(initTypingRoot);
})();
