import json
import uuid
import time
import asyncio
import traceback # Will be removed where exc_info=True is used
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union
from copy import deepcopy
from sqlalchemy import sql

from ..models.quest import Quest # This is likely the Pydantic model
from ..models.quest_step import QuestStep # This is likely the Pydantic model
# Need DB models for saving
from bot.database.models import GeneratedQuest as DBGeneratedQuest, QuestStepTable as DBQuestStepTable
from bot.ai.ai_data_models import GenerationContext # Uncommented and confirmed path
from sqlalchemy.ext.asyncio import AsyncSession # Added for type hinting

# Specific model imports for accept_quest
from bot.database.models import Player
# DBGeneratedQuest and DBQuestStepTable are already imported

# CRUD utils for accept_quest
from bot.database.crud_utils import get_entity_by_id, get_entities

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
    # For game_manager access if needed, though QuestManager usually is part of it
    from bot.game.managers.game_manager import GameManager

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
        notification_service: Optional["NotificationService"] = None,
        game_manager: Optional["GameManager"] = None
    ):
        logger.info("Initializing QuestManager...") # Added guild_id context if available from settings? For now, global.
        self._db_service = db_service
        self._settings = settings if settings else {}
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._item_manager = item_manager
        self._rule_engine = rule_engine
        self._relationship_manager = relationship_manager
        self._consequence_processor = consequence_processor # This will be replaced by the new instantiation below
        self._game_log_manager = game_log_manager
        self._notification_service = notification_service
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._openai_service = openai_service
        self._ai_validator = ai_validator
        self.game_manager = game_manager # Moved game_manager assignment higher up

        # Ensure ConsequenceProcessor is initialized with NotificationService
        if consequence_processor is None and self.game_manager and character_manager and npc_manager and item_manager and self.game_manager.location_manager and self.game_manager.event_manager and self and self.game_manager.status_manager and game_log_manager:
            from bot.game.services.consequence_processor import ConsequenceProcessor # Local import to avoid circular if not already imported at top
            self._consequence_processor = ConsequenceProcessor(
                character_manager=character_manager,
                npc_manager=npc_manager,
                item_manager=item_manager,
                location_manager=self.game_manager.location_manager,
                event_manager=self.game_manager.event_manager,
                quest_manager=self,
                status_manager=self.game_manager.status_manager,
                dialogue_manager=None,
                game_state=None,
                rule_engine=rule_engine,
                economy_manager=None,
                relationship_manager=relationship_manager,
                game_log_manager=game_log_manager,
                notification_service=self._notification_service,
                prompt_context_collector=None
            )
            logger.info("QuestManager: Auto-initialized ConsequenceProcessor with NotificationService.")
        elif consequence_processor:
            self._consequence_processor = consequence_processor
            # If ConsequenceProcessor was already provided, we assume it was correctly initialized by the caller.
            # However, to ensure it has the notification service from this QuestManager's context if not already set:
            if hasattr(self._consequence_processor, '_notification_service') and getattr(self._consequence_processor, '_notification_service') is None:
                 setattr(self._consequence_processor, '_notification_service', self._notification_service)
                 logger.info("QuestManager: Attached NotificationService to pre-existing ConsequenceProcessor.")
            if hasattr(self._consequence_processor, '_prompt_context_collector') and getattr(self._consequence_processor, '_prompt_context_collector') is None:
                 # setattr(self._consequence_processor, '_prompt_context_collector', self._prompt_context_collector_instance_if_any) # Pass if QuestManager gets one
                 pass


        self._active_quests: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._quest_templates: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._completed_quests: Dict[str, Dict[str, List[str]]] = {}
        self._dirty_quests: Dict[str, Set[str]] = {}
        self._all_quests: Dict[str, Dict[str, "Quest"]] = {}
        self.campaign_data: Dict[str, Any] = self._settings.get("campaign_data", {})
        self._default_lang = self._settings.get("default_language", "en")

        # Add game_manager reference if available through settings or passed in __init__
        # For now, assuming it's not directly available or needed for basic accept_quest
        # If needed for rules, it would require __init__ modification or passing GameManager instance.
        # self.game_manager assignment moved higher up

        logger.info("QuestManager initialized.")

    async def accept_quest(self, guild_id: str, player_id_pk: str, quest_id_to_accept: str) -> tuple[bool, str]:
        """
        Allows a player to accept a quest.
        Checks prerequisites, finds the first step, and updates player's active quests.
        """
        if not self._db_service:
            logger.error(f"DBService not available in QuestManager for accept_quest. Guild: {guild_id}")
            return False, "Quest system is currently unavailable."

        async with self._db_service.get_session() as session:
            try:
                # Load Player
                player = await get_entity_by_id(session, Player, player_id_pk, guild_id)
                if not player:
                    logger.warning(f"accept_quest: Player {player_id_pk} not found in guild {guild_id}.")
                    return False, "Player not found."

                # Load Quest to Accept
                # Using DBGeneratedQuest as that's the alias for GeneratedQuest model
                quest_to_accept = await get_entity_by_id(session, DBGeneratedQuest, quest_id_to_accept, guild_id)
                if not quest_to_accept:
                    logger.warning(f"accept_quest: Quest {quest_id_to_accept} not found in guild {guild_id}.")
                    return False, "Quest not found or is not available."

                # Initialize player.active_quests
                active_quests_list = []
                if player.active_quests:
                    if isinstance(player.active_quests, str):
                        try:
                            active_quests_list = json.loads(player.active_quests)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to decode active_quests JSON for player {player.id} in guild {guild_id}. Data: {player.active_quests}", exc_info=True)
                            # Keep active_quests_list as empty, effectively overwriting corrupted data.
                    elif isinstance(player.active_quests, list):
                        active_quests_list = list(player.active_quests) # Ensure it's a mutable list

                    if not isinstance(active_quests_list, list): # Double check if it became non-list
                        logger.warning(f"Player {player.id} active_quests was not a list after parsing ({type(active_quests_list)}), resetting.")
                        active_quests_list = []

                # Check if Quest Already Active
                for entry in active_quests_list:
                    if isinstance(entry, dict) and entry.get("quest_id") == quest_id_to_accept:
                        return False, "You are already on this quest."

                # Prerequisite Checks
                if quest_to_accept.prerequisites_json:
                    try:
                        prereqs = json.loads(quest_to_accept.prerequisites_json)
                        if isinstance(prereqs, dict):
                            min_level = prereqs.get("min_level")
                            if isinstance(min_level, (int, float)) and player.level < min_level:
                                return False, f"You are not high enough level for this quest. Requires level {min_level}."

                            # TODO: Add checks for completed_quests, required_items etc.
                            # required_quests = prereqs.get("completed_quests", [])
                            # if required_quests:
                            #    player_completed_quests = ... (need a way to get player's completed quest IDs)
                            #    if not all(q_id in player_completed_quests for q_id in required_quests):
                            #        return False, "You haven't completed the necessary prerequisite quests."

                        else:
                            logger.warning(f"Parsed prerequisites_json for quest {quest_id_to_accept} is not a dict: {prereqs}")
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse prerequisites_json for quest {quest_id_to_accept}: {quest_to_accept.prerequisites_json}", exc_info=True)
                        # Potentially block quest acceptance if prereqs are unreadable and strictness is desired.
                        # return False, "This quest has unreadable prerequisites. Please contact an admin."


                if quest_to_accept.suggested_level and player.level < quest_to_accept.suggested_level:
                    logger.info(f"Player {player.id} (level {player.level}) accepting quest {quest_id_to_accept} below suggested level {quest_to_accept.suggested_level}.")
                    # This is a soft warning, not blocking.

                # Find First Quest Step
                # Using DBQuestStepTable as that's the alias for QuestStepTable model
                first_step_candidates = await get_entities(
                    session,
                    DBQuestStepTable,
                    guild_id,
                    conditions=[DBQuestStepTable.quest_id == quest_id_to_accept],
                    order_by=[DBQuestStepTable.step_order.asc()]
                )

                if not first_step_candidates:
                    logger.error(f"Quest {quest_id_to_accept} has no defined steps in guild {guild_id}.")
                    return False, "This quest has no objectives defined. Please contact an admin."

                first_step = first_step_candidates[0]

                # Add to player.active_quests
                new_active_quest_entry = {
                    "quest_id": quest_id_to_accept,
                    "current_step_id": first_step.id,
                    "status": "in_progress", # Using snake_case for status consistency
                    "step_progress": {}, # For any future step-specific data like counters
                    "started_at": time.time() # Optional: timestamp when quest was accepted
                }
                active_quests_list.append(new_active_quest_entry)
                player.active_quests = json.dumps(active_quests_list) # SQLAlchemy handles JSONB conversion

                session.add(player) # Add player to session to save changes to active_quests
                await session.commit()

                # Log Event (Conceptual)
                if self._game_log_manager:
                    # Ensure game_log_manager.log_event is async or called appropriately
                    asyncio.create_task(self._game_log_manager.log_event(
                        guild_id,
                        "QUEST_ACCEPTED",
                        {"quest_id": quest_id_to_accept, "player_id": player.id, "first_step_id": first_step.id},
                        player_id_pk # Pass primary key if that's what log_event expects for player_id
                    ))

                player_lang = player.selected_language or self._default_lang # Use player's lang or manager's default

                quest_title = quest_to_accept.title_i18n.get(player_lang, quest_to_accept.title_i18n.get('en', "Unnamed Quest")) if quest_to_accept.title_i18n else "Unnamed Quest"
                step_title = first_step.title_i18n.get(player_lang, first_step.title_i18n.get('en', "First Objective")) if first_step.title_i18n else "First Objective"

                return True, f"Quest '{quest_title}' accepted! Your first objective: {step_title}."

            except Exception as e:
                logger.error(f"Error in accept_quest for player {player_id_pk}, quest {quest_id_to_accept}, guild {guild_id}: {e}", exc_info=True)
                await session.rollback()
                return False, "An unexpected error occurred while trying to accept the quest."

    async def get_active_quests_for_character(self, guild_id: str, character_id: str) -> List[Quest]:
        """Retrieves active Quest Pydantic objects for a character in a guild."""
        active_quests_char_cache = self._active_quests.get(str(guild_id), {}).get(str(character_id), {})
        quests_to_return: List[Quest] = []
        if not active_quests_char_cache:
            logger.debug(f"No active quest entries in _active_quests cache for char {character_id} in guild {guild_id}.")
            return quests_to_return

        all_guild_quests = self._all_quests.get(str(guild_id), {})
        for quest_id, quest_dict_from_active in active_quests_char_cache.items():
            quest_obj = all_guild_quests.get(quest_id)
            if quest_obj:
                if quest_obj.status == 'active': # Double check status from the definitive object
                    quests_to_return.append(quest_obj)
                else:
                    logger.debug(f"Quest {quest_id} found in _all_quests but status is '{quest_obj.status}', not 'active'. Skipping from active list for char {character_id}.")
            elif isinstance(quest_dict_from_active, dict) and quest_dict_from_active.get('status') == 'active':
                # Fallback: reconstruct from dict if not in _all_quests (should be rare if _all_quests is kept up-to-date)
                logger.warning(f"Quest {quest_id} for char {character_id} (guild {guild_id}) was in _active_quests (status: active) but not _all_quests. Reconstructing.")
                current_quest_data = deepcopy(quest_dict_from_active)
                current_quest_data.setdefault('guild_id', str(guild_id)) # Ensure guild_id for from_dict

                reconstructed_quest = Quest.from_dict(current_quest_data)
                # Ensure steps are also Pydantic objects if they were dicts in the cache
                if not reconstructed_quest.steps and current_quest_data.get('steps'):
                    parsed_steps = []
                    for step_d_idx, step_d_val in enumerate(current_quest_data['steps']):
                        if isinstance(step_d_val, dict):
                            step_d_val.setdefault('guild_id', str(guild_id))
                            step_d_val.setdefault('quest_id', quest_id)
                            parsed_steps.append(QuestStep.from_dict(step_d_val))
                        elif isinstance(step_d_val, QuestStep): # If already a Pydantic object
                            parsed_steps.append(step_d_val)
                        else:
                            logger.warning(f"Step data at index {step_d_idx} for reconstructed quest {quest_id} is neither dict nor QuestStep. Skipping step.")
                    reconstructed_quest.steps = parsed_steps
                quests_to_return.append(reconstructed_quest)
                # Optionally add to _all_quests here if this path is hit often
                # self._all_quests.setdefault(str(guild_id), {})[quest_id] = reconstructed_quest
            else:
                logger.debug(f"Quest {quest_id} from _active_quests for char {character_id} (guild {guild_id}) not found in _all_quests and not a reconstructible active dict.")

        logger.info(f"Retrieved {len(quests_to_return)} active quests for character {character_id} in guild {guild_id}.")
        return quests_to_return

    async def get_completed_quests_for_character(self, guild_id: str, character_id: str) -> List[Quest]:
        """Retrieves completed Quest Pydantic objects for a character in a guild."""
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)

        completed_quest_ids = self._completed_quests.get(guild_id_str, {}).get(character_id_str, [])
        quests_to_return: List[Quest] = []

        if not completed_quest_ids:
            logger.debug(f"No completed quest IDs found in _completed_quests cache for char {character_id_str} in guild {guild_id_str}.")
            return quests_to_return

        all_guild_quests = self._all_quests.get(guild_id_str, {})
        for quest_id in completed_quest_ids:
            quest_obj = all_guild_quests.get(quest_id)
            if quest_obj:
                if quest_obj.status == 'completed': # Verify status from the definitive object
                    quests_to_return.append(quest_obj)
                else:
                    logger.warning(f"Quest {quest_id} listed in _completed_quests for char {character_id_str} but its status in _all_quests is '{quest_obj.status}'.")
            else:
                # This case is less likely for completed quests if they are always loaded into _all_quests
                # and status updated there. If a quest was completed but never made it to _all_quests,
                # it means it was handled only via _active_quests and then its ID moved to _completed_quests.
                # This would be a gap in ensuring _all_quests is comprehensive.
                logger.warning(f"Completed quest {quest_id} for char {character_id_str} (guild {guild_id_str}) not found in _all_quests cache. Cannot retrieve full details.")

        logger.info(f"Retrieved {len(quests_to_return)} completed quests for character {character_id_str} in guild {guild_id_str}.")
        return quests_to_return

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
            # Standard Quests: Query modified to remove steps_json
            sql_standard = "SELECT id, name_i18n, description_i18n, status, influence_level, prerequisites_json_str, connections_json, rewards_json_str, npc_involvement_json, guild_id, consequences_json_str, quest_giver_details_i18n, consequences_summary_i18n, ai_prompt_context_json_str FROM quests WHERE guild_id = $1"
            rows = await self._db_service.adapter.fetchall(sql_standard, (guild_id_str,))
            for row_data_dict in rows:
                data = dict(row_data_dict)
                data['is_ai_generated'] = False
                # steps_json and steps_json_str are no longer in the main query or passed to from_dict directly from here

                # Ensure JSON string fields are parsed if necessary (DB adapter might handle JSONB directly)
                # For Text fields storing JSON strings (like *_json_str), Quest.from_dict expects strings.
                # For JSONB fields, Quest.from_dict expects parsed dicts/lists.
                # The following loop is more for safety if adapter returns strings for JSONB,
                # but ideally, adapter gives Python dicts for JSONB.
                for field in ['name_i18n', 'description_i18n', 'connections_json', 'npc_involvement_json', 'quest_giver_details_i18n', 'consequences_summary_i18n']:
                    if field in data and isinstance(data[field], str):
                        try: data[field] = json.loads(data[field])
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse JSON for field '%s' in quest %s for guild %s", field, data.get('id'), guild_id_str, exc_info=True)
                            data[field] = {} # Default to empty dict

                # prerequisites in Pydantic model Quest is List[str], but prerequisites_json_str is string.
                # Quest.from_dict handles parsing prerequisites_json_str if prerequisites field is None.
                # So, we pass prerequisites_json_str as is.
                # Similar for rewards_json_str, consequences_json_str, ai_prompt_context_json_str.

                quest_obj = Quest.from_dict(data) # Create quest object first to get its ID

                # Fetch steps for this quest
                sql_steps = "SELECT * FROM quest_steps WHERE quest_id = $1 AND guild_id = $2 ORDER BY step_order ASC"
                step_rows = await self._db_service.adapter.fetchall(sql_steps, (quest_obj.id, guild_id_str))
                loaded_steps = []
                for step_row_data_dict in step_rows:
                    step_data = dict(step_row_data_dict)
                    # Ensure guild_id and quest_id are present if QuestStep.from_dict needs them (it does)
                    step_data.setdefault('guild_id', guild_id_str)
                    step_data.setdefault('quest_id', quest_obj.id)
                    loaded_steps.append(QuestStep.from_dict(step_data))
                quest_obj.steps = loaded_steps

                guild_quest_cache[quest_obj.id] = quest_obj
            logger.info("Loaded %s standard quests for guild %s.", len(rows), guild_id_str)
        except Exception as e: logger.error("Error loading standard quests for guild %s: %s", guild_id_str, e, exc_info=True)

        try:
            # Generated Quests: Query modified to remove stages_json (steps_json_str alias)
            sql_generated = "SELECT id, title_i18n, description_i18n, status, suggested_level, rewards_json, prerequisites_json, consequences_json, quest_giver_npc_id, ai_prompt_context_json, guild_id, quest_giver_details_i18n, consequences_summary_i18n FROM generated_quests WHERE guild_id = $1"
            rows_gen = await self._db_service.adapter.fetchall(sql_generated, (guild_id_str,))
            for row_data_gen_dict in rows_gen:
                data_gen = dict(row_data_gen_dict)
                data_gen['is_ai_generated'] = True

                # Quest.from_dict handles title_i18n as an alternative to name_i18n.
                # ai_prompt_context_json from DB maps to ai_prompt_context_json_str in Pydantic.
                # rewards_json from DB maps to rewards_json_str etc.
                # Quest.from_dict expects these with the "_str" suffix if they are JSON strings.
                # The DB columns are Text, so they should be strings.
                if 'ai_prompt_context_json' in data_gen: data_gen['ai_prompt_context_json_str'] = data_gen.pop('ai_prompt_context_json')
                if 'rewards_json' in data_gen: data_gen['rewards_json_str'] = data_gen.pop('rewards_json')
                if 'prerequisites_json' in data_gen: data_gen['prerequisites_json_str'] = data_gen.pop('prerequisites_json')
                if 'consequences_json' in data_gen: data_gen['consequences_json_str'] = data_gen.pop('consequences_json')

                # Similar to standard quests, ensure JSONB fields are dicts if adapter returns strings.
                for field in ['title_i18n', 'description_i18n', 'quest_giver_details_i18n', 'consequences_summary_i18n']:
                    if field in data_gen and isinstance(data_gen[field], str):
                        try: data_gen[field] = json.loads(data_gen[field])
                        except json.JSONDecodeError:
                            logger.warning("Failed to parse JSON for field '%s' in generated quest %s for guild %s", field, data_gen.get('id'), guild_id_str, exc_info=True)
                            data_gen[field] = {}

                quest_obj_gen = Quest.from_dict(data_gen)

                # Fetch steps for this generated quest
                sql_gen_steps = "SELECT * FROM quest_steps WHERE quest_id = $1 AND guild_id = $2 ORDER BY step_order ASC"
                step_rows_gen = await self._db_service.adapter.fetchall(sql_gen_steps, (quest_obj_gen.id, guild_id_str))
                loaded_steps_gen = []
                for step_row_gen_data_dict in step_rows_gen:
                    step_data_gen = dict(step_row_gen_data_dict)
                    step_data_gen.setdefault('guild_id', guild_id_str)
                    step_data_gen.setdefault('quest_id', quest_obj_gen.id)
                    loaded_steps_gen.append(QuestStep.from_dict(step_data_gen))
                quest_obj_gen.steps = loaded_steps_gen

                guild_quest_cache[quest_obj_gen.id] = quest_obj_gen
            logger.info("Loaded %s generated quests for guild %s.", len(rows_gen), guild_id_str)
        except Exception as e: logger.error("Error loading generated quests for guild %s: %s", guild_id_str, e, exc_info=True)

    def get_quest_template(self, guild_id: str, quest_template_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id); quest_template_id_str = str(quest_template_id)
        if guild_id_str not in self._quest_templates: self.load_quest_templates(guild_id_str)
        return self._quest_templates.get(guild_id_str, {}).get(quest_template_id_str)

    async def start_quest(self, guild_id: str, character_id: str, quest_template_id: str, **kwargs: Any) -> Optional[Union[Dict[str, Any], Dict[str, str]]]:
        guild_id_str, character_id_str, quest_template_id_str = str(guild_id), str(character_id), str(quest_template_id)
        logger.info("Attempting to start quest %s for char %s in guild %s.", quest_template_id_str, character_id_str, guild_id_str)

        if quest_template_id_str.startswith("AI:"):
            request_id = str(uuid.uuid4())
            logger.info("AI-gen quest data for '%s' (req_id: %s) prepared for mod in guild %s.", quest_template_id_str, request_id, guild_id_str)
            # This part would involve AI generation and then potentially saving and starting the quest.
            # For now, it returns a preview. The actual Quest object creation would happen after moderation.
            return {"status": "pending_moderation", "request_id": "dummy_request_id", "quest_data_preview": {}}

        template_data_from_campaign = self.get_quest_template(guild_id_str, quest_template_id_str)
        if not template_data_from_campaign:
            logger.warning("Quest template %s not found for guild %s.", quest_template_id_str, guild_id_str)
            return {"status": "error", "message": "Quest template not found."}

        if self._character_manager and not await self._character_manager.get_character(guild_id_str, character_id_str):
            logger.warning("Character %s not found in guild %s for starting quest %s.", character_id_str, guild_id_str, quest_template_id_str)
            return None

        # Check if quest from this template is already active for the character
        # Note: _active_quests stores dicts, not Quest objects directly.
        # If we need to check against Quest objects, we'd convert or load from _all_quests.
        # For now, assuming template_id check on dicts is sufficient for this specific check.
        active_quests_for_char = self._active_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, {})
        for existing_quest_dict in active_quests_for_char.values():
            if existing_quest_dict.get("template_id") == quest_template_id_str:
                logger.info("Quest (template: %s) already active for char %s in guild %s. Quest ID: %s", quest_template_id_str, character_id_str, guild_id_str, existing_quest_dict.get('id'))
                return existing_quest_dict # Return the existing quest dict

        # Create and store the new quest
        quest_id = str(uuid.uuid4())
        template_for_pydantic = deepcopy(template_data_from_campaign)
        template_for_pydantic['id'] = quest_id
        template_for_pydantic.setdefault('guild_id', guild_id_str) # Ensure guild_id for Quest.from_dict

        # Quest.from_dict will handle parsing steps from steps_json_str or a 'steps' list.
        # load_quest_templates prepares 'steps_json' in template_data_from_campaign.
        # This becomes 'steps_json_str' for Quest.from_dict.
        if "steps_json" in template_for_pydantic: # This is what load_quest_templates currently produces
            template_for_pydantic['steps_json_str'] = template_for_pydantic.pop('steps_json')

        quest_obj = Quest.from_dict(template_for_pydantic)
        quest_obj.status = "active" # Set status for new quest
        # Ensure quest_obj has character_id and start_time for storage in _active_quests if needed,
        # but these are not part of the core Quest Pydantic model.
        # The _active_quests cache stores dicts, so we convert quest_obj to dict.

        new_quest_dict_for_cache = quest_obj.to_dict()
        new_quest_dict_for_cache.update({
            "character_id": character_id_str, # Contextual info for active quest
            "start_time": time.time(),        # Contextual info for active quest
            "template_id": quest_template_id_str, # To link back to template if needed
            "progress": {} # Application-specific progress tracking, not in Pydantic model
        })

        # Store in _active_quests (as dict) and _all_quests (as Pydantic object)
        active_quests_for_char[quest_id] = new_quest_dict_for_cache
        self._all_quests.setdefault(guild_id_str, {})[quest_id] = quest_obj

        self._dirty_quests.setdefault(guild_id_str, set()).add(character_id_str) # Assuming this is for player-level dirty state

        # Persist the new quest and its steps to DB
        # Standard quests started from templates are not "AI generated"
        # We need a method to save a standard Quest object and its steps, similar to save_generated_quest
        # For now, this subtask focuses on adapting existing logic. Persisting new standard quests
        # would be a new feature or require adapting save_generated_quest to be more generic.
        # Let's assume for now that starting a template quest doesn't immediately write to 'quests' table
        # unless save_quest (a hypothetical new method) is called.
        # However, if steps are modified (e.g. status), they need DB updates.
        # The current structure implies _active_quests is an in-memory representation of ongoing quest progress.

        if self._game_log_manager:
            asyncio.create_task(self._game_log_manager.log_event(
                guild_id_str, "QUEST_STARTED",
                {"quest_id": quest_id, "template_id": quest_template_id_str},
                player_id=character_id_str
            ))
        logger.info("Quest %s (template: %s) started for char %s in guild %s. Stored in-memory.", quest_id, quest_template_id_str, character_id_str, guild_id_str)
        return new_quest_dict_for_cache


    async def save_generated_quest(self, quest: "Quest") -> bool:
        guild_id_str = quest.guild_id
        if not isinstance(quest, Quest) or not quest.is_ai_generated:
            logger.warning("Attempted to save non-AI quest or invalid object via save_generated_quest for guild %s.", guild_id_str) # Added guild_id
            return False
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("DBService not available for save_generated_quest for guild %s.", guild_id_str) # Added guild_id
            return False
        try:
            # Save main quest details to generated_quests table
            # stages_json column is removed.
            # title_i18n in DB maps to quest.name_i18n in Pydantic.
            # *_json fields in DB (Text) map to *_json_str in Pydantic (String).
            sql_main_quest = """
    INSERT INTO generated_quests
    (id, title_i18n, description_i18n, status, suggested_level, rewards_json, prerequisites_json, consequences_json, quest_giver_npc_id, ai_prompt_context_json, guild_id, quest_giver_details_i18n, consequences_summary_i18n)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
    ON CONFLICT (id) DO UPDATE SET
        title_i18n = EXCLUDED.title_i18n,
        description_i18n = EXCLUDED.description_i18n,
        status = EXCLUDED.status,
        suggested_level = EXCLUDED.suggested_level,
        rewards_json = EXCLUDED.rewards_json,
        prerequisites_json = EXCLUDED.prerequisites_json,
        consequences_json = EXCLUDED.consequences_json,
        quest_giver_npc_id = EXCLUDED.quest_giver_npc_id,
        ai_prompt_context_json = EXCLUDED.ai_prompt_context_json,
        quest_giver_details_i18n = EXCLUDED.quest_giver_details_i18n,
        consequences_summary_i18n = EXCLUDED.consequences_summary_i18n;
"""
            # Note: ON CONFLICT (id, guild_id) might be better if (id) is not globally unique
            # For now, assuming quest.id is unique enough or handled by application logic before save.
            # SQLAlchemy models use default=uuid.uuid4 for id, so it should be unique.
            # The Pydantic Quest.from_dict also ensures quest.id is populated.

            # Ensure quest.id and quest.guild_id are set
            if not quest.id: quest.id = str(uuid.uuid4())
            if not quest.guild_id:
                logger.error("Guild ID missing in quest object for saving generated quest.")
                return False

            params_main_quest = (
                quest.id,
                quest.name_i18n or {}, # title_i18n in DB, adapter handles dict to JSONB
                quest.description_i18n or {}, # description_i18n in DB
                quest.status,
                getattr(quest, 'suggested_level', None), # Pydantic Quest doesn't have suggested_level, get if exists
                quest.rewards_json_str,
                quest.prerequisites_json_str,
                quest.consequences_json_str,
                getattr(quest, 'quest_giver_npc_id', None), # Pydantic Quest doesn't have this
                quest.ai_prompt_context_json_str,
                quest.guild_id,
                quest.quest_giver_details_i18n or {},
                quest.consequences_summary_i18n or {}
            )
            await self._db_service.adapter.execute(sql_main_quest, params_main_quest)
            logger.info("Saved main details for generated quest %s for guild %s.", quest.id, guild_id_str)

            # Save quest steps to quest_steps table
            # First, clear existing steps for this quest_id to handle updates correctly.
            # This is a simple way; more sophisticated merging could be done.
            sql_delete_steps = "DELETE FROM quest_steps WHERE quest_id = $1 AND guild_id = $2"
            await self._db_service.adapter.execute(sql_delete_steps, (quest.id, quest.guild_id))

            for step_obj in quest.steps:
                if not step_obj.id: step_obj.id = str(uuid.uuid4()) # Ensure step has an ID
                # Ensure guild_id and quest_id are correctly set on the step object for insertion
                step_obj.guild_id = quest.guild_id
                step_obj.quest_id = quest.id

                sql_step = """
    INSERT INTO quest_steps
    (id, quest_id, guild_id, title_i18n, description_i18n, requirements_i18n,
    required_mechanics_json, abstract_goal_json, conditions_json, step_order, status,
    assignee_type, assignee_id, consequences_json, linked_location_id, linked_npc_id,
    linked_item_id, linked_guild_event_id)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
    ON CONFLICT (id) DO UPDATE SET
        quest_id = EXCLUDED.quest_id,
        guild_id = EXCLUDED.guild_id,
        title_i18n = EXCLUDED.title_i18n,
        description_i18n = EXCLUDED.description_i18n,
        requirements_i18n = EXCLUDED.requirements_i18n,
        required_mechanics_json = EXCLUDED.required_mechanics_json,
        abstract_goal_json = EXCLUDED.abstract_goal_json,
        conditions_json = EXCLUDED.conditions_json,
        step_order = EXCLUDED.step_order,
        status = EXCLUDED.status,
        assignee_type = EXCLUDED.assignee_type,
        assignee_id = EXCLUDED.assignee_id,
        consequences_json = EXCLUDED.consequences_json,
        linked_location_id = EXCLUDED.linked_location_id,
        linked_npc_id = EXCLUDED.linked_npc_id,
        linked_item_id = EXCLUDED.linked_item_id,
        linked_guild_event_id = EXCLUDED.linked_guild_event_id;
"""
                params_step = (
                    step_obj.id,
                    step_obj.quest_id,
                    step_obj.guild_id,
                    step_obj.title_i18n or {}, # JSONB
                    step_obj.description_i18n or {}, # JSONB
                    step_obj.requirements_i18n or {}, # JSONB
                    step_obj.required_mechanics_json, # Text
                    step_obj.abstract_goal_json, # Text
                    step_obj.conditions_json, # Text
                    step_obj.step_order,
                    step_obj.status,
                    step_obj.assignee_type,
                    step_obj.assignee_id,
                    step_obj.consequences_json, # Text
                    step_obj.linked_location_id,
                    step_obj.linked_npc_id,
                    step_obj.linked_item_id,
                    step_obj.linked_guild_event_id
                )
                await self._db_service.adapter.execute(sql_step, params_step)
            logger.info("Saved %s steps for generated quest %s for guild %s.", len(quest.steps), quest.id, guild_id_str)
            return True
        except Exception as e:
            logger.error("Error saving generated quest %s for guild %s: %s", quest.id if quest.id else "UnknownID", guild_id_str, e, exc_info=True)
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

    def _build_consequence_context(self, guild_id: str, character_id: str, quest_obj: Quest) -> Dict[str, Any]: # Changed quest_data to quest_obj
        # This method seems to be for building context for consequence processing.
        # It likely needs access to character, items, etc.
        # For now, assuming it can get what it needs from managers or quest_obj if extended.
        # The core Pydantic Quest doesn't hold live character/item objects.
        # This might indicate _active_quests storing more than just dicts, or this method fetching fresh data.
        # For this refactor, we'll assume its internal logic for fetching context is okay.
        logger.debug("Building consequence context for quest %s, char %s, guild %s", quest_obj.id, character_id, guild_id)
        # Example: Accessing quest properties: quest_obj.name, quest_obj.status
        # If it needs step details, it can iterate quest_obj.steps
        return {
            "guild_id": guild_id,
            "character_id": character_id,
            "quest_id": quest_obj.id,
            # Potentially add other relevant data from managers
        }

    def _are_all_objectives_complete(self, quest_obj: Quest) -> bool: # MODIFIED signature
        if not quest_obj:
            logger.warning("_are_all_objectives_complete called with no quest_obj.")
            return False

        logger.debug("Checking objectives for quest %s in guild %s. Found %s steps.", quest_obj.id, quest_obj.guild_id, len(quest_obj.steps))
        if not quest_obj.steps: # A quest with no steps is arguably complete by default, or an anomaly.
            logger.warning("Quest %s in guild %s has no steps. Considering it 'complete' for objective check.", quest_obj.id, quest_obj.guild_id)
            return True

        for step_obj in quest_obj.steps:
            if step_obj.status != 'completed':
                logger.debug("Quest %s step %s (order %s) is not completed (status: %s).", quest_obj.id, step_obj.id, step_obj.step_order, step_obj.status)
                return False
        logger.debug("All %s steps completed for quest %s.", len(quest_obj.steps), quest_obj.id)
        return True

    async def _mark_step_complete(self, guild_id: str, assignee_id: str, quest_id: str, step_order: int) -> bool:
        guild_id_str, quest_id_str = str(guild_id), str(quest_id)
        logger.info("Marking step %s complete for quest %s, assignee %s, guild %s", step_order, quest_id_str, assignee_id, guild_id_str)

        quest_obj = self._all_quests.get(guild_id_str, {}).get(quest_id_str)
        if not quest_obj:
            # Try to load from _active_quests if it's a dict
            active_quest_dict = self._active_quests.get(guild_id_str, {}).get(str(assignee_id), {}).get(quest_id_str)
            if active_quest_dict and isinstance(active_quest_dict, dict):
                logger.info("Quest %s not in _all_quests, attempting to reconstruct from _active_quests dict for marking step.", quest_id_str)
                quest_obj = Quest.from_dict(active_quest_dict.copy()) # Use copy to avoid modifying cache dict directly with Pydantic model
                # This quest_obj might not have full step details if _active_quests stores minimal data.
                # _load_all_quests_from_db populates _all_quests with full Quest objects including steps.
                # This path implies _mark_step_complete is called for a quest not fully loaded into _all_quests yet.
                # For robust behavior, ensure quest_obj has steps. If created from a minimal dict, it might not.
                # This indicates a potential need to always fetch full quest data or ensure _active_quests stores full Quest objects.
                # For now, if steps are missing, we cannot proceed.
                if not quest_obj.steps and active_quest_dict.get('steps'): # If dict had steps
                     parsed_steps = []
                     for step_d in active_quest_dict['steps']:
                         step_d.setdefault('guild_id', guild_id_str)
                         step_d.setdefault('quest_id', quest_id_str)
                         parsed_steps.append(QuestStep.from_dict(step_d))
                     quest_obj.steps = parsed_steps

            if not quest_obj:
                 logger.error("Cannot mark step complete: Quest %s not found for assignee %s in guild %s.", quest_id_str, assignee_id, guild_id_str)
                 return False

        target_step: Optional[QuestStep] = None
        for step in quest_obj.steps:
            if step.step_order == step_order:
                target_step = step
                break

        if not target_step:
            logger.error("Step order %s not found in quest %s for guild %s.", step_order, quest_id_str, guild_id_str)
            return False

        if target_step.status == 'completed':
            logger.info("Step %s (order %s) of quest %s is already marked completed.", target_step.id, step_order, quest_id_str)
            return True # Already complete

        target_step.status = 'completed'
        logger.info("Step %s (order %s) of quest %s marked as completed in Pydantic model.", target_step.id, step_order, quest_id_str)

        # Persist step status change to DB
        if self._db_service and self._db_service.adapter:
            try:
                update_sql = "UPDATE quest_steps SET status = $1 WHERE id = $2 AND guild_id = $3"
                await self._db_service.adapter.execute(update_sql, ('completed', target_step.id, guild_id_str))
                logger.info("Successfully updated status for step %s in DB for quest %s.", target_step.id, quest_id_str)
            except Exception as e_db:
                logger.error("Failed to update status for step %s in DB for quest %s (guild %s): %s", target_step.id, quest_id_str, guild_id_str, e_db, exc_info=True)
                # Optionally revert Pydantic model status change here or handle error
                target_step.status = 'pending' # Example: Revert, though this might hide issues
                return False
        else:
            logger.warning("DBService not available, step %s status update for quest %s not persisted to DB.", target_step.id, quest_id_str)
            # Depending on desired behavior, may want to prevent in-memory change if DB fails
            # For now, Pydantic model is updated, but DB is not.

        # Process consequences for this step
        if target_step.consequences_json and target_step.consequences_json not in ('{}', '[]'):
            if self._consequence_processor:
                consequence_context = self._build_consequence_context(guild_id_str, str(assignee_id), quest_obj) # Pass Quest object
                logger.debug("Processing consequences for step %s of quest %s. Context: %s", target_step.id, quest_id_str, consequence_context)
                asyncio.create_task(self._consequence_processor.process_consequences(
                    guild_id_str,
                    target_step.consequences_json,
                    consequence_context,
                    actor_id=str(assignee_id) # Assuming assignee is the actor
                ))
            else:
                logger.warning("ConsequenceProcessor not available for step %s of quest %s.", target_step.id, quest_id_str)

        # Update the representation in _active_quests if it exists there as a dict
        active_char_quests = self._active_quests.get(guild_id_str, {}).get(str(assignee_id), {})
        if quest_id_str in active_char_quests and isinstance(active_char_quests[quest_id_str], dict):
            # Re-serialize the quest_obj to update the dict in _active_quests
            active_char_quests[quest_id_str] = quest_obj.to_dict()
            # Add back contextual info if it was stripped by to_dict
            active_char_quests[quest_id_str].update({
                "character_id": str(assignee_id),
                "template_id": active_char_quests[quest_id_str].get("template_id"), # Preserve existing
                "start_time": active_char_quests[quest_id_str].get("start_time") # Preserve existing
            })
            logger.debug("Updated quest dict in _active_quests for quest %s", quest_id_str)

        return True

    async def _evaluate_abstract_goal(self, guild_id: str, assignee_id: str, quest_obj: Quest, step_obj: QuestStep, event_log_entry: Dict[str, Any]) -> bool:
        # This method evaluates if an event log entry satisfies a step's abstract goal.
        # It now receives QuestStep object directly.
        if not step_obj.abstract_goal_json or step_obj.abstract_goal_json in ('{}', '[]'):
            return False # No goal to evaluate

        try:
            goal_conditions = json.loads(step_obj.abstract_goal_json)
            # Assuming goal_conditions is a dict that RuleEngine can process
            # The context for RuleEngine might need the quest_obj, step_obj, character, etc.
            if self._rule_engine:
                # Build a specific context for this rule evaluation
                eval_context = {
                    "event": event_log_entry,
                    "quest": quest_obj.to_dict(), # Pass quest data as dict
                    "step": step_obj.to_dict(),   # Pass step data as dict
                    "character_id": assignee_id,
                    "guild_id": guild_id,
                    # Potentially add character object, npc objects etc. from managers
                }
                # Example: if self._character_manager: eval_context["character"] = await self._character_manager.get_character(guild_id, assignee_id)

                logger.debug("Evaluating abstract goal for Q:%s S:%s (order %s) with event %s", quest_obj.id, step_obj.id, step_obj.step_order, event_log_entry.get("event_type"))
                return self._rule_engine.evaluate_conditions(goal_conditions, eval_context)
            else:
                logger.warning("RuleEngine not available for evaluating abstract goal of step %s, quest %s", step_obj.id, quest_obj.id)
                return False
        except json.JSONDecodeError as e:
            logger.error("Failed to parse abstract_goal_json for Q:%s S:%s (order %s) in guild %s: %s. JSON: %s",
                         quest_obj.id, step_obj.id, step_obj.step_order, guild_id, e, step_obj.abstract_goal_json, exc_info=True)
            return False
        except Exception as ex: # Catch other rule engine evaluation errors
            logger.error("Error evaluating abstract_goal for Q:%s S:%s (order %s) in guild %s: %s",
                         quest_obj.id, step_obj.id, step_obj.step_order, guild_id, ex, exc_info=True)
            return False


    async def handle_player_event_for_quest(self, guild_id: str, character_id: str, event_data: Dict[str, Any]) -> None: # Signature updated
        guild_id_str, character_id_str = str(guild_id), str(character_id)

        active_char_quests = self._active_quests.get(guild_id_str, {}).get(character_id_str, {})
        if not active_char_quests:
            logger.debug(f"No active quests for character {character_id_str} in guild {guild_id_str} to handle event.")
            return

        logger.info(f"Handling event for quests of character {character_id_str} in guild {guild_id_str}. Event type: {event_data.get('event_type')}")

        # Iterate over a copy of values if quests might be removed during iteration (e.g., upon completion)
        for quest_data_dict in list(active_char_quests.values()):
            quest_id = quest_data_dict.get('id')
            if not quest_id:
                logger.warning(f"Found active quest data without an ID for character {character_id_str}, skipping.")
                continue

            if not isinstance(quest_data_dict, dict):
                logger.warning(f"Quest data for {quest_id} in _active_quests is not a dict for character {character_id_str}, skipping. Data: {quest_data_dict}")
                continue

            current_quest_obj = self._all_quests.get(guild_id_str, {}).get(quest_id)
            if not current_quest_obj:
                logger.debug(f"Quest object for ID {quest_id} not found in _all_quests cache for character {character_id_str}. Reconstructing from _active_quests dict.")
                current_quest_obj = Quest.from_dict(deepcopy(quest_data_dict))
                if not current_quest_obj.steps and quest_data_dict.get('steps'):
                    parsed_steps = []
                    for step_d in quest_data_dict['steps']:
                        step_d.setdefault('guild_id', guild_id_str)
                        step_d.setdefault('quest_id', quest_id)
                        parsed_steps.append(QuestStep.from_dict(step_d))
                    current_quest_obj.steps = parsed_steps

                if not current_quest_obj.steps: # If still no steps, cannot process effectively
                     logger.warning(f"Could not reconstruct Quest {quest_id} with steps from _active_quests dict for character {character_id_str}. Event handling for it might be limited.")
                     # Continue with the partially reconstructed object if basic status check is all that's needed,
                     # or skip if steps are essential for any evaluation. For now, proceed.

            if current_quest_obj.status != 'active':
                logger.debug(f"Quest {quest_id} for character {character_id_str} is not active (status: {current_quest_obj.status}), skipping event handling.")
                continue

            logger.debug(f"Evaluating event for active quest {quest_id} (Character: {character_id_str}).")
            for step_obj in current_quest_obj.steps:
                if step_obj.status == 'pending':
                    logger.debug(f"Checking pending step {step_obj.step_order} ('{step_obj.title_i18n.get(self._default_lang, 'N/A')}') of quest {quest_id}.")

                    should_complete_step = await self._evaluate_abstract_goal(guild_id_str, character_id_str, current_quest_obj, step_obj, event_data)

                    if should_complete_step:
                        logger.info(f"Conditions met for step {step_obj.step_order} of quest {quest_id} for character {character_id_str}.")
                        step_marked_success = await self._mark_step_complete(guild_id_str, character_id_str, current_quest_obj.id, step_obj.step_order)

                        if step_marked_success:
                            logger.info(f"Step {step_obj.step_order} of quest {quest_id} successfully marked complete for character {character_id_str}.")
                            if self._are_all_objectives_complete(current_quest_obj):
                                logger.info(f"All objectives for quest {quest_id} are complete for character {character_id_str}. Completing quest.")
                                await self.complete_quest(guild_id_str, character_id_str, current_quest_obj.id)
                                break # Stop processing steps for this quest as it's now finished.
                        else:
                            logger.warning(f"Failed to mark step {step_obj.step_order} of quest {quest_id} as complete for character {character_id_str} after conditions met.")
                    else:
                        logger.debug(f"Conditions not met for step {step_obj.step_order} of quest {quest_id} based on current event.")

                if current_quest_obj.status != 'active': # Check if quest status changed (e.g., completed)
                    logger.debug(f"Quest {quest_id} no longer active (status: {current_quest_obj.status}) after processing step {step_obj.step_order}. Stopping further step processing for this quest.")
                    break

            if current_quest_obj.status != 'active': # If quest completed, move to next quest for character
                logger.debug(f"Quest {quest_id} is no longer active. Moving to next active quest for character {character_id_str}, if any.")
                # The main loop `for quest_data_dict in list(active_char_quests.values()):` will continue
                # to the next quest. No explicit break here for the outer loop is needed unless a single event
                # should only ever affect one quest.

        logger.debug(f"Finished event handling for character {character_id_str} in guild {guild_id_str}.")


    async def generate_quest_details_from_ai(self, guild_id: str, quest_idea: str, generation_context_obj: "GenerationContext", triggering_entity_id: Optional[str] = None) -> Optional[Quest]:
        logger.info(f"Starting AI quest generation for guild {guild_id}. Idea: '{quest_idea}'. Trigger: {triggering_entity_id if triggering_entity_id else 'N/A'}")

        if not self._multilingual_prompt_generator:
            logger.error(f"MultilingualPromptGenerator not available for AI quest generation in guild {guild_id}.")
            return None
        if not self._openai_service:
            logger.error(f"OpenAIService not available for AI quest generation in guild {guild_id}.")
            return None
        if not self._ai_validator:
            logger.error(f"AIResponseValidator not available for AI quest generation in guild {guild_id}.")
            return None
        if not self._db_service:
            logger.error(f"DBService not available for saving AI quest in guild {guild_id}.")
            return None

        try:
            # 1. Generate Prompts
            prompts = self._multilingual_prompt_generator.generate_quest_prompt(generation_context_obj)
            system_prompt = prompts["system"]
            user_prompt = prompts["user"]
            logger.debug(f"Generated prompts for AI quest in guild {guild_id}. System prompt length: {len(system_prompt)}, User prompt length: {len(user_prompt)}")

            # 2. Call OpenAI Service
            # Assuming generate_structured_multilingual_content returns a dict or None
            ai_response_dict = await self._openai_service.generate_structured_multilingual_content(
                system_prompt, user_prompt, max_tokens=3500, temperature=0.7
            ) # Increased max_tokens, adjusted temperature

            if ai_response_dict is None or "error" in ai_response_dict:
                error_detail = ai_response_dict.get("error") if isinstance(ai_response_dict, dict) else "No response from AI service"
                logger.error(f"AI service failed to generate quest for guild {guild_id}. Idea: '{quest_idea}'. Error: {error_detail}")
                return None

            logger.debug(f"Received AI response for quest generation in guild {guild_id}. Response keys: {list(ai_response_dict.keys())}")

            # 3. Validate AI Response
            ai_json_string = json.dumps(ai_response_dict)
            validation_result = self._ai_validator.validate_ai_response(
                ai_json_string,
                expected_structure="single_quest",
                generation_context=generation_context_obj
            )

            if validation_result.overall_status in ["error", "requires_moderation"] or not validation_result.entities:
                logger.error(f"AI Quest validation failed or requires moderation for guild {guild_id}. Status: {validation_result.overall_status}. Issues: {validation_result.global_errors}. Entity issues: {[e.issues for e in validation_result.entities]}")
                # TODO: Potentially save quests requiring moderation to a separate table/state if desired.
                return None

            # Assuming "success" or "success_with_autocorrections" and one entity for "single_quest"
            validated_quest_dict = validation_result.entities[0].data
            logger.info(f"AI quest successfully validated for guild {guild_id}. Status: {validation_result.overall_status}.")
            if validation_result.overall_status == "success_with_autocorrections":
                logger.info(f"Autocorrections applied: {[e.issues for e in validation_result.entities if e.issues]}")


            # 4. Process and Save Validated Quest
            validated_quest_dict['guild_id'] = guild_id  # Ensure guild_id is set from the request context
            validated_quest_dict['is_ai_generated'] = True # Mark as AI generated

            # Ensure a unique ID for the quest. Override AI's ID if it provided one, or generate if missing.
            original_ai_id = validated_quest_dict.get('id')
            new_quest_id = str(uuid.uuid4())
            validated_quest_dict['id'] = new_quest_id
            if original_ai_id:
                 logger.info(f"Overriding AI provided quest ID '{original_ai_id}' with new UUID '{new_quest_id}' for guild {guild_id}.")

            # Create Pydantic Quest object
            # Quest.from_dict will handle creating QuestStep objects from the 'steps' list of dicts.
            # It also ensures the main quest_obj has guild_id.
            quest_to_save = Quest.from_dict(validated_quest_dict)

            # Explicitly set quest_id and guild_id for each step.
            # Quest.from_dict (if updated per instructions) should inject quest_id and guild_id into steps if they are missing.
            # However, double-checking and ensuring here before save provides an extra layer of safety.
            for step_obj in quest_to_save.steps:
                if not step_obj.id:
                    step_obj.id = str(uuid.uuid4())
                step_obj.quest_id = quest_to_save.id # Assign parent quest ID
                step_obj.guild_id = quest_to_save.guild_id # Assign parent quest guild ID

            save_success = await self.save_generated_quest(quest_to_save)

            if save_success:
                self._all_quests.setdefault(guild_id, {})[quest_to_save.id] = quest_to_save
                logger.info(f"Successfully generated, validated, and saved AI quest '{quest_to_save.id}' (Name: {quest_to_save.name_i18n.get(self._default_lang, 'N/A')}) for guild {guild_id}.")
                return quest_to_save
            else:
                logger.error(f"Failed to save AI generated quest {quest_to_save.id} for guild {guild_id} after successful validation.")
                return None

        except Exception as e:
            logger.error(f"Unexpected error during AI quest generation for guild {guild_id}, idea '{quest_idea}': {e}", exc_info=True)
            return None

    async def handle_player_event_for_quest(self, guild_id: str, character_id: str, event_data: Dict[str, Any]) -> None: # Signature updated
        guild_id_str, character_id_str = str(guild_id), str(character_id)

        active_char_quests = self._active_quests.get(guild_id_str, {}).get(character_id_str, {})
        if not active_char_quests:
            logger.debug(f"No active quests for character {character_id_str} in guild {guild_id_str} to handle event.")
            return

        logger.info(f"Handling event for quests of character {character_id_str} in guild {guild_id_str}. Event type: {event_data.get('event_type')}")

        # Iterate over a copy of values if quests might be removed during iteration (e.g., upon completion)
        for quest_data_dict in list(active_char_quests.values()):
            quest_id = quest_data_dict.get('id')
            if not quest_id:
                logger.warning(f"Found active quest data without an ID for character {character_id_str}, skipping.")
                continue

            if not isinstance(quest_data_dict, dict):
                logger.warning(f"Quest data for {quest_id} in _active_quests is not a dict for character {character_id_str}, skipping. Data: {quest_data_dict}")
                continue

            current_quest_obj = self._all_quests.get(guild_id_str, {}).get(quest_id)
            if not current_quest_obj:
                logger.debug(f"Quest object for ID {quest_id} not found in _all_quests cache for character {character_id_str}. Reconstructing from _active_quests dict.")
                current_quest_obj = Quest.from_dict(deepcopy(quest_data_dict))
                if not current_quest_obj.steps and quest_data_dict.get('steps'):
                    parsed_steps = []
                    for step_d in quest_data_dict['steps']:
                        step_d.setdefault('guild_id', guild_id_str)
                        step_d.setdefault('quest_id', quest_id)
                        parsed_steps.append(QuestStep.from_dict(step_d))
                    current_quest_obj.steps = parsed_steps

                if not current_quest_obj.steps: # If still no steps, cannot process effectively
                     logger.warning(f"Could not reconstruct Quest {quest_id} with steps from _active_quests dict for character {character_id_str}. Event handling for it might be limited.")
                     # Continue with the partially reconstructed object if basic status check is all that's needed,
                     # or skip if steps are essential for any evaluation. For now, proceed.

            if current_quest_obj.status != 'active':
                logger.debug(f"Quest {quest_id} for character {character_id_str} is not active (status: {current_quest_obj.status}), skipping event handling.")
                continue

            logger.debug(f"Evaluating event for active quest {quest_id} (Character: {character_id_str}).")
            for step_obj in current_quest_obj.steps:
                if step_obj.status == 'pending':
                    logger.debug(f"Checking pending step {step_obj.step_order} ('{step_obj.title_i18n.get(self._default_lang, 'N/A')}') of quest {quest_id}.")

                    should_complete_step = await self._evaluate_abstract_goal(guild_id_str, character_id_str, current_quest_obj, step_obj, event_data)

                    if should_complete_step:
                        logger.info(f"Conditions met for step {step_obj.step_order} of quest {quest_id} for character {character_id_str}.")
                        step_marked_success = await self._mark_step_complete(guild_id_str, character_id_str, current_quest_obj.id, step_obj.step_order)

                        if step_marked_success:
                            logger.info(f"Step {step_obj.step_order} of quest {quest_id} successfully marked complete for character {character_id_str}.")
                            if self._are_all_objectives_complete(current_quest_obj):
                                logger.info(f"All objectives for quest {quest_id} are complete for character {character_id_str}. Completing quest.")
                                await self.complete_quest(guild_id_str, character_id_str, current_quest_obj.id)
                                break # Stop processing steps for this quest as it's now finished.
                        else:
                            logger.warning(f"Failed to mark step {step_obj.step_order} of quest {quest_id} as complete for character {character_id_str} after conditions met.")
                    else:
                        logger.debug(f"Conditions not met for step {step_obj.step_order} of quest {quest_id} based on current event.")

                if current_quest_obj.status != 'active': # Check if quest status changed (e.g., completed)
                    logger.debug(f"Quest {quest_id} no longer active (status: {current_quest_obj.status}) after processing step {step_obj.step_order}. Stopping further step processing for this quest.")
                    break

            if current_quest_obj.status != 'active': # If quest completed, move to next quest for character
                logger.debug(f"Quest {quest_id} is no longer active. Moving to next active quest for character {character_id_str}, if any.")
                # The main loop `for quest_data_dict in list(active_char_quests.values()):` will continue
                # to the next quest. No explicit break here for the outer loop is needed unless a single event
                # should only ever affect one quest.

        logger.debug(f"Finished event handling for character {character_id_str} in guild {guild_id_str}.")


    def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool: # Sync version
        guild_id_str, character_id_str, quest_id_str = str(guild_id), str(character_id), str(quest_id)
        logger.info("Attempting to complete quest %s for char %s in guild %s (sync).", quest_id_str, character_id_str, guild_id_str) # Added guild_id
        # ... (rest of sync complete_quest logic, ensure guild_id_str in logs for errors/warnings) ...
        return False # Placeholder

    async def complete_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool: # Async version
        guild_id_str, character_id_str, quest_id_str = str(guild_id), str(character_id), str(quest_id)
        logger.info("Attempting to complete quest %s for char %s in guild %s (async).", quest_id_str, character_id_str, guild_id_str)

        quest_obj = self._all_quests.get(guild_id_str, {}).get(quest_id_str)
        active_quest_dict = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)

        if not quest_obj and active_quest_dict: # If not in _all_quests, try to reconstruct from _active_quests
            logger.info("Quest %s not in _all_quests, reconstructing from _active_quests dict for completion.", quest_id_str)
            quest_obj = Quest.from_dict(deepcopy(active_quest_dict))
            # Ensure steps are loaded if they were in the dict
            if not quest_obj.steps and active_quest_dict.get('steps'):
                 parsed_steps = []
                 for step_d in active_quest_dict['steps']:
                     step_d.setdefault('guild_id', guild_id_str)
                     step_d.setdefault('quest_id', quest_id_str)
                     parsed_steps.append(QuestStep.from_dict(step_d))
                 quest_obj.steps = parsed_steps


        if not quest_obj:
            logger.error("Quest %s not found for character %s in guild %s to complete.", quest_id_str, character_id_str, guild_id_str)
            return False

        if quest_obj.status == 'completed':
            logger.info("Quest %s already completed for char %s in guild %s.", quest_id_str, character_id_str, guild_id_str)
            return True # Already completed

        # Ensure all objectives are actually met before completing
        if not self._are_all_objectives_complete(quest_obj):
            logger.warning("Attempt to complete quest %s for char %s (guild %s), but not all objectives are met.", quest_id_str, character_id_str, guild_id_str)
            # Optionally, mark all pending steps complete if desired, or just return False
            return False

        original_status = quest_obj.status
        quest_obj.status = 'completed'

        # Persist quest status change to DB
        db_updated = False
        if self._db_service and self._db_service.adapter:
            table_name = 'generated_quests' if quest_obj.is_ai_generated else 'quests'
            try:
                update_sql = f"UPDATE {table_name} SET status = $1 WHERE id = $2 AND guild_id = $3"
                await self._db_service.adapter.execute(update_sql, ('completed', quest_id_str, guild_id_str))
                logger.info("Successfully updated status to 'completed' in DB for quest %s (table: %s).", quest_id_str, table_name)
                db_updated = True
            except Exception as e_db:
                logger.error("Failed to update status to 'completed' in DB for quest %s (guild %s, table: %s): %s", quest_id_str, guild_id_str, table_name, e_db, exc_info=True)
                quest_obj.status = original_status # Revert Pydantic model status
                return False # Failed to persist
        else:
            logger.warning("DBService not available, quest %s status update to 'completed' not persisted to DB.", quest_id_str)
            # Decide if in-memory change is allowed if DB fails. For now, it is, but Pydantic model was reverted if DB error.
            # If no DB service, effectively it's in-memory only.

        # Process overall quest consequences
        if quest_obj.consequences_json_str and quest_obj.consequences_json_str not in ('{}', '[]'):
            if self._consequence_processor:
                consequence_context = self._build_consequence_context(guild_id_str, character_id_str, quest_obj)
                logger.debug("Processing overall consequences for quest %s. Context: %s", quest_id_str, consequence_context)
                asyncio.create_task(self._consequence_processor.process_consequences(
                    guild_id_str,
                    quest_obj.consequences_json_str,
                    consequence_context,
                    actor_id=character_id_str
                ))
            else:
                logger.warning("ConsequenceProcessor not available for overall consequences of quest %s.", quest_id_str)

        # Update caches
        self._completed_quests.setdefault(guild_id_str, {}).setdefault(character_id_str, []).append(quest_id_str)
        if character_id_str in self._active_quests.get(guild_id_str, {}):
            if quest_id_str in self._active_quests[guild_id_str][character_id_str]:
                del self._active_quests[guild_id_str][character_id_str][quest_id_str]
                logger.info("Removed quest %s from active list for char %s, guild %s.", quest_id_str, character_id_str, guild_id_str)
            if not self._active_quests[guild_id_str][character_id_str]: # Clean up empty dict
                del self._active_quests[guild_id_str][character_id_str]

        if self._game_log_manager:
            asyncio.create_task(self._game_log_manager.log_event(guild_id_str, "QUEST_COMPLETED", {"quest_id": quest_id_str}, player_id=character_id_str))

        logger.info("Quest %s completed for char %s in guild %s.", quest_id_str, character_id_str, guild_id_str)
        return True


    def fail_quest(self, guild_id: str, character_id: str, quest_id: str) -> bool: # Sync version for now, make async if DB calls become async
        guild_id_str, character_id_str, quest_id_str = str(guild_id), str(character_id), str(quest_id)
        logger.info("Failing quest %s for char %s in guild %s.", quest_id_str, character_id_str, guild_id_str)

        quest_obj = self._all_quests.get(guild_id_str, {}).get(quest_id_str)
        active_quest_dict = self._active_quests.get(guild_id_str, {}).get(character_id_str, {}).get(quest_id_str)

        if not quest_obj and active_quest_dict:
            logger.info("Quest %s not in _all_quests, reconstructing from _active_quests dict for failing.", quest_id_str)
            quest_obj = Quest.from_dict(deepcopy(active_quest_dict))
            # Steps might not be needed for fail, but if they were, load them similarly to complete_quest

        if not quest_obj:
            logger.error("Quest %s not found for character %s in guild %s to fail.", quest_id_str, character_id_str, guild_id_str)
            return False

        if quest_obj.status == 'failed':
            logger.info("Quest %s already failed for char %s in guild %s.", quest_id_str, character_id_str, guild_id_str)
            return True

        original_status = quest_obj.status
        quest_obj.status = 'failed'

        # Persist quest status change to DB (using asyncio.create_task for async DB call from sync method if needed)
        db_updated = False
        if self._db_service and self._db_service.adapter:
            table_name = 'generated_quests' if quest_obj.is_ai_generated else 'quests'
            try:
                # This should be an async call if fail_quest is async.
                # If fail_quest remains sync, this DB call needs to be blocking or handled carefully.
                # For now, let's assume it can be made async like others, or QuestManager becomes fully async.
                async def _update_db_fail_status():
                    update_sql = f"UPDATE {table_name} SET status = $1 WHERE id = $2 AND guild_id = $3"
                    await self._db_service.adapter.execute(update_sql, ('failed', quest_id_str, guild_id_str))
                    logger.info("Successfully updated status to 'failed' in DB for quest %s (table: %s).", quest_id_str, table_name)
                # Running async code from sync like this is generally not recommended.
                # This suggests fail_quest should be an async method.
                # For the purpose of this refactor, I'll write it as if it can call async.
                # If this manager is run in an asyncio loop, this might work via ensure_future or create_task.
                # However, the method signature is sync. This part highlights a design consideration.
                # Let's assume for now this part of DB update is best-effort or needs fail_quest to be async.
                # For now, I'll log a warning about the sync nature.
                logger.warning("DB update for fail_quest is async; actual execution depends on context. Quest: %s", quest_id_str)
                asyncio.create_task(_update_db_fail_status()) # Fire-and-forget (problematic for error handling)
                db_updated = True # Assume it will work for now for flow
            except Exception as e_db:
                logger.error("Error submitting DB update for status to 'failed' for quest %s (guild %s, table: %s): %s", quest_id_str, guild_id_str, table_name, e_db, exc_info=True)
                quest_obj.status = original_status # Revert
                return False
        else:
            logger.warning("DBService not available, quest %s status update to 'failed' not persisted to DB.", quest_id_str)

        # Update caches
        # Similar to complete_quest, remove from active, add to a failed list if needed (not currently implemented)
        if character_id_str in self._active_quests.get(guild_id_str, {}):
            if quest_id_str in self._active_quests[guild_id_str][character_id_str]:
                del self._active_quests[guild_id_str][character_id_str][quest_id_str]
                logger.info("Removed quest %s from active list for char %s, guild %s upon failing.", quest_id_str, character_id_str, guild_id_str)
            if not self._active_quests[guild_id_str][character_id_str]:
                 del self._active_quests[guild_id_str][character_id_str]

        if self._game_log_manager:
             asyncio.create_task(self._game_log_manager.log_event(guild_id_str, "QUEST_FAILED", {"quest_id": quest_id_str}, player_id=character_id_str))

        logger.info("Quest %s failed for char %s in guild %s.", quest_id_str, character_id_str, guild_id_str)
        return True

    async def generate_and_save_quest(
        self,
        guild_id: str,
        context_details: Dict[str, Any]
    ) -> Optional[DBGeneratedQuest]:
        """
        Generates a new quest using AI based on context_details,
        validates the response, and saves the valid quest and its steps to the database.

        Args:
            guild_id: The ID of the guild for which to generate the quest.
            context_details: A dictionary containing contextual details to guide quest generation
                             (e.g., player_id, location_id, theme, difficulty_hint).

        Returns:
            The successfully created and saved DBGeneratedQuest object (with steps potentially
            accessible via relationship after refresh, though this method focuses on saving),
            or None if any part of the process fails.
        """
        log_prefix = f"QuestGeneration (Guild: {guild_id})"
        logger.info(f"{log_prefix}: Starting quest generation with context: {context_details}.")

        # 1. Access Services via self.game_manager
        if not self.game_manager: # Should have been caught by __init__ critical log
            logger.error(f"{log_prefix}: GameManager not available.")
            return None

        # Check for individual services on game_manager
        services_to_check = {
            "multilingual_prompt_generator": self.game_manager.multilingual_prompt_generator,
            "openai_service": self.game_manager.openai_service,
            "ai_response_validator": self.game_manager.ai_response_validator,
            "db_service": self.game_manager.db_service # or self._db_service if preferred
        }
        for service_name, service_instance in services_to_check.items():
            if not service_instance:
                logger.error(f"{log_prefix}: Service '{service_name}' is missing from GameManager.")
                return None

        prompt_generator = self.game_manager.multilingual_prompt_generator
        openai_service = self.game_manager.openai_service
        validator = self.game_manager.ai_response_validator
        db_service = self.game_manager.db_service # Using game_manager's instance for consistency

        created_quest_db: Optional[DBGeneratedQuest] = None

        async with db_service.get_session() as session:
            try:
                # 2. Prepare Prompt
                logger.debug(f"{log_prefix}: Preparing quest generation prompt.")
                prompt = await prompt_generator.prepare_quest_generation_prompt(
                    guild_id, session, self.game_manager, context_details
                )
                if not prompt or prompt.startswith("Error:"):
                    logger.error(f"{log_prefix}: Failed to generate prompt. Details: {prompt}")
                    return None
                logger.debug(f"{log_prefix}: Prompt generated (first 300 chars): {prompt[:300]}...")

                # 3. Call OpenAI Service
                logger.debug(f"{log_prefix}: Requesting completion from OpenAI.")
                raw_ai_output = await openai_service.get_completion(prompt_text=prompt)
                if not raw_ai_output:
                    logger.error(f"{log_prefix}: AI service returned no output.")
                    return None
                logger.debug(f"{log_prefix}: Raw AI output received (first 100 chars): {raw_ai_output[:100]}")

                # 4. Validate AI Response
                logger.debug(f"{log_prefix}: Validating AI response for quest.")
                # This returns a Dict[str, Any] representing the 'quest_data' part of the AI response
                validated_quest_data = await validator.parse_and_validate_quest_generation_response(
                    raw_ai_output, guild_id, self.game_manager
                )
                if not validated_quest_data:
                    logger.error(f"{log_prefix}: AI response validation failed for quest. Raw output: {raw_ai_output}")
                    return None
                logger.info(f"{log_prefix}: AI quest response validated successfully.")

                # 5. Create and Save Quest and Step Entities
                main_quest_id = str(uuid.uuid4())

                quest_model_data = {
                    "id": main_quest_id,
                    "guild_id": guild_id,
                    "title_i18n": validated_quest_data.get("title_i18n"),
                    "description_i18n": validated_quest_data.get("description_i18n"),
                    "suggested_level": validated_quest_data.get("suggested_level"),
                    "rewards_json": validated_quest_data.get("rewards_json"), # Already validated as JSON string
                    "prerequisites_json": validated_quest_data.get("prerequisites_json"), # Already validated as JSON string
                    "consequences_json": validated_quest_data.get("consequences_json"), # Already validated as JSON string
                    "quest_giver_details_i18n": validated_quest_data.get("quest_giver_details_i18n"),
                    "status": "available", # Default status for new quests
                    # Ensure any other fields expected by DBGeneratedQuest model are included or have defaults
                }
                # Filter out None values for fields that are nullable in the DB model
                quest_model_data = {k: v for k, v in quest_model_data.items() if v is not None}


                new_quest_db = DBGeneratedQuest(**quest_model_data)
                session.add(new_quest_db)
                logger.debug(f"{log_prefix}: Prepared main quest {main_quest_id} for saving.")

                created_steps_db: List[DBQuestStepTable] = []
                for i, step_data in enumerate(validated_quest_data.get("steps", [])):
                    step_model_data = {
                        "id": str(uuid.uuid4()),
                        "guild_id": guild_id,
                        "quest_id": main_quest_id,
                        "title_i18n": step_data.get("title_i18n"),
                        "description_i18n": step_data.get("description_i18n"),
                        "required_mechanics_json": step_data.get("required_mechanics_json"), # Validated JSON string
                        "abstract_goal_json": step_data.get("abstract_goal_json"), # Validated JSON string
                        "consequences_json": step_data.get("consequences_json"), # Validated JSON string
                        "step_order": step_data.get("step_order", i), # Use provided order or default to index
                        "status": "pending", # Default status for new steps
                    }
                    # Filter out None values for fields that are nullable in the DB model
                    step_model_data = {k: v for k, v in step_model_data.items() if v is not None}

                    new_step_db = DBQuestStepTable(**step_model_data)
                    session.add(new_step_db)
                    created_steps_db.append(new_step_db)

                logger.debug(f"{log_prefix}: Prepared {len(created_steps_db)} steps for quest {main_quest_id}.")

                await session.commit()
                logger.info(f"{log_prefix}: Successfully generated and saved quest '{main_quest_id}' with {len(created_steps_db)} steps to DB.")

                # Refresh the main quest object to load relationships (like steps) if configured
                await session.refresh(new_quest_db)
                # To access steps via new_quest_db.steps, the relationship needs to be loaded,
                # which might require specific loader options or another refresh with those options.
                # For now, returning the main quest object.

                created_quest_db = new_quest_db

            except Exception as e:
                logger.error(f"{log_prefix}: Error during quest generation and saving pipeline: {e}", exc_info=True)
                if 'session' in locals() and session.is_active: # Check if session was defined and is active
                    await session.rollback()
                return None # Explicitly return None on error

        return created_quest_db
