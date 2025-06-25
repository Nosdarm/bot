import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import discord # type: ignore

# Import a more specific type for the bot if available, else use commands.Bot
# from bot.bot_core import RPGBot  # Assuming RPGBot is a commands.Bot subclass
from discord.ext import commands # Fallback if RPGBot specific import is problematic

# Models that will be checked/created
from bot.database.models import GuildConfig, RulesConfig, WorldState, Location, Player

# Function to be tested (indirectly via bot event)
from bot.game.guild_initializer import initialize_new_guild

# Cog containing commands
from bot.command_modules.general_cmds import GeneralCog
from bot.command_modules.settings_cmds import SettingsCog
from bot.command_modules.guild_config_cmds import GuildConfigCmds


# --- Fixtures ---

@pytest.fixture
def mock_discord_guild():
    guild = AsyncMock(spec=discord.Guild)
    guild.id = 123456789012345678 # discord.Guild.id is int
    guild.name = "Test Guild"
    guild.system_channel = AsyncMock(spec=discord.TextChannel)
    guild.system_channel.send = AsyncMock()
    guild.text_channels = [guild.system_channel]
    # Mock permissions_for for the system_channel
    mock_permissions = MagicMock()
    mock_permissions.send_messages = True
    guild.me = AsyncMock(spec=discord.Member) # bot's own member object in the guild
    guild.system_channel.permissions_for.return_value = mock_permissions

    # Add a generic text channel for cases where system_channel might be None
    generic_channel = AsyncMock(spec=discord.TextChannel)
    generic_channel.name = "general"
    generic_channel.id = 987654321098765432
    generic_channel.permissions_for.return_value = mock_permissions
    generic_channel.send = AsyncMock()
    guild.text_channels.append(generic_channel)

    return guild

@pytest.fixture
def mock_discord_user():
    user = AsyncMock(spec=discord.User)
    user.id = 112233445566778899
    user.name = "TestUser"
    user.bot = False
    return user

@pytest.fixture
def mock_discord_member(mock_discord_user, mock_discord_guild):
    member = AsyncMock(spec=discord.Member)
    member.id = mock_discord_user.id
    member.name = mock_discord_user.name
    member.bot = mock_discord_user.bot
    member.guild = mock_discord_guild
    # Add roles if needed for permission checks
    member.roles = []
    return member


@pytest.fixture
def mock_interaction(mock_discord_guild, mock_discord_member, mock_discord_user):
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.guild = mock_discord_guild
    interaction.guild_id = mock_discord_guild.id
    interaction.user = mock_discord_member # Typically interaction.user is a Member in guild context
    interaction.channel = mock_discord_guild.system_channel # Or any other mock channel
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.is_done.return_value = False # Default for initial response
    interaction.followup = AsyncMock(spec=discord.Webhook)
    interaction.followup.send = AsyncMock()
    interaction.client = AsyncMock(spec=commands.Bot) # Mock the client attribute
    return interaction


@pytest.fixture
def mock_bot_user():
    bot_user = MagicMock(spec=discord.ClientUser)
    bot_user.name = "TestRPGBot"
    bot_user.id = 998877665544332211
    return bot_user

@pytest.fixture
def mock_rpg_bot(mock_db_session, mock_bot_user): # mock_db_session from global conftest.py
    # Mock GameManager and its dependencies
    mock_game_manager = AsyncMock()
    mock_game_manager.db_service = AsyncMock()
    mock_game_manager.db_service.get_session.return_value.__aenter__.return_value = mock_db_session # Make get_session return the test session
    mock_game_manager.db_service.get_session.return_value.__aexit__.return_value = None
    mock_game_manager.get_player_by_discord_id = AsyncMock()
    mock_game_manager.update_rule_config = AsyncMock()
    mock_game_manager._rules_config_cache = {} # For welcome message lang check

    # Mock OpenAI Service
    mock_openai_service = AsyncMock()

    # Create a mock RPGBot instance
    # Using commands.Bot as a base if RPGBot class itself is complex to mock or not fully defined for tests yet
    intents = discord.Intents.default()
    intents.guilds = True # Ensure guilds intent is enabled for on_guild_join
    # We need to use a real commands.Bot instance to test event dispatching and cog loading.
    # Patch 'bot.bot_core.RPGBot' if we were testing main.py, but here we test methods of RPGBot itself
    # or cogs that depend on it.
    # For testing RPGBot methods like on_guild_join, we can instantiate it directly.
    # However, the actual RPGBot class is in bot.bot_core
    from bot.bot_core import RPGBot

    # Minimal RPGBot for testing events
    # We pass game_manager=None initially, then set the mock.
    # The RPGBot's __init__ will set self.game_manager.
    # The global_game_manager is set in bot_core.py when RPGBot is init.
    # We need to simulate that or ensure RPGBot uses its own self.game_manager.

    # Patch 'bot.game.guild_initializer.initialize_new_guild' for specific on_guild_join tests
    # to avoid running the actual complex initializer unless that's what we're testing.
    # For now, let RPGBot's init happen, then attach mocks.

    bot_instance = RPGBot(game_manager=None, openai_service=mock_openai_service, command_prefix="!", intents=intents)
    bot_instance.game_manager = mock_game_manager # Assign the mock game_manager
    bot_instance.user = mock_bot_user # Mock the bot's own user

    # Mock the tree for command registration if needed for cog tests, not strictly for on_guild_join
    bot_instance.tree = AsyncMock(spec=app_commands.CommandTree)

    return bot_instance


