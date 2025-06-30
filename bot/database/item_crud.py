from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError # For handling unique constraint violations

from .models import NewItem, NewCharacterItem # Relative import for models within the same directory/package
from ..api.schemas.item_schemas import NewItemCreate, NewItemUpdate # Relative import for schemas

async def create_new_item(db: AsyncSession, item: NewItemCreate) -> NewItem:
    """
    Creates a new item in the database.
    """
    db_item = NewItem(**item.model_dump())
    db.add(db_item)
    try:
        await db.commit()
        await db.refresh(db_item)
        return db_item
    except IntegrityError:
        await db.rollback()
        # In a real app, you might raise HTTPException here or a custom exception
        # that the API layer can catch and convert to an HTTP response.
        # from fastapi import HTTPException
        # raise HTTPException(status_code=400, detail="Item with this name already exists")
        raise # Re-raise for now, let API layer handle

async def get_new_item(db: AsyncSession, item_id: UUID, guild_id: str) -> NewItem | None:
    """
    Retrieves a single item by its ID and guild_id.
    """
    result = await db.execute(select(NewItem).where(NewItem.id == item_id, NewItem.guild_id == guild_id))
    return result.scalar_one_or_none()

async def get_new_items(db: AsyncSession, guild_id: str, skip: int = 0, limit: int = 100) -> list[NewItem]:
    """
    Retrieves a list of items for a specific guild with pagination.
    """
    result = await db.execute(
        select(NewItem).where(NewItem.guild_id == guild_id).offset(skip).limit(limit)
    )
    return list(result.scalars().all())

async def update_new_item(db: AsyncSession, item_id: UUID, guild_id: str, item_update: NewItemUpdate) -> NewItem | None:
    """
    Updates an existing item, ensuring it belongs to the correct guild.
    """
    db_item = await get_new_item(db, item_id, guild_id) # Pass guild_id here
    if db_item is None:
        return None

    update_data = item_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_item, key, value)

    db.add(db_item)
    try:
        await db.commit()
        await db.refresh(db_item)
        return db_item
    except IntegrityError:
        await db.rollback()
        # from fastapi import HTTPException
        # raise HTTPException(status_code=400, detail="Item with this name already exists after update")
        raise # Re-raise for now

async def delete_new_item(db: AsyncSession, item_id: UUID, guild_id: str) -> NewItem | None:
    """
    Deletes an item for a specific guild after checking if it's in any character's inventory within that guild.
    """
    # Check if the item is in any NewCharacterItem record belonging to a character in the same guild.
    # This requires joining NewCharacterItem -> Character -> Player (or directly Character.guild_id if available)
    # For simplicity, if NewCharacterItem doesn't directly link to guild, this check might be broad
    # or needs more complex query. Assuming item_id is globally unique but deletion is guild-scoped.
    # The main check is that the item template to be deleted belongs to the guild.

    db_item = await get_new_item(db, item_id, guild_id) # This ensures we only consider items from the correct guild
    if db_item is None:
        return None # Item not found in this guild, or at all.

    # Check if the item (by template ID) is in any NewCharacterItem record.
    # This check is across all guilds if NewCharacterItem is not directly guild_scoped.
    # A more accurate check would be: is this item_id (template) used by any character in *this* guild?
    # This would require joining inventory -> character -> player.guild_id or character.guild_id.
    # For now, keeping the existing broad check against NewCharacterItem.item_id
    exists_query = select(NewCharacterItem.id).where(NewCharacterItem.item_id == item_id).limit(1)
    result = await db.execute(exists_query)
    is_in_inventory = result.scalar_one_or_none() is not None

    if is_in_inventory:
        # Consider refining this error or the check to be guild-specific for inventory.
        raise ValueError("Item cannot be deleted as it is currently in a character's inventory (global check).")

    # If we've reached here, db_item is confirmed to be from the correct guild.
    await db.delete(db_item)
    await db.commit()
    return db_item
