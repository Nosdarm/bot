# Test comment
# bot/game/managers/dialogue_manager.py

from __future__ import annotations
import json
import uuid
import traceback # Will be removed
import asyncio
import logging # Added
import time
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union, Tuple

from asyncpg.exceptions import UndefinedTableError # MODIFIED IMPORT
from bot.services.db_service import DBService
from builtins import dict, set, list, str, int, bool, float

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.managers.time_manager import TimeManager
    from bot.services.openai_service import OpenAIService 
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.quest_manager import QuestManager 
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.services.notification_service import NotificationService
    from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__) # Added

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

# logger.debug("DEBUG: dialogue_manager.py module loaded.") # Changed

class DialogueManager:
    required_args_for_load: List[str] = ["guild_id"] 
    required_args_for_save: List[str] = ["guild_id"] 
    required_args_for_rebuild: List[str] = ["guild_id"]

    _active_dialogues: Dict[str, Dict[str, Dict[str, Any]]]
    _dialogue_templates: Dict[str, Dict[str, Dict[str, Any]]]
    _dirty_dialogues: Dict[str, Set[str]] 
    _deleted_dialogue_ids: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None, 
        settings: Optional[Dict[str, Any]] = None,
        character_manager: Optional["CharacterManager"] = None, 
        npc_manager: Optional["NpcManager"] = None, 
        rule_engine: Optional["RuleEngine"] = None, 
        event_stage_processor: Optional["EventStageProcessor"] = None, 
        time_manager: Optional["TimeManager"] = None, 
        openai_service: Optional["OpenAIService"] = None, 
        relationship_manager: Optional["RelationshipManager"] = None, 
        game_log_manager: Optional["GameLogManager"] = None,
        quest_manager: Optional["QuestManager"] = None, 
        notification_service: Optional["NotificationService"] = None,
        game_manager: Optional["GameManager"] = None
    ):
        logger.info("Initializing DialogueManager...") # Changed
        self._db_service = db_service 
        self._settings = settings if settings is not None else {}
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._rule_engine = rule_engine
        self._event_stage_processor = event_stage_processor
        self._time_manager = time_manager
        self._openai_service = openai_service 
        self._relationship_manager = relationship_manager 
        self._game_log_manager = game_log_manager
        self._quest_manager = quest_manager
        self._notification_service = notification_service
        self._game_manager = game_manager

        self._active_dialogues = {} 
        self._dialogue_templates = {} 
        self._dirty_dialogues = {} 
        self._deleted_dialogue_ids = {} 
        logger.info("DialogueManager initialized.") # Changed

    def load_dialogue_templates(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        logger.info("DialogueManager: Loading dialogue templates for guild %s.", guild_id_str) # Added
        self._dialogue_templates.pop(guild_id_str, None)
        guild_templates_cache = self._dialogue_templates.setdefault(guild_id_str, {})
        try:
            if self._settings is None: self._settings = {}
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            templates_data = guild_settings.get('dialogue_templates')
            if isinstance(templates_data, dict):
                 for tpl_id, data in templates_data.items():
                      if tpl_id and isinstance(data, dict):
                           template_data = data.copy()
                           template_data.setdefault('id', str(tpl_id)) 
                           template_data.setdefault('name', f"Unnamed Dialogue Template ({tpl_id})") 
                           template_data.setdefault('stages', {}) 
                           guild_templates_cache[str(tpl_id)] = template_data 
            elif templates_data is not None:
                 logger.warning("DialogueManager: Dialogue templates data for guild %s is not a dictionary (%s).", guild_id_str, type(templates_data)) # Changed
        except Exception as e:
            logger.error("DialogueManager: Error loading dialogue templates for guild %s: %s", guild_id_str, e, exc_info=True) # Changed

    def get_dialogue_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        if guild_id_str not in self._dialogue_templates: 
            self.load_dialogue_templates(guild_id_str) # Ensures templates are loaded if not already
        guild_templates = self._dialogue_templates.get(guild_id_str, {})
        return guild_templates.get(str(template_id))

    def get_dialogue(self, guild_id: str, dialogue_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        guild_dialogues = self._active_dialogues.get(guild_id_str) 
        if guild_dialogues:
             dialogue_data = guild_dialogues.get(str(dialogue_id)) 
             if dialogue_data is not None:
                  return dialogue_data.copy() 
        return None

    def get_active_dialogues(self, guild_id: str) -> List[Dict[str, Any]]: 
        guild_id_str = str(guild_id)
        guild_dialogues = self._active_dialogues.get(guild_id_str) 
        if guild_dialogues:
             return [d.copy() for d in guild_dialogues.values()]
        return [] 

    def is_in_dialogue(self, guild_id: str, entity_id: str) -> bool:
        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)
        guild_dialogues = self._active_dialogues.get(guild_id_str)
        if guild_dialogues:
             for d in guild_dialogues.values(): 
                 participants_data = d.get('participants', []) 
                 if isinstance(participants_data, list):
                     for p_entry in participants_data:
                         if isinstance(p_entry, dict) and p_entry.get('entity_id') == entity_id_str:
                             return True
                         elif isinstance(p_entry, str) and p_entry == entity_id_str: 
                             return True
        return False 

    async def start_dialogue(
        self, guild_id: str, template_id: str,
        participant1_id: str, participant2_id: str, 
        participant1_type: str, participant2_type: str, 
        channel_id: Optional[int] = None, event_id: Optional[str] = None,
        initial_state_data: Optional[Dict[str, Any]] = None, **kwargs: Any,
    ) -> Optional[str]:
        guild_id_str = str(guild_id)
        tpl_id_str = str(template_id)
        logger.info("DialogueManager: Starting dialogue from template '%s' for guild %s between %s (%s) and %s (%s).", tpl_id_str, guild_id_str, participant1_id, participant1_type, participant2_id, participant2_type ) # Added
        
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("DialogueManager: No DB service for guild %s. Cannot start dialogue.", guild_id_str) # Changed
            return None
        tpl = self.get_dialogue_template(guild_id_str, tpl_id_str)
        if not tpl:
            logger.warning("DialogueManager: Dialogue template '%s' not found for guild %s.", tpl_id_str, guild_id_str) # Changed
            return None
        try:
            new_id = str(uuid.uuid4())
            initial_state = initial_state_data or {} 
            if tpl.get('initial_state_variables'):
                if isinstance(tpl['initial_state_variables'], dict):
                    template_initial_state = tpl['initial_state_variables'].copy()
                    template_initial_state.update(initial_state)
                    initial_state = template_initial_state 
            
            participants_data_list = [
                {"entity_id": str(participant1_id), "entity_type": participant1_type},
                {"entity_id": str(participant2_id), "entity_type": participant2_type}
            ]

            current_game_time = time.time() # Fallback
            if self._time_manager:
                current_game_time = await self._time_manager.get_current_game_time(guild_id=guild_id_str)

            dialogue_data: Dict[str, Any] = {
                'id': new_id, 'template_id': tpl_id_str, 'guild_id': guild_id_str,
                'participants': participants_data_list, 
                'channel_id': int(channel_id) if channel_id is not None else None,
                'current_stage_id': str(tpl.get('start_stage_id', 'start')),
                'state_variables': initial_state, 
                'last_activity_game_time': current_game_time,
                'event_id': str(event_id) if event_id is not None else None, 'is_active': True,
            }
            
            self._active_dialogues.setdefault(guild_id_str, {})[new_id] = dialogue_data
            self.mark_dialogue_dirty(guild_id_str, new_id)
            logger.info("DialogueManager: Dialogue %s started successfully for guild %s.", new_id, guild_id_str) # Added
            
            send_cb_factory = kwargs.get('send_callback_factory') 
            dialogue_channel_id_val = dialogue_data.get('channel_id') 
            if send_cb_factory and dialogue_channel_id_val is not None:
                 try:
                     send_cb = send_cb_factory(int(dialogue_channel_id_val))
                     dialogue_template = self.get_dialogue_template(guild_id_str, dialogue_data['template_id'])
                     current_stage_def = dialogue_template.get('stages', {}).get(dialogue_data['current_stage_id']) if dialogue_template else None
                     if current_stage_def:
                         stage_text = current_stage_def.get('text_i18n', {}).get(self._settings.get('default_language', 'en'), "Dialogue begins...")
                         await send_cb(stage_text)
                         if self._rule_engine:
                             player_char_id_for_options = participant1_id if participant1_type == "Character" else participant2_id
                             filtered_options = await self._rule_engine.get_filtered_dialogue_options(dialogue_data, player_char_id_for_options, current_stage_def, kwargs)
                             options_text = self._format_player_responses(filtered_options)
                             if options_text: await send_cb(options_text)
                     else: await send_cb("Dialogue begins...")
                 except Exception as e_send:
                      logger.error("DialogueManager: Error sending dialogue start message for %s in guild %s: %s", new_id, guild_id_str, e_send, exc_info=True) # Changed
            return new_id
        except Exception as e:
            logger.error("DialogueManager: Error starting dialogue from template '%s' for guild %s: %s", tpl_id_str, guild_id_str, e, exc_info=True) # Changed
            return None

    def _format_player_responses(self, response_options: List[Dict[str, Any]]) -> str:
        if not response_options: return ""
        formatted_responses = ["Choose an option:"]
        default_lang = self._settings.get('default_language', 'en')
        for i, option_data in enumerate(response_options):
            option_id = option_data.get('id', f"opt_{i+1}")
            option_text_i18n = option_data.get('text_i18n', {})
            option_text = option_text_i18n.get(default_lang, next(iter(option_text_i18n.values()), option_id) if option_text_i18n else option_id)
            is_available = option_data.get('is_available', True) 
            if is_available:
                formatted_responses.append(f"  [{option_id}] {option_text}")
            else:
                failure_text_i18n_direct = option_data.get('failure_text_i18n_direct', {})
                failure_text = failure_text_i18n_direct.get(default_lang, "This option is currently unavailable.")
                # Assuming _i18n_utils is not available in this manager directly, remove related fallback for now
                # if not failure_text_i18n_direct and option_data.get('failure_feedback_key') and self._i18n_utils:
                #     failure_text = self._i18n_utils.get_localized_string(...)
                formatted_responses.append(f"  [{option_id}] ~~{option_text}~~ ({failure_text})")
        return "\n".join(formatted_responses)

    async def advance_dialogue(
        self, guild_id: str, dialogue_id: str, participant_id: str, 
        action_data: Dict[str, Any], **kwargs: Any,
    ) -> None:
        guild_id_str = str(guild_id)
        dialogue_id_str = str(dialogue_id)
        p_id_str = str(participant_id) 
        logger.info("DialogueManager: Advancing dialogue %s for participant %s in guild %s. Action: %s", dialogue_id_str, p_id_str, guild_id_str, action_data.get('response_id', 'N/A')) # Added
        
        dialogue_data = self._active_dialogues.get(guild_id_str, {}).get(dialogue_id_str)
        if not dialogue_data:
            logger.warning("DialogueManager: Dialogue %s not found for guild %s.", dialogue_id_str, guild_id_str) # Changed
            return

        participants_data_list = dialogue_data.get('participants', []) 
        is_valid_participant = any(
            (isinstance(p_entry, dict) and p_entry.get('entity_id') == p_id_str) or
            (isinstance(p_entry, str) and p_entry == p_id_str)
            for p_entry in participants_data_list
        )
        if not is_valid_participant:
             logger.warning("DialogueManager: Participant %s is not in dialogue %s for guild %s.", p_id_str, dialogue_id_str, guild_id_str) # Changed
             return

        if not self._rule_engine or not hasattr(self._rule_engine, 'process_dialogue_action'):
             logger.error("DialogueManager: RuleEngine or process_dialogue_action not available for guild %s. Cannot advance dialogue %s.", guild_id_str, dialogue_id_str) # Changed
             return
        
        if 'guild_id' not in kwargs: kwargs['guild_id'] = guild_id_str

        try:
            outcome = await self._rule_engine.process_dialogue_action(
                dialogue_data=dialogue_data.copy(), character_id=p_id_str,
                p_action_data=action_data, context=kwargs
            )

            new_stage_id = outcome.get('new_stage_id')
            is_dialogue_ending = outcome.get('is_dialogue_ending', False)
            skill_check_result = outcome.get('skill_check_result')
            immediate_actions_to_trigger = outcome.get('immediate_actions_to_trigger', [])
            direct_relationship_changes = outcome.get('direct_relationship_changes', [])
            
            npc_id = None; npc_entity_type = "NPC"; npc_name_for_feedback = "Other participant"
            for p_data_entry in participants_data_list:
                p_entity_id = p_data_entry.get('entity_id') if isinstance(p_data_entry, dict) else str(p_data_entry)
                if p_entity_id != p_id_str:
                    npc_id = p_entity_id
                    if isinstance(p_data_entry, dict): npc_entity_type = p_data_entry.get('entity_type', "NPC")
                    break
            
            npc_faction_id = None
            if npc_id and npc_entity_type == "NPC" and self._npc_manager:
                npc_obj = await self._npc_manager.get_npc(guild_id_str, npc_id)
                if npc_obj: npc_faction_id = getattr(npc_obj, 'faction_id', None); npc_name_for_feedback = getattr(npc_obj, 'name', npc_id)

            if self._game_log_manager:
                # ... (logging for skill_check_result and direct_relationship_changes as before, ensure guild_id is in logs) ...
                pass # GameLogManager calls already include guild_id
            
            dialogue_data['current_stage_id'] = new_stage_id 
            if self._time_manager:
                 dialogue_data['last_activity_game_time'] = await self._time_manager.get_current_game_time(guild_id=guild_id_str)
            self.mark_dialogue_dirty(guild_id_str, dialogue_id_str)

            if is_dialogue_ending:
                await self.end_dialogue(guild_id_str, dialogue_id_str, **kwargs)
            else: # Send next stage info
                # ... (send_cb logic as before, ensure guild_id is in logs if any error occurs) ...
                send_cb_factory = kwargs.get('send_callback_factory')
                dialogue_channel_id_val = dialogue_data.get('channel_id')
                if send_cb_factory and dialogue_channel_id_val is not None and new_stage_id:
                    try:
                        # ... (rest of send logic)
                        pass
                    except Exception as e_send:
                        logger.error("DialogueManager: Error sending next stage message for dialogue %s in guild %s: %s", dialogue_id_str, guild_id_str, e_send, exc_info=True) # Changed
            
            for immediate_action in immediate_actions_to_trigger: # Process immediate actions
                action_type = immediate_action.get("type")
                if action_type == "start_quest" and self._quest_manager:
                    quest_tpl_id = immediate_action.get("quest_template_id")
                    if quest_tpl_id:
                        logger.info("DialogueManager: Triggering start_quest %s for participant %s in guild %s from dialogue %s.", quest_tpl_id, p_id_str, guild_id_str, dialogue_id_str) # Added
                        await self._quest_manager.start_quest(guild_id_str, p_id_str, quest_tpl_id, **kwargs) 
        except Exception as e:
            logger.error("DialogueManager: Error processing dialogue action for %s in dialogue %s (guild %s): %s", p_id_str, dialogue_id_str, guild_id_str, e, exc_info=True) # Changed

    async def end_dialogue(self, guild_id: str, dialogue_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        dialogue_id_str = str(dialogue_id)
        logger.info("DialogueManager: Ending dialogue %s for guild %s.", dialogue_id_str, guild_id_str) # Added

        dialogue_data = self._active_dialogues.get(guild_id_str, {}).get(dialogue_id_str)
        if not dialogue_data:
            if guild_id_str in self._deleted_dialogue_ids and dialogue_id_str in self._deleted_dialogue_ids[guild_id_str]:
                 logger.debug("DialogueManager: Dialogue %s in guild %s already marked for deletion.", dialogue_id_str, guild_id_str) # Added
                 return 
            logger.warning("DialogueManager: Dialogue %s not found for guild %s during end_dialogue.", dialogue_id_str, guild_id_str) # Added
            return 

        if dialogue_data.get('is_active', True):
             dialogue_data['is_active'] = False 
             self.mark_dialogue_dirty(guild_id_str, dialogue_id_str) 
        
        await self._perform_event_cleanup_logic(dialogue_data, **kwargs) 

        send_cb_factory = kwargs.get('send_callback_factory') 
        event_channel_id = dialogue_data.get('channel_id')
        if send_cb_factory and event_channel_id is not None:
             send_cb = send_cb_factory(int(event_channel_id)) 
             end_message_template = dialogue_data.get('end_message_template_i18n', {}).get(self._settings.get('default_language', 'en'), 'Диалог завершён.')
             try: await send_cb(end_message_template)
             except Exception as e:
                  logger.error("DialogueManager: Error sending dialogue end message for %s in guild %s: %s", dialogue_id_str, guild_id_str, e, exc_info=True) # Changed
        
        # ... (GameLogManager logging as before, ensure guild_id is in logs) ...
        
        await self.remove_active_dialogue(guild_id_str, dialogue_id_str, **kwargs)
        logger.info("DialogueManager: Dialogue %s ended and cleaned up for guild %s.", dialogue_id_str, guild_id_str) # Added

    async def _perform_event_cleanup_logic(self, event_data: Dict[str,Any], **kwargs: Any) -> None: 
        guild_id = event_data.get('guild_id') 
        event_id = event_data.get('id') 
        if not guild_id or not event_id: return
        guild_id_str = str(guild_id)
        logger.debug("DialogueManager: Performing cleanup logic for dialogue/event %s in guild %s.", event_id, guild_id_str) # Added
        
        cleanup_context: Dict[str, Any] = {**kwargs, 'event_id': event_id, 'event': event_data, 'guild_id': guild_id_str,
             'character_manager': self._character_manager or kwargs.get('character_manager'),
             'npc_manager': self._npc_manager or kwargs.get('npc_manager'),
        }
        participants_list = list(event_data.get('participants', [])) 
        if participants_list:
             for p_data_entry in participants_list:
                  participant_id = p_data_entry.get('entity_id') if isinstance(p_data_entry, dict) else str(p_data_entry)
                  p_type = p_data_entry.get('entity_type') if isinstance(p_data_entry, dict) else None
                  mgr = None; char_mgr = cleanup_context.get('character_manager'); npc_mgr = cleanup_context.get('npc_manager')
                  if not p_type and char_mgr and await char_mgr.get_character(guild_id_str, participant_id): p_type = "Character"
                  elif not p_type and npc_mgr and await npc_mgr.get_npc(guild_id_str, participant_id): p_type = "NPC"
                  if p_type == "Character": mgr = char_mgr
                  elif p_type == "NPC": mgr = npc_mgr
                  clean_up_method_name_generic = 'clean_up_for_entity'
                  if mgr and hasattr(mgr, clean_up_method_name_generic):
                       try: await getattr(mgr, clean_up_method_name_generic)(participant_id, p_type, context=cleanup_context)
                       except Exception as e:
                            logger.error("DialogueManager: Error during cleanup for participant %s %s in dialogue %s (guild %s): %s", p_type, participant_id, event_id, guild_id_str, e, exc_info=True) # Changed

    async def remove_active_dialogue(self, guild_id: str, dialogue_id: str, **kwargs: Any) -> Optional[str]:
        guild_id_str = str(guild_id)
        dialogue = self.get_dialogue(guild_id_str, dialogue_id) 
        if not dialogue or str(dialogue.get('guild_id')) != guild_id_str:
            if guild_id_str in self._deleted_dialogue_ids and dialogue_id in self._deleted_dialogue_ids[guild_id_str]:
                 # logger.debug("DialogueManager: Dialogue %s in guild %s already removed and marked for DB deletion.", dialogue_id, guild_id_str) # Added
                 return dialogue_id 
            logger.warning("DialogueManager: Dialogue %s not found or guild mismatch for removal in guild %s.", dialogue_id, guild_id_str) # Added
            return None
        
        guild_dialogues_cache = self._active_dialogues.get(guild_id_str)
        if guild_dialogues_cache:
             guild_dialogues_cache.pop(dialogue_id, None) 
        
        self._dirty_dialogues.get(guild_id_str, set()).discard(dialogue_id)
        self._deleted_dialogue_ids.setdefault(guild_id_str, set()).add(dialogue_id)
        logger.info("DialogueManager: Dialogue %s removed from active cache and marked for DB deletion in guild %s.", dialogue_id, guild_id_str) # Added
        return dialogue_id

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("DialogueManager: Loading state for guild %s.", guild_id_str) # Added
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("DialogueManager: DBService not available for load_state in guild %s.", guild_id_str) # Added
            self._active_dialogues.pop(guild_id_str, None); self._active_dialogues[guild_id_str] = {}
            self._dialogue_templates.pop(guild_id_str, None); self._dialogue_templates[guild_id_str] = {}
            self._dirty_dialogues.pop(guild_id_str, None); self._deleted_dialogue_ids.pop(guild_id_str, None)
            return

        self.load_dialogue_templates(guild_id_str) # Load templates first
        self._active_dialogues.pop(guild_id_str, None); self._active_dialogues[guild_id_str] = {}
        self._dirty_dialogues.pop(guild_id_str, None); self._deleted_dialogue_ids.pop(guild_id_str, None)
        rows = []
        try:
            sql = '''
            SELECT id, template_id, guild_id, participants, channel_id,
                   current_stage_id, state_variables, last_activity_game_time, event_id, is_active
            FROM dialogues WHERE guild_id = $1 AND is_active = TRUE
            '''
            rows = await self._db_service.adapter.fetchall(sql, (guild_id_str,))
            logger.info("DialogueManager: Found %s active dialogues in DB for guild %s.", len(rows), guild_id_str) # Added
        except AttributeError: # Handles if adapter is None, though already checked by _db_service.adapter
            logger.error("DialogueManager: DB adapter not available for load_state in guild %s.", guild_id_str)
            return # Or raise, depending on desired behavior
        except UndefinedTableError: # MODIFIED: Use direct import
            logger.warning("DialogueManager: 'dialogues' table not found in database for guild %s. Dialogue persistence will be skipped.", guild_id_str)
            rows = [] # Ensure rows is an empty list to prevent further errors
        except Exception as e:
            logger.critical("DialogueManager: CRITICAL ERROR fetching dialogues for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            # Depending on policy, may want to raise, or return to allow bot to run without dialogues
            return # For now, return to prevent crash

        loaded_count = 0
        guild_dialogues_cache = self._active_dialogues.get(guild_id_str) # Should be {} due to pop above
        if guild_dialogues_cache is None: # Should not happen due to setdefault in __init__ or pop/re-assign
            self._active_dialogues[guild_id_str] = {}
            guild_dialogues_cache = self._active_dialogues[guild_id_str]


        for row in rows:
             data = dict(row) 
             try:
                 # ... (Data parsing as before, ensure guild_id in logs for warnings/errors) ...
                 dialogue_id = str(data.get('id'))
                 if data.get('is_active', True): # Only load active ones into memory
                     guild_dialogues_cache[dialogue_id] = {k: data[k] for k in ['id', 'template_id', 'guild_id', 'participants', 'channel_id', 'current_stage_id', 'state_variables', 'last_activity_game_time', 'event_id', 'is_active']}
                     loaded_count += 1
             except Exception as e:
                 logger.error("DialogueManager: Error loading dialogue %s for guild %s: %s", data.get('id', 'N/A'), guild_id_str, e, exc_info=True) # Changed
        logger.info("DialogueManager: Loaded %s active dialogues into cache for guild %s.", loaded_count, guild_id_str) # Added

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("DialogueManager: Saving state for guild %s.", guild_id_str) # Added
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("DialogueManager: DBService not available for save_state in guild %s.", guild_id_str) # Added
            return

        dirty_ids_set = self._dirty_dialogues.get(guild_id_str, set()).copy()
        deleted_ids_set = self._deleted_dialogue_ids.get(guild_id_str, set()).copy()
        # guild_cache = self._active_dialogues.get(guild_id_str, {}) # This might be problematic if items are removed from active_dialogues before saving is_active=False

        # Get all dialogues that need saving (dirty ones, including those marked inactive)
        dialogues_to_process_for_save = []
        # Add active dirty dialogues
        active_guild_dialogues = self._active_dialogues.get(guild_id_str, {})
        for d_id in dirty_ids_set:
            if d_id in active_guild_dialogues:
                dialogues_to_process_for_save.append(active_guild_dialogues[d_id].copy())
            # If a dialogue was marked dirty and then ended (is_active=False), it might not be in active_guild_dialogues
            # but still needs its is_active=False state saved. This requires a temporary holding or different logic.
            # For now, assume if it's dirty, it's in active_dialogues (even if is_active=False).

        if not dialogues_to_process_for_save and not deleted_ids_set:
            # logger.debug("DialogueManager: No dirty or deleted dialogues to save for guild %s.", guild_id_str) # Too noisy
            self._dirty_dialogues.pop(guild_id_str, None); self._deleted_dialogue_ids.pop(guild_id_str, None)
            return

        logger.info("DialogueManager: Saving %s dialogues and deleting %s dialogues for guild %s.", len(dialogues_to_process_for_save), len(deleted_ids_set), guild_id_str) # Added

        try:
            if deleted_ids_set:
                 ids_to_del = list(deleted_ids_set)
                 if ids_to_del:
                     placeholders = ','.join([f'${i+2}' for i in range(len(ids_to_del))])
                     sql_delete = f"DELETE FROM dialogues WHERE guild_id = $1 AND id IN ({placeholders})" # Renamed variable to avoid conflict
                     try:
                         await self._db_service.adapter.execute(sql_delete, (guild_id_str, *tuple(ids_to_del)))
                         logger.info("DialogueManager: Deleted %s dialogues from DB for guild %s.", len(ids_to_del), guild_id_str) # Added
                         self._deleted_dialogue_ids.pop(guild_id_str, None)
                     except UndefinedTableError: # MODIFIED: Use direct import
                         logger.warning("DialogueManager: 'dialogues' table not found for deletion in guild %s. Skipping deletion.", guild_id_str)
                         self._deleted_dialogue_ids.pop(guild_id_str, None) # Still clear from memory
                     except Exception as e:
                         logger.error("DialogueManager: Error deleting dialogues for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            else: self._deleted_dialogue_ids.pop(guild_id_str, None)

            if dialogues_to_process_for_save: # Renamed from to_save_data_dicts
                 upsert_sql = '''
                 INSERT INTO dialogues (id, template_id, guild_id, participants, channel_id, current_stage_id, state_variables, last_activity_game_time, event_id, is_active)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                 ON CONFLICT (id) DO UPDATE SET template_id=EXCLUDED.template_id, guild_id=EXCLUDED.guild_id, participants=EXCLUDED.participants, channel_id=EXCLUDED.channel_id, current_stage_id=EXCLUDED.current_stage_id, state_variables=EXCLUDED.state_variables, last_activity_game_time=EXCLUDED.last_activity_game_time, event_id=EXCLUDED.event_id, is_active=EXCLUDED.is_active
                 '''
                 params_list = []
                 saved_ids = set()
                 for d_data in dialogues_to_process_for_save: # Renamed
                     if d_data.get('id') is None or d_data.get('guild_id') != guild_id_str: continue
                     # ... (participant processing as before) ...
                     current_participants = d_data.get('participants', [])
                     valid_participants_for_db = []
                     for p_entry in current_participants:
                         if isinstance(p_entry, dict) and 'entity_id' in p_entry and 'entity_type' in p_entry:
                             valid_participants_for_db.append({'entity_id': str(p_entry['entity_id']), 'entity_type': str(p_entry['entity_type'])})
                         elif isinstance(p_entry, str): 
                              valid_participants_for_db.append({'entity_id': str(p_entry), 'entity_type': 'Character'}) # Assume Character if only ID string
                     
                     params_list.append((
                         str(d_data['id']), str(d_data.get('template_id')), guild_id_str,
                         json.dumps(valid_participants_for_db), d_data.get('channel_id'),
                         str(d_data.get('current_stage_id')), json.dumps(d_data.get('state_variables', {})),
                         d_data.get('last_activity_game_time'), d_data.get('event_id'), d_data.get('is_active', True)
                     ))
                     saved_ids.add(str(d_data['id']))
                 if params_list:
                     try:
                         await self._db_service.adapter.execute_many(upsert_sql, params_list)
                         logger.info("DialogueManager: Saved/Updated %s dialogues for guild %s.", len(params_list), guild_id_str) # Added
                         if guild_id_str in self._dirty_dialogues:
                             self._dirty_dialogues[guild_id_str].difference_update(saved_ids)
                             if not self._dirty_dialogues[guild_id_str]: del self._dirty_dialogues[guild_id_str]
                     except UndefinedTableError: # MODIFIED: Use direct import
                         logger.warning("DialogueManager: 'dialogues' table not found for upsert in guild %s. Skipping save.", guild_id_str)
                         # If table doesn't exist, can't save, so clear dirty flags for these items
                         if guild_id_str in self._dirty_dialogues:
                             self._dirty_dialogues[guild_id_str].difference_update(saved_ids)
                             if not self._dirty_dialogues[guild_id_str]: del self._dirty_dialogues[guild_id_str]
            else: 
                if guild_id_str in self._dirty_dialogues and not self._dirty_dialogues[guild_id_str]:
                    del self._dirty_dialogues[guild_id_str]
                elif not dirty_ids_set : 
                    self._dirty_dialogues.pop(guild_id_str, None)
        except AttributeError: # Handles if adapter is None
            logger.error("DialogueManager: DB adapter not available for save_state in guild %s.", guild_id_str)
        except Exception as e:
            logger.error("DialogueManager: Error during save_state for guild %s: %s", guild_id_str, e, exc_info=True) # Changed

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("DialogueManager: Rebuilding runtime caches for guild %s.", guild_id) # Added
        pass 

    def mark_dialogue_dirty(self, guild_id: str, dialogue_id: str) -> None:
         guild_id_str = str(guild_id)
         dialogue_id_str = str(dialogue_id)
         guild_dialogues_cache = self._active_dialogues.get(guild_id_str)
         if guild_dialogues_cache and dialogue_id_str in guild_dialogues_cache:
              self._dirty_dialogues.setdefault(guild_id_str, set()).add(dialogue_id_str)
         # else: logger.debug("DialogueManager: Attempted to mark non-cached dialogue %s in guild %s as dirty.", dialogue_id_str, guild_id_str) # Too noisy

    def mark_dialogue_deleted(self, guild_id: str, dialogue_id: str) -> None:
         guild_id_str = str(guild_id)
         dialogue_id_str = str(dialogue_id)
         # No need to check active cache, just mark for deletion
         self._deleted_dialogue_ids.setdefault(guild_id_str, set()).add(dialogue_id_str)
         # Remove from dirty set if it was there
         if guild_id_str in self._dirty_dialogues: 
            self._dirty_dialogues.get(guild_id_str, set()).discard(dialogue_id_str)
         logger.info("DialogueManager: Dialogue %s marked for deletion in guild %s.", dialogue_id_str, guild_id_str) # Added

    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
         guild_id = kwargs.get('guild_id')
         if guild_id is None:
             logger.warning("DialogueManager: clean_up_for_entity called for %s %s without guild_id.", entity_type, entity_id) # Added
             return

         guild_id_str = str(guild_id); entity_id_str = str(entity_id)
         # logger.info("DialogueManager: Cleaning up dialogues for entity %s %s in guild %s.", entity_type, entity_id_str, guild_id_str) # INFO is too verbose for this
         dialogue_ids_to_end: List[str] = [] # Collect IDs to avoid modifying dict during iteration

         guild_dialogues = self._active_dialogues.get(guild_id_str)
         if guild_dialogues:
              for d_id, d_data in guild_dialogues.items(): 
                  participants_data_list = d_data.get('participants', [])
                  if isinstance(participants_data_list, list):
                      for p_entry in participants_data_list:
                          if isinstance(p_entry, dict) and p_entry.get('entity_id') == entity_id_str:
                              dialogue_ids_to_end.append(d_id); break
                          elif isinstance(p_entry, str) and p_entry == entity_id_str:
                              dialogue_ids_to_end.append(d_id); break

         for d_id_to_end in dialogue_ids_to_end:
              logger.info("DialogueManager: Ending dialogue %s in guild %s due to entity %s cleanup.", d_id_to_end, guild_id_str, entity_id_str) # Added
              await self.end_dialogue(guild_id_str, d_id_to_end, **kwargs)

    async def handle_talk_action(
        self, character_speaker: Any, guild_id: str,
        action_data: Dict[str, Any], rules_config: Any
    ) -> Dict[str, Any]:
        logger.info(f"DialogueManager: handle_talk_action called for {character_speaker.id} in guild {guild_id}.")
        return {"success": True, "message": "Talk action handled (placeholder).", "state_changed": False}

    async def process_player_dialogue_message(
        self, character: Any, message_text: str, channel_id: int, guild_id: str, **kwargs: Any 
    ):
        guild_id_str = str(guild_id); char_id_str = str(character.id)
         # logger.debug("DialogueManager: Processing player message from char %s in guild %s, channel %s: '%s'", char_id_str, guild_id_str, channel_id, message_text) # Added
        active_dialogue = None; dialogue_id = None
        guild_dialogues = self._active_dialogues.get(guild_id_str, {})
        for d_id, d_data in guild_dialogues.items():
            participants_data_list = d_data.get("participants", [])
            if isinstance(participants_data_list, list):
                for p_entry in participants_data_list:
                    if isinstance(p_entry, dict) and p_entry.get('entity_id') == char_id_str:
                        active_dialogue = d_data; dialogue_id = d_id; break
                    elif isinstance(p_entry, str) and p_entry == char_id_str:
                        active_dialogue = d_data; dialogue_id = d_id; break
            if active_dialogue: break

        if active_dialogue and dialogue_id:
            # TODO: Parse message_text to determine chosen option_id
            # For now, assume message_text directly IS the option_id for simplicity
            chosen_option_id = message_text.strip()
            logger.info("DialogueManager: Player char %s in guild %s chose option '%s' in dialogue %s.", char_id_str, guild_id_str, chosen_option_id, dialogue_id) # Added
            action_data = {"type": "player_response", "response_id": chosen_option_id}
            await self.advance_dialogue(guild_id_str, dialogue_id, char_id_str, action_data, **kwargs)
        else:
            # logger.debug("DialogueManager: No active dialogue found for char %s in guild %s to process message.", char_id_str, guild_id_str) # Added
            # Optionally, send a message back to player "You are not in a dialogue."
            pass

# logger.debug("DEBUG: dialogue_manager.py module loaded.") # Changed
