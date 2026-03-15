import logging
import os
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.config import settings
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fantasy Football Regret Engine",
    description="Visualize your fantasy football season's worst decisions",
    version="0.1.0",
)

templates = Jinja2Templates(directory="app/frontend")


@app.on_event("startup")
async def startup_event():
    logger.info("Starting Fantasy Football Regret Engine...")
    logger.info(f"PORT={os.environ.get('PORT', 'not set')}")
    logger.info(f"DATABASE_URL set: {bool(os.environ.get('DATABASE_URL'))}")
    try:
        from app.db import init_db
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        logger.info("App will start but DB features may not work")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/api/teams")
async def get_teams(season_year: int = None):
    """Get all teams in the league."""
    from app.models import LeagueWeeklyRoster
    from sqlalchemy import select, distinct

    year = season_year or settings.season_year
    from app.db import async_session
    async with async_session() as session:
        result = await session.execute(
            select(distinct(LeagueWeeklyRoster.team_id))
            .where(LeagueWeeklyRoster.season_year == year)
            .order_by(LeagueWeeklyRoster.team_id)
        )
        teams = result.scalars().all()

        return {"teams": teams}


@app.get("/api/teams/options", response_class=HTMLResponse)
async def get_teams_options(season_year: int = None):
    """Return team options as HTML for select population."""
    import json
    from pathlib import Path
    from app.models import LeagueWeeklyRoster
    from sqlalchemy import select, distinct

    from app.db import async_session

    year = season_year or settings.season_year

    # Load team names if available
    team_names_file = Path(__file__).parent / "team_names.json"
    team_names = {}
    if team_names_file.exists():
        team_names = json.loads(team_names_file.read_text())

    async with async_session() as session:
        result = await session.execute(
            select(distinct(LeagueWeeklyRoster.team_id))
            .where(LeagueWeeklyRoster.season_year == year)
            .order_by(LeagueWeeklyRoster.team_id)
        )
        teams = sorted(result.scalars().all())

    html = '<option value="">-- Select Your Team --</option>\n'
    for team in teams:
        name = team_names.get(team)
        if not name:
            team_num = team.split(".")[-1] if "." in team else team
            name = f"Team {team_num}"
        html += f'<option value="{team}">{name}</option>\n'
    return html


@app.get("/api/team/{team_id}/summary")
async def get_team_summary(team_id: str, season_year: int = None):
    """Get regret summary for a team, plus league-wide ranges and standings."""
    from app.models import RegretMetric, LeagueMatchup
    from sqlalchemy import select, func, Integer

    year = season_year or settings.season_year
    from app.db import async_session
    async with async_session() as session:
        score_filter = RegretMetric.regret_score > 0
        season_filter = RegretMetric.season_year == year

        # Total points lost across all types
        result = await session.execute(
            select(
                func.sum(RegretMetric.regret_score).label("total_points_lost"),
            )
            .where(RegretMetric.team_id == team_id)
            .where(score_filter)
            .where(season_filter)
        )
        all_summary = result.first()

        # League-wide ranges for points lost (all regret types, per-team)
        all_team_stats = (
            select(
                RegretMetric.team_id,
                func.sum(RegretMetric.regret_score).label("pts"),
            )
            .where(score_filter)
            .where(season_filter)
            .group_by(RegretMetric.team_id)
        ).subquery()

        league_result = await session.execute(
            select(
                func.min(all_team_stats.c.pts).label("min_points"),
                func.max(all_team_stats.c.pts).label("max_points"),
            )
        )
        league = league_result.first()

        # Total points scored: sum actual_points from start_sit data_payload
        startsit_result = await session.execute(
            select(RegretMetric.team_id, RegretMetric.data_payload)
            .where(RegretMetric.metric_type == "start_sit")
            .where(season_filter)
        )
        all_startsit = startsit_result.all()

        team_scored_map: dict[str, float] = {}
        for row_team_id, payload in all_startsit:
            pts = float(payload.get("actual_points", 0))
            team_scored_map[row_team_id] = team_scored_map.get(row_team_id, 0) + pts

        team_scored = team_scored_map.get(team_id, 0)
        scored_values = list(team_scored_map.values())
        scored_range = (min(scored_values), max(scored_values)) if scored_values else (0, 0)

        # Standings: use playoff results from team_standings.json,
        # fall back to regular season W-L
        import json
        from pathlib import Path
        standings_file = Path(__file__).parent / "team_standings.json"
        playoff_standings = {}
        if standings_file.exists():
            all_standings = json.loads(standings_file.read_text())
            playoff_standings = all_standings.get(str(year), {})

        # Get total teams count from matchups
        team_count_result = await session.execute(
            select(func.count(func.distinct(LeagueMatchup.team_id)))
            .where(LeagueMatchup.season_year == year)
        )
        total_teams = team_count_result.scalar() or 14

        if team_id in playoff_standings:
            team_finish = playoff_standings[team_id]
        else:
            # Fall back to regular season ranking
            matchup_result = await session.execute(
                select(
                    LeagueMatchup.team_id,
                    func.sum(func.cast(LeagueMatchup.is_win, Integer)).label("wins"),
                    func.sum(LeagueMatchup.team_score).label("total_pts"),
                )
                .where(LeagueMatchup.season_year == year)
                .group_by(LeagueMatchup.team_id)
            )
            standings_rows = matchup_result.all()
            standings = sorted(
                standings_rows,
                key=lambda r: (r.wins or 0, r.total_pts or 0),
                reverse=True,
            )
            team_finish = None
            for i, row in enumerate(standings):
                if row.team_id == team_id:
                    team_finish = i + 1
                    break

        return {
            "team_id": team_id,
            "total_points_lost": float(all_summary.total_points_lost or 0) if all_summary else 0,
            "total_scored": team_scored,
            "finish": team_finish,
            "total_teams": total_teams,
            "league_range": {
                "points_lost": [float(league.min_points or 0), float(league.max_points or 0)],
                "scored": [
                    float(scored_range[0] or 0) if scored_range else 0,
                    float(scored_range[1] or 0) if scored_range else 0,
                ],
            } if league else None,
        }


