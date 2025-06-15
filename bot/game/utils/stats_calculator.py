"""
Calculates effective character/NPC statistics based on base stats, items, and status effects.
"""
import json
from typing import Dict, Any, List, Optional, Union

from bot.ai.rules_schema import CoreGameRulesConfig, StatModifierRule, GrantedAbilityOrSkill

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.models.character import Character
    from bot.game.models.npc import NPC as NpcModel
    from bot.game.models.item import ItemTemplate # For item_manager.get_item_template
    from bot.game.models.status_effect import StatusEffectTemplate # For status_manager.get_status_template
    from bot.game.models.status_effect import StatusEffect as StatusEffectInstance # For active statuses
    # This import was missing in the original file for the __main__ block, adding it here for completeness
    # although the __main__ block itself is commented out.
    from unittest.mock import MagicMock


async def calculate_effective_stats(
    db_service: "DBService",
    guild_id: str,
    entity_id: str,
    entity_type: str,
    rules_config_data: CoreGameRulesConfig,
    character_manager: "CharacterManager",
    npc_manager: "NpcManager",
    item_manager: "ItemManager",
    status_manager: "StatusManager"
) -> Dict[str, Any]:
    """
    Calculates effective stats for an entity by applying bonuses in the correct order:
    1. Base Stats & Skills.
    2. Flat Bonuses (from items, then statuses).
    3. Percentage Increase Bonuses (from items, then statuses, applied to sum of base + flats).
    4. Multiplier Bonuses (from items, then statuses, applied to sum of base + flats + percentages).
    5. Stat Caps.
    6. Derived Stats.
    7. Collects granted abilities/skills throughout.
    """
    raw_stats: Dict[str, Any] = {} # Holds initial stats + skills
    granted_abilities_skills: List[GrantedAbilityOrSkill] = []

    entity: Optional[Union["Character", "NpcModel"]] = None
    if entity_type.lower() == "character" or entity_type.lower() == "player":
        entity = await character_manager.get_character(guild_id, entity_id)
        entity_type = "Character"
    elif entity_type.lower() == "npc":
        entity = await npc_manager.get_npc(guild_id, entity_id)
        entity_type = "NPC"
    else:
        raise ValueError(f"Unknown entity_type: {entity_type}. Expected 'Character' or 'NPC'.")

    if not entity:
        print(f"Error: Entity {entity_id} of type {entity_type} not found in guild {guild_id}.")
        return {}

    # Initialize with base stat definitions (default values)
    for stat_id_key, stat_def in rules_config_data.base_stats.items():
        raw_stats[stat_id_key.lower()] = stat_def.default_value

    # Override with entity's stored base stats
    base_stats_from_entity = getattr(entity, 'stats', {})
    if isinstance(base_stats_from_entity, str):
        try: base_stats_from_entity = json.loads(base_stats_from_entity)
        except json.JSONDecodeError: base_stats_from_entity = {}
    for stat_name, value in base_stats_from_entity.items():
        raw_stats[stat_name.lower()] = value

    # Load base skills
    base_skills_source = {}
    if entity_type == "Character":
        skills_json = getattr(entity, 'skills_data_json', '{}')
        if isinstance(skills_json, str): base_skills_source = json.loads(skills_json or '{}')
        elif isinstance(skills_json, dict): base_skills_source = skills_json
    elif entity_type == "NPC":
        skills_attr = getattr(entity, 'skills', getattr(entity, 'skills_data_json', {}))
        if isinstance(skills_attr, str): base_skills_source = json.loads(skills_attr or '{}')
        elif isinstance(skills_attr, dict): base_skills_source = skills_attr

    for skill_name, value in base_skills_source.items():
        raw_stats[skill_name.lower()] = value

    # --- Stage 1: Apply Flat Bonuses ---
    stats_after_flats = raw_stats.copy()

    # Get item modifiers
    equipped_item_instances = []
    if hasattr(entity, 'inventory'):
        raw_inventory = getattr(entity, 'inventory')
        if isinstance(raw_inventory, str): raw_inventory = json.loads(raw_inventory or '[]')
        if isinstance(raw_inventory, list):
            equipped_item_instances = [item for item in raw_inventory if isinstance(item, dict) and item.get("equipped")]

    item_modifiers_all: List[StatModifierRule] = []
    for item_instance_data in equipped_item_instances:
        template_id = item_instance_data.get("template_id")
        item_template: Optional["ItemTemplate"] = await item_manager.get_item_template(guild_id, template_id) if template_id else None
        if item_template and item_template.properties: # Check if properties exist
            # Access modifiers and granted abilities/skills from the properties dictionary
            stat_modifiers_data = item_template.properties.get('stat_modifiers')
            if isinstance(stat_modifiers_data, list):
                    # Convert dicts back to StatModifierRule objects if necessary, or ensure they are stored as such
                    for mod_data in stat_modifiers_data:
                        if isinstance(mod_data, dict):
                            item_modifiers_all.append(StatModifierRule(**mod_data))
                        elif isinstance(mod_data, StatModifierRule): # If already objects
                            item_modifiers_all.append(mod_data)

            grants_data = item_template.properties.get('grants_abilities_or_skills')
            if isinstance(grants_data, list):
                for grant_data in grants_data:
                    if isinstance(grant_data, dict):
                        granted_abilities_skills.append(GrantedAbilityOrSkill(**grant_data))
                    elif isinstance(grant_data, GrantedAbilityOrSkill): # If already objects
                        granted_abilities_skills.append(grant_data)

    # Apply flat item bonuses
    for mod_rule in item_modifiers_all:
        if mod_rule.bonus_type == "flat":
            stat_key = mod_rule.stat_name.lower()
            stats_after_flats[stat_key] = stats_after_flats.get(stat_key, 0.0) + mod_rule.value

    # Get status effect modifiers
    active_status_instances: List["StatusEffectInstance"] = await status_manager.get_active_statuses_for_entity(guild_id, entity_id, entity_type)
    status_modifiers_all: List[StatModifierRule] = []
    for status_instance in active_status_instances:
            # Changed status_instance.template_id to status_instance.status_type
            # Also, status_template type hint should be StatusEffectDefinition from rules_schema
            status_template: Optional[StatusEffectDefinition] = await status_manager.get_status_template(guild_id, status_instance.status_type)
            # This block needs to be aligned with the line above
            if status_template:
                if hasattr(status_template, 'stat_modifiers') and isinstance(status_template.stat_modifiers, list):
                    status_modifiers_all.extend(status_template.stat_modifiers)
                if hasattr(status_template, 'grants_abilities_or_skills') and isinstance(status_template.grants_abilities_or_skills, list):
                    granted_abilities_skills.extend(status_template.grants_abilities_or_skills)

    # Apply flat status bonuses
    for mod_rule in status_modifiers_all:
        if mod_rule.bonus_type == "flat":
            stat_key = mod_rule.stat_name.lower()
            stats_after_flats[stat_key] = stats_after_flats.get(stat_key, 0.0) + mod_rule.value

    # --- Stage 2: Apply Percentage Increases ---
    stats_after_percentages = stats_after_flats.copy()

    # Item percentage increases
    for mod_rule in item_modifiers_all:
        if mod_rule.bonus_type == "percentage_increase":
            stat_key = mod_rule.stat_name.lower()
            base_value_for_calc = stats_after_flats.get(stat_key, 0.0) # Applied to (Base + All Flats)
            stats_after_percentages[stat_key] = stats_after_percentages.get(stat_key, 0.0) + (base_value_for_calc * (mod_rule.value / 100.0))

    # Status percentage increases
    for mod_rule in status_modifiers_all:
        if mod_rule.bonus_type == "percentage_increase":
            stat_key = mod_rule.stat_name.lower()
            base_value_for_calc = stats_after_flats.get(stat_key, 0.0) # Applied to (Base + All Flats)
            stats_after_percentages[stat_key] = stats_after_percentages.get(stat_key, 0.0) + (base_value_for_calc * (mod_rule.value / 100.0))

    # --- Stage 3: Apply Multipliers ---
    stats_after_multipliers = stats_after_percentages.copy()

    # Item multipliers
    for mod_rule in item_modifiers_all:
        if mod_rule.bonus_type == "multiplier":
            stat_key = mod_rule.stat_name.lower()
            base_value_for_calc = stats_after_percentages.get(stat_key, 0.0) # Applied to (Base + Flats + Percentages)
            stats_after_multipliers[stat_key] = base_value_for_calc * mod_rule.value

    # Status multipliers
    for mod_rule in status_modifiers_all:
        if mod_rule.bonus_type == "multiplier":
            stat_key = mod_rule.stat_name.lower()
            base_value_for_calc = stats_after_percentages.get(stat_key, 0.0) # Applied to (Base + Flats + Percentages)
            stats_after_multipliers[stat_key] = stats_after_multipliers.get(stat_key, base_value_for_calc) * mod_rule.value


    effective_stats = stats_after_multipliers

    # --- Stage 4: Apply Caps ---
    for stat_id_key, stat_def in rules_config_data.base_stats.items():
        stat_key = stat_id_key.lower()
        if stat_key in effective_stats:
            current_value = float(effective_stats[stat_key])
            min_val = float(stat_def.min_value)
            max_val = float(stat_def.max_value)
            effective_stats[stat_key] = max(min_val, min(current_value, max_val))
            if isinstance(stat_def.default_value, int):
                 effective_stats[stat_key] = round(effective_stats[stat_key])

    # --- Stage 5: Calculate Derived Stats ---
    # The existing derived_stat_rules might provide a generic way.
    # The following calculations are specific overrides or additions as per the subtask.

    # Get effective base stats for calculation (ensure keys are lowercase)
    eff_base_strength = effective_stats.get("base_strength", 0.0) # Default to 0.0 for calculations
    eff_base_dexterity = effective_stats.get("base_dexterity", 0.0)
    eff_base_constitution = effective_stats.get("base_constitution", 0.0)
    # eff_base_intelligence = effective_stats.get("base_intelligence", 0.0) # Not used in current formulas
    # eff_base_wisdom = effective_stats.get("base_wisdom", 0.0)
    # eff_base_charisma = effective_stats.get("base_charisma", 0.0)

    entity_level = getattr(entity, 'level', 1) # Get level from entity, default to 1
    if not isinstance(entity_level, (int, float)) or entity_level < 1:
        entity_level = 1 # Ensure level is a positive number for calculations

    # Max HP Calculation
    # Max HP = 10 (base_offset) + constitution * 2 (scaling_factor) + level * 5 (level_factor)
    # These factors could also come from rules_config_data if a more generic system is desired later.
    max_hp_base_offset = 10.0
    max_hp_con_scaling_factor = 2.0
    max_hp_level_scaling_factor = 5.0
    effective_stats['max_hp'] = round(
        max_hp_base_offset +
        (eff_base_constitution * max_hp_con_scaling_factor) +
        (entity_level * max_hp_level_scaling_factor)
    )

    # Attack Calculation
    # Attack = strength + level / 2
    attack_level_divisor = 2.0
    effective_stats['attack'] = round(eff_base_strength + (entity_level / attack_level_divisor))

    # Defense Calculation
    # Defense = dexterity + level / 2
    defense_level_divisor = 2.0
    effective_stats['defense'] = round(eff_base_dexterity + (entity_level / defense_level_divisor))

    # Note: Current HP (entity.hp) is not managed here.
    # The caller (e.g., CharacterManager) should handle adjusting current HP if max_hp changes.

    # Process any other generic derived_stat_rules from config, if they don't conflict.
    # The current derived_stat_rules logic for max_hp was:
    # if rules_config_data.derived_stat_rules:
    #     con_val = effective_stats.get("constitution", ...)
    #     hp_per_con = rules_config_data.derived_stat_rules.get('hp_per_constitution_point', 10.0)
    #     base_hp_offset_config = rules_config_data.derived_stat_rules.get('base_hp_offset', 0.0)
    #     max_hp_base_default_obj = rules_config_data.base_stats.get("MAX_HP")
    #     max_hp_base_default = max_hp_base_default_obj.default_value if max_hp_base_default_obj else 0.0
    #     # Only apply if max_hp is still at its default (i.e., not set by specific items/effects directly)
    #     if effective_stats.get("max_hp") == max_hp_base_default:
    #          effective_stats['max_hp'] = round(float(con_val) * hp_per_con + base_hp_offset_config)
    # The new specific formulas for max_hp, attack, defense take precedence as per the task.
    # If other derived stats were defined in derived_stat_rules, their calculation could be added here.

    effective_stats['granted_abilities_skills'] = [gas.model_dump(mode='python') for gas in granted_abilities_skills]
    return effective_stats

# --- Main Test Block (Commented out as per plan) ---
# if __name__ == '__main__':
#     from unittest.mock import MagicMock # Added import
#     # ... (Test code would need significant mocking of managers) ...
#     # print("Stats Calculator module loaded. Run tests via unittest framework.")
print("Stats Calculator module loaded.")
