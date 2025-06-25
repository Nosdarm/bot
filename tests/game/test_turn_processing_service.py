import pytest
import asyncio
import time
import json
from unittest.mock import AsyncMock, MagicMock, patch, call # Import call from unittest.mock

# Models and Services to test/mock
from bot.game.turn_processing_service import TurnProcessingService
from bot.game.action_scheduler import GuildActionScheduler
from bot.game.ai.npc_action_planner import NPCActionPlanner
from bot.game.npc_action_processor import NPCActionProcessor
from bot.game.character_processors.character_action_processor import CharacterActionProcessor

from bot.database.models import Player, Character as DBCharacter, NPC as DBNPC
from bot.game.models.action_request import ActionRequest

from bot.game.managers.game_manager import GameManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.rules.rule_engine import RuleEngine


@pytest.fixture
def mock_game_mngr_for_tps():
    gm = AsyncMock(spec=GameManager)
    gm.character_manager = AsyncMock(spec=CharacterManager)
    gm.npc_manager = AsyncMock(spec=NpcManager)
    gm.game_log_manager = AsyncMock(spec=GameLogManager)
    gm.rule_engine = AsyncMock(spec=RuleEngine)
    gm.db_service = AsyncMock()
    gm.save_game_state_after_action = AsyncMock()

    gm.action_scheduler = MagicMock(spec=GuildActionScheduler)
    gm.npc_action_planner = AsyncMock(spec=NPCActionPlanner)
    gm.npc_action_processor = AsyncMock(spec=NPCActionProcessor)
    gm.character_action_processor = AsyncMock(spec=CharacterActionProcessor)

    gm.combat_manager = AsyncMock()
    gm.location_manager = AsyncMock()
    gm.item_manager = AsyncMock()
    gm.inventory_manager = AsyncMock()
    gm.dialogue_manager = AsyncMock()
    gm.location_interaction_service = AsyncMock()
    gm.equipment_manager = AsyncMock()

    gm.rule_engine._rules_data = {}

    return gm

@pytest.fixture
def turn_processing_service(mock_game_mngr_for_tps: GameManager):
    return TurnProcessingService(
        character_manager=mock_game_mngr_for_tps.character_manager,
        rule_engine=mock_game_mngr_for_tps.rule_engine,
        game_manager=mock_game_mngr_for_tps,
        game_log_manager=mock_game_mngr_for_tps.game_log_manager,
        character_action_processor=mock_game_mngr_for_tps.character_action_processor,
        combat_manager=mock_game_mngr_for_tps.combat_manager,
        location_manager=mock_game_mngr_for_tps.location_manager,
        location_interaction_service=mock_game_mngr_for_tps.location_interaction_service,
        dialogue_manager=mock_game_mngr_for_tps.dialogue_manager,
        inventory_manager=mock_game_mngr_for_tps.inventory_manager,
        equipment_manager=mock_game_mngr_for_tps.equipment_manager,
        item_manager=mock_game_mngr_for_tps.item_manager,
        action_scheduler=mock_game_mngr_for_tps.action_scheduler,
        npc_action_planner=mock_game_mngr_for_tps.npc_action_planner,
        npc_action_processor=mock_game_mngr_for_tps.npc_action_processor,
        npc_manager=mock_game_mngr_for_tps.npc_manager,
        settings={}
    )

@pytest.mark.asyncio
async def test_run_turn_cycle_no_players_or_actions(
    turn_processing_service: TurnProcessingService,
    mock_game_mngr_for_tps: GameManager
):
    guild_id = "test_guild_empty"
    mock_game_mngr_for_tps.character_manager.get_all_characters.return_value = []
    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.return_value = []
    mock_game_mngr_for_tps.npc_manager.get_all_npcs.return_value = []

    await turn_processing_service.run_turn_cycle_check(guild_id)

    mock_game_mngr_for_tps.character_manager.get_all_characters.assert_called_with(guild_id)
    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.assert_any_call(guild_id)
    mock_game_mngr_for_tps.character_action_processor.process_action_from_request.assert_not_called()
    mock_game_mngr_for_tps.npc_action_planner.plan_action.assert_not_called()
    mock_game_mngr_for_tps.npc_action_processor.process_action.assert_not_called()

    mock_game_mngr_for_tps.game_log_manager.log_event.assert_any_call(guild_id=guild_id, event_type="turn_cycle_check_start", details=pytest. детей.ANY)
    mock_game_mngr_for_tps.game_log_manager.log_event.assert_any_call(guild_id=guild_id, event_type="turn_cycle_check_end", details=pytest. детей.ANY)


