import random
from typing import List, Optional, Dict, Any, TYPE_CHECKING

# Assuming these models and managers exist and are importable.
# For subtask environment, direct imports might be tricky.
# Fallback to TYPE_CHECKING if full objects are not needed for function signature.
if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.game_log_manager import GameLogManager
    # from bot.game.models.character import Character
    # from bot.game.models.npc import NPC

from bot.game.models.check_models import DetailedCheckResult, CheckOutcome

def _roll_dice_simple(dice_str: str) -> int:
    # Very simple parser for NdX+M or NdX-M or NdX
    dice_str = dice_str.replace(" ", "").lower()

    modifier = 0
    if '+' in dice_str:
        parts, mod_str = dice_str.split('+', 1)
        modifier = int(mod_str)
        dice_str = parts
    elif '-' in dice_str:
        parts, mod_str = dice_str.split('-', 1)
        modifier = -int(mod_str)
        dice_str = parts

    if 'd' not in dice_str: # Handle flat number like "5"
        return int(dice_str) + modifier

    num_dice_str, sides_str = dice_str.split('d', 1)
    num_dice = int(num_dice_str) if num_dice_str else 1
    sides = int(sides_str)

    if sides <= 0: raise ValueError("Dice sides must be positive.")
    if num_dice <=0: raise ValueError("Number of dice must be positive.")

    total_roll = 0
    for _ in range(num_dice):
        total_roll += random.randint(1, sides)
    return total_roll + modifier

