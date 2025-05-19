# bot/game/managers/location_manager.py (ИСПРАВЛЕННАЯ ВЕРСИЯ ДЛЯ КРУГОВОГО ИМПОРТА И СИГНАТУР ПЕРСИСТЕНТНОСТИ)

from __future__ import annotations
import json
import traceback
import asyncio
import uuid # Needed for generating UUIDs

from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING # Import TYPE_CHECKING

# --- Import Modules / Managers (attempt direct imports first) ---
# Handle cases where modules might not exist (optional components)
# Imports here are for runtime access if the class instance is created elsewhere
# or if the class itself is used for static methods/attributes.

try:
    from bot.database.sqlite_adapter import SqliteAdapter
except ImportError:
    SqliteAdapter = None # Handle if adapter is not available
    print("LocationManager: Warning: SqliteAdapter module not found. Database persistence functions will be limited.")


# Direct Imports for Managers known NOT to create direct cycles with LocationManager at top level
# These are also typically mandatory managers or very fundamental ones.
# Use try/except for safety even for mandatory ones, although missing mandatory implies a larger config issue.
try:
    from bot.game.managers.character_manager import CharacterManager
except ImportError:
    CharacterManager = None # If mandatory import fails, indicate criticality.
    print("LocationManager: CRITICAL: CharacterManager module not found during import. Startup likely to fail.")

try:
    from bot.game.managers.event_manager import EventManager
except ImportError:
    EventManager = None
    print("LocationManager: CRITICAL: EventManager module not found during import. Startup likely to fail.")


# Imports for other optional Managers, often safer with try/except if they are optional or cause cycles
# or used via injected instances primarily.
# Use try/except to allow bot to run without these if optional.
try:
    from bot.game.managers.npc_manager import NpcManager
except ImportError:
    NpcManager = None
    print("LocationManager: Warning: NpcManager module not found, skipping import.")

try:
    from bot.game.managers.combat_manager import CombatManager
except ImportError:
    CombatManager = None
    print("LocationManager: Warning: CombatManager module not found, skipping import.")

try:
    from bot.game.managers.item_manager import ItemManager
except ImportError:
    ItemManager = None
    print("LocationManager: Warning: ItemManager module not found, skipping import.")

try:
    from bot.game.managers.time_manager import TimeManager
except ImportError:
    TimeManager = None
    print("LocationManager: Warning: TimeManager module not found, skipping import.")

try:
    from bot.game.managers.status_manager import StatusManager
except ImportError:
    StatusManager = None
    print("LocationManager: Warning: StatusManager module not found, skipping import.")

try:
    from bot.game.managers.party_manager import PartyManager
except ImportError:
    PartyManager = None
    print("LocationManager: Warning: PartyManager module not found, skipping import.")

# Include other optional managers with try/except
try:
    from bot.game.managers.economy_manager import EconomyManager
except ImportError:
    EconomyManager = None
    print("LocationManager: Warning: EconomyManager module not found, skipping import.")

try:
    from bot.game.managers.crafting_manager import CraftingManager
except ImportError:
    CraftingManager = None
    print("LocationManager: Warning: CraftingManager module not found, skipping import.")


# Imports for Processors potentially involved in cycles, safer in TYPE_CHECKING and accessed via instance attributes.
try:
    # Although imported directly here for potential instance checks or constants,
    # rely on string literals in annotations and passing instances.
    from bot.game.rules.rule_engine import RuleEngine # RuleEngine has cycle with LM/processors
except ImportError:
    RuleEngine = None
    print("LocationManager: Warning: RuleEngine module not found, skipping import.") # Note: If RE is truly optional or will raise later if missing


# Other processors might be involved in cycles. Import with try/except for safety.
try:
     from bot.game.event_processors.event_stage_processor import EventStageProcessor # Likely cycles
except ImportError:
     EventStageProcessor = None
     print("LocationManager: Warning: EventStageProcessor module not found, skipping import.")

try:
     from bot.game.event_processors.event_action_processor import EventActionProcessor # Likely cycles
