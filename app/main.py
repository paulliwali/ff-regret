from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import async_session, init_db, get_db
from app.config import settings
import uvicorn

app = FastAPI(
    title="Fantasy Football Regret Engine",
    description="Visualize your fantasy football season's worst decisions",
    version="0.1.0",
)

templates = Jinja2Templates(directory="app/frontend")


@app.on_event("startup")
async def startup_event():
    await init_db()


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/api/teams")
async def get_teams():
    """Get all teams in the league."""
    from app.models import LeagueWeeklyRoster
    from sqlalchemy import select, func, distinct
    
    async with async_session() as session:
        result = await session.execute(
            select(distinct(LeagueWeeklyRoster.team_id))
            .where(LeagueWeeklyRoster.season_year == settings.season_year)
        )
        teams = result.scalars().all()
        
        return {"teams": teams}


@app.get("/api/team/{team_id}/summary")
async def get_team_summary(team_id: str):
    """Get regret summary for a team."""
    from app.models import RegretMetric
    from sqlalchemy import select, func, case, literal_column
    
    async with async_session() as session:
        result = await session.execute(
            select(
                func.count(RegretMetric.id).label("total_regrets"),
                func.sum(RegretMetric.regret_score).label("total_points_lost"),
                func.avg(RegretMetric.regret_score).label("avg_regret_per_mistake")
            )
            .where(RegretMetric.team_id == team_id)
        )
        summary = result.first()
        
        if summary:
            return {
                "team_id": team_id,
                "total_regrets": summary.total_regrets or 0,
                "total_points_lost": float(summary.total_points_lost or 0),
                "avg_regret_per_mistake": float(summary.avg_regret_per_mistake or 0)
            }
        
        return {"team_id": team_id, "total_regrets": 0, "total_points_lost": 0, "avg_regret_per_mistake": 0}


@app.get("/api/team/{team_id}/draft-regrets")
async def get_draft_regrets(team_id: str):
    """Get draft regrets for a team."""
    from app.models import RegretMetric
    from sqlalchemy import select
    
    async with async_session() as session:
        result = await session.execute(
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .where(RegretMetric.metric_type == "draft")
            .order_by(RegretMetric.regret_score.desc())
        )
        regrets = result.scalars().all()
        
        return {"draft_regrets": [r.data_payload for r in regrets]}


@app.get("/api/team/{team_id}/waiver-regrets")
async def get_waiver_regrets(team_id: str, week: int = None):
    """Get waiver regrets for a team, optionally filtered by week."""
    from app.models import RegretMetric
    from sqlalchemy import select
    
    async with async_session() as session:
        query = (
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .where(RegretMetric.metric_type == "waiver")
        )
        
        if week:
            query = query.where(RegretMetric.week == week)
        
        query = query.order_by(RegretMetric.week, RegretMetric.regret_score.desc())
        
        result = await session.execute(query)
        regrets = result.scalars().all()
        
        return {"waiver_regrets": [r.data_payload for r in regrets]}


@app.get("/api/team/{team_id}/startsit-regrets")
async def get_startsit_regrets(team_id: str, week: int = None):
    """Get start/sit regrets for a team, optionally filtered by week."""
    from app.models import RegretMetric
    from sqlalchemy import select
    
    async with async_session() as session:
        query = (
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .where(RegretMetric.metric_type == "start_sit")
        )
        
        if week:
            query = query.where(RegretMetric.week == week)
        
        query = query.order_by(RegretMetric.week, RegretMetric.regret_score.desc())
        
        result = await session.execute(query)
        regrets = result.scalars().all()
        
        return {"startsit_regrets": [r.data_payload for r in regrets]}


@app.get("/api/team/{team_id}/all-regrets")
async def get_all_regrets(team_id: str):
    """Get all regrets for a team, sorted by impact."""
    from app.models import RegretMetric
    from sqlalchemy import select, case, literal_column
    
    async with async_session() as session:
        result = await session.execute(
            select(RegretMetric)
            .where(RegretMetric.team_id == team_id)
            .order_by(RegretMetric.regret_score.desc())
            .limit(20)
        )
        regrets = result.scalars().all()
        
        return {"all_regrets": [r.data_payload for r in regrets]}


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
