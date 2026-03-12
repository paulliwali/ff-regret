import argparse
import asyncio
import json
import logging
from pathlib import Path

import polars as pl
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session, init_db
from app.models import (
    LeagueConfig,
    LeagueDraftResult,
    LeagueWeeklyRoster,
    NflGameLog,
    PlayerMap,
    WaiverWireAvailability,
)
from app.services.nfl_service import NFLDataService
from app.services.player_mapper import PlayerMapper
from app.services.scoring_calculator import FantasyPointsCalculator, ScoringRulesParser
from app.services.yahoo_service import YahooFantasyService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / ".cache"

STEPS = [
    "fetch_yahoo",
    "fetch_nfl",
    "store_league_config",
    "store_draft",
    "store_rosters",
    "store_waivers",
    "store_player_maps",
    "store_game_logs",
]


# --- Cache helpers ---

def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def _save_cache(name: str, data):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(name)
    with open(path, "w") as f:
        json.dump(data, f)
    logger.info(f"Cached {name} -> {path}")


def _load_cache(name: str):
    path = _cache_path(name)
    if path.exists():
        logger.info(f"Loading cached {name} from {path}")
        with open(path, "r") as f:
            return json.load(f)
    return None


def _cache_parquet_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.parquet"


def _save_parquet_cache(name: str, df: pl.DataFrame):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_parquet_path(name)
    df.write_parquet(path)
    logger.info(f"Cached {name} -> {path}")


def _load_parquet_cache(name: str) -> pl.DataFrame | None:
    path = _cache_parquet_path(name)
    if path.exists():
        logger.info(f"Loading cached {name} from {path}")
        return pl.read_parquet(path)
    return None


# --- Fetch steps (cache API responses locally) ---

def fetch_yahoo_data() -> dict:
    """Fetch all Yahoo data, using cache if available."""
    league_config = _load_cache("league_config")
    draft_results = _load_cache("draft_results")
    weekly_rosters = _load_cache("weekly_rosters")
    waiver_data = _load_cache("waiver_data")

    if all(x is not None for x in [league_config, draft_results, weekly_rosters, waiver_data]):
        logger.info("All Yahoo data loaded from cache")
        return {
            "league_config": league_config,
            "draft_results": draft_results,
            "weekly_rosters": weekly_rosters,
            "waiver_data": waiver_data,
        }

    yahoo_service = YahooFantasyService()

    if league_config is None:
        logger.info("Fetching league config from Yahoo")
        league_config = yahoo_service.fetch_league_config()
        _save_cache("league_config", league_config)

    if draft_results is None:
        logger.info("Fetching draft results from Yahoo")
        draft_results = yahoo_service.fetch_draft_results()
        _save_cache("draft_results", draft_results)

    if weekly_rosters is None:
        logger.info("Fetching weekly rosters from Yahoo")
        weekly_rosters = yahoo_service.fetch_all_weekly_rosters()
        _save_cache("weekly_rosters", weekly_rosters)

    if waiver_data is None:
        logger.info("Fetching waiver wire data from Yahoo")
        waiver_data = {}
        lg = yahoo_service.get_league()
        end_week = lg.end_week()
        for week in range(1, end_week + 1):
            logger.info(f"  Week {week}/{end_week}")
            waiver_data[week] = yahoo_service.fetch_waiver_wire_availability(week)
        _save_cache("waiver_data", waiver_data)

    return {
        "league_config": league_config,
        "draft_results": draft_results,
        "weekly_rosters": weekly_rosters,
        "waiver_data": waiver_data,
    }


def fetch_nfl_data() -> dict:
    """Fetch NFL data, using cache if available."""
    game_logs = _load_parquet_cache("nfl_game_logs")
    player_ids = _load_parquet_cache("nfl_player_ids")

    if game_logs is not None and player_ids is not None:
        logger.info("All NFL data loaded from cache")
        return {"game_logs": game_logs, "player_ids": player_ids}

    nfl_service = NFLDataService()

    if game_logs is None:
        logger.info("Fetching NFL game logs")
        game_logs = nfl_service.fetch_weekly_game_logs()
        _save_parquet_cache("nfl_game_logs", game_logs)

    if player_ids is None:
        logger.info("Fetching NFL player IDs")
        player_ids = nfl_service.fetch_player_ids()
        _save_parquet_cache("nfl_player_ids", player_ids)

    return {"game_logs": game_logs, "player_ids": player_ids}