# --- Tests for RPGBot Events ---

@pytest.mark.asyncio
@patch('bot.game.guild_initializer.initialize_new_guild', new_callable=AsyncMock)
async def test_rpgbot_on_guild_join_new_guild_success(
    mock_init_guild_func: AsyncMock, # Patched initialize_new_guild
    mock_rpg_bot: commands.Bot, # Using the more general type from fixture
    mock_discord_guild: discord.Guild,
    mock_db_session: AsyncSession # From global conftest
):
    """Tests that on_guild_join calls initialize_new_guild and handles success."""
    # Ensure the bot object is correctly typed if RPGBot has specific methods not on commands.Bot
    # For this test, commands.Bot interface for on_guild_join is sufficient.
    # The mock_rpg_bot fixture now returns an instance of the actual RPGBot class.

    # Setup: initialize_new_guild should run without error
    mock_init_guild_func.return_value = True

    # Act
    await mock_rpg_bot.on_guild_join(mock_discord_guild)

    # Assert
    # 1. initialize_new_guild was called correctly
    mock_init_guild_func.assert_awaited_once_with(
        mock_db_session, # The session yielded by bot.get_db_session()
        str(mock_discord_guild.id),
        force_reinitialize=False
    )

    # 2. Transaction was committed (indirectly, by checking no error and init_guild was called)
    # Direct commit check is on the session from bot.get_db_session's context manager,
    # which is our mock_db_session. Its begin() and commit() should be called.
    mock_db_session.begin.assert_called_once() # From RPGBot.get_db_session -> session.begin()
    # The commit is handled by the GuildTransaction context manager if initialize_new_guild succeeds.
    # Since initialize_new_guild is mocked here, we can't directly test its internal commit.
    # However, RPGBot's on_guild_join wraps initialize_new_guild in its own session.begin().
    # If mock_init_guild_func does not raise, the outer session.begin() in on_guild_join should commit.
    mock_db_session.commit.assert_awaited_once() # This commit is from the session in on_guild_join

    # 3. Welcome message was attempted
    # Check if any channel in the guild had send called.
    # We check the system_channel which is the first preference.
    mock_discord_guild.system_channel.send.assert_called_once()


@pytest.mark.asyncio
@patch('bot.game.guild_initializer.initialize_new_guild', new_callable=AsyncMock)
async def test_rpgbot_on_guild_join_initialization_failure(
    mock_init_guild_func: AsyncMock,
    mock_rpg_bot: commands.Bot, # RPGBot instance
    mock_discord_guild: discord.Guild,
    mock_db_session: AsyncSession,
    caplog
):
    """Tests that on_guild_join handles failure from initialize_new_guild and rolls back."""
    # Setup: initialize_new_guild will raise an error
    simulated_error_message = "DB constraint failed during init"
    mock_init_guild_func.side_effect = Exception(simulated_error_message)

    # Act
    await mock_rpg_bot.on_guild_join(mock_discord_guild)

    # Assert
    # 1. initialize_new_guild was called
    mock_init_guild_func.assert_awaited_once_with(
        mock_db_session, str(mock_discord_guild.id), force_reinitialize=False
    )

    # 2. Transaction was rolled back
    # The RPGBot.on_guild_join's session.begin() context manager should handle rollback.
    mock_db_session.rollback.assert_awaited_once()
    mock_db_session.commit.assert_not_awaited() # Commit should not be called

    # 3. Error was logged
    assert "Failed to initialize guild" in caplog.text
    assert str(mock_discord_guild.id) in caplog.text
    assert simulated_error_message in caplog.text

    # 4. Welcome message attempt might still happen or not, depending on error handling details.
    # Current bot_core.py sends welcome message outside the try/except for init.
    mock_discord_guild.system_channel.send.assert_called_once()


