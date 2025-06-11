"""
Provides the AIResponseValidator class for validating AI-generated game content.

This module is responsible for ensuring that JSON data produced by AI (e.g., for NPCs,
quests, items) adheres to predefined game rules and structural expectations. It uses
Pydantic models defined in `rules_schema.py` to perform these validations.
The validator can also perform auto-corrections (like clamping values) and flags
content that requires manual moderation.
"""
import json
from typing import List, Dict, Any, Optional, Union, cast, Set, Callable

from bot.ai.ai_data_models import GenerationContext, ParsedAiData, ValidationError, ValidatedEntity, ValidationIssue
from bot.ai.ai_data_models import GenerationContext, ParsedAiData, ValidationError, ValidatedEntity, ValidationIssue
from .rules_schema import GameRules, RoleStatRules, StatRange, ItemPriceCategory, ItemPriceDetail, QuestRewardRules
# Game models are used for type hinting and as a structural reference,
# though the validator primarily works with dictionaries from AI JSON.
# from bot.game.models.npc import NPC # Not directly used now
# from bot.game.models.quest import Quest # Not directly used now
# from bot.game.models.item import Item # Not directly used now


# Type alias for the specific signature of block validator functions
ValidatorFuncType = Callable[[Dict[str, Any], GenerationContext, Dict[str, Set[str]]], ValidatedEntity]

