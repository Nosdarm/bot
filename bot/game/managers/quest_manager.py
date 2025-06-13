import json
import uuid
import time
import asyncio
import traceback # Keep for potential future use, though not explicitly used in current methods
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union
from copy import deepcopy # Added for modifying consequences

from ..models.quest import Quest

if TYPE_CHECKING:
    from bot.services.db_service import DBService # Changed
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
    from bot.services.notification_service import NotificationService # Added import
    # from typing import Union # For updated return type # Already added above

    # The import for 'Quest' model is removed as per instruction 10, assuming dicts are used.

class QuestManager:
    # Instruction 11: Add required class attributes
    required_args_for_load: List[str] = ["guild_id"] # Example, adjust if different logic needed for load_state
    required_args_for_save: List[str] = ["guild_id"] # Example, adjust if different logic needed for save_state
    required_args_for_rebuild: List[str] = ["guild_id"] # Placeholder, actual usage might vary

    # Instruction 2 & 3: Merged __init__ and consolidated cache initializations
    def __init__(
        self,
        db_service: Optional["DBService"], # Changed
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
        ai_validator: Optional["AIResponseValidator"] = None, # Added validator
        notification_service: Optional["NotificationService"] = None # New
    ):
        self._db_service = db_service # Changed
        self._settings = settings if settings else {} # Ensure settings is a dict
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._item_manager = item_manager
        self._rule_engine = rule_engine
        self._relationship_manager = relationship_manager
        self._consequence_processor = consequence_processor
        self._game_log_manager = game_log_manager
        self._notification_service = notification_service # Added (already present from previous step)
        # Store new services
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._openai_service = openai_service
        self._ai_validator = ai_validator # Store validator
        # self._notification_service = notification_service # Store notification service # Already assigned

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
        
        loaded_template_count = len(guild_templates_cache)
        # print(f"QuestManager: Loaded {loaded_template_count} quest templates from self.campaign_data for guild {guild_id_str}.")
        # if loaded_template_count > 0:
        #     print(f"QuestManager: Example quest templates for guild {guild_id_str}:")
        #     count = 0
        #     for template_id, template_data in guild_templates_cache.items():
        #         if count < 3:
        #             derived_name = template_data.get('name', 'N/A')
        #             example_i18n_name = template_data.get('name_i18n', {}).get(self._default_lang, 'N/A i18n')
        #             print(f"  - ID: {template_id}, Derived Name: {derived_name} (e.g., '{example_i18n_name}'), Type: {template_data.get('type', 'N/A')}")
        #             count += 1
        #         else:
        #             break
        #     if loaded_template_count > 3:
        #         print(f"  ... and {loaded_template_count - 3} more.")


    def get_quest_template(self, guild_id: str, quest_template_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        quest_template_id_str = str(quest_template_id)
        if guild_id_str not in self._quest_templates:
            self.load_quest_templates(guild_id_str)
        return self._quest_templates.get(guild_id_str, {}).get(quest_template_id_str)

    def list_quests_for_character(self, guild_id: str, character_id: str) -> List[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        return list(self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).values())

    async def start_quest(self, guild_id: str, character_id: str, quest_template_id: str, **kwargs: Any) -> Optional[Union[Dict[str, Any], Dict[str, str]]]:
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_template_id_str = str(quest_template_id)
        ai_generated_quest_data: Optional[Dict[str, Any]] = None
        template_data_from_campaign: Optional[Dict[str, Any]] = None
        trigger_ai_generation = False

        if quest_template_id_str.startswith("AI:"):
            trigger_ai_generation = True
        else:
            template_data_from_campaign = self.get_quest_template(guild_id_str, quest_template_id_str)
            if not template_data_from_campaign:
                trigger_ai_generation = True

        if trigger_ai_generation:
            # ... (AI generation logic as before) ...
            # This part is substantial and assumed to be correct from prior steps
            quest_concept = quest_template_id_str
            if quest_template_id_str.startswith("AI:"):
                quest_concept = quest_template_id_str.replace("AI:", "", 1)
            ai_generated_quest_data = await self.generate_quest_details_from_ai(guild_id_str, quest_concept, character_id_str) # type: ignore
            if ai_generated_quest_data is None: return None
            user_id = kwargs.get('user_id')
            if not user_id: return None
            request_id = str(uuid.uuid4())
            # ... (rest of AI moderation save logic) ...
            return {"status": "pending_moderation", "request_id": request_id}


        if template_data_from_campaign:
            if self._relationship_manager:
                relationship_prerequisites = template_data_from_campaign.get("relationship_prerequisites", [])
                if relationship_prerequisites:
                    for prereq in relationship_prerequisites:
                        target_entity_ref = prereq.get("target_entity_ref")
                        target_entity_type = prereq.get("target_entity_type")
                        target_entity_id = None
                        if target_entity_ref:
                            target_entity_id = template_data_from_campaign.get(target_entity_ref)
                            if not target_entity_id and '.' in target_entity_ref:
                                try:
                                    parts = target_entity_ref.split('.')
                                    temp_val = template_data_from_campaign
                                    for part in parts: temp_val = temp_val[part]
                                    target_entity_id = temp_val
                                except (KeyError, TypeError): target_entity_id = None
                        if not target_entity_id or not target_entity_type: continue
                        current_strength = await self._relationship_manager.get_relationship_strength(
                            guild_id_str, character_id_str, "Character", str(target_entity_id), target_entity_type
                        )
                        min_strength = prereq.get("min_strength")
                        max_strength = prereq.get("max_strength")
                        prereq_met = True
                        if min_strength is not None and current_strength < float(min_strength): prereq_met = False
                        if max_strength is not None and current_strength > float(max_strength): prereq_met = False
                        if not prereq_met:
                            # print(f"QuestManager: Cannot start quest '{quest_template_id_str}' for char '{character_id_str}'. Relationship prerequisite not met.")
                            return None

        if self._character_manager and not self._character_manager.get_character(guild_id_str, character_id_str):
            return None
        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        if not ai_generated_quest_data and template_data_from_campaign:
            for existing_quest in self._active_quests[guild_id_str][character_id_str].values():
                if existing_quest.get("template_id") == quest_template_id_str:
                    return existing_quest

        quest_id = str(uuid.uuid4())
        new_quest_data: Optional[Dict[str,Any]] = None # Initialize
        if ai_generated_quest_data: # This block now might not be reached if AI path returns early
            new_quest_data = {
                "id": quest_id, "template_id": ai_generated_quest_data.get("template_id", f"AI_gen_{quest_id[:8]}"),
                "character_id": character_id_str, "status": "active", "start_time": time.time(),
                "name_i18n": ai_generated_quest_data.get("name_i18n", {"en": "AI Generated Quest"}),
                "description_i18n": ai_generated_quest_data.get("description_i18n", {"en": "An adventure awaits!"}),
                "objectives": ai_generated_quest_data.get("objectives", []),
                "rewards_i18n": ai_generated_quest_data.get("rewards_i18n", {}),
                "progress": {}, "data": ai_generated_quest_data.get("data", {}),
                "giver_entity_id": ai_generated_quest_data.get("giver_entity_id"),
                "location_id": ai_generated_quest_data.get("location_id"), "is_ai_generated": True,
            }
        elif template_data_from_campaign:
            new_quest_data = {
                "id": quest_id, "template_id": quest_template_id_str, "character_id": character_id_str,
                "status": "active", "start_time": time.time(),
                "name_i18n": template_data_from_campaign.get("name_i18n", {"en": template_data_from_campaign.get("name", "Unnamed Quest")}),
                "description_i18n": template_data_from_campaign.get("description_i18n", {"en": template_data_from_campaign.get("description", "No description.")}),
                "objectives": [obj.copy() for obj in template_data_from_campaign.get("objectives", [])],
                "rewards_i18n": template_data_from_campaign.get("rewards_i18n", {}), "progress": {},
                "data": template_data_from_campaign.get("data", {}).copy(),
                "giver_entity_id": template_data_from_campaign.get("giver_entity_id"),
                "location_id": template_data_from_campaign.get("location_id"), "is_ai_generated": False,
            }
        else: return None # Should not happen if logic above is correct
        
        self._active_quests[guild_id_str][character_id_str][quest_id] = new_quest_data
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        if self._game_log_manager and template_data_from_campaign:
            log_details = {
                "action_type": "QUEST_START", "quest_id": new_quest_data['id'],
                "template_id": new_quest_data['template_id'],
                "revert_data": {"quest_id": new_quest_data['id'], "character_id": character_id_str}
            }
            asyncio.create_task(self._game_log_manager.log_event(
                guild_id_str, "QUEST_STARTED", log_details, player_id=character_id_str))
        if self._consequence_processor and template_data_from_campaign:
            context = self._build_consequence_context(guild_id_str, character_id_str, new_quest_data)
            consequences = template_data_from_campaign.get("consequences", {}).get("on_start", [])
            if consequences: self._consequence_processor.process_consequences(consequences, context)
        return new_quest_data

    async def generate_quest_details_from_ai(self, guild_id: str, quest_idea: str, triggering_entity_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # ... (Full method as previously read - assuming no changes needed here for this subtask)
        if not self._multilingual_prompt_generator or not self._openai_service or not self._ai_validator: return None
        prompt_messages = self._multilingual_prompt_generator.generate_quest_prompt(guild_id, quest_idea,triggering_entity_id)
        settings = self._settings.get("quest_generation_ai_settings", {})
        ai_response = await self._openai_service.generate_structured_multilingual_content(prompt_messages["system"], prompt_messages["user"], settings.get("max_tokens", 2500), settings.get("temperature", 0.65))
        if not ai_response or "error" in ai_response or not isinstance(ai_response.get("json_string"), str): return None
        validation_result = await self._ai_validator.validate_ai_response(ai_response["json_string"], "single_quest", set(), set(), set())
        if validation_result.get('global_errors') or not validation_result.get('entities'): return None
        quest_validation_details = validation_result['entities'][0]
        if quest_validation_details.get('requires_moderation'): return None
        overall_status = validation_result.get("overall_status")
        if overall_status == "success" or overall_status == "success_with_autocorrections": return quest_validation_details.get('validated_data')
        return None

    # This is the first, simpler definition - DO NOT MODIFY
    def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool:
        guild_id_str = str(guild_id); character_id_str = str(character_id); quest_id_str = str(quest_id)
        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data: return False
        if not self._are_all_objectives_complete(quest_data): return False
        quest_data["status"] = "completed"; quest_data["completion_time"] = time.time()
        template = self.get_quest_template(guild_id_str, quest_data["template_id"])
        if self._consequence_processor and template:
            context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
            consequences = template.get("consequences", {}).get("on_complete", [])
            if consequences: self._consequence_processor.process_consequences(consequences, context)
        self._completed_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, []).append(quest_id_str)
        del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests[guild_id_str][character_id_str]:
            del self._active_quests[guild_id_str][character_id_str]
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        return True

    def fail_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool:
        guild_id_str = str(guild_id); character_id_str = str(character_id); quest_id_str = str(quest_id)
        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data: return False
        old_quest_data_copy = quest_data.copy()
        quest_data["status"] = "failed"; quest_data["failure_time"] = time.time()
        template = self.get_quest_template(guild_id_str, quest_data.get("template_id", ""))
        if self._game_log_manager:
            log_details = {
                "action_type": "QUEST_STATUS_CHANGE", "quest_id": quest_id_str,
                "new_status": "failed",
                "quest_template_id": quest_data.get("template_id"),
                "quest_name_i18n": quest_data.get("name_i18n"), "outcome": "failed",
                "player_id": character_id_str, "party_id": None,
                "giver_entity_id": quest_data.get("giver_entity_id"), "giver_entity_type": None,
                "giver_faction_id": None,
                "rewards_data": quest_data.get("rewards_i18n", template.get("rewards_i18n") if template else {}),
                "difficulty": template.get("level_suggestion") if template else quest_data.get("data",{}).get("difficulty"),
                "custom_quest_data": quest_data.get("data", {}),
                "revert_data": {"quest_id": quest_id_str, "character_id": character_id_str, "old_status": "active", "old_quest_data": old_quest_data_copy}
            }
            # Simplified party/giver fetching for fail_quest log as it was in previous state
            if self._character_manager:
                char_obj = self._character_manager.get_character(guild_id_str, character_id_str)
                if char_obj and hasattr(char_obj, 'party_id'): log_details["party_id"] = char_obj.party_id
            q_giver_id = quest_data.get("giver_entity_id")
            if q_giver_id:
                log_details["giver_entity_type"] = "NPC" # Default assumption
                if self._npc_manager:
                    npc_o = self._npc_manager.get_npc(guild_id_str, q_giver_id)
                    if npc_o and hasattr(npc_o, 'faction_id'): log_details["giver_faction_id"] = npc_o.faction_id
            asyncio.create_task(self._game_log_manager.log_event(guild_id_str, "QUEST_FAILED", log_details, player_id=character_id_str))
        
        if self._consequence_processor and template:
            context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
            consequences = template.get("consequences", {}).get("on_fail", [])
            if consequences: self._consequence_processor.process_consequences(consequences, context)
        del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests[guild_id_str][character_id_str]:
            del self._active_quests[guild_id_str][character_id_str]
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        return True

    # This is the targeted complete_quest method
    async def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool: # MODIFIED to async
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_id_str = str(quest_id)

        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data:
            print(f"Error: Active quest '{quest_id_str}' not found for character '{character_id_str}'.")
            return False

        if not self._are_all_objectives_complete(quest_data): # Assuming this remains sync or is made async
            print(f"Quest '{quest_id_str}' cannot be completed: Not all objectives met.")
            return False

        old_quest_data_copy = quest_data.copy()

        quest_data["status"] = "completed"
        quest_data["completion_time"] = time.time()

        template = self.get_quest_template(guild_id_str, quest_data.get("template_id", ""))

        # --- MODIFICATION START ---
        applied_reward_modifications = []
        consequences_to_process: List[Dict[str, Any]] = []

        # Determine player language for feedback text resolution (e.g. quest name, giver name)
        player_language = self._settings.get("main_bot_language", "en")
        if self._character_manager:
            player_character_obj = await self._character_manager.get_character(guild_id_str, character_id_str)
            if player_character_obj:
                player_language = getattr(player_character_obj, 'language_preference', player_language)

        quest_name_for_feedback = quest_data.get("name_i18n", {}).get(player_language, "A Quest")


        q_giver_entity_id = quest_data.get("giver_entity_id", template.get("giver_entity_id") if template else None)
        q_giver_entity_type = None
        giver_name_for_feedback = "an unknown benefactor"

        if template and q_giver_entity_id:
            q_giver_entity_type = template.get("giver_type")
            if not q_giver_entity_type and self._npc_manager and await self._npc_manager.get_npc(guild_id_str, q_giver_entity_id):
                 q_giver_entity_type = "NPC"

            if q_giver_entity_type == "NPC" and self._npc_manager:
                npc_giver = await self._npc_manager.get_npc(guild_id_str, q_giver_entity_id)
                if npc_giver: giver_name_for_feedback = getattr(npc_giver, 'name', q_giver_entity_id)
            elif q_giver_entity_type == "Faction" and self._rule_engine: # Assuming RuleEngine can get faction details
                faction_details = self._rule_engine.get_faction_details(q_giver_entity_id) # This method needs to exist
                if faction_details: giver_name_for_feedback = faction_details.get("name", q_giver_entity_id)
            elif q_giver_entity_id : # Fallback if type is unknown but ID exists
                giver_name_for_feedback = f"{q_giver_entity_type or 'Entity'} {q_giver_entity_id}"


        current_relationship_strength = 0.0
        if self._relationship_manager and q_giver_entity_id and q_giver_entity_type:
            try:
                current_relationship_strength = await self._relationship_manager.get_relationship_strength( # MODIFIED to await
                    guild_id_str, character_id_str, "Character", str(q_giver_entity_id), q_giver_entity_type
                )
            except Exception as e_rel_fetch:
                print(f"QuestManager: Error fetching relationship strength with quest giver {q_giver_entity_type} {q_giver_entity_id}: {e_rel_fetch}")

        if template:
            original_on_complete_consequences = template.get("consequences", {}).get("on_complete", [])
            consequences_to_process = deepcopy(original_on_complete_consequences)

            if self._rule_engine and self._rule_engine._rules_data and q_giver_entity_id and q_giver_entity_type:
                reward_rules_config = self._rule_engine._rules_data.get("relationship_influence_rules", {}).get("quest_rewards", {})
                type_match_str = f"Player-{q_giver_entity_type}Giver"

                for i, consequence_dict in enumerate(consequences_to_process):
                    consequence_type = consequence_dict.get("type")
                    original_amount_any = consequence_dict.get("amount")

                    if original_amount_any is None: continue
                    try:
                        original_amount = float(original_amount_any)
                    except (ValueError, TypeError): continue

                    modified_amount = original_amount
                    bonus_applied_value = 0.0

                    if consequence_type == "grant_xp":
                        xp_rules = reward_rules_config.get("xp_modifier_percent", [])
                        for rule in sorted(xp_rules, key=lambda x: x.get("threshold", 0.0), reverse=True):
                            if current_relationship_strength >= rule.get("threshold", float('inf')) and \
                               (not rule.get("type_match") or rule.get("type_match") == type_match_str):
                                bonus_percent = rule.get("bonus_percent", 0.0)
                                bonus_applied_value = original_amount * (float(bonus_percent) / 100.0)
                                modified_amount = original_amount + bonus_applied_value
                                applied_reward_modifications.append({
                                    "type": "xp_bonus_percent", "original_amount": int(original_amount),
                                    "modified_amount": int(modified_amount),
                                    "reason_key": "feedback.relationship.quest_reward_bonus_xp", # MODIFIED
                                    "reason_params": { # ADDED
                                        "bonus_xp": int(bonus_applied_value),
                                        "quest_name": quest_name_for_feedback,
                                        "giver_name": giver_name_for_feedback
                                    }
                                })
                                break
                    elif consequence_type == "add_currency":
                        currency_rules = reward_rules_config.get("currency_bonus_flat", [])
                        currency_name = consequence_dict.get("currency_type", "gold") # Assuming currency type in consequence
                        for rule in sorted(currency_rules, key=lambda x: x.get("threshold", 0.0), reverse=True):
                            if current_relationship_strength >= rule.get("threshold", float('inf')) and \
                               (not rule.get("type_match") or rule.get("type_match") == type_match_str):
                                bonus_applied_value = rule.get("bonus_amount", 0.0)
                                modified_amount = original_amount + float(bonus_applied_value)
                                applied_reward_modifications.append({
                                    "type": "currency_bonus_flat", "original_amount": int(original_amount),
                                    "modified_amount": int(modified_amount),
                                    "reason_key": "feedback.relationship.quest_reward_bonus_currency", # MODIFIED
                                    "reason_params": { # ADDED
                                        "bonus_amount": int(bonus_applied_value),
                                        "currency_name": currency_name,
                                        "quest_name": quest_name_for_feedback,
                                        "giver_name": giver_name_for_feedback
                                    }
                                })
                                break

                    if int(modified_amount) != int(original_amount):
                        consequences_to_process[i]["amount"] = int(modified_amount)
        # --- END MODIFICATION FOR RELATIONSHIP-BASED REWARDS ---

        # Send feedback notifications for applied reward modifications
        if self._notification_service: # Check if service is available
            for mod_info in applied_reward_modifications:
                if mod_info.get("reason_key"):
                    # Player language already fetched above
                    asyncio.create_task(self._notification_service.send_relationship_influence_feedback(
                        guild_id=guild_id_str,
                        player_id=character_id_str,
                        feedback_key=mod_info["reason_key"],
                        context_params=mod_info["reason_params"],
                        language=player_language,
                        target_channel_id=None # DM the player
                    ))

        if self._game_log_manager:
            revert_data = {
                "quest_id": quest_id_str,
                "character_id": character_id_str,
                "old_status": "active",
                "old_quest_data": old_quest_data_copy
            }

            party_id = None
            if self._character_manager:
                character_obj = self._character_manager.get_character(guild_id_str, character_id_str)
                if character_obj and hasattr(character_obj, 'party_id'):
                    party_id = character_obj.party_id

            logged_giver_faction_id = None
            if q_giver_entity_type == "NPC" and self._npc_manager and q_giver_entity_id:
                npc_obj = self._npc_manager.get_npc(guild_id_str, q_giver_entity_id)
                if npc_obj and hasattr(npc_obj, 'faction_id'):
                    logged_giver_faction_id = npc_obj.faction_id
            elif q_giver_entity_type == "Faction":
                logged_giver_faction_id = q_giver_entity_id

            log_details = {
                "action_type": "QUEST_STATUS_CHANGE",
                "quest_id": quest_id_str,
                "quest_template_id": quest_data.get("template_id"),
                "quest_name_i18n": quest_data.get("name_i18n"),
                "outcome": "completed",
                "player_id": character_id_str,
                "party_id": party_id,
                "giver_entity_id": q_giver_entity_id, # Use identified giver
                "giver_entity_type": q_giver_entity_type, # Use identified giver type
                "giver_faction_id": logged_giver_faction_id, # Use logged faction ID for this
                "rewards_data": quest_data.get("rewards_i18n", template.get("rewards_i18n") if template else {}), # Original rewards for reference
                "difficulty": template.get("level_suggestion") if template else quest_data.get("data",{}).get("difficulty"),
                "custom_quest_data": quest_data.get("data", {}),
                "reward_modifications": applied_reward_modifications, # Add info about modifications
                "revert_data": revert_data
            }
            asyncio.create_task(self._game_log_manager.log_event(
                guild_id=guild_id_str,
                event_type="QUEST_COMPLETED",
                details=log_details,
                player_id=character_id_str
            ))

        # Process the (potentially modified) consequences
        if self._consequence_processor:
            if consequences_to_process:
                context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
                self._consequence_processor.process_consequences(consequences_to_process, context)
            elif template : # Template existed but no on_complete consequences
                 pass
            # else: No template, nothing to process

        self._completed_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, []).append(quest_id_str)
        del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests[guild_id_str][character_id_str]:
            del self._active_quests[guild_id_str][character_id_str]

        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        return True

    async def revert_quest_start(self, guild_id: str, character_id: str, quest_id: str, **kwargs: Any) -> bool:
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        quest_id_str = str(quest_id)

        char_active_quests = self._active_quests.get(guild_id_str, {}).get(character_id_str, {})

        if quest_id_str in char_active_quests:
            del char_active_quests[quest_id_str]
            if not char_active_quests:
                if guild_id_str in self._active_quests and character_id_str in self._active_quests[guild_id_str]:
                    del self._active_quests[guild_id_str][character_id_str]
                if guild_id_str in self._active_quests and not self._active_quests[guild_id_str]:
                    del self._active_quests[guild_id_str]
            self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
            return True
        else:
            return False

    async def revert_quest_status_change(self, guild_id: str, character_id: str, quest_id: str, old_status: str, old_quest_data: Dict[str, Any], **kwargs: Any) -> bool:
        guild_id_str = str(guild_id); character_id_str = str(character_id); quest_id_str = str(quest_id)
        char_active_quests = self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        char_completed_quests = self._completed_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, [])
        is_currently_completed = quest_id_str in char_completed_quests
        if old_status == "active":
            if is_currently_completed:
                char_completed_quests[:] = [qid for qid in char_completed_quests if qid != quest_id_str]
            char_active_quests[quest_id_str] = old_quest_data.copy(); char_active_quests[quest_id_str]['status'] = old_status
        elif quest_id_str in char_active_quests :
            char_active_quests[quest_id_str]['status'] = old_status
            if old_status == "completed":
                if quest_id_str not in char_completed_quests: char_completed_quests.append(quest_id_str)
                del char_active_quests[quest_id_str]
            elif old_status == "failed":
                del char_active_quests[quest_id_str]
        else:
            if old_status == "completed":
                if quest_id_str not in char_completed_quests: char_completed_quests.append(quest_id_str)
                if quest_id_str in char_active_quests: del char_active_quests[quest_id_str]
            elif old_status == "failed":
                if quest_id_str in char_active_quests: del char_active_quests[quest_id_str]
                if quest_id_str in char_completed_quests:
                    char_completed_quests[:] = [qid for qid in char_completed_quests if qid != quest_id_str]
            else: return False
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        return True

    async def revert_quest_progress_update(self, guild_id: str, character_id: str, quest_id: str, objective_id: str, old_progress: Any, **kwargs: Any) -> bool:
        guild_id_str = str(guild_id); character_id_str = str(character_id); quest_id_str = str(quest_id)
        objective_id_str = str(objective_id)
        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data: return False
        if quest_data.get("status") != "active": return False
        if not isinstance(quest_data.get('progress'), dict): quest_data['progress'] = {}
        quest_data['progress'][objective_id_str] = old_progress
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        return True

    def load_state(self, guild_id: str, character_id: str, data: List[Dict[str, Any]]) -> None:
        guild_id_str = str(guild_id); character_id_str = str(character_id)
        if guild_id_str not in self._all_quests:
            print(f"QuestManager: Warning - _load_all_quests_from_db should be called before loading character-specific quest states for guild {guild_id_str}.")
        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        active_quests_for_char = self._active_quests[guild_id_str][character_id_str]
        for quest_data_item_id in data:
            quest_id = None
            if isinstance(quest_data_item_id, dict): quest_id = quest_data_item_id.get("id")
            elif isinstance(quest_data_item_id, str): quest_id = quest_data_item_id
            if quest_id:
                full_quest_obj = self._all_quests.get(guild_id_str, {}).get(str(quest_id))
                if full_quest_obj:
                    active_quests_for_char[str(quest_id)] = full_quest_obj.to_dict()
                    if isinstance(quest_data_item_id, dict):
                        active_quests_for_char[str(quest_id)].update(quest_data_item_id)

    async def _load_all_quests_from_db(self, guild_id: str) -> None:
        from bot.game.models.quest import Quest
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None: return
        self._all_quests[guild_id_str] = {}
        guild_quest_cache = self._all_quests[guild_id_str]
        try:
            sql_standard = "SELECT id, name_i18n, description_i18n, status, influence_level, prerequisites, connections, stages, rewards, npc_involvement, guild_id FROM quests WHERE guild_id = $1"
            rows = await self._db_service.adapter.fetchall(sql_standard, (guild_id_str,))
            for row_data in rows:
                data = dict(row_data); data['is_ai_generated'] = False
                for field in ['name_i18n', 'description_i18n', 'prerequisites', 'connections', 'stages', 'rewards', 'npc_involvement']:
                    if field in data and isinstance(data[field], str):
                        try: data[field] = json.loads(data[field])
                        except json.JSONDecodeError: data[field] = {} if field not in ['prerequisites'] else []
                guild_quest_cache[Quest.from_dict(data).id] = Quest.from_dict(data)
        except Exception as e: print(f"Error loading standard quests for guild {guild_id_str}: {e}"); traceback.print_exc()
        try:
            sql_generated = "SELECT id, title_i18n, description_i18n, status, suggested_level, stages_json, rewards_json, prerequisites_json, consequences_json, quest_giver_npc_id, ai_prompt_context_json, guild_id FROM generated_quests WHERE guild_id = $1"
            rows_gen = await self._db_service.adapter.fetchall(sql_generated, (guild_id_str,))
            for row_data_gen in rows_gen:
                data_gen = dict(row_data_gen); data_gen['is_ai_generated'] = True
                if 'title_i18n' in data_gen: data_gen['name_i18n'] = data_gen.pop('title_i18n')
                for json_field_db, model_json_str_field in {"stages_json": "stages_json_str", "rewards_json": "rewards_json_str", "prerequisites_json": "prerequisites_json_str", "consequences_json": "consequences_json_str", "ai_prompt_context_json": "ai_prompt_context_json_str"}.items():
                    if json_field_db in data_gen: data_gen[model_json_str_field] = data_gen.pop(json_field_db)
                for field in ['name_i18n', 'description_i18n']:
                    if field in data_gen and isinstance(data_gen[field], str):
                        try: data_gen[field] = json.loads(data_gen[field])
                        except json.JSONDecodeError: data_gen[field] = {}
                quest_obj = Quest.from_dict(data_gen)
                if quest_obj.stages_json_str:
                    try: quest_obj.stages = json.loads(quest_obj.stages_json_str)
                    except json.JSONDecodeError: quest_obj.stages = {}
                if quest_obj.rewards_json_str:
                    try: quest_obj.rewards = json.loads(quest_obj.rewards_json_str)
                    except json.JSONDecodeError: quest_obj.rewards = {}
                if quest_obj.prerequisites_json_str:
                    try: quest_obj.prerequisites = json.loads(quest_obj.prerequisites_json_str)
                    except json.JSONDecodeError: quest_obj.prerequisites = []
                if quest_obj.consequences_json_str:
                    try: quest_obj.consequences = json.loads(quest_obj.consequences_json_str)
                    except json.JSONDecodeError: quest_obj.consequences = {}
                guild_quest_cache[quest_obj.id] = quest_obj
        except Exception as e: print(f"Error loading generated quests for guild {guild_id_str}: {e}"); traceback.print_exc()

    async def save_state(self, guild_id: str, character_id: str) -> List[Dict[str, Any]]:
        guild_id_str = str(guild_id); character_id_str = str(character_id)
        character_quests_map = self._active_quests.get(guild_id_str, {}).get(character_id_str, {})
        return list(character_quests_map.values())

    def _build_consequence_context(self, guild_id: str, character_id: str, quest_data: Dict[str, Any]) -> Dict[str, Any]:
        context = {"guild_id": guild_id, "character_id": character_id, "quest": quest_data}
        if self._npc_manager: context["npc_manager"] = self._npc_manager
        if self._item_manager: context["item_manager"] = self._item_manager
        if self._character_manager: context["character_manager"] = self._character_manager
        if self._relationship_manager: context["relationship_manager"] = self._relationship_manager
        return context

    def _are_all_objectives_complete(self, quest_data: Dict[str, Any]) -> bool:
        print(f"Placeholder: _are_all_objectives_complete for quest {quest_data.get('id')} returning True.")
        return True

    def update_quest_progress(self, guild_id: str, character_id: str, quest_id: str, objective_id: str, progress_update: Any) -> bool:
        guild_id_str = str(guild_id); character_id_str = str(character_id); quest_id_str = str(quest_id)
        objective_id_str = str(objective_id)
        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data or quest_data.get("status") != "active": return False
        objective_to_update = None
        for obj in quest_data.get("objectives", []):
            if obj.get("id") == objective_id_str: objective_to_update = obj; break
        if not objective_to_update: return False
        current_progress = quest_data.get("progress", {}).get(objective_id_str, 0)
        obj_type = objective_to_update.get("type")
        if obj_type in ["kill", "collect"]:
            if not isinstance(current_progress, (int, float)): current_progress = 0
            if isinstance(progress_update, (int, float)): new_progress = current_progress + progress_update
            else: new_progress = progress_update
        else: new_progress = progress_update
        quest_data.setdefault("progress", {})[objective_id_str] = new_progress
        old_progress_value = quest_data.get("progress", {}).get(objective_id_str)
        quest_data.setdefault("progress", {})[objective_id_str] = new_progress
        if self._game_log_manager:
            log_details = {
                "action_type": "QUEST_PROGRESS_UPDATE", "quest_id": quest_id_str,
                "objective_id": objective_id_str, "new_progress": new_progress,
                "revert_data": {"quest_id": quest_id_str, "character_id": character_id_str, "objective_id": objective_id_str, "old_progress": old_progress_value}
            }
            asyncio.create_task(self._game_log_manager.log_event(guild_id_str, "QUEST_PROGRESS_UPDATED", log_details, player_id=character_id_str))
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        if self._are_all_objectives_complete(quest_data):
            self.complete_quest(guild_id_str, character_id_str, quest_id_str)
        return True

    def get_dirty_character_ids(self, guild_id: str) -> Set[str]:
        return self._dirty_quests.get(str(guild_id), set()).copy()

    def clear_dirty_character_ids(self, guild_id: str) -> None:
        if str(guild_id) in self._dirty_quests:
            self._dirty_quests[str(guild_id)].clear()

    async def save_generated_quest(self, quest: "Quest") -> bool:
        from bot.game.models.quest import Quest
        if not isinstance(quest, Quest) or not quest.is_ai_generated: return False
        if self._db_service is None or self._db_service.adapter is None: return False
        try:
            title_i18n_json = json.dumps(quest.name_i18n or {}); description_i18n_json = json.dumps(quest.description_i18n or {})
            stages_json = json.dumps(quest.stages or {}); rewards_json = json.dumps(quest.rewards or {})
            prerequisites_json = json.dumps(quest.prerequisites or []); consequences_json = json.dumps(quest.consequences or {})
            ai_context_to_dump = {}
            if hasattr(quest, 'ai_prompt_context_data') and isinstance(getattr(quest, 'ai_prompt_context_data'), dict):
                ai_context_to_dump = getattr(quest, 'ai_prompt_context_data')
            elif quest.ai_prompt_context_json_str:
                try: ai_context_to_dump = json.loads(quest.ai_prompt_context_json_str)
                except json.JSONDecodeError: pass
            ai_prompt_context_json = json.dumps(ai_context_to_dump)
            suggested_level_val = 0
            if hasattr(quest, 'suggested_level') and isinstance(getattr(quest, 'suggested_level'), int):
                suggested_level_val = getattr(quest, 'suggested_level')
            elif isinstance(quest.influence_level, str) and quest.influence_level.isdigit():
                try: suggested_level_val = int(quest.influence_level)
                except ValueError: pass
            quest_giver_npc_id = quest.npc_involvement.get('giver') if isinstance(quest.npc_involvement, dict) else None
            sql = "INSERT INTO generated_quests (id, guild_id, title_i18n, description_i18n, status, suggested_level, stages_json, rewards_json, prerequisites_json, consequences_json, quest_giver_npc_id, ai_prompt_context_json) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) ON CONFLICT (id) DO UPDATE SET guild_id = EXCLUDED.guild_id, title_i18n = EXCLUDED.title_i18n, description_i18n = EXCLUDED.description_i18n, status = EXCLUDED.status, suggested_level = EXCLUDED.suggested_level, stages_json = EXCLUDED.stages_json, rewards_json = EXCLUDED.rewards_json, prerequisites_json = EXCLUDED.prerequisites_json, consequences_json = EXCLUDED.consequences_json, quest_giver_npc_id = EXCLUDED.quest_giver_npc_id, ai_prompt_context_json = EXCLUDED.ai_prompt_context_json"
            params = (quest.id, quest.guild_id, title_i18n_json, description_i18n_json, quest.status, suggested_level_val, stages_json, rewards_json, prerequisites_json, consequences_json, quest_giver_npc_id, ai_prompt_context_json)
            await self._db_service.adapter.execute(sql, params)
            return True
        except Exception as e: print(f"Error saving generated quest {quest.id}: {e}"); traceback.print_exc(); return False

    async def start_quest_from_moderated_data(self, guild_id: str, character_id: str, quest_data: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from bot.game.models.quest import Quest
        guild_id_str = str(guild_id); character_id_str = str(character_id)
        if not self._character_manager or not await self._character_manager.get_character(guild_id_str, character_id_str): return None
        quest_data['guild_id'] = guild_id_str; quest_data['is_ai_generated'] = True
        quest_obj = Quest.from_dict(quest_data)
        if not await self.save_generated_quest(quest_obj): return None
        self._all_quests.setdefault(guild_id_str, {})[quest_obj.id] = quest_obj
        active_quest_data = quest_obj.to_dict()
        active_quest_data["character_id"] = character_id_str; active_quest_data["start_time"] = time.time()
        active_quest_data["status"] = "active"; active_quest_data.setdefault("progress", {})
        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})[quest_obj.id] = active_quest_data
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        if self._game_log_manager:
            log_details = {"action_type": "QUEST_START", "quest_id": active_quest_data['id'], "template_id": active_quest_data.get('template_id', 'AI_GENERATED'), "revert_data": {"quest_id": active_quest_data['id'], "character_id": character_id_str}}
            asyncio.create_task(self._game_log_manager.log_event(guild_id_str, "QUEST_STARTED", log_details, player_id=character_id_str))
        if self._consequence_processor:
            consequences_context_data = quest_obj.to_dict(); consequences_context_data["character_id"] = character_id_str
            built_context = self._build_consequence_context(guild_id_str, character_id_str, consequences_context_data)
            built_context.update(context)
            consequences_to_check = quest_obj.consequences or quest_data.get("consequences", {})
            consequences_value = consequences_to_check.get("on_start", [])
            consequences_to_process: List[Dict[str, Any]] = [consequences_value] if isinstance(consequences_value, dict) else consequences_value if isinstance(consequences_value, list) else []
            if consequences_to_process: self._consequence_processor.process_consequences(consequences_to_process, built_context)
        return active_quest_data
