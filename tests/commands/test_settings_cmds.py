# tests/commands/test_settings_cmds.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import discord # For discord.Interaction and app_commands.Choice

# Assuming your Cog and Player model are structured as such
from bot.command_modules.settings_cmds import SettingsCog, LANGUAGE_CHOICES
from bot.database.models import Player

# Mock RPGBot class for type hinting and attribute access
class MockRPGBot:
    def __init__(self):
        self.get_db_session = AsyncMock() # This will be the async context manager
        # Mock other attributes if the cog uses them, e.g., game_manager

@pytest.fixture
def mock_bot_instance():
    bot = MockRPGBot()
    # Configure the get_db_session to return a mock session context
    mock_session_ctx = AsyncMock(spec=discord.ext.commands.Context) # Incorrect type, should be AsyncSession provider

    # Re-mock get_db_session to be an async context manager yielding a mock AsyncSession
    mock_async_session = AsyncMock(spec=AsyncSession)
    mock_async_session.commit = AsyncMock() # Make commit awaitable

    # The context manager itself
    db_session_cm = AsyncMock()
    db_session_cm.__aenter__.return_value = mock_async_session # session object yielded by 'async with'
    db_session_cm.__aexit__.return_value = None # Should return None or an awaitable

    bot.get_db_session.return_value = db_session_cm
    return bot

@pytest.fixture
def settings_cog(mock_bot_instance):
    return SettingsCog(bot=mock_bot_instance) # type: ignore

@pytest.fixture
def mock_interaction():
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.User)
    interaction.user.id = 123456789
    interaction.guild_id = 987654321
    interaction.response = AsyncMock(spec=discord.InteractionResponse)
    interaction.followup = AsyncMock(spec=discord.Webhook) # if followup is used
    return interaction

@pytest.mark.asyncio
async def test_set_language_success(settings_cog: SettingsCog, mock_interaction: discord.Interaction, mock_bot_instance: MockRPGBot):
    chosen_lang_choice = LANGUAGE_CHOICES[0] # e.g., English, value "en"

    # Mock Player instance to be returned by the query
    mock_player_instance = Player(id="player_uuid_1", discord_id=str(mock_interaction.user.id), guild_id=str(mock_interaction.guild_id))
    mock_player_instance.selected_language = "old_lang" # Initial language

    # Mock the session that will be yielded by bot.get_db_session()
    mock_session = mock_bot_instance.get_db_session.return_value.__aenter__.return_value

    # Mock the SQLAlchemy select result chain
    mock_execute_result = AsyncMock()
    mock_scalars_result = AsyncMock()
    mock_scalars_result.first.return_value = mock_player_instance
    mock_execute_result.scalars.return_value = mock_scalars_result
    mock_session.execute.return_value = mock_execute_result

    mock_session.add = MagicMock()

    await settings_cog.set_language.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice) # type: ignore

    # Assertions
    mock_session.execute.assert_called_once() # Check that a query was made for the player
    mock_session.add.assert_called_once_with(mock_player_instance)
    assert mock_player_instance.selected_language == chosen_lang_choice.value
    mock_session.commit.assert_awaited_once()

    mock_interaction.response.send_message.assert_awaited_once_with(
        f"Your language has been set to: {chosen_lang_choice.name} ({chosen_lang_choice.value}).",
        ephemeral=True
    )

@pytest.mark.asyncio
async def test_set_language_player_not_found(settings_cog: SettingsCog, mock_interaction: discord.Interaction, mock_bot_instance: MockRPGBot):
    chosen_lang_choice = LANGUAGE_CHOICES[1] # e.g., Russian, value "ru"

    mock_session = mock_bot_instance.get_db_session.return_value.__aenter__.return_value

    mock_execute_result = AsyncMock()
    mock_scalars_result = AsyncMock()
    mock_scalars_result.first.return_value = None # Simulate player not found
    mock_execute_result.scalars.return_value = mock_scalars_result
    mock_session.execute.return_value = mock_execute_result

    await settings_cog.set_language.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice) # type: ignore

    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()
    mock_interaction.response.send_message.assert_awaited_once_with(
        "Could not find your player record to update the language. Please contact support if this issue persists.",
        ephemeral=True
    )

@pytest.mark.asyncio
async def test_set_language_db_error(settings_cog: SettingsCog, mock_interaction: discord.Interaction, mock_bot_instance: MockRPGBot):
    chosen_lang_choice = LANGUAGE_CHOICES[0]

    mock_session = mock_bot_instance.get_db_session.return_value.__aenter__.return_value
    mock_session.commit.side_effect = Exception("DB commit error") # Simulate error on commit

    # Assume player is found for this test path
    mock_player_instance = Player(id="player_uuid_err", discord_id=str(mock_interaction.user.id), guild_id=str(mock_interaction.guild_id))
    mock_execute_result = AsyncMock()
    mock_scalars_result = AsyncMock()
    mock_scalars_result.first.return_value = mock_player_instance
    mock_execute_result.scalars.return_value = mock_scalars_result
    mock_session.execute.return_value = mock_execute_result

    await settings_cog.set_language.callback(settings_cog, mock_interaction, language_code=chosen_lang_choice) # type: ignore

    mock_interaction.response.send_message.assert_awaited_once_with(
        "An error occurred while trying to set your language. Please try again later.",
        ephemeral=True
    )
    # Rollback would be handled by the get_db_session context manager in RPGBot

# TODO: Add tests for /settings view and /settings set timezone if they are part of this scope
# For now, focusing on the modified set_language command.
# The `view_settings` command would need similar mocking for `user_settings_crud.get_user_settings`.
# The `set_timezone` command would need mocking for `user_settings_crud.create_or_update_user_settings`.
# These are left out as they were not directly part of this subtask's changes.
