# tests/utils/test_config_utils.py
import pytest
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select # Added import
# Added for more specific mocking/assertion if needed for pg_insert:
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Assuming the same test DB setup fixtures from other integration tests are available via conftest.py
# or we redefine minimal ones here if this test file is meant to be standalone for utils.
# For now, let's assume 'db_session' fixture is available (like in test_guild_initializer.py)

@pytest.fixture
async def test_guild_id(db_session: AsyncSession) -> str:
    """Creates a GuildConfig entry and returns its ID."""
    guild_id = f"test_config_guild_{str(uuid.uuid4())[:8]}"
    guild_config = GuildConfig(guild_id=guild_id, bot_language="en")
    db_session.add(guild_config)
    await db_session.commit()
    return guild_id

# --- Tests for load_rules_config ---
@pytest.mark.asyncio
async def test_load_rules_config_empty(db_session: AsyncSession, test_guild_id: str):
    """Test loading rules for a guild with no rules."""
    rules = await config_utils.load_rules_config(db_session, test_guild_id)
    assert rules == {}

@pytest.mark.asyncio
async def test_load_rules_config_with_data(db_session: AsyncSession, test_guild_id: str):
    """Test loading rules for a guild that has rules."""
    rule1_data = {"key": "rate", "value": 1.5}
    rule2_data = {"key": "feature_x_enabled", "value": True}

    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule1_data["key"], value=rule1_data["value"]))
    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule2_data["key"], value=rule2_data["value"]))
    await db_session.commit()

    rules = await config_utils.load_rules_config(db_session, test_guild_id)
    assert len(rules) == 2
    assert rules[rule1_data["key"]] == rule1_data["value"]
    assert rules[rule2_data["key"]] == rule2_data["value"]

@pytest.mark.asyncio
async def test_load_rules_config_non_existent_guild(db_session: AsyncSession):
    """Test loading rules for a guild_id that doesn't exist."""
    non_existent_guild_id = "non_existent_guild"
    rules = await config_utils.load_rules_config(db_session, non_existent_guild_id)
    assert rules == {}
    mock_db_session.execute.assert_awaited_once()

@pytest.mark.asyncio
async def test_get_rule_from_db_exists(db_session: AsyncSession, test_guild_id: str):
    """Test getting an existing rule from the database."""
    rule_key = "my_rule"
    rule_value = {"detail": "some_value"}
    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule_key, value=rule_value))
    await db_session.commit()

    fetched_value = await config_utils.get_rule(db_session, test_guild_id, rule_key)
    assert fetched_value == rule_value

# --- Tests for get_rule ---
@pytest.mark.asyncio
async def test_get_rule_from_db_not_exists(db_session: AsyncSession, test_guild_id: str):
    """Test getting a non-existing rule from the database."""
    fetched_value = await config_utils.get_rule(db_session, test_guild_id, "non_existent_rule_key")
    assert fetched_value is None

@pytest.mark.asyncio
async def test_get_rule_from_cache(db_session: AsyncSession, test_guild_id: str):
    """Test getting a rule from a provided cache."""
    rule_key = "cached_rule"
    rule_value = "cached_value"
    cache = {rule_key: rule_value}

    # Rule should not be in DB for this specific cache test part
    fetched_value = await config_utils.get_rule(db_session, test_guild_id, rule_key, rule_cache=cache)
    assert fetched_value == rule_value
    # Ensure DB was not hit (mock db_session.execute if more rigorous check needed, but logic is simple)

@pytest.mark.asyncio
async def test_get_rule_from_db_if_not_in_cache(db_session: AsyncSession, test_guild_id: str):
    """Test getting a rule from DB if not in cache, even if cache is provided."""
    rule_key = "db_fallback_rule"
    rule_value = {"value": 123}
    cache = {"other_cached_rule": "some_data"}

    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule_key, value=rule_value))
    await db_session.commit()

    fetched_value = await config_utils.get_rule(db_session, test_guild_id, rule_key, rule_cache=cache)
    assert fetched_value == rule_value

@pytest.mark.asyncio
async def test_update_rule_config_create_new(db_session: AsyncSession, test_guild_id: str):
    """Test creating a new rule using update_rule_config."""
    rule_key = "new_rule_via_update"
    rule_value = "initial_value"

    await config_utils.update_rule_config(db_session, test_guild_id, rule_key, rule_value)
    # db_session.commit() is called by update_rule_config

    # Verify by fetching directly
    stmt = select(RulesConfig.value).where(RulesConfig.guild_id == test_guild_id, RulesConfig.key == rule_key)
    result = await db_session.execute(stmt)
    fetched_value = result.scalars().first()
    assert fetched_value == rule_value

# --- Tests for update_rule_config ---
@pytest.mark.asyncio
async def test_update_rule_config_update_existing(db_session: AsyncSession, test_guild_id: str):
    """Test updating an existing rule using update_rule_config."""
    rule_key = "existing_rule_to_update"
    initial_value = {"count": 10}
    updated_value = {"count": 20, "active": False}

    # Create initial rule
    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule_key, value=initial_value))
    await db_session.commit()

    # Update it
    await config_utils.update_rule_config(db_session, test_guild_id, rule_key, updated_value)

    # Verify
    stmt = select(RulesConfig.value).where(RulesConfig.guild_id == test_guild_id, RulesConfig.key == rule_key)
    result = await db_session.execute(stmt)
    fetched_value = result.scalars().first()
    assert fetched_value == updated_value

