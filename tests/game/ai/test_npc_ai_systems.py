import unittest
from unittest.mock import MagicMock, patch, ANY
import time
import uuid
from typing import Optional, Dict, Any, List # Ensure these are imported for type hints

# Assuming ActionRequest, NPCActionPlanner, NPCActionProcessor are importable
# Adjust import paths if necessary
from bot.game.models.action_request import ActionRequest
from bot.game.ai.npc_action_planner import NPCActionPlanner
from bot.game.npc_action_processor import NPCActionProcessor
try:
    from bot.game.models.npc import NPC # Assuming NPC model exists
except ImportError:
    NPC = Any # Fallback if NPC model is not available or causes issues in test environment

from bot.game.ai.npc_combat_ai import NpcCombatAI # For mocking its behavior

# Basic NPC model stub for testing
# In a real test suite, you might use a factory or more complete fixtures
if NPC != Any and hasattr(NPC, 'model_validate'): # Check if it's a Pydantic v2 model
    class MockNPC(NPC): # type: ignore
        def __init__(self, id: str, name: str, current_location_id: Optional[str] = "loc1", **kwargs):
            # Pydantic v2 style init
            data = {
                "id": id,
                "name_i18n": {"en": name, "ru": name}, # Assuming name_i18n structure
                "guild_id": kwargs.get("guild_id", "test_guild"),
                "template_id": kwargs.get("template_id", "mock_template"),
                "current_location_id": current_location_id,
                "available_actions": kwargs.get("available_actions", [{"action_type": "attack", "name": "Punch", "weapon_id": "fist"}]),
                "current_combat_id": kwargs.get("current_combat_id", None),
                **kwargs
            }
            super().__init__(**data)
            # Ensure direct attribute assignment if NPC model doesn't automatically do it from kwargs
            # For Pydantic models, direct assignment after super().__init__ is usually not needed if fields are in schema
            self.id = id
            self.name = name # Keep direct name attribute for simplicity in tests if used
            self.current_location_id = current_location_id
            self.available_actions = data["available_actions"]
            self.current_combat_id = data["current_combat_id"]


elif NPC != Any: # Assuming it might be a Pydantic v1 model or a simple class
    class MockNPC(NPC): # type: ignore
        def __init__(self, id: str, name: str, current_location_id: Optional[str] = "loc1", **kwargs):
            # This assumes NPC's __init__ can handle these kwargs or Pydantic v1 style.
            # If NPC is not Pydantic, its __init__ must be matched.
            init_kwargs = {
                "id": id,
                "name_i18n": {"en": name},
                "guild_id": "test_guild",
                "template_id": "mock_template",
                "current_location_id": current_location_id,
                "available_actions": kwargs.get("available_actions", [{"action_type": "attack", "name": "Punch", "weapon_id": "fist"}]),
                "current_combat_id": None,
                **kwargs
            }
            try:
                super().__init__(**init_kwargs)
            except Exception as e: # Fallback if super init fails (e.g. non-Pydantic strict init)
                # print(f"MockNPC super().__init__ failed: {e}. Using direct assignment.")
                object.__setattr__(self, 'id', id) # Use object.__setattr__ if __setattr__ is overridden by Pydantic
                object.__setattr__(self, 'name_i18n', {"en": name})
                object.__setattr__(self, 'guild_id', "test_guild")
                # ... and so on for all required fields by NPC

            # Direct assignments for test access, potentially redundant if super().__init__ works
            self.id = id
            self.name = name
            self.current_location_id = current_location_id
            self.available_actions = init_kwargs["available_actions"]
            self.current_combat_id = init_kwargs["current_combat_id"]

