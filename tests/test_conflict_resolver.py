import pytest
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

from bot.game.conflict_resolver import ConflictResolver
# Assuming RuleEngine and NotificationService might be imported by ConflictResolver
# For mocking, we might not need direct imports if they are passed to __init__

# Sample rules_config for testing
# Note: The "check_type" here should match a key in RuleEngine's self._rules_data['checks']
# if RuleEngine.resolve_check uses it to fetch specific check configurations.
# For the tests, we'll mock RuleEngine.resolve_check's return value directly.
SAMPLE_RULES_CONFIG = {
    "simultaneous_move_to_limited_space": {
        "description": "Two entities attempt to move into the same limited space.",
        "manual_resolution_required": False,
        "automatic_resolution": {
            "check_type": "opposed_agility_check", # Example check_type for RuleEngine
            "difficulty_dc": None, # DC might be irrelevant for opposed, or RuleEngine handles it
            "outcome_rules": { # How ConflictResolver maps RuleEngine result to conflict outcome
                "higher_wins": True, # Assuming RuleEngine's success means actor won opposed roll
                "tie_breaker_rule": "random", # RuleEngine should handle this
                "outcomes": {
                    "actor_wins": {"description": "Actor gets the space.", "effects": ["actor_moves_to_space"]},
                    "target_wins": {"description": "Target gets the space.", "effects": ["target_moves_to_space"]},
                    "tie": {"description": "Both fail or a random outcome.", "effects": ["both_fail_move"]},
                    # Example: if RuleEngine.resolve_check returns outcome "CRITICAL_SUCCESS" for actor
                    "actor_crit_wins": {"description": "Actor critically gets the space!", "effects": ["actor_moves_to_space", "target_stunned_briefly"]},
                }
            }
        },
        "notification_format": { # This is for ConflictResolver's own use if it sends notifications
            "message": "Conflict: {actor_id} vs {target_id} for space {space_id} automatically resolved."
        }
    },
    "contested_resource_grab": {
        "description": "Two players try to grab the same unique item.",
        "manual_resolution_required": True,
        "notification_format": {
            "message": "Manual resolution required: {actor_id} vs {target_id} for item {item_id} at {location}.",
            "placeholders": ["actor_id", "target_id", "item_id", "location"]
        }
    },
    "unknown_conflict_type": {
        # No definition, to test error handling
    }
}

@pytest.fixture
def mock_rule_engine():
    engine = MagicMock()
    # RuleEngine.resolve_check is now async, so mock it with AsyncMock
    engine.resolve_check = AsyncMock()
    # RuleEngine.resolve_dice_roll is also async (though not directly used by ConflictResolver's auto_resolve now)
    engine.resolve_dice_roll = AsyncMock()
    return engine

@pytest.fixture
def mock_notification_service():
    service = MagicMock()
    # If NotificationService.send_master_alert were async:
    # service.send_master_alert = AsyncMock()
    # For now, prepare_for_manual_resolution is sync.
    return service

@pytest.fixture
def conflict_resolver_instance(mock_rule_engine, mock_notification_service):
    return ConflictResolver(
        rule_engine=mock_rule_engine,
        rules_config_data=SAMPLE_RULES_CONFIG,
        notification_service=mock_notification_service
    )

# --- Test analyze_actions_for_conflicts ---

@pytest.mark.asyncio
async def test_analyze_actions_no_conflict(conflict_resolver_instance: ConflictResolver):
    """Test that no conflicts are returned for non-conflicting actions."""
    player_actions = {
        "player1": [{"type": "MOVE", "target_space": "A1", "player_id": "player1"}],
        "player2": [{"type": "MOVE", "target_space": "B2", "player_id": "player2"}],
    }
    conflicts = await conflict_resolver_instance.analyze_actions_for_conflicts(player_actions)
    assert len(conflicts) == 0

