from pydantic import BaseModel, field_validator, FieldValidationInfo
from typing import List, Dict, Optional, Any, Union
import json
import logging

logger = logging.getLogger(__name__)

# --- Standardized ValidationIssue Model ---
class ValidationIssue(BaseModel):
    loc: List[Union[str, int]] # Location of the error, e.g., ["stats", "strength"] or ["steps", 0, "title_i18n"]
    type: str                 # Type of error, e.g., "value_error.missing", "semantic.invalid_id_reference"
    msg: str                  # Human-readable message
    input_value: Optional[Any] = None # The problematic input value
    severity: str = "error"   # "error", "warning", "info"
    suggestion: Optional[str] = None # Optional suggestion for fixing

# --- Reusable Helper Validators ---

# Re-adding 'cls' as it's part of Pydantic's field_validator signature, even if not always used by the validator logic.
# Pyright expects it for methods decorated with @field_validator.
def validate_i18n_field(cls, v: Any, info: FieldValidationInfo) -> Dict[str, str]:
    if not isinstance(v, dict):
        raise ValueError(f"Field '{info.field_name}' must be a dictionary.")
    if not v:
        raise ValueError(f"Field '{info.field_name}' must not be empty.")

    target_languages = info.context.get("target_languages") if info.context else None
    if not target_languages:
        logger.warning(f"Validator for '{info.field_name}': 'target_languages' not found in context. Defaulting to 'en'.")
        target_languages = ['en']

    validated_dict: Dict[str, str] = {}
    for lang_code, text in v.items():
        if not isinstance(lang_code, str):
            raise ValueError(f"Language code '{lang_code}' in '{info.field_name}' must be a string.")
        if not isinstance(text, str):
            raise ValueError(f"Text for language '{lang_code}' in '{info.field_name}' must be a string. Found type: {type(text)}")
        stripped_text = text.strip()
        if not stripped_text:
            raise ValueError(f"Text for language '{lang_code}' in '{info.field_name}' must not be empty or just whitespace.")
        validated_dict[lang_code] = stripped_text

    missing_languages = [lang for lang in target_languages if lang not in validated_dict]
    if missing_languages:
        if 'en' in missing_languages and validated_dict:
            first_available_lang = next(iter(validated_dict))
            validated_dict['en'] = validated_dict[first_available_lang]
            logger.info(f"Field '{info.field_name}': Missing 'en' translation, copied from '{first_available_lang}'.")
            if 'en' in missing_languages: missing_languages.remove('en')


        if missing_languages:
            primary_guild_lang = target_languages[0]
            if primary_guild_lang in missing_languages and 'en' in validated_dict:
                validated_dict[primary_guild_lang] = validated_dict['en']
                logger.info(f"Field '{info.field_name}': Missing primary language '{primary_guild_lang}', copied from 'en'.")
                if primary_guild_lang in missing_languages: missing_languages.remove(primary_guild_lang)


        if missing_languages: # Check again after potential autofill
            raise ValueError(f"Field '{info.field_name}' is missing required language(s): {', '.join(missing_languages)}. Provided: {list(validated_dict.keys())}")
    return validated_dict

def ensure_valid_json_string(cls, v: Any, info: FieldValidationInfo) -> Optional[str]:
    field_is_optional = True # Default assumption, difficult to determine robustly without model schema access here
    # A more robust way would be to pass `field_info.is_required` from the model's field if this validator
    # is used in a context where `field_info` (from Pydantic's model_fields) is accessible.
    # For a generic validator, this is tricky. Let's assume optional for now if v is None or empty string.

    if v is None:
        return None

    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v)
        except (TypeError, OverflowError) as e:
            raise ValueError(f"Field '{info.field_name}': Invalid object for JSON stringification: {e}")

    if not isinstance(v, str):
        raise ValueError(f"Field '{info.field_name}' must be a string or a valid JSON serializable object/list. Got type: {type(v)}")

    if not v.strip(): # If string is empty or whitespace
        # For optional JSON fields, an empty string might mean "no data" -> None
        # For required JSON fields, an empty string is invalid.
        # This logic depends on how the specific field is defined in the model (Optional vs Required).
        # If field_is_optional (hard to determine here accurately without model schema), return None.
        # Otherwise, if it's a required JSON field, an empty string is an error.
        # For now, let's return None for empty strings, assuming they represent optional empty JSON.
        return None


    try:
        json.loads(v) # Check if it's valid JSON
    except json.JSONDecodeError as e:
        raise ValueError(f"Field '{info.field_name}' contains an invalid JSON string: {e}")
    return v

# --- Pydantic Models for AI Generated Content ---

class GeneratedQuestStep(BaseModel):
    title_i18n: Dict[str, str]
    description_i18n: Dict[str, str]
    required_mechanics_json: str
    abstract_goal_json: str
    step_order: int
    consequences_json: str
    assignee_type: Optional[str] = None
    assignee_id: Optional[str] = None

    _validate_i18n_fields = field_validator('title_i18n', 'description_i18n', mode='before')(validate_i18n_field)
    _validate_json_strings = field_validator('required_mechanics_json', 'abstract_goal_json', 'consequences_json', mode='before')(ensure_valid_json_string)