# perform_check should already be in this file
def perform_check(
    actor_id: str,
    rules_config: Dict[str, Any], # This is settings["rules_config"]
    check_type: str,
    base_die_override: Optional[str] = None,
    modifier: int = 0,
    modifier_details: Optional[List[Dict[str, Any]]] = None,
    dc: Optional[int] = None,
    target_id: Optional[str] = None,
    opposed_roll_value: Optional[int] = None,
    opposed_roll_crit_status: Optional[str] = None
) -> DetailedCheckResult:
    if modifier_details is None:
        modifier_details = []

    result = DetailedCheckResult(
        check_type=check_type,
        entity_doing_check_id=actor_id,
        target_entity_id=target_id,
        difficulty_dc=dc,
        actor_modifier_applied=modifier,
        actor_modifier_details=modifier_details,
    )

    combat_rules = rules_config.get("combat_rules", {})
    config_key = ""

    if "attack" in check_type:
        config_key = "attack_roll"
        result.actor_roll_formula = combat_rules.get(config_key, {}).get("base_die", "1d20")
    elif "saving_throw" in check_type:
        config_key = "saving_throws"
        result.actor_roll_formula = combat_rules.get(config_key, {}).get("base_die", "1d20")
    else:
        result.actor_roll_formula = combat_rules.get("default_check_die", "1d20")

    if base_die_override:
        result.actor_roll_formula = base_die_override

    actor_raw_roll = 0
    try:
        # Using the more robust _roll_dice_simple for consistency if formula is simple enough
        # This assumes perform_check's formulas are also simple like "1d20" or "NdX"
        if 'd' in result.actor_roll_formula.lower():
             # _roll_dice_simple can handle "1d20", "2d6+3" etc.
             # For perform_check, the base_die from config is usually just "1d20".
             # If it's more complex, _roll_dice_simple might fail or misinterpret.
             # The original logic was fine for "NdX" format.
            num_dice_pd, die_type_pd = map(int, result.actor_roll_formula.lower().split('d'))
            rolls = [random.randint(1, die_type_pd) for _ in range(num_dice_pd)]
            actor_raw_roll = sum(rolls)
            result.actor_rolls = rolls
        else:
            actor_raw_roll = int(result.actor_roll_formula) # Flat number "roll"
            result.actor_rolls = [actor_raw_roll]
    except ValueError: # Fallback if parsing above failed
        try:
            actor_raw_roll = _roll_dice_simple(result.actor_roll_formula)
            result.actor_rolls = [actor_raw_roll] # _roll_dice_simple returns sum, not individual rolls for now
        except Exception as e_simple_roll:
            actor_raw_roll = random.randint(1, 20)
            result.actor_rolls = [actor_raw_roll]
            result.description = f"Note: Dice formula '{result.actor_roll_formula}' invalid ('{e_simple_roll}'), used 1d20."


    result.actor_total_roll_value = actor_raw_roll + modifier

    crit_rule_details = combat_rules.get(config_key, {})
    if not crit_rule_details and "saving_throw" in check_type:
        crit_rule_details = combat_rules.get("saving_throws", {}).get("critical_rules", {})
    if not crit_rule_details:
         crit_rule_details = combat_rules.get("critical_hit_rules", {})

    crit_success_threshold = crit_rule_details.get("crit_success_threshold", 20)
    crit_failure_threshold = crit_rule_details.get("crit_failure_threshold", 1)
    natural_20_is_always_success = crit_rule_details.get("natural_20_is_always_success", True)
    natural_1_is_always_failure = crit_rule_details.get("natural_1_is_always_failure", True)

    natural_20_wins_opposed = combat_rules.get("opposed_checks", {}).get("natural_20_auto_wins", True)
    natural_1_loses_opposed = combat_rules.get("opposed_checks", {}).get("natural_1_auto_loses", True)

    if actor_raw_roll >= crit_success_threshold:
        result.actor_crit_status = CheckOutcome.CRITICAL_SUCCESS.value
        result.is_critical = True
    elif actor_raw_roll <= crit_failure_threshold:
        result.actor_crit_status = CheckOutcome.CRITICAL_FAILURE.value
        result.is_critical = True
    else:
        result.actor_crit_status = None

    current_description = result.description if result.description else ""

    if dc is not None:
        if result.actor_crit_status == CheckOutcome.CRITICAL_SUCCESS.value and natural_20_is_always_success:
            result.is_success = True
        elif result.actor_crit_status == CheckOutcome.CRITICAL_FAILURE.value and natural_1_is_always_failure:
            result.is_success = False
        else:
            result.is_success = result.actor_total_roll_value >= dc

        if result.is_success:
            result.outcome = CheckOutcome.CRITICAL_SUCCESS if result.actor_crit_status == CheckOutcome.CRITICAL_SUCCESS.value else CheckOutcome.SUCCESS
        else:
            result.outcome = CheckOutcome.CRITICAL_FAILURE if result.actor_crit_status == CheckOutcome.CRITICAL_FAILURE.value else CheckOutcome.FAILURE
        result.description = f"{current_description}{actor_id} rolled {actor_raw_roll}({result.actor_rolls}) + {modifier} = {result.actor_total_roll_value} vs DC {dc}."

    elif opposed_roll_value is not None:
        actor_wins_on_crit_success = result.actor_crit_status == CheckOutcome.CRITICAL_SUCCESS.value and natural_20_wins_opposed
        actor_loses_on_crit_failure = result.actor_crit_status == CheckOutcome.CRITICAL_FAILURE.value and natural_1_loses_opposed

        target_crit_success = opposed_roll_crit_status == CheckOutcome.CRITICAL_SUCCESS.value and natural_20_wins_opposed
        target_crit_failure = opposed_roll_crit_status == CheckOutcome.CRITICAL_FAILURE.value and natural_1_loses_opposed

        if actor_wins_on_crit_success: result.is_success = True
        elif actor_loses_on_crit_failure: result.is_success = False
        elif target_crit_success: result.is_success = False
        elif target_crit_failure: result.is_success = True
        else:
            tie_breaker_rule = combat_rules.get("opposed_checks", {}).get("tie_breaker", "actor_wins")
            if tie_breaker_rule == "actor_wins": result.is_success = result.actor_total_roll_value >= opposed_roll_value
            elif tie_breaker_rule == "target_wins": result.is_success = result.actor_total_roll_value > opposed_roll_value
            else: result.is_success = result.actor_total_roll_value >= opposed_roll_value

        if result.is_success: result.outcome = CheckOutcome.ACTOR_WINS_OPPOSED
        elif result.actor_total_roll_value == opposed_roll_value: result.outcome = CheckOutcome.TIE_OPPOSED
        else: result.outcome = CheckOutcome.TARGET_WINS_OPPOSED
        result.description = f"{current_description}{actor_id} rolled {actor_raw_roll}({result.actor_rolls}) + {modifier} = {result.actor_total_roll_value} vs opponent's {opposed_roll_value}."
    else:
        result.outcome = CheckOutcome.INDETERMINATE
        result.is_success = False
        result.description = f"{current_description}{actor_id} rolled {actor_raw_roll}({result.actor_rolls}) + {modifier} = {result.actor_total_roll_value}. No DC or opposed roll."

    result.description += f" Outcome: {result.outcome.value}."
    if result.is_critical and result.actor_crit_status:
        result.description += f" Critical Status: {result.actor_crit_status}."
    return result

