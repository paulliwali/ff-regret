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

# Run any script against Railway Postgres (RAILWAY_DATABASE_URL is in .env)
DATABASE_URL=$(grep RAILWAY_DATABASE_URL .env | cut -d= -f2-) uv run python scripts/initialize_yahoo.py --league-key 461.l.186782 --season-year 2025

# Calculate regret metrics (per season, add DATABASE_URL= prefix for Railway)
uv run python scripts/calculate_regrets.py --season-year 2024
uv run python scripts/calculate_regrets.py --season-year 2025

# Test Yahoo API connection
uv run python scripts/test_connection.py
```

## Architecture

### Data Pipeline

Yahoo API is the sole data source. The pipeline runs per league/season:

1. **Fetch** — `scripts/initialize_yahoo.py` calls Yahoo API for league config, draft results, weekly rosters (all 17 weeks × 14 teams), waiver wire, player stats (`total_points` per player per week), and matchup results. All responses cached in `.cache/{season_year}/` as JSON.
2. **Store** — Pipeline writes to 7 tables with season-scoped DELETEs (running for 2025 never touches 2024 data). Player mapping is identity: `yahoo_id == gsis_id` since Yahoo is the only source. Fantasy points come directly from Yahoo's `total_points` field — no custom scoring calculator needed.
3. **Calculate** — `scripts/calculate_regrets.py` runs three regret algorithms per team, stores results in `regret_metrics` with narrative text in `data_payload`.
4. **Serve** — FastAPI serves precomputed regrets via JSON API endpoints. Frontend fetches and renders client-side.

### Regret Algorithms

**Draft Regret**: For each draft pick, find players drafted within ±3 picks at the same position. Calculate season-long points delta. Keep top 3 biggest misses per team.

**Waiver Regret**: For weeks 1-14, find free agents (≤30% owned) who outscored the team's worst rostered player at that position for rest-of-season by >20 points. Deduplicate per FA, keep top 3.

**Start/Sit Regret**: For each week, compare actual lineup points to optimal lineup (greedy algorithm respecting position constraints: QB/2RB/2WR/TE/FLEX/K/DEF). Store specific bench↔start swaps with point deltas.

### Database (Lazy Init)
`app/db/__init__.py` uses a lazy initialization pattern. `_init_engine()` creates the engine on first use. `async_session()` is a function (not a sessionmaker instance) that returns a new AsyncSession. All scripts and routes import `async_session` and call it as `async_session()`.

### Config
`app/config.py` — Pydantic `Settings` class loads from `.env` file. `extra="ignore"` allows non-setting env vars like `RAILWAY_DATABASE_URL`. The `async_database_url` property converts Railway's `postgresql://` URLs to `postgresql+asyncpg://` format.

### Routes
All in `app/main.py`. Routes use lazy imports for models and `async_session` inside the function body to avoid circular imports and ensure DB is initialized. All regret/team endpoints accept `?season_year=` query param (defaults to `settings.season_year`).

### Services (`app/services/`)
- `yahoo_service.py` — Yahoo Fantasy API wrapper. `get_league_by_key()` for multi-season access. `fetch_player_stats_weekly()` takes `list(int)` player IDs (library handles key building + batching). `fetch_matchups()` parses deeply nested scoreboard JSON.
- `lineup_optimizer.py` — Greedy algorithm filling QB→RB→WR→TE→FLEX→K→DEF slots with highest-scoring available players.
- `regret_engine.py` — Three calculator classes (`DraftRegretCalculator`, `WaiverRegretCalculator`, `StartSitRegretCalculator`) + `RegretEngine` orchestrator. All accept `season_year` and scope DB queries accordingly.

### Frontend (`app/frontend/`)
- `base.html` — Tailwind dark mode + HTMX + Inter font via CDN
- `index.html` — Single-page dashboard with season selector, team dropdown, summary cards, weekly timeline (bar chart with click-to-expand), and three regret pillar cards. All data loaded via JS `fetch()` calls to JSON API endpoints.
- `team_names.json` — Maps team keys to display names for both leagues

