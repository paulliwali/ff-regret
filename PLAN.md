# PLAN.md: The Fantasy Football "Regret Engine"

## 1. Project Overview

An interactive web application for Yahoo Fantasy Football managers to visualize the "what-ifs" of their previous season. The app focuses on three "Pillars of Regret":

- Draft picks
- Waiver Wire misses
- Start/Sit blunders

**Scope**: Single league (my league) with multiple users. Each user selects their team to view their personalized regret analysis.

**Deployment Target**: Personal Railway account (private deployment for league members only)

## 2. Goals & Objectives

- **Primary Goal**: Provide a "snappy," high-performance UI for users to relive their season's worst decisions.
- **Data Accuracy**: Join Yahoo league data with verified NFL play-by-play/game-log data.
- **Portability**: Designed to be hosted on Railway with a minimal memory footprint (<512MB RAM).
- **Precomputation**: All regret metrics are precomputed for the league, serving individual users instantly.

## 3. Tech Stack

| Component    | Technology        | Reasoning                                                                                    |
| ------------ | ----------------- | -------------------------------------------------------------------------------------------- |
| Backend      | Python (FastAPI)  | Async performance; native support for your Data Science workflow.                            |
| API Wrapper  | yahoo-fantasy-api | Handles the complex Yahoo OAuth and nested JSON parsing.                                     |
| Data Engine  | Polars            | High-speed data manipulation with lower RAM usage than Pandas.                               |
| Primary Data | nfl_data_py       | The "Gold Standard" for historical NFL stats and player ID mapping.                          |
| Database     | PostgreSQL        | Persistent storage on Railway (personal account) to cache Yahoo data and NFL stats.          |
| Frontend     | HTMX + Tailwind   | Provides a "SPA-like" snappy feel without the overhead of a JS framework. Dark mode enabled. |

## 4. Database Schema

### `league_config`

- `scoring_config`: JSON blob of Yahoo's custom scoring rules
- `roster_requirements`: JSON blob of lineup slots (QB, RB, WR, TE, FLEX, etc.)
- `season_year`: 2025

### `player_map`

- `yahoo_id`: Primary key from Yahoo
- `gsis_id`: NFLverse ID (primary mapping)
- `full_name`: Fallback for fuzzy name matching
- `match_confidence`: 1.0 if ID match, <1.0 if name match

### `nfl_game_logs`

- `player_id` (gsis_id)
- `week`
- `season_year` (2025)
- `fantasy_points`: Calculated using league scoring config
- `status`: OUT, DOUBTFUL, QUESTIONABLE, etc.

### `league_weekly_rosters`

- `team_id`: Yahoo team ID
- `week`
- `season_year`
- `roster_snapshot`: JSON blob of that week's roster with starter/bench status (includes all mid-season trades and moves)

### `league_draft_results`

- `team_id`
- `overall_pick`
- `round`
- `player_id` (yahoo_id)
- `pick_timestamp`

### `waiver_wire_availability`

- `player_id` (yahoo_id)
- `week`
- `ownership_percentage`: 0-100
- `is_on_waivers`: boolean
- `last_drop_date`: timestamp

### `regret_metrics` (Precomputed for each team)

- `team_id`
- `metric_type`: 'draft', 'waiver', 'start_sit'
- `week` (null for draft, 1-17 for others)
- `regret_score`: Numerical regret magnitude
- `data_payload`: JSON blob with details (missed players, points left on table, etc.)

## 5. Implementation Phases

### Phase 1: The "Rosetta Stone" (Data Foundations) — DONE

**1.1 Initialize Railway Postgres (DONE)**

- All 7 tables created with proper indexes on Railway Postgres
- Lazy DB init pattern in `app/db/__init__.py` handles both SQLite (local) and Postgres (prod)

**1.2 Fetch NFL Data (DONE)**

