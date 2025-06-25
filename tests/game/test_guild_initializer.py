# tests/game/test_guild_initializer.py
import pytest
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.future import select
import json

from bot.database.models import (
    Base, GuildConfig, RulesConfig, GeneratedFaction, Location, WorldState,
    LocationTemplate, NPC, Character as DBCharacter # Renamed to avoid conflict with pytest 'character'
)
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

    success = await initialize_new_guild(db_session, test_guild_id, force_reinitialize=False)
    assert success is True
    await db_session.commit() # Commit after initialization to save changes

    # Verify GuildConfig
    guild_config = await db_session.get(GuildConfig, test_guild_id)
    assert guild_config is not None
    assert guild_config.guild_id == test_guild_id
    assert guild_config.bot_language == "en"

    # Verify WorldState
    world_state_stmt = select(WorldState).where(WorldState.guild_id == test_guild_id)
    result = await db_session.execute(world_state_stmt)
    world_state = result.scalars().first()
    assert world_state is not None
    assert world_state.guild_id == test_guild_id
    assert world_state.global_narrative_state_i18n == {} # Default

    # Verify LocationTemplates (check a few known default ones)
    default_template_ids = ["town_square", "tavern", "default_start_location"]
    for template_id in default_template_ids:
        loc_template_stmt = select(LocationTemplate).where(LocationTemplate.id == template_id, LocationTemplate.guild_id == test_guild_id)
        result = await db_session.execute(loc_template_stmt)
        loc_template = result.scalars().first()
        assert loc_template is not None, f"LocationTemplate {template_id} not found for guild {test_guild_id}"
        assert loc_template.guild_id == test_guild_id


    # Verify default RulesConfig entries
    rules_stmt = select(RulesConfig).where(RulesConfig.guild_id == test_guild_id)
    result = await db_session.execute(rules_stmt)
    rules_from_db = {rule.key: rule.value for rule in result.scalars().all()}

    expected_rules = {
        "experience_rate": 1.0,
        "default_language": "en",
        "max_party_size": 4,
        "nlu.action_verbs.en": { # Example of a dict rule
            "move": ["go", "walk", "travel", "head", "proceed", "run", "sprint", "dash", "stroll"],
            "look": ["look", "examine", "inspect", "view", "observe", "scan", "check", "peer", "gaze"],
            "attack": ["attack", "fight", "hit", "strike", "assault", "bash", "slash"],
            "talk": ["talk", "speak", "chat", "ask", "converse", "address", "question"],
            "use": ["use", "apply", "consume", "drink", "read", "equip", "activate"],
            "pickup": ["pickup", "take", "get", "collect", "grab", "acquire"],
            "drop": ["drop", "leave", "discard"],
            "open": ["open", "unseal"],
            "close": ["close", "seal"],
            "search": ["search", "explore area", "look around", "investigate area"]
        },
         "starting_base_stats": {"strength": 10, "dexterity": 10, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10},
    }
    for key, value in expected_rules.items():
        assert key in rules_from_db, f"Rule key '{key}' missing from DB rules."
        # JsonVariant should mean direct comparison works for dicts/lists too
        assert rules_from_db[key] == value, f"Mismatch for rule '{key}'. Expected: {value}, Got: {rules_from_db[key]}"

    # Verify default entities are created if is_new_world_setup was true (which it is on first call)
    factions_stmt = select(GeneratedFaction.id).where(GeneratedFaction.guild_id == test_guild_id)
    factions_result = await db_session.execute(factions_stmt)
    assert len(factions_result.scalars().all()) >= 3

    locations_stmt = select(Location.id).where(Location.guild_id == test_guild_id)
    locations_result = await db_session.execute(locations_stmt)
    assert len(locations_result.scalars().all()) >= 6 # default_start + 5 village/forest locations


