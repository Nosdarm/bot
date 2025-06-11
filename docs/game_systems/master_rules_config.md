# Master Rules Configuration (`master_rules_config.md`)

## Introduction

This document provides a comprehensive guide to the `MASTER_RULES_CONFIG_STRUCTURE`, which defines the blueprint for the Game Master's (GM) editable game rules. The actual game rules are typically stored in a JSON file (often referred to as `RuleConfig.config_data` or similar) that the game loads at runtime. This JSON file **must** conform to the structure outlined here.

The `MASTER_RULES_CONFIG_STRUCTURE` is defined in `bot/game/models/rules_config_definition.py` and serves as the single source of truth for the expected configuration format. Game Masters and developers should use this document to understand how to modify and extend game rules.

## Distinction from Pydantic Schema Documentation

This document (`master_rules_config.md`) describes the **live, GM-editable JSON structure** for game rules.

It is distinct from any documentation that might cover the Pydantic models themselves (e.g., `CoreGameRulesConfig` found in `bot/ai/rules_schema.py`). While this configuration is largely based on those Pydantic models, this document focuses on the practical JSON representation that the GM will interact with, providing examples and explanations for each configuration section. The Pydantic models are used internally by the game system, for example, for validation or by AI systems to understand rule constraints, whereas this document is for configuring the game's core mechanics.

---

## Top-Level Configuration Keys

The `MASTER_RULES_CONFIG_STRUCTURE` is a JSON object (a Python dictionary) containing the following top-level keys:

### `checks`

*   **Description**: Defines all types of checks or rolls used in the game (e.g., skill checks, saving throws, attack rolls). Each check has a unique ID.
*   **JSON Structure**: A dictionary where each key is a unique `check_id` (string) and the value is an object conforming to the `CheckDefinition` Pydantic model (from `bot/ai/rules_schema.py`).
*   **Example**:
    ```json
    "checks": {
        "perception_dc15_check": {
            "dice_formula": "1d20",
            "base_dc": 15,
            "affected_by_stats": ["dexterity", "perception_skill"],
            "crit_success_threshold": 20,
            "crit_fail_threshold": 1,
            "success_on_beat_dc": true,
            "opposed_check_type": null,
            "description": "A standard perception check against a fixed DC of 15."
        },
        "athletics_opposed_grapple_check": {
            "dice_formula": "1d20",
            "base_dc": null,
            "affected_by_stats": ["strength", "athletics_skill"],
            "crit_success_threshold": null,
            "crit_fail_threshold": null,
            "success_on_beat_dc": true,
            "opposed_check_type": "athletics_opposed_grapple_check", // Can point to itself or another check type for defense
            "description": "An athletics check to initiate or escape a grapple, opposed by the target's athletics."
        }
    }
    ```
*   **Sub-keys for each check definition**:
    *   `dice_formula` (string): The dice to roll (e.g., "1d20", "2d6+STR"). Modifiers from character stats/skills are typically added by the game's `CheckResolver` system based on `affected_by_stats`.
    *   `base_dc` (integer, nullable): The base difficulty class if the check is not contested or otherwise specified by an interaction.
    *   `affected_by_stats` (list of strings): List of character stat or skill keys (e.g., "dexterity", "perception_skill") that should modify this check's outcome.
    *   `crit_success_threshold` (integer, nullable): The roll value on the primary die (e.g., a 20 on a d20) at or above which the check is a critical success.
    *   `crit_fail_threshold` (integer, nullable): The roll value on the primary die (e.g., a 1 on a d20) at or below which the check is a critical fumble.
    *   `success_on_beat_dc` (boolean): If `true`, the roll result must be strictly greater than the DC. If `false`, the roll result must be greater than or equal to the DC.
    *   `opposed_check_type` (string, nullable): If this check is part of a contested roll, this field specifies the `check_id` of the check the target uses to oppose.
    *   `description` (string, optional): A human-readable description of the check.
*   **Usage**: The game's `CheckResolver` or similar systems use these definitions to execute dice rolls whenever an action or situation requires a check. `action_conflicts` and `location_interactions` often refer to these check IDs.

