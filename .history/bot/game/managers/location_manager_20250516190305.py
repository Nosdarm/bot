# bot/game/managers/location_manager.py

from __future__ import annotations
import json
import traceback
import asyncio
import uuid # Needed for generating UUIDs

from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING # Import TYPE_CHECKING


# --- Import Modules / Managers (attempt direct imports first) ---
# Use try/except for optional components or those potentially causing cycles if not needed for core functionality.
# Imports here are for runtime access if the class instance is created elsewhere or class is used for static methods/attributes.

try:
    from bot.database.sqlite_adapter import SqliteAdapter
except ImportError:
    SqliteAdapter = None # Handle if adapter is not available


# Direct Imports for fundamental Managers/Processors (if known not to cause cycles here).
# These classes might be needed for isinstance checks or direct references where string literals aren't sufficient or desired.
try:
    from bot.game.managers.character_manager import CharacterManager
except ImportError:
    CharacterManager = None
    print("LocationManager: CRITICAL: CharacterManager module not found. Startup likely to fail.")

try:
    from bot.game.managers.event_manager import EventManager
except ImportError:
    EventManager = None
    print("LocationManager: CRITICAL: EventManager module not found. Startup likely to fail.")

# Import THIS class for type hints or if needed. Implicitly available.

# Other Managers/Processors - use try/except, safer if they are optional or cause cycles.
# If a class instance from one of these is only ever accessed via injection/kwargs and
# used to call methods (not for isinstance/static checks in THIS file),
# their try/except import might be redundant if they are ONLY listed in TYPE_CHECKING.
# However, for robustness with varying levels of strictness in type checkers and Python versions,
# listing here *and* in TYPE_CHECKING is a common pattern, even if slightly redundant for analysis tools.
try:
    from bot.game.managers.npc_manager import NpcManager
except ImportError:
    NpcManager = None
    print("LocationManager: Warning: NpcManager module not found.")
try:
    from bot.game.managers.combat_manager import CombatManager
except ImportError:
    CombatManager = None
    print("LocationManager: Warning: CombatManager module not found.")
try:
    from bot.game.managers.item_manager import ItemManager
except ImportError:
    ItemManager = None
    print("LocationManager: Warning: ItemManager module not found.")
try:
    from bot.game.managers.time_manager import TimeManager
except ImportError:
    TimeManager = None
    print("LocationManager: Warning: TimeManager module not found.")
try:
    from bot.game.managers.status_manager import StatusManager
except ImportError:
    StatusManager = None
    print("LocationManager: Warning: StatusManager module not found.")
try:
    from bot.game.managers.party_manager import PartyManager
except ImportError:
    PartyManager = None
    print("LocationManager: Warning: PartyManager module not found.")
try:
    from bot.game.managers.economy_manager import EconomyManager
except ImportError:
    EconomyManager = None
    print("LocationManager: Warning: EconomyManager module not found.")
try:
    from bot.game.managers.crafting_manager import CraftingManager
except ImportError:
    CraftingManager = None
    print("LocationManager: Warning: CraftingManager module not found.")


# Processors - likely cycles, often preferred in TYPE_CHECKING only if only methods on instances are called.
# If using isinstance(obj, Class), need import here (even via try/except).
# Assuming minimal runtime checks for now.

# Re-add try/except imports for classes used for instanceof or constants at runtime if needed.
# If only method calls on injected instances, the TYPE_CHECKING import and string literal is enough.
# Let's keep try/except here for classes used for isinstance checks within LocationManager,
# even if their primary interaction is via injected instances.

try:
    from bot.game.rules.rule_engine import RuleEngine
except ImportError:
    RuleEngine = None
    print("LocationManager: Warning: RuleEngine module not found.") # Cycle risk
try:
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
except ImportError:
    OnEnterActionExecutor = None
    print("LocationManager: Warning: OnEnterActionExecutor module not found.") # Cycle risk
try:
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
except ImportError:
    StageDescriptionGenerator = None
    print("LocationManager: Warning: StageDescriptionGenerator module not found.") # Cycle risk

# Note: EventStageProcessor and EventActionProcessor also likely have cycles.


# --- Define Callback Types ---
SendToChannelCallback = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


# --- TYPE_CHECKING Imports ---
# List ALL classes that are injected/passed via kwargs and used as TYPE HINTS within THIS class methods.
# Use string literal convention ("ClassName") consistently here, even if they were directly imported above.
# This provides a uniform approach for static analysis hints regardless of import method or cycle risk.
if TYPE_CHECKING:
    # From bot.database
    from bot.database.sqlite_adapter import SqliteAdapter

    # From bot.game.rules
    from bot.game.rules.rule_engine import RuleEngine

    # From bot.game.managers
    # Use string literals here to match "ClassName" form used in Optional["ClassName"] type hints below.
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.character_manager import CharacterManager
    # from bot.game.managers.location_manager import LocationManager # Self-reference fine
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.crafting_manager import CraftingManager

    # From bot.game.event_processors
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
    # Add other injected/referenced classes

