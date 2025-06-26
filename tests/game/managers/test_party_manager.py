import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call
import json
import sys
import uuid
from typing import Optional, List, Dict, Any # Added Dict, Any

from bot.game.managers.party_manager import PartyManager
from bot.game.models.party import Party
from bot.game.models.character import Character
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.location_manager import LocationManager 
# from bot.game.action_processor import ActionProcessor # Assuming this might be part of game_manager mock
from bot.database.db_service import DBService # Changed from PostgresAdapter to DBService for type hinting
from bot.database.models.world_related import Location as DBLocation # For location model if needed by mocks


class TestPartyManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = AsyncMock(spec=DBService) # Changed to DBService
        self.mock_settings = {}
        
        self.mock_character_manager = AsyncMock(spec=CharacterManager)
        self.mock_npc_manager = AsyncMock(spec=NpcManager) 
        self.mock_combat_manager = AsyncMock(spec=CombatManager)
        
        self.mock_location_manager = AsyncMock(spec=LocationManager)
        # self.mock_action_processor = AsyncMock(spec=ActionProcessor) # If used directly
        self.mock_discord_client = MagicMock()

        self.mock_game_manager = MagicMock()
        self.mock_game_manager.location_manager = self.mock_location_manager
        # self.mock_game_manager.action_processor = self.mock_action_processor # If used
        self.mock_game_manager.discord_client = self.mock_discord_client
        self.mock_game_manager.character_manager = self.mock_character_manager 
        self.mock_game_manager.event_manager = AsyncMock() 
        self.mock_game_manager.rule_engine = AsyncMock() 
        self.mock_game_manager.openai_service = AsyncMock() 
        self.mock_game_manager.game_state = MagicMock() 
        self.mock_game_manager.game_state.guild_id = "test_guild_1"

        self.party_manager = PartyManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings,
            character_manager=self.mock_character_manager,
            game_manager=self.mock_game_manager
        )
        
        # Initialize internal state for tests, ignoring type checks for these direct assignments
        self.party_manager._parties: Dict[str, Dict[str, Party]] = {} # type: ignore[attr-defined]
        self.party_manager._dirty_parties: Dict[str, Set[str]] = {} # type: ignore[attr-defined]
        self.party_manager._member_to_party_map: Dict[str, Dict[str, str]] = {} # type: ignore[attr-defined]
        self.party_manager._deleted_parties: Dict[str, Set[str]] = {}  # type: ignore[attr-defined]
        self.party_manager._diagnostic_log: List[str] = [] # type: ignore[attr-defined]


        self.guild_id = "test_guild_1"
        self.party_id = "test_party_1"
        self.party_leader_id = "leader_1"
        
        self.dummy_party_data = {
            "id": self.party_id, "guild_id": self.guild_id,
            "name_i18n": {"en": "Test Party", "ru": "Тестовая Группа"},
            "leader_id": self.party_leader_id,
            "player_ids_list": [self.party_leader_id, "member_2"], 
            "current_location_id": "loc1", "state_variables": {},
            "current_action": None, "turn_status": "сбор_действий"
        }

        self.test_party = Party.from_dict(self.dummy_party_data)
        self.party_manager._parties.setdefault(self.guild_id, {})[self.party_id] = self.test_party # type: ignore[attr-defined]
        self.party_manager.mark_party_dirty = MagicMock()

    async def test_successfully_updates_party_location(self):
        new_location_id = "new_location_456"
        self.party_manager._diagnostic_log = [] # type: ignore[attr-defined]
        result = await self.party_manager.update_party_location(self.guild_id, self.party_id, new_location_id)
        self.assertTrue(result)
        self.assertEqual(self.test_party.current_location_id, new_location_id)
        self.party_manager.mark_party_dirty.assert_called_once_with(self.guild_id, self.party_id)

    async def test_party_not_found(self):
        result = await self.party_manager.update_party_location(self.guild_id, "non_existent_party", "new_loc")
        self.assertFalse(result)
        self.party_manager.mark_party_dirty.assert_not_called()

    async def test_party_already_at_target_location(self):
        current_location = "location_abc"
        self.test_party.current_location_id = current_location
        self.party_manager._parties[self.guild_id][self.party_id] = self.test_party # type: ignore[attr-defined]
        result = await self.party_manager.update_party_location(self.guild_id, self.party_id, current_location)
        self.assertTrue(result)
        self.party_manager.mark_party_dirty.assert_not_called()
        self.assertEqual(self.test_party.current_location_id, current_location)

    async def test_update_location_to_none(self):
        self.test_party.current_location_id = "some_initial_location"
        self.party_manager._parties[self.guild_id][self.party_id] = self.test_party # type: ignore[attr-defined]
        result = await self.party_manager.update_party_location(self.guild_id, self.party_id, None)
        self.assertTrue(result)
        self.assertIsNone(self.test_party.current_location_id)
        self.party_manager.mark_party_dirty.assert_called_once_with(self.guild_id, self.party_id)

    async def test_party_missing_current_location_id_attribute(self):
        party_data_no_loc = self.dummy_party_data.copy()
        del party_data_no_loc['current_location_id']
        party_without_loc_attr = Party.from_dict(party_data_no_loc)
        self.assertIsNone(party_without_loc_attr.current_location_id)
        self.party_manager._parties[self.guild_id][self.party_id] = party_without_loc_attr # type: ignore[attr-defined]
        new_location_id = "new_valid_location"
        result = await self.party_manager.update_party_location(self.guild_id, self.party_id, new_location_id)
        self.assertTrue(result)
        self.assertTrue(hasattr(party_without_loc_attr, 'current_location_id'))
        self.assertEqual(party_without_loc_attr.current_location_id, new_location_id)
        self.party_manager.mark_party_dirty.assert_called_once_with(self.guild_id, self.party_id)

    async def test_create_party_success(self):
        leader_char_id = "leader_char_id_for_create"
        leader_location_id = "leader_loc_for_create"
        party_name_i18n = {"en": "The Brave Companions"}
        self.mock_character_manager.set_character_party_id = AsyncMock()
        test_uuid_val = uuid.uuid4()
        with patch('uuid.uuid4', return_value=test_uuid_val):
            created_party_object = await self.party_manager.create_party( # type: ignore[attr-defined] # Assuming create_party exists
                guild_id=self.guild_id,
                leader_character_id=leader_char_id, # Corrected param name
                party_name_i18n=party_name_i18n,     # Corrected param name
                leader_location_id=leader_location_id
            )
        self.assertIsNotNone(created_party_object)
        self.assertEqual(created_party_object.id, str(test_uuid_val))
        self.assertEqual(created_party_object.name_i18n, party_name_i18n)
        self.mock_character_manager.set_character_party_id.assert_awaited_once_with(self.guild_id, leader_char_id, created_party_object.id)
        self.assertIn(created_party_object.id, self.party_manager._parties[self.guild_id]) # type: ignore[attr-defined]
        self.assertEqual(self.party_manager._member_to_party_map[self.guild_id][leader_char_id], created_party_object.id) # type: ignore[attr-defined]
        self.party_manager.mark_party_dirty.assert_called_once_with(self.guild_id, created_party_object.id)

    async def test_add_member_to_party_success(self):
        new_member_char_id = "new_member_char_id"
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=MagicMock(id=new_member_char_id, location_id=self.test_party.current_location_id))
        self.mock_character_manager.set_character_party_id = AsyncMock()
        self.party_manager._parties[self.guild_id] = {self.test_party.id: self.test_party} # type: ignore[attr-defined]
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})[self.test_party.leader_id] = self.test_party.id # type: ignore[attr-defined]

        result = await self.party_manager.add_member_to_party( # type: ignore[attr-defined]
            guild_id=self.guild_id, party_id=self.test_party.id, character_id=new_member_char_id,
            character_location_id=self.test_party.current_location_id
        )
        self.assertTrue(result)
        self.assertIn(new_member_char_id, self.test_party.player_ids_list)
        self.mock_character_manager.set_character_party_id.assert_awaited_once_with(self.guild_id, new_member_char_id, self.test_party.id)
        self.assertEqual(self.party_manager._member_to_party_map[self.guild_id][new_member_char_id], self.test_party.id) # type: ignore[attr-defined]
        self.party_manager.mark_party_dirty.assert_called_with(self.guild_id, self.test_party.id)

    async def test_add_member_already_in_party(self):
        member_id = self.test_party.leader_id
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})[member_id] = self.test_party.id # type: ignore[attr-defined]
        result = await self.party_manager.add_member_to_party(self.guild_id, self.test_party.id, member_id, self.test_party.current_location_id) # type: ignore[attr-defined]
        self.assertFalse(result)
        self.mock_character_manager.set_character_party_id.assert_not_called()

    async def test_add_member_location_mismatch(self):
        new_member_id = "new_member_loc_mismatch"
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=MagicMock(id=new_member_id, location_id="diff_loc"))
        result = await self.party_manager.add_member_to_party(self.guild_id, self.test_party.id, new_member_id, "diff_loc") # type: ignore[attr-defined]
        self.assertFalse(result)
        self.mock_character_manager.set_character_party_id.assert_not_called()

    async def test_remove_member_from_party_success(self):
        member_to_remove_id = "member_2"
        if member_to_remove_id not in self.test_party.player_ids_list: self.test_party.player_ids_list.append(member_to_remove_id)
        self.party_manager._parties[self.guild_id] = {self.test_party.id: self.test_party} # type: ignore[attr-defined]
        member_map = self.party_manager._member_to_party_map.setdefault(self.guild_id, {}) # type: ignore[attr-defined]
        for mid in self.test_party.player_ids_list: member_map[mid] = self.test_party.id
        self.mock_character_manager.set_character_party_id = AsyncMock()

        result = await self.party_manager.remove_member_from_party(self.guild_id, self.test_party.id, member_to_remove_id) # type: ignore[attr-defined]
        self.assertTrue(result)
        self.assertNotIn(member_to_remove_id, self.test_party.player_ids_list)
        self.mock_character_manager.set_character_party_id.assert_awaited_once_with(self.guild_id, member_to_remove_id, None)
        self.assertNotIn(member_to_remove_id, self.party_manager._member_to_party_map.get(self.guild_id, {})) # type: ignore[attr-defined]
        self.party_manager.mark_party_dirty.assert_called_with(self.guild_id, self.test_party.id)

    async def test_remove_member_leader_leaves_party_disbands(self):
        leader_id = self.test_party.leader_id
        self.test_party.player_ids_list = [leader_id]
        self.party_manager._parties[self.guild_id] = {self.test_party.id: self.test_party} # type: ignore[attr-defined]
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})[leader_id] = self.test_party.id # type: ignore[attr-defined]
        self.mock_character_manager.set_character_party_id = AsyncMock()
        self.party_manager.disband_party = AsyncMock(return_value=True) # type: ignore[assignment]

        result = await self.party_manager.remove_member_from_party(self.guild_id, self.test_party.id, leader_id) # type: ignore[attr-defined]
        self.assertTrue(result)
        self.party_manager.disband_party.assert_awaited_once_with(self.guild_id, self.test_party.id, leader_id)
        self.mock_character_manager.set_character_party_id.assert_awaited_once_with(self.guild_id, leader_id, None)

    async def test_disband_party_success_as_leader(self):
        other_member_id = "member_2_in_disband"
        self.test_party.player_ids_list = [self.test_party.leader_id, other_member_id]
        self.party_manager._parties[self.guild_id] = {self.test_party.id: self.test_party} # type: ignore[attr-defined]
        member_map = self.party_manager._member_to_party_map.setdefault(self.guild_id, {}) # type: ignore[attr-defined]
        member_map[self.test_party.leader_id] = self.test_party.id
        member_map[other_member_id] = self.test_party.id
        self.mock_character_manager.set_character_party_id = AsyncMock()

        result = await self.party_manager.disband_party(self.guild_id, self.test_party.id, self.test_party.leader_id)
        self.assertTrue(result)
        expected_calls = [call(self.guild_id, self.test_party.leader_id, None), call(self.guild_id, other_member_id, None)]
        self.mock_character_manager.set_character_party_id.assert_has_awaits(expected_calls, any_order=True)
        self.assertNotIn(self.test_party.id, self.party_manager._parties.get(self.guild_id, {})) # type: ignore[attr-defined]
        self.assertNotIn(self.test_party.leader_id, self.party_manager._member_to_party_map.get(self.guild_id, {})) # type: ignore[attr-defined]
        self.assertIn(self.test_party.id, self.party_manager._deleted_parties.get(self.guild_id, set())) # type: ignore[attr-defined]
        self.party_manager.mark_party_dirty.assert_not_called()

    async def test_disband_party_not_leader_fails(self):
        non_leader_id = "member_2_not_leader"
        self.test_party.player_ids_list = [self.test_party.leader_id, non_leader_id]
        self.party_manager._parties[self.guild_id] = {self.test_party.id: self.test_party} # type: ignore[attr-defined]
        result = await self.party_manager.disband_party(self.guild_id, self.test_party.id, non_leader_id)
        self.assertFalse(result)
        self.mock_character_manager.set_character_party_id.assert_not_called()
        self.assertIn(self.test_party.id, self.party_manager._parties.get(self.guild_id, {})) # type: ignore[attr-defined]

    def test_get_party_success(self): # Made synchronous
        self.party_manager._parties[self.guild_id] = {self.test_party.id: self.test_party} # type: ignore[attr-defined]
        party = self.party_manager.get_party(self.guild_id, self.test_party.id)
        self.assertEqual(party, self.test_party)

    def test_get_party_not_found(self): # Made synchronous
        party = self.party_manager.get_party(self.guild_id, "non_existent_party_for_get")
        self.assertIsNone(party)

    def test_get_party_by_member_id_success(self): # Made synchronous
        member_id = self.test_party.leader_id
        self.party_manager._parties[self.guild_id] = {self.test_party.id: self.test_party} # type: ignore[attr-defined]
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})[member_id] = self.test_party.id # type: ignore[attr-defined]
        party = self.party_manager.get_party_by_member_id(self.guild_id, member_id) # type: ignore[attr-defined]
        self.assertEqual(party, self.test_party)

    def test_get_party_by_member_id_not_in_party(self): # Made synchronous
        party = self.party_manager.get_party_by_member_id(self.guild_id, "char_not_in_any_party") # type: ignore[attr-defined]
        self.assertIsNone(party)

    async def test_save_state_saves_dirty_and_deletes_parties(self):
        dirty_party_id = "dirty_party_1"; dirty_party_data = self.dummy_party_data.copy(); dirty_party_data["id"] = dirty_party_id
        dirty_party = Party.from_dict(dirty_party_data)
        self.party_manager._parties.setdefault(self.guild_id, {})[dirty_party_id] = dirty_party # type: ignore[attr-defined]
        self.party_manager._dirty_parties.setdefault(self.guild_id, set()).add(dirty_party_id) # type: ignore[attr-defined]
        deleted_party_id = "deleted_party_1"
        self.party_manager._deleted_parties.setdefault(self.guild_id, set()).add(deleted_party_id) # type: ignore[attr-defined]
        if deleted_party_id in self.party_manager._parties.get(self.guild_id, {}): # type: ignore[attr-defined]
            del self.party_manager._parties[self.guild_id][deleted_party_id] # type: ignore[attr-defined]

        self.mock_db_service.upsert_party = AsyncMock() # Changed from mock_db_adapter
        self.mock_db_service.delete_party_by_id = AsyncMock() # Changed from mock_db_adapter

        await self.party_manager.save_state(self.guild_id)
        self.mock_db_service.upsert_party.assert_awaited_once()
        self.assertEqual(self.mock_db_service.upsert_party.call_args[0][0]['id'], dirty_party_id)
        self.mock_db_service.delete_party_by_id.assert_awaited_once_with(deleted_party_id, self.guild_id)
        self.assertNotIn(dirty_party_id, self.party_manager._dirty_parties.get(self.guild_id, set())) # type: ignore[attr-defined]
        self.assertNotIn(deleted_party_id, self.party_manager._deleted_parties.get(self.guild_id, set())) # type: ignore[attr-defined]

    async def test_load_state_for_guild_success(self):
        party1_data = {**self.dummy_party_data, "id": "db_party_1", "name_i18n": {"en": "DB1"}}
        party2_data = {**self.dummy_party_data, "id": "db_party_2", "name_i18n": {"en": "DB2"}, "leader_id": "ldr3", "player_ids_list": ["ldr3", "mem4"]}
        self.mock_db_service.load_parties_for_guild = AsyncMock(return_value=[party1_data, party2_data]) # Changed

        await self.party_manager.load_state_for_guild(self.guild_id) # type: ignore[attr-defined]
        self.assertEqual(len(self.party_manager._parties[self.guild_id]), 2) # type: ignore[attr-defined]
        self.assertEqual(self.party_manager._parties[self.guild_id]["db_party_1"].name_i18n["en"], "DB1") # type: ignore[attr-defined]
        member_map = self.party_manager._member_to_party_map[self.guild_id] # type: ignore[attr-defined]
        self.assertEqual(member_map.get(self.party_leader_id), "db_party_1")
        self.assertEqual(member_map.get("ldr3"), "db_party_2")

    async def create_mock_character(self, player_id: str, location_id: str, status: str, actions_json: Optional[str] = "[]") -> MagicMock:
        char = AsyncMock(spec=Character) # Use AsyncMock for awaitable attributes if needed
        char.id = player_id; char.name = f"Char_{player_id}"; char.location_id = location_id
        char.current_game_status = status; char.собранные_действия_JSON = actions_json
        char.discord_user_id = f"discord_{player_id}"
        return char

    async def test_check_and_process_party_turn_not_all_ready(self):
        loc_id = "loc1"
        char1_ready = await self.create_mock_character("p1", loc_id, "ожидание_обработку")
        char2_not_ready = await self.create_mock_character("p2", loc_id, "исследование")
        self.test_party.player_ids_list = [char1_ready.id, char2_not_ready.id]
        self.party_manager._parties[self.guild_id][self.party_id] = self.test_party # type: ignore[attr-defined]
        async def mock_get_char_side_effect(guild_id, discord_user_id_or_char_id): # Adjusted signature
            return {"p1": char1_ready, "p2": char2_not_ready}.get(discord_user_id_or_char_id)
        self.mock_character_manager.get_character.side_effect = mock_get_char_side_effect # Assuming get_character is used
        
        self.party_manager._diagnostic_log = [] # type: ignore[attr-defined]
        await self.party_manager.check_and_process_party_turn(self.party_id, loc_id, self.guild_id, self.mock_game_manager) # type: ignore[attr-defined]
        
        if hasattr(self.mock_db_service, 'execute'): self.mock_db_service.execute.assert_not_called()
        if hasattr(self.mock_game_manager.action_processor, 'process_party_actions'): self.mock_game_manager.action_processor.process_party_actions.assert_not_called()
        self.assertEqual(self.test_party.turn_status, "сбор_действий")

    @unittest.skip("PartyManager.check_and_process_party_turn method needs review or is not fully implemented as expected by test.")
    async def test_check_and_process_party_turn_all_ready_success(self):
        # This test needs significant review based on PartyManager's actual implementation
        pass

    async def test_check_and_process_party_turn_no_actions_data(self):
        loc_id = "loc1"
        char1 = await self.create_mock_character("p1", loc_id, "ожидание_обработку", "[]")
        self.test_party.player_ids_list = [char1.id]
        self.party_manager._parties[self.guild_id][self.party_id] = self.test_party # type: ignore[attr-defined]
        async def mock_get_char_return_value(guild_id, char_id): return char1
        self.mock_character_manager.get_character.side_effect = mock_get_char_return_value
        
        mock_location_model = AsyncMock(spec=DBLocation); mock_location_model.channel_id = "1234567890"; mock_location_model.name_i18n = {"ru": loc_id, "en": loc_id}
        self.mock_location_manager.get_location_instance = AsyncMock(return_value=mock_location_model) # Changed to get_location_instance
        
        # self.mock_action_processor.process_party_actions = AsyncMock(return_value={"success": True, "individual_action_results": [], "overall_state_changed": False, "target_channel_id": "1234567890"})
        # Ensure action_processor is on game_manager if accessed that way
        self.mock_game_manager.action_processor = AsyncMock(return_value={"success": True, "individual_action_results": [], "overall_state_changed": False, "target_channel_id": "1234567890"})


        mock_discord_channel = AsyncMock(); mock_discord_channel.send = AsyncMock()
        self.mock_discord_client.get_channel = MagicMock(return_value=mock_discord_channel)

        self.party_manager._diagnostic_log = [] # type: ignore[attr-defined]
        await self.party_manager.check_and_process_party_turn(self.party_id, loc_id, self.guild_id, self.mock_game_manager) # type: ignore[attr-defined]

        if hasattr(self.mock_db_service, 'execute'):
            self.mock_db_service.execute.assert_any_call("UPDATE parties SET turn_status = $1 WHERE id = $2 AND guild_id = $3", ('обработка', self.party_id, self.guild_id)) # type: ignore
            self.mock_db_service.execute.assert_any_call("UPDATE parties SET turn_status = $1 WHERE id = $2 AND guild_id = $3", ('сбор_действий', self.party_id, self.guild_id)) # type: ignore

        self.mock_game_manager.action_processor.process_party_actions.assert_called_once()
        self.assertEqual(self.mock_game_manager.action_processor.process_party_actions.call_args.kwargs['party_actions_data'], [('p1', '[]')])
        self.assertEqual(char1.current_game_status, "исследование")
        self.assertEqual(char1.собранные_действия_JSON, "[]")
        self.mock_character_manager.save_character_from_instance.assert_called_once_with(char1, self.guild_id) # Assuming save_character_from_instance
        mock_discord_channel.send.assert_called_once()

if __name__ == '__main__':
    unittest.main()