### `damage_types`

*   **Description**: Defines the various types of damage that can occur in the game (e.g., fire, slashing, psychic).
*   **JSON Structure**: A dictionary where each key is a unique `damage_type_id` (string) and the value is an object conforming to the `DamageTypeDefinition` Pydantic model.
*   **Example**:
    ```json
    "damage_types": {
        "fire": {
            "description": "Deals fire damage, potentially causing targets to burn."
        },
        "slashing": {
            "description": "Physical damage from sharp objects like swords or claws."
        }
    }
    ```
*   **Sub-keys for each damage type**:
    *   `description` (string): A human-readable description of the damage type.
    *   *(Future expansions could include resistances, vulnerabilities, or special effects associated with the damage type).*
*   **Usage**: Used by combat systems, item effects, status effects, and spells to determine how damage is applied and potentially resisted or amplified.

### `xp_rules`

*   **Description**: Configures rules related to experience points (XP) gain.
*   **JSON Structure**: An object conforming to the `XPRule` Pydantic model.
*   **Example**:
    ```json
    "xp_rules": {
        "level_difference_modifier": {
            "-5": 0.5,
            "0": 1.0,
            "5": 1.5
        },
        "base_xp_per_challenge": {
            "trivial": 10,
            "easy": 50,
            "medium": 100,
            "hard": 200,
            "deadly": 500
        }
    }
    ```
*   **Sub-keys**:
    *   `level_difference_modifier` (object): A dictionary where keys are string representations of level differences (e.g., "-5", "0", "+5") and values are XP multipliers. This allows scaling XP gain based on the difference between the player/party level and the challenge level.
    *   `base_xp_per_challenge` (object): A dictionary defining base XP amounts for different challenge ratings or types (e.g., "easy", "medium", "hard").
*   **Usage**: The game's progression system uses these rules to calculate XP awarded for completing quests, defeating enemies, or overcoming challenges.

### `loot_tables`

*   **Description**: Defines various loot tables that can be used to generate items, currency, or other rewards.
*   **JSON Structure**: A dictionary where each key is a unique `loot_table_id` (string) and the value is an object conforming to the `LootTableDefinition` Pydantic model.
*   **Example**:
    ```json
    "loot_tables": {
        "goblin_shaman_drops": {
            "id": "goblin_shaman_drops",
            "entries": [
                {
                    "item_template_id": "minor_staff_of_binding",
                    "quantity_dice": "1",
                    "weight": 1
                },
                {
                    "item_template_id": "herbs_dreamleaf",
                    "quantity_dice": "1d3",
                    "weight": 5
                },
                {
                    "item_template_id": "gold_coins",
                    "quantity_dice": "2d8",
                    "weight": 10
                }
            ]
        }
    }
    ```
*   **Sub-keys for each loot table**:
    *   `id` (string): The unique identifier for this loot table (should match the dictionary key).
    *   `entries` (list of objects): A list of potential items or rewards. Each entry object has:
        *   `item_template_id` (string): The ID of the item to be potentially dropped (references an item defined elsewhere).
        *   `quantity_dice` (string, default: "1"): A dice formula (e.g., "1", "1d4", "2d6") determining the quantity of the item.
        *   `weight` (integer, default: 1): The relative weight for this entry in a weighted random selection from the table. Higher weights mean a higher chance of being selected.
*   **Usage**: Used by the game when an NPC is defeated, a container is opened, or a quest is completed to randomly determine the loot awarded.

### `action_conflicts`

*   **Description**: Defines rules for resolving conflicts that arise when multiple actions or intents clash (e.g., two characters trying to move to the same limited spot).
*   **JSON Structure**: A list of objects, where each object conforms to the `ActionConflictDefinition` Pydantic model.
*   **Example**:
    ```json
    "action_conflicts": [
        {
            "type": "simultaneous_move_to_limited_slot",
            "description": "Two entities attempt to move into the same space that can only occupy one.",
            "involved_intent_pattern": ["move"],
            "resolution_type": "auto",
            "auto_resolution_check_type": "opposed_agility_check",
            "manual_resolution_options": null
        },
        {
            "type": "contested_resource_pickup",
            "description": "Multiple entities attempt to pick up the same limited resource simultaneously.",
            "involved_intent_pattern": ["pickup_item"],
            "resolution_type": "manual",
            "auto_resolution_check_type": null,
            "manual_resolution_options": ["Actor 1 gets it", "Actor 2 gets it", "No one gets it"]
        }
    ]
    ```
