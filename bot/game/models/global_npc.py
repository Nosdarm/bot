from typing import Optional, Dict, Any, List
from bot.game.models.base_model import BaseModel
import uuid

class GlobalNpc(BaseModel):
    id: Optional[str] = None
    guild_id: str
    name_i18n: Dict[str, str]
    description_i18n: Optional[Dict[str, str]] = None
    current_location_id: Optional[str] = None
    npc_template_id: Optional[str] = None
    state_variables: Optional[Dict[str, Any]] = None
    faction_id: Optional[str] = None
    is_active: bool = True

    def __init__(self, **data: Any):
        super().__init__(id=data.pop('id', None)) # Pass ID to custom BaseModel's init

        self.guild_id = data.pop("guild_id")
        self.name_i18n = data.pop("name_i18n", {"en": "Default Global NPC Name"})
        self.description_i18n = data.pop("description_i18n", {})
        self.current_location_id = data.pop("current_location_id", None)
        self.npc_template_id = data.pop("npc_template_id", None)
        self.state_variables = data.pop("state_variables", {})
        self.faction_id = data.pop("faction_id", None)
        self.is_active = data.pop("is_active", True)

        # Store any other provided data, though Pydantic models usually define all fields
        # If this BaseModel is not meant to be a Pydantic model, this is one way to handle extra data.
        # However, for stricter Pydantic-like behavior, you might want to raise an error for unexpected fields.
        for key, value in data.items():
            setattr(self, key, value)

        if not self.name_i18n: # Ensure name_i18n is not empty after pop
            self.name_i18n = {"en": "Default Global NPC Name"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "guild_id": self.guild_id,
            "name_i18n": self.name_i18n or {},
            "description_i18n": self.description_i18n or {},
            "current_location_id": self.current_location_id,
            "npc_template_id": self.npc_template_id,
            "state_variables": self.state_variables or {},
            "faction_id": self.faction_id,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GlobalNpc':
        data.setdefault('id', str(uuid.uuid4()))
        data.setdefault('name_i18n', {"en": "Default Global NPC Name"})
        data.setdefault('description_i18n', {})
        data.setdefault('state_variables', {})
        data.setdefault('is_active', True)
        return cls(**data)
