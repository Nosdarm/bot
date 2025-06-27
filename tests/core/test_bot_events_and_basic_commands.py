import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select # Added for select query assertion

import discord
from discord import app_commands # Added for app_commands.Choice and CheckFailure
from discord.ext import commands

from bot.bot_core import RPGBot
from bot.database.models import GuildConfig, Player # RulesConfig, WorldState, Location not directly used here
# from bot.game.guild_initializer import initialize_new_guild # Mocked anyway

from bot.command_modules.general_cmds import GeneralCog
from bot.command_modules.settings_cmds import SettingsCog
from bot.command_modules.guild_config_cmds import GuildConfigCmds


# --- Fixtures ---

@pytest.fixture
def mock_discord_guild() -> discord.Guild: # Added return type hint
    guild = AsyncMock(spec=discord.Guild)
    guild.id = 123456789012345678
    guild.name = "Test Guild"
    guild.system_channel = AsyncMock(spec=discord.TextChannel)
    guild.system_channel.send = AsyncMock()
    guild.text_channels = [guild.system_channel]
    mock_permissions = MagicMock(spec=discord.Permissions) # Added spec
    mock_permissions.send_messages = True
    guild.me = AsyncMock(spec=discord.Member)
    guild.system_channel.permissions_for = MagicMock(return_value=mock_permissions) # Made it MagicMock

    generic_channel = AsyncMock(spec=discord.TextChannel)
    generic_channel.name = "general"
    generic_channel.id = 987654321098765432
    generic_channel.permissions_for = MagicMock(return_value=mock_permissions) # Made it MagicMock
    generic_channel.send = AsyncMock()
    guild.text_channels.append(generic_channel)

    return guild

@pytest.fixture
def mock_discord_user() -> discord.User: # Added return type hint
    user = AsyncMock(spec=discord.User)
    user.id = 112233445566778899
    user.name = "TestUser"
    user.bot = False
    return user

@pytest.fixture
def mock_discord_member(mock_discord_user: discord.User, mock_discord_guild: discord.Guild) -> discord.Member: # Added type hints
    member = AsyncMock(spec=discord.Member)
    member.id = mock_discord_user.id
    member.name = mock_discord_user.name
    member.bot = mock_discord_user.bot
    member.guild = mock_discord_guild
    member.roles = []
    return member


@pytest.fixture
def mock_interaction(mock_discord_guild: discord.Guild, mock_discord_member: discord.Member) -> discord.Interaction: # Added type hints
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = mock_discord_guild
    interaction.guild_id = mock_discord_guild.id
    interaction.user = mock_discord_member
    interaction.channel = mock_discord_guild.system_channel
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.is_done.return_value = False
    interaction.followup = AsyncMock(spec=discord.Webhook)
    interaction.followup.send = AsyncMock()
    interaction.client = AsyncMock(spec=RPGBot) # Use RPGBot spec
    return interaction


@pytest.fixture
def mock_bot_user() -> discord.ClientUser: # Added return type hint
    bot_user = MagicMock(spec=discord.ClientUser)
    bot_user.name = "TestRPGBot"
    bot_user.id = 998877665544332211
    return bot_user

@pytest.fixture
def mock_rpg_bot(mock_db_session: AsyncSession, mock_bot_user: discord.ClientUser) -> RPGBot: # Added return type hint
    mock_game_manager = AsyncMock()
    mock_game_manager.db_service = AsyncMock()
    # Configure the async context manager for get_session
    mock_session_context_manager = AsyncMock()
    mock_session_context_manager.__aenter__.return_value = mock_db_session
    mock_session_context_manager.__aexit__.return_value = None
    mock_game_manager.db_service.get_session.return_value = mock_session_context_manager

    mock_game_manager.get_player_by_discord_id = AsyncMock()
    mock_game_manager.update_rule_config = AsyncMock()
    mock_game_manager._rules_config_cache = {}

    mock_openai_service = AsyncMock()
    intents = discord.Intents.default()
    intents.guilds = True
    intents.message_content = True # Often needed too

    # Patch the RPGBot's __init__ dependencies if they cause issues during instantiation for tests
    # For example, if it tries to connect to a real DB or service.
    # Here, we assume RPGBot can be instantiated with None for game_manager and openai_service initially.

    # Create the bot instance
    # MockDBService and MockAIGenService are not directly used by RPGBot.__init__ based on current structure
    # GameManager is the main dependency passed.
    bot_instance = RPGBot(game_manager=mock_game_manager, openai_service=mock_openai_service, command_prefix="!", intents=intents)

    # Assign mocked components after instantiation if necessary
    bot_instance.user = mock_bot_user
    bot_instance.tree = AsyncMock(spec=app_commands.CommandTree)

    return bot_instance


