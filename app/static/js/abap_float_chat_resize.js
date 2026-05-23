/**
 * AI 문의 플로팅 패널 리사이즈
 * - 패널(좌상단): 너비·높이 — 높이는 대화 영역(.abap-float-chat-body)만 늘어남, 입력창 높이는 유지
 * - 입력창(우상단): 높이만 조절; 너비는 패널 너비와 함께 이동
 */
(function () {
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

    function loadStoredSizeIfAny() {
      if (!desktopOnly()) {
        panel.style.width = '';
        panel.style.height = '';
        if (ta) {
          ta.style.height = '';
          ta.style.width = '';
        }
        return;
      }
      try {
        var raw = localStorage.getItem(sizeKey);
        if (!raw) return;
        var o = JSON.parse(raw);
        var b = sizeBounds();
        if (typeof o.w === 'number') {
          panel.style.width = clamp(o.w, b.minW, b.maxW) + 'px';
        }
        if (typeof o.h === 'number') {
          panel.style.height = clamp(o.h, b.minH, b.maxH) + 'px';
        }
        if (ta && typeof o.taH === 'number') {
          ta.style.height = clamp(o.taH, b.taMinH, b.taMaxH) + 'px';
          ta.style.minHeight = b.taMinH + 'px';
          ta.style.width = '';
          ta.style.maxWidth = '100%';
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
      var r = panel.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return;
      panel.style.width = clamp(Math.round(r.width), b.minW, b.maxW) + 'px';
      panel.style.height = clamp(Math.round(r.height), b.minH, b.maxH) + 'px';
    }

    function scheduleSaveSize() {
      if (!desktopOnly()) return;
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(function () {
        saveTimer = null;
        if (panel.hasAttribute('hidden')) return;
        try {
          var b = sizeBounds();
          var r = panel.getBoundingClientRect();
          var payload = {
            w: clamp(Math.round(r.width), b.minW, b.maxW),
            h: clamp(Math.round(r.height), b.minH, b.maxH),
          };
          if (ta) {
            payload.taH = clamp(Math.round(ta.offsetHeight), b.taMinH, b.taMaxH);
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
          panel.style.width = clamp(Math.round(w0 + dw), b.minW, b.maxW) + 'px';
          panel.style.height = clamp(Math.round(h0 + dh), b.minH, b.maxH) + 'px';
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
          scheduleSaveSize();
        }
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);
      });
    }

    function bindTextareaResizeGrip() {
      if (!ta || !taGrip) return;
      var wrap = ta.closest ? ta.closest('.abap-followup-ta-wrap') : null;
      if (!wrap) return;
      taGrip.addEventListener('pointerdown', function (e) {
        if (!desktopOnly() || e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        var pid = e.pointerId;
        try {
          taGrip.setPointerCapture(pid);
        } catch (err) {}
        var startX = e.clientX;
        var startY = e.clientY;
        var h0 = ta.offsetHeight;
        var panelW0 = panel.offsetWidth;
        function move(ev) {
          if (!desktopOnly()) return;
          var b = sizeBounds();
          var dh = startY - ev.clientY;
          var dw = startX - ev.clientX;
          var nh = clamp(Math.round(h0 + dh), b.taMinH, b.taMaxH);
          ta.style.height = nh + 'px';
          ta.style.minHeight = b.taMinH + 'px';
          ta.style.width = '';
          ta.style.maxWidth = '100%';
          panel.style.width = clamp(Math.round(panelW0 + dw), b.minW, b.maxW) + 'px';
        }
        function up(ev) {
          try {
            if (ev && taGrip.hasPointerCapture && taGrip.hasPointerCapture(ev.pointerId)) {
              taGrip.releasePointerCapture(ev.pointerId);
            }
          } catch (err2) {}
          window.removeEventListener('pointermove', move);
          window.removeEventListener('pointerup', up);
          window.removeEventListener('pointercancel', up);
          scheduleSaveSize();
        }
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);
      });
    }

    bindPanelResizeGrip();
    bindTextareaResizeGrip();
    window.addEventListener('resize', clampPanelToViewport);

    return {
      loadStoredSizeIfAny: loadStoredSizeIfAny,
      clampPanelToViewport: clampPanelToViewport,
      scheduleSaveSize: scheduleSaveSize,
    };
  }

  window.initAbapFloatChatResize = initAbapFloatChatResize;
})();
