import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Assuming paths for imports - adjust if necessary based on project structure
from bot.command_modules.game_setup_cmds import cmd_start_new_character
from bot.services.db_service import DBService # Needed for type hinting if not patching directly
from bot.game.models.character import Character # For constructing expected return

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
        mock_db_service = AsyncMock(spec=DBService)
        mock_game_manager = MagicMock()
        mock_game_manager.db_service = mock_db_service
        
        mock_interaction.client = MagicMock()
        mock_interaction.client.game_manager = mock_game_manager

        # Mock get_player_by_discord_id to simulate no existing character
        mock_db_service.get_player_by_discord_id.return_value = None

        # Define the character data that create_player is expected to return
        # This should match what cmd_start_new_character expects after creation
        created_player_data = {
            "id": "test_player_id_1",
            "discord_user_id": 12345,
            "name": "TestChar",
            "race": "Human",
            "guild_id": "test_guild_1",
            "location_id": "town_square", # Default starting location in cmd
            "hp": 100,
            "mp": 50,
            "stats": {"strength": 10, "dexterity": 10, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10},
            "level": 1,
            "experience": 0,
            "unspent_xp": 0,
            # other fields as necessary based on DBService.create_player's return and cmd_start_new_character's usage
        }
        mock_db_service.create_player.return_value = created_player_data
        
        # Mock get_location for the success message part
        mock_db_service.get_location.return_value = {"name": "Town Square", "id": "town_square"}

        char_name = "TestChar"
        char_race = "Human"

        # Call the command
        await cmd_start_new_character(mock_interaction, name=char_name, race=char_race)

        # Assert that defer was called
        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

        # Assert get_player_by_discord_id was called correctly
        mock_db_service.get_player_by_discord_id.assert_called_once_with(
            discord_user_id=12345,
            guild_id="test_guild_1"
        )

        # Assert create_player was called with the correct parameters, including level, experience, unspent_xp
        mock_db_service.create_player.assert_called_once_with(
            discord_user_id=12345,
            name=char_name,
            race=char_race,
            guild_id="test_guild_1",
            location_id="town_square", # Default starting location
            hp=100, # Default HP
            mp=50,  # Default MP
            attack=10, # Default attack (goes into stats or dedicated field)
            defense=5, # Default defense (goes into stats or dedicated field)
            stats={"strength": 10, "dexterity": 10, "constitution": 10, "intelligence": 10, "wisdom": 10, "charisma": 10}, # Default stats
            level=1,      # Expected default level
            experience=0, # Expected default experience
            unspent_xp=0  # Expected default unspent_xp
        )

        # Assert followup message indicates success
        # We can check if followup.send was called, and optionally parts of its content.
        mock_interaction.followup.send.assert_called_once()
        args, kwargs = mock_interaction.followup.send.call_args
        self.assertIn(f"Welcome, {char_name} the {char_race}", args[0])
        self.assertEqual(kwargs.get('ephemeral'), False)

    @patch('bot.command_modules.game_setup_cmds.is_master_or_admin', return_value=True)
    async def test_cmd_set_bot_language_updates_gm_config(self, mock_is_master_or_admin):
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

        # Execute the command
        await bot.command_modules.game_setup_cmds.cmd_set_bot_language(interaction_mock, language="ru")

        # Assertions
        mock_is_master_or_admin.assert_called_once_with(interaction_mock, mock_game_manager)
        mock_game_manager.set_default_bot_language.assert_called_once_with(
            "ru", str(interaction_mock.guild_id)
        )
        interaction_mock.response.defer.assert_called_once_with(ephemeral=True)
        interaction_mock.followup.send.assert_called_once_with(
            "Основной язык бота установлен на русский.", ephemeral=True
        )

    @patch('bot.command_modules.game_setup_cmds.is_master_or_admin', return_value=False)
    async def test_cmd_set_bot_language_unauthorized(self, mock_is_master_or_admin):
        # Mock Interaction
        interaction_mock = AsyncMock()
        interaction_mock.response = AsyncMock()
        interaction_mock.followup = AsyncMock()
        interaction_mock.client = MagicMock() # RPGBot mock
        interaction_mock.guild_id = "test_guild_789"

        # Mock GameManager
        mock_game_manager = MagicMock() # GameManager mock
        interaction_mock.client.game_manager = mock_game_manager

        # Execute the command
        await bot.command_modules.game_setup_cmds.cmd_set_bot_language(interaction_mock, language="ru")

        # Assertions
        mock_is_master_or_admin.assert_called_once_with(interaction_mock, mock_game_manager)
        mock_game_manager.set_default_bot_language.assert_not_called()
        interaction_mock.response.defer.assert_called_once_with(ephemeral=True)
        interaction_mock.followup.send.assert_called_once_with(
            "You are not authorized to use this command.", ephemeral=True
        )

if __name__ == '__main__':
    unittest.main()
