(function () {
  function syncSwitchLabels(form, isOn) {
    if (!form) return;
    form.querySelectorAll(".kb-publish-switch-label-on").forEach(function (el) {
      el.classList.toggle("d-none", !isOn);
    });
    form.querySelectorAll(".kb-publish-switch-label-off").forEach(function (el) {
      el.classList.toggle("d-none", isOn);
    });
  }

  document.querySelectorAll(".kb-publish-switch-form").forEach(function (form) {
    var sw = form.querySelector(".kb-publish-switch");
    var hidden = form.querySelector('input[type="hidden"][name="published"]');
    if (!sw || !hidden) return;

    sw.addEventListener("change", function () {
      var wantOn = !!sw.checked;
      hidden.value = wantOn ? "1" : "0";
      syncSwitchLabels(form, wantOn);
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    });
  });
})();