*   **Sub-keys for each action conflict definition**:
    *   `type` (string): A unique type identifier for this conflict (e.g., "simultaneous_move_to_limited_slot").
    *   `description` (string): A human-readable explanation of the conflict.
    *   `involved_intent_pattern` (list of strings): A list of action intents (e.g., "move", "pickup_item") that can trigger or be part of this conflict.
    *   `resolution_type` (string): How the conflict is resolved. Can be "auto" (resolved automatically by the system, typically via a check) or "manual" (requires GM or player choice).
    *   `auto_resolution_check_type` (string, nullable): If `resolution_type` is "auto", this specifies the `check_id` (from the `checks` section) used for resolution.
    *   `manual_resolution_options` (list of strings, nullable): If `resolution_type` is "manual", this provides a list of descriptive options for the choice.
*   **Usage**: The game's action resolution or turn management system uses these definitions to identify and resolve conflicting intents or actions declared by players or NPCs.

### `location_interactions`

*   **Description**: Defines interactive elements within game locations (e.g., levers, doors, chests, points of interest).
*   **JSON Structure**: A dictionary where each key is a unique `interaction_id` (string, e.g., "lever_main_hall_west_wall") and the value is an object conforming to the `LocationInteractionDefinition` Pydantic model.
*   **Example**:
    ```json
    "location_interactions": {
        "lever_main_hall_west_wall": {
            "id": "lever_main_hall_west_wall",
            "description_i18n": {"en_US": "A rusty lever protrudes from the wall."},
            "check_type": "strength_dc12_check",
            "success_outcome": {
                "type": "reveal_exit",
                "exit_id": "secret_passage_a",
                "message_i18n": {"en_US": "With a groan, a section of the wall slides open!"}
            },
            "failure_outcome": {
                "type": "display_message",
                "message_i18n": {"en_US": "The lever creaks but doesn't budge."}
            },
            "required_items": ["crowbar_item_id"]
        }
    }
    ```
*   **Sub-keys for each location interaction**:
    *   `id` (string): Unique identifier for this interaction (should match the dictionary key).
    *   `description_i18n` (object): Internationalized description of the interactable object (e.g., `{"en_US": "A lever", "es_ES": "Una palanca"}`).
    *   `check_type` (string, nullable): Optional `check_id` (from the `checks` section) required to attempt or succeed at the interaction.
    *   `success_outcome` (object): Defines what happens if the interaction (and any associated check) is successful. Contains:
        *   `type` (string): Type of outcome (e.g., "reveal_exit", "grant_item", "trigger_trap", "update_state_var", "display_message").
        *   Other keys depending on `type` (e.g., `exit_id`, `item_template_id`, `message_i18n`).
    *   `failure_outcome` (object, nullable): Defines what happens if the interaction or check fails. Structured similarly to `success_outcome`.
    *   `required_items` (list of strings, nullable): List of item template IDs an entity must possess to attempt the interaction.
*   **Usage**: The game engine uses these definitions when players or NPCs attempt to interact with specific objects or points in a location.

### `base_stats`

*   **Description**: Defines the fundamental statistics for characters and creatures in the game (e.g., Strength, Dexterity, Intelligence).
*   **JSON Structure**: A dictionary where each key is a unique `stat_id` (string, e.g., "strength") and the value is an object conforming to the `BaseStatDefinition` Pydantic model.
*   **Example**:
    ```json
    "base_stats": {
        "strength": {
            "name_i18n": {"en_US": "Strength"},
            "description_i18n": {"en_US": "Measures physical power and carrying capacity."},
            "default_value": 10,
            "min_value": 1,
            "max_value": 20
        },
        "intelligence": {
            "name_i18n": {"en_US": "Intelligence"},
            "description_i18n": {"en_US": "Measures reasoning, memory, and problem-solving ability."},
            "default_value": 10,
            "min_value": 1,
            "max_value": 20
        }
    }
    ```
