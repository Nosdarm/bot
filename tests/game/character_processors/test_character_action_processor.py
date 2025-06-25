import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import uuid
import json
from typing import Dict, Any, List, Optional

from bot.game.character_processors.character_action_processor import CharacterActionProcessor
from bot.game.models.character import Character as CharacterModel
from bot.game.models.combat import Combat as CombatModel # For mocking combat instances
from bot.ai.rules_schema import CoreGameRulesConfig, EquipmentSlotDefinition, StatusEffectDefinition, ItemEffectDefinition # ItemDefinition removed
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.inventory_manager import InventoryManager
from bot.game.managers.equipment_manager import EquipmentManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.dialogue_manager import DialogueManager
from bot.game.managers.event_manager import EventManager
from bot.game.rules.rule_engine import RuleEngine
from bot.services.db_service import DBService
from bot.services.openai_service import OpenAIService
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.managers.party_manager import PartyManager
from bot.game.event_processors.event_stage_processor import EventStageProcessor
from bot.game.event_processors.event_action_processor import EventActionProcessor


class MockCharacter(CharacterModel):
    def __init__(self, id: str, guild_id: str, name: str = "Test Character",
                 location_id: str = "loc_test_1", inventory: Optional[List[Dict[str, Any]]] = None,
                 equipment: Optional[Dict[str, Any]] = None,
                 current_health: int = 100, max_health: int = 100,
                 stats: Optional[Dict[str, Any]] = None,
                 discord_channel_id: Optional[int] = 12345,
                 current_action: Optional[Dict[str, Any]] = None,
                 action_queue: Optional[List[Dict[str,Any]]] = None):
        # Ensure stats_json, inventory_json, equipment_json are strings for the model
        stats_json_str = json.dumps(stats or {})
        inventory_json_str = json.dumps(inventory or [])
        equipment_json_str = json.dumps(equipment or {})

        super().__init__(id=id, guild_id=guild_id, name=name, current_health=current_health, max_health=max_health,
                         stats_json=stats_json_str, inventory_json=inventory_json_str,
                         equipment_json=equipment_json_str,
                         location_id=location_id, discord_channel_id=discord_channel_id)
        # These are for easier access in tests if needed, CharacterModel uses properties
        self._inventory_list = inventory if inventory is not None else []
        self._equipment_dict = equipment if equipment is not None else {}

        self.current_action = current_action
        self.action_queue = action_queue if action_queue is not None else []

    # Override properties if direct list/dict access is preferred in tests over JSON manipulation
    @property
    def inventory(self) -> List[Dict[str, Any]]:
        return self._inventory_list

    @inventory.setter
    def inventory(self, value: List[Dict[str, Any]]):
        self._inventory_list = value
        self.inventory_json = json.dumps(value)

    @property
    def equipment(self) -> Dict[str, Any]: # This should be Dict[str, Dict[str,Any]] if items are dicts
        return self._equipment_dict

    @equipment.setter
    def equipment(self, value: Dict[str, Any]):
        self._equipment_dict = value
        self.equipment_json = json.dumps(value)


