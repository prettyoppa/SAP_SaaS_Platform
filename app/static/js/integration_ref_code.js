/**
 * SAP 연동 개발 요청 – 참고 코드 (ABAP·VBA·Python 등, integration_requests.reference_code_payload)
 */
(function () {
  'use strict';

  var MAX_SLOTS = 3;
  var DEBOUNCE_MS = 450;
  var saveTimer = null;
  var visibleSlotCount = 1;

  var SECTION_TYPES_BY_KIND = {
    abap: [
      '메인 프로그램',
      'TOP Include',
      'Selection Screen',
      'Form Subroutines',
      'PBO Modules',
      'PAI Modules',
      'Class',
      '기타 Include',
    ],
    vba: ['모듈(.bas)', '클래스', 'UserForm', 'Sheet 모듈', 'ThisWorkbook', '기타'],
    python: ['메인 스크립트', '모듈', '설정/유틸', '기타'],
    sql: ['쿼리/스크립트', '저장 프로시저', '뷰', '기타'],
    other: ['코드', '설정·구성', '기타'],
  };

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

  function getKindFromRoot(root) {
    if (!root) return 'abap';
    var sel = root.querySelector('.js-ref-code-type');
    var v = (sel && sel.value) || 'abap';
    return SECTION_TYPES_BY_KIND[v] ? v : 'abap';
  }

  function defaultSections(kind) {
    var types = SECTION_TYPES_BY_KIND[kind] || SECTION_TYPES_BY_KIND.abap;
    return [{ type: types[0], name: '', code: '' }];
  }

  function toggleAbapMeta(slotIdx) {
    var root = document.querySelector('[data-ref-slot="' + slotIdx + '"]');
    if (!root) return;
    var kind = getKindFromRoot(root);
    var box = root.querySelector('.js-ref-abap-meta');
    if (box) box.classList.toggle('d-none', kind !== 'abap');
    var h = root.querySelector('.js-ref-sections-heading');
    if (h) {
      h.textContent = kind === 'abap' ? 'ABAP 소스 (섹션별)' : '코드 (섹션·블록별)';
    }
  }

  function makeSectionEl(slotIdx, idx, sec, kind) {
    sec = sec || { type: '', name: '', code: '' };
    var types = SECTION_TYPES_BY_KIND[kind] || SECTION_TYPES_BY_KIND.abap;
    if (!sec.type || types.indexOf(sec.type) < 0) sec.type = types[0];
    var div = document.createElement('div');
    div.className = 'ref-code-section border rounded p-2 mb-2';

    var bar = document.createElement('div');
    bar.className = 'd-flex align-items-center gap-2 flex-wrap mb-2';

    var sel = document.createElement('select');
    sel.className = 'form-select form-select-sm section-type-select';
    sel.style.maxWidth = '240px';
    types.forEach(function (t) {
      var o = document.createElement('option');
      o.value = t;
      o.textContent = t;
      if (t === sec.type) o.selected = true;
      sel.appendChild(o);
    });

    var nameInp = document.createElement('input');
    nameInp.type = 'text';
    nameInp.className = 'form-control form-control-sm section-name-input';
    nameInp.style.maxWidth = '220px';
    nameInp.placeholder = '이름·파일명 등 (선택)';
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
    ta.placeholder = '';
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
    var root = document.querySelector('[data-ref-slot="' + slotIdx + '"]');
    var kind = getKindFromRoot(root);
    host.innerHTML = '';
    var list = sections && sections.length ? sections : defaultSections(kind);
    list.forEach(function (s, i) {
      host.appendChild(makeSectionEl(slotIdx, i, s, kind));
    });
  }

  function refreshSlotCounts(slotIdx) {
    var root = document.querySelector('[data-ref-slot="' + slotIdx + '"]');
    if (!root || getKindFromRoot(root) !== 'abap') return;
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
        var root = document.querySelector('[data-ref-slot="' + slotIdx + '"]');
        if (!root || getKindFromRoot(root) !== 'abap') return;
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
      var kindEl = root.querySelector('.js-ref-code-type');
      var code_type = (kindEl && kindEl.value) || 'abap';
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
      var slot = {
        code_type: code_type,
        program_id: (root.querySelector('.js-ref-pid') || {}).value || '',
        transaction_code: (root.querySelector('.js-ref-tcode') || {}).value || '',
        title: (root.querySelector('.js-ref-title') || {}).value || '',
        sap_modules: [],
        dev_types: [],
        sections: sections,
      };
      if (code_type === 'abap') {
        slot.sap_modules = Array.prototype.map.call(
          root.querySelectorAll('.ref-mod-' + i + ':checked'),
          function (c) {
            return c.value;
          },
        );
        slot.dev_types = Array.prototype.map.call(
          root.querySelectorAll('.ref-dt-' + i + ':checked'),
          function (c) {
            return c.value;
          },
        );
      }
      slots.push(slot);
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
    var ct = root.querySelector('.js-ref-code-type');
    if (ct) ct.value = 'abap';
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
    toggleAbapMeta(slotIdx);
    rebuildSections(slotIdx, defaultSections('abap'));
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
    if ((s.code_type || 'abap') === 'abap') {
      if (s.sap_modules && s.sap_modules.length) return true;
      if (s.dev_types && s.dev_types.length) return true;
    }
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

  function wireCodeTypeChange(slotIdx) {
    var root = document.querySelector('[data-ref-slot="' + slotIdx + '"]');
    if (!root) return;
    var sel = root.querySelector('.js-ref-code-type');
    if (!sel) return;
    sel.addEventListener('change', function () {
      toggleAbapMeta(slotIdx);
      var k = getKindFromRoot(root);
      if (k !== 'abap') {
        root.querySelectorAll('.ref-mod-' + slotIdx).forEach(function (cb) {
          cb.checked = false;
        });
        root.querySelectorAll('.ref-dt-' + slotIdx).forEach(function (cb) {
          cb.checked = false;
        });
      }
      rebuildSections(slotIdx, defaultSections(k));
      refreshSlotCounts(slotIdx);
      scheduleSave();
    });
  }

  function wireAddSection(slotIdx) {
    var addBtn = document.getElementById('ref-add-sec-' + slotIdx);
    if (!addBtn) return;
    addBtn.addEventListener('click', function () {
      var root = document.querySelector('[data-ref-slot="' + slotIdx + '"]');
      var host = document.getElementById('ref-sections-' + slotIdx);
      if (!host || !root) return;
      var kind = getKindFromRoot(root);
      var types = SECTION_TYPES_BY_KIND[kind] || SECTION_TYPES_BY_KIND.abap;
      var n = host.querySelectorAll('.ref-code-section').length;
      host.appendChild(
        makeSectionEl(slotIdx, n, { type: types[Math.min(1, types.length - 1)] || types[0], name: '', code: '' }, kind),
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
        var ctSel = root.querySelector('.js-ref-code-type');
        var ct = (slotData.code_type || 'abap').toLowerCase();
        if (ctSel) ctSel.value = SECTION_TYPES_BY_KIND[ct] ? ct : 'abap';
        var pid = root.querySelector('.js-ref-pid');
        var tc = root.querySelector('.js-ref-tcode');
        var tit = root.querySelector('.js-ref-title');
        if (pid) pid.value = slotData.program_id || '';
        if (tc) tc.value = slotData.transaction_code || '';
        if (tit) tit.value = slotData.title || '';
      }

      toggleAbapMeta(i);
      rebuildSections(
        i,
        slotData.sections && slotData.sections.length ? slotData.sections : defaultSections(getKindFromRoot(root)),
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
        'ref-dt-count-' + i,
      );
      wireAddSection(i);
      wireCodeTypeChange(i);

      if (root && window.initSapPidTcodePair && getKindFromRoot(root) === 'abap') {
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
      } else if (root) {
        var titleEl2 = root.querySelector('.js-ref-title');
        if (titleEl2) titleEl2.addEventListener('input', scheduleSave);
        ['.js-ref-pid', '.js-ref-tcode'].forEach(function (sel) {
          var el = root.querySelector(sel);
          if (el) el.addEventListener('input', scheduleSave);
        });
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
        var msg =
          '입력한 참고 코드를 모두 삭제할까요? 이 요청 분석·제안에 더 이상 반영되지 않습니다.';
        var runWipe = function () {
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
        };
        if (typeof window.appConfirm === 'function') {
          window.appConfirm(msg).then(function (ok) {
            if (ok) runWipe();
          });
        } else if (window.confirm(msg)) {
          runWipe();
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

  function applyGalleryRefPayload(payload, collapseSelector) {
    if (!payload || !Array.isArray(payload.slots)) return Promise.resolve(false);
    var host = document.getElementById('ref-code-slots-host');
    if (!host) return Promise.resolve(false);
    var needConfirm =
      typeof window.countIntegrationRefCodeSlotsFilled === 'function' &&
      window.countIntegrationRefCodeSlotsFilled() > 0;
    var confirmMsg =
      '이미 입력된 참고 코드가 있습니다. 갤러리 항목으로 바꿀까요? (저장된 내용은 덮어씌워집니다)';
    var doApply = function () {
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
          var ctSel = root.querySelector('.js-ref-code-type');
          if (ctSel) ctSel.value = 'abap';
          var pid = root.querySelector('.js-ref-pid');
          var tc = root.querySelector('.js-ref-tcode');
          var tit = root.querySelector('.js-ref-title');
          if (pid) pid.value = slotData.program_id || '';
          if (tc) tc.value = slotData.transaction_code || '';
          if (tit) tit.value = slotData.title || '';
        }

        toggleAbapMeta(i);
        rebuildSections(
          i,
          slotData.sections && slotData.sections.length ? slotData.sections : defaultSections('abap'),
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
    };
    if (needConfirm) {
      if (typeof window.appConfirm === 'function') {
        return window.appConfirm(confirmMsg).then(function (ok) {
          return ok ? doApply() : false;
        });
      }
      if (!window.confirm(confirmMsg)) return Promise.resolve(false);
    }
    return Promise.resolve(doApply());
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
      var kind = getKindFromRoot(root);
      var mods = kind === 'abap' ? root.querySelectorAll('.ref-mod-' + i + ':checked').length : 0;
      var dts = kind === 'abap' ? root.querySelectorAll('.ref-dt-' + i + ':checked').length : 0;
      if (pid || tit || hasCode || mods || dts) n++;
    }
    return n;
  };
})();
