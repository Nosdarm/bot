# bot/game/managers/item_manager.py
from __future__ import annotations # Enables using type hints as strings implicitly, simplifying things
import json
import uuid
import traceback
import asyncio

# Import typing components
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float

# --- Imports needed ONLY for Type Checking ---
if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.models.item import Item
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.crafting_manager import CraftingManager

# --- Imports needed at Runtime ---
from bot.game.models.item import Item # Ensure Item model is imported for runtime instantiation

print("DEBUG: item_manager.py module loaded.")


class ItemManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    _item_templates: Dict[str, Dict[str, Any]]
    _items: Dict[str, Dict[str, "Item"]] # Stores Item objects

    _items_by_owner: Dict[str, Dict[str, Set[str]]]
    _items_by_location: Dict[str, Dict[str, Set[str]]]
    _dirty_items: Dict[str, Set[str]]
    _deleted_items: Dict[str, Set[str]]

    def __init__(
        self,
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        economy_manager: Optional["EconomyManager"] = None,
        crafting_manager: Optional["CraftingManager"] = None,
    ):
        print("Initializing ItemManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._location_manager = location_manager
        self._party_manager = party_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._economy_manager = economy_manager
        self._crafting_manager = crafting_manager

        self._item_templates = {}
        self._items = {}
        self._items_by_owner = {}
        self._items_by_location = {}
        self._dirty_items = {}
        self._deleted_items = {}

        self._load_item_templates()
        print("ItemManager initialized.")

    def _load_item_templates(self):
        print("ItemManager: Loading global item templates...")
        self._item_templates = {}
        try:
            if self._settings and 'item_templates' in self._settings and isinstance(self._settings['item_templates'], dict):
                self._item_templates = self._settings['item_templates']
                # Basic validation for each template
                for tpl_id, data in self._item_templates.items():
                    if not isinstance(data, dict):
                        print(f"ItemManager: Warning - Template data for {tpl_id} is not a dict. Removing.")
                        # self._item_templates.pop(tpl_id) # Cannot modify during iteration this way
                        continue # Or handle error more gracefully
                    data.setdefault('id', tpl_id) # Ensure template has its ID
                    data.setdefault('name', f"Unnamed Item ({tpl_id})")
                    data.setdefault('description', "")
                    data.setdefault('type', "misc")
                    data.setdefault('properties', {})

                loaded_count = len(self._item_templates)
                print(f"ItemManager: Successfully loaded {loaded_count} item templates from settings.")
            else:
                print("ItemManager: No item templates found in settings or 'item_templates' is not a dict.")
        except Exception as e:
            print(f"ItemManager: Error loading item templates from settings: {e}")
            traceback.print_exc()

    def get_item_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        return self._item_templates.get(str(template_id))

    def get_item_instance(self, guild_id: str, item_id: str) -> Optional["Item"]:
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        return self._items.get(guild_id_str, {}).get(item_id_str)

    def get_all_item_instances(self, guild_id: str) -> List["Item"]:
        guild_id_str = str(guild_id)
        return list(self._items.get(guild_id_str, {}).values())

    def get_items_by_owner(self, guild_id: str, owner_id: str) -> List["Item"]:
        guild_id_str = str(guild_id)
        owner_id_str = str(owner_id)
        owner_item_ids = self._items_by_owner.get(guild_id_str, {}).get(owner_id_str, set())
        guild_items_cache = self._items.get(guild_id_str, {})
        return [item_obj for item_id in owner_item_ids if (item_obj := guild_items_cache.get(item_id)) is not None]

    def get_items_in_location(self, guild_id: str, location_id: str) -> List["Item"]:
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        location_item_ids = self._items_by_location.get(guild_id_str, {}).get(location_id_str, set())
        guild_items_cache = self._items.get(guild_id_str, {})
        return [item_obj for item_id in location_item_ids if (item_obj := guild_items_cache.get(item_id)) is not None]

    async def create_item_instance(self,
                                   guild_id: str,
                                   template_id: str,
                                   owner_id: Optional[str] = None,
                                   owner_type: Optional[str] = None,
                                   location_id: Optional[str] = None,
                                   quantity: float = 1.0,
                                   initial_state: Optional[Dict[str, Any]] = None,
                                   is_temporary: bool = False,
                                   **kwargs: Any
                                  ) -> Optional["Item"]:
        guild_id_str = str(guild_id)
        template_id_str = str(template_id)

        if self._db_adapter is None:
            print(f"ItemManager: No DB adapter for guild {guild_id_str}. Cannot create item instance.")
            return None

        template = self.get_item_template(template_id_str)
        if not template:
            print(f"ItemManager: Error creating instance: Template '{template_id_str}' not found globally.")
            return None

        if quantity <= 0:
            print(f"ItemManager: Warning creating instance: Quantity must be positive ({quantity}). Cannot create.")
            return None

        resolved_location_id: Optional[str] = str(location_id) if location_id else None
        resolved_owner_id: Optional[str] = str(owner_id) if owner_id else None
        resolved_owner_type: Optional[str] = str(owner_type) if owner_type else None

        if resolved_owner_type and resolved_owner_id and resolved_owner_type.lower() == 'location':
             resolved_location_id = resolved_owner_id
        elif resolved_owner_type is None and location_id is not None:
             resolved_location_id = str(location_id)

        new_item_id = str(uuid.uuid4())

        item_data_for_model: Dict[str, Any] = {
            'id': new_item_id,
            'guild_id': guild_id_str,
            'template_id': template_id_str,
            'quantity': float(quantity),
            'owner_id': resolved_owner_id,
            'owner_type': resolved_owner_type,
            'location_id': resolved_location_id,
            'state_variables': initial_state if initial_state is not None else {},
            'is_temporary': is_temporary
        }

        new_item = Item.from_dict(item_data_for_model)

        try:
            if not await self.save_item(new_item, guild_id_str): # save_item now handles cache update
                print(f"ItemManager: Failed to save new item {new_item_id} to DB for guild {guild_id_str}.")
                return None

            print(f"ItemManager: Item instance {new_item_id} (Template: {template_id_str}) created, saved, and cached for guild {guild_id_str}.")
            return new_item
        except Exception as e:
            print(f"ItemManager: ❌ Error during item instance creation or saving for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return None

    async def remove_item_instance(self, guild_id: str, item_id: str, **kwargs: Any) -> bool:
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        item_to_remove = self.get_item_instance(guild_id_str, item_id_str)

        if not item_to_remove:
            if guild_id_str in self._deleted_items and item_id_str in self._deleted_items[guild_id_str]:
                 return True
            return False

        try:
            if self._db_adapter:
                sql = 'DELETE FROM items WHERE id = ? AND guild_id = ?'
                await self._db_adapter.execute(sql, (item_id_str, guild_id_str))

            guild_items_cache = self._items.get(guild_id_str, {})
            if item_id_str in guild_items_cache:
                 del guild_items_cache[item_id_str]
                 if not guild_items_cache:
                      self._items.pop(guild_id_str, None)

            self._update_lookup_caches_remove(guild_id_str, item_to_remove.to_dict())
            self._dirty_items.get(guild_id_str, set()).discard(item_id_str)
            self._deleted_items.setdefault(guild_id_str, set()).add(item_id_str)
            return True
        except Exception as e:
            print(f"ItemManager: ❌ Error removing item instance {item_id_str} for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return False

    async def update_item_instance(self, guild_id: str, item_id: str, updates: Dict[str, Any], **kwargs: Any) -> bool:
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        item_object = self.get_item_instance(guild_id_str, item_id_str)

        if not item_object:
            return False

        old_item_dict_for_lookup = item_object.to_dict() # For lookup cache removal

        # Apply updates to the Item object's attributes
        for key, value in updates.items():
            if hasattr(item_object, key):
                if key == 'state_variables' and isinstance(value, dict):
                    current_state = getattr(item_object, key, {})
                    if not isinstance(current_state, dict) : current_state = {}
                    current_state.update(value)
                    setattr(item_object, key, current_state)
                else:
                    setattr(item_object, key, value)
            else:
                print(f"ItemManager: Warning - Attempted to update unknown attribute {key} for item {item_id_str}")

        # Recalculate if owner/location changed for lookup caches
        new_item_dict_for_lookup = item_object.to_dict()
        owner_changed = old_item_dict_for_lookup.get('owner_id') != new_item_dict_for_lookup.get('owner_id') or \
                        old_item_dict_for_lookup.get('owner_type') != new_item_dict_for_lookup.get('owner_type')
        location_changed = old_item_dict_for_lookup.get('location_id') != new_item_dict_for_lookup.get('location_id')

        if owner_changed or location_changed:
            self._update_lookup_caches_remove(guild_id_str, old_item_dict_for_lookup)
            self._update_lookup_caches_add(guild_id_str, new_item_dict_for_lookup)

        self.mark_item_dirty(guild_id_str, item_id_str)
        return True

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_adapter is None:
             self._clear_guild_state_cache(guild_id_str)
             return

        self._clear_guild_state_cache(guild_id_str)
        guild_items_cache = self._items[guild_id_str]

        try:
            sql_items = 'SELECT id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary FROM items WHERE guild_id = ?'
            rows_items = await self._db_adapter.fetchall(sql_items, (guild_id_str,))
            loaded_count = 0
            for row in rows_items:
                try:
                    item_data_dict: Dict[str, Any] = {
                       'id': row['id'],
                       'template_id': str(row['template_id']) if row['template_id'] is not None else None,
                       'guild_id': str(row['guild_id']),
                       'owner_id': str(row['owner_id']) if row['owner_id'] is not None else None,
                       'owner_type': str(row['owner_type']) if row['owner_type'] is not None else None,
                       'location_id': str(row['location_id']) if row['location_id'] is not None else None,
                       'quantity': float(row['quantity']) if row['quantity'] is not None else 1.0,
                       'state_variables': json.loads(row['state_variables'] or '{}') if isinstance(row['state_variables'], (str, bytes)) else {},
                       'is_temporary': bool(row['is_temporary'])
                    }
                    if item_data_dict['template_id'] is None or item_data_dict['guild_id'] != guild_id_str:
                        continue

                    item_object = Item.from_dict(item_data_dict)
                    guild_items_cache[item_object.id] = item_object
                    loaded_count += 1
                    self._update_lookup_caches_add(guild_id_str, item_object.to_dict())
                except Exception as e:
                   print(f"ItemManager: ❌ Error processing item row ID {row['id'] if row and 'id' in row else 'Unknown'}: {e}")
                   traceback.print_exc()
            print(f"ItemManager: Loaded {loaded_count} item instances for guild {guild_id_str}.")
        except Exception as e:
            print(f"ItemManager: ❌ CRITICAL ERROR loading items for guild {guild_id_str}: {e}")
            self._clear_guild_state_cache(guild_id_str)
            raise

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_adapter is None: return

        dirty_ids = self._dirty_items.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_items.get(guild_id_str, set()).copy()

        if not dirty_ids and not deleted_ids:
            self._dirty_items.pop(guild_id_str, None)
            self._deleted_items.pop(guild_id_str, None)
            return

        if deleted_ids:
            placeholders = ','.join(['?'] * len(deleted_ids))
            sql_delete = f"DELETE FROM items WHERE guild_id = ? AND id IN ({placeholders})"
            try:
                await self._db_adapter.execute(sql_delete, (guild_id_str, *list(deleted_ids)))
                self._deleted_items.pop(guild_id_str, None)
            except Exception as e: print(f"ItemManager: Error deleting items: {e}")

        items_to_upsert = [obj.to_dict() for id_str in dirty_ids if (obj := self._items.get(guild_id_str, {}).get(id_str))]

        if items_to_upsert:
            upsert_sql = '''
            INSERT OR REPLACE INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            data_tuples = []
            processed_ids = set()
            for item_data in items_to_upsert:
                try:
                    data_tuples.append((
                        item_data['id'], item_data['template_id'], item_data['guild_id'],
                        item_data['owner_id'], item_data['owner_type'], item_data['location_id'],
                        item_data['quantity'], json.dumps(item_data['state_variables']),
                        int(bool(item_data['is_temporary']))
                    ))
                    processed_ids.add(item_data['id'])
                except Exception as e: print(f"ItemManager: Error preparing item {item_data.get('id')} for save: {e}")

            if data_tuples:
                try:
                    await self._db_adapter.execute_many(upsert_sql, data_tuples)
                    if guild_id_str in self._dirty_items:
                        self._dirty_items[guild_id_str].difference_update(processed_ids)
                        if not self._dirty_items[guild_id_str]: del self._dirty_items[guild_id_str]
                except Exception as e: print(f"ItemManager: Error batch upserting items: {e}")
        print(f"ItemManager: Save state complete for guild {guild_id_str}.")

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
         guild_id_str = str(guild_id)
         self._items_by_owner.pop(guild_id_str, None)
         self._items_by_owner[guild_id_str] = {}
         self._items_by_location.pop(guild_id_str, None)
         self._items_by_location[guild_id_str] = {}

         guild_items_cache = self._items.get(guild_id_str, {})
         for item_id, item_obj in guild_items_cache.items(): # item_obj is Item
              self._update_lookup_caches_add(guild_id_str, item_obj.to_dict()) # Helper expects dict
         print(f"ItemManager: Runtime caches rebuilt for guild {guild_id_str}.")

    async def clean_up_for_character(self, character_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
         guild_id = context.get('guild_id')
         if not guild_id: return
         # ... (rest of method needs to use Item objects, not dicts) ...
         # Example for dropping: if item_obj in items_to_clean: (item_obj is Item)
         #   await self.update_item_instance(guild_id_str, item_obj.id, updates_dict)
         # This method needs significant rewrite if items_to_clean returns List[Item]
         # For now, assuming previous dict logic and focusing on get_location_instance call
         loc_mgr = context.get('location_manager', self._location_manager)
         char_loc_id = context.get('location_instance_id')
         # ...
         if loc_mgr and hasattr(loc_mgr, 'get_location_instance') and char_loc_id:
              drop_location_instance = loc_mgr.get_location_instance(str(guild_id), str(char_loc_id)) # Corrected call
         # ...
         # The loop `for item_data in list(items_to_clean):` will now be `for item_obj in list(items_to_clean):`
         # and `item_id = item_obj.id`. `updates` for `update_item_instance` will change Item object attributes.

    async def clean_up_for_npc(self, npc_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
         guild_id = context.get('guild_id')
         if not guild_id: return
         # ... (similar to clean_up_for_character, needs rewrite for Item objects) ...
         loc_mgr = context.get('location_manager', self._location_manager)
         npc_loc_id = context.get('location_instance_id')
         # ...
         if loc_mgr and hasattr(loc_mgr, 'get_location_instance') and npc_loc_id:
             drop_location_instance = loc_mgr.get_location_instance(str(guild_id), str(npc_loc_id)) # Corrected call
         # ...

    async def remove_items_by_location(self, location_id: str, guild_id: str, **kwargs: Any) -> None:
         guild_id_str = str(guild_id)
         location_id_str = str(location_id)
         items_to_remove = self.get_items_in_location(guild_id_str, location_id_str) # Returns List[Item]
         for item_obj in list(items_to_remove): # item_obj is Item
              await self.remove_item_instance(guild_id_str, item_obj.id, **kwargs)

    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        self._items.pop(guild_id_str, None)
        self._items[guild_id_str] = {}
        self._items_by_owner.pop(guild_id_str, None)
        self._items_by_owner[guild_id_str] = {}
        self._items_by_location.pop(guild_id_str, None)
        self._items_by_location[guild_id_str] = {}
        self._dirty_items.pop(guild_id_str, None)
        self._deleted_items.pop(guild_id_str, None)
        # print(f"ItemManager: Cleared per-guild caches for guild {guild_id_str}.") # Reduced noise

    def mark_item_dirty(self, guild_id: str, item_id: str) -> None:
         guild_id_str = str(guild_id)
         item_id_str = str(item_id)
         if guild_id_str in self._items and item_id_str in self._items[guild_id_str]:
              self._dirty_items.setdefault(guild_id_str, set()).add(item_id_str)

    def _update_lookup_caches_add(self, guild_id: str, item_data: Dict[str, Any]) -> None: # Expects dict
        guild_id_str = str(guild_id)
        item_id_str = str(item_data.get('id'))
        owner_id = item_data.get('owner_id')
        location_id = item_data.get('location_id')
        if owner_id is not None:
             self._items_by_owner.setdefault(guild_id_str, {}).setdefault(str(owner_id), set()).add(item_id_str)
        if location_id is not None:
             self._items_by_location.setdefault(guild_id_str, {}).setdefault(str(location_id), set()).add(item_id_str)

    def _update_lookup_caches_remove(self, guild_id: str, item_data: Dict[str, Any]) -> None: # Expects dict
        guild_id_str = str(guild_id)
        item_id_str = str(item_data.get('id'))
        owner_id = item_data.get('owner_id')
        location_id = item_data.get('location_id')
        if owner_id is not None:
             owner_id_str = str(owner_id)
             guild_owner_cache = self._items_by_owner.get(guild_id_str)
             if guild_owner_cache and owner_id_str in guild_owner_cache:
                  guild_owner_cache[owner_id_str].discard(item_id_str)
                  if not guild_owner_cache[owner_id_str]:
                       guild_owner_cache.pop(owner_id_str)
                       if not guild_owner_cache: self._items_by_owner.pop(guild_id_str, None)
        if location_id is not None:
             location_id_str = str(location_id)
             guild_location_cache = self._items_by_location.get(guild_id_str)
             if guild_location_cache and location_id_str in guild_location_cache:
                  guild_location_cache[location_id_str].discard(item_id_str)
                  if not guild_location_cache[location_id_str]:
                       guild_location_cache.pop(location_id_str)
                       if not guild_location_cache: self._items_by_location.pop(guild_id_str, None)

    async def save_item(self, item: "Item", guild_id: str) -> bool:
        if self._db_adapter is None: return False
        guild_id_str = str(guild_id)
        item_id = getattr(item, 'id', None)
        if not item_id: return False
        if str(getattr(item, 'guild_id', None)) != guild_id_str: return False # Item must have guild_id matching context

        try:
            item_data_from_model = item.to_dict()
            db_params = (
                item_data_from_model.get('id'), item_data_from_model.get('template_id'),
                guild_id_str, # Use guild_id_str from context
                item_data_from_model.get('owner_id'), item_data_from_model.get('owner_type'),
                item_data_from_model.get('location_id'),
                float(item_data_from_model.get('quantity', 1.0)),
                json.dumps(item_data_from_model.get('state_variables', {})),
                int(bool(item_data_from_model.get('is_temporary', False)))
            )
            upsert_sql = '''
            INSERT OR REPLACE INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'''
            await self._db_adapter.execute(upsert_sql, db_params)

            guild_dirty_set = self._dirty_items.get(guild_id_str)
            if guild_dirty_set:
                guild_dirty_set.discard(item_id)
                if not guild_dirty_set: del self._dirty_items[guild_id_str]

            self._items.setdefault(guild_id_str, {})[item_id] = item # Store Item object

            item_as_dict_for_lookup = item.to_dict()
            self._update_lookup_caches_remove(guild_id_str, item_as_dict_for_lookup)
            self._update_lookup_caches_add(guild_id_str, item_as_dict_for_lookup)
            return True
        except Exception as e:
            print(f"ItemManager: Error saving item {item_id} for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return False

print("DEBUG: item_manager.py module loaded.")
