# AI Response Validation Guide

This document outlines the strategies and mechanisms for validating responses received from the AI language model, ensuring data integrity and consistency within the game.

## 1. Overview

AI-generated content, while powerful, can sometimes be unpredictable or not strictly adhere to defined data structures or game rules. The `AIResponseValidator` class (`bot/ai/ai_response_validator.py`) plays a crucial role in parsing the raw AI output (expected to be JSON) and validating it against Pydantic models and semantic game rules. Its goal is to identify issues and, where safe and appropriate, perform minor auto-corrections to improve data usability.

## 2. Validation Layers

Validation occurs in multiple layers:

*   **JSON Parsing:** The initial step is to ensure the AI output is a valid JSON string. Errors at this stage are critical and usually prevent further processing.
*   **Pydantic Model Validation (Structural & Type Validation):**
    *   The parsed JSON data is validated against predefined Pydantic models (defined in `bot/ai/ai_data_models.py`) corresponding to the `request_type` (e.g., `GeneratedLocationContent`, `GeneratedNpcProfile`, `GeneratedQuestData`, `GeneratedItemProfile`).
    *   This layer checks for:
        *   Correct field names and data types (e.g., string, integer, boolean, list, dict).
        *   Presence of required fields.
        *   Adherence to basic constraints (e.g., string length, number ranges if defined in Pydantic).
    *   Pydantic's built-in validators and custom validators within the models handle these checks.
*   **Internationalization (i18n) Field Validation:** A specific type of Pydantic validation focused on fields ending with `_i18n`. (Details in Section 4).
*   **Semantic Validation:** After structural validation passes, further semantic checks ensure the data makes sense within the game world's context and rules. (Details in Section 5).

## 3. `ValidationIssue` Model

All validation problems, whether from Pydantic or semantic checks, are standardized into `ValidationIssue` objects. This provides a consistent way to report issues. Each `ValidationIssue` typically includes:

*   `loc`: A path (list of strings/integers) to the problematic field (e.g., `["stats", "strength"]` or `["points_of_interest", 0, "name_i18n"]`).
*   `type`: A code for the type of error (e.g., `json_decode_error`, `value_error.integer`, `semantic.id_not_found`, `semantic.stat_out_of_range`, `i18n.missing_required_language`).
*   `msg`: A human-readable error message describing the issue.
*   `input_value`: The actual value that caused the validation to fail.
*   `severity`:
    *   `"error"`: Typically for Pydantic/structural issues or severe semantic issues that make the data unusable or unsafe to apply directly.
    *   `"warning"`: For semantic issues where the data might be usable but is flagged for review, or if an auto-correction was made that the GM should be aware of.
    *   `"info"`: For informational messages, often related to auto-corrections or minor deviations.
*   `suggestion`: Optional hint on how to fix the issue or what the validator did.

## 4. Internationalization (i18n) Field Validation