*   **Sub-keys for each base stat**:
    *   `name_i18n` (object): Internationalized display name for the stat.
    *   `description_i18n` (object): Internationalized description of the stat.
    *   `default_value` (integer): The typical starting value for this stat.
    *   `min_value` (integer): The minimum possible value for this stat.
    *   `max_value` (integer): The maximum typical value for this stat (though monsters or special circumstances might exceed this).
*   **Usage**: Used by character creation, character sheets, and any game mechanic that references core statistics (e.g., skill calculations, combat, checks).

### `equipment_slots`

*   **Description**: Defines the available slots where characters can equip items.
*   **JSON Structure**: A dictionary where each key is a unique `slot_id` (string, e.g., "main_hand") and the value is an object conforming to the `EquipmentSlotDefinition` Pydantic model.
*   **Example**:
    ```json
    "equipment_slots": {
        "main_hand": {
            "slot_id": "main_hand",
            "name_i18n": {"en_US": "Main Hand"},
            "compatible_item_types": ["weapon_sword", "weapon_axe", "tool_torch"]
        },
        "armor_body": {
            "slot_id": "armor_body",
            "name_i18n": {"en_US": "Body Armor"},
            "compatible_item_types": ["armor_light", "armor_medium", "armor_heavy"]
        }
    }
    ```
*   **Sub-keys for each equipment slot**:
    *   `slot_id` (string): Unique identifier for the slot (should match the dictionary key).
    *   `name_i18n` (object): Internationalized display name for the slot.
    *   `compatible_item_types` (list of strings): A list of item type IDs that can be equipped in this slot.
*   **Usage**: Used by the inventory and character systems to manage equippable items. `ItemEffectDefinition` can also reference a slot if an effect is tied to an equippable item.

### `item_effects`

*   **Description**: Defines reusable effects that items can have (e.g., healing, stat boosts, applying status effects). These can be referenced by item templates.
*   **JSON Structure**: A dictionary where each key is a unique `effect_id` (string, which could also be an `item_template_id` if the effect is unique to one item) and the value is an object conforming to the `ItemEffectDefinition` Pydantic model.
*   **Example**:
    ```json
    "item_effects": {
        "minor_healing_potion_effect": {
            "description_i18n": {"en_US": "Restores a small amount of health."},
            "stat_modifiers": [],
            "direct_health_effects": [{
                "amount": 10,
                "effect_type": "heal"
            }],
            "apply_status_effects": [],
            "learn_spells": [],
            "grant_resources": [],
            "consumable": true,
            "target_policy": "self",
            "slot": null
        },
        "sword_of_agility_effect": {
            "description_i18n": {"en_US": "A swift blade that enhances agility when equipped."},
            "stat_modifiers": [{
                "stat_name": "dexterity",
                "bonus_type": "flat",
                "value": 2.0,
                "duration_turns": null
            }],
            "consumable": false,
            "target_policy": "requires_target",
            "slot": "main_hand"
        }
    }
    ```
*   **Sub-keys for each item effect (see `ItemEffectDefinition` in `bot/ai/rules_schema.py` for full details)**:
    *   `description_i18n` (object, nullable): Internationalized description of the combined effects.
    *   `stat_modifiers` (list of `StatModifierRule` objects): Defines changes to character stats.
    *   `grants_abilities_or_skills` (list of `GrantedAbilityOrSkill` objects): Abilities/skills granted by the item.
    *   `direct_health_effects` (list of `DirectHealthEffect` objects, nullable): Direct healing or damage.
    *   `apply_status_effects` (list of `ApplyStatusEffectRule` objects, nullable): Status effects to apply.
    *   `learn_spells` (list of `LearnSpellRule` objects, nullable): Spells learned permanently.
    *   `grant_resources` (list of `GrantResourceRule` objects, nullable): Resources granted (e.g., mana, gold).
    *   `consumable` (boolean): Whether the item is consumed on use.
    *   `target_policy` (string): Defines targeting rules (e.g., "self", "requires_target").
    *   `slot` (string, nullable): If equippable, the `slot_id` it uses.