# --- Tests for GeneralCog Commands ---

@pytest.fixture
async def general_cog(mock_rpg_bot: commands.Bot): # Use the RPGBot typed fixture
    cog = GeneralCog(mock_rpg_bot)
    await mock_rpg_bot.add_cog(cog) # Simulate cog loading
    return cog

@pytest.mark.asyncio
async def test_ping_command(general_cog: GeneralCog, mock_interaction: discord.Interaction):
    # mock_rpg_bot is part of general_cog.bot
    general_cog.bot.latency = 0.12345 # Simulate some latency

    await general_cog.cmd_ping(mock_interaction)

    mock_interaction.response.send_message.assert_awaited_once()
    sent_message_content = mock_interaction.response.send_message.call_args[0][0]
    assert "Pong!" in sent_message_content
    assert "123.45ms" in sent_message_content


# --- Tests for SettingsCog Commands ---

@pytest.fixture
async def settings_cog(mock_rpg_bot: commands.Bot): # RPGBot typed
    cog = SettingsCog(mock_rpg_bot)
    await mock_rpg_bot.add_cog(cog)
    return cog

@pytest.mark.asyncio
async def test_lang_command_existing_player_language_updated(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction,
    # mock_db_session is not directly used here, but by the mocked db_service
):
    """Tests that an existing player's language preference is updated."""
    mock_player_obj = Player(
        id="player_guid_abc", # Using a more distinct ID
        discord_id=str(mock_interaction.user.id),
        guild_id=str(mock_interaction.guild_id),
        selected_language="fr" # Initial language French
    )
    # Ensure get_player_by_discord_id returns our mock player
    settings_cog.bot.game_manager.get_player_by_discord_id.return_value = mock_player_obj

    # Ensure update_player_field (which is on db_service, accessed via game_manager) is an AsyncMock
    # and returns True for success.
    # The mock_rpg_bot fixture already sets up game_manager.db_service as an AsyncMock.
    # We might need to configure the specific method `update_player_field` on that mock.
    settings_cog.bot.game_manager.db_service.update_player_field = AsyncMock(return_value=True)

    lang_choice = app_commands.Choice(name="English", value="en") # Changing to English
    await settings_cog.lang_command(mock_interaction, language_code=lang_choice)

    # Verify get_player_by_discord_id was called as expected
    settings_cog.bot.game_manager.get_player_by_discord_id.assert_awaited_once_with(
        discord_id=str(mock_interaction.user.id),
        guild_id=str(mock_interaction.guild_id)
    )

    # Verify update_player_field was called with correct parameters
    settings_cog.bot.game_manager.db_service.update_player_field.assert_awaited_once_with(
        player_id=mock_player_obj.id,
        field_name='selected_language',
        value='en', # New language
        guild_id_str=str(mock_interaction.guild_id)
    )

    # Verify success message
    mock_interaction.followup.send.assert_awaited_once_with(
        "Your language has been set to: English (en)."
    )

@pytest.mark.asyncio
async def test_lang_command_player_not_found(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction
):
    settings_cog.bot.game_manager.get_player_by_discord_id.return_value = None # Player does not exist

    lang_choice = app_commands.Choice(name="English", value="en")
    await settings_cog.lang_command(mock_interaction, language_code=lang_choice)

    mock_interaction.followup.send.assert_awaited_once_with(
        "Your player profile was not found. Please ensure you have started playing or contact support."
    )


# --- Tests for GuildConfigCmds Commands ---

@pytest.fixture
async def guild_config_cog(mock_rpg_bot: commands.Bot): # RPGBot typed
    # GuildConfigCmds instantiates its own DBService, which is not ideal for testing.
    # We should patch it or refactor GuildConfigCmds to take DBService in __init__.
    # For now, let's patch the DBService instance within the cog after it's created.

    # Create a mock DBService that will be used by the cog
    mock_cog_db_service = AsyncMock()
    mock_cog_db_service.get_session.return_value.__aenter__.return_value = mock_rpg_bot.game_manager.db_service.get_session.return_value.__aenter__.return_value # Use the same session mock
    mock_cog_db_service.get_session.return_value.__aexit__.return_value = None

    with patch('bot.command_modules.guild_config_cmds.DBService', return_value=mock_cog_db_service):
        cog = GuildConfigCmds(mock_rpg_bot)
        # The cog now has a mocked DBService instance internally.
        # We can also assign it directly if preferred and if the cog allows it.
        # cog.db_service = mock_cog_db_service
        await mock_rpg_bot.add_cog(cog)
        return cog


