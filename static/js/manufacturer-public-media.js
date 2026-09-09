document.querySelectorAll("[data-public-image-upload]").forEach((input) => {
  const output = input.closest(".mfr-upload").querySelector("[data-upload-name]");
  const empty = output.textContent;
  input.addEventListener("change", () => {
    output.textContent = input.files.length ? input.files[0].name : empty;
  });
});
