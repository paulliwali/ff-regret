import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models import Base
from app.config import settings

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None


def _init_engine():
    global _engine, _session_factory
    if _engine is None:
        url = settings.async_database_url
        logger.info(f"Connecting to database: {url[:30]}...")
        _engine = create_async_engine(url, echo=False)
        _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


def async_session():
    _init_engine()
    return _session_factory()


async def init_db():
    _init_engine()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
