"""
Defines the structure for rules_config, which holds conflict types and resolution rules,
and the master structure for all game rules.
"""

# MASTER_RULES_CONFIG_STRUCTURE
# This dictionary serves as the comprehensive template for the GM's config_data JSON.
# It mirrors the fields and structure of CoreGameRulesConfig from bot/ai/rules_schema.py
# and includes additional top-level keys for broader game configuration.
MASTER_RULES_CONFIG_STRUCTURE = {
    "checks": {  # Based on Dict[str, CheckDefinition] from bot/ai/rules_schema.py
        "example_check_id": {  # Unique identifier for a type of check (e.g., "perception_dc15", "strength_opposed_athletics")
            "dice_formula": "1d20",  # Dice formula (e.g., '1d20', '2d6+STR'). Modifiers are added by CheckResolver.
            "base_dc": 15,  # Base difficulty class, if not contested.
            "affected_by_stats": ["dexterity", "perception_skill"],  # List of stat/skill keys that modify this check.
            "crit_success_threshold": 20,  # Roll value for critical success (e.g., on a d20).
            "crit_fail_threshold": 1,  # Roll value for critical fumble.
            "success_on_beat_dc": True,  # True if roll > DC is success; False if roll >= DC is success.
            "opposed_check_type": None,  # If contested, specifies the 'check_type' the target uses. E.g., "athletics_check"
            "description": "A sample check definition." # Optional description
        }
    },
    "damage_types": {  # Based on Dict[str, DamageTypeDefinition] from bot/ai/rules_schema.py
        "example_damage_type_id": {  # E.g., "fire", "slashing", "psychic"
            "description": "Deals fire damage, burning the target."
            # Future: "resistances_map": {"water": 0.5}, "vulnerabilities_map": {"ice": 1.5}
        }
    },
    "xp_rules": {  # Based on XPRule from bot/ai/rules_schema.py
        "level_difference_modifier": {
            "-5": 0.5, # Target is 5 levels lower: 50% XP
            "0": 1.0,  # Target is same level: 100% XP
            "5": 1.5   # Target is 5 levels higher: 150% XP
        },
        "base_xp_per_challenge": {
            "trivial": 10,
            "easy": 50,
            "medium": 100,
            "hard": 200,
            "deadly": 500
        }
    },
    "loot_tables": {  # Based on Dict[str, LootTableDefinition] from bot/ai/rules_schema.py
        "example_loot_table_id": {  # E.g., "goblin_chieftain_drops", "common_treasure_chest"
            "id": "example_loot_table_id", # Should match the key
            "entries": [
                {
                    "item_template_id": "healing_potion_small",
                    "quantity_dice": "1d2",
                    "weight": 10
                },
                {
                    "item_template_id": "gold_coins",
                    "quantity_dice": "5d6",
                    "weight": 5
                }
            ]
        }
    },
    "action_conflicts": [  # Based on List[ActionConflictDefinition] from bot/ai/rules_schema.py
        {
            "type": "simultaneous_move_to_limited_slot", # Unique type identifier
            "description": "Two entities attempt to move into the same space that can only occupy one.",
            "involved_intent_pattern": ["move"], # Intents that can trigger this
            "resolution_type": "auto", # 'auto' or 'manual'
            "auto_resolution_check_type": "opposed_agility_check", # Key from "checks" dict
            "manual_resolution_options": None # Options if 'manual'
        }
    ],
    "location_interactions": {  # Based on Dict[str, LocationInteractionDefinition] from bot/ai/rules_schema.py
        "example_interaction_id": { # E.g., "lever_main_hall_west_wall"
            "id": "example_interaction_id", # Should match the key
            "description_i18n": {"en_US": "A rusty lever protrudes from the wall."},
            "check_type": "strength_dc12_check", # Optional: key from "checks" dict
            "success_outcome": {
                "type": "reveal_exit", # E.g., 'reveal_exit', 'grant_item', 'display_message'
                "exit_id": "secret_passage_a",
                "message_i18n": {"en_US": "With a groan, a section of the wall slides open!"}
            },
            "failure_outcome": {
                "type": "display_message",
                "message_i18n": {"en_US": "The lever creaks but doesn't budge."}
            },
            "required_items": ["crowbar_item_id"] # Optional list of item template IDs
        }
    },
    "base_stats": {  # Based on Dict[str, BaseStatDefinition] from bot/ai/rules_schema.py
        "strength": {
            "name_i18n": {"en_US": "Strength"},
            "description_i18n": {"en_US": "Measures physical power and carrying capacity."},
            "default_value": 10,
            "min_value": 1,
            "max_value": 20 # Typical player max, monsters can exceed
        },
        "dexterity": {
            "name_i18n": {"en_US": "Dexterity"},
            "description_i18n": {"en_US": "Measures agility, reflexes, and balance."},
            "default_value": 10,
            "min_value": 1,
            "max_value": 20
        }
        # ... other base stats (intelligence, constitution, wisdom, charisma, etc.)
    },
    "equipment_slots": {  # Based on Dict[str, EquipmentSlotDefinition] from bot/ai/rules_schema.py
        "main_hand": {
            "slot_id": "main_hand", # Should match the key
            "name_i18n": {"en_US": "Main Hand"},
            "compatible_item_types": ["weapon_sword", "weapon_axe", "tool_torch"]
        },
        "armor_body": {
            "slot_id": "armor_body",
            "name_i18n": {"en_US": "Body Armor"},
            "compatible_item_types": ["armor_light", "armor_medium", "armor_heavy"]
        }
        # ... other slots (off_hand, head, feet, accessory1, accessory2, etc.)
    },
    "item_effects": {  # Based on Dict[str, ItemEffectDefinition] from bot/ai/rules_schema.py
        "example_healing_effect": { # Can be an effect ID or directly an item_template_id if effect is unique to item
            "description_i18n": {"en_US": "Restores a small amount of health."},
            "stat_modifiers": [], # No permanent stat mods for this simple heal
            "direct_health_effects": [{
                "amount": 10, # Heals for 10 HP
                "effect_type": "heal"
            }],
            "consumable": True,
            "target_policy": "self" # 'self', 'requires_target', 'no_target'
        },
        "example_sword_attributes": {
            "description_i18n": {"en_US": "A finely crafted longsword."},
            "stat_modifiers": [ # Example: a sword that gives +1 to an attack stat
                {
                    "stat_name": "attack_bonus_melee", # A conceptual stat the game would use
                    "bonus_type": "flat",
                    "value": 1.0,
                    "duration_turns": None # Permanent while equipped
                }
            ],
            "slot": "main_hand", # Indicates this effect is for an equippable item
            "consumable": False,
            "target_policy": "requires_target" # For attacking
        }
    },
    "status_effects": {  # Based on Dict[str, StatusEffectDefinition] from bot/ai/rules_schema.py
        "poisoned_status": {
            "id": "poisoned_status", # Should match the key
            "name_i18n": {"en_US": "Poisoned"},
            "description_i18n": {"en_US": "Taking damage over time and disadvantaged on attack rolls."},
            "stat_modifiers": [
                {
                    "stat_name": "attack_roll_modifier", # Example conceptual stat for game logic
                    "bonus_type": "flat", # Using 'flat' for a direct penalty
                    "value": -2.0, # Represents a disadvantage or penalty
                    "duration_turns": None # Duration is governed by the status effect itself
                }
            ],
            "duration_type": "turns", # 'turns', 'permanent', 'until_condition_met'
            "default_duration_turns": 3,
            # "tick_effect": { # Example of a damage-over-time component
            #    "type": "damage", "damage_type": "poison_internal", "amount_dice": "1d4"
            # }
        }
    },
    # --- New Top-Level Keys ---
    "economy_rules": {
        "description": "Rules governing game economy, prices, currency.",
        "base_buy_price_multiplier": 1.25, # NPCs sell items at 125% of base value
        "base_sell_price_multiplier": 0.75, # NPCs buy items from players at 75% of base value
        "currency_units": {
            "gold": {"name_i18n": {"en_US": "Gold"}, "symbol": "g"},
            "silver": {"name_i18n": {"en_US": "Silver"}, "symbol": "s"}
        },
        "exchange_rates": { # Relative to a base unit or each other
            "gold_to_silver": 100 # 1 gold = 100 silver
        },
        "regional_price_modifiers": { # Example: prices might vary by location
            "starting_village_market": {"buy_factor_adj": -0.1, "sell_factor_adj": 0.05} # Cheaper to buy, slightly better to sell
        }
    },
    "ai_behavior_rules": {
        "description": "Rules for AI difficulty scaling, archetype behaviors, and decision-making.",
        "global_difficulty_modifier": 1.0, # Can be adjusted to make all AI easier/harder
        "archetype_profiles": {
            "aggressive_melee": {
                "preferred_target_rules": ["lowest_hp_percentage", "closest_target"],
                "engagement_range_cells": 1,
                "special_ability_usage_threshold_hp": 0.5 # Uses special abilities when below 50% HP
            },
            "cautious_ranged": {
                "preferred_target_rules": ["highest_threat", "caster_types"],
                "engagement_range_cells": 10,
                "kite_if_target_too_close_distance": 3,
                "healing_potion_usage_threshold_hp": 0.3 # Uses healing potion if available and HP < 30%
            }
        },
        "faction_ai_settings": { # How AI of one faction behaves towards another by default
            "faction_a_id": {
                "default_stance_towards_faction_b_id": "hostile", # 'hostile', 'neutral', 'friendly'
                "assist_allies_in_combat_range_cells": 20
            }
        }
    },
    "gm_rules": {
        "description": "Guidelines and automated behaviors for the Game Master.",
        "event_triggers": [ # Automated or GM-assist event triggers
            {
                "event_id": "world_boss_spawn_warning",
                "condition_type": "game_time_elapsed_hours", # 'player_level_milestone', 'quest_completed', etc.
                "value": 168, # e.g., 168 game hours (1 week)
                "action_to_take": "gm_broadcast_message", # 'spawn_npc_group', 'modify_environment'
                "message_i18n": {"en_US": "A powerful entity is rumored to be stirring in the Dragon's Peak..."}
            }
        ],
        "gm_intervention_prompts": { # Situations where GM might be prompted to intervene
            "player_stuck_location_duration_minutes": 30,
            "economy_imbalance_flag_threshold_gold": 1000000 # If a player accumulates too much wealth quickly
        },
        "plot_advancement_rules": {
            "main_quest_line_auto_offer_delay_hours": 2 # After completing a main quest, offer next one after 2 game hours
        }
    },
    "quest_rules_config": { # Distinct from CoreGameRulesConfig.quest_rules (which is for AI NPC/Quest gen validation)
        "description": "Game mechanics for quest progression, reward calculation, and objective types.",
        "global_quest_xp_multiplier": 1.0,
        "global_quest_gold_multiplier": 1.0,
        "objective_type_defaults": {
            "kill_target": {"base_xp_per_level_of_target": 10, "can_be_shared": True},
            "fetch_item": {"base_xp_per_rarity_of_item": {"common": 20, "rare": 100}, "item_value_gold_percentage_reward": 0.5},
            "explore_location": {"base_xp": 150}
        },
        "quest_chain_rules": {
            "max_active_side_quests": 5,
            "main_story_gate_level_requirements": { # Level required to start certain main story quests
                "chapter_2_start_quest_id": 10,
                "chapter_3_start_quest_id": 20
            }
        },
        "dynamic_quest_generation_params": { # If the game supports procedural quests
             "max_distance_for_kill_target_km": 5,
             "min_reward_to_effort_ratio": 0.8 # Effort being a heuristic (time, difficulty)
        }
    },
    "roll_formulas": { # Generic roll formulas accessible system-wide
        "description": "Centralized definitions for common dice roll formulas beyond specific checks.",
        "initiative_roll": "1d20 + dexterity_modifier", # More specific than a generic check
        "item_salvage_success_roll": "1d100", # Used with a DC perhaps defined elsewhere
        "random_encounter_chance_roll": "1d100"
    },
    "damage_effect_formulas": { # For complex damage calculations not covered by simple damage types
        "description": "Formulas for specific abilities or environmental effects that deal damage.",
        "fireball_spell_base_damage": "6d6", # Base damage before modifiers like scaling or resistances
        "backstab_multiplier_vs_unaware": "3.0", # Damage multiplier
        "critical_hit_damage_bonus_dice": "1d6" # Extra dice on a critical hit for certain weapons/abilities
    }
}


