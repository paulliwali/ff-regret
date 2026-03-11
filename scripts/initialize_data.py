import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import async_session, init_db
from app.models import LeagueConfig, PlayerMap, NflGameLog, LeagueWeeklyRoster, LeagueDraftResult, WaiverWireAvailability
from app.services.yahoo_service import YahooFantasyService
from app.services.nfl_service import NFLDataService
from app.config import settings
import polars as pl
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def store_league_config(session: AsyncSession, config: dict):
    logger.info("Storing league configuration")
    league_config = LeagueConfig(
        scoring_config=config.get("scoring_config", {}),
        roster_requirements=config.get("roster_requirements", {}),
        season_year=settings.season_year,
    )
    session.add(league_config)
    await session.commit()


async def store_draft_results(session: AsyncSession, draft_results: list):
    logger.info(f"Storing {len(draft_results)} draft results")
    for result in draft_results:
        draft_result = LeagueDraftResult(
            team_id=result["team_id"],
            overall_pick=result["overall_pick"],
            round=result["round"],
            player_id=result["player_id"],
            pick_timestamp=result.get("pick_timestamp"),
        )
        session.add(draft_result)
    await session.commit()


async def store_weekly_rosters(session: AsyncSession, weekly_rosters: dict):
    logger.info("Storing weekly rosters")
    for week, rosters in weekly_rosters.items():
        for team_id, players in rosters.items():
            roster = LeagueWeeklyRoster(
                team_id=team_id,
                week=week,
                season_year=settings.season_year,
                roster_snapshot={"players": players},
            )
            session.add(roster)
    await session.commit()


async def store_waiver_wire_data(session: AsyncSession, waiver_data: dict):
    logger.info("Storing waiver wire data")
    for week, players in waiver_data.items():
        for player_data in players:
            availability = WaiverWireAvailability(
                player_id=player_data["player_id"],
                week=player_data["week"],
                ownership_percentage=player_data["ownership_percentage"],
                is_on_waivers=player_data["is_on_waivers"],
            )
            session.add(availability)
    await session.commit()


async def store_player_maps(session: AsyncSession, player_ids: pl.DataFrame):
    logger.info(f"Storing {len(player_ids)} player ID mappings")
    
    for row in player_ids.iter_rows(named=True):
        player_map = PlayerMap(
            yahoo_id=row.get("yahoo_id", ""),
            gsis_id=row.get("gsis_id", ""),
            full_name=row.get("full_name", ""),
            match_confidence=1.0,
        )
        session.add(player_map)
    
    await session.commit()


async def store_nfl_game_logs(session: AsyncSession, game_logs: pl.DataFrame, scoring_rules: dict):
    logger.info(f"Storing {len(game_logs)} NFL game logs")
    
    nfl_service = NFLDataService()
    
    for row in game_logs.iter_rows(named=True):
        fantasy_points = nfl_service._calculate_fantasy_points(row, scoring_rules)
        
        game_log = NflGameLog(
            player_id=row.get("gsis_id", ""),
            week=row.get("week", 1),
            season_year=settings.season_year,
            fantasy_points=fantasy_points,
            status=row.get("status", "ACTIVE"),
            raw_stats=row,
        )
        session.add(game_log)
    
    await session.commit()


async def main():
    logger.info("Starting data initialization")
    await init_db()
    
    async with async_session() as session:
        try:
            yahoo_service = YahooFantasyService()
            
            logger.info("Fetching Yahoo data")
            league_config = yahoo_service.fetch_league_config()
            draft_results = yahoo_service.fetch_draft_results()
            weekly_rosters = yahoo_service.fetch_all_weekly_rosters()
            waiver_data = yahoo_service.fetch_all_waiver_wire_data()
            
            logger.info("Storing Yahoo data to database")
            await store_league_config(session, league_config)
            await store_draft_results(session, draft_results)
            await store_weekly_rosters(session, weekly_rosters)
            await store_waiver_wire_data(session, waiver_data)
            
            logger.info("Fetching NFL data")
            nfl_service = NFLDataService()
            game_logs = nfl_service.fetch_weekly_game_logs()
            player_ids = nfl_service.fetch_player_ids()
            
            if not player_ids.empty:
                logger.info("Storing player ID mappings")
                await store_player_maps(session, player_ids)
            else:
                logger.warning("No player IDs to store")
            
            if not game_logs.empty:
                logger.info("Storing NFL game logs")
                scoring_rules = league_config.get("scoring_config", {})
                await store_nfl_game_logs(session, game_logs, scoring_rules)
            else:
                logger.warning("No game logs to store")
            
            logger.info("Data initialization complete!")
            
        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
