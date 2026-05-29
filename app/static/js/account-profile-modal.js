/**
 * 회원 정보 — 현재 페이지 Bootstrap 모달로 표시 (/account/panel).
 */
(function () {
  var modalEl = document.getElementById("accountProfileModal");
  var bodyEl = document.getElementById("accountProfileModalBody");
  if (!modalEl || !bodyEl || typeof bootstrap === "undefined") return;

  var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  var loadingHtml =
    '<div class="text-center py-4 text-muted">' +
    '<div class="spinner-border spinner-border-sm text-primary" role="status" aria-hidden="true"></div>' +
    '<div class="small mt-2"><span class="nav-ko">불러오는 중…</span>' +
    '<span class="nav-en" style="display:none">Loading…</span></div></div>';
  var cachedHtml = "";
  var inflight = null;

  function applyLangInModal() {
    var lang = document.documentElement.getAttribute("data-lang") || "en";
    var isKo = lang === "ko";
    bodyEl.querySelectorAll(".nav-ko").forEach(function (el) {
      el.style.display = isKo ? "" : "none";
    });
    bodyEl.querySelectorAll(".nav-en").forEach(function (el) {
      el.style.display = isKo ? "none" : "";
    });
  }

  function loadPanel(force) {
    if (!force && cachedHtml) {
      bodyEl.innerHTML = cachedHtml;
      applyLangInModal();
      return Promise.resolve();
    }
    if (inflight) return inflight;
    bodyEl.innerHTML = loadingHtml;
    applyLangInModal();
    inflight = fetch("/account/panel", {
      credentials: "same-origin",
      headers: { Accept: "text/html" },
    })
      .then(function (r) {
        if (!r.ok) throw new Error("load_failed");
        return r.text();
      })
      .then(function (html) {
        cachedHtml = html;
        bodyEl.innerHTML = html;
        applyLangInModal();
      })
      .catch(function () {
        bodyEl.innerHTML =
          '<div class="alert alert-warning small mb-0">' +
          '<span class="nav-ko">회원 정보를 불러오지 못했습니다. 잠시 후 다시 시도하거나 ' +
          '<a href="/account">전체 페이지</a>에서 확인해 주세요.</span>' +
          '<span class="nav-en" style="display:none">Could not load profile. Try again or open the ' +
          '<a href="/account">full profile page</a>.</span></div>';
        applyLangInModal();
      })
      .finally(function () {
        inflight = null;
      });
    return inflight;
  }

  function openModal(forceReload) {
    loadPanel(!!forceReload).then(function () {
      modal.show();
    });
  }

  document.addEventListener("click", function (e) {
    var trigger = e.target.closest("[data-account-profile-modal]");
    if (!trigger) return;
    e.preventDefault();
    openModal(false);
  });

  document.addEventListener("app:langchange", function () {
    if (modalEl.classList.contains("show")) applyLangInModal();
  });

  modalEl.addEventListener("hidden.bs.modal", function () {
    /* 다음 열 때 최신 정보(선택): 저장 후 돌아올 때를 위해 캐시 유지, 쿼리 있으면 갱신 */
    var q = window.location.search || "";
    if (
      q.indexOf("profile_saved=1") >= 0 ||
      q.indexOf("password_saved=1") >= 0 ||
      q.indexOf("email_changed=1") >= 0 ||
      q.indexOf("phone_saved=1") >= 0
    ) {
      cachedHtml = "";
    }
  });

  /* /account?… 저장 알림 후 전체 페이지 대신 모달로 열기 */
  if (window.location.pathname === "/account") {
    var params = new URLSearchParams(window.location.search);
    if (
      params.get("profile_saved") === "1" ||
      params.get("password_saved") === "1" ||
      params.get("email_changed") === "1" ||
      params.get("phone_saved") === "1"
    ) {
      var back = "/";
      try {
        if (document.referrer) {
          var ref = new URL(document.referrer);
          if (ref.origin === window.location.origin && ref.pathname !== "/account") {
            back = ref.pathname + ref.search + ref.hash;
          }
        }
      } catch (_) {
        /* ignore */
      }
      history.replaceState(null, "", back);
      openModal(true);
    }
  }
})();
