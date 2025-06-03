# bot/game/managers/location_manager.py

from __future__ import annotations
import json
import traceback
import asyncio
# --- Необходимые импорты для runtime ---
import uuid # uuid нужен для генерации ID инстансов

# --- Базовые типы и TYPE_CHECKING ---
# Set и другие типы нужны для аннотаций
# ИСПРАВЛЕНИЕ: Добавляем необходимые типы из typing
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins

# --- Imports needed ONLY for Type Checking ---
# Эти импорты игнорируются Python при runtime, помогая разорвать циклы импорта.
# Используйте строковые литералы ("ClassName") для type hints в __init__ и методах
# для классов, импортированных здесь.
if TYPE_CHECKING:
    # Import Managers and Processors received via dependency injection (__init__)
    # or passed into methods that might cause import cycles.
    # LocationManager активно использует эти зависимости, поэтому их импорт сюда (а не прямой)
    # и использование строковых литералов для их аннотаций в __init__ и сигнатурах методов -
    # стандартный подход при наличии циклов или условных импортов в других местах.
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    # Добавляем процессоры, которые вызываются напрямую (handle_entity_arrival/departure)
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
    from bot.game.character_processors.character_view_service import CharacterViewService # Maybe needed in context?
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator # Corrected import name

    # Add other managers/processors/services if they are dependencies passed via kwargs and might cause cycles


# --- Imports needed at Runtime ---
# Только импортируйте модули/классы здесь, если они строго необходимы для выполнения кода
# (например, создание экземпляров, вызов статических методов, isinstance проверки).
# Если класс используется только для аннотаций типов, импортируйте его в блок TYPE_CHECKING выше.

# Прямых импортов менеджеров/процессоров здесь больше нет, так как они получены через dependency injection.


