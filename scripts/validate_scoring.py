"""Validate fantasy point calculations against raw stats and scoring rules.

Performs three checks:
1. Internal consistency: recalculate from raw_stats using scoring rules, compare to stored fantasy_points
2. Detailed breakdowns for well-known players (manual comparison vs Yahoo dashboard)
3. Player mapping audit: flag low-confidence or missing mappings
"""

import asyncio
import logging
from collections import defaultdict
from sqlalchemy import select, func
from app.db import async_session
from app.models import NflGameLog, PlayerMap, LeagueConfig
from app.services.scoring_calculator import ScoringRulesParser, FantasyPointsCalculator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SPOT_CHECK_PLAYERS = [
    "Patrick Mahomes",
    "Josh Allen",
    "Saquon Barkley",
    "Ja'Marr Chase",
    "Tyreek Hill",
    "Travis Kelce",
    "Derrick Henry",
    "Lamar Jackson",
    "Bijan Robinson",
    "CeeDee Lamb",
]


async def load_scoring_rules(session):
    """Load and parse league scoring rules."""
    result = await session.execute(select(LeagueConfig).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        raise RuntimeError("No league config found")

    rules = ScoringRulesParser.parse_yahoo_scoring_config({
        "scoring_config": config.scoring_config
    })
    return rules


async def check_internal_consistency(session, calculator):
    """Recalculate points from raw_stats for all game logs and compare to stored value."""
    result = await session.execute(
        select(NflGameLog).where(NflGameLog.season_year == 2024)
    )
    logs = result.scalars().all()

    mismatches = []
    total = 0
    exact = 0
    close = 0  # within 0.1

    for log in logs:
        if not log.raw_stats:
            continue
        total += 1
        recalculated = calculator.calculate_fantasy_points(log.raw_stats)
        stored = log.fantasy_points or 0
        diff = abs(recalculated - stored)

        if diff == 0:
            exact += 1
        elif diff < 0.1:
            close += 1
        else:
            mismatches.append({
                "player_id": log.player_id,
                "week": log.week,
                "stored": stored,
                "recalculated": recalculated,
                "diff": round(recalculated - stored, 2),
            })

    print("\n=== INTERNAL CONSISTENCY CHECK ===")
    print(f"Total game logs checked: {total}")
    print(f"Exact matches: {exact} ({exact/total*100:.1f}%)")
    print(f"Close matches (<0.1 diff): {close} ({close/total*100:.1f}%)")
    print(f"Mismatches: {len(mismatches)}")

    if mismatches:
        mismatches.sort(key=lambda x: abs(x["diff"]), reverse=True)
        print(f"\nTop 10 largest mismatches:")
        for m in mismatches[:10]:
            print(f"  player={m['player_id']} week={m['week']} "
                  f"stored={m['stored']:.2f} recalc={m['recalculated']:.2f} "
                  f"diff={m['diff']:+.2f}")

    return mismatches


async def spot_check_players(session, calculator, scoring_rules):
    """Print detailed scoring breakdowns for well-known players."""
    print("\n=== PLAYER SPOT-CHECK BREAKDOWNS ===")

    for name in SPOT_CHECK_PLAYERS:
        result = await session.execute(
            select(PlayerMap).where(PlayerMap.full_name.ilike(f"%{name}%"))
        )
        pm = result.scalar_one_or_none()
        if not pm:
            print(f"\n{name}: NOT FOUND in player_map")
            continue

        result = await session.execute(
            select(NflGameLog)
            .where(NflGameLog.player_id == pm.gsis_id)
            .where(NflGameLog.season_year == 2024)
            .order_by(NflGameLog.week)
        )
        logs = result.scalars().all()

        if not logs:
            print(f"\n{name} ({pm.gsis_id}): No game logs found")
            continue

        season_stored = sum(log.fantasy_points or 0 for log in logs)
        season_recalc = sum(
            calculator.calculate_fantasy_points(log.raw_stats)
            for log in logs if log.raw_stats
        )

        pos = logs[0].raw_stats.get("position", "?") if logs[0].raw_stats else "?"
        print(f"\n{name} ({pos}) — yahoo_id={pm.yahoo_id} gsis_id={pm.gsis_id} "
              f"confidence={pm.match_confidence}")
        print(f"  Season total: stored={season_stored:.1f}  recalc={season_recalc:.1f}  "
              f"diff={season_recalc - season_stored:+.1f}")
        print(f"  Games: {len(logs)}")

        # Detailed breakdown for week 1
        log = logs[0]
        if log.raw_stats:
            print(f"  Week {log.week} breakdown (stored={log.fantasy_points:.2f}):")
            breakdown_total = 0.0
            for stat, multiplier in sorted(scoring_rules.items()):
                value = calculator._get_stat_value(log.raw_stats, stat)
                if value and value != 0:
                    pts = float(value) * multiplier
                    breakdown_total += pts
                    print(f"    {stat}: {value} x {multiplier} = {pts:.2f}")
            print(f"    TOTAL: {breakdown_total:.2f}")

        # nfl_data_py comparison
        if log.raw_stats:
            nfl_std = log.raw_stats.get("fantasy_points", 0)
            nfl_ppr = log.raw_stats.get("fantasy_points_ppr", 0)
            print(f"  nfl_data_py week {log.week}: std={nfl_std:.1f} ppr={nfl_ppr:.1f} "
                  f"ours={log.fantasy_points:.1f}")


async def audit_player_mappings(session):
    """Check player mapping quality."""
    print("\n=== PLAYER MAPPING AUDIT ===")

    result = await session.execute(select(PlayerMap))
    maps = result.scalars().all()

    total = len(maps)
    by_confidence = defaultdict(int)
    low_confidence = []
    no_gsis = []

    for pm in maps:
        conf = pm.match_confidence or 0
        if conf == 1.0:
            by_confidence["exact (1.0)"] += 1
        elif conf >= 0.9:
            by_confidence["high (>=0.9)"] += 1
        elif conf >= 0.8:
            by_confidence["medium (>=0.8)"] += 1
        else:
            by_confidence["low (<0.8)"] += 1
            low_confidence.append(pm)

        if not pm.gsis_id:
            no_gsis.append(pm)

    print(f"Total player mappings: {total}")
    for bucket, count in sorted(by_confidence.items()):
        print(f"  {bucket}: {count}")

    if no_gsis:
        print(f"\nPlayers with NO gsis_id ({len(no_gsis)}):")
        for pm in no_gsis[:10]:
            print(f"  yahoo_id={pm.yahoo_id} name={pm.full_name}")

    if low_confidence:
        print(f"\nLow confidence mappings ({len(low_confidence)}):")
        for pm in low_confidence[:10]:
            print(f"  yahoo_id={pm.yahoo_id} name={pm.full_name} "
                  f"gsis={pm.gsis_id} conf={pm.match_confidence}")

    # Check for players in game logs with no mapping
    result = await session.execute(
        select(NflGameLog.player_id).distinct()
    )
    all_gsis_ids = set(r[0] for r in result.all())
    mapped_gsis_ids = set(pm.gsis_id for pm in maps if pm.gsis_id)
    unmapped_in_logs = all_gsis_ids - mapped_gsis_ids

    print(f"\nNFL game log players: {len(all_gsis_ids)}")
    print(f"Mapped to Yahoo: {len(mapped_gsis_ids & all_gsis_ids)}")
    print(f"Unmapped (in game logs but no Yahoo mapping): {len(unmapped_in_logs)}")


async def main():
    async with async_session() as session:
        scoring_rules = await load_scoring_rules(session)
        calculator = FantasyPointsCalculator(scoring_rules)

        print(f"Loaded {len(scoring_rules)} scoring rules:")
        for stat, mult in sorted(scoring_rules.items()):
            if mult != 0:
                print(f"  {stat}: {mult}")

        await check_internal_consistency(session, calculator)
        await spot_check_players(session, calculator, scoring_rules)
        await audit_player_mappings(session)


if __name__ == "__main__":
    asyncio.run(main())
