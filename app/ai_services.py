import json # For JSON parsing
from sqlalchemy.orm import Session
from typing import Optional, Tuple, Literal, TypedDict, List, Dict, Any # Added TypedDict, List, Dict, Any

from . import models # For Player, Party, Location etc.
from . import world_state_manager, rules_engine, locations_manager, player_manager, party_manager, crud
from .config import logger, OPENAI_API_KEY # Import OPENAI_API_KEY
from .db import transactional_session # For fetching GuildConfig during validation
import openai # Import openai library
from openai import OpenAI # Updated import for openai v1.x.x

def prepare_ai_prompt(db: Session,
                          guild_id: int,
                          generation_type: str,
                          location_id: Optional[int] = None,
                          player_id: Optional[int] = None,
                          party_id: Optional[int] = None,
                          additional_context: Optional[dict] = None) -> str:
    """
    Prepares a detailed prompt for the AI based on the generation type and provided context.
    """
    logger.info(f"Preparing AI prompt for guild {guild_id}, type: {generation_type}")

    prompt_parts = []

    # --- Core Context (Always Fetch) ---
    guild_config = crud.get_guild_config_by_guild_id(db, guild_id=guild_id) # Corrected call
    if not guild_config:
        logger.error(f"CRITICAL: GuildConfig not found for guild {guild_id} during AI prompt prep.")
        # In a real scenario, might raise an exception or return a structured error
        return "Error: Guild configuration not found. Cannot prepare AI prompt."

    guild_language = guild_config.bot_language
    prompt_parts.append(f"## Overall Instructions:")
    prompt_parts.append(f"- You are an AI assistant for a text-based RPG. Your responses should be creative, immersive, and engaging.")
    prompt_parts.append(f"- Generate all textual content (names, descriptions, dialogue, etc.) in two languages simultaneously: '{guild_language}' (primary language for this guild) and 'en' (English, as a universal fallback).")
    prompt_parts.append(f"- Use the following JSON structure for all i18n text fields: {{'{guild_language}': 'Text in primary language', 'en': 'Text in English'}}.")
    prompt_parts.append(f"- Your entire response MUST be a single, valid JSON object that strictly adheres to the schema requested for the specified '{generation_type}'. Do not include any explanatory text, apologies, or any characters outside of this JSON structure.")

    world_state_data = world_state_manager.load_world_state(guild_id)
    prompt_parts.append(f"\n## Current World Context (Guild ID: {guild_id}):")
    prompt_parts.append(f"- World State: {world_state_data}") # Consider json.dumps for complex dicts

    rules_config_data = rules_engine.load_rules_config(guild_id)
    # Example: filter or summarize rules for relevance to AI.
    relevant_rules_for_ai = {
        'game_theme': rules_config_data.get('game_theme', 'classic fantasy'),
        'game_tone': rules_config_data.get('game_tone', 'adventurous and slightly dangerous'),
        'ai_creativity_level': rules_config_data.get('ai_creativity_level', 'high'),
        'forbidden_topics': rules_config_data.get('forbidden_topics', ['real_world_politics', 'explicit_content'])
    }
    prompt_parts.append(f"- Key Game Rules & Guidelines (subset): {relevant_rules_for_ai}")

    # --- Specific Context based on generation_type & IDs ---
    current_location = None
    if location_id:
        current_location = locations_manager.get_location(db, location_id)
        if current_location and current_location.guild_id == guild_id:
            prompt_parts.append(f"\n## Current Location Context (Location ID: {location_id}, Static ID: {current_location.static_id}):")
            prompt_parts.append(f"- Location Name: {current_location.name_i18n}")
            prompt_parts.append(f"- Location Type: {current_location.type}")
            prompt_parts.append(f"- Location Description: {current_location.descriptions_i18n}")
            prompt_parts.append(f"- Existing Neighbors: {current_location.neighbor_locations_json}")
            prompt_parts.append(f"- Existing AI Metadata for this location: {current_location.ai_metadata_json}")
            prompt_parts.append(f"- Existing Generated Details for this location: {current_location.generated_details_json}")
        else:
            logger.warning(f"Location {location_id} not found or guild mismatch for AI prompt. Guild ID: {guild_id}")

    current_player = None
    if player_id:
        current_player = player_manager.get_player_by_id(db, player_id) # player_id is Player.id
        if current_player and current_player.guild_id == guild_id:
            prompt_parts.append(f"\n## Player Context (Player ID: {player_id}, Discord ID: {current_player.discord_id}):")
            prompt_parts.append(f"- Player Level: {current_player.level}")
            prompt_parts.append(f"- Player Status: {current_player.current_status}")
            prompt_parts.append(f"- Player Gold: {current_player.gold}")
            # Future: Add player class, key items, faction alignment, etc.
        else:
            logger.warning(f"Player {player_id} not found or guild mismatch for AI prompt. Guild ID: {guild_id}")

    current_party = None
    if party_id: # party_id is Party.id
        current_party = party_manager.get_party_by_id(db, party_id)
        if current_party and current_party.guild_id == guild_id:
            prompt_parts.append(f"\n## Party Context (Party ID: {party_id}):")
            prompt_parts.append(f"- Party Name: {current_party.name}")
            prompt_parts.append(f"- Party Leader ID (Player.id): {current_party.leader_id}")
            prompt_parts.append(f"- Party Member IDs (Player.id list): {current_party.player_ids_json}")
            # Future: Add party reputation, average level, etc.
        else:
            logger.warning(f"Party {party_id} not found or guild mismatch for AI prompt. Guild ID: {guild_id}")

    if additional_context:
        prompt_parts.append(f"\n## Additional Context Provided for this Generation:")
        prompt_parts.append(str(additional_context)) # Convert dict to string for now

    # --- Task-Specific Instructions & Output Schema ---
    prompt_parts.append(f"\n## Generation Task Details:")
    prompt_parts.append(f"Task Type: '{generation_type}'")

    if generation_type == "npc_for_location":
        prompt_parts.append(f"Your goal is to generate details for a new Non-Player Character (NPC) who fits naturally within the current location context (if provided, otherwise a general NPC for the world).")
        prompt_parts.append(f"The NPC should be unique, memorable, and offer potential for interaction (e.g., dialogue, quest hook, information).")
        prompt_parts.append(f"Required JSON output schema (ensure this exact structure):")
        prompt_parts.append(f"{{")
        prompt_parts.append(f"  \"name_i18n\": {{ \"{guild_language}\": \"<NPC Name in {guild_language}>\", \"en\": \"<NPC Name in English>\" }},")
        prompt_parts.append(f"  \"description_i18n\": {{ \"{guild_language}\": \"<Detailed NPC description, appearance, demeanor in {guild_language}>\", \"en\": \"<Detailed NPC description in English>\" }},")
        prompt_parts.append(f"  \"dialogue_greeting_i18n\": {{ \"{guild_language}\": \"<A characteristic greeting phrase in {guild_language}>\", \"en\": \"<A characteristic greeting phrase in English>\" }},")
        prompt_parts.append(f"  \"npc_type\": \"<e.g., merchant, quest_giver, guard, traveler, scholar, hermit, artisan - choose one appropriate type>\",")
        prompt_parts.append(f"  \"faction_static_id\": \"<Optional: static_id of a relevant faction if this NPC is aligned, otherwise null or omit key>\",")
        prompt_parts.append(f"  \"key_info_i18n\": {{ \"{guild_language}\": \"<Optional: A piece of key information or a secret the NPC might know, in {guild_language}>\", \"en\": \"<Optional: Key info/secret in English>\" }}")
        prompt_parts.append(f"}}")
    elif generation_type == "location_description_detail":
        prompt_parts.append(f"Your goal is to generate an additional, vivid descriptive detail for the current location context. This detail should enhance the atmosphere and provide more sensory information.")
        prompt_parts.append(f"Required JSON output schema (ensure this exact structure):")
        prompt_parts.append(f"{{")
        prompt_parts.append(f"  \"detail_text_i18n\": {{ \"{guild_language}\": \"<The descriptive snippet in {guild_language}>\", \"en\": \"<The descriptive snippet in English>\" }},")
        prompt_parts.append(f"  \"sensory_type\": \"<sight|sound|smell|touch|feeling - choose one primary sense this detail appeals to>\",")
        prompt_parts.append(f"  \"keywords_i18n\": {{ \"{guild_language}\": [\"<keyword1 {guild_language}>\", \"<keyword2 {guild_language}>\"], \"en\": [\"<keyword1 English>\", \"<keyword2 English>\"] }}")
        prompt_parts.append(f"}}")
    elif generation_type == "quest_basic":
        prompt_parts.append(f"Generate details for a new RPG quest suitable for the game's context.")
        prompt_parts.append(f"The quest should be engaging and provide a clear objective for the player. It should consist of 1 to 3 steps.")
        prompt_parts.append(f"If an 'assigning_npc_static_id' is suggested, it should be a plausible static_id of an NPC that would logically give this quest (can be an existing one if context allows, or a new one if 'assigning_npc_suggestion_i18n' is also filled).")
        prompt_parts.append(f"Quest steps should describe a sequence of actions for the player.")
        prompt_parts.append(f"For 'required_mechanics_placeholder_json', describe the type of action (e.g., 'fetch', 'kill', 'dialogue', 'goto', 'explore') and relevant targets or parameters as a JSON object. Use i18n for descriptive text within these details.")
        prompt_parts.append(f"For 'consequences_placeholder_json', describe the outcomes of completing the step (e.g., XP, gold, items, information revealed, faction reputation change) as a JSON object. Use i18n for descriptive text within these details.")
        prompt_parts.append(f"Required JSON output format:")
        prompt_parts.append(f"{{")
        prompt_parts.append(f"  \"title_i18n\": {{ \"{guild_language}\": \"<Quest Title in {guild_language}>\", \"en\": \"<Quest Title in English>\" }},")
        prompt_parts.append(f"  \"description_i18n\": {{ \"{guild_language}\": \"<Detailed quest description, including backstory and overall goal, in {guild_language}>\", \"en\": \"<Detailed quest description in English>\" }},")
        prompt_parts.append(f"  \"assigning_npc_suggestion_i18n\": {{ \"{guild_language}\": \"<Optional: Description of a suggested NPC who assigns this quest (e.g., 'an old mage in the library', 'a worried farmer') in {guild_language}>\", \"en\": \"<Optional: Description of suggested NPC in English>\" }},")
        prompt_parts.append(f"  \"assigning_npc_static_id\": \"<Optional: A plausible new or existing static_id for the suggested assigning NPC>\",")
        prompt_parts.append(f"  \"required_level\": <Optional_Integer_Player_Level_e.g_1_5_null_if_no_specific_level>,")
        prompt_parts.append(f"  \"steps\": [")
        prompt_parts.append(f"    {{")
        prompt_parts.append(f"      \"step_order\": 1,")
        prompt_parts.append(f"      \"description_i18n\": {{ \"{guild_language}\": \"<Step 1 detailed description in {guild_language}>\", \"en\": \"<Step 1 detailed description in English>\" }},")
        prompt_parts.append(f"      \"goal_summary_i18n\": {{ \"{guild_language}\": \"<Brief goal for step 1 in {guild_language}>\", \"en\": \"<Brief goal for step 1 in English>\" }},")
        prompt_parts.append(f"      \"required_mechanics_placeholder_json\": {{ \"type\": \"<e.g., fetch/kill/dialogue/goto>\", \"details_i18n\": {{ \"{guild_language}\": \"<Description of mechanical goal in {guild_language}>\", \"en\": \"<Description of mechanical goal in English>\" }}, \"target_static_id\": \"<Optional_target_static_id_e.g._item_npc_location>\", \"count\": <Optional_Integer_count> }},")
        prompt_parts.append(f"      \"consequences_placeholder_json\": {{ \"reward_xp\": <Optional_Integer>, \"reward_gold\": <Optional_Integer>, \"reward_item_static_ids\": [\"<Optional_item_static_id>\"], \"info_revealed_i18n\": {{ \"{guild_language}\": \"<Optional info in {guild_language}>\", \"en\": \"<Optional info in English>\" }} }}")
        prompt_parts.append(f"    }}")
        prompt_parts.append(f"    // (Generate 1 to 3 steps like the one above, incrementing 'step_order')")
        prompt_parts.append(f"  ]")
        prompt_parts.append(f"}}")
    # Add more generation_types and their specific instructions/schemas later
    else:
        prompt_parts.append(f"Error: Unknown generation_type '{generation_type}'. Cannot provide specific schema instructions.")
        logger.warning(f"Unknown generation_type '{generation_type}' requested for AI prompt in guild {guild_id}.")

    prompt_parts.append(f"\nFinal Reminder: Your entire output must be a single, valid JSON object matching the schema described above for '{generation_type}'. No extra text, explanations, or markdown formatting outside the JSON structure.")

    final_prompt = "\n".join(prompt_parts)
    # Log a snippet of the prompt for debugging, avoiding overly long logs
    log_snippet = final_prompt
    if len(log_snippet) > 1000: # Max length for snippet
        log_snippet = log_snippet[:500] + "\n...\n" + log_snippet[-500:]
    logger.debug(f"Generated AI Prompt for guild {guild_id}, type {generation_type}:\n{log_snippet}")

    return final_prompt


