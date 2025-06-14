import pytest
import pytest_asyncio
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from bot.database.models import Base, RulesConfig, GeneratedFaction, Location
from bot.game.guild_initializer import initialize_new_guild # DEFAULT_START_LOCATION_ID is not used by this function for ID

# Use a consistent in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite_memory:///:memory:"

# Define constants used by the initializer if they are not exported by it
# DEFAULT_RULES_CONFIG_ID_IN_TEST = "main_rules_config" # RulesConfig PK is guild_id
FACTION_NAMES_EN = ["Neutral Observers", "Forest Guardians", "Rivertown Traders"]
DEFAULT_LOCATION_STATIC_NAMES = { # Using static names for checks as IDs are dynamic
    "village_square": "internal_village_square_{}",
    "tavern": "internal_village_tavern_{}",
    "shop": "internal_village_shop_{}",
    "forest_edge": "internal_forest_edge_{}",
    "deep_forest": "internal_deep_forest_{}"
}
DEFAULT_LANGUAGE = "en"
DEFAULT_PREFIX = ["!"]


@pytest_asyncio.fixture(scope="function")
async def async_db_session() -> AsyncIterator[AsyncSession]:
    """Fixture to create an async database session for each test, with table setup and teardown."""
    engine = create_async_engine(TEST_DATABASE_URL) # echo=True for debugging SQL
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # sessionmaker for creating sessions
    async_session_local = sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_local() as session:
        yield session # Provide the session to the test
        # Teardown: drop all tables after the test
        # This is usually handled by dropping the in-memory DB, but explicit drop ensures clean state if DB were persistent.
        # For in-memory SQLite, simply closing the engine or letting it go out of scope might be enough.
        # However, explicit drop is safer for other DBs.
        # await session.close() # Close the session used by the test
        # async with engine.begin() as conn: # New connection for dropping tables
        #    await conn.run_sync(Base.metadata.drop_all) # This might be too slow/complex for in-memory

    await engine.dispose() # Dispose of the engine

TEST_GUILD_ID = "test_guild_123"
TEST_GUILD_ID_2 = "test_guild_456" # For re-initialization tests

@pytest.mark.asyncio
async def test_initialize_new_guild_success(async_db_session: AsyncSession):
    """Tests successful initialization of a new guild."""
    session = async_db_session

    # initialize_new_guild now returns True/False, not a tuple
    initialized = await initialize_new_guild(session, TEST_GUILD_ID)
    assert initialized is True # Changed from success to initialized

    # Verify RulesConfig
    rules_config_stmt = select(RulesConfig).where(RulesConfig.guild_id == TEST_GUILD_ID)
    rules_config_result = await session.execute(rules_config_stmt)
    rules_config_entry = rules_config_result.scalar_one_or_none()
    assert rules_config_entry is not None
    assert rules_config_entry.guild_id == TEST_GUILD_ID
    assert rules_config_entry.config_data.get("default_language") == DEFAULT_LANGUAGE
    assert rules_config_entry.config_data.get("command_prefixes") == DEFAULT_PREFIX

    # Verify GeneratedFactions
    faction_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == TEST_GUILD_ID)
    faction_result = await session.execute(faction_stmt)
    factions = faction_result.scalars().all()
    assert len(factions) == len(FACTION_NAMES_EN) # Check for correct number of factions

    db_faction_names_en = sorted([f.name_i18n.get("en") for f in factions])
    assert db_faction_names_en == sorted(FACTION_NAMES_EN)
    for faction in factions:
        assert faction.guild_id == TEST_GUILD_ID
        assert faction.description_i18n.get("en") is not None

    # Verify default Map (Locations)
    all_locations_stmt = select(Location).where(Location.guild_id == TEST_GUILD_ID)
    all_locations_result = await session.execute(all_locations_stmt)
    all_db_locations = all_locations_result.scalars().all()

    assert len(all_db_locations) == len(DEFAULT_LOCATION_STATIC_NAMES)

    # Check Village Square and one of its exits
    village_square_static_name = DEFAULT_LOCATION_STATIC_NAMES["village_square"].format(TEST_GUILD_ID)
    village_square_loc = next((loc for loc in all_db_locations if loc.static_name == village_square_static_name), None)
    assert village_square_loc is not None
    assert village_square_loc.name_i18n.get("en") == "Village Square"
    assert village_square_loc.guild_id == TEST_GUILD_ID

    # Check that exits are populated and point to other created locations
    assert "north" in village_square_loc.exits
    forest_edge_exit_data = village_square_loc.exits["north"]
    forest_edge_loc_by_exit_id = next((loc for loc in all_db_locations if loc.id == forest_edge_exit_data["id"]), None)
    assert forest_edge_loc_by_exit_id is not None
    assert forest_edge_loc_by_exit_id.static_name == DEFAULT_LOCATION_STATIC_NAMES["forest_edge"].format(TEST_GUILD_ID)
    assert forest_edge_loc_by_exit_id.name_i18n.get("en") == "Forest Edge"

    # Check Tavern and its exit back to square
    tavern_static_name = DEFAULT_LOCATION_STATIC_NAMES["tavern"].format(TEST_GUILD_ID)
    tavern_loc = next((loc for loc in all_db_locations if loc.static_name == tavern_static_name), None)
    assert tavern_loc is not None
    assert "west" in tavern_loc.exits
    square_exit_data = tavern_loc.exits["west"]
    square_loc_by_exit_id = next((loc for loc in all_db_locations if loc.id == square_exit_data["id"]), None)
    assert square_loc_by_exit_id is not None
    assert square_loc_by_exit_id.static_name == village_square_static_name


