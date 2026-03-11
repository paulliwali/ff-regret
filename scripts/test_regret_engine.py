"""Test regret engine with sample data."""

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import async_session
from app.models import LeagueDraftResult, LeagueWeeklyRoster, PlayerMap, NflGameLog, LeagueConfig
from app.services.regret_engine import RegretEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_draft_regret():
    """Test draft regret calculation."""
    logger.info("Testing Draft Regret Calculation")
    
    async with async_session() as session:
        # Get first team ID
        result = await session.execute(select(LeagueDraftResult.team_id).limit(1))
        team_id = result.scalar()
        
        if not team_id:
            logger.error("No teams found")
            return
        
        logger.info(f"Testing with team: {team_id}")
        
        # Get roster requirements
        result = await session.execute(select(LeagueConfig).limit(1))
        config = result.scalar_one_or_none()
        
        if not config:
            logger.error("No league config found")
            return
        
        roster_requirements = config.roster_requirements
        
        # Initialize regret engine
        engine = RegretEngine(session, roster_requirements)
        
        # Calculate draft regrets
        draft_regrets = await engine.draft_calculator.calculate_draft_regret(team_id)
        
        logger.info(f"Found {len(draft_regrets)} draft regrets")
        for i, regret in enumerate(draft_regrets):
            logger.info(f"\nRegret #{i+1}:")
            logger.info(f"  Pick: {regret['overall_pick']} (Round {regret['round']})")
            logger.info(f"  Points Delta: {regret['points_delta']:.1f}")
            logger.info(f"  Narrative: {engine.draft_calculator.generate_narrative(regret)}")


async def test_waiver_regret():
    """Test waiver regret calculation."""
    logger.info("\nTesting Waiver Regret Calculation")
    
    async with async_session() as session:
        # Get first team ID
        result = await session.execute(select(LeagueDraftResult.team_id).limit(1))
        team_id = result.scalar()
        
        logger.info(f"Testing with team: {team_id}")
        
        # Get roster requirements
        result = await session.execute(select(LeagueConfig).limit(1))
        config = result.scalar_one_or_none()
        
        if not config:
            logger.error("No league config found")
            return
        
        roster_requirements = config.roster_requirements
        
        # Initialize regret engine
        engine = RegretEngine(session, roster_requirements)
        
        # Calculate waiver regrets for week 1
        waiver_regrets = await engine.waiver_calculator.calculate_weekly_waiver_regret(team_id, 1)
        
        logger.info(f"Found {len(waiver_regrets)} waiver regrets for week 1")
        for i, regret in enumerate(waiver_regrets):
            logger.info(f"\nRegret #{i+1}:")
            logger.info(f"  Position: {regret['position']}")
            logger.info(f"  Starter: {regret['starter_name']} ({regret['starter_points']:.1f} pts)")
            logger.info(f"  Benched: {regret['benched_name']} ({regret['benched_points']:.1f} pts)")
            logger.info(f"  Delta: {regret['points_delta']:.1f}")
            logger.info(f"  Narrative: {engine.waiver_calculator.generate_narrative(regret, 1)}")


async def test_startsit_regret():
    """Test start/sit regret calculation."""
    logger.info("\nTesting Start/Sit Regret Calculation")
    
    async with async_session() as session:
        # Get first team ID
        result = await session.execute(select(LeagueDraftResult.team_id).limit(1))
        team_id = result.scalar()
        
        logger.info(f"Testing with team: {team_id}")
        
        # Get roster requirements
        result = await session.execute(select(LeagueConfig).limit(1))
        config = result.scalar_one_or_none()
        
        if not config:
            logger.error("No league config found")
            return
        
        roster_requirements = config.roster_requirements
        
        # Initialize regret engine
        engine = RegretEngine(session, roster_requirements)
        
        # Calculate start/sit regrets for week 1
        startsit_regret = await engine.startsit_calculator.calculate_weekly_startsit_regret(team_id, 1)
        
        if startsit_regret:
            logger.info(f"\nStart/Sit Results for Week 1:")
            logger.info(f"  Actual Points: {startsit_regret['actual_points']:.1f}")
            logger.info(f"  Optimal Points: {startsit_regret['optimal_points']:.1f}")
            logger.info(f"  Delta: {startsit_regret['points_delta']:.1f}")
            
            comparison = startsit_regret.get('comparison', {})
            if comparison:
                logger.info(f"  Improvement: {comparison.get('improvement_percentage', 0):.1f}%")
            
            logger.info(f"  Narrative: {engine.startsit_calculator.generate_narrative(startsit_regret, 1)}")


async def main():
    logger.info("Starting Regret Engine Tests")
    
    try:
        await test_draft_regret()
        await test_waiver_regret()
        await test_startsit_regret()
        
        logger.info("\n" + "=" * 60)
        logger.info("All Regret Engine Tests Passed!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error during testing: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())