# RULES_CONFIG_STRUCTURE (Existing structure, kept for reference or specific use cases)
# This structure defines a template for how individual conflict types and their resolution
# mechanisms are configured. The `action_conflicts` list in MASTER_RULES_CONFIG_STRUCTURE
# uses ActionConflictDefinition from schema.py, which is more aligned with Pydantic.
# This older structure might still be useful for very detailed, game-specific conflict
# resolution logic that doesn't fit neatly into the ActionConflictDefinition's fields,
# or if the game engine has systems built around this specific structure.
#
# If ActionConflictDefinition (with its `auto_resolution_check_type` pointing to a `CheckDefinition`)
# fully covers the needs, this older structure might be deprecated in the future.
RULES_CONFIG_STRUCTURE = {
    "conflict_type_id": {  # Unique identifier for the conflict type (e.g., "simultaneous_move_to_limited_space")
        "description": "A human-readable description of the conflict type.",
        "manual_resolution_required": True,  # Boolean: True if manual intervention is needed
        "notification_format": {  # Required if manual_resolution_required is True
            "message": "Player {actor_id} and Player {target_id} are attempting to move to the same limited space: {space_id}. Please resolve.",
            "placeholders": ["actor_id", "target_id", "space_id"] # List of placeholders used in the message
        },
        "automatic_resolution": {  # Required if manual_resolution_required is False
            "check_type": "skill_check",  # e.g., "skill_check", "stat_check", "opposed_check", "random". This would map to a key in MASTER_RULES_CONFIG_STRUCTURE.checks
            "actor_check_details": { # Details for the actor initiating the action
                "skill_or_stat_to_use": "dexterity", # e.g., "dexterity", "strength", "negotiation_skill"
                "modifiers": ["status_effect_agility_buff"] # List of potential modifiers (buffs/debuffs)
            },
            "target_check_details": { # Details for the target of the action (if applicable, e.g., in opposed_check)
                "skill_or_stat_to_use": "dexterity",
                "modifiers": []
            },
            "outcome_rules": {
                "success_threshold": 10, # For single player checks (skill_check, stat_check)
                "higher_wins": True, # For opposed checks
                "tie_breaker_rule": "actor_priority", # e.g., "actor_priority", "target_priority", "random", "re_roll"
                "outcomes": {
                    "actor_wins": {
                        "description": "Actor successfully performs the action.",
                        "effects": ["apply_effect_move_to_space_actor", "apply_effect_stun_target_short"]
                    },
                    "target_wins": { # Or "actor_fails" for single player checks
                        "description": "Target successfully defends or actor fails the action.",
                        "effects": ["apply_effect_move_to_space_target"]
                    },
                    "tie": {
                        "description": "The conflict results in a stalemate or a specific tie outcome.",
                        "effects": ["apply_effect_both_remain_in_place"]
                    }
                }
            }
        }
    }
}

