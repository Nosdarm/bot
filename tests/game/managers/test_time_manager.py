import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Assuming DBService and PostgresAdapter are structured to be mockable
# Adjust imports based on your actual project structure
from bot.services.db_service import DBService
from bot.database.postgres_adapter import PostgresAdapter
from bot.game.managers.time_manager import TimeManager

@pytest_asyncio.fixture
async def mock_db_service():
    mock_adapter = AsyncMock(spec=PostgresAdapter)
    mock_adapter.execute = AsyncMock()
    mock_adapter.execute_many = AsyncMock() # Explicitly mock execute_many

    # If DBService initializes the adapter internally, you might need to patch its __init__
    # or provide a way to inject the mock_adapter.
    # For this example, let's assume DBService can take an adapter instance.
    db_service = DBService() # This might need adjustment based on DBService's actual constructor
    db_service.adapter = mock_adapter
    return db_service

@pytest_asyncio.fixture
async def time_manager(mock_db_service):
    # Initialize TimeManager with the mocked DBService
    # Add other necessary dependencies if any, or mock them as well
    tm = TimeManager(db_service=mock_db_service, settings={})

    # Ensure guild-specific time cache is clean for each test
    tm._current_game_time = {}
    return tm

@pytest.mark.asyncio
async def test_save_state_inserts_new_game_time(time_manager, mock_db_service):
    """Test that save_state correctly inserts a new game time if none exists."""
    guild_id = "test_guild_123"
    game_time = 100.5

    # Set the game time in the TimeManager's cache
    time_manager._current_game_time[guild_id] = game_time

    await time_manager.save_state(guild_id=guild_id)

    # Verify that adapter.execute was called with the correct SQL and parameters
    # for inserting the game time
    mock_db_service.adapter.execute.assert_any_call(
        "INSERT INTO global_state (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (f'game_time_{guild_id}', json.dumps(game_time))
    )

    # Ensure it was called for game time (it's one of potentially two calls in save_state)
    # This check is more robust if save_state makes multiple execute calls.
    found_game_time_call = False
    for call_args in mock_db_service.adapter.execute.call_args_list:
        sql, params = call_args[0]
        if sql.startswith("INSERT INTO global_state") and params[0] == f'game_time_{guild_id}':
            assert params[1] == json.dumps(game_time)
            found_game_time_call = True
            break
    assert found_game_time_call, "The call to save game_time was not found."


@pytest.mark.asyncio
async def test_save_state_updates_existing_game_time(time_manager, mock_db_service):
    """Test that save_state correctly updates an existing game time using ON CONFLICT."""
    guild_id = "test_guild_456"
    initial_game_time = 50.0
    updated_game_time = 150.75

    # Simulate initial save (or existing state) by setting current time
    time_manager._current_game_time[guild_id] = initial_game_time
    await time_manager.save_state(guild_id=guild_id) # This call will be captured

    # Reset mock call history for the adapter before the action we are testing
    mock_db_service.adapter.execute.reset_mock()

    # Update the game time in TimeManager's cache
    time_manager._current_game_time[guild_id] = updated_game_time

    # Call save_state again to trigger the update
    await time_manager.save_state(guild_id=guild_id)

    # Verify adapter.execute was called with the correct SQL for ON CONFLICT DO UPDATE
    # for the updated game time
    mock_db_service.adapter.execute.assert_any_call(
        "INSERT INTO global_state (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (f'game_time_{guild_id}', json.dumps(updated_game_time))
    )

    # More specific check for the game time update call
    found_game_time_update_call = False
    for call_args in mock_db_service.adapter.execute.call_args_list:
        sql, params = call_args[0]
        if sql.startswith("INSERT INTO global_state") and params[0] == f'game_time_{guild_id}':
            assert params[1] == json.dumps(updated_game_time)
            found_game_time_update_call = True
            break
    assert found_game_time_update_call, "The call to update game_time was not found."

    # Ensure it was called at least once (for the game time part of save_state)
    # after the reset_mock(). The exact number of calls might depend on other operations
    # in save_state (like saving timers). We are primarily interested in the game_time call.
    assert mock_db_service.adapter.execute.call_count >= 1
