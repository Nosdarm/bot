"""
Calculates effective character/NPC statistics based on base stats, items, and status effects.

This module provides the `calculate_effective_stats` function, which is the core
logic for determining an entity's final stats after all modifications are applied.
It uses the `CoreGameRulesConfig` to understand base stat definitions, item effects,
and status effects.
"""
import json
import asyncio # For __main__
from typing import Dict, Any, List, Optional, Tuple, Union

# Assuming DBService provides an async interface. For testing, we'll use a mock.
# from bot.services.db_service import DBService
from bot.ai.rules_schema import CoreGameRulesConfig, StatModifierRule, GrantedAbilityOrSkill

# Added imports for type hinting actual managers
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.models.character import Character
    from bot.game.models.npc import NPC as NpcModel
    from bot.game.models.item import ItemTemplate
    from bot.game.models.status_effect import StatusEffectTemplate


# --- Helper: Mock DB Service and Data for __main__ testing ---
class MockDBService: # Keep for __main__ test
    """
    A mock database service to simulate fetching entity data.
    """
    async def fetchone(self, query: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        print(f"MockDBService: Fetchone query: {query}, params: {params}")
        entity_id = params[0] if params else None
        if "FROM players" in query and entity_id == "player_test_1":
            return {
                "id": "player_test_1",
                "stats": json.dumps({"strength": 10, "dexterity": 12, "wisdom": 14, "constitution": 13}),
                "skills_data_json": json.dumps({"perception": 2, "stealth": 1, "athletics": 3}),
                "inventory": json.dumps([
                    {"item_id": "item_sword_of_strength", "template_id": "tpl_sword_str", "equipped": True, "slot": "main_hand"},
                    {"item_id": "item_amulet_of_health", "template_id": "tpl_amulet_con", "equipped": True, "slot": "neck"},
                    {"item_id": "item_boots_of_speed", "template_id": "tpl_boots_dex_multi", "equipped": True, "slot": "feet"},
                    {"item_id": "item_unused_potion", "template_id": "tpl_potion_heal", "equipped": False}
                ]),
                "status_effects": json.dumps([ # List of status effect IDs currently active
                    {"id": "sef_blessed", "duration": 5},
                    {"id": "sef_weakened", "duration": 3, "source_item": "item_cursed_ring"}
                ])
            }
        elif "FROM npcs" in query and entity_id == "npc_test_1":
             return {
                "id": "npc_test_1",
                "stats": json.dumps({"strength": 15, "dexterity": 10, "wisdom": 8}),
                "skills_data": json.dumps({"intimidation": 4}), # Note: 'skills_data' for NPC in models
                "inventory": json.dumps([
                    {"item_id": "item_rusty_axe", "template_id": "tpl_axe_basic", "equipped": True, "slot": "main_hand"}
                ]),
                "status_effects": json.dumps([])
            }
        return None

    async def fetchall(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        # Not used directly by calculate_effective_stats for now, but good for a mock.
        print(f"MockDBService: Fetchall query: {query}, params: {params}")
        return []

async def calculate_effective_stats(
    db_service: "DBService",
    guild_id: str, # Added guild_id
    entity_id: str,
    entity_type: str, # "player" or "npc" - consider "Character" or "NPC" to match model names
    rules_config_data: CoreGameRulesConfig,
    character_manager: "CharacterManager",
    npc_manager: "NpcManager",
    item_manager: "ItemManager",
    status_manager: "StatusManager"
) -> Dict[str, Any]:
    """Calculates effective stats for an entity.

    This function computes the final statistics of a player or NPC by:
    1.  Starting with base stats (from entity data or defaults in rules_config).
    2.  Loading base skills.
    3.  Applying flat bonuses from equipped items.
    4.  Applying multiplier bonuses from equipped items.
    5.  Applying flat bonuses from active status effects.
    6.  Applying multiplier bonuses from active status effects.
    7.  Applying min/max caps to stats as defined in rules_config.
    8.  Collecting any abilities or skills granted by items or statuses.

    The order of operations for stat modification is generally:
    base -> flat bonuses -> multipliers -> caps.

    Args:
        db_service: An instance of the database service (or a mock) to fetch entity data.
        entity_id: The ID of the player or NPC.
        entity_type: A string indicating the type of entity ("player" or "npc").
        rules_config_data: A CoreGameRulesConfig object containing game rule definitions
                           (base stats, item effects, status effects).

    Returns:
        A dictionary where keys are stat names (lowercase) and values are their
        effective calculated values. Includes a special key 'granted_abilities_skills'
        listing any abilities/skills granted by effects. Returns an empty dict if
        the entity is not found.

    Raises:
        ValueError: If an unknown `entity_type` is provided.
    """
    effective_stats: Dict[str, Any] = {}
    granted_abilities_skills: List[GrantedAbilityOrSkill] = []

    # 1. Fetch Full Entity Object
    entity: Optional[Union["Character", "NpcModel"]] = None
    if entity_type.lower() == "character" or entity_type.lower() == "player": # Allow "player" for compatibility
        entity = await character_manager.get_character(guild_id, entity_id)
        entity_type = "Character" # Normalize
    elif entity_type.lower() == "npc":
        entity = await npc_manager.get_npc(guild_id, entity_id)
        entity_type = "NPC" # Normalize
    else:
        raise ValueError(f"Unknown entity_type: {entity_type}. Expected 'Character' or 'NPC'.")

    if not entity:
        print(f"Error: Entity {entity_id} of type {entity_type} not found in guild {guild_id}.")
        return {}

    # Initialize with base stats defined in rules_config, applying defaults
    for stat_id, stat_def in rules_config_data.base_stats.items():
        effective_stats[stat_id.lower()] = stat_def.default_value

    # Override with entity's stored base stats
    # Character model has 'stats' (dict), NPC model has 'stats' (dict)
    base_stats_dict = getattr(entity, 'stats', {})
    if isinstance(base_stats_dict, str): # Handle if stats are stored as JSON string
        try: base_stats_dict = json.loads(base_stats_dict)
        except json.JSONDecodeError: base_stats_dict = {}

    for stat_name, value in base_stats_dict.items():
        effective_stats[stat_name.lower()] = value

    # Initialize with base skills
    # Character model has 'skills_data_json', NPC model has 'skills' (dict) or 'skills_data_json'
    base_skills_source = {}
    if entity_type == "Character":
        skills_json = getattr(entity, 'skills_data_json', '{}')
        if isinstance(skills_json, str):
            try: base_skills_source = json.loads(skills_json)
            except json.JSONDecodeError: base_skills_source = {}
        elif isinstance(skills_json, dict): # If already a dict
            base_skills_source = skills_json
    elif entity_type == "NPC":
        # NPC model might have 'skills' as a dict or 'skills_data_json'
        skills_attr = getattr(entity, 'skills', getattr(entity, 'skills_data_json', {}))
        if isinstance(skills_attr, str):
            try: base_skills_source = json.loads(skills_attr)
            except json.JSONDecodeError: base_skills_source = {}
        elif isinstance(skills_attr, dict):
            base_skills_source = skills_attr

    for skill_name, value in base_skills_source.items():
        effective_stats[skill_name.lower()] = value

    # --- Helper to apply modifiers ---
    def apply_stat_modifiers_to_dict(current_stats: Dict[str, Any],
                                     modifiers: List[StatModifierRule],
                                     is_multiplier_pass: bool):
        for mod_rule in modifiers:
            stat_key = mod_rule.stat_name.lower()
            if stat_key not in current_stats: # Initialize if stat is new (e.g. resistances)
                # Try to get a default from base_stats in rules_config if it's a known base stat
                # Otherwise, assume 0 for things like attack_bonus, resistances etc.
                base_stat_def = rules_config_data.base_stats.get(mod_rule.stat_name.upper()) # Base stats are keyed by UPPER
                current_stats[stat_key] = base_stat_def.default_value if base_stat_def else 0.0

            if mod_rule.bonus_type == "flat" and not is_multiplier_pass:
                current_stats[stat_key] += mod_rule.value
            elif mod_rule.bonus_type == "multiplier" and is_multiplier_pass:
                 # Multipliers apply to the value *after* all flat bonuses.
                 # This means multipliers should ideally stack multiplicatively with each other if multiple exist.
                 # E.g., stat * val1 * val2. Or additively: stat * (1 + m1 + m2)
                 # Current simple model: stat = stat_after_flat_bonuses * multiplier_value.
                 # If multiple multipliers, this will take the last one.
                 # More robust: collect all multipliers, sum them (e.g. +10% and +20% = +30%), then apply once.
                 # Or, apply them sequentially: stat = stat * m1; stat = stat * m2;
                 # For now, let's assume a simple sequential application of multipliers on the post-flat-bonus value.
                 # This means the order of multiplier effects might matter if they are not structured carefully.
                 # A common approach: base_value * (1 + sum_of_percentage_increases) * product_of_multipliers
                 # For simplicity here: value from stats_before_multipliers * mod_rule.value
                 # This needs careful thought for final game balance.
                 # Let's assume multipliers are applied to the value that already includes flat bonuses from *other* sources
                 # but not its own previous multiplier passes. This is tricky.
                 # Safest for now: stat_value_with_flats * (1 + percentage_bonus) or stat_value_with_flats * multiplier
                 # This example will use: current_stat_value * rule_value (e.g. current_dex * 1.1 for +10%)

                 # Simplified multiplier: applies to current value. If multiple multipliers, they stack.
                 current_stats[stat_key] *= mod_rule.value
            elif mod_rule.bonus_type == "percentage_increase" and not is_multiplier_pass: # Treat as flat for now, apply before multipliers
                 # This should ideally apply to a "base" value of the stat.
                 # For now, adding a percentage of the current stat value (after prior flat bonuses).
                 base_for_percentage = stats_before_multipliers.get(stat_key, current_stats.get(stat_key, 0))
                 current_stats[stat_key] += base_for_percentage * (mod_rule.value / 100.0)


    # Store initial stats (base + skills) before item/status effects for precise multiplier calculations
    stats_after_base = effective_stats.copy()

    # --- Item Effects ---
    # Assumes entity model has 'inventory' (list of item instances/dicts) and 'equipment' (dict slot_id -> item_instance_id)
    # Or, CharacterManager/NpcManager provides a way to get equipped items.
    # For now, let's assume `entity.inventory` contains items with an `equipped` flag and `template_id`.

    equipped_item_instances = []
    if hasattr(entity, 'inventory'): # Character model might have this
        raw_inventory = getattr(entity, 'inventory')
        if isinstance(raw_inventory, str): # If inventory is JSON string
            try: raw_inventory = json.loads(raw_inventory)
            except json.JSONDecodeError: raw_inventory = []
        if isinstance(raw_inventory, list):
            equipped_item_instances = [item for item in raw_inventory if isinstance(item, dict) and item.get("equipped")]

    # Collect all item modifiers first
    all_item_stat_modifiers: List[StatModifierRule] = []
    for item_instance_data in equipped_item_instances:
        template_id = item_instance_data.get("template_id")
        item_template: Optional["ItemTemplate"] = await item_manager.get_item_template(guild_id, template_id) if template_id else None
        if item_template and hasattr(item_template, 'stat_modifiers') and isinstance(item_template.stat_modifiers, list):
            all_item_stat_modifiers.extend(item_template.stat_modifiers)
            # Collect granted abilities/skills from items
            if hasattr(item_template, 'grants_abilities_or_skills') and isinstance(item_template.grants_abilities_or_skills, list):
                granted_abilities_skills.extend(item_template.grants_abilities_or_skills)

    # Apply flat item bonuses
    apply_stat_modifiers_to_dict(effective_stats, all_item_stat_modifiers, is_multiplier_pass=False, base_for_percentage_calc=stats_after_base)
    stats_after_item_flats = effective_stats.copy()
    # Apply multiplier item bonuses (using stats_after_item_flats as the base for multiplication if needed by rule)
    apply_stat_modifiers_to_dict(effective_stats, all_item_stat_modifiers, is_multiplier_pass=True, base_for_multiplier_calc=stats_after_item_flats)


    # --- Status Effects ---
    active_status_effect_instances = await status_manager.get_active_statuses_for_entity(guild_id, entity_id, entity_type)

    all_status_stat_modifiers: List[StatModifierRule] = []
    for status_instance in active_status_effect_instances:
        status_template: Optional["StatusEffectTemplate"] = await status_manager.get_status_template(guild_id, status_instance.template_id)
        if status_template and hasattr(status_template, 'stat_modifiers') and isinstance(status_template.stat_modifiers, list):
            all_status_stat_modifiers.extend(status_template.stat_modifiers)
            # Collect granted abilities/skills from statuses
            if hasattr(status_template, 'grants_abilities_or_skills') and isinstance(status_template.grants_abilities_or_skills, list):
                granted_abilities_skills.extend(status_template.grants_abilities_or_skills)

    # Apply flat status bonuses (base for percentage is after item flats and multipliers)
    # This means status percentages apply to stats already modified by items.
    stats_before_status_flats = effective_stats.copy() # Stats after all item effects
    apply_stat_modifiers_to_dict(effective_stats, all_status_stat_modifiers, is_multiplier_pass=False, base_for_percentage_calc=stats_before_status_flats)
    stats_after_status_flats = effective_stats.copy()
    # Apply multiplier status bonuses
    apply_stat_modifiers_to_dict(effective_stats, all_status_stat_modifiers, is_multiplier_pass=True, base_for_multiplier_calc=stats_after_status_flats)

    # --- Derived Stats Calculation ---
    # Example: Max HP from Constitution
    # This should use rules from rules_config_data.derived_stat_rules or similar
    if 'constitution' in effective_stats and rules_config_data.derived_stat_rules:
        hp_per_con = rules_config_data.derived_stat_rules.get('hp_per_constitution_point', 10)
        base_hp_offset = rules_config_data.derived_stat_rules.get('base_hp_offset', 0)
        # Max HP might also be a base stat itself that gets modified, or purely derived.
        # Assuming it can be derived if not directly set or modified by items/statuses above.
        # If 'max_hp' was already calculated via items/statuses, this might override or add to it.
        # For now, let's assume it's a derivation based on final CON unless already heavily modified.
        # A common pattern: BaseHP + (CON_modifier * Level) + OtherBonuses
        # Simple for now: CON * factor + offset
        if 'max_hp' not in effective_stats or effective_stats.get('max_hp',0) == rules_config_data.base_stats.get("MAX_HP", StatModifierRule(stat_name="",bonus_type="",value=0)).default_value : # only if not modified by items/status
             effective_stats['max_hp'] = round(effective_stats['constitution'] * hp_per_con + base_hp_offset)


    # --- Apply Caps ---
    for stat_id, stat_def in rules_config_data.base_stats.items():
        stat_key = stat_id.lower()
        if stat_key in effective_stats:
            effective_stats[stat_key] = max(stat_def.min_value, min(effective_stats[stat_key], stat_def.max_value))
            # Ensure integers for stats that should be integers (like HP, core attributes after all calcs)
            if isinstance(stat_def.default_value, int) or isinstance(stat_def.min_value, int): # Heuristic
                 effective_stats[stat_key] = round(effective_stats[stat_key])


    effective_stats['granted_abilities_skills'] = [gas.model_dump() for gas in granted_abilities_skills] # Convert Pydantic to dict for output

    return effective_stats

# --- Main Test Block ---
if __name__ == '__main__':

    # Sample CoreGameRulesConfig data for testing
    sample_rules_dict = {
        "base_stats": {
            "STRENGTH": {"name_i18n": {"en": "Strength"}, "description_i18n": {}, "default_value": 10, "min_value": 1, "max_value": 30},
            "DEXTERITY": {"name_i18n": {"en": "Dexterity"}, "description_i18n": {}, "default_value": 10, "min_value": 1, "max_value": 30},
            "CONSTITUTION": {"name_i18n": {"en": "Constitution"}, "description_i18n": {}, "default_value": 10, "min_value": 1, "max_value": 30},
            "WISDOM": {"name_i18n": {"en": "Wisdom"}, "description_i18n": {}, "default_value": 10, "min_value": 1, "max_value": 30},
            "MAX_HP": {"name_i18n": {"en": "Max HP"}, "description_i18n": {}, "default_value": 10, "min_value": 1, "max_value": 999},
            "PERCEPTION": {"name_i18n": {"en": "Perception Skill"}, "description_i18n": {}, "default_value": 0, "min_value": -5, "max_value": 20},
            "STEALTH": {"name_i18n": {"en": "Stealth Skill"}, "description_i18n": {}, "default_value": 0, "min_value": -5, "max_value": 20},
            "ATHLETICS": {"name_i18n": {"en": "Athletics Skill"}, "description_i18n": {}, "default_value": 0, "min_value": -5, "max_value": 20},
        },
        "item_effects": {
            "tpl_sword_str": {
                "stat_modifiers": [{"stat_name": "strength", "bonus_type": "flat", "value": 2}]
            },
            "tpl_amulet_con": {
                "stat_modifiers": [{"stat_name": "constitution", "bonus_type": "flat", "value": 5}] # Big boost
            },
            "tpl_boots_dex_multi": { # Example of a multiplier item
                "stat_modifiers": [{"stat_name": "dexterity", "bonus_type": "multiplier", "value": 1.1}] # +10% dexterity
            }
        },
        "status_effects": {
            "sef_blessed": {
                "id": "sef_blessed", "name_i18n": {"en": "Blessed"}, "description_i18n": {},
                "stat_modifiers": [{"stat_name": "strength", "bonus_type": "flat", "value": 1},
                                   {"stat_name": "perception", "bonus_type": "flat", "value": 2}]
            },
            "sef_weakened": {
                "id": "sef_weakened", "name_i18n": {"en": "Weakened"}, "description_i18n": {},
                "stat_modifiers": [{"stat_name": "strength", "bonus_type": "flat", "value": -2}]
            }
        },
        "checks": {}, "damage_types": {}, "xp_rules": None, "loot_tables": {},
        "action_conflicts": [], "location_interactions": {}
    }
    test_game_rules = CoreGameRulesConfig.parse_obj(sample_rules_dict)
    mock_db = MockDBService()

    async def run_player_test():
        print("\n--- Testing Player with Items and Statuses ---")
        player_id = "player_test_1"
        # Base Player Stats: {"strength": 10, "dexterity": 12, "wisdom": 14, "constitution": 13}
        # Base Player Skills: {"perception": 2, "stealth": 1, "athletics": 3}

        # Expected calculation walk-through for player_test_1:
        # Initial Stats (from DB + defaults):
        #   strength: 10, dexterity: 12, wisdom: 14 (used as default), constitution: 13
        #   max_hp: 10 (default from base_stats rule)
        #   perception: 2, stealth: 1, athletics: 3

        # Item Effects (Flat Pass):
        # - Sword of Strength: strength +2 -> strength = 12
        # - Amulet of Health: constitution +5 -> constitution = 18
        # Stats after item flats: strength: 12, dexterity: 12, wisdom: 14, constitution: 18, perception: 2, ...

        # Item Effects (Multiplier Pass):
        # - Boots of Speed: dexterity * 1.1 -> dexterity = 12 * 1.1 = 13.2
        # Stats after item multipliers: strength: 12, dexterity: 13.2, wisdom: 14, constitution: 18, perception: 2, ...

        # Status Effects (Flat Pass):
        # - Blessed: strength +1 -> strength = 12 + 1 = 13
        #            perception +2 -> perception = 2 + 2 = 4
        # - Weakened: strength -2 -> strength = 13 - 2 = 11
        # Stats after status flats (applied to current effective stats):
        #   strength: 11 (10 base +2 item_sword +1 blessed -2 weakened)
        #   dexterity: 13.2 (12 base * 1.1 item_boots)
        #   constitution: 18 (13 base +5 item_amulet)
        #   wisdom: 14 (base)
        #   perception: 4 (2 base +2 blessed)
        #   stealth: 1 (base)
        #   athletics: 3 (base)
        #   max_hp: 10 (default)

        # Status Effects (Multiplier Pass) - None in this example

        # Final Clamping/Rounding:
        #   dexterity: round(13.2) = 13
        #   (Other stats are within min/max from base_stats and are integers already)

        effective_stats = await calculate_effective_stats(mock_db, player_id, "player", test_game_rules)
        print(f"Effective Stats for {player_id}: {json.dumps(effective_stats, indent=2)}")

        assert effective_stats['strength'] == 11
        assert effective_stats['dexterity'] == 13 # 12 * 1.1 = 13.2, rounded to 13
        assert effective_stats['constitution'] == 18
        assert effective_stats['wisdom'] == 14
        assert effective_stats['perception'] == 4
        assert effective_stats['stealth'] == 1
        assert effective_stats['athletics'] == 3
        assert effective_stats['max_hp'] == 10 # Default, as no modifiers applied
        assert 'granted_abilities_skills' in effective_stats
        print(f"Granted abilities/skills for {player_id}: {effective_stats['granted_abilities_skills']}")


    async def run_npc_test_no_effects():
        print("\n--- Testing NPC with No Special Items/Statuses ---")
        npc_id = "npc_test_1"
        # Base NPC Stats: {"strength": 15, "dexterity": 10, "wisdom": 8}
        # Base NPC Skills: {"intimidation": 4} (not in CoreGameRulesConfig.base_stats, so treated as custom skill)
        # Item: Rusty Axe (tpl_axe_basic) - no effect defined in sample_rules_dict.item_effects
        # Statuses: None

        # Expected: Base stats from DB + defaults from CoreGameRulesConfig.base_stats for any missing
        #   strength: 15, dexterity: 10, wisdom: 8
        #   constitution: 10 (default)
        #   max_hp: 10 (default)
        #   perception: 0 (default)
        #   stealth: 0 (default)
        #   athletics: 0 (default)
        #   intimidation: 4 (from skills_data)

        effective_stats_npc = await calculate_effective_stats(mock_db, npc_id, "npc", test_game_rules)
        print(f"Effective Stats for {npc_id}: {json.dumps(effective_stats_npc, indent=2)}")
        assert effective_stats_npc['strength'] == 15
        assert effective_stats_npc['dexterity'] == 10
        assert effective_stats_npc['wisdom'] == 8
        assert effective_stats_npc['constitution'] == 10 # Default
        assert effective_stats_npc.get('intimidation', 0) == 4 # Custom skill from NPC's skills_data

    async def main():
        await run_player_test()
        await run_npc_test_no_effects()

    asyncio.run(main())

print("Stats Calculator module loaded.")