else: # Fallback if NPC is Any (could not be imported)
    from pydantic import BaseModel, Field as PydanticField # Use alias to avoid conflict
    class MinimalNPCModel(BaseModel):
        id: str
        name_i18n: Dict[str, str] = PydanticField(default_factory=dict)
        guild_id: str
        template_id: str
        current_location_id: Optional[str] = None
        available_actions: List[Dict[str,Any]] = PydanticField(default_factory=list)
        current_combat_id: Optional[str] = None

        @property
        def name(self):
            return self.name_i18n.get("en", self.id)

    class MockNPC(MinimalNPCModel): # type: ignore
         def __init__(self, id: str, name: str, current_location_id: Optional[str] = "loc1", **kwargs):
            super().__init__(id=id, name_i18n={"en": name}, guild_id="test_guild", template_id="mock_template",
                             current_location_id=current_location_id,
                             available_actions=kwargs.get("available_actions", [{"action_type": "attack", "name": "Punch", "weapon_id": "fist"}]),
                             current_combat_id=kwargs.get("current_combat_id"),
                             **kwargs)
            # Pydantic models handle attribute assignment automatically.
            # For tests that might access self.name directly:
            self.name = name


class TestNPCActionPlanner(unittest.IsolatedAsyncioTestCase):
    async def test_plan_action_idle_if_no_combat(self):
        planner = NPCActionPlanner()
        npc_actor = MockNPC(id="npc1", name="Test NPC")
        guild_id = "test_guild"
        context = {}

        action_request = await planner.plan_action(npc_actor, guild_id, context)

        self.assertIsNotNone(action_request)
        self.assertIn(action_request.action_type, ["NPC_IDLE", "NPC_THINK"])
        self.assertEqual(action_request.actor_id, npc_actor.id)
        self.assertEqual(action_request.guild_id, guild_id)

    @patch('bot.game.ai.npc_action_planner.NpcCombatAI')
    async def test_plan_action_combat_action_chosen(self, MockNpcCombatAIClass):
        mock_combat_ai_instance = MockNpcCombatAIClass.return_value
        mock_combat_ai_instance.get_npc_combat_action.return_value = {
            "type": "ATTACK",
            "target_id": "player1",
            "weapon_id": "sword",
            "actor_id": "npc1"
        }

        planner = NPCActionPlanner()
        npc_actor = MockNPC(id="npc1", name="Combat NPC")
        guild_id = "test_guild"

        mock_combat_instance = MagicMock()
        mock_combat_instance.is_participant.return_value = True

        context = {
            'combat_instance': mock_combat_instance,
            'potential_targets': [MagicMock(id="player1")],
            'rules_config': {},
            'npc_effective_stats': {npc_actor.id: {"health": 100}},
            'targets_effective_stats': {"player1": {"health": 50}}
        }

        action_request = await planner.plan_action(npc_actor, guild_id, context)

        self.assertIsNotNone(action_request)
        self.assertEqual(action_request.action_type, "NPC_ATTACK")
        self.assertEqual(action_request.actor_id, npc_actor.id)
        self.assertEqual(action_request.guild_id, guild_id)
        self.assertEqual(action_request.action_data.get('target_id'), "player1")
        self.assertEqual(action_request.action_data.get('weapon_id'), "sword")

        MockNpcCombatAIClass.assert_called_once_with(npc=npc_actor)
        mock_combat_ai_instance.get_npc_combat_action.assert_called_once_with(
            combat_instance=mock_combat_instance,
            potential_targets=context['potential_targets'],
            context=ANY
        )

    @patch('bot.game.ai.npc_action_planner.NpcCombatAI')
    async def test_plan_action_combat_ai_returns_wait(self, MockNpcCombatAIClass):
        mock_combat_ai_instance = MockNpcCombatAIClass.return_value
        mock_combat_ai_instance.get_npc_combat_action.return_value = {"type": "wait"}

        planner = NPCActionPlanner()
        npc_actor = MockNPC(id="npc1", name="Waiting NPC")
        guild_id = "test_guild"
        mock_combat_instance = MagicMock()
        mock_combat_instance.is_participant.return_value = True

        context = {'combat_instance': mock_combat_instance, 'potential_targets': []}
        action_request = await planner.plan_action(npc_actor, guild_id, context)

        self.assertIsNotNone(action_request)
        self.assertEqual(action_request.action_type, "NPC_COMBAT_IDLE")
        self.assertEqual(action_request.actor_id, npc_actor.id)


