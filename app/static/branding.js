// Live preview for the branding form. The server is the source of truth; this is only a mock-up.
const form = document.querySelector("#branding-form");

if (form) {
  const $ = (selector) => document.querySelector(selector);
  const preview = $("#preview");
  const header = $("#pv-header");
  const logo = $("#pv-logo");
  const title = $("#pv-title");
  const footer = $("#pv-footer");

  // Same rule as the server: black or white text, whichever is more readable on the colour.
  function readableOn(hex) {
    const channel = (i) => {
      const c = parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2) > 0.179 ? "#000" : "#fff";
  }

  let logoUrl = preview.dataset.logo || "";
  function update() {
    title.textContent = $("#header_text").value.trim() || "Your game name";
    footer.textContent = $("#footer_text").value.trim();
    footer.hidden = !footer.textContent;
    const accent = $("#use_accent").checked ? $("#accent_color").value : "";
    preview.style.setProperty("--brand", accent || "currentColor");
    header.style.background = accent || "transparent";
    header.style.color = accent ? readableOn(accent) : "inherit";
    logo.hidden = !logoUrl;
    if (logoUrl) logo.src = logoUrl;
  }

  $("#logo").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (logoUrl.startsWith("blob:")) URL.revokeObjectURL(logoUrl);
    logoUrl = file ? URL.createObjectURL(file) : preview.dataset.logo || "";
    update();
  });
  form.addEventListener("input", update);
  update();
}
