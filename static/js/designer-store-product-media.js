(function () {
  "use strict";

  function languageIsArabic() {
    return document.documentElement.lang === "ar" || document.documentElement.dir === "rtl";
  }

  function text(en, ar) {
    return languageIsArabic() ? ar : en;
  }

  function initForm(form) {
    var fileInput = form.querySelector("[data-store-media-file]");
    var filename = form.querySelector("[data-store-media-filename]");
    var progressWrap = form.querySelector("[data-store-media-progress-wrap]");
    var progress = form.querySelector("[data-store-media-progress]");
    var percent = form.querySelector("[data-store-media-percent]");
    var status = form.querySelector("[data-store-media-status]");
    var submit = form.querySelector("[data-store-media-submit]");
    var inFlight = false;

    if (!fileInput || !submit || !window.XMLHttpRequest || !window.FormData) {
      return;
    }

    function setFilename() {
      var selected = fileInput.files && fileInput.files[0];
      filename.textContent = selected
        ? selected.name
        : text("No file selected.", "لم يتم اختيار ملف.");
    }

    function resetInteractiveState(message, focusSubmit) {
      inFlight = false;
      submit.disabled = false;
      fileInput.disabled = false;
      status.textContent = message || "";
      if (focusSubmit) {
        submit.focus();
      }
    }

    function safeFailure(message) {
      progressWrap.hidden = true;
      progress.removeAttribute("value");
      percent.textContent = "";
      resetInteractiveState(
        message || text(
          "Product image upload could not be completed. Please try again.",
          "تعذر إكمال رفع صورة المنتج. يرجى المحاولة مرة أخرى."
        ),
        true
      );
    }

    fileInput.addEventListener("change", function () {
      setFilename();
      status.textContent = "";
    });

    form.addEventListener("submit", function (event) {
      if (inFlight) {
        event.preventDefault();
        return;
      }
      if (!fileInput.files || !fileInput.files.length) {
        // Preserve the canonical no-JS/browser validation behavior for an empty
        // file choice rather than fabricating an enhanced request.
        return;
      }

      event.preventDefault();
      inFlight = true;
      submit.disabled = true;
      fileInput.disabled = false;
      progressWrap.hidden = false;
      progress.max = 100;
      progress.value = 0;
      percent.textContent = "0%";
      status.textContent = text("Uploading…", "جارٍ الرفع…");

      var xhr = new XMLHttpRequest();
      var endpoint = form.getAttribute("action") || window.location.href;
      xhr.open("POST", endpoint, true);
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      xhr.responseType = "text";

      xhr.upload.addEventListener("progress", function (eventProgress) {
        if (!eventProgress.lengthComputable || !eventProgress.total) {
          progress.removeAttribute("value");
          percent.textContent = "";
          status.textContent = text("Uploading…", "جارٍ الرفع…");
          return;
        }
        var actual = Math.max(0, Math.min(100, Math.round((eventProgress.loaded / eventProgress.total) * 100)));
        progress.value = actual;
        percent.textContent = actual + "%";
        if (eventProgress.loaded >= eventProgress.total) {
          status.textContent = text("Processing image…", "جارٍ معالجة الصورة…");
        } else {
          status.textContent = text("Uploading…", "جارٍ الرفع…");
        }
      });

      xhr.upload.addEventListener("load", function () {
        progress.value = 100;
        percent.textContent = "100%";
        status.textContent = text("Processing image…", "جارٍ معالجة الصورة…");
      });

      xhr.addEventListener("load", function () {
        if (xhr.status < 200 || xhr.status >= 400) {
          safeFailure();
          return;
        }
        var parser = new DOMParser();
        var responseDocument = parser.parseFromString(xhr.responseText || "", "text/html");
        var feedback = responseDocument.querySelector("[data-store-media-feedback]");
        var success = feedback && feedback.querySelector('[data-store-media-message][data-level~="success"]');
        var error = feedback && feedback.querySelector('[data-store-media-message][data-level~="error"]');
        if (success) {
          status.textContent = success.textContent.trim() || text("Product image attached.", "تم إرفاق صورة المنتج.");
          window.location.assign(xhr.responseURL || window.location.href);
          return;
        }
        safeFailure(error ? error.textContent.trim() : "");
      });

      xhr.addEventListener("error", function () { safeFailure(); });
      xhr.addEventListener("abort", function () {
        safeFailure(text("Product image upload was cancelled. You can try again.", "تم إلغاء رفع صورة المنتج. يمكنك المحاولة مرة أخرى."));
      });

      xhr.send(new FormData(form));
    });

    setFilename();
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-store-media-upload-form]").forEach(initForm);
  });
})();
