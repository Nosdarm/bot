import unittest
from unittest.mock import MagicMock, patch, AsyncMock, ANY
import time
import uuid
import json # For serializing collected_actions_json
from typing import Optional, Dict, Any, List # Ensure these are imported for type hints

# Main classes to test and their dependencies
from bot.game.turn_processing_service import TurnProcessingService
from bot.game.action_scheduler import GuildActionScheduler
from bot.game.ai.npc_action_planner import NPCActionPlanner
from bot.game.npc_action_processor import NPCActionProcessor
from bot.game.character_processors.character_action_processor import CharacterActionProcessor # Player actions

# Models
from bot.game.models.action_request import ActionRequest
# Attempt to import real models, with fallback
try:
    from bot.game.models.character import Character
    from bot.game.models.npc import NPC
except ImportError:
    Character = Any
    NPC = Any


# Managers (mocked)
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.game_manager import GameManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.item_manager import ItemManager
from bot.services.db_service import DBService
from bot.game.managers.dialogue_manager import DialogueManager
from bot.game.managers.inventory_manager import InventoryManager
from bot.game.managers.equipment_manager import EquipmentManager
from bot.game.services.location_interaction_service import LocationInteractionService


# --- Helper: Minimal Pydantic Models for testing if real ones are too complex ---
_CharacterModel = Character
_NPCModel = NPC

# Check if the imported models are placeholders (Any) or if they are actual classes
# that might be too complex for easy instantiation in tests.
# This check is a bit rudimentary; a more robust way might involve checking base classes or specific attributes.
if not hasattr(Character, 'model_fields') or not hasattr(NPC, 'model_fields'): # model_fields is Pydantic v2
    if not hasattr(Character, '__fields__') or not hasattr(NPC, '__fields__'): # __fields__ is Pydantic v1
        # If neither Pydantic v1 nor v2 attributes are found, assume they might be 'Any' or non-Pydantic.
        # So, use the minimal fallback models.
        # print("Using fallback MinimalCharacter and MinimalNPC for testing.") # For debugging test setup
        from pydantic import BaseModel, Field as PydanticField
        from typing import Dict as PydanticDict, List as PydanticList, Optional as PydanticOptional, Any as PydanticAny

        class MinimalCharacter(BaseModel):
            id: str
            name_i18n: PydanticDict[str, str] = PydanticField(default_factory=dict)
            guild_id: str
            template_id: str
            discord_user_id: PydanticOptional[str] = None
            current_location_id: PydanticOptional[str] = None
            collected_actions_json: PydanticOptional[str] = None
            current_game_status: str = "idle"

            @property
            def name(self): return self.name_i18n.get("en", self.id)

        class MinimalNPC(BaseModel):
            id: str
            name_i18n: PydanticDict[str, str] = PydanticField(default_factory=dict)
            guild_id: str
            template_id: str
            current_location_id: PydanticOptional[str] = None
            available_actions: PydanticList[PydanticDict[str, PydanticAny]] = PydanticField(default_factory=list)
            current_combat_id: PydanticOptional[str] = None

            @property
            def name(self): return self.name_i18n.get("en", self.id)

        _CharacterModel = MinimalCharacter # type: ignore
        _NPCModel = MinimalNPC             # type: ignore

# --- End Helper Models ---


