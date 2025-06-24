# tests/game/test_guild_initializer.py
import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine # Added AsyncEngine
from sqlalchemy.future import select
import json # For json.loads if needed in assertions

from bot.database.models import Base, GuildConfig, RulesConfig, GeneratedFaction, Location
from bot.game.guild_initializer import initialize_new_guild

# Use environment variables for test DB to avoid hardcoding credentials
import os
# Fallback to a local dockerized PG if GITHUB_ACTIONS is not set
# In GitHub Actions, this variable might be set by the workflow.
# For local, ensure you have a PG instance at localhost:5433 or change this.
DEFAULT_PG_URL = "postgresql+asyncpg://user:password@localhost:5433/test_db_integrations"
TEST_DB_URL = os.getenv("TEST_DATABASE_URL_INTEGRATION", DEFAULT_PG_URL)


@pytest.fixture(scope="session")
async def engine():
    if TEST_DB_URL == DEFAULT_PG_URL and not os.getenv("CI"):
        try:
            temp_engine = create_async_engine(TEST_DB_URL, connect_args={"timeout": 2})
            async with temp_engine.connect(): # Quick check
                pass
            await temp_engine.dispose()
        except Exception:
             pytest.skip(f"Default PostgreSQL ({DEFAULT_PG_URL}) not available. Skipping.")

    db_engine = create_async_engine(TEST_DB_URL, echo=False)
    async with db_engine.connect() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()

    yield db_engine # This now yields the engine instance correctly

    await db_engine.dispose()

@pytest.fixture
async def db_session(engine: AsyncEngine): # engine is now correctly AsyncEngine
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield session # session is an AsyncSession
    finally:
        await session.rollback()
        await session.close()

@pytest.mark.asyncio
async def test_initialize_new_guild_creates_guild_config_and_rules(db_session: AsyncSession): # db_session is now AsyncSession
    test_guild_id = f"test_init_guild_{str(uuid.uuid4())[:8]}"

    success = await initialize_new_guild(db_session, test_guild_id, force_reinitialize=False) # Use db_session directly
    assert success is True

    # Verify GuildConfig
    guild_config_stmt = select(GuildConfig).where(GuildConfig.guild_id == test_guild_id)
    result = await db_session.execute(guild_config_stmt) # Use db_session directly
    guild_config = result.scalars().first()

    assert guild_config is not None
    assert guild_config.guild_id == test_guild_id
    assert guild_config.bot_language == "en" # Default from initializer

    # Verify default RulesConfig entries (key-value structure)
    rules_stmt = select(RulesConfig).where(RulesConfig.guild_id == test_guild_id)
    result = await db_session.execute(rules_stmt)
    rules_from_db = {rule.key: rule.value for rule in result.scalars().all()}

    # Expected default rules (subset for brevity, ensure all relevant ones are checked)
    # This check might need to be updated if default_rules in guild_initializer changes.
    expected_rules_subset = {
        "experience_rate": 1.0,
        "default_language": "en",
        "max_party_size": 4
    }
    for key, value in expected_rules_subset.items():
        assert key in rules_from_db, f"Rule key {key} missing from DB rules."
        # RulesConfig.value is JSONB, so it stores JSON strings for dicts/lists, and numbers/bools directly.
        # The default_rules in guild_initializer.py has simple types for these keys.
        if isinstance(value, (list, dict)):
            assert json.loads(rules_from_db[key]) == value, f"Mismatch for rule {key}"
        else:
            assert rules_from_db[key] == value, f"Mismatch for rule {key}"


    # Verify other default entities are created
    factions_stmt = select(GeneratedFaction.id).where(GeneratedFaction.guild_id == test_guild_id)
    factions_result = await db_session.execute(factions_stmt)
    assert len(factions_result.scalars().all()) >= 3 # At least 3 factions

    locations_stmt = select(Location.id).where(Location.guild_id == test_guild_id)
    locations_result = await db_session.execute(locations_stmt)
    # Check for at least the number of locations created by the initializer
    # (e.g., default_start_location + 5 village/forest locations)
    assert len(locations_result.scalars().all()) >= 6


