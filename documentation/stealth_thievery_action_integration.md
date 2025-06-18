# Stealth and Thievery: Action Integration Plan

This document outlines the plan for integrating new stealth and thievery player actions into the game's action processing system.

## 1. Identified Modules for Action Processing

The primary modules involved in processing player actions, from command input to rule engine execution, are:

*   **Command Parsing:**
    *   `bot/game/command_handlers/`: This directory will house the new command definitions. A new file like `thievery_commands.py` could be created, or existing files like `action_commands.py` or `interaction_commands.py` could be augmented.
*   **Action Storage & Management:**
    *   `bot/game/managers/character_manager.py`: Manages `Character` objects, which store the `current_action_json` or an action queue. This manager will be used to set and clear actions for characters.
*   **Action Execution & Rule Engine Invocation:**
    *   `bot/game/character_processors/character_action_processor.py`: This appears to be the most specialized module for handling actions initiated by player characters. It's the likely candidate for recognizing the new action types and calling the `RuleEngine`.
    *   `bot/game/action_processor.py`: A more generic action processor. It might be a higher-level dispatcher or used for non-character actions. `CharacterActionProcessor` might be a specific implementation it uses.
    *   `bot/game/turn_processor.py`: Could be responsible for overall turn management, including invoking the `CharacterActionProcessor` for each character that has a pending action.
*   **Rule Engine:**
    *   `bot/game/rules/rule_engine.py`: Contains the game logic (e.g., `resolve_stealth_check`) that `CharacterActionProcessor` will call.
*   **Orchestration:**
    *   `bot/game/managers/game_manager.py`: Likely initializes and coordinates the interaction between these managers and processors.

## 2. Defined Action Structures

The following JSON structures will be used to represent the new actions. These will typically be stored in a field like `Character.current_action_json` or managed in an action queue.

*   **Stealth Action:**
    ```json
    {
      "type": "stealth_attempt",
      "character_id": "char_id_performing_action",
      "guild_id": "guild_id_of_character",
      "location_id": "current_location_id_of_character"
    }
    ```

*   **Pickpocket Action:**
    ```json
    {
      "type": "pickpocket_attempt",
      "character_id": "char_id_performing_action",
      "guild_id": "guild_id_of_character",
      "target_npc_id": "npc_id_being_targeted",
      "location_id": "current_location_id_of_character"
      // "target_item_id": "item_id_optional" // Future enhancement
    }
    ```

*   **Lockpick Action:**
    ```json
    {
      "type": "lockpick_attempt",
      "character_id": "char_id_performing_action",
      "guild_id": "guild_id_of_character",
      "target_poi_id": "poi_id_of_locked_object", // e.g., a chest or door
      "location_id": "current_location_id_of_poi"
    }
    ```

*   **Disarm Trap Action:**
    ```json
    {
      "type": "disarm_trap_attempt",
      "character_id": "char_id_performing_action",
      "guild_id": "guild_id_of_character",
      "target_poi_id": "poi_id_of_trap",
      "location_id": "current_location_id_of_poi"
    }
    ```
    *(Added `guild_id` to all actions for consistency and utility in manager/engine calls)*

## 3. Conceptual Command Parsing

New slash commands will be introduced. These commands will be responsible for:
1.  Parsing user input (e.g., target names, PoI identifiers).
2.  Resolving these inputs to game entity IDs (e.g., `npc_id`, `poi_id`). This might involve querying `NpcManager` or `LocationManager`.
3.  Constructing one of the action JSON structures defined above.
4.  Using `CharacterManager` to assign this action to the character (e.g., setting `current_action_json` or adding to an action queue).

**Example Commands (Conceptual):**

*   `/stealth`: Initiates a stealth attempt in the current location.
    *   Parses to: `{"type": "stealth_attempt", "character_id": "...", "guild_id": "...", "location_id": "..."}`
*   `/pickpocket <target_npc_name_or_id>`: Attempts to pickpocket the specified NPC.
    *   Needs to resolve `<target_npc_name_or_id>` to an `npc_id`.
    *   Parses to: `{"type": "pickpocket_attempt", "character_id": "...", "guild_id": "...", "target_npc_id": "...", "location_id": "..."}`
*   `/lockpick <target_poi_description_or_id>`: Attempts to pick a lock on a specified object/PoI.
    *   Needs to resolve `<target_poi_description_or_id>` to a `poi_id` within the character's current location. This might involve looking up PoIs in `Location.points_of_interest_json`.
    *   Parses to: `{"type": "lockpick_attempt", "character_id": "...", "guild_id": "...", "target_poi_id": "...", "location_id": "..."}`