class TestTurnProcessingIntegration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.guild_id = "test_guild_integration"

        self.action_scheduler = GuildActionScheduler()

        self.mock_char_mgr = AsyncMock(spec=CharacterManager)
        self.mock_npc_mgr = AsyncMock(spec=NpcManager)
        self.mock_game_mgr = AsyncMock(spec=GameManager)
        self.mock_log_mgr = AsyncMock(spec=GameLogManager)
        self.mock_rule_engine = AsyncMock(spec=RuleEngine)
        self.mock_location_mgr = AsyncMock(spec=LocationManager)
        self.mock_combat_mgr = AsyncMock(spec=CombatManager)
        self.mock_item_mgr = AsyncMock(spec=ItemManager)
        self.mock_db_service = AsyncMock(spec=DBService)
        self.mock_dialogue_mgr = AsyncMock(spec=DialogueManager)
        self.mock_inventory_mgr = AsyncMock(spec=InventoryManager)
        self.mock_equipment_mgr = AsyncMock(spec=EquipmentManager)
        self.mock_loc_interaction_service = AsyncMock(spec=LocationInteractionService)
        self.mock_send_callback_factory = MagicMock() # CAP needs this, though not used in these tests

        self.player_action_processor = CharacterActionProcessor(
            character_manager=self.mock_char_mgr,
            send_callback_factory=self.mock_send_callback_factory, # Added
            db_service=self.mock_db_service,
            item_manager=self.mock_item_mgr,
            location_manager=self.mock_location_mgr,
            dialogue_manager=self.mock_dialogue_mgr,
            rule_engine=self.mock_rule_engine,
            combat_manager=self.mock_combat_mgr,
            status_manager=AsyncMock(), # Assuming StatusManager might be needed
            party_manager=AsyncMock(),   # Assuming PartyManager might be needed
            npc_manager=self.mock_npc_mgr,
            event_stage_processor=AsyncMock(),
            event_action_processor=AsyncMock(),
            game_log_manager=self.mock_log_mgr,
            openai_service=AsyncMock(),
            event_manager=AsyncMock(),
            equipment_manager=self.mock_equipment_mgr,
            inventory_manager=self.mock_inventory_mgr,
            location_interaction_service=self.mock_loc_interaction_service
        )

        self.npc_action_planner = NPCActionPlanner(context_providing_services={})

        npc_processor_managers = {
            'game_log_manager': self.mock_log_mgr,
            'location_manager': self.mock_location_mgr,
            'combat_manager': self.mock_combat_mgr,
            'character_manager': self.mock_char_mgr,
            'npc_manager': self.mock_npc_mgr
        }
        self.npc_action_processor = NPCActionProcessor(managers=npc_processor_managers)

        self.turn_service = TurnProcessingService(
            character_manager=self.mock_char_mgr,
            rule_engine=self.mock_rule_engine,
            game_manager=self.mock_game_mgr,
            game_log_manager=self.mock_log_mgr,
            character_action_processor=self.player_action_processor,
            combat_manager=self.mock_combat_mgr,
            location_manager=self.mock_location_mgr,
            location_interaction_service=self.mock_loc_interaction_service,
            dialogue_manager=self.mock_dialogue_mgr,
            inventory_manager=self.mock_inventory_mgr,
            equipment_manager=self.mock_equipment_mgr,
            item_manager=self.mock_item_mgr,
            settings={},
            action_scheduler=self.action_scheduler,
            npc_action_planner=self.npc_action_planner,
            npc_action_processor=self.npc_action_processor,
            npc_manager=self.mock_npc_mgr
        )

        self.mock_rule_engine.rules_config_data = {}

    async def test_player_submits_action_it_gets_scheduled_and_processed(self):
        player_id = "player1_integration"
        player_char = _CharacterModel(
            id=player_id, name_i18n={"en": "Test Player"}, guild_id=self.guild_id, template_id="p_template", # Ensure template_id is provided
            collected_actions_json=json.dumps([
                {"intent_type": "LOOK", "action_id": "look1"}
            ])
        )
        self.mock_char_mgr.get_all_characters.return_value = [player_char]
        self.mock_char_mgr.get_character.return_value = player_char

        async def mock_player_action_processing(action_request: ActionRequest, character: _CharacterModel, context: Dict[str, Any]): # Added type hints
            if action_request.action_type == "PLAYER_LOOK":
                return {"success": True, "message": "You look around.", "state_changed": False, "action_id": action_request.action_id, "actor_id": character.id}
            return {"success": False, "message": "Unknown player action.", "state_changed": False, "action_id": action_request.action_id, "actor_id": character.id}

        self.player_action_processor.process_action_from_request = AsyncMock(side_effect=mock_player_action_processing)

        submission_result = await self.turn_service.process_player_turns(self.guild_id)

        # Ensure submission_result is a dict before accessing keys
        self.assertIsInstance(submission_result, dict, "submission_result should be a dictionary")
        self.assertEqual(submission_result.get('status'), "player_actions_submitted")
        self.assertEqual(submission_result.get('count'), 1)


        queued_actions = self.action_scheduler.get_all_actions_for_guild(self.guild_id)
        self.assertEqual(len(queued_actions), 1)
        self.assertEqual(queued_actions[0].actor_id, player_id)
        self.assertEqual(queued_actions[0].action_type, "PLAYER_LOOK")
        self.assertEqual(queued_actions[0].status, "pending")

        self.mock_npc_mgr.get_all_npcs.return_value = []

        guild_turn_context = {'rules_config': {}, 'guild_id': self.guild_id, 'managers': {}} # Ensure managers is a dict
        processing_result = await self.turn_service.process_guild_turn(self.guild_id, guild_turn_context)

        self.assertIsInstance(processing_result, dict, "processing_result should be a dictionary")
        self.assertEqual(processing_result.get('player_actions_processed'), 1)
        self.assertEqual(processing_result.get('npc_actions_planned'), 0)
        self.assertEqual(processing_result.get('npc_actions_processed'), 0)

        self.player_action_processor.process_action_from_request.assert_called_once()
        call_args = self.player_action_processor.process_action_from_request.call_args[0]
        self.assertEqual(call_args[0].action_id, "look1")
        self.assertEqual(call_args[1].id, player_id)

        final_action_status = self.action_scheduler.get_action(self.guild_id, "look1")
        self.assertIsNotNone(final_action_status)
        self.assertEqual(getattr(final_action_status, 'status', None), "completed") # Safe access
        final_action_result = getattr(final_action_status, 'result', None)
        self.assertIsInstance(final_action_result, dict, "final_action_status.result should be a dictionary")
        self.assertTrue(final_action_result.get('success'))
        self.assertIn("You look around.", final_action_result.get('message', ""))


    async def test_npc_plans_and_executes_action(self):
        npc_id = "npc1_integration"
        npc_actor = _NPCModel(
            id=npc_id, name_i18n={"en":"Test NPC"}, guild_id=self.guild_id, template_id="n_template", # Ensure template_id
            available_actions=[{"action_type": "patrol", "name": "Patrol Duty"}]
        )
        self.mock_npc_mgr.get_all_npcs.return_value = [npc_actor]
        self.mock_npc_mgr.get_npc.return_value = npc_actor

        self.mock_char_mgr.get_all_characters.return_value = []
        await self.turn_service.process_player_turns(self.guild_id)


        async def mock_npc_plan_action(npc: _NPCModel, guild_id_param: str, context_param: Dict[str, Any]): # Added type hints
            if npc.id == npc_id:
                return ActionRequest(
                    guild_id=guild_id_param, actor_id=npc.id, action_type="NPC_PATROL",
                    action_data={"destination": "point_alpha"}, priority=50, execute_at=time.time()
                )
            return None
        self.npc_action_planner.plan_action = AsyncMock(side_effect=mock_npc_plan_action)

        async def mock_npc_action_processing(action_request: ActionRequest, npc: _NPCModel): # Added type hints
            dest = action_request.action_data.get("destination") if isinstance(action_request.action_data, dict) else "unknown_dest"
            npc_name = getattr(npc, 'name', 'Unknown NPC') # Safe access for name
            if action_request.action_type == "NPC_PATROL":
                return {"success": True, "message": f"{npc_name} patrols to {dest}.", "state_changed": True, "action_id": action_request.action_id, "actor_id": npc.id}
            return {"success": False, "message": "Unknown NPC action.", "state_changed": False, "action_id": action_request.action_id, "actor_id": npc.id}
        self.npc_action_processor.process_action = AsyncMock(side_effect=mock_npc_action_processing)

        guild_turn_context = {'rules_config': {}, 'guild_id': self.guild_id, 'managers': {}} # Ensure managers is a dict
        processing_result = await self.turn_service.process_guild_turn(self.guild_id, guild_turn_context)

        self.assertIsInstance(processing_result, dict, "processing_result should be a dictionary")
        self.assertEqual(processing_result.get('npc_actions_planned'), 1)
        self.assertEqual(processing_result.get('npc_actions_processed'), 1)


        self.npc_action_planner.plan_action.assert_called_once_with(npc_actor, self.guild_id, ANY)
        self.npc_action_processor.process_action.assert_called_once()
        call_args_proc = self.npc_action_processor.process_action.call_args[0]
        self.assertEqual(call_args_proc[0].action_type, "NPC_PATROL")
        self.assertEqual(call_args_proc[1].id, npc_id)

        all_guild_actions = self.action_scheduler.get_all_actions_for_guild(self.guild_id)
        self.assertEqual(len(all_guild_actions),1)
        npc_action_from_scheduler = all_guild_actions[0]

        self.assertEqual(getattr(npc_action_from_scheduler, 'status', None), "completed") # Safe access
        self.assertEqual(getattr(npc_action_from_scheduler, 'action_type', None), "NPC_PATROL") # Safe access

        npc_action_result = getattr(npc_action_from_scheduler, 'result', None)
        self.assertIsInstance(npc_action_result, dict, "npc_action_from_scheduler.result should be a dictionary")
        self.assertTrue(npc_action_result.get('success'))
        self.assertIn("patrols to point_alpha", npc_action_result.get('message', ""))


    async def test_action_dependency_player_waits_for_npc(self):
        player_id = "player_dep_test"
        npc_id = "npc_dep_test"
        player_action_id = "player_action_dep"
        npc_action_id_fixed = "fixed_npc_action_for_dependency"

        player_char = _CharacterModel(
            id=player_id, name_i18n={"en":"Dependent Player"}, guild_id=self.guild_id, template_id="p_temp", # Ensure template_id
            collected_actions_json=json.dumps([
                {"intent_type": "FOLLOW_NPC", "action_id": player_action_id,
                 "target_npc_id": npc_id,
                 "custom_dependency_on_npc_action_id_for_test": npc_action_id_fixed
                }
            ])
        )
        npc_actor = _NPCModel(id=npc_id, name_i18n={"en":"Leading NPC"}, guild_id=self.guild_id, template_id="n_temp") # Ensure template_id

        self.mock_char_mgr.get_all_characters.return_value = [player_char]
        self.mock_char_mgr.get_character.return_value = player_char
        self.mock_npc_mgr.get_all_npcs.return_value = [npc_actor]
        self.mock_npc_mgr.get_npc.return_value = npc_actor

        async def mock_player_follow_processing(action_request: ActionRequest, character: _CharacterModel, context: Dict[str, Any]): # Type hints
            char_name = getattr(character, 'name', 'Unknown Player') # Safe access
            return {"success": True, "message": f"{char_name} follows.", "state_changed": True, "action_id": action_request.action_id, "actor_id": character.id}
        self.player_action_processor.process_action_from_request = AsyncMock(side_effect=mock_player_follow_processing)

        async def mock_npc_reach_dest_plan(npc: _NPCModel, guild_id_param: str, context_param: Dict[str, Any]): # Type hints
            return ActionRequest(
                action_id=npc_action_id_fixed,
                guild_id=guild_id_param, actor_id=npc.id, action_type="NPC_REACH_DESTINATION",
                action_data={"destination": "final_spot"}, execute_at=time.time()
            )
        self.npc_action_planner.plan_action = AsyncMock(side_effect=mock_npc_reach_dest_plan)

        async def mock_npc_reach_dest_process(action_request: ActionRequest, npc: _NPCModel): # Type hints
            npc_name = getattr(npc, 'name', 'Unknown NPC') # Safe access
            return {"success": True, "message": f"{npc_name} reached destination.", "state_changed": True, "action_id": action_request.action_id, "actor_id": npc.id}
        self.npc_action_processor.process_action = AsyncMock(side_effect=mock_npc_reach_dest_process)

        await self.turn_service.process_player_turns(self.guild_id)

        player_ar_from_scheduler = self.action_scheduler.get_action(self.guild_id, player_action_id)
        self.assertIsNotNone(player_ar_from_scheduler)
        if player_ar_from_scheduler: # Type guard for safety
            player_ar_from_scheduler.dependencies = [npc_action_id_fixed]
            player_ar_from_scheduler.execute_at = time.time() + 0.1

        guild_turn_context = {'rules_config': {}, 'guild_id': self.guild_id, 'managers': {}} # Ensure managers is dict
        result_turn1 = await self.turn_service.process_guild_turn(self.guild_id, guild_turn_context)

        self.assertIsInstance(result_turn1, dict, "result_turn1 should be a dictionary")
        self.assertEqual(result_turn1.get('npc_actions_planned'), 1)
        self.assertEqual(result_turn1.get('npc_actions_processed'), 1)
        self.assertEqual(result_turn1.get('player_actions_processed'), 0)

        npc_action_in_scheduler = self.action_scheduler.get_action(self.guild_id, npc_action_id_fixed)
        self.assertEqual(getattr(npc_action_in_scheduler, 'status', None), "completed") # Safe access

        player_action_in_scheduler = self.action_scheduler.get_action(self.guild_id, player_action_id)
        self.assertEqual(getattr(player_action_in_scheduler, 'status', None), "pending") # Safe access

        self.npc_action_planner.plan_action.reset_mock()
        async def mock_npc_idle_plan(npc: _NPCModel, guild_id_param: str, context_param: Dict[str, Any]):  # Type hints
            return ActionRequest(guild_id=guild_id_param, actor_id=npc.id, action_type="NPC_IDLE", execute_at=time.time())
        self.npc_action_planner.plan_action = AsyncMock(side_effect=mock_npc_idle_plan)

        async def mock_npc_idle_process(action_request: ActionRequest, npc: _NPCModel): # Type hints
            return {"success": True, "message":"NPC idles.", "state_changed":False, "action_id":action_request.action_id, "actor_id":npc.id}
        self.npc_action_processor.process_action = AsyncMock(side_effect=mock_npc_idle_process)

        result_turn2 = await self.turn_service.process_guild_turn(self.guild_id, guild_turn_context)
        self.assertIsInstance(result_turn2, dict, "result_turn2 should be a dictionary")

        self.npc_action_planner.plan_action.assert_called_once()

        self.assertEqual(result_turn2.get('player_actions_processed'), 1)
        self.assertEqual(result_turn2.get('npc_actions_processed'), 1)

        player_action_in_scheduler_after_turn2 = self.action_scheduler.get_action(self.guild_id, player_action_id)
        self.assertEqual(getattr(player_action_in_scheduler_after_turn2, 'status', None), "completed") # Safe access

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
