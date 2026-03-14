"""Calculate and store regret metrics for all teams."""

import argparse
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.db import async_session
from app.models import LeagueConfig, LeagueDraftResult, RegretMetric
from app.services.regret_engine import RegretEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def store_regret_metrics(
    session: AsyncSession,
    team_id: str,
    metric_type: str,
    week: int,
    season_year: int,
    regret_score: float,
    data_payload: dict,
):
    """Store a regret metric in the database."""
    metric = RegretMetric(
        team_id=team_id,
        metric_type=metric_type,
        week=week,
        season_year=season_year,
        regret_score=regret_score,
        data_payload=data_payload,
    )
    session.add(metric)
    await session.commit()


async def calculate_and_store_team_regrets(
    session: AsyncSession, team_id: str, season_year: int
):
    """Calculate and store all regret metrics for a single team."""
    logger.info(f"Processing team {team_id}")

    # Get roster requirements for this season
    result = await session.execute(
        select(LeagueConfig).where(LeagueConfig.season_year == season_year).limit(1)
    )
    config = result.scalar_one_or_none()

    if not config:
        logger.error(f"No league config found for season {season_year}")
        return

    roster_requirements = config.roster_requirements

    engine = RegretEngine(session, roster_requirements, season_year)
    all_regrets = await engine.calculate_all_regrets(team_id)

    # Store draft regrets
    for i, draft_regret in enumerate(all_regrets.get("draft_regrets", [])):
        narrative = await engine.draft_calculator.generate_narrative(draft_regret)
        await store_regret_metrics(
            session=session,
            team_id=team_id,
            metric_type="draft",
            week=None,
            season_year=season_year,
            regret_score=draft_regret["points_delta"],
            data_payload={
                "rank": i + 1,
                "overall_pick": draft_regret["overall_pick"],
                "round": draft_regret["round"],
                "drafted_player_id": draft_regret["drafted_player_id"],
                "drafted_player_name": draft_regret["drafted_player_name"],
                "drafted_player_points": draft_regret["drafted_player_points"],
                "drafted_position": draft_regret.get("drafted_position", ""),
                "missed_player_id": draft_regret["missed_player_id"],
                "missed_player_name": draft_regret["missed_player_name"],
                "missed_player_points": draft_regret["missed_player_points"],
                "narrative": narrative,
            },
        )
        logger.info(
            f"  Stored draft regret #{i+1}: {draft_regret['points_delta']:.1f} points"
        )

    # Store waiver regrets
    for i, waiver_regret in enumerate(all_regrets.get("waiver_regrets", [])):
        await store_regret_metrics(
            session=session,
            team_id=team_id,
            metric_type="waiver",
            week=waiver_regret["week"],
            season_year=season_year,
            regret_score=waiver_regret["points_delta"],
            data_payload={
                "rank": i + 1,
                **waiver_regret,
                "narrative": engine.waiver_calculator.generate_narrative(waiver_regret),
            },
        )
        logger.info(
            f"  Stored waiver regret #{i+1}: {waiver_regret['fa_name']} "
            f"({waiver_regret['points_delta']:.1f} pts ROS)"
        )

    # Store weekly start/sit regrets
    weekly_regrets = all_regrets.get("weekly_regrets", {})
    for week, week_data in weekly_regrets.items():
        startsit_data = week_data.get("startsit_regret", {})
        if startsit_data and startsit_data.get("points_delta", 0) > 0:
            swaps = startsit_data.get("swaps", [])
            await store_regret_metrics(
                session=session,
                team_id=team_id,
                metric_type="start_sit",
                week=week,
                season_year=season_year,
                regret_score=startsit_data["points_delta"],
                data_payload={
                    "actual_points": startsit_data["actual_points"],
                    "optimal_points": startsit_data["optimal_points"],
                    "swaps": swaps,
                    "narrative": engine.startsit_calculator.generate_narrative(
                        startsit_data, week
                    ),
                },
            )
            logger.info(
                f"  Stored week {week} start/sit: "
                f"{startsit_data['points_delta']:.1f} points"
            )


async def main():
    parser = argparse.ArgumentParser(description="Calculate regret metrics")
    parser.add_argument(
        "--season-year", type=int, default=2025,
        help="Season year to calculate regrets for (default: 2025)",
    )
    args = parser.parse_args()

    season_year = args.season_year
    logger.info(f"Starting regret metrics calculation for {season_year}")

    async with async_session() as session:
        try:
            # Clear existing regret metrics for this season only
            await session.execute(
                delete(RegretMetric).where(RegretMetric.season_year == season_year)
            )
            await session.commit()
            logger.info(f"Cleared existing regret metrics for {season_year}")

            # Get all unique team IDs from draft results for this season
            result = await session.execute(
                select(LeagueDraftResult.team_id)
                .where(LeagueDraftResult.season_year == season_year)
                .distinct()
            )
            team_ids = result.scalars().all()

            logger.info(f"Found {len(team_ids)} teams to process")

            for team_id in team_ids:
                await calculate_and_store_team_regrets(session, team_id, season_year)

            logger.info(f"Regret metrics calculation complete for {season_year}!")

        except Exception as e:
            logger.error(f"Error during regret calculation: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
