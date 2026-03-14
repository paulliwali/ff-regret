"""Initialize FF Regret data using Yahoo Fantasy API as the sole data source.

Usage:
    # 2024 season
    uv run python scripts/initialize_yahoo.py --league-key 449.l.776116 --season-year 2024

    # 2025 season
    uv run python scripts/initialize_yahoo.py --league-key 461.l.186782 --season-year 2025
"""

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session, init_db
from app.models import (
    LeagueConfig,
    LeagueDraftResult,
    LeagueMatchup,
    LeagueWeeklyRoster,
    NflGameLog,
    PlayerMap,
    WaiverWireAvailability,
)
from app.services.yahoo_service import YahooFantasyService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Cache helpers ---

def _cache_dir(season_year: int) -> Path:
    base = Path(__file__).parent.parent / ".cache" / str(season_year)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _save_cache(season_year: int, name: str, data):
    path = _cache_dir(season_year) / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f)
    logger.info(f"Cached {name} -> {path}")


def _load_cache(season_year: int, name: str):
    path = _cache_dir(season_year) / f"{name}.json"
    if path.exists():
        logger.info(f"Loading cached {name} from {path}")
        with open(path, "r") as f:
            return json.load(f)
    return None


# --- Fetch from Yahoo ---

def fetch_yahoo_league_data(
    yahoo: YahooFantasyService, league_key: str, season_year: int
) -> dict:
    """Fetch league config, draft, rosters, waivers from Yahoo."""
    lg = yahoo.get_league_by_key(league_key)
    end_week = lg.end_week()
    logger.info(f"League {league_key}, end_week={end_week}")

    # League config
    league_config = _load_cache(season_year, "league_config")
    if league_config is None:
        logger.info("Fetching league config")
        settings_data = lg.settings()
        league_config = {
            "scoring_config": {
                "stat_modifiers": settings_data.get("stat_modifiers", {}),
                "stat_categories": lg.stat_categories(),
                "uses_fractional_points": settings_data.get(
                    "uses_fractional_points", "0"
                ) == "1",
                "uses_negative_points": settings_data.get(
                    "uses_negative_points", "0"
                ) == "1",
            },
            "roster_requirements": settings_data.get("roster_positions", {}),
        }
        _save_cache(season_year, "league_config", league_config)

    # Draft results
    draft_results = _load_cache(season_year, "draft_results")
    if draft_results is None:
        logger.info("Fetching draft results")
        raw_draft = lg.draft_results()
        draft_results = []
        for result in raw_draft:
            draft_results.append({
                "team_id": result["team_key"],
                "overall_pick": result.get("pick", 0),
                "round": result["round"],
                "player_id": result["player_id"],
                "pick_timestamp": result.get("timestamp"),
            })
        _save_cache(season_year, "draft_results", draft_results)

    # Weekly rosters
    weekly_rosters = _load_cache(season_year, "weekly_rosters")
    if weekly_rosters is None:
        logger.info("Fetching weekly rosters")
        teams = lg.teams()
        weekly_rosters = {}
        for week in range(1, end_week + 1):
            logger.info(f"  Rosters week {week}/{end_week}")
            week_rosters = {}
            for team_key in teams:
                roster_data = lg.to_team(team_key).roster(week=week)
                players = []
                for player in roster_data:
                    players.append({
                        "player_id": player["player_id"],
                        "name": player["name"],
                        "position": player.get("eligible_positions", ["UNK"])[0],
                        "eligible_positions": player.get(
                            "eligible_positions", ["UNK"]
                        ),
                        "selected_position": player.get("selected_position", "BN"),
                        "is_starter": player.get("selected_position", "BN") != "BN",
                    })
                week_rosters[team_key] = players
            weekly_rosters[str(week)] = week_rosters
        _save_cache(season_year, "weekly_rosters", weekly_rosters)

    # Waiver data
    waiver_data = _load_cache(season_year, "waiver_data")
    if waiver_data is None:
        logger.info("Fetching waiver wire data")
        waiver_data = {}
        for week in range(1, end_week + 1):
            logger.info(f"  Waivers week {week}/{end_week}")
            waivers = lg.waivers()
            week_waivers = []
            for player in waivers:
                week_waivers.append({
                    "player_id": player["player_id"],
                    "name": player["name"],
                    "week": week,
                    "ownership_percentage": player.get("percent_owned", 0),
                    "is_on_waivers": player.get("status", "") == "W",
                })
            waiver_data[str(week)] = week_waivers
        _save_cache(season_year, "waiver_data", waiver_data)

    return {
        "league_config": league_config,
        "draft_results": draft_results,
        "weekly_rosters": weekly_rosters,
        "waiver_data": waiver_data,
        "end_week": end_week,
    }