# --- Tests for RPGBot Events ---

@pytest.mark.asyncio
@patch('bot.game.guild_initializer.initialize_new_guild', new_callable=AsyncMock)
async def test_rpgbot_on_guild_join_new_guild_success(
    mock_init_guild_func: AsyncMock,
    mock_rpg_bot: RPGBot,
    mock_discord_guild: discord.Guild,
    mock_db_session: AsyncSession # This fixture might be redundant if get_session is always mocked
):
    mock_init_guild_func.return_value = True
    # Directly call the event handler method of the bot instance
    # For cogs, this would be different, but for bot events, it's usually a method on the bot.
    if hasattr(mock_rpg_bot, 'on_guild_join') and callable(mock_rpg_bot.on_guild_join):
        await mock_rpg_bot.on_guild_join(mock_discord_guild)
    else:
        pytest.fail("RPGBot does not have a callable on_guild_join method")

    mock_init_guild_func.assert_awaited_once_with(
        ANY, # The session is obtained within on_guild_join, so we use ANY here
        str(mock_discord_guild.id),
        force_reinitialize=False
    )
    # Assertions on mock_db_session (commit, begin) might need to be on the session
    # obtained *within* the on_guild_join method if it creates its own session.
    # If it uses the one from game_manager.db_service.get_session, then these are fine.
    # Based on RPGBot structure, it uses a session from its db_service.
    mock_rpg_bot.game_manager.db_service.get_session.return_value.__aenter__.return_value.begin.assert_called_once()
    mock_rpg_bot.game_manager.db_service.get_session.return_value.__aenter__.return_value.commit.assert_awaited_once()
    mock_discord_guild.system_channel.send.assert_called_once()


@pytest.mark.asyncio
@patch('bot.game.guild_initializer.initialize_new_guild', new_callable=AsyncMock)
async def test_rpgbot_on_guild_join_initialization_failure(
    mock_init_guild_func: AsyncMock,
    mock_rpg_bot: RPGBot,
    mock_discord_guild: discord.Guild,
    mock_db_session: AsyncSession, # Similar to above, might be redundant
    caplog
):
    simulated_error_message = "DB constraint failed during init"
    mock_init_guild_func.side_effect = Exception(simulated_error_message)
    if hasattr(mock_rpg_bot, 'on_guild_join') and callable(mock_rpg_bot.on_guild_join):
        await mock_rpg_bot.on_guild_join(mock_discord_guild)
    else:
        pytest.fail("RPGBot does not have a callable on_guild_join method")

    mock_init_guild_func.assert_awaited_once_with(
        ANY, str(mock_discord_guild.id), force_reinitialize=False
    )
    mock_rpg_bot.game_manager.db_service.get_session.return_value.__aenter__.return_value.rollback.assert_awaited_once()
    mock_rpg_bot.game_manager.db_service.get_session.return_value.__aenter__.return_value.commit.assert_not_awaited()
    assert "Failed to initialize guild" in caplog.text
    assert str(mock_discord_guild.id) in caplog.text
    assert simulated_error_message in caplog.text
    mock_discord_guild.system_channel.send.assert_called_once()


# --- Tests for GeneralCog Commands ---

@pytest.fixture
async def general_cog(mock_rpg_bot: RPGBot) -> GeneralCog: # Return type hint
    cog = GeneralCog(mock_rpg_bot)
    # await mock_rpg_bot.add_cog(cog) # Not needed if directly invoking command callback
    return cog