- Used `nfl_data_py` to pull 2024 game logs for all players
- Imported player IDs and metadata
- Stored in `nfl_game_logs` (5,597 rows)

**1.3 Yahoo API Connection (DONE)**

- OAuth2 flow working via `yahoo_oauth` library with token file `app/oauth2.json`
- Tokens auto-refresh; `yahoo_oauth` handles expiry/renewal transparently
- League confirmed: "The Newer CFL" — 14 teams, game ID `461`, league ID `186782`
- Service layer: `app/services/yahoo_service.py` wraps `yahoo_fantasy_api`
- Connection test: `uv run python scripts/test_connection.py`

**1.4 Yahoo Data Fetch (DONE)**

- All Yahoo data fetched and stored: league config (3 rows), draft results (196 rows), weekly rosters (238 rows), waiver wire (12,308 rows)
- `scripts/initialize_data_v2.py` caches API responses in `.cache/` dir to avoid re-fetching
- Supports `--from-step` flag for resuming from any pipeline step
- `scripts/migrate_sqlite_to_postgres.py` migrates local SQLite → Railway Postgres directly

**1.5 Player ID Mapping Pipeline (DONE)**

- Primary: Match yahoo_id ↔ gsis_id using `nfl_data_py.import_ids()`
- Fallback: Fuzzy name matching via rapidfuzz (normalize names, remove suffixes, handle typos)
- 326 player mappings stored in `player_map` with confidence scores

**1.6 Calculate Fantasy Points (DONE)**

- League's custom scoring rules parsed from Yahoo config via `ScoringRulesParser`
- Fantasy points calculated for all game logs using league-specific multipliers
- Stored in `nfl_game_logs.fantasy_points`

### Phase 2: The "Regret Engine" (Precomputation) — DONE

**2.1 Draft Regret Algorithm**

- For each team, iterate through their draft picks
- For each pick, identify players drafted within ±3 picks
- Calculate delta: (missed_player_total_points - drafted_player_total_points)
- Keep top 3 highest delta misses per team
- Store in `regret_metrics`

**2.2 Waiver Regret Algorithm**

- For each week, for each team:
  - Identify players on their bench or available waivers (0% owned)
  - Filter out injured (OUT, IR, DOUBTFUL status)
  - Calculate potential points if they had started the best available player
  - Delta = (best_available_points - started_points)
- Keep top 3 waiver misses per week per team
- Store in `regret_metrics`

**2.3 Start/Sit Regret Algorithm**

- For each week, for each team:
  - Load their actual starters for that week (includes mid-season trades)
  - Using their full roster (starters + bench), calculate optimal lineup:
    - Use greedy selection: fill each slot with best available player by fantasy points
    - Respect position constraints (QB, RB, WR, TE, FLEX, etc.)
    - Respect bye weeks (filter out players on bye)
    - Respect injury statuses (filter OUT, IR, DOUBTFUL)
    - Maximize fantasy points
  - Delta = (optimal_points - actual_points)
- Store weekly regret scores in `regret_metrics`

**2.4 Optimization for Memory**

- Process one team at a time
- Stream weekly data instead of loading all weeks
- Use Polars lazy evaluation
- Store only regret metrics, not intermediate calculations

### Phase 3: The "Regret UI" (Frontend) — IN PROGRESS

**3.1 Team Selection**

- Simple dropdown to select user's team

**3.2 Dashboard Layout**

- Summary cards: Total regret points across all 3 pillars
- Weekly regret trend line
- **Primary visualization**: "The One That Got Away" spotlight cards (see Section 6)

**3.3 Pillar Deep-Dive Views**
All pillars use "The One That Got Away" narrative card format:

- Draft Regret: Top 3 draft picks with player comparison stories
- Waiver Regret: Week-by-week missed opportunity stories
- Start/Sit Regret: Weekly lineup decision stories

### Phase 4: Deployment & Testing — PARTIALLY DONE

**4.1 Railway Deployment (DONE)**