class AIResponseValidator:
    """
    Validates AI-generated JSON content against a set of game rules.

    The validator checks for structural correctness, adherence to defined value ranges,
    validity of types/IDs, i18n content completeness, and can perform auto-corrections.
    It reports errors, notifications (for auto-corrections or warnings), and flags
    content that requires manual moderation.
    """
    def __init__(self, rules: GameRules):
        """
        Initializes the AIResponseValidator.

        Args:
            rules: A GameRules object containing all the rule definitions (loaded from config).
        """
        self.rules = rules

    def _check_is_dict(self, data: Any, field_name: str, entity_id_info: str, issues: List[ValidationIssue]) -> bool:
        """
        Helper to check if the provided data is a dictionary. Appends an issue if not.

        Args:
            data: The data to check.
            field_name: The name of the field being checked (for error messages).
            entity_id_info: Contextual information about the entity (for error messages).
            issues: The list to append ValidationIssue objects to.

        Returns:
            True if data is a dictionary, False otherwise.
        """
        if not isinstance(data, dict):
            issues.append(ValidationIssue(
                field=field_name,
                issue_type="invalid_type",
                message=f"{entity_id_info}: Field '{field_name}' must be a dictionary, got {type(data).__name__}.",
                severity="error"
            ))
            return False
        return True

    def _validate_i18n_field_completeness(self, i18n_dict: Dict[str, str], field_name: str, entity_id_info: str, issues: List[ValidationIssue], target_languages: List[str]) -> None:
        """
        Validates that an i18n dictionary (field_name_i18n) has non-empty string translations
        for all languages specified in `target_languages`. Appends ValidationIssue objects to `issues`.

        Args:
            i18n_dict: The dictionary of translations (e.g., {"en": "Hello", "ru": "Привет"}).
            field_name: The name of the i18n field (e.g., "name_i18n").
            entity_id_info: Contextual information (e.g., "NPC 'npc123'") for error messages.
            issues: The list to append ValidationIssue objects to.
            target_languages: A list of language codes for which translations are required.
        """
        for lang_code in target_languages:
            if lang_code not in i18n_dict:
                issues.append(ValidationIssue(
                    field=field_name,
                    issue_type="missing_translation",
                    message=f"{entity_id_info}: Field '{field_name}' is missing translation for language '{lang_code}'.",
                    severity="error"
                ))
            elif not isinstance(i18n_dict.get(lang_code), str) or not (i18n_dict.get(lang_code) or "").strip():
                issues.append(ValidationIssue(
                    field=f"{field_name}.{lang_code}",
                    issue_type="empty_translation",
                    message=f"{entity_id_info}: Field '{field_name}' has empty or non-string content for language '{lang_code}'.",
                    severity="error"
                ))

    def _get_canonical_role_key(self, npc_data: Dict[str, Any], entity_info: str, issues: List[ValidationIssue]) -> Optional[str]:
        """
        Determines a canonical role key string for an NPC from its data.
        Priority:
        1. `npc_data['archetype']` (if string and non-empty)
        2. `npc_data['role']` (if string and non-empty)
        3. `npc_data['role_i18n']` (using 'en' first, then first available non-empty language).
        The role key is converted to lowercase. Appends ValidationIssue objects for info or errors.

        Args:
            npc_data: The NPC data dictionary.
            entity_info: Contextual information for logging/notifications.
            issues: List to append ValidationIssue objects to.

        Returns:
            The canonical role key as a lowercase string, or None if not determinable.
        """
        role_source_field = None
        role_value = None

        if 'archetype' in npc_data and isinstance(npc_data['archetype'], str) and npc_data['archetype'].strip():
            role_source_field = 'archetype'
            role_value = npc_data['archetype'].strip().lower()
        elif 'role' in npc_data and isinstance(npc_data['role'], str) and npc_data['role'].strip():
            role_source_field = 'role'
            role_value = npc_data['role'].strip().lower()
        elif isinstance(npc_data.get('role_i18n'), dict) and npc_data['role_i18n']:
            role_i18n = npc_data['role_i18n']
            if 'en' in role_i18n and isinstance(role_i18n['en'], str) and role_i18n['en'].strip():
                role_source_field = 'role_i18n.en'
                role_value = role_i18n['en'].strip().lower()
            else: # Fallback to first available language
                for lang, value_text in role_i18n.items():
                    if isinstance(value_text, str) and value_text.strip():
                        role_source_field = f'role_i18n.{lang}'
                        role_value = value_text.strip().lower()
                        break
            if not role_value:
                issues.append(ValidationIssue(
                    field="role_i18n",
                    issue_type="missing_content",
                    message=f"{entity_info}: 'role_i18n' is present but contains no valid, non-empty role names.",
                    severity="warning" # Or error, depending on strictness for role
                ))
                return None

        if role_value and role_source_field:
            issues.append(ValidationIssue(
                field=role_source_field,
                issue_type="info",
                message=f"{entity_info}: Using '{role_source_field}' for role: '{role_value}'.",
                severity="info"
            ))
            return role_value

        issues.append(ValidationIssue(
            field="role", # Generic field name as it could be multiple
            issue_type="missing_required_field",
            message=f"{entity_info}: Could not determine NPC role from 'archetype', 'role', or 'role_i18n' fields for stat validation.",
            severity="error" # Usually critical for stat validation
        ))
        return None

    def _calculate_entity_status(self, issues: List[ValidationIssue]) -> str:
        """
        Determines the overall validation status for an entity based on its issues.
        """
        if any(issue.severity == "error" for issue in issues):
            return "requires_moderation"
        if any(issue.issue_type == "auto_correction" for issue in issues): # auto_correction is a 'warning'
            return "success_with_autocorrections"
        # If only 'info' or 'warning' (non-autocorrect) issues, it's still success, but with warnings.
        # For simplicity, we can treat this as "success" or add another status like "success_with_warnings"
        # if any(issue.severity == "warning" for issue in issues):
        #     return "success_with_warnings"
        return "success"


    def validate_npc_block(self, npc_data: Dict[str, Any], generation_context: GenerationContext, game_terms: Dict[str, Set[str]]) -> ValidatedEntity:
        """
        Validates a single NPC data block against game rules.

        Checks i18n completeness, stats, skills, faction affiliations, etc.
        May perform auto-corrections (e.g., clamping stats/skills) and records these
        as ValidationIssues.

        Args:
            npc_data: The NPC data dictionary to validate.
            generation_context: The context used for this generation, including target languages.
            game_terms: Dictionary of known game term IDs (e.g., "stat_ids", "skill_ids", "item_template_ids").

        Returns:
            A ValidatedEntity object.
        """
        issues: List[ValidationIssue] = []
        entity_id_str = npc_data.get('template_id', npc_data.get('id')) # Prefer 'template_id' for NPCs
        entity_info = f"NPC '{entity_id_str or 'Unknown NPC'}'"
        original_data_copy = npc_data.copy() # For storing pre-autocorrection state if needed for ValidatedEntity

        if not self._check_is_dict(npc_data, "NPC root", entity_info, issues):
            # If root is not a dict, further validation is impossible.
            status_str = self._calculate_entity_status(issues)
            return ValidatedEntity(
                entity_id=entity_id_str, entity_type="npc", data=npc_data,
                validation_status=status_str, issues=issues
            )

        # --- I18n Field Completeness ---
        i18n_fields_to_check = [
            'name_i18n', 'backstory_i18n', 'role_i18n',
            'personality_i18n', 'motivation_i18n',
            'dialogue_hints_i18n', 'visual_description_i18n'
        ]
        for field in i18n_fields_to_check:
            field_value = npc_data.get(field)
            if field_value is not None: # Field is present
                if self._check_is_dict(field_value, field, entity_info, issues):
                    self._validate_i18n_field_completeness(field_value, field, entity_info, issues, generation_context.target_languages)
            # else: # If a field is mandatory by schema, Pydantic would ideally catch this.
                  # For now, focusing on completeness if present.
                  # issues.append(ValidationIssue(field=field, issue_type="missing_required_field", ...))


        # --- Role Determination ---
        role_key = self._get_canonical_role_key(npc_data, entity_info, issues)

        # --- Archetype Validation ---
        archetype = npc_data.get("archetype")
        if archetype and isinstance(archetype, str):
            valid_archetypes = game_terms.get("archetype_ids", self.rules.character_stats_rules.get_valid_archetypes()) # Assuming a method or direct access
            if archetype not in valid_archetypes:
                 issues.append(ValidationIssue(field="archetype", issue_type="invalid_reference", message=f"{entity_info}: Archetype '{archetype}' is not in the list of known archetypes.", severity="warning")) # Warning or error
        elif 'archetype' in npc_data : # exists but not string
             issues.append(ValidationIssue(field="archetype", issue_type="invalid_type", message=f"{entity_info}: Archetype field must be a string.", severity="error"))


        # --- Stat Validation ---
        stats_data = npc_data.get('stats')
        known_stat_ids = game_terms.get("stat_ids", set(self.rules.character_stats_rules.valid_stats))
        if self._check_is_dict(stats_data, 'stats', entity_info, issues):
            stats_data = cast(Dict[str, Any], stats_data)
            for stat_key, stat_value in list(stats_data.items()):
                if stat_key not in known_stat_ids:
                    issues.append(ValidationIssue(field=f"stats.{stat_key}", issue_type="invalid_reference", message=f"{entity_info}: Invalid stat name: '{stat_key}'.", severity="error"))
                    continue
                if not isinstance(stat_value, (int, float)):
                    issues.append(ValidationIssue(field=f"stats.{stat_key}", issue_type="invalid_type", message=f"{entity_info}: Stat '{stat_key}' value '{stat_value}' is not a number.", severity="error"))
                    continue

                # Role-based stat value validation (using GameRules as source of truth for ranges)
                if role_key and self.rules.character_stats_rules.stat_ranges_by_role:
                    role_specific_rules = self.rules.character_stats_rules.stat_ranges_by_role.get(role_key)
                    if role_specific_rules and role_specific_rules.stats:
                        stat_range_model = role_specific_rules.stats.get(stat_key)
                        if stat_range_model: # stat_range_model is StatRange
                            min_val, max_val = stat_range_model.min, stat_range_model.max
                            if not (min_val <= stat_value <= max_val):
                                original_value = stat_value
                                corrected_value = max(min_val, min(original_value, max_val))
                                stats_data[stat_key] = corrected_value # Auto-correction
                                issues.append(ValidationIssue(
                                    field=f"stats.{stat_key}", issue_type="auto_correction",
                                    message=f"AUTO-CORRECT: {entity_info}: Stat '{stat_key}' value {original_value} for role '{role_key}' was out of range ({min_val}-{max_val}). Clamped to {corrected_value}.",
                                    severity="warning", recommended_fix=f"Set value to be between {min_val} and {max_val}."
                                ))
                        # else: No specific range for this valid stat under this role.
                    elif role_key: # role_key is valid, but no rules for it in stat_ranges_by_role
                         issues.append(ValidationIssue(field=f"stats.{stat_key}", issue_type="missing_rule_definition", message=f"{entity_info}: No stat range rules for role '{role_key}' for stat '{stat_key}'. Skipping role-based value check.", severity="info"))

        # --- Skill Validation ---
        skills_data = npc_data.get('skills')
        known_skill_ids = game_terms.get("skill_ids", set(self.rules.skill_rules.valid_skills))
        if self._check_is_dict(skills_data, 'skills', entity_info, issues):
            skills_data = cast(Dict[str, Any], skills_data)
            skill_range = self.rules.skill_rules.skill_value_ranges # This is a StatRange object
            min_skill, max_skill = skill_range.min, skill_range.max

            for skill_key, skill_value in list(skills_data.items()):
                if skill_key not in known_skill_ids:
                    issues.append(ValidationIssue(field=f"skills.{skill_key}", issue_type="invalid_reference", message=f"{entity_info}: Invalid skill name: '{skill_key}'.", severity="error"))
                    continue
                if not isinstance(skill_value, (int, float)):
                    issues.append(ValidationIssue(field=f"skills.{skill_key}", issue_type="invalid_type", message=f"{entity_info}: Skill '{skill_key}' value '{skill_value}' is not a number.", severity="error"))
                    continue

                if not (min_skill <= skill_value <= max_skill):
                    original_value = skill_value
                    corrected_value = max(min_skill, min(original_value, max_skill))
                    skills_data[skill_key] = corrected_value # Auto-correction
                    issues.append(ValidationIssue(
                        field=f"skills.{skill_key}", issue_type="auto_correction",
                        message=f"AUTO-CORRECT: {entity_info}: Skill '{skill_key}' value {original_value} was out of range ({min_skill}-{max_skill}). Clamped to {corrected_value}.",
                        severity="warning", recommended_fix=f"Set value between {min_skill} and {max_skill}."
                    ))

        # --- Abilities, Spells, Inventory Validation ---
        for field_name, term_type_key, list_name in [
            ("abilities", "ability_ids", "Abilities"),
            ("spells", "spell_ids", "Spells")
        ]:
            data_list = npc_data.get(field_name)
            if data_list is not None:
                if not isinstance(data_list, list):
                    issues.append(ValidationIssue(field=field_name, issue_type="invalid_type", message=f"{entity_info}: '{field_name}' should be a list.", severity="error"))
                else:
                    known_ids = game_terms.get(term_type_key, set())
                    for i, item_id in enumerate(data_list):
                        if not isinstance(item_id, str):
                             issues.append(ValidationIssue(field=f"{field_name}[{i}]", issue_type="invalid_type", message=f"{entity_info}: ID in '{list_name}' list is not a string: {item_id}.", severity="error"))
                        elif item_id not in known_ids:
                             issues.append(ValidationIssue(field=f"{field_name}[{i}]", issue_type="invalid_reference", message=f"{entity_info}: Unknown ID '{item_id}' in '{list_name}' list.", severity="warning"))

        inventory_data = npc_data.get("inventory")
        if inventory_data is not None:
            if not isinstance(inventory_data, list):
                 issues.append(ValidationIssue(field="inventory", issue_type="invalid_type", message=f"{entity_info}: 'inventory' should be a list.", severity="error"))
            else:
                known_item_ids = game_terms.get("item_template_ids", set())
                for i, item_entry in enumerate(inventory_data):
                    if not self._check_is_dict(item_entry, f"inventory[{i}]", entity_info, issues):
                        continue
                    item_template_id = item_entry.get("item_template_id")
                    if not isinstance(item_template_id, str):
                         issues.append(ValidationIssue(field=f"inventory[{i}].item_template_id", issue_type="invalid_type", message=f"{entity_info}: Inventory item 'item_template_id' is not a string.", severity="error"))
                    elif item_template_id not in known_item_ids:
                         issues.append(ValidationIssue(field=f"inventory[{i}].item_template_id", issue_type="invalid_reference", message=f"{entity_info}: Unknown item_template_id '{item_template_id}' in inventory.", severity="warning"))
                    quantity = item_entry.get("quantity")
                    if quantity is not None and (not isinstance(quantity, int) or quantity <= 0):
                        issues.append(ValidationIssue(field=f"inventory[{i}].quantity", issue_type="invalid_value", message=f"{entity_info}: Inventory item '{item_template_id}' quantity '{quantity}' must be a positive integer.", severity="error"))


        # --- Faction Affiliation Validation ---
        faction_affiliations = npc_data.get('faction_affiliations')
        if faction_affiliations is not None:
            if not isinstance(faction_affiliations, list):
                issues.append(ValidationIssue(field="faction_affiliations", issue_type="invalid_type", message=f"{entity_info}: 'faction_affiliations' should be a list if provided.", severity="error"))
            else:
                known_faction_ids = game_terms.get("faction_ids", self.rules.faction_rules.valid_faction_ids if self.rules.faction_rules else set())
                for i, affiliation in enumerate(faction_affiliations):
                    affiliation_info = f"{entity_info}, Faction Affiliation index {i}"
                    if self._check_is_dict(affiliation, f"faction_affiliations[{i}]", affiliation_info, issues):
                        faction_id = affiliation.get('faction_id')
                        if faction_id:
                            if faction_id not in known_faction_ids:
                                issues.append(ValidationIssue(field=f"faction_affiliations[{i}].faction_id", issue_type="invalid_reference", message=f"{affiliation_info}: Invalid faction_id '{faction_id}'. Known: {known_faction_ids}", severity="warning"))
                        else: # faction_id is mandatory per affiliation object
                            issues.append(ValidationIssue(field=f"faction_affiliations[{i}].faction_id", issue_type="missing_required_field", message=f"{affiliation_info}: Missing 'faction_id'.", severity="error"))

                        rank_i18n = affiliation.get('rank_i18n')
                        if rank_i18n is not None and self._check_is_dict(rank_i18n, f"faction_affiliations[{i}].rank_i18n", affiliation_info, issues):
                             self._validate_i18n_field_completeness(rank_i18n, f"faction_affiliations[{i}].rank_i18n", affiliation_info, issues, generation_context.target_languages)

        status_str = self._calculate_entity_status(issues)
        return ValidatedEntity(
            entity_id=entity_id_str,
            entity_type="npc",
            data=npc_data, # This is the potentially auto-corrected data
            original_data=original_data_copy if status_str == "success_with_autocorrections" else None,
            validation_status=status_str,
            issues=issues
        )

    def validate_quest_block(self, quest_data: Dict[str, Any], generation_context: GenerationContext, game_terms: Dict[str, Set[str]]) -> ValidatedEntity:
        """
        Validates a single Quest data block against game rules.

        Checks i18n completeness, referential integrity of linked quests/NPCs,
        quest structure (stages, objectives), and rewards (XP, items).
        May perform auto-corrections (e.g., clamping XP reward) and records these.

        Args:
            quest_data: The Quest data dictionary to validate.
            generation_context: The context for generation, including target languages.
            game_terms: Dictionary of known game term IDs.

        Returns:
            A ValidatedEntity object.
        """
        issues: List[ValidationIssue] = []
        entity_id_str = quest_data.get('template_id', quest_data.get('id'))
        entity_info = f"Quest '{entity_id_str or 'Unknown Quest'}'"
        original_data_copy = quest_data.copy()

        # Known IDs from game_terms, with fallbacks to empty sets if a key is missing
        known_quest_ids = game_terms.get("quest_ids", set())
        known_npc_ids = game_terms.get("npc_ids", set())
        known_item_template_ids = game_terms.get("item_template_ids", set())
        known_skill_ids = game_terms.get("skill_ids", set())
        # known_location_ids = game_terms.get("location_ids", set()) # If needed for 'goto' objectives

        if not self._check_is_dict(quest_data, "Quest root", entity_info, issues):
            status_str = self._calculate_entity_status(issues)
            return ValidatedEntity(entity_id=entity_id_str, entity_type="quest", data=quest_data,
                                   validation_status=status_str, issues=issues)

        # --- I18n Field Completeness (Top-Level) ---
        top_level_i18n_fields = ['title_i18n', 'description_i18n'] # 'quest_giver_details_i18n', 'consequences_summary_i18n' also if used
        if quest_data.get("quest_giver_id") is None and "quest_giver_i18n" in quest_data : # If quest_giver_id is not provided, then quest_giver_i18n might be expected
             top_level_i18n_fields.append('quest_giver_i18n')
        if "consequences" in quest_data and isinstance(quest_data["consequences"], dict) and "description_i18n" in quest_data["consequences"]:
            # Special handling for nested i18n in consequences
            consequences_i18n = quest_data["consequences"]["description_i18n"]
            if self._check_is_dict(consequences_i18n, "consequences.description_i18n", entity_info, issues):
                 self._validate_i18n_field_completeness(consequences_i18n, "consequences.description_i18n", entity_info, issues, generation_context.target_languages)

        for field in top_level_i18n_fields:
            field_value = quest_data.get(field)
            if field_value is not None:
                if self._check_is_dict(field_value, field, entity_info, issues):
                    self._validate_i18n_field_completeness(field_value, field, entity_info, issues, generation_context.target_languages)

        # --- Suggested Level ---
        suggested_level = quest_data.get("suggested_level")
        if suggested_level is not None and (not isinstance(suggested_level, int) or suggested_level < 0):
            issues.append(ValidationIssue(field="suggested_level", issue_type="invalid_value", message=f"{entity_info}: suggested_level '{suggested_level}' must be a non-negative integer.", severity="error"))


        # --- Referential Integrity ---
        quest_giver_id = quest_data.get("quest_giver_id")
        if quest_giver_id and (not isinstance(quest_giver_id, str) or quest_giver_id not in known_npc_ids):
            issues.append(ValidationIssue(field="quest_giver_id", issue_type="invalid_reference", message=f"{entity_info}: Quest giver ID '{quest_giver_id}' invalid/not found in known NPC IDs.", severity="warning")) # Warning as it might be a new NPC

        prerequisites = quest_data.get('prerequisites') # List of quest_template_ids
        if isinstance(prerequisites, list):
            for i, p_id in enumerate(prerequisites):
                if not isinstance(p_id, str) or p_id not in known_quest_ids:
                    issues.append(ValidationIssue(field=f"prerequisites[{i}]", issue_type="invalid_reference", message=f"{entity_info}: Prerequisite quest ID '{p_id}' invalid/not found.", severity="warning"))
        elif prerequisites is not None:
             issues.append(ValidationIssue(field="prerequisites", issue_type="invalid_type", message=f"{entity_info}: 'prerequisites' must be a list of strings.", severity="error"))


        # --- Quest Structure (Stages & Objectives) ---
        stages_list = quest_data.get('stages') # Expecting 'stages' now, not 'stages_i18n' at top level of quest
        if not isinstance(stages_list, list) or not stages_list:
            issues.append(ValidationIssue(field="stages", issue_type="missing_or_invalid_type", message=f"{entity_info}: Quest 'stages' must be a non-empty list.", severity="error"))
        else:
            for s_idx, stage_data in enumerate(stages_list):
                stage_info = f"{entity_info}, Stage {s_idx} ('{stage_data.get('stage_id', 'Unknown Stage')}')"
                if not self._check_is_dict(stage_data, f"stages[{s_idx}]", stage_info, issues):
                    continue

                # I18n for stage fields
                stage_i18n_fields = ['title_i18n', 'description_i18n', 'alternative_solutions_i18n']
                for field in stage_i18n_fields:
                    f_val = stage_data.get(field)
                    if f_val is not None and self._check_is_dict(f_val, f"stages[{s_idx}].{field}", stage_info, issues):
                        self._validate_i18n_field_completeness(f_val, f"stages[{s_idx}].{field}", stage_info, issues, generation_context.target_languages)

                objectives_list = stage_data.get('objectives')
                if not isinstance(objectives_list, list) or not objectives_list:
                    issues.append(ValidationIssue(field=f"stages[{s_idx}].objectives", issue_type="missing_or_invalid_type", message=f"{stage_info}: Objectives must be a non-empty list.", severity="error"))
                else:
                    for o_idx, obj_data in enumerate(objectives_list):
                        obj_info = f"{stage_info}, Objective {o_idx} ('{obj_data.get('objective_id', 'Unknown Obj')}')"
                        if not self._check_is_dict(obj_data, f"stages[{s_idx}].objectives[{o_idx}]", obj_info, issues):
                            continue

                        obj_desc_i18n = obj_data.get('description_i18n')
                        if obj_desc_i18n is None or not self._check_is_dict(obj_desc_i18n, f"stages[{s_idx}].objectives[{o_idx}].description_i18n", obj_info, issues):
                             issues.append(ValidationIssue(field=f"stages[{s_idx}].objectives[{o_idx}].description_i18n", issue_type="missing_required_field", message=f"{obj_info}: Objective 'description_i18n' is missing or invalid.", severity="error"))
                        else:
                            self._validate_i18n_field_completeness(obj_desc_i18n, f"stages[{s_idx}].objectives[{o_idx}].description_i18n", obj_info, issues, generation_context.target_languages)

                        obj_type = obj_data.get("type")
                        valid_obj_types = self.rules.quest_rules.valid_objective_types if self.rules.quest_rules else []
                        if not isinstance(obj_type, str) or (valid_obj_types and obj_type not in valid_obj_types) :
                            issues.append(ValidationIssue(field=f"stages[{s_idx}].objectives[{o_idx}].type", issue_type="invalid_value", message=f"{obj_info}: Objective type '{obj_type}' is invalid or not supported. Valid: {valid_obj_types}", severity="error"))

                        target_id = obj_data.get("target_id")
                        if target_id is not None: # Optional field
                            if not isinstance(target_id, str):
                                issues.append(ValidationIssue(field=f"stages[{s_idx}].objectives[{o_idx}].target_id", issue_type="invalid_type", message=f"{obj_info}: Objective target_id '{target_id}' must be a string.", severity="error"))
                            # Further validation of target_id based on obj_type might be needed (e.g. if type is "kill", target_id should be an NPC id)
                            # For now, just ensuring it's a string if present. Example:
                            # if obj_type == "kill" and target_id not in known_npc_ids: ...

                        skill_check = obj_data.get("skill_check")
                        if skill_check is not None and self._check_is_dict(skill_check, f"stages[{s_idx}].objectives[{o_idx}].skill_check", obj_info, issues):
                            skill_id = skill_check.get("skill_id")
                            if not isinstance(skill_id, str) or skill_id not in known_skill_ids:
                                issues.append(ValidationIssue(field=f"stages[{s_idx}].objectives[{o_idx}].skill_check.skill_id", issue_type="invalid_reference", message=f"{obj_info}: Skill check skill_id '{skill_id}' is invalid.", severity="error"))
                            dc = skill_check.get("dc")
                            if not isinstance(dc, int) or dc <= 0:
                                issues.append(ValidationIssue(field=f"stages[{s_idx}].objectives[{o_idx}].skill_check.dc", issue_type="invalid_value", message=f"{obj_info}: Skill check DC '{dc}' must be a positive integer.", severity="error"))
                            # I18n for skill_check.description_i18n
                            sc_desc_i18n = skill_check.get("description_i18n")
                            if sc_desc_i18n is not None and self._check_is_dict(sc_desc_i18n, f"stages[{s_idx}].objectives[{o_idx}].skill_check.description_i18n", obj_info, issues):
                                self._validate_i18n_field_completeness(sc_desc_i18n, f"stages[{s_idx}].objectives[{o_idx}].skill_check.description_i18n", obj_info, issues, generation_context.target_languages)


        # --- Reward Validation ---
        rewards_data = quest_data.get('rewards')
        if self._check_is_dict(rewards_data, 'rewards', entity_info, issues):
            rewards_data = cast(Dict[str, Any], rewards_data)
            xp = rewards_data.get('experience_points') # Field name from prompt
            if xp is not None:
                if not isinstance(xp, int) or xp < 0:
                    issues.append(ValidationIssue(field="rewards.experience_points", issue_type="invalid_value", message=f"{entity_info}: XP reward '{xp}' must be non-negative int.", severity="error"))
                elif self.rules.quest_rules and self.rules.quest_rules.reward_rules and self.rules.quest_rules.reward_rules.xp_reward_range:
                    xp_range = self.rules.quest_rules.reward_rules.xp_reward_range # StatRange
                    if not (xp_range.min <= xp <= xp_range.max):
                        original_xp = xp
                        corrected_xp = max(xp_range.min, min(original_xp, xp_range.max))
                        rewards_data['experience_points'] = corrected_xp # Auto-correction
                        issues.append(ValidationIssue(
                            field="rewards.experience_points", issue_type="auto_correction",
                            message=f"AUTO-CORRECT: {entity_info}: XP {original_xp} out of range ({xp_range.min}-{xp_range.max}). Clamped to {corrected_xp}.",
                            severity="warning", recommended_fix=f"Set XP between {xp_range.min} and {xp_range.max}."
                        ))

            item_rewards = rewards_data.get('items') # List of {"item_template_id": "...", "quantity": ...}
            if isinstance(item_rewards, list):
                for i, item_entry in enumerate(item_rewards):
                    item_info_ctx = f"{entity_info}, Item Reward {i}"
                    if not self._check_is_dict(item_entry, f"rewards.items[{i}]", item_info_ctx, issues):
                        continue
                    template_id_to_check = item_entry.get('item_template_id')
                    if not isinstance(template_id_to_check, str):
                        issues.append(ValidationIssue(field=f"rewards.items[{i}].item_template_id", issue_type="invalid_type", message=f"{item_info_ctx}: 'item_template_id' is missing or not a string.", severity="error"))
                    elif template_id_to_check not in known_item_template_ids:
                        issues.append(ValidationIssue(field=f"rewards.items[{i}].item_template_id", issue_type="invalid_reference", message=f"{item_info_ctx}: Item template_id '{template_id_to_check}' not found.", severity="warning"))

                    quantity = item_entry.get('quantity')
                    if quantity is not None and (not isinstance(quantity, int) or quantity <=0):
                        issues.append(ValidationIssue(field=f"rewards.items[{i}].quantity", issue_type="invalid_value", message=f"{item_info_ctx}: Quantity '{quantity}' invalid for item '{template_id_to_check}'. Must be positive integer.", severity="error"))
            elif item_rewards is not None:
                 issues.append(ValidationIssue(field="rewards.items", issue_type="invalid_type", message=f"{entity_info}: 'items' in rewards must be a list.", severity="error"))

        status_str = self._calculate_entity_status(issues)
        return ValidatedEntity(
            entity_id=entity_id_str, entity_type="quest", data=quest_data,
            original_data=original_data_copy if status_str == "success_with_autocorrections" else None,
            validation_status=status_str, issues=issues
        )

    def validate_item_block(self, item_data: Dict[str, Any], generation_context: GenerationContext, game_terms: Dict[str, Set[str]]) -> ValidatedEntity:
        """
        Validates a single Item data block against game rules.

        Checks i18n completeness, item type, price (with clamping), and presence of
        some type-specific properties.

        Args:
            item_data: The Item data dictionary to validate.
            generation_context: Context for generation, including target languages.
            game_terms: Dictionary of known game term IDs.

        Returns:
            A ValidatedEntity object.
        """
        issues: List[ValidationIssue] = []
        # Items typically use 'template_id' as their primary non-instance identifier
        entity_id_str = item_data.get('template_id', item_data.get('id'))
        entity_info = f"Item '{entity_id_str or 'Unknown Item'}'"
        original_data_copy = item_data.copy()

        known_item_template_ids = game_terms.get("item_template_ids", set())
        # known_stat_ids = game_terms.get("stat_ids", set()) # For requirements if any

        if not self._check_is_dict(item_data, "Item root", entity_info, issues):
            status_str = self._calculate_entity_status(issues)
            return ValidatedEntity(entity_id=entity_id_str, entity_type="item", data=item_data,
                                   validation_status=status_str, issues=issues)

        # --- Template ID Validation (Crucial for items) ---
        template_id = item_data.get('template_id')
        if not template_id:
            issues.append(ValidationIssue(field="template_id", issue_type="missing_required_field", message=f"{entity_info}: Missing 'template_id'.", severity="error"))
        elif not isinstance(template_id, str):
            issues.append(ValidationIssue(field="template_id", issue_type="invalid_type", message=f"{entity_info}: 'template_id' must be a string.", severity="error"))
        # Not checking against known_item_template_ids here if we are defining a *new* item template.
        # If this validator is used for *instances* of items, then this check would be:
        # elif template_id not in known_item_template_ids:
        #     issues.append(ValidationIssue(field="template_id", issue_type="invalid_reference", message=f"{entity_info}: Item template_id '{template_id}' not in known template IDs.", severity="error"))


        # --- I18n Field Completeness ---
        item_i18n_fields = ['name_i18n', 'description_i18n'] # 'properties_i18n' potentially if it contains descriptions
        for field in item_i18n_fields:
            f_val = item_data.get(field)
            if f_val is not None and self._check_is_dict(f_val, field, entity_info, issues):
                self._validate_i18n_field_completeness(f_val, field, entity_info, issues, generation_context.target_languages)

        properties_i18n = item_data.get("properties_i18n")
        if self._check_is_dict(properties_i18n, "properties_i18n", entity_info, issues):
            for prop_key, prop_value in properties_i18n.items():
                if isinstance(prop_value, dict) and any(lang in prop_value for lang in generation_context.target_languages): # It's an i18n dict itself
                     self._validate_i18n_field_completeness(prop_value, f"properties_i18n.{prop_key}", entity_info, issues, generation_context.target_languages)
                # Numerical or simple string properties don't need this i18n check


        # --- Item Type and Rarity Validation ---
        item_type = item_data.get('item_type') # Changed from 'type' to 'item_type' to match prompt plan
        item_type_validated = False
        if item_type:
            if isinstance(item_type, str):
                valid_item_types = self.rules.item_rules.valid_item_types if self.rules.item_rules else []
                if valid_item_types and item_type not in valid_item_types:
                    issues.append(ValidationIssue(field="item_type", issue_type="invalid_value", message=f"{entity_info}: Invalid item type: '{item_type}'. Valid: {valid_item_types}", severity="error"))
                elif not valid_item_types:
                     issues.append(ValidationIssue(field="item_type", issue_type="missing_rule_definition", message=f"{entity_info}: No valid_item_types rule defined. Cannot validate '{item_type}'.", severity="info"))
                else:
                    item_type_validated = True
            else:
                issues.append(ValidationIssue(field="item_type", issue_type="invalid_type", message=f"{entity_info}: Item 'item_type' field must be a string, got {type(item_type).__name__}.", severity="error"))

        item_rarity = item_data.get("rarity")
        if item_rarity is not None: # Rarity is optional
            if not isinstance(item_rarity, str):
                 issues.append(ValidationIssue(field="rarity", issue_type="invalid_type", message=f"{entity_info}: Item 'rarity' must be a string.", severity="error"))
            else:
                valid_rarities = self.rules.item_rules.valid_rarities if self.rules.item_rules else []
                if valid_rarities and item_rarity not in valid_rarities:
                     issues.append(ValidationIssue(field="rarity", issue_type="invalid_value", message=f"{entity_info}: Invalid item rarity: '{item_rarity}'. Valid: {valid_rarities}", severity="warning"))


        # --- Price Validation (Value) ---
        price_value = item_data.get('value') # 'value' as per prompt plan
        if price_value is not None:
            if not isinstance(price_value, (int, float)) or price_value < 0:
                issues.append(ValidationIssue(field="value", issue_type="invalid_value", message=f"{entity_info}: Value '{price_value}' must be a non-negative number.", severity="error"))
            else:
                if self.rules.item_rules and self.rules.item_rules.price_ranges_by_type and item_type_validated:
                    price_cat_rules = self.rules.item_rules.price_ranges_by_type.get(item_type) # ItemPriceCategory
                    if price_cat_rules and price_cat_rules.prices:
                        # Using rarity if available, otherwise a default or generic price check might be needed
                        rarity_for_price = item_rarity if item_rarity and isinstance(item_rarity, str) else "common" # Default if no rarity
                        price_detail_rules = price_cat_rules.prices.get(rarity_for_price) # ItemPriceDetail
                        if price_detail_rules:
                            min_price, max_price = price_detail_rules.min, price_detail_rules.max
                            if not (min_price <= price_value <= max_price):
                                original_price = price_value
                                clamped_price = max(min_price, min(original_price, max_price))
                                item_data['value'] = clamped_price # Auto-correction
                                issues.append(ValidationIssue(
                                    field="value", issue_type="auto_correction",
                                    message=f"AUTO-CORRECT: {entity_info}: Value {original_price} for type '{item_type}' rarity '{rarity_for_price}' out of range ({min_price}-{max_price}). Clamped to {clamped_price}.",
                                    severity="warning", recommended_fix=f"Set value between {min_price} and {max_price}."
                                ))
                        # else: No price rules for this specific rarity/type combo.
                    # else: No price categories defined for this item type.
                # else: Cannot do price range validation based on type/rarity.

        # --- Stackable ---
        is_stackable = item_data.get("stackable")
        if is_stackable is not None and not isinstance(is_stackable, bool):
            issues.append(ValidationIssue(field="stackable", issue_type="invalid_type", message=f"{entity_info}: 'stackable' must be a boolean.", severity="error"))

        # --- General Property Presence (Example soft checks based on type) ---
        # These would need more detailed rules in GameRules for robust validation
        if item_type_validated:
            if item_type == 'weapon' and 'damage' not in item_data.get("properties_i18n", {}):
                 issues.append(ValidationIssue(field="properties_i18n.damage", issue_type="missing_recommended_field", message=f"{entity_info}: Weapon type item is missing 'damage' in properties_i18n.", severity="warning"))
            if item_type == 'potion' and not any(k.startswith("effect") for k in item_data.get("properties_i18n", {})):
                 issues.append(ValidationIssue(field="properties_i18n", issue_type="missing_recommended_field", message=f"{entity_info}: Potion type item is missing an 'effect' in properties_i18n.", severity="warning"))


        status_str = self._calculate_entity_status(issues)
        return ValidatedEntity(
            entity_id=entity_id_str, entity_type="item", data=item_data,
            original_data=original_data_copy if status_str == "success_with_autocorrections" else None,
            validation_status=status_str, issues=issues
        )

    def validate_ai_response(self, ai_json_string: str, expected_structure: str, generation_context: GenerationContext) -> ParsedAiData:
        """
        Parses an AI-generated JSON string and validates its content based on the expected structure and game rules.

        Args:
            ai_json_string: The JSON string received from the AI.
            expected_structure: A string indicating the expected top-level structure of the JSON.
                Valid values: "single_npc", "list_of_npcs", "single_quest", "list_of_quests",
                              "single_item", "list_of_items".
            generation_context: The context used for generation, containing game terms, target_languages, etc.
        Returns:
            A ParsedAiData object summarizing the validation outcome.
        """
        validated_entities: List[ValidatedEntity] = []
        global_issues: List[ValidationIssue] = [] # Using ValidationIssue for global errors too

        try:
            parsed_data = json.loads(ai_json_string)
        except json.JSONDecodeError as e:
            global_issues.append(ValidationIssue(
                field="root", issue_type="json_decode_error",
                message=f"Invalid JSON format: {e}", severity="error"
            ))
            # No entities to process, return immediately with global error
            return ParsedAiData(
                overall_status="error", entities=[],
                global_errors=[f"{issue.field}: {issue.message}" for issue in global_issues], # Convert to string list
                raw_ai_output=ai_json_string
            )

        validator_func: Optional[ValidatorFuncType] = None
        is_list = False
        entity_type_for_placeholder = "unknown" # For malformed list items

        if expected_structure == "list_of_npcs": validator_func = self.validate_npc_block; is_list = True; entity_type_for_placeholder = "npc"
        elif expected_structure == "single_npc": validator_func = self.validate_npc_block; entity_type_for_placeholder = "npc"
        elif expected_structure == "list_of_quests": validator_func = self.validate_quest_block; is_list = True; entity_type_for_placeholder = "quest"
        elif expected_structure == "single_quest": validator_func = self.validate_quest_block; entity_type_for_placeholder = "quest"
        elif expected_structure == "list_of_items": validator_func = self.validate_item_block; is_list = True; entity_type_for_placeholder = "item"
        elif expected_structure == "single_item": validator_func = self.validate_item_block; entity_type_for_placeholder = "item"
        else:
            global_issues.append(ValidationIssue(
                field="expected_structure", issue_type="unknown_value",
                message=f"Unknown expected_structure: '{expected_structure}'", severity="error"
            ))
            return ParsedAiData(
                overall_status="error", entities=[],
                global_errors=[f"{issue.field}: {issue.message}" for issue in global_issues],
                raw_ai_output=ai_json_string
            )

        # Prepare game_terms from generation_context for block validators
        game_terms_from_context: Dict[str, Set[str]] = {
           "stat_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "stat"},
           "skill_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "skill"},
           "ability_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "ability"},
           "spell_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "spell"},
           "npc_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "npc"},
           "item_template_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "item_template"},
           "location_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "location"},
           "faction_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "faction"}, # Assuming factions are in terms
           "quest_ids": {term.id for term in generation_context.game_terms_dictionary if term.term_type == "quest"},
           # Add other term types like 'archetype_ids' if they are defined in GameTerm.term_type
        }
        # Example for archetypes if they are part of game_terms_dictionary
        game_terms_from_context["archetype_ids"] = {term.id for term in generation_context.game_terms_dictionary if term.term_type == "archetype"}


        if is_list:
            if not isinstance(parsed_data, list):
                global_issues.append(ValidationIssue(
                    field="root", issue_type="invalid_type",
                    message=f"Expected a list for '{expected_structure}', but got {type(parsed_data).__name__}.",
                    severity="error"
                ))
            else:
                for i, item_data_uncast in enumerate(parsed_data):
                    if not isinstance(item_data_uncast, dict):
                        malformed_issue = ValidationIssue(
                            field=f"list_item[{i}]", issue_type="invalid_type",
                            message=f"Item at index {i} for '{expected_structure}' is not a dictionary.",
                            severity="error"
                        )
                        validated_entities.append(ValidatedEntity(
                            entity_id=None, entity_type=entity_type_for_placeholder, data={"raw_data": item_data_uncast},
                            validation_status="requires_moderation", issues=[malformed_issue]
                        ))
                        continue
                    if validator_func:
                        validated_entity_obj = validator_func(
                            cast(Dict[str, Any], item_data_uncast),
                            generation_context=generation_context,
                            game_terms=game_terms_from_context
                        )
                        validated_entities.append(validated_entity_obj)
        else: # Expected a single dictionary entity
            if not isinstance(parsed_data, dict):
                global_issues.append(ValidationIssue(
                    field="root", issue_type="invalid_type",
                    message=f"Expected a dictionary for '{expected_structure}', but got {type(parsed_data).__name__}.",
                    severity="error"
                ))
            else:
                if validator_func:
                    validated_entity_obj = validator_func(
                        cast(Dict[str, Any], parsed_data),
                        generation_context=generation_context,
                        game_terms=game_terms_from_context
                    )
                    validated_entities.append(validated_entity_obj)

        # Determine overall_status based on global_issues and individual entity statuses
        final_overall_status = "success"
        if any(gi.severity == "error" for gi in global_issues):
            final_overall_status = "error"
        elif any(entity.validation_status == "requires_moderation" for entity in validated_entities):
            final_overall_status = "requires_moderation"
        elif any(entity.validation_status == "success_with_autocorrections" for entity in validated_entities):
            final_overall_status = "success_with_autocorrections"
        # If global_issues contains only warnings/info, and entities are clean, it's still success.
        # Could add a "success_with_global_warnings" status if needed.

        return ParsedAiData(
            overall_status=final_overall_status,
            entities=validated_entities,
            global_errors=[f"GLOBAL ({issue.severity.upper()}) {issue.field}: {issue.message}" for issue in global_issues], # Simplified representation
            raw_ai_output=ai_json_string
        )
