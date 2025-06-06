# bot/game/managers/location_manager.py

from __future__ import annotations
import json
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
    # Статические шаблоны локаций (теперь per-guild, соответствует предполагаемой схеме)
    _location_templates: Dict[str, Dict[str, Dict[str, Any]]] # {guild_id: {tpl_id: data}}
    # Динамические инстансы (per-guild)
    _location_instances: Dict[str, Dict[str, Dict[str, Any]]] # {guild_id: {instance_id: data}}
    # Наборы "грязных" и удаленных инстансов (per-guild)
    _dirty_instances: Dict[str, Set[str]] # {guild_id: {instance_id, ...}}
    _deleted_instances: Dict[str, Set[str]] # {guild_id: {instance_id, ...}}


    def __init__(
        self,
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
        on_enter_action_executor: Optional["OnEnterActionExecutor"] = None,
        stage_description_generator: Optional["StageDescriptionGenerator"] = None,
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
        self._on_enter_action_executor = on_enter_action_executor
        self._stage_description_generator = stage_description_generator

        self._location_templates = {}
        self._location_instances = {}
        self._dirty_instances = {}
        self._deleted_instances = {}

        print("LocationManager initialized.")

    # --- Методы для PersistenceManager ---
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает статические шаблоны локаций и динамические инстансы для гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Loading state for guild {guild_id_str} (static templates + instances)...")

        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"]
        if db_adapter is None:
             print(f"LocationManager: Database adapter is not available. Cannot load state for guild {guild_id_str}.")
             self._clear_guild_state_cache(guild_id_str)
             return # Let PM handle if critical

        self._clear_guild_state_cache(guild_id_str)

        guild_templates_cache: Dict[str, Dict[str, Any]] = self._location_templates.setdefault(guild_id_str, {})

        loaded_templates_count = 0
        try:
            # Corrected SQL query based on schema - template data is in 'properties' column
            # Using per-guild filter WHERE guild_id = ? as assumed for LocationManager
            sql_templates = "SELECT id, name, description, properties FROM location_templates WHERE guild_id = ?"
            # Passing guild_id parameter for fetchall on per-guild table
            rows_templates = await db_adapter.fetchall(sql_templates, (guild_id_str,))
            print(f"LocationManager: Found {len(rows_templates)} location template rows for guild {guild_id_str}.")
            for row in rows_templates:
                 tpl_id = row.get('id')
                 tpl_data_json = row.get('properties')
                 if tpl_id is None:
                      print(f"LocationManager: Warning: Skipping template row with missing ID for guild {guild_id_str}. Row: {row}.");
                      continue
                 try:
                      data: Dict[str, Any] = json.loads(tpl_data_json or '{}') if isinstance(tpl_data_json, (str, bytes)) else {}
                      if not isinstance(data, dict):
                           print(f"LocationManager: Warning: Template data for template '{tpl_id}' is not a dictionary ({type(data)}) for guild {guild_id_str}. Skipping.");
                           continue
                      data['id'] = str(tpl_id) # Ensure string ID
                      data.setdefault('name', row.get('name') if row.get('name') is not None else str(tpl_id))
                      data.setdefault('description', row.get('description') if row.get('description') is not None else "")
                      # Ensure exits/connected_locations are parsed correctly if they exist
                      exits = data.get('exits') or data.get('connected_locations')
                      if isinstance(exits, str):
                           try: exits = json.loads(exits)
                           except (json.JSONDecodeError, TypeError): exits = {}
                      if not isinstance(exits, dict): exits = {}
                      data['exits'] = exits
                      data.pop('connected_locations', None)

                      # Store in per-guild cache
                      guild_templates_cache[str(tpl_id)] = data
                      loaded_templates_count += 1
                 except json.JSONDecodeError:
                     print(f"LocationManager: Error decoding template '{tpl_id}' for guild {guild_id_str}: {traceback.format_exc()}. Skipping template row.");
                 except Exception as e:
                      print(f"LocationManager: Error processing template row '{tpl_id}' for guild {guild_id_str}: {e}. Skipping."); traceback.print_exc();


            print(f"LocationManager: Loaded {loaded_templates_count} templates for guild {guild_id_str} from DB.")


        except Exception as e:
            print(f"LocationManager: ❌ Error during DB template load for guild {guild_id_str}: {e}"); traceback.print_exc();
            self._location_templates.pop(guild_id_str, None)
            raise

        # --- Загрузка динамических инстансов (per-guild) ---
        guild_instances_cache = self._location_instances.setdefault(guild_id_str, {})
        # dirty_instances set and deleted_instances set for this guild were cleared by _clear_guild_state_cache

        loaded_instances_count = 0

        try:
            # Corrected column names based on schema
            sql_instances = '''
            SELECT id, template_id, name, description, exits, state_variables, is_active, guild_id FROM locations WHERE guild_id = ?
            '''
            rows_instances = await db_adapter.fetchall(sql_instances, (guild_id_str,))
            if rows_instances:
                 print(f"LocationManager: Found {len(rows_instances)} instances for guild {guild_id_str}.")

                 for row in rows_instances:
                      try:
                           instance_id_raw = row.get('id')
                           loaded_guild_id_raw = row.get('guild_id')

                           if instance_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                                print(f"LocationManager: Warning: Skipping instance row with invalid ID ('{instance_id_raw}') or mismatched guild_id ('{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row}.")
                                continue

                           instance_id = str(instance_id_raw)
                           template_id = str(row.get('template_id')) if row.get('template_id') is not None else None
                           instance_name = row.get('name')
                           instance_description = row.get('description')
                           instance_exits_json = row.get('exits')
                           instance_state_json_raw = row.get('state_variables')
                           is_active = row.get('is_active', 0)

                           instance_state_data = json.loads(instance_state_json_raw or '{}') if isinstance(instance_state_json_raw, (str, bytes)) else {}
                           if not isinstance(instance_state_data, dict):
                               instance_state_data = {}
                               print(f"LocationManager: Warning: State data for instance ID {instance_id} not a dict ({type(instance_state_data)}) for guild {guild_id_str}. Resetting.")

                           instance_exits = json.loads(instance_exits_json or '{}') if isinstance(instance_exits_json, (str, bytes)) else {}
                           if not isinstance(instance_exits, dict):
                               instance_exits = {}
                               print(f"LocationManager: Warning: Exits data for instance ID {instance_id} not a dict ({type(instance_exits)}) for guild {guild_id_str}. Resetting.")


                           instance_data: Dict[str, Any] = {
                               'id': instance_id,
                               'guild_id': guild_id_str,
                               'template_id': template_id,
                               'name': str(instance_name) if instance_name is not None else None,
                               'description': str(instance_description) if instance_description is not None else None,
                               'exits': instance_exits,
                               'state': instance_state_data,
                               'is_active': bool(is_active)
                           }

                           if instance_data.get('template_id') is not None:
                               template = self.get_location_static(guild_id_str, instance_data['template_id'])
                               if not template:
                                    print(f"LocationManager: Warning: Template '{instance_data['template_id']}' not found for instance '{instance_id}' in guild {guild_id_str} during load.")
                           else:
                                print(f"LocationManager: Warning: Instance ID {instance_id} missing template_id for guild {guild_id_str} during load.")
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
            self._location_instances.pop(guild_id_str, None)
            self._dirty_instances.pop(guild_id_str, None)
            self._deleted_instances.pop(guild_id_str, None)
            raise

        print(f"LocationManager: Load state complete for guild {guild_id_str}.")


    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет измененные/удаленные динамические инстансы локаций для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Saving state for guild {guild_id_str}...")

        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"]
        if db_adapter is None:
             print(f"LocationManager: Database adapter not available. Skipping save for guild {guild_id_str}.")
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
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 sql_delete_batch = f"DELETE FROM locations WHERE guild_id = ? AND id IN ({placeholders_del})"
                 await db_adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete)));
                 print(f"LocationManager: Deleted {len(ids_to_delete)} instances from DB for guild {guild_id_str}.")
                 self._deleted_instances.pop(guild_id_str, None)


            # Обновить или вставить измененные инстансы для этого guild_id
            instances_to_upsert_list = [ inst for id in list(dirty_instances_set) if (inst := guild_instances_cache.get(id)) is not None ]

            if instances_to_upsert_list:
                 print(f"LocationManager: Upserting {len(instances_to_upsert_list)} instances for guild {guild_id_str}...")
                 # Corrected column names based on schema
                 upsert_sql = ''' INSERT OR REPLACE INTO locations (id, guild_id, template_id, name, description, exits, state_variables, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?) '''
                 data_to_upsert = []
                 upserted_instance_ids: Set[str] = set()

                 for instance_data in instances_to_upsert_list:
                      try:
                          instance_id = instance_data.get('id')
                          instance_guild_id = instance_data.get('guild_id')

                          if instance_id is None or str(instance_guild_id) != guild_id_str:
                              print(f"LocationManager: Warning: Skipping upsert for instance with invalid ID ('{instance_id}') or mismatched guild ('{instance_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                              continue

                          template_id = instance_data.get('template_id')
                          instance_name = instance_data.get('name')
                          instance_description = instance_data.get('description')
                          instance_exits = instance_data.get('exits', {})
                          state_variables = instance_data.get('state', {})
                          is_active = instance_data.get('is_active', True)

                          if not isinstance(state_variables, dict):
                              print(f"LocationManager: Warning: Instance {instance_id} state_variables is not a dict ({type(state_variables)}) for guild {guild_id_str}. Saving as empty dict.")
                              state_variables = {}
                          if not isinstance(instance_exits, dict):
                              print(f"LocationManager: Warning: Instance {instance_id} exits is not a dict ({type(instance_exits)}) for guild {guild_id_str}. Saving as empty dict.")
                              instance_exits = {}


                          data_to_upsert.append((
                              str(instance_id),
                              guild_id_str,
                              str(template_id) if template_id is not None else None,
                              str(instance_name) if instance_name is not None else None,
                              str(instance_description) if instance_description is not None else None,
                              json.dumps(instance_exits),
                              json.dumps(state_variables),
                              int(bool(is_active)),
                          ));
                          upserted_instance_ids.add(str(instance_id))

                      except Exception as e:
                          print(f"LocationManager: Error preparing data for instance {instance_data.get('id', 'N/A')} (guild {instance_data.get('guild_id', 'N/A')}) for upsert: {e}"); traceback.print_exc();

                 if data_to_upsert:
                     try:
                         await db_adapter.execute_many(upsert_sql, data_to_upsert);
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
         guild_id_str = str(guild_id)
         print(f"LocationManager: Creating instance for guild {guild_id_str} from template {template_id} in memory...")

         guild_templates = self._location_templates.get(guild_id_str, {})
         template = guild_templates.get(str(template_id))

         if not template:
             print(f"LocationManager: Error creating instance: Template '{template_id}' not found for guild {guild_id_str}.")
             return None
         if not template.get('name'):
             print(f"LocationManager: Warning: Template '{template_id}' missing 'name' for guild {guild_id_str}. Using template ID as name.")

         new_instance_id = str(uuid.uuid4())

         template_initial_state = template.get('initial_state', {})
         if not isinstance(template_initial_state, dict): template_initial_state = {}
         instance_state_data = dict(template_initial_state)
         if initial_state is not None:
             if isinstance(initial_state, dict): instance_state_data.update(initial_state)
             else: print(f"LocationManager: Warning: Provided initial_state is not a dict. Ignoring.")

         resolved_instance_name = instance_name if instance_name is not None else template.get('name', str(template_id))
         resolved_instance_description = instance_description if instance_description is not None else template.get('description', "")
         resolved_instance_exits = instance_exits if instance_exits is not None else template.get('exits', {})
         if not isinstance(resolved_instance_exits, dict):
              print(f"LocationManager: Warning: Resolved instance exits is not a dict ({type(resolved_instance_exits)}). Using {{}}.")
              resolved_instance_exits = {}

         instance_for_cache: Dict[str, Any] = {
             'id': new_instance_id,
             'guild_id': guild_id_str,
             'template_id': str(template_id),
             'name': str(resolved_instance_name) if resolved_instance_name is not None else None,
             'description': str(resolved_instance_description) if resolved_instance_description is not None else None,
             'exits': resolved_instance_exits,
             'state': instance_state_data,
             'is_active': True,
         }

         self._location_instances.setdefault(guild_id_str, {})[new_instance_id] = instance_for_cache
         self._dirty_instances.setdefault(guild_id_str, set()).add(new_instance_id)

         print(f"LocationManager: Instance {new_instance_id} created and added to cache and marked dirty for guild {guild_id_str}. Template: {template_id}, Name: '{resolved_instance_name}'.")

         return instance_for_cache

    def get_location_instance(self, guild_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
         """Получить динамический инстанс локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         guild_instances = self._location_instances.get(guild_id_str, {})
         return guild_instances.get(str(instance_id))


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
             instance_name = instance.get('name')
             if instance_name is not None:
                 return str(instance_name)

             template_id = instance.get('template_id')
             template = self.get_location_static(guild_id_str, template_id)
             if template and template.get('name') is not None:
                  return str(template['name'])

         if isinstance(instance_id, str):
             return f"Unknown Location ({instance_id[:6]})"
         return None

    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]:
         """Получить связанные локации (выходы) для инстанса локации по ID для данной гильдии."""
         guild_id_str = str(guild_id)
         instance = self.get_location_instance(guild_id_str, instance_id)
         if instance:
              instance_exits = instance.get('exits')
              if instance_exits is not None:
                  if isinstance(instance_exits, dict):
                       return {str(k): str(v) for k, v in instance_exits.items()}
                  print(f"LocationManager: Warning: Instance {instance_id} exits data is not a dict ({type(instance_exits)}) for guild {guild_id_str}. Falling back to template exits.")


              template_id = instance.get('template_id')
              template = self.get_location_static(guild_id_str, template_id)
              if template:
                  template_exits = template.get('exits')
                  if template_exits is None:
                       template_exits = template.get('connected_locations')

                  if isinstance(template_exits, dict):
                       return {str(k): str(v) for k, v in template_exits.items()}
                  if isinstance(template_exits, list):
                       return {str(loc_id): str(loc_id) for loc_id in template_exits if loc_id is not None}
                  if template_exits is not None:
                       print(f"LocationManager: Warning: Template {template_id} exits data is not a dict or list ({type(template_exits)}) for instance {instance_id} in guild {guild_id_str}. Returning {{}}.")


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
            template = self.get_location_static(guild_id_str, template_id)
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
        # TODO: Add other entity types like 'Party'
        # elif entity_type == 'Party':
        #      mgr = kwargs.get('party_manager', self._party_manager)
        #      update_location_method_name = 'update_party_location'
        #      manager_attr_name = '_party_manager'
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
        except Exception as e:
             print(f"LocationManager: ❌ Error updating location for {entity_type} {entity_id} to {to_location_id} for guild {guild_id_str} via {type(mgr).__name__}: {e}")
             traceback.print_exc()
             send_cb_factory = kwargs.get('send_callback_factory', self._send_callback_factory)
             channel_id = kwargs.get('channel_id') or self.get_location_channel(guild_id_str, from_location_id or to_location_id)
             if send_cb_factory and channel_id is not None:
                 try: await send_cb_factory(channel_id)(f"❌ Произошла внутренняя ошибка при попытке обновить вашу локацию. Пожалуйста, сообщите об этом администратору.")
                 except Exception as cb_e: print(f"LocationManager: Error sending feedback: {cb_e}")
             return False

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
        tpl = self.get_location_static(guild_id_str, template_id)

        if not tpl:
             print(f"LocationManager: Warning: No template found for location instance {location_id} (guild {guild_id_str}) on arrival of {entity_type} {entity_id}. Cannot execute triggers.")
             return

        triggers = tpl.get('on_enter_triggers')

        engine: Optional["RuleEngine"] = kwargs.get('rule_engine')
        if engine is None: engine = self._rule_engine

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

        template_id = instance_data.get('template_id') if instance_data else None
        if template_id is None: template_id = kwargs.get('location_template_id')

        tpl = self.get_location_static(guild_id_str, template_id)

        if not tpl:
             print(f"LocationManager: Warning: No template found for location instance {location_id} (guild {guild_id_str}) on departure of {entity_type} {entity_id}. Cannot execute triggers.")
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
                       try: # <-- Corrected Indentation Start
                            template_id = instance_data.get('template_id')
                            template = self.get_location_static(guild_id_str, template_id)

                            if not template:
                                 print(f"LocationManager: Warning: Template not found for active instance {instance_id} in guild {guild_id_str} during tick.")
                                 continue

                            await rule_engine.process_location_tick(
                                instance=instance_data,
                                template=template,
                                context=managers_context
                            )

                       except Exception as e: # <-- Corrected Indentation (aligned with try)
                           print(f"LocationManager: ❌ Error processing tick for location instance {instance_id} in guild {guild_id_str}: {e}")
                           traceback.print_exc() # <-- Corrected Indentation (aligned with print above)

         elif rule_engine:
              print(f"LocationManager: Warning: RuleEngine injected/found, but 'process_location_tick' method not found for tick processing.")

    def get_location_static(self, guild_id: str, template_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Получить статический шаблон локации по ID для данной гильдии."""
        guild_id_str = str(guild_id)
        guild_templates = self._location_templates.get(guild_id_str, {})
        return guild_templates.get(str(template_id)) if template_id is not None else None

    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        self._location_templates.pop(guild_id_str, None)
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


# --- Конец класса LocationManager ---