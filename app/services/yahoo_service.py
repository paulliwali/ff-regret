import logging
from pathlib import Path

from yahoo_oauth import OAuth2
from yahoo_fantasy_api import game, league
from app.config import settings
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

TOKEN_FILE = Path(__file__).parent.parent / "oauth2.json"


class YahooFantasyService:
    def __init__(self):
        self._oauth = None
        self._game = None
        self._league = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate using yahoo_oauth's file-based token management.

        The oauth2.json file stores consumer_key, consumer_secret,
        access_token, refresh_token, and token_time. The library
        handles token refresh automatically.
        """
        if not TOKEN_FILE.exists():
            raise ValueError(
                f"Token file not found: {TOKEN_FILE}. "
                "Run: uv run python scripts/setup_yahoo_auth.py"
            )

        # yahoo_oauth handles everything: loading, validation, refresh, re-auth
        self._oauth = OAuth2(None, None, from_file=str(TOKEN_FILE))

        if not self._oauth.token_is_valid():
            logger.info("Token expired, refreshing...")
            self._oauth.refresh_access_token()

        # Game takes (oauth_session, sport_code)
        self._game = game.Game(self._oauth, "nfl")
        logger.info("Yahoo Fantasy API connection established")

    def get_league(self) -> league.League:
        league_key = self._get_league_key()
        return self._game.to_league(league_key)

    def _get_league_key(self) -> str:
        """Build the Yahoo league key: {game_key}.l.{league_id}"""
        gid = self._game.game_id()
        return f"{gid}.l.{settings.yahoo_league_id}"

    def fetch_league_config(self) -> Dict[str, Any]:
        lg = self.get_league()
        settings_data = lg.settings()

        return {
            "scoring_config": {
                "stat_modifiers": settings_data.get("stat_modifiers", {}),
                "stat_categories": lg.stat_categories(),
                "uses_fractional_points": settings_data.get("uses_fractional_points", "0") == "1",
                "uses_negative_points": settings_data.get("uses_negative_points", "0") == "1",
            },
            "roster_requirements": settings_data.get("roster_positions", {}),
        }

    def fetch_draft_results(self) -> List[Dict[str, Any]]:
        lg = self.get_league()
        draft_results = lg.draft_results()

        formatted = []
        for result in draft_results:
            formatted.append({
                "team_id": result["team_key"],
                "overall_pick": result.get("pick", 0),
                "round": result["round"],
                "player_id": result["player_id"],
                "pick_timestamp": result.get("timestamp"),
            })
        return formatted

    def fetch_weekly_rosters(self, week: int) -> Dict[str, List[Dict[str, Any]]]:
        lg = self.get_league()
        teams = lg.teams()

        rosters = {}
        for team_key, team_info in teams.items():
            roster_data = lg.to_team(team_key).roster(week=week)
            players = []

            for player in roster_data:
                players.append({
                    "player_id": player["player_id"],
                    "name": player["name"],
                    "position": player.get("eligible_positions", ["UNK"])[0],
                    "eligible_positions": player.get("eligible_positions", ["UNK"]),
                    "selected_position": player.get("selected_position", "BN"),
                    "is_starter": player.get("selected_position", "BN") != "BN",
                })

            rosters[team_key] = players
        return rosters

    def fetch_all_weekly_rosters(self) -> Dict[int, Dict[str, List[Dict[str, Any]]]]:
        lg = self.get_league()
        end_week = lg.end_week()

        all_rosters = {}
        for week in range(1, end_week + 1):
            logger.info(f"Fetching rosters for week {week}")
            all_rosters[week] = self.fetch_weekly_rosters(week)
        return all_rosters

    def fetch_waiver_wire_availability(self, week: int) -> List[Dict[str, Any]]:
        lg = self.get_league()
        waivers = lg.waivers()
        
        availability = []
        for player in waivers:
            availability.append({
                "player_id": player["player_id"],
                "name": player["name"],
                "week": week,
                "ownership_percentage": player.get("percent_owned", 0),
                "is_on_waivers": player.get("status", "") == "W",
            })
        return availability
