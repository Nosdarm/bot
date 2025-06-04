# bot/game/models/location.py
import uuid 
import json # For handling JSON string fields if necessary
from typing import Dict, Any, Optional, List

from bot.game.models.base_model import BaseModel

class Location(BaseModel):
    def __init__(self, 
                 id: Optional[str] = None, 
                 name_i18n: Optional[Dict[str, str]] = None,
                 description_template_i18n: Optional[Dict[str, str]] = None,
                 descriptions_i18n: Optional[Dict[str, str]] = None, # Now a dict
                 static_name: Optional[str] = None,      
                 static_connections: Optional[str] = None, 
                 # Backward compatibility for old fields
                 name: Optional[str] = None, 
                 description_template: Optional[str] = None,
                 **kwargs):
        super().__init__(id=id)

        # Handle name_i18n and backward compatibility for 'name'
        if name_i18n is not None:
            self.name_i18n = name_i18n
        elif name is not None:
            self.name_i18n = {"en": name}
        else:
            self.name_i18n = {"en": "Unknown Location"} # Default

        # Handle description_template_i18n and backward compatibility
        if description_template_i18n is not None:
            self.description_template_i18n = description_template_i18n
        elif description_template is not None:
            self.description_template_i18n = {"en": description_template}
        else:
            self.description_template_i18n = {"en": "This is a mysterious place with no clear description."} # Default

        # Handle descriptions_i18n (already i18n, ensure it's a dict)
        if descriptions_i18n is not None:
            if isinstance(descriptions_i18n, str):
                try:
                    self.descriptions_i18n = json.loads(descriptions_i18n)
                except json.JSONDecodeError:
                    self.descriptions_i18n = {"en": descriptions_i18n} # Treat as plain text if not JSON
            else:
                self.descriptions_i18n = descriptions_i18n
        else:
            self.descriptions_i18n = {} # Default to empty dict

        self.static_name: Optional[str] = static_name
        self.static_connections: Optional[str] = static_connections
        
        self.exits: List[Dict[str, str]] = kwargs.pop('exits', [])
        
        self.guild_id: Optional[str] = kwargs.pop('guild_id', None) # Ensure guild_id is captured
        self.template_id: Optional[str] = kwargs.pop('template_id', None)
        self.is_active: bool = kwargs.pop('is_active', True)
        self.state: Dict[str, Any] = kwargs.pop('state', {}) # For dynamic state variables

        self.__dict__.update(kwargs) # Capture any other dynamic fields

    @property
    def name(self) -> str:
        """Provides a plain text name, derived from name_i18n."""
        # This assumes a default language (e.g., 'en') or some way to determine preferred lang.
        # For simplicity, using 'en' or the first available if 'en' is not present.
        default_lang = "en"
        if self.name_i18n:
            return self.name_i18n.get(default_lang, next(iter(self.name_i18n.values()), str(self.id)))
        return str(self.id) # Fallback

    @property
    def display_description(self) -> str:
        """
        Provides a plain text description for display.
        Prioritizes instance-specific descriptions_i18n, then template_description_i18n.
        """
        default_lang = "en" # This could be configurable or context-aware

        # Try instance-specific description first
        if self.descriptions_i18n and isinstance(self.descriptions_i18n, dict):
            desc = self.descriptions_i18n.get(default_lang)
            if desc: return desc
            # Fallback to first available language in instance-specific descriptions
            if self.descriptions_i18n.values():
                return next(iter(self.descriptions_i18n.values()))

        # Fallback to template description
        if self.description_template_i18n and isinstance(self.description_template_i18n, dict):
            desc = self.description_template_i18n.get(default_lang)
            if desc: return desc
            # Fallback to first available language in template descriptions
            if self.description_template_i18n.values():
                return next(iter(self.description_template_i18n.values()))

        return "A location shrouded in mystery." # Ultimate fallback

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict() # Gets 'id' or '_id'
        data.update({
            "name_i18n": self.name_i18n,
            "description_template_i18n": self.description_template_i18n,
            "descriptions_i18n": self.descriptions_i18n, # Serialized as dict
            "static_name": self.static_name,
            "static_connections": self.static_connections,
            "exits": self.exits,
            "guild_id": self.guild_id,
            "template_id": self.template_id,
            "is_active": self.is_active,
            "state": self.state
        })
        # Add any other attributes that were set via kwargs during __init__
        # and are not explicitly listed but are part of self.__dict__
        for key, value in self.__dict__.items():
            if key not in data and key not in ['_id', 'id'] and not key.startswith('_'): # Avoid private/internal
                data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        data_copy = data.copy() # Work with a copy

        # Handle backward compatibility for name
        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {"en": data_copy.pop("name")}
        
        # Handle backward compatibility for description_template
        if "description_template" in data_copy and "description_template_i18n" not in data_copy:
            data_copy["description_template_i18n"] = {"en": data_copy.pop("description_template")}

        # Handle descriptions_i18n if it's a JSON string in data
        if "descriptions_i18n" in data_copy and isinstance(data_copy["descriptions_i18n"], str):
            try:
                data_copy["descriptions_i18n"] = json.loads(data_copy["descriptions_i18n"])
            except json.JSONDecodeError:
                # If it's a string but not valid JSON, wrap it in 'en' key or log error
                data_copy["descriptions_i18n"] = {"en": data_copy["descriptions_i18n"]}
        
        return cls(**data_copy)
