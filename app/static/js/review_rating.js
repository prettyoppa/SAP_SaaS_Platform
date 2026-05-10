/* 문의/리뷰 별점: fetch + DOM 갱신. 낙관적 UI로 클릭 직후 별·집계를 먼저 반영. */

(function () {
  'use strict';

  function filledFromAvg(avg) {
    if (avg == null || Number.isNaN(Number(avg))) return 0;
    return Math.max(0, Math.min(5, Math.round(Number(avg))));
  }

  function setStarButtonIcon(button, slot, mine) {
    const icon = button.querySelector('.review-star-icon');
    if (!icon) return;
    const filled = mine >= slot;
    icon.className = filled
      ? 'fa-solid fa-star review-star-icon review-star-icon--filled'
      : 'fa-solid fa-star review-star-icon review-star-icon--empty';
    icon.setAttribute('aria-hidden', 'true');
  }

  function updateStarRow(container, mine) {
    container.querySelectorAll('form[data-review-rate="1"]').forEach((form) => {
      const hidden = form.querySelector('input[name="stars"]');
      const btn = form.querySelector('button.review-star-submit');
      if (!hidden || !btn) return;
      const slot = parseInt(hidden.value, 10);
      if (Number.isNaN(slot)) return;
      setStarButtonIcon(btn, slot, mine);
    });
  }

  function renderBoardAggregate(el, avg, count) {
    if (!el) return;
    el.textContent = '';
    if (!count || avg == null || Number.isNaN(Number(avg))) {
      const sp = document.createElement('span');
      sp.className = 'text-muted';
      sp.textContent = '평점 없음';
      el.appendChild(sp);
      return;
    }
    const filled = filledFromAvg(avg);
    for (let i = 0; i < filled; i += 1) {
      const icon = document.createElement('i');
      icon.className = 'fa-solid fa-star text-warning';
      icon.style.fontSize = '.75rem';
      el.appendChild(icon);
    }
    for (let i = filled; i < 5; i += 1) {
      const icon = document.createElement('i');
      icon.className = 'fa-regular fa-star text-muted';
      icon.style.fontSize = '.75rem';
      el.appendChild(icon);
    }
    const span = document.createElement('span');
    span.className = 'ms-1';
    span.textContent = `(${count})`;
    el.appendChild(span);
  }

  function renderDetailAggregate(el, avg, count) {
    if (!el) return;
    if (!count || avg == null || Number.isNaN(Number(avg))) {
      el.innerHTML = '<span>아직 평가 없음</span>';
      return;
    }
    const filled = filledFromAvg(avg);
    let html = '';
    for (let i = 0; i < filled; i += 1) {
      html += '<i class="fa-solid fa-star text-warning"></i>';
    }
    for (let i = filled; i < 5; i += 1) {
      html += '<i class="fa-regular fa-star text-muted"></i>';
    }
    const av = Number(avg).toFixed(1);
    html += `<span class="ms-1">평균 · ${av} (${count}명)</span>`;
    el.innerHTML = html;
  }

  function findAggregateFromForm(form) {
    const card = form.closest('.review-board-card');
    if (card) return card.querySelector('.review-board-aggregate');
    return document.querySelector('.review-detail-aggregate');
  }

  function setAggregateDataset(aggEl, avg, count) {
    if (!aggEl) return;
    if (avg == null || Number.isNaN(Number(avg))) {
      aggEl.dataset.aggAvg = '';
    } else {
      aggEl.dataset.aggAvg = String(avg);
    }
    aggEl.dataset.aggCount = String(count);
  }

  function refreshAggregatesFromForm(form, avg, count) {
    const agg = findAggregateFromForm(form);
    if (!agg) return;
    setAggregateDataset(agg, avg, count);
    if (agg.classList.contains('review-board-aggregate')) {
      renderBoardAggregate(agg, avg, count);
    } else {
      renderDetailAggregate(agg, avg, count);
    }
  }

  /** 서버 집계와 동일한 가정: prevMine=0 이면 참가자 +1, 아니면 같은 인원에서 평균만 교체 */
  function nextAggregate(prevMine, newStars, avgStr, countStr) {
    const c = parseInt(countStr || '0', 10) || 0;
    const a = avgStr === '' || avgStr == null ? null : Number(avgStr);
    const p = prevMine | 0;
    const n = Math.max(1, Math.min(5, newStars | 0));
    if (p === 0) {
      const nc = c + 1;
      if (nc <= 0) return { avg: n, count: 1 };
      const na = c === 0 || a == null ? n : (a * c + n) / nc;
      return { avg: na, count: nc };
    }
    if (c <= 0) return { avg: n, count: 1 };
    const na = (a == null ? 0 : a * c) - p + n;
    return { avg: na / c, count: c };
  }

  function snapshotAggregate(aggEl) {
    if (!aggEl) return null;
    return { avg: aggEl.dataset.aggAvg || '', count: aggEl.dataset.aggCount || '0' };
  }

  function rollbackAggregate(aggEl, snap) {
    if (!aggEl || !snap) return;
    aggEl.dataset.aggAvg = snap.avg;
    aggEl.dataset.aggCount = snap.count;
    const c = parseInt(snap.count || '0', 10) || 0;
    const a = snap.avg === '' ? null : Number(snap.avg);
    if (aggEl.classList.contains('review-board-aggregate')) {
      renderBoardAggregate(aggEl, a, c);
    } else {
      renderDetailAggregate(aggEl, a, c);
    }
  }

  document.addEventListener(
    'submit',
    (e) => {
      const form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (form.getAttribute('data-review-rate') !== '1') return;
      e.preventDefault();

      const container = form.closest('.review-star-rate');
      if (!container) return;
      if (container.getAttribute('data-rating-in-flight') === '1') return;

      const hiddenStars = form.querySelector('input[name="stars"]');
      if (!hiddenStars) return;
      const newStars = parseInt(hiddenStars.value, 10);
      if (Number.isNaN(newStars)) return;

      const prevMine = parseInt(container.getAttribute('data-my-stars') || '0', 10) || 0;
      const aggEl = findAggregateFromForm(form);
      const aggSnap = snapshotAggregate(aggEl);

      const opt = nextAggregate(prevMine, newStars, aggEl ? aggEl.dataset.aggAvg || '' : '', aggEl ? aggEl.dataset.aggCount || '0' : '0');
      if (aggEl) {
        setAggregateDataset(aggEl, opt.avg, opt.count);
        if (aggEl.classList.contains('review-board-aggregate')) {
          renderBoardAggregate(aggEl, opt.avg, opt.count);
        } else {
          renderDetailAggregate(aggEl, opt.avg, opt.count);
        }
      }
      updateStarRow(container, newStars);
      container.setAttribute('data-my-stars', String(newStars));

      container.setAttribute('data-rating-in-flight', '1');

      const fd = new FormData(form);
      fetch(form.action, {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
      })
        .then(async (res) => {
          const ct = (res.headers.get('content-type') || '').toLowerCase();
          if (!ct.includes('application/json')) {
            throw new Error('not_json');
          }
          const data = await res.json();
          if (!res.ok || !data.ok) {
            const msg = (data && data.message) || '별점을 저장하지 못했습니다.';
            window.alert(msg);
            updateStarRow(container, prevMine);
            container.setAttribute('data-my-stars', String(prevMine));
            rollbackAggregate(aggEl, aggSnap);
            return;
          }
          const mine = data.stars;
          updateStarRow(container, mine);
          container.setAttribute('data-my-stars', String(mine));
          refreshAggregatesFromForm(form, data.avg, data.count);
        })
        .catch(() => {
          window.alert('별점을 저장하지 못했습니다. 네트워크 또는 로그인 상태를 확인해 주세요.');
          updateStarRow(container, prevMine);
          container.setAttribute('data-my-stars', String(prevMine));
          rollbackAggregate(aggEl, aggSnap);
        })
        .finally(() => {
          container.removeAttribute('data-rating-in-flight');
        });
    },
    true,
  );
})();
