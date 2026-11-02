// Small progressive enhancements. No build step: this file is served as-is.

// Confirm before destructive form submits: <form data-confirm="Are you sure?">
document.addEventListener("submit", (event) => {
  const message = event.target.dataset?.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});

// Clip editor: capture start/end from the player and preview the selected window.
function setupClipEditor() {
  const player = document.querySelector("#clip-player");
  if (!player) return;
  const startInput = document.querySelector("#start");
  const endInput = document.querySelector("#end");

  const format = (seconds) => {
    const tenths = Math.round(seconds * 10);
    const minutes = Math.floor(tenths / 600);
    const rest = ((tenths % 600) / 10).toFixed(1).padStart(4, "0");
    return `${minutes}:${rest}`;
  };

  const parse = (text) => {
    const trimmed = text.trim();
    if (!trimmed) return null;
    const parts = trimmed.split(":").map(Number);
    if (parts.length > 3 || parts.some((n) => !Number.isFinite(n) || n < 0)) return null;
    return parts.reduce((total, n) => total * 60 + n, 0);
  };

  document.querySelectorAll("[data-capture]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.capture === "start" ? startInput : endInput;
      target.value = format(player.currentTime);
    });
  });

  let windowEnd = null;
  player.addEventListener("timeupdate", () => {
    if (windowEnd !== null && player.currentTime >= windowEnd) {
      player.pause();
      windowEnd = null;
    }
  });
  player.addEventListener("pause", () => {
    // A manual pause cancels the preview auto-stop.
    if (windowEnd !== null && player.currentTime < windowEnd) windowEnd = null;
  });

  document.querySelector("#preview")?.addEventListener("click", () => {
    player.currentTime = parse(startInput.value) ?? 0;
    windowEnd = parse(endInput.value);
    player.play();
  });
}

setupClipEditor();
