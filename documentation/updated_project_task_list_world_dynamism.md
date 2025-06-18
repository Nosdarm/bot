# Project Task List Updates for World Dynamism Integration

This document outlines the conceptual updates to the main project task list to incorporate the implementation of "Enhance World Dynamism" features, specifically Dynamic Localized Events and NPC Schedules.

## Phase A: Core Mechanics and Systems (Continued)

### A.3 Enhance World Dynamism

#### A.3.1 Dynamic Localized Events (Integration based on Subtask "Define Location.event_triggers and outline processing logic")

*   **Task 4 (Location Model) / Task 23 (Location Model Refined - Game World & Locations):**
    *   **Existing:** Define `Location` model, including `points_of_interest_json`. (Assume `event_triggers` field is new or needs formal definition here).
    *   **Modification/Addition:**
        *   "Add or formalize `Location.event_triggers` as a `Column(JSONB, nullable=True)`. This field will store a list of event trigger objects."
        *   **New Sub-point:** "Define and document the detailed JSON structure for objects within `Location.event_triggers`. Each object must include `trigger_id` (unique within location), `trigger_condition` (a dictionary with a `type` field like `on_player_action`, `on_world_state_change`, `on_time_of_day`, `random_chance_periodic`, `on_npc_state_change`, `on_item_used_in_location`, etc., and associated parameters), either an `event_template_id` (string, FK to EventManager templates) or a list of `actions_on_trigger` (simple direct actions like spawn NPC, display message, change location state, grant item, update PoI state), `one_time_only` (boolean, defaults to false), `cooldown_seconds` (optional integer), `execution_params` (optional dict), `is_active` (boolean, defaults to true), and `last_triggered_timestamp` (optional float). (Reference: `documentation/json_structures.md` for the comprehensive structure and examples)."

*   **Task 46 (Global Entities & Dynamic World / `WorldSimulationProcessor`):**
    *   **Existing:** Implement `WorldSimulationProcessor` for global dynamic world aspects.
    *   **Expansion/New Sub-tasks for Event Trigger Processing:**
        *   "**Periodic Event Trigger Evaluation:** Implement logic in `WorldSimulationProcessor` (or a new dedicated `LocationEventTriggerService`) to periodically iterate through active locations and their `event_triggers`. This evaluation should be based on current game time (from `TimeManager`), world state flags (from `WorldStateManager` or `GameManager`), NPC states (from `NpcManager`), and random chance for `random_chance_periodic` triggers. Manage `check_interval_seconds` for periodic triggers."
        *   "**Trigger Execution:** If a trigger's conditions are met, it's active, and not on cooldown:
            *   If an `event_template_id` is specified, invoke `EventManager.create_event_from_template(event_template_id, location_id, guild_id, execution_params, triggering_character_id_if_any)`.
            *   If `actions_on_trigger` are specified, execute these simple actions directly (e.g., call `NpcManager.spawn_npc_in_location`, send messages via a messaging service, update `Location.state_variables` via `LocationManager.update_location_state_variable`, grant items via `InventoryManager.add_item_to_character`, update PoI states via `LocationManager.update_poi_state`)."
        *   "**Trigger State Management:** After execution, update the trigger's `last_triggered_timestamp`. If `one_time_only` is true, set its `is_active` flag to false. These changes to `Location.event_triggers` must be persisted via `LocationManager` (e.g., using `location_manager.update_event_trigger_state(location_id, trigger_id, new_trigger_data)`)."
        *   (Reference: `documentation/event_trigger_processing_logic.md` for detailed processing logic).

*   **Task 15 (Turn Processor / `CharacterActionProcessor`):**
    *   **Existing:** Implement `CharacterActionProcessor` to handle player actions.
    *   **New Sub-task for Reactive Event Triggers:** "After successfully processing a player's action, the `CharacterActionProcessor` (or a hook called by it) must check the current `Location.event_triggers`. If any trigger has an `trigger_condition` of type `on_player_action` (matching the completed action type, target PoI, required item, skill level etc.), `on_item_used_in_location` (matching item used), or `on_player_enter_area` (if action resulted in area change), and its conditions are met, the trigger should be executed as per the 'Trigger Execution' logic defined under Task 46."

#### A.3.2 NPC Schedules/Routines (Integration based on Subtask "Define NPC.schedule_json and outline processing logic")

*   **Task 7 (DB Schemas - Character, Party, NPC, Item, Location, Quest, Event, Dialogue, Faction, WorldState, GlobalNPC, GameLogEntry):**
    *   **Existing:** Define database schema for `NPC` model.
    *   **Modification for `NPC` model:**
        *   "Add a new field `schedule_json: Column(JSONB, nullable=True)` to the `NPC` class in `bot/database/models.py`."
        *   **New Sub-point:** "Define and document the detailed JSON structure for `NPC.schedule_json`. This structure should support `default_activity` (string), `default_location_id` (string), `daily_schedule` (list of objects with `time`, `location_id`, `activity_key`, `duration_minutes`), `weekly_schedule` (dictionary mapping day names to daily schedules), and `special_event_overrides` (list of objects with `condition_world_flag`, `location_id`, `activity_key`, `priority`). (Reference: `documentation/json_structures.md` for the comprehensive structure and examples)."
        *   **New Sub-point:** "A new database migration (Alembic) will be required for this schema change."

