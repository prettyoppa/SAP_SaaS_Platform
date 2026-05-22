/**
 * 홈 텍스트 애니메이션 — «사용 안내» 타이핑 + 서비스 타일 줄 단위 펼침 (KO/EN)
 */
(function () {
  "use strict";

  var CHAR_MS = 110;
  var LINE_PAUSE_MS = 320;
  var HOLD_MS = 10000;
  var START_PAUSE_MS = 550;
  var REVEAL_LINE_MS = 11000;
  var REVEAL_LINE_GAP_MS = 0;
  var REVEAL_HOLD_MS = 1500;
  var REVEAL_START_PAUSE_MS = 0;

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

  function parseBundle(bundleEl) {
    try {
      return JSON.parse(bundleEl.textContent || "{}");
    } catch (e) {
      return {};
    }
  }

  function initTypingRoot(root) {
    var stage = root.querySelector(".home-guide-text-lines");
    var viewport = root.querySelector(".home-guide-text-viewport");
    var bundleEl = root.querySelector("script.home-typing-bundle");
    if (!stage || !viewport || !bundleEl) return;

    var bundle = parseBundle(bundleEl);
    var holdMs = HOLD_MS;
    var holdAttr = root.getAttribute("data-typing-hold-ms");
    if (holdAttr) {
      var parsed = parseInt(holdAttr, 10);
      if (!isNaN(parsed) && parsed >= 0) holdMs = parsed;
    }

    var runGen = 0;
    var scrollPending = false;
    var lastScrollAt = 0;

    function clearStage() {
      stage.innerHTML = "";
    }

    function showAllLines(lines) {
      clearStage();
      (lines || []).forEach(function (ln, idx) {
        var el = document.createElement("div");
        el.className = "home-guide-text-line";
        if (idx === 0) el.classList.add("is-lead");
        el.textContent = ln || "";
        stage.appendChild(el);
      });
      scrollToEnd(false);
    }

    function scrollToEnd(smooth) {
      var max = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
      if (max <= 0) return;
      if (smooth && typeof viewport.scrollTo === "function") {
        var now = Date.now();
        if (now - lastScrollAt < 120) return;
        lastScrollAt = now;
        viewport.scrollTo({ top: max, behavior: "smooth" });
        return;
      }
      viewport.scrollTop = max;
    }

    function scheduleScrollToEnd(smooth) {
      if (scrollPending) return;
      scrollPending = true;
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          scrollPending = false;
          scrollToEnd(smooth);
        });
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
        if (i % 3 === 0 || i === text.length - 1) scheduleScrollToEnd(true);
        await sleep(CHAR_MS);
      }
      lineEl.classList.remove("is-typing");
      scheduleScrollToEnd(true);
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
    document.addEventListener("app:langchange", start);
  }

  function initRevealRoot(root) {
    var stage = root.querySelector(".home-guide-text-lines");
    var bundleEl = root.querySelector("script.home-typing-bundle");
    if (!stage || !bundleEl) return;

    var bundle = parseBundle(bundleEl);
    var holdMs = REVEAL_HOLD_MS;
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
        var wrap = document.createElement("div");
        wrap.className = "home-tile-reveal-line is-revealed";
        var inner = document.createElement("div");
        inner.className = "home-tile-reveal-line-inner";
        inner.textContent = ln || "";
        wrap.appendChild(inner);
        stage.appendChild(wrap);
      });
    }

    function revealDurationMs() {
      var raw = getComputedStyle(root).getPropertyValue("--tile-reveal-duration").trim();
      if (!raw) return REVEAL_LINE_MS;
      var n = parseFloat(raw);
      if (isNaN(n)) return REVEAL_LINE_MS;
      if (raw.indexOf("ms") !== -1) return n;
      return n * 1000;
    }

    function waitTransition(el) {
      var durationMs = revealDurationMs();
      return new Promise(function (resolve) {
        var done = false;
        function finish() {
          if (done) return;
          done = true;
          el.removeEventListener("transitionend", onEnd);
          resolve();
        }
        function onEnd(ev) {
          if (ev.target !== el) return;
          if (ev.propertyName && ev.propertyName !== "clip-path") return;
          finish();
        }
        el.addEventListener("transitionend", onEnd);
        setTimeout(finish, durationMs + 60);
      });
    }

    async function runReveal(gen) {
      var block = pickLocaleBlock(bundle, siteLang());
      var lines = block.lines || [];
      if (!hasContent(block)) return;

      clearStage();
      if (REVEAL_START_PAUSE_MS > 0) await sleep(REVEAL_START_PAUSE_MS);
      if (gen !== runGen) return;

      for (var li = 0; li < lines.length; li++) {
        if (gen !== runGen) return;
        var text = String(lines[li] || "");
        var wrap = document.createElement("div");
        wrap.className = "home-tile-reveal-line";
        var inner = document.createElement("div");
        inner.className = "home-tile-reveal-line-inner";
        inner.textContent = text;
        wrap.appendChild(inner);
        stage.appendChild(wrap);
        void wrap.offsetWidth;
        wrap.classList.add("is-revealed");
        await waitTransition(inner);
        if (gen !== runGen) return;
        if (REVEAL_LINE_GAP_MS > 0 && li < lines.length - 1) await sleep(REVEAL_LINE_GAP_MS);
      }

      await sleep(holdMs);
    }

    function start() {
      runGen += 1;
      var gen = runGen;
      (async function loop() {
        while (gen === runGen) {
          await runReveal(gen);
        }
      })();
    }

    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      showAllLines(pickLocaleBlock(bundle, siteLang()).lines || []);
      return;
    }

    start();
    document.addEventListener("app:langchange", start);
  }

  document.querySelectorAll("[data-home-typing-text]").forEach(function (root) {
    if ((root.getAttribute("data-typing-mode") || "typing") === "reveal") {
      initRevealRoot(root);
    } else {
      initTypingRoot(root);
    }
  });
})();
