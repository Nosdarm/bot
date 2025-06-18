# Project Task List Updates for AI & NLU Refinements Integration

This document outlines the conceptual updates to the main project task list to incorporate the "Refine AI & NLU Capabilities" features: Proactive NPC Behavior, NLU Ambiguity Handling, and a placeholder for GM AI Assistance.

## Phase A: Core Mechanics and Systems (Continued)

### A.4 Refine AI & NLU Capabilities

#### A.4.1 Proactive NPC Behavior (Integration based on Subtask "Document NPC.behavior_tags and related logic")

*   **Task 7 (DB Schemas - Character, Party, NPC, Item, Location, Quest, Event, Dialogue, Faction, WorldState, GlobalNPC, GameLogEntry):**
    *   **Existing:** Define database schema for `NPC` model. (Assume `behavior_tags: Column(JSONB, nullable=True)` is added or formalized here).
    *   **Modification/Addition for `NPC` model:**
        *   "Formalize `NPC.behavior_tags` as `Column(JSONB, nullable=True)`, storing a list of strings."
        *   **New Sub-point:** "Define and document patterns for strings within `NPC.behavior_tags` that can trigger proactive NPC actions. Examples include `PROACTIVE_DIALOGUE:QUEST_AVAILABLE:<quest_id>`, `PROACTIVE_HOSTILITY:FACTION_HATE:<faction_id>`, `PROACTIVE_WARNING:AREA_RESTRICTED:<area_id>`. These tags are parsed to determine conditions and actions. (Reference: `documentation/json_structures.md` for detailed patterns and examples)."

*   **Task 4 (Location Model) / Task 23 (Location Model Refined - Game World & Locations):**
    *   **Existing:** Define `Location.event_triggers` structure.
    *   **Modification for `Location.event_triggers.actions_on_trigger`:**
        *   "Ensure the `actions_on_trigger` list within `Location.event_triggers` can include new action types specifically for NPC initiation as a result of a location event. These include:
            *   `npc_initiate_dialogue` (specifying target NPC, dialogue tree, and player target).
            *   `npc_change_behavior` (adding/removing behavior/state tags from an NPC, possibly with duration).
            *   `npc_move_to_interact` (NPC moves to a PoI or player, then performs an activity).
            *   `npc_set_hostility` (makes specified NPC hostile).
            *   (Reference: `documentation/json_structures.md` for detailed action structures)."

*   **Task 46 (Global Entities & Dynamic World / `WorldSimulationProcessor`):**
    *   **Existing:** Implement `WorldSimulationProcessor` for dynamic world aspects and NPC schedules.
    *   **New Sub-task for Proactive NPC Behavior (Tick-Based):** "In the NPC processing portion of the `WorldSimulationProcessor`'s tick (when an NPC is idle or performing low-priority scheduled activities):
        1.  Check for nearby players.
        2.  For each nearby player, iterate through the NPC's `behavior_tags`.
        3.  Parse and evaluate the condition associated with each tag pattern (e.g., player quest eligibility via `QuestManager`, faction status via `RelationshipManager`, inventory contents via `InventoryManager`, game conditions via `RuleEngine`).
        4.  If a tag's condition is met and the NPC is not otherwise engaged in a critical action (e.g., combat), initiate the corresponding proactive behavior (e.g., call `DialogueManager.start_dialogue`, `CombatManager.initiate_combat`, send a warning message, or trigger a custom interaction).
        *   (Reference: `documentation/proactive_npc_behavior_logic.md` for detailed processing logic)."

*   **Task 15 (Turn Processor / `CharacterActionProcessor`):**
    *   **Existing:** Implement `CharacterActionProcessor` to handle player actions.
    *   **New Sub-task for Proactive NPC Behavior (Reactive):** "After processing a player's action (especially movement, area entry, or interactions that change player state visible to NPCs):
        1.  Identify NPCs in the vicinity whose `behavior_tags` might be triggered by the player's new state or presence (e.g., `PROACTIVE_HOSTILITY:ON_SIGHT`, `PROACTIVE_WARNING:AREA_RESTRICTED` if player just entered).
        2.  Evaluate and execute these reactive behaviors similarly to the tick-based checks in `WorldSimulationProcessor` but with more immediate context."

*   **Task 10 (AI-generation, Moderation, Saving - specifically for AI NPC Generation, tied to Task 8 - AI Prompt Prep):**
    *   **Existing:** AI generates NPC profiles.
    *   **Modification for `MultilingualPromptGenerator` (Task 8):** "Modify NPC generation prompts to instruct the AI to suggest a list of relevant `behavior_tags` for the NPC, consistent with its role, personality, faction, and known environment. For example, a guard NPC might get `[\"ROLE:GUARD\", \"PROACTIVE_WARNING:AREA_RESTRICTED:treasury\"]`."

#### A.4.2 NLU for Ambiguity (Integration based on Subtask "Document planned changes for handling ambiguous NLU results")

*   **Task 13 (NLU & Intent/Entity Recognition - `PlayerActionParser`):**
    *   **Existing:** Define NLU intents and entities; `PlayerActionParser` resolves input to action.
    *   **Major Revision:**
        *   "Modify `PlayerActionParser` to output `action_data['possible_intents']` instead of a single `action_data['intent']`.
        *   `possible_intents` will be a list of dictionaries, each containing:
            *   `"intent"` (string, e.g., "action_attack_target_instrument")
            *   `"confidence"` (float, 0.0-1.0)
            *   `"display_text_i18n"` (dictionary for user-friendly option text)
            *   `"parsed_entities"` (dictionary of entities relevant to this intent)
            *   `"target_ambiguity"` (optional list of ambiguous targets for a key entity, e.g., if "attack goblin" could mean one of several goblins)
            *   `"clarification_questions_needed"` (optional list for further required info).
        *   Implement initial heuristics for assigning `confidence` scores (e.g., based on direct action verb matches, keyword density, completeness of entity pattern matching).
        *   Implement logic within the parser to identify and populate `target_ambiguity` when multiple valid targets for an intent's primary entity slot are found.
        *   (Reference: `documentation/nlu_ambiguity_handling.md` for detailed structures)."