*   **Task 46 (Global Entities & Dynamic World / `WorldSimulationProcessor`):**
    *   **Existing:** Implement `WorldSimulationProcessor`.
    *   **New Sub-tasks for NPC Schedule Processing:**
        *   "**NPC Schedule Iteration:** In the per-guild tick of `WorldSimulationProcessor`, after `TimeManager.update_guild_time(guild_id)` (or equivalent) has been called, retrieve all NPCs for the guild that have a defined `schedule_json` (e.g., via `NpcManager.get_npcs_with_schedules(guild_id)`)."
        *   "**Current Activity Determination:** For each such NPC, implement logic to determine its current scheduled activity. This involves:
            1.  Fetching the current game time details (day of week, hour, minute) for the guild from `TimeManager`.
            2.  Checking `special_event_overrides` against current world state flags (via `WorldStateManager` or `GameManager.get_rule`).
            3.  If no override applies, checking `weekly_schedule` for the current day of the week.
            4.  If no weekly entry matches, checking `daily_schedule`.
            5.  If no specific entry matches, falling back to `default_activity` and `default_location_id`."
        *   "**NPC Action Initiation (Location Change):** If the determined scheduled entry requires the NPC to be in a different `location_id` than its current `NPC.location_id`, and the NPC is not currently engaged in a critical uninterruptible action (e.g., combat, checked via `CombatManager`), call a new method like `NpcManager.initiate_move_to_location(guild_id, npc_id, target_location_id, goal_activity_key_on_arrival)`."
        *   "**NPC Action Initiation (Activity Change):** If the NPC is already in the correct location (or the schedule entry doesn't specify a location change), but the determined `activity_key` is different from its current activity (e.g., derived from `NPC.current_action_json` or a new `NPC.current_activity_key` field), call a new method like `NpcManager.initiate_activity(guild_id, npc_id, activity_key, schedule_entry_data)`."
        *   (Reference: `documentation/npc_schedule_processing_logic.md` for detailed processing logic).

*   **Task (New or existing `NpcManager` / `NpcActionProcessor` task, e.g., Task 26 - NPC Behavior & Actions):**
    *   **Existing:** Implement NPC behavior and action processing.
    *   **New Sub-task for Schedule-Driven Actions:** "Implement `NpcManager.initiate_move_to_location(guild_id: str, npc_id: str, target_location_id: str, goal_activity_on_arrival: Optional[str] = None)`. This method should queue a movement action for the NPC, to be handled by `NpcActionProcessor`."
    *   **New Sub-task for Schedule-Driven Activities:** "Implement `NpcManager.initiate_activity(guild_id: str, npc_id: str, activity_key: str, schedule_entry_data: Dict)`. This method should make the NPC start the specified activity, potentially by setting `NPC.current_action_json` to an appropriate action structure that `NpcActionProcessor` can interpret (e.g., `{\"type\": \"perform_activity\", \"key\": \"work_at_forge\", ...}`)."
    *   **Dependency Note:** "Ensure `TimeManager` provides methods to easily get current game day_of_week (string/enum), hour (0-23), and minute (0-59) for a given guild, which is essential for schedule processing."


#### A.3.3 AI Context & Generation for World Dynamism (Integration based on Subtask "Plan AI updates for dynamic events and NPC schedules")

*   **Task 8 (AI Prompt Preparation - `PromptContextCollector`, `MultilingualPromptGenerator`):**
    *   **Existing:** Prepare context and generate prompts for AI.
    *   **Modifications for `PromptContextCollector`:**
        *   "Update `PromptContextCollector` to include a list of available `event_template_id`s (with brief descriptions) in `GenerationContext` to aid AI in suggesting valid event triggers for locations."
        *   "Update `PromptContextCollector` to provide relevant contextual information for NPC schedule generation, such as the NPC's role/archetype, typical location type/PoIs, general world time conventions (e.g., shop hours), and potentially relevant `RuleConfig` for NPC activities."
    *   **Modifications for `MultilingualPromptGenerator`:**
        *   "Modify `generate_location_description_prompt` to add instructions for the AI to suggest a list of `event_triggers` (in a `suggested_event_triggers_json` field). The prompt should guide the AI on the structure of these triggers (condition, event/action, one-time, cooldown) and emphasize thematic appropriateness."
        *   "Modify `generate_npc_profile_prompt` to add instructions for the AI to suggest an `NPC.schedule_json` (including default activity, daily schedule with time/location/activity entries). The prompt should guide the AI to make the schedule consistent with the NPC's role and environment."
        *   (Reference: `documentation/ai_event_schedule_integration.md` for prompt details and JSON examples)."

*   **Task 9 (AI Response Parsing & Validation - `AIResponseValidator`, Pydantic models in `ai_data_models.py`):**
    *   **Existing:** Parse and validate AI responses.
    *   **Modifications for `ai_data_models.py`:**
        *   "Update `GeneratedLocationContent` Pydantic model to include `suggested_event_triggers_json: Optional[List[Dict[str, Any]]]` (with a note for future stricter typing using a dedicated `SuggestedEventTrigger` model)."
        *   "Update `GeneratedNpcProfile` Pydantic model to include `schedule_json: Optional[Dict[str, Any]]]` (with a note for future stricter typing using a dedicated `NPCSchedule` model)."
    *   **Modifications for `AIResponseValidator`:**
        *   "Update `AIResponseValidator` to perform basic validation on the structure and essential keys of `suggested_event_triggers_json` and `schedule_json` if they are present in AI responses."
        *   (Reference: `documentation/ai_event_schedule_integration.md`)."

## General
*   Ensure all new world dynamism features (event triggers, NPC schedules) are covered by appropriate unit and integration tests.
*   Update game documentation and tutorials to reflect these new dynamic aspects of the game world.

This integration plan aims to seamlessly weave the world dynamism features into the existing project tasks.