# --- Store steps (clear table + insert, each idempotent) ---

async def store_league_config(session: AsyncSession, config: dict):
    await session.execute(delete(LeagueConfig))
    logger.info("Storing league configuration")
    league_config = LeagueConfig(
        scoring_config=config.get("scoring_config", {}),
        roster_requirements=config.get("roster_requirements", {}),
        season_year=settings.season_year,
    )
    session.add(league_config)
    await session.commit()


async def store_draft_results(session: AsyncSession, draft_results: list):
    await session.execute(delete(LeagueDraftResult))
    logger.info(f"Storing {len(draft_results)} draft results")
    for result in draft_results:
        draft_result = LeagueDraftResult(
            team_id=str(result["team_id"]),
            overall_pick=result["overall_pick"],
            round=result["round"],
            player_id=str(result["player_id"]),
            pick_timestamp=result.get("pick_timestamp"),
        )
        session.add(draft_result)
    await session.commit()


async def store_weekly_rosters(session: AsyncSession, weekly_rosters: dict):
    await session.execute(delete(LeagueWeeklyRoster))
    logger.info("Storing weekly rosters")
    for week, rosters in weekly_rosters.items():
        for team_id, players in rosters.items():
            roster = LeagueWeeklyRoster(
                team_id=str(team_id),
                week=int(week),
                season_year=settings.season_year,
                roster_snapshot={"players": players},
            )
            session.add(roster)
    await session.commit()


async def store_waiver_wire_data(session: AsyncSession, waiver_data: dict):
    await session.execute(delete(WaiverWireAvailability))
    logger.info("Storing waiver wire data")
    for week, players in waiver_data.items():
        for player_data in players:
            availability = WaiverWireAvailability(
                player_id=str(player_data["player_id"]),
                week=int(player_data["week"]),
                ownership_percentage=player_data["ownership_percentage"],
                is_on_waivers=player_data["is_on_waivers"],
            )
            session.add(availability)
    await session.commit()


async def store_player_maps(session: AsyncSession, yahoo_data: dict, nfl_data: dict):
    await session.execute(delete(PlayerMap))

    player_ids = nfl_data["player_ids"]
    if len(player_ids) == 0:
        logger.warning("No NFL player IDs available for mapping")
        return

    yahoo_players = collect_all_yahoo_players(
        yahoo_data["draft_results"],
        yahoo_data["weekly_rosters"],
        yahoo_data["waiver_data"],
    )
    logger.info(f"Mapping {len(yahoo_players)} Yahoo players to NFL IDs")

    player_mapper = PlayerMapper()
    mapped_players = player_mapper.batch_map_yahoo_players(yahoo_players, player_ids)

    mapped_count = 0
    unmapped_count = 0
    for mapping in mapped_players:
        player_map = PlayerMap(
            yahoo_id=str(mapping["yahoo_id"]),
            gsis_id=mapping["gsis_id"],
            full_name=mapping["full_name"],
            match_confidence=mapping["match_confidence"],
        )
        session.add(player_map)
        if mapping["gsis_id"]:
            mapped_count += 1
        else:
            unmapped_count += 1

    await session.commit()
    logger.info(f"Stored {mapped_count} mapped, {unmapped_count} unmapped players")


async def store_nfl_game_logs(session: AsyncSession, yahoo_data: dict, nfl_data: dict):
    await session.execute(delete(NflGameLog))

    game_logs = nfl_data["game_logs"]
    if len(game_logs) == 0:
        logger.warning("No NFL game logs to store")
        return

    scoring_rules = ScoringRulesParser.parse_yahoo_scoring_config(yahoo_data["league_config"])
    logger.info(f"Parsed {len(scoring_rules)} scoring rules")
    scoring_calculator = FantasyPointsCalculator(scoring_rules)

    logger.info(f"Storing {len(game_logs)} NFL game logs")
    batch_size = 1000
    total_batches = len(game_logs) // batch_size + 1

    for i in range(total_batches):
        batch = game_logs.slice(i * batch_size, batch_size)

        for row in batch.iter_rows(named=True):
            if not row.get("gsis_id"):
                continue

            fantasy_points = scoring_calculator.calculate_fantasy_points(row)
            game_log = NflGameLog(
                player_id=row.get("gsis_id", ""),
                week=row.get("week", 1),
                season_year=settings.season_year,
                fantasy_points=fantasy_points,
                status=row.get("status", "ACTIVE"),
                raw_stats=dict(row) if hasattr(row, "__dict__") else {},
            )
            session.add(game_log)

        await session.commit()
        if i % 10 == 0:
            logger.info(f"  Batch {i}/{total_batches}")

    logger.info("Game logs stored")


