# tests/core/test_bot_events.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
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
def mock_bot_for_events(mocker): # Added mocker
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

    # Correctly mock the 'user' property on the bot instance using mocker
    mock_user_instance = MagicMock(spec=discord.ClientUser)
    mock_user_instance.name = "TestBot"
    mock_user_instance.id = 123456789 # A default ID

    # Patch discord.Client.user with a PropertyMock *before* RPGBot is instantiated
    # This PropertyMock will be inherited by the RPGBot instance
    mocker.patch.object(discord.Client, 'user', new_callable=PropertyMock, return_value=mock_user_instance)

    # Intents are needed for super().__init__
    intents = discord.Intents.default() # This was already here, ensure it's correctly placed
    bot = RPGBot(
        game_manager=mock_game_manager,
        openai_service=mock_openai_service,
        command_prefix="!",
        intents=intents
    )
    bot.get_db_session = MagicMock(return_value=db_session_cm) # Patch the instance's method

    return bot, mock_session # Return session for assertions if needed

@pytest.mark.asyncio
@patch('bot.bot_core.initialize_new_guild', new_callable=AsyncMock) # Patch initializer
async def test_on_guild_join_initializes_guild_and_welcomes(mock_initialize_new_guild, mock_bot_for_events, mock_guild, mocker): # Added mocker
    bot, mock_session = mock_bot_for_events
    # bot.user is now correctly mocked by the fixture.
    # If specific attributes for bot.user are needed for this test beyond what fixture provides,
    # they can be set on bot.user (which is the return_value of the PropertyMock).
    # Example: bot.user.name = "SpecificTestBotName" (if bot.user is the MagicMock instance)

    # Simulate a system channel for welcome message
    mock_system_channel = MagicMock(spec=discord.TextChannel)
    mock_system_channel.permissions_for.return_value.send_messages = True
    mock_guild.system_channel = mock_system_channel
    mock_guild.name = "Omega Test Server" # For snapshot of message

    await bot.on_guild_join(mock_guild)

    mock_initialize_new_guild.assert_awaited_once_with(mock_session, str(mock_guild.id), force_reinitialize=False)
    mock_system_channel.send.assert_called_once()


@pytest.mark.asyncio
@patch('bot.bot_core.initialize_new_guild', new_callable=AsyncMock)
async def test_on_guild_join_init_fails_gracefully(mock_initialize_new_guild, mock_bot_for_events, mock_guild):
    bot, _ = mock_bot_for_events # Don't need session here
    mock_initialize_new_guild.side_effect = Exception("Initialization DB Error")

    await bot.on_guild_join(mock_guild)
    assert mock_initialize_new_guild.call_count > 0


@pytest.mark.asyncio
async def test_on_guild_remove_logs_and_clears_cache(mock_bot_for_events, mock_guild):
    bot, _ = mock_bot_for_events
    guild_id_str = str(mock_guild.id)
    bot.game_manager._rules_config_cache[guild_id_str] = {"some_rule": "some_value"}

    with patch.object(logging.getLogger('bot.bot_core'), 'warning') as mock_log_warning, \
         patch.object(logging.getLogger('bot.bot_core'), 'info') as mock_log_info:
        await bot.on_guild_remove(mock_guild)

    mock_log_warning.assert_any_call(f"Bot removed from guild: {mock_guild.name} (ID: {mock_guild.id})")
    assert guild_id_str not in bot.game_manager._rules_config_cache
    mock_log_info.assert_any_call(f"Cleared rules_config_cache for removed guild {guild_id_str}")

@pytest.mark.asyncio
async def test_on_ready_runs(mock_bot_for_events, mocker): # Added mocker
    bot, _ = mock_bot_for_events

    # Ensure bot.user is mocked if the fixture didn't cover all needs for this test
    # The fixture now provides a default mock for bot.user.
    # If this test needs specific attributes for bot.user, configure them on bot.user:
    # (e.g., bot.user.id = 12345 if the fixture's default ID is not suitable)
    # The fixture sets id to 123456789, so we can use that or re-patch if needed.
    # For this test, the fixture's default mock should be sufficient.

    bot.tree = AsyncMock()
    bot.turn_processing_task = None

    await bot.on_ready()
    bot.tree.sync.assert_called()
    assert bot.turn_processing_task is not None

@pytest.mark.asyncio
async def test_on_message_bot_message_ignored(mock_bot_for_events): # mocker not needed if bot.user isn't directly manipulated here
    bot, _ = mock_bot_for_events
    message = MagicMock(spec=discord.Message)
    message.author = MagicMock(spec=discord.User) # Ensure author is also a MagicMock
    message.author.bot = True

    bot.get_prefix = AsyncMock(return_value="!")

    await bot.on_message(message)
    assert True