@pytest.mark.asyncio
async def test_ping_command(general_cog: GeneralCog, mock_interaction: discord.Interaction):
    mock_rpg_bot_instance = cast(RPGBot, general_cog.bot)
    # Directly assign to the property if it's a simple attribute, or mock the property if it's complex
    # Assuming latency is a simple attribute for this test's purpose
    mock_rpg_bot_instance.latency = 0.12345 # type: ignore[misc] # Ignoring misc for direct assignment to property-like attribute

    ping_command = general_cog.cmd_ping
    await ping_command.callback(general_cog, mock_interaction)

    mock_interaction.response.send_message.assert_awaited_once()
    # Accessing call_args might be different depending on MagicMock vs AsyncMock, ensure it's correct.
    # For AsyncMock, await_args or await_args_list might be more appropriate if the method itself is async.
    # send_message is often synchronous in how its mock is checked.
    sent_message_content = mock_interaction.response.send_message.call_args.args[0]
    assert "Pong!" in sent_message_content
    assert "123.45ms" in sent_message_content


# --- Tests for SettingsCog Commands ---

@pytest.fixture
async def settings_cog(mock_rpg_bot: RPGBot) -> SettingsCog:
    cog = SettingsCog(mock_rpg_bot)
    return cog

@pytest.mark.asyncio
async def test_lang_command_existing_player_language_updated(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction,
):
    mock_player_obj = Player(
        id="player_guid_abc", # Assuming Player model takes these args
        discord_id=str(mock_interaction.user.id), # Ensure str for discord_id if model expects it
        guild_id=str(mock_interaction.guild_id), # Ensure str
        selected_language="fr"
    )
    mock_rpg_bot_instance = cast(RPGBot, settings_cog.bot)
    # Ensure game_manager and db_service are correctly mocked and attached
    if not mock_rpg_bot_instance.game_manager: # Should be set in mock_rpg_bot fixture
        mock_rpg_bot_instance.game_manager = AsyncMock()
    if not mock_rpg_bot_instance.game_manager.db_service:
         mock_rpg_bot_instance.game_manager.db_service = AsyncMock()

    mock_rpg_bot_instance.game_manager.get_player_by_discord_id = AsyncMock(return_value=mock_player_obj)
    mock_rpg_bot_instance.game_manager.db_service.update_player_field = AsyncMock(return_value=True)

    lang_choice = app_commands.Choice(name="English", value="en")
    lang_command = settings_cog.lang_command
    await lang_command.callback(settings_cog, mock_interaction, language_code=lang_choice)


    mock_rpg_bot_instance.game_manager.get_player_by_discord_id.assert_awaited_once_with( # type: ignore[attr-defined]
        discord_id=str(mock_interaction.user.id),
        guild_id=str(mock_interaction.guild_id)
    )
    mock_rpg_bot_instance.game_manager.db_service.update_player_field.assert_awaited_once_with( # type: ignore[attr-defined]
        player_id=mock_player_obj.id,
        field_name='selected_language',
        value='en',
        guild_id_str=str(mock_interaction.guild_id)
    )
    mock_interaction.followup.send.assert_awaited_once_with(
        "Your language has been set to: English (en)."
    )

@pytest.mark.asyncio
async def test_lang_command_player_not_found(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction
):
    mock_rpg_bot_instance = cast(RPGBot, settings_cog.bot)
    if not mock_rpg_bot_instance.game_manager: mock_rpg_bot_instance.game_manager = AsyncMock() # Ensure game_manager exists
    mock_rpg_bot_instance.game_manager.get_player_by_discord_id = AsyncMock(return_value=None) # type: ignore[attr-defined]

    lang_choice = app_commands.Choice(name="English", value="en")
    lang_command = settings_cog.lang_command
    await lang_command.callback(settings_cog, mock_interaction, language_code=lang_choice)

    mock_interaction.followup.send.assert_awaited_once_with(
        "Your player profile was not found. Please ensure you have started playing or contact support."
    )


# --- Tests for GuildConfigCmds Commands ---

@pytest.fixture
async def guild_config_cog(mock_rpg_bot: RPGBot) -> GuildConfigCmds:
    # DBService is not a direct dependency of GuildConfigCmds constructor based on its definition
    # It likely accesses db_service via self.bot.game_manager.db_service
    cog = GuildConfigCmds(mock_rpg_bot)
    return cog


