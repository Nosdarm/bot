import pytest
import asyncio
import time
import json
from unittest.mock import AsyncMock, MagicMock, patch, call, ANY # Import ANY

# Models and Services to test/mock
from bot.game.turn_processing_service import TurnProcessingService
from bot.game.action_scheduler import GuildActionScheduler
from bot.game.ai.npc_action_planner import NPCActionPlanner
from bot.game.npc_action_processor import NPCActionProcessor
from bot.game.character_processors.character_action_processor import CharacterActionProcessor

from bot.database.models import Player, Character as DBCharacter, NPC as DBNPC # type: ignore[attr-defined] # Assuming models are correct
from bot.game.models.action_request import ActionRequest
from bot.game.models.character import Character as GameCharacterModel # For mock_char spec

from bot.game.managers.game_manager import GameManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.rules.rule_engine import RuleEngine


@pytest.fixture
def mock_game_mngr_for_tps() -> MagicMock: # Return type hint
    gm = MagicMock(spec=GameManager) # Use MagicMock for general manager
    gm.character_manager = AsyncMock(spec=CharacterManager)
    gm.npc_manager = AsyncMock(spec=NpcManager)
    gm.game_log_manager = AsyncMock(spec=GameLogManager)
    gm.rule_engine = AsyncMock(spec=RuleEngine)
    gm.db_service = AsyncMock() # Keep as AsyncMock if DB ops are async
    gm.save_game_state_after_action = AsyncMock()

    gm.action_scheduler = MagicMock(spec=GuildActionScheduler)
    # Ensure methods on action_scheduler are also mocks if called directly and asserted upon
    gm.action_scheduler.get_ready_actions = MagicMock(return_value=[])
    gm.action_scheduler.add_action = MagicMock()
    gm.action_scheduler.update_action_status = MagicMock()

    gm.npc_action_planner = AsyncMock(spec=NPCActionPlanner)
    gm.npc_action_processor = AsyncMock(spec=NPCActionProcessor)
    gm.character_action_processor = AsyncMock(spec=CharacterActionProcessor)

    # Mock other managers if their methods are directly called by TPS or its components
    gm.combat_manager = AsyncMock()
    gm.location_manager = AsyncMock()
    gm.item_manager = AsyncMock()
    gm.inventory_manager = AsyncMock()
    gm.dialogue_manager = AsyncMock()
    gm.location_interaction_service = AsyncMock()
    gm.equipment_manager = AsyncMock()

    # Ensure rule_engine has _rules_data if accessed directly by TPS (though unlikely)
    # If TPS calls methods on rule_engine that use _rules_data, those methods should be mocked.
    if hasattr(gm.rule_engine, '_rules_data'):
        gm.rule_engine._rules_data = {} # type: ignore[attr-defined]

    return gm

@pytest.fixture
def turn_processing_service(mock_game_mngr_for_tps: MagicMock) -> TurnProcessingService: # Corrected type hint
    # Ensure all passed managers are not None for TPS constructor if it expects non-Optional
    # Using cast or # type: ignore[arg-type] if managers on mock_game_mngr_for_tps are Optional but TPS needs concrete
    return TurnProcessingService(
        character_manager=mock_game_mngr_for_tps.character_manager, # type: ignore[arg-type]
        rule_engine=mock_game_mngr_for_tps.rule_engine, # type: ignore[arg-type]
        game_manager=mock_game_mngr_for_tps, # type: ignore[arg-type]
        game_log_manager=mock_game_mngr_for_tps.game_log_manager, # type: ignore[arg-type]
        character_action_processor=mock_game_mngr_for_tps.character_action_processor, # type: ignore[arg-type]
        combat_manager=mock_game_mngr_for_tps.combat_manager, # type: ignore[arg-type]
        location_manager=mock_game_mngr_for_tps.location_manager, # type: ignore[arg-type]
        location_interaction_service=mock_game_mngr_for_tps.location_interaction_service, # type: ignore[arg-type]
        dialogue_manager=mock_game_mngr_for_tps.dialogue_manager, # type: ignore[arg-type]
        inventory_manager=mock_game_mngr_for_tps.inventory_manager, # type: ignore[arg-type]
        equipment_manager=mock_game_mngr_for_tps.equipment_manager, # type: ignore[arg-type]
        item_manager=mock_game_mngr_for_tps.item_manager, # type: ignore[arg-type]
        action_scheduler=mock_game_mngr_for_tps.action_scheduler, # type: ignore[arg-type]
        npc_action_planner=mock_game_mngr_for_tps.npc_action_planner, # type: ignore[arg-type]
        npc_action_processor=mock_game_mngr_for_tps.npc_action_processor, # type: ignore[arg-type]
        npc_manager=mock_game_mngr_for_tps.npc_manager, # type: ignore[arg-type]
        settings={}
    )

