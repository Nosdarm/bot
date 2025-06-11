# bot/ai/multilingual_prompt_generator.py

import json
from typing import TYPE_CHECKING, Dict, Any, List, Optional

from bot.ai.ai_data_models import GenerationContext, ParsedAiData, ValidationError, ValidatedEntity, ValidationIssue

if TYPE_CHECKING:
    from bot.ai.prompt_context_collector import PromptContextCollector

class MultilingualPromptGenerator:
    def __init__(
        self,
        context_collector: 'PromptContextCollector',
        main_bot_language: str, # e.g., "ru", "en"
        # Potentially OpenAIService if it's used directly for some reason, though likely not.
    ):
        self.context_collector = context_collector
        # main_bot_language and target_languages will now be primarily sourced from GenerationContext
        # However, keeping main_bot_language might be useful for methods not directly using GenerationContext
        # or as a default if GenerationContext isn't fully populated.
        self.main_bot_language = main_bot_language


    def update_main_bot_language(self, new_language: str) -> None:
        """Updates the main bot language used for prompt generation."""
        self.main_bot_language = new_language
        print(f"MultilingualPromptGenerator: Main bot language updated to '{new_language}'.")


    def _get_base_system_prompt(self, target_languages: List[str]) -> str:
        unique_sorted_languages = sorted(list(set(target_languages)))
        lang_fields_example = ", ".join([f'"{lang}": "..."' for lang in unique_sorted_languages])

        return f"""You are a helpful assistant for a text-based RPG.
Generate ALL user-facing textual content (names, descriptions, dialogues, quest text, item properties, etc.)
in a JSON structure with keys for each target language.
The required language fields are: {{{lang_fields_example}}}.
For example, a name field must be structured as: {{"name_i18n": {{{lang_fields_example}}}}}.
Apply this multilingual JSON format strictly to ALL text meant for the user.

You MUST use the provided `<game_context>` data extensively.
Inside the `<game_context>`, pay special attention to:
- `game_terms_dictionary`: Use this for correct naming, IDs, and understanding of game elements (stats, skills, items, NPCs, locations, etc.).
- `scaling_parameters`: Use these, along with any player-specific context (like `player_context.level_info` if available), to determine appropriate values for stats, rewards, difficulty, prices, etc.
- `lore_snippets`, `world_state`, `faction_data`, `relationship_data`, `active_quests_summary` for situational awareness.

Content should be creative, engaging, and consistent with a fantasy RPG setting.
Output only the requested JSON object, without any additional explanatory text before or after the JSON.
"""

    def _build_full_prompt_for_openai(self, specific_task_prompt: str, generation_context: GenerationContext) -> Dict[str, str]:
        """
        Combines the base system prompt, specific task prompt, and context into a format
        suitable for an OpenAI API call (system and user messages).
        Context data is stringified as JSON to be included in the user prompt.
        """
        system_prompt = self._get_base_system_prompt(target_languages=generation_context.target_languages)

        # Serialize the rich context data into a JSON string to be part of the user prompt
        try:
            # Try Pydantic v2 method first
            context_json_string = generation_context.model_dump_json(indent=2, exclude_none=True)
        except AttributeError:
            # Fallback to Pydantic v1 method
            context_dict = generation_context.dict(exclude_none=True)
            context_json_string = json.dumps(context_dict, ensure_ascii=False, indent=2)
        except TypeError as e:
            # Handle cases where the object might not be a Pydantic model or other TypeError during serialization
            print(f"Error serializing GenerationContext (TypeError): {e}. Context type: {type(generation_context)}")
            context_json_string = json.dumps({
                "error": "context_serialization_failed_type_error",
                "detail": str(e),
                "message": "Problematic GenerationContext data was omitted from the prompt."
            }, indent=2)
        except Exception as e_unknown:
            # Catch any other unexpected error during serialization
            print(f"Unknown error serializing GenerationContext: {e_unknown}. Context type: {type(generation_context)}")
            context_json_string = json.dumps({
                "error": "unknown_context_serialization_failed",
                "detail": str(e_unknown),
                "message": "Problematic GenerationContext data was omitted due to an unknown error."
            }, indent=2)

        user_prompt = f"""
Here is the current game context:
<game_context>
{context_json_string}
</game_context>

Based on this context, please perform the following task:
<task>
{specific_task_prompt}
</task>
"""
        return {"system": system_prompt, "user": user_prompt}

    def generate_npc_profile_prompt(self, generation_context: GenerationContext) -> Dict[str, str]:
        npc_id_idea = generation_context.request_params.get("npc_id_idea", "a generic NPC")

        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(generation_context.target_languages)))])

        task_prompt = f"""
Generate a complete JSON profile for a new NPC.
NPC Identifier/Concept: {npc_id_idea}

The JSON profile MUST include the following fields:
- `template_id`: string (a unique template ID for this NPC, e.g., "npc_wizard_frost_001", "npc_bandit_chief_generic").
- `name_i18n`: {{{lang_example_str}}} (multilingual name).
- `role_i18n`: {{{lang_example_str}}} (multilingual role, e.g., "Mysterious Sorcerer", "Gruff Mercenary Captain").
- `archetype`: string (a specific archetype, e.g., "mage_ice", "warrior_tank", "rogue_assassin"; use/derive from `game_terms_dictionary` if specific archetypes are listed there).
- `backstory_i18n`: {{{lang_example_str}}} (multilingual detailed backstory).
- `personality_i18n`: {{{lang_example_str}}} (multilingual personality traits).
- `motivation_i18n`: {{{lang_example_str}}} (multilingual motivations and goals).
- `visual_description_i18n`: {{{lang_example_str}}} (multilingual detailed visual appearance).
- `dialogue_hints_i18n`: {{{lang_example_str}}} (multilingual sample dialogue lines or style hints).
- `stats`: A dictionary. Populate with stat names/IDs found in `game_terms_dictionary` (where `term_type` is 'stat'). Values MUST be determined based on the NPC's role, archetype, and relevant `scaling_parameters` from the `<game_context>` (considering `player_context.level_info` if provided). Example: {{"strength": 12, "dexterity": 10}} (use actual stat IDs from `game_terms_dictionary`).
- `skills`: A dictionary. Populate with skill names/IDs from `game_terms_dictionary` (where `term_type` is 'skill'). Values MUST be scaled similarly to stats. Example: {{"stealth": 45, "persuasion": 60}} (use actual skill IDs).
- `abilities`: Optional list of ability IDs (strings) from `game_terms_dictionary` (where `term_type` is 'ability'). Select appropriate abilities based on role and archetype.
- `spells`: Optional list of spell IDs (strings) from `game_terms_dictionary` (where `term_type` is 'spell'). Select appropriate spells.
- `inventory`: Optional list of objects, each with `item_template_id` (must be an ID from `game_terms_dictionary` where `term_type` is 'item_template') and `quantity`. Scale quantity and quality/type of items based on `scaling_parameters` and NPC role.
- `faction_affiliations`: Optional list of objects, each with `faction_id` (use known faction IDs from `game_terms_dictionary` or `faction_data` in context if available, or generate new plausible ones if necessary) and `rank_i18n`: {{{lang_example_str}}}.
- `relationships`: Optional list of objects, each with `target_entity_id` (can be an ID from `game_terms_dictionary` for existing entities, or a newly generated placeholder ID for a new related NPC), `relationship_type` (e.g., "friendly", "hostile", "neutral"), and `strength` (numeric value, e.g., from -100 to 100).

CRITICAL INSTRUCTIONS:
1.  Refer to `game_terms_dictionary` in the `<game_context>` for valid IDs and names of stats, skills, abilities, spells, item templates.
2.  Adhere strictly to `scaling_parameters` and `player_context` from `<game_context>` to determine appropriate values for all numerical properties (stats, skill levels, quantity/quality of inventory, etc.), ensuring the NPC is balanced for the given context.
3.  All textual fields (names, descriptions, roles, etc.) MUST be in the specified multilingual JSON format: {{{lang_example_str}}}.
4.  The entire output must be a single JSON object representing the NPC profile. Do not include any text outside this JSON object.
"""
        return self._build_full_prompt_for_openai(task_prompt, generation_context)

    def generate_quest_prompt(self, generation_context: GenerationContext) -> Dict[str, str]:
        """Generates a prompt to create a structured quest."""
        quest_idea = generation_context.request_params.get("quest_idea", "a generic quest")
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(generation_context.target_languages)))])

        task_prompt = f"""
Design a complete, structured JSON quest based on the following idea:
Quest Idea/Trigger: {quest_idea}

The JSON quest structure MUST include:
- `template_id`: string (a unique template ID for this quest, e.g., "quest_rescue_merchant_001").
- `title_i18n`: {{{lang_example_str}}} (multilingual title).
- `description_i18n`: {{{lang_example_str}}} (multilingual description outlining the premise).
- `suggested_level`: integer (appropriate for the player level, scaled using `player_context.level_info` and `scaling_parameters` from `<game_context>`).
- `quest_giver_id`: Optional string (ID of an NPC from `game_terms_dictionary` or `faction_data` that gives the quest. If a new NPC, ensure it's also generated or referenced).
- `stages`: An array of stage objects, each having:
    - `stage_id`: string (unique identifier for the stage, e.g., "stage_1_find_clues").
    - `title_i18n`: {{{lang_example_str}}} (multilingual title for the stage).
    - `description_i18n`: {{{lang_example_str}}} (multilingual description of what the player needs to do for this stage).
    - `objectives`: An array of objective objects, each with:
        - `objective_id`: string (e.g., "obj_1_1_kill_bandits")
        - `description_i18n`: {{{lang_example_str}}} (multilingual detailing of conditions, e.g., "Defeat the 3 goblin lookouts").
        - `type`: string (e.g., "kill", "collect", "goto", "talk", "use_skill", "event_trigger"; use types from `game_terms_dictionary` if available).
        - `target_id`: Optional string (e.g., specific NPC ID, item template ID, location ID from `game_terms_dictionary`).
        - `quantity`: Optional integer (if applicable).
        - `skill_check`: Optional object (e.g., `{{"skill_id": "lockpicking", "dc": 15, "description_i18n": {{{lang_example_str}}} }}`; skill_id must be from `game_terms_dictionary`).
    - `alternative_solutions_i18n`: Optional {{{lang_example_str}}} (multilingual description of other ways to complete the stage).
- `prerequisites`: Optional list of quest template IDs (from `game_terms_dictionary` or previously generated quests) that must be completed before this quest can start.
- `consequences`: Optional object describing outcomes:
    - `description_i18n`: {{{lang_example_str}}} (multilingual summary of consequences).
    - `world_state_changes`: Optional list of objects defining changes to the world state (e.g., `[{{"type": "location_state_change", "location_id": "loc_town_01", "new_state_key": "destroyed"}}]`).
    - `relationship_changes`: Optional list of objects defining changes to NPC/faction relationships (e.g., `[{{"target_id": "faction_villagers", "change_amount": 20, "type": "faction"}}]`).
- `rewards`: object containing:
    - `experience_points`: integer (scaled using `scaling_parameters` and `player_context`).
    - `gold`: integer (scaled similarly).
    - `items`: Optional list of objects, each with `item_template_id` (from `game_terms_dictionary`) and `quantity` (scaled).
    - `ability_unlocks`: Optional list of ability IDs (from `game_terms_dictionary`).

CRITICAL INSTRUCTIONS:
1.  Use `game_terms_dictionary` from `<game_context>` for all entity IDs (NPCs, items, locations, skills, abilities).
2.  Scale `suggested_level`, XP, gold, and item rewards according to `scaling_parameters` and `player_context` in `<game_context>`.
3.  All textual fields MUST be in the specified multilingual JSON format: {{{lang_example_str}}}.
4.  The entire output must be a single JSON object representing the quest. Do not include any text outside this JSON object.
"""
        return self._build_full_prompt_for_openai(task_prompt, generation_context)

    def generate_item_description_prompt(self, generation_context: GenerationContext) -> Dict[str, str]:
        """Generates a prompt for item name, description, and properties."""
        item_idea = generation_context.request_params.get("item_idea", "a generic item")
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(generation_context.target_languages)))])

        task_prompt = f"""
Generate a complete JSON profile for a new game item based on the following idea:
Item Idea/Keywords: {item_idea}

The JSON item profile MUST include:
- `template_id`: string (a unique template ID, e.g., "item_sword_flaming_001", "item_potion_healing_greater").
- `name_i18n`: {{{lang_example_str}}} (multilingual name).
- `description_i18n`: {{{lang_example_str}}} (multilingual description, including lore or flavor text).
- `item_type`: string (e.g., "weapon", "armor", "potion", "ring", "quest_item", "resource"; use types from `game_terms_dictionary` if item types are listed, otherwise use common RPG types).
- `rarity`: string (e.g., "common", "uncommon", "rare", "epic", "legendary"; scaled based on `scaling_parameters`).
- `properties_i18n`: A dictionary of key-value pairs. Property keys should be standardized (e.g., "damage", "armor_class", "healing_amount", "attribute_bonus_strength"). Values for textual properties (like effect descriptions) MUST be multilingual {{{lang_example_str}}}. Numerical values MUST be scaled using `scaling_parameters` from `<game_context>`. Example: `{{"damage": "1d8+2", "effect_i18n": {{{{"en": "Grants +5 to Strength for 1 minute", "ru": "Дает +5 к Силе на 1 минуту"}}}} }}`.
- `value`: integer (estimated gold value, scaled using `scaling_parameters` and item rarity/power).
- `weight`: float (item weight).
- `stackable`: boolean (can the item be stacked in inventory?).
- `icon`: string (suggest an emoji or a descriptive keyword for an icon, e.g., "⚔️", "shield_icon", "red_potion_ bubbling").
- `equipable_slot`: Optional string (e.g., "weapon_hand", "armor_chest", "finger"; use slots from `game_terms_dictionary` if available).
- `requirements`: Optional object (e.g., `{{"level": 5, "strength": 12}}`; use stat/skill IDs from `game_terms_dictionary`).

CRITICAL INSTRUCTIONS:
1.  Use `game_terms_dictionary` from `<game_context>` for `item_type` (if defined there), `equipable_slot` (if defined), and any stat/skill IDs used in `requirements` or `properties_i18n`.
2.  Scale `value`, `rarity`, and numerical values in `properties_i18n` according to `scaling_parameters` and `player_context` (if available) from `<game_context>`.
3.  All textual fields (names, descriptions, property effects) MUST be in the specified multilingual JSON format: {{{lang_example_str}}}.
4.  The entire output must be a single JSON object representing the item profile. Do not include any text outside this JSON object.
"""
        return self._build_full_prompt_for_openai(task_prompt, generation_context)

    def generate_location_description_prompt(self, generation_context: GenerationContext) -> Dict[str, str]:
        """Generates a prompt for an atmospheric location description and potential new connections."""
        location_idea = generation_context.request_params.get("location_idea", "a generic location")
        # existing_location_id = generation_context.request_params.get("existing_location_id") # If needed for context fetching strategy
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(generation_context.target_languages)))])

        task_prompt = f"""
Generate a JSON object describing a game location based on the following idea:
Location Idea/Current Location ID (if updating): {location_idea}

The JSON output MUST include:
- `template_id`: string (a unique template ID for this location, e.g., "loc_haunted_forest_001", "loc_market_district_capital").
- `name_i18n`: {{{lang_example_str}}} (multilingual name of the location).
- `atmospheric_description_i18n`: {{{lang_example_str}}} (multilingual, rich and evocative description focusing on sights, sounds, smells, and overall mood. Incorporate elements from `lore_snippets` and `world_state` from `<game_context>` if relevant).
- `points_of_interest`: Optional list of objects, each describing a point of interest within the location:
    - `poi_id`: string (unique ID for the PoI, e.g., "poi_ancient_shrine_01").
    - `name_i18n`: {{{lang_example_str}}} (multilingual name of the PoI).
    - `description_i18n`: {{{lang_example_str}}} (multilingual description of the PoI).
    - `contained_item_ids`: Optional list of item template IDs (from `game_terms_dictionary`) that might be found here (scaled by `scaling_parameters`).
    - `npc_ids`: Optional list of NPC template IDs (from `game_terms_dictionary` or `faction_data`) present at this PoI.
- `connections`: Optional list of objects describing connections to other locations:
    - `to_location_id`: string (ID of a connected location from `game_terms_dictionary`, or a placeholder for a new one).
    - `path_description_i18n`: {{{lang_example_str}}} (multilingual description of the path).
    - `travel_time_hours`: Optional integer (estimated travel time).
- `possible_events_i18n`: Optional list of brief descriptions for events that could occur here: `[{{{lang_example_str}}}, ...]`
- `required_access_items_ids`: Optional list of item template IDs (from `game_terms_dictionary`) needed to enter this location.

CRITICAL INSTRUCTIONS:
1.  Use `game_terms_dictionary` from `<game_context>` for any referenced entity IDs (items, NPCs, other locations).
2.  If suggesting items or encounters (via PoIs or events), ensure they are appropriate for the location's theme and consider `scaling_parameters` from `<game_context>`.
3.  All textual fields MUST be in the specified multilingual JSON format: {{{lang_example_str}}}.
4.  The entire output must be a single JSON object. Do not include any text outside this JSON object.
"""
        return self._build_full_prompt_for_openai(task_prompt, generation_context)
