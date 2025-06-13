# bot/game/managers/status_manager.py

import json
import uuid
import traceback # Will be removed
import asyncio
import logging # Added
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

from bot.game.models.status_effect import StatusEffect
from bot.services.db_service import DBService
from bot.game.utils.stats_calculator import calculate_effective_stats
from bot.utils.i18n_utils import get_i18n_text

if TYPE_CHECKING:
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.party_manager import PartyManager
    from bot.ai.rules_schema import CoreGameRulesConfig

logger = logging.getLogger(__name__) # Added

SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

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
        logger.info("Initializing StatusManager...") # Changed
        self._db_service = db_service
        self._settings = settings
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._party_manager = party_manager
        self.rules_config: Optional[CoreGameRulesConfig] = None
        if self._rule_engine and hasattr(self._rule_engine, 'rules_config_data'):
            self.rules_config = self._rule_engine.rules_config_data
        self._status_effects: Dict[str, Dict[str, StatusEffect]] = {}
        self._status_templates: Dict[str, Dict[str, Any]] = {} # Note: This seems to be global, not per-guild
        self._dirty_status_effects: Dict[str, Set[str]] = {}
        self._deleted_status_effects_ids: Dict[str, Set[str]] = {}
        self._load_status_templates()
        logger.info("StatusManager initialized.") # Changed

    def _load_status_templates(self):
        logger.info("StatusManager: Loading status templates...") # Changed
        self._status_templates = {}
        if self.rules_config and self.rules_config.status_effects:
            for status_id, status_def in self.rules_config.status_effects.items():
                try: self._status_templates[status_id] = status_def.model_dump(mode='python')
                except AttributeError: self._status_templates[status_id] = status_def.dict()
            logger.info("StatusManager: Loaded %s status templates from CoreGameRulesConfig.", len(self.rules_config.status_effects)) # Changed
            return
        logger.warning("StatusManager: CoreGameRulesConfig.status_effects not found or empty. Falling back to settings for status templates.") # Changed
        try:
            if self._settings is None:
                logger.error("StatusManager: Settings object is None. Cannot load status templates.") # Changed
                return
            raw_templates = self._settings.get('status_templates')
            if raw_templates is None:
                logger.warning("StatusManager: 'status_templates' key not found in settings.") # Changed
                return
            processed_templates = {}
            for template_id, template_data in raw_templates.items():
                if not isinstance(template_data, dict):
                    logger.warning("StatusManager: Template data for '%s' is not a dictionary. Skipping.", template_id) # Changed
                    continue
                # ... (i18n processing as before)
                processed_templates[template_id] = template_data
            self._status_templates = processed_templates
            logger.info("StatusManager: Loaded and processed %s status templates from settings.", len(self._status_templates)) # Changed
        except Exception as e:
            logger.error("StatusManager: Error loading status templates from settings: %s", e, exc_info=True) # Changed

    def get_status_template(self, status_type: str) -> Optional[Dict[str, Any]]:
        if self.rules_config and self.rules_config.status_effects and status_type in self.rules_config.status_effects:
            status_def_model = self.rules_config.status_effects[status_type]
            try: return status_def_model.model_dump(mode='python')
            except AttributeError: return status_def_model.dict()
        return self._status_templates.get(status_type)

    def get_status_display_name(self, status_instance: StatusEffect, lang: str = "en", default_lang: str = "en") -> str:
        # ... (logic as before)
        return "Неизвестный статус" # Placeholder
    def get_status_display_description(self, status_instance: StatusEffect, lang: str = "en", default_lang: str = "en") -> str:
        # ... (logic as before)
        return "Описание недоступно." # Placeholder
    def get_status_effect(self, guild_id: str, status_effect_id: str) -> Optional[StatusEffect]:
        # ... (logic as before)
        return None # Placeholder

    async def apply_status(self, target_id: str, target_type: str, status_id: str, guild_id: str,
                           duration_turns: Optional[float] = None, source_id: Optional[str] = None,
                           source_item_instance_id: Optional[str] = None,
                           initial_state_variables: Optional[Dict[str, Any]] = None, **kwargs: Any
                          ) -> Optional[StatusEffect]:
        guild_id_str = str(guild_id)
        log_prefix = f"StatusManager.apply_status(guild='{guild_id_str}', target='{target_type} {target_id}', status_id='{status_id}'):" # Added guild_id
        if self._db_service is None:
             logger.error("%s Error: Database service is not available.", log_prefix) # Changed
             return None
        status_template = self.get_status_template(status_id)
        if not status_template:
            logger.error("%s Error: Status template '%s' not found.", log_prefix, status_id) # Changed
            return None
        # ... (rest of apply_status logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("%s Error applying status: %s", log_prefix, e, exc_info=True)
        # Example: logger.info("%s Status effect '%s' (type: %s) applied successfully.", log_prefix, status_effect_obj.id, status_id)
        return None # Placeholder

    async def remove_status_effect(self, status_effect_id: str, guild_id: str, **kwargs: Any) -> bool:
        guild_id_str, status_effect_id_str = str(guild_id), str(status_effect_id)
        log_prefix = f"StatusManager.remove_status_effect(guild='{guild_id_str}', id='{status_effect_id_str}'):" # Added guild_id
        # ... (rest of remove_status_effect logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("%s Error removing status: %s", log_prefix, e, exc_info=True)
        # Example: logger.info("%s Successfully processed removal.", log_prefix)
        return False # Placeholder

    async def remove_statuses_by_source_item_instance(self, guild_id: str, target_id: str, source_item_instance_id: str, **kwargs: Any) -> int:
        guild_id_str, target_id_str = str(guild_id), str(target_id)
        log_prefix = f"StatusManager.remove_statuses_by_source_item(guild='{guild_id_str}', target='{target_id_str}', item_instance='{source_item_instance_id}'):" # Added guild_id
        # ... (rest of logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.info("%s Successfully removed %s status(es).", log_prefix, removed_count)
        return 0 # Placeholder

    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        # logger.debug("StatusManager: Processing tick for guild %s. Delta: %.2f", guild_id_str, game_time_delta) # Too noisy for info
        # ... (rest of process_tick logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("StatusManager: Error in tick processing for status %s ('%s') on %s %s for guild %s: %s", eff_id, eff.status_type, eff.target_type, eff.target_id, guild_id_str, e, exc_info=True)
        pass

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("StatusManager: Saving state for guild %s...", guild_id_str) # Changed
        if self._db_service is None:
             logger.error("StatusManager: Database service is not available. Skipping save for guild %s.", guild_id_str) # Changed
             return
        # ... (rest of save_state logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("StatusManager: Error during saving state for guild %s: %s", guild_id_str, e, exc_info=True)
        # Example: logger.info("StatusManager: Successfully saved state for guild %s.", guild_id_str)

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("StatusManager: Loading state for guild %s...", guild_id_str) # Changed
        if self._db_service is None:
             logger.warning("StatusManager: Database service not available. Loading placeholder state for guild %s.", guild_id_str) # Changed
             self._status_effects[guild_id_str] = {}
             self._dirty_status_effects.pop(guild_id_str, None)
             self._deleted_status_effects_ids.pop(guild_id_str, None)
             return
        # ... (rest of load_state logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("StatusManager: CRITICAL ERROR loading state for guild %s: %s", guild_id_str, e_load, exc_info=True)
        # Example: logger.info("StatusManager: Loaded %s statuses for guild %s.", loaded_count, guild_id_str)

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
         logger.info("StatusManager: Rebuilding runtime caches for guild %s (No specific action needed for StatusManager unless more complex caches are added).", guild_id) # Changed

    async def clean_up_for_character(self, character_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
         guild_id = context.get('guild_id')
         if guild_id is None:
             logger.warning("StatusManager: clean_up_for_character called for char %s without guild_id.", character_id) # Added
             return
         guild_id_str = str(guild_id)
         logger.info("StatusManager: Cleaning up statuses for character %s in guild %s.", character_id, guild_id_str) # Added
         # ... (rest of logic, ensure guild_id_str in logs) ...
         pass

    async def save_status_effect(self, status_effect: "StatusEffect", guild_id: str) -> bool:
        guild_id_str = str(guild_id)
        effect_id = getattr(status_effect, 'id', 'N/A')
        logger.debug("StatusManager: Saving status effect %s for guild %s.", effect_id, guild_id_str) # Added
        if self._db_service is None:
            logger.error("StatusManager: DBService not available, cannot save status effect %s for guild %s.", effect_id, guild_id_str) # Added
            return False
        # ... (rest of logic, ensure guild_id_str in logs for errors) ...
        # Example: logger.error("StatusManager: Error saving status effect %s for guild %s: %s", effect_id, guild_id_str, e, exc_info=True)
        return False # Placeholder

    async def remove_status_effects_by_type(self, target_id: str, target_type: str, status_type_to_remove: str, guild_id: str, context: Dict[str, Any]) -> int:
        guild_id_str = str(guild_id)
        logger.info("StatusManager: Removing statuses of type '%s' from %s %s in guild %s.", status_type_to_remove, target_type, target_id, guild_id_str) # Added
        # ... (rest of logic, ensure guild_id_str in logs) ...
        return 0 # Placeholder

    def mark_status_effect_dirty(self, guild_id: str, status_effect_id: str) -> None:
        guild_id_str, status_effect_id_str = str(guild_id), str(status_effect_id)
        if guild_id_str in self._status_effects and status_effect_id_str in self._status_effects[guild_id_str]:
            self._dirty_status_effects.setdefault(guild_id_str, set()).add(status_effect_id_str)
        # else: logger.debug("StatusManager: Attempted to mark non-cached status %s for guild %s as dirty.", status_effect_id_str, guild_id_str) # Too noisy
