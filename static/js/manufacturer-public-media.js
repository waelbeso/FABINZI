document.querySelectorAll("[data-public-image-upload]").forEach((input) => {
  const wrapper = input.closest(".mfr-upload");
  const output = wrapper ? wrapper.querySelector("[data-upload-name]") : null;
  if (!output) return;
  const empty = output.textContent;
  input.addEventListener("change", () => {
    output.textContent = input.files.length ? input.files[0].name : empty;
  });
});

document.querySelectorAll("[data-public-profile-image]").forEach((image) => {
  const frame = image.closest("[data-public-image-frame]");
  const fallback = frame ? frame.querySelector("[data-public-image-fallback]") : null;
  const showFallback = () => {
    image.hidden = true;
    if (fallback) fallback.hidden = false;
  };
  image.addEventListener("error", showFallback, { once: true });
  if (image.complete && image.naturalWidth === 0) showFallback();
});
