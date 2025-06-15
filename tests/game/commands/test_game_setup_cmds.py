import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from bot.command_modules.game_setup_cmds import GameSetupCog
from bot.services.db_service import DBService
from bot.game.models.character import Character
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.game_manager import GameManager
from bot.bot_core import RPGBot

class TestGameSetupCmds(unittest.IsolatedAsyncioTestCase):

    async def test_cmd_start_new_character_initial_values(self):
        """
        Tests that a new character created via cmd_start_new_character
        is initialized with experience=0, level=1, and unspent_xp=0.
        """
        mock_interaction = AsyncMock()
        mock_interaction.user.id = 12345
        mock_interaction.guild_id = "test_guild_1"
        
        mock_db_service = AsyncMock(spec=DBService)
        mock_character_manager = AsyncMock(spec=CharacterManager)
        mock_character_manager.get_character_by_discord_id = AsyncMock(return_value=None)

        # Define GameManager mock and its dependencies BEFORE it's used
        mock_game_manager = MagicMock(spec=GameManager)
        mock_game_manager.character_manager = mock_character_manager

        # Define the character data that start_new_character_session is expected to return
        # This data will be used to create a Character instance
        character_init_data = {
            "id": "test_player_id_1",
            "discord_user_id": 12345, # Ensure this is present
            "name_i18n": {"en": "TestChar"}, # Use name_i18n
            "guild_id": "test_guild_1",
            "location_id": "town_square",
            "stats": {
                "strength": 10, "dexterity": 10, "constitution": 10,
                "intelligence": 10, "wisdom": 10, "charisma": 10,
                "mana": 50, "max_mana": 50, "hp": 100, "max_health": 100
            },
            "level": 1,
            "experience": 0,
            "unspent_xp": 0,
            "selected_language": "en" # Ensure this is present
            # Other fields as necessary for Character constructor
        }

        # Ensure all required fields for Character constructor are in character_init_data
        # Minimal required: id, discord_user_id, name_i18n, guild_id
        # The rest are optional with defaults in the Character model.

        mock_returned_character = Character(**character_init_data)
        mock_game_manager.start_new_character_session = AsyncMock(return_value=mock_returned_character)

        mock_location_manager = AsyncMock()
        mock_location_manager.get_location_instance.return_value = {"name": "Town Square", "id": "town_square"}
        mock_game_manager.location_manager = mock_location_manager

        # Assign GameManager to client mock
        mock_bot_instance = MagicMock(spec=RPGBot)
        mock_bot_instance.game_manager = mock_game_manager
        mock_interaction.client = mock_bot_instance
        
        char_name = "TestChar"
        # player_language is an argument to the command, not char_race

        cog = GameSetupCog(mock_bot_instance)

        await cog.cmd_start_new_character.callback(cog, interaction=mock_interaction, character_name=char_name, player_language=None)

        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

        mock_game_manager.start_new_character_session.assert_called_once_with(
            user_id=12345,
            guild_id="test_guild_1",
            character_name=char_name
        )

        mock_interaction.followup.send.assert_called_once()
        args, kwargs = mock_interaction.followup.send.call_args
        self.assertIn(f"Персонаж '{char_name}' успешно создан!", args[0])
        self.assertEqual(kwargs.get('ephemeral'), True)

    @patch('bot.command_modules.game_setup_cmds.is_master_or_admin_check', return_value=True)
    async def test_cmd_set_bot_language_updates_gm_config(self, mock_is_master_or_admin_check):
        interaction_mock = AsyncMock()
        interaction_mock.response = AsyncMock()
        interaction_mock.guild_id = "test_guild_789"
        interaction_mock.user = MagicMock()

        mock_game_manager = MagicMock(spec=GameManager)
        mock_game_manager.set_default_bot_language = AsyncMock(return_value=True)

        mock_bot_instance = MagicMock(spec=RPGBot)
        mock_bot_instance.game_manager = mock_game_manager
        interaction_mock.client = mock_bot_instance

        cog = GameSetupCog(mock_bot_instance)

        await cog.cmd_set_bot_language.callback(cog, interaction_mock, language_code="ru")

        mock_is_master_or_admin_check.assert_called_once_with(interaction_mock)
        mock_game_manager.set_default_bot_language.assert_called_once_with(
            "ru", str(interaction_mock.guild_id)
        )
        interaction_mock.response.send_message.assert_called_once_with(
            "Язык бота для этой гильдии установлен на 'ru'.", ephemeral=True
        )

    @patch('bot.command_modules.game_setup_cmds.is_master_or_admin_check', return_value=False)
    async def test_cmd_set_bot_language_unauthorized(self, mock_is_master_or_admin_check):
        interaction_mock = AsyncMock()
        interaction_mock.response = AsyncMock()
        interaction_mock.client = MagicMock(spec=RPGBot)
        interaction_mock.guild_id = "test_guild_789"
        interaction_mock.user = MagicMock()

        mock_game_manager = MagicMock(spec=GameManager)
        interaction_mock.client.game_manager = mock_game_manager

        # Instantiate the Cog
        cog = GameSetupCog(bot=interaction_mock.client) # Pass the bot mock

        cog = GameSetupCog(interaction_mock.client)

        await cog.cmd_set_bot_language.callback(cog, interaction_mock, language_code="ru")

        mock_is_master_or_admin_check.assert_called_once_with(interaction_mock)
        mock_game_manager.set_default_bot_language.assert_not_called()
        interaction_mock.response.send_message.assert_called_once_with(
            "Только Мастер или администратор может менять язык бота.", ephemeral=True
        )

if __name__ == '__main__':
    unittest.main()