@app.get("/api/team/{team_id}/draft-regrets")
async def get_draft_regrets(team_id: str, season_year: int = None):
    """Get draft regrets for a team."""
    from app.models import RegretMetric
    from sqlalchemy import select

    year = season_year or settings.season_year
    from app.db import async_session
    async with async_session() as session:
        result = await session.execute(
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .where(RegretMetric.metric_type == "draft")
            .where(RegretMetric.season_year == year)
            .order_by(RegretMetric.regret_score.desc())
        )
        regrets = result.scalars().all()
        
        return {
            "draft_regrets": [
                {"regret_score": r.regret_score, "week": r.week, **r.data_payload}
                for r in regrets
            ]
        }


@app.get("/api/team/{team_id}/waiver-regrets")
async def get_waiver_regrets(team_id: str, week: int = None, season_year: int = None):
    """Get waiver regrets for a team, optionally filtered by week."""
    from app.models import RegretMetric
    from sqlalchemy import select

    year = season_year or settings.season_year
    from app.db import async_session
    async with async_session() as session:
        query = (
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .where(RegretMetric.metric_type == "waiver")
            .where(RegretMetric.season_year == year)
        )
        
        if week:
            query = query.where(RegretMetric.week == week)
        
        query = query.order_by(RegretMetric.week, RegretMetric.regret_score.desc())
        
        result = await session.execute(query)
        regrets = result.scalars().all()
        
        return {
            "waiver_regrets": [
                {"regret_score": r.regret_score, "week": r.week, **r.data_payload}
                for r in regrets
            ]
        }


@app.get("/api/team/{team_id}/drop-regrets")
async def get_drop_regrets(team_id: str, season_year: int = None):
    """Get drop regrets for a team — players you let go who balled out."""
    from app.models import RegretMetric
    from sqlalchemy import select

    year = season_year or settings.season_year
    from app.db import async_session
    async with async_session() as session:
        result = await session.execute(
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .where(RegretMetric.metric_type == "drop")
            .where(RegretMetric.season_year == year)
            .order_by(RegretMetric.regret_score.desc())
        )
        regrets = result.scalars().all()

        return {
            "drop_regrets": [
                {"regret_score": r.regret_score, "week": r.week, **r.data_payload}
                for r in regrets
            ]
        }


@app.get("/api/team/{team_id}/startsit-regrets")
async def get_startsit_regrets(team_id: str, week: int = None, season_year: int = None):
    """Get start/sit regrets for a team, optionally filtered by week."""
    from app.models import RegretMetric
    from sqlalchemy import select

    year = season_year or settings.season_year
    from app.db import async_session
    async with async_session() as session:
        query = (
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .where(RegretMetric.metric_type == "start_sit")
            .where(RegretMetric.season_year == year)
        )
        
        if week:
            query = query.where(RegretMetric.week == week)
        
        query = query.order_by(RegretMetric.week, RegretMetric.regret_score.desc())
        
        result = await session.execute(query)
        regrets = result.scalars().all()
        
        return {
            "startsit_regrets": [
                {"regret_score": r.regret_score, "week": r.week, **r.data_payload}
                for r in regrets
            ]
        }


