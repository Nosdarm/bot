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
    from bot.services.db_service import DBService # Changed
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
    from bot.game.managers.game_log_manager import GameLogManager # Added for logging

# --- Imports needed at Runtime ---
from bot.game.models.item import Item # Ensure Item model is imported for runtime instantiation
from bot.utils.i18n_utils import get_i18n_text # For new display methods

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
        db_service: Optional["DBService"] = None, # Changed
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
        game_log_manager: Optional["GameLogManager"] = None, # Added game_log_manager
    ):
        print("Initializing ItemManager...")
        self._db_service = db_service # Changed
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
        self._game_log_manager = game_log_manager # Store game_log_manager

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
        self._item_templates = {} # Clear global template cache

        # The settings data should ideally provide name_i18n and description_i18n as dictionaries.
        try:
            if self._settings and 'item_templates' in self._settings and isinstance(self._settings['item_templates'], dict):
                processed_templates = {}
                # Assuming default_language might come from general settings, not item-specific settings.
                # This default_lang is used for backward compatibility conversion.
                default_lang_setting = self._settings.get('game_rules', {}).get('default_bot_language', 'en')

                for template_id, template_data_orig in self._settings['item_templates'].items():
                    template_data = template_data_orig.copy() # Work on a copy
                    template_data['id'] = template_id # Ensure id is part of template data

                    # Ensure name_i18n is a dict, converting from 'name' if necessary
                    if not isinstance(template_data.get('name_i18n'), dict):
                        if 'name' in template_data and isinstance(template_data['name'], str):
                            template_data['name_i18n'] = {default_lang_setting: template_data['name']}
                            # print(f"ItemManager: Converted 'name' to 'name_i18n' for template {template_id}")
                        else: # Fallback if no 'name' or 'name_i18n'
                            template_data['name_i18n'] = {default_lang_setting: template_id}

                    # Ensure description_i18n is a dict, converting from 'description' if necessary
                    if not isinstance(template_data.get('description_i18n'), dict):
                        if 'description' in template_data and isinstance(template_data['description'], str):
                            template_data['description_i18n'] = {default_lang_setting: template_data['description']}
                        else: # Fallback for description
                            template_data['description_i18n'] = {default_lang_setting: "An item of unclear nature."}

                    # Optional: Keep a plain 'name' and 'description' field for direct access using default lang,
                    # but primary access should use the new i18n methods.
                    # For example, to keep 'name':
                    # name_i18n_dict = template_data['name_i18n']
                    # template_data['name'] = name_i18n_dict.get(default_lang_setting, list(name_i18n_dict.values())[0] if name_i18n_dict else template_id)

                    template_data.setdefault('type', "misc")
                    template_data.setdefault('properties', {})
                    processed_templates[template_id] = template_data

                self._item_templates = processed_templates
                loaded_count = len(self._item_templates)
                print(f"ItemManager: Successfully loaded and processed {loaded_count} item templates from settings.")

                # Example logging (optional)
                # if loaded_count > 0:
                #     print("ItemManager: Example item templates loaded (displaying first entry's name_i18n):")
                #     first_tpl_id, first_tpl_data = next(iter(self._item_templates.items()))
                #     print(f"  - ID: {first_tpl_id}, Name_i18n: {first_tpl_data.get('name_i18n')}, Type: {first_tpl_data.get('type', 'N/A')}")

            else:
                print("ItemManager: No item templates found in settings or 'item_templates' is not a dict.")
        except Exception as e:
            print(f"ItemManager: Error loading item templates from settings: {e}")
            traceback.print_exc()

    def get_item_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        return self._item_templates.get(str(template_id))

    def get_item_template_display_name(self, template_id: str, lang: str, default_lang: str = "en") -> str:
        """Gets the internationalized display name for an item template."""
        template = self.get_item_template(template_id)
        if not template:
            return f"Item template '{template_id}' not found"

        # get_i18n_text expects the dict containing 'name_i18n' and optionally 'name'
        # The template itself is this dict.
        return get_i18n_text(template, "name", lang, default_lang)

    def get_item_template_display_description(self, template_id: str, lang: str, default_lang: str = "en") -> str:
        """Gets the internationalized display description for an item template."""
        template = self.get_item_template(template_id)
        if not template:
            return f"Item template '{template_id}' not found"

        return get_i18n_text(template, "description", lang, default_lang)

    def get_item_instance(self, guild_id: str, item_id: str) -> Optional["Item"]:
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        return self._items.get(guild_id_str, {}).get(item_id_str)

    async def get_all_item_instances(self, guild_id: str) -> List["Item"]: # Changed to async
        guild_id_str = str(guild_id)
        return list(self._items.get(guild_id_str, {}).values())

    async def get_items_by_owner(self, guild_id: str, owner_id: str) -> List["Item"]: # Changed to async
        guild_id_str = str(guild_id)
        owner_id_str = str(owner_id)
        owner_item_ids = self._items_by_owner.get(guild_id_str, {}).get(owner_id_str, set())
        guild_items_cache = self._items.get(guild_id_str, {})
        return [item_obj for item_id in owner_item_ids if (item_obj := guild_items_cache.get(item_id)) is not None]

    async def get_items_in_location(self, guild_id: str, location_id: str) -> List["Item"]: # Changed to async
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

        if self._db_service is None or self._db_service.adapter is None: # Changed
            print(f"ItemManager: No DB service or adapter for guild {guild_id_str}. Cannot create item instance.")
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

            # Log creation for undo
            if self._game_log_manager:
                revert_data = {"item_id": new_item.id}
                log_details = {
                    "action_type": "ITEM_INSTANCE_CREATE",
                    "item_id": new_item.id,
                    "template_id": new_item.template_id,
                    "owner_id": new_item.owner_id,
                    "owner_type": new_item.owner_type,
                    "location_id": new_item.location_id,
                    "quantity": new_item.quantity,
                    "revert_data": revert_data
                }
                player_id_context = kwargs.get('player_id_context')
                asyncio.create_task(self._game_log_manager.log_event(
                    guild_id=guild_id_str,
                    event_type="ITEM_CREATED",
                    details=log_details,
                    player_id=player_id_context
                ))

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
                 # Already marked for deletion or previously deleted and handled
                 print(f"ItemManager.remove_item_instance: Item {item_id_str} already marked as deleted or not found in active cache for guild {guild_id_str}.")
                 return True # Consistent with allowing multiple calls to remove a deleted item
            print(f"ItemManager.remove_item_instance: Item {item_id_str} not found for removal in guild {guild_id_str}.")
            return False

        # Log before actual removal attempt
        if self._game_log_manager:
            revert_data = {"original_item_data": item_to_remove.to_dict()}
            log_details = {
                "action_type": "ITEM_INSTANCE_DELETE",
                "item_id": item_to_remove.id,
                "template_id": item_to_remove.template_id,
                "owner_id": item_to_remove.owner_id,
                "location_id": item_to_remove.location_id,
                "revert_data": revert_data
            }
            player_id_context = kwargs.get('player_id_context')
            # Awaiting directly as remove_item_instance is async
            await self._game_log_manager.log_event(
                guild_id=guild_id_str,
                event_type="ITEM_DELETED",
                details=log_details,
                player_id=player_id_context
            )

        try:
            if self._db_service and self._db_service.adapter: # Changed
                sql = 'DELETE FROM items WHERE id = $1 AND guild_id = $2' # Changed placeholders
                await self._db_service.adapter.execute(sql, (item_id_str, guild_id_str)) # Changed

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
            print(f"ItemManager.update_item_instance: Item {item_id_str} not found in guild {guild_id_str}.")
            return False

        old_item_dict_for_lookup = item_object.to_dict() # For lookup cache removal

        # Prepare revert_data by capturing old values *before* applying updates
        old_field_values = {}
        for key_to_update in updates.keys():
            if hasattr(item_object, key_to_update):
                old_field_values[key_to_update] = getattr(item_object, key_to_update)
                # For mutable types like dict (state_variables), a deepcopy might be better if not handled by to_dict
                if isinstance(old_field_values[key_to_update], dict):
                     old_field_values[key_to_update] = json.loads(json.dumps(old_field_values[key_to_update]))


        # Apply updates to the Item object's attributes
        for key, value in updates.items():
            if hasattr(item_object, key):
                if key == 'state_variables' and isinstance(value, dict):
                    current_state = getattr(item_object, key, {})
                    if not isinstance(current_state, dict) : current_state = {} # Ensure it's a dict
                    current_state.update(value) # Merge new state variables
                    setattr(item_object, key, current_state)
                else:
                    setattr(item_object, key, value)
            else:
                print(f"ItemManager: Warning - Attempted to update unknown attribute {key} for item {item_id_str}")

        # Log the update with revert_data
        if self._game_log_manager and old_field_values: # Only log if there were valid fields to capture for revert
            revert_data = {"item_id": item_object.id, "old_field_values": old_field_values}
            log_details = {
                "action_type": "ITEM_INSTANCE_UPDATE",
                "item_id": item_object.id,
                "updated_fields_new_values": updates, # Log the changes that were applied
                "revert_data": revert_data
            }
            player_id_context = kwargs.get('player_id_context')
            await self._game_log_manager.log_event( # Assuming update_item_instance is async
                guild_id=guild_id_str,
                event_type="ITEM_UPDATED",
                details=log_details,
                player_id=player_id_context
            )

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

    async def revert_item_creation(self, guild_id: str, item_id: str, **kwargs: Any) -> bool:
        """Reverts the creation of an item by removing its instance."""
        print(f"ItemManager.revert_item_creation: Attempting to remove item {item_id} for guild {guild_id}.")
        success = await self.remove_item_instance(guild_id, item_id, **kwargs)
        if success:
            print(f"ItemManager.revert_item_creation: Successfully removed item {item_id} for guild {guild_id}.")
        else:
            print(f"ItemManager.revert_item_creation: Failed to remove item {item_id} for guild {guild_id}.")
        return success

    async def revert_item_deletion(self, guild_id: str, item_data: Dict[str, Any], **kwargs: Any) -> bool:
        """Reverts the deletion of an item by recreating it from its data."""
        item_id_to_recreate = item_data.get('id')
        if not item_id_to_recreate:
            print(f"ItemManager.revert_item_deletion: Invalid item_data, missing 'id'. Cannot revert deletion for guild {guild_id}.")
            return False

        print(f"ItemManager.revert_item_deletion: Attempting to recreate item {item_id_to_recreate} for guild {guild_id} from data: {item_data}")

        # Check if item already exists (e.g., partial undo)
        existing_item = self.get_item_instance(guild_id, item_id_to_recreate)
        if existing_item:
            print(f"ItemManager.revert_item_deletion: Item {item_id_to_recreate} already exists in guild {guild_id}. Assuming already reverted.")
            # Potentially verify if existing_item matches item_data and update if necessary,
            # but for now, if it exists, consider it done.
            return True

        try:
            # Ensure all necessary fields for Item.from_dict are present or have defaults
            # Item.from_dict should be robust enough or we need to ensure item_data is complete
            # based on Item model's requirements.
            item_data.setdefault('guild_id', guild_id) # Ensure guild_id is in the data for from_dict
            item_data.setdefault('state_variables', item_data.get('state_variables', {}))
            item_data.setdefault('is_temporary', item_data.get('is_temporary', False))
            # Ensure quantity is float for Item model
            item_data['quantity'] = float(item_data.get('quantity', 1.0))


            newly_created_item_object = Item.from_dict(item_data)

            # Save_item handles adding to caches and DB persistence.
            # It's crucial that save_item correctly handles an item with a pre-existing ID
            # by performing an UPSERT or by checking existence before INSERT.
            # Based on save_item's current UPSERT logic, this should be fine.
            save_success = await self.save_item(newly_created_item_object, guild_id)

            if save_success:
                print(f"ItemManager.revert_item_deletion: Successfully recreated and saved item {item_id_to_recreate} for guild {guild_id}.")
                return True
            else:
                print(f"ItemManager.revert_item_deletion: Failed to save recreated item {item_id_to_recreate} for guild {guild_id}.")
                return False
        except Exception as e:
            print(f"ItemManager.revert_item_deletion: Error during item recreation for {item_id_to_recreate} in guild {guild_id}: {e}")
            traceback.print_exc()
            return False

    async def revert_item_update(self, guild_id: str, item_id: str, old_field_values: Dict[str, Any], **kwargs: Any) -> bool:
        """Reverts specific fields of an item to their old values."""
        item = self.get_item_instance(guild_id, item_id)
        if not item:
            print(f"ItemManager.revert_item_update: Item {item_id} not found in guild {guild_id}. Cannot revert update.")
            return False

        print(f"ItemManager.revert_item_update: Reverting fields for item {item_id} in guild {guild_id}. Old values: {old_field_values}")

        old_item_dict_for_lookup = item.to_dict() # Capture state before this specific revert

        for field_name, old_value in old_field_values.items():
            if hasattr(item, field_name):
                # Special handling for quantity to ensure it's float
                if field_name == 'quantity' and old_value is not None:
                    try:
                        setattr(item, field_name, float(old_value))
                    except ValueError:
                        print(f"ItemManager.revert_item_update: Invalid old_value '{old_value}' for quantity on item {item_id}. Skipping field.")
                        continue
                else:
                    setattr(item, field_name, old_value)
            else:
                print(f"ItemManager.revert_item_update: Warning - Item {item_id} has no attribute '{field_name}'. Skipping field.")

        new_item_dict_for_lookup = item.to_dict() # Capture state after this specific revert

        # Check if owner or location changed to update lookup caches
        owner_changed = (old_item_dict_for_lookup.get('owner_id') != new_item_dict_for_lookup.get('owner_id') or
                         old_item_dict_for_lookup.get('owner_type') != new_item_dict_for_lookup.get('owner_type'))

        location_changed = old_item_dict_for_lookup.get('location_id') != new_item_dict_for_lookup.get('location_id')

        if owner_changed or location_changed:
            print(f"ItemManager.revert_item_update: Owner or location changed for item {item_id}. Updating lookup caches.")
            self._update_lookup_caches_remove(guild_id, old_item_dict_for_lookup) # Remove based on state *before* this revert
            self._update_lookup_caches_add(guild_id, new_item_dict_for_lookup)   # Add based on state *after* this revert

        self.mark_item_dirty(guild_id, item_id)
        print(f"ItemManager.revert_item_update: Successfully reverted fields for item {item_id} in guild {guild_id}.")
        return True

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None: # Changed
             self._clear_guild_state_cache(guild_id_str)
             return

        self._clear_guild_state_cache(guild_id_str)
        guild_items_cache = self._items[guild_id_str]

        try:
            sql_items = 'SELECT id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary FROM items WHERE guild_id = $1' # Changed placeholder
            rows_items = await self._db_service.adapter.fetchall(sql_items, (guild_id_str,)) # Changed
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
        if self._db_service is None or self._db_service.adapter is None: return # Changed

        dirty_ids = self._dirty_items.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_items.get(guild_id_str, set()).copy()

        if not dirty_ids and not deleted_ids:
            self._dirty_items.pop(guild_id_str, None)
            self._deleted_items.pop(guild_id_str, None)
            return

        if deleted_ids:
            if deleted_ids: # Ensure list is not empty
                placeholders = ','.join([f'${i+2}' for i in range(len(deleted_ids))]) # $2, $3, ...
                sql_delete = f"DELETE FROM items WHERE guild_id = $1 AND id IN ({placeholders})" # Changed placeholders
                try:
                    await self._db_service.adapter.execute(sql_delete, (guild_id_str, *list(deleted_ids))) # Changed
                    self._deleted_items.pop(guild_id_str, None)
                except Exception as e: print(f"ItemManager: Error deleting items: {e}")
            else: # If deleted_ids was empty for this guild
                self._deleted_items.pop(guild_id_str, None)

        items_to_upsert = [obj.to_dict() for id_str in dirty_ids if (obj := self._items.get(guild_id_str, {}).get(id_str))]

        if items_to_upsert:
            upsert_sql = '''
            INSERT INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (id) DO UPDATE SET
                template_id = EXCLUDED.template_id,
                guild_id = EXCLUDED.guild_id,
                owner_id = EXCLUDED.owner_id,
                owner_type = EXCLUDED.owner_type,
                location_id = EXCLUDED.location_id,
                quantity = EXCLUDED.quantity,
                state_variables = EXCLUDED.state_variables,
                is_temporary = EXCLUDED.is_temporary
            ''' # PostgreSQL UPSERT
            data_tuples = []
            processed_ids = set()
            for item_data in items_to_upsert:
                try:
                    data_tuples.append((
                        item_data['id'], item_data['template_id'], item_data['guild_id'],
                        item_data['owner_id'], item_data['owner_type'], item_data['location_id'],
                        item_data['quantity'], json.dumps(item_data['state_variables']),
                        bool(item_data['is_temporary']) # Pass boolean directly
                    ))
                    processed_ids.add(item_data['id'])
                except Exception as e: print(f"ItemManager: Error preparing item {item_data.get('id')} for save: {e}")

            if data_tuples:
                try:
                    await self._db_service.adapter.execute_many(upsert_sql, data_tuples) # Changed
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
        if self._db_service is None or self._db_service.adapter is None: return False # Changed
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
                bool(item_data_from_model.get('is_temporary', False)) # Pass boolean directly
            )
            upsert_sql = '''
            INSERT INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (id) DO UPDATE SET
                template_id = EXCLUDED.template_id,
                guild_id = EXCLUDED.guild_id,
                owner_id = EXCLUDED.owner_id,
                owner_type = EXCLUDED.owner_type,
                location_id = EXCLUDED.location_id,
                quantity = EXCLUDED.quantity,
                state_variables = EXCLUDED.state_variables,
                is_temporary = EXCLUDED.is_temporary
            ''' # PostgreSQL UPSERT
            await self._db_service.adapter.execute(upsert_sql, db_params) # Changed

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

    async def get_items_in_location_async(self, guild_id: str, location_id: str) -> List["Item"]: # Assuming Item model exists
        """
        Retrieves all item instances currently in a specific location.
        Fetches from DBService and converts to Item model objects.
        """
        if not self.db_service:
            print(f"ItemManager: DBService not available. Cannot get items in location {location_id} for guild {guild_id}.")
            return []

        # from bot.game.models.item import Item # Already imported globally

        item_data_list = await self.db_service.get_item_instances_in_location(location_id=location_id, guild_id=guild_id)

        items: List[Item] = []
        for data in item_data_list:
            try:
                # The data from db_service.get_item_instances_in_location includes joined item_template data.
                # Item.from_dict needs to handle this structure.
                item_properties = data.get('properties', {}) # from item_templates
                state_variables = data.get('state_variables', {}) # from items table (instance)

                item_init_data = {
                    "id": data.get("item_instance_id"), # Instance ID
                    "template_id": data.get("template_id"),
                    "guild_id": guild_id, # Passed guild_id
                    "name": data.get("name"), # From template
                    "description": data.get("description"), # From template
                    "item_type": data.get("item_type"), # From template
                    "quantity": data.get("quantity"), # From instance
                    "properties": item_properties, # From template
                    "state_variables": state_variables, # From instance
                    "owner_id": None, # Items in location are not owned by an entity
                    "owner_type": "location", # Or None, depending on how unowned items in locations are marked
                    "location_id": location_id # Explicitly set items in this location
                }
                # Ensure all required fields by Item.from_dict are present
                if not item_init_data["id"] or not item_init_data["template_id"]:
                    print(f"ItemManager: Skipping item data due to missing id or template_id: {item_init_data}")
                    continue

                items.append(Item.from_dict(item_init_data))
            except Exception as e:
                print(f"ItemManager: Error converting data to Item object for item in location {location_id}: {data}, Error: {e}")
                traceback.print_exc() # Ensure traceback is imported
        return items

    async def transfer_item_world_to_character(self, guild_id: str, character_id: str, item_instance_id: str, quantity: int = 1) -> bool:
        """
        Transfers a specific quantity of an item instance from the world (a location)
        to a character's inventory.
        """
        if not self.db_service or not self._character_manager: # Use self._character_manager
            print("ItemManager: DBService or CharacterManager not available. Cannot transfer item.")
            return False

        # 1. Get the item instance from the world
        item_instance_data = await self.db_service.get_entity(table_name="items", entity_id=item_instance_id, guild_id=guild_id)

        if not item_instance_data:
            print(f"ItemManager: Item instance {item_instance_id} not found in guild {guild_id}.")
            return False

        current_quantity_in_world = item_instance_data.get('quantity', 0.0) # DB might store as float
        if not isinstance(current_quantity_in_world, (int, float)): current_quantity_in_world = 0.0

        template_id = item_instance_data.get('template_id')

        if not template_id:
             print(f"ItemManager: Item instance {item_instance_id} is missing a template_id.")
             return False

        if current_quantity_in_world < quantity:
            print(f"ItemManager: Not enough quantity of item {item_instance_id} in world. Has {current_quantity_in_world}, needs {quantity}.")
            return False

        # 2. Add item to character's inventory
        # CharacterManager.add_item_to_inventory expects template_id
        add_success = await self._character_manager.add_item_to_inventory(
            guild_id=guild_id,
            character_id=character_id,
            item_id=template_id, # Use template_id for adding to character
            quantity=quantity
        )

        if not add_success:
            print(f"ItemManager: Failed to add item (template: {template_id}) to character {character_id} inventory.")
            return False

        # 3. Update or delete the item instance from the world
        if current_quantity_in_world == quantity:
            delete_success = await self.db_service.delete_entity(table_name="items", entity_id=item_instance_id, guild_id=guild_id)
            if not delete_success:
                print(f"ItemManager: Failed to delete item instance {item_instance_id} from world. Manual cleanup may be needed.")
                # Consider rolling back character inventory addition if possible, or log inconsistency.
            else:
                print(f"ItemManager: Item instance {item_instance_id} deleted from world.")
                # Remove from local cache if it exists
                guild_items_cache = self._items.get(guild_id, {})
                if item_instance_id in guild_items_cache:
                    del guild_items_cache[item_instance_id]
                self._update_lookup_caches_remove(guild_id, item_instance_data) # item_instance_data is a dict
                self._dirty_items.get(guild_id, set()).discard(item_instance_id)
                self._deleted_items.setdefault(guild_id, set()).add(item_instance_id)


        else:
            new_world_quantity = current_quantity_in_world - quantity
            update_success = await self.db_service.update_entity(
                table_name="items",
                entity_id=item_instance_id,
                data={'quantity': new_world_quantity},
                guild_id=guild_id
            )
            if not update_success:
                print(f"ItemManager: Failed to update quantity for item instance {item_instance_id} in world.")
                # Consider rolling back.
            else:
                print(f"ItemManager: Item instance {item_instance_id} quantity updated in world to {new_world_quantity}.")
                # Update local cache if it exists
                cached_item = self.get_item_instance(guild_id, item_instance_id)
                if cached_item:
                    cached_item.quantity = new_world_quantity
                    self.mark_item_dirty(guild_id, item_instance_id)

        return True

print("DEBUG: item_manager.py module loaded.")
