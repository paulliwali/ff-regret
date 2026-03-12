"""Fetch team names from Yahoo and save to a JSON file."""

import json
from pathlib import Path
from app.services.yahoo_service import YahooFantasyService

TEAM_NAMES_FILE = Path(__file__).parent.parent / "app" / "team_names.json"


def main():
    service = YahooFantasyService()
    teams = service.fetch_teams()
    TEAM_NAMES_FILE.write_text(json.dumps(teams, indent=2))
    print(f"Saved {len(teams)} team names to {TEAM_NAMES_FILE}")
    for key, name in teams.items():
        print(f"  {key}: {name}")


if __name__ == "__main__":
    main()
