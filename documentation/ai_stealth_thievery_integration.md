# AI Pipeline Integration Plan for Stealth and Thievery Mechanics

This document outlines the planned modifications to the AI context gathering, prompt generation, and response validation systems to support new stealth and thievery mechanics.

## 1. `bot/ai/prompt_context_collector.py` Modifications

The `GenerationContext` needs to be enriched with information relevant to stealth and thievery.

*   **Character Skills:**
    *   Within the `player_context` or a more specific `character_details_context` (if it exists or is created), include the character's stealth-related skills. This data will be sourced from `Character.skills_data_json`.
    *   Example structure within context:
        ```json
        "player_character": {
          // ... other character details
          "skills": {
            "stealth": 12,
            "pickpocket": 8,
            "lockpicking": 10,
            "disarm_traps": 11
            // ... other skills
          }
        }
        ```
*   **Location & NPC Information for Thievery Targets:**
    *   **Primary Location Details (`primary_location_details`):** When gathering context for location generation or interaction, ensure that information about PoIs that are locked containers or traps is included. This data comes from `Location.points_of_interest_json`.
        *   Example structure for a PoI within context:
            ```json
            "points_of_interest": [
              {
                "id": "chest_01",
                "type": "container", // or "lockable_container"
                "name_i18n": {"en": "Ornate Chest"},
                "lock_details": {"dc": 15, "is_locked": true}
              },
              {
                "id": "trap_01",
                "type": "trap",
                "name_i18n": {"en": "Floor Spike Trap"},
                "trap_details": {
                  "trap_type": "spike_trap",
                  "is_active": true,
                  "detection_dc": 14,
                  "disarm_dc": 16
                }
              }
            ]
            ```
    *   **NPC Details:** When gathering context for NPC generation or interaction, if an NPC has valuable items in their `inventory_json` (from `NPC.inventory_json`), this should be accessible. This allows the AI to subtly hint at pickpocketing opportunities.
        *   Example structure for NPC context:
            ```json
            "involved_npcs": [
              {
                "id": "npc_merchant_01",
                "name": "Silas",
                // ... other npc details
                "inventory_summary": ["Gold pouch", "Shiny dagger", "A crumpled note"], // Could be a summary or key items
                "behavior_tags": ["distracted", "wealthy"] // Hints for thievery
              }
            ]
            ```

## 2. `bot/ai/multilingual_prompt_generator.py` Modifications

Prompts need to be updated to guide the AI in generating content that incorporates stealth and thievery opportunities.

*   **Location Generation (`generate_location_description_prompt`):**
    *   **Add instructions for environmental details:**
        > "Describe the location, paying attention to elements that could be relevant for stealthy actions. Are there shadowy corners, alcoves, rafters, or dense foliage that could serve as hiding spots? Are there guard patrols with predictable routes? Mention any sources of light or noise."
    *   **Add instructions for PoIs related to thievery:**
        > "When detailing Points of Interest (PoIs):
        > If a PoI is a container that should be locked, include a `lock_details` object like: `\"lock_details\": {\"dc\": <integer_difficulty_check_value>, \"is_locked\": true}`.
        > If a PoI is a trap, include a `trap_details` object like: `\"trap_details\": {\"trap_type\": \"<e.g., dart_trap, pit_trap>\", \"is_active\": true, \"detection_dc\": <integer_value>, \"disarm_dc\": <integer_value>, \"effect_description_i18n\": {\"en\": \"...\"}}`."
    *   **Example snippet for prompt:**
        ```
        ...
        Points of Interest: Describe any interactive elements.
        For locked containers, specify: "lock_details": {"dc": 15, "is_locked": true}.
        For traps, specify: "trap_details": {"trap_type": "dart_trap", "is_active": true, "detection_dc": 14, "disarm_dc": 16, "effect_description_i18n": {"en": "A hidden dart fires!"}}.
        Consider including shadowy areas suitable for hiding or guard patrol routes if applicable.
        ...
        ```

*   **NPC Generation (`generate_npc_profile_prompt`):**
    *   **Add instructions for pickpocketable items and NPC awareness:**
        > "Consider the NPC's profession and personality. If they are likely to carry valuable small items (like keys, jewelry, coin purses, important notes), include a few such items in their `inventory_json`. Subtly hint at these items if appropriate in their description or behavior.
        > Also, reflect on their general awareness. Are they typically alert, observant, distracted, or oblivious? This can be hinted at in their `personality_i18n` description or by adding relevant `behavior_tags` (e.g., 'alert', 'careless', 'paranoid')."
    *   **Example snippet for prompt:**
        ```
        ...
        Inventory: List any notable items the NPC carries. If they might have items a player could try to steal, include them here.
        Personality & Behavior: Describe their personality. Note if they are particularly observant or perhaps easily distracted, which might affect stealth interactions. Add relevant `behavior_tags`.
        ...
        ```