# --- Helpers ---

def collect_all_yahoo_players(draft_results: list, weekly_rosters: dict, waiver_data: dict) -> list:
    players = {}

    for result in draft_results:
        pid = str(result["player_id"])
        if pid and pid not in players:
            players[pid] = {"player_id": pid, "name": ""}

    for week, rosters in weekly_rosters.items():
        for team_id, player_list in rosters.items():
            for player in player_list:
                pid = str(player.get("player_id", ""))
                if pid:
                    if pid not in players:
                        players[pid] = {"player_id": pid, "name": player.get("name", "")}
                    elif not players[pid].get("name"):
                        players[pid]["name"] = player.get("name", "")

    for week, player_list in waiver_data.items():
        for player in player_list:
            pid = str(player.get("player_id", ""))
            if pid:
                if pid not in players:
                    players[pid] = {"player_id": pid, "name": player.get("name", "")}
                elif not players[pid].get("name"):
                    players[pid]["name"] = player.get("name", "")

    logger.info(f"Collected {len(players)} unique Yahoo players")
    return list(players.values())


# --- Main pipeline ---

async def main():
    parser = argparse.ArgumentParser(description="Initialize FF Regret data")
    parser.add_argument(
        "--from-step",
        choices=STEPS,
        default=STEPS[0],
        help=f"Resume from this step. Steps: {', '.join(STEPS)}",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Delete cached API responses and re-fetch everything",
    )
    args = parser.parse_args()

    if args.clear_cache:
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
            logger.info("Cache cleared")

    start_idx = STEPS.index(args.from_step)
    logger.info(f"Starting from step: {args.from_step} (step {start_idx + 1}/{len(STEPS)})")

    await init_db()

    # Step 1: Fetch Yahoo data (cached locally)
    yahoo_data = None
    if start_idx <= STEPS.index("fetch_yahoo"):
        logger.info("=== Step 1/8: Fetch Yahoo data ===")
        yahoo_data = fetch_yahoo_data()
    else:
        yahoo_data = {
            "league_config": _load_cache("league_config"),
            "draft_results": _load_cache("draft_results"),
            "weekly_rosters": _load_cache("weekly_rosters"),
            "waiver_data": _load_cache("waiver_data"),
        }
        if any(v is None for v in yahoo_data.values()):
            logger.error("Yahoo cache missing — run from fetch_yahoo step first")
            return

    # Step 2: Fetch NFL data (cached locally)
    nfl_data = None
    if start_idx <= STEPS.index("fetch_nfl"):
        logger.info("=== Step 2/8: Fetch NFL data ===")
        nfl_data = fetch_nfl_data()
    else:
        game_logs = _load_parquet_cache("nfl_game_logs")
        player_ids = _load_parquet_cache("nfl_player_ids")
        if game_logs is None or player_ids is None:
            logger.error("NFL cache missing — run from fetch_nfl step first")
            return
        nfl_data = {"game_logs": game_logs, "player_ids": player_ids}

    # Steps 3-8: Store to database (each clears its table first)
    async with async_session() as session:
        try:
            if start_idx <= STEPS.index("store_league_config"):
                logger.info("=== Step 3/8: Store league config ===")
                await store_league_config(session, yahoo_data["league_config"])

            if start_idx <= STEPS.index("store_draft"):
                logger.info("=== Step 4/8: Store draft results ===")
                await store_draft_results(session, yahoo_data["draft_results"])

            if start_idx <= STEPS.index("store_rosters"):
                logger.info("=== Step 5/8: Store weekly rosters ===")
                await store_weekly_rosters(session, yahoo_data["weekly_rosters"])

            if start_idx <= STEPS.index("store_waivers"):
                logger.info("=== Step 6/8: Store waiver wire data ===")
                await store_waiver_wire_data(session, yahoo_data["waiver_data"])

            if start_idx <= STEPS.index("store_player_maps"):
                logger.info("=== Step 7/8: Store player mappings ===")
                await store_player_maps(session, yahoo_data, nfl_data)

            if start_idx <= STEPS.index("store_game_logs"):
                logger.info("=== Step 8/8: Store NFL game logs ===")
                await store_nfl_game_logs(session, yahoo_data, nfl_data)

            logger.info("Data initialization complete!")

        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
