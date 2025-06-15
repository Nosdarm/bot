import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# from bot.command_modules.utility_cmds import cmd_lang # Removed import for non-existent command
from bot.bot_core import RPGBot
from bot.game.managers.game_manager import GameManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.models.character import Character as CharacterModel

# class TestUtilityCommands(unittest.IsolatedAsyncioTestCase):
#
#     async def test_cmd_lang_updates_player_language(self):
#         # Mock Interaction
#         interaction_mock = AsyncMock()
#         interaction_mock.response = AsyncMock()
#         interaction_mock.followup = AsyncMock()
#         interaction_mock.client = MagicMock(spec=RPGBot)
#         interaction_mock.guild_id = "test_guild_123"
#         interaction_mock.user = MagicMock()
#         interaction_mock.user.id = "user_discord_456"
#
#         # Mock GameManager and CharacterManager
#         mock_game_manager = MagicMock(spec=GameManager)
#         mock_character_manager = MagicMock(spec=CharacterManager)
#         interaction_mock.client.game_manager = mock_game_manager
#         mock_game_manager.character_manager = mock_character_manager
#
#         # Mock Character
#         mock_character = MagicMock(spec=CharacterModel)
#         mock_character.id = "char_uuid_789"
#         mock_character.selected_language = "en" # Initial language
#
#         mock_character_manager.get_character_by_discord_id = AsyncMock(return_value=mock_character)
#         mock_character_manager.save_character = AsyncMock()
#         mock_character_manager.mark_character_dirty = MagicMock()
#
#         # Execute the command
#         await cmd_lang(interaction_mock, language="ru")
#
#         # Assertions
#         self.assertEqual(mock_character.selected_language, "ru")
#         mock_character_manager.mark_character_dirty.assert_called_once_with(
#             str(interaction_mock.guild_id), mock_character.id
#         )
#         mock_character_manager.save_character.assert_called_once_with(
#             mock_character, guild_id=str(interaction_mock.guild_id)
#         )
#         interaction_mock.response.defer.assert_called_once_with(ephemeral=True)
#         interaction_mock.followup.send.assert_called_once_with(
#             "Ваш язык изменен на русский.", ephemeral=True
#         )
#
#     async def test_cmd_lang_character_not_found(self):
#         # Mock Interaction
#         interaction_mock = AsyncMock()
#         interaction_mock.response = AsyncMock()
#         interaction_mock.followup = AsyncMock()
#         interaction_mock.client = MagicMock(spec=RPGBot)
#         interaction_mock.guild_id = "test_guild_123"
#         interaction_mock.user = MagicMock()
#         interaction_mock.user.id = "user_discord_456"
#
#         # Mock GameManager and CharacterManager
#         mock_game_manager = MagicMock(spec=GameManager)
#         mock_character_manager = MagicMock(spec=CharacterManager)
#         interaction_mock.client.game_manager = mock_game_manager
#         mock_game_manager.character_manager = mock_character_manager
#
#         mock_character_manager.get_character_by_discord_id = AsyncMock(return_value=None) # No character found
#
#         # Execute the command
#         await cmd_lang(interaction_mock, language="ru")
#
#         # Assertions
#         interaction_mock.response.defer.assert_called_once_with(ephemeral=True)
#         interaction_mock.followup.send.assert_called_once_with(
#             "You need to create a character first! Use /start.", ephemeral=True
#         )
#         mock_character_manager.save_character.assert_not_called()
#
#     async def test_cmd_lang_game_manager_not_ready(self):
#         # Mock Interaction
#         interaction_mock = AsyncMock()
#         interaction_mock.response = AsyncMock()
#         interaction_mock.followup = AsyncMock()
#         interaction_mock.client = MagicMock(spec=RPGBot)
#
#         # Game manager not ready
#         interaction_mock.client.game_manager = None
#
#         # Execute the command
#         await cmd_lang(interaction_mock, language="ru")
#
#         # Assertions
#         interaction_mock.response.defer.assert_called_once_with(ephemeral=True)
#         interaction_mock.followup.send.assert_called_once_with(
#             "Error: Game systems (Character Manager) are not fully initialized.", ephemeral=True
#         )

if __name__ == '__main__':
    unittest.main()
