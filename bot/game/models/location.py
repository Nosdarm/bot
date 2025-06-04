# bot/game/models/location.py
import uuid 
import json # For handling JSON string fields if necessary
from typing import Dict, Any, Optional, List

from bot.game.models.base_model import BaseModel
from bot.utils.i18n_utils import get_i18n_text # Import the new utility

class Location(BaseModel):
    def __init__(self, 
                 id: Optional[str] = None, 
                 name_i18n: Optional[Dict[str, str]] = None,
                 description_template_i18n: Optional[Dict[str, str]] = None, # From template
                 descriptions_i18n: Optional[Dict[str, str]] = None, # Instance specific override
                 static_name: Optional[str] = None,      
                 static_connections: Optional[str] = None, 
                 selected_language: Optional[str] = "en", # Language context
                 # Backward compatibility for old fields
                 name: Optional[str] = None, 
                 description_template: Optional[str] = None,
                 **kwargs):
        super().__init__(id=id)

        self.selected_language = selected_language if selected_language else "en"

        # Handle name_i18n and backward compatibility for 'name'
        if name_i18n is not None:
            self.name_i18n = name_i18n
        elif name is not None: # Backwards compatibility for plain name
            self.name_i18n = {self.selected_language: name}
        else: # Default if neither i18n nor plain name is provided
            self.name_i18n = {self.selected_language: f"Unknown Location {self.id}"}

        # Handle description_template_i18n (from template)
        if description_template_i18n is not None:
            self.description_template_i18n = description_template_i18n
        elif description_template is not None: # Backwards compatibility for plain description_template
            self.description_template_i18n = {self.selected_language: description_template}
        else: # Default
            self.description_template_i18n = {self.selected_language: "This is a mysterious place."}

        # Handle descriptions_i18n (instance-specific override)
        if descriptions_i18n is not None:
            if isinstance(descriptions_i18n, str): # If it's a plain string, assume it's for selected_language
                try:
                    # Attempt to parse if it's a JSON string representing a dict
                    parsed_dict = json.loads(descriptions_i18n)
                    if isinstance(parsed_dict, dict):
                        self.descriptions_i18n = parsed_dict
                    else: # Not a dict, treat as plain text for selected_language
                         self.descriptions_i18n = {self.selected_language: descriptions_i18n}
                except json.JSONDecodeError: # Not JSON, treat as plain text for selected_language
                    self.descriptions_i18n = {self.selected_language: descriptions_i18n}
            elif isinstance(descriptions_i18n, dict):
                self.descriptions_i18n = descriptions_i18n
            else: # Not a string or dict, problematic, initialize empty
                 self.descriptions_i18n = {}
        else:
            self.descriptions_i18n = {} # Default to empty dict (no instance override)


        self.static_name: Optional[str] = static_name
        self.static_connections: Optional[str] = static_connections
        
        self.exits: List[Dict[str, str]] = kwargs.pop('exits', [])
        
        self.guild_id: Optional[str] = kwargs.pop('guild_id', None)
        self.template_id: Optional[str] = kwargs.pop('template_id', None)
        self.is_active: bool = kwargs.pop('is_active', True)
        self.state: Dict[str, Any] = kwargs.pop('state', {})

        self.__dict__.update(kwargs)

    def to_dict_for_i18n(self) -> Dict[str, Any]:
        """Helper to provide a dictionary structure for get_i18n_text."""
        return {
            "name_i18n": self.name_i18n,
            "descriptions_i18n": self.descriptions_i18n, # Instance specific
            "description_template_i18n": self.description_template_i18n, # Template
            "id": self.id
        }

    @property
    def name(self) -> str:
        """Provides the internationalized name for the location."""
        lang_to_use = self.selected_language if self.selected_language else "en"
        # get_i18n_text will also use self.id as a fallback if name_i18n is empty or field is missing
        return get_i18n_text(self.to_dict_for_i18n(), "name", lang_to_use, "en")

    @property
    def display_description(self) -> str:
        """
        Provides the internationalized description for display.
        Prioritizes instance-specific descriptions_i18n, then template_description_i18n.
        """
        lang_to_use = self.selected_language if self.selected_language else "en"

        # Check instance-specific description first
        # We pass the full i18n dict for 'descriptions' to get_i18n_text
        data_for_i18n = self.to_dict_for_i18n()

        instance_desc = get_i18n_text(data_for_i18n, "descriptions", lang_to_use, "en")

        # Check if a meaningful description was found from instance_specific descriptions
        # get_i18n_text returns "field_prefix not found" if nothing is found.
        if instance_desc and not instance_desc.startswith("descriptions not found"):
            return instance_desc

        # Fallback to template description
        template_desc = get_i18n_text(data_for_i18n, "description_template", lang_to_use, "en")
        if template_desc and not template_desc.startswith("description_template not found"):
            return template_desc

        return "A location shrouded in mystery." # Ultimate fallback

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            "name_i18n": self.name_i18n,
            "description_template_i18n": self.description_template_i18n,
            "descriptions_i18n": self.descriptions_i18n,
            "static_name": self.static_name,
            "static_connections": self.static_connections,
            "selected_language": self.selected_language,
            "exits": self.exits,
            "guild_id": self.guild_id,
            "template_id": self.template_id,
            "is_active": self.is_active,
            "state": self.state,
            # Include resolved name and description for convenience if needed by consumers of to_dict
            "name": self.name,
            "display_description": self.display_description
        })
        # Add any other attributes that were set via kwargs during __init__
        # that are not explicitly listed but are part of self.__dict__
        # This part might need refinement if some kwargs are not meant to be serialized.
        # For now, assuming relevant fields are explicitly handled or are simple types.
        # current_explicit_keys = set(data.keys()) | {'_id', 'id'} # BaseModel might use _id
        # for key, value in self.__dict__.items():
        #     if key not in current_explicit_keys and not key.startswith('_'):
        #         data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        data_copy = data.copy()

        # Ensure selected_language is determined before being used for defaults
        selected_lang_val = data_copy.get('selected_language', "en")
        data_copy['selected_language'] = selected_lang_val # Ensure it's in the dict for __init__

        # Handle backward compatibility for name
        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {selected_lang_val: data_copy.pop("name")}
        
        # Handle backward compatibility for description_template
        if "description_template" in data_copy and "description_template_i18n" not in data_copy:
            data_copy["description_template_i18n"] = {selected_lang_val: data_copy.pop("description_template")}

        # Handle descriptions_i18n if it's a JSON string in data or plain string
        if "descriptions_i18n" in data_copy:
            descriptions_val = data_copy["descriptions_i18n"]
            if isinstance(descriptions_val, str):
                try:
                    parsed_dict = json.loads(descriptions_val)
                    if isinstance(parsed_dict, dict):
                        data_copy["descriptions_i18n"] = parsed_dict
                    else: # Not a dict, treat as plain text for selected_lang
                        data_copy["descriptions_i18n"] = {selected_lang_val: descriptions_val}
                except json.JSONDecodeError: # Not JSON, treat as plain text
                    data_copy["descriptions_i18n"] = {selected_lang_val: descriptions_val}
            # If it's already a dict, it will be passed as is.
            # If it's some other type, it might cause issues or be ignored by __init__.
        
        return cls(**data_copy)
