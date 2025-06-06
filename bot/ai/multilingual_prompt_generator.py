# bot/ai/multilingual_prompt_generator.py

import json
from typing import TYPE_CHECKING, Dict, Any, List, Optional

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
        self.main_bot_language = main_bot_language
        self.target_languages = ["en", "ru"] # Default languages for multilingual output
        if self.main_bot_language not in self.target_languages:
            self.target_languages.append(self.main_bot_language)

    def update_main_bot_language(self, new_language: str) -> None:
        """Updates the main bot language used for prompt generation."""
        self.main_bot_language = new_language
        print(f"MultilingualPromptGenerator: Main bot language updated to '{new_language}'.")
        # Optionally, re-evaluate self.target_languages if the new main language should always be included
        if self.main_bot_language not in self.target_languages:
            self.target_languages.append(self.main_bot_language)
            # If target_languages should be strictly main + ru/en, then re-initialize:
            # self.target_languages = list(set(["en", "ru", self.main_bot_language]))


    def _get_base_system_prompt(self) -> str:
        """
        Base instructions for the AI, including multilingual JSON output format.
        """
        # Dynamically generate the language fields example based on target_languages
        # Using sorted list of unique languages to ensure consistent order and no duplicates.
        unique_sorted_languages = sorted(list(set(self.target_languages)))
        lang_fields_example = ", ".join([f'"{lang}": "..."' for lang in unique_sorted_languages])

        json_format_instruction = f"""You are a helpful assistant for a text-based RPG.
Generate ALL user-facing textual content (names, descriptions, dialogues, quest text, item properties, etc.)
in a JSON structure with keys for each target language.
The required language fields are: {{{lang_fields_example}}}.
For example, a name field must be structured as: {{"name_i18n": {{{lang_fields_example}}}}}.
Apply this multilingual JSON format strictly to ALL text meant for the user.
"""

        return f"""{json_format_instruction}
You must use the provided context extensively, including game rules, lore, and existing world state.
Adhere to the specified game rules for character stats, abilities, item properties, etc., using the names and definitions provided in the context.
Content should be creative, engaging, and consistent with a fantasy RPG setting.
If the request implies scaling based on player level, use the player level information from the context to adjust difficulty, complexity, or rewards accordingly.
"""

    def _build_full_prompt_for_openai(self, specific_task_prompt: str, context_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Combines the base system prompt, specific task prompt, and context into a format
        suitable for an OpenAI API call (system and user messages).
        Context data is stringified as JSON to be included in the user prompt.
        """
        system_prompt = self._get_base_system_prompt()

        # Serialize the rich context data into a JSON string to be part of the user prompt
        try:
            context_json_string = json.dumps(context_data, ensure_ascii=False, indent=2)
        except TypeError as e:
            error_message = f"Error serializing context data to JSON for prompt: {e}. Offending data snippet: {str(context_data)[:500]}"
            print(error_message)
            context_json_string = json.dumps({
                "error": "context_serialization_failed",
                "detail": str(e),
                "message": "Problematic context data was omitted from the prompt."
            })

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

    def generate_npc_profile_prompt(self, guild_id: str, npc_id_idea: str, player_level_override: Optional[int] = None) -> Dict[str, str]:
        """
        Generates a prompt to create a full NPC profile.
        npc_id_idea could be a specific ID to flesh out, or a concept for a new NPC.
        player_level_override can be used if the NPC's challenge should be scaled to a specific level.
        """
        context_target_id = None
        context_target_type = None

        context_data = self.context_collector.get_full_context(
            guild_id=guild_id,
            target_entity_id=context_target_id,
            target_entity_type=context_target_type
        )
        if player_level_override is not None:
            context_data.setdefault("target_player_level_for_scaling", player_level_override)

        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(self.target_languages)))])

        task_prompt = f"""
Generate a complete profile for an NPC.
NPC Identifier/Concept: {npc_id_idea}

The profile must include:
- `name_i18n`: {{{lang_example_str}}} (multilingual name)
- `role_i18n`: {{{lang_example_str}}} (multilingual role in the world)
- `personality_i18n`: {{{lang_example_str}}} (multilingual character/personality traits)
- `motivation_i18n`: {{{lang_example_str}}} (multilingual motivations)
- Attributes/Stats: A dictionary using attribute names from `game_rules.attributes` context (e.g., `{{"strength": 12, "dexterity": 10}}`).
- Skills: A dictionary using skill names from `game_rules.skills` context (e.g., `{{"stealth": 45, "persuasion": 60}}`).
- Abilities: A list of objects, each with an `id` (from `game_rules.abilities`) and `name_i18n` (e.g., `[{{"id": "ability_id_1", "name_i18n": {{{lang_example_str}}}}}]`).
- Spells: A list of objects, each with an `id` (from `game_rules.spells`) and `name_i18n` (e.g., `[{{"id": "spell_id_1", "name_i18n": {{{lang_example_str}}}}}]`).
- Initial Inventory: A list of objects, each with `item_template_id` (from `game_rules.item_rules_summary`) and `quantity` (e.g., `[{{"item_template_id": "potion_health_minor", "quantity": 2}}]`).
- Faction affiliations: A list of objects, each with `faction_id` and `rank_i18n` (e.g., `[{{"faction_id": "thieves_guild", "rank_i18n": {{{lang_example_str}}}}}]`).
- Initial relationships: A list of objects, each with `target_entity_id`, `relationship_type` (use standard types like "friendly", "hostile", "neutral" or types from `game_rules.relationship_types` if available), and `strength` (e.g., `[{{"target_entity_id": "faction_city_guard", "relationship_type": "hostile", "strength": -50}}]`).
- `dialogue_hints_i18n`: {{{lang_example_str}}} (multilingual dialogue lines or style hints).

Adjust the NPC's capabilities (stats, skills, inventory quality) based on the `target_player_level_for_scaling` provided in the context, if available.
Ensure all textual fields are in the specified multilingual JSON format.
"""
        return self._build_full_prompt_for_openai(task_prompt, context_data)

    def generate_quest_prompt(self, guild_id: str, quest_idea: str, triggering_entity_id: Optional[str] = None) -> Dict[str, str]:
        """Generates a prompt to create a structured quest."""
        context_data = self.context_collector.get_full_context(guild_id=guild_id, target_entity_id=triggering_entity_id, target_entity_type="character" if triggering_entity_id else None)
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(self.target_languages)))])

        task_prompt = f"""
Design a complete, structured quest based on the following idea:
Quest Idea/Trigger: {quest_idea}

The quest structure must include:
- `title_i18n`: {{{lang_example_str}}} (multilingual title)
- `description_i18n`: {{{lang_example_str}}} (multilingual description outlining the premise and what the player needs to do)
- `suggested_level`: integer (appropriate for the player level in context if available)
- `quest_giver_i18n`: {{{lang_example_str}}} (optional, multilingual name/description of the quest giver if it's a new NPC, otherwise provide existing NPC ID)
- `steps`: An array of step objects, each having:
    - `step_id`: string (unique identifier for the step, e.g., "step_1_defeat_guards")
    - `description_i18n`: {{{lang_example_str}}} (multilingual description of what the player needs to do for this step)
    - `requirements_description_i18n`: {{{lang_example_str}}} (multilingual detailing of conditions, e.g., "Defeat the 3 goblin lookouts", "Talk to Elder Willow", "Find the Sunstone Amulet")
    - `objective_type`: string (e.g., "kill", "collect", "goto", "talk", "use_skill", "event_trigger")
    - `target`: string (e.g., specific NPC ID, item template ID from `game_rules.item_rules_summary`, location ID, or monster type name from `game_rules`)
    - `quantity`: integer (if applicable, e.g., for kill or collect objectives)
    - `skill_check`: optional object (e.g., `{{"skill": "lockpicking", "dc": 15, "description_i18n": {{{lang_example_str}}} }}`)
    - `alternative_solutions_i18n`: optional {{{lang_example_str}}} (multilingual description of other ways to complete the step)
- `abstract_goals_i18n`: optional array of objects, each with `description_i18n`: {{{lang_example_str}}} and `success_criteria_i18n`: {{{lang_example_str}}}
- `consequences_i18n`: {{{lang_example_str}}} (multilingual description of how World State and relationships might change upon completion or failure)
    - `world_state_changes`: optional array of specific changes (e.g., `[{{"type": "change_location_state", "location_id": "...", "new_state": "liberated"}}]`)
    - `relationship_changes`: optional array of changes (e.g., `[{{"target_id": "faction_villagers", "change_amount": 20, "type": "faction"}}]`)
- `rewards`: object containing:
    - `experience_points`: integer
    - `gold`: integer
    - `items`: optional list of objects, each with `item_template_id` (from `game_rules.item_rules_summary`) and `quantity` (e.g., `[{{"item_template_id": "magic_sword_1", "quantity": 1}}]`)
    - `relationship_rewards`: optional array, similar to `relationship_changes`
    - `ability_unlocks`: optional list of ability IDs (from `game_rules.abilities`)
Ensure all textual fields are in the specified multilingual JSON format.
Scale difficulty and rewards based on player level from context if available.
"""
        return self._build_full_prompt_for_openai(task_prompt, context_data)

    def generate_item_description_prompt(self, guild_id: str, item_idea: str) -> Dict[str, str]:
        """Generates a prompt for item name, description, and properties."""
        context_data = self.context_collector.get_full_context(guild_id=guild_id)
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(self.target_languages)))])

        task_prompt = f"""
Generate details for a game item based on the following idea:
Item Idea/Keywords: {item_idea}

The item details must include:
- `name_i18n`: {{{lang_example_str}}} (multilingual name)
- `description_i18n`: {{{lang_example_str}}} (multilingual description)
- `type`: string (e.g., "weapon", "armor", "potion", "ring", "quest_item", "resource", using types from `game_rules.item_rules_summary.[item_template_id].type` context)
- `properties`: A dictionary of key-value pairs. Use property names from `game_rules.item_rules_summary.[item_template_id].properties` or general game rules (e.g., `{{"damage": "1d8", "armor_value": 15, "effect_i18n": {{{lang_example_str}}}}}`). Any textual properties MUST be multilingual.
- `value`: integer (estimated gold value, based on rules from `game_rules` context and item power)
- `icon`: string (suggest an emoji or a descriptive keyword for an icon, e.g., "⚔️", "shield", "red_potion")
Ensure all textual fields are in the specified multilingual JSON format.
"""
        return self._build_full_prompt_for_openai(task_prompt, context_data)

    def generate_location_description_prompt(self, guild_id: str, location_idea: str, existing_location_id: Optional[str] = None) -> Dict[str, str]:
        """Generates a prompt for an atmospheric location description and potential new connections."""
        context_data = self.context_collector.get_full_context(guild_id=guild_id, target_entity_id=existing_location_id, target_entity_type="location" if existing_location_id else None)
        lang_example_str = ", ".join([f'"{lang}": "..."' for lang in sorted(list(set(self.target_languages)))])

        task_prompt = f"""
Generate an atmospheric description for a game location.
Location Idea/Current Location ID: {location_idea}

The output must include:
- `name_i18n`: {{{lang_example_str}}} (multilingual name, if a new location)
- `atmospheric_description_i18n`: {{{lang_example_str}}} (multilingual, rich and evocative description focusing on sights, sounds, smells, and overall mood)
- `points_of_interest_i18n`: optional list of objects, each with `name_i18n`: {{{lang_example_str}}} and `description_i18n`: {{{lang_example_str}}} (for specific features within the location)
- `new_connections_i18n`: optional list of objects, each with `to_location_idea_i18n`: {{{lang_example_str}}} (idea/name for connected location) and `path_description_i18n`: {{{lang_example_str}}} (description of the path leading there)
Ensure all textual fields are in the specified multilingual JSON format.
Incorporate elements from the lore and world state context if relevant.
"""
        return self._build_full_prompt_for_openai(task_prompt, context_data)
