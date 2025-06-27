# bot/ai/multilingual_prompt_generator.py

import json
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Tuple

from bot.ai.ai_data_models import GenerationContext, ValidationIssue

from sqlalchemy.ext.asyncio import AsyncSession
from bot.database.models import GuildConfig, Location, WorldState, Player, GeneratedFaction, GeneratedNpc
from bot.database.crud_utils import get_entity_by_id, get_entity_by_attributes, get_entities


if TYPE_CHECKING:
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.game.managers.game_manager import GameManager

class MultilingualPromptGenerator:
    def __init__(
        self,
        context_collector: 'PromptContextCollector',
        main_bot_language: str,
        settings: Optional[Dict[str, Any]] = None
    ):
        self.context_collector = context_collector
        self.main_bot_language = main_bot_language
        self.settings = settings if settings else {}
        self.prompt_templates_config: Dict[str, Dict[str, Any]] = self.settings.get("prompt_templates", {})


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
        system_prompt = self._get_base_system_prompt(target_languages=generation_context.target_languages if generation_context and generation_context.target_languages else [self.main_bot_language, "en"])
        context_json_string = ""
        try:
            if generation_context and hasattr(generation_context, 'model_dump_json') and callable(generation_context.model_dump_json):
                context_json_string = generation_context.model_dump_json(indent=2, exclude_none=True)
            elif generation_context and hasattr(generation_context, 'dict') and callable(generation_context.dict):
                context_dict = generation_context.dict(exclude_none=True)
                context_json_string = json.dumps(context_dict, ensure_ascii=False, indent=2)
            elif isinstance(generation_context, dict):
                context_json_string = json.dumps(generation_context, ensure_ascii=False, indent=2)
            else:
                context_json_string = json.dumps({"error": "generation_context_is_none_or_invalid_type", "type": str(type(generation_context))}, indent=2)
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
        npc_id_idea = "a generic NPC"
        if generation_context and generation_context.request_params:
            npc_id_idea = generation_context.request_params.get("npc_id_idea", "a generic NPC")

        target_langs = generation_context.target_languages if generation_context and generation_context.target_languages else [self.main_bot_language, "en"]
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(target_langs)))])
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

TRADER-SPECIFIC INSTRUCTIONS (Apply if relevant for the NPC concept):
- If this NPC is a trader, include `"is_trader": true` in the root of the JSON profile.
- If `"is_trader": true`:
    - Populate the `inventory` field: This MUST be a list of item objects. Each item object MUST contain:
        - `item_template_id`: string (a valid item ID from `game_terms_dictionary` where `term_type` is 'item_template').
        - `quantity`: integer (the amount of this item the trader has in stock). This quantity should be scaled appropriately based on `scaling_parameters`, the trader's type (e.g., a small village shop vs. a large city emporium), and the item's rarity/value. Provide a varied and thematic assortment of goods. Prices will be determined by game rules based on these item template IDs and quantities.
    - Add a `currency_gold`: integer field to the root of the JSON profile (e.g., `"currency_gold": 500`). This represents the trader's starting cash on hand. Scale this amount using `scaling_parameters` and the trader's presumed wealth/scale of operation.
    - For `dialogue_hints_i18n`, include some trade-related phrases or topics. Examples: "Bargaining phrases", "Comments on item quality or rarity", "Mentions of new stock or items they are looking to buy", "Rumors about supply shortages or new trade routes".

CRITICAL INSTRUCTIONS:
1.  Refer to `game_terms_dictionary` in the `<game_context>` for valid IDs and names of stats, skills, abilities, spells, item templates.
2.  Adhere strictly to `scaling_parameters` and `player_context` from `<game_context>` to determine appropriate values for all numerical properties (stats, skill levels, quantity/quality of inventory, trader currency amounts, etc.), ensuring the NPC is balanced for the given context.
3.  All textual fields (names, descriptions, roles, etc.) MUST be in the specified multilingual JSON format: {{{lang_example_str}}}.
4.  The entire output must be a single JSON object representing the NPC profile. Do not include any text outside this JSON object.
"""
        return self._build_full_prompt_for_openai(task_prompt, generation_context)

    def generate_quest_prompt(self, generation_context: GenerationContext) -> Dict[str, str]:
        quest_idea = "a generic quest"
        if generation_context and generation_context.request_params:
            quest_idea = generation_context.request_params.get("quest_idea", "a generic quest")

        target_langs = generation_context.target_languages if generation_context and generation_context.target_languages else [self.main_bot_language, "en"]
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(target_langs)))])


        task_prompt = f"""
Design a complete, structured JSON quest based on the following idea:
Quest Idea/Trigger: {quest_idea}

