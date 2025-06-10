from typing import TypedDict, Dict, Any, Optional, List # Added List
from bot.game.rules.dice_roller import roll_dice
from bot.ai.rules_schema import CoreGameRulesConfig, CheckDefinition # Import new schema

class CheckResult(TypedDict):
    outcome: str  # 'success', 'fail', 'crit_success', 'crit_fail'
    roll_details: Dict[str, Any]
    modifier: int
    final_result: int
    dc_or_vs_result: int
    check_type: str
    succeeded: bool
    error: Optional[str]

# Placeholder for get_entity_effective_stats (Task 15)
# Updated to provide stats that will be used in example CheckDefinitions
MOCK_EFFECTIVE_STATS_DB = {
    "player_1": {"strength": 2, "dexterity": 3, "wisdom": 14, "perception": 2, "stealth": 5, "athletics": 3}, # Using "perception" and "stealth" as skill names
    "npc_1": {"strength": 1, "dexterity": 12, "wisdom": 10, "perception": 1, "stealth": 1},
    "player_2_high_perception": {"wisdom": 18, "perception": 5} # Example for opposed checks
}

def get_entity_effective_stats(entity_id: str, entity_type: str) -> Dict[str, Any]:
    # entity_type is ignored for this mock
    # In a real scenario, this would fetch from CharacterManager or similar
    return MOCK_EFFECTIVE_STATS_DB.get(entity_id, {})

