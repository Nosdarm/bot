import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands

# Models
from bot.database.models import Player

# Cog to test
from bot.command_modules.action_cmds import ActionModuleCog

# Import RPGBot for type hinting
from bot.bot_core import RPGBot


# --- Fixtures ---
# Assuming mock_rpg_bot, mock_interaction, mock_db_session are from shared conftest

@pytest.fixture
async def action_module_cog(mock_rpg_bot: RPGBot):
    cog = ActionModuleCog(mock_rpg_bot)
    # No need to explicitly add_cog if testing methods directly
    return cog

# --- Tests for ActionModuleCog Commands ---

# Tests for /end_turn
@pytest.mark.asyncio
@patch('bot.command_modules.action_cmds.get_entity_by_attributes', new_callable=AsyncMock)
@patch('bot.command_modules.action_cmds.update_entity', new_callable=AsyncMock)
async def test_cmd_end_turn_success(
    mock_update_entity: AsyncMock,
    mock_get_player: AsyncMock,
    action_module_cog: ActionModuleCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock # Session mock from conftest, used by db_service.get_session
):
    bot_instance = action_module_cog.bot
    game_mngr = bot_instance.game_manager # This is an AsyncMock from mock_rpg_bot

    # Ensure the bot's game_manager.db_service.get_session() returns our mock_db_session
    # This should be configured in the mock_rpg_bot fixture
    game_mngr.db_service.get_session.return_value.__aenter__.return_value = mock_db_session

    guild_id_str = str(mock_interaction.guild_id)
    discord_id_str = str(mock_interaction.user.id)

    mock_player_obj = Player(id="player_end_turn_1", discord_id=discord_id_str, guild_id=guild_id_str, current_game_status="exploring")
    mock_get_player.return_value = mock_player_obj
    mock_update_entity.return_value = mock_player_obj # Assume update_entity returns the updated entity

    await action_module_cog.cmd_end_turn.callback(action_module_cog, mock_interaction)

    mock_get_player.assert_awaited_once_with(
        mock_db_session, Player, {"discord_id": discord_id_str}, guild_id_str
    )
    mock_update_entity.assert_awaited_once_with(
        mock_db_session, mock_player_obj, {"current_game_status": "actions_submitted"}
    )
    mock_db_session.commit.assert_awaited_once()

    mock_interaction.followup.send.assert_awaited_once_with(
        "You have ended your turn. Your actions will be processed soon.", ephemeral=True
    )

@pytest.mark.asyncio
@patch('bot.command_modules.action_cmds.get_entity_by_attributes', new_callable=AsyncMock)
async def test_cmd_end_turn_player_not_found(
    mock_get_player: AsyncMock,
    action_module_cog: ActionModuleCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock
):
    bot_instance = action_module_cog.bot
    game_mngr = bot_instance.game_manager
    game_mngr.db_service.get_session.return_value.__aenter__.return_value = mock_db_session

    mock_get_player.return_value = None # Player not found

    await action_module_cog.cmd_end_turn.callback(action_module_cog, mock_interaction)

    mock_db_session.commit.assert_not_called()
    mock_interaction.followup.send.assert_awaited_once_with(
        "Player not found. Have you registered or started your character?", ephemeral=True
    )

@pytest.mark.asyncio
@patch('bot.command_modules.action_cmds.get_entity_by_attributes', new_callable=AsyncMock)
@patch('bot.command_modules.action_cmds.update_entity', new_callable=AsyncMock)
async def test_cmd_end_turn_db_error_on_update(
    mock_update_entity: AsyncMock,
    mock_get_player: AsyncMock,
    action_module_cog: ActionModuleCog,
    mock_interaction: discord.Interaction,
    mock_db_session: AsyncMock,
    caplog
):
    bot_instance = action_module_cog.bot
    game_mngr = bot_instance.game_manager
    game_mngr.db_service.get_session.return_value.__aenter__.return_value = mock_db_session

    guild_id_str = str(mock_interaction.guild_id)
    discord_id_str = str(mock_interaction.user.id)
    mock_player_obj = Player(id="player_db_error_1", discord_id=discord_id_str, guild_id=guild_id_str)
    mock_get_player.return_value = mock_player_obj

    mock_update_entity.side_effect = Exception("Simulated DB update error")

    await action_module_cog.cmd_end_turn.callback(action_module_cog, mock_interaction)

    # Rollback is handled by the async_session context manager in action_cmds.py
    # So, we check if commit was NOT called.
    # If get_session() itself has a try/except/finally with rollback, that would be tested there.
    # The GuildTransaction used in other places handles rollback. Here, it's a direct session.
    # The test's mock_db_session might also have rollback asserted by its __aexit__ if an error propagates.
    mock_db_session.commit.assert_not_called()
    # To assert rollback, the __aexit__ of the session context manager in cmd_end_turn needs to be checked.
    # This is complex if not using a specific GuildTransaction-like context manager there.
    # For now, checking commit_not_called is a good start.
    # And check logs
    assert "Error in /end_turn" in caplog.text
    assert "Simulated DB update error" in caplog.text

    mock_interaction.followup.send.assert_awaited_once_with(
        "An unexpected error occurred while ending your turn.", ephemeral=True
    )

# TODO: Add tests for other commands in ActionModuleCog like /interact, /fight, /talk
# These will require more extensive mocking of CharacterActionProcessor and other game manager components.

print("DEBUG: tests/commands/test_action_cmds.py created.")
