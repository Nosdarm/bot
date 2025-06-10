# Core Game Rules Configuration (`CoreGameRulesConfig`) Schema

This document outlines the structure and purpose of the `CoreGameRulesConfig` schema, which defines the core mechanics and rules for the game. These rules are typically stored in a central database (e.g., in the `RulesConfig` table as a JSON object) and loaded by various game modules at runtime.

The schema is defined using Pydantic models in `bot/ai/rules_schema.py`.

## Top-Level Structure: `CoreGameRulesConfig`

The main container for all core game rules.

| Key                     | Type                                      | Description                                                                 |
|-------------------------|-------------------------------------------|-----------------------------------------------------------------------------|
| `checks`                | `Dict[str, CheckDefinition]`              | Defines all skill checks, saving throws, or other probabilistic game events.  |
| `damage_types`          | `Dict[str, DamageTypeDefinition]`         | Defines various types of damage (e.g., "fire", "slashing") and their properties. |
| `xp_rules`              | `Optional[XPRule]`                        | Rules governing experience point awards.                                    |
| `loot_tables`           | `Dict[str, LootTableDefinition]`          | Definitions for loot tables used for generating treasure, item drops, etc.   |
| `action_conflicts`      | `List[ActionConflictDefinition]`          | Rules for identifying and resolving conflicts between player/NPC actions.   |
| `location_interactions` | `Dict[str, LocationInteractionDefinition]`| Defines interactive elements within locations and their outcomes.           |
| `base_stats`            | `Dict[str, BaseStatDefinition]`           | Definitions for base character stats (e.g., STR, DEX).                      |
| `item_effects`          | `Dict[str, ItemEffectDefinition]`         | Definitions for reusable item effects.                                      |
| `status_effects`        | `Dict[str, StatusEffectDefinition]`       | Definitions for status effects (buffs, debuffs).                            |
| `equipment_slots`       | `Dict[str, EquipmentSlotDefinition]`      | Defines character equipment slots and compatible item types.                |

---

## 1. `checks`

Defines all types of checks that can occur in the game. The key for each entry is a unique `check_type` string (e.g., "perception", "lockpicking_easy", "stealth_vs_perception").

**Module Usage:** Primarily used by the `CheckResolver` module.

### `CheckDefinition` Structure:

| Key                      | Type          | Description                                                                                                | Example                                 |
|--------------------------|---------------|------------------------------------------------------------------------------------------------------------|-----------------------------------------|
| `dice_formula`           | `str`         | The dice roll involved (e.g., "1d20", "2d6"). Stat modifiers are typically added by the `CheckResolver`.   | `"1d20"`                                |
| `base_dc`                | `Optional[int]` | The base difficulty class if it's a simple check against a fixed value.                                  | `15`                                    |
| `affected_by_stats`      | `List[str]`   | List of character stats or skill names that modify the check result (e.g., "dexterity", "perception_skill"). | `["wisdom", "survival_skill"]`        |
| `crit_success_threshold` | `Optional[int]` | For d20-based checks, the raw roll value (e.g., 20) that signifies a critical success.                     | `20`                                    |
| `crit_fail_threshold`    | `Optional[int]` | For d20-based checks, the raw roll value (e.g., 1) that signifies a critical failure.                      | `1`                                     |
| `success_on_beat_dc`     | `bool`        | If `True`, the roll must be strictly greater than the DC. If `False`, meeting or exceeding the DC is success. | `True` (for most checks) / `False` (e.g. some saving throws) |
| `opposed_check_type`     | `Optional[str]` | If this check is contested, this field holds the `check_type` the opposing entity uses.                  | `"perception"` (for a "stealth" check)  |

**Example `checks` entry:**
```json
{
  "checks": {
    "lockpicking_average": {
      "dice_formula": "1d20",
      "base_dc": 15,
      "affected_by_stats": ["dexterity", "lockpicking_skill"],
      "crit_success_threshold": 20,
      "crit_fail_threshold": 1,
      "success_on_beat_dc": false
    },
    "stealth_attempt": {
      "dice_formula": "1d20",
      "affected_by_stats": ["dexterity", "stealth_skill"],
      "opposed_check_type": "perception_passive",
      "success_on_beat_dc": true
    },
    "perception_passive": {
      "dice_formula": "1d20", // Or could be "10" for true passive + mods
      "affected_by_stats": ["wisdom", "perception_skill"],
      "success_on_beat_dc": true // Irrelevant if used as DC for another check
    }
  }
}
```

