# bot/game/managers/item_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
# Импорт базовых типов
# ИСПРАВЛЕНИЕ: Импортируем необходимые типы из typing
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union

# Импорт модели Item (для аннотаций и работы с объектами при runtime)
from bot.game.models.item import Item # Прямой импорт

# Адаптер БД
from bot.database.sqlite_adapter import SqliteAdapter

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins


if TYPE_CHECKING:
    # Чтобы не создавать циклических импортов, импортируем эти типы только для подсказок
    # Используем строковые литералы ("ClassName")
    from bot.game.managers.location_manager import LocationManager
    from bot.game.rules.rule_engine import RuleEngine
    # Add managers/processors that might be in context kwargs
    # from bot.game.managers.character_manager import CharacterManager
    # from bot.game.managers.npc_manager import NpcManager
    # from bot.game.managers.combat_manager import CombatManager
    # from bot.game.managers.status_manager import StatusManager
    # from bot.game.managers.party_manager import PartyManager
    # from bot.game.managers.time_manager import TimeManager


class ItemManager:
    """
    Менеджер для создания, хранения и персистенции предметов.
    Работает на основе guild_id для многогильдийной поддержки.
    Хранит статические шаблоны (per-guild) и кеш экземпляров (per-guild).
    """
    # Required args для PersistenceManager
    required_args_for_load: List[str] = ["guild_id"] # Загрузка per-guild
    required_args_for_save: List[str] = ["guild_id"] # Сохранение per-guild
    required_args_for_rebuild: List[str] = ["guild_id"] # Rebuild per-guild


    # --- Class-Level Attribute Annotations ---
    # Кеш экземпляров предметов: {guild_id: {item_id: Item_object}}
    # ИСПРАВЛЕНИЕ: Кеш экземпляров должен быть per-guild
    _items: Dict[str, Dict[str, "Item"]] # Аннотация кеша использует строковый литерал "Item"

    # Статические шаблоны предметов: {guild_id: {template_id: data_dict}}
    # ИСПРАВЛЕНИЕ: Шаблоны также должны быть per-guild
    _item_templates: Dict[str, Dict[str, Dict[str, Any]]]

    # Изменённые экземпляры, подлежащие записи: {guild_id: set(item_ids)}
    # ИСПРАВЛЕНИЕ: dirty items также per-guild
    _dirty_items: Dict[str, Set[str]]

    # Удалённые экземпляры, подлежащие удалению из БД: {guild_id: set(item_ids)}
    # ИСПРАВЛЕНИЕ: deleted item ids также per-guild
    _deleted_item_ids: Dict[str, Set[str]]


    def __init__(
        self,
        # Используем строковые литералы для всех опциональных зависимостей
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        location_manager: Optional["LocationManager"] = None, # Use string literal!
        rule_engine: Optional["RuleEngine"] = None, # Use string literal!
        # Add other injected dependencies here with Optional and string literals
        # Example: character_manager: Optional["CharacterManager"] = None,
    ):
        print("Initializing ItemManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        # Store other managers if injected and needed in cleanup methods, etc.
        # self._character_manager = character_manager


        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые outer словари
        # Кеш экземпляров предметов: {guild_id: {item_id: Item}}
        self._items = {} # Инициализируем как пустой dict

        # Статические шаблоны предметов: {guild_id: {template_id: data_dict}}
        self._item_templates = {} # Инициализируем как пустой dict

        # Изменённые экземпляры, подлежащие записи: {guild_id: set(item_ids)}
        self._dirty_items = {} # Инициализируем как пустой dict

        # Удалённые экземпляры, подлежащие удалению из БД: {guild_id: set(item_ids)}
        self._deleted_item_ids = {} # Инициализируем как пустой dict

        # Загружаем статические шаблоны НЕ здесь. Загрузка per-guild происходит в load_state.
        # _load_item_templates() # Remove this call from __init__

        print("ItemManager initialized.")

    # Переименовываем _load_item_templates в load_static_templates (не вызывается PM)
    # Этот метод будет вызываться из load_state
    def load_static_templates(self, guild_id: str) -> None:
        """(Пример) Загружает статические шаблоны для определенной гильдии из настроек или файлов."""
        guild_id_str = str(guild_id)
        print(f"ItemManager: Loading item templates for guild {guild_id_str}...")

        # Очищаем кеш шаблонов для этой гильдии перед загрузкой
        self._item_templates.pop(guild_id_str, None)
        guild_templates_cache = self._item_templates.setdefault(guild_id_str, {}) # Create empty cache for this guild

        try:
            # Пример загрузки из settings (предполагаем структуру settings['guilds'][guild_id]['item_templates']
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            templates_data = guild_settings.get('item_templates')

            if templates_data is None and self._settings: # Fallback to global templates if not found in guild settings
                 # Example: load from a global JSON file defined in settings
                 global_templates_file = self._settings.get('global_item_templates_file')
                 if global_templates_file:
                      try:
                           with open(global_templates_file, 'r', encoding='utf-8') as f: # Specify encoding
                                global_templates_data = json.load(f)
                                # Assuming global_templates_data is a dict {tpl_id: data}
                                if isinstance(global_templates_data, dict):
                                     templates_data = global_templates_data
                                     print(f"ItemManager: Loaded global item templates from {global_templates_file}.")
                      except FileNotFoundError:
                           print(f"ItemManager: Warning: Global item templates file not found: {global_templates_file}")
                      except json.JSONDecodeError:
                           print(f"ItemManager: Warning: Error decoding JSON from global templates file: {global_templates_file}")
                           traceback.print_exc()
                      except Exception as e:
                           print(f"ItemManager: Warning: Error loading global item templates: {e}")
                           traceback.print_exc()


            if isinstance(templates_data, dict):
                 for tpl_id, data in templates_data.items():
                      # Basic validation
                      if tpl_id and isinstance(data, dict):
                           data.setdefault('id', str(tpl_id)) # Ensure id is in data
                           data.setdefault('name', f"Unnamed Template ({tpl_id})") # Ensure name
                           data.setdefault('properties', {}) # Ensure properties
                           guild_templates_cache[str(tpl_id)] = data # Store with string ID
                 print(f"ItemManager: Loaded {len(guild_templates_cache)} item templates for guild {guild_id_str}.")
            elif templates_data is not None:
                 print(f"ItemManager: Warning: Item templates data for guild {guild_id_str} is not a dictionary ({type(templates_data)}). Skipping template load.")
            else:
                 print(f"ItemManager: No item templates found in settings for guild {guild_id_str} or globally.")


        except Exception as e:
            print(f"ItemManager: ❌ Error loading item templates for guild {guild_id_str}: {e}")
            traceback.print_exc()
            # Decide how to handle error - should template loading failure be critical?
            # For now, log and continue with empty template cache for this guild.


    # get_item_template now needs guild_id
    def get_item_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        """Возвращает данные шаблона по его ID для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Get templates from the per-guild cache
        guild_templates = self._item_templates.get(guild_id_str, {})
        return guild_templates.get(str(template_id)) # Ensure template_id is string


    # get_item_name now needs guild_id (as item object might not have guild_id directly)
    def get_item_name(self, guild_id: str, item_id: str) -> Optional[str]:
        """
        Возвращает имя экземпляра предмета по его ID для определенной гильдии, глядя в его шаблон.
        """
        guild_id_str = str(guild_id)
        # Get item instance from the per-guild cache
        item = self.get_item(guild_id_str, item_id) # Use get_item with guild_id
        if not item:
            # print(f"ItemManager: Warning: Item instance {item_id} not found for guild {guild_id_str} when getting name.") # Too noisy?
            return f"Unknown Item Instance ({item_id})" # Return a default name if instance not found

        template_id = getattr(item, 'template_id', None) # Use getattr safely
        if template_id is None:
             print(f"ItemManager: Warning: Item instance {item_id} has no template_id for guild {guild_id_str}. Cannot get template name.")
             return f"Unnamed Item ({item_id})"

        # Get template using guild_id and template_id
        tpl = self.get_item_template(guild_id_str, template_id)
        if tpl:
            # Ensure template has a 'name' attribute and it's a string
            name = tpl.get('name')
            if isinstance(name, str) and name:
                 return name
            else:
                 print(f"ItemManager: Warning: Template '{template_id}' has invalid/missing 'name' for guild {guild_id_str}. Template data: {tpl}")
                 return f"Unnamed Item ({template_id})" # Fallback using template ID

        # If template not found
        print(f"ItemManager: Warning: Template '{template_id}' not found for item {item_id} for guild {guild_id_str} when getting name.")
        return f"Unknown Template ({template_id})" # Fallback using template ID

    # get_item now needs guild_id
    def get_item(self, guild_id: str, item_id: str) -> Optional["Item"]:
        """Возвращает экземпляр предмета из кеша для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Get items from the per-guild cache
        guild_items = self._items.get(guild_id_str) # Get per-guild cache
        if guild_items:
             return guild_items.get(str(item_id)) # Ensure item_id is string
        return None # Guild or item not found


    # create_item now needs guild_id and uses per-guild caches
    async def create_item(self, guild_id: str, item_data: Dict[str, Any], **kwargs: Any) -> Optional[str]:
        """
        Создаёт новый экземпляр предмета для определенной гильдии на основе item_data['template_id'],
        кладёт его в кеш и помечает для сохранения.
        """
        guild_id_str = str(guild_id)
        print(f"ItemManager: Creating item for guild {guild_id_str} from template '{item_data.get('template_id')}'...")

        if self._db_adapter is None:
            print(f"ItemManager: No DB adapter for guild {guild_id_str}.")
            # In multi-guild, this might require different handling
            return None

        tpl_id = item_data.get('template_id')
        if tpl_id is None:
            print(f"ItemManager: Missing 'template_id' in item_data for guild {guild_id_str}.")
            return None
        tpl_id_str = str(tpl_id)

        # Check if template exists for this guild
        template = self.get_item_template(guild_id_str, tpl_id_str)
        if template is None:
            print(f"ItemManager: Template '{tpl_id_str}' not found for guild {guild_id_str}. Cannot create item.")
            return None

        try:
            new_id = str(uuid.uuid4()) # Generate unique ID for the item instance

            # Prepare data for the Item object
            data: Dict[str, Any] = {
                'id': new_id,
                'guild_id': guild_id_str, # <--- Store guild_id with the item instance
                'template_id': tpl_id_str,
                'owner_id': item_data.get('owner_id'), # Optional owner ID (char_id, npc_id, party_id, etc.)
                'owner_type': item_data.get('owner_type'), # Optional owner type ('character', 'npc', 'location', 'party')
                'location_id': item_data.get('location_id'), # Optional location ID (if on ground)
                'quantity': item_data.get('quantity', 1), # Default quantity 1
                'is_temporary': bool(item_data.get('is_temporary', False)), # Default False
                # Initial state variables from item_data, overriding template default state if provided
                'state_variables': item_data.get('state_variables', template.get('initial_state_variables', {})),
                # Consider adding other template properties to the instance if they can change (e.g., durability)
                # 'durability': item_data.get('durability', template.get('durability', None)),
            }

            # Basic validation of quantity
            if not isinstance(data.get('quantity'), (int, float)) or data.get('quantity', 0) <= 0:
                 print(f"ItemManager: Warning: Invalid or non-positive quantity ({data.get('quantity')}) for item '{tpl_id_str}' for guild {guild_id_str}. Setting quantity to 1.")
                 data['quantity'] = 1


            # Create the Item object
            item = Item.from_dict(data) # Requires Item.from_dict


            # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш экземпляров
            self._items.setdefault(guild_id_str, {})[new_id] = item


            # ИСПРАВЛЕНИЕ: Помечаем новый экземпляр dirty (per-guild)
            self.mark_item_dirty(guild_id_str, new_id)


            print(f"ItemManager: Item instance '{new_id}' (template '{tpl_id_str}') created and marked dirty for guild {guild_id_str}.")

            # Optional: Trigger RuleEngine hook for item creation?
            # rule_engine = kwargs.get('rule_engine', self._rule_engine)
            # if rule_engine and hasattr(rule_engine, 'on_item_created'):
            #      try: await rule_engine.on_item_created(item, context=kwargs)
            #      except Exception: traceback.print_exc();

            return new_id # Return the ID of the created item instance

        except Exception as e:
            print(f"ItemManager: Error creating item from template '{tpl_id_str}' for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            return None


    # move_item now needs guild_id and uses per-guild caches
    async def move_item(
        self,
        guild_id: str, # Added guild_id
        item_id: str,
        new_owner_id: Optional[str] = None,
        new_location_id: Optional[str] = None, # Instance ID
        new_owner_type: Optional[str] = None, # Optional type of the new owner ('character', 'npc', 'location', 'party', etc.)
        **kwargs: Any
    ) -> bool:
        """
        Меняет owner_id, owner_type и/или location_id в кеше и помечает экземпляр dirty для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        print(f"ItemManager: Moving item instance {item_id} for guild {guild_id_str} → owner {new_owner_id} ({new_owner_type}), loc {new_location_id}")

        # ИСПРАВЛЕНИЕ: Получаем экземпляр предмета с учетом guild_id
        item = self.get_item(guild_id_str, item_id) # Use get_item with guild_id
        if not item or str(getattr(item, 'guild_id', None)) != guild_id_str: # Check if item exists and belongs to this guild
            print(f"ItemManager: Item instance {item_id} not found or does not belong to guild {guild_id_str}.")
            # Optional: Send feedback if a command triggered this
            return False


        # Example validation of new location (if needed)
        # loc_mgr = kwargs.get('location_manager', self._location_manager) # Get LocationManager from context or self
        # if new_location_id is not None and loc_mgr is not None and not loc_mgr.get_location_instance(guild_id_str, new_location_id): # Use loc_mgr with guild_id
        #     print(f"ItemManager: Target location instance {new_location_id} not found for guild {guild_id_str}.")
        #     # Optional: Send feedback
        #     return False

        # Update the item object's attributes
        # Ensure new_owner_id and new_location_id are strings or None
        item.owner_id = str(new_owner_id) if new_owner_id is not None else None
        item.location_id = str(new_location_id) if new_location_id is not None else None
        item.owner_type = str(new_owner_type) if new_owner_type is not None else None # Update owner type

        # Mark the item as dirty for this guild
        self.mark_item_dirty(guild_id_str, item_id) # Use method mark_item_dirty with guild_id

        print(f"ItemManager: Item instance {item_id} marked dirty after move for guild {guild_id_str}.")

        # TODO: Trigger RuleEngine hook for item movement?
        # rule_engine = kwargs.get('rule_engine', self._rule_engine)
        # if rule_engine and hasattr(rule_engine, 'on_item_moved'):
        #      try: await rule_engine.on_item_moved(item, old_owner_id, old_location_id, **kwargs) # Need old values
        #      except Exception: traceback.print_exc();

        return True


    # save_state - replaces save_all_items, works per-guild
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """
        Сохраняет все _dirty_items и удаляет те, что в _deleted_item_ids для определенной гильдии.
        Вызывается PersistenceManager.
        """
        guild_id_str = str(guild_id)
        print(f"ItemManager: Saving state for guild {guild_id_str}...")

        if self._db_adapter is None:
            print(f"ItemManager: Warning: No DB adapter available. Skipping save for guild {guild_id_str}.")
            return

        # ИСПРАВЛЕНИЕ: Получаем per-guild dirty/deleted IDs
        dirty_item_ids_set = self._dirty_items.get(guild_id_str, set()).copy() # Use a copy for safety
        deleted_item_ids_set = self._deleted_item_ids.get(guild_id_str, set()).copy() # Use a copy for safety


        if not dirty_item_ids_set and not deleted_item_ids_set:
            # print(f"ItemManager: No dirty or deleted items to save for guild {guild_id_str}.") # Too noisy
            # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, очищаем per-guild dirty/deleted сеты
            self._dirty_items.pop(guild_id_str, None)
            self._deleted_item_ids.pop(guild_id_str, None)
            return

        print(f"ItemManager: Saving {len(dirty_item_ids_set)} dirty, deleting {len(deleted_item_ids_set)} items for guild {guild_id_str}...")


        try:
            # 1. Удаляем помеченные для удаления предметы для этой гильдии
            if deleted_item_ids_set:
                ids_to_delete = list(deleted_item_ids_set)
                placeholders_del = ','.join('?' * len(ids_to_delete))
                # Ensure deleting only for this guild and these IDs
                sql_delete_batch = f"DELETE FROM items WHERE guild_id = ? AND id IN ({placeholders_del})"
                try:
                     await self._db_adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete)));
                     print(f"ItemManager: Deleted {len(ids_to_delete)} items from DB for guild {guild_id_str}.")
                     # ИСПРАВЛЕНИЕ: Очищаем per-guild deleted set after successful deletion
                     self._deleted_item_ids.pop(guild_id_str, None)
                except Exception as e:
                    print(f"ItemManager: Error deleting items for guild {guild_id_str}: {e}"); traceback.print_exc();
                    # Do NOT clear deleted set on error


            # 2. Сохраняем/обновляем измененные предметы для этой гильдии
            # Фильтруем dirty IDs on items that still exist in the per-guild cache
            guild_items_cache = self._items.get(guild_id_str, {})
            items_to_upsert_list: List["Item"] = [ itm for iid in list(dirty_item_ids_set) if (itm := guild_items_cache.get(iid)) is not None ] # Iterate over a copy of IDs

            if items_to_upsert_list:
                 print(f"ItemManager: Upserting {len(items_to_upsert_list)} items for guild {guild_id_str}...")
                 # Use correct column names based on schema (added guild_id)
                 upsert_sql = '''
                     INSERT OR REPLACE INTO items
                     (id, guild_id, template_id, owner_id, owner_type, location_id, quantity, is_temporary, state_variables)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                 '''
                 data_to_upsert = []
                 upserted_item_ids: Set[str] = set() # Track IDs successfully prepared

                 for itm in items_to_upsert_list:
                     try:
                         # Ensure item object has all required attributes
                         item_id = getattr(itm, 'id', None)
                         item_guild_id = getattr(itm, 'guild_id', None)

                         # Double check required fields and guild ID match
                         if item_id is None or str(item_guild_id) != guild_id_str:
                             print(f"ItemManager: Warning: Skipping upsert for item with invalid ID ('{item_id}') or mismatched guild ('{item_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                             continue

                         template_id = getattr(itm, 'template_id', None)
                         owner_id = getattr(itm, 'owner_id', None)
                         owner_type = getattr(itm, 'owner_type', None)
                         location_id = getattr(itm, 'location_id', None)
                         quantity = getattr(itm, 'quantity', 1)
                         is_temporary = getattr(itm, 'is_temporary', False)
                         state_variables = getattr(itm, 'state_variables', {})

                         # Ensure data types are suitable for JSON dumping / DB columns
                         if not isinstance(state_variables, dict): state_variables = {}
                         if not isinstance(quantity, (int, float)): quantity = 1

                         state_variables_json = json.dumps(state_variables)

                         data_to_upsert.append((
                             str(item_id),
                             guild_id_str, # Ensure guild_id string
                             str(template_id) if template_id is not None else None, # Ensure str or None
                             str(owner_id) if owner_id is not None else None, # Ensure str or None
                             str(owner_type) if owner_type is not None else None, # Ensure str or None
                             str(location_id) if location_id is not None else None, # Ensure str or None
                             float(quantity), # Save quantity as REAL for flexibility
                             int(bool(is_temporary)), # Save bool as integer
                             state_variables_json,
                         ))
                         upserted_item_ids.add(str(item_id)) # Track ID

                     except Exception as e:
                         print(f"ItemManager: Error preparing data for item {getattr(itm, 'id', 'N/A')} (template {getattr(itm, 'template_id', 'N/A')}, guild {getattr(itm, 'guild_id', 'N/A')}) for upsert: {e}")
                         import traceback
                         print(traceback.format_exc())
                         # This item won't be saved but remains in _dirty_items

                 if data_to_upsert:
                     try:
                         await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                         print(f"ItemManager: Successfully upserted {len(data_to_upsert)} items for guild {guild_id_str}.")
                         # Only clear dirty flags for items that were successfully processed
                         if guild_id_str in self._dirty_items:
                              self._dirty_items[guild_id_str].difference_update(upserted_item_ids)
                              # If set is empty after update, remove the guild key
                              if not self._dirty_items[guild_id_str]:
                                   del self._dirty_items[guild_id_str]

                     except Exception as e:
                         print(f"ItemManager: Error during batch upsert for guild {guild_id_str}: {e}"); traceback.print_exc();
                         # Don't clear dirty_items if batch upsert failed

            # else: print(f"ItemManager: No dirty items to save for guild {guild_id_str}.") # Too noisy


        except Exception as e:
            print(f"ItemManager: ❌ Error during saving state for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Do NOT clear dirty/deleted sets on error to allow retry.
            # raise # Re-raise if critical

        print(f"ItemManager: Save state complete for guild {guild_id_str}.")


    # load_state - replaces load_all_items, loads per-guild
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """
        Загружает все строки из таблицы items для определенной гильдии в кеш _items.
        Загружает также статические шаблоны для этой гильдии.
        """
        guild_id_str = str(guild_id)
        print(f"ItemManager: Loading state for guild {guild_id_str} (items + templates)...")

        if self._db_adapter is None:
            print(f"ItemManager: Warning: No DB adapter. Skipping item/template load for guild {guild_id_str}. It will work with empty caches.")
            # TODO: In non-DB mode, load placeholder data
            return

        # --- 1. Загрузка статических шаблонов (per-guild) ---
        # Call the helper method
        self.load_static_templates(guild_id_str)


        # --- 2. Загрузка экземпляров предметов (per-guild) ---
        # Очищаем кеш экземпляров ТОЛЬКО для этой гильдии перед загрузкой
        self._items.pop(guild_id_str, None) # Remove old cache for this guild
        self._items[guild_id_str] = {} # Create an empty cache for this guild

        # При загрузке, считаем, что все в DB "чистое", поэтому очищаем dirty/deleted для этой гильдии
        self._dirty_items.pop(guild_id_str, None)
        self._deleted_item_ids.pop(guild_id_str, None)

        rows = []
        try:
            # Execute SQL SELECT FROM items WHERE guild_id = ?
            # Use correct column names based on schema (added guild_id, owner_type, quantity)
            sql = '''
                SELECT id, guild_id, template_id, owner_id, owner_type, location_id, quantity, is_temporary, state_variables
                FROM items WHERE guild_id = ?
            '''
            rows = await self._db_adapter.fetchall(sql, (guild_id_str,)) # Filter by guild_id
            print(f"ItemManager: Found {len(rows)} items in DB for guild {guild_id_str}.")

        except Exception as e:
            print(f"ItemManager: ❌ CRITICAL ERROR executing DB fetchall for items for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Clear item cache for this guild on critical error
            self._items.pop(guild_id_str, None)
            raise # Re-raise critical error


        loaded_count = 0
        # Get the cache dict for this specific guild
        guild_items_cache = self._items[guild_id_str]

        for row in rows:
             data = dict(row)
             try:
                 # Validate and parse data
                 item_id_raw = data.get('id')
                 loaded_guild_id_raw = data.get('guild_id') # Should match guild_id_str due to WHERE clause

                 if item_id_raw is None or loaded_guild_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                     # This check is mostly redundant due to WHERE clause but safe.
                     print(f"ItemManager: Warning: Skipping item row with invalid ID ('{item_id_raw}') or mismatched guild ('{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row}.")
                     continue

                 item_id = str(item_id_raw)

                 # Parse JSON fields, handle None/malformed data gracefully
                 try:
                     data['state_variables'] = json.loads(data.get('state_variables') or '{}') if isinstance(data.get('state_variables'), (str, bytes)) else {}
                 except (json.JSONDecodeError, TypeError):
                      print(f"ItemManager: Warning: Failed to parse state_variables for item {item_id} in guild {guild_id_str}. Setting to {{}}. Data: {data.get('state_variables')}")
                      data['state_variables'] = {}

                 # Convert boolean/numeric/string types, handle potential None/malformed data
                 data['is_temporary'] = bool(data.get('is_temporary', 0)) if data.get('is_temporary') is not None else False # Default False
                 data['quantity'] = float(data.get('quantity', 1.0)) if isinstance(data.get('quantity'), (int, float)) else 1.0 # Store as float
                 data['template_id'] = str(data.get('template_id')) if data.get('template_id') is not None else None
                 data['owner_id'] = str(data.get('owner_id')) if data.get('owner_id') is not None else None
                 data['owner_type'] = str(data.get('owner_type')) if data.get('owner_type') is not None else None
                 data['location_id'] = str(data.get('location_id')) if data.get('location_id') is not None else None

                 # Update data dict with validated/converted values
                 data['id'] = item_id
                 data['guild_id'] = guild_id_str # Ensure guild_id is string


                 # Create Item object
                 item = Item.from_dict(data) # Requires Item.from_dict method

                 # Add Item object to the per-guild cache
                 guild_items_cache[item.id] = item

                 loaded_count += 1

             except Exception as e:
                 print(f"ItemManager: Error loading item {data.get('id', 'N/A')} for guild {guild_id_str}: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # Continue loop for other rows


        print(f"ItemManager: Successfully loaded {loaded_count} items into cache for guild {guild_id_str}.")
        print(f"ItemManager: Load state complete for guild {guild_id_str}.")


    # rebuild_runtime_caches - replaces existing method, works per-guild
    # Already takes guild_id and **kwargs
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """
        Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии.
        Например, кеш предметов по локации или по владельцу.
        """
        guild_id_str = str(guild_id)
        print(f"ItemManager: Rebuilding runtime caches for guild {guild_id_str}...")

        # Get all items loaded for this guild
        guild_items = self._items.get(guild_id_str, {}).values()

        # Example: Rebuild {location_id: set(item_id)} cache for this guild
        # if hasattr(self, '_items_by_location'): # Check if the attribute exists
        #      guild_items_by_location = self._items_by_location.setdefault(guild_id_str, {})
        #      guild_items_by_location.clear() # Clear old cache for this guild
        #      for item in guild_items: # Iterate through items loaded for THIS guild
        #           item_id = getattr(item, 'id', None)
        #           location_id = getattr(item, 'location_id', None)
        #           # Only add if item has ID and location_id, and location_id is a string
        #           if item_id and isinstance(location_id, str):
        #                guild_items_by_location.setdefault(location_id, set()).add(item_id) # Uses set()

        # Example: Rebuild {owner_id: set(item_id)} cache for this guild
        # if hasattr(self, '_items_by_owner'): # Check if the attribute exists
        #      guild_items_by_owner = self._items_by_owner.setdefault(guild_id_str, {})
        #      guild_items_by_owner.clear() # Clear old cache for this guild
        #      for item in guild_items: # Iterate through items loaded for THIS guild
        #           item_id = getattr(item, 'id', None)
        #           owner_id = getattr(item, 'owner_id', None)
        #           # Only add if item has ID and owner_id, and owner_id is a string
        #           if item_id and isinstance(owner_id, str):
        #                guild_items_by_owner.setdefault(owner_id, set()).add(item_id) # Uses set()

        print(f"ItemManager: Runtime caches rebuilt for guild {guild_id_str}.")

    # TODO: Implement clean_up methods called by other managers
    # For example, called by CharacterManager.remove_character, NpcManager.remove_npc, LocationManager.delete_location_instance

    # clean_up_for_entity - called by CharacterManager, NpcManager, PartyManager (or generic entity cleanup)
    # This method needs to remove items owned by this entity (e.g., destroy them or drop them).
    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
         """
         Обрабатывает очистку предметов, принадлежащих сущности (Character, NPC, Party), когда сущность удаляется.
         (Например, удаляет или бросает предметы).
         """
         # Get guild_id from context kwargs
         guild_id = kwargs.get('guild_id')
         if guild_id is None:
              print(f"ItemManager: Warning: clean_up_for_entity called for {entity_type} {entity_id} without guild_id in context. Cannot clean up items.")
              return # Cannot proceed without guild_id

         guild_id_str = str(guild_id)
         print(f"ItemManager: Cleaning up items owned by {entity_type} {entity_id} in guild {guild_id_str}...")

         # Get all items owned by this entity for this guild
         # Requires iterating through the per-guild items cache and checking owner_id/owner_type
         items_to_cleanup: List["Item"] = []
         guild_items = self._items.get(guild_id_str, {})
         for item in guild_items.values():
              if (getattr(item, 'owner_id', None) == entity_id # Check owner ID
                  and getattr(item, 'owner_type', None) == entity_type # Check owner type
                  and getattr(item, 'guild_id', None) == guild_id_str # Double check guild ID
                 ):
                   items_to_cleanup.append(item)

         if not items_to_cleanup:
              # print(f"ItemManager: No items found owned by {entity_type} {entity_id} in guild {guild_id_str} for cleanup.") # Too noisy?
              return # Nothing to clean up

         print(f"ItemManager: Found {len(items_to_cleanup)} items owned by {entity_type} {entity_id} in guild {guild_id_str}.")


         # TODO: Decide what happens to the items (delete, drop, transfer).
         # Default: Mark temporary items for deletion, drop non-temporary items at entity's location (if known).
         # Get entity's current location from context if available, or from the entity's manager/object.
         entity_location_id = kwargs.get('location_instance_id') # Try to get location from context (e.g. if entity is in location)
         if entity_location_id is None and entity_type == 'Character':
             # Try getting location from CharacterManager if available in context
             char_mgr = kwargs.get('character_manager') # type: Optional["CharacterManager"]
             if char_mgr and hasattr(char_mgr, 'get_character'):
                  # get_character now takes guild_id
                  char = char_mgr.get_character(guild_id_str, entity_id)
                  if char: entity_location_id = getattr(char, 'location_id', None)
         elif entity_location_id is None and entity_type == 'NPC':
              # Try getting location from NpcManager if available in context
              npc_mgr = kwargs.get('npc_manager') # type: Optional["NpcManager"]
              if npc_mgr and hasattr(npc_mgr, 'get_npc'):
                   # get_npc now takes guild_id
                   npc = npc_mgr.get_npc(guild_id_str, entity_id)
                   if npc: entity_location_id = getattr(npc, 'location_id', None)
         # TODO: Add logic for Party location if Parties can own items and have a location

         for item in items_to_cleanup:
             item_id = getattr(item, 'id', None)
             if not item_id: continue

             try:
                  if getattr(item, 'is_temporary', False):
                       # Mark temporary items for deletion
                       print(f"ItemManager: Marking temporary item {item_id} for deletion (owned by {entity_id}).")
                       # mark_item_deleted needs guild_id
                       self.mark_item_deleted(guild_id_str, item_id) # Mark item for deletion from DB

                  elif entity_location_id is not None:
                       # Drop non-temporary items at the entity's location
                       print(f"ItemManager: Moving non-temporary item {item_id} to location {entity_location_id} (owned by {entity_id}).")
                       # move_item needs guild_id
                       await self.move_item(
                           guild_id=guild_id_str,
                           item_id=item_id,
                           new_owner_id=None, # No owner
                           new_location_id=entity_location_id, # Drop at entity's location
                           new_owner_type=None, # No owner type
                           **kwargs # Pass context
                       )

                  else:
                       # If not temporary and no location is known, what happens? Destroy it?
                       print(f"ItemManager: Warning: Non-temporary item {item_id} owned by {entity_type} {entity_id} has no known location in guild {guild_id_str}. Marking for deletion.")
                       # Decide policy: delete it or keep it ownerless/locationless? Defaulting to deletion.
                       self.mark_item_deleted(guild_id_str, item_id) # Mark item for deletion from DB


             except Exception as e:
                  print(f"ItemManager: Error during cleanup for item {item_id} owned by {entity_id} in guild {guild_id_str}: {e}")
                  traceback.print_exc()
                  # Do not re-raise, continue cleanup for other items


         print(f"ItemManager: Cleanup of items owned by {entity_type} {entity_id} complete for guild {guild_id_str}.")


    # clean_up_for_location - called by LocationManager.delete_location_instance
    # This method needs to remove items located in this instance.
    async def clean_up_for_location(self, location_instance_id: str, **kwargs: Any) -> None:
         """
         Обрабатывает очистку предметов, находящихся в инстансе локации, когда локация удаляется.
         (Например, удаляет или перемещает предметы).
         """
         # Get guild_id from context kwargs
         guild_id = kwargs.get('guild_id')
         if guild_id is None:
              print(f"ItemManager: Warning: clean_up_for_location called for instance {location_instance_id} without guild_id in context. Cannot clean up items.")
              return # Cannot proceed without guild_id

         guild_id_str = str(guild_id)
         print(f"ItemManager: Cleaning up items located in instance {location_instance_id} in guild {guild_id_str}...")

         # Get all items located in this instance for this guild
         # Requires iterating through the per-guild items cache and checking location_id
         items_to_cleanup: List["Item"] = []
         guild_items = self._items.get(guild_id_str, {})
         for item in guild_items.values():
              if (getattr(item, 'location_id', None) == location_instance_id # Check location ID
                  and getattr(item, 'owner_id', None) is None # Only items on the ground (no owner)
                  and getattr(item, 'guild_id', None) == guild_id_str # Double check guild ID
                 ):
                   items_to_cleanup.append(item)

         if not items_to_cleanup:
              # print(f"ItemManager: No items found in location instance {location_instance_id} in guild {guild_id_str} for cleanup.") # Too noisy?
              return # Nothing to clean up

         print(f"ItemManager: Found {len(items_to_cleanup)} items in location instance {location_instance_id} in guild {guild_id_str}.")

         # TODO: Decide what happens to these items (delete, move to default location, move to GM inventory).
         # Default: Delete temporary items, move non-temporary to a default "lost and found" location (or GM inventory).
         # For simplicity now: Mark temporary for deletion, delete non-temporary too if no fallback location.
         # Get default "lost and found" location ID from settings or context?
         # location_manager = kwargs.get('location_manager', self._location_manager) # Get LocationManager from context or self
         # lost_and_found_loc_id = location_manager.get_lost_and_found_location(guild_id_str) if location_manager and hasattr(location_manager, 'get_lost_and_found_location') else None

         for item in items_to_cleanup:
             item_id = getattr(item, 'id', None)
             if not item_id: continue

             try:
                  if getattr(item, 'is_temporary', False):
                       # Mark temporary items for deletion
                       print(f"ItemManager: Marking temporary item {item_id} for deletion (in location {location_instance_id}).")
                       # mark_item_deleted needs guild_id
                       self.mark_item_deleted(guild_id_str, item_id)

                  # elif lost_and_found_loc_id is not None:
                       # Move non-temporary items to the default lost & found location
                       # print(f"ItemManager: Moving non-temporary item {item_id} from {location_instance_id} to {lost_and_found_loc_id}.")
                       # await self.move_item(
                       #     guild_id=guild_id_str,
                       #     item_id=item_id,
                       #     new_owner_id=None,
                       #     new_location_id=lost_and_found_loc_id,
                       #     new_owner_type='location', # Mark location as owner type?
                       #     **kwargs
                       # )

                  else:
                       # No L&F location, delete non-temporary items too
                       print(f"ItemManager: Warning: No lost & found location for guild {guild_id_str}. Non-temporary item {item_id} from {location_instance_id} marking for deletion.")
                       self.mark_item_deleted(guild_id_str, item_id) # Mark item for deletion

             except Exception as e:
                  print(f"ItemManager: Error during cleanup for item {item_id} in location {location_instance_id} in guild {guild_id_str}: {e}")
                  traceback.print_exc()
                  # Do not re-raise, continue cleanup for other items

         print(f"ItemManager: Cleanup of items located in instance {location_instance_id} complete for guild {guild_id_str}.")


    # mark_item_dirty needs guild_id
    def mark_item_dirty(self, guild_id: str, item_id: str) -> None:
         """Помечает экземпляр предмета как измененный для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         item_id_str = str(item_id)
         # Check if the item ID exists in the per-guild items cache
         guild_items_cache = self._items.get(guild_id_str)
         if guild_items_cache and item_id_str in guild_items_cache:
              # Add to the per-guild dirty set
              self._dirty_items.setdefault(guild_id_str, set()).add(item_id_str)
         # else: print(f"ItemManager: Warning: Attempted to mark non-existent item {item_id_str} in guild {guild_id_str} as dirty.") # Too noisy?


    # mark_item_deleted needs guild_id
    # Called by remove_item methods or cleanup methods.
    def mark_item_deleted(self, guild_id: str, item_id: str) -> None:
        """Помечает экземпляр предмета как удаленный для определенной гильдии."""
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)

        # Check if item exists in the per-guild cache
        guild_items_cache = self._items.get(guild_id_str)
        if guild_items_cache and item_id_str in guild_items_cache:
            # Remove from per-guild cache
            del guild_items_cache[item_id_str]
            print(f"ItemManager: Removed item instance {item_id_str} from cache for guild {guild_id_str}.")

            # Add to per-guild deleted set
            self._deleted_item_ids.setdefault(guild_id_str, set()).add(item_id_str) # uses set()

            # Remove from per-guild dirty set if it was there
            self._dirty_items.get(guild_id_str, set()).discard(item_id_str) # uses set()

            print(f"ItemManager: Item instance {item_id_str} marked for deletion for guild {guild_id_str}.")

        # Handle case where item was already deleted but mark_deleted is called again
        elif guild_id_str in self._deleted_item_ids and item_id_str in self._deleted_item_ids[guild_id_str]:
             print(f"ItemManager: Item instance {item_id_str} in guild {guild_id_str} already marked for deletion.")
        else:
             print(f"ItemManager: Warning: Attempted to mark non-existent item {item_id_str} in guild {guild_id_str} as deleted.")


# TODO: Implement remove_items_by_owner(owner_id, owner_type, guild_id, **context)
# This is called by entity managers (Char, NPC, Party) clean_up_for_entity
async def remove_items_by_owner(self, owner_id: str, owner_type: str, guild_id: str, **kwargs: Any) -> None:
     """
     Удаляет все предметы, принадлежащие указанному владельцу, для определенной гильдии.
     (Например, при смерти персонажа или удалении NPC).
     """
     guild_id_str = str(guild_id)
     print(f"ItemManager: Removing items owned by {owner_type} {owner_id} in guild {guild_id_str}...")

     # Get all items owned by this entity for this guild
     # Requires iterating through the per-guild items cache and checking owner_id/owner_type
     items_to_remove: List["Item"] = []
     guild_items = self._items.get(guild_id_str, {})
     for item in guild_items.values():
          # Check owner ID, owner type, and guild ID match
          if (getattr(item, 'owner_id', None) == owner_id
              and getattr(item, 'owner_type', None) == owner_type
              and getattr(item, 'guild_id', None) == guild_id_str
             ):
               items_to_remove.append(item)

     if not items_to_remove:
          # print(f"ItemManager: No items found owned by {owner_type} {owner_id} in guild {guild_id_str} for removal.") # Too noisy?
          return # Nothing to remove

     print(f"ItemManager: Found {len(items_to_remove)} items owned by {owner_type} {owner_id} in guild {guild_id_str} for removal.")

     # Mark each found item for deletion
     for item in items_to_remove:
          item_id = getattr(item, 'id', None)
          if item_id:
               try:
                    # mark_item_deleted needs guild_id
                    self.mark_item_deleted(guild_id_str, item_id) # Mark item for deletion from DB
                    print(f"ItemManager: Marked item {item_id} for deletion (owned by {owner_id}).")
               except Exception as e:
                    print(f"ItemManager: Error marking item {item_id} for deletion (owned by {owner_id}) in guild {guild_id_str}: {e}")
                    traceback.print_exc()
                    # Do not re-raise, continue


     print(f"ItemManager: Removal of items owned by {owner_type} {owner_id} complete for guild {guild_id_str}.")


# TODO: Implement remove_items_by_location(location_id, guild_id, **context)
# This is called by LocationManager.delete_location_instance
async def remove_items_by_location(self, location_id: str, guild_id: str, **kwargs: Any) -> None:
     """
     Удаляет все предметы, находящиеся в указанном инстансе локации, для определенной гильдии.
     (Например, при удалении локации).
     """
     guild_id_str = str(guild_id)
     print(f"ItemManager: Removing items located in instance {location_id} in guild {guild_id_str}...")

     # Get all items located in this instance for this guild
     # Requires iterating through the per-guild items cache and checking location_id
     items_to_remove: List["Item"] = []
     guild_items = self._items.get(guild_id_str, {})
     for item in guild_items.values():
          # Check location ID and guild ID match, and ensure it has no owner (on the ground)
          if (getattr(item, 'location_id', None) == location_id
              and getattr(item, 'guild_id', None) == guild_id_str
              and getattr(item, 'owner_id', None) is None # Only items on the ground
             ):
               items_to_remove.append(item)

     if not items_to_remove:
          # print(f"ItemManager: No items found in location instance {location_id} in guild {guild_id_str} for removal.") # Too noisy?
          return # Nothing to remove

     print(f"ItemManager: Found {len(items_to_remove)} items in location instance {location_id} in guild {guild_id_str} for removal.")

     # Mark each found item for deletion
     for item in items_to_remove:
          item_id = getattr(item, 'id', None)
          if item_id:
               try:
                    # mark_item_deleted needs guild_id
                    self.mark_item_deleted(guild_id_str, item_id) # Mark item for deletion from DB
                    print(f"ItemManager: Marked item {item_id} for deletion (in location {location_id}).")
               except Exception as e:
                    print(f"ItemManager: Error marking item {item_id} for deletion (in location {location_id}) in guild {guild_id_str}: {e}")
                    traceback.print_exc()
                    # Do not re-raise, continue

     print(f"ItemManager: Removal of items located in instance {location_id} complete for guild {guild_id_str}.")

# TODO: Implement clean_up_for_combat(combat_id, guild_id, **context)
# Called by CombatManager.end_combat if needed (e.g., removing temporary combat loot)
# async def clean_up_for_combat(self, combat_id: str, guild_id: str, **kwargs: Any) -> None: ...


# TODO: Implement drop_all_inventory(entity_id, entity_type, location_id, guild_id, **context)
# Called by entity managers (Character, NPC) clean_up_on_death
# Should move items from entity's inventory to the specified location_id
# async def drop_all_inventory(self, entity_id: str, entity_type: str, location_id: str, guild_id: str, **kwargs: Any) -> None: ...

# --- Конец класса ItemManager ---

print("DEBUG: item_manager.py module loaded.")