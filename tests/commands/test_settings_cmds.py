# tests/commands/test_settings_cmds.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from sqlalchemy.ext.asyncio import AsyncSession

from bot.command_modules.settings_cmds import SettingsCog, LANGUAGE_CHOICES
from bot.database.models import Player, UserSettings
from bot.game.managers.game_manager import GameManager
from bot.services.db_service import DBService

# Mock RPGBot class
class MockRPGBot:
    def __init__(self, game_manager: GameManager): # Accept GameManager
        self.game_manager = game_manager
        # Mock get_db_session if used directly by the cog for UserSettings,
        # but language setting now goes through GameManager -> DBService -> Player
        mock_async_session = AsyncMock(spec=AsyncSession)
        mock_async_session.commit = AsyncMock()
        db_session_cm = AsyncMock()
        db_session_cm.__aenter__.return_value = mock_async_session
        db_session_cm.__aexit__.return_value = None
        self.get_db_session = MagicMock(return_value=db_session_cm)


@pytest.fixture
def mock_game_manager():
    gm = MagicMock(spec=GameManager)
    gm.db_service = AsyncMock(spec=DBService) # Mock the DBService on GameManager
    # Mock other methods of GameManager if SettingsCog uses them directly
    return gm

@pytest.fixture
def mock_bot_instance(mock_game_manager: GameManager): # Use the GameManager fixture
    return MockRPGBot(game_manager=mock_game_manager)

@pytest.fixture
def settings_cog(mock_bot_instance: MockRPGBot): # Use the updated bot instance
    return SettingsCog(bot=mock_bot_instance)

@pytest.fixture
def mock_interaction():
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.User)
    interaction.user.id = "user123" # Use string IDs consistent with Player model
    interaction.guild_id = "guild123" # Use string IDs
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    # followup is used by deferring responses
    interaction.followup = AsyncMock(spec=discord.Webhook)
    return interaction

# --- Tests for /lang and /settings set language ---
@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", ["lang_command", "set_language"]) # Test both /lang and /settings set language
async def test_set_player_language_success(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction,
    mock_game_manager: GameManager, # Use the GameManager fixture
    command_name: str
):
    chosen_lang_choice = LANGUAGE_CHOICES[0] # e.g., English, value "en"
    user_id_str = str(mock_interaction.user.id)
    guild_id_str = str(mock_interaction.guild_id)

    mock_player = Player(id="player_uuid_1", discord_id=user_id_str, guild_id=guild_id_str, selected_language="old_lang")
    mock_game_manager.get_player_by_discord_id.return_value = mock_player
    mock_game_manager.db_service.update_player_field.return_value = True # Simulate successful update

    command_method = getattr(settings_cog, command_name)
    # For app_commands.command, the callback is on the command object itself,
    # but discord.py usually makes it accessible via the method name if it's a direct method on the cog.
    # If it's part of a group, it's slightly different.
    # settings_cog.set_language is settings_cog.settings_set_group.commands[name="language"]
    # settings_cog.lang_command is a direct command on the cog.

    if command_name == "set_language": # This is under settings_set_group
        await settings_cog.set_language.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice)
    else: # lang_command
        await settings_cog.lang_command.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice)


    mock_game_manager.get_player_by_discord_id.assert_awaited_once_with(discord_id=user_id_str, guild_id=guild_id_str)
    mock_game_manager.db_service.update_player_field.assert_awaited_once_with(
        player_id=mock_player.id,
        field_name='selected_language',
        value=chosen_lang_choice.value,
        guild_id_str=guild_id_str
    )
    mock_interaction.followup.send.assert_awaited_once_with(
        f"Your language has been set to: {chosen_lang_choice.name} ({chosen_lang_choice.value})."
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", ["lang_command", "set_language"])
async def test_set_player_language_player_not_found(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction,
    mock_game_manager: GameManager,
    command_name: str
):
    chosen_lang_choice = LANGUAGE_CHOICES[1]
    user_id_str = str(mock_interaction.user.id)
    guild_id_str = str(mock_interaction.guild_id)

    mock_game_manager.get_player_by_discord_id.return_value = None # Simulate player not found

    if command_name == "set_language":
        await settings_cog.set_language.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice)
    else:
        await settings_cog.lang_command.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice)

    mock_game_manager.get_player_by_discord_id.assert_awaited_once_with(discord_id=user_id_str, guild_id=guild_id_str)
    mock_game_manager.db_service.update_player_field.assert_not_called()
    mock_interaction.followup.send.assert_awaited_once_with(
        "Your player profile was not found. Please ensure you have started playing or contact support."
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", ["lang_command", "set_language"])
async def test_set_player_language_db_update_fails(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction,
    mock_game_manager: GameManager,
    command_name: str
):
    chosen_lang_choice = LANGUAGE_CHOICES[0]
    user_id_str = str(mock_interaction.user.id)
    guild_id_str = str(mock_interaction.guild_id)

    mock_player = Player(id="player_uuid_dberr", discord_id=user_id_str, guild_id=guild_id_str)
    mock_game_manager.get_player_by_discord_id.return_value = mock_player
    mock_game_manager.db_service.update_player_field.return_value = False # Simulate DB update failure

    if command_name == "set_language":
        await settings_cog.set_language.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice)
    else:
        await settings_cog.lang_command.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice)

    mock_interaction.followup.send.assert_awaited_once_with(
        "Could not save your language preference. Please try again or contact an administrator."
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", ["lang_command", "set_language"])
async def test_set_player_language_general_exception(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction,
    mock_game_manager: GameManager,
    command_name: str
):
    chosen_lang_choice = LANGUAGE_CHOICES[0]
    mock_game_manager.get_player_by_discord_id.side_effect = Exception("Unexpected GM error")

    if command_name == "set_language":
        await settings_cog.set_language.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice)
    else:
        await settings_cog.lang_command.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice)

    mock_interaction.followup.send.assert_awaited_once_with(
        "An unexpected error occurred while trying to set your language. Please try again later."
    )

