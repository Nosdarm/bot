from typing import TypedDict, Dict, Any, Optional

class CheckResult(TypedDict):
    outcome: str  # 'success', 'fail', 'crit_success', 'crit_fail'
    roll_details: Dict[str, Any] # From dice_roller.roll_dice()
    modifier: int
    final_result: int
    dc_or_vs_result: int
    check_type: str
    succeeded: bool # True for success or crit_success
    error: Optional[str] # To pass along errors like invalid check_type

from bot.game.rules.dice_roller import roll_dice

# Placeholder for rules_config (Task 14)
MOCK_RULES_CONFIG = {
    'perception_check': {
        'dice': '1d20',
        'modifiers': ['wisdom', 'perception_skill'], # Corresponding keys in Effective_Stats
        'crit_success_threshold': 20,
        'crit_fail_threshold': 1,
        'success_on_beat_dc': True, # True if roll must beat DC, False if >= DC
        'default_dc': 15
    },
    'stealth_vs_perception': { # Example of a contested check
        'dice': '1d20',
        'modifiers': ['dexterity', 'stealth_skill'],
        'contested_by_check': 'perception_check_passive', # Target will roll this
        'crit_success_threshold': 20,
        'crit_fail_threshold': 1,
        'success_on_beat_dc': True,
    },
    'perception_check_passive': { # Passive version for contested rolls
        'dice': '1d20', # Or sometimes just 10 + modifiers
        'modifiers': ['wisdom', 'perception_skill'],
        'crit_success_threshold': 20, # Crits might not apply to passive
        'crit_fail_threshold': 1,
        'success_on_beat_dc': True, # Not really a "success", but used for comparison
        'is_passive_for_contested': True # Special flag
    },
    'simple_stat_check': {
        'dice': '1d20',
        'modifiers': ['strength'],
        'crit_success_threshold': 19,
        'crit_fail_threshold': 2,
        'success_on_beat_dc': False, # Success if roll >= DC
        'default_dc': 10
    }
}

# Placeholder for get_entity_effective_stats (Task 15)
MOCK_EFFECTIVE_STATS_DB = {
    "player_1": {"strength": 2, "dexterity": 3, "wisdom": 4, "perception_skill": 2, "stealth_skill": 5},
    "npc_1": {"strength": 1, "dexterity": 2, "wisdom": 1, "perception_skill": 1, "stealth_skill": 1},
    "player_2_high_perception": {"wisdom": 5, "perception_skill": 5}
}

def get_entity_effective_stats(entity_id: str, entity_type: str) -> Dict[str, Any]:
    # entity_type is ignored for this mock
    return MOCK_EFFECTIVE_STATS_DB.get(entity_id, {})