@pytest.mark.asyncio
async def test_run_turn_cycle_processes_player_actions(
    turn_processing_service: TurnProcessingService,
    mock_game_mngr_for_tps: GameManager
):
    guild_id = "test_guild_player_actions"
    char_id = "char1"

    mock_char = MagicMock(spec=DBCharacter)
    mock_char.id = char_id
    mock_char.collected_actions_json = json.dumps([{"intent": "LOOK", "target_id": "obj1"}])
    mock_char.current_game_status = "actions_submitted"

    mock_game_mngr_for_tps.character_manager.get_all_characters.return_value = [mock_char]
    mock_game_mngr_for_tps.character_manager.get_character.return_value = mock_char

    player_action_request = ActionRequest(guild_id=guild_id, actor_id=char_id, action_type="PLAYER_LOOK", action_data={"target_id": "obj1"})

    mock_game_mngr_for_tps.npc_manager.get_all_npcs.return_value = []
    mock_game_mngr_for_tps.npc_action_planner.plan_action.return_value = None

    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.side_effect = [[player_action_request], []]
    mock_game_mngr_for_tps.action_scheduler.add_action = MagicMock()
    mock_game_mngr_for_tps.action_scheduler.update_action_status = MagicMock()

    mock_game_mngr_for_tps.character_action_processor.process_action_from_request.return_value = {"success": True, "message": "Looked.", "state_changed": True}

    await turn_processing_service.run_turn_cycle_check(guild_id)

    mock_game_mngr_for_tps.action_scheduler.add_action.assert_called_once()
    added_action_arg = mock_game_mngr_for_tps.action_scheduler.add_action.call_args[0][0]
    assert isinstance(added_action_arg, ActionRequest)
    assert added_action_arg.actor_id == char_id
    assert added_action_arg.action_type == "PLAYER_LOOK"

    assert mock_char.collected_actions_json is None
    assert mock_char.current_game_status == "actions_queued"

    mock_game_mngr_for_tps.character_action_processor.process_action_from_request.assert_awaited_once_with(
        action_request=player_action_request,
        character=mock_char,
        context=pytest. детей.ANY
    )
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, player_action_request.action_id, "processing")
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, player_action_request.action_id, "completed", {"success": True, "message": "Looked.", "state_changed": True})

    assert mock_char.current_game_status == "turn_cycle_complete"
    mock_game_mngr_for_tps.character_manager.mark_character_dirty.assert_any_call(guild_id, char_id)
    mock_game_mngr_for_tps.save_game_state_after_action.assert_any_call(guild_id)


@pytest.mark.asyncio
async def test_run_turn_cycle_plans_and_processes_npc_actions(
    turn_processing_service: TurnProcessingService,
    mock_game_mngr_for_tps: GameManager
):
    guild_id = "test_guild_npc_actions"
    npc_id = "npc1"
    mock_npc = MagicMock(spec=DBNPC)
    mock_npc.id = npc_id

    mock_game_mngr_for_tps.character_manager.get_all_characters.return_value = []
    mock_game_mngr_for_tps.npc_manager.get_all_npcs.return_value = [mock_npc]
    mock_game_mngr_for_tps.npc_manager.get_npc.return_value = mock_npc

    npc_action_request = ActionRequest(guild_id=guild_id, actor_id=npc_id, action_type="NPC_PATROL", action_data={})
    mock_game_mngr_for_tps.npc_action_planner.plan_action.return_value = npc_action_request

    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.side_effect = [[], [npc_action_request]]
    mock_game_mngr_for_tps.action_scheduler.add_action = MagicMock()
    mock_game_mngr_for_tps.action_scheduler.update_action_status = MagicMock()

    mock_game_mngr_for_tps.npc_action_processor.process_action.return_value = {"success": True, "message": "Patrolled.", "state_changed": True}

    await turn_processing_service.run_turn_cycle_check(guild_id)

    mock_game_mngr_for_tps.npc_action_planner.plan_action.assert_awaited_once_with(mock_npc, guild_id, pytest. детей.ANY)
    mock_game_mngr_for_tps.action_scheduler.add_action.assert_called_once_with(npc_action_request)

    mock_game_mngr_for_tps.npc_action_processor.process_action.assert_awaited_once_with(
        action_request=npc_action_request,
        npc=mock_npc
    )
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, npc_action_request.action_id, "processing")
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, npc_action_request.action_id, "completed", {"success": True, "message": "Patrolled.", "state_changed": True})

    mock_game_mngr_for_tps.npc_manager.mark_npc_dirty.assert_called_with(guild_id, npc_id)
    mock_game_mngr_for_tps.save_game_state_after_action.assert_any_call(guild_id)

print("DEBUG: tests/game/test_turn_processing_service.py overwritten.")
