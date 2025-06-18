# Event Trigger Processing Logic

This document outlines the necessary logic changes in various game systems to process the event triggers defined in `Location.event_triggers` (see `documentation/json_structures.md`).

## 1. Core Trigger Evaluation Service

A central service, potentially named `EventTriggerEvaluator` or integrated within `WorldSimulationProcessor` and `CharacterActionProcessor`, will be responsible for checking trigger conditions. This service would need access to:

*   **`LocationManager`**: To fetch `Location.event_triggers` and `Location.state_variables_json`.
*   **`CharacterManager`**: To get details about characters in a location (for `on_player_action`, `on_player_enter_area` conditions, and for targeting actions like `grant_item_to_player`).
*   **`NpcManager`**: To get NPC states for `on_npc_state_change` conditions.
*   **`TimeManager`**: For `on_time_of_day` and `on_game_time_elapsed` conditions.
*   **`WorldStateManager` (or `GameManager.get_rule("world_state_flags")`)**: For `on_world_state_change` conditions.
*   **`ItemManager`**: To validate `item_template_id` if needed, or get item properties.
*   **Player Action Log/Queue (if available)**: For recently performed actions if checking reactively.

## 2. `WorldSimulationProcessor` (or new `LocationEventTriggerService`)

This processor will handle triggers that are not directly tied to an immediate player action. It will run periodically (e.g., every few seconds or on a game tick).

*   **Iteration:**
    *   Identify "active" locations (e.g., locations with players, or locations flagged for continuous simulation).
    *   For each active location, retrieve its `event_triggers` list from `LocationManager`.
*   **Trigger Evaluation Loop:**
    *   For each trigger in the list:
        1.  **Check `is_active`**: If `false`, skip.
        2.  **Check Cooldown**: If `cooldown_seconds` is set and `last_triggered_timestamp` indicates it's on cooldown, skip.
        3.  **Evaluate `trigger_condition`**:
            *   **`on_world_state_change`**: Compare `flag_name`'s current value with `expected_value`.
            *   **`on_time_of_day`**: Check current game time against `specific_time` or `time_range_start`/`end`.
            *   **`on_game_time_elapsed`**: Calculate elapsed time based on `reference_point`.
            *   **`random_chance_periodic`**: If `(current_time - last_checked_time_for_this_trigger) >= check_interval_seconds`, roll for `chance_percent`. Update `last_checked_time_for_this_trigger` (this implies triggers might need to store this transient state, or the service manages it).
            *   **`on_npc_state_change`**: Fetch relevant NPC(s) by `npc_id_or_tag`. Evaluate their `state_condition`. This might be complex if checking many NPCs or many conditions frequently. Could be optimized if NPCs emit events on state changes that this service subscribes to.
            *   Other relevant passive condition types.
        4.  **If Condition Met:** Proceed to execution.

## 3. `CharacterActionProcessor`

This processor will handle triggers that are direct reactions to player actions.

*   **Post-Action Hook:**
    *   After a player action is successfully resolved (e.g., `inspect_poi`, `use_item`, `enter_location_first_time`), this hook is called.
    *   Retrieve `event_triggers` for the character's current location.
*   **Trigger Evaluation Loop (Reactive):**
    *   For each trigger in the list:
        1.  **Check `is_active`**: If `false`, skip.
        2.  **Check Cooldown**: If `cooldown_seconds` is set, check against `last_triggered_timestamp`.
        3.  **Evaluate `trigger_condition`**:
            *   Focus on `on_player_action` type triggers. Match `action_type` from the just-completed action.
            *   If `target_poi_id` is specified, check if it matches the action's target.
            *   If `required_item_id` is specified, check character's inventory.
            *   If `min_skill_level` is specified, check character's skills.
            *   `on_item_used_in_location`: Check if the item used matches `item_template_id`.
            *   `on_player_enter_area`: If the action was a movement that resulted in entering a new location or area within the location, check this condition.
        4.  **If Condition Met:** Proceed to execution.

## 4. Trigger Execution Logic (Common to both processors/services)

Once a trigger's condition is met and it's not on cooldown:

1.  **Execute Actions:**
    *   If `event_template_id` is provided:
        *   Call `EventManager.create_event_from_template(event_template_id, location_id, guild_id, execution_params, triggering_character_id_if_any)`.
    *   If `actions_on_trigger` list is present:
        *   Iterate through the action list and execute them. This will involve calling appropriate managers:
            *   `spawn_npc`: Call `NpcManager.spawn_npc_in_location(...)`.
            *   `display_message_i18n`: Call a messaging service or `GameLogManager`.
            *   `change_location_state`: Call `LocationManager.update_location_state_variable(location_id, variable_name, new_value, operation)`.
            *   `grant_item_to_player`: Call `InventoryManager.add_item_to_character(...)` (requires identifying the correct player, especially for non-player-action triggers).
            *   `update_poi_state`: Call `LocationManager.update_poi_state(location_id, poi_id, new_poi_state_data)`.
2.  **Update Trigger State:**
    *   Set `last_triggered_timestamp` to the current time.
    *   If `one_time_only` is `true`, set `is_active` to `false`.
    *   These changes require updating the `Location` object's `event_triggers` JSONB field via `LocationManager` and marking the location as dirty for persistence.

## 5. Required Manager Modifications/Helpers

*   **`LocationManager`:**
    *   `update_location_state_variable(location_id, variable_name, new_value, operation)`: To modify `Location.state_variables_json`.
    *   `update_poi_state(location_id, poi_id, new_poi_state_data)`: To modify a specific PoI within `Location.points_of_interest_json`.
    *   `update_event_trigger_state(location_id, trigger_id, new_trigger_data)`: To update fields like `is_active` or `last_triggered_timestamp` for a specific trigger in `Location.event_triggers`.
*   **`EventManager`:**
    *   `create_event_from_template(...)` needs to be robust.
*   **`NpcManager`:**
    *   `spawn_npc_in_location(...)` needs to handle quantity, spawn points, and temporary duration.
    *   Methods to query NPC states based on tags or multiple IDs might be useful for `on_npc_state_change` conditions.
*   **`InventoryManager` (or `ItemManager`):**
    *   `add_item_to_character(...)`.
*   **`TimeManager`:**
    *   Provide easy access to current game time components relevant for trigger conditions (e.g., hour, minute, time of day category like "night").

## 6. Considerations

*   **Performance:** Iterating through many locations and many triggers frequently can be performance-intensive. Optimizations might include:
    *   Only checking triggers in locations that are "active" (e.g., have players).
    *   Indexing triggers by condition type for faster lookup (e.g., only check `on_time_of_day` triggers when the time changes significantly).
    *   For `on_npc_state_change`, consider an event-driven approach where NPCs emit state change events, and triggers subscribe to these, rather than polling.
*   **Complexity of Conditions:** The `trigger_condition` can become very complex. The evaluation logic needs to be robust and extensible.
*   **Targeting for Actions:** For triggers not directly initiated by a player (e.g., `random_chance_periodic`), actions like `grant_item_to_player` need clear rules for selecting the target player(s) in the location.
*   **Serialization/Deserialization:** Ensure that changes to `Location.event_triggers` (like marking a trigger inactive) are correctly persisted.

This document outlines the high-level logic for integrating and processing dynamic event triggers within the game.
