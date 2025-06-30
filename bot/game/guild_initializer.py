from bot.database.database import get_db
from bot.database import crud_utils as crud
from bot.database import models
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

async def initialize_new_guild(db_session: AsyncSession, guild_id: str, force_reinitialize: bool = False) -> bool:
    """
    Initializes a new guild with default configurations, rules, and basic world data.
    """
    logger.info(f"Attempting to initialize guild: {guild_id}, Force: {force_reinitialize}")

    try:
        existing_config = await crud.get_entity_by_pk_async(db_session, models.GuildConfig, guild_id)
        if existing_config and not force_reinitialize:
            logger.info(f"Guild {guild_id} already initialized and force_reinitialize is false. Skipping.")
            return True

        if existing_config and force_reinitialize:
            logger.info(f"Force re-initializing guild {guild_id}.")

        guild_config_data = {"guild_id": guild_id, "bot_language": "en", "game_channel_id": "12345"}
        await crud.upsert_entity_async(db_session, models.GuildConfig, guild_config_data, pk_column_name="guild_id")
        logger.info(f"GuildConfig ensured for guild {guild_id}")

        # This is a placeholder for loading static data.
        # In a real application, this would be more robust.
        try:
            with open('data/locations.json') as f:
                locations = json.load(f)
            for loc_data in locations:
                loc_data['guild_id'] = guild_id
                await crud.upsert_entity_async(db_session, models.Location, loc_data, pk_column_name="static_id")
        except FileNotFoundError:
            logger.warning("data/locations.json not found, skipping static location loading.")

        await db_session.commit()
        logger.info(f"Guild {guild_id} initialization process completed and committed.")
        return True

    except IntegrityError as e:
        await db_session.rollback()
        logger.error(f"IntegrityError during guild initialization: {guild_id}. Error: {e}")
        raise
    except Exception as e:
        await db_session.rollback()
        logger.exception(f"Unexpected error during guild initialization: {guild_id}. Error: {e}")
        raise
