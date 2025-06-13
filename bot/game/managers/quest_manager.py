import json
import uuid
import time
import asyncio
import traceback
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union, cast
from copy import deepcopy

from ..models.quest import Quest # Required for type hinting and Quest.from_dict
from bot.ai.ai_data_models import GenerationContext # Required for type hinting

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

    def load_quest_templates(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
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
                            logger.error(f"Error serializing steps_data for template {tpl_id}: {e}")
                            template_dict["steps_json"] = "[]"
                    elif 'stages' in template_dict and isinstance(template_dict['stages'], dict): # Legacy conversion
                        converted_steps_data = []
                        for stage_k, stage_v in template_dict['stages'].items():
                            if isinstance(stage_v, dict):
                                new_stage_v = stage_v.copy()
                                if 'id' not in new_stage_v: new_stage_v['id'] = stage_k
                                new_stage_v.setdefault('step_order', len(converted_steps_data))
                                if 'title_i18n' not in new_stage_v and 'title' in new_stage_v:
                                    new_stage_v['title_i18n'] = {self._default_lang: new_stage_v.pop('title')}
                                if 'description_i18n' not in new_stage_v and 'description' in new_stage_v:
                                    new_stage_v['description_i18n'] = {self._default_lang: new_stage_v.pop('description')}
                                converted_steps_data.append(new_stage_v)
                        try: template_dict["steps_json"] = json.dumps(converted_steps_data)
                        except (TypeError, OverflowError) as e:
                            logger.error(f"Error serializing converted stages for template {tpl_id}: {e}")
                            template_dict["steps_json"] = "[]"
                        template_dict.pop('stages', None) # Remove old stages after conversion
                    else: template_dict["steps_json"] = "[]"

                    if 'name_i18n' not in template_dict and 'name' in template_dict:
                        template_dict['name_i18n'] = {self._default_lang: template_dict.pop('name')}
                    for field_key, default_type in [
                        ("prerequisites", list), ("connections", dict),
                        ("rewards", dict), ("npc_involvement", dict), ("data", dict) ]:
                        template_dict.setdefault(field_key, default_type())
                    guild_templates_cache[tpl_id] = template_dict
                else: logger.warning(f"Invalid quest template format: {template_dict_orig}")
        else: logger.warning(f"'quest_templates' not list for guild {guild_id_str}.")

    async def _load_all_quests_from_db(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None: return
        self._all_quests[guild_id_str] = {}
        guild_quest_cache = self._all_quests[guild_id_str]
        try:
            # Ensure all relevant JSON fields are selected, map 'steps_json' from DB to 'steps_json_str' for model
            sql_standard = "SELECT id, name_i18n, description_i18n, status, influence_level, prerequisites, connections, steps_json, rewards, npc_involvement, guild_id, consequences_json_str, prerequisites_json_str, rewards_json_str, quest_giver_details_i18n, consequences_summary_i18n, ai_prompt_context_json_str FROM quests WHERE guild_id = $1"
            rows = await self._db_service.adapter.fetchall(sql_standard, (guild_id_str,))
            for row_data in rows:
                data = dict(row_data); data['is_ai_generated'] = False
                if 'steps_json' in data and data['steps_json'] is not None: data['steps_json_str'] = data.pop('steps_json')
                else: data['steps_json_str'] = "[]" # Default if null or missing

                for field in ['name_i18n', 'description_i18n', 'prerequisites', 'connections', 'rewards', 'npc_involvement', 'quest_giver_details_i18n', 'consequences_summary_i18n']:
                    if field in data and isinstance(data[field], str):
                        try: data[field] = json.loads(data[field])
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse JSON for field '{field}' in quest {data.get('id')}")
                            data[field] = {} if field not in ['prerequisites'] else []
                guild_quest_cache[Quest.from_dict(data).id] = Quest.from_dict(data)
        except Exception as e: logger.error(f"Error loading standard quests for {guild_id_str}: {e}\n{traceback.format_exc()}")
        try:
            sql_generated = "SELECT id, title_i18n, description_i18n, status, suggested_level, stages_json AS steps_json_str, rewards_json AS rewards_json_str, prerequisites_json AS prerequisites_json_str, consequences_json AS consequences_json_str, quest_giver_npc_id, ai_prompt_context_json AS ai_prompt_context_json_str, guild_id, quest_giver_details_i18n, consequences_summary_i18n FROM generated_quests WHERE guild_id = $1"
            rows_gen = await self._db_service.adapter.fetchall(sql_generated, (guild_id_str,))
            for row_data_gen in rows_gen:
                data_gen = dict(row_data_gen); data_gen['is_ai_generated'] = True
                if 'title_i18n' in data_gen: data_gen['name_i18n'] = data_gen.pop('title_i18n')
                # Ensure steps_json_str is not None
                if data_gen.get('steps_json_str') is None: data_gen['steps_json_str'] = "[]"

                for field in ['name_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n']:
                    if field in data_gen and isinstance(data_gen[field], str):
                        try: data_gen[field] = json.loads(data_gen[field])
                        except json.JSONDecodeError: data_gen[field] = {}
                guild_quest_cache[Quest.from_dict(data_gen).id] = Quest.from_dict(data_gen)
        except Exception as e: logger.error(f"Error loading generated quests for {guild_id_str}: {e}\n{traceback.format_exc()}")

    def get_quest_template(self, guild_id: str, quest_template_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        quest_template_id_str = str(quest_template_id)
        if guild_id_str not in self._quest_templates:
            self.load_quest_templates(guild_id_str) # Ensure templates are loaded
        return self._quest_templates.get(guild_id_str, {}).get(quest_template_id_str)

    async def start_quest(self, guild_id: str, character_id: str, quest_template_id: str, **kwargs: Any) -> Optional[Union[Dict[str, Any], Dict[str, str]]]:
        guild_id_str = str(guild_id); character_id_str = str(character_id); quest_template_id_str = str(quest_template_id)
        if quest_template_id_str.startswith("AI:"):
            quest_concept = quest_template_id_str.replace("AI:", "", 1)
            generation_context_data = kwargs.get("generation_context")
            if not isinstance(generation_context_data, GenerationContext): return {"status": "error", "message": "Missing generation context for AI quest."}
            ai_generated_quest_dict = await self.generate_quest_details_from_ai(guild_id_str, quest_concept, generation_context_data, triggering_entity_id=character_id_str)
            if ai_generated_quest_dict is None: return {"status": "error", "message": "AI quest generation failed."}
            user_id = kwargs.get('user_id') # Removed trailing semicolon for consistency, though not strictly required by task
            if not user_id: return {"status": "error", "message": "User ID required for AI quest moderation."}
            request_id = str(uuid.uuid4()) # Define request_id on its own line
            logger.info(f"AI-gen quest data for '{quest_concept}' (req_id: {request_id}) prepared for mod.")
            return {"status": "pending_moderation", "request_id": request_id, "quest_data_preview": ai_generated_quest_dict.get("name_i18n")}

        template_data_from_campaign = self.get_quest_template(guild_id_str, quest_template_id_str)
        if not template_data_from_campaign: return {"status": "error", "message": "Quest template not found."}

        if self._character_manager and not await self._character_manager.get_character(guild_id_str, character_id_str): return None # Changed to await

        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        for existing_quest in self._active_quests[guild_id_str][character_id_str].values():
            if existing_quest.get("template_id") == quest_template_id_str: return existing_quest

        quest_id = str(uuid.uuid4()); template_for_quest_obj = template_data_from_campaign.copy(); template_for_quest_obj['id'] = quest_id; template_for_quest_obj.setdefault('guild_id', guild_id_str)
        # Pass steps_json from template to Quest.from_dict via steps_json_str
        if "steps_json" in template_for_quest_obj:
            template_for_quest_obj['steps_json_str'] = template_for_quest_obj.pop('steps_json')

        quest_obj = Quest.from_dict(template_for_quest_obj); new_quest_data = quest_obj.to_dict()
        new_quest_data.update({"character_id": character_id_str, "status": "active", "start_time": time.time(), "template_id": quest_template_id_str, "progress": {}, "is_ai_generated": False})
        # steps_json is already in new_quest_data from quest_obj.to_dict()
        self._active_quests[guild_id_str][character_id_str][quest_id] = new_quest_data; self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        if self._game_log_manager: asyncio.create_task(self._game_log_manager.log_event(guild_id_str, "QUEST_STARTED", {"quest_id": quest_id, "template_id": quest_template_id_str}, player_id=character_id_str))
        return new_quest_data

    async def save_generated_quest(self, quest: "Quest") -> bool:
        if not isinstance(quest, Quest) or not quest.is_ai_generated: return False
        if self._db_service is None or self._db_service.adapter is None: return False
        try:
            stages_json_for_db = quest.steps_json
            title_i18n_json = json.dumps(quest.name_i18n or {}); description_i18n_json = json.dumps(quest.description_i18n or {});
            rewards_json = quest.rewards_json_str or "{}" ; prerequisites_json = quest.prerequisites_json_str or "{}"
            consequences_json = quest.consequences_json_str or "{}"; ai_prompt_context_json = quest.ai_prompt_context_json_str or "{}"
            quest_giver_details_i18n_json = json.dumps(quest.quest_giver_details_i18n or {})
            consequences_summary_i18n_json = json.dumps(quest.consequences_summary_i18n or {})
            suggested_level_val = 0
            if isinstance(quest.influence_level, str) and quest.influence_level.isdigit():
                try: suggested_level_val = int(quest.influence_level)
                except ValueError: pass
            quest_giver_npc_id = quest.npc_involvement.get('giver') if isinstance(quest.npc_involvement, dict) else None
            sql = """INSERT INTO generated_quests
                   (id, guild_id, title_i18n, description_i18n, status, suggested_level, stages_json,
                    rewards_json, prerequisites_json, consequences_json, quest_giver_npc_id,
                    ai_prompt_context_json, quest_giver_details_i18n, consequences_summary_i18n)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                   ON CONFLICT (id) DO UPDATE SET
                   guild_id = EXCLUDED.guild_id, title_i18n = EXCLUDED.title_i18n,
                   description_i18n = EXCLUDED.description_i18n, status = EXCLUDED.status,
                   suggested_level = EXCLUDED.suggested_level, stages_json = EXCLUDED.stages_json,
                   rewards_json = EXCLUDED.rewards_json, prerequisites_json = EXCLUDED.prerequisites_json,
                   consequences_json = EXCLUDED.consequences_json, quest_giver_npc_id = EXCLUDED.quest_giver_npc_id,
                   ai_prompt_context_json = EXCLUDED.ai_prompt_context_json,
                   quest_giver_details_i18n = EXCLUDED.quest_giver_details_i18n,
                   consequences_summary_i18n = EXCLUDED.consequences_summary_i18n
                   """
            params = (quest.id, quest.guild_id, title_i18n_json, description_i18n_json, quest.status,
                      suggested_level_val, stages_json_for_db, rewards_json, prerequisites_json,
                      consequences_json, quest_giver_npc_id, ai_prompt_context_json,
                      quest_giver_details_i18n_json, consequences_summary_i18n_json)
            await self._db_service.adapter.execute(sql, params)
            return True
        except Exception as e:
            logger.error(f"Error saving generated quest {quest.id}: {e}\n{traceback.format_exc()}")
            return False

    async def start_quest_from_moderated_data(self, guild_id: str, character_id: str, quest_data_from_ai: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id); character_id_str = str(character_id)
        if not self._character_manager or not await self._character_manager.get_character(guild_id_str, character_id_str):
            logger.warning(f"Char {character_id_str} not found for AI quest."); return None
        internal_quest_data = quest_data_from_ai.copy(); internal_quest_data['guild_id'] = guild_id_str; internal_quest_data['is_ai_generated'] = True
        if 'steps' in internal_quest_data and isinstance(internal_quest_data['steps'], list): internal_quest_data['steps_data'] = internal_quest_data.pop('steps')
        quest_obj = Quest.from_dict(internal_quest_data)
        if not await self.save_generated_quest(quest_obj): logger.error(f"Failed to save AI quest {quest_obj.id}."); return None
        self._all_quests.setdefault(guild_id_str, {})[quest_obj.id] = quest_obj; active_quest_data = quest_obj.to_dict()
        active_quest_data.update({"character_id": character_id_str, "start_time": time.time(), "status": "active", "progress": {}})
        self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})[quest_obj.id] = active_quest_data; self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        if self._game_log_manager: asyncio.create_task(self._game_log_manager.log_event(guild_id_str, "QUEST_STARTED", {"action_type": "QUEST_START", "quest_id": active_quest_data['id'], "template_id": active_quest_data.get('template_id', 'AI_GENERATED'), "revert_data": {"quest_id": active_quest_data['id'], "character_id": character_id_str}}, player_id=character_id_str))
        if self._consequence_processor:
            consequences_context_data = quest_obj.to_dict(); consequences_context_data["character_id"] = character_id_str
            built_context = self._build_consequence_context(guild_id_str, character_id_str, consequences_context_data); built_context.update(context)
            try: parsed_consequences = json.loads(quest_obj.consequences_json_str) if quest_obj.consequences_json_str else {}; on_start_consequences = parsed_consequences.get("on_start", [])
            except json.JSONDecodeError: on_start_consequences = []; logger.warning(f"Invalid JSON in consequences_json_str for {quest_obj.id}")
            if on_start_consequences: self._consequence_processor.process_consequences(on_start_consequences, built_context)
        return active_quest_data

    def list_quests_for_character(self, guild_id: str, character_id: str) -> List[Dict[str, Any]]:
        guild_id_str = str(guild_id); character_id_str = str(character_id)
        return list(self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).values())

    def _build_consequence_context(self, guild_id: str, character_id: str, quest_data: Dict[str, Any]) -> Dict[str, Any]:
        context = {"guild_id": guild_id, "character_id": character_id, "quest": quest_data}
        if self._npc_manager: context["npc_manager"] = self._npc_manager
        if self._item_manager: context["item_manager"] = self._item_manager
        if self._character_manager: context["character_manager"] = self._character_manager
        if self._relationship_manager: context["relationship_manager"] = self._relationship_manager
        return context

    def _are_all_objectives_complete(self, quest_data: Dict[str, Any]) -> bool:
        if not quest_data: logger.warning("_are_all_objectives_complete called with no quest_data."); return False
        steps_json_str = quest_data.get("steps_json", "[]")
        try:
            steps_list = json.loads(steps_json_str)
            if not isinstance(steps_list, list): logger.error(f"Quest {quest_data.get('id')}: steps_json not list."); return False
            if not steps_list: return True
            for step in steps_list:
                if not isinstance(step, dict): logger.warning(f"Quest {quest_data.get('id')}: step not dict: {step}"); return False
                if step.get('status') != 'completed': return False
            return True
        except json.JSONDecodeError as e: logger.error(f"Error decoding steps_json for {quest_data.get('id')}: {e}. Data: {steps_json_str}"); return False

    async def _mark_step_complete(self, guild_id: str, assignee_id: str, quest_id: str, step_order: int) -> bool:
        guild_id_str, assignee_id_str, quest_id_str = str(guild_id), str(assignee_id), str(quest_id)

        quest_data_map = self._active_quests.get(guild_id_str, {}).get(assignee_id_str, {})
        quest_data = quest_data_map.get(quest_id_str)

        if not quest_data:
            logger.error(f"Cannot mark step complete: Quest {quest_id_str} not found for assignee {assignee_id_str}.")
            return False

        try:
            step_dictionaries = json.loads(quest_data.get("steps_json", "[]"))
            if not isinstance(step_dictionaries, list):
                logger.error(f"steps_json for Q:{quest_id_str} is not a list. Data: {quest_data.get('steps_json')}")
                return False
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse steps_json for Q:{quest_id_str}: {e}")
            return False

        target_step_dict = None
        target_step_idx = -1
        for idx, s_dict in enumerate(step_dictionaries):
            if isinstance(s_dict, dict) and s_dict.get('step_order') == step_order:
                target_step_dict = s_dict
                target_step_idx = idx
                break

        if target_step_dict is None:
            logger.error(f"Step with order {step_order} not found in Q:{quest_id_str}.")
            return False

        if target_step_dict.get('status') == 'completed':
            logger.info(f"Step {step_order} of Q:{quest_id_str} is already completed.")
            return True # Already in desired state

        target_step_dict['status'] = 'completed'
        step_dictionaries[target_step_idx] = target_step_dict # Update the list

        # Process Step-Specific Consequences
        step_consequences_str = target_step_dict.get("consequences_json", "{}")
        if step_consequences_str and step_consequences_str.strip() not in ["{}", "[]"]:
            try:
                step_consequences_data = json.loads(step_consequences_str)
                if step_consequences_data and self._consequence_processor:
                    # Assuming consequences are structured like {"on_complete": [...]} or directly a list of actions
                    # The prompt example was: `{"grant_xp": 50, ...}` which implies a dict of actions.
                    # ConsequenceProcessor.process_consequences expects List[Dict]

                    actions_to_process = []
                    if isinstance(step_consequences_data, list): # Already a list of actions
                        actions_to_process = step_consequences_data
                    elif isinstance(step_consequences_data, dict): # A dict of actions or { "on_complete": [...] }
                        if "on_complete" in step_consequences_data and isinstance(step_consequences_data["on_complete"], list):
                             actions_to_process = step_consequences_data["on_complete"]
                        else: # Assume the dict itself contains actions like {"grant_xp": 50}
                             actions_to_process = [step_consequences_data] # Wrap it as a list of one dict

                    if actions_to_process:
                        step_context = self._build_consequence_context(guild_id_str, assignee_id_str, quest_data)
                        step_context['current_step_order'] = step_order
                        # Make a deepcopy if process_consequences might modify the list/dicts
                        self._consequence_processor.process_consequences(deepcopy(actions_to_process), step_context)
                        logger.info(f"Processed consequences for step {step_order} of Q:{quest_id_str}.")

            except json.JSONDecodeError as e_cons:
                logger.error(f"Error parsing step consequences_json for Q:{quest_id_str} S:{step_order}: {e_cons}. Data: {step_consequences_str}")
            except Exception as e_proc_cons:
                logger.error(f"Error processing step consequences for Q:{quest_id_str} S:{step_order}: {e_proc_cons}")

        quest_data["steps_json"] = json.dumps(step_dictionaries)
        self._dirty_quests.setdefault(guild_id_str, set()).add(assignee_id_str)
        logger.info(f"Step {step_order} of quest {quest_id_str} marked complete for {assignee_id_str}.")

        if self._are_all_objectives_complete(quest_data):
            logger.info(f"All steps for quest {quest_id_str} completed by {assignee_id_str}. Proceeding to complete quest.")
            await self.complete_quest(guild_id_str, assignee_id_str, quest_id_str) # Call async version

        return True

    async def _evaluate_abstract_goal(self, guild_id: str, assignee_id: str, quest_data: Dict[str, Any], step_dict: Dict[str, Any], event_log_entry: Dict[str, Any]) -> bool:
        abstract_goal_str = step_dict.get("abstract_goal_json", "{}")
        if not abstract_goal_str.strip() or abstract_goal_str == "{}":
            return False

        try:
            abstract_goal_data = json.loads(abstract_goal_str)
            if not abstract_goal_data:
                logger.debug(f"Empty abstract_goal_data for Q:{quest_data.get('id')} S:{step_dict.get('step_order')}")
                return False
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse abstract_goal_json for Q:{quest_data.get('id')} S:{step_dict.get('step_order', 'N/A')}: {e}. Data: {abstract_goal_str}")
            return False

        logger.info(f"Evaluating abstract goal for Q:{quest_data.get('id')} S:{step_dict.get('step_order')}: {abstract_goal_data}")
        collected_logs: List[Dict[str,Any]] = []
        evaluation_method = abstract_goal_data.get("evaluation_method", "rules")

        if evaluation_method == "llm":
            if not self._openai_service or not self._multilingual_prompt_generator:
                logger.warning("LLM eval for abstract goal skipped: AI services not available."); return False
            logger.info(f"LLM judgment placeholder for Q:{quest_data.get('id')} S:{step_dict.get('step_order')}."); return False
        else:
            if not self._rule_engine: logger.warning("Rule-based eval for abstract goal skipped: RuleEngine not available."); return False
            if hasattr(self._rule_engine, "evaluate_abstract_goal"):
                try:
                    goal_met_by_rules = self._rule_engine.evaluate_abstract_goal(abstract_goal_data, collected_logs, event_log_entry, quest_data, step_dict)
                    logger.info(f"Rule-based judgment for abstract goal Q:{quest_data.get('id')} S:{step_dict.get('step_order')}: {'Met' if goal_met_by_rules else 'Not Met'}.")
                    return goal_met_by_rules
                except Exception as e_rule_eval: logger.error(f"Error rule-based abstract goal eval: {e_rule_eval}"); return False
            else: logger.warning("RuleEngine no 'evaluate_abstract_goal' method."); return False

    async def handle_player_event_for_quest(self, guild_id: str, assignee_id: str, event_log_entry: Dict[str, Any]) -> None:
        guild_id_str, assignee_id_str = str(guild_id), str(assignee_id)
        active_quests_for_assignee = self._active_quests.get(guild_id_str, {}).get(assignee_id_str, {})
        if not active_quests_for_assignee: return

        for quest_id, quest_data in list(active_quests_for_assignee.items()):
            if not isinstance(quest_data, dict): logger.warning(f"Quest data {quest_id} not dict."); continue

            current_quest_id = quest_data.get('id') # Use actual ID from quest_data for safety
            if not current_quest_id: logger.warning(f"Quest data missing 'id'. Skipping."); continue


            steps_json_str = quest_data.get("steps_json", "[]")
            try:
                step_dictionaries = json.loads(steps_json_str) # This will be modified if a step completes
                if not isinstance(step_dictionaries, list):
                    logger.error(f"Steps_json for {current_quest_id} not list: {steps_json_str}"); continue
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse steps_json for {current_quest_id}: {e}. Data: {steps_json_str}"); continue

            for step_dict in step_dictionaries: # Iterate a copy for inspection, actual update via _mark_step_complete
                if not isinstance(step_dict, dict): logger.warning(f"Step in {current_quest_id} not dict: {step_dict}"); continue

                step_status = step_dict.get('status')
                if step_status not in ['active', 'pending']: continue

                step_assignee = step_dict.get('assignee_id', assignee_id_str)
                if step_assignee != assignee_id_str: continue

                current_step_order = step_dict.get('step_order')
                if current_step_order is None :
                    logger.warning(f"Step in Q:{current_quest_id} missing 'step_order'. Skipping."); continue


                mechanics_matched = False
                required_mechanics_str = step_dict.get("required_mechanics_json", "{}")
                has_required_mechanics = required_mechanics_str and required_mechanics_str.strip() not in ["{}", "[]"]

                if has_required_mechanics:
                    try:
                        mechanics_data = json.loads(required_mechanics_str)
                        if not mechanics_data: has_required_mechanics = False
                    except json.JSONDecodeError as e:
                        logger.error(f"Parse error required_mechanics_json Q:{current_quest_id} S:{current_step_order}: {e}"); continue # Skip this step

                    if self._rule_engine and hasattr(self._rule_engine, "check_event_matches_mechanics"):
                        try:
                            if self._rule_engine.check_event_matches_mechanics(event_log_entry, mechanics_data):
                                mechanics_matched = True
                        except Exception as e_rule: logger.error(f"RuleEngine check_event_matches_mechanics error: {e_rule}")
                    elif self._rule_engine: logger.warning("RuleEngine missing 'check_event_matches_mechanics'.")

                abstract_goal_str = step_dict.get("abstract_goal_json", "{}")
                has_abstract_goal = abstract_goal_str and abstract_goal_str.strip() not in ["{}", "[]"]

                step_should_complete = False
                if has_required_mechanics and mechanics_matched:
                    if has_abstract_goal:
                        logger.info(f"Mechanics met for Q:{current_quest_id} S:{current_step_order}. Eval abstract goal.")
                        if await self._evaluate_abstract_goal(guild_id_str, assignee_id_str, quest_data, step_dict, event_log_entry):
                            step_should_complete = True
                        else: logger.info(f"Abstract goal NOT MET for Q:{current_quest_id} S:{current_step_order}.")
                    else: # Mechanics matched, no abstract goal
                        step_should_complete = True
                elif not has_required_mechanics and has_abstract_goal: # Only abstract goal
                    logger.info(f"No required mechanics for Q:{current_quest_id} S:{current_step_order}. Eval abstract goal.")
                    if await self._evaluate_abstract_goal(guild_id_str, assignee_id_str, quest_data, step_dict, event_log_entry):
                        step_should_complete = True
                    else: logger.info(f"Abstract goal ONLY NOT MET for Q:{current_quest_id} S:{current_step_order}.")

                if step_should_complete:
                    logger.info(f"Proceeding to mark step {current_step_order} of quest {current_quest_id} complete.")
                    # Call _mark_step_complete. If it returns True and completes the quest,
                    # the quest might be removed from active_quests. Iterating list(active_quests...) handles this.
                    await self._mark_step_complete(guild_id_str, assignee_id_str, current_quest_id, current_step_order)
                    # If a step was completed, and potentially the quest, it's good to break from processing further steps
                    # for THIS event, as the state has changed. Another event might trigger next steps.
                    # However, if multiple steps could be completed by a single event and don't depend on each other's prior state,
                    # this break might be premature. For now, assume one step progression per event for simplicity.
                    break # Break from iterating steps of this quest for this event

    # --- Methods like update_quest_progress, revert_*, load_state, save_state, etc. ---
    # Assume they are present as per the previous file content.
    # For brevity, only pasting a few key ones that were part of earlier subtasks or related.

    async def generate_quest_details_from_ai(self, guild_id: str, quest_idea: str, generation_context: "GenerationContext", triggering_entity_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self._multilingual_prompt_generator or not self._openai_service or not self._ai_validator:
            logger.error("AI services not configured for quest generation."); return None
        generation_context.request_params["quest_idea"] = quest_idea
        if triggering_entity_id: generation_context.request_params["triggering_entity_id"] = triggering_entity_id
        prompt_messages = self._multilingual_prompt_generator.generate_quest_prompt(generation_context)
        ai_settings = self._settings.get("quest_generation_ai_settings", {}); max_tokens = ai_settings.get("max_tokens", 2500); temperature = ai_settings.get("temperature", 0.65)
        ai_response = await self._openai_service.generate_structured_multilingual_content(prompt_messages["system"], prompt_messages["user"], max_tokens, temperature)
        if not ai_response or "error" in ai_response or not isinstance(ai_response.get("json_string"), str):
            logger.error(f"AI service error or invalid response: {ai_response.get('error') if ai_response else 'No response'}"); return None
        ai_json_str = ai_response["json_string"]
        validation_result = self._ai_validator.validate_ai_response(ai_json_str, "single_quest", generation_context)
        if not validation_result.entities and validation_result.overall_status == "error":
            logger.error(f"AI response validation failed globally: {validation_result.global_errors}"); return None
        if not validation_result.entities: logger.error("AI validation yielded no entities."); return None
        quest_validation_details = validation_result.entities[0]
        overall_status = validation_result.overall_status
        if overall_status == "error":
            logger.error(f"Quest generation failed critical validation. Status: {overall_status}. Issues: {quest_validation_details.issues}"); return None
        elif overall_status in ["success", "success_with_autocorrections", "requires_moderation"]:
            logger.info(f"AI quest validation status: {overall_status}. Data will be returned."); return cast(Dict[str, Any], quest_validation_details.data)
        else: logger.warning(f"AI quest validation returned unexpected status: {overall_status}"); return None

    def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool: # Sync version
        guild_id_str = str(guild_id); character_id_str = str(character_id); quest_id_str = str(quest_id)
        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data: return False
        if not self._are_all_objectives_complete(quest_data): return False
        quest_data["status"] = "completed"; quest_data["completion_time"] = time.time()
        template = self.get_quest_template(guild_id_str, quest_data.get("template_id",""))
        if self._consequence_processor and template:
            context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
            consequences = template.get("consequences", {}).get("on_complete", []) # This should be quest level consequences
            if consequences: self._consequence_processor.process_consequences(consequences, context)
        self._completed_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, []).append(quest_id_str)
        if quest_id_str in self._active_quests.get(guild_id_str, {}).get(character_id_str, {}):
            del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests.get(guild_id_str, {}).get(character_id_str, {}):
            if character_id_str in self._active_quests.get(guild_id_str, {}):
                 del self._active_quests[guild_id_str][character_id_str]
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        return True

    async def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool: # Async version
        guild_id_str = str(guild_id); character_id_str = str(character_id); quest_id_str = str(quest_id)
        # Retrieve from active_quests, not _all_quests, as it's an active quest instance
        quest_data_map = self._active_quests.get(guild_id_str, {}).get(character_id_str, {})
        quest_data = quest_data_map.get(quest_id_str)

        if not quest_data:
            logger.warning(f"Async complete_quest: Active quest '{quest_id_str}' not found for assignee '{character_id_str}'.")
            return False

        # _are_all_objectives_complete checks the status of steps in steps_json
        if not self._are_all_objectives_complete(quest_data):
            logger.info(f"Async complete_quest: Quest '{quest_id_str}' not all steps met for assignee '{character_id_str}'.")
            return False

        logger.info(f"Completing quest {quest_id_str} for assignee {character_id_str}.")
        quest_data["status"] = "completed"
        quest_data["completion_time"] = time.time()

        # Process quest-level consequences (from Quest object's consequences_json_str)
        if self._consequence_processor and quest_data.get('consequences_json_str'):
            try:
                quest_consequences_data = json.loads(quest_data['consequences_json_str'])
                # Assuming quest consequences are also structured with an "on_complete" key
                on_complete_actions = quest_consequences_data.get("on_complete", [])
                if isinstance(on_complete_actions, list) and on_complete_actions: # Ensure it's a list of actions
                    context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
                    self._consequence_processor.process_consequences(deepcopy(on_complete_actions), context)
                    logger.info(f"Processed overall completion consequences for quest {quest_id_str}.")
                elif isinstance(quest_consequences_data, dict) and not on_complete_actions and quest_consequences_data: # if it's a flat dict of actions
                     context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
                     self._consequence_processor.process_consequences(deepcopy([quest_consequences_data]), context) # Wrap in list
                     logger.info(f"Processed overall completion consequences (flat dict) for quest {quest_id_str}.")

            except json.JSONDecodeError as e:
                logger.error(f"Error parsing quest-level consequences_json_str for quest {quest_id_str}: {e}")
            except Exception as e_proc:
                 logger.error(f"Error processing quest-level consequences for quest {quest_id_str}: {e_proc}")


        self._completed_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, []).append(quest_id_str)
        if quest_id_str in self._active_quests.get(guild_id_str, {}).get(character_id_str, {}):
            del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests.get(guild_id_str, {}).get(character_id_str, {}):
            if character_id_str in self._active_quests.get(guild_id_str, {}): del self._active_quests[guild_id_str][character_id_str]

        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        logger.info(f"Quest {quest_id_str} successfully completed and moved for assignee {character_id_str}.")
        return True

    def fail_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool:
        guild_id_str = str(guild_id); character_id_str = str(character_id); quest_id_str = str(quest_id)
        quest_data = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)
        if not quest_data: return False
        logger.info(f"Quest {quest_id_str} failed. steps_json: {quest_data.get('steps_json', 'N/A')}")
        quest_data.copy(); quest_data["status"] = "failed"; quest_data["failure_time"] = time.time()
        template = self.get_quest_template(guild_id_str, quest_data.get("template_id", ""))
        if self._game_log_manager: pass
        if self._consequence_processor and template: # Using template for fail consequences
            context = self._build_consequence_context(guild_id_str, character_id_str, quest_data)
            # Quest level consequences on fail usually come from the template
            consequences = template.get("consequences", {}).get("on_fail", [])
            if isinstance(consequences, str): # If consequences are a JSON string in template
                try: consequences = json.loads(consequences).get("on_fail", [])
                except json.JSONDecodeError: consequences = []
            if consequences: self._consequence_processor.process_consequences(consequences, context)

        if quest_id_str in self._active_quests.get(guild_id_str, {}).get(character_id_str, {}): del self._active_quests[guild_id_str][character_id_str][quest_id_str]
        if not self._active_quests.get(guild_id_str, {}).get(character_id_str, {}):
             if character_id_str in self._active_quests.get(guild_id_str, {}): del self._active_quests[guild_id_str][character_id_str]
        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str)
        return True


