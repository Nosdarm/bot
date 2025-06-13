# Relationship Rules Configuration

This document outlines the structure for configuring relationship dynamics and their influence on game mechanics. These rules are typically defined in a JSON configuration file (e.g., `data/relationship_rules_config.json`) and loaded into the game's `RuleEngine`.

## 1. `relation_rules` - Defining Relationship Changes

`relation_rules` dictate how relationships between entities (players, NPCs, factions) change in response to game events. Each rule specifies the event, conditions, and the exact modifications to relationship strength or type.

**Structure:** An array of `RelationChangeRule` objects.

### `RelationChangeRule` Object:

*   `name` (String, Required): A unique name for the rule (e.g., "QuestCompletedWithNpcPositive").
*   `event_type` (String, Required): The specific game event that triggers this rule (e.g., "quest_completed", "combat_attack").
*   `condition` (String, Optional): A Python expression string evaluated against `event_data` associated with the event. If true, the rule's changes are processed.
    *   Example: `"event_data.get('outcome') == 'success' and event_data.get('npc_id') is not None"`
*   `changes` (List of `RelationChangeInstruction` objects, Required): A list of specific changes to apply if the condition is met.
*   `description` (String, Optional): A human-readable description of the rule's purpose.

### `RelationChangeInstruction` Object:

*   `entity1_ref` (String, Required): A reference to the first entity involved in the relationship change. This is a key to look up in `event_data` (e.g., "player_id", "attacker_id").
*   `entity1_type_ref` (String, Required): A reference to the type of the first entity. Can be a key in `event_data` (e.g., "player_type") or a literal string (e.g., `"'faction'"` - note the inner quotes for literals).
*   `entity2_ref` (String, Required): Reference for the second entity.
*   `entity2_type_ref` (String, Required): Type reference for the second entity.
*   `relation_type` (String, Required): The type of relationship being affected (e.g., "friendly", "hostile", "reputation", "personal_hostility").
*   `update_type` (String, Required): How the strength is modified. Enum:
    *   `"add"`: Adds `magnitude_formula` result to current strength.
    *   `"subtract"`: Subtracts `magnitude_formula` result from current strength.
    *   `"set"`: Sets current strength to `magnitude_formula` result.
    *   `"multiply"`: Multiplies current strength by `magnitude_formula` result.
*   `magnitude_formula` (String, Required): A Python expression string that evaluates to a numerical value for the strength change. Can use `event_data` and `current_strength`.
    *   Example: `"10"`, `"event_data.get('quest_xp_reward', 0) * 0.1"`, `"current_strength * 0.5"`
*   `condition` (String, Optional): A sub-condition specific to this instruction, evaluated against `event_data`.
*   `name` (String, Optional): An optional name for this specific instruction.
*   `description` (String, Optional): A description of this specific instruction.

## 2. `relationship_influence_rules` - Defining Relationship Effects

`relationship_influence_rules` define how existing relationship strengths affect various game mechanics, such as dialogue, NPC behavior, and combat.

**Structure:** An array of `RelationshipInfluenceRule` objects.

### `RelationshipInfluenceRule` Object:

*   `name` (String, Required): A unique name for the influence rule (e.g., "DialogueSkillCheckBonus_FriendlyNPC").
*   `influence_type` (String, Required): Categorizes the type of influence (e.g., "dialogue_skill_check", "npc_targeting", "dialogue_option_availability", "npc_behavior_hostility").
*   `condition` (String, Optional): A Python expression evaluated against context provided by the game system using this rule (e.g., `character`, `npc`, `option_data`, `rule_context`).
    *   Example: `"npc is not None and rule_context.get('skill_type') == 'persuasion'"`
*   `threshold_type` (String, Optional): The type of strength threshold. Enum: `"min_strength"`, `"max_strength"`.
*   `threshold_value` (Float, Optional): The relationship strength value for the threshold.
*   `bonus_malus_formula` (String, Optional): A Python expression for calculating a bonus or penalty (e.g., for skill checks, threat scores). Can use `current_strength`.
    *   Example: `"5 + (current_strength / 20)"`, `"(abs(current_strength) / 10.0)"`
*   `effect_description_i18n_key` (String, Optional): An i18n key for feedback messages (e.g., "feedback.relationship.dialogue_check_bonus").
*   `effect_params_mapping` (Dict, Optional): Maps parameters for the i18n feedback string to available context variables.
    *   Example: `{"npc_name": "npc.name", "bonus_amount_str": "calculated_bonus_str"}`
*   `availability_flag` (Boolean, Optional): For "dialogue_option_availability", `true` if the option becomes available when conditions/thresholds met, `false` if it becomes unavailable.
*   `failure_feedback_key` (String, Optional): For "dialogue_option_availability", i18n key for why an option is unavailable.
*   `failure_feedback_params_mapping` (Dict, Optional): Parameters for the `failure_feedback_key`.

**Evaluation Context:**
The `condition`, `magnitude_formula`, and `bonus_malus_formula` fields are evaluated as Python expressions. The exact variables available in their context depend on where the rule is being applied:
*   For `relation_rules`: `event_data` (dict of event-specific data) and `current_strength` (for the specific relationship being modified by an instruction).
*   For `relationship_influence_rules`: `current_strength` (of the relevant relationship), and context-specific objects like `character`, `npc`, `option_data`, `rule_context` (a dict for miscellaneous data like skill type).

Refer to `data/relationship_rules_config.json` for concrete examples of these rule structures.