def resolve_check(
    rules_config_data: CoreGameRulesConfig, # Changed from check_type: str
    check_type: str,
    entity_doing_check_id: str,
    entity_doing_check_type: str,
    target_entity_id: Optional[str] = None,
    target_entity_type: Optional[str] = None,
    difficulty_dc: Optional[int] = None,
    check_context: Optional[Dict[str, Any]] = None
) -> CheckResult:
    if check_context is None:
        check_context = {}

    if check_type not in rules_config_data.checks:
        return {
            'outcome': 'fail', 'roll_details': {'total': 0, 'rolls': [], 'dice_str': '', 'raw_roll': 0, 'error': 'Invalid check type'},
            'modifier': 0, 'final_result': 0, 'dc_or_vs_result': 0,
            'check_type': check_type, 'succeeded': False, 'error': f"Invalid check_type: {check_type}"
        }

    rule: CheckDefinition = rules_config_data.checks[check_type]

    entity_stats = get_entity_effective_stats(entity_doing_check_id, entity_doing_check_type)

    # Error if essential stats are missing for defined modifiers
    if not entity_stats and rule.affected_by_stats:
        return {
            'outcome': 'fail', 'roll_details': {'total': 0, 'rolls': [], 'dice_str': rule.dice_formula, 'raw_roll': 0, 'error': 'Entity stats not found'},
            'modifier': 0, 'final_result': 0,
            'dc_or_vs_result': difficulty_dc or rule.base_dc or 10, # Use rule.base_dc
            'check_type': check_type, 'succeeded': False, 'error': f"Stats not found for entity: {entity_doing_check_id}"
        }

    total_modifier = 0
    for stat_key in rule.affected_by_stats:
        total_modifier += entity_stats.get(stat_key, 0)

    dice_formula = rule.dice_formula # Modifiers from stats are separate from dice_formula intrinsic modifiers

    try:
        roll_total_from_dice, individual_rolls = roll_dice(dice_formula)
    except ValueError as e:
        return {
            'outcome': 'fail',
            'roll_details': {'total': 0, 'rolls': [], 'dice_str': dice_formula, 'raw_roll': 0, 'error': str(e)},
            'modifier': total_modifier, 'final_result': total_modifier,
            'dc_or_vs_result': difficulty_dc or rule.base_dc or 10,
            'check_type': check_type, 'succeeded': False, 'error': f"Dice roll failed: {e}"
        }

    roll_details_constructed = {
        'total': roll_total_from_dice,
        'rolls': individual_rolls, 'dice_str': dice_formula
    }

    raw_roll_value_for_crit = None
    # Assuming crit checks are mainly for 1d20 based rolls.
    # The dice_formula itself might be "1d20+STR_mod", so check base die.
    # A simple check: if "1d20" is the start of the formula (ignoring potential character sheet modifiers in formula)
    if rule.dice_formula.startswith("1d20") and individual_rolls:
        raw_roll_value_for_crit = individual_rolls[0]
    roll_details_constructed['raw_roll'] = raw_roll_value_for_crit

    final_result = roll_total_from_dice + total_modifier

    actual_dc_or_vs_result: int
    if difficulty_dc is not None:
        actual_dc_or_vs_result = difficulty_dc
    elif rule.opposed_check_type and target_entity_id and target_entity_type:
        # Pass the full rules_config_data for recursive calls
        target_check_result = resolve_check(
            rules_config_data=rules_config_data,
            check_type=rule.opposed_check_type,
            entity_doing_check_id=target_entity_id,
            entity_doing_check_type=target_entity_type,
            difficulty_dc=None,
            check_context=check_context
        )
        # If the target check itself had an error, this might need handling.
        # For now, assume it returns a valid CheckResult and use its final_result.
        actual_dc_or_vs_result = target_check_result['final_result']
    elif rule.base_dc is not None:
        actual_dc_or_vs_result = rule.base_dc
    else:
        actual_dc_or_vs_result = 10 # Fallback default DC if no other DC is specified

    outcome: str
    succeeded: bool

    if raw_roll_value_for_crit is not None:
        if rule.crit_success_threshold is not None and raw_roll_value_for_crit >= rule.crit_success_threshold:
            outcome = 'crit_success'
            succeeded = True
        elif rule.crit_fail_threshold is not None and raw_roll_value_for_crit <= rule.crit_fail_threshold:
            outcome = 'crit_fail'
            succeeded = False
        else:
            succeeded = final_result > actual_dc_or_vs_result if rule.success_on_beat_dc else final_result >= actual_dc_or_vs_result
            outcome = 'success' if succeeded else 'fail'
    else:
        succeeded = final_result > actual_dc_or_vs_result if rule.success_on_beat_dc else final_result >= actual_dc_or_vs_result
        outcome = 'success' if succeeded else 'fail'

    return {
        'outcome': outcome, 'roll_details': roll_details_constructed, 'modifier': total_modifier,
        'final_result': final_result, 'dc_or_vs_result': actual_dc_or_vs_result,
        'check_type': check_type, 'succeeded': succeeded, 'error': None
    }