@pytest.mark.asyncio
async def test_run_turn_cycle_no_players_or_actions(
    turn_processing_service: TurnProcessingService,
    mock_game_mngr_for_tps: MagicMock # Corrected type hint
):
    guild_id = "test_guild_empty"
    # Ensure methods on manager mocks are themselves mocks if return_value/side_effect is set
    mock_game_mngr_for_tps.character_manager.get_all_characters = AsyncMock(return_value=[])
    mock_game_mngr_for_tps.action_scheduler.get_ready_actions = MagicMock(return_value=[])
    mock_game_mngr_for_tps.npc_manager.get_all_npcs = AsyncMock(return_value=[])

    await turn_processing_service.run_turn_cycle_check(guild_id)

    mock_game_mngr_for_tps.character_manager.get_all_characters.assert_called_with(guild_id)
    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.assert_any_call(guild_id)
    mock_game_mngr_for_tps.character_action_processor.process_action_from_request.assert_not_called()
    mock_game_mngr_for_tps.npc_action_planner.plan_action.assert_not_called()
    mock_game_mngr_for_tps.npc_action_processor.process_action.assert_not_called()

    mock_game_mngr_for_tps.game_log_manager.log_event.assert_any_call(guild_id=guild_id, event_type="turn_cycle_check_start", details=ANY)
    mock_game_mngr_for_tps.game_log_manager.log_event.assert_any_call(guild_id=guild_id, event_type="turn_cycle_check_end", details=ANY)


@pytest.mark.asyncio
async def test_run_turn_cycle_processes_player_actions(
    turn_processing_service: TurnProcessingService,
    mock_game_mngr_for_tps: MagicMock # Corrected type hint
):
    guild_id = "test_guild_player_actions"
    char_id = "char1"

    mock_char = MagicMock(spec=GameCharacterModel) # Use GameCharacterModel for spec
    mock_char.id = char_id
    mock_char.collected_actions_json = json.dumps([{"intent": "LOOK", "target_id": "obj1"}])
    mock_char.current_game_status = "actions_submitted"

    mock_game_mngr_for_tps.character_manager.get_all_characters = AsyncMock(return_value=[mock_char])
    mock_game_mngr_for_tps.character_manager.get_character = AsyncMock(return_value=mock_char) # Ensure it's AsyncMock

    player_action_request = ActionRequest(guild_id=guild_id, actor_id=char_id, action_type="PLAYER_LOOK", action_data={"target_id": "obj1"})

    mock_game_mngr_for_tps.npc_manager.get_all_npcs = AsyncMock(return_value=[])
    mock_game_mngr_for_tps.npc_action_planner.plan_action = AsyncMock(return_value=None) # Ensure AsyncMock

    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.side_effect = [[player_action_request], []] # This is fine for MagicMock
    # add_action and update_action_status are already MagicMocks from fixture

    mock_game_mngr_for_tps.character_action_processor.process_action_from_request = AsyncMock(return_value={"success": True, "message": "Looked.", "state_changed": True})

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
        context=ANY
    )
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, player_action_request.action_id, "processing")
    mock_game_mngr_for_tps.action_scheduler.update_action_status.assert_any_call(guild_id, player_action_request.action_id, "completed", {"success": True, "message": "Looked.", "state_changed": True})

    assert mock_char.current_game_status == "turn_cycle_complete"
    mock_game_mngr_for_tps.character_manager.mark_character_dirty.assert_any_call(guild_id, char_id)
    mock_game_mngr_for_tps.save_game_state_after_action.assert_any_call(guild_id)


@pytest.mark.asyncio
async def test_run_turn_cycle_plans_and_processes_npc_actions(
    turn_processing_service: TurnProcessingService,
    mock_game_mngr_for_tps: MagicMock # Corrected type hint
):
    guild_id = "test_guild_npc_actions"
    npc_id = "npc1"
    mock_npc = MagicMock(spec=DBNPC) # Use DBNPC if that's what NpcManager methods return/expect
    mock_npc.id = npc_id

    mock_game_mngr_for_tps.character_manager.get_all_characters = AsyncMock(return_value=[])
    mock_game_mngr_for_tps.npc_manager.get_all_npcs = AsyncMock(return_value=[mock_npc])
    mock_game_mngr_for_tps.npc_manager.get_npc = AsyncMock(return_value=mock_npc)

    npc_action_request = ActionRequest(guild_id=guild_id, actor_id=npc_id, action_type="NPC_PATROL", action_data={})
    mock_game_mngr_for_tps.npc_action_planner.plan_action = AsyncMock(return_value=npc_action_request)

    mock_game_mngr_for_tps.action_scheduler.get_ready_actions.side_effect = [[], [npc_action_request]]
    # add_action and update_action_status are already MagicMocks

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

    mock_game_mngr_for_tps.npc_manager.mark_npc_dirty.assert_called_with(guild_id, npc_id)
    mock_game_mngr_for_tps.save_game_state_after_action.assert_any_call(guild_id)

print("DEBUG: tests/game/test_turn_processing_service.py overwritten.")
