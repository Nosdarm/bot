import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from bot.database.models import Base, RulesConfig, GeneratedFaction, Location
from bot.game.guild_initializer import initialize_new_guild # DEFAULT_START_LOCATION_ID is not used by this function for ID

# Use a consistent in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite_memory:///:memory:"

# Define constants used by the initializer if they are not exported by it
DEFAULT_RULES_CONFIG_ID_IN_TEST = "main_rules_config" # Match the implicit one if not exported
DEFAULT_FACTION_EN_NAME = "Neutral Observers"
DEFAULT_LOCATION_EN_NAME = "Quiet Crossroads"
# The actual ID of the default location is dynamic, so we'll use static_name or name_i18n for querying
# DEFAULT_START_LOCATION_STATIC_NAME_FORMAT = "internal_starting_crossroads_{}" # Used to form the static_name

@pytest_asyncio.fixture(scope="function") # Changed from pytest.fixture to pytest_asyncio.fixture
async def async_db_session() -> AsyncSession:
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

    success, message = await initialize_new_guild(session, TEST_GUILD_ID)

    assert success is True
    assert "successfully initialized" in message.lower()

    # Verify RulesConfig
    rules_config_stmt = select(RulesConfig).where(RulesConfig.guild_id == TEST_GUILD_ID)
    rules_config_result = await session.execute(rules_config_stmt)
    rules_config_entry = rules_config_result.scalar_one_or_none()
    assert rules_config_entry is not None
    assert rules_config_entry.guild_id == TEST_GUILD_ID
    # The RulesConfig primary key 'id' is not set by initialize_new_guild,
    # it's part of the data it loads/creates. The PK is (guild_id, id)
    # The default ID for the rules config entry itself is 'main_rules_config'
    # The model has id = Column(String, primary_key=True, default=DEFAULT_RULES_CONFIG_ID)
    # So, if the initializer creates a new RulesConfig, it should have this ID.
    # However, the primary key of RulesConfig is just guild_id as per current DB model.
    # The `id` field on RulesConfig is not the PK. Let's check what initialize_new_guild does.
    # initialize_new_guild does NOT set RulesConfig.id. It's up to the model default or another process.
    # For now, we'll assume the guild_id is the main check.
    # If RulesConfig has a composite PK (guild_id, id), the query needs to change.
    # Based on `bot/database/models.py`, RulesConfig PK is just `guild_id`. It does not have a separate `id` field.
    # The line `assert rules_config_entry.id == DEFAULT_RULES_CONFIG_ID` is incorrect based on the model.
    # It seems there's a mismatch between my test assumption and the actual RulesConfig model.
    # Let's re-check models.py RulesConfig: `guild_id = Column(String, primary_key=True)`
    # So, there is no RulesConfig.id field. The test for this needs to be removed.
    # assert rules_config_entry.id == DEFAULT_RULES_CONFIG_ID_IN_TEST
    assert "default_language" in rules_config_entry.config_data # Check for presence of default data

    # Verify GeneratedFaction
    faction_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == TEST_GUILD_ID)
    faction_result = await session.execute(faction_stmt)
    factions = faction_result.scalars().all()
    assert len(factions) > 0
    neutral_observers_faction = next((f for f in factions if f.name_i18n.get("en") == DEFAULT_FACTION_EN_NAME), None)
    assert neutral_observers_faction is not None
    assert neutral_observers_faction.description_i18n.get("en") is not None

    # Verify default Location
    # Query by static_name as ID is dynamic
    expected_static_name = f"internal_starting_crossroads_{TEST_GUILD_ID}"
    location_stmt = select(Location).where(Location.guild_id == TEST_GUILD_ID, Location.static_name == expected_static_name)
    location_result = await session.execute(location_stmt)
    default_location = location_result.scalar_one_or_none()
    assert default_location is not None
    assert default_location.guild_id == TEST_GUILD_ID
    assert default_location.name_i18n.get("en") == DEFAULT_LOCATION_EN_NAME
    # Add more checks for location properties if necessary

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
    success, message = await initialize_new_guild(session, TEST_GUILD_ID_2, force_reinitialize=False)

    assert success is True
    # Message can vary, "already has a RuleConfig" or "already initialized" or "skipped"
    assert "already" in message.lower() or "skipped" in message.lower()

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
    rules_config_initial_res = await session.execute(rules_config_initial_stmt)
    rules_config_initial_entry = rules_config_initial_res.scalar_one()

    if not isinstance(rules_config_initial_entry.config_data, dict):
        rules_config_initial_entry.config_data = {}

    original_config_data_copy = rules_config_initial_entry.config_data.copy()

    modified_config_data_copy = original_config_data_copy.copy()
    modified_config_data_copy["custom_setting_to_be_wiped"] = "custom_value"
    rules_config_initial_entry.config_data = modified_config_data_copy
    session.add(rules_config_initial_entry)
    await session.commit()

    # Attempt to re-initialize with force
    success, message = await initialize_new_guild(session, TEST_GUILD_ID, force_reinitialize=True)

    assert success is True
    assert "successfully" in message.lower()

    # Verify RulesConfig was reset to default
    rules_config_after_stmt = select(RulesConfig).where(RulesConfig.guild_id == TEST_GUILD_ID)
    rules_config_after_res = await session.execute(rules_config_after_stmt)
    rules_config_after_entry = rules_config_after_res.scalar_one()

    assert "custom_setting_to_be_wiped" not in rules_config_after_entry.config_data
    assert "default_language" in rules_config_after_entry.config_data

    # Verify default Location is present (or re-created)
    expected_static_name = f"internal_starting_crossroads_{TEST_GUILD_ID}"
    location_stmt = select(Location).where(Location.guild_id == TEST_GUILD_ID, Location.static_name == expected_static_name)
    location_result = await session.execute(location_stmt)
    default_location_after = location_result.scalar_one_or_none()
    assert default_location_after is not None
    assert default_location_after.name_i18n.get("en") == DEFAULT_LOCATION_EN_NAME

    # Verify GeneratedFaction (default factions are re-created)
    faction_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == TEST_GUILD_ID)
    faction_result = await session.execute(faction_stmt)
    factions_after = faction_result.scalars().all()
    assert len(factions_after) > 0
    neutral_observers_faction_after = next((f for f in factions_after if f.name_i18n.get("en") == DEFAULT_FACTION_EN_NAME), None)
    assert neutral_observers_faction_after is not None