class TestNPCActionProcessor(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_managers = {
            'game_log_manager': MagicMock(),
            'location_manager': MagicMock(),
            'combat_manager': MagicMock(),
            'character_manager': MagicMock(),
            'npc_manager': MagicMock()
        }
        self.processor = NPCActionProcessor(managers=self.mock_managers)

    async def test_process_action_npc_idle(self):
        npc_actor = MockNPC(id="npc1", name="Idle NPC")
        action_req = ActionRequest(
            guild_id="test_guild",
            actor_id=npc_actor.id,
            action_type="NPC_IDLE",
            action_data={"reason": "testing"}
        )
        result = await self.processor.process_action(action_req, npc_actor) # type: ignore

        self.assertTrue(result['success'])
        self.assertIn("idles", result['message'])
        self.assertFalse(result['state_changed'])
        self.mock_managers['game_log_manager'].log_event.assert_called_once()

    async def test_process_action_npc_think(self):
        npc_actor = MockNPC(id="npc1", name="Thinking NPC")
        action_req = ActionRequest(
            guild_id="test_guild",
            actor_id=npc_actor.id,
            action_type="NPC_THINK",
            action_data={"thought": "deep thoughts"}
        )
        result = await self.processor.process_action(action_req, npc_actor) # type: ignore

        self.assertTrue(result['success'])
        self.assertIn("deep thoughts", result['message'])
        self.assertFalse(result['state_changed'])
        self.mock_managers['game_log_manager'].log_event.assert_called_once()

    async def test_process_action_npc_move_placeholder(self):
        npc_actor = MockNPC(id="npc1", name="Moving NPC")
        target_loc_id = "new_location"
        action_req = ActionRequest(
            guild_id="test_guild",
            actor_id=npc_actor.id,
            action_type="NPC_MOVE",
            action_data={"target_location_id": target_loc_id}
        )

        result = await self.processor.process_action(action_req, npc_actor) # type: ignore

        self.assertTrue(result['success'])
        self.assertIn(f"moves to {target_loc_id}", result['message'])
        self.assertTrue(result['state_changed'])
        self.mock_managers['game_log_manager'].log_event.assert_called_once()

    async def test_process_action_npc_attack_placeholder(self):
        npc_actor = MockNPC(id="npc1", name="Attacking NPC")
        action_req = ActionRequest(
            guild_id="test_guild",
            actor_id=npc_actor.id,
            action_type="NPC_ATTACK",
            action_data={"target_id": "player1", "weapon_id": "claws", "action_name": "Claw Attack"}
        )

        result = await self.processor.process_action(action_req, npc_actor) # type: ignore

        self.assertTrue(result['success'])
        self.assertIn("performs Claw Attack on target player1", result['message'])
        self.assertTrue(result['state_changed'])
        self.mock_managers['game_log_manager'].log_event.assert_called_once()


    async def test_process_action_unknown_action(self):
        npc_actor = MockNPC(id="npc1", name="Confused NPC")
        action_req = ActionRequest(
            guild_id="test_guild",
            actor_id=npc_actor.id,
            action_type="NPC_DANCE_MACABRE",
            action_data={}
        )
        result = await self.processor.process_action(action_req, npc_actor) # type: ignore

        self.assertFalse(result['success'])
        self.assertIn("not yet implemented", result['message'])
        self.mock_managers['game_log_manager'].log_event.assert_called_once_with(
            guild_id="test_guild",
            event_type="NPC_ACTION_UNKNOWN",
            message=ANY,
            details=ANY
        )

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