except ImportError:
     EventActionProcessor = None
     print("LocationManager: Warning: EventActionProcessor module not found, skipping import.")


# Other Action Executors / Description Generators might depend on managers and cause cycles.
# Import with try/except if instance methods are called at runtime and they were injected.
# Otherwise put in TYPE_CHECKING only. Assuming they are injected.
try:
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
except ImportError:
    OnEnterActionExecutor = None
    print("LocationManager: Warning: OnEnterActionExecutor module not found, skipping import.")

try:
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
except ImportError:
    StageDescriptionGenerator = None
    print("LocationManager: Warning: StageDescriptionGenerator module not found, skipping import.")


# --- Define Callback Types ---
SendToChannelCallback = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


# --- TYPE_CHECKING Imports ---
# List ALL classes that are injected/passed via kwargs and used in type hints within this class (LocationManager),
# to provide correct static analysis hints.
# Use string literal convention ("ClassName") consistently here for safety and uniform Pylance analysis.
if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter

    from bot.game.rules.rule_engine import RuleEngine

    # Use string literals here to match their use as string literals in __init__ annotation.
    # Even if the class is imported directly above, using the string literal form
    # in TYPE_CHECKING block and corresponding annotation helps consistency and can sometimes
    # avoid subtle static analysis issues if the class above might resolve to None.
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.location_manager import LocationManager # Self-reference is fine
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.crafting_manager import CraftingManager

    # Processors referenced by type hint and injected
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
    Обрабатывает триггеры OnEnter/OnExit. Инжектирует другие менеджеры/процессоры.
    """
    def __init__(
        self,
        # Use string literals for all injected managers/dependencies consistently for Pylance.
        # Their *runtime* existence will be checked via 'if self._manager is not None:'
        # db_adapter is a dependency provided from outside (GameManager). Use string literal for type.
        db_adapter: Optional["SqliteAdapter"] = None, # Pylance OK with Optional["StrLit"]=None
        settings: Optional[Dict[str, Any]] = None,

        # Injected Managers/Processors - Use string literals for type hints
        rule_engine: Optional["RuleEngine"] = None,
        event_manager: Optional["EventManager"] = None,
        send_callback_factory: Optional[SendCallbackFactory] = None, # Callable type - no string literal

        character_manager: Optional["CharacterManager"] = None, # String literal
        npc_manager: Optional["NpcManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        time_manager: Optional["TimeManager"] = None,

        event_stage_processor: Optional["EventStageProcessor"] = None,
        event_action_processor: Optional["EventActionProcessor"] = None,

        on_enter_action_executor: Optional["OnEnterActionExecutor"] = None,
        stage_description_generator: Optional["StageDescriptionGenerator"] = None,

        # TODO: Add other injected dependencies
    ):
        print("Initializing LocationManager...")

        # --- Store Injected Dependencies ---
        # No type checks here, rely on annotations in signature and GameManager's checks.
        self._db_adapter = db_adapter
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
        self._dirty_instances: Dict[str, Set[str]] = {}
        self._deleted_instances: Dict[str, Set[str]] = {}

        print("LocationManager initialized.\n")

    # --- Helper methods for guild-specific cache access ---
    # Implementation bodies restored
    def _get_guild_templates(self, guild_id: str) -> Dict[str, Dict[str, Any]]: return self._location_templates.setdefault(str(guild_id), {})
    def _get_guild_instances(self, guild_id: str) -> Dict[str, Dict[str, Any]]: return self._location_instances.setdefault(str(guild_id), {})
    def _get_guild_dirty_set(self, guild_id: str) -> Set[str]: return self._dirty_instances.setdefault(str(guild_id), set())
    def _get_guild_deleted_set(self, guild_id: str) -> Set[str]: return self._deleted_instances.setdefault(str(guild_id), set())
    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        self._location_templates.pop(guild_id_str, None)
        self._location_instances.pop(guild_id_str, None)
        self._dirty_instances.pop(guild_id_str, None)
        self._deleted_instances.pop(guild_id_str, None)
        print(f"LocationManager: Cleared cache for guild {guild_id_str}.")


    # --- Load Static Templates ---
    # Load templates needs guild_id and db_adapter access. Accept kwargs.
    async def load_campaign_templates(self, guild_id: str, **kwargs) -> None:
        """Loads static location templates for a specific guild from the database or other sources."""
        guild_id_str = str(guild_id)
        print(f"LocationManager: Loading location templates for guild {guild_id_str} from DB/source...")

        # Get db_adapter from context or injected attribute
        db_adapter = kwargs.get('db_adapter', self._db_adapter)

        if db_adapter is None:
             print(f"LocationManager: Database adapter is not available. Cannot load location templates for guild {guild_id_str}.")
             raise ConnectionError("Database adapter is required for loading campaign templates.")

        # Clear existing templates for this guild before loading new ones
        self._location_templates.pop(guild_id_str, None)
        guild_templates_cache = self._get_guild_templates(guild_id_str)
        loaded_count = 0

        try:
            sql = "SELECT id, template_data FROM location_templates WHERE guild_id = ?"
            rows = await db_adapter.fetchall(sql, (guild_id_str,)) # Use db_adapter from kwargs/self
            print(f"LocationManager: Found {len(rows)} location template rows in DB for guild {guild_id_str}.")

            for row in rows:
                tpl_id = row.get('id')
                tpl_data_json = row.get('template_data')

                if not tpl_id:
                    print(f"LocationManager: Warning: Row with missing ID found during template load for guild {guild_id_str}: {row}. Skipping.")
                    continue

                try:
                    data = json.loads(tpl_data_json or '{}')
                    if not isinstance(data, dict):
                        print(f"LocationManager: Warning: template_data for ID '{tpl_id}' for guild {guild_id_str} is not a dictionary ({type(data)}). Skipping template.")
                        continue

                    data.setdefault('template_id', tpl_id)
                    guild_templates_cache[tpl_id] = data
                    loaded_count += 1

                except json.JSONDecodeError:
                    print(f"LocationManager: ❌ JSON decoding error for template '{tpl_id}' for guild {guild_id_str}: {traceback.format_exc()}. Skipping template.")
                except Exception as e:
                    print(f"LocationManager: Error processing template '{tpl_id}' for guild {guild_id_str}: {e}. Skipping template.")
                    traceback.print_exc()

            print(f"LocationManager: Successfully loaded {loaded_count} location templates into cache for guild {guild_id_str} from DB.")

        except Exception as e:
            print(f"LocationManager: ❌ Error during DB template load for guild {guild_id_str}: {e}")
            traceback.print_exc()
            self._location_templates.pop(guild_id_str, None)
            raise # Critical failure


    def get_location_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
         # Implementation remains as before.
         return self._get_guild_templates(guild_id).get(str(template_id)) # Ensure template_id is string key


    # --- Dynamic Instance Management ---
    # Bodies restored
    async def create_location_instance(self, guild_id: str, template_id: str, initial_state: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
         guild_id_str = str(guild_id)
         print(f"LocationManager: Creating location instance for guild {guild_id_str} from template {template_id} in memory...")

         template = self.get_location_template(guild_id_str, template_id)
         if not template:
             print(f"LocationManager: Error creating instance: Template '{template_id}' not found for guild {guild_id_str}. Make sure templates are loaded.")
             return None

         if not template.get('name'):
              print(f"LocationManager: Error creating instance: Template '{template_id}' for guild {guild_id_str} is missing required 'name' field.")
              return None

         new_instance_id = str(uuid.uuid4())

         template_initial_state = template.get('initial_state', {})
         if not isinstance(template_initial_state, dict):
              print(f"LocationManager: Warning: Template '{template_id}' initial_state is not a dict. Using empty dict.")
              template_initial_state = {}

         instance_state_data = dict(template_initial_state)
         if initial_state is not None:
             if isinstance(initial_state, dict):
                  instance_state_data.update(initial_state)
             else:
                  print(f"LocationManager: Warning: Provided initial_state... not a dict.")

         instance_for_cache = {
              'id': new_instance_id, 'guild_id': guild_id_str, 'template_id': template_id,
              'state': instance_state_data, 'is_active': True,
         }
         self._get_guild_instances(guild_id_str)[new_instance_id] = instance_for_cache

         if self._db_adapter: # Only mark dirty if DB is enabled
             self._get_guild_dirty_set(guild_id_str).add(new_instance_id)

         print(f"LocationManager: Location instance {new_instance_id} added to cache and marked dirty (if DB enabled).")
         return instance_for_cache


    def get_location_instance(self, guild_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
         return self._get_guild_instances(guild_id).get(str(instance_id))


    async def delete_location_instance(self, guild_id: str, instance_id: str) -> bool:
        guild_id_str = str(guild_id)
        guild_instances_cache = self._get_guild_instances(guild_id_str)
        instance_id_str = str(instance_id)
        if instance_id_str in guild_instances_cache:
             del guild_instances_cache[instance_id_str]
             self._get_guild_deleted_set(guild_id_str).add(instance_id_str)
             self._get_guild_dirty_set(guild_id_str).discard(instance_id_str) # Remove from dirty if there
             print(f"LocationManager: Instance {instance_id_str} marked for deletion.")
             return True
        print(f"LocationManager: Warning: Attempted to delete non-existent instance {instance_id_str}.")
        return False


    def get_location_name(self, guild_id: str, instance_id: str) -> Optional[str]:
         instance_data = self.get_location_instance(guild_id, instance_id)
         if instance_data:
              template = self.get_location_template(guild_id, instance_data.get('template_id'))
              if template and template.get('name'): return template.get('name')
              return f"Unnamed Location ({instance_id})" # Fallback
         return None


    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]:
         instance_data = self.get_location_instance(guild_id, instance_id)
         if instance_data:
              template = self.get_location_template(guild_id, instance_data.get('template_id'))
              if template and isinstance(template.get('exits'), (dict, list)):
                   exits = template.get('exits')
                   if isinstance(exits, dict): return exits
                   if isinstance(exits, list): return {loc_id: loc_id for loc_id in exits} # List of template IDs mapped to themselves
         return {}


    async def update_location_state(self, guild_id: str, instance_id: str, state_updates: Dict[str, Any]) -> bool:
        guild_id_str = str(guild_id)
        instance_data = self.get_location_instance(guild_id_str, instance_id)
        if instance_data:
            current_state = instance_data.setdefault('state', {})
            if not isinstance(current_state, dict): current_state = {}
            current_state.update(state_updates)
            if self._db_adapter: # Mark dirty only if DB enabled
                self._get_guild_dirty_set(guild_id_str).add(instance_data['id'])
            print(f"LocationManager: Updated state for instance {instance_data['id']} for guild {guild_id_str}.")
            return True
        print(f"LocationManager: Warning: Attempted to update state for non-existent instance {instance_id}.")
        return False


    def get_location_channel(self, guild_id: str, instance_id: str) -> Optional[int]:
         instance = self.get_location_instance(guild_id, instance_id)
         if instance:
              template = self.get_location_template(guild_id, instance.get('template_id'))
              if template:
                   channel_id = template.get('channel_id')
                   if channel_id is not None:
                        try: return int(channel_id)
                        except (ValueError, TypeError): print(f"LocationManager: Warning: Invalid channel_id in template {template.get('template_id')} for instance {instance_id}.")
         return None


    def get_all_location_instances(self, guild_id: str) -> List[Dict[str, Any]]:
         return list(self._get_guild_instances(guild_id).values())


    def get_loaded_guild_ids(self) -> List[str]:
         loaded_template_guilds = set(self._location_templates.keys())
         loaded_instance_guilds = set(self._location_instances.keys())
         return list(loaded_template_guilds.union(loaded_instance_guilds))


    # --- Persistence Methods (Called by PersistenceManager) ---
    # Implement save_state and load_state with unified signatures.

    async def save_state(self, guild_id: str, **kwargs) -> None:
        """
        Saves LocationManager dynamic state (instances) for a specific guild to DB.
        Called by PersistenceManager for per-guild saving.
        Accepts guild_id: str and **kwargs context (includes db_adapter).
        """
        guild_id_str = str(guild_id)
        print(f"LocationManager: Saving state for guild {guild_id_str}...")
        # Get db_adapter from context (**kwargs) first.
        db_adapter: Optional[SqliteAdapter] = kwargs.get('db_adapter', self._db_adapter)

        if db_adapter is None:
             print(f"LocationManager: Database adapter is not available. Skipping save for guild {guild_id_str}.")
             return

        # --- Your original save_state logic using db_adapter goes here ---
        guild_instances_cache = self._get_guild_instances(guild_id_str)
        dirty_instances = self._get_guild_dirty_set(guild_id_str)
        deleted_instances = self._get_guild_deleted_set(guild_id_str)

        try:
            if deleted_instances:
                 placeholders_del = ','.join(['?'] * len(deleted_instances))
                 sql_delete_batch = f"DELETE FROM locations WHERE guild_id = ? AND id IN ({placeholders_del})"
                 await db_adapter.execute(sql_delete_batch, (guild_id_str, *list(deleted_instances)))
                 print(f"LocationManager: Deleted {len(deleted_instances)} location instances from DB for guild {guild_id_str}.")
                 deleted_instances.clear()

            instances_to_upsert = [
                guild_instances_cache[inst_id] for inst_id in dirty_instances if inst_id in guild_instances_cache
            ]

            if instances_to_upsert:
                 upsert_sql = ''' INSERT OR REPLACE INTO locations (id, guild_id, template_id, state_json, is_active) VALUES (?, ?, ?, ?, ?) '''
                 data_to_upsert = []
                 for instance_data in instances_to_upsert:
                      try: data_to_upsert.append(( instance_data.get('id'), guild_id_str, instance_data.get('template_id'), json.dumps(instance_data.get('state', {})), int(instance_data.get('is_active', True)), ))
                      except Exception as e: print(f"LocationManager: Error preparing data for instance {instance_data.get('id', 'N/A')} for upsert: {e}"); traceback.print_exc(); raise

                 if data_to_upsert:
                      await db_adapter.executemany(upsert_sql, data_to_upsert)
                      print(f"LocationManager: Upserted {len(data_to_upsert)} instances for guild {guild_id_str}.")
                      dirty_instances.clear()

            else:
                print(f"LocationManager: No dirty instances to save for guild {guild_id_str}.")

        except Exception as e:
            print(f"LocationManager: ❌ Error during saving state for guild {guild_id_str}: {e}"); traceback.print_exc(); raise


    async def load_state(self, **kwargs) -> None:
        """
        Loads LocationManager dynamic state (instances) and static templates from DB.
        Called by PersistenceManager for a specific guild based on context.
        **kwargs: Context from PersistenceManager (includes db_adapter, guild_id).
        """
        # --- FIX: load_state gets args from **kwargs ---
        db_adapter: Optional[SqliteAdapter] = kwargs.get('db_adapter', self._db_adapter)
        guild_id_str: Optional[str] = kwargs.get('guild_id') # Mandatory for per-guild load

        if db_adapter is None:
             print("LocationManager: Database adapter not available. Skipping load.")
             return # Cannot load without DB adapter

        # LocationManager is designed for per-guild load based on guild_id.
        if guild_id_str is None:
             print("LocationManager: Error: load_state called without 'guild_id' in kwargs. Cannot load per-guild data.")
             raise ValueError("LocationManager load_state requires 'guild_id' in kwargs.") # Indicate design expectation


        print(f"LocationManager: Loading state for guild {guild_id_str}...")

        # Clear cache for THIS guild.
        self._clear_guild_state_cache(guild_id_str)

        loaded_instances_count = 0

        try:
            # --- Load static location templates for THIS guild ---
            # Call load_campaign_templates, pass necessary args (guild_id) and relevant context from kwargs.
            await self.load_campaign_templates(guild_id_str, db_adapter=db_adapter, **kwargs)

            # --- Load location instances for THIS guild ---
            sql_instances = ''' SELECT id, template_id, state_json, is_active FROM locations WHERE guild_id = ? '''
            rows_instances = await db_adapter.fetchall(sql_instances, (guild_id_str,))

            if rows_instances:
                 print(f"LocationManager: Found {len(rows_instances)} location instances for guild {guild_id_str}.")
                 guild_instances_cache = self._get_guild_instances(guild_id_str)

                 for row in rows_instances:
                      try:
                           instance_id_raw = row.get('id')
                           if not instance_id_raw or not isinstance(instance_id_raw, str):
                                print(f"LocationManager: Warning: Invalid instance ID '{instance_id_raw}'. Skipping row.")
                                continue

                           state_json_raw = row.get('state_json')
                           instance_state_data = json.loads(state_json_raw or '{}') if state_json_raw else {}
                           if not isinstance(instance_state_data, dict): instance_state_data = {} # Use empty dict on error

                           instance_data: Dict[str, Any] = {
                                'id': instance_id_raw, 'guild_id': guild_id_str,
                                'template_id': row.get('template_id'),
                                'state': instance_state_data, 'is_active': bool(row.get('is_active', 0))
                           }

                           if not instance_data.get('template_id'): print(f"Warning: Instance ID {instance_data.get('id', 'N/A')} missing template_id. Skipping load.") ; continue

                           guild_instances_cache[instance_data['id']] = instance_data
                           loaded_instances_count += 1

                      except json.JSONDecodeError: print(f"LocationManager: Error decoding JSON for instance (ID: {row.get('id', 'N/A')}): {traceback.format_exc()}. Skipping.")
                      except Exception as e: print(f"LocationManager: Error processing instance row (ID: {row.get('id', 'N/A')}): {e}"); traceback.print_exc()


                 print(f"LocationManager: Successfully loaded {loaded_instances_count} instances for guild {guild_id_str}.")

            else:
                 print(f"LocationManager: No location instances found for guild {guild_id_str}.")

        except Exception as e:
            print(f"LocationManager: ❌ Error during loading state for guild {guild_id_str}: {e}"); traceback.print_exc(); self._clear_guild_state_cache(guild_id_str); raise


    def rebuild_runtime_caches(self, guild_id: str, **kwargs) -> None:
         # Signature matches required interface. Implementation can add logic if needed.
         guild_id_str = str(guild_id)
         # Access other managers from kwargs here if needed to rebuild relationships.
         # e.g. char_mgr = kwargs.get('CharacterManager')
         print(f"LocationManager: Rebuilding runtime caches for guild {guild_id_str}.")
         pass # Add implementation here


    # --- Methods for Entity Movement (Called by Action Processors) ---
    # Implementation bodies restored. Need to use injected managers (self._...) or get from **kwargs consistently.
    # Let's use injected managers if available, fallback to kwargs.

    async def move_entity(
        self, guild_id: str, entity_id: str, entity_type: str, from_location_id: Optional[str], to_location_id: str, **kwargs # Context
    ) -> bool:
        # Combine injected and kwargs managers for use in handlers.
        combined_managers = {
            'location_manager': self, # Pass self
            'rule_engine': self._rule_engine or kwargs.get('rule_engine'), # Use injected, fallback to kwargs
            'event_manager': self._event_manager or kwargs.get('event_manager'),
            'send_callback_factory': self._send_callback_factory or kwargs.get('send_callback_factory'),
            'character_manager': self._character_manager or kwargs.get('character_manager'),
            'npc_manager': self._npc_manager or kwargs.get('npc_manager'),
            'item_manager': self._item_manager or kwargs.get('item_manager'),
            'combat_manager': self._combat_manager or kwargs.get('combat_manager'),
            'status_manager': self._status_manager or kwargs.get('status_manager'),
            'party_manager': self._party_manager or kwargs.get('party_manager'),
            'time_manager': self._time_manager or kwargs.get('time_manager'),
            'event_stage_processor': self._event_stage_processor or kwargs.get('event_stage_processor'),
            'event_action_processor': self._event_action_processor or kwargs.get('event_action_processor'),
            **kwargs # Include anything else from original kwargs
        }
        # Filter None managers
        combined_managers = {k: v for k, v in combined_managers.items() if v is not None}

        print(f"LocationManager: Attempting to move {entity_type} ID {entity_id} from {from_location_id} to {to_location_id} for guild {guild_id}.")
        if self.get_location_instance(guild_id, to_location_id) is None:
             print(f"LocationManager: Error: Target instance {to_location_id} not found for guild {guild_id}. Cannot move.")
             return False

        # Handle OnExit triggers before updating location
        if from_location_id and 'on_enter_action_executor' in combined_managers: # Need executor for triggers
            await self.handle_entity_departure(guild_id, from_location_id, entity_id, entity_type, **combined_managers) # Pass context


        # Update the entity's location in its manager
        update_method_name = f"update_{entity_type.lower()}_location"
        entity_manager = combined_managers.get(f"{entity_type}Manager") # Get manager by name convention

        if entity_manager and hasattr(entity_manager, update_method_name):
            try:
                 update_context = {**combined_managers} # Pass combined context to update method
                 update_successful = await getattr(entity_manager, update_method_name)(
                     str(guild_id), entity_id, to_location_id, context=update_context # Assuming update method takes guild_id, entity_id, location_id, context
                 )
                 if not update_successful:
                      raise RuntimeError(f"Failed to update {entity_type} {entity_id} location via its manager.")
            except Exception as e: print(f"LocationManager: ❌ Error updating {entity_type} {entity_id} location: {e}"); traceback.print_exc(); raise


        else: print(f"LocationManager: Error: No manager/update method for {entity_type}. Movement not supported.") ; raise NotImplementedError(...) # Critical


        # Handle OnEnter triggers after updating location
        if 'on_enter_action_executor' in combined_managers:
             await self.handle_entity_arrival(guild_id, to_location_id, entity_id, entity_type, **combined_managers) # Pass context


        print(f"LocationManager: Successfully moved {entity_type} {entity_id} to {to_location_id} for guild {guild_id}. Triggers processed.")
        return True

    # Handle entity arrival/departure methods using combined managers from kwargs
    async def handle_entity_arrival(
        self, guild_id: str, location_instance_id: str, entity_id: str, entity_type: str, **kwargs # Context
    ) -> None:
         # Implementation uses kwargs to get managers and execute triggers/notifications.
         loc_instance_data = self.get_location_instance(guild_id, location_instance_id)
         template_id = loc_instance_data.get('template_id') if loc_instance_data else None
         loc_template_data = self.get_location_template(guild_id, template_id) if template_id else None

         on_enter_triggers = loc_template_data.get('on_enter_triggers', []) if loc_template_data else []
         rule_engine = kwargs.get('rule_engine') # Get RuleEngine from kwargs
         if on_enter_triggers and rule_engine and hasattr(rule_engine, 'execute_triggers'):
              trigger_context = {**kwargs, 'guild_id': guild_id, 'entity_id': entity_id, 'entity_type': entity_type} # Build context for triggers
              await rule_engine.execute_triggers(guild_id, on_enter_triggers, context=trigger_context)

         # Notification logic (uses send_callback_factory and entity managers from kwargs)
         send_cb_factory = kwargs.get('send_callback_factory')
         char_mgr = kwargs.get('character_manager')
         # ... get other managers from kwargs ...
         if send_cb_factory and char_mgr: # Basic check
             # Logic to find entities and send notification via send_cb_factory
             pass # Placeholder

    async def handle_entity_departure(self, guild_id: str, location_instance_id: str, entity_id: str, entity_type: str, **kwargs) -> None:
        # Similar structure to handle_entity_arrival, uses kwargs to get managers.
        loc_instance_data = self.get_location_instance(guild_id, location_instance_id)
        # ... logic to get triggers and managers from kwargs and execute ...
        pass # Placeholder

    # TODO: Implement Process Tick if needed
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs) -> None:
        # Logic here processes location state based on time/context from kwargs.
        pass # Placeholder

# End of LocationManager class