---

## 2. `damage_types`

Defines properties for different types of damage. The key is the damage type ID (e.g., "fire", "slashing", "psychic").

**Module Usage:** Used by `CombatManager` when applying damage, calculating resistances/vulnerabilities.

### `DamageTypeDefinition` Structure:

| Key           | Type  | Description                                     | Example        |
|---------------|-------|-------------------------------------------------|----------------|
| `description` | `str` | A textual description of the damage type.       | `"Burning heat"` |
| `(future)`    |       | Could include fields for resistances, effects.  |                |

**Example `damage_types` entry:**
```json
{
  "damage_types": {
    "fire": {
      "description": "Damage from flames or intense heat."
    },
    "arcane_frost": {
      "description": "Magical cold that chills to the bone."
    }
  }
}
```

---

## 3. `xp_rules`

Defines how experience points (XP) are awarded.

**Module Usage:** Used by `QuestManager`, `CombatManager`, or a dedicated XP service after successful quests, encounters, or other achievements.

### `XPRule` Structure:

| Key                         | Type                | Description                                                                                             | Example                                            |
|-----------------------------|---------------------|---------------------------------------------------------------------------------------------------------|----------------------------------------------------|
| `level_difference_modifier` | `Dict[str, float]`  | XP multiplier based on level difference (e.g., entity vs target). Keys are relative levels (e.g., "-2", "0", "+3"). | `{"-5": 0.5, "0": 1.0, "+5": 1.5}`                 |
| `base_xp_per_challenge`     | `Dict[str, int]`    | Base XP awarded for challenges of different ratings (e.g., "easy", "medium", "hard_encounter").         | `{"easy": 50, "medium": 100, "boss": 500}`       |

**Example `xp_rules` entry:**
```json
{
  "xp_rules": {
    "level_difference_modifier": {
      "-3": 0.75,
      "0": 1.0,
      "3": 1.25
    },
    "base_xp_per_challenge": {
      "trivial_mob": 10,
      "standard_quest_stage": 75,
      "major_milestone": 300
    }
  }
}
```

---

## 4. `loot_tables`

Defines loot tables that can be referenced by NPCs, treasure chests, quest rewards, etc. The key for each entry is a unique loot table ID.

**Module Usage:** Used by `LootManager` (or similar) when an entity is defeated, a chest is opened, or a quest is completed.

### `LootTableDefinition` Structure:

| Key       | Type                  | Description                                   | Example                 |
|-----------|-----------------------|-----------------------------------------------|-------------------------|
| `id`      | `str`                 | Unique ID for this loot table.                | `"goblin_chieftain_drops"` |
| `entries` | `List[LootTableEntry]`| List of items that can drop from this table.  |                         |

### `LootTableEntry` Structure:

| Key                | Type          | Description                                                                    | Example  |
|--------------------|---------------|--------------------------------------------------------------------------------|----------|
| `item_template_id` | `str`         | ID of the item template (from `item_templates` table).                         | `"itm_001"`|
| `quantity_dice`    | `str`         | Dice formula for determining the quantity of the item (e.g., "1", "1d3", "2d4"). | `"1d2"`  |
| `weight`           | `int`         | Weight for this entry in weighted random selection from the table.             | `10`     |
| `(future)`         | `Optional[str]` | Could add a `condition` field for conditional drops.                           |          |

**Example `loot_tables` entry:**
```json
{
  "loot_tables": {
    "common_monster_drops": {
      "id": "common_monster_drops",
      "entries": [
        { "item_template_id": "itm_gold_small", "quantity_dice": "2d6", "weight": 50 },
        { "item_template_id": "itm_potion_minor_healing", "quantity_dice": "1", "weight": 20 },
        { "item_template_id": "itm_rusty_dagger", "quantity_dice": "1", "weight": 5 }
      ]
    }
  }
}
```