async def process_attack(
    actor_id: str, actor_type: str, target_id: str, target_type: str,
    rules_config: Dict[str, Any], character_manager: 'CharacterManager',
    npc_manager: 'NpcManager', game_log_manager: 'GameLogManager'
) -> Dict[str, Any]:
    outcome_summary = {
        "hit": False, "damage_dealt": 0.0, "target_hp_after": 0.0,
        "log_messages": [], "crit": False, "actor_id": actor_id, "target_id": target_id
    }
    log_messages = outcome_summary["log_messages"]
    guild_id = rules_config.get("guild_id", "default_guild")

    actor_entity: Optional[Any] = None
    if actor_type == "Character": actor_entity = await character_manager.get_character(guild_id, actor_id)
    elif actor_type == "NPC": actor_entity = await npc_manager.get_npc(guild_id, actor_id)

    target_entity: Optional[Any] = None
    if target_type == "Character": target_entity = await character_manager.get_character(guild_id, target_id)
    elif target_type == "NPC": target_entity = await npc_manager.get_npc(guild_id, target_id)

    if not actor_entity:
        log_messages.append(f"Attacker {actor_id} ({actor_type}) not found.")
        return outcome_summary
    if not target_entity:
        log_messages.append(f"Target {target_id} ({target_type}) not found.")
        return outcome_summary

    actor_name = getattr(actor_entity, 'name', actor_id)
    target_name = getattr(target_entity, 'name', target_id)

    combat_rules = rules_config.get("combat_rules", {})
    attack_modifier = 0
    modifier_details_list = []
    stat_bonus_config = combat_rules.get("stat_bonus_rules", {}).get("strength_modifier", {})
    actor_stats = getattr(actor_entity, 'stats', {})

    if stat_bonus_config and actor_stats:
        stat_name = stat_bonus_config.get("stat", "strength")
        stat_val = actor_stats.get(stat_name, 10)
        base_value = stat_bonus_config.get("base_value", 10)
        divisor = stat_bonus_config.get("divisor", 2)
        multiplier = stat_bonus_config.get("multiplier", 1)
        if divisor == 0: divisor = 1
        attack_modifier = int( (stat_val - base_value) / divisor * multiplier )
        modifier_details_list.append({"source": f"{stat_name}_bonus", "value": attack_modifier})
    else:
        attack_modifier = combat_rules.get("default_attack_modifier", 1)
        modifier_details_list.append({"source": "default_bonus", "value": attack_modifier})
    log_messages.append(f"{actor_name} attack modifier: {attack_modifier} ({modifier_details_list[-1]['source']}).")

    ac_config = combat_rules.get("armor_class_rules", {})
    ac_stat_name = ac_config.get("stat_name", "armor_class")
    default_ac = ac_config.get("default_ac", 10)
    target_stats = getattr(target_entity, 'stats', {})
    target_ac = target_stats.get(ac_stat_name, default_ac)
    log_messages.append(f"{target_name} {ac_stat_name}: {target_ac}.")

    attack_check_result = perform_check(
        actor_id=actor_id, rules_config=rules_config, check_type="attack_roll",
        modifier=attack_modifier, modifier_details=modifier_details_list,
        dc=target_ac, target_id=target_id
    )
    log_messages.append(attack_check_result.description)
    if attack_check_result.is_critical and attack_check_result.actor_crit_status:
        outcome_summary["crit"] = True
    await game_log_manager.add_log_entry(f"Combat: {attack_check_result.description}", "combat_details")

    if not attack_check_result.is_success:
        outcome_summary["hit"] = False
        return outcome_summary

    outcome_summary["hit"] = True
    damage_config = combat_rules.get("damage_calculation", {})
    base_damage_formula = damage_config.get("base_weapon_damage", "1d6")
    base_damage = 0
    try:
        base_damage = _roll_dice_simple(base_damage_formula)
    except Exception: # Fallback if _roll_dice_simple fails
        if 'd' in base_damage_formula:
            try:
                num_dice, die_type = map(int, base_damage_formula.lower().split('d'))
                base_damage = sum(random.randint(1, die_type) for _ in range(num_dice))
            except ValueError: base_damage = random.randint(1, 6)
        else: base_damage = int(base_damage_formula)


    damage_details = [{"source": "base_weapon", "type": "physical", "value": base_damage}]
    damage_bonus = attack_modifier
    if damage_bonus != 0: damage_details.append({"source": "stat_bonus", "type": "physical", "value": damage_bonus})
    total_damage = base_damage + damage_bonus

    if attack_check_result.actor_crit_status == CheckOutcome.CRITICAL_SUCCESS.value:
        crit_multiplier = combat_rules.get("attack_roll", {}).get("crit_success_multiplier", 2.0)
        crit_damage_bonus = total_damage * (crit_multiplier - 1.0)
        total_damage += crit_damage_bonus
        damage_details.append({"source": "critical_hit_bonus", "type": "bonus", "value": crit_damage_bonus})
        log_messages.append(f"Critical Hit bonus damage: {crit_damage_bonus:.2f}.")

    total_damage = max(0.0, float(total_damage))
    outcome_summary["damage_dealt"] = total_damage
    log_messages.append(f"Total damage: {total_damage:.2f}. Details: {damage_details}")

    target_current_hp = 0.0; new_hp = 0.0; hp_stat_name = "hp"
    if target_type == "Character":
        char_target = await character_manager.get_character(guild_id, target_id)
        if char_target:
            target_current_hp = float(getattr(char_target, 'hp', 0))
            new_hp = target_current_hp - total_damage
            await character_manager.update_character_stats(guild_id, target_id, {"hp": new_hp})
            outcome_summary["target_hp_after"] = new_hp
    elif target_type == "NPC":
        hp_stat_name = combat_rules.get("npc_health_stat_name", "health")
        npc_target = await npc_manager.get_npc(guild_id, target_id)
        if npc_target:
            target_current_hp = float(getattr(npc_target, hp_stat_name, 0))
            new_hp = target_current_hp - total_damage
            await npc_manager.update_npc_stats(guild_id, target_id, {hp_stat_name: new_hp})
            outcome_summary["target_hp_after"] = new_hp

    log_messages.append(f"{target_name} {hp_stat_name}: {target_current_hp:.2f} -> {new_hp:.2f}.")
    await game_log_manager.add_log_entry(f"Combat: {target_name} takes {total_damage:.2f} damage. {hp_stat_name}: {target_current_hp:.2f} -> {new_hp:.2f}", "combat_results")
    return outcome_summary

