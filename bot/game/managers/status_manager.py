# bot/game/managers/status_manager.py

# --- Импорты ---
import json
import uuid
import traceback
import asyncio
# ИСПРАВЛЕНИЕ: Добавляем Union
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union # Добавляем Union
# from dataclasses import dataclass, field # dataclass и field не нужны в StatusManager, если только не используются для внутренней вспомогательной структуры, но не для модели NPC.

# Импорт модели StatusEffect (для объектов эффектов)
from bot.game.models.status_effect import StatusEffect
# Импорт адаптера БД
# from bot.database.postgres_adapter import PostgresAdapter # Replaced with DBService
from bot.services.db_service import DBService
# Импорт утилиты для i18n
from bot.utils.i18n_utils import get_i18n_text

if TYPE_CHECKING:
    # Импорты менеджеров, которые нужны StatusManager для получения данных или вызова их методов
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.time_manager import TimeManager # Нужен для получения текущего времени и работы с длительностью
    from bot.game.managers.character_manager import CharacterManager # Нужен для получения целевых персонажей (в process_tick, clean_up)
    from bot.game.managers.npc_manager import NpcManager # Нужен для получения целевых NPC (в process_tick, clean_up)
    from bot.game.managers.combat_manager import CombatManager # Нужен для очистки статусов при завершении боя (clean_up)
    from bot.game.managers.party_manager import PartyManager # Нужен для получения целевых групп (если статусы на группу)
    # from bot.game.managers.location_manager import LocationManager # Если статусы привязаны к локациям
    # from bot.game.event_processors.event_stage_processor import EventStageProcessor # Если статусы привязаны к стадиям событий
    from bot.ai.rules_schema import CoreGameRulesConfig


