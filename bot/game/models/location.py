# bot/game/models/location.py
import uuid # May not be strictly needed here if IDs are generated elsewhere, but keep for BaseModel clarity
from typing import Dict, Any, Optional, List

from bot.game.models.base_model import BaseModel # Ensure this import is correct

class Location(BaseModel):
    def __init__(self, 
                 id: Optional[str] = None, 
                 name: str = "Неизвестная Локация", 
                 description_template: str = "Это загадочное место без четкого описания.", 
                 descriptions_i18n: Optional[str] = None, # JSON string for multilingual descriptions
                 static_name: Optional[str] = None,       # Static identifier for the location
                 static_connections: Optional[str] = None, # JSON string for static connections
                 **kwargs):
        super().__init__(id=id)
        self.name: str = name # Instance-specific or display name
        self.description_template: str = description_template # Base description, maybe a fallback or template key
        
        # New fields for i18n and static definitions
        self.descriptions_i18n: Optional[str] = descriptions_i18n
        self.static_name: Optional[str] = static_name
        self.static_connections: Optional[str] = static_connections
        
        # --- Field for Exits ---
        # These are likely dynamic/instance-specific exits, separate from static_connections
        self.exits: List[Dict[str, str]] = kwargs.pop('exits', []) # List of {"direction": str, "target_location_id": str}
        # --- ---
        
        # Ensure any other relevant fields from kwargs are also set.
        # This includes fields like template_id, guild_id, state_variables, is_active from the database schema.
        self.__dict__.update(kwargs)

    def to_dict(self) -> Dict[str, Any]:
         return super().to_dict()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
         return cls(**data)