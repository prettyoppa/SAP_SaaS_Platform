/**
 * 홈 히어로 «사용 안내» — Markdown 서식 유지, 블록별 위→아래 clip 펼침 (KO/EN)
 */
(function () {
  "use strict";

  var root = document.querySelector("[data-home-guide-text-demo]");
  if (!root) return;

  var stage = root.querySelector(".home-guide-text-reveal");
  var viewport = root.querySelector(".home-guide-text-viewport");
  var bundleEl = document.getElementById("home-guide-text-bundle-json");
  if (!stage || !viewport || !bundleEl) return;

  var BUNDLE;
  try {
    BUNDLE = JSON.parse(bundleEl.textContent || "{}");
  } catch (e) {
    BUNDLE = {};
  }

  /** 블록(제목·문단·목록 항목)당 펼침 시간 — 내부도 위→아래로 서서히 드러남 */
  var LINE_REVEAL_MS = 2000;
  var BLOCK_GAP_MS = 140;
  var HOLD_MS = 10000;
  var START_PAUSE_MS = 400;
  var runGen = 0;

  var REVEAL_SELECTOR =
    "h1,h2,h3,h4,h5,h6,p,li,blockquote,pre,hr";

  function siteLang() {
    return localStorage.getItem("lang") === "en" ? "en" : "ko";
  }

  function hasContent(block) {
    return block && String(block.html || "").trim().length > 0;
  }

  function pickLocaleBlock(lang) {
    var ko = BUNDLE.ko || { html: "" };
    var en = BUNDLE.en || { html: "" };
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

  function collectRevealUnits(container) {
    var units = Array.prototype.slice.call(
      container.querySelectorAll(REVEAL_SELECTOR)
    );
    if (units.length) return units;
    if (!container.innerHTML.trim()) return [];
    var wrap = document.createElement("div");
    wrap.className = "home-guide-reveal-block";
    wrap.innerHTML = container.innerHTML;
    container.innerHTML = "";
    container.appendChild(wrap);
    return [wrap];
  }

  function resetUnits(units) {
    units.forEach(function (el) {
      el.classList.remove("is-revealed");
      el.classList.add("home-guide-reveal-block");
    });
  }

  function animateReveal(el) {
    return new Promise(function (resolve) {
      var settled = false;
      function finish() {
        if (settled) return;
        settled = true;
        el.removeEventListener("transitionend", onEnd);
        resolve();
      }
      function onEnd(e) {
        if (e.target === el && e.propertyName === "clip-path") finish();
      }
      el.classList.add("home-guide-reveal-block");
      el.addEventListener("transitionend", onEnd);
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          el.classList.add("is-revealed");
        });
      });
      setTimeout(finish, LINE_REVEAL_MS + 120);
    });
  }

  async function runReveal(gen) {
    var block = pickLocaleBlock(siteLang());
    var html = block.html || "";
    if (!hasContent(block)) return;

    stage.innerHTML = html;
    var units = collectRevealUnits(stage);
    resetUnits(units);
    viewport.scrollTop = 0;
    await sleep(START_PAUSE_MS);
    if (gen !== runGen) return;

    for (var i = 0; i < units.length; i++) {
      if (gen !== runGen) return;
      await animateReveal(units[i]);
      if (gen !== runGen) return;
      if (i < units.length - 1) await sleep(BLOCK_GAP_MS);
      viewport.scrollTop = viewport.scrollHeight;
    }

    await sleep(HOLD_MS);
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

  function showAll() {
    var html = pickLocaleBlock(siteLang()).html || "";
    stage.innerHTML = html;
    collectRevealUnits(stage).forEach(function (el) {
      el.classList.add("home-guide-reveal-block", "is-revealed");
    });
  }

  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    showAll();
    return;
  }

  start();

  document.addEventListener("app:langchange", function () {
    start();
  });
})();
