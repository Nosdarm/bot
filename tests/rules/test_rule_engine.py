import pytest
import asyncio # For async test functions
from unittest.mock import MagicMock, AsyncMock, patch # For mocking

# Models and Enums to test
from bot.game.models.check_models import CheckOutcome, DetailedCheckResult
from bot.game.models.character import Character # Assuming Character model for entity_obj
from bot.game.models.npc import NPC # Assuming NPC model for entity_obj

# Class to test
from bot.game.rules.rule_engine import RuleEngine

# Managers that RuleEngine might interact with (even if mocked)
# from bot.game.managers.character_manager import CharacterManager
# from bot.game.managers.npc_manager import NpcManager

# Default rules_data for testing
DEFAULT_TEST_RULES_DATA = {
    "checks": {
        "SimpleSuccessCheck": {
            "roll_formula": "1d20",
            "default_dc": 10,
            "critical_success_roll": 20,
            "critical_failure_roll": 1,
            "modifier_sources": [] # No modifiers for this simple check
        },
        "SimpleFailureCheck": {
            "roll_formula": "1d20",
            "default_dc": 15,
            "critical_success_roll": 20,
            "critical_failure_roll": 1,
            "modifier_sources": []
        },
        "AttackRoll_Hit": {
            "roll_formula": "1d20",
            "modifier_sources": [{"type": "stat_bonus", "stat": "strength", "scale": 1}], # Example
            "opposed_by": {"type": "stat", "stat": "armor_class", "source": "target"},
            "critical_success_roll": 20,
            "critical_failure_roll": 1
        },
        "AttackRoll_Miss": {
            "roll_formula": "1d20",
            "modifier_sources": [{"type": "stat_bonus", "stat": "strength", "scale": 1}],
            "opposed_by": {"type": "stat", "stat": "armor_class", "source": "target"},
            "critical_success_roll": 20,
            "critical_failure_roll": 1
        },
        "StealthVsPerception": {
            "roll_formula": "1d20",
            "modifier_sources": [{"type": "skill", "skill": "stealth"}],
            "opposed_by": {"type": "check", "check_type": "PerceptionCheck", "source": "target"},
            "critical_success_margin": 5,
            "critical_failure_margin": -5 # Or "absolute_margin_failure": 5
        },
        "PerceptionCheck": { # For the opposed part of StealthVsPerception
            "roll_formula": "1d20",
            "modifier_sources": [{"type": "skill", "skill": "perception"}],
            "uses_dc": True # This implies it can be rolled against a DC if not opposed directly
        },
        "CritSuccessMarginCheck": {
            "roll_formula": "1d20",
            "default_dc": 10,
            "critical_success_roll": 19, # Natural 19 or 20 is crit
            "critical_success_margin": 5, # Also crit if roll beats DC by 5+
            "modifier_sources": []
        },
        "CritFailureMarginCheck": {
            "roll_formula": "1d20",
            "default_dc": 15,
            "critical_failure_roll": 2, # Natural 1 or 2 is crit fail
            "critical_failure_margin": -5, # Also crit fail if roll is 5+ below DC
            "modifier_sources": []
        }
    },
    "stats_config": { # Example stats for modifier calculations
        "strength": {"default": 10},
        "dexterity": {"default": 10},
        "armor_class": {"default": 10}
    },
    "skills_config": { # Example skills
        "stealth": {"default_value": 0},
        "perception": {"default_value": 0}
    }
}


@pytest.fixture
def rule_engine_instance():
    # Create a RuleEngine instance with mocked dependencies if necessary
    # For now, assume CharacterManager and NpcManager are used by _get_entity_data_for_check
    mock_char_manager = MagicMock()
    mock_npc_manager = MagicMock()
    
    engine = RuleEngine(
        settings={'rules_data': DEFAULT_TEST_RULES_DATA},
        character_manager=mock_char_manager,
        npc_manager=mock_npc_manager
    )
    # engine._rules_data = DEFAULT_TEST_RULES_DATA # Ensure rules_data is set
    return engine

@pytest.mark.asyncio
async def test_resolve_check_simple_success_fixed_roll(rule_engine_instance: RuleEngine):
    # Mock the internal dice roll to control the outcome
    with patch.object(rule_engine_instance, 'resolve_dice_roll', new_callable=AsyncMock) as mock_dice_roll:
        mock_dice_roll.return_value = {'rolls': [15], 'total': 15, 'num_dice': 1, 'dice_sides': 20, 'modifier': 0}

        # Mock _get_entity_data_for_check to return minimal data as it's not used by SimpleSuccessCheck modifiers
        with patch.object(rule_engine_instance, '_get_entity_data_for_check', new_callable=AsyncMock) as mock_get_entity:
            mock_get_entity.return_value = {
                "id": "player1", "type": "Character", "stats": {}, "skills": {}, 
                "status_effects": [], "inventory": [], "name": "Player One",
                "current_hp": 10, "max_hp": 10, "is_alive": True
            }

            result = await rule_engine_instance.resolve_check(
                check_type="SimpleSuccessCheck",
                entity_doing_check_id="player1",
                entity_doing_check_type="Character",
                context={'guild_id': 'test_guild'}
            )

            assert result.outcome == CheckOutcome.SUCCESS
            assert result.is_success is True
            assert result.is_critical is False
            assert result.total_roll_value == 15
            assert result.target_value == 10 # default_dc for SimpleSuccessCheck

