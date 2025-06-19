# bot/game/rules/resolvers/skill_check_resolver.py
import random
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, List, Callable, Awaitable

from bot.game.models.check_models import CheckResult

if TYPE_CHECKING:
    from bot.game.models.character import Character
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    # from bot.game.managers.item_manager import ItemManager # Removed unused import
    # Add other necessary model/manager imports if specific methods need them


async def resolve_skill_check(
    character: "Character",
    skill_type: str,
    dc: int,
    rules_data: Dict[str, Any], # From RuleEngine._rules_data
    resolve_dice_roll_func: Callable[[str, Optional[int], Optional[Dict[str, Any]]], Awaitable[Dict[str, Any]]],
    context: Optional[Dict[str, Any]] = None
) -> Tuple[bool, int, int, Optional[str]]:
    """
    Core logic for resolving a skill check.
    """
    if context is None:
        context = {}

    # This is a simplified placeholder.
    # Actual skill modifier calculation (e.g., from stats + proficiency + expertise) should be implemented here
    # based on how character.skills_data_json is structured or if there are other stat sources.
    # For example, if skills_data_json stores raw skill points:
    skills_data = character.skills_data_json or {}
    skill_bonus = skills_data.get(skill_type, 0) # This might be a total modifier or just points.

    # Example: if skill_type refers to an attribute like 'strength' for an athletics check:
    # char_stats = character.stats_json or {}
    # attribute_value = char_stats.get(skill_type, 10) # Default to 10 if not found
    # modifier = (attribute_value - 10) // 2
    # skill_bonus = modifier # Or add proficiency if applicable

    dice_roll_result = await resolve_dice_roll_func("1d20", context=context)
    d20_roll = dice_roll_result.get("rolls", [0])[0]

    total_roll = d20_roll + skill_bonus # Add other situational modifiers if any from context

    crit_status = None
    # Access critical success/failure thresholds from rules_data
    check_rules = rules_data.get("check_rules", {})
    crit_success_threshold = check_rules.get("critical_success_threshold", 20)
    crit_failure_threshold = check_rules.get("critical_failure_threshold", 1)

    if d20_roll >= crit_success_threshold: # Use >= for threshold
        crit_status = "critical_success"
    elif d20_roll <= crit_failure_threshold: # Use <= for threshold
        crit_status = "critical_failure"

    success = total_roll >= dc
    # Apply critical success/failure overrides
    if crit_status == "critical_success":
        success = True
    elif crit_status == "critical_failure":
        success = False

    return success, total_roll, d20_roll, crit_status


async def resolve_stealth_check(
    character_manager: "CharacterManager",
    rules_data: Dict[str, Any],
    resolve_dice_roll_func: Callable, # To pass to the core resolve_skill_check
    character_id: str,
    guild_id: str,
    location_id: str, # Currently unused, but kept for signature consistency
    **kwargs: Any # Pass full context including resolve_dice_roll_func
) -> CheckResult:
    character = await character_manager.get_character(guild_id, character_id)
    if not character:
        return CheckResult(succeeded=False, description="Character not found.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

    stealth_rules = rules_data.get("stealth_rules", {})
    current_dc = stealth_rules.get("base_detection_dc", 15)

    # Ensure resolve_dice_roll_func from kwargs is passed to the core skill check function
    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character, "stealth", current_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )

    # Calculate modifier_applied correctly
    skills_data = character.skills_data_json or {}
    skill_bonus = skills_data.get("stealth", 0) # Simplified; actual modifier logic might be more complex

    return CheckResult(
        succeeded=success,
        roll_value=d20_roll,
        modifier_applied=total_roll - d20_roll, # This is skill_bonus + any other context modifiers
        total_roll_value=total_roll,
        dc_value=current_dc,
        description=f"Stealth check {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}",
        details_log={"skill_type": "stealth", "crit_status": crit_status}
    )

