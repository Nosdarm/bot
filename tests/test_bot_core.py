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

    @patch('bot.bot_core.parse_player_action') # Key NLU parser
    @patch('bot.bot_core.OpenAIService') # RPGBot dependency
    @patch('bot.bot_core.GameManager') # RPGBot dependency
    async def test_on_message_action_accumulation(self, MockGameManager, MockOpenAIService, mock_parse_player_action):
        # --- Setup Mocks ---
        mock_settings = {'discord_token': 'fake_token', 'openai_api_key': 'fake_key'} # Dummy settings
        
        # Mock GameManager instance and its components
        mock_gm_instance = MockGameManager.return_value
        mock_character_manager = AsyncMock()
        mock_nlu_data_service = AsyncMock()
        mock_gm_instance.character_manager = mock_character_manager
        mock_gm_instance.nlu_data_service = mock_nlu_data_service

        # Mock Character
        mock_char = MagicMock()
        mock_char.id = "char1"
        mock_char.name = "Player"
        mock_char.current_game_status = "исследование" # NLU processing state
        mock_char.selected_language = "ru"
        mock_char.собранные_действия_JSON = None # Start with no actions

        mock_character_manager.get_character_by_discord_id.return_value = mock_char
        mock_character_manager.update_character = AsyncMock()

        # Mock discord.Message
        mock_message = AsyncMock(spec=discord.Message)
        mock_message.author = AsyncMock(spec=discord.User)
        mock_message.author.bot = False
        mock_message.author.id = "discord_user1"
        mock_message.guild = AsyncMock(spec=discord.Guild)
        mock_message.guild.id = "guild1"
        mock_message.content = "первое действие"
        mock_message.channel = AsyncMock(spec=discord.TextChannel)
        
        # Instantiate RPGBot - its on_message will be called
        # RPGBot constructor: game_manager, openai_service, command_prefix, intents, debug_guild_ids
        intents = discord.Intents.default()
        intents.message_content = True # Explicitly set for on_message testing
        
        # We pass the mocked GameManager and OpenAIService instances to RPGBot
        bot = RPGBot(
            game_manager=mock_gm_instance, 
            openai_service=MockOpenAIService(), 
            command_prefix="!", 
            intents=intents
        )
        # Ensure game_manager is set on bot for on_message
        bot.game_manager = mock_gm_instance


        # --- First message: Accumulate one action ---
        mock_parse_player_action.return_value = ("intent_1", {"entity_1": "value_1"})
        
        await bot.on_message(mock_message)

        # Assertions for first action
        mock_character_manager.get_character_by_discord_id.assert_called_with(user_id="discord_user1", guild_id="guild1")
        mock_parse_player_action.assert_called_with(text="первое действие", language="ru", guild_id="guild1", game_terms_db=mock_nlu_data_service)
        
        expected_actions_after_first = [{"intent": "intent_1", "entities": {"entity_1": "value_1"}, "original_text": "первое действие"}]
        self.assertIsNotNone(mock_char.собранные_действия_JSON)
        self.assertEqual(json.loads(mock_char.собранные_действия_JSON), expected_actions_after_first)
        mock_character_manager.update_character.assert_called_with(mock_char)
        
        # --- Second message: Accumulate another action ---
        mock_message.content = "второе действие"
        mock_parse_player_action.return_value = ("intent_2", {"entity_2": "value_2"})
        # Reset call count for update_character for this new call context if needed, or check call_count increment
        # update_character_call_count_before_second = mock_character_manager.update_character.call_count

        await bot.on_message(mock_message)

        # Assertions for second action
        mock_parse_player_action.assert_called_with(text="второе действие", language="ru", guild_id="guild1", game_terms_db=mock_nlu_data_service)
        
        expected_actions_after_second = [
            {"intent": "intent_1", "entities": {"entity_1": "value_1"}, "original_text": "первое действие"},
            {"intent": "intent_2", "entities": {"entity_2": "value_2"}, "original_text": "второе действие"}
        ]
        self.assertIsNotNone(mock_char.собранные_действия_JSON)
        self.assertEqual(json.loads(mock_char.собранные_действия_JSON), expected_actions_after_second)
        # self.assertEqual(mock_character_manager.update_character.call_count, update_character_call_count_before_second + 1)
        mock_character_manager.update_character.assert_called_with(mock_char) # Called again with updated actions

    @patch('bot.bot_core.parse_player_action') 
    @patch('bot.bot_core.OpenAIService') 
    @patch('bot.bot_core.GameManager')
    async def test_on_message_input_routing_dialogue(self, MockGameManager, MockOpenAIService, mock_parse_player_action):
        # --- Setup Mocks ---
        mock_gm_instance = MockGameManager.return_value
        mock_character_manager = AsyncMock()
        mock_dialogue_manager = AsyncMock() # Key manager for this test
        mock_gm_instance.character_manager = mock_character_manager
        mock_gm_instance.dialogue_manager = mock_dialogue_manager
        mock_gm_instance.nlu_data_service = AsyncMock() # NLU service needed for general on_message path

        mock_char = MagicMock()
        mock_char.id = "char_dialogue"
        mock_char.name = "Talker"
        mock_char.current_game_status = "диалог" # Busy state: dialogue
        mock_char.selected_language = "ru"
        mock_char.собранные_действия_JSON = None 

        mock_character_manager.get_character_by_discord_id.return_value = mock_char

        mock_message = AsyncMock(spec=discord.Message)
        mock_message.author = AsyncMock(spec=discord.User, bot=False, id="discord_user_talker")
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
        mock_dialogue_manager.process_player_dialogue_message.assert_called_once_with(
            character=mock_char,
            message_text="это мое сообщение в диалоге",
            channel_id="channel_dialogue",
            guild_id="guild_dialogue"
        )
        # Character update should not be called by the NLU block in on_message
        mock_character_manager.update_character.assert_not_called() 

    @patch('bot.bot_core.parse_player_action')
    @patch('bot.bot_core.OpenAIService')
    @patch('bot.bot_core.GameManager')
    async def test_on_message_input_routing_combat_logs_no_dialogue_call(self, MockGameManager, MockOpenAIService, mock_parse_player_action):
        # --- Setup Mocks ---
        mock_gm_instance = MockGameManager.return_value
        mock_character_manager = AsyncMock()
        mock_dialogue_manager = AsyncMock() 
        mock_gm_instance.character_manager = mock_character_manager
        mock_gm_instance.dialogue_manager = mock_dialogue_manager # Available, but shouldn't be called for 'бой'
        mock_gm_instance.nlu_data_service = AsyncMock()

        mock_char = MagicMock()
        mock_char.id = "char_fighter"
        mock_char.name = "Fighter"
        mock_char.current_game_status = "бой" # Busy state: combat
        mock_char.selected_language = "ru"
        mock_char.собранные_действия_JSON = None

        mock_character_manager.get_character_by_discord_id.return_value = mock_char

        mock_message = AsyncMock(spec=discord.Message)
        mock_message.author = AsyncMock(spec=discord.User, bot=False, id="discord_user_fighter")
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

if __name__ == '__main__':
    unittest.main()
