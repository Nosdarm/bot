import unittest
import asyncio
import json # Not strictly needed for these tests yet, but good for consistency
import uuid
from typing import Optional, Dict, Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import discord # For Interaction and app_commands

# Modules to be tested
from bot.bot_core import RPGBot
from bot.game.managers.game_manager import GameManager
from bot.game.managers.undo_manager import UndoManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.party_manager import PartyManager
from bot.game.models.character import Character
from bot.game.models.party import Party # Assuming Party model exists if PartyManager.get_party returns it
from bot.command_modules.utility_cmds import UtilityCog
from bot.command_modules.gm_app_cmds import GMAppCog
# from bot.command_modules.game_setup_cmds import is_master_or_admin_check # For patching

class TestUndoCommands(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.guild_id = 12345
        self.user_id = 67890
        self.char_id = "char_test_id_undo_cmd"
        self.party_id = "party_test_id_undo_cmd"
        self.log_id_target = str(uuid.uuid4())

        self.mock_bot = MagicMock(spec=RPGBot)
        self.mock_game_manager = MagicMock(spec=GameManager)
        self.mock_undo_manager = AsyncMock(spec=UndoManager)
        self.mock_character_manager = AsyncMock(spec=CharacterManager)
        self.mock_party_manager = AsyncMock(spec=PartyManager)

        self.mock_bot.game_manager = self.mock_game_manager
        self.mock_game_manager.undo_manager = self.mock_undo_manager
        self.mock_game_manager.character_manager = self.mock_character_manager
        self.mock_game_manager.party_manager = self.mock_party_manager

        # For GM commands, settings might be accessed by is_master_or_admin_check
        # Provide a basic settings dict if needed by the check itself, or mock the check fully.
        self.mock_game_manager._settings = {"bot_admins": [str(self.user_id)]}


        self.utility_cog = UtilityCog(self.mock_bot)
        self.gm_app_cog = GMAppCog(self.mock_bot)

        self.mock_interaction = AsyncMock(spec=discord.Interaction)
        self.mock_interaction.guild_id = self.guild_id
        self.mock_interaction.user = MagicMock(spec=discord.User) # or discord.Member
        self.mock_interaction.user.id = self.user_id
        # Ensure response is an AsyncMock to mock defer and followup.send
        self.mock_interaction.response = AsyncMock(spec=discord.InteractionResponse)
        self.mock_interaction.followup = AsyncMock(spec=discord.Webhook)


    # --- Tests for player /undo command (cmd_undo_last_event in UtilityCog) ---
    async def test_player_undo_success(self):
        mock_char = MagicMock(spec=Character)
        mock_char.id = self.char_id
        self.mock_character_manager.get_character_by_discord_id.return_value = mock_char
        self.mock_undo_manager.undo_last_player_event.return_value = True

        # Corrected: Added self.utility_cog as the first argument
        await self.utility_cog.cmd_undo_last_event.callback(self.utility_cog, self.mock_interaction)

        self.mock_character_manager.get_character_by_discord_id.assert_called_once_with(str(self.guild_id), self.user_id)
        self.mock_undo_manager.undo_last_player_event.assert_called_once_with(str(self.guild_id), self.char_id, num_steps=1)
        self.mock_interaction.followup.send.assert_called_once_with(
            "Your last game action has been reverted. Note: Some complex actions might not be fully undoable automatically.",
            ephemeral=True
        )

    async def test_player_undo_failure_no_char(self):
        self.mock_character_manager.get_character_by_discord_id.return_value = None

        # Corrected: Added self.utility_cog as the first argument
        await self.utility_cog.cmd_undo_last_event.callback(self.utility_cog, self.mock_interaction)

        self.mock_character_manager.get_character_by_discord_id.assert_called_once_with(str(self.guild_id), self.user_id)
        self.mock_interaction.followup.send.assert_called_once_with(
            "You need to have an active character to undo game events. Use `/start_new_character`.",
            ephemeral=True
        )
        self.mock_undo_manager.undo_last_player_event.assert_not_called()

    async def test_player_undo_failure_manager_returns_false(self):
        mock_char = MagicMock(spec=Character)
        mock_char.id = self.char_id
        self.mock_character_manager.get_character_by_discord_id.return_value = mock_char
        self.mock_undo_manager.undo_last_player_event.return_value = False

        # Corrected: Added self.utility_cog as the first argument
        await self.utility_cog.cmd_undo_last_event.callback(self.utility_cog, self.mock_interaction)

        self.mock_undo_manager.undo_last_player_event.assert_called_once_with(str(self.guild_id), self.char_id, num_steps=1)
        self.mock_interaction.followup.send.assert_called_once_with(
            "Failed to revert your last game action. This could be due to the action being too old, too complex, or an internal error. Please contact a GM if the issue persists.",
            ephemeral=True
        )

    # --- Tests for GM /master undo command (cmd_master_undo in GMAppCog) ---
    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_undo_player_success(self, mock_is_gm): # Renamed num_steps to num_steps_arg
        mock_is_gm.return_value = True
        num_steps_arg = 2 # Renamed local variable

        mock_player_char = MagicMock(spec=Character)
        mock_player_char.id = self.char_id
        self.mock_character_manager.get_character.return_value = mock_player_char
        # Ensure party_manager.get_party returns None if we are testing player undo path first
        self.mock_party_manager.get_party.return_value = None

        self.mock_undo_manager.undo_last_player_event.return_value = True

        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_undo.callback(
            self.gm_app_cog, self.mock_interaction, num_steps=num_steps_arg, entity_id=self.char_id
        )

        mock_is_gm.assert_called_once_with(self.mock_interaction)
        self.mock_character_manager.get_character.assert_called_once_with(str(self.guild_id), self.char_id)
        self.mock_undo_manager.undo_last_player_event.assert_called_once_with(
            str(self.guild_id), self.char_id, num_steps=num_steps_arg # Used renamed variable
        )
        self.mock_party_manager.get_party.assert_not_called() # Should not be called if char found
        self.mock_undo_manager.undo_last_party_event.assert_not_called()
        self.mock_interaction.followup.send.assert_called_once_with(
            f"**Мастер:** Последние {num_steps_arg} событий для player '{self.char_id}' были успешно отменены.", # Used renamed variable
            ephemeral=True
        )

    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_undo_party_success(self, mock_is_gm): # Renamed num_steps to num_steps_arg
        mock_is_gm.return_value = True
        num_steps_arg = 1 # Renamed local variable

        # Simulate character not found, then party found
        self.mock_character_manager.get_character.return_value = None
        mock_party_obj = MagicMock(spec=Party)
        mock_party_obj.id = self.party_id
        self.mock_party_manager.get_party.return_value = mock_party_obj

        self.mock_undo_manager.undo_last_party_event.return_value = True

        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_undo.callback(
            self.gm_app_cog, self.mock_interaction, num_steps=num_steps_arg, entity_id=self.party_id
        )

        mock_is_gm.assert_called_once_with(self.mock_interaction)
        self.mock_character_manager.get_character.assert_called_once_with(str(self.guild_id), self.party_id)
        self.mock_party_manager.get_party.assert_called_once_with(str(self.guild_id), self.party_id)
        self.mock_undo_manager.undo_last_party_event.assert_called_once_with(
            str(self.guild_id), self.party_id, num_steps=num_steps_arg # Used renamed variable
        )
        self.mock_undo_manager.undo_last_player_event.assert_not_called()
        self.mock_interaction.followup.send.assert_called_once_with(
            f"**Мастер:** Последние {num_steps_arg} событий для party '{self.party_id}' были успешно отменены.", # Used renamed variable
            ephemeral=True
        )

    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_undo_entity_not_found(self, mock_is_gm): # Renamed num_steps to num_steps_arg
        mock_is_gm.return_value = True
        unknown_entity_id = "unknown_id"
        num_steps_arg = 1 # Renamed local variable (though not used in assertions here, good practice)

        self.mock_character_manager.get_character.return_value = None
        self.mock_party_manager.get_party.return_value = None

        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_undo.callback(
            self.gm_app_cog, self.mock_interaction, num_steps=num_steps_arg, entity_id=unknown_entity_id
        )

        mock_is_gm.assert_called_once_with(self.mock_interaction)
        self.mock_character_manager.get_character.assert_called_once_with(str(self.guild_id), unknown_entity_id)
        self.mock_party_manager.get_party.assert_called_once_with(str(self.guild_id), unknown_entity_id)
        self.mock_undo_manager.undo_last_player_event.assert_not_called()
        self.mock_undo_manager.undo_last_party_event.assert_not_called()
        self.mock_interaction.followup.send.assert_called_once_with(
            f"**Мастер:** Сущность с ID '{unknown_entity_id}' не найдена как игрок или партия.",
            ephemeral=True
        )

    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_undo_no_entity_id_provided(self, mock_is_gm): # Renamed num_steps to num_steps_arg
        mock_is_gm.return_value = True
        num_steps_arg = 1 # Renamed local variable

        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_undo.callback(
            self.gm_app_cog, self.mock_interaction, num_steps=num_steps_arg, entity_id=None
        )

        mock_is_gm.assert_called_once_with(self.mock_interaction)
        self.mock_undo_manager.undo_last_player_event.assert_not_called()
        self.mock_undo_manager.undo_last_party_event.assert_not_called()
        self.mock_interaction.followup.send.assert_called_once_with(
            "**Мастер:** Guild-wide undo без указания ID игрока или партии не поддерживается. Пожалуйста, укажите ID.",
            ephemeral=True
        )

    # --- Tests for GM /master goto_log command (cmd_master_goto_log in GMAppCog) ---
    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_goto_log_player_success(self, mock_is_gm): # Renamed log_id_target to log_id_target_arg
        mock_is_gm.return_value = True
        log_id_target_arg = self.log_id_target # Use the one from setup

        self.mock_character_manager.get_character.return_value = MagicMock(spec=Character) # Found as player
        self.mock_party_manager.get_party.return_value = None
        self.mock_undo_manager.undo_to_log_entry.return_value = True

        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_goto_log.callback(
            self.gm_app_cog, self.mock_interaction, log_id_target=log_id_target_arg, entity_id=self.char_id
        )

        mock_is_gm.assert_called_once_with(self.mock_interaction)
        self.mock_character_manager.get_character.assert_called_once_with(str(self.guild_id), self.char_id)
        self.mock_party_manager.get_party.assert_not_called()
        self.mock_undo_manager.undo_to_log_entry.assert_called_once_with(
            str(self.guild_id), log_id_target_arg, player_or_party_id=self.char_id, entity_type="player" # Used renamed variable
        )
        self.mock_interaction.followup.send.assert_called_once_with(
            f"**Мастер:** События успешно отменены до записи лога '{log_id_target_arg}'. Для сущности (player) '{self.char_id}'.", # Used renamed variable
            ephemeral=True
        )

    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_goto_log_party_success(self, mock_is_gm): # Renamed log_id_target to log_id_target_arg
        mock_is_gm.return_value = True
        log_id_target_arg = self.log_id_target # Use the one from setup

        self.mock_character_manager.get_character.return_value = None # Not a player
        self.mock_party_manager.get_party.return_value = MagicMock(spec=Party) # Found as party
        self.mock_undo_manager.undo_to_log_entry.return_value = True

        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_goto_log.callback(
            self.gm_app_cog, self.mock_interaction, log_id_target=log_id_target_arg, entity_id=self.party_id
        )
        mock_is_gm.assert_called_once_with(self.mock_interaction)
        self.mock_character_manager.get_character.assert_called_once_with(str(self.guild_id), self.party_id)
        self.mock_party_manager.get_party.assert_called_once_with(str(self.guild_id), self.party_id)
        self.mock_undo_manager.undo_to_log_entry.assert_called_once_with(
            str(self.guild_id), log_id_target_arg, player_or_party_id=self.party_id, entity_type="party" # Used renamed variable
        )
        self.mock_interaction.followup.send.assert_called_once_with(
            f"**Мастер:** События успешно отменены до записи лога '{log_id_target_arg}'. Для сущности (party) '{self.party_id}'.", # Used renamed variable
            ephemeral=True
        )

    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_goto_log_guild_wide_success(self, mock_is_gm): # Renamed log_id_target to log_id_target_arg
        mock_is_gm.return_value = True
        log_id_target_arg = self.log_id_target # Use the one from setup
        self.mock_undo_manager.undo_to_log_entry.return_value = True

        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_goto_log.callback(
            self.gm_app_cog, self.mock_interaction, log_id_target=log_id_target_arg, entity_id=None
        )
        mock_is_gm.assert_called_once_with(self.mock_interaction)
        self.mock_undo_manager.undo_to_log_entry.assert_called_once_with(
            str(self.guild_id), log_id_target_arg, player_or_party_id=None, entity_type=None # Used renamed variable
        )
        self.mock_interaction.followup.send.assert_called_once_with(
            f"**Мастер:** События успешно отменены до записи лога '{log_id_target_arg}'. Для всей гильдии.", # Used renamed variable
            ephemeral=True
        )

    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_goto_log_entity_id_not_found(self, mock_is_gm): # Renamed log_id_target to log_id_target_arg
        mock_is_gm.return_value = True
        unknown_entity_id = "id_does_not_exist"
        log_id_target_arg = self.log_id_target # Use the one from setup
        self.mock_character_manager.get_character.return_value = None
        self.mock_party_manager.get_party.return_value = None

        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_goto_log.callback(
            self.gm_app_cog, self.mock_interaction, log_id_target=log_id_target_arg, entity_id=unknown_entity_id
        )
        mock_is_gm.assert_called_once_with(self.mock_interaction)
        self.mock_character_manager.get_character.assert_called_once_with(str(self.guild_id), unknown_entity_id)
        self.mock_party_manager.get_party.assert_called_once_with(str(self.guild_id), unknown_entity_id)
        self.mock_undo_manager.undo_to_log_entry.assert_not_called()
        self.mock_interaction.followup.send.assert_called_once_with(
            f"**Мастер:** Сущность с ID '{unknown_entity_id}' не найдена. Укажите корректный ID игрока/партии или не указывайте ID для отката всех событий гильдии (с осторожностью).",
            ephemeral=True
        )

    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_goto_log_manager_returns_false(self, mock_is_gm): # Renamed log_id_target to log_id_target_arg
        mock_is_gm.return_value = True
        log_id_target_arg = self.log_id_target # Use the one from setup
        self.mock_undo_manager.undo_to_log_entry.return_value = False # Simulate failure in UndoManager

        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_goto_log.callback(
            self.gm_app_cog, self.mock_interaction, log_id_target=log_id_target_arg, entity_id=None # Guild-wide for simplicity
        )
        mock_is_gm.assert_called_once_with(self.mock_interaction)
        self.mock_undo_manager.undo_to_log_entry.assert_called_once()
        self.mock_interaction.followup.send.assert_called_once_with(
            f"**Мастер:** Не удалось отменить события до записи лога '{log_id_target_arg}'. Проверьте логи.", # Used renamed variable
            ephemeral=True
        )

    @patch('bot.command_modules.gm_app_cmds.is_master_or_admin_check', new_callable=AsyncMock)
    async def test_gm_command_not_gm(self, mock_is_gm): # Renamed num_steps to num_steps_arg
        mock_is_gm.return_value = False # Simulate user is NOT a GM or admin
        num_steps_arg = 1 # Renamed local variable

        # Test with cmd_master_undo, but logic should be similar for cmd_master_goto_log
        # Corrected: Added self.gm_app_cog as the first argument
        await self.gm_app_cog.cmd_master_undo.callback(
            self.gm_app_cog, self.mock_interaction, num_steps=num_steps_arg, entity_id=self.char_id
        )

        mock_is_gm.assert_called_once_with(self.mock_interaction)
        # Check that the response was sent directly, not followup, and is the permission error
        self.mock_interaction.response.send_message.assert_called_once_with(
            "**Мастер:** Только Мастера Игры могут использовать эту команду.",
            ephemeral=True
        )
        self.mock_undo_manager.undo_last_player_event.assert_not_called()


# Removed: asyncio.run(unittest.main()) - Test execution should be handled by the test runner
# if __name__ == '__main__':
# asyncio.run(unittest.main())
