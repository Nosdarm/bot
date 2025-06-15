# bot/ai/prompt_context_collector.py
import json
import logging # ADDED
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Union
from bot.ai.ai_data_models import GenerationContext # ScalingParameter and GameTerm removed

if TYPE_CHECKING:
    from bot.services.db_service import DBService # ADDED
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.ability_manager import AbilityManager
    from bot.game.managers.spell_manager import SpellManager
    from bot.game.managers.event_manager import EventManager
    # Forward reference for GameManager if needed, or pass settings directly
    # from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__) # ADDED

class PromptContextCollector:
    def __init__(
        self,
        settings: Dict[str, Any],
        character_manager: 'CharacterManager',
        npc_manager: 'NpcManager',
        quest_manager: 'QuestManager',
        relationship_manager: 'RelationshipManager',
        item_manager: 'ItemManager',
        location_manager: 'LocationManager',
        ability_manager: 'AbilityManager',
        spell_manager: 'SpellManager',
        event_manager: 'EventManager',
        db_service: 'DBService' # ADDED
        # Potentially lore_data if loaded separately, or handled via location_manager/settings
    ):
        self.settings = settings
        self.db_service = db_service # ADDED
        self.character_manager = character_manager
        self.npc_manager = npc_manager
        self.quest_manager = quest_manager
        self.relationship_manager = relationship_manager
        self.item_manager = item_manager
        self.location_manager = location_manager
        self.ability_manager = ability_manager
        self.spell_manager = spell_manager
        self.event_manager = event_manager

    def get_main_language_code(self) -> str:
        """Determines the main language code for the bot."""
        return self.settings.get('main_language_code', 'ru') # Default to 'ru' as per plan

    def get_lore_context(self) -> List[Dict[str, Any]]:
        """Gathers lore context from game_data/lore_i18n.json."""
        try:
            with open("game_data/lore_i18n.json", 'r', encoding='utf-8') as f:
                lore_data = json.load(f)
                return lore_data.get("lore_entries", [])
        except FileNotFoundError:
            logger.warning(f"Lore file not found at game_data/lore_i18n.json") # MODIFIED print to logger.warning
            return []
        except json.JSONDecodeError:
            logger.warning(f"Could not decode lore file at game_data/lore_i18n.json") # MODIFIED print to logger.warning
            return []

    def get_world_state_context(self, guild_id: str) -> Dict[str, Any]:
        """Gathers current world state context from various managers."""
        world_state_context = {}

        # 1. Fetch active global events from EventManager
        active_events_data = []
        active_events = self.event_manager.get_active_events(guild_id)
        for event in active_events:
            active_events_data.append({
                "id": getattr(event, 'id', None),
                "name": getattr(event, 'name', "Unknown Event"),
                "current_stage_id": getattr(event, 'current_stage_id', None),
                "type": getattr(event, 'template_id', None), # Assuming template_id can serve as type
                "is_active": getattr(event, 'is_active', True)
            })
        world_state_context["active_global_events"] = active_events_data

        # 2. Fetch key location statuses from LocationManager
        key_location_states_data = []
        # Assuming location_manager stores instances in _location_instances as {guild_id: {loc_id: loc_dict}}
        # Or provides a method like get_all_location_instances(guild_id)
        # For now, directly accessing _location_instances if available, otherwise using get_location_instance if needed.
        # This part might need adjustment based on actual LocationManager implementation.

        # Option A: If LocationManager has get_all_location_instances(guild_id) -> List[Location]
        # all_locations = self.location_manager.get_all_location_instances(guild_id)

        # Option B: Accessing _location_instances directly (less ideal, but for placeholder)
        # This is a simplification. A proper method in LocationManager would be better.
        all_guild_locations_cache = self.location_manager._location_instances.get(guild_id, {})

        for loc_id, loc_data_dict in all_guild_locations_cache.items():
            # loc_data_dict could be a dict or a Location object. Assuming dict from _location_instances.
            # If it's an object: loc_obj = loc_data_dict
            # If it's a dict: loc_obj = self.location_manager.get_location_instance(guild_id, loc_id)
            # For simplicity, let's assume loc_data_dict is the dictionary representation.

            # If loc_data_dict is not a dict (e.g. it's a Location object), convert to dict or access attributes
            # For this example, we'll assume it's a dict as per typical _location_instances structure.
            # If get_location_instance returns a Location object, we'd use that.
            location_obj = self.location_manager.get_location_instance(guild_id, loc_id)
            if not location_obj:
                continue

            state_variables = getattr(location_obj, 'state', {}) # Location.state is Dict[str,Any]
            status_flags = []
            if state_variables.get('is_destroyed', False):
                status_flags.append('destroyed')
            if state_variables.get('is_under_attack', False):
                status_flags.append('under_attack')
            if state_variables.get('is_quest_hub', False):
                status_flags.append('quest_hub')
            if state_variables.get('has_active_event', False): # Example custom flag
                status_flags.append('active_event_site')

            if status_flags: # Only include locations with key statuses
                key_location_states_data.append({
                    "id": loc_id,
                    "name": getattr(location_obj, 'name_i18n', {}).get(self.get_main_language_code(), loc_id),
                    "status_flags": status_flags,
                    "state_variables": state_variables # Optionally include all state_variables
                })
        world_state_context["key_location_statuses"] = key_location_states_data

        # 3. Fetch significant NPC states/updates from NpcManager
        significant_npc_states_data = []
        all_npcs = self.npc_manager.get_all_npcs(guild_id)
        for npc in all_npcs:
            is_significant = False
            significance_reasons = []

            npc_health = getattr(npc, 'health', 0.0)
            npc_max_health = getattr(npc, 'max_health', 1.0) # Avoid division by zero
            if npc_max_health == 0: npc_max_health = 1.0 # Ensure not zero

            if (npc_health / npc_max_health) < 0.3: # Below 30% health
                is_significant = True
                significance_reasons.append("low_health")

            if getattr(npc, 'current_action', None) is not None:
                is_significant = True
                significance_reasons.append("active_action")

            # Example: Check for a specific role or flag in state_variables
            # state_vars = getattr(npc, 'state_variables', {})
            # if state_vars.get('is_vital_quest_npc', False):
            #     is_significant = True
            #     significance_reasons.append("vital_quest_npc")

            if is_significant:
                significant_npc_states_data.append({
                    "id": getattr(npc, 'id', None),
                    "name": getattr(npc, 'name', "Unknown NPC"), # Plain name for now
                    "health_percentage": round((npc_health / npc_max_health) * 100, 1),
                    "current_action_type": getattr(npc.current_action, 'type', None) if getattr(npc, 'current_action', None) else None,
                    "location_id": getattr(npc, 'location_id', None),
                    "significance_reasons": significance_reasons
                    # "state_variables": getattr(npc, 'state_variables', {}) # Optionally include relevant state_variables
                })
        world_state_context["significant_npc_states"] = significant_npc_states_data

        # 4. Fetch current game time string from TimeManager
        # Assuming TimeManager has a method get_current_game_time_string(guild_id)
        # If not, format it from get_current_game_time(guild_id) -> float
        game_time_float = self.settings.get("time_manager").get_current_game_time(guild_id) # Assuming time_manager is in settings

        # Basic formatting: Convert float (seconds) to a readable string (e.g., "Day X, HH:MM:SS")
        # This is a placeholder formatting. A more robust solution might be needed in TimeManager.
        days = int(game_time_float // 86400)
        hours = int((game_time_float % 86400) // 3600)
        minutes = int((game_time_float % 3600) // 60)
        seconds = int(game_time_float % 60)
        game_time_string = f"Day {days + 1}, {hours:02d}:{minutes:02d}:{seconds:02d}" # Example format

        world_state_context["current_time"] = {"game_time_string": game_time_string}

        return world_state_context

    def get_faction_data_context(self, guild_id: str, game_rules_data: Dict[str, Any]) -> List[Dict[str, Any]]: # MODIFIED signature
        """
        Gathers faction data from game settings.
        Attempts to find detailed definitions first, then falls back to basic IDs.
        Uses provided game_rules_data.
        """
        faction_data_list = []
        # game_rules = self.settings.get("game_rules", {}) # REMOVED, use game_rules_data

        # 1. Attempt to retrieve detailed faction definitions
        factions_definition = game_rules_data.get("factions_definition", {})
        if isinstance(factions_definition, dict) and factions_definition:
            for faction_id, faction_details in factions_definition.items():
                if isinstance(faction_details, dict):
                    faction_entry = {
                        "id": faction_id,
                        "name_i18n": faction_details.get("name_i18n", {"en": faction_id, "ru": faction_id}),
                        "description_i18n": faction_details.get("description_i18n", {"en": "No description available.", "ru": "Описание отсутствует."}),
                        "member_archetypes": faction_details.get("member_archetypes", []),
                        "relationships_to_other_factions": faction_details.get("relationships_to_other_factions", {})
                        # Add any other relevant details you expect to find
                    }
                    faction_data_list.append(faction_entry)
            if faction_data_list:
                return faction_data_list

        # 2. If no detailed definitions, fall back to basic faction IDs
        faction_rules = game_rules_data.get("faction_rules", {}) # Use game_rules_data
        if isinstance(faction_rules, dict):
            valid_faction_ids = faction_rules.get("valid_faction_ids", [])
            if isinstance(valid_faction_ids, list) and valid_faction_ids:
                for faction_id in valid_faction_ids:
                    if isinstance(faction_id, str): # Ensure IDs are strings
                        faction_data_list.append({
                            "id": faction_id,
                            "name_i18n": {"en": faction_id, "ru": faction_id} # Generic name from ID
                            # No other details available in this fallback
                        })
                if faction_data_list:
                    return faction_data_list

        # 3. Return empty list if no faction data found
        return []

    def get_relationship_context(self, guild_id: str, entity_id: str, entity_type: str) -> List[Dict[str, Any]]:
        """Gathers relationship context for a given entity using RelationshipManager."""
        relationship_data_list = []

        if not self.relationship_manager:
            logger.warning(f"RelationshipManager not available for guild {guild_id}. Cannot fetch relationship context.") # MODIFIED print to logger.warning
            return []

        try:
            relationships = self.relationship_manager.get_relationships_for_entity(guild_id, entity_id)

            for rel_obj in relationships:
                if rel_obj: # Ensure the object is not None
                    # Use the to_dict() method from the Relationship model
                    rel_dict = rel_obj.to_dict()

                    # Ensure all required keys are present, even if some might be None from to_dict()
                    # The Relationship.to_dict() should provide all necessary fields.
                    # We can add defaults here if any key might be missing from to_dict() output,
                    # but ideally, to_dict() is comprehensive.
                    formatted_rel = {
                        "entity1_id": rel_dict.get("entity1_id"),
                        "entity1_type": rel_dict.get("entity1_type"),
                        "entity2_id": rel_dict.get("entity2_id"),
                        "entity2_type": rel_dict.get("entity2_type"),
                        "relationship_type": rel_dict.get("relationship_type"),
                        "strength": rel_dict.get("strength"),
                        "details": rel_dict.get("details_i18n") # Using details_i18n as per model
                        # Any other fields from rel_dict can be added if needed.
                    }
                    relationship_data_list.append(formatted_rel)
        except Exception as e:
            logger.error(f"Error fetching or processing relationships for entity {entity_id} in guild {guild_id}: {e}", exc_info=True) # MODIFIED print to logger.error
            # Optionally, log traceback: import traceback; traceback.print_exc()
            return [] # Return empty list on error

        return relationship_data_list

    def get_quest_context(self, guild_id: str, character_id: str) -> Dict[str, Any]:
        """Gathers active and completed quest context for a character."""
        active_quests_list = []
        completed_quests_summary_list = []

        if not self.quest_manager:
            logger.warning(f"QuestManager not available for guild {guild_id}. Cannot fetch quest context.") # MODIFIED print to logger.warning
            return {"active_quests": [], "completed_quests_summary": []}

        # 1. Get active quests
        try:
            active_quest_dicts = self.quest_manager.list_quests_for_character(guild_id, character_id)
            for quest_dict in active_quest_dicts:
                # Assuming quest_dict from QuestManager is already somewhat serialized.
                # We need to ensure it has the relevant details for the prompt.
                # 'objectives' might be part of 'stages' or a top-level key.
                # For now, let's assume objectives are described within the current stage or overall description.

                # Try to get current stage and its objectives if possible
                current_stage_id = quest_dict.get("current_stage_id") # Assuming this field exists
                current_objectives_desc = "No specific objectives listed for current stage."

                stages_data = quest_dict.get("stages") # This is Dict[str, Any] from Quest model
                if current_stage_id and isinstance(stages_data, dict):
                    current_stage_data = stages_data.get(current_stage_id)
                    if isinstance(current_stage_data, dict):
                        # Attempt to get i18n description for the current stage
                        # The Quest model has get_stage_description(stage_id)
                        # but here we have a dict.
                        stage_desc_i18n = current_stage_data.get("description_i18n", {})
                        main_lang = self.get_main_language_code()
                        current_objectives_desc = stage_desc_i18n.get(main_lang,
                                                                  stage_desc_i18n.get("en",
                                                                  "Objectives for this stage are not clearly defined."))
                        # If objectives are listed explicitly under a key like 'objectives' within a stage:
                        # current_objectives_list = current_stage_data.get("objectives", [])
                        # current_objectives_desc = "; ".join([obj.get("description", "Unnamed objective") for obj in current_objectives_list])


                serialized_quest = {
                    "id": quest_dict.get("id"),
                    "name_i18n": quest_dict.get("name_i18n", {"en": "Unknown Quest", "ru": "Неизвестный квест"}),
                    "status": quest_dict.get("status", "unknown"),
                    "current_objectives_summary": current_objectives_desc, # Placeholder for now
                    # "full_description_i18n": quest_dict.get("description_i18n"), # Optional: if needed
                }
                active_quests_list.append(serialized_quest)
        except Exception as e:
            logger.error(f"Error fetching active quests for character {character_id} in guild {guild_id}: {e}", exc_info=True) # MODIFIED print to logger.error
            # import traceback; traceback.print_exc();

        # 2. Get completed quests summary
        # QuestManager stores completed quests as guild_id -> character_id -> list of quest_ids
        # It does not have a direct get_completed_quests_summary method returning full details.
        # We'll retrieve IDs and try to get their names from the _all_quests cache if available.
        try:
            completed_quest_ids = self.quest_manager._completed_quests.get(guild_id, {}).get(character_id, [])
            for quest_id in completed_quest_ids:
                quest_details = None
                # Attempt to get full quest data from _all_quests cache in QuestManager
                if hasattr(self.quest_manager, '_all_quests'):
                    quest_obj_from_cache = self.quest_manager._all_quests.get(guild_id, {}).get(quest_id)
                    if quest_obj_from_cache and hasattr(quest_obj_from_cache, 'to_dict'):
                        quest_details = quest_obj_from_cache.to_dict()

                if quest_details:
                    completed_quests_summary_list.append({
                        "id": quest_id,
                        "name_i18n": quest_details.get("name_i18n", {"en": "Completed Quest", "ru": "Завершенный квест"}),
                        "outcome": quest_details.get("status", "completed") # status should be 'completed'
                    })
                else:
                    # Fallback if full details are not found (e.g., quest not in _all_quests)
                    completed_quests_summary_list.append({
                        "id": quest_id,
                        "name_i18n": {"en": f"Completed Quest ({quest_id[:8]})", "ru": f"Завершенный квест ({quest_id[:8]})"},
                        "outcome": "completed"
                    })
        except Exception as e:
            logger.error(f"Error fetching completed quests summary for character {character_id} in guild {guild_id}: {e}", exc_info=True) # MODIFIED print to logger.error
            # import traceback; traceback.print_exc();


        return {
            "active_quests": active_quests_list,
            "completed_quests_summary": completed_quests_summary_list
        }

    async def get_game_rules_summary(self, guild_id: str) -> Dict[str, Any]: # MODIFIED to async
        """Extracts relevant game rules (stats, skills, abilities, items) from settings or DB."""
        logger.debug(f"Fetching game rules context for guild {guild_id}") # MODIFIED print to logger.debug

        if not self.db_service:
            logger.error("PromptContextCollector: DBService not available. Cannot fetch guild-specific game rules.")
            game_rules_data = {}
        else:
            game_rules_data = await self.db_service.get_rules_config(guild_id)
            if game_rules_data is None:
                logger.warning(f"PromptContextCollector: No game rules found for guild {guild_id} in DB. Using empty rules.")
                game_rules_data = {}
        
        # Attributes
        character_stats_rules = game_rules_data.get("character_stats_rules", {})
        attributes_data = character_stats_rules.get("attributes", {})
        attributes = {attr_id: data.get("description_i18n", {"en": "No description", "ru": "Нет описания"}) # Assuming description_i18n exists
                      for attr_id, data in attributes_data.items()}

        # Skills
        skill_rules = game_rules.get("skill_rules", {})
        skill_stat_map_data = skill_rules.get("skill_stat_map", {})
        skills = {skill_id: {"associated_stat": stat_id, "description_i18n": skill_rules.get("skills", {}).get(skill_id, {}).get("description_i18n", {"en": "No description", "ru": "Нет описания"})} # Assuming description_i18n
                  for skill_id, stat_id in skill_stat_map_data.items()}

        # Placeholder for Abilities
        # Real implementation would call:
        # ability_definitions = self.ability_manager.get_all_ability_definitions(guild_id)
        # abilities = {ab_id: {"name_i18n": ab_data.get("name_i18n"), "description_i18n": ab_data.get("description_i18n")} for ab_id, ab_data in ability_definitions.items()}
        abilities_placeholder = {
            "placeholder_ability_id_1": {
                "name_i18n": {"en": "Placeholder Ability 1", "ru": "Способность-заглушка 1"},
                "description_i18n": {"en": "Does placeholder things.", "ru": "Делает заглушечные вещи."}
            },
            "placeholder_ability_id_2": {
                "name_i18n": {"en": "Placeholder Ability 2", "ru": "Способность-заглушка 2"},
                "description_i18n": {"en": "Another placeholder action.", "ru": "Другое заглушечное действие."}
            }
        }

        # Placeholder for Spells
        # Real implementation would call:
        # spell_definitions = self.spell_manager.get_all_spell_definitions(guild_id)
        # spells = {sp_id: {"name_i18n": sp_data.get("name_i18n"), "description_i18n": sp_data.get("description_i18n")} for sp_id, sp_data in spell_definitions.items()}
        spells_placeholder = {
            "placeholder_spell_id_1": {
                "name_i18n": {"en": "Placeholder Spell 1", "ru": "Заклинание-заглушка 1"},
                "description_i18n": {"en": "Casts placeholder magic.", "ru": "Колдует заглушечную магию."}
            }
        }

        # Item Templates: Types and Properties Summary
        item_templates = self.settings.get("item_templates", {})
        item_rules_summary = {}
        for tmpl_id, data in item_templates.items():
            properties = list(data.keys()) # Get all keys as properties
            # Filter out common/meta keys if necessary, e.g., 'name_i18n', 'description_i18n', 'type'
            # For now, including all keys to show available data.
            item_rules_summary[tmpl_id] = {
                "type": data.get("type", "unknown"),
                "properties": properties, # List of all property keys for this item template
                "name_i18n": data.get("name_i18n", {"en": tmpl_id, "ru": tmpl_id})
            }

        return {
            "attributes": attributes,
            "skills": skills,
            "abilities": abilities_placeholder, # Using placeholder
            "spells": spells_placeholder,       # Using placeholder
            "item_rules_summary": item_rules_summary
        }

    async def get_character_details_context(self, guild_id: str, character_id: str) -> Dict[str, Any]: # RENAMED and made async
        """Gathers detailed context for a specific character."""
        default_return = {
            "character_id": character_id,
            "level": 1,
            "party_average_level": 1.0,
            "class_i18n": None,
            "hp": None,
            "max_hp": None,
            "faction_id": None,
            "status_effects": []
        }

        if not self.character_manager:
            logger.warning(f"CharacterManager not available for guild {guild_id}. Cannot fetch character details context.")
            return default_return

        # Assuming self.character_manager.get_character is async
        character = await self.character_manager.get_character(guild_id, character_id)

        if not character:
            logger.warning(f"Character {character_id} not found in guild {guild_id} for character details context.")
            return default_return

        character_level = getattr(character, 'level', 1)
        party_average_level: Optional[float] = None

        # Party average level calculation (remains synchronous if party_manager methods are sync)
        party_id_to_check = getattr(character, 'current_party_id', None)
        if party_id_to_check is None:
            party_id_to_check = getattr(character, 'party_id', None)

        if party_id_to_check and hasattr(self, 'party_manager') and self.party_manager: # Check if party_manager exists
            party = self.party_manager.get_party(guild_id, party_id_to_check) # Assuming get_party is sync
            if party:
                member_ids = getattr(party, 'player_ids_list', []) # Assuming this attribute exists and is list of char IDs
                if isinstance(member_ids, list) and member_ids:
                    member_levels = []
                    for member_id in member_ids:
                        # This could be async if get_character is always async
                        member_char = await self.character_manager.get_character(guild_id, member_id)
                        if member_char:
                            member_levels.append(getattr(member_char, 'level', 1))
                    if member_levels:
                        party_average_level = sum(member_levels) / len(member_levels)
                        party_average_level = round(party_average_level, 1)
        
        if party_average_level is None:
            party_average_level = float(character_level)

        # Fetch other details
        character_class_i18n = getattr(character, 'class_i18n', None)
        current_hp = getattr(character, 'current_hp', None) # Pydantic model uses current_hp
        max_hp = getattr(character, 'max_hp', None) # Pydantic model uses max_hp
        faction_id = getattr(character, 'faction_id', None) # Attempt to get, will be None if not present
        status_effects = getattr(character, 'status_effects', []) # Assuming it's a list

        return {
            "character_id": character_id,
            "level": character_level,
            "party_average_level": party_average_level,
            "class_i18n": character_class_i18n,
            "hp": current_hp,
            "max_hp": max_hp,
            "faction_id": faction_id,
            "status_effects": status_effects
        }

    def _ensure_i18n_dict(self, text_or_dict: Optional[Union[str, Dict[str, str]]], default_lang: str, default_text: str = "") -> Dict[str, str]:
        """Ensures that the output is an i18n dictionary."""
        if text_or_dict is None:
            return {default_lang: default_text}
        if isinstance(text_or_dict, dict):
            if not text_or_dict and default_text: # If empty dict and default_text is provided
                 return {default_lang: default_text}
            if default_lang not in text_or_dict and text_or_dict and default_text: # If lang not in dict, dict not empty, and default_text is provided
                # This condition might be too complex or not hit if default_text is only for None/empty dict.
                # Simplified: if default_lang not in text_or_dict and default_text, add it.
                # However, the original logic was to use first_val if default_lang is missing.
                # Reverting to a slightly modified original logic for safety:
                first_val = next(iter(text_or_dict.values()), None) # Get first value or None
                # if default_lang not in text_or_dict and first_val is not None: # If lang missing and dict not empty
                #    text_or_dict[default_lang] = first_val
                # elif default_lang not in text_or_dict and default_text: # If lang missing and dict empty (or first_val was None)
                #    text_or_dict[default_lang] = default_text

            # Simpler approach for ensuring default_lang key if dict is not empty:
            if text_or_dict and default_lang not in text_or_dict:
                 val_to_use = next(iter(text_or_dict.values()), default_text if default_text else "") # Ensure some value
                 text_or_dict[default_lang] = val_to_use
            elif not text_or_dict and default_text: # If dict is empty and default_text provided
                 return {default_lang: default_text}


            return text_or_dict
        return {default_lang: str(text_or_dict)}

    def get_game_terms_dictionary(self, guild_id: str, game_rules_data: Dict[str, Any]) -> List[Dict[str, Any]]: # MODIFIED signature
        """Compiles a list of game terms from various managers and settings. Uses provided game_rules_data."""
        terms: List[Dict[str, Any]] = []
        # game_rules = self.settings.get("game_rules", {}) # REMOVED, use game_rules_data
        main_lang = self.get_main_language_code()
        default_description = {"en": "No description available.", main_lang: "Описание отсутствует."}


        # 1. Stats
        attributes_data = game_rules_data.get("character_stats_rules", {}).get("attributes", {}) # Use game_rules_data
        if isinstance(attributes_data, dict):
            for stat_id, stat_info in attributes_data.items():
                if isinstance(stat_info, dict):
                    terms.append({
                        "id": stat_id,
                        "name_i18n": self._ensure_i18n_dict(stat_info.get("name_i18n"), main_lang, stat_id),
                        "term_type": "stat",
                        "description_i18n": self._ensure_i18n_dict(stat_info.get("description_i18n"), main_lang, default_description[main_lang])
                    })
                else:
                    terms.append({"id": stat_id, "name_i18n": {main_lang: stat_id}, "term_type": "stat", "description_i18n": default_description.copy()})

        # 2. Skills
        skills_data = game_rules_data.get("skill_rules", {}).get("skills", {}) # Use game_rules_data
        if isinstance(skills_data, dict):
            for skill_id, skill_info in skills_data.items():
                if isinstance(skill_info, dict):
                    terms.append({
                        "id": skill_id,
                        "name_i18n": self._ensure_i18n_dict(skill_info.get("name_i18n"), main_lang, skill_id),
                        "term_type": "skill",
                        "description_i18n": self._ensure_i18n_dict(skill_info.get("description_i18n"), main_lang, default_description[main_lang])
                    })
                else:
                    terms.append({"id": skill_id, "name_i18n": {main_lang: skill_id}, "term_type": "skill", "description_i18n": default_description.copy()})

        # 3. Abilities
        if self.ability_manager and hasattr(self.ability_manager, '_ability_templates'):
            for ability_id, ability_obj in self.ability_manager._ability_templates.get(guild_id, {}).items():
                if hasattr(ability_obj, 'name') and hasattr(ability_obj, 'description'):
                    terms.append({
                        "id": ability_id,
                        "name_i18n": self._ensure_i18n_dict(getattr(ability_obj, 'name', ability_id), main_lang, ability_id),
                        "term_type": "ability",
                        "description_i18n": self._ensure_i18n_dict(getattr(ability_obj, 'description', None), main_lang, default_description[main_lang])
                    })

        # 4. Spells
        if self.spell_manager and hasattr(self.spell_manager, '_spell_templates'):
            for spell_id, spell_obj in self.spell_manager._spell_templates.get(guild_id, {}).items():
                 if hasattr(spell_obj, 'name') and hasattr(spell_obj, 'description'):
                    terms.append({
                        "id": spell_id,
                        "name_i18n": self._ensure_i18n_dict(getattr(spell_obj, 'name', spell_id), main_lang, spell_id),
                        "term_type": "spell",
                        "description_i18n": self._ensure_i18n_dict(getattr(spell_obj, 'description', None), main_lang, default_description[main_lang])
                    })

        # 5. NPC Archetypes
        if self.npc_manager and hasattr(self.npc_manager, '_npc_archetypes'):
            for archetype_id, archetype_data in self.npc_manager._npc_archetypes.items():
                if isinstance(archetype_data, dict):
                    desc = archetype_data.get("description_i18n", archetype_data.get("backstory_i18n", archetype_data.get("backstory")))
                    terms.append({
                        "id": archetype_id,
                        "name_i18n": self._ensure_i18n_dict(archetype_data.get("name_i18n", archetype_data.get("name")), main_lang, archetype_id),
                        "term_type": "npc_archetype",
                        "description_i18n": self._ensure_i18n_dict(desc, main_lang, default_description[main_lang])
                    })

        # 6. Item Templates
        if self.item_manager and hasattr(self.item_manager, '_item_templates'):
            for template_id, item_data in self.item_manager._item_templates.items():
                if isinstance(item_data, dict):
                    terms.append({
                        "id": template_id,
                        "name_i18n": self._ensure_i18n_dict(item_data.get("name_i18n"), main_lang, template_id),
                        "term_type": "item_template",
                        "description_i18n": self._ensure_i18n_dict(item_data.get("description_i18n"), main_lang, default_description[main_lang])
                    })

        # 7. Location Templates
        if self.location_manager and hasattr(self.location_manager, '_location_templates'):
            for template_id, loc_data in self.location_manager._location_templates.items():
                if isinstance(loc_data, dict):
                    terms.append({
                        "id": template_id,
                        "name_i18n": self._ensure_i18n_dict(loc_data.get("name_i18n"), main_lang, template_id),
                        "term_type": "location_template",
                        "description_i18n": self._ensure_i18n_dict(loc_data.get("description_i18n"), main_lang, default_description[main_lang])
                    })

        # 8. Factions
        # Call with game_rules_data
        faction_summary_list = self.get_faction_data_context(guild_id, game_rules_data=game_rules_data)
        for faction_info in faction_summary_list:
            if isinstance(faction_info, dict):
                terms.append({
                    "id": faction_info.get("id", "unknown_faction"),
                    "name_i18n": self._ensure_i18n_dict(faction_info.get("name_i18n"), main_lang, faction_info.get("id", "Unknown Faction")),
                    "term_type": "faction",
                    "description_i18n": self._ensure_i18n_dict(faction_info.get("description_i18n"), main_lang, default_description[main_lang])
                })

        # 9. Quest Templates
        if self.quest_manager and hasattr(self.quest_manager, '_quest_templates'):
            for template_id, quest_data in self.quest_manager._quest_templates.get(guild_id, {}).items():
                if isinstance(quest_data, dict):
                    terms.append({
                        "id": template_id,
                        "name_i18n": self._ensure_i18n_dict(quest_data.get("name_i18n"), main_lang, template_id),
                        "term_type": "quest_template",
                        "description_i18n": self._ensure_i18n_dict(quest_data.get("description_i18n"), main_lang, default_description[main_lang])
                    })

        return terms

    def get_scaling_parameters(self, guild_id: str, game_rules_data: Dict[str, Any]) -> List[Dict[str, Any]]: # MODIFIED signature
        """Extracts various scaling parameters from game rules. Uses provided game_rules_data."""
        params: List[Dict[str, Any]] = []
        # game_rules_data_local = self.settings.get("game_rules", {}) # REMOVED, use game_rules_data parameter
        # The parameter is already named game_rules_data, so direct use is fine.

        def _add_param(name: str, val: Any, ctx: Optional[str] = None):
            try:
                params.append({"parameter_name": name, "value": float(val), "context": ctx}) # Changed to dict
            except (ValueError, TypeError):
                logger.warning(f"Could not convert value '{val}' to float for scaling parameter '{name}'. Skipping.") # MODIFIED print to logger.warning

        # 1. NPC Stat Scaling (from character_stats_rules.stat_ranges_by_role)
        # This part assumes game_rules_data is loaded correctly from DB or settings.
        # game_rules_data is now sourced from DB via get_game_rules_summary
        # However, get_scaling_parameters itself is not async and get_game_rules_summary is.
        # This means get_scaling_parameters needs game_rules_data passed to it, or it needs to become async too.
        # For now, I will assume game_rules_data is passed if this method is called from an async method.
        # The current call from get_full_context will be problematic if get_game_rules_summary is not awaited there.
        # Let's assume get_full_context passes the result of awaited get_game_rules_summary to this,
        # or this method is refactored to take game_rules_data as param.
        # For this subtask, I'll modify it to take game_rules_data.

        # Re-evaluating: get_scaling_parameters is called by get_full_context.
        # get_full_context will call `await self.get_game_rules_summary(guild_id)`.
        # So, `self.settings.get("game_rules", {})` needs to be replaced with the result from that call.
        # This means `get_scaling_parameters` doesn't need to change its direct data source if get_full_context provides it.
        # The prompt asks to modify `get_game_rules_summary` to fetch from DB.
        # `get_scaling_parameters`'s use of `self.settings.get("game_rules", {})` is now incorrect.
        # It should use the same DB-fetched rules.
        # This implies `get_scaling_parameters` should also be async or take `game_rules_data` as an argument.
        # Let's make it take `game_rules_data` as an argument for simplicity in this step.
        # I will modify its signature and the call in get_full_context.

        # **Correction**: The instruction is to modify `get_game_rules_summary`.
        # `get_scaling_parameters` and `get_game_terms_dictionary` also use `self.settings.get("game_rules", {})`.
        # They should ideally use the DB-fetched rules as well.
        # This subtask only specified changes for `get_game_rules_summary`'s data source.
        # I will stick to that, but note this dependency.
        # For now, `get_scaling_parameters` will keep using `self.settings` as per current structure,
        # which means it might use stale or global rules, not guild-specific if `game_rules` was only in settings.
        # This is a limitation of the current refactoring scope. # This comment is now less relevant here.
        
        character_stats_rules = game_rules_data.get("character_stats_rules", {}) # Use game_rules_data parameter
        stat_ranges_by_role = character_stats_rules.get("stat_ranges_by_role", {})
        if isinstance(stat_ranges_by_role, dict):
            for role, role_stats_data in stat_ranges_by_role.items():
                if isinstance(role_stats_data, dict): # Should be a dict of stats for the role
                    actual_stats = role_stats_data.get("stats", {}) # The actual stats are under a "stats" key
                    if isinstance(actual_stats, dict):
                        for stat_name, stat_range in actual_stats.items():
                            if isinstance(stat_range, dict):
                                if "min" in stat_range:
                                    _add_param(f"npc_stat_{stat_name}_{role}_min", stat_range["min"], f"NPC Role: {role}, Stat: {stat_name}")
                                if "max" in stat_range:
                                    _add_param(f"npc_stat_{stat_name}_{role}_max", stat_range["max"], f"NPC Role: {role}, Stat: {stat_name}")

        # 2. Quest Reward Scaling (from quest_rules.reward_rules)
        quest_rules = game_rules_data.get("quest_rules", {})
        if isinstance(quest_rules, dict):
            reward_rules = quest_rules.get("reward_rules", {})
            if isinstance(reward_rules, dict):
                xp_reward_range = reward_rules.get("xp_reward_range", {})
                if isinstance(xp_reward_range, dict):
                    if "min" in xp_reward_range:
                        _add_param("quest_xp_reward_min", xp_reward_range["min"], "Quest general XP reward")
                    if "max" in xp_reward_range:
                        _add_param("quest_xp_reward_max", xp_reward_range["max"], "Quest general XP reward")

                # Placeholder for item reward scaling (if schema was extended)
                # item_reward_tiers = reward_rules.get("item_reward_tiers", {})
                # if isinstance(item_reward_tiers, dict):
                #     for level_range, tier_info in item_reward_tiers.items():
                #         if isinstance(tier_info, dict) and "tier_name" in tier_info:
                #             _add_param(f"quest_item_reward_tier_{level_range}", tier_info["tier_name"], f"Quest item reward tier for level {level_range}")

        # 3. Item Price Scaling (from item_rules.price_ranges_by_type)
        item_rules = game_rules_data.get("item_rules", {})
        if isinstance(item_rules, dict):
            price_ranges_by_type = item_rules.get("price_ranges_by_type", {})
            if isinstance(price_ranges_by_type, dict):
                for item_type, rarity_ranges in price_ranges_by_type.items():
                    if isinstance(rarity_ranges, dict):
                        for rarity, price_range in rarity_ranges.items():
                            if isinstance(price_range, dict):
                                if "min" in price_range:
                                    _add_param(f"item_price_{item_type}_{rarity}_min", price_range["min"], f"Item Type: {item_type}, Rarity: {rarity}")
                                if "max" in price_range:
                                    _add_param(f"item_price_{item_type}_{rarity}_max", price_range["max"], f"Item Type: {item_type}, Rarity: {rarity}")

        # 4. General Difficulty/Scaling Parameters (e.g., from xp_rules)
        xp_rules = game_rules_data.get("xp_rules", {})
        if isinstance(xp_rules, dict):
            level_diff_modifiers = xp_rules.get("level_difference_modifier", {})
            if isinstance(level_diff_modifiers, dict):
                for diff, modifier in level_diff_modifiers.items():
                    # Ensure diff is a string that can be part of a parameter name
                    diff_str = str(diff).replace("-", "minus").replace("+", "plus")
                    _add_param(f"xp_modifier_level_diff_{diff_str}", modifier, f"XP modifier for level difference: {diff}")

            # Example: if there was a general enemy HP scale factor
            # enemy_scaling = game_rules_data.get("enemy_scaling_rules", {})
            # if isinstance(enemy_scaling, dict) and "hp_scale_per_player_level" in enemy_scaling:
            #     _add_param("enemy_hp_scale_factor_per_player_level", enemy_scaling["hp_scale_per_player_level"], "General enemy HP scaling")

        # Add some pre-existing generic placeholders if they are still relevant or not covered by specific rules
        # These were in the original method, might be superseded by more specific rules now.
        # params.append(ScalingParameter(parameter_name="generic_difficulty_scalar_low_level", value=0.8, context="player_level_1-5"))
        # params.append(ScalingParameter(parameter_name="generic_difficulty_scalar_mid_level", value=1.0, context="player_level_6-10"))

        # It's better to derive such generic scalars from more granular rules if possible,
        # or define them explicitly in game_rules if they are truly global overrides.
        # For now, let's rely on what's extracted from the structured rules.

        return params

    async def get_full_context(self, guild_id: str, request_type: str, request_params: Dict[str, Any], target_entity_id: Optional[str] = None, target_entity_type: Optional[str] = None) -> GenerationContext: # MODIFIED to async
        """
        Assembles all context components.
        guild_id is needed for manager calls that are guild-specific.
        target_entity_id and target_entity_type are for context specific to an entity (e.g., player character, NPC).
        """
        logger.debug(f"Assembling full context (guild: {guild_id}, request_type: {request_type}, target: {target_entity_type} {target_entity_id})") # MODIFIED print to logger.debug

        # Fetch guild-specific game rules once
        game_rules_data_for_guild = await self.get_game_rules_summary(guild_id)

        context_dict: Dict[str, Any] = {
            "guild_id": guild_id,
            "main_language": self.get_main_language_code(),
            "target_languages": self.settings.get("target_languages", ["en", "ru"]),
            "request_type": request_type,
            "request_params": request_params,
            "game_rules_summary": game_rules_data_for_guild, # Use fetched data
            "lore_snippets": self.get_lore_context(),
            "world_state": self.get_world_state_context(guild_id),
            "game_terms_dictionary": self.get_game_terms_dictionary(guild_id, game_rules_data=game_rules_data_for_guild), # MODIFIED call
            "scaling_parameters": self.get_scaling_parameters(guild_id, game_rules_data=game_rules_data_for_guild), # MODIFIED call
            "player_context": None,
            "faction_data": self.get_faction_data_context(guild_id, game_rules_data=game_rules_data_for_guild), # MODIFIED call
            "relationship_data": [],
            "active_quests_summary": [],
        }

        if target_entity_id and target_entity_type == "character":
            character_details_ctx = await self.get_character_details_context(guild_id, character_id=target_entity_id) # MODIFIED call
            context_dict["player_context"] = character_details_ctx # MODIFIED assignment

            quest_ctx = self.get_quest_context(guild_id, character_id=target_entity_id)
            if isinstance(quest_ctx, dict):
                context_dict["active_quests_summary"] = quest_ctx.get("active_quests", [])
            context_dict["relationship_data"] = self.get_relationship_context(guild_id, entity_id=target_entity_id, entity_type="character")

        elif target_entity_id and target_entity_type == "npc":
            context_dict["relationship_data"] = self.get_relationship_context(guild_id, entity_id=target_entity_id, entity_type="npc")

        try:
            generation_context_model = GenerationContext(**context_dict)
            return generation_context_model
        except Exception as e:
            logger.error(f"Error creating GenerationContext model from dict. Keys: {list(context_dict.keys())}", exc_info=True) # MODIFIED print to logger.error
            # logger.error(f"Pydantic Validation Error: {e}", exc_info=True) # Included in above
            raise ValueError(f"Failed to construct GenerationContext: {e}") from e
