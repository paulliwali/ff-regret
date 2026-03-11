"""Map Yahoo players to NFL GSIS IDs using game logs."""

import sqlite3
import json
from rapidfuzz import fuzz, process
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def normalize_name(name: str) -> str:
    """Normalize player name for fuzzy matching."""
    name = str(name).strip() if name else ''
    
    # Remove suffixes like "Jr.", "II", "III", "IV", "Sr."
    suffixes = r'\b(Jr\.?|II|III|IV|Sr\.?|MD|PhD)\b\.?'
    name = re.sub(suffixes, '', name, flags=re.IGNORECASE)
    
    # Remove special characters except hyphens and apostrophes
    name = re.sub(r"[^\w\-'\s]", '', name)
    
    # Remove periods (from initials like "B.Mayfield")
    name = name.replace('.', '')
    
    # Convert to lowercase and strip
    name = name.lower().strip()
    
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)
    
    return name


def main():
    logger.info("Building player name index from NFL game logs")
    
    conn = sqlite3.connect('ff_regret.db')
    cursor = conn.cursor()
    
    # Step 1: Build name index from NFL data using nfl_data_py
    import nfl_data_py as nfl
    import polars as pl
    
    logger.info("Fetching NFL game logs with player names")
    df = nfl.import_weekly_data([2024])
    
    if df is None or len(df) == 0:
        logger.error("No NFL game logs found")
        return
    
    df_pl = pl.from_pandas(df)
    logger.info(f"Fetched {len(df_pl)} NFL game log entries")
    
    # Build player_name -> gsis_id mapping (using both player_name and player_display_name)
    player_name_to_gsis = {}
    unique_players = df_pl.select(['player_id', 'player_name', 'player_display_name']).unique()
    
    for row in unique_players.iter_rows(named=True):
        gsis_id = row.get('player_id')
        
        # Index by player_name (e.g., "B.Mayfield")
        player_name = row.get('player_name')
        if player_name:
            normalized = normalize_name(player_name)
            if normalized not in player_name_to_gsis:
                player_name_to_gsis[normalized] = gsis_id
        
        # Index by player_display_name (e.g., "Baker Mayfield")
        display_name = row.get('player_display_name')
        if display_name:
            normalized = normalize_name(display_name)
            if normalized not in player_name_to_gsis:
                player_name_to_gsis[normalized] = gsis_id
    
    logger.info(f"Built index for {len(player_name_to_gsis)} unique NFL players")
    
    # Step 2: Collect Yahoo players from rosters
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
                    if yahoo_id_str not in yahoo_players or not yahoo_players[yahoo_id_str]:
                        yahoo_players[yahoo_id_str] = name
        except Exception as e:
            continue
    
    logger.info(f"Collected {len(yahoo_players)} unique Yahoo players from rosters")
    
    # Step 3: Match Yahoo players to NFL GSIS IDs
    mapped = 0
    unmatched = []
    
    cursor.execute('DELETE FROM player_map')
    
    for yahoo_id, yahoo_name in yahoo_players.items():
        normalized_yahoo = normalize_name(yahoo_name)
        
        gsis_id = None
        confidence = 0.0
        
        # Try direct lookup
        if normalized_yahoo in player_name_to_gsis:
            gsis_id = player_name_to_gsis[normalized_yahoo]
            confidence = 1.0
        else:
            # Fuzzy matching
            matches = process.extract(
                normalized_yahoo,
                list(player_name_to_gsis.keys()),
                limit=1,
                scorer=fuzz.token_sort_ratio
            )
            
            if matches and matches[0][1] >= 90:  # 90% similarity threshold
                best_match = matches[0][0]
                score = matches[0][1]
                gsis_id = player_name_to_gsis[best_match]
                
                if score >= 95:
                    confidence = 0.95
                elif score >= 90:
                    confidence = 0.85
                else:
                    gsis_id = None
                    confidence = 0.0
        
        # Insert into database
        cursor.execute(
            'INSERT INTO player_map (yahoo_id, gsis_id, full_name, match_confidence) VALUES (?, ?, ?, ?)',
            (yahoo_id, gsis_id, yahoo_name, confidence)
        )
        
        if gsis_id:
            mapped += 1
        else:
            unmatched.append((yahoo_id, yahoo_name))
    
    conn.commit()
    
    # Summary
    logger.info(f"\nMapping Summary:")
    logger.info(f"  Total Yahoo players: {len(yahoo_players)}")
    logger.info(f"  Successfully mapped: {mapped} ({mapped/len(yahoo_players)*100:.1f}%)")
    
    # Show examples
    logger.info("\nExample successful mappings:")
    cursor.execute('SELECT yahoo_id, gsis_id, full_name, match_confidence FROM player_map WHERE gsis_id IS NOT NULL ORDER BY match_confidence DESC LIMIT 10')
    for row in cursor.fetchall():
        logger.info(f"  {row[2]} (Yahoo: {row[0]} -> NFL: {row[1]}) - Confidence: {row[3]:.2f}")
    
    # Show unmatched examples
    if unmatched:
        logger.info(f"\nUnmatched players (first 10):")
        for yahoo_id, name in unmatched[:10]:
            logger.info(f"  {name} (Yahoo ID: {yahoo_id})")
    
    conn.close()
    logger.info("\nPlayer mapping complete!")


if __name__ == "__main__":
    main()
