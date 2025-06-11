# bot/game/managers/inventory_manager.py
from __future__ import annotations
import uuid
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.models.character import Character # For type hinting

class InventoryManager:
    def __init__(self, character_manager: "CharacterManager", item_manager: "ItemManager"):
        self._character_manager = character_manager
        self._item_manager = item_manager # Might be needed for item properties like stackability
        print("InventoryManager initialized.")

    def _get_character_inventory(self, guild_id: str, character_id: str) -> Optional[List[Dict[str, Any]]]:
        """Helper to get a character's inventory list."""
        character = self._character_manager.get_character(guild_id, character_id)
        if character:
            if not hasattr(character, 'inventory') or character.inventory is None:
                character.inventory = [] # Initialize if missing
            return character.inventory
        return None

    def has_item(self, guild_id: str, character_id: str, item_template_id: str, quantity: int = 1) -> bool:
        """Checks if the character has a specific quantity of an item by template ID."""
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None:
            return False

        current_quantity = 0
        for item_stack in inventory:
            if item_stack.get('item_id') == item_template_id:
                current_quantity += item_stack.get('quantity', 0)

        return current_quantity >= quantity

    def add_item(self, guild_id: str, character_id: str, item_template_id: str, quantity: int = 1, item_data: Optional[Dict[str, Any]] = None) -> bool:
        """Adds an item to the character's inventory."""
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None:
            print(f"InventoryManager: Character {character_id} not found in guild {guild_id} for add_item.")
            return False

        character = self._character_manager.get_character(guild_id, character_id)
        if not character: # Should not happen if _get_character_inventory worked, but as a safeguard
            return False

        # TODO: Check item stackability using ItemManager if available
        # item_definition = self._item_manager.get_item_template(guild_id, item_template_id)
        # is_stackable = item_definition.stackable if item_definition else True # Default to stackable
        is_stackable = True # Placeholder

        if is_stackable:
            for item_stack in inventory:
                if item_stack.get('item_id') == item_template_id:
                    item_stack['quantity'] = item_stack.get('quantity', 0) + quantity
                    self._character_manager.mark_character_dirty(guild_id, character_id)
                    return True

        # If not stackable, or stackable but not found, add new entry/entries
        # For non-stackable items, add quantity individual entries
        # For stackable, add one new entry with the quantity

        num_to_add = quantity if not is_stackable else 1
        effective_quantity = 1 if not is_stackable else quantity

        for _ in range(num_to_add):
            new_item_instance: Dict[str, Any] = {
                "item_id": item_template_id,
                "quantity": effective_quantity,
                "instance_id": str(uuid.uuid4()) # Unique ID for each instance or stack
            }
            if item_data: # For unique properties, e.g., enchantments, durability
                new_item_instance.update(item_data)
            inventory.append(new_item_instance)

        self._character_manager.mark_character_dirty(guild_id, character_id)
        return True

    def remove_item(self, guild_id: str, character_id: str, item_template_id: str, quantity: int = 1, instance_id: Optional[str] = None) -> bool:
        """Removes an item from the character's inventory."""
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None:
            print(f"InventoryManager: Character {character_id} not found for remove_item.")
            return False

        character = self._character_manager.get_character(guild_id, character_id)
        if not character: return False

        if instance_id: # Remove a specific instance (e.g., an equipped weapon)
            item_found = False
            for i, item_stack in enumerate(inventory):
                if item_stack.get('instance_id') == instance_id:
                    if item_stack.get('item_id') != item_template_id: # Sanity check
                        print(f"InventoryManager: Warning - item_template_id mismatch for instance_id {instance_id}.")
                        return False # Item ID mismatch

                    current_qty = item_stack.get('quantity', 0)
                    if current_qty > quantity:
                        item_stack['quantity'] = current_qty - quantity
                    else: # Remove the whole stack/instance
                        inventory.pop(i)
                    item_found = True
                    break
            if not item_found:
                return False # Specific instance not found
        else: # Remove by template_id (e.g., consumables)
            # This needs to handle multiple stacks if item is not perfectly stackable or if stored as such
            quantity_to_remove = quantity
            indices_to_remove = []
            for i, item_stack in reversed(list(enumerate(inventory))): # Iterate backwards to safely remove
                if item_stack.get('item_id') == item_template_id:
                    current_qty_in_stack = item_stack.get('quantity', 0)
                    if current_qty_in_stack > quantity_to_remove:
                        item_stack['quantity'] = current_qty_in_stack - quantity_to_remove
                        quantity_to_remove = 0
                        break
                    else: # Remove this stack and continue if more quantity needs to be removed
                        quantity_to_remove -= current_qty_in_stack
                        indices_to_remove.append(i)
                        if quantity_to_remove <= 0:
                            break

            if quantity_to_remove > 0: # Not enough items found
                return False

            for i in sorted(indices_to_remove, reverse=True): # Remove from highest index first
                inventory.pop(i)

        self._character_manager.mark_character_dirty(guild_id, character_id)
        return True

    def get_item_instance_by_id(self, guild_id: str, character_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
        """Gets a specific item instance from inventory by its instance_id."""
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None: return None

        for item_stack in inventory:
            if item_stack.get('instance_id') == instance_id:
                return item_stack
        return None

    def get_items_by_template_id(self, guild_id: str, character_id: str, item_template_id: str) -> List[Dict[str, Any]]:
        """Gets all item instances/stacks matching a given template_id."""
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None: return []

        return [item_stack for item_stack in inventory if item_stack.get('item_id') == item_template_id]

    def get_total_quantity_of_item(self, guild_id: str, character_id: str, item_template_id: str) -> int:
        """Calculates the total quantity of an item by its template ID across all stacks."""
        inventory = self._get_character_inventory(guild_id, character_id)
        if inventory is None: return 0

        total_quantity = 0
        for item_stack in inventory:
            if item_stack.get('item_id') == item_template_id:
                total_quantity += item_stack.get('quantity', 0)
        return total_quantity

print("DEBUG: inventory_manager.py module loaded.")