async def process_saving_throw(
    entity_id: str, entity_type: str, rules_config: Dict[str, Any],
    dc: int, save_type: str, character_manager: 'CharacterManager',
    npc_manager: 'NpcManager', game_log_manager: 'GameLogManager',
    effect_description: Optional[str] = "an effect"
) -> DetailedCheckResult:
    guild_id = rules_config.get("guild_id", "default_guild")
    entity_object: Optional[Any] = None
    if entity_type == "Character": entity_object = await character_manager.get_character(guild_id, entity_id)
    elif entity_type == "NPC": entity_object = await npc_manager.get_npc(guild_id, entity_id)

    if not entity_object:
        error_description = f"Entity {entity_id} ({entity_type}) not found for saving throw against {effect_description} (DC {dc})."
        await game_log_manager.add_log_entry(error_description, "error_combat")
        return DetailedCheckResult(
            check_type=f"saving_throw_{save_type}", entity_doing_check_id=entity_id, difficulty_dc=dc,
            outcome=CheckOutcome.FAILURE, description=error_description, actor_rolls=[0], actor_total_roll_value=0
        )

    entity_name = getattr(entity_object, 'name', entity_id)
    save_modifier = 0
    modifier_details_list = []
    combat_rules = rules_config.get("combat_rules", {})
    saving_throw_rules = combat_rules.get("saving_throws", {})
    stat_to_use_for_save = saving_throw_rules.get("stat_modifiers", {}).get(save_type)
    entity_stats = getattr(entity_object, 'stats', {})

    if stat_to_use_for_save and entity_stats:
        stat_val = entity_stats.get(stat_to_use_for_save, 10)
        modifier_formula_config = combat_rules.get("stat_bonus_rules", {}).get("default_ability_modifier", {})
        base_value = modifier_formula_config.get("base_value", 10)
        divisor = modifier_formula_config.get("divisor", 2)
        if divisor == 0: divisor = 1
        save_modifier = (stat_val - base_value) // divisor
        modifier_details_list.append({"source": f"{stat_to_use_for_save}_bonus_for_{save_type}", "value": save_modifier})
    else:
        save_modifier = saving_throw_rules.get("default_modifier", 0)
        modifier_details_list.append({"source": "default_save_bonus", "value": save_modifier})

    check_type_str = f"saving_throw_{save_type}"
    saving_throw_result = perform_check(
        actor_id=entity_id, rules_config=rules_config, check_type=check_type_str,
        modifier=save_modifier, modifier_details=modifier_details_list, dc=dc
    )

    saving_throw_result.description = (
        f"{entity_name} attempts a {save_type} saving throw against {effect_description}. "
        f"{saving_throw_result.description}"
    )
    await game_log_manager.add_log_entry(saving_throw_result.description, "combat_save")
    return saving_throw_result

