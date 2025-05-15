# bot/game/rules/skill_rules.py
import random # Needed for dice rolls
from typing import Dict, Any, Optional # Type hints

# Import types if the specific logic needs to access details from entity objects
from bot.game.models.character import Character # Example

# Import managers if specific skill check logic performs lookups *within* the specialized rules module (less common, usually facade does this)
from bot.game.managers.character_manager import CharacterManager # Example


# Helper function (can remain here or be moved)
# Note: RuleEngine already has a get_base_dc helper, might be better to call it from there.
# If this skill_rules function calls it, it needs to import it.
from bot.game.rules.rule_engine import get_base_dc as get_rule_engine_base_dc


# --- Specific logic for skill checks ---
# Called BY RuleEngine.perform_check
# Receives processed data and results from RuleEngine
def perform_skill_check(
    # Pass data RuleEngine gathered, including entity ID/object, base_dc, modifiers.
    entity_id: str, # ID of entity performing check
    entity_object: Optional[Character], # Entity object (passed from RuleEngine if available)
    skill_name: str, # Specific skill being checked
    base_dc: int, # Base Difficulty Class determined before this
    modifiers: Dict[str, Any], # Modifiers already collected and combined (env, status, etc.)
    # Add managers here IF skill_rules needs them internally for lookups that RuleEngine did NOT do before delegating
    # character_manager: Optional[CharacterManager] = None # Example

) -> Dict[str, Any]:
    """
    Executes the specific mechanics for a skill check.
    Called by RuleEngine.perform_check. Calculates roll, result, success/fail/crit.
    Returns a dictionary with the check result details.
    """
    # Example logic based on Character stats/skills
    if not entity_object:
        print(f"Error: Skill check called for entity ID {entity_id}, but entity object not provided to skill_rules.")
        # Return an error result or raise exception
        return {"outcome": "error", "description": f"Ошибка: не удалось провести проверку для {entity_id}."}

    # --- Access entity stats and skills ---
    # Use data from the entity_object passed
    # Example: Assumes Character object has .stats and .skills dictionaries
    stats = entity_object.stats if hasattr(entity_object, 'stats') else {}
    skills = entity_object.skills if hasattr(entity_object, 'skills') else {}


    # --- Determine skill bonus and relevant stat modifier ---
    skill_value = skills.get(skill_name, 0) # Get skill value, default to 0 if untrained

    # Example: Determine relevant stat and get its modifier
    # This mapping should ideally come from rule data loaded by RuleEngine or a specialized data manager.
    stat_mapping = {"athletics": "strength", "stealth": "dexignterity", "persuasion": "charisma", "investigate": "intelligence", "survival":"wisdom"} # Example mapping
    related_stat_name = stat_mapping.get(skill_name, "strength") # Default stat

    stat_value = stats.get(related_stat_name, 10) # Get stat value, default 10
    stat_modifier = (stat_value - 10) // 2 # Example: Standard modifier formula (+1 for every 2 points above 10)


    # --- Calculate final DC (Base DC + Modifiers) ---
    final_modifiers: Dict[str, Any] = modifiers if modifiers is not None else {}

    # --- Perform the roll (Example: 1d20) ---
    roll_result = random.randint(1, 20)

    # --- Calculate total check result ---
    total_result = roll_result + skill_value + stat_modifier + sum(modifiers.values()) # Sum up all modifiers (if needed)


    # --- Determine outcome: Success/Fail/Crit ---
    is_success = total_result >= final_dc
    final_dc: int = base_dc + modifiers.get("environment", 0) + modifiers.get("status", 0) + sum(v for k, v in modifiers.items() if k not in ["environment", "status"] and isinstance(v, (int, float)))

    # --- Check for critical results ---
    # Basic d20 crit rule: natural 20 (crit success) or natural 1 (crit fail)
    # Modify if using other dice types or rules (e.g., max die value on skill die)
    # For standard d20 checks:
    is_critical_success = (roll_result == 20)
    # Crit fail only matters if check failed on d20 rule, OR nat 1 always crit fail regardless of result (GM decision!)
    is_critical_failure = (roll_result == 1) # Simplest: Nat 1 is always critical failure


    # --- Construct and return result dictionary ---
    outcome_desc = "Успех!" if is_success else "Провал!"
    if is_critical_success: outcome_desc = "Критический успех!"
    # if is_critical_failure and not is_success: outcome_desc = "Критический провал!" # More complex: crit fail only if failed
    if is_critical_failure: outcome_desc = "Критический провал!" # Simpler: Nat 1 overrides


    # The check result dictionary structure (Used by ConditionChecker and ActionProcessor for AI description)
    check_result = {
        "check_type": "skill", # Type of check performed
        "skill_name": skill_name,
        "entity_id": entity_id,
        "roll": roll_result,
        "base_dc": base_dc,
        "final_dc": final_dc,
        "skill_value": skill_value,
        "stat_value": stat_value,
        "stat_modifier": stat_modifier,
        "total_result": total_result,
        "modifiers": final_modifiers, # Return all applied modifiers
        "is_success": is_success,
        "is_critical_success": is_critical_success,
        "is_critical_failure": is_critical_failure,
        # Simplified outcome string ('success', 'failure', 'critical_success', 'critical_failure')
        "outcome": "critical_success" if is_critical_success else ("critical_failure" if is_critical_failure else ("success" if is_success else "failure")),
        "description": f"Проверка навыка '{skill_name}': бросок {roll_result} + {skill_value} (навык) + {stat_modifier} ({related_stat_name}) + {sum(final_modifiers.values()) if final_modifiers else 0} (мод) = {total_result} против DC {final_dc}. Результат: {outcome_desc}." # Detailed string description

    }

    return check_result # Return the dictionary of results

# Add other specific rule methods here (e.g., for attribute checks, saving throws)
# def perform_attribute_check(...): ...
# def perform_saving_throw(...): ...