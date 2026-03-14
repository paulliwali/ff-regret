# Fantasy Football Regret Engine

## Project Overview

Three ways to regret your fantasy football season — whether you drafted the wrong player, picked up the wrong player, or started the wrong player. Built for Yahoo Fantasy Football managers in a single league ("The Newer CFL" — 14 teams). Supports multiple seasons via Yahoo API as the sole data source.

**2024 league:** `449.l.776116` (season=2024, end_week=17)
**2025 league:** `461.l.186782` (current, season=2025, end_week=17)

## Tech Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Backend | FastAPI (async) | Entry point: `app/main.py` |
| ORM | SQLAlchemy 2.0 (async) | Models: `app/models/__init__.py` |
| DB (prod) | PostgreSQL + asyncpg | Railway-hosted |
| DB (local) | SQLite + aiosqlite | File: `ff_regret.db` |
| Data | Yahoo Fantasy API | Sole data source for stats + points |
| Yahoo API | yahoo-fantasy-api + yahoo_oauth | OAuth tokens in `app/oauth2.json` (gitignored) |
| Frontend | HTMX 1.9.10 + Tailwind CSS (CDN) | Jinja2 templates, dark mode |
| Package mgr | uv | Lock file: `uv.lock` |
| Deploy | Railway (Dockerfile) | Config: `railway.toml` |

## Commands

```bash
# Local dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Initialize data from Yahoo API (per season)
uv run python scripts/initialize_yahoo.py --league-key 449.l.776116 --season-year 2024
uv run python scripts/initialize_yahoo.py --league-key 461.l.186782 --season-year 2025

# Initialize against Railway Postgres
DATABASE_URL="postgresql+asyncpg://<user>:<pass>@<host>:<port>/<db>" uv run python scripts/initialize_yahoo.py --league-key 461.l.186782 --season-year 2025

# Calculate regret metrics (per season)
uv run python scripts/calculate_regrets.py --season-year 2024
uv run python scripts/calculate_regrets.py --season-year 2025

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
- `yahoo_service.py` — Yahoo Fantasy API wrapper with OAuth2 token management, player stats, matchups
- `lineup_optimizer.py` — Greedy algorithm respecting position constraints, bye weeks, injuries
- `regret_engine.py` — Orchestrates draft/waiver/start-sit regret calculations (season_year-aware)

### Frontend (`app/frontend/`)
- `base.html` — Tailwind dark mode + HTMX + Inter font via CDN
- `index.html` — Team selection dashboard with HTMX-driven loading
- `team.html` — Team-specific regret dashboard
- `components/` — Reusable regret card templates (draft, waiver, start/sit)

### Scripts (`scripts/`)
- `initialize_yahoo.py` — Main pipeline: Yahoo API → cache → store (per league/season)
- `calculate_regrets.py` — Compute regret metrics for all teams (per season)
- `initialize_data_v2.py` — Legacy pipeline (nfl_data_py, kept for reference)
- Various `fetch_*.py`, `map_*.py`, `test_*.py`, `debug_*.py` utilities

## Database Tables

8 tables in `app/models/__init__.py` (all season_year-scoped):
- `league_config` — Scoring rules + roster requirements (JSON)
- `player_map` — yahoo_id ↔ gsis_id mapping (identity when Yahoo-only), with position + season_year
- `nfl_game_logs` — Weekly stats + fantasy points from Yahoo `total_points`
- `league_weekly_rosters` — JSON roster snapshots per team per week
- `league_draft_results` — Draft picks with round/overall pick + season_year
- `waiver_wire_availability` — Weekly ownership % and waiver status + season_year
- `league_matchups` — Weekly matchup results (team scores, W/L) + season_year
- `regret_metrics` — Precomputed regret scores + narrative JSON payloads + season_year

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
