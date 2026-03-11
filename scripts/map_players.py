"""Map Yahoo players to NFL GSIS IDs using fuzzy matching."""

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import async_session
from app.services.player_mapper import PlayerMapper
from app.services.nfl_service import NFLDataService
import sqlite3
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting player mapping with fuzzy matching")
    
    # Get NFL player IDs with names
    nfl_service = NFLDataService(season_year=2024)
    nfl_player_ids = nfl_service.fetch_player_ids()
    
    if len(nfl_player_ids) == 0:
        logger.error("No NFL player IDs available")
        return
    
    logger.info(f"Found {len(nfl_player_ids)} NFL player IDs")
    
    # Collect Yahoo players from rosters using sqlite directly
    conn = sqlite3.connect('ff_regret.db')
    cursor = conn.cursor()
    
    yahoo_players = {}
    cursor.execute('SELECT roster_snapshot FROM league_weekly_rosters')
    for (roster_json,) in cursor.fetchall():
        try:
            roster = json.loads(roster_json)
            for player in roster.get('players', []):
                yahoo_id = player.get('player_id')
                name = player.get('name', '').strip()
                if yahoo_id and name:
                    yahoo_id_str = str(yahoo_id)
                    # Keep the name from the roster
                    if yahoo_id_str not in yahoo_players or not yahoo_players[yahoo_id_str]:
                        yahoo_players[yahoo_id_str] = name
        except Exception as e:
            print(f"Error parsing roster: {e}")
            continue
    
    conn.close()
    logger.info(f"Collected {len(yahoo_players)} unique Yahoo players from rosters")
    
    # Prepare Yahoo players list for mapper
    yahoo_players_list = [
        {"player_id": yahoo_id, "name": name}
        for yahoo_id, name in yahoo_players.items()
    ]
    
    # Use PlayerMapper to match players
    mapper = PlayerMapper()
    mapped_players = mapper.batch_map_yahoo_players(yahoo_players_list, nfl_player_ids)
    
    # Count successful mappings
    successful = [p for p in mapped_players if p.get('gsis_id')]
    logger.info(f"Mapped {len(successful)}/{len(yahoo_players_list)} players successfully")
    
    # Update player_map table using sqlite directly
    conn = sqlite3.connect('ff_regret.db')
    cursor = conn.cursor()
    
    # Clear existing entries
    cursor.execute('DELETE FROM player_map')
    logger.info("Cleared existing player_map entries")
    
    # Insert new mappings
    count = 0
    for mapping in mapped_players:
        cursor.execute(
            'INSERT INTO player_map (yahoo_id, gsis_id, full_name, match_confidence) VALUES (?, ?, ?, ?)',
            (
                mapping['yahoo_id'],
                mapping['gsis_id'],
                mapping['full_name'],
                mapping['match_confidence']
            )
        )
        count += 1
        if count % 100 == 0:
            conn.commit()
            logger.info(f"Inserted {count} player mappings...")
    
    conn.commit()
    logger.info(f"Total inserted: {count} player mappings")
    
    # Summary statistics
    cursor.execute('SELECT COUNT(*) FROM player_map WHERE gsis_id IS NOT NULL')
    mapped_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM player_map')
    total_count = cursor.fetchone()[0]
    
    logger.info(f"\nMapping Summary:")
    logger.info(f"  Total Yahoo players: {len(yahoo_players_list)}")
    logger.info(f"  Successfully mapped: {mapped_count}")
    logger.info(f"  Mapped with confidence >= 0.7: {sum(1 for m in mapped_players if m.get('gsis_id') and m.get('match_confidence', 0) >= 0.7)}")
    
    # Show some examples of matches
    cursor.execute('SELECT yahoo_id, gsis_id, full_name, match_confidence FROM player_map WHERE gsis_id IS NOT NULL LIMIT 10')
    logger.info("\nExample mappings:")
    for row in cursor.fetchall():
        confidence_label = mapper.match_confidence_label(row[3])
        logger.info(f"  {row[2]} (Yahoo: {row[0]} -> NFL: {row[1]}) - Confidence: {row[3]:.2f} ({confidence_label})")
    
    # Show some unmatched examples
    cursor.execute('SELECT yahoo_id, full_name FROM player_map WHERE gsis_id IS NULL LIMIT 5')
    unmatched = cursor.fetchall()
    if unmatched:
        logger.info("\nUnmatched players (first 5):")
        for row in unmatched:
            logger.info(f"  {row[1]} (Yahoo ID: {row[0]})")
    
    conn.close()
    
    logger.info("\nPlayer mapping complete!")


if __name__ == "__main__":
    asyncio.run(main())
