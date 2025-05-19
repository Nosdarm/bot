# bot/game/managers/location_manager.py

from __future__ import annotations
import json
import traceback
import asyncio
# --- Необходимые импорты для runtime ---
# uuid нужен для генерации ID инстансов
import uuid

# --- Базовые типы и TYPE_CHECKING ---
# Set и другие типы нужны для аннотаций
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING

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
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator

    # Add other managers/processors/services if they are dependencies passed via kwargs and might cause cycles


# --- Imports needed at Runtime ---
# Только импортируйте модули/классы здесь, если они строго необходимы для выполнения кода
# (например, создание экземпляров, вызов статических методов, isinstance проверки).
# Если класс используется только для аннотаций типов, импортируйте его в блок TYPE_CHECKING выше.

# Прямых импортов менеджеров/процессоров здесь больше нет, так как они получены через dependency injection.


# Define Callback Types (Callable types не требуют строковых литералов, если базовые типы определены)
SendToChannelCallback = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]] # Добавлена Optional Dict для консистентности
SendCallbackFactory = Callable[[int], SendToChannelCallback]

# Add TYPE_CHECKING for types used in the callback signature if they cause cycles? Unlikely for str/Dict/Any.


class LocationManager:
    """
    Менеджер для управления локациями игрового мира.
    Хранит статические шаблоны локаций и обрабатывает триггеры OnEnter/OnExit.
    """
    # Добавляем required_args для совместимости с PersistenceManager
    # Если локации динамические и зависят от guild_id, добавляем ["guild_id"].
    # Судя по возвращенной логике save/load_state, они работают per-guild.
    required_args_for_load = ["guild_id"] # Если PersistenceManager передает guild_id в load_state
    required_args_for_save = ["guild_id"] # Если PersistenceManager передает guild_id в save_state


    def __init__(
        self,
        # Используем строковые литералы для всех опциональных зависимостей
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None, # Use string literal!
        event_manager: Optional["EventManager"] = None, # Use string literal!
        character_manager: Optional["CharacterManager"] = None, # Use string literal!
        npc_manager: Optional["NpcManager"] = None, # Use string literal!
        item_manager: Optional["ItemManager"] = None, # Use string literal!
        combat_manager: Optional["CombatManager"] = None, # Use string literal!
        status_manager: Optional["StatusManager"] = None, # Use string literal!
        party_manager: Optional["PartyManager"] = None, # Use string literal!
        time_manager: Optional["TimeManager"] = None, # Use string literal!
        send_callback_factory: Optional[SendCallbackFactory] = None,
        event_stage_processor: Optional["EventStageProcessor"] = None, # Use string literal!
        event_action_processor: Optional["EventActionProcessor"] = None, # Use string literal!
        # Добавляем OnEnter/OnExit action executors и generator, если инжектируются напрямую
        on_enter_action_executor: Optional["OnEnterActionExecutor"] = None, # Use string literal!
        stage_description_generator: Optional["StageDescriptionGenerator"] = None, # Use string literal!

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
        self._stage_description_generator = stage_description_generator


        # Статические шаблоны локаций (теперь per-guild)
        self._location_templates: Dict[str, Dict[str, Dict[str, Any]]] = {} # {guild_id: {tpl_id: data}}
        # Динамические инстансы (per-guild)
        self._location_instances: Dict[str, Dict[str, Dict[str, Any]]] = {} # {guild_id: {instance_id: data}}
        # Наборы "грязных" и удаленных инстансов (per-guild)
        self._dirty_instances: Dict[str, Set[str]] = {} # {guild_id: {instance_id, ...}} - Use Set! (Ln 511 approx location for Set error if not imported)
        self._deleted_instances: Dict[str, Set[str]] = {} # {guild_id: {instance_id, ...}}

        print("LocationManager initialized.")

    # --- Методы для PersistenceManager ---
    # Переименовываем load_location_templates в load_state, чтобы соответствовать интерфейсу
    async def load_state(self, guild_id: str, **kwargs: Any) -> None: # Добавляем guild_id и kwargs
        """Загружает статические шаблоны локаций и динамические инстансы для гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Loading state for guild {guild_id_str} (static templates + instances)...")

        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"] # Use string literal
        if db_adapter is None:
             print(f"LocationManager: Database adapter is not available. Cannot load state for guild {guild_id_str}.")
             raise ConnectionError("Database adapter is required for loading state.")

        # Очищаем все кеши для этой гильдии перед загрузкой
        self._clear_guild_state_cache(guild_id_str)

        # --- Загрузка статических шаблонов (per-guild) ---
        guild_templates_cache: Dict[str, Dict[str, Any]] = self._location_templates.setdefault(guild_id_str, {})

        loaded_templates_count = 0
        try:
            sql_templates = "SELECT id, template_data FROM location_templates WHERE guild_id = ?"
            rows_templates = await db_adapter.fetchall(sql_templates, (guild_id_str,))
            print(f"LocationManager: Found {len(rows_templates)} template rows for guild {guild_id_str}.")
            for row in rows_templates:
                 tpl_id = row.get('id')
                 tpl_data_json = row.get('template_data')
                 if not tpl_id: continue
                 try:
                      data = json.loads(tpl_data_json or '{}')
                      if not isinstance(data, dict): continue
                      data.setdefault('id', tpl_id) # Ensure ID is in data
                      guild_templates_cache[str(tpl_id)] = data
                      loaded_templates_count += 1
                 except json.JSONDecodeError:
                     print(f"Error decoding template '{tpl_id}' for guild {guild_id_str}: {traceback.format_exc()}. Skipping.");

            print(f"LocationManager: Loaded {loaded_templates_count} templates for guild {guild_id_str} from DB.")

        except Exception as e:
            print(f"LocationManager: ❌ Error during DB template load for guild {guild_id_str}: {e}"); traceback.print_exc();
            self._location_templates.pop(guild_id_str, None) # Clear cache only for this guild on error
            raise # Re-raise as this is likely critical


        # --- Загрузка динамических инстансов (per-guild) ---
        guild_instances_cache = self._location_instances.setdefault(guild_id_str, {})
        # dirty_instances set and deleted_instances set for this guild were cleared by _clear_guild_state_cache

        loaded_instances_count = 0

        try:
            sql_instances = '''
            SELECT id, template_id, state_json, is_active, guild_id FROM locations WHERE guild_id = ?
            '''
            rows_instances = await db_adapter.fetchall(sql_instances, (guild_id_str,))
            if rows_instances:
                 print(f"Found {len(rows_instances)} instances for guild {guild_id_str}.")

                 for row in rows_instances:
                      try:
                           instance_id_raw = row.get('id')
                           loaded_guild_id_raw = row.get('guild_id')

                           if not instance_id_raw or str(loaded_guild_id_raw) != guild_id_str:
                                print(f"Warning: Skipping instance with invalid ID ('{instance_id_raw}') or mismatched guild_id ('{loaded_guild_id_raw}').")
                                continue

                           instance_id = str(instance_id_raw)
                           state_json_raw = row.get('state_json')
                           instance_state_data = json.loads(state_json_raw or '{}') if state_json_raw else {}
                           if not isinstance(instance_state_data, dict):
                               instance_state_data = {}
                               print(f"Warning: State data for instance ID {instance_id} not a dict. Resetting.")

                           instance_data: Dict[str, Any] = {
                               'id': instance_id,
                               'guild_id': guild_id_str,
                               'template_id': row.get('template_id'),
                               'state': instance_state_data,
                               'is_active': bool(row.get('is_active', 0)) # Ensure boolean
                           }

                           if not instance_data.get('template_id'):
                               print(f"Warning: Instance ID {instance_id} missing template_id. Skipping load.")
                               continue

                           guild_instances_cache[instance_data['id']] = instance_data
                           loaded_instances_count += 1

                      except json.JSONDecodeError:
                          print(f"Error decoding JSON for instance (ID: {row.get('id', 'N/A')}, guild: {row.get('guild_id', 'N/A')}): {traceback.format_exc()}. Skipping.");
                      except Exception as e:
                          print(f"Error processing instance row (ID: {row.get('id', 'N/A')}, guild: {row.get('guild_id', 'N/A')}): {e}. Skipping."); traceback.print_exc();

                 print(f"Loaded {loaded_instances_count} instances for guild {guild_id_str}.")
            else: print(f"No instances found for guild {guild_id_str}.")
        except Exception as e:
            print(f"❌ Error during DB instance load for guild {guild_id_str}: {e}"); traceback.print_exc();
            # Clear caches for this guild on error
            self._location_instances.pop(guild_id_str, None)
            self._dirty_instances.pop(guild_id_str, None)
            self._deleted_instances.pop(guild_id_str, None)
            raise # Re-raise as this is likely critical


        print(f"LocationManager: Load state complete for guild {guild_id_str}.") # Corrected logging message

    # Переименовываем в save_state, чтобы соответствовать интерфейсу
    async def save_state(self, guild_id: str, **kwargs: Any) -> None: # Добавляем guild_id и kwargs
        """Сохраняет измененные/удаленные динамические инстансы локаций для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Saving state for guild {guild_id_str}...")
        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"]
        if db_adapter is None: print(f"Database adapter not available. Skipping save for guild {guild_id_str}.") ; return

        # Получаем per-guild кеши, используем get() с default {} или set() для безопасности
        guild_instances_cache = self._location_instances.get(guild_id_str, {})
        dirty_instances = self._dirty_instances.get(guild_id_str, set()) # Uses Set (should be defined)
        deleted_instances = self._deleted_instances.get(guild_id_str, set()) # Uses Set (should be defined)


        try:
            # Удалить помеченные для удаления инстансы для этого guild_id
            if deleted_instances:
                 ids_to_delete = list(deleted_instances)
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 sql_delete_batch = f"DELETE FROM locations WHERE guild_id = ? AND id IN ({placeholders_del})"
                 await db_adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete)));
                 print(f"LocationManager: Deleted {len(ids_to_delete)} instances from DB for guild {guild_id_str}.")
                 # Очищаем per-guild deleted set
                 deleted_instances.clear()

            # Обновить или вставить измененные инстансы для этого guild_id
            # Фильтруем dirty_instances на те, что все еще существуют в кеше (не были удалены)
            instances_to_upsert = [ inst for id in list(dirty_instances) if (inst := guild_instances_cache.get(id)) is not None ] # Use list(dirty_instances) to iterate over a copy

            if instances_to_upsert:
                 print(f"LocationManager: Upserting {len(instances_to_upsert)} instances for guild {guild_id_str}...")
                 upsert_sql = ''' INSERT OR REPLACE INTO locations (id, guild_id, template_id, state_json, is_active) VALUES (?, ?, ?, ?, ?) '''
                 data_to_upsert = []
                 for instance_data in instances_to_upsert:
                      try:
                          instance_id = instance_data.get('id')
                          if not instance_id: continue # Skip if missing ID
                          data_to_upsert.append((
                              instance_id,
                              guild_id_str, # Ensure correct guild_id
                              instance_data.get('template_id'),
                              json.dumps(instance_data.get('state', {})),
                              int(instance_data.get('is_active', True)), # Ensure int
                          ));
                      except Exception as e:
                          print(f"Error preparing data for instance {instance_data.get('id', 'N/A')} for upsert: {e}"); traceback.print_exc();
                          # Decide if you want to skip or raise. Skipping allows saving other instances.
                          pass # Skip this instance


                 if data_to_upsert:
                     try:
                         await db_adapter.execute_many(upsert_sql, data_to_upsert);
                         print(f"LocationManager: Successfully upserted {len(data_to_upsert)} instances for guild {guild_id_str}.")
                         # Only clear dirty flags for instances that were successfully processed
                         # Assuming execute_many is all or nothing, clear all in the set for this guild.
                         dirty_instances.clear()
                     except Exception as e:
                          print(f"LocationManager: Error during batch upsert for guild {guild_id_str}: {e}"); traceback.print_exc();
                          # Don't clear dirty_instances if batch upsert failed

            else: print(f"No dirty instances to save for guild {guild_id_str}.")

        except Exception as e: print(f"❌ Error during saving state for guild {guild_id_str}: {e}"); traceback.print_exc();
        # Decide if you want to clear dirty/deleted here on failure or keep them to allow retry
        # Keeping them allows retry, clearing might prevent infinite loop on persistent error
        # For save, it might be better NOT to clear on error.
        # raise # Re-raise if this is a critical failure


    # Add rebuild_runtime_caches
    def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Rebuilding runtime caches for guild {guild_id_str}. (Placeholder)")
        # Если у вас есть кеши, которые нужно построить на основе загруженных локаций-инстансов,
        # например, кеш локаций по каналу {channel_id: instance_id},
        # или кеш персонажей/NPC по локации {location_id: set(entity_id)}.
        # Note: Кеш сущностей по локации лучше хранить в менеджерах сущностей (Character/NPC Manager),
        # которые должны получать загруженные данные локаций (через этот менеджер в контексте kwargs
        # или через direct dependency injection при необходимости).
        # Получаем инстансы локаций для этой гильдии:
        guild_instances = self._location_instances.get(guild_id_str, {}).values()
        # Получаем другие менеджеры из kwargs, если они нужны для перестройки
        # char_mgr = kwargs.get('character_manager') # type: Optional["CharacterManager"] # Use string literal


    # --- Dynamic Instance Management (вернули методы из более раннего кода) ---
    # предполагаем, что инстансы per-guild

    async def create_location_instance(self, guild_id: str, template_id: str, initial_state: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
         guild_id_str = str(guild_id)
         print(f"LocationManager: Creating instance for guild {guild_id_str} from template {template_id} in memory...")

         # Получаем шаблон для этой гильдии
         guild_templates = self._location_templates.get(guild_id_str, {})
         template = guild_templates.get(str(template_id))

         if not template:
             print(f"Error creating instance: Template '{template_id}' not found for guild {guild_id_str}.")
             return None
         if not template.get('name'):
             print(f"Error creating instance: Template '{template_id}' missing 'name' for guild {guild_id_str}.")
             return None

         new_instance_id = str(uuid.uuid4()) # Uses uuid (should be defined)

         template_initial_state = template.get('initial_state', {})
         if not isinstance(template_initial_state, dict):
             template_initial_state = {}
             print(f"Warning: Template '{template_id}' initial_state not a dict.")

         instance_state_data = dict(template_initial_state)
         if initial_state is not None:
             if isinstance(initial_state, dict):
                 instance_state_data.update(initial_state)
             else:
                 print(f"Warning: Provided initial_state not a dict.")

         instance_for_cache = {
             'id': new_instance_id,
             'guild_id': guild_id_str, # Store guild_id in instance data
             'template_id': template_id,
             'state': instance_state_data,
             'is_active': True,
         }

         # Добавляем инстанс в кеш для данной гильдии
         self._location_instances.setdefault(guild_id_str, {})[new_instance_id] = instance_for_cache

         # Помечаем инстанс грязным для данной гильдии
         if self._db_adapter:
             self._dirty_instances.setdefault(guild_id_str, set()).add(new_instance_id) # Uses set() - should be defined

         print(f"LocationManager: Instance {new_instance_id} added to cache and marked dirty (if DB enabled) for guild {guild_id_str}.")
         return instance_for_cache

    def get_location_instance(self, guild_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
         """Получить динамический инстанс локации по ID для данной гильдии."""
         # Получаем инстанс из кеша для данной гильдии
         guild_instances = self._location_instances.get(str(guild_id), {})
         return guild_instances.get(str(instance_id))

    async def delete_location_instance(self, guild_id: str, instance_id: str, **kwargs: Any) -> bool:
        """Пометить динамический инстанс локации для удаления для данной гильдии."""
        guild_id_str = str(guild_id)
        instance_id_str = str(instance_id)

        # Проверяем и удаляем из кеша для данной гильдии
        guild_instances = self._location_instances.get(guild_id_str, {})
        if instance_id_str in guild_instances:
             del guild_instances[instance_id_str]

             # Добавляем в список удаленных для данной гильдии
             self._deleted_instances.setdefault(guild_id_str, set()).add(instance_id_str) # Uses set() - should be defined

             # Удаляем из списка грязных для данной гильдии, если там был
             self._dirty_instances.setdefault(guild_id_str, set()).discard(instance_id_str) # Uses set() - should be defined

             print(f"LocationManager: Instance {instance_id_str} marked for deletion for guild {guild_id_str}.")
             return True
        print(f"LocationManager: Warning: Attempted to delete non-existent instance {instance_id_str} for guild {guild_id_str}.")
        return False

    def get_location_name(self, guild_id: str, instance_id: str) -> Optional[str]:
         """Получить название инстанса локации по ID для данной гильдии."""
         instance = self.get_location_instance(guild_id, instance_id)
         if instance:
             # Получаем шаблон для этой гильдии по template_id инстанса
             guild_templates = self._location_templates.get(str(guild_id), {})
             template = guild_templates.get(instance.get('template_id'))
             if template and template.get('name'):
                  return template.get('name')

         # Если инстанс или шаблон не найден, или у шаблона нет имени, возвращаем дефолт
         if instance and instance.get('id'):
             return f"Unnamed Location ({instance['id']})"
         if isinstance(instance_id, str):
             return f"Unknown Location ({instance_id})" # Fallback using requested ID
         return None

    # Убедитесь, что get_connected_locations работает с инстансом и его шаблоном для данной гильдии
    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]:
         """Получить связанные локации (выходы) для инстанса локации по ID для данной гильдии."""
         instance = self.get_location_instance(guild_id, instance_id)
         if instance:
              # Получаем шаблон для этой гильдии по template_id инстанса
             guild_templates = self._location_templates.get(str(guild_id), {})
             template = guild_templates.get(instance.get('template_id'))
             if template:
                 connections = template.get('exits') or template.get('connected_locations')
                 if isinstance(connections, dict): return connections
                 # Если выходы заданы как список ID, преобразуем в словарь {id: id}
                 if isinstance(connections, list): return {str(loc_id): str(loc_id) for loc_id in connections} # Убедимся, что ключи и значения - строки
         return {}


    async def update_location_state(self, guild_id: str, instance_id: str, state_updates: Dict[str, Any], **kwargs: Any) -> bool:
        """Обновляет динамическое состояние инстанса локации для данной гильдии."""
        guild_id_str = str(guild_id)
        instance_data = self.get_location_instance(guild_id_str, instance_id)
        if instance_data:
            current_state = instance_data.setdefault('state', {})
            if not isinstance(current_state, dict):
                current_state = {} # Reset if not a dict
                instance_data['state'] = current_state # Update in instance_data
            current_state.update(state_updates)
            # Помечаем инстанс грязным для данной гильдии
            if self._db_adapter:
                self._dirty_instances.setdefault(guild_id_str, set()).add(instance_data['id']) # Uses set() - should be defined
            print(f"LocationManager: Updated state for instance {instance_data['id']} for guild {guild_id_str}. Marked dirty (if DB enabled).")
            return True
        print(f"LocationManager: Warning: Attempted to update state for non-existent instance {instance_id} for guild {guild_id_str}.")
        return False


    def get_location_channel(self, guild_id: str, instance_id: str) -> Optional[int]:
        """Получить ID канала для инстанса локации для данной гильдии."""
        instance = self.get_location_instance(guild_id, instance_id)
        if instance:
            # Получаем шаблон для этой гильдии по template_id инстанса
            guild_templates = self._location_templates.get(str(guild_id), {})
            template = guild_templates.get(instance.get('template_id'))
            if template and template.get('channel_id') is not None:
                 try: return int(template['channel_id']) # Убеждаемся, что возвращаем int
                 except (ValueError, TypeError): print(f"Warning: Invalid channel_id in template {template.get('id', 'N/A')} for instance {instance_id}.") ; return None
        return None

    # Добавляем метод get_default_location_id, который использовался в CharacterManager
    # Его реализация может зависеть от того, хранятся ли дефолты в настройках или в шаблонах
    def get_default_location_id(self, guild_id: str) -> Optional[str]: # Добавляем guild_id, если дефолт per-guild
        """Получить ID дефолтной начальной локации для данной гильдии."""
        # Пример: дефолт в настройках
        guild_settings = self._settings.get(str(guild_id), self._settings) # Попытка получить per-guild настройки, иначе общие
        default_id = guild_settings.get('default_start_location_id')
        if default_id and isinstance(default_id, str):
             # Optional: проверить, существует ли инстанс или шаблон с таким ID для этой гильдии
             # if self.get_location_instance(guild_id, default_id) or self.get_location_static(guild_id, default_id): # Если static templates тоже per-guild
             return default_id
        # Пример: дефолт в шаблонах (может быть специальный шаблон 'start')
        # guild_templates = self._location_templates.get(str(guild_id), {})
        # start_template = guild_templates.get('start') # Ищем шаблон с id='start'
        # if start_template: return start_template.get('id')
        print(f"LocationManager: Warning: Default start location not found for guild {guild_id}.")
        return None # Нет дефолта

    # --- Методы для перемещения сущностей (используют динамические инстансы) ---

    async def move_entity(
        self,
        guild_id: str, # Добавляем guild_id
        entity_id: str,
        entity_type: str,
        from_location_id: Optional[str], # Теперь это instance_id
        to_location_id: str, # Теперь это instance_id
        **kwargs: Any,
    ) -> bool:
        """Универсальный метод для перемещения сущности (Character/NPC/Item/Party) между инстансами локаций."""
        print(f"LocationManager: Attempting to move {entity_type} {entity_id} for guild {guild_id} from {from_location_id} to {to_location_id}.")

        # Проверяем наличие целевого инстанса локации для этой гильдии
        target_instance = self.get_location_instance(guild_id, to_location_id)
        if not target_instance:
             print(f"LocationManager: Error: Target location instance '{to_location_id}' not found for guild {guild_id}. Cannot move.")
             # Опционально: уведомить через send_message_callback, если доступен в kwargs
             # send_cb = kwargs.get('send_message_callback')
             # if send_cb: await send_cb(f"Ошибка перемещения: Локация {to_location_id} не найдена.", None)
             return False

        # Получаем соответствующий менеджер сущностей из kwargs или из __init__
        # Используем строковые литералы в аннотациях переменных
        mgr: Optional[Any] = None # Тип Any, т.к. может быть разный менеджер
        # dirty_set: Optional[Set[str]] = None # No longer needed here if manager handles its own dirty state
        get_method_name = None # No longer needed here
        update_location_method_name = None
        # manager_attr is used below to get the manager name string - is defined below

        if entity_type == 'Character':
            mgr = kwargs.get('character_manager', self._character_manager) # Fallback to injected
            # Предполагаем, что character_manager.update_character_location существует и принимает (char_id, location_id, context)
            update_location_method_name = 'update_character_location'
            manager_attr = '_character_manager' # Define manager_attr explicitly or derive it
        elif entity_type == 'NPC':
            mgr = kwargs.get('npc_manager', self._npc_manager)
            update_location_method_name = 'update_npc_location'
            manager_attr = '_npc_manager' # Define manager_attr explicitly or derive it
        # TODO: Add other entity types like 'Party', 'Item' if needed for movement
        else:
            print(f"LocationManager: Error: Movement not supported for entity type {entity_type}.")
            return False


        if not mgr or not hasattr(mgr, update_location_method_name):
            print(f"LocationManager: Error: No suitable manager ({manager_attr} or via kwargs) or update method ('{update_location_method_name}') found for entity type {entity_type}.") # manager_attr used here - is defined now
            # Опционально: уведомить через send_message_callback
            return False

        # Получаем объект сущности через соответствующий менеджер
        # Предполагаем, что get_ methods в менеджерах сущностей принимают (guild_id, entity_id) или просто (entity_id)
        # А затем проверяют guild_id внутри. Убедимся, что get_character/get_npc принимают guild_id.
        # Если get_ character/npc принимают только entity_id, то нужно убедиться, что ID уникальны по всему боту.
        # Судя по CharacterManager, get_character_by_discord_id использует discord_id, get_character использует char_id.
        # update_character_location в CharacterManager принимает (character_id, location_id). Не guild_id!
        # Нужно решить: manager methods need guild_id?
        # Если методы менеджера сущностей (update_location, get_entity) не принимают guild_id,
        # но менеджер кеширует per-guild данные, это может быть проблемой.
        # В CharacterManager методы save/load_state теперь работают с guild_id.
        # А методы типа get_character(char_id) - работают с глобальным кешем (_characters).
        # update_character_location(char_id, loc_id) - тоже работает с глобальным кешем.
        # Это означает, что уникальность char_id должна быть в рамках всего бота, а не гильдии.
        # А методы менеджера должны полагаться на guild_id внутри объекта Character/NPC.

        # Получим сущность. Предположим, менеджеры сущностей умеют получить по ID (без guild_id здесь).
        # Хотя логичнее, чтобы менеджеры, кеширующие per-guild, требовали guild_id в геттерах.
        # Let's assume get_ methods might need guild_id:
        # entity = getattr(mgr, get_method_name)(guild_id, entity_id) if hasattr(mgr, get_method_name) else None
        # Или если геттер не требует guild_id, но мы должны убедиться, что сущность принадлежит гильдии
        # entity = getattr(mgr, get_method_name)(entity_id)
        # if entity and str(entity.guild_id) != str(guild_id):
        #      print("Error: Entity belongs to wrong guild") ; return False
        # Let's assume update_character_location etc are enough.

        # Создаем контекст для передачи в OnExit/OnEnter и метод обновления локации менеджера сущностей
        movement_context: Dict[str, Any] = { # Explicit Dict annotation
            'guild_id': guild_id,
            'entity_id': entity_id,
            'entity_type': entity_type,
            'from_location_instance_id': from_location_id,
            'to_location_instance_id': to_location_id,
            # Передаем все менеджеры и колбэки из kwargs или __init__
            'location_manager': self,
            # Get managers/processors from kwargs first, fallback to injected.
            'rule_engine': kwargs.get('rule_engine', self._rule_engine),
            'event_manager': kwargs.get('event_manager', self._event_manager),
            'character_manager': kwargs.get('character_manager', self._character_manager),
            'npc_manager': kwargs.get('npc_manager', self._npc_manager),
            'item_manager': kwargs.get('item_manager', self._item_manager),
            'combat_manager': kwargs.get('combat_manager', self._combat_manager),
            'status_manager': kwargs.get('status_manager', self._status_manager),
            'party_manager': kwargs.get('party_manager', self._party_manager),
            'time_manager': kwargs.get('time_manager', self._time_manager),
            'send_callback_factory': kwargs.get('send_callback_factory', self._send_callback_factory),
            'event_stage_processor': kwargs.get('event_stage_processor', self._event_stage_processor),
            'event_action_processor': kwargs.get('event_action_processor', self._event_action_processor),
            # Add OnEnter/OnExit action executors and generator from __init__ or kwargs
            'on_enter_action_executor': kwargs.get('on_enter_action_executor', self._on_enter_action_executor), # <-- Uses OnEnterActionExecutor (should be defined via TYPE_CHECKING)
            'stage_description_generator': kwargs.get('stage_description_generator', self._stage_description_generator), # Uses StageDescriptionGenerator (should be defined via TYPE_CHECKING)

            # Включаем любые другие kwargs
            # **kwargs # Add kwargs via .update() to avoid Pylance warning if needed
        }
        movement_context.update(kwargs) # Add kwargs using update


        # 1. Обработать OnExit триггеры
        if from_location_id:
            # handle_entity_departure должен уметь использовать менеджеры из **kwargs контекста
            # uses movement_context, which contains managers and other stuff
            await self.handle_entity_departure(from_location_id, entity_id, entity_type, **movement_context)

        # 2. Обновить location_id внутри модели персонажа/NPC через его менеджер
        # Используем метод update_location_method_name, который определили выше
        # Предполагаем, что этот метод принимает (entity_id, new_location_id, context=...)
        try:
            await getattr(mgr, update_location_method_name)(
                 entity_id, # ID сущности
                 to_location_id, # Новая локация (instance_id)
                 context=movement_context # Передаем контекст
            )
            print(f"LocationManager: Successfully updated location for {entity_type} {entity_id} to {to_location_id} via {type(mgr).__name__}.")
        except Exception as e:
             print(f"LocationManager: ❌ Error updating location for {entity_type} {entity_id} to {to_location_id} via {type(mgr).__name__}: {e}")
             traceback.print_exc()
             #raise # Перебрасываем, если не удалось обновить локацию


        # 3. Обработать OnEnter триггеры
        # handle_entity_arrival должен уметь использовать менеджеры из **kwargs контекста
        # uses movement_context
        await self.handle_entity_arrival(to_location_id, entity_id, entity_type, **movement_context)


        print(f"LocationManager: Completed movement for {entity_type} {entity_id} for guild {guild_id} to {to_location_id}.")
        return True # Успех

    # Вспомогательные методы handle_entity_arrival и handle_entity_departure
    # должны получать rule_engine и, возможно, другие менеджеры через **kwargs контекста.
    # Ваши последние версии этих методов, кажется, уже используют context.get() для этого.

    async def handle_entity_arrival(
        self,
        location_id: str, # Instance ID
        entity_id: str,
        entity_type: str,
        **kwargs: Any, # Context with managers and other info
    ) -> None:
        """Обработка триггеров при входе сущности в локацию (инстанс)."""
        guild_id = kwargs.get('guild_id') # Get guild_id from context
        if not guild_id: print("LocationManager: Warning: guild_id missing in context for handle_entity_arrival."); return

        # Получаем инстанс локации и его шаблон для этой гильдии
        instance_data = self.get_location_instance(guild_id, location_id)
        template_id = instance_data.get('template_id') if instance_data else None
        tpl = self.get_location_static(guild_id, template_id) # Get template using instance data and guild_id

        if not tpl: print(f"LocationManager: Warning: No template found for location instance {location_id} (guild {guild_id}) on arrival."); return

        triggers = tpl.get('on_enter_triggers')
        # Получаем RuleEngine и OnEnterActionExecutor из kwargs (контекста) или из __init__
        engine: Optional["RuleEngine"] = kwargs.get('rule_engine', self._rule_engine)
        on_enter_action_executor: Optional["OnEnterActionExecutor"] = kwargs.get('on_enter_action_executor', self._on_enter_action_executor) # <-- Uses OnEnterActionExecutor


        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers') and on_enter_action_executor and hasattr(on_enter_action_executor, 'execute_actions'):
            print(f"LocationManager: Executing {len(triggers)} OnEnter triggers for {entity_type} {entity_id} in location {location_id} (guild {guild_id}).")
            try:
                # Context for trigger evaluation and action execution
                trigger_context = {
                     **kwargs, # Pass all context
                     'location_instance_id': location_id, # Use instance ID
                     # Add entity/location specific details to context
                     'entity_id': entity_id, 'entity_type': entity_type,
                     'location_template_id': tpl.get('id'),
                     'location_instance_data': instance_data, # Pass instance data
                     'location_template_data': tpl,
                     # Maybe add character/npc object if available? context.get('character') / context.get('npc')
                 }
                # Assuming execute_triggers finds/uses the event context from kwargs or its own context
                # If RuleEngine.execute_triggers itself orchestrates action execution,
                # and RuleEngine has access to on_enter_action_executor via context.
                # This makes the call `engine.execute_triggers(triggers, context=context)` correct.
                await engine.execute_triggers(triggers, context=trigger_context)
                print("LocationManager: OnEnter triggers executed.")

                # NOTE: execute_triggers *might* call EventActionProcessor or other things.
                # If OnEnter triggers run actions, they should likely call on_enter_action_executor.
                # The original code structure suggests triggers -> actions executed by RuleEngine.
                # OR RuleEngine.execute_triggers *calls* on_enter_action_executor.
                # If RuleEngine.execute_triggers just evaluates and decides which actions to run,
                # those actions might then be executed by on_enter_action_executor (received via context by RuleEngine).


            except Exception as e:
                print(f"LocationManager: ❌ Error executing OnEnter triggers for {entity_type} {entity_id} in {location_id} (guild {guild_id}): {e}")
                traceback.print_exc()
        elif triggers:
             # Log warning if triggers defined but RuleEngine/Executor is missing
             missing = []
             if not engine: missing.append("RuleEngine")
             if not on_enter_action_executor: missing.append("OnEnterActionExecutor")
             print(f"LocationManager: Warning: OnEnter triggers defined for location {location_id} (guild {guild_id}), but missing dependencies: {', '.join(missing)}.")
        else:
            print(f"LocationManager: No OnEnter triggers defined for location {location_id} (guild {guild_id}).") # Log if no triggers defined


    async def handle_entity_departure(
        self,
        location_id: str, # Instance ID
        entity_id: str,
        entity_type: str,
        **kwargs: Any, # Context with managers and other info
    ) -> None:
        """Обработка триггеров при выходе сущности из локации (инстанс)."""
        guild_id = kwargs.get('guild_id') # Get guild_id from context
        if not guild_id: print("LocationManager: Warning: guild_id missing in context for handle_entity_departure."); return

        # Получаем инстанс локации и его шаблон для этой гильдии (возможно, локация уже удалена из кеша, если это удаление инстанса?)
        # Если это уход игрока, инстанс должен быть в кеше. Если удаление инстанса, нужно работать с данными, переданными извне.
        # Assume instance data might not be in cache anymore if this is part of instance deletion cleanup.
        # Get instance data safely.
        instance_data = self.get_location_instance(guild_id, location_id)
        template_id = instance_data.get('template_id') if instance_data else None
        tpl = self.get_location_static(guild_id, template_id) # Get template

        if not tpl: print(f"LocationManager: Warning: No template found for location instance {location_id} (guild {guild_id}) on departure."); return

        triggers = tpl.get('on_exit_triggers')
        # Получаем RuleEngine и OnEnterActionExecutor из kwargs (контекста) или из __init__
        engine: Optional["RuleEngine"] = kwargs.get('rule_engine', self._rule_engine)
        on_enter_action_executor: Optional["OnEnterActionExecutor"] = kwargs.get('on_enter_action_executor', self._on_enter_action_executor) # Note: OnExit triggers likely use the same executor


        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers') and on_enter_action_executor and hasattr(on_enter_action_executor, 'execute_actions'):
            print(f"LocationManager: Executing {len(triggers)} OnExit triggers for {entity_type} {entity_id} from location {location_id} (guild {guild_id}).")
            try:
                 # Context for trigger evaluation and action execution
                trigger_context = {
                     **kwargs, # Pass all context
                     'location_instance_id': location_id, # Use instance ID
                     # Add entity/location specific details to context
                     'entity_id': entity_id, 'entity_type': entity_type,
                     'location_template_id': tpl.get('id'),
                     # Pass instance data *before* departure, if needed (careful if instance deleted)
                     'location_instance_data': instance_data, # Pass instance data if available
                     'location_template_data': tpl,
                 }
                 # Assuming execute_triggers finds/uses event context from kwargs.
                await engine.execute_triggers(triggers, context=trigger_context)
                print("LocationManager: OnExit triggers executed.")

            except Exception as e:
                print(f"LocationManager: ❌ Error executing OnExit triggers for {entity_type} {entity_id} from {location_id} (guild {guild_id}): {e}")
                traceback.print_exc()
        elif triggers:
            # Log warning if triggers defined but RuleEngine/Executor is missing
            missing = []
            if not engine: missing.append("RuleEngine")
            if not on_enter_action_executor: missing.append("OnEnterActionExecutor")
            print(f"LocationManager: Warning: OnExit triggers defined for location {location_id} (guild {guild_id}), but missing dependencies: {', '.join(missing)}.")
        else:
             print(f"LocationManager: No OnExit triggers defined for location {location_id} (guild {guild_id}).") # Log if no triggers defined


    # Добавляем метод process_tick для совместимости с PersistenceManager
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
         """Обработка игрового тика для локаций."""
         # Если у локаций есть состояние, которое меняется со временем (например, рост растений, движение NPC вне боя)
         # это место для обработки.
         print(f"LocationManager: Processing tick for guild {guild_id}. Delta: {game_time_delta}. (Placeholder)")

         # TODO: Implement tick logic if location state changes over time.
         # Example: Get all active location instances for this guild
         # guild_instances = self._location_instances.get(str(guild_id), {}).values()
         # managers_context = {**kwargs, 'location_manager': self, 'guild_id': guild_id, 'game_time_delta': game_time_delta}
         # for instance in guild_instances:
         #      if instance.get('is_active', False):
         #          # Update instance state based on game_time_delta and rules
         #          # e.g. handle resource regeneration, environmental effects
         #          # Possible: call a method in RuleEngine to handle tick logic for a location instance
         #          # rule_engine = managers_context.get('rule_engine')
         #          # if rule_engine and hasattr(rule_engine, 'process_location_tick'):
         #          #     await rule_engine.process_location_tick(instance, context=managers_context)
         #          # Check if instance state changed and mark dirty
         #          # self.mark_location_instance_dirty(guild_id, instance['id'])


    # Helper to get template considering per-guild storage
    # get_location_static now needs guild_id and template_id
    def get_location_static(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        """Получить статический шаблон локации по ID для данной гильдии."""
        # Assuming _location_templates is Dict[str, Dict[str, Dict[str, Any]]] = {guild_id: {tpl_id: data}}
        guild_templates = self._location_templates.get(str(guild_id), {})
        return guild_templates.get(str(template_id))

    # Helper to clear guild state cache (re-added from earlier version)
    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        # Удаляем все кеши для конкретной гильдии
        self._location_templates.pop(guild_id_str, None) # Если шаблоны per-guild
        self._location_instances.pop(guild_id_str, None)
        self._dirty_instances.pop(guild_id_str, None)
        self._deleted_instances.pop(guild_id_str, None)
        print(f"LocationManager: Cleared cache for guild {guild_id_str}.")

    # Убираем метод shutdown из LocationManager, он должен быть в GameManager
    # async def shutdown(self) -> None:
    #      ...