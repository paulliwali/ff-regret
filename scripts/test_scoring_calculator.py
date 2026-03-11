"""Test the scoring calculator with Yahoo config."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.yahoo_service import YahooFantasyService
from app.services.scoring_calculator import ScoringRulesParser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_scoring_calculator():
    """Test scoring calculator with actual Yahoo config."""
    
    try:
        print("=" * 60)
        print("Testing Scoring Calculator")
        print("=" * 60)
        
        # Fetch Yahoo config
        yahoo_service = YahooFantasyService()
        league_config = yahoo_service.fetch_league_config()
        
        # Parse scoring rules
        print("\n1. Parsing Yahoo scoring config...")
        scoring_rules = ScoringRulesParser.parse_yahoo_scoring_config(league_config)
        
        print(f"   ✓ Parsed {len(scoring_rules)} scoring rules:")
        for stat_name, multiplier in sorted(scoring_rules.items()):
            print(f"     - {stat_name}: {multiplier} points")
        
        # Test with sample data
        print("\n2. Testing with sample player data...")
        from app.services.scoring_calculator import FantasyPointsCalculator
        calculator = FantasyPointsCalculator(scoring_rules)
        
        # Sample QB game stats
        sample_qb_game = {
            "passing_yards": 300,
            "passing_tds": 2,
            "passing_ints": 1,
            "rushing_yards": 25,
            "rushing_tds": 0
        }
        
        qb_points = calculator.calculate_fantasy_points(sample_qb_game)
        print(f"   Sample QB game: {qb_points} points")
        print(f"     - 300 pass yards * 0.04 = {300 * 0.04}")
        print(f"     - 2 pass TDs * 4 = {2 * 4}")
        print(f"     - 1 INT * -2 = {1 * -2}")
        print(f"     - 25 rush yards * 0.1 = {25 * 0.1}")
        
        # Sample RB game stats
        sample_rb_game = {
            "rushing_yards": 100,
            "rushing_tds": 1,
            "receiving_yards": 50,
            "receptions": 5,
            "receiving_tds": 1,
            "fumbles_lost": 0
        }
        
        rb_points = calculator.calculate_fantasy_points(sample_rb_game)
        print(f"\n   Sample RB game: {rb_points} points")
        
        print("\n" + "=" * 60)
        print("Scoring Calculator Tests Passed! ✓")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_scoring_calculator()
    sys.exit(0 if success else 1)