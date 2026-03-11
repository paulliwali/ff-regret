"""Re-import NFL game logs to fix player data."""

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.db import async_session, init_db
from app.services.nfl_service import NFLDataService
from app.services.scoring_calculator import ScoringRulesParser, FantasyPointsCalculator
from app.models import LeagueConfig
import logging
import polars as pl

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def clear_nfl_game_logs(session: AsyncSession):
    """Clear existing NFL game logs."""
    from app.models import NflGameLog
    
    logger.info("Clearing existing NFL game logs...")
    await session.execute(delete(NflGameLog))
    await session.commit()
    logger.info("Cleared NFL game logs")


async def store_nfl_game_logs(session: AsyncSession, game_logs: pl.DataFrame, scoring_calculator: FantasyPointsCalculator):
    """Store NFL game logs with fantasy points calculated using league scoring rules."""
    logger.info(f"Storing {len(game_logs)} NFL game logs")
    
    # Process in batches to avoid memory issues
    batch_size = 1000
    from app.models import NflGameLog
    
    for i in range(0, len(game_logs), batch_size):
        batch = game_logs[i:i+batch_size]
        
        for row in batch.iter_rows(named=True):
            player_id = row.get('player_id')
            week = row.get('week')
            season_year = row.get('season')
            
            # Calculate fantasy points using league scoring rules
            fantasy_points = scoring_calculator.calculate_fantasy_points(row)
            
            game_log = NflGameLog(
                player_id=player_id,
                week=week,
                season_year=season_year,
                fantasy_points=fantasy_points,
                status=row.get('status'),
                raw_stats=row
            )
            session.add(game_log)
        
        await session.commit()
        logger.info(f"Processed batch {i//batch_size + 1}/{(len(game_logs) // batch_size) + 1}")


async def main():
    logger.info("Starting NFL game logs re-import")
    await init_db()
    
    async with async_session() as session:
        # Get league scoring config
        result = await session.execute(select(LeagueConfig).limit(1))
        config = result.scalar_one_or_none()
        
        if not config:
            logger.error("No league config found")
            return
        
        # Parse Yahoo scoring config
        scoring_rules = ScoringRulesParser.parse_yahoo_scoring_config({
            "stat_modifiers": config.scoring_config
        })
        logger.info(f"Parsed {len(scoring_rules)} scoring rules")
        
        # Create fantasy points calculator
        scoring_calculator = FantasyPointsCalculator(scoring_rules)
        
        # Fetch NFL game logs
        nfl_service = NFLDataService(season_year=2024)
        game_logs = nfl_service.fetch_weekly_game_logs()
        
        if len(game_logs) == 0:
            logger.error("No NFL game logs to store")
            return
        
        # Clear existing logs
        await clear_nfl_game_logs(session)
        
        # Store new logs
        await store_nfl_game_logs(session, game_logs, scoring_calculator)
        
        logger.info("NFL game logs re-import complete!")


if __name__ == "__main__":
    asyncio.run(main())
