import uuid
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload # Although not strictly needed for this simple model, good practice

from bot.database.models import RPGCharacter # Our new SQLAlchemy model
from bot.api.schemas.rpg_character_schemas import RPGCharacterCreate, RPGCharacterUpdate # Our Pydantic schemas

async def create_rpg_character(db: AsyncSession, character: RPGCharacterCreate) -> RPGCharacter:
    """
    Creates a new RPG character in the database.
    """
    db_character = RPGCharacter(
        name=character.name,
        class_name=character.class_name,
        level=character.level,
        health=character.health,
        mana=character.mana
        # id, created_at, updated_at are handled by the database/model defaults
    )
    db.add(db_character)
    await db.commit()
    await db.refresh(db_character)
    return db_character

async def get_rpg_character(db: AsyncSession, character_id: uuid.UUID) -> Optional[RPGCharacter]:
    """
    Retrieves an RPG character by its ID.
    """
    result = await db.execute(select(RPGCharacter).filter(RPGCharacter.id == character_id))
    return result.scalars().first()

async def get_rpg_characters(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[RPGCharacter]:
    """
    Retrieves a list of RPG characters with pagination.
    """
    result = await db.execute(
        select(RPGCharacter).offset(skip).limit(limit)
    )
    return result.scalars().all()

async def update_rpg_character(db: AsyncSession, character_id: uuid.UUID, character_update: RPGCharacterUpdate) -> Optional[RPGCharacter]:
    """
    Updates an existing RPG character.
    Returns the updated character or None if not found.
    """
    db_character = await get_rpg_character(db, character_id)
    if db_character is None:
        return None

    update_data = character_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_character, key, value)

    # created_at is not changed, updated_at should be handled by onupdate
    db.add(db_character) # Add to session to mark as dirty
    await db.commit()
    await db.refresh(db_character)
    return db_character

async def delete_rpg_character(db: AsyncSession, character_id: uuid.UUID) -> Optional[RPGCharacter]:
    """
    Deletes an RPG character by its ID.
    Returns the deleted character object or None if not found.
    """
    db_character = await get_rpg_character(db, character_id)
    if db_character is None:
        return None

    await db.delete(db_character)
    await db.commit()
    return db_character
