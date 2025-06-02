# Action and Conflict Resolution System

This document outlines how player actions are submitted, processed, and how conflicts arising from these actions are resolved within the game.

## Player Action Submission

Players interact with the game world by submitting actions for their characters or parties.

### Command for Action Submission

-   **Command**: `/party_submit_actions_placeholder` (Note: This is a placeholder command name and might be replaced by a more user-friendly command like `/actions` or integrated into a UI).
-   **Usage**: `{prefix}party_submit_actions_placeholder <party_id> <char1_id> '<actions_json1>' [<char2_id> '<actions_json2>'...]`
    -   `party_id`: The ID of the party performing the actions.
    -   `charX_id`: The ID of the character performing an action.
    -   `actions_jsonX`: A JSON string representing the list of actions for that character.

### Action Format

Actions are submitted as a JSON string, which is a list of action objects. Each action object typically includes:

-   `intent`: The primary type of action (e.g., "move", "interact", "use_skill", "attack").
-   `entities`: A dictionary of relevant entities or parameters for the action.
    -   For `"move"`: `{"target_space": "A2"}` or `{"destination": "location_id_or_name"}`
    -   For `"interact"`: `{"target_id": "npc_or_object_id"}`
    -   For `"use_skill"`: `{"skill_name": "stealth", "target_id": "optional_target_id"}`
-   `original_text` (optional): The raw text command from the player, for context or logging.

**Example JSON for a single character:**

```json
[
    {"intent": "move", "entities": {"target_space": "A2"}, "original_text": "move to A2"},
    {"intent": "look", "entities": {}, "original_text": "look around"}
]
```

### Temporary Storage of Actions

When a player submits actions via the command:

1.  The raw JSON string of actions for each character is temporarily stored on their respective `Character` object in the `collected_actions_json` attribute.
2.  This data is persisted to the database before the main action processing begins. This ensures that if a conflict requires manual intervention by a Master, the originally intended actions are available for review.

## Conflict Resolution Process

### Overview

Once actions are submitted for a party or a set of characters, the system (specifically the `ActionProcessor` and `ConflictResolver`) analyzes these actions to identify potential conflicts. A conflict occurs when two or more actions are incompatible or compete for the same resource or outcome.

### Automatic Resolution

-   Many common conflicts can be resolved automatically by the system.
-   The `ConflictResolver` uses rules defined in the game's configuration (`rules_config`) and relies on the `RuleEngine` to perform checks (e.g., opposed skill checks, stat comparisons).
-   **Example**: If two characters attempt to move into the same limited-capacity space simultaneously, an opposed Agility check (handled by `RuleEngine.resolve_check`) might determine who gets the space. The `ConflictResolver` would then apply the outcome (e.g., one character moves, the other's action fails or is modified).

### Manual Resolution

-   Complex, ambiguous, or highly consequential conflicts are flagged for manual resolution by a Game Master (Master).
-   The `ConflictResolver` identifies these based on the `rules_config`.
-   When a conflict is marked for manual resolution:
    -   The `collected_actions_json` for the involved characters becomes crucial, as it provides the Master with the context of what each character was attempting to do.
    -   The conflict details are stored (currently in memory in `ConflictResolver.pending_manual_resolutions`, with potential for future database persistence).

## Master Notification and Resolution

### Notification

-   When a conflict requires manual intervention, the Master is notified.
-   This notification is handled by the `NotificationService`. It typically involves sending a message to a designated Master channel on Discord.
-   The notification includes the `conflict_id`, the type of conflict, involved players, and a summary of the conflicting actions (derived from `collected_actions_json` and conflict analysis).

### Master Resolution Command

-   **Command**: `/resolve_conflict` (or a similar GM-restricted command).
-   **Usage**: `/resolve_conflict <conflict_id> <outcome_type> [params_json]`
    -   `conflict_id`: The unique ID of the conflict that was sent in the notification.
    -   `outcome_type`: A string defining how the Master has decided to resolve the conflict. Examples:
        -   `actor_wins`: The primary instigator of one side of the conflict succeeds.
        -   `target_wins`: The other party involved succeeds.
        -   `both_succeed_modified`: Both actions succeed but with modifications.
        -   `both_fail`: Both actions fail.
        -   `custom_outcome`: A more complex, narrative resolution.
    -   `params_json` (optional): A JSON string providing additional parameters for the chosen `outcome_type`.
        -   For `"custom_outcome"`: `{"description": "The ground splits, and both are momentarily stunned.", "effects": ["apply_stun_player1_1_round", "apply_stun_player2_1_round"]}`
        -   For determining a winner: `{"winner_player_id": "player123", "reason": "Player1 had a more compelling argument."}`

## Conflict Data Structure

When a conflict is pending manual resolution, it's stored (currently in-memory by `ConflictResolver`) with the following key information:

-   `conflict_id` (str): A unique identifier for the conflict (e.g., a UUID).
-   `type` (str): The type of conflict as defined in `rules_config` (e.g., "contested_resource_grab", "simultaneous_critical_action").
-   `involved_players` (List[str]): A list of character IDs involved in the conflict.
-   `details` (Dict[str, Any]): Specifics of the conflict, often including:
    -   The raw actions that caused it (from `collected_actions_json`).
    -   The resource, space, or target in contention.
-   `status` (str): The current status of the conflict (e.g., "identified", "awaiting_manual_resolution", "resolved_automatically", "resolved_manually").
-   `master_notification_message` (str): The formatted message sent to the Master, summarizing the conflict.
-   `outcome` (Optional[Dict[str, Any]]): Populated after resolution, detailing the winner (if any), effects, and description of the outcome.

## Post-Resolution

After any action (whether it involved a conflict or not) is fully processed:
1. The `collected_actions_json` on the character objects is cleared (set to `None`).
2. This change is persisted to the database.

This ensures that old action data is not accidentally reused or misinterpreted in future turns.
