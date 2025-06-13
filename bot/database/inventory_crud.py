from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from .models import NewItem, NewCharacterItem, Character # Relative import for models
# Schemas are not directly used as function params per prompt, but could be for validation layer
# from ..api.schemas.inventory_schemas import NewCharacterItemCreate, NewCharacterItemUpdate
# from ..api.schemas.item_schemas import NewItemRead

async def get_character_inventory(db: AsyncSession, character_id: str) -> list[NewCharacterItem]:
    """
    Retrieves all inventory items for a character, with item details eager loaded.
    """
    stmt = (
        select(NewCharacterItem)
        .where(NewCharacterItem.character_id == character_id)
        .options(joinedload(NewCharacterItem.item))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())

async def add_item_to_character_inventory(
    db: AsyncSession, character_id: str, item_id: UUID, quantity: int = 1
) -> NewCharacterItem:
    """
    Adds a specified quantity of an item to a character's inventory.
    If the item is already present, its quantity is incremented.
    Otherwise, a new inventory entry is created.
    """
    if quantity <= 0:
        raise ValueError("Quantity to add must be positive.")

    # Check if character exists
    character_exists = await db.get(Character, character_id)
    if not character_exists:
        raise ValueError("Character not found")

    # Check if item template (NewItem) exists
    item_template_exists = await db.get(NewItem, item_id)
    if not item_template_exists:
        raise ValueError("Item template not found")

    # Check if the item already exists in the character's inventory
    existing_entry_stmt = select(NewCharacterItem).where(
        and_(
            NewCharacterItem.character_id == character_id,
            NewCharacterItem.item_id == item_id,
        )
    )
    existing_entry_result = await db.execute(existing_entry_stmt)
    inventory_item_entry = existing_entry_result.scalar_one_or_none()

    if inventory_item_entry:
        inventory_item_entry.quantity += quantity
    else:
        inventory_item_entry = NewCharacterItem(
            character_id=character_id, item_id=item_id, quantity=quantity
        )
        db.add(inventory_item_entry)

    try:
        await db.commit()
        await db.refresh(inventory_item_entry)
        # Eager load item details for the returned object as well
        await db.refresh(inventory_item_entry, attribute_names=['item'])
        return inventory_item_entry
    except IntegrityError: # Catches issues like quantity check constraint if we didn't validate quantity > 0 before.
        await db.rollback()
        raise ValueError("Could not add item to inventory due to a database constraint.")


async def remove_item_from_character_inventory(
    db: AsyncSession, character_id: str, item_id: UUID, quantity_to_remove: int = 1
) -> NewCharacterItem | None:
    """
    Removes a specified quantity of an item from a character's inventory.
    If the quantity becomes zero or less, the item entry is deleted.
    Returns the updated item entry or None if deleted.
    """
    if quantity_to_remove <= 0:
        raise ValueError("Quantity to remove must be positive.")

    # Check if character exists (optional, depends on how strict, remove_item assumes entry exists)
    # character_exists = await db.get(Character, character_id)
    # if not character_exists:
    #     raise ValueError("Character not found")

    # Fetch the NewCharacterItem entry
    entry_stmt = select(NewCharacterItem).where(
        and_(
            NewCharacterItem.character_id == character_id,
            NewCharacterItem.item_id == item_id,
        )
    )
    inventory_item_entry_result = await db.execute(entry_stmt)
    inventory_item_entry = inventory_item_entry_result.scalar_one_or_none()

    if not inventory_item_entry:
        raise ValueError("Item not found in character's inventory.")

    if quantity_to_remove > inventory_item_entry.quantity:
        raise ValueError("Cannot remove more items than available in inventory.")

    inventory_item_entry.quantity -= quantity_to_remove

    if inventory_item_entry.quantity <= 0:
        await db.delete(inventory_item_entry)
        await db.commit()
        return None
    else:
        try:
            await db.commit()
            await db.refresh(inventory_item_entry)
            # Eager load item details for the returned object
            await db.refresh(inventory_item_entry, attribute_names=['item'])
            return inventory_item_entry
        except IntegrityError: # Should not happen if logic is correct, but as safeguard
            await db.rollback()
            raise ValueError("Could not update item in inventory due to a database constraint.")


async def get_character_item_entry(
    db: AsyncSession, character_id: str, item_id: UUID
) -> NewCharacterItem | None:
    """
    Retrieves a specific inventory item entry for a character, with item details eager loaded.
    """
    stmt = (
        select(NewCharacterItem)
        .where(
            and_(
                NewCharacterItem.character_id == character_id,
                NewCharacterItem.item_id == item_id,
            )
        )
        .options(joinedload(NewCharacterItem.item))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
