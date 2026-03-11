"""Examine Yahoo API scoring configuration in detail."""

import logging
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.yahoo_service import YahooFantasyService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def examine_scoring_config():
    """Examine scoring configuration from Yahoo API."""
    
    try:
        service = YahooFantasyService()
        lg = service.get_league()
        
        settings_data = lg.settings()
        
        print("=" * 60)
        print("Yahoo Scoring Configuration")
        print("=" * 60)
        
        # Check stat_modifiers
        print("\n1. Stat Modifiers:")
        if "stat_modifiers" in settings_data:
            stat_modifiers = settings_data["stat_modifiers"]
            print("Type:", type(stat_modifiers))
            if isinstance(stat_modifiers, dict):
                print("Keys:", list(stat_modifiers.keys()))
                if "stats" in stat_modifiers:
                    stats = stat_modifiers["stats"]
                    print("Number of stats:", len(stats))
                    print("\nStat modifiers:")
                    for stat in stats[:10]:  # Show first 10
                        print(f"  {json.dumps(stat, indent=4)}")
                elif "stat" in stat_modifiers:
                    # Alternative structure
                    stat = stat_modifiers["stat"]
                    print("Stat structure:", type(stat))
                    if isinstance(stat, list):
                        print("Number of stats:", len(stat))
                        print("\nStat modifiers:")
                        for s in stat[:10]:  # Show first 10
                            print(f"  {json.dumps(s, indent=4)}")
        
        # Try alternative method: league.settings() with different approach
        print("\n2. League Settings Full Structure (scoring-related keys):")
        scoring_related_keys = [
            'stat_modifiers', 'scoring_type', 'stat_categories', 
            'uses_fractional_points', 'uses_negative_points'
        ]
        for key in scoring_related_keys:
            if key in settings_data:
                print(f"\n{key}:")
                print(json.dumps(settings_data[key], indent=2, default=str))
        
        # Try league.stat_categories() method if it exists
        print("\n3. Trying league.stat_categories() method:")
        try:
            if hasattr(lg, 'stat_categories'):
                stat_cats = lg.stat_categories()
                print("Stat categories:", json.dumps(stat_cats, indent=2, default=str))
            else:
                print("Method doesn't exist")
        except Exception as e:
            print(f"Error: {e}")
        
        print("\n" + "=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    examine_scoring_config()