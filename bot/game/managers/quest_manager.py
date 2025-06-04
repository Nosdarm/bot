import json
import uuid
import time
import traceback # Keep for potential future use, though not explicitly used in current methods
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.rules.rule_engine import RuleEngine  # Changed path
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.services.consequence_processor import ConsequenceProcessor  # Changed path
    from bot.game.managers.game_log_manager import GameLogManager
    # Add these:
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.services.openai_service import OpenAIService
    from bot.ai.ai_response_validator import AIResponseValidator # Added validator
    from typing import Union # For updated return type

    # The import for 'Quest' model is removed as per instruction 10, assuming dicts are used.

class QuestManager:
    # Instruction 11: Add required class attributes
    required_args_for_load: List[str] = ["guild_id"] # Example, adjust if different logic needed for load_state
    required_args_for_save: List[str] = ["guild_id"] # Example, adjust if different logic needed for save_state
    required_args_for_rebuild: List[str] = ["guild_id"] # Placeholder, actual usage might vary

    # Instruction 2 & 3: Merged __init__ and consolidated cache initializations
    def __init__(
        self,
        db_adapter: Optional["SqliteAdapter"],
        settings: Optional[Dict[str, Any]],
        npc_manager: Optional["NpcManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        consequence_processor: Optional["ConsequenceProcessor"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        # New parameters
        multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None,
        openai_service: Optional["OpenAIService"] = None,
        ai_validator: Optional["AIResponseValidator"] = None # Added validator
    ):
        self._db_adapter = db_adapter
        self._settings = settings if settings else {} # Ensure settings is a dict
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._item_manager = item_manager
        self._rule_engine = rule_engine
        self._relationship_manager = relationship_manager
        self._consequence_processor = consequence_processor
        self._game_log_manager = game_log_manager
        # Store new services
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._openai_service = openai_service
        self._ai_validator = ai_validator # Store validator

        # guild_id -> character_id -> quest_id -> quest_data
        self._active_quests: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # guild_id -> quest_template_id -> quest_template_data
        self._quest_templates: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # guild_id -> character_id -> list of completed quest_ids
        self._completed_quests: Dict[str, Dict[str, List[str]]] = {}
        # guild_id -> set of character_ids with dirty quest data
        self._dirty_quests: Dict[str, Set[str]] = {}
        
        # Cache for all loaded quests (standard and generated)
        # guild_id -> quest_id -> Quest object
        self._all_quests: Dict[str, Dict[str, "Quest"]] = {}

        # Removed _deleted_quest_ids as per instruction 3.

        # Load campaign data from settings
        self.campaign_data: Dict[str, Any] = self._settings.get("campaign_data", {})
        self._default_lang = self._settings.get("default_language", "en")


    # Instruction 4: Corrected load_quest_templates
    def load_quest_templates(self, guild_id: str) -> None:
        """Loads quest templates from campaign data and potentially guild-specific settings."""
        guild_id_str = str(guild_id) # Ensure guild_id is a string for dict keys
        
        # Initialize cache for the guild if it doesn't exist
        self._quest_templates.setdefault(guild_id_str, {})
        guild_templates_cache = self._quest_templates[guild_id_str]

        # Load from campaign_data (e.g., global templates)
        campaign_templates_list = self.campaign_data.get("quest_templates", [])
        
        if isinstance(campaign_templates_list, list):
            for template_dict_orig in campaign_templates_list:
                if isinstance(template_dict_orig, dict) and "id" in template_dict_orig:
                    template_dict = template_dict_orig.copy() # Work on a copy
                    tpl_id = str(template_dict["id"])

                    # Process name_i18n (assuming campaign data might have plain 'name')
                    if 'name_i18n' not in template_dict and 'name' in template_dict:
                        template_dict['name_i18n'] = {self._default_lang: template_dict.pop('name')}
                    elif 'name_i18n' not in template_dict:
                         template_dict['name_i18n'] = {self._default_lang: tpl_id} # Fallback

                    # Derive plain 'name'
                    name_i18n_val = template_dict['name_i18n']
                    if isinstance(name_i18n_val, dict):
                        template_dict['name'] = name_i18n_val.get(self._default_lang, next(iter(name_i18n_val.values()), tpl_id) if name_i18n_val else tpl_id)
                    else: # If name_i18n is somehow not a dict, use it as is or fallback
                        template_dict['name'] = str(name_i18n_val or tpl_id)


                    # Process description_i18n
                    if 'description_i18n' not in template_dict and 'description' in template_dict:
                        template_dict['description_i18n'] = {self._default_lang: template_dict.pop('description')}
                    elif 'description_i18n' not in template_dict:
                        template_dict['description_i18n'] = {self._default_lang: ""} # Fallback

                    # Process stages for i18n (title and description)
                    if 'stages' in template_dict and isinstance(template_dict['stages'], dict):
                        processed_stages = {}
                        for stage_id, stage_data_orig in template_dict['stages'].items():
                            stage_data = stage_data_orig.copy()
                            if 'title_i18n' not in stage_data and 'title' in stage_data:
                                stage_data['title_i18n'] = {self._default_lang: stage_data.pop('title')}
                            if 'description_i18n' not in stage_data and 'description' in stage_data:
                                stage_data['description_i18n'] = {self._default_lang: stage_data.pop('description')}
                            processed_stages[stage_id] = stage_data
                        template_dict['stages'] = processed_stages

                    # Ensure complex fields are dicts/lists if they exist, otherwise initialize
                    for field_key, default_type in [
                        ("prerequisites", list), ("connections", dict),
                        ("rewards", dict), ("npc_involvement", dict), ("data", dict)
                    ]:
                        if field_key in template_dict and not isinstance(template_dict[field_key], default_type):
                            template_dict[field_key] = default_type()
                        elif field_key not in template_dict:
                             template_dict[field_key] = default_type()


                    guild_templates_cache[tpl_id] = template_dict
                else:
                    # Using print for now, consider a logging framework for production
                    print(f"Warning: Invalid quest template format in campaign_data: {template_dict_orig}")
        else:
            print(f"Warning: 'quest_templates' in campaign_data is not a list for guild {guild_id_str}.")

        # Placeholder for loading from guild-specific settings (e.g., DB)
        # This part would typically involve fetching from self._db_adapter
        # For example:
        # guild_specific_db_templates = self._load_guild_specific_templates_from_db(guild_id_str)
        # for tpl_id, template_data in guild_specific_db_templates.items():
        #     guild_templates_cache[str(tpl_id)] = template_data # Ensure tpl_id is string
        
        # print(f"Loaded {len(guild_templates_cache)} quest templates for guild {guild_id_str}.")
        
        loaded_template_count = len(guild_templates_cache)
        print(f"QuestManager: Loaded {loaded_template_count} quest templates from self.campaign_data for guild {guild_id_str}.")
        if loaded_template_count > 0:
            print(f"QuestManager: Example quest templates for guild {guild_id_str}:")
            count = 0
            for template_id, template_data in guild_templates_cache.items():
                if count < 3:
                    # Display derived name and an example from name_i18n
                    derived_name = template_data.get('name', 'N/A')
                    example_i18n_name = template_data.get('name_i18n', {}).get(self._default_lang, 'N/A i18n')
                    print(f"  - ID: {template_id}, Derived Name: {derived_name} (e.g., '{example_i18n_name}'), Type: {template_data.get('type', 'N/A')}")
                    count += 1
                else:
                    break
            if loaded_template_count > 3:
                print(f"  ... and {loaded_template_count - 3} more.")


    # Instruction 5: Ensure single functional version of helper methods
    def get_quest_template(self, guild_id: str, quest_template_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a specific quest template for a guild."""
        guild_id_str = str(guild_id)
        quest_template_id_str = str(quest_template_id)

        if guild_id_str not in self._quest_templates:
            self.load_quest_templates(guild_id_str) # Load if not already loaded for the guild
        
        return self._quest_templates.get(guild_id_str, {}).get(quest_template_id_str)

    # Instruction 6: Quest lifecycle methods compatible with ConsequenceProcessor
    def list_quests_for_character(self, guild_id: str, character_id: str) -> List[Dict[str, Any]]:
        """Lists active quests for a character."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        return list(self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).values())

    async def start_quest(self, guild_id: str, character_id: str, quest_template_id: str, **kwargs: Any) -> Optional[Union[Dict[str, Any], Dict[str, str]]]:
        """
        Starts a new quest for a character.
        If AI generation is used and successful, it saves the content for moderation
        and returns a dict with status 'pending_moderation' and 'request_id'.
        Otherwise, it creates the quest directly and returns the quest data dictionary.
        Returns None on failure.
        """
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_template_id_str = str(quest_template_id)

        ai_generated_quest_data: Optional[Dict[str, Any]] = None
        template_data_from_campaign: Optional[Dict[str, Any]] = None
        trigger_ai_generation = False

        if quest_template_id_str.startswith("AI:"):
            trigger_ai_generation = True
            print(f"QuestManager: AI generation triggered by keyword for quest '{quest_template_id_str}'.")
        else:
            template_data_from_campaign = self.get_quest_template(guild_id_str, quest_template_id_str)
            if not template_data_from_campaign:
                print(f"QuestManager: Quest template '{quest_template_id_str}' not found. Triggering AI generation.")
                trigger_ai_generation = True

        if trigger_ai_generation:
            quest_concept = quest_template_id_str
            if quest_template_id_str.startswith("AI:"):
                quest_concept = quest_template_id_str.replace("AI:", "", 1)

            ai_generated_quest_data = await self.generate_quest_details_from_ai(
                guild_id=guild_id_str,
                quest_idea=quest_concept,
                triggering_entity_id=character_id_str
            )
            if ai_generated_quest_data is None:
                print(f"QuestManager: AI generation failed for concept '{quest_concept}'. Quest creation aborted.")
                return None # AI generation failed

            # --- Moderation Step for AI Generated Quest Data ---
            user_id = kwargs.get('user_id')
            if not user_id:
                print(f"QuestManager: CRITICAL - user_id not found in kwargs for AI quest generation. Aborting moderation save.")
                return None
            
            request_id = str(uuid.uuid4())
            content_type = 'quest'
            try:
                # ai_generated_quest_data is already a dict from the validator
                data_json = json.dumps(ai_generated_quest_data)
                if self._db_adapter:
                    await self._db_adapter.save_pending_moderation_request(
                        request_id, guild_id_str, str(user_id), content_type, data_json
                    )
                    print(f"QuestManager: AI-generated quest data for '{quest_concept}' saved for moderation. Request ID: {request_id}")
                    return {"status": "pending_moderation", "request_id": request_id}
                else:
                    print(f"QuestManager: ERROR - DB adapter not available. Cannot save quest for moderation.")
                    return None # Or handle differently, e.g., proceed without moderation if allowed by policy
            except Exception as e_mod_save:
                print(f"QuestManager: ERROR saving AI quest content for moderation: {e_mod_save}")
                traceback.print_exc()
                return None # Failed to save for moderation

        # --- This part below is now only for NON-AI generated quests (i.e., from template_data_from_campaign) ---
        # Basic check for character existence
        if self._character_manager and not self._character_manager.get_character(guild_id_str, character_id_str): # Changed get_character_by_id to get_character
            print(f"Error: Character '{character_id_str}' not found in guild '{guild_id_str}'. Cannot start quest.")
            return None

        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        
        # Prevent starting the same quest template if it's already active (unless AI generated a unique one)
        # If AI generated the quest, it's unique by its new quest_id, so this check is more for campaign quests.
        if not ai_generated_quest_data and template_data_from_campaign:
            for existing_quest in self._active_quests[guild_id_str][character_id_str].values():
                if existing_quest.get("template_id") == quest_template_id_str:
                    print(f"Warning: Quest (Template: '{quest_template_id_str}') already active for character '{character_id_str}'.")
                    return existing_quest

        quest_id = str(uuid.uuid4())

        # Populate new_quest_data: AI data takes precedence
        if ai_generated_quest_data:
            # Assume ai_generated_quest_data is a dict with keys like 'name', 'description', 'objectives', 'rewards', etc.
            # And that it has been validated by generate_quest_details_from_ai
            new_quest_data = {
                "id": quest_id, # Fresh unique ID
                "template_id": ai_generated_quest_data.get("template_id", f"AI_gen_{quest_id[:8]}"), # Use AI provided or generate one
                "character_id": character_id_str,
                "status": "active",
                "start_time": time.time(),
                "name_i18n": ai_generated_quest_data.get("name_i18n", {"en": "AI Generated Quest"}),
                "description_i18n": ai_generated_quest_data.get("description_i18n", {"en": "An adventure awaits!"}),
                "objectives": ai_generated_quest_data.get("objectives", []), # Expects list of objective dicts
                "rewards_i18n": ai_generated_quest_data.get("rewards_i18n", {}), # Expects dict
                "progress": {}, # Initialize progress
                "data": ai_generated_quest_data.get("data", {}), # Any other custom data from AI
                "giver_entity_id": ai_generated_quest_data.get("giver_entity_id"), # Optional: NPC/entity who gave the quest
                "location_id": ai_generated_quest_data.get("location_id"), # Optional: relevant location
                "is_ai_generated": True,
            }
        elif template_data_from_campaign:
            new_quest_data = {
                "id": quest_id,
                "template_id": quest_template_id_str,
                "character_id": character_id_str,
                "status": "active",
                "start_time": time.time(),
                "name_i18n": template_data_from_campaign.get("name_i18n", {"en": template_data_from_campaign.get("name", "Unnamed Quest")}),
                "description_i18n": template_data_from_campaign.get("description_i18n", {"en": template_data_from_campaign.get("description", "No description.")}),
                "objectives": [obj.copy() for obj in template_data_from_campaign.get("objectives", [])],
                "rewards_i18n": template_data_from_campaign.get("rewards_i18n", {}),
                "progress": {},
                "data": template_data_from_campaign.get("data", {}).copy(),
                "giver_entity_id": template_data_from_campaign.get("giver_entity_id"),
                "location_id": template_data_from_campaign.get("location_id"),
                "is_ai_generated": False,
            }
        else:
            # This case should ideally not be reached if logic is correct (either template found or AI triggered)
            print(f"Critical Error: No template data and no AI data for quest '{quest_template_id_str}'. Aborting.")
            return None
        
        self._active_quests[guild_id_str][character_id_str][quest_id] = new_quest_data
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        
        # Handle consequences for non-AI path
        if self._consequence_processor and template_data_from_campaign: # Ensure this runs only for campaign quests now
            context = self._build_consequence_context(guild_id_str, character_id_str, new_quest_data)
            consequences_value = template_data_from_campaign.get("consequences", {}).get("on_start", [])
            consequences_to_process: List[Dict[str, Any]] = []
            if isinstance(consequences_value, dict):
                consequences_to_process = [consequences_value]
            elif isinstance(consequences_value, list):
                consequences_to_process = consequences_value
            
            if consequences_to_process:
                self._consequence_processor.process_consequences(consequences_to_process, context)
        
        print(f"Quest '{new_quest_data.get('name_i18n', {}).get('en', quest_id)}' (ID: {quest_id}) started from campaign template for char {character_id_str}.")
        return new_quest_data # Return quest data dict for non-AI path

    async def generate_quest_details_from_ai(self, guild_id: str, quest_idea: str, triggering_entity_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Uses MultilingualPromptGenerator, OpenAIService, and AIResponseValidator to generate detailed
        quest data based on an idea or trigger.

        Args:
            guild_id: The ID of the guild.
            quest_idea: A string describing the quest concept or trigger.
            triggering_entity_id: Optional ID of the character/NPC initiating or targeted by the quest, for context.

        Returns:
            A dictionary containing the structured, validated, multilingual quest data from the AI,
            or None if generation or validation fails.
        """
        if not self._multilingual_prompt_generator or not self._openai_service or not self._ai_validator:
            print("QuestManager ERROR: AI services (PromptGen, OpenAI, Validator) not fully available.")
            return None

        print(f"QuestManager: Generating AI details for quest idea '{quest_idea}' in guild {guild_id}.")

        prompt_messages = self._multilingual_prompt_generator.generate_quest_prompt(
            guild_id=guild_id,
            quest_idea=quest_idea,
            triggering_entity_id=triggering_entity_id
            # Potentially add more context like existing NPC/item IDs if validator needs them for this structure
        )

        system_prompt = prompt_messages["system"]
        user_prompt = prompt_messages["user"]

        quest_generation_settings = self._settings.get("quest_generation_ai_settings", {})
        max_tokens = quest_generation_settings.get("max_tokens", 2500)
        temperature = quest_generation_settings.get("temperature", 0.65)

        ai_response = await self._openai_service.generate_structured_multilingual_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )

        if not ai_response or "error" in ai_response or not isinstance(ai_response.get("json_string"), str):
            error_detail = ai_response.get("error") if ai_response else "Unknown error or invalid format from AI service"
            raw_text = ai_response.get("raw_text", "") if ai_response else ""
            print(f"QuestManager ERROR: Failed to generate AI content for quest '{quest_idea}'. Error: {error_detail}")
            if raw_text: print(f"QuestManager: Raw AI response: {raw_text[:500]}...")
            return None

        generated_content_str = ai_response["json_string"]

        # TODO: Determine existing IDs needed for validation context if any for quests.
        # For now, passing empty sets as placeholders.
        validation_result = await self._ai_validator.validate_ai_response(
            ai_json_string=generated_content_str,
            expected_structure="single_quest", # Define this structure in AIResponseValidator
            existing_npc_ids=set(), # Placeholder
            existing_quest_ids=set(), # Placeholder
            existing_item_template_ids=set() # Placeholder
        )

        if validation_result.get('global_errors'):
            print(f"QuestManager ERROR: AI content validation failed with global errors for quest '{quest_idea}': {validation_result['global_errors']}")
            return None

        if not validation_result.get('entities'):
            print(f"QuestManager ERROR: AI content validation produced no entities for quest '{quest_idea}'.")
            return None

        quest_validation_details = validation_result['entities'][0] # Expecting one quest

        if quest_validation_details.get('errors'):
            print(f"QuestManager WARNING: Validation errors for quest '{quest_idea}': {quest_validation_details['errors']}")
        if quest_validation_details.get('notifications'):
            print(f"QuestManager INFO: Validation notifications for quest '{quest_idea}': {quest_validation_details['notifications']}")
        if quest_validation_details.get('requires_moderation'):
            print(f"QuestManager CRITICAL: Quest data for '{quest_idea}' requires moderation. Raw: {generated_content_str[:500]}...")
            return None # Or handle moderation queue

        overall_status = validation_result.get("overall_status")
        if overall_status == "success" or overall_status == "success_with_autocorrections":
            print(f"QuestManager: Successfully validated AI details for quest '{quest_idea}'. Status: {overall_status}")
            return quest_validation_details.get('validated_data') # This is the dict to be used
        else:
            print(f"QuestManager ERROR: Unhandled validation status '{overall_status}' for quest '{quest_idea}'.")
            return None

    def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool:
        """Marks a quest as completed if all objectives are met."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_id_str = str(quest_id)

        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data:
            print(f"Error: Active quest '{quest_id_str}' not found for character '{character_id_str}'.")
            return False

        # Objective completion check (simplified - real logic would be more complex)
        # This needs to be implemented based on how objectives and progress are structured.
        # For now, assume a function self._are_all_objectives_complete(quest_data) exists.
        if not self._are_all_objectives_complete(quest_data): # Placeholder for actual check
            print(f"Quest '{quest_id_str}' cannot be completed: Not all objectives met.")
            return False

        quest_data["status"] = "completed"
        quest_data["completion_time"] = time.time()
        
        template = self.get_quest_template(guild_id_str, quest_data["template_id"])

        if self._consequence_processor and template:
            context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
            consequences_value = template.get("consequences", {}).get("on_complete", [])
            consequences_to_process: List[Dict[str, Any]] = []
            if isinstance(consequences_value, dict):
                consequences_to_process = [consequences_value]
            elif isinstance(consequences_value, list):
                consequences_to_process = consequences_value

            if consequences_to_process:
                self._consequence_processor.process_consequences(consequences_to_process, context)

        self._completed_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, []).append(quest_id_str)
        del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests[guild_id_str][character_id_str]: # Cleanup if no more active quests for char
            del self._active_quests[guild_id_str][character_id_str]
        
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        # print(f"Quest '{quest_id_str}' completed for character '{character_id_str}'.")
        return True

    def fail_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool:
        """Marks a quest as failed."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_id_str = str(quest_id)

        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data:
            print(f"Error: Active quest '{quest_id_str}' not found for character '{character_id_str}'.")
            return False

        quest_data["status"] = "failed"
        quest_data["failure_time"] = time.time()
        
        template = self.get_quest_template(guild_id_str, quest_data["template_id"])

        if self._consequence_processor and template:
            context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
            consequences_value = template.get("consequences", {}).get("on_fail", [])
            consequences_to_process: List[Dict[str, Any]] = []
            if isinstance(consequences_value, dict):
                consequences_to_process = [consequences_value]
            elif isinstance(consequences_value, list):
                consequences_to_process = consequences_value
            
            if consequences_to_process:
                self._consequence_processor.process_consequences(consequences_to_process, context)
        
        del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests[guild_id_str][character_id_str]: # Cleanup
            del self._active_quests[guild_id_str][character_id_str]
            
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        # print(f"Quest '{quest_id_str}' failed for character '{character_id_str}'.")
        return True

    # Instruction 12: load_state and save_state consistent with dict structure
    def load_state(self, guild_id: str, character_id: str, data: List[Dict[str, Any]]) -> None:
        """
        Loads active quests for a specific character from a list of quest data objects.
        This is typically called when loading a character's state.
        The general loading of all quests for a guild should happen in a separate method like _load_all_quests_from_db.
        """
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)

        # Ensure the _all_quests cache for the guild is populated first.
        # This is a simplified approach; ideally, GameManager orchestrates loading.
        if guild_id_str not in self._all_quests:
            # This would ideally be an async call orchestrated by GameManager
            # For now, this highlights a dependency. We'll assume _load_all_quests_from_db
            # is called appropriately during the game's loading sequence.
            print(f"QuestManager: Warning - _load_all_quests_from_db should be called before loading character-specific quest states for guild {guild_id_str}.")
            # Attempt to load them now if not loaded. This might be problematic if called from sync context.
            # asyncio.run(self._load_all_quests_from_db(guild_id_str)) # Avoid asyncio.run here.

        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        active_quests_for_char = self._active_quests[guild_id_str][character_id_str]
        
        for quest_data_item_id in data: # Assuming 'data' is a list of quest IDs or simple quest state dicts
            quest_id = None
            if isinstance(quest_data_item_id, dict): # If it's a dict, assume it has an 'id'
                quest_id = quest_data_item_id.get("id")
            elif isinstance(quest_data_item_id, str): # If it's just an ID string
                quest_id = quest_data_item_id

            if quest_id:
                # Attempt to find the full quest object from the _all_quests cache
                full_quest_obj = self._all_quests.get(guild_id_str, {}).get(str(quest_id))
                if full_quest_obj:
                    # Store the actual Quest object or its dict representation for active quests
                    # Storing dicts for active_quests to match current save_state return type
                    active_quests_for_char[str(quest_id)] = full_quest_obj.to_dict()
                    # If data contained more state (like progress), merge it here.
                    if isinstance(quest_data_item_id, dict):
                        active_quests_for_char[str(quest_id)].update(quest_data_item_id)
                else:
                    print(f"Warning: Quest with ID '{quest_id}' not found in _all_quests cache for guild '{guild_id_str}' during char load.")
            else:
                print(f"Warning: Quest data without ID found during load_state for char '{character_id_str}'")


    async def _load_all_quests_from_db(self, guild_id: str) -> None:
        """Loads all standard and generated quests for a guild from the database."""
        from bot.game.models.quest import Quest # Local import for Quest model

        guild_id_str = str(guild_id)
        print(f"QuestManager: Loading all quests for guild {guild_id_str} from DB...")
        if self._db_adapter is None:
            print("QuestManager: DB adapter not available. Cannot load quests.")
            return

        self._all_quests[guild_id_str] = {}
        guild_quest_cache = self._all_quests[guild_id_str]

        # Load standard quests from 'quests' table
        try:
            sql_standard = """
                SELECT id, name_i18n, description_i18n, status, influence_level,
                       prerequisites, connections, stages, rewards, npc_involvement, guild_id
                FROM quests WHERE guild_id = ?
            """
            rows = await self._db_adapter.fetchall(sql_standard, (guild_id_str,))
            for row_data in rows:
                data = dict(row_data)
                data['is_ai_generated'] = False
                # Parse main JSON strings from DB before passing to Quest.from_dict
                # Quest.from_dict expects these to be Python objects or specific *_json_str fields
                for field in ['name_i18n', 'description_i18n', 'prerequisites', 'connections', 'stages', 'rewards', 'npc_involvement']:
                    if field in data and isinstance(data[field], str):
                        try:
                            data[field] = json.loads(data[field])
                        except json.JSONDecodeError:
                            print(f"Warning: Invalid JSON for field '{field}' in quest ID '{data.get('id')}'. Defaulting.")
                            data[field] = {} if field not in ['prerequisites'] else []

                quest_obj = Quest.from_dict(data)
                guild_quest_cache[quest_obj.id] = quest_obj
        except Exception as e:
            print(f"Error loading standard quests for guild {guild_id_str}: {e}")
            traceback.print_exc()

        # Load generated quests from 'generated_quests' table
        try:
            sql_generated = """
                SELECT id, title_i18n, description_i18n, status, suggested_level,
                       stages_json, rewards_json, prerequisites_json, consequences_json,
                       quest_giver_npc_id, ai_prompt_context_json, guild_id
                FROM generated_quests WHERE guild_id = ?
            """ # Removed 'is_moderated' as it's not in schema v20
            rows_gen = await self._db_adapter.fetchall(sql_generated, (guild_id_str,))
            for row_data_gen in rows_gen:
                data_gen = dict(row_data_gen)
                data_gen['is_ai_generated'] = True

                # Map title_i18n to name_i18n for the model
                if 'title_i18n' in data_gen:
                    data_gen['name_i18n'] = data_gen.pop('title_i18n')

                # Pass JSON strings directly to from_dict via *_json_str keys
                # Quest.from_dict is updated to handle these.
                for json_field_db, model_json_str_field in {
                    "stages_json": "stages_json_str", "rewards_json": "rewards_json_str",
                    "prerequisites_json": "prerequisites_json_str",
                    "consequences_json": "consequences_json_str",
                    "ai_prompt_context_json": "ai_prompt_context_json_str"
                }.items():
                    if json_field_db in data_gen:
                        data_gen[model_json_str_field] = data_gen.pop(json_field_db)

                # Parse name_i18n and description_i18n from string here if they are strings
                for field in ['name_i18n', 'description_i18n']:
                    if field in data_gen and isinstance(data_gen[field], str):
                        try:
                            data_gen[field] = json.loads(data_gen[field])
                        except json.JSONDecodeError:
                            print(f"Warning: Invalid JSON for field '{field}' in generated quest ID '{data_gen.get('id')}'. Defaulting.")
                            data_gen[field] = {}

                quest_obj = Quest.from_dict(data_gen)

                # After creating quest_obj, parse the *_json_str fields into actual data attributes
                # This responsibility is shifted to the manager after object creation.
                if quest_obj.stages_json_str:
                    try: quest_obj.stages = json.loads(quest_obj.stages_json_str)
                    except json.JSONDecodeError: print(f"Error parsing stages_json for gen_quest {quest_obj.id}"); quest_obj.stages = {}
                if quest_obj.rewards_json_str:
                    try: quest_obj.rewards = json.loads(quest_obj.rewards_json_str)
                    except json.JSONDecodeError: print(f"Error parsing rewards_json for gen_quest {quest_obj.id}"); quest_obj.rewards = {}
                if quest_obj.prerequisites_json_str: # This should result in List[Dict] or similar for generated quests
                    try: quest_obj.prerequisites = json.loads(quest_obj.prerequisites_json_str)
                    except json.JSONDecodeError: print(f"Error parsing prerequisites_json for gen_quest {quest_obj.id}"); quest_obj.prerequisites = []
                if quest_obj.consequences_json_str:
                    try: quest_obj.consequences = json.loads(quest_obj.consequences_json_str)
                    except json.JSONDecodeError: print(f"Error parsing consequences_json for gen_quest {quest_obj.id}"); quest_obj.consequences = {}
                # ai_prompt_context_data can be handled similarly if needed as a dict on the object

                guild_quest_cache[quest_obj.id] = quest_obj
        except Exception as e:
            print(f"Error loading generated quests for guild {guild_id_str}: {e}")
            traceback.print_exc()

        print(f"QuestManager: Loaded {len(guild_quest_cache)} total quests for guild {guild_id_str}.")


    async def save_state(self, guild_id: str, character_id: str) -> List[Dict[str, Any]]:
        """Saves active quests for a character. Returns a list of quest data objects for character state persistence."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)

        character_quests_map = self._active_quests.get(guild_id_str, {}).get(character_id_str, {})
        
        # If serialization to JSON strings for specific fields is needed for DB storage:
        # serialized_quests = []
        # for quest_data in character_quests_map.values():
        #     data_copy = quest_data.copy()
        #     if "progress" in data_copy and isinstance(data_copy["progress"], dict):
        #         data_copy["progress"] = json.dumps(data_copy["progress"]) # Serialize 'progress' to JSON string
        #     serialized_quests.append(data_copy)
        # return serialized_quests
        
        # The user's version of this file might have an `await self._db_adapter.execute_many(...)` call here.
        # This version of the code does not, so we are only making the function async
        # to satisfy the Pylance error reported by the user.
        return list(character_quests_map.values())

    # Helper methods
    def _build_consequence_context(self, guild_id: str, character_id: str, quest_data: Dict[str, Any]) -> Dict[str, Any]:
        """Builds the context dictionary for consequence processing."""
        context = {
            "guild_id": guild_id,
            "character_id": character_id,
            "quest": quest_data,
            # Pass managers if they are available and needed by consequences
        }
        if self._npc_manager: context["npc_manager"] = self._npc_manager
        if self._item_manager: context["item_manager"] = self._item_manager
        if self._character_manager: context["character_manager"] = self._character_manager
        if self._relationship_manager: context["relationship_manager"] = self._relationship_manager
        # rule_engine is not typically part of context, but used by ConsequenceProcessor itself
        return context

    def _are_all_objectives_complete(self, quest_data: Dict[str, Any]) -> bool:
        """
        Checks if all objectives for the quest are complete.
        This is a placeholder and needs to be implemented based on objective structure.
        Example:
        for objective in quest_data.get("objectives", []):
            obj_id = objective.get("id")
            obj_type = objective.get("type")
            required_count = objective.get("count")
            
            current_progress = quest_data.get("progress", {}).get(obj_id)

            if obj_type == "kill" or obj_type == "collect":
                if not isinstance(current_progress, int) or current_progress < required_count:
                    return False
            # Add checks for other objective types (e.g., "reach_location", "talk_to_npc")
            else: # Unknown objective type
                print(f"Warning: Unknown objective type '{obj_type}' for objective '{obj_id}' in quest '{quest_data.get('id')}'.")
                return False 
        return True
        """
        # Simplified placeholder: assume true for now.
        # In a real implementation, iterate through quest_data["objectives"]
        # and check against quest_data["progress"].
        print(f"Placeholder: _are_all_objectives_complete for quest {quest_data.get('id')} returning True.")
        return True

    def update_quest_progress(self, guild_id: str, character_id: str, quest_id: str, objective_id: str, progress_update: Any) -> bool:
        """
        Updates the progress of a specific objective within an active quest.
        `progress_update` could be an increment value, a boolean flag, or other data.
        This method should also check for quest completion after progress update.
        """
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_id_str = str(quest_id)
        objective_id_str = str(objective_id)

        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data or quest_data.get("status") != "active":
            print(f"Error: Active quest '{quest_id_str}' not found or not active for progress update.")
            return False

        # Find the objective to update
        objective_to_update = None
        for obj in quest_data.get("objectives", []):
            if obj.get("id") == objective_id_str:
                objective_to_update = obj
                break
        
        if not objective_to_update:
            print(f"Error: Objective '{objective_id_str}' not found in quest '{quest_id_str}'.")
            return False

        # Update progress (example for count-based objectives)
        current_progress = quest_data.get("progress", {}).get(objective_id_str, 0)
        obj_type = objective_to_update.get("type")

        if obj_type in ["kill", "collect"]: # Assuming progress_update is an increment for these
            if not isinstance(current_progress, (int, float)): current_progress = 0
            if isinstance(progress_update, (int, float)):
                 new_progress = current_progress + progress_update
            else: # If progress_update is not a number, assume it's the new value
                new_progress = progress_update
        else: # For other types, progress_update might be a boolean or specific value
            new_progress = progress_update 
            
        quest_data.setdefault("progress", {})[objective_id_str] = new_progress
        # print(f"Progress for objective '{objective_id_str}' in quest '{quest_id_str}' updated to {new_progress}.")
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)

        # Check for quest completion
        if self._are_all_objectives_complete(quest_data):
            self.complete_quest(guild_id_str, character_id_str, quest_id_str)
            # complete_quest handles consequences and state changes

        return True


    def get_dirty_character_ids(self, guild_id: str) -> Set[str]:
        """Gets set of character IDs with changed quest states for a guild."""
        return self._dirty_quests.get(str(guild_id), set()).copy() # Return a copy

    def clear_dirty_character_ids(self, guild_id: str) -> None:
        """Clears the set of dirty character IDs for a guild."""
        if str(guild_id) in self._dirty_quests:
            self._dirty_quests[str(guild_id)].clear()
    
    # Example of how guild-specific templates might be loaded if they were in a DB (conceptual)
    # def _load_guild_specific_templates_from_db(self, guild_id: str) -> Dict[str, Any]:
    #     if not self._db_adapter:
    #         return {}
    #     # This is a conceptual example. Actual table and column names would vary.
    #     # Assumes a table 'guild_quest_templates' with 'guild_id', 'template_id', 'template_data_json'
    #     try:
    #         rows = self._db_adapter.fetchall_sync(
    #             "SELECT template_id, template_data_json FROM guild_quest_templates WHERE guild_id = ?",
    #             (guild_id,)
    #         )
    #         templates = {}
    #         for row in rows:
    #             try:
    #                 template_data = json.loads(row[1]) # template_data_json column
    #                 templates[str(row[0])] = template_data # template_id column
    #             except json.JSONDecodeError:
    #                 print(f"Error decoding quest template JSON for template_id '{row[0]}' in guild '{guild_id}'.")
    #         return templates
    #     except Exception as e: # Catch database errors or other issues
    #         print(f"Error loading guild-specific quest templates from DB for guild '{guild_id}': {e}")

    #         # Consider logging the full traceback using traceback.format_exc()
    #         # Consider logging the full traceback using traceback.format_exc()
    #         return {}

    async def save_generated_quest(self, quest: "Quest") -> bool:
        """Saves an AI-generated quest to the 'generated_quests' table."""
        from bot.game.models.quest import Quest # Local import
        if not isinstance(quest, Quest) or not quest.is_ai_generated:
            print("QuestManager: save_generated_quest called with invalid or non-AI quest object.")
            return False

        if self._db_adapter is None:
            print("QuestManager: DB adapter not available. Cannot save generated quest.")
            return False

        try:
            # Prepare data for DB
            # title_i18n in DB maps to name_i18n in Quest model
            title_i18n_json = json.dumps(quest.name_i18n or {})
            description_i18n_json = json.dumps(quest.description_i18n or {})

            # stages_json: quest.stages should be a Python dict/list
            stages_json = json.dumps(quest.stages or {})
            rewards_json = json.dumps(quest.rewards or {})

            # prerequisites for generated quests might be more complex than List[str]
            # For now, assume it's a structure that can be dumped to JSON.
            # The Quest model stores it in self.prerequisites.
            prerequisites_json = json.dumps(quest.prerequisites or [])

            # consequences for generated quests
            consequences_json = json.dumps(quest.consequences or {})

            # ai_prompt_context_json
            # The Quest model stores this as ai_prompt_context_json_str
            # If it's already a string, use it. If it was parsed to a dict, dump it.
            ai_context_to_dump = {}
            if hasattr(quest, 'ai_prompt_context_data') and isinstance(getattr(quest, 'ai_prompt_context_data'), dict):
                ai_context_to_dump = getattr(quest, 'ai_prompt_context_data')
            elif quest.ai_prompt_context_json_str: # If it was loaded as a string and not parsed
                try:
                    ai_context_to_dump = json.loads(quest.ai_prompt_context_json_str)
                except json.JSONDecodeError:
                    print(f"Warning: Invalid JSON in ai_prompt_context_json_str for quest {quest.id}. Saving as empty.")
            ai_prompt_context_json = json.dumps(ai_context_to_dump)

            suggested_level_val = 0 # Default
            if hasattr(quest, 'suggested_level') and isinstance(getattr(quest, 'suggested_level'), int):
                suggested_level_val = getattr(quest, 'suggested_level')
            elif isinstance(quest.influence_level, str) and quest.influence_level.isdigit():
                try:
                    suggested_level_val = int(quest.influence_level) # Try to use influence_level if it's numeric
                except ValueError:
                    pass # Keep default if not convertible

            quest_giver_npc_id = quest.npc_involvement.get('giver') if isinstance(quest.npc_involvement, dict) else None


            sql = """
                INSERT OR REPLACE INTO generated_quests (
                    id, guild_id, title_i18n, description_i18n, status,
                    suggested_level, stages_json, rewards_json, prerequisites_json,
                    consequences_json, quest_giver_npc_id, ai_prompt_context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """ # 12 columns
            params = (
                quest.id, quest.guild_id, title_i18n_json, description_i18n_json,
                quest.status, suggested_level_val, stages_json, rewards_json,
                prerequisites_json, consequences_json, quest_giver_npc_id,
                ai_prompt_context_json
            )
            await self._db_adapter.execute(sql, params)
            print(f"QuestManager: Successfully saved generated quest {quest.id} to DB.")
            return True
        except Exception as e:
            print(f"Error saving generated quest {quest.id}: {e}")
            traceback.print_exc()
            return False

    async def start_quest_from_moderated_data(self, guild_id: str, character_id: str, quest_data: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Starts a new quest for a character using already validated and approved moderated data.
        This now also saves the quest to the generated_quests table.
        This now also saves the quest to the generated_quests table.
        """
        from bot.game.models.quest import Quest # Local import for Quest model
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)

        print(f"QuestManager: Starting quest from moderated data for character {character_id_str} in guild {guild_id_str}.")

        if not self._character_manager or not self._character_manager.get_character(guild_id_str, character_id_str):
            print(f"Error: Character '{character_id_str}' not found in guild '{guild_id_str}'. Cannot start quest from moderated data.")
            return None

        # Create a Quest object from the moderated data
        # Ensure quest_data (which is validated AI output) has all necessary fields for Quest.from_dict
        # or that Quest.from_dict has suitable defaults.
        quest_data['guild_id'] = guild_id_str # Ensure guild_id is in the data for the model
        quest_data['is_ai_generated'] = True   # Mark as AI-generated

        # If 'id' is not in quest_data or is a placeholder, Quest.from_dict will generate one.
        # If 'title_i18n' is in quest_data, Quest.from_dict will map it to name_i18n.
        quest_obj = Quest.from_dict(quest_data)

        # Save the AI-generated quest to the 'generated_quests' table
        save_success = await self.save_generated_quest(quest_obj)
        if not save_success:
            print(f"QuestManager: Failed to save generated quest {quest_obj.id} to DB. Aborting start.")
            return None

        # Add to _all_quests cache (if not already there due to loading, though saving implies new)
        self._all_quests.setdefault(guild_id_str, {})[quest_obj.id] = quest_obj

        # Now, handle starting the quest for the character (active quests)
        # Convert Quest object to dict for storing in _active_quests, to match existing structure.
        active_quest_data = quest_obj.to_dict()
        # Ensure character_id and start_time are set for the active quest instance
        active_quest_data["character_id"] = character_id_str
        active_quest_data["start_time"] = time.time()
        active_quest_data["status"] = "active" # Ensure it's active
        # Ensure progress is initialized for the active instance if not already
        active_quest_data.setdefault("progress", {})


        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})[quest_obj.id] = active_quest_data
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str) # Mark character's quests dirty

        print(f"Quest '{quest_obj.name}' (ID: {quest_obj.id}) started from moderated data for char {character_id_str}.")

        # Handle 'on_start' consequences if defined in the quest data (using quest_obj for context)
        if self._consequence_processor:
            # Build context using the quest object
            consequences_context_data = quest_obj.to_dict() # Get full data from quest object
            consequences_context_data["character_id"] = character_id_str # Ensure char_id is in context

            built_context = self._build_consequence_context(guild_id_str, character_id_str, consequences_context_data)
            built_context.update(context) # Merge the broader command context (e.g., send_message callback)

            # Consequences might be in quest_obj.consequences (parsed) or directly in quest_data from moderation
            consequences_to_check = quest_obj.consequences or quest_data.get("consequences", {})

            consequences_value = consequences_to_check.get("on_start", [])
            consequences_to_process: List[Dict[str, Any]] = []
            if isinstance(consequences_value, dict):
                consequences_to_process = [consequences_value]
            elif isinstance(consequences_value, list):
                consequences_to_process = consequences_value

            if consequences_to_process:
                self._consequence_processor.process_consequences(consequences_to_process, built_context)

        return active_quest_data # Return the active quest data as a dict


# No __main__ block in the final library file unless specifically for testing within this file.
# For this refactoring task, it's better to remove it if it was part of the original conflicted file.