*   **Quest Generation (`generate_quest_prompt`):**
    *   **Add suggestions for skill-based quest steps:**
        > "When designing quest steps, consider incorporating challenges that can be overcome using stealth or thievery skills. For example, a step might involve:
        > - Sneaking into an area unseen (`stealth`).
        > - Pickpocketing a key or document from an NPC (`pickpocket`).
        > - Bypassing a locked door or opening a secure chest (`lockpicking`).
        > - Disarming a trap protecting an objective (`disarm_traps`).
        > For such steps, define the necessary mechanic in the `required_mechanics_json` field."
    *   **Provide examples for `required_mechanics_json`:**
        > "Examples for `required_mechanics_json`:
        >   `{\"type\": \"skill_check\", \"skill\": \"stealth\", \"dc\": 15, \"description_i18n\": {\"en\": \"Sneak past the guards\"}}`
        >   `{\"type\": \"skill_check\", \"skill\": \"pickpocket\", \"target_npc_id\": \"<npc_id_placeholder>\", \"item_to_obtain_ref\": \"quest_key_01\", \"dc\": 14, \"description_i18n\": {\"en\": \"Steal the key from the warden\"}}`
        >   `{\"type\": \"skill_check\", \"skill\": \"lockpicking\", \"target_poi_id\": \"<poi_id_placeholder_for_locked_door>\", \"dc\": 18, \"description_i18n\": {\"en\": \"Open the master vault door\"}}`
        >   `{\"type\": \"skill_check\", \"skill\": \"disarm_traps\", \"target_poi_id\": \"<poi_id_placeholder_for_trap>\", \"dc\": 16, \"description_i18n\": {\"en\": \"Disable the pressure plate\"}}`"

## 3. `bot/ai/ai_response_validator.py` and `bot/ai/ai_data_models.py` Modifications

Pydantic models used for validating AI responses will need updating to reflect the new data structures for PoIs and quest mechanics. These models are likely defined in `bot/ai/ai_data_models.py`.

*   **Point of Interest (PoI) Model:**
    *   The Pydantic model representing a PoI (likely nested within `GeneratedLocationContent` or a similar model) needs to be updated to include optional `lock_details` and `trap_details` fields.
    *   **`LockDetails` (New Pydantic Model):**
        ```python
        from typing import Optional
        from pydantic import BaseModel, Field

        class LockDetails(BaseModel):
            dc: int = Field(..., description="Difficulty class to pick the lock.")
            is_locked: bool = Field(default=True, description="Whether the lock is currently locked.")
            # attempts_to_break_pick: Optional[int] = Field(None, description="Number of failed attempts before a pick breaks.") # Future
        ```
    *   **`TrapDetails` (New Pydantic Model):**
        ```python
        from typing import Optional, Dict
        from pydantic import BaseModel, Field

        class TrapDetails(BaseModel):
            trap_type: str = Field(..., description="Type of trap, e.g., 'dart_trap', 'pit_trap'.")
            is_active: bool = Field(default=True, description="Whether the trap is currently active.")
            detection_dc: int = Field(..., description="DC to detect the trap.")
            disarm_dc: int = Field(..., description="DC to disarm the trap.")
            avoid_dc: Optional[int] = Field(None, description="Optional DC to avoid the trap if triggered.")
            effect_description_i18n: Dict[str, str] = Field(..., description="User-facing description of the trap's effect.")
            effect_mechanics_json: Optional[Dict] = Field(None, description="Structured data for game effects.") # Validate as generic JSON for now
            reset_time_seconds: Optional[int] = Field(None, description="Time for the trap to reset, if applicable.")
        ```
    *   The main PoI Pydantic model would then include:
        ```python
        class PointOfInterestModel(BaseModel): # Or existing name
            # ... other PoI fields (id, type, name_i18n, description_i18n)
            lock_details: Optional[LockDetails] = None
            trap_details: Optional[TrapDetails] = None
            # ... other fields
        ```

*   **NPC Profile (`GeneratedNpcProfile`):**
    *   No structural changes anticipated for `inventory_json` itself, as it's likely already a list of strings or simple objects.
    *   `behavior_tags` (if added as a new field, e.g., `List[str]`) would need to be added to the Pydantic model.

*   **Quest Data (`GeneratedQuestData` and `GeneratedQuestStep`):**
    *   The `required_mechanics_json` field in `GeneratedQuestStep` (or equivalent) might currently be validated as a generic `Dict` or `JSON`.
    *   For improved validation, specific Pydantic models could be created for different mechanic types, using a discriminated union if Pydantic supports it well enough, or by validating the `'type'` field and then parsing the rest.
    *   **MVP Approach:** For now, continue validating `required_mechanics_json` as `Optional[Dict[str, Any]]`. The structure examples provided in prompt generation will guide the AI. Future tasks can enhance this validation if needed.

## 4. Summary of Files and Key Changes

*   **`bot/ai/prompt_context_collector.py`:**
    *   Enhance `GenerationContext` to include character skills (stealth, pickpocket, etc.) and relevant details about PoIs (locks, traps) and NPC inventories/behaviors.
*   **`bot/ai/multilingual_prompt_generator.py`:**
    *   Update `generate_location_description_prompt` to request details on hiding spots, locked/trapped PoIs with specific JSON structures.
    *   Update `generate_npc_profile_prompt` to request hints about pickpocketable items and NPC awareness levels (via personality or `behavior_tags`).
    *   Update `generate_quest_prompt` to suggest quest steps involving stealth/thievery skills and provide examples for `required_mechanics_json`.
*   **`bot/ai/ai_data_models.py` (or equivalent file for Pydantic models):**
    *   Define new Pydantic models: `LockDetails` and `TrapDetails`.
    *   Update the PoI Pydantic model to include `Optional[LockDetails]` and `Optional[TrapDetails]`.
    *   Potentially add `behavior_tags: Optional[List[str]]` to the NPC Pydantic model.
    *   No immediate changes to `GeneratedQuestStep.required_mechanics_json` validation beyond ensuring it can accept a flexible dictionary, but structured examples will be provided in prompts.
*   **`bot/ai/ai_response_validator.py`:**
    *   The validator will automatically use the updated Pydantic models from `ai_data_models.py` to validate the new structures in AI-generated content (locations with locks/traps).

This plan focuses on guiding the AI to produce content that naturally integrates with the new game mechanics.
