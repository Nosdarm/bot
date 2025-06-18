# AI Pipeline Integration Plan for Dynamic Events & NPC Schedules

This document outlines the planned modifications to the AI context gathering, prompt generation, and response validation systems to support AI-assisted generation of `Location.event_triggers` and `NPC.schedule_json`.

## 1. `bot/ai/prompt_context_collector.py` Modifications

The `GenerationContext` needs to be appropriately set up to enable the AI to suggest plausible event triggers and NPC schedules.

*   **World State/Location Context for Event Triggers:**
    *   **`GenerationContext.primary_location_details`**: When generating a new location or suggesting additions to an existing one, this context should be rich enough for the AI to infer thematic event triggers. This includes location type, description, existing PoIs, and overall atmosphere.
    *   **`GenerationContext.game_terms_dictionary` or `GenerationContext.available_event_templates`**:
        *   Include a list or dictionary of available `event_template_id`s (and perhaps a brief description of what they do, e.g., `{"id": "ghostly_apparition_event", "description": "A harmless ghost appears and delivers a cryptic message."}`). This allows the AI to suggest valid and contextually appropriate event templates.
        *   Example:
            ```json
            "available_event_templates": [
              {"id": "spawn_common_monster_event", "description": "Spawns a common monster."},
              {"id": "discover_hidden_cache_event", "description": "Player finds a small hidden item cache."}
            ]
            ```
    *   **Signal for Suggesting Triggers**: The prompt itself (see next section) will primarily signal the desire for `event_triggers`. The context should support the AI in making good suggestions.

*   **NPC Context for Schedules:**
    *   **`GenerationContext.primary_location_details` (if NPC is contextually tied to a location being generated/viewed):** The type of location (e.g., "market," "tavern," "barracks," "wilderness_path") and its PoIs (e.g., "shop_counter," "forge," "guard_tower") can heavily influence an NPC's schedule.
    *   **`GenerationContext.npc_profile_being_generated` (or similar for existing NPCs):**
        *   The NPC's `role_i18n`, `archetype_i18n`, `faction_id`, and `personality_traits_i18n` are crucial for suggesting a believable schedule.
    *   **`GenerationContext.world_details.time_conventions` (Conceptual):**
        *   Provide general information about the world's day/night cycle (e.g., "Sunrise around 06:00, sunset around 18:00", "Shops typically open 08:00-18:00"). This helps the AI make logical time-based schedule entries.
    *   **`GenerationContext.rule_config_summary.npc_activities` (Conceptual):**
        *   If `RuleConfig` defines standard activity keys (e.g., "patrolling", "working_shop", "sleeping") or default schedules for certain NPC roles, a summary could be provided.
        *   Example:
            ```json
            "npc_activity_rules": {
              "shop_hours": {"open": "08:00", "close": "18:00"},
              "guard_patrol_duration_hours": 4
            }
            ```

## 2. `bot/ai/multilingual_prompt_generator.py` Modifications

Prompts will be updated to explicitly request suggestions for event triggers and NPC schedules.

*   **Location Generation (`generate_location_description_prompt`):**
    *   **Add instructions for suggesting `event_triggers`:**
        > "Based on the location's characteristics (theme, type, Points of Interest, potential dangers or secrets), please suggest 1 to 3 plausible `event_triggers` in a field named `suggested_event_triggers_json`. Each trigger in this list should be a JSON object with the following key fields:
        >   - `trigger_id`: A brief, descriptive ID (e.g., "ghostly_sighting_at_ruins", "bandit_ambush_on_road").
        >   - `trigger_condition`: A JSON object defining when it fires. Examples:
        >     - `{\"type\": \"on_player_action\", \"action_type\": \"inspect_poi\", \"target_poi_id\": \"<id_of_a_poi_in_this_location>\"}`
        >     - `{\"type\": \"on_time_of_day\", \"specific_time\": \"23:00\"}`
        >     - `{\"type\": \"random_chance_periodic\", \"chance_percent\": 5, \"check_interval_seconds\": 1800}` (checks every 30 real-time minutes)
        >   - `event_template_id`: (Preferred) The ID of an existing event template to run (see `available_event_templates` in context).
        >   - `actions_on_trigger`: (Alternative, for simple effects) A list of simple actions, e.g., `[{\"type\": \"display_message_i18n\", \"message_key\": \"creepy_sound_echos\"}]` or `[{\"type\": \"spawn_npc\", \"npc_template_id\": \"minor_spirit\", \"quantity\": \"1\"}]`.
        >   - `one_time_only`: `true` or `false`.
        >   - `cooldown_seconds`: (Optional) e.g., `3600`.
        > Make these triggers thematically appropriate and engaging for the location."
    *   The output field in the location's JSON would be `suggested_event_triggers_json: [...]`.

