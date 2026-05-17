(function () {
  var form = document.getElementById("ai-credits-claim-form");
  var amountInp = document.getElementById("topup-amount");
  var depositorInp = document.getElementById("topup-depositor");
  var confirmBtn = document.getElementById("topup-confirm-btn");
  var amountErr = document.getElementById("topup-amount-error");
  var depositorErr = document.getElementById("topup-depositor-error");
  if (!form || !amountInp || !confirmBtn) return;

  var minAmt = parseInt(amountInp.getAttribute("data-min") || "0", 10) || 0;

  function isKo() {
    return (document.documentElement.lang || "ko") === "ko";
  }

  function digitsOnly(s) {
    return (s || "").replace(/\D/g, "");
  }

  function formatKrw(digits) {
    if (!digits) return "";
    var n = parseInt(digits, 10);
    if (!isFinite(n)) return "";
    return n.toLocaleString("ko-KR");
  }

  function hideFieldError(inp, errEl) {
    if (!inp || !errEl) return;
    inp.classList.remove("is-invalid");
    errEl.textContent = "";
    errEl.classList.add("d-none");
  }

  function showFieldError(inp, errEl, message) {
    if (!inp || !errEl) return;
    inp.classList.add("is-invalid");
    errEl.textContent = message;
    errEl.classList.remove("d-none");
  }

  function minAmountMessage() {
    var fmt = minAmt.toLocaleString("ko-KR");
    return isKo()
      ? "최소 충전 금액은 ₩" + fmt + " 이상입니다."
      : "Minimum top-up is ₩" + fmt + ".";
  }

  function depositorMessage() {
    return isKo() ? "입금자명을 입력해 주세요." : "Please enter the depositor name.";
  }

  amountInp.addEventListener("input", function () {
    hideFieldError(amountInp, amountErr);
    var raw = digitsOnly(amountInp.value);
    amountInp.value = formatKrw(raw);
  });

  if (depositorInp) {
    depositorInp.addEventListener("input", function () {
      hideFieldError(depositorInp, depositorErr);
    });
  }

  form.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
    }
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
  });

  confirmBtn.addEventListener("click", function () {
    hideFieldError(amountInp, amountErr);
    hideFieldError(depositorInp, depositorErr);

    var raw = digitsOnly(amountInp.value);
    var n = parseInt(raw, 10);
    var valid = true;

    if (!isFinite(n) || n < minAmt) {
      showFieldError(amountInp, amountErr, minAmountMessage());
      valid = false;
    }

    var dep = depositorInp ? (depositorInp.value || "").trim() : "";
    if (!dep) {
      showFieldError(depositorInp, depositorErr, depositorMessage());
      valid = false;
    }

    if (!valid) return;

    amountInp.value = raw;
    form.submit();
  });
})();
