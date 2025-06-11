from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field

# --- Structures for prepare_ai_prompt ---

class GameTerm(BaseModel):
    id: str
    name_i18n: Dict[str, str]
    term_type: str # e.g., "stat", "skill", "npc", "item_template", "location"
    description_i18n: Optional[Dict[str, str]] = None

class ScalingParameter(BaseModel):
    parameter_name: str # e.g., "difficulty_scalar", "reward_multiplier"
    value: float
    context: Optional[str] = None # e.g., "player_level_5-10"

class GenerationContext(BaseModel):
    guild_id: str
    main_language: str = Field(default='ru', description="Main language for the bot, influences primary text generation if not overridden by target_languages.")
    target_languages: List[str] = Field(default_factory=lambda: ["en", "ru"], description="Languages required for i18n output.")

    request_type: str # e.g., "generate_npc", "generate_quest", "generate_item"
    request_params: Dict[str, Any] = Field(default_factory=dict, description="Specific parameters for the request, e.g., {'npc_idea': 'old wizard', 'player_level': 10}")

    world_state: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Relevant parts of the current world state (e.g., key events, location statuses).")
    faction_data: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Information about relevant factions.")
    relationship_data: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Information about relevant entity relationships.")
    active_quests_summary: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Summary of active quests relevant to the context.")

    game_lore_snippets: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Snippets of game lore relevant to the generation task.")

    game_terms_dictionary: List[GameTerm] = Field(default_factory=list, description="Dictionary of key game terms (stats, skills, entity IDs and names) for AI reference.")
    scaling_parameters: List[ScalingParameter] = Field(default_factory=list, description="Parameters for scaling generated content (e.g., difficulty, rewards) based on rules.")

    # Reference to the full game rules structure, if needed directly by the prompt generator
    # For now, assuming scaling_parameters and game_terms_dictionary are derived from this elsewhere.
    # game_rules_snapshot: Optional[Dict[str, Any]] = None
    game_rules_summary: Optional[Dict[str, Any]] = Field(default=None, description="General summary of game rules, if distinct from specific terms/scaling params.")
    player_context: Optional[Dict[str, Any]] = Field(default=None, description="Context specific to a player, if generation is player-centric (e.g. player level, inventory).")

# --- Structures for parse_and_validate_ai_response ---

class ValidationIssue(BaseModel):
    field: str # e.g., "stats.strength", "name_i18n.en", "stages[0].objectives[1].type"
    issue_type: str # e.g., "missing_translation", "value_out_of_range", "invalid_reference"
    message: str
    recommended_fix: Optional[str] = None
    severity: str = Field(default="error", description="'error' or 'warning'") # For auto-correction vs. moderation

class ValidatedEntity(BaseModel):
    entity_id: Optional[str] = None # ID of the entity if successfully parsed/validated
    entity_type: str # e.g., "npc", "quest", "item"
    data: Dict[str, Any] # The validated (and potentially auto-corrected) data for the entity
    original_data: Optional[Dict[str, Any]] = Field(None, description="Original data before auto-correction, for reference.")
    validation_status: str # e.g., "success", "success_with_autocorrections", "requires_moderation"
    issues: List[ValidationIssue] = Field(default_factory=list)

class ParsedAiData(BaseModel):
    overall_status: str # "success", "success_with_autocorrections", "requires_moderation", "error" (if global parsing failed)
    entities: List[ValidatedEntity] = Field(default_factory=list)
    global_errors: List[str] = Field(default_factory=list, description="Errors not specific to one entity, e.g., JSON parsing error of the whole response.")
    raw_ai_output: Optional[str] = None # Store the raw output for debugging

class ValidationError(BaseModel):
    # This could be similar to ParsedAiData if parse_and_validate_ai_response returns one or the other.
    # Or it could be a more specific error structure if it's raised as an exception.
    # For now, let's assume it's for when validation itself encounters a major problem or for critical failures.
    error_message: str
    details: Optional[Dict[str, Any]] = None
    parsed_data_attempt: Optional[ParsedAiData] = Field(None, description="If parsing/validation failed partially, this might contain what was processed.")

    # Alternative: parse_and_validate_ai_response always returns ParsedAiData,
    # and ValidationError is an exception class.
    # For the return type `ParsedAiData | ValidationError`, this model is fine.

# Example usage (not part of the file, just for illustration):
# def prepare_ai_prompt(generation_context: GenerationContext) -> str:
#     # ... use generation_context ...
#     return "prompt"

# def parse_and_validate_ai_response(raw_ai_output_text: str, context: GenerationContext) -> Union[ParsedAiData, ValidationError]:
#     # ... parse and validate ...
#     if good:
#         return ParsedAiData(...)
#     else:
#         return ValidationError(...)
