import logging
import time
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

    def get_league_by_key(self, league_key: str) -> league.League:
        """Access a specific league by its full key (e.g. '449.l.776116')."""
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

    def fetch_teams(self) -> Dict[str, str]:
        """Return a mapping of team_key -> team_name."""
        lg = self.get_league()
        teams = lg.teams()
        return {key: info["name"] for key, info in teams.items()}

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

    def fetch_player_stats_weekly(
        self, lg: league.League, player_ids: List[int], week: int
    ) -> List[Dict[str, Any]]:
        """Fetch weekly stats for a list of players.

        Uses lg.player_stats() which returns total_points as calculated
        by Yahoo's scoring engine — the exact number managers see.

        :param player_ids: Numeric Yahoo player IDs (the library builds keys internally)
        """
        if not player_ids:
            return []

        try:
            # player_stats() expects list(int), handles batching + key building
            stats = lg.player_stats(player_ids, "week", week=week)
        except Exception as e:
            logger.warning(f"Failed to fetch stats for week {week}: {e}")
            return []

        results = []
        for player_stat in stats:
            results.append({
                "player_id": player_stat.get("player_id", ""),
                "name": player_stat.get("name", ""),
                "total_points": float(player_stat.get("total_points", 0)),
                "stats": player_stat,
            })
        return results

    def fetch_matchups(
        self, lg: league.League, week: int
    ) -> List[Dict[str, Any]]:
        """Fetch matchup results for a given week.

        The raw scoreboard JSON is deeply nested:
        fantasy_content.league[1].scoreboard.0.matchups.{N}.matchup.0.teams.{0,1}.team
        Each team entry is [list_of_meta, {team_points: {total: "X"}}].
        """
        try:
            raw = lg.matchups(week=week)
        except Exception as e:
            logger.warning(f"Failed to fetch matchups for week {week}: {e}")
            return []

        matchups = []
        if not raw:
            return matchups

        try:
            scoreboard = raw["fantasy_content"]["league"][1]["scoreboard"]
            matchups_container = scoreboard["0"]["matchups"]
        except (KeyError, IndexError, TypeError):
            logger.warning(f"Unexpected matchup format for week {week}")
            return matchups

        # Iterate numeric keys: "0", "1", "2", ...
        idx = 0
        while str(idx) in matchups_container:
            matchup = matchups_container[str(idx)].get("matchup", {})
            teams_data = matchup.get("0", {}).get("teams", {})

            team_entries = []
            for ti in range(2):
                team_raw = teams_data.get(str(ti), {}).get("team", [])
                if len(team_raw) < 2:
                    continue
                # team_raw[0] is a list of meta dicts, team_raw[1] has points
                meta_list = team_raw[0] if isinstance(team_raw[0], list) else []
                team_key = ""
                for item in meta_list:
                    if isinstance(item, dict) and "team_key" in item:
                        team_key = item["team_key"]
                        break
                points_info = team_raw[1] if len(team_raw) > 1 else {}
                total = float(
                    points_info.get("team_points", {}).get("total", 0)
                )
                team_entries.append({"key": team_key, "points": total})

            if len(team_entries) == 2:
                matchups.append({
                    "team1_key": team_entries[0]["key"],
                    "team1_score": team_entries[0]["points"],
                    "team2_key": team_entries[1]["key"],
                    "team2_score": team_entries[1]["points"],
                })

            idx += 1

        return matchups
