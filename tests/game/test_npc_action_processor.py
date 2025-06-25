import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# Models and Services to test/mock
from bot.game.npc_action_processor import NPCActionProcessor
from bot.game.models.action_request import ActionRequest
from bot.game.models.npc import NPC as PydanticNPC # Assuming Pydantic model for npc parameter

# Managers that NPCActionProcessor might use
from bot.game.managers.game_log_manager import GameLogManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.npc_manager import NpcManager


@pytest.fixture
def mock_managers_dict():
    managers = {
        "game_log_manager": AsyncMock(spec=GameLogManager),
        "location_manager": AsyncMock(spec=LocationManager),
        "combat_manager": AsyncMock(spec=CombatManager),
        "npc_manager": AsyncMock(spec=NpcManager)
        # Add other managers if NPCActionProcessor starts using them
    }
    return managers

@pytest.fixture
def npc_action_processor(mock_managers_dict: dict) -> NPCActionProcessor:
    return NPCActionProcessor(managers=mock_managers_dict)

@pytest.fixture
def mock_npc_object(mock_managers_dict) -> MagicMock: # Return MagicMock that can have attributes set
    npc = MagicMock(spec=PydanticNPC) # Use PydanticNPC if that's what's passed, or a mock of DB NPC
    npc.id = "npc_test_1"
    npc.name = "Test NPC" # PydanticNPC might use name_i18n
    npc.name_i18n = {"en": "Test NPC", "ru": "Тестовый НПЦ"}
    npc.guild_id = "test_guild_npc_proc"
    # Add other attributes if NPCActionProcessor methods access them directly
    # For example, if move action updates npc.current_location_id:
    npc.current_location_id = "loc_start"

    # If NPC object is fetched via NpcManager inside processor methods,
    # then mock_managers_dict["npc_manager"].get_npc.return_value = npc
    # But current process_action takes npc as argument.
    return npc

def create_action_request(
    guild_id: str,
    actor_id: str,
    action_type: str,
    action_data: dict
) -> ActionRequest:
    return ActionRequest(
        guild_id=guild_id,
        actor_id=actor_id,
        action_type=action_type,
        action_data=action_data,
        action_id=f"action_{str(uuid.uuid4())[:8]}" # Ensure unique action_id for logging
    )

@pytest.mark.asyncio
async def test_process_action_idle(
    npc_action_processor: NPCActionProcessor,
    mock_npc_object: MagicMock,
    mock_managers_dict: dict
):
    action = create_action_request(
        guild_id=mock_npc_object.guild_id,
        actor_id=mock_npc_object.id,
        action_type="NPC_IDLE",
        action_data={}
    )
    result = await npc_action_processor.process_action(action, mock_npc_object)

    assert result["success"] is True
    assert f"{mock_npc_object.name} idles" in result["message"]
    assert result["state_changed"] is False
    mock_managers_dict["game_log_manager"].log_event.assert_awaited_once_with(
        guild_id=action.guild_id,
        event_type="NPC_ACTION_IDLE",
        message=unittest.mock.ANY, # Message content can be more specific if needed
        details={"actor_id": action.actor_id, "action_id": action.action_id}
    )

@pytest.mark.asyncio
async def test_process_action_think(
    npc_action_processor: NPCActionProcessor,
    mock_npc_object: MagicMock,
    mock_managers_dict: dict
):
    thought_text = "Contemplating existence."
    action = create_action_request(
        guild_id=mock_npc_object.guild_id,
        actor_id=mock_npc_object.id,
        action_type="NPC_THINK",
        action_data={"thought": thought_text}
    )
    result = await npc_action_processor.process_action(action, mock_npc_object)

    assert result["success"] is True
    assert f"{mock_npc_object.name} thinks: '{thought_text}'" in result["message"]
    mock_managers_dict["game_log_manager"].log_event.assert_awaited_once_with(
        guild_id=action.guild_id,
        event_type="NPC_ACTION_THINK",
        message=unittest.mock.ANY,
        details={"actor_id": action.actor_id, "action_id": action.action_id, "thought": thought_text}
    )