@pytest.mark.asyncio
async def test_analyze_actions_simple_auto_conflict(conflict_resolver_instance: ConflictResolver, mock_rule_engine: AsyncMock):
    """Test identification and automatic resolution path for a simple conflict."""
    player_actions = {
        "player1": [{"type": "MOVE", "target_space": "X1Y1", "player_id": "player1", "entity_type": "Character"}],
        "player2": [{"type": "MOVE", "target_space": "X1Y1", "player_id": "player2", "entity_type": "Character"}],
    }
    
    # Mock RuleEngine.resolve_check for the automatic resolution part
    # Assume player1 (actor) wins the check
    mock_detailed_check_result = MagicMock()
    mock_detailed_check_result.is_success = True
    # Assuming CheckOutcome enum might be used by RuleEngine, or plain strings:
    mock_detailed_check_result.outcome = "SUCCESS" # or CheckOutcome.SUCCESS
    mock_detailed_check_result.total_roll_value = 15
    mock_detailed_check_result.rolls = [10] # Example roll
    mock_detailed_check_result.modifier_applied = 5 # Example modifier
    mock_detailed_check_result.description = "Player1 won check"
    mock_rule_engine.resolve_check.return_value = mock_detailed_check_result
        
    test_context = {"guild_id": "test_guild"}
    
    conflicts = await conflict_resolver_instance.analyze_actions_for_conflicts(player_actions, context=test_context)
    
    assert len(conflicts) == 1
    conflict_result = conflicts[0]
    
    assert conflict_result["type"] == "simultaneous_move_to_limited_space"
    assert "player1" in conflict_result["involved_players"]
    assert "player2" in conflict_result["involved_players"]
    assert conflict_result["status"] == "resolved_automatically"
    assert "outcome" in conflict_result
    assert conflict_result["outcome"]["winner_id"] == "player1" 
    
    mock_rule_engine.resolve_check.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_actions_simple_manual_conflict(conflict_resolver_instance: ConflictResolver, mock_notification_service: MagicMock):
    """Test identification and manual resolution path for a conflict."""
    # Temporarily modify rule for this test
    original_rule_config = SAMPLE_RULES_CONFIG["simultaneous_move_to_limited_space"].copy() # Shallow copy
    # Deep copy parts that will be modified if necessary, or ensure test isolation
    SAMPLE_RULES_CONFIG["simultaneous_move_to_limited_space"] = {
        **original_rule_config,
        "manual_resolution_required": True,
        "automatic_resolution": None # Ensure auto is disabled
    }

    player_actions = {
        "player1": [{"type": "MOVE", "target_space": "Z1Z1", "player_id": "player1"}],
        "player2": [{"type": "MOVE", "target_space": "Z1Z1", "player_id": "player2"}],
    }
    test_context = {"guild_id": "test_guild"} # analyze_actions_for_conflicts now takes context

    # prepare_for_manual_resolution is synchronous
    conflicts = await conflict_resolver_instance.analyze_actions_for_conflicts(player_actions, context=test_context)
        
    assert len(conflicts) == 1
    conflict_result = conflicts[0]

    assert conflict_result["type"] == "simultaneous_move_to_limited_space"
    assert "player1" in conflict_result["details_for_master"] 
    assert "player2" in conflict_result["details_for_master"]
    assert conflict_result["status"] == "awaiting_manual_resolution"
    assert "conflict_id" in conflict_result
    
    assert conflict_result["conflict_id"] in conflict_resolver_instance.pending_manual_resolutions
    
    # Restore original rule config by replacing the key
    SAMPLE_RULES_CONFIG["simultaneous_move_to_limited_space"] = original_rule_config


# --- Test resolve_conflict_automatically ---

@pytest.mark.asyncio
async def test_resolve_conflict_automatically_actor_wins(conflict_resolver_instance: ConflictResolver, mock_rule_engine: AsyncMock):
    conflict_data = {
        "type": "simultaneous_move_to_limited_space",
        "involved_players": ["playerA", "playerB"],
        "details": {
            "space_id": "Y1Y1", 
            "actions": [ # Provide mock actions to infer entity_type
                {"player_id": "playerA", "entity_type": "Character"}, # actor
                {"player_id": "playerB", "entity_type": "Character"}  # target
            ],
            # guild_id should be passed in context for RuleEngine.resolve_check
        },
        "status": "identified"
    }
    
    # Mock RuleEngine.resolve_check to make playerA (actor) win
    mock_detailed_check_result = MagicMock() # This will be the return value of an AsyncMock
    mock_detailed_check_result.is_success = True
    mock_detailed_check_result.outcome = "SUCCESS" # Or CheckOutcome.SUCCESS
    mock_detailed_check_result.total_roll_value = 18
    mock_detailed_check_result.rolls = [15]
    mock_detailed_check_result.modifier_applied = 3
    mock_detailed_check_result.description = "PlayerA won opposed check for space."
    mock_rule_engine.resolve_check.return_value = mock_detailed_check_result
        
    resolved_conflict = await conflict_resolver_instance.resolve_conflict_automatically(conflict_data, context={"guild_id": "test_guild_auto_resolve"})

    assert resolved_conflict["status"] == "resolved_automatically"
    assert resolved_conflict["outcome"]["winner_id"] == "playerA"
    assert "actor_moves_to_space" in resolved_conflict["outcome"]["effects"]
    assert "conflict_id" in resolved_conflict
    
    # Verify RuleEngine.resolve_check was called with correct parameters
    mock_rule_engine.resolve_check.assert_called_once_with(
        check_type=SAMPLE_RULES_CONFIG["simultaneous_move_to_limited_space"]["automatic_resolution"]["check_type"],
        entity_doing_check_id="playerA",
        entity_doing_check_type="Character",
        target_entity_id="playerB",
        target_entity_type="Character",
        difficulty_dc=None, # As per current SAMPLE_RULES_CONFIG
        context={"guild_id": "test_guild_auto_resolve"}
    )

