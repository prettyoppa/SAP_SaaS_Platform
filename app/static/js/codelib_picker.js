/**
 * 관리자: 코드 갤러리에서 참고 코드 단건 가져오기 (모달 피커).
 * data-codelib-import="rfp" | "integration"
 * data-ref-collapse="#collapse-ref-code" 등 접기 영역을 가져온 뒤 펼침.
 */
(function () {
  'use strict';

  var DEBOUNCE_MS = 320;
  var searchTimer = null;
  var modalEl = null;
  var listHost = null;
  var searchInput = null;
  var errBox = null;
  var pendingScope = null;
  var pendingCollapse = null;

  function ensureModal() {
    if (document.getElementById('codelibPickerModal')) {
      modalEl = document.getElementById('codelibPickerModal');
      listHost = document.getElementById('codelib-picker-list');
      searchInput = document.getElementById('codelib-picker-search');
      errBox = document.getElementById('codelib-picker-err');
      return;
    }
    document.body.insertAdjacentHTML(
      'beforeend',
      '<div class="modal fade" id="codelibPickerModal" tabindex="-1" aria-labelledby="codelibPickerModalLabel" aria-hidden="true">' +
        '<div class="modal-dialog modal-lg modal-dialog-scrollable">' +
        '<div class="modal-content">' +
        '<div class="modal-header">' +
        '<h5 class="modal-title" id="codelibPickerModalLabel">코드 갤러리에서 가져오기</h5>' +
        '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="닫기"></button>' +
        '</div>' +
        '<div class="modal-body">' +
        '<p class="text-muted small mb-2">항목을 선택하면 현재 폼의 참고 코드가 해당 갤러리 항목으로 바뀝니다.</p>' +
        '<div class="mb-3">' +
        '<input type="search" class="form-control" id="codelib-picker-search" placeholder="제목·프로그램 ID·트랜잭션 검색" autocomplete="off"/>' +
        '</div>' +
        '<div id="codelib-picker-err" class="alert alert-danger py-2 small d-none" role="alert"></div>' +
        '<div id="codelib-picker-list" class="list-group"></div>' +
        '</div>' +
        '</div></div></div>'
    );
    modalEl = document.getElementById('codelibPickerModal');
    listHost = document.getElementById('codelib-picker-list');
    searchInput = document.getElementById('codelib-picker-search');
    errBox = document.getElementById('codelib-picker-err');
    searchInput.addEventListener('input', function () {
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        loadList(searchInput.value);
      }, DEBOUNCE_MS);
    });
  }

  function showErr(msg) {
    if (!errBox) return;
    errBox.textContent = msg || '';
    errBox.classList.toggle('d-none', !msg);
  }

  function loadList(q) {
    showErr('');
    if (!listHost) return;
    listHost.innerHTML =
      '<div class="list-group-item text-muted small">불러오는 중…</div>';
    var url = '/admin/api/codelib-items' + (q && q.trim() ? '?q=' + encodeURIComponent(q.trim()) : '');
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 403) throw new Error('관리자만 사용할 수 있습니다.');
        if (!r.ok) throw new Error('목록을 불러오지 못했습니다.');
        return r.json();
      })
      .then(function (data) {
        var items = (data && data.items) || [];
        listHost.innerHTML = '';
        if (!items.length) {
          listHost.innerHTML =
            '<div class="list-group-item text-muted small">표시할 항목이 없습니다.</div>';
          return;
        }
        items.forEach(function (it) {
          var a = document.createElement('button');
          a.type = 'button';
          a.className = 'list-group-item list-group-item-action text-start';
          var draft = it.is_draft ? ' <span class="badge bg-warning text-dark">임시</span>' : '';
          a.innerHTML =
            '<div class="fw-semibold">' +
            (it.title || '(제목 없음)') +
            draft +
            '</div>' +
            '<div class="small text-muted">' +
            (it.program_id || '—') +
            ' · ' +
            (it.transaction_code || '—') +
            ' · ID ' +
            it.id +
            '</div>';
          a.addEventListener('click', function () {
            pickItem(it.id);
          });
          listHost.appendChild(a);
        });
      })
      .catch(function (e) {
        listHost.innerHTML = '';
        showErr(e.message || '오류가 발생했습니다.');
      });
  }

  function pickItem(id) {
    showErr('');
    fetch('/admin/api/codelib-items/' + id + '/reference-payload', { credentials: 'same-origin' })
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, status: r.status, body: body };
        });
      })
      .then(function (res) {
        if (res.status === 403) throw new Error('관리자만 사용할 수 있습니다.');
        if (res.status === 404) throw new Error('항목을 찾을 수 없습니다.');
        if (res.status === 400 && res.body && res.body.error === 'reference_code_too_large') {
          throw new Error('갤러리 코드가 참고 코드 허용 용량을 초과합니다. 갤러리에서 줄인 뒤 다시 시도해 주세요.');
        }
        if (!res.ok || !res.body || !res.body.payload) {
          throw new Error('가져오기에 실패했습니다.');
        }
        var payload = res.body.payload;
        var scope = pendingScope;
        var collapse = pendingCollapse;
        var ok;
        if (scope === 'integration') {
          if (typeof window.applyIntegrationGalleryRefPayload !== 'function') {
            throw new Error('참고 코드 스크립트가 로드되지 않았습니다. 페이지를 새로고침해 주세요.');
          }
          ok = window.applyIntegrationGalleryRefPayload(payload, collapse);
        } else if (scope === 'rfp' || scope === 'abap') {
          if (typeof window.applyRfpGalleryRefPayload !== 'function') {
            throw new Error('참고 코드 스크립트가 로드되지 않았습니다. 페이지를 새로고침해 주세요.');
          }
          ok = window.applyRfpGalleryRefPayload(payload, collapse);
        } else {
          throw new Error('알 수 없는 가져오기 범위입니다.');
        }
        if (ok === false) return;
        if (!ok) throw new Error('폼에 적용하지 못했습니다.');
        if (window.bootstrap && modalEl) {
          var inst = window.bootstrap.Modal.getInstance(modalEl);
          if (inst) inst.hide();
        }
      })
      .catch(function (e) {
        showErr(e.message || '오류가 발생했습니다.');
      });
  }

  function openPicker(scope, collapseSelector) {
    ensureModal();
    pendingScope = scope;
    pendingCollapse = collapseSelector || null;
    if (searchInput) searchInput.value = '';
    showErr('');
    loadList('');
    if (window.bootstrap && modalEl) {
      window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  function wire() {
    document.querySelectorAll('[data-codelib-import]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var scope = (btn.getAttribute('data-codelib-import') || 'rfp').trim();
        var collapse = btn.getAttribute('data-ref-collapse') || '';
        openPicker(scope, collapse);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
