from bot.database.database import get_db_session # This likely needs to change for async
from bot.database import crud_utils as crud
from bot.database import models
import json
import logging # Added logging
from sqlalchemy.ext.asyncio import AsyncSession # Added for type hint
from sqlalchemy.exc import IntegrityError # Added for error handling

logger = logging.getLogger(__name__) # Added logger

# TODO: The function signature and implementation needs to be fully updated
# to match the async nature and parameters (db_session, guild_id, force_reinitialize)
# expected by the API router and tests.
# The current content is synchronous and uses a different way to get DB session.
# This is a temporary rename to fix the ImportError. Further work is needed here.

async def initialize_new_guild(db_session: AsyncSession, guild_id: str, force_reinitialize: bool = False) -> bool:
    """
    Initializes a new guild with default configurations, rules, and basic world data.
    This function is expected to be async and use the provided AsyncSession.
    The current implementation below is mostly a placeholder based on the old sync function
    and needs significant refactoring to be truly async and match expectations.
    """
    logger.info(f"Attempting to initialize guild: {guild_id}, Force: {force_reinitialize}")

    try:
        # Example: Check if GuildConfig already exists
        existing_config = await crud.get_entity_by_pk_async(db_session, models.GuildConfig, guild_id)
        if existing_config and not force_reinitialize:
            logger.info(f"Guild {guild_id} already initialized and force_reinitialize is false. Skipping full initialization.")
            # Optionally, ensure some defaults are present or updated if non-destructive
            # For now, just return True indicating it's "handled"
            return True

        if existing_config and force_reinitialize:
            logger.info(f"Force re-initializing guild {guild_id}. Existing data might be reset or cleared.")
            # TODO: Implement actual data clearing/resetting logic here if needed for force_reinitialize

        # Create GuildConfig if it doesn't exist or if forced
        # This uses a simplified version of what might be needed for an upsert or create_or_update
        guild_config_data = {"guild_id": guild_id, "bot_language": "en", "game_channel_id": "12345"} # Example game_channel_id
        await crud.upsert_entity_async(db_session, models.GuildConfig, guild_config_data, pk_column_name="guild_id")
        logger.info(f"GuildConfig ensured for guild {guild_id}")

        # Create static locations (example, needs to be async and use db_session)
        # This is a placeholder and needs to be made async and use the provided db_session
        # with open('data/locations.json') as f: # This is synchronous file I/O
        #     locations = json.load(f)
        # for loc_data in locations:
        #     # This crud.create_entity is not async and uses a different session manager
        #     # crud.create_entity(db, guild.id, models.Location, **loc_data)
        #     pass # Placeholder for async location creation
        logger.warning(f"Static location creation for guild {guild_id} is currently a placeholder and needs async implementation.")

        # TODO: Add logic for RulesConfig, WorldState, LocationTemplates, default Factions, Locations etc.
        # All these operations need to be asynchronous and use the passed `db_session`.

        await db_session.commit() # Commit at the end of successful operations
        logger.info(f"Guild {guild_id} initialization process completed and committed.")
        return True

    except IntegrityError as e:
        await db_session.rollback()
        logger.error(f"IntegrityError during guild initialization: {guild_id}. Error: {e}")
        # Re-raise if the caller should handle it, or return False if this function handles the logging/reporting.
        # For now, let's re-raise so the API can potentially return a 500.
        raise
    except Exception as e:
        await db_session.rollback()
        logger.exception(f"Unexpected error during guild initialization: {guild_id}. Error: {e}")
        # Re-raise or return False
        raise

# Old synchronous function, kept for reference during refactor, but should be removed.
# def initialize_guild_data(guild):
#     with get_db_session() as db: # This is synchronous session management
#         # Create GuildConfig
#         crud.create_entity(db, guild.id, models.GuildConfig, id=guild.id, main_language='en')

        # Create static locations
        with open('data/locations.json') as f:
            locations = json.load(f)
        for loc_data in locations:
            crud.create_entity(db, guild.id, models.Location, **loc_data)