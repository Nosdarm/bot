import json
import logging
from pydantic import BaseModel, ValidationError as PydanticValidationError # Ensure Pydantic's ValidationError is imported
from typing import Tuple, TYPE_CHECKING, Any, Dict, Optional, List # Added Tuple, TYPE_CHECKING

# Import the new Pydantic models for AI outputs
from .ai_data_models import GeneratedLocationContent, GeneratedNpcProfile, GeneratedQuest as GeneratedQuestData # Use alias for GeneratedQuest

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager # For type hinting

logger = logging.getLogger(__name__)

class AIResponseValidator:
    def __init__(self):
        # The validator might not need to store game_manager or db_service
        # if they are passed directly to its methods, as planned for this subtask.
        pass

    async def parse_and_validate_location_description_response(
        self,
        raw_ai_output_text: str,
        guild_id: str,
        game_manager: "GameManager"
    ) -> Optional[Dict[str, str]]:
        """
        Parses the AI's raw text output (expected to be JSON) for a location description,
        validates its structure and essential content.

        Args:
            raw_ai_output_text: The raw string output from the AI.
            guild_id: The ID of the guild for which the description was generated.
            game_manager: An instance of GameManager to fetch guild-specific rules (like language).

        Returns:
            A dictionary containing the i18n descriptions (e.g., {"en": "desc", "ru": "описание"})
            if parsing and validation are successful, otherwise None.
        """
        logger.debug(f"Attempting to parse and validate AI location description for guild {guild_id}. Raw output (first 100 chars): '{raw_ai_output_text[:100]}'")

        # 1. Parse JSON
        try:
            parsed_data = json.loads(raw_ai_output_text)
        except json.JSONDecodeError as e:
            logger.warning(f"Validation Error (guild {guild_id}): AI output is not valid JSON. Error: {e}. Raw: '{raw_ai_output_text}'")
            return None

        logger.debug(f"Successfully parsed JSON for guild {guild_id}.")

        # 2. Structural Validation
        if not isinstance(parsed_data, dict):
            logger.warning(f"Validation Error (guild {guild_id}): Parsed data is not a dictionary. Type: {type(parsed_data)}. Data: {parsed_data}")
            return None

        if 'description_i18n' not in parsed_data:
            logger.warning(f"Validation Error (guild {guild_id}): Missing top-level key 'description_i18n'. Data: {parsed_data}")
            return None

        descriptions_i18n = parsed_data['description_i18n']
        if not isinstance(descriptions_i18n, dict):
            logger.warning(f"Validation Error (guild {guild_id}): 'description_i18n' is not a dictionary. Type: {type(descriptions_i18n)}. Data: {parsed_data}")
            return None

        logger.debug(f"Structural validation passed for guild {guild_id}.")

        # 3. Semantic Validation
        try:
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
        except Exception as e:
            logger.error(f"Semantic Validation Error (guild {guild_id}): Could not fetch bot_language using game_manager.get_rule. Error: {e}", exc_info=True)
            return None # Cannot proceed without knowing the expected primary language

        # Check for primary bot language key
        if bot_language not in descriptions_i18n:
            logger.warning(f"Validation Error (guild {guild_id}): Missing required language key '{bot_language}' in 'description_i18n'. Data: {descriptions_i18n}")
            return None

        if not descriptions_i18n[bot_language] or not isinstance(descriptions_i18n[bot_language], str) or not descriptions_i18n[bot_language].strip():
            logger.warning(f"Validation Error (guild {guild_id}): Description for primary language '{bot_language}' is missing, not a string, or empty. Value: '{descriptions_i18n.get(bot_language)}'")
            return None

        # Check for 'en' key (required fallback)
        if 'en' not in descriptions_i18n:
            logger.warning(f"Validation Error (guild {guild_id}): Missing required language key 'en' (English) in 'description_i18n'. Data: {descriptions_i18n}")
            return None

        if not descriptions_i18n['en'] or not isinstance(descriptions_i18n['en'], str) or not descriptions_i18n['en'].strip():
            logger.warning(f"Validation Error (guild {guild_id}): Description for English ('en') is missing, not a string, or empty. Value: '{descriptions_i18n.get('en')}'")
            return None

        logger.info(f"Semantic validation passed for guild {guild_id}. Required languages '{bot_language}' and 'en' are present and non-empty.")

        # 4. Successful Validation
        # Return only the descriptions_i18n dictionary, ensuring values are stripped.
        validated_descriptions = {}
        for lang_code, desc_text in descriptions_i18n.items():
            if isinstance(desc_text, str) and desc_text.strip():
                validated_descriptions[lang_code] = desc_text.strip()
            else:
                # Log if a non-required language has an empty/invalid description, but don't fail validation for it.
                if lang_code != bot_language and lang_code != 'en':
                    logger.warning(f"Validation Warning (guild {guild_id}): Language code '{lang_code}' had an empty or non-string description. It will be excluded from the final result. Original value: '{desc_text}'")

        # Final check to ensure the required languages are still valid after stripping and filtering
        if not (bot_language in validated_descriptions and validated_descriptions[bot_language]):
            logger.error(f"Critical Validation Error (guild {guild_id}): Primary language '{bot_language}' description became empty after processing. Initial: '{descriptions_i18n.get(bot_language)}'")
            return None
        if not ('en' in validated_descriptions and validated_descriptions['en']):
            logger.error(f"Critical Validation Error (guild {guild_id}): English ('en') description became empty after processing. Initial: '{descriptions_i18n.get('en')}'")
            return None

        logger.info(f"Successfully parsed and validated location description for guild {guild_id}. Returning: {validated_descriptions}")
        return validated_descriptions

    async def parse_and_validate_faction_generation_response(
        self,
        raw_ai_output_text: str,
        guild_id: str,
        game_manager: "GameManager"
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Parses the AI's raw text output (expected to be JSON) for faction generation,
        validates its structure and essential content for each faction.

        Args:
            raw_ai_output_text: The raw string output from the AI.
            guild_id: The ID of the guild for which factions were generated.
            game_manager: An instance of GameManager to fetch guild-specific rules (like language).

        Returns:
            A list of validated faction data dictionaries if successful, otherwise None.
            Each faction dictionary will contain the i18n fields.
        """
        logger.debug(f"Attempting to parse and validate AI faction generation response for guild {guild_id}. Raw output (first 100 chars): '{raw_ai_output_text[:100]}'")

        # 1. Parse Main JSON
        try:
            parsed_data = json.loads(raw_ai_output_text)
        except json.JSONDecodeError as e:
            logger.warning(f"Faction Validation Error (guild {guild_id}): AI output is not valid JSON. Error: {e}. Raw: '{raw_ai_output_text}'")
            return None

        if not isinstance(parsed_data, dict):
            logger.warning(f"Faction Validation Error (guild {guild_id}): Parsed data is not a dictionary. Type: {type(parsed_data)}. Data: {parsed_data}")
            return None

        if 'new_factions' not in parsed_data:
            logger.warning(f"Faction Validation Error (guild {guild_id}): Missing top-level key 'new_factions'. Data: {parsed_data}")
            return None

        faction_data_list = parsed_data['new_factions']
        if not isinstance(faction_data_list, list):
            logger.warning(f"Faction Validation Error (guild {guild_id}): 'new_factions' is not a list. Type: {type(faction_data_list)}. Data: {parsed_data}")
            return None

        if not faction_data_list: # AI returned an empty list
            logger.warning(f"Faction Validation Info (guild {guild_id}): 'new_factions' list is empty. No factions to validate.")
            return [] # Return empty list, as the structure is valid but no data

        logger.debug(f"Successfully parsed JSON for faction generation for guild {guild_id}. Found {len(faction_data_list)} potential factions.")

        # 2. Fetch Guild Language
        try:
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
        except Exception as e:
            logger.error(f"Faction Validation Error (guild {guild_id}): Could not fetch bot_language using game_manager.get_rule. Error: {e}", exc_info=True)
            return None

        # 3. Iterate and Validate Each Faction Object
        validated_factions: List[Dict[str, Any]] = []
        required_i18n_fields = ["name_i18n", "ideology_i18n", "description_i18n"]
        optional_i18n_fields = ["leader_concept_i18n", "resource_notes_i18n"]

        for i, faction_data in enumerate(faction_data_list):
            log_prefix = f"Faction Validation (guild {guild_id}, faction item {i+1})"
            if not isinstance(faction_data, dict):
                logger.warning(f"{log_prefix}): Item is not a dictionary. Skipping. Data: {faction_data}")
                continue

            current_faction_valid = True
            processed_faction: Dict[str, Any] = {}

            # Validate Required i18n fields
            for field_name in required_i18n_fields:
                field_value = faction_data.get(field_name)
                if not isinstance(field_value, dict):
                    logger.warning(f"{log_prefix}: Required field '{field_name}' is missing or not a dictionary. Data: {faction_data}")
                    current_faction_valid = False; break

                lang_specific_content = {}
                # Check bot_language
                if bot_language not in field_value or not isinstance(field_value[bot_language], str) or not field_value[bot_language].strip():
                    logger.warning(f"{log_prefix}: Required field '{field_name}' missing or empty for bot language '{bot_language}'. Data: {field_value}")
                    current_faction_valid = False; break
                lang_specific_content[bot_language] = field_value[bot_language].strip()

                # Check 'en'
                if 'en' not in field_value or not isinstance(field_value['en'], str) or not field_value['en'].strip():
                    logger.warning(f"{log_prefix}: Required field '{field_name}' missing or empty for English ('en'). Data: {field_value}")
                    current_faction_valid = False; break
                lang_specific_content['en'] = field_value['en'].strip()

                processed_faction[field_name] = lang_specific_content

            if not current_faction_valid:
                logger.warning(f"{log_prefix}: Failed required field validation. Skipping this faction object.")
                continue # Skip to next faction in faction_data_list

            # Validate Optional i18n fields (if present, must be valid)
            for field_name in optional_i18n_fields:
                if field_name in faction_data:
                    field_value = faction_data.get(field_name)
                    if not isinstance(field_value, dict): # If present, must be a dict
                        logger.warning(f"{log_prefix}: Optional field '{field_name}' is present but not a dictionary. Invalidating. Data: {field_value}")
                        current_faction_valid = False; break

                    lang_specific_content = {}
                    # Check bot_language
                    if bot_language not in field_value or not isinstance(field_value[bot_language], str) or not field_value[bot_language].strip():
                        logger.warning(f"{log_prefix}: Optional field '{field_name}' present but missing/empty for bot language '{bot_language}'. Invalidating. Data: {field_value}")
                        current_faction_valid = False; break
                    lang_specific_content[bot_language] = field_value[bot_language].strip()

                    # Check 'en'
                    if 'en' not in field_value or not isinstance(field_value['en'], str) or not field_value['en'].strip():
                        logger.warning(f"{log_prefix}: Optional field '{field_name}' present but missing/empty for English ('en'). Invalidating. Data: {field_value}")
                        current_faction_valid = False; break
                    lang_specific_content['en'] = field_value['en'].strip()

                    processed_faction[field_name] = lang_specific_content

            if not current_faction_valid:
                logger.warning(f"{log_prefix}: Failed optional field validation. Skipping this faction object.")
                continue

            # Non-i18n fields can be added here if any (e.g. "alignment_suggestion" from prompt)
            # For example, if "alignment_suggestion" was part of the prompt for the AI to generate:
            # if "alignment_suggestion" in faction_data and isinstance(faction_data["alignment_suggestion"], str):
            #    processed_faction["alignment_suggestion"] = faction_data["alignment_suggestion"]
            # else:
            #    logger.warning(f"{log_prefix}: 'alignment_suggestion' missing or not a string. Skipping field.")


            if current_faction_valid: # Re-check, as optional field validation might have failed it
                validated_factions.append(processed_faction)
                logger.debug(f"{log_prefix}: Faction object successfully validated and processed.")

        # 4. Final Check
        if not validated_factions:
            logger.warning(f"Faction Validation (guild {guild_id}): No valid faction objects found in the AI response after processing {len(faction_data_list)} items.")
            return None # Or return [] if an empty list is acceptable for "valid structure, no valid items"

        logger.info(f"Successfully parsed and validated {len(validated_factions)} factions for guild {guild_id}.")
        return validated_factions

    @staticmethod
    def _validate_i18n_field(
        data: Dict[str, Any],
        field_name: str,
        bot_language: str,
        log_prefix: str,
        english_required: bool = True,
        is_required: bool = True
    ) -> Optional[Dict[str, str]]:
        """Helper to validate a generic i18n field."""
        if field_name not in data:
            if is_required:
                logger.warning(f"{log_prefix}: Required i18n field '{field_name}' is missing.")
                return None
            return {} # Optional field, not present, return empty dict to signify valid absence

        field_value = data.get(field_name)
        if not isinstance(field_value, dict):
            logger.warning(f"{log_prefix}: Field '{field_name}' is not a dictionary. Value: {field_value}")
            return None

        processed_i18n_content = {}
        # Check bot_language
        if bot_language not in field_value or not isinstance(field_value[bot_language], str) or not field_value[bot_language].strip():
            if is_required or (field_name in data and field_value): # If optional but malformed
                 logger.warning(f"{log_prefix}: Field '{field_name}' missing or empty for bot language '{bot_language}'. Value: {field_value.get(bot_language)}")
                 return None
        elif field_value[bot_language].strip(): # Only add if valid content
            processed_i18n_content[bot_language] = field_value[bot_language].strip()

        # Check 'en' if required
        if english_required:
            if 'en' not in field_value or not isinstance(field_value['en'], str) or not field_value['en'].strip():
                if is_required or (field_name in data and field_value): # If optional but malformed
                    logger.warning(f"{log_prefix}: Field '{field_name}' missing or empty for English ('en'). Value: {field_value.get('en')}")
                    return None
            elif field_value['en'].strip(): # Only add if valid content
                 processed_i18n_content['en'] = field_value['en'].strip()

        # If it's a required field, it must have at least one valid language entry (either bot_language or en if bot_language is en)
        if is_required and not processed_i18n_content:
            logger.warning(f"{log_prefix}: Required field '{field_name}' resulted in no valid language entries after stripping. Original: {field_value}")
            return None

        return processed_i18n_content

    @staticmethod
    def _validate_json_string_field(
        data: Dict[str, Any],
        field_name: str,
        log_prefix: str,
        is_required: bool = True
    ) -> Optional[str]:
        """Helper to validate a field that should contain a JSON string."""
        if field_name not in data:
            if is_required:
                logger.warning(f"{log_prefix}: Required JSON string field '{field_name}' is missing.")
                return None
            return None # Optional field, not present

        field_value = data.get(field_name)
        if field_value is None and not is_required: # Allowed for optional fields
             return None

        if not isinstance(field_value, str):
            logger.warning(f"{log_prefix}: Field '{field_name}' is not a string. Expected JSON string. Value: {field_value}")
            return None

        if not field_value.strip() and not is_required: # Allow empty string for optional fields, treat as None
            return None

        try:
            json.loads(field_value) # Check if it's valid JSON
            return field_value # Return the original string if valid
        except json.JSONDecodeError as e:
            logger.warning(f"{log_prefix}: Field '{field_name}' is not a valid JSON string. Error: {e}. Value: {field_value}")
            return None

    async def parse_and_validate_quest_generation_response(
        self,
        raw_ai_output_text: str,
        guild_id: str,
        game_manager: "GameManager"
    ) -> Optional[Dict[str, Any]]:
        """
        Parses and validates the AI's JSON output for quest generation.
        """
        log_main_prefix = f"Quest Validation (Guild: {guild_id})"
        logger.debug(f"{log_main_prefix}: Attempting to parse and validate AI quest generation response. Raw output (first 100 chars): '{raw_ai_output_text[:100]}'")

        try:
            parsed_data = json.loads(raw_ai_output_text)
        except json.JSONDecodeError as e:
            logger.warning(f"{log_main_prefix}: AI output is not valid JSON. Error: {e}. Raw: '{raw_ai_output_text}'")
            return None

        if not isinstance(parsed_data, dict) or "quest_data" not in parsed_data:
            logger.warning(f"{log_main_prefix}: Parsed data is not a dict or missing 'quest_data' key. Data: {parsed_data}")
            return None

        quest_data = parsed_data["quest_data"]
        if not isinstance(quest_data, dict):
            logger.warning(f"{log_main_prefix}: 'quest_data' is not a dictionary. Type: {type(quest_data)}. Data: {quest_data}")
            return None

        logger.debug(f"{log_main_prefix}: Successfully parsed JSON and found 'quest_data'.")

        try:
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
        except Exception as e:
            logger.error(f"{log_main_prefix}: Could not fetch bot_language. Error: {e}", exc_info=True)
            return None

        validated_main_quest: Dict[str, Any] = {}

        # Validate Main Quest Data
        main_quest_log_prefix = f"{log_main_prefix} MainQuest"

        title = self._validate_i18n_field(quest_data, "title_i18n", bot_language, main_quest_log_prefix)
        if title is None: return None
        validated_main_quest["title_i18n"] = title

        description = self._validate_i18n_field(quest_data, "description_i18n", bot_language, main_quest_log_prefix)
        if description is None: return None
        validated_main_quest["description_i18n"] = description

        suggested_level = quest_data.get("suggested_level")
        if not isinstance(suggested_level, int) or suggested_level <= 0:
            logger.warning(f"{main_quest_log_prefix}: 'suggested_level' is missing, not an int, or not positive. Value: {suggested_level}")
            return None
        validated_main_quest["suggested_level"] = suggested_level

        rewards_json = self._validate_json_string_field(quest_data, "rewards_json", main_quest_log_prefix, is_required=True)
        if rewards_json is None: return None # Must be valid JSON string if present
        validated_main_quest["rewards_json"] = rewards_json


        # Optional Main Quest Fields
        opt_giver = self._validate_i18n_field(quest_data, "quest_giver_details_i18n", bot_language, main_quest_log_prefix, is_required=False)
        if opt_giver is None and "quest_giver_details_i18n" in quest_data : return None # Present but invalid
        if opt_giver: validated_main_quest["quest_giver_details_i18n"] = opt_giver

        opt_prereqs = self._validate_json_string_field(quest_data, "prerequisites_json", main_quest_log_prefix, is_required=False)
        if opt_prereqs is None and "prerequisites_json" in quest_data and quest_data["prerequisites_json"] is not None: return None # Present but invalid (or not null and invalid)
        if opt_prereqs: validated_main_quest["prerequisites_json"] = opt_prereqs

        opt_conseq = self._validate_json_string_field(quest_data, "consequences_json", main_quest_log_prefix, is_required=False)
        if opt_conseq is None and "consequences_json" in quest_data and quest_data["consequences_json"] is not None: return None # Present but invalid
        if opt_conseq: validated_main_quest["consequences_json"] = opt_conseq

        # Validate Quest Steps
        if "steps" not in quest_data or not isinstance(quest_data["steps"], list) or not quest_data["steps"]:
            logger.warning(f"{main_quest_log_prefix}: 'steps' array is missing, not a list, or empty. Quest requires steps.")
            return None

        validated_steps: List[Dict[str, Any]] = []
        for i, step_data in enumerate(quest_data["steps"]):
            step_log_prefix = f"{log_main_prefix} Step {i+1}"
            if not isinstance(step_data, dict):
                logger.warning(f"{step_log_prefix}: Step data is not a dictionary. Skipping. Data: {step_data}")
                return None # Strict: one bad step fails all

            processed_step: Dict[str, Any] = {}

            step_title = self._validate_i18n_field(step_data, "title_i18n", bot_language, step_log_prefix)
            if step_title is None: return None # Strict: one bad step field fails all
            processed_step["title_i18n"] = step_title

            step_desc = self._validate_i18n_field(step_data, "description_i18n", bot_language, step_log_prefix)
            if step_desc is None: return None
            processed_step["description_i18n"] = step_desc

            req_mech = self._validate_json_string_field(step_data, "required_mechanics_json", step_log_prefix, is_required=True)
            if req_mech is None: return None
            processed_step["required_mechanics_json"] = req_mech

            # Optional step fields
            abs_goal = self._validate_json_string_field(step_data, "abstract_goal_json", step_log_prefix, is_required=False)
            if abs_goal is None and "abstract_goal_json" in step_data and step_data["abstract_goal_json"] is not None: return None
            if abs_goal: processed_step["abstract_goal_json"] = abs_goal

            step_conseq = self._validate_json_string_field(step_data, "consequences_json", step_log_prefix, is_required=False)
            if step_conseq is None and "consequences_json" in step_data and step_data["consequences_json"] is not None: return None
            if step_conseq: processed_step["consequences_json"] = step_conseq

            # Other non-validated fields like step_order can be copied if needed, assuming AI provides them correctly.
            if "step_order" in step_data and isinstance(step_data["step_order"], int):
                 processed_step["step_order"] = step_data["step_order"]
            else: # Default step_order if not provided or invalid
                 logger.warning(f"{step_log_prefix}: 'step_order' missing or invalid, defaulting to index {i}.")
                 processed_step["step_order"] = i


            validated_steps.append(processed_step)

        if not validated_steps: # Should have been caught by earlier check if quest_data["steps"] was empty
            logger.warning(f"{main_quest_log_prefix}: No valid steps found after processing.")
            return None

        validated_main_quest["steps"] = validated_steps
        logger.info(f"{log_main_prefix}: Successfully parsed and validated quest data with {len(validated_steps)} steps.")
        return validated_main_quest

    async def parse_and_validate_item_generation_response(
        self,
        raw_ai_output_text: str,
        guild_id: str,
        game_manager: "GameManager"
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Parses the AI's raw text output (expected to be JSON) for item generation,
        validates its structure and essential content for each item.

        Args:
            raw_ai_output_text: The raw string output from the AI.
            guild_id: The ID of the guild for which items were generated.
            game_manager: An instance of GameManager to fetch guild-specific rules (like language).

        Returns:
            A list of validated item data dictionaries if successful, otherwise None.
        """
        log_main_prefix = f"ItemValidation (Guild: {guild_id})"
        logger.debug(f"{log_main_prefix}: Attempting to parse and validate AI item generation response. Raw output (first 100 chars): '{raw_ai_output_text[:100]}'")

        try:
            parsed_data = json.loads(raw_ai_output_text)
        except json.JSONDecodeError as e:
            logger.warning(f"{log_main_prefix}: AI output is not valid JSON. Error: {e}. Raw: '{raw_ai_output_text}'")
            return None

        if not isinstance(parsed_data, dict) or "new_items" not in parsed_data:
            logger.warning(f"{log_main_prefix}: Parsed data is not a dict or missing 'new_items' key. Data: {parsed_data}")
            return None

        item_data_list = parsed_data.get("new_items")
        if not isinstance(item_data_list, list):
            logger.warning(f"{log_main_prefix}: 'new_items' is not a list. Type: {type(item_data_list)}. Data: {parsed_data}")
            return None

        if not item_data_list:
            logger.info(f"{log_main_prefix}: 'new_items' list is empty. No items to validate.")
            return []

        logger.debug(f"{log_main_prefix}: Successfully parsed JSON. Found {len(item_data_list)} potential items.")

        try:
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
        except Exception as e:
            logger.error(f"{log_main_prefix}: Could not fetch bot_language. Error: {e}", exc_info=True)
            return None

        validated_items: List[Dict[str, Any]] = []

        for i, item_data in enumerate(item_data_list):
            item_log_prefix = f"{log_main_prefix} Item {i+1}"
            if not isinstance(item_data, dict):
                logger.warning(f"{item_log_prefix}: Item data is not a dictionary. Skipping. Data: {item_data}")
                continue

            processed_item: Dict[str, Any] = {}
            current_item_valid = True

            # Required i18n fields
            name_i18n = self._validate_i18n_field(item_data, "name_i18n", bot_language, item_log_prefix)
            if name_i18n is None: current_item_valid = False
            else: processed_item["name_i18n"] = name_i18n

            desc_i18n = self._validate_i18n_field(item_data, "description_i18n", bot_language, item_log_prefix)
            if desc_i18n is None: current_item_valid = False
            else: processed_item["description_i18n"] = desc_i18n

            # Required string fields
            item_type = item_data.get("item_type")
            if not isinstance(item_type, str) or not item_type.strip():
                logger.warning(f"{item_log_prefix}: 'item_type' is missing or empty. Data: {item_data}")
                current_item_valid = False
            else:
                processed_item["item_type"] = item_type.strip()

            # Required integer field
            base_value = item_data.get("base_value")
            if not isinstance(base_value, int): # Allow 0 as a valid value
                logger.warning(f"{item_log_prefix}: 'base_value' is missing or not an integer. Data: {item_data}")
                current_item_valid = False
            else:
                processed_item["base_value"] = base_value

            # Required JSON string field
            properties_json = self._validate_json_string_field(item_data, "properties_json", item_log_prefix, is_required=True)
            if properties_json is None: current_item_valid = False # If required and invalid/missing
            else: processed_item["properties_json"] = properties_json


            # Optional string field
            rarity_level = item_data.get("rarity_level")
            if rarity_level is not None: # If present, it must be a non-empty string
                if not isinstance(rarity_level, str) or not rarity_level.strip():
                    logger.warning(f"{item_log_prefix}: Optional 'rarity_level' is present but empty or not a string. Data: {item_data}")
                    current_item_valid = False
                else:
                    processed_item["rarity_level"] = rarity_level.strip()

            if current_item_valid:
                validated_items.append(processed_item)
                logger.debug(f"{item_log_prefix}: Item object successfully validated and processed: {processed_item.get('name_i18n',{}).get(bot_language, 'Unknown Item')}")
            else:
                logger.warning(f"{item_log_prefix}: Item failed validation. Skipping. Data: {item_data}")

        if not item_data_list: # This case is already handled (returns [] if item_data_list is empty)
             pass
        elif not validated_items: # item_data_list was not empty, but nothing validated
            logger.warning(f"{log_main_prefix}: No valid item objects found after processing {len(item_data_list)} items.")
            return None

        logger.info(f"{log_main_prefix}: Successfully parsed and validated {len(validated_items)} items out of {len(item_data_list)} received.")
        return validated_items

    async def parse_and_validate_npc_generation_response(
        self,
        raw_ai_output_text: str,
        guild_id: str,
        game_manager: "GameManager"
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Parses the AI's raw text output (expected to be JSON) for NPC generation,
        validates its structure and essential content for each NPC.

        Args:
            raw_ai_output_text: The raw string output from the AI.
            guild_id: The ID of the guild for which NPCs were generated.
            game_manager: An instance of GameManager to fetch guild-specific rules (like language).

        Returns:
            A list of validated NPC data dictionaries if successful, otherwise None.
        """
        log_main_prefix = f"NPCValidation (Guild: {guild_id})"
        logger.debug(f"{log_main_prefix}: Attempting to parse and validate AI NPC generation response. Raw output (first 100 chars): '{raw_ai_output_text[:100]}'")

        try:
            parsed_data = json.loads(raw_ai_output_text)
        except json.JSONDecodeError as e:
            logger.warning(f"{log_main_prefix}: AI output is not valid JSON. Error: {e}. Raw: '{raw_ai_output_text}'")
            return None

        if not isinstance(parsed_data, dict) or "new_npcs" not in parsed_data:
            logger.warning(f"{log_main_prefix}: Parsed data is not a dict or missing 'new_npcs' key. Data: {parsed_data}")
            return None

        npc_data_list = parsed_data.get("new_npcs")
        if not isinstance(npc_data_list, list):
            logger.warning(f"{log_main_prefix}: 'new_npcs' is not a list. Type: {type(npc_data_list)}. Data: {parsed_data}")
            return None

        if not npc_data_list:
            logger.info(f"{log_main_prefix}: 'new_npcs' list is empty. No NPCs to validate.")
            return []

        logger.debug(f"{log_main_prefix}: Successfully parsed JSON. Found {len(npc_data_list)} potential NPCs.")

        try:
            bot_language = await game_manager.get_rule(guild_id, 'default_language', 'en')
        except Exception as e:
            logger.error(f"{log_main_prefix}: Could not fetch bot_language. Error: {e}", exc_info=True)
            return None

        validated_npcs: List[Dict[str, Any]] = []

        required_i18n_fields = ["name_i18n", "description_i18n", "backstory_i18n", "persona_i18n"]
        optional_i18n_fields = ["initial_dialogue_greeting_i18n"]

        for i, npc_data in enumerate(npc_data_list):
            npc_log_prefix = f"{log_main_prefix} NPC {i+1}"
            if not isinstance(npc_data, dict):
                logger.warning(f"{npc_log_prefix}: NPC data is not a dictionary. Skipping. Data: {npc_data}")
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