- Dockerfile: multi-stage build with `uv` for fast installs, Python 3.11-slim
- `railway.toml`: health check on `/health`, 60s timeout, restart on failure
- Railway Postgres provisioned, `DATABASE_URL` auto-injected
- Start command: `sh -c 'uvicorn app.main:app --host 0.0.0.0 --port $PORT'`
- Lazy DB init handles Railway's `postgresql://` → `postgresql+asyncpg://` conversion
- Live at: `https://ff-regret-production.up.railway.app`
- Data seeded via `scripts/migrate_sqlite_to_postgres.py` (SQLite → Railway Postgres)

**4.2 Data Validation (TODO)**

- Spot-check player ID mapping accuracy
- Validate fantasy point calculations vs Yahoo
- Cross-reference regret calculations manually

## 6. Primary Visualization: "The One That Got Away" Spotlight

**Core Concept**: Narrative-driven cards that tell the story of your worst decisions across all three regret pillars. Each card highlights one missed opportunity with context, impact, and visual flair.

### Card Structure (Dark Mode)

```
┌─────────────────────────────────────────────────────┐
│  WEEK 5  │  🚨 WAIVER MISS                          │
│  42.3 pts lost  │  RB - Saquon Barkley             │
├─────────────────────────────────────────────────────┤
│                                                     │
│  "You started Justin Jefferson (8.2 pts) when      │
│   Saquon Barkley (28.4 pts) sat on your bench"    │
│                                                     │
│  Started: Justin Jefferson   8.2 pts  🔴           │
│  Should have: Saquon Barkley  28.4 pts  🟢         │
│                                                     │
│  Delta: +20.2 pts                                  │
│  Status: Available on waivers (0% owned)          │
│  Matchup: You lost by 3.5 points                  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Draft Regret Spotlight Cards

**Format**: Top 3 worst draft decisions for the season

**Card Content**:

- Draft position: "Round 2, Pick 15"
- Your pick: Player name, position, total season points, team logo
- Should have picked: Player name, position, total season points, team logo
- Narrative: "With the 15th pick, you selected [Player A] who scored [X] points. [Player B], selected 2 picks later, scored [Y] points (+Z%)"
- Delta: Season-long point differential in bold red/green
- Context: Was this a reach? Sleeper bust? Injury-related?

**Visual Elements**:

- Player headshots (if available) or position icons
- Team colors/jersey numbers
- Season-long performance sparkline
- "Regret Factor" badge (e.g., "+156%" in red)
- Draft order visualization showing nearby picks

### Waiver Regret Spotlight Cards

**Format**: Week-by-week missed opportunities, sorted by impact

**Card Content**:

- Week number and matchup context
- Your actual starter: Name, position, points scored, injury status
- Missed opportunity: Name, position, points scored, waiver status
- Narrative: "Week 5: You started [Player A] (8.2 pts) when [Player B] (28.4 pts) sat on waivers"
- Delta: Weekly points left on table
- Context: Did this cost you the matchup? Playoff implications?

**Visual Elements**:

- Player comparison with big bold numbers
- Waiver status indicator (0% owned, 25% owned, etc.)
- Matchup result overlay (won/lost by X pts)
- Injury status badges
- Previous week ownership trend (small sparkline)

### Start/Sit Regret Spotlight Cards

**Format**: Weekly lineup decisions, grouped by severity of mistake

**Card Content**:

- Week number and matchup
- Your actual lineup: Grid of starters with points
- Optimal lineup: Grid showing should-have-started with "⬆️" badges
- Narrative: "Week 7: By benching [Player A] and starting [Player B], you left 24.5 points on the table"
- Delta: Total weekly optimization gap
- Context: Was this injury-related? Matchup-based decision?

**Visual Elements**:

- Two-column lineup comparison (Actual vs Optimal)
- Delta callouts for each position swap
- Position optimization score (e.g., "QB: Perfect ✅", "WR: -8.3 pts 🔴")
- Weekly trend arrow showing improvement/decline

### Dashboard Integration

**Hero Section**:

- "Season Story" summary card: "Your season was defined by Week 7, where you left 42 points on the bench. Your worst decision was drafting [Player A] instead of [Player B], costing you 156 total points."

**Timeline View**:

- Horizontal scrollable timeline of all 17 weeks
- Each week shows regret intensity (color: red/orange/green)
- Click to expand spotlight card for that week

**Regret Leaderboard**:

- Top 5 worst decisions across all pillars
- Each entry clickable for full spotlight card
- Sortable by: Total points lost, Percentage impact, Week

### Secondary Visualizations (Supporting)

- Weekly regret trend line (area chart showing cumulative missed points)
- Position regret breakdown (radar chart showing which positions cost you most)
- Regret intensity heatmap (calendar view with red/green coloring)

### Interactive Features

- Click any card to drill down into detailed player stats
- Toggle "What If" mode: Show how your season would have played out with optimal decisions
- Compare your regret vs league average (small badge on each card)
- Export/share individual spotlight cards (social media friendly)

## 7. Narrative Generation Logic

Precomputed in `regret_metrics.data_payload` JSON for each spotlight card:

### Draft Narrative Template

```python
{
  "narrative": "With the {pick_number} pick, you selected {drafted_player} who scored {drafted_points} points. {missed_player}, selected {pick_delta} picks later, scored {missed_points} points (+{percentage}%)",
  "impact": {
    "points_delta": float,
    "percentage_delta": float,
    "pick_delta": int,
    "severity": "high" | "medium" | "low"
  },
  "context": {
    "drafted_player_stats": {...},
    "missed_player_stats": {...},
    "nearby_picks": [...]
  }
}
```

### Waiver Narrative Template

```python
{
  "narrative": "Week {week}: You started {started_player} ({started_points} pts) when {missed_player} ({missed_points} pts) sat on waivers",
  "impact": {
    "points_delta": float,
    "matchup_delta": float,  # Would this have changed the result?
    "severity": "high" | "medium" | "low"
  },
  "context": {
    "waiver_status": "0% owned" | "25% owned" | "on waivers",
    "injury_status": "healthy" | "questionable" | "doubtful",
    "matchup_result": "lost by {points}",
    "season_impact": "cost playoff berth" | "cost home field" | "no impact"
  }
}
```

### Start/Sit Narrative Template

```python
{
  "narrative": "Week {week}: By benching {benched_player} and starting {started_player}, you left {points_delta} points on the table",
  "impact": {
    "total_delta": float,
    "position_breakdown": {...},
    "severity": "high" | "medium" | "low"
  },
  "context": {
    "actual_lineup": {...},
    "optimal_lineup": {...},
    "swaps": [
      {"position": "RB", "benched": "...", "started": "...", "delta": float}
    ],
    "matchup_result": "lost by {points}"
  }
}
```

### Narrative Enhancement

Precomputed narratives will be enhanced with:

- **Emotional tone**: "Brutal miss," "Costly blunder," "Solid decision" based on delta magnitude
- **Contextual relevance**: Mention playoff implications, division races, or streaks
- **Player-specific notes**: Rookie, breakout star, injury comeback (if known from NFL data)
- **League context**: How this decision compared to others in your league

## 8. Finalized Decisions

**Q1**: Start/Sit optimization - Simple greedy selection algorithm. Fill each slot with best available player by fantasy points while respecting position constraints, bye weeks, and injury statuses.

**Q2**: Mid-season trades - Track roster week-to-week. Weekly roster snapshots capture all trades, drops, and pickups throughout the season.

**Q3**: Visual style - Dark mode enabled for the entire application.

**Q4**: Primary visualization - "The One That Got Away" spotlight cards with narrative-driven storytelling across all three regret pillars.
