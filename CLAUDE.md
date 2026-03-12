# Fantasy Football Regret Engine

## Project Overview

Three ways to regret your fantasy football season — whether you drafted the wrong player, picked up the wrong player, or started the wrong player. Built for Yahoo Fantasy Football managers in a single league ("The Newer CFL" — 14 teams, game ID `461`, league ID `186782`).

## Tech Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Backend | FastAPI (async) | Entry point: `app/main.py` |
| ORM | SQLAlchemy 2.0 (async) | Models: `app/models/__init__.py` |
| DB (prod) | PostgreSQL + asyncpg | Railway-hosted |
| DB (local) | SQLite + aiosqlite | File: `ff_regret.db` |
| Data | nfl_data_py + Polars | NFL stats and player IDs |
| Yahoo API | yahoo-fantasy-api + yahoo_oauth | OAuth tokens in `app/oauth2.json` (gitignored) |
| Frontend | HTMX 1.9.10 + Tailwind CSS (CDN) | Jinja2 templates, dark mode |
| Fuzzy match | rapidfuzz | Player name matching |
| Package mgr | uv | Lock file: `uv.lock` |
| Deploy | Railway (Dockerfile) | Config: `railway.toml` |

## Commands

```bash
# Local dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Initialize data (local)
uv run python scripts/initialize_data_v2.py

# Initialize data against Railway Postgres
DATABASE_URL="postgresql+asyncpg://<user>:<pass>@<host>:<port>/<db>" uv run python scripts/initialize_data_v2.py

# Calculate regret metrics
uv run python scripts/calculate_regrets.py

# Test Yahoo API connection
uv run python scripts/test_connection.py
```

## Architecture

### Database (Lazy Init)
`app/db/__init__.py` uses a lazy initialization pattern. `_init_engine()` creates the engine on first use. `async_session()` is a function (not a sessionmaker instance) that returns a new AsyncSession. All scripts and routes import `async_session` and call it as `async_session()`.

### Config
`app/config.py` — Pydantic `Settings` class loads from `.env` file. The `async_database_url` property converts Railway's `postgresql://` or `postgres://` URLs to `postgresql+asyncpg://` format.

### Routes
All in `app/main.py`. Routes use lazy imports for models and `async_session` inside the function body to avoid circular imports and ensure DB is initialized.

### Services (`app/services/`)
- `yahoo_service.py` — Yahoo Fantasy API wrapper with OAuth2 token management
- `nfl_service.py` — nfl_data_py wrapper, converts Pandas→Polars
- `player_mapper.py` — 3-tier matching: ID lookup → exact name → fuzzy match (rapidfuzz)
- `scoring_calculator.py` — Yahoo stat ID → NFL column mapping (60+ stats), calculates fantasy points
- `lineup_optimizer.py` — Greedy algorithm respecting position constraints, bye weeks, injuries
- `regret_engine.py` — Orchestrates draft/waiver/start-sit regret calculations

### Frontend (`app/frontend/`)
- `base.html` — Tailwind dark mode + HTMX + Inter font via CDN
- `index.html` — Team selection dashboard with HTMX-driven loading
- `team.html` — Team-specific regret dashboard
- `components/` — Reusable regret card templates (draft, waiver, start/sit)

### Scripts (`scripts/`)
- `initialize_data_v2.py` — Main pipeline: Yahoo fetch → NFL data → player mapping → scoring → store
- `calculate_regrets.py` — Compute regret metrics for all teams
- Various `fetch_*.py`, `map_*.py`, `test_*.py`, `debug_*.py` utilities

## Database Tables

7 tables in `app/models/__init__.py`:
- `league_config` — Scoring rules + roster requirements (JSON)
- `player_map` — yahoo_id (PK) ↔ gsis_id mapping with confidence score
- `nfl_game_logs` — Weekly stats + calculated fantasy points (indexed on player_id+week)
- `league_weekly_rosters` — JSON roster snapshots per team per week
- `league_draft_results` — Draft picks with round/overall pick
- `waiver_wire_availability` — Weekly ownership % and waiver status
- `regret_metrics` — Precomputed regret scores + narrative JSON payloads

## Deployment

- **Platform**: Railway (personal account, private deployment)
- **Build**: Multi-stage Dockerfile with `uv` for fast installs
- **Config**: `railway.toml` — health check on `/health`, 60s timeout
- **DB**: Railway PostgreSQL service, `DATABASE_URL` auto-injected
- **Start**: `sh -c 'uvicorn app.main:app --host 0.0.0.0 --port $PORT'`
- **URL**: `https://ff-regret-production.up.railway.app`
- **Data seeding**: Run `initialize_data_v2.py` locally with `DATABASE_URL` pointing to Railway's public Postgres URL

## Environment Variables

| Variable | Local | Railway |
|----------|-------|---------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./ff_regret.db` | Auto-injected by PostgreSQL service |
| `YAHOO_CONSUMER_KEY` | `.env` | Manual |
| `YAHOO_CONSUMER_SECRET` | `.env` | Manual |
| `YAHOO_ACCESS_TOKEN` | `.env` | Manual |
| `YAHOO_REFRESH_TOKEN` | `.env` | Manual |
| `YAHOO_LEAGUE_ID` | `186782` | `186782` |
| `YAHOO_GAME_ID` | `nfl` | `nfl` |
| `SEASON_YEAR` | `2024` | `2024` |

## Code Style

- Python ≥3.11, <3.13
- Indentation: 4 spaces
- Line length: 100 (black + ruff)
- Formatter: `black`
- Linter: `ruff` (E, F, W, I, N, B, C4, UP)
- Type checker: `mypy` (strict mode)
- Git: conventional commits (`feat:`, `fix:`, `refactor:`, etc.)
- Comments: only when "why" isn't obvious
