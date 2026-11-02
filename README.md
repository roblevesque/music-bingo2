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

Phase 2 (game engine) is implemented:

- [x] Ticket generator: unique, balanced N\u00d7N tickets (default 5\u00d75), see `app/services/ticket_gen.py`
- [x] Claim checker: decides a claim against the songs played so far, using the round's rules (`checker.py`, `patterns.py`)
- [x] Game creation UI: pick a song pool, grid size and ticket count; join code; ticket viewer
- [x] Rounds: the host chooses per round which patterns count (rows, columns, diagonals, how many lines, or full house) and can edit them at any time

Phase 1 (foundation) is implemented:

- [x] Project skeleton, config, dependencies (uv)
- [x] DB models and setup (SQLite via SQLModel)
- [x] Host login and sessions (argon2 hashes, signed cookies, CSRF tokens)
- [x] Song library: upload MP3/Ogg, read tags, edit title/artist/tags, optional write-back to the file's own tags
- [x] Per-track start and end points (non-destructive play window, with in-browser preview)

## Layout

```
app/
  main.py          app factory
  config.py        settings from env
  db.py, models.py SQLite engine and tables
  security.py      password hashing, CSRF, safe redirects
  deps.py          require_user dependency
  web.py           template rendering and flash messages
  routes/          auth.py, library.py, games.py
  services/        clips.py (audio via mutagen), parsing.py,
                   patterns.py, checker.py, ticket_gen.py (pure game logic, no framework)
  templates/       Jinja pages
  static/          styles.css, app.js (plain ES module)
tests/
```

## Deployment notes

- Behind a reverse proxy, set the request body limit at least as high as
  `MUSICBINGO_MAX_UPLOAD_MB`, and cap it so unauthenticated clients cannot send huge bodies.
- There is no login rate limiting yet; put the app behind a proxy that provides it if it
  is exposed to the internet.
- Run a single worker. Live-game pub/sub (phase 3) is in-memory.

## Upgrading from phase 1

Phase 2 only adds tables, so an existing `data/bingo.db3` is upgraded automatically on
start-up. If you ever see schema errors during development, delete `data/bingo.db3` and
re-upload; Alembic migrations should be added before real users depend on the data.

A song that is in a game's pool can't be deleted from the library until that game is deleted.
