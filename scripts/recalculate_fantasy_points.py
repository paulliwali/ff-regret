"""Recalculate all fantasy points from raw_stats using corrected scoring rules."""

import asyncio
import logging
from sqlalchemy import select
from app.db import async_session
from app.models import NflGameLog, LeagueConfig
from app.services.scoring_calculator import ScoringRulesParser, FantasyPointsCalculator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    async with async_session() as session:
        # Load scoring rules
        result = await session.execute(select(LeagueConfig).limit(1))
        config = result.scalar_one_or_none()
        if not config:
            logger.error("No league config found")
            return

        rules = ScoringRulesParser.parse_yahoo_scoring_config({
            "scoring_config": config.scoring_config
        })
        calculator = FantasyPointsCalculator(rules)

        # Load all game logs
        result = await session.execute(
            select(NflGameLog).where(NflGameLog.season_year == 2024)
        )
        logs = result.scalars().all()
        logger.info(f"Recalculating fantasy points for {len(logs)} game logs")

        updated = 0
        unchanged = 0
        no_stats = 0

        for log in logs:
            if not log.raw_stats:
                no_stats += 1
                continue

            new_points = calculator.calculate_fantasy_points(log.raw_stats)
            if new_points != log.fantasy_points:
                log.fantasy_points = new_points
                updated += 1
            else:
                unchanged += 1

        await session.commit()

        logger.info(f"Updated: {updated}")
        logger.info(f"Unchanged: {unchanged}")
        logger.info(f"No raw_stats: {no_stats}")
        logger.info("Done. Now re-run scripts/calculate_regrets.py to update regret metrics.")


if __name__ == "__main__":
    asyncio.run(main())