@pytest.mark.asyncio
async def test_initialize_new_guild_no_force_if_exists(db_session: AsyncSession):
    test_guild_id = f"test_init_guild_exist_{str(uuid.uuid4())[:8]}"

    # Initial call
    await initialize_new_guild(db_session, test_guild_id, force_reinitialize=False)
    await db_session.commit() # Save initial state

    # Modify GuildConfig
    guild_config = await db_session.get(GuildConfig, test_guild_id)
    assert guild_config is not None
    guild_config.bot_language = "custom_lang"
    db_session.add(guild_config)

    # Modify a rule
    rule_to_change_stmt = select(RulesConfig).where(RulesConfig.guild_id == test_guild_id, RulesConfig.key == "experience_rate")
    result = await db_session.execute(rule_to_change_stmt)
    rule_to_change = result.scalars().first()
    assert rule_to_change is not None
    original_exp_rate_value = rule_to_change.value # Store original for later check if needed
    rule_to_change.value = 50.0 # This should be a float, matching default_rules
    db_session.add(rule_to_change)

    # Modify WorldState
    world_state_stmt = select(WorldState).where(WorldState.guild_id == test_guild_id)
    result = await db_session.execute(world_state_stmt)
    world_state = result.scalars().first()
    assert world_state is not None
    world_state.custom_flags = {"event_active": True}
    db_session.add(world_state)
    await db_session.commit()

    # Second call, without force
    # The initialize_new_guild function now always returns True on logical success or re-raises error.
    # It attempts upserts for GuildConfig, WorldState, LocationTemplates.
    # It checks for existing rules before adding defaults.
    # It skips new world entity creation (Factions, specific Locations) if not is_new_world_setup.
    success_second_call = await initialize_new_guild(db_session, test_guild_id, force_reinitialize=False)
    assert success_second_call is True # Expected to be True as it attempts some operations
    await db_session.commit()

    # Verify GuildConfig language was NOT reset by the upsert (current logic might reset it)
    # The current GuildConfig upsert in initialize_new_guild *will* set bot_language from its internal values.
    # If the goal is to preserve it, the upsert logic needs to change.
    # For now, testing current behavior:
    await db_session.refresh(guild_config)
    # With on_conflict_do_nothing, custom_lang should be preserved
    assert guild_config.bot_language == "custom_lang"
    assert guild_config.game_channel_id == "12345" # Should also be preserved

    # Verify the rule was not reset (because ensure_rules_are_added should be false)
    await db_session.refresh(rule_to_change)
    assert rule_to_change.value == 50.0 # Should remain 50.0

    # Verify WorldState custom_flags were NOT reset by the upsert
    # With on_conflict_do_nothing, custom_flags should be preserved
    await db_session.refresh(world_state)
    assert world_state.custom_flags == {"event_active": True} # Should remain as set