The JSON quest structure MUST include the following fields, aligning with the `GeneratedQuest` Pydantic model:
- `name_i18n`: {{{lang_example_str}}} (Multilingual title for the quest. If you are more familiar with `title_i18n`, that is an acceptable alias for this field).
- `description_i18n`: {{{lang_example_str}}} (Multilingual description outlining the quest premise).
- `steps`: An array of step objects. Each step object MUST conform to the `GeneratedQuestStep` Pydantic model structure:
    - `title_i18n`: {{{lang_example_str}}} (Multilingual title for the step).
    - `description_i18n`: {{{lang_example_str}}} (Multilingual description of what the player needs to do for this step).
    - `step_order`: integer (Sequential order of the step, e.g., 0, 1, 2...).
    - `required_mechanics_json`: string (A valid JSON string detailing specific game mechanic requirements for this step. This string will be parsed as JSON. Example: `{{"action": "PLAYER_KILL_NPC", "npc_id": "goblin_scout", "quantity": 3}}`).
    - `abstract_goal_json`: string (A valid JSON string for more complex, narrative, or engine-interpreted goals. Example: `{{"goal": "DISCOVER_LOCATION", "location_id": "hidden_cave_01"}}`).
    - `consequences_json`: string (A valid JSON string for step-specific consequences or rewards upon its completion. Example: `{{"grant_xp": 50}}`).
    - `assignee_type`: Optional string (e.g., "player", "party"). Default is null or omit if not applicable.
    - `assignee_id`: Optional string (Player ID or Party ID, if `assignee_type` is set). Default is null or omit.
- `consequences_json`: string (A valid JSON string describing overall quest outcomes upon final completion or failure. Example: `{{"on_complete": {{ "grant_xp": 500, "grant_gold": 100}}, "on_fail": {{ "faction_reputation_change": [{{"faction_id": "thieves_guild", "change": -20}}] }} }}`).
- `prerequisites_json`: string (A valid JSON string describing conditions that must be met before this quest can start. Example: `{{"min_level": 5, "quests_completed": ["main_story_01"]}}`).

