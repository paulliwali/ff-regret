import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import async_session
from app.models import PlayerMap, NflGameLog
from app.services.nfl_service import NFLDataService
from app.services.scoring_calculator import FantasyPointsCalculator, ScoringRulesParser
from app.config import settings
from sqlalchemy import select
import logging
import polars as pl

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_scoring_rules(session: AsyncSession) -> dict:
    from app.models import LeagueConfig
    result = await session.execute(select(LeagueConfig).order_by(LeagueConfig.created_at.desc()))
    config = result.first()
    if config:
        yahoo_config = config[0].scoring_config
        return ScoringRulesParser.parse_yahoo_scoring_config({"scoring_config": yahoo_config})
    return {}


async def main():
    logger.info("Starting NFL data fetch")
    
    async with async_session() as session:
        try:
            nfl_service = NFLDataService(season_year=settings.season_year)
            
            logger.info(f"Fetching NFL data for {settings.season_year} season")
            
            logger.info("Fetching player ID mappings")
            player_ids = nfl_service.fetch_player_ids()
            
            if len(player_ids) == 0:
                logger.warning("No player IDs fetched, continuing anyway")
            else:
                logger.info(f"Fetched {len(player_ids)} player ID mappings")
                
                logger.info("Clearing existing player mappings")
                from sqlalchemy import delete
                await session.execute(delete(PlayerMap))
                await session.commit()
                
                logger.info("Deduplicating player ID mappings")
                player_ids = player_ids.unique(subset=["gsis_id"], keep="first")
                logger.info(f"After deduplication: {len(player_ids)} unique players")
                
                logger.info("Storing player ID mappings")
                batch = []
                for row in player_ids.iter_rows(named=True):
                    yahoo_id = row.get("yahoo_id")
                    gsis_id = row.get("gsis_id")
                    full_name = row.get("name", "")
                    
                    if yahoo_id is None or (isinstance(yahoo_id, float) and yahoo_id != yahoo_id):
                        continue
                    
                    player_map = PlayerMap(
                        yahoo_id=str(yahoo_id) if yahoo_id else "",
                        gsis_id=str(gsis_id) if gsis_id else "",
                        full_name=full_name,
                        match_confidence=1.0,
                    )
                    batch.append(player_map)
                    if len(batch) >= 100:
                        session.add_all(batch)
                        await session.commit()
                        batch = []
                
                if batch:
                    session.add_all(batch)
                    await session.commit()
                
                logger.info(f"Player ID mappings stored")
            
            logger.info("Fetching NFL game logs")
            game_logs = nfl_service.fetch_weekly_game_logs()
            
            if len(game_logs) == 0:
                logger.warning("No game logs fetched")
            else:
                logger.info(f"Fetched {len(game_logs)} game logs")
                
                scoring_rules = await get_scoring_rules(session)
                logger.info(f"Using {len(scoring_rules)} scoring rules")
                
                calculator = FantasyPointsCalculator(scoring_rules)
                
                logger.info("Calculating fantasy points and storing game logs")
                batch_size = 100
                batch = []
                
                for i, row in enumerate(game_logs.iter_rows(named=True)):
                    fantasy_points = calculator.calculate_fantasy_points(row)
                    
                    game_log = NflGameLog(
                        player_id=row.get("player_id", ""),
                        week=row.get("week", 1),
                        season_year=settings.season_year,
                        fantasy_points=fantasy_points,
                        status=row.get("status", "ACTIVE"),
                        raw_stats=dict(row),
                    )
                    batch.append(game_log)
                    
                    if len(batch) >= batch_size:
                        session.add_all(batch)
                        await session.commit()
                        logger.info(f"Stored {i+1}/{len(game_logs)} game logs")
                        batch = []
                
                if batch:
                    session.add_all(batch)
                    await session.commit()
                    logger.info(f"Stored final batch, total: {len(game_logs)} game logs")
            
            logger.info("NFL data fetch complete!")
            
        except Exception as e:
            logger.error(f"Error during NFL data fetch: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
