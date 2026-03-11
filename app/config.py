from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/ff_regret"

    yahoo_consumer_key: str = ""
    yahoo_consumer_secret: str = ""
    yahoo_access_token: str = ""
    yahoo_access_token_secret: str = ""
    yahoo_refresh_token: str = ""
    yahoo_league_id: str = ""
    yahoo_game_id: str = "nfl"

    season_year: int = 2025

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
