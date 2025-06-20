# bot/game/managers/event_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
# Импорт базовых типов
# ИСПРАВЛЕНИЕ: Импортируем необходимые типы из typing
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union # Added Union

# Импорт модели Event (для аннотаций и работы с объектами при runtime)
from bot.game.models.event import Event # Прямой импорт

# Адаптер БД
from bot.services.db_service import DBService # Changed

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins


if TYPE_CHECKING:
    # Опциональные зависимости только для аннотаций, чтобы разорвать циклы
    # Используем строковые литералы ("ClassName")
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.services.openai_service import OpenAIService
    # Добавляем другие менеджеры/процессоры, которые могут быть в context kwargs
    # from bot.game.event_processors.event_action_processor import EventActionProcessor
    # from bot.game.character_processors.character_view_service import CharacterViewService


class EventManager:
    """
    Менеджер для загрузки шаблонов и управления событиями:
    создание, хранение, сохранение/загрузка и удаление.
    Работает на основе guild_id для многогильдийной поддержки.
    """
    # Required args для PersistenceManager
    required_args_for_load: List[str] = ["guild_id"] # Загрузка per-guild
    required_args_for_save: List[str] = ["guild_id"] # Сохранение per-guild
    # ИСПРАВЛЕНИЕ: Добавляем guild_id для rebuild_runtime_caches
    required_args_for_rebuild: List[str] = ["guild_id"] # Rebuild per-guild


    # --- Class-Level Attribute Annotations ---
    # Статические шаблоны событий: {guild_id: {template_id: data_dict}}
    # ИСПРАВЛЕНИЕ: Шаблоны должны быть per-guild
    _event_templates: Dict[str, Dict[str, Dict[str, Any]]]

    # Кеш активных событий: {guild_id: {event_id: Event_object}}
    # ИСПРАВЛЕНИЕ: Кеш активных событий должен быть per-guild
    _active_events: Dict[str, Dict[str, "Event"]] # Аннотация кеша использует строковый литерал "Event"

    # Кеш событий по каналу: {guild_id: {channel_id: event_id}}
    # ИСПРАВЛЕНИЕ: Кеш по каналу должен быть per-guild
    _active_events_by_channel: Dict[str, Dict[int, str]] # {guild_id: {channel_id: event_id}}

    # Изменённые события, подлежащие записи: {guild_id: set(event_ids)}
    # ИСПРАВЛЕНИЕ: dirty events также per-guild
    _dirty_events: Dict[str, Set[str]]

    # Удалённые события, подлежащие удалению из БД: {guild_id: set(event_ids)}
    # ИСПРАВЛЕНИЕ: deleted event ids также per-guild
    _deleted_event_ids: Dict[str, Set[str]]


    def __init__(
        self,
        # Используем строковые литералы для всех опциональных зависимостей
        db_service: Optional["DBService"] = None, # Changed
        settings: Optional[Dict[str, Any]] = None,
        npc_manager: Optional["NpcManager"] = None, # Use string literal!
        item_manager: Optional["ItemManager"] = None, # Use string literal!
        location_manager: Optional["LocationManager"] = None, # Use string literal!
        rule_engine: Optional["RuleEngine"] = None, # Use string literal!
        character_manager: Optional["CharacterManager"] = None, # Use string literal!
        combat_manager: Optional["CombatManager"] = None, # Use string literal!
        status_manager: Optional["StatusManager"] = None, # Use string literal!
        party_manager: Optional["PartyManager"] = None, # Use string literal!
        time_manager: Optional["TimeManager"] = None, # Use string literal!
        event_stage_processor: Optional["EventStageProcessor"] = None, # Use string literal!
        # Add other injected dependencies here with Optional and string literals
        # Example: event_action_processor: Optional["EventActionProcessor"] = None,
        multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None,
        openai_service: Optional["OpenAIService"] = None
    ):
        print("Initializing EventManager...")
        self._db_service = db_service # Changed
        self._settings = settings

        # Инжектированные зависимости
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._time_manager = time_manager
        self._event_stage_processor = event_stage_processor
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._openai_service = openai_service
        # self._event_action_processor = event_action_processor


        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые outer словари
        self._event_templates = {} # {guild_id: {tpl_id: data_dict}}
        self._active_events = {} # {guild_id: {event_id: Event_object}}
        self._active_events_by_channel = {} # {guild_id: {channel_id: event_id}}
        self._dirty_events = {} # {guild_id: set(event_ids)}
        self._deleted_event_ids = {} # {guild_id: set(event_ids)}

        # Загружаем статические шаблоны НЕ здесь. Загрузка per-guild происходит в load_state.
        # _load_event_templates() # Remove this call from __init__

        print("EventManager initialized.\n")

    # Переименовываем _load_event_templates в load_static_templates (не вызывается PM)
    # Этот метод будет вызываться из load_state
    def load_static_templates(self, guild_id: str) -> None:
        """(Пример) Загружает статические шаблоны для определенной гильдии из настроек или файлов."""
        guild_id_str = str(guild_id)
        print(f"EventManager: Loading event templates for guild {guild_id_str}...")

        # Очищаем кеш шаблонов для этой гильдии перед загрузкой
        self._event_templates.pop(guild_id_str, None)
        guild_templates_cache = self._event_templates.setdefault(guild_id_str, {}) # Create empty cache for this guild

        try:
            # Пример загрузки из settings (предполагаем структуру settings['guilds'][guild_id]['event_templates']
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            templates_data = guild_settings.get('event_templates')

            # TODO: Add fallback to global templates file like in ItemManager

            if isinstance(templates_data, dict):
                 for tpl_id, data in templates_data.items():
                      # Basic validation
                      if tpl_id and isinstance(data, dict):
                           clone = data.copy() # Work on a copy
                           clone.setdefault('id', str(tpl_id)) # Ensure id is in data and is string
                           clone.setdefault('name', f"Unnamed Event ({tpl_id})") # Ensure name
                           # Ensure stages_data is a dict
                           stages_data = clone.get('stages_data', {})
                           if not isinstance(stages_data, dict):
                                print(f"EventManager: Warning: Template '{tpl_id}' stages_data is not a dict ({type(stages_data)}) for guild {guild_id_str}. Using empty dict.")
                                stages_data = {}
                           clone['stages_data'] = stages_data

                           # Ensure start_stage_id exists if stages_data is not empty
                           if stages_data and not clone.get('start_stage_id'):
                                if stages_data: # If there are stages defined
                                     # Try to find the first key in stages_data as start_stage_id
                                     first_stage_id = next(iter(stages_data), None)
                                     if first_stage_id:
                                         clone.setdefault('start_stage_id', str(first_stage_id))
                                         print(f"EventManager: Warning: Template '{tpl_id}' missing start_stage_id, defaulting to first stage '{first_stage_id}'.")
                                     else:
                                          print(f"EventManager: Warning: Template '{tpl_id}' stages_data is empty, cannot set start_stage_id.")

                           # Store template with string ID
                           guild_templates_cache[str(tpl_id)] = clone

                 print(f"EventManager: Loaded {len(guild_templates_cache)} event templates for guild {guild_id_str}.")
            elif templates_data is not None:
                 print(f"EventManager: Warning: Event templates data for guild {guild_id_str} is not a dictionary ({type(templates_data)}). Skipping template load.")
            else:
                 print(f"EventManager: No event templates found in settings for guild {guild_id_str} or globally.")


        except Exception as e:
            print(f"EventManager: ❌ Error loading event templates for guild {guild_id_str}: {e}")
            traceback.print_exc()
            # Decide how to handle error - should template loading failure be critical?
            # For now, log and continue with empty template cache for this guild.


    # get_event_template now needs guild_id
    def get_event_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        """Возвращает данные шаблона по его ID для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Get templates from the per-guild cache
        guild_templates = self._event_templates.get(guild_id_str, {})
        return guild_templates.get(str(template_id)) # Ensure template_id is string


    # get_event now needs guild_id
    def get_event(self, guild_id: str, event_id: str) -> Optional["Event"]:
        """Получить объект события по ID для определенной гильдии (из кеша активных)."""
        guild_id_str = str(guild_id)
        # Get events from the per-guild cache
        guild_events = self._active_events.get(guild_id_str) # Get per-guild cache
        if guild_events:
             return guild_events.get(str(event_id)) # Ensure event_id is string
        return None # Guild or event not found


    # get_active_events now needs guild_id
    def get_active_events(self, guild_id: str) -> List["Event"]:
        """Получить список всех активных событий для определенной гильдии (из кеша)."""
        guild_id_str = str(guild_id)
        guild_events = self._active_events.get(guild_id_str) # Get per-guild cache
        if guild_events:
             return list(guild_events.values())
        return [] # Return empty list if no active events for guild


    # get_event_by_channel_id now needs guild_id
    def get_event_by_channel_id(self, guild_id: str, channel_id: int) -> Optional["Event"]:
        """Найти активное событие по ID канала для определенной гильдии."""
        guild_id_str = str(guild_id)
        channel_id_int = int(channel_id) # Ensure channel_id is integer

        # Get channel map from the per-guild cache
        guild_channel_map = self._active_events_by_channel.get(guild_id_str) # Get per-guild channel map
        if guild_channel_map:
             event_id = guild_channel_map.get(channel_id_int) # Get event ID from channel map
             if event_id:
                 # Get event object from the per-guild event cache
                 return self.get_event(guild_id_str, event_id) # Use get_event with guild_id

        return None # Guild, map, or event not found


    # create_event_from_template now needs guild_id and uses per-guild caches
    async def create_event_from_template(
        self,
        guild_id: str, # Added guild_id
        template_id: str,
        location_id: Optional[str] = None, # Instance ID
        initial_player_ids: Optional[List[str]] = None, # List of Character IDs
        channel_id: Optional[int] = None,
        **kwargs: Any,
    ) -> Optional["Event"]: # Returns Event object
        """Создает новое событие из шаблона для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"EventManager: Creating event for guild {guild_id_str} from template '{template_id}'")

        if self._db_service is None or self._db_service.adapter is None: # Changed
            print(f"EventManager: No DB service or adapter for guild {guild_id_str}. Cannot create persistent event.")
            # Should creating an event require persistence? Maybe temporary events don't.
            # For now, assume events require persistence.
            return None

        # Get template for this guild
        tpl = self.get_event_template(guild_id_str, template_id) # Use get_event_template with guild_id
        if not tpl:
            print(f"EventManager: Template '{template_id}' not found for guild {guild_id_str}.")
            # TODO: Send feedback if a command triggered this
            return None

        # TODO: Validation (initial_player_ids exist, location_id exists, channel_id is valid for guild etc.)
        # Use injected managers (character_manager, location_manager) with guild_id checks.
        # char_mgr = kwargs.get('character_manager', self._character_manager) # type: Optional["CharacterManager"]
        # loc_mgr = kwargs.get('location_manager', self._location_manager) # type: Optional["LocationManager"]
        # ... validation logic ...


        try:
            eid = str(uuid.uuid4()) # Generate unique ID for the event instance

            # Prepare data for the Event object
            # Ensure stages_data and initial_state_variables are copied from the template
            tpl_stages_data = tpl.get('stages_data', {})
            if not isinstance(tpl_stages_data, dict): tpl_stages_data = {} # Ensure dict
            tpl_initial_state_variables = tpl.get('initial_state_variables', {})
            if not isinstance(tpl_initial_state_variables, dict): tpl_initial_state_variables = {} # Ensure dict

            # Allow overriding initial state variables and stages data from kwargs
            initial_state_variables = kwargs.get('initial_state_variables', {}).copy() # Get from kwargs, copy to avoid modifying source
            initial_state_variables.update(tpl_initial_state_variables) # Apply template defaults *after* kwargs overrides? Or before? Decide policy. Let's do kwargs then template defaults.
            tpl_initial_state_variables.update(initial_state_variables) # Template defaults, then kwargs
            # Simpler: Start with template copy, then update with kwargs
            event_state_variables = tpl_initial_state_variables.copy()
            if kwargs.get('initial_state_variables'):
                 event_state_variables.update(kwargs['initial_state_variables']) # Override with kwargs

            event_stages_data = tpl_stages_data.copy()
            if kwargs.get('stages_data'):
                 if isinstance(kwargs['stages_data'], dict):
                      event_stages_data.update(kwargs['stages_data'])
                 else: print(f"EventManager: Warning: Provided stages_data is not a dict ({type(kwargs['stages_data'])}). Ignoring.")


            data: Dict[str, Any] = {
                'id': eid,
                'template_id': str(template_id), # Store template ID as string
                'name': str(tpl.get('name', 'Событие')), # Ensure string
                'guild_id': guild_id_str, # <--- Store guild_id with the event instance
                'is_active': kwargs.get('is_active', True), # Allow setting initial active status from kwargs
                'channel_id': int(channel_id) if channel_id is not None else None, # Store channel ID as int or None
                # TODO: Should location_id be stored on Event? Or derived from participants/stages?
                # 'location_id': str(location_id) if location_id is not None else None,

                # Determine start stage
                'current_stage_id': str(kwargs.get('start_stage_id', tpl.get('start_stage_id', 'start'))), # Allow override from kwargs, fallback to template, then 'start'

                'players': initial_player_ids or [], # List of participant IDs (Character/NPC)
                'state_variables': event_state_variables, # Dynamic state variables for event instance
                'stages_data': event_stages_data, # Stages definition for this instance (can be customized from template)
                'end_message_template': str(kwargs.get('end_message_template', tpl.get('end_message_template', 'Событие завершилось.'))), # Allow override, fallback to template, then default string
            }

            # Basic validation of players list
            if not isinstance(data.get('players'), list): data['players'] = [] # Ensure list
            else: data['players'] = [str(p) for p in data['players'] if p is not None] # Ensure player IDs are strings


            event = Event.from_dict(data) # Requires Event.from_dict


            # --- Spawn NPC and Items defined in template ---
            # Use managers from kwargs (passed by CommandRouter/WSP) or self
            npc_mgr = kwargs.get('npc_manager', self._npc_manager) # type: Optional["NpcManager"]
            item_mgr = kwargs.get('item_manager', self._item_manager) # type: Optional["ItemManager"]

            # Pass all kwargs (context) to spawn methods as well
            spawn_context = {**kwargs, 'event_id': eid} # Add event_id to context

            # Spawn NPC (template.get('npc_spawn_templates', []) is expected to be List[Dict])
            temp_npcs_ids: List[str] = []
            if npc_mgr and hasattr(npc_mgr, 'create_npc'): # Check manager and method
                 for spawn_def in tpl.get('npc_spawn_templates', []):
                      if not isinstance(spawn_def, dict): continue # Skip if not dict
                      spawn_tpl_id = spawn_def.get('template_id')
                      spawn_count = int(spawn_def.get('count', 1))
                      spawn_loc_id = spawn_def.get('location_id', location_id) # Use spawn_def loc if present, else event loc
                      spawn_is_temporary = bool(spawn_def.get('is_temporary', True))
                      spawn_name = spawn_def.get('name') # Allow specifying name in spawn def

                      if spawn_tpl_id:
                           for _ in range(spawn_count):
                                try:
                                     # create_npc needs guild_id, template_id, location_id, name, is_temporary, owner_id, **kwargs
                                     # Pass event_id as owner_id, and pass context
                                     # Pass guild_id
                                     nid = await npc_mgr.create_npc(
                                         guild_id=guild_id_str, # Pass guild_id
                                         npc_template_id=str(spawn_tpl_id), # Ensure string template_id
                                         location_id=str(spawn_loc_id) if spawn_loc_id is not None else None, # Ensure string or None
                                         name=str(spawn_name) if spawn_name is not None else None,
                                         owner_id=eid, # Event is the owner
                                         owner_type='Event', # Specify owner type
                                         is_temporary=spawn_is_temporary,
                                         **spawn_context # Pass context
                                     )
                                     if nid:
                                         temp_npcs_ids.append(nid)
                                except Exception as e:
                                     print(f"EventManager: Error spawning NPC from template '{spawn_tpl_id}' for event {eid} in guild {guild_id_str}: {e}"); traceback.print_exc();

            # Store created temporary NPC IDs in event state
            if temp_npcs_ids:
                 event.state_variables.setdefault('__temp_npcs', []).extend(temp_npcs_ids) # Use a hidden key

            # Spawn Items (template.get('item_spawn_templates', []) is expected to be List[Dict])
            temp_items_ids: List[str] = []
            if item_mgr and hasattr(item_mgr, 'create_item') and hasattr(item_mgr, 'move_item'): # Check manager and methods
                 for spawn_def in tpl.get('item_spawn_templates', []):
                      if not isinstance(spawn_def, dict): continue # Skip if not dict
                      spawn_tpl_id = spawn_def.get('template_id')
                      spawn_count = int(spawn_def.get('count', 1))
                      spawn_owner_id = spawn_def.get('owner_id') # Can specify owner in spawn def
                      spawn_owner_type = spawn_def.get('owner_type') # Can specify owner type in spawn def
                      spawn_loc_id = spawn_def.get('location_id', location_id) # Use spawn_def loc if present, else event loc
                      spawn_is_temporary = bool(spawn_def.get('is_temporary', True))
                      spawn_initial_state = spawn_def.get('state_variables') # Allow initial state override

                      if spawn_tpl_id:
                           for _ in range(spawn_count):
                                try:
                                     # create_item needs guild_id, item_data (dict), **kwargs
                                     # item_data should include template_id, is_temporary, state_variables
                                     # item_data might include owner_id, owner_type, location_id if created with them directly
                                     item_data_for_create = {
                                         'template_id': str(spawn_tpl_id), # Ensure string template_id
                                         'is_temporary': spawn_is_temporary,
                                         'state_variables': spawn_initial_state if isinstance(spawn_initial_state, dict) else {}, # Initial state
                                         # Owner/location are set by move_item AFTER creation
                                         'owner_id': None, 'owner_type': None, 'location_id': None,
                                         # TODO: Add quantity if items can stack?
                                     }
                                     # Pass guild_id
                                     iid = await item_mgr.create_item(
                                         guild_id=guild_id_str, # Pass guild_id
                                         item_data=item_data_for_create,
                                         **spawn_context # Pass context
                                     )
                                     if iid:
                                         temp_items_ids.append(iid)
                                         # Move the created item to the specified owner/location
                                         # move_item needs guild_id, item_id, new_owner_id, new_location_id, new_owner_type, **kwargs
                                         await item_mgr.move_item(
                                             guild_id=guild_id_str, # Pass guild_id
                                             item_id=iid,
                                             new_owner_id=str(spawn_owner_id) if spawn_owner_id is not None else None, # Ensure string or None
                                             new_location_id=str(spawn_loc_id) if spawn_loc_id is not None else None, # Ensure string or None
                                             new_owner_type=str(spawn_owner_type) if spawn_owner_type is not None else None, # Ensure string or None
                                             **spawn_context # Pass context
                                         )

                                except Exception as e:
                                     print(f"EventManager: Error spawning item from template '{spawn_tpl_id}' for event {eid} in guild {guild_id_str}: {e}"); traceback.print_exc();

            # Store created temporary Item IDs in event state
            if temp_items_ids:
                 event.state_variables.setdefault('__temp_items', []).extend(temp_items_ids) # Use a hidden key


            # --- Save event to active cache and mark dirty ---
            # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш активных событий
            self._active_events.setdefault(guild_id_str, {})[eid] = event

            # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш по каналу
            if event.channel_id is not None:
                 self._active_events_by_channel.setdefault(guild_id_str, {})[event.channel_id] = eid # Use guild_id for channel map

            # ИСПРАВЛЕНИЕ: Помечаем новое событие dirty (per-guild)
            self.mark_event_dirty(guild_id_str, eid)


            event_display_name = getattr(event, 'name', eid) # Safe name access
            print(f"EventManager: Event '{eid}' ('{event_display_name}') created for guild {guild_id_str} in channel {event.channel_id}. Marked dirty.")

            # Optional: Trigger RuleEngine hook for event creation?
            # rule_engine = kwargs.get('rule_engine', self._rule_engine)
            # if rule_engine and hasattr(rule_engine, 'on_event_created'):
            #      try: await rule_engine.on_event_created(event, context=kwargs)
            #      except Exception: traceback.print_exc();

            return event # Return the created Event object

        except Exception as exc:
            print(f"EventManager: ❌ Error creating event from template '{template_id}' for guild {guild_id_str}: {exc}")
            traceback.print_exc()
            # TODO: Handle rollback of spawned entities/items if event creation fails
            # Requires tracking created entities/items during spawn loop
            return None


    # remove_active_event now needs guild_id and cleans up per-guild
    async def remove_active_event(self, guild_id: str, event_id: str, **kwargs: Any) -> Optional[str]: # Made async for cleanup calls
        """Удаляет активное событие и помечает для удаления в БД для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"EventManager: Removing event '{event_id}' from guild {guild_id_str}...")

        # ИСПРАВЛЕНИЕ: Получаем событие с учетом guild_id
        event = self.get_event(guild_id_str, event_id) # Type: Optional["Event"]

        if not event or str(getattr(event, 'guild_id', None)) != guild_id_str: # Check if event exists and belongs to this guild
            # Check if it's already marked for deletion for this guild
            if guild_id_str in self._deleted_event_ids and event_id in self._deleted_event_ids[guild_id_str]:
                 print(f"EventManager: Event {event_id} in guild {guild_id_str} was already marked for deletion.")
                 return event_id # Return ID if already marked

            print(f"EventManager: Event {event_id} not found or does not belong to guild {guild_id_str} for removal.")
            return None


        # Check if event is already inactive (already ended but not removed from cache/DB yet)
        # We still want to remove it, but skip cleanup if it's already handled by end_event.
        is_already_inactive = not getattr(event, 'is_active', True) # Use getattr safely

        # --- Perform Cleanup for entities/items spawned by the event ---
        # Use injected managers and pass context kwargs
        cleanup_context: Dict[str, Any] = {
             **kwargs, # Start with all incoming kwargs
             'event_id': event_id,
             'event': event, # Pass the event object
             'guild_id': guild_id_str, # Ensure guild_id_str is in context
             # Critical managers for cleanup (get from self or kwargs)
             'npc_manager': self._npc_manager or kwargs.get('npc_manager'),
             'item_manager': self._item_manager or kwargs.get('item_manager'),
             'combat_manager': self._combat_manager or kwargs.get('combat_manager'), # Combat might be linked to event
             'status_manager': self._status_manager or kwargs.get('status_manager'), # Statuses might be linked to event
             'party_manager': self._party_manager or kwargs.get('party_manager'), # Parties might be linked to event
             'location_manager': self._location_manager or kwargs.get('location_manager'), # Locations might be linked to event
             'rule_engine': self._rule_engine or kwargs.get('rule_engine'), # RuleEngine might have cleanup hooks
             # Add others...
        }

        # Perform cleanup ONLY if the event was active (cleanup is usually done by end_event)
        # If event is already inactive, cleanup should have been handled by end_event.
        if not is_already_inactive:
             print(f"EventManager: Cleaning up resources for event {event_id} in guild {guild_id_str}...")
             # Cleanup temporary NPC spawned by this event
             temp_npcs_ids = list(getattr(event.state_variables, '__temp_npcs', [])) # Use getattr safely
             npc_mgr = cleanup_context.get('npc_manager') # type: Optional["NpcManager"]
             if npc_mgr and hasattr(npc_mgr, 'remove_npc'): # Check manager and method
                 if temp_npcs_ids:
                      print(f"EventManager: Removing {len(temp_npcs_ids)} temporary NPCs for event {event_id}...")
                      for npc_id in temp_npcs_ids:
                           # remove_npc needs guild_id, npc_id, **kwargs
                           try: await npc_mgr.remove_npc(guild_id_str, str(npc_id), **cleanup_context) # Ensure string ID, pass context
                           except Exception: traceback.print_exc(); print(f"EventManager: Error removing temp NPC {npc_id} for event {event_id}.");

             # Cleanup temporary Items spawned by this event
             temp_items_ids = list(getattr(event.state_variables, '__temp_items', [])) # Use getattr safely
             item_mgr = cleanup_context.get('item_manager') # type: Optional["ItemManager"]
             if item_mgr and hasattr(item_mgr, 'mark_item_deleted'): # Check manager and method
                  if temp_items_ids:
                       print(f"EventManager: Marking {len(temp_items_ids)} temporary Items for deletion for event {event_id}...")
                       for item_id in temp_items_ids:
                            # mark_item_deleted needs guild_id, item_id
                            try: item_mgr.mark_item_deleted(guild_id_str, str(item_id)) # Ensure string ID
                            except Exception: traceback.print_exc(); print(f"EventManager: Error marking temp Item {item_id} for deletion for event {event_id}.");


             # TODO: Cleanup Combats linked to this event?
             # combat_mgr = cleanup_context.get('combat_manager') # type: Optional["CombatManager"]
             # if combat_mgr and hasattr(combat_mgr, 'get_combats_by_event_id') and hasattr(combat_mgr, 'end_combat'):
             #      combats_in_event = combat_mgr.get_combats_by_event_id(guild_id_str, event_id) # get_combats_by_event_id needs guild_id
             #      if combats_in_event:
             #           print(f"EventManager: Ending {len(combats_in_event)} combats linked to event {event_id}...")
             #           for combat in combats_in_event:
             #                combat_id = getattr(combat, 'id', None)
             #                if combat_id:
             #                     try: await combat_mgr.end_combat(combat_id, **cleanup_context) # end_combat needs combat_id, context
             #                     except Exception: traceback.print_exc(); print(f"EventManager: Error ending combat {combat_id} linked to event {event_id}.");

             # TODO: Trigger RuleEngine hook for event removal?
             # rule_engine = cleanup_context.get('rule_engine') # type: Optional["RuleEngine"]
             # if rule_engine and hasattr(rule_engine, 'on_event_removed'):
             #      try: await rule_engine.on_event_removed(event, context=cleanup_context)
             #      except Exception: traceback.print_exc();

             print(f"EventManager: Resource cleanup complete for event {event_id} in guild {guild_id_str}.")
        else:
             print(f"EventManager: Event {event_id} in guild {guild_id_str} was already inactive, skipping resource cleanup.")


        # --- Remove event from active cache and mark for deletion from DB ---
        # Use the correct per-guild active cache
        guild_events_cache = self._active_events.get(guild_id_str)
        if guild_events_cache:
             guild_events_cache.pop(event_id, None) # Remove from per-guild cache

        # Use the correct per-guild channel map cache
        guild_channel_map = self._active_events_by_channel.get(guild_id_str)
        if guild_channel_map:
             # Find the channel ID mapped to this event ID and remove it
             # This requires iterating through the map, or storing a reverse map {event_id: channel_id}
             # For now, iterate (less efficient but works with current structure)
             channel_id_to_remove = None
             for ch_id, ev_id in list(guild_channel_map.items()): # Iterate over a copy
                  if ev_id == event_id:
                       channel_id_to_remove = ch_id
                       break
             if channel_id_to_remove is not None:
                  guild_channel_map.pop(channel_id_to_remove, None)
                  print(f"EventManager: Removed channel mapping for event {event_id} (channel {channel_id_to_remove}) in guild {guild_id_str}.")
             # Note: If event object has channel_id attribute, we could also use that directly:
             # channel_id_from_obj = getattr(event, 'channel_id', None)
             # if channel_id_from_obj is not None: guild_channel_map.pop(int(channel_id_from_obj), None)


        # Remove from per-guild dirty set if it was there
        self._dirty_events.get(guild_id_str, set()).discard(event_id)

        # Mark for deletion from DB (per-guild)
        self._deleted_event_ids.setdefault(guild_id_str, set()).add(event_id)

        print(f"EventManager: Event '{event_id}' fully removed from cache and marked for deletion for guild {guild_id_str}.")
        return event_id # Return the ID of the removed event


    # TODO: Implement end_event method
    async def end_event(self, guild_id: str, event_id: str, **kwargs: Any) -> None:
        """Координирует завершение события для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"EventManager: Ending event {event_id} for guild {guild_id_str}...")

        # Get event with guild_id
        event = self.get_event(guild_id_str, event_id) # Type: Optional["Event"]

        if not event or str(getattr(event, 'guild_id', None)) != guild_id_str: # Check guild_id match
            print(f"EventManager: Warning: Attempted to end non-existent/mismatched-guild event {event_id} for guild {guild_id_str}.")
            return # Nothing to end

        # Check if event is already inactive/ending
        if not getattr(event, 'is_active', True):
             print(f"EventManager: Event {event_id} in guild {guild_id_str} is already inactive. Skipping end process.")
             return # Already inactive

        # --- 1. Mark event as inactive ---
        if hasattr(event, 'is_active'): event.is_active = False
        # Mark dirty for saving final state (is_active=False)
        self.mark_event_dirty(guild_id_str, event_id) # Use mark_event_dirty with guild_id

        # --- 2. Perform Cleanup of resources and entities tied to the event ---
        # This is the same cleanup logic as in remove_active_event for non-inactive events.
        # We can call remove_active_event, but need to prevent it from double-marking for deletion
        # Or, ideally, extract the cleanup logic into a separate internal method.
        # Let's extract the cleanup logic.
        await self._perform_event_cleanup_logic(event, **kwargs) # Pass event object and context

        # --- 3. Send event end message (optional) ---
        send_callback_factory = kwargs.get('send_callback_factory') # Get factory from context
        event_channel_id = getattr(event, 'channel_id', None) # Get channel_id from event object
        if send_callback_factory and event_channel_id is not None:
             send_callback = send_callback_factory(int(event_channel_id)) # Ensure channel_id is int
             end_message_template = getattr(event, 'end_message_template', 'Событие завершилось.') # Get template from event object
             # TODO: Format message (e.g., winner/loser)
             end_message_content = end_message_template # Simple message for now
             try:
                  await send_callback(end_message_content) # Send the message
                  print(f"EventManager: Sent event end message for {event_id} to channel {event_channel_id} in guild {guild_id_str}.")
             except Exception as e:
                  print(f"EventManager: Error sending event end message for {event_id} to channel {event_channel_id} in guild {guild_id_str}: {e}")
                  traceback.print_exc()

        # --- 4. Event is marked inactive and resources cleaned up. It will be saved by PM. ---
        # We don't remove it from the active cache here if we want to save its final state.
        # It will remain in _active_events[guild_id_str] with is_active=False and will be saved.
        # It will only be *removed* from the active cache when remove_active_event is called,
        # which also marks it for deletion from DB. So end_event just makes it inactive and saves.
        # If ended events should NOT stay in the active cache, then call remove_active_event here.
        # Let's assume ended events *are* removed from the active cache and marked for DB deletion.
        # This means end_event should call remove_active_event.
        print(f"EventManager: Event {event_id} in guild {guild_id_str} state set to inactive. Calling remove_active_event...")
        await self.remove_active_event(guild_id_str, event_id, **kwargs) # remove_active_event marks for deletion and removes from cache


        print(f"EventManager: Event {event_id} fully ended for guild {guild_id_str}.")


    # Internal helper for cleanup logic
    async def _perform_event_cleanup_logic(self, event: "Event", **kwargs: Any) -> None:
        """Internal helper to perform cleanup of resources tied to an event."""
        guild_id = getattr(event, 'guild_id', None) # Get guild_id from event object
        event_id = getattr(event, 'id', None)
        if not guild_id or not event_id:
            print(f"EventManager: Warning: _perform_event_cleanup_logic called with event missing guild_id or id: {event}. Cannot perform cleanup.")
            return
        guild_id_str = str(guild_id)

        cleanup_context: Dict[str, Any] = {
             **kwargs, # Start with all incoming kwargs
             'event_id': event_id,
             'event': event, # Pass the event object
             'guild_id': guild_id_str, # Ensure guild_id_str is in context
             # Critical managers for cleanup (get from self or kwargs)
             'npc_manager': self._npc_manager or kwargs.get('npc_manager'),
             'item_manager': self._item_manager or kwargs.get('item_manager'),
             'combat_manager': self._combat_manager or kwargs.get('combat_manager'),
             'status_manager': self._status_manager or kwargs.get('status_manager'),
             'party_manager': self._party_manager or kwargs.get('party_manager'),
             'location_manager': self._location_manager or kwargs.get('location_manager'),
             'rule_engine': self._rule_engine or kwargs.get('rule_engine'),
             # Add others...
        }

        print(f"EventManager: Performing resource cleanup for event {event_id} in guild {guild_id_str}...")

        # Cleanup temporary NPC spawned by this event
        # Assume temporary NPC IDs are stored in event.state_variables['__temp_npcs']
        temp_npcs_ids = list(getattr(event.state_variables, '__temp_npcs', [])) # Use getattr safely
        npc_mgr = cleanup_context.get('npc_manager') # type: Optional["NpcManager"]
        if npc_mgr and hasattr(npc_mgr, 'remove_npc'): # Check manager and method
            if temp_npcs_ids:
                 print(f"EventManager: Removing {len(temp_npcs_ids)} temporary NPCs for event {event_id}...")
                 for npc_id in temp_npcs_ids:
                      # remove_npc needs guild_id, npc_id, **kwargs
                      try: await npc_mgr.remove_npc(guild_id_str, str(npc_id), **cleanup_context) # Ensure string ID, pass context
                      except Exception: traceback.print_exc(); print(f"EventManager: Error removing temp NPC {npc_id} for event {event_id}.");

        # Cleanup temporary Items spawned by this event
        # Assume temporary Item IDs are stored in event.state_variables['__temp_items']
        temp_items_ids = list(getattr(event.state_variables, '__temp_items', [])) # Use getattr safely
        item_mgr = cleanup_context.get('item_manager') # type: Optional["ItemManager"]
        # Items are usually marked for deletion by their owner's cleanup (e.g. NPC removal).
        # But if items were spawned "on the ground" or owned by the event itself,
        # EventManager cleanup should handle them.
        # Let's assume items owned by 'Event' type are cleaned up here.
        if item_mgr and hasattr(item_mgr, 'remove_items_by_owner'): # Assuming ItemManager has a method to remove items by owner
            # remove_items_by_owner needs owner_id, owner_type, guild_id, **context
            try: await item_mgr.remove_items_by_owner(event_id, 'Event', guild_id_str, **cleanup_context)
            except Exception: traceback.print_exc(); print(f"EventManager: Error removing items owned by event {event_id}.");

        # Temporary items (marked by is_temporary=True during creation) might need specific handling
        # If the item was marked temporary *regardless* of owner, the item manager's save_state should delete them.
        # If temporary items are only temporary *while* owned by the event, then they need cleanup here.
        # Let's stick to cleaning up items explicitly owned by the 'Event' type owner.
        # The __temp_items list might contain IDs of items that were NOT owned by the event (e.g., given to players)
        # Cleaning up by owner 'Event' is safer.

        # TODO: Cleanup Combats linked to this event?
        combat_mgr = cleanup_context.get('combat_manager') # type: Optional["CombatManager"]
        if combat_mgr and hasattr(combat_mgr, 'get_combats_by_event_id') and hasattr(combat_mgr, 'end_combat'):
             combats_in_event = combat_mgr.get_combats_by_event_id(guild_id_str, event_id) # get_combats_by_event_id needs guild_id
             if combats_in_event:
                  print(f"EventManager: Ending {len(combats_in_event)} combats linked to event {event_id}...")
                  for combat in combats_in_event:
                       combat_id = getattr(combat, 'id', None)
                       if combat_id:
                            try: await combat_mgr.end_combat(combat_id, **cleanup_context) # end_combat needs combat_id, context
                            except Exception: traceback.print_exc(); print(f"EventManager: Error ending combat {combat_id} linked to event {event_id}.");

        # TODO: Trigger RuleEngine hook for event removal?
        rule_engine = cleanup_context.get('rule_engine') # type: Optional["RuleEngine"]
        if rule_engine and hasattr(rule_engine, 'on_event_removed'): # Assuming RuleEngine method
             try: await rule_engine.on_event_removed(event, context=cleanup_context)
             except Exception: traceback.print_exc();

        print(f"EventManager: Resource cleanup logic complete for event {event_id} in guild {guild_id_str}.")


    # load_state - loads per-guild
    # required_args_for_load = ["guild_id"]

    async def generate_event_details_from_ai(self, guild_id: str, event_concept: str, related_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Uses AI to generate details for a game event.

        Args:
            guild_id: The ID of the guild.
            event_concept: A string describing the event idea or trigger.
            related_context: Optional dictionary providing specific context for the event
                             (e.g., involved NPCs, location, player actions).

        Returns:
            A dictionary containing the structured, multilingual event data from the AI,
            or None if generation fails.
        """
        if not self._multilingual_prompt_generator:
            print("EventManager ERROR: MultilingualPromptGenerator is not available.")
            return None
        if not self._openai_service:
            print("EventManager ERROR: OpenAIService is not available.")
            return None
        if not self._settings: # Settings might be needed for AI parameters
            print("EventManager ERROR: Settings are not available.")
            return None

        print(f"EventManager: Generating AI details for event concept '{event_concept}' in guild {guild_id}.")

        # Gather full context. The MultilingualPromptGenerator's methods typically handle this.
        # A generic prompt type or a new specific one for events might be needed in the generator.
        # For now, construct a task prompt and use the generator's _build_full_prompt_for_openai.

        context_data = self._multilingual_prompt_generator.context_collector.get_full_context(
            guild_id=guild_id
            # Pass specific entity IDs from related_context if get_full_context can use them
        )
        # Augment general context with specific event_related_context if provided
        if related_context:
            context_data["event_specific_inputs"] = related_context

        # Define the task for the AI
        specific_task_prompt = f"""
        Design details for a game event based on the following concept and context.
        Event Concept: {event_concept}
        Additional Event Context: {json.dumps(related_context) if related_context else "None provided."}

        The event details should include:
        - event_id (suggest a unique slug-like ID if this is a template, or state if it's an instance)
        - title_i18n (multilingual, compelling title for the event)
        - description_i18n (multilingual, detailed description of what is happening)
        - type (e.g., "dynamic_encounter", "environmental_hazard", "social_interaction", "mini_quest_trigger")
        - duration_description_i18n (multilingual, e.g., "lasts for a few hours", "ongoing until resolved")
        - stages_i18n (optional, if a multi-stage event, an array of stage descriptions, multilingual)
        - involved_entities_i18n (optional, descriptions of how specific NPCs, factions, or locations are involved, multilingual)
        - potential_outcomes_i18n (multilingual, brief on possible results or player impacts)
        - player_interaction_hooks_i18n (multilingual, how players can interact or what choices they might have)

        Ensure all textual fields are in the specified multilingual JSON format ({{"en": "...", "ru": "..."}}).
        Incorporate elements from the broader lore and world state context provided.
        """

        prompt_messages = self._multilingual_prompt_generator._build_full_prompt_for_openai(
            specific_task_prompt=specific_task_prompt,
            context_data=context_data
        )

        system_prompt = prompt_messages["system"]
        user_prompt = prompt_messages["user"]

        ai_settings = self._settings.get("event_generation_ai_settings", {})
        max_tokens = ai_settings.get("max_tokens", 1800)
        temperature = ai_settings.get("temperature", 0.7)

        generated_data = await self._openai_service.generate_structured_multilingual_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )

        if generated_data and "error" not in generated_data:
            print(f"EventManager: Successfully generated AI details for event '{event_concept}'.")
            # Further validation of event structure might be needed here.
            return generated_data
        else:
            error_detail = generated_data.get("error") if generated_data else "Unknown error"
            raw_text = generated_data.get("raw_text", "") if generated_data else ""
            print(f"EventManager ERROR: Failed to generate AI details for event '{event_concept}'. Error: {error_detail}")
            if raw_text:
                print(f"EventManager: Raw response from AI was: {raw_text[:500]}...")
            return None

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает активные события и шаблоны для определенной гильдии из базы данных/настроек в кеш."""
        guild_id_str = str(guild_id)
        print(f"EventManager: Loading state for guild {guild_id_str} (events + templates)...")

        if self._db_service is None or self._db_service.adapter is None: # Changed
            print(f"EventManager: Warning: No DB service or adapter. Skipping event/template load for guild {guild_id_str}. It will work with empty caches.")
            # TODO: In non-DB mode, load placeholder data
            return

        # --- 1. Загрузка статических шаблонов (per-guild) ---
        # Call the helper method
        self.load_static_templates(guild_id_str)


        # --- 2. Загрузка активных событий (per-guild) ---
        # Очищаем кеши событий ТОЛЬКО для этой гильдии перед загрузкой
        self._active_events.pop(guild_id_str, None) # Remove old active events cache for this guild
        self._active_events[guild_id_str] = {} # Create an empty cache for this guild

        self._active_events_by_channel.pop(guild_id_str, None) # Remove old channel map cache
        self._active_events_by_channel[guild_id_str] = {} # Create an empty channel map cache

        # При загрузке, считаем, что все в DB "чистое", поэтому очищаем dirty/deleted для этой гильдии
        self._dirty_events.pop(guild_id_str, None)
        self._deleted_event_ids.pop(guild_id_str, None)

        rows = []
        try:
            # Execute SQL SELECT FROM events WHERE guild_id = ? AND is_active = 1
            sql = '''
            SELECT id, template_id, name_i18n, is_active, channel_id,
                   current_stage_id, players, state_variables,
                   stages_data, end_message_template_i18n, guild_id
            FROM events WHERE guild_id = $1 AND is_active = TRUE
            ''' # Changed placeholder and is_active condition
            rows = await self._db_service.adapter.fetchall(sql, (guild_id_str,)) # Changed to db_service
            print(f"EventManager: Found {len(rows)} active events in DB for guild {guild_id_str}.")

        except Exception as e:
            print(f"EventManager: ❌ CRITICAL ERROR executing DB fetchall for events for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Clear event caches for this guild on critical error
            self._active_events.pop(guild_id_str, None)
            self._active_events_by_channel.pop(guild_id_str, None)
            raise # Re-raise critical error


        loaded_count = 0
        # Get the cache dicts for this specific guild
        guild_events_cache = self._active_events[guild_id_str]
        guild_channel_map_cache = self._active_events_by_channel[guild_id_str]


        for row in rows:
             data = dict(row)
             try:
                 # Validate and parse data
                 event_id_raw = data.get('id')
                 loaded_guild_id_raw = data.get('guild_id') # Should match guild_id_str due to WHERE clause

                 if event_id_raw is None or loaded_guild_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                     # This check is mostly redundant due to WHERE clause but safe.
                     print(f"EventManager: Warning: Skipping event row with invalid ID ('{event_id_raw}') or mismatched guild ('{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row}.")
                     continue

                 event_id = str(event_id_raw)


                 # Parse JSON fields, handle None/malformed data gracefully
                 try:
                     data['players'] = json.loads(data.get('players') or '[]') if isinstance(data.get('players'), (str, bytes)) else []
                 except (json.JSONDecodeError, TypeError):
                      print(f"EventManager: Warning: Failed to parse players for event {event_id} in guild {guild_id_str}. Setting to []. Data: {data.get('players')}")
                      data['players'] = []
                 else: # Ensure player IDs are strings
                      data['players'] = [str(p) for p in data['players'] if p is not None]

                 try:
                     data['state_variables'] = json.loads(data.get('state_variables') or '{}') if isinstance(data.get('state_variables'), (str, bytes)) else {}
                 except (json.JSONDecodeError, TypeError):
                      print(f"EventManager: Warning: Failed to parse state_variables for event {event_id} in guild {guild_id_str}. Setting to {{}}. Data: {data.get('state_variables')}")
                      data['state_variables'] = {}

                 try:
                     data['stages_data'] = json.loads(data.get('stages_data') or '{}') if isinstance(data.get('stages_data'), (str, bytes)) else {}
                 except (json.JSONDecodeError, TypeError):
                      print(f"EventManager: Warning: Failed to parse stages_data for event {event_id} in guild {guild_id_str}. Setting to {{}}. Data: {data.get('stages_data')}")
                      data['stages_data'] = {}

                 # Convert boolean/numeric/string types, handle potential None/malformed data
                 data['is_active'] = bool(data.get('is_active', 0)) if data.get('is_active') is not None else True # Default True if None/missing
                 data['channel_id'] = int(data.get('channel_id')) if data.get('channel_id') is not None else None # Store channel_id as int or None
                 data['template_id'] = str(data.get('template_id')) if data.get('template_id') is not None else None

                 # --- NAME_I18N HANDLING START ---
                 name_i18n_json = data.get('name_i18n')
                 name_i18n_dict = {}
                 if isinstance(name_i18n_json, str):
                     try:
                         name_i18n_dict = json.loads(name_i18n_json or '{}')
                     except json.JSONDecodeError:
                         print(f"EventManager: Warning: Failed to parse name_i18n for event {event_id}. Data: {name_i18n_json}")
                 elif isinstance(name_i18n_json, dict):
                     name_i18n_dict = name_i18n_json

                 data['name_i18n'] = name_i18n_dict

                 default_lang_for_name = 'en'
                 plain_name = name_i18n_dict.get(default_lang_for_name)
                 if not plain_name and name_i18n_dict:
                     plain_name = next(iter(name_i18n_dict.values()), None)
                 if not plain_name:
                     plain_name = f"Event {event_id[:8]}"
                 data['name'] = str(plain_name)
                 # --- NAME_I18N HANDLING END ---

                 data['current_stage_id'] = str(data.get('current_stage_id')) if data.get('current_stage_id') is not None else 'start' # Ensure string stage ID

                 # --- END_MESSAGE_TEMPLATE_I18N HANDLING START ---
                 end_message_i18n_json = data.get('end_message_template_i18n')
                 end_message_i18n_dict = {}
                 if isinstance(end_message_i18n_json, str):
                     try:
                         end_message_i18n_dict = json.loads(end_message_i18n_json or '{}')
                     except json.JSONDecodeError:
                         print(f"EventManager: Warning: Failed to parse end_message_template_i18n for event {event_id}. Data: {end_message_i18n_json}")
                 elif isinstance(end_message_i18n_json, dict):
                     end_message_i18n_dict = end_message_i18n_json

                 data['end_message_template_i18n'] = end_message_i18n_dict

                 plain_end_message = end_message_i18n_dict.get(default_lang_for_name) # Using same default_lang
                 if not plain_end_message and end_message_i18n_dict:
                     plain_end_message = next(iter(end_message_i18n_dict.values()), None)
                 if not plain_end_message:
                     plain_end_message = "Событие завершилось." # Default fallback
                 data['end_message_template'] = str(plain_end_message)
                 # --- END_MESSAGE_TEMPLATE_I18N HANDLING END ---

                 # Update data dict with validated/converted values
                 data['id'] = event_id
                 data['guild_id'] = guild_id_str # Ensure guild_id is string


                 # Create Event object
                 event = Event.from_dict(data) # Requires Event.from_dict method


                 # Add Event object to the per-guild cache of active events
                 if event.is_active: # Only add if truly active
                     guild_events_cache[event.id] = event
                     # Add to the per-guild channel map cache
                     if event.channel_id is not None:
                          # TODO: Handle conflict if multiple active events map to the same channel in this guild?
                          # Current logic overwrites.
                          if event.channel_id in guild_channel_map_cache:
                               print(f"EventManager: Warning: Loading event {event.id} maps to channel {event.channel_id} which is already mapped to event {guild_channel_map_cache[event.channel_id]} in guild {guild_id_str}. Overwriting.")
                          guild_channel_map_cache[event.channel_id] = event.id

                     loaded_count += 1
                 else:
                      # Log or handle inactive events found in query if necessary.
                      # The SQL WHERE clause "AND is_active = 1" should prevent loading inactive events anyway.
                      # If an inactive event is loaded, it indicates a schema/query issue.
                      print(f"EventManager: Warning: Loaded inactive event {event.id} for guild {guild_id_str}. SQL query might be incorrect.")


             except Exception as e:
                 print(f"EventManager: Error loading event {data.get('id', 'N/A')} for guild {guild_id_str}: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # Continue loop for other rows


        print(f"EventManager: Successfully loaded {loaded_count} active events into cache for guild {guild_id_str}.")
        print(f"EventManager: Load state complete for guild {guild_id_str}.")


    # save_state - saves per-guild
    # required_args_for_save = ["guild_id"]
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет активные/измененные события для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"EventManager: Saving events for guild {guild_id_str}...")

        if self._db_service is None or self._db_service.adapter is None: # Changed
            print(f"EventManager: Warning: Cannot save events for guild {guild_id_str}, DB service or adapter missing.")
            return

        # ИСПРАВЛЕНИЕ: Соберите dirty/deleted ID ИЗ per-guild кешей
        # Get copies for safety
        dirty_event_ids_set = self._dirty_events.get(guild_id_str, set()).copy()
        deleted_event_ids_set = self._deleted_event_ids.get(guild_id_str, set()).copy()

        # Filter active events by guild_id AND dirty status
        guild_events_cache = self._active_events.get(guild_id_str, {})
        events_to_save: List["Event"] = [
             event for event_id, event in guild_events_cache.items()
             if event_id in dirty_event_ids_set # Only save if marked dirty
             and getattr(event, 'guild_id', None) == guild_id_str # Double check guild_id
             # Note: This saves active events marked dirty. If an ended event (is_active=False)
             # needs saving for history, it must still be in _active_events AND be marked dirty.
             # If events are removed from _active_events upon ending (in end_event calling remove_active_event),
             # then ended events are ONLY handled by the delete logic below.
             # The current logic of remove_active_event removing from _active_events means only
             # events that are STILL ACTIVE but marked dirty will be saved/upserted here.
             # Events that END and are marked for deletion will be handled by the DELETE block.
        ]

        if not events_to_save and not deleted_event_ids_set:
            # print(f"EventManager: No dirty or deleted events to save for guild {guild_id_str}.") # Too noisy
            # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, очищаем per-guild dirty/deleted сеты
            self._dirty_events.pop(guild_id_str, None)
            self._deleted_event_ids.pop(guild_id_str, None)
            return

        print(f"EventManager: Saving {len(events_to_save)} dirty active, deleting {len(deleted_event_ids_set)} events for guild {guild_id_str}...")


        try:
            # 1. Удаляем помеченные для удаления события для этой гильдии
            if deleted_event_ids_set:
                ids_to_delete = list(deleted_event_ids_set)
                if ids_to_delete: # Ensure list is not empty
                    placeholders_del = ','.join([f'${i+2}' for i in range(len(ids_to_delete))]) # $2, $3, ...
                    # Ensure deleting only for this guild and these IDs
                    sql_delete_batch = f"DELETE FROM events WHERE guild_id = $1 AND id IN ({placeholders_del})" # Changed placeholders
                    try:
                         await self._db_service.adapter.execute(sql_delete_batch, (guild_id_str, *tuple(ids_to_delete))); # Changed
                         print(f"EventManager: Deleted {len(ids_to_delete)} events from DB for guild {guild_id_str}.")
                         # ИСПРАВЛЕНИЕ: Очищаем per-guild deleted set after successful deletion
                         self._deleted_event_ids.pop(guild_id_str, None)
                    except Exception as e:
                        print(f"EventManager: Error deleting events for guild {guild_id_str}: {e}"); traceback.print_exc();
                        # Do NOT clear deleted set on error
            else: # If the set was empty for this guild
                self._deleted_event_ids.pop(guild_id_str, None)


            # 2. Сохраняем/обновляем измененные события для этого guild_id
            if events_to_save:
                 print(f"EventManager: Upserting {len(events_to_save)} active events for guild {guild_id_str}...")
                 # Use correct column names based on schema (added guild_id)
                 upsert_sql = '''
                 INSERT INTO events
                 (id, template_id, name_i18n, is_active, channel_id,
                  current_stage_id, players, state_variables,
                  stages_data, end_message_template_i18n, guild_id)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                 ON CONFLICT (id) DO UPDATE SET
                    template_id = EXCLUDED.template_id,
                    name_i18n = EXCLUDED.name_i18n,
                    is_active = EXCLUDED.is_active,
                    channel_id = EXCLUDED.channel_id,
                    current_stage_id = EXCLUDED.current_stage_id,
                    players = EXCLUDED.players,
                    state_variables = EXCLUDED.state_variables,
                    stages_data = EXCLUDED.stages_data,
                    end_message_template_i18n = EXCLUDED.end_message_template_i18n,
                    guild_id = EXCLUDED.guild_id
                 ''' # PostgreSQL UPSERT
                 data_to_upsert = []
                 upserted_event_ids: Set[str] = set() # Track IDs successfully prepared
            else: # If the set was empty for this guild
                self._deleted_event_ids.pop(guild_id_str, None)


            # 2. Сохраняем/обновляем измененные события для этого guild_id
            if events_to_save:
                 print(f"EventManager: Upserting {len(events_to_save)} active events for guild {guild_id_str}...")
                 # Use correct column names based on schema (added guild_id)
                 upsert_sql = '''
                 INSERT INTO events
                 (id, template_id, name_i18n, is_active, channel_id,
                  current_stage_id, players, state_variables,
                  stages_data, end_message_template_i18n, guild_id)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                 ON CONFLICT (id) DO UPDATE SET
                    template_id = EXCLUDED.template_id,
                    name_i18n = EXCLUDED.name_i18n,
                    is_active = EXCLUDED.is_active,
                    channel_id = EXCLUDED.channel_id,
                    current_stage_id = EXCLUDED.current_stage_id,
                    players = EXCLUDED.players,
                    state_variables = EXCLUDED.state_variables,
                    stages_data = EXCLUDED.stages_data,
                    end_message_template_i18n = EXCLUDED.end_message_template_i18n,
                    guild_id = EXCLUDED.guild_id
                 ''' # PostgreSQL UPSERT
                 data_to_upsert = []
                 upserted_event_ids: Set[str] = set() # Track IDs successfully prepared

                 for ev in events_to_save:
                      try:
                           # Ensure event object has all required attributes
                           event_id = getattr(ev, 'id', None)
                           event_guild_id = getattr(ev, 'guild_id', None)

                           # Double check required fields and guild ID match
                           if event_id is None or str(event_guild_id) != guild_id_str:
                               print(f"EventManager: Warning: Skipping upsert for event with invalid ID ('{event_id}') or mismatched guild ('{event_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                               continue

                           template_id = getattr(ev, 'template_id', None)
                           name_i18n = getattr(ev, 'name_i18n', {}) # Expect dict
                           is_active = getattr(ev, 'is_active', True)
                           channel_id = getattr(ev, 'channel_id', None)
                           current_stage_id = getattr(ev, 'current_stage_id', 'start')
                           players = getattr(ev, 'players', [])
                           state_variables = getattr(ev, 'state_variables', {})
                           stages_data = getattr(ev, 'stages_data', {})
                           end_message_template_i18n = getattr(ev, 'end_message_template_i18n', {}) # Expect dict

                           # Ensure data types are suitable for JSON dumping / DB columns
                           if not isinstance(name_i18n, dict): name_i18n = {}
                           if not isinstance(players, list): players = []
                           if not isinstance(state_variables, dict): state_variables = {}
                           if not isinstance(stages_data, dict): stages_data = {}
                           if not isinstance(end_message_template_i18n, dict): end_message_template_i18n = {}

                           name_i18n_json = json.dumps(name_i18n)
                           players_json = json.dumps(players)
                           state_variables_json = json.dumps(state_variables)
                           stages_data_json = json.dumps(stages_data)
                           end_message_template_i18n_json = json.dumps(end_message_template_i18n)

                           data_to_upsert.append((
                               str(event_id),
                               str(template_id) if template_id is not None else None, # Ensure str or None
                               name_i18n_json, # Pass JSON string
                               is_active, # Pass boolean directly
                               int(channel_id) if channel_id is not None else None, # Ensure int or None
                               str(current_stage_id), # Ensure string
                               players_json,
                               state_variables_json,
                               stages_data_json,
                               end_message_template_i18n_json, # Pass JSON string
                               guild_id_str, # Ensure guild_id string
                           ))
                           upserted_event_ids.add(str(event_id)) # Track ID

                      except Exception as e:
                           print(f"EventManager: Error preparing data for event {getattr(ev, 'id', 'N/A')} ('{getattr(ev, 'name_i18n', {}).get('en', 'N/A')}', guild {getattr(ev, 'guild_id', 'N/A')}) for upsert: {e}")
                           import traceback
                           print(traceback.format_exc())
                           # This event won't be saved but remains in _dirty_events

                 if data_to_upsert:
                      if self._db_service is None or self._db_service.adapter is None: # Changed
                           print(f"EventManager: Warning: DB service or adapter is None during event upsert batch for guild {guild_id_str}.")
                      else:
                           await self._db_service.adapter.execute_many(upsert_sql, data_to_upsert) # Changed
                           print(f"EventManager: Successfully upserted {len(data_to_upsert)} active events for guild {guild_id_str}.")
                           # Only clear dirty flags for events that were successfully processed
                           if guild_id_str in self._dirty_events:
                                self._dirty_events[guild_id_str].difference_update(upserted_event_ids)
                                # If set is empty after update, remove the guild key
                                if not self._dirty_events[guild_id_str]:
                                     del self._dirty_events[guild_id_str]

                 # Note: Ended events (is_active=False) that were removed from _active_events
                 # (by end_event calling remove_active_event) are NOT saved by this upsert block.
                 # They are handled by the DELETE block.

        except Exception as e:
            print(f"EventManager: ❌ Error during saving state for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Do NOT clear dirty/deleted sets on error to allow retry.
            # raise # Re-raise if critical

        print(f"EventManager: Save state complete for guild {guild_id_str}.")


    # rebuild_runtime_caches - rebuilds per-guild caches after loading
    # required_args_for_rebuild = ["guild_id"]
    # Already takes guild_id and **kwargs
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"EventManager: Rebuilding runtime caches for guild {guild_id_str}...")

        # Get all active events loaded for this guild
        # Use the per-guild cache
        guild_events = self._active_events.get(guild_id_str, {}).values()

        # Rebuild the per-guild channel map cache
        # Use the correct per-guild cache
        guild_channel_map = self._active_events_by_channel.setdefault(guild_id_str, {})
        guild_channel_map.clear() # Clear old map for this guild

        for ev in guild_events: # Iterate through events loaded for THIS guild
             event_id = getattr(ev, 'id', None)
             channel_id = getattr(ev, 'channel_id', None)

             if event_id and channel_id is not None:
                  try:
                       channel_id_int = int(channel_id)
                       # TODO: Check conflicts - multiple active events mapping to the same channel?
                       # Current logic overwrites.
                       if channel_id_int in guild_channel_map:
                            print(f"EventManager: Warning: Rebuilding channel map for guild {guild_id_str}. Channel {channel_id_int} mapped to multiple events: already {guild_channel_map[channel_id_int]}, now {event_id}. Keeping {event_id}.")
                       guild_channel_map[channel_id_int] = event_id
                  except (ValueError, TypeError):
                       print(f"EventManager: Warning: Invalid channel_id '{channel_id}' for event {event_id} in guild {guild_id_str} during rebuild. Skipping channel mapping.")

        # TODO: Other runtime caches based on events? (e.g., location -> event map)


        print(f"EventManager: Rebuild runtime caches complete for guild {guild_id_str}. Channel map size: {len(guild_channel_map)}")


    # mark_event_dirty needs guild_id
    # Needs _dirty_events Set (per-guild)
    def mark_event_dirty(self, guild_id: str, event_id: str) -> None:
        """Помечает событие как измененное для последующего сохранения для определенной гильдии."""
        guild_id_str = str(guild_id)
        event_id_str = str(event_id)
        # Add check that the event ID exists in the per-guild active cache
        guild_events_cache = self._active_events.get(guild_id_str)
        if guild_events_cache and event_id_str in guild_events_cache:
             # Add to the per-guild dirty set
             self._dirty_events.setdefault(guild_id_str, set()).add(event_id_str)
        # else: print(f"EventManager: Warning: Attempted to mark non-existent event {event_id_str} in guild {guild_id_str} as dirty.") # Too noisy?


    # mark_event_deleted needs guild_id
    # Needs _deleted_event_ids Set (per-guild)
    # Called by remove_active_event
    def mark_event_deleted(self, guild_id: str, event_id: str) -> None:
        """Помечает событие как удаленное для определенной гильдии."""
        guild_id_str = str(guild_id)
        event_id_str = str(event_id)

        # Check if event exists in the per-guild active cache (optional, remove_active_event handles this)
        # guild_events_cache = self._active_events.get(guild_id_str)
        # if guild_events_cache and event_id_str in guild_events_cache:
             # remove_active_event already removes from cache

        # Add to per-guild deleted set
        self._deleted_event_ids.setdefault(guild_id_str, set()).add(event_id_str) # uses set()

        # Remove from per-guild dirty set if it was there
        self._dirty_events.get(guild_id_str, set()).discard(event_id_str) # uses set()

        print(f"EventManager: Event {event_id_str} marked for deletion for guild {guild_id_str}.")

        # Handle case where event was already marked for deletion
        # elif guild_id_str in self._deleted_event_ids and event_id_str in self._deleted_event_ids[guild_id_str]:
        #      print(f"EventManager: Event {event_id_str} in guild {guild_id_str} already marked for deletion.")
        # else:
        #      print(f"EventManager: Warning: Attempted to mark non-existent event {event_id_str} in guild {guild_id_str} as deleted.")


    # TODO: Implement clean_up_for_entity(entity_id, entity_type, context) if entities can be linked to events
    # Called by CharacterManager.remove_character, NpcManager.remove_npc etc.
    # This method would check if the entity is a 'player' in any event and remove them.
    # async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None: ...


    # TODO: Implement clean_up_for_location(location_id, guild_id, **context) if events are tied to locations
    # Called by LocationManager.delete_location_instance
    # This method would check if any events are happening in/tied to this location instance and potentially end them.
    # async def clean_up_for_location(self, location_id: str, guild_id: str, **kwargs: Any) -> None: ...


    # TODO: Implement clean_up_for_combat(combat_id, guild_id, **context) if events are tied to specific combats
    # Called by CombatManager.end_combat
    # This method would check if the combat is linked to an event (combat.event_id) and potentially trigger event state changes.
    # async def clean_up_for_combat(self, combat_id: str, guild_id: str, **kwargs: Any) -> None: ...


    # TODO: Implement clean_up_for_party(party_id, guild_id, **context) if events are tied to parties
    # Called by PartyManager.remove_party
    # This method would check if any events are tied to this party and potentially end them.
    # async def clean_up_for_party(self, party_id: str, guild_id: str, **kwargs: Any) -> None: ...


    # TODO: Implement process_tick(guild_id, game_time_delta, **kwargs)
    # Called by WorldSimulationProcessor
    # This method would iterate through active events for the guild and call event_stage_processor.process_tick_event
    # async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None: ...

    async def save_event(self, event: "Event", guild_id: str) -> bool:
        """
        Saves a single event entity to the database using an UPSERT operation.
        """
        if self._db_service is None or self._db_service.adapter is None: # Changed
            print(f"EventManager: Error: DB service or adapter missing for guild {guild_id}. Cannot save event {getattr(event, 'id', 'N/A')}.")
            return False

        guild_id_str = str(guild_id)
        event_id = getattr(event, 'id', None)
        if not event_id:
            print(f"EventManager: Error: Event object is missing an 'id'. Cannot save.")
            return False

        # Ensure the event's internal guild_id matches the provided guild_id parameter
        # event.guild_id is now mandatory in the Event model
        if not hasattr(event, 'guild_id') or event.guild_id is None:
            # This case should ideally not happen if Event object is correctly initialized
            print(f"EventManager: CRITICAL Error: Event object {event_id} is missing 'guild_id' attribute during save for guild context {guild_id_str}.")
            return False # Cannot proceed without event's own guild_id for verification

        if event.guild_id != guild_id_str:
            print(f"EventManager: Error: Event {event_id} actual guild_id ({event.guild_id}) does not match provided saving context guild_id ({guild_id_str}). Aborting save.")
            return False

        try:
            event_data = event.to_dict()

            # Prepare data for DB columns based on 'events' table schema used in save_state
            # id, template_id, name_i18n, is_active, channel_id, current_stage_id,
            # players, state_variables, stages_data, end_message_template_i18n, guild_id

            db_id = event_data.get('id')
            db_template_id = event_data.get('template_id')
            db_name_i18n = event_data.get('name_i18n', {"en": "Unnamed Event"}) # Expect dict
            if not isinstance(db_name_i18n, dict): db_name_i18n = {}


            db_is_active = getattr(event, 'is_active', True)
            db_channel_id = event_data.get('channel_id')
            db_current_stage_id = event_data.get('current_stage_id', 'start')

            involved_entities = event_data.get('involved_entities', {})
            db_players_list = involved_entities.get('players', [])
            if not isinstance(db_players_list, list): db_players_list = []

            db_stages_data = event_data.get('stages_data', {})
            db_end_message_template_i18n = event_data.get('end_message_template_i18n', {}) # Expect dict
            if not isinstance(db_end_message_template_i18n, dict): db_end_message_template_i18n = {}


            # Collect remaining fields from event_data into state_variables, merging with explicit state_variables
            managed_fields = {
                'id', '_id', 'template_id', 'name_i18n', 'is_active', 'channel_id',
                'current_stage_id', 'players', 'stages_data', 'end_message_template_i18n',
                'guild_id', 'involved_entities', 'name', 'end_message_template' # legacy fields
            }
            current_state_vars = event_data.get('state_variables', {})
            if not isinstance(current_state_vars, dict): current_state_vars = {}

            additional_state_data = {
                k: v for k, v in event_data.items() if k not in managed_fields and k != 'state_variables'
            }
            final_state_vars = {**current_state_vars, **additional_state_data}
            if 'location_id' in event_data and 'location_id' not in managed_fields:
                final_state_vars['location_id'] = event_data['location_id']

            db_params = (
                db_id,
                db_template_id,
                json.dumps(db_name_i18n),
                db_is_active,
                db_channel_id,
                db_current_stage_id,
                json.dumps(db_players_list),
                json.dumps(final_state_vars),
                json.dumps(db_stages_data),
                json.dumps(db_end_message_template_i18n),
                guild_id_str
            )

            upsert_sql = '''
            INSERT INTO events (
                id, template_id, name_i18n, is_active, channel_id,
                current_stage_id, players, state_variables, stages_data,
                end_message_template_i18n, guild_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (id) DO UPDATE SET
                template_id = EXCLUDED.template_id,
                name_i18n = EXCLUDED.name_i18n,
                is_active = EXCLUDED.is_active,
                channel_id = EXCLUDED.channel_id,
                current_stage_id = EXCLUDED.current_stage_id,
                players = EXCLUDED.players,
                state_variables = EXCLUDED.state_variables,
                stages_data = EXCLUDED.stages_data,
                end_message_template_i18n = EXCLUDED.end_message_template_i18n,
                guild_id = EXCLUDED.guild_id
            ''' # PostgreSQL UPSERT
            # 11 columns, 11 placeholders.

            await self._db_service.adapter.execute(upsert_sql, db_params) # Changed
            print(f"EventManager: Successfully saved event {db_id} for guild {guild_id_str}.")

            # If this event was marked as dirty, clean it from the dirty set
            if guild_id_str in self._dirty_events and db_id in self._dirty_events[guild_id_str]:
                self._dirty_events[guild_id_str].discard(db_id)
                if not self._dirty_events[guild_id_str]: # If set becomes empty
                    del self._dirty_events[guild_id_str]

            return True

        except Exception as e:
            print(f"EventManager: Error saving event {event_id} for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            return False

    async def process_player_action_within_event(
        self,
        event_id: str,
        player_id: str, # Typically character_id
        action_type: str,
        action_data: Dict[str, Any],
        guild_id: str, # Added guild_id for context
        **kwargs: Any
    ) -> Dict[str, Any]:
        # TODO: CRITICAL - This is a stub. Full implementation needed.
        # This method should:
        # 1. Get the event object using event_id and guild_id.
        # 2. Get the player character object.
        # 3. Determine the current stage of the event.
        # 4. Check if the action_type is valid for the current stage's available actions/interactions.
        # 5. If valid, process the action:
        #    - Update event state_variables.
        #    - Check for stage transition conditions using RuleEngine.
        #    - If transition, call self._event_stage_processor.advance_stage(...).
        #    - Generate narrative response (possibly using AI via StageDescriptionGenerator or OpenAIService).
        # 6. Return a dictionary: {"success": bool, "message": str, "target_channel_id": int, "state_changed": bool, ...}

        event = self.get_event(guild_id, event_id)
        event_name = getattr(event, 'name', event_id) if event else event_id

        char_mgr: Optional["CharacterManager"] = kwargs.get('character_manager') # Type hint for clarity
        player_name = player_id # Default to ID
        if char_mgr: # No need for isinstance if we rely on duck typing or trust context
            try:
                # Assuming get_character might be async or sync; if it's always async, add await
                # For a stub, direct attribute access or a simpler call is fine.
                # This part depends on CharacterManager's interface.
                # Let's assume get_character is async for robust example.
                player = await char_mgr.get_character(guild_id=guild_id, character_id=player_id)
                if player:
                    # Assuming name_i18n is a dict like {"en": "Name", "ru": "Имя"}
                    player_name_i18n = getattr(player, 'name_i18n', {})
                    player_name = player_name_i18n.get('en', player_id) if isinstance(player_name_i18n, dict) else player_id
            except Exception as e:
                print(f"EventManager: Error fetching character {player_id} for event action: {e}")
                # player_name remains player_id

        message = (
            f"**Мастер (Событие: {event_name})**: Действие '{action_type}' от {player_name} отмечено. "
            f"Взаимодействие с событиями в разработке. Детали: {json.dumps(action_data)}" # Dump dict for clarity
        )
        print(f"EVENT_TODO: EventManager.process_player_action_within_event called for event {event_id}, player {player_id}, action {action_type}. Needs full implementation.")

        target_channel_id = None
        if event:
            target_channel_id = getattr(event, 'channel_id', None)

        if target_channel_id is None: # Fallback if event has no channel or event is None
            target_channel_id = kwargs.get('ctx_channel_id')


        return {
            "success": True,
            "message": message,
            "target_channel_id": target_channel_id,
            "state_changed": False
        }

# --- Конец класса EventManager ---

print("DEBUG: event_manager.py module loaded.")
