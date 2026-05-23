(function () {
  function buildPayload() {
    var rows = document.querySelectorAll('.interview-suggestion-row');
    var like = [];
    var dislike = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var t = (row.getAttribute('data-suggestion') || '').trim();
      if (!t) continue;
      var v = row.dataset.vote || 'none';
      if (v === 'like') like.push(t);
      else if (v === 'dislike') dislike.push(t);
    }
    var ta = document.getElementById('s6-seq-answer-input');
    var free = ta ? (ta.value || '').trim() : '';
    return { v: 1, like: like, dislike: dislike, free: free };
  }
  function isPayloadValid(p) {
    if (!p) return false;
    var text = '';
    if (p.like && p.like.length) text += p.like.join(' ');
    if (p.dislike && p.dislike.length) text += p.dislike.join(' ');
    if (p.free) text += p.free;
    return text.replace(/\s/g, '').length >= 2;
  }
  function syncHiddenPayload() {
    var hid = document.getElementById('s6-answer-payload-json');
    if (hid) hid.value = JSON.stringify(buildPayload());
  }
  var suggData = document.getElementById('s6-answer-suggestions-data');
  var suggHost = document.getElementById('s6-answer-suggestion-rows');
  var seqIn = document.getElementById('s6-seq-answer-input');
  if (suggData && suggHost && seqIn) {
    try {
      var items = JSON.parse(suggData.textContent || '[]');
      if (Array.isArray(items)) {
        items.forEach(function (txt) {
          if (!txt || String(txt).trim().length < 1) return;
          var t = String(txt).trim();
          var row = document.createElement('div');
          row.className = 'interview-suggestion-row';
          row.setAttribute('data-suggestion', t);
          var span = document.createElement('span');
          span.className = 'sug-text';
          span.textContent = t;
          var vote = document.createElement('div');
          vote.className = 'sug-vote';
          var btnL = document.createElement('button');
          btnL.type = 'button';
          btnL.className = 'btn interview-svote-btn svote-like btn-outline-success';
          btnL.title = '이 답·방향 (복수 가능)';
          btnL.innerHTML = '<i class="fa-solid fa-thumbs-up" aria-hidden="true"></i>';
          var btnD = document.createElement('button');
          btnD.type = 'button';
          btnD.className = 'btn interview-svote-btn svote-dislike btn-outline-danger';
          btnD.title = '이 행은 맞지 않음';
          btnD.innerHTML = '<i class="fa-solid fa-thumbs-down" aria-hidden="true"></i>';
          function syncRowStyle() {
            row.classList.remove('is-like', 'is-dislike');
            if (row.dataset.vote === 'like') row.classList.add('is-like');
            if (row.dataset.vote === 'dislike') row.classList.add('is-dislike');
            btnL.classList.toggle('active', row.dataset.vote === 'like');
            btnD.classList.toggle('active', row.dataset.vote === 'dislike');
            syncHiddenPayload();
          }
          row.dataset.vote = 'none';
          syncRowStyle();
          btnL.addEventListener('click', function () {
            row.dataset.vote = row.dataset.vote === 'like' ? 'none' : 'like';
            syncRowStyle();
          });
          btnD.addEventListener('click', function () {
            row.dataset.vote = row.dataset.vote === 'dislike' ? 'none' : 'dislike';
            syncRowStyle();
          });
          vote.appendChild(btnL);
          vote.appendChild(btnD);
          row.appendChild(span);
          row.appendChild(vote);
          suggHost.appendChild(row);
        });
      }
    } catch (e) {}
  }
  if (seqIn) seqIn.addEventListener('input', syncHiddenPayload);
  syncHiddenPayload();
  var seqForm = document.getElementById('s6-iv-seq-form');
  var seqBtn = document.getElementById('s6-seq-next-btn');
  if (seqForm && seqBtn) {
    seqForm.addEventListener('submit', function (e) {
      syncHiddenPayload();
      if (!isPayloadValid(buildPayload())) {
        e.preventDefault();
        var lang = (typeof currentLang !== 'undefined' && currentLang === 'en') ? 'en' : 'ko';
        alert(lang === 'en'
          ? 'Select thumbs up/down or enter at least 2 characters in the notes field.'
          : '좋아요·싫어요로 선택하거나, 보충/추가 란에 2자 이상 입력해 주세요.');
        return;
      }
      seqBtn.disabled = true;
    });
  }
})();