Optional fields for the main quest structure (include if relevant and sensible based on the quest idea and context):
- `guild_id`: Optional string (The ID of the guild this quest is primarily associated with. Use IDs from `game_terms_dictionary` or `faction_data` in context if a specific guild/faction is a quest giver or central to the quest).
- `influence_level`: Optional string (Describes the scope of the quest's impact, e.g., "local", "regional", "global", "faction_specific").
- `npc_involvement`: Optional dictionary (Describes key NPCs and their roles. Example: `{{"quest_giver_id": "npc_elder_maria", "target_npc_id": "npc_bandit_leader_grak", "informant_npc_id": "npc_shady_contact_01"}}`. Use NPC IDs from `game_terms_dictionary`).
- `quest_giver_details_i18n`: Optional {{{lang_example_str}}} (If the quest giver is not a predefined NPC, provide multilingual details here, like their appearance or role).
- `consequences_summary_i18n`: Optional {{{lang_example_str}}} (A brief multilingual summary of the overall quest consequences for the player).
- `suggested_level`: Optional integer (An appropriate player character level for this quest. Determine this by considering the `player_context.level` (if available) from the `<game_context>`, the quest's complexity, and `scaling_parameters`. If `player_context` is not available, use general `scaling_parameters` to suggest a reasonable level).


CRITICAL INSTRUCTIONS:
1.  All fields ending with `_json` (e.g., `required_mechanics_json`, `abstract_goal_json`, `consequences_json`, `prerequisites_json`) MUST contain valid JSON strings. The content of these strings should be JSON objects or arrays as appropriate for the data they represent.
2.  Use `game_terms_dictionary` from `<game_context>` for all entity IDs (NPCs, items, locations, skills, abilities, factions).
3.  Scale `suggested_level`, XP, gold, and item rewards (within step or quest consequences) according to `scaling_parameters` and `player_context` in `<game_context>`.
4.  All textual fields (titles, descriptions, summaries) MUST be in the specified multilingual JSON format: {{{lang_example_str}}}.
5.  The entire output must be a single JSON object representing the quest. Do not include any text outside this JSON object.
"""
        return self._build_full_prompt_for_openai(task_prompt, generation_context)

    def generate_item_description_prompt(self, generation_context: GenerationContext) -> Dict[str, str]:
        item_idea = "a generic item"
        if generation_context and generation_context.request_params:
            item_idea = generation_context.request_params.get("item_idea", "a generic item")

        target_langs = generation_context.target_languages if generation_context and generation_context.target_languages else [self.main_bot_language, "en"]
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(target_langs)))])
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
- `value`: integer (estimated gold value, scaled using `scaling_parameters` and item rarity/power. This value will be used as the item's `base_price` in economic calculations by the game rules.).
- `weight`: float (item weight).
- `stackable`: boolean (can the item be stacked in inventory?).
- `icon`: string (suggest an emoji or a descriptive keyword for an icon, e.g., "⚔️", "shield_icon", "red_potion_ bubbling").
- `equipable_slot`: Optional string (e.g., "weapon_hand", "armor_chest", "finger"; use slots from `game_terms_dictionary` if available).
- `requirements`: Optional object (e.g., `{{"level": 5, "strength": 12}}`; use stat/skill IDs from `game_terms_dictionary`).
CRITICAL INSTRUCTIONS:
1.  Use `game_terms_dictionary` from `<game_context>` for `item_type` (if defined there), `equipable_slot` (if defined), and any stat/skill IDs used in `requirements` or `properties_i18n`.
2.  Scale `value`, `rarity`, and numerical values in `properties_i18n` according to `scaling_parameters` and `player_context` (if available) from `<game_context>`. The `value` field is especially important as it will directly serve as the item's `base_price` for all economic activities and trade calculations.
3.  All textual fields (names, descriptions, property effects) MUST be in the specified multilingual JSON format: {{{lang_example_str}}}.
4.  The entire output must be a single JSON object representing the item profile. Do not include any text outside this JSON object.
"""
        return self._build_full_prompt_for_openai(task_prompt, generation_context)

    def generate_location_description_prompt(self, generation_context: GenerationContext) -> Dict[str, str]:
        location_idea = "a generic location"
        if generation_context and generation_context.request_params:
            location_idea = generation_context.request_params.get("location_idea", "a generic location")

        target_langs = generation_context.target_languages if generation_context and generation_context.target_languages else [self.main_bot_language, "en"]
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(target_langs)))])
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

    async def prepare_ai_prompt(
        self,
        guild_id: str,
        location_id: str,
        specific_task_instruction: str,
        player_id: Optional[str] = None,
        party_id: Optional[str] = None,
        additional_request_params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Prepares a generalized prompt for the AI based on provided context parameters.
        """
        if not self.context_collector:
            raise ValueError("PromptContextCollector is not initialized in MultilingualPromptGenerator.")

        request_params: Dict[str, Any] = {"location_id": location_id}
        if player_id: request_params["player_id"] = player_id
        if party_id: request_params["party_id"] = party_id
        if additional_request_params: request_params.update(additional_request_params)

        request_type = "general_task"
        target_entity_id = None
        target_entity_type = None

        if player_id:
            target_entity_id = player_id
            target_entity_type = "character"
            request_type = "player_specific_task"
        elif party_id:
            target_entity_id = party_id
            target_entity_type = "party"
            request_type = "party_specific_task"

        if "event" not in request_params: request_params["event"] = {}
        request_params["event"]["type"] = request_type
        if player_id: request_params["event"]["player_id"] = player_id
        if party_id: request_params["event"]["party_id"] = party_id

        generation_context_obj: GenerationContext = await self.context_collector.get_full_context(
            guild_id=guild_id,
            request_type=request_type,
            request_params=request_params,
            target_entity_id=target_entity_id,
            target_entity_type=target_entity_type
        )
        # The `lang` for GenerationContext will be derived from its own logic or defaults.
        # `target_languages` in `generation_context_obj` is crucial for `_get_base_system_prompt`.

        # Ensure target_languages in the context object is correctly populated
        # This might be redundant if PCC.get_full_context already handles this robustly.
        requested_target_languages: Optional[List[str]] = None
        if additional_request_params and "target_languages" in additional_request_params and \
           isinstance(additional_request_params["target_languages"], list):
            requested_target_languages = [str(tl) for tl in additional_request_params["target_languages"] if isinstance(tl, str)]

        if requested_target_languages:
            generation_context_obj.target_languages = sorted(list(set(requested_target_languages + [self.main_bot_language, "en"])))
        elif not generation_context_obj.target_languages : # If still empty or None after PCC
            generation_context_obj.target_languages = sorted(list(set([self.main_bot_language, "en"])))
        # Ensure 'en' is always present if not the main language
        if "en" not in generation_context_obj.target_languages and self.main_bot_language != "en":
            generation_context_obj.target_languages.append("en")
            generation_context_obj.target_languages = sorted(list(set(generation_context_obj.target_languages)))


        full_prompt_dict = self._build_full_prompt_for_openai(
            specific_task_prompt=specific_task_instruction,
            generation_context=generation_context_obj
        )
        return full_prompt_dict.get("user", "")


    def get_prompt_template(self, lang: str, template_key: str) -> Optional[str]:
        if not hasattr(self, 'prompt_templates_config') or not self.prompt_templates_config:
            return None
        # Ensure lang_templates is Dict[str, str] or handle other types
        lang_templates = self.prompt_templates_config.get(lang)
        if isinstance(lang_templates, dict): # Check if lang_templates is a dictionary
            template_value = lang_templates.get(template_key)
            return str(template_value) if template_value is not None else None # Ensure string return
        return None

    def generate_narrative_prompt(
        self,
>>>>>>> REPLACE
