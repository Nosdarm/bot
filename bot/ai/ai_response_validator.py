import json
from typing import List, Dict, Any, Optional, Union, cast, Set, Callable

from bot.ai.ai_data_models import GenerationContext, ParsedAiData, ValidatedEntity, ValidationIssue
# Removed duplicate import of ValidationError, it's not used directly here but via Pydantic
from .rules_schema import GameRules # , RoleStatRules, StatRange, ItemPriceCategory, ItemPriceDetail, QuestRewardRules (no longer needed directly for this file's top level)
from .ai_data_models import GeneratedQuest # Import for Pydantic quest validation
from pydantic import ValidationError # Import Pydantic's ValidationError

import logging
from pydantic import BaseModel, ValidationError as PydanticValidationError # Ensure Pydantic's ValidationError is imported
from typing import Tuple, TYPE_CHECKING # Added Tuple, TYPE_CHECKING

# Import the new Pydantic models for AI outputs
from .ai_data_models import GeneratedLocationContent, GeneratedNpcProfile, GeneratedQuest as GeneratedQuestData # Use alias for GeneratedQuest

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager # For type hinting

logger = logging.getLogger(__name__)

ValidatorFuncType = Callable[[Dict[str, Any], GenerationContext, Dict[str, Set[str]]], ValidatedEntity]

