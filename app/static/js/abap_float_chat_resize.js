/**
 * AI 문의 플로팅 패널 리사이즈
 * - 패널(좌상단): 너비·높이 — 높이는 대화 영역(.abap-float-chat-body)만 늘어남, 입력창 높이는 유지
 * - 입력창(우상단): 높이만 조절; 너비는 패널 너비와 함께 이동
 */
(function () {
  var TOP_VIEWPORT_MARGIN = 12;
  var FLOAT_STACK_GAP = 8;

  function clamp(n, lo, hi) {
    return Math.max(lo, Math.min(hi, n));
  }

  function desktopOnly() {
    return !(window.matchMedia && window.matchMedia('(max-width: 576px)').matches);
  }

  function sizeBounds() {
    var vw = window.innerWidth || 800;
    var vh = window.innerHeight || 600;
    return {
      minW: 280,
      minH: 260,
      maxW: Math.min(vw * 0.96, 920),
      maxH: vh * 0.9,
      taMinH: 56,
      taMaxH: 420,
    };
  }

  function siblingsBelowPanelHeight(panel) {
    var root = panel.closest ? panel.closest('.abap-float-chat') : null;
    if (!root) return 0;
    var total = 0;
    var pastPanel = false;
    Array.prototype.forEach.call(root.children, function (el) {
      if (el === panel) {
        pastPanel = true;
        return;
      }
      if (!pastPanel) return;
      if (el.classList && el.classList.contains('abap-float-chat-panel') && el.hasAttribute('hidden')) {
        return;
      }
      var h = el.getBoundingClientRect().height;
      if (h > 0.5) total += h + FLOAT_STACK_GAP;
    });
    return total;
  }

  function maxPanelHeight(panel) {
    var b = sizeBounds();
    var root = panel.closest ? panel.closest('.abap-float-chat') : null;
    if (!root) return b.maxH;
    var rootBottom = root.getBoundingClientRect().bottom;
    var below = siblingsBelowPanelHeight(panel);
    var avail = Math.floor(rootBottom - TOP_VIEWPORT_MARGIN - below);
    return clamp(avail, b.minH, b.maxH);
  }

  function initAbapFloatChatResize(opts) {
    var panel = opts && opts.panel;
    var sizeKey = (opts && opts.sizeKey) || '';
    if (!panel || !sizeKey) return null;

    var panelGrip = opts.panelGrip || null;
    var ta =
      (opts.textarea) ||
      (opts.textareaId && document.getElementById(opts.textareaId)) ||
      panel.querySelector('.abap-followup-msg-input');
    var taGrip = opts.taGrip || null;
    var saveTimer = null;

    function activeComposeTextarea() {
      return panel.querySelector('.offer-member-inquiry-compose:not([hidden]) .offer-member-inquiry-msg')
        || panel.querySelector('.abap-followup-msg-input')
        || ta;
    }

    function applyTextareaHeight(taEl, heightPx) {
      if (!taEl) return;
      var b = sizeBounds();
      var nh = clamp(Math.round(heightPx), b.taMinH, b.taMaxH);
      taEl.style.height = nh + 'px';
      taEl.style.minHeight = b.taMinH + 'px';
      taEl.style.width = '';
      taEl.style.maxWidth = '100%';
    }

    function loadStoredSizeIfAny() {
      if (!desktopOnly()) {
        panel.style.width = '';
        panel.style.height = '';
        panel.querySelectorAll('.abap-followup-msg-input').forEach(function (el) {
          el.style.height = '';
          el.style.width = '';
        });
        return;
      }
      try {
        var raw = localStorage.getItem(sizeKey);
        if (!raw) return;
        var o = JSON.parse(raw);
        var b = sizeBounds();
        var maxH = maxPanelHeight(panel);
        if (typeof o.w === 'number') {
          panel.style.width = clamp(o.w, b.minW, b.maxW) + 'px';
        }
        if (typeof o.h === 'number') {
          panel.style.height = clamp(o.h, b.minH, maxH) + 'px';
        }
        if (typeof o.taH === 'number') {
          panel.querySelectorAll('.offer-member-inquiry-msg').forEach(function (el) {
            applyTextareaHeight(el, o.taH);
          });
          var activeTa = activeComposeTextarea();
          if (activeTa && !activeTa.classList.contains('offer-member-inquiry-msg')) {
            applyTextareaHeight(activeTa, o.taH);
          } else if (!panel.querySelector('.offer-member-inquiry-msg') && ta) {
            applyTextareaHeight(ta, o.taH);
          }
        }
      } catch (e) { /* ignore */ }
    }

    function clampPanelToViewport() {
      if (panel.hasAttribute('hidden')) return;
      if (!desktopOnly()) {
        panel.style.width = '';
        panel.style.height = '';
        return;
      }
      var b = sizeBounds();
      var maxH = maxPanelHeight(panel);
      var r = panel.getBoundingClientRect();
      var w = r.width > 0.5 ? Math.round(r.width) : (panel.offsetWidth || b.minW);
      var h = r.height > 0.5 ? Math.round(r.height) : (panel.offsetHeight || b.minH);
      panel.style.width = clamp(w, b.minW, b.maxW) + 'px';
      panel.style.height = clamp(h, b.minH, maxH) + 'px';
      r = panel.getBoundingClientRect();
      if (r.top < TOP_VIEWPORT_MARGIN) {
        var reduced = clamp(Math.round(r.height - (TOP_VIEWPORT_MARGIN - r.top)), b.minH, maxH);
        panel.style.height = reduced + 'px';
      }
    }

    function scheduleSaveSize() {
      if (!desktopOnly()) return;
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(function () {
        saveTimer = null;
        if (panel.hasAttribute('hidden')) return;
        try {
          var b = sizeBounds();
          var maxH = maxPanelHeight(panel);
          var r = panel.getBoundingClientRect();
          var payload = {
            w: clamp(Math.round(r.width), b.minW, b.maxW),
            h: clamp(Math.round(r.height), b.minH, maxH),
          };
          var activeTa = activeComposeTextarea();
          if (activeTa) {
            payload.taH = clamp(Math.round(activeTa.offsetHeight), b.taMinH, b.taMaxH);
          }
          localStorage.setItem(sizeKey, JSON.stringify(payload));
        } catch (e) { /* ignore */ }
      }, 200);
    }

    function bindPanelResizeGrip() {
      if (!panelGrip) return;
      panelGrip.addEventListener('pointerdown', function (e) {
        if (!desktopOnly() || e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        var pid = e.pointerId;
        try {
          panelGrip.setPointerCapture(pid);
        } catch (err) {}
        var startX = e.clientX;
        var startY = e.clientY;
        var rect = panel.getBoundingClientRect();
        var w0 = rect.width;
        var h0 = rect.height;
        function move(ev) {
          if (!desktopOnly()) return;
          var dw = startX - ev.clientX;
          var dh = startY - ev.clientY;
          var b = sizeBounds();
          var maxH = maxPanelHeight(panel);
          panel.style.width = clamp(Math.round(w0 + dw), b.minW, b.maxW) + 'px';
          panel.style.height = clamp(Math.round(h0 + dh), b.minH, maxH) + 'px';
        }
        function up(ev) {
          try {
            if (ev && panelGrip.hasPointerCapture && panelGrip.hasPointerCapture(ev.pointerId)) {
              panelGrip.releasePointerCapture(ev.pointerId);
            }
          } catch (err2) {}
          window.removeEventListener('pointermove', move);
          window.removeEventListener('pointerup', up);
          window.removeEventListener('pointercancel', up);
          clampPanelToViewport();
          scheduleSaveSize();
        }
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);
      });
    }

    function bindTextareaResizeGripForPair(taEl, gripEl) {
      if (!taEl || !gripEl) return;
      var wrap = taEl.closest ? taEl.closest('.abap-followup-ta-wrap') : null;
      if (!wrap) return;
      gripEl.addEventListener('pointerdown', function (e) {
        if (!desktopOnly() || e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        var pid = e.pointerId;
        try {
          gripEl.setPointerCapture(pid);
        } catch (err) {}
        var startX = e.clientX;
        var startY = e.clientY;
        var h0 = Math.max(taEl.offsetHeight, sizeBounds().taMinH);
        var panelW0 = panel.offsetWidth;
        function move(ev) {
          if (!desktopOnly()) return;
          var b = sizeBounds();
          var dh = startY - ev.clientY;
          var dw = startX - ev.clientX;
          applyTextareaHeight(taEl, h0 + dh);
          panel.style.width = clamp(Math.round(panelW0 + dw), b.minW, b.maxW) + 'px';
        }
        function up(ev) {
          try {
            if (ev && gripEl.hasPointerCapture && gripEl.hasPointerCapture(ev.pointerId)) {
              gripEl.releasePointerCapture(ev.pointerId);
            }
          } catch (err2) {}
          window.removeEventListener('pointermove', move);
          window.removeEventListener('pointerup', up);
          window.removeEventListener('pointercancel', up);
          clampPanelToViewport();
          scheduleSaveSize();
        }
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);
      });
    }

    function bindTextareaResizeGrips() {
      var boundIds = {};
      panel.querySelectorAll('.abap-followup-ta-resize[data-ta-for]').forEach(function (grip) {
        var id = grip.getAttribute('data-ta-for');
        if (!id || boundIds[id]) return;
        var taEl = document.getElementById(id);
        if (!taEl) return;
        boundIds[id] = true;
        bindTextareaResizeGripForPair(taEl, grip);
      });
      if (!Object.keys(boundIds).length && ta && taGrip) {
        bindTextareaResizeGripForPair(ta, taGrip);
      }
    }

    bindPanelResizeGrip();
    bindTextareaResizeGrips();
    window.addEventListener('resize', clampPanelToViewport);

    return {
      loadStoredSizeIfAny: loadStoredSizeIfAny,
      clampPanelToViewport: clampPanelToViewport,
      scheduleSaveSize: scheduleSaveSize,
    };
  }

  window.initAbapFloatChatResize = initAbapFloatChatResize;
})();