# --- Example Configurations ---
# This demonstrates how the old RULES_CONFIG_STRUCTURE might be used.
# The new MASTER_RULES_CONFIG_STRUCTURE.action_conflicts would contain a list of
# ActionConflictDefinition objects.
EXAMPLE_RULES_CONFIG = {
    "simultaneous_move_to_limited_space": {
        "description": "Two entities attempt to move into the same space that can only occupy one.",
        "manual_resolution_required": False,
        "automatic_resolution": {
            "check_type": "opposed_agility_check", # This would be a key in MASTER_RULES_CONFIG_STRUCTURE.checks
            "actor_check_details": { # These details might be redundant if "opposed_agility_check" defines them
                "skill_or_stat_to_use": "agility_score", # Could be defined by the check itself
                "modifiers": ["haste_buff", "encumbered_debuff"] # These are dynamic, applied at resolution time
            },
            "target_check_details": {
                "skill_or_stat_to_use": "agility_score",
                "modifiers": ["terrain_advantage_buff"]
            },
            "outcome_rules": { # These rules (thresholds, tie-breakers) would ideally be part of the CheckDefinition
                "higher_wins": True,
                "tie_breaker_rule": "random",
                "outcomes": {
                    "actor_wins": {
                        "description": "The actor reaches the space first.",
                        "effects": ["actor_moves_to_space", "target_remains_previous_space"]
                    },
                    "target_wins": {
                        "description": "The target reaches the space first.",
                        "effects": ["target_moves_to_space", "actor_remains_previous_space"]
                    },
                    "tie": {
                        "description": "Both entities are momentarily stunned by the near collision.",
                        "effects": ["apply_stun_brief_actor", "apply_stun_brief_target"]
                    }
                }
            }
        }
    },
    # ... (other examples from the original file would go here, but truncated for brevity in this new combined file)
    "contested_resource_grab": {
        "description": "Two or more players attempt to grab the same limited resource.",
        "manual_resolution_required": True,
        "notification_format": {
            "message": "Conflict ID {conflict_id}: Players {player_ids_str} are trying to grab '{resource_name}' at {location_name}. Who gets it?",
            "placeholders": ["conflict_id", "player_ids_str", "resource_name", "location_name"]
        }
    }
}

