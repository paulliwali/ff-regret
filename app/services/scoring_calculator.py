import logging
from typing import Dict, List, Any, Optional
import polars as pl

logger = logging.getLogger(__name__)


class ScoringRulesParser:
    """Parse Yahoo Fantasy scoring configuration into usable scoring rules."""

    # Yahoo stat ID to NFL data column mapping
    # Verified against league scoring page 2024-03-12
    YAHOO_TO_NFL_MAP = {
        # Passing
        4: ("passing_yards", 0.04),             # Pass Yards (25 yds/pt)
        5: ("passing_tds", 4.0),                # Pass TDs
        6: ("interceptions", -2.0),             # Interceptions Thrown

        # Rushing
        9: ("rushing_yards", 0.1),              # Rush Yards (10 yds/pt)
        10: ("rushing_tds", 6.0),               # Rush TDs
        56: ("rushing_fumbles", -2.0),          # Rushing Fumbles

        # Receiving
        11: ("receptions", 0.5),                # Receptions (half PPR)
        12: ("receiving_yards", 0.1),           # Rec Yards (10 yds/pt)
        13: ("receiving_tds", 6.0),             # Rec TDs

        # General offense
        15: ("return_tds", 6.0),                # Return TDs (offense)
        16: ("two_point_conversions", 2.0),     # 2-Point Conversions
        18: ("fumbles_lost", -2.0),             # Fumbles Lost
        57: ("off_fumble_ret_tds", 6.0),        # Offensive Fumble Return TD

        # Kicking - FG Made
        19: ("kicking_fgm_0_19", 3.0),         # FG Made 0-19
        20: ("kicking_fgm_20_29", 3.0),        # FG Made 20-29
        21: ("kicking_fgm_30_39", 3.0),        # FG Made 30-39
        22: ("kicking_fgm_40_49", 4.0),        # FG Made 40-49
        23: ("kicking_fgm_50_plus", 5.0),      # FG Made 50+

        # Kicking - FG Missed (by distance)
        24: ("kicking_fgmiss_0_19", -1.0),     # FG Missed 0-19
        25: ("kicking_fgmiss_20_29", -1.0),    # FG Missed 20-29
        26: ("kicking_fgmiss_30_39", -1.0),    # FG Missed 30-39
        27: ("kicking_fgmiss_40_49", -1.0),    # FG Missed 40-49

        # Kicking - PAT
        29: ("kicking_xpm", 1.0),               # PAT Made
        30: ("kicking_xpmiss", -1.0),           # PAT Missed

        # Defense
        32: ("def_sacks", 1.0),                 # Sacks
        33: ("def_interceptions", 2.0),         # Interceptions
        34: ("def_fumbles_recovered", 2.0),     # Fumbles Recovered
        35: ("def_tds", 6.0),                   # Defensive TDs
        36: ("def_safeties", 2.0),              # Safeties
        37: ("def_blocked_kicks", 2.0),         # Blocked Kicks
        49: ("def_ret_tds", 6.0),               # Return TDs (defense)

        # Defense points allowed
        50: ("def_pts_allow_0", 10.0),          # Points Allowed 0
        51: ("def_pts_allow_1_6", 7.0),         # Points Allowed 1-6
        52: ("def_pts_allow_7_13", 4.0),        # Points Allowed 7-13
        53: ("def_pts_allow_14_20", 1.0),       # Points Allowed 14-20
        54: ("def_pts_allow_21_27", 0.0),       # Points Allowed 21-27
        55: ("def_pts_allow_28_34", -1.0),      # Points Allowed 28-34
        82: ("def_pts_allow_35_plus", -4.0),    # Points Allowed 35+
    }

    @staticmethod
    def parse_yahoo_scoring_config(yahoo_config: Dict[str, Any]) -> Dict[str, float]:
        """Parse Yahoo Fantasy scoring configuration into simple stat->multiplier dict.

        Args:
            yahoo_config: Yahoo league settings dict containing scoring config

        Returns:
            Dictionary mapping stat names to point multipliers
        """
        scoring_rules = {}
        
        # Get stat_modifiers which contains the scoring values
        scoring_config = yahoo_config.get("scoring_config", {})
        stat_modifiers = scoring_config.get("stat_modifiers", {})
        stats = stat_modifiers.get("stats", [])
        
        if not stats:
            logger.warning("No scoring stats found in Yahoo config, using defaults")
            return ScoringRulesParser._get_default_scoring_rules()
        
        logger.info(f"Parsing {len(stats)} scoring categories from Yahoo config")
        
        for stat_item in stats:
            stat = stat_item.get("stat", {})
            stat_id = stat.get("stat_id")
            value_str = stat.get("value", "0")
            
            # Convert value to float (Yahoo returns strings)
            try:
                value = float(value_str)
            except (ValueError, TypeError):
                logger.warning(f"Could not convert value '{value_str}' to float for stat_id {stat_id}")
                continue
            
            if stat_id in ScoringRulesParser.YAHOO_TO_NFL_MAP:
                stat_name, default_multiplier = ScoringRulesParser.YAHOO_TO_NFL_MAP[stat_id]
                # Use Yahoo's value if provided (not 0), otherwise use default
                scoring_rules[stat_name] = value if value != 0 else default_multiplier
                logger.debug(f"  {stat_name}: {scoring_rules[stat_name]} points")
            else:
                logger.debug(f"  Unknown stat_id: {stat_id}")
        
        if not scoring_rules:
            logger.warning("No valid scoring rules parsed, using defaults")
            return ScoringRulesParser._get_default_scoring_rules()
        
        return scoring_rules

    @staticmethod
    def _get_default_scoring_rules() -> Dict[str, float]:
        """Get default half-PPR scoring rules as fallback."""
        return {
            "passing_yards": 0.04,
            "passing_tds": 4.0,
            "interceptions": -2.0,
            "rushing_yards": 0.1,
            "rushing_tds": 6.0,
            "receiving_yards": 0.1,
            "receiving_tds": 6.0,
            "receptions": 0.5,
            "two_point_conversions": 2.0,
            "fumbles_lost": -2.0,
            "kicking_fgm_30_39": 3.0,
            "kicking_xpm": 1.0,
        }


