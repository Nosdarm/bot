# Project Task List Updates for Stealth & Thievery Mechanics Integration

This document outlines the conceptual updates to the main project task list to incorporate the implementation of Stealth and Thievery Mechanics.

## Phase A: Core Mechanics and Systems

### A.1 Core Gameplay Logic & Data Models

#### A.1.1 Model Definitions (Integration of Subtask "Define JSON structures for Character.skills_data_json and Location.points_of_interest_json")

*   **Task 4 (Location Model) / Task 23 (Location Model Refined - Game World & Locations):**
    *   **Existing:** Define `Location` model, including `points_of_interest_json`.
    *   **Modification:**
        *   "Update `Location.points_of_interest_json` to support:
            *   PoIs of `type: "trap"` with a nested `trap_details` object containing fields like `trap_type`, `is_active`, `detection_dc`, `disarm_dc`, `avoid_dc`, `effect_description_i18n`, `effect_mechanics_json`, `reset_time_seconds`.
            *   PoIs representing locked objects (e.g., `type: "container"`, `type: "door"`) to include a `lock_details` object: `{"dc": <integer_difficulty_check_value>, "is_locked": true}`.
            *   (Reference: `documentation/json_structures.md` for detailed structures)."

*   **Task 7 (DB Schemas - Character, Party, NPC, Item, Location, Quest, Event, Dialogue, Faction, WorldState, GlobalNPC, GameLogEntry):**
    *   **Existing:** Define database schemas for core models.
    *   **Modification for `Character` model:**
        *   "Update `Character.skills_data_json` to explicitly include keys for stealth-related skills:
            *   `stealth`: Integer (skill in moving unseen/unheard).
            *   `pickpocket`: Integer (skill for stealing from NPCs).
            *   `lockpicking`: Integer (skill for opening locked containers/doors).
            *   `disarm_traps`: Integer (skill for neutralizing traps).
            *   These are in addition to any other planned skills.
            *   (Reference: `documentation/json_structures.md` for context)."

#### A.1.2 RuleEngine Updates (Integration of Subtask "Add new rule logic to RuleEngine for stealth, pickpocketing, lockpicking, and disarming traps")

*   **Task 12 (Check Resolver & Rule Engine - `RuleEngine` class, `resolve_skill_check`, `resolve_saving_throw`, `resolve_attack_roll`, `calculate_damage`):**
    *   **Existing:** Implement core check resolution methods in `RuleEngine`.
    *   **Modifications/Additions:**
        *   "Implement `async def resolve_stealth_check(self, character_id: str, guild_id: str, location_id: str, **kwargs) -> DetailedCheckResult` in `RuleEngine`. This will use the character's `stealth` skill against a DC derived from location factors or NPC perception (from `RuleConfig`)."
        *   "Implement `async def resolve_pickpocket_attempt(self, character_id: str, guild_id: str, target_npc_id: str, **kwargs) -> DetailedCheckResult` in `RuleEngine`. This will use `pickpocket` skill against a DC from target NPC's awareness and item difficulty (from `RuleConfig`). Outcome includes success, detection, and item stolen."
        *   "Implement `async def resolve_lockpick_attempt(self, character_id: str, guild_id: str, poi_data: Dict[str, Any], **kwargs) -> DetailedCheckResult` in `RuleEngine`. This uses `lockpicking` skill against `poi_data.lock_details.dc`. Outcome includes success and potential tool breakage (from `RuleConfig`)."
        *   "Implement `async def resolve_disarm_trap_attempt(self, character_id: str, guild_id: str, poi_data: Dict[str, Any], **kwargs) -> DetailedCheckResult` in `RuleEngine`. This uses `disarm_traps` skill against `poi_data.trap_details.disarm_dc`. Outcome includes success and trap triggered status (rules for triggering on fail from `RuleConfig`)."
        *   "Ensure all new `RuleEngine` methods utilize `self._rules_data` (loaded from `RuleConfig`) for relevant parameters (base DCs, modifiers, consequences of critical failures, etc.)."

#### A.1.3 Action System Updates (Integration of Subtask "Define and integrate new player actions for stealth and thievery into the game's action processing system")

*   **Task 13 (NLU & Intent/Entity Recognition - `IntentRecognizer` and `EntityExtractor`):**
    *   **Existing:** Define NLU intents and entities.
    *   **New Sub-task:** "Define NLU intents (e.g., `intent_stealth`, `intent_pickpocket`, `intent_lockpick`, `intent_disarm_trap`) and corresponding entities (e.g., `entity_target_npc`, `entity_target_poi`) for stealth and thievery commands."
    *   **New Sub-task:** "Update the guild-scoped NLU dictionary/model with these new intents and entities."

*   **Task 15 (Turn Processor - `TurnProcessor` / `CharacterActionProcessor`):**
    *   **Existing:** Implement `TurnProcessor` to manage game turns and action execution.
    *   **Modification (specifically for `CharacterActionProcessor` or equivalent):**
        *   "Update action processing logic to recognize and handle new action types:
            *   `stealth_attempt`
            *   `pickpocket_attempt`
            *   `lockpick_attempt`
            *   `disarm_trap_attempt`
        *   For each new action type:
            *   Fetch necessary context (e.g., PoI data for lockpicking/disarming from `LocationManager`).
            *   Invoke the corresponding new `RuleEngine.resolve_*` method.
            *   Process the `DetailedCheckResult`: update game state (character status, NPC awareness, PoI states via `LocationManager` helpers, inventory changes via `InventoryManager`), and generate appropriate player feedback.
            *   (Reference: `documentation/stealth_thievery_action_integration.md` for action structures)."