# --- Class Definition ---
class LocationManager:
    """
    Менеджер для управления локациями игрового мира для всех серверов.
    Хранит статические шаблоны локаций (загруженные из БД по Guild ID) и динамическое состояние экземпляров локаций (по Guild ID).
    """

    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]


    def __init__(
        self,
        # Use string literals for ALL injected dependencies for consistency with Pylance
        # and robustness with Optional types / ImportError.
        db_adapter: Optional["SqliteAdapter"] = None, # String literal for type hint - Ln 166 (approx)
        settings: Optional[Dict[str, Any]] = None,

        # Injected Managers/Processors - Use Optional and string literals for type hints.
        rule_engine: Optional["RuleEngine"] = None, # Ln 170 (approx)
        event_manager: Optional["EventManager"] = None, # Ln 171 (approx)
        send_callback_factory: Optional[SendCallbackFactory] = None, # Callable type - no string literal

        character_manager: Optional["CharacterManager"] = None, # Ln 174 (approx)
        npc_manager: Optional["NpcManager"] = None, # Ln 175 (approx)
        item_manager: Optional["ItemManager"] = None, # Ln 176 (approx)
        combat_manager: Optional["CombatManager"] = None, # Ln 177 (approx)
        status_manager: Optional["StatusManager"] = None, # Ln 178 (approx)
        party_manager: Optional["PartyManager"] = None, # Ln 179 (approx)
        time_manager: Optional["TimeManager"] = None, # Ln 180 (approx)

        event_stage_processor: Optional["EventStageProcessor"] = None, # Ln 185 (approx)
        event_action_processor: Optional["EventActionProcessor"] = None, # Ln 186 (approx)

        on_enter_action_executor: Optional["OnEnterActionExecutor"] = None,
        stage_description_generator: Optional["StageDescriptionGenerator"] = None,

        # TODO: Add other injected dependencies
    ):
        print("Initializing LocationManager...")

        # --- Validation of Mandatory Dependencies ---
        # Check if mandatory manager *classes* were successfully imported (are not None)
        # AND the passed argument is an instance (if class imported).
        # This catches config errors early if mandatory components are missing.
        if EventManager is None or (event_manager is not None and not isinstance(event_manager, EventManager)):
             raise TypeError("EventManager must be provided and be a valid instance if EventManager class imported.")
        if CharacterManager is None or (character_manager is not None and not isinstance(character_manager, CharacterManager)):
             raise TypeError("CharacterManager must be provided and be a valid instance if CharacterManager class imported.")
        if LocationManager is None:
             # This class itself didn't import. Fundamental problem.
             raise ImportError("LocationManager class itself failed to import.")


        # Store injected dependencies - Store the provided instances regardless of whether class imported or not.
        self._db_adapter = db_adapter # If SqliteAdapter class wasn't imported, GameManager should pass None or raise earlier based on your config.
        self._settings = settings

        self._rule_engine = rule_engine
        self._event_manager = event_manager
        self._send_callback_factory = send_callback_factory

        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._time_manager = time_manager

        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor

        self._on_enter_action_executor = on_enter_action_executor
        self._stage_description_generator = stage_description_generator
        # TODO: Store other injected dependencies

        # --- Location Cache (PER GUILD) ---
        self._location_templates: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._location_instances: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._dirty_instances: Dict[str, Set[str]] = {} # Needs correct List[str] type hint if [] - Corrected to Set[str]
        self._deleted_instances: Dict[str, Set[str]] = {}

        print("LocationManager initialized.\n")


    # --- Helper methods for guild-specific cache access ---
    def _get_guild_templates(self, guild_id: str) -> Dict[str, Dict[str, Any]]:
        return self._location_templates.setdefault(str(guild_id), {})

    def _get_guild_instances(self, guild_id: str) -> Dict[str, Dict[str, Any]]:
        return self._location_instances.setdefault(str(guild_id), {})

    def _get_guild_dirty_set(self, guild_id: str) -> Set[str]:
        return self._dirty_instances.setdefault(str(guild_id), set()) # Default value needs to be a Set

    def _get_guild_deleted_set(self, guild_id: str) -> Set[str]:
        return self._deleted_instances.setdefault(str(guild_id), set()) # Default value needs to be a Set

    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        self._location_templates.pop(guild_id_str, None)
        self._location_instances.pop(guild_id_str, None)
        self._dirty_instances.pop(guild_id_str, None)
        self._deleted_instances.pop(guild_id_str, None)
        print(f"LocationManager: Cleared cache for guild {guild_id_str}.")


    # --- Load Static Templates ---
    async def load_campaign_templates(self, guild_id: str, **kwargs) -> None:
        """Loads static location templates for a specific guild from the database or other sources."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Loading location templates for guild {guild_id_str} from DB/source...")

        # Get db_adapter from context or injected attribute
        # Use comment type hint for the variable pulled from kwargs
        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"] # <-- Corrected - Ln 267

        if db_adapter is None:
             print(f"LocationManager: Database adapter is not available. Cannot load location templates for guild {guild_id_str}.")
             raise ConnectionError("Database adapter is required for loading campaign templates.")

        self._location_templates.pop(guild_id_str, None)
        guild_templates_cache = self._get_guild_templates(guild_id_str)
        loaded_count = 0

        try:
            sql = "SELECT id, template_data FROM location_templates WHERE guild_id = ?"
            rows = await db_adapter.fetchall(sql, (guild_id_str,))
            print(f"LocationManager: Found {len(rows)} template rows for guild {guild_id_str}.")

            for row in rows:
                tpl_id = row.get('id')
                tpl_data_json = row.get('template_data')

                if not tpl_id:
                    print(f"Warning: Missing ID in template row for guild {guild_id_str}: {row}. Skipping.")
                    continue

                try:
                    data = json.loads(tpl_data_json or '{}')
                    if not isinstance(data, dict):
                        print(f"Warning: template_data for ID '{tpl_id}' is not a dictionary for guild {guild_id_str}. Skipping.")
                        continue
                    data.setdefault('template_id', tpl_id)
                    guild_templates_cache[tpl_id] = data
                    loaded_count += 1
                except json.JSONDecodeError:
                    print(f"Error decoding template '{tpl_id}' for guild {guild_id_str}: {traceback.format_exc()}. Skipping.")
                except Exception as e:
                    print(f"Error processing template '{tpl_id}' for guild {guild_id_str}: {e}")
                    traceback.print_exc()
                    print("Skipping.") # Added explicit print for clarity

            print(f"LocationManager: Loaded {loaded_count} templates for guild {guild_id_str} from DB.")
        except Exception as e:
            print(f"LocationManager: ❌ Error during DB template load for guild {guild_id_str}: {e}")
            traceback.print_exc()
            self._location_templates.pop(guild_id_str, None)
            raise


    def get_location_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
         return self._get_guild_templates(guild_id).get(str(template_id))


    # --- Dynamic Instance Management ---
    # Bodies restored without squeezing. Use comment type hints for vars from kwargs/defaults if needed.
    async def create_location_instance(self, guild_id: str, template_id: str, initial_state: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
         guild_id_str = str(guild_id)
         print(f"LocationManager: Creating instance for guild {guild_id_str} from template {template_id} in memory...")
         template = self.get_location_template(guild_id_str, template_id)
         if not template:
             print(f"Error creating instance: Template '{template_id}' not found for guild {guild_id_str}.")
             return None
         if not template.get('name'):
             print(f"Error creating instance: Template '{template_id}' missing 'name' for guild {guild_id_str}.")
             return None
         new_instance_id = str(uuid.uuid4())
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
         instance_for_cache = {'id': new_instance_id, 'guild_id': guild_id_str, 'template_id': template_id, 'state': instance_state_data, 'is_active': True,}
         self._get_guild_instances(guild_id_str)[new_instance_id] = instance_for_cache
         if self._db_adapter:
             self._get_guild_dirty_set(guild_id_str).add(new_instance_id)
         print(f"LocationManager: Instance {new_instance_id} added to cache and marked dirty (if DB enabled).")
         return instance_for_cache

    def get_location_instance(self, guild_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
         return self._get_guild_instances(guild_id).get(str(instance_id))

    async def delete_location_instance(self, guild_id: str, instance_id: str) -> bool:
        guild_id_str = str(guild_id)
        instance_id_str = str(instance_id)
        if instance_id_str in self._get_guild_instances(guild_id_str):
             del self._get_guild_instances(guild_id_str)[instance_id_str]
             self._get_guild_deleted_set(guild_id_str).add(instance_id_str)
             self._get_guild_dirty_set(guild_id_str).discard(instance_id_str) # Remove from dirty if there
             print(f"LocationManager: Instance {instance_id_str} marked for deletion.")
             return True
        print(f"LocationManager: Warning: Attempted to delete non-existent instance {instance_id_str} for guild {guild_id_str}.")
        return False

    def get_location_name(self, guild_id: str, instance_id: str) -> Optional[str]:
         instance = self.get_location_instance(guild_id, instance_id)
         if instance:
             template = self.get_location_template(guild_id, instance.get('template_id'))
         if instance and template and template.get('name'):
             return template.get('name')
         if instance and instance.get('id'):
             return f"Unnamed Location ({instance['id']})"
         if isinstance(instance_id, str):
             return f"Unknown Location ({instance_id})" # Fallback using requested ID
         return None


    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]:
         instance = self.get_location_instance(guild_id, instance_id)
         if instance:
             template = self.get_location_template(guild_id, instance.get('template_id'))
         if instance and template:
             connections = template.get('exits') or template.get('connected_locations')
             if isinstance(connections, dict):
                 return connections
             if isinstance(connections, list):
                 return {loc_id: loc_id for loc_id in connections}
         return {}

    async def update_location_state(self, guild_id: str, instance_id: str, state_updates: Dict[str, Any]) -> bool:
        guild_id_str = str(guild_id)
        instance_data = self.get_location_instance(guild_id_str, instance_id)
        if instance_data:
            current_state = instance_data.setdefault('state', {})
            if not isinstance(current_state, dict):
                current_state = {}
            current_state.update(state_updates)
            if self._db_adapter:
                self._get_guild_dirty_set(guild_id_str).add(instance_data['id'])
            print(f"LocationManager: Updated state for instance {instance_data['id']} for guild {guild_id_str}. Marked dirty (if DB enabled).")
            return True
        print(f"LocationManager: Warning: Attempted to update state for non-existent instance {instance_id}.")
        return False


    def get_location_channel(self, guild_id: str, instance_id: str) -> Optional[int]:
         instance = self.get_location_instance(guild_id, instance_id)
         if instance:
             template = self.get_location_template(guild_id, instance.get('template_id'))
         if instance and template and template.get('channel_id') is not None:
              try:
                  return int(template['channel_id'])
              except (ValueError, TypeError):
                  print(f"Warning: Invalid channel_id in template {template.get('template_id')} for instance {instance_id}.")
                  return None # Ensure None on failure
         return None


    def get_all_location_instances(self, guild_id: str) -> List[Dict[str, Any]]:
        return list(self._get_guild_instances(guild_id).values())

    def get_loaded_guild_ids(self) -> List[str]:
        return list(set(self._location_instances.keys()).union(self._location_templates.keys()))


    # --- Persistence Methods (Called by PersistenceManager) ---
    async def save_state(self, guild_id: str, **kwargs) -> None:
        guild_id_str = str(guild_id)
        print(f"LocationManager: Saving state for guild {guild_id_str}...")

        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"] # <-- Corrected - Ln 428 (approx)
        if db_adapter is None:
            print(f"Database adapter not available. Skipping save for guild {guild_id_str}.")
            return

        guild_instances_cache = self._get_guild_instances(guild_id_str)
        dirty_instances = self._get_guild_dirty_set(guild_id_str)
        deleted_instances = self._get_guild_deleted_set(guild_id_str)

        try:
            if deleted_instances:
                 placeholders_del = ','.join(['?'] * len(deleted_instances))
                 sql_delete_batch = f"DELETE FROM locations WHERE guild_id = ? AND id IN ({placeholders_del})"
                 await db_adapter.execute(sql_delete_batch, (guild_id_str, *list(deleted_instances)))
                 print(f"LocationManager: Deleted {len(deleted_instances)} instances for guild {guild_id_str}.")
                 deleted_instances.clear()

            # Collect instances to upsert, filtering out ones marked for deletion or not in cache (shouldn't happen but check)
            instances_to_upsert = [
                inst for id in dirty_instances
                if id not in deleted_instances and (inst := guild_instances_cache.get(id)) is not None
            ]

            if instances_to_upsert:
                 upsert_sql = ''' INSERT OR REPLACE INTO locations (id, guild_id, template_id, state_json, is_active) VALUES (?, ?, ?, ?, ?) '''
                 data_to_upsert = []
                 for instance_data in instances_to_upsert:
                      try:
                          # Ensure all required fields are present or default gracefully
                          instance_id = instance_data.get('id')
                          if not instance_id:
                              print(f"Warning: Instance data missing 'id' during upsert preparation. Skipping.")
                              continue # Skip this instance

                          data_to_upsert.append((
                              instance_id,
                              guild_id_str,
                              instance_data.get('template_id'), # Should exist if loaded from template
                              json.dumps(instance_data.get('state', {})),
                              int(instance_data.get('is_active', True)),
                          ))
                      except Exception as e:
                          print(f"Error preparing data for instance {instance_data.get('id', 'N/A')} for upsert: {e}")
                          traceback.print_exc()
                          # Decide if you want to re-raise or skip the problematic instance
                          # For now, let's re-raise to indicate a significant issue with data formatting
                          raise

                 if data_to_upsert:
                     await db_adapter.executemany(upsert_sql, data_to_upsert)
                     print(f"LocationManager: Upserted {len(data_to_upsert)} instances for guild {guild_id_str}.")
                     # Only clear dirty flags for instances that were successfully processed
                     # In this batch executemany, it's all or nothing usually, so clear all dirty
                     dirty_instances.clear()
            else:
                print(f"No dirty instances to save for guild {guild_id_str}.")
        except Exception as e:
            print(f"❌ Error during saving state for guild {guild_id_str}: {e}")
            traceback.print_exc()
            # Consider if you want to clear dirty/deleted here on failure or keep them
            # Keeping them allows retry, clearing might prevent infinite loop on persistent error
            # Let's keep them for now to allow potential retry
            raise

    async def load_state(self, **kwargs) -> None:
        db_adapter = kwargs.get('db_adapter', self._db_adapter) # type: Optional["SqliteAdapter"] # <-- Corrected - Ln 493 (approx)
        # guild_id_str = kwargs.get('guild_id') # type: Optional[str] # <-- 'str' is built-in, no need for string literal. This one should not cause the warning. Kept as is.

        guild_id_str = kwargs.get('guild_id')
        # Added explicit check based on potential issue if guild_id is not str
        if not isinstance(guild_id_str, str):
             print("Error: load_state called without a valid 'guild_id' (string). Cannot load per-guild data.")
             raise ValueError("LocationManager load_state requires 'guild_id' (string) in kwargs.")


        if db_adapter is None:
            print("Database adapter not available. Skipping load.")
            return
        # The check for guild_id_str is moved/refined slightly above


        print(f"LocationManager: Loading state for guild {guild_id_str}...")
        self._clear_guild_state_cache(guild_id_str)
        loaded_instances_count = 0

        try:
            # Load templates first as instances depend on them
            await self.load_campaign_templates(guild_id_str, db_adapter=db_adapter, **kwargs)

            sql_instances = ''' SELECT id, template_id, state_json, is_active FROM locations WHERE guild_id = ? '''
            rows_instances = await db_adapter.fetchall(sql_instances, (guild_id_str,))

            if rows_instances:
                 print(f"Found {len(rows_instances)} instances for guild {guild_id_str}.")
                 guild_instances_cache = self._get_guild_instances(guild_id_str)

                 for row in rows_instances:
                      try:
                           instance_id_raw = row.get('id')
                           if not instance_id_raw or not isinstance(instance_id_raw, str):
                               print(f"Warning: Invalid instance ID '{instance_id_raw}'. Skipping row.")
                               continue

                           state_json_raw = row.get('state_json')
                           # Handle potential None or empty string from DB gracefully
                           instance_state_data = json.loads(state_json_raw or '{}') if state_json_raw else {}
                           if not isinstance(instance_state_data, dict):
                               instance_state_data = {}
                               print(f"Warning: State data for instance ID {instance_id_raw} is not a dictionary. Resetting to empty dict.")

                           instance_data: Dict[str, Any] = {
                               'id': instance_id_raw,
                               'guild_id': guild_id_str,
                               'template_id': row.get('template_id'), # Should exist if saved properly
                               'state': instance_state_data,
                               'is_active': bool(row.get('is_active', 0)) # Ensure boolean
                           }

                           if not instance_data.get('template_id'):
                               print(f"Warning: Instance ID {instance_data.get('id', 'N/A')} missing template_id. Skipping load.")
                               continue # Skip instances without a template ID

                           guild_instances_cache[instance_data['id']] = instance_data
                           loaded_instances_count += 1

                      except json.JSONDecodeError:
                          print(f"Error decoding JSON for instance (ID: {row.get('id', 'N/A')}): {traceback.format_exc()}. Skipping.")
                      except Exception as e:
                          print(f"Error processing instance row (ID: {row.get('id', 'N/A')}): {e}")
                          traceback.print_exc()
                          print("Skipping.") # Added explicit print for clarity

                 print(f"Loaded {loaded_instances_count} instances for guild {guild_id_str}.")
            else:
                print(f"No instances found for guild {guild_id_str}.")

        except Exception as e:
            print(f"❌ Error during loading state for guild {guild_id_str}: {e}")
            traceback.print_exc()
            self._clear_guild_state_cache(guild_id_str) # Clear cache on load failure
            raise

    def rebuild_runtime_caches(self, guild_id: str, **kwargs) -> None:
         # Signature matches required interface. Implementation can add logic if needed.
         guild_id_str = str(guild_id)
         # Access other managers from kwargs here if needed to rebuild relationships.
         # e.g. char_mgr = kwargs.get('CharacterManager') # type: Optional["CharacterManager"] # Example comment hint
         print(f"LocationManager: Rebuilding runtime caches for guild {guild_id_str}.")
         pass # Add implementation here


    # --- Methods for Entity Movement (Called by Action Processors) ---
    async def move_entity( self, guild_id: str, entity_id: str, entity_type: str, from_location_id: Optional[str], to_location_id: str, **kwargs ) -> bool:
        # Use comment type hints for variables extracted from kwargs.
        combined_managers = {**kwargs} # Copy initial kwargs
        combined_managers['location_manager'] = self # Include self

        # Get injected managers, fallback to kwargs, using comment hints for variables
        re = self._rule_engine or kwargs.get('rule_engine') # type: Optional["RuleEngine"] # <-- Corrected - Ln 586 (approx)
        if re:
            combined_managers['rule_engine'] = re # Add if exists

        em = self._event_manager or kwargs.get('event_manager') # type: Optional["EventManager"] # <-- Corrected - Ln 590 (approx)
        if em:
            combined_managers['event_manager'] = em

        scb_factory = self._send_callback_factory or kwargs.get('send_callback_factory') # type: Optional[SendCallbackFactory] # Callable type - no string literal

        cm = self._character_manager or kwargs.get('character_manager') # type: Optional["CharacterManager"] # <-- Corrected - Ln 596 (approx)
        if cm:
            combined_managers['character_manager'] = cm

        # ... get other managers similarly ...
        # Example:
        nm = self._npc_manager or kwargs.get('npc_manager') # type: Optional["NpcManager"] # <-- Corrected - Ln 602 (approx)
        if nm:
            combined_managers['npc_manager'] = nm

        # Add other managers if needed in combined_managers context
        # For instance:
        im = self._item_manager or kwargs.get('item_manager') # type: Optional["ItemManager"] # <-- Corrected - Ln 608 (approx)
        if im: combined_managers['item_manager'] = im

        comb_mgr = self._combat_manager or kwargs.get('combat_manager') # type: Optional["CombatManager"] # <-- Corrected - Ln 611 (approx)
        if comb_mgr: combined_managers['combat_manager'] = comb_mgr

        sm = self._status_manager or kwargs.get('status_manager') # type: Optional["StatusManager"] # <-- Corrected - Ln 614 (approx)
        if sm: combined_managers['status_manager'] = sm

        pm = self._party_manager or kwargs.get('party_manager') # type: Optional["PartyManager"] # <-- Corrected - Ln 617 (approx)
        if pm: combined_managers['party_manager'] = pm

        tm = self._time_manager or kwargs.get('time_manager') # type: Optional["TimeManager"] # <-- Corrected - Ln 620 (approx)
        if tm: combined_managers['time_manager'] = tm

        # Add processors too
        esp = self._event_stage_processor or kwargs.get('event_stage_processor') # type: Optional["EventStageProcessor"] # <-- Corrected - Ln 631 (approx)
        if esp: combined_managers['event_stage_processor'] = esp

        eap = self._event_action_processor or kwargs.get('event_action_processor') # type: Optional["EventActionProcessor"] # <-- Corrected - Ln 634 (approx)
        if eap: combined_managers['event_action_processor'] = eap

        # Get OnEnterActionExecutor, fallback to kwargs
        oaea = self._on_enter_action_executor or kwargs.get('on_enter_action_executor') # type: Optional["OnEnterActionExecutor"]
        if oaea: combined_managers['on_enter_action_executor'] = oaea # Add if exists

        sdg = self._stage_description_generator or kwargs.get('stage_description_generator') # type: Optional["StageDescriptionGenerator"]
        if sdg: combined_managers['stage_description_generator'] = sdg # Add if exists


        print(f"LocationManager: Attempting to move {entity_type} ID {entity_id} from {from_location_id} to {to_location_id} for guild {guild_id}.")
        if self.get_location_instance(guild_id, to_location_id) is None:
            print(f"Error: Target instance {to_location_id} not found for guild {guild_id}.")
            return False

        # Handle departure triggers BEFORE updating location
        if from_location_id and oaea:
             await self.handle_entity_departure(guild_id, from_location_id, entity_id, entity_type, **combined_managers)

        # Update entity's location in the relevant manager
        # Attempt to get manager by inferred name + key name convention (refined)
        mgr_to_call_update = None
        update_method_name = None

        if entity_type == 'Character':
            mgr_to_call_update = combined_managers.get('character_manager')
            update_method_name = 'update_character_location' # Assume method name convention
        elif entity_type == 'NPC':
            mgr_to_call_update = combined_managers.get('npc_manager')
            update_method_name = 'update_npc_location' # Assume method name convention
        # Add other entity types as needed

        if mgr_to_call_update and update_method_name and hasattr(mgr_to_call_update, update_method_name):
            try:
                # Assuming update method exists and accepts guild_id, entity_id, new_location_id, context
                await getattr(mgr_to_call_update, update_method_name)(
                    str(guild_id),
                    entity_id,
                    to_location_id,
                    context=combined_managers
                )
            except Exception as e:
                print(f"❌ Error updating {entity_type} {entity_id} location: {e}")
                traceback.print_exc()
                raise # Re-raise the error if location update fails
        else:
            print(f"Error: No suitable manager or update method found for entity type '{entity_type}'. Movement not supported.")
            # Decide how to handle this - log error, raise exception, or return False
            # Raising NotImplementedError seems appropriate if the type is unexpected/unsupported
            raise NotImplementedError(f"Movement not implemented for entity type: {entity_type}")

        # Handle arrival triggers AFTER updating location
        if oaea:
            await self.handle_entity_arrival(guild_id, to_location_id, entity_id, entity_type, **combined_managers)

        print(f"LocationManager: Successfully moved {entity_type} {entity_id} to {to_location_id} for guild {guild_id}.")
        return True

    async def handle_entity_arrival( self, guild_id: str, location_instance_id: str, entity_id: str, entity_type: str, **kwargs ) -> None:
         loc_instance_data = self.get_location_instance(guild_id, location_instance_id)
         template_id = loc_instance_data.get('template_id') if loc_instance_data else None
         loc_template_data = self.get_location_template(guild_id, template_id) if template_id else None

         on_enter_triggers = loc_template_data.get('on_enter_triggers', []) if loc_template_data else []
         rule_engine = kwargs.get('rule_engine') # type: Optional["RuleEngine"] # <-- Corrected - Ln 698 (approx)

         if on_enter_triggers and rule_engine and hasattr(rule_engine, 'execute_triggers'):
              trigger_context = {
                  **kwargs, # Pass through all provided context
                  'guild_id': guild_id,
                  'entity_id': entity_id,
                  'entity_type': entity_type,
                  'location_instance_id': location_instance_id,
                  'location_template_id': template_id,
                  'location_instance_data': loc_instance_data,
                  'location_template_data': loc_template_data
              }
              await rule_engine.execute_triggers(guild_id, on_enter_triggers, context=trigger_context)

         send_cb_factory = kwargs.get('send_callback_factory') # type: Optional[SendCallbackFactory] # Callable - no string literal
         char_mgr = kwargs.get('character_manager') # type: Optional["CharacterManager"] # <-- Corrected - Ln 714 (approx)
         npc_mgr = kwargs.get('npc_manager') # type: Optional["NpcManager"] # <-- Corrected - Ln 715 (approx)

         if send_cb_factory:
              try:
                   # Get all entities (excluding the arriving one) to potentially notify them
                   all_entities_in_loc = []
                   # Add filtering by guild_id where needed in get_methods (assuming managers handle this)
                   if char_mgr and hasattr(char_mgr, 'get_characters_in_location'):
                       entities = await char_mgr.get_characters_in_location(guild_id, location_instance_id, context=kwargs)
                       if isinstance(entities,(list,tuple)):
                           all_entities_in_loc.extend(entities)

                   if npc_mgr and hasattr(npc_mgr, 'get_npcs_in_location'):
                       entities = await npc_mgr.get_npcs_in_location(guild_id, location_instance_id, context=kwargs)
                       if isinstance(entities,(list,tuple)):
                           all_entities_in_loc.extend(entities)

                   # Filter out the arriving entity itself
                   other_entities_in_loc = [ ent for ent in all_entities_in_loc if getattr(ent, 'id', None) != entity_id ]

                   if other_entities_in_loc:
                       # Get arriving entity obj requires calling manager; manager needs guild_id. Use kwargs context.
                       # Use conditional getting based on entity_type
                       arriving_entity_obj = None
                       if entity_type == 'Character' and char_mgr and hasattr(char_mgr, 'get_character'):
                            arriving_entity_obj = char_mgr.get_character(guild_id, entity_id)
                       elif entity_type == 'NPC' and npc_mgr and hasattr(npc_mgr, 'get_npc'):
                           arriving_entity_obj = npc_mgr.get_npc(guild_id, entity_id)
                       # Add other entity types

                       arriving_entity_name = getattr(arriving_entity_obj, 'name', entity_type) # Default to entity_type if name not found
                       location_name = self.get_location_name(guild_id, location_instance_id) or location_instance_id
                       arrival_message = f"{arriving_entity_name} прибывает в {location_name}."

                       loc_channel_id = self.get_location_channel(guild_id, location_instance_id)
                       if loc_channel_id is not None:
                            # Assuming send_callback_factory creates a callable `send`
                            await send_cb_factory(loc_channel_id)(arrival_message, None)

              except Exception as e:
                  print(f"Error during entity arrival notification: {e}")
                  traceback.print_exc()


    async def handle_entity_departure(self, guild_id: str, location_instance_id: str, entity_id: str, entity_type: str, **kwargs) -> None:
        # Similar structure, uses kwargs and type comments
         loc_instance_data = self.get_location_instance(guild_id, location_instance_id)
         template_id = loc_instance_data.get('template_id') if loc_instance_data else None
         loc_template_data = self.get_location_template(guild_id, template_id) if template_id else None

         on_exit_triggers = loc_template_data.get('on_exit_triggers', []) if loc_template_data else []
         rule_engine = kwargs.get('rule_engine') # type: Optional["RuleEngine"] # <-- Corrected - Ln 766 (approx)

         if on_exit_triggers and rule_engine and hasattr(rule_engine, 'execute_triggers'):
              trigger_context = {
                  **kwargs, # Pass through all provided context
                  'guild_id': guild_id,
                  'entity_id': entity_id,
                  'entity_type': entity_type,
                  'location_instance_id': location_instance_id,
                  'location_template_id': template_id,
                  'location_instance_data': loc_instance_data,
                  'location_template_data': loc_template_data
              } # Build context
              await rule_engine.execute_triggers(guild_id, on_exit_triggers, context=trigger_context)

         send_cb_factory = kwargs.get('send_callback_factory') # type: Optional[SendCallbackFactory] # Callable - no string literal
         char_mgr = kwargs.get('character_manager') # type: Optional["CharacterManager"] # <-- Corrected - Ln 782 (approx)
         npc_mgr = kwargs.get('npc_manager') # type: Optional["NpcManager"] # <-- Corrected - Ln 783 (approx)

         if send_cb_factory:
              try:
                   # Get all entities (excluding the departing one, although it might still be listed by the manager *before* its location is updated)
                   # For more accurate departure notification, you might get entities *before* location update
                   # or rely on the manager's get methods to reflect the *new* location state already.
                   # The current logic gets entities *in the old location*, which seems correct for a departure message.
                   all_entities_in_loc = []
                   if char_mgr and hasattr(char_mgr, 'get_characters_in_location'):
                       entities = await char_mgr.get_characters_in_location(guild_id, location_instance_id, context=kwargs)
                       if isinstance(entities,(list,tuple)):
                           all_entities_in_loc.extend(entities)

                   if npc_mgr and hasattr(npc_mgr, 'get_npcs_in_location'):
                       entities = await npc_mgr.get_npcs_in_location(guild_id, location_instance_id, context=kwargs)
                       if isinstance(entities,(list,tuple)):
                           all_entities_in_loc.extend(entities)

                   # Filter out the departing entity itself (if it's still listed)
                   remaining_entities_in_loc = [ ent for ent in all_entities_in_loc if getattr(ent, 'id', None) != entity_id ]

                   if remaining_entities_in_loc:
                       # Get departing entity obj requires calling manager; manager needs guild_id. Use kwargs context.
                       # Use conditional getting based on entity_type
                       departing_entity_obj = None
                       if entity_type == 'Character' and char_mgr and hasattr(char_mgr, 'get_character'):
                            departing_entity_obj = char_mgr.get_character(guild_id, entity_id)
                       elif entity_type == 'NPC' and npc_mgr and hasattr(npc_mgr, 'get_npc'):
                           departing_entity_obj = npc_mgr.get_npc(guild_id, entity_id)
                       # Add other entity types

                       departing_entity_name = getattr(departing_entity_obj, 'name', entity_type) # Default to entity_type if name not found
                       location_name = self.get_location_name(guild_id, location_instance_id) or location_instance_id
                       departure_message = f"{departing_entity_name} покидает {location_name}."

                       loc_channel_id = self.get_location_channel(guild_id, location_instance_id)
                       if loc_channel_id is not None:
                           # Assuming send_callback_factory creates a callable `send`
                           await send_cb_factory(loc_channel_id)(departure_message, None)

              except Exception as e:
                  print(f"Error during entity departure notification: {e}")
                  traceback.print_exc()

    # TODO: Implement Process Tick
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs) -> None:
        # Uses managers from kwargs, use comment syntax for annotation.
        time_manager = kwargs.get('time_manager') # type: Optional["TimeManager"] # <-- Corrected - Ln 831 (approx)
        rule_engine = kwargs.get('rule_engine') # type: Optional["RuleEngine"] # <-- Corrected - Ln 832 (approx)
        # ... get other managers using type comments and apply string literal ...
        # e.g. combat_manager = kwargs.get('combat_manager') # type: Optional["CombatManager"]


        # ... (your process_tick logic) ...
        pass # Placeholder with correct signature


# End of LocationManager class