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
| Backend | FastAPI (or Flask) + Uvicorn | Same language as the original, so ticket logic is easy to port. Native SSE/WebSocket support. |
| Pages | Server-rendered Jinja2 templates | No SPA, no bundler. |
| Interactivity | [htmx](https://htmx.org) (vendored single file) + vanilla ES modules | Browsers run ES modules directly, so nothing needs compiling. |
| Live updates | Server-Sent Events (SSE) | One-way server-to-player push is all bingo needs. Simpler than WebSockets. |
| Database | SQLite via SQLAlchemy / SQLModel | Single file, no DB server. |
| Printable tickets | HTML + `@media print` CSS | No PDF library required at first. |
| Tests | pytest | Unit tests for generator and checker. |

**Run it:**

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```
 *Note:* This is an example only. Prefer the use of uv over pip. unicorn would be fine if that's the best choice. 

---

## 3. Features

### MVP
- [ ] Host login (hashed passwords, session cookies)
- [ ] Song library: upload clips (mp3/ogg), title, artist, theme tags, title ID3 tag modification
- [ ] Selection of start point, and end point for each track
- [ ] Game creation: pick songs, set number of tickets, generate tickets
- [ ] Players join with game code and display name (no account)
- [ ] Host console: play next clip, view played list, pause, skip
- [ ] Player ticket view: tap to mark songs; claim line, two lines or full house
- [ ] Server-side claim verification against the played list
- [ ] PDF ticket export
- [ ] In-browser clip trimming (Web Audio API), so ffmpeg is not needed
- [ ] Progressive game play (Each time a player wins, host can set the winable patterns for use when checking the next ticket. For instance, First Round: 1 line, Second Round: Two or more lines, Third round: Full house)

### Later
- [ ] Game import/export
- [ ] Players join with game code and display name (no account)
- [ ] Permissions model to allow some users to add more users, or deny others the abillity to create games
- [ ] Host triggerable sfx events. For example, 'thinking' music while checking tickets, win and lose sfx. 
- [ ] Pre and post game music playing. Possibly from commercial service, or from pool of music already available. 
- [ ] Host remote. Allow host to pause music, trigger events from mobile device.

---

## 4. Core Game Logic

- **Ticket:** a NxN grid of n songs drawn from the game's song pool (typically 30 to 75 songs, but leave amount up to host).
- **Ticket generator:** produces N unique tickets, balances how often each song appears, and rejects duplicates or near-duplicates.
- **Play order:** shuffled once when the game starts and stored in the DB, so games are resumable and claims are verifiable. Allow reshuffle on the fly if host decides necessary
- **Claim checker:** a claim is valid if every song in the claimed row(s) is in the played prefix. Returns one of: `win`, `rejected` (with missing songs), `already_claimed`.
- **Win types:** one line, two lines, full house.

Build and unit-test the generator and checker first. They are the correctness core of the app.

---

## 5. Data Model

| Entity | Key fields |
|---|---|
| `User` (host) | username, password_hash |
| `Song` | file path, title, artist, tags, duration |
| `Game` | code, status, song pool, play order, current index |
| `Ticket` | game, ticket number, 15 song references (3 rows x 5) |
| `Player` | game, display name, assigned ticket |
| `Claim` | player, claim type, result, timestamp |

---

## 6. Project Layout

```
musicbingo/
├── app/
│   ├── main.py            # FastAPI app, router registration
│   ├── models.py          # DB models
│   ├── routes/
│   │   ├── auth.py
│   │   ├── library.py
│   │   ├── games.py
│   │   ├── play.py
│   │   └── events.py      # SSE endpoint
│   ├── services/
│   │   ├── ticket_gen.py
│   │   ├── checker.py
│   │   └── clips.py
│   ├── templates/         # Jinja: host console, player ticket, admin
│   └── static/
│       ├── htmx.min.js    # vendored, no npm
│       ├── app.js         # ES modules
│       └── styles.css
├── data/                  # bingo.db3, clips/ (gitignored)
├── tests/
├── requirements.txt
├── Dockerfile
├── PLAN.md
└── README.md
```

---

## 7. Real-Time and Audio Design

### Events
- Server keeps an in-memory pub/sub channel per game (fine for a single worker).
- Host's "next song" is a normal POST. The server then broadcasts over SSE: `song_played`, `claim_result`, `game_over`.
- Clients that reconnect re-sync state from the DB.

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
- [ ] Project skeleton, config, dependencies
- [ ] DB models and setup
- [ ] Host login and sessions
- [ ] Song library with upload

### Phase 2: Game Engine
- [ ] Ticket generator with tests
- [ ] Claim checker with tests
- [ ] Game creation UI

### Phase 3: Play Loop
- [ ] Player join flow
- [ ] Player ticket view with marking
- [ ] Host console
- [ ] SSE event stream
- [ ] Claim flow and verification

### Phase 4: Print and Polish
- [ ] Printable tickets
- [ ] Mobile-friendly CSS
- [ ] Error handling and reconnect logic

### Phase 5: Deploy
- [ ] Dockerfile
- [ ] README with setup instructions
- [ ] Backup guidance for `data/`

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
- [ ] FastAPI vs Flask?
- [X] Do players need persistent accounts, or are game-code joins enough?
- [X] Which win types ship in the MVP?