@app.get("/api/team/{team_id}/all-regrets")
async def get_all_regrets(team_id: str, season_year: int = None):
    """Get all regrets for a team, sorted by impact."""
    from app.models import RegretMetric
    from sqlalchemy import select, case, literal_column

    year = season_year or settings.season_year
    from app.db import async_session
    async with async_session() as session:
        result = await session.execute(
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .where(RegretMetric.regret_score > 0)
            .where(RegretMetric.season_year == year)
            .order_by(RegretMetric.regret_score.desc())
            .limit(20)
        )
        regrets = result.scalars().all()
        
        return {
            "all_regrets": [
                {
                    "metric_type": r.metric_type,
                    "week": r.week,
                    "regret_score": r.regret_score,
                    **r.data_payload,
                }
                for r in regrets
            ]
        }


@app.get("/api/team/{team_id}/weekly-timeline")
async def get_weekly_timeline(team_id: str, season_year: int = None):
    """Get per-week regret summary with matchup context for timeline."""
    from app.models import RegretMetric, LeagueMatchup
    from sqlalchemy import select

    year = season_year or settings.season_year
    from app.db import async_session
    async with async_session() as session:
        # Fetch all weekly regrets (start_sit + waiver)
        result = await session.execute(
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .where(RegretMetric.week.isnot(None))
            .where(RegretMetric.season_year == year)
            .order_by(RegretMetric.week)
        )
        regrets = result.scalars().all()

        # Fetch matchups for this team
        result = await session.execute(
            select(LeagueMatchup)
            .where(LeagueMatchup.team_id == team_id)
            .where(LeagueMatchup.season_year == year)
            .order_by(LeagueMatchup.week)
        )
        matchups_by_week = {m.week: m for m in result.scalars().all()}

        # Group regrets by week
        weeks: dict[int, dict] = {}
        for r in regrets:
            wk = r.week
            if wk not in weeks:
                weeks[wk] = {"week": wk, "total_score": 0, "regrets": []}
            if r.regret_score > 0 and r.metric_type == "start_sit":
                weeks[wk]["total_score"] += r.regret_score
            weeks[wk]["regrets"].append({
                "metric_type": r.metric_type,
                "regret_score": r.regret_score,
                **r.data_payload,
            })

        # Build full 1-17 timeline with matchup context
        timeline = []
        cumulative_wins = 0
        cumulative_losses = 0
        for wk in range(1, 18):
            entry = weeks.get(wk, {"week": wk, "total_score": 0, "regrets": []})
            entry["week"] = wk

            matchup = matchups_by_week.get(wk)
            if matchup:
                actual_pts = matchup.team_score
                opp_pts = matchup.opponent_score
                is_win = matchup.is_win

                if is_win:
                    cumulative_wins += 1
                else:
                    cumulative_losses += 1

                # Matchup-aware color: would optimal lineup have changed outcome?
                startsit_delta = sum(
                    r["regret_score"] for r in entry["regrets"]
                    if r["metric_type"] == "start_sit" and r["regret_score"] > 0
                )
                optimal_pts = actual_pts + startsit_delta

                if is_win or startsit_delta == 0:
                    color = "green"
                elif optimal_pts > opp_pts:
                    color = "red"  # optimal would have won
                else:
                    color = "yellow"  # lost either way

                entry["matchup"] = {
                    "team_score": actual_pts,
                    "opponent_score": opp_pts,
                    "opponent_id": matchup.opponent_id,
                    "is_win": is_win,
                    "optimal_score": round(optimal_pts, 2),
                    "would_have_won": optimal_pts > opp_pts,
                    "color": color,
                }
                entry["record"] = f"{cumulative_wins}-{cumulative_losses}"
            else:
                entry["matchup"] = None
                entry["record"] = f"{cumulative_wins}-{cumulative_losses}"

            timeline.append(entry)

        max_score = max((w["total_score"] for w in timeline), default=1) or 1

        return {
            "timeline": timeline,
            "max_score": max_score,
        }


@app.get("/team/{team_id}")
async def team_page(team_id: str):
    """Team-specific regret dashboard."""
    return templates.TemplateResponse("team.html", {"request": {"team_id": team_id}})


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
