import logging # Added
from typing import Optional, Dict, Any, TYPE_CHECKING, Union, List

from bot.database.models import Player, NPC # Assuming NPC model is in bot.database.models
from bot.game.models.check_models import CheckResult
from bot.game.rules import dice_roller # From step 1
from bot.game.utils.stats_calculator import calculate_effective_stats # Added import

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__) # Added

async def resolve_check(
    guild_id: str,
    check_type: str, # e.g., "strength_save", "skill_stealth", "attack_melee_strength"
    performing_entity_id: str,
    performing_entity_type: str, # "player" or "npc"
    game_manager: 'GameManager',
    target_entity_id: Optional[str] = None,
    target_entity_type: Optional[str] = None,
    difficulty_dc: Optional[int] = None,
    base_roll_str: str = "1d20",
    additional_modifiers: Optional[Dict[str, int]] = None, # e.g., {"bless_spell": 1, "item_bonus": 2}
    context_notes: Optional[str] = None # Optional notes for the description
) -> CheckResult:
    """
    Resolves a generic attribute or skill check.
    """
    if not game_manager or not game_manager.db_service:
        # This should ideally not happen if GameManager is properly initialized
        raise ValueError("GameManager or DBService not available for resolve_check.")

    # 1. Fetch Performing Entity
    entity: Optional[Union[Player, NPC]] = None
    entity_name_for_log = performing_entity_id # Default name for logging if entity fetch fails

    if performing_entity_type.lower() == "player":
        entity = await game_manager.get_player_model_by_id(guild_id, performing_entity_id)
        if entity: entity_name_for_log = getattr(entity, 'name_i18n', {}).get('en', performing_entity_id)
    elif performing_entity_type.lower() == "npc":
        if game_manager.npc_manager:
             entity = await game_manager.npc_manager.get_npc(guild_id, performing_entity_id)
             if entity: entity_name_for_log = getattr(entity, 'name_i18n', {}).get('en', performing_entity_id)
        else:
            raise NotImplementedError(f"NPC Manager not available in GameManager, cannot fetch NPC for resolve_check.")

    if not entity:
        raise ValueError(f"Performing entity {performing_entity_type} {performing_entity_id} not found in guild {guild_id}.")

    # 2. Get Effective Stats
    effective_stats = await calculate_effective_stats(entity, guild_id, game_manager)

    # 3. Determine Primary Attribute/Skill and Base Modifier
    details_log_dict: Dict[str, Any] = { # Initialize details_log_dict earlier
        "entity_id": performing_entity_id,
        "entity_type": performing_entity_type,
        "entity_name": entity_name_for_log,
        "check_type": check_type,
    }

    primary_stat_key_used = None
    primary_stat_name = None

    # Try to get skill mapping first
    skill_rule_key = f"checks.{check_type}.skill"
    defined_skill = await game_manager.get_rule(guild_id, skill_rule_key)

    if defined_skill and isinstance(defined_skill, str):
        primary_stat_name = defined_skill
        primary_stat_key_used = skill_rule_key
        details_log_dict["stat_determination_method"] = f"RuleConfig: skill_key='{skill_rule_key}'"
    else:
        # If no skill mapping, try attribute mapping
        attribute_rule_key = f"checks.{check_type}.attribute"
        defined_attribute = await game_manager.get_rule(guild_id, attribute_rule_key)
        if defined_attribute and isinstance(defined_attribute, str):
            primary_stat_name = defined_attribute
            primary_stat_key_used = attribute_rule_key
            details_log_dict["stat_determination_method"] = f"RuleConfig: attribute_key='{attribute_rule_key}'"
        else:
            # Fallback if no specific rule is found
            primary_stat_name = "strength" # Default fallback attribute
            details_log_dict["stat_determination_method"] = f"Fallback: No specific rule for '{check_type}', defaulted to '{primary_stat_name}'."
            logger.warning(f"CheckResolver: No RuleConfig for check_type '{check_type}' (keys: '{skill_rule_key}', '{attribute_rule_key}'). Defaulted to '{primary_stat_name}'.")

    details_log_dict["assumed_primary_stat"] = primary_stat_name
    stat_value = effective_stats.get(primary_stat_name, 10)
    if not isinstance(stat_value, int):
        try:
            stat_value = int(stat_value)
        except (ValueError, TypeError):
            stat_value = 10

    base_modifier = (stat_value - 10) // 2

    details_log_dict["stat_value_used"] = stat_value
    details_log_dict["base_modifier_calc"] = f"({stat_value} - 10) // 2 = {base_modifier}"

    # 4. Calculate Total Modifier
    total_modifier = base_modifier
    modifier_breakdown = {f"base_{primary_stat_name}": base_modifier} # Use primary_stat_name

    if additional_modifiers:
        for source, mod_val in additional_modifiers.items():
            total_modifier += mod_val
            modifier_breakdown[source] = mod_val

    details_log_dict["modifier_sources"] = modifier_breakdown
    details_log_dict["total_modifier_applied"] = total_modifier

    # 5. Perform Dice Roll
    try:
        roll_sum, individual_rolls = dice_roller.roll_dice(base_roll_str)
    except ValueError as e:
        raise ValueError(f"Invalid base_roll_str '{base_roll_str}' for check: {e}") from e

    details_log_dict["dice_roll_str"] = base_roll_str
    details_log_dict["individual_rolls"] = individual_rolls
    details_log_dict["raw_roll_sum"] = roll_sum

    # 6. Calculate Total Roll Value
    total_roll_value = roll_sum + total_modifier
    details_log_dict["final_roll_value_calc"] = f"{roll_sum} (roll) + {total_modifier} (mod) = {total_roll_value}"

    # 7. Determine Success
    succeeded = False
    target_defense_value_for_check: Optional[int] = None
    # Use entity_name_for_log which has a fallback if i18n name isn't there
    description_parts = [
        f"{check_type.replace('_', ' ').title()} for {entity_name_for_log}:",
        f"{roll_sum} (roll {base_roll_str})",
    ]
    if total_modifier >= 0:
        description_parts.append(f"+ {total_modifier} (mod)")
    else:
        description_parts.append(f"- {abs(total_modifier)} (mod)")
    description_parts.append(f"= {total_roll_value}")

    if difficulty_dc is not None:
        succeeded = total_roll_value >= difficulty_dc
        description_parts.append(f"vs DC {difficulty_dc}")
        details_log_dict["target_dc"] = difficulty_dc
        target_defense_value_for_check = difficulty_dc # For consistent CheckResult population
    elif target_entity_id and target_entity_type:
        target_entity: Optional[Union[Player, NPC]] = None
        target_entity_name_for_log = target_entity_id

        if target_entity_type.lower() == "player":
            target_entity = await game_manager.get_player_model_by_id(guild_id, target_entity_id)
            if target_entity: target_entity_name_for_log = getattr(target_entity, 'name_i18n', {}).get('en', target_entity_id)
        elif target_entity_type.lower() == "npc":
            if game_manager.npc_manager:
                target_entity = await game_manager.npc_manager.get_npc(guild_id, target_entity_id)
                if target_entity: target_entity_name_for_log = getattr(target_entity, 'name_i18n', {}).get('en', target_entity_id)
            else:
                logger.error(f"CheckResolver: NpcManager not available, cannot fetch target NPC {target_entity_id}.")

        if not target_entity:
            logger.error(f"CheckResolver: Target entity {target_entity_type} {target_entity_id} not found for opposed check.")
            succeeded = False # Fail if target not found
            description_parts.append(f"vs Target {target_entity_name_for_log} (Not Found)")
            details_log_dict["opposition_type"] = "error_target_not_found"
        else:
            target_effective_stats = await calculate_effective_stats(target_entity, guild_id, game_manager)

            opposed_by_stat_key = f"checks.{check_type}.opposed_by_stat"
            opposed_by_skill_key = f"checks.{check_type}.opposed_by_skill"

            defined_opposing_stat_name = await game_manager.get_rule(guild_id, opposed_by_stat_key)
            defined_opposing_skill_name = await game_manager.get_rule(guild_id, opposed_by_skill_key)

            if defined_opposing_stat_name and isinstance(defined_opposing_stat_name, str):
                target_defense_value_for_check = target_effective_stats.get(defined_opposing_stat_name, 10)
                succeeded = total_roll_value >= target_defense_value_for_check
                description_parts.append(f"vs Target {target_entity_name_for_log}'s {defined_opposing_stat_name.replace('_',' ').title()} {target_defense_value_for_check}")
                details_log_dict["opposition_type"] = "stat"
                details_log_dict["opposing_stat_name"] = defined_opposing_stat_name
                details_log_dict["target_defense_value"] = target_defense_value_for_check
            elif defined_opposing_skill_name and isinstance(defined_opposing_skill_name, str):
                target_skill_value = target_effective_stats.get(defined_opposing_skill_name, 10)
                if not isinstance(target_skill_value, int): target_skill_value = 10
                target_skill_modifier = (target_skill_value - 10) // 2
                target_defense_value_for_check = 10 + target_skill_modifier # Passive check
                succeeded = total_roll_value >= target_defense_value_for_check
                description_parts.append(f"vs Target {target_entity_name_for_log}'s Passive {defined_opposing_skill_name.replace('_',' ').title()} {target_defense_value_for_check}")
                details_log_dict["opposition_type"] = "passive_skill"
                details_log_dict["opposing_skill_name"] = defined_opposing_skill_name
                details_log_dict["target_defense_value"] = target_defense_value_for_check
            else:
                logger.warning(f"CheckResolver: No RuleConfig for opposition for check_type '{check_type}' against target. Defaulting to failure. Searched keys: '{opposed_by_stat_key}', '{opposed_by_skill_key}'.")
                succeeded = False
                description_parts.append(f"vs Target {target_entity_name_for_log} (Undefined Opposition)")
                details_log_dict["opposition_type"] = "undefined"
    else:
        description_parts.append("(no DC or target specified; outcome may depend on context)")
        succeeded = False # Or True, depending on interpretation for checks without explicit targets.

    description_parts.append(f"-> {'Success' if succeeded else 'Failure'}")
    if context_notes:
        description_parts.append(f"({context_notes})")

    final_description = " ".join(description_parts)
    details_log_dict["outcome_description"] = final_description
    details_log_dict["succeeded"] = succeeded

    return CheckResult(
        succeeded=succeeded,
        roll_value=roll_sum,
        modifier_applied=total_modifier,
        total_roll_value=total_roll_value,
        dc_value=difficulty_dc,
        opposed_roll_value=target_defense_value_for_check, # Use the calculated target value
        description=final_description,
        details_log=details_log_dict
    )
