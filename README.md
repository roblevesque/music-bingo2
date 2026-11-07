# Music Bingo

A web-based Music Bingo game. The host plays short clips from their own song library through
their own speakers; players mark the matching songs on their tickets, on their phones or on
paper. Pure Python: no Node.js and no front-end build step.

Inspired by [asrashley/music-bingo](https://github.com/asrashley/music-bingo). See
[PLAN.md](PLAN.md) for the roadmap and [DECISIONS.md](DECISIONS.md) for the design decisions.

## Features

- **Song library:** upload MP3 or Ogg clips, edit title, artist and tags (optionally written back into
  the file's own tags), and set a start and end point for each clip. Trimming is non-destructive: the
  file is never re-encoded and no ffmpeg is needed.
- **Games:** pick a song pool, a grid size (N×N, default 5×5) and a number of tickets. Tickets are
  unique and use every song about equally often.
- **Rounds with host-chosen patterns:** for each round the host decides what wins: rows, columns,
  diagonals, how many lines, or full house. The rules can be changed at any time, including mid-game.
- **Live play:** players join with a game code and a team name (no accounts), tap squares to mark
  them, and call Bingo. The server checks each claim against the songs actually played.
- **Host console:** start, next song, replay, pause, skip, reshuffle the songs not yet played, move
  to the next round, end the game. Optional automatic next song and fade in/out.
- **Printed tickets:** download every ticket as one numbered PDF, hand them out, and check a paper
  ticket by number from the console.
- **Run again:** re-run a finished game under a new join code, keeping the same tickets so printed
  copies stay valid (or regenerating them).
- **Phone friendly:** layouts tested at 375 px wide, with live updates that reconnect after a dropped
  connection or a phone waking up.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```bash
uv sync                                                  # creates .venv and uv.lock
uv run uvicorn app.main:create_app --factory --reload   # http://127.0.0.1:8000
uv run pytest                                            # run the tests
```

On first visit you are sent to `/setup` to create the host account. That page closes as soon as one
host exists.

### Letting phones join

For a real game, players' phones must be able to reach the host's computer:

```bash
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Then open the console using the computer's network address (for example
`http://192.168.1.20:8000`), **not** `localhost`. The join link shown in the console is built from the
address you used, so this is what makes it work on phones. Keep `MUSICBINGO_HTTPS_ONLY` at `0`
unless you serve the app over HTTPS, otherwise browsers won't send the login cookie. Some public
Wi-Fi networks isolate devices from each other; if phones can't connect, use your own hotspot or
router.

## Configuration

All optional, set as environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `MUSICBINGO_DATA_DIR` | `./data` | SQLite database (`bingo.db3`), uploaded clips, generated secret key |
| `MUSICBINGO_SECRET_KEY` | generated into `data/secret_key` | Signs session cookies |
| `MUSICBINGO_MAX_UPLOAD_MB` | `50` | Per-file upload limit |
| `MUSICBINGO_HTTPS_ONLY` | `0` | Set to `1` when served over HTTPS so cookies are marked Secure |
| `MUSICBINGO_PDF_FONT` | built-in font | Path to a `.ttf` so printed tickets can show titles in other alphabets |
| `MUSICBINGO_PDF_FONT_BOLD` | same as above | Optional bold `.ttf` to go with it |

See [Backups](#backups) for how to back up safely.

## Running a game

1. **Library:** upload clips and set each song's start and end point.
2. **Games → New game:** choose the song pool, grid size and number of tickets. Make at least as
   many tickets as you expect teams. A pool of roughly twice the number of squares per ticket gives
   more varied tickets, and the app tells you when tickets end up closer than the 80% rule.
3. **Rounds:** the game starts with one round (one line, rows only). Add more on the game page, or
   from the console during play.
4. **Printed tickets (optional):** on the game page choose paper size and tickets per page, then
   download the PDF. Each ticket is numbered.
5. **Console:** open the host console and share the join code or the `/join/CODE` link. Players
   enter a team name and get a ticket.
6. **Play:** press **Start game**, then **Next song** for each clip. The clip plays in the host's
   browser; players never see song titles, only their own ticket.
7. **Claims:** when a team taps **Bingo!** the server checks it. The console lists every claim with
   the song count at the time, so ties are visible. A rejected claim has a short cooldown.
8. **Rounds:** after a win, press **Next round**, or change what counts as a win ("Change what
   counts as a win"). The same team can win several rounds.
9. **Paper tickets:** type the ticket number into **Check a printed ticket** to see whether it wins the
   current round, and what it is still missing.
10. **Afterwards:** **End game**, then **Run this game again** from the game page.

### Automatic next song and fades

In the console, tick **Play the next song automatically** and set how many seconds to wait after each
clip. Pressing Pause or Replay cancels the countdown, and a valid bingo holds auto-play until you
press **Next song**. **Fade in and out** ramps the volume over the clip's start and end points
(0 turns it off). These settings are remembered in that browser.

### Running a game again

A finished game's page has **Run this game again**: a new join code, the same songs and rounds, and
fresh teams. By default the tickets are kept, so tickets you printed earlier still work. Tick the box
to generate new tickets instead. The games list shows each game once, as its latest run (with a
badge such as "run 3 of 3"); earlier runs are listed on the game page. Deleting the newest run
brings the previous one back to the list.

## Docker

```bash
docker compose up --build        # http://localhost:8000
```

The compose file keeps the database, clips and session key in a named volume (`bingo-data`) so they
survive rebuilds and upgrades. The image needs your `uv.lock` (run `uv sync` once and commit it) and
runs a single worker as an unprivileged user. For HTTPS behind a reverse proxy, set
`MUSICBINGO_HTTPS_ONLY=1`, and set `FORWARDED_ALLOW_IPS` to the proxy's address so join links use
the public address. If you mount a folder from the host instead of the volume, make it writable by
uid 10001.

## Backups

Don't just copy `bingo.db3` while the app is running: recent changes can still be in a side file.
Use the built-in tool, which is safe to run mid-game:

```bash
uv run python -m app.backup create --out backups --keep 14   # timestamped .tar.gz, newest 14 kept
uv run python -m app.backup restore backups/musicbingo-backup-<time>.tar.gz --data-dir data
```

A backup holds the database, the uploaded clips and the session key (so everyone stays logged in
after a restore). Treat it as sensitive and copy it off the machine. Restoring into a folder that
already has data needs `--force`, which moves the old data into a `before-restore-<time>` folder
instead of deleting it. In Docker:

```bash
docker compose exec musicbingo python -m app.backup create --out /data/backups --keep 14
docker compose cp musicbingo:/data/backups ./backups
```

To restore into a fresh container, copy the archive in with `docker compose cp` and run
`python -m app.backup restore <archive> --data-dir /data --force` inside it, then restart.

## Game night checklist

Before:

- [ ] Clips uploaded and their start/end points checked by ear
- [ ] Game created with enough tickets; rounds set up (add a spare round or two)
- [ ] Tickets printed from the PDF, if you are using paper
- [ ] Computer and phones on the same network; console opened by network address; join link tried on a phone
- [ ] Speakers connected and volume tested; one click on the console page done so the browser allows audio

During:

- [ ] Start game, then Next song (or turn on automatic next song)
- [ ] Valid bingo: check the claim, announce, then Next round (or change the rules)
- [ ] Paper claims: check the ticket number in the console
- [ ] If a clip doesn't start, press Replay

After:

- [ ] End game; run it again next time instead of building a new one

## Layout

```
app/
  main.py            app factory, error pages
  config.py          settings from environment variables
  backup.py          backup and restore (python -m app.backup)
  db.py, models.py   SQLite engine, tables, additive migrations
  security.py        password hashing, CSRF, safe redirects
  deps.py            require_user dependency
  web.py             template rendering, flash messages, error page
  routes/
    auth.py          first-run setup, login, logout, home page
    library.py       song library
    games.py         games, rounds, tickets, PDF download, run again
    run.py           host console and its actions
    play.py          joining, marking, claiming (player side)
  services/          pure Python where possible (no web framework)
    patterns.py      what counts as a win
    checker.py       claim verification
    ticket_gen.py    ticket generation
    playlist.py      play order
    series.py        runs of the same game
    events.py        live-update hub (Server-Sent Events)
    snapshots.py     state sent to players and to the host
    pdf.py           printable tickets (reportlab)
    clips.py         audio files and tags (mutagen)
    parsing.py       tags and time values
  templates/         Jinja pages
  static/            styles.css and plain ES modules (app, play, console, live, playback)
tests/
Dockerfile, compose.yaml, .dockerignore
```

## Design notes

- **In-room audio:** only the host's browser plays audio. Players see tickets, never titles.
- **One worker:** live updates are held in memory, and game actions rely on being handled one at a
  time by a single event loop. Run one `uvicorn` worker.
- **Live updates:** Server-Sent Events carry full state snapshots, so reconnecting always re-syncs.
- **Rules per round:** a win is decided by the round's rules at the moment of the claim, so changing
  them mid-game takes effect immediately.
- **Tickets are data:** a ticket is a list of song ids, so reusing a game can keep printed tickets valid.

## Deployment notes

- Behind a reverse proxy, set the request body limit at least as high as
  `MUSICBINGO_MAX_UPLOAD_MB`, and cap it so unauthenticated clients cannot send huge bodies.
- Run it in Docker with the included `Dockerfile` and `compose.yaml` (see above).
- Reverse proxies must not buffer `text/event-stream` responses (the app sends `X-Accel-Buffering: no`
  for nginx).
- There is no login rate limiting yet; put the app behind something that provides it if it is exposed
  to the internet.
- The join link uses the address the console was opened from. Behind a proxy, make sure it forwards
  the original host and scheme.

## Upgrading

New tables are created on start-up. Columns added to existing tables since the first release
(`game.current_round`, `game.series_id`, `game.run_number`) are added by a small built-in migration,
so an existing `data/bingo.db3` keeps working. Add Alembic before real users depend on the data.

## Known limitations

- A team is tied to the browser it joined from (a signed cookie). Reopening the join link in the same
  browser resumes the team; another browser joins as a new team.
- Fades use the browser's volume control, which iPhones and iPads ignore. Use a laptop as the host.
- Browsers may block audio until the page has been clicked. If a clip doesn't start, press Replay.
- Printed tickets use a built-in font that covers Western European text. Other alphabets print as `?`
  unless you set `MUSICBINGO_PDF_FONT`.
- A song that is in a game's pool can't be deleted from the library until that game is deleted.
  Rounds that have been played, or are in play, can't be deleted.
- Grids larger than about 6×6 are cramped on a phone.

## Possible next steps

From the "Later" list in PLAN.md: game import/export, a permissions model for multiple hosts,
sound effects the host can trigger (thinking music, win and lose sounds), music before and after
the game, and a phone remote for the host.
