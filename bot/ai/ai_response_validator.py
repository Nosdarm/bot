import json
import logging
from pydantic import BaseModel, ValidationError as PydanticValidationError
from typing import Tuple, TYPE_CHECKING, Any, Dict, Optional, List, Union # Added Union

from .ai_data_models import (
    GeneratedLocationContent,
    GeneratedNpcProfile,
    GeneratedQuestData,
    GeneratedItemProfile,
    ValidationIssue # Import the updated ValidationIssue model
)

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__)

class AIResponseValidator:
    def __init__(self):
        pass

    # _create_validation_issue is removed as per plan. ValidationIssue instances will be created directly.

    def _check_id_in_terms(self, entity_id: Optional[str], expected_term_type: str, game_terms: List[Dict[str, Any]], field_path: Union[str, List[Union[str,int]]]) -> Optional[ValidationIssue]:
        if not entity_id:
            return None

        loc_path = [field_path] if isinstance(field_path, str) else field_path

        if not any(term.get('id') == entity_id and term.get('term_type') == expected_term_type for term in game_terms):
            return ValidationIssue(
                loc=loc_path,
                type="semantic.invalid_id_reference",
                msg=f"Invalid ID: '{entity_id}' not found as a known '{expected_term_type}'.",
                input_value=entity_id,
                severity="warning",
                suggestion=f"Ensure the ID exists in game_terms as type '{expected_term_type}' or is a standard placeholder if allowed."
            )
        return None

    def _semantic_validate_npc_profile(self, data_dict: Dict[str, Any], game_terms: List[Dict[str, Any]], guild_id: str, game_manager: Optional['GameManager']) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []

        # Validate stat IDs against game_terms
        for stat_key in data_dict.get('stats', {}).keys():
            issue = self._check_id_in_terms(stat_key, "stat", game_terms, ["stats", stat_key])
            if issue: issues.append(issue)

        # Validate stat value ranges if game_manager is available
        if game_manager:
            npc_archetype = data_dict.get('archetype')
            npc_stats = data_dict.get('stats', {})

            # Fetch stat range rules once
            all_npc_stat_ranges = game_manager.get_rule(guild_id, "npc_stat_ranges", default={})
            archetype_specific_ranges = all_npc_stat_ranges.get(npc_archetype, {}) if npc_archetype else {}
            global_stat_limits = game_manager.get_rule(guild_id, "npc_global_stat_limits", default={})

            for stat_key, stat_value in npc_stats.items():
                if not isinstance(stat_value, (int, float)):
                    issues.append(ValidationIssue(
                        loc=["stats", stat_key], type="semantic.stat_value_not_numeric",
                        msg=f"Stat '{stat_key}' value '{stat_value}' is not a number.",
                        input_value=stat_value, severity="warning"
                    ))
                    continue

                # Check archetype-specific range first
                stat_rule = archetype_specific_ranges.get(stat_key)
                # If not found, check global range
                if not stat_rule:
                    stat_rule = global_stat_limits.get(stat_key)

                if stat_rule and isinstance(stat_rule, dict):
                    min_val = stat_rule.get('min')
                    max_val = stat_rule.get('max')

                    if min_val is not None and stat_value < min_val:
                        issues.append(ValidationIssue(
                            loc=["stats", stat_key], type="semantic.stat_out_of_range.min",
                            msg=f"Stat '{stat_key}' value {stat_value} is below minimum {min_val} for archetype '{npc_archetype or 'global'}'.",
                            input_value=stat_value, severity="warning",
                            suggestion=f"Value should be >= {min_val}."
                        ))
                    if max_val is not None and stat_value > max_val:
                        issues.append(ValidationIssue(
                            loc=["stats", stat_key], type="semantic.stat_out_of_range.max",
                            msg=f"Stat '{stat_key}' value {stat_value} is above maximum {max_val} for archetype '{npc_archetype or 'global'}'.",
                            input_value=stat_value, severity="warning",
                            suggestion=f"Value should be <= {max_val}."
                        ))
        else:
            logger.info(f"GameManager not available for NPC stat range validation in guild {guild_id}.")


        for skill_key in data_dict.get('skills', {}).keys():
            issue = self._check_id_in_terms(skill_key, "skill", game_terms, ["skills", skill_key])
            if issue: issues.append(issue)

        for i, ability_id in enumerate(data_dict.get('abilities', [])):
            issue = self._check_id_in_terms(ability_id, "ability", game_terms, ["abilities", i])
            if issue: issues.append(issue)

        for i, spell_id in enumerate(data_dict.get('spells', [])):
            issue = self._check_id_in_terms(spell_id, "spell", game_terms, ["spells", i])
            if issue: issues.append(issue)

        for i, item_entry in enumerate(data_dict.get('inventory', [])):
            item_tpl_id = item_entry.get('item_template_id')
            issue = self._check_id_in_terms(item_tpl_id, "item_template", game_terms, ["inventory", i, "item_template_id"])
            if issue: issues.append(issue)

        for i, faction_entry in enumerate(data_dict.get('faction_affiliations', [])):
            faction_id = faction_entry.get('faction_id')
            issue = self._check_id_in_terms(faction_id, "faction", game_terms, ["faction_affiliations", i, "faction_id"])
            if issue: issues.append(issue)

        archetype = data_dict.get('archetype')
        if archetype:
            issue = self._check_id_in_terms(archetype, "npc_archetype", game_terms, "archetype")
            if issue: issues.append(issue)
        return issues

    def _semantic_validate_quest_data(self, data_dict: Dict[str, Any], game_terms: List[Dict[str, Any]], guild_id: str) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        npc_involvement = data_dict.get('npc_involvement', {})
        if isinstance(npc_involvement, dict):
            for role, npc_id in npc_involvement.items():
                issue = self._check_id_in_terms(npc_id, "npc_archetype", game_terms, ["npc_involvement", role])
                if issue: issues.append(issue)

        for json_field_name in ["rewards_json", "prerequisites_json"]:
            json_str = data_dict.get(json_field_name)
            if json_str:
                try:
                    content = json.loads(json_str)
                    if isinstance(content, dict) and "items" in content and isinstance(content["items"], list):
                        for i, item_ref in enumerate(content["items"]):
                            if isinstance(item_ref, dict) and "item_id" in item_ref:
                                item_id = item_ref["item_id"]
                                issue = self._check_id_in_terms(item_id, "item_template", game_terms, [json_field_name, "items", i, "item_id"])
                                if issue: issues.append(issue)
                except json.JSONDecodeError: pass

        for i, step in enumerate(data_dict.get('steps', [])):
            # Placeholder for deeper step validation (e.g., checking IDs within step's JSON fields)
            pass
        return issues

    def _semantic_validate_location_content(self, data_dict: Dict[str, Any], game_terms: List[Dict[str, Any]], guild_id: str, game_manager: Optional['GameManager']) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        # Existing semantic checks for location content (e.g., PoI item/NPC IDs, connections)
        for i, poi in enumerate(data_dict.get('points_of_interest', [])):
            for j, item_id in enumerate(poi.get('contained_item_ids', [])): # This field might not exist on current PoI model
                issue = self._check_id_in_terms(item_id, "item_template", game_terms, ["points_of_interest", i, "contained_item_ids", j])
                if issue: issues.append(issue)

            # Example: If PoIs can have NPCs directly listed by archetype for generation
            for k, npc_archetype_id in enumerate(poi.get('npc_archetypes_to_spawn', [])): # Assuming such a field could exist
                issue = self._check_id_in_terms(npc_archetype_id, "npc_archetype", game_terms, ["points_of_interest", i, "npc_archetypes_to_spawn", k])
                if issue: issues.append(issue)

        for i, conn in enumerate(data_dict.get('connections', [])): # This field might not exist on current Location model
            to_loc_id = conn.get('to_location_id')
            if to_loc_id and not any(term.get('id') == to_loc_id and term.get('term_type') in ["location_template", "location"] for term in game_terms):
                 issues.append(ValidationIssue(
                    loc=["connections", i, "to_location_id"],
                    type="semantic.unknown_location_reference",
                    msg=f"Connected location ID '{to_loc_id}' does not match any known location template or instance ID.",
                    input_value=to_loc_id,
                    severity="info",
                    suggestion="If this is a new location, ensure its full definition is also provided or generated."
                ))
        return issues

    def _semantic_validate_item_profile(self, data_dict: Dict[str, Any], game_terms: List[Dict[str, Any]], guild_id: str) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []
        # item_type = data_dict.get('item_type') # Placeholder for item_type validation
        # equip_slot = data_dict.get('equipable_slot') # Placeholder for equip_slot validation

        properties_json_str = data_dict.get('properties_json')
        if properties_json_str:
            try:
                properties = json.loads(properties_json_str)
                if isinstance(properties, dict):
                    if "grants_skill" in properties:
                        skill_id = properties["grants_skill"]
                        issue = self._check_id_in_terms(skill_id, "skill", game_terms, ["properties_json", "grants_skill"])
                        if issue: issues.append(issue)
                    if "grants_ability" in properties:
                        ability_id = properties["grants_ability"]
                        issue = self._check_id_in_terms(ability_id, "ability", game_terms, ["properties_json", "grants_ability"])
                        if issue: issues.append(issue)
            except json.JSONDecodeError:
                # This was already handled by the main JSON decode, but if properties_json itself is a string needing further parsing
                issues.append(ValidationIssue(
                    loc=["properties_json"], type="json_decode_error.string_content",
                    msg=f"Content of 'properties_json' is not valid JSON.",
                    input_value=properties_json_str[:100], severity="error"
                ))

        # Item value validation
        if game_manager:
            assert game_manager is not None # Ensure game_manager is not None for type checkers and runtime safety
            item_type = data_dict.get('item_type') # Assuming item_type is a simple string like "weapon", "potion"
            rarity_level = data_dict.get('rarity_tag') # Assuming a field like "rarity_tag": "common", "rare"
            base_value = data_dict.get('base_value')

            if item_type and rarity_level and isinstance(base_value, (int, float)):
                all_item_value_ranges = game_manager.get_rule(guild_id, "item_value_ranges", default={})
                type_ranges = all_item_value_ranges.get(item_type, {})
                rarity_specific_rule = type_ranges.get(rarity_level)

                if rarity_specific_rule and isinstance(rarity_specific_rule, dict):
                    min_val = rarity_specific_rule.get('min')
                    max_val = rarity_specific_rule.get('max')

                    if min_val is not None and base_value < min_val:
                        issues.append(ValidationIssue(
                            loc=["base_value"], type="semantic.value_out_of_range.min",
                            msg=f"Item base_value {base_value} is below minimum {min_val} for type '{item_type}' rarity '{rarity_level}'.",
                            input_value=base_value, severity="warning",
                            suggestion=f"Value should be >= {min_val}."
                        ))
                    if max_val is not None and base_value > max_val:
                        issues.append(ValidationIssue(
                            loc=["base_value"], type="semantic.value_out_of_range.max",
                            msg=f"Item base_value {base_value} is above maximum {max_val} for type '{item_type}' rarity '{rarity_level}'.",
                            input_value=base_value, severity="warning",
                            suggestion=f"Value should be <= {max_val}."
                        ))
            elif base_value is not None and not isinstance(base_value, (int, float)):
                 issues.append(ValidationIssue(
                    loc=["base_value"], type="semantic.value_not_numeric",
                    msg=f"Item base_value '{base_value}' is not a number.",
                    input_value=base_value, severity="warning"
                ))
        else:
            logger.info(f"GameManager not available for item value range validation in guild {guild_id}.")

        return issues

    async def parse_and_validate_ai_response(
        self,
        raw_ai_output_text: str,
        guild_id: str,
        request_type: str,
        game_manager: Optional['GameManager'] = None # game_manager is now passed here
    ) -> Tuple[Optional[Dict[str, Any]], Optional[List[ValidationIssue]]]:
        logger.debug(f"Parsing and validating AI response for request_type: {request_type}, guild_id: {guild_id}")

        parsed_json_data: Optional[Dict[str, Any]] = None
        pydantic_issues: List[ValidationIssue] = []
        semantic_issues: List[ValidationIssue] = []
        model_instance_dict: Optional[Dict[str, Any]] = None

        try:
            parsed_json_data = json.loads(raw_ai_output_text)
        except json.JSONDecodeError as e:
            logger.error(f"JSONDecodeError: {e}. Raw: '{raw_ai_output_text[:200]}...'")
            pydantic_issues.append(ValidationIssue(loc=["input_string"], type="json_decode_error", msg=str(e), input_value=raw_ai_output_text[:200]))
            return None, pydantic_issues

        request_type_to_model_map: Dict[str, Any] = {
            "location_content_generation": GeneratedLocationContent,
            "npc_profile_generation": GeneratedNpcProfile,
            "quest_generation": GeneratedQuestData,
            "item_profile_generation": GeneratedItemProfile,
        }
        PydanticModel = request_type_to_model_map.get(request_type)

        if PydanticModel is None:
            logger.warning(f"Unknown request_type for Pydantic: {request_type}")
            pydantic_issues.append(ValidationIssue(loc=["request_type"], type="unknown_request_type", msg=f"No Pydantic model for {request_type}", input_value=request_type))
            return parsed_json_data, pydantic_issues

        validation_context = {}
        target_languages = ['en']
        if game_manager:
            try:
                guild_main_lang = await game_manager.get_rule(guild_id, "default_language", "en")
                target_languages = sorted(list(set([guild_main_lang, "en"])))
                validation_context["target_languages"] = target_languages
            except Exception as e: logger.error(f"Failed to get guild language for context: {e}", exc_info=True)
        else:
            logger.warning("GameManager not provided. i18n validation may use default 'en'.")
        validation_context.setdefault("target_languages", ['en'])


        try:
            if not isinstance(parsed_json_data, dict):
                 logger.error(f"Expected JSON object for '{request_type}', got {type(parsed_json_data).__name__}")
                 pydantic_issues.append(ValidationIssue(loc=["input_string"], type="invalid_structure.not_dict", msg=f"Expected JSON object, got {type(parsed_json_data).__name__}.", input_value=parsed_json_data))
            else:
                model_instance = PydanticModel.model_validate(parsed_json_data, context=validation_context)
                model_instance_dict = model_instance.model_dump()
                logger.info(f"Pydantic validation successful for {request_type}")

        except PydanticValidationError as e:
            for error in e.errors():
                pydantic_issues.append(ValidationIssue(loc=list(error['loc']), type=error['type'], msg=error['msg'], input_value=error.get('input')))
            logger.warning(f"Pydantic validation failed for {request_type}. Errors: {pydantic_issues}")
        except Exception as e_gen:
            logger.error(f"Generic error during Pydantic processing for {request_type}: {e_gen}", exc_info=True)
            pydantic_issues.append(ValidationIssue(loc=["validation_logic"], type="model_processing_error", msg=f"Unexpected error: {str(e_gen)}"))

        if not pydantic_issues and model_instance_dict is not None and game_manager and game_manager.prompt_context_collector:
            try:
                game_rules_data = await game_manager.prompt_context_collector.get_game_rules_summary(guild_id)
                # Note: get_game_terms_dictionary is synchronous. Ability/spell defs are passed via kwargs from get_full_context.
                # For direct use here, we might need a way to pass those, or accept that semantic checks for them might be limited.
                game_terms = game_manager.prompt_context_collector.get_game_terms_dictionary(guild_id, game_rules_data=game_rules_data)

                if request_type == "npc_profile_generation":
                    semantic_issues.extend(self._semantic_validate_npc_profile(model_instance_dict, game_terms, guild_id, game_manager))
                elif request_type == "quest_generation":
                    semantic_issues.extend(self._semantic_validate_quest_data(model_instance_dict, game_terms, guild_id)) # Pass game_manager if needed
                elif request_type == "location_content_generation":
                    semantic_issues.extend(self._semantic_validate_location_content(model_instance_dict, game_terms, guild_id, game_manager)) # Pass game_manager if needed
                elif request_type == "item_profile_generation":
                    semantic_issues.extend(self._semantic_validate_item_profile(model_instance_dict, game_terms, guild_id, game_manager))

                if semantic_issues: logger.info(f"Semantic validation found {len(semantic_issues)} issues for {request_type}.")
            except Exception as e_sem:
                logger.error(f"Error during semantic validation for {request_type}: {e_sem}", exc_info=True)
                semantic_issues.append(ValidationIssue(loc=["semantic_validation_process"], type="semantic.internal_error", msg=f"Error: {str(e_sem)}"))
        elif not game_manager or not game_manager.prompt_context_collector:
            logger.info("GameManager or PromptContextCollector not available, skipping semantic validation.")

        all_issues = pydantic_issues + semantic_issues
        data_to_return = model_instance_dict if model_instance_dict else parsed_json_data

        return data_to_return, all_issues if all_issues else None

    # --- Deprecated Methods ---
    async def parse_and_validate_location_description_response(self, raw_ai_output_text: str, guild_id: str, game_manager: "GameManager") -> Optional[Dict[str, str]]:
        logger.warning("Deprecated: Use parse_and_validate_ai_response with request_type='location_content_generation'.")
        data, issues = await self.parse_and_validate_ai_response(raw_ai_output_text, guild_id, "location_content_generation", game_manager)
        if data and not issues and isinstance(data.get("atmospheric_description_i18n"), dict): return data["atmospheric_description_i18n"]
        return None

    async def parse_and_validate_faction_generation_response(self, raw_ai_output_text: str, guild_id: str, game_manager: "GameManager") -> Optional[List[Dict[str, Any]]]:
        logger.warning("Deprecated. Faction generation validation needs specific Pydantic model and request_type.")
        return None

    async def parse_and_validate_quest_generation_response(self, raw_ai_output_text: str, guild_id: str, game_manager: "GameManager") -> Optional[Dict[str, Any]]:
        logger.warning("Deprecated: Use parse_and_validate_ai_response with request_type='quest_generation'.")
        data, issues = await self.parse_and_validate_ai_response(raw_ai_output_text, guild_id, "quest_generation", game_manager)
        return data if data and not issues else None

    async def parse_and_validate_item_generation_response(self, raw_ai_output_text: str, guild_id: str, game_manager: "GameManager") -> Optional[List[Dict[str, Any]]]:
        logger.warning("Deprecated. For single item, use request_type='item_profile_generation'. For lists, new type needed.")
        return None

    async def parse_and_validate_npc_generation_response(self, raw_ai_output_text: str, guild_id: str, game_manager: "GameManager") -> Optional[List[Dict[str, Any]]]:
        logger.warning("Deprecated. For single NPC, use request_type='npc_profile_generation'. For lists, new type needed.")
        return None
