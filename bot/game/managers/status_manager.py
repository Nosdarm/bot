# bot/game/managers/status_manager.py

import json
import uuid
import traceback # Will be removed
import asyncio
import logging # Added
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

from bot.game.models.status_effect import StatusEffect # Pydantic model
from bot.database.models import Status as SQLAlchemyStatus # SQLAlchemy model
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
        logger.info("Initializing StatusManager...")
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
        self._status_templates: Dict[str, Dict[str, Any]] = {}
        self._dirty_status_effects: Dict[str, Set[str]] = {}
        self._deleted_status_effects_ids: Dict[str, Set[str]] = {}
        self._load_status_templates()
        logger.info("StatusManager initialized.")

    def _load_status_templates(self):
        logger.info("StatusManager: Loading status templates...")
        self._status_templates = {}
        if self.rules_config and self.rules_config.status_effects:
            for status_id, status_def in self.rules_config.status_effects.items():
                try: self._status_templates[status_id] = status_def.model_dump(mode='python')
                except AttributeError: self._status_templates[status_id] = status_def.dict()
            log_msg_rules = f"Loaded {len(self.rules_config.status_effects)} status templates from CoreGameRulesConfig."
            logger.info(f"StatusManager: {log_msg_rules}")
            return
        log_msg_fallback = "CoreGameRulesConfig.status_effects not found or empty. Falling back to settings for status templates."
        logger.warning(f"StatusManager: {log_msg_fallback}")
        try:
            if self._settings is None:
                log_msg_no_settings = "Settings object is None. Cannot load status templates."
                logger.error(f"StatusManager: {log_msg_no_settings}")
                return
            raw_templates = self._settings.get('status_templates')
            if raw_templates is None:
                log_msg_no_key = "'status_templates' key not found in settings."
                logger.warning(f"StatusManager: {log_msg_no_key}")
                return
            processed_templates = {}
            for template_id, template_data in raw_templates.items():
                if not isinstance(template_data, dict):
                    log_msg_skip = f"Template data for '{template_id}' is not a dictionary. Skipping."
                    logger.warning(f"StatusManager: {log_msg_skip}")
                    continue
                processed_templates[template_id] = template_data
            self._status_templates = processed_templates
            log_msg_loaded_settings = f"Loaded and processed {len(self._status_templates)} status templates from settings."
            logger.info(f"StatusManager: {log_msg_loaded_settings}")
        except Exception as e:
            log_msg_err_settings = f"Error loading status templates from settings: {e}"
            logger.error(f"StatusManager: {log_msg_err_settings}", exc_info=True)

    def get_status_template(self, status_type: str) -> Optional[Dict[str, Any]]:
        if self.rules_config and self.rules_config.status_effects and status_type in self.rules_config.status_effects:
            status_def_model = self.rules_config.status_effects[status_type]
            try: return status_def_model.model_dump(mode='python')
            except AttributeError: return status_def_model.dict()
        return self._status_templates.get(status_type)

    def get_status_display_name(self, status_instance: StatusEffect, lang: str = "en", default_lang: str = "en") -> str:
        return "Неизвестный статус"
    def get_status_display_description(self, status_instance: StatusEffect, lang: str = "en", default_lang: str = "en") -> str:
        return "Описание недоступно."
    def get_status_effect(self, guild_id: str, status_effect_id: str) -> Optional[StatusEffect]:
        return None

    async def apply_status(self, target_id: str, target_type: str, status_id: str, guild_id: str,
                           duration_turns: Optional[float] = None, source_id: Optional[str] = None,
                           source_item_instance_id: Optional[str] = None,
                           initial_state_variables: Optional[Dict[str, Any]] = None, **kwargs: Any
                          ) -> Optional[StatusEffect]:
        guild_id_str = str(guild_id)
        log_prefix = f"StatusManager.apply_status(guild='{guild_id_str}', target='{target_type} {target_id}', status_id='{status_id}'):"
        if self._db_service is None:
             err_msg = f"{log_prefix} Error: Database service is not available."
             logger.error(err_msg)
             return None
        status_template = self.get_status_template(status_id)
        if not status_template:
            err_msg = f"{log_prefix} Error: Status template '{status_id}' not found."
            logger.error(err_msg)
            return None
        return None

    async def remove_status_effect(self, status_effect_id: str, guild_id: str, **kwargs: Any) -> bool:
        guild_id_str, status_effect_id_str = str(guild_id), str(status_effect_id)
        log_prefix = f"StatusManager.remove_status_effect(guild='{guild_id_str}', id='{status_effect_id_str}'):"
        return False

    async def remove_statuses_by_source_item_instance(self, guild_id: str, target_id: str, source_item_instance_id: str, **kwargs: Any) -> int:
        guild_id_str, target_id_str = str(guild_id), str(target_id)
        log_prefix = f"StatusManager.remove_statuses_by_source_item(guild='{guild_id_str}', target='{target_id_str}', item_instance='{source_item_instance_id}'):"
        return 0

    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        pass

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("StatusManager: Saving state for guild %s...", guild_id_str)
        if self._db_service is None:
             err_msg = f"Database service is not available. Skipping save for guild {guild_id_str}."
             logger.error(f"StatusManager: {err_msg}")
             return

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("StatusManager: Loading state for guild %s...", guild_id_str)
        if self._db_service is None:
             warn_msg = f"Database service not available. Loading placeholder state for guild {guild_id_str}."
             logger.warning(f"StatusManager: {warn_msg}")
             self._status_effects[guild_id_str] = {}
             self._dirty_status_effects.pop(guild_id_str, None)
             self._deleted_status_effects_ids.pop(guild_id_str, None)
             return

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
         log_msg = f"Rebuilding runtime caches for guild {guild_id} (No specific action needed for StatusManager unless more complex caches are added)."
         logger.info(f"StatusManager: {log_msg}")

    async def clean_up_for_character(self, character_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
         guild_id = context.get('guild_id')
         if guild_id is None:
             logger.warning("StatusManager: clean_up_for_character called for char %s without guild_id.", character_id)
             return
         guild_id_str = str(guild_id)
         logger.info("StatusManager: Cleaning up statuses for character %s in guild %s.", character_id, guild_id_str)
         pass

    async def save_status_effect(self, status_effect: "StatusEffect", guild_id: str) -> bool:
        guild_id_str = str(guild_id)
        effect_id = getattr(status_effect, 'id', 'N/A')
        logger.debug("StatusManager: Saving status effect %s for guild %s.", effect_id, guild_id_str)
        if self._db_service is None:
            logger.error("StatusManager: DBService not available, cannot save status effect %s for guild %s.", effect_id, guild_id_str)
            return False
        return False

    async def remove_status_effects_by_type(self, target_id: str, target_type: str, status_type_to_remove: str, guild_id: str, context: Dict[str, Any]) -> int:
        guild_id_str = str(guild_id)
        target_id_str = str(target_id)

        logger.info("StatusManager: Removing statuses of type '%s' from %s %s in guild %s.", status_type_to_remove, target_type, target_id_str, guild_id_str)

        removed_count = 0
        guild_statuses = self._status_effects.get(guild_id_str, {})
        if not guild_statuses:
            return 0

        effects_to_check = list(guild_statuses.values())

        for effect in effects_to_check:
            if (str(effect.target_id) == target_id_str and
                effect.target_type == target_type and
                effect.status_type == status_type_to_remove):

                removal_result = await self.remove_status_effect(effect.id, guild_id_str, **context)

                if removal_result == effect.id:
                    removed_count += 1

        logger.info("StatusManager: Successfully removed %s status(es) of type '%s' from %s %s in guild %s.", removed_count, status_type_to_remove, target_type, target_id_str, guild_id_str)
        return removed_count

    def mark_status_effect_dirty(self, guild_id: str, status_effect_id: str) -> None:
        guild_id_str, status_effect_id_str = str(guild_id), str(status_effect_id)
        if guild_id_str in self._status_effects and status_effect_id_str in self._status_effects[guild_id_str]:
            self._dirty_status_effects.setdefault(guild_id_str, set()).add(status_effect_id_str)

    async def get_active_statuses_for_entity(self, entity_id: str, entity_type: str, guild_id: str) -> List[SQLAlchemyStatus]:
        """
        Retrieves all active status effects for a given entity from the database.
        """
        log_prefix = f"StatusManager.get_active_statuses(guild='{guild_id}', target='{entity_type} {entity_id}'):"
        if not self._db_service:
            logger.error(f"{log_prefix} DBService not available.")
            return []
        if not self._time_manager:
            logger.error(f"{log_prefix} TimeManager not available.")
            return []

        try:
            current_time = self._time_manager.get_current_game_time(guild_id) # Synchronous call

            all_statuses_for_entity: List[SQLAlchemyStatus] = await self._db_service.get_entities_by_conditions(
                model_class=SQLAlchemyStatus,
                conditions={'guild_id': guild_id, 'target_id': entity_id, 'target_type': entity_type}
            )

            if not all_statuses_for_entity:
                logger.debug(f"{log_prefix} No statuses found in DB for entity.")
                return []

            active_statuses: List[SQLAlchemyStatus] = []
            for status in all_statuses_for_entity:
                if status.duration_turns is None or status.duration_turns == 0: # Permanent or condition-based
                    active_statuses.append(status)
                    logger.debug(f"{log_prefix} Status '{status.name}' (ID: {status.id}) is active (permanent/conditional).")
                elif status.applied_at is not None and status.duration_turns is not None:
                    if current_time < (status.applied_at + status.duration_turns):
                        active_statuses.append(status)
                        logger.debug(f"{log_prefix} Status '{status.name}' (ID: {status.id}) is active. Ends at {status.applied_at + status.duration_turns}, current time {current_time}.")
                    else:
                        logger.debug(f"{log_prefix} Status '{status.name}' (ID: {status.id}) has expired. Ended at {status.applied_at + status.duration_turns}, current time {current_time}.")
                else:
                    # If duration is not None/0, but applied_at is None, it's indeterminate; treat as inactive or log warning
                    logger.warning(f"{log_prefix} Status '{status.name}' (ID: {status.id}) has duration but no applied_at time. Treating as inactive.")

            logger.info(f"{log_prefix} Found {len(active_statuses)} active statuses out of {len(all_statuses_for_entity)} total for entity.")
            return active_statuses

        except Exception as e:
            logger.error(f"{log_prefix} Error fetching or filtering statuses: {e}", exc_info=True)
            return []

    async def apply_status_to_character(
        self,
        guild_id: str,
        character_id: str,
        status_id_or_key: str,
        duration_turns: Optional[int] = None,
        source_id: Optional[str] = None,
        source_type: Optional[str] = None,
        session: Optional[Any] = None  # Using Any for AsyncSession to avoid direct import
    ) -> bool:
        """
        Applies a status effect to a character by updating Character.status_effects_json.
        Manages SQLAlchemy session if one is not provided.
        """
        from sqlalchemy.ext.asyncio import AsyncSession  # Local import for type safety
        from bot.database.models import Character # SQLAlchemy Character model
        from sqlalchemy.orm.attributes import flag_modified
        import time # For applied_at timestamp if using real time instead of turns

        if not self._db_service:
            logger.error("StatusManager: DBService not available. Cannot apply status.")
            return False

        status_definition = self.get_status_template(status_id_or_key)
        if not status_definition:
            logger.error(f"StatusManager: Status definition for '{status_id_or_key}' not found. Cannot apply status to character {character_id}.")
            return False

        provided_session = session is not None
        db_session: AsyncSession = session if provided_session else self._db_service.get_session() # type: ignore

        try:
            async with db_session.begin_nested() if provided_session else db_session.begin() as transaction: # type: ignore
                character_model = await db_session.get(Character, character_id)
                if not character_model or str(character_model.guild_id) != guild_id:
                    logger.error(f"StatusManager: Character {character_id} not found in guild {guild_id}. Cannot apply status '{status_id_or_key}'.")
                    if not provided_session: await transaction.rollback() # type: ignore
                    return False

                # Determine duration: use provided, then template default, then None
                final_duration = duration_turns
                if final_duration is None: # If not explicitly passed
                    final_duration = status_definition.get('default_duration_turns') # Get from template

                current_game_turn = None
                if self._time_manager:
                    current_game_turn = self._time_manager.get_current_turn(guild_id) # Assuming this is synchronous or fetched appropriately
                else:
                    logger.warning("StatusManager: TimeManager not available. Cannot set 'applied_at_turn'.")

                applied_status_data = {
                    "status_id": status_id_or_key,
                    "name_i18n": status_definition.get("name_i18n", {"en": status_id_or_key}),
                    "description_i18n": status_definition.get("description_i18n", {"en": "No description."}),
                    "effects_detail": status_definition.get("effects", []), # Store actual effects
                    "duration_turns": final_duration,
                    "applied_at_turn": current_game_turn,
                    "source_id": source_id,
                    "source_type": source_type,
                    "instance_id": str(uuid.uuid4()) # Unique ID for this application instance
                }

                if character_model.status_effects_json is None or not isinstance(character_model.status_effects_json, list):
                    character_model.status_effects_json = []

                character_model.status_effects_json.append(applied_status_data)
                flag_modified(character_model, "status_effects_json")
                db_session.add(character_model)

                if not provided_session:
                    await transaction.commit() # type: ignore

                logger.info(f"StatusManager: Applied status '{status_id_or_key}' to character {character_id} in guild {guild_id}.")

                # Trigger stat recalculation if CharacterManager is available
                if self._character_manager:
                    # This call might need to be awaited if _recalculate_and_store_effective_stats becomes fully async
                    # and if the session from this method needs to be passed down.
                    # For now, assuming it can operate with the character model being in the session.
                    await self._character_manager._recalculate_and_store_effective_stats(guild_id, character_id, char_model=character_model)
                    # If the session was internally managed here, the char_model changes (including new effective_stats)
                    # would need another commit or be part of the same transaction.
                    # If CharacterManager's method uses its own session, it's fine.
                    # Best if _recalculate_and_store_effective_stats can use the passed session or if CharacterManager.save_state is called after.
                    # For now, the char_model is already in the session being managed here.
                    # If the session was provided, the caller of apply_status_to_character is responsible for the final commit.
                    if not provided_session: # If we own the session, commit again after recalc if it made further changes not covered by session.add(character_model)
                         async with db_session.begin() as recalc_transaction: # type: ignore
                              db_session.add(character_model) # Ensure it's re-added if recalc modified it
                              await recalc_transaction.commit() # type: ignore

                return True

        except Exception as e:
            logger.error(f"StatusManager: Error applying status '{status_id_or_key}' to character {character_id}: {e}", exc_info=True)
            if not provided_session and 'transaction' in locals() and transaction.is_active: # type: ignore
                await transaction.rollback() # type: ignore
            return False
        finally:
            if not provided_session:
                await db_session.close()
