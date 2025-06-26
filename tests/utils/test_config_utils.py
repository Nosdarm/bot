# tests/utils/test_config_utils.py
import pytest
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from unittest.mock import AsyncMock, patch # Added patch
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Import the module to be tested
from bot.utils import config_utils

# Import models used in tests
from bot.database.models.config_related import GuildConfig, RulesConfig # Added imports

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

    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule1_data["key"], value=rule1_data["value"])) # type: ignore[call-arg] # If RulesConfig expects value as JSON
    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule2_data["key"], value=rule2_data["value"])) # type: ignore[call-arg]
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

@pytest.mark.asyncio
async def test_load_rules_config_db_error(db_session: AsyncSession, test_guild_id: str, caplog: pytest.LogCaptureFixture): # Added caplog type
    """Test loading rules when a database error occurs."""
    with patch.object(db_session, 'execute', new_callable=AsyncMock) as mock_execute:
        mock_execute.side_effect = Exception("Simulated DB Error during load")
        rules = await config_utils.load_rules_config(db_session, test_guild_id)
    assert rules == {}
    assert "Error loading rules config" in caplog.text
    assert f"guild {test_guild_id}" in caplog.text
    assert "Simulated DB Error during load" in caplog.text

@pytest.mark.asyncio
async def test_get_rule_from_db_exists(db_session: AsyncSession, test_guild_id: str):
    """Test getting an existing rule from the database."""
    rule_key = "my_rule"
    rule_value = {"detail": "some_value"}
    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule_key, value=rule_value)) # type: ignore[call-arg]
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
async def test_get_rule_from_db_error(db_session: AsyncSession, test_guild_id: str, caplog: pytest.LogCaptureFixture): # Added caplog type
    """Test getting a rule when a database error occurs."""
    rule_key = "rule_leads_to_db_error"
    with patch.object(db_session, 'execute', new_callable=AsyncMock) as mock_execute:
        mock_execute.side_effect = Exception("Simulated DB Error during get")
        fetched_value = await config_utils.get_rule(db_session, test_guild_id, rule_key)

    assert fetched_value is None
    assert f"Error fetching rule '{rule_key}' for guild {test_guild_id}" in caplog.text
    assert "Simulated DB Error during get" in caplog.text

@pytest.mark.asyncio
async def test_get_rule_from_cache(db_session: AsyncSession, test_guild_id: str):
    """Test getting a rule from a provided cache."""
    rule_key = "cached_rule"
    rule_value = "cached_value"
    cache = {rule_key: rule_value}

    fetched_value = await config_utils.get_rule(db_session, test_guild_id, rule_key, rule_cache=cache)
    assert fetched_value == rule_value

@pytest.mark.asyncio
async def test_get_rule_from_db_if_not_in_cache(db_session: AsyncSession, test_guild_id: str):
    """Test getting a rule from DB if not in cache, even if cache is provided."""
    rule_key = "db_fallback_rule"
    rule_value = {"value": 123}
    cache = {"other_cached_rule": "some_data"}

    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule_key, value=rule_value)) # type: ignore[call-arg]
    await db_session.commit()

    fetched_value = await config_utils.get_rule(db_session, test_guild_id, rule_key, rule_cache=cache)
    assert fetched_value == rule_value

@pytest.mark.asyncio
async def test_update_rule_config_create_new(db_session: AsyncSession, test_guild_id: str):
    """Test creating a new rule using update_rule_config."""
    rule_key = "new_rule_via_update"
    rule_value = "initial_value"

    await config_utils.update_rule_config(db_session, test_guild_id, rule_key, rule_value)

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

    db_session.add(RulesConfig(guild_id=test_guild_id, id=str(uuid.uuid4()), key=rule_key, value=initial_value)) # type: ignore[call-arg]
    await db_session.commit()

    await config_utils.update_rule_config(db_session, test_guild_id, rule_key, updated_value)

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

    stmt1 = select(RulesConfig.value).where(RulesConfig.guild_id == test_guild_id, RulesConfig.key == rule_key)
    result1 = await db_session.execute(stmt1)
    fetched_value1 = result1.scalars().first()
    assert fetched_value1 == value1

    stmt2 = select(RulesConfig.value).where(RulesConfig.guild_id == other_guild_id, RulesConfig.key == rule_key)
    result2 = await db_session.execute(stmt2)
    fetched_value2 = result2.scalars().first()
    assert fetched_value2 == value2

@pytest.mark.asyncio
async def test_update_rule_config_db_error_causes_rollback(db_session: AsyncSession, test_guild_id: str):
    rule_key = "rule_causing_error"
    rule_value = "some_value"

    original_commit = db_session.commit
    original_rollback = db_session.rollback

    async def mock_commit_failure() -> None: # Added return type hint
        raise Exception("Simulated DB commit error")

    db_session.commit = AsyncMock(side_effect=mock_commit_failure) # type: ignore[method-assign]
    db_session.rollback = AsyncMock() # type: ignore[method-assign]

    with pytest.raises(Exception, match="Simulated DB commit error"):
        await config_utils.update_rule_config(db_session, test_guild_id, rule_key, rule_value)

    db_session.rollback.assert_awaited_once() # type: ignore[attr-defined]

    db_session.commit = original_commit # type: ignore[method-assign]
    db_session.rollback = original_rollback # type: ignore[method-assign]

    stmt = select(RulesConfig.value).where(RulesConfig.guild_id == test_guild_id, RulesConfig.key == rule_key)
    result = await db_session.execute(stmt)
    fetched_value = result.scalars().first()
    assert fetched_value is None
