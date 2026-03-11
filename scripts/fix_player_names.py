"""Update player_map with correct names from roster data."""

import sqlite3
import json

conn = sqlite3.connect('ff_regret.db')
cursor = conn.cursor()

# First, collect player names from weekly rosters
player_names = {}
cursor.execute('SELECT roster_snapshot FROM league_weekly_rosters')
rosters = cursor.fetchall()

for (roster_json,) in rosters:
    try:
        roster = json.loads(roster_json)
        for player in roster.get('players', []):
            player_id = player.get('player_id')
            name = player.get('name', '')
            if player_id and name and (player_id not in player_names or not player_names[player_id]):
                player_names[player_id] = name
    except:
        pass

print(f"Collected names for {len(player_names)} players from rosters")

# Now update the player_map table
updated_count = 0
cursor.execute('SELECT yahoo_id, full_name FROM player_map')
for yahoo_id, full_name in cursor.fetchall():
    if not full_name and yahoo_id in player_names:
        cursor.execute(
            'UPDATE player_map SET full_name = ? WHERE yahoo_id = ?',
            (player_names[yahoo_id], yahoo_id)
        )
        updated_count += 1
        if updated_count % 100 == 0:
            print(f"Updated {updated_count} player names...")
            conn.commit()

conn.commit()
print(f"\nTotal updated: {updated_count} player names")

conn.close()
print("Done!")
