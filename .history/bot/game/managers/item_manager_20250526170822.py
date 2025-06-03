# bot/game/managers/item_manager.py
from __future__ import annotations # Enables using type hints as strings implicitly, simplifying things
import json
import uuid
import traceback
import asyncio

# Import typing components
# Set, Dict, Any, List, Optional, Callable, Awaitable, Union, TYPE_CHECKING
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins

# --- Imports needed ONLY for Type Checking ---
# These modules are imported ONLY for static analysis (Pylance/Mypy).
# This breaks import cycles at runtime and helps Pylance correctly resolve types.
# Use string literals ("ClassName") for type hints in __init__ and methods
# for classes imported here.
if TYPE_CHECKING:
    # Add SqliteAdapter here
    from bot.database.sqlite_adapter import SqliteAdapter
    # Add models if they cause import cycles or are complex
    # from bot.game.models.item_instance import ItemInstance # If you have an ItemInstance model
    # from bot.game.models.item_template import ItemTemplate # If you have an ItemTemplate model
    # Add other managers and RuleEngine
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager # If item effects interact with combat
    from bot.game.managers.status_manager import StatusManager # If items apply statuses
    from bot.game.managers.economy_manager import EconomyManager # If items interact with economy
    from bot.game.managers.crafting_manager import CraftingManager # If items are craftable/ingredients
    # Add other managers if needed in cleanup or other methods
    # from bot.game.managers.event_manager import EventManager
    # from bot.game.managers.time_manager import TimeManager

# --- Imports needed at Runtime ---
# Only import modules/classes here if they are strictly necessary for execution.
# For ItemManager, you might need a model for ItemInstance if you use one.
# Assuming item instances are represented as Dict[str, Any] for simplicity based on DB schema.
# If you have an ItemInstance model with a from_dict method, import it here.
# from bot.game.models.item_instance import ItemInstance # Example


print("DEBUG: item_manager.py module loaded.")


