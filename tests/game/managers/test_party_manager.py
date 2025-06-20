import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import json # For Character.собранные_действия_JSON
from typing import Optional, List # Added Optional and List

from bot.game.managers.party_manager import PartyManager
from bot.game.models.party import Party
from bot.game.models.character import Character # For creating mock character objects
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager # Though not directly used in these new tests
from bot.game.managers.combat_manager import CombatManager # Though not directly used in these new tests
from bot.game.managers.location_manager import LocationManager 
from bot.game.action_processor import ActionProcessor 
from bot.database.postgres_adapter import PostgresAdapter


class TestPartyManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_adapter = AsyncMock(spec=PostgresAdapter)
        self.mock_settings = {}
        
        self.mock_character_manager = AsyncMock(spec=CharacterManager)
        self.mock_npc_manager = AsyncMock(spec=NpcManager) 
        self.mock_combat_manager = AsyncMock(spec=CombatManager)
        
        # Mocks for check_and_process_party_turn dependencies
        self.mock_location_manager = AsyncMock(spec=LocationManager)
        self.mock_action_processor = AsyncMock(spec=ActionProcessor)
        self.mock_discord_client = AsyncMock() 

        # Mock game_manager which provides access to other managers and discord_client
        self.mock_game_manager = MagicMock()
        self.mock_game_manager.location_manager = self.mock_location_manager
        self.mock_game_manager.action_processor = self.mock_action_processor
        self.mock_game_manager.discord_client = self.mock_discord_client
        # For ActionProcessor call through game_manager if needed by AP
        self.mock_game_manager.character_manager = self.mock_character_manager 
        self.mock_game_manager.event_manager = AsyncMock() 
        self.mock_game_manager.rule_engine = AsyncMock() 
        self.mock_game_manager.openai_service = AsyncMock() 
        self.mock_game_manager.game_state = MagicMock() 
        self.mock_game_manager.game_state.guild_id = "test_guild_1" # Ensure guild_id is on game_state for AP

        self.party_manager = PartyManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings,
            character_manager=self.mock_character_manager, # PartyManager needs this directly
            npc_manager=self.mock_npc_manager, 
            combat_manager=self.mock_combat_manager 
        )
        
        self.party_manager._parties = {}
        self.party_manager._dirty_parties = {}
        self.party_manager._member_to_party_map = {}
        self.party_manager._deleted_parties = {} 

        self.guild_id = "test_guild_1"
        self.party_id = "test_party_1"
        self.party_leader_id = "leader_1"
        
        self.dummy_party_data = {
            "id": self.party_id,
            "guild_id": self.guild_id,
            "name": "Test Party",
            "leader_id": self.party_leader_id,
            "player_ids_list": [self.party_leader_id, "member_2"], 
            "current_location_id": "loc1", 
            "state_variables": {},
            "current_action": None,
            "turn_status": "сбор_действий" 
        }
        self.test_party = Party.from_dict(self.dummy_party_data)
        self.party_manager._parties.setdefault(self.guild_id, {})[self.party_id] = self.test_party
        self.party_manager.mark_party_dirty = MagicMock()

    async def test_successfully_updates_party_location(self):
        # This test was pre-existing, ensure it still works or adapt
        new_location_id = "new_location_456"
        context = {"reason": "test_move"}

        result = await self.party_manager.update_party_location(
            self.party_id, new_location_id, self.guild_id, context
        )

        self.assertTrue(result)
        self.assertEqual(self.test_party.current_location_id, new_location_id)
        self.party_manager.mark_party_dirty.assert_called_once_with(self.guild_id, self.party_id)

    async def test_party_not_found(self):
        non_existent_party_id = "party_does_not_exist"
        new_location_id = "new_location_789"
        context = {}

        result = await self.party_manager.update_party_location(
            non_existent_party_id, new_location_id, self.guild_id, context
        )

        self.assertFalse(result)
        self.party_manager.mark_party_dirty.assert_not_called()

    async def test_party_already_at_target_location(self):
        # Set current location to be the same as new_location_id
        current_location = "location_abc"
        self.test_party.current_location_id = current_location
        
        # Re-cache the party with the updated current_location_id
        self.party_manager._parties[self.guild_id][self.party_id] = self.test_party
        
        context = {}

        result = await self.party_manager.update_party_location(
            self.party_id, current_location, self.guild_id, context
        )

        self.assertTrue(result) # Should return True as it's already there
        # Based on current implementation in PartyManager, mark_party_dirty is NOT called if location is same.
        self.party_manager.mark_party_dirty.assert_not_called()
        self.assertEqual(self.test_party.current_location_id, current_location)


    async def test_update_location_to_none(self):
        new_location_id = None # Setting location to None
        context = {"reason": "teleport_to_void"}

        # Ensure there's an initial location
        self.test_party.current_location_id = "some_initial_location"
        self.party_manager._parties[self.guild_id][self.party_id] = self.test_party


        result = await self.party_manager.update_party_location(
            self.party_id, new_location_id, self.guild_id, context
        )

        self.assertTrue(result)
        self.assertIsNone(self.test_party.current_location_id)
        self.party_manager.mark_party_dirty.assert_called_once_with(self.guild_id, self.party_id)

    async def test_party_missing_current_location_id_attribute(self):
        # Create a party object that doesn't have 'current_location_id'
        party_data_no_loc = self.dummy_party_data.copy()
        del party_data_no_loc['current_location_id'] # Remove the attribute
        party_without_loc_attr = Party.from_dict(party_data_no_loc)
        
        # Ensure this attribute is indeed missing before the call for this specific test object
        self.assertFalse(hasattr(party_without_loc_attr, 'current_location_id'))

        self.party_manager._parties[self.guild_id][self.party_id] = party_without_loc_attr
        
        new_location_id = "new_valid_location"
        context = {}

        # The method should initialize current_location_id to None and then update it
        result = await self.party_manager.update_party_location(
            self.party_id, new_location_id, self.guild_id, context
        )

        self.assertTrue(result)
        self.assertTrue(hasattr(party_without_loc_attr, 'current_location_id')) # Attribute should now exist
        self.assertEqual(party_without_loc_attr.current_location_id, new_location_id)
        self.party_manager.mark_party_dirty.assert_called_once_with(self.guild_id, self.party_id)

        self.mock_char_manager = AsyncMock()
        # self.party_manager = PartyManager(
        #     db_adapter=self.mock_db_adapter,
        #     settings=self.mock_settings,
        #     character_manager=self.mock_char_manager
        # )
        pass

        # Initialize/reset internal caches for each test
        self.party_manager._parties = {}
        self.party_manager._dirty_parties = {}
        self.party_manager._member_to_party_map = {}
        self.party_manager._deleted_parties = {} # Ensure this is also reset

    async def test_placeholder_party_manager(self):
        # This is a placeholder test.
        # Actual tests for PartyManager methods would go here or in other methods.
        self.assertTrue(True)

    # Placeholder for test_successfully_updates_party_location (if it were to be added here)
    # async def test_successfully_updates_party_location(self):
    #     pass

    # Placeholder for test_party_not_found
    # async def test_party_not_found(self):
    #     pass

    # ... and so on for other test methods mentioned in the prompt,
    # ensuring they are part of this class if they were intended for PartyManager tests.
    # For now, only the setup and placeholder are implemented as per current file content.

    # --- Tests for check_and_process_party_turn ---

    async def create_mock_character(self, player_id: str, location_id: str, status: str, actions_json: Optional[str] = "[]") -> MagicMock:
        char = MagicMock(spec=Character)
        char.id = player_id
        char.name = f"Char_{player_id}"
        char.location_id = location_id
        char.current_game_status = status
        char.собранные_действия_JSON = actions_json
        char.discord_user_id = f"discord_{player_id}" # Needed by ActionProcessor via char_model
        return char

    async def test_check_and_process_party_turn_not_all_ready(self):
        loc_id = "loc1"
        char1_ready = await self.create_mock_character("p1", loc_id, "ожидание_обработку")
        char2_not_ready = await self.create_mock_character("p2", loc_id, "исследование")
        
        self.test_party.player_ids_list = [char1_ready.id, char2_not_ready.id]
        self.party_manager._parties[self.guild_id][self.party_id] = self.test_party

        self.mock_character_manager.get_character_by_player_id.side_effect = lambda player_id, guild_id: {
            "p1": char1_ready, "p2": char2_not_ready
        }.get(player_id)

        await self.party_manager.check_and_process_party_turn(self.party_id, loc_id, self.guild_id, self.mock_game_manager)

        self.mock_db_adapter.execute.assert_not_called() # No status change for party
        self.mock_action_processor.process_party_actions.assert_not_called()
        self.assertEqual(self.test_party.turn_status, "сбор_действий") # Should remain unchanged

    async def test_check_and_process_party_turn_all_ready_success(self):
        loc_id = "loc1"
        char1_actions = json.dumps([{"intent": "spell", "entities": {"target": "enemy"}}])
        char1 = await self.create_mock_character("p1", loc_id, "ожидание_обработку", char1_actions)
        char2 = await self.create_mock_character("p2", loc_id, "ожидание_обработку", "[]") # No actions

        self.test_party.player_ids_list = [char1.id, char2.id]
        self.party_manager._parties[self.guild_id][self.party_id] = self.test_party
        
        self.mock_character_manager.get_character_by_player_id.side_effect = lambda player_id, guild_id: {
            "p1": char1, "p2": char2
        }.get(player_id)
        
        # Mock ActionProcessor response
        self.mock_action_processor.process_party_actions.return_value = {
            "success": True, 
            "individual_action_results": [], 
            "overall_state_changed": True
        }
        
        # Mock LocationManager for channel retrieval
        mock_location_model = MagicMock()
        mock_location_model.channel_id = "1234567890"
        self.mock_location_manager.get_location.return_value = mock_location_model
        
        mock_discord_channel = AsyncMock()
        self.mock_discord_client.get_channel.return_value = mock_discord_channel

        await self.party_manager.check_and_process_party_turn(self.party_id, loc_id, self.guild_id, self.mock_game_manager)

        # 1. Party status updated to 'обработка' and then to 'сбор_действий'
        self.mock_db_adapter.execute.assert_any_call(
            "UPDATE parties SET turn_status = ? WHERE id = ? AND guild_id = ?", 
            ('обработка', self.party_id, self.guild_id)
        )
        self.mock_db_adapter.execute.assert_any_call(
            "UPDATE parties SET turn_status = ? WHERE id = ? AND guild_id = ?", 
            ('сбор_действий', self.party_id, self.guild_id)
        )
        self.assertEqual(self.test_party.turn_status, "сбор_действий")

        # 2. ActionProcessor called
        expected_actions_data = [
            (char1.id, char1_actions),
            (char2.id, "[]") 
        ]
        self.mock_action_processor.process_party_actions.assert_called_once_with(
            game_state=self.mock_game_manager.game_state,
            char_manager=self.mock_character_manager,
            loc_manager=self.mock_location_manager,
            event_manager=self.mock_game_manager.event_manager,
            rule_engine=self.mock_game_manager.rule_engine,
            openai_service=self.mock_game_manager.openai_service,
            party_actions_data=expected_actions_data,
            ctx_channel_id_fallback=int(mock_location_model.channel_id)
        )

        # 3. Character statuses reset and actions cleared
        self.assertEqual(char1.current_game_status, "исследование")
        self.assertEqual(char1.собранные_действия_JSON, "[]")
        self.mock_character_manager.update_character.assert_any_call(char1)
        
        self.assertEqual(char2.current_game_status, "исследование")
        self.assertEqual(char2.собранные_действия_JSON, "[]")
        self.mock_character_manager.update_character.assert_any_call(char2)
        self.assertEqual(self.mock_character_manager.update_character.call_count, 2)


        # 4. Notification sent
        self.mock_location_manager.get_location.assert_called_with(loc_id, self.guild_id)
        self.mock_discord_client.get_channel.assert_called_with(int(mock_location_model.channel_id))
        mock_discord_channel.send.assert_called_once()
        self.assertIn("Ход для группы 'Test Party' в локации 'loc1' был обработан.", mock_discord_channel.send.call_args[0][0])

    async def test_check_and_process_party_turn_no_actions_data(self):
        loc_id = "loc1"
        char1 = await self.create_mock_character("p1", loc_id, "ожидание_обработку", "[]") # Empty actions
        
        self.test_party.player_ids_list = [char1.id]
        self.party_manager._parties[self.guild_id][self.party_id] = self.test_party
        
        self.mock_character_manager.get_character_by_player_id.return_value = char1
        
        mock_location_model = MagicMock()
        mock_location_model.channel_id = "1234567890"
        self.mock_location_manager.get_location.return_value = mock_location_model
        mock_discord_channel = AsyncMock()
        self.mock_discord_client.get_channel.return_value = mock_discord_channel

        await self.party_manager.check_and_process_party_turn(self.party_id, loc_id, self.guild_id, self.mock_game_manager)
        
        # Party status should still cycle
        self.mock_db_adapter.execute.assert_any_call(
            "UPDATE parties SET turn_status = ? WHERE id = ? AND guild_id = ?", ('обработка', self.party_id, self.guild_id))
        self.mock_db_adapter.execute.assert_any_call(
            "UPDATE parties SET turn_status = ? WHERE id = ? AND guild_id = ?", ('сбор_действий', self.party_id, self.guild_id))

        # ActionProcessor should be called with empty list or not called if party_actions_data is empty before call
        # Based on PartyManager code, it's called with empty list:
        self.mock_action_processor.process_party_actions.assert_called_once() 
        called_args, _ = self.mock_action_processor.process_party_actions.call_args
        self.assertEqual(called_args[6], []) # party_actions_data should be empty list

        self.assertEqual(char1.current_game_status, "исследование")
        self.assertEqual(char1.собранные_действия_JSON, "[]")
        self.mock_character_manager.update_character.assert_called_once_with(char1)
        mock_discord_channel.send.assert_called_once()


if __name__ == '__main__':
    unittest.main()
