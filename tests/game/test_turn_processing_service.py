import pytest
import asyncio
# import time # Unused
import json
from unittest.mock import AsyncMock, MagicMock, patch, call, ANY
from typing import cast


from bot.game.turn_processing_service import TurnProcessingService
from bot.game.action_scheduler import GuildActionScheduler
from bot.game.ai.npc_action_planner import NPCActionPlanner
from bot.game.npc_action_processor import NPCActionProcessor
from bot.game.character_processors.character_action_processor import CharacterActionProcessor

from bot.database.models.character_related import Character as DBCharacter, NPC as DBNPC # Assuming these are the DB models
from bot.game.models.action_request import ActionRequest
from bot.game.models.character import Character as GameCharacterModel

from bot.game.managers.game_manager import GameManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.inventory_manager import InventoryManager
from bot.game.managers.dialogue_manager import DialogueManager
from bot.game.services.location_interaction_service import LocationInteractionService
from bot.game.managers.equipment_manager import EquipmentManager


@pytest.fixture
def mock_game_mngr_for_tps() -> MagicMock:
    gm = MagicMock(spec=GameManager)
    gm.character_manager = AsyncMock(spec=CharacterManager)
    gm.npc_manager = AsyncMock(spec=NpcManager)
    gm.game_log_manager = AsyncMock(spec=GameLogManager)
    gm.rule_engine = AsyncMock(spec=RuleEngine)
    gm.db_service = AsyncMock()
    gm.save_game_state_after_action = AsyncMock()

    # Ensure action_scheduler and its methods are correctly mocked
    gm.action_scheduler = MagicMock(spec=GuildActionScheduler)
    gm.action_scheduler.get_ready_actions = MagicMock(return_value=[]) # Default to empty list
    gm.action_scheduler.add_action = MagicMock()
    gm.action_scheduler.update_action_status = MagicMock()
    gm.action_scheduler.remove_action = MagicMock()


    gm.npc_action_planner = AsyncMock(spec=NPCActionPlanner)
    gm.npc_action_processor = AsyncMock(spec=NPCActionProcessor)
    gm.character_action_processor = AsyncMock(spec=CharacterActionProcessor)

    # Mock other potentially accessed managers
    gm.combat_manager = AsyncMock(spec=CombatManager)
    gm.location_manager = AsyncMock(spec=LocationManager)
    gm.item_manager = AsyncMock(spec=ItemManager)
    gm.inventory_manager = AsyncMock(spec=InventoryManager)
    gm.dialogue_manager = AsyncMock(spec=DialogueManager)
    gm.location_interaction_service = AsyncMock(spec=LocationInteractionService)
    gm.equipment_manager = AsyncMock(spec=EquipmentManager)


    # If rule_engine._rules_data is accessed, mock it. Otherwise, mock methods on rule_engine.
    # For now, assuming methods are called, so specific rule_engine method mocks might be needed in tests.
    # If direct _rules_data access is confirmed, uncomment and adjust:
    # gm.rule_engine._rules_data = {} # type: ignore[attr-defined]
    return gm

@pytest.fixture
def turn_processing_service(mock_game_mngr_for_tps: MagicMock) -> TurnProcessingService:
    # Cast managers to their specific types if TPS expects non-Optional versions
    # This helps Pyright if the attributes on the MagicMock are treated as Optional by default.
    return TurnProcessingService(
        character_manager=cast(CharacterManager, mock_game_mngr_for_tps.character_manager),
        rule_engine=cast(RuleEngine, mock_game_mngr_for_tps.rule_engine),
        game_manager=mock_game_mngr_for_tps, # GameManager itself can be MagicMock
        game_log_manager=cast(GameLogManager, mock_game_mngr_for_tps.game_log_manager),
        character_action_processor=cast(CharacterActionProcessor, mock_game_mngr_for_tps.character_action_processor),
        combat_manager=cast(CombatManager, mock_game_mngr_for_tps.combat_manager),
        location_manager=cast(LocationManager, mock_game_mngr_for_tps.location_manager),
        location_interaction_service=cast(LocationInteractionService, mock_game_mngr_for_tps.location_interaction_service),
        dialogue_manager=cast(DialogueManager, mock_game_mngr_for_tps.dialogue_manager),
        inventory_manager=cast(InventoryManager, mock_game_mngr_for_tps.inventory_manager),
        equipment_manager=cast(EquipmentManager, mock_game_mngr_for_tps.equipment_manager),
        item_manager=cast(ItemManager, mock_game_mngr_for_tps.item_manager),
        action_scheduler=cast(GuildActionScheduler, mock_game_mngr_for_tps.action_scheduler),
        npc_action_planner=cast(NPCActionPlanner, mock_game_mngr_for_tps.npc_action_planner),
        npc_action_processor=cast(NPCActionProcessor, mock_game_mngr_for_tps.npc_action_processor),
        npc_manager=cast(NpcManager, mock_game_mngr_for_tps.npc_manager),
        settings={}
    )

