# tests/utils/test_config_utils.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call # Added patch
from sqlalchemy.ext.asyncio import AsyncSession
# Added for more specific mocking/assertion if needed for pg_insert:
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bot.utils import config_utils # Assuming this is the path to your module
from bot.database.models import RulesConfig # For type hinting and mocking return values

@pytest.fixture
def mock_db_session(): # Renamed for consistency
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock() # General mock for execute
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    # Setup for result.all() and result.scalars().first()
    # These will be configured per test as needed.
    # Example: session.execute.return_value.all.return_value = [...]
    # Example: session.execute.return_value.scalars.return_value.first.return_value = ...
    return session

# --- Tests for load_rules_config ---
@pytest.mark.asyncio
async def test_load_rules_config_success(mock_db_session): # Use renamed fixture
    guild_id = "test_guild_1"

    # Mock rows that would be returned by SQLAlchemy's result.all()
    # Each row should have 'key' and 'value' attributes as accessed in load_rules_config
    mock_rules_data = [
        MagicMock(key="rule1", value={"val": 1}),
        MagicMock(key="rule2", value="abc"),
    ]
    mock_db_session.execute.return_value.all.return_value = mock_rules_data

    rules = await config_utils.load_rules_config(mock_db_session, guild_id)

    assert len(rules) == 2
    assert rules["rule1"] == {"val": 1}
    assert rules["rule2"] == "abc"
    mock_db_session.execute.assert_awaited_once()
    # Check the statement passed to execute - basic check for guild_id
    stmt = mock_db_session.execute.call_args[0][0]
    assert str(guild_id) in str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "rules_config.guild_id =" in str(stmt.compile(compile_kwargs={"literal_binds": True}))

@pytest.mark.asyncio
async def test_load_rules_config_empty(mock_db_session):
    guild_id = "test_guild_empty"
    mock_db_session.execute.return_value.all.return_value = [] # No rules

    rules = await config_utils.load_rules_config(mock_db_session, guild_id)
    assert rules == {}
    mock_db_session.execute.assert_awaited_once()

@pytest.mark.asyncio
async def test_load_rules_config_db_error(mock_db_session):
    guild_id = "test_guild_dberror"
    mock_db_session.execute.side_effect = Exception("DB Error")

    rules = await config_utils.load_rules_config(mock_db_session, guild_id)
    assert rules == {} # Should return empty dict on error

# --- Tests for get_rule ---
@pytest.mark.asyncio
async def test_get_rule_cache_hit(mock_db_session):
    guild_id = "test_guild_cache"
    key = "my_rule"
    cached_value = "cached_val"
    rule_cache = {key: cached_value}

    value = await config_utils.get_rule(mock_db_session, guild_id, key, rule_cache)

    assert value == cached_value
    mock_db_session.execute.assert_not_called() # DB should not be hit

