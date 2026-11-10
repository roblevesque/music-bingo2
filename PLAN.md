# Music Bingo: Project Plan

A web-based Music Bingo app, inspired by [asrashley/music-bingo](https://github.com/asrashley/music-bingo), built entirely in Python with **no Node.js or front-end build step**.

In Music Bingo, the numbers of normal bingo are replaced by songs. Players listen to short clips and mark the matching songs on their tickets.

---

## 1. Goals and Non-Goals

### Goals
- Host creates games from their own library of song clips
- Players join from any browser using a game code
- Live play: host plays clips, players mark tickets, claims are verified by the server
- Simple deployment: `pip install` and run, or a single Docker container
- No Node.js, npm, bundlers or transpilers at any stage

### Non-Goals (for now)
- Streaming or licensing commercial music
- Large-scale hosting (thousands of concurrent games)

---

## 2. Technology Choices

| Layer | Choice | Rationale |
|---|---|---|
| Backend | FastAPI + Uvicorn | Same language as the original, so ticket logic is easy to port. Native SSE/WebSocket support. |
| Pages | Server-rendered Jinja2 templates | No SPA, no bundler. |
| Interactivity | Vanilla ES modules + `fetch` (htmx wasn't needed) | Browsers run ES modules directly, so nothing needs compiling. |
| Live updates | Server-Sent Events (SSE) | One-way server-to-player push is all bingo needs. Simpler than WebSockets. |
| Database | SQLite via SQLAlchemy / SQLModel | Single file, no DB server. |
| Printable tickets | reportlab (pure Python) | One numbered PDF of every ticket, Letter or A4, 1, 2 or 4 per page. |
| Tests | pytest | Unit tests for generator and checker. |

**Run it:**

```bash
uv sync
uv run uvicorn app.main:create_app --factory --reload
```

Or in Docker: `docker compose up --build`.

---

## 3. Features

### MVP
- [X] Host login (hashed passwords, session cookies)
- [X] Song library: upload clips (mp3/ogg), title, artist, theme tags, title ID3 tag modification
- [X] Selection of start point, and end point for each track
- [X] Game creation: pick songs, set number of tickets, generate tickets
- [X] Players join with game code and display name (no account)
- [X] Host console: play next clip, view played list, pause, skip
- [X] Player ticket view: tap to mark songs; claim line, two lines or full house
- [X] Server-side claim verification against the played list
- [X] PDF ticket export
- [X] In-browser clip trimming, so ffmpeg is not needed (delivered as non-destructive start/end markers with a preview; files are never re-encoded)
- [X] Progressive game play (Each time a player wins, host can set the winable patterns for use when checking the next ticket. For instance, First Round: 1 line, Second Round: Two or more lines, Third round: Full house)

### Later
- [X] Ticket branding via web interface
- [ ] Remaining playlist visible from host console, not just next up
- [ ] Related to above perhaps, but host console more completely and effectively using screen real estate
- [X] Game import/export
- [X] Permissions model to allow some users to add more users, or deny others the abillity to create games
- [X] Host triggerable sfx events (built-in win, lose and thinking sounds). For example, 'thinking' music while checking tickets, win and lose sfx. 
- [ ] Configurable sound effects: choose from an assortment, or upload your own
- [ ] Pre and post game music playing. Possibly from commercial service, or from pool of music already available. 
- [ ] Host remote. Allow host to pause music, trigger events from mobile device

---

## 4. Core Game Logic

- **Ticket:** a NxN grid (typically, 5x5 but host configurable) of a number songs drawn from the game's song pool (typically 30 to 75 songs, but leave amount up to host).
- **Ticket generator:** produces N unique tickets, balances how often each song appears, and rejects duplicates or near-duplicates.
    -   Near-Duplicate tickets are defined as tickets that share approximately 80% of the same song IDs, or the same set of songs in a different permutation.
    -   Implemented as: no two tickets hold the same set of songs, and where the pool allows, any two differ in at least a fifth of their squares. Small pools relax this step by step, and the host is warned whenever tickets end up closer than that.
- **Play order:** shuffled once when the game starts and stored in the DB, so games are resumable and claims are verifiable. Allow reshuffle on the fly if host decides necessary
- **Claim checker:** a claim is valid if every song in the claimed row(s) is in the played prefix. Returns one of: `win`, `rejected` (with missing songs), `already_claimed`.
- **Win types:** chosen by the host per round and changeable at any time: rows, columns and/or diagonals, a configurable number of lines, or full house.

Build and unit-test the generator and checker first. They are the correctness core of the app.

---

## 5. Data Model

| Entity | Key fields |
|---|---|
| `User` (host) | username, password_hash, is_admin, can_create_games, is_active, must_change_password, token_version |
| `Song` | owner, stored file, title, artist, tags, duration, start_ms, end_ms, sha256 |
| `Game` | owner, name, code, status, grid_size, play_order, current_index, current_round, series_id, run_number |
| `GameSong` | game, song (the song pool) |
| `Ticket` | game, ticket number, cells (song ids, row-major, N x N) |
| `Round` | game, number, name, mode (lines / full house), lines_required, rows, columns, diagonals |
| `Team` | game, name, ticket, marks (replaces `Player`; no accounts, remembered by a signed cookie) |
| `Claim` | game, team, round, status (win / rejected), songs played at the time, detail, timestamp |

---

## 6. Project Layout

```
music-bingo2/
├── app/
│   ├── main.py            # app factory, error pages
│   ├── config.py, db.py, models.py, security.py, deps.py, web.py
│   ├── backup.py          # python -m app.backup create|restore
│   ├── routes/            # auth, library, games, run (host console), play (players)
│   ├── services/          # patterns, checker, ticket_gen, playlist, series, events (SSE hub),
│   │                      # snapshots, pdf, clips, parsing
│   ├── templates/         # Jinja pages
│   └── static/            # styles.css, app.js, play.js, console.js, live.js, playback.js
├── data/                  # bingo.db3, clips/, secret_key (gitignored)
├── tests/
├── pyproject.toml, uv.lock
├── Dockerfile, compose.yaml, .dockerignore
├── PLAN.md, DECISIONS.md
└── README.md
```

---

## 7. Real-Time and Audio Design

### Events
- Server keeps an in-memory pub/sub channel per game (fine for a single worker).
- Host actions (next song, claims, round changes) are normal POSTs. The server then broadcasts a full `state` snapshot over SSE, separately for players (no song titles) and for the host, plus a `ping` every 15 seconds.
- Clients that reconnect get the current snapshot straight away, and back off and retry if the server is unreachable.

### Audio modes

| Mode | How it works | Trade-offs |
|---|---|---|
| **In-room** | Only the host's browser plays audio. Players' phones show tickets. | Simplest. Matches pub-style music bingo. |
| **Remote** | Each player's browser plays the clip, started from a server timestamp. | Needs "Join audio" tap (autoplay policy). About 1 s drift. |

- Serve clips with HTTP range support so seeking and preloading work.
- Preload the next clip on the host to avoid gaps.

---

## 8. Roadmap

### Phase 1: Foundation
- [X] Project skeleton, config, dependencies
- [X] DB models and setup
- [X] Host login and sessions
- [X] Song library with upload

### Phase 2: Game Engine
- [X] Ticket generator with tests
- [X] Claim checker with tests
- [X] Game creation UI

### Phase 3: Play Loop
- [X] Player join flow
- [X] Player ticket view with marking
- [X] Host console
- [X] SSE event stream
- [X] Claim flow and verification

### Phase 4: Print and Polish
- [X] Printable tickets
- [X] Mobile-friendly CSS
- [X] Error handling and reconnect logic
- [X] Automaticly play next song after x seconds
- [X] Fade in / fade out song sections
- [X] Game restart / reuse (with new join code)

### Phase 5: Deploy
- [X] Dockerfile
- [X] README with setup instructions
- [X] Backup guidance for `data/`

### Phase 6: Extras
- [ ] Items from the "Later" list in section 3

Phases 1 to 3 produce a playable game. Each phase ends with something runnable or testable.

---

## 9. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Browser autoplay restrictions | Require an explicit "Start game" / "Join audio" button press. |
| Audio sync drift in remote mode | Accept about 1 s drift, or recommend in-room mode. |
| Single-process pub/sub limits scale | Fine for hundreds of players. Add Redis only if needed. |
| Music licensing | Host supplies their own clips. Keep clips short. Do not ship copyrighted audio. |
| Duplicate or unfair tickets | Generator enforces uniqueness and balance, covered by tests. |

---

## 10. Open Decisions (Answers in DECISIONS.md)

- [X] Primary audio mode: in-room, remote, or both?
- [X] FastAPI vs Flask? (FastAPI)
- [X] Do players need persistent accounts, or are game-code joins enough?
- [X] Which win types ship in the MVP?
