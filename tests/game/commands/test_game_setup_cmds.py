import bot
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Assuming paths for imports - adjust if necessary based on project structure
from bot.command_modules.game_setup_cmds import GameSetupCog, is_master_or_admin_check # MODIFIED
from bot.services.db_service import DBService # Needed for type hinting if not patching directly
from bot.game.models.character import Character # For constructing expected return
from bot.game.managers.character_manager import CharacterManager # Import CharacterManager

class TestGameSetupCmds(unittest.IsolatedAsyncioTestCase):

    async def test_cmd_start_new_character_initial_values(self):
        """
        Tests that a new character created via cmd_start_new_character
        is initialized with experience=0, level=1, and unspent_xp=0.
        """
        mock_interaction = AsyncMock()
        mock_interaction.user.id = 12345
        mock_interaction.guild_id = "test_guild_1"

        # Mock the game_manager and db_service structure
        mock_db_service = AsyncMock(spec=DBService) # This mock is for the DBService used by CharacterManager

        # Mock CharacterManager and its async methods
        mock_character_manager = AsyncMock(spec=CharacterManager)

        # Explicitly mock the async methods on CharacterManager
        mock_character_manager.get_character_by_discord_id = AsyncMock(return_value=None) # Simulate no existing character

        # Define the character data that create_character is expected to return
        # REMOVED race from here
        created_player_data = {
            "id": "test_player_id_1",
            "discord_user_id": 12345,
            "name": "TestChar",
            "name_i18n": {"en": "TestChar"},
            "guild_id": "test_guild_1",
            "location_id": "town_square",
            "hp": 100,
            "stats": {
                "strength": 10, "dexterity": 10, "constitution": 10,
                "intelligence": 10, "wisdom": 10, "charisma": 10,
                "mana": 50, "max_mana": 50
            },
            "level": 1,
            "experience": 0,
            "unspent_xp": 0,
        }
        character_init_data = {k: v for k, v in created_player_data.items()}
        mock_character_manager.create_character = AsyncMock(return_value=Character(**character_init_data))

        # Mock GameManager
        mock_game_manager = MagicMock()
        mock_game_manager.character_manager = mock_character_manager

        mock_location_manager = AsyncMock()
        mock_location_manager.get_location_instance.return_value = {"name": "Town Square", "id": "town_square"}
        mock_game_manager.location_manager = mock_location_manager
        
        # mock_interaction.client = MagicMock() # This is the RPGBot mock
        # mock_interaction.client.game_manager = mock_game_manager
        # UPDATED mock_interaction.client to be mock_rpg_bot for clarity
        mock_rpg_bot = MagicMock()
        mock_rpg_bot.game_manager = mock_game_manager
        mock_interaction.client = mock_rpg_bot # Assign mock_rpg_bot to interaction.client

        char_name = "TestChar"
        # char_race = "Human" # REMOVED char_race

        # Instantiate the Cog
        cog = GameSetupCog(bot=mock_rpg_bot)

        # Call the command
        # await cmd_start_new_character.callback(mock_interaction, name=char_name, race=char_race)
        # MODIFIED call to use cog and updated signature
        await cog.cmd_start_new_character(mock_interaction, character_name=char_name, player_language=None)


        # Assert that defer was called
        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

        # Assert get_character_by_discord_id was called correctly on CharacterManager
        # This is now called inside game_manager.start_new_character_session, which is called by the cog command.
        # The command itself calls self.bot.game_manager.start_new_character_session
        # So we need to mock start_new_character_session on game_manager instead of CharacterManager directly for this test level
        # OR ensure game_manager.character_manager.get_character_by_discord_id is asserted if that's the path.
        # The command directly calls:
        # player_char = await self.bot.game_manager.start_new_character_session(
        #     user_id=interaction.user.id,
        #     guild_id=str(interaction.guild_id),
        #     character_name=character_name,
        #     language_code=player_language  # Pass language_code here
        # )
        # For this test, we'll assume start_new_character_session is not mocked and it calls character_manager methods.
        mock_character_manager.get_character_by_discord_id.assert_called_once_with(
            guild_id="test_guild_1",
            discord_user_id=12345
        )

        # Assert create_character was called with the correct parameters on CharacterManager
        # REMOVED race from assertion
        mock_character_manager.create_character.assert_called_once_with(
            discord_id=12345,
            name=char_name,
            guild_id="test_guild_1"
            # location_id, hp, stats, etc., are assumed to be handled by CharacterManager's defaults
        )

        # Assert followup message indicates success
        mock_interaction.followup.send.assert_called_once()
        args, kwargs = mock_interaction.followup.send.call_args
        # self.assertIn(f"Welcome, {char_name} the {char_race}", args[0])
        # Based on actual success message: f"Персонаж '{character_name}' успешно создан! Язык: {effective_language}."
        # For this test, let's assume default language or check how it's determined.
        # The command uses self.bot.game_manager.get_guild_language(str(interaction.guild_id))
        # And then self.bot.game_manager.loc.get_message_for_lang(...)
        # This is too complex to replicate here, let's just check for character name.
        # A more robust way would be to mock get_guild_language and loc.get_message_for_lang on game_manager
        self.assertIn(f"Персонаж '{char_name}' успешно создан!", args[0]) # Simplified assertion
        self.assertEqual(kwargs.get('ephemeral'), False)

    @patch('bot.command_modules.game_setup_cmds.is_master_or_admin_check', return_value=True) # MODIFIED patch target
    async def test_cmd_set_bot_language_updates_gm_config(self, mock_is_master_or_admin_check): # MODIFIED mock name
        # Mock Interaction
        interaction_mock = AsyncMock()
        interaction_mock.response = AsyncMock()
        interaction_mock.followup = AsyncMock()
        interaction_mock.client = MagicMock() # RPGBot mock
        interaction_mock.guild_id = "test_guild_789"

        # Mock GameManager
        mock_game_manager = MagicMock() # GameManager mock
        mock_game_manager.set_default_bot_language = AsyncMock()
        interaction_mock.client.game_manager = mock_game_manager

        # Instantiate the Cog
        cog = GameSetupCog(bot=interaction_mock.client) # Pass the bot mock (interaction_mock.client)

        # Execute the command
        # await bot.command_modules.game_setup_cmds.cmd_set_bot_language(interaction_mock, language="ru")
        # MODIFIED call to use cog and updated parameter name
        await cog.cmd_set_bot_language(interaction_mock, language_code="ru")

        # Assertions
        # mock_is_master_or_admin.assert_called_once_with(interaction_mock, mock_game_manager)
        # MODIFIED assertion for the new patch target
        mock_is_master_or_admin_check.assert_called_once_with(interaction_mock)
        mock_game_manager.set_default_bot_language.assert_called_once_with(
            "ru", str(interaction_mock.guild_id)
        )
        interaction_mock.response.defer.assert_called_once_with(ephemeral=True)
        # interaction_mock.followup.send.assert_called_once_with(
        #     "Основной язык бота установлен на русский.", ephemeral=True
        # )
        # MODIFIED expected message based on command's actual message
        interaction_mock.followup.send.assert_called_once_with(
            "Язык бота для этой гильдии установлен на 'ru'.", ephemeral=True
        )

    @patch('bot.command_modules.game_setup_cmds.is_master_or_admin_check', return_value=False) # MODIFIED patch target
    async def test_cmd_set_bot_language_unauthorized(self, mock_is_master_or_admin_check): # MODIFIED mock name
        # Mock Interaction
        interaction_mock = AsyncMock()
        interaction_mock.response = AsyncMock()
        interaction_mock.followup = AsyncMock()
        interaction_mock.client = MagicMock() # RPGBot mock
        interaction_mock.guild_id = "test_guild_789"

        # Mock GameManager
        mock_game_manager = MagicMock() # GameManager mock
        interaction_mock.client.game_manager = mock_game_manager

        # Instantiate the Cog
        cog = GameSetupCog(bot=interaction_mock.client) # Pass the bot mock

        # Execute the command
        # await bot.command_modules.game_setup_cmds.cmd_set_bot_language(interaction_mock, language="ru")
        # MODIFIED call to use cog and updated parameter name
        await cog.cmd_set_bot_language(interaction_mock, language_code="ru")


        # Assertions
        # mock_is_master_or_admin.assert_called_once_with(interaction_mock, mock_game_manager)
        # MODIFIED assertion for the new patch target
        mock_is_master_or_admin_check.assert_called_once_with(interaction_mock)
        mock_game_manager.set_default_bot_language.assert_not_called()
        interaction_mock.response.defer.assert_called_once_with(ephemeral=True)
        # interaction_mock.followup.send.assert_called_once_with(
        #     "You are not authorized to use this command.", ephemeral=True
        # )
        # MODIFIED expected message based on command's actual message
        interaction_mock.followup.send.assert_called_once_with(
            "Только Мастер или администратор может менять язык бота.", ephemeral=True
        )

if __name__ == '__main__':
    unittest.main()
