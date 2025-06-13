# Test comment
# bot/game/managers/dialogue_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
import time

# Импорт базовых типов
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union, Tuple # Added Tuple

# Модели для аннотаций (используем строковые литералы из-за TYPE_CHECKING)
# TODO: Create Dialogue and DialogueTemplate models if needed
# For now, dialogues are represented as Dict[str, Any]
# from bot.game.models.dialogue import Dialogue # If Dialogue model exists
# from bot.game.models.dialogue_template import DialogueTemplate # If template model exists

# Адаптер БД (прямой импорт нужен для __init__)
from bot.services.db_service import DBService # Changed

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins


if TYPE_CHECKING:
    # Чтобы не создавать циклических импортов, импортируем эти типы только для подсказок
    # Используем строковые литералы ("ClassName")
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
    from bot.services.notification_service import NotificationService # Added


# Type aliases for callbacks (defined outside TYPE_CHECKING if used in __init__ signature)
# UNCOMMENTED: Needed for type hints in method signatures and assignments
SendToChannelCallback = Callable[..., Awaitable[Any]] # Represents a function like ctx.send or channel.send
SendCallbackFactory = Callable[[int], SendToChannelCallback] # Represents the factory that takes channel ID and returns a send callback


print("DEBUG: dialogue_manager.py module loaded.")


