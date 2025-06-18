# AI Pipeline Integration Plan for Crafting & Gathering Mechanics

This document outlines the planned modifications to the AI context gathering, prompt generation, and response validation systems to support new crafting and gathering mechanics.

## 1. `bot/ai/prompt_context_collector.py` Modifications

The `GenerationContext` needs to be enriched with information relevant to crafting and gathering.

*   **Character Skills:**
    *   Within `player_context` or a specific `character_details_context`, include the character's crafting and gathering skills (e.g., `mining`, `herbalism`, `blacksmithing`, `alchemy`, `leatherworking`, `inscription`, `tailoring`, `jewelcrafting`, `woodworking`). This data is sourced from `Character.skills_data_json`.
    *   Example structure within context:
        ```json
        "player_character": {
          // ... other character details
          "skills": {
            "mining": 15,
            "herbalism": 10,
            "blacksmithing": 8,
            // ... other skills
          }
        }
        ```

*   **Location Context (`primary_location_details`):**
    *   When gathering context for location generation or interaction, ensure that PoIs of `type: "resource_node"` are included, along with their `resource_details` (as defined in `documentation/json_structures.md`).
    *   Example structure for a resource node PoI within context:
        ```json
        "points_of_interest": [
          {
            "id": "poi_iron_vein_001",
            "type": "resource_node",
            "name_i18n": { "en": "Iron Vein" },
            "resource_details": {
              "resource_item_template_id": "iron_ore_item",
              "gathering_skill_id": "mining",
              "gathering_dc": 12,
              "required_tool_category": "pickaxe",
              "base_yield_formula": "1d6",
              "respawn_time_seconds": 3600
            }
          }
        ]
        ```

*   **Crafting Recipe Data (`available_recipes_summary`):**
    *   For contexts where the AI might need to reference recipes (e.g., an NPC dialogue about crafting, or a quest requiring a specific crafted item that the player might not know yet), provide a summary of available or relevant `CraftingRecipe` data.
    *   This could be a new section in `GenerationContext`:
        ```json
        "available_recipes_summary": [
          {
            "recipe_id": "healing_potion_basic_recipe",
            "output_item_name_i18n": {"en": "Basic Healing Potion"},
            "primary_skill_id": "alchemy"
          },
          {
            "recipe_id": "iron_dagger_recipe",
            "output_item_name_i18n": {"en": "Iron Dagger"},
            "primary_skill_id": "blacksmithing"
          }
          // More recipe summaries
        ]
        ```
    *   The level of detail here would depend on the AI's needs – it could range from just names/IDs to key ingredients or skill requirements.

## 2. `bot/ai/multilingual_prompt_generator.py` Modifications

Prompts need to guide the AI to generate content incorporating crafting and gathering.

