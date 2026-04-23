/**
 * 신규 요청 – 참고 코드 정보 (localStorage, 계정·요청 스코프별, 서버 미전송)
 */
(function () {
  'use strict';

  var MAX_SLOTS = 3;
  var DEBOUNCE_MS = 450;
  var saveTimer = null;
  /** 동시에 펼쳐 보이는 참고 코드 슬롯 수 (1~3, 로컬 저장) */
  var visibleSlotCount = 1;

  var TYPE_OPTIONS = [
    '메인 프로그램',
    'TOP Include',
    'Selection Screen',
    'Form Subroutines',
    'PBO Modules',
    'PAI Modules',
    'Class',
    '기타 Include',
  ];

  function ctx() {
    return window.__RFP_CTX__ || { userId: 0, scope: 'new' };
  }

  function storageKey() {
    var c = ctx();
    return 'sapdevhub_rfp_refcode_v1_u' + c.userId + '_' + c.scope;
  }

  function defaultSections() {
    return [{ type: '메인 프로그램', name: '', code: '' }];
  }

  function loadRaw() {
    try {
      var s = localStorage.getItem(storageKey());
      return s ? JSON.parse(s) : null;
    } catch (e) {
      return null;
    }
  }

  function saveRaw(obj) {
    try {
      localStorage.setItem(storageKey(), JSON.stringify(obj));
    } catch (e) { /* quota */ }
  }

  function makeSectionEl(slotIdx, idx, sec) {
    sec = sec || { type: '메인 프로그램', name: '', code: '' };
    if (TYPE_OPTIONS.indexOf(sec.type) < 0) sec.type = '메인 프로그램';
    var div = document.createElement('div');
    div.className = 'ref-code-section border rounded p-2 mb-2';

    var bar = document.createElement('div');
    bar.className = 'd-flex align-items-center gap-2 flex-wrap mb-2';

    var sel = document.createElement('select');
    sel.className = 'form-select form-select-sm section-type-select';
    sel.style.maxWidth = '220px';
    TYPE_OPTIONS.forEach(function (t) {
      var o = document.createElement('option');
      o.value = t;
      o.textContent = t;
      if (t === sec.type) o.selected = true;
      sel.appendChild(o);
    });

    var nameInp = document.createElement('input');
    nameInp.type = 'text';
    nameInp.className = 'form-control form-control-sm section-name-input';
    nameInp.style.maxWidth = '200px';
    nameInp.value = sec.name || '';

    var rm = document.createElement('button');
    rm.type = 'button';
    rm.className = 'btn btn-sm btn-outline-danger ref-remove-sec';
    rm.textContent = '섹션 삭제';
    if (idx === 0) {
      rm.disabled = true;
    }

    bar.appendChild(sel);
    bar.appendChild(nameInp);
    bar.appendChild(rm);

    var ta = document.createElement('textarea');
    ta.className = 'form-control section-code';
    ta.rows = 8;
    ta.value = sec.code || '';

    div.appendChild(bar);
    div.appendChild(ta);

    rm.addEventListener('click', function () {
      div.remove();
      scheduleSave();
    });

    [sel, nameInp, ta].forEach(function (el) {
      el.addEventListener('input', scheduleSave);
      el.addEventListener('change', scheduleSave);
    });

    return div;
  }

  function rebuildSections(slotIdx, sections) {
    var host = document.getElementById('ref-sections-' + slotIdx);
    if (!host) return;
    host.innerHTML = '';
    var list = sections && sections.length ? sections : defaultSections();
    list.forEach(function (s, i) {
      host.appendChild(makeSectionEl(slotIdx, i, s));
    });
  }

  function setupSlotMaxSelect(slotIdx, clsMod, clsDt, modCountId, dtCountId) {
    var max = 3;
    function bind(cls, countId) {
      var inputs = document.querySelectorAll('.' + cls);
      var countEl = document.getElementById(countId);
      function upd() {
        var checked = document.querySelectorAll('.' + cls + ':checked').length;
        if (countEl) countEl.textContent = checked + ' / ' + max;
        inputs.forEach(function (inp) {
          if (!inp.checked) inp.disabled = checked >= max;
        });
      }
      inputs.forEach(function (inp) {
        inp.addEventListener('change', function () {
          upd();
          scheduleSave();
        });
      });
      upd();
    }
    bind(clsMod, modCountId);
    bind(clsDt, dtCountId);
  }

  function slotHasData(s) {
    if (!s) return false;
    if ((s.program_id || '').trim()) return true;
    if ((s.transaction_code || '').trim()) return true;
    if ((s.title || '').trim()) return true;
    if ((s.sap_modules || []).length) return true;
    if ((s.dev_types || []).length) return true;
    var secs = s.sections || [];
    for (var j = 0; j < secs.length; j++) {
      if ((secs[j].code || '').trim()) return true;
      if ((secs[j].name || '').trim()) return true;
    }
    return false;
  }

  function minSlotsFromPayload(slots) {
    var n = 1;
    if (!slots || !slots.length) return 1;
    for (var i = 0; i < MAX_SLOTS; i++) {
      if (slotHasData(slots[i])) n = i + 1;
    }
    return n;
  }

  function applySlotVisibility() {
    for (var i = 0; i < MAX_SLOTS; i++) {
      var root = document.querySelector('[data-ref-slot="' + i + '"]');
      if (!root) continue;
      root.classList.toggle('d-none', i >= visibleSlotCount);
    }
    var btn = document.getElementById('ref-add-slot-btn');
    if (btn) {
      btn.style.display = visibleSlotCount >= MAX_SLOTS ? 'none' : '';
      btn.disabled = visibleSlotCount >= MAX_SLOTS;
    }
  }

  function gather() {
    var slots = [];
    for (var i = 0; i < MAX_SLOTS; i++) {
      var root = document.querySelector('[data-ref-slot="' + i + '"]');
      if (!root) continue;
      var sections = [];
      var host = document.getElementById('ref-sections-' + i);
      if (host) {
        host.querySelectorAll('.ref-code-section').forEach(function (sec) {
          sections.push({
            type: sec.querySelector('.section-type-select').value,
            name: sec.querySelector('.section-name-input').value,
            code: sec.querySelector('.section-code').value,
          });
        });
      }
      slots.push({
        program_id: (root.querySelector('.js-ref-pid') || {}).value || '',
        transaction_code: (root.querySelector('.js-ref-tcode') || {}).value || '',
        title: (root.querySelector('.js-ref-title') || {}).value || '',
        sap_modules: Array.prototype.map.call(
          root.querySelectorAll('.ref-mod-' + i + ':checked'),
          function (c) {
            return c.value;
          }
        ),
        dev_types: Array.prototype.map.call(
          root.querySelectorAll('.ref-dt-' + i + ':checked'),
          function (c) {
            return c.value;
          }
        ),
        sections: sections,
      });
    }
    return { v: 1, slots: slots, savedAt: Date.now() };
  }

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      saveRaw(gather());
      if (typeof window.updateReview === 'function') window.updateReview();
    }, DEBOUNCE_MS);
  }

  function wireAddSection(slotIdx) {
    var addBtn = document.getElementById('ref-add-sec-' + slotIdx);
    if (!addBtn) return;
    addBtn.addEventListener('click', function () {
      var host = document.getElementById('ref-sections-' + slotIdx);
      if (!host) return;
      var n = host.querySelectorAll('.ref-code-section').length;
      host.appendChild(
        makeSectionEl(slotIdx, n, { type: 'Form Subroutines', name: '', code: '' })
      );
      scheduleSave();
    });
  }

  function init() {
    var host = document.getElementById('ref-code-slots-host');
    if (!host) return;

    var loaded = loadRaw();
    visibleSlotCount = 1;
    if (loaded) {
      var fromData = minSlotsFromPayload(loaded.slots);
      var saved =
        typeof loaded.visibleSlotCount === 'number' ? loaded.visibleSlotCount : 1;
      visibleSlotCount = Math.min(MAX_SLOTS, Math.max(1, saved, fromData));
    }

    for (var i = 0; i < MAX_SLOTS; i++) {
      var slotData = (loaded && loaded.slots && loaded.slots[i]) || {};
      var root = document.querySelector('[data-ref-slot="' + i + '"]');
      if (root) {
        var pid = root.querySelector('.js-ref-pid');
        var tc = root.querySelector('.js-ref-tcode');
        var tit = root.querySelector('.js-ref-title');
        if (pid) pid.value = slotData.program_id || '';
        if (tc) tc.value = slotData.transaction_code || '';
        if (tit) tit.value = slotData.title || '';
      }

      rebuildSections(
        i,
        slotData.sections && slotData.sections.length ? slotData.sections : defaultSections()
      );

      if (root) {
        root.querySelectorAll('.ref-mod-' + i).forEach(function (cb) {
          cb.checked = (slotData.sap_modules || []).indexOf(cb.value) >= 0;
        });
        root.querySelectorAll('.ref-dt-' + i).forEach(function (cb) {
          cb.checked = (slotData.dev_types || []).indexOf(cb.value) >= 0;
        });
      }

      setupSlotMaxSelect(
        i,
        'ref-mod-' + i,
        'ref-dt-' + i,
        'ref-mod-count-' + i,
        'ref-dt-count-' + i
      );
      wireAddSection(i);

      if (root && window.initSapPidTcodePair) {
        window.initSapPidTcodePair({
          programEl: root.querySelector('.js-ref-pid'),
          transactionEl: root.querySelector('.js-ref-tcode'),
          feedbackPid: root.querySelector('.js-ref-fb-pid'),
          feedbackTc: root.querySelector('.js-ref-fb-tcode'),
          maxPid: 40,
          maxTc: 20,
          mirrorTc: true,
          onChange: scheduleSave,
        });
        var titleEl = root.querySelector('.js-ref-title');
        if (titleEl) titleEl.addEventListener('input', scheduleSave);
      }
    }

    applySlotVisibility();

    var addSlotBtn = document.getElementById('ref-add-slot-btn');
    if (addSlotBtn) {
      addSlotBtn.addEventListener('click', function () {
        if (visibleSlotCount < MAX_SLOTS) {
          visibleSlotCount++;
          applySlotVisibility();
          scheduleSave();
        }
      });
    }
  }

  window.initRfpLocalRefCode = init;
  window.scheduleRfpRefCodeSave = scheduleSave;
  window.countRfpRefCodeSlotsFilled = function () {
    var n = 0;
    for (var i = 0; i < MAX_SLOTS; i++) {
      var root = document.querySelector('[data-ref-slot="' + i + '"]');
      if (!root) continue;
      var pid = ((root.querySelector('.js-ref-pid') || {}).value || '').trim();
      var tit = ((root.querySelector('.js-ref-title') || {}).value || '').trim();
      var hasCode = false;
      root.querySelectorAll('.section-code').forEach(function (ta) {
        if (ta.value.trim()) hasCode = true;
      });
      var mods = root.querySelectorAll('.ref-mod-' + i + ':checked').length;
      var dts = root.querySelectorAll('.ref-dt-' + i + ':checked').length;
      if (pid || tit || hasCode || mods || dts) n++;
    }
    return n;
  };
})();
