# Test comment
# bot/game/managers/dialogue_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
# Импорт базовых типов
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union, Tuple # Added Tuple

# Модели для аннотаций (используем строковые литералы из-за TYPE_CHECKING)
# TODO: Create Dialogue and DialogueTemplate models if needed
# For now, dialogues are represented as Dict[str, Any]
# from bot.game.models.dialogue import Dialogue # If Dialogue model exists
# from bot.game.models.dialogue_template import DialogueTemplate # If template model exists

# Адаптер БД (прямой импорт нужен для __init__)
from bot.database.sqlite_adapter import SqliteAdapter

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
    from bot.services.openai_service import OpenAIService # Added import
    from bot.game.managers.relationship_manager import RelationshipManager # Added import
    # Add other managers/services that might be in context kwargs (e.g., from CommandRouter/WSP)
    from bot.game.managers.location_manager import LocationManager
    # from bot.game.managers.event_manager import EventManager
    from bot.game.managers.game_log_manager import GameLogManager # Assuming path


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
    # Required args для PersistenceManager
    # Диалоги привязаны к гильдии. PersistenceManager должен загружать/сохранять per-guild.
    required_args_for_load: List[str] = ["guild_id"] # Загрузка per-guild
    required_args_for_save: List[str] = ["guild_id"] # Сохранение per-guild
    # ИСПРАВЛЕНИЕ: Добавляем guild_id для rebuild_runtime_caches
    required_args_for_rebuild: List[str] = ["guild_id"] # Rebuild per-guild


    # --- Class-Level Attribute Annotations ---
    # Кеш активных диалогов {guild_id: {dialogue_id: Dialogue_object_or_Dict}}
    # Assuming dialogue data is stored as Dict for now.
    # ИСПРАВЛЕНИЕ: Кеш активных диалогов должен быть per-guild
    _active_dialogues: Dict[str, Dict[str, Dict[str, Any]]]

    # Статические шаблоны диалогов: {guild_id: {template_id: data_dict}}
    # ИСПРАВЛЕНИЕ: Шаблоны диалогов должны быть per-guild
    _dialogue_templates: Dict[str, Dict[str, Dict[str, Any]]]

    # Изменённые диалоги, подлежащие записи: {guild_id: set(dialogue_ids)}
    # ИСПРАВЛЕНИЕ: dirty dialogues также per-guild
    _dirty_dialogues: Dict[str, Set[str]] # {guild_id: {dialogue_id}}

    # Удалённые диалоги, подлежащие удалению из БД: {guild_id: set(dialogue_ids)}
    # ИСПРАВЛЕНИЕ: deleted dialogue ids также per-guild
    _deleted_dialogue_ids: Dict[str, Set[str]] # {guild_id: {dialogue_id}}

    # TODO: Возможно, кеш {participant_id: dialogue_id} если часто нужно найти диалог по участнику
    # _participant_to_dialogue_map: Dict[str, Dict[str, str]] # {guild_id: {participant_id: dialogue_id}}


    def __init__(
        self,
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        character_manager: Optional["CharacterManager"] = None, # Use string literal!
        npc_manager: Optional["NpcManager"] = None, # Use string literal!
        rule_engine: Optional["RuleEngine"] = None, # Use string literal!
        event_stage_processor: Optional["EventStageProcessor"] = None, # Use string literal!
        time_manager: Optional["TimeManager"] = None, # Use string literal!
        openai_service: Optional["OpenAIService"] = None, # Added openai_service
        relationship_manager: Optional["RelationshipManager"] = None, # Added relationship_manager
        # Add other injected dependencies here with Optional and string literals
        game_log_manager: Optional["GameLogManager"] = None, # Added game_log_manager

    ):
        print("Initializing DialogueManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        # Инжектированные зависимости
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._rule_engine = rule_engine
        self._event_stage_processor = event_stage_processor
        self._time_manager = time_manager
        self._openai_service = openai_service # Assigned to instance variable
        self._relationship_manager = relationship_manager # Assigned to instance variable
        self._game_log_manager = game_log_manager # Assigned to instance variable


        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые outer словари
        # Кеш активных диалогов: {guild_id: {dialogue_id: Dialogue_object_or_Dict}}
        self._active_dialogues = {} # Инициализируем как пустой dict

        # Статические шаблоны диалогов: {guild_id: {template_id: data_dict}}
        self._dialogue_templates = {} # Инициализируем как пустой dict

        # Для оптимизации персистенции
        self._dirty_dialogues = {} # Инициализируем как пустой dict
        self._deleted_dialogue_ids = {} # Инициализируем как пустой dict

        # TODO: Инициализировать кеш {participant_id: dialogue_id} если нужен
        # self._participant_to_dialogue_map = {}

        print("DialogueManager initialized.")

    # load_dialogue_templates method (not called by PM directly)
    # This method will be called from load_state
    def load_dialogue_templates(self, guild_id: str) -> None:
        """(Пример) Загружает статические шаблоны диалогов для определенной гильдии из настроек или файлов."""
        guild_id_str = str(guild_id)
        print(f"DialogueManager: Loading dialogue templates for guild {guild_id_str}...")

        # Очищаем кеш шаблонов для этой гильдии перед загрузкой
        self._dialogue_templates.pop(guild_id_str, None)
        # Create empty cache for this guild. Use setdefault for atomic check-and-set.
        guild_templates_cache = self._dialogue_templates.setdefault(guild_id_str, {})

        try:
            # Пример загрузки из settings (предполагаем структуру settings['guilds'][guild_id]['dialogue_templates']
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            templates_data = guild_settings.get('dialogue_templates')

            # TODO: Add fallback to global templates file if needed

            if isinstance(templates_data, dict):
                 for tpl_id, data in templates_data.items():
                      # Basic validation for template structure
                      if tpl_id and isinstance(data, dict):
                           # Create a copy to avoid modifying original settings data if templates are modified later
                           template_data = data.copy()
                           template_data.setdefault('id', str(tpl_id)) # Ensure id is in data
                           template_data.setdefault('name', f"Unnamed Dialogue Template ({tpl_id})") # Ensure name
                           template_data.setdefault('stages', {}) # Ensure stages exists (as empty dict default)
                           # Add more validation for stages structure if needed

                           guild_templates_cache[str(tpl_id)] = template_data # Store with string ID
                 print(f"DialogueManager: Loaded {len(guild_templates_cache)} dialogue templates for guild {guild_id_str}.")
            elif templates_data is not None:
                 print(f"DialogueManager: Warning: Dialogue templates data for guild {guild_id_str} is not a dictionary ({type(templates_data)}). Skipping template load.")
            else:
                 print(f"DialogueManager: No dialogue templates found in settings for guild {guild_id_str} or globally.")


        except Exception as e:
            print(f"DialogueManager: ❌ Error loading dialogue templates for guild {guild_id_str}: {e}")
            traceback.print_exc()
            # Decide how to handle error - critical or just log? Log and continue for now.


    # get_dialogue_template now needs guild_id
    def get_dialogue_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        """Возвращает данные шаблона диалога по его ID для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Get templates from the per-guild cache
        guild_templates = self._dialogue_templates.get(guild_id_str, {})
        return guild_templates.get(str(template_id)) # Ensure template_id is string


    # get_dialogue now needs guild_id
    def get_dialogue(self, guild_id: str, dialogue_id: str) -> Optional[Dict[str, Any]]: # Returning Dict[str, Any] as we don't have a model yet
        """Получить данные активного диалога по ID для определенной гильдии (из кеша)."""
        guild_id_str = str(guild_id)
        # Get dialogues from the per-guild cache
        guild_dialogues = self._active_dialogues.get(guild_id_str) # Get per-guild cache
        if guild_dialogues:
             # Return a copy of the dialogue data to prevent external modification
             dialogue_data = guild_dialogues.get(str(dialogue_id)) # Ensure dialogue_id is string
             if dialogue_data is not None:
                  return dialogue_data.copy() # Return a copy
        return None # Guild or dialogue not found


    # get_active_dialogues now needs guild_id
    def get_active_dialogues(self, guild_id: str) -> List[Dict[str, Any]]: # Returning List[Dict[str, Any]]
        """Получить список всех активных диалогов для определенной гильдии (из кеша)."""
        guild_id_str = str(guild_id)
        guild_dialogues = self._active_dialogues.get(guild_id_str) # Get per-guild cache
        if guild_dialogues:
             # Return copies of dialogue data
             return [d.copy() for d in guild_dialogues.values()]
        return [] # Return empty list


    # is_in_dialogue needs guild_id
    def is_in_dialogue(self, guild_id: str, entity_id: str) -> bool:
        """Проверяет, участвует ли сущность в активном диалоге для определенной гильдии."""
        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)
        # Iterate only through active dialogues for this guild
        guild_dialogues = self._active_dialogues.get(guild_id_str)
        if guild_dialogues:
             for d in guild_dialogues.values(): # d is a Dict[str, Any]
                 # Check if the entity ID is in the participants list for this dialogue
                 participants = d.get('participants', []) # Participants expected to be a List[str]
                 if isinstance(participants, list) and entity_id_str in participants:
                      # Found the participant in this dialogue
                      return True
        return False # Participant not found in any active dialogue for this guild


    # start_dialogue needs guild_id and stores it
    async def start_dialogue(
        self,
        guild_id: str, # Added guild_id
        template_id: str,
        participant1_id: str,
        participant2_id: str,
        channel_id: Optional[int] = None,
        event_id: Optional[str] = None, # Link to event if applicable
        initial_state_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any, # Context with managers etc.
    ) -> Optional[str]: # Returns dialogue ID (str)
        """Начинает новый диалог по шаблону между двумя участниками для определенной гильдии."""
        guild_id_str = str(guild_id)
        tpl_id_str = str(template_id)
        p1_id_str = str(participant1_id)
        p2_id_str = str(participant2_id)
        print(f"DialogueManager: Starting dialogue {tpl_id_str} between {p1_id_str} and {p2_id_str} for guild {guild_id_str}.")

        if self._db_adapter is None:
            print(f"DialogueManager: No DB adapter available for guild {guild_id_str}. Cannot start dialogue that requires persistence.")
            # Should starting dialogue require persistence? Maybe temporary dialogues don't.
            # For now, assume active dialogues should be persistent.
            return None

        # Get template for this guild
        tpl = self.get_dialogue_template(guild_id_str, tpl_id_str) # Use get_dialogue_template with guild_id
        if not tpl:
            print(f"DialogueManager: Dialogue template '{tpl_id_str}' not found for guild {guild_id_str}.")
            # TODO: Send feedback if a command triggered this? Need send_callback_factory from kwargs.
            return None

        # TODO: Validation: participants exist and belong to this guild, check if participants are already in dialogue (using is_in_dialogue with guild_id)
        # Use injected managers (character_manager, npc_manager) with guild_id checks.
        # char_mgr = kwargs.get('character_manager', self._character_manager) # type: Optional["CharacterManager"]
        # npc_mgr = kwargs.get('npc_manager', self._npc_manager) # type: Optional["NpcManager"]
        # if char_mgr and hasattr(char_mgr, 'get_character'): char1 = char_mgr.get_character(guild_id_str, p1_id_str) # Assumes sync get_character by ID
        # if npc_mgr and hasattr(npc_mgr, 'get_npc'): npc1 = npc_mgr.get_npc(guild_id_str, p1_id_str) # Assumes sync get_npc by ID
        # ... etc.
        # if self.is_in_dialogue(guild_id_str, p1_id_str) or self.is_in_dialogue(guild_id_str, p2_id_str):
        #      print(f"DialogueManager: One or both participants already in a dialogue in guild {guild_id_str}.")
        #      # TODO: Send feedback if a command triggered this? Need send_callback_factory from kwargs.
        #      return None # Cannot start dialogue if participants are busy


        try:
            new_id = str(uuid.uuid4())

            # Prepare initial dialogue state data
            initial_state = initial_state_data or {} # Use provided initial state if any
            # Merge with template initial state if template has one
            if tpl.get('initial_state_variables'):
                if isinstance(tpl['initial_state_variables'], dict):
                    # Decide policy: kwargs overrides template? Template provides defaults?
                    # Let's assume kwargs initial_state_data overrides template defaults
                    template_initial_state = tpl['initial_state_variables'].copy()
                    template_initial_state.update(initial_state)
                    initial_state = template_initial_state # Final state starts with template defaults + kwargs overrides
                else:
                     print(f"DialogueManager: Warning: Template '{tpl_id_str}' initial_state_variables is not a dict ({type(tpl['initial_state_variables'])}). Ignoring template initial state.")


            dialogue_data: Dict[str, Any] = {
                'id': new_id,
                'template_id': tpl_id_str,
                'guild_id': guild_id_str, # <--- Add guild_id
                'participants': [p1_id_str, p2_id_str], # Store participant IDs as strings
                'channel_id': int(channel_id) if channel_id is not None else None, # Store channel ID as int or None
                'current_stage_id': str(tpl.get('start_stage_id', 'start')), # Use template start stage, fallback to 'start'
                'state_variables': initial_state, # Dynamic state variables for dialogue instance
                'last_activity_game_time': None, # Will be set on first advance or tick
                'event_id': str(event_id) if event_id is not None else None, # Link to event instance if applicable
                'is_active': True, # New dialogues start as active
                # TODO: Add other fields from DB schema if any (e.g., created_at, ended_at)
            }

            # Basic validation for participants list
            if not isinstance(dialogue_data.get('participants'), list) or len(dialogue_data['participants']) != 2:
                 print(f"DialogueManager: Warning: Invalid participant list for dialogue {new_id} in guild {guild_id_str}. Setting to empty list.")
                 dialogue_data['participants'] = []
            else: # Ensure participant IDs are strings
                 dialogue_data['participants'] = [str(p) for p in dialogue_data['participants'] if p is not None]


            # --- Add to active cache and mark dirty ---
            # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш активных диалогов
            self._active_dialogues.setdefault(guild_id_str, {})[new_id] = dialogue_data # Store the data dict

            # TODO: Update _participant_to_dialogue_map if using it
            # if hasattr(self, '_participant_to_dialogue_map'):
            #      guild_participant_map = self._participant_to_dialogue_map.setdefault(guild_id_str, {})
            #      for p_id in dialogue_data['participants']:
            #           guild_participant_map[p_id] = new_id


            # ИСПРАВЛЕНИЕ: Помечаем новый диалог dirty (per-guild)
            self.mark_dialogue_dirty(guild_id_str, new_id)


            print(f"DialogueManager: Dialogue {new_id} ({tpl_id_str}) started for guild {guild_id_str}.")

            # Optional: Notify participants / channel about dialogue start?
            send_cb_factory = kwargs.get('send_callback_factory') # Get factory from context
            dialogue_channel_id_val = dialogue_data.get('channel_id') # This can be Optional[int]

            # FIX: Corrected the try/except structure and indentation
            if send_cb_factory and dialogue_channel_id_val is not None:
                 try:
                     # Ensure channel_id is int before passing to factory
                     dialogue_channel_id_int = int(dialogue_channel_id_val) # Use consistent variable name
                     send_cb = send_cb_factory(dialogue_channel_id_int)

                     # Construct the initial message text
                     start_message = f"Начинается диалог ({tpl_id_str})!" # Basic message for now

                     rule_engine = kwargs.get('rule_engine', self._rule_engine)
                     if rule_engine and hasattr(rule_engine, 'get_dialogue_stage_text'):
                         try:
                             start_stage_id = dialogue_data.get('current_stage_id')
                             if start_stage_id:
                                 # Assuming get_dialogue_stage_text is async
                                 stage_text = await rule_engine.get_dialogue_stage_text(
                                     template_id=tpl_id_str,
                                     stage_id=start_stage_id,
                                     dialogue_state=dialogue_data, # Pass the dialogue data
                                     context=kwargs # Pass context
                                 )
                                 if stage_text:
                                     start_message += f"\n{stage_text}"
                         except Exception as e_text:
                             print(f"DialogueManager: Error getting start dialogue text for {new_id}: {e_text}")
                             traceback.print_exc() # traceback should be imported at the top

                     # Send the message
                     await send_cb(start_message)
                     print(f"DialogueManager: Sent start message for dialogue {new_id} to channel {dialogue_channel_id_int}.")

                 except (ValueError, TypeError) as e_int: # Catch error from int(dialogue_channel_id_val)
                      print(f"DialogueManager: Invalid channel_id format '{dialogue_channel_id_val}' for dialogue {new_id}. Cannot send start message: {e_int}")
                 except Exception as e_send: # Catch any other error during message sending or text generation
                      print(f"DialogueManager: Error sending dialogue start message for {new_id} to channel {dialogue_channel_id_val}: {e_send}")
                      traceback.print_exc()
            # END FIX


            return new_id # Return the created dialogue ID

        except Exception as e:
            print(f"DialogueManager: Error starting dialogue from template '{tpl_id_str}' for guild {guild_id_str}: {e}")
            # import traceback # traceback should be imported at the top
            print(traceback.format_exc())
            return None


    # advance_dialogue needs guild_id
    async def advance_dialogue(
        self,
        guild_id: str, # Added guild_id
        dialogue_id: str,
        participant_id: str, # ID of participant who took the action
        action_data: Dict[str, Any], # Data describing the participant's action (e.g., {type: 'response', response_id: 'option_1'})
        **kwargs: Any, # Context with managers etc. (includes send_callback_factory, channel_id)
    ) -> None:
        """
        Продвигает диалог вперед на основе действия участника для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        dialogue_id_str = str(dialogue_id)
        p_id_str = str(participant_id)
        action_type = action_data.get('type', 'unknown')
        print(f"DialogueManager: Advancing dialogue {dialogue_id_str} by {p_id_str} with action '{action_type}' for guild {guild_id_str}.")

        # ИСПРАВЛЕНИЕ: Получаем диалог с учетом guild_id (use copy if RuleEngine modifies in place)
        dialogue_data = self._active_dialogues.get(guild_id_str, {}).get(dialogue_id_str) # Get dialogue data dict

        if not dialogue_data:
            print(f"DialogueManager: Dialogue {dialogue_id_str} not found or not in guild {guild_id_str}.")
            # Optional: Send feedback? Needs send_callback_factory from kwargs/context
            # send_cb_factory = kwargs.get('send_callback_factory')
            # if send_cb_factory and kwargs.get('channel_id') is not None:
            #     try: await send_cb_factory(kwargs['channel_id'])("Error: Dialogue not found.")
            #     except Exception: pass
            return # Dialogue not found or mismatched guild


        # Check if participant is actually in this dialogue
        participants = dialogue_data.get('participants', [])
        if not isinstance(participants, list) or p_id_str not in participants:
             print(f"DialogueManager: Warning: Participant {p_id_str} is not in dialogue {dialogue_id_str} for guild {guild_id_str}. Ignoring action.")
             # Optional: Send feedback? Needs send_callback_factory from kwargs/context
             return # Ignore action from non-participant


        # Get RuleEngine from kwargs or self
        rule_engine = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]

        if not rule_engine or not hasattr(rule_engine, 'process_dialogue_action'):
             print(f"DialogueManager: Warning: RuleEngine or process_dialogue_action method not available for guild {guild_id_str}. Cannot process dialogue action for {dialogue_id_str}.")
             # Optional: Send feedback? Needs send_callback_factory from kwargs/context
             return


        try:
            # Use RuleEngine to process the participant's action and get the next stage ID or dialogue outcome.
            # process_dialogue_action needs dialogue_data (Dict), participant_id, action_data, context.
            # RuleEngine is expected to modify dialogue_data in place or return updated data/commands.
            # RuleEngine is expected to use guild_id from dialogue_data or context for per-guild logic.

            # Pass all necessary context to RuleEngine
            dialogue_context = {**kwargs, 'guild_id': guild_id_str, 'dialogue_id': dialogue_id_str, 'participant_id': p_id_str, 'action_data': action_data} # Add specific dialogue info

            # FIXME: RuleEngine.process_dialogue_action method does not exist. Implement or remove.
            # Assuming process_dialogue_action is async
            # outcome = await rule_engine.process_dialogue_action(
            #     dialogue_data=dialogue_data, # Pass the dialogue data dict (RuleEngine might modify this directly)
            #     participant_id=p_id_str,
            #     action_data=action_data,
            #     context=dialogue_context # Pass full context
            # )
            print(f"DialogueManager: FIXME: Call to rule_engine.process_dialogue_action skipped for dialogue {dialogue_id_str} as method is missing.")
            # If RuleEngine modifies dialogue_data in place, it's already updated in our cache dictionary.

            # --- 3. Update dialogue state based on RuleEngine outcome ---
            # Update last_activity_game_time
            if self._time_manager and hasattr(self._time_manager, 'get_current_game_time'):
                dialogue_data['last_activity_game_time'] = self._time_manager.get_current_game_time(guild_id=guild_id_str) # Get time per-guild
                # Assuming get_current_game_time returns float or None. Ensure field type consistency.

            # The RuleEngine should set 'is_active' = False or set 'current_stage_id' to an end stage within dialogue_data if dialogue ends.
            # Let's check the state *after* the (skipped) RuleEngine call.
            is_dialogue_active_after_action = dialogue_data.get('is_active', True) # Check state after processing

            template_id_val = dialogue_data.get('template_id')
            # Get template for this guild
            tpl = self.get_dialogue_template(guild_id_str, template_id_val) if template_id_val else None # Use get_dialogue_template with guild_id

            if tpl is None:
                 print(f"DialogueManager: Warning: Invalid or missing template_id '{template_id_val}' in dialogue {dialogue_id_str} for guild {guild_id_str}. Cannot determine end stages.")
                 end_stages = ['end'] # Default end stages if template is missing/invalid
                 # Potentially end the dialogue if template_id is crucial and missing/invalid.
                 # dialogue_data['is_active'] = False # Consider forcing inactive state
            else:
                 end_stages = tpl.get('end_stages', ['end']) # Default end stages if template is missing/invalid


            if not is_dialogue_active_after_action or dialogue_data.get('current_stage_id') in end_stages:
                 # Dialogue should end
                 print(f"DialogueManager: Dialogue {dialogue_id_str} meets end conditions for guild {guild_id_str} after action by {p_id_str}.")
                 # Call end_dialogue directly, passing context
                 await self.end_dialogue(guild_id_str, dialogue_id_str, **kwargs) # Pass guild_id and context
                 # Note: end_dialogue marks for deletion and removes from active cache.

            else:
                 # Dialogue continues - mark as dirty to save updated state
                 self.mark_dialogue_dirty(guild_id_str, dialogue_id_str) # Use method mark_dialogue_dirty with guild_id
                 print(f"DialogueManager: Dialogue {dialogue_id_str} advanced by {p_id_str}, state updated, marked dirty for guild {guild_id_str}.")
                 # Optional: Send text for the new stage? RuleEngine might have done this.
                 # If not, get current_stage_id from dialogue_data and send its text via RuleEngine/send_callback
                 # This would involve getting send_callback_factory from kwargs/context and channel_id from dialogue_data.

        except Exception as e:
            print(f"DialogueManager: ❌ Error processing dialogue action for {p_id_str} in dialogue {dialogue_id_str} for guild {guild_id_str}: {e}")
            # import traceback # traceback should be imported at the top
            print(traceback.format_exc())
            # TODO: Decide how to handle error - maybe end dialogue? Log severe error?
            # For now, log and leave the dialogue as is (marked dirty).


    # end_dialogue needs guild_id
    async def end_dialogue(self, guild_id: str, dialogue_id: str, **kwargs: Any) -> None:
        """
        Координирует завершение диалога для определенной гильдии.
        Удаляет диалог из активных, запускает cleanup логику для участников, помечает для удаления из БД.
        """
        guild_id_str = str(guild_id)
        dialogue_id_str = str(dialogue_id)
        print(f"DialogueManager: Ending dialogue {dialogue_id_str} for guild {guild_id_str}...")

        # ИСПРАВЛЕНИЕ: Получаем диалог с учетом guild_id (use copy if managers modify it)
        # Using direct access to modify the cached dict in place is okay here as it's being ended anyway.
        dialogue_data = self._active_dialogues.get(guild_id_str, {}).get(dialogue_id_str)

        if not dialogue_data:
            # Check if it's already marked for deletion for this guild
            if guild_id_str in self._deleted_dialogue_ids and dialogue_id_str in self._deleted_dialogue_ids[guild_id_str]:
                 print(f"DialogueManager: Dialogue {dialogue_id_str} in guild {guild_id_str} was already marked for deletion.")
                 return # Already marked for deletion
            print(f"DialogueManager: Dialogue {dialogue_id_str} not found or not in guild {guild_id_str} for ending.")
            return # Dialogue not found or mismatched guild


        # Ensure is_active is False in data for saving (if it wasn't set by RuleEngine/ending condition)
        if dialogue_data.get('is_active', True): # Check current state (defaults to True if missing)
             dialogue_data['is_active'] = False # Mark as inactive in the data
             self.mark_dialogue_dirty(guild_id_str, dialogue_id_str) # Mark dirty to save this state (is_active=False)


        # --- Выполнение Cleanup Логики для участников ---
        # Cобрать контекст для методов clean_up_*
        # Ensure essential managers are in context, preferring injected over kwargs if both exist.
        cleanup_context: Dict[str, Any] = {
             **kwargs, # Start with all incoming kwargs
             'dialogue_id': dialogue_id_str,
             'dialogue': dialogue_data, # Pass the dialogue data
             'guild_id': guild_id_str, # Ensure guild_id_str is in context

             # Critical managers for cleanup (get from self or kwargs, prefer self if injected)
             'character_manager': self._character_manager if self._character_manager else kwargs.get('character_manager'),
             'npc_manager': self._npc_manager if self._npc_manager else kwargs.get('npc_manager'),
             'game_log_manager': self._game_log_manager if self._game_log_manager else kwargs.get('game_log_manager'),
             # Add others... party_manager? combat_manager?
        }


        # --- Cleanup participants ---
        # Notify participants' managers that they are no longer in dialogue state.
        # This is typically done by calling a cleanup method on the entity managers.
        # Example: CharacterManager.clean_up_from_dialogue(character_id, context)
        participants_list = list(dialogue_data.get('participants', [])) # Iterate over a copy
        if participants_list:
             print(f"DialogueManager: Cleaning up {len(participants_list)} participants for dialogue {dialogue_id_str} in guild {guild_id_str}.")
             for participant_id in participants_list:
                  # Determine participant type (Character or NPC?)
                  p_type = None
                  mgr = None # type: Optional[Any]
                  # Get managers from cleanup context
                  char_mgr = cleanup_context.get('character_manager') # type: Optional["CharacterManager"]
                  npc_mgr = cleanup_context.get('npc_manager') # type: Optional["NpcManager"]

                  # Assumes sync get_character/get_npc methods checking by ID exist and return truthy on found.
                  if char_mgr and hasattr(char_mgr, 'get_character') and char_mgr.get_character(guild_id_str, participant_id):
                       p_type = 'Character' ; mgr = char_mgr
                  elif npc_mgr and hasattr(npc_mgr, 'get_npc') and npc_mgr.get_npc(guild_id_str, participant_id):
                       p_type = 'NPC' ; mgr = npc_mgr
                  # TODO: Add other entity types (e.g., Party, Item, Location?)

                  # Assuming entity managers have a clean_up_for_entity method taking (entity_id, entity_type, context)
                  # Or a specific method like clean_up_from_dialogue(entity_id, context)
                  clean_up_method_name_generic = 'clean_up_for_entity' # Preferred generic method


                  if mgr:
                       try:
                           if hasattr(mgr, clean_up_method_name_generic):
                                # Generic cleanup: clean_up_for_entity(entity_id, entity_type, context)
                                # Assuming clean_up_for_entity is async
                                await getattr(mgr, clean_up_method_name_generic)(participant_id, p_type, context=cleanup_context)
                           else:
                                print(f"DialogueManager: Warning: No suitable generic dialogue cleanup method ('{clean_up_method_name_generic}') found on {type(mgr).__name__} for participant {p_type} {participant_id} in guild {guild_id_str}.")
                                # Maybe look for a specific method like clean_up_from_dialogue if generic not found? Decide preferred API.
                                # For now, just log warning and continue.
                                continue # Skip cleanup for this participant if no suitable method


                           print(f"DialogueManager: Cleaned up participant {p_type} {participant_id} from dialogue {dialogue_id_str} in guild {guild_id_str}.")

                       except Exception as e:
                            print(f"DialogueManager: ❌ Error during cleanup for participant {p_type} {participant_id} in dialogue {dialogue_id_str} for guild {guild_id_str}: {e}")
                            # import traceback # traceback should be imported at the top
                            print(traceback.format_exc())
                            # Do not re-raise error, continue cleanup for other participants.

        print(f"DialogueManager: Finished participant cleanup for dialogue {dialogue_id_str} in guild {guild_id_str}.")


        # TODO: Trigger dialogue end logic (RuleEngine?) - e.g., events, quest updates, relationship changes based on outcome
        rule_engine = cleanup_context.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]
        # FIXME: RuleEngine.trigger_dialogue_end method does not exist. Implement or remove.
        # Assuming trigger_dialogue_end is async
        # if rule_engine and hasattr(rule_engine, 'trigger_dialogue_end'): # Assuming RuleEngine method
        #      try: await rule_engine.trigger_dialogue_end(dialogue_data, context=cleanup_context)
        #      except Exception as e: print(f"DialogueManager: Error triggering dialogue end logic for {dialogue_id_str} in guild {guild_id_str}: {e}"); traceback.print_exc();
        print(f"DialogueManager: FIXME: Call to rule_engine.trigger_dialogue_end skipped for dialogue {dialogue_id_str} as method is missing.")


        print(f"DialogueManager: Dialogue {dialogue_id_str} cleanup processes complete for guild {guild_id_str}.")


        # --- 3. Удаляем диалог из кеша активных и помечаем для удаления из DB ---

        # ИСПРАВЛЕНИЕ: Помечаем диалог для удаления из DB (per-guild)
        # Use the correct per-guild deleted set
        self.mark_dialogue_deleted(guild_id_str, dialogue_id_str) # Use the separate method


        # ИСПРАВЛЕНИЕ: Удаляем диалог из per-guild кеша активных диалогов.
        # Use the correct per-guild active dialogues cache
        guild_dialogues_cache = self._active_dialogues.get(guild_id_str)
        if guild_dialogues_cache:
             # Use pop to remove and get the item, or None if not found (safer than del)
             removed_dialogue = guild_dialogues_cache.pop(dialogue_id_str, None)
             if removed_dialogue:
                 print(f"DialogueManager: Dialogue {dialogue_id_str} removed from active cache for guild {guild_id_str}.")
             else:
                 print(f"DialogueManager: Warning: Attempted to remove dialogue {dialogue_id_str} from active cache for guild {guild_id_str}, but it wasn't found.") # Should not happen if get was successful


        # Убираем из dirty set, если там был (удален -> не dirty anymore for upsert)
        # Use the correct per-guild dirty set
        # Note: mark_dialogue_deleted already does this via discard()
        # self._dirty_dialogues.get(guild_id_str, set()).discard(dialogue_id_str)


        # Log the end of the dialogue
        game_log_manager = cleanup_context.get('game_log_manager', self._game_log_manager)
        if game_log_manager and hasattr(game_log_manager, 'log_event'):
             try:
                  # Pass participants, template_id etc. to the log
                  log_message = f"Dialogue ended (Template: {dialogue_data.get('template_id', 'N/A')}) with participants: {', '.join(dialogue_data.get('participants', []))}."
                  related_entities = [{"id": pid, "type": "Character"} for pid in dialogue_data.get('participants', [])] # Assume participants are Characters for logging example
                  metadata = {
                      'dialogue_id': dialogue_id_str,
                      'template_id': dialogue_data.get('template_id'),
                      'final_stage_id': dialogue_data.get('current_stage_id'), # Log the stage it ended on
                      'is_active': False # Explicitly log it ended
                  }
                  # Assuming log_event is async
                  await game_log_manager.log_event(
                       guild_id=guild_id_str,
                       event_type="dialogue_end",
                       message=log_message,
                       related_entities=related_entities,
                       metadata=metadata
                   )
             except Exception as e:
                   print(f"DialogueManager: ❌ Error logging dialogue end for {dialogue_id_str} in guild {guild_id_str}: {e}")
                   traceback.print_exc()


        print(f"DialogueManager: Dialogue {dialogue_id_str} fully ended, removed from active cache, and marked for deletion for guild {guild_id_str}.")


    # load_state(guild_id, **kwargs) - called by PersistenceManager
    # Needs to load ACTIVE dialogues for the specific guild.
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает активные диалоги и шаблоны для определенной гильдии из базы данных/настроек в кеш."""
        guild_id_str = str(guild_id)
        print(f"DialogueManager: Loading state for guild {guild_id_str} (dialogues + templates)...")

        if self._db_adapter is None:
            print(f"DialogueManager: Warning: No DB adapter. Skipping dialogue/template load for guild {guild_id_str}. It will work with empty caches.")
            # TODO: In non-DB mode, load placeholder data (e.g. from files/defaults)
            self._active_dialogues.pop(guild_id_str, None)
            self._active_dialogues[guild_id_str] = {} # Ensure empty cache exists for this guild
            self._dialogue_templates.pop(guild_id_str, None)
            self._dialogue_templates[guild_id_str] = {} # Ensure empty cache exists for this guild
            # Clear dirty/deleted sets for this guild as they are not relevant without DB
            self._dirty_dialogues.pop(guild_id_str, None)
            self._deleted_dialogue_ids.pop(guild_id_str, None)
            return

        # --- 1. Загрузка статических шаблонов (per-guild) ---
        # Call the helper method
        self.load_dialogue_templates(guild_id_str)


        # --- 2. Загрузка активных диалогов (per-guild) ---
        # Очищаем кеши диалогов ТОЛЬКО для этой гильдии перед загрузкой
        self._active_dialogues.pop(guild_id_str, None) # Remove old cache for this guild
        self._active_dialogues[guild_id_str] = {} # Create an empty cache for this guild

        # Upon loading, everything in DB is considered "clean", so clear dirty/deleted for this guild
        self._dirty_dialogues.pop(guild_id_str, None)
        self._deleted_dialogue_ids.pop(guild_id_str, None)

        rows = []
        try:
            # Execute SQL SELECT FROM dialogues WHERE guild_id = ? AND is_active = 1 (assuming dialogues table has is_active)
            # Assuming table has columns: id, template_id, guild_id, participants, channel_id, current_stage_id, state_variables, last_activity_game_time, event_id, is_active
            sql = '''
            SELECT id, template_id, guild_id, participants, channel_id,
                   current_stage_id, state_variables, last_activity_game_time, event_id,
                   is_active -- Assuming is_active column exists
            FROM dialogues WHERE guild_id = ? AND is_active = 1
            '''
            # Assuming fetchall is async
            rows = await self._db_adapter.fetchall(sql, (guild_id_str,)) # Filter by guild_id and active
            print(f"DialogueManager: Found {len(rows)} active dialogues in DB for guild {guild_id_str}.")

        except Exception as e:
            print(f"DialogueManager: ❌ CRITICAL ERROR executing DB fetchall for dialogues for guild {guild_id_str}: {e}")
            # import traceback # traceback should be imported at the top
            print(traceback.format_exc())
            # Clear cache for this guild on critical error (already done above pop/setdefault)
            raise # Re-raise critical error


        loaded_count = 0
        # Get the cache dict for this specific guild
        guild_dialogues_cache = self._active_dialogues.get(guild_id_str) # Should exist due to setdefault/pop

        if guild_dialogues_cache is None:
             # Should not happen with pop/setdefault pattern above, but as a safety
             print(f"DialogueManager: CRITICAL ERROR: Guild cache for {guild_id_str} disappeared during load.")
             return # Cannot proceed

        for row in rows:
             data = dict(row) # Convert row tuple/list to dict for easier access
             try:
                 # Validate and parse data
                 dialogue_id_raw = data.get('id')
                 loaded_guild_id_raw = data.get('guild_id') # Should match guild_id_str due to WHERE clause

                 if dialogue_id_raw is None or loaded_guild_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                     # This check is mostly redundant due to WHERE clause but safe.
                     print(f"DialogueManager: Warning: Skipping dialogue row with invalid ID ('{dialogue_id_raw}') or mismatched guild ('{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row}.")
                     continue

                 dialogue_id = str(dialogue_id_raw)


                 # Parse JSON fields, handle None/malformed data gracefully
                 try:
                     # Ensure participant IDs are strings after load
                     participants_raw = data.get('participants')
                     data['participants'] = [str(p) for p in json.loads(participants_raw) if p is not None] if isinstance(participants_raw, (str, bytes)) else []
                 except (json.JSONDecodeError, TypeError):
                      print(f"DialogueManager: Warning: Failed to parse participants for dialogue {dialogue_id} in guild {guild_id_str}. Setting to []. Data: {data.get('participants')}")
                      data['participants'] = []


                 try:
                     state_variables_raw = data.get('state_variables')
                     data['state_variables'] = json.loads(state_variables_raw) if isinstance(state_variables_raw, (str, bytes)) else {}
                 except (json.JSONDecodeError, TypeError):
                      print(f"DialogueManager: Warning: Failed to parse state_variables for dialogue {dialogue_id} in guild {guild_id_str}. Setting to {{}}. Data: {data.get('state_variables')}")
                      data['state_variables'] = {}


                 # Convert boolean/numeric/string types, handle potential None/malformed data
                 # is_active check in SQL filters for 1 (True), but data might still be 0/1/None.
                 # Ensure we store boolean.
                 data['is_active'] = bool(data.get('is_active', 0)) if data.get('is_active') is not None else True # Default True if None/missing in DB column

                 # Ensure float or None for nullable numeric field
                 last_activity_raw = data.get('last_activity_game_time')
                 data['last_activity_game_time'] = float(last_activity_raw) if isinstance(last_activity_raw, (int, float)) else None

                 # Ensure string or None for nullable string fields
                 data['template_id'] = str(data.get('template_id')) if data.get('template_id') is not None else None
                 data['current_stage_id'] = str(data.get('current_stage_id')) if data.get('current_stage_id') is not None else 'start' # Ensure string stage ID
                 data['event_id'] = str(data.get('event_id')) if data.get('event_id') is not None else None

                 # Ensure int or None for nullable integer field (channel_id)
                 channel_id_raw = data.get('channel_id')
                 data['channel_id'] = int(channel_id_raw) if channel_id_raw is not None else None # Store channel_id as int or None


                 # Update data dict with validated/converted values
                 data['id'] = dialogue_id
                 data['guild_id'] = guild_id_str # Ensure guild_id string


                 # Store the loaded dialogue data dict in the per-guild cache of active dialogues
                 # We are not using a dedicated Dialogue model currently, just storing the data dicts.
                 # Only add if truly active (redundant due to SQL filter, but safe)
                 if data.get('is_active', True):
                     guild_dialogues_cache[data['id']] = {
                         'id': data['id'],
                         'template_id': data['template_id'],
                         'guild_id': data['guild_id'],
                         'participants': data['participants'],
                         'channel_id': data['channel_id'],
                         'current_stage_id': data['current_stage_id'],
                         'state_variables': data['state_variables'],
                         'last_activity_game_time': data['last_activity_game_time'],
                         'event_id': data['event_id'],
                         'is_active': data['is_active'], # Include is_active in the dict
                     }
                     loaded_count += 1
                 # else: // Inactive dialogues are excluded by SQL query anyway


             except Exception as e:
                 print(f"DialogueManager: Error loading dialogue {data.get('id', 'N/A')} for guild {guild_id_str}: {e}")
                 # import traceback # traceback should be imported at the top
                 print(traceback.format_exc())
                 # Continue loop for other rows


        print(f"DialogueManager: Successfully loaded {loaded_count} active dialogues into cache for guild {guild_id_str}.")
        print(f"DialogueManager: Load state complete for guild {guild_id_str}.")


    # save_state - saves per-guild
    # required_args_for_save = ["guild_id"]
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет активные/измененные диалоги для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"DialogueManager: Saving dialogues for guild {guild_id_str}...")

        if self._db_adapter is None:
            print(f"DialogueManager: Warning: Cannot save dialogues for guild {guild_id_str}, DB adapter missing.")
            return

        # ИСПРАВЛЕНИЕ: Соберите dirty/deleted ID ИЗ per-guild кешей
        # Note: Currently, only active dialogues marked dirty are saved.
        # If you need to save *all* ended dialogues (is_active=False) for logging/history,
        # adjust this logic to include non-active dialogues from cache belonging to this guild.
        dirty_dialogue_ids_for_guild_set = self._dirty_dialogues.get(guild_id_str, set()).copy() # Use a copy to iterate
        deleted_dialogue_ids_for_guild_set = self._deleted_dialogue_ids.get(guild_id_str, set()).copy() # Use a copy to iterate

        # Filter active dialogues by guild_id AND dirty status
        guild_dialogues_cache = self._active_dialogues.get(guild_id_str, {})
        dialogues_to_save: List[Dict[str, Any]] = []

        # Iterate over dirty IDs for this guild
        for d_id in dirty_dialogue_ids_for_guild_set:
             # Get the dialogue data from the active cache for this guild
             d = guild_dialogues_cache.get(d_id)
             # Only add if found in active cache AND belongs to this guild (safety check)
             if d and d.get('guild_id') == guild_id_str:
                  # Add a copy to the list to avoid modifying the cache while preparing for save
                  dialogues_to_save.append(d.copy())
             # else: dialogue was marked dirty but not found in active cache (e.g. ended before save) - it will be skipped by upsert and remain dirty.
             # Or it was marked dirty in a different guild's set - should not happen with per-guild sets.


        if not dialogues_to_save and not deleted_dialogue_ids_for_guild_set:
            # print(f"DialogueManager: No dirty or deleted dialogues to save for guild {guild_id_str}.") # Too noisy
            # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, очищаем per-guild dirty/deleted сеты
            self._dirty_dialogues.pop(guild_id_str, None) # Clear the guild's dirty set
            self._deleted_dialogue_ids.pop(guild_id_str, None) # Clear the guild's deleted set
            return

        print(f"DialogueManager: Saving {len(dialogues_to_save)} dirty active, {len(deleted_dialogue_ids_for_guild_set)} deleted dialogues for guild {guild_id_str}...")


        try:
            # 1. Удаление диалогов, помеченных для удаления для этой гильдии
            if deleted_dialogue_ids_for_guild_set:
                 ids_to_delete = list(deleted_dialogue_ids_for_guild_set)
                 # SQLite allows placeholders like (?, ?, ...). Max is usually 999. Handle larger lists if needed.
                 # For typical dialogue counts, this should be fine.
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 # Ensure deleting only for this guild and these IDs
                 # Assuming 'id' is the PK and 'guild_id' is a column
                 delete_sql = f"DELETE FROM dialogues WHERE guild_id = ? AND id IN ({placeholders_del})"
                 try:
                     # Assuming execute is async
                     await self._db_adapter.execute(sql=delete_sql, params=(guild_id_str, *tuple(ids_to_delete))) # Use keyword args if adapter supports it (params=...)
                     print(f"DialogueManager: Deleted {len(ids_to_delete)} dialogues from DB for guild {guild_id_str}.")
                     # ИСПРАВЛЕНИЕ: Очищаем per-guild deleted set after successful deletion
                     self._deleted_dialogue_ids.pop(guild_id_str, None) # Clear the guild's deleted set
                 except Exception as e:
                     print(f"DialogueManager: Error deleting dialogues for guild {guild_id_str}: {e}")
                     # import traceback # traceback should be imported at the top
                     print(traceback.format_exc())
                     # Do NOT clear deleted set on error - they remain marked for deletion for next save attempt.


            # 2. Обновить или вставить измененные диалоги для этого guild_id
            if dialogues_to_save:
                 print(f"DialogueManager: Upserting {len(dialogues_to_save)} active dialogues for guild {guild_id_str}...")
                 # Use correct column names based on expected schema
                 upsert_sql = '''
                 INSERT OR REPLACE INTO dialogues
                 (id, template_id, guild_id, participants, channel_id, current_stage_id, state_variables, last_activity_game_time, event_id, is_active)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                 '''
                 data_to_upsert_params = []
                 upserted_dialogue_ids_on_success: Set[str] = set() # Track IDs successfully prepared for upsert

                 for d in dialogues_to_save: # d is a Dict[str, Any] (a copy)
                      try:
                           # Ensure dialogue data dict has all required keys and types
                           dialogue_id = d.get('id')
                           dialogue_guild_id = d.get('guild_id')

                           # Double check required fields and guild ID match
                           if dialogue_id is None or dialogue_guild_id != guild_id_str:
                               print(f"DialogueManager: Warning: Skipping upsert for dialogue with invalid ID ('{dialogue_id}') or mismatched guild ('{dialogue_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}. Data: {d}.")
                               continue # Skip this dialogue if invalid


                           template_id = d.get('template_id')
                           participants = d.get('participants', [])
                           channel_id = d.get('channel_id')
                           current_stage_id = d.get('current_stage_id')
                           state_variables = d.get('state_variables', {})
                           last_activity_game_time = d.get('last_activity_game_time')
                           event_id = d.get('event_id')
                           is_active = d.get('is_active', True) # Default to True if missing


                           # Ensure data types are suitable for JSON dumping / DB columns
                           if not isinstance(participants, list): participants = [] # Ensure list for JSON
                           if not isinstance(state_variables, dict): state_variables = {} # Ensure dict for JSON

                           participants_json = json.dumps(participants)
                           state_variables_json = json.dumps(state_variables)

                           # Prepare tuple of parameters for execute_many
                           data_to_upsert_params.append((
                               str(dialogue_id), # Ensure string ID
                               str(template_id) if template_id is not None else None, # Ensure str or None
                               guild_id_str, # Ensure guild_id string
                               participants_json,
                               int(channel_id) if channel_id is not None else None, # Ensure int or None
                               str(current_stage_id) if current_stage_id is not None else None, # Ensure str or None
                               state_variables_json,
                               float(last_activity_game_time) if last_activity_game_time is not None else None, # Ensure float or None
                               str(event_id) if event_id is not None else None, # Ensure str or None
                               int(bool(is_active)), # Save boolean as integer (1 or 0)
                           ))
                           upserted_dialogue_ids_on_success.add(str(dialogue_id)) # Track ID that was prepared


                      except Exception as e:
                           print(f"DialogueManager: Error preparing data for dialogue {d.get('id', 'N/A')} (guild {d.get('guild_id', 'N/A')}) for upsert: {e}. Data: {d}")
                           # import traceback # traceback should be imported at the top
                           print(traceback.format_exc())
                           # This dialogue won't be saved but remains in _dirty_dialogues


                 if data_to_upsert_params: # Only execute if there is data to upsert
                      if self._db_adapter is None:
                           print(f"DialogueManager: Warning: DB adapter is None during dialogue upsert batch for guild {guild_id_str}.")
                      else:
                           # Assuming execute_many is async
                           await self._db_adapter.execute_many(sql=upsert_sql, data=data_to_upsert_params) # Use keyword args
                           print(f"DialogueManager: Successfully upserted {len(data_to_upsert_params)} active dialogues for guild {guild_id_str}.")

                           # Only clear dirty flags for dialogues that were successfully processed and upserted
                           if guild_id_str in self._dirty_dialogues:
                                # Remove only the IDs that were successfully upserted from the dirty set for this guild
                                self._dirty_dialogues[guild_id_str].difference_update(upserted_dialogue_ids_on_success)
                                # If the set becomes empty after update, remove the guild key
                                if not self._dirty_dialogues[guild_id_str]:
                                     del self._dirty_dialogues[guild_id_str]
                           # else: Dirty set for this guild was already empty or didn't exist.


        except Exception as e:
            print(f"DialogueManager: ❌ Error during saving state for guild {guild_id_str}: {e}")
            # import traceback # traceback should be imported at the top
            print(traceback.format_exc())
            # Do NOT clear dirty/deleted sets on error to allow retry on next save.
            # raise # Re-raise if critical


        print(f"DialogueManager: Save state complete for guild {guild_id_str}.")


    # rebuild_runtime_caches(guild_id, **kwargs) - called by PersistenceManager
    # Rebuilds runtime caches specific to the guild after loading.
    # Already takes guild_id and **kwargs
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """
        Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии.
        Например, кеш {participant_id: dialogue_id}.
        """
        guild_id_str = str(guild_id)
        print(f"DialogueManager: Rebuilding runtime caches for guild {guild_id_str}...")

        # Get all active dialogues loaded for this guild
        # Use the per-guild cache
        guild_dialogues = self._active_dialogues.get(guild_id_str, {}).values()

        # Example: Rebuild {participant_id: dialogue_id} map for this guild
        # if hasattr(self, '_participant_to_dialogue_map'): # Check if the attribute exists and is initialized
        #      # Use setdefault to ensure the guild's inner dict exists
        #      guild_participant_map = self._participant_to_dialogue_map.setdefault(guild_id_str, {})
        #      guild_participant_map.clear() # Clear old map for this guild before rebuilding

        #      for dialogue_data in guild_dialogues: # Iterate through dialogues loaded for THIS guild
        #           dialogue_id = dialogue_data.get('id')
        #           if dialogue_id is None:
        #                print(f"DialogueManager: Warning: Skipping dialogue with no ID during rebuild for guild {guild_id_str}. Data: {dialogue_data}.")
        #                continue
        #           participants = dialogue_data.get('participants', [])
        #           if isinstance(participants, list):
        #                for p_id in participants:
        #                     # Ensure participant ID is a string
        #                     p_id_str = str(p_id) if p_id is not None else None
        #                     if p_id_str:
        #                          # TODO: Check conflicts - one participant in multiple dialogues? (Shouldn't happen for active, but handle gracefully)
        #                          if p_id_str in guild_participant_map:
        #                               print(f"DialogueManager: Warning: Participant {p_id_str} found in multiple active dialogues during rebuild for guild {guild_id_str}: already in {guild_participant_map[p_id_str]}, now in {dialogue_id}.")
        #                               # Decide policy: Keep first? Overwrite? For map, overwrite is common.
        #                          guild_participant_map[p_id_str] = dialogue_id


        # Entity managers (Character, NPC, Party) need to know if their entities are busy in dialogue.
        # They will typically get DialogueManager from kwargs and use is_in_dialogue(guild_id, entity_id)
        # or iterate through active dialogues (using get_active_dialogues(guild_id))
        # to rebuild *their own* per-guild busy status caches.
        # This manager doesn't rebuild the busy status *in other managers*.
        # It provides the methods (like is_in_dialogue, get_active_dialogues) for other managers to use during *their* rebuild.

        print(f"DialogueManager: Rebuild runtime caches complete for guild {guild_id_str}. (Dialogue specific caches)")


    # mark_dialogue_dirty needs guild_id
    # Needs _dirty_dialogues Set (per-guild)
    def mark_dialogue_dirty(self, guild_id: str, dialogue_id: str) -> None:
         """Помечает диалог как измененный для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         dialogue_id_str = str(dialogue_id)
         # Add check that the dialogue ID exists in the per-guild active cache before marking dirty
         guild_dialogues_cache = self._active_dialogues.get(guild_id_str)
         if guild_dialogues_cache and dialogue_id_str in guild_dialogues_cache:
              # Add to the per-guild dirty set
              self._dirty_dialogues.setdefault(guild_id_str, set()).add(dialogue_id_str)
         # else: print(f"DialogueManager: Warning: Attempted to mark non-existent active dialogue {dialogue_id_str} in guild {guild_id_str} as dirty.") # Too noisy?


    # TODO: Implement clean_up_for_entity method (used by Character/NPC/Party Managers)
    # This method is called by CharacterManager.remove_character, NpcManager.remove_npc etc.
    # It should find and end any dialogue the entity is involved in.
    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
         """
         Завершает любой диалог, в котором участвует сущность, когда сущность удаляется.
         Предназначен для вызова менеджерами сущностей (Character, NPC).
         """
         # Get guild_id from context kwargs
         guild_id = kwargs.get('guild_id')
         if guild_id is None:
              print(f"DialogueManager: Warning: clean_up_for_entity called for {entity_type} {entity_id} without guild_id in context. Cannot clean up from dialogue.")
              return # Cannot clean up without guild_id

         guild_id_str = str(guild_id)
         entity_id_str = str(entity_id)
         print(f"DialogueManager: Cleaning up {entity_type} {entity_id} from dialogue in guild {guild_id_str}...")

         # Find the dialogue the entity is in within this guild
         # Use the updated is_in_dialogue logic or iterate through per-guild cache
         # Iterate over a copy of keys to avoid issues if end_dialogue modifies the dict
         dialogue_id_to_end: Optional[str] = None
         guild_dialogues = self._active_dialogues.get(guild_id_str)
         if guild_dialogues:
              for d_id, d_data in guild_dialogues.items(): # Use .items() for ID and data
                  participants = d_data.get('participants', [])
                  if isinstance(participants, list) and entity_id_str in participants:
                       dialogue_id_to_end = d_id # Found the ID
                       # Found the dialogue. Assuming an entity is only in one dialogue at a time.
                       break # Found it, exit loop

         if dialogue_id_to_end:
              print(f"DialogueManager: Found dialogue {dialogue_id_to_end} involving {entity_type} {entity_id} in guild {guild_id_str}. Ending dialogue.")
              # Call end_dialogue directly, passing context
              # end_dialogue removes the dialogue from the active cache.
              await self.end_dialogue(guild_id_str, dialogue_id_to_end, **kwargs) # Pass guild_id and context
         # else: print(f"DialogueManager: {entity_type} {entity_id} is not in any active dialogue in guild {guild_id_str}.") # Too noisy?


    # mark_dialogue_deleted needs guild_id
    # Needs _deleted_dialogue_ids Set (per-guild)
    # Called by end_dialogue
    def mark_dialogue_deleted(self, guild_id: str, dialogue_id: str) -> None:
         """Помечает диалог как удаленный для определенной гильдии."""
         guild_id_str = str(guild_id)
         dialogue_id_str = str(dialogue_id)

         # Check if dialogue is currently in the active cache for this guild
         # This is primarily a safety check, end_dialogue should remove it.
         # It also prevents marking non-existent dialogues for deletion.
         guild_dialogues_cache = self._active_dialogues.get(guild_id_str)
         if guild_dialogues_cache and dialogue_id_str in guild_dialogues_cache:
              print(f"DialogueManager: Warning: Attempted to mark dialogue {dialogue_id_str} in guild {guild_id_str} as deleted, but it's still in active cache. Removing from active cache.")
              # Remove from active cache just in case end_dialogue didn't
              guild_dialogues_cache.pop(dialogue_id_str, None)


         # Add to per-guild deleted set
         self._deleted_dialogue_ids.setdefault(guild_id_str, set()).add(dialogue_id_str)

         # Remove from per-guild dirty set if it was there (a deleted dialogue doesn't need upserting)
         self._dirty_dialogues.get(guild_id_str, set()).discard(dialogue_id_str)

         print(f"DialogueManager: Dialogue {dialogue_id_str} marked for deletion for guild {guild_id_str}.")

         # Handle case where dialogue was already marked for deletion (optional logging)
         # elif guild_id_str in self._deleted_dialogue_ids and dialogue_id_str in self._deleted_dialogue_ids[guild_id_str]:
         #      print(f"DialogueManager: Dialogue {dialogue_id_str} in guild {guild_id_str} already marked for deletion.")
         # else:
         #      print(f"DialogueManager: Warning: Attempted to mark non-existent dialogue {dialogue_id_str} in guild {guild_id_str} as deleted (not in active cache or deleted set).")


    # TODO: Implement process_tick method if needed for dialogue timeouts etc.
    # Called by WorldSimulationProcessor
    # Needs guild_id, game_time_delta, context
    # async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None: ...


    # TODO: Implement get_dialogue_by_participant_id if needed frequently (using the map cache)
    # async def get_dialogue_by_participant_id(self, guild_id: str, entity_id: str) -> Optional[Dict[str, Any]]: ...


    # TODO: Implement other dialogue actions like cancel_dialogue, send_message_in_dialogue (delegates to send_callback_factory from context)
    # async def cancel_dialogue(self, guild_id: str, dialogue_id: str, **kwargs: Any) -> None: ...


    async def process_player_dialogue_message(
        self, character: Any, message_text: str, channel_id: int, guild_id: str, **kwargs: Any # Added kwargs for context
    ):
        """
        Processes a raw message from a player who is currently in a dialogue state.
        This is a placeholder. Actual implementation would involve:
        - Retrieving the active dialogue session for the character.
        - Parsing the message_text (e.g., for keywords, NLU intent within dialogue context).
        - Calling self.advance_dialogue with appropriate action_data.
        - Sending responses back to the channel.
        """
        # TODO: Implement actual dialogue continuation logic
        guild_id_str = str(guild_id)
        char_id_str = str(character.id)
        print(
             f"DialogueManager: Received raw message '{message_text}' from {getattr(character, 'name', char_id_str)} (ID: {char_id_str}) "
             f"in potential dialogue context (Guild: {guild_id_str}) in channel {channel_id}."
        )

        active_dialogue = None
        dialogue_id = None
        # Example of how to find the dialogue (using the cache directly)
        guild_dialogues = self._active_dialogues.get(guild_id_str, {})
        for d_id, d_data in guild_dialogues.items():
            participants = d_data.get("participants", [])
            if isinstance(participants, list) and char_id_str in participants:
                active_dialogue = d_data  # Found it
                dialogue_id = d_id
                break # Found the dialogue, assuming max one dialogue per participant

        if active_dialogue and dialogue_id:
            print(
                f"DialogueManager: Processing message for character {char_id_str} in dialogue {dialogue_id}."
            )
            # Here, you would parse message_text and then potentially call:
            # action_data = self._parse_dialogue_message(active_dialogue, char_id_str, message_text, **kwargs) # Needs implementation
            # if action_data:
            #    await self.advance_dialogue(guild_id_str, dialogue_id, char_id_str, action_data, channel_id=channel_id, **kwargs)
            # else:
            #    print(f"DialogueManager: Message '{message_text}' from {char_id_str} in dialogue {dialogue_id} did not match any valid dialogue action.")
            #    # Optional: Send feedback "That didn't make sense." - Needs send_callback_factory from kwargs.
            pass # Placeholder for actual processing

        else:
            print(
                f"DialogueManager: Received message '{message_text}' from {char_id_str} (Guild: {guild_id_str}) "
                f"in channel {channel_id}, but NO ACTIVE DIALOGUE found for them."
            )
            # This case might indicate an issue with state management or dialogue cleanup.
            # The CommandRouter (or calling code) should ideally check is_in_dialogue *before* calling this method,
            # and route non-dialogue messages elsewhere. If it still happens, log it.


# --- Конец класса DialogueManager ---

print("DEBUG: dialogue_manager.py module loaded.")