def collect_all_players(yahoo_data: dict) -> Dict[str, Dict[str, str]]:
    """Collect all unique players with name + position from Yahoo data."""
    players: Dict[str, Dict[str, str]] = {}

    for result in yahoo_data["draft_results"]:
        pid = str(result["player_id"])
        if pid not in players:
            players[pid] = {"name": "", "position": ""}

    for week, rosters in yahoo_data["weekly_rosters"].items():
        for team_id, player_list in rosters.items():
            for player in player_list:
                pid = str(player.get("player_id", ""))
                if not pid:
                    continue
                if pid not in players:
                    players[pid] = {
                        "name": player.get("name", ""),
                        "position": player.get("position", ""),
                    }
                else:
                    if not players[pid]["name"]:
                        players[pid]["name"] = player.get("name", "")
                    if not players[pid]["position"]:
                        players[pid]["position"] = player.get("position", "")

    for week, player_list in yahoo_data["waiver_data"].items():
        for player in player_list:
            pid = str(player.get("player_id", ""))
            if pid and pid not in players:
                players[pid] = {
                    "name": player.get("name", ""),
                    "position": "",
                }

    logger.info(f"Collected {len(players)} unique players")
    return players


def fetch_player_stats(
    yahoo: YahooFantasyService,
    league_key: str,
    season_year: int,
    player_ids: List[str],
    end_week: int,
) -> Dict[int, List[Dict[str, Any]]]:
    """Fetch weekly player stats from Yahoo, week by week."""
    lg = yahoo.get_league_by_key(league_key)

    # player_stats() expects list(int) — it handles key building + batching
    numeric_ids = [int(pid) for pid in player_ids]

    all_stats: Dict[int, List[Dict[str, Any]]] = {}

    for week in range(1, end_week + 1):
        cached = _load_cache(season_year, f"player_stats_week_{week}")
        if cached is not None:
            all_stats[week] = cached
            continue

        logger.info(f"Fetching player stats week {week}/{end_week}")
        week_stats = yahoo.fetch_player_stats_weekly(lg, numeric_ids, week)

        _save_cache(season_year, f"player_stats_week_{week}", week_stats)
        all_stats[week] = week_stats
        time.sleep(1)

    return all_stats


def fetch_matchups(
    yahoo: YahooFantasyService,
    league_key: str,
    season_year: int,
    end_week: int,
) -> Dict[int, List[Dict[str, Any]]]:
    """Fetch matchup results from Yahoo, week by week."""
    lg = yahoo.get_league_by_key(league_key)
    all_matchups: Dict[int, List[Dict[str, Any]]] = {}

    for week in range(1, end_week + 1):
        cached = _load_cache(season_year, f"matchups_week_{week}")
        if cached is not None:
            all_matchups[week] = cached
            continue

        logger.info(f"Fetching matchups week {week}/{end_week}")
        matchups = yahoo.fetch_matchups(lg, week)
        _save_cache(season_year, f"matchups_week_{week}", matchups)
        all_matchups[week] = matchups
        time.sleep(1)

    return all_matchups


# --- Store to database (season-scoped deletes) ---