class DialogueManager:
    """
    Менеджер для управления диалогами между сущностями.
    Отвечает за запуск, продвижение и завершение диалогов,
    хранит активные диалоги и координирует взаимодействие менеджеров.
    Работает на основе guild_id для многогильдийной поддержки.
    """
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
        notification_service: Optional["NotificationService"] = None, # Added
    ):
        print("Initializing DialogueManager...")
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
        self._notification_service = notification_service # Added

        self._active_dialogues = {} 
        self._dialogue_templates = {} 
        self._dirty_dialogues = {} 
        self._deleted_dialogue_ids = {} 

        print("DialogueManager initialized.")

    def load_dialogue_templates(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
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
                 print(f"DialogueManager: Warning: Dialogue templates data for guild {guild_id_str} is not a dictionary ({type(templates_data)}).")
        except Exception as e:
            print(f"DialogueManager: ❌ Error loading dialogue templates for guild {guild_id_str}: {e}")
            traceback.print_exc()

    def get_dialogue_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        if guild_id_str not in self._dialogue_templates: 
            self.load_dialogue_templates(guild_id_str)
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
        
        if self._db_service is None or self._db_service.adapter is None:
            print(f"DialogueManager: No DB service for guild {guild_id_str}. Cannot start dialogue.")
            return None
        tpl = self.get_dialogue_template(guild_id_str, tpl_id_str)
        if not tpl:
            print(f"DialogueManager: Dialogue template '{tpl_id_str}' not found for guild {guild_id_str}.")
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

            current_game_time = time.time()
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
                         if self._rule_engine: # Filter options for the new stage
                             # Determine which participant is the player character for filtering
                             player_char_id_for_options = participant1_id if participant1_type == "Character" else participant2_id
                             
                             filtered_options = await self._rule_engine.get_filtered_dialogue_options(dialogue_data, player_char_id_for_options, current_stage_def, kwargs)
                             options_text = self._format_player_responses(filtered_options)
                             if options_text: await send_cb(options_text)
                     else: await send_cb("Dialogue begins...")
                 except Exception as e_send:
                      print(f"DialogueManager: Error sending dialogue start message for {new_id}: {e_send}")
            return new_id
        except Exception as e:
            print(f"DialogueManager: Error starting dialogue from template '{tpl_id_str}' for guild {guild_id_str}: {e}")
            print(traceback.format_exc())
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
                if not failure_text_i18n_direct and option_data.get('failure_feedback_key') and self._i18n_utils: # Fallback to key
                    failure_text = self._i18n_utils.get_localized_string(
                        option_data['failure_feedback_key'], 
                        default_lang, # Assuming player's language is default_lang for now
                        **(option_data.get('failure_feedback_params', {}))
                    ) or "This option is currently unavailable."
                formatted_responses.append(f"  [{option_id}] ~~{option_text}~~ ({failure_text})")
        return "\n".join(formatted_responses)

    async def advance_dialogue(
        self, guild_id: str, dialogue_id: str, participant_id: str, 
        action_data: Dict[str, Any], **kwargs: Any,
    ) -> None:
        guild_id_str = str(guild_id)
        dialogue_id_str = str(dialogue_id)
        p_id_str = str(participant_id) 
        
        dialogue_data = self._active_dialogues.get(guild_id_str, {}).get(dialogue_id_str)
        if not dialogue_data:
            print(f"DialogueManager: Dialogue {dialogue_id_str} not found for guild {guild_id_str}.")
            return

        participants_data_list = dialogue_data.get('participants', []) 
        
        # Ensure participant_id is one of the entity_ids in the participants list
        is_valid_participant = False
        for p_entry in participants_data_list:
            if isinstance(p_entry, dict) and p_entry.get('entity_id') == p_id_str:
                is_valid_participant = True
                break
            elif isinstance(p_entry, str) and p_entry == p_id_str: # Legacy support
                is_valid_participant = True
                break
        if not is_valid_participant:
             print(f"DialogueManager: Warning: Participant {p_id_str} is not in dialogue {dialogue_id_str}.")
             return

        if not self._rule_engine or not hasattr(self._rule_engine, 'process_dialogue_action'):
             print(f"DialogueManager: RuleEngine or process_dialogue_action not available. Cannot advance dialogue {dialogue_id_str}.")
             return
        
        if 'guild_id' not in kwargs: 
            kwargs['guild_id'] = guild_id_str

        try:
            outcome = await self._rule_engine.process_dialogue_action(
                dialogue_data=dialogue_data.copy(), 
                character_id=p_id_str,
                p_action_data=action_data,
                context=kwargs 
            )

            new_stage_id = outcome.get('new_stage_id')
            is_dialogue_ending = outcome.get('is_dialogue_ending', False)
            skill_check_result = outcome.get('skill_check_result')
            immediate_actions_to_trigger = outcome.get('immediate_actions_to_trigger', [])
            direct_relationship_changes = outcome.get('direct_relationship_changes', [])
            
            npc_id = None
            npc_entity_type = "NPC" 
            for p_data_entry in participants_data_list:
                p_entity_id = p_data_entry.get('entity_id') if isinstance(p_data_entry, dict) else str(p_data_entry)
                if p_entity_id != p_id_str:
                    npc_id = p_entity_id
                    if isinstance(p_data_entry, dict):
                        npc_entity_type = p_data_entry.get('entity_type', "NPC")
                    break
            
            npc_faction_id = None
            npc_name_for_feedback = npc_id # Fallback
            if npc_id and npc_entity_type == "NPC" and self._npc_manager:
                npc_obj = await self._npc_manager.get_npc(guild_id_str, npc_id)
                if npc_obj:
                    npc_faction_id = getattr(npc_obj, 'faction_id', None)
                    npc_name_for_feedback = getattr(npc_obj, 'name', npc_id)


            if self._game_log_manager:
                current_stage_for_log = dialogue_data.get('current_stage_id')
                if skill_check_result:
                    event_data_check = {
                        "player_id": p_id_str, "npc_id": npc_id, "npc_faction_id": npc_faction_id,
                        "dialogue_id": dialogue_id_str, "dialogue_template_id": dialogue_data.get('template_id'),
                        "stage_id": current_stage_for_log, "response_id": action_data.get('response_id'),
                        "check_type": skill_check_result.get('type'), "dc": skill_check_result.get('dc'),
                        "roll": skill_check_result.get('roll'), "total_roll_value": skill_check_result.get('total'),
                        "success": skill_check_result.get('success'), "crit_status": skill_check_result.get('crit_status'),
                        "relationship_bonus_applied": skill_check_result.get('relationship_bonus_applied')
                    }
                    asyncio.create_task(self._game_log_manager.log_event(
                        guild_id=guild_id_str, event_type="DIALOGUE_CHECK_RESULT", 
                        details=event_data_check, player_id=p_id_str
                    ))
                    
                    # Send feedback for skill check result
                    if self._notification_service and skill_check_result.get("feedback_key") and self._character_manager: # Ensure managers are present
                        player_character = await self._character_manager.get_character(guild_id_str, p_id_str)
                        player_language = self._settings.get("main_bot_language", "en") # Default language
                        if player_character:
                            player_language = getattr(player_character, 'language_preference', player_language)
                        
                        feedback_params = skill_check_result.get("feedback_params", {})
                        # Ensure npc_name is in params if not already (RuleEngine might have added it)
                        if "npc_name" not in feedback_params and npc_name_for_feedback:
                             feedback_params["npc_name"] = npc_name_for_feedback
                        
                        asyncio.create_task(self._notification_service.send_relationship_influence_feedback(
                            guild_id=guild_id_str, 
                            player_id=p_id_str, # This is character_id
                            feedback_key=skill_check_result["feedback_key"],
                            context_params=feedback_params,
                            language=player_language,
                            # Send to the dialogue channel; NotificationService handles DM if channel_id is None
                            target_channel_id=dialogue_data.get('channel_id') 
                        ))

                if direct_relationship_changes:
                    event_data_choice = {
                        "player_id": p_id_str, "npc_id": npc_id, "npc_faction_id": npc_faction_id,
                        "dialogue_id": dialogue_id_str, "stage_id": current_stage_for_log,
                        "response_id": action_data.get('response_id'), "intended_changes": direct_relationship_changes
                    }
                    asyncio.create_task(self._game_log_manager.log_event(
                        guild_id=guild_id_str, event_type="DIALOGUE_CHOICE_EFFECT", 
                        details=event_data_choice, player_id=p_id_str
                    ))
            
            dialogue_data['current_stage_id'] = new_stage_id 
            if self._time_manager:
                 dialogue_data['last_activity_game_time'] = await self._time_manager.get_current_game_time(guild_id=guild_id_str)
            self.mark_dialogue_dirty(guild_id_str, dialogue_id_str)

            if is_dialogue_ending:
                await self.end_dialogue(guild_id_str, dialogue_id_str, **kwargs)
            else:
                send_cb_factory = kwargs.get('send_callback_factory')
                dialogue_channel_id_val = dialogue_data.get('channel_id')
                if send_cb_factory and dialogue_channel_id_val is not None and new_stage_id:
                    try:
                        send_cb = send_cb_factory(int(dialogue_channel_id_val))
                        dialogue_template = self.get_dialogue_template(guild_id_str, dialogue_data['template_id'])
                        new_stage_def = dialogue_template.get('stages', {}).get(new_stage_id) if dialogue_template else None
                        if new_stage_def:
                            stage_text = new_stage_def.get('text_i18n', {}).get(self._settings.get('default_language', 'en'), "...")
                            await send_cb(stage_text) 
                            
                            if self._rule_engine: 
                                filtered_options = await self._rule_engine.get_filtered_dialogue_options(dialogue_data, p_id_str, new_stage_def, kwargs)
                                
                                # Send feedback for unavailable options BEFORE formatting them
                                if self._notification_service and self._character_manager:
                                    player_character = await self._character_manager.get_character(guild_id_str, p_id_str)
                                    player_language = self._settings.get("main_bot_language", "en")
                                    if player_character:
                                        player_language = getattr(player_character, 'language_preference', player_language)

                                    for option_feedback in filtered_options:
                                        if option_feedback.get('is_available') is False and option_feedback.get('failure_feedback_key'):
                                            feedback_params_option = option_feedback.get('failure_feedback_params', {})
                                            # Ensure npc_name is in params if not already (RuleEngine might have added it)
                                            if "npc_name" not in feedback_params_option and npc_name_for_feedback:
                                                feedback_params_option["npc_name"] = npc_name_for_feedback

                                            asyncio.create_task(self._notification_service.send_relationship_influence_feedback(
                                                guild_id=guild_id_str,
                                                player_id=p_id_str, # character_id
                                                feedback_key=option_feedback['failure_feedback_key'],
                                                context_params=feedback_params_option,
                                                language=player_language,
                                                target_channel_id=dialogue_data.get('channel_id')
                                            ))
                                
                                options_text = self._format_player_responses(filtered_options)
                                if options_text: await send_cb(options_text)
                        else:
                            await send_cb("Error: Next dialogue stage not found.")
                    except Exception as e_send:
                        print(f"DialogueManager: Error sending next stage message for dialogue {dialogue_id_str}: {e_send}")
            
            for immediate_action in immediate_actions_to_trigger:
                action_type = immediate_action.get("type")
                if action_type == "start_quest" and self._quest_manager:
                    quest_tpl_id = immediate_action.get("quest_template_id")
                    if quest_tpl_id:
                        await self._quest_manager.start_quest(guild_id_str, p_id_str, quest_tpl_id, **kwargs) 
        except Exception as e:
            print(f"DialogueManager: Error processing dialogue action for {p_id_str} in dialogue {dialogue_id_str}: {e}")
            traceback.print_exc()

    async def end_dialogue(self, guild_id: str, dialogue_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        dialogue_id_str = str(dialogue_id)
        dialogue_data = self._active_dialogues.get(guild_id_str, {}).get(dialogue_id_str)
        if not dialogue_data:
            if guild_id_str in self._deleted_dialogue_ids and dialogue_id_str in self._deleted_dialogue_ids[guild_id_str]:
                 return 
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
             try:
                  await send_cb(end_message_template) 
             except Exception as e:
                  print(f"DialogueManager: Error sending dialogue end message for {dialogue_id_str}: {e}")
        
        if self._game_log_manager:
             log_details_end = {
                 'dialogue_id': dialogue_id_str,
                 'template_id': dialogue_data.get('template_id'),
                 'final_stage_id': dialogue_data.get('current_stage_id'),
                 'participants': dialogue_data.get('participants', []),
                 'final_state_variables': dialogue_data.get('state_variables', {}) 
             }
             primary_player_id = None
             participants_list = dialogue_data.get('participants', [])
             if participants_list:
                 for p_entry in participants_list:
                     if isinstance(p_entry, dict) and p_entry.get('entity_type') == "Character":
                         primary_player_id = p_entry.get('entity_id')
                         break
                 if not primary_player_id and participants_list: 
                     first_p = participants_list[0]
                     primary_player_id = first_p.get('entity_id') if isinstance(first_p, dict) else str(first_p)

             asyncio.create_task(self._game_log_manager.log_event(
                 guild_id=guild_id_str, event_type="dialogue_end", 
                 details=log_details_end, 
                 player_id=primary_player_id 
             ))
        
        await self.remove_active_dialogue(guild_id_str, dialogue_id_str, **kwargs)

    async def _perform_event_cleanup_logic(self, event_data: Dict[str,Any], **kwargs: Any) -> None: 
        guild_id = event_data.get('guild_id') 
        event_id = event_data.get('id') 
        if not guild_id or not event_id: return
        guild_id_str = str(guild_id)
        
        cleanup_context: Dict[str, Any] = {
             **kwargs, 'event_id': event_id, 'event': event_data, 'guild_id': guild_id_str,
             'character_manager': self._character_manager or kwargs.get('character_manager'),
             'npc_manager': self._npc_manager or kwargs.get('npc_manager'),
        }
        participants_list = list(event_data.get('participants', [])) 
        if participants_list:
             for p_data_entry in participants_list:
                  participant_id = p_data_entry.get('entity_id') if isinstance(p_data_entry, dict) else str(p_data_entry)
                  p_type = p_data_entry.get('entity_type') if isinstance(p_data_entry, dict) else None
                  
                  mgr = None 
                  char_mgr = cleanup_context.get('character_manager') 
                  npc_mgr = cleanup_context.get('npc_manager') 

                  if not p_type and char_mgr and await char_mgr.get_character(guild_id_str, participant_id):
                      p_type = "Character"
                  elif not p_type and npc_mgr and await npc_mgr.get_npc(guild_id_str, participant_id):
                      p_type = "NPC"

                  if p_type == "Character": mgr = char_mgr
                  elif p_type == "NPC": mgr = npc_mgr
                  
                  clean_up_method_name_generic = 'clean_up_for_entity'
                  if mgr:
                       try:
                           if hasattr(mgr, clean_up_method_name_generic):
                               await getattr(mgr, clean_up_method_name_generic)(participant_id, p_type, context=cleanup_context)
                       except Exception as e:
                            print(f"DialogueManager: Error during cleanup for participant {p_type} {participant_id}: {e}")
                            print(traceback.format_exc())

    async def remove_active_dialogue(self, guild_id: str, dialogue_id: str, **kwargs: Any) -> Optional[str]:
        guild_id_str = str(guild_id)
        dialogue = self.get_dialogue(guild_id_str, dialogue_id) 
        if not dialogue or str(dialogue.get('guild_id')) != guild_id_str:
            if guild_id_str in self._deleted_dialogue_ids and dialogue_id in self._deleted_dialogue_ids[guild_id_str]:
                 return dialogue_id 
            return None
        
        guild_dialogues_cache = self._active_dialogues.get(guild_id_str)
        if guild_dialogues_cache:
             guild_dialogues_cache.pop(dialogue_id, None) 
        
        self._dirty_dialogues.get(guild_id_str, set()).discard(dialogue_id)
        self._deleted_dialogue_ids.setdefault(guild_id_str, set()).add(dialogue_id)
        return dialogue_id

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None:
            self._active_dialogues.pop(guild_id_str, None); self._active_dialogues[guild_id_str] = {}
            self._dialogue_templates.pop(guild_id_str, None); self._dialogue_templates[guild_id_str] = {}
            self._dirty_dialogues.pop(guild_id_str, None); self._deleted_dialogue_ids.pop(guild_id_str, None)
            return

        self.load_dialogue_templates(guild_id_str)
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
        except Exception as e:
            print(f"DialogueManager: ❌ CRITICAL ERROR fetching dialogues for guild {guild_id_str}: {e}")
            traceback.print_exc(); raise

        loaded_count = 0
        guild_dialogues_cache = self._active_dialogues.get(guild_id_str)
        if guild_dialogues_cache is None: return

        for row in rows:
             data = dict(row) 
             try:
                 dialogue_id_raw = data.get('id'); loaded_guild_id_raw = data.get('guild_id')
                 if dialogue_id_raw is None or str(loaded_guild_id_raw) != guild_id_str: continue
                 dialogue_id = str(dialogue_id_raw)
                 try: 
                     participants_raw = data.get('participants')
                     if isinstance(participants_raw, (str, bytes)):
                         parsed_participants = json.loads(participants_raw)
                     elif isinstance(participants_raw, list):
                         parsed_participants = participants_raw
                     else: 
                         parsed_participants = []
                     valid_participants = []
                     for p_entry in parsed_participants:
                         if isinstance(p_entry, dict) and 'entity_id' in p_entry and 'entity_type' in p_entry:
                             valid_participants.append({'entity_id': str(p_entry['entity_id']), 'entity_type': str(p_entry['entity_type'])})
                         elif isinstance(p_entry, str): 
                              valid_participants.append({'entity_id': str(p_entry), 'entity_type': 'Character'}) 
                     data['participants'] = valid_participants
                 except (json.JSONDecodeError, TypeError) as e_p: 
                     print(f"DialogueManager: Warning: Failed to parse participants for dialogue {dialogue_id}. Error: {e_p}. Data: {data.get('participants')}")
                     data['participants'] = []
                 
                 try:
                     state_variables_raw = data.get('state_variables')
                     data['state_variables'] = json.loads(state_variables_raw) if isinstance(state_variables_raw, (str, bytes)) else {}
                 except: data['state_variables'] = {}
                 data['is_active'] = bool(data.get('is_active', 0)) if data.get('is_active') is not None else True
                 last_activity_raw = data.get('last_activity_game_time')
                 data['last_activity_game_time'] = float(last_activity_raw) if isinstance(last_activity_raw, (int, float)) else None
                 data['template_id'] = str(data.get('template_id')) if data.get('template_id') is not None else None
                 data['current_stage_id'] = str(data.get('current_stage_id')) if data.get('current_stage_id') is not None else 'start'
                 data['event_id'] = str(data.get('event_id')) if data.get('event_id') is not None else None
                 channel_id_raw = data.get('channel_id')
                 data['channel_id'] = int(channel_id_raw) if channel_id_raw is not None else None
                 data['id'] = dialogue_id; data['guild_id'] = guild_id_str
                 if data.get('is_active', True):
                     guild_dialogues_cache[data['id']] = {k: data[k] for k in ['id', 'template_id', 'guild_id', 'participants', 'channel_id', 'current_stage_id', 'state_variables', 'last_activity_game_time', 'event_id', 'is_active']}
                     loaded_count += 1
             except Exception as e:
                 print(f"DialogueManager: Error loading dialogue {data.get('id', 'N/A')} for guild {guild_id_str}: {e}")
                 traceback.print_exc()

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None: return

        dirty_ids_set = self._dirty_dialogues.get(guild_id_str, set()).copy()
        deleted_ids_set = self._deleted_dialogue_ids.get(guild_id_str, set()).copy()
        guild_cache = self._active_dialogues.get(guild_id_str, {})
        to_save_data_dicts: List[Dict[str,Any]] = [d.copy() for d_id, d in guild_cache.items() if d_id in dirty_ids_set and d.get('guild_id') == guild_id_str]

        if not to_save_data_dicts and not deleted_ids_set:
            self._dirty_dialogues.pop(guild_id_str, None); self._deleted_dialogue_ids.pop(guild_id_str, None)
            return
        try:
            if deleted_ids_set:
                 ids_to_del = list(deleted_ids_set)
                 if ids_to_del:
                     placeholders = ','.join([f'${i+2}' for i in range(len(ids_to_del))])
                     sql = f"DELETE FROM dialogues WHERE guild_id = $1 AND id IN ({placeholders})"
                     try:
                         await self._db_service.adapter.execute(sql, (guild_id_str, *tuple(ids_to_del)))
                         self._deleted_dialogue_ids.pop(guild_id_str, None)
                     except Exception as e: print(f"DM Error deleting dialogues: {e}")
            else: self._deleted_dialogue_ids.pop(guild_id_str, None)

            if to_save_data_dicts:
                 upsert_sql = '''
                 INSERT INTO dialogues (id, template_id, guild_id, participants, channel_id, current_stage_id, state_variables, last_activity_game_time, event_id, is_active)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                 ON CONFLICT (id) DO UPDATE SET template_id=EXCLUDED.template_id, guild_id=EXCLUDED.guild_id, participants=EXCLUDED.participants, channel_id=EXCLUDED.channel_id, current_stage_id=EXCLUDED.current_stage_id, state_variables=EXCLUDED.state_variables, last_activity_game_time=EXCLUDED.last_activity_game_time, event_id=EXCLUDED.event_id, is_active=EXCLUDED.is_active
                 '''
                 params_list = []
                 saved_ids = set()
                 for d_data in to_save_data_dicts:
                     if d_data.get('id') is None or d_data.get('guild_id') != guild_id_str: continue
                     current_participants = d_data.get('participants', [])
                     valid_participants_for_db = []
                     for p_entry in current_participants:
                         if isinstance(p_entry, dict) and 'entity_id' in p_entry and 'entity_type' in p_entry:
                             valid_participants_for_db.append({'entity_id': str(p_entry['entity_id']), 'entity_type': str(p_entry['entity_type'])})
                         elif isinstance(p_entry, str): 
                              valid_participants_for_db.append({'entity_id': str(p_entry), 'entity_type': 'Character'})
                     
                     params_list.append((
                         str(d_data['id']), str(d_data.get('template_id')), guild_id_str,
                         json.dumps(valid_participants_for_db), d_data.get('channel_id'),
                         str(d_data.get('current_stage_id')), json.dumps(d_data.get('state_variables', {})),
                         d_data.get('last_activity_game_time'), d_data.get('event_id'), d_data.get('is_active', True)
                     ))
                     saved_ids.add(str(d_data['id']))
                 if params_list:
                     await self._db_service.adapter.execute_many(upsert_sql, params_list)
                     if guild_id_str in self._dirty_dialogues:
                         self._dirty_dialogues[guild_id_str].difference_update(saved_ids)
                         if not self._dirty_dialogues[guild_id_str]: del self._dirty_dialogues[guild_id_str]
            else: 
                if guild_id_str in self._dirty_dialogues and not self._dirty_dialogues[guild_id_str]:
                    del self._dirty_dialogues[guild_id_str]
                elif not dirty_ids_set : 
                    self._dirty_dialogues.pop(guild_id_str, None)
        except Exception as e:
            print(f"DM Error save_state: {e}"); traceback.print_exc()

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        pass 

    def mark_dialogue_dirty(self, guild_id: str, dialogue_id: str) -> None:
         guild_id_str = str(guild_id)
         dialogue_id_str = str(dialogue_id)
         guild_dialogues_cache = self._active_dialogues.get(guild_id_str)
         if guild_dialogues_cache and dialogue_id_str in guild_dialogues_cache:
              self._dirty_dialogues.setdefault(guild_id_str, set()).add(dialogue_id_str)

    def mark_dialogue_deleted(self, guild_id: str, dialogue_id: str) -> None:
         guild_id_str = str(guild_id)
         dialogue_id_str = str(dialogue_id)
         guild_dialogues_cache = self._active_dialogues.get(guild_id_str)
         if guild_dialogues_cache and dialogue_id_str in guild_dialogues_cache:
              guild_dialogues_cache.pop(dialogue_id_str, None) 
         self._deleted_dialogue_ids.setdefault(guild_id_str, set()).add(dialogue_id_str)
         if guild_id_str in self._dirty_dialogues: 
            self._dirty_dialogues.get(guild_id_str, set()).discard(dialogue_id_str)

    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
         guild_id = kwargs.get('guild_id')
         if guild_id is None: return
         guild_id_str = str(guild_id); entity_id_str = str(entity_id)
         dialogue_id_to_end: Optional[str] = None
         guild_dialogues = self._active_dialogues.get(guild_id_str)
         if guild_dialogues:
              for d_id, d_data in guild_dialogues.items(): 
                  participants_data_list = d_data.get('participants', [])
                  if isinstance(participants_data_list, list):
                      for p_entry in participants_data_list:
                          if isinstance(p_entry, dict) and p_entry.get('entity_id') == entity_id_str:
                              dialogue_id_to_end = d_id; break
                          elif isinstance(p_entry, str) and p_entry == entity_id_str: # Legacy
                              dialogue_id_to_end = d_id; break
                  if dialogue_id_to_end: break
         if dialogue_id_to_end:
              await self.end_dialogue(guild_id_str, dialogue_id_to_end, **kwargs)

    async def process_player_dialogue_message(
        self, character: Any, message_text: str, channel_id: int, guild_id: str, **kwargs: Any 
    ):
        guild_id_str = str(guild_id); char_id_str = str(character.id)
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
            pass 
        else:
            pass

print("DEBUG: dialogue_manager.py module loaded.")


