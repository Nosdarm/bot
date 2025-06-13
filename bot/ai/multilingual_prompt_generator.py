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
    ):
        self.context_collector = context_collector
        self.main_bot_language = main_bot_language


    def update_main_bot_language(self, new_language: str) -> None:
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
        system_prompt = self._get_base_system_prompt(target_languages=generation_context.target_languages)
        try:
            context_json_string = generation_context.model_dump_json(indent=2, exclude_none=True)
        except AttributeError:
            context_dict = generation_context.dict(exclude_none=True)
            context_json_string = json.dumps(context_dict, ensure_ascii=False, indent=2)
        except TypeError as e:
            print(f"Error serializing GenerationContext (TypeError): {e}. Context type: {type(generation_context)}")
            context_json_string = json.dumps({ "error": "context_serialization_failed_type_error", "detail": str(e) }, indent=2)
        except Exception as e_unknown:
            print(f"Unknown error serializing GenerationContext: {e_unknown}. Context type: {type(generation_context)}")
            context_json_string = json.dumps({ "error": "unknown_context_serialization_failed", "detail": str(e_unknown) }, indent=2)

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
        # ... (NPC prompt remains unchanged from previous state)
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
        quest_idea = generation_context.request_params.get("quest_idea", "a generic quest")
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(generation_context.target_languages)))])

        task_prompt = f"""
Design a complete, structured JSON quest based on the following idea:
Quest Idea/Trigger: {quest_idea}

The JSON quest structure MUST include:
- `name_i18n`: {{{lang_example_str}}} (multilingual title for the quest, also accept `title_i18n` as an alias).
- `description_i18n`: {{{lang_example_str}}} (multilingual description outlining the quest premise).
- `suggested_level`: Optional integer (appropriate player level, scaled using `player_context.level_info` and `scaling_parameters`).
- `guild_id`: Optional string (if applicable, the guild associated with this quest).
- `influence_level`: Optional string (e.g., "local", "regional", "global").
- `quest_giver_id`: Optional string (ID of an NPC from `game_terms_dictionary` or `faction_data` that gives the quest).
- `quest_giver_details_i18n`: Optional {{{lang_example_str}}} (multilingual details about the quest giver if not a known NPC).
- `npc_involvement`: Optional dictionary (e.g., `{{"key_npc_id": "npc_wizard_eldron", "role_in_quest": "informant"}}`).
- `steps`: An array of step objects. Each step object MUST conform to the following structure:
    - `title_i18n`: {{{lang_example_str}}} (multilingual title for the step).
    - `description_i18n`: {{{lang_example_str}}} (multilingual description of what the player needs to do for this step).
    - `step_order`: integer (sequential order of the step, starting from 0 or 1).
    - `required_mechanics_json`: string (A valid JSON string detailing specific, concrete game mechanic requirements for this step. Examples: `{{"action": "PLAYER_KILL_NPC", "npc_id": "goblin_scout", "quantity": 3}}`, `{{"action": "PLAYER_ACQUIRE_ITEM", "item_id": "lost_amulet", "quantity": 1}}`, `{{"action": "PLAYER_USE_SKILL", "skill_id": "lockpicking", "target_id": "chest_001", "dc": 15}}`. The structure of this JSON will be interpreted by the game's rule engine. The structure and content of this JSON should be guided by the game's internal rule system (ref: rules 14/45).).
    - `abstract_goal_json`: string (A valid JSON string for more complex, less strictly defined goals that might require narrative judgment or broader log analysis. Examples: `{{"goal": "BEFRIEND_NPC", "npc_id": "merchant_elara"}}`, `{{"goal": "SECURE_AREA", "location_id": "old_watchtower"}}`, `{{"goal": "DELIVER_MESSAGE_TO_NPC", "npc_id": "captain_valerius", "message_summary_i18n": {lang_example_str} }} `. This will be interpreted by a rule engine or another LLM. The structure and content of this JSON should be guided by the game's internal rule system (ref: rules 14/45).).
    - `consequences_json`: string (A valid JSON string for step-specific consequences/rewards upon its completion. Example: `{{"grant_xp": 50, "grant_items": [{{"item_id": "minor_potion_healing", "quantity": 2}}], "spawn_npc": {{ "npc_id": "grateful_child", "location_id": "current" }} }}`. The structure and content of this JSON should be guided by the game's internal rule system (ref: rules 14/45).).
    - `assignee_type`: Optional string (e.g., "player", "party").
    - `assignee_id`: Optional string (player_id or party_id, if applicable).
- `prerequisites_json`: string (A valid JSON string describing conditions that must be met before this quest can start. Example: `{{"quests_completed": ["quest_intro_001"], "min_level": 5, "faction_reputation": {{"faction_id": "town_guard", "min_standing": "neutral"}}}}`. The structure and content of this JSON should be guided by the game's internal rule system (ref: rules 14/45).).
- `consequences_json`: string (A valid JSON string describing overall quest outcomes upon final completion or failure. Example: `{{"on_complete": {{ "grant_xp": 500, "grant_gold": 100, "reputation_change": [{{"faction_id": "merchant_guild", "change": 25}}] }}, "on_fail": {{ "reputation_change": [{{"faction_id": "merchant_guild", "change": -10}}] }} }}`. The structure and content of this JSON should be guided by the game's internal rule system (ref: rules 14/45).).
- `consequences_summary_i18n`: Optional {{{lang_example_str}}} (multilingual summary of overall quest consequences).

CRITICAL INSTRUCTIONS:
1.  All `*_json` fields (e.g., `required_mechanics_json`, `abstract_goal_json`, `consequences_json`, `prerequisites_json`) MUST be valid JSON strings. Their internal structure should be a JSON object or array as appropriate for the data they represent.
2.  Use `game_terms_dictionary` from `<game_context>` for all entity IDs (NPCs, items, locations, skills, abilities, factions).
3.  Scale `suggested_level`, XP, gold, and item rewards (within step or quest consequences) according to `scaling_parameters` and `player_context` in `<game_context>`.
4.  All textual fields (titles, descriptions, summaries) MUST be in the specified multilingual JSON format: {{{lang_example_str}}}.
5.  The entire output must be a single JSON object representing the quest. Do not include any text outside this JSON object.
"""
        return self._build_full_prompt_for_openai(task_prompt, generation_context)

    def generate_item_description_prompt(self, generation_context: GenerationContext) -> Dict[str, str]:
        # ... (Item prompt remains unchanged from previous state)
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
        # ... (Location prompt remains unchanged from previous state)
        location_idea = generation_context.request_params.get("location_idea", "a generic location")
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


