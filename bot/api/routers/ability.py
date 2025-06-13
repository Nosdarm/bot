# bot/api/routers/ability.py
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
import uuid # For generating ability IDs
import logging
from typing import List

from bot.api.dependencies import get_db_session
from bot.api.schemas.ability_schemas import AbilityCreate, AbilityUpdate, AbilityResponse
from bot.database.models import Ability

logger = logging.getLogger(__name__)
router = APIRouter() # Prefix will be /api/v1/guilds/{guild_id}/abilities from main.py

@router.post("/", response_model=AbilityResponse, status_code=status.HTTP_201_CREATED, summary="Create a new ability for the guild")
async def create_ability(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    ability_data: AbilityCreate = Depends(),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Attempting to create ability '{ability_data.name_i18n.get('en', 'Unknown Name')}' in guild {guild_id}")
    ability_id = str(uuid.uuid4())

    db_ability = Ability(
        id=ability_id,
        guild_id=guild_id,
        **ability_data.dict()
    )
    db.add(db_ability)
    try:
        await db.commit()
        await db.refresh(db_ability)
    except IntegrityError as e: # Should not happen with UUIDs unless other constraints exist
        await db.rollback()
        logger.error(f"IntegrityError creating ability: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create ability due to data integrity issue.")
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating ability: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create ability.")
    return db_ability

@router.get("/", response_model=List[AbilityResponse], summary="List all abilities for the guild")
async def list_abilities(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    skip: int = 0, # Pagination: records to skip
    limit: int = 100, # Pagination: max records to return
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Listing abilities for guild {guild_id} with skip={skip}, limit={limit}")
    stmt = select(Ability).where(Ability.guild_id == guild_id).offset(skip).limit(limit)
    result = await db.execute(stmt)
    abilities = result.scalars().all()
    return abilities

@router.get("/{ability_id}", response_model=AbilityResponse, summary="Get a specific ability by ID")
async def get_ability(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    ability_id: str = Path(..., description="ID of the ability to retrieve"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Fetching ability {ability_id} for guild {guild_id}")
    stmt = select(Ability).where(Ability.id == ability_id, Ability.guild_id == guild_id)
    result = await db.execute(stmt)
    db_ability = result.scalars().first()
    if not db_ability:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ability not found in this guild")
    return db_ability

@router.put("/{ability_id}", response_model=AbilityResponse, summary="Update an ability")
async def update_ability(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    ability_id: str = Path(..., description="ID of the ability to update"),
    ability_update_data: AbilityUpdate = Depends(),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Updating ability {ability_id} in guild {guild_id}")
    stmt = select(Ability).where(Ability.id == ability_id, Ability.guild_id == guild_id)
    result = await db.execute(stmt)
    db_ability = result.scalars().first()

    if not db_ability:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ability not found in this guild")

    update_data = ability_update_data.dict(exclude_unset=True) # Get only fields that were actually sent
    for key, value in update_data.items():
        setattr(db_ability, key, value)

    db.add(db_ability)
    try:
        await db.commit()
        await db.refresh(db_ability)
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating ability {ability_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update ability.")
    return db_ability

@router.delete("/{ability_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an ability")
async def delete_ability(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    ability_id: str = Path(..., description="ID of the ability to delete"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Attempting to delete ability {ability_id} in guild {guild_id}")
    stmt = select(Ability).where(Ability.id == ability_id, Ability.guild_id == guild_id)
    result = await db.execute(stmt)
    db_ability = result.scalars().first()

    if not db_ability:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ability not found in this guild")

    await db.delete(db_ability)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting ability {ability_id}: {e}")
        # Could be an error if the ability is still linked (e.g. to characters, skills)
        # depending on ForeignKey constraints not explicitly defined here but potentially in DB.
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete ability. It might be in use or another error occurred.")
    return # Implicitly returns 204 No Content