---

## 5. `action_conflicts`

Defines rules for identifying and resolving conflicts when multiple entities attempt actions that might interfere with each other.

**Module Usage:** Used by the `ConflictResolver` module, which observes actions processed by `ActionProcessor`.

### `ActionConflictDefinition` Structure:

| Key                            | Type             | Description                                                                                              | Example                                                    |
|--------------------------------|------------------|----------------------------------------------------------------------------------------------------------|------------------------------------------------------------|
| `type`                         | `str`            | Unique identifier for the conflict type.                                                                 | `"simultaneous_move_to_limited_slot"`                      |
| `description`                  | `str`            | Human-readable description of the conflict.                                                              | `"Two characters trying to move into the same single-occupancy space."` |
| `involved_intent_pattern`      | `List[str]`      | List of intents that can trigger this conflict (e.g., two "move" intents to the same constrained target). | `["move", "move"]` (for two move actions)                  |
| `resolution_type`              | `str`            | How the conflict is resolved: "auto" (via a check) or "manual" (GM/player choice, or predefined rule).    | `"auto"`                                                   |
| `auto_resolution_check_type`   | `Optional[str]`  | If `resolution_type` is "auto", this is the `check_type` (from `checks`) used to determine the winner.      | `"initiative"` or `"dexterity_contest"`                     |
| `manual_resolution_options`    | `Optional[List[str]]` | If `resolution_type` is "manual", provides descriptive options for choice or logging.                  | `["Character A gets it", "Character B gets it", "Neither"]`|

**Example `action_conflicts` entry:**
```json
{
  "action_conflicts": [
    {
      "type": "contested_item_pickup",
      "description": "Multiple entities attempt to pick up the same item in the same turn.",
      "involved_intent_pattern": ["pickup", "pickup"],
      "resolution_type": "auto",
      "auto_resolution_check_type": "sleight_of_hand_vs_sleight_of_hand"
    }
  ]
}
```

---

## 6. `location_interactions`

Defines interactive elements within locations (e.g., levers, buttons, chests, secret doors) and the outcomes of interacting with them. The key for each entry is a unique interaction ID.

**Module Usage:** Used by a `LocationInteractionService` or directly by `ActionProcessor` when a player attempts to interact with something in a location.

### `LocationInteractionDefinition` Structure:

| Key                 | Type                                  | Description                                                                                                  | Example                                                     |
|---------------------|---------------------------------------|--------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------|
| `id`                | `str`                                 | Unique ID for this interaction point.                                                                        | `"lever_dungeon_cell_A"`                                     |
| `description_i18n`  | `Dict[str, str]`                      | I18n description of the interactable object/point (e.g., {"en": "A rusty lever", "ru": "Ржавый рычаг"}).      | `{"en": "A sturdy oak chest", "ru": "Крепкий дубовый сундук"}` |
| `check_type`        | `Optional[str]`                       | Optional `check_type` (from `checks`) required to successfully interact or to determine the outcome.         | `"lockpicking_average"` or `"strength_heavy_lift"`        |
| `success_outcome`   | `LocationInteractionOutcome`          | Defines what happens if the interaction is successful (or if no check is required).                            | (See `LocationInteractionOutcome` below)                    |
| `failure_outcome`   | `Optional[LocationInteractionOutcome]`| Defines what happens if the interaction check fails.                                                           | (See `LocationInteractionOutcome` below)                    |
| `required_items`    | `Optional[List[str]]`                 | List of item template IDs that the interactor must possess to attempt the interaction (e.g., a key).       | `["itm_old_key_001"]`                                       |

### `LocationInteractionOutcome` Structure:

