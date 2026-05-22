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

  function waitForLayout() {
    return new Promise(function (resolve) {
      requestAnimationFrame(function () {
        requestAnimationFrame(resolve);
      });
    });
  }

  function getRevealViewportWidth(viewport, stage) {
    var el = viewport || stage;
    if (!el) return 0;
    var w = el.getBoundingClientRect().width;
    if (w <= 4 && viewport && viewport.parentElement) {
      w = viewport.parentElement.getBoundingClientRect().width;
    }
    return Math.floor(w);
  }

  /** 펼침 줄 분할용 숨김 요소 (stage 비우기와 분리) */
  function getMeasureProbe(root) {
    if (!root._tileRevealMeasureProbe) {
      var probe = document.createElement("div");
      probe.className = "home-tile-reveal-line-inner";
      probe.setAttribute("aria-hidden", "true");
      probe.style.cssText =
        "position:absolute;left:-10000px;top:0;visibility:hidden;pointer-events:none;max-height:none;clip-path:none;";
      root.appendChild(probe);
      root._tileRevealMeasureProbe = probe;
    }
    return root._tileRevealMeasureProbe;
  }

  function probeLineHeight(probe) {
    var prev = probe.textContent;
    probe.textContent = "Hg";
    var cs = getComputedStyle(probe);
    var lh = parseFloat(cs.lineHeight);
    if (isNaN(lh) || lh <= 0) lh = parseFloat(cs.fontSize) * 1.35;
    probe.textContent = prev;
    return lh || 16;
  }

  function wrapSegmentToVisualLinesDom(text, widthPx, probe) {
    text = String(text || "");
    if (!text) return [""];
    if (widthPx <= 4) return [text];

    probe.style.width = widthPx + "px";
    probe.style.whiteSpace = "normal";
    probe.style.wordBreak = "break-word";
    probe.style.overflowWrap = "anywhere";

    var lh = probeLineHeight(probe);

    function isSingleLine(str) {
      probe.textContent = str;
      return probe.offsetHeight <= lh * 1.55;
    }

    if (isSingleLine(text)) return [text];

    function wrapByChars(src) {
      var out = [];
      var cur = "";
      var chars = Array.from(src);
      for (var i = 0; i < chars.length; i++) {
        probe.textContent = cur + chars[i];
        if (cur && probe.offsetHeight > lh * 1.55) {
          out.push(cur);
          cur = chars[i];
        } else {
          cur += chars[i];
        }
      }
      if (cur) out.push(cur);
      return out.length ? out : [src];
    }

    if (!/\s/.test(text)) return wrapByChars(text);

    var lines = [];
    var tokens = text.split(/(\s+)/);
    var cur = "";
    for (var t = 0; t < tokens.length; t++) {
      var token = tokens[t];
      if (!token) continue;
      probe.textContent = cur + token;
      if (cur.trim() && probe.offsetHeight > lh * 1.55) {
        lines.push(cur.replace(/\s+$/, ""));
        cur = token.replace(/^\s+/, "");
      } else {
        cur += token;
      }
    }
    if (cur.trim()) lines.push(cur.replace(/\s+$/, ""));

    var fixed = [];
    lines.forEach(function (ln) {
      if (!ln) return;
      if (isSingleLine(ln)) fixed.push(ln);
      else wrapByChars(ln).forEach(function (v) {
        fixed.push(v);
      });
    });
    return fixed.length ? fixed : wrapByChars(text);
  }

  function expandLogicalLinesToVisual(logicalLines, viewportEl, root) {
    var width = getRevealViewportWidth(viewportEl, null);
    var probe = getMeasureProbe(root);
    var visual = [];
    (logicalLines || []).forEach(function (ln) {
      var text = String(ln || "").trim();
      if (!text) return;
      wrapSegmentToVisualLinesDom(text, width, probe).forEach(function (v) {
        if (String(v || "").trim()) visual.push(v);
      });
    });
    return visual;
  }

  function appendRevealLine(stage, text, revealed) {
    var wrap = document.createElement("div");
    wrap.className = "home-tile-reveal-line" + (revealed ? " is-revealed" : "");
    var inner = document.createElement("div");
    inner.className = "home-tile-reveal-line-inner";
    inner.textContent = text || "";
    wrap.appendChild(inner);
    stage.appendChild(wrap);
    return { wrap: wrap, inner: inner };
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
    var viewport = root.querySelector(".home-guide-text-viewport");
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
    var revealBusy = false;
    var lastViewportWidth = getRevealViewportWidth(viewport, stage);
    var pendingRelayout = false;

    function clearStage() {
      stage.innerHTML = "";
    }

    function scrollViewportEnd() {
      if (!viewport) return;
      var max = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
      viewport.scrollTop = max;
    }

    function showAllLines(logicalLines) {
      clearStage();
      var visual = expandLogicalLinesToVisual(logicalLines, viewport, root);
      visual.forEach(function (ln) {
        appendRevealLine(stage, ln, true);
      });
      scrollViewportEnd();
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
      var logical = block.lines || [];
      if (!hasContent(block)) return;

      revealBusy = true;
      try {
        clearStage();
        if (viewport) viewport.scrollTop = 0;
        if (REVEAL_START_PAUSE_MS > 0) await sleep(REVEAL_START_PAUSE_MS);
        if (gen !== runGen) return;

        await waitForLayout();
        if (gen !== runGen) return;

        lastViewportWidth = getRevealViewportWidth(viewport, stage);
        var visual = expandLogicalLinesToVisual(logical, viewport, root);
        for (var vi = 0; vi < visual.length; vi++) {
          if (gen !== runGen) return;
          var lineText = String(visual[vi] || "").trim();
          if (!lineText) continue;
          var row = appendRevealLine(stage, lineText, false);
          scrollViewportEnd();
          void row.wrap.offsetWidth;
          row.wrap.classList.add("is-revealed");
          await waitTransition(row.inner);
          scrollViewportEnd();
          if (gen !== runGen) return;
          if (REVEAL_LINE_GAP_MS > 0 && vi < visual.length - 1) await sleep(REVEAL_LINE_GAP_MS);
        }

        scrollViewportEnd();
        await sleep(holdMs);
      } finally {
        if (gen === runGen) {
          revealBusy = false;
          if (pendingRelayout) {
            pendingRelayout = false;
            start();
          }
        }
      }
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
    if (viewport && typeof ResizeObserver !== "undefined") {
      var resizeTimer = null;
      var ro = new ResizeObserver(function () {
        var w = getRevealViewportWidth(viewport, stage);
        if (w <= 4 || Math.abs(w - lastViewportWidth) < 2) return;
        lastViewportWidth = w;
        if (revealBusy) {
          pendingRelayout = true;
          return;
        }
        if (resizeTimer) clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
          resizeTimer = null;
          start();
        }, 280);
      });
      ro.observe(viewport);
    }
  }

  document.querySelectorAll("[data-home-typing-text]").forEach(function (root) {
    if ((root.getAttribute("data-typing-mode") || "typing") === "reveal") {
      initRevealRoot(root);
    } else {
      initTypingRoot(root);
    }
  });
})();