# --- Tests for /settings view ---
@pytest.mark.asyncio
async def test_view_settings_success(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction,
    mock_bot_instance: MockRPGBot # Uses bot.get_db_session directly
):
    user_id_str = str(mock_interaction.user.id)
    guild_id_str = str(mock_interaction.guild_id)
    mock_user_settings = UserSettings(
        user_id=user_id_str,
        guild_id=guild_id_str,
        language_code="en",
        timezone="UTC"
    )
    # Mock the user_settings_crud.get_user_settings function
    with patch('bot.command_modules.settings_cmds.user_settings_crud.get_user_settings', new_callable=AsyncMock, return_value=mock_user_settings) as mock_get_settings:
        await settings_cog.view_settings.callback(settings_cog, mock_interaction)

        mock_get_settings.assert_awaited_once() # Check that it was called with session
        # The actual session object passed to get_user_settings would be mock_bot_instance.get_db_session.return_value.__aenter__.return_value
        # For more precise checking:
        # actual_session_arg = mock_get_settings.call_args[0][0]
        # assert actual_session_arg == mock_bot_instance.get_db_session.return_value.__aenter__.return_value

        mock_interaction.response.send_message.assert_awaited_once()
        sent_embed = mock_interaction.response.send_message.call_args[1]['embed']
        assert sent_embed.title == f"{mock_interaction.user.display_name}'s Settings"
        assert sent_embed.fields[0].name == "Language Code"
        assert sent_embed.fields[0].value == "en"
        assert sent_embed.fields[1].name == "Timezone"
        assert sent_embed.fields[1].value == "UTC"

# --- Tests for /settings set timezone ---
@pytest.mark.asyncio
async def test_set_timezone_success(
    settings_cog: SettingsCog,
    mock_interaction: discord.Interaction,
    mock_bot_instance: MockRPGBot
):
    timezone_str = "Europe/London"
    with patch('bot.command_modules.settings_cmds.user_settings_crud.create_or_update_user_settings', new_callable=AsyncMock) as mock_create_update:
        await settings_cog.set_timezone.callback(settings_cog, mock_interaction, timezone_str=timezone_str)

        mock_create_update.assert_awaited_once()
        # Example of deeper assertion if needed:
        # call_args = mock_create_update.call_args[0] # (session, user_id, guild_id)
        # call_kwargs = mock_create_update.call_args[1] # {'timezone': timezone_str}
        # assert call_kwargs['timezone'] == timezone_str

        mock_interaction.response.send_message.assert_awaited_once_with(
            f"Your timezone has been set to: {timezone_str}.",
            ephemeral=True
        )
