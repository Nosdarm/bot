# Proactive NPC Behavior and Triggered Action Processing Logic

This document outlines the logic for processing proactive NPC behaviors based on `NPC.behavior_tags` and handling NPC-initiated actions defined within `Location.event_triggers.actions_on_trigger`.

## 1. Processing `NPC.behavior_tags`

Proactive behaviors based on `NPC.behavior_tags` are typically checked when an NPC is idle or performing a low-priority scheduled activity, and a player character is nearby. They can also be checked immediately after a player action that might change the context for the NPC.

### A. `WorldSimulationProcessor` (During NPC Tick/Update)

*   **Condition for Checking:** When an NPC is determined to be in an "idle" state, or performing a low-priority, interruptible activity from its schedule (e.g., "wandering", "observing").
*   **Player Proximity:**
    1.  Identify players within a certain radius of the NPC or in the same location. If no players are nearby, proactive behaviors targeting players are usually skipped.
    2.  For each nearby player:
        *   Iterate through the NPC's `behavior_tags`.
        *   Parse each tag (e.g., split by ':').
        *   Evaluate the condition implied by the tag pattern against the current player and game state.
*   **Tag Evaluation & Action Examples:**
    *   **`PROACTIVE_DIALOGUE:QUEST_AVAILABLE:<quest_id>`**:
        *   **Condition:** Check `QuestManager` if `player` is eligible for `<quest_id>` (meets prerequisites, hasn't started/completed).
        *   **Action:** If true, and NPC is not in combat/critical action, call `DialogueManager.start_dialogue(npc, player, dialogue_tree_id_for_quest_offer)`. (The specific dialogue tree might be linked to the quest or a default "quest offer" dialogue).
    *   **`PROACTIVE_DIALOGUE:CONDITION:<condition_key>:<dialogue_tree_id>`**:
        *   **Condition:** Use `RuleEngine.check_conditions` with a predefined condition structure associated with `<condition_key>`, targeting the `player` or `world_state`.
        *   **Action:** If true, `DialogueManager.start_dialogue(npc, player, dialogue_tree_id)`.
    *   **`PROACTIVE_DIALOGUE:FIRST_ENCOUNTER:<dialogue_tree_id>`**:
        *   **Condition:** Check if this NPC has a "met_player_X" flag for the current player (managed via `RelationshipManager` or NPC state).
        *   **Action:** If not met, `DialogueManager.start_dialogue(npc, player, dialogue_tree_id)` and set the "met_player_X" flag.
    *   **`PROACTIVE_WARNING:AREA_RESTRICTED:<area_id_or_name>:<dialogue_tree_id_or_message_key>`**:
        *   **Condition:** Check if `player.current_area_id_within_location` matches `<area_id_or_name>`.
        *   **Action:** Initiate dialogue or send a direct message (e.g., using a notification service).
    *   **`PROACTIVE_HOSTILITY:FACTION_HATE:<enemy_faction_id>`**:
        *   **Condition:** Check `player.faction_id` against `<enemy_faction_id>` and NPC's own faction's relationships (via `RelationshipManager` or `FactionManager`).
        *   **Action:** If hostile relationship confirmed, call `CombatManager.initiate_combat(npc, player)`.
    *   **`PROACTIVE_HOSTILITY:ITEM_DETECTED:<forbidden_item_template_id>:<dc_optional>`**:
        *   **Condition:** Check `player.inventory` for `<forbidden_item_template_id>`. If `dc_optional` is present, NPC makes a perception check (vs. player's stealth/concealment if applicable).
        *   **Action:** If detected, `CombatManager.initiate_combat(npc, player)`.
    *   **`PROACTIVE_INTERACTION:ITEM_REQUEST:<item_template_id>:<dialogue_tree_id>`**:
        *   **Condition:** NPC logic determines it needs the item (could be always active or tied to another internal state).
        *   **Action:** `DialogueManager.start_dialogue(npc, player, dialogue_tree_id)`.
*   **Cooldown/Frequency:** Some proactive tags (like `RANDOM_CHATTER`) might have internal cooldowns or be limited in frequency to avoid spam. This could be managed by storing `last_used_timestamp` with the NPC state for that specific tag pattern.

### B. `CharacterActionProcessor` (Post Player Action Hook)

*   **Triggering Event:** After a player action is resolved (especially movement, entering a new location, interacting with PoIs, or actions that change player state recognized by NPCs like brandishing a forbidden item).
*   **Immediate Check:**
    1.  Identify NPCs in the immediate vicinity of the player or relevant to the action's context.
    2.  For these NPCs, evaluate their `behavior_tags` that are sensitive to immediate player presence or actions (e.g., `PROACTIVE_HOSTILITY:ON_SIGHT`, `PROACTIVE_HOSTILITY:TRESPASSING` if player entered a restricted area, `PROACTIVE_WARNING:AREA_RESTRICTED`).
    3.  The evaluation and action initiation logic is similar to the `WorldSimulationProcessor` but triggered more directly.

## 2. Processing NPC-Initiated Actions from `Location.event_triggers`

The logic for `Location.event_triggers` is primarily handled by `WorldSimulationProcessor` (for time-based, state-based, periodic triggers) and `CharacterActionProcessor` (for player-action-based triggers), as defined in `documentation/event_trigger_processing_logic.md`. The refinement here is ensuring the specific NPC-related actions within `actions_on_trigger` are correctly dispatched.

When an event trigger fires and its `actions_on_trigger` list is processed:

*   **`npc_initiate_dialogue`**:
    *   `{"type": "npc_initiate_dialogue", "target_npc_id_or_tag": "...", "dialogue_tree_id": "...", "triggering_player_is_target": true, "max_range_from_player": ...}`
    *   **Logic:**
        1.  Identify the `target_npc` based on `target_npc_id_or_tag`. If a tag is used, select one appropriate NPC (e.g., nearest, first available).
        2.  Identify the player target. If `triggering_player_is_target` is true and the event was triggered by a player, that player is the target. Otherwise, it might be the nearest player or a player meeting certain criteria within `execution_params`.
        3.  If `max_range_from_player` is specified, check distance. If too far, NPC might first need to move closer (see `npc_move_to_interact`).
        4.  Call `DialogueManager.start_dialogue(npc, player_target, dialogue_tree_id)`.

*   **`npc_change_behavior`**:
    *   `{"type": "npc_change_behavior", "target_npc_id_or_tag": "...", "add_tags": ["..."], "remove_tags": ["..."], "duration_seconds": ...}`
    *   **Logic:**
        1.  Identify `target_npc`(s).
        2.  Fetch NPC's current `behavior_tags` and/or `state_tags` (a similar field for temporary states might be useful).
        3.  Add tags from `add_tags`.
        4.  Remove tags from `remove_tags`.
        5.  Update the NPC's data via `NpcManager`.
        6.  If `duration_seconds` is present, schedule a temporary effect removal (e.g., via a `StatusManager` or by queuing a future action/event for this NPC).

*   **`npc_move_to_interact`**:
    *   `{"type": "npc_move_to_interact", "target_npc_id_or_tag": "...", "destination_poi_id": "...", "destination_player_target": true, "activity_on_arrival": "..."}`
    *   **Logic:**
        1.  Identify `target_npc`.
        2.  Determine destination:
            *   If `destination_poi_id` is set, get PoI coordinates from `LocationManager`.
            *   If `destination_player_target` is true, get the triggering player's current coordinates.
        3.  Call `NpcManager.initiate_move_to_location(npc, destination_coordinates, goal_activity_on_arrival=activity_on_arrival)`.

*   **`npc_set_hostility`**:
    *   `{"type": "npc_set_hostility", "target_npc_id_or_tag": "...", "hostile_to_player_character": true, "hostile_to_faction_id": "..."}`
    *   **Logic:**
        1.  Identify `target_npc`(s).
        2.  If `hostile_to_player_character` is true and event was triggered by a player, make NPC hostile to that player via `CombatManager` or by updating relationship status via `RelationshipManager` and then potentially initiating combat.
        3.  If `hostile_to_faction_id` is set, update NPC's relationship towards that faction. This might trigger combat if members of that faction are nearby.

## 3. Required Manager Modifications/Helpers

*   **`DialogueManager`**:
    *   `start_dialogue(npc, player, dialogue_tree_id, context_params=None)`: Initiates a dialogue.
*   **`CombatManager`**:
    *   `initiate_combat(attacker, target)`: Starts combat.
*   **`NpcManager`**:
    *   `get_npcs_by_tag(location_id, tag)`: To find NPCs for tag-based actions.
    *   `update_npc_tags(npc_id, tags_to_add, tags_to_remove)`: Modifies `NPC.behavior_tags` or a similar dynamic state field.
    *   `initiate_move_to_location` and `initiate_activity` (as defined for schedules) will be reused.
*   **`QuestManager`**:
    *   `is_player_eligible_for_quest(player_id, quest_id)`.
    *   `get_player_quest_step(player_id, quest_id)`.
*   **`RuleEngine`**:
    *   `check_conditions(condition_definition, character_context, world_context)`: A generic condition checker.
*   **`RelationshipManager`**:
    *   `get_faction_relationship(faction1_id, faction2_id)`.
    *   `set_character_npc_relationship_status(char_id, npc_id, status_key)` (e.g., "MET_FIRST_TIME").
*   **Player Proximity Service**: A utility to find players within a certain radius of an NPC or in the same defined sub-area of a location.

This outlines how `NPC.behavior_tags` and refined `Location.event_triggers` can drive more dynamic NPC actions and interactions within the game world.