@pytest.mark.asyncio
async def test_initialize_existing_guild_no_force(async_db_session: AsyncSession):
    """Tests that re-initializing an existing guild without force_reinitialize skips the process."""
    session = async_db_session

    # Initial setup
    await initialize_new_guild(session, TEST_GUILD_ID_2)

    # Get initial data to compare later
    rules_config_initial_stmt = select(RulesConfig).where(RulesConfig.guild_id == TEST_GUILD_ID_2)
    rules_config_initial_res = await session.execute(rules_config_initial_stmt)
    rules_config_initial_entry = rules_config_initial_res.scalar_one()

    # Modify a field to check if it's overwritten or not
    # Ensure config_data is a mutable dictionary
    if not isinstance(rules_config_initial_entry.config_data, dict):
        rules_config_initial_entry.config_data = {} # Or load from JSON if it's a string

    original_config_data_copy = rules_config_initial_entry.config_data.copy()
    modified_config_data_copy = original_config_data_copy.copy()
    modified_config_data_copy["test_field"] = "test_value"

    rules_config_initial_entry.config_data = modified_config_data_copy # Assign the modified copy
    session.add(rules_config_initial_entry) # Add to session before commit
    await session.commit() # Save modification

    # Attempt to re-initialize without force
    initialized_again = await initialize_new_guild(session, TEST_GUILD_ID_2, force_reinitialize=False)

    # Should indicate skipped or already initialized, which means it effectively succeeded by doing nothing or verifying.
    # The initializer returns False if skipped.
    assert initialized_again is False

    # Verify RulesConfig was not changed
    rules_config_after_stmt = select(RulesConfig).where(RulesConfig.guild_id == TEST_GUILD_ID_2)
    rules_config_after_res = await session.execute(rules_config_after_stmt)
    rules_config_after_entry = rules_config_after_res.scalar_one()
    assert rules_config_after_entry.config_data == modified_config_data_copy

@pytest.mark.asyncio
async def test_initialize_existing_guild_with_force(async_db_session: AsyncSession):
    """Tests that re-initializing an existing guild with force_reinitialize=True updates records."""
    session = async_db_session

    # Initial setup
    await initialize_new_guild(session, TEST_GUILD_ID)

    # Modify some data to ensure it gets overwritten
    rules_config_initial_stmt = select(RulesConfig).where(RulesConfig.guild_id == TEST_GUILD_ID)
    rules_config_initial_stmt = select(RulesConfig).where(RulesConfig.guild_id == TEST_GUILD_ID)
    rules_config_initial_res = await session.execute(rules_config_initial_stmt)
    rules_config_initial_entry = rules_config_initial_res.scalar_one()

    # Store the original count of factions and locations to ensure they are replaced, not just added to.
    initial_factions_count_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == TEST_GUILD_ID)
    initial_factions_count_res = await session.execute(initial_factions_count_stmt)
    initial_factions_count = len(initial_factions_count_res.scalars().all())

    initial_locations_count_stmt = select(Location).where(Location.guild_id == TEST_GUILD_ID)
    initial_locations_count_res = await session.execute(initial_locations_count_stmt)
    initial_locations_count = len(initial_locations_count_res.scalars().all())


    if not isinstance(rules_config_initial_entry.config_data, dict):
        rules_config_initial_entry.config_data = {} # Should be a dict already

    original_config_data_copy = rules_config_initial_entry.config_data.copy()
    modified_config_data_copy = original_config_data_copy.copy() # Create a copy to modify
    modified_config_data_copy["custom_setting_to_be_wiped"] = "custom_value"
    rules_config_initial_entry.config_data = modified_config_data_copy
    session.add(rules_config_initial_entry)
    await session.commit()


    # Attempt to re-initialize with force
    initialized_force = await initialize_new_guild(session, TEST_GUILD_ID, force_reinitialize=True)
    assert initialized_force is True

    # Verify RulesConfig was reset to default
    rules_config_after_stmt = select(RulesConfig).where(RulesConfig.guild_id == TEST_GUILD_ID)
    rules_config_after_res = await session.execute(rules_config_after_stmt)
    rules_config_after_entry = rules_config_after_res.scalar_one()

    assert "custom_setting_to_be_wiped" not in rules_config_after_entry.config_data
    assert rules_config_after_entry.config_data.get("default_language") == DEFAULT_LANGUAGE
    assert rules_config_after_entry.config_data.get("command_prefixes") == DEFAULT_PREFIX

    # Verify default Locations are re-created
    all_locations_stmt_after = select(Location).where(Location.guild_id == TEST_GUILD_ID)
    all_locations_result_after = await session.execute(all_locations_stmt_after)
    all_db_locations_after = all_locations_result_after.scalars().all()
    assert len(all_db_locations_after) == len(DEFAULT_LOCATION_STATIC_NAMES) # Ensure correct count
    # Spot check one location
    village_square_static_name_after = DEFAULT_LOCATION_STATIC_NAMES["village_square"].format(TEST_GUILD_ID)
    village_square_loc_after = next((loc for loc in all_db_locations_after if loc.static_name == village_square_static_name_after), None)
    assert village_square_loc_after is not None
    assert village_square_loc_after.name_i18n.get("en") == "Village Square"


    # Verify GeneratedFactions are re-created
    faction_stmt_after = select(GeneratedFaction).where(GeneratedFaction.guild_id == TEST_GUILD_ID)
    faction_result_after = await session.execute(faction_stmt_after)
    factions_after = faction_result_after.scalars().all()
    assert len(factions_after) == len(FACTION_NAMES_EN) # Ensure correct count
    db_faction_names_en_after = sorted([f.name_i18n.get("en") for f in factions_after])
    assert db_faction_names_en_after == sorted(FACTION_NAMES_EN)