class GeneratedQuestData(BaseModel):
    name_i18n: Dict[str, str]
    description_i18n: Dict[str, str]
    steps: List[GeneratedQuestStep]
    consequences_json: str
    prerequisites_json: str # Optional if an empty JSON string means "no prerequisites"
    guild_id: Optional[str] = None
    influence_level: Optional[str] = None
    npc_involvement: Optional[Dict[str, str]] = None
    quest_giver_details_i18n: Optional[Dict[str, str]] = None
    consequences_summary_i18n: Optional[Dict[str, str]] = None
    suggested_level: Optional[int] = None

    _validate_i18n_fields = field_validator('name_i18n', 'description_i18n', mode='before')(validate_i18n_field)
    @field_validator('quest_giver_details_i18n', 'consequences_summary_i18n', mode='before')
    def validate_optional_i18n(cls, v, info: FieldValidationInfo): # Separate validator for optional i18n
        if v is None: return None
        return validate_i18n_field(cls, v, info)
    _validate_json_strings = field_validator('consequences_json', 'prerequisites_json', mode='before')(ensure_valid_json_string)

    @field_validator('steps')
    def check_min_steps(cls, v):
        if not v:
            raise ValueError('Quest must have at least one step.')
        return v

    @field_validator('suggested_level')
    def check_suggested_level(cls, v):
        if v is not None and v <= 0:
            raise ValueError('Suggested level must be positive.')
        return v

class GeneratedNpcInventoryItem(BaseModel):
    item_template_id: str
    quantity: int

    @field_validator('quantity')
    def check_quantity_positive(cls, v):
        if v <= 0:
            raise ValueError('Quantity must be positive.')
        return v

class GeneratedNpcFactionAffiliation(BaseModel):
    faction_id: str
    rank_i18n: Dict[str, str]
    _validate_i18n_rank = field_validator('rank_i18n', mode='before')(validate_i18n_field)

class GeneratedNpcRelationship(BaseModel):
    target_entity_id: str
    relationship_type: str
    strength: Optional[int] = None

class GeneratedNpcProfile(BaseModel):
    template_id: str
    name_i18n: Dict[str, str]
    role_i18n: Dict[str, str]
    archetype: str
    backstory_i18n: Dict[str, str]
    personality_i18n: Dict[str, str]
    motivation_i18n: Dict[str, str]
    visual_description_i18n: Dict[str, str]
    dialogue_hints_i18n: Dict[str, str]
    stats: Dict[str, Union[int, float]]
    skills: Dict[str, Union[int, float]]
    abilities: Optional[List[str]] = None
    spells: Optional[List[str]] = None
    inventory: Optional[List[GeneratedNpcInventoryItem]] = None
    faction_affiliations: Optional[List[GeneratedNpcFactionAffiliation]] = None
    relationships: Optional[List[GeneratedNpcRelationship]] = None
    is_trader: Optional[bool] = None
    currency_gold: Optional[int] = None

    _validate_i18n_fields = field_validator(
        'name_i18n', 'role_i18n', 'backstory_i18n',
        'personality_i18n', 'motivation_i18n',
        'visual_description_i18n', 'dialogue_hints_i18n',
        mode='before'
    )(validate_i18n_field)

    @field_validator('currency_gold')
    def check_currency_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError('Currency (gold) cannot be negative.')
        return v

class POIModel(BaseModel):
    poi_id: str
    name_i18n: Dict[str, str]
    description_i18n: Dict[str, str]
    contained_item_ids: Optional[List[str]] = None # Deprecated: Will be phased out. New content should use contained_item_instance_ids.
    contained_item_instance_ids: Optional[List[str]] = None
    npc_ids: Optional[List[str]] = None
    _validate_i18n_fields = field_validator('name_i18n', 'description_i18n', mode='before')(validate_i18n_field)

class ConnectionModel(BaseModel):
    to_location_id: str
    path_description_i18n: Dict[str, str]
    travel_time_hours: Optional[int] = None
    _validate_i18n_fields = field_validator('path_description_i18n', mode='before')(validate_i18n_field)

    @field_validator('travel_time_hours')
    def check_travel_time_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError('Travel time cannot be negative.')
        return v