*   **Location Generation (`generate_location_description_prompt`):**
    *   **Add instructions for resource nodes:**
        > "Describe any harvestable natural resources present, such as mineral veins, unique plants, fishing spots, or areas where specific creatures suitable for skinning might be found. Define these as Points of Interest (PoIs) with `type: \"resource_node\"`. For each, provide `resource_details` including:
        >   `resource_item_template_id`: The primary item gathered (e.g., \"iron_ore\").
        >   `gathering_skill_id`: The skill used (e.g., \"mining\", \"herbalism\", \"skinning\").
        >   `gathering_dc`: The difficulty to gather.
        >   `required_tool_category`: (Optional) e.g., \"pickaxe\", \"herb_clippers\".
        >   `base_yield_formula`: Dice formula for quantity (e.g., \"1d4\").
        >   `respawn_time_seconds`: (Optional) Time in seconds for the node to replenish."
    *   **Example snippet for prompt:**
        ```
        ...
        Points of Interest: Describe interactive elements.
        For resource nodes, specify: "type": "resource_node", and "resource_details": {"resource_item_template_id": "...", "gathering_skill_id": "...", "gathering_dc": ..., "required_tool_category": "...", "base_yield_formula": "...", "respawn_time_seconds": ...}.
        ...
        ```

*   **NPC Generation (`generate_npc_profile_prompt`):**
    *   **Instructions for crafter/gatherer NPCs:**
        > "If this NPC is a crafter (e.g., blacksmith, alchemist, tailor) or a gatherer (e.g., miner, herbalist, hunter/skinner):
        >   - Clearly state their profession or role in their `role_i18n` or `description_i18n`.
        >   - Their `inventory_json` might include relevant tools, raw materials they've gathered, or items they have crafted.
        >   - They might offer to sell related raw materials, crafted goods, or recipes.
        >   - For crafters, consider if they might know specific `CraftingRecipe` (reference by `recipe_id` or name if available in context). This could be hinted at in their `dialogue_hints_i18n` (e.g., \"Known for their potent healing potions\") or explicitly listed in a new field like `known_recipes: List[str]` (e.g., `[\"healing_potion_basic_recipe\"]`)."
    *   **Example snippet for prompt:**
        ```
        ...
        Role/Profession: Describe the NPC's primary role or job.
        Inventory: List notable items. For gatherers, this might be raw materials. For crafters, tools or crafted items.
        Dialogue Hints: Include hints about services they offer, items they trade, or recipes they might know.
        If applicable, list recipe IDs or names they know in `known_recipes: ["recipe_id_1", "recipe_name_2"]`.
        ...
        ```

*   **Quest Generation (`generate_quest_prompt`):**
    *   **Instructions for gathering/crafting quest steps:**
        > "When designing quest steps, consider objectives that involve gathering specific resources or crafting particular items:
        >   - For gathering, use a structure like `{\"type\": \"gather_item\", \"item_template_id\": \"specific_herb_id\", \"quantity\": 5, \"target_location_hint_i18n\": {\"en\": \"Found in the Sunken Caves\"}}` within `required_mechanics_json` or a dedicated `objectives_json` list.
        >   - For crafting, use `{\"type\": \"craft_item\", \"output_item_template_id\": \"quest_artifact_replica\", \"recipe_hint_i18n\": {\"en\": \"The recipe can be found in the old library\"}}` in `required_mechanics_json` or `objectives_json`."

*   **New Prompt Type - Recipe Generation (`generate_crafting_recipe_prompt`):**
    *   This would be needed if the AI is tasked with creating new `CraftingRecipe` definitions.
    *   **Function Signature (Conceptual):** `async def generate_crafting_recipe_prompt(self, theme: str, available_item_templates: List[Dict], existing_skills: List[str]) -> str:`
    *   **Prompt Instructions:**
        > "Generate a JSON object for a new Crafting Recipe. The recipe should fit the theme: `{theme}`.
        > You can use the following item templates for ingredients and output: `{available_item_templates_summary_json_string}`.
        > Available crafting skills are: `{existing_skills_json_string}`.
        > The JSON output should follow this structure:
        > `{\"name_i18n\": {\"en\": \"<Recipe Name>\"}, \"description_i18n\": {\"en\": \"<Brief Description>\"}, \"ingredients_json\": [{\"item_template_id\": \"<id>\", \"quantity\": <num>}], \"output_item_template_id\": \"<id>\", \"output_quantity\": <num>, \"required_skill_id\": \"<skill_id>\", \"required_skill_level\": <num>, \"other_requirements_json\": {\"required_tools\": [\"<item_id>\"], \"crafting_station_type\": \"<station_type>\"}}`."

## 3. `bot/ai/ai_response_validator.py` & `bot/ai/ai_data_models.py` Modifications

Pydantic models in `ai_data_models.py` will be updated/added to validate AI responses.

*   **Point of Interest (PoI) Model Update:**
    *   The Pydantic model for PoIs (e.g., `PointOfInterestModel` in `ai_data_models.py`, likely nested within `GeneratedLocationContent`) needs a new optional field for resource node details.
    *   **New `ResourceNodeDetails` Pydantic Model:**
        ```python
        from typing import Optional, List
        from pydantic import BaseModel, Field

        class ResourceNodeDetails(BaseModel):
            resource_item_template_id: str = Field(..., description="The item template ID of the primary resource obtained.")
            gathering_skill_id: str = Field(..., description="The skill ID used for gathering from this node.")
            gathering_dc: int = Field(..., description="Base difficulty to gather.")
            required_tool_category: Optional[str] = Field(None, description="Category of tool required, e.g., 'pickaxe'.")
            base_yield_formula: str = Field(..., description="Dice formula for quantity, e.g., '1d4'.")
            secondary_resource_item_template_id: Optional[str] = Field(None, description="Optional rarer secondary resource item ID.")
            secondary_resource_yield_formula: Optional[str] = Field(None, description="Formula for yielding secondary resource.")
            secondary_resource_chance: Optional[float] = Field(None, description="Chance (0.0-1.0) of getting secondary resource.")
            respawn_time_seconds: Optional[int] = Field(None, description="Time in seconds for the node to respawn.")
        ```
    *   The main PoI Pydantic model would then include:
        ```python
        class PointOfInterestModel(BaseModel): # Or existing name
            # ... other PoI fields (id, type, name_i18n, description_i18n, lock_details, trap_details)
            resource_details: Optional[ResourceNodeDetails] = None
            # ... other fields

            # Validator to ensure resource_details is present if type is "resource_node"
            # @root_validator
            # def check_resource_details_for_type(cls, values):
            #     poi_type = values.get("type")
            #     resource_details = values.get("resource_details")
            #     if poi_type == "resource_node" and resource_details is None:
            #         raise ValueError("resource_details must be provided for PoIs of type 'resource_node'")
            #     return values
        ```

*   **NPC Profile (`GeneratedNpcProfile`):**
    *   Add `known_recipes: Optional[List[str]] = Field(None, description="List of recipe IDs or descriptive names the NPC knows.")`

*   **New Pydantic Model - `GeneratedCraftingRecipe`:**
    *   If AI generates recipes, define this model in `ai_data_models.py`.
        ```python
        from typing import Optional, List, Dict
        from pydantic import BaseModel, Field

        class RecipeIngredient(BaseModel):
            item_template_id: str
            quantity: int

        class OtherRecipeRequirements(BaseModel):
            required_tools: Optional[List[str]] = None # List of item_template_ids
            crafting_station_type: Optional[str] = None # e.g., "anvil_and_forge"
            required_location_tags: Optional[List[str]] = None
            requires_event_flag: Optional[str] = None

        class GeneratedCraftingRecipe(BaseModel):
            recipe_id: Optional[str] = Field(None, description="Unique ID for the recipe, if generated or known.") # May be added post-generation
            name_i18n: Dict[str, str]
            description_i18n: Optional[Dict[str, str]] = None
            ingredients_json: List[RecipeIngredient]
            output_item_template_id: str
            output_quantity: int = Field(default=1)
            required_skill_id: str # e.g., "blacksmithing"
            required_skill_level: int
            other_requirements_json: Optional[OtherRecipeRequirements] = None
            # Future: experience_gained, discovery_chance, etc.
        ```

*   **`AIResponseValidator`:**
    *   Update validation logic to use `ResourceNodeDetails` when validating PoIs of type "resource_node".
    *   If `GeneratedCraftingRecipe` is implemented, add validation logic for AI responses that are expected to produce recipe JSON.

## 4. Summary of Files and Key Changes

*   **`bot/ai/prompt_context_collector.py`:**
    *   Enhance `GenerationContext` to include character crafting/gathering skills, resource node PoI details, and potentially a summary of available/known crafting recipes.
*   **`bot/ai/multilingual_prompt_generator.py`:**
    *   Update `generate_location_description_prompt` to request `resource_node` PoIs with specific `resource_details`.
    *   Update `generate_npc_profile_prompt` for NPCs involved in crafting/gathering (professions, inventory, known recipes).
    *   Update `generate_quest_prompt` to suggest gathering/crafting objectives.
    *   Potentially add `generate_crafting_recipe_prompt` if AI is to generate recipes.
*   **`bot/ai/ai_data_models.py`:**
    *   Define new Pydantic model: `ResourceNodeDetails`.
    *   Update the PoI Pydantic model to include `Optional[ResourceNodeDetails]`.
    *   Add `known_recipes: Optional[List[str]]` to `GeneratedNpcProfile`.
    *   Potentially define `GeneratedCraftingRecipe`, `RecipeIngredient`, and `OtherRecipeRequirements` Pydantic models if AI generates recipes.
*   **`bot/ai/ai_response_validator.py`:**
    *   Update to use the new/modified Pydantic models for validating AI-generated content.

This plan focuses on guiding the AI to produce content that naturally integrates with the new crafting and gathering game mechanics.
