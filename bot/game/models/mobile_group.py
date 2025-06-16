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
        super().__init__(**data)
        if self.id is None:
            self.id = str(uuid.uuid4())
        if not hasattr(self, 'name_i18n') or not self.name_i18n:
            self.name_i18n = {"en": "Default Mobile Group Name"}
        if not hasattr(self, 'description_i18n') or self.description_i18n is None:
            self.description_i18n = {}
        if not hasattr(self, 'member_ids') or self.member_ids is None:
            self.member_ids = []
        if not hasattr(self, 'state_variables') or self.state_variables is None:
            self.state_variables = {}
        if not hasattr(self, 'is_active'):
            self.is_active = True


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
