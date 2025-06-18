# AI Prompt Module Review (Task 2.2 Preparedness)

This document summarizes the review of `bot/ai/prompt_context_collector.py` and `bot/ai/multilingual_prompt_generator.py` with respect to their adequacy for fulfilling the requirements of Task 2.2 (AI Prompt Preparation for Dynamic Content Generation).

## 1. `PromptContextCollector` Review (Subtask A.2.2.1)

The `PromptContextCollector` and its primary method `get_full_context(guild_id, character_id, target_entity_id, target_entity_type, location_id, event_id, **kwargs)` were reviewed.

*   **Comprehensiveness for Task 2.2:**
    *   The method is designed to gather a wide array of data points, which largely align with the needs of Task 2.2 for generating dynamic content.
    *   It covers:
        *   **World State:** Fetches `WorldState` data for the guild.
        *   **Character Context:** Gathers details for the primary character involved (stats, skills, inventory, quests, status effects, party info).
        *   **Target Entity Context:** Can fetch similar details if a specific target entity (NPC, another Character) is provided.
        *   **Location Context:** Includes details about the current or target location, including Points of Interest (PoIs).
        *   **Event Context:** Can fetch details for an ongoing event.
        *   **Relationship Context:** Includes relationship data between the primary character and a target entity.
        *   **Lore Context:** The `_get_dynamic_lore_snippets` method aims to fetch relevant lore.
        *   **Game Terms Dictionary:** Provides definitions for game-specific terms, skills, abilities, etc.
        *   **Party Context:** Includes average party level and member details if the character is in a party.
*   **Lore Manager Dependency:**
    *   The effectiveness of lore inclusion via `_get_dynamic_lore_snippets` is heavily dependent on the full implementation of `LoreManager`.
    *   Currently, `LoreManager` (as per its initial plan/implementation) primarily loads lore from static files or `WorldState.custom_flags.embedded_lore_entries`. For truly dynamic and contextually relevant lore snippets based on evolving gameplay (e.g., from `StoryLog`), `LoreManager` would need further enhancements (e.g., Task 33.B - Querying Lore). This is a known dependency for optimal lore context.
*   **Guild-Scoped Data Fetching:**
    *   All data fetching operations within `PromptContextCollector` are correctly guild-scoped, ensuring that context is relevant to the specific guild where content generation is requested. This is achieved by passing `guild_id` to underlying managers and database queries.

*   **Conclusion for `PromptContextCollector`:**
    *   The module is largely adequate and provides a comprehensive set of data for AI prompt generation as required by Task 2.2.
    *   The main dependency for enhancing lore context is the full implementation of `LoreManager`'s dynamic querying capabilities.

## 2. `MultilingualPromptGenerator.prepare_ai_prompt` Review (Subtask A.2.2.2)

The `MultilingualPromptGenerator` and its method `prepare_ai_prompt(self, generation_type: str, context: GenerationContext, player_id: Optional[str] = None, target_languages: Optional[List[str]] = None, **kwargs)` were reviewed.

*   **Parameter Sufficiency:**
    *   The method accepts `generation_type` (e.g., "location_description", "npc_dialogue", "quest_idea") and the comprehensive `GenerationContext` object from `PromptContextCollector`.
    *   It also takes `target_languages` to instruct the AI on desired output languages.
    *   These parameters are generally sufficient for constructing varied and contextually rich prompts.

*   **Key Refinement - `player_id` to `character_id`:**
    *   **Current Parameter:** `player_id: Optional[str]`.
    *   **Needed Change:** This parameter should be changed to `character_id: Optional[str]`.
    *   **Reasoning:**
        *   The `PromptContextCollector.get_full_context` method (which `prepare_ai_prompt` would typically call or have its output passed to) uses `character_id` as its primary parameter for fetching player-character-specific context (like skills, stats, active quests, current location).
        *   Using `player_id` (which represents the Discord user's account, not their in-game avatar) at this stage can lead to ambiguity if a player has multiple characters or if the distinction is not clearly handled when fetching context.
        *   To ensure the AI prompt is built around the correct in-game entity performing an action or being the subject of generation, `character_id` is the more precise identifier.
        *   While `PromptContextCollector` can derive `character_id` from `player_id` (by fetching the player's active character), making `character_id` the direct parameter in `prepare_ai_prompt` simplifies the interface and makes the intent clearer, especially if this method is called from various places some ofwhich might already have `character_id`.
        *   This change aligns the `prepare_ai_prompt` interface more closely with the data requirements of `PromptContextCollector` for character-centric contexts.

*   **Return Type:**
    *   The method currently returns a `str` which is the final "user-facing" part of the prompt for the AI.
    *   Internally, it constructs both a system prompt and a user prompt. For the purpose of Task 2.2's API signature (which expects the final prompt string), this is adequate. The full system/user pair is available within the method if needed for other uses.

*   **Multilingual Output Handling:**
    *   The generator correctly uses `target_languages` from the `GenerationContext` (if not overridden by the direct parameter) to instruct the AI to provide outputs (e.g., `name_i18n`, `description_i18n`) in multiple languages within the generated JSON structures. This is a key feature and functions as intended.

*   **Conclusion for `MultilingualPromptGenerator.prepare_ai_prompt`:**
    *   The method is fundamentally sound for its purpose.
    *   The primary refinement needed is to change the `player_id` parameter to `character_id` to ensure precise context gathering for the character involved in the generation request.

## 3. Overall Adequacy for Task 2.2

*   The existing modules, `PromptContextCollector` and `MultilingualPromptGenerator`, provide a strong and largely adequate foundation for the AI prompt preparation requirements of Task 2.2.
*   **Key Action Items for Full Preparedness:**
    1.  **Refactor `MultilingualPromptGenerator.prepare_ai_prompt`**: Change the `player_id: Optional[str]` parameter to `character_id: Optional[str]`. Ensure all internal logic and calls to `PromptContextCollector` are updated to use `character_id` when character-specific context is needed.
    2.  **Full `LoreManager` Implementation**: The completion of `LoreManager`'s dynamic lore fetching capabilities (beyond static files/embedded lore) is crucial for providing rich and contextually relevant lore snippets to the AI. This is an external dependency but impacts the quality of context.

With these refinements and dependencies addressed, these modules will effectively support Task 2.2.