# Define Callback Types (Callable types не требуют строковых литералов, если базовые типы определены)
# Updated annotation to be more general if callback signature varies
SendToChannelCallback = Callable[..., Awaitable[Any]] # Use ... if args/kwargs are flexible
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class LocationManager:
    """
    Менеджер для управления локациями игрового мира.
    Хранит статические шаблоны локаций и динамические инстансы (per-guild),
    обрабатывает триггеры OnEnter/OnExit.
    """
    # Добавляем required_args для совместимости с PersistenceManager
    # Если локации динамические и зависят от guild_id, добавляем ["guild_id"].
    # Судя по возвращенной логике save/load_state, они работают per-guild.
    required_args_for_load = ["guild_id"] # PersistenceManager передает guild_id в load_state
    required_args_for_save = ["guild_id"] # PersistenceManager передает guild_id в save_state
    # ИСПРАВЛЕНИЕ: Добавляем guild_id для rebuild_runtime_caches
    required_args_for_rebuild = ["guild_id"] # PersistenceManager передает guild_id в rebuild_runtime_caches


    # --- Class-Level Attribute Annotations ---
    # Статические шаблоны локаций (теперь per-guild)
    _location_templates: Dict[str, Dict[str, Dict[str, Any]]] # {guild_id: {tpl_id: data}}
    # Динамические инстансы (per-guild)
    _location_instances: Dict[str, Dict[str, Dict[str, Any]]] # {guild_id: {instance_id: data}}
    # Наборы "грязных" и удаленных инстансов (per-guild)
    _dirty_instances: Dict[str, Set[str]] # {guild_id: {instance_id, ...}}
    _deleted_instances: Dict[str, Set[str]] # {guild_id: {instance_id, ...}}


    def __init__(
        self,
        # Используем строковые литералы для всех опциональных зависимостей
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None,
        event_manager: Optional["EventManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        time_manager: Optional["TimeManager"] = None,
        send_callback_factory: Optional[SendCallbackFactory] = None,
        event_stage_processor: Optional["EventStageProcessor"] = None,
        event_action_processor: Optional["EventActionProcessor"] = None,
        # Добавляем OnEnter/OnExit action executors и generator, если инжектируются напрямую
        on_enter_action_executor: Optional["OnEnterActionExecutor"] = None,
        # ИСПРАВЛЕНИЕ: Используем правильное имя класса StageDescriptionGenerator
        stage_description_generator: Optional["StageDescriptionGenerator"] = None,

        # Add other dependencies here with Optional and string literals
    ):
        print("Initializing LocationManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._rule_engine = rule_engine
        self._event_manager = event_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._time_manager = time_manager
        self._send_callback_factory = send_callback_factory
        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor
        # Сохраняем инжектированные экзекуторы/генератор
        self._on_enter_action_executor = on_enter_action_executor
        # ИСПРАВЛЕНИЕ: Используем правильное имя атрибута для StageDescriptionGenerator
        self._stage_description_generator = stage_description_generator


        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые outer словари
        self._location_templates = {} # {guild_id: {tpl_id: data}}
        self._location_instances = {} # {guild_id: {instance_id: data}}
        self._dirty_instances = {} # {guild_id: {instance_id, ...}}
        self._deleted_instances = {} # {guild_id: {instance_id, ...}}

        print("LocationManager initialized.")

    # --- Методы для PersistenceManager ---
    # Переименовываем load_location_templates в load_state, чтобы соответствовать интерфейсу
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает статические шаблоны локаций и динамические инстансы для гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Loading state for guild {guild_id_str} (static templates + instances)...")

        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"]
        if db_adapter is None:
             print(f"LocationManager: Database adapter is not available. Cannot load state for guild {guild_id_str}.")
             # PersistenceManager handles re-raising, just log and return/propagate
             # raise ConnectionError("Database adapter is required for loading state.") # Or raise
             return # Let PM handle if it's critical

        # Очищаем все кеши для этой гильдии перед загрузкой
        self._clear_guild_state_cache(guild_id_str)

        # --- Загрузка статических шаблонов (per-guild) ---
        guild_templates_cache: Dict[str, Dict[str, Any]] = self._location_templates.setdefault(guild_id_str, {})

        loaded_templates_count = 0
        try:
            # Corrected SQL query based on previous logs - location_templates should have guild_id
            sql_templates = "SELECT id, template_data FROM location_templates WHERE guild_id = ?"
            rows_templates = await db_adapter.fetchall(sql_templates, (guild_id_str,))
            print(f"LocationManager: Found {len(rows_templates)} template rows for guild {guild_id_str}.")
            for row in rows_templates:
                 tpl_id = row.get('id')
                 tpl_data_json = row.get('template_data')
                 if tpl_id is None:
                      print(f"LocationManager: Warning: Skipping template row with missing ID for guild {guild_id_str}. Row: {row}.")
                      continue
                 try:
                      # Handle potential None data gracefully
                      data = json.loads(tpl_data_json or '{}') if isinstance(tpl_data_json, (str, bytes)) else {}
                      if not isinstance(data, dict):
                           print(f"LocationManager: Warning: Template data for template '{tpl_id}' is not a dictionary ({type(data)}) for guild {guild_id_str}. Skipping.")
                           continue
                      data.setdefault('id', str(tpl_id)) # Ensure ID is in data and is string
                      # Ensure exits/connected_locations are parsed correctly if they exist
                      exits = data.get('exits') or data.get('connected_locations')
                      if isinstance(exits, str):
                           try: exits = json.loads(exits)
                           except (json.JSONDecodeError, TypeError): exits = {}
                      if not isinstance(exits, dict): exits = {} # Ensure it's a dict
                      data['exits'] = exits # Standardize name
                      data.pop('connected_locations', None) # Remove old key if present

                      guild_templates_cache[str(tpl_id)] = data
                      loaded_templates_count += 1
                 except json.JSONDecodeError:
                     print(f"LocationManager: Error decoding template '{tpl_id}' for guild {guild_id_str}: {traceback.format_exc()}. Skipping template row.");
                 except Exception as e:
                      print(f"LocationManager: Error processing template row '{tpl_id}' for guild {guild_id_str}: {e}. Skipping."); traceback.print_exc();


            print(f"LocationManager: Loaded {loaded_templates_count} templates for guild {guild_id_str} from DB.")

        except Exception as e:
            print(f"LocationManager: ❌ Error during DB template load for guild {guild_id_str}: {e}"); traceback.print_exc();
            self._location_templates.pop(guild_id_str, None) # Clear cache only for this guild on error
            raise # Re-raise as this is likely critical for the guild


        # --- Загрузка динамических инстансов (per-guild) ---
        guild_instances_cache = self._location_instances.setdefault(guild_id_str, {})
        # dirty_instances set and deleted_instances set for this guild were cleared by _clear_guild_state_cache

        loaded_instances_count = 0

        try:
            # Corrected SQL query based on schema
            sql_instances = '''
            SELECT id, template_id, state_variables, is_active, guild_id FROM locations WHERE guild_id = ?
            '''
            rows_instances = await db_adapter.fetchall(sql_instances, (guild_id_str,))
            if rows_instances:
                 print(f"LocationManager: Found {len(rows_instances)} instances for guild {guild_id_str}.")

                 for row in rows_instances:
                      try:
                           instance_id_raw = row.get('id')
                           loaded_guild_id_raw = row.get('guild_id') # Should match guild_id_str due to WHERE clause

                           if instance_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                                # This check is mostly redundant due to WHERE clause but safe.
                                print(f"LocationManager: Warning: Skipping instance row with invalid ID ('{instance_id_raw}') or mismatched guild_id ('{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row}.")
                                continue

                           instance_id = str(instance_id_raw)
                           state_json_raw = row.get('state_variables') # Correct column name based on schema
                           instance_state_data = json.loads(state_json_raw or '{}') if isinstance(state_json_raw, (str, bytes)) else {}
                           if not isinstance(instance_state_data, dict):
                               instance_state_data = {}
                               print(f"LocationManager: Warning: State data for instance ID {instance_id} not a dict ({type(instance_state_data)}) for guild {guild_id_str}. Resetting.")

                           instance_data: Dict[str, Any] = {
                               'id': instance_id,
                               'guild_id': guild_id_str, # Store as string
                               'template_id': str(row.get('template_id')) if row.get('template_id') is not None else None, # Ensure string or None
                               'state': instance_state_data,
                               'is_active': bool(row.get('is_active', 0)) # Ensure boolean from integer (0 or 1)
                           }

                           if not instance_data.get('template_id'):
                               print(f"LocationManager: Warning: Instance ID {instance_id} missing template_id for guild {guild_id_str}. Skipping load.")
                               continue

                           guild_instances_cache[instance_data['id']] = instance_data
                           loaded_instances_count += 1

                      except json.JSONDecodeError:
                          print(f"LocationManager: Error decoding JSON for instance row (ID: {row.get('id', 'N/A')}, guild: {row.get('guild_id', 'N/A')}): {traceback.format_exc()}. Skipping instance row.");
                      except Exception as e:
                          print(f"LocationManager: Error processing instance row (ID: {row.get('id', 'N/A')}, guild: {row.get('guild_id', 'N/A')}): {e}. Skipping instance row."); traceback.print_exc();


                 print(f"LocationManager: Loaded {loaded_instances_count} instances for guild {guild_id_str}.")
            else: print(f"LocationManager: No instances found for guild {guild_id_str}.")

        except Exception as e:
            print(f"LocationManager: ❌ Error during DB instance load for guild {guild_id_str}: {e}"); traceback.print_exc();
            # Clear caches for this guild on error
            self._location_instances.pop(guild_id_str, None)
            self._dirty_instances.pop(guild_id_str, None)
            self._deleted_instances.pop(guild_id_str, None)
            raise # Re-raise as this is likely critical for the guild


        print(f"LocationManager: Load state complete for guild {guild_id_str}.")

    # Переименовываем в save_state, чтобы соответствовать интерфейсу
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет измененные/удаленные динамические инстансы локаций для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Saving state for guild {guild_id_str}...")

        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"]
        if db_adapter is None:
             print(f"LocationManager: Database adapter not available. Skipping save for guild {guild_id_str}.")
             return

        # Получаем per-guild кеши, используем get() с default {} or set() для безопасности
        guild_instances_cache = self._location_instances.get(guild_id_str, {})
        dirty_instances_set = self._dirty_instances.get(guild_id_str, set()).copy() # Use a copy for safety
        deleted_instances_set = self._deleted_instances.get(guild_id_str, set()).copy() # Use a copy for safety


        if not dirty_instances_set and not deleted_instances_set:
            # print(f"LocationManager: No dirty or deleted instances to save for guild {guild_id_str}.") # Too noisy
            # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, очищаем per-guild dirty/deleted сеты
            self._dirty_instances.pop(guild_id_str, None)
            self._deleted_instances.pop(guild_id_str, None)
            return

        print(f"LocationManager: Saving {len(dirty_instances_set)} dirty, {len(deleted_instances_set)} deleted instances for guild {guild_id_str}...")


        try:
            # Удалить помеченные для удаления инстансы для этого guild_id
            if deleted_instances_set:
                 ids_to_delete = list(deleted_instances_set)
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 # Ensure deleting only for this guild and these IDs
                 sql_delete_batch = f"DELETE FROM locations WHERE guild_id = ? AND id IN ({placeholders_del})"
                 await db_adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete)));
                 print(f"LocationManager: Deleted {len(ids_to_delete)} instances from DB for guild {guild_id_str}.")
                 # ИСПРАВЛЕНИЕ: Очищаем per-guild deleted set after successful deletion
                 self._deleted_instances.pop(guild_id_str, None)


            # Обновить или вставить измененные инстансы для этого guild_id
            # Фильтруем dirty_instances на те, что все еще существуют в кеше (не были удалены)
            instances_to_upsert_list = [ inst for id in list(dirty_instances_set) if (inst := guild_instances_cache.get(id)) is not None ] # Iterate over a copy of IDs

            if instances_to_upsert_list:
                 print(f"LocationManager: Upserting {len(instances_to_upsert_list)} instances for guild {guild_id_str}...")
                 # Corrected column names based on schema
                 upsert_sql = ''' INSERT OR REPLACE INTO locations (id, guild_id, template_id, state_variables, is_active) VALUES (?, ?, ?, ?, ?) '''
                 data_to_upsert = []
                 upserted_instance_ids: Set[str] = set() # Track IDs successfully prepared

                 for instance_data in instances_to_upsert_list:
                      try:
                          instance_id = instance_data.get('id')
                          instance_guild_id = instance_data.get('guild_id')

                          # Double check required fields and guild ID match
                          if instance_id is None or str(instance_guild_id) != guild_id_str:
                              print(f"LocationManager: Warning: Skipping upsert for instance with invalid ID ('{instance_id}') or mismatched guild ('{instance_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                              continue

                          template_id = instance_data.get('template_id')
                          state_variables = instance_data.get('state', {}) # Use 'state' attribute from cache data
                          is_active = instance_data.get('is_active', True)

                          # Ensure state_variables is a dict for JSON dump
                          if not isinstance(state_variables, dict):
                              print(f"LocationManager: Warning: Instance {instance_id} state_variables is not a dict ({type(state_variables)}) for guild {guild_id_str}. Saving as empty dict.")
                              state_variables = {}

                          data_to_upsert.append((
                              str(instance_id),
                              guild_id_str, # Ensure correct guild_id string
                              str(template_id) if template_id is not None else None, # Ensure template_id is string or None
                              json.dumps(state_variables), # Save state as JSON
                              int(bool(is_active)), # Ensure int (0 or 1)
                          ));
                          upserted_instance_ids.add(str(instance_id)) # Track ID

                      except Exception as e:
                          print(f"LocationManager: Error preparing data for instance {instance_data.get('id', 'N/A')} (guild {instance_data.get('guild_id', 'N/A')}) for upsert: {e}"); traceback.print_exc();
                          # This instance won't be saved in this batch but remains in _dirty_instances

                 if data_to_upsert:
                     try:
                         await db_adapter.execute_many(upsert_sql, data_to_upsert);
                         print(f"LocationManager: Successfully upserted {len(data_to_upsert)} instances for guild {guild_id_str}.")
                         # Only clear dirty flags for instances that were successfully processed
                         # If execute_many succeeds, clear all in the initial dirty set for this guild
                         if guild_id_str in self._dirty_instances:
                              self._dirty_instances[guild_id_str].difference_update(upserted_instance_ids)
                              # If set is empty after update, remove the guild key
                              if not self._dirty_instances[guild_id_str]:
                                   del self._dirty_instances[guild_id_str]

                     except Exception as e:
                          print(f"LocationManager: Error during batch upsert for guild {guild_id_str}: {e}"); traceback.print_exc();
                          # Don't clear dirty_instances if batch upsert failed

            # else: print(f"LocationManager: No dirty instances to save for guild {guild_id_str}.") # Too noisy


        except Exception as e:
             print(f"LocationManager: ❌ Error during saving state for guild {guild_id_str}: {e}"); traceback.print_exc();
             # For save, it's generally better NOT to clear dirty/deleted on error
             # to allow retry on the next save interval.
             # raise # Re-raise if this is a critical failure


        print(f"LocationManager: Save state complete for guild {guild_id_str}.")


    # Add rebuild_runtime_caches with correct signature
    # İSPRAVLENIE: Добавляем guild_id и kwargs
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Rebuilding runtime caches for guild {guild_id_str}. (Placeholder)")
        # This method is called by PersistenceManager *after* load_state for this guild.
        # Any runtime caches that depend on the loaded location data (templates/instances)
        # or need to interact with other managers loaded for this guild should be built here.

        # Example: If you had a cache of {channel_id: location_instance_id}
        # channel_to_location_cache = self._channel_to_location_cache.setdefault(guild_id_str, {})
        # channel_to_location_cache.clear()
        # for instance in self._location_instances.get(guild_id_str, {}).values():
        #     # Get the template for this instance
        #     template = self.get_location_static(guild_id_str, instance.get('template_id'))
        #     if template and template.get('channel_id') is not None:
        #         try:
        #             channel_id = int(template['channel_id'])
        #             channel_to_location_cache[channel_id] = instance['id']
        #         except (ValueError, TypeError):
        #              print(f"LocationManager: Warning: Invalid channel_id '{template.get('channel_id')}' in template '{template.get('id')}' for instance '{instance.get('id')}' in guild {guild_id_str}.")

        # Managers like CharacterManager or NpcManager might rebuild *their* per-location caches.
        # They would get the LocationManager instance and loaded locations from kwargs.
        # char_mgr = kwargs.get('character_manager') # type: Optional["CharacterManager"]
        # if char_mgr and hasattr(char_mgr, 'rebuild_location_caches'):
        #     await char_mgr.rebuild_location_caches(guild_id_str, self._location_instances.get(guild_id_str, {}), **kwargs)


        print(f"LocationManager: Rebuild runtime caches complete for guild {guild_id_str}.")


    # --- Dynamic Instance Management ---
    # Methods updated to accept guild_id and work with per-guild caches

    async def create_location_instance(self, guild_id: str, template_id: str, initial_state: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
         """Создает динамический инстанс локации из шаблона для определенной гильдии."""
         guild_id_str = str(guild_id)
         print(f"LocationManager: Creating instance for guild {guild_id_str} from template {template_id} in memory...")

         # Получаем шаблон для этой гильдии
         guild_templates = self._location_templates.get(guild_id_str, {})
         template = guild_templates.get(str(template_id)) # Ensure template_id is string

         if not template:
             print(f"LocationManager: Error creating instance: Template '{template_id}' not found for guild {guild_id_str}.")
             return None
         if not template.get('name'):
             print(f"LocationManager: Error creating instance: Template '{template_id}' missing 'name' for guild {guild_id_str}.")
             return None

         new_instance_id = str(uuid.uuid4()) # Generate unique ID for the instance

         template_initial_state = template.get('initial_state', {})
         if not isinstance(template_initial_state, dict):
             template_initial_state = {}
             print(f"LocationManager: Warning: Template '{template_id}' initial_state is not a dict. Using empty dict.")

         instance_state_data = dict(template_initial_state) # Start with template initial state
         if initial_state is not None:
             if isinstance(initial_state, dict):
                 instance_state_data.update(initial_state) # Override with provided state
             else:
                 print(f"LocationManager: Warning: Provided initial_state is not a dict. Ignoring.")

         instance_for_cache: Dict[str, Any] = {
             'id': new_instance_id,
             'guild_id': guild_id_str, # Store guild_id in instance data
             'template_id': str(template_id), # Store template ID as string
             'state': instance_state_data, # Dynamic state
             'is_active': True, # Instances are usually active by default
         }

         # Добавляем инстанс в кеш для данной гильдии
         self._location_instances.setdefault(guild_id_str, {})[new_instance_id] = instance_for_cache

         # Помечаем инстанс грязным для данной гильдии
         # Use the correct per-guild dirty set
         self._dirty_instances.setdefault(guild_id_str, set()).add(new_instance_id)


         print(f"LocationManager: Instance {new_instance_id} created and added to cache and marked dirty for guild {guild_id_str}.")
         # Optionally save immediately if critical, but usually wait for periodic save
         # if self._db_adapter:
         #      await self.save_state(guild_id_str, **kwargs)

         return instance_for_cache

    def get_location_instance(self, guild_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
         """Получить динамический инстанс локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         # Получаем инстанс из per-guild кеша
         guild_instances = self._location_instances.get(guild_id_str, {})
         return guild_instances.get(str(instance_id)) # Ensure instance_id is string


    async def delete_location_instance(self, guild_id: str, instance_id: str, **kwargs: Any) -> bool:
        """Пометить динамический инстанс локации для удаления для данной гильдии."""
        guild_id_str = str(guild_id)
        instance_id_str = str(instance_id)
        print(f"LocationManager: Marking instance {instance_id_str} for deletion for guild {guild_id_str}...")

        # Check if instance exists in the per-guild cache
        guild_instances_cache = self._location_instances.get(guild_id_str, {})
        instance_to_delete = guild_instances_cache.get(instance_id_str)

        if instance_to_delete:
             # TODO: Perform cleanup for entities/items/events in this instance
             # Call clean_up_location_contents method if implemented (see below)
             cleanup_context = {**kwargs, 'guild_id': guild_id_str, 'location_instance_id': instance_id_str}
             await self.clean_up_location_contents(instance_id_str, **cleanup_context)


             # Remove from per-guild instance cache
             del guild_instances_cache[instance_id_str]
             print(f"LocationManager: Removed instance {instance_id_str} from cache for guild {guild_id_str}.")

             # Add to per-guild deleted set
             self._deleted_instances.setdefault(guild_id_str, set()).add(instance_id_str) # uses set()

             # Remove from per-guild dirty set if it was there
             self._dirty_instances.get(guild_id_str, set()).discard(instance_id_str) # uses set()


             print(f"LocationManager: Instance {instance_id_str} marked for deletion for guild {guild_id_str}.")
             # Optional: Save state immediately to ensure deletion is persistent? Usually not needed.
             # if self._db_adapter: await self.save_state(guild_id_str, **kwargs)

             return True
        print(f"LocationManager: Warning: Attempted to delete non-existent instance {instance_id_str} for guild {guild_id_str}.")
        return False


    # TODO: Add a method to clean up contents (entities, items) in a location instance
    async def clean_up_location_contents(self, location_instance_id: str, **kwargs: Any) -> None:
         """Очищает сущности и предметы, находящиеся в указанном инстансе локации, при удалении локации."""
         guild_id = kwargs.get('guild_id') # Get guild_id from context
         if not guild_id: print("LocationManager: Warning: guild_id missing in context for clean_up_location_contents."); return
         guild_id_str = str(guild_id)
         print(f"LocationManager: Cleaning up contents of location instance {location_instance_id} in guild {guild_id_str}...")

         # Get relevant managers from kwargs or self
         char_manager = kwargs.get('character_manager', self._character_manager) # type: Optional["CharacterManager"]
         npc_manager = kwargs.get('npc_manager', self._npc_manager) # type: Optional["NpcManager"]
         item_manager = kwargs.get('item_manager', self._item_manager) # type: Optional["ItemManager"]

         cleanup_context = {**kwargs, 'location_instance_id': location_instance_id} # Pass relevant context


         # Remove all Characters in this location instance
         if char_manager and hasattr(char_manager, 'get_characters_in_location') and hasattr(char_manager, 'remove_character'):
              # get_characters_in_location needs guild_id and location_id (instance ID)
              characters_to_remove = char_manager.get_characters_in_location(guild_id_str, location_instance_id)
              print(f"LocationManager: Found {len(characters_to_remove)} characters in location {location_instance_id}.")
              for char in list(characters_to_remove): # Iterate over a copy as we remove
                   char_id = getattr(char, 'id', None)
                   if char_id:
                        try:
                             # Remove character (cleanup will handle items, status, party, combat etc.)
                             # remove_character needs character_id, guild_id, and context
                             await char_manager.remove_character(char_id, guild_id_str, **cleanup_context) # Pass guild_id and context
                             print(f"LocationManager: Removed character {char_id} from location {location_instance_id}.")
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error removing character {char_id} from location {location_instance_id}.");


         # Remove all NPCs in this location instance
         if npc_manager and hasattr(npc_manager, 'get_npcs_in_location') and hasattr(npc_manager, 'remove_npc'):
              # get_npcs_in_location needs guild_id and location_id (instance ID)
              npcs_to_remove = npc_manager.get_npcs_in_location(guild_id_str, location_instance_id)
              print(f"LocationManager: Found {len(npcs_to_remove)} NPCs in location {location_instance_id}.")
              for npc in list(npcs_to_remove): # Iterate over a copy
                   npc_id = getattr(npc, 'id', None)
                   if npc_id:
                        try:
                             # Remove NPC (cleanup will handle items, status, party, combat etc.)
                             # remove_npc needs guild_id, npc_id, and context
                             await npc_manager.remove_npc(guild_id_str, npc_id, **cleanup_context) # Pass guild_id and context
                             print(f"LocationManager: Removed NPC {npc_id} from location {location_instance_id}.")
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error removing NPC {npc_id} from location {location_instance_id}.");


         # Remove all Items located in this location instance
         if item_manager and hasattr(item_manager, 'remove_items_by_location'): # Assuming such a method exists
              # remove_items_by_location needs location_id (instance ID), guild_id, and context
              try:
                   await item_manager.remove_items_by_location(location_instance_id, guild_id_str, **cleanup_context) # Pass guild_id and context
                   print(f"LocationManager: Removed items from location {location_instance_id}.")
              except Exception: traceback.print_exc(); print(f"LocationManager: Error removing items from location {location_instance_id}.");

         # TODO: Clean up events tied to this location?

         print(f"LocationManager: Cleanup of contents complete for location instance {location_instance_id} in guild {guild_id_str}.")


    def get_location_name(self, guild_id: str, instance_id: str) -> Optional[str]:
         """Получить название инстанса локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         instance = self.get_location_instance(guild_id_str, instance_id)
         if instance:
             template_id = instance.get('template_id')
             # Получаем шаблон для этой гильдии по template_id инстанса
             template = self.get_location_static(guild_id_str, template_id) # Use get_location_static with guild_id
             if template and template.get('name'):
                  return template.get('name')

         # Fallback names
         if isinstance(instance_id, str):
             return f"Unknown Location ({instance_id})" # Fallback using requested ID
         return None

    # get_connected_locations now works with instance and its template for the given guild
    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]:
         """Получить связанные локации (выходы) для инстанса локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         instance = self.get_location_instance(guild_id_str, instance_id)
         if instance:
              template_id = instance.get('template_id')
              # Получаем шаблон для этой гильдии по template_id инстанса
              template = self.get_location_static(guild_id_str, template_id) # Use get_location_static with guild_id
              if template:
                  # Check both 'exits' and 'connected_locations' for backward compatibility
                  connections = template.get('exits')
                  if connections is None: # Fallback to 'connected_locations' if 'exits' is not found or is None
                       connections = template.get('connected_locations')

                  # Ensure connections is a dictionary. If it was a list, convert {id:id}.
                  if isinstance(connections, dict):
                       # Ensure keys and values are strings for consistency
                       return {str(k): str(v) for k, v in connections.items()}
                  if isinstance(connections, list):
                       # Convert list of IDs to dictionary {id: id}
                       return {str(loc_id): str(loc_id) for loc_id in connections if loc_id is not None}
         return {} # Return empty dict if instance, template, or connections not found/valid


    async def update_location_state(self, guild_id: str, instance_id: str, state_updates: Dict[str, Any], **kwargs: Any) -> bool:
        """Обновляет динамическое состояние инстанса локации для данной гильдии."""
        guild_id_str = str(guild_id)
        instance_data = self.get_location_instance(guild_id_str, instance_id)
        if instance_data:
            current_state = instance_data.setdefault('state', {})
            if not isinstance(current_state, dict):
                print(f"LocationManager: Warning: Instance {instance_data.get('id', 'N/A')} state is not a dict ({type(current_state)}) for guild {guild_id_str}. Resetting to {{}}.")
                current_state = {} # Reset if not a dict
                instance_data['state'] = current_state # Update in instance_data

            # Update the state dictionary
            current_state.update(state_updates)

            # Mark the instance as dirty for this guild
            # Use the correct per-guild dirty set
            self._dirty_instances.setdefault(guild_id_str, set()).add(instance_data['id'])


            print(f"LocationManager: Updated state for instance {instance_data['id']} for guild {guild_id_str}. Marked dirty.")
            return True
        print(f"LocationManager: Warning: Attempted to update state for non-existent instance {instance_id} for guild {guild_id_str}.")
        return False


    def get_location_channel(self, guild_id: str, instance_id: str) -> Optional[int]:
        """Получить ID канала для инстанса локации для данной гильдии."""
        guild_id_str = str(guild_id)
        instance = self.get_location_instance(guild_id_str, instance_id)
        if instance:
            template_id = instance.get('template_id')
            # Получаем шаблон для этой гильдии по template_id инстанса
            template = self.get_location_static(guild_id_str, template_id) # Use get_location_static with guild_id
            if template and template.get('channel_id') is not None:
                 channel_id_raw = template['channel_id']
                 try:
                      # Ensure it's an integer
                      return int(channel_id_raw)
                 except (ValueError, TypeError):
                      print(f"LocationManager: Warning: Invalid channel_id '{channel_id_raw}' in template {template.get('id', 'N/A')} for instance {instance_id} in guild {guild_id_str}. Expected integer.");
                      return None
        return None

    # get_default_location_id now explicitly takes guild_id
    def get_default_location_id(self, guild_id: str) -> Optional[str]:
        """Получить ID дефолтной начальной локации для данной гильдии."""
        guild_id_str = str(guild_id)
        # Example: default in settings
        # Try to get guild-specific settings first, fallback to global settings
        guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {}) # Try guild-specific
        default_id = guild_settings.get('default_start_location_id') # Check guild-specific setting
        if default_id is None: # If not found in guild-specific, check global
             default_id = self._settings.get('default_start_location_id')

        if isinstance(default_id, (str, int)): # Accept string or integer from settings
             default_id_str = str(default_id)
             # Optional: check if an instance or template with this ID exists for this guild
             # This requires loading templates/instances first, which happens before this method is likely called.
             # get_location_instance requires guild_id
             # get_location_static requires guild_id
             if self.get_location_instance(guild_id_str, default_id_str) or self.get_location_static(guild_id_str, default_id_str):
                 return default_id_str
             else:
                 print(f"LocationManager: Warning: Default start location ID '{default_id_str}' found in settings for guild {guild_id_str}, but no corresponding instance or template exists.")
                 return None # Found setting, but location doesn't exist

        # Example: default in templates (could be a special template 'start')
        # This approach is less common as it requires the template to be loaded before getting the default ID.
        # guild_templates = self._location_templates.get(guild_id_str, {})
        # start_template = guild_templates.get('start') # Look for a template with id='start'
        # if start_template and start_template.get('id'): return str(start_template['id'])

        print(f"LocationManager: Warning: Default start location setting ('default_start_location_id') not found or is invalid for guild {guild_id_str}.")
        return None # No default found or invalid setting


    # --- Methods for moving entities (use dynamic instances) ---
    # Methods updated to accept guild_id and use context correctly

    async def move_entity(
        self,
        guild_id: str, # Added guild_id
        entity_id: str,
        entity_type: str,
        from_location_id: Optional[str], # Instance ID
        to_location_id: str, # Instance ID
        **kwargs: Any, # Context
    ) -> bool:
        """Универсальный метод для перемещения сущности (Character/NPC/Item/Party) между инстансами локаций для данной гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Attempting to move {entity_type} {entity_id} for guild {guild_id_str} from {from_location_id} to {to_location_id}.")

        # Check if source and target locations exist for this guild (optional for source if entity is already in cache)
        # Source location instance might not be in cache if this is cleanup for a deleted location instance.
        # If from_location_id is None, it's likely initial placement or appearing from nowhere.
        if from_location_id is not None:
             source_instance = self.get_location_instance(guild_id_str, from_location_id)
             if not source_instance:
                  print(f"LocationManager: Warning: Source location instance '{from_location_id}' not found for guild {guild_id_str} during move of {entity_type} {entity_id}. Proceeding anyway.")
                  # Decide if this should be an error. If the entity's current location points to a non-existent instance, that's a data inconsistency.
                  # For now, allow moving out of a 'bad' location, but log.

        # Check presence of the target location instance for this guild
        target_instance = self.get_location_instance(guild_id_str, to_location_id)
        if not target_instance:
             print(f"LocationManager: Error: Target location instance '{to_location_id}' not found for guild {guild_id_str}. Cannot move {entity_type} {entity_id}.")
             # Send feedback if send_callback_factory is available in kwargs or injected
             send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
             channel_id = kwargs.get('channel_id') # Try to get channel from context
             if channel_id is None and from_location_id is not None: # Try to get channel from source location
                 channel_id = self.get_location_channel(guild_id_str, from_location_id)
             if channel_id is None and to_location_id is not None: # Try to get channel from target location
                 channel_id = self.get_location_channel(guild_id_str, to_location_id)

             if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Ошибка перемещения: Целевая локация `{to_location_id}` не найдена.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback for move failure: {cb_e}")
             return False

        # Get the relevant entity manager from kwargs or __init__
        mgr: Optional[Any] = None # Use Any type as it can be different managers
        update_location_method_name: Optional[str] = None
        manager_attr_name: Optional[str] = None # For logging

        if entity_type == 'Character':
            mgr = kwargs.get('character_manager', self._character_manager)
            update_location_method_name = 'update_character_location'
            manager_attr_name = '_character_manager'
        elif entity_type == 'NPC':
            mgr = kwargs.get('npc_manager', self._npc_manager)
            update_location_method_name = 'update_npc_location' # Assuming NPCManager has this method
            manager_attr_name = '_npc_manager'
        # TODO: Add other entity types like 'Party', 'Item' if their location is managed here
        # elif entity_type == 'Party': ... PartyManager.update_party_location?
        # elif entity_type == 'Item': ... ItemManager.update_item_location?
        else:
            print(f"LocationManager: Error: Movement not supported for entity type {entity_type}.")
            # Send feedback if possible
            send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
            channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id) # Get channel from context or either location
            if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Ошибка перемещения: Перемещение сущностей типа `{entity_type}` не поддерживается.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")
            return False

        # Check if the manager and update method are available
        if not mgr or not hasattr(mgr, update_location_method_name):
            print(f"LocationManager: Error: No suitable manager ({manager_attr_name} or via kwargs) or update method ('{update_location_method_name}') found for entity type {entity_type}.")
            # Send feedback if possible
            send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
            channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
            if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Ошибка перемещения: Внутренняя ошибка сервера (не найден обработчик для {entity_type}).")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")

            return False

        # Build context for passing to cleanup and manager methods
        movement_context: Dict[str, Any] = {
            **kwargs, # Start with all incoming kwargs
            'guild_id': guild_id_str, # Ensure guild_id is in context
            'entity_id': entity_id,
            'entity_type': entity_type,
            'from_location_instance_id': from_location_id,
            'to_location_instance_id': to_location_id,
            'location_manager': self, # Pass self
            # Ensure essential managers/processors are in context, preferring injected over kwargs if both exist (optional)
            # Example: 'character_manager': self._character_manager or kwargs.get('character_manager'),
            # It's usually better to just pass kwargs and let the methods using them decide which source to trust.
        }
        # Add managers/processors from self if not already in kwargs (alternative to preferred method above)
        # This ensures they are always available in the context if injected into LocationManager.
        # if self._rule_engine and 'rule_engine' not in movement_context: movement_context['rule_engine'] = self._rule_engine
        # ... add other managers from self ...
        # A simpler approach is to list critical ones explicitly:
        critical_managers = {
            'rule_engine': self._rule_engine, 'event_manager': self._event_manager,
            'character_manager': self._character_manager, 'npc_manager': self._npc_manager,
            'item_manager': self._item_manager, 'combat_manager': self._combat_manager,
            'status_manager': self._status_manager, 'party_manager': self._party_manager,
            'time_manager': self._time_manager, 'send_callback_factory': self._send_callback_factory,
            'event_stage_processor': self._event_stage_processor, 'event_action_processor': self._event_action_processor,
            'on_enter_action_executor': self._on_enter_action_executor, 'stage_description_generator': self._stage_description_generator,
            # Add others...
        }
        # Add critical managers from self if they exist AND are not already in the incoming kwargs
        for mgr_name, mgr_instance in critical_managers.items():
             if mgr_instance is not None and mgr_name not in movement_context:
                  movement_context[mgr_name] = mgr_instance
        # Now movement_context contains incoming kwargs + essential injected managers (if not overridden by kwargs)


        # 1. Handle OnExit triggers for the source location (if moving from a location)
        if from_location_id:
            # handle_entity_departure takes location_id (instance ID), entity_id, entity_type, and **context
            await self.handle_entity_departure(from_location_id, entity_id, entity_type, **movement_context)

        # 2. Update location_id within the entity's model via its manager
        # Call the correct manager method: update_character_location or update_npc_location etc.
        try:
            # The update_location method is expected to take (entity_id, new_location_id, context=...)
            # and handle marking the entity dirty internally.
            # LocationManager does NOT mark the entity dirty directly.
            await getattr(mgr, update_location_method_name)(
                 entity_id, # ID of the entity being moved
                 to_location_id, # The new location (instance ID)
                 context=movement_context # Pass the full context dictionary
            )
            print(f"LocationManager: Successfully updated location for {entity_type} {entity_id} to {to_location_id} for guild {guild_id_str} via {type(mgr).__name__}.")
        except Exception as e:
             print(f"LocationManager: ❌ Error updating location for {entity_type} {entity_id} to {to_location_id} for guild {guild_id_str} via {type(mgr).__name__}: {e}")
             traceback.print_exc()
             # Decide if movement fails critically if location update fails.
             # If the entity's state isn't updated, it's still 'stuck' in the old location data.
             # This is a critical failure for the move operation. Re-raise or return False.
             # Let's return False and log the error.
             # raise # Or re-raise
             # Send feedback if possible
             send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
             channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
             if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Произошла внутренняя ошибка при попытке обновить вашу локацию. Пожалуйста, сообщите об этом администратору.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")
             return False


        # 3. Handle OnEnter triggers for the target location
        # handle_entity_arrival takes location_id (instance ID), entity_id, entity_type, and **context
        await self.handle_entity_arrival(to_location_id, entity_id, entity_type, **movement_context)

        print(f"LocationManager: Completed movement process for {entity_type} {entity_id} for guild {guild_id_str} to {to_location_id}.")
        return True # Indicate successful movement


    # Helper methods handle_entity_arrival and handle_entity_departure now use **kwargs context
    # They need to get RuleEngine and potentially other managers from kwargs.

    async def handle_entity_arrival(
        self,
        location_id: str, # Instance ID
        entity_id: str,
        entity_type: str,
        **kwargs: Any, # Context with managers and other info (includes guild_id)
    ) -> None:
        """Обработка триггеров при входе сущности в локацию (инстанс) для определенной гильдии."""
        guild_id = kwargs.get('guild_id') # Get guild_id from context
        if not guild_id: print("LocationManager: Warning: guild_id missing in context for handle_entity_arrival."); return
        guild_id_str = str(guild_id)

        # Get the location instance and its template for this guild
        instance_data = self.get_location_instance(guild_id_str, location_id)
        template_id = instance_data.get('template_id') if instance_data else None
        tpl = self.get_location_static(guild_id_str, template_id) # Use get_location_static with guild_id

        if not tpl:
             print(f"LocationManager: Warning: No template found for location instance {location_id} (guild {guild_id_str}) on arrival of {entity_type} {entity_id}. Cannot execute triggers.")
             return # Cannot proceed without a template

        triggers = tpl.get('on_enter_triggers') # Get triggers from template data

        # Get RuleEngine and OnEnterActionExecutor from kwargs (context)
        engine: Optional["RuleEngine"] = kwargs.get('rule_engine') # Use from context first
        if engine is None: engine = self._rule_engine # Fallback to injected

        on_enter_action_executor: Optional["OnEnterActionExecutor"] = kwargs.get('on_enter_action_executor') # Use from context first
        if on_enter_action_executor is None: on_enter_action_executor = self._on_enter_action_executor # Fallback


        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers') and on_enter_action_executor and hasattr(on_enter_action_executor, 'execute_actions'):
            print(f"LocationManager: Executing {len(triggers)} OnEnter triggers for {entity_type} {entity_id} in location {location_id} (guild {guild_id_str}).")
            try:
                # Build context for trigger evaluation and action execution
                trigger_context = {
                     **kwargs, # Pass all incoming context (includes guild_id, managers etc.)
                     'location_instance_id': location_id, # Use instance ID
                     # Add entity/location specific details to context
                     'entity_id': entity_id, 'entity_type': entity_type,
                     'location_template_id': tpl.get('id'),
                     'location_instance_data': instance_data, # Pass instance data
                     'location_template_data': tpl,
                     # You might add the actual entity object here if it's available in kwargs
                     # 'character': kwargs.get('character'), 'npc': kwargs.get('npc'), etc.
                 }
                # Call RuleEngine to execute the triggers, passing the enriched context
                # RuleEngine is expected to use the context to find necessary managers/executors (like on_enter_action_executor)
                # RuleEngine.execute_triggers(triggers: List[Dict[str, Any]], context: Dict[str, Any]) -> Awaitable[Any]
                await engine.execute_triggers(triggers, context=trigger_context)
                print(f"LocationManager: OnEnter triggers executed for {entity_type} {entity_id}.")

            except Exception as e:
                print(f"LocationManager: ❌ Error executing OnEnter triggers for {entity_type} {entity_id} in {location_id} (guild {guild_id_str}): {e}")
                traceback.print_exc()
        elif triggers:
             # Log warning if triggers defined but RuleEngine/Executor is missing (get from context first)
             missing = []
             if not engine: missing.append("RuleEngine (injected or in context)")
             if not on_enter_action_executor: missing.append("OnEnterActionExecutor (injected or in context)")
             if missing:
                 print(f"LocationManager: Warning: OnEnter triggers defined for location {location_id} (guild {guild_id_str}), but missing dependencies: {', '.join(missing)}.")
        # else: print(f"LocationManager: No OnEnter triggers defined for location {location_id} (guild {guild_id_str}).") # Too noisy if many locations


    async def handle_entity_departure(
        self,
        location_id: str, # Instance ID
        entity_id: str,
        entity_type: str,
        **kwargs: Any, # Context with managers and other info (includes guild_id)
    ) -> None:
        """Обработка триггеров при выходе сущности из локации (инстанс) для определенной гильдии."""
        guild_id = kwargs.get('guild_id') # Get guild_id from context
        if not guild_id: print("LocationManager: Warning: guild_id missing in context for handle_entity_departure."); return
        guild_id_str = str(guild_id)


        # Get the location instance and its template for this guild
        # Note: If this is called as part of delete_location_instance, the instance might be gone from cache.
        # The context should contain enough info (like location_template_id, location_instance_data) if needed.
        instance_data = self.get_location_instance(guild_id_str, location_id)
        template_id = instance_data.get('template_id') if instance_data else None
        # If instance_data is None (because it was just deleted from cache), try to get template_id from context if passed
        if template_id is None: template_id = kwargs.get('location_template_id')

        tpl = self.get_location_static(guild_id_str, template_id) # Use get_location_static with guild_id

        if not tpl:
             # This might happen if the template was also deleted or never existed
             print(f"LocationManager: Warning: No template found for location instance {location_id} (guild {guild_id_str}) on departure of {entity_type} {entity_id}. Cannot execute triggers.")
             return # Cannot proceed without a template

        triggers = tpl.get('on_exit_triggers') # Get triggers from template data

        # Get RuleEngine and OnEnterActionExecutor from kwargs (context) (assuming same executor for OnExit)
        engine: Optional["RuleEngine"] = kwargs.get('rule_engine') # Use from context first
        if engine is None: engine = self._rule_engine # Fallback to injected

        on_enter_action_executor: Optional["OnEnterActionExecutor"] = kwargs.get('on_enter_action_executor') # Use from context first
        if on_enter_action_executor is None: on_enter_action_executor = self._on_enter_action_executor # Fallback


        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers') and on_enter_action_executor and hasattr(on_enter_action_executor, 'execute_actions'):
            print(f"LocationManager: Executing {len(triggers)} OnExit triggers for {entity_type} {entity_id} from location {location_id} (guild {guild_id_str}).")
            try:
                 # Build context for trigger evaluation and action execution
                trigger_context = {
                     **kwargs, # Pass all incoming context (includes guild_id, managers etc.)
                     'location_instance_id': location_id, # Use instance ID
                     # Add entity/location specific details to context
                     'entity_id': entity_id, 'entity_type': entity_type,
                     'location_template_id': tpl.get('id'),
                     # Pass instance data *before* departure, if available
                     'location_instance_data': instance_data, # Pass instance data if available
                     'location_template_data': tpl,
                 }
                 # Call RuleEngine to execute the triggers, passing the enriched context
                await engine.execute_triggers(triggers, context=trigger_context)
                print(f"LocationManager: OnExit triggers executed for {entity_type} {entity_id}.")

            except Exception as e:
                print(f"LocationManager: ❌ Error executing OnExit triggers for {entity_type} {entity_id} from {location_id} (guild {guild_id_str}): {e}")
                traceback.print_exc()
        elif triggers:
            # Log warning if triggers defined but RuleEngine/Executor is missing (get from context first)
            missing = []
            if not engine: missing.append("RuleEngine (injected or in context)")
            if not on_enter_action_executor: missing.append("OnEnterActionExecutor (injected or in context)")
            if missing:
                print(f"LocationManager: Warning: OnExit triggers defined for location {location_id} (guild {guild_id_str}), but missing dependencies: {', '.join(missing)}.")
        # else: print(f"LocationManager: No OnExit triggers defined for location {location_id} (guild {guild_id_str}).") # Too noisy


    # Добавляем метод process_tick для совместимости с PersistenceManager
    # ИСПРАВЛЕНИЕ: Добавляем guild_id и kwargs
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
         """Обработка игрового тика для локаций для определенной гильдии."""
         guild_id_str = str(guild_id)
         # print(f"LocationManager: Processing tick for guild {guild_id_str}. Delta: {game_time_delta}. (Placeholder)") # Too noisy


         # If location state changes over time (e.g., resource regeneration, environmental effects)
         # this is the place to process it.
         # Get RuleEngine from kwargs or self
         rule_engine = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]

         if rule_engine and hasattr(rule_engine, 'process_location_tick'):
             # Get all active location instances for this guild
             guild_instances = self._location_instances.get(guild_id_str, {}).values()
             # Build managers context for the tick processing in RuleEngine
             managers_context = {
                 **kwargs, # Start with all incoming kwargs
                 'guild_id': guild_id_str, # Ensure guild_id is in context
                 'location_manager': self, # Pass self
                 'game_time_delta': game_time_delta, # Pass time delta explicitly
                 # Add other essential managers from self if not in kwargs (similar logic to move_entity)
                 # Example: 'item_manager': self._item_manager or kwargs.get('item_manager'), etc.
             }
             critical_managers = {
                 'item_manager': self._item_manager, 'status_manager': self._status_manager,
                 # Add others...
             }
             for mgr_name, mgr_instance in critical_managers.items():
                  if mgr_instance is not None and mgr_name not in managers_context:
                       managers_context[mgr_name] = mgr_instance


             for instance in guild_instances:
                  # Check if instance is active and has an ID
                  instance_id = instance.get('id')
                  is_active = instance.get('is_active', False)

                  if instance_id and is_active:
                       try:
                            # Get the location template for the instance
                            template_id = instance.get('template_id')
                            template = self.get_location_static(guild_id_str, template_id)

                            if not template:
                                 print(f"LocationManager: Warning: Template not found for active instance {instance_id} in guild {guild_id_str} during tick.")
                                 continue # Skip tick processing if template is missing

                            # Call RuleEngine to process tick logic for this specific instance
                            # Assumes RuleEngine.process_location_tick(location_instance: Dict[str, Any], location_template: Dict[str, Any], context: Dict[str, Any]) -> Awaitable[None]
                            await rule_engine.process_location_tick(
                                instance=instance, # Pass instance data (mutable)
                                template=template, # Pass template data (immutable)
                                context=managers_context # Pass context
                            )
                            # RuleEngine.process_location_tick is responsible for updating instance['state']
                            # if state changes, and potentially calling self.mark_location_instance_dirty

                       except Exception as e:
                            print(f"LocationManager: ❌ Error processing tick for location instance {instance_id} in guild {guild_id_str}: {e}")
                            traceback.print_exc()

         elif rule_engine:
             # Log warning if RuleEngine exists but the method is missing
              print(f"LocationManager: Warning: RuleEngine injected/found, but 'process_location_tick' method not found for tick processing.")
         # else: print(f"LocationManager: No RuleEngine available for location tick processing.") # Too noisy


    # Helper to get template considering per-guild storage
    # get_location_static now needs guild_id and template_id
    def get_location_static(self, guild_id: str, template_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Получить статический шаблон локации по ID для данной гильдии."""
        guild_id_str = str(guild_id)
        # Assuming _location_templates is Dict[str, Dict[str, Dict[str, Any]]] = {guild_id: {tpl_id: data}}
        guild_templates = self._location_templates.get(guild_id_str, {})
        # Ensure template_id is string before lookup
        return guild_templates.get(str(template_id)) if template_id is not None else None

    # Helper to clear guild state cache
    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        # Remove all caches for the specific guild ID
        self._location_templates.pop(guild_id_str, None)
        self._location_instances.pop(guild_id_str, None)
        self._dirty_instances.pop(guild_id_str, None)
        self._deleted_instances.pop(guild_id_str, None)
        print(f"LocationManager: Cleared cache for guild {guild_id_str}.")

    # Helper to mark an instance as dirty (per-guild)
    # İSPRAVLENIE: mark_location_instance_dirty должен принимать guild_id
    def mark_location_instance_dirty(self, guild_id: str, instance_id: str) -> None:
         """Помечает инстанс локации как измененный для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         instance_id_str = str(instance_id)
         # Check if the instance exists in the per-guild cache
         if guild_id_str in self._location_instances and instance_id_str in self._location_instances[guild_id_str]:
              # Add to the per-guild dirty set
              self._dirty_instances.setdefault(guild_id_str, set()).add(instance_id_str)
         # else: print(f"LocationManager: Warning: Attempted to mark non-existent instance {instance_id_str} in guild {guild_id_str} as dirty.") # Too noisy?


# --- Конец класса LocationManager ---
