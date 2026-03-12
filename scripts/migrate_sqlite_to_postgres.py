"""Migrate all data from local SQLite to Railway Postgres.

Usage:
    DATABASE_URL="postgresql+asyncpg://..." uv run python scripts/migrate_sqlite_to_postgres.py
"""

import asyncio
import logging
import sqlite3
from datetime import datetime

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session, init_db
from app.models import (
    LeagueConfig,
    LeagueDraftResult,
    LeagueWeeklyRoster,
    NflGameLog,
    PlayerMap,
    RegretMetric,
    WaiverWireAvailability,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SQLITE_PATH = "ff_regret.db"

# Ordered so we can clear in reverse (respecting any future FK constraints)
TABLES = [
    ("regret_metrics", RegretMetric),
    ("nfl_game_logs", NflGameLog),
    ("player_map", PlayerMap),
    ("waiver_wire_availability", WaiverWireAvailability),
    ("league_weekly_rosters", LeagueWeeklyRoster),
    ("league_draft_results", LeagueDraftResult),
    ("league_config", LeagueConfig),
]


def read_sqlite_table(table_name: str) -> tuple[list[str], list[tuple]]:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    columns = rows[0].keys() if rows else []
    data = [dict(row) for row in rows]
    conn.close()
    return columns, data


def coerce_str(value) -> str:
    """Ensure value is a string (handles int player IDs from SQLite)."""
    return str(value) if value is not None else None


def parse_json(value):
    """Parse JSON string from SQLite into Python object."""
    import json
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def parse_datetime(value):
    """Parse datetime string from SQLite."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def migrate_table(session: AsyncSession, table_name: str, model_class, columns, rows):
    """Clear target table and insert all rows."""
    await session.execute(delete(model_class))
    await session.commit()

    logger.info(f"Migrating {table_name}: {len(rows)} rows")

    if not rows:
        return

    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        for row in batch:
            # Remove 'id' — let Postgres generate it
            row.pop("id", None)

            # Coerce types based on table
            if table_name == "league_draft_results":
                row["player_id"] = coerce_str(row.get("player_id"))
                row["team_id"] = coerce_str(row.get("team_id"))
                row["pick_timestamp"] = parse_datetime(row.get("pick_timestamp"))
                row["created_at"] = parse_datetime(row.get("created_at"))

            elif table_name == "player_map":
                row["yahoo_id"] = coerce_str(row.get("yahoo_id"))
                row["gsis_id"] = coerce_str(row.get("gsis_id"))
                row["created_at"] = parse_datetime(row.get("created_at"))

            elif table_name == "nfl_game_logs":
                row["raw_stats"] = parse_json(row.get("raw_stats"))
                row["created_at"] = parse_datetime(row.get("created_at"))

            elif table_name == "league_weekly_rosters":
                row["team_id"] = coerce_str(row.get("team_id"))
                row["roster_snapshot"] = parse_json(row.get("roster_snapshot"))
                row["created_at"] = parse_datetime(row.get("created_at"))

            elif table_name == "league_config":
                row["scoring_config"] = parse_json(row.get("scoring_config"))
                row["roster_requirements"] = parse_json(row.get("roster_requirements"))
                row["created_at"] = parse_datetime(row.get("created_at"))

            elif table_name == "waiver_wire_availability":
                row["player_id"] = coerce_str(row.get("player_id"))
                row["last_drop_date"] = parse_datetime(row.get("last_drop_date"))
                row["created_at"] = parse_datetime(row.get("created_at"))

            elif table_name == "regret_metrics":
                row["team_id"] = coerce_str(row.get("team_id"))
                row["data_payload"] = parse_json(row.get("data_payload"))
                row["created_at"] = parse_datetime(row.get("created_at"))

            obj = model_class(**row)
            session.add(obj)

        await session.commit()
        logger.info(f"  {table_name}: {min(i + batch_size, len(rows))}/{len(rows)}")


async def main():
    logger.info(f"Migrating from {SQLITE_PATH} to Postgres")
    logger.info(f"Target: {settings.async_database_url[:40]}...")

    await init_db()

    async with async_session() as session:
        for table_name, model_class in TABLES:
            try:
                columns, rows = read_sqlite_table(table_name)
                await migrate_table(session, table_name, model_class, columns, rows)
            except Exception as e:
                logger.error(f"Failed migrating {table_name}: {e}")
                import traceback
                traceback.print_exc()
                await session.rollback()
                raise

    logger.info("Migration complete!")


if __name__ == "__main__":
    asyncio.run(main())
