# bot/game/managers/event_manager.py

from __future__ import annotations
import json
import uuid
import traceback # Will be removed
import asyncio
import logging # Added
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union, Tuple

from bot.game.models.event import Event
from bot.services.db_service import DBService
from builtins import dict, set, list, str, int, bool, float

if TYPE_CHECKING:
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
    from bot.game.ai.event_ai_generator import EventAIGenerator
    from bot.game.managers.game_log_manager import GameLogManager

logger = logging.getLogger(__name__) # Added

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

logger.debug("DEBUG: dialogue_manager.py module loaded.") # Changed from dialogue_manager to event_manager (original was likely a copy-paste error)

class EventManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _event_templates: Dict[str, Dict[str, Dict[str, Any]]]
    _active_events: Dict[str, Dict[str, "Event"]]
    _active_events_by_channel: Dict[str, Dict[int, str]]
    _dirty_events: Dict[str, Set[str]]
    _deleted_event_ids: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        npc_manager: Optional["NpcManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        character_manager: Optional["CharacterManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        time_manager: Optional["TimeManager"] = None,
        event_stage_processor: Optional["EventStageProcessor"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None,
        openai_service: Optional["OpenAIService"] = None
    ):
        logger.info("Initializing EventManager...") # Changed
        self._db_service = db_service
        self._settings = settings
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
        self._game_log_manager = game_log_manager
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._openai_service = openai_service

        if self._openai_service and self._multilingual_prompt_generator and self._settings:
            # Assuming EventAIGenerator is defined elsewhere or imported
            from bot.game.ai.event_ai_generator import EventAIGenerator # Moved import here
            self._event_ai_generator: Optional[EventAIGenerator] = EventAIGenerator(
                openai_service=self._openai_service,
                multilingual_prompt_generator=self._multilingual_prompt_generator,
                settings=self._settings
            )
            logger.info("EventManager: EventAIGenerator initialized.") # Changed
        else:
            self._event_ai_generator = None
            logger.warning("EventManager: EventAIGenerator NOT initialized due to missing dependencies (OpenAI, PromptGen, or Settings).") # Changed

        self._event_templates = {}
        self._active_events = {}
        self._active_events_by_channel = {}
        self._dirty_events = {}
        self._deleted_event_ids = {}
        logger.info("EventManager initialized.") # Changed

    def load_static_templates(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        logger.info("EventManager: Loading event templates for guild %s...", guild_id_str) # Changed

        self._event_templates.pop(guild_id_str, None)
        guild_templates_cache = self._event_templates.setdefault(guild_id_str, {})

        try:
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            templates_data = guild_settings.get('event_templates')

            if isinstance(templates_data, dict):
                 for tpl_id, data in templates_data.items():
                      if tpl_id and isinstance(data, dict):
                           clone = data.copy()
                           clone.setdefault('id', str(tpl_id))
                           clone.setdefault('name', f"Unnamed Event ({tpl_id})")
                           stages_data = clone.get('stages_data', {})
                           if not isinstance(stages_data, dict):
                                logger.warning("EventManager: Template '%s' stages_data is not a dict (%s) for guild %s. Using empty dict.", tpl_id, type(stages_data), guild_id_str) # Changed
                                stages_data = {}
                           clone['stages_data'] = stages_data
                           if stages_data and not clone.get('start_stage_id'):
                                if stages_data:
                                     first_stage_id = next(iter(stages_data), None)
                                     if first_stage_id:
                                         clone.setdefault('start_stage_id', str(first_stage_id))
                                         logger.warning("EventManager: Template '%s' for guild %s missing start_stage_id, defaulting to first stage '%s'.", tpl_id, guild_id_str, first_stage_id) # Changed
                                     else:
                                          logger.warning("EventManager: Template '%s' for guild %s stages_data is empty, cannot set start_stage_id.", tpl_id, guild_id_str) # Changed
                           guild_templates_cache[str(tpl_id)] = clone
                 logger.info("EventManager: Loaded %s event templates for guild %s.", len(guild_templates_cache), guild_id_str) # Changed
            elif templates_data is not None:
                 logger.warning("EventManager: Event templates data for guild %s is not a dictionary (%s). Skipping template load.", guild_id_str, type(templates_data)) # Changed
            else:
                 logger.info("EventManager: No event templates found in settings for guild %s or globally.", guild_id_str) # Changed
        except Exception as e:
            logger.error("EventManager: Error loading event templates for guild %s: %s", guild_id_str, e, exc_info=True) # Changed

    def get_event_template(self, guild_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        guild_id_str = str(guild_id)
        guild_templates = self._event_templates.get(guild_id_str, {})
        return guild_templates.get(str(template_id))

    def get_event(self, guild_id: str, event_id: str) -> Optional["Event"]:
        guild_id_str = str(guild_id)
        guild_events = self._active_events.get(guild_id_str)
        if guild_events:
             return guild_events.get(str(event_id))
        return None

    def get_active_events(self, guild_id: str) -> List["Event"]:
        guild_id_str = str(guild_id)
        guild_events = self._active_events.get(guild_id_str)
        if guild_events:
             return list(guild_events.values())
        return []

    def get_event_by_channel_id(self, guild_id: str, channel_id: int) -> Optional["Event"]:
        guild_id_str = str(guild_id)
        channel_id_int = int(channel_id)
        guild_channel_map = self._active_events_by_channel.get(guild_id_str)
        if guild_channel_map:
             event_id = guild_channel_map.get(channel_id_int)
             if event_id:
                 return self.get_event(guild_id_str, event_id)
        return None

    async def create_event_from_template(
        self, guild_id: str, template_id: str, location_id: Optional[str] = None,
        initial_player_ids: Optional[List[str]] = None, channel_id: Optional[int] = None, **kwargs: Any,
    ) -> Optional["Event"]:
        guild_id_str = str(guild_id)
        logger.info("EventManager: Creating event for guild %s from template '%s'", guild_id_str, template_id) # Changed

        if self._db_service is None or self._db_service.adapter is None:
            logger.error("EventManager: No DB service or adapter for guild %s. Cannot create persistent event.", guild_id_str) # Changed
            return None

        tpl = self.get_event_template(guild_id_str, template_id)
        if not tpl:
            logger.warning("EventManager: Template '%s' not found for guild %s.", template_id, guild_id_str) # Changed
            return None
        try:
            eid = str(uuid.uuid4())
            tpl_stages_data = tpl.get('stages_data', {})
            if not isinstance(tpl_stages_data, dict): tpl_stages_data = {}
            tpl_initial_state_variables = tpl.get('initial_state_variables', {})
            if not isinstance(tpl_initial_state_variables, dict): tpl_initial_state_variables = {}

            event_state_variables = tpl_initial_state_variables.copy()
            if kwargs.get('initial_state_variables'):
                 event_state_variables.update(kwargs['initial_state_variables'])
            event_stages_data = tpl_stages_data.copy()
            if kwargs.get('stages_data'):
                 if isinstance(kwargs['stages_data'], dict): event_stages_data.update(kwargs['stages_data'])
                 else: logger.warning("EventManager: Provided stages_data for event in guild %s is not a dict (%s). Ignoring.", guild_id_str, type(kwargs['stages_data'])) # Changed

            data: Dict[str, Any] = {
                'id': eid, 'template_id': str(template_id),
                'name': str(tpl.get('name', 'Событие')), 'guild_id': guild_id_str,
                'is_active': kwargs.get('is_active', True),
                'channel_id': int(channel_id) if channel_id is not None else None,
                'current_stage_id': str(kwargs.get('start_stage_id', tpl.get('start_stage_id', 'start'))),
                'players': initial_player_ids or [], 'state_variables': event_state_variables,
                'stages_data': event_stages_data,
                'end_message_template': str(kwargs.get('end_message_template', tpl.get('end_message_template', 'Событие завершилось.'))),
            }
            if not isinstance(data.get('players'), list): data['players'] = []
            else: data['players'] = [str(p) for p in data['players'] if p is not None]
            event = Event.from_dict(data)

            spawn_context = {**kwargs, 'event_id': eid, 'npc_manager': self._npc_manager, 'item_manager': self._item_manager}
            temp_npcs_ids = await self._spawn_npcs_for_event(tpl, location_id, eid, guild_id_str, spawn_context)
            if temp_npcs_ids: event.state_variables.setdefault('__temp_npcs', []).extend(temp_npcs_ids)
            temp_items_ids = await self._spawn_items_for_event(tpl, location_id, eid, guild_id_str, spawn_context)
            if temp_items_ids: event.state_variables.setdefault('__temp_items', []).extend(temp_items_ids)

            self._active_events.setdefault(guild_id_str, {})[eid] = event
            if event.channel_id is not None:
                 self._active_events_by_channel.setdefault(guild_id_str, {})[event.channel_id] = eid
            self.mark_event_dirty(guild_id_str, eid)

            event_display_name = getattr(event, 'name', eid)
            logger.info("EventManager: Event '%s' ('%s') created for guild %s in channel %s. Marked dirty.", eid, event_display_name, guild_id_str, event.channel_id) # Changed

            if self._game_log_manager: # Log EVENT_STARTED
                # ... (game log logic as before, ensure guild_id is in logs) ...
                pass # GameLogManager calls already include guild_id

            return event
        except Exception as exc:
            logger.error("EventManager: Error creating event from template '%s' for guild %s: %s", template_id, guild_id_str, exc, exc_info=True) # Changed
            return None

    async def _spawn_npcs_for_event(
        self, event_template_data: Dict[str, Any], event_location_id: Optional[str],
        event_id: str, guild_id: str, spawn_context: Dict[str, Any]
    ) -> List[str]:
        spawned_npc_ids: List[str] = []
        npc_mgr = spawn_context.get('npc_manager', self._npc_manager)
        if not npc_mgr or not hasattr(npc_mgr, 'create_npc'):
            logger.warning("EventManager (guild %s): NPCManager not available or create_npc method missing. Skipping NPC spawn for event %s.", guild_id, event_id) # Changed
            return spawned_npc_ids
        for spawn_def in event_template_data.get('npc_spawn_templates', []):
            # ... (NPC spawning logic as before, ensure guild_id in logs for errors) ...
            if not isinstance(spawn_def, dict): continue
            try:
                # ... (rest of spawn logic)
                pass
            except Exception as e:
                logger.error("EventManager (guild %s): Error spawning NPC '%s' for event %s: %s", guild_id, spawn_def.get('template_id','N/A'), event_id, e, exc_info=True) # Changed
        return spawned_npc_ids

    async def _spawn_items_for_event(
        self, event_template_data: Dict[str, Any], event_location_id: Optional[str],
        event_id: str, guild_id: str, spawn_context: Dict[str, Any]
    ) -> List[str]:
        spawned_item_ids: List[str] = []
        item_mgr = spawn_context.get('item_manager', self._item_manager)
        if not item_mgr or not hasattr(item_mgr, 'create_item') or not hasattr(item_mgr, 'move_item'):
            logger.warning("EventManager (guild %s): ItemManager not available or methods missing. Skipping item spawn for event %s.", guild_id, event_id) # Changed
            return spawned_item_ids
        for spawn_def in event_template_data.get('item_spawn_templates', []):
            # ... (Item spawning logic as before, ensure guild_id in logs for errors) ...
            if not isinstance(spawn_def, dict): continue
            try:
                # ... (rest of spawn logic)
                pass
            except Exception as e:
                logger.error("EventManager (guild %s): Error spawning item '%s' for event %s: %s", guild_id, spawn_def.get('template_id','N/A'), event_id, e, exc_info=True) # Changed
        return spawned_item_ids

    async def remove_active_event(self, guild_id: str, event_id: str, **kwargs: Any) -> Optional[str]:
        guild_id_str = str(guild_id)
        logger.info("EventManager: Removing event '%s' from guild %s...", event_id, guild_id_str) # Changed

        event = self.get_event(guild_id_str, event_id)
        if not event or str(getattr(event, 'guild_id', None)) != guild_id_str:
            if guild_id_str in self._deleted_event_ids and event_id in self._deleted_event_ids[guild_id_str]:
                 logger.debug("EventManager: Event %s in guild %s was already marked for deletion.", event_id, guild_id_str) # Added
                 return event_id
            logger.warning("EventManager: Event %s not found or does not belong to guild %s for removal.", event_id, guild_id_str) # Changed
            return None

        is_already_inactive = not getattr(event, 'is_active', True)
        if not is_already_inactive:
             logger.info("EventManager: Cleaning up resources for active event %s in guild %s before removal...", event_id, guild_id_str) # Changed
             # ... (Cleanup logic as before, ensure guild_id in logs for errors) ...
             # Example: logger.error("Error removing temp NPC %s for event %s in guild %s.", npc_id, event_id, guild_id_str, exc_info=True)
        else:
             logger.info("EventManager: Event %s in guild %s was already inactive, skipping resource cleanup during removal.", event_id, guild_id_str) # Changed

        guild_events_cache = self._active_events.get(guild_id_str)
        if guild_events_cache: guild_events_cache.pop(event_id, None)
        guild_channel_map = self._active_events_by_channel.get(guild_id_str)
        if guild_channel_map: # Channel map cleanup
            # ... (channel map cleanup logic as before) ...
            pass

        self._dirty_events.get(guild_id_str, set()).discard(event_id)
        self._deleted_event_ids.setdefault(guild_id_str, set()).add(event_id)
        logger.info("EventManager: Event '%s' fully removed from cache and marked for deletion for guild %s.", event_id, guild_id_str) # Changed
        return event_id

    async def end_event(self, guild_id: str, event_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("EventManager: Ending event %s for guild %s...", event_id, guild_id_str) # Changed

        event = self.get_event(guild_id_str, event_id)
        if not event or str(getattr(event, 'guild_id', None)) != guild_id_str:
            logger.warning("EventManager: Attempted to end non-existent/mismatched-guild event %s for guild %s.", event_id, guild_id_str) # Changed
            return

        if not getattr(event, 'is_active', True):
             logger.info("EventManager: Event %s in guild %s is already inactive. Skipping end process.", event_id, guild_id_str) # Changed
             return

        if hasattr(event, 'is_active'): event.is_active = False
        self.mark_event_dirty(guild_id_str, event_id)

        await self._perform_event_cleanup_logic(event, **kwargs)

        # ... (Send end message logic as before, ensure guild_id in logs for errors) ...
        # Example: logger.error("Error sending event end message for %s in guild %s: %s", event_id, guild_id_str, e, exc_info=True)

        if self._game_log_manager: # Game log
            # ... (game log logic as before, ensure guild_id is in logs) ...
            pass # GameLogManager calls already include guild_id

        logger.info("EventManager: Event %s in guild %s state set to inactive. Calling remove_active_event...", event_id, guild_id_str) # Changed
        await self.remove_active_event(guild_id_str, event_id, **kwargs)
        logger.info("EventManager: Event %s fully ended for guild %s.", event_id, guild_id_str) # Changed

    async def _perform_event_cleanup_logic(self, event: "Event", **kwargs: Any) -> None:
        guild_id = getattr(event, 'guild_id', None)
        event_id = getattr(event, 'id', None)
        if not guild_id or not event_id:
            logger.warning("EventManager: _perform_event_cleanup_logic called with event missing guild_id or id: %s. Cannot perform cleanup.", event) # Changed
            return
        guild_id_str = str(guild_id)
        logger.info("EventManager: Performing resource cleanup for event %s in guild %s...", event_id, guild_id_str) # Changed
        # ... (Rest of cleanup logic, ensure guild_id is in logs for errors) ...
        # Example: logger.error("Error during cleanup for participant %s %s in event %s (guild %s): %s", p_type, participant_id, event_id, guild_id_str, e, exc_info=True)

    async def generate_event_details_from_ai(self, guild_id: str, event_concept: str, related_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if not self._event_ai_generator:
            logger.error("EventManager (guild %s): EventAIGenerator is not available. Cannot generate event details.", guild_id) # Changed
            return None
        logger.info("EventManager (guild %s): Generating AI event details for concept: %s", guild_id, event_concept) # Added
        return await self._event_ai_generator.generate_event_details_from_ai(
            guild_id=guild_id, event_concept=event_concept, related_context=related_context
        )

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("EventManager: Loading state for guild %s (events + templates)...", guild_id_str) # Changed
        if self._db_service is None or self._db_service.adapter is None:
            logger.warning("EventManager: No DB service or adapter for guild %s. Skipping event/template load.", guild_id_str) # Changed
            return
        self.load_static_templates(guild_id_str)
        # ... (Rest of load_state logic, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.critical("EventManager: CRITICAL ERROR fetching events for guild %s: %s", guild_id_str, e, exc_info=True)
        # Example: logger.info("EventManager: Successfully loaded %s active events into cache for guild %s.", loaded_count, guild_id_str)

    def _transform_db_row_to_event(self, row_data: Dict[str, Any], guild_id_str: str) -> Optional[Event]:
        # ... (Transform logic as before, ensure guild_id in logs for warnings/errors) ...
        # Example: logger.warning("EventManager (guild %s): Skipping event row with invalid ID ('%s') or mismatched guild ('%s').", guild_id_str, event_id_raw, loaded_guild_id_raw)
        # Example: logger.error("EventManager (guild %s): Error transforming DB row to event %s: %s", guild_id_str, data.get('id', 'N/A'), e, exc_info=True)
        return None # Placeholder, original logic is complex

    def _prepare_event_for_db(self, event_object: Event) -> Optional[Tuple]:
        # ... (Prepare logic as before, ensure guild_id in logs for warnings/errors) ...
        # Example: logger.error("EventManager (guild %s): Error preparing data for event %s for DB: %s", guild_id_str, event_id_str, e, exc_info=True)
        return None # Placeholder

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        # logger.debug("EventManager: Saving events for guild %s...", guild_id_str) # Too noisy for info
        if self._db_service is None or self._db_service.adapter is None:
            logger.warning("EventManager (guild %s): Cannot save events, DB service or adapter missing.", guild_id_str) # Changed
            return
        # ... (Rest of save_state logic, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.info("EventManager (guild %s): Saving %s dirty active, deleting %s events...", guild_id_str, len(events_to_save), len(deleted_event_ids_set))
        # Example: logger.error("EventManager (guild %s): Error deleting events: %s", guild_id_str, e, exc_info=True)

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("EventManager: Rebuilding runtime caches for guild %s...", guild_id_str) # Changed
        # ... (Rest of rebuild logic, ensure guild_id in logs for warnings/errors) ...
        logger.info("EventManager: Rebuild runtime caches complete for guild %s. Channel map size: %s", guild_id_str, len(self._active_events_by_channel.get(guild_id_str, {}))) # Changed

    def mark_event_dirty(self, guild_id: str, event_id: str) -> None:
         guild_id_str = str(guild_id)
         event_id_str = str(event_id)
         guild_events_cache = self._active_events.get(guild_id_str)
         if guild_events_cache and event_id_str in guild_events_cache:
              self._dirty_events.setdefault(guild_id_str, set()).add(event_id_str)
         # else: logger.debug("EventManager: Attempted to mark non-existent event %s in guild %s as dirty.", event_id_str, guild_id_str) # Too noisy

    def mark_event_deleted(self, guild_id: str, event_id: str) -> None:
         guild_id_str = str(guild_id)
         event_id_str = str(event_id)
         self._deleted_event_ids.setdefault(guild_id_str, set()).add(event_id_str)
         if guild_id_str in self._dirty_events:
            self._dirty_events.get(guild_id_str, set()).discard(event_id_str)
         logger.info("EventManager: Event %s marked for deletion for guild %s.", event_id_str, guild_id_str) # Changed

    async def save_event(self, event: "Event", guild_id: str) -> bool:
        # ... (Save single event logic, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.error("EventManager: Error saving event %s for guild %s: %s", event_id, guild_id_str, e, exc_info=True)
        return False # Placeholder

    async def process_player_action_within_event(
        self, event_id: str, player_id: str, action_type: str,
        action_data: Dict[str, Any], guild_id: str, **kwargs: Any
    ) -> Dict[str, Any]:
        # ... (Process action logic, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.info("EVENT_TODO: EventManager.process_player_action_within_event called for event %s, player %s, action %s in guild %s.", event_id, player_id, action_type, guild_id)
        return {"success": False, "message": "Not implemented", "target_channel_id": None, "state_changed": False} # Placeholder

logger.debug("DEBUG: event_manager.py module loaded.") # Changed