def resolve_check(
    check_type: str,
    entity_doing_check_id: str,
    entity_doing_check_type: str, # e.g. "player", "npc"
    target_entity_id: Optional[str] = None,
    target_entity_type: Optional[str] = None, # e.g. "player", "npc"
    difficulty_dc: Optional[int] = None,
    check_context: Optional[Dict[str, Any]] = None # For future complex modifiers
) -> CheckResult:
    """
    Resolves a skill check or contested check based on defined rules.
    """
    if check_context is None:
        check_context = {}

    if check_type not in MOCK_RULES_CONFIG:
        # Basic error handling for invalid check_type
        return {
            'outcome': 'fail',
            'roll_details': {'total': 0, 'rolls': [], 'dice_str': '', 'raw_roll': 0},
            'modifier': 0,
            'final_result': 0,
            'dc_or_vs_result': 0,
            'check_type': check_type,
            'succeeded': False,
            'error': f"Invalid check_type: {check_type}",
        }

    rule = MOCK_RULES_CONFIG[check_type]

    # 1. Fetch Effective_Stats for the entity doing the check
    entity_stats = get_entity_effective_stats(entity_doing_check_id, entity_doing_check_type)
    if not entity_stats and rule.get('modifiers'): # only error if modifiers are expected
        return {
            'outcome': 'fail',
            'roll_details': {'total': 0, 'rolls': [], 'dice_str': rule['dice'], 'raw_roll': 0},
            'modifier': 0,
            'final_result': 0,
            'dc_or_vs_result': difficulty_dc or rule.get('default_dc', 10),
            'check_type': check_type,
            'succeeded': False,
            'error': f"Stats not found for entity: {entity_doing_check_id}",
        }

    # 2. Calculate total modifier
    total_modifier = 0
    for mod_key in rule.get('modifiers', []):
        total_modifier += entity_stats.get(mod_key, 0)

    # Contextual modifiers (future)
    # if 'context_modifiers' in rule:
    #     for mod_info in rule['context_modifiers']:
    #         if check_context.get(mod_info['context_key']):
    #             total_modifier += mod_info['bonus']

    # 3. Roll dice
    dice_formula = rule['dice']
    try:
        roll_total_from_dice, individual_rolls = roll_dice(dice_formula)
    except ValueError as e: # Catch errors from dice_roller (e.g. invalid format)
        return {
            'outcome': 'fail',
            'roll_details': {'total': 0, 'rolls': [], 'dice_str': dice_formula, 'raw_roll': 0, 'error': str(e)},
            'modifier': total_modifier,
            'final_result': total_modifier, # result is just modifier if roll fails
            'dc_or_vs_result': difficulty_dc or rule.get('default_dc', 10),
            'check_type': check_type,
            'succeeded': False,
            'error': f"Dice roll failed: {e}"
        }

    roll_details_constructed = {
        'total': roll_total_from_dice, # This total is from dice_roller, includes internal modifiers if any in dice_string
        'rolls': individual_rolls,
        'dice_str': dice_formula
    }

    # Determine raw_roll for crit checks (typically the first d20 roll)
    raw_roll_value_for_crit = None
    if "1d20" in dice_formula.split('+')[0].split('-')[0] and individual_rolls: # Check base dice is 1d20
        raw_roll_value_for_crit = individual_rolls[0]

    roll_details_constructed['raw_roll'] = raw_roll_value_for_crit

    # 4. Calculate final result
    # The roll_total_from_dice already includes modifiers from the dice_string (e.g., 1d20+1)
    # The total_modifier here is for stats/skills.
    final_result = roll_total_from_dice + total_modifier

    # 5. Determine DC or VS Result
    actual_dc_or_vs_result: int
    is_contested_check = False

    if difficulty_dc is not None:
        actual_dc_or_vs_result = difficulty_dc
    elif rule.get('contested_by_check') and target_entity_id and target_entity_type:
        is_contested_check = True
        contested_check_type = rule['contested_by_check']

        # For contested roll, target rolls its check.
        # DC for target's check is simplified here. Could be player's current result, or a fixed value.
        # For now, let's assume the target is rolling against a general "awareness" or fixed DC (e.g. 10),
        # or its result becomes the DC for the original checker.
        # The current implementation: target's final_result becomes the DC for entity_doing_check.

        # Simplified: target's check doesn't have its own DC here, it just generates a result.
        target_check_result = resolve_check(
            check_type=contested_check_type,
            entity_doing_check_id=target_entity_id,
            entity_doing_check_type=target_entity_type,
            difficulty_dc=None, # Target isn't rolling against a DC, they are setting it.
            check_context=check_context # Pass context along
        )
        actual_dc_or_vs_result = target_check_result['final_result']
    else:
        actual_dc_or_vs_result = rule.get('default_dc', 10) # Fallback DC

    # 6. Determine outcome
    outcome: str
    succeeded: bool

    crit_success_threshold = rule.get('crit_success_threshold')
    crit_fail_threshold = rule.get('crit_fail_threshold')

    # Check for critical success/failure based on the raw d20 roll (if applicable)
    if raw_roll_value_for_crit is not None: # Indicates it was a 1d20 roll suitable for this crit logic
        if crit_success_threshold is not None and raw_roll_value_for_crit >= crit_success_threshold:
            outcome = 'crit_success'
            succeeded = True
        elif crit_fail_threshold is not None and raw_roll_value_for_crit <= crit_fail_threshold:
            outcome = 'crit_fail'
            succeeded = False
        else: # Not a critical based on raw roll, proceed to compare with DC
            if rule.get('success_on_beat_dc', True): # Must beat DC
                succeeded = final_result > actual_dc_or_vs_result
            else: # Meets or beats DC
                succeeded = final_result >= actual_dc_or_vs_result
            outcome = 'success' if succeeded else 'fail'
    else: # Not a 1d20 roll suitable for d20-style crits, or crit thresholds not applicable
        if rule.get('success_on_beat_dc', True):
            succeeded = final_result > actual_dc_or_vs_result
        else:
            succeeded = final_result >= actual_dc_or_vs_result
        outcome = 'success' if succeeded else 'fail'

    # Passive checks for contested rolls don't typically have "success/fail" in the same way,
    # their result is just used as a DC. But for consistency, we'll assign one.
    # This section might need more refinement if 'is_passive_for_contested' has further implications.
    # if rule.get('is_passive_for_contested'):
    #     pass


    return {
        'outcome': outcome,
        'roll_details': roll_details_constructed,
        'modifier': total_modifier,
        'final_result': final_result,
        'dc_or_vs_result': actual_dc_or_vs_result,
        'check_type': check_type,
        'succeeded': succeeded,
        'error': None # No error in this path
    }