async def resolve_pickpocket_attempt(
    character_manager: "CharacterManager",
    npc_manager: "NpcManager", # Added NpcManager
    rules_data: Dict[str, Any],
    resolve_dice_roll_func: Callable,
    character_id: str,
    guild_id: str,
    target_npc_id: str,
    **kwargs: Any
) -> CheckResult:
    character = await character_manager.get_character(guild_id, character_id)
    if not character:
        return CheckResult(succeeded=False, description="Character not found for pickpocket.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

    # target_npc is needed for perception or opposed checks in future, not strictly for base DC here yet
    target_npc = await npc_manager.get_npc(guild_id, target_npc_id)
    if not target_npc:
         return CheckResult(succeeded=False, description="Target NPC not found for pickpocket.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Target NPC not found."})

    pickpocket_rules = rules_data.get("pickpocket_rules", {})
    current_dc = pickpocket_rules.get("base_dc", 12)

    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character, "pickpocket", current_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )

    detected = not success # Simple assumption
    item_id_stolen = "GENERIC_LOOT_PLACEHOLDER" if success else None # Placeholder logic

    skills_data = character.skills_data_json or {}
    skill_bonus = skills_data.get("pickpocket", 0)

    return CheckResult(
        succeeded=success,
        roll_value=d20_roll,
        modifier_applied=total_roll - d20_roll,
        total_roll_value=total_roll,
        dc_value=current_dc,
        description=f"Pickpocket attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}",
        details_log={
            "skill_type": "pickpocket",
            "crit_status": crit_status,
            "detected": detected,
            "item_id_stolen": item_id_stolen
        }
    )

async def resolve_gathering_attempt(
    character_manager: "CharacterManager",
    rules_data: Dict[str, Any],
    resolve_dice_roll_func: Callable,
    character_id: str,
    guild_id: str,
    poi_data: Dict[str, Any],
    # Removed character_skills and character_inventory, will use character object
    **kwargs: Any
) -> CheckResult:
    character = await character_manager.get_character(guild_id, character_id)
    if not character:
        return CheckResult(succeeded=False, description="error_character_not_found", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "error_character_not_found"})

    char_inventory_list = character.inventory_json or [] # Assuming inventory_json is a list of item dicts

    resource_details = poi_data.get("resource_details")
    if not resource_details:
        return CheckResult(succeeded=False, description="gathering_fail_invalid_node_data", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "gathering_fail_invalid_node_data"})

    gathering_skill_id = resource_details.get("gathering_skill_id")
    gathering_dc = resource_details.get("gathering_dc", 15)
    required_tool_category = resource_details.get("required_tool_category")
    base_yield_formula = resource_details.get("base_yield_formula", "1")
    primary_resource_id = resource_details.get("resource_item_template_id")
    secondary_resource_id = resource_details.get("secondary_resource_item_template_id")
    secondary_yield_formula = resource_details.get("secondary_resource_yield_formula", "1")
    secondary_chance = resource_details.get("secondary_resource_chance", 0.0)

    if not primary_resource_id or not gathering_skill_id:
        return CheckResult(succeeded=False, description="gathering_fail_incomplete_node_data", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=gathering_dc, details_log={"reason": "gathering_fail_incomplete_node_data", "skill_type": gathering_skill_id})

    if required_tool_category:
        has_required_tool = False
        for item_dict in char_inventory_list:
            item_properties = item_dict.get("properties", {}) # Assuming properties is a dict
            if isinstance(item_properties, dict) and item_properties.get("tool_category") == required_tool_category:
                has_required_tool = True
                break
        if not has_required_tool:
            return CheckResult(succeeded=False, description=f"gathering_fail_no_tool_{required_tool_category}", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=gathering_dc, details_log={"skill_type": gathering_skill_id, "required_tool_category": required_tool_category})

    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character, gathering_skill_id, gathering_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )

    if not success:
        skills_data = character.skills_data_json or {}
        skill_bonus = skills_data.get(gathering_skill_id, 0)
        return CheckResult(succeeded=False, description=f"gathering_fail_skill_check_{gathering_skill_id}", roll_value=d20_roll, modifier_applied=total_roll-d20_roll, total_roll_value=total_roll, dc_value=gathering_dc, details_log={"skill_type": gathering_skill_id, "crit_status": crit_status})

    yielded_items = []
    try:
        primary_yield_roll = await resolve_dice_roll_func(base_yield_formula, context=kwargs)
        primary_quantity = primary_yield_roll.get("total", 0)
        if primary_quantity > 0:
            yielded_items.append({"item_template_id": primary_resource_id, "quantity": primary_quantity})
        if secondary_resource_id and random.random() < secondary_chance:
            secondary_yield_roll = await resolve_dice_roll_func(secondary_yield_formula, context=kwargs)
            secondary_quantity = secondary_yield_roll.get("total", 0)
            if secondary_quantity > 0:
                yielded_items.append({"item_template_id": secondary_resource_id, "quantity": secondary_quantity})
    except ValueError as e:
        return CheckResult(succeeded=False, description="gathering_fail_yield_calculation_error", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=gathering_dc, details_log={"reason": "gathering_fail_yield_calculation_error", "skill_type": gathering_skill_id, "error": str(e)})

    skills_data = character.skills_data_json or {}
    skill_bonus = skills_data.get(gathering_skill_id, 0)
    return CheckResult(succeeded=True, roll_value=d20_roll, modifier_applied=total_roll-d20_roll, total_roll_value=total_roll, dc_value=gathering_dc, description=f"gathering_success_{gathering_skill_id}", details_log={"skill_type": gathering_skill_id, "crit_status": crit_status, "yielded_items": yielded_items})

