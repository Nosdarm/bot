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

from .rules_schema import GameRules # Implicitly import others like RoleStatRules
# Game models are used for type hinting and as a structural reference,
# though the validator primarily works with dictionaries from AI JSON.
from bot.game.models.npc import NPC
from bot.game.models.quest import Quest
from bot.game.models.item import Item

# Define a type alias for the block validator result for clarity
BlockValidationResult = Dict[str, Any]

# Type alias for the specific signature of block validator functions
ValidatorFuncType = Callable[[Dict[str, Any], Optional[Set[str]], Optional[Set[str]], Optional[Set[str]]], BlockValidationResult]

class AIResponseValidator:
    """
    Validates AI-generated JSON content against a set of game rules.

    The validator checks for structural correctness, adherence to defined value ranges,
    validity of types/IDs, i18n content completeness, and can perform auto-corrections.
    It reports errors, notifications (for auto-corrections or warnings), and flags
    content that requires manual moderation.
    """
    def __init__(self, rules: GameRules, required_languages: List[str]):
        """
        Initializes the AIResponseValidator.

        Args:
            rules: A GameRules object containing all the rule definitions (loaded from config).
            required_languages: A list of language codes (e.g., ['en', 'ru']) for which
                                i18n content must be provided and complete.
        """
        self.rules = rules
        self.required_languages = required_languages
        if not self.required_languages:
            # Default to 'en' if no languages are specified to prevent issues during validation.
            self.required_languages = ['en']

    def _check_is_dict(self, data: Any, field_name: str, entity_id_info: str, errors: List[str]) -> bool:
        """
        Helper to check if the provided data is a dictionary. Appends an error if not.

        Args:
            data: The data to check.
            field_name: The name of the field being checked (for error messages).
            entity_id_info: Contextual information about the entity (for error messages).
            errors: The list to append errors to.

        Returns:
            True if data is a dictionary, False otherwise.
        """
        if not isinstance(data, dict):
            errors.append(f"{entity_id_info}: Field '{field_name}' must be a dictionary, got {type(data).__name__}.")
            return False
        return True

    def _validate_i18n_field_completeness(self, i18n_dict: Dict[str, str], field_name: str, entity_id_info: str) -> List[str]:
        """
        Validates that an i18n dictionary (field_name_i18n) has non-empty string translations
        for all languages specified in `self.required_languages`.

        Args:
            i18n_dict: The dictionary of translations (e.g., {"en": "Hello", "ru": "Привет"}).
            field_name: The name of the i18n field (e.g., "name_i18n").
            entity_id_info: Contextual information (e.g., "NPC 'npc123'") for error messages.

        Returns:
            A list of error messages detailing missing or empty translations.
        """
        validation_errors: List[str] = []
        for lang_code in self.required_languages:
            if lang_code not in i18n_dict:
                validation_errors.append(f"{entity_id_info}: Field '{field_name}' is missing translation for language '{lang_code}'.")
            elif not isinstance(i18n_dict[lang_code], str) or not i18n_dict[lang_code].strip():
                validation_errors.append(f"{entity_id_info}: Field '{field_name}' has empty or non-string content for language '{lang_code}'.")
        return validation_errors

    def _get_canonical_role_key(self, npc_data: Dict[str, Any], entity_info: str, errors: List[str], notifications: List[str]) -> Optional[str]:
        """
        Determines a canonical role key string for an NPC from its data.
        Priority:
        1. `npc_data['archetype']` (if string and non-empty)
        2. `npc_data['role']` (if string and non-empty)
        3. `npc_data['role_i18n']` (using 'en' first, then first available non-empty language).
        The role key is converted to lowercase.

        Args:
            npc_data: The NPC data dictionary.
            entity_info: Contextual information for logging/notifications.
            errors: List to append errors to if role cannot be determined.
            notifications: List to append informational messages about role source.

        Returns:
            The canonical role key as a lowercase string, or None if not determinable.
        """
        if 'archetype' in npc_data and isinstance(npc_data['archetype'], str) and npc_data['archetype'].strip():
            notifications.append(f"{entity_info}: Using 'archetype' field for role: '{npc_data['archetype']}'.")
            return npc_data['archetype'].strip().lower()
        if 'role' in npc_data and isinstance(npc_data['role'], str) and npc_data['role'].strip():
            notifications.append(f"{entity_info}: Using 'role' field for role: '{npc_data['role']}'.")
            return npc_data['role'].strip().lower()

        role_i18n = npc_data.get('role_i18n')
        if isinstance(role_i18n, dict) and role_i18n:
            if 'en' in role_i18n and isinstance(role_i18n['en'], str) and role_i18n['en'].strip():
                notifications.append(f"{entity_info}: Using 'en' from 'role_i18n' for role: '{role_i18n['en']}'.")
                return role_i18n['en'].strip().lower()
            for lang, value in role_i18n.items(): # Fallback to first available language
                if isinstance(value, str) and value.strip():
                    notifications.append(f"{entity_info}: Using '{lang}' from 'role_i18n' for role: '{value}'.")
                    return value.strip().lower()
            errors.append(f"{entity_info}: 'role_i18n' is present but contains no valid, non-empty role names.")
            return None

        errors.append(f"{entity_info}: Could not determine NPC role from 'archetype', 'role', or 'role_i18n' fields for stat validation.")
        return None

    def _determine_status_and_moderation(self, errors: List[str], notifications: List[str]) -> tuple[str, bool]:
        """
        Determines the validation status and moderation requirement based on errors and notifications.

        Args:
            errors: A list of error messages.
            notifications: A list of notification messages.

        Returns:
            A tuple: (status_string, requires_moderation_bool).
            Status can be "requires_moderation", "success_with_autocorrections", or "success".
        """
        requires_moderation = bool(errors) # Any error means moderation is required
        status = "requires_moderation" if errors else "success"
        if not errors and any("AUTO-CORRECT:" in n for n in notifications):
            status = "success_with_autocorrections"
        return status, requires_moderation

    def validate_npc_block(self, npc_data: Dict[str, Any],
                           existing_quest_ids: Optional[Set[str]] = None,
                           existing_npc_ids: Optional[Set[str]] = None,
                           existing_item_template_ids: Optional[Set[str]] = None) -> BlockValidationResult:
        """
        Validates a single NPC data block against game rules.

        Checks i18n completeness, stats, skills, faction affiliations, etc.
        May perform auto-corrections (e.g., clamping stats/skills) and records these
        in notifications.

        Args:
            npc_data: The NPC data dictionary to validate.
            existing_quest_ids: Optional set of existing quest IDs for referential integrity (not used by NPC block directly yet).
            existing_npc_ids: Optional set of existing NPC IDs for referential integrity (not used by NPC block directly yet).
            existing_item_template_ids: Optional set of existing item template IDs (not used by NPC block directly yet).


        Returns:
            A BlockValidationResult dictionary with keys: 'entity_id', 'type', 'status',
            'errors', 'notifications', 'requires_moderation', 'validated_data'.
        """
        errors: List[str] = []
        notifications: List[str] = []
        entity_id_str = npc_data.get('id', npc_data.get('template_id')) # Prefer 'id', fallback to 'template_id'
        entity_info = f"NPC '{entity_id_str or 'Unknown NPC'}'" # Used in error/notification messages

        if not self._check_is_dict(npc_data, "NPC root", entity_info, errors):
            status, req_mod = self._determine_status_and_moderation(errors, notifications)
            return {
                "entity_id": entity_id_str, "type": "npc", "status": status,
                "errors": errors, "notifications": notifications,
                "requires_moderation": req_mod, "validated_data": npc_data
            }

        # --- I18n Field Completeness ---
        i18n_fields_to_check = [
            'name_i18n', 'backstory_i18n', 'role_i18n',
            'personality_i18n', 'motivation_i18n',
            'dialogue_hints_i18n', 'visual_description_i18n'
        ]
        for field in i18n_fields_to_check:
            field_value = npc_data.get(field)
            if field_value is not None: # Field is present
                if self._check_is_dict(field_value, field, entity_info, errors):
                    errors.extend(self._validate_i18n_field_completeness(field_value, field, entity_info))
            # else: # If a field is mandatory, add error. Current design: i18n completeness check handles missing translations.
            #    errors.append(f"{entity_info}: Missing required i18n field: '{field}'.")


        # --- Role Determination ---
        role_key = self._get_canonical_role_key(npc_data, entity_info, errors, notifications)

        # --- Stat Validation ---
        stats_data = npc_data.get('stats')
        if self._check_is_dict(stats_data, 'stats', entity_info, errors): # Will add error to `errors` list if not dict
            stats_data = cast(Dict[str, Any], stats_data) # Ensure type checker knows it's a dict
            valid_stats = self.rules.character_stats_rules.valid_stats
            for stat_key, stat_value in list(stats_data.items()): # Use list() for safe iteration if modifying
                if stat_key not in valid_stats:
                    errors.append(f"{entity_info}: Invalid stat name: '{stat_key}'.")
                    continue
                if not isinstance(stat_value, (int, float)):
                    errors.append(f"{entity_info}: Stat '{stat_key}' value '{stat_value}' is not a number.")
                    continue

                # Role-based stat value validation
                if role_key and self.rules.character_stats_rules.stat_ranges_by_role:
                    role_specific_rules = self.rules.character_stats_rules.stat_ranges_by_role.get(role_key)
                    if role_specific_rules and role_specific_rules.stats:
                        stat_range_model = role_specific_rules.stats.get(stat_key)
                        if stat_range_model:
                            min_val, max_val = stat_range_model.min, stat_range_model.max
                            if not (min_val <= stat_value <= max_val):
                                original_value = stat_value
                                corrected_value = max(min_val, min(original_value, max_val))
                                stats_data[stat_key] = corrected_value # Clamp
                                msg = (f"{entity_info}: Stat '{stat_key}' value {original_value} for role '{role_key}' "
                                       f"was out of range ({min_val}-{max_val}). Clamped to {corrected_value}.")
                                errors.append(msg)
                                notifications.append(f"AUTO-CORRECT: {msg}")
                        # else: No specific range for this valid stat under this role. Could be a warning or allowed.
                    elif role_key: # role_key is valid, but no rules for it in stat_ranges_by_role
                         notifications.append(f"{entity_info}: No stat range rules for role '{role_key}'. Skipping role-based value check for '{stat_key}'.")
                # else if no role_key, can't do role-based validation. Could have a generic range check here if defined in rules.

        # --- Skill Validation ---
        skills_data = npc_data.get('skills')
        if self._check_is_dict(skills_data, 'skills', entity_info, errors):
            skills_data = cast(Dict[str, Any], skills_data)
            valid_skills = self.rules.skill_rules.valid_skills
            skill_range = self.rules.skill_rules.skill_value_ranges # This is a StatRange object
            min_skill, max_skill = skill_range.min, skill_range.max

            for skill_key, skill_value in list(skills_data.items()):
                if skill_key not in valid_skills:
                    errors.append(f"{entity_info}: Invalid skill name: '{skill_key}'.")
                    continue
                if not isinstance(skill_value, (int, float)):
                    errors.append(f"{entity_info}: Skill '{skill_key}' value '{skill_value}' is not a number.")
                    continue

                if not (min_skill <= skill_value <= max_skill):
                    original_value = skill_value
                    corrected_value = max(min_skill, min(original_value, max_skill))
                    skills_data[skill_key] = corrected_value # Clamp
                    msg = (f"{entity_info}: Skill '{skill_key}' value {original_value} "
                           f"was out of range ({min_skill}-{max_skill}). Clamped to {corrected_value}.")
                    errors.append(msg)
                    notifications.append(f"AUTO-CORRECT: {msg}")

        # --- Faction Affiliation Validation ---
        faction_affiliations = npc_data.get('faction_affiliations')
        if faction_affiliations is not None: # Field is optional
            if isinstance(faction_affiliations, list):
                if self.rules.faction_rules and self.rules.faction_rules.valid_faction_ids:
                    valid_faction_ids = self.rules.faction_rules.valid_faction_ids
                    for i, affiliation in enumerate(faction_affiliations):
                        affiliation_info = f"{entity_info}, Faction Affiliation index {i}"
                        if self._check_is_dict(affiliation, f"faction_affiliations[{i}]", entity_info, errors):
                            faction_id = affiliation.get('faction_id')
                            if faction_id:
                                if faction_id not in valid_faction_ids:
                                    errors.append(f"{affiliation_info}: Invalid faction_id '{faction_id}'.")
                            else:
                                errors.append(f"{affiliation_info}: Missing 'faction_id'.") # faction_id is mandatory per affiliation

                            rank_i18n = affiliation.get('rank_i18n') # rank_i18n is optional within an affiliation
                            if rank_i18n is not None and self._check_is_dict(rank_i18n, 'rank_i18n', affiliation_info, errors):
                                 errors.extend(self._validate_i18n_field_completeness(rank_i18n, 'rank_i18n', affiliation_info))
                elif self.rules.faction_rules is None: # Faction rules are defined but no valid_faction_ids list.
                     notifications.append(f"{entity_info}: Faction rules not defined or no valid_faction_ids specified. Skipping faction ID validation.")
            else:
                errors.append(f"{entity_info}: 'faction_affiliations' should be a list if provided.")

        final_status, requires_moderation_flag = self._determine_status_and_moderation(errors, notifications)
        return {
            "entity_id": entity_id_str, "type": "npc", "status": final_status,
            "errors": errors, "notifications": notifications,
            "requires_moderation": requires_moderation_flag, "validated_data": npc_data
        }

    def validate_quest_block(self, quest_data: Dict[str, Any],
                             existing_quest_ids: Optional[Set[str]] = None,
                             existing_npc_ids: Optional[Set[str]] = None,
                             existing_item_template_ids: Optional[Set[str]] = None) -> BlockValidationResult:
        """
        Validates a single Quest data block against game rules.

        Checks i18n completeness, referential integrity of linked quests/NPCs,
        quest structure (stages, objectives), and rewards (XP, items).
        May perform auto-corrections (e.g., clamping XP reward) and records these.

        Args:
            quest_data: The Quest data dictionary to validate.
            existing_quest_ids: Set of existing quest IDs for validating prerequisites/connections.
            existing_npc_ids: Set of existing NPC IDs for validating NPC involvement.
            existing_item_template_ids: Set of existing item template IDs for validating item rewards.

        Returns:
            A BlockValidationResult dictionary.
        """
        errors: List[str] = []
        notifications: List[str] = []
        entity_id_str = quest_data.get('id', quest_data.get('template_id'))
        entity_info = f"Quest '{entity_id_str or 'Unknown Quest'}'"

        # Initialize default sets if None for easier use
        _existing_quest_ids = existing_quest_ids if existing_quest_ids is not None else set()
        _existing_npc_ids = existing_npc_ids if existing_npc_ids is not None else set()
        _existing_item_template_ids = existing_item_template_ids if existing_item_template_ids is not None else set()

        if not self._check_is_dict(quest_data, "Quest root", entity_info, errors):
            status, req_mod = self._determine_status_and_moderation(errors, notifications)
            return {"entity_id": entity_id_str, "type": "quest", "status": status, "errors": errors,
                    "notifications": notifications, "requires_moderation": req_mod, "validated_data": quest_data}

        # --- I18n Field Completeness (Top-Level) ---
        top_level_i18n_fields = ['name_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n']
        for field in top_level_i18n_fields:
            field_value = quest_data.get(field)
            if field_value is not None: # Assuming these fields are optional or their absence is handled by schema
                if self._check_is_dict(field_value, field, entity_info, errors):
                    errors.extend(self._validate_i18n_field_completeness(field_value, field, entity_info))

        # --- Referential Integrity ---
        prerequisites = quest_data.get('prerequisites')
        if isinstance(prerequisites, list):
            for p_id in prerequisites:
                if not isinstance(p_id, str) or p_id not in _existing_quest_ids:
                    errors.append(f"{entity_info}: Prerequisite quest ID '{p_id}' invalid/not found.")

        connections = quest_data.get('connections') # e.g., {"next_quest": ["q2"], "related_lore": ["lore_q3"]}
        if isinstance(connections, dict):
            for c_type, c_ids in connections.items():
                if isinstance(c_ids, list):
                    for c_id in c_ids:
                        if not isinstance(c_id, str) or c_id not in _existing_quest_ids:
                            errors.append(f"{entity_info}: Connected quest ID '{c_id}' ({c_type}) invalid/not found.")
                else:
                    errors.append(f"{entity_info}: Connections for '{c_type}' must be a list.")

        npc_involvement = quest_data.get('npc_involvement') # e.g., {"quest_giver": "npc1", "target": ["npc2", "npc3"]}
        if isinstance(npc_involvement, dict):
            for role, npc_id_val in npc_involvement.items():
                npc_ids_to_check = [npc_id_val] if isinstance(npc_id_val, str) else npc_id_val if isinstance(npc_id_val, list) else []
                if not npc_ids_to_check and not isinstance(npc_id_val, (str, list)): # Invalid type for NPC ID(s)
                     errors.append(f"{entity_info}: NPC ID for role '{role}' invalid type: {type(npc_id_val).__name__}.")
                     continue
                for npc_id_item in npc_ids_to_check:
                    if not isinstance(npc_id_item, str) or npc_id_item not in _existing_npc_ids:
                        errors.append(f"{entity_info}: Involved NPC ID '{npc_id_item}' ({role}) invalid/not found.")

        # --- Quest Structure (Stages & Objectives) ---
        stages_field = quest_data.get('stages_i18n', quest_data.get('stages')) # Allow 'stages' as non-i18n fallback
        if not self._check_is_dict(stages_field, 'stages_i18n/stages', entity_info, errors) or not stages_field : # Must have stages
            errors.append(f"{entity_info}: Quest stages missing/invalid or empty.")
        else:
            stages_field = cast(Dict[str, Any], stages_field) # Ensure type checker knows it's a dict
            for s_key, s_data in stages_field.items():
                s_info = f"{entity_info}, Stage '{s_key}'"
                if not self._check_is_dict(s_data, f"Stage '{s_key}' data", s_info, errors):
                    continue # Skip this stage if its main structure is wrong

                # I18n for stage fields
                stage_i18n_fields = ['title_i18n', 'description_i18n', 'requirements_description_i18n', 'alternative_solutions_i18n']
                for field in stage_i18n_fields:
                    f_val = s_data.get(field)
                    if f_val is not None and self._check_is_dict(f_val, field, s_info, errors):
                        errors.extend(self._validate_i18n_field_completeness(f_val, field, s_info))

                obj_field = s_data.get('objectives_i18n', s_data.get('objectives')) # Allow non-i18n 'objectives'
                if not isinstance(obj_field, list) or not obj_field: # Must have objectives
                    errors.append(f"{s_info}: Objectives missing/invalid or empty.")
                else:
                    for i, obj in enumerate(obj_field):
                        if not isinstance(obj, dict):
                            errors.append(f"{s_info}, Objective {i}: Not a dictionary.")
                        # else: # Further validation of objective structure if needed
                        #    if 'description_i18n' not in obj or ... : errors.append(...)

        # --- Reward Validation ---
        rewards_data = quest_data.get('rewards')
        if self._check_is_dict(rewards_data, 'rewards', entity_info, errors): # rewards block is optional, but if present, it's a dict
            rewards_data = cast(Dict[str, Any], rewards_data)
            xp = rewards_data.get('experience')
            if xp is not None: # XP is optional within rewards
                if not isinstance(xp, int) or xp < 0:
                    errors.append(f"{entity_info}: XP reward '{xp}' must be non-negative int.")
                # Check against defined XP range if rules are available
                elif self.rules.quest_rules and \
                     self.rules.quest_rules.reward_rules and \
                     self.rules.quest_rules.reward_rules.xp_reward_range:
                    xp_range = self.rules.quest_rules.reward_rules.xp_reward_range
                    if not (xp_range.min <= xp <= xp_range.max):
                        original_xp = xp
                        corrected_xp = max(xp_range.min, min(original_xp, xp_range.max))
                        rewards_data['experience'] = corrected_xp # Clamp
                        msg = f"{entity_info}: XP {original_xp} out of range ({xp_range.min}-{xp_range.max}). Clamped to {corrected_xp}."
                        errors.append(msg); notifications.append(f"AUTO-CORRECT: {msg}")

            item_rewards = rewards_data.get('items')
            if isinstance(item_rewards, list): # Items list is optional, but if present, must be a list
                for i, item_entry in enumerate(item_rewards):
                    item_info_ctx = f"{entity_info}, Item Reward {i}"
                    template_id_to_check: Optional[str] = None
                    if isinstance(item_entry, str):
                        template_id_to_check = item_entry
                    elif isinstance(item_entry, dict):
                        template_id_to_check = item_entry.get('template_id')
                        if not isinstance(template_id_to_check, str):
                            errors.append(f"{item_info_ctx}: 'template_id' is missing or not a string in item reward object.")
                        quantity = item_entry.get('quantity')
                        if quantity is not None and (not isinstance(quantity, int) or quantity <=0): # Quantity is optional, but must be positive int if present
                            errors.append(f"{item_info_ctx}: Quantity '{quantity}' invalid for item '{template_id_to_check}'. Must be positive integer.")
                    else:
                        errors.append(f"{item_info_ctx}: Item reward entry is not a string or dictionary.")

                    if template_id_to_check and template_id_to_check not in _existing_item_template_ids:
                        errors.append(f"{item_info_ctx}: Item template_id '{template_id_to_check}' not found.")
            elif item_rewards is not None: # If 'items' key exists but is not a list
                 errors.append(f"{entity_info}: 'items' in rewards must be a list.")

        final_status, requires_moderation_flag = self._determine_status_and_moderation(errors, notifications)
        return {"entity_id": entity_id_str, "type": "quest", "status": final_status, "errors": errors,
                "notifications": notifications, "requires_moderation": requires_moderation_flag, "validated_data": quest_data}

    def validate_item_block(self, item_data: Dict[str, Any],
                            existing_quest_ids: Optional[Set[str]] = None,
                            existing_npc_ids: Optional[Set[str]] = None,
                            existing_item_template_ids: Optional[Set[str]] = None) -> BlockValidationResult:
        """
        Validates a single Item data block against game rules.

        Checks i18n completeness, item type, price (with clamping), and presence of
        some type-specific properties (as notifications).

        Args:
            item_data: The Item data dictionary to validate.
            existing_quest_ids: Not used by item block.
            existing_npc_ids: Not used by item block.
            existing_item_template_ids: Set of existing item template IDs for validating template_id.

        Returns:
            A BlockValidationResult dictionary.
        """
        errors: List[str] = []
        notifications: List[str] = []
        entity_id_str = item_data.get('id', item_data.get('template_id')) # Items often use template_id as their primary non-instance ID
        entity_info = f"Item '{entity_id_str or 'Unknown Item'}'"

        if not self._check_is_dict(item_data, "Item root", entity_info, errors):
            status, req_mod = self._determine_status_and_moderation(errors, notifications)
            return {"entity_id": entity_id_str, "type": "item", "status": status, "errors": errors,
                    "notifications": notifications, "requires_moderation": req_mod, "validated_data": item_data}

        # --- Template ID Validation (Crucial for items) ---
        template_id = item_data.get('template_id')
        if not template_id:
            errors.append(f"{entity_info}: Missing 'template_id'.")
        # Check against existing if list provided (e.g. for generated items referencing known templates)
        elif existing_item_template_ids is not None and template_id not in existing_item_template_ids:
             errors.append(f"{entity_info}: Item's template_id '{template_id}' not in known template IDs.")

        # --- I18n Field Completeness (for fields AI might generate directly) ---
        item_i18n_fields = ['name_i18n', 'description_i18n']
        for field in item_i18n_fields:
            f_val = item_data.get(field)
            if f_val is not None and self._check_is_dict(f_val, field, entity_info, errors): # Only validate if present and dict
                errors.extend(self._validate_i18n_field_completeness(f_val, field, entity_info))

        # --- Item Type Validation ---
        item_type = item_data.get('type')
        item_type_validated = False # Flag to ensure type is valid before using it for price checks
        if item_type: # Item type is often important
            if isinstance(item_type, str):
                if self.rules.item_rules and self.rules.item_rules.valid_item_types:
                    if item_type not in self.rules.item_rules.valid_item_types:
                        errors.append(f"{entity_info}: Invalid item type: '{item_type}'.")
                    else:
                        item_type_validated = True # Type is valid
                else: # No rules for valid_item_types
                    notifications.append(f"{entity_info}: No valid_item_types rule defined. Skipping item type validation for '{item_type}'.")
            else:
                errors.append(f"{entity_info}: Item 'type' field must be a string, got {type(item_type).__name__}.")
        # else: Item type might be optional if derived from template_id later in the system.

        # --- Price Validation ---
        price = item_data.get('price')
        if price is not None: # Price is often optional for items (e.g., quest items, or if price comes from template)
            if not isinstance(price, (int, float)) or price < 0:
                errors.append(f"{entity_info}: Price '{price}' must be a non-negative number.")
            else: # Price is a valid number, proceed with range checks
                if self.rules.item_rules and self.rules.item_rules.price_ranges_by_type:
                    if item_type and item_type_validated: # Only if type is known and valid
                        item_rarity = item_data.get('rarity', 'common').lower() # Default rarity to 'common'

                        price_cat_rules = self.rules.item_rules.price_ranges_by_type.get(item_type)
                        if price_cat_rules and price_cat_rules.prices: # price_cat_rules is ItemPriceCategory
                            price_detail_rules = price_cat_rules.prices.get(item_rarity) # price_detail_rules is ItemPriceDetail
                            if price_detail_rules:
                                min_price, max_price = price_detail_rules.min, price_detail_rules.max
                                if not (min_price <= price <= max_price):
                                    original_price = price
                                    clamped_price = max(min_price, min(original_price, max_price))
                                    item_data['price'] = clamped_price # Clamp the price in the data
                                    msg = f"{entity_info}: Price {original_price} for type '{item_type}' rarity '{item_rarity}' out of range ({min_price}-{max_price}). Clamped to {clamped_price}."
                                    errors.append(msg); notifications.append(f"AUTO-CORRECT: {msg}")
                            else: # No price rules for this specific rarity
                                notifications.append(f"{entity_info}: No price rules for rarity '{item_rarity}' of type '{item_type}'. Skipping price range check.")
                        else: # No price categories defined for this item type
                            notifications.append(f"{entity_info}: No price categories found for item type '{item_type}'. Skipping price range validation.")
                    elif item_type and not item_type_validated: # Type was provided but invalid
                         notifications.append(f"{entity_info}: Item type '{item_type}' is invalid. Skipping price range validation based on type.")
                    else: # Item type not specified, cannot use type-based price rules
                        notifications.append(f"{entity_info}: Item type not specified. Skipping type/rarity-based price range validation.")
                else: # No price_ranges_by_type rule defined at all
                    notifications.append(f"{entity_info}: No price_ranges_by_type rule defined. Skipping price range validation.")

        # --- General Property Presence (Example soft checks) ---
        if item_type_validated: # Only perform these checks if the type was valid
            if item_type == 'weapon' and 'damage' not in item_data:
                notifications.append(f"{entity_info}: Weapon missing 'damage' field (soft check).")
            if item_type == 'potion' and 'effect' not in item_data:
                notifications.append(f"{entity_info}: Potion missing 'effect' field (soft check).")

        final_status, requires_moderation_flag = self._determine_status_and_moderation(errors, notifications)
        return {"entity_id": entity_id_str, "type": "item", "status": final_status, "errors": errors,
                "notifications": notifications, "requires_moderation": requires_moderation_flag, "validated_data": item_data}

    def validate_ai_response(self, ai_json_string: str, expected_structure: str,
                             existing_quest_ids: Optional[Set[str]] = None,
                             existing_npc_ids: Optional[Set[str]] = None,
                             existing_item_template_ids: Optional[Set[str]] = None) -> Dict[str, Any]:
        """
        Parses an AI-generated JSON string and validates its content based on the expected structure and game rules.

        Args:
            ai_json_string: The JSON string received from the AI.
            expected_structure: A string indicating the expected top-level structure of the JSON.
                Valid values: "single_npc", "list_of_npcs", "single_quest", "list_of_quests",
                              "single_item", "list_of_items".
            existing_quest_ids: Optional set of existing quest IDs for referential integrity checks.
            existing_npc_ids: Optional set of existing NPC IDs for referential integrity checks.
            existing_item_template_ids: Optional set of existing item template IDs for referential integrity.

        Returns:
            A dictionary summarizing the validation outcome:
            {
                "overall_status": str,  // "success", "success_with_autocorrections",
                                       // "requires_moderation", or "error" (for global issues like bad JSON)
                "entities": List[BlockValidationResult], // List of validation results for each entity
                                                        // Each BlockValidationResult contains:
                                                        //   "entity_id": str|None, "type": str, "status": str,
                                                        //   "errors": List[str], "notifications": List[str],
                                                        //   "requires_moderation": bool, "validated_data": Dict
                "global_errors": List[str] // Errors related to overall parsing or structure, not specific entities.
            }
        """
        entities: List[BlockValidationResult] = []
        global_errors: List[str] = []

        try:
            parsed_data = json.loads(ai_json_string)
        except json.JSONDecodeError as e:
            global_errors.append(f"Invalid JSON format: {e}")
            # No entities to process, return immediately with global error
            return {"overall_status": "error", "entities": entities, "global_errors": global_errors}

        validator_func: Optional[ValidatorFuncType] = None
        validator_func: Optional[Callable[..., Any]] = None # To satisfy type checker before assignment
        is_list = False # Flag to indicate if parsed_data should be a list of entities

        # Determine the correct block validator function based on expected_structure
        if expected_structure == "list_of_npcs": validator_func = self.validate_npc_block; is_list = True
        elif expected_structure == "single_npc": validator_func = self.validate_npc_block
        elif expected_structure == "list_of_quests": validator_func = self.validate_quest_block; is_list = True
        elif expected_structure == "single_quest": validator_func = self.validate_quest_block
        elif expected_structure == "list_of_items": validator_func = self.validate_item_block; is_list = True
        elif expected_structure == "single_item": validator_func = self.validate_item_block
        else:
            global_errors.append(f"Unknown expected_structure: '{expected_structure}'")
            return {"overall_status": "error", "entities": entities, "global_errors": global_errors}

        # Prepare context arguments to pass to block validators
        context_args = {
            "existing_quest_ids": existing_quest_ids,
            "existing_npc_ids": existing_npc_ids,
            "existing_item_template_ids": existing_item_template_ids
        }

        if is_list:
            if not isinstance(parsed_data, list):
                global_errors.append(f"Expected a list for '{expected_structure}', but got {type(parsed_data).__name__}.")
            else: # It's a list, iterate and validate each item
                for i, item_data_uncast in enumerate(parsed_data):
                    if not isinstance(item_data_uncast, dict):
                        err_msg = f"Item at index {i} for '{expected_structure}' is not a dictionary, skipping validation for this item."
                        global_errors.append(err_msg)
                        # Add a placeholder error entity for this malformed list item
                        entity_type_str = expected_structure.split('_of_')[-1][:-1] if '_of_' in expected_structure else "unknown" # e.g. "npc" from "list_of_npcs"
                        entities.append({
                            "entity_id": None, "type": entity_type_str,
                            "status": "requires_moderation", "errors": [err_msg],
                            "notifications": [], "requires_moderation": True,
                            "validated_data": item_data_uncast if isinstance(item_data_uncast, dict) else {"raw_data": item_data_uncast}
                        })
                        continue
                    # Call the appropriate block validator for the dictionary item
                    if validator_func:
                        entities.append(validator_func(cast(Dict[str, Any], item_data_uncast), **context_args))
                    # If validator_func is None here, it means expected_structure was unknown,
                    # and global_errors would have been populated. The loop continues,
                    # but no validation for this item happens.
                    # If validator_func is None here, it implies an issue with expected_structure that wasn't caught
                    # by the initial return, though that path should ideally prevent this.
        else: # Expected a single dictionary entity
            if not isinstance(parsed_data, dict):
                global_errors.append(f"Expected a dictionary for '{expected_structure}', but got {type(parsed_data).__name__}.")
            else:
                # Call the appropriate block validator for the single dictionary
                if validator_func:
                    entities.append(validator_func(cast(Dict[str, Any], parsed_data), **context_args))
                # If validator_func is None, global_errors related to unknown expected_structure
                # would have already been set.
                # If validator_func is None here, similar to the list case, an error in logic or unhandled expected_structure.

        # Determine overall_status based on global_errors and individual entity statuses
        overall_status = "success" # Default assumption
        if global_errors: # Any global error immediately makes the overall status "error"
            overall_status = "error"
        elif any(entity.get("status") == "requires_moderation" for entity in entities):
            overall_status = "requires_moderation"
        elif any(entity.get("status") == "success_with_autocorrections" for entity in entities):
            overall_status = "success_with_autocorrections"
        # If no global errors and no entities require moderation or had auto-corrections, it remains "success".

        return {"overall_status": overall_status, "entities": entities, "global_errors": global_errors}

