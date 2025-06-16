# tests/core/test_bot_events.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import logging


from bot.bot_core import RPGBot # The class we are testing
# Assuming GameManager and DBService are complex dependencies, mock them simply
from bot.game.managers.game_manager import GameManager
from bot.services.openai_service import OpenAIService
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 123456789012345678
    guild.name = "Test Guild"
    guild.system_channel = None # Default, can be overridden in tests
    guild.text_channels = []    # Default
    guild.me = MagicMock(spec=discord.Member) # For permission checks
    return guild

@pytest.fixture
def mock_bot_for_events():
    # Create a mock for OpenAI service if needed by RPGBot constructor
    mock_openai_service = MagicMock(spec=OpenAIService)

    # Create a mock for GameManager
    mock_game_manager = MagicMock(spec=GameManager)
    mock_game_manager.db_service = MagicMock()
    mock_game_manager.db_service.async_session_factory = MagicMock()
    # Mock the rules config cache for on_guild_remove and on_guild_join (welcome message lang)
    mock_game_manager._rules_config_cache = {}

    # Mock the get_db_session context manager on the bot instance itself
    mock_session = AsyncMock(spec=AsyncSession)
    db_session_cm = AsyncMock()
    db_session_cm.__aenter__.return_value = mock_session
    db_session_cm.__aexit__.return_value = None

    # Minimal RPGBot instantiation
    # Intents are needed for super().__init__
    intents = discord.Intents.default()
    bot = RPGBot(
        game_manager=mock_game_manager,
        openai_service=mock_openai_service,
        command_prefix="!",
        intents=intents
    )
    bot.get_db_session = MagicMock(return_value=db_session_cm) # Patch the instance's method
    bot.user = MagicMock(spec=discord.ClientUser) # Mock bot.user for welcome message
    bot.user.name = "TestBot"
    return bot, mock_session # Return session for assertions if needed

@pytest.mark.asyncio
@patch('bot.bot_core.initialize_new_guild', new_callable=AsyncMock) # Patch initializer
async def test_on_guild_join_initializes_guild_and_welcomes(mock_initialize_new_guild, mock_bot_for_events, mock_guild):
    bot, mock_session = mock_bot_for_events

    # Simulate a system channel for welcome message
    mock_system_channel = MagicMock(spec=discord.TextChannel)
    mock_system_channel.permissions_for.return_value.send_messages = True
    mock_guild.system_channel = mock_system_channel
    mock_guild.name = "Omega Test Server" # For snapshot of message

    await bot.on_guild_join(mock_guild)

    mock_initialize_new_guild.assert_awaited_once_with(mock_session, str(mock_guild.id), force_reinitialize=False)

    # Check if welcome message was attempted
    # This depends on the welcome message logic in on_guild_join
    # If it tries to send to system_channel:
    mock_system_channel.send.assert_called_once()
    # Optional: Snapshot test the welcome message content if it's complex
    # args, kwargs = mock_system_channel.send.call_args
    # assert "Thanks for adding me to **Omega Test Server**!" in args[0]


@pytest.mark.asyncio
@patch('bot.bot_core.initialize_new_guild', new_callable=AsyncMock)
async def test_on_guild_join_init_fails_gracefully(mock_initialize_new_guild, mock_bot_for_events, mock_guild):
    bot, _ = mock_bot_for_events # Don't need session here
    mock_initialize_new_guild.side_effect = Exception("Initialization DB Error")

    # We expect it to log an error but not crash the event handler itself
    await bot.on_guild_join(mock_guild)

    # Assert that initialize_new_guild was called
    assert mock_initialize_new_guild.call_count > 0
    # Welcome message might still be attempted or skipped depending on error handling details
    # For this test, we're primarily concerned that the handler doesn't crash.

@pytest.mark.asyncio
async def test_on_guild_remove_logs_and_clears_cache(mock_bot_for_events, mock_guild):
    bot, _ = mock_bot_for_events
    guild_id_str = str(mock_guild.id)

    # Pre-populate cache for this guild to test clearing
    bot.game_manager._rules_config_cache[guild_id_str] = {"some_rule": "some_value"}

    with patch.object(logging.getLogger('bot.bot_core'), 'warning') as mock_log_warning, \
         patch.object(logging.getLogger('bot.bot_core'), 'info') as mock_log_info: # For cache clear log
        await bot.on_guild_remove(mock_guild)

    mock_log_warning.assert_any_call(f"Bot removed from guild: {mock_guild.name} (ID: {mock_guild.id})")

    # Check if cache was cleared
    assert guild_id_str not in bot.game_manager._rules_config_cache
    mock_log_info.assert_any_call(f"Cleared rules_config_cache for removed guild {guild_id_str}")

# Minimal test for on_ready just to ensure it runs without error with mocks
@pytest.mark.asyncio
async def test_on_ready_runs(mock_bot_for_events):
    bot, _ = mock_bot_for_events
    bot.user = MagicMock(spec=discord.ClientUser) # on_ready uses self.user
    bot.user.name = "TestBot"
    bot.user.id = 12345
    bot.tree = AsyncMock() # Mock command tree
    bot.turn_processing_task = None # Ensure it tries to start it

    await bot.on_ready()
    # Basic assertion: tree.sync was called, turn_processing_task was created
    bot.tree.sync.assert_called()
    assert bot.turn_processing_task is not None

# Minimal test for on_message (very basic, just that it doesn't crash)
@pytest.mark.asyncio
async def test_on_message_bot_message_ignored(mock_bot_for_events):
    bot, _ = mock_bot_for_events
    message = MagicMock(spec=discord.Message)
    message.author.bot = True

    # To prevent error if get_prefix is called and not mocked:
    bot.get_prefix = AsyncMock(return_value="!")

    await bot.on_message(message)
    # No specific output to assert, just that it returned early and didn't process.
    # If there was a processing function, assert it wasn't called.
    # For now, just ensuring no crash.
    assert True # Reached here without error

# TODO: More comprehensive on_message tests would involve mocking game_manager, NLU, player states, etc.
# This is out of scope for "basic" event handler tests here.
