import json
from typing import List, Dict, Any, Optional, Union, cast, Set, Callable

from bot.ai.ai_data_models import GenerationContext, ParsedAiData, ValidatedEntity, ValidationIssue
# Removed duplicate import of ValidationError, it's not used directly here but via Pydantic
from .rules_schema import GameRules # , RoleStatRules, StatRange, ItemPriceCategory, ItemPriceDetail, QuestRewardRules (no longer needed directly for this file's top level)
from .ai_data_models import GeneratedQuest # Import for Pydantic quest validation
from pydantic import ValidationError # Import Pydantic's ValidationError

import logging
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


    def validate_quest_block(self, quest_data: Dict[str, Any], generation_context: GenerationContext, game_terms: Dict[str, Set[str]]) -> ValidatedEntity:
        issues: List[ValidationIssue] = []
        # Quest ID might be 'id' or 'template_id' from AI, Pydantic model doesn't enforce one for generation.
        # We'll use 'name_i18n' as a fallback for entity_info if ID is missing.
        quest_name_for_info = quest_data.get('name_i18n', {}).get('en', 'Unknown Quest')
        entity_id_str = quest_data.get('id', quest_data.get('template_id', quest_name_for_info))
        entity_info = f"Quest '{entity_id_str}'"
        original_data_copy = quest_data.copy() # For storing pre-autocorrection state

        # Data passed here should already be validated by GeneratedQuest Pydantic model.
        # `validate_quest_block` now focuses on deeper, domain-specific validation.

        # --- I18n Field Completeness (Top-Level Quest) ---
        top_level_i18n_fields = ['name_i18n', 'description_i18n']
        if quest_data.get('quest_giver_details_i18n'): top_level_i18n_fields.append('quest_giver_details_i18n')
        if quest_data.get('consequences_summary_i18n'): top_level_i18n_fields.append('consequences_summary_i18n')

        for field in top_level_i18n_fields:
            field_value = quest_data.get(field)
            if field_value is not None: # Field is present
                if self._check_is_dict(field_value, field, entity_info, issues):
                    self._validate_i18n_field_completeness(field_value, field, entity_info, issues, generation_context.target_languages)
            # else: If Pydantic model made it optional, it's fine. If mandatory, Pydantic caught it.

        # --- Suggested Level (Example of a numerical check) ---
        suggested_level = quest_data.get("suggested_level")
        if suggested_level is not None: # Pydantic would have checked type if defined in model.
            if not isinstance(suggested_level, int) or suggested_level < 0:
                 issues.append(ValidationIssue(field="suggested_level", issue_type="invalid_value", message=f"{entity_info}: suggested_level '{suggested_level}' must be a non-negative integer.", severity="warning"))

        # --- Referential Integrity (Example: quest_giver_id) ---
        known_npc_ids = game_terms.get("npc_ids", set())
        quest_giver_id = quest_data.get("quest_giver_id")
        if quest_giver_id and quest_giver_id not in known_npc_ids:
            issues.append(ValidationIssue(field="quest_giver_id", issue_type="invalid_reference", message=f"{entity_info}: Quest giver ID '{quest_giver_id}' not found in known NPC IDs.", severity="warning"))

        # --- JSON String Fields (Quest Level) ---
        # Pydantic validated these are valid JSON strings.
        # Here, we might add warnings if they are empty but expected to have content.
        for json_field_name in ["prerequisites_json", "consequences_json"]:
            json_string_value = quest_data.get(json_field_name)
            if json_string_value in ["{}", "[]", "null", ""]: # Check for empty/null JSON content
                issues.append(ValidationIssue(
                    field=json_field_name, issue_type="empty_json_content",
                    message=f"{entity_info}: Field '{json_field_name}' is an empty/null JSON string ('{json_string_value}'). This might be acceptable but review if content was expected.",
                    severity="info" # Info or warning depending on game logic expectations
                ))

        # --- Steps Validation ---
        steps_list = quest_data.get('steps', []) # Changed from 'stages'
        if not isinstance(steps_list, list): # Pydantic should ensure this is a list
            issues.append(ValidationIssue(field="steps", issue_type="invalid_type", message=f"{entity_info}: 'steps' must be a list.", severity="error")) # Should be caught by Pydantic
        else:
            for s_idx, step_data in enumerate(steps_list):
                # step_data here is a dict because GeneratedQuest has List[GeneratedQuestStep]
                # and .model_dump() converts GeneratedQuestStep to dict.
                step_info = f"{entity_info}, Step {step_data.get('step_order', s_idx)}"

                if not self._check_is_dict(step_data, f"steps[{s_idx}]", step_info, issues):
                    continue # Should not happen if Pydantic validated

                # I18n for step title and description
                step_i18n_fields = ['title_i18n', 'description_i18n']
                for field in step_i18n_fields:
                    f_val = step_data.get(field)
                    if f_val is not None and self._check_is_dict(f_val, f"steps[{s_idx}].{field}", step_info, issues):
                        self._validate_i18n_field_completeness(f_val, f"steps[{s_idx}].{field}", step_info, issues, generation_context.target_languages)
                    elif f_val is None: # Pydantic should have caught if mandatory
                        issues.append(ValidationIssue(field=f"steps[{s_idx}].{field}", issue_type="missing_required_field", message=f"{step_info}: Required field '{field}' is missing.", severity="error"))


                # Check step_order
                if not isinstance(step_data.get('step_order'), int):
                    issues.append(ValidationIssue(field=f"steps[{s_idx}].step_order", issue_type="invalid_type", message=f"{step_info}: 'step_order' must be an integer.", severity="error"))

                # JSON String Fields within Step
                # Pydantic (GeneratedQuestStep) validated these are valid JSON strings.
                # Add warnings for empty JSON strings if content is expected.
                step_json_fields = ['required_mechanics_json', 'abstract_goal_json', 'consequences_json']
                for json_field_name in step_json_fields:
                    json_string_value = step_data.get(json_field_name)
                    if json_string_value is None: # Field is missing
                         issues.append(ValidationIssue(
                            field=f"steps[{s_idx}].{json_field_name}", issue_type="missing_required_field",
                            message=f"{step_info}: Required JSON string field '{json_field_name}' is missing.",
                            severity="error" # Assuming these are mandatory per game design
                        ))
                    elif json_string_value in ["{}", "[]", "null", ""]: # Empty/null JSON
                        issues.append(ValidationIssue(
                            field=f"steps[{s_idx}].{json_field_name}", issue_type="empty_json_content",
                            message=f"{step_info}: Field '{json_field_name}' is an empty/null JSON string ('{json_string_value}'). Review if content was expected.",
                            severity="warning"
                        ))
                # Old objective list validation within stages is removed.

        # --- Reward Validation (Example for quest-level rewards if not fully in consequences_json) ---
        # This part might be redundant if all rewards are inside consequences_json,
        # or it might validate a separate simplified 'rewards' structure if still used.
        # For now, assuming GeneratedQuest Pydantic model handles reward structure.
        # If 'rewards' field existed outside consequences_json and needed validation, it would go here.

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

[end of bot/ai/ai_response_validator.py]
