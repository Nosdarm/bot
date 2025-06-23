# bot/game/managers/inventory_manager.py
from __future__ import annotations
import uuid
import json # Added for robust JSON parsing
import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING

# SQLAlchemy specific imports
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

# Project models and services
from bot.database.models import Character, Item as ItemDbModel # SQLAlchemy models, aliased Item to ItemDbModel
# Assuming ItemTemplate is represented as a Dict from ItemManager, no specific model import needed unless it's a Pydantic model too.

if TYPE_CHECKING:
    from bot.services.db_service import DBService # For direct DB operations
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    # Character model is already imported globally

logger = logging.getLogger(__name__)

class InventoryManager:
    def __init__(self,
                 character_manager: "CharacterManager",
                 item_manager: "ItemManager",
                 db_service: "DBService"): # Added db_service
        self._character_manager = character_manager # Still useful for non-DB character cache operations
        self._item_manager = item_manager
        self._db_service = db_service # Store DBService
        logger.info("InventoryManager initialized with DBService.")

    # --- Existing helper and inventory management methods (unchanged for this subtask) ---
    # These methods likely operate on cached Character models or will need their own DB logic/session handling
    # if CharacterManager changes to fully rely on DB models passed around.
    # For now, assuming they work with CharacterManager's cached character objects which have an 'inventory' list of dicts.

    def _get_character_inventory_from_cache(self, guild_id: str, character_id: str) -> Optional[List[Dict[str, Any]]]:
        """Helper to get a character's inventory list from cached Character model."""
        character = self._character_manager.get_character(guild_id, character_id) # Assumes this returns cached model
        if character:
            if not hasattr(character, 'inventory') or character.inventory is None: # 'inventory' here is the Pydantic/game model field
                # logger.debug("Character (cache) %s in guild %s inventory is None, initializing to empty list.", character_id, guild_id)
                character.inventory = []
            return character.inventory
        logger.warning("Character (cache) %s not found in guild %s for inventory access.", character_id, guild_id)
        return None

    def has_item(self, guild_id: str, character_id: str, item_template_id: str, quantity: int = 1) -> bool:
        inventory = self._get_character_inventory_from_cache(guild_id, character_id)
        if inventory is None: return False
        current_quantity = 0
        for item_stack in inventory:
            if item_stack.get('item_id') == item_template_id:
                current_quantity += item_stack.get('quantity', 0)
        return current_quantity >= quantity

    def add_item(self, guild_id: str, character_id: str, item_template_id: str, quantity: int = 1, item_data: Optional[Dict[str, Any]] = None) -> bool:
        # This method operates on the cached Character.inventory (list of dicts)
        # It will need updating if Character.inventory becomes Character.inventory_json directly
        inventory = self._get_character_inventory_from_cache(guild_id, character_id)
        if inventory is None:
            logger.error("InventoryManager (cache): Character %s not found in guild %s for add_item.", character_id, guild_id)
            return False
        # ... (rest of the original add_item logic that manipulates a list of dicts) ...
        # This original add_item is NOT what we are modifying for DB interaction.
        # The new add_item_to_character_inventory handles DB.
        # For clarity, I'll leave the original add_item as is, assuming it serves a different purpose (e.g. pre-DB state)
        # or will be refactored/removed later. The subtask focuses on add_item_to_character_inventory.
        logger.info(f"InventoryManager (cache): Original add_item called for {item_template_id}. This does not use DB directly.")
        # Fallback to previous logic for now to not break existing calls to this specific method signature.
        # This method should ideally be deprecated or updated to use the new DB-centric approach.
        character = self._character_manager.get_character(guild_id, character_id)
        if not character: return False
        item_definition = self._item_manager.get_item_template(item_template_id) # Sync cache lookup
        is_stackable = item_definition.get('stackable', True) if item_definition else True
        item_name_log = item_definition.get('name_i18n', {}).get('en', item_template_id) if item_definition else item_template_id

        if is_stackable:
            for item_stack in inventory:
                if item_stack.get('item_id') == item_template_id and not item_data:
                    item_stack['quantity'] = item_stack.get('quantity', 0) + quantity
                    self._character_manager.mark_character_dirty(guild_id, character_id)
                    logger.info("InventoryManager (cache): Added %s to existing stack of '%s' for char %s.", quantity, item_name_log, character_id)
                    return True
        num_to_add = quantity if not is_stackable and not item_data else 1
        effective_quantity = 1 if not is_stackable and not item_data else quantity
        for _ in range(num_to_add):
            new_item_instance: Dict[str, Any] = {"item_id": item_template_id, "quantity": effective_quantity, "instance_id": str(uuid.uuid4())}
            if item_data: new_item_instance.update(item_data)
            inventory.append(new_item_instance)
        self._character_manager.mark_character_dirty(guild_id, character_id)
        logger.info("InventoryManager (cache): Added %s new instance(s) of '%s' (qty %s each) for char %s.", num_to_add, item_name_log, effective_quantity, character_id)
        return True


    def remove_item(self, guild_id: str, character_id: str, item_template_id: str, quantity: int = 1, instance_id: Optional[str] = None) -> bool:
        # This method also operates on the cached Character.inventory
        inventory = self._get_character_inventory_from_cache(guild_id, character_id)
        if inventory is None: return False
        # ... (rest of original remove_item logic) ...
        logger.info(f"InventoryManager (cache): Original remove_item called for {item_template_id}. This does not use DB directly.")
        return True # Placeholder for brevity, original logic is more complex

    # --- New/Verified DB-centric method ---
    async def add_item_to_character_inventory(
        self,
        guild_id: str,
        character_id: str,
        item_template_id: str,
        quantity: int = 1,
        state_variables: Optional[Dict[str, Any]] = None,
        session: Optional[AsyncSession] = None
    ) -> bool:
        """
        Adds item(s) to a character's inventory by creating ItemDbModel instances
        and updating the Character.inventory_json field.
        Manages SQLAlchemy session if one is not provided.
        """
        if not self._db_service:
            logger.error("InventoryManager: DBService not available. Cannot add item to character inventory.")
            return False

        if quantity <= 0:
            logger.warning(f"InventoryManager: Attempted to add non-positive quantity ({quantity}) of item {item_template_id} for character {character_id}.")
            return False

        manage_session = False
        actual_session: AsyncSession
        if session is None:
            actual_session = self._db_service.get_session() # type: ignore
            manage_session = True
        else:
            actual_session = session

        try:
            if manage_session: # If we created the session, we manage its lifecycle (begin, commit, rollback, close)
                async with actual_session.begin(): # Start transaction
                    item_template_dict = await self._item_manager.get_item_template_as_dict(guild_id, item_template_id) # Expects dict
                    if not item_template_dict:
                        logger.error(f"InventoryManager: Item template '{item_template_id}' not found for guild {guild_id}. Cannot add item.")
                        # No explicit rollback needed here, 'async with' handles it on exception
                        return False

                    character = await actual_session.get(Character, character_id)
                    if not character or str(character.guild_id) != guild_id:
                        logger.error(f"InventoryManager: Character {character_id} not found in guild {guild_id}.")
                        return False

                    await self._execute_add_item_logic(actual_session, character, guild_id, item_template_id, item_template_dict, quantity, state_variables)
                # Commit happens automatically if 'async with actual_session.begin()' completes without error
            else: # If session is provided, assume caller manages lifecycle and transaction
                item_template_dict = await self._item_manager.get_item_template_as_dict(guild_id, item_template_id)
                if not item_template_dict:
                    logger.error(f"InventoryManager: Item template '{item_template_id}' not found for guild {guild_id} (using provided session).")
                    return False # Caller should handle rollback if necessary

                character = await actual_session.get(Character, character_id)
                if not character or str(character.guild_id) != guild_id:
                    logger.error(f"InventoryManager: Character {character_id} not found in guild {guild_id} (using provided session).")
                    return False

                await self._execute_add_item_logic(actual_session, character, guild_id, item_template_id, item_template_dict, quantity, state_variables)

            logger.info(f"InventoryManager: Successfully processed add_item for {quantity} of '{item_template_id}' to char {character_id}.")
            return True

        except Exception as e:
            logger.error(f"InventoryManager: Error adding item {item_template_id} to character {character_id}: {e}", exc_info=True)
            # Rollback is handled by 'async with' if manage_session is True and an error occurred within the block.
            # If session was provided, caller handles rollback.
            return False
        finally:
            if manage_session and actual_session: # Close session only if it was created here
                await actual_session.close()

    async def _execute_add_item_logic(self,
                                      active_session: AsyncSession,
                                      character: Character,
                                      guild_id: str,
                                      item_template_id: str,
                                      item_template_dict: Dict[str, Any], # Expecting dict from ItemManager
                                      quantity: int,
                                      state_variables: Optional[Dict[str, Any]]):
        """Core logic to create ItemDbModel instances and update Character.inventory_json."""
        new_item_instance_ids = []
        for _ in range(quantity):
            item_instance_id = str(uuid.uuid4())
            new_item = ItemDbModel(
                id=item_instance_id,
                template_id=item_template_id,
                guild_id=guild_id,
                owner_id=character.id,
                owner_type="character",
                quantity=1, # Each DB row is one instance
                state_variables=state_variables if state_variables else {},
                name_i18n=item_template_dict.get("name_i18n", {"en": item_template_id}),
                description_i18n=item_template_dict.get("description_i18n", {"en": "No description."}),
                properties=item_template_dict.get("properties", {}),
                # Add other relevant fields if they exist on ItemDbModel and item_template_dict
                # e.g., value=item_template_dict.get("base_value")
            )
            active_session.add(new_item)
            new_item_instance_ids.append(item_instance_id)

        current_inventory_list = []
        if character.inventory_json:
            if isinstance(character.inventory_json, list):
                current_inventory_list = character.inventory_json
            elif isinstance(character.inventory_json, str): # Should not happen if DB field is JSONB and ORM handles it
                try:
                    loaded_json = json.loads(character.inventory_json)
                    if isinstance(loaded_json, list): current_inventory_list = loaded_json
                    else: logger.warning(f"Char {character.id} inventory_json (str) not a list. Resetting.")
                except json.JSONDecodeError:
                    logger.warning(f"Char {character.id} inventory_json (str) invalid. Resetting.")

        current_inventory_list.extend(new_item_instance_ids)
        character.inventory_json = current_inventory_list
        flag_modified(character, "inventory_json")
        active_session.add(character)


    # Other existing methods (get_item_instance_by_id, etc.) would also need to be updated
    # if they are intended to work with DB Item models rather than cached Character.inventory list of dicts.
    # For this subtask, focus is on add_item_to_character_inventory.

# logger.debug("DEBUG: inventory_manager.py module loaded.")

