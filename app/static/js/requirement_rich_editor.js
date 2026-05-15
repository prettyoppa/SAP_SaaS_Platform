/**
 * 분석·개선 — 요구사항 리치 에디터(인라인 이미지 붙여넣기) / 텍스트 전용 전환
 */
(function () {
  'use strict';

  var root = document.getElementById('req-rich-root');
  if (!root) return;

  var MAX_IMG = 5;
  var MAX_BYTES = 2097152;
  var MAX_TOTAL = 8388608;

  var fmtInput = document.getElementById('requirement-text-format');
  var hiddenDesc = document.getElementById('description');
  var richEl = document.getElementById('description-rich');
  var plainEl = document.getElementById('description-plain');
  var toolbar = document.getElementById('req-rich-toolbar');
  var alertEl = document.getElementById('req-rich-alert');
  var counter = document.getElementById('char-count');
  var modeRich = document.getElementById('req-mode-rich');
  var modePlain = document.getElementById('req-mode-plain');
  var formEl = document.getElementById('abap-analysis-form');

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

  function isRichMode() {
    return fmtInput && fmtInput.value === 'html';
  }

  function countImages() {
    if (!richEl) return 0;
    return richEl.querySelectorAll('img').length;
  }

  function updateCharCount() {
    if (!counter) return;
    var n = 0;
    if (isRichMode() && richEl) {
      n = (richEl.innerText || '').replace(/\s+/g, ' ').trim().length;
    } else if (plainEl) {
      n = (plainEl.value || '').length;
    }
    counter.textContent = String(n);
  }

  function syncHidden() {
    if (!hiddenDesc) return;
    if (isRichMode() && richEl) {
      hiddenDesc.value = richEl.innerHTML;
    } else if (plainEl) {
      hiddenDesc.value = plainEl.value;
    }
  }

  function setMode(mode) {
    var rich = mode === 'html';
    if (fmtInput) fmtInput.value = rich ? 'html' : 'plain';
    if (richEl) richEl.classList.toggle('d-none', !rich);
    if (plainEl) plainEl.classList.toggle('d-none', rich);
    if (toolbar) toolbar.classList.toggle('d-none', !rich);
    if (modeRich) modeRich.checked = rich;
    if (modePlain) modePlain.checked = !rich;
    if (rich && plainEl && plainEl.value.trim() && !(richEl.innerText || '').trim()) {
      richEl.innerHTML = '<p>' + escapeHtml(plainEl.value).replace(/\n/g, '<br>') + '</p>';
    }
    if (!rich && richEl && (richEl.innerText || '').trim()) {
      plainEl.value = richEl.innerText.trim();
    }
    hideAlert();
    updateCharCount();
    syncHidden();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function compressToJpeg(blob, maxDim, quality) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(blob);
      var img = new Image();
      img.onload = function () {
        URL.revokeObjectURL(url);
        var w = img.naturalWidth;
        var h = img.naturalHeight;
        var scale = Math.min(1, maxDim / Math.max(w, h, 1));
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
        canvas.toBlob(function (out) {
          if (!out) reject(new Error('blob'));
          else resolve(out);
        }, 'image/jpeg', quality);
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error('load'));
      };
      img.src = url;
    });
  }

  function insertImageAtSelection(dataUrl) {
    richEl.focus();
    var img = document.createElement('img');
    img.src = dataUrl;
    img.alt = '캡처';
    img.className = 'req-inline-img';
    img.setAttribute('data-inline-id', 'tmp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8));

    var sel = window.getSelection();
    if (sel && sel.rangeCount) {
      var range = sel.getRangeAt(0);
      range.deleteContents();
      range.insertNode(img);
      range.setStartAfter(img);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    } else {
      richEl.appendChild(img);
    }
    var br = document.createElement('br');
    img.parentNode.insertBefore(br, img.nextSibling);
    updateCharCount();
    syncHidden();
  }

  function onPaste(e) {
    if (!isRichMode() || !richEl) return;
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
    hideAlert();
    if (countImages() >= MAX_IMG) {
      showAlert('이미지는 본문에 최대 ' + MAX_IMG + '장까지 넣을 수 있습니다.');
      return;
    }
    compressToJpeg(blob, 1920, 0.82).then(function (jpeg) {
      if (jpeg.size > MAX_BYTES) {
        showAlert('이미지 한 장은 약 ' + Math.round(MAX_BYTES / 1024 / 1024) + 'MB 이하여야 합니다.');
        return;
      }
      var reader = new FileReader();
      reader.onload = function () {
        if (typeof reader.result === 'string') insertImageAtSelection(reader.result);
      };
      reader.readAsDataURL(jpeg);
    }).catch(function () {
      showAlert('이미지를 붙여넣지 못했습니다.');
    });
  }

  if (modeRich) modeRich.addEventListener('change', function () { if (modeRich.checked) setMode('html'); });
  if (modePlain) modePlain.addEventListener('change', function () { if (modePlain.checked) setMode('plain'); });

  if (toolbar) {
    toolbar.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-cmd]');
      if (!btn || !isRichMode()) return;
      e.preventDefault();
      document.execCommand(btn.getAttribute('data-cmd'), false, null);
      richEl.focus();
      syncHidden();
    });
  }

  if (richEl) {
    richEl.addEventListener('paste', onPaste);
    richEl.addEventListener('input', function () {
      updateCharCount();
      syncHidden();
    });
    richEl.addEventListener('blur', syncHidden);
    if (!richEl.innerHTML.trim() && richEl.dataset.placeholder) {
      richEl.dataset.empty = '1';
    }
  }
  if (plainEl) {
    plainEl.addEventListener('input', function () {
      updateCharCount();
      syncHidden();
    });
  }

  if (formEl) {
    formEl.addEventListener('submit', function () {
      syncHidden();
    });
  }

  setMode(fmtInput ? fmtInput.value || 'html' : 'html');
})();
