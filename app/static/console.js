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

  let state = JSON.parse(document.querySelector("#initial-state").textContent);
  let playing = null; // the song whose start/end window is playing
  let preloaded = "";
  let formRound = null; // round number the rules form shows
  let formSignature = ""; // what the server last said that round contains
  let countdownTimer = null; // running while we wait to play the next song automatically
  let autoHold = false; // a team has called a valid bingo: don't auto-play until the host moves on
  let windowStop = false; // we paused the audio ourselves at the end of the clip window
  let knownClaims = new Set(state.claims.map((c) => c.id));

  // Playback settings are remembered in this browser (they belong to the host's setup, not the game).
  const SETTINGS_KEY = "musicbingo.console";
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    autoBox.checked = Boolean(saved.auto);
    autoSeconds.value = clampNumber(saved.autoSeconds, 0, 120, 10);
    fadeSeconds.value = clampNumber(saved.fade, 0, 10, 0);
  } catch { /* storage unavailable: keep the defaults in the page */ }
  const saveSettings = () => {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({
        auto: autoBox.checked, autoSeconds: autoSeconds.value, fade: fadeSeconds.value,
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

  async function post(action, fields = {}) {
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
      showError(typeof data.detail === "string" ? data.detail : "That didn't work.");
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

  async function advance() {
    cancelCountdown();
    autoHold = false;
    setAutoStatus("");
    const data = await post("next");
    if (data) { playSong(data.current_song); render(data); }
  }

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
  }

  // ---- buttons
  $("#btn-start").addEventListener("click", async () => {
    const data = await post("start");
    if (data) render(data);
  });
  $("#btn-next").addEventListener("click", advance);
  $("#btn-replay").addEventListener("click", () => { cancelCountdown(); playSong(state.current_song); });
  pauseButton.addEventListener("click", () => { if (audio.paused) audio.play(); else audio.pause(); });
  $("#btn-skip").addEventListener("click", async () => { const d = await post("skip"); if (d) render(d); });
  $("#btn-reshuffle").addEventListener("click", async () => { const d = await post("reshuffle"); if (d) render(d); });
  $("#btn-finish").addEventListener("click", async () => {
    if (!window.confirm("End the game for everyone?")) return;
    const d = await post("finish");
    if (d) { audio.pause(); render(d); }
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
  });

  render(state);
}
