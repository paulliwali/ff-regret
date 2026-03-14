from sqlalchemy import Column, String, Integer, Float, JSON, Boolean, DateTime, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class LeagueConfig(Base):
    __tablename__ = "league_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scoring_config = Column(JSON, nullable=False)
    roster_requirements = Column(JSON, nullable=False)
    season_year = Column(Integer, nullable=False, default=2025)
    created_at = Column(DateTime, default=datetime.utcnow)


class PlayerMap(Base):
    __tablename__ = "player_map"

    id = Column(Integer, primary_key=True, autoincrement=True)
    yahoo_id = Column(String, nullable=False)
    gsis_id = Column(String, nullable=True)
    full_name = Column(String, nullable=False)
    position = Column(String, nullable=True)
    season_year = Column(Integer, nullable=False, default=2025)
    match_confidence = Column(Float, nullable=False, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_player_map_yahoo_id", "yahoo_id"),
        Index("ix_player_map_season", "season_year"),
    )


class NflGameLog(Base):
    __tablename__ = "nfl_game_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, nullable=False)
    week = Column(Integer, nullable=False)
    season_year = Column(Integer, nullable=False, default=2025)
    fantasy_points = Column(Float, nullable=False)
    status = Column(String, nullable=True)
    raw_stats = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_game_logs_player_week", "player_id", "week"),
        Index("ix_game_logs_week", "week"),
        Index("ix_game_logs_season", "season_year"),
    )


class LeagueWeeklyRoster(Base):
    __tablename__ = "league_weekly_rosters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(String, nullable=False)
    week = Column(Integer, nullable=False)
    season_year = Column(Integer, nullable=False, default=2025)
    roster_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_rosters_team_week", "team_id", "week"),
    )


class LeagueDraftResult(Base):
    __tablename__ = "league_draft_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(String, nullable=False)
    overall_pick = Column(Integer, nullable=False)
    round = Column(Integer, nullable=False)
    player_id = Column(String, nullable=False)
    season_year = Column(Integer, nullable=False, default=2025)
    pick_timestamp = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_draft_team", "team_id"),
        Index("ix_draft_pick", "overall_pick"),
        Index("ix_draft_season", "season_year"),
    )


class WaiverWireAvailability(Base):
    __tablename__ = "waiver_wire_availability"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, nullable=False)
    week = Column(Integer, nullable=False)
    season_year = Column(Integer, nullable=False, default=2025)
    ownership_percentage = Column(Integer, nullable=False, default=0)
    is_on_waivers = Column(Boolean, nullable=False, default=True)
    last_drop_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_waivers_player_week", "player_id", "week"),
        Index("ix_waivers_week", "week"),
        Index("ix_waivers_season", "season_year"),
    )


class LeagueMatchup(Base):
    __tablename__ = "league_matchups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(String, nullable=False)
    week = Column(Integer, nullable=False)
    season_year = Column(Integer, nullable=False, default=2025)
    opponent_id = Column(String, nullable=False)
    team_score = Column(Float, nullable=False, default=0.0)
    opponent_score = Column(Float, nullable=False, default=0.0)
    is_win = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_matchups_team_week", "team_id", "week"),
        Index("ix_matchups_season", "season_year"),
    )


class RegretMetric(Base):
    __tablename__ = "regret_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(String, nullable=False)
    metric_type = Column(String, nullable=False)
    week = Column(Integer, nullable=True)
    season_year = Column(Integer, nullable=False, default=2025)
    regret_score = Column(Float, nullable=False)
    data_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_regret_team_type", "team_id", "metric_type"),
        Index("ix_regret_week", "week"),
        Index("ix_regret_season", "season_year"),
    )
