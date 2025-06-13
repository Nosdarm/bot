# bot/game/guild_initializer.py
import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from bot.database.models import RulesConfig, GeneratedFaction, Location # Assuming GeneratedFaction is the current model for Factions

logger = logging.getLogger(__name__)

async def initialize_new_guild(db_session: AsyncSession, guild_id: str, force_reinitialize: bool = False):
    """
    Initializes a new guild with default data: RuleConfig, a default Faction, and a starting Location.
    Checks if RuleConfig already exists to prevent re-initialization unless force_reinitialize is True.
    """
    logger.info(f"Attempting to initialize guild_id: {guild_id}")

    # Check if RulesConfig already exists for this guild
    existing_rule_config_stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id)
    result = await db_session.execute(existing_rule_config_stmt)
    existing_rule_config = result.scalars().first()

    if existing_rule_config and not force_reinitialize:
        logger.warning(f"Guild {guild_id} already has a RuleConfig. Skipping initialization.")
        return False # Indicate that initialization was skipped

    try:
        # If forcing reinitialization, clear existing data that might conflict
        # For simplicity, this example only checks RulesConfig. A more robust solution
        # would delete existing related entities or handle conflicts more gracefully.
        # For now, we'll rely on primary key conflicts to stop if not forcing and data exists.

        # 1. Create Default RulesConfig
        default_rules_data = {
            "experience_rate": 1.0,
            "loot_drop_chance": 0.5,
            "combat_difficulty_modifier": 1.0,
            "default_language": "en",
            "command_prefixes": ["!"]
        }
        if existing_rule_config and force_reinitialize: # Update existing if forcing
            logger.info(f"Force reinitializing RuleConfig for guild {guild_id}.")
            existing_rule_config.config_data = default_rules_data
            db_session.add(existing_rule_config)
        elif not existing_rule_config:
            new_rule_config = RulesConfig(
                guild_id=guild_id,
                config_data=default_rules_data
            )
            db_session.add(new_rule_config)
            logger.info(f"Added default RuleConfig for guild {guild_id}.")

        # 2. Create Default GeneratedFaction (Faction)
        # Check if default faction exists or handle if force_reinitialize
        default_faction_id = f"default_faction_{str(uuid.uuid4())[:8]}" # Unique ID for faction

        existing_faction_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == guild_id, GeneratedFaction.name_i18n['en'].astext == "Neutral Observers")
        faction_result = await db_session.execute(existing_faction_stmt)
        existing_faction = faction_result.scalars().first()

        if not existing_faction or force_reinitialize:
            if existing_faction and force_reinitialize:
                logger.info(f"Force reinitializing default Faction for guild {guild_id}. Deleting old one first if names match.")
                # More complex logic might be needed if we don't want to delete by name
                await db_session.delete(existing_faction)
                await db_session.flush() # Ensure delete is processed before add

            default_faction = GeneratedFaction(
                id=default_faction_id,
                guild_id=guild_id,
                name_i18n={"en": "Neutral Observers", "ru": "Нейтральные Наблюдатели"},
                description_i18n={"en": "A neutral faction observing events.", "ru": "Нейтральная фракция, наблюдающая за событиями."}
            )
            db_session.add(default_faction)
            logger.info(f"Added default Faction '{default_faction_id}' for guild {guild_id}.")
        else:
            logger.info(f"Default faction already exists for guild {guild_id} and not forcing reinitialization.")

        # 3. Create Default Location (Starting Area)
        starting_location_id = f"starting_area_{str(uuid.uuid4())[:8]}" # Unique ID for location

        existing_location_stmt = select(Location).where(Location.guild_id == guild_id, Location.static_name == f"internal_starting_crossroads_{guild_id}")
        loc_result = await db_session.execute(existing_location_stmt)
        existing_location = loc_result.scalars().first()

        if not existing_location or force_reinitialize:
            if existing_location and force_reinitialize:
                logger.info(f"Force reinitializing starting Location for guild {guild_id}. Deleting old one first.")
                await db_session.delete(existing_location)
                await db_session.flush()

            starting_location = Location(
                id=starting_location_id,
                guild_id=guild_id,
                name_i18n={"en": "Quiet Crossroads", "ru": "Тихий Перекресток"},
                descriptions_i18n={"en": "A quiet crossroads, suitable for starting an adventure.", "ru": "Тихий перекресток, подходящий для начала приключения."},
                static_name=f"internal_starting_crossroads_{guild_id}", # Ensure this is unique per guild if needed
                is_active=True,
                exits={},
                inventory={},
                state_variables={},
                static_connections={},
                details_i18n={},
                tags_i18n={},
                atmosphere_i18n={},
                features_i18n={}
            )
            db_session.add(starting_location)
            logger.info(f"Added starting Location '{starting_location_id}' for guild {guild_id}.")
        else:
            logger.info(f"Starting location already exists for guild {guild_id} and not forcing reinitialization.")

        await db_session.commit()
        logger.info(f"Successfully initialized/updated default data for guild_id: {guild_id}")
        return True

    except IntegrityError as e:
        await db_session.rollback()
        logger.error(f"IntegrityError during guild initialization for {guild_id}: {e}. Rolled back session.")
        return False
    except Exception as e:
        await db_session.rollback()
        logger.error(f"Unexpected error during guild initialization for {guild_id}: {e}. Rolled back session.", exc_info=True)
        return False

if __name__ == '__main__':
    # Example of how to run this (requires async setup and DB connection)
    # This part is for testing and won't be part of the actual bot runtime directly like this.
    async def main_test():
        # This is a placeholder for how one might test this function.
        # In a real scenario, you'd get a DB session from your application's DB management.
        # For example, using a dummy session or a real one if the DB is available.

        # --- Setup a dummy database for local testing (if needed) ---
        from sqlalchemy.ext.asyncio import create_async_engine
        from bot.database.models import Base # Ensure Base is imported

        # Use an in-memory SQLite for testing if PostgreSQL is not available
        # Note: Some features might not work perfectly with SQLite if they rely on PG-specific types/functions.
        # For this initializer, it should be mostly fine.
        DATABASE_URL = "sqlite+aiosqlite:///./test_guild_init.db"
        # DATABASE_URL = "postgresql+asyncpg://postgres:test123@localhost:5432/kvelin_bot_test_init"


        engine = create_async_engine(DATABASE_URL, echo=False)

        async with engine.begin() as conn:
            # await conn.run_sync(Base.metadata.drop_all) # Drop all tables
            await conn.run_sync(Base.metadata.create_all) # Create all tables

        async_session_local = lambda: AsyncSession(bind=engine, expire_on_commit=False)

        test_guild_id = "test_guild_123"

        async with async_session_local() as session:
            logger.info(f"Running test initialization for guild: {test_guild_id}")
            success = await initialize_new_guild(session, test_guild_id)
            if success:
                logger.info(f"Test initialization for {test_guild_id} reported success.")
            else:
                logger.error(f"Test initialization for {test_guild_id} reported failure.")

            # Optionally, try re-initializing with force=True
            logger.info(f"Running test re-initialization with force=True for guild: {test_guild_id}")
            success_force = await initialize_new_guild(session, test_guild_id, force_reinitialize=True)
            if success_force:
                logger.info(f"Test re-initialization with force for {test_guild_id} reported success.")
            else:
                logger.error(f"Test re-initialization with force for {test_guild_id} reported failure.")

        await engine.dispose()

    logging.basicConfig(level=logging.INFO)
    # import asyncio
    # asyncio.run(main_test()) # Commented out to prevent execution in subtask environment directly