*   **Usage**: The item system applies these effects when items are used, equipped, or unequipped. Item templates will typically reference these effect definitions.

### `status_effects`

*   **Description**: Defines various status effects that can be applied to characters (e.g., poisoned, blessed, strengthened).
*   **JSON Structure**: A dictionary where each key is a unique `status_effect_id` (string) and the value is an object conforming to the `StatusEffectDefinition` Pydantic model.
*   **Example**:
    ```json
    "status_effects": {
        "poisoned_weak": {
            "id": "poisoned_weak",
            "name_i18n": {"en_US": "Weakly Poisoned"},
            "description_i18n": {"en_US": "Taking minor damage over time."},
            "stat_modifiers": [],
            "grants_abilities_or_skills": [],
            "duration_type": "turns",
            "default_duration_turns": 5
            // "tick_effect": {"type": "damage", "damage_type": "poison", "amount_dice": "1d4"} // Example for DoT
        }
    }
    ```
*   **Sub-keys for each status effect (see `StatusEffectDefinition` for full details)**:
    *   `id` (string): Unique identifier (should match the dictionary key).
    *   `name_i18n` (object): Internationalized display name.
    *   `description_i18n` (object): Internationalized description.
    *   `stat_modifiers` (list of `StatModifierRule` objects): Stat changes while the effect is active.
    *   `grants_abilities_or_skills` (list of `GrantedAbilityOrSkill` objects): Abilities/skills granted temporarily.
    *   `duration_type` (string): How duration is measured (e.g., "turns", "permanent", "until_condition_met").
    *   `default_duration_turns` (integer, nullable): Default duration in turns if applicable.
    *   *(May include `tick_effect` for damage/healing over time, messages on apply/remove, etc.)*
*   **Usage**: Applied by item effects, spells, traps, or other game mechanics. The combat or character system manages active status effects and applies their modifications.

---
## New Game-Wide Configuration Sections

These keys provide configuration for broader game systems beyond the direct mechanics covered by `CoreGameRulesConfig`.

### `economy_rules`

*   **Description**: Configures rules governing the game's economy, including pricing, currency, and exchange rates.
*   **JSON Structure**: An object containing various economic parameters.
*   **Example**:
    ```json
    "economy_rules": {
        "description": "Rules governing game economy, prices, currency.",
        "base_buy_price_multiplier": 1.25,
        "base_sell_price_multiplier": 0.75,
        "currency_units": {
            "gold": {"name_i18n": {"en_US": "Gold"}, "symbol": "g"},
            "silver": {"name_i18n": {"en_US": "Silver"}, "symbol": "s"}
        },
        "exchange_rates": {
            "gold_to_silver": 100
        },
        "regional_price_modifiers": {
            "starting_village_market": {"buy_factor_adj": -0.1, "sell_factor_adj": 0.05}
        }
    }
    ```
*   **Sub-keys**:
    *   `description` (string): Explanation of this section.
    *   `base_buy_price_multiplier` (float): Multiplier applied to an item's base value when an NPC sells it to a player (e.g., 1.25 means 125% of base value).
    *   `base_sell_price_multiplier` (float): Multiplier applied to an item's base value when an NPC buys it from a player (e.g., 0.75 means 75% of base value).
    *   `currency_units` (object): Defines the types of currency used in the game. Each key is a currency ID (e.g., "gold"), and the value contains details like `name_i18n` and `symbol`.
    *   `exchange_rates` (object): Defines conversion rates between different currency units (e.g., `{"gold_to_silver": 100}`).
    *   `regional_price_modifiers` (object, optional): Allows for location-specific adjustments to buy/sell prices. Keys are region/market IDs, values contain adjustment factors.
*   **Usage**: Used by merchant NPCs, loot systems, and quest reward systems to determine item prices and currency transactions.

### `ai_behavior_rules`

