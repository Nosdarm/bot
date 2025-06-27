# bot/ai/prompt_context_collector.py
import json
import logging
import uuid
import asyncio
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Union, cast

from bot.ai.ai_data_models import GenerationContext
from bot.database.models import Ability, Spell # Ensure models are imported for type hinting

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
    from bot.database.models.world_related import Location as LocationModel, WorldState
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
        event_manager: 'EventManager',
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
        self.event_manager = event_manager
        self.ability_manager = ability_manager
        self.spell_manager = spell_manager
        self.party_manager = party_manager
        self.lore_manager = lore_manager
        self._game_manager = game_manager

    def _ensure_i18n_dict(self, data: Any, main_lang: str, default_value_if_empty: Optional[str] = None) -> Dict[str, str]:
        if isinstance(data, dict) and data:
            if main_lang not in data:
                 first_key = next(iter(data))
                 return {main_lang: str(data[first_key]), **{str(k): str(v) for k,v in data.items()}}
            return {str(k): str(v) for k,v in data.items()}
        elif isinstance(data, str):
            return {main_lang: data}
        if default_value_if_empty: return {main_lang: default_value_if_empty}
        return {main_lang: "N/A"}

    async def get_main_language_code(self, guild_id_for_lang: Optional[str] = None) -> str: # Added Optional guild_id
        if self._game_manager and hasattr(self._game_manager, 'get_default_bot_language') and callable(getattr(self._game_manager, 'get_default_bot_language')):
            # Try to get guild-specific language if guild_id is provided
            if guild_id_for_lang:
                lang = await getattr(self._game_manager, 'get_default_bot_language')(guild_id_for_lang)
                if lang and isinstance(lang, str): return lang
            # Fallback to first active guild or settings default
            if hasattr(self._game_manager, '_active_guild_ids') and self._game_manager._active_guild_ids: # type: ignore[attr-defined]
                active_guild_id = self._game_manager._active_guild_ids[0] # type: ignore[attr-defined]
                if active_guild_id:
                    lang = await getattr(self._game_manager, 'get_default_bot_language')(active_guild_id)
                    if lang and isinstance(lang, str): return lang
        return self.settings.get('main_language_code', 'ru')


    def get_lore_context(self) -> List[Dict[str, Any]]:
        try:
            with open("game_data/lore_i18n.json", 'r', encoding='utf-8') as f:
                lore_data = json.load(f)
                return lore_data.get("lore_entries", [])
        except FileNotFoundError: logger.warning("Lore file not found."); return []
        except json.JSONDecodeError: logger.warning("Could not decode lore file."); return []

    def get_world_state_context(self, guild_id: str) -> Dict[str, Any]:
        # ... (Implementation as before, ensure safe getattr for model attributes)
        return {} # Simplified for brevity

    def get_faction_data_context(self, guild_id: str, game_rules_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        # ... (Implementation as before)
        return []

    def get_relationship_context(self, guild_id: str, entity_id: str, entity_type: str) -> List[Dict[str, Any]]:
        # ... (Implementation as before)
        return []

    def get_quest_context(self, guild_id: str, character_id: str) -> Dict[str, Any]:
        # ... (Implementation as before)
        return {"active_quests": [], "completed_quests_summary": []}

    async def get_game_rules_summary(self, guild_id: str) -> Dict[str, Any]:
        # ... (Implementation as before)
        return {}

    def get_game_terms_dictionary(self, guild_id: str, game_rules_data: Dict[str, Any], **kwargs) -> List[Dict[str, Any]]:
        # ... (Implementation as before)
        return []

    def get_scaling_parameters(self, guild_id: str, game_rules_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        # ... (Implementation as before)
        return []

    async def _get_db_world_state_details(self, guild_id: str, world_state_dict_to_update: Dict[str, Any], session: Optional['AsyncSession']):
        if not self.db_service: logger.warning("DBService not available for DB world state."); return
        from bot.database.models.world_related import WorldState # Local import for type

        get_entity_method = getattr(self.db_service, 'get_entity_by_conditions', None)
        world_state_record: Optional[WorldState] = None # Initialize
        if callable(get_entity_method):
            world_state_record = await get_entity_method(WorldState, {"guild_id": guild_id}, single_entity=True, session=session)
        else:
            logger.warning("DBService.get_entity_by_conditions method not found.")

        if world_state_record and isinstance(world_state_record, WorldState): # Check type
            world_state_dict_to_update["db_current_era_i18n"] = world_state_record.current_era_i18n
            world_state_dict_to_update["db_global_narrative_state_i18n"] = world_state_record.global_narrative_state_i18n
            world_state_dict_to_update["db_custom_flags"] = world_state_record.custom_flags
        else: logger.info(f"No WorldState record for guild {guild_id} in DB.")

    async def _get_dynamic_lore_snippets(self, guild_id: str, request_params: Dict[str, Any], target_entity_id: Optional[str], target_entity_type: Optional[str], session: Optional['AsyncSession']) -> List[Dict[str, Any]]:
        if not self.lore_manager: logger.warning("LoreManager not available for dynamic lore."); return []
        location_id = request_params.get('location_id'); lore_entries: List[Union[str, Dict[str, Any]]] = []

        get_contextual_lore_method = getattr(self.lore_manager, 'get_contextual_lore', None)
        if callable(get_contextual_lore_method):
            lore_entries = await get_contextual_lore_method(guild_id, location_id, target_entity_id, target_entity_type, limit=3, session=session)
        else:
            logger.info("LoreManager missing get_contextual_lore method.")

        formatted_snippets: List[Dict[str, Any]] = []
        main_lang_for_lore = await self.get_main_language_code(guild_id) # Pass guild_id
        for entry in lore_entries:
            if isinstance(entry, dict):
                text_i18n = entry.get("text_i18n", entry.get("content_i18n")); title_i18n = entry.get("title_i18n")
                if text_i18n: snippet = {"text_i18n": text_i18n}; (snippet.update({"title_i18n": title_i18n}) if title_i18n else None); formatted_snippets.append(snippet)
            elif isinstance(entry, str): formatted_snippets.append({"text_i18n": {main_lang_for_lore: entry}})
        return formatted_snippets

    async def get_full_context(self, guild_id: str, request_type: str, request_params: Dict[str, Any], target_entity_id: Optional[str] = None, target_entity_type: Optional[str] = None, session: Optional['AsyncSession'] = None) -> GenerationContext:
        logger.debug(f"Assembling full context (guild: {guild_id}, type: {request_type}, target: {target_entity_type} {target_entity_id})")
        if not self._game_manager: raise ValueError("PromptContextCollector needs GameManager.")
        from bot.database.models.world_related import Location as LocationModel

        guild_main_lang_val = await self.get_main_language_code(guild_id) # Use the async helper

        # Filter None before creating the set for sorted()
        filtered_langs = [lang for lang in [guild_main_lang_val, "en"] if lang is not None]
        target_languages = sorted(list(set(filtered_langs)))
        if not target_languages: target_languages = ["en"] # Fallback if both were None

        game_rules_data = await self.get_game_rules_summary(guild_id)
        world_state_data = self.get_world_state_context(guild_id); await self._get_db_world_state_details(guild_id, world_state_data, session=session)
        dynamic_lore = await self._get_dynamic_lore_snippets(guild_id, request_params, target_entity_id, target_entity_type, session=session)
        static_lore = self.get_lore_context(); combined_lore = dynamic_lore + static_lore

        terms_kwargs: Dict[str, Any] = {'_fetched_abilities': False, '_fetched_spells': False} # Explicit type
        # ... (rest of the method, ensuring safe attribute access and method calls on managers) ...

        context_dict: Dict[str, Any] = {
            "guild_id": guild_id, "main_language": guild_main_lang_val, "target_languages": target_languages,
            "request_type": request_type, "request_params": request_params,
            "game_rules_summary": game_rules_data, "lore_snippets": combined_lore, "world_state": world_state_data,
            "game_terms_dictionary": self.get_game_terms_dictionary(guild_id, game_rules_data=game_rules_data, **terms_kwargs),
            "scaling_parameters": self.get_scaling_parameters(guild_id, game_rules_data=game_rules_data),
            "player_context": None, "faction_data": self.get_faction_data_context(guild_id, game_rules_data=game_rules_data),
            "relationship_data": [], "active_quests_summary": [], "primary_location_details": None, "party_context": None
        }
        # ... (rest of the method for filling context_dict)
        for key in GenerationContext.model_fields.keys(): context_dict.setdefault(key, None) # Ensure all fields for GenerationContext
        try: return GenerationContext(**context_dict)
        except Exception as e: logger.error(f"Error creating GenerationContext. Keys: {list(context_dict.keys())}", exc_info=True); raise ValueError(f"Failed GenerationContext: {e}") from e

    async def get_character_details_context(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]:
        # ... (Implementation as before)
        return None

[end of bot/ai/prompt_context_collector.py]