# Add tests for target_wins and tie by changing mock_rule_engine.resolve_check.return_value

# --- Test prepare_for_manual_resolution ---
# This method is currently synchronous.

def test_prepare_for_manual_resolution(conflict_resolver_instance: ConflictResolver, mock_notification_service: MagicMock):
    conflict_data = {
        "type": "contested_resource_grab",
        "involved_players": ["playerX", "playerY"],
        "details": {"item_id": "idol_of_testing", "location": "test_shrine"},
        "status": "identified"
    }
    
    result = conflict_resolver_instance.prepare_for_manual_resolution(conflict_data)

    assert "conflict_id" in result
    conflict_id = result["conflict_id"]
    assert result["status"] == "awaiting_manual_resolution"
    assert "details_for_master" in result
    assert "playerX" in result["details_for_master"] # Check if player names are in the message
    
    assert conflict_id in conflict_resolver_instance.pending_manual_resolutions
    stored_conflict = conflict_resolver_instance.pending_manual_resolutions[conflict_id]
    assert stored_conflict["type"] == "contested_resource_grab"
    assert "master_notification_message" in stored_conflict

    # If NotificationService is a real mock object with methods
    if hasattr(mock_notification_service, 'send_master_alert') and callable(mock_notification_service.send_master_alert):
         mock_notification_service.send_master_alert.assert_called_once()
         # Can also check call arguments:
         # args, kwargs = mock_notification_service.send_master_alert.call_args
         # assert conflict_id in args[0] # Assuming message is first arg
    # If it's a string placeholder, this test part is skipped or adapted.


# --- Test process_master_resolution ---

def test_process_master_resolution_valid(conflict_resolver_instance: ConflictResolver):
    # First, prepare a conflict
    conflict_data = {
        "type": "contested_resource_grab",
        "involved_players": ["playerC", "playerD"],
        "details": {"item_id": "test_orb"}, "status": "identified"
    }
    prepared_info = conflict_resolver_instance.prepare_for_manual_resolution(conflict_data)
    conflict_id = prepared_info["conflict_id"]

    assert conflict_id in conflict_resolver_instance.pending_manual_resolutions
    
    resolution_params = {"reason": "Master deems playerC more worthy."}
    resolution_result = conflict_resolver_instance.process_master_resolution(
        conflict_id, "actor_wins", params=resolution_params
    )

    assert resolution_result["success"] is True
    assert resolution_result["message"].startswith(f"Conflict '{conflict_id}' resolved by Master")
    assert conflict_id not in conflict_resolver_instance.pending_manual_resolutions
    assert resolution_result["resolution_details"]["chosen_outcome"] == "actor_wins"
    assert resolution_result["resolution_details"]["parameters_applied"] == resolution_params

def test_process_master_resolution_invalid_id(conflict_resolver_instance: ConflictResolver):
    invalid_conflict_id = "non_existent_conflict_123"
    resolution_result = conflict_resolver_instance.process_master_resolution(
        invalid_conflict_id, "actor_wins"
    )
    assert resolution_result["success"] is False
    assert "not found" in resolution_result["message"]

# TODO: Add more tests for edge cases and different outcomes in resolve_conflict_automatically.
# TODO: If RuleEngine methods become async, update mocks to AsyncMock and use `await` in tests.
# e.g. @pytest.mark.asyncio async def test_async_method(...)
#      mock_rule_engine.resolve_check = AsyncMock(return_value=...)
#      await conflict_resolver_instance.some_async_method()

# Placeholder for async test structure if needed
# @pytest.mark.asyncio
# async def test_example_async_interaction(conflict_resolver_instance_async_deps, mock_rule_engine_async):
#     mock_rule_engine_async.resolve_check = AsyncMock(return_value=...) # Setup async mock
#     # result = await conflict_resolver_instance_async_deps.some_method_that_calls_resolve_check()
#     # assert result ...
#     pass

# To run these tests:
# Ensure pytest and pytest-asyncio (if needed) are installed:
# pip install pytest pytest-asyncio
# Then run: pytest tests/test_conflict_resolver.py
