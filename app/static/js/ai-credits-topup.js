(function () {
  var form = document.getElementById("ai-credits-claim-form");
  var amountInp = document.getElementById("topup-amount");
  if (!form || !amountInp) return;

  var minAmt = parseInt(amountInp.getAttribute("data-min") || "0", 10) || 0;

  function digitsOnly(s) {
    return (s || "").replace(/\D/g, "");
  }

  function formatKrw(digits) {
    if (!digits) return "";
    var n = parseInt(digits, 10);
    if (!isFinite(n)) return "";
    return n.toLocaleString("ko-KR");
  }

  amountInp.addEventListener("input", function () {
    var raw = digitsOnly(amountInp.value);
    amountInp.value = formatKrw(raw);
  });

  form.addEventListener("submit", function () {
    amountInp.value = digitsOnly(amountInp.value);
    var n = parseInt(amountInp.value, 10);
    if (!isFinite(n) || n < minAmt) {
      return;
    }
  });
})();