class GeneratedLocationContent(BaseModel):
    template_id: str
    name_i18n: Dict[str, str]
    atmospheric_description_i18n: Dict[str, str]
    points_of_interest: Optional[List[POIModel]] = None
    connections: Optional[List[ConnectionModel]] = None
    possible_events_i18n: Optional[List[Dict[str, str]]] = None
    required_access_items_ids: Optional[List[str]] = None
    static_id: Optional[str] = None
    location_type_key: str
    coordinates_json: Optional[Dict[str, Any]] = None
    initial_npcs_json: Optional[List[GeneratedNpcProfile]] = None
    initial_items_json: Optional[List[Dict[str, Any]]] = None
    generated_details_json: Optional[Dict[str, Any]] = None
    ai_metadata_json: Optional[Dict[str, Any]] = None

    _validate_i18n_fields = field_validator('name_i18n', 'atmospheric_description_i18n', mode='before')(validate_i18n_field)

    @field_validator('possible_events_i18n', mode='before')
    def validate_possible_events(cls, v, info: FieldValidationInfo):
        if v is None: return None
        if not isinstance(v, list): raise ValueError("possible_events_i18n must be a list of dictionaries.")
        validated_list = []
        for index, event_i18n_dict in enumerate(v):
            try:
                # Pass the main `info` object. validate_i18n_field uses info.context.
                # The field_name on `info` will be for 'possible_events_i18n' itself,
                # if validate_i18n_field needs the sub-field name, it would need more specific handling.
                # Assuming validate_i18n_field can work with the main field's info for context.
                validated_list.append(validate_i18n_field(cls, event_i18n_dict, info))
            except ValueError as e:
                raise ValueError(f"Validation failed for item {index} in possible_events_i18n: {e}")
        return validated_list

class GeneratedItemProfile(BaseModel):
    template_id: str
    name_i18n: Dict[str, str]
    description_i18n: Dict[str, str]
    item_type: str
    base_value: int
    properties_json: str
    rarity_level: Optional[str] = None
    icon: Optional[str] = None
    equipable_slot: Optional[str] = None
    requirements: Optional[Dict[str, Any]] = None

    _validate_i18n_fields = field_validator('name_i18n', 'description_i18n', mode='before')(validate_i18n_field)
    _validate_json_strings = field_validator('properties_json', mode='before')(ensure_valid_json_string)

    @field_validator('base_value')
    def check_base_value_non_negative(cls, v):
        if v < 0:
            raise ValueError('Base value cannot be negative.')
        return v

# --- Generation Context Model ---
class GenerationContext(BaseModel):
    guild_id: str
    main_language: str
    target_languages: List[str]
    request_type: str
    request_params: Dict[str, Any]
    game_rules_summary: Dict[str, Any]
    lore_snippets: List[Dict[str, Any]]
    world_state: Dict[str, Any]
    game_terms_dictionary: List[Dict[str, Any]]
    scaling_parameters: List[Dict[str, Any]]
    player_context: Optional[Dict[str, Any]] = None
    faction_data: List[Dict[str, Any]]
    relationship_data: List[Dict[str, Any]]
    active_quests_summary: List[Dict[str, Any]]
    primary_location_details: Optional[Dict[str, Any]] = None
    party_context: Optional[Dict[str, Any]] = None

# --- Wrapper Models for AI Response Validation ---
# These are not directly produced by AI but used to structure the validation process and results.
class ValidatedAiResponse(BaseModel):
    model_type: str
    data: Union[
        GeneratedQuestData,
        GeneratedNpcProfile,
        GeneratedLocationContent,
        GeneratedItemProfile,
        None
    ] = None
    validation_issues: List[ValidationIssue] = [] # Uses the new ValidationIssue model
    raw_ai_output: Optional[str] = None
    parsed_json_data: Optional[Dict[str, Any]] = None

    @property
    def is_valid(self) -> bool:
        return self.data is not None and not self.validation_issues

# Placeholder for ParsedAiData if it was intended for structured parsing before Pydantic model
class ParsedAiData(BaseModel):
    raw_json: Dict[str, Any]
    entity_type: Optional[str] = None # e.g., "npc", "quest_list"
    # Potentially other fields if it was doing more structured parsing

# Placeholder for ValidatedEntity if it was used by an older validator structure
class ValidatedEntity(BaseModel):
    entity_type: str
    data: Optional[Any] = None # Could be specific Pydantic model like GeneratedNpcProfile
    issues: List[ValidationIssue] = []
    validation_status: str = "unknown" # E.g., "success", "error", "requires_moderation"
    original_data: Optional[Dict[str, Any]] = None

    @property
    def is_strictly_valid(self) -> bool:
        return self.validation_status == "success" and not self.issues

from enum import Enum # Added for GenerationType

# --- Added Models for GameTerm and ScalingParameter ---
class GameTerm(BaseModel):
    id: str
    name_i18n: Dict[str, str]
    term_type: str
    description_i18n: Optional[Dict[str, str]] = None
    # Example: validate name_i18n using the shared validator
    _validate_name_i18n = field_validator('name_i18n', mode='before')(validate_i18n_field)
    @field_validator('description_i18n', mode='before')
    def validate_optional_desc_i18n(cls, v, info: FieldValidationInfo):
        if v is None: return None
        return validate_i18n_field(cls, v, info)

class ScalingParameter(BaseModel):
    parameter_name: str
    value: Union[float, int, str, bool, List[Any], Dict[str, Any]] # Allow list/dict for complex params
    description_i18n: Optional[Dict[str, str]] = None
    # Example: validate description_i18n if it's present
    @field_validator('description_i18n', mode='before')
    def validate_optional_desc_i18n(cls, v, info: FieldValidationInfo):
        if v is None: return None
        return validate_i18n_field(cls, v, info)
