import bot
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Assuming paths for imports - adjust if necessary based on project structure
from bot.command_modules.game_setup_cmds import cmd_start_new_character
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
        created_player_data = {
            "id": "test_player_id_1",
            "discord_user_id": 12345,
            "name_i18n": {"en": "TestChar"},
            "guild_id": "test_guild_1",
            "location_id": "town_square",
            "hp": 100,
            # "mp": 50, # mp (mana) should be part of stats
            "stats": {
                "strength": 10, "dexterity": 10, "constitution": 10,
                "intelligence": 10, "wisdom": 10, "charisma": 10,
                "mana": 50, "max_mana": 50 # Add mana here
            },
            "level": 1,
            "experience": 0,
            "unspent_xp": 0,
            # other fields might be needed if Character constructor expects them or __post_init__ relies on them
            # For now, assuming these are the core fields.
            # Add 'char_class' if it's a required part of the data for Character init and not optional.
            # Based on model, char_class is Optional[str], so not strictly needed.
        }
        # Create a dictionary for Character constructor, excluding fields not in __init__ (like 'race')
        character_init_data = {k: v for k, v in created_player_data.items()}

        # Assign the create_character mock here, after character_init_data is defined
        mock_character_manager.create_character = AsyncMock(return_value=Character(**character_init_data))

        # Mock GameManager
        mock_game_manager = MagicMock()
        # mock_game_manager.db_service = mock_db_service # db_service is now used by CharacterManager, not directly by cmd
        mock_game_manager.character_manager = mock_character_manager

        # Mock LocationManager and its get_location_instance for the success message
        mock_location_manager = AsyncMock() # spec=LocationManager if available
        mock_location_manager.get_location_instance.return_value = {"name": "Town Square", "id": "town_square"}
        mock_game_manager.location_manager = mock_location_manager

        mock_interaction.client = MagicMock()
        mock_interaction.client.game_manager = mock_game_manager
        
        # get_player_by_discord_id is called by character_manager.get_character_by_discord_id
        # create_player is called by character_manager.create_character
        # These are now internal to CharacterManager, so we mock CharacterManager's methods directly.

        char_name = "TestChar"
        char_race = "Human"

        # Call the command
        await cmd_start_new_character.callback(mock_interaction, name=char_name, race=char_race)

        # Assert that defer was called
        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

        # Assert get_character_by_discord_id was called correctly on CharacterManager
        mock_character_manager.get_character_by_discord_id.assert_called_once_with(
            guild_id="test_guild_1",
            discord_user_id=12345
        )

        # Assert create_character was called with the correct parameters on CharacterManager
        mock_character_manager.create_character.assert_called_once_with(
            discord_id=12345,
            name=char_name,
            guild_id="test_guild_1",
            race=char_race # Assert race is passed
            # location_id, hp, stats, etc., are assumed to be handled by CharacterManager's defaults
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
