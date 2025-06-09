# bot/game/managers/location_manager.py

from __future__ import annotations
import json
from bot.game.models.party import Party
import traceback
import asyncio
# --- Необходимые импорты для runtime ---
import uuid # uuid нужен для генерации ID инстансов

# --- Базовые типы и TYPE_CHECKING ---
# Set и другие типы нужны для аннотаций
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins

# --- Imports needed ONLY for Type Checking ---
if TYPE_CHECKING:
    from bot.services.db_service import DBService # Changed
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
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator


# Define Callback Types
SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class LocationManager:
    """
    Менеджер для управления локациями игрового мира.
    Хранит статические шаблоны локаций и динамические инстансы (per-guild),
    обрабатывает триггеры OnEnter/OnExit.
    """
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]


    # --- Class-Level Attribute Annotations ---
    # Статические шаблоны локаций (глобальные)
    _location_templates: Dict[str, Dict[str, Any]] # {tpl_id: data}
    # Динамические инстансы (per-guild)
    _location_instances: Dict[str, Dict[str, Dict[str, Any]]] # {guild_id: {instance_id: data}}
    # Наборы "грязных" и удаленных инстансов (per-guild)
    _dirty_instances: Dict[str, Set[str]] # {guild_id: {instance_id, ...}}
    _deleted_instances: Dict[str, Set[str]] # {guild_id: {instance_id, ...}}


    def __init__(
        self,
        db_service: Optional["DBService"] = None, # Changed
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
        on_enter_action_executor: Optional["OnEnterActionExecutor"] = None,
        stage_description_generator: Optional["StageDescriptionGenerator"] = None,
    ):
        print("Initializing LocationManager...")
        self._db_service = db_service # Changed
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
        self._on_enter_action_executor = on_enter_action_executor
        self._stage_description_generator = stage_description_generator

        self._location_templates = {}
        self._location_instances = {}
        self._dirty_instances = {}
        self._deleted_instances = {}

        self._load_location_templates()
        print("LocationManager initialized.")

    def _load_location_templates(self):
        print("LocationManager: Loading global location templates...")
        self._location_templates = {} # Clear global template cache
        if self._settings and 'location_templates' in self._settings:
            templates_data = self._settings['location_templates']
            if isinstance(templates_data, dict):
                for template_id, data in templates_data.items():
                    if isinstance(data, dict): # Ensure data is a dict
                        data['id'] = str(template_id) # Ensure id is part of template data and is a string
                        # Ensure name_i18n and description_i18n are dicts
                        if not isinstance(data.get('name_i18n'), dict):
                            data['name_i18n'] = {"en": data.get('name', template_id), "ru": data.get('name', template_id)}
                        if not isinstance(data.get('description_i18n'), dict):
                            data['description_i18n'] = {"en": data.get('description', ""), "ru": data.get('description', "")}
                        self._location_templates[str(template_id)] = data
                    else:
                        print(f"LocationManager: Warning: Data for location template '{template_id}' is not a dictionary. Skipping.")
                print(f"LocationManager: Loaded {len(self._location_templates)} global location templates from settings.")
            else:
                print("LocationManager: 'location_templates' in settings is not a dictionary.")
        else:
            print("LocationManager: No 'location_templates' found in settings.")

    # --- Методы для PersistenceManager ---
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает ДИНАМИЧЕСКИЕ ИНСТАНСЫ локаций для гильдии. Шаблоны загружаются глобально."""
        guild_id_str = str(guild_id)
        print(f"LocationManager.load_state: Called for guild_id: {guild_id_str}")
        print(f"LocationManager: Loading state for guild {guild_id_str} (instances only)...")

        db_service = kwargs.get('db_service', self._db_service) # type: Optional["DBService"]
        if db_service is None or db_service.adapter is None:
             print(f"LocationManager: Database service or adapter is not available. Cannot load instances for guild {guild_id_str}.")
             # Clear only instance related caches for the guild
             self._location_instances.pop(guild_id_str, None)
             self._dirty_instances.pop(guild_id_str, None)
             self._deleted_instances.pop(guild_id_str, None)
             return

        # Clear relevant per-guild caches before loading
        self._location_instances[guild_id_str] = {}
        self._dirty_instances.pop(guild_id_str, None)
        self._deleted_instances.pop(guild_id_str, None)

        # Static templates are loaded globally in __init__, no need to load them here per guild.
        # guild_templates_cache: Dict[str, Dict[str, Any]] = self._location_templates.setdefault(guild_id_str, {}) # Removed

        # --- Загрузка динамических инстансов (per-guild) ---
        guild_instances_cache = self._location_instances[guild_id_str]
        # dirty_instances set and deleted_instances set for this guild were cleared by _clear_guild_state_cache

        loaded_instances_count = 0

        try:
            # Added descriptions_i18n to SELECT
            sql_instances = '''
            SELECT id, template_id, name_i18n, descriptions_i18n, exits, state_variables, is_active, guild_id, static_name, static_connections
            FROM locations WHERE guild_id = $1
            ''' # Changed
            print(f"LocationManager.load_state: Preparing to load instances from DB for guild {guild_id_str}. SQL query: {sql_instances}")
            rows_instances = await db_service.adapter.fetchall(sql_instances, (guild_id_str,)) # Changed
            print(f"LocationManager.load_state: Fetched {len(rows_instances) if rows_instances else 0} rows from DB for guild {guild_id_str}.")
            if rows_instances:
                 print(f"LocationManager: Found {len(rows_instances)} instances for guild {guild_id_str}.")

                 for row in rows_instances:
                      try:
                           print(f"LocationManager.load_state: Processing row: {dict(row) if row else 'Empty row'}")
                           print(f"LocationManager.load_state: Row data - id: {row['id']}, template_id: {row['template_id']}, descriptions_i18n: {row.get('descriptions_i18n')}")
                           instance_id_raw = row['id']
                           loaded_guild_id_raw = row['guild_id']

                           if instance_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                                print(f"LocationManager: Warning: Skipping instance row with invalid ID ('{instance_id_raw}') or mismatched guild_id ('{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row}.")
                                continue

                           instance_id = str(instance_id_raw)
                           template_id = str(row['template_id']) if row['template_id'] is not None else None

                           # name_i18n and descriptions_i18n are now directly selected
                           name_i18n_json = row['name_i18n']
                           descriptions_i18n_json = row['descriptions_i18n']

                           instance_name_i18n_dict = {}
                           if isinstance(name_i18n_json, str):
                               try: instance_name_i18n_dict = json.loads(name_i18n_json)
                               except json.JSONDecodeError: instance_name_i18n_dict = {"en": name_i18n_json} # Fallback
                           elif isinstance(name_i18n_json, dict): instance_name_i18n_dict = name_i18n_json

                           instance_descriptions_i18n_dict = {}
                           if isinstance(descriptions_i18n_json, str):
                               try: instance_descriptions_i18n_dict = json.loads(descriptions_i18n_json)
                               except json.JSONDecodeError: instance_descriptions_i18n_dict = {"en": descriptions_i18n_json} # Fallback
                           elif isinstance(descriptions_i18n_json, dict): instance_descriptions_i18n_dict = descriptions_i18n_json

                           instance_exits_json = row['exits']
                           instance_state_json_raw = row['state_variables']
                           is_active = row['is_active'] if 'is_active' in row.keys() else 0

                           instance_state_data = json.loads(instance_state_json_raw or '{}') if isinstance(instance_state_json_raw, (str, bytes)) else {}
                           if not isinstance(instance_state_data, dict):
                               instance_state_data = {}
                               print(f"LocationManager: Warning: State data for instance ID {instance_id} not a dict ({type(instance_state_data)}) for guild {guild_id_str}. Resetting.")

                           instance_exits = json.loads(instance_exits_json or '{}') if isinstance(instance_exits_json, (str, bytes)) else {}
                           if not isinstance(instance_exits, dict):
                               instance_exits = {}
                               print(f"LocationManager: Warning: Exits data for instance ID {instance_id} not a dict ({type(instance_exits)}) for guild {guild_id_str}. Resetting.")

                           # Prepare data for Location.from_dict or direct cache
                           instance_data_for_model: Dict[str, Any] = {
                               'id': instance_id,
                               'guild_id': guild_id_str,
                               'template_id': template_id,
                               'name_i18n': instance_name_i18n_dict,
                               'descriptions_i18n': instance_descriptions_i18n_dict,
                               'exits': instance_exits,
                               'state': instance_state_data,
                               'is_active': bool(is_active),
                               'static_name': row.get('static_name'),
                               'static_connections': row.get('static_connections')
                           }

                           from bot.game.models.location import Location # Local import
                           location_obj = Location.from_dict(instance_data_for_model)
                           print(f"LocationManager.load_state: Location object created from row data: {location_obj.id if location_obj else 'Failed to create Location obj'}. Added to guild_instances_cache.")
                           guild_instances_cache[location_obj.id] = location_obj.to_dict()

                           # Validation (template existence check can remain the same)
                           if template_id is not None:
                               if not self.get_location_static(template_id): # Removed guild_id_str
                                    print(f"LocationManager: Warning: Template '{template_id}' not found for instance '{instance_id}' in guild {guild_id_str} during load.")
                           else:
                                print(f"LocationManager: Warning: Instance ID {instance_id} missing template_id for guild {guild_id_str} during load.")
                                continue # Or handle as location without template

                           loaded_instances_count += 1

                      except json.JSONDecodeError:
                          print(f"LocationManager: Error decoding JSON for instance row (ID: {row.get('id', 'N/A')}, guild: {row.get('guild_id', 'N/A')}): {traceback.format_exc()}. Skipping instance row.");
                      except Exception as e:
                          print(f"LocationManager: Error processing instance row (ID: {row.get('id', 'N/A')}, guild: {row.get('guild_id', 'N/A')}): {e}. Skipping instance row."); traceback.print_exc();


                 print(f"LocationManager: Loaded {loaded_instances_count} instances for guild {guild_id_str}.")
            else: print(f"LocationManager: No instances found for guild {guild_id_str}.")

        except Exception as e:
            print(f"LocationManager: ❌ Error during DB instance load for guild {guild_id_str}: {e}"); traceback.print_exc();
            self._location_instances.pop(guild_id_str, None)
            self._dirty_instances.pop(guild_id_str, None)
            self._deleted_instances.pop(guild_id_str, None)
            raise

        print(f"LocationManager.load_state: Successfully loaded {loaded_instances_count} instances into cache for guild {guild_id_str}.")
        print(f"LocationManager: Load state complete for guild {guild_id_str}.")


    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет измененные/удаленные динамические инстансы локаций для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Saving state for guild {guild_id_str}...")

        db_service = kwargs.get('db_service', self._db_service) # type: Optional["DBService"] # Changed
        if db_service is None or db_service.adapter is None: # Changed
             print(f"LocationManager: Database service or adapter not available. Skipping save for guild {guild_id_str}.")
             return

        guild_instances_cache = self._location_instances.get(guild_id_str, {})
        dirty_instances_set = self._dirty_instances.get(guild_id_str, set()).copy()
        deleted_instances_set = self._deleted_instances.get(guild_id_str, set()).copy()


        if not dirty_instances_set and not deleted_instances_set:
            self._dirty_instances.pop(guild_id_str, None)
            self._deleted_instances.pop(guild_id_str, None)
            return

        print(f"LocationManager: Saving {len(dirty_instances_set)} dirty, {len(deleted_instances_set)} deleted instances for guild {guild_id_str}...")


        try:
            # Удалить помеченные для удаления инстансы для этого guild_id
            if deleted_instances_set:
                 ids_to_delete = list(deleted_instances_set)
                 if ids_to_delete: # Check if list is not empty
                    placeholders_del = ','.join([f'${i+2}' for i in range(len(ids_to_delete))]) # $2, $3, ...
                    sql_delete_batch = f"DELETE FROM locations WHERE guild_id = $1 AND id IN ({placeholders_del})" # Changed
                    await db_service.adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete))); # Changed
                    print(f"LocationManager: Deleted {len(ids_to_delete)} instances from DB for guild {guild_id_str}.")
                    self._deleted_instances.pop(guild_id_str, None)
                 else: # If set was empty for this guild
                    self._deleted_instances.pop(guild_id_str, None)


            # Обновить или вставить измененные инстансы для этого guild_id
            instances_to_upsert_list = [inst for id_key in list(dirty_instances_set) if (inst := guild_instances_cache.get(id_key)) is not None]

            if instances_to_upsert_list:
                 print(f"LocationManager: Upserting {len(instances_to_upsert_list)} instances for guild {guild_id_str}...")
                  # Use name_i18n and descriptions_i18n in SQL
                 upsert_sql = '''
                 INSERT INTO locations (
                      id, guild_id, template_id, name_i18n, descriptions_i18n,
                     exits, state_variables, is_active
                  ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                 ON CONFLICT (id) DO UPDATE SET
                    guild_id = EXCLUDED.guild_id,
                    template_id = EXCLUDED.template_id,
                     name_i18n = EXCLUDED.name_i18n,
                    descriptions_i18n = EXCLUDED.descriptions_i18n,
                    exits = EXCLUDED.exits,
                    state_variables = EXCLUDED.state_variables,
                    is_active = EXCLUDED.is_active
                 ''' # PostgreSQL UPSERT
                 data_to_upsert = []
                 upserted_instance_ids: Set[str] = set()

                 for instance_data_dict in instances_to_upsert_list: # instance_data_dict is a dict from cache
                      current_instance_description = "UNKNOWN_INSTANCE_IN_SAVE"
                      try:
                          instance_id = instance_data_dict.get('id')
                          instance_guild_id = instance_data_dict.get('guild_id')
                          current_instance_description = f"instance {instance_data_dict.get('id', 'N/A')} (guild {instance_data_dict.get('guild_id', 'N/A')})"

                          if instance_id is None or str(instance_guild_id) != guild_id_str:
                              print(f"LocationManager: Warning: Skipping upsert for instance with invalid ID ('{instance_id}') or mismatched guild ('{instance_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                              continue

                          template_id = instance_data_dict.get('template_id')

                          # Directly use name_i18n and descriptions_i18n from the instance data dict
                          name_i18n_dict = instance_data_dict.get('name_i18n', {})
                          instance_descriptions_i18n_dict = instance_data_dict.get('descriptions_i18n', {})

                          instance_exits = instance_data_dict.get('exits', {})
                          # 'state_variables' in DB, 'state' in model/cache dict
                          state_variables = instance_data_dict.get('state', instance_data_dict.get('state_variables', {}))
                          is_active = instance_data_dict.get('is_active', True)

                          if not isinstance(state_variables, dict):
                              print(f"LocationManager: Warning: Instance {instance_id} state_variables is not a dict ({type(state_variables)}) for guild {guild_id_str}. Saving as empty dict.")
                              state_variables = {}
                          if not isinstance(instance_exits, dict):
                              print(f"LocationManager: Warning: Instance {instance_id} exits is not a dict ({type(instance_exits)}) for guild {guild_id_str}. Saving as empty dict.")
                              instance_exits = {}
                          if not isinstance(instance_descriptions_i18n_dict, dict):
                              print(f"LocationManager: Warning: Instance {instance_id} descriptions_i18n is not a dict ({type(instance_descriptions_i18n_dict)}). Saving as empty dict.")
                              instance_descriptions_i18n_dict = {}


                          data_to_upsert.append((
                              str(instance_id), # id
                              guild_id_str,     # guild_id
                              str(template_id) if template_id is not None else None, # template_id
                               json.dumps(name_i18n_dict),               # name_i18n
                               json.dumps(instance_descriptions_i18n_dict), # descriptions_i18n
                              json.dumps(instance_exits),               # exits
                              json.dumps(state_variables),              # state_variables
                               bool(is_active)                           # is_active (boolean)
                           )); # 8 parameters
                          upserted_instance_ids.add(str(instance_id))

                      except Exception as e:
                          print(f"LocationManager: Error preparing data for {current_instance_description} for upsert: {e}"); traceback.print_exc();

                 if data_to_upsert:
                     try:
                         await db_service.adapter.execute_many(upsert_sql, data_to_upsert); # Changed
                         print(f"LocationManager: Successfully upserted {len(data_to_upsert)} instances for guild {guild_id_str}.")
                         if guild_id_str in self._dirty_instances:
                              self._dirty_instances[guild_id_str].difference_update(upserted_instance_ids)
                              if not self._dirty_instances[guild_id_str]:
                                   del self._dirty_instances[guild_id_str]

                     except Exception as e:
                          print(f"LocationManager: Error during batch upsert for guild {guild_id_str}: {e}"); traceback.print_exc();


        except Exception as e:
             print(f"LocationManager: ❌ Error during saving state for guild {guild_id_str}: {e}"); traceback.print_exc();


        print(f"LocationManager: Save state complete for guild {guild_id_str}.")


    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Rebuilding runtime caches for guild {guild_id_str}. (Placeholder)")

        print(f"LocationManager: Rebuild runtime caches complete for guild {guild_id_str}.")


    # --- Dynamic Instance Management ---
    async def create_location_instance(self, guild_id: str, template_id: str, initial_state: Optional[Dict[str, Any]] = None, instance_name: Optional[str] = None, instance_description: Optional[str] = None, instance_exits: Optional[Dict[str, str]] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
         """Создает динамический инстанс локации из шаблона для определенной гильдии."""
         ai_response_data = None
         source_data = None
         guild_id_str = str(guild_id)
         print(f"LocationManager: Creating instance for guild {guild_id_str} from template {template_id} in memory...")

         # guild_templates = self._location_templates.get(guild_id_str, {}) # Templates are global now
         template = self.get_location_static(str(template_id)) # Use global getter

         if not template:
             print(f"LocationManager: Error creating instance: Template '{template_id}' not found (globally).")
             return None
         # Name check can use template.get('name_i18n') or a plain 'name' as fallback
         template_name_i18n = template.get('name_i18n', {})
         if not template_name_i18n.get('en', template.get('name')): # Check English name or fallback plain name
             print(f"LocationManager: Warning: Template '{template_id}' missing 'name' or 'name_i18n.en'. Using template ID as name.")

         new_instance_id = str(uuid.uuid4())

         template_initial_state = template.get('initial_state', {})
         if not isinstance(template_initial_state, dict): template_initial_state = {}
         instance_state_data = dict(template_initial_state)
         if initial_state is not None:
             if isinstance(initial_state, dict): instance_state_data.update(initial_state)
             else: print(f"LocationManager: Warning: Provided initial_state is not a dict. Ignoring.")

         # Use i18n name from template if instance_name not provided
         default_name_i18n = template.get('name_i18n', {"en": str(template_id), "ru": str(template_id)})
         resolved_instance_name_i18n = instance_name if isinstance(instance_name, dict) else \
                                    ({"en": instance_name, "ru": instance_name} if instance_name else default_name_i18n)

         default_desc_i18n = template.get('description_i18n', {"en": "", "ru": ""})
         resolved_instance_description_i18n = instance_description if isinstance(instance_description, dict) else \
                                           ({"en": instance_description, "ru": instance_description} if instance_description else default_desc_i18n)

         resolved_instance_exits = instance_exits if instance_exits is not None else template.get('exits', {})
         if not isinstance(resolved_instance_exits, dict):
              print(f"LocationManager: Warning: Resolved instance exits is not a dict ({type(resolved_instance_exits)}). Using {{}}.")
              resolved_instance_exits = {}

         instance_for_cache: Dict[str, Any] = {
             'id': new_instance_id,
             'guild_id': guild_id_str,
             'template_id': str(template_id),
             'name_i18n': resolved_instance_name_i18n,
             'descriptions_i18n': resolved_instance_description_i18n,
             'exits': resolved_instance_exits,
             'state': instance_state_data,
             'is_active': True,
             # Ensure 'name' and 'description' are also set for compatibility if Location model uses them
             'name': resolved_instance_name_i18n.get('en', str(template_id)), # Fallback to English or ID
             'description': resolved_instance_description_i18n.get('en', '') # Fallback to English or empty
         }

         self._location_instances.setdefault(guild_id_str, {})[new_instance_id] = instance_for_cache
         self._dirty_instances.setdefault(guild_id_str, set()).add(new_instance_id)

         print(f"LocationManager: Instance {new_instance_id} created and added to cache and marked dirty for guild {guild_id_str}. Template: {template_id}, Name (en): '{instance_for_cache['name']}'.")

         return instance_for_cache

    def get_location_instance(self, guild_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
         """Получить динамический инстанс локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         print(f"LocationManager.get_location_instance: Called for guild_id: {guild_id_str}, instance_id: {instance_id}")
         guild_instances = self._location_instances.get(guild_id_str, {})
         print(f"LocationManager.get_location_instance: Instances cached for guild {guild_id_str}: {bool(guild_instances)}")
         instance_data = guild_instances.get(str(instance_id))
         print(f"LocationManager.get_location_instance: Instance data found in cache for {instance_id}: {bool(instance_data)}")
         if instance_data:
             print(f"LocationManager.get_location_instance: Keys in instance_data for {instance_id}: {list(instance_data.keys())}")
         else:
             print(f"LocationManager.get_location_instance: No instance data found in cache for {instance_id} under guild {guild_id_str}.")
         return instance_data


    async def delete_location_instance(self, guild_id: str, instance_id: str, **kwargs: Any) -> bool:
        """Пометить динамический инстанс локации для удаления для данной гильдии."""
        guild_id_str = str(guild_id)
        instance_id_str = str(instance_id)
        print(f"LocationManager: Marking instance {instance_id_str} for deletion for guild {guild_id_str}...")

        guild_instances_cache = self._location_instances.get(guild_id_str, {})
        instance_to_delete = guild_instances_cache.get(instance_id_str)

        if instance_to_delete:
             cleanup_context = {**kwargs, 'guild_id': guild_id_str, 'location_instance_id': instance_id_str, 'location_instance_data': instance_to_delete}
             await self.clean_up_location_contents(instance_id_str, **cleanup_context)

             del guild_instances_cache[instance_id_str]
             print(f"LocationManager: Removed instance {instance_id_str} from cache for guild {guild_id_str}.")

             self._deleted_instances.setdefault(guild_id_str, set()).add(instance_id_str)
             self._dirty_instances.get(guild_id_str, set()).discard(instance_id_str)

             print(f"LocationManager: Instance {instance_id_str} marked for deletion for guild {guild_id_str}.")
             return True
        print(f"LocationManager: Warning: Attempted to delete non-existent instance {instance_id_str} for guild {guild_id_str}.")
        return False


    async def clean_up_location_contents(self, location_instance_id: str, **kwargs: Any) -> None:
         """Очищает сущности и предметы, находящиеся в указанном инстансе локации, при удалении локации."""
         guild_id = kwargs.get('guild_id')
         if not guild_id: print("LocationManager: Warning: guild_id missing in context for clean_up_location_contents."); return
         guild_id_str = str(guild_id)
         print(f"LocationManager: Cleaning up contents of location instance {location_instance_id} in guild {guild_id_str}...")

         char_manager = kwargs.get('character_manager', self._character_manager)
         npc_manager = kwargs.get('npc_manager', self._npc_manager)
         item_manager = kwargs.get('item_manager', self._item_manager)
         party_manager = kwargs.get('party_manager', self._party_manager)
         event_manager = kwargs.get('event_manager', self._event_manager)


         cleanup_context = {**kwargs, 'location_instance_id': location_instance_id}

         if char_manager and hasattr(char_manager, 'get_characters_in_location') and hasattr(char_manager, 'remove_character'):
              characters_to_remove = char_manager.get_characters_in_location(guild_id_str, location_instance_id, **cleanup_context)
              print(f"LocationManager: Found {len(characters_to_remove)} characters in location {location_instance_id} for guild {guild_id_str}.")
              for char in list(characters_to_remove):
                   char_id = getattr(char, 'id', None)
                   if char_id:
                        try:
                             await char_manager.remove_character(char_id, guild_id_str, **cleanup_context)
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error removing character {char_id} from location {location_instance_id} for guild {guild_id_str}.");


         if npc_manager and hasattr(npc_manager, 'get_npcs_in_location') and hasattr(npc_manager, 'remove_npc'):
              npcs_to_remove = npc_manager.get_npcs_in_location(guild_id_str, location_instance_id, **cleanup_context)
              print(f"LocationManager: Found {len(npcs_to_remove)} NPCs in location {location_instance_id} for guild {guild_id_str}.")
              for npc in list(npcs_to_remove):
                   npc_id = getattr(npc, 'id', None)
                   if npc_id:
                        try:
                             await npc_manager.remove_npc(guild_id_str, npc_id, **cleanup_context)
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error removing NPC {npc_id} from location {location_instance_id} for guild {guild_id_str}.");


         if item_manager and hasattr(item_manager, 'remove_items_by_location'):
              try:
                   await item_manager.remove_items_by_location(location_instance_id, guild_id_str, **cleanup_context)
                   print(f"LocationManager: Removed items from location {location_instance_id} for guild {guild_id_str}.")
              except Exception: traceback.print_exc(); print(f"LocationManager: Error removing items from location {location_instance_id} for guild {guild_id_str}.");

         if event_manager and hasattr(event_manager, 'get_events_in_location') and hasattr(event_manager, 'cancel_event'):
              events_in_loc = event_manager.get_events_in_location(guild_id_str, location_instance_id, **cleanup_context)
              print(f"LocationManager: Found {len(events_in_loc)} events in location {location_instance_id} for guild {guild_id_str}.")
              for event in list(events_in_loc):
                   event_id = getattr(event, 'id', None)
                   if event_id:
                        try:
                             await event_manager.cancel_event(event_id, guild_id_str, **cleanup_context)
                             print(f"LocationManager: Cancelled event {event_id} in location {location_instance_id} for guild {guild_id_str}.")
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error cancelling event {event_id} in location {location_instance_id} for guild {guild_id_str}.");


         if party_manager and hasattr(party_manager, 'get_parties_in_location') and hasattr(party_manager, 'disband_party'):
              parties_in_loc = party_manager.get_parties_in_location(guild_id_str, location_instance_id, **cleanup_context)
              print(f"LocationManager: Found {len(parties_in_loc)} parties in location {location_instance_id} for guild {guild_id_str}.")
              for party in list(parties_in_loc):
                   party_id = getattr(party, 'id', None)
                   if party_id:
                        try:
                             await party_manager.disband_party(party_id, guild_id_str, **cleanup_context)
                             print(f"LocationManager: Disbanded party {party_id} in location {location_instance_id} for guild {guild_id_str}.")
                        except Exception: traceback.print_exc(); print(f"LocationManager: Error disbanding party {party_id} in location {location_instance_id} for guild {guild_id_str}.");


         print(f"LocationManager: Cleanup of contents complete for location instance {location_instance_id} in guild {guild_id_str}.")


    def get_location_name(self, guild_id: str, instance_id: str) -> Optional[str]:
         """Получить название инстанса локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         instance = self.get_location_instance(guild_id_str, instance_id)
         if instance:
             # Prefer name_i18n, then plain name, then template name
             name_i18n = instance.get('name_i18n', {})
             # Assuming a default language or a way to get it, e.g., 'en'
             lang_to_try = 'en' # Placeholder, ideally from context or settings
             instance_name = name_i18n.get(lang_to_try, instance.get('name'))

             if instance_name is not None:
                 return str(instance_name)

             template_id = instance.get('template_id')
             template = self.get_location_static(template_id) # Removed guild_id_str
             if template:
                 template_name_i18n = template.get('name_i18n', {})
                 template_name = template_name_i18n.get(lang_to_try, template.get('name'))
                 if template_name is not None:
                      return str(template_name)

         if isinstance(instance_id, str):
             return f"Unknown Location ({instance_id[:6]})"
         return None

    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]:
         """Получить связанные локации (выходы) для инстанса локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         instance = self.get_location_instance(guild_id_str, instance_id)
         if instance:
              instance_exits_data = instance.get('exits')
              if isinstance(instance_exits_data, dict): # Check if it's already a dict
                  return {str(k): str(v) for k, v in instance_exits_data.items()} # Ensure keys/values are strings
              # Fallback to template if instance exits are not a dict or missing

              template_id = instance.get('template_id')
              template = self.get_location_static(template_id) # Removed guild_id_str
              if template:
                  template_exits_data = template.get('exits', template.get('connected_locations')) # Check both keys
                  if isinstance(template_exits_data, dict):
                       return {str(k): str(v) for k, v in template_exits_data.items()}
                  if isinstance(template_exits_data, list): # Handle list format if present in template
                       return {str(loc_id): str(loc_id) for loc_id in template_exits_data if loc_id is not None}
                  if template_exits_data is not None: # If exists but not dict/list
                       print(f"LocationManager: Warning: Template {template_id} exits data is not a dict or list ({type(template_exits_data)}) for instance {instance_id} in guild {guild_id_str}. Returning {{}}.")


         return {}

    async def update_location_state(self, guild_id: str, instance_id: str, state_updates: Dict[str, Any], **kwargs: Any) -> bool:
        """Обновляет динамическое состояние инстанса локации для данной гильдии."""
        guild_id_str = str(guild_id)
        instance_data = self.get_location_instance(guild_id_str, instance_id)
        if instance_data:
            current_state = instance_data.setdefault('state', {})
            if not isinstance(current_state, dict):
                print(f"LocationManager: Warning: Instance {instance_data.get('id', 'N/A')} state is not a dict ({type(current_state)}) for guild {guild_id_str}. Resetting to {{}}.")
                current_state = {}
                instance_data['state'] = current_state

            if isinstance(state_updates, dict):
                 current_state.update(state_updates)
                 self._dirty_instances.setdefault(guild_id_str, set()).add(instance_data['id'])
                 print(f"LocationManager: Updated state for instance {instance_data['id']} for guild {guild_id_str}. Marked dirty.")
                 return True
            else:
                 print(f"LocationManager: Warning: state_updates is not a dict ({type(state_updates)}) for instance {instance_id} in guild {guild_id_str}. Ignoring update.")
                 return False


        print(f"LocationManager: Warning: Attempted to update state for non-existent instance {instance_id} for guild {guild_id_str}.")
        return False


    def get_location_channel(self, guild_id: str, instance_id: str) -> Optional[int]:
        """Получить ID канала для инстанса локации для данной гильдии."""
        guild_id_str = str(guild_id)
        instance = self.get_location_instance(guild_id_str, instance_id)
        if instance:
            template_id = instance.get('template_id')
            template = self.get_location_static(template_id) # Removed guild_id_str
            if template and template.get('channel_id') is not None:
                 channel_id_raw = template['channel_id']
                 try:
                      return int(channel_id_raw)
                 except (ValueError, TypeError):
                      print(f"LocationManager: Warning: Invalid channel_id '{channel_id_raw}' in template {template.get('id', 'N/A')} for instance {instance_id} in guild {guild_id_str}. Expected integer.");
                      return None
        return None

    def get_default_location_id(self, guild_id: str) -> Optional[str]:
        """Получить ID дефолтной начальной локации для данной гильдии."""
        guild_id_str = str(guild_id)
        guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
        default_id = guild_settings.get('default_start_location_id')
        if default_id is None:
             default_id = self._settings.get('default_start_location_id')

        if isinstance(default_id, (str, int)):
             default_id_str = str(default_id)
             if self.get_location_instance(guild_id_str, default_id_str):
                 print(f"LocationManager: Found default start location instance ID '{default_id_str}' in settings for guild {guild_id_str}.")
                 return default_id_str
             else:
                 print(f"LocationManager: Warning: Default start location instance ID '{default_id_str}' found in settings for guild {guild_id_str}, but no corresponding instance exists.")
                 return None

        print(f"LocationManager: Warning: Default start location setting ('default_start_location_id') not found or is invalid for guild {guild_id_str}.")
        return None

    async def move_entity(
        self,
        guild_id: str,
        entity_id: str,
        entity_type: str,
        from_location_id: Optional[str],
        to_location_id: str,
        **kwargs: Any,
    ) -> bool:
        """Универсальный метод для перемещения сущности (Character/NPC/Item/Party) между инстансами локаций для данной гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Attempting to move {entity_type} {entity_id} for guild {guild_id_str} from {from_location_id} to {to_location_id}.")

        target_instance = self.get_location_instance(guild_id_str, to_location_id)
        if not target_instance:
             print(f"LocationManager: Error: Target location instance '{to_location_id}' not found for guild {guild_id_str}. Cannot move {entity_type} {entity_id}.")
             send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
             channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
             if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Ошибка перемещения: Целевая локация `{to_location_id}` не найдена.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback for move failure: {cb_e}")
             return False

        mgr: Optional[Any] = None
        update_location_method_name: Optional[str] = None
        manager_attr_name: Optional[str] = None

        if entity_type == 'Character':
            mgr = kwargs.get('character_manager', self._character_manager)
            update_location_method_name = 'update_character_location'
            manager_attr_name = '_character_manager'
        elif entity_type == 'NPC':
            mgr = kwargs.get('npc_manager', self._npc_manager)
            update_location_method_name = 'update_npc_location'
            manager_attr_name = '_npc_manager'
        elif entity_type == 'Item':
             mgr = kwargs.get('item_manager', self._item_manager)
             update_location_method_name = 'update_item_location'
             manager_attr_name = '_item_manager'
        elif entity_type == 'Party':
            mgr = kwargs.get('party_manager', self._party_manager)
            update_location_method_name = 'update_party_location'
            manager_attr_name = '_party_manager'
        else:
            print(f"LocationManager: Error: Movement not supported for entity type {entity_type} for guild {guild_id_str}.")
            send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
            channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
            if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Ошибка перемещения: Перемещение сущностей типа `{entity_type}` не поддерживается.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")
            return False

        if not mgr or not hasattr(mgr, update_location_method_name):
            print(f"LocationManager: Error: No suitable manager ({manager_attr_name} or via kwargs) or update method ('{update_location_method_name}') found for entity type {entity_type} for guild {guild_id_str}.")
            send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
            channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
            if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Ошибка перемещения: Внутренняя ошибка сервера (не найден обработчик для {entity_type}).")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")

            return False

        movement_context: Dict[str, Any] = {
            **kwargs,
            'guild_id': guild_id_str,
            'entity_id': entity_id,
            'entity_type': entity_type,
            'from_location_instance_id': from_location_id,
            'to_location_instance_id': to_location_id,
            'location_manager': self,
        }
        critical_managers = {
            'rule_engine': self._rule_engine, 'event_manager': self._event_manager,
            'character_manager': self._character_manager, 'npc_manager': self._npc_manager,
            'item_manager': self._item_manager, 'combat_manager': self._combat_manager,
            'status_manager': self._status_manager, 'party_manager': self._party_manager,
            'time_manager': self._time_manager, 'send_callback_factory': self._send_callback_factory,
            'event_stage_processor': self._event_stage_processor, 'event_action_processor': self._event_action_processor,
            'on_enter_action_executor': self._on_enter_action_executor, 'stage_description_generator': self._stage_description_generator,
        }
        for mgr_name, mgr_instance in critical_managers.items():
             if mgr_instance is not None and mgr_name not in movement_context:
                  movement_context[mgr_name] = mgr_instance


        if from_location_id:
            from_instance_data = self.get_location_instance(guild_id_str, from_location_id)
            departure_context = {**movement_context, 'location_instance_data': from_instance_data}
            await self.handle_entity_departure(from_location_id, entity_id, entity_type, **departure_context)

        try:
            await getattr(mgr, update_location_method_name)(
                 entity_id,
                 to_location_id,
                 context=movement_context
            )
            print(f"LocationManager: Successfully updated location for {entity_type} {entity_id} to {to_location_id} for guild {guild_id_str} via {type(mgr).__name__}.")
            update_successful = True
        except Exception as e:
             print(f"LocationManager: ❌ Error updating location for {entity_type} {entity_id} to {to_location_id} for guild {guild_id_str} via {type(mgr).__name__}: {e}")
             traceback.print_exc()
             send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
             channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
             if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Произошла внутренняя ошибка при попытке обновить вашу локацию. Пожалуйста, сообщите об этом администратору.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")
             return False
        
        if entity_type == 'Party' and update_successful:
            party_manager = movement_context.get('party_manager') # Already used mgr above, which is party_manager in this case
            if party_manager:
                party = await party_manager.get_party(guild_id_str, entity_id)
                if party: # party is a Party object
                    character_manager = movement_context.get('character_manager')
                    if character_manager:
                        player_ids_list = getattr(party, 'player_ids_list', [])
                        for member_id in player_ids_list:
                            try:
                                await character_manager.update_character_location(
                                    character_id=member_id,
                                    location_id=to_location_id,
                                    guild_id=guild_id_str,
                                    context=movement_context
                                )
                                print(f"LocationManager: Successfully updated location for party member {member_id} to {to_location_id}.")
                            except Exception as char_update_e:
                                print(f"LocationManager: ❌ Error updating location for party member {member_id} to {to_location_id}: {char_update_e}")
                                traceback.print_exc() # Log error but continue with other members
                    else:
                        print(f"LocationManager: Warning: CharacterManager not found in movement_context. Cannot update party member locations.")
                else:
                    print(f"LocationManager: Warning: Party {entity_id} not found after move. Cannot update member locations.")
            else:
                print(f"LocationManager: Warning: PartyManager not found in movement_context. Cannot update party member locations.")


        target_instance_data = self.get_location_instance(guild_id_str, to_location_id) # Get target instance data AFTER entity is moved
        arrival_context = {**movement_context, 'location_instance_data': target_instance_data}
        await self.handle_entity_arrival(to_location_id, entity_id, entity_type, **arrival_context)

        print(f"LocationManager: Completed movement process for {entity_type} {entity_id} for guild {guild_id_str} to {to_location_id}.")
        return True

    async def handle_entity_arrival(
        self,
        location_id: str,
        entity_id: str,
        entity_type: str,
        **kwargs: Any,
    ) -> None:
        """Обработка триггеров при входе сущности в локацию (инстанс) для определенной гильдии."""
        guild_id = kwargs.get('guild_id')
        if not guild_id: print("LocationManager: Warning: guild_id missing in context for handle_entity_arrival."); return
        guild_id_str = str(guild_id)

        instance_data = kwargs.get('location_instance_data', self.get_location_instance(guild_id_str, location_id))

        template_id = instance_data.get('template_id') if instance_data else None
        tpl = self.get_location_static(template_id) # Removed guild_id_str

        if not tpl:
             print(f"LocationManager: Warning: No template found for location instance {location_id} (template ID: {template_id}, guild {guild_id_str}) on arrival of {entity_type} {entity_id}. Cannot execute triggers.")
             return

        triggers = tpl.get('on_enter_triggers')

        engine: Optional["RuleEngine"] = kwargs.get('rule_engine')
        if engine is None:
            engine = self._rule_engine

        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers'):
            print(f"LocationManager: Executing {len(triggers)} OnEnter triggers for {entity_type} {entity_id} in location {location_id} (guild {guild_id_str}).")
            try:
                trigger_context = {
                     **kwargs,
                     'location_instance_id': location_id,
                     'entity_id': entity_id, 'entity_type': entity_type,
                     'location_template_id': tpl.get('id'),
                     'location_instance_data': instance_data,
                     'location_template_data': tpl,
                 }
                await engine.execute_triggers(triggers, context=trigger_context)
                print(f"LocationManager: OnEnter triggers executed for {entity_type} {entity_id}.")

            except Exception as e:
                print(f"LocationManager: ❌ Error executing OnEnter triggers for {entity_type} {entity_id} in {location_id} (guild {guild_id_str}): {e}")
                traceback.print_exc()
        elif triggers:
             missing = []
             if not engine: missing.append("RuleEngine (injected or in context)")
             if missing:
                 print(f"LocationManager: Warning: OnEnter triggers defined for location {location_id} (guild {guild_id_str}), but missing dependencies: {', '.join(missing)}.")


    async def handle_entity_departure(
        self,
        location_id: str,
        entity_id: str,
        entity_type: str,
        **kwargs: Any,
    ) -> None:
        """Обработка триггеров при выходе сущности из локации (инстанс) для определенной гильдии."""
        guild_id = kwargs.get('guild_id')
        if not guild_id: print("LocationManager: Warning: guild_id missing in context for handle_entity_departure."); return
        guild_id_str = str(guild_id)

        instance_data = kwargs.get('location_instance_data', self.get_location_instance(guild_id_str, location_id))

        template_id_from_instance = instance_data.get('template_id') if instance_data else None
        # Use template_id from instance if available, otherwise from kwargs (less ideal but for robustness)
        final_template_id = template_id_from_instance if template_id_from_instance is not None else kwargs.get('location_template_id')

        tpl = self.get_location_static(final_template_id) # Removed guild_id_str

        if not tpl:
             print(f"LocationManager: Warning: No template found for location instance {location_id} (template ID: {final_template_id}, guild {guild_id_str}) on departure of {entity_type} {entity_id}. Cannot execute triggers.")
             return

        triggers = tpl.get('on_exit_triggers')

        engine: Optional["RuleEngine"] = kwargs.get('rule_engine')
        if engine is None: engine = self._rule_engine

        if isinstance(triggers, list) and engine and hasattr(engine, 'execute_triggers'):
            print(f"LocationManager: Executing {len(triggers)} OnExit triggers for {entity_type} {entity_id} from location {location_id} (guild {guild_id_str}).")
            try:
                 # --- Начало блока try (отступ 4 пробела от if) ---
                 trigger_context = {
                     **kwargs,
                     'location_instance_id': location_id,
                     'entity_id': entity_id, 'entity_type': entity_type,
                     'location_template_id': tpl.get('id'),
                     'location_instance_data': instance_data,
                     'location_template_data': tpl,
                 }
                 await engine.execute_triggers(triggers, context=trigger_context)
                 print(f"LocationManager: OnExit triggers executed for {entity_type} {entity_id}.")
            # --- Конец блока try ---
            except Exception as e: # <--- except должен быть на том же уровне отступа, что и try
                print(f"LocationManager: ❌ Error executing OnExit triggers for {entity_type} {entity_id} from {location_id} (guild {guild_id_str}): {e}")
                traceback.print_exc() # <--- print и traceback должны быть внутри except блока (отступ 4 пробела от except)
        # --- Конец блока if ---
        elif triggers:
            # ... остальная логика elif ...
            pass

    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
         """Обработка игрового тика для локаций для определенной гильдии."""
         guild_id_str = str(guild_id)

         rule_engine = kwargs.get('rule_engine', self._rule_engine)

         if rule_engine and hasattr(rule_engine, 'process_location_tick'):
             guild_instances = self._location_instances.get(guild_id_str, {}).values()
             managers_context = {
                 **kwargs,
                 'guild_id': guild_id_str,
                 'location_manager': self,
                 'game_time_delta': game_time_delta,
             }
             critical_managers = {
                 'item_manager': self._item_manager, 'status_manager': self._status_manager,
                 'character_manager': self._character_manager, 'npc_manager': self._npc_manager,
                 'party_manager': self._party_manager,
             }
             for mgr_name, mgr_instance in critical_managers.items():
                  if mgr_instance is not None and mgr_name not in managers_context:
                       managers_context[mgr_name] = mgr_instance

             for instance_data in list(guild_instances): # Iterate over a copy
                  instance_id = instance_data.get('id')
                  is_active = instance_data.get('is_active', False)

                  if instance_id and is_active:
                       try:
                            template_id = instance_data.get('template_id')
                            template = self.get_location_static(template_id) # Removed guild_id_str

                            if not template:
                                 print(f"LocationManager: Warning: Template not found for active instance {instance_id} (template ID: {template_id}) in guild {guild_id_str} during tick.")
                                 continue

                            await rule_engine.process_location_tick(
                                instance=instance_data,
                                template=template,
                                context=managers_context
                            )
                       except Exception as e:
                            print(f"LocationManager: ❌ Error processing tick for location instance {instance_id} in guild {guild_id_str}: {e}")
                            traceback.print_exc()
         elif rule_engine:
              print(f"LocationManager: Warning: RuleEngine injected/found, but 'process_location_tick' method not found for tick processing.")

    def get_location_static(self, template_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Получить глобальный статический шаблон локации по ID."""
        return self._location_templates.get(str(template_id)) if template_id is not None else None

    def _clear_guild_state_cache(self, guild_id: str) -> None:
        """Clears per-guild dynamic instance caches. Static templates are global and not cleared here."""
        guild_id_str = str(guild_id)
        # self._location_templates.pop(guild_id_str, None) # Templates are global now
        self._location_instances.pop(guild_id_str, None)
        self._dirty_instances.pop(guild_id_str, None)
        self._deleted_instances.pop(guild_id_str, None)
        print(f"LocationManager: Cleared cache for guild {guild_id_str}.")

    def mark_location_instance_dirty(self, guild_id: str, instance_id: str) -> None:
         """Помечает инстанс локации как измененный для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         instance_id_str = str(instance_id)
         if guild_id_str in self._location_instances and instance_id_str in self._location_instances[guild_id_str]:
              self._dirty_instances.setdefault(guild_id_str, set()).add(instance_id_str)

    def get_active_channel_ids_for_guild(self, guild_id: str) -> List[int]:
        """
        Retrieves a list of unique channel IDs for all active location instances in a given guild.
        """
        guild_id_str = str(guild_id)
        active_channel_ids: Set[int] = set()
        guild_instances = self._location_instances.get(guild_id_str, {})

        for instance_data in guild_instances.values():
            if instance_data.get('is_active'):
                template_id = instance_data.get('template_id')
                if not template_id:
                    continue

                template = self.get_location_static(template_id) # Removed guild_id_str
                if template:
                    channel_id_raw = template.get('channel_id')
                    if channel_id_raw is not None:
                        try:
                            active_channel_ids.add(int(channel_id_raw))
                        except (ValueError, TypeError):
                            print(f"LocationManager: Warning: Invalid channel_id '{channel_id_raw}' in template {template.get('id', 'N/A')} for guild {guild_id_str}.")

        return list(active_channel_ids)

    async def create_location_instance_from_moderated_data(self, guild_id: str, location_data: Dict[str, Any], user_id: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Creates a new location instance from moderated (AI-generated) data.
        Saves it to the database and marks it as generated.
        """
        from bot.game.models.location import Location  # Local import

        guild_id_str = str(guild_id)
        user_id_str = str(user_id) # Ensure user_id is string

        print(f"LocationManager: Creating location instance from moderated data for guild {guild_id_str} by user {user_id_str}.")

        if self._db_service is None or self._db_service.adapter is None:
            print("LocationManager: Error: DBService or adapter not available.")
            return None

        # Ensure location_data has an ID, or assign a new one.
        loc_id = location_data.get('id')
        if not loc_id:
            loc_id = str(uuid.uuid4())
            location_data['id'] = loc_id
            print(f"LocationManager: Assigned new ID {loc_id} to location from moderated data.")

        # Ensure guild_id is correctly set in the data for the model
        location_data['guild_id'] = guild_id_str

        # Ensure essential i18n fields and other JSON fields are at least empty dicts if not present
        # This is mostly handled by Location.from_dict now, but good to be explicit.
        i18n_fields = ['name_i18n', 'descriptions_i18n', 'details_i18n',
                       'tags_i18n', 'atmosphere_i18n', 'features_i18n']
        for field in i18n_fields:
            location_data.setdefault(field, {})

        json_fields_default_dict = ['exits', 'inventory', 'state_variables', 'static_connections']
        for field in json_fields_default_dict:
            location_data.setdefault(field, {})

        location_data.setdefault('is_active', True) # Default to active

        try:
            # Create Location object using the class method
            loc_obj = Location.from_dict(location_data)

            # Convert to dictionary for database operation
            location_dict_for_db = loc_obj.to_dict()

            # Save/update the location in the 'locations' table
            upsert_success = await self._db_service.adapter.upsert_location(location_dict_for_db)
            if not upsert_success:
                print(f"LocationManager: Failed to upsert location {loc_obj.id} to database.")
                return None

            print(f"LocationManager: Successfully upserted location {loc_obj.id} to database.")

            # Mark the location as AI-generated
            await self._db_service.adapter.add_generated_location(loc_obj.id, guild_id_str, user_id_str)
            print(f"LocationManager: Marked location {loc_obj.id} as generated by user {user_id_str}.")

            # Add to in-memory cache
            # The cache _location_instances stores dicts.
            self._location_instances.setdefault(guild_id_str, {})[loc_obj.id] = location_dict_for_db
            self.mark_location_instance_dirty(guild_id_str, loc_obj.id) # Mark as dirty to ensure it's persisted if save_state relies on dirty flags

            print(f"LocationManager: Location instance {loc_obj.id} created from moderated data and cached.")
            return location_dict_for_db

        except ValueError as ve: # Catch errors from Location.from_dict (e.g. missing id/guild_id)
            print(f"LocationManager: Error creating Location object from moderated data: {ve}")
            traceback.print_exc()
            return None
        except Exception as e:
            print(f"LocationManager: Error processing moderated location data for ID {location_data.get('id', 'N/A')}: {e}")
            traceback.print_exc()
            return None

# --- Конец класса LocationManager ---