*   **Description**: Defines parameters for AI difficulty scaling, archetype behaviors, and decision-making processes for NPCs.
*   **JSON Structure**: An object containing AI configuration parameters.
*   **Example**:
    ```json
    "ai_behavior_rules": {
        "description": "Rules for AI difficulty scaling, archetype behaviors, and decision-making.",
        "global_difficulty_modifier": 1.0,
        "archetype_profiles": {
            "aggressive_melee": {
                "preferred_target_rules": ["lowest_hp_percentage", "closest_target"],
                "engagement_range_cells": 1,
                "special_ability_usage_threshold_hp": 0.5
            },
            "cautious_ranged": {
                "preferred_target_rules": ["highest_threat", "caster_types"],
                "engagement_range_cells": 10,
                "kite_if_target_too_close_distance": 3,
                "healing_potion_usage_threshold_hp": 0.3
            }
        },
        "faction_ai_settings": {
            "faction_a_id": {
                "default_stance_towards_faction_b_id": "hostile",
                "assist_allies_in_combat_range_cells": 20
            }
        }
    }
    ```
*   **Sub-keys**:
    *   `description` (string): Explanation of this section.
    *   `global_difficulty_modifier` (float): A general multiplier that can make all AI easier or harder (e.g., affects AI stats, decision-making).
    *   `archetype_profiles` (object): Defines behavior patterns for different AI archetypes (e.g., "aggressive_melee", "cautious_ranged"). Each archetype can have specific rules for:
        *   `preferred_target_rules` (list of strings): Criteria for selecting targets.
        *   `engagement_range_cells` (integer): Preferred combat distance.
        *   Other archetype-specific behaviors (e.g., `special_ability_usage_threshold_hp`, `kite_if_target_too_close_distance`).
    *   `faction_ai_settings` (object): Defines default AI behavior between different factions, such as initial stance (hostile, neutral, friendly) or when to assist allies.
*   **Usage**: Used by the AI system to control NPC behavior in combat and non-combat situations, allowing for varied and scalable challenges.

### `gm_rules`

*   **Description**: Provides guidelines and configurations for automated Game Master (GM) behaviors or GM-assist features.
*   **JSON Structure**: An object containing rules and triggers for GM-level actions.
*   **Example**:
    ```json
    "gm_rules": {
        "description": "Guidelines and automated behaviors for the Game Master.",
        "event_triggers": [
            {
                "event_id": "world_boss_spawn_warning",
                "condition_type": "game_time_elapsed_hours",
                "value": 168,
                "action_to_take": "gm_broadcast_message",
                "message_i18n": {"en_US": "A powerful entity is rumored to be stirring in the Dragon's Peak..."}
            }
        ],
        "gm_intervention_prompts": {
            "player_stuck_location_duration_minutes": 30,
            "economy_imbalance_flag_threshold_gold": 1000000
        },
        "plot_advancement_rules": {
            "main_quest_line_auto_offer_delay_hours": 2
        }
    }
    ```
*   **Sub-keys**:
    *   `description` (string): Explanation of this section.
    *   `event_triggers` (list of objects): Defines conditions that can automatically trigger game events or GM notifications. Each trigger includes:
        *   `event_id` (string): Unique ID for the event trigger.
        *   `condition_type` (string): The type of condition (e.g., "game_time_elapsed_hours", "player_level_milestone").
        *   `value`: The threshold value for the condition.
        *   `action_to_take` (string): What should happen (e.g., "gm_broadcast_message", "spawn_npc_group").
        *   Other action-specific parameters (e.g., `message_i18n`).
    *   `gm_intervention_prompts` (object): Defines situations where the GM might be prompted to intervene manually (e.g., a player being stuck, or economic imbalances).
    *   `plot_advancement_rules` (object): Rules for automatically managing or suggesting plot progression (e.g., delays before offering the next main quest).
*   **Usage**: Used by game systems to automate certain GM tasks, manage world events, or alert human GMs to situations requiring attention, helping to create a dynamic game world.

### `quest_rules_config`

