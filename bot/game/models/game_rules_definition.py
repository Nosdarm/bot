# bot/game/models/game_rules_definition.py
"""
Defines the comprehensive structure for game rules.
This structure will be used as a schema for the 'game_rules' section
in settings.json and potentially for per-campaign rule overrides in the database.
"""

GAME_RULES_STRUCTURE = {
    "general_settings": {
        "max_character_level": 20,
        "attribute_cap": 20,
        "skill_cap": 100,
    },
    "experience_rules": {
        "xp_to_level_up": {  # Table defining XP needed for each level
            # Example: "level_2": 1000, "level_3": 2500, ... (or a formula type)
            "type": "table", # Could also be "formula" e.g., "base_xp * (level^exponent)"
            "values": {
                "1": 0,
                "2": 1000,
                "3": 3000,
                "4": 6000,
                "5": 10000,
                # ... up to max_character_level
            },
            # Example for formula based approach (if type was "formula")
            # "formula_base_xp": 1000,
            # "formula_exponent": 1.5,
        },
        "xp_awards": {
            "combat": {
                "base_xp_per_cr": 100, # Base XP per challenge rating unit
                "cr_scaling_factor": 1.2, # How much CR difference affects XP
                "party_bonus_factor": 1.0, # Bonus for full parties, etc.
            },
            "quest": {
                "base_xp_per_difficulty": 200, # Easy, Medium, Hard
                "story_quest_multiplier": 1.5,
            },
            "skill_use": {
                "xp_per_successful_check": 5,
                "difficulty_multiplier": 1.1, # Higher DC checks give more XP
            },
        },
        "party_xp_distribution": {
            "method": "even_split", # Options: "even_split", "contribution_based" (future), "leader_weighted"
            "level_range_penalty": 0.8, # Penalty if party members have too wide level difference
        }
    },
    "character_stats_rules": {
        "attributes": { # Definition of primary attributes
            "strength": {"description": "Physical power and carrying capacity."},
            "dexterity": {"description": "Agility, reflexes, and accuracy."},
            "constitution": {"description": "Health, stamina, and resilience."},
            "intelligence": {"description": "Reasoning, memory, and knowledge."},
            "wisdom": {"description": "Perception, intuition, and willpower."},
            "charisma": {"description": "Force of personality, leadership, and social skills."}
        },
        "attribute_modifier_formula": "(attribute_value - 10) // 2", # Python eval-safe string
        "default_initial_stats": { # Used by RuleEngine.generate_initial_character_stats
            "strength": 10, "dexterity": 10, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10
        },
        "derived_stats": { # Stats calculated from primary attributes or other sources
            "max_health": {
                "base_formula": "10 + constitution_modifier + (level * (5 + constitution_modifier))",
                "per_level_bonus_from_class": True # If class gives bonus HP per level
            },
            "armor_class": {
                "base": 10,
                "dex_modifier_applies": True,
                "max_dex_bonus_from_armor_type": { # For armor types like heavy
                    "heavy": 0, "medium": 2
                }
            },
            "initiative": {"base_stat": "dexterity_modifier"}, # Can add more factors like feats
            # ... other derived stats like movement speed, carry capacity
        }
    },
    "skill_rules": {
        "default_skill_cap": 100,
        "skill_improvement_on_use": {
            "enabled": True,
            "base_chance": 0.1, # Base chance to improve skill on successful use
            "dc_factor": 0.01, # Higher DC increases chance
            "current_skill_factor": -0.005 # Higher current skill decreases chance
        },
        "skill_stat_map": { # Default associated stat for skills (can be overridden by specific check)
            "athletics": "strength", "acrobatics": "dexterity", "stealth": "dexterity",
            "perception": "wisdom", "insight": "wisdom", "survival": "wisdom", "medicine": "wisdom",
            "persuasion": "charisma", "deception": "charisma", "intimidation": "charisma", "performance": "charisma",
            "investigation": "intelligence", "knowledge_arcana": "intelligence",
            "knowledge_history": "intelligence", "knowledge_nature": "intelligence",
            "lockpicking": "dexterity", "pickpocket": "dexterity",
            # ... other skills
        }
    },
    "check_rules": { # General rules for dice checks
        "dice_roll_notation": "NdX+M", # Standard (already supported by RuleEngine)
        "default_roll_formula": "1d20",
        "critical_success": {
            "natural_roll": 20, # On a 1d20
            "auto_succeeds": True,
            "additional_effect": "max_damage_or_double_effect" # Example, needs specific handling
        },
        "critical_failure": {
            "natural_roll": 1, # On a 1d20
            "auto_fails": True,
            "additional_effect": "fumble_or_negative_consequence" # Example
        },
        "difficulty_classes": { # Standard DCs for reference or dynamic calculation
            "very_easy": 5, "easy": 10, "medium": 15, "hard": 20, "very_hard": 25, "nearly_impossible": 30
        },
        "modifier_sources": ["primary_stat", "relevant_skill", "status_effects", "equipment_bonus", "situational_context"]
    },
    "combat_rules": {
        "initiative_formula": "dexterity_modifier + perception_modifier/2", # Example formula
        "surprise_round": {
            "enabled": True,
            "perception_dc_vs_stealth": True, # Stealth check vs Passive Perception
        },
        "attack_roll_formula": "1d20 + attack_bonus + primary_stat_modifier + proficiency_bonus",
        "damage_calculation": {
            "base_damage": "weapon_dice_or_spell_damage",
            "stat_modifier_applies": True, # Str for melee, Dex for ranged/finesse, Spellcasting ability for spells
            "critical_hit_multiplier": 2.0, # e.g., 2.0 for double dice, or "max_then_roll"
            "resistances": {"physical": 0.5, "fire": 0.75}, # Example: key is damage_type, value is multiplier
            "vulnerabilities": {"bludgeoning": 1.5, "cold": 2.0},
            "immunities": ["poison_gas"], # List of damage types
            "damage_types": ["slashing", "piercing", "bludgeoning", "fire", "cold", "lightning", "acid", "poison", "necrotic", "radiant", "psychic", "force", "arcane"]
        },
        "armor_class_calculation": "base_ac_from_armor + dexterity_modifier (up_to_max) + shield_bonus + other_bonuses",
        "death_and_dying": {
            "dying_condition_at_zero_hp": True,
            "death_saves_dc": 10,
            "max_failures": 3,
            "stabilize_on_successes": 3,
            "death_on_massive_damage_threshold": 50 # % of max HP as overkill
        }
    },
    "status_effect_rules": {
        "stacking_rules": {
            "default": "duration_extends", # Options: "duration_extends", "intensity_increases", "not_allowed", "independent"
            "buffs": "intensity_increases_up_to_cap",
            "debuffs": "duration_extends"
        },
        "default_durations": { # In game time units (e.g., rounds or seconds)
            "short": 60, "medium": 300, "long": 3600
        },
        "dispelling_rules": {
            "base_dc": 10,
            "level_modifier": 1 # Per level of the effect being dispelled
        }
    },
    "equipment_rules": {
        "slots": ["main_hand", "off_hand", "head", "chest", "legs", "feet", "hands", "ring1", "ring2", "amulet", "belt"],
        "stat_bonuses_on_items": "defined_in_item_properties", # e.g., item.properties.bonuses = {"strength": 2, "armor_class": 1}
        "skill_bonuses_on_items": "defined_in_item_properties",
        "attunement_limit": 3, # Max number of attuned magic items
        "item_durability": {
            "enabled": False, # Simple system for now
            "degrade_on_use_chance": 0.01,
            "repair_costs_factor": 0.25 # % of item value
        }
    },
    "economy_rules": {
        "base_currency_name": "Gold Pieces",
        "base_item_prices": "defined_in_item_templates_value", # 'value' field in item_templates.json
        "price_multipliers": {
            "location_demand_factor": {"min": 0.8, "max": 1.5}, # Based on location's economy type or events
            "faction_reputation_discount": { # Discount % based on reputation level
                "hostile": 2.0, # Price gouging
                "neutral": 1.0,
                "friendly": 0.9,
                "honored": 0.8
            },
            "barter_skill_influence": 0.05 # % price change per 10 points in barter skill (example)
        },
        "vendor_gold_refresh_rate": 1000, # Amount of gold a vendor gets per day (example)
    },
    "loot_rules": {
        "loot_tables_by_enemy_cr": { # Example structure
            "cr_0_1": {"common_items": 0.5, "gold_dice": "1d6"},
            "cr_2_5": {"common_items": 0.7, "uncommon_items": 0.2, "gold_dice": "2d10*5"},
            # ...
        },
        "drop_chances": { # General drop chances for rarities if not specified in loot table
            "common": 0.8,
            "uncommon": 0.15,
            "rare": 0.04,
            "legendary": 0.01
        },
        "magic_item_generation_rules": {
            "prefix_suffix_system": True,
            "base_modifier_chance": 0.1 # Chance for a generated item to have a magic modifier
        }
    },
    "conflict_resolution": {
        # This section will integrate or reference the structure from
        # bot/game/models/rules_config_definition.py's RULES_CONFIG_STRUCTURE
        # For now, it's a placeholder. The actual structure is more detailed.
        "default_manual_resolution_required": False,
        "types": {
            "simultaneous_move": {
                "description": "Two entities try to move to the same limited space.",
                "resolution_check": "opposed_dexterity_check" # Key to a check defined in "check_definitions"
            },
            # ... other conflict types
        }
    },
    "checks": {
        # This section is based on the existing RuleEngine.resolve_check idea
        # and will store definitions for specific checks.
        "athletics_check": {
            "description": "A check for physical prowess, climbing, jumping, etc.",
            "roll_formula": "1d20",
            "primary_stat": "strength",
            "relevant_skill": "athletics",
            "allow_critical_success": True,
            "allow_critical_failure": True,
            "default_dc": 12 # Can be overridden by context
        },
        "stealth_check": {
            "description": "A check for moving unseen and unheard.",
            "roll_formula": "1d20",
            "primary_stat": "dexterity",
            "relevant_skill": "stealth",
            "default_dc_against_perception": True # DC is target's passive perception
        },
        "spell_attack_intelligence": {
            "description": "An attack roll for a spell using Intelligence as the casting stat.",
            "roll_formula": "1d20",
            "primary_stat": "intelligence",
            "relevant_skill": "spellcasting_proficiency_bonus", # Could be a special skill or derived from class/level
            "target_dc_stat": "armor_class", # Target's AC
            "allow_critical_success": True, # Spells can crit
            "allow_critical_failure": True
        },
        # ... more predefined check types like saving throws, perception, etc.
    }
}

# Example of how a specific check or formula might be used:
#
# XP to Level:
# level = 2
# xp_needed = GAME_RULES_STRUCTURE["experience_rules"]["xp_to_level_up"]["values"].get(str(level))
#
# Attribute Modifier:
# strength_score = 15
# formula = GAME_RULES_STRUCTURE["character_stats_rules"]["attribute_modifier_formula"]
# # RuleEngine would replace "attribute_value" and eval: (15 - 10) // 2 = 2
# strength_modifier = eval(formula.replace("attribute_value", str(strength_score)))
#
# Damage:
# base_weapon_damage = "1d8" # From weapon
# strength_modifier = 2
# crit_multiplier = GAME_RULES_STRUCTURE["combat_rules"]["damage_calculation"]["critical_hit_multiplier"]
# # RuleEngine would roll 1d8, add modifier, and apply crit_multiplier if applicable.
#
