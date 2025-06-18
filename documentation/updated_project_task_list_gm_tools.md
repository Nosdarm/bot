# Project Task List Updates for Game Master Tool Enhancements

This document outlines the conceptual updates to the main project task list to incorporate "Game Master Tool Enhancements," specifically Simple Event Scripting via RuleConfig and "God Mode Lite" APIs.

## Phase A: Core Mechanics and Systems (Continued) / Phase B: Game Master & Admin Tools

*(These features bridge core systems and GM-specific tooling)*

### A.5 Game Master Tool Enhancements

#### A.5.1 Simple Event Scripting System (via RuleConfig)

*   **Task 0.2 (Data Models & Schema - `RuleConfig` Definition) & Task 0.3 (Manager Implementation Plan - `RuleConfigManager`):**
    *   **Existing:** Define `RuleConfig` structure and manager.
    *   **Modification to `RuleConfig` Definition (Task 0.2):**
        *   "Expand the definition of `RuleConfig` to include a new top-level key, e.g., `gm_event_scripts: List[Dict[str, Any]]`. Each dictionary in this list represents a GM-defined 'IF-THEN' event script."
        *   "Define the JSON structure for an individual GM event script. This structure must include:
            *   `script_id: str` (unique identifier).
            *   `description: str` (human-readable description of what the script does).
            *   `is_active: bool` (to enable/disable the script).
            *   `guild_id: str` (to scope the script, though `RuleConfig` is already guild-scoped, this can be for explicitness or future cross-guild templates).
            *   `conditions: List[Dict[str, Any]]` (a list of conditions that ALL must be met for the script to trigger. Each condition dict should be similar to those defined for `Location.event_triggers.trigger_condition`, e.g., `{"type": "on_player_enter_location", "location_id": "loc_x"}`, `{"type": "on_npc_death", "npc_template_id_or_tag": "goblin_chieftain"}`, `{"type": "on_item_pickup", "item_template_id": "key_to_city"}`, `{"type": "on_world_state_is", "flag_name": "war_declared", "value": true}`).
            *   `actions: List[Dict[str, Any]]` (a list of actions to execute if conditions are met. Each action dict should be similar to those defined for `Location.event_triggers.actions_on_trigger`, e.g., `{"type": "spawn_npc", ...}`, `{"type": "grant_item_to_player", ...}`, `{"type": "set_world_flag", ...}`, `{"type": "display_message_to_player", ...}`)."
        *   (A new document `documentation/gm_event_scripting.md` would be created to detail this JSON structure and processing logic, similar to how `Location.event_triggers` were handled).
    *   **New Sub-task under `RuleConfigManager` (Task 0.3):** "Implement utility functions within `RuleConfigManager` to efficiently fetch, cache, and update the `gm_event_scripts` list from the `RuleConfig` for a given guild."

*   **Task 47 (Master Commands - GM Commands for Game State & Rules) / UI.4 (Task 58 - UI for RuleConfig):**
    *   **Existing:** GM commands and UI for `RuleConfig`.
    *   **New Sub-task:** "Extend GM commands (and the corresponding UI in Task 58) to manage `gm_event_scripts` stored in `RuleConfig`. This includes functionalities for GMs to:
        *   Create new event scripts.
        *   View existing event scripts.
        *   Edit event scripts (modify conditions, actions, description, active status).
        *   Delete event scripts."

*   **New Task (or extend Task 15 Turn Processor / Task 46 WorldSimulationProcessor): "Implement GM Event Script Evaluation Service"**
    *   **Description:** "Develop a service or enhance existing processors (`CharacterActionProcessor`, `WorldSimulationProcessor`, relevant managers) to evaluate and execute GM-defined event scripts from `RuleConfig.gm_event_scripts`.
        1.  **Condition Evaluation Hooks:** Integrate checks at various points in the game loop:
            *   After player actions are processed (in `CharacterActionProcessor`): Check scripts triggered by `on_player_action`, `on_item_pickup`, `on_player_enter_location`, etc.
            *   During NPC state changes (e.g., death, hostility change - hooks in `NpcManager` or `CombatManager`): Check scripts triggered by `on_npc_death`, `on_npc_hostility_change`.
            *   Periodically for time-based or persistent world-state conditions (in `WorldSimulationProcessor`): Check scripts triggered by `on_world_state_is`, `on_game_time_is`.
        2.  **Script Execution:** If all conditions for an active script are met:
            *   Execute its defined `actions` list by calling the relevant service managers (e.g., `NpcManager.spawn_npc_in_location`, `InventoryManager.add_item_to_character`, `WorldStateManager.set_custom_flag`, `NotificationService.send_message_to_player`).
            *   Log the execution of the GM script and its actions via `GameLogManager`.
            *   Consider script cooldowns or one-time execution if such properties are added to the script definition."
    *   **(Reference: A new `documentation/gm_event_scripting.md` would be created to detail the script structure and this processing logic more thoroughly.)**