class FantasyPointsCalculator:
    """Calculate fantasy points for NFL players using league-specific scoring rules."""

    def __init__(self, scoring_rules: Dict[str, float]):
        self.scoring_rules = scoring_rules
        logger.info(f"Initialized with {len(scoring_rules)} scoring rules")

    def calculate_fantasy_points(self, row: Dict[str, Any]) -> float:
        """Calculate fantasy points for a single game.

        Args:
            row: Dictionary containing player game stats

        Returns:
            Total fantasy points
        """
        points = 0.0
        
        for stat, multiplier in self.scoring_rules.items():
            value = self._get_stat_value(row, stat)
            if value is not None:
                points += float(value) * multiplier
        
        return round(points, 2)

    def _get_stat_value(self, row: Dict[str, Any], stat_name: str) -> Optional[float]:
        """Get stat value from row with various fallback strategies.

        Handles different column naming conventions between data sources.
        """
        # Direct lookup
        if stat_name in row:
            return float(row[stat_name])
        
        # Common variations (nfl_data_py column names differ from Yahoo stat names)
        variations = {
            "passing_yards": ["pass_yards", "passing_yd", "pass_yd"],
            "passing_tds": ["pass_tds", "passing_td", "pass_td"],
            "interceptions": ["passing_ints", "pass_ints", "passing_int"],
            "rushing_yards": ["rush_yards", "rushing_yd", "rush_yd"],
            "rushing_tds": ["rush_tds", "rushing_td", "rush_td"],
            "rushing_fumbles": ["rush_fumbles"],
            "receiving_yards": ["rec_yards", "receiving_yd", "rec_yd"],
            "receiving_tds": ["rec_tds", "receiving_td", "rec_td"],
            "receptions": ["rec"],
            "fumbles_lost": ["fumbles", "fum_lost"],
            "two_point_conversions": ["passing_2pt_conversions", "rushing_2pt_conversions"],
        }
        
        if stat_name in variations:
            for variation in variations[stat_name]:
                if variation in row:
                    return float(row[variation])
        
        return None

    def calculate_season_points(self, game_logs: pl.DataFrame) -> float:
        """Calculate total fantasy points for a season.

        Args:
            game_logs: DataFrame of player's game logs for the season

        Returns:
            Total fantasy points for the season
        """
        total_points = 0.0
        
        for row in game_logs.iter_rows(named=True):
            points = self.calculate_fantasy_points(row)
            total_points += points
        
        return round(total_points, 2)

    def calculate_weekly_points(self, game_logs: pl.DataFrame) -> Dict[int, float]:
        """Calculate fantasy points for each week.

        Args:
            game_logs: DataFrame of player's game logs

        Returns:
            Dictionary mapping week number to fantasy points
        """
        weekly_points = {}
        
        for row in game_logs.iter_rows(named=True):
            week = row.get("week", 1)
            points = self.calculate_fantasy_points(row)
            weekly_points[week] = points
        
        return weekly_points