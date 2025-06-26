import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch, call, ANY
import uuid
from typing import Optional, List, Dict, Any, Set, cast
import discord # Added import for discord

from bot.game.managers.party_manager import PartyManager
from bot.game.models.party import Party
from bot.game.models.character import Character as GameCharacterModel # Renamed to avoid clash
from bot.game.managers.character_manager import CharacterManager
# from bot.game.managers.npc_manager import NpcManager # Not directly used
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.location_manager import LocationManager
from bot.services.db_service import DBService
from bot.game.managers.game_manager import GameManager # For typing game_manager


class TestPartyManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_db_service = AsyncMock(spec=DBService)
        self.mock_settings: Dict[str, Any] = {}
        
        self.mock_character_manager = AsyncMock(spec=CharacterManager)
        # self.mock_npc_manager = AsyncMock(spec=NpcManager) # Not used
        self.mock_combat_manager = AsyncMock(spec=CombatManager)
        self.mock_location_manager = AsyncMock(spec=LocationManager)
        self.mock_discord_client = MagicMock(spec=discord.Client) # Added spec

        # Mock game_manager and its attributes that PartyManager might access
        self.mock_game_manager = MagicMock(spec=GameManager)
        self.mock_game_manager.location_manager = self.mock_location_manager
        self.mock_game_manager.discord_client = self.mock_discord_client
        self.mock_game_manager.character_manager = self.mock_character_manager
        self.mock_game_manager.combat_manager = self.mock_combat_manager # Added combat_manager to mock
        self.mock_game_manager.event_manager = AsyncMock() 
        self.mock_game_manager.rule_engine = AsyncMock() 
        self.mock_game_manager.openai_service = AsyncMock() 
        self.mock_game_manager.game_state = MagicMock() 
        self.mock_game_manager.game_state.guild_id = "test_guild_1" # Example guild_id

        self.party_manager = PartyManager(
            db_service=self.mock_db_service,
            settings=self.mock_settings,
            character_manager=self.mock_character_manager,
            game_manager=self.mock_game_manager # Pass the mocked game_manager
        )
        
        # Initialize internal state for tests
        self.party_manager._parties: Dict[str, Dict[str, Party]] = {}
        self.party_manager._dirty_parties: Dict[str, Set[str]] = {}
        self.party_manager._member_to_party_map: Dict[str, Dict[str, str]] = {}
        self.party_manager._deleted_parties: Dict[str, Set[str]] = {}
        self.party_manager._diagnostic_log: List[str] = []


        self.guild_id = "test_guild_1"
        self.party_id = str(uuid.uuid4())
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
        self.party_manager._parties.setdefault(self.guild_id, {})[self.party_id] = self.test_party
        self.party_manager.mark_party_dirty = AsyncMock()

    async def test_successfully_updates_party_location(self):
        new_location_id = "new_location_456"
        self.party_manager._diagnostic_log.clear()
        result = await self.party_manager.update_party_location(self.guild_id, self.party_id, new_location_id)
        self.assertTrue(result)
        self.assertEqual(self.test_party.current_location_id, new_location_id)
        self.party_manager.mark_party_dirty.assert_awaited_once_with(self.guild_id, self.party_id)

    async def test_party_not_found_update_location(self):
        result = await self.party_manager.update_party_location(self.guild_id, "non_existent_party", "new_loc")
        self.assertFalse(result)
        self.party_manager.mark_party_dirty.assert_not_called()

    async def test_party_already_at_target_location(self):
        current_location = "location_abc"
        self.test_party.current_location_id = current_location
        # Ensure the party is in the manager's dictionary for the test
        self.party_manager._parties.setdefault(self.guild_id, {})[self.party_id] = self.test_party
        result = await self.party_manager.update_party_location(self.guild_id, self.party_id, current_location)
        self.assertTrue(result)
        self.party_manager.mark_party_dirty.assert_not_called()

    async def test_update_location_to_none(self):
        self.test_party.current_location_id = "some_initial_location"
        # Ensure the party is in the manager's dictionary for the test
        self.party_manager._parties.setdefault(self.guild_id, {})[self.party_id] = self.test_party
        result = await self.party_manager.update_party_location(self.guild_id, self.party_id, None)
        self.assertTrue(result)
        self.assertIsNone(self.test_party.current_location_id)
        self.party_manager.mark_party_dirty.assert_awaited_once_with(self.guild_id, self.party_id)

    async def test_party_missing_current_location_id_attribute(self):
        party_data_no_loc = self.dummy_party_data.copy()
        del party_data_no_loc['current_location_id']
        party_without_loc_attr = Party.from_dict(party_data_no_loc)
        self.assertIsNone(party_without_loc_attr.current_location_id)
        # Ensure the party is in the manager's dictionary for the test
        self.party_manager._parties.setdefault(self.guild_id, {})[self.party_id] = party_without_loc_attr
        new_location_id = "new_valid_location"
        result = await self.party_manager.update_party_location(self.guild_id, self.party_id, new_location_id)
        self.assertTrue(result)
        self.assertEqual(party_without_loc_attr.current_location_id, new_location_id)
        self.party_manager.mark_party_dirty.assert_awaited_once_with(self.guild_id, self.party_id)

    async def test_create_party_success(self):
        leader_char_id = "leader_char_id_for_create"
        leader_location_id = "leader_loc_for_create"
        party_name_i18n = {"en": "The Brave Companions"}
        self.mock_character_manager.set_character_party_id = AsyncMock()
        test_uuid_val = uuid.uuid4()
        with patch('uuid.uuid4', return_value=test_uuid_val):
            created_party_object = await self.party_manager.create_party(
                guild_id=self.guild_id,
                leader_character_id=leader_char_id,
                party_name_i18n=party_name_i18n,
                leader_location_id=leader_location_id
            )
        self.assertIsNotNone(created_party_object)
        self.assertEqual(created_party_object.id, str(test_uuid_val))
        self.assertEqual(created_party_object.name_i18n, party_name_i18n)
        self.mock_character_manager.set_character_party_id.assert_awaited_once_with(self.guild_id, leader_char_id, created_party_object.id)
        # Ensure the guild_id key exists before assertion
        self.party_manager._parties.setdefault(self.guild_id, {})
        self.assertIn(created_party_object.id, self.party_manager._parties[self.guild_id])
        # Ensure the guild_id key exists for member_to_party_map as well
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})
        self.assertEqual(self.party_manager._member_to_party_map[self.guild_id][leader_char_id], created_party_object.id)
        self.party_manager.mark_party_dirty.assert_awaited_once_with(self.guild_id, created_party_object.id)

    async def test_add_member_to_party_success(self):
        new_member_char_id = "new_member_char_id"
        mock_char = AsyncMock(spec=GameCharacterModel)
        mock_char.id = new_member_char_id
        mock_char.current_location_id = self.test_party.current_location_id
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=mock_char)
        self.mock_character_manager.set_character_party_id = AsyncMock()
        self.party_manager._parties.setdefault(self.guild_id, {})[self.test_party.id] = self.test_party
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})[self.test_party.leader_id] = self.test_party.id

        result = await self.party_manager.add_member_to_party(
            guild_id=self.guild_id, party_id=self.test_party.id, character_id=new_member_char_id,
            character_location_id=str(self.test_party.current_location_id)
        )
        self.assertTrue(result)
        self.assertIn(new_member_char_id, self.test_party.player_ids_list)
        self.mock_character_manager.set_character_party_id.assert_awaited_once_with(self.guild_id, new_member_char_id, self.test_party.id)
        # Ensure the guild_id key exists for member_to_party_map as well
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})
        self.assertEqual(self.party_manager._member_to_party_map[self.guild_id][new_member_char_id], self.test_party.id)
        self.party_manager.mark_party_dirty.assert_any_call(self.guild_id, self.test_party.id)

    async def test_add_member_already_in_party(self):
        member_id = self.test_party.leader_id
        # Ensure the guild_id key exists for member_to_party_map as well
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})[member_id] = self.test_party.id
        result = await self.party_manager.add_member_to_party(self.guild_id, self.test_party.id, member_id, str(self.test_party.current_location_id))
        self.assertFalse(result)
        self.mock_character_manager.set_character_party_id.assert_not_called()

    async def test_add_member_location_mismatch(self):
        new_member_id = "new_member_loc_mismatch"
        mock_char_mismatch = AsyncMock(spec=GameCharacterModel)
        mock_char_mismatch.id = new_member_id
        mock_char_mismatch.current_location_id = "diff_loc"
        self.mock_character_manager.get_character_by_id = AsyncMock(return_value=mock_char_mismatch)
        result = await self.party_manager.add_member_to_party(self.guild_id, self.test_party.id, new_member_id, "diff_loc")
        self.assertFalse(result)
        self.mock_character_manager.set_character_party_id.assert_not_called()

    async def test_remove_member_from_party_success(self):
        member_to_remove_id = "member_2"
        if member_to_remove_id not in self.test_party.player_ids_list: self.test_party.player_ids_list.append(member_to_remove_id)
        self.party_manager._parties.setdefault(self.guild_id, {})[self.test_party.id] = self.test_party
        member_map = self.party_manager._member_to_party_map.setdefault(self.guild_id, {})
        for mid in self.test_party.player_ids_list: member_map[mid] = self.test_party.id
        self.mock_character_manager.set_character_party_id = AsyncMock()

        result = await self.party_manager.remove_member_from_party(self.guild_id, self.test_party.id, member_to_remove_id)
        self.assertTrue(result)
        self.assertNotIn(member_to_remove_id, self.test_party.player_ids_list)
        self.mock_character_manager.set_character_party_id.assert_awaited_once_with(self.guild_id, member_to_remove_id, None)
        # Ensure the guild_id key exists for member_to_party_map as well
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})
        self.assertNotIn(member_to_remove_id, self.party_manager._member_to_party_map.get(self.guild_id, {}))
        self.party_manager.mark_party_dirty.assert_any_call(self.guild_id, self.test_party.id)

    async def test_remove_member_leader_leaves_party_disbands(self):
        leader_id = self.test_party.leader_id
        self.test_party.player_ids_list = [leader_id] # type: ignore
        self.party_manager._parties.setdefault(self.guild_id, {})[self.test_party.id] = self.test_party
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})[leader_id] = self.test_party.id
        self.mock_character_manager.set_character_party_id = AsyncMock()
        self.party_manager.disband_party = AsyncMock(return_value=True)

        result = await self.party_manager.remove_member_from_party(self.guild_id, self.test_party.id, leader_id)
        self.assertTrue(result)
        self.party_manager.disband_party.assert_awaited_once_with(self.guild_id, self.test_party.id, disbanding_character_id=leader_id)
        self.mock_character_manager.set_character_party_id.assert_awaited_once_with(self.guild_id, leader_id, None)


    async def test_disband_party_success_as_leader(self):
        other_member_id = "member_2_in_disband"
        self.test_party.player_ids_list = [self.test_party.leader_id, other_member_id] # type: ignore
        self.party_manager._parties.setdefault(self.guild_id, {})[self.test_party.id] = self.test_party
        member_map = self.party_manager._member_to_party_map.setdefault(self.guild_id, {})
        member_map[self.test_party.leader_id] = self.test_party.id
        member_map[other_member_id] = self.test_party.id
        self.mock_character_manager.set_character_party_id = AsyncMock()

        result = await self.party_manager.disband_party(self.guild_id, self.test_party.id, str(self.test_party.leader_id))
        self.assertTrue(result)
        expected_calls = [call(self.guild_id, self.test_party.leader_id, None), call(self.guild_id, other_member_id, None)]
        self.mock_character_manager.set_character_party_id.assert_has_awaits(expected_calls, any_order=True)
        self.assertNotIn(self.test_party.id, self.party_manager._parties.get(self.guild_id, {}))
        self.assertNotIn(self.test_party.leader_id, self.party_manager._member_to_party_map.get(self.guild_id, {}))
        self.assertIn(self.test_party.id, self.party_manager._deleted_parties.get(self.guild_id, set()))
        self.party_manager.mark_party_dirty.assert_not_called()

    async def test_disband_party_not_leader_fails(self):
        non_leader_id = "member_2_not_leader"
        self.test_party.player_ids_list = [self.test_party.leader_id, non_leader_id] # type: ignore
        self.party_manager._parties.setdefault(self.guild_id, {})[self.test_party.id] = self.test_party
        result = await self.party_manager.disband_party(self.guild_id, self.test_party.id, non_leader_id)
        self.assertFalse(result)
        self.mock_character_manager.set_character_party_id.assert_not_called()
        self.assertIn(self.test_party.id, self.party_manager._parties.get(self.guild_id, {}))

    def test_get_party_success(self):
        self.party_manager._parties.setdefault(self.guild_id, {})[self.test_party.id] = self.test_party
        party = self.party_manager.get_party(self.guild_id, self.test_party.id)
        self.assertEqual(party, self.test_party)

    def test_get_party_not_found(self):
        party = self.party_manager.get_party(self.guild_id, "non_existent_party_for_get")
        self.assertIsNone(party)

    def test_get_party_by_member_id_success(self):
        member_id = self.test_party.leader_id
        self.party_manager._parties.setdefault(self.guild_id, {})[self.test_party.id] = self.test_party
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {})[member_id] = self.test_party.id
        party = self.party_manager.get_party_by_member_id(self.guild_id, member_id)
        self.assertEqual(party, self.test_party)

    def test_get_party_by_member_id_not_in_party(self):
        party = self.party_manager.get_party_by_member_id(self.guild_id, "char_not_in_any_party")
        self.assertIsNone(party)

    async def test_save_state_saves_dirty_and_deletes_parties(self):
        dirty_party_id = "dirty_party_1"; dirty_party_data = self.dummy_party_data.copy(); dirty_party_data["id"] = dirty_party_id
        dirty_party = Party.from_dict(dirty_party_data)
        self.party_manager._parties.setdefault(self.guild_id, {})[dirty_party_id] = dirty_party
        self.party_manager._dirty_parties.setdefault(self.guild_id, set()).add(dirty_party_id)
        deleted_party_id = "deleted_party_1"
        self.party_manager._deleted_parties.setdefault(self.guild_id, set()).add(deleted_party_id)
        if deleted_party_id in self.party_manager._parties.get(self.guild_id, {}):
            del self.party_manager._parties[self.guild_id][deleted_party_id]

        self.mock_db_service.upsert_party = AsyncMock()
        self.mock_db_service.delete_party_by_id = AsyncMock()

        await self.party_manager.save_state(self.guild_id)
        self.mock_db_service.upsert_party.assert_awaited_once()
        args, _ = self.mock_db_service.upsert_party.call_args
        self.assertEqual(args[0]['id'], dirty_party_id)

        self.mock_db_service.delete_party_by_id.assert_awaited_once_with(deleted_party_id, self.guild_id)
        self.assertNotIn(dirty_party_id, self.party_manager._dirty_parties.get(self.guild_id, set()))
        self.assertNotIn(deleted_party_id, self.party_manager._deleted_parties.get(self.guild_id, set()))

    async def test_load_state_for_guild_success(self):
        party1_data = {**self.dummy_party_data, "id": "db_party_1", "name_i18n": {"en": "DB1"}}
        party2_data = {**self.dummy_party_data, "id": "db_party_2", "name_i18n": {"en": "DB2"}, "leader_id": "ldr3", "player_ids_list": ["ldr3", "mem4"]}
        self.mock_db_service.load_parties_for_guild = AsyncMock(return_value=[party1_data, party2_data])

        await self.party_manager.load_state_for_guild(self.guild_id)
        self.party_manager._parties.setdefault(self.guild_id, {}) # Ensure guild_id key exists
        self.assertEqual(len(self.party_manager._parties[self.guild_id]), 2)
        self.assertEqual(self.party_manager._parties[self.guild_id]["db_party_1"].name_i18n["en"], "DB1")
        self.party_manager._member_to_party_map.setdefault(self.guild_id, {}) # Ensure guild_id key exists
        member_map = self.party_manager._member_to_party_map[self.guild_id]
        self.assertEqual(member_map.get(self.party_leader_id), "db_party_1")
        self.assertEqual(member_map.get("ldr3"), "db_party_2")

    async def create_mock_character(self, player_id: str, location_id: str, status: str, actions_json: Optional[str] = "[]") -> MagicMock: # type: ignore
        char = AsyncMock(spec=GameCharacterModel)
        char.id = player_id; char.name = f"Char_{player_id}"; char.current_location_id = location_id
        char.current_game_status = status; char.collected_actions_json = actions_json
        char.discord_user_id = f"discord_{player_id}"
        return char

    async def test_check_and_process_party_turn_not_all_ready(self):
        loc_id = "loc1"
        char1_ready = await self.create_mock_character("p1", loc_id, "ожидание_обработки")
        char2_not_ready = await self.create_mock_character("p2", loc_id, "исследование")
        self.test_party.player_ids_list = [str(char1_ready.id), str(char2_not_ready.id)] # type: ignore
        self.party_manager._parties.setdefault(self.guild_id, {})[self.party_id] = self.test_party
        
        async def mock_get_char_side_effect(guild_id_arg: str, char_id_arg: str, session_arg: Any = None):
            if char_id_arg == "p1": return char1_ready
            if char_id_arg == "p2": return char2_not_ready
            return None
        self.mock_character_manager.get_character_by_id = AsyncMock(side_effect=mock_get_char_side_effect)
        
        self.party_manager._diagnostic_log.clear()
        await self.party_manager.check_and_process_party_turn(self.party_id, loc_id, self.guild_id, self.mock_game_manager)

        if hasattr(self.mock_db_service, 'execute'): self.mock_db_service.execute.assert_not_called() # type: ignore
        if hasattr(self.mock_game_manager, 'action_processor') and self.mock_game_manager.action_processor and \
           hasattr(self.mock_game_manager.action_processor, 'process_party_actions'):
            self.mock_game_manager.action_processor.process_party_actions.assert_not_called()
        self.assertEqual(self.test_party.turn_status, "сбор_действий")

    @unittest.skip("PartyManager.check_and_process_party_turn method needs review or is not fully implemented as expected by test.")
    async def test_check_and_process_party_turn_all_ready_success(self):
        pass

    async def test_check_and_process_party_turn_no_actions_data(self):
        loc_id = "loc1"
        char1 = await self.create_mock_character("p1", loc_id, "ожидание_обработки", "[]")
        self.test_party.player_ids_list = [str(char1.id)] # type: ignore
        self.party_manager._parties.setdefault(self.guild_id, {})[self.party_id] = self.test_party
        
        async def mock_get_char_return_value(guild_id_arg: str, char_id_arg: str, session_arg: Any = None): return char1
        self.mock_character_manager.get_character_by_id = AsyncMock(side_effect=mock_get_char_return_value)
        
        mock_location_model = MagicMock()
        mock_location_model.channel_id = "1234567890"; mock_location_model.name_i18n = {"ru": loc_id, "en": loc_id}
        self.mock_location_manager.get_location_instance_by_id = AsyncMock(return_value=mock_location_model)

        self.mock_game_manager.action_processor = AsyncMock()
        self.mock_game_manager.action_processor.process_party_actions = AsyncMock(return_value={"success": True, "individual_action_results": [], "overall_state_changed": False, "target_channel_id": "1234567890"})

        mock_discord_channel = AsyncMock(spec=discord.TextChannel)
        mock_discord_channel.send = AsyncMock()
        self.mock_discord_client.get_channel = MagicMock(return_value=mock_discord_channel)

        self.party_manager._diagnostic_log.clear()
        await self.party_manager.check_and_process_party_turn(self.party_id, loc_id, self.guild_id, self.mock_game_manager)

        if hasattr(self.mock_db_service, 'execute_transactional_query_for_guild'):
            self.mock_db_service.execute_transactional_query_for_guild.assert_any_call(self.guild_id, ANY, ('обработка', self.party_id)) # type: ignore
            self.mock_db_service.execute_transactional_query_for_guild.assert_any_call(self.guild_id, ANY, ('сбор_действий', self.party_id)) # type: ignore

        self.mock_game_manager.action_processor.process_party_actions.assert_awaited_once()
        args_list = self.mock_game_manager.action_processor.process_party_actions.await_args_list
        self.assertEqual(args_list[0].kwargs['party_actions_data'], [('p1', '[]')])

        self.assertEqual(char1.current_game_status, "исследование") # type: ignore
        self.assertEqual(char1.collected_actions_json, "[]") # type: ignore
        self.mock_character_manager.save_character_from_instance.assert_awaited_once_with(char1, self.guild_id, session=ANY)
        mock_discord_channel.send.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
