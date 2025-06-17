# bot/ai/multilingual_prompt_generator.py

import json
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Tuple # Ensure Tuple is imported

from bot.ai.ai_data_models import GenerationContext, ParsedAiData, ValidationError, ValidatedEntity, ValidationIssue

if TYPE_CHECKING:
    from bot.ai.prompt_context_collector import PromptContextCollector

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