@pytest.mark.asyncio
async def test_run_turn_cycle_no_players_or_actions(
    turn_processing_service: TurnProcessingService,
    mock_game_mngr_for_tps: MagicMock
):
    guild_id = "test_guild_empty"
    mock_game_mngr_for_tps.character_manager.get_all_characters = AsyncMock(return_value=[])
    # mock_game_mngr_for_tps.action_scheduler.get_ready_actions is already a MagicMock returning []
    mock_game_mngr_for_tps.npc_manager.get_all_npcs = AsyncMock(return_value=[])

    await turn_processing_service.run_turn_cycle_check(guild_id)

    mock_game_mngr_for_tps.character_manager.get_all_characters.assert_awaited_with(guild_id)
    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.assert_any_call(guild_id)
    mock_game_mngr_for_tps.character_action_processor.process_action_from_request.assert_not_awaited()
    mock_game_mngr_for_tps.npc_action_planner.plan_action.assert_not_awaited()
    mock_game_mngr_for_tps.npc_action_processor.process_action.assert_not_awaited()

    mock_game_mngr_for_tps.game_log_manager.log_event.assert_any_call(guild_id=guild_id, event_type="turn_cycle_check_start", details=ANY)
    mock_game_mngr_for_tps.game_log_manager.log_event.assert_any_call(guild_id=guild_id, event_type="turn_cycle_check_end", details=ANY)


@pytest.mark.asyncio
async def test_run_turn_cycle_processes_player_actions(
    turn_processing_service: TurnProcessingService,
    mock_game_mngr_for_tps: MagicMock
):
    guild_id = "test_guild_player_actions"
    char_id = "char1"

    mock_char = MagicMock(spec=GameCharacterModel)
    mock_char.id = char_id
    mock_char.collected_actions_json = json.dumps([{"intent": "LOOK", "target_id": "obj1"}])
    mock_char.current_game_status = "actions_submitted"

    mock_game_mngr_for_tps.character_manager.get_all_characters = AsyncMock(return_value=[mock_char])
    mock_game_mngr_for_tps.character_manager.get_character = AsyncMock(return_value=mock_char)

    player_action_request = ActionRequest(guild_id=guild_id, actor_id=char_id, action_type="PLAYER_LOOK", action_data={"target_id": "obj1"})

    mock_game_mngr_for_tps.npc_manager.get_all_npcs = AsyncMock(return_value=[])
    mock_game_mngr_for_tps.npc_action_planner.plan_action = AsyncMock(return_value=None)

    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.side_effect = [[player_action_request], []]
    mock_game_mngr_for_tps.character_action_processor.process_action_from_request = AsyncMock(return_value={"success": True, "message": "Looked.", "state_changed": True})

    await turn_processing_service.run_turn_cycle_check(guild_id)

    mock_game_mngr_for_tps.action_scheduler.add_action.assert_called_once()
    added_action_arg = mock_game_mngr_for_tps.action_scheduler.add_action.call_args[0][0]
    assert isinstance(added_action_arg, ActionRequest)
    assert added_action_arg.actor_id == char_id
    assert added_action_arg.action_type == "PLAYER_LOOK"

    # Assertions on mock_char attributes after processing
    assert mock_char.collected_actions_json == None # Should be cleared
    assert mock_char.current_game_status == "actions_queued" # Initial status after action extraction


    mock_game_mngr_for_tps.character_action_processor.process_action_from_request.assert_awaited_once_with(
        action_request=player_action_request,
        character=mock_char,
        context=ANY
    )
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, player_action_request.action_id, "processing")
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, player_action_request.action_id, "completed", {"success": True, "message": "Looked.", "state_changed": True})

    # Check final status of character after action completion
    self.assertEqual(mock_char.current_game_status, "turn_cycle_complete")
    mock_game_mngr_for_tps.character_manager.mark_character_dirty.assert_any_call(guild_id, char_id)
    mock_game_mngr_for_tps.save_game_state_after_action.assert_any_call(guild_id)


@pytest.mark.asyncio
async def test_run_turn_cycle_plans_and_processes_npc_actions(
    turn_processing_service: TurnProcessingService,
    mock_game_mngr_for_tps: MagicMock
):
    guild_id = "test_guild_npc_actions"
    npc_id = "npc1"
    mock_npc = MagicMock(spec=DBNPC)
    mock_npc.id = npc_id

    mock_game_mngr_for_tps.character_manager.get_all_characters = AsyncMock(return_value=[])
    mock_game_mngr_for_tps.npc_manager.get_all_npcs = AsyncMock(return_value=[mock_npc])
    mock_game_mngr_for_tps.npc_manager.get_npc = AsyncMock(return_value=mock_npc)

    npc_action_request = ActionRequest(guild_id=guild_id, actor_id=npc_id, action_type="NPC_PATROL", action_data={})
    mock_game_mngr_for_tps.npc_action_planner.plan_action = AsyncMock(return_value=npc_action_request)

    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.side_effect = [[], [npc_action_request]]
    mock_game_mngr_for_tps.npc_action_processor.process_action = AsyncMock(return_value={"success": True, "message": "Patrolled.", "state_changed": True})

    await turn_processing_service.run_turn_cycle_check(guild_id)

    mock_game_mngr_for_tps.npc_action_planner.plan_action.assert_awaited_once_with(mock_npc, guild_id, ANY)
    mock_game_mngr_for_tps.action_scheduler.add_action.assert_called_once_with(npc_action_request)

    mock_game_mngr_for_tps.npc_action_processor.process_action.assert_awaited_once_with(
        action_request=npc_action_request,
        npc=mock_npc
    )
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, npc_action_request.action_id, "processing")
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, npc_action_request.action_id, "completed", {"success": True, "message": "Patrolled.", "state_changed": True})

    mock_game_mngr_for_tps.npc_manager.mark_npc_dirty.assert_awaited_with(guild_id, npc_id) # Use awaited_with for async
    mock_game_mngr_for_tps.save_game_state_after_action.assert_any_call(guild_id)