*   **Task 16 (Intra-Location Interaction Handler - `InteractionHandler`):**
    *   **Existing:** Handle interactions within a location.
    *   **Modification:** "Ensure that interactions with PoIs that are locked (e.g., chests, doors) or are traps can trigger the `lockpick_attempt` or `disarm_trap_attempt` actions respectively, by queueing the appropriate action structure for the `CharacterActionProcessor`."

*   **New Task Group: "A.1.3.1 Thievery Command Modules"** (or integrate into existing command module tasks)
    *   **New Task:** "Implement Discord command parsing for `/stealth`. This command will create and queue a `stealth_attempt` action JSON."
    *   **New Task:** "Implement Discord command parsing for `/pickpocket <target_npc> [optional_item_name]`. This command will resolve target NPC, create, and queue a `pickpocket_attempt` action JSON."
    *   **New Task:** "Implement Discord command parsing for `/lockpick <target_object_in_poi>`. This command will resolve the target PoI (e.g., from `Location.points_of_interest_json`), create, and queue a `lockpick_attempt` action JSON."
    *   **New Task:** "Implement Discord command parsing for `/disarm <trap_in_poi>`. This command will resolve the target PoI, create, and queue a `disarm_trap_attempt` action JSON."
    *   "All command parsing logic should refer to `documentation/stealth_thievery_action_integration.md` for the defined action JSON structures."

### A.2 AI System Enhancements

#### A.2.1 AI Context and Generation for Stealth/Thievery (Integration of Subtask "Plan updates to AI context gathering, prompt generation, and response validation for stealth/thievery")

*   **Task 8 (AI Prompt Preparation - `PromptContextCollector`, `MultilingualPromptGenerator`):**
    *   **Existing:** Prepare context and generate prompts for AI.
    *   **Modifications for `PromptContextCollector`:**
        *   "Update `PromptContextCollector` to include the character's stealth-related skills (`stealth`, `pickpocket`, `lockpicking`, `disarm_traps` from `Character.skills_data_json`) in the `GenerationContext` (e.g., within `player_context`)."
        *   "Update `PromptContextCollector` to include `lock_details` and `trap_details` from `Location.points_of_interest_json` in `primary_location_details` when relevant for AI context."
        *   "Update `PromptContextCollector` to make relevant NPC inventory details and behavioral hints (e.g. 'alert', 'distracted') available for NPC-related generation context."
    *   **Modifications for `MultilingualPromptGenerator`:**
        *   "Modify `generate_location_description_prompt` to instruct the AI to include descriptions of stealth opportunities (shadows, hiding spots, patrol routes) and to define PoIs representing locked objects (with `lock_details`) and traps (with `trap_details`, including DCs and effects)."
        *   "Modify `generate_npc_profile_prompt` to instruct the AI to consider including pickpocketable items in NPC inventories and to provide hints about NPC awareness levels in their personality or behavior tags."
        *   "Modify `generate_quest_prompt` to instruct the AI to consider suggesting quest steps that might involve stealth, pickpocketing, lockpicking, or disarming traps, including examples for their `required_mechanics_json` structure."
        *   (Reference: `documentation/ai_stealth_thievery_integration.md` for prompt details and JSON examples)."

*   **Task 9 (AI Response Parsing & Validation - `AIResponseValidator`, Pydantic models in `ai_data_models.py`):**
    *   **Existing:** Parse and validate AI responses.
    *   **Modifications for `ai_data_models.py`:**
        *   "Define a new Pydantic model `LockDetails` with fields like `dc: int`, `is_locked: bool`."
        *   "Define a new Pydantic model `TrapDetails` with fields like `trap_type: str`, `is_active: bool`, `detection_dc: int`, `disarm_dc: int`, `effect_description_i18n: Dict[str, str]`, etc."
        *   "Update the existing Pydantic model for Points of Interest (PoIs) to include `lock_details: Optional[LockDetails]` and `trap_details: Optional[TrapDetails]`."
        *   "Consider adding `behavior_tags: Optional[List[str]]` to the NPC Pydantic model."
    *   **Modifications for `AIResponseValidator`:**
        *   "Ensure `AIResponseValidator` correctly uses the updated PoI Pydantic model (with nested `LockDetails` and `TrapDetails`) for validating AI-generated location content."
        *   "For quest steps, `required_mechanics_json` will continue to be validated as `Optional[Dict[str, Any]]` for MVP, but AI will be guided by prompt examples for structure."
        *   (Reference: `documentation/ai_stealth_thievery_integration.md`)."

## General
*   Ensure all new features are covered by appropriate unit and integration tests.
*   Update game documentation and tutorials to reflect new mechanics.

This integration plan aims to seamlessly weave the stealth and thievery mechanics into the existing project tasks.