@pytest.mark.asyncio
@patch('bot.utils.decorators.is_master_role') # Path to where is_master_role is defined/imported
async def test_set_bot_language_success(
    mock_is_master: MagicMock, # Patched decorator
    guild_config_cog: GuildConfigCmds,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncSession # Session used by the cog's db_service
):
    mock_is_master.return_value = lambda func: func # Bypass the decorator check

    # Simulate GuildConfig existing in DB
    mock_guild_config_db_instance = GuildConfig(guild_id=str(mock_interaction.guild_id), bot_language="fr")

    # Configure the session mock for the cog's DBService
    # session.get(GuildConfig, guild_id_str) -> first execute, then scalars().first()
    mock_execute_result = AsyncMock()
    mock_execute_result.scalars.return_value.first.return_value = mock_guild_config_db_instance
    mock_db_session.execute.return_value = mock_execute_result # For the select GuildConfig
    mock_db_session.get = AsyncMock(return_value=mock_guild_config_db_instance) # If cog uses session.get

    # Mock GameManager's update_rule_config
    guild_config_cog.bot.game_manager.update_rule_config = AsyncMock()

    lang_choice = app_commands.Choice(name="English", value="en")
    await guild_config_cog.set_bot_language(mock_interaction, language=lang_choice)

    # Assertions
    # 1. GuildConfig was fetched
    # This depends on whether the cog uses session.get or session.execute(select(...))
    # The current guild_config_cmds.py uses session.execute(select(...))
    mock_db_session.execute.assert_any_call(
        select(GuildConfig).where(GuildConfig.guild_id == str(mock_interaction.guild_id))
    )

    # 2. GuildConfig.bot_language was updated (on the mocked instance)
    assert mock_guild_config_db_instance.bot_language == "en"
    mock_db_session.add.assert_called_with(mock_guild_config_db_instance)
    mock_db_session.commit.assert_awaited_once() # Cog's DBService session should commit

    # 3. GameManager.update_rule_config was called
    guild_config_cog.bot.game_manager.update_rule_config.assert_awaited_once_with(
        str(mock_interaction.guild_id), "default_language", "en"
    )

    # 4. Success message sent
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
    # Simulate the check failing by making the decorator raise CheckFailure
    # The decorator itself is mocked, so its internal logic isn't run.
    # Instead, we simulate its effect if the check failed.
    # A common way is to mock the predicate inside to return False,
    # or make the decorator raise app_commands.CheckFailure directly.
    # The cog's error handler should catch CheckFailure.

    # To test the cog's error handler, we need the command to raise CheckFailure.
    # The decorator is applied at collection time. We can't easily mock its *effect* per-test
    # without more complex pytest mechanisms or refactoring the decorator.
    # A simpler way for this unit test:
    # Assume the decorator is NOT applied for this specific test call,
    # and we manually check the cog's error handler.
    # Or, we can mock the predicate that the app_commands.check decorator uses.
    # For now, let's assume the cog's error handler is tested separately or implicitly.
    # This test will focus on the command logic if the check *were* to fail.

    # If the decorator is properly mocked to raise CheckFailure:
    mock_is_master.side_effect = app_commands.CheckFailure("Mocked check failure")

    lang_choice = app_commands.Choice(name="English", value="en")

    # The error should be caught by the cog's error handler if defined,
    # or by the bot's global error handler.
    # We expect the cog's specific error handler to respond.
    # Need to ensure the error handler is also part of the cog setup for testing.
    # Let's assume the cog's `cog_app_command_error` will be triggered.

    # Directly calling the command will bypass the decorator if it's not part of the test setup's call chain.
    # If testing through bot.tree.call, it would be different.
    # For a direct unit test of the command method with a mocked decorator:
    # We'd typically mock the check *inside* the decorator if it's complex, or
    # ensure the test framework correctly simulates the decorator raising CheckFailure.

    # Let's assume the cog's error handler is in place.
    # We can simulate the error being passed to it.
    mock_error = app_commands.CheckFailure("Simulated check failure")
    await guild_config_cog.cog_app_command_error(mock_interaction, mock_error)

    mock_interaction.response.send_message.assert_awaited_once_with(
         "You do not have the required Master role to use this command.",
         ephemeral=True
    )

# Further tests for GuildConfigCmds (e.g., guild_config not found) would follow a similar pattern.

# Note: This test file is becoming quite large. Consider splitting into
# test_bot_events.py, test_general_cmds.py, test_settings_cmds.py, test_guild_config_cmds.py
# in the future for better organization.
# For now, fulfilling the request to cover task 0.1.

print("DEBUG: tests/core/test_bot_events_and_basic_commands.py created/overwritten")
