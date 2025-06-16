# tests/game/test_guild_initializer.py
import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.future import select

from bot.database.models import Base, GuildConfig, RulesConfig, GeneratedFaction, Location
from bot.game.guild_initializer import initialize_new_guild

# Use environment variables for test DB to avoid hardcoding credentials
import os
# Fallback to a local dockerized PG if GITHUB_ACTIONS is not set
# In GitHub Actions, this variable might be set by the workflow.
# For local, ensure you have a PG instance at localhost:5433 or change this.
DEFAULT_PG_URL = "postgresql+asyncpg://user:password@localhost:5433/test_db_integrations"
TEST_DB_URL = os.getenv("TEST_DATABASE_URL_INTEGRATION", DEFAULT_PG_URL)


@pytest.fixture(scope="session") # Changed to session for potentially faster tests if DB setup is slow
async def engine():
    # Skip if using default placeholder URL and it's likely not configured
    if TEST_DB_URL == DEFAULT_PG_URL and not os.getenv("CI"): # Avoid skip in CI if default is used there
        try:
            # Attempt a quick connection to see if the default is actually running
            temp_engine = create_async_engine(TEST_DB_URL, connect_args={"timeout": 2})
            async with temp_engine.connect() as conn:
                pass # Connection successful
            await temp_engine.dispose()
        except Exception: # pylint: disable=broad-except
             pytest.skip(f"Default PostgreSQL TEST_DATABASE_URL_INTEGRATION ({DEFAULT_PG_URL}) not available or not configured. Skipping integration tests.")

    db_engine = create_async_engine(TEST_DB_URL, echo=False)
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield db_engine
    # Teardown after all tests in session (if needed, but drop_all handles it for next run)
    # async with db_engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.drop_all)
    await db_engine.dispose()

@pytest.fixture
async def db_session(engine): # Depends on the session-scoped engine
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
        # Rollback any uncommitted changes after each test
        await session.rollback()
        # Clean up specific data if necessary, but generally tests should manage their own data
        # or rely on full DB refresh if tests are not isolated.
        # For these tests, each uses a unique guild_id, so direct cleanup per test is less critical.

@pytest.mark.asyncio
async def test_initialize_new_guild_creates_guild_config_and_rules(db_session: AsyncSession):
    test_guild_id = f"test_init_guild_{str(uuid.uuid4())[:8]}"

    success = await initialize_new_guild(db_session, test_guild_id, force_reinitialize=False)
    assert success is True

    # Verify GuildConfig
    guild_config_stmt = select(GuildConfig).where(GuildConfig.guild_id == test_guild_id)
    result = await db_session.execute(guild_config_stmt)
    guild_config = result.scalars().first()

    assert guild_config is not None
    assert guild_config.guild_id == test_guild_id
    assert guild_config.bot_language == "en" # Default from initializer

    # Verify default RulesConfig entries (key-value structure)
    rules_stmt = select(RulesConfig).where(RulesConfig.guild_id == test_guild_id)
    result = await db_session.execute(rules_stmt)
    rules_from_db = {rule.key: rule.value for rule in result.scalars().all()}

    expected_rules = {
        "experience_rate": 1.0,
        "loot_drop_chance": 0.5,
        "combat_difficulty_modifier": 1.0,
        "default_language": "en",
        "command_prefixes": ["!"],
        "max_party_size": 4,
        "action_cooldown_seconds": 30
    }
    assert rules_from_db == expected_rules

    # Verify other default entities are created
    factions_stmt = select(GeneratedFaction.id).where(GeneratedFaction.guild_id == test_guild_id)
    factions_result = await db_session.execute(factions_stmt)
    # Based on guild_initializer, 3 factions are created
    assert len(factions_result.scalars().all()) == 3

    locations_stmt = select(Location.id).where(Location.guild_id == test_guild_id)
    locations_result = await db_session.execute(locations_stmt)
    # Based on guild_initializer, 5 locations are created
    assert len(locations_result.scalars().all()) == 5


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
    await db_session.refresh(guild_config) # Refresh from DB
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