class TestCharacterActionProcessor(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_character_manager = AsyncMock(spec=CharacterManager)
        self.mock_item_manager = AsyncMock(spec=ItemManager)
        self.mock_inventory_manager = AsyncMock(spec=InventoryManager)
        self.mock_equipment_manager = AsyncMock(spec=EquipmentManager)
        self.mock_location_manager = AsyncMock(spec=LocationManager)
        self.mock_npc_manager = AsyncMock(spec=NpcManager)
        self.mock_combat_manager = AsyncMock(spec=CombatManager)
        self.mock_status_manager = AsyncMock(spec=StatusManager)
        self.mock_dialogue_manager = AsyncMock(spec=DialogueManager)
        self.mock_event_manager = AsyncMock(spec=EventManager)
        self.mock_rule_engine = AsyncMock(spec=RuleEngine)
        self.mock_openai_service = AsyncMock(spec=OpenAIService)
        self.mock_game_log_manager = AsyncMock(spec=GameLogManager)
        self.mock_party_manager = AsyncMock(spec=PartyManager)
        self.mock_event_stage_processor = AsyncMock(spec=EventStageProcessor)
        self.mock_event_action_processor = AsyncMock(spec=EventActionProcessor)
        self.mock_db_service = AsyncMock(spec=DBService) # Added mock for DBService

        async def async_send_callback(message: str): pass
        self.mock_send_callback = AsyncMock(side_effect=async_send_callback)
        self.mock_send_callback_factory = MagicMock(return_value=self.mock_send_callback)

        self.rules_config = CoreGameRulesConfig(
            equipment_slots={}, status_effects={}, # ItemDefinition removed
            item_effects={}, action_conflicts=[]
        )
        self.mock_rule_engine.rules_config_data = self.rules_config # CAP might get it from here

        self.processor = CharacterActionProcessor(
            character_manager=self.mock_character_manager,
            send_callback_factory=self.mock_send_callback_factory,
            db_service=self.mock_db_service, # Added db_service
            item_manager=self.mock_item_manager,
            inventory_manager=self.mock_inventory_manager, # Added
            equipment_manager=self.mock_equipment_manager,
            location_manager=self.mock_location_manager,
            npc_manager=self.mock_npc_manager,
            combat_manager=self.mock_combat_manager,
            status_manager=self.mock_status_manager,
            party_manager=self.mock_party_manager,
            event_manager=self.mock_event_manager,
            rule_engine=self.mock_rule_engine,
            openai_service=self.mock_openai_service,
            game_log_manager=self.mock_game_log_manager,
            event_stage_processor=self.mock_event_stage_processor,
            event_action_processor=self.mock_event_action_processor
            # location_interaction_service is optional and defaults to None
        )

    def _create_mock_character(self, char_id: str, guild_id: str, name: str = "Test Character",
                               location_id: str = "loc_test_1",
                               inventory: Optional[List[Dict[str, Any]]] = None,
                               equipment: Optional[Dict[str, Any]] = None,
                               current_health: int = 100) -> MockCharacter:
        return MockCharacter(
            id=char_id, guild_id=guild_id, name=name, location_id=location_id,
            inventory=inventory, equipment=equipment, current_health=current_health
        )

    # --- Test handle_explore_action / handle_look_action ---
    async def test_handle_explore_action_general_look(self):
        guild_id, char_id = "gex1", "cex1"
        mock_char = self._create_mock_character(char_id, guild_id, location_id="loc1")
        action_params_from_nlu = {"entities": []}
        mock_loc_inst = MagicMock(name="Tavern", display_description="Cozy.", exits={"north": "loc2"})
        self.mock_location_manager.get_location_instance.return_value = mock_loc_inst
        self.mock_character_manager.get_characters_in_location.return_value = []
        self.mock_npc_manager.get_npcs_in_location.return_value = []
        self.mock_item_manager.get_items_in_location.return_value = []
        self.mock_event_manager.get_active_events.return_value = []
        self.mock_location_manager.get_location_static.return_value = {"name": "North Room"}
        result = await self.processor.handle_explore_action(mock_char, guild_id, action_params_from_nlu, {})
        self.assertTrue(result["success"])
        self.assertIn("Tavern", result["message"])
        self.mock_openai_service.generate_text.assert_called_once()

    async def test_handle_explore_action_look_at_npc(self):
        guild_id, char_id, npc_id = "gex2", "cex2", "npc_barman"
        mock_char = self._create_mock_character(char_id, guild_id, location_id="tavern")
        action_params_from_nlu = {"entities": [{"type": "npc", "id": npc_id, "value": "barman"}]}
        mock_npc = MagicMock(name="Bob", description="Friendly.")
        self.mock_npc_manager.get_npc.return_value = mock_npc
        result = await self.processor.handle_explore_action(mock_char, guild_id, action_params_from_nlu, {})
        self.assertTrue(result["success"])
        self.assertIn("Bob", result["message"])
        self.mock_npc_manager.get_npc.assert_called_once_with(guild_id, npc_id)

    # --- Equip/Unequip Tests (already good) ---

    # --- Drop Item Tests (already good) ---

    # --- Attack Action Tests ---
    async def _setup_attack_test(self, attacker_id: str, target_id: str, guild_id: str, target_type: str = "npc", target_health: int = 50):
        mock_attacker = self._create_mock_character(attacker_id, guild_id, name=f"Attacker_{attacker_id}", location_id="arena")
        action_data = {"intent": "ATTACK", "entities": [{"type": target_type, "id": target_id, "value": "target"}]}

        if target_type == "npc":
            mock_target = self._create_mock_character(target_id, guild_id, name=f"Target_{target_id}", current_health=target_health) # Using MockCharacter for NPC for simplicity
            self.mock_npc_manager.get_npc.return_value = mock_target
        else: # character
            mock_target = self._create_mock_character(target_id, guild_id, name=f"Target_{target_id}", current_health=target_health)
            self.mock_character_manager.get_character.return_value = mock_target # Assume this if target is char

        # Default successful attack roll and damage
        self.mock_rule_engine.resolve_attack_roll.return_value = {"success": True, "total_roll_value": 18, "dc_value": 10, "message_parts": ["Roll: 18 vs 10."]}
        self.mock_rule_engine.calculate_damage.return_value = {"total_damage": 7, "damage_type": "slashing", "message_parts": ["Damage: 7."]}
        self.mock_combat_manager.apply_damage_to_participant.return_value = {"message": "Target took 7 damage."}

        return mock_attacker, action_data, mock_target

    async def test_handle_attack_action_success_starts_combat(self):
        guild_id, attacker_id, target_id = "g_atk_start", "atk_s1", "npc_s1"
        mock_attacker, action_data, _ = await self._setup_attack_test(attacker_id, target_id, guild_id)
        self.mock_combat_manager.is_character_in_combat.return_value = None # Both not in combat
        mock_combat_instance = MagicMock(spec=CombatModel, id="new_combat_1")
        self.mock_combat_manager.start_combat.return_value = mock_combat_instance

        result = await self.processor.handle_attack_action(mock_attacker, guild_id, action_data, self.rules_config)

        self.assertTrue(result["success"])
        self.assertTrue(result["state_changed"])
        self.mock_combat_manager.start_combat.assert_called_once()
        self.mock_combat_manager.apply_damage_to_participant.assert_called_once()

    async def test_handle_attack_action_attacker_joins_target_combat(self):
        guild_id, attacker_id, target_id = "g_atk_join", "atk_j1", "npc_j1"
        existing_combat_id = "combat_existing"
        mock_attacker, action_data, mock_target = await self._setup_attack_test(attacker_id, target_id, guild_id)

        # Attacker not in combat, target is in combat
        self.mock_combat_manager.is_character_in_combat.side_effect = [None, existing_combat_id]
        mock_existing_combat = MagicMock(spec=CombatModel, id=existing_combat_id, participants=[MagicMock(entity_id=target_id)])
        self.mock_combat_manager.get_combat.return_value = mock_existing_combat
        self.mock_combat_manager.add_participant_to_combat.return_value = True # Assume success

        result = await self.processor.handle_attack_action(mock_attacker, guild_id, action_data, self.rules_config)

        self.assertTrue(result["success"])
        self.mock_combat_manager.add_participant_to_combat.assert_called_once_with(guild_id, existing_combat_id, attacker_id, "Character")
        self.mock_combat_manager.apply_damage_to_participant.assert_called_once()

    async def test_handle_attack_action_target_joins_attacker_combat(self):
        guild_id, attacker_id, target_id = "g_atk_tjoin", "atk_tj1", "npc_tj1"
        existing_combat_id = "combat_attacker_is_in"
        mock_attacker, action_data, mock_target = await self._setup_attack_test(attacker_id, target_id, guild_id)

        # Attacker in combat, target is not
        self.mock_combat_manager.is_character_in_combat.side_effect = [existing_combat_id, None]
        mock_attacker_combat = MagicMock(spec=CombatModel, id=existing_combat_id, participants=[MagicMock(entity_id=attacker_id)])
        self.mock_combat_manager.get_combat.return_value = mock_attacker_combat
        self.mock_combat_manager.add_participant_to_combat.return_value = True

        result = await self.processor.handle_attack_action(mock_attacker, guild_id, action_data, self.rules_config)

        self.assertTrue(result["success"])
        self.mock_combat_manager.add_participant_to_combat.assert_called_once_with(guild_id, existing_combat_id, target_id, "npc")
        self.mock_combat_manager.apply_damage_to_participant.assert_called_once()

    async def test_handle_attack_action_already_in_same_combat(self):
        guild_id, attacker_id, target_id = "g_atk_same", "atk_same1", "npc_same1"
        existing_combat_id = "combat_shared"
        mock_attacker, action_data, mock_target = await self._setup_attack_test(attacker_id, target_id, guild_id)

        self.mock_combat_manager.is_character_in_combat.return_value = existing_combat_id # Both in same combat
        mock_shared_combat = MagicMock(spec=CombatModel, id=existing_combat_id, participants=[MagicMock(entity_id=attacker_id), MagicMock(entity_id=target_id)])
        self.mock_combat_manager.get_combat.return_value = mock_shared_combat

        result = await self.processor.handle_attack_action(mock_attacker, guild_id, action_data, self.rules_config)

        self.assertTrue(result["success"])
        self.mock_combat_manager.start_combat.assert_not_called()
        self.mock_combat_manager.add_participant_to_combat.assert_not_called()
        self.mock_combat_manager.apply_damage_to_participant.assert_called_once()

    async def test_handle_attack_action_attack_misses(self):
        guild_id, attacker_id, target_id = "g_atk_miss", "atk_miss1", "npc_miss1"
        mock_attacker, action_data, _ = await self._setup_attack_test(attacker_id, target_id, guild_id)
        self.mock_combat_manager.is_character_in_combat.return_value = None # Start new combat
        mock_combat_instance = MagicMock(spec=CombatModel, id="new_combat_miss")
        self.mock_combat_manager.start_combat.return_value = mock_combat_instance

        self.mock_rule_engine.resolve_attack_roll.return_value = {"success": False, "total_roll_value": 5, "dc_value": 10, "message_parts": ["Roll: 5 vs 10."]} # Attack fails

        result = await self.processor.handle_attack_action(mock_attacker, guild_id, action_data, self.rules_config)

        self.assertTrue(result["success"]) # Action itself is successful (attempt was made)
        self.assertIn("Промах!", result["message"])
        self.assertTrue(result["state_changed"])
        self.mock_rule_engine.calculate_damage.assert_not_called()
        self.mock_combat_manager.apply_damage_to_participant.assert_not_called()
        self.mock_combat_manager.record_attack.assert_called_once() # Record the miss

    # --- Skill Use Tests (already good) ---

    # --- Pickup Item Tests (already good) ---

    # --- Move Action Tests ---
    async def _setup_move_test(self, guild_id: str, char_id: str, current_loc_id: str,
                               target_loc_id: str, in_party: bool = False, party_id_val: Optional[str] = None):
        mock_character = self._create_mock_character(char_id, guild_id, location_id=current_loc_id)
        if in_party:
            mock_character.party_id = party_id_val

        self.mock_character_manager.get_character.return_value = mock_character # Used by some internal calls if any

        mock_current_loc = MagicMock(id=current_loc_id, name_i18n={"en": "Current Room"})
        mock_target_loc = MagicMock(id=target_loc_id, name_i18n={"en": "Target Room"})

        # LocationManager.get_location_instance used by CAP.handle_move_action
        def get_loc_instance_side_effect(gid, loc_id_to_get, session=None):
            if gid == guild_id:
                if loc_id_to_get == current_loc_id: return mock_current_loc
                if loc_id_to_get == target_loc_id: return mock_target_loc
            return None
        self.mock_location_manager.get_location_instance = MagicMock(side_effect=get_loc_instance_side_effect)

        # LocationManager.can_move_between called by CAP.handle_move_action
        self.mock_location_manager.can_move_between = AsyncMock(return_value=True) # Default to can move

        # CharacterManager.update_character_location called by CAP.handle_move_action
        self.mock_character_manager.update_character_location = AsyncMock(return_value=True)

        # PartyManager mocks
        if in_party:
            mock_party_obj = MagicMock(id=party_id_val, current_location_id=current_loc_id)
            self.mock_party_manager.get_party_by_member_id.return_value = mock_party_obj
            self.mock_party_manager.update_party_location = AsyncMock(return_value=True)
        else:
            self.mock_party_manager.get_party_by_member_id.return_value = None

        # RuleEngine for party movement rules
        self.mock_rule_engine.get_rule = MagicMock(return_value=True) # Default: party movement allowed

        # GameLogManager
        self.mock_game_log_manager.log_event = AsyncMock()

        # LocationManager event triggers
        self.mock_location_manager.handle_entity_departure = AsyncMock()
        self.mock_location_manager.handle_entity_arrival = AsyncMock()

        destination_entity_nlu = {"type": "location_id", "id": target_loc_id, "value": "Target Room"}
        return mock_character, destination_entity_nlu

    async def test_handle_move_action_success_solo_player(self):
        guild_id, char_id, current_loc, target_loc = "g_move_solo", "c_move_solo", "loc_start_solo", "loc_end_solo"
        mock_char, dest_nlu = await self._setup_move_test(guild_id, char_id, current_loc, target_loc, in_party=False)

        result = await self.processor.handle_move_action(mock_char, dest_nlu, guild_id)

        self.assertTrue(result["success"])
        self.assertIn("успешно переместились", result["message"])
        self.assertTrue(result["state_changed"])

        self.mock_location_manager.can_move_between.assert_awaited_once_with(guild_id, current_loc, target_loc)
        self.mock_character_manager.update_character_location.assert_awaited_once_with(char_id, target_loc, guild_id)
        self.mock_game_log_manager.log_event.assert_awaited_once()
        log_args = self.mock_game_log_manager.log_event.call_args[1] # kwargs
        self.assertEqual(log_args['guild_id'], guild_id)
        self.assertEqual(log_args['event_type'], "PLAYER_MOVE")
        self.assertEqual(log_args['details']['character_id'], char_id)
        self.assertEqual(log_args['details']['from_location_id'], current_loc)
        self.assertEqual(log_args['details']['to_location_id'], target_loc)

        self.mock_location_manager.handle_entity_departure.assert_awaited_once_with(current_loc, char_id, "Character", guild_id=guild_id)
        self.mock_location_manager.handle_entity_arrival.assert_awaited_once_with(target_loc, char_id, "Character", guild_id=guild_id)
        self.mock_party_manager.update_party_location.assert_not_called()


    async def test_handle_move_action_no_connection(self):
        guild_id, char_id, current_loc, target_loc = "g_move_nocon", "c_move_nocon", "loc_start_nocon", "loc_end_nocon"
        mock_char, dest_nlu = await self._setup_move_test(guild_id, char_id, current_loc, target_loc)
        self.mock_location_manager.can_move_between = AsyncMock(return_value=False) # No connection

        result = await self.processor.handle_move_action(mock_char, dest_nlu, guild_id)

        self.assertFalse(result["success"])
        self.assertIn("нельзя пройти", result["message"])
        self.mock_character_manager.update_character_location.assert_not_called()

    async def test_handle_move_action_party_success(self):
        guild_id, char_id, current_loc, target_loc = "g_move_party", "c_move_party", "loc_start_party", "loc_end_party"
        party_id = "party_move_1"
        mock_char, dest_nlu = await self._setup_move_test(guild_id, char_id, current_loc, target_loc, in_party=True, party_id_val=party_id)

        result = await self.processor.handle_move_action(mock_char, dest_nlu, guild_id)

        self.assertTrue(result["success"])
        self.mock_character_manager.update_character_location.assert_awaited_once_with(char_id, target_loc, guild_id)
        self.mock_party_manager.update_party_location.assert_awaited_once_with(guild_id, party_id, target_loc)
        self.mock_location_manager.handle_entity_departure.assert_awaited_once_with(current_loc, party_id, "Party", guild_id=guild_id) # Party departs
        self.mock_location_manager.handle_entity_arrival.assert_awaited_once_with(target_loc, party_id, "Party", guild_id=guild_id)   # Party arrives

    async def test_handle_move_action_party_rule_disallows(self):
        guild_id, char_id, current_loc, target_loc = "g_move_party_rule", "c_move_party_rule", "loc_start_party_rule", "loc_end_party_rule"
        party_id = "party_move_rule_1"
        mock_char, dest_nlu = await self._setup_move_test(guild_id, char_id, current_loc, target_loc, in_party=True, party_id_val=party_id)

        # Simulate RuleEngine disallowing party movement
        self.mock_rule_engine.get_rule = MagicMock(return_value=False) # Example: "party_can_move" rule returns False

        result = await self.processor.handle_move_action(mock_char, dest_nlu, guild_id)

        self.assertFalse(result["success"])
        self.assertIn("партия не может сейчас двигаться", result["message"].lower())
        self.mock_character_manager.update_character_location.assert_not_called()
        self.mock_party_manager.update_party_location.assert_not_called()

if __name__ == '__main__':
    unittest.main()