async def apply_status_effect(
    target_id: str,
    target_type: str,
    status_template_id: str,
    rules_config: Dict[str, Any],
    status_manager: 'StatusManager',
    character_manager: 'CharacterManager',
    npc_manager: 'NpcManager',
    game_log_manager: 'GameLogManager',
    source_id: Optional[str] = None,
    source_type: Optional[str] = None,
    duration_override_rounds: Optional[int] = None,
    requires_save_info: Optional[Dict[str, Any]] = None,
    current_game_time: float = 0.0
) -> bool:
    guild_id = rules_config.get("guild_id", "default_guild")
    log_prefix = f"ApplyStatus ({status_template_id}) on {target_type} {target_id}:"
    await game_log_manager.add_log_entry(f"{log_prefix} Initiating application.", "status_debug")

    actual_duration_rounds: Optional[int] = duration_override_rounds
    status_effect_rules = rules_config.get("combat_rules", {}).get("status_effects", {})
    default_duration_rounds_config = status_effect_rules.get("default_duration_rounds", 5)

    if actual_duration_rounds is None:
        actual_duration_rounds = default_duration_rounds_config

    if requires_save_info and isinstance(requires_save_info, dict):
        save_type = requires_save_info.get("save_type")
        save_dc = requires_save_info.get("dc")
        effect_on_save = requires_save_info.get("effect_on_save", "negate")

        if not save_type or not isinstance(save_dc, int):
            await game_log_manager.add_log_entry(f"{log_prefix} Invalid requires_save_info: {requires_save_info}", "error_combat")
            return False

        save_effect_desc = f"resisting {status_template_id}"
        save_result = await process_saving_throw(
            entity_id=target_id, entity_type=target_type, rules_config=rules_config,
            dc=save_dc, save_type=save_type, character_manager=character_manager,
            npc_manager=npc_manager, game_log_manager=game_log_manager,
            effect_description=save_effect_desc
        )

        await game_log_manager.add_log_entry(f"{log_prefix} Save attempt result: {save_result.description}", "status_debug")

        if save_result.is_success:
            if effect_on_save == "negate":
                await game_log_manager.add_log_entry(f"{log_prefix} Successfully saved and negated.", "status_info")
                return True
            elif effect_on_save == "half_duration":
                if actual_duration_rounds is not None:
                    actual_duration_rounds = max(1, actual_duration_rounds // 2)
                await game_log_manager.add_log_entry(f"{log_prefix} Saved for half duration. New duration: {actual_duration_rounds} rounds.", "status_info")

    if actual_duration_rounds is None:
        actual_duration_rounds = default_duration_rounds_config
        await game_log_manager.add_log_entry(f"{log_prefix} Duration override was None, and save didn't set it. Defaulting to {actual_duration_rounds} rounds.", "warning_combat")

    combat_settings = rules_config.get("combat_settings", {})
    round_duration_seconds = float(combat_settings.get("round_duration_seconds", 6.0))
    final_duration_seconds = actual_duration_rounds * round_duration_seconds

    applied_successfully = await status_manager.add_status_effect(
        guild_id=guild_id,
        target_id=target_id,
        target_type=target_type,
        status_type=status_template_id,
        duration_seconds=final_duration_seconds,
        applied_by_source_id=source_id,
        applied_by_source_type=source_type,
        current_game_time=current_game_time
    )

    if applied_successfully:
        await game_log_manager.add_log_entry(f"{log_prefix} Applied via StatusManager with duration {final_duration_seconds:.2f}s ({actual_duration_rounds} rounds).", "status_info")
        return True
    else:
        await game_log_manager.add_log_entry(f"{log_prefix} Failed to apply via StatusManager.", "error_combat")
        return False

async def process_direct_damage(
    actor_id: str,
    actor_type: Optional[str],
    target_id: str,
    target_type: str,
    damage_amount_str: str,
    damage_type: str,
    rules_config: Dict[str, Any],
    character_manager: 'CharacterManager',
    npc_manager: 'NpcManager',
    game_log_manager: Optional['GameLogManager']
) -> Dict[str, Any]:
    outcome = {"damage_dealt": 0.0, "target_hp_after": 0.0, "log_messages": [], "target_id": target_id}

    target_entity: Optional[Any] = None
    guild_id = rules_config.get("guild_id", "")
    if target_type == "Character":
        target_entity = await character_manager.get_character(guild_id, target_id)
    elif target_type == "NPC":
        target_entity = await npc_manager.get_npc(guild_id, target_id)

    if not target_entity:
        outcome["log_messages"].append(f"DirectDamage: Target {target_id} ({target_type}) not found.")
        return outcome

    target_name = getattr(target_entity, 'name', target_id)
    hp_attr = 'hp' if target_type == "Character" else 'health'
    initial_hp = float(getattr(target_entity, hp_attr, 0))
    outcome["target_hp_after"] = initial_hp

    try:
        base_damage = _roll_dice_simple(damage_amount_str)
    except Exception as e:
        outcome["log_messages"].append(f"DirectDamage: Error rolling damage '{damage_amount_str}': {e}")
        if game_log_manager: await game_log_manager.add_log_entry(outcome["log_messages"][-1], "error_combat")
        return outcome

    # Placeholder for resistances/vulnerabilities
    # final_damage = apply_resistances_vulnerabilities(base_damage, damage_type, target_entity.stats, rules_config)
    final_damage = base_damage

    actual_damage_taken = max(0, final_damage) # Damage cannot be negative
    new_hp = initial_hp - actual_damage_taken

    outcome["damage_dealt"] = actual_damage_taken
    outcome["target_hp_after"] = new_hp

    if target_type == "Character":
        await character_manager.update_character_stats(guild_id, target_id, {"hp": new_hp})
    elif target_type == "NPC":
        await npc_manager.update_npc_stats(guild_id, target_id, {"health": new_hp})

    log_msg = f"{target_name} took {actual_damage_taken} {damage_type} direct damage. HP: {initial_hp:.1f} -> {new_hp:.1f}."
    outcome["log_messages"].append(log_msg)
    if game_log_manager:
        await game_log_manager.add_log_entry(log_msg, "combat_direct_damage",
                                             metadata={"target_id": target_id, "damage": actual_damage_taken, "damage_type": damage_type, "actor_id": actor_id})

    return outcome

async def process_healing(
    target_id: str,
    target_type: str,
    heal_amount_str: str,
    rules_config: Dict[str, Any],
    character_manager: 'CharacterManager',
    npc_manager: 'NpcManager',
    game_log_manager: Optional['GameLogManager']
) -> Dict[str, Any]:
    outcome = {"healing_done": 0.0, "target_hp_after": 0.0, "log_messages": [], "target_id": target_id}

    target_entity: Optional[Any] = None
    guild_id = rules_config.get("guild_id", "")
    if target_type == "Character":
        target_entity = await character_manager.get_character(guild_id, target_id)
    elif target_type == "NPC":
        target_entity = await npc_manager.get_npc(guild_id, target_id)

    if not target_entity:
        outcome["log_messages"].append(f"ProcessHealing: Target {target_id} ({target_type}) not found.")
        return outcome

    target_name = getattr(target_entity, 'name', target_id)
    initial_hp_attr = 'hp' if target_type == "Character" else 'health'
    initial_hp = float(getattr(target_entity, initial_hp_attr, 0))

    target_stats = getattr(target_entity, 'stats', {})
    # Ensure max_hp is float and handles missing key robustly
    max_hp_val = target_stats.get('max_health', target_stats.get('max_hp')) # Check both common names
    if max_hp_val is None: max_hp_val = initial_hp # Fallback to current HP if no max_hp defined
    max_hp = float(max_hp_val)


    outcome["target_hp_after"] = initial_hp

    try:
        base_healing = _roll_dice_simple(heal_amount_str)
    except Exception as e:
        outcome["log_messages"].append(f"ProcessHealing: Error rolling healing '{heal_amount_str}': {e}")
        if game_log_manager: await game_log_manager.add_log_entry(outcome["log_messages"][-1], "error_combat")
        return outcome

    actual_healing = max(0, base_healing) # Healing cannot be negative
    hp_after_heal = min(initial_hp + actual_healing, max_hp) # Cap at max_hp
    effective_healing = hp_after_heal - initial_hp # Actual amount healed

    outcome["healing_done"] = effective_healing
    outcome["target_hp_after"] = hp_after_heal

    if target_type == "Character":
        await character_manager.update_character_stats(guild_id, target_id, {"hp": hp_after_heal})
    elif target_type == "NPC":
        await npc_manager.update_npc_stats(guild_id, target_id, {"health": hp_after_heal})

    log_msg = f"{target_name} was healed for {effective_healing:.1f} HP. HP: {initial_hp:.1f} -> {hp_after_heal:.1f} (Max: {max_hp:.1f})."
    outcome["log_messages"].append(log_msg)
    if game_log_manager:
        await game_log_manager.add_log_entry(log_msg, "combat_healing",
                                             metadata={"target_id": target_id, "healing_amount": effective_healing})

    return outcome
