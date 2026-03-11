"""Quick test: can we connect to Yahoo Fantasy API and read league data?"""

import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)

from yahoo_oauth import OAuth2

TOKEN_FILE = Path(__file__).parent.parent / "app" / "oauth2.json"

print("Step 1: Loading OAuth2 from token file...")
try:
    oauth = OAuth2(None, None, from_file=str(TOKEN_FILE))
    print(f"  Token valid: {oauth.token_is_valid()}")
except Exception as e:
    print(f"  FAILED: {e}")
    sys.exit(1)

print()
print("Step 2: Creating Game object...")
from yahoo_fantasy_api import game as yf_game

try:
    gm = yf_game.Game(oauth, "nfl")
    game_id = gm.game_id()
    print(f"  Game ID: {game_id}")
except Exception as e:
    print(f"  FAILED: {e}")
    sys.exit(1)

print()
print("Step 3: Connecting to league 186782...")
try:
    league_key = f"{game_id}.l.186782"
    lg = gm.to_league(league_key)
    print(f"  League key: {league_key}")

    settings_data = lg.settings()
    print(f"  League name: {settings_data.get('name', 'Unknown')}")
    print(f"  Num teams: {settings_data.get('num_teams', 'Unknown')}")
except Exception as e:
    print(f"  FAILED: {e}")
    print()
    print("If you get a 401 error, your access token may have expired.")
    print("The library should auto-refresh using the refresh_token in oauth2.json.")
    print("If refresh also fails, you need to re-authorize:")
    print("  Delete app/oauth2.json, restore consumer_key/secret, and re-run.")
    sys.exit(1)

print()
print("SUCCESS - Yahoo API connection is working!")