async def resolve_crafting_attempt(
    character_manager: "CharacterManager",
    # rules_data: Dict[str, Any], # Not directly used in MVP logic, but good for future
    character_id: str,
    guild_id: str,
    recipe_data: Dict[str, Any],
    current_location_data: Dict[str, Any], # Contains 'tags' list and 'properties' like 'station_type'
    **kwargs: Any # Pass full context
) -> CheckResult:
    character = await character_manager.get_character(guild_id, character_id)
    if not character:
        return CheckResult(succeeded=False, description="error_character_not_found", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"reason": "error_character_not_found"})

    char_skills = character.skills_data_json or {}
    char_inventory_list = character.inventory_json or [] # Assuming list of item dicts

    recipe_id = recipe_data.get("id", "unknown_recipe")
    ingredients = recipe_data.get("ingredients_json", [])
    outputs = recipe_data.get("outputs_json", []) # Assuming this is the new format
    required_skill_id = recipe_data.get("required_skill_id")
    required_skill_level = recipe_data.get("required_skill_level", 0)
    other_requirements = recipe_data.get("other_requirements_json", {})
    required_tools_specific = other_requirements.get("required_tools", [])
    required_crafting_station = other_requirements.get("crafting_station_type")
    required_location_tags = other_requirements.get("required_location_tags", [])

    if required_skill_id and char_skills.get(required_skill_id, 0) < required_skill_level:
        return CheckResult(succeeded=False, description="crafting_fail_skill_too_low", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "required_skill": required_skill_id, "required_level": required_skill_level})

    consumed_items_for_outcome = []
    # Create a temporary map of available ingredients from character's inventory for easier lookup
    # This assumes inventory_json is a list of dicts, each with 'template_id' and 'quantity'
    inventory_map = {item['template_id']: item['quantity'] for item in char_inventory_list if 'template_id' in item and 'quantity' in item}

    for ingredient in ingredients:
        ing_id = ingredient.get("item_template_id")
        ing_qty = ingredient.get("quantity")
        if not ing_id or ing_qty is None: continue # Skip malformed ingredient

        if inventory_map.get(ing_id, 0) < ing_qty:
            return CheckResult(succeeded=False, description="crafting_fail_missing_ingredients", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "missing_item_id": ing_id, "required_quantity": ing_qty})
        consumed_items_for_outcome.append({"item_template_id": ing_id, "quantity": ing_qty})

    if required_tools_specific:
        for tool_template_id in required_tools_specific:
            if not any(item.get('template_id') == tool_template_id for item in char_inventory_list):
                return CheckResult(succeeded=False, description="crafting_fail_missing_specific_tool", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "missing_tool_id": tool_template_id})

    if required_crafting_station:
        location_station_type = current_location_data.get("properties", {}).get("station_type")
        if location_station_type != required_crafting_station:
             return CheckResult(succeeded=False, description="crafting_fail_wrong_station", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "required_station": required_crafting_station, "current_station": location_station_type or "none"})

    if required_location_tags:
        location_tags = current_location_data.get("tags", [])
        if not all(tag in location_tags for tag in required_location_tags):
            return CheckResult(succeeded=False, description="crafting_fail_location_tags", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "required_tags": required_location_tags})

    # MVP: If all checks pass, crafting is successful.
    crafted_item_details = outputs[0] if outputs else None # Assume primary output is the first
    if not crafted_item_details: # Must have at least one output
        return CheckResult(succeeded=False, description="crafting_fail_no_output_defined", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id})

    return CheckResult(succeeded=True, description="crafting_success", roll_value=0, modifier_applied=0, total_roll_value=0, details_log={"recipe_id": recipe_id, "crafted_item": crafted_item_details, "consumed_items": consumed_items_for_outcome})