| Key                  | Type                   | Description                                                                                             | Example                                                    |
|----------------------|------------------------|---------------------------------------------------------------------------------------------------------|------------------------------------------------------------|
| `type`               | `str`                  | Type of outcome, e.g., "reveal_exit", "grant_item", "trigger_trap", "update_state_var", "display_message". | `"grant_item"`                                               |
| `exit_id`            | `Optional[str]`        | (For "reveal_exit") ID of the exit to reveal/enable.                                                    | `"exit_secret_passage"`                                      |
| `item_template_id`   | `Optional[str]`        | (For "grant_item") ID of the item template to grant.                                                      | `"itm_potion_healing"`                                     |
| `quantity`           | `Optional[int]`        | (For "grant_item") Quantity of the item to grant. Defaults to 1.                                        | `1`                                                        |
| `trap_id`            | `Optional[str]`        | (For "trigger_trap") ID of a trap definition (schema for traps TBD).                                    | `"trap_fireball_rune"`                                     |
| `state_var_name`     | `Optional[str]`        | (For "update_state_var") Name of a state variable (e.g., on the location or global) to update.          | `"lever_cell_A_pulled"`                                    |
| `state_var_new_value`| `Optional[Any]`        | (For "update_state_var") New value for the state variable.                                              | `true`                                                     |
| `message_i18n`       | `Optional[Dict[str, str]]` | (For "display_message") An i18n message to display to the player.                                       | `{"en": "The mechanism clicks!", "ru": "Механизм щёлкнул!"}` |


**Example `location_interactions` entry:**
```json
{
  "location_interactions": {
    "chest_barracks_01": {
      "id": "chest_barracks_01",
      "description_i18n": {"en": "A locked wooden chest sits in the corner.", "ru": "В углу стоит запертый деревянный сундук."},
      "check_type": "lockpicking_average",
      "success_outcome": {
        "type": "grant_item",
        "item_template_id": "itm_gold_coins",
        "quantity": 10
      },
      "failure_outcome": {
        "type": "display_message",
        "message_i18n": {"en": "You failed to pick the lock.", "ru": "Вам не удалось взломать замок."}
      }
    },
    "lever_ancient_tomb": {
      "id": "lever_ancient_tomb",
      "description_i18n": {"en": "A large, stone lever covered in moss.", "ru": "Большой каменный рычаг, покрытый мхом."},
      "check_type": "strength_heavy_lift",
      "success_outcome": {
        "type": "reveal_exit",
        "exit_id": "exit_tomb_secret_chamber"
      },
      "failure_outcome": {
        "type": "display_message",
        "message_i18n": {"en": "The lever doesn't budge.", "ru": "Рычаг не поддается."}
      },
      "required_items": ["itm_gauntlets_of_ogre_power"]
    }
  }
}
```

---

This schema provides a comprehensive framework for defining game rules that can be dynamically loaded and used by various game systems to ensure consistent and configurable game behavior.

---

## 7. `base_stats`

Defines the core attributes or statistics that characters and NPCs can possess. The key for each entry is the stat ID (e.g., "STR", "DEX", "HP").

**Module Usage:** Used by `CharacterManager` for character creation, level-ups, and as a reference for any system that needs to know about base stat properties. `EffectiveStatsCalculator` uses these as the foundation before applying modifiers.

### `BaseStatDefinition` Structure:

| Key                  | Type             | Description                                                                 | Example                                               |
|----------------------|------------------|-----------------------------------------------------------------------------|-------------------------------------------------------|
| `name_i18n`          | `Dict[str, str]` | I18n display name for the stat.                                             | `{"en": "Strength", "ru": "Сила"}`                    |
| `description_i18n`   | `Dict[str, str]` | I18n description of what the stat represents.                               | `{"en": "Physical power and brawn", "ru": "..."}`     |
| `default_value`      | `int`            | Default value for this stat when a character is created or if not specified. | `10`                                                  |
| `min_value`          | `int`            | Absolute minimum value this stat can be.                                    | `1`                                                   |
| `max_value`          | `int`            | Absolute maximum value this stat can typically reach (can be overridden).   | `20` (for player stats), `100` (for HP or monster stats) |

**Example `base_stats` entry:**
```json
{
  "base_stats": {
    "STR": {
      "name_i18n": {"en": "Strength", "ru": "Сила"},
      "description_i18n": {"en": "Measures raw physical power.", "ru": "Измеряет грубую физическую силу."},
      "default_value": 10,
      "min_value": 3,
      "max_value": 20
    },
    "HP": {
      "name_i18n": {"en": "Hit Points", "ru": "Очки Здоровья"},
      "description_i18n": {"en": "Represents health and vitality.", "ru": "Отражает здоровье и живучесть."},
      "default_value": 10,
      "min_value": 0,
      "max_value": 999
    }
  }
}
```