@pytest.mark.asyncio
async def test_update_rule_config_different_guilds(db_session: AsyncSession, test_guild_id: str):
    """Test that updating a rule in one guild does not affect another."""
    other_guild_id = f"other_config_guild_{str(uuid.uuid4())[:8]}"
    other_guild_config = GuildConfig(guild_id=other_guild_id, bot_language="en")
    db_session.add(other_guild_config)
    await db_session.commit()


    rule_key = "shared_key_diff_guilds"
    value1 = "guild1_value"
    value2 = "guild2_value"

    await config_utils.update_rule_config(db_session, test_guild_id, rule_key, value1)
    await config_utils.update_rule_config(db_session, other_guild_id, rule_key, value2)

    # Verify for first guild
    stmt1 = select(RulesConfig.value).where(RulesConfig.guild_id == test_guild_id, RulesConfig.key == rule_key)
    result1 = await db_session.execute(stmt1)
    fetched_value1 = result1.scalars().first()
    assert fetched_value1 == value1

    # Verify for second guild
    stmt2 = select(RulesConfig.value).where(RulesConfig.guild_id == other_guild_id, RulesConfig.key == rule_key)
    result2 = await db_session.execute(stmt2)
    fetched_value2 = result2.scalars().first()
    assert fetched_value2 == value2

# Note: These tests rely on the db_session fixture providing a connection to a PostgreSQL database
# because update_rule_config uses pg_insert for upsert functionality.
# If run against SQLite, the on_conflict_do_update part will fail.
# The test_guild_initializer.py already sets up such an environment.
# Ensure conftest.py or similar makes the `engine` and `db_session` fixtures available.
# A `GuildConfig` entry is needed for `RulesConfig.guild_id` FK, so `test_guild_id` fixture handles this.

# Consider adding a test for when update_rule_config fails due to DB error (e.g., if commit fails).
# This would involve mocking db_session.commit() to raise an exception.
@pytest.mark.asyncio
async def test_update_rule_config_db_error_causes_rollback(db_session: AsyncSession, test_guild_id: str):
    rule_key = "rule_causing_error"
    rule_value = "some_value"

    original_commit = db_session.commit
    original_rollback = db_session.rollback

    async def mock_commit_failure():
        raise Exception("Simulated DB commit error")

    db_session.commit = AsyncMock(side_effect=mock_commit_failure)
    db_session.rollback = AsyncMock() # Ensure rollback can be asserted

    with pytest.raises(Exception, match="Simulated DB commit error"):
        await config_utils.update_rule_config(db_session, test_guild_id, rule_key, rule_value)

    db_session.rollback.assert_awaited_once()

    # Restore original methods if db_session is used by other tests within the same scope (though it shouldn't be for function-scoped fixtures)
    db_session.commit = original_commit
    db_session.rollback = original_rollback

    # Verify the rule was not actually saved
    stmt = select(RulesConfig.value).where(RulesConfig.guild_id == test_guild_id, RulesConfig.key == rule_key)
    result = await db_session.execute(stmt) # This execute will be on a fresh state if rollback worked
    fetched_value = result.scalars().first()
    assert fetched_value is None

# To use the same engine and session fixtures as in test_database_model_constraints.py
# and test_guild_initializer.py, you might need to ensure they are defined in a shared
# conftest.py at a higher level (e.g., in the tests/ directory).
# If they are defined in those files directly, pytest might not share them across different test files
# unless explicitly configured.
# For this example, assuming they are available (e.g., via conftest.py).

# Minimal conftest.py content (example if not already present at tests/ level)
# import pytest
# import os
# from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
# from bot.database.models import Base
#
# DEFAULT_PG_URL = "postgresql+asyncpg://user:password@localhost:5433/test_db_integrations"
# TEST_DB_URL = os.getenv("TEST_DATABASE_URL_INTEGRATION", DEFAULT_PG_URL)
#
# @pytest.fixture(scope="session")
# async def engine():
#     if TEST_DB_URL == DEFAULT_PG_URL and not os.getenv("CI"):
#         try:
#             # Quick check for DB availability
#             temp_engine = create_async_engine(TEST_DB_URL, connect_args={"timeout": 2})
#             async with temp_engine.connect(): pass
#             await temp_engine.dispose()
#         except Exception:
#             pytest.skip(f"Default PostgreSQL ({DEFAULT_PG_URL}) not available. Skipping integration tests.")
#
#     db_engine = create_async_engine(TEST_DB_URL, echo=False)
#     async with db_engine.connect() as conn:
#         await conn.run_sync(Base.metadata.drop_all)
#         await conn.run_sync(Base.metadata.create_all)
#         await conn.commit()
#     yield db_engine
#     await db_engine.dispose()
#
# @pytest.fixture(scope="function") # Changed to function scope for better isolation
# async def db_session(engine: AsyncEngine):
#     session = AsyncSession(engine, expire_on_commit=False)
#     async with session.begin_nested(): # Use nested transactions for per-test rollback
#         yield session
#         # Rollback is handled by begin_nested() on exit if an exception occurred,
#         # or if the block completes normally, it's ready for commit by the test if needed.
#         # However, to ensure clean state, an explicit rollback is often safer.
#         await session.rollback() # Ensure rollback after each test
#     await session.close()

# The test_guild_id fixture needs to be available too.
# If it's specific to this file's tests, keeping it here is fine.
# If used by other test_utils_*.py files, move to conftest.py.
