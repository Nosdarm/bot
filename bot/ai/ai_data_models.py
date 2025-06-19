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
            missing_languages.remove('en')

        if missing_languages:
            primary_guild_lang = target_languages[0]
            if primary_guild_lang in missing_languages and 'en' in validated_dict:
                validated_dict[primary_guild_lang] = validated_dict['en']
                logger.info(f"Field '{info.field_name}': Missing primary language '{primary_guild_lang}', copied from 'en'.")
                missing_languages.remove(primary_guild_lang)

        if missing_languages:
            raise ValueError(f"Field '{info.field_name}' is missing required language(s): {', '.join(missing_languages)}. Provided: {list(validated_dict.keys())}")
    return validated_dict

def ensure_valid_json_string(cls, v: Any, info: FieldValidationInfo) -> str:
    field_is_optional = not cls.model_fields[info.field_name].is_required()
    if v is None and field_is_optional:
        return v # Allow None for optional fields

    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v)
        except (TypeError, OverflowError) as e:
            raise ValueError(f"Field '{info.field_name}': Invalid object for JSON stringification: {e}")

    if not isinstance(v, str):
        raise ValueError(f"Field '{info.field_name}' must be a string or a valid JSON serializable object/list. Got type: {type(v)}")

    # Allow empty string for optional fields that were explicitly passed as ""
    if not v.strip() and field_is_optional:
        # Consider if empty string should be converted to None or kept as ""
        # For now, keeping as "" if it's explicitly passed. If it should be None, add: return None
        pass

    try:
        json.loads(v)
    except json.JSONDecodeError as e:
        # If it's an optional field and the string is empty, it might be acceptable
        if field_is_optional and not v.strip():
             pass # Allow empty string for optional JSON fields (implies empty/null structure)
        else:
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
                temp_info_dict = {"field_name":f"{info.field_name}[{index}]", "context": info.context, "config": info.config}
                temp_field_val_info = FieldValidationInfo.from_config(temp_info_dict['config'], field_name=temp_info_dict['field_name'], context=temp_info_dict['context']) # type: ignore
                validated_list.append(validate_i18n_field(cls, event_i18n_dict, temp_field_val_info))
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

# Note: GenerationContext was removed as it was minimal and not directly part of this subtask's focus on AI output models.
# If needed, it can be re-added or defined elsewhere.