*   **NPC Generation (`generate_npc_profile_prompt`):**
    *   **Add instructions for suggesting `schedule_json`:**
        > "Based on this NPC's role, archetype, personality, and typical location (if known), suggest a basic daily routine in a field named `schedule_json`. This JSON object should include:
        >   - `default_activity`: A fallback activity key (e.g., \"wandering_market\", \"guarding_post\", \"idle_at_home\").
        >   - `default_location_id`: The `location_id` for their default activity (use a placeholder like `\"<npc_home_location_id>\"` or `\"<npc_work_location_id>\"` if specific IDs are not yet known).
        >   - `daily_schedule`: A list of 2-5 entries, each a JSON object: `{\"time\": \"HH:MM\", \"location_id\": \"<relevant_location_id_or_placeholder>\", \"activity_key\": \"<e.g., work_at_forge, patrol_route_A, lunch_at_tavern, sleep_in_quarters>\", \"duration_minutes\": <optional_num>}`.
        > Ensure the schedule is logical for the NPC type. For example, a blacksmith might be at their forge during working hours, a guard on patrol, and a scholar in the library."
    *   The output field in the NPC's JSON would be `schedule_json: {...}`.

## 3. `bot/ai/ai_response_validator.py` & `bot/ai/ai_data_models.py` Modifications

Pydantic models in `ai_data_models.py` will be updated to validate these new AI-suggested structures.

*   **Location Content (`GeneratedLocationContent` Pydantic model):**
    *   Add new field: `suggested_event_triggers_json: Optional[List[Dict[str, Any]]] = Field(None, description="AI-suggested event triggers for the location.")`
    *   **Stricter Typing (Future Enhancement):**
        *   Define `EventTriggerCondition(BaseModel)` with various sub-models for different types using discriminated unions if feasible.
        *   Define `EventAction(BaseModel)` similarly.
        *   Define `SuggestedEventTrigger(BaseModel)` with `trigger_id: str`, `trigger_condition: EventTriggerCondition`, `event_template_id: Optional[str]`, `actions_on_trigger: Optional[List[EventAction]]`, `one_time_only: bool`, `cooldown_seconds: Optional[int]`.
        *   Then change `suggested_event_triggers_json` to `Optional[List[SuggestedEventTrigger]]`.
    *   For MVP, `List[Dict[str, Any]]` is acceptable, relying on prompt structure and basic validation in `AIResponseValidator`.

*   **NPC Profile (`GeneratedNpcProfile` Pydantic model):**
    *   Add new field: `schedule_json: Optional[Dict[str, Any]] = Field(None, description="AI-suggested NPC schedule.")`
    *   **Stricter Typing (Future Enhancement):**
        *   Define `ScheduleEntry(BaseModel)` with `time: str`, `location_id: str`, `activity_key: str`, `duration_minutes: Optional[int]`.
        *   Define `SpecialEventOverrideEntry(ScheduleEntry)` adding `condition_world_flag: str`, `expected_value: Optional[Any]`, `priority: Optional[int]`.
        *   Define `NPCSchedule(BaseModel)` with `default_activity: Optional[str]`, `default_location_id: Optional[str]`, `daily_schedule: Optional[List[ScheduleEntry]]`, `weekly_schedule: Optional[Dict[str, List[ScheduleEntry]]]`, `special_event_overrides: Optional[List[SpecialEventOverrideEntry]]`.
        *   Then change `schedule_json` to `Optional[NPCSchedule]`.
    *   For MVP, `Dict[str, Any]` is acceptable for `schedule_json`.

*   **`AIResponseValidator`:**
    *   Update to check for the presence and basic structure of `suggested_event_triggers_json` and `schedule_json` if they are included in the AI response.
    *   For `suggested_event_triggers_json` (if `List[Dict[str, Any]]`):
        *   Iterate through the list. For each dict, check for essential keys like `trigger_id`, `trigger_condition`, and either `event_template_id` or `actions_on_trigger`.
    *   For `schedule_json` (if `Dict[str, Any]`):
        *   Check for presence of some expected top-level keys like `daily_schedule` or `default_activity`.
        *   If `daily_schedule` exists, check that it's a list and its elements are dictionaries with `time`, `location_id`, `activity_key`.

## 4. Summary of Files and Key Changes

*   **`bot/ai/prompt_context_collector.py`:**
    *   Enhance `GenerationContext` to include:
        *   List of available `event_template_id`s for suggesting event triggers.
        *   Location characteristics, NPC roles/archetypes, and world time conventions/rules to inform schedule generation.
*   **`bot/ai/multilingual_prompt_generator.py`:**
    *   Update `generate_location_description_prompt` to request `suggested_event_triggers_json` with a defined structure.
    *   Update `generate_npc_profile_prompt` to request `schedule_json` with a defined structure, appropriate to the NPC's role.
*   **`bot/ai/ai_data_models.py`:**
    *   Add `suggested_event_triggers_json: Optional[List[Dict[str, Any]]]` to `GeneratedLocationContent`.
    *   Add `schedule_json: Optional[Dict[str, Any]]]` to `GeneratedNpcProfile`.
    *   (Future: Implement more specific Pydantic models for these structures like `SuggestedEventTrigger` and `NPCSchedule` for stricter validation).
*   **`bot/ai/ai_response_validator.py`:**
    *   Add validation logic for the basic structure and presence of key fields within `suggested_event_triggers_json` and `schedule_json` when they appear in AI responses.

This plan focuses on enabling the AI to contribute to the dynamic aspects of the game world by suggesting event triggers and NPC schedules.
