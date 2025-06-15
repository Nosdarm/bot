from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from typing import List
from uuid import UUID

from bot.database import item_crud # Adjusted path
from bot.api.schemas.item_schemas import NewItemCreate, NewItemRead, NewItemUpdate # Adjusted path
from bot.api.dependencies import get_db_session # Adjusted path

router = APIRouter()

@router.post("/", response_model=NewItemRead, status_code=status.HTTP_201_CREATED)
async def create_item_endpoint(item: NewItemCreate, db: AsyncSession = Depends(get_db_session)):
    try:
        created_item = await item_crud.create_new_item(db=db, item=item)
        return created_item
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item with this name already exists")
    except Exception as e:
        # Generic error handler for unexpected errors
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/", response_model=List[NewItemRead])
async def read_items_endpoint(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db_session)):
    try:
        items = await item_crud.get_new_items(db=db, skip=skip, limit=limit)
        return items
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/{item_id}", response_model=NewItemRead)
async def read_item_endpoint(item_id: UUID, db: AsyncSession = Depends(get_db_session)):
    try:
        db_item = await item_crud.get_new_item(db=db, item_id=item_id)
        if db_item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
        return db_item
    except HTTPException: # Re-raise HTTPException
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")

@router.put("/{item_id}", response_model=NewItemRead)
async def update_item_endpoint(item_id: UUID, item: NewItemUpdate, db: AsyncSession = Depends(get_db_session)):
    try:
        updated_item = await item_crud.update_new_item(db=db, item_id=item_id, item_update=item)
        if updated_item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
        return updated_item
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Another item with this name already exists")
    except HTTPException: # Re-raise HTTPException
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")

@router.patch("/{item_id}", response_model=NewItemRead)
async def patch_item_endpoint(item_id: UUID, item: NewItemUpdate, db: AsyncSession = Depends(get_db_session)):
    # The item_crud.update_new_item function should use model_dump(exclude_unset=True)
    # from the Pydantic model, which is suitable for PATCH behavior.
    try:
        updated_item = await item_crud.update_new_item(db=db, item_id=item_id, item_update=item)
        if updated_item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
        return updated_item
    except IntegrityError: # This will be caught if update_new_item re-raises it
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Another item with this name already exists or other integrity violation.")
    except HTTPException: # Re-raise HTTPException if already one (e.g. 404)
        raise
    except Exception as e: # Catch any other unexpected errors from CRUD or elsewhere
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")

@router.delete("/{item_id}", response_model=NewItemRead)
async def delete_item_endpoint(item_id: UUID, db: AsyncSession = Depends(get_db_session)):
    try:
        deleted_item = await item_crud.delete_new_item(db=db, item_id=item_id)
        if deleted_item is None: # This case implies item was not found before attempting delete or after check (if logic changes)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found or already deleted")
        return deleted_item
    except ValueError as ve: # Catch ValueError from CRUD (e.g., item in inventory)
        if "Item cannot be deleted as it is currently in a character's inventory" in str(ve):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item cannot be deleted as it is currently in a character's inventory")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except HTTPException: # Re-raise HTTPException
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")
