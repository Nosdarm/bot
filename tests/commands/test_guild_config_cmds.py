# tests/commands/test_guild_config_cmds.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord # For discord.Interaction, TextChannel, app_commands.Choice

from bot.command_modules.guild_config_cmds import GuildConfigCmds, LANGUAGE_CHOICES
from bot.database.models import GuildConfig
from bot.services.db_service import DBService # For mocking its instance if cog instantiates it

# Mock RPGBot class
class MockRPGBot:
    def __init__(self):
        self.db_service = AsyncMock(spec=DBService) # Mock the db_service attribute
        # Mock game_manager and its _rules_config_cache for testing cache update
        self.game_manager = MagicMock()
        self.game_manager._rules_config_cache = {}
        # self.get_db_session = AsyncMock() # If used by the cog for sessions

# Mock DBService's get_session if GuildConfigCmds instantiates DBService directly
# and uses its get_session method.
@pytest.fixture
def mock_db_service_with_session():
    mock_db_serv = AsyncMock(spec=DBService)
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    db_session_cm = AsyncMock() # The context manager object
    db_session_cm.__aenter__.return_value = mock_session
    db_session_cm.__aexit__.return_value = None

    mock_db_serv.get_session.return_value = db_session_cm
    return mock_db_serv, mock_session


@pytest.fixture
def guild_config_cog(mock_db_service_with_session):
    # If GuildConfigCmds takes bot, and bot has db_service:
    # bot = MockRPGBot()
    # bot.db_service = mock_db_service_with_session[0]
    # cog = GuildConfigCmds(bot)

    # If GuildConfigCmds instantiates DBService itself, we need to patch that instantiation
    with patch('bot.command_modules.guild_config_cmds.DBService', return_value=mock_db_service_with_session[0]):
        bot = MockRPGBot() # Cog needs a bot instance
        cog = GuildConfigCmds(bot)
        # Patch the cog's direct db_service instance if it creates its own
        cog.db_service = mock_db_service_with_session[0]
        # Patch the bot instance on the cog to have the mock GameManager for cache testing
        cog.bot.game_manager = bot.game_manager
    return cog


@pytest.fixture
def mock_interaction_guild():
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.User)
    interaction.user.id = 123
    interaction.guild = MagicMock(spec=discord.Guild) # Ensure guild object exists
    interaction.guild_id = 987
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    return interaction

# --- Tests for /set_bot_language ---
@pytest.mark.asyncio
@patch('bot.command_modules.guild_config_cmds.is_master_role', lambda: lambda func: func) # Bypass decorator
async def test_set_bot_language_success(guild_config_cog: GuildConfigCmds, mock_interaction_guild: discord.Interaction, mock_db_service_with_session):
    mock_db_serv, mock_session = mock_db_service_with_session
    chosen_lang_choice = LANGUAGE_CHOICES[0] # English, "en"
    guild_id_str = str(mock_interaction_guild.guild_id)

    mock_guild_config_instance = GuildConfig(id="gc_uuid_1", guild_id=guild_id_str, bot_language="ru")

    mock_execute_result = AsyncMock()
    mock_scalars_result = AsyncMock()
    mock_scalars_result.first.return_value = mock_guild_config_instance
    mock_execute_result.scalars.return_value = mock_scalars_result
    mock_session.execute.return_value = mock_execute_result

    # Initialize rules cache for this guild to test its update
    guild_config_cog.bot.game_manager._rules_config_cache[guild_id_str] = {"default_language": "ru"}

    await guild_config_cog.set_bot_language.callback(guild_config_cog, mock_interaction_guild, language=chosen_lang_choice) # type: ignore

    mock_session.execute.assert_called_once() # For fetching GuildConfig
    mock_session.add.assert_called_once_with(mock_guild_config_instance)
    assert mock_guild_config_instance.bot_language == chosen_lang_choice.value
    mock_session.commit.assert_awaited_once()

    # Check cache update
    assert guild_config_cog.bot.game_manager._rules_config_cache[guild_id_str]["default_language"] == chosen_lang_choice.value

    mock_interaction_guild.response.send_message.assert_awaited_once_with(
        f"Bot language for this server has been set to {chosen_lang_choice.name} ({chosen_lang_choice.value}).",
        ephemeral=True
    )

@pytest.mark.asyncio
@patch('bot.command_modules.guild_config_cmds.is_master_role', lambda: lambda func: func)
async def test_set_bot_language_guild_config_not_found(guild_config_cog: GuildConfigCmds, mock_interaction_guild: discord.Interaction, mock_db_service_with_session):
    mock_db_serv, mock_session = mock_db_service_with_session
    chosen_lang_choice = LANGUAGE_CHOICES[0]

    mock_execute_result = AsyncMock()
    mock_scalars_result = AsyncMock()
    mock_scalars_result.first.return_value = None # Simulate GuildConfig not found
    mock_execute_result.scalars.return_value = mock_scalars_result
    mock_session.execute.return_value = mock_execute_result

    await guild_config_cog.set_bot_language.callback(guild_config_cog, mock_interaction_guild, language=chosen_lang_choice) # type: ignore

    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()
    mock_interaction_guild.response.send_message.assert_awaited_once_with(
        "Error: Guild configuration not found. The bot might need to be re-invited or initial setup is pending.",
        ephemeral=True
    )

# --- Tests for channel setting commands ---
# These will be similar, mocking GuildConfig fetch and verifying setattr and commit.

