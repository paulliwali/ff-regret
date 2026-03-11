"""Debug script to examine Yahoo API response structure."""

import logging
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.yahoo_service import YahooFantasyService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def debug_yahoo_api_structure():
    """Examine the raw structure of Yahoo API responses."""
    
    try:
        service = YahooFantasyService()
        lg = service.get_league()
        
        print("=" * 60)
        print("Examining Yahoo API Structure")
        print("=" * 60)
        
        # Test league settings structure
        print("\n1. League Settings Structure:")
        settings_data = lg.settings()
        print("Keys:", list(settings_data.keys()))
        
        # Check scoring config
        if "stat_categories" in settings_data:
            stat_categories = settings_data["stat_categories"]
            print("stat_categories keys:", list(stat_categories.keys()) if isinstance(stat_categories, dict) else "Not a dict")
            if isinstance(stat_categories, dict) and "stats" in stat_categories:
                print("Number of stats:", len(stat_categories["stats"]))
                if stat_categories["stats"]:
                    print("First stat:", stat_categories["stats"][0])
        
        # Check roster positions
        if "roster_positions" in settings_data:
            roster_positions = settings_data["roster_positions"]
            print("roster_positions type:", type(roster_positions))
            if isinstance(roster_positions, dict):
                print("roster_positions keys:", list(roster_positions.keys()))
            elif isinstance(roster_positions, list):
                print("Number of roster positions:", len(roster_positions))
                if roster_positions:
                    print("First position:", roster_positions[0])
        
        # Test draft results structure
        print("\n2. Draft Results Structure:")
        draft_results = lg.draft_results()
        if draft_results:
            print("Number of picks:", len(draft_results))
            print("First pick keys:", list(draft_results[0].keys()))
            print("First pick:", json.dumps(draft_results[0], indent=2, default=str))
        
        # Test free agents structure
        print("\n3. Free Agents Structure:")
        free_agents = lg.free_agents("ALL")
        print("Number of free agents:", len(free_agents))
        if free_agents:
            print("First agent keys:", list(free_agents[0].keys()))
            print("First agent:", json.dumps(free_agents[0], indent=2, default=str))
        
        # Test roster structure
        print("\n4. Roster Structure:")
        teams = lg.teams()
        first_team_key = list(teams.keys())[0]
        team_roster = lg.to_team(first_team_key).roster(week=1)
        print("Number of players:", len(team_roster))
        if team_roster:
            print("First player keys:", list(team_roster[0].keys()))
            print("First player:", json.dumps(team_roster[0], indent=2, default=str))
        
        print("\n" + "=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error during debugging: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    debug_yahoo_api_structure()