@pytest.mark.asyncio
async def test_resolve_check_simple_failure_fixed_roll(rule_engine_instance: RuleEngine):
    with patch.object(rule_engine_instance, 'resolve_dice_roll', new_callable=AsyncMock) as mock_dice_roll:
        mock_dice_roll.return_value = {'rolls': [5], 'total': 5} # num_dice, etc. are not strictly needed by resolve_check itself for this test

        with patch.object(rule_engine_instance, '_get_entity_data_for_check', new_callable=AsyncMock) as mock_get_entity:
            mock_get_entity.return_value = {"id": "player1", "type": "Character", "stats": {}, "skills": {}} # Minimal

            result = await rule_engine_instance.resolve_check(
                check_type="SimpleFailureCheck", # DC 15
                entity_doing_check_id="player1",
                entity_doing_check_type="Character",
                context={'guild_id': 'test_guild'}
            )

            assert result.outcome == CheckOutcome.FAILURE
            assert result.is_success is False
            assert result.is_critical is False
            assert result.total_roll_value == 5
            assert result.target_value == 15

@pytest.mark.asyncio
async def test_resolve_check_critical_success_roll(rule_engine_instance: RuleEngine):
    with patch.object(rule_engine_instance, 'resolve_dice_roll', new_callable=AsyncMock) as mock_dice_roll:
        mock_dice_roll.return_value = {'rolls': [20], 'total': 20}
        with patch.object(rule_engine_instance, '_get_entity_data_for_check', new_callable=AsyncMock) as mock_get_entity:
            mock_get_entity.return_value = {"id": "player1", "type": "Character", "stats": {}, "skills": {}}

            result = await rule_engine_instance.resolve_check(
                check_type="SimpleSuccessCheck", # DC 10, Crit Success 20
                entity_doing_check_id="player1",
                entity_doing_check_type="Character",
                context={'guild_id': 'test_guild'}
            )
            assert result.outcome == CheckOutcome.CRITICAL_SUCCESS
            assert result.is_success is True
            assert result.is_critical is True
            assert result.total_roll_value == 20

@pytest.mark.asyncio
async def test_resolve_check_critical_failure_roll(rule_engine_instance: RuleEngine):
    with patch.object(rule_engine_instance, 'resolve_dice_roll', new_callable=AsyncMock) as mock_dice_roll:
        mock_dice_roll.return_value = {'rolls': [1], 'total': 1}
        with patch.object(rule_engine_instance, '_get_entity_data_for_check', new_callable=AsyncMock) as mock_get_entity:
            mock_get_entity.return_value = {"id": "player1", "type": "Character", "stats": {}, "skills": {}}

            result = await rule_engine_instance.resolve_check(
                check_type="SimpleSuccessCheck", # DC 10, Crit Fail 1
                entity_doing_check_id="player1",
                entity_doing_check_type="Character",
                context={'guild_id': 'test_guild'}
            )
            assert result.outcome == CheckOutcome.CRITICAL_FAILURE
            assert result.is_success is False
            assert result.is_critical is True
            assert result.total_roll_value == 1

@pytest.mark.asyncio
async def test_resolve_check_attack_roll_hit_with_modifier(rule_engine_instance: RuleEngine):
    # Mock _get_entity_data_for_check to provide stats for attacker and target
    async def mock_get_entity_data_side_effect(entity_id, entity_type, requested_keys, context):
        if entity_id == "attacker":
            return {"id": "attacker", "type": "Character", "stats": {"strength": 16}, "skills": {}} # STR mod +3
        elif entity_id == "target":
            return {"id": "target", "type": "NPC", "stats": {"armor_class": 12}, "skills": {}}
        return {}

    with patch.object(rule_engine_instance, '_get_entity_data_for_check', side_effect=mock_get_entity_data_side_effect) as mock_get_entity:
        with patch.object(rule_engine_instance, 'resolve_dice_roll', new_callable=AsyncMock) as mock_dice_roll:
            mock_dice_roll.return_value = {'rolls': [10], 'total': 10} # Roll 10

            # This test will use the placeholder modifier logic in resolve_check for now.
            # The placeholder modifier is 0. So 10 (roll) + 0 (placeholder mod) = 10. Target AC is 12. This should be a miss.
            # Once modifier logic is implemented, this test will need to be updated.
            # For now, let's adjust expectation or the test to reflect placeholder state.
            # Expected: roll 10 + 0 (placeholder) = 10. AC 12. Miss.
            # If we assume modifier_sources IS partially processed by placeholder:
            # "modifier_sources": [{"type": "stat_bonus", "stat": "strength", "scale": 1}]
            # The current placeholder in resolve_check does:
            # calculated_modifier = 0
            # modifier_details_dict = {"placeholder_bonus": 0, "sources": check_config.get('modifier_sources', [])}
            # So, calculated_modifier will indeed be 0.

            result = await rule_engine_instance.resolve_check(
                check_type="AttackRoll_Hit", # Uses strength mod, opposed by AC
                entity_doing_check_id="attacker",
                entity_doing_check_type="Character",
                target_entity_id="target",
                target_entity_type="NPC",
                context={'guild_id': 'test_guild'}
            )
            
            # With placeholder modifier logic (modifier_applied = 0):
            # Roll 10 + 0 = 10. Target AC = 12. Expected: Miss.
            assert result.total_roll_value == 10 
            assert result.modifier_applied == 0 # Placeholder behavior
            assert result.target_value == 12 # Target's AC
            assert result.is_success is False
            assert result.outcome == CheckOutcome.FAILURE

