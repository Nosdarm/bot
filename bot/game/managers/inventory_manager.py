# bot/game/managers/inventory_manager.py
from __future__ import annotations
import uuid
import logging # Added
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.models.character import Character # For type hinting

logger = logging.getLogger(__name__) # Added

class InventoryManager:
    def __init__(self, character_manager: "CharacterManager", item_manager: "ItemManager"):
        self._character_manager = character_manager
        self._item_manager = item_manager
        logger.info("InventoryManager initialized.") # Changed

    def _get_character_inventory(self, guild_id: str, character_id: str) -> Optional[List[Dict[str, Any]]]:
        """Helper to get a character's inventory list."""
        character = self._character_manager.get_character(guild_id, character_id)
        if character:
            if not hasattr(character, 'inventory') or character.inventory is None:
                logger.debug("Character %s in guild %s inventory is None, initializing to empty list.", character_id, guild_id) # Added
                character.inventory = []
            return character.inventory
        logger.warning("Character %s not found in guild %s for inventory access.", character_id, guild_id) # Added
        return None

    def has_item(self, guild_id: str, character_id: str, item_template_id: str, quantity: int = 1) -> bool:
        """Checks if the character has a specific quantity of an item by template ID."""
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None:
            return False # Character not found or inventory error already logged

        current_quantity = 0
        for item_stack in inventory:
            if item_stack.get('item_id') == item_template_id: # Assuming item_id is template_id here
                current_quantity += item_stack.get('quantity', 0)
        return current_quantity >= quantity

    def add_item(self, guild_id: str, character_id: str, item_template_id: str, quantity: int = 1, item_data: Optional[Dict[str, Any]] = None) -> bool:
        """Adds an item to the character's inventory."""
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None:
            logger.error("InventoryManager: Character %s not found in guild %s for add_item.", character_id, guild_id) # Changed
            return False

        character = self._character_manager.get_character(guild_id, character_id)
        if not character:
            logger.error("InventoryManager: Character %s (guild %s) disappeared after inventory check for add_item.", character_id, guild_id) # Added
            return False

        # is_stackable = True # Placeholder, TODO: use ItemManager
        item_definition = None
        if self._item_manager and hasattr(self._item_manager, 'get_item_template_by_id'): # Check for modern method
            item_definition = self._item_manager.get_item_template_by_id(guild_id, item_template_id)
        elif self._item_manager and hasattr(self._item_manager, 'get_item_template'): # Fallback
             item_definition = self._item_manager.get_item_template(guild_id, item_template_id)

        is_stackable = getattr(item_definition, 'stackable', True) if item_definition else True # Default to stackable if def not found
        item_name_log = getattr(item_definition, 'name', item_template_id) if item_definition else item_template_id

        if is_stackable:
            for item_stack in inventory:
                # Check for matching template ID and if item_data is compatible for stacking
                # For simplicity, if item_data is provided, assume it makes the item unique unless ItemManager says otherwise
                if item_stack.get('item_id') == item_template_id and not item_data: # Only stack if no unique data
                    item_stack['quantity'] = item_stack.get('quantity', 0) + quantity
                    self._character_manager.mark_character_dirty(guild_id, character_id)
                    logger.info("InventoryManager: Added %s to existing stack of '%s' for char %s in guild %s.", quantity, item_name_log, character_id, guild_id) # Added
                    return True

        # If not stackable, or stackable but not found (or has unique data), add new entry/entries
        num_to_add = quantity if not is_stackable and not item_data else 1 # If not stackable & no unique data, add multiple entries. Otherwise one.
        effective_quantity = 1 if not is_stackable and not item_data else quantity # If one entry, it has the full quantity

        for _ in range(num_to_add):
            new_item_instance: Dict[str, Any] = {
                "item_id": item_template_id, # This is template_id
                "quantity": effective_quantity,
                "instance_id": str(uuid.uuid4())
            }
            if item_data:
                new_item_instance.update(item_data)
            inventory.append(new_item_instance)

        self._character_manager.mark_character_dirty(guild_id, character_id)
        logger.info("InventoryManager: Added %s new instance(s) of '%s' (qty %s each) for char %s in guild %s.", num_to_add, item_name_log, effective_quantity, character_id, guild_id) # Added
        return True

    def remove_item(self, guild_id: str, character_id: str, item_template_id: str, quantity: int = 1, instance_id: Optional[str] = None) -> bool:
        """Removes an item from the character's inventory."""
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None:
            logger.error("InventoryManager: Character %s (guild %s) not found for remove_item.", character_id, guild_id) # Changed
            return False

        character = self._character_manager.get_character(guild_id, character_id)
        if not character:
            logger.error("InventoryManager: Character %s (guild %s) disappeared after inventory check for remove_item.", character_id, guild_id) # Added
            return False

        item_name_log = item_template_id # Fallback
        if self._item_manager: # Try to get a better name for logging
            item_def = None
            if hasattr(self._item_manager, 'get_item_template_by_id'): item_def = self._item_manager.get_item_template_by_id(guild_id, item_template_id)
            elif hasattr(self._item_manager, 'get_item_template'): item_def = self._item_manager.get_item_template(guild_id, item_template_id)
            if item_def: item_name_log = getattr(item_def, 'name', item_template_id)


        if instance_id:
            item_found_and_removed = False
            for i, item_stack in enumerate(inventory):
                if item_stack.get('instance_id') == instance_id:
                    if item_stack.get('item_id') != item_template_id:
                        logger.warning("InventoryManager: Item template_id mismatch for instance_id %s (char %s, guild %s). Expected %s, got %s.", instance_id, character_id, guild_id, item_template_id, item_stack.get('item_id')) # Changed
                        return False

                    current_qty = item_stack.get('quantity', 0)
                    if current_qty > quantity:
                        item_stack['quantity'] = current_qty - quantity
                        logger.info("InventoryManager: Reduced quantity of item instance %s (template '%s') by %s for char %s in guild %s. New qty: %s.", instance_id, item_name_log, quantity, character_id, guild_id, item_stack['quantity']) # Added
                    else:
                        inventory.pop(i)
                        logger.info("InventoryManager: Removed item instance %s (template '%s', qty %s) for char %s in guild %s.", instance_id, item_name_log, current_qty, character_id, guild_id) # Added
                    item_found_and_removed = True
                    break
            if not item_found_and_removed:
                logger.warning("InventoryManager: Specific item instance %s not found for char %s in guild %s.", instance_id, character_id, guild_id) # Added
                return False
        else:
            quantity_to_remove = quantity
            indices_to_remove = []
            for i, item_stack in reversed(list(enumerate(inventory))):
                if item_stack.get('item_id') == item_template_id:
                    current_qty_in_stack = item_stack.get('quantity', 0)
                    if current_qty_in_stack > quantity_to_remove:
                        item_stack['quantity'] = current_qty_in_stack - quantity_to_remove
                        logger.info("InventoryManager: Reduced quantity of '%s' by %s from a stack for char %s in guild %s. Stack new qty: %s.", item_name_log, quantity_to_remove, character_id, guild_id, item_stack['quantity']) # Added
                        quantity_to_remove = 0
                        break
                    else:
                        quantity_to_remove -= current_qty_in_stack
                        indices_to_remove.append(i)
                        if quantity_to_remove <= 0:
                            break
            if quantity_to_remove > 0:
                logger.warning("InventoryManager: Not enough of item '%s' found for char %s in guild %s. Requested %s, but %s still to remove.", item_name_log, character_id, guild_id, quantity, quantity_to_remove) # Added
                return False
            for i in sorted(indices_to_remove, reverse=True):
                removed_stack = inventory.pop(i)
                logger.info("InventoryManager: Removed stack of item '%s' (qty %s, instance %s) for char %s in guild %s.", item_name_log, removed_stack.get('quantity'), removed_stack.get('instance_id'), character_id, guild_id) # Added

        self._character_manager.mark_character_dirty(guild_id, character_id)
        return True

    def get_item_instance_by_id(self, guild_id: str, character_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None: return None
        for item_stack in inventory:
            if item_stack.get('instance_id') == instance_id:
                return item_stack
        return None

    def get_items_by_template_id(self, guild_id: str, character_id: str, item_template_id: str) -> List[Dict[str, Any]]:
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None: return []
        return [item_stack for item_stack in inventory if item_stack.get('item_id') == item_template_id]

    def get_total_quantity_of_item(self, guild_id: str, character_id: str, item_template_id: str) -> int:
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None: return 0
        total_quantity = 0
        for item_stack in inventory:
            if item_stack.get('item_id') == item_template_id:
                total_quantity += item_stack.get('quantity', 0)
        return total_quantity

logger.debug("DEBUG: inventory_manager.py module loaded.") # Changed