async def resolve_lockpick_attempt(
    character_manager: "CharacterManager",
    rules_data: Dict[str, Any],
    resolve_dice_roll_func: Callable,
    character_id: str,
    guild_id: str,
    poi_data: Dict[str, Any],
    **kwargs: Any
) -> CheckResult:
    character = await character_manager.get_character(guild_id, character_id)
    if not character:
        return CheckResult(succeeded=False, description="Character not found for lockpicking.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

    lock_details = poi_data.get("lock_details", {})
    current_dc = lock_details.get("dc", 15)

    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character, "lockpicking", current_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )

    skills_data = character.skills_data_json or {}
    skill_bonus = skills_data.get("lockpicking", 0)

    return CheckResult(succeeded=success, roll_value=d20_roll, modifier_applied=total_roll - d20_roll, total_roll_value=total_roll, dc_value=current_dc, description=f"Lockpicking attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}", details_log={"skill_type": "lockpicking", "crit_status": crit_status})

async def resolve_disarm_trap_attempt(
    character_manager: "CharacterManager",
    rules_data: Dict[str, Any],
    resolve_dice_roll_func: Callable,
    character_id: str,
    guild_id: str,
    poi_data: Dict[str, Any],
    **kwargs: Any
) -> CheckResult:
    character = await character_manager.get_character(guild_id, character_id)
    if not character:
        return CheckResult(succeeded=False, description="Character not found for disarming trap.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

    trap_details = poi_data.get("trap_details")
    if not trap_details:
        return CheckResult(succeeded=False, description="Trap details not found in PoI data.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Trap details not found."})
    current_dc = trap_details.get("disarm_dc", 15)

    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character, "disarm_traps", current_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )
    trap_triggered_on_fail = not success # Simplified: any failure triggers

    skills_data = character.skills_data_json or {}
    skill_bonus = skills_data.get("disarm_traps", 0)

    return CheckResult(succeeded=success, roll_value=d20_roll, modifier_applied=total_roll-d20_roll, total_roll_value=total_roll, dc_value=current_dc, description=f"Disarm trap attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}", details_log={"skill_type": "disarm_traps", "crit_status": crit_status, "trap_triggered_on_fail": trap_triggered_on_fail})