# --- OpenAI Client Initialization ---
_openai_client = None
if OPENAI_API_KEY:
    try:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        logger.info("OpenAI client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
else:
    logger.warning("OpenAI client not initialized due to missing API key (OPENAI_API_KEY not set). AI generation will not function.")


# --- OpenAI API Call Helper (Synchronous) ---
def call_openai_api_sync(prompt: str, model_name: str = "gpt-3.5-turbo") -> Optional[str]:
    """
    Calls the OpenAI API (synchronously) with the given prompt and model.
    Returns the raw text response from the AI or None if an error occurs or client not initialized.
    """
    if not _openai_client:
        logger.error("OpenAI client is not initialized. Cannot make API call.")
        return None

    logger.info(f"Calling OpenAI API (sync) with model: {model_name}. Prompt length: {len(prompt)}")
    # Safeguard for very long prompts, actual limits depend on model and context window
    if len(prompt) > 15000:
         logger.warning(f"Prompt length ({len(prompt)}) is very long. This may exceed model context limits or be costly.")

    try:
        # Using the synchronous client
        response = _openai_client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are an expert JSON-generating AI assistant for a text-based RPG. You always output valid JSON according to the exact schema requested, with i18n fields where specified. You never include any text outside the JSON structure."},
                {"role": "user", "content": prompt}
            ],
            # temperature=0.7, # Example: Adjust for creativity vs. determinism
            # max_tokens=2000, # Example: Adjust based on expected output size for the generation type
            response_format={ "type": "json_object" } # For newer models that support JSON mode
        )

        if response.choices and len(response.choices) > 0:
            choice = response.choices[0]
            if choice.message and choice.message.content:
                ai_response_text = choice.message.content.strip()
                logger.info(f"Received synchronous response from OpenAI API. Response length: {len(ai_response_text)}")
                logger.debug(f"AI Response Snippet (sync): {ai_response_text[:200]}...")
                return ai_response_text
            else:
                logger.error("OpenAI API response (sync) choice or message content is empty.")
                return None
        else:
            logger.error("OpenAI API response (sync) does not contain any choices.")
            return None

    except openai.APIConnectionError as e:
        logger.error(f"OpenAI API request (sync) failed to connect: {e}", exc_info=True)
    except openai.RateLimitError as e:
        logger.error(f"OpenAI API request (sync) exceeded rate limit: {e}", exc_info=True)
    except openai.APIStatusError as e:
        logger.error(f"OpenAI API (sync) returned an API Status Error: Status Code: {e.status_code}, Response: {e.response}", exc_info=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred during OpenAI API call (sync): {e}", exc_info=True)

    return None


# --- TypedDicts for Parsed AI Data ---
class I18nField(TypedDict, total=False): # total=False allows for optional keys if one lang is missing temporarily
    en: str
    # Primary guild language key will be added dynamically, e.g., "ru": "..."

class ParsedNpcData(TypedDict):
    name_i18n: I18nField
    description_i18n: I18nField
    dialogue_greeting_i18n: I18nField
    npc_type: str
    faction_static_id: Optional[str]
    key_info_i18n: Optional[I18nField]

class ParsedLocationDetailData(TypedDict):
    detail_text_i18n: I18nField
    sensory_type: str
    keywords_i18n: I18nField # Changed from List[str] to I18nField to hold lists for each lang

class ParsedQuestStepMechanics(TypedDict, total=False):
    type: str
    details_i18n: I18nField
    target_npc_name_i18n: Optional[I18nField]
    target_location_name_i18n: Optional[I18nField]
    item_to_find_i18n: Optional[I18nField]
    # target_static_id and count are also in the prompt, ensure they're handled if needed.

class ParsedQuestStepConsequences(TypedDict, total=False):
    reward_xp: Optional[int]
    reward_gold: Optional[int]
    reward_item_name_i18n: Optional[I18nField] # Prompt used reward_item_static_ids: List[str]
    info_revealed_i18n: Optional[I18nField]

class ParsedQuestStepData(TypedDict):
    step_order: int
    description_i18n: I18nField
    goal_summary_i18n: I18nField
    required_mechanics_placeholder_json: ParsedQuestStepMechanics
    consequences_placeholder_json: ParsedQuestStepConsequences

class ParsedQuestData(TypedDict):
    title_i18n: I18nField
    description_i18n: I18nField
    assigning_npc_suggestion_i18n: Optional[I18nField]
    assigning_npc_static_id: Optional[str]
    required_level: Optional[int]
    steps: List[ParsedQuestStepData]

# Generic structure for parsed data before specific type validation
class GenericParsedAiResponse(TypedDict):
    raw_json: Dict[str, Any] # The successfully parsed JSON from AI
    errors: List[str]
    warnings: List[str]
    # specific_typed_data: Optional[Any] # Could hold ParsedNpcData etc. after successful validation


# --- Custom Exception ---
class AiValidationIssue(Exception):
    """Custom exception for AI response validation problems."""
    def __init__(self, message: str, errors: Optional[List[str]] = None, warnings: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors if errors is not None else []
        self.warnings = warnings if warnings is not None else []


# --- Parsing and Validation Function ---
def parse_and_validate_ai_response(
    raw_ai_output_text: str,
    guild_id: int,
    expected_schema_type: str
) -> GenericParsedAiResponse:
    """
    Parses the raw AI output, validates its structure and content.
    Returns a GenericParsedAiResponse containing the parsed data and lists of errors/warnings.
    """
    logger.info(f"Parsing and validating AI response for guild {guild_id}, type: {expected_schema_type}")

    parsed_data_dict: Dict[str, Any] = {}
    validation_errors: List[str] = []
    validation_warnings: List[str] = []

    # 1. JSON Parsing
    try:
        # Attempt to strip potential markdown code block fences if AI includes them
        processed_text = raw_ai_output_text.strip()
        if processed_text.startswith("```json"):
            processed_text = processed_text[7:]
        if processed_text.startswith("```"): # General markdown fence
            processed_text = processed_text[3:]
        if processed_text.endswith("```"):
            processed_text = processed_text[:-3]
        processed_text = processed_text.strip()

        parsed_json = json.loads(processed_text)
        if not isinstance(parsed_json, dict):
            validation_errors.append("AI output is not a valid JSON object (dictionary structure expected at the top level).")
            return GenericParsedAiResponse(raw_json={}, errors=validation_errors, warnings=validation_warnings)
        parsed_data_dict = parsed_json
    except json.JSONDecodeError as e:
        validation_errors.append(f"AI output is not valid JSON. Details: {e}. Raw text (approx first 200 chars): '{raw_ai_output_text[:200]}'")
        logger.warning(f"JSONDecodeError for guild {guild_id}, type {expected_schema_type}. Raw text: {raw_ai_output_text[:200]}...")
        return GenericParsedAiResponse(raw_json={}, errors=validation_errors, warnings=validation_warnings)

    # 2. Schema and Content Validation (Guild-Scoped)
    db_session_for_validation = None
    try:
        db_session_for_validation = next(transactional_session(guild_id=guild_id))
        guild_config = crud.get_guild_config_by_guild_id(db_session_for_validation, guild_id=guild_id)
    except Exception as e: # Catch potential DB errors during this fetch
        logger.error(f"Database error while fetching GuildConfig for validation: {e}", exc_info=True)
        validation_errors.append(f"Internal error: Could not fetch guild configuration for validation. Details: {e}")
        return GenericParsedAiResponse(raw_json=parsed_data_dict, errors=validation_errors, warnings=validation_warnings)
    finally:
        if db_session_for_validation:
            db_session_for_validation.close()

    if not guild_config:
        validation_errors.append("Critical: Guild configuration not found. Cannot perform language-specific validation.")
        return GenericParsedAiResponse(raw_json=parsed_data_dict, errors=validation_errors, warnings=validation_warnings)

    primary_lang = guild_config.bot_language
    # Ensure 'en' is always checked, even if it's the primary_lang.
    # If primary_lang is 'en', required_langs will correctly be {'en'}.
    required_langs = {'en', primary_lang}


    def _validate_i18n_field(field_name: str, data: Dict[str, Any], is_optional: bool = False) -> Optional[I18nField]:
        field_value = data.get(field_name)

        if field_value is None:
            if not is_optional:
                validation_errors.append(f"Required i18n field '{field_name}' is missing.")
            return None # Field not present

        if not isinstance(field_value, dict):
            validation_errors.append(f"I18n field '{field_name}' is not a JSON object (dictionary). Found type: {type(field_value)}.")
            return None # Invalid structure

        # Check for required languages
        missing_langs = required_langs - set(field_value.keys())
        if missing_langs:
            # This is an error if any of the *required* languages are missing.
            validation_errors.append(f"I18n field '{field_name}' is missing required translations for: {', '.join(missing_langs)}.")

        # Check individual language entries
        for lang_code, text in field_value.items():
            if lang_code not in required_langs and lang_code != primary_lang : # Allow any extra languages, but warn if not 'en' or primary
                 validation_warnings.append(f"I18n field '{field_name}' contains an unexpected language code '{lang_code}'. Expected one of {required_langs}.")

            if not isinstance(text, str) or not text.strip():
                # Allow empty strings for optional translations but warn, error if required lang is empty
                if lang_code in required_langs:
                    validation_errors.append(f"I18n field '{field_name}' has empty or non-string text for required language '{lang_code}'.")
                else: # Optional language entry is empty
                    validation_warnings.append(f"I18n field '{field_name}' has empty or non-string text for optional language '{lang_code}'.")

        # Attempt to cast to I18nField for type consistency, though TypedDict isn't runtime enforced this way
        return field_value if isinstance(field_value, dict) else None


    # --- Schema-specific validation ---
    if expected_schema_type == "npc_for_location":
        _validate_i18n_field("name_i18n", parsed_data_dict)
        _validate_i18n_field("description_i18n", parsed_data_dict)
        _validate_i18n_field("dialogue_greeting_i18n", parsed_data_dict)

        if not isinstance(parsed_data_dict.get("npc_type"), str) or not parsed_data_dict.get("npc_type","").strip():
            validation_errors.append("Field 'npc_type' is missing, empty, or not a string.")

        if "faction_static_id" in parsed_data_dict and not (isinstance(parsed_data_dict["faction_static_id"], str) or parsed_data_dict["faction_static_id"] is None):
            validation_warnings.append("Optional field 'faction_static_id' is present but not a string or null.")

        _validate_i18n_field("key_info_i18n", parsed_data_dict, is_optional=True)

    elif expected_schema_type == "location_description_detail":
        _validate_i18n_field("detail_text_i18n", parsed_data_dict)
        if not isinstance(parsed_data_dict.get("sensory_type"), str) or not parsed_data_dict.get("sensory_type","").strip():
            validation_errors.append("Field 'sensory_type' is missing, empty, or not a string.")

        # keywords_i18n was changed to I18nField in TypedDict, containing lists of strings per language
        keywords_i18n_field = _validate_i18n_field("keywords_i18n", parsed_data_dict) # This was for location_description_detail
        if keywords_i18n_field:
            for lang_code, keywords_list_or_str in keywords_i18n_field.items(): # AI prompt for loc_desc_detail has keywords_i18n as I18nField of lists
                if not isinstance(keywords_list_or_str, list) or not all(isinstance(k, str) and k.strip() for k in keywords_list_or_str):
                    validation_errors.append(f"Field 'keywords_i18n' for language '{lang_code}' must be a list of non-empty strings.")

    elif expected_schema_type == "quest_basic":
        _validate_i18n_field("title_i18n", parsed_data_dict)
        _validate_i18n_field("description_i18n", parsed_data_dict)

        _validate_i18n_field("assigning_npc_suggestion_i18n", parsed_data_dict, is_optional=True)

        assigning_npc_static_id = parsed_data_dict.get("assigning_npc_static_id")
        if assigning_npc_static_id is not None and not isinstance(assigning_npc_static_id, str): # Allow empty string if AI provides it, or null
            validation_warnings.append("Optional field 'assigning_npc_static_id' should be a string if present and not null.")

        required_level = parsed_data_dict.get("required_level")
        if required_level is not None and not isinstance(required_level, int):
            validation_errors.append("Field 'required_level' must be an integer if present.")

        steps_data = parsed_data_dict.get("steps")
        if not isinstance(steps_data, list) or not steps_data:
            validation_errors.append("Field 'steps' must be a non-empty list.")
        else:
            if not (1 <= len(steps_data) <= 3):
                 validation_warnings.append(f"Quest has {len(steps_data)} steps, prompt suggested 1 to 3.")

            for i, step_dict in enumerate(steps_data):
                step_path_prefix = f"steps[{i}]" # For error reporting
                if not isinstance(step_dict, dict):
                    validation_errors.append(f"{step_path_prefix} is not a valid JSON object.")
                    continue

                step_order = step_dict.get("step_order")
                if not isinstance(step_order, int): # or check if step_order == (i + 1)
                    validation_errors.append(f"{step_path_prefix}.step_order is missing or not an integer.")

                _validate_i18n_field("description_i18n", step_dict) # Error path will be "description_i18n" not full path
                _validate_i18n_field("goal_summary_i18n", step_dict)

                mechanics_json = step_dict.get("required_mechanics_placeholder_json")
                if not isinstance(mechanics_json, dict):
                    validation_errors.append(f"{step_path_prefix}.required_mechanics_placeholder_json is missing or not a JSON object.")
                elif "type" not in mechanics_json or not isinstance(mechanics_json["type"], str) or not mechanics_json["type"].strip():
                    validation_warnings.append(f"{step_path_prefix}.required_mechanics_placeholder_json is missing a 'type' string or it's empty.")
                if isinstance(mechanics_json, dict) and mechanics_json.get("details_i18n") is not None: # details_i18n is part of the mechanics structure
                     _validate_i18n_field("details_i18n", mechanics_json) # Validates the nested i18n field

                consequences_json = step_dict.get("consequences_placeholder_json")
                if not isinstance(consequences_json, dict):
                    validation_errors.append(f"{step_path_prefix}.consequences_placeholder_json is missing or not a JSON object.")
                if isinstance(consequences_json, dict): # Check sub-fields if parent is a dict
                    if "reward_xp" in consequences_json and consequences_json["reward_xp"] is not None and not isinstance(consequences_json["reward_xp"], int):
                        validation_warnings.append(f"{step_path_prefix}.consequences_placeholder_json.reward_xp should be an integer if present.")
                    if "reward_gold" in consequences_json and consequences_json["reward_gold"] is not None and not isinstance(consequences_json["reward_gold"], int):
                        validation_warnings.append(f"{step_path_prefix}.consequences_placeholder_json.reward_gold should be an integer if present.")

                    # Prompt used "reward_item_static_ids": ["<Optional_item_static_id>"]
                    # TypedDict used "reward_item_name_i18n": Optional[I18nField]
                    # Adjusting validation to match TypedDict for now.
                    _validate_i18n_field("reward_item_name_i18n", consequences_json, is_optional=True)
                    _validate_i18n_field("info_revealed_i18n", consequences_json, is_optional=True)

    # Add more schema checks for other expected_schema_types here

    # 3. Semantic Validation (Example - can be expanded)
    # This needs the rules_engine to be available, or pass rules_config_data if fetched earlier
    # For simplicity, assuming rules_engine.load_rules_config can be called if needed.
    # However, it's better if guild_config and rules_config are passed in or fetched once.
    # The current transactional_session usage is only for guild_config.

    # rules = rules_engine.load_rules_config(guild_id) # This would open another session if not careful
    # For now, this semantic validation part is kept minimal as it might require broader context.
    if expected_schema_type == "npc_for_location" and "npc_type" in parsed_data_dict:
        # This rule check could be more dynamic if rules_engine is enhanced
        # For now, let's assume rules_engine.get_rule can be used if rules_engine itself is refactored
        # to accept a db session or if rules are pre-loaded.
        # This part of validation might be better suited for a layer above that has already fetched rules.
        # For now, commenting out direct rule check to avoid complex session handling here.
        # allowed_npc_types = rules.get("allowed_npc_types", ["commoner", "merchant", "guard", "quest_giver", "traveler", "scholar", "hermit", "artisan"])
        # if parsed_data_dict.get("npc_type") not in allowed_npc_types:
        #     validation_warnings.append(f"Generated NPC type '{parsed_data_dict.get('npc_type')}' is not in the typical allowed list: {allowed_npc_types}.")
        pass


    logger.info(f"AI Response Validation for guild {guild_id}, type {expected_schema_type}: Errors: {len(validation_errors)}, Warnings: {len(validation_warnings)}")
    if validation_errors:
         logger.warning(f"Validation Errors for guild {guild_id}, type {expected_schema_type}: {validation_errors}")
    if validation_warnings:
         logger.info(f"Validation Warnings for guild {guild_id}, type {expected_schema_type}: {validation_warnings}")

    return GenericParsedAiResponse(raw_json=parsed_data_dict, errors=validation_errors, warnings=validation_warnings)


# --- Saving Approved Content ---
async def save_approved_content(db: Session, pending_gen: models.PendingGeneration):
    """
    Saves the content from an 'approved' PendingGeneration record to the appropriate
    database tables based on its generation_type.
    This function expects to be called within an existing transaction.
    """
    if pending_gen.status != 'approved':
        logger.warning(f"save_approved_content called for PendingGeneration ID {pending_gen.id} with status '{pending_gen.status}', not 'approved'. Skipping.")
        return

    logger.info(f"Processing approved content for PendingGeneration ID {pending_gen.id}, type: {pending_gen.generation_type}")

    try:
        parsed_data = pending_gen.parsed_data_json
        if not parsed_data:
            raise ValueError("Parsed data is missing from the approved content.")

        context = pending_gen.context_json
        if not context: # Should always be present, even if empty dict
            logger.warning(f"Context data is missing or empty for PendingGeneration ID {pending_gen.id}. Proceeding with caution.")
            # raise ValueError("Context data is missing from the approved content.") # Or proceed if some types don't need it

        guild_id = pending_gen.guild_id # Get guild_id from the pending_gen record itself

        if pending_gen.generation_type == "npc_for_location":
            location_id = context.get("location_id")
            if not location_id:
                raise ValueError("location_id missing from context for npc_for_location.")

            target_location = db.query(models.Location).filter(
                models.Location.id == location_id,
                models.Location.guild_id == guild_id
            ).first()
            if not target_location:
                raise ValueError(f"Target location ID {location_id} not found or does not belong to guild {guild_id}.")

            npc_data_to_create = {
                "guild_id": guild_id,
                "location_id": location_id,
                "name_i18n": parsed_data.get("name_i18n"),
                "description_i18n": parsed_data.get("description_i18n"),
                "npc_type": parsed_data.get("npc_type"), # Assumes GeneratedNpc model has 'npc_type' (Text)
                "dialogue_greeting_i18n": parsed_data.get("dialogue_greeting_i18n"), # Assumes GeneratedNpc has this
                # Add other fields from ParsedNpcData to GeneratedNpc as needed
                # "faction_static_id": parsed_data.get("faction_static_id"),
                # "key_info_i18n": parsed_data.get("key_info_i18n"), # This might go into a different field/table
            }
            # Filter out None values to rely on DB defaults or if model fields are not nullable
            npc_data_cleaned = {k: v for k, v in npc_data_to_create.items() if v is not None}

            # Ensure all required fields for GeneratedNpc are present
            if not npc_data_cleaned.get("name_i18n"): # Example required field check
                 raise ValueError("Missing required field 'name_i18n' for GeneratedNpc.")


            new_npc = crud.create_entity(db, models.GeneratedNpc, npc_data_cleaned) # create_entity handles add, no commit here
            logger.info(f"Created GeneratedNpc ID {new_npc.id} for PendingGeneration ID {pending_gen.id} at Location ID {location_id}.")

        elif pending_gen.generation_type == "location_description_detail":
            location_id = context.get("location_id")
            if not location_id:
                raise ValueError("location_id missing from context for location_description_detail.")

            target_location = db.query(models.Location).filter(
                models.Location.id == location_id,
                models.Location.guild_id == guild_id
            ).first()
            if not target_location:
                raise ValueError(f"Target location ID {location_id} not found for detail addition.")

            if target_location.generated_details_json is None:
                target_location.generated_details_json = []

            if not isinstance(target_location.generated_details_json, list):
                logger.warning(f"Location {location_id} generated_details_json was not a list. Resetting to list before appending.")
                target_location.generated_details_json = []

            # Assuming parsed_data for "location_description_detail" is the detail object itself
            target_location.generated_details_json.append(parsed_data)

            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(target_location, "generated_details_json")

            db.add(target_location) # Stage the change
            logger.info(f"Appended description detail to Location ID {location_id} for PendingGeneration ID {pending_gen.id}.")

        elif pending_gen.generation_type == "quest_basic":
            # parsed_data should be available from pending_gen.parsed_data_json
            # This assumes it has been validated by parse_and_validate_ai_response
            # to match ParsedQuestData structure.

            assigning_npc_id = None
            npc_static_id_from_ai = parsed_data.get("assigning_npc_static_id")
            if npc_static_id_from_ai:
                # Query for the NPC using the static_id and guild_id
                assigning_npc = db.query(models.GeneratedNpc).filter(
                    models.GeneratedNpc.guild_id == pending_gen.guild_id,
                    models.GeneratedNpc.static_id == npc_static_id_from_ai
                ).first()
                if assigning_npc:
                    assigning_npc_id = assigning_npc.id
                    logger.info(f"Quest Saving: Linked assigning NPC ID {assigning_npc_id} via static_id '{npc_static_id_from_ai}'.")
                else:
                    logger.warning(f"Quest Saving: Assigning NPC with static_id '{npc_static_id_from_ai}' not found for guild {pending_gen.guild_id}. Quest will be created without assigning NPC link by static_id.")

            # Create GeneratedQuest
            main_quest_details = {
                "guild_id": pending_gen.guild_id,
                "title_i18n": parsed_data.get("title_i18n"),
                "description_i18n": parsed_data.get("description_i18n"),
                "assigning_npc_id": assigning_npc_id, # This will be None if NPC not found or not specified
                "required_level": parsed_data.get("required_level"),
                "static_id": parsed_data.get("quest_static_id") # AI might suggest a static_id for the quest itself
                # Add other fields from ParsedQuestData as needed by GeneratedQuest model
            }
            # Clean None values so DB defaults can apply if a field is nullable
            main_quest_details_cleaned = {k: v for k, v in main_quest_details.items() if v is not None}

            if not main_quest_details_cleaned.get("title_i18n") or not main_quest_details_cleaned.get("description_i18n"):
                 raise ValueError("Missing required title or description for GeneratedQuest.")

            new_quest = crud.create_entity(db, models.GeneratedQuest, main_quest_details_cleaned)
            logger.info(f"Created GeneratedQuest ID {new_quest.id} (PendingGeneration ID: {pending_gen.id}).")

            # Create QuestSteps
            steps_data = parsed_data.get("steps", []) # Expecting a list of step dicts
            if not steps_data:
                logger.warning(f"Quest ID {new_quest.id} has no steps from parsed_data (PendingGeneration ID: {pending_gen.id}).")

            for step_json_data in steps_data:
                quest_step_details = {
                    "quest_id": new_quest.id,
                    "guild_id": pending_gen.guild_id, # Denormalized for easier lookup
                    "step_order": step_json_data.get("step_order"),
                    "description_i18n": step_json_data.get("description_i18n"),
                    "goal_summary_i18n": step_json_data.get("goal_summary_i18n"),
                    # Placeholders from prompt, actual implementation might differ
                    "required_mechanics_placeholder_json": step_json_data.get("required_mechanics_placeholder_json"),
                    "consequences_placeholder_json": step_json_data.get("consequences_placeholder_json")
                }
                quest_step_details_cleaned = {k: v for k, v in quest_step_details.items() if v is not None}

                if not quest_step_details_cleaned.get("step_order") or \
                   not quest_step_details_cleaned.get("description_i18n") or \
                   not quest_step_details_cleaned.get("goal_summary_i18n"):
                    logger.error(f"Skipping quest step for Quest ID {new_quest.id} due to missing critical fields (order, desc, summary). Data: {step_json_data}")
                    continue # Or raise error, depending on strictness

                crud.create_entity(db, models.QuestStep, quest_step_details_cleaned)

            logger.info(f"Saved {len(steps_data)} steps for Quest ID {new_quest.id}.")

        else:
            logger.warning(f"Unknown generation_type '{pending_gen.generation_type}' for PendingGeneration ID {pending_gen.id}. Cannot save.")
            pending_gen.status = 'error_processing_unknown_type'
            db.add(pending_gen)
            return

        pending_gen.status = 'processed'
        db.add(pending_gen)
        logger.info(f"Successfully processed and saved content for PendingGeneration ID {pending_gen.id}.")

    except Exception as e:
        logger.error(f"Error processing approved content for PendingGeneration ID {pending_gen.id}: {e}", exc_info=True)
        pending_gen.status = 'error_processing'
        error_info = {"processing_error": str(e)}
        if pending_gen.validation_errors_json and isinstance(pending_gen.validation_errors_json, list):
            pending_gen.validation_errors_json.append(error_info)
        elif isinstance(pending_gen.validation_errors_json, dict): # if it was dict from API error
            pending_gen.validation_errors_json.update(error_info)
        else: # If None or other type
            pending_gen.validation_errors_json = [error_info]
        db.add(pending_gen)
        raise # Re-raise to ensure the calling transaction is rolled back.


# --- Orchestration Function ---
async def trigger_content_generation(
    db: Session,
    guild_id: int,
    generation_type: str,
    context_data: dict,
    requested_by_discord_id: Optional[int] = None
) -> models.PendingGeneration:
    """
    Triggers the AI content generation pipeline (sequentially for now).
    1. Creates a PendingGeneration record.
    2. Prepares prompt, calls AI, validates response.
    3. Updates PendingGeneration record with results and status.
    The passed 'db' session is expected to be managed (commit/rollback) by the caller.
    """
    logger.info(f"Triggering content generation for guild {guild_id}, type: {generation_type}, context: {context_data}")

    pending_gen_data = {
        "guild_id": guild_id,
        "generation_type": generation_type,
        "context_json": context_data,
        "requested_by_discord_id": requested_by_discord_id,
        "status": "pending_create_record" # Initial status before DB interaction for this record
    }

    # Create the PendingGeneration object, add to session, and flush to get ID and server defaults
    pending_gen = models.PendingGeneration(**pending_gen_data)
    db.add(pending_gen)
    db.flush()
    db.refresh(pending_gen) # To get timestamp, updated_at, and default status if set by server

    logger.info(f"Created PendingGeneration record ID: {pending_gen.id} with initial status '{pending_gen.status}'.")

    # Sequential pipeline execution (ideal for background task later)
    try:
        # 1. Prepare Prompt
        logger.info(f"Preparing AI prompt for PendingGeneration ID: {pending_gen.id}")
        # prepare_ai_prompt requires a db session, use the one passed in.
        prompt = prepare_ai_prompt(db, guild_id, generation_type,
                                   location_id=context_data.get("location_id"),
                                   player_id=context_data.get("player_id"),
                                   party_id=context_data.get("party_id"),
                                   additional_context=context_data.get("additional_context"))

        if prompt.startswith("Error:"): # Check for error string from prepare_ai_prompt
            logger.error(f"Failed to prepare prompt for PG ID {pending_gen.id}: {prompt}")
            pending_gen.raw_ai_prompt = prompt # Store the error message as prompt
            pending_gen.status = "error_prompt_generation"
            db.add(pending_gen); db.flush(); db.refresh(pending_gen)
            return pending_gen # Early exit

        pending_gen.raw_ai_prompt = prompt
        pending_gen.status = "pending_api_call" # Update status before API call
        db.add(pending_gen); db.flush(); db.refresh(pending_gen)
        logger.info(f"Prompt prepared for PG ID {pending_gen.id}. Status: {pending_gen.status}")

        # 2. Call AI API
        logger.info(f"Calling OpenAI API for PG ID: {pending_gen.id}")
        raw_response = call_openai_api_sync(prompt) # Using the synchronous version

        if raw_response is None:
            logger.error(f"AI API call failed for PG ID: {pending_gen.id}")
            pending_gen.status = "error_api_call"
            # Store a more structured error in validation_errors_json perhaps
            pending_gen.validation_errors_json = {"error": "API call failed or returned no response."}
        else:
            pending_gen.raw_ai_response = raw_response
            pending_gen.status = "pending_validation"
        db.add(pending_gen); db.flush(); db.refresh(pending_gen)
        logger.info(f"API call completed for PG ID {pending_gen.id}. Status: {pending_gen.status}")


        # 3. Parse and Validate Response (only if API call was successful)
        if pending_gen.status == "pending_validation":
            logger.info(f"Validating AI response for PG ID: {pending_gen.id}")
            # parse_and_validate_ai_response creates its own short-lived session for GuildConfig
            validation_result = parse_and_validate_ai_response(
                raw_ai_output_text=pending_gen.raw_ai_response, # Should not be None here
                guild_id=guild_id,
                expected_schema_type=generation_type
            )
            pending_gen.parsed_data_json = validation_result['raw_json']
            pending_gen.validation_errors_json = validation_result['errors']
            pending_gen.validation_warnings_json = validation_result['warnings']

            if validation_result['errors']:
                logger.warning(f"Validation errors for PG ID {pending_gen.id}: {validation_result['errors']}")
                pending_gen.status = "error_validation"
            else:
                pending_gen.status = "pending_moderation" # Or 'approved' if no moderation step
                logger.info(f"Content for PG ID {pending_gen.id} is '{pending_gen.status}'.")
                if pending_gen.status == "pending_moderation":
                     logger.info(f"GM NOTIFICATION (Placeholder): New content (ID: {pending_gen.id}, Type: {generation_type}) for guild {guild_id} is awaiting moderation.")

        db.add(pending_gen); db.flush(); db.refresh(pending_gen)
        logger.info(f"Validation completed for PG ID {pending_gen.id}. Final Status: {pending_gen.status}")

    except Exception as e:
        logger.error(f"Unhandled error in generation pipeline for PG ID {pending_gen.id}: {e}", exc_info=True)
        try:
            pending_gen.status = "error_processing"
            error_info = {"pipeline_error": str(e), "details": "Check logs for full traceback."}
            # Ensure validation_errors_json is a list or dict as expected by model
            if pending_gen.validation_errors_json and isinstance(pending_gen.validation_errors_json, list):
                 pending_gen.validation_errors_json.append(str(error_info))
            else:
                 pending_gen.validation_errors_json = [str(error_info)]

            db.add(pending_gen); db.flush(); db.refresh(pending_gen)
        except Exception as e_inner: # Catch error during error handling itself
            logger.error(f"Critical error trying to update PendingGeneration status during exception handling for PG ID {pending_gen.id}: {e_inner}", exc_info=True)

    return pending_gen
