// Host console: drives the game and plays each song's clip window in this browser.
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

  let state = JSON.parse(document.querySelector("#initial-state").textContent);
  let playing = null; // the song whose start/end window is playing
  let preloaded = "";
  let formRound = null; // round number the rules form shows
  let formSignature = ""; // what the server last said that round contains

  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const showError = (message) => { errorBox.textContent = message; errorBox.hidden = false; };
  const clearError = () => { errorBox.hidden = true; };

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
  setInterval(() => {
    if (playing && playing.end_ms && !audio.paused && audio.currentTime * 1000 >= playing.end_ms) audio.pause();
  }, 100);
  audio.addEventListener("play", () => { pauseButton.textContent = "Pause"; });
  audio.addEventListener("pause", () => { pauseButton.textContent = "Resume"; });

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

    renderRules();
  }

  // ---- buttons
  $("#btn-start").addEventListener("click", async () => {
    const data = await post("start");
    if (data) render(data);
  });
  $("#btn-next").addEventListener("click", async () => {
    const data = await post("next");
    if (data) { playSong(data.current_song); render(data); }
  });
  $("#btn-replay").addEventListener("click", () => playSong(state.current_song));
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
    if (d) { formRound = null; render(d); }
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
  const source = new EventSource(`/games/${gameId}/run/events`);
  source.addEventListener("state", (event) => render(JSON.parse(event.data)));
  source.onopen = () => { $("#connection").textContent = "Live"; };
  source.onerror = () => { $("#connection").textContent = "Reconnecting\u2026"; };

  render(state);
}
