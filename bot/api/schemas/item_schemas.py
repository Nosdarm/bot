from pydantic import BaseModel, UUID4 as PydanticUUID  # Use UUID4 for Pydantic
from datetime import datetime
from typing import Optional, Dict, Any

class NewItemBase(BaseModel):
    name: str
    description: Optional[str] = None
    item_type: str # e.g., "weapon", "armor", "consumable"
    item_metadata: Optional[Dict[str, Any]] = None

    class Config:
        # Ensure Pydantic can map item_metadata to a field named 'metadata' if SQLAlchemy model uses name="metadata"
        # For ORM mode, this is handled by SQLAlchemy attribute name, but for validation against dicts:
        populate_by_name = True
        # alias_generator = lambda field_name: 'metadata' if field_name == 'item_metadata' else field_name


class NewItemCreate(NewItemBase):
    pass

class NewItemUpdate(BaseModel): # As per spec, inherits BaseModel directly
    name: Optional[str] = None
    description: Optional[str] = None
    item_type: Optional[str] = None
    item_metadata: Optional[Dict[str, Any]] = None

class NewItemRead(NewItemBase):
    id: PydanticUUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
