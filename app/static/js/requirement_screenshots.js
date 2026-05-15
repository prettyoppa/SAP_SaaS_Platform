/**
 * 분석·개선 — 요구사항 캡처 붙여넣기 (Ctrl+V), 클라이언트 용량·개수 검증.
 */
(function () {
  'use strict';

  var root = document.getElementById('req-screenshots-root');
  if (!root) return;

  var maxCount = parseInt(root.getAttribute('data-max-count') || '5', 10);
  var maxBytes = parseInt(root.getAttribute('data-max-bytes') || '2097152', 10);
  var maxTotalBytes = parseInt(root.getAttribute('data-max-total-bytes') || '8388608', 10);
  var stateInput = document.getElementById('requirement-screenshots-state');
  var alertEl = document.getElementById('req-screenshots-alert');
  var listEl = document.getElementById('req-screenshots-list');
  var pasteZone = document.getElementById('req-screenshots-paste-zone');
  var descEl = document.getElementById('description');
  var formEl = document.getElementById('abap-analysis-form');

  /** @type {{id:string, kind:'existing'|'new', path?:string, previewUrl:string, name:string, size:number, dataUrl?:string}[]} */
  var items = [];

  var initialEl = document.getElementById('req-screenshots-initial');
  if (initialEl && initialEl.textContent) {
    try {
      var initial = JSON.parse(initialEl.textContent);
      if (Array.isArray(initial)) {
        initial.forEach(function (ent, i) {
          if (!ent || !ent.path) return;
          var url = ent.preview_url || ent.path;
          items.push({
            id: 'ex-' + i + '-' + (ent.path || '').slice(-12),
            kind: 'existing',
            path: ent.path,
            previewUrl: url,
            name: ent.filename || 'screenshot-' + (i + 1) + '.png',
            size: ent.size || 0,
          });
        });
      }
    } catch (e) { /* ignore */ }
  }

  function showAlert(msg) {
    if (!alertEl) return;
    alertEl.textContent = msg;
    alertEl.classList.remove('d-none');
  }

  function hideAlert() {
    if (!alertEl) return;
    alertEl.classList.add('d-none');
    alertEl.textContent = '';
  }

  function totalBytes() {
    return items.reduce(function (s, it) { return s + (it.size || 0); }, 0);
  }

  function syncHidden() {
    if (!stateInput) return;
    stateInput.value = JSON.stringify({
      keep_paths: items.filter(function (it) { return it.kind === 'existing'; }).map(function (it) { return it.path; }),
      new: items.filter(function (it) { return it.kind === 'new'; }).map(function (it) {
        return { data: it.dataUrl, name: it.name, size: it.size };
      }),
    });
  }

  function render() {
    if (!listEl) return;
    listEl.innerHTML = '';
    items.forEach(function (it, idx) {
      var li = document.createElement('li');
      li.className = 'req-screenshots-item';
      var img = document.createElement('img');
      img.src = it.previewUrl;
      img.alt = it.name;
      var meta = document.createElement('div');
      meta.className = 'req-screenshots-item-meta small text-muted';
      meta.textContent = it.name;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm btn-outline-danger req-screenshots-remove';
      btn.setAttribute('aria-label', '캡처 삭제');
      btn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
      btn.addEventListener('click', function () {
        items.splice(idx, 1);
        hideAlert();
        render();
        syncHidden();
      });
      li.appendChild(img);
      li.appendChild(meta);
      li.appendChild(btn);
      listEl.appendChild(li);
    });
    syncHidden();
  }

  function compressToJpeg(blob, maxDim, quality) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(blob);
      var img = new Image();
      img.onload = function () {
        URL.revokeObjectURL(url);
        var w = img.naturalWidth;
        var h = img.naturalHeight;
        var scale = 1;
        if (w > maxDim || h > maxDim) {
          scale = Math.min(maxDim / w, maxDim / h);
        }
        var cw = Math.max(1, Math.round(w * scale));
        var ch = Math.max(1, Math.round(h * scale));
        var canvas = document.createElement('canvas');
        canvas.width = cw;
        canvas.height = ch;
        var ctx = canvas.getContext('2d');
        if (!ctx) {
          reject(new Error('canvas'));
          return;
        }
        ctx.drawImage(img, 0, 0, cw, ch);
        canvas.toBlob(
          function (out) {
            if (!out) {
              reject(new Error('blob'));
              return;
            }
            resolve(out);
          },
          'image/jpeg',
          quality
        );
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error('load'));
      };
      img.src = url;
    });
  }

  function addFromBlob(blob, suggestedName) {
    hideAlert();
    if (items.length >= maxCount) {
      showAlert('캡처는 최대 ' + maxCount + '장까지 붙여넣을 수 있습니다.');
      return;
    }
    compressToJpeg(blob, 1920, 0.82).then(function (jpeg) {
      if (jpeg.size > maxBytes) {
        showAlert('이미지 한 장은 약 ' + Math.round(maxBytes / 1024 / 1024) + 'MB 이하여야 합니다. 더 작은 영역만 캡처해 보세요.');
        return;
      }
      if (totalBytes() + jpeg.size > maxTotalBytes) {
        showAlert('캡처 용량 합계가 너무 큽니다. 일부를 삭제하거나 해상도를 줄여 주세요.');
        return;
      }
      var reader = new FileReader();
      reader.onload = function () {
        var dataUrl = reader.result;
        if (typeof dataUrl !== 'string') return;
        var name = (suggestedName || 'screenshot').replace(/\.[^.]+$/, '') + '.jpg';
        items.push({
          id: 'new-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8),
          kind: 'new',
          previewUrl: dataUrl,
          dataUrl: dataUrl,
          name: name,
          size: jpeg.size,
        });
        render();
      };
      reader.readAsDataURL(jpeg);
    }).catch(function () {
      showAlert('이미지를 처리하지 못했습니다. PNG/JPEG 캡처인지 확인해 주세요.');
    });
  }

  function onPaste(e) {
    var cd = e.clipboardData;
    if (!cd || !cd.items) return;
    var imgItem = null;
    for (var i = 0; i < cd.items.length; i++) {
      if (cd.items[i].type && cd.items[i].type.indexOf('image/') === 0) {
        imgItem = cd.items[i];
        break;
      }
    }
    if (!imgItem) return;
    var blob = imgItem.getAsFile();
    if (!blob) return;
    e.preventDefault();
    addFromBlob(blob, blob.name || 'screenshot.png');
  }

  if (pasteZone) {
    pasteZone.addEventListener('paste', onPaste);
    pasteZone.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') pasteZone.focus();
    });
  }
  if (descEl) descEl.addEventListener('paste', onPaste);

  if (formEl) {
    formEl.addEventListener('submit', function () {
      syncHidden();
    });
  }

  render();
})();
