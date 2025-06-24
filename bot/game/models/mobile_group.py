from __future__ import annotations
from typing import Optional, Dict, Any, List
import uuid

from bot.game.models.base_model import BaseModel

class MobileGroup(BaseModel):
    """
    Represents a mobile group of entities, such as caravans, patrols, or migrating herds.
    These groups can move between locations and may have specific members (NPCs or characters).
    """
    id: Optional[str] = None
    guild_id: str
    name_i18n: Dict[str, str]
    description_i18n: Optional[Dict[str, str]] = None
    current_location_id: Optional[str] = None
    member_ids: Optional[List[str]] = None  # List of GlobalNpc IDs or Character IDs
    destination_location_id: Optional[str] = None
    state_variables: Optional[Dict[str, Any]] = None
    is_active: bool = True

    def __init__(self, **data: Any):
        super().__init__(id=data.pop('id', None)) # Pass ID to custom BaseModel's init

        self.guild_id = data.pop("guild_id")
        self.name_i18n = data.pop("name_i18n", {"en": "Default Mobile Group Name"})
        self.description_i18n = data.pop("description_i18n", {})
        self.current_location_id = data.pop("current_location_id", None)
        self.member_ids = data.pop("member_ids", [])
        self.destination_location_id = data.pop("destination_location_id", None)
        self.state_variables = data.pop("state_variables", {})
        self.is_active = data.pop("is_active", True)

        # Store any other provided data
        for key, value in data.items():
            setattr(self, key, value)

        if not self.name_i18n: # Ensure name_i18n is not empty after pop
            self.name_i18n = {"en": "Default Mobile Group Name"}
        if self.member_ids is None: # Ensure member_ids is a list
             self.member_ids = []
        if self.state_variables is None: # Ensure state_variables is a dict
             self.state_variables = {}


    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "guild_id": self.guild_id,
            "name_i18n": self.name_i18n or {},
            "description_i18n": self.description_i18n or {},
            "current_location_id": self.current_location_id,
            "member_ids": self.member_ids or [],
            "destination_location_id": self.destination_location_id,
            "state_variables": self.state_variables or {},
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MobileGroup:
        data.setdefault('id', str(uuid.uuid4()))
        data.setdefault('name_i18n', {"en": "Default Mobile Group Name"})
        data.setdefault('description_i18n', {})
        data.setdefault('member_ids', [])
        data.setdefault('state_variables', {})
        data.setdefault('is_active', True)
        # guild_id must be present in data for a valid MobileGroup
        if 'guild_id' not in data:
            raise ValueError("guild_id is required for MobileGroup")
        return cls(**data)

    def __repr__(self) -> str:
        return f"<MobileGroup(id='{self.id}', name='{self.name_i18n.get('en', 'N/A')}', guild_id='{self.guild_id}')>"