#### A.5.2 "God Mode Lite" APIs (Integration based on Subtask "Outline and document 'God Mode Lite' APIs")

*   **Task 47 (Master Commands - GM Commands for Game State & Rules):**
    *   **Existing:** Basic GM commands.
    *   **Major Expansion/Revision:**
        *   "Design and implement a comprehensive suite of backend HTTP APIs providing 'God Mode Lite' functionalities for Game Masters. These APIs are intended for use with a future GM dashboard/UI and will allow direct, authenticated, and authorized manipulation of game state for a specific guild."
        *   **API Categories (as documented in `documentation/gm_god_mode_apis.md`):**
            *   **Character Manipulation APIs:** Endpoints for setting/adjusting stats (HP, attributes, XP, level, gold), adding/removing items from inventory, equipping/unequipping items, applying/removing status effects, teleporting characters, managing skills/abilities/spells, and modifying quest states (grant, complete step, remove).
            *   **NPC Manipulation APIs:** Endpoints for setting NPC stats, managing inventory, status effects, teleportation, changing behavior (e.g., `behavior_tags`, hostility), and spawning/despawning NPCs.
            *   **Location Manipulation APIs:** Endpoints for modifying `Location.state_variables`, locking/unlocking PoIs (doors, chests), activating/deactivating traps in PoIs, adding/removing items from location or PoI container inventories, and spawning items/NPCs at specific coordinates within a location.
            *   **World State Manipulation APIs:** Endpoints for setting/unsetting global world flags (`WorldState.custom_flags`).
            *   **Event Manipulation APIs:** Endpoints for manually triggering event templates at a location or for specific players, and for advancing/ending active event instances.
            *   **RuleConfig Management APIs:** (Already covered but ensure they fit the HTTP API paradigm if not already) Endpoints for viewing and editing `RuleConfig` values.
        *   **Core Requirements for all GM APIs:**
            *   All endpoints must be authenticated and authorized to ensure only users with GM role for the specified `guild_id` can use them.
            *   All operations must be strictly guild-scoped.
            *   All actions performed via these APIs must be logged in detail to `GameLogManager` (e.g., recording GM ID, action performed, parameters, target entities, timestamp).
        *   (Reference: `documentation/gm_god_mode_apis.md` for detailed endpoint definitions, request/response payloads, and backend logic outlines)."

*   **UI Tasks (Tasks 55-66 - Master Game UI - Vue.js SPA):**
    *   **Task 55 (UI.1 Base Structure):** "Ensure base UI structure can accommodate a dedicated section or views for GM administration tools."
    *   **Task 57 (UI.3 Character Info):** "Add GM functionalities to this UI view to allow GMs to view detailed character sheets and use 'God Mode Lite' Character Manipulation APIs to modify character stats, inventory, quests, etc."
    *   **Task (Relevant UI tasks for NPCs, e.g., if part of UI.9 Global Entities):** "Add GM functionalities to NPC views to allow GMs to use 'God Mode Lite' NPC Manipulation APIs."
    *   **Task (Relevant UI tasks for Locations, e.g., if part of UI.9 Global Entities):** "Add GM functionalities to Location views to allow GMs to use 'God Mode Lite' Location Manipulation APIs (e.g., editing PoI states, location variables)."
    *   **Task 58 (UI.4 RuleConfig):** "Expand this UI to support viewing and editing `RuleConfig` values, including the new `gm_event_scripts` list. Provide a user-friendly interface for GMs to create, modify, and manage these simple event scripts."
    *   **Task 64 (UI.10 Monitoring & GM Dashboard):** "This task could be expanded or serve as the basis for a comprehensive GM Dashboard that consolidates access to various 'God Mode Lite' API functionalities and provides an overview of game state relevant to GM administration."
    *   **New Conceptual UI Task: "UI.X: Dedicated GM 'God Mode' Dashboard/Interface"**
        *   **Description:** "Design and implement a dedicated dashboard or a set of integrated views within the Master Game UI specifically for Game Master administrative actions. This interface will provide user-friendly access to the various 'God Mode Lite' API functionalities, allowing GMs to easily search for, view, and modify characters, NPCs, locations, world state, events, and manage GM event scripts and RuleConfig settings."

## General
*   Ensure all new GM tool enhancement features are covered by appropriate unit and integration tests, especially the API endpoints and event script processing logic.
*   Update GM-specific documentation and guides.

This integration plan aims to seamlessly weave the Game Master Tool Enhancements into the existing project tasks and UI development plans.