*   **Task 15 (Turn Processor - `TurnProcessor` / `CharacterActionProcessor`):**
    *   **Existing:** Process actions from `Character.current_action_json` (or `collected_actions_json`).
    *   **Major Revision for Handling Ambiguous NLU Output:**
        *   "Adapt `TurnProcessor` (or `CharacterActionProcessor`) to handle the new `possible_intents` structure from `PlayerActionParser`.
        *   **Disambiguation Logic:**
            1.  If `possible_intents` contains a single intent with high confidence (above a defined threshold and significantly higher than any others) and no `target_ambiguity`, proceed to execute that action.
            2.  If there's only one intent but it has `target_ambiguity`, proceed to target clarification.
            3.  **Intent Clarification Flow (MVP):** If multiple intents have comparable confidence scores or the top confidence is low:
                *   Set `Character.current_game_status` to `"awaiting_clarification"`.
                *   Store `original_text` and a list of clarification `options` (derived from `possible_intents`, including their `display_text_i18n` and underlying `intent_data`) in `Character.state_variables_json.pending_clarification_data`.
                *   Use `NotificationService` to present the player with a numbered list of choices (e.g., "Did you mean to: 1. Attack the goblin? 2. Talk to the goblin?").
            4.  **Target Clarification Flow (MVP):** If an intent is selected (either directly or after intent clarification) but has `target_ambiguity`:
                *   Set `Character.current_game_status` to `"awaiting_clarification"`.
                *   Store `original_text`, `chosen_intent_data`, `ambiguous_field`, and `options` (derived from `target_ambiguity.ambiguous_targets`) in `Character.state_variables_json.pending_clarification_data`.
                *   Use `NotificationService` to prompt the player to choose a specific target from a numbered list.
        *   (Future Enhancement: Briefly note potential for contextual disambiguation using game state before prompting player).
        *   (Reference: `documentation/nlu_ambiguity_handling.md` for detailed logic)."

*   **Task 0.2/7 (Character Model - `Character`):**
    *   **Existing:** Define `Character` model.
    *   **Modification:**
        *   "Add a note confirming that `Character.state_variables_json` (JSONB) will be used to store `pending_clarification_data` when NLU results are ambiguous. This data will include the original text, the type of clarification needed (intent or target), and the options presented to the player."
        *   "Review or add `Character.current_game_status: Optional[str]` (or similar state field) to support states like `awaiting_clarification`, which can gate other command processing."

*   **New Task (e.g., under Phase 6 UI/UX or a dedicated Command Handling phase): "Implement Player Input Handling for NLU Clarification Prompts"**
    *   **Description:** "Design and implement a system for players to respond to NLU clarification prompts.
        1.  This could be a new command (e.g., `/clarify <option_number>` or `/c <number>`) or a mode where direct number input is accepted when `Character.current_game_status` is `awaiting_clarification`.
        2.  The command handler will retrieve `pending_clarification_data` from `Character.state_variables_json`.
        3.  Validate the player's numerical choice against the stored options.
        4.  If the choice is valid:
            *   If clarification was for intent: Construct the chosen action data (now unambiguous or with target ambiguity to resolve next).
            *   If clarification was for a target: Update the chosen action data with the selected target.
        5.  Clear `pending_clarification_data` and reset `Character.current_game_status`.
        6.  Queue the now-disambiguated action for processing by `TurnProcessor` in the next appropriate cycle (or immediately if feasible)."

#### A.4.3 GM AI Assistance (Placeholder - Integration based on Subtask "Outline concept for AI-assisted GM logging and summarization")

*   **New Task (Low Priority / Future Consideration, e.g., Phase 15 or new "Advanced GM Tools" phase): "Conceptualize and Design AI-Assisted GM Summaries"**
    *   **Description:** "Investigate and document a system for providing GMs with AI-generated summaries of significant game events, player achievements, or emerging plot threads.
        1.  Define requirements for `GameLogManager` (Task 17, `StoryLog`) to extract relevant log entries based on time period and significance criteria.
        2.  Outline a conceptual `GmSummaryService` that would:
            *   Fetch data from `GameLogManager` and other relevant sources.
            *   Use `PromptContextCollector` to gather context for the LLM.
            *   Use `MultilingualPromptGenerator` to create prompts for summarizing events into a narrative for the GM (specifying length, focus, tone).
            *   Interact with an LLM service (e.g., `OpenAIService`).
            *   Format and deliver the summary (e.g., via `NotificationService`).
        3.  Consider GM configuration options (frequency, event types for highlighting).
        4.  This task is initially for design and documentation. (Reference: `documentation/gm_ai_assistance_concepts.md`)."
    *   **Marking:** Designate this task explicitly as `Future Consideration` or `Low Priority / Post-MVP`.

## General
*   Ensure all new AI/NLU refinement features are covered by appropriate unit and integration tests.
*   Update game documentation and tutorials where player interaction changes (e.g., NLU clarification).

This integration plan aims to seamlessly weave the AI & NLU refinement features into the existing project tasks.
