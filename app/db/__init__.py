import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models import Base
from app.config import settings

logger = logging.getLogger(__name__)

engine = None
async_session = None


def _init_engine():
    global engine, async_session
    if engine is None:
        url = settings.async_database_url
        logger.info(f"Connecting to database: {url[:30]}...")
        engine = create_async_engine(url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    _init_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


async def get_db() -> AsyncSession:
    _init_engine()
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
