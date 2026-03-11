import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import async_session
from app.models import WaiverWireAvailability
from app.services.yahoo_service import YahooFantasyService
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting waiver wire data fetch")
    
    async with async_session() as session:
        try:
            yahoo_service = YahooFantasyService()
            lg = yahoo_service.get_league()
            end_week = lg.end_week()
            
            logger.info(f"Fetching waiver wire data for weeks 1-{end_week}")
            
            for week in range(1, end_week + 1):
                logger.info(f"Fetching week {week}")
                
                availability_data = yahoo_service.fetch_waiver_wire_availability(week)
                
                batch = []
                for player_data in availability_data:
                    availability = WaiverWireAvailability(
                        player_id=player_data["player_id"],
                        week=player_data["week"],
                        ownership_percentage=int(player_data.get("ownership_percentage", 0) or 0),
                        is_on_waivers=player_data.get("is_on_waivers", False),
                    )
                    batch.append(availability)
                
                session.add_all(batch)
                await session.commit()
                logger.info(f"Stored {len(batch)} waiver wire records for week {week}")
            
            logger.info("Waiver wire data fetch complete!")
            
        except Exception as e:
            logger.error(f"Error during waiver wire fetch: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