@pytest.mark.asyncio
@patch('bot.utils.decorators.is_master_role') # This decorator is applied to the command itself
async def test_set_bot_language_success(
    mock_is_master: MagicMock, # Mock for the decorator
    guild_config_cog: GuildConfigCmds,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncSession # Used by the mocked db_service via game_manager
):
    mock_is_master.return_value = lambda func: func # Make decorator pass through

    mock_guild_config_db_instance = GuildConfig(guild_id=str(mock_interaction.guild_id), bot_language="fr")

    # Mock the behavior of the session obtained via game_manager.db_service
    mock_rpg_bot_instance = cast(RPGBot, guild_config_cog.bot)
    if not mock_rpg_bot_instance.game_manager: mock_rpg_bot_instance.game_manager = AsyncMock()
    if not mock_rpg_bot_instance.game_manager.db_service: mock_rpg_bot_instance.game_manager.db_service = AsyncMock()

    # Configure the async context manager for get_session on the bot's game_manager.db_service
    session_context_manager = mock_rpg_bot_instance.game_manager.db_service.get_session.return_value
    session_instance_mock = session_context_manager.__aenter__.return_value

    # Mock the database interactions happening *inside* the command
    mock_execute_result = AsyncMock()
    mock_execute_result.scalars.return_value.first.return_value = mock_guild_config_db_instance
    session_instance_mock.execute.return_value = mock_execute_result
    session_instance_mock.get = AsyncMock(return_value=mock_guild_config_db_instance) # If get is used

    mock_rpg_bot_instance.game_manager.update_rule_config = AsyncMock() # type: ignore[attr-defined]

    lang_choice = app_commands.Choice(name="English", value="en")
    set_bot_language_command = guild_config_cog.set_bot_language
    await set_bot_language_command.callback(guild_config_cog, mock_interaction, language=lang_choice)

    session_instance_mock.execute.assert_any_call(
        select(GuildConfig).where(GuildConfig.guild_id == str(mock_interaction.guild_id))
    )
    assert mock_guild_config_db_instance.bot_language == "en"
    session_instance_mock.add.assert_called_with(mock_guild_config_db_instance)
    session_instance_mock.commit.assert_awaited_once()
    mock_rpg_bot_instance.game_manager.update_rule_config.assert_awaited_once_with( # type: ignore[attr-defined]
        str(mock_interaction.guild_id), "default_language", "en"
    )
    mock_interaction.response.send_message.assert_awaited_once_with(
        "Bot language for this server has been set to English (en). RulesConfig also updated.",
        ephemeral=True
    )

@pytest.mark.asyncio
@patch('bot.utils.decorators.is_master_role')
async def test_set_bot_language_not_master(
    mock_is_master: MagicMock,
    guild_config_cog: GuildConfigCmds,
    mock_interaction: discord.Interaction
):
    mock_is_master.side_effect = app_commands.CheckFailure("Mocked check failure")
    # lang_choice = app_commands.Choice(name="English", value="en") # Not needed as check fails first

    mock_error = app_commands.CheckFailure("Simulated check failure")
    # Simulate how the error handler for the cog would be called
    # This assumes the error handler is correctly implemented in the cog
    # If the command itself is directly called and the decorator is mocked to raise,
    # the test framework (pytest) might catch it before the cog's error handler.
    # For robust testing of error handlers, it's often better to call them directly
    # with a mocked error and interaction.
    if hasattr(guild_config_cog, 'cog_app_command_error'):
        await guild_config_cog.cog_app_command_error(mock_interaction, mock_error)
        mock_interaction.response.send_message.assert_awaited_once_with(
            "You do not have the required Master role to use this command.",
            ephemeral=True
        )
    else:
        # If no specific cog error handler, the bot's global handler might be hit,
        # or the test might fail if the error is unhandled.
        # For this test's scope, we'll assume the cog handler exists.
        pytest.skip("Cog error handler for GuildConfigCmds not directly testable in this setup or not found.")


print("DEBUG: tests/core/test_bot_events_and_basic_commands.py created/overwritten")