@pytest.mark.asyncio
async def test_initialize_new_guild_no_force_if_exists(db_session: AsyncSession):
    test_guild_id = f"test_init_guild_exist_{str(uuid.uuid4())[:8]}"

    # Initial call
    await initialize_new_guild(db_session, test_guild_id, force_reinitialize=False)

    # Modify a setting
    guild_config_select_stmt = select(GuildConfig).where(GuildConfig.guild_id == test_guild_id)
    result = await db_session.execute(guild_config_select_stmt)
    guild_config = result.scalars().first()
    assert guild_config is not None
    guild_config.bot_language = "custom_lang"
    # Also modify a rule to ensure it's not reset
    await db_session.execute(
        RulesConfig.__table__.update().where(
            RulesConfig.guild_id == test_guild_id,
            RulesConfig.key == "experience_rate"
        ).values(value=50.0) # Ensure value is JSONB compatible if RulesConfig.value is JSONB
    )
    await db_session.commit()

    # Second call, without force
    success_second_call = await initialize_new_guild(db_session, test_guild_id, force_reinitialize=False)
    assert success_second_call is False # Should skip as GuildConfig exists

    # Verify the language was not reset
    await db_session.refresh(guild_config) # Refresh from DB
    assert guild_config.bot_language == "custom_lang"

    # Verify the rule was not reset
    exp_rate_rule_stmt = select(RulesConfig.value).where(
        RulesConfig.guild_id == test_guild_id, RulesConfig.key == "experience_rate"
    )
    exp_rate_result = await db_session.execute(exp_rate_rule_stmt)
    assert exp_rate_result.scalars().first() == 50.0


@pytest.mark.asyncio
async def test_initialize_new_guild_force_reinitialize(db_session: AsyncSession):
    test_guild_id = f"test_init_guild_force_{str(uuid.uuid4())[:8]}"

    # Initial call
    await initialize_new_guild(db_session, test_guild_id, force_reinitialize=False)

    # Modify GuildConfig bot_language
    guild_config_select_stmt = select(GuildConfig).where(GuildConfig.guild_id == test_guild_id)
    result = await db_session.execute(guild_config_select_stmt)
    guild_config = result.scalars().first()
    assert guild_config is not None
    guild_config.bot_language = "custom_lang_before_force"

    # Modify a rule directly in DB for testing
    await db_session.execute(
         RulesConfig.__table__.update().where(
            RulesConfig.guild_id == test_guild_id,
            RulesConfig.key == "experience_rate"
        ).values(value=100.0) # Ensure JSONB compatible if needed
    )
    await db_session.commit()

    # Call with force_reinitialize=True
    success_force_call = await initialize_new_guild(db_session, test_guild_id, force_reinitialize=True)
    assert success_force_call is True

    # Verify GuildConfig bot_language is reset to default 'en' (as per current upsert logic in initializer)
    await db_session.refresh(guild_config)
    assert guild_config.bot_language == "en"

    # Verify RulesConfig experience_rate is reset to default 1.0
    rules_stmt = select(RulesConfig.value).where(
        RulesConfig.guild_id == test_guild_id,
        RulesConfig.key == "experience_rate"
    )
    rule_val_result = await db_session.execute(rules_stmt)
    exp_rate_after_force = rule_val_result.scalars().first()
    assert exp_rate_after_force == 1.0

# Note: These tests require a PostgreSQL database configured via TEST_DATABASE_URL_INTEGRATION.
# The default value "postgresql+asyncpg://user:password@localhost:5433/test_db_integrations"
# is a placeholder. If not overridden by an environment variable, tests will attempt to connect to this
# default and skip if it's unavailable (unless CI=true is set in env).
# The tests will drop and recreate all tables in this database at the start of the test session.
# USE WITH CAUTION and point to a dedicated test database.
