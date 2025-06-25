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
        self.mock_interaction.client = self.mock_bot_instance

        # Mock LocationManager on GameManager for starting location
        self.mock_location_manager = AsyncMock(spec=LocationManager)
        self.mock_game_manager.location_manager = self.mock_location_manager


        self.cog = GameSetupCog(self.mock_bot_instance)

    async def test_cmd_start_new_character_success_new_player_and_new_char(self):
        char_name = "TestHero"
        starting_loc_id = "start_loc_123"
        self.mock_session.execute.return_value = self.mock_sql_execute_result_no_player

        # Mock game_manager.get_rule to return the starting_location_id
        async def get_rule_side_effect(guild_id, rule_key, default):
            if rule_key == 'starting_location_id':
                return starting_loc_id
            return default
        self.mock_game_manager.get_rule.side_effect = get_rule_side_effect

        async def mock_create_player(session, model_cls, data, **kwargs):
            # Simplified mock for create_entity focusing on Player creation
            if model_cls == Player:
                player_id = data.get("id", str(uuid.uuid4()))
                # Ensure guild_id is correctly passed from kwargs if not in data
                # In the actual command, guild_id is passed as a kwarg to create_entity
                # and create_entity adds it to data if not present.
                # Here, we assume data will have guild_id from the command's logic.
                return Player(id=player_id, **data)
            return None

        with patch('bot.command_modules.game_setup_cmds.create_entity', new=AsyncMock(side_effect=mock_create_player)) as mock_create_entity_call:
            expected_char_pydantic_obj = Character( # Pydantic model
                id="char_id_1", discord_user_id=self.mock_interaction.user.id,
                name_i18n={"en": char_name}, guild_id=self.mock_interaction.guild_id,
                selected_language="en", location_id=starting_loc_id # Expect starting location
            )
            self.mock_character_manager.create_new_character = AsyncMock(return_value=expected_char_pydantic_obj)

            await self.cog.cmd_start_new_character.callback(self.cog, self.mock_interaction, character_name=char_name, player_language=None)

        # Player creation checks
        mock_create_entity_call.assert_called_once()
        created_player_data = mock_create_entity_call.call_args[0][2] # data dict passed to create_entity
        self.assertEqual(created_player_data["guild_id"], self.mock_interaction.guild_id)
        self.assertEqual(created_player_data["discord_id"], str(self.mock_interaction.user.id))

        # Character creation checks
        self.mock_character_manager.create_new_character.assert_awaited_once()
        cm_call_kwargs = self.mock_character_manager.create_new_character.call_args.kwargs
        self.assertEqual(cm_call_kwargs['guild_id'], self.mock_interaction.guild_id)
        self.assertEqual(cm_call_kwargs['user_id'], self.mock_interaction.user.id)
        self.assertEqual(cm_call_kwargs['character_name'], char_name)
        self.assertEqual(cm_call_kwargs['language'], "en")
        # We expect create_new_character in CharacterManager to use the starting_location_id rule.
        # So, the Character object it returns should have this location_id.
        # The actual setting of location_id happens inside CharacterManager.create_new_character.

        self.mock_interaction.followup.send.assert_called_once()
        args, kwargs = self.mock_interaction.followup.send.call_args
        self.assertIn(f"Персонаж '{char_name}' успешно создан!", args[0])

    async def test_cmd_start_new_character_existing_player_new_char(self):
        char_name = "AnotherHero"
        starting_loc_id = "start_loc_xyz"
        self.mock_session.execute.return_value = self.mock_sql_execute_result_existing_player
        self.mock_existing_player_obj.active_character_id = None

        expected_char_obj = Character(
            id="char_id_2", discord_user_id=self.mock_interaction.user.id,
            name_i18n={"en": char_name}, guild_id=self.mock_interaction.guild_id,
            selected_language="ru"
        )
        self.mock_character_manager.create_new_character = AsyncMock(return_value=expected_char_obj)

        await self.cog.cmd_start_new_character.callback(self.cog, self.mock_interaction, character_name=char_name, player_language="ru")

        self.mock_session.execute.assert_called_once()
        self.mock_session.commit.assert_not_called()

        self.mock_character_manager.create_new_character.assert_awaited_once_with(
            guild_id=self.mock_interaction.guild_id,
            user_id=self.mock_interaction.user.id,
            character_name=char_name,
            language="ru"
        )
        self.mock_interaction.followup.send.assert_called_once()
        args, kwargs = self.mock_interaction.followup.send.call_args
        self.assertIn(f"Персонаж '{char_name}' успешно создан!", args[0])
        self.assertIn("Язык для сообщений: ru", args[0])


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
