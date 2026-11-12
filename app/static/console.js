// Host console: drives the game and plays each song's clip window in this browser.
import { connectLive, statusText } from "./live.js";
import { clampNumber, fadeVolume } from "./playback.js";

const root = document.querySelector("#console");

if (root) {
  const gameId = root.dataset.game;
  const csrf = root.dataset.csrf;
  const $ = (selector) => root.querySelector(selector);
  const audio = $("#host-audio");
  const preload = $("#preload-audio");
  const errorBox = $("#console-error");
  const pauseButton = $("#btn-pause");
  const ruleRound = $("#rule-round");
  const rulesForm = $("#rules-form");
  const autoBox = $("#auto-next");
  const autoSeconds = $("#auto-seconds");
  const fadeSeconds = $("#fade-seconds");
  const autoStatus = $("#auto-status");
  const effectAudio = $("#effect-audio");
  const effectsBox = $("#effects");
  const bgAudio = $("#bg-audio");
  const bgStatus = $("#bg-status");
  const bgVolume = $("#bg-volume");
  const bgAfter = $("#bg-after");

  let state = JSON.parse(document.querySelector("#initial-state").textContent);
  let playing = null; // the song whose start/end window is playing
  let preloaded = "";
  let formRound = null; // round number the rules form shows
  let formSignature = ""; // what the server last said that round contains
  let countdownTimer = null; // running while we wait to play the next song automatically
  let autoHold = false; // a team has called a valid bingo: don't auto-play until the host moves on
  let windowStop = false; // we paused the audio ourselves at the end of the clip window
  let activeEffect = null; // the sound effect that is playing, if any
  let bgQueue = []; // background music: the library in a shuffled order
  let bgIndex = -1;
  let bgActive = false; // the host has started it (it may be paused)
  let bgErrors = 0; // tracks in a row that failed to play
  let effectsSignature = ""; // so the effect buttons are only rebuilt when the list changes
  let knownClaims = new Set(state.claims.map((c) => c.id));

  // Playback settings are remembered in this browser (they belong to the host's setup, not the game).
  const SETTINGS_KEY = "musicbingo.console";
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    autoBox.checked = Boolean(saved.auto);
    autoSeconds.value = clampNumber(saved.autoSeconds, 0, 120, 10);
    fadeSeconds.value = clampNumber(saved.fade, 0, 10, 0);
    bgVolume.value = clampNumber(saved.bgVolume, 0, 100, 40);
    bgAfter.checked = Boolean(saved.bgAfter);
  } catch { /* storage unavailable: keep the defaults in the page */ }
  const saveSettings = () => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({
        auto: autoBox.checked, autoSeconds: autoSeconds.value, fade: fadeSeconds.value,
        bgVolume: bgVolume.value, bgAfter: bgAfter.checked,
      }));
    } catch { /* ignore */ }
  };

  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const showError = (message) => { errorBox.textContent = message; errorBox.hidden = false; };
  const clearError = () => { errorBox.hidden = true; };
  const songLine = (s) => `${s.title}${s.artist ? " \u2014 " + s.artist : ""}`;

  async function post(action, fields = {}, options = {}) {
    const body = new FormData();
    body.set("csrf_token", csrf);
    Object.entries(fields).forEach(([key, value]) => body.set(key, value));
    let response;
    try {
      response = await fetch(`/games/${gameId}/run/${action}`, { method: "POST", body });
    } catch {
      showError("Could not reach the server.");
      return null;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (!options.quiet) showError(typeof data.detail === "string" ? data.detail : "That didn't work.");
      return null;
    }
    clearError();
    return data;
  }

  // ---- audio: play only the saved start..end window of each clip
  function playSong(song) {
    if (!song) return;
    playing = song;
    const begin = () => {
      audio.currentTime = (song.start_ms || 0) / 1000;
      audio.play().catch(() => showError("Your browser blocked autoplay. Press Replay to play the clip."));
    };
    if (audio.src.endsWith(song.audio_url) && audio.readyState >= 1) {
      begin();
    } else {
      audio.src = song.audio_url;
      audio.addEventListener("loadedmetadata", begin, { once: true });
      audio.load();
    }
  }

  // Every 50 ms: apply the fade curve, and stop at the end of the saved window.
  setInterval(() => {
    if (!playing || audio.paused) return;
    const start = (playing.start_ms || 0) / 1000;
    const end = playing.end_ms ? playing.end_ms / 1000 : audio.duration;
    audio.volume = fadeVolume(audio.currentTime, start, end, clampNumber(fadeSeconds.value, 0, 10, 0));
    if (playing.end_ms && audio.currentTime >= end) {
      windowStop = true;
      audio.pause();
      onClipFinished();
    }
  }, 50);
  audio.addEventListener("play", () => { pauseButton.textContent = "Pause"; });
  audio.addEventListener("pause", () => {
    pauseButton.textContent = "Resume";
    if (windowStop) windowStop = false; // the clip ended by itself; keep the countdown going
    else cancelCountdown(); // the host paused: don't start the next song behind their back
  });
  audio.addEventListener("ended", onClipFinished);

  // ---- background music: the whole library, shuffled, for before and after the game
  const bgAllowed = () => state.game.status !== "active";
  const bgLevel = () => clampNumber(bgVolume.value, 0, 100, 40) / 100;
  async function startBackground() {
    if (!bgAllowed()) return;
    let data;
    try {
      const response = await fetch(`/games/${gameId}/run/background`);
      if (!response.ok) throw new Error();
      data = await response.json();
    } catch {
      bgStatus.textContent = "Couldn't load your library. Try again.";
      return;
    }
    if (!data.songs.length) { bgStatus.textContent = "Your library is empty. Upload some songs first."; return; }
    bgQueue = data.songs;
    bgIndex = -1;
    bgErrors = 0;
    bgActive = true;
    playNextBackground();
  }
  function playNextBackground() {
    if (!bgActive || !bgQueue.length) return;
    bgIndex = (bgIndex + 1) % bgQueue.length; // when the shuffled list runs out, go round again
    const track = bgQueue[bgIndex];
    bgAudio.src = track.audio_url;
    bgAudio.volume = bgLevel();
    bgStatus.textContent = `Playing: ${songLine(track)}`;
    bgAudio.play().catch(() => { bgStatus.textContent = "Your browser blocked the sound. Press Play again."; });
    renderBackground();
  }
  function stopBackground(fade = false) {
    if (!bgActive) return;
    bgActive = false;
    bgStatus.textContent = "";
    if (!fade || bgAudio.paused) { bgAudio.pause(); renderBackground(); return; }
    const from = bgAudio.volume;
    let step = 0;
    const timer = setInterval(() => { // ease out over about a second so the game doesn't start with a jolt
      step += 1;
      bgAudio.volume = Math.max(0, from * (1 - step / 10));
      if (step >= 10) { clearInterval(timer); bgAudio.pause(); bgAudio.volume = bgLevel(); }
    }, 80);
    renderBackground();
  }
  function renderBackground() {
    if (bgActive && !bgAllowed()) { stopBackground(true); return; }
    $("#bg-play").disabled = !bgAllowed();
    ["#bg-pause", "#bg-skip", "#bg-stop"].forEach((id) => { $(id).disabled = !bgActive; });
    $("#bg-pause").textContent = bgActive && bgAudio.paused ? "Resume" : "Pause";
  }
  $("#bg-play").addEventListener("click", startBackground);
  $("#bg-skip").addEventListener("click", playNextBackground);
  $("#bg-stop").addEventListener("click", () => stopBackground(true));
  $("#bg-pause").addEventListener("click", () => { if (bgAudio.paused) bgAudio.play(); else bgAudio.pause(); });
  bgAudio.addEventListener("play", renderBackground);
  bgAudio.addEventListener("pause", renderBackground);
  bgAudio.addEventListener("playing", () => { bgErrors = 0; });
  bgAudio.addEventListener("ended", playNextBackground);
  bgAudio.addEventListener("error", () => { // a missing or unplayable file: move on, but give up if everything fails
    if (!bgActive) return;
    bgErrors += 1;
    if (bgErrors > Math.min(10, bgQueue.length)) { stopBackground(); bgStatus.textContent = "Couldn't play those tracks."; }
    else playNextBackground();
  });
  bgVolume.addEventListener("input", () => { bgAudio.volume = bgLevel(); saveSettings(); });
  bgAfter.addEventListener("change", saveSettings);

  // ---- sound effects: the list comes from the server, so the buttons follow it
  function renderEffects() {
    const effects = state.effects || [];
    const signature = JSON.stringify(effects);
    if (signature !== effectsSignature) {
      effectsSignature = signature;
      effectsBox.replaceChildren(...effects.map((effect, index) => {
        const button = el("button", `${effect.label} (${index + 1})`, "secondary");
        button.type = "button";
        button.dataset.effect = effect.id;
        button.addEventListener("click", () => triggerEffect(effect));
        return button;
      }));
    }
    [...effectsBox.children].forEach((button) => {
      const on = Boolean(activeEffect) && button.dataset.effect === activeEffect.id;
      button.classList.toggle("playing", on);
      button.setAttribute("aria-pressed", String(on));
    });
  }
  function stopEffect() {
    effectAudio.pause();
    activeEffect = null;
    renderEffects();
  }
  function triggerEffect(effect) {
    if (activeEffect && activeEffect.id === effect.id && effect.loop) { stopEffect(); return; } // press again to stop a loop
    cancelCountdown(); // a pending automatic next song must not start under an effect
    if (bgActive && !bgAudio.paused) bgAudio.pause(); // an effect takes over from background music too
    if (!audio.paused) audio.pause();
    effectAudio.pause();
    effectAudio.src = effect.url;
    effectAudio.loop = Boolean(effect.loop);
    effectAudio.volume = 1;
    activeEffect = effect;
    effectAudio.play().catch(() => {
      activeEffect = null;
      renderEffects();
      showError("Your browser blocked the sound. Click the button again.");
    });
    renderEffects();
  }
  effectAudio.addEventListener("ended", () => { activeEffect = null; renderEffects(); });
  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest?.("input, textarea, select, [contenteditable]")) return;
    const effects = state.effects || [];
    const index = Number(event.key) - 1;
    if (Number.isInteger(index) && index >= 0 && index < effects.length) { event.preventDefault(); triggerEffect(effects[index]); }
    else if (event.key === "Escape" && activeEffect) stopEffect();
  });

  // ---- automatic next song
  function setAutoStatus(text) { autoStatus.textContent = text; }
  function cancelCountdown() {
    clearInterval(countdownTimer);
    countdownTimer = null;
    if (!autoHold) setAutoStatus("");
  }
  function startCountdown() {
    const exhausted = state.songs_played >= state.total_songs;
    if (!autoBox.checked || autoHold || state.game.status !== "active" || exhausted) return;
    const due = Date.now() + clampNumber(autoSeconds.value, 0, 120, 10) * 1000;
    clearInterval(countdownTimer);
    const tick = () => {
      const left = Math.ceil((due - Date.now()) / 1000);
      if (left <= 0) { cancelCountdown(); advance(); }
      else setAutoStatus(`Next song in ${left}s. Press Pause to stop auto-play.`);
    };
    countdownTimer = setInterval(tick, 250);
    tick();
  }
  function onClipFinished() { if (playing) startCountdown(); }

  async function advance(expect) {
    cancelCountdown();
    autoHold = false;
    setAutoStatus("");
    // From the phone, `expect` is the song count it saw: the server ignores the tap if the game has moved on.
    const fromPhone = expect !== undefined;
    const data = await post("next", fromPhone ? { expect: String(expect) } : {}, { quiet: fromPhone });
    if (data) { playSong(data.current_song); render(data); }
  }
  async function skipNext(expectNext) {
    const fromPhone = expectNext !== undefined;
    const data = await post("skip", fromPhone ? { expect_next: String(expectNext) } : {}, { quiet: fromPhone });
    if (data) render(data);
  }

  // ---- phone remote: commands arrive over the live connection and act as if the host had clicked
  const seenCommands = new Set();
  const COMMAND_NAMES = { next: "Next song", replay: "Replay", pause: "Pause/Resume", skip: "Skip next", start: "Start game",
    next_round: "Next round", effect: "Sound effect", stop_effect: "Stop effect" };
  function handleCommand(command) {
    if (seenCommands.has(command.id)) return; // never act twice on one command
    seenCommands.add(command.id);
    // A disabled button means "not allowed right now", so clicking only works when the host could have clicked it.
    const click = (selector) => { const button = $(selector); if (button && !button.disabled) button.click(); };
    switch (command.action) {
      case "next": if (!$("#btn-next").disabled) advance(command.expect); break;
      case "skip": if (!$("#btn-skip").disabled) skipNext(command.expect_next); break;
      case "replay": click("#btn-replay"); break;
      case "pause": click("#btn-pause"); break;
      case "start": click("#btn-start"); break;
      case "next_round": click("#btn-next-round"); break;
      case "effect": {
        const effect = (state.effects || []).find((e) => e.id === command.effect);
        if (effect) triggerEffect(effect);
        break;
      }
      case "stop_effect": stopEffect(); break;
    }
    $("#remote-last").textContent = `Last from a phone: ${COMMAND_NAMES[command.action] || command.action}`;
  }
  function renderRemote() {
    const remote = state.remote || { enabled: false };
    $("#remote-intro").hidden = remote.enabled;
    $("#remote-panel").hidden = !remote.enabled;
    if (!remote.enabled) return;
    $("#remote-url").textContent = remote.url || `${window.location.origin}/remote`;
    $("#remote-code").textContent = remote.code;
    $("#remote-count").textContent = `${remote.connected} phone${remote.connected === 1 ? "" : "s"} connected.`;
  }
  async function setRemote(mode) {
    const data = await post("remote", { mode });
    if (data) { $("#remote-last").textContent = ""; render(data); }
  }
  $("#remote-turn-on").addEventListener("click", () => setRemote("on"));
  $("#remote-turn-off").addEventListener("click", () => setRemote("off"));
  $("#remote-new").addEventListener("click", () => {
    if (window.confirm("Disconnect every phone and make a new code?")) setRemote("new");
  });

  // A valid bingo holds auto-play so the host can check it; "Next song" resumes it.
  function noteNewWins(next) {
    const fresh = next.claims.filter((c) => !knownClaims.has(c.id));
    knownClaims = new Set(next.claims.map((c) => c.id));
    if (fresh.some((c) => c.status === "win")) {
      autoHold = true;
      clearInterval(countdownTimer);
      countdownTimer = null;
      if (autoBox.checked) setAutoStatus("Auto-play is on hold: a team called bingo. Press Next song to continue.");
    }
  }
  [autoBox, autoSeconds, fadeSeconds].forEach((input) => input.addEventListener("change", () => {
    saveSettings();
    if (!autoBox.checked) { autoHold = false; cancelCountdown(); }
    if (input === fadeSeconds && audio.paused) audio.volume = 1;
  }));

  // ---- drawing the state
  function fillRulesForm(round) {
    rulesForm.elements.name.value = round.name;
    rulesForm.elements.mode.value = round.mode;
    rulesForm.elements.lines_required.value = round.lines_required;
    rulesForm.elements.rows.checked = round.rows;
    rulesForm.elements.columns.checked = round.columns;
    rulesForm.elements.diagonals.checked = round.diagonals;
  }

  function renderRules() {
    const rounds = state.rounds;
    ruleRound.replaceChildren(...rounds.map((r) => {
      const option = el("option", `${r.number}. ${r.name}`);
      option.value = r.id;
      return option;
    }));
    const wanted = rounds.find((r) => r.number === formRound) || state.round || rounds[0];
    if (!wanted) return;
    ruleRound.value = wanted.id;
    const signature = JSON.stringify(wanted);
    if (wanted.number !== formRound || signature !== formSignature) {
      fillRulesForm(wanted); // only when the round changed, so typing isn't overwritten
      formRound = wanted.number;
      formSignature = signature;
    }
  }

  function render(next) {
    state = next;
    noteNewWins(next);
    if (next.game.status !== "active") cancelCountdown();
    const { game, round } = state;
    const draft = game.status === "draft";
    const active = game.status === "active";
    const remaining = state.total_songs - state.songs_played;

    $("#join-code").textContent = game.code;
    $("#join-url").textContent = state.join_url;
    $("#teams-count").textContent = `${state.teams.length} team${state.teams.length === 1 ? "" : "s"} joined.`;

    $("#btn-start").disabled = !draft;
    $("#btn-next").disabled = !active || remaining < 1;
    $("#btn-replay").disabled = !state.current_song;
    $("#btn-skip").disabled = !active || remaining < 2;
    $("#btn-reshuffle").disabled = !active || remaining < 2;
    $("#btn-finish").disabled = !active;

    const song = state.current_song;
    $("#now-title").textContent = song ? song.title : "Nothing yet";
    $("#now-artist").textContent = song && song.artist ? `\u2014 ${song.artist}` : "";
    $("#progress").textContent = draft ? "Game not started." : `${state.songs_played} of ${state.total_songs} songs played`;
    const upcoming = state.next_song;
    $("#next-title").textContent = upcoming ? `${upcoming.title}${upcoming.artist ? " \u2014 " + upcoming.artist : ""}` : "\u2014";
    if (upcoming && upcoming.audio_url !== preloaded) { // fetch the next clip ahead of time
      preloaded = upcoming.audio_url;
      preload.src = upcoming.audio_url;
    }

    $("#round-text").textContent = round ? `${round.number}. ${round.name}: ${round.text}` : "No round selected.";
    const hasNext = round && state.rounds.some((r) => r.number === round.number + 1);
    $("#btn-next-round").disabled = !active || !hasNext;
    $("#btn-next-round").textContent = hasNext ? `Start round ${round.number + 1}` : "No further round (add one below)";
    const current = state.winners.find((w) => round && w.round === round.number);
    $("#winners-text").textContent = current ? `Winners so far: ${current.teams.join(", ")}` : "";

    const claims = state.claims.map((c) => {
      const label = c.status === "win" ? "VALID" : "not valid";
      return el("li", `${c.team} (ticket ${c.ticket}): ${label} after song ${c.songs_played} \u2014 ${c.detail}`, c.status);
    });
    $("#claims").replaceChildren(...(claims.length ? claims : [el("li", "No claims yet.", "muted")]));

    const teams = state.teams.map((t) => el("li", `${t.name} (ticket ${t.ticket})`));
    $("#teams").replaceChildren(...(teams.length ? teams : [el("li", "Nobody has joined yet.", "muted")]));

    $("#played").replaceChildren(...state.played.map((p) => {
      const li = el("li", `${p.title}${p.artist ? " \u2014 " + p.artist : ""}`);
      li.value = p.n; // keep the real song number even though newest is listed first
      return li;
    }));

    const queue = state.upcoming.map((s, i) => {
      const li = el("li", songLine(s), i === 0 ? "next" : "");
      li.value = s.n; // the number the song will have when it is played
      return li;
    });
    const emptyQueue = draft ? "The play order is made when you start the game." : "No songs left.";
    $("#upcoming").replaceChildren(...(queue.length ? queue : [el("li", emptyQueue, "muted")]));
    $("#upcoming-count").textContent = state.upcoming.length ? `(${state.upcoming.length})` : "";
    $("#played-count").textContent = state.played.length ? `(${state.played.length})` : "";

    // A valid bingo is the thing the host most needs to notice, so it gets a banner.
    const wins = state.claims.filter((c) => c.status === "win").reverse(); // oldest first, so ties read in order
    const banner = $("#claim-alert");
    banner.hidden = wins.length === 0;
    banner.textContent = wins.length
      ? "Bingo called! " + wins.map((w) => `${w.team} (ticket ${w.ticket}) after song ${w.songs_played}: ${w.detail}`).join(" \u2022 ")
      : "";

    renderRules();
    renderEffects();
    renderBackground();
    renderRemote();
  }

  // ---- buttons
  $("#btn-start").addEventListener("click", async () => {
    stopBackground(true); // the game is about to begin
    const data = await post("start");
    if (data) render(data);
  });
  $("#btn-next").addEventListener("click", () => advance());
  $("#btn-replay").addEventListener("click", () => { cancelCountdown(); playSong(state.current_song); });
  pauseButton.addEventListener("click", () => { if (audio.paused) audio.play(); else audio.pause(); });
  $("#btn-skip").addEventListener("click", () => skipNext());
  $("#btn-reshuffle").addEventListener("click", async () => { const d = await post("reshuffle"); if (d) render(d); });
  $("#btn-finish").addEventListener("click", async () => {
    if (!window.confirm("End the game for everyone?")) return;
    const d = await post("finish");
    if (d) {
      audio.pause();
      stopEffect();
      render(d);
      if (bgAfter.checked) startBackground();
    }
  });
  $("#btn-next-round").addEventListener("click", async () => {
    const d = await post("round", { number: state.round.number + 1 });
    if (d) { formRound = null; autoHold = false; setAutoStatus(""); render(d); }
  });

  // ---- rules: change what counts as a win, now or for a later round
  ruleRound.addEventListener("change", () => {
    const chosen = state.rounds.find((r) => String(r.id) === ruleRound.value);
    if (chosen) { fillRulesForm(chosen); formRound = chosen.number; formSignature = JSON.stringify(chosen); }
  });
  const ruleFields = () => {
    const f = rulesForm.elements;
    const fields = { name: f.name.value, mode: f.mode.value, lines_required: f.lines_required.value };
    ["rows", "columns", "diagonals"].forEach((key) => { if (f[key].checked) fields[key] = "on"; });
    return fields;
  };
  rulesForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const d = await post("rules", { round_id: ruleRound.value, ...ruleFields() });
    if (d) { formSignature = ""; render(d); }
  });
  $("#btn-add-round").addEventListener("click", async () => {
    const d = await post("rounds", ruleFields());
    if (d) render(d);
  });

  // ---- check a printed ticket
  $("#check-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const box = $("#check-result");
    const d = await post("check", { ticket_number: event.target.elements.ticket_number.value });
    if (!d) { box.hidden = true; return; }
    if (d.status === "win") {
      box.textContent = `Ticket ${d.ticket} WINS ${d.round}: ${d.lines.join(", ") || "full house"}.`;
      box.className = "flash success";
    } else {
      const need = d.missing.length ? ` Still needs: ${d.missing.join("; ")}.` : "";
      box.textContent = `Ticket ${d.ticket} does not win ${d.round} yet (${d.squares_needed} short).${need}`;
      box.className = "flash error";
    }
    box.hidden = false;
  });

  // ---- live updates
  connectLive(`/games/${gameId}/run/events`, {
    onState: render,
    onStatus: (name) => {
      $("#connection").textContent = statusText(name);
      $("#connection").classList.toggle("warn", name !== "live");
    },
    events: {
      command: handleCommand,
      remote: (info) => { state.remote = { ...(state.remote || {}), connected: info.connected }; renderRemote(); },
    },
  });

  render(state);
}
