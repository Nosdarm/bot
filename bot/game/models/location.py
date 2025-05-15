# bot/game/models/location.py
import uuid # May not be strictly needed here if IDs are generated elsewhere, but keep for BaseModel clarity
from typing import Dict, Any, Optional, List

from bot.game.models.base_model import BaseModel # Ensure this import is correct

class Location(BaseModel):
    def __init__(self, id: Optional[str] = None, name: str = "Неизвестная Локация", description_template: str = "Это загадочное место без четкого описания.", **kwargs):
        super().__init__(id=id)
        self.name: str = name
        self.description_template: str = description_template
        # --- Field for Exits ---
        self.exits: List[Dict[str, str]] = kwargs.pop('exits', []) # List of {"direction": str, "target_location_id": str}
        # --- ---
        self.__dict__.update(kwargs)

    def to_dict(self) -> Dict[str, Any]:
         return super().to_dict()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
         return cls(**data)