from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from uuid import UUID

from ...database import inventory_crud, item_crud # For item checks if needed, and character_crud placeholder
from ...database.models import Character # To check character existence
# We need a way to get a character. Assuming a character_crud.py exists or similar
# For now, let's define a placeholder if direct db access for simple get is acceptable:
from ...database.models import Character as CharacterModel # ORM Model
# from ....database import character_crud # Placeholder for actual character CRUD module

from ..schemas.inventory_schemas import (
    NewCharacterItemRead, 
    NewCharacterItemCreate, 
    # NewCharacterItemUpdate, # Not used directly in this router's current spec
    InventoryItemRead
)
from ..dependencies import get_db_session

router = APIRouter()

# Placeholder for character existence check - replace with actual CRUD if available
async def get_character_orm(db: AsyncSession, character_id: str) -> Optional[CharacterModel]:
    """Helper to fetch a character ORM object."""
    return await db.get(CharacterModel, character_id)


@router.get("/inventory", response_model=List[InventoryItemRead])
async def get_character_inventory_endpoint(character_id: str, db: AsyncSession = Depends(get_db_session)):
    character = await get_character_orm(db, character_id)
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")

    try:
        character_items = await inventory_crud.get_character_inventory(db=db, character_id=character_id)
        # Transform List[NewCharacterItem (ORM)] to List[InventoryItemRead (Pydantic)]
        # NewCharacterItem.item is already eager loaded by the CRUD function.
        response_items = []
        for char_item in character_items:
            if char_item.item: # Should always be true due to joinedload and FK constraint
                response_items.append(
                    InventoryItemRead(
                        item=char_item.item, # Pydantic will convert NewItem ORM to NewItemRead
                        quantity=char_item.quantity
                    )
                )
            else:
                # This case should ideally not happen if data integrity is maintained
                # and item is correctly eager loaded. Log an error if it does.
                # Consider raising 500 if item details are unexpectedly missing.
                pass # Or log: print(f"Warning: CharacterItem {char_item.id} missing item details.")

        return response_items
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")


@router.post("/inventory/add", response_model=NewCharacterItemRead)
async def add_item_to_inventory_endpoint(character_id: str, item_add_data: NewCharacterItemCreate, db: AsyncSession = Depends(get_db_session)):
    try:
        # Character existence is checked within add_item_to_character_inventory
        added_item_entry = await inventory_crud.add_item_to_character_inventory(
            db=db, 
            character_id=character_id, 
            item_id=item_add_data.item_id, 
            quantity=item_add_data.quantity
        )
        return added_item_entry
    except ValueError as ve:
        if "Character not found" in str(ve):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
        elif "Item template not found" in str(ve):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item template not found")
        elif "Quantity to add must be positive" in str(ve):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
        else: # Other ValueErrors from CRUD
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except IntegrityError: # Should be rare if checks are in place, but good for safety
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database integrity error while adding item.")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")


@router.post("/inventory/remove", response_model=Optional[NewCharacterItemRead])
async def remove_item_from_inventory_endpoint(
    character_id: str, 
    item_remove_data: NewCharacterItemCreate, # Using NewCharacterItemCreate for item_id and quantity
    response: Response, # Moved here
    db: AsyncSession = Depends(get_db_session) # Default argument now at the end
):
    try:
        # Character existence is implicitly checked by inventory_crud function if item not found for char.
        updated_item_entry = await inventory_crud.remove_item_from_character_inventory(
            db=db,
            character_id=character_id,
            item_id=item_remove_data.item_id,
            quantity_to_remove=item_remove_data.quantity
        )
        if updated_item_entry is None: # Item was fully removed
            response.status_code = status.HTTP_204_NO_CONTENT
            return None 
        return updated_item_entry
    except ValueError as ve:
        if "Character not found" in str(ve): # Should be caught by character check if implemented before call
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
        elif "Item not found in character's inventory" in str(ve):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in inventory")
        elif "Cannot remove more items than available" in str(ve):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient quantity to remove")
        elif "Quantity to remove must be positive" in str(ve):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
        else: # Other ValueErrors from CRUD
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except IntegrityError:
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database integrity error while removing item.")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {str(e)}")
