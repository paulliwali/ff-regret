"""Create player_map by matching Yahoo player names from rosters to NFL data."""

import sqlite3
import json

conn = sqlite3.connect('ff_regret.db')
cursor = conn.cursor()

# Step 1: Collect all Yahoo players from rosters with their names
yahoo_players = {}
cursor.execute('SELECT roster_snapshot FROM league_weekly_rosters')
for (roster_json,) in cursor.fetchall():
    try:
        roster = json.loads(roster_json)
        for player in roster.get('players', []):
            yahoo_id = player.get('player_id')
            name = player.get('name', '').strip()
            if yahoo_id and name:
                # Convert yahoo_id to string for consistency
                yahoo_id_str = str(yahoo_id)
                if yahoo_id_str not in yahoo_players or not yahoo_players[yahoo_id_str]:
                    yahoo_players[yahoo_id_str] = name
    except Exception as e:
        print(f"Error parsing roster: {e}")
        continue

print(f"Collected {len(yahoo_players)} Yahoo players from rosters")

# Step 2: Get all NFL player IDs from game logs
nfl_players = {}
cursor.execute('SELECT DISTINCT player_id FROM nfl_game_logs')
for (player_id,) in cursor.fetchall():
    nfl_players[player_id] = None  # We'll store name if available

print(f"Found {len(nfl_players)} unique NFL player IDs")

# Step 3: Try to match using player names (we need NFL player names first)
# For now, we'll create player_map entries without GSIS IDs
# The fuzzy matching will need to be done with NFL player names which we don't have in the DB yet

# Create player_map entries
count = 0
for yahoo_id, name in yahoo_players.items():
    cursor.execute(
        'INSERT OR REPLACE INTO player_map (yahoo_id, gsis_id, full_name, match_confidence) VALUES (?, ?, ?, ?)',
        (yahoo_id, None, name, 0.0)
    )
    count += 1
    if count % 100 == 0:
        conn.commit()
        print(f"Inserted {count} player entries...")

conn.commit()
print(f"\nTotal inserted: {count} player_map entries")

# Verify
cursor.execute('SELECT COUNT(*) FROM player_map')
total = cursor.fetchone()[0]
print(f'Total player_map entries: {total}')

conn.close()
print("Done!")
