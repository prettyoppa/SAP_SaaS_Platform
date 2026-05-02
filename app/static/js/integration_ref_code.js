/**
 * SAP 연동 개발 요청 – 참고 코드 정보 (본 integration_requests 행에 저장)
 */
(function () {
  'use strict';

  var MAX_SLOTS = 3;
  var DEBOUNCE_MS = 450;
  var saveTimer = null;
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

  function requestId() {
    var c = window.__INTEGRATION_CTX__ || {};
    return c.requestId || null;
  }

  function loadInitial() {
    var el = document.getElementById('int-refcode-initial');
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function defaultSections() {
    return [{ type: '메인 프로그램', name: '', code: '' }];
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

  function refreshSlotCounts(slotIdx) {
    var max = 3;
    var modCls = 'ref-mod-' + slotIdx;
    var dtCls = 'ref-dt-' + slotIdx;
    function upd(cls, countId) {
      var inputs = document.querySelectorAll('.' + cls);
      var countEl = document.getElementById(countId);
      var checked = document.querySelectorAll('.' + cls + ':checked').length;
      if (countEl) countEl.textContent = checked + ' / ' + max;
      inputs.forEach(function (inp) {
        if (!inp.checked) inp.disabled = checked >= max;
      });
    }
    upd(modCls, 'ref-mod-count-' + slotIdx);
    upd(dtCls, 'ref-dt-count-' + slotIdx);
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
    return {
      v: 1,
      slots: slots,
      visibleSlotCount: visibleSlotCount,
      savedAt: Date.now(),
    };
  }

  function syncHiddenInput() {
    var el = document.getElementById('reference-code-json-field');
    if (!el) return;
    el.value = JSON.stringify(gather());
  }

  function pushServer() {
    var id = requestId();
    if (!id) {
      syncHiddenInput();
      return;
    }
    var payload = gather();
    fetch('/integration/' + id + '/reference-codes', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }).catch(function () {});
  }

  function scheduleSave() {
    syncHiddenInput();
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      pushServer();
      if (typeof window.updateIntegrationReview === 'function') window.updateIntegrationReview();
    }, DEBOUNCE_MS);
  }

  function clearSlot(slotIdx) {
    var root = document.querySelector('[data-ref-slot="' + slotIdx + '"]');
    if (!root) return;
    var pid = root.querySelector('.js-ref-pid');
    var tc = root.querySelector('.js-ref-tcode');
    var tit = root.querySelector('.js-ref-title');
    if (pid) pid.value = '';
    if (tc) tc.value = '';
    if (tit) tit.value = '';
    root.querySelectorAll('.ref-mod-' + slotIdx).forEach(function (cb) {
      cb.checked = false;
    });
    root.querySelectorAll('.ref-dt-' + slotIdx).forEach(function (cb) {
      cb.checked = false;
    });
    rebuildSections(slotIdx, defaultSections());
    var fb1 = root.querySelector('.js-ref-fb-pid');
    var fb2 = root.querySelector('.js-ref-fb-tcode');
    if (fb1) fb1.textContent = '';
    if (fb2) fb2.textContent = '';
    refreshSlotCounts(slotIdx);
  }

  function applySlotVisibility() {
    for (var i = 0; i < MAX_SLOTS; i++) {
      var root = document.querySelector('[data-ref-slot="' + i + '"]');
      if (!root) continue;
      root.classList.toggle('d-none', i >= visibleSlotCount);
      var btn = root.querySelector('.js-ref-remove-last');
      if (btn) {
        var show = visibleSlotCount > 1 && i === visibleSlotCount - 1;
        btn.classList.toggle('d-none', !show);
      }
    }
    var addBtn = document.getElementById('ref-add-slot-btn');
    if (addBtn) {
      addBtn.style.display = visibleSlotCount >= MAX_SLOTS ? 'none' : '';
      addBtn.disabled = visibleSlotCount >= MAX_SLOTS;
    }
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

  function removeLastRefSlot(slotIdx) {
    if (visibleSlotCount <= 1) return;
    if (slotIdx !== visibleSlotCount - 1) return;
    clearSlot(slotIdx);
    visibleSlotCount--;
    applySlotVisibility();
    scheduleSave();
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

    var loaded = loadInitial();
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

    document.querySelectorAll('.js-ref-remove-last').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var idx = parseInt(btn.getAttribute('data-slot'), 10);
        removeLastRefSlot(idx);
      });
    });

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

    var delAll = document.getElementById('ref-delete-all-btn');
    if (delAll) {
      delAll.addEventListener('click', function () {
        if (!confirm('입력한 ABAP 코드를 모두 삭제할까요? 이 요청 분석·제안서에 더 이상 반영되지 않습니다.')) return;
        var id = requestId();
        function wipeLocal() {
          visibleSlotCount = 1;
          for (var j = 0; j < MAX_SLOTS; j++) {
            clearSlot(j);
          }
          applySlotVisibility();
          for (var k = 0; k < MAX_SLOTS; k++) refreshSlotCounts(k);
          syncHiddenInput();
          if (typeof window.updateIntegrationReview === 'function') window.updateIntegrationReview();
        }
        if (id) {
          fetch('/integration/' + id + '/reference-codes', {
            method: 'DELETE',
            credentials: 'same-origin',
          })
            .then(function () {
              wipeLocal();
            })
            .catch(function () {
              wipeLocal();
            });
        } else {
          wipeLocal();
        }
      });
    }

    var form = document.getElementById('integration-form');
    if (form) {
      form.addEventListener('submit', function () {
        syncHiddenInput();
      });
    }

    syncHiddenInput();
    if (typeof window.updateIntegrationReview === 'function') window.updateIntegrationReview();
  }

  function expandRefCollapseMaybe(collapseSelector) {
    if (!collapseSelector) return;
    var el = document.querySelector(collapseSelector);
    if (!el || typeof window.bootstrap === 'undefined') return;
    try {
      window.bootstrap.Collapse.getOrCreateInstance(el, { toggle: false }).show();
    } catch (e) {}
  }

  /** 관리자: 코드 갤러리 API에서 받은 payload로 참고 코드 영역을 덮어씁니다. */
  function applyGalleryRefPayload(payload, collapseSelector) {
    if (!payload || !Array.isArray(payload.slots)) return false;
    var host = document.getElementById('ref-code-slots-host');
    if (!host) return false;
    if (
      typeof window.countIntegrationRefCodeSlotsFilled === 'function' &&
      window.countIntegrationRefCodeSlotsFilled() > 0
    ) {
      if (
        !confirm(
          '이미 입력된 참고 코드가 있습니다. 갤러리 항목으로 바꿀까요? (저장된 내용은 덮어씌워집니다)'
        )
      ) {
        return false;
      }
    }
    expandRefCollapseMaybe(collapseSelector);
    visibleSlotCount = 1;
    var fromData = minSlotsFromPayload(payload.slots);
    var saved =
      typeof payload.visibleSlotCount === 'number' ? payload.visibleSlotCount : 1;
    visibleSlotCount = Math.min(MAX_SLOTS, Math.max(1, saved, fromData));

    for (var i = 0; i < MAX_SLOTS; i++) {
      var slotData = payload.slots[i] || {};
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
    }

    applySlotVisibility();
    for (var k = 0; k < MAX_SLOTS; k++) refreshSlotCounts(k);
    syncHiddenInput();
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = null;
    pushServer();
    if (typeof window.updateIntegrationReview === 'function') window.updateIntegrationReview();
    return true;
  }

  window.initIntegrationRefCode = init;
  window.scheduleIntegrationRefCodeSave = scheduleSave;
  window.applyIntegrationGalleryRefPayload = applyGalleryRefPayload;
  window.countIntegrationRefCodeSlotsFilled = function () {
    var n = 0;
    for (var i = 0; i < visibleSlotCount; i++) {
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
