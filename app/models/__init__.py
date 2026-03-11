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

    yahoo_id = Column(String, primary_key=True)
    gsis_id = Column(String, unique=True, nullable=True)
    full_name = Column(String, nullable=False)
    match_confidence = Column(Float, nullable=False, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)


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
    pick_timestamp = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_draft_team", "team_id"),
        Index("ix_draft_pick", "overall_pick"),
    )


class WaiverWireAvailability(Base):
    __tablename__ = "waiver_wire_availability"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, nullable=False)
    week = Column(Integer, nullable=False)
    ownership_percentage = Column(Integer, nullable=False, default=0)
    is_on_waivers = Column(Boolean, nullable=False, default=True)
    last_drop_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_waivers_player_week", "player_id", "week"),
        Index("ix_waivers_week", "week"),
    )


class RegretMetric(Base):
    __tablename__ = "regret_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(String, nullable=False)
    metric_type = Column(String, nullable=False)
    week = Column(Integer, nullable=True)
    regret_score = Column(Float, nullable=False)
    data_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_regret_team_type", "team_id", "metric_type"),
        Index("ix_regret_week", "week"),
    )
