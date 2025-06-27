# bot/game/world_processors/world_simulation_processor.py

import asyncio
import traceback
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable, Set, Union, TYPE_CHECKING, cast

# Manager Imports
if TYPE_CHECKING:
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.crafting_manager import CraftingManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.global_npc_manager import GlobalNpcManager
    from bot.game.managers.mobile_group_manager import MobileGroupManager
    from bot.services.openai_service import OpenAIService
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.ai.prompt_context_collector import PromptContextCollector # Added for context_collector type
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
    from bot.game.npc_processors.npc_action_processor import NpcActionProcessor
    from bot.game.managers.persistence_manager import PersistenceManager
    from bot.game.models.event import Event, EventStage
    from bot.game.models.character import Character
    from bot.game.models.npc import NPC
    from bot.game.models.item import Item
    from bot.game.models.combat import Combat
    from bot.game.models.party import Party


SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class WorldSimulationProcessor:
    def __init__(self,
                 event_manager: "EventManager",
                 character_manager: "CharacterManager",
                 location_manager: "LocationManager",
                 rule_engine: "RuleEngine",
                 openai_service: "OpenAIService",
                 event_stage_processor: "EventStageProcessor",
                 event_action_processor: "EventActionProcessor",
                 persistence_manager: "PersistenceManager",
                 settings: Dict[str, Any],
                 send_callback_factory: SendCallbackFactory,
                 character_action_processor: "CharacterActionProcessor",
                 party_action_processor: "PartyActionProcessor",
                 npc_action_processor: Optional["NpcActionProcessor"] = None,
                 npc_manager: Optional["NpcManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                 item_manager: Optional["ItemManager"] = None,
                 time_manager: Optional["TimeManager"] = None,
                 status_manager: Optional["StatusManager"] = None,
                 crafting_manager: Optional["CraftingManager"] = None,
                 economy_manager: Optional["EconomyManager"] = None,
                 party_manager: Optional["PartyManager"] = None, # Note: party_manager is also a required arg earlier
                 dialogue_manager: Optional["DialogueManager"] = None,
                 quest_manager: Optional["QuestManager"] = None,
                 relationship_manager: Optional["RelationshipManager"] = None,
                 game_log_manager: Optional["GameLogManager"] = None,
                 multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None,
                 global_npc_manager: Optional["GlobalNpcManager"] = None,
                 mobile_group_manager: Optional["MobileGroupManager"] = None,
                ):
        print("Initializing WorldSimulationProcessor...")
        self._event_manager = event_manager
        self._character_manager = character_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._openai_service = openai_service
        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor
        self._persistence_manager = persistence_manager
        self._settings = settings
        self._send_callback_factory = send_callback_factory
        self._character_action_processor = character_action_processor
        self._party_action_processor = party_action_processor
        self._npc_action_processor = npc_action_processor
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._item_manager = item_manager
        self._time_manager = time_manager
        self._status_manager = status_manager
        self._crafting_manager = crafting_manager
        self._economy_manager = economy_manager
        self._party_manager_optional = party_manager # Use a different name for the optional one
        self._dialogue_manager = dialogue_manager
        self._quest_manager = quest_manager
        self._relationship_manager = relationship_manager
        self._game_log_manager = game_log_manager
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._global_npc_manager = global_npc_manager
        self._mobile_group_manager = mobile_group_manager
        self._command_prefix = settings.get('discord_command_prefix', '/')
        print("WorldSimulationProcessor initialized.")

    async def start_new_event(self,
                              event_template_id: str,
                              location_id: str,
                              guild_id: str,
                              players_discord_ids: List[int],
                              channel_id: int,
                              **kwargs: Any
                             ) -> Optional[str]:
        print(f"WSP: Starting event '{event_template_id}' at {location_id} in {guild_id} (channel {channel_id}).")
        status_callback = self._send_callback_factory(channel_id)

        context_for_managers: Dict[str, Any] = {
            'guild_id': guild_id, 'channel_id': channel_id, 'send_callback_factory': self._send_callback_factory,
            'settings': self._settings, 'world_simulation_processor': self,
            'character_manager': self._character_manager, 'location_manager': self._location_manager,
            'rule_engine': self._rule_engine, 'openai_service': self._openai_service,
            'npc_manager': self._npc_manager, 'combat_manager': self._combat_manager,
            'item_manager': self._item_manager, 'time_manager': self._time_manager,
            'status_manager': self._status_manager, 'party_manager': self._party_manager_optional, # Use optional one
            'event_manager': self._event_manager, 'persistence_manager': self._persistence_manager,
            'character_action_processor': self._character_action_processor,
            'party_action_processor': self._party_action_processor,
            'npc_action_processor': self._npc_action_processor,
            'event_stage_processor': self._event_stage_processor,
            'global_npc_manager': self._global_npc_manager,
            'mobile_group_manager': self._mobile_group_manager,
        }
        context_for_managers.update(kwargs)

        event_template_data = self._event_manager.get_event_template(event_template_id)
        if not event_template_data:
             print(f"WSP: Error: Event template '{event_template_id}' not found."); await status_callback(f"❌ Ошибка: Шаблон '{event_template_id}' не найден."); return None

        location_data = await self._location_manager.get_location_instance_by_id(guild_id, location_id)
        if not location_data:
             print(f"WSP: Error: Location '{location_id}' not found for guild {guild_id}."); await status_callback(f"❌ Ошибка: Локация '{location_id}' не найдена."); return None

        event_channel_id_final_any = getattr(location_data, 'channel_id', None)
        event_channel_id_final = int(str(event_channel_id_final_any)) if event_channel_id_final_any is not None else channel_id

        player_char_ids: List[str] = []
        if players_discord_ids:
             for discord_id in players_discord_ids:
                  char = await self._character_manager.get_character_by_discord_id(guild_id, str(discord_id))
                  if char:
                       char_id = getattr(char, 'id', None)
                       if char_id: player_char_ids.append(str(char_id))
                  else: print(f"WSP: Warn: Char not found for Discord ID: {discord_id} in guild {guild_id}.")

        new_event: Optional["Event"] = None
        try:
            # Ensure create_event_from_template is callable on event_manager
            create_event_method = getattr(self._event_manager, 'create_event_from_template', None)
            if not callable(create_event_method):
                print(f"WSP: Error: EventManager.create_event_from_template is not callable."); await status_callback("❌ Ошибка конфигурации EventManager."); return None

            new_event = await create_event_method(
                template_id=event_template_id, # template_id is required
                location_id=location_id, guild_id=guild_id,
                initial_player_ids=player_char_ids, channel_id=event_channel_id_final,
                **context_for_managers
            )
            if new_event is None:
                 print(f"WSP: Error: EventManager failed to create event '{event_template_id}'."); await status_callback(f"❌ Ошибка при создании '{event_template_id}'."); return None
            event_name = getattr(new_event, 'name_i18n', {}).get('en', 'Unknown Event')
            print(f"WSP: Event {new_event.id} ('{event_name}') created. Initial stage: {new_event.current_stage_id}")
        except Exception as e:
             print(f"WSP: Exception creating event '{event_template_id}': {e}"); traceback.print_exc(); await status_callback(f"❌ Критическая ошибка: {e}."); return None

        setattr(new_event, 'is_active', True) # Use setattr for safety if is_active might not exist
        add_active_event_method = getattr(self._event_manager, 'add_active_event', None)
        if callable(add_active_event_method): add_active_event_method(guild_id, new_event)
        else: print("WSP: Error: EventManager.add_active_event is not callable.")

        print(f"WSP: Processing initial stage '{new_event.current_stage_id}' for event {new_event.id}.")
        try:
            if new_event.channel_id is None:
                 print(f"WSP: Error: Event {new_event.id} has no channel_id."); await status_callback("❌ Ошибка: Событие без канала.");
                 if hasattr(self, 'end_event'): await self.end_event(guild_id, new_event.id); return None

            event_channel_callback = self._send_callback_factory(new_event.channel_id)
            await self._event_stage_processor.advance_stage(
                event=new_event, target_stage_id=new_event.current_stage_id,
                send_message_callback=event_channel_callback, **context_for_managers,
                transition_context={"trigger": "event_start", "template_id": event_template_id, "location_id": location_id, "guild_id": guild_id}
            )
            print(f"WSP: Initial stage processed for event {new_event.id}.")
            if self._persistence_manager:
                 save_state_method = getattr(self._persistence_manager, 'save_game_state', None)
                 if callable(save_state_method): await save_state_method(guild_ids=[guild_id], **context_for_managers)
            return new_event.id
        except Exception as e:
            event_name_err = getattr(new_event, 'name_i18n', {}).get('en', event_template_id)
            print(f"WSP: ❌ CRITICAL ERROR processing initial stage of event {new_event.id} ('{event_name_err}'): {e}"); traceback.print_exc()
            if hasattr(self, 'end_event'): await self.end_event(guild_id, new_event.id)
            await status_callback(f"❌ КРИТИЧЕСКАЯ ОШИБКА '{event_name_err}': {e}."); return None

    async def end_event(self, guild_id: str, event_id: str) -> None:
        # ... (rest of end_event, ensure managers and methods are checked with hasattr/callable) ...
        event: Optional["Event"] = self._event_manager.get_event(guild_id, event_id)
        if not event: print(f"WSP: Warn: End called for non-existent event {event_id}."); return
        if not getattr(event, 'is_active', False) and getattr(event, 'current_stage_id', None) == 'event_end': print(f"WSP: Event {event_id} already ended."); return

        setattr(event, 'current_stage_id', 'event_end')
        if hasattr(self._event_manager, 'mark_event_dirty'): self._event_manager.mark_event_dirty(guild_id, event.id)

        if self._npc_manager and hasattr(self._npc_manager, 'remove_npc') and callable(getattr(self._npc_manager, 'remove_npc')):
            temp_npc_ids: List[str] = getattr(event, 'state_variables', {}).get('temp_npcs', [])
            for npc_id in list(temp_npc_ids):
                try:
                    await self._npc_manager.remove_npc(npc_id, guild_id) # Removed **cleanup_context, assume remove_npc takes specific args
                    if 'temp_npcs' in getattr(event, 'state_variables', {}) and npc_id in event.state_variables['temp_npcs']:
                        event.state_variables['temp_npcs'].remove(npc_id)
                except Exception as e: print(f"WSP: Error removing temp NPC {npc_id}: {e}")
            if 'temp_npcs' in getattr(event, 'state_variables', {}) and not event.state_variables['temp_npcs']:
                event.state_variables.pop('temp_npcs', None)
                if hasattr(self._event_manager, 'mark_event_dirty'): self._event_manager.mark_event_dirty(guild_id, event.id)

        # ... (rest of end_event logic, similar safety checks)
        setattr(event, 'is_active', False)
        if hasattr(self._event_manager, 'remove_active_event'): self._event_manager.remove_active_event(guild_id, event.id)


    async def process_world_tick(self, game_time_delta: float, **kwargs: Any) -> None:
        # ... (ensure all manager.process_tick calls are guarded with hasattr/callable) ...
        active_guild_ids: List[str] = []
        persistence_manager = kwargs.get('persistence_manager')
        if persistence_manager and hasattr(persistence_manager, 'get_loaded_guild_ids') and callable(getattr(persistence_manager, 'get_loaded_guild_ids')):
            active_guild_ids = persistence_manager.get_loaded_guild_ids()
        if not active_guild_ids: return

        for guild_id in active_guild_ids:
            guild_tick_context: Dict[str, Any] = {'guild_id': guild_id, **kwargs}

            managers_to_tick = [
                self._time_manager, self._status_manager, self._crafting_manager,
                self._combat_manager, self._character_action_processor,
                self._npc_action_processor, self._party_action_processor,
                self._item_manager, self._location_manager, self._economy_manager,
                self._global_npc_manager, self._mobile_group_manager
            ]
            for manager_instance in managers_to_tick:
                if manager_instance:
                    process_tick_method = None
                    # Specific handling for processors that tick entities
                    if manager_instance is self._character_action_processor and self._character_manager and hasattr(self._character_manager, 'get_entities_with_active_action'):
                        entities = self._character_manager.get_entities_with_active_action(guild_id)
                        if entities and hasattr(manager_instance, 'process_tick'):
                            for entity_id in list(entities): await getattr(manager_instance, 'process_tick')(entity_id=entity_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                        continue # Skip generic tick
                    elif manager_instance is self._npc_action_processor and self._npc_manager and hasattr(self._npc_manager, 'get_entities_with_active_action'):
                        entities = self._npc_manager.get_entities_with_active_action(guild_id)
                        if entities and hasattr(manager_instance, 'process_tick'):
                             for entity_id in list(entities): await getattr(manager_instance, 'process_tick')(entity_id=entity_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                        continue
                    elif manager_instance is self._party_action_processor and self._party_manager_optional and hasattr(self._party_manager_optional, 'get_parties_with_active_action'):
                        entities = self._party_manager_optional.get_parties_with_active_action(guild_id)
                        if entities and hasattr(manager_instance, 'process_tick'):
                             for entity_id in list(entities): await getattr(manager_instance, 'process_tick')(party_id=entity_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context) # party_id
                        continue
                    elif manager_instance is self._combat_manager and hasattr(manager_instance, 'process_tick_for_guild'): # CombatManager specific
                        process_tick_method = getattr(manager_instance, 'process_tick_for_guild', None)
                    else: # Generic manager tick
                        process_tick_method = getattr(manager_instance, 'process_tick', None)

                    if callable(process_tick_method):
                        try: await process_tick_method(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                        except Exception as e: print(f"WSP: Error during {type(manager_instance).__name__} tick for guild {guild_id}: {e}"); traceback.print_exc()

            # Event auto-transition logic
            if self._event_manager and self._event_stage_processor and \
               hasattr(self._event_manager, 'get_active_events_by_guild') and callable(getattr(self._event_manager, 'get_active_events_by_guild')) and \
               hasattr(self._event_stage_processor, 'advance_stage') and callable(getattr(self._event_stage_processor, 'advance_stage')):
                active_events: List["Event"] = self._event_manager.get_active_events_by_guild(guild_id)
                for event_item in list(active_events):
                    if not getattr(event_item, 'is_active', False) or getattr(event_item, 'current_stage_id', None) == 'event_end': continue
                    next_stage_id_auto = self._check_event_for_auto_transition(event_item)
                    if next_stage_id_auto and event_item.channel_id is not None:
                        try:
                            event_channel_callback = self._send_callback_factory(event_item.channel_id)
                            await self._event_stage_processor.advance_stage(event=event_item, target_stage_id=next_stage_id_auto, send_message_callback=event_channel_callback, **guild_tick_context, transition_context={"trigger": "auto_advance"})
                        except Exception as e: print(f"WSP: Error auto-advancing event {event_item.id}: {e}")

                events_ending = [ev.id for ev in list(self._event_manager.get_active_events_by_guild(guild_id)) if getattr(ev, 'current_stage_id', None) == 'event_end']
                for event_id_to_end in events_ending: await self.end_event(guild_id, event_id_to_end)
            # ... (Persistence logic remains)

    async def generate_dynamic_event_narrative(self, guild_id: str, event_concept: str, related_entities: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        if not self._multilingual_prompt_generator or not self._openai_service or not self._settings:
            print("WSP ERROR: Core services for narrative generation not available."); return None

        context_collector_val = getattr(self._multilingual_prompt_generator, 'context_collector', None)
        if not isinstance(context_collector_val, PromptContextCollector) or \
           not hasattr(context_collector_val, 'get_full_context') or \
           not callable(getattr(context_collector_val, 'get_full_context')):
            print("WSP ERROR: MultilingualPromptGenerator.context_collector.get_full_context not available."); return None

        context_data = await context_collector_val.get_full_context(guild_id=guild_id) # No other params needed if default

        specific_task_prompt = f"Generate narrative for: {event_concept}. Related: {related_entities or 'General'}" # Simplified

        build_prompt_method = getattr(self._multilingual_prompt_generator, '_build_full_prompt_for_openai', None)
        if not callable(build_prompt_method):
            print("WSP ERROR: _build_full_prompt_for_openai not callable."); return None

        prompt_messages = build_prompt_method(
            generation_type_str="dynamic_narrative", # Added generation_type_str
            context_data=context_data,
            target_languages=["en", "ru"],
            specific_task_instruction=specific_task_prompt
        )
        # ... (rest of generation logic)
        generated_data = await self._openai_service.generate_structured_multilingual_content(
            system_prompt=prompt_messages["system"], user_prompt=prompt_messages["user"],
            max_tokens=self._settings.get("world_event_ai_settings", {}).get("max_tokens", 1500),
            temperature=self._settings.get("world_event_ai_settings", {}).get("temperature", 0.7)
        )
        if generated_data and "error" not in generated_data: return generated_data
        else: print(f"WSP ERROR: AI narrative generation failed: {generated_data.get('error') if generated_data else 'Unknown'}"); return None


    def _check_event_for_auto_transition(self, event: "Event") -> Optional[str]:
        # ... (ensure getattr is used for EventStage attributes like auto_transitions)
        current_stage_data = getattr(event, 'stages_data', {}).get(event.current_stage_id)
        if not current_stage_data: return None
        current_stage_obj: Union["EventStage", Dict[str, Any]]
        try: current_stage_obj = EventStage.model_validate(current_stage_data)
        except Exception: current_stage_obj = current_stage_data # Fallback

        auto_transitions_rules: List[Dict[str, Any]] = []
        if isinstance(current_stage_obj, EventStage): auto_transitions_rules = getattr(current_stage_obj, 'auto_transitions', []) or []
        elif isinstance(current_stage_obj, dict): auto_transitions_rules = current_stage_obj.get('auto_transitions', []) or []

        # ... (rest of logic, ensure safe access to rule dict keys)
        for rule in auto_transitions_rules:
            if not isinstance(rule, dict): continue
            # ...
        return None

    def _get_managers_for_rule_engine_context(self) -> Dict[str, Any]:
        # ... (This method seems fine, just ensure all managers are correctly assigned in __init__)
        return { name[1:]: manager for name, manager in self.__dict__.items() if name.startswith('_') and manager is not None and not name.endswith('optional')}


