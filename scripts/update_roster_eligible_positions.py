"""Update existing roster data to include eligible_positions."""

import sqlite3
import json

conn = sqlite3.connect('ff_regret.db')
cursor = conn.cursor()

# Get all weekly rosters
cursor.execute('SELECT id, roster_snapshot FROM league_weekly_rosters')
rosters = cursor.fetchall()

print(f"Found {len(rosters)} weekly rosters to update")

updated_count = 0
for roster_id, roster_json in rosters:
    try:
        roster = json.loads(roster_json)
        
        # Update each player to include eligible_positions
        for player in roster.get('players', []):
            if 'eligible_positions' not in player:
                # Use position field as eligible_positions
                position = player.get('position', 'UNK')
                player['eligible_positions'] = [position] if position != 'UNK' else []
        
        # Update the database
        updated_json = json.dumps(roster)
        cursor.execute(
            'UPDATE league_weekly_rosters SET roster_snapshot = ? WHERE id = ?',
            (updated_json, roster_id)
        )
        updated_count += 1
        
        if updated_count % 100 == 0:
            print(f"Updated {updated_count} rosters...")
            conn.commit()
    
    except Exception as e:
        print(f"Error updating roster {roster_id}: {e}")
        continue

conn.commit()
print(f"\nTotal updated: {updated_count} rosters")

conn.close()
print("Done!")