@pytest.mark.asyncio
async def test_process_action_move_placeholder_success(
    npc_action_processor: NPCActionProcessor,
    mock_npc_object: MagicMock,
    mock_managers_dict: dict
):
    target_loc_id = "loc_destination_1"
    action = create_action_request(
        guild_id=mock_npc_object.guild_id,
        actor_id=mock_npc_object.id,
        action_type="NPC_MOVE",
        action_data={"target_location_id": target_loc_id}
    )

    # For placeholder, LocationManager might not be called for actual move.
    # If it were, we'd mock:
    # mock_managers_dict["location_manager"].move_entity_to_location.return_value = True

    result = await npc_action_processor.process_action(action, mock_npc_object)

    assert result["success"] is True
    assert f"{mock_npc_object.name} moves to {target_loc_id}" in result["message"]
    assert result["state_changed"] is True # Placeholder assumes move changes state
    mock_managers_dict["game_log_manager"].log_event.assert_awaited_once_with(
        guild_id=action.guild_id,
        event_type="NPC_ACTION_MOVE",
        message=unittest.mock.ANY,
        details={"actor_id": action.actor_id, "action_id": action.action_id, "target_location_id": target_loc_id}
    )

@pytest.mark.asyncio
async def test_process_action_attack_placeholder_success(
    npc_action_processor: NPCActionProcessor,
    mock_npc_object: MagicMock,
    mock_managers_dict: dict
):
    target_char_id = "char_victim_1"
    action = create_action_request(
        guild_id=mock_npc_object.guild_id,
        actor_id=mock_npc_object.id,
        action_type="NPC_ATTACK",
        action_data={"target_id": target_char_id, "action_name": "Basic Attack"}
    )
    # For placeholder, CombatManager might not be deeply involved.
    # If it were, mock:
    # mock_managers_dict["combat_manager"].process_npc_action_in_combat.return_value = {"success": True, ...}

    result = await npc_action_processor.process_action(action, mock_npc_object)

    assert result["success"] is True
    assert f"NPC {mock_npc_object.name} ({mock_npc_object.id}) performs Basic Attack on target {target_char_id}" in result["message"]
    assert result["state_changed"] is True
    mock_managers_dict["game_log_manager"].log_event.assert_awaited_once_with(
        guild_id=action.guild_id,
        event_type=f"NPC_ACTION_{action.action_type}", # Action type is NPC_ATTACK
        message=unittest.mock.ANY,
        details={"target_id": target_char_id, "action_name": "Basic Attack", "actor_id": action.actor_id, "action_id": action.action_id}
    )

@pytest.mark.asyncio
async def test_process_action_unhandled_type(
    npc_action_processor: NPCActionProcessor,
    mock_npc_object: MagicMock,
    mock_managers_dict: dict
):
    unhandled_action_type = "NPC_SING_OPERA"
    action = create_action_request(
        guild_id=mock_npc_object.guild_id,
        actor_id=mock_npc_object.id,
        action_type=unhandled_action_type,
        action_data={}
    )
    result = await npc_action_processor.process_action(action, mock_npc_object)

    assert result["success"] is False
    assert f"Action type '{unhandled_action_type}' not yet implemented" in result["message"]
    mock_managers_dict["game_log_manager"].log_event.assert_awaited_once_with(
        guild_id=action.guild_id,
        event_type="NPC_ACTION_UNKNOWN",
        message=unittest.mock.ANY,
        details={"actor_id": action.actor_id, "action_id": action.action_id, "action_type": unhandled_action_type, "action_data": {}}
    )

@pytest.mark.asyncio
async def test_process_action_exception_handling(
    npc_action_processor: NPCActionProcessor,
    mock_npc_object: MagicMock,
    mock_managers_dict: dict
):
    action = create_action_request(
        guild_id=mock_npc_object.guild_id,
        actor_id=mock_npc_object.id,
        action_type="NPC_IDLE", # Use a normally succeeding action
        action_data={}
    )
    # Force an error during logging, for example
    error_message = "Simulated logging failure"
    mock_managers_dict["game_log_manager"].log_event.side_effect = Exception(error_message)

    result = await npc_action_processor.process_action(action, mock_npc_object)

    assert result["success"] is False
    assert result.get("error") is True
    assert error_message in result["message"]

    # Check that the initial log attempt was made, then the error log attempt
    assert mock_managers_dict["game_log_manager"].log_event.call_count == 2
    first_call_args = mock_managers_dict["game_log_manager"].log_event.call_args_list[0].kwargs
    second_call_args = mock_managers_dict["game_log_manager"].log_event.call_args_list[1].kwargs

    assert first_call_args['event_type'] == "NPC_ACTION_IDLE" # First attempt
    assert second_call_args['event_type'] == "NPC_ACTION_ERROR" # Second attempt (logging the error)
    assert error_message in second_call_args['message']


print("DEBUG: tests/game/test_npc_action_processor.py created.")
