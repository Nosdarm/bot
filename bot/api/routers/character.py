# bot/api/routers/character.py
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
import uuid # For generating character IDs if not using auto-increment or other DB mechanism
import logging
from typing import List

from bot.api.dependencies import get_db_session
from bot.api.schemas.character_schemas import CharacterCreate, CharacterUpdate, CharacterResponse
from bot.database.models import Character, Player # Player model needed to verify player_id exists

logger = logging.getLogger(__name__)
router = APIRouter() # Prefix will be /api/v1/guilds/{guild_id} from main.py

# Note: guild_id is expected to be a path parameter provided by the include_router prefix in main.py

@router.post(
    "/players/{player_id}/characters/",
    response_model=CharacterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new character for a player"
)
async def create_character_for_player(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    player_id: str = Path(..., description="ID of the player to create the character for"),
    character_data: CharacterCreate = Depends(), # Using Depends for CharacterCreate
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Attempting to create character for player {player_id} in guild {guild_id}")

    # Verify player exists and belongs to the guild
    player_stmt = select(Player).where(Player.id == player_id, Player.guild_id == guild_id)
    result = await db.execute(player_stmt)
    db_player = result.scalars().first()
    if not db_player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player with ID {player_id} not found in guild {guild_id}"
        )

    character_id = str(uuid.uuid4())
    db_character = Character(
        id=character_id,
        player_id=player_id,
        guild_id=guild_id, # Explicitly set guild_id
        **character_data.dict()
    )
    db.add(db_character)
    try:
        await db.commit()
        await db.refresh(db_character)
    except IntegrityError as e: # Catch potential DB errors like FK violations if any
        await db.rollback()
        logger.error(f"IntegrityError creating character for player {player_id}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create character due to data integrity issue.")
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating character for player {player_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create character.")
    return db_character

@router.get(
    "/players/{player_id}/characters/",
    response_model=List[CharacterResponse],
    summary="List all characters for a specific player"
)
async def list_characters_for_player(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    player_id: str = Path(..., description="ID of the player whose characters to list"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Listing characters for player {player_id} in guild {guild_id}")
    # Verify player exists and belongs to the guild (optional, but good for context)
    player_stmt = select(Player).where(Player.id == player_id, Player.guild_id == guild_id)
    result = await db.execute(player_stmt)
    if not result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player with ID {player_id} not found in guild {guild_id}"
        )

    stmt = select(Character).where(Character.player_id == player_id, Character.guild_id == guild_id)
    result = await db.execute(stmt)
    characters = result.scalars().all()
    return characters

@router.get(
    "/characters/{character_id}",
    response_model=CharacterResponse,
    summary="Get a specific character by Character ID"
)
async def get_character(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    character_id: str = Path(..., description="ID of the character to retrieve"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Fetching character {character_id} in guild {guild_id}")
    stmt = select(Character).where(Character.id == character_id, Character.guild_id == guild_id)
    result = await db.execute(stmt)
    db_character = result.scalars().first()
    if not db_character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found in this guild")
    return db_character

@router.put(
    "/characters/{character_id}",
    response_model=CharacterResponse,
    summary="Update a character's details"
)
async def update_character(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    character_id: str = Path(..., description="ID of the character to update"),
    character_update_data: CharacterUpdate = Depends(), # Using Depends for CharacterUpdate
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Updating character {character_id} in guild {guild_id}")
    stmt = select(Character).where(Character.id == character_id, Character.guild_id == guild_id)
    result = await db.execute(stmt)
    db_character = result.scalars().first()

    if not db_character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found in this guild")

    update_data = character_update_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_character, key, value)

    db.add(db_character)
    try:
        await db.commit()
        await db.refresh(db_character)
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating character {character_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update character.")
    return db_character

@router.delete(
    "/characters/{character_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a character"
)
async def delete_character(
    guild_id: str = Path(..., description="Guild ID from path prefix"),
    character_id: str = Path(..., description="ID of the character to delete"),
    db: AsyncSession = Depends(get_db_session)
):
    logger.info(f"Attempting to delete character {character_id} in guild {guild_id}")
    stmt = select(Character).where(Character.id == character_id, Character.guild_id == guild_id)
    result = await db.execute(stmt)
    db_character = result.scalars().first()

    if not db_character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found in this guild")

    await db.delete(db_character)
    try:
        await db.commit()
    except Exception as e: # Could be DB error if character is linked elsewhere with restrict
        await db.rollback()
        logger.error(f"Error deleting character {character_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete character.")
    return # Implicitly returns 204 No Content
