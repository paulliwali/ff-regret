"""Test script to verify Yahoo Fantasy API data fetching functionality."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.yahoo_service import YahooFantasyService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_yahoo_service():
    """Test all Yahoo Fantasy API data fetching methods."""
    
    try:
        print("=" * 60)
        print("Testing Yahoo Fantasy Service")
        print("=" * 60)
        
        service = YahooFantasyService()
        
        # Test 1: League configuration
        print("\n1. Fetching league configuration...")
        league_config = service.fetch_league_config()
        print(f"   ✓ League config fetched")
        scoring_config = league_config.get('scoring_config', {})
        stat_modifiers = scoring_config.get('stat_modifiers', {}).get('stats', [])
        print(f"   - Scoring modifiers: {len(stat_modifiers)} stats")
        print(f"   - Stat categories: {len(scoring_config.get('stat_categories', []))}")
        print(f"   - Uses fractional points: {scoring_config.get('uses_fractional_points', False)}")
        print(f"   - Uses negative points: {scoring_config.get('uses_negative_points', False)}")
        print(f"   - Roster positions: {len(league_config.get('roster_requirements', {}))}")
        
        # Test 2: Draft results
        print("\n2. Fetching draft results...")
        draft_results = service.fetch_draft_results()
        print(f"   ✓ Draft results fetched: {len(draft_results)} picks")
        if draft_results:
            print(f"   - First pick: {draft_results[0].get('player_id', 'Unknown')}")
        
        # Test 3: Weekly rosters (test week 1)
        print("\n3. Fetching weekly rosters...")
        weekly_roster = service.fetch_weekly_rosters(week=1)
        print(f"   ✓ Week 1 rosters fetched: {len(weekly_roster)} teams")
        if weekly_roster:
            first_team_id = list(weekly_roster.keys())[0]
            print(f"   - First team: {first_team_id}")
            print(f"   - Team roster size: {len(weekly_roster[first_team_id])} players")
        
        # Test 4: All weekly rosters
        print("\n4. Fetching all weekly rosters...")
        all_rosters = service.fetch_all_weekly_rosters()
        print(f"   ✓ All weekly rosters fetched: {len(all_rosters)} weeks")
        
        # Test 5: Waiver wire availability
        print("\n5. Fetching waiver wire availability...")
        waiver_data = service.fetch_waiver_wire_availability(week=1)
        print(f"   ✓ Week 1 waiver data fetched: {len(waiver_data)} players")
        if waiver_data:
            print(f"   - Sample player: {waiver_data[0].get('name', 'Unknown')} ({waiver_data[0].get('player_id', 'Unknown')})")
        
        print("\n" + "=" * 60)
        print("All Yahoo Fantasy API tests passed! ✓")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_yahoo_service()
    sys.exit(0 if success else 1)