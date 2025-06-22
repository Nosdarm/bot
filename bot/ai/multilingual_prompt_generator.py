# bot/ai/multilingual_prompt_generator.py

import json
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Tuple # Ensure Tuple is imported

from bot.ai.ai_data_models import GenerationContext, ValidationIssue

# Imports for prepare_location_description_prompt & prepare_faction_generation_prompt & prepare_quest_generation_prompt
from sqlalchemy.ext.asyncio import AsyncSession
from bot.database.models import GuildConfig, Location, WorldState, Player, GeneratedFaction, GeneratedNpc # Added GeneratedNpc
from bot.database.crud_utils import get_entity_by_id, get_entity_by_attributes, get_entities
# GameManager and LoreManager will be accessed via the game_manager parameter

if TYPE_CHECKING:
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.game.managers.game_manager import GameManager # For type hinting game_manager parameter

class MultilingualPromptGenerator:
    def __init__(
        self,
        context_collector: 'PromptContextCollector',
        main_bot_language: str, # e.g., "ru", "en"
        settings: Optional[Dict[str, Any]] = None # Added settings for prompt_templates_config
    ):
        self.context_collector = context_collector
        self.main_bot_language = main_bot_language
        self.settings = settings if settings else {}
        # Example of how prompt_templates_config might be loaded from settings
        # This assumes settings structure like: {"prompt_templates": {"en": {"narrative_generation_system": "..."}}}
        self.prompt_templates_config: Dict[str, Dict[str, str]] = self.settings.get("prompt_templates", {})


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
        quest_idea = generation_context.request_params.get("quest_idea", "a generic quest")
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(generation_context.target_languages)))])

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
- `guild_id`: Optional string (The ID of the guild this quest is primarily associated with. Use IDs from `game_terms_dictionary` or `faction_data` if a specific guild/faction is a quest giver or central to the quest).
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

    async def prepare_ai_prompt(
        self,
        guild_id: str,
        location_id: str, # Assuming location is usually a primary context point
        specific_task_instruction: str,
        player_id: Optional[str] = None,
        party_id: Optional[str] = None,
        additional_request_params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Prepares a generalized prompt for the AI based on provided context parameters.
        This method is intended to be a versatile way to generate prompts for various
        in-game situations not covered by more specific prompt generators.
        """
        if not self.context_collector:
            # In a real application, proper logging should be used.
            # print("ERROR: PromptContextCollector not available in MultilingualPromptGenerator.")
            # Consider raising an exception or returning a specific error indicator.
            raise ValueError("PromptContextCollector is not initialized in MultilingualPromptGenerator.")

        # 1. Prepare request_params for get_full_context
        request_params: Dict[str, Any] = {"location_id": location_id}
        if player_id:
            request_params["player_id"] = player_id
        if party_id:
            request_params["party_id"] = party_id

        if additional_request_params:
            request_params.update(additional_request_params)

        # 2. Determine request_type and target_entity (can be refined)
        request_type = "general_task" # Default type
        target_entity_id = None
        target_entity_type = None

        if player_id:
            target_entity_id = player_id
            target_entity_type = "character" # Consistent with PromptContextCollector
            request_type = "player_specific_task" # More specific if player is involved
        elif party_id: # Only if player_id didn't take precedence
            target_entity_id = party_id
            target_entity_type = "party" # PCC might need specific handling for party deep context
            request_type = "party_specific_task"

        # If a specific entity is mentioned in additional_request_params, that could also set target_entity
        # For example, if additional_request_params = {"npc_id": "some_npc"}, then:
        # target_entity_id = additional_request_params["npc_id"]
        # target_entity_type = "npc"
        # request_type = "npc_interaction_task"
        # This logic can be expanded based on common patterns.

        # 3. Call get_full_context
        # Assuming get_main_language_code is available in context_collector or self
        # For GenerationContext, lang is the primary language for the response format.
        # The actual bot language (self.main_bot_language) is used for _get_base_system_prompt via generation_context.target_languages

        # The 'lang' for GenerationContext should typically be the main bot language or a specific target language for this request.
        # Let's use self.main_bot_language as the primary language for the context object itself.
        # The target_languages field within GenerationContext will guide the multilingual output.
        current_bot_lang = self.main_bot_language

        # The GenerationContext itself doesn't have a 'lang' field, but its target_languages field is used.
        # The 'lang' parameter for get_full_context in PCC was for event language, which is not directly applicable here.
        # PCC's get_full_context takes guild_id, request_type, request_params, target_entity_id, target_entity_type.
        # The lang for GenerationContext will be derived from settings or main_bot_language for its internal formatting.

        # Re-checking GenerationContext: it has `lang: str` for the main language of the request.
        # It also has `target_languages: List[str]` which is handled by _get_base_system_prompt.
        # So, we need to pass a `lang` to get_full_context.

        # The `event` field in GenerationContext is a dict. For a general task, it can be empty.
        # We need to ensure `request_params` is correctly passed to `get_full_context`.
        # The PCC.get_full_context expects `request_params` to be a dict.
        # The `GenerationContext` will then be built from the `context_dict` inside PCC.get_full_context.

        # The `event` parameter for `GenerationContext` in `get_full_context` is the first argument.
        # For a general task, we might not have a specific "event" dict.
        # We can pass the specific_task_instruction or key elements as part of the event if needed,
        # or just an empty dict. Let's pass minimal event info.
        event_info_for_context = {
            "type": request_type,
            "task_instruction": specific_task_instruction,
            "source_entity_id": player_id or party_id # Who is initiating this task
        }

        generation_context_obj: GenerationContext = await self.context_collector.get_full_context(
            guild_id=guild_id,
            # lang=current_bot_lang, # get_full_context doesn't take lang, GenerationContext does. PCC sets it.
            request_type=request_type, # This is for PCC to know how to structure context
            request_params=request_params, # This contains player_id, party_id, location_id
            target_entity_id=target_entity_id,
            target_entity_type=target_entity_type
            # event_data=event_info_for_context # Pass event_info here if PCC uses it for GenerationContext.event
        )
        # The above call to get_full_context will internally create the GenerationContext object.
        # We need to ensure its `event` field is populated if specific_task_instruction should be part of it.
        # Let's ensure the GenerationContext has the task instruction.
        # We can add it to request_params or handle it when building the user prompt.
        # The current structure of get_full_context populates GenerationContext.event from request_params.event
        # So, let's add it to request_params.
        if "event" not in request_params: # Ensure event key exists for PCC
            request_params["event"] = {}
        request_params["event"]["type"] = request_type # Overwrite or set event type in request_params
        request_params["event"]["specific_task_instruction"] = specific_task_instruction
        if player_id: request_params["event"]["player_id"] = player_id
        if party_id: request_params["event"]["party_id"] = party_id


        # Re-call get_full_context with updated request_params that include the task if necessary
        # Or, more simply, pass specific_task_instruction directly to _build_full_prompt_for_openai
        # The GenerationContext object is built inside get_full_context.

        # Let's re-evaluate: get_full_context builds the GenerationContext.
        # The specific_task_instruction is for the <task> part of the user prompt, not necessarily part of GenerationContext.event
        # unless the context itself needs to vary based on the task instruction (which it might).
        # For now, specific_task_instruction is separate.

        # 4. Call _build_full_prompt_for_openai
        full_prompt_dict = self._build_full_prompt_for_openai(specific_task_instruction, generation_context_obj)

        # 5. Return User Prompt
        return full_prompt_dict.get("user", "")


    def get_prompt_template(self, lang: str, template_key: str) -> Optional[str]:
        """
        Placeholder: Retrieves a prompt template string.
        In a real implementation, this would load from config files or a database.
        Uses self.prompt_templates_config which should be populated during __init__.
        """
        if not hasattr(self, 'prompt_templates_config') or not self.prompt_templates_config:
            # print(f"DEBUG: prompt_templates_config not found or empty in MultilingualPromptGenerator.")
            return None

        lang_templates = self.prompt_templates_config.get(lang)
        if lang_templates:
            return lang_templates.get(template_key)
        return None

    def generate_narrative_prompt(
        self,
        event_type: str,
        source_name: str,
        target_name: Optional[str],
        key_details_str: str,
        guild_setting: str,
        tone: str,
        lang: str
    ) -> Tuple[str, str]:
        """
        Generates system and user prompts for creating a narrative for a game event.

        Args:
            event_type: The type of the event (e.g., "PLAYER_MOVE", "ITEM_DROP").
            source_name: Name of the entity that caused the event.
            target_name: Optional name of the entity affected by the event.
            key_details_str: A string summarizing other key details of the event.
            guild_setting: Brief description of the game world (e.g., "Dark Fantasy").
            tone: Desired narrative tone (e.g., "Gritty", "Epic", "Concise").
            lang: The desired language code for the narrative (e.g., "en", "ru").

        Returns:
            A tuple containing (system_prompt, user_prompt).
        """

        # System prompt sets the persona and overall instruction for the AI
        system_prompt_template = self.get_prompt_template(lang, "narrative_generation_system")
        if not system_prompt_template: # Fallback if specific template not found
            system_prompt_template = "You are a master storyteller for a text-based role-playing game. Your descriptions should be engaging and fit the specified tone and setting. Focus on creating a brief, vivid narrative for the event provided by the user. The narrative should be in {lang}."

        system_prompt = system_prompt_template.format(lang=lang, tone=tone, guild_setting=guild_setting)

        user_prompt_lines = []
        user_prompt_lines.append(f"Language for narrative: {lang}")
        user_prompt_lines.append(f"Game Setting: {guild_setting}")
        user_prompt_lines.append(f"Desired Tone: {tone}")
        user_prompt_lines.append(f"Event Type: {event_type}")
        user_prompt_lines.append(f"Event Source: {source_name}")
        if target_name:
            user_prompt_lines.append(f"Event Target: {target_name}")
        user_prompt_lines.append(f"Key Details: {key_details_str}")

        user_prompt_lines.append("\nInstructions:")
        user_prompt_lines.append("Based on the event details above, generate a brief (1-2 sentences) narrative description of what happened. Make it immersive and fit the specified tone and setting.")
        user_prompt_lines.append("Do NOT repeat the input details verbatim; weave them into a story.")
        user_prompt_lines.append("Focus on the action and its immediate impact or feeling.")

        user_prompt = "\n".join(user_prompt_lines)

        # print(f"DEBUG Narrative Prompts for lang '{lang}':\nSystem: {system_prompt}\nUser: {user_prompt}")
        return system_prompt, user_prompt

    def generate_faction_creation_prompt(
        self,
        guild_setting: str,
        existing_npcs_summary: Optional[str], # Made optional
        existing_locations_summary: Optional[str], # Made optional
        lang: str,
        num_factions: int
    ) -> Tuple[str, str]:
        """
        Generates system and user prompts for creating faction concepts using an LLM.

        Args:
            guild_setting: Brief description of the game world (e.g., "Dark Fantasy").
            existing_npcs_summary: Optional string summarizing key existing NPCs.
            existing_locations_summary: Optional string summarizing key existing locations.
            lang: The desired language code for the faction details (e.g., "en", "ru").
            num_factions: The number of distinct faction concepts to generate.

        Returns:
            A tuple containing (system_prompt, user_prompt).
        """

        system_prompt_template = self.get_prompt_template(lang, "faction_creation_system")
        if not system_prompt_template: # Fallback if specific template not found
            system_prompt_template = (
                "You are an expert world-builder for a text-based role-playing game. "
                "Your task is to generate {num_factions} distinct and interesting faction concepts "
                "suitable for a {guild_setting} world. Ensure the output is in valid JSON format as specified. "
                "The factions should feel unique and offer potential for conflict or cooperation. "
                "Leader names should be thematic. Descriptions should be concise but evocative. "
                "Provide all text in {lang}."
            )

        system_prompt = system_prompt_template.format(
            num_factions=num_factions,
            guild_setting=guild_setting,
            lang=lang
        )

        user_prompt_lines = [
            f"Please generate {num_factions} unique faction concepts for a game set in a '{guild_setting}' world.",
            f"The primary language for names and descriptions should be: {lang}.",
            "For each faction, provide the following details in a JSON list format. Each object in the list should represent a faction and have these EXACT keys:",
            "- `name_i18n`: A dictionary with at least an entry for '{lang}' (e.g., {{'{lang}': 'Faction Name in {lang}'}}) and optionally for 'en' if {lang} is not 'en'.",
            "- `description_i18n`: A dictionary similar to name_i18n, for the faction's ideology and brief description (e.g., {{'{lang}': 'Description in {lang}'}}).",
            "- `leader_concept`: A dictionary describing a potential leader, including:",
            "  - `name`: Suggested name for the leader (in {lang}).",
            "  - `persona`: A brief (1-2 sentence) description of the leader's personality and role (in {lang}).",
            "- `goals`: A list of 2-3 short strings describing the faction's primary objectives (in {lang}).",
            "- `alignment_suggestion`: A suggested alignment (e.g., 'Lawful Good', 'Chaotic Neutral', 'True Neutral', 'Lawful Evil')."
        ]

        if existing_npcs_summary:
            user_prompt_lines.append(f"\nConsider these existing NPCs as potential inspiration or connections (but you can create new leaders):\n{existing_npcs_summary}")
        if existing_locations_summary:
            user_prompt_lines.append(f"\nConsider these existing locations as potential faction bases or areas of interest:\n{existing_locations_summary}")

        user_prompt_lines.append(
            "\nExample JSON structure for a single faction object within the list:"
            "\n```json"
            "\n{"
            "\n  \"name_i18n\": {\"{lang}\": \"Солнечный Орден\", \"en\": \"Order of the Sun\"},"
            "\n  \"description_i18n\": {\"{lang}\": \"Рыцари, посвятившие себя искоренению тьмы.\", \"en\": \"Knights dedicated to eradicating darkness.\"},"
            "\n  \"leader_concept\": {\"name\": \"Верховный Паладин Елена\", \"persona\": \"Строгая, но справедливая воительница, ведущая своих рыцарей с непоколебимой верой.\"},"
            "\n  \"goals\": [\"Защитить невинных\", \"Уничтожить нежить\", \"Распространить свет\"],"
            "\n  \"alignment_suggestion\": \"Lawful Good\""
            "\n}"
            "\n```"
            "\nPlease provide the full JSON list containing all {num_factions} faction objects."
        )

        user_prompt = "\n".join(user_prompt_lines).format(lang=lang, num_factions=num_factions) # Format lang here for example

        # print(f"DEBUG Faction Creation Prompts for lang '{lang}':\nSystem: {system_prompt}\nUser: {user_prompt}")
        return system_prompt, user_prompt

    async def prepare_location_description_prompt(
        self,
        guild_id: str,
        location_id: str,
        db_session: AsyncSession,
        game_manager: "GameManager", # Use forward reference string for GameManager
        player_id: Optional[str] = None
    ) -> str:
        """
        Prepares a detailed prompt for an AI to generate a location description.
        """
        prompt_lines = []

        try:
            # 1. Load Bot Language for the Guild
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
            prompt_lines.append(f"Primary Language for output and context interpretation: {bot_language}")
            # Specify target languages for the output JSON structure
            target_languages = sorted(list(set([bot_language, "en"])))
            lang_fields_example = ", ".join([f'"{lang}": "..."' for lang in target_languages])


            # 2. Load Location
            location = await get_entity_by_id(db_session, Location, location_id)
            if not location or location.guild_id != guild_id:
                # If using manager's cache: location = game_manager.location_manager.get_location_instance(guild_id, location_id)
                # For DB direct:
                # location = await get_entity_by_attributes(db_session, Location, {"id": location_id, "guild_id": guild_id})
                error_msg = f"Error: Location with ID '{location_id}' not found for guild '{guild_id}'."
                # print(error_msg) # Or log
                return f"Cannot generate description: {error_msg}" # Or raise specific exception

            location_name_native = location.name_i18n.get(bot_language, location.name_i18n.get("en", "Unknown Location"))
            location_desc_native = location.descriptions_i18n.get(bot_language, location.descriptions_i18n.get("en", ""))


            # 3. Load WorldState
            world_state = await get_entity_by_attributes(db_session, WorldState, {}, guild_id)
            # If using manager's cache: world_state = game_manager.world_state_manager.get_world_state(guild_id)

            world_state_info = "No specific world state details available."
            if world_state:
                current_era_native = world_state.current_era_i18n.get(bot_language, world_state.current_era_i18n.get("en", "Current era not specified"))

                custom_flags_details = []
                if world_state.custom_flags and isinstance(world_state.custom_flags, dict):
                    for key, value in world_state.custom_flags.items():
                        if isinstance(value, bool):
                            if value: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')}.")
                            else: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')} is not the case.")
                        else: custom_flags_details.append(f"- Regarding '{key.replace('_', ' ')}': {value}.")

                world_flags_context_str = ""
                if custom_flags_details:
                    world_flags_context_str = "\n**Current World State Flags that may be relevant:**\n" + "\n".join(custom_flags_details)

                world_state_info = f"Current Era: {current_era_native}.{world_flags_context_str}"
            else: # world_state is None
                 world_state_info = "World state information is currently unavailable."


            # 4. Load Player (if player_id provided)
            player_info = "No specific player context for this description."
            if player_id:
                player = await get_entity_by_id(db_session, Player, player_id)
                # player = await get_entity_by_attributes(db_session, Player, {"id": player_id, "guild_id": guild_id})
                if player and player.guild_id == guild_id: # ensure player is from the correct guild
                    player_name_native = player.name_i18n.get(bot_language, player.name_i18n.get("en", "A traveler"))
                    player_info = f"The player, {player_name_native} (ID: {player.id}), is currently at this location. Consider their perspective if appropriate."
                else:
                    player_info = f"Player with ID {player_id} not found in this guild. Generating a general description."


            # 5. Fetch Lore
            lore_info = "No specific lore snippets available for this location at the moment."
            if game_manager.lore_manager:
                # Assuming a method like get_lore_for_context exists in LoreManager
                # For MVP, let's assume it takes location_id and returns a list of strings
                try:
                    # This method might need db_session if it queries DB directly
                    lore_snippets = await game_manager.lore_manager.get_lore_for_location_context(
                        guild_id=guild_id,
                        location_id=location_id,
                        # db_session=db_session # if LoreManager methods need it
                    )
                    if lore_snippets:
                        lore_info = "Relevant Lore Snippets:\n" + "\n".join([f"- {s}" for s in lore_snippets])
                except AttributeError:
                    lore_info = "LoreManager does not have 'get_lore_for_location_context'. Using placeholder lore."
                except Exception as e:
                    lore_info = f"Error fetching lore: {e}. Using placeholder lore."
            else:
                lore_info = "LoreManager not available. Using placeholder lore."


            # --- Assemble Prompt String ---
            prompt_lines = [
                "Task: Generate a rich and immersive description for a location in a text-based RPG.",
                "Output Format Guidance:",
                f"  - Provide the description in two languages: {bot_language} (primary) and English (en).",
                f"  - Format the output as a single JSON object.",
                f"  - The JSON object MUST have a top-level key 'description_i18n'.",
                f"  - The value of 'description_i18n' MUST be another JSON object with keys for each language: '{bot_language}' and 'en'.",
                f"  - Example: {{\"description_i18n\": {{ \"{bot_language}\": \"Описание на языке {bot_language}...\", \"en\": \"Description in English...\"}}}}",
                "Constraints & Style:",
                "  - The description should be detailed, engaging, and suitable for a text RPG.",
                "  - Focus on sensory details (sights, sounds, smells, atmosphere).",
                "  - Avoid game mechanics or player actions. Describe the place itself.",
                "  - Be creative and consistent with a typical fantasy RPG setting unless context suggests otherwise.",
                "Context for Generation:",
                f"  - Location Name ({bot_language}): {location_name_native}",
                f"  - Location ID: {location.id}",
                f"  - Existing Static Description ({bot_language}): {location_desc_native if location_desc_native else 'Not set.'}",
                f"  - World State Information: {world_state_info}", # Updated variable name for clarity
                f"  - Player Context: {player_info}",
                f"  - {lore_info}",
                "Please generate the location description now based on all the provided context and adhering to the output format."
            ]

            return "\n".join(prompt_lines)

        except Exception as e:
            # print(f"Error preparing location description prompt: {e}") # Or log
            # traceback.print_exc()
            return f"Error: Could not prepare prompt for location {location_id}. Details: {e}"

    async def prepare_faction_generation_prompt(
        self,
        guild_id: str,
        db_session: AsyncSession,
        game_manager: "GameManager",
        theme_keywords: Optional[List[str]] = None,
        num_factions_to_generate: int = 2 # Default to generating 2 if not specified
    ) -> str:
        """
        Prepares a detailed prompt for an AI to generate new factions.
        """
        prompt_lines = []
        try:
            # 1. Determine Language
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
            target_languages = sorted(list(set([bot_language, "en"])))

            # 2. Load WorldState
            world_state = await get_entity_by_attributes(db_session, WorldState, {}, guild_id)
            world_state_info = "No specific world state details available."
            if world_state:
                current_era_native = world_state.current_era_i18n.get(bot_language, world_state.current_era_i18n.get("en", "Current era not specified"))

                custom_flags_details = []
                if world_state.custom_flags and isinstance(world_state.custom_flags, dict):
                    for key, value in world_state.custom_flags.items():
                        if isinstance(value, bool):
                            if value: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')}.")
                            else: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')} is not the case.")
                        else: custom_flags_details.append(f"- Regarding '{key.replace('_', ' ')}': {value}.")

                world_flags_context_str = ""
                if custom_flags_details:
                    world_flags_context_str = "\n**Current World State Flags that may be relevant:**\n" + "\n".join(custom_flags_details)

                world_state_info = f"Current Era: {current_era_native}.{world_flags_context_str}"
            else: # world_state is None
                world_state_info = "World state information is currently unavailable."

            # 3. Load Existing Factions
            existing_factions_str = "No factions currently exist."
            existing_factions = await get_entities(db_session, GeneratedFaction, guild_id=guild_id)
            if existing_factions:
                faction_names = [f.name_i18n.get(bot_language, f.name_i18n.get("en", "Unnamed Faction")) for f in existing_factions if f.name_i18n]
                if faction_names:
                    existing_factions_str = f"The world already contains these factions: {', '.join(faction_names)}."

            # 4. Fetch Lore
            lore_info = "No specific lore snippets available for faction generation at the moment."
            if game_manager.lore_manager:
                try:
                    # Using a more generic lore fetching method for broader context
                    lore_snippets = await game_manager.lore_manager.get_general_world_lore(guild_id, db_session, limit=5)
                    if lore_snippets:
                        lore_info = "Relevant World Lore Snippets (consider these for themes and relationships):\n" + "\n".join([f"- {s}" for s in lore_snippets])
                except AttributeError:
                    lore_info = "LoreManager does not have 'get_general_world_lore'. Using placeholder lore."
                except Exception as e:
                    lore_info = f"Error fetching lore: {e}. Using placeholder lore."
            else:
                lore_info = "LoreManager not available. Using placeholder lore."

            # 5. Fetch Faction Generation Rules (Optional)
            faction_archetypes = await game_manager.get_rule(guild_id, 'faction_generation_archetypes', [])
            naming_conventions = await game_manager.get_rule(guild_id, 'faction_naming_conventions', None)

            rules_guidelines = []
            if faction_archetypes:
                rules_guidelines.append(f"Consider these faction archetypes/themes if appropriate: {', '.join(faction_archetypes)}.")
            if naming_conventions:
                rules_guidelines.append(f"Follow these naming conventions if possible: {naming_conventions}.")
            rules_guidelines_str = "\n".join(rules_guidelines) if rules_guidelines else "No specific generation rules provided; use general fantasy tropes."


            # --- Assemble Prompt String ---
            prompt_lines.append(f"Task: Generate {num_factions_to_generate} new, unique factions for a fantasy text-based RPG world.")

            prompt_lines.append("\nOutput Format Guidance:")
            prompt_lines.append("  - The output MUST be a valid JSON object.")
            prompt_lines.append("  - The JSON object should contain a single top-level key: 'new_factions'.")
            prompt_lines.append("  - The value of 'new_factions' MUST be a list, where each item in the list is an object representing a single faction.")
            prompt_lines.append("  - Each faction object MUST have the following keys:")
            prompt_lines.append("    - 'name_i18n': An object with language codes as keys (must include 'en' and the primary bot language '{bot_language}'). Values are the faction names.")
            prompt_lines.append("    - 'ideology_i18n': An object similar to 'name_i18n', for the faction's core beliefs/goals.")
            prompt_lines.append("    - 'description_i18n': An object similar to 'name_i18n', for a paragraph describing the faction, its typical members, and activities.")
            prompt_lines.append("  - Optionally, each faction object can also include:")
            prompt_lines.append("    - 'leader_concept_i18n': An object similar to 'name_i18n', for a brief idea of a leader figure.")
            prompt_lines.append("    - 'resource_notes_i18n': An object similar to 'name_i18n', for notes on key resources the faction might control or seek.")

            example_faction_json = {
                "name_i18n": {bot_language: f"Название фракции ({bot_language})", "en": "Faction Name (en)"},
                "ideology_i18n": {bot_language: f"Идеология ({bot_language})", "en": "Ideology (en)"},
                "description_i18n": {bot_language: f"Описание ({bot_language})", "en": "Description (en)"},
                "leader_concept_i18n": {bot_language: f"Концепция лидера ({bot_language})", "en": "Leader Concept (en)"},
                "resource_notes_i18n": {bot_language: f"Заметки о ресурсах ({bot_language})", "en": "Resource Notes (en)"}
            }
            prompt_lines.append(f"  - Example structure for one faction object: \n{json.dumps(example_faction_json, ensure_ascii=False, indent=2)}")

            prompt_lines.append("\nConstraints & Style:")
            prompt_lines.append("  - Factions should be unique and fit a fantasy RPG setting.")
            prompt_lines.append("  - Ensure names, ideologies, and descriptions are creative and distinct from each other and from existing factions.")
            prompt_lines.append(f"  - All text in '_i18n' fields must be provided for both '{bot_language}' and 'en'.")

            prompt_lines.append("\nContext for Generation:")
            prompt_lines.append(f"  - Primary Bot Language: {bot_language}")
            prompt_lines.append(f"  - World State Information: {world_state_info}") # Updated variable name
            prompt_lines.append(f"  - Existing Factions: {existing_factions_str}")
            prompt_lines.append(f"  - {lore_info}")
            if theme_keywords:
                prompt_lines.append(f"  - Focus on themes like: {', '.join(theme_keywords)}.")
            prompt_lines.append(f"  - Generation Guidelines: {rules_guidelines_str}")

            prompt_lines.append(f"\nPlease generate the JSON object containing a list of {num_factions_to_generate} new factions now.")

            return "\n\n".join(prompt_lines)

        except Exception as e:
            # Log the error with traceback for debugging
            # logger.error(f"Error preparing faction generation prompt for guild {guild_id}: {e}", exc_info=True)
            return f"Error: Could not prepare prompt for faction generation. Details: {e}"

    async def prepare_quest_generation_prompt(
        self,
        guild_id: str,
        db_session: AsyncSession,
        game_manager: "GameManager",
        context_details: Dict[str, Any]
    ) -> str:
        """
        Prepares a detailed prompt for an AI to generate a new quest with multiple steps.
        context_details can contain: player_id, location_id, npc_id, faction_id, theme, difficulty_hint
        """
        prompt_lines = []
        try:
            # 1. Determine Language
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
            target_languages = sorted(list(set([bot_language, "en"])))

            # 2. Load Contextual Data
            world_state = await get_entity_by_attributes(db_session, WorldState, {}, guild_id)
            world_state_info = "No specific world state details available."
            if world_state:
                current_era_native = world_state.current_era_i18n.get(bot_language, world_state.current_era_i18n.get("en", "Current era not specified"))

                custom_flags_details = []
                if world_state.custom_flags and isinstance(world_state.custom_flags, dict):
                    for key, value in world_state.custom_flags.items():
                        if isinstance(value, bool):
                            if value: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')}.")
                            else: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')} is not the case.")
                        else: custom_flags_details.append(f"- Regarding '{key.replace('_', ' ')}': {value}.")

                world_flags_context_str = ""
                if custom_flags_details:
                    world_flags_context_str = "\n**Current World State Flags that may be relevant:**\n" + "\n".join(custom_flags_details)

                world_state_info = f"Current Era: {current_era_native}.{world_flags_context_str}"
            else: # world_state is None
                world_state_info = "World state information is currently unavailable."

            player_context_info = "No specific player context for this quest generation."
            if context_details.get("player_id"):
                player = await get_entity_by_id(db_session, Player, context_details["player_id"])
                if player and player.guild_id == guild_id:
                    player_name = player.name_i18n.get(bot_language, player.name_i18n.get("en", "A traveler"))
                    player_level = player.level
                    player_loc_id = player.current_location_id
                    player_loc_name = "Unknown"
                    if player_loc_id:
                        player_current_loc = await get_entity_by_id(db_session, Location, player_loc_id)
                        if player_current_loc:
                            player_loc_name = player_current_loc.name_i18n.get(bot_language, player_current_loc.name_i18n.get("en", "Unknown"))
                    player_context_info = f"Consider Player: {player_name} (Level {player_level}, Current Location: {player_loc_name} (ID: {player_loc_id}))."

            location_context_info = "No specific location context provided."
            if context_details.get("location_id"):
                loc = await get_entity_by_id(db_session, Location, context_details["location_id"])
                if loc and loc.guild_id == guild_id:
                    loc_name = loc.name_i18n.get(bot_language, loc.name_i18n.get("en", "A location"))
                    loc_desc = loc.descriptions_i18n.get(bot_language, loc.descriptions_i18n.get("en", "No description"))
                    location_context_info = f"Quest may be relevant to Location: {loc_name} (ID: {loc.id}) - Description: {loc_desc[:150]}..."

            npc_context_info = "No specific NPC context provided."
            if context_details.get("npc_id"):
                npc = await get_entity_by_id(db_session, GeneratedNpc, context_details["npc_id"]) # Assuming GeneratedNpc
                if npc and npc.guild_id == guild_id:
                    npc_name = npc.name_i18n.get(bot_language, npc.name_i18n.get("en", "An NPC"))
                    npc_context_info = f"Quest may involve NPC: {npc_name} (ID: {npc.id})."

            faction_context_info = "No specific faction context provided."
            if context_details.get("faction_id"):
                faction = await get_entity_by_id(db_session, GeneratedFaction, context_details["faction_id"])
                if faction and faction.guild_id == guild_id:
                    faction_name = faction.name_i18n.get(bot_language, faction.name_i18n.get("en", "A faction"))
                    faction_context_info = f"Quest may involve Faction: {faction_name} (ID: {faction.id})."

            theme_info = f"Suggested theme: {context_details['theme']}" if context_details.get('theme') else "Theme: General fantasy adventure."
            difficulty_info = f"Suggested difficulty: {context_details['difficulty_hint']}" if context_details.get('difficulty_hint') else "Difficulty: Medium (adjust based on player level if provided)."

            lore_info = "No general world lore provided for this quest generation."
            if game_manager.lore_manager:
                try:
                    lore_snippets = await game_manager.lore_manager.get_general_world_lore(guild_id, db_session, limit=3)
                    if lore_snippets:
                        lore_info = "General World Lore (consider for themes/plots):\n" + "\n".join([f"- {s}" for s in lore_snippets])
                except Exception: pass # Ignore lore errors for now

            # 3. Fetch Quest Generation Rules (Optional)
            quest_structures = await game_manager.get_rule(guild_id, 'quest_generation_structures', [])
            reward_guidelines = await game_manager.get_rule(guild_id, 'quest_reward_guidelines', {})
            rules_guidelines = []
            if quest_structures: rules_guidelines.append(f"Consider these quest structures if appropriate: {', '.join(quest_structures)}.")
            if reward_guidelines: rules_guidelines.append(f"Follow these reward guidelines: {json.dumps(reward_guidelines, ensure_ascii=False)}.")
            rules_guidelines_str = "\n".join(rules_guidelines) if rules_guidelines else "Use standard RPG quest structures and reward patterns."

            # --- Assemble Prompt String ---
            prompt_lines.append("You are an expert quest designer for a fantasy text-based RPG. Generate a compelling quest with multiple steps, suitable for the given context.")

            prompt_lines.append(f"\nGuild/World Language for i18n fields: {bot_language} (English 'en' must also be provided).")

            prompt_lines.append("\nCONTEXT FOR QUEST GENERATION:")
            prompt_lines.append(f"  - World State Information: {world_state_info}") # Updated variable name
            prompt_lines.append(f"  - Player Context: {player_context_info}")
            prompt_lines.append(f"  - Location Context: {location_context_info}")
            prompt_lines.append(f"  - NPC Context: {npc_context_info}")
            prompt_lines.append(f"  - Faction Context: {faction_context_info}")
            prompt_lines.append(f"  - {theme_info}")
            prompt_lines.append(f"  - {difficulty_info}")
            prompt_lines.append(f"  - {lore_info}")
            prompt_lines.append(f"  - Design Guidelines: {rules_guidelines_str}")

            prompt_lines.append("\nMAIN QUEST DETAILS TO GENERATE:")
            prompt_lines.append("  - `title_i18n`: A catchy, multilingual title for the quest.")
            prompt_lines.append("  - `description_i18n`: A multilingual summary of the quest's premise and what the player will generally be doing.")
            prompt_lines.append("  - `suggested_level` (integer): Approximate player level suitable for this quest (consider Player Context if provided, otherwise make a reasonable estimate).")
            prompt_lines.append("  - `quest_giver_details_i18n` (Optional): Multilingual details about the quest giver if not a specific known NPC (e.g., 'a mysterious note', 'a village elder').")
            prompt_lines.append("  - `prerequisites_json` (Optional, string): A JSON string defining conditions to start the quest. Example: '{\"min_level\": 5, \"completed_quest_id\": \"main_story_01\"}'. Leave as null if no specific prerequisites.")
            prompt_lines.append("  - `rewards_json` (string): A JSON string detailing rewards upon final quest completion. Example: '{\"xp\": 500, \"gold\": 100, \"items\": [{\"item_template_id\": \"healing_potion_greater\", \"quantity\": 3}]}'. Be specific with item_template_ids if possible, otherwise use descriptive placeholders like 'a_rusty_sword'.")
            prompt_lines.append("  - `consequences_json` (Optional, string): A JSON string for overall consequences of quest completion or failure. Example: '{\"on_complete\": {\"world_flag_set\": \"village_saved\"}, \"on_fail\": {\"faction_rep_change\": {\"thieves_guild_id\": -10}}}'.")

            prompt_lines.append("\nQUEST STEPS (Generate a list of 2 to 4 sequential steps):")
            prompt_lines.append("  For each step, provide:")
            prompt_lines.append("    - `title_i18n`: Multilingual title for the step.")
            prompt_lines.append("    - `description_i18n`: Multilingual detailed description of what the player needs to do for this step.")
            prompt_lines.append("    - `required_mechanics_json` (string): A JSON string defining specific, game-engine-parsable completion criteria. Examples:")
            prompt_lines.append("        - Item Collection: '{\"type\": \"acquire_item\", \"item_template_id\": \"specific_herb_001\", \"quantity\": 5}'")
            prompt_lines.append("        - NPC Interaction: '{\"type\": \"interaction\", \"target_npc_id\": \"npc_merchant_john\", \"interaction_type\": \"persuade_discount\"}' (interaction_type can be generic like 'discuss_topic_X')")
            prompt_lines.append("        - Location Exploration: '{\"type\": \"explore_location\", \"location_id\": \"ancient_ruins_lvl2\"}'")
            prompt_lines.append("        - Enemy Defeat: '{\"type\": \"defeat_enemy\", \"enemy_type_id\": \"goblin_shaman_template\", \"quantity\": 1, \"in_location_id\": \"goblin_cave_entrance\"}' (optional in_location_id)")
            prompt_lines.append("    - `abstract_goal_json` (Optional, string): A JSON string for goals that are more narrative or require GM/complex AI judgment. Example: '{\"goal_summary\": \"Find evidence of the spy's betrayal\"}'. Use this if required_mechanics_json is too specific or not applicable.")
            prompt_lines.append("    - `consequences_json` (Optional, string): A JSON string for step-specific consequences or rewards upon its completion. Example: '{\"grant_xp\": 50, \"unlock_dialogue_option\": \"learned_secret_X\"}'.")

            prompt_lines.append("\nOUTPUT FORMAT (CRITICAL):")
            prompt_lines.append("  - The entire output MUST be a single valid JSON object.")
            prompt_lines.append("  - This object should contain a single top-level key: `\"quest_data\"`.")
            prompt_lines.append("  - The value of `\"quest_data\"` must be an object containing all the 'MAIN QUEST DETAILS' requested above.")
            prompt_lines.append("  - The `\"quest_data\"` object must also contain a key named `\"steps\"`, whose value is a LIST of quest step objects.")
            prompt_lines.append("  - Each quest step object in the `\"steps\"` list must contain its respective attributes ('title_i18n', 'description_i18n', 'required_mechanics_json', etc.).")
            prompt_lines.append(f"  - All fields ending with `_i18n` (e.g., `title_i18n`) MUST be objects containing two keys: '{bot_language}' and 'en', with string values for the respective translations.")
            prompt_lines.append("  - All fields ending with `_json` (e.g., `rewards_json`, `required_mechanics_json`) MUST contain VALID JSON STRINGS as their values (i.e., strings that can be parsed into JSON objects or arrays).")

            example_output_structure = {
                "quest_data": {
                    "title_i18n": {bot_language: "Название квеста", "en": "Quest Title"},
                    "description_i18n": {bot_language: "Описание квеста.", "en": "Quest description."},
                    "suggested_level": 5,
                    "quest_giver_details_i18n": {bot_language: "Информация о квестодателе.", "en": "Quest giver information."},
                    "prerequisites_json": json.dumps({"min_level": 5}),
                    "rewards_json": json.dumps({"xp": 100, "gold": 50}),
                    "consequences_json": json.dumps({"faction_rep_change": {"some_faction_id": 10}}),
                    "steps": [
                        {
                            "title_i18n": {bot_language: "Шаг 1", "en": "Step 1"},
                            "description_i18n": {bot_language: "Описание шага 1.", "en": "Step 1 description."},
                            "required_mechanics_json": json.dumps({"type": "explore_location", "location_id": "some_loc_id"}),
                            "abstract_goal_json": None, # Can be null if not applicable
                            "consequences_json": None
                        },
                        {
                            "title_i18n": {bot_language: "Шаг 2", "en": "Step 2"},
                            "description_i18n": {bot_language: "Описание шага 2.", "en": "Step 2 description."},
                            "required_mechanics_json": json.dumps({"type": "acquire_item", "item_template_id": "key_item", "quantity": 1}),
                            "abstract_goal_json": None,
                            "consequences_json": json.dumps({"xp_bonus": 50})
                        }
                    ]
                }
            }
            prompt_lines.append(f"  - Example of the complete JSON output structure:\n```json\n{json.dumps(example_output_structure, ensure_ascii=False, indent=2)}\n```")
            prompt_lines.append("\nEnsure quests are engaging, logical, and fit a fantasy RPG setting. Step descriptions should clearly guide the player.")
            prompt_lines.append("Please generate the quest JSON object now.")

            return "\n\n".join(prompt_lines)

        except Exception as e:
            # logger.error(f"Error preparing quest generation prompt for guild {guild_id}: {e}", exc_info=True)
            return f"Error: Could not prepare prompt for quest generation. Details: {e}"

    async def prepare_item_generation_prompt(
        self,
        guild_id: str,
        db_session: AsyncSession, # db_session might not be strictly needed if all context comes from game_manager rules
        game_manager: "GameManager",
        item_type_suggestion: Optional[str] = None,
        theme_keywords: Optional[List[str]] = None,
        num_items_to_generate: int = 3
    ) -> str:
        """
        Prepares a detailed prompt for an AI to generate new game items.
        """
        prompt_lines = []
        try:
            # 1. Determine Language
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
            target_languages = sorted(list(set([bot_language, "en"])))

            # 2. Load WorldState (for custom_flags, if any)
            world_state = await get_entity_by_attributes(db_session, WorldState, {}, guild_id)
            world_flags_context_str = ""
            if world_state and world_state.custom_flags and isinstance(world_state.custom_flags, dict):
                custom_flags_details = []
                for key, value in world_state.custom_flags.items():
                    if isinstance(value, bool):
                        if value: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')}.")
                        else: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')} is not the case.")
                    else: custom_flags_details.append(f"- Regarding '{key.replace('_', ' ')}': {value}.")
                if custom_flags_details:
                    world_flags_context_str = "\n  - Current World State Flags that may influence item properties or availability:\n" + "\n    ".join(custom_flags_details)


            # 3. Fetch Item Generation Rules from RuleConfig (with defaults)
            common_item_types_default = ["weapon", "armor", "potion", "scroll", "ring", "amulet", "crafting_material", "quest_item", "currency_generic", "food", "tool", "key", "book_readable", "container_generic", "misc_valuable", "misc_mundane"]
            common_item_types = await game_manager.get_rule(guild_id, 'item_generation_common_types', common_item_types_default)

            property_examples_default = {
                "weapon": {"damage": "1d8 piercing", "bonus_attack": 1, "weight_kg": 1.0, "value_coins": 50},
                "armor": {"armor_class_bonus": 3, "stealth_disadvantage": True, "weight_kg": 10.0, "value_coins": 100},
                "potion": {"effect_description_i18n": {bot_language: "Восстанавливает немного здоровья.", "en": "Restores a small amount of health."}, "effect_mechanics_json": "{\\\"type\\\": \\\"heal\\\", \\\"amount\\\": \\\"2d4+2\\\"}", "value_coins": 25},
                "ring": {"attribute_bonus_i18n": {bot_language: "Кольцо ловкости +1", "en": "Ring of Dexterity +1"}, "effect_mechanics_json": "{\\\"attributes\\\": {\\\"dexterity\\\": 1}}", "value_coins": 150},
                "crafting_material": {"description_i18n": {bot_language: "Редкий кристалл, используемый в мощных зачарованиях.", "en": "A rare crystal used in powerful enchantments."}, "value_coins": 75}
            }
            property_examples = await game_manager.get_rule(guild_id, 'item_generation_property_examples', property_examples_default)

            value_range_suggestions_default = {"common": "1-50", "uncommon": "51-250", "rare": "251-1000", "very_rare": "1001-5000", "legendary": "5001+"}
            value_range_suggestions = await game_manager.get_rule(guild_id, 'item_value_range_suggestions', value_range_suggestions_default)

            # --- Assemble Prompt String ---
            prompt_lines.append("You are an expert item designer for a fantasy text-based RPG. Generate a list of unique and interesting items.")

            prompt_lines.append("\nCONTEXT & GUIDELINES:")
            prompt_lines.append(f"  - Guild/World Language for i18n fields: {bot_language} (English 'en' must also be provided).")
            if world_flags_context_str:
                prompt_lines.append(world_flags_context_str)
            prompt_lines.append(f"  - Generate exactly {num_items_to_generate} distinct items.")
            if item_type_suggestion:
                prompt_lines.append(f"  - Focus on items of type or related to: '{item_type_suggestion}'.")
            if theme_keywords:
                prompt_lines.append(f"  - Incorporate themes like: {', '.join(theme_keywords)}.")
            prompt_lines.append(f"  - Common Item Types (feel free to be more specific or invent variations): {', '.join(common_item_types)}.")
            prompt_lines.append(f"  - Item Properties (`properties_json` field): This field is CRITICAL and MUST be a valid JSON string. It should detail the item's mechanical effects, bonuses, requirements, etc. Examples for different types:")
            for item_type, example in property_examples.items():
                prompt_lines.append(f"    - For '{item_type}': {json.dumps(example, ensure_ascii=False)}")
            prompt_lines.append(f"  - Suggested Base Value Ranges (in generic currency units): {json.dumps(value_range_suggestions, ensure_ascii=False)}. Adjust based on power and rarity.")

            prompt_lines.append("\nITEM DETAILS TO GENERATE (for each item):")
            prompt_lines.append("  - `name_i18n`: Creative and descriptive name (localized for '{bot_language}' and 'en').")
            prompt_lines.append("  - `description_i18n`: Flavorful description, including appearance and lore if any (localized for '{bot_language}' and 'en').")
            prompt_lines.append("  - `item_type` (string): A specific type for the item (e.g., \"longsword\", \"healing_potion\", \"ancient_tome\", \"iron_ore\"). Should be chosen from common types or be a sensible specific one.")
            prompt_lines.append("  - `base_value` (integer): Estimated monetary value in the game world. Use the value range suggestions as a guide.")
            prompt_lines.append("  - `properties_json` (string): A valid JSON string detailing all mechanical effects, bonuses, skill requirements, equipable slot, weight, stackability, etc. Example: '{{\"damage\": \"1d6 slashing\", \"weight_kg\": 1.5, \"equipable_slot\": \"main_hand\"}}' or '{{\"effect\": \"restores_hp\", \"amount\": \"2d4+2\", \"stackable\": true, \"max_stack\": 10, \"weight_kg\": 0.1}}'. This field is crucial.")
            prompt_lines.append("  - `rarity_level` (Optional, string): e.g., \"common\", \"uncommon\", \"rare\", \"very_rare\", \"legendary\". If omitted, will be considered 'common'.")

            prompt_lines.append("\nOUTPUT FORMAT (CRITICAL):")
            prompt_lines.append("  - The entire output MUST be a single valid JSON object.")
            prompt_lines.append("  - The JSON object should contain a single top-level key: `\"new_items\"`.")
            prompt_lines.append("  - The value of `\"new_items\"` MUST be a list, where each item in the list is an object representing a single generated item.")
            prompt_lines.append("  - Each item object must have the keys: 'name_i18n', 'description_i18n', 'item_type', 'base_value', and 'properties_json'. The key 'rarity_level' is optional.")
            prompt_lines.append(f"  - All fields ending with `_i18n` (e.g., `name_i18n`) MUST be objects containing two keys: '{bot_language}' and 'en', with string values for the respective translations.")
            prompt_lines.append("  - The 'properties_json' field MUST contain a valid JSON STRING as its value (i.e., a string that can be parsed into a JSON object).")

            example_item_json = {
                "name_i18n": {bot_language: f"Название предмета ({bot_language})", "en": "Item Name (en)"},
                "description_i18n": {bot_language: f"Описание предмета ({bot_language})", "en": "Item Description (en)"},
                "item_type": "specific_item_type_example",
                "base_value": 100,
                "properties_json": json.dumps({"example_property": "example_value", "weight_kg": 0.5, "effect_i18n": {bot_language: "Эффект предмета", "en": "Item Effect"}}),
                "rarity_level": "uncommon"
            }
            prompt_lines.append(f"  - Example structure for one item object: \n{json.dumps(example_item_json, ensure_ascii=False, indent=2)}")

            prompt_lines.append("\nEnsure items are suitable for a fantasy RPG. Be creative with names, descriptions, and properties. The 'properties_json' field is critical for defining game mechanics.")
            prompt_lines.append(f"Please generate the JSON object containing a list of {num_items_to_generate} new items now.")

            return "\n\n".join(prompt_lines)

        except Exception as e:
            # logger.error(f"Error preparing item generation prompt for guild {guild_id}: {e}", exc_info=True)
            return f"Error: Could not prepare prompt for item generation. Details: {e}"

    async def prepare_npc_generation_prompt(
        self,
        guild_id: str,
        db_session: AsyncSession,
        game_manager: "GameManager",
        context_details: Dict[str, Any]
    ) -> str:
        """
        Prepares a detailed prompt for an AI to generate new NPCs.
        context_details can include: location_id, faction_id, role_suggestion,
                                     theme_keywords, num_npcs_to_generate (default 1).
        """
        prompt_lines = []
        try:
            # 1. Determine Language and Number to Generate
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
            num_npcs_to_generate = context_details.get("num_npcs_to_generate", 1)

            # 2. Load Contextual Data
            world_state = await get_entity_by_attributes(db_session, WorldState, {}, guild_id)
            world_state_info = "No specific world state details available."
            world_flags_context_str = ""
            if world_state:
                current_era_native = world_state.current_era_i18n.get(bot_language, world_state.current_era_i18n.get("en", "Current era not specified"))
                if world_state.custom_flags and isinstance(world_state.custom_flags, dict):
                    custom_flags_details = []
                    for key, value in world_state.custom_flags.items():
                        if isinstance(value, bool):
                            if value: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')}.")
                            else: custom_flags_details.append(f"- It is known that {key.replace('_', ' ')} is not the case.")
                        else: custom_flags_details.append(f"- Regarding '{key.replace('_', ' ')}': {value}.")
                    if custom_flags_details:
                        world_flags_context_str = "\n  - Current World State Flags:\n    " + "\n    ".join(custom_flags_details)
                world_state_info = f"Current Era: {current_era_native}.{world_flags_context_str}"

            location_context_info = "No specific location context provided for NPC placement."
            if context_details.get("location_id"):
                loc = await get_entity_by_id(db_session, Location, context_details["location_id"])
                if loc and loc.guild_id == guild_id:
                    loc_name = loc.name_i18n.get(bot_language, loc.name_i18n.get("en", "A location"))
                    location_context_info = f"NPC(s) might appear in or be relevant to Location: {loc_name} (ID: {loc.id})."

            faction_context_info = "No specific faction context provided for NPC affiliation."
            if context_details.get("faction_id"):
                faction = await get_entity_by_id(db_session, GeneratedFaction, context_details["faction_id"])
                if faction and faction.guild_id == guild_id:
                    faction_name = faction.name_i18n.get(bot_language, faction.name_i18n.get("en", "A faction"))
                    faction_ideology = faction.ideology_i18n.get(bot_language, faction.ideology_i18n.get("en", "Unknown ideology")) if faction.ideology_i18n else "Unknown ideology"
                    faction_context_info = f"Consider NPC affiliation with Faction: {faction_name} (ID: {faction.id}) - Ideology: {faction_ideology}."

            lore_info = "No general world lore provided for NPC context."
            if game_manager.lore_manager:
                try:
                    lore_snippets = await game_manager.lore_manager.get_general_world_lore(guild_id, db_session, limit=3)
                    if lore_snippets:
                        lore_info = "General World Lore (for NPC background/knowledge):\n" + "\n".join([f"- {s}" for s in lore_snippets])
                except Exception: pass

            # 3. Fetch NPC Generation Rules (Optional)
            npc_archetypes_default = ["merchant", "guard", "scholar", "artisan", "hermit", "thief", "noble", "peasant", "traveler", "quest_giver", "innkeeper", "blacksmith", "healer", "bandit", "cultist"]
            npc_archetypes_examples = await game_manager.get_rule(guild_id, 'npc_generation_archetypes', npc_archetypes_default)

            personality_traits_default = ["curious", "gruff", "friendly", "suspicious", "talkative", "secretive", "brave", "cowardly", "wise", "foolish", "greedy", "generous", "arrogant", "humble"]
            personality_trait_examples = await game_manager.get_rule(guild_id, 'npc_personality_trait_examples', personality_traits_default)

            # --- Assemble Prompt String ---
            prompt_lines.append(f"You are an expert NPC designer for a fantasy text-based RPG. Generate {num_npcs_to_generate} unique and interesting NPCs suitable for the given context.")

            prompt_lines.append("\nCONTEXT & GUIDELINES:")
            prompt_lines.append(f"  - Guild/World Language for i18n fields: {bot_language} (English 'en' must also be provided).")
            prompt_lines.append(f"  - World State Context: {world_state_info}")
            if location_context_info: prompt_lines.append(f"  - Location Context: {location_context_info}")
            if faction_context_info: prompt_lines.append(f"  - Faction Context: {faction_context_info}")
            if context_details.get('role_suggestion'): prompt_lines.append(f"  - Role Suggestion: {context_details['role_suggestion']}.")
            if context_details.get('theme_keywords'): prompt_lines.append(f"  - Incorporate themes like: {', '.join(context_details['theme_keywords'])}.")
            if lore_info: prompt_lines.append(f"  - {lore_info}")
            prompt_lines.append(f"  - Example NPC Archetypes: {', '.join(npc_archetypes_examples)}.")
            prompt_lines.append(f"  - Example Personality Traits: {', '.join(personality_trait_examples)}.")

            prompt_lines.append("\nDETAILS FOR EACH NPC TO GENERATE:")
            prompt_lines.append("  - `name_i18n`: Full name (localized for '{bot_language}' and 'en').")
            prompt_lines.append("  - `description_i18n`: Physical appearance, typical attire, and general demeanor (localized for '{bot_language}' and 'en').")
            prompt_lines.append("  - `backstory_i18n`: A brief, intriguing backstory or origin (localized for '{bot_language}' and 'en').")
            prompt_lines.append("  - `persona_i18n`: Key personality traits, motivations, quirks, and goals (localized for '{bot_language}' and 'en' - paragraph or bullet points).")
            prompt_lines.append("  - `archetype` (string): A specific archetype or role (e.g., \"wandering merchant\", \"retired city guard captain\", \"secretive scholar of forbidden lore\"). Should be inspired by common archetypes or be a sensible specific one.")
            prompt_lines.append("  - `initial_dialogue_greeting_i18n` (Optional): A simple, characteristic greeting the NPC might say when first encountered (localized for '{bot_language}' and 'en').")
            prompt_lines.append("  - `faction_affiliation_id` (Optional, string): If relevant, suggest a faction name or concept if a specific ID is not known. The system will attempt to map this to an ID later.")

            prompt_lines.append("\nOUTPUT FORMAT (CRITICAL):")
            prompt_lines.append("  - The entire output MUST be a single valid JSON object.")
            prompt_lines.append("  - The JSON object should contain a single top-level key: `\"new_npcs\"`.")
            prompt_lines.append("  - The value of `\"new_npcs\"` MUST be a list, where each item in the list is an object representing a single generated NPC.")
            prompt_lines.append("  - Each NPC object must have the keys: 'name_i18n', 'description_i18n', 'backstory_i18n', 'persona_i18n', 'archetype'. The keys 'initial_dialogue_greeting_i18n' and 'faction_affiliation_id' are optional.")
            prompt_lines.append(f"  - All fields ending with `_i18n` (e.g., `name_i18n`) MUST be objects containing two keys: '{bot_language}' and 'en', with string values for the respective translations.")

            example_npc_json = {
                "name_i18n": {bot_language: f"Имя NPC ({bot_language})", "en": "NPC Name (en)"},
                "description_i18n": {bot_language: f"Описание NPC ({bot_language})", "en": "NPC Description (en)"},
                "backstory_i18n": {bot_language: f"Предыстория NPC ({bot_language})", "en": "NPC Backstory (en)"},
                "persona_i18n": {bot_language: f"Личность NPC ({bot_language})", "en": "NPC Persona (en)"},
                "archetype": "example_archetype (e.g., wandering merchant)",
                "initial_dialogue_greeting_i18n": {bot_language: f"Приветствие NPC ({bot_language})", "en": "NPC Greeting (en)"},
                "faction_affiliation_id": "placeholder_faction_name_or_concept"
            }
            prompt_lines.append(f"  - Example structure for one NPC object: \n{json.dumps(example_npc_json, ensure_ascii=False, indent=2)}")

            prompt_lines.append("\nEnsure NPCs are distinct, memorable, and fit a fantasy RPG setting. Their persona and backstory should offer potential for interaction or quests. Avoid generic descriptions.")
            prompt_lines.append(f"Please generate the JSON object containing a list of {num_npcs_to_generate} new NPCs now.")

            return "\n\n".join(prompt_lines)

        except Exception as e:
            # logger.error(f"Error preparing NPC generation prompt for guild {guild_id}: {e}", exc_info=True)
            return f"Error: Could not prepare prompt for NPC generation. Details: {e}"
