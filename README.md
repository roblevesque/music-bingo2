# Music Bingo

A web-based Music Bingo app. The host plays short song clips from their own library;
players mark the matching songs on their tickets. Pure Python, no Node.js and no
front-end build step. See [PLAN.md](PLAN.md) for the roadmap.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
uv sync                                                      # creates .venv and uv.lock
uv run uvicorn app.main:create_app --factory --reload       # http://127.0.0.1:8000
uv run pytest                                                # run the tests
```

On first visit you are sent to `/setup` to create the host account. That page closes
as soon as one host exists.

## Configuration

All optional, set as environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `MUSICBINGO_DATA_DIR` | `./data` | SQLite database (`bingo.db3`), uploaded clips, generated secret key |
| `MUSICBINGO_SECRET_KEY` | generated into `data/secret_key` | Signs session cookies |
| `MUSICBINGO_MAX_UPLOAD_MB` | `50` | Per-file upload limit |
| `MUSICBINGO_HTTPS_ONLY` | `0` | Set to `1` when served over HTTPS so cookies are marked Secure |

Back up the whole `data/` directory.

## Status

Phase 3 (play loop) is implemented:

- [x] Players join with a game code and a team name (no accounts); each team gets its own ticket
- [x] Player page: tap squares to mark them (saved on the server), call Bingo, see the round's rules and winners
- [x] Host console: start, next song, replay, pause, skip, reshuffle the unplayed songs, end game
- [x] Live updates over Server-Sent Events (no polling, no WebSocket library)
- [x] Claims verified by the server against the songs actually played, using the current round's rules
- [x] Progressive rounds: after a win the host moves to the next round, or changes what counts as a win at any time
- [x] Check a *printed* ticket by number (for paper play)

Phase 2 (game engine) is implemented:

- [x] Ticket generator: unique, balanced N×N tickets (default 5×5), see `app/services/ticket_gen.py`
- [x] Claim checker: decides a claim against the songs played so far, using the round's rules (`checker.py`, `patterns.py`)
- [x] Game creation UI: pick a song pool, grid size and ticket count; join code; ticket viewer
- [x] Rounds: the host chooses per round which patterns count (rows, columns, diagonals, how many lines, or full house) and can edit them at any time

Phase 1 (foundation) is implemented:

- [x] Project skeleton, config, dependencies (uv)
- [x] DB models and setup (SQLite via SQLModel)
- [x] Host login and sessions (argon2 hashes, signed cookies, CSRF tokens)
- [x] Song library: upload MP3/Ogg, read tags, edit title/artist/tags, optional write-back to the file's own tags
- [x] Per-track start and end points (non-destructive play window, with in-browser preview)

## Running a game

1. Upload clips to the **Library** and set each song's start/end point.
2. **Games → New game**: pick the song pool, grid size and number of tickets, then set up the rounds.
3. Open the **host console** and share the join code (or the `/join/CODE` link). Players enter a team name.
4. Press **Start game**, then **Next song** for each clip. The clip plays in the host's browser through
   the host's speakers; players never see song titles, only their own ticket.
5. A team taps **Bingo!**; the server checks the claim. The console lists every claim with the song
   count at the time, so ties are visible. Use **Next round** (or edit the rules) to continue.

Notes:

- A team is tied to the browser it joined from (a signed cookie). Reopening the join link in the same
  browser resumes the team; a different browser has to join as a new team.
- Browsers may block audio until you have clicked something on the page. If a clip doesn't start,
  press **Replay**.
- The join link uses the address you opened the console from. Behind a reverse proxy, make sure it
  forwards the original host and scheme.

## Layout

```
app/
  main.py          app factory
  config.py        settings from env
  db.py, models.py SQLite engine and tables
  security.py      password hashing, CSRF, safe redirects
  deps.py          require_user dependency
  web.py           template rendering and flash messages
  routes/          auth.py, library.py, games.py, run.py (host console), play.py (players)
  services/        clips.py (audio via mutagen), parsing.py,
                   patterns.py, checker.py, ticket_gen.py, playlist.py, events.py (pure, no framework),
                   snapshots.py (state sent to players and host)
  templates/       Jinja pages
  static/          styles.css, app.js, play.js, console.js (plain ES modules)
tests/
```

## Deployment notes

- Behind a reverse proxy, set the request body limit at least as high as
  `MUSICBINGO_MAX_UPLOAD_MB`, and cap it so unauthenticated clients cannot send huge bodies.
- There is no login rate limiting yet; put the app behind a proxy that provides it if it
  is exposed to the internet.
- Run a single worker (`uvicorn` default). Live updates are in-memory, and game actions rely on
  being handled one at a time by one event loop.
- Reverse proxies must not buffer `text/event-stream` responses (the app sends `X-Accel-Buffering: no`
  for nginx).

## Upgrading from an earlier phase

New tables are created automatically on start-up, and the one column added since phase 2
(`game.current_round`) is added by a small built-in migration, so an existing `data/bingo.db3` keeps working. If you ever see schema errors during development, delete `data/bingo.db3` and
re-upload; Alembic migrations should be added before real users depend on the data.

A song that is in a game's pool can't be deleted from the library until that game is deleted.