@pytest.fixture
def mock_text_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 1122334455
    channel.mention = "<#1122334455>"
    return channel

@pytest.mark.asyncio
@patch('bot.command_modules.guild_config_cmds.is_master_role', lambda: lambda func: func)
async def test_set_game_channel_success(guild_config_cog: GuildConfigCmds, mock_interaction_guild: discord.Interaction, mock_db_service_with_session, mock_text_channel: discord.TextChannel):
    mock_db_serv, mock_session = mock_db_service_with_session
    guild_id_str = str(mock_interaction_guild.guild_id)

    mock_guild_config_instance = GuildConfig(id="gc_uuid_2", guild_id=guild_id_str)

    mock_execute_result = AsyncMock()
    mock_scalars_result = AsyncMock()
    mock_scalars_result.first.return_value = mock_guild_config_instance
    mock_execute_result.scalars.return_value = mock_scalars_result
    mock_session.execute.return_value = mock_execute_result

    await guild_config_cog.set_game_channel.callback(guild_config_cog, mock_interaction_guild, channel=mock_text_channel) # type: ignore

    mock_session.add.assert_called_once_with(mock_guild_config_instance)
    assert mock_guild_config_instance.game_channel_id == str(mock_text_channel.id)
    mock_session.commit.assert_awaited_once()
    mock_interaction_guild.response.send_message.assert_awaited_once_with(
        f"Game channel id has been set to {mock_text_channel.mention}.",
        ephemeral=True
    )

# Add similar tests for set_master_channel and set_system_notifications_channel

@pytest.mark.asyncio
@patch('bot.command_modules.guild_config_cmds.is_master_role', lambda: lambda func: func)
async def test_set_master_channel_success(guild_config_cog: GuildConfigCmds, mock_interaction_guild: discord.Interaction, mock_db_service_with_session, mock_text_channel: discord.TextChannel):
    mock_db_serv, mock_session = mock_db_service_with_session
    guild_id_str = str(mock_interaction_guild.guild_id)
    mock_guild_config_instance = GuildConfig(id="gc_uuid_3", guild_id=guild_id_str)
    mock_execute_result = AsyncMock(); mock_scalars_result = AsyncMock(); mock_scalars_result.first.return_value = mock_guild_config_instance
    mock_execute_result.scalars.return_value = mock_scalars_result; mock_session.execute.return_value = mock_execute_result

    await guild_config_cog.set_master_channel.callback(guild_config_cog, mock_interaction_guild, channel=mock_text_channel) # type: ignore

    assert mock_guild_config_instance.master_channel_id == str(mock_text_channel.id)
    mock_interaction_guild.response.send_message.assert_awaited_once_with(
        f"Master channel id has been set to {mock_text_channel.mention}.", ephemeral=True
    )

@pytest.mark.asyncio
@patch('bot.command_modules.guild_config_cmds.is_master_role', lambda: lambda func: func)
async def test_set_system_notifications_channel_success(guild_config_cog: GuildConfigCmds, mock_interaction_guild: discord.Interaction, mock_db_service_with_session, mock_text_channel: discord.TextChannel):
    mock_db_serv, mock_session = mock_db_service_with_session
    guild_id_str = str(mock_interaction_guild.guild_id)
    mock_guild_config_instance = GuildConfig(id="gc_uuid_4", guild_id=guild_id_str)
    mock_execute_result = AsyncMock(); mock_scalars_result = AsyncMock(); mock_scalars_result.first.return_value = mock_guild_config_instance
    mock_execute_result.scalars.return_value = mock_scalars_result; mock_session.execute.return_value = mock_execute_result

    await guild_config_cog.set_system_notifications_channel.callback(guild_config_cog, mock_interaction_guild, channel=mock_text_channel) # type: ignore

    assert mock_guild_config_instance.system_notifications_channel_id == str(mock_text_channel.id)
    mock_interaction_guild.response.send_message.assert_awaited_once_with(
        f"System notifications channel id has been set to {mock_text_channel.mention}.", ephemeral=True
    )

# Test for CheckFailure (is_master_role fails)
@pytest.mark.asyncio
async def test_guild_config_cmds_check_failure(guild_config_cog: GuildConfigCmds, mock_interaction_guild: discord.Interaction):
    # Simulate a CheckFailure by not patching is_master_role and assuming it would fail
    # Or, more directly, mock the error handler
    error = app_commands.CheckFailure("Mocked check failure")

    # Directly call the error handler
    await guild_config_cog.cog_app_command_error(mock_interaction_guild, error)

    mock_interaction_guild.response.send_message.assert_awaited_once_with(
        "You do not have the required Master role to use this command.",
        ephemeral=True
    )

# Note: The @patch for is_master_role bypasses the actual decorator logic.
# Testing the decorator itself would be separate, or require more complex interaction setup.
# The current cog instantiation patches DBService globally for the module.
# If GuildConfigCmds used self.bot.get_db_session(), the mock_bot_instance fixture would be more relevant.
# The tests assume that GuildConfigCmds correctly instantiates or is provided a DBService.
# The patch for DBService needs to be active when GuildConfigCmds is imported or instantiated.
# A fixture that provides a fully initialized cog with all dependencies mocked is often a good pattern.
# The current `guild_config_cog` fixture attempts this by patching DBService during cog instantiation.
from discord import app_commands # ensure app_commands is available for CheckFailure test