async def store_league_config(session: AsyncSession, config: dict, season_year: int):
    await session.execute(
        delete(LeagueConfig).where(LeagueConfig.season_year == season_year)
    )
    session.add(LeagueConfig(
        scoring_config=config.get("scoring_config", {}),
        roster_requirements=config.get("roster_requirements", {}),
        season_year=season_year,
    ))
    await session.commit()
    logger.info(f"Stored league config for {season_year}")


async def store_draft_results(
    session: AsyncSession, draft_results: list, season_year: int
):
    await session.execute(
        delete(LeagueDraftResult).where(LeagueDraftResult.season_year == season_year)
    )
    for result in draft_results:
        session.add(LeagueDraftResult(
            team_id=str(result["team_id"]),
            overall_pick=result["overall_pick"],
            round=result["round"],
            player_id=str(result["player_id"]),
            season_year=season_year,
            pick_timestamp=result.get("pick_timestamp"),
        ))
    await session.commit()
    logger.info(f"Stored {len(draft_results)} draft results for {season_year}")


async def store_weekly_rosters(
    session: AsyncSession, weekly_rosters: dict, season_year: int
):
    await session.execute(
        delete(LeagueWeeklyRoster).where(
            LeagueWeeklyRoster.season_year == season_year
        )
    )
    count = 0
    for week, rosters in weekly_rosters.items():
        for team_id, players in rosters.items():
            session.add(LeagueWeeklyRoster(
                team_id=str(team_id),
                week=int(week),
                season_year=season_year,
                roster_snapshot={"players": players},
            ))
            count += 1
    await session.commit()
    logger.info(f"Stored {count} roster snapshots for {season_year}")


async def store_waiver_data(
    session: AsyncSession, waiver_data: dict, season_year: int
):
    await session.execute(
        delete(WaiverWireAvailability).where(
            WaiverWireAvailability.season_year == season_year
        )
    )
    count = 0
    for week, players in waiver_data.items():
        for p in players:
            session.add(WaiverWireAvailability(
                player_id=str(p["player_id"]),
                week=int(p["week"]),
                season_year=season_year,
                ownership_percentage=p["ownership_percentage"],
                is_on_waivers=p["is_on_waivers"],
            ))
            count += 1
    await session.commit()
    logger.info(f"Stored {count} waiver records for {season_year}")


async def store_player_maps(
    session: AsyncSession,
    all_players: Dict[str, Dict[str, str]],
    season_year: int,
):
    """Identity mapping: yahoo_id = gsis_id since Yahoo is the sole source."""
    await session.execute(
        delete(PlayerMap).where(PlayerMap.season_year == season_year)
    )
    for yahoo_id, info in all_players.items():
        session.add(PlayerMap(
            yahoo_id=str(yahoo_id),
            gsis_id=str(yahoo_id),
            full_name=info.get("name", f"Player #{yahoo_id}"),
            position=info.get("position", ""),
            season_year=season_year,
            match_confidence=1.0,
        ))
    await session.commit()
    logger.info(f"Stored {len(all_players)} player maps for {season_year}")


async def store_game_logs(
    session: AsyncSession,
    player_stats: Dict[int, List[Dict[str, Any]]],
    all_players: Dict[str, Dict[str, str]],
    season_year: int,
):
    """Store Yahoo weekly stats as game logs. player_id = yahoo_id."""
    await session.execute(
        delete(NflGameLog).where(NflGameLog.season_year == season_year)
    )
    count = 0
    for week, stats in player_stats.items():
        for stat in stats:
            yahoo_id = str(stat.get("player_id", ""))

            position = all_players.get(yahoo_id, {}).get("position", "")
            raw = stat.get("stats", {})
            if isinstance(raw, dict):
                raw["position"] = position
            else:
                raw = {"position": position}

            session.add(NflGameLog(
                player_id=str(yahoo_id),
                week=int(week),
                season_year=season_year,
                fantasy_points=stat.get("total_points", 0.0),
                raw_stats=raw,
            ))
            count += 1

        # Commit per week to avoid huge transactions
        await session.commit()

    logger.info(f"Stored {count} game logs for {season_year}")


