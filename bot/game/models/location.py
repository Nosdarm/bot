# bot/game/models/location.py
import uuid 
import json
import logging # Added for from_dict warnings
from typing import Dict, Any, Optional, List

from bot.game.models.base_model import BaseModel
from bot.utils.i18n_utils import get_i18n_text

logger = logging.getLogger(__name__)

class Location(BaseModel):
    def __init__(self, 
                 id: Optional[str] = None, 
                 name_i18n: Optional[Dict[str, str]] = None,
                 description_template_i18n: Optional[Dict[str, str]] = None,
                 descriptions_i18n: Optional[Dict[str, str]] = None,
                 static_id: Optional[str] = None, # Explicitly add static_id
                 type_i18n: Optional[Dict[str, str]] = None,
                 coordinates: Optional[Dict[str, Any]] = None,
                 exits: Optional[List[Dict[str, Any]]] = None, # Changed to List[Dict] to better match common exit structures
                 neighbor_locations_json: Optional[Dict[str, Any]] = None,
                 generated_details_json: Optional[Dict[str, Any]] = None,
                 ai_metadata_json: Optional[Dict[str, Any]] = None,
                 details_i18n: Optional[Dict[str, str]] = None,
                 tags_i18n: Optional[Dict[str, str]] = None,
                 atmosphere_i18n: Optional[Dict[str, str]] = None,
                 features_i18n: Optional[Dict[str, str]] = None,
                 channel_id: Optional[str] = None, # Kept as str based on some test data
                 image_url: Optional[str] = None,
                 points_of_interest_json: Optional[List[Dict[str, Any]]] = None,
                 on_enter_events_json: Optional[List[Dict[str, Any]]] = None,
                 moderation_request_id: Optional[str] = None,
                 created_by_user_id: Optional[str] = None,
                 state_variables: Optional[Dict[str, Any]] = None, # Renamed from state
                 selected_language: Optional[str] = "en",
                 # Backward compatibility
                 name: Optional[str] = None, 
                 description_template: Optional[str] = None,
                 static_name: Optional[str] = None, # Kept for backward compatibility if used by old data
                 static_connections: Optional[str] = None, # Kept for backward compatibility
                 guild_id: Optional[str] = None,
                 template_id: Optional[str] = None,
                 is_active: bool = True,
                 state: Optional[Dict[str, Any]] = None, # Old state field, will be merged into state_variables
                 **kwargs): # Catch any other unexpected kwargs

        super().__init__(id=id)

        self.selected_language = selected_language if selected_language else "en"

        # Handle name_i18n and backward compatibility for 'name'
        if name_i18n is not None:
            self.name_i18n = name_i18n
        elif name is not None:
            self.name_i18n = {self.selected_language: name}
        else:
            self.name_i18n = {self.selected_language: f"Unknown Location {self.id}"}

        # Handle description_template_i18n (from template)
        if description_template_i18n is not None:
            self.description_template_i18n = description_template_i18n
        elif description_template is not None:
            self.description_template_i18n = {self.selected_language: description_template}
        else:
            self.description_template_i18n = {self.selected_language: "This is a mysterious place."}

        # Handle descriptions_i18n (instance-specific override)
        final_descriptions_i18n = {}
        if descriptions_i18n is not None:
            if isinstance(descriptions_i18n, str):
                try:
                    parsed_dict = json.loads(descriptions_i18n)
                    if isinstance(parsed_dict, dict): final_descriptions_i18n = parsed_dict
                    else: final_descriptions_i18n = {self.selected_language: descriptions_i18n}
                except json.JSONDecodeError:
                    final_descriptions_i18n = {self.selected_language: descriptions_i18n}
            elif isinstance(descriptions_i18n, dict):
                final_descriptions_i18n = descriptions_i18n
        self.descriptions_i18n = final_descriptions_i18n

        self.static_id: Optional[str] = static_id
        self.type_i18n: Dict[str, str] = type_i18n if type_i18n is not None else {}
        self.coordinates: Optional[Dict[str, Any]] = coordinates
        self.exits: List[Dict[str, Any]] = exits if exits is not None else [] # Ensure it's a list of dicts
        self.neighbor_locations_json: Optional[Dict[str, Any]] = neighbor_locations_json
        self.generated_details_json: Optional[Dict[str, Any]] = generated_details_json
        self.ai_metadata_json: Optional[Dict[str, Any]] = ai_metadata_json
        self.details_i18n: Optional[Dict[str, str]] = details_i18n
        self.tags_i18n: Optional[Dict[str, str]] = tags_i18n
        self.atmosphere_i18n: Optional[Dict[str, str]] = atmosphere_i18n
        self.features_i18n: Optional[Dict[str, str]] = features_i18n
        self.channel_id: Optional[str] = channel_id
        self.image_url: Optional[str] = image_url
        self.points_of_interest_json: Optional[List[Dict[str, Any]]] = points_of_interest_json
        self.on_enter_events_json: Optional[List[Dict[str, Any]]] = on_enter_events_json
        self.moderation_request_id: Optional[str] = moderation_request_id
        self.created_by_user_id: Optional[str] = created_by_user_id

        # Merge state and state_variables, preferring state_variables
        merged_state = {}
        if isinstance(state, dict): merged_state.update(state)
        if isinstance(state_variables, dict): merged_state.update(state_variables)
        self.state_variables: Dict[str, Any] = merged_state

        # Backward compatibility / other kwargs
        self.static_name: Optional[str] = static_name
        self.static_connections: Optional[str] = static_connections
        self.guild_id: Optional[str] = guild_id
        self.template_id: Optional[str] = template_id
        self.is_active: bool = is_active
        
        # Apply any other kwargs that were not explicitly handled
        # This is risky if kwargs contains fields that clash with properties or methods
        # Filter to only include fields that are part of the intended model structure if possible
        # For now, keeping it simple but be cautious.
        # known_attrs = set(self.__annotations__.keys()) if hasattr(self, '__annotations__') else set()
        # for k, v in kwargs.items():
        #     if k not in known_attrs and not hasattr(self, k): # Avoid overwriting existing or method names
        #         setattr(self, k, v)


    def to_dict_for_i18n(self) -> Dict[str, Any]:
        return {
            "name_i18n": self.name_i18n,
            "descriptions_i18n": self.descriptions_i18n,
            "description_template_i18n": self.description_template_i18n,
            "id": self.id,
            "type_i18n": self.type_i18n,
            "details_i18n": self.details_i18n,
            "atmosphere_i18n": self.atmosphere_i18n,
            "features_i18n": self.features_i18n,
        }

    @property
    def name(self) -> str:
        lang_to_use = self.selected_language if self.selected_language else "en"
        return get_i18n_text(self.to_dict_for_i18n(), "name", lang_to_use, "en")

    @property
    def display_description(self) -> str:
        lang_to_use = self.selected_language if self.selected_language else "en"
        data_for_i18n = self.to_dict_for_i18n()
        instance_desc = get_i18n_text(data_for_i18n, "descriptions", lang_to_use, "en")
        if instance_desc and not instance_desc.startswith("descriptions not found"):
            return instance_desc
        template_desc = get_i18n_text(data_for_i18n, "description_template", lang_to_use, "en")
        if template_desc and not template_desc.startswith("description_template not found"):
            return template_desc
        return "A location shrouded in mystery."

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            "name_i18n": self.name_i18n,
            "description_template_i18n": self.description_template_i18n,
            "descriptions_i18n": self.descriptions_i18n,
            "static_id": self.static_id,
            "type_i18n": self.type_i18n,
            "coordinates": self.coordinates,
            "exits": self.exits,
            "neighbor_locations_json": self.neighbor_locations_json,
            "generated_details_json": self.generated_details_json,
            "ai_metadata_json": self.ai_metadata_json,
            "details_i18n": self.details_i18n,
            "tags_i18n": self.tags_i18n,
            "atmosphere_i18n": self.atmosphere_i18n,
            "features_i18n": self.features_i18n,
            "channel_id": self.channel_id,
            "image_url": self.image_url,
            "points_of_interest_json": self.points_of_interest_json,
            "on_enter_events_json": self.on_enter_events_json,
            "moderation_request_id": self.moderation_request_id,
            "created_by_user_id": self.created_by_user_id,
            "state_variables": self.state_variables, # Changed from state
            "selected_language": self.selected_language,
            "guild_id": self.guild_id,
            "template_id": self.template_id,
            "is_active": self.is_active,
            "name": self.name, # Property
            "display_description": self.display_description, # Property
            # Backward compatibility fields if they are still needed by some logic
            "static_name": self.static_name,
            "static_connections": self.static_connections,
        })
        # Remove None values to keep the dict clean, if desired
        # data = {k: v for k, v in data.items() if v is not None}
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        data_copy = data.copy()
        selected_lang_val = data_copy.get('selected_language', "en")
        data_copy['selected_language'] = selected_lang_val

        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {selected_lang_val: data_copy.pop("name")}
        if "description_template" in data_copy and "description_template_i18n" not in data_copy:
            data_copy["description_template_i18n"] = {selected_lang_val: data_copy.pop("description_template")}
        
        if 'state' in data_copy and 'state_variables' not in data_copy: # Merge state into state_variables
            data_copy['state_variables'] = data_copy.pop('state')
        elif 'state' in data_copy and 'state_variables' in data_copy: # Both exist, merge state into state_variables
            if isinstance(data_copy['state_variables'], dict) and isinstance(data_copy['state'], dict):
                # state_variables takes precedence for overlapping keys
                merged_state = data_copy['state'].copy()
                merged_state.update(data_copy['state_variables'])
                data_copy['state_variables'] = merged_state
            del data_copy['state']


        # Ensure JSON-like fields are dictionaries/lists if they come as strings
        json_fields_expected_dict = [
            "name_i18n", "description_template_i18n", "descriptions_i18n", "type_i18n",
            "coordinates", "neighbor_locations_json", "generated_details_json",
            "ai_metadata_json", "details_i18n", "tags_i18n", "atmosphere_i18n",
            "features_i18n", "state_variables"
        ]
        json_fields_expected_list = [
            "points_of_interest_json", "on_enter_events_json", "exits"
        ]

        for field_name in json_fields_expected_dict:
            if field_name in data_copy and isinstance(data_copy[field_name], str):
                try: data_copy[field_name] = json.loads(data_copy[field_name])
                except json.JSONDecodeError:
                    logger.warning(f"Location.from_dict: Field '{field_name}' ('{data_copy[field_name]}') is a string but not valid JSON dict. Initializing as empty dict.")
                    data_copy[field_name] = {}

        for field_name in json_fields_expected_list:
            if field_name in data_copy and isinstance(data_copy[field_name], str):
                try: data_copy[field_name] = json.loads(data_copy[field_name])
                except json.JSONDecodeError:
                    logger.warning(f"Location.from_dict: Field '{field_name}' ('{data_copy[field_name]}') is a string but not valid JSON list. Initializing as empty list.")
                    data_copy[field_name] = []

        # Specific handling for exits if it's a dict (old format) vs list of dicts (new)
        if 'exits' in data_copy and isinstance(data_copy['exits'], dict) and \
           all(isinstance(k, str) and isinstance(v, str) for k,v in data_copy['exits'].items()):
            logger.debug("Location.from_dict: Converting old dict-style exits to new list-of-dicts format.")
            data_copy['exits'] = [{"direction": k, "target_location_id": v, "description_i18n": {selected_lang_val: f"Path to {v}"}} for k,v in data_copy['exits'].items()]

        return cls(**data_copy)