---

## 8. `item_effects`

Defines reusable sets of effects that can be applied by items. The key for each entry is an effect ID (e.g., "minor_healing_effect", "strength_boost_potion") which can be referenced by item definitions (e.g., in an item's `properties` field).

**Module Usage:** Used by `ItemManager` or `EffectApplierService` when an item is used or equipped to determine what changes to make to the character's stats or state.

### `ItemEffectDefinition` Structure:

| Key                             | Type                          | Description                                                                    | Example                               |
|---------------------------------|-------------------------------|--------------------------------------------------------------------------------|---------------------------------------|
| `description_i18n`              | `Optional[Dict[str, str]]`    | Optional i18n description of the combined effects (e.g., for display on item). | `{"en": "Restores health and boosts might."}` |
| `stat_modifiers`                | `List[StatModifierRule]`           | List of direct modifications to character stats.                               | (See `StatModifierRule` below)        |
| `grants_abilities_or_skills`    | `List[GrantedAbilityOrSkill]`      | List of abilities or skills granted by the effect.                             | (See `GrantedAbilityOrSkill` below)   |
| `slot`                          | `Optional[str]`                    | If this effect is tied to an equippable item, specifies the slot ID it occupies. | `"main_hand"`                         |
| `direct_health_effects`         | `Optional[List[DirectHealthEffect]]`| List of direct healing or damage effects.                                      | (See `DirectHealthEffect` below)      |
| `apply_status_effects`          | `Optional[List[ApplyStatusEffectRule]]`| Status effects to apply on use or equip.                                       | (See `ApplyStatusEffectRule` below)   |
| `learn_spells`                  | `Optional[List[LearnSpellRule]]`   | Spells learned permanently by the user.                                        | (See `LearnSpellRule` below)          |
| `grant_resources`               | `Optional[List[GrantResourceRule]]`| Resources granted to the user (e.g., mana, gold).                              | (See `GrantResourceRule` below)       |
| `consumable`                    | `bool`                             | If true, the item is consumed after a single use. Defaults to `False`.         | `True` (for a potion)                 |
| `target_policy`                 | `str`                              | Defines targeting rules: "self", "requires_target", "no_target". Defaults to "self". | `"requires_target"`                   |


### `StatModifierRule` Structure:

| Key                | Type            | Description                                                                                             | Example                               |
|--------------------|-----------------|---------------------------------------------------------------------------------------------------------|---------------------------------------|
| `stat_name`        | `str`           | The name of the stat to modify (e.g., "HP", "strength", "fire_resistance"). This should map to a defined stat key. | `"HP"`                                |
| `bonus_type`       | `str`           | Type of bonus: "flat" (adds value), "multiplier" (multiplies stat), "percentage_increase" (adds X% of base). | `"flat"`                              |
| `value`            | `float`         | The value of the modification.                                                                          | `10` (for flat HP bonus)              |
| `duration_turns`   | `Optional[int]` | For temporary effects, duration in game turns. `None` for permanent or until item is unequipped.        | `5`                                   |

### `GrantedAbilityOrSkill` Structure:

| Key  | Type  | Description                                                              | Example            |
|------|-------|--------------------------------------------------------------------------|--------------------|
| `id` | `str` | ID of the ability or skill being granted (references Ability/Skill definitions). | `"abil_fire_aura"` |
| `type` | `str` | Specifies if it's an "ability" or a "skill".                             | `"ability"`        |

### `DirectHealthEffect` Structure:

| Key           | Type  | Description                                                              | Example        |
|---------------|-------|--------------------------------------------------------------------------|----------------|
| `amount`      | `int` | Amount of health to change (positive for heal, negative for damage).     | `10` (heal), `-5` (damage) |
| `effect_type` | `str` | Type of health effect, e.g., "heal", "damage". Can also be "temp_hp".    | `"heal"`       |

### `ApplyStatusEffectRule` Structure:

| Key                  | Type            | Description                                                                                             | Example                     |
|----------------------|-----------------|---------------------------------------------------------------------------------------------------------|-----------------------------|
| `status_effect_id`   | `str`           | ID of the status effect to apply (references a key in `CoreGameRulesConfig.status_effects`).            | `"sef_blessed_might"`       |
| `duration_turns`     | `Optional[int]` | Overrides default status effect duration if specified. Use `0` for instant, `None` for default duration. | `10`                        |
| `target`             | `str`           | Target of the status effect: "self" or "target_entity". Defaults to "self".                             | `"target_entity"`           |

### `LearnSpellRule` Structure:

| Key        | Type  | Description                                           | Example              |
|------------|-------|-------------------------------------------------------|----------------------|
| `spell_id` | `str` | ID of the spell to be learned by the character.       | `"spell_fireball_v1"` |

### `GrantResourceRule` Structure:

| Key             | Type  | Description                                                              | Example       |
|-----------------|-------|--------------------------------------------------------------------------|---------------|
| `resource_name` | `str` | Name of the resource to grant (e.g., "mana", "gold", "action_points").   | `"mana"`      |
| `amount`        | `int` | Amount of the resource to grant.                                         | `25`          |


**Example `item_effects` entry:**
```json
{
  "item_effects": {
    "potion_of_healing_sml": {
      "description_i18n": {"en": "Restores a small amount of health."},
      "direct_health_effects": [
        {"amount": 10, "effect_type": "heal"}
      ],
      "consumable": true,
      "target_policy": "self"
    },
    "amulet_of_strength": {
      "description_i18n": {"en": "Grants enhanced strength while worn."},
      "stat_modifiers": [
        {"stat_name": "strength", "bonus_type": "flat", "value": 2}
      ],
      "grants_abilities_or_skills": [
        {"id": "skill_intimidate_bonus", "type": "skill"}
      ],
      "slot": "neck",
      "consumable": false,
      "target_policy": "self"
    },
    "scroll_of_fireball": {
      "description_i18n": {"en": "A scroll that unleashes a fiery explosion."},
      "apply_status_effects": [
        {"status_effect_id": "sef_burning_hands", "duration_turns": 3, "target": "target_entity"}
      ],
      "learn_spells": [
        {"spell_id": "spell_minor_fireball"}
      ],
      "consumable": true,
      "target_policy": "requires_target"
    }
  }
}
```

---

## 9. `status_effects`

Defines status effects (buffs, debuffs, conditions) that can be applied to characters. The key for each entry is a unique status effect ID (e.g., "poisoned", "blessed").

**Module Usage:** Used by `StatusManager` or `EffectApplierService` to apply, track, and remove status effects. The `EffectiveStatsCalculator` will also use these to modify character stats dynamically.

### `StatusEffectDefinition` Structure:

| Key                             | Type                          | Description                                                                                                | Example                                                     |
|---------------------------------|-------------------------------|------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------|
| `id`                            | `str`                         | Unique ID for this status effect type.                                                                     | `"sef_poisoned_lvl1"`                                       |
| `name_i18n`                     | `Dict[str, str]`              | I18n display name for the status effect.                                                                   | `{"en": "Poisoned (Minor)", "ru": "Отравление (слабое)"}`     |
| `description_i18n`              | `Dict[str, str]`              | I18n description of what the status effect does.                                                           | `{"en": "Losing health each turn.", "ru": "..."}`           |
| `stat_modifiers`                | `List[StatModifierRule]`      | List of direct modifications to character stats while the status is active.                                | `[{"stat_name": "dexterity", "bonus_type": "flat", "value": -2}]` |
| `grants_abilities_or_skills`    | `List[GrantedAbilityOrSkill]` | List of abilities or skills temporarily granted or suppressed by the status.                               |                                                             |
| `duration_type`                 | `str`                         | How duration is measured: "turns", "permanent" (until removed by specific action), "until_condition_met".  | `"turns"`                                                   |
| `default_duration_turns`        | `Optional[int]`               | Default duration in game turns, if `duration_type` is "turns".                                             | `5`                                                         |
| `(future)`                      |                               | Could include `tick_effect` (for damage/healing over time), `on_apply_message_i18n`, `is_positive_effect`. |                                                             |

**Example `status_effects` entry:**
```json
{
  "status_effects": {
    "sef_blessed_might": {
      "id": "sef_blessed_might",
      "name_i18n": {"en": "Blessed Might", "ru": "Благословенная Мощь"},
      "description_i18n": {"en": "You feel a surge of divine strength!", "ru": "Вы чувствуете прилив божественной силы!"},
      "stat_modifiers": [
        {"stat_name": "attack_bonus", "bonus_type": "flat", "value": 2},
        {"stat_name": "strength_save_bonus", "bonus_type": "flat", "value": 1}
      ],
      "duration_type": "turns",
      "default_duration_turns": 10
    },
    "sef_minor_poison": {
      "id": "sef_minor_poison",
      "name_i18n": {"en": "Minor Poison", "ru": "Слабый Яд"},
      "description_i18n": {"en": "Slightly weakened by poison.", "ru": "Слегка ослаблен ядом."},
      "stat_modifiers": [
        {"stat_name": "constitution", "bonus_type": "flat", "value": -1, "duration_turns": 5}
      ],
      "duration_type": "turns", // Overall status duration
      "default_duration_turns": 5 // Redundant if all mods have duration, but good for overall status
      // "tick_effect": {"type": "damage", "damage_type": "poison", "amount_dice": "1d2"} // Future
    }
  }
}
```

---

This schema provides a comprehensive framework for defining game rules that can be dynamically loaded and used by various game systems to ensure consistent and configurable game behavior.

---

## 10. `equipment_slots`

Defines the available equipment slots on a character and what types of items can be equipped in them. The key for each entry is a unique `slot_id` (e.g., "main_hand", "armor_body", "finger_1").

**Module Usage:** Used by `InventoryManager` or `CharacterManager` when equipping items to validate compatibility. Also used by UI to display equipment slots. The `EffectiveStatsCalculator` may also need to know which items are in which slots if effects are slot-dependent (though effects themselves might also specify their slot).

### `EquipmentSlotDefinition` Structure:

| Key                       | Type             | Description                                                                    | Example                                               |
|---------------------------|------------------|--------------------------------------------------------------------------------|-------------------------------------------------------|
| `slot_id`                 | `str`            | Unique identifier for the equipment slot.                                      | `"main_hand"`                                         |
| `name_i18n`               | `Dict[str, str]` | I18n display name for the slot.                                                | `{"en": "Main Hand", "ru": "Основная рука"}`           |
| `compatible_item_types`   | `List[str]`      | List of item type identifiers (e.g., "weapon_sword", "armor_chest_heavy", "ring") that can be equipped in this slot. | `["weapon_sword", "weapon_axe", "weapon_mace"]` |
| `(future) max_items`      | `int`            | Max number of items this slot can hold (e.g., 2 for rings). Defaults to 1.     | `2` (for a ring slot)                                 |

**Example `equipment_slots` entry:**
```json
{
  "equipment_slots": {
    "main_hand": {
      "slot_id": "main_hand",
      "name_i18n": {"en": "Main Hand", "ru": "Основная рука"},
      "compatible_item_types": ["weapon_sword", "weapon_axe", "weapon_mace", "shield_small"]
    },
    "armor_body": {
      "slot_id": "armor_body",
      "name_i18n": {"en": "Body Armor", "ru": "Нательная броня"},
      "compatible_item_types": ["armor_light_body", "armor_medium_body", "armor_heavy_body"]
    },
    "finger_1": {
      "slot_id": "finger_1",
      "name_i18n": {"en": "Finger 1", "ru": "Палец 1"},
      "compatible_item_types": ["ring"]
    },
    "finger_2": {
      "slot_id": "finger_2",
      "name_i18n": {"en": "Finger 2", "ru": "Палец 2"},
      "compatible_item_types": ["ring"]
    }
  }
}
```

---

This schema provides a comprehensive framework for defining game rules that can be dynamically loaded and used by various game systems to ensure consistent and configurable game behavior.