# It is expected that the actual rules_config.json or Python dict used by the game
# will be a dictionary conforming to MASTER_RULES_CONFIG_STRUCTURE.
#
# The list of `effects` within outcomes (in the old structure) would correspond to function names or identifiers
# that the game engine knows how to execute. For example, "actor_moves_to_space"
# would trigger a game logic function responsible for moving the actor.
#
# Modifiers like "haste_buff" or "encumbered_debuff" would be looked up on the character/entity
# involved in the conflict, and their values (e.g., +2 agility, -10% speed) would be applied
# to the relevant skill/stat check during resolution.
#
# The `MASTER_RULES_CONFIG_STRUCTURE.action_conflicts` uses `ActionConflictDefinition` which points
# to a `check_type` in `MASTER_RULES_CONFIG_STRUCTURE.checks`. That `CheckDefinition` should contain
# the core logic for dice rolls, DC, crit thresholds, etc., making parts of the old
# `automatic_resolution` details (like `actor_check_details`, `outcome_rules.success_threshold`)
# potentially redundant if those details are defined within the referenced check.
# The system should prefer using the `CheckDefinition` for these aspects.
# Dynamic parts like specific modifiers on actors would still be applied at runtime.

# Placeholder for Any type from typing, if needed for some flexible fields,
# though Pydantic models in schema.py handle most typing.
# from typing import Any