if __name__ == '__main__':
    # Sample CoreGameRulesConfig data
    sample_rules_data = {
        "checks": {
            "perception": {
                "dice_formula": "1d20",
                "base_dc": 15,
                "affected_by_stats": ["wisdom", "perception"],
                "crit_success_threshold": 20,
                "crit_fail_threshold": 1,
                "success_on_beat_dc": True
            },
            "stealth_vs_perception": {
                "dice_formula": "1d20",
                "affected_by_stats": ["dexterity", "stealth"],
                "opposed_check_type": "perception", # Opposed by a "perception" check
                "crit_success_threshold": 20,
                "crit_fail_threshold": 1,
                "success_on_beat_dc": True
            },
            "athletics_check_ge": { # Success on Greater Than or Equal
                "dice_formula": "1d20",
                "affected_by_stats": ["strength", "athletics"],
                "base_dc": 10,
                "crit_success_threshold": 19,
                "crit_fail_threshold": 2,
                "success_on_beat_dc": False
            }
        },
        "damage_types": {}, "xp_rules": None, "loot_tables": {},
        "action_conflicts": [], "location_interactions": {}
    }
    game_rules = CoreGameRulesConfig.parse_obj(sample_rules_data)

    print("--- Check Resolver Examples (using CoreGameRulesConfig) ---")

    print("\nExample 1: Simple Perception Check (DC 15 from rules)")
    # Player_1 stats: wisdom: 14, perception: 2. Modifier = (14-10)/2 + 2 = 2 + 2 = 4 (assuming D&D 5e style stat mod)
    # For simplicity, MOCK_EFFECTIVE_STATS_DB stores direct modifiers for now.
    # Player_1: wisdom: 14, perception: 2. Let's say MOCK_EFFECTIVE_STATS_DB stores these as direct bonuses:
    # "player_1": {"wisdom": 2, "perception": 2} => total_modifier = 4
    # If MOCK_EFFECTIVE_STATS_DB stores raw stats: "player_1": {"wisdom_raw": 14, "perception_skill_bonus": 2}
    # The get_entity_effective_stats would need to convert raw stats to modifiers.
    # For this test, assume MOCK_EFFECTIVE_STATS_DB provides direct bonuses:
    # "player_1": {"wisdom": 2, "perception": 2} => total_modifier = 4
    # If "wisdom" and "perception" are direct bonus values:
    # Player_1: wisdom=2, perception=2. Total Mod = 4.
    # (Updating MOCK_EFFECTIVE_STATS_DB for clarity)
    MOCK_EFFECTIVE_STATS_DB["player_1"] = {"wisdom": 2, "perception": 3, "dexterity": 1, "stealth": 2, "strength": 0, "athletics": 1}
    MOCK_EFFECTIVE_STATS_DB["npc_1"] = {"wisdom": 0, "perception": 1, "dexterity": 2, "stealth": 3}


    result1 = resolve_check(
        rules_config_data=game_rules,
        check_type='perception',
        entity_doing_check_id='player_1',
        entity_doing_check_type='player'
    )
    print(f"Result 1 (Perception): {result1}")
    # Assertions based on player_1 stats (wisdom:2, perception:3 => mod:5) and perception rule (DC15)
    assert result1['check_type'] == 'perception'
    assert result1['modifier'] == 5
    assert result1['dc_or_vs_result'] == 15

    print("\nExample 2: Athletics Check against specified DC 12 (success_on_beat_dc=False)")
    result2 = resolve_check(
        rules_config_data=game_rules,
        check_type='athletics_check_ge',
        entity_doing_check_id='player_1', # strength:0, athletics:1 => mod:1
        entity_doing_check_type='player',
        difficulty_dc=12
    )
    print(f"Result 2 (Athletics DC 12): {result2}")
    assert result2['dc_or_vs_result'] == 12
    assert result2['modifier'] == 1
    # Example: if roll is 11, final = 12. 12 >= 12 is success.
    # If roll is 10, final = 11. 11 >= 12 is fail.
    if result2['final_result'] >= 12 : assert result2['succeeded'] is True or result2['outcome'] == 'crit_success'
    else: assert result2['succeeded'] is False or result2['outcome'] == 'crit_fail'


    print("\nExample 3: Contested Stealth vs Perception")
    # Player 1 (Stealth): dexterity:1, stealth:2 => mod:3
    # NPC 1 (Perception): wisdom:0, perception:1 => mod:1
    result3 = resolve_check(
        rules_config_data=game_rules,
        check_type='stealth_vs_perception',
        entity_doing_check_id='player_1',
        entity_doing_check_type='player',
        target_entity_id='npc_1',
        target_entity_type='npc'
    )
    print(f"Result 3 (Stealth vs Perception): {result3}")
    print(f"  Stealth (Player 1): Roll {result3['roll_details']['rolls'][0]} + Mod {result3['modifier']} = Final {result3['final_result']}")
    print(f"  Perception DC (NPC 1's result): {result3['dc_or_vs_result']}")
    assert result3['check_type'] == 'stealth_vs_perception'
    assert result3['modifier'] == 3 # Player 1's stealth modifier
    # DC is NPC_1's perception check (1d20 + mod 1)

    print("\n--- End of Examples ---")
    print("Note: Outcomes are probabilistic. Examine roll details and logic.")