class ItemManager:
    """
    Менеджер для управления предметами (Item Templates и Item Instances).
    Отвечает за загрузку шаблонов, создание, получение, обновление, удаление инстансов предметов,
    управление их владельцами (инвентарь персонажа/NPC/партии, локация) и персистентность.
    Работает на основе guild_id для многогильдийной поддержки инстансов.
    Шаблоны предметов (Item Templates) считаются глобальными.
    """
    # Добавляем required_args для совместимости с PersistenceManager
    # Инстансы предметов привязаны к гильдии, поэтому сохранение/загрузка per-guild.
    required_args_for_load = ["guild_id"] # load_state фильтрует по guild_id
    required_args_for_save = ["guild_id"] # save_state фильтрует по guild_id
    required_args_for_rebuild = ["guild_id"] # rebuild_runtime_caches фильтрует по guild_id

    # --- Class-Level Attribute Annotations ---
    # Статические шаблоны предметов (глобальные, не per-guild)
    _item_templates: Dict[str, Dict[str, Any]] # {template_id: data}

    # Динамические инстансы предметов (per-guild)
    _items: Dict[str, Dict[str, Dict[str, Any]]] # {guild_id: {item_instance_id: data}}

    # Кеши для оптимизации поиска по владельцу и локации (per-guild)
    # Это ускоряет поиск предметов в инвентаре или на земле.
    _items_by_owner: Dict[str, Dict[str, Set[str]]] # {guild_id: {owner_id: {item_id, ...}}}
    _items_by_location: Dict[str, Dict[str, Set[str]]] # {guild_id: {location_id: {item_id, ...}}}

    # Кеши для персистентности инстансов (per-guild)
    _dirty_items: Dict[str, Set[str]] # {guild_id: {item_id, ...}}
    _deleted_items: Dict[str, Set[str]] # {guild_id: {item_id, ...}}


    def __init__(
        self,
        # Используем строковые литералы для всех опциональных зависимостей
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None,
        character_manager: Optional["CharacterManager"] = None, # Needed for cleanup/lookup
        npc_manager: Optional["NpcManager"] = None, # Needed for cleanup/lookup
        location_manager: Optional["LocationManager"] = None, # Needed for cleanup/lookup/dropping
        party_manager: Optional["PartyManager"] = None, # Needed for cleanup/lookup
        combat_manager: Optional["CombatManager"] = None, # If items interact with combat (e.g. consume on use in combat)
        status_manager: Optional["StatusManager"] = None, # If items apply statuses
        economy_manager: Optional["EconomyManager"] = None, # If items are bought/sold
        crafting_manager: Optional["CraftingManager"] = None, # If items are crafted/ingredients
        # Add other dependencies here with Optional and string literals
    ):
        print("Initializing ItemManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        # Store injected managers/dependencies
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._location_manager = location_manager
        self._party_manager = party_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._economy_manager = economy_manager
        self._crafting_manager = crafting_manager
        # Store others...

        # ИСПРАВЛЕНИЕ: Инициализируем кеши
        self._item_templates = {} # {template_id: data} - ГЛОБАЛЬНЫЙ КЕШ
        self._items = {} # {guild_id: {item_instance_id: data}} - ПЕР-ГИЛЬДИЙНЫЙ КЕШ ИНСТАНСОВ
        self._items_by_owner = {} # {guild_id: {owner_id: {item_id, ...}}} - ПЕР-ГИЛЬДИЙНЫЙ КЕШ ПО ВЛАДЕЛЬЦУ
        self._items_by_location = {} # {guild_id: {location_id: {item_id, ...}}} - ПЕР-ГИЛЬДИЙНЫЙ КЕШ ПО ЛОКАЦИИ
        self._dirty_items = {} # {guild_id: {item_id, ...}} - ПЕР-ГИЛЬДИЙНЫЙ DIRTY КЕШ
        self._deleted_items = {} # {guild_id: {item_id, ...}} - ПЕР-ГИЛЬДИЙНЫЙ DELETED КЕШ


        # Load static templates (globally, not per guild)
        self._load_item_templates() # Called once on init

        print("ItemManager initialized.")

    def _load_item_templates(self):
        """(Пример) Загружает статические шаблоны предметов из settings или DB (если глобальные)."""
        # Based on sqlite_adapter.py, item_templates is a global table.
        # This method should load ALL templates from the global table.
        print("ItemManager: Loading global item templates...")
        self._item_templates = {} # Clear global template cache

        # TODO: Implement loading from DB instead of settings if templates are in DB
        # if self._db_adapter:
        #     try:
        #         # SELECT all templates (no guild filter for global table)
        #         sql = "SELECT id, name, description, type, properties FROM item_templates"
        #         rows = asyncio.run(self._db_adapter.fetchall(sql)) # Use asyncio.run for sync init? Or move loading to async setup.
        #         # BETTER: Make this method async and call it from async GameManager setup *before* loading guild states.
        #         # Or, if templates are always in settings, keep this sync method loading from settings.
        #         pass # Loading from DB logic here
        #     except Exception as e:
        #         print(f"ItemManager: Error loading global item templates from DB: {e}"); traceback.print_exc();

        # Example: Load from settings (assuming settings has a 'item_templates' dict)
        try:
            if self._settings and 'item_templates' in self._settings and isinstance(self._settings['item_templates'], dict):
                self._item_templates = self._settings['item_templates']
                loaded_count = len(self._item_templates)
                print(f"ItemManager: Successfully loaded {loaded_count} item templates from settings.")
                if loaded_count > 0:
                    print("ItemManager: Example item templates loaded:")
                    for i, (template_id, template_data) in enumerate(self._item_templates.items()):
                        if i < 3: # Print up to 3 examples
                            print(f"  - ID: {template_id}, Name: {template_data.get('name', 'N/A')}, Type: {template_data.get('type', 'N/A')}")
                        else:
                            break
                    if loaded_count > 3:
                        print(f"  ... and {loaded_count - 3} more.")
            else:
                print("ItemManager: No item templates found in settings or 'item_templates' is not a dict.")
        except Exception as e:
            print(f"ItemManager: Error loading item templates from settings: {e}")
            traceback.print_exc()


    # --- Getters ---
    # get_item_template is GLOBAL
    def get_item_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Получить статический шаблон предмета по ID (глобально)."""
        return self._item_templates.get(str(template_id)) # Ensure template_id is string

    # get_item_instance is PER-GUILD
    def get_item_instance(self, guild_id: str, item_id: str) -> Optional[Dict[str, Any]]:
        """Получить динамический инстанс предмета по ID для определенной гильдии."""
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        # Get from per-guild items cache
        return self._items.get(guild_id_str, {}).get(item_id_str)

    # get_all_item_instances is PER-GUILD
    def get_all_item_instances(self, guild_id: str) -> List[Dict[str, Any]]:
        """Получить список всех загруженных инстансов предметов для определенной гильдии (из кеша)."""
        guild_id_str = str(guild_id)
        # Get values from per-guild items cache
        return list(self._items.get(guild_id_str, {}).values())

    # get_items_by_owner is PER-GUILD
    def get_items_by_owner(self, guild_id: str, owner_id: str) -> List[Dict[str, Any]]:
        """Получить список инстансов предметов, принадлежащих владельцу, для определенной гильдии."""
        guild_id_str = str(guild_id)
        owner_id_str = str(owner_id)
        # Use per-guild lookup cache for item IDs, then get full item data from main cache
        owner_item_ids = self._items_by_owner.get(guild_id_str, {}).get(owner_id_str, set())
        guild_items_cache = self._items.get(guild_id_str, {})
        # Filter main cache by owner item IDs and return the item data dictionaries
        return [guild_items_cache[item_id] for item_id in owner_item_ids if item_id in guild_items_cache] # Ensure item exists in main cache


    # get_items_in_location is PER-GUILD
    def get_items_in_location(self, guild_id: str, location_id: str) -> List[Dict[str, Any]]:
        """Получить список инстансов предметов, находящихся в локации (на земле), для определенной гильдии."""
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        # Use per-guild lookup cache for item IDs, then get full item data from main cache
        location_item_ids = self._items_by_location.get(guild_id_str, {}).get(location_id_str, set())
        guild_items_cache = self._items.get(guild_id_str, {})
        # Filter main cache by location item IDs
        return [guild_items_cache[item_id] for item_id in location_item_ids if item_id in guild_items_cache] # Ensure item exists in main cache


    # --- Item Instance Management ---
    # create_item_instance is PER-GUILD
    async def create_item_instance(self,
                                   guild_id: str, # Item instance belongs to a guild
                                   template_id: str,
                                   owner_id: Optional[str] = None, # Optional owner (char, npc, party, location)
                                   owner_type: Optional[str] = None, # e.g., 'character', 'npc', 'location', 'party'
                                   location_id: Optional[str] = None, # Explicit location if on ground (redundant with owner_type='location'?)
                                   quantity: float = 1.0,
                                   initial_state: Optional[Dict[str, Any]] = None, # Instance-specific state
                                   **kwargs: Any # Context
                                  ) -> Optional[Dict[str, Any]]:
        """
        Создает новый инстанс предмета для определенной гильдии.
        Возвращает словарь данных инстанса предмета.
        """
        guild_id_str = str(guild_id)
        template_id_str = str(template_id)
        print(f"ItemManager: Creating instance for template '{template_id_str}' for guild {guild_id_str}...")

        if self._db_adapter is None:
            print(f"ItemManager: No DB adapter for guild {guild_id_str}. Cannot create item instance.")
            return None # Cannot proceed without DB for persistence

        # Validate template exists (global lookup)
        template = self.get_item_template(template_id_str)
        if not template:
            print(f"ItemManager: Error creating instance: Template '{template_id_str}' not found globally.")
            return None

        # Validate quantity
        if quantity <= 0:
            print(f"ItemManager: Warning creating instance: Quantity must be positive ({quantity}). Cannot create.")
            return None # Cannot create item with zero or negative quantity

        # Validate owner/location consistency
        # If owner_type is 'location', owner_id should be the location_id.
        # If owner_type is anything else, location_id should probably be None (or handled differently).
        # This logic depends on how you model items on the ground vs. in inventory.
        # Let's assume owner_type determines location. If owner_type is 'location', owner_id IS the location ID.
        # If owner_type is something else, location_id should be None.
        resolved_location_id: Optional[str] = None
        resolved_owner_id: Optional[str] = None
        resolved_owner_type: Optional[str] = None

        if owner_type and owner_id:
            resolved_owner_type = str(owner_type)
            resolved_owner_id = str(owner_id)
            if resolved_owner_type.lower() == 'location':
                 resolved_location_id = resolved_owner_id # Owner ID is the location ID
                 print(f"ItemManager: Creating item instance in location {resolved_location_id} (guild {guild_id_str}).")
            # else: resolved_location_id remains None
        # else: owner_type and owner_id remain None, resolved_location_id remains None

        # If location_id was explicitly passed *and* owner_type is NOT location, decide what to do.
        # For simplicity, let's prioritize owner_type. If owner_type is set and not 'location', explicit location_id is ignored.
        # If owner_type is None, the item has no owner but MIGHT be in a location (e.g., spawned on the ground).
        if resolved_owner_type is None and location_id is not None:
             resolved_location_id = str(location_id)
             print(f"ItemManager: Creating item instance with no owner in location {resolved_location_id} (guild {guild_id_str}).")


        new_item_id = str(uuid.uuid4()) # Generate unique ID for the instance

        item_data: Dict[str, Any] = { # Dictionary representing the item instance data
            'id': new_item_id,
            'template_id': template_id_str,
            'guild_id': guild_id_str, # Item instance belongs to a guild
            'owner_id': resolved_owner_id,
            'owner_type': resolved_owner_type,
            'location_id': resolved_location_id, # Location ID if owner_type is 'location' or no owner
            'quantity': float(quantity), # Ensure float
            'state_variables': initial_state if initial_state is not None and isinstance(initial_state, dict) else {},
            'is_temporary': int(bool(kwargs.get('is_temporary', False))), # 0 or 1
            # Add other fields from DB schema here if needed (e.g. name override, durability)
            # 'name': kwargs.get('name_override') # Example
        }

        try:
            # --- Save to DB ---
            if self._db_adapter:
                # Ensure SQL matches ALL columns in the 'items' table, including guild_id, owner_type, location_id etc.
                sql = '''
                    INSERT INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    -- Add other columns here
                '''
                params = (
                    item_data['id'], item_data['template_id'], item_data['guild_id'],
                    item_data['owner_id'], item_data['owner_type'], item_data['location_id'],
                    item_data['quantity'], json.dumps(item_data['state_variables']),
                    item_data['is_temporary']
                    # Add other parameters in order
                )

                await self._db_adapter.execute(sql, params)
                # execute already commits

                print(f"ItemManager: Item instance {new_item_id} ({template_id_str}) created and saved to DB for guild {guild_id_str}.")
            else:
                 print(f"ItemManager: No DB adapter. Simulating save for item instance {new_item_id} for guild {guild_id_str}.")


            # --- Add to cache after successful save ---
            # Add to per-guild items cache
            self._items.setdefault(guild_id_str, {})[new_item_id] = item_data

            # Update per-guild lookup caches
            self._update_lookup_caches_add(guild_id_str, item_data) # Update owner/location caches

            # Mark as dirty for this guild (although just saved, might be modified later in same tick)
            # But typically, just created means it's clean from DB perspective after saving.
            # Let's NOT mark dirty here unless immediate modification follows creation.
            # self._dirty_items.setdefault(guild_id_str, set()).add(new_item_id) # Optional, depends on workflow


            print(f"ItemManager: Item instance {new_item_id} added to cache and lookup caches for guild {guild_id_str}.")

            return item_data # Return the created item data dictionary

        except Exception as e:
            print(f"ItemManager: ❌ Error creating or saving item instance for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # rollback already in execute
            return None

    # remove_item_instance is PER-GUILD
    async def remove_item_instance(self, guild_id: str, item_id: str, **kwargs: Any) -> bool:
        """
        Удаляет инстанс предмета по ID из кеша и БД для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        print(f"ItemManager: Removing item instance {item_id_str} for guild {guild_id_str}...")

        # Get the item data from the per-guild cache before removing
        guild_items_cache = self._items.get(guild_id_str, {})
        item_data_to_remove = guild_items_cache.get(item_id_str)

        if not item_data_to_remove:
            print(f"ItemManager: Warning: Attempted to remove non-existent item instance {item_id_str} for guild {guild_id_str} (not found in cache).")
            # If not in cache, check if it's already marked for deletion
            if guild_id_str in self._deleted_items and item_id_str in self._deleted_items[guild_id_str]:
                 print(f"ItemManager: Item instance {item_id_str} for guild {guild_id_str} was already marked for deletion.")
                 return True # Consider it successful if already marked
            # If not in cache and not marked for deletion, still attempt DB delete just in case
            pass # Continue to DB delete attempt


        try:
            # --- Удаляем из БД ---
            if self._db_adapter:
                # Add guild_id filter to DELETE
                sql = 'DELETE FROM items WHERE id = ? AND guild_id = ?'
                await self._db_adapter.execute(sql, (item_id_str, guild_id_str))
                # execute already commits
                print(f"ItemManager: Item instance {item_id_str} deleted from DB for guild {guild_id_str}.")
            else:
                 print(f"ItemManager: No DB adapter. Simulating delete from DB for item {item_id_str} for guild {guild_id_str}.")

            # --- Удаляем из кеша ---
            if guild_items_cache: # Check if cache for guild exists
                 guild_items_cache.pop(item_id_str, None) # Remove by ID from per-guild cache
                 # If cache for guild is empty after removal, remove the guild key
                 if not guild_items_cache:
                      self._items.pop(guild_id_str, None)


            # Update per-guild lookup caches (remove old owner/location mapping)
            if item_data_to_remove: # Only update lookups if the item was found in cache
                 self._update_lookup_caches_remove(guild_id_str, item_data_to_remove) # Update owner/location caches


            # Удаляем из пер-гильдийных персистентных кешей
            self._dirty_items.get(guild_id_str, set()).discard(item_id_str) # Remove from dirty set
            self._deleted_items.setdefault(guild_id_str, set()).add(item_id_str) # Add to deleted set

            print(f"ItemManager: Item instance {item_id_str} removed from cache and lookup caches, marked for deletion for guild {guild_id_str}.")

            return True

        except Exception as e:
            print(f"ItemManager: ❌ Error removing item instance {item_id_str} for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # rollback already in execute
            return False # Indicate removal failed


    # update_item_instance is PER-GUILD
    async def update_item_instance(self, guild_id: str, item_id: str, updates: Dict[str, Any], **kwargs: Any) -> bool:
        """
        Обновляет данные инстанса предмета (например, количество, state_variables) для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)

        # Get the item data from the per-guild cache
        guild_items_cache = self._items.get(guild_id_str, {})
        item_data = guild_items_cache.get(item_id_str)

        if not item_data:
            print(f"ItemManager: Warning: Attempted to update non-existent item instance {item_id_str} for guild {guild_id_str}.")
            return False # Cannot update if not in cache

        # Check if owner/location is being changed, as this affects lookup caches
        owner_changed = ('owner_id' in updates or 'owner_type' in updates) and (updates.get('owner_id') != item_data.get('owner_id') or updates.get('owner_type') != item_data.get('owner_type'))
        location_changed = ('location_id' in updates) and (updates.get('location_id') != item_data.get('location_id'))

        # If owner/location is changing, remove old lookup entries BEFORE updating the item_data
        if owner_changed or location_changed:
            # Pass the item data *before* the update to the remove helper
            self._update_lookup_caches_remove(guild_id_str, item_data)


        # Apply updates to the item data dictionary
        # Be careful with nested dictionaries like 'state_variables'
        if 'state_variables' in updates and isinstance(updates['state_variables'], dict):
             # Update state_variables separately to merge
             current_state = item_data.setdefault('state_variables', {}) # Use setdefault for safety
             if not isinstance(current_state, dict): # If it wasn't a dict somehow, reset it
                  print(f"ItemManager: Warning: Item {item_id_str} state_variables is not a dict ({type(current_state)}). Resetting.")
                  current_state = {}
             current_state.update(updates['state_variables']) # Merge state_variables updates
             # Remove state_variables from the main updates dict to avoid overwriting the reference
             updates_without_state = {k: v for k, v in updates.items() if k != 'state_variables'}
             item_data.update(updates_without_state) # Apply other updates
        else:
             # Apply all updates directly if state_variables is not in updates or not a dict
             item_data.update(updates)


        # After updating item_data, add new entries to lookup caches if owner/location changed
        if owner_changed or location_changed:
            # Pass the item data *after* the update to the add helper
            self._update_lookup_caches_add(guild_id_str, item_data)


        # Mark the item instance as dirty for this guild
        self.mark_item_dirty(guild_id_str, item_id_str) # Use the helper method


        print(f"ItemManager: Updated item instance {item_id_str} for guild {guild_id_str}. Marked dirty.")
        return True


    # --- Persistence Methods (Called by PersistenceManager) ---

    # load_state is PER-GUILD
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """
        Загружает инстансы предметов для определенной гильдии из базы данных в кеш.
        """
        guild_id_str = str(guild_id)
        print(f"ItemManager: Loading item instances for guild {guild_id_str} from DB...")

        if self._db_adapter is None:
             print(f"ItemManager: Database adapter is not available. Loading placeholder item instances for guild {guild_id_str}.")
             self._clear_guild_state_cache(guild_id_str) # Clear caches for this guild
             print(f"ItemManager: State is default after load (no DB adapter) for guild {guild_id_str}. Item Instances = 0.")
             return

        # Очищаем все кеши для этой гильдии перед загрузкой
        self._clear_guild_state_cache(guild_id_str)
        guild_items_cache = self._items[guild_id_str] # Get reference to the empty cache for this guild


        try:
            # Select all item instances ONLY for this guild
            # Ensure SELECT matches ALL columns in the 'items' table
            sql_items = '''
                SELECT id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary
                FROM items WHERE guild_id = ?
            '''
            rows_items = await self._db_adapter.fetchall(sql_items, (guild_id_str,))

            if rows_items:
                 print(f"ItemManager: Found {len(rows_items)} item instances in DB for guild {guild_id_str}.")

                 loaded_count = 0
                 for row in rows_items:
                      try:
                           # Create item data dictionary from DB row
                           row_dict = dict(row) # Convert Row object to dict

                           # Validate and process basic fields
                           item_id_raw = row_dict.get('id')
                           loaded_guild_id_raw = row_dict.get('guild_id') # Should match guild_id_str

                           if item_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                                print(f"ItemManager: Warning: Skipping item instance row with invalid ID ('{item_id_raw}') or mismatched guild_id ('{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row_dict}.")
                                continue # Skip invalid or mismatched rows

                           item_id = str(item_id_raw)

                           # Process quantity (ensure float)
                           quantity_raw = row_dict.get('quantity', 1.0)
                           item_quantity = float(quantity_raw) if isinstance(quantity_raw, (int, float)) else 1.0

                           # Process boolean (ensure 0/1 is bool)
                           is_temporary_raw = row_dict.get('is_temporary', 0)
                           item_is_temporary = bool(is_temporary_raw) # 0/1 to bool


                           # Process JSON fields
                           state_json_raw = row_dict.get('state_variables')
                           item_state_variables = json.loads(state_json_raw or '{}') if isinstance(state_json_raw, (str, bytes)) else {}
                           if not isinstance(item_state_variables, dict):
                               print(f"ItemManager: Warning: State variables for item {item_id} not a dict ({type(item_state_variables)}) for guild {guild_id_str}. Resetting.")
                               item_state_variables = {}


                           # Build item_data dictionary for cache
                           item_data: Dict[str, Any] = {
                               'id': item_id,
                               'template_id': str(row_dict.get('template_id')) if row_dict.get('template_id') is not None else None, # Ensure string or None
                               'guild_id': guild_id_str, # Store as string
                               'owner_id': str(row_dict['owner_id']) if row_dict.get('owner_id') is not None else None, # Ensure string or None
                               'owner_type': str(row_dict['owner_type']) if row_dict.get('owner_type') is not None else None, # Ensure string or None
                               'location_id': str(row_dict['location_id']) if row_dict.get('location_id') is not None else None, # Ensure string or None
                               'quantity': item_quantity,
                               'state_variables': item_state_variables,
                               'is_temporary': item_is_temporary,
                               # Load other columns here
                           }

                           # Validate essential fields after parsing
                           if item_data.get('template_id') is None:
                                print(f"ItemManager: Warning: Item instance {item_id} missing template_id for guild {guild_id_str}. Skipping load.")
                                continue # Skip item if template_id is missing

                           # Add the loaded item to the per-guild cache
                           guild_items_cache[item_id] = item_data
                           loaded_count += 1

                           # Update per-guild lookup caches upon loading
                           self._update_lookup_caches_add(guild_id_str, item_data) # Rebuild owner/location caches during load


                      except (json.JSONDecodeError, ValueError, TypeError) as e:
                           print(f"ItemManager: ❌ Error decoding or converting item data from DB for ID {row.get('id', 'Unknown')} for guild {guild_id_str}: {e}. Skipping item instance.")
                           import traceback
                           print(traceback.format_exc())
                      except Exception as e: # Catch any other errors during row processing
                           print(f"ItemManager: ❌ Error processing item instance row for ID {row.get('id', 'Unknown')} for guild {guild_id_str}: {e}. Skipping item instance.")
                           import traceback
                           print(traceback.format_exc())


                 print(f"ItemManager: Successfully loaded {loaded_count} item instances into cache for guild {guild_id_str}.")
                 if loaded_count < len(rows_items):
                     print(f"ItemManager: Note: Failed to load {len(rows_items) - loaded_count} item instances for guild {guild_id_str} due to errors.")


            else:
                 print(f"ItemManager: No item instances found in DB for guild {guild_id_str}.")


        except Exception as e:
            print(f"ItemManager: ❌ CRITICAL ERROR during loading item instances for guild {guild_id_str} from DB: {e}")
            import traceback
            print(traceback.format_exc())
            print(f"ItemManager: Loading failed for guild {guild_id_str}. State for this guild might be incomplete.")
            # Clear caches for this guild on critical load error
            self._clear_guild_state_cache(guild_id_str)
            raise # Re-raise the exception so GameManager knows load failed


    # save_state is PER-GUILD
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """
        Сохраняет измененные и удаленные инстансы предметов для определенной гильдии в БД.
        """
        guild_id_str = str(guild_id)
        print(f"ItemManager: Saving state for guild {guild_id_str}...")

        if self._db_adapter is None:
             print(f"ItemManager: Database adapter not available. Skipping save for guild {guild_id_str}.")
             return

        # Get per-guild persistence caches
        dirty_item_ids_set = self._dirty_items.get(guild_id_str, set()).copy() # Use a copy
        deleted_item_ids_set = self._deleted_items.get(guild_id_str, set()).copy() # Use a copy

        if not dirty_item_ids_set and not deleted_item_ids_set:
             # print(f"ItemManager: No dirty or deleted items to save for guild {guild_id_str}.") # Too noisy
             # Clear per-guild dirty/deleted sets if nothing to save/delete
             self._dirty_items.pop(guild_id_str, None)
             self._deleted_items.pop(guild_id_str, None)
             return

        print(f"ItemManager: Saving {len(dirty_item_ids_set)} dirty, {len(deleted_item_ids_set)} deleted item instances for guild {guild_id_str}.")

        try:
            # --- Delete marked items for this guild ---
            if deleted_item_ids_set:
                 ids_to_delete = list(deleted_item_ids_set)
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 # Ensure deleting ONLY for this guild and these IDs
                 sql_delete_batch = f"DELETE FROM items WHERE guild_id = ? AND id IN ({placeholders_del})"
                 await self._db_adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete)));
                 print(f"ItemManager: Deleted {len(ids_to_delete)} item instances from DB for guild {guild_id_str}.")
                 # Clear per-guild deleted set after successful deletion
                 self._deleted_items.pop(guild_id_str, None)


            # --- Upsert dirty items for this guild ---
            # Get items from the per-guild cache using the dirty IDs
            guild_items_cache = self._items.get(guild_id_str, {})
            items_to_upsert_list = [ item for id in list(dirty_item_ids_set) if (item := guild_items_cache.get(id)) is not None ] # Filter for items still in cache

            if items_to_upsert_list:
                 print(f"ItemManager: Upserting {len(items_to_upsert_list)} item instances for guild {guild_id_str}...")
                 # Ensure SQL matches ALL columns in the 'items' table for INSERT OR REPLACE
                 upsert_sql = '''
                    INSERT OR REPLACE INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    -- Add other columns here
                 '''
                 data_to_upsert = []
                 upserted_item_ids: Set[str] = set() # Track IDs successfully prepared

                 for item_data in items_to_upsert_list:
                      try:
                          item_id = item_data.get('id')
                          item_guild_id = item_data.get('guild_id')

                          # Double check required fields and guild ID match
                          if item_id is None or str(item_guild_id) != guild_id_str or item_data.get('template_id') is None:
                              print(f"ItemManager: Warning: Skipping upsert for invalid item instance (ID: '{item_id}', Tpl: '{item_data.get('template_id')}', Guild: '{item_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                              continue # Skip this invalid item

                          quantity = item_data.get('quantity', 1.0)
                          state_variables = item_data.get('state_variables', {})
                          is_temporary = item_data.get('is_temporary', False)

                          # Ensure quantity is numeric
                          if not isinstance(quantity, (int, float)):
                              print(f"ItemManager: Warning: Invalid quantity type for item {item_id} ({type(quantity)}). Saving as 1.0.")
                              quantity = 1.0
                          quantity = float(quantity) # Ensure float

                          # Ensure state_variables is a dict for JSON dump
                          if not isinstance(state_variables, dict):
                              print(f"ItemManager: Warning: Item {item_id} state_variables is not a dict ({type(state_variables)}). Saving as empty dict.")
                              state_variables = {}

                          # Ensure boolean is int 0/1
                          is_temporary_int = int(bool(is_temporary))


                          data_to_upsert.append((
                              str(item_id), # Ensure string ID
                              str(item_data['template_id']), # Ensure string template ID
                              guild_id_str, # Ensure correct guild_id string
                              str(item_data['owner_id']) if item_data.get('owner_id') is not None else None, # Ensure string or None
                              str(item_data['owner_type']) if item_data.get('owner_type') is not None else None, # Ensure string or None
                              str(item_data['location_id']) if item_data.get('location_id') is not None else None, # Ensure string or None
                              quantity,
                              json.dumps(state_variables),
                              is_temporary_int,
                              # Add other parameters
                          ));
                          upserted_item_ids.add(str(item_id)) # Track ID

                      except Exception as e:
                          print(f"ItemManager: Error preparing data for item instance {item_data.get('id', 'N/A')} (guild {item_data.get('guild_id', 'N/A')}) for upsert: {e}"); traceback.print_exc();
                          # This item won't be saved in this batch but remains in _dirty_items

                 if data_to_upsert:
                     try:
                         await self._db_adapter.execute_many(upsert_sql, data_to_upsert);
                         print(f"ItemManager: Successfully upserted {len(data_to_upsert)} item instances for guild {guild_id_str}.")
                         # Only clear dirty flags for items that were successfully processed
                         if guild_id_str in self._dirty_items:
                              self._dirty_items[guild_id_str].difference_update(upserted_item_ids)
                              # If set is empty after update, remove the guild key
                              if not self._dirty_items[guild_id_str]:
                                   del self._dirty_items[guild_id_str]

                     except Exception as e:
                          print(f"ItemManager: Error during batch upsert for guild {guild_id_str}: {e}"); traceback.print_exc();
                          # Don't clear dirty_items if batch upsert failed


        except Exception as e:
             print(f"ItemManager: ❌ Error during saving state for guild {guild_id_str}: {e}"); traceback.print_exc();
             # For save, it's generally better NOT to clear dirty/deleted on error
             # to allow retry on the next save interval.
             # raise # Re-raise if critical


        print(f"ItemManager: Save state complete for guild {guild_id_str}.")


    # rebuild_runtime_caches is PER-GUILD
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
         """
         Перестраивает внутренние кеши TimeManager после загрузки для определенной гильдии.
         Called by PersistenceManager *after* load_state for the guild.
         """
         guild_id_str = str(guild_id)
         print(f"ItemManager: Rebuilding runtime caches for guild {guild_id_str}...")

         # Clear and rebuild per-guild lookup caches (_items_by_owner, _items_by_location)
         # based on the items already loaded into _items[guild_id] by load_state.
         self._items_by_owner.pop(guild_id_str, None)
         self._items_by_owner[guild_id_str] = {} # Create empty per-guild cache

         self._items_by_location.pop(guild_id_str, None)
         self._items_by_location[guild_id_str] = {} # Create empty per-guild cache


         guild_items_cache = self._items.get(guild_id_str, {}) # Get the loaded items for this guild

         for item_id, item_data in guild_items_cache.items():
              # Use the helper method to add items to the lookup caches
              self._update_lookup_caches_add(guild_id_str, item_data)

         # Example: Interact with other managers' caches if needed.
         # char_mgr = kwargs.get('character_manager', self._character_manager)
         # if char_mgr and hasattr(char_mgr, 'notify_items_loaded'):
         #      # If CharacterManager needs to know which items were loaded for its characters
         #      characters_in_guild = char_mgr.get_all_characters(guild_id_str) # Assuming this getter exists
         #      await char_mgr.notify_items_loaded(guild_id_str, self, characters_in_guild, **kwargs) # Pass self (ItemManager)


         print(f"ItemManager: Runtime caches rebuilt for guild {guild_id_str}.")


    # --- Cleanup Methods (Called by other managers) ---
    # These methods should get guild_id from the context dictionary

    # clean_up_for_character is PER-GUILD (via context)
    async def clean_up_for_character(self, character_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
         """Удаляет или переносит предметы из инвентаря персонажа при его удалении или смерти."""
         guild_id = context.get('guild_id') # Get guild_id from context
         if not guild_id: print("ItemManager: Error in clean_up_for_character: Missing guild_id in context."); return
         guild_id_str = str(guild_id)
         char_id_str = str(character_id)
         print(f"ItemManager: Cleaning up items for character {char_id_str} in guild {guild_id_str}...")

         # Get all items owned by this character for this guild
         # Use the per-guild getter
         items_to_clean = self.get_items_by_owner(guild_id_str, char_id_str) # Assumes character_id is the owner_id

         if not items_to_clean:
              print(f"ItemManager: No items found for character {char_id_str} in guild {guild_id_str}.")
              return

         print(f"ItemManager: Found {len(items_to_clean)} items for character {char_id_str} in guild {guild_id_str}. Processing...")

         # Define cleanup strategy (e.g., drop on ground, destroy, transfer to default location/inventory)
         # Example: Drop items on the ground in the character's last known location.
         # Needs LocationManager from context or self, and the character's location from context or char object.
         char_location_id: Optional[str] = context.get('location_instance_id') # Try getting location from context first
         if char_location_id is None:
              # Fallback: Try to get the character object and its location (requires CharacterManager in context)
              char_mgr = context.get('character_manager', self._character_manager) # type: Optional["CharacterManager"]
              if char_mgr and hasattr(char_mgr, 'get_character'):
                   # Get character using guild_id
                   char_obj = char_mgr.get_character(guild_id_str, char_id_str) # Assumes get_character is per-guild
                   if char_obj:
                        char_location_id = getattr(char_obj, 'location_id', None) # Safely get location_id from char object


         if char_location_id is None:
              print(f"ItemManager: Warning: Cannot determine location to drop items for character {char_id_str} in guild {guild_id_str}. Items will be destroyed.")
              cleanup_strategy = 'destroy'
              drop_location_id = None
         else:
              # Check if the location instance actually exists for this guild
              loc_mgr = context.get('location_manager', self._location_manager) # type: Optional["LocationManager"]
              drop_location_instance = None
              if loc_mgr and hasattr(loc_mgr, 'get_location_instance'):
                   # Get location instance using guild_id
                   drop_location_instance = loc_mgr.get_location_instance(guild_id_str, char_location_id) # Assumes get_location_instance is per-guild

              if drop_location_instance:
                   cleanup_strategy = 'drop'
                   drop_location_id = char_location_id
                   print(f"ItemManager: Dropping items at location instance {drop_location_id} for character {char_id_str} in guild {guild_id_str}.")
              else:
                   print(f"ItemManager: Warning: Character's location instance '{char_location_id}' not found for guild {guild_id_str}. Items will be destroyed instead of dropped.")
                   cleanup_strategy = 'destroy'
                   drop_location_id = None


         for item_data in list(items_to_clean): # Iterate over a copy
              item_id = item_data.get('id')
              if item_id is None:
                   print(f"ItemManager: Warning: Item data for char {char_id_str} has no ID: {item_data}. Skipping cleanup.")
                   continue

              try:
                   if cleanup_strategy == 'drop' and drop_location_id is not None:
                        # Move the item to the location (change owner/type/location_id)
                        # update_item_instance needs guild_id, item_id, updates
                        updates = {
                            'owner_id': drop_location_id,
                            'owner_type': 'location',
                            'location_id': drop_location_id # Redundant if owner_type='location', but explicit is clear
                        }
                        # update_item_instance marks the item dirty
                        await self.update_item_instance(guild_id_str, item_id, updates, **context) # Pass context
                        print(f"ItemManager: Dropped item {item_id} for character {char_id_str} at location {drop_location_id}.")

                   elif cleanup_strategy == 'destroy':
                        # Remove the item instance entirely
                        # remove_item_instance needs guild_id, item_id
                        await self.remove_item_instance(guild_id_str, item_id, **context) # Pass context
                        print(f"ItemManager: Destroyed item {item_id} for character {char_id_str}.")

                   # TODO: Add other strategies (e.g., transfer to GM inventory)

              except Exception as e:
                   print(f"ItemManager: Error cleaning up item {item_id} for character {char_id_str} in guild {guild_id_str}: {e}")
                   traceback.print_exc()

         print(f"ItemManager: Item cleanup complete for character {char_id_str} in guild {guild_id_str}.")


    # clean_up_for_npc is PER-GUILD (via context)
    async def clean_up_for_npc(self, npc_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
         """Удаляет или переносит предметы из инвентаря NPC при его удалении oли смерти."""
         guild_id = context.get('guild_id') # Get guild_id from context
         if not guild_id: print("ItemManager: Error in clean_up_for_npc: Missing guild_id in context."); return
         guild_id_str = str(guild_id)
         npc_id_str = str(npc_id)
         print(f"ItemManager: Cleaning up items for NPC {npc_id_str} in guild {guild_id_str}...")

         # Get all items owned by this NPC for this guild
         items_to_clean = self.get_items_by_owner(guild_id_str, npc_id_str) # Assumes npc_id is the owner_id

         if not items_to_clean:
              print(f"ItemManager: No items found for NPC {npc_id_str} in guild {guild_id_str}.")
              return

         print(f"ItemManager: Found {len(items_to_clean)} items for NPC {npc_id_str} in guild {guild_id_str}. Processing...")

         # Cleanup strategy for NPC items can be different (e.g., drop always, or drop some)
         # Example: Drop items on the ground at the NPC's last known location.
         npc_location_id: Optional[str] = context.get('location_instance_id') # Try getting location from context
         if npc_location_id is None:
              # Fallback: Try to get the NPC object and its location (requires NpcManager in context)
              npc_mgr = context.get('npc_manager', self._npc_manager) # type: Optional["NpcManager"]
              if npc_mgr and hasattr(npc_mgr, 'get_npc'):
                   # Get NPC using guild_id
                   npc_obj = npc_mgr.get_npc(guild_id_str, npc_id_str) # Assumes get_npc is per-guild
                   if npc_obj:
                        npc_location_id = getattr(npc_obj, 'location_id', None) # Safely get location_id from NPC object


         if npc_location_id is None:
              print(f"ItemManager: Warning: Cannot determine location to drop items for NPC {npc_id_str} in guild {guild_id_str}. Items will be destroyed.")
              cleanup_strategy = 'destroy'
              drop_location_id = None
         else:
              # Check if the location instance actually exists for this guild
              loc_mgr = context.get('location_manager', self._location_manager) # type: Optional["LocationManager"]
              drop_location_instance = None
              if loc_mgr and hasattr(loc_mgr, 'get_location_instance'):
                   # Get location instance using guild_id
                   drop_location_instance = loc_mgr.get_location_instance(guild_id_str, npc_location_id)

              if drop_location_instance:
                   cleanup_strategy = 'drop'
                   drop_location_id = npc_location_id
                   print(f"ItemManager: Dropping items at location instance {drop_location_id} for NPC {npc_id_str} in guild {guild_id_str}.")
              else:
                   print(f"ItemManager: Warning: NPC's location instance '{npc_location_id}' not found for guild {guild_id_str}. Items will be destroyed instead of dropped.")
                   cleanup_strategy = 'destroy'
                   drop_location_id = None


         for item_data in list(items_to_clean): # Iterate over a copy
              item_id = item_data.get('id')
              if item_id is None:
                   print(f"ItemManager: Warning: Item data for NPC {npc_id_str} has no ID: {item_data}. Skipping cleanup.")
                   continue

              try:
                   if cleanup_strategy == 'drop' and drop_location_id is not None:
                        # Move the item to the location
                        updates = {
                            'owner_id': drop_location_id,
                            'owner_type': 'location',
                            'location_id': drop_location_id
                        }
                        await self.update_item_instance(guild_id_str, item_id, updates, **context)
                        print(f"ItemManager: Dropped item {item_id} for NPC {npc_id_str} at location {drop_location_id}.")

                   elif cleanup_strategy == 'destroy':
                        # Remove the item instance
                        await self.remove_item_instance(guild_id_str, item_id, **context)
                        print(f"ItemManager: Destroyed item {item_id} for NPC {npc_id_str}.")

                   # TODO: Add loot table logic if applicable

              except Exception as e:
                   print(f"ItemManager: Error cleaning up item {item_id} for NPC {npc_id_str} in guild {guild_id_str}: {e}")
                   traceback.print_exc()

         print(f"ItemManager: Item cleanup complete for NPC {npc_id_str} in guild {guild_id_str}.")

    # remove_items_by_location is called by LocationManager.clean_up_location_contents
    async def remove_items_by_location(self, location_id: str, guild_id: str, **kwargs: Any) -> None:
         """Удаляет все предметы, находящиеся на земле в указанном инстансе локации, для определенной гильдии."""
         guild_id_str = str(guild_id)
         location_id_str = str(location_id)
         print(f"ItemManager: Removing items located in instance {location_id_str} for guild {guild_id_str}...")

         # Get all items located in this instance for this guild
         # Use the per-guild getter
         items_to_remove = self.get_items_in_location(guild_id_str, location_id_str)

         if not items_to_remove:
              print(f"ItemManager: No items found located in {location_id_str} for guild {guild_id_str}.")
              return

         print(f"ItemManager: Found {len(items_to_remove)} items located in {location_id_str} for guild {guild_id_str}. Removing...")

         for item_data in list(items_to_remove): # Iterate over a copy
              item_id = item_data.get('id')
              if item_id is None:
                   print(f"ItemManager: Warning: Item data located in {location_id_str} has no ID: {item_data}. Skipping removal.")
                   continue
              try:
                   # Remove the item instance entirely
                   # remove_item_instance needs guild_id, item_id
                   await self.remove_item_instance(guild_id_str, item_id, **kwargs) # Pass context
                   print(f"ItemManager: Removed item {item_id} from location {location_id_str}.")
              except Exception as e:
                   print(f"ItemManager: Error removing item {item_id} located in {location_id_str} in guild {guild_id_str}: {e}")
                   traceback.print_exc()

         print(f"ItemManager: Item removal complete for location instance {location_id_str} in guild {guild_id_str}.")


    # TODO: Add clean_up_for_party(party_id, context) method if parties can own items

    # --- Helper Methods ---

    # Helper to clear guild state caches
    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        # Remove all per-guild caches for the specific guild ID
        self._items.pop(guild_id_str, None)
        self._items[guild_id_str] = {} # Create empty dict for this guild
        self._items_by_owner.pop(guild_id_str, None)
        self._items_by_owner[guild_id_str] = {} # Create empty dict for this guild
        self._items_by_location.pop(guild_id_str, None)
        self._items_by_location[guild_id_str] = {} # Create empty dict for this guild
        self._dirty_items.pop(guild_id_str, None) # Clear dirty flags
        self._deleted_items.pop(guild_id_str, None) # Clear deleted flags
        print(f"ItemManager: Cleared per-guild caches for guild {guild_id_str}.")


    # Helper to mark an item instance as dirty (per-guild)
    def mark_item_dirty(self, guild_id: str, item_id: str) -> None:
         """Помечает инстанс предмета как измененный для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         item_id_str = str(item_id)
         # Check if the item exists in the per-guild cache
         if guild_id_str in self._items and item_id_str in self._items[guild_id_str]:
              # Add to the per-guild dirty set
              self._dirty_items.setdefault(guild_id_str, set()).add(item_id_str)
         # else: print(f"ItemManager: Warning: Attempted to mark non-existent item {item_id_str} in guild {guild_id_str} as dirty.") # Too noisy?


    # Helper to update lookup caches when an item is added or modified (owner/location changed)
    def _update_lookup_caches_add(self, guild_id: str, item_data: Dict[str, Any]) -> None:
        """Обновляет кеши _items_by_owner и _items_by_location, добавляя запись для предмета."""
        guild_id_str = str(guild_id)
        item_id_str = str(item_data.get('id')) # Ensure ID is string

        owner_id = item_data.get('owner_id')
        owner_type = item_data.get('owner_type')
        location_id = item_data.get('location_id')

        # Add to owner lookup cache if owner is set
        if owner_id is not None: # owner_type check is implicit if owner_id is None
             owner_id_str = str(owner_id)
             self._items_by_owner.setdefault(guild_id_str, {}).setdefault(owner_id_str, set()).add(item_id_str)
             # print(f"ItemManager: Added item {item_id_str} to owner lookup for {owner_type} {owner_id_str} in guild {guild_id_str}.") # Debug

        # Add to location lookup cache if location is set (usually when owner_type is 'location' or owner is None)
        if location_id is not None:
             location_id_str = str(location_id)
             self._items_by_location.setdefault(guild_id_str, {}).setdefault(location_id_str, set()).add(item_id_str)
             # print(f"ItemManager: Added item {item_id_str} to location lookup for {location_id_str} in guild {guild_id_str}.") # Debug


    # Helper to update lookup caches when an item is removed or modified (owner/location changed)
    # Pass the item data *before* the modification/removal
    def _update_lookup_caches_remove(self, guild_id: str, item_data: Dict[str, Any]) -> None:
        """Обновляет кеши _items_by_owner и _items_by_location, удаляя запись для предмета."""
        guild_id_str = str(guild_id)
        item_id_str = str(item_data.get('id')) # Ensure ID is string

        owner_id = item_data.get('owner_id')
        # owner_type = item_data.get('owner_type') # Not strictly needed for removal lookup
        location_id = item_data.get('location_id')

        # Remove from owner lookup cache if it was there
        if owner_id is not None:
             owner_id_str = str(owner_id)
             guild_owner_cache = self._items_by_owner.get(guild_id_str)
             if guild_owner_cache and owner_id_str in guild_owner_cache:
                  guild_owner_cache[owner_id_str].discard(item_id_str) # Remove ID from the set
                  # Clean up empty sets/dicts
                  if not guild_owner_cache[owner_id_str]:
                       guild_owner_cache.pop(owner_id_str)
                       if not guild_owner_cache:
                            self._items_by_owner.pop(guild_id_str, None)
                  # print(f"ItemManager: Removed item {item_id_str} from owner lookup for {owner_id_str} in guild {guild_id_str}.") # Debug


        # Remove from location lookup cache if it was there
        if location_id is not None:
             location_id_str = str(location_id)
             guild_location_cache = self._items_by_location.get(guild_id_str)
             if guild_location_cache and location_id_str in guild_location_cache:
                  guild_location_cache[location_id_str].discard(item_id_str) # Remove ID from the set
                  # Clean up empty sets/dicts
                  if not guild_location_cache[location_id_str]:
                       guild_location_cache.pop(location_id_str)
                       if not guild_location_cache:
                            self._items_by_location.pop(guild_id_str, None)
                  # print(f"ItemManager: Removed item {item_id_str} from location lookup for {location_id_str} in guild {guild_id_str}.") # Debug


# --- Конец класса ItemManager ---


print("DEBUG: item_manager.py module loaded.")
