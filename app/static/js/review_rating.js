/* 문의/리뷰 별점: fetch + DOM 갱신(전체 페이지 리로드 없음) */

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
    if (!count || avg == null) {
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
    if (!count || avg == null) {
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

  function refreshAggregatesFromForm(form, avg, count) {
    const card = form.closest('.review-board-card');
    if (card) {
      const agg = card.querySelector('.review-board-aggregate');
      renderBoardAggregate(agg, avg, count);
      return;
    }
    const detailAgg = document.querySelector('.review-detail-aggregate');
    if (detailAgg) {
      renderDetailAggregate(detailAgg, avg, count);
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

      const fd = new FormData(form);
      container.setAttribute('aria-busy', 'true');
      container.querySelectorAll('button').forEach((b) => {
        b.disabled = true;
      });

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
            return;
          }
          const mine = data.stars;
          updateStarRow(container, mine);
          refreshAggregatesFromForm(form, data.avg, data.count);
        })
        .catch(() => {
          window.alert('별점을 저장하지 못했습니다. 네트워크 또는 로그인 상태를 확인해 주세요.');
        })
        .finally(() => {
          container.removeAttribute('aria-busy');
          container.querySelectorAll('button').forEach((b) => {
            b.disabled = false;
          });
        });
    },
    true,
  );
})();
