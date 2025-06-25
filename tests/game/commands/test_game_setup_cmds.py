import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import uuid # Required for Player ID generation if not mocked away

from bot.command_modules.game_setup_cmds import GameSetupCog
from bot.services.db_service import DBService
from bot.game.models.character import Character
from bot.database.models.character_related import Player # Corrected Import Player for spec
from bot.game.managers.character_manager import CharacterManager, CharacterAlreadyExistsError
from bot.game.managers.game_manager import GameManager
from bot.bot_core import RPGBot
from sqlalchemy.ext.asyncio import AsyncSession # For spec

class TestGameSetupCmds(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_interaction = AsyncMock()
        self.mock_interaction.user.id = 12345
        self.mock_interaction.user.display_name = "TestUser"
        self.mock_interaction.guild_id = "test_guild_1"
        self.mock_interaction.guild = MagicMock()
        self.mock_interaction.guild.id = "test_guild_1"


        self.mock_db_service = AsyncMock(spec=DBService)
        
        # Mock for session.execute().scalars().first() to find no existing player
        self.mock_sql_execute_result_no_player = MagicMock(name="sql_execute_result_no_player")
        self.mock_scalars_result_no_player = MagicMock(name="scalars_result_no_player")
        self.mock_scalars_result_no_player.first.return_value = None
        self.mock_sql_execute_result_no_player.scalars.return_value = self.mock_scalars_result_no_player

        # Mock for session.execute().scalars().first() to find an existing player
        self.mock_existing_player_obj = Player(id=str(uuid.uuid4()), discord_id=str(self.mock_interaction.user.id), guild_id=self.mock_interaction.guild_id, name_i18n={"en":"Existing Player"})
        self.mock_sql_execute_result_existing_player = MagicMock(name="sql_execute_result_existing_player")
        self.mock_scalars_result_existing_player = MagicMock(name="scalars_result_existing_player")
        self.mock_scalars_result_existing_player.first.return_value = self.mock_existing_player_obj
        self.mock_sql_execute_result_existing_player.scalars.return_value = self.mock_scalars_result_existing_player


        self.mock_session = AsyncMock(spec=AsyncSession)
        self.mock_session.commit = AsyncMock()
        self.mock_session.rollback = AsyncMock()
        
        self.mock_session.execute = AsyncMock(return_value=self.mock_sql_execute_result_no_player) # Default: no player

        self.mock_db_service.get_session.return_value.__aenter__.return_value = self.mock_session

        self.mock_character_manager = AsyncMock(spec=CharacterManager)

        self.mock_game_manager = AsyncMock(spec=GameManager)
        self.mock_game_manager.character_manager = self.mock_character_manager
        self.mock_game_manager.db_service = self.mock_db_service
        self.mock_game_manager.get_rule = AsyncMock(side_effect=lambda guild_id, rule_key, default: default)

        self.mock_bot_instance = MagicMock(spec=RPGBot)
        self.mock_bot_instance.game_manager = self.mock_game_manager
        # Ensure get_db_session is on the bot instance if cog uses self.bot.get_db_session
        # self.mock_bot_instance.get_db_session = self.mock_db_service.get_session
        self.mock_interaction.client = self.mock_bot_instance


        self.cog = GameSetupCog(self.mock_bot_instance)

    async def test_cmd_start_new_character_success_new_player_and_new_char(self):
        char_name = "TestHero"
        player_lang = "en" # Explicitly set for clarity in test
        self.mock_session.execute.return_value = self.mock_sql_execute_result_no_player # No existing Player

        # Mock the Player object that will be "created" by create_entity
        created_player_id = str(uuid.uuid4())
        mock_created_player_obj = Player(
            id=created_player_id,
            discord_id=str(self.mock_interaction.user.id),
            guild_id=self.mock_interaction.guild_id,
            name_i18n={"en": self.mock_interaction.user.display_name}, # Name from display_name
            selected_language=player_lang, # Language from command or default
            is_active=True
        )

        # Mock CharacterManager response - this is a Pydantic model
        # Ensure it has all fields required by ТЗ 1.2 for /start
        expected_pydantic_char = Character(
            id="char_id_1",
            discord_user_id=self.mock_interaction.user.id,
            name_i18n={"en": char_name, player_lang: char_name}, # Ensure selected lang name
            guild_id=self.mock_interaction.guild_id,
            selected_language=player_lang,
            location_id="default_starting_location_id", # Expected starting location
            level=1,
            experience=0,
            unspent_xp=0,
            gold=0,
            current_game_status="exploring", # As per ТЗ
            collected_actions_json="[]", # As per ТЗ (empty list as JSON)
            # other fields like stats, hp, etc., would be set by CharacterManager
            stats={"strength": 10}, # Example minimal stats
            hp=100.0,
            max_health=100.0
        )
        self.mock_character_manager.create_new_character = AsyncMock(return_value=expected_pydantic_char)

        # Mock game_manager.get_rule for default language if player_language is None
        # This cog's logic: if player_language is None, it uses game_manager.get_default_bot_language()
        # which in turn might use get_rule. For this test, we pass player_lang explicitly.
        # If testing player_language=None, then mock get_default_bot_language.
        self.mock_game_manager.get_default_bot_language = AsyncMock(return_value="en")


        with patch('bot.command_modules.game_setup_cmds.create_entity', new=AsyncMock(return_value=mock_created_player_obj)) as mock_create_entity_call:
            await self.cog.cmd_start_new_character.callback(self.cog, self.mock_interaction, character_name=char_name, player_language=player_lang)

        self.mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
        self.mock_session.execute.assert_called_once() # To check if player exists

        # Assert that create_entity was called to create a Player
        mock_create_entity_call.assert_called_once()
        call_args_create_player = mock_create_entity_call.call_args[0]
        self.assertEqual(call_args_create_player[1], Player) # model_class
        self.assertEqual(call_args_create_player[2]['discord_id'], str(self.mock_interaction.user.id))
        self.assertEqual(call_args_create_player[2]['guild_id'], self.mock_interaction.guild_id)
        self.assertEqual(call_args_create_player[2]['selected_language'], player_lang)

        self.mock_session.commit.assert_called_once() # Commit for new Player

        # Assert that CharacterManager.create_new_character was called correctly
        self.mock_character_manager.create_new_character.assert_awaited_once_with(
            guild_id=self.mock_interaction.guild_id,
            user_id=self.mock_interaction.user.id, # user_id is int
            character_name=char_name,
            language=player_lang, # Language passed to manager
            session=self.mock_session # Ensure session is passed
        )

        self.mock_interaction.followup.send.assert_called_once()
        args, kwargs = self.mock_interaction.followup.send.call_args
        self.assertIn(f"Персонаж '{char_name}' успешно создан!", args[0])
        self.assertEqual(kwargs.get('ephemeral'), True)
        # TODO: Add assertions for other Player fields if they are set by this command or create_entity
        # e.g. Player.xp, Player.level - these are on Character model, so check expected_pydantic_char

    async def test_cmd_start_new_character_existing_player_new_char(self):
        char_name = "AnotherHero"
        player_lang = "ru"
        self.mock_session.execute.return_value = self.mock_sql_execute_result_existing_player # Player exists
        self.mock_existing_player_obj.active_character_id = None # But no active character

        expected_pydantic_char = Character(
            id="char_id_2", discord_user_id=self.mock_interaction.user.id,
            name_i18n={"en": char_name, player_lang: char_name}, guild_id=self.mock_interaction.guild_id,
            selected_language=player_lang,
            location_id="default_starting_location_id_2", level=1, experience=0, unspent_xp=0, gold=0,
            current_game_status="exploring", collected_actions_json="[]",
            stats={}, hp=100.0, max_health=100.0
        )
        self.mock_character_manager.create_new_character = AsyncMock(return_value=expected_pydantic_char)
        self.mock_game_manager.get_default_bot_language = AsyncMock(return_value="en") # Fallback if lang not provided

        await self.cog.cmd_start_new_character.callback(self.cog, self.mock_interaction, character_name=char_name, player_language=player_lang)

        self.mock_session.execute.assert_called_once() # Check for existing player
        # create_entity for Player should NOT be called
        # session.commit for Player update (e.g. language) might be called by cog.
        # The cog current logic updates player language if provided.
        self.mock_session.add.assert_called_once_with(self.mock_existing_player_obj) # For language update
        self.mock_session.commit.assert_called_once() # Commit for Player language update

        self.mock_character_manager.create_new_character.assert_awaited_once_with(
            guild_id=self.mock_interaction.guild_id,
            user_id=self.mock_interaction.user.id,
            character_name=char_name,
            language=player_lang,
            session=self.mock_session
        )
        self.mock_interaction.followup.send.assert_called_once()
        args, kwargs = self.mock_interaction.followup.send.call_args
        self.assertIn(f"Персонаж '{char_name}' успешно создан!", args[0])
        self.assertIn(f"Язык для сообщений: {player_lang}", args[0]) # Check if lang update message is there
        self.assertEqual(self.mock_existing_player_obj.selected_language, player_lang)


    async def test_cmd_start_new_character_already_exists_error(self):
        char_name = "DuplicateHero"
        self.mock_session.execute.return_value = self.mock_sql_execute_result_existing_player
        # Important: Simulate that the existing player *already has an active character*
        self.mock_existing_player_obj.active_character_id = "some_active_char_id"

        # If create_new_character is called, it should raise CharacterAlreadyExistsError
        self.mock_character_manager.create_new_character = AsyncMock(side_effect=CharacterAlreadyExistsError("Test char already exists"))

        await self.cog.cmd_start_new_character.callback(self.cog, self.mock_interaction, character_name=char_name, player_language=None)

        # In this specific path (player exists, active character ID exists on player),
        # CharacterManager.create_new_character should be called and raise the error.
        self.mock_character_manager.create_new_character.assert_awaited_once()
        self.mock_interaction.followup.send.assert_called_once_with(
            "У вас уже есть персонаж в этой игре. Вы не можете создать еще одного.",
            ephemeral=True
        )

    async def test_cmd_start_new_character_player_creation_fails_gracefully(self):
        char_name = "UnluckyHero"
        self.mock_session.execute.return_value = self.mock_sql_execute_result_no_player

        with patch('bot.command_modules.game_setup_cmds.create_entity', new=AsyncMock(return_value=None)) as mock_create_entity_fail:
            await self.cog.cmd_start_new_character.callback(self.cog, self.mock_interaction, character_name=char_name, player_language=None)

            mock_create_entity_fail.assert_called_once()
            self.mock_interaction.followup.send.assert_called_once_with(
                "There was an issue creating your player profile. Please try again.", ephemeral=True
            )
            self.mock_character_manager.create_new_character.assert_not_called()


if __name__ == '__main__':
    unittest.main()
