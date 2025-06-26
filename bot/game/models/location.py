# bot/game/models/location.py
import uuid 
import json
import logging
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
                 static_id: Optional[str] = None,
                 type_i18n: Optional[Dict[str, str]] = None,
                 coordinates: Optional[Dict[str, Any]] = None,
                 exits: Optional[List[Dict[str, Any]]] = None,
                 neighbor_locations_json: Optional[Dict[str, Any]] = None, # Can store complex exit data
                 generated_details_json: Optional[Dict[str, Any]] = None,
                 ai_metadata_json: Optional[Dict[str, Any]] = None,
                 details_i18n: Optional[Dict[str, str]] = None,
                 tags_i18n: Optional[Dict[str, str]] = None,
                 atmosphere_i18n: Optional[Dict[str, str]] = None,
                 features_i18n: Optional[Dict[str, str]] = None,
                 channel_id: Optional[str] = None,
                 image_url: Optional[str] = None,
                 points_of_interest_json: Optional[List[Dict[str, Any]]] = None,
                 on_enter_events_json: Optional[List[Dict[str, Any]]] = None,
                 on_exit_triggers: Optional[List[Dict[str, Any]]] = None, # Added from DUMMY_LOCATION_TEMPLATE_DATA
                 on_enter_triggers: Optional[List[Dict[str, Any]]] = None, # Added from DUMMY_LOCATION_TEMPLATE_DATA
                 initial_state: Optional[Dict[str, Any]] = None, # Added from DUMMY_LOCATION_TEMPLATE_DATA
                 moderation_request_id: Optional[str] = None,
                 created_by_user_id: Optional[str] = None,
                 state_variables: Optional[Dict[str, Any]] = None,
                 selected_language: Optional[str] = "en",
                 name: Optional[str] = None, 
                 description_template: Optional[str] = None,
                 static_name: Optional[str] = None,
                 static_connections: Optional[str] = None,
                 guild_id: Optional[str] = None,
                 template_id: Optional[str] = None,
                 is_active: bool = True,
                 state: Optional[Dict[str, Any]] = None,
                 **kwargs): # Catch any other unexpected kwargs

        super().__init__(id=id)

        self.selected_language = selected_language if selected_language else "en"

        if name_i18n is not None: self.name_i18n = name_i18n
        elif name is not None: self.name_i18n = {self.selected_language: name}
        else: self.name_i18n = {self.selected_language: f"Unknown Location {self.id}"}

        if description_template_i18n is not None: self.description_template_i18n = description_template_i18n
        elif description_template is not None: self.description_template_i18n = {self.selected_language: description_template}
        else: self.description_template_i18n = {self.selected_language: "This is a mysterious place."}

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
        self.exits: List[Dict[str, Any]] = exits if exits is not None else []
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
        self.on_exit_triggers: Optional[List[Dict[str, Any]]] = on_exit_triggers
        self.on_enter_triggers: Optional[List[Dict[str, Any]]] = on_enter_triggers
        self.initial_state: Optional[Dict[str, Any]] = initial_state

        self.moderation_request_id: Optional[str] = moderation_request_id
        self.created_by_user_id: Optional[str] = created_by_user_id

        merged_state = {}
        if isinstance(state, dict): merged_state.update(state) # old field
        if isinstance(state_variables, dict): merged_state.update(state_variables) # new field
        if isinstance(initial_state, dict): # from template, lowest precedence
            temp_initial_state = initial_state.copy()
            temp_initial_state.update(merged_state) # existing state takes precedence
            merged_state = temp_initial_state
        self.state_variables: Dict[str, Any] = merged_state

        self.static_name: Optional[str] = static_name
        self.static_connections: Optional[str] = static_connections
        self.guild_id: Optional[str] = guild_id
        self.template_id: Optional[str] = template_id
        self.is_active: bool = is_active
        
        # Handle any remaining kwargs that were not explicitly defined as parameters
        # This is useful if the data source (e.g., DB, JSON) has more fields than defined in __init__
        # and we want to load them onto the model instance.
        for key, value in kwargs.items():
            if not hasattr(self, key): # Only set if not already set by explicit params
                setattr(self, key, value)


    def to_dict_for_i18n(self) -> Dict[str, Any]:
        return {
            "name_i18n": self.name_i18n,
            "descriptions_i18n": self.descriptions_i18n,
            "description_template_i18n": self.description_template_i18n,
            "id": self.id,
            "type_i18n": getattr(self, 'type_i18n', {}),
            "details_i18n": getattr(self, 'details_i18n', None),
            "atmosphere_i18n": getattr(self, 'atmosphere_i18n', None),
            "features_i18n": getattr(self, 'features_i18n', None),
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
        # Explicitly add all defined fields to ensure they are included
        fields_to_include = [
            "name_i18n", "description_template_i18n", "descriptions_i18n", "static_id",
            "type_i18n", "coordinates", "exits", "neighbor_locations_json",
            "generated_details_json", "ai_metadata_json", "details_i18n", "tags_i18n",
            "atmosphere_i18n", "features_i18n", "channel_id", "image_url",
            "points_of_interest_json", "on_enter_events_json", "on_exit_triggers", "on_enter_triggers",
            "initial_state", # Retained for serialization if needed from template
            "moderation_request_id", "created_by_user_id", "state_variables",
            "selected_language", "guild_id", "template_id", "is_active",
            "static_name", "static_connections"
        ]
        for field in fields_to_include:
            if hasattr(self, field): # Check if attribute exists before getting
                data[field] = getattr(self, field)

        data["name"] = self.name # Property
        data["display_description"] = self.display_description # Property
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
        
        # Merge 'state' into 'state_variables', 'state_variables' takes precedence
        current_state_variables = data_copy.get('state_variables', {})
        if not isinstance(current_state_variables, dict): current_state_variables = {}

        old_state = data_copy.pop('state', None)
        if isinstance(old_state, dict):
            merged_state = old_state.copy()
            merged_state.update(current_state_variables) # current_state_variables overrides old_state
            data_copy['state_variables'] = merged_state
        elif isinstance(current_state_variables, dict):
             data_copy['state_variables'] = current_state_variables
        else: # Neither are dicts or state_variables was not present
            data_copy['state_variables'] = {}


        json_fields_expected_dict = [
            "name_i18n", "description_template_i18n", "descriptions_i18n", "type_i18n",
            "coordinates", "neighbor_locations_json", "generated_details_json",
            "ai_metadata_json", "details_i18n", "tags_i18n", "atmosphere_i18n",
            "features_i18n", "state_variables", "initial_state"
        ]
        json_fields_expected_list = [
            "points_of_interest_json", "on_enter_events_json", "exits",
            "on_exit_triggers", "on_enter_triggers"
        ]

        for field_name in json_fields_expected_dict:
            if field_name in data_copy and isinstance(data_copy[field_name], str):
                try:
                    loaded_val = json.loads(data_copy[field_name])
                    if isinstance(loaded_val, dict): data_copy[field_name] = loaded_val
                    else: logger.warning(f"Location.from_dict: Field '{field_name}' ('{data_copy[field_name]}') decoded to {type(loaded_val)}, expected dict. Keeping as string or default.")
                except json.JSONDecodeError:
                    logger.warning(f"Location.from_dict: Field '{field_name}' ('{data_copy[field_name]}') is a string but not valid JSON dict. Initializing as empty dict if appropriate or keeping string.")
                    if field_name.endswith("_i18n"): # Basic fallback for i18n text fields if not JSON
                        data_copy[field_name] = {selected_lang_val: data_copy[field_name]}
                    elif field_name not in ["coordinates", "neighbor_locations_json", "generated_details_json", "ai_metadata_json", "state_variables", "initial_state"]: # Avoid turning these into lang dicts
                        data_copy[field_name] = {} # Default to empty dict for other complex dict types

        for field_name in json_fields_expected_list:
            if field_name in data_copy and isinstance(data_copy[field_name], str):
                try:
                    loaded_val = json.loads(data_copy[field_name])
                    if isinstance(loaded_val, list): data_copy[field_name] = loaded_val
                    else: logger.warning(f"Location.from_dict: Field '{field_name}' ('{data_copy[field_name]}') decoded to {type(loaded_val)}, expected list. Keeping as string or default.")
                except json.JSONDecodeError:
                    logger.warning(f"Location.from_dict: Field '{field_name}' ('{data_copy[field_name]}') is a string but not valid JSON list. Initializing as empty list.")
                    data_copy[field_name] = []

        if 'exits' in data_copy and isinstance(data_copy['exits'], dict) and \
           all(isinstance(k, str) and isinstance(v, str) for k,v in data_copy['exits'].items()):
            logger.debug("Location.from_dict: Converting old dict-style exits to new list-of-dicts format.")
            data_copy['exits'] = [{"direction": k, "target_location_id": v, "description_i18n": {selected_lang_val: f"Path to {v}"}} for k,v in data_copy['exits'].items()]

        return cls(**data_copy)
