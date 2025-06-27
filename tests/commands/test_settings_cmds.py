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
class MockRPGBot(commands.Bot): # Inherit from commands.Bot for more realistic behavior
    def __init__(self, game_manager: Optional[GameManager], *args, **kwargs): # Accept Optional GameManager
        super().__init__(*args, **kwargs)
        self.game_manager = game_manager if game_manager else AsyncMock(spec=GameManager) # type: ignore[assignment]

        # Ensure db_service and get_session are correctly mocked on game_manager
        if not hasattr(self.game_manager, 'db_service') or self.game_manager.db_service is None: # type: ignore[attr-defined]
            self.game_manager.db_service = AsyncMock(spec=DBService) # type: ignore[attr-defined]

        if not hasattr(self.game_manager.db_service, 'get_session') or not isinstance(self.game_manager.db_service.get_session, MagicMock): # type: ignore[attr-defined]
            mock_session_context = AsyncMock()
            mock_session_instance = AsyncMock(spec=AsyncSession)
            mock_session_context.__aenter__.return_value = mock_session_instance
            mock_session_context.__aexit__.return_value = None
            self.game_manager.db_service.get_session = MagicMock(return_value=mock_session_context) # type: ignore[attr-defined]

        # Mock get_db_session if it's on the bot instance directly (used by view_settings, set_timezone)
        if not hasattr(self, 'get_db_session'):
             self.get_db_session = self.game_manager.db_service.get_session


@pytest.fixture
def mock_game_manager_fixture() -> AsyncMock: # Renamed to avoid conflict with class GameManager
    gm = AsyncMock(spec=GameManager)
    gm.db_service = AsyncMock(spec=DBService)
    # Mock specific methods used by the cog on game_manager
    gm.get_player_by_discord_id = AsyncMock()
    # Mock get_rule if used by the cog
    gm.get_rule = AsyncMock(return_value="en") # Default mock for get_rule
    return gm

@pytest.fixture
def mock_bot_instance_fixture(mock_game_manager_fixture: AsyncMock) -> MockRPGBot: # Use the renamed fixture
    # Provide a dummy command_prefix and intents for commands.Bot initialization
    return MockRPGBot(game_manager=mock_game_manager_fixture, command_prefix="!", intents=discord.Intents.default())


@pytest.fixture
def settings_cog(mock_bot_instance_fixture: MockRPGBot) -> SettingsCog: # Use the updated bot instance
    return SettingsCog(bot=mock_bot_instance_fixture) # Argument of type "MockRPGBot" cannot be assigned to parameter "bot" of type "RPGBot" - Fixed by ensuring MockRPGBot inherits commands.Bot or is cast

@pytest.fixture
def mock_interaction_fixture() -> AsyncMock: # Renamed
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.User)
    interaction.user.id = "user123"
    interaction.user.display_name = "TestUser" # Added display_name
    interaction.guild_id = "guild123"
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    interaction.followup = AsyncMock(spec=discord.Webhook)
    return interaction

