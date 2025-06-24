import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json

# Placeholder for future imports
# from bot.bot_core import RPGBot 
# from bot.game.managers.game_manager import GameManager
# from bot.game.models.character import Character
# import discord # May need to mock discord.Message etc.

# Actual imports
from bot.bot_core import RPGBot
# from bot.game.managers.game_manager import GameManager # Mocked
# from bot.game.models.character import Character # Mocked
import discord # For discord.Message

class TestBotCoreOnMessage(unittest.IsolatedAsyncioTestCase):

    @patch('bot.bot_core.parse_player_action')
    @patch('bot.bot_core.OpenAIService')
    @patch('bot.bot_core.GameManager')
    async def test_on_message_action_accumulation(self, MockGameManager, MockOpenAIService, mock_parse_player_action):
        # --- Setup Mocks ---
        mock_gm_instance = MockGameManager.return_value
        mock_nlu_data_service = AsyncMock()
        mock_db_service = AsyncMock() # For update_player_field
        mock_gm_instance.nlu_data_service = mock_nlu_data_service
        mock_gm_instance.db_service = mock_db_service
        mock_gm_instance.settings = {'discord_command_prefix': '!'} # Add settings to gm_instance

        # Mock Player object
        mock_player_obj = MockPlayer(
            player_id="player1_db_id",
            discord_id_str="discord_user1",
            guild_id_str="guild1",
            current_game_status="исследование",
            selected_language="ru",
            collected_actions_json=None
        )
        mock_gm_instance.get_player_by_discord_id = AsyncMock(return_value=mock_player_obj)
        mock_gm_instance.db_service.update_player_field = AsyncMock(return_value=True)


        mock_message = AsyncMock(spec=discord.Message)
        mock_message.author = AsyncMock(spec=discord.User, bot=False, id="discord_user1") # String ID
        mock_message.guild = AsyncMock(spec=discord.Guild, id="guild1") # String ID
        mock_message.content = "первое действие"
        mock_message.channel = AsyncMock(spec=discord.TextChannel)
        mock_message.add_reaction = AsyncMock()
        
        intents = discord.Intents.default()
        intents.message_content = True
        
        bot = RPGBot(
            game_manager=mock_gm_instance, 
            openai_service=MockOpenAIService(), 
            command_prefix="!", # Matches settings
            intents=intents
        )
        bot.game_manager = mock_gm_instance # Ensure it's set

        # --- First message: Accumulate one action ---
        mock_parse_player_action.return_value = {"intent_type": "intent_1", "entities": {"entity_1": "value_1"}, "original_text": "первое действие"}
        
        await bot.on_message(mock_message)

        # Assertions for first action
        mock_gm_instance.get_player_by_discord_id.assert_called_with("discord_user1", "guild1")
        mock_parse_player_action.assert_called_with(text="первое действие", language="ru", guild_id="guild1", nlu_data_service=mock_nlu_data_service)
        
        expected_actions_after_first = [{"intent_type": "intent_1", "entities": {"entity_1": "value_1"}, "original_text": "первое действие"}]
        self.assertIsNotNone(mock_player_obj.collected_actions_json)
        self.assertEqual(json.loads(mock_player_obj.collected_actions_json), expected_actions_after_first)
        mock_gm_instance.db_service.update_player_field.assert_called_with(
            player_id="player1_db_id", field_name='collected_actions_json',
            value=mock_player_obj.collected_actions_json, guild_id="guild1"
        )
        mock_message.add_reaction.assert_called_with("👍")
        
        # --- Second message: Accumulate another action ---
        mock_message.content = "второе действие"
        mock_parse_player_action.return_value = {"intent_type": "intent_2", "entities": {"entity_2": "value_2"}, "original_text": "второе действие"}

        await bot.on_message(mock_message)

        expected_actions_after_second = [
            {"intent_type": "intent_1", "entities": {"entity_1": "value_1"}, "original_text": "первое действие"},
            {"intent_type": "intent_2", "entities": {"entity_2": "value_2"}, "original_text": "второе действие"}
        ]
        self.assertIsNotNone(mock_player_obj.collected_actions_json)
        self.assertEqual(json.loads(mock_player_obj.collected_actions_json), expected_actions_after_second)
        # update_player_field would be called again
        self.assertEqual(mock_gm_instance.db_service.update_player_field.call_count, 2)
        mock_message.add_reaction.assert_called_with("👍") # Called again

    @patch('bot.bot_core.parse_player_action') 
    @patch('bot.bot_core.OpenAIService') 
    @patch('bot.bot_core.GameManager')
    async def test_on_message_input_routing_dialogue(self, MockGameManager, MockOpenAIService, mock_parse_player_action):
        # --- Setup Mocks ---
        mock_gm_instance = MockGameManager.return_value
        mock_dialogue_manager = AsyncMock()
        mock_character_manager = AsyncMock() # For get_character_by_player_id
        mock_gm_instance.dialogue_manager = mock_dialogue_manager
        mock_gm_instance.character_manager = mock_character_manager # Add to GM
        mock_gm_instance.nlu_data_service = AsyncMock()
        mock_gm_instance.settings = {'discord_command_prefix': '!'}


        mock_player_obj = MockPlayer(
            player_id="player_talker_db_id",
            discord_id_str="discord_user_talker",
            guild_id_str="guild_dialogue",
            current_game_status="диалог", # Busy state: dialogue
            selected_language="ru"
        )
        mock_gm_instance.get_player_by_discord_id = AsyncMock(return_value=mock_player_obj)

        mock_character_obj = MockCharacter(char_id="char_dialogue_active") # The actual character model
        mock_gm_instance.character_manager.get_character_by_player_id = AsyncMock(return_value=mock_character_obj)


        mock_message = AsyncMock(spec=discord.Message)
        mock_message.author = AsyncMock(spec=discord.User, bot=False, id="discord_user_talker") # String ID
        mock_message.guild = AsyncMock(spec=discord.Guild, id="guild_dialogue")
        mock_message.content = "это мое сообщение в диалоге" # Non-command message
        mock_message.channel = AsyncMock(spec=discord.TextChannel, id="channel_dialogue")
        
        intents = discord.Intents.default()
        intents.message_content = True
        bot = RPGBot(game_manager=mock_gm_instance, openai_service=MockOpenAIService(), command_prefix="!", intents=intents)
        bot.game_manager = mock_gm_instance # Ensure it's set

        # --- Call on_message ---
        await bot.on_message(mock_message)

        # --- Assertions ---
        # NLU should NOT be called
        mock_parse_player_action.assert_not_called()
        
        # DialogueManager's method SHOULD be called
        mock_gm_instance.dialogue_manager.process_player_dialogue_message.assert_called_once_with(
            character=mock_character_obj, # Expecting the Character model
            message_text="это мое сообщение в диалоге",
            channel_id="channel_dialogue", # Ensure this is string if handler expects str
            guild_id="guild_dialogue"
        )
        # db_service.update_player_field for collected_actions_json should not be called by NLU block
        mock_gm_instance.db_service.update_player_field.assert_not_called()

    @patch('bot.bot_core.parse_player_action')
    @patch('bot.bot_core.OpenAIService')
    @patch('bot.bot_core.GameManager')
    async def test_on_message_input_routing_combat_logs_no_dialogue_call(self, MockGameManager, MockOpenAIService, mock_parse_player_action):
        # --- Setup Mocks ---
        mock_gm_instance = MockGameManager.return_value
        mock_dialogue_manager = AsyncMock() 
        mock_gm_instance.dialogue_manager = mock_dialogue_manager
        mock_gm_instance.nlu_data_service = AsyncMock()
        mock_gm_instance.settings = {'discord_command_prefix': '!'}


        mock_player_obj = MockPlayer(
            player_id="player_fighter_db_id",
            discord_id_str="discord_user_fighter",
            guild_id_str="guild_combat",
            name="Fighter", # Name is on Player model for the log message
            current_game_status="бой",
            selected_language="ru"
        )
        mock_gm_instance.get_player_by_discord_id = AsyncMock(return_value=mock_player_obj)

        mock_message = AsyncMock(spec=discord.Message)
        mock_message.author = AsyncMock(spec=discord.User, bot=False, id="discord_user_fighter") # String ID
        mock_message.guild = AsyncMock(spec=discord.Guild, id="guild_combat")
        mock_message.content = "some raw text during combat" # Non-command
        mock_message.channel = AsyncMock(spec=discord.TextChannel)

        intents = discord.Intents.default()
        intents.message_content = True
        bot = RPGBot(game_manager=mock_gm_instance, openai_service=MockOpenAIService(), command_prefix="!", intents=intents)
        bot.game_manager = mock_gm_instance
        
        # --- Call on_message ---
        # To check logs, we might need to patch logging.info or logging.debug
        with patch('logging.info') as mock_logging_info: # Or logging.debug if that's where the message is
            await bot.on_message(mock_message)

            # --- Assertions ---
            mock_parse_player_action.assert_not_called() # NLU skipped
            mock_dialogue_manager.process_player_dialogue_message.assert_not_called() # Dialogue Manager skipped

            # Check if the specific log message for 'бой' state was called
            # This is a bit brittle as it depends on exact log message.
            # Example: logging.info(f"Input: Message from {char_model.name} received while in 'бой' state...")
            found_log = False
            for call in mock_logging_info.call_args_list:
                args, _ = call
                if args and "received while in 'бой' state" in args[0]:
                    found_log = True
                    break
            self.assertTrue(found_log, "Expected log message for 'бой' state not found.")

    @patch('bot.bot_core.parse_player_action')
    @patch('bot.bot_core.OpenAIService')
    @patch('bot.bot_core.GameManager')
    async def test_on_message_nlu_language_fallback(self, MockGameManager, MockOpenAIService, mock_parse_player_action):
        # --- Setup Mocks ---
        mock_gm_instance = MockGameManager.return_value
        mock_nlu_data_service = AsyncMock()
        mock_db_service = AsyncMock()
        mock_gm_instance.nlu_data_service = mock_nlu_data_service
        mock_gm_instance.db_service = mock_db_service # For update_player_field
        mock_gm_instance.settings = {'discord_command_prefix': '!'}


        # Mock GameManager's get_default_bot_language
        mock_gm_instance.get_default_bot_language = AsyncMock(return_value="ru") # GM default is 'ru'

        mock_player_obj = MockPlayer(
            player_id="player_lang_fallback_db_id",
            discord_id_str="discord_user_lang_fallback",
            guild_id_str="guild_lang_fallback",
            name="LangFallbacker",
            current_game_status="исследование",
            selected_language=None, # Player has NOT set a language
            collected_actions_json=None
        )
        mock_gm_instance.get_player_by_discord_id = AsyncMock(return_value=mock_player_obj)
        mock_gm_instance.db_service.update_player_field = AsyncMock(return_value=True)


        mock_message = AsyncMock(spec=discord.Message)
        mock_message.author = AsyncMock(spec=discord.User, bot=False, id="discord_user_lang_fallback") # String ID
        mock_message.guild = AsyncMock(spec=discord.Guild, id="guild_lang_fallback")
        mock_message.content = "какое-то действие"
        mock_message.channel = AsyncMock(spec=discord.TextChannel)

        intents = discord.Intents.default()
        intents.message_content = True

        bot = RPGBot(
            game_manager=mock_gm_instance,
            openai_service=MockOpenAIService(),
            command_prefix="!",
            intents=intents
        )
        bot.game_manager = mock_gm_instance

        # --- Call on_message ---
        mock_parse_player_action.return_value = ("intent_fallback", {"entity_fallback": "value_fallback"})
        await bot.on_message(mock_message)

        # --- Assertions ---
        # Verify player was fetched
        mock_gm_instance.get_player_by_discord_id.assert_called_with("discord_user_lang_fallback", "guild_lang_fallback")

        # Verify get_default_bot_language was called on GameManager
        mock_gm_instance.get_default_bot_language.assert_called_once_with("guild_lang_fallback")

        # Verify parse_player_action was called with the GM's default language ("ru")
        mock_parse_player_action.assert_called_once_with(
            text="какое-то действие",
            language="ru", # Expected fallback language
            guild_id="guild_lang_fallback",
            nlu_data_service=mock_nlu_data_service # Corrected kwarg name
        )

        # Verify player data update was attempted
        expected_actions = [{"intent_type": "intent_fallback", "entities": {"entity_fallback": "value_fallback"}, "original_text": "какое-то действие"}]
        self.assertIsNotNone(mock_player_obj.collected_actions_json)
        self.assertEqual(json.loads(mock_player_obj.collected_actions_json), expected_actions)

        mock_gm_instance.db_service.update_player_field.assert_called_once_with(
            player_id="player_lang_fallback_db_id",
            field_name='collected_actions_json',
            value=mock_player_obj.collected_actions_json,
            guild_id="guild_lang_fallback"
        )


if __name__ == '__main__':
    unittest.main()