### Scripts (`scripts/`)
- `initialize_yahoo.py` — Main pipeline: Yahoo API → cache → store (per league/season)
- `calculate_regrets.py` — Compute regret metrics for all teams (per season)
- `initialize_data_v2.py` — Legacy pipeline (nfl_data_py, kept for reference)

## Database Tables

8 tables in `app/models/__init__.py` (all season_year-scoped):
- `league_config` — Scoring rules + roster requirements (JSON)
- `player_map` — yahoo_id ↔ gsis_id identity mapping, with position + season_year. Auto-increment PK (not yahoo_id).
- `nfl_game_logs` — Weekly fantasy points from Yahoo `total_points`. `raw_stats` JSON includes `position`. Indexed on (player_id, week) and season_year.
- `league_weekly_rosters` — JSON roster snapshots per team per week. `roster_snapshot.players[]` has player_id, name, position, eligible_positions, selected_position, is_starter.
- `league_draft_results` — Draft picks with round, overall_pick, player_id, season_year.
- `waiver_wire_availability` — Weekly ownership % and waiver status + season_year.
- `league_matchups` — Weekly matchup results: team_id, opponent_id, scores, is_win. Two rows per matchup (one per team).
- `regret_metrics` — Precomputed regret scores. `metric_type` is "draft", "waiver", or "start_sit". `data_payload` JSON contains narrative text, player names/points, and swap details.

## Deployment

- **Platform**: Railway (personal account, private deployment)
- **Build**: Multi-stage Dockerfile with `uv` for fast installs
- **Config**: `railway.toml` — health check on `/health`, 60s timeout
- **DB**: Railway PostgreSQL service, `DATABASE_URL` auto-injected
- **Start**: `sh -c 'uvicorn app.main:app --host 0.0.0.0 --port $PORT'`
- **URL**: `https://ff-regret-production.up.railway.app`
- **Data seeding**: Run `initialize_yahoo.py` locally with `DATABASE_URL` pointing to Railway Postgres
- **Schema changes**: Drop + recreate tables via `Base.metadata.drop_all` / `create_all` (no migrations tool)

## Environment Variables

| Variable | Local | Railway |
|----------|-------|---------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./ff_regret.db` | Auto-injected by PostgreSQL service |
| `RAILWAY_DATABASE_URL` | In `.env` for convenience | N/A |
| `YAHOO_CONSUMER_KEY` | `.env` | Manual |
| `YAHOO_CONSUMER_SECRET` | `.env` | Manual |
| `YAHOO_ACCESS_TOKEN` | `.env` | Manual |
| `YAHOO_REFRESH_TOKEN` | `.env` | Manual |
| `YAHOO_LEAGUE_ID` | `186782` | `186782` |
| `YAHOO_GAME_ID` | `nfl` | `nfl` |
| `SEASON_YEAR` | `2025` | `2025` |

## Code Style

- Python ≥3.11, <3.13
- Indentation: 4 spaces
- Line length: 100 (black + ruff)
- Formatter: `black`
- Linter: `ruff` (E, F, W, I, N, B, C4, UP)
- Type checker: `mypy` (strict mode)
- Git: conventional commits (`feat:`, `fix:`, `refactor:`, etc.)
- Comments: only when "why" isn't obvious

## Future Ideas

- **Matchup context**: Show "this cost you the matchup" when regret delta > margin of loss (data available in `league_matchups`)
- **Season narrative**: Auto-generated summary card ("Your season was defined by Week 7...")
- **Regret leaderboard**: Top 5 worst decisions across all pillars, sortable
- **Position breakdown**: Which positions cost you the most points
- **"What If" mode**: Show season record with optimal decisions
- **Cumulative trend**: Area chart of missed points over the season