# --- Tests for /lang and /settings set language ---
@pytest.mark.asyncio
@pytest.mark.parametrize("command_name_param", ["lang_command", "set_language"]) # Renamed parameter
async def test_set_player_language_success(
    settings_cog: SettingsCog,
    mock_interaction_fixture: discord.Interaction, # Use renamed fixture
    mock_game_manager_fixture: AsyncMock, # Use renamed fixture
    command_name_param: str # Use renamed parameter
):
    chosen_lang_choice = LANGUAGE_CHOICES[0]
    user_id_str = str(mock_interaction_fixture.user.id)
    guild_id_str = str(mock_interaction_fixture.guild_id)

    mock_player = Player(id="player_uuid_1", discord_id=user_id_str, guild_id=guild_id_str, selected_language="old_lang")
    mock_game_manager_fixture.get_player_by_discord_id.return_value = mock_player
    mock_game_manager_fixture.db_service.update_player_field = AsyncMock(return_value=True) # Ensure update_player_field is an AsyncMock

    if command_name_param == "set_language":
        # For commands in a group, the callback is on the command object itself.
        # SettingsCog.settings_set_group is an app_commands.Group.
        # We need to get the command from the group.
        set_language_command = next(cmd for cmd in settings_cog.settings_set_group.walk_commands() if cmd.name == "language")
        await set_language_command.callback(settings_cog, mock_interaction_fixture, language_code=chosen_lang_choice) # type: ignore[attr-defined]
    else:
        await settings_cog.lang_command.callback(settings_cog, mock_interaction_fixture, language_code=chosen_lang_choice) # type: ignore[attr-defined]


    mock_game_manager_fixture.get_player_by_discord_id.assert_awaited_once_with(discord_id=user_id_str, guild_id=guild_id_str)
    mock_game_manager_fixture.db_service.update_player_field.assert_awaited_once_with( # Cannot access attribute "update_player_field" for class "AsyncMock" (Pyright error) - Fixed by ensuring it's an AsyncMock on the spec or instance
        player_id=mock_player.id,
        field_name='selected_language',
        value=chosen_lang_choice.value,
        guild_id_str=guild_id_str # Parameter name might be just guild_id in the actual call
    )
    cast(AsyncMock, mock_interaction_fixture.followup.send).assert_awaited_once_with( # Cannot access attribute "send" for class "AsyncMock" (Pyright error) - This is fine, followup is AsyncMock
        f"Your language has been set to: {chosen_lang_choice.name} ({chosen_lang_choice.value})."
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("command_name_param", ["lang_command", "set_language"])
async def test_set_player_language_player_not_found(
    settings_cog: SettingsCog,
    mock_interaction_fixture: discord.Interaction,
    mock_game_manager_fixture: AsyncMock,
    command_name_param: str
):
    chosen_lang_choice = LANGUAGE_CHOICES[1]
    user_id_str = str(mock_interaction_fixture.user.id)
    guild_id_str = str(mock_interaction_fixture.guild_id)

    mock_game_manager_fixture.get_player_by_discord_id.return_value = None
    mock_game_manager_fixture.db_service.update_player_field = AsyncMock() # Ensure it's an AsyncMock


    if command_name_param == "set_language":
        set_language_command = next(cmd for cmd in settings_cog.settings_set_group.walk_commands() if cmd.name == "language")
        await set_language_command.callback(settings_cog, mock_interaction_fixture, language_code=chosen_lang_choice) # type: ignore[attr-defined]
    else:
        await settings_cog.lang_command.callback(settings_cog, mock_interaction_fixture, language_code=chosen_lang_choice) # type: ignore[attr-defined]

    mock_game_manager_fixture.get_player_by_discord_id.assert_awaited_once_with(discord_id=user_id_str, guild_id=guild_id_str)
    mock_game_manager_fixture.db_service.update_player_field.assert_not_called() # Cannot access attribute "update_player_field" for class "AsyncMock" (Pyright error) - Fixed
    cast(AsyncMock, mock_interaction_fixture.followup.send).assert_awaited_once_with(
        "Your player profile was not found. Please ensure you have started playing or contact support."
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("command_name_param", ["lang_command", "set_language"])
async def test_set_player_language_db_update_fails(
    settings_cog: SettingsCog,
    mock_interaction_fixture: discord.Interaction,
    mock_game_manager_fixture: AsyncMock,
    command_name_param: str
):
    chosen_lang_choice = LANGUAGE_CHOICES[0]
    user_id_str = str(mock_interaction_fixture.user.id)
    guild_id_str = str(mock_interaction_fixture.guild_id)

    mock_player = Player(id="player_uuid_dberr", discord_id=user_id_str, guild_id=guild_id_str)
    mock_game_manager_fixture.get_player_by_discord_id.return_value = mock_player
    mock_game_manager_fixture.db_service.update_player_field = AsyncMock(return_value=False) # Simulate DB update failure & Ensure AsyncMock

    if command_name_param == "set_language":
        set_language_command = next(cmd for cmd in settings_cog.settings_set_group.walk_commands() if cmd.name == "language")
        await set_language_command.callback(settings_cog, mock_interaction_fixture, language_code=chosen_lang_choice) # type: ignore[attr-defined]
    else:
        await settings_cog.lang_command.callback(settings_cog, mock_interaction_fixture, language_code=chosen_lang_choice) # type: ignore[attr-defined]

    cast(AsyncMock, mock_interaction_fixture.followup.send).assert_awaited_once_with(
        "Could not save your language preference. Please try again or contact an administrator."
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("command_name_param", ["lang_command", "set_language"])
async def test_set_player_language_general_exception(
    settings_cog: SettingsCog,
    mock_interaction_fixture: discord.Interaction,
    mock_game_manager_fixture: AsyncMock,
    command_name_param: str
):
    chosen_lang_choice = LANGUAGE_CHOICES[0]
    mock_game_manager_fixture.get_player_by_discord_id.side_effect = Exception("Unexpected GM error")

    if command_name_param == "set_language":
        set_language_command = next(cmd for cmd in settings_cog.settings_set_group.walk_commands() if cmd.name == "language")
        await set_language_command.callback(settings_cog, mock_interaction_fixture, language_code=chosen_lang_choice) # type: ignore[attr-defined]
    else:
        await settings_cog.lang_command.callback(settings_cog, mock_interaction_fixture, language_code=chosen_lang_choice) # type: ignore[attr-defined]

    cast(AsyncMock, mock_interaction_fixture.followup.send).assert_awaited_once_with(
        "An unexpected error occurred while trying to set your language. Please try again later."
    )

# --- Tests for /settings view ---
@pytest.mark.asyncio
async def test_view_settings_success(
    settings_cog: SettingsCog,
    mock_interaction_fixture: discord.Interaction,
    mock_bot_instance_fixture: MockRPGBot # Uses bot.get_db_session directly
):
    user_id_str = str(mock_interaction_fixture.user.id)
    guild_id_str = str(mock_interaction_fixture.guild_id)
    mock_user_settings = UserSettings(
        user_id=user_id_str, guild_id=guild_id_str, language_code="en", timezone="UTC"
    )

    with patch('bot.command_modules.settings_cmds.user_settings_crud.get_user_settings', new_callable=AsyncMock, return_value=mock_user_settings) as mock_get_settings:
        view_settings_command = next(cmd for cmd in settings_cog.settings_set_group.walk_commands() if cmd.name == "view")
        await view_settings_command.callback(settings_cog, mock_interaction_fixture) # type: ignore[attr-defined]

        mock_get_settings.assert_awaited_once()
        actual_session_arg = mock_get_settings.call_args.args[0] # session is the first positional arg
        assert isinstance(actual_session_arg, AsyncMock) # Check it's a mock session

        cast(AsyncMock, mock_interaction_fixture.response.send_message).assert_awaited_once() # Cannot access attribute "send_message" for class "AsyncMock" (Pyright error) - This is fine
        send_message_kwargs = cast(AsyncMock, mock_interaction_fixture.response.send_message).call_args.kwargs # Cannot access attribute "call_args" for class "FunctionType" (Pyright error) - This is fine
        sent_embed = send_message_kwargs['embed']
        assert sent_embed.title == f"{mock_interaction_fixture.user.display_name}'s Settings"
        assert sent_embed.fields[0].name == "Language Code"
        assert sent_embed.fields[0].value == "en"
        assert sent_embed.fields[1].name == "Timezone"
        assert sent_embed.fields[1].value == "UTC"

# --- Tests for /settings set timezone ---
@pytest.mark.asyncio
async def test_set_timezone_success(
    settings_cog: SettingsCog,
    mock_interaction_fixture: discord.Interaction,
    mock_bot_instance_fixture: MockRPGBot # Uses bot.get_db_session
):
    timezone_str_param = "Europe/London" # Renamed parameter
    with patch('bot.command_modules.settings_cmds.user_settings_crud.create_or_update_user_settings', new_callable=AsyncMock) as mock_create_update:
        set_timezone_command = next(cmd for cmd in settings_cog.settings_set_group.walk_commands() if cmd.name == "timezone")
        await set_timezone_command.callback(settings_cog, mock_interaction_fixture, timezone_str=timezone_str_param) # type: ignore[attr-defined]

        mock_create_update.assert_awaited_once()
        call_kwargs = mock_create_update.call_args.kwargs
        assert call_kwargs['timezone'] == timezone_str_param

        cast(AsyncMock, mock_interaction_fixture.response.send_message).assert_awaited_once_with( # Cannot access attribute "send_message" for class "AsyncMock" (Pyright error) - This is fine
            f"Your timezone has been set to: {timezone_str_param}.",
            ephemeral=True
        )
