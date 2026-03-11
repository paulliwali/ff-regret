import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import async_session, init_db
from app.models import LeagueConfig, PlayerMap, NflGameLog, LeagueWeeklyRoster, LeagueDraftResult, WaiverWireAvailability
from app.services.yahoo_service import YahooFantasyService
from app.services.nfl_service import NFLDataService
from app.services.player_mapper import PlayerMapper
from app.services.scoring_calculator import ScoringRulesParser, FantasyPointsCalculator
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


async def store_player_maps(session: AsyncSession, mapped_players: list):
    """Store player ID mappings with confidence scores."""
    logger.info(f"Storing {len(mapped_players)} player ID mappings")
    
    mapped_count = 0
    unmapped_count = 0
    
    for mapping in mapped_players:
        player_map = PlayerMap(
            yahoo_id=mapping["yahoo_id"],
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
    logger.info(f"Stored {mapped_count} mapped players, {unmapped_count} unmapped")


async def store_nfl_game_logs(session: AsyncSession, game_logs: pl.DataFrame, scoring_calculator: FantasyPointsCalculator):
    """Store NFL game logs with fantasy points calculated using league scoring rules."""
    logger.info(f"Storing {len(game_logs)} NFL game logs")
    
    # Process in batches to avoid memory issues
    batch_size = 1000
    batches = len(game_logs) // batch_size + 1
    
    for i in range(batches):
        start = i * batch_size
        end = start + batch_size
        batch = game_logs.slice(start, batch_size)
        
        for row in batch.iter_rows(named=True):
            # Skip if no gsis_id
            if not row.get("gsis_id"):
                continue
            
            # Calculate fantasy points using league scoring calculator
            fantasy_points = scoring_calculator.calculate_fantasy_points(row)
            
            game_log = NflGameLog(
                player_id=row.get("gsis_id", ""),
                week=row.get("week", 1),
                season_year=settings.season_year,
                fantasy_points=fantasy_points,
                status=row.get("status", "ACTIVE"),
                raw_stats=dict(row) if hasattr(row, '__dict__') else {},
            )
            session.add(game_log)
        
        if i % 10 == 0:
            await session.commit()
            logger.info(f"Processed batch {i}/{batches}")
    
    await session.commit()


async def map_and_store_players(session: AsyncSession, yahoo_players: list, nfl_player_ids: pl.DataFrame):
    """Map Yahoo players to NFL IDs using fuzzy matching and store results."""
    logger.info(f"Mapping {len(yahoo_players)} Yahoo players to NFL IDs")
    
    player_mapper = PlayerMapper()
    mapped_players = player_mapper.batch_map_yahoo_players(yahoo_players, nfl_player_ids)
    
    await store_player_maps(session, mapped_players)


def collect_all_yahoo_players(draft_results: list, weekly_rosters: dict, waiver_data: dict) -> list:
    """Collect all unique players from draft, rosters, and waivers."""
    players = {}
    
    # From draft (draft results don't have names, just player_id)
    for result in draft_results:
        player_id = result["player_id"]
        if player_id and player_id not in players:
            players[player_id] = {
                "player_id": player_id,
                "name": ""
            }
    
    # From weekly rosters (update names if missing)
    for week, rosters in weekly_rosters.items():
        for team_id, player_list in rosters.items():
            for player in player_list:
                player_id = player.get("player_id")
                if player_id:
                    if player_id not in players:
                        players[player_id] = {
                            "player_id": player_id,
                            "name": player.get("name", "")
                        }
                    elif not players[player_id].get("name"):
                        players[player_id]["name"] = player.get("name", "")
    
    # From waiver wire (update names if missing)
    for week, player_list in waiver_data.items():
        for player in player_list:
            player_id = player.get("player_id")
            if player_id:
                if player_id not in players:
                    players[player_id] = {
                        "player_id": player_id,
                        "name": player.get("name", "")
                    }
                elif not players[player_id].get("name"):
                    players[player_id]["name"] = player.get("name", "")
    
    logger.info(f"Collected {len(players)} unique Yahoo players")
    return list(players.values())


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
            
            # Fetch waiver wire data manually
            logger.info("Fetching waiver wire data")
            waiver_data = {}
            lg = yahoo_service.get_league()
            end_week = lg.end_week()
            for week in range(1, end_week + 1):
                logger.info(f"Fetching waiver wire data for week {week}")
                waiver_data[week] = yahoo_service.fetch_waiver_wire_availability(week)
            
            logger.info("Storing Yahoo data to database")
            await store_league_config(session, league_config)
            await store_draft_results(session, draft_results)
            await store_weekly_rosters(session, weekly_rosters)
            await store_waiver_wire_data(session, waiver_data)
            
            logger.info("Fetching NFL data")
            nfl_service = NFLDataService()
            game_logs = nfl_service.fetch_weekly_game_logs()
            player_ids = nfl_service.fetch_player_ids()
            
            if len(player_ids) > 0:
                logger.info("Mapping Yahoo players to NFL IDs with fuzzy matching")
                
                # Collect all Yahoo players from draft, rosters, and waivers
                yahoo_players = collect_all_yahoo_players(draft_results, weekly_rosters, waiver_data)
                
                # Map Yahoo players to NFL IDs
                await map_and_store_players(session, yahoo_players, player_ids)
            else:
                logger.warning("No NFL player IDs available for mapping")
            
            if len(game_logs) > 0:
                logger.info("Storing NFL game logs")
                
                # Parse Yahoo scoring config into scoring rules
                scoring_rules = ScoringRulesParser.parse_yahoo_scoring_config(league_config)
                logger.info(f"Parsed {len(scoring_rules)} scoring rules from Yahoo config")
                
                # Create fantasy points calculator
                scoring_calculator = FantasyPointsCalculator(scoring_rules)
                
                await store_nfl_game_logs(session, game_logs, scoring_calculator)
            else:
                logger.warning("No NFL game logs to store")
            
            logger.info("Data initialization complete!")
            
        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())