@pytest.mark.asyncio
async def test_initialize_new_guild_force_reinitialize(db_session: AsyncSession):
    test_guild_id = f"test_init_guild_force_{str(uuid.uuid4())[:8]}"

    # Initial call
    await initialize_new_guild(db_session, test_guild_id, force_reinitialize=False)
    await db_session.commit()

    # Create some entities that should be deleted on force_reinitialize
    # Add a specific NPC
    npc_to_delete = NPC(id=str(uuid.uuid4()), guild_id=test_guild_id, name_i18n={"en": "Old NPC"})
    db_session.add(npc_to_delete)
    # Add a specific Character (Player needs to exist first for Character's player_id FK)
    from bot.database.models import Player # Ensure Player is imported
    player_for_char_id = str(uuid.uuid4())
    temp_player = Player(id=player_for_char_id, discord_id=str(uuid.uuid4()), guild_id=test_guild_id, name_i18n={"en": "Temp Player"})
    db_session.add(temp_player)
    await db_session.flush() # Flush to get player_id if it's server-generated or ensure it exists

    char_to_delete = DBCharacter(id=str(uuid.uuid4()), player_id=temp_player.id, guild_id=test_guild_id, name_i18n={"en": "Old Character"})
    db_session.add(char_to_delete)


    # Modify GuildConfig bot_language
    guild_config = await db_session.get(GuildConfig, test_guild_id)
    assert guild_config is not None
    guild_config.bot_language = "custom_lang_before_force"
    db_session.add(guild_config)

    # Modify a rule
    rule_to_change_stmt = select(RulesConfig).where(RulesConfig.guild_id == test_guild_id, RulesConfig.key == "experience_rate")
    result = await db_session.execute(rule_to_change_stmt)
    rule_to_change = result.scalars().first()
    assert rule_to_change is not None
    rule_to_change.value = 100.0 # This should be a float
    db_session.add(rule_to_change)
    await db_session.commit()

    # Count factions and locations before force reinitialize
    factions_before_stmt = select(GeneratedFaction).where(GeneratedFaction.guild_id == test_guild_id)
    factions_before_result = await db_session.execute(factions_before_stmt)
    factions_before_count = len(factions_before_result.scalars().all())

    locations_before_stmt = select(Location).where(Location.guild_id == test_guild_id)
    locations_before_result = await db_session.execute(locations_before_stmt)
    locations_before_count = len(locations_before_result.scalars().all())

    # Call with force_reinitialize=True
    success_force_call = await initialize_new_guild(db_session, test_guild_id, force_reinitialize=True)
    assert success_force_call is True
    await db_session.commit()

    # Verify GuildConfig bot_language is reset to default 'en'
    await db_session.refresh(guild_config)
    assert guild_config.bot_language == "en"

    # Verify RulesConfig experience_rate is reset to default 1.0
    await db_session.refresh(rule_to_change) # Re-fetch the rule instance or query by key
    refetched_rule_stmt = select(RulesConfig).where(RulesConfig.guild_id == test_guild_id, RulesConfig.key == "experience_rate")
    result = await db_session.execute(refetched_rule_stmt)
    refetched_rule = result.scalars().first()
    assert refetched_rule is not None
    assert refetched_rule.value == 1.0

    # Verify factions and locations were re-created (counts should be similar to new init)
    factions_after_stmt = select(GeneratedFaction.id).where(GeneratedFaction.guild_id == test_guild_id)
    factions_after_result = await db_session.execute(factions_after_stmt)
    assert len(factions_after_result.scalars().all()) == factions_before_count # Assuming same number of defaults

    locations_after_stmt = select(Location.id).where(Location.guild_id == test_guild_id)
    locations_after_result = await db_session.execute(locations_after_stmt)
    assert len(locations_after_result.scalars().all()) == locations_before_count # Assuming same number of defaults

    # Verify specific NPC and Character were deleted
    assert await db_session.get(NPC, npc_to_delete.id) is None
    assert await db_session.get(DBCharacter, char_to_delete.id) is None


# Note: These tests require a PostgreSQL database configured via TEST_DATABASE_URL_INTEGRATION.
# The default value "postgresql+asyncpg://user:password@localhost:5433/test_db_integrations"
# is a placeholder. If not overridden by an environment variable, tests will attempt to connect to this
# default and skip if it's unavailable (unless CI=true is set in env).
# The tests will drop and recreate all tables in this database at the start of the test session.
# USE WITH CAUTION and point to a dedicated test database.

@pytest.mark.asyncio
async def test_initialize_new_guild_db_integrity_error_propagates(db_session: AsyncSession, caplog):
    """
    Tests that an IntegrityError during initialization is propagated,
    allowing the calling context (like on_guild_join) to handle transaction rollback.
    """
    guild_id = f"fail_guild_{str(uuid.uuid4())[:8]}"

    # Mock db_session.execute to raise IntegrityError when specific insert happens
    original_execute = db_session.execute
    async def mock_execute_that_fails(statement, *args, **kwargs):
        # Check if it's an insert statement targeting GuildConfig table
        # This is a simplified check; real statement inspection can be more complex.
        if hasattr(statement, 'is_insert') and statement.is_insert:
            if hasattr(statement, 'table') and statement.table.name == GuildConfig.__tablename__:
                raise IntegrityError("Simulated GuildConfig insert failure", params=None, orig=None)
        return await original_execute(statement, *args, **kwargs)

    with patch.object(db_session, 'execute', side_effect=mock_execute_that_fails):
        with pytest.raises(IntegrityError, match="Simulated GuildConfig insert failure"):
            await initialize_new_guild(db_session, guild_id, force_reinitialize=False)
            # If initialize_new_guild completes and error is not raised, this line won't be hit:
            # await db_session.commit() # Should not commit due to error

    # Check logs for the error message from initialize_new_guild
    assert f"IntegrityError during guild initialization: {guild_id}" in caplog.text
    assert "Simulated GuildConfig insert failure" in caplog.text
    # The actual rollback is handled by the test's db_session fixture or the calling code's transaction manager.
    # initialize_new_guild re-raises the exception, so it won't try to commit.
