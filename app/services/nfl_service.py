import nfl_data_py as nfl
import polars as pl
from app.config import settings
from app.services.scoring_calculator import ScoringRulesParser, FantasyPointsCalculator
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class NFLDataService:
    def __init__(self, season_year: int = None, scoring_rules: Dict[str, float] = None):
        self.season_year = season_year if season_year is not None else settings.season_year
        self.scoring_rules = scoring_rules or {}
        self.calculator = None
        
        if self.scoring_rules:
            self.calculator = FantasyPointsCalculator(self.scoring_rules)
        logger.info(f"Updated scoring rules with {len(self.scoring_rules)} categories")

    def fetch_weekly_game_logs(self) -> pl.DataFrame:
        logger.info(f"Fetching NFL game logs for season {self.season_year}")

        try:
            df = nfl.import_weekly_data([self.season_year])
            
            if df is None or len(df) == 0:
                logger.warning(f"No game logs found for season {self.season_year}")
                return pl.DataFrame()

            df_pl = pl.from_pandas(df)
            logger.info(f"Fetched {len(df_pl)} game logs")

            return df_pl
        except Exception as e:
            logger.error(f"Error fetching game logs: {e}")
            return pl.DataFrame()

    def fetch_player_ids(self) -> pl.DataFrame:
        logger.info("Fetching NFL player ID mapping")

        try:
            df = nfl.import_ids()

            if df is None or len(df) == 0:
                logger.warning("No player ID mappings found")
                return pl.DataFrame()

            df_pl = pl.from_pandas(df)
            logger.info(f"Fetched {len(df_pl)} player ID mappings")

            return df_pl

        except Exception as e:
            logger.error(f"Error fetching player IDs: {e}")
            return pl.DataFrame()

    def fetch_roster_data(self) -> pl.DataFrame:
        logger.info(f"Fetching NFL roster data for season {self.season_year}")

        try:
            df = nfl.import_weekly_rosters([self.season_year])

            if df is None or len(df) == 0:
                logger.warning(f"No roster data found for season {self.season_year}")
                return pl.DataFrame()

            df_pl = pl.from_pandas(df)
            logger.info(f"Fetched {len(df_pl)} roster records")

            return df_pl

        except Exception as e:
            logger.error(f"Error fetching roster data: {e}")
            return pl.DataFrame()

    def filter_game_logs_by_player_id(self, game_logs: pl.DataFrame, player_id: str) -> pl.DataFrame:
        return game_logs.filter(pl.col("gsis_id") == player_id)

    def get_player_weekly_points(self, game_logs: pl.DataFrame, player_id: str) -> Dict[int, float]:
        if not self.calculator:
            logger.warning("No scoring rules set, returning empty dict")
            return {}

        player_logs = self.filter_game_logs_by_player_id(game_logs, player_id)

        weekly_points = {}
        for row in player_logs.iter_rows(named=True):
            week = row.get("week")
            points = self.calculator.calculate_fantasy_points(row)
            weekly_points[week] = points

        return weekly_points

    def calculate_fantasy_points(self, row: Dict[str, Any]) -> float:
        """Calculate fantasy points for a single game row."""
        if not self.calculator:
            logger.warning("No scoring rules set, returning 0.0")
            return 0.0
            
        return self.calculator.calculate_fantasy_points(row)
