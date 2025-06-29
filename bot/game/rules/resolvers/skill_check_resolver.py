# bot/game/rules/resolvers/skill_check_resolver.py
import json
import random
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, List, Callable, Awaitable

from bot.game.models.check_models import CheckResult

if TYPE_CHECKING:
    from bot.game.models.character import Character
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    # from bot.game.managers.item_manager import ItemManager # Removed unused import
    # Add other necessary model/manager imports if specific methods need them

logger = logging.getLogger(__name__)


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

    # Ensure character.skills_data_json is a dict before .get()
    skills_data_json_val = getattr(character, 'skills_data_json', None)
    skills_data = {}
    if isinstance(skills_data_json_val, str):
        try:
            skills_data = json.loads(skills_data_json_val)
        except json.JSONDecodeError:
            logger.error(f"resolve_skill_check: Invalid JSON in skills_data_json for character {character.id}: {skills_data_json_val}")
            skills_data = {} # Default to empty if parsing fails
    elif isinstance(skills_data_json_val, dict):
        skills_data = skills_data_json_val
    else: # If None or other type, default to empty dict
        skills_data = {}

    skill_bonus = skills_data.get(skill_type, 0) # This might be a total modifier or just points.

    # Example: if skill_type refers to an attribute like 'strength' for an athletics check:
    # char_stats_json_val = getattr(character, 'stats_json', None)
    # char_stats = {}
    # if isinstance(char_stats_json_val, str):
    # try: char_stats = json.loads(char_stats_json_val)
    # except json.JSONDecodeError: pass
    # elif isinstance(char_stats_json_val, dict):
    # char_stats = char_stats_json_val
    # attribute_value = char_stats.get(skill_type, 10) # Default to 10 if not found
    # modifier = (attribute_value - 10) // 2
    # skill_bonus = modifier # Or add proficiency if applicable

    # Ensure resolve_dice_roll_func is callable
    if not callable(resolve_dice_roll_func):
        logger.error(f"resolve_skill_check: resolve_dice_roll_func is not callable for character {character.id}, skill {skill_type}")
        # Handle this error case, perhaps by returning a default failure or raising an exception
        # For now, let's assume a default roll of 0 if the function is missing, though this is not ideal.
        d20_roll = 0 # Default or raise error
    else:
        dice_roll_result = await resolve_dice_roll_func("1d20", context=context)
        d20_roll = dice_roll_result.get("rolls", [0])[0] if isinstance(dice_roll_result, dict) else 0


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
    character_obj = await character_manager.get_character(guild_id, character_id) # Renamed to avoid conflict
    if not character_obj:
        return CheckResult(succeeded=False, description="Character not found.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

    stealth_rules = rules_data.get("stealth_rules", {})
    current_dc = stealth_rules.get("base_detection_dc", 15)

    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character_obj, "stealth", current_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )

    skills_data_json_val = getattr(character_obj, 'skills_data_json', None)
    skills_data = {}
    if isinstance(skills_data_json_val, str):
        try: skills_data = json.loads(skills_data_json_val)
        except json.JSONDecodeError: pass
    elif isinstance(skills_data_json_val, dict):
        skills_data = skills_data_json_val

    skill_bonus = skills_data.get("stealth", 0)

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
    character_obj = await character_manager.get_character(guild_id, character_id) # Renamed
    if not character_obj:
        return CheckResult(succeeded=False, description="Character not found for pickpocket.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

    target_npc_obj = None # Renamed
    if npc_manager and hasattr(npc_manager, 'get_npc') and callable(npc_manager.get_npc):
        target_npc_obj = await npc_manager.get_npc(guild_id, target_npc_id)

    if not target_npc_obj: # Check renamed variable
         return CheckResult(succeeded=False, description="Target NPC not found for pickpocket.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Target NPC not found."})

    pickpocket_rules = rules_data.get("pickpocket_rules", {})
    current_dc = pickpocket_rules.get("base_dc", 12)

    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character_obj, "pickpocket", current_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )

    detected = not success
    item_id_stolen = "GENERIC_LOOT_PLACEHOLDER" if success else None

    skills_data_json_val = getattr(character_obj, 'skills_data_json', None)
    skills_data = {}
    if isinstance(skills_data_json_val, str):
        try: skills_data = json.loads(skills_data_json_val)
        except json.JSONDecodeError: pass
    elif isinstance(skills_data_json_val, dict):
        skills_data = skills_data_json_val
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
    character_obj = await character_manager.get_character(guild_id, character_id) # Renamed
    if not character_obj:
        return CheckResult(succeeded=False, description="error_character_not_found", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "error_character_not_found"})

    char_inventory_json_val = getattr(character_obj, 'inventory_json', None)
    char_inventory_list = []
    if isinstance(char_inventory_json_val, str):
        try: char_inventory_list = json.loads(char_inventory_json_val)
        except json.JSONDecodeError: logger.error(f"resolve_gathering_attempt: Invalid JSON in inventory_json for char {character_id}")
    elif isinstance(char_inventory_json_val, list):
        char_inventory_list = char_inventory_json_val
    if not isinstance(char_inventory_list, list): char_inventory_list = [] # Ensure it's a list

    resource_details = poi_data.get("resource_details")
    if not isinstance(resource_details, dict): # Ensure resource_details is a dict
        return CheckResult(succeeded=False, description="gathering_fail_invalid_node_data", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "gathering_fail_invalid_node_data"})

    gathering_skill_id = resource_details.get("gathering_skill_id") # Already checked resource_details is dict
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
        for item_dict in char_inventory_list: # Already ensured char_inventory_list is a list
            if isinstance(item_dict, dict): # Ensure item_dict is a dict
                item_properties = item_dict.get("properties", {})
                if isinstance(item_properties, dict) and item_properties.get("tool_category") == required_tool_category:
                    has_required_tool = True
                    break
        if not has_required_tool:
            return CheckResult(succeeded=False, description=f"gathering_fail_no_tool_{required_tool_category}", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=gathering_dc, details_log={"skill_type": gathering_skill_id, "required_tool_category": required_tool_category})

    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character_obj, gathering_skill_id, gathering_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )

    skills_data_json_val_gather = getattr(character_obj, 'skills_data_json', None) # Use character_obj
    skills_data_gather = {}
    if isinstance(skills_data_json_val_gather, str):
        try: skills_data_gather = json.loads(skills_data_json_val_gather)
        except json.JSONDecodeError: pass
    elif isinstance(skills_data_json_val_gather, dict):
        skills_data_gather = skills_data_json_val_gather
    skill_bonus_gather = skills_data_gather.get(gathering_skill_id, 0)


    if not success:
        return CheckResult(succeeded=False, description=f"gathering_fail_skill_check_{gathering_skill_id}", roll_value=d20_roll, modifier_applied=total_roll-d20_roll, total_roll_value=total_roll, dc_value=gathering_dc, details_log={"skill_type": gathering_skill_id, "crit_status": crit_status})

    yielded_items = []
    try:
        if callable(resolve_dice_roll_func):
            primary_yield_roll = await resolve_dice_roll_func(base_yield_formula, context=kwargs)
            primary_quantity = primary_yield_roll.get("total", 0) if isinstance(primary_yield_roll, dict) else 0
            if primary_quantity > 0:
                yielded_items.append({"item_template_id": primary_resource_id, "quantity": primary_quantity})
            if secondary_resource_id and random.random() < secondary_chance:
                secondary_yield_roll = await resolve_dice_roll_func(secondary_yield_formula, context=kwargs)
                secondary_quantity = secondary_yield_roll.get("total", 0) if isinstance(secondary_yield_roll, dict) else 0
                if secondary_quantity > 0:
                    yielded_items.append({"item_template_id": secondary_resource_id, "quantity": secondary_quantity})
        else: # Should not happen if check is done in core resolve_skill_check
            logger.error(f"resolve_gathering_attempt: resolve_dice_roll_func not callable for {character_id}")
            # Default to no yield or specific error
    except ValueError as e: # Catch specific error if dice formula is bad
        return CheckResult(succeeded=False, description="gathering_fail_yield_calculation_error", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=gathering_dc, details_log={"reason": "gathering_fail_yield_calculation_error", "skill_type": gathering_skill_id, "error": str(e)})
    except Exception as e_dice: # Catch any other error during dice roll
        logger.error(f"resolve_gathering_attempt: Error in resolve_dice_roll_func for {character_id}: {e_dice}")
        return CheckResult(succeeded=False, description="gathering_fail_dice_error", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=gathering_dc, details_log={"reason": "gathering_fail_dice_error", "skill_type": gathering_skill_id, "error": str(e_dice)})


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
    character_obj = await character_manager.get_character(guild_id, character_id) # Renamed
    if not character_obj:
        return CheckResult(succeeded=False, description="error_character_not_found", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"reason": "error_character_not_found"})

    char_skills_json_val = getattr(character_obj, 'skills_data_json', None)
    char_skills = {}
    if isinstance(char_skills_json_val, str):
        try: char_skills = json.loads(char_skills_json_val)
        except json.JSONDecodeError: pass
    elif isinstance(char_skills_json_val, dict):
        char_skills = char_skills_json_val

    char_inventory_json_val = getattr(character_obj, 'inventory_json', None)
    char_inventory_list = []
    if isinstance(char_inventory_json_val, str):
        try: char_inventory_list = json.loads(char_inventory_json_val)
        except json.JSONDecodeError: pass
    elif isinstance(char_inventory_json_val, list):
        char_inventory_list = char_inventory_json_val
    if not isinstance(char_inventory_list, list): char_inventory_list = []


    recipe_id = recipe_data.get("id", "unknown_recipe")
    ingredients_val = recipe_data.get("ingredients_json", []) # Ensure it's a list
    ingredients = ingredients_val if isinstance(ingredients_val, list) else []

    outputs_val = recipe_data.get("outputs_json", []) # Ensure it's a list
    outputs = outputs_val if isinstance(outputs_val, list) else []

    required_skill_id = recipe_data.get("required_skill_id")
    required_skill_level = recipe_data.get("required_skill_level", 0)

    other_req_val = recipe_data.get("other_requirements_json", {}) # Ensure it's a dict
    other_requirements = other_req_val if isinstance(other_req_val, dict) else {}

    required_tools_specific = other_requirements.get("required_tools", [])
    if not isinstance(required_tools_specific, list): required_tools_specific = [] # Ensure list

    required_crafting_station = other_requirements.get("crafting_station_type")

    required_location_tags = other_requirements.get("required_location_tags", [])
    if not isinstance(required_location_tags, list): required_location_tags = [] # Ensure list


    if required_skill_id and char_skills.get(required_skill_id, 0) < required_skill_level: # char_skills is dict
        return CheckResult(succeeded=False, description="crafting_fail_skill_too_low", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "required_skill": required_skill_id, "required_level": required_skill_level})

    consumed_items_for_outcome = []
    inventory_map = {item['template_id']: item['quantity'] for item in char_inventory_list if isinstance(item, dict) and 'template_id' in item and 'quantity' in item}


    for ingredient in ingredients: # ingredients is list
        if not isinstance(ingredient, dict): continue # Ensure ingredient is dict
        ing_id = ingredient.get("item_template_id")
        ing_qty = ingredient.get("quantity")
        if not ing_id or ing_qty is None: continue

        if inventory_map.get(ing_id, 0) < ing_qty:
            return CheckResult(succeeded=False, description="crafting_fail_missing_ingredients", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "missing_item_id": ing_id, "required_quantity": ing_qty})
        consumed_items_for_outcome.append({"item_template_id": ing_id, "quantity": ing_qty})

    if required_tools_specific: # is list
        for tool_template_id in required_tools_specific:
            if not any(isinstance(item, dict) and item.get('template_id') == tool_template_id for item in char_inventory_list): # char_inventory_list is list
                return CheckResult(succeeded=False, description="crafting_fail_missing_specific_tool", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "missing_tool_id": tool_template_id})

    if required_crafting_station:
        location_properties = current_location_data.get("properties", {}) # current_location_data is dict
        location_station_type = location_properties.get("station_type") if isinstance(location_properties, dict) else None
        if location_station_type != required_crafting_station:
             return CheckResult(succeeded=False, description="crafting_fail_wrong_station", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "required_station": required_crafting_station, "current_station": location_station_type or "none"})

    if required_location_tags: # is list
        location_tags = current_location_data.get("tags", []) # current_location_data is dict
        if not isinstance(location_tags, list): location_tags = [] # Ensure list
        if not all(tag in location_tags for tag in required_location_tags):
            return CheckResult(succeeded=False, description="crafting_fail_location_tags", roll_value=0, total_roll_value=0, modifier_applied=0, details_log={"recipe_id": recipe_id, "required_tags": required_location_tags})

    crafted_item_details = outputs[0] if outputs else None # outputs is list
    if not crafted_item_details:
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
    character_obj = await character_manager.get_character(guild_id, character_id) # Renamed
    if not character_obj:
        return CheckResult(succeeded=False, description="Character not found for lockpicking.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

    lock_details_val = poi_data.get("lock_details", {}) # Ensure dict
    lock_details = lock_details_val if isinstance(lock_details_val, dict) else {}
    current_dc = lock_details.get("dc", 15)

    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character_obj, "lockpicking", current_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )

    skills_data_json_val = getattr(character_obj, 'skills_data_json', None)
    skills_data = {}
    if isinstance(skills_data_json_val, str):
        try: skills_data = json.loads(skills_data_json_val)
        except json.JSONDecodeError: pass
    elif isinstance(skills_data_json_val, dict):
        skills_data = skills_data_json_val
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
    character_obj = await character_manager.get_character(guild_id, character_id) # Renamed
    if not character_obj:
        return CheckResult(succeeded=False, description="Character not found for disarming trap.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Character not found."})

    trap_details_val = poi_data.get("trap_details") # Ensure dict
    if not isinstance(trap_details_val, dict):
        return CheckResult(succeeded=False, description="Trap details not found or invalid in PoI data.", roll_value=0, total_roll_value=0, modifier_applied=0, dc_value=None, details_log={"reason": "Trap details not found or invalid."})
    current_dc = trap_details_val.get("disarm_dc", 15)

    success, total_roll, d20_roll, crit_status = await resolve_skill_check(
        character_obj, "disarm_traps", current_dc, rules_data, resolve_dice_roll_func, context=kwargs
    )
    trap_triggered_on_fail = not success

    skills_data_json_val = getattr(character_obj, 'skills_data_json', None)
    skills_data = {}
    if isinstance(skills_data_json_val, str):
        try: skills_data = json.loads(skills_data_json_val)
        except json.JSONDecodeError: pass
    elif isinstance(skills_data_json_val, dict):
        skills_data = skills_data_json_val
    skill_bonus = skills_data.get("disarm_traps", 0)


    return CheckResult(succeeded=success, roll_value=d20_roll, modifier_applied=total_roll-d20_roll, total_roll_value=total_roll, dc_value=current_dc, description=f"Disarm trap attempt {'succeeded' if success else 'failed'}. Roll: {total_roll} vs DC: {current_dc}", details_log={"skill_type": "disarm_traps", "crit_status": crit_status, "trap_triggered_on_fail": trap_triggered_on_fail})