@pytest.mark.asyncio
async def test_get_rule_from_db_no_cache_provided(mock_db_session): # Renamed for clarity
    guild_id = "test_guild_db_no_cache"
    key = "db_rule_no_cache"
    db_value = "from_db_no_cache"

    mock_db_session.execute.return_value.scalars.return_value.first.return_value = db_value

    value = await config_utils.get_rule(mock_db_session, guild_id, key, rule_cache=None)

    assert value == db_value
    mock_db_session.execute.assert_awaited_once()
    stmt = mock_db_session.execute.call_args[0][0]
    assert str(guild_id) in str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert str(key) in str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "rules_config.key =" in str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "rules_config.guild_id =" in str(stmt.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_get_rule_cache_miss_found_in_db(mock_db_session): # Test with cache provided but key not in it
    guild_id = "test_guild_db_cache_miss"
    key = "db_rule_cache_miss"
    db_value = "from_db_cache_miss"
    rule_cache = {"other_key": "other_value"} # Cache exists but doesn't have 'key'

    mock_db_session.execute.return_value.scalars.return_value.first.return_value = db_value

    value = await config_utils.get_rule(mock_db_session, guild_id, key, rule_cache=rule_cache)

    assert value == db_value
    mock_db_session.execute.assert_awaited_once()

@pytest.mark.asyncio
async def test_get_rule_not_found_anywhere(mock_db_session): # Renamed for clarity
    guild_id = "test_guild_notfound_anywhere"
    key = "missing_rule_anywhere"

    mock_db_session.execute.return_value.scalars.return_value.first.return_value = None # Rule not in DB

    value = await config_utils.get_rule(mock_db_session, guild_id, key, rule_cache={}) # Empty cache

    assert value is None
    mock_db_session.execute.assert_awaited_once()

@pytest.mark.asyncio
async def test_get_rule_db_error_when_not_in_cache(mock_db_session): # Renamed for clarity
    guild_id = "test_guild_fetch_error_no_cache"
    key = "error_rule_no_cache"
    mock_db_session.execute.side_effect = Exception("DB Fetch Error No Cache")

    value = await config_utils.get_rule(mock_db_session, guild_id, key, rule_cache=None)

    assert value is None # Expect None on error

# --- Tests for update_rule_config ---
@pytest.mark.asyncio
async def test_update_rule_config_upsert_success(mock_db_session):
    guild_id = "guild_upd1"
    key = "rule_to_update"
    new_value = "new_val"

    mock_pg_insert_stmt = MagicMock()
    mock_on_conflict_stmt = MagicMock()

    with patch('bot.utils.config_utils.pg_insert', return_value=mock_pg_insert_stmt) as mock_pg_insert_func:
        mock_pg_insert_stmt.values.return_value = mock_pg_insert_stmt
        mock_pg_insert_stmt.on_conflict_do_update.return_value = mock_on_conflict_stmt

        await config_utils.update_rule_config(mock_db_session, guild_id, key, new_value)

        mock_pg_insert_func.assert_called_once_with(RulesConfig)
        mock_pg_insert_stmt.values.assert_called_once_with(guild_id=guild_id, key=key, value=new_value)
        mock_pg_insert_stmt.on_conflict_do_update.assert_called_once()

        mock_db_session.execute.assert_awaited_once_with(mock_on_conflict_stmt)
        mock_db_session.commit.assert_awaited_once()
        mock_db_session.rollback.assert_not_awaited()

@pytest.mark.asyncio
async def test_update_rule_config_db_error_rolls_back_and_raises(mock_db_session):
    guild_id = "test_guild_upsert_error"
    key = "error_upsert_key"
    value = "error_value"

    mock_pg_insert_stmt = MagicMock()
    mock_on_conflict_stmt = MagicMock()
    with patch('bot.utils.config_utils.pg_insert', return_value=mock_pg_insert_stmt):
        mock_pg_insert_stmt.values.return_value = mock_pg_insert_stmt
        mock_pg_insert_stmt.on_conflict_do_update.return_value = mock_on_conflict_stmt

        mock_db_session.execute.side_effect = Exception("Upsert DB Error")

        with pytest.raises(Exception, match="Upsert DB Error"):
            await config_utils.update_rule_config(mock_db_session, guild_id, key, value)

        mock_db_session.execute.assert_awaited_once_with(mock_on_conflict_stmt)
        mock_db_session.commit.assert_not_awaited()
        mock_db_session.rollback.assert_awaited_once()

@pytest.mark.asyncio
async def test_update_rule_config_updates_existing_value(mock_db_session):
    guild_id = "guild_upd_exist"
    key = "existing_key"
    updated_value = "new"

    mock_pg_insert_stmt = MagicMock()
    mock_on_conflict_stmt = MagicMock()

    with patch('bot.utils.config_utils.pg_insert', return_value=mock_pg_insert_stmt) as mock_pg_insert_func:
        mock_pg_insert_stmt.values.return_value = mock_pg_insert_stmt
        mock_pg_insert_stmt.excluded = MagicMock() # Mock .excluded attribute
        mock_pg_insert_stmt.excluded.value = "mock_excluded_value_placeholder"
        mock_pg_insert_stmt.on_conflict_do_update.return_value = mock_on_conflict_stmt

        await config_utils.update_rule_config(mock_db_session, guild_id, key, updated_value)

        mock_pg_insert_func.assert_called_once_with(RulesConfig)
        mock_pg_insert_stmt.values.assert_called_once_with(guild_id=guild_id, key=key, value=updated_value)

        conflict_args, conflict_kwargs = mock_pg_insert_stmt.on_conflict_do_update.call_args
        assert conflict_kwargs['index_elements'] == ['guild_id', 'key']
        assert 'value' in conflict_kwargs['set_']
        # This assertion checks that the 'value' in set_={'value': ...} is indeed referencing the excluded value placeholder
        assert conflict_kwargs['set_']['value'] == mock_pg_insert_stmt.excluded.value

        mock_db_session.execute.assert_awaited_once_with(mock_on_conflict_stmt)
        mock_db_session.commit.assert_awaited_once()

# --- Tests for Logging ---
@pytest.mark.asyncio
async def test_load_rules_config_logs_activity(mock_db_session, caplog):
    guild_id = "log_guild_1"
    mock_db_session.execute.return_value.all.return_value = []
    with caplog.at_level("DEBUG"):
        await config_utils.load_rules_config(mock_db_session, guild_id)

    assert f"Loading rules configuration for guild_id: {guild_id}" in caplog.text
    assert f"Successfully loaded 0 rules for guild {guild_id}" in caplog.text

@pytest.mark.asyncio
async def test_get_rule_logs_cache_hit_and_miss(mock_db_session, caplog):
    guild_id = "log_guild_2"
    key_cached = "cached_key"
    key_db = "db_key"
    cache = {key_cached: "val1"}
    mock_db_session.execute.return_value.scalars.return_value.first.return_value = "val2"

    with caplog.at_level("DEBUG"):
        await config_utils.get_rule(mock_db_session, guild_id, key_cached, rule_cache=cache)
        assert f"Retrieved rule '{key_cached}' for guild {guild_id} from cache." in caplog.text
        caplog.clear()

        await config_utils.get_rule(mock_db_session, guild_id, key_db, rule_cache=cache)
        assert f"Fetching rule '{key_db}' for guild {guild_id} from database." in caplog.text
        assert f"Successfully fetched rule '{key_db}' for guild {guild_id} from DB." in caplog.text

@pytest.mark.asyncio
async def test_update_rule_config_logs_activity(mock_db_session, caplog):
    guild_id = "log_guild_3"
    key = "log_update_key"
    value = {"data": "test_log_update"}

    mock_pg_insert_stmt = MagicMock()
    mock_on_conflict_stmt = MagicMock()
    with patch('bot.utils.config_utils.pg_insert', return_value=mock_pg_insert_stmt):
        mock_pg_insert_stmt.values.return_value = mock_pg_insert_stmt
        mock_pg_insert_stmt.on_conflict_do_update.return_value = mock_on_conflict_stmt

        with caplog.at_level("INFO"):
            await config_utils.update_rule_config(mock_db_session, guild_id, key, value)

    assert f"Updating rule '{key}' for guild {guild_id} with value: {str(value)[:100]}" in caplog.text
    assert f"Successfully upserted rule '{key}' for guild {guild_id}." in caplog.text
