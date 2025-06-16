# tests/utils/test_config_utils.py
import pytest
from unittest.mock import AsyncMock, MagicMock, call

from sqlalchemy.ext.asyncio import AsyncSession

from bot.utils import config_utils # Assuming this is the path to your module
from bot.database.models import RulesConfig # For type hinting and mocking return values

@pytest.fixture
def mock_db_session_config(): # Renamed to avoid conflict with other test files if conftest is used later
    session = AsyncMock(spec=AsyncSession)
    # Mock execute to return an object that has a scalars() method, which in turn has all() or first()
    mock_execute_result = AsyncMock()
    session.execute.return_value = mock_execute_result
    return session

@pytest.mark.asyncio
async def test_load_rules_config_success(mock_db_session_config):
    guild_id = "test_guild_1"

    # Mock rows that would be returned by SQLAlchemy's result.all()
    # Each row should have 'key' and 'value' attributes as accessed in load_rules_config
    mock_row_1 = MagicMock()
    mock_row_1.key = "exp_rate"
    mock_row_1.value = 1.5

    mock_row_2 = MagicMock()
    mock_row_2.key = "loot_chance"
    mock_row_2.value = 0.5

    # config_utils.load_rules_config uses: result = await db_session.execute(stmt); result.all()
    mock_execute_result = AsyncMock() # This is what 'result' will be
    mock_execute_result.all = MagicMock(return_value=[mock_row_1, mock_row_2]) # .all() is a sync method on result
    mock_db_session_config.execute.return_value = mock_execute_result

    rules = await config_utils.load_rules_config(mock_db_session_config, guild_id)

    mock_db_session_config.execute.assert_awaited_once()
    assert rules == {"exp_rate": 1.5, "loot_chance": 0.5}

@pytest.mark.asyncio
async def test_load_rules_config_empty(mock_db_session_config):
    guild_id = "test_guild_empty"
    mock_execute_result = AsyncMock()
    mock_execute_result.all = MagicMock(return_value=[]) # No rules
    mock_db_session_config.execute.return_value = mock_execute_result

    rules = await config_utils.load_rules_config(mock_db_session_config, guild_id)
    assert rules == {}

@pytest.mark.asyncio
async def test_load_rules_config_db_error(mock_db_session_config):
    guild_id = "test_guild_dberror"
    # If execute itself fails
    mock_db_session_config.execute.side_effect = Exception("DB Error")

    rules = await config_utils.load_rules_config(mock_db_session_config, guild_id)
    assert rules == {} # Should return empty dict on error

@pytest.mark.asyncio
async def test_get_rule_cache_hit(mock_db_session_config):
    guild_id = "test_guild_cache"
    key = "my_rule"
    cached_value = "cached_val"
    rule_cache = {key: cached_value}

    value = await config_utils.get_rule(mock_db_session_config, guild_id, key, rule_cache)

    assert value == cached_value
    mock_db_session_config.execute.assert_not_called() # DB should not be hit

@pytest.mark.asyncio
async def test_get_rule_cache_miss_found_in_db(mock_db_session_config):
    guild_id = "test_guild_db"
    key = "db_rule"
    db_value = "from_db"

    # Correct mocking for: result = await db_session.execute(stmt); rule_value_row = result.scalars().first()
    mock_execute_result = AsyncMock()      # Returned by awaited session.execute()
    mock_scalars_result = MagicMock()      # Returned by result.scalars() (sync method)
    mock_scalars_result.first.return_value = db_value # .first() is a sync method on ScalarResult

    mock_execute_result.scalars = MagicMock(return_value=mock_scalars_result)
    mock_db_session_config.execute.return_value = mock_execute_result

    value = await config_utils.get_rule(mock_db_session_config, guild_id, key, rule_cache=None)

    assert value == db_value
    mock_db_session_config.execute.assert_awaited_once()

@pytest.mark.asyncio
async def test_get_rule_not_found(mock_db_session_config):
    guild_id = "test_guild_notfound"
    key = "missing_rule"

    mock_execute_result = AsyncMock()
    mock_scalars_result = MagicMock()
    mock_scalars_result.first.return_value = None # Rule not in DB
    mock_execute_result.scalars = MagicMock(return_value=mock_scalars_result)
    mock_db_session_config.execute.return_value = mock_execute_result

    value = await config_utils.get_rule(mock_db_session_config, guild_id, key, rule_cache={})

    assert value is None
    mock_db_session_config.execute.assert_awaited_once()

@pytest.mark.asyncio
async def test_get_rule_db_error_on_fetch(mock_db_session_config):
    guild_id = "test_guild_fetch_error"
    key = "error_rule"
    # If execute itself fails
    mock_db_session_config.execute.side_effect = Exception("DB Fetch Error")

    value = await config_utils.get_rule(mock_db_session_config, guild_id, key, rule_cache=None)

    assert value is None # Expect None on error

@pytest.mark.asyncio
async def test_update_rule_config_upsert(mock_db_session_config):
    guild_id = "test_guild_upsert"
    key = "upsert_key"
    value = {"data": "new_value"}

    # This function uses pg_insert which is harder to mock precisely without deeper SQLAlchemy mocking.
    # We'll check that execute and commit are called.
    # A more thorough test would involve an actual test DB or more complex mocking of the insert statement.

    await config_utils.update_rule_config(mock_db_session_config, guild_id, key, value)

    mock_db_session_config.execute.assert_called_once() # Check that some statement was executed
    # The actual statement check for pg_insert is complex here.
    # Example (very basic, might not work for complex statements):
    # executed_stmt_str = str(mock_db_session_config.execute.call_args[0][0])
    # assert "INSERT INTO rules_config" in executed_stmt_str
    # assert "ON CONFLICT (guild_id, key) DO UPDATE" in executed_stmt_str

    mock_db_session_config.commit.assert_awaited_once()
    mock_db_session_config.rollback.assert_not_awaited()

@pytest.mark.asyncio
async def test_update_rule_config_db_error_on_upsert(mock_db_session_config):
    guild_id = "test_guild_upsert_error"
    key = "error_upsert_key"
    value = "error_value"

    mock_db_session_config.execute.side_effect = Exception("Upsert DB Error")

    with pytest.raises(Exception, match="Upsert DB Error"): # Expecting it to re-raise
        await config_utils.update_rule_config(mock_db_session_config, guild_id, key, value)

    mock_db_session_config.rollback.assert_awaited_once()
    mock_db_session_config.commit.assert_not_awaited()

# Example of a more complex argument assertion for execute, if needed:
# from sqlalchemy import text # or your specific statement type
# def assert_statement_details(mock_execute_call, expected_table_name, expected_conditions):
#     called_stmt = mock_execute_call.args[0]
#     # Add logic here to inspect `called_stmt` based on its type (e.g., Select, Insert)
#     # This can be quite involved.
#     pass
