// The phone remote: shows the game and sends button presses to the host console, which plays the audio.
import { connectLive, statusText } from "./live.js";

const root = document.querySelector("#remote");

if (root) {
  const id = root.dataset.id;
  const csrf = root.dataset.csrf;
  const $ = (selector) => root.querySelector(selector);
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  let state = JSON.parse(document.querySelector("#initial-state").textContent);
  let effectsSignature = "";
  const recent = new Set(); // buttons pressed in the last moment: a double tap on one button can't send twice,
  // while a quick tap on a different button still goes straight through
  let toastTimer = null;

  function toast(message) {
    $("#r-toast").textContent = message;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { $("#r-toast").textContent = ""; }, 2500);
  }

  function render(next) {
    state = next;
    const offline = !state.console_online;
    const active = state.status === "active";
    const draft = state.status === "draft";

    $("#r-title").textContent = state.name;
    $("#r-offline").hidden = !offline;
    $("#r-round").textContent = state.round ? `${state.round.name}: ${state.round.text}` : "";
    $("#r-now").textContent = state.current ? state.current.title : "Nothing yet";
    $("#r-now-artist").textContent = state.current && state.current.artist ? `\u2014 ${state.current.artist}` : "";
    $("#r-next-song").textContent = state.next ? `${state.next.title}${state.next.artist ? " \u2014 " + state.next.artist : ""}` : "\u2014";
    $("#r-progress").textContent = draft ? "Game not started." : state.status === "finished" ? "The game has ended." : `${state.songs_played} of ${state.total_songs} songs played`;

    $("#r-start").hidden = !draft;
    $("#r-start").disabled = offline;
    $("#r-next").disabled = offline || !active || !state.next;
    $("#r-skip").disabled = offline || !active || !state.next;
    $("#r-pause").disabled = offline;
    $("#r-replay").disabled = offline || !state.current;
    $("#r-next-round").hidden = !state.has_next_round;
    $("#r-next-round").disabled = offline || !active;
    $("#r-stop-effect").disabled = offline;

    const banner = $("#r-win");
    banner.hidden = state.wins.length === 0;
    banner.textContent = state.wins.length
      ? "Bingo called! " + state.wins.map((w) => `${w.team} (ticket ${w.ticket}, ${w.detail})`).join(" \u2022 ")
      : "";

    const signature = JSON.stringify(state.effects);
    if (signature !== effectsSignature) { // rebuild only when the list changes, so taps aren't interrupted
      effectsSignature = signature;
      $("#r-effects").replaceChildren(...state.effects.map((effect) => {
        const button = el("button", effect.label, "remote-btn secondary");
        button.type = "button";
        button.dataset.effect = effect.id;
        button.addEventListener("click", () => send("effect", { effect: effect.id }));
        return button;
      }));
    }
    [...$("#r-effects").children].forEach((button) => { button.disabled = offline; });
  }

  async function send(action, extra = {}) {
    const key = action + (extra.effect || "");
    if (recent.has(key)) return;
    recent.add(key);
    setTimeout(() => recent.delete(key), 350);
    if (navigator.vibrate) navigator.vibrate(25);
    const body = new FormData();
    body.set("csrf_token", csrf);
    body.set("action", action);
    Object.entries(extra).forEach(([key, value]) => body.set(key, value));
    try {
      const response = await fetch(`/remote/${id}/command`, { method: "POST", body });
      if (response.ok) { toast("Sent"); return; }
      const data = await response.json().catch(() => ({}));
      toast(typeof data.detail === "string" ? data.detail : "That didn't work.");
    } catch {
      toast("No connection. Check your signal.");
    }
  }

  $("#r-start").addEventListener("click", () => send("start"));
  $("#r-next").addEventListener("click", () => send("next", { expect: state.songs_played }));
  $("#r-pause").addEventListener("click", () => send("pause"));
  $("#r-replay").addEventListener("click", () => send("replay"));
  $("#r-skip").addEventListener("click", () => send("skip", { expect_next: state.next ? state.next.id : "" }));
  $("#r-next-round").addEventListener("click", () => send("next_round"));
  $("#r-stop-effect").addEventListener("click", () => send("stop_effect"));

  // Keep the screen on while the remote is open (not every browser supports this).
  let wakeLock = null;
  async function keepAwake() {
    try { if (navigator.wakeLock && document.visibilityState === "visible") wakeLock = await navigator.wakeLock.request("screen"); }
    catch { /* not allowed: the screen may dim, which is fine */ }
  }
  document.addEventListener("visibilitychange", keepAwake);
  keepAwake();

  render(state);
  connectLive(`/remote/${id}/events`, {
    onState: render,
    onStatus: (name) => {
      $("#r-connection").textContent = name === "live" ? "" : statusText(name);
    },
    events: {
      presence: (info) => render({ ...state, console_online: info.console_online }),
      revoked: () => { window.location.href = "/remote"; }, // the host changed the code or turned the remote off
    },
  });
}