@pytest.mark.asyncio
async def test_resolve_check_unsupported_check_type(rule_engine_instance: RuleEngine):
    with patch.object(rule_engine_instance, '_get_entity_data_for_check', new_callable=AsyncMock) as mock_get_entity:
        mock_get_entity.return_value = {"id": "player1", "type": "Character", "stats": {}, "skills": {}}
    
        result = await rule_engine_instance.resolve_check(
            check_type="NonExistentCheck",
            entity_doing_check_id="player1",
            entity_doing_check_type="Character",
            context={'guild_id': 'test_guild'}
        )
        assert result.outcome == CheckOutcome.FAILURE # Default for errors
        assert "Unsupported check_type: NonExistentCheck" in result.description
        assert result.is_success is False

@pytest.mark.asyncio
async def test_resolve_check_crit_success_by_margin(rule_engine_instance: RuleEngine):
    rule_engine_instance._rules_data["checks"]["CritSuccessMarginCheck"]["critical_success_roll"] = 20 # Natural 20 only for this test part
    
    with patch.object(rule_engine_instance, 'resolve_dice_roll', new_callable=AsyncMock) as mock_dice_roll:
        mock_dice_roll.return_value = {'rolls': [14], 'total': 14} # Roll 14. DC 10. Margin 5. (14-10=4, not enough for margin crit)
        with patch.object(rule_engine_instance, '_get_entity_data_for_check', new_callable=AsyncMock) as mock_get_entity:
            mock_get_entity.return_value = {"id": "player1", "type": "Character", "stats": {}, "skills": {}}

            result_normal_success = await rule_engine_instance.resolve_check(
                check_type="CritSuccessMarginCheck",
                entity_doing_check_id="player1",
                entity_doing_check_type="Character",
                context={'guild_id': 'test_guild'}
            )
            assert result_normal_success.outcome == CheckOutcome.SUCCESS
            assert result_normal_success.is_critical is False
            assert result_normal_success.total_roll_value == 14

        mock_dice_roll.return_value = {'rolls': [15], 'total': 15} # Roll 15. DC 10. Margin 5. (15-10=5, IS a margin crit)
        with patch.object(rule_engine_instance, '_get_entity_data_for_check', new_callable=AsyncMock) as mock_get_entity:
            mock_get_entity.return_value = {"id": "player1", "type": "Character", "stats": {}, "skills": {}}
            result_crit_success = await rule_engine_instance.resolve_check(
                check_type="CritSuccessMarginCheck",
                entity_doing_check_id="player1",
                entity_doing_check_type="Character",
                context={'guild_id': 'test_guild'}
            )
            assert result_crit_success.outcome == CheckOutcome.CRITICAL_SUCCESS
            assert result_crit_success.is_critical is True
            assert result_crit_success.total_roll_value == 15

@pytest.mark.asyncio
async def test_resolve_check_input_difficulty_dc_used(rule_engine_instance: RuleEngine):
    with patch.object(rule_engine_instance, 'resolve_dice_roll', new_callable=AsyncMock) as mock_dice_roll:
        mock_dice_roll.return_value = {'rolls': [12], 'total': 12}
        with patch.object(rule_engine_instance, '_get_entity_data_for_check', new_callable=AsyncMock) as mock_get_entity:
            mock_get_entity.return_value = {"id": "player1", "type": "Character", "stats": {}, "skills": {}}

            result = await rule_engine_instance.resolve_check(
                check_type="SimpleSuccessCheck", # Default DC is 10
                entity_doing_check_id="player1",
                entity_doing_check_type="Character",
                difficulty_dc=15, # Override with 15
                context={'guild_id': 'test_guild'}
            )
            assert result.target_value == 15 # Should use the provided DC
            assert result.difficulty_dc == 15 # Ensure it's stored
            assert result.is_success is False # 12 vs 15
            assert result.outcome == CheckOutcome.FAILURE

# TODO: Add tests for opposed checks once the logic for `opposed_by: {"type": "check"}` is more than a placeholder.
# TODO: Add tests that verify actual modifier calculation once that part of `resolve_check` is implemented.