# Define send callback type (нужен для отправки уведомлений о статусах)
# SendToChannelCallback определен в GameManager, но его можно определить и здесь, если нужно.
SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class StatusManager:
    """
    Менеджер для управления статус-эффектами.
    Отвечает за наложение, снятие, обновление длительности и применение эффектов статусов.
    Централизованно обрабатывается в мировом тике.
    """
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
        print("Initializing StatusManager...")
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

        print("StatusManager initialized.")

    def _load_status_templates(self):
        """Загружает статические шаблоны статус-эффектов из rules_config или settings."""
        print("StatusManager: Loading status templates...")
        self._status_templates = {} # Legacy, prefer rules_config

        if self.rules_config and self.rules_config.status_effects:
            for status_id, status_def in self.rules_config.status_effects.items():
                # Convert Pydantic model to dict to match legacy _status_templates format if needed
                # Or adapt get_status_template to work directly with Pydantic models
                try:
                    self._status_templates[status_id] = status_def.model_dump(mode='python')
                except AttributeError: # Pydantic v1
                    self._status_templates[status_id] = status_def.dict()

            print(f"StatusManager: Loaded {len(self.rules_config.status_effects)} status templates from CoreGameRulesConfig.")
            return

        # Fallback to settings if rules_config is not available or empty
        print("StatusManager: CoreGameRulesConfig.status_effects not found or empty. Falling back to settings for status templates.")
        try:
            if self._settings is None:
                print("StatusManager: Error: Settings object is None. Cannot load status templates.")
                return
            # ... (rest of the settings-based loading logic from previous version) ...
            raw_templates = self._settings.get('status_templates')
            if raw_templates is None:
                print("StatusManager: 'status_templates' key not found in settings.")
                return
            # ... (processing as before)
            processed_templates = {}
            for template_id, template_data in raw_templates.items():
                if not isinstance(template_data, dict):
                    print(f"StatusManager: Warning: Template data for '{template_id}' is not a dictionary. Skipping.")
                    continue
                if not isinstance(template_data.get('name_i18n'), dict):
                    if 'name' in template_data and isinstance(template_data['name'], str):
                        template_data['name_i18n'] = {"en": template_data['name']}
                    else:
                        template_data['name_i18n'] = {"en": template_id}
                    template_data.pop('name', None)
                if not isinstance(template_data.get('description_i18n'), dict):
                    if 'description' in template_data and isinstance(template_data['description'], str):
                        template_data['description_i18n'] = {"en": template_data['description']}
                    else:
                        template_data['description_i18n'] = {"en": "No description."}
                    template_data.pop('description', None)
                processed_templates[template_id] = template_data
            self._status_templates = processed_templates # Overwrite with settings-loaded ones
            print(f"StatusManager: Loaded and processed {len(self._status_templates)} status templates from settings.")

        except Exception as e:
            print(f"StatusManager: Error loading status templates from settings: {e}")
            traceback.print_exc()

    def get_status_template(self, status_type: str) -> Optional[Dict[str, Any]]: # Made async in previous, but templates are sync
        """Получить статический шаблон статуса по его типу (глобально)."""
        # Prioritize rules_config if available
        if self.rules_config and self.rules_config.status_effects and status_type in self.rules_config.status_effects:
            status_def_model = self.rules_config.status_effects[status_type]
            try:
                return status_def_model.model_dump(mode='python')
            except AttributeError: # Pydantic v1
                return status_def_model.dict()
        # Fallback to legacy _status_templates (loaded from settings)
        return self._status_templates.get(status_type)


    def get_status_display_name(self, status_instance: StatusEffect, lang: str = "en", default_lang: str = "en") -> str:
         if not isinstance(status_instance, StatusEffect):
              return "Неизвестный статус"

         tpl = self.get_status_template(status_instance.status_type)

         display_name = status_instance.status_type
         if tpl:
             display_name = get_i18n_text(tpl, "name", lang, default_lang) # tpl is dict here

         desc_parts = [display_name]
         if status_instance.duration is not None:
             desc_parts.append(f"({status_instance.duration:.1f} ост.)")

         return " ".join(desc_parts)

    def get_status_display_description(self, status_instance: StatusEffect, lang: str = "en", default_lang: str = "en") -> str:
        if not isinstance(status_instance, StatusEffect):
            return "Описание недоступно."

        tpl = self.get_status_template(status_instance.status_type)
        if tpl:
            return get_i18n_text(tpl, "description", lang, default_lang)

        return "Описание недоступно."


    def get_status_effect(self, guild_id: str, status_effect_id: str) -> Optional[StatusEffect]:
        guild_id_str = str(guild_id)
        guild_statuses = self._status_effects.get(guild_id_str)
        if guild_statuses:
             return guild_statuses.get(status_effect_id)
        return None

    async def apply_status(self,
                           target_id: str,
                           target_type: str, # "character" or "npc"
                           status_id: str, # This is status_type/template_id from rules_config.status_effects
                           guild_id: str,
                           duration_turns: Optional[float] = None, # Duration in game turns
                           source_id: Optional[str] = None, # E.g., ability_id, trap_id, used for source_item_template_id by ItemManager
                           source_item_instance_id: Optional[str] = None, # Specific item instance ID
                           initial_state_variables: Optional[Dict[str, Any]] = None,
                           **kwargs: Any
                          ) -> Optional[StatusEffect]: # Return StatusEffect object or None
        """
        Applies a new status effect to an entity. Replaces add_status_effect_to_entity.
        Uses status_id (template ID from rules_config.status_effects).
        Stores source_item_instance_id in state_variables.
        """
        guild_id_str = str(guild_id)
        log_prefix = f"StatusManager.apply_status(target='{target_type} {target_id}', status_id='{status_id}', guild='{guild_id_str}'):"

        if self._db_service is None:
             print(f"{log_prefix} Error: Database service is not available.")
             return None

        status_template = self.get_status_template(status_id) # Fetches from rules_config or legacy
        if not status_template:
            print(f"{log_prefix} Error: Status template '{status_id}' not found.")
            return None

        # Resolve duration: use provided, then template default, then None (permanent)
        resolved_duration: Optional[float] = duration_turns
        if resolved_duration is None: # If not provided directly
            # Check for default_duration_turns in the Pydantic model via rules_config
            if self.rules_config and self.rules_config.status_effects and status_id in self.rules_config.status_effects:
                resolved_duration = self.rules_config.status_effects[status_id].default_duration_turns
            elif 'default_duration_turns' in status_template: # Fallback to dict template
                resolved_duration = status_template['default_duration_turns']

        # Ensure resolved_duration is float if not None
        if resolved_duration is not None:
            try:
                resolved_duration = float(resolved_duration)
            except (ValueError, TypeError):
                print(f"{log_prefix} Warning: Invalid duration format '{resolved_duration}'. Setting to permanent.")
                resolved_duration = None


        applied_at_time: Optional[float] = None
        time_mgr = kwargs.get('time_manager', self._time_manager)
        if time_mgr and hasattr(time_mgr, 'get_current_game_time'):
            applied_at_time = time_mgr.get_current_game_time(guild_id_str)


        current_state_vars = initial_state_variables.copy() if initial_state_variables else {}
        if source_item_instance_id:
            current_state_vars['source_item_instance_id'] = source_item_instance_id
        # source_id (template_id) is already a main field.

        # TODO: Stacking Logic
        # Check if a status of this type already exists on the target.
        # Based on rules_config.status_effects[status_id].stacking_policy (e.g., "refresh", "stack", "ignore", "intensify")
        # This is a simplified placeholder for stacking.
        existing_statuses_of_type = [
            se for se_id, se in self._status_effects.get(guild_id_str, {}).items()
            if se.target_id == target_id and se.target_type == target_type and se.status_type == status_id
        ]
        if existing_statuses_of_type:
            # print(f"{log_prefix} Found existing status of type '{status_id}' on target.")
            # Apply stacking rules here. For now, let's assume "refresh" or "ignore" if not stackable.
            # This needs to be driven by status_template.stacking_policy from rules_config
            pass # Add detailed stacking logic later. For now, it will just add another instance.


        try:
            new_effect_id = str(uuid.uuid4())
            status_data: Dict[str, Any] = {
                'id': new_effect_id,
                'status_type': status_id, # This is the template ID
                'target_id': target_id,
                'target_type': target_type,
                'duration': resolved_duration,
                'applied_at': applied_at_time,
                'source_id': source_id, # Used for item_template_id, ability_id etc.
                'guild_id': guild_id_str,
                'state_variables': current_state_vars,
            }

            status_effect_obj = StatusEffect.from_dict(status_data)

            if self._db_service:
                 sql = '''
                     INSERT INTO statuses (id, status_type, target_id, target_type, duration_turns, applied_at, source_id, state_variables, guild_id)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                 '''
                 params = (
                     status_effect_obj.id, status_effect_obj.status_type, status_effect_obj.target_id, status_effect_obj.target_type,
                     status_effect_obj.duration, status_effect_obj.applied_at, status_effect_obj.source_id,
                     json.dumps(status_effect_obj.state_variables),
                     status_effect_obj.guild_id
                 )
                 await self._db_service.adapter.execute(sql, params)

            self._status_effects.setdefault(guild_id_str, {})[status_effect_obj.id] = status_effect_obj
            self.mark_status_effect_dirty(guild_id_str, status_effect_obj.id)

            print(f"{log_prefix} Status effect '{status_effect_obj.id}' (type: {status_id}) applied successfully.")
            # TODO: Notify target entity's manager (CharacterManager, NpcManager) about the new status effect.
            # This allows recalculation of stats or other on-apply logic if needed.
            # Example: self._character_manager.notify_status_applied(guild_id, target_id, status_effect_obj)

            return status_effect_obj

        except Exception as e:
            print(f"{log_prefix} ❌ Error applying status: {e}")
            traceback.print_exc()
            return None

    # add_status_effect_to_entity is now replaced by apply_status
    # async def add_status_effect_to_entity(...): ... (Keep old one commented or remove if sure)


    async def remove_status_effect(self, status_effect_id: str, guild_id: str, **kwargs: Any) -> bool: # Changed return to bool
        guild_id_str = str(guild_id)
        status_effect_id_str = str(status_effect_id)
        log_prefix = f"StatusManager.remove_status_effect(id='{status_effect_id_str}', guild='{guild_id_str}'):"

        eff = self.get_status_effect(guild_id_str, status_effect_id_str)
        if not eff:
            # print(f"{log_prefix} Warning: Status not found in cache. Attempting DB delete if marked previously.")
            # If it was already marked for deletion and removed from cache, DB operation might still be pending.
            # If it's in _deleted_status_effects_ids, this call is redundant for cache, but confirms DB.
            pass

        # TODO: "on_remove" effects from RuleEngine
        # target_entity = ...
        # if rule_engine and eff and target_entity:
        #    await rule_engine.trigger_status_on_remove_effects(eff, target_entity, **kwargs)

        try:
            if self._db_service:
                sql = 'DELETE FROM statuses WHERE id = ? AND guild_id = ?'
                await self._db_service.adapter.execute(sql, (status_effect_id_str, guild_id_str))

            guild_statuses_cache = self._status_effects.get(guild_id_str)
            if guild_statuses_cache:
                 if guild_statuses_cache.pop(status_effect_id_str, None):
                    # print(f"{log_prefix} Removed from active cache.")
                    pass
                 if not guild_statuses_cache:
                      self._status_effects.pop(guild_id_str, None)

            self._dirty_status_effects.get(guild_id_str, set()).discard(status_effect_id_str)
            self._deleted_status_effects_ids.setdefault(guild_id_str, set()).add(status_effect_id_str) # Ensure it's marked for deletion confirmation

            # print(f"{log_prefix} Successfully processed removal.")
            # TODO: Notify target entity's manager about status removal for stat recalculation etc.
            # Example: if eff: self._character_manager.notify_status_removed(guild_id, eff.target_id, eff)
            return True

        except Exception as e:
            print(f"{log_prefix} ❌ Error removing status: {e}")
            traceback.print_exc()
            return False

    async def remove_statuses_by_source_item_instance(self, guild_id: str, target_id: str, source_item_instance_id: str, **kwargs: Any) -> int:
        """
        Removes all status effects from a target that were sourced by a specific item instance.
        Checks state_variables['source_item_instance_id'].
        Returns the count of removed status effects.
        """
        guild_id_str = str(guild_id)
        target_id_str = str(target_id)
        log_prefix = f"StatusManager.remove_statuses_by_source_item(target='{target_id_str}', item_instance='{source_item_instance_id}', guild='{guild_id_str}'):"

        removed_count = 0
        if guild_id_str not in self._status_effects:
            # print(f"{log_prefix} No statuses cached for this guild.")
            return 0

        # Iterate over a copy of status IDs for safe removal from the cache during iteration
        status_ids_to_check = list(self._status_effects.get(guild_id_str, {}).keys())

        for status_effect_id in status_ids_to_check:
            status_effect = self.get_status_effect(guild_id_str, status_effect_id) # Get from cache again, in case it was removed by another call

            if status_effect and \
               status_effect.target_id == target_id_str and \
               isinstance(status_effect.state_variables, dict) and \
               status_effect.state_variables.get('source_item_instance_id') == source_item_instance_id:

                # print(f"{log_prefix} Found matching status '{status_effect.id}' (type: {status_effect.status_type}). Attempting removal.")
                if await self.remove_status_effect(status_effect.id, guild_id_str, **kwargs):
                    removed_count += 1

        if removed_count > 0:
            print(f"{log_prefix} Successfully removed {removed_count} status(es).")
        # else:
            # print(f"{log_prefix} No statuses found matching the source item instance ID.")

        return removed_count

    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        guild_statuses_cache = self._status_effects.get(guild_id_str, {})
        if not guild_statuses_cache:
             return

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        char_mgr = kwargs.get('character_manager', self._character_manager)
        npc_mgr  = kwargs.get('npc_manager', self._npc_manager)

        to_remove_ids: List[str] = []

        for eff_id, eff in list(guild_statuses_cache.items()):
            if not isinstance(eff, StatusEffect):
                 print(f"StatusManager: Warning: Invalid object in cache for guild {guild_id_str}, ID {eff_id}. Expected StatusEffect, got {type(eff).__name__}. Marking for removal.")
                 to_remove_ids.append(eff_id)
                 continue

            try:
                if eff.duration is not None:
                    if not isinstance(eff.duration, (int, float)):
                         print(f"StatusManager: Warning: Invalid duration type for status {eff_id} ('{eff.status_type}') in guild {guild_id_str}: {eff.duration}. Expected number. Marking for removal.")
                         to_remove_ids.append(eff_id)
                         continue

                    eff.duration -= game_time_delta
                    self.mark_status_effect_dirty(guild_id_str, eff_id)

                    if eff.duration <= 0:
                        to_remove_ids.append(eff_id)
                        continue

                # Periodic effects (RuleEngine call)
                # This part needs to be adapted if rules_config is the primary source for effect details
                status_template_dict = self.get_status_template(eff.status_type) # Fetches dict form

                if status_template_dict and rule_engine and hasattr(rule_engine, 'apply_status_periodic_effects'):
                    target_entity = None
                    if eff.target_type == 'Character' and char_mgr:
                         target_entity = await char_mgr.get_character(guild_id_str, eff.target_id)
                    elif eff.target_type == 'NPC' and npc_mgr:
                         target_entity = await npc_mgr.get_npc(guild_id_str, eff.target_id)

                    if target_entity:
                        await rule_engine.apply_status_periodic_effects(
                            status_effect=eff,
                            target_entity=target_entity,
                            game_time_delta=game_time_delta,
                            rules_config=self.rules_config, # Pass rules_config
                            **kwargs
                        )
            except Exception as e:
                print(f"StatusManager: ❌ Error in tick processing for status {eff_id} ('{eff.status_type}') on {eff.target_type} {eff.target_id} for guild {guild_id_str}: {e}")
                traceback.print_exc()
                to_remove_ids.append(eff_id)

        for status_id_to_remove in set(to_remove_ids):
             await self.remove_status_effect(status_id_to_remove, guild_id_str, **kwargs)


    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        print(f"StatusManager: Saving state for guild {guild_id}...")
        if self._db_service is None:
             print(f"StatusManager: Database service is not available. Skipping save for guild {guild_id}.")
             return

        guild_id_str = str(guild_id)
        try:
            dirty_ids_set = self._dirty_status_effects.get(guild_id_str, set()).copy()
            deleted_ids_set = self._deleted_status_effects_ids.get(guild_id_str, set()).copy()

            if not dirty_ids_set and not deleted_ids_set:
                 self._dirty_status_effects.pop(guild_id_str, None)
                 self._deleted_status_effects_ids.pop(guild_id_str, None)
                 return

            if deleted_ids_set:
                ids_to_delete_db = list(deleted_ids_set)
                placeholders = ','.join(['?'] * len(ids_to_delete_db))
                sql_del = f"DELETE FROM statuses WHERE id IN ({placeholders}) AND guild_id = ?"
                params_del = tuple(ids_to_delete_db) + (guild_id_str,)
                await self._db_service.adapter.execute(sql_del, params_del)
                self._deleted_status_effects_ids.pop(guild_id_str, None) # Clear after successful DB operation

            guild_statuses_cache = self._status_effects.get(guild_id_str, {})
            statuses_to_save_db: List[StatusEffect] = []
            upserted_in_db_ids: Set[str] = set()

            for sid in list(dirty_ids_set): # Iterate copy
                 eff = guild_statuses_cache.get(sid)
                 if eff and isinstance(eff, StatusEffect) and getattr(eff, 'guild_id', None) == guild_id_str:
                      # Filter out statuses that might have been marked dirty then deleted before save
                      if sid not in deleted_ids_set: # Only save if not also marked for deletion
                          statuses_to_save_db.append(eff)
                 else: # Not in cache or wrong guild, remove from dirty
                      self._dirty_status_effects.get(guild_id_str, set()).discard(sid)

            if statuses_to_save_db:
                sql_upsert = '''
                    INSERT OR REPLACE INTO statuses
                    (id, status_type, target_id, target_type, duration_turns, applied_at, source_id, state_variables, guild_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
                data_to_upsert_db = []
                for eff_to_save in statuses_to_save_db:
                    sv_json = json.dumps(getattr(eff_to_save, 'state_variables', {}))
                    data_to_upsert_db.append((
                        eff_to_save.id, eff_to_save.status_type, eff_to_save.target_id, eff_to_save.target_type,
                        eff_to_save.duration, eff_to_save.applied_at, eff_to_save.source_id,
                        sv_json, eff_to_save.guild_id
                    ))
                    upserted_in_db_ids.add(eff_to_save.id)

                if data_to_upsert_db:
                     await self._db_service.adapter.execute_many(sql_upsert, data_to_upsert_db)
                     if guild_id_str in self._dirty_status_effects:
                        self._dirty_status_effects[guild_id_str].difference_update(upserted_in_db_ids)
                        if not self._dirty_status_effects[guild_id_str]:
                            self._dirty_status_effects.pop(guild_id_str)

            # Clean up any remaining empty sets in dirty_status_effects
            if guild_id_str in self._dirty_status_effects and not self._dirty_status_effects[guild_id_str]:
                self._dirty_status_effects.pop(guild_id_str)

            print(f"StatusManager: Successfully saved state for guild {guild_id_str}.")
        except Exception as e:
            print(f"StatusManager: ❌ Error during saving state for guild {guild_id_str}: {e}")
            traceback.print_exc()


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        print(f"StatusManager: Loading state for guild {guild_id}...")
        guild_id_str = str(guild_id)

        if self._db_service is None:
             print(f"StatusManager: Database service not available. Loading placeholder state for guild {guild_id_str}.")
             self._status_effects[guild_id_str] = {}
             self._dirty_status_effects.pop(guild_id_str, None)
             self._deleted_status_effects_ids.pop(guild_id_str, None)
             return

        try:
            self._status_effects[guild_id_str] = {}
            self._dirty_status_effects.pop(guild_id_str, None)
            self._deleted_status_effects_ids.pop(guild_id_str, None)

            sql_statuses = '''
                SELECT id, status_type, target_id, target_type, duration_turns, applied_at, source_id, state_variables, guild_id
                FROM statuses WHERE guild_id = $1
            '''
            rows_statuses = await self._db_service.adapter.fetchall(sql_statuses, (guild_id_str,))

            if rows_statuses:
                 time_mgr = kwargs.get('time_manager', self._time_manager)
                 current_game_time_for_guild = None
                 if time_mgr and hasattr(time_mgr, 'get_current_game_time'):
                      current_game_time_for_guild = time_mgr.get_current_game_time(guild_id_str)

                 loaded_count = 0
                 for row in rows_statuses:
                      try:
                           row_dict = dict(row)
                           status_id_db = row_dict.get('id')
                           if status_id_db is None: continue

                           row_dict['state_variables'] = json.loads(row_dict.get('state_variables') or '{}') if isinstance(row_dict.get('state_variables'), (str, bytes)) else {}
                           row_dict['duration'] = float(row_dict.pop('duration_turns')) if row_dict.get('duration_turns') is not None else None
                           row_dict['applied_at'] = float(row_dict['applied_at']) if row_dict['applied_at'] is not None else None

                           if str(row_dict.get('guild_id')) != guild_id_str: continue

                           status_instance = StatusEffect.from_dict(row_dict)

                           if status_instance.duration is not None and status_instance.applied_at is not None and current_game_time_for_guild is not None:
                                elapsed = current_game_time_for_guild - status_instance.applied_at
                                if elapsed > 0:
                                    status_instance.duration -= elapsed
                                    if status_instance.duration <= 0:
                                        self._deleted_status_effects_ids.setdefault(guild_id_str, set()).add(status_instance.id)
                                        continue

                           self._status_effects.setdefault(guild_id_str, {})[status_instance.id] = status_instance
                           loaded_count += 1
                      except Exception as e_row:
                           print(f"StatusManager: ❌ Error processing status row ID {row.get('id', 'Unknown')} for guild {guild_id_str}: {e_row}")
                 print(f"StatusManager: Loaded {loaded_count} statuses for guild {guild_id_str}.")
            else:
                 print(f"StatusManager: No statuses found in DB for guild {guild_id_str}.")
        except Exception as e_load:
            print(f"StatusManager: ❌ CRITICAL ERROR loading state for guild {guild_id_str}: {e_load}")
            traceback.print_exc()


    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
         print(f"StatusManager: Rebuilding runtime caches for guild {guild_id} (No specific action needed for StatusManager unless more complex caches are added).")


    async def clean_up_for_character(self, character_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
         guild_id = context.get('guild_id')
         if guild_id is None: return
         guild_id_str = str(guild_id)
         statuses_on_target_ids = [ sid for sid, s in self._status_effects.get(guild_id_str, {}).items()
                                   if isinstance(s, StatusEffect) and s.target_id == character_id and s.target_type == 'Character']
         for status_id_to_remove in statuses_on_target_ids:
              await self.remove_status_effect(status_id_to_remove, guild_id_str, **context)

    async def save_status_effect(self, status_effect: "StatusEffect", guild_id: str) -> bool:
        if self._db_service is None: return False
        guild_id_str = str(guild_id)
        effect_id = getattr(status_effect, 'id', None)
        if not effect_id: return False
        try:
            effect_data = status_effect.to_dict()
            db_params = (
                effect_data.get('id'), effect_data.get('status_type'), effect_data.get('target_id'), effect_data.get('target_type'),
                effect_data.get('duration'), effect_data.get('applied_at'), effect_data.get('source_id'),
                json.dumps(effect_data.get('state_variables', {})), guild_id_str # Use guild_id_str here
            )
            upsert_sql = '''
            INSERT OR REPLACE INTO statuses (
                id, status_type, target_id, target_type, duration_turns,
                applied_at, source_id, state_variables, guild_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            await self._db_service.adapter.execute(upsert_sql, db_params)
            if guild_id_str in self._dirty_status_effects and effect_id in self._dirty_status_effects[guild_id_str]:
                self._dirty_status_effects[guild_id_str].discard(effect_id)
                if not self._dirty_status_effects[guild_id_str]: del self._dirty_status_effects[guild_id_str]
            self._status_effects.setdefault(guild_id_str, {})[effect_id] = status_effect
            return True
        except Exception as e:
            print(f"StatusManager: Error saving status effect {effect_id} for guild {guild_id_str}: {e}")
            return False

    async def remove_status_effects_by_type(self, target_id: str, target_type: str, status_type_to_remove: str, guild_id: str, context: Dict[str, Any]) -> int:
        guild_id_str = str(guild_id)
        removed_count = 0
        if guild_id_str not in self._status_effects: return 0
        statuses_to_check = list(self._status_effects.get(guild_id_str, {}).values())
        for status_effect_instance in statuses_to_check:
            if isinstance(status_effect_instance, StatusEffect) and \
               status_effect_instance.target_id == target_id and \
               status_effect_instance.target_type == target_type and \
               status_effect_instance.status_type == status_type_to_remove:
                if await self.remove_status_effect(status_effect_instance.id, guild_id_str, **context):
                    removed_count += 1
        return removed_count

    def mark_status_effect_dirty(self, guild_id: str, status_effect_id: str) -> None:
        """Helper to mark a status effect as dirty for the given guild."""
        guild_id_str = str(guild_id)
        status_effect_id_str = str(status_effect_id)
        # Ensure the status effect actually exists in the cache for this guild before marking dirty
        if guild_id_str in self._status_effects and status_effect_id_str in self._status_effects[guild_id_str]:
            self._dirty_status_effects.setdefault(guild_id_str, set()).add(status_effect_id_str)
        # else:
            # print(f"StatusManager.mark_status_effect_dirty: Attempted to mark non-cached status {status_effect_id_str} for guild {guild_id_str}.")


# Конец класса StatusManager
