import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Placeholder for future imports if needed
# from bot.command_modules.action_cmds import cmd_end_turn, cmd_end_party_turn
# from bot.game.models.character import Character # Assuming Character model
# from bot.game.models.party import Party # Assuming Party model

# Actual imports
from bot.command_modules.action_cmds import cmd_end_turn #, cmd_end_party_turn
# from bot.game.models.character import Character # Using MagicMock for Character for now
# from bot.game.models.party import Party

class TestActionCommands(unittest.IsolatedAsyncioTestCase):

    @patch('bot.command_modules.action_cmds.RPGBot') # To mock interaction.client
    async def test_cmd_end_turn_success(self, MockRPGBot):
        # --- Mocks ---
        mock_interaction = AsyncMock()
        mock_interaction.response = AsyncMock()
        mock_interaction.followup = AsyncMock()
        mock_interaction.guild_id = "test_guild_123"
        mock_interaction.user.id = "user_discord_123"

        mock_char_model = MagicMock()
        mock_char_model.id = "char_id_1"
        mock_char_model.name = "Test Character"
        mock_char_model.current_game_status = "исследование"
        mock_char_model.собранные_действия_JSON = 'old_actions' # Start with some old actions

        mock_character_manager = AsyncMock()
        mock_character_manager.get_character_by_discord_id.return_value = mock_char_model
        mock_character_manager.update_character = AsyncMock()

        # Setup mock bot and game_manager structure on interaction.client
        mock_bot_instance = MockRPGBot.return_value
        mock_bot_instance.game_manager = MagicMock()
        mock_bot_instance.game_manager.character_manager = mock_character_manager
        mock_interaction.client = mock_bot_instance
        
        # --- Call the command ---
        await cmd_end_turn.callback(mock_interaction) # Assuming cmd_end_turn is an app_commands.Command

        # --- Assertions ---
        # Check interaction responses
        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
        
        # Check character fetching
        mock_character_manager.get_character_by_discord_id.assert_called_once_with(
            user_id="user_discord_123", guild_id="test_guild_123"
        )

        # Check character updates
        self.assertEqual(mock_char_model.current_game_status, 'ожидание_обработку')
        self.assertEqual(mock_char_model.собранные_действия_JSON, '[]') # Actions cleared
        mock_character_manager.update_character.assert_called_once_with(mock_char_model)
        
        # Check followup message
        mock_interaction.followup.send.assert_called_once_with(
            "Ваш ход завершен. Действия будут обработаны.", ephemeral=True
        )

    @patch('bot.command_modules.action_cmds.RPGBot')
    async def test_cmd_end_turn_no_character(self, MockRPGBot):
        mock_interaction = AsyncMock()
        mock_interaction.response = AsyncMock()
        mock_interaction.followup = AsyncMock()
        mock_interaction.guild_id = "test_guild_123"
        mock_interaction.user.id = "user_discord_123"

        mock_character_manager = AsyncMock()
        mock_character_manager.get_character_by_discord_id.return_value = None # No character found

        mock_bot_instance = MockRPGBot.return_value
        mock_bot_instance.game_manager = MagicMock()
        mock_bot_instance.game_manager.character_manager = mock_character_manager
        mock_interaction.client = mock_bot_instance

        await cmd_end_turn.callback(mock_interaction)

        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
        mock_character_manager.get_character_by_discord_id.assert_called_once_with(
            user_id="user_discord_123", guild_id="test_guild_123"
        )
        mock_character_manager.update_character.assert_not_called()
        mock_interaction.followup.send.assert_called_once_with(
            "Не удалось найти вашего персонажа. Используйте `/start` для создания.", ephemeral=True
        )

    @patch('bot.command_modules.action_cmds.RPGBot')
    async def test_cmd_end_turn_already_waiting(self, MockRPGBot):
        mock_interaction = AsyncMock()
        mock_interaction.response = AsyncMock()
        mock_interaction.followup = AsyncMock()
        mock_interaction.guild_id = "test_guild_123"
        mock_interaction.user.id = "user_discord_123"

        mock_char_model = MagicMock()
        mock_char_model.current_game_status = 'ожидание_обработку' # Already waiting

        mock_character_manager = AsyncMock()
        mock_character_manager.get_character_by_discord_id.return_value = mock_char_model

        mock_bot_instance = MockRPGBot.return_value
        mock_bot_instance.game_manager = MagicMock()
        mock_bot_instance.game_manager.character_manager = mock_character_manager
        mock_interaction.client = mock_bot_instance

        await cmd_end_turn.callback(mock_interaction)

        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
        mock_character_manager.update_character.assert_not_called()
        mock_interaction.followup.send.assert_called_once_with(
            "Вы уже завершили свой ход. Ожидайте обработки.", ephemeral=True
        )

    # --- Tests for cmd_end_party_turn ---
    @patch('bot.command_modules.action_cmds.RPGBot') # Mocks interaction.client
    async def test_cmd_end_party_turn_success_all_ready_trigger(self, MockRPGBot):
        mock_interaction = AsyncMock()
        mock_interaction.response = AsyncMock()
        mock_interaction.followup = AsyncMock()
        mock_interaction.guild_id = "guild1"
        mock_interaction.user.id = "discord_user_leader"
        mock_interaction.channel_id = "channel_123"


        # --- Character Setup ---
        sender_char = MagicMock(id="char_leader", name="Leader", party_id="party1", location_id="loc1", current_game_status="исследование")
        member_in_loc = MagicMock(id="char_member1", name="MemberInLoc", party_id="party1", location_id="loc1", current_game_status="исследование")
        member_other_loc = MagicMock(id="char_member2", name="MemberOtherLoc", party_id="party1", location_id="loc2", current_game_status="исследование")
        member_already_waiting = MagicMock(id="char_member3", name="MemberWaiting", party_id="party1", location_id="loc1", current_game_status="ожидание_обработку")

        # --- Party Setup ---
        mock_party = MagicMock(id="party1", name="The A-Team", player_ids_list=[sender_char.id, member_in_loc.id, member_other_loc.id, member_already_waiting.id])

        # --- Manager Mocks ---
        mock_character_manager = AsyncMock()
        def get_char_by_discord_id_side_effect(user_id, guild_id):
            if user_id == sender_char.id: return sender_char # Assuming discord_id is same as char_id for simplicity here
            return None
        def get_char_by_player_id_side_effect(player_id, guild_id):
            if player_id == sender_char.id: return sender_char
            if player_id == member_in_loc.id: return member_in_loc
            if player_id == member_other_loc.id: return member_other_loc
            if player_id == member_already_waiting.id: return member_already_waiting
            return None
        mock_character_manager.get_character_by_discord_id.side_effect = get_char_by_discord_id_side_effect
        mock_character_manager.get_character_by_player_id.side_effect = get_char_by_player_id_side_effect
        mock_character_manager.update_character = AsyncMock()

        mock_party_manager = AsyncMock()
        mock_party_manager.get_party.return_value = mock_party
        mock_party_manager.check_and_process_party_turn = AsyncMock() # This is key

        # Setup mock bot and game_manager structure
        mock_bot_instance = MockRPGBot.return_value
        mock_bot_instance.game_manager = MagicMock()
        mock_bot_instance.game_manager.character_manager = mock_character_manager
        mock_bot_instance.game_manager.party_manager = mock_party_manager
        mock_bot_instance.game_manager.db_service = AsyncMock() # Required by command structure but not directly tested here for DB writes
        mock_interaction.client = mock_bot_instance

        # Import the command locally to use the patched RPGBot
        from bot.command_modules.action_cmds import cmd_end_party_turn

        # --- Call the command ---
        await cmd_end_party_turn.callback(mock_interaction)

        # --- Assertions ---
        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
        
        # Check characters updated
        # Sender should be updated
        self.assertEqual(sender_char.current_game_status, 'ожидание_обработку')
        # Member in same location, not waiting, should be updated
        self.assertEqual(member_in_loc.current_game_status, 'ожидание_обработку')
        # Member already waiting should not be "re-updated" in this part of logic (though harmless if it is)
        # The count of update_character calls will be more telling.
        # Member in other location should NOT be updated
        self.assertEqual(member_other_loc.current_game_status, 'исследование') 

        # update_character calls: sender_char + member_in_loc
        self.assertEqual(mock_character_manager.update_character.call_count, 2)
        mock_character_manager.update_character.assert_any_call(sender_char)
        mock_character_manager.update_character.assert_any_call(member_in_loc)

        # Check followup message
        # Names that should be in the message: Leader, MemberInLoc
        # Order might vary, so check for content.
        followup_message = mock_interaction.followup.send.call_args[0][0]
        self.assertIn("Ход завершен для следующих членов вашей группы", followup_message)
        self.assertIn(sender_char.name, followup_message)
        self.assertIn(member_in_loc.name, followup_message)
        self.assertNotIn(member_other_loc.name, followup_message)
        self.assertNotIn(member_already_waiting.name, followup_message) # Was already waiting

        # Assert check_and_process_party_turn was called because Leader and MemberInLoc became ready,
        # and MemberWaiting was already ready.
        mock_party_manager.check_and_process_party_turn.assert_called_once_with(
            party_id="party1",
            location_id="loc1",
            guild_id="guild1",
            game_manager=mock_bot_instance.game_manager
        )

    @patch('bot.command_modules.action_cmds.RPGBot')
    async def test_cmd_end_party_turn_sender_not_in_party(self, MockRPGBot):
        mock_interaction = AsyncMock()
        mock_interaction.response = AsyncMock()
        mock_interaction.followup = AsyncMock()
        mock_interaction.guild_id = "guild1"
        mock_interaction.user.id = "discord_user_solo"

        sender_char_no_party = MagicMock(id="char_solo", name="SoloPlayer", party_id=None, location_id="loc1")

        mock_character_manager = AsyncMock()
        mock_character_manager.get_character_by_discord_id.return_value = sender_char_no_party
        
        mock_bot_instance = MockRPGBot.return_value
        mock_bot_instance.game_manager = MagicMock()
        mock_bot_instance.game_manager.character_manager = mock_character_manager
        mock_bot_instance.game_manager.party_manager = AsyncMock() # Needs to exist
        mock_interaction.client = mock_bot_instance
        
        from bot.command_modules.action_cmds import cmd_end_party_turn
        await cmd_end_party_turn.callback(mock_interaction)

        mock_interaction.followup.send.assert_called_once_with("Вы не состоите в группе.", ephemeral=True)
        mock_bot_instance.game_manager.party_manager.check_and_process_party_turn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
