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

        # 2. Create Default GeneratedFactions
        logger.info(f"Initializing default factions for guild {guild_id}.")
        if force_reinitialize:
            logger.info(f"Force reinitialize: Deleting existing factions for guild {guild_id}.")
            existing_factions_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == guild_id)
            result = await db_session.execute(existing_factions_stmt)
            for faction in result.scalars().all():
                await db_session.delete(faction)
            await db_session.flush()

        default_factions_data = [
            {
                "id": f"faction_observers_{str(uuid.uuid4())[:8]}",
                "name_i18n": {"en": "Neutral Observers", "ru": "Нейтральные Наблюдатели"},
                "description_i18n": {"en": "A neutral faction, keen on watching events unfold without direct intervention.", "ru": "Нейтральная фракция, заинтересованная в наблюдении за событиями без прямого вмешательства."}
            },
            {
                "id": f"faction_guardians_{str(uuid.uuid4())[:8]}",
                "name_i18n": {"en": "Forest Guardians", "ru": "Стражи Леса"},
                "description_i18n": {"en": "Protectors of the ancient woods and its secrets.", "ru": "Защитники древних лесов и их тайн."}
            },
            {
                "id": f"faction_merchants_{str(uuid.uuid4())[:8]}",
                "name_i18n": {"en": "Rivertown Traders", "ru": "Торговцы Речного Города"},
                "description_i18n": {"en": "A mercantile collective known for their extensive network along the river.", "ru": "Торговый коллектив, известный своей обширной сетью вдоль реки."}
            }
        ]

        factions_to_add = []
        for faction_data in default_factions_data:
            # Check if this specific faction already exists (e.g. by name, if names are unique identifiers for default set)
            # For simplicity, if not forcing, we assume we don't add if ANY faction exists, or we add if this one doesn't.
            # A more robust check might be needed if we want to add missing default factions without force_reinitialize.
            # Current logic: if not force_reinitialize, it might add factions if some are missing, or skip if one was found by earlier broader checks.
            # The initial check for RuleConfig is the main gate for non-forced reinitialization.
            # If we are here and not force_reinitialize, it means RuleConfig was missing.
            new_faction = GeneratedFaction(
                id=faction_data["id"],
                guild_id=guild_id,
                name_i18n=faction_data["name_i18n"],
                description_i18n=faction_data["description_i18n"]
            )
            factions_to_add.append(new_faction)

        if factions_to_add:
            db_session.add_all(factions_to_add)
            logger.info(f"Added {len(factions_to_add)} default factions for guild {guild_id}.")
        else:
            logger.info(f"No new factions to add for guild {guild_id} (either existed or not forcing).")


        # 3. Create Default Map (Locations)
        logger.info(f"Initializing default map for guild {guild_id}.")
        if force_reinitialize:
            logger.info(f"Force reinitialize: Deleting existing locations for guild {guild_id}.")
            existing_locations_stmt = select(Location).where(Location.guild_id == guild_id)
            result = await db_session.execute(existing_locations_stmt)
            for loc in result.scalars().all():
                await db_session.delete(loc)
            await db_session.flush()

        # Define locations
        village_square_id = f"loc_village_square_{str(uuid.uuid4())[:8]}"
        village_tavern_id = f"loc_village_tavern_{str(uuid.uuid4())[:8]}"
        village_shop_id = f"loc_village_shop_{str(uuid.uuid4())[:8]}"
        forest_edge_id = f"loc_forest_edge_{str(uuid.uuid4())[:8]}"
        deep_forest_id = f"loc_deep_forest_{str(uuid.uuid4())[:8]}"

        default_locations_data = [
            {
                "id": village_square_id,
                "name_i18n": {"en": "Village Square", "ru": "Деревенская Площадь"},
                "descriptions_i18n": {"en": "The bustling center of a small village.", "ru": "Шумный центр небольшой деревни."},
                "static_name": f"internal_village_square_{guild_id}",
                "exits": {
                    "north": {"id": forest_edge_id, "name_i18n": {"en": "Forest Edge", "ru": "Опушка Леса"}},
                    "east": {"id": village_tavern_id, "name_i18n": {"en": "The Prancing Pony Tavern", "ru": "Таверна 'Гарцующий Пони'"}},
                    "west": {"id": village_shop_id, "name_i18n": {"en": "General Store", "ru": "Универсальный Магазин"}}
                }
            },
            {
                "id": village_tavern_id,
                "name_i18n": {"en": "The Prancing Pony Tavern", "ru": "Таверна 'Гарцующий Пони'"},
                "descriptions_i18n": {"en": "A cozy tavern, filled with locals and adventurers.", "ru": "Уютная таверна, полная местных жителей и искателей приключений."},
                "static_name": f"internal_village_tavern_{guild_id}",
                "exits": {"west": {"id": village_square_id, "name_i18n": {"en": "Village Square", "ru": "Деревенская Площадь"}}}
            },
            {
                "id": village_shop_id,
                "name_i18n": {"en": "General Store", "ru": "Универсальный Магазин"},
                "descriptions_i18n": {"en": "A store selling various goods and supplies.", "ru": "Магазин, продающий различные товары и припасы."},
                "static_name": f"internal_village_shop_{guild_id}",
                "exits": {"east": {"id": village_square_id, "name_i18n": {"en": "Village Square", "ru": "Деревенская Площадь"}}}
            },
            {
                "id": forest_edge_id,
                "name_i18n": {"en": "Forest Edge", "ru": "Опушка Леса"},
                "descriptions_i18n": {"en": "The edge of a dark and ancient forest.", "ru": "Край темного и древнего леса."},
                "static_name": f"internal_forest_edge_{guild_id}",
                "exits": {
                    "south": {"id": village_square_id, "name_i18n": {"en": "Village Square", "ru": "Деревенская Площадь"}},
                    "north": {"id": deep_forest_id, "name_i18n": {"en": "Deep Forest", "ru": "Глубокий Лес"}}
                }
            },
            {
                "id": deep_forest_id,
                "name_i18n": {"en": "Deep Forest", "ru": "Глубокий Лес"},
                "descriptions_i18n": {"en": "The heart of the ancient, whispering woods.", "ru": "Сердце древнего, шепчущего леса."},
                "static_name": f"internal_deep_forest_{guild_id}",
                "exits": {"south": {"id": forest_edge_id, "name_i18n": {"en": "Forest Edge", "ru": "Опушка Леса"}}}
            }
        ]

        locations_to_add = []
        for loc_data in default_locations_data:
            new_location = Location(
                id=loc_data["id"],
                guild_id=guild_id,
                name_i18n=loc_data["name_i18n"],
                descriptions_i18n=loc_data["descriptions_i18n"],
                static_name=loc_data["static_name"],
                is_active=True,
                exits=loc_data.get("exits", {}),
                # Ensure all required fields from Location model are present
                inventory={}, state_variables={}, static_connections={}, details_i18n={},
                tags_i18n={}, atmosphere_i18n={}, features_i18n={}, type_i18n={"en": "Area", "ru": "Область"}
            )
            locations_to_add.append(new_location)

        if locations_to_add:
            db_session.add_all(locations_to_add)
            logger.info(f"Added {len(locations_to_add)} default locations for guild {guild_id}.")
        else:
            logger.info(f"No new locations to add for guild {guild_id} (either existed or not forcing).")

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