*   **Description**: Configures game mechanics related to quest progression, objective types, and reward calculations. This is distinct from `CoreGameRulesConfig.quest_rules` which is primarily for AI validation of generated quest *content*.
*   **JSON Structure**: An object containing parameters for the quest system.
*   **Example**:
    ```json
    "quest_rules_config": {
        "description": "Game mechanics for quest progression, reward calculation, and objective types.",
        "global_quest_xp_multiplier": 1.0,
        "global_quest_gold_multiplier": 1.0,
        "objective_type_defaults": {
            "kill_target": {"base_xp_per_level_of_target": 10, "can_be_shared": true},
            "fetch_item": {"base_xp_per_rarity_of_item": {"common": 20, "rare": 100}, "item_value_gold_percentage_reward": 0.5},
            "explore_location": {"base_xp": 150}
        },
        "quest_chain_rules": {
            "max_active_side_quests": 5,
            "main_story_gate_level_requirements": {
                "chapter_2_start_quest_id": 10,
                "chapter_3_start_quest_id": 20
            }
        },
        "dynamic_quest_generation_params": {
             "max_distance_for_kill_target_km": 5,
             "min_reward_to_effort_ratio": 0.8
        }
    }
    ```
*   **Sub-keys**:
    *   `description` (string): Explanation of this section.
    *   `global_quest_xp_multiplier` (float): Multiplier for all XP rewards from quests.
    *   `global_quest_gold_multiplier` (float): Multiplier for all gold rewards from quests.
    *   `objective_type_defaults` (object): Defines default reward parameters or properties for different quest objective types (e.g., "kill_target", "fetch_item").
    *   `quest_chain_rules` (object): Rules governing quest lines, such as maximum active side quests or level requirements for main story progression.
    *   `dynamic_quest_generation_params` (object, optional): Parameters for any procedural or dynamic quest generation systems.
*   **Usage**: Used by the quest management system to control how quests are offered, how objectives are tracked, and how rewards are calculated and distributed.

### `roll_formulas`

*   **Description**: Provides a centralized repository for common or generic dice roll formulas that might be used by various game systems beyond the specific `checks` definitions.
*   **JSON Structure**: A dictionary where keys are formula IDs (string) and values are the dice roll formulas (string).
*   **Example**:
    ```json
    "roll_formulas": {
        "description": "Centralized definitions for common dice roll formulas beyond specific checks.",
        "initiative_roll": "1d20 + dexterity_modifier",
        "item_salvage_success_roll": "1d100",
        "random_encounter_chance_roll": "1d100"
    }
    ```
*   **Sub-keys**:
    *   `description` (string): Explanation of this section.
    *   Each key-value pair defines a named roll formula. The formula string might include conceptual terms like "dexterity_modifier" which the game system would resolve at runtime.
*   **Usage**: These formulas can be referenced by various game modules (e.g., combat for initiative, crafting for salvage success) when a standardized roll is needed that isn't complex enough to warrant a full `CheckDefinition`.

### `damage_effect_formulas`

*   **Description**: Defines formulas for more complex damage calculations, often used for spells, special abilities, or environmental effects that go beyond simple weapon damage or basic damage types.
*   **JSON Structure**: A dictionary where keys are formula IDs (string) and values are the damage calculation formulas or parameters.
*   **Example**:
    ```json
    "damage_effect_formulas": {
        "description": "Formulas for specific abilities or environmental effects that deal damage.",
        "fireball_spell_base_damage": "6d6",
        "backstab_multiplier_vs_unaware": "3.0",
        "critical_hit_damage_bonus_dice": "1d6"
    }
    ```
*   **Sub-keys**:
    *   `description` (string): Explanation of this section.
    *   Each key-value pair defines a named damage formula. This can be dice strings, multipliers, or other parameters the combat system can interpret.
*   **Usage**: The combat system or ability execution system would use these formulas to calculate damage for specific effects, applying them before considering resistances or vulnerabilities defined in `damage_types`.

---
This concludes the documentation for the `MASTER_RULES_CONFIG_STRUCTURE`. GMs and developers should refer to this guide when creating or modifying the game's rule configuration JSON.
