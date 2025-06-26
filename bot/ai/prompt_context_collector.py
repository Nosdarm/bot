# bot/ai/prompt_context_collector.py
import json
import logging
import uuid
import asyncio
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Union

from bot.ai.ai_data_models import GenerationContext
# Ensure models are imported for type hinting if direct type checks are ever needed, though getattr is used.
from bot.database.models import Ability, Spell

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.ability_manager import AbilityManager
    from bot.game.managers.spell_manager import SpellManager
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.lore_manager import LoreManager
    from bot.database.models import Location as LocationModel, WorldState # Removed Ability, Spell from here as they are globally imported now
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class PromptContextCollector:
    def __init__(
        self,
        settings: Dict[str, Any],
        db_service: 'DBService',
        character_manager: 'CharacterManager',
        npc_manager: 'NpcManager',
        quest_manager: 'QuestManager',
        relationship_manager: 'RelationshipManager',
        item_manager: 'ItemManager',
        location_manager: 'LocationManager',
        event_manager: 'EventManager', # Moved before optional arguments
        ability_manager: Optional['AbilityManager'] = None,
        spell_manager: Optional['SpellManager'] = None,
        party_manager: Optional['PartyManager'] = None,
        lore_manager: Optional['LoreManager'] = None,
        game_manager: Optional['GameManager'] = None
    ):
        self.settings = settings
        self.db_service = db_service
        self.character_manager = character_manager
        self.npc_manager = npc_manager
        self.quest_manager = quest_manager
        self.relationship_manager = relationship_manager
        self.item_manager = item_manager
        self.location_manager = location_manager
        self.event_manager = event_manager # Assignment is correct
        self.ability_manager = ability_manager
        self.spell_manager = spell_manager
        self.party_manager = party_manager
        self.lore_manager = lore_manager
        self._game_manager = game_manager

    def _ensure_i18n_dict(self, data: Any, main_lang: str, default_value_if_empty: Optional[str] = None) -> Dict[str, str]:
        """Ensures the output is a dict with at least the main_lang key."""
        if isinstance(data, dict) and data:
            # If it's already a dict, ensure main_lang is present if possible, or any key.
            if main_lang not in data and not data: # Empty dict
                 if default_value_if_empty: return {main_lang: default_value_if_empty}
                 return {main_lang: "Unknown"} # Fallback for empty
            elif main_lang not in data and data: # Non-empty dict but missing main_lang
                 first_key = next(iter(data))
                 return {main_lang: data[first_key], **data} # Add main_lang with first available value
            return data # Already a dict and contains main_lang or is non-empty
        elif isinstance(data, str): # If it's a plain string, wrap it
            return {main_lang: data}

        # Fallback for other types or if data is None/empty and no default_value_if_empty
        if default_value_if_empty:
            return {main_lang: default_value_if_empty}
        return {main_lang: "N/A"} # General fallback

    def get_main_language_code(self) -> str:
        if self._game_manager and hasattr(self._game_manager, '_active_guild_ids') and self._game_manager._active_guild_ids and hasattr(self._game_manager, 'get_default_bot_language'):
            active_guild_id = self._game_manager._active_guild_ids[0] # type: ignore[attr-defined]
            if active_guild_id:
                return self._game_manager.get_default_bot_language(active_guild_id) # type: ignore[attr-defined]
        return self.settings.get('main_language_code', 'ru')

    def get_lore_context(self) -> List[Dict[str, Any]]:
        try:
            with open("game_data/lore_i18n.json", 'r', encoding='utf-8') as f:
                lore_data = json.load(f)
                return lore_data.get("lore_entries", [])
        except FileNotFoundError: logger.warning(f"Lore file not found at game_data/lore_i18n.json"); return []
        except json.JSONDecodeError: logger.warning(f"Could not decode lore file at game_data/lore_i18n.json"); return []

    def get_world_state_context(self, guild_id: str) -> Dict[str, Any]:
        world_state_context = {}
        active_events_data = []
        if self.event_manager:
            active_events = self.event_manager.get_active_events(guild_id) # type: ignore[attr-defined]
            for event in active_events:
                active_events_data.append({"id": getattr(event, 'id', None), "name": getattr(event, 'name', "Unknown Event"), "current_stage_id": getattr(event, 'current_stage_id', None), "type": getattr(event, 'template_id', None), "is_active": getattr(event, 'is_active', True)})
        world_state_context["active_global_events"] = active_events_data

        key_location_states_data = []
        if self.location_manager:
            all_guild_locations_cache = self.location_manager._location_instances.get(guild_id, {}) # type: ignore[attr-defined]
            for loc_id, loc_data_dict in all_guild_locations_cache.items():
                location_obj = self.location_manager.get_location_instance(guild_id, loc_id) # type: ignore[attr-defined]
                if not location_obj: continue
                state_variables = getattr(location_obj, 'state', {}); status_flags = []
                if state_variables.get('is_destroyed', False): status_flags.append('destroyed')
                if state_variables.get('is_under_attack', False): status_flags.append('under_attack')
                if state_variables.get('is_quest_hub', False): status_flags.append('quest_hub')
                if state_variables.get('has_active_event', False): status_flags.append('active_event_site')
                if status_flags: key_location_states_data.append({"id": loc_id, "name": getattr(location_obj, 'name_i18n', {}).get(self.get_main_language_code(), loc_id), "status_flags": status_flags, "state_variables": state_variables })
        world_state_context["key_location_statuses"] = key_location_states_data

        significant_npc_states_data = []
        if self.npc_manager:
            all_npcs = self.npc_manager.get_all_npcs(guild_id) # type: ignore[attr-defined]
            for npc in all_npcs:
                is_significant = False; significance_reasons = []
                npc_health = getattr(npc, 'health', 0.0); npc_max_health = getattr(npc, 'max_health', 1.0)
                if npc_max_health == 0: npc_max_health = 1.0
                if (npc_health / npc_max_health) < 0.3: is_significant = True; significance_reasons.append("low_health")
                if getattr(npc, 'current_action', None) is not None: is_significant = True; significance_reasons.append("active_action")
                if is_significant: significant_npc_states_data.append({"id": getattr(npc, 'id', None), "name": getattr(npc, 'name', "Unknown NPC"), "health_percentage": round((npc_health / npc_max_health) * 100, 1), "current_action_type": getattr(npc.current_action, 'type', None) if getattr(npc, 'current_action', None) else None, "location_id": getattr(npc, 'location_id', None), "significance_reasons": significance_reasons})
        world_state_context["significant_npc_states"] = significant_npc_states_data

        game_time_string = "Time not available"
        if self._game_manager and hasattr(self._game_manager, 'time_manager') and self._game_manager.time_manager:
            game_time_float = self._game_manager.time_manager.get_current_game_time(guild_id) # type: ignore[attr-defined]
            days = int(game_time_float // 86400); hours = int((game_time_float % 86400) // 3600); minutes = int((game_time_float % 3600) // 60); seconds = int(game_time_float % 60)
            game_time_string = f"Day {days + 1}, {hours:02d}:{minutes:02d}:{seconds:02d}"
        world_state_context["current_time"] = {"game_time_string": game_time_string}
        return world_state_context

    def get_faction_data_context(self, guild_id: str, game_rules_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        faction_data_list = []
        factions_definition = game_rules_data.get("factions_definition", {})
        if isinstance(factions_definition, dict) and factions_definition:
            for faction_id, faction_details in factions_definition.items():
                if isinstance(faction_details, dict): faction_data_list.append({"id": faction_id, "name_i18n": faction_details.get("name_i18n", {"en": faction_id, "ru": faction_id}), "description_i18n": faction_details.get("description_i18n", {"en": "No description.", "ru": "Нет описания."}), "member_archetypes": faction_details.get("member_archetypes", []), "relationships_to_other_factions": faction_details.get("relationships_to_other_factions", {})})
            if faction_data_list: return faction_data_list
        faction_rules = game_rules_data.get("faction_rules", {})
        if isinstance(faction_rules, dict):
            valid_faction_ids = faction_rules.get("valid_faction_ids", [])
            if isinstance(valid_faction_ids, list) and valid_faction_ids:
                for faction_id in valid_faction_ids:
                    if isinstance(faction_id, str): faction_data_list.append({"id": faction_id, "name_i18n": {"en": faction_id, "ru": faction_id}})
                if faction_data_list: return faction_data_list
        return []

    def get_relationship_context(self, guild_id: str, entity_id: str, entity_type: str) -> List[Dict[str, Any]]:
        relationship_data_list = []
        if not self.relationship_manager: logger.warning(f"RelationshipManager not available for guild {guild_id}."); return []
        try:
            relationships = self.relationship_manager.get_relationships_for_entity(guild_id, entity_id) # type: ignore[attr-defined]
            for rel_obj in relationships:
                if rel_obj: rel_dict = rel_obj.to_dict(); relationship_data_list.append({"entity1_id": rel_dict.get("entity1_id"), "entity1_type": rel_dict.get("entity1_type"), "entity2_id": rel_dict.get("entity2_id"), "entity2_type": rel_dict.get("entity2_type"), "relationship_type": rel_dict.get("relationship_type"), "strength": rel_dict.get("strength"), "details": rel_dict.get("details_i18n")})
        except Exception as e: logger.error(f"Error fetching relationships for {entity_id} in guild {guild_id}: {e}", exc_info=True)
        return relationship_data_list

    def get_quest_context(self, guild_id: str, character_id: str) -> Dict[str, Any]:
        active_quests_list, completed_quests_summary_list = [], []
        if not self.quest_manager: logger.warning(f"QuestManager not available for guild {guild_id}."); return {"active_quests": [], "completed_quests_summary": []}
        try:
            active_quest_dicts = self.quest_manager.list_quests_for_character(guild_id, character_id) # type: ignore[attr-defined]
            for q_dict in active_quest_dicts:
                current_stage_id = q_dict.get("current_stage_id"); objectives_desc = "No specific objectives."
                stages_data = q_dict.get("stages")
                if current_stage_id and isinstance(stages_data, dict):
                    stage_data = stages_data.get(current_stage_id)
                    if isinstance(stage_data, dict): desc_i18n = stage_data.get("description_i18n", {}); main_lang = self.get_main_language_code(); objectives_desc = desc_i18n.get(main_lang, desc_i18n.get("en", "Objectives unclear."))
                active_quests_list.append({"id": q_dict.get("id"), "name_i18n": q_dict.get("name_i18n", {"en": "Quest", "ru": "Квест"}), "status": q_dict.get("status", "unknown"), "current_objectives_summary": objectives_desc})
        except Exception as e: logger.error(f"Error fetching active quests for {character_id}: {e}", exc_info=True)
        try:
            completed_ids = self.quest_manager._completed_quests.get(guild_id, {}).get(character_id, []) # type: ignore[attr-defined]
            for q_id in completed_ids:
                q_details = self.quest_manager._all_quests.get(guild_id, {}).get(q_id) # type: ignore[attr-defined]
                q_details_dict = q_details.to_dict() if q_details and hasattr(q_details, 'to_dict') else {}
                completed_quests_summary_list.append({"id": q_id, "name_i18n": q_details_dict.get("name_i18n", {"en": f"Old Tale ({q_id[:4]})", "ru": f"Быль ({q_id[:4]})"}), "outcome": q_details_dict.get("status", "completed")})
        except Exception as e: logger.error(f"Error fetching completed quests for {character_id}: {e}", exc_info=True)
        return {"active_quests": active_quests_list, "completed_quests_summary": completed_quests_summary_list}

    async def get_game_rules_summary(self, guild_id: str) -> Dict[str, Any]:
        logger.debug(f"Fetching game rules context for guild {guild_id}")
        if not self.db_service: logger.error("DBService not available."); return {}
        game_rules_data = await self.db_service.get_rules_config(guild_id) or {}
        attributes = {attr_id: data.get("description_i18n", {}) for attr_id, data in game_rules_data.get("character_stats_rules", {}).get("attributes", {}).items()}
        skills = {skill_id: {"associated_stat": stat_id, "description_i18n": game_rules_data.get("skill_rules", {}).get("skills", {}).get(skill_id, {}).get("description_i18n", {})}
                  for skill_id, stat_id in game_rules_data.get("skill_rules", {}).get("skill_stat_map", {}).items()}
        item_rules_summary = {}
        item_templates_settings = self.settings.get("item_templates", {}); item_templates_rules = game_rules_data.get("item_definitions", {})
        merged_item_templates = {**item_templates_settings, **item_templates_rules}
        for tmpl_id, data in merged_item_templates.items():
            if isinstance(data, dict): item_rules_summary[tmpl_id] = {"type": data.get("type", "unknown"), "properties": list(data.keys()), "name_i18n": data.get("name_i18n", {"en": tmpl_id, "ru": tmpl_id})}
        return {"attributes": attributes, "skills": skills, "item_rules_summary": item_rules_summary}

    def get_game_terms_dictionary(self, guild_id: str, game_rules_data: Dict[str, Any], **kwargs) -> List[Dict[str, Any]]:
        terms: List[Dict[str, Any]] = []
        main_lang = self.get_main_language_code()
        default_description_text = "Описание отсутствует." if main_lang == "ru" else "No description available."

        attributes_data = game_rules_data.get("character_stats_rules", {}).get("attributes", {})
        if isinstance(attributes_data, dict):
            for stat_id, stat_info in attributes_data.items():
                if isinstance(stat_info, dict): terms.append({"id": stat_id, "name_i18n": self._ensure_i18n_dict(stat_info.get("name_i18n"), main_lang, stat_id), "term_type": "stat", "description_i18n": self._ensure_i18n_dict(stat_info.get("description_i18n"), main_lang, default_description_text)})
        skills_data = game_rules_data.get("skill_rules", {}).get("skills", {})
        if isinstance(skills_data, dict):
            for skill_id, skill_info in skills_data.items():
                if isinstance(skill_info, dict): terms.append({"id": skill_id, "name_i18n": self._ensure_i18n_dict(skill_info.get("name_i18n"), main_lang, skill_id), "term_type": "skill", "description_i18n": self._ensure_i18n_dict(skill_info.get("description_i18n"), main_lang, default_description_text)})

        ability_definitions = kwargs.get('_ability_definitions_for_terms', [])
        fetched_abilities_flag = kwargs.get('_fetched_abilities', False) # Check if fetch was attempted

        if ability_definitions:
            for ab_def in ability_definitions: # ab_def is expected to be an object with attributes or a dict
                ability_id = str(getattr(ab_def, 'id', uuid.uuid4()))
                terms.append({
                    "id": ability_id,
                    "name_i18n": self._ensure_i18n_dict(getattr(ab_def, 'name_i18n', {}), main_lang, ability_id),
                    "term_type": "ability",
                    "description_i18n": self._ensure_i18n_dict(getattr(ab_def, 'description_i18n', {}), main_lang, default_description_text),
                    "details": {
                        "cost": getattr(ab_def, 'cost', {}),
                        "effect_i18n": self._ensure_i18n_dict(getattr(ab_def, 'effect_i18n', {}), main_lang)
                    }
                })
        elif fetched_abilities_flag: # Fetch was attempted but returned no definitions
            logger.info(f"No ability definitions found for guild {guild_id} via AbilityManager (data was empty).")
        elif not self.ability_manager: # Manager itself is not available
            logger.warning(f"AbilityManager not available for guild {guild_id}. No abilities added to game terms dictionary.")
            # Removed placeholder ability
        # If manager exists but fetch flag is false, it means get_full_context didn't fetch, which is also a valid state (no log here)

        spell_definitions = kwargs.get('_spell_definitions_for_terms', [])
        fetched_spells_flag = kwargs.get('_fetched_spells', False) # Check if fetch was attempted

        if spell_definitions:
            for sp_def in spell_definitions: # sp_def is expected to be an object with attributes or a dict
                spell_id = str(getattr(sp_def, 'id', uuid.uuid4()))
                terms.append({
                    "id": spell_id,
                    "name_i18n": self._ensure_i18n_dict(getattr(sp_def, 'name_i18n', {}), main_lang, spell_id),
                    "term_type": "spell",
                    "description_i18n": self._ensure_i18n_dict(getattr(sp_def, 'description_i18n', {}), main_lang, default_description_text),
                    "details": {
                        "cost": getattr(sp_def, 'cost', {}),
                        "effect_i18n": self._ensure_i18n_dict(getattr(sp_def, 'effect_i18n', {}), main_lang)
                    }
                })
        elif fetched_spells_flag: # Fetch was attempted but returned no definitions
            logger.info(f"No spell definitions found for guild {guild_id} via SpellManager (data was empty).")
        elif not self.spell_manager: # Manager itself is not available
            logger.warning(f"SpellManager not available for guild {guild_id}. No spells added to game terms dictionary.")
            # Removed placeholder spell
        # If manager exists but fetch flag is false, it means get_full_context didn't fetch (no log here)

        if self.npc_manager and hasattr(self.npc_manager, '_npc_archetypes'):
            for archetype_id, archetype_data in self.npc_manager._npc_archetypes.items(): # type: ignore[attr-defined]
                if isinstance(archetype_data, dict): terms.append({"id": archetype_id, "name_i18n": self._ensure_i18n_dict(archetype_data.get("name_i18n", archetype_data.get("name")), main_lang, archetype_id), "term_type": "npc_archetype", "description_i18n": self._ensure_i18n_dict(archetype_data.get("description_i18n", archetype_data.get("backstory_i18n", archetype_data.get("backstory"))), main_lang, default_description_text)})
        if self.item_manager and hasattr(self.item_manager, '_item_templates'):
            for template_id, item_data in self.item_manager._item_templates.items(): # type: ignore[attr-defined]
                if isinstance(item_data, dict): terms.append({"id": template_id, "name_i18n": self._ensure_i18n_dict(item_data.get("name_i18n"), main_lang, template_id), "term_type": "item_template", "description_i18n": self._ensure_i18n_dict(item_data.get("description_i18n"), main_lang, default_description_text)})
        if self.location_manager and hasattr(self.location_manager, '_location_templates'):
            for template_id, loc_data in self.location_manager._location_templates.items(): # type: ignore[attr-defined]
                if isinstance(loc_data, dict): terms.append({"id": template_id, "name_i18n": self._ensure_i18n_dict(loc_data.get("name_i18n"), main_lang, template_id), "term_type": "location_template", "description_i18n": self._ensure_i18n_dict(loc_data.get("description_i18n"), main_lang, default_description_text)})
        faction_summary_list = self.get_faction_data_context(guild_id, game_rules_data=game_rules_data)
        for faction_info in faction_summary_list:
            if isinstance(faction_info, dict): terms.append({"id": faction_info.get("id", "unknown_faction"), "name_i18n": self._ensure_i18n_dict(faction_info.get("name_i18n"), main_lang, faction_info.get("id", "Unknown Faction")), "term_type": "faction", "description_i18n": self._ensure_i18n_dict(faction_info.get("description_i18n"), main_lang, default_description_text)})
        if self.quest_manager and hasattr(self.quest_manager, '_quest_templates'):
            for template_id, quest_data in self.quest_manager._quest_templates.get(guild_id, {}).items(): # type: ignore[attr-defined]
                if isinstance(quest_data, dict): terms.append({"id": template_id, "name_i18n": self._ensure_i18n_dict(quest_data.get("name_i18n"), main_lang, template_id), "term_type": "quest_template", "description_i18n": self._ensure_i18n_dict(quest_data.get("description_i18n"), main_lang, default_description_text)})
        return terms

    def get_scaling_parameters(self, guild_id: str, game_rules_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        params: List[Dict[str, Any]] = []
        def _add_param(name: str, val: Any, ctx: Optional[str] = None):
            try: params.append({"parameter_name": name, "value": float(val), "context": ctx})
            except (ValueError, TypeError): logger.warning(f"Could not convert value '{val}' to float for param '{name}'.")
        
        character_stats_rules = game_rules_data.get("character_stats_rules", {})
        stat_ranges_by_role = character_stats_rules.get("stat_ranges_by_role", {})
        if isinstance(stat_ranges_by_role, dict):
            for role, role_stats_data in stat_ranges_by_role.items():
                if isinstance(role_stats_data, dict):
                    actual_stats = role_stats_data.get("stats", {})
                    if isinstance(actual_stats, dict):
                        for stat_name, stat_range in actual_stats.items():
                            if isinstance(stat_range, dict):
                                if "min" in stat_range: _add_param(f"npc_stat_{stat_name}_{role}_min", stat_range["min"], f"NPC Role: {role}, Stat: {stat_name}")
                                if "max" in stat_range: _add_param(f"npc_stat_{stat_name}_{role}_max", stat_range["max"], f"NPC Role: {role}, Stat: {stat_name}")
        quest_rules = game_rules_data.get("quest_rules", {})
        if isinstance(quest_rules, dict):
            reward_rules = quest_rules.get("reward_rules", {})
            if isinstance(reward_rules, dict):
                xp_reward_range = reward_rules.get("xp_reward_range", {})
                if isinstance(xp_reward_range, dict):
                    if "min" in xp_reward_range: _add_param("quest_xp_reward_min", xp_reward_range["min"], "Quest general XP reward")
                    if "max" in xp_reward_range: _add_param("quest_xp_reward_max", xp_reward_range["max"], "Quest general XP reward")
        item_rules = game_rules_data.get("item_rules", {})
        if isinstance(item_rules, dict):
            price_ranges_by_type = item_rules.get("price_ranges_by_type", {})
            if isinstance(price_ranges_by_type, dict):
                for item_type, rarity_ranges in price_ranges_by_type.items():
                    if isinstance(rarity_ranges, dict):
                        for rarity, price_range in rarity_ranges.items():
                            if isinstance(price_range, dict):
                                if "min" in price_range: _add_param(f"item_price_{item_type}_{rarity}_min", price_range["min"], f"Item Type: {item_type}, Rarity: {rarity}")
                                if "max" in price_range: _add_param(f"item_price_{item_type}_{rarity}_max", price_range["max"], f"Item Type: {item_type}, Rarity: {rarity}")
        xp_rules = game_rules_data.get("xp_rules", {})
        if isinstance(xp_rules, dict):
            level_diff_modifiers = xp_rules.get("level_difference_modifier", {})
            if isinstance(level_diff_modifiers, dict):
                for diff, modifier in level_diff_modifiers.items():
                    diff_str = str(diff).replace("-", "minus").replace("+", "plus")
                    _add_param(f"xp_modifier_level_diff_{diff_str}", modifier, f"XP modifier for level difference: {diff}")
        return params

    async def _get_db_world_state_details(self, guild_id: str, world_state_dict_to_update: Dict[str, Any], session: Optional['AsyncSession']): # Type hint fix
        if not self.db_service: logger.warning("DBService not available for DB world state."); return
        # Ensure WorldState is imported if used as a type hint or for direct model access
        from bot.database.models import WorldState
        world_state_record = await self.db_service.get_entity_by_conditions(WorldState, {"guild_id": guild_id}, single_entity=True, session=session)
        if world_state_record:
            world_state_dict_to_update["db_current_era_i18n"] = world_state_record.current_era_i18n
            world_state_dict_to_update["db_global_narrative_state_i18n"] = world_state_record.global_narrative_state_i18n
            world_state_dict_to_update["db_custom_flags"] = world_state_record.custom_flags
        else: logger.info(f"No WorldState record for guild {guild_id} in DB.")

    async def _get_dynamic_lore_snippets(self, guild_id: str, request_params: Dict[str, Any], target_entity_id: Optional[str], target_entity_type: Optional[str], session: Optional['AsyncSession']) -> List[Dict[str, Any]]: # Type hint fix
        if not self.lore_manager: logger.warning("LoreManager not available for dynamic lore."); return []
        location_id = request_params.get('location_id'); lore_entries: List[Union[str, Dict[str, Any]]] = []
        if hasattr(self.lore_manager, 'get_contextual_lore'): lore_entries = await self.lore_manager.get_contextual_lore(guild_id, location_id, target_entity_id, target_entity_type, limit=3, session=session)
        else: logger.info("LoreManager missing get_contextual_lore.")
        formatted_snippets: List[Dict[str, Any]] = []
        for entry in lore_entries:
            if isinstance(entry, dict):
                text_i18n = entry.get("text_i18n", entry.get("content_i18n")); title_i18n = entry.get("title_i18n")
                if text_i18n: snippet = {"text_i18n": text_i18n}; (snippet.update({"title_i18n": title_i18n}) if title_i18n else None); formatted_snippets.append(snippet)
            elif isinstance(entry, str): main_lang = self._game_manager.get_default_bot_language(guild_id) if self._game_manager else self.get_main_language_code(); formatted_snippets.append({"text_i18n": {main_lang: entry}})
        return formatted_snippets

    async def get_full_context(self, guild_id: str, request_type: str, request_params: Dict[str, Any], target_entity_id: Optional[str] = None, target_entity_type: Optional[str] = None, session: Optional['AsyncSession'] = None) -> GenerationContext: # Type hint fix
        logger.debug(f"Assembling full context (guild: {guild_id}, type: {request_type}, target: {target_entity_type} {target_entity_id})")
        if not self._game_manager: raise ValueError("PromptContextCollector needs GameManager.")
        # Ensure LocationModel is imported if used as a type hint
        from bot.database.models import Location as LocationModel

        guild_main_lang = await self._game_manager.get_rule(guild_id, "default_language", "en")
        target_languages = sorted(list(set([guild_main_lang, "en"])))
        game_rules_data = await self.get_game_rules_summary(guild_id)
        world_state_data = self.get_world_state_context(guild_id); await self._get_db_world_state_details(guild_id, world_state_data, session=session)
        dynamic_lore = await self._get_dynamic_lore_snippets(guild_id, request_params, target_entity_id, target_entity_type, session=session)
        static_lore = self.get_lore_context(); combined_lore = dynamic_lore + static_lore

        terms_kwargs = {'_fetched_abilities': False, '_fetched_spells': False}
        if self.ability_manager and hasattr(self.ability_manager, 'get_all_ability_definitions_for_guild'):
            try:
                terms_kwargs['_ability_definitions_for_terms'] = await self.ability_manager.get_all_ability_definitions_for_guild(guild_id, session=session) # type: ignore[attr-defined]
                terms_kwargs['_fetched_abilities'] = True
            except Exception as e: logger.error(f"Error fetching ability definitions: {e}", exc_info=True)
        if self.spell_manager and hasattr(self.spell_manager, 'get_all_spell_definitions_for_guild'):
            try:
                terms_kwargs['_spell_definitions_for_terms'] = await self.spell_manager.get_all_spell_definitions_for_guild(guild_id, session=session) # type: ignore[attr-defined]
                terms_kwargs['_fetched_spells'] = True
            except Exception as e: logger.error(f"Error fetching spell definitions: {e}", exc_info=True)


        context_dict: Dict[str, Any] = {
            "guild_id": guild_id, "main_language": guild_main_lang, "target_languages": target_languages,
            "request_type": request_type, "request_params": request_params,
            "game_rules_summary": game_rules_data, "lore_snippets": combined_lore, "world_state": world_state_data,
            "game_terms_dictionary": self.get_game_terms_dictionary(guild_id, game_rules_data=game_rules_data, **terms_kwargs),
            "scaling_parameters": self.get_scaling_parameters(guild_id, game_rules_data=game_rules_data),
            "player_context": None, "faction_data": self.get_faction_data_context(guild_id, game_rules_data=game_rules_data),
            "relationship_data": [], "active_quests_summary": [], "primary_location_details": None, "party_context": None
        }
        loc_id_param = request_params.get("location_id")
        if loc_id_param and self.location_manager:
            # Ensure LocationModel is the correct type for loc_inst
            loc_inst: Optional[LocationModel] = await self.location_manager.get_location_instance(guild_id, str(loc_id_param)) # type: ignore[attr-defined]
            if loc_inst: context_dict["primary_location_details"] = loc_inst.to_dict(); logger.debug(f"Added primary_location_details for {loc_id_param}")
            else: logger.warning(f"Could not fetch details for primary_location_id: {loc_id_param}")
        party_id_param = request_params.get("party_id")
        if party_id_param and self.party_manager and self.character_manager:
            party_obj = self.party_manager.get_party(guild_id, str(party_id_param)) # type: ignore[attr-defined]
            if party_obj:
                party_ctx_data = {"party_id": getattr(party_obj, 'id', str(party_id_param)), "name_i18n": getattr(party_obj, 'name_i18n', {}), "member_details": [], "average_level": None}
                member_levels = []; member_ids_list = getattr(party_obj, 'player_ids', getattr(party_obj, 'player_ids_list', []))
                for member_id in member_ids_list:
                    if not member_id: continue
                    char_obj = await self.character_manager.get_character(guild_id, str(member_id)) # type: ignore[attr-defined]
                    if char_obj: party_ctx_data["member_details"].append({"id": char_obj.id, "name_i18n": char_obj.name_i18n, "level": char_obj.level}); member_levels.append(char_obj.level)
                if member_levels: party_ctx_data["average_level"] = round(sum(member_levels) / len(member_levels), 1)
                context_dict["party_context"] = party_ctx_data; logger.debug(f"Added party_context for {party_id_param}")
            else: logger.warning(f"Could not fetch party details for party_id: {party_id_param}")
        if target_entity_id and target_entity_type == "character":
            # Ensure CharacterModel or similar from character_manager.py is used here if needed
            char_details_ctx = await self.character_manager.get_character_details_context(guild_id, character_id=target_entity_id) # type: ignore[attr-defined]
            context_dict["player_context"] = char_details_ctx
            quest_ctx = self.get_quest_context(guild_id, character_id=target_entity_id)
            if isinstance(quest_ctx, dict): context_dict["active_quests_summary"] = quest_ctx.get("active_quests", [])
            context_dict["relationship_data"] = self.get_relationship_context(guild_id, entity_id=target_entity_id, entity_type="character")
        elif target_entity_id and target_entity_type == "npc":
            context_dict["relationship_data"] = self.get_relationship_context(guild_id, entity_id=target_entity_id, entity_type="npc")
        for key in GenerationContext.model_fields.keys(): context_dict.setdefault(key, None)
        try: return GenerationContext(**context_dict)
        except Exception as e: logger.error(f"Error creating GenerationContext. Keys: {list(context_dict.keys())}", exc_info=True); raise ValueError(f"Failed GenerationContext: {e}") from e

    async def get_character_details_context(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]:
        # Placeholder for a more detailed character context method
        if not self.character_manager: return None
        char_obj = await self.character_manager.get_character(guild_id, character_id) # type: ignore[attr-defined]
        if char_obj:
            return {
                "id": char_obj.id,
                "name_i18n": char_obj.name_i18n,
                "class_i18n": char_obj.class_i18n,
                "level": char_obj.level,
                "current_location_id": char_obj.current_location_id,
                # Add more fields as needed: stats, inventory summary, status effects, etc.
            }
        return None