async def store_matchups(
    session: AsyncSession,
    matchups: Dict[int, List[Dict[str, Any]]],
    season_year: int,
):
    await session.execute(
        delete(LeagueMatchup).where(LeagueMatchup.season_year == season_year)
    )
    count = 0
    for week, week_matchups in matchups.items():
        for m in week_matchups:
            t1, t2 = m["team1_key"], m["team2_key"]
            t1_pts, t2_pts = m["team1_score"], m["team2_score"]

            session.add(LeagueMatchup(
                team_id=t1, week=int(week), season_year=season_year,
                opponent_id=t2, team_score=t1_pts, opponent_score=t2_pts,
                is_win=t1_pts > t2_pts,
            ))
            session.add(LeagueMatchup(
                team_id=t2, week=int(week), season_year=season_year,
                opponent_id=t1, team_score=t2_pts, opponent_score=t1_pts,
                is_win=t2_pts > t1_pts,
            ))
            count += 2
    await session.commit()
    logger.info(f"Stored {count} matchup records for {season_year}")


# --- Main pipeline ---

async def main():
    parser = argparse.ArgumentParser(description="Initialize FF Regret data from Yahoo")
    parser.add_argument(
        "--league-key", required=True,
        help="Yahoo league key (e.g. 449.l.776116 for 2024, 461.l.186782 for 2025)",
    )
    parser.add_argument(
        "--season-year", type=int, required=True,
        help="Season year (2024 or 2025)",
    )
    parser.add_argument(
        "--clear-cache", action="store_true",
        help="Clear cached data for this season and re-fetch",
    )
    parser.add_argument(
        "--skip-stats", action="store_true",
        help="Skip fetching player stats (useful for testing)",
    )
    args = parser.parse_args()

    if args.clear_cache:
        import shutil
        cache = _cache_dir(args.season_year)
        if cache.exists():
            shutil.rmtree(cache)
            logger.info(f"Cache cleared for {args.season_year}")

    await init_db()

    # Step 1: Fetch Yahoo league data
    logger.info(f"=== Fetching Yahoo data for {args.season_year} ===")
    yahoo = YahooFantasyService()
    yahoo_data = fetch_yahoo_league_data(yahoo, args.league_key, args.season_year)

    # Step 2: Collect all unique players
    all_players = collect_all_players(yahoo_data)
    player_ids = list(all_players.keys())

    # Step 3: Fetch player stats from Yahoo
    player_stats = {}
    if not args.skip_stats:
        logger.info(f"=== Fetching player stats ({len(player_ids)} players) ===")
        player_stats = fetch_player_stats(
            yahoo, args.league_key, args.season_year,
            player_ids, yahoo_data["end_week"],
        )

    # Step 4: Fetch matchups
    logger.info("=== Fetching matchups ===")
    matchups = fetch_matchups(
        yahoo, args.league_key, args.season_year, yahoo_data["end_week"],
    )

    # Step 5: Store everything to DB
    logger.info("=== Storing to database ===")
    async with async_session() as session:
        try:
            await store_league_config(
                session, yahoo_data["league_config"], args.season_year
            )
            await store_draft_results(
                session, yahoo_data["draft_results"], args.season_year
            )
            await store_weekly_rosters(
                session, yahoo_data["weekly_rosters"], args.season_year
            )
            await store_waiver_data(
                session, yahoo_data["waiver_data"], args.season_year
            )
            await store_player_maps(session, all_players, args.season_year)

            if player_stats:
                await store_game_logs(
                    session, player_stats, all_players, args.season_year
                )

            await store_matchups(session, matchups, args.season_year)

            logger.info(f"=== Data initialization complete for {args.season_year}! ===")

        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