Fields an_i18n` (e.g., `name_i18n`, `description_i18n`) are expected to be JSON objects containing multiple language translations for a piece of text. Their validation is primarily handled by the `validate_i18n_field` Pydantic helper function (defined in or imported by `bot/ai/ai_data_models.py`).

*   **Core Requirements Checked by `validate_i18n_field`:**
    1.  **Non-Empty Dictionary:** The field must be a dictionary and not empty.
    2.  **Target Languages Presence:** It ensures that all `target_languages` specified in the `GenerationContext` (typically the guild's main language and English as a fallback) are present as keys in the i18n dictionary.
    3.  **Non-Empty String Values:** The text for each target language must be a non-empty string after stripping whitespace.
*   **Fallback Mechanism:**
    *   If the primary target language (e.g., guild's default like 'ru') is missing or empty, but English ('en') is present and valid, the English text is copied to the primary target language field.
    *   Conversely, if English is missing or empty but the primary target language is present and valid, its text is copied to 'en'.
    *   This ensures that at least the essential languages have content if possible.
*   **Error Handling:**
    *   If, after fallbacks, any of the `target_languages` still lack valid, non-empty text, a `ValueError` is raised by the Pydantic validator. This results in a `ValidationIssue` with a type like `value_error.i18n.missing_required_language`.
*   **Purpose:** This validation strategy ensures that all essential internationalized texts are available for the game's configured languages, maintaining a good user experience across different language settings.

## 5. Semantic Validation Details

Semantic validation is performed by helper methods within `AIResponseValidator` (e.g., `_semantic_validate_npc_profile`, `_semantic_validate_item_profile`) after Pydantic model validation succeeds. These checks ensure game-specific rules and references are respected. All semantic checks are guild-aware, using the `guild_id` and `GameManager` instance to fetch relevant `RuleConfig` entries or game terms.

*   **ID Reference Checks (`_check_id_in_terms`):**
    *   This utility function is used across various semantic validators.
    *   **Function:** It verifies if a given `entity_id` (e.g., a skill ID like "mining" in an NPC's skills list, an item template ID in an inventory) exists as a known term of an `expected_term_type` (e.g., "skill", "item_template") within the `game_terms` dictionary (provided by `PromptContextCollector`).
    *   **Issue Generation:** If an ID is not found or does not match the expected type, a `ValidationIssue` with `type="semantic.invalid_id_reference"` and `severity="warning"` is generated. This flags potentially incorrect or hallucinated IDs by the AI.

*   **NPC Profile Validation (`_semantic_validate_npc_profile`):**
    *   **Stat ID Validation:** Uses `_check_id_in_terms` to verify that all keys in the `stats` dictionary (e.g., "strength", "dexterity") are valid stat types.
    *   **Skill/Ability/Spell ID Validation:** Uses `_check_id_in_terms` for IDs listed in `skills`, `abilities`, and `spells`.
    *   **Inventory Item ID Validation:** Uses `_check_id_in_terms` for `item_template_id` within each inventory entry.
    *   **Faction Affiliation ID Validation:** Uses `_check_id_in_terms` for `faction_id` in `faction_affiliations`.
    *   **Archetype ID Validation:** Uses `_check_id_in_terms` for the NPC's `archetype`.
    *   **Stat Value Range Validation:**
        *   Compares generated numerical stat values against min/max ranges defined in `RuleConfig`.
        *   It first looks for ranges specific to the NPC's `archetype` (e.g., from `npc_stat_ranges.<archetype>.<stat_key>`).
        *   If no archetype-specific range is found, it checks for global limits (e.g., from `npc_global_stat_limits.<stat_key>`).
        *   If a stat value is outside these bounds, a `ValidationIssue` (e.g., `type="semantic.stat_out_of_range.min"`, `severity="warning"`) is generated. This may also trigger auto-correction as per Section 6.

*   **Item Profile Validation (`_semantic_validate_item_profile`):**
    *   **Property ID Validation:** If `properties_json` contains references like `grants_skill` or `grants_ability`, their IDs are validated using `_check_id_in_terms`.
    *   **Base Value Range Validation:**
        *   Compares the item's `base_value` against min/max ranges defined in `RuleConfig` under `item_value_ranges`.
        *   These ranges are typically structured by `item_type` (e.g., "weapon", "potion") and `rarity_tag` (e.g., "common", "rare").
        *   If the `base_value` is outside these bounds, a `ValidationIssue` (e.g., `type="semantic.value_out_of_range.min"`, `severity="warning"`) is generated. This may also trigger auto-correction.

*   **Quest Data Validation (`_semantic_validate_quest_data`):**
    *   **NPC Involvement:** Validates NPC IDs referenced in `npc_involvement` using `_check_id_in_terms` (expecting "npc_archetype" or actual NPC IDs if context allows).
    *   **Item ID Validation (in Rewards/Prerequisites):** If `rewards_json` or `prerequisites_json` are stringified JSON containing item lists, it attempts to parse them and validate any `item_id`s using `_check_id_in_terms`.
    *   **Step Structure:** Basic checks for presence of essential fields in quest steps can be added (e.g., ensuring each step has a description). More complex validation of `required_mechanics_json` might be added later.

*   **Location Content Validation (`_semantic_validate_location_content`):**
    *   **PoI Content:** Validates `item_template_id`s in `contained_item_ids` (if used) or `npc_archetype_id`s in `npc_archetypes_to_spawn` (if used) within Points of Interest, using `_check_id_in_terms`.
    *   **Connections:** Checks if `to_location_id` in `connections` refers to a known location template or instance ID from `game_terms`. Issues a `semantic.unknown_location_reference` warning if not.

## 6. Auto-Correction Strategy (MVP)

*(This section was created in the previous subtask A.2.3.3 and is retained here, fitting well after semantic validation)*

While the primary goal of the validator is to identify issues, simple and safe auto-corrections can improve the usability of AI-generated content, especially for minor deviations.

*   **Guiding Principles for Auto-Correction:**
    *   **Safety First:** Auto-corrections should only be applied when the intent is clear and the correction is highly likely to be what was intended or is a safe fallback.
    *   **Transparency:** Any auto-correction performed must be logged and reported, typically by generating a `ValidationIssue` with `severity="info"` or `severity="warning"` detailing the change.
    *   **MVP Scope:** For the initial implementation (MVP), auto-correction will be minimal and focus on easily definable, low-risk scenarios.

*   **MVP Auto-Correction Focus: Numerical Clamping**
    *   **NPC Stat Clamping:**
        *   **Scenario:** An AI-generated NPC stat (e.g., `strength`) is outside a defined min/max range specified in `RuleConfig`.
        *   **Mechanism:** The semantic validation logic in `_semantic_validate_npc_profile` (as described in Section 5) detects an out-of-bounds value. It then:
            1.  Modifies the value directly in the `data_dict` being validated, clamping it to the nearest valid boundary (min or max).
            2.  Generates a `ValidationIssue` with `severity="info"` or `severity="warning"` indicating that an auto-correction was performed.
    *   **Item Value Clamping:**
        *   **Scenario:** An AI-generated item's `base_value` is outside the expected range.
        *   **Mechanism:** Similar to stat clamping, `_semantic_validate_item_profile` (Section 5) clamps the value and generates an informational `ValidationIssue`.

*   **Threshold for Clamping:** For MVP, any value outside the hard min/max defined in `RuleConfig` is clamped to the boundary. More nuanced "slight deviation" logic can be added later if needed.

*   **Deferred Auto-Corrections:** More complex auto-corrections (e.g., fixing invalid ID references, structural rearrangements) are deferred for future enhancements.

This comprehensive validation approach ensures that AI-generated content is both structurally sound and semantically plausible within the game's defined rules and context.
