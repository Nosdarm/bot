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
@patch('bot.bot_core.initialize_new_guild', new_callable=AsyncMock)
@patch('logging.getLogger') # Patch the logger
async def test_on_guild_join_initializes_guild_and_welcomes_system_channel(
    mock_get_logger, mock_initialize_new_guild, mock_bot_for_events, mock_guild
):
    mock_logger_instance = MagicMock()
    mock_get_logger.return_value = mock_logger_instance
    bot, mock_session = mock_bot_for_events

    mock_system_channel = MagicMock(spec=discord.TextChannel)
    mock_system_channel.permissions_for.return_value.send_messages = True
    mock_guild.system_channel = mock_system_channel
    mock_guild.text_channels = [mock_system_channel] # Ensure it's in text_channels for some logic paths

    await bot.on_guild_join(mock_guild)

    mock_initialize_new_guild.assert_awaited_once_with(mock_session, str(mock_guild.id), force_reinitialize=False)
    mock_system_channel.send.assert_called_once()
    # Verify no error/warning logs related to finding channel or sending message
    assert not any("Failed to send welcome message" in call.args[0] for call in mock_logger_instance.error.call_args_list)
    assert not any("Missing permissions to send welcome message" in call.args[0] for call in mock_logger_instance.warning.call_args_list)
    assert not any("Could not find a suitable channel" in call.args[0] for call in mock_logger_instance.warning.call_args_list)

@pytest.mark.asyncio
@patch('bot.bot_core.initialize_new_guild', new_callable=AsyncMock)
@patch('logging.getLogger')
async def test_on_guild_join_welcomes_fallback_channel(
    mock_get_logger, mock_initialize_new_guild, mock_bot_for_events, mock_guild
):
    mock_logger_instance = MagicMock()
    mock_get_logger.return_value = mock_logger_instance
    bot, mock_session = mock_bot_for_events

    mock_guild.system_channel = None # No system channel
    mock_fallback_channel = MagicMock(spec=discord.TextChannel)
    mock_fallback_channel.name = "general"
    mock_fallback_channel.permissions_for.return_value.send_messages = True
    mock_guild.text_channels = [mock_fallback_channel]

    await bot.on_guild_join(mock_guild)

    mock_initialize_new_guild.assert_awaited_once_with(mock_session, str(mock_guild.id), force_reinitialize=False)
    mock_fallback_channel.send.assert_called_once()
    assert not any("Could not find a suitable channel" in call.args[0] for call in mock_logger_instance.warning.call_args_list)

@pytest.mark.asyncio
@patch('bot.bot_core.initialize_new_guild', new_callable=AsyncMock)
@patch('logging.getLogger')
async def test_on_guild_join_no_suitable_channel_for_welcome(
    mock_get_logger, mock_initialize_new_guild, mock_bot_for_events, mock_guild
):
    mock_logger_instance = MagicMock()
    mock_get_logger.return_value = mock_logger_instance
    bot, mock_session = mock_bot_for_events

    mock_guild.system_channel = None
    mock_unsendable_channel = MagicMock(spec=discord.TextChannel)
    mock_unsendable_channel.name = "locked-chat"
    mock_unsendable_channel.permissions_for.return_value.send_messages = False # No perms
    mock_guild.text_channels = [mock_unsendable_channel]

    await bot.on_guild_join(mock_guild)

    mock_initialize_new_guild.assert_awaited_once_with(mock_session, str(mock_guild.id), force_reinitialize=False)
    mock_unsendable_channel.send.assert_not_called() # Should not attempt to send
    # Check for the specific warning log
    assert any("Could not find a suitable channel" in call.args[0] for call in mock_logger_instance.warning.call_args_list)


@pytest.mark.asyncio
@patch('bot.bot_core.initialize_new_guild', new_callable=AsyncMock)
@patch('logging.getLogger')
async def test_on_guild_join_init_fails_gracefully(
    mock_get_logger, mock_initialize_new_guild, mock_bot_for_events, mock_guild
):
    mock_logger_instance = MagicMock()
    mock_get_logger.return_value = mock_logger_instance
    bot, _ = mock_bot_for_events

    mock_initialize_new_guild.side_effect = Exception("Initialization DB Error")

    # Mock a channel to see if send is (not) called
    mock_any_channel = MagicMock(spec=discord.TextChannel)
    mock_any_channel.permissions_for.return_value.send_messages = True
    mock_guild.system_channel = mock_any_channel

    await bot.on_guild_join(mock_guild)

    assert mock_initialize_new_guild.call_count > 0
    # Check that an error was logged
    assert any("Failed to initialize guild" in call.args[0] for call in mock_logger_instance.error.call_args_list)
    # Ensure welcome message was not sent
    mock_any_channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_on_guild_remove_logs_and_clears_cache(mock_bot_for_events, mock_guild):
    bot, _ = mock_bot_for_events
    guild_id_str = str(mock_guild.id)
    bot.game_manager._rules_config_cache[guild_id_str] = {"some_rule": "some_value"}

    # Use the same mock_get_logger pattern if you want to assert specific log messages
    with patch('logging.getLogger') as mock_get_logger_for_remove:
        mock_logger_instance_remove = MagicMock()
        mock_get_logger_for_remove.return_value = mock_logger_instance_remove

        await bot.on_guild_remove(mock_guild)

        mock_logger_instance_remove.warning.assert_any_call(f"Bot removed from guild: {mock_guild.name} (ID: {mock_guild.id})")
        assert guild_id_str not in bot.game_manager._rules_config_cache
        mock_logger_instance_remove.info.assert_any_call(f"Cleared rules_config_cache for removed guild {guild_id_str}")

@pytest.mark.asyncio
async def test_on_ready_runs(mock_bot_for_events, mocker):
    bot, _ = mock_bot_for_events
    bot.tree = AsyncMock()
    bot.turn_processing_task = None # Ensure it's None before on_ready

    await bot.on_ready()

    bot.tree.sync.assert_called()
    assert bot.turn_processing_task is not None
    # To be more robust, check if the task is actually running or created correctly
    # For example, if run_periodic_turn_checks is a method:
    # mock_run_periodic = mocker.patch.object(bot, 'run_periodic_turn_checks', new_callable=AsyncMock)
    # await bot.on_ready()
    # mock_run_periodic.assert_called_once() # Or check asyncio.create_task was called with it

@pytest.mark.asyncio
async def test_on_message_bot_message_ignored(mock_bot_for_events):
    bot, _ = mock_bot_for_events
    message = MagicMock(spec=discord.Message)
    message.author = bot.user # Message from the bot itself
    # Or more generally:
    # message.author = MagicMock(spec=discord.User)
    # message.author.bot = True


    # Mock get_prefix if on_message uses it to differentiate commands from NLU messages
    # For this specific test (ignoring bot messages), get_prefix might not be reached.
    # bot.get_prefix = AsyncMock(return_value="!")

    # If on_message has other processing, ensure it's not triggered
    # For example, if it calls game_manager.process_nlu_message:
    if hasattr(bot.game_manager, 'process_nlu_message'):
        bot.game_manager.process_nlu_message = AsyncMock()

    await bot.on_message(message)

    if hasattr(bot.game_manager, 'process_nlu_message'):
        bot.game_manager.process_nlu_message.assert_not_called()
    # Add other assertions if on_message has more side effects that should be avoided for bot messages.
    # For now, the main check is that it doesn't raise an error and returns early.
    assert True # Implicitly, no error means success for this simple case.