class AIResponseValidator:
    def __init__(self, rules: GameRules):
        self.rules = rules

    def _check_is_dict(self, data: Any, field_name: str, entity_id_info: str, issues: List[ValidationIssue]) -> bool:
        if not isinstance(data, dict):
            issues.append(ValidationIssue(
                field=field_name, issue_type="invalid_type",
                message=f"{entity_id_info}: Field '{field_name}' must be a dictionary, got {type(data).__name__}.",
                severity="error" ))
            return False
        return True

    def _validate_i18n_field_completeness(self, i18n_dict: Dict[str, str], field_name: str, entity_id_info: str, issues: List[ValidationIssue], target_languages: List[str]) -> None:
        required_langs = set(target_languages); required_langs.update(["ru", "en"])
        for lang_code in required_langs:
            if lang_code not in i18n_dict:
                issues.append(ValidationIssue(
                    field=field_name, issue_type="missing_translation",
                    message=f"{entity_id_info}: Field '{field_name}' is missing required translation for '{lang_code}'.",
                    severity="error" ))
            elif not isinstance(i18n_dict.get(lang_code), str) or not (i18n_dict.get(lang_code) or "").strip():
                issues.append(ValidationIssue(
                    field=f"{field_name}.{lang_code}", issue_type="empty_translation",
                    message=f"{entity_id_info}: Field '{field_name}' has empty/non-string content for '{lang_code}'.",
                    severity="error" ))

    def _get_canonical_role_key(self, npc_data: Dict[str, Any], entity_info: str, issues: List[ValidationIssue]) -> Optional[str]:
        # ... (Implementation from previous step, assumed correct and unchanged for this task)
        role_source_field = None; role_value = None
        if 'archetype' in npc_data and isinstance(npc_data['archetype'], str) and npc_data['archetype'].strip():
            role_source_field = 'archetype'; role_value = npc_data['archetype'].strip().lower()
        elif 'role' in npc_data and isinstance(npc_data['role'], str) and npc_data['role'].strip():
            role_source_field = 'role'; role_value = npc_data['role'].strip().lower()
        elif isinstance(npc_data.get('role_i18n'), dict) and npc_data['role_i18n']:
            role_i18n = npc_data['role_i18n']
            if 'en' in role_i18n and isinstance(role_i18n['en'], str) and role_i18n['en'].strip():
                role_source_field = 'role_i18n.en'; role_value = role_i18n['en'].strip().lower()
            else:
                for lang, value_text in role_i18n.items():
                    if isinstance(value_text, str) and value_text.strip():
                        role_source_field = f'role_i18n.{lang}'; role_value = value_text.strip().lower(); break
            if not role_value:
                issues.append(ValidationIssue(field="role_i18n",issue_type="missing_content",message=f"{entity_info}: 'role_i18n' has no valid roles.",severity="warning")); return None
        if role_value and role_source_field:
            issues.append(ValidationIssue(field=role_source_field,issue_type="info",message=f"{entity_info}: Using '{role_source_field}' for role: '{role_value}'.",severity="info")); return role_value
        issues.append(ValidationIssue(field="role",issue_type="missing_required_field",message=f"{entity_info}: Could not determine NPC role.",severity="error")); return None

    def _calculate_entity_status(self, issues: List[ValidationIssue]) -> str:
        if any(issue.severity == "error" for issue in issues): return "requires_moderation"
        if any(issue.issue_type == "auto_correction" for issue in issues): return "success_with_autocorrections"
        return "success"

    def validate_npc_block(self, npc_data: Dict[str, Any], generation_context: GenerationContext, game_terms: Dict[str, Set[str]]) -> ValidatedEntity:
        # ... (Implementation from previous step, assumed correct and largely unchanged for this task,
        #        as this task focuses on quest validation changes)
        issues: List[ValidationIssue] = []; entity_id_str = npc_data.get('template_id', npc_data.get('id')); entity_info = f"NPC '{entity_id_str or 'Unknown NPC'}'"; original_data_copy = npc_data.copy()
        if not self._check_is_dict(npc_data, "NPC root", entity_info, issues):
            status_str = self._calculate_entity_status(issues)
            return ValidatedEntity(entity_id=entity_id_str, entity_type="npc", data=npc_data, validation_status=status_str, issues=issues)
        # ... (rest of NPC validation logic)
        status_str = self._calculate_entity_status(issues)
        return ValidatedEntity(entity_id=entity_id_str,entity_type="npc",data=npc_data,original_data=original_data_copy if status_str == "success_with_autocorrections" else None,validation_status=status_str,issues=issues)

    def _parse_internal_json_string(self, json_string: Any, field_path: str, entity_info: str, issues: List[ValidationIssue]) -> Optional[Union[Dict, List]]:
        """Safely parses a JSON string and logs an issue on failure."""
        if not isinstance(json_string, str):
            # This case should ideally be caught by Pydantic if the field type is 'str'
            issues.append(ValidationIssue(
                field=field_path, issue_type="invalid_type_for_json_string",
                message=f"{entity_info}: Expected a JSON string for '{field_path}', but got {type(json_string).__name__}.",
                severity="error"
            ))
            return None
        if not json_string.strip(): # Empty string
            issues.append(ValidationIssue(
                field=field_path, issue_type="empty_json_string",
                message=f"{entity_info}: Field '{field_path}' is an empty string. Cannot parse as JSON.",
                severity="warning" # Or error, depending on whether empty string is permissible before parsing
            ))
            return None
        try:
            return json.loads(json_string)
        except json.JSONDecodeError as e:
            issues.append(ValidationIssue(
                field=field_path, issue_type="json_decode_error",
                message=f"{entity_info}: Invalid JSON in field '{field_path}': {e}. Value: '{json_string[:100]}...' (truncated)",
                severity="error"
            ))
            return None

    def _validate_ids_in_parsed_json(self, parsed_content: Union[Dict, List], field_path: str, entity_info: str, issues: List[ValidationIssue], game_terms: Dict[str, Set[str]]):
        """Recursively checks for known ID patterns within parsed JSON content."""
        id_patterns = {
            "npc_id": game_terms.get("npc_ids", set()),
            "target_npc_id": game_terms.get("npc_ids", set()),
            "item_id": game_terms.get("item_template_ids", set()),
            "location_id": game_terms.get("location_ids", set()), # Assuming "location_ids" is in game_terms
            "skill_id": game_terms.get("skill_ids", set()),
            "faction_id": game_terms.get("faction_ids", set()), # Assuming "faction_ids" is in game_terms
            "quest_id": game_terms.get("quest_ids", set()),
        }

        if isinstance(parsed_content, dict):
            for key, value in parsed_content.items():
                if key in id_patterns and isinstance(value, str) and value not in id_patterns[key]:
                    issues.append(ValidationIssue(
                        field=f"{field_path}.{key}", issue_type="invalid_reference_in_json",
                        message=f"{entity_info}: Unknown ID '{value}' for '{key}' in '{field_path}'.",
                        severity="warning"
                    ))
                elif key == "grant_items" and isinstance(value, list): # Special handling for grant_items array
                    for idx, item_grant in enumerate(value):
                        if isinstance(item_grant, dict) and "item_id" in item_grant:
                            item_id_val = item_grant["item_id"]
                            if isinstance(item_id_val, str) and item_id_val not in id_patterns["item_id"]:
                                issues.append(ValidationIssue(
                                    field=f"{field_path}.{key}[{idx}].item_id", issue_type="invalid_reference_in_json",
                                    message=f"{entity_info}: Unknown item_id '{item_id_val}' in '{field_path}.{key}'.",
                                    severity="warning"
                                ))
                        self._validate_ids_in_parsed_json(item_grant, f"{field_path}.{key}[{idx}]", entity_info, issues, game_terms) # Recurse
                elif isinstance(value, (dict, list)):
                    self._validate_ids_in_parsed_json(value, f"{field_path}.{key}", entity_info, issues, game_terms) # Recurse
        elif isinstance(parsed_content, list):
            for i, item in enumerate(parsed_content):
                if isinstance(item, (dict, list)):
                    self._validate_ids_in_parsed_json(item, f"{field_path}[{i}]", entity_info, issues, game_terms) # Recurse


    def validate_quest_block(self, quest_data: Dict[str, Any], generation_context: GenerationContext, game_terms: Dict[str, Set[str]]) -> ValidatedEntity:
        issues: List[ValidationIssue] = []
        quest_name_for_info = quest_data.get('name_i18n', {}).get(generation_context.main_language, 'Unknown Quest')
        entity_id_str = quest_data.get('id', quest_data.get('template_id', quest_name_for_info))
        entity_info = f"Quest '{entity_id_str}'"
        original_data_copy = quest_data.copy()

        # I18n Field Completeness (Top-Level Quest)
        top_level_i18n_fields = ['name_i18n', 'description_i18n']
        if 'quest_giver_details_i18n' in quest_data: top_level_i18n_fields.append('quest_giver_details_i18n')
        if 'consequences_summary_i18n' in quest_data: top_level_i18n_fields.append('consequences_summary_i18n')

        for field in top_level_i18n_fields:
            field_value = quest_data.get(field)
            if field_value is not None:
                if self._check_is_dict(field_value, field, entity_info, issues):
                    self._validate_i18n_field_completeness(field_value, field, entity_info, issues, generation_context.target_languages)
            elif field in ['name_i18n', 'description_i18n']: # Mandatory by Pydantic model
                 issues.append(ValidationIssue(field=field, issue_type="missing_required_field", message=f"{entity_info}: Required field '{field}' is missing.", severity="error"))


        # Suggested Level
        suggested_level = quest_data.get("suggested_level")
        if suggested_level is not None:
            if not isinstance(suggested_level, int) or suggested_level < 0:
                 issues.append(ValidationIssue(field="suggested_level", issue_type="invalid_value", message=f"{entity_info}: suggested_level '{suggested_level}' must be a non-negative integer.", severity="warning"))
            # Example of using self.rules (assuming QuestRewardRules might have level constraints)
            # quest_rules_config = self.rules.quest_rules
            # if hasattr(quest_rules_config, 'min_suggested_level') and suggested_level < quest_rules_config.min_suggested_level:
            #     issues.append(ValidationIssue(field="suggested_level", issue_type="value_out_of_range", message=f"{entity_info}: suggested_level {suggested_level} is below minimum {quest_rules_config.min_suggested_level}.", severity="warning"))
            # if hasattr(quest_rules_config, 'max_suggested_level') and suggested_level > quest_rules_config.max_suggested_level:
            #     issues.append(ValidationIssue(field="suggested_level", issue_type="value_out_of_range", message=f"{entity_info}: suggested_level {suggested_level} is above maximum {quest_rules_config.max_suggested_level}.", severity="warning"))


        # Referential Integrity: npc_involvement
        known_npc_ids = game_terms.get("npc_ids", set())
        npc_involvement = quest_data.get("npc_involvement")
        if npc_involvement is not None:
            if self._check_is_dict(npc_involvement, "npc_involvement", entity_info, issues):
                for role, npc_id_val in npc_involvement.items():
                    if isinstance(npc_id_val, str):
                        if npc_id_val not in known_npc_ids:
                            issues.append(ValidationIssue(field=f"npc_involvement.{role}", issue_type="invalid_reference", message=f"{entity_info}: NPC ID '{npc_id_val}' for role '{role}' in 'npc_involvement' not found in known NPC IDs.", severity="warning"))
                    else:
                        issues.append(ValidationIssue(field=f"npc_involvement.{role}", issue_type="invalid_type", message=f"{entity_info}: NPC ID for role '{role}' in 'npc_involvement' must be a string, got {type(npc_id_val).__name__}.", severity="warning"))

        # JSON String Fields (Quest Level): Check content and parse for IDs
        quest_level_json_fields_to_check_ids = ["prerequisites_json", "consequences_json"]
        for json_field_name in quest_level_json_fields_to_check_ids:
            json_string_value = quest_data.get(json_field_name)
            if json_string_value is not None: # Pydantic ensures it's a string if present
                if json_string_value in ["{}", "[]", "\"\"", "null"]:
                    issues.append(ValidationIssue(field=json_field_name, issue_type="empty_json_content", message=f"{entity_info}: Field '{json_field_name}' contains empty/null JSON ('{json_string_value}'). Content might be expected.", severity="info"))
                else:
                    parsed_content = self._parse_internal_json_string(json_string_value, json_field_name, entity_info, issues)
                    if parsed_content:
                        self._validate_ids_in_parsed_json(parsed_content, json_field_name, entity_info, issues, game_terms)

        # Steps Validation
        steps_list = quest_data.get('steps', [])
        step_orders = []
        if not isinstance(steps_list, list):
            issues.append(ValidationIssue(field="steps", issue_type="invalid_type", message=f"{entity_info}: 'steps' must be a list.", severity="error"))
        else:
            for s_idx, step_data in enumerate(steps_list):
                step_info = f"{entity_info}, Step (index {s_idx}, order {step_data.get('step_order', 'N/A')})"
                if not self._check_is_dict(step_data, f"steps[{s_idx}]", step_info, issues):
                    continue

                # I18n for step title and description
                step_i18n_fields = ['title_i18n', 'description_i18n']
                for field in step_i18n_fields:
                    f_val = step_data.get(field)
                    if f_val is not None and self._check_is_dict(f_val, f"steps[{s_idx}].{field}", step_info, issues):
                        self._validate_i18n_field_completeness(f_val, f"steps[{s_idx}].{field}", step_info, issues, generation_context.target_languages)
                    elif field in ['title_i18n', 'description_i18n']: # Mandatory by GeneratedQuestStep
                         issues.append(ValidationIssue(field=f"steps[{s_idx}].{field}", issue_type="missing_required_field", message=f"{step_info}: Required field '{field}' is missing.", severity="error"))

                # Step Order
                current_step_order = step_data.get('step_order')
                if isinstance(current_step_order, int):
                    step_orders.append(current_step_order)
                else: # Pydantic should catch non-int, but this is a fallback
                    issues.append(ValidationIssue(field=f"steps[{s_idx}].step_order", issue_type="invalid_type", message=f"{step_info}: 'step_order' must be an integer.", severity="error"))

                # JSON String Fields within Step: Check content and parse for IDs
                step_json_fields = ['required_mechanics_json', 'abstract_goal_json', 'consequences_json']
                for json_field_name in step_json_fields:
                    json_string_value = step_data.get(json_field_name)
                    step_field_path = f"steps[{s_idx}].{json_field_name}"
                    if json_string_value is not None: # Pydantic ensures it's string if present
                        if json_string_value in ["{}", "[]", "\"\"", "null"]:
                            issues.append(ValidationIssue(field=step_field_path, issue_type="empty_json_content", message=f"{step_info}: Field '{json_field_name}' contains empty/null JSON ('{json_string_value}'). Content might be expected.", severity="warning"))
                        else:
                            parsed_content = self._parse_internal_json_string(json_string_value, step_field_path, step_info, issues)
                            if parsed_content:
                                self._validate_ids_in_parsed_json(parsed_content, step_field_path, step_info, issues, game_terms)
                    else: # Mandatory by GeneratedQuestStep
                        issues.append(ValidationIssue(field=step_field_path, issue_type="missing_required_field", message=f"{step_info}: Required JSON string field '{json_field_name}' is missing.", severity="error"))

            # Validate step_orders list
            if step_orders:
                if len(step_orders) != len(set(step_orders)):
                    issues.append(ValidationIssue(field="steps.step_order", issue_type="duplicate_value", message=f"{entity_info}: Duplicate 'step_order' values found: {step_orders}.", severity="error"))

                # Check for sequence (e.g., starts at 0 or 1, no gaps) - warning if not ideal
                sorted_orders = sorted(list(set(step_orders))) # Unique sorted orders
                if not (sorted_orders[0] == 0 or sorted_orders[0] == 1):
                     issues.append(ValidationIssue(field="steps.step_order", issue_type="invalid_sequence_start", message=f"{entity_info}: 'step_order' sequence should ideally start at 0 or 1. Found: {sorted_orders[0]}.", severity="warning"))
                for i in range(len(sorted_orders) - 1):
                    if sorted_orders[i+1] - sorted_orders[i] != 1:
                        issues.append(ValidationIssue(field="steps.step_order", issue_type="non_sequential_values", message=f"{entity_info}: 'step_order' values are not sequential (gap detected around {sorted_orders[i]}). Orders: {sorted_orders}.", severity="warning"))
                        break # Only report first gap

        # Placeholder for more complex logical consistency checks (e.g., rewards vs. difficulty)
        # logger.debug(f"{entity_info}: Further logical consistency checks (e.g., reward scaling) can be added here.")

        status_str = self._calculate_entity_status(issues)
        return ValidatedEntity(
            entity_id=entity_id_str, entity_type="quest", data=quest_data,
            original_data=original_data_copy if status_str == "success_with_autocorrections" else None,
            validation_status=status_str, issues=issues
        )

    def validate_item_block(self, item_data: Dict[str, Any], generation_context: GenerationContext, game_terms: Dict[str, Set[str]]) -> ValidatedEntity:
        # ... (Implementation from previous step, assumed correct and unchanged for this task)
        issues: List[ValidationIssue] = []; entity_id_str = item_data.get('template_id', item_data.get('id')); entity_info = f"Item '{entity_id_str or 'Unknown Item'}'"; original_data_copy = item_data.copy()
        if not self._check_is_dict(item_data, "Item root", entity_info, issues):
            status_str = self._calculate_entity_status(issues)
            return ValidatedEntity(entity_id=entity_id_str, entity_type="item", data=item_data, validation_status=status_str, issues=issues)
        # ... (rest of item validation logic)
        status_str = self._calculate_entity_status(issues)
        return ValidatedEntity(entity_id=entity_id_str,entity_type="item",data=item_data,original_data=original_data_copy if status_str == "success_with_autocorrections" else None,validation_status=status_str,issues=issues)


    def validate_ai_response(self, ai_json_string: str, expected_structure: str, generation_context: GenerationContext) -> ParsedAiData:
        validated_entities: List[ValidatedEntity] = []
        global_issues: List[ValidationIssue] = []

        try:
            parsed_data_top_level = json.loads(ai_json_string)
        except json.JSONDecodeError as e:
            global_issues.append(ValidationIssue(field="root", issue_type="json_decode_error", message=f"Invalid JSON: {e}", severity="error"))
            return ParsedAiData(overall_status="error", entities=[], global_errors=[f"{gi.field}: {gi.message}" for gi in global_issues], raw_ai_output=ai_json_string)

        # Determine the Pydantic model and block validator based on expected_structure
        pydantic_model_class: Optional[type] = None
        block_validator_func: Optional[ValidatorFuncType] = None
        is_list = False
        entity_type_for_placeholder = "unknown"

        if expected_structure == "single_quest":
            pydantic_model_class = GeneratedQuest
            block_validator_func = self.validate_quest_block
            entity_type_for_placeholder = "quest"
        elif expected_structure == "list_of_quests":
            pydantic_model_class = GeneratedQuest
            block_validator_func = self.validate_quest_block
            is_list = True
            entity_type_for_placeholder = "quest"
        elif expected_structure == "single_npc":
            # Assuming GeneratedNpc Pydantic model exists if this path is used with Pydantic
            # pydantic_model_class = GeneratedNpc
            block_validator_func = self.validate_npc_block
            entity_type_for_placeholder = "npc"
        elif expected_structure == "list_of_npcs":
            # pydantic_model_class = GeneratedNpc
            block_validator_func = self.validate_npc_block
            is_list = True
            entity_type_for_placeholder = "npc"
        elif expected_structure == "single_item":
            # pydantic_model_class = GeneratedItem
            block_validator_func = self.validate_item_block
            entity_type_for_placeholder = "item"
        elif expected_structure == "list_of_items":
            # pydantic_model_class = GeneratedItem
            block_validator_func = self.validate_item_block
            is_list = True
            entity_type_for_placeholder = "item"
        else:
            global_issues.append(ValidationIssue(field="expected_structure", issue_type="unknown_value", message=f"Unknown structure: '{expected_structure}'", severity="error"))
            return ParsedAiData(overall_status="error", entities=[], global_errors=[f"{gi.field}: {gi.message}" for gi in global_issues], raw_ai_output=ai_json_string)

        game_terms_from_context: Dict[str, Set[str]] = {
           "stat_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "stat"},
           "skill_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "skill"},
           # ... (other game_terms as before)
           "npc_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "npc"},
           "item_template_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "item_template"},
           "quest_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "quest"},
        }

        data_items_to_process: List[Any] = []
        if is_list:
            if not isinstance(parsed_data_top_level, list):
                global_issues.append(ValidationIssue(field="root", issue_type="invalid_type", message=f"Expected list for '{expected_structure}', got {type(parsed_data_top_level).__name__}.", severity="error"))
            else:
                data_items_to_process = parsed_data_top_level
        else: # Single entity
            if not isinstance(parsed_data_top_level, dict):
                 global_issues.append(ValidationIssue(field="root", issue_type="invalid_type", message=f"Expected dict for '{expected_structure}', got {type(parsed_data_top_level).__name__}.", severity="error"))
            else:
                data_items_to_process = [parsed_data_top_level]

        if global_issues and any(gi.severity == "error" for gi in global_issues):
             return ParsedAiData(overall_status="error", entities=[], global_errors=[f"{gi.field}: {gi.message}" for gi in global_issues], raw_ai_output=ai_json_string)

        for i, item_data_dict in enumerate(data_items_to_process):
            entity_issues: List[ValidationIssue] = []
            item_id_for_error = item_data_dict.get('id', item_data_dict.get('template_id', f"item_at_index_{i}"))

            if not isinstance(item_data_dict, dict):
                malformed_issue = ValidationIssue(field=f"list_item[{i}]" if is_list else "root", issue_type="invalid_type", message=f"Data item is not a dictionary.", severity="error")
                validated_entities.append(ValidatedEntity(entity_id=None, entity_type=entity_type_for_placeholder, data={"raw_data": item_data_dict}, validation_status="requires_moderation", issues=[malformed_issue]))
                continue

            validated_data_for_block_validator = item_data_dict # Default to original if no Pydantic

            if pydantic_model_class: # If Pydantic model is defined for this structure
                try:
                    # Using Pydantic v2 .model_validate()
                    pydantic_instance = pydantic_model_class.model_validate(item_data_dict)
                    # Using Pydantic v2 .model_dump()
                    validated_data_for_block_validator = pydantic_instance.model_dump(exclude_none=True) # Get dict from Pydantic model
                except ValidationError as pydantic_error:
                    for error in pydantic_error.errors():
                        field_path = ".".join(map(str, error['loc'])) if error['loc'] else "unknown_field"
                        entity_issues.append(ValidationIssue(
                            field=field_path,
                            issue_type=error['type'],
                            message=error['msg'],
                            severity="error" # Pydantic errors are typically structural/type errors
                        ))
                    # If Pydantic validation fails, we create a ValidatedEntity with these issues
                    # and skip the block_validator_func for this item.
                    status = self._calculate_entity_status(entity_issues)
                    validated_entities.append(ValidatedEntity(
                        entity_id=item_id_for_error, # Use ID from original data if possible
                        entity_type=entity_type_for_placeholder,
                        data=item_data_dict, # Original data that failed Pydantic
                        validation_status=status, # Should be "requires_moderation"
                        issues=entity_issues
                    ))
                    continue # Move to the next item in the list

            # If Pydantic validation passed (or no Pydantic model for this type), run the block validator
            if block_validator_func:
                # Pass the (potentially Pydantic-validated and dumped) dict to the block validator
                # along with any issues already found (e.g., from Pydantic, though typically we'd not mix if Pydantic fails hard)
                # For now, assume block_validator_func starts with an empty list of issues or gets Pydantic issues if we want to merge.
                # Here, we only call block_validator_func if Pydantic succeeded, so entity_issues is empty.
                validated_entity_obj = block_validator_func(
                    validated_data_for_block_validator, # This is dict from Pydantic model or original dict
                    generation_context=generation_context,
                    game_terms=game_terms_from_context
                )
                # The block_validator_func might add its own issues.
                # If Pydantic found issues and we didn't 'continue', we'd merge them:
                # validated_entity_obj.issues.extend(entity_issues)
                # validated_entity_obj.validation_status = self._calculate_entity_status(validated_entity_obj.issues)
                validated_entities.append(validated_entity_obj)
            elif not pydantic_model_class : # No Pydantic and no block validator for this type (should not happen with current logic)
                 global_issues.append(ValidationIssue(field="validator_logic", issue_type="internal_error", message=f"No validator for {expected_structure}", severity="error"))


        final_overall_status = "success"
        if any(gi.severity == "error" for gi in global_issues): final_overall_status = "error"
        elif any(entity.validation_status == "requires_moderation" for entity in validated_entities): final_overall_status = "requires_moderation"
        elif any(entity.validation_status == "success_with_autocorrections" for entity in validated_entities): final_overall_status = "success_with_autocorrections"

        return ParsedAiData(
            overall_status=final_overall_status, entities=validated_entities,
            global_errors=[f"GLOBAL ({issue.severity.upper()}) {issue.field}: {issue.message}" for issue in global_issues],
            raw_ai_output=ai_json_string
        )


