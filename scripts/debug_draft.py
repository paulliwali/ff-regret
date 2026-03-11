"""Debug script to see what draft results look like"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)

from yahoo_oauth import OAuth2
from yahoo_fantasy_api import game, league

TOKEN_FILE = Path(__file__).parent.parent / "app" / "oauth2.json"

oauth = OAuth2(None, None, from_file=str(TOKEN_FILE))
gm = game.Game(oauth, "nfl")
league_key = f"{gm.game_id()}.l.186782"
lg = gm.to_league(league_key)

print("Fetching draft results...")
draft_results = lg.draft_results()

print(f"\nTotal draft results: {len(draft_results)}")
print("\nFirst draft result:")
print(draft_results[0])
print("\nAll keys in first result:")
print(draft_results[0].keys())