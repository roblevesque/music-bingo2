// Player page: tap squares to mark, call bingo, and follow the game live.
import { connectLive, statusText } from "./live.js";

const root = document.querySelector("#play");

if (root) {
  const code = root.dataset.code;
  const csrf = root.dataset.csrf;
  const banner = root.querySelector("#banner");
  const progress = root.querySelector("#progress");
  const winners = root.querySelector("#winners");
  const bingo = root.querySelector("#bingo");
  const result = root.querySelector("#claim-result");
  const connection = root.querySelector("#connection");
  let status = "draft";

  const form = (fields) => {
    const body = new FormData();
    body.set("csrf_token", csrf);
    Object.entries(fields).forEach(([key, value]) => body.set(key, value));
    return body;
  };

  function render(state) {
    status = state.status;
    if (state.status === "draft") banner.textContent = "Waiting for the host to start the game\u2026";
    else if (state.status === "finished") banner.textContent = "The game is over. Thanks for playing!";
    else if (state.round) banner.textContent = `${state.round.name}: ${state.round.text}`;
    progress.textContent = state.status === "draft" ? "" : `${state.songs_played} of ${state.total_songs} songs played`;
    bingo.disabled = state.status !== "active";

    const items = state.winners.map((entry) => {
      const li = document.createElement("li");
      li.textContent = `${entry.round_name}: ${entry.teams.join(", ")}`;
      return li;
    });
    if (items.length === 0) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "No winners yet.";
      items.push(li);
    }
    winners.replaceChildren(...items);
  }

  function showResult(text, kind) {
    result.textContent = text;
    result.className = `flash ${kind}`;
    result.hidden = false;
  }

  // Marking a square is saved on the server so a reload keeps it.
  root.querySelectorAll("button.mark").forEach((button) => {
    button.addEventListener("click", async () => {
      const marked = button.getAttribute("aria-pressed") !== "true";
      const apply = (value) => {
        button.setAttribute("aria-pressed", String(value));
        button.classList.toggle("marked", value);
      };
      apply(marked);
      try {
        const response = await fetch(`/play/${code}/mark`, {
          method: "POST",
          body: form({ position: button.dataset.pos, marked: String(marked) }),
        });
        if (!response.ok) throw new Error();
      } catch {
        apply(!marked); // the server didn't take it, so undo
        showResult("Couldn't save that. Check your connection.", "error");
      }
    });
  });

  bingo.addEventListener("click", async () => {
    bingo.disabled = true;
    try {
      const response = await fetch(`/play/${code}/claim`, { method: "POST", body: form({}) });
      const data = await response.json();
      const kind = data.status === "win" ? "success" : data.status === "rejected" ? "error" : "info";
      showResult(data.message || "Something went wrong.", kind);
    } catch {
      showResult("Couldn't reach the server. Try again.", "error");
    }
    // Brief pause before another call; the server enforces its own cooldown too.
    setTimeout(() => { bingo.disabled = status !== "active"; }, 3000);
  });

  render(JSON.parse(document.querySelector("#initial-state").textContent));

  connectLive(`/play/${code}/events`, {
    onState: render,
    onStatus: (name) => {
      connection.textContent = statusText(name);
      connection.classList.toggle("warn", name !== "live");
    },
  });
}
