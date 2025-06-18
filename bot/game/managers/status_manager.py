# bot/game/managers/status_manager.py

import json
import uuid
import traceback
import asyncio
import logging
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

from pydantic import BaseModel # Added for ApplyStatusResult

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from bot.game.models.status_effect import StatusEffect as PydanticStatusEffect # Pydantic model for definitions
from bot.database.models import Character, Player # SQLAlchemy models
from bot.services.db_service import DBService
# from bot.game.utils.stats_calculator import calculate_effective_stats # Not directly used here, but by CharacterManager
# from bot.utils.i18n_utils import get_i18n_text # Can use a local helper

if TYPE_CHECKING:
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.party_manager import PartyManager
    from bot.ai.rules_schema import CoreGameRulesConfig

logger = logging.getLogger(__name__)

# Pydantic model for apply_status_to_character return type
class ApplyStatusResult(BaseModel):
    applied: bool
    status_key: Optional[str] = None
    status_name: Optional[str] = None
    duration_turns: Optional[int] = None
    instance_id: Optional[str] = None # ID of the specific status instance applied
    message: Optional[str] = None

class StatusManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    def __init__(self,
                 db_service: Optional[DBService] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 rule_engine: Optional['RuleEngine'] = None,
                 time_manager: Optional['TimeManager'] = None,
                 character_manager: Optional['CharacterManager'] = None,
                 npc_manager: Optional['NpcManager'] = None,
                 combat_manager: Optional['CombatManager'] = None,
                 party_manager: Optional['PartyManager'] = None,
                 ):
        logger.info("Initializing StatusManager...")
        self._db_service = db_service
        self._settings = settings if settings is not None else {}
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._character_manager = character_manager

        self.rules_config: Optional[CoreGameRulesConfig] = None
        if self._rule_engine and hasattr(self._rule_engine, 'rules_config_data'):
            self.rules_config = self._rule_engine.rules_config_data

        self._status_effects: Dict[str, Dict[str, PydanticStatusEffect]] = {}
        self._status_templates: Dict[str, Any] = {}
        self._dirty_status_effects: Dict[str, Set[str]] = {}
        self._deleted_status_effects_ids: Dict[str, Set[str]] = {}
        self._load_status_templates()
        logger.info("StatusManager initialized.")

    def _load_status_templates(self): # Unchanged from previous version
        logger.info("StatusManager: Loading status templates...")
        self._status_templates = {}
        if self.rules_config and self.rules_config.status_effects:
            for status_id, status_def in self.rules_config.status_effects.items():
                try: self._status_templates[status_id] = status_def.model_dump(mode='python')
                except AttributeError: self._status_templates[status_id] = status_def.dict() # type: ignore
            logger.info(f"StatusManager: Loaded {len(self.rules_config.status_effects)} status templates from CoreGameRulesConfig.")
            return
        logger.warning("StatusManager: CoreGameRulesConfig.status_effects not found. Falling back to settings if available.")
        # Fallback logic for settings (if any) would go here.

    def get_status_template(self, status_type_or_id: str) -> Optional[Dict[str, Any]]: # Unchanged
        if self.rules_config and self.rules_config.status_effects and status_type_or_id in self.rules_config.status_effects:
            status_def_model = self.rules_config.status_effects[status_type_or_id]
            try: return status_def_model.model_dump(mode='python')
            except AttributeError: return status_def_model.dict() # type: ignore
        return self._status_templates.get(status_type_or_id)

    def _get_localized_status_name(self, status_definition: Dict[str, Any], char_lang: str, fallback_lang: str = "en") -> str:
        """ Safely extracts localized status name. """
        name_i18n = status_definition.get("name_i18n", {})
        if isinstance(name_i18n, dict):
            name = name_i18n.get(char_lang, name_i18n.get(fallback_lang))
            if name: return str(name)
        # Fallback to definition ID or a generic name if no i18n name found
        return str(status_definition.get("id", status_definition.get("status_id", "Unknown Status")))


    async def apply_status_to_character(
        self,
        guild_id: str,
        character_id: str,
        status_id_or_key: str,
        duration_turns: Optional[int] = None,
        source_id: Optional[str] = None,
        source_type: Optional[str] = None,
        session: Optional[AsyncSession] = None
    ) -> ApplyStatusResult:
        if not self._db_service:
            msg = "DBService not available."
            logger.error(f"StatusManager: {msg} Cannot apply status.")
            return ApplyStatusResult(applied=False, message=msg, status_key=status_id_or_key)
        if not self._character_manager:
            msg = "CharacterManager not available."
            logger.error(f"StatusManager: {msg} Cannot apply status (for stat recalc).")
            return ApplyStatusResult(applied=False, message=msg, status_key=status_id_or_key)

        status_definition_dict = self.get_status_template(status_id_or_key)
        if not status_definition_dict:
            msg = f"Status definition for '{status_id_or_key}' not found."
            logger.error(f"StatusManager: {msg} Cannot apply to char {character_id}.")
            return ApplyStatusResult(applied=False, status_key=status_id_or_key, message=msg)

        manage_session = session is None
        actual_session: AsyncSession = session if session else self._db_service.get_session() # type: ignore

        try:
            async with (actual_session.begin() if manage_session else actual_session.begin_nested()): # type: ignore
                character_model = await actual_session.get(Character, character_id)
                if not character_model or str(character_model.guild_id) != guild_id:
                    msg = f"Character {character_id} not found in guild {guild_id}."
                    logger.error(f"StatusManager: {msg} Cannot apply status '{status_id_or_key}'.")
                    return ApplyStatusResult(applied=False, message=msg, status_key=status_id_or_key)

                final_duration = duration_turns
                if final_duration is None:
                    final_duration = status_definition_dict.get('default_duration_turns')

                current_game_turn = None
                char_language = "en" # Default
                if character_model.player_id: # Need to fetch Player for selected_language
                    player_account = await actual_session.get(Player, character_model.player_id)
                    if player_account and player_account.selected_language:
                        char_language = player_account.selected_language

                if self._time_manager:
                    current_game_turn = self._time_manager.get_current_turn(guild_id)
                else:
                    logger.warning("StatusManager: TimeManager not available. 'applied_at_turn' will be None.")

                status_instance_id = str(uuid.uuid4())
                applied_status_data = {
                    "status_id": status_id_or_key,
                    "name_i18n": status_definition_dict.get("name_i18n", {"en": status_id_or_key}),
                    "description_i18n": status_definition_dict.get("description_i18n", {"en": "No description."}),
                    "effects_detail": status_definition_dict.get("effects", []),
                    "duration_turns": final_duration,
                    "applied_at_turn": current_game_turn,
                    "source_id": source_id,
                    "source_type": source_type,
                    "instance_id": status_instance_id
                }

                current_effects_list = list(character_model.status_effects_json or [])
                current_effects_list.append(applied_status_data)
                character_model.status_effects_json = current_effects_list

                flag_modified(character_model, "status_effects_json")
                actual_session.add(character_model)

                await self._character_manager._recalculate_and_store_effective_stats(
                    guild_id, character_id, char_model=character_model, session_for_db=actual_session
                )

                logger.info(f"StatusManager: Applied status '{status_id_or_key}' to char {character_id}, guild {guild_id}. Pending commit.")

            self._character_manager._characters.setdefault(str(guild_id), {})[character_id] = character_model

            localized_status_name = self._get_localized_status_name(status_definition_dict, char_language)
            return ApplyStatusResult(
                applied=True,
                status_key=status_id_or_key,
                status_name=localized_status_name,
                duration_turns=final_duration,
                instance_id=status_instance_id,
                message=f"Status '{localized_status_name}' applied successfully."
            )

        except Exception as e:
            msg = f"Error applying status '{status_id_or_key}' to char {character_id}: {e}"
            logger.error(f"StatusManager: {msg}", exc_info=True)
            return ApplyStatusResult(applied=False, message=msg, status_key=status_id_or_key)
        finally:
            if manage_session: await actual_session.close()

    # ... (Other placeholder methods) ...
    def get_status_display_name(self, status_instance: PydanticStatusEffect, lang: str = "en", default_lang: str = "en") -> str: return "Неизвестный статус"
    def get_status_display_description(self, status_instance: PydanticStatusEffect, lang: str = "en", default_lang: str = "en") -> str: return "Описание недоступно."
    def get_status_effect(self, guild_id: str, status_effect_id: str) -> Optional[PydanticStatusEffect]: return None
    async def remove_status_effect(self, status_effect_id: str, guild_id: str, **kwargs: Any) -> bool: return False
    async def remove_statuses_by_source_item_instance(self, guild_id: str, target_id: str, source_item_instance_id: str, **kwargs: Any) -> int: return 0
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None: pass
    async def save_state(self, guild_id: str, **kwargs: Any) -> None: logger.info(f"StatusManager: save_state for guild {guild_id}.")
    async def load_state(self, guild_id: str, **kwargs: Any) -> None: logger.info(f"StatusManager: load_state for guild {guild_id}.")
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None: logger.info(f"StatusManager: rebuild_runtime_caches for guild {guild_id}.")
    async def clean_up_for_character(self, character_id: str, context: Dict[str, Any], **kwargs: Any) -> None: pass
    async def save_status_effect(self, status_effect: PydanticStatusEffect, guild_id: str) -> bool: return False
    async def remove_status_effects_by_type(self, target_id: str, target_type: str, status_type_to_remove: str, guild_id: str, context: Dict[str, Any]) -> int: return 0
    def mark_status_effect_dirty(self, guild_id: str, status_effect_id: str) -> None: pass
    async def get_active_statuses_for_entity(self, entity_id: str, entity_type: str, guild_id: str) -> List[Any]: return []
```
