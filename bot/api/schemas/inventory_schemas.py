from pydantic import BaseModel, UUID4 as PydanticUUID
from datetime import datetime
from typing import Optional, List
from .item_schemas import NewItemRead # Relative import

class NewCharacterItemBase(BaseModel):
    item_id: PydanticUUID # This should be the ID of a NewItem
    quantity: int = 1

class NewCharacterItemCreate(NewCharacterItemBase):
    pass

class NewCharacterItemUpdate(BaseModel): # Only quantity can be updated
    quantity: int

class NewCharacterItemRead(NewCharacterItemBase):
    id: PydanticUUID
    character_id: str # Character.id is String in the ORM model
    created_at: datetime
    updated_at: datetime
    item: NewItemRead # Nested NewItem details

    class Config:
        from_attributes = True

# Schema for the GET /characters/{character_id}/inventory endpoint
class InventoryItemRead(BaseModel):
    item: NewItemRead # Details of the item
    quantity: int     # Quantity of this item in the character's inventory

    class Config:
        from_attributes = True
