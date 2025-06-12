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
        if item_template:
            if hasattr(item_template, 'stat_modifiers') and isinstance(item_template.stat_modifiers, list):
                item_modifiers_all.extend(item_template.stat_modifiers)
            if hasattr(item_template, 'grants_abilities_or_skills') and isinstance(item_template.grants_abilities_or_skills, list):
                granted_abilities_skills.extend(item_template.grants_abilities_or_skills)

    # Apply flat item bonuses
    for mod_rule in item_modifiers_all:
        if mod_rule.bonus_type == "flat":
            stat_key = mod_rule.stat_name.lower()
            stats_after_flats[stat_key] = stats_after_flats.get(stat_key, 0.0) + mod_rule.value

    # Get status effect modifiers
    active_status_instances: List["StatusEffectInstance"] = await status_manager.get_active_statuses_for_entity(guild_id, entity_id, entity_type)
    status_modifiers_all: List[StatModifierRule] = []
    for status_instance in active_status_instances:
        status_template: Optional["StatusEffectTemplate"] = await status_manager.get_status_template(guild_id, status_instance.template_id)
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
            # If multiple multipliers for the same stat, they stack: (value * item_multi_1) * status_multi_1
            stats_after_multipliers[stat_key] = stats_after_multipliers.get(stat_key, base_value_for_calc) * mod_rule.value


    effective_stats = stats_after_multipliers # This is now the dictionary to finalize

    # --- Stage 4: Apply Caps ---
    for stat_id_key, stat_def in rules_config_data.base_stats.items():
        stat_key = stat_id_key.lower()
        if stat_key in effective_stats:
            # Ensure value is float before min/max if it could be int from defaults
            current_value = float(effective_stats[stat_key])
            min_val = float(stat_def.min_value)
            max_val = float(stat_def.max_value)

            effective_stats[stat_key] = max(min_val, min(current_value, max_val))

            # Round if the original base stat default was an integer (heuristic for integer-like stats)
            if isinstance(stat_def.default_value, int):
                 effective_stats[stat_key] = round(effective_stats[stat_key])

    # --- Stage 5: Calculate Derived Stats ---
    if rules_config_data.derived_stat_rules:
        # Example: Max HP from Constitution
        con_val = effective_stats.get("constitution", rules_config_data.base_stats.get("CONSTITUTION", MagicMock(default_value=10)).default_value)
        hp_per_con = rules_config_data.derived_stat_rules.get('hp_per_constitution_point', 10.0)
        base_hp_offset = rules_config_data.derived_stat_rules.get('base_hp_offset', 0.0)

        # Only set max_hp if it wasn't already modified by items/statuses (or if it's still at default)
        # This logic might need adjustment based on whether derived stats should override or add to existing modified stats.
        # For now, if max_hp came from base_stats default, recalculate it.
        max_hp_base_default = rules_config_data.base_stats.get("MAX_HP", MagicMock(default_value=0)).default_value
        if effective_stats.get("max_hp") == max_hp_base_default :
             effective_stats['max_hp'] = round(float(con_val) * hp_per_con + base_hp_offset)

        # Example: Attack Bonus from Strength or Dexterity (conceptual)
        # str_val = effective_stats.get("strength", 10)
        # dex_val = effective_stats.get("dexterity", 10)
        # attack_bonus_base_stat = "strength" # This could be rule-driven (e.g. finesse weapons use DEX)
        # primary_attack_stat_val = effective_stats.get(attack_bonus_base_stat, 10)
        # effective_stats["attack_bonus"] = effective_stats.get("attack_bonus",0) + ((primary_attack_stat_val - 10) // 2) # D&D style modifier

    effective_stats['granted_abilities_skills'] = [gas.model_dump(mode='python') for gas in granted_abilities_skills]
    return effective_stats

# --- Main Test Block (Commented out as per plan) ---
# if __name__ == '__main__':
#     # ... (Test code would need significant mocking of managers) ...
#     print("Stats Calculator module loaded. Run tests via unittest framework.")
print("Stats Calculator module loaded.")
