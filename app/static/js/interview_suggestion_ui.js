/**
 * 인터뷰 선지 — exclusive(택1) / multi(복수) 그룹 UI
 */
(function (global) {
  'use strict';

  function t(key, fallback) {
    if (global.t && typeof global.t === 'function') {
      var v = global.t(key);
      if (v) return v;
    }
    return fallback;
  }

  function parseJsonEl(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent || 'null');
    } catch (e) {
      return null;
    }
  }

  function buildPayloadFromRows(rows) {
    var like = [];
    var dislike = [];
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var txt = (row.getAttribute('data-suggestion') || '').trim();
      if (!txt) continue;
      var v = row.dataset.vote || 'none';
      if (v === 'like') like.push(txt);
      else if (v === 'dislike') dislike.push(txt);
    }
    return { v: 1, like: like, dislike: dislike, free: '' };
  }

  function validatePayload(p, groups, freeText) {
    if (!p) return 'empty';
    p.free = (freeText || '').trim();
    var hasContent = (p.like && p.like.length) || (p.dislike && p.dislike.length)
      || p.free.replace(/\s/g, '').length >= 2;
    if (!hasContent) return 'empty';

    if (!groups || !groups.length) return null;

    for (var g = 0; g < groups.length; g++) {
      var grp = groups[g];
      if ((grp.mode || '').toLowerCase() !== 'exclusive') continue;
      var opts = grp.options || [];
      var picked = [];
      for (var j = 0; j < p.like.length; j++) {
        if (opts.indexOf(p.like[j]) >= 0) picked.push(p.like[j]);
      }
      if (picked.length > 1) return 'exclusive_multi';
      if (picked.length === 0 && p.free.length < 2 && opts.length >= 2) return 'exclusive_none';
    }
    return null;
  }

  function alertForCode(code) {
    if (code === 'exclusive_none') {
      return t('interview.suggest.exclusiveNone', '택1 선택지에서 하나를 고르거나, 보충란에 답을 입력해 주세요.');
    }
    if (code === 'exclusive_multi') {
      return t('interview.suggest.exclusiveMulti', '택1 선택지에서는 하나만 고를 수 있습니다.');
    }
    return t('interview.suggest.needAnswer', '좋아요·싫어요로 선택하거나, 보충/추가 란에 2자 이상 입력해 주세요.');
  }

  function mount(cfg) {
    var host = document.getElementById(cfg.hostId);
    if (!host) return;

    var groupsEnabled = !!cfg.groupsEnabled;
    var groups = Array.isArray(cfg.groups) ? cfg.groups : [];
    var flat = Array.isArray(cfg.flatItems) ? cfg.flatItems : [];
    var draft = cfg.draft || { v: 1, like: [], dislike: [], free: '' };

    var likeSet = {};
    (draft.like || []).forEach(function (x) {
      if (x) likeSet[String(x).trim()] = true;
    });
    var dislikeSet = {};
    (draft.dislike || []).forEach(function (x) {
      if (x) dislikeSet[String(x).trim()] = true;
    });

    host.innerHTML = '';

    function addRow(txt, groupMeta) {
      if (!txt || String(txt).trim().length < 1) return;
      var tstr = String(txt).trim();
      var row = document.createElement('div');
      row.className = 'interview-suggestion-row';
      row.setAttribute('data-suggestion', tstr);
      if (groupMeta) {
        row.dataset.groupId = groupMeta.id || '';
        row.dataset.groupMode = groupMeta.mode || 'multi';
      }
      if (likeSet[tstr]) row.classList.add('is-like');
      else if (dislikeSet[tstr]) row.classList.add('is-dislike');

      var span = document.createElement('span');
      span.className = 'sug-text';
      span.textContent = tstr;

      var vote = document.createElement('div');
      vote.className = 'sug-vote';

      var isExclusive = groupMeta && groupMeta.mode === 'exclusive';
      var btnL = document.createElement('button');
      btnL.type = 'button';
      btnL.className = 'btn interview-svote-btn svote-like btn-outline-success';
      btnL.title = isExclusive
        ? t('interview.suggest.likeExclusive', '이 답 선택 (하나만)')
        : t('interview.suggest.likeMulti', '이 답·방향 (복수 가능)');
      btnL.innerHTML = '<i class="fa-solid fa-thumbs-up" aria-hidden="true"></i>';

      var btnD = document.createElement('button');
      btnD.type = 'button';
      btnD.className = 'btn interview-svote-btn svote-dislike btn-outline-danger';
      btnD.title = t('interview.suggest.dislike', '이 행은 맞지 않음');
      btnD.innerHTML = '<i class="fa-solid fa-thumbs-down" aria-hidden="true"></i>';

      function syncRowStyle() {
        row.classList.remove('is-like', 'is-dislike');
        if (row.dataset.vote === 'like') row.classList.add('is-like');
        if (row.dataset.vote === 'dislike') row.classList.add('is-dislike');
        btnL.classList.toggle('active', row.dataset.vote === 'like');
        btnD.classList.toggle('active', row.dataset.vote === 'dislike');
        btnL.setAttribute('aria-pressed', row.dataset.vote === 'like' ? 'true' : 'false');
        btnD.setAttribute('aria-pressed', row.dataset.vote === 'dislike' ? 'true' : 'false');
        if (cfg.onSync) cfg.onSync();
      }

      row.dataset.vote = 'none';
      if (row.classList.contains('is-like')) row.dataset.vote = 'like';
      if (row.classList.contains('is-dislike')) row.dataset.vote = 'dislike';

      btnL.addEventListener('click', function () {
        if (row.dataset.vote === 'like') {
          row.dataset.vote = 'none';
        } else {
          if (isExclusive && groupMeta.id) {
            host.querySelectorAll('.interview-suggestion-row[data-group-id="' + groupMeta.id + '"]').forEach(function (other) {
              if (other !== row) other.dataset.vote = 'none';
            });
          }
          row.dataset.vote = 'like';
        }
        host.querySelectorAll('.interview-suggestion-row').forEach(function (r) {
          if (r.dataset.vote === 'like' || r.dataset.vote === 'dislike') {
            r.classList.remove('is-like', 'is-dislike');
            if (r.dataset.vote === 'like') r.classList.add('is-like');
            if (r.dataset.vote === 'dislike') r.classList.add('is-dislike');
            var bl = r.querySelector('.svote-like');
            var bd = r.querySelector('.svote-dislike');
            if (bl) bl.classList.toggle('active', r.dataset.vote === 'like');
            if (bd) bd.classList.toggle('active', r.dataset.vote === 'dislike');
          } else {
            r.classList.remove('is-like', 'is-dislike');
            var bl2 = r.querySelector('.svote-like');
            var bd2 = r.querySelector('.svote-dislike');
            if (bl2) bl2.classList.remove('active');
            if (bd2) bd2.classList.remove('active');
          }
        });
        syncRowStyle();
      });

      btnD.addEventListener('click', function () {
        if (row.dataset.vote === 'dislike') row.dataset.vote = 'none';
        else row.dataset.vote = 'dislike';
        syncRowStyle();
      });

      vote.appendChild(btnL);
      vote.appendChild(btnD);
      row.appendChild(span);
      row.appendChild(vote);
      host.appendChild(row);
    }

    var useGroups = groupsEnabled && groups.length > 0;
    if (useGroups) {
      groups.forEach(function (g) {
        var hint = document.createElement('div');
        hint.className = 'interview-suggestion-group-hint small text-muted mb-1 mt-2';
        hint.textContent = g.prompt || (g.mode === 'exclusive'
          ? t('interview.suggest.exclusiveHint', '아래 중 하나를 선택하세요')
          : t('interview.suggest.multiHint', '해당하는 항목을 선택하세요 (복수 가능)'));
        host.appendChild(hint);
        (g.options || []).forEach(function (opt) {
          addRow(opt, { id: g.id, mode: g.mode });
        });
      });
    } else {
      flat.forEach(function (txt) {
        addRow(txt, null);
      });
    }

    if (cfg.onSync) cfg.onSync();
  }

  global.InterviewSuggestionUI = {
    mount: mount,
    buildPayloadFromRows: buildPayloadFromRows,
    validatePayload: validatePayload,
    alertForCode: alertForCode,
    parseJsonEl: parseJsonEl,
  };
})(typeof window !== 'undefined' ? window : this);