*   `/disarm <target_poi_description_or_id>`: Attempts to disarm a specified trap/PoI.
    *   Similar resolution as lockpicking for `poi_id`.
    *   Parses to: `{"type": "disarm_trap_attempt", "character_id": "...", "guild_id": "...", "target_poi_id": "...", "location_id": "..."}`

A new file, e.g., `bot/game/command_handlers/thievery_commands.py`, could be created, or these commands could be added to `action_commands.py`.

## 4. Integration Points in Action Processor

The `bot/game/character_processors/character_action_processor.py` (or a similar central action processing module) will be the primary integration point. It will need to:

1.  **Recognize New Action Types:** In its main action processing loop/method, add `if/elif` blocks or switch-case statements to handle the new action `type` strings: `"stealth_attempt"`, `"pickpocket_attempt"`, `"lockpick_attempt"`, `"disarm_trap_attempt"`.
2.  **Fetch Action Data:** Retrieve the details from the action JSON (e.g., `target_npc_id`, `target_poi_id`).
3.  **Fetch Additional Game State:**
    *   For lockpicking and disarming, it will need to fetch the `poi_data` for the `target_poi_id` from `LocationManager.get_location().points_of_interest_json`.
4.  **Call RuleEngine Methods:** Invoke the corresponding methods implemented in `RuleEngine`:
    *   `rule_engine.resolve_stealth_check(character_id, guild_id, location_id, **action_data)`
    *   `rule_engine.resolve_pickpocket_attempt(character_id, guild_id, target_npc_id=action_data['target_npc_id'], **action_data)`
    *   `rule_engine.resolve_lockpick_attempt(character_id, guild_id, poi_data=fetched_poi_data, **action_data)`
    *   `rule_engine.resolve_disarm_trap_attempt(character_id, guild_id, poi_data=fetched_poi_data, **action_data)`
5.  **Process `DetailedCheckResult`:** Use the outcome from the `RuleEngine` to:
    *   **Update Game State:**
        *   Stealth: Potentially update character status (e.g., "hidden") or NPC/location awareness levels.
        *   Pickpocket: If successful and `item_id_stolen` is present, use `InventoryManager` to transfer the item. If detected, update NPC disposition or trigger alerts.
        *   Lockpick: If successful, update the PoI state in `Location.points_of_interest_json` (e.g., `is_locked: false`).
        *   Disarm Trap: If successful, update PoI state (`is_active: false`). If `trap_triggered_on_fail` is true, trigger the trap's effects (this might involve another call to `RuleEngine` or a different service to apply effects).
    *   **Generate Player Feedback:** Send messages to the player about the action's outcome (success, failure, detection, items stolen, trap triggered, etc.).
6.  **Clear Action:** After processing, use `CharacterManager` to clear the action from the character.

## 5. Summary of Anticipated Changes

*   **`bot/game/command_handlers/` (New or existing files like `action_commands.py`):**
    *   Add new slash command handlers for `/stealth`, `/pickpocket`, `/lockpick`, `/disarm`.
    *   Implement logic to parse arguments, resolve entity IDs, construct action JSONs, and queue them using `CharacterManager`.
*   **`bot/game/character_processors/character_action_processor.py` (or similar):**
    *   Modify the main action processing method to include `if/elif` conditions for the new action types.
    *   For each new action type:
        *   Add logic to extract necessary parameters from the action JSON.
        *   Add logic to fetch required game state (e.g., PoI data for lockpicking/disarming).
        *   Call the corresponding `RuleEngine.resolve_*` method.
        *   Implement logic to handle the `DetailedCheckResult`: update game state (characters, NPCs, PoIs, inventories), and generate player feedback.
*   **`bot/game/managers/location_manager.py` (Potentially):**
    *   May need helper methods to easily update the state of a PoI (e.g., `mark_poi_unlocked(location_id, poi_id)`, `mark_poi_trap_disarmed(location_id, poi_id)`). This is to avoid direct manipulation of JSON from the action processor.
*   **`bot/game/managers/character_manager.py`:**
    *   No new methods anticipated, but will be used by command handlers to set actions and by the action processor to get/clear actions.
*   **`bot/game/models/character.py` (No change):**
    *   The `skills_data_json` field is already used by `RuleEngine`.
    *   `current_action_json` or similar field for action queueing is assumed to exist or be adaptable.
*   **`bot/game/models/location.py` (No change):**
    *   The `points_of_interest_json` structure is already defined to support lock and trap details.

This plan provides a roadmap for the implementation of stealth and thievery actions. The next steps would involve creating specific subtasks for coding the command handlers and modifying the action processor.
