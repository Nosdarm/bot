# Project Task List Updates for Crafting & Gathering Mechanics Integration

This document outlines the conceptual updates to the main project task list to incorporate the implementation of Crafting and Gathering Mechanics.

## Phase A: Core Mechanics and Systems (Continued)

### A.2 Crafting and Gathering Mechanics

#### A.2.1 Model Definitions (Integration based on Subtask "Document JSON structures for CraftingRecipe, resource_node PoIs, and new skills")

*   **Task 7 (DB Schemas - Character, Party, NPC, Item, Location, Quest, Event, Dialogue, Faction, WorldState, GlobalNPC, GameLogEntry):**
    *   **Existing:** Define database schemas for core models.
    *   **Modification for `CraftingRecipe` model (assuming it's part of DB schema or a structured config):**
        *   "Ensure `CraftingRecipe` definition includes `other_requirements_json` field. This JSON will store:
            *   `required_tools: Optional[List[str]]` (list of item\_template\_ids).
            *   `crafting_station_type: Optional[str]` (e.g., "anvil\_and\_forge", "alchemy\_lab").
            *   `required_location_tags: Optional[List[str]]`.
            *   `requires_event_flag: Optional[str]`."
    *   **Modification for `Character` model:**
        *   "Update `Character.skills_data_json` to explicitly include keys for crafting and gathering skills:
            *   `mining`, `herbalism`, `skinning` (gathering skills).
            *   `blacksmithing`, `alchemy`, `leatherworking`, `inscription`, `tailoring`, `jewelcrafting`, `woodworking` (crafting skills).
            *   (Reference: `documentation/json_structures.md` for details)."

*   **Task 4 (Location Model) / Task 23 (Location Model Refined - Game World & Locations):**
    *   **Existing:** Define `Location` model, including `points_of_interest_json`.
    *   **Modification:**
        *   "Update `Location.points_of_interest_json` to support PoIs of `type: "resource_node"`. These PoIs will include a nested `resource_details` object containing fields such as:
            *   `resource_item_template_id: str`
            *   `gathering_skill_id: str`
            *   `gathering_dc: int`
            *   `required_tool_category: Optional[str]`
            *   `base_yield_formula: str`
            *   `secondary_resource_item_template_id: Optional[str]`
            *   `secondary_resource_yield_formula: Optional[str]`
            *   `secondary_resource_chance: Optional[float]`
            *   `respawn_time_seconds: Optional[int]`
            *   `last_gathered_timestamp: Optional[float]`
            *   `is_depleted: bool`.
            *   (Reference: `documentation/json_structures.md` for detailed structure)."

#### A.2.2 RuleEngine Updates (Integration based on Subtask "Add new rule logic to RuleEngine for gathering resources and crafting items")

*   **Task 12 (Check Resolver & Rule Engine - `RuleEngine` class, `resolve_skill_check`, etc.):**
    *   **Existing:** Implement core check resolution methods in `RuleEngine`.
    *   **Modifications/Additions:**
        *   "Implement `async def resolve_gathering_attempt(self, character_id: str, guild_id: str, poi_data: Dict[str, Any], character_skills: Dict[str, int], character_inventory: List[Dict[str, Any]], **kwargs) -> DetailedCheckResult` in `RuleEngine`. This method will:
            *   Check if the character has the `required_tool_category` (from `poi_data.resource_details`) in their `character_inventory`.
            *   Perform a skill check using `resolve_skill_check` with the character's relevant gathering skill against `poi_data.resource_details.gathering_dc`.
            *   If successful, calculate resource yield using `resolve_dice_roll` on `poi_data.resource_details.base_yield_formula` (and secondary yield if applicable).
            *   Return `DetailedCheckResult` with success status, message key, and yielded items."
        *   "Implement `async def resolve_crafting_attempt(self, character_id: str, guild_id: str, recipe_data: Dict[str, Any], character_skills: Dict[str, int], character_inventory: List[Dict[str, Any]], current_location_data: Dict[str, Any], **kwargs) -> DetailedCheckResult` in `RuleEngine`. For MVP, this method will:
            *   Verify character's skill level (from `character_skills`) meets `recipe_data.required_skill_level`.
            *   Verify character possesses all ingredients (from `recipe_data.ingredients_json`) in `character_inventory`.
            *   Verify character possesses specific tools (from `recipe_data.other_requirements_json.required_tools`) in `character_inventory`.
            *   Verify current environment (`current_location_data`) meets `crafting_station_type` and `required_location_tags` specified in `recipe_data.other_requirements_json`.
            *   If all checks pass, assume success. Future enhancements include a skill check against recipe difficulty.
            *   Return `DetailedCheckResult` with success status, message key, crafted item, and consumed ingredients."
        *   "Ensure these new `RuleEngine` methods are prepared to use `self._rules_data` (from `RuleConfig`) for future parameters like base success chances, tool effectiveness modifiers, XP gain formulas, etc."

#### A.2.3 Action System Updates (Integration based on Subtask "Define and outline the integration of new player actions for crafting and gathering")

*   **Task 13 (NLU & Intent/Entity Recognition - `IntentRecognizer` and `EntityExtractor`):**
    *   **Existing:** Define NLU intents and entities.
    *   **New Sub-task:** "Define NLU intents (e.g., `intent_gather_resource`, `intent_craft_item`) and corresponding entities (e.g., `entity_target_poi_resource`, `entity_recipe_name`) for gathering and crafting commands. Update the guild-scoped NLU dictionary/model."

*   **Task 15 (Turn Processor - `TurnProcessor` / `CharacterActionProcessor`):**
    *   **Existing:** Implement `TurnProcessor` to manage game turns and action execution.
    *   **Modification (specifically for `CharacterActionProcessor` or equivalent):**
        *   "Update action processing logic to recognize and handle new action types:
            *   `gather_resource_attempt`
            *   `craft_item_attempt`
        *   For `gather_resource_attempt`:
            *   Fetch character skills/inventory, and PoI data (including `resource_details`) via managers.
            *   Invoke `rule_engine.resolve_gathering_attempt(...)`.
            *   Process `DetailedCheckResult`: update character inventory with yielded items (via `InventoryManager`), update PoI state (e.g., `is_depleted`, `last_gathered_timestamp` via `LocationManager`), and provide player feedback.
        *   For `craft_item_attempt`:
            *   Fetch character skills/inventory, recipe data (via `CraftingManager` or `RuleConfig`), and current location data.
            *   Invoke `rule_engine.resolve_crafting_attempt(...)`.
            *   Process `DetailedCheckResult`: update character inventory by removing consumed items and adding crafted items (via `InventoryManager`), potentially grant XP, and provide player feedback.
            *   (Reference: `documentation/crafting_gathering_action_integration.md` for action structures)."

*   **Task 16 (Intra-Location Interaction Handler - `InteractionHandler`):**
    *   **Existing:** Handle interactions within a location.
    *   **Modification:** "Ensure that interactions with PoIs of `type: "resource_node"` can trigger the `gather_resource_attempt` action by queueing the appropriate action structure for the `CharacterActionProcessor`."

*   **New Task Group: "A.2.3.1 Crafting & Gathering Command Modules"** (or integrate into existing command module tasks)
    *   **New Task:** "Implement Discord command parsing for `/gather <target_resource_node_poi>`. This command will resolve target PoI, create, and queue a `gather_resource_attempt` action JSON."
    *   **New Task:** "Implement Discord command parsing for `/craft <recipe_name_or_id> [quantity]`. This command will resolve the recipe, create, and queue a `craft_item_attempt` action JSON."
    *   "Command parsing logic should refer to `documentation/crafting_gathering_action_integration.md` for defined action JSON structures."

*   **Task 0.3 (Manager Implementation Plan) / New Task:**
    *   **New Sub-task/Consideration:** "Implement `CraftingManager` to handle loading, caching, and providing access to `CraftingRecipe` definitions. This manager will be used by `CharacterActionProcessor` (or similar) to fetch recipe data for crafting attempts. Alternatively, integrate recipe management into `RuleConfig` or `ItemManager`."

### A.3 AI System Enhancements (Crafting/Gathering)

#### A.3.1 AI Context and Generation for Crafting/Gathering (Integration based on Subtask "Plan updates to AI context, prompts, and validation for crafting/gathering")

*   **Task 8 (AI Prompt Preparation - `PromptContextCollector`, `MultilingualPromptGenerator`):**
    *   **Existing:** Prepare context and generate prompts for AI.
    *   **Modifications for `PromptContextCollector`:**
        *   "Update `PromptContextCollector` to include character's crafting/gathering skills (e.g., `mining`, `blacksmithing`) in the `GenerationContext`."
        *   "Update `PromptContextCollector` to include `resource_details` from `resource_node` PoIs in `primary_location_details` for AI context."
        *   "Update `PromptContextCollector` to consider adding `available_recipes_summary` (list of known/available recipe names/IDs) to `GenerationContext` for scenarios where AI needs to reference recipes."
    *   **Modifications for `MultilingualPromptGenerator`:**
        *   "Modify `generate_location_description_prompt` to instruct the AI to include `resource_node` PoIs with their full `resource_details` structure."
        *   "Modify `generate_npc_profile_prompt` to instruct the AI to consider crafter/gatherer roles for NPCs, including relevant inventory items and potentially a list of `known_recipes`."
        *   "Modify `generate_quest_prompt` to instruct the AI to suggest quest steps involving gathering specific resources or crafting particular items, with example `required_mechanics_json` or `objectives_json` structures."
        *   **New Sub-task:** "Define and implement `generate_crafting_recipe_prompt` if the AI is intended to generate `CraftingRecipe` data directly. This prompt should guide the AI to output JSON matching the defined recipe structure."
        *   (Reference: `documentation/ai_crafting_gathering_integration.md` for prompt details and JSON examples)."

*   **Task 9 (AI Response Parsing & Validation - `AIResponseValidator`, Pydantic models in `ai_data_models.py`):**
    *   **Existing:** Parse and validate AI responses.
    *   **Modifications for `ai_data_models.py`:**
        *   "Define a new Pydantic model `ResourceNodeDetails` with fields like `resource_item_template_id`, `gathering_skill_id`, `gathering_dc`, `required_tool_category`, `base_yield_formula`, `respawn_time_seconds`, etc."
        *   "Update the existing Pydantic model for Points of Interest (PoIs) to include `resource_details: Optional[ResourceNodeDetails]`."
        *   "Consider adding `known_recipes: Optional[List[str]]` to the `GeneratedNpcProfile` Pydantic model."
        *   "If AI generates recipes, define a `GeneratedCraftingRecipe` Pydantic model, including nested models for ingredients and other requirements, mirroring the structure of `CraftingRecipe`."
    *   **Modifications for `AIResponseValidator`:**
        *   "Ensure `AIResponseValidator` correctly uses the updated PoI Pydantic model (with nested `ResourceNodeDetails`) for validating AI-generated location content."
        *   "If `GeneratedCraftingRecipe` is implemented, add validation logic for AI responses expected to produce recipe JSON."
        *   (Reference: `documentation/ai_crafting_gathering_integration.md`)."

## General
*   Ensure all new crafting and gathering features are covered by appropriate unit and integration tests.
*   Update game documentation and tutorials to reflect new mechanics.

This integration plan aims to seamlessly weave the crafting and gathering mechanics into the existing project tasks.
