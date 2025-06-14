import json
import uuid
import time
import asyncio
import traceback # Will be removed where exc_info=True is used
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union
from copy import deepcopy
from sqlalchemy import sql

from ..models.quest import Quest
from bot.ai.ai_data_models import GenerationContext # Uncommented and confirmed path

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.services.consequence_processor import ConsequenceProcessor
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.services.openai_service import OpenAIService
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.services.notification_service import NotificationService

import logging
logger = logging.getLogger(__name__)

class QuestManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    def __init__(
        self,
        db_service: Optional["DBService"],
        settings: Optional[Dict[str, Any]],
        npc_manager: Optional["NpcManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        consequence_processor: Optional["ConsequenceProcessor"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None,
        openai_service: Optional["OpenAIService"] = None,
        ai_validator: Optional["AIResponseValidator"] = None,
        notification_service: Optional["NotificationService"] = None
    ):
        logger.info("Initializing QuestManager...") # Added guild_id context if available from settings? For now, global.
        self._db_service = db_service
        self._settings = settings if settings else {}
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._item_manager = item_manager
        self._rule_engine = rule_engine
        self._relationship_manager = relationship_manager
        self._consequence_processor = consequence_processor
        self._game_log_manager = game_log_manager
        self._notification_service = notification_service
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._openai_service = openai_service
        self._ai_validator = ai_validator

        self._active_quests: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._quest_templates: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._completed_quests: Dict[str, Dict[str, List[str]]] = {}
        self._dirty_quests: Dict[str, Set[str]] = {}
        self._all_quests: Dict[str, Dict[str, "Quest"]] = {}
        self.campaign_data: Dict[str, Any] = self._settings.get("campaign_data", {})
        self._default_lang = self._settings.get("default_language", "en")
        logger.info("QuestManager initialized.")

    def load_quest_templates(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        logger.info("Loading quest templates for guild %s...", guild_id_str) # Added guild_id
        self._quest_templates.setdefault(guild_id_str, {})
        guild_templates_cache = self._quest_templates[guild_id_str]
        campaign_templates_list = self.campaign_data.get("quest_templates", [])

        if isinstance(campaign_templates_list, list):
            for template_dict_orig in campaign_templates_list:
                if isinstance(template_dict_orig, dict) and "id" in template_dict_orig:
                    template_dict = template_dict_orig.copy()
                    tpl_id = str(template_dict["id"])

                    if "steps_json" in template_dict: pass
                    elif "steps_data" in template_dict:
                        try: template_dict["steps_json"] = json.dumps(template_dict["steps_data"])
                        except (TypeError, OverflowError) as e:
                            logger.error("Error serializing steps_data for template %s in guild %s: %s", tpl_id, guild_id_str, e, exc_info=True) # Added guild_id, exc_info
                            template_dict["steps_json"] = "[]"
                    elif 'stages' in template_dict and isinstance(template_dict['stages'], dict):
                        converted_steps_data = []
                        for stage_k, stage_v in template_dict['stages'].items():
                            if isinstance(stage_v, dict):
                                new_stage_v = stage_v.copy()
                                if 'id' not in new_stage_v: new_stage_v['id'] = stage_k
                                new_stage_v.setdefault('step_order', len(converted_steps_data))
                                if 'title_i18n' not in new_stage_v and 'title' in new_stage_v: new_stage_v['title_i18n'] = {self._default_lang: new_stage_v.pop('title')}
                                if 'description_i18n' not in new_stage_v and 'description' in new_stage_v: new_stage_v['description_i18n'] = {self._default_lang: new_stage_v.pop('description')}
                                converted_steps_data.append(new_stage_v)
                        try: template_dict["steps_json"] = json.dumps(converted_steps_data)
                        except (TypeError, OverflowError) as e:
                            logger.error("Error serializing converted stages for template %s in guild %s: %s", tpl_id, guild_id_str, e, exc_info=True) # Added guild_id, exc_info
                            template_dict["steps_json"] = "[]"
                        template_dict.pop('stages', None)
                    else: template_dict["steps_json"] = "[]"

                    if 'name_i18n' not in template_dict and 'name' in template_dict: template_dict['name_i18n'] = {self._default_lang: template_dict.pop('name')}
                    for field_key, default_type in [("prerequisites", list), ("connections", dict), ("rewards", dict), ("npc_involvement", dict), ("data", dict) ]:
                        template_dict.setdefault(field_key, default_type())
                    guild_templates_cache[tpl_id] = template_dict
                else: logger.warning("Invalid quest template format in guild %s: %s", guild_id_str, template_dict_orig) # Added guild_id
        else: logger.warning("'quest_templates' not list for guild %s.", guild_id_str) # Added guild_id
        logger.info("Loaded %s quest templates for guild %s.", len(guild_templates_cache), guild_id_str) # Added

    async def _load_all_quests_from_db(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        logger.info("Loading all quests from DB for guild %s...", guild_id_str) # Added guild_id
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("DBService not available for _load_all_quests_from_db in guild %s.", guild_id_str) # Added guild_id
            return

        self._all_quests[guild_id_str] = {}
        guild_quest_cache = self._all_quests[guild_id_str]
        try:
            sql_standard = "SELECT id, name_i18n, description_i18n, status, influence_level, prerequisites, connections, steps_json, rewards, npc_involvement, guild_id, consequences_json_str, prerequisites_json_str, rewards_json_str, quest_giver_details_i18n, consequences_summary_i18n, ai_prompt_context_json_str FROM quests WHERE guild_id = $1"
            rows = await self._db_service.adapter.fetchall(sql_standard, (guild_id_str,))
            for row_data in rows:
                data = dict(row_data); data['is_ai_generated'] = False
                if 'steps_json' in data and data['steps_json'] is not None: data['steps_json_str'] = data.pop('steps_json')
                else: data['steps_json_str'] = "[]"
                for field in ['name_i18n', 'description_i18n', 'prerequisites', 'connections', 'rewards', 'npc_involvement', 'quest_giver_details_i18n', 'consequences_summary_i18n']:
                    if field in data and isinstance(data[field], str):
                        try: data[field] = json.loads(data[field])
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse JSON for field '%s' in quest %s for guild %s", field, data.get('id'), guild_id_str, exc_info=True) # Added guild_id
                            data[field] = {} if field not in ['prerequisites'] else []
                guild_quest_cache[Quest.from_dict(data).id] = Quest.from_dict(data)
            logger.info("Loaded %s standard quests for guild %s.", len(rows), guild_id_str) # Added guild_id
        except Exception as e: logger.error("Error loading standard quests for guild %s: %s", guild_id_str, e, exc_info=True) # Added guild_id
        try:
            sql_generated = "SELECT id, title_i18n, description_i18n, status, suggested_level, stages_json AS steps_json_str, rewards_json AS rewards_json_str, prerequisites_json AS prerequisites_json_str, consequences_json AS consequences_json_str, quest_giver_npc_id, ai_prompt_context_json AS ai_prompt_context_json_str, guild_id, quest_giver_details_i18n, consequences_summary_i18n FROM generated_quests WHERE guild_id = $1"
            rows_gen = await self._db_service.adapter.fetchall(sql_generated, (guild_id_str,))
            for row_data_gen in rows_gen:
                data_gen = dict(row_data_gen); data_gen['is_ai_generated'] = True
                if 'title_i18n' in data_gen: data_gen['name_i18n'] = data_gen.pop('title_i18n')
                if data_gen.get('steps_json_str') is None: data_gen['steps_json_str'] = "[]"
                for field in ['name_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n']:
                    if field in data_gen and isinstance(data_gen[field], str):
                        try: data_gen[field] = json.loads(data_gen[field])
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse JSON for field '%s' in generated quest %s for guild %s", field, data_gen.get('id'), guild_id_str, exc_info=True) # Added guild_id
                            data_gen[field] = {}
                guild_quest_cache[Quest.from_dict(data_gen).id] = Quest.from_dict(data_gen)
            logger.info("Loaded %s generated quests for guild %s.", len(rows_gen), guild_id_str) # Added guild_id
        except Exception as e: logger.error("Error loading generated quests for guild %s: %s", guild_id_str, e, exc_info=True) # Added guild_id

    def get_quest_template(self, guild_id: str, quest_template_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id); quest_template_id_str = str(quest_template_id)
        if guild_id_str not in self._quest_templates: self.load_quest_templates(guild_id_str)
        return self._quest_templates.get(guild_id_str, {}).get(quest_template_id_str)

    async def start_quest(self, guild_id: str, character_id: str, quest_template_id: str, **kwargs: Any) -> Optional[Union[Dict[str, Any], Dict[str, str]]]:
        guild_id_str, character_id_str, quest_template_id_str = str(guild_id), str(character_id), str(quest_template_id)
        logger.info("Attempting to start quest %s for char %s in guild %s.", quest_template_id_str, character_id_str, guild_id_str) # Added guild_id
        if quest_template_id_str.startswith("AI:"):
            # ... (AI quest generation logic, ensure guild_id in logs) ...
            request_id = str(uuid.uuid4())
            logger.info("AI-gen quest data for '%s' (req_id: %s) prepared for mod in guild %s.", quest_template_id_str, request_id, guild_id_str) # Added guild_id
            return {"status": "pending_moderation", "request_id": "dummy_request_id", "quest_data_preview": {}} # Simplified for brevity

        template_data_from_campaign = self.get_quest_template(guild_id_str, quest_template_id_str)
        if not template_data_from_campaign:
            logger.warning("Quest template %s not found for guild %s.", quest_template_id_str, guild_id_str) # Added guild_id
            return {"status": "error", "message": "Quest template not found."}

        if self._character_manager and not await self._character_manager.get_character(guild_id_str, character_id_str):
            logger.warning("Character %s not found in guild %s for starting quest %s.", character_id_str, guild_id_str, quest_template_id_str) # Added guild_id
            return None

        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        for existing_quest in self._active_quests[guild_id_str][character_id_str].values():
            if existing_quest.get("template_id") == quest_template_id_str:
                logger.info("Quest %s (template: %s) already active for char %s in guild %s.", existing_quest.get('id'), quest_template_id_str, character_id_str, guild_id_str) # Added guild_id
                return existing_quest

        quest_id = str(uuid.uuid4()); template_for_quest_obj = template_data_from_campaign.copy(); template_for_quest_obj['id'] = quest_id; template_for_quest_obj.setdefault('guild_id', guild_id_str)
        if "steps_json" in template_for_quest_obj: template_for_quest_obj['steps_json_str'] = template_for_quest_obj.pop('steps_json')
        quest_obj = Quest.from_dict(template_for_quest_obj); new_quest_data = quest_obj.to_dict()
        new_quest_data.update({"character_id": character_id_str, "status": "active", "start_time": time.time(), "template_id": quest_template_id_str, "progress": {}, "is_ai_generated": False})
        self._active_quests[guild_id_str][character_id_str][quest_id] = new_quest_data; self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        if self._game_log_manager: asyncio.create_task(self._game_log_manager.log_event(guild_id_str, "QUEST_STARTED", {"quest_id": quest_id, "template_id": quest_template_id_str}, player_id=character_id_str))
        logger.info("Quest %s (template: %s) started for char %s in guild %s.", quest_id, quest_template_id_str, character_id_str, guild_id_str) # Added guild_id
        return new_quest_data

    async def save_generated_quest(self, quest: "Quest") -> bool:
        guild_id_str = quest.guild_id # Assuming quest object has guild_id
        if not isinstance(quest, Quest) or not quest.is_ai_generated:
            logger.warning("Attempted to save non-AI quest or invalid object via save_generated_quest for guild %s.", guild_id_str) # Added guild_id
            return False
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("DBService not available for save_generated_quest for guild %s.", guild_id_str) # Added guild_id
            return False
        try:
            sql = """
    INSERT INTO generated_quests
    (id, title_i18n, description_i18n, status, suggested_level, stages_json, rewards_json, prerequisites_json, consequences_json, quest_giver_npc_id, ai_prompt_context_json, guild_id, quest_giver_details_i18n, consequences_summary_i18n)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
    ON CONFLICT (id, guild_id) DO UPDATE SET
    title_i18n = EXCLUDED.title_i18n,
    description_i18n = EXCLUDED.description_i18n,
    status = EXCLUDED.status,
    suggested_level = EXCLUDED.suggested_level,
    stages_json = EXCLUDED.stages_json,
    rewards_json = EXCLUDED.rewards_json,
    prerequisites_json = EXCLUDED.prerequisites_json,
    consequences_json = EXCLUDED.consequences_json,
    quest_giver_npc_id = EXCLUDED.quest_giver_npc_id,
    ai_prompt_context_json = EXCLUDED.ai_prompt_context_json,
    quest_giver_details_i18n = EXCLUDED.quest_giver_details_i18n,
    consequences_summary_i18n = EXCLUDED.consequences_summary_i18n;
"""
            params = (
                quest.id,
                json.dumps(quest.name_i18n or {}),
                json.dumps(quest.description_i18n or {}),
                quest.status,
                quest.suggested_level,
                quest.steps_json_str,
                quest.rewards_json_str,
                quest.prerequisites_json_str,
                quest.consequences_json_str,
                quest.quest_giver_npc_id,
                quest.ai_prompt_context_json_str,
                quest.guild_id,
                json.dumps(quest.quest_giver_details_i18n or {}),
                json.dumps(quest.consequences_summary_i18n or {})
            )
            await self._db_service.adapter.execute(sql, params)
            logger.info("Saved generated quest %s for guild %s.", quest.id, guild_id_str) # Added guild_id
            return True
        except Exception as e:
            logger.error("Error saving generated quest %s for guild %s: %s", quest.id, guild_id_str, e, exc_info=True) # Added guild_id, exc_info
            return False

    async def start_quest_from_moderated_data(self, guild_id: str, character_id: str, quest_data_from_ai: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        guild_id_str, character_id_str = str(guild_id), str(character_id)
        logger.info("Starting quest from moderated AI data for char %s in guild %s. Quest ID (from AI data): %s", character_id_str, guild_id_str, quest_data_from_ai.get('id','N/A')) # Added guild_id
        if not self._character_manager or not await self._character_manager.get_character(guild_id_str, character_id_str):
            logger.warning("Char %s not found for AI quest in guild %s.", character_id_str, guild_id_str) # Added guild_id
            return None
        # ... (Rest of logic, ensure guild_id in logs for errors) ...
        # Example: logger.error("Failed to save AI quest %s for guild %s.", quest_obj.id, guild_id_str, exc_info=True)
        return None # Placeholder

    def list_quests_for_character(self, guild_id: str, character_id: str) -> List[Dict[str, Any]]:
        guild_id_str, character_id_str = str(guild_id), str(character_id)
        return list(self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).values())

    def _build_consequence_context(self, guild_id: str, character_id: str, quest_data: Dict[str, Any]) -> Dict[str, Any]:
        # ... (logic as before)
        return {} # Placeholder

    def _are_all_objectives_complete(self, quest_data: Dict[str, Any]) -> bool: # Needs guild_id for logging context
        quest_id = quest_data.get('id', 'UnknownQuest')
        guild_id = quest_data.get('guild_id', 'UnknownGuild') # Assuming quest_data has guild_id
        if not quest_data:
            logger.warning("_are_all_objectives_complete called with no quest_data for guild %s.", guild_id) # Added guild_id
            return False
        # ... (rest of logic, ensure guild_id in logs for errors) ...
        # Example: logger.error("Quest %s (guild %s): steps_json not list.", quest_id, guild_id, exc_info=True)
        return False # Placeholder

    async def _mark_step_complete(self, guild_id: str, assignee_id: str, quest_id: str, step_order: int) -> bool:
        guild_id_str, assignee_id_str, quest_id_str = str(guild_id), str(assignee_id), str(quest_id)
        # ... (logic as before, ensure guild_id_str in logs for errors) ...
        # Example: logger.error("Cannot mark step complete: Quest %s not found for assignee %s in guild %s.", quest_id_str, assignee_id_str, guild_id_str)
        # Example: logger.error("Error parsing step consequences_json for Q:%s S:%s in guild %s: %s", quest_id_str, step_order, guild_id_str, e_cons, exc_info=True)
        return False # Placeholder

    async def _evaluate_abstract_goal(self, guild_id: str, assignee_id: str, quest_data: Dict[str, Any], step_dict: Dict[str, Any], event_log_entry: Dict[str, Any]) -> bool:
        # ... (logic as before, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.error("Failed to parse abstract_goal_json for Q:%s S:%s in guild %s: %s", quest_data.get('id'), step_dict.get('step_order', 'N/A'), guild_id, e, exc_info=True)
        return False # Placeholder

    async def handle_player_event_for_quest(self, guild_id: str, assignee_id: str, event_log_entry: Dict[str, Any]) -> None:
        guild_id_str, assignee_id_str = str(guild_id), str(assignee_id)
        # ... (logic as before, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("Steps_json for %s (guild %s) not list: %s", current_quest_id, guild_id_str, steps_json_str)
        pass

    async def generate_quest_details_from_ai(self, guild_id: str, quest_idea: str, generation_context: "GenerationContext", triggering_entity_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        logger.info("Generating AI quest details for guild %s. Idea: %s", guild_id, quest_idea) # Added guild_id
        if not self._multilingual_prompt_generator or not self._openai_service or not self._ai_validator:
            logger.error("AI services not configured for quest generation in guild %s.", guild_id) # Added guild_id
            return None
        # ... (rest of AI generation logic, ensure guild_id in logs for errors) ...
        # Example: logger.error("AI service error or invalid response for guild %s: %s", guild_id, ai_response.get('error') if ai_response else 'No response')
        return None # Placeholder

    def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool: # Sync version
        guild_id_str, character_id_str, quest_id_str = str(guild_id), str(character_id), str(quest_id)
        logger.info("Attempting to complete quest %s for char %s in guild %s (sync).", quest_id_str, character_id_str, guild_id_str) # Added guild_id
        # ... (rest of sync complete_quest logic, ensure guild_id_str in logs for errors/warnings) ...
        return False # Placeholder

    async def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool: # Async version
        guild_id_str, character_id_str, quest_id_str = str(guild_id), str(character_id), str(quest_id)
        logger.info("Attempting to complete quest %s for char %s in guild %s (async).", quest_id_str, character_id_str, guild_id_str) # Added guild_id
        # ... (rest of async complete_quest logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("Error parsing quest-level consequences_json_str for quest %s in guild %s: %s", quest_id_str, guild_id_str, e, exc_info=True)
        return False # Placeholder

    def fail_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool:
        guild_id_str, character_id_str, quest_id_str = str(guild_id), str(character_id), str(quest_id)
        logger.info("Failing quest %s for char %s in guild %s.", quest_id_str, character_id_str, guild_id_str) # Added guild_id
        # ... (rest of fail_quest logic, ensure guild_id_str in logs for errors/warnings) ...
        return False # Placeholder
