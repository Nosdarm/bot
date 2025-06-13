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

async def get_new_item(db: AsyncSession, item_id: UUID) -> NewItem | None:
    """
    Retrieves a single item by its ID.
    """
    result = await db.execute(select(NewItem).where(NewItem.id == item_id))
    return result.scalar_one_or_none()

async def get_new_items(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[NewItem]:
    """
    Retrieves a list of items with pagination.
    """
    result = await db.execute(
        select(NewItem).offset(skip).limit(limit)
    )
    return list(result.scalars().all())

async def update_new_item(db: AsyncSession, item_id: UUID, item_update: NewItemUpdate) -> NewItem | None:
    """
    Updates an existing item.
    """
    db_item = await get_new_item(db, item_id)
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

async def delete_new_item(db: AsyncSession, item_id: UUID) -> NewItem | None:
    """
    Deletes an item after checking if it's in any character's inventory.
    """
    # Check if the item is in any NewCharacterItem record
    exists_query = select(NewCharacterItem.id).where(NewCharacterItem.item_id == item_id).limit(1)
    result = await db.execute(exists_query)
    is_in_inventory = result.scalar_one_or_none() is not None

    if is_in_inventory:
        # from fastapi import HTTPException
        # raise HTTPException(status_code=400, detail="Item cannot be deleted as it is currently in a character's inventory")
        # For now, raising a generic exception or returning None, API layer should handle.
        # Consider a custom exception type e.g. ItemInUseError
        raise ValueError("Item cannot be deleted as it is currently in a character's inventory")

    db_item = await get_new_item(db, item_id)
    if db_item is None:
        return None

    await db.delete(db_item)
    await db.commit()
    return db_item
