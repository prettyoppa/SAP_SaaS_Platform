/**
 * AI credits — poll PortOne sync after PayPal/card return (?portone_sync=paymentId).
 */
(function () {
  var params = new URLSearchParams(window.location.search);
  var paymentId = (params.get("portone_sync") || "").trim();
  if (!paymentId) return;

  var busyMeta = {
    titleKo: "결제 결과를 반영하는 중입니다…",
    titleEn: "Applying your payment…",
    hintKo: "완전히 끝날 때까지 이 화면을 닫거나 이동하지 마세요.",
    hintEn: "Do not close or leave this page until processing finishes.",
  };

  function showBusy() {
    if (typeof showGlobalBusy === "function") showGlobalBusy(busyMeta);
  }

  function hideBusy() {
    if (typeof hideGlobalBusy === "function") hideGlobalBusy();
  }

  function cleanUrlAndReload() {
    var u = new URL(window.location.href);
    u.searchParams.delete("portone_sync");
    u.searchParams.set("ok", "portone");
    window.location.replace(u.pathname + u.search + (u.hash || "#topup-form"));
  }

  async function pollSync() {
    showBusy();
    var maxAttempts = 30;
    var delayMs = 2000;
    for (var i = 0; i < maxAttempts; i++) {
      try {
        var r = await fetch("/payments/portone/complete", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ paymentId: paymentId }),
        });
        var j = await r.json();
        if (j && j.ok) {
          cleanUrlAndReload();
          return;
        }
      } catch (_) {
        /* retry */
      }
      await new Promise(function (resolve) {
        setTimeout(resolve, delayMs);
      });
    }
    hideBusy();
    var errEl = document.querySelector(".account-ai-credits-alert, #portone-checkout-err, .alert-warning");
    if (!errEl) {
      var panel = document.querySelector(".account-ai-credits-topup");
      if (panel) {
        errEl = document.createElement("div");
        errEl.className = "alert alert-warning small account-ai-credits-alert mt-2";
        panel.insertAdjacentElement("afterbegin", errEl);
      }
    }
    if (errEl) {
      var isKo = (document.documentElement.getAttribute("data-lang") || "ko") === "ko";
      errEl.innerHTML = isKo
        ? "결제 반영이 지연되고 있습니다. 잠시 후 새로고침하거나 고객 지원에 문의해 주세요."
        : "Payment is taking longer to apply. Refresh in a moment or contact support.";
      errEl.classList.remove("d-none");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", pollSync);
  } else {
    pollSync();
  }
})();
