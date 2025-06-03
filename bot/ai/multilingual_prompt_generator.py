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
            # Ensure main language is part of the target if it's different
            # Or decide on a fixed set like ["en", "ru"] always.
            # For now, let's assume the issue means always generate "en" and "ru".
            pass

    def _get_base_system_prompt(self) -> str:
        """
        Base instructions for the AI, including multilingual JSON output format.
        """
        # Construct the language fields string, e.g., "{\"en\": \"...", \"ru\": \"..."}"
        lang_fields_example = ", ".join([f'\"{lang}\": \"..."' for lang in self.target_languages])

        # Ensure the JSON structure is clearly defined in the prompt.
        # Example: "For any text content like names, descriptions, dialogues, quest objectives, etc.,
        # you MUST provide it in a JSON object format with keys for each language: {LANG_FIELDS_EXAMPLE}."
        # Replace LANG_FIELDS_EXAMPLE with the actual constructed string.

        # Using f-string for clarity, ensure proper escaping if this string is itself part of another layer of formatting.
        # The double backslashes for quotes inside the example JSON string are intentional for the final prompt string.
        # Example: {"ru": "текст на русском", "en": "text in english"}

        # Simplified example for the plan:
        json_format_instruction = "You are a helpful assistant for a text-based RPG. Generate all textual content (names, descriptions, dialogues, quest text, etc.) in a JSON structure with keys for English ('en') and Russian ('ru'). For example, a name field should be like: {\"name_i18n\": {\"en\": \"English Name\", \"ru\": \"Русское Имя\"}}. Apply this to all user-facing text strings."

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
            print(f"Error serializing context data to JSON: {e}")
            # Fallback or simplified context if serialization fails
            context_json_string = json.dumps({"error": "context_serialization_failed", "detail": str(e)})

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
        # Gather context using the collector
        # The target_entity_id for get_full_context might be the player if scaling to them,
        # or None if this NPC is context-agnostic or uses player_level_override.
        # For now, let's assume context is general or player_level_override is used.
        context_target_id = None # Or a relevant player character ID if scaling to a specific player
        context_target_type = None # Or "character"

        # If player_level_override is provided, we might want to inject it into context gathering,
        # or the AI can be told to use it directly.
        # For now, the context collector's get_player_level_context would need adaptation or this is handled in the prompt.

        context_data = self.context_collector.get_full_context(
            guild_id=guild_id,
            target_entity_id=context_target_id,
            target_entity_type=context_target_type
        )
        if player_level_override is not None: # Add/override level info if provided
            context_data.setdefault("target_player_level_for_scaling", player_level_override)

        task_prompt = f"""
Generate a complete profile for an NPC.
NPC Identifier/Concept: {npc_id_idea}

The profile must include:
- Name (multilingual: name_i18n: {{"en": "...", "ru": "..."}})
- Role in the world (multilingual: role_i18n: {{"en": "...", "ru": "..."}})
- Character/Personality traits (multilingual: personality_i18n: {{"en": "...", "ru": "..."}})
- Motivations (multilingual: motivation_i18n: {{"en": "...", "ru": "..."}})
- Attributes/Stats (using attribute names from game_rules context, e.g., {{"strength": 12, "dexterity": 10, ...}})
- Skills (using skill names from game_rules context, e.g., {{"stealth": 45, "persuasion": 60, ...}})
- Abilities (list of ability IDs from game_rules context, with multilingual names, e.g., [{{"id": "ability_id_1", "name_i18n": ...}}])
- Spells (list of spell IDs from game_rules context, with multilingual names, e.g., [{{"id": "spell_id_1", "name_i18n": ...}}])
- Initial Inventory (list of item template IDs from game_rules context, with quantities, e.g., [{{"item_template_id": "potion_health_minor", "quantity": 2}}])
- Faction affiliations (e.g., [{{"faction_id": "thieves_guild", "rank_i18n": {{"en": "Initiate", "ru": "Посвященный"}}}}])
- Initial relationships with key factions or other NPCs (e.g., [{{"target_entity_id": "faction_city_guard", "relationship_type": "hostile", "strength": -50}}])
- Dialogue lines or style hints (multilingual: dialogue_hints_i18n: {{"en": "...", "ru": "..."}})

Adjust the NPC's capabilities (stats, skills, inventory quality) based on the target_player_level_for_scaling provided in the context, if available.
Ensure all textual fields are in the specified multilingual JSON format.
"""
        return self._build_full_prompt_for_openai(task_prompt, context_data)

    def generate_quest_prompt(self, guild_id: str, quest_idea: str, triggering_entity_id: Optional[str] = None) -> Dict[str, str]:
        """Generates a prompt to create a structured quest."""
        context_data = self.context_collector.get_full_context(guild_id=guild_id, target_entity_id=triggering_entity_id, target_entity_type="character" if triggering_entity_id else None)

        task_prompt = f"""
Design a complete, structured quest based on the following idea:
Quest Idea/Trigger: {quest_idea}

The quest structure must include:
- Title (multilingual: title_i18n: {{"en": "...", "ru": "..."}})
- Description (multilingual: description_i18n: {{"en": "...", "ru": "..."}}, outlining the premise and what the player needs to do)
- Suggested Level (integer, appropriate for the player level in context if available)
- Quest Giver (optional NPC ID or description, multilingual if new: quest_giver_i18n: {{...}})
- Sequence of Steps (an array of objects, each step having):
    - step_id (unique string identifier for the step)
    - description_i18n (multilingual: {{"en": "...", "ru": "..."}} for what the player needs to do for this step)
    - requirements_description_i18n (multilingual: {{"en": "...", "ru": "..."}} detailing conditions like 'Defeat X', 'Talk to Y', 'Find Z item', 'Go to location A')
    - objective_type (e.g., "kill", "collect", "goto", "talk", "use_skill", "event_trigger")
    - target (e.g., specific NPC ID, item template ID, location ID, monster type name from rules)
    - quantity (if applicable, e.g., for kill or collect objectives)
    - skill_check (optional, e.g., {{"skill": "lockpicking", "dc": 15, "description_i18n": {{...}} }})
    - alternative_solutions_i18n (optional, multilingual: {{"en": "...", "ru": "..."}} describing other ways to complete the step, e.g., stealth vs. combat)
- Abstract Goals (optional, array of objects with description_i18n and success_criteria_i18n)
- Consequences (multilingual description of how World State and relationships might change upon completion or failure: consequences_i18n: {{...}})
    - world_state_changes (optional, array of specific changes, e.g., [{{"type": "change_location_state", "location_id": "...", "new_state": "liberated"}}])
    - relationship_changes (optional, array of changes, e.g., [{{"target_id": "faction_villagers", "change_amount": 20, "type": "faction"}}])
- Rewards:
    - experience_points (integer)
    - gold (integer)
    - items (optional, list of item template IDs with quantities, e.g., [{{"item_template_id": "magic_sword_1", "quantity": 1}}])
    - relationship_rewards (optional, similar to relationship_changes)
    - ability_unlocks (optional, list of ability IDs)
Ensure all textual fields are in the specified multilingual JSON format.
Scale difficulty and rewards based on player level from context if available.
"""
        return self._build_full_prompt_for_openai(task_prompt, context_data)

    def generate_item_description_prompt(self, guild_id: str, item_idea: str) -> Dict[str, str]:
        """Generates a prompt for item name, description, and properties."""
        context_data = self.context_collector.get_full_context(guild_id=guild_id)

        task_prompt = f"""
Generate details for a game item based on the following idea:
Item Idea/Keywords: {item_idea}

The item details must include:
- Name (multilingual: name_i18n: {{"en": "...", "ru": "..."}})
- Description (multilingual: description_i18n: {{"en": "...", "ru": "..."}})
- Type (e.g., "weapon", "armor", "potion", "ring", "quest_item", "resource", using types from game_rules context if applicable)
- Properties (a dictionary of key-value pairs, using property names from game_rules context where possible, e.g., {{"damage": "1d8", "damage_type": "fire", "weight": 0.5, "value": 100, "effect": "heal_20hp"}}). For textual properties, use multilingual format.
- Icon (suggest an emoji or a descriptive keyword for an icon)
- Value/Price (integer, based on rules and item power from context)
Ensure all textual fields are in the specified multilingual JSON format.
"""
        return self._build_full_prompt_for_openai(task_prompt, context_data)

    def generate_location_description_prompt(self, guild_id: str, location_idea: str, existing_location_id: Optional[str] = None) -> Dict[str, str]:
        """Generates a prompt for an atmospheric location description and potential new connections."""
        context_data = self.context_collector.get_full_context(guild_id=guild_id, target_entity_id=existing_location_id, target_entity_type="location" if existing_location_id else None)

        task_prompt = f"""
Generate an atmospheric description for a game location.
Location Idea/Current Location ID: {location_idea}

The output must include:
- Name (if a new location, multilingual: name_i18n: {{"en": "...", "ru": "..."}})
- Atmospheric Description (multilingual: description_i18n: {{"en": "...", "ru": "..."}}, focusing on sights, sounds, smells, and overall mood. This should be rich and evocative.)
- Points of Interest (optional, list of multilingual descriptions for specific features within the location: points_of_interest_i18n: [{{ "name_i18n": {{...}}, "description_i18n": {{...}} }}])
- New Connections/Exits (optional, list of potential new exits or connections to other locations, including a brief multilingual description of the path: new_connections_i18n: [{{ "to_location_idea_i18n": {{...}}, "path_description_i18n": {{...}} }}])
Ensure all textual fields are in the specified multilingual JSON format.
Incorporate elements from the lore and world state context if relevant.
"""
        return self._build_full_prompt_for_openai(task_prompt, context_data)
