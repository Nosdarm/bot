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
        super().__init__(**data)
        if self.id is None:
            self.id = str(uuid.uuid4())
        if not self.name_i18n:
            self.name_i18n = {"en": "Default Global NPC Name"} # Default if empty
        if self.description_i18n is None:
            self.description_i18n = {}
        if self.state_variables is None:
            self.state_variables = {}

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
