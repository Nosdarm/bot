import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Response

from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.dependencies import get_db_session # Assuming this provides AsyncSession
from bot.api.schemas.rpg_character_schemas import (
    RPGCharacterCreate,
    RPGCharacterUpdate,
    RPGCharacterResponse
)
from bot.database import rpg_character_crud # CRUD functions

router = APIRouter(
    prefix="/characters", # This prefix will be applied to all routes in this router
    tags=["RPG Characters"], # Tag for Swagger UI grouping
)

@router.post("/", response_model=RPGCharacterResponse, status_code=status.HTTP_201_CREATED)
async def create_new_character(
    character: RPGCharacterCreate,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Create a new RPG character.
    """
    # Pydantic already validates input based on RPGCharacterCreate schema
    # Additional validation for non-negative numbers is in the Pydantic models
    return await rpg_character_crud.create_rpg_character(db=db, character=character)

@router.get("/", response_model=List[RPGCharacterResponse])
async def list_all_characters(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Get a list of all RPG characters. Supports pagination via skip and limit.
    """
    characters = await rpg_character_crud.get_rpg_characters(db=db, skip=skip, limit=limit)
    return characters

@router.get("/{character_id}", response_model=RPGCharacterResponse)
async def get_single_character(
    character_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Get details of a specific RPG character by its ID.
    """
    db_character = await rpg_character_crud.get_rpg_character(db=db, character_id=character_id)
    if db_character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return db_character

@router.put("/{character_id}", response_model=RPGCharacterResponse)
async def update_existing_character(
    character_id: uuid.UUID,
    character_update: RPGCharacterUpdate,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Update an existing RPG character's details.
    Only provided fields will be updated.
    """
    # Pydantic validates input based on RPGCharacterUpdate
    # Non-negative checks are in the Pydantic model
    updated_character = await rpg_character_crud.update_rpg_character(
        db=db, character_id=character_id, character_update=character_update
    )
    if updated_character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    return updated_character

@router.delete("/{character_id}", status_code=status.HTTP_200_OK)
async def delete_existing_character(
    character_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Delete an RPG character by its ID.
    """
    deleted_character = await rpg_character_crud.delete_rpg_character(db=db, character_id=character_id)
    if deleted_character is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    # Return a success message or an empty 204 No Content.
    # The requirement asks for 200 OK with a message or empty response.
    # FastAPI handles 204 by default if no content is returned.
    # To force 200 with a message:
    return {"message": "Character deleted successfully"}
    # If an empty response with 200 is preferred over 204, use Response(status_code=status.HTTP_200_OK)