if __name__ == '__main__':
    # Now using the actual roll_dice from dice_roller module
    # The examples will be non-deterministic due to random rolls.
    # Assertions will need to be more about structure and less about specific values unless we can control the seed.

    print("--- Check Resolver Examples (using actual dice_roller) ---")

    # Example 1: Simple Perception Check against default DC
    print("\nExample 1: Simple Perception Check (Default DC)")
    # Player_1 stats: wisdom: 4, perception_skill: 2. Modifier = 6
    # Rule: 1d20, default_dc: 15.
    # Expected: final_result = (1d20 roll) + 6. Outcome depends on roll vs 15.
    result1 = resolve_check(
        check_type='perception_check',
        entity_doing_check_id='player_1',
        entity_doing_check_type='player'
    )
    print(f"Result 1: {result1}")
    assert result1['check_type'] == 'perception_check'
    assert result1['modifier'] == 6
    assert result1['dc_or_vs_result'] == 15
    assert result1['final_result'] == result1['roll_details']['total'] + result1['modifier']
    if result1['roll_details']['raw_roll'] is not None: # Check if it was a 1d20 roll
        if result1['roll_details']['raw_roll'] >= MOCK_RULES_CONFIG['perception_check']['crit_success_threshold']:
            assert result1['outcome'] == 'crit_success'
        elif result1['roll_details']['raw_roll'] <= MOCK_RULES_CONFIG['perception_check']['crit_fail_threshold']:
            assert result1['outcome'] == 'crit_fail'
        elif result1['succeeded']:
            assert result1['outcome'] == 'success'
        else:
            assert result1['outcome'] == 'fail'


    # Example 2: Perception Check against a specified DC (e.g., very high DC)
    print("\nExample 2: Perception Check (Specified High DC 25)")
    # Player_1 stats: wisdom: 4, perception_skill: 2. Modifier = 6
    # Rule: 1d20. DC: 25.
    # Expected: Most likely a fail unless a high roll or crit success.
    result2 = resolve_check(
        check_type='perception_check',
        entity_doing_check_id='player_1',
        entity_doing_check_type='player',
        difficulty_dc=25
    )
    print(f"Result 2: {result2}")
    assert result2['dc_or_vs_result'] == 25
    print(f"Player 1 (mod {result2['modifier']}) rolled {result2['roll_details']['rolls'][0]}, total {result2['roll_details']['total']}. Final: {result2['final_result']}. Outcome: {result2['outcome']}")


    # Example 3: Contested Check (Stealth vs Perception)
    # Player 1 (Stealth): dexterity: 3, stealth_skill: 5. Modifier = 8
    # NPC 1 (Perception for contested roll): wisdom: 1, perception_skill: 1. Modifier = 2
    # Expected: Player 1 rolls 1d20+8. NPC 1 rolls 1d20+2. Player 1 wins if their result > NPC 1's result.
    print("\nExample 3: Contested Stealth vs Perception")
    result3 = resolve_check(
        check_type='stealth_vs_perception',
        entity_doing_check_id='player_1', # Stealth
        entity_doing_check_type='player',
        target_entity_id='npc_1',        # Perception
        target_entity_type='npc'
    )
    print(f"Result 3: {result3}")
    # Player 1 (Stealth) details
    print(f"  Stealth (Player 1): Roll {result3['roll_details']['rolls'][0]} + Mod {result3['modifier']} = Final {result3['final_result']}")
    # The DC was the target's (NPC_1) perception roll result.
    # To see NPC_1's roll, we'd need to inspect the recursive call, which isn't directly returned.
    # However, dc_or_vs_result IS npc_1's perception final_result.
    print(f"  Perception DC (NPC 1's result): {result3['dc_or_vs_result']}")
    assert result3['check_type'] == 'stealth_vs_perception'
    assert result3['modifier'] == 8 # Player 1's stealth modifier

    # Example 4: A check that is likely to succeed (low DC)
    print("\nExample 4: Likely Success (Simple Stat Check vs DC 5)")
    # Player_1 stats: strength: 2. Modifier = 2
    # Rule: simple_stat_check, 1d20, default_dc: 10. success_on_beat_dc: False (>=)
    # Using DC 5 for high chance of success.
    result4 = resolve_check(
        check_type='simple_stat_check',
        entity_doing_check_id='player_1',
        entity_doing_check_type='player',
        difficulty_dc=5
    )
    print(f"Result 4: {result4}")
    assert result4['dc_or_vs_result'] == 5
    if result4['outcome'] not in ['crit_success', 'success']:
        print(f"  Unexpected fail/crit_fail: Roll {result4['roll_details']['rolls'][0]} + Mod {result4['modifier']} = {result4['final_result']}")
    assert result4['succeeded'] is True or result4['outcome'] == 'crit_success'


    # Example 5: A check that is likely to fail (high DC)
    print("\nExample 5: Likely Fail (Simple Stat Check vs DC 25)")
    # Player_1 stats: strength: 2. Modifier = 2
    # Rule: simple_stat_check, 1d20.
    # Using DC 25 for high chance of failure.
    result5 = resolve_check(
        check_type='simple_stat_check',
        entity_doing_check_id='player_1',
        entity_doing_check_type='player',
        difficulty_dc=25
    )
    print(f"Result 5: {result5}")
    assert result5['dc_or_vs_result'] == 25
    if result5['outcome'] not in ['crit_fail', 'fail']:
         print(f"  Unexpected success/crit_success: Roll {result5['roll_details']['rolls'][0]} + Mod {result5['modifier']} = {result5['final_result']}")
    assert result5['succeeded'] is False or result5['outcome'] == 'crit_fail'

    print("\n--- End of Examples ---")
    print("Note: Outcomes are probabilistic due to random dice rolls.")
    print("Run multiple times to observe different results including natural crits if dice_roller produces them for 1d20.")

```