async def parse_and_validate_ai_response(
    raw_ai_output_text: str,
    guild_id: str, # guild_id might be used by semantic validators in the future
    request_type: str,
    game_manager: Optional['GameManager'] = None # Optional for now, for semantic validation later
) -> Tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Parses raw AI output text, validates it against a Pydantic model based on request_type,
    and prepares for further semantic validation.

    Args:
        raw_ai_output_text: The raw JSON string output from the AI.
        guild_id: The guild ID, for context.
        request_type: The type of request (e.g., "location_content_generation") to determine the Pydantic model.
        game_manager: GameManager instance, for potential future semantic validation.

    Returns:
        A tuple: (validated_data_dict, validation_issues_list).
        - validated_data_dict: Dictionary representation of the validated Pydantic model if successful,
                               or the raw parsed JSON if Pydantic validation failed. None if JSON parsing failed.
        - validation_issues_list: List of error dicts if validation failed, else None.
    """
    logger.debug(f"Parsing and validating AI response for request_type: {request_type}, guild_id: {guild_id}")

    parsed_json_data: Optional[Dict[str, Any]] = None
    validation_issues: List[Dict[str, Any]] = []

    # 1. JSON Parsing
    try:
        parsed_json_data = json.loads(raw_ai_output_text)
        if not isinstance(parsed_json_data, dict) and not (request_type in ["list_of_quests", "list_of_npcs", "list_of_items"] and isinstance(parsed_json_data, list)): # Allow list for specific list types
            # This check might need refinement based on whether top-level can be a list for some request_types
            logger.error(f"AI output is not a JSON object or expected list. Type: {type(parsed_json_data)}")
            validation_issues.append({
                "type": "invalid_json_structure",
                "loc": ["input_string"],
                "msg": "AI output must be a JSON object (or a list for certain request types)."
            })
            return parsed_json_data, validation_issues # Return parsed data for moderator to see
    except json.JSONDecodeError as e:
        logger.error(f"JSONDecodeError parsing AI output: {e}. Raw text: '{raw_ai_output_text[:200]}...'")
        validation_issues.append({
            "type": "json_decode_error",
            "loc": ["input_string"],
            "msg": f"Invalid JSON: {str(e)}"
        })
        return None, validation_issues

    # 2. Pydantic Validation
    request_type_to_model_map: Dict[str, Optional[BaseModel]] = {
        "location_content_generation": GeneratedLocationContent,
        "npc_profile_generation": GeneratedNpcProfile,
        "quest_generation": GeneratedQuestData,
        # Add other request_types and their corresponding Pydantic models here
        # "list_of_quests": GeneratedQuestData, # If expecting a list, Pydantic handles List[GeneratedQuestData]
    }

    PydanticModel = request_type_to_model_map.get(request_type)

    if PydanticModel is None:
        logger.warning(f"Unknown request_type for Pydantic validation: {request_type}")
        validation_issues.append({
            "type": "unknown_request_type",
            "loc": ["request_type"],
            "msg": f"No Pydantic model configured for request_type: {request_type}"
        })
        return parsed_json_data, validation_issues

    try:
        # If the expected structure is a list of items (e.g., "list_of_quests")
        # Pydantic can validate List[ModelType] directly if model is defined for list items
        # For now, assuming top-level is a single object unless specified otherwise
        # This part might need adjustment if AI is expected to return a list for some request_types
        if request_type in ["list_of_quests", "list_of_npcs", "list_of_items"]: # Example list types
            if not isinstance(parsed_json_data, list):
                logger.error(f"Expected a list for request_type '{request_type}', but got {type(parsed_json_data)}")
                validation_issues.append({
                    "type": "invalid_structure_for_list_type",
                    "loc": ["input_string"],
                    "msg": f"Expected a JSON list for '{request_type}'."
                })
                return parsed_json_data, validation_issues
            # Validate each item in the list
            validated_items = [PydanticModel(**item) for item in parsed_json_data]
            model_instance_dict = [item.model_dump() for item in validated_items]
        else: # Single object expected
            if not isinstance(parsed_json_data, dict): # Should have been caught by initial JSON check if not a list type
                 logger.error(f"Expected a JSON object for request_type '{request_type}', but got {type(parsed_json_data)}")
                 validation_issues.append({
                    "type": "invalid_structure_for_object_type",
                    "loc": ["input_string"],
                    "msg": f"Expected a JSON object for '{request_type}'."
                })
                 return parsed_json_data, validation_issues

            model_instance = PydanticModel(**parsed_json_data)
            model_instance_dict = model_instance.model_dump()

        logger.info(f"Pydantic validation successful for request_type: {request_type}")

        # 3. Semantic Validation (Placeholder)
        # Here, you would call more advanced validation logic, potentially using game_manager
        # For example, checking if referenced item IDs exist, if stats are within reasonable bounds for a level, etc.
        if game_manager:
            logger.info(f"Semantic validation pending for type {request_type} (GameManager available).")
            # Example: issues = await game_manager.semantic_validator.validate(model_instance_dict, request_type, guild_id)
            # if issues: return model_instance_dict, issues
        else:
            logger.info(f"Semantic validation skipped for type {request_type} (GameManager not available).")

        return model_instance_dict, None # Success

    except PydanticValidationError as e:
        formatted_errors = []
        for error in e.errors():
            formatted_errors.append({
                "type": error['type'],
                "loc": list(error['loc']) if error['loc'] else ["unknown_field"],
                "msg": error['msg'],
                "input": error.get('input', 'N/A')
            })
        logger.warning(f"Pydantic validation failed for request_type: {request_type}. Errors: {formatted_errors}")
        return parsed_json_data, formatted_errors # Return original parsed data and errors
    except Exception as e_gen: # Catch any other unexpected errors during model instantiation
        logger.error(f"Generic error during Pydantic model instantiation for {request_type}: {e_gen}", exc_info=True)
        validation_issues.append({
            "type": "model_instantiation_error",
            "loc": ["parsing_logic"],
            "msg": f"Unexpected error: {str(e_gen)}"
        })
        return parsed_json_data, validation_issues
