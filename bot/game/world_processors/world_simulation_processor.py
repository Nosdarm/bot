# bot/game/world_processors/world_simulation_processor.py

import asyncio
import traceback
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable, Set, Union, TYPE_CHECKING

# Manager Imports
if TYPE_CHECKING: # Use TYPE_CHECKING to avoid circular imports at runtime for type hints
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
                 npc_action_processor: Optional["NpcActionProcessor"] = None, # Made optional as it might not exist
                 npc_manager: Optional["NpcManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                 item_manager: Optional["ItemManager"] = None,
                 time_manager: Optional["TimeManager"] = None,
                 status_manager: Optional["StatusManager"] = None,
                 crafting_manager: Optional["CraftingManager"] = None,
                 economy_manager: Optional["EconomyManager"] = None,
                 party_manager: Optional["PartyManager"] = None,
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
        self._party_manager = party_manager
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
        print(f"WorldSimulationProcessor initiating start of new event from template '{event_template_id}' at location {location_id} in guild {guild_id} channel {channel_id}.")
        status_callback = self._send_callback_factory(channel_id)

        context_for_managers: Dict[str, Any] = {
            'guild_id': guild_id,
            'channel_id': channel_id,
            'send_callback_factory': self._send_callback_factory,
            'settings': self._settings,
            'world_simulation_processor': self,
            'character_manager': self._character_manager, 'location_manager': self._location_manager,
            'rule_engine': self._rule_engine, 'openai_service': self._openai_service,
            'npc_manager': self._npc_manager, 'combat_manager': self._combat_manager,
            'item_manager': self._item_manager, 'time_manager': self._time_manager,
            'status_manager': self._status_manager, 'party_manager': self._party_manager,
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
             print(f"WorldSimulationProcessor: Error starting event: Event template '{event_template_id}' not found.")
             await status_callback(f"❌ Ошибка: Шаблон события '{event_template_id}' не найден.")
             return None

        location_data = await self._location_manager.get_location_instance_by_id(guild_id, location_id) # Changed to get_location_instance_by_id and added await
        if not location_data:
             print(f"WorldSimulationProcessor: Error starting event: Location '{location_id}' not found for guild {guild_id}.")
             await status_callback(f"❌ Ошибка: Локация '{location_id}' не найдена для вашей гильдии.")
             return None

        event_channel_id_final = getattr(location_data, 'channel_id', None) # Use getattr for safe access
        if event_channel_id_final is None:
             event_channel_id_final = channel_id
             print(f"WorldSimulationProcessor: No specific channel_id found for location {location_id} in guild {guild_id}. Using command channel {channel_id} for event.")
             if not isinstance(event_channel_id_final, int):
                  print(f"WorldSimulationProcessor: Error starting event: Command channel ID is not an integer ({channel_id}). Cannot determine event channel.")
                  await status_callback(f"❌ Ошибка: Не удалось определить Discord канал для события.")
                  return None

        player_char_ids: List[str] = []
        if players_discord_ids:
             for discord_id in players_discord_ids:
                  char = await self._character_manager.get_character_by_discord_id(guild_id, str(discord_id)) # Ensure discord_id is str, added await
                  if char:
                       char_id = getattr(char, 'id', None)
                       if char_id: player_char_ids.append(str(char_id))
                  else:
                       print(f"WorldSimulationProcessor: Warning: Character not found for Discord user ID: {discord_id} in guild {guild_id}. Cannot add to event.")

        new_event: Optional["Event"] = None
        try:
            new_event = await self._event_manager.create_event_from_template(
                template_id=event_template_id,
                location_id=location_id,
                guild_id=guild_id,
                initial_player_ids=player_char_ids,
                channel_id=event_channel_id_final,
                **context_for_managers
            )

            if new_event is None:
                 print(f"WorldSimulationProcessor: Error: EventManager failed to create event object from template '{event_template_id}' for guild {guild_id}.")
                 await status_callback(f"❌ Ошибка при создании события из шаблона '{event_template_id}'. EventManager вернул None.")
                 return None

            event_name = getattr(new_event, 'name', 'Unknown Event') # Safe access
            print(f"WorldSimulationProcessor: Event object {new_event.id} ('{event_name}') created for guild {guild_id} location {location_id} in channel {new_event.channel_id}. Initial stage: {new_event.current_stage_id}")

        except Exception as e:
             print(f"WorldSimulationProcessor: Exception caught while creating event object from template {event_template_id} for guild {guild_id}: {e}")
             traceback.print_exc()
             await status_callback(f"❌ Критическая ошибка при создании события из шаблона '{event_template_id}': {e}. Смотрите логи бота.")
             return None

        if new_event is None: # Should not happen if above logic is correct, but as a safeguard
            return None

        new_event.is_active = True
        self._event_manager.add_active_event(guild_id, new_event)

        print(f"WorldSimulationProcessor: Calling EventStageProcessor to process the initial stage '{new_event.current_stage_id}' for event {new_event.id} in guild {guild_id}.")

        try:
            if new_event.channel_id is None:
                 print(f"WorldSimulationProcessor: Error: Newly created event {new_event.id} in guild {guild_id} has no channel_id before processing initial stage.")
                 await status_callback(f"❌ Ошибка: Созданное событие не привязано к Discord каналу. Невозможно обработать начальную стадию.")
                 try: await self.end_event(guild_id, new_event.id)
                 except Exception as cleanup_e: print(f"WorldSimulationProcessor: Error during cleanup of event {new_event.id} after channel error: {cleanup_e}")
                 return None

            event_channel_callback = self._send_callback_factory(new_event.channel_id)

            await self._event_stage_processor.advance_stage(
                event=new_event, target_stage_id=new_event.current_stage_id,
                send_message_callback=event_channel_callback,
                **context_for_managers,
                transition_context={"trigger": "event_start", "template_id": event_template_id, "location_id": location_id, "guild_id": guild_id}
            )
            print(f"WorldSimulationProcessor: Initial stage processing completed for event {new_event.id} in guild {guild_id}.")

            if self._persistence_manager:
                 try:
                     save_kwargs = {'time_manager': self._time_manager}
                     save_kwargs.update(context_for_managers)
                     await self._persistence_manager.save_game_state(guild_ids=[guild_id], **save_kwargs)
                     print(f"WorldSimulationProcessor: Initial game state saved after starting event {new_event.id} for guild {guild_id}.")
                 except Exception as e:
                     print(f"WorldSimulationProcessor: Error during initial save after event start for guild {guild_id}: {e}")
                     traceback.print_exc()
            else:
                  print("WorldSimulationProcessor: Skipping initial save after event start (PersistenceManager not available).")
            return new_event.id

        except Exception as e:
            event_name_for_error = getattr(new_event, 'name', event_template_id) if new_event else event_template_id
            error_event_id = new_event.id if new_event else "UNKNOWN_EVENT_ID"
            print(f"WorldSimulationProcessor: ❌ КРИТИЧЕСКАЯ ОШИБКА во время обработки начальной стадии события {error_event_id} для гильдии {guild_id}: {e}")
            traceback.print_exc()
            if new_event: # Only try to end if new_event object exists
                try: await self.end_event(guild_id, new_event.id)
                except Exception as cleanup_e: print(f"WorldSimulationProcessor: Error during cleanup of event {error_event_id} after critical stage processing error: {cleanup_e}")
            await status_callback(f"❌ КРИТИЧЕСКАЯ ОШИБКА при запуске начальной стадии события '{event_name_for_error}': {e}. Событие остановлено. Проверьте логи бота.")
            return None


    async def end_event(self, guild_id: str, event_id: str) -> None:
        print(f"WorldSimulationProcessor: Received request to end event {event_id} for guild {guild_id}.")

        cleanup_context: Dict[str, Any] = {
            'guild_id': guild_id,
            'event_id': event_id,
            'send_callback_factory': self._send_callback_factory,
            'settings': self._settings,
            'character_manager': self._character_manager, 'location_manager': self._location_manager,
            'rule_engine': self._rule_engine, 'openai_service': self._openai_service,
            'npc_manager': self._npc_manager, 'combat_manager': self._combat_manager,
            'item_manager': self._item_manager, 'time_manager': self._time_manager,
            'status_manager': self._status_manager, 'party_manager': self._party_manager,
            'event_manager': self._event_manager,
            'global_npc_manager': self._global_npc_manager,
            'mobile_group_manager': self._mobile_group_manager,
        }

        event: Optional["Event"] = self._event_manager.get_event(guild_id, event_id)

        if not event:
            print(f"WorldSimulationProcessor: Warning: Attempted to end non-existent event {event_id} for guild {guild_id}.")
            return

        if not event.is_active and event.current_stage_id == 'event_end':
             print(f"WorldSimulationProcessor: Event {event_id} for guild {guild_id} is already marked as ended. Skipping end process.")
             return

        if event.current_stage_id != 'event_end':
             print(f"WorldSimulationProcessor: Forcing event {event.id} for guild {guild_id} current_stage_id to 'event_end' for termination.")
             event.current_stage_id = 'event_end'
             self._event_manager.mark_event_dirty(guild_id, event.id)

        event_name = getattr(event, 'name', 'N/A') # Safe access
        print(f"WorldSimulationProcessor: Ending event {event.id} ('{event_name}') for guild {guild_id}. Initiating cleanup.")

        cleaned_up_npcs_count = 0
        if self._npc_manager:
            temp_npc_ids: List[str] = getattr(event, 'state_variables', {}).get('temp_npcs', [])
            if temp_npc_ids:
                 print(f"WorldSimulationProcessor: Cleaning up {len(temp_npc_ids)} temporary NPCs for event {event.id} in guild {guild_id}.")
                 successfully_removed_npc_ids: List[str] = []
                 for npc_id in list(temp_npc_ids): # Iterate over a copy if modifying
                      try:
                           if hasattr(self._npc_manager, 'remove_npc') and callable(getattr(self._npc_manager, 'remove_npc')):
                               removed_id = await self._npc_manager.remove_npc(npc_id, guild_id, **cleanup_context)
                               if removed_id:
                                    successfully_removed_npc_ids.append(removed_id)
                               if 'temp_npcs' in getattr(event, 'state_variables', {}) and npc_id in event.state_variables['temp_npcs']: # Re-check existence
                                    event.state_variables['temp_npcs'].remove(npc_id)
                           else:
                                print(f"WorldSimulationProcessor: NPCManager missing remove_npc method for event {event.id}, npc {npc_id}.")
                      except Exception as e:
                           print(f"WorldSimulationProcessor: Error removing temp NPC {npc_id} for event {event.id} in guild {guild_id}: {e}")
                           traceback.print_exc()
                 cleaned_up_npcs_count = len(successfully_removed_npc_ids)
                 print(f"WorldSimulationProcessor: Finished NPC cleanup for event {event.id} in guild {guild_id}. {cleaned_up_npcs_count} NPCs removed.")
                 if 'temp_npcs' in getattr(event, 'state_variables', {}) and not event.state_variables.get('temp_npcs'): # Check if list is empty
                      event.state_variables.pop('temp_npcs', None) # Safe pop
                      self._event_manager.mark_event_dirty(guild_id, event.id)

        if event.channel_id is not None:
            send_callback = self._send_callback_factory(event.channel_id)
            end_message_content: Optional[str] = getattr(event, 'end_message_template', None)
            if not end_message_content:
                 end_message_content = f"Событие **{event_name}** завершилось."
            try:
                 await send_callback(end_message_content)
                 print(f"WorldSimulationProcessor: Sent event end message for event {event.id} to channel {event.channel_id} in guild {guild_id}.")
            except Exception as e:
                 print(f"WorldSimulationProcessor: Error sending event end message for event {event.id} to channel {event.channel_id} in guild {guild_id}: {e}")
                 traceback.print_exc()

        event.is_active = False
        self._event_manager.remove_active_event(guild_id, event.id)
        print(f"WorldSimulationProcessor: Event {event.id} for guild {guild_id} marked inactive and removed from active cache.")

        if self._persistence_manager:
             try:
                 save_kwargs = {'time_manager': self._time_manager}
                 save_kwargs.update(cleanup_context)
                 await self._persistence_manager.save_game_state(guild_ids=[guild_id], **save_kwargs)
                 print(f"WorldSimulationProcessor: Final game state saved after ending event {event.id} for guild {guild_id}.")
             except Exception as e:
                 print(f"WorldSimulationProcessor: Error during final save after ending event {event.id} for guild {guild_id}: {e}")
                 traceback.print_exc()
        else:
             print("WorldSimulationProcessor: Skipping final save after ending event (PersistenceManager not available).")
        print(f"WorldSimulationProcessor: Event {event_id} ending process completed for guild {guild_id}.")

    async def process_world_tick(self, game_time_delta: float, **kwargs: Any) -> None:
        active_guild_ids: List[str] = []
        persistence_manager = kwargs.get('persistence_manager')
        if persistence_manager and hasattr(persistence_manager, 'get_loaded_guild_ids'):
            active_guild_ids = persistence_manager.get_loaded_guild_ids()
        if not active_guild_ids:
             return

        for guild_id in active_guild_ids:
             guild_tick_context: Dict[str, Any] = {'guild_id': guild_id}
             guild_tick_context.update(kwargs)

             if self._time_manager:
                 try:
                      await self._time_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                 except Exception as e: print(f"WorldSimulationProcessor: Error during TimeManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             if self._status_manager:
                  try:
                       await self._status_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during StatusManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             if self._crafting_manager:
                  try:
                       await self._crafting_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during CraftingManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             if self._combat_manager:
                 try:
                      if hasattr(self._combat_manager, 'process_tick_for_guild') and callable(getattr(self._combat_manager, 'process_tick_for_guild')):
                           await self._combat_manager.process_tick_for_guild(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                      elif hasattr(self._combat_manager, 'get_active_combats_by_guild') and callable(getattr(self._combat_manager, 'get_active_combats_by_guild')) \
                           and hasattr(self._combat_manager, 'process_combat_round') and callable(getattr(self._combat_manager, 'process_combat_round')) \
                           and hasattr(self._combat_manager, 'end_combat') and callable(getattr(self._combat_manager, 'end_combat')):
                          active_combats_in_guild = self._combat_manager.get_active_combats_by_guild(guild_id)
                          combats_to_end_ids: List[str] = []
                          if active_combats_in_guild:
                               for combat in list(active_combats_in_guild):
                                    if not combat.is_active: continue
                                    combat_finished_signal = await self._combat_manager.process_combat_round(combat_id=combat.id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                                    if combat_finished_signal: combats_to_end_ids.append(combat.id)
                          for combat_id in combats_to_end_ids:
                                await self._combat_manager.end_combat(combat_id=combat_id, guild_id=guild_id, winners=[], context=guild_tick_context) # Added winners and context
                      else:
                           print(f"WorldSimulationProcessor: Warning: CombatManager or its required methods not available for tick processing for guild {guild_id}.")
                 except Exception as e: print(f"WorldSimulationProcessor: Error during CombatManager tick processing for guild {guild_id}: {e}"); traceback.print_exc()

             if self._character_manager and self._character_action_processor:
                  try:
                       if hasattr(self._character_manager, 'get_entities_with_active_action') and callable(getattr(self._character_manager, 'get_entities_with_active_action')) \
                          and hasattr(self._character_action_processor, 'process_tick') and callable(getattr(self._character_action_processor, 'process_tick')):
                            characters_with_active_action = self._character_manager.get_entities_with_active_action(guild_id)
                            if characters_with_active_action:
                                for char_id in list(characters_with_active_action):
                                     await self._character_action_processor.process_tick(entity_id=char_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during CharacterActionProcessor process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             if self._npc_manager and self._npc_action_processor: # Check NpcActionProcessor
                  try:
                       if hasattr(self._npc_manager, 'get_entities_with_active_action') and callable(getattr(self._npc_manager, 'get_entities_with_active_action')) \
                          and hasattr(self._npc_action_processor, 'process_tick') and callable(getattr(self._npc_action_processor, 'process_tick')):
                            npcs_with_active_action = self._npc_manager.get_entities_with_active_action(guild_id)
                            if npcs_with_active_action:
                                for npc_id in list(npcs_with_active_action):
                                     await self._npc_action_processor.process_tick(entity_id=npc_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during NpcActionProcessor process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             if self._party_manager and self._party_action_processor:
                  try:
                       if hasattr(self._party_manager, 'get_parties_with_active_action') and callable(getattr(self._party_manager, 'get_parties_with_active_action')) \
                          and hasattr(self._party_action_processor, 'process_tick') and callable(getattr(self._party_action_processor, 'process_tick')):
                            parties_with_active_action = self._party_manager.get_parties_with_active_action(guild_id)
                            if parties_with_active_action:
                                 for party_id in list(parties_with_active_action):
                                      await self._party_action_processor.process_tick(party_id=party_id, guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during PartyActionProcessor process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             if self._item_manager and hasattr(self._item_manager, 'process_tick') and callable(getattr(self._item_manager, 'process_tick')):
                  try: await self._item_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during ItemManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             if self._location_manager and hasattr(self._location_manager, 'process_tick') and callable(getattr(self._location_manager, 'process_tick')):
                  try: await self._location_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during LocationManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             if self._economy_manager and hasattr(self._economy_manager, 'process_tick') and callable(getattr(self._economy_manager, 'process_tick')):
                  try: await self._economy_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                  except Exception as e: print(f"WorldSimulationProcessor: Error during EconomyManager process_tick for guild {guild_id}: {e}"); traceback.print_exc()

             if self._global_npc_manager and hasattr(self._global_npc_manager, 'process_tick') and callable(getattr(self._global_npc_manager, 'process_tick')):
                 try:
                     await self._global_npc_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                 except Exception as e:
                     print(f"WorldSimulationProcessor: Error during GlobalNpcManager process_tick for guild {guild_id}: {e}")
                     traceback.print_exc()

             if self._mobile_group_manager and hasattr(self._mobile_group_manager, 'process_tick') and callable(getattr(self._mobile_group_manager, 'process_tick')):
                 try:
                     await self._mobile_group_manager.process_tick(guild_id=guild_id, game_time_delta=game_time_delta, **guild_tick_context)
                 except Exception as e:
                     print(f"WorldSimulationProcessor: Error during MobileGroupManager process_tick for guild {guild_id}: {e}")
                     traceback.print_exc()

             if self._event_manager and self._event_stage_processor:
                  if hasattr(self._event_manager, 'get_active_events_by_guild') and callable(getattr(self._event_manager, 'get_active_events_by_guild')) \
                     and hasattr(self, '_check_event_for_auto_transition') and callable(getattr(self, '_check_event_for_auto_transition')) \
                     and hasattr(self._event_stage_processor, 'advance_stage') and callable(getattr(self._event_stage_processor, 'advance_stage')):
                       active_events: List["Event"] = self._event_manager.get_active_events_by_guild(guild_id)
                       events_to_auto_advance_info: List[Tuple["Event", str]] = []
                       for event_item in list(active_events): # Renamed event to event_item
                            if not event_item.is_active or event_item.current_stage_id == 'event_end': continue
                            next_stage_id_auto = self._check_event_for_auto_transition(event_item)
                            if next_stage_id_auto:
                                 event_name = getattr(event_item, 'name', 'N/A') # Safe access
                                 print(f"WorldSimulationProcessor: Event {event_item.id} ('{event_name}') for guild {guild_id}: Auto-transition condition met from stage '{event_item.current_stage_id}' to stage '{next_stage_id_auto}'. Scheduling transition.")
                                 events_to_auto_advance_info.append((event_item, next_stage_id_auto))
                       for event_to_advance, target_stage_id_auto in events_to_auto_advance_info:
                            try:
                                 if event_to_advance.channel_id is None:
                                      print(f"WorldSimulationProcessor: Warning: Cannot auto-advance event {event_to_advance.id} for guild {guild_id}. Event has no channel_id for notifications.")
                                      continue
                                 event_channel_callback = self._send_callback_factory(event_to_advance.channel_id)
                                 await self._event_stage_processor.advance_stage(
                                     event=event_to_advance, target_stage_id=target_stage_id_auto,
                                     send_message_callback=event_channel_callback,
                                     **guild_tick_context,
                                     transition_context={"trigger": "auto_advance", "from_stage_id": event_to_advance.current_stage_id, "to_stage_id": target_stage_id_auto}
                                 )
                                 print(f"WorldSimulationProcessor: Auto-transition to '{target_stage_id_auto}' completed for event {event_to_advance.id} in guild {guild_id}.")
                            except Exception as e: print(f"WorldSimulationProcessor: Error during auto-transition execution for event {event_to_advance.id} to stage {target_stage_id_auto} in guild {guild_id}: {e}"); traceback.print_exc()
                  else:
                       print(f"WorldSimulationProcessor: Warning: EventManager or EventStageProcessor or their required methods not available for auto-transition check for guild {guild_id}.")

             if self._event_manager and hasattr(self._event_manager, 'get_active_events_by_guild') and callable(getattr(self._event_manager, 'get_active_events_by_guild')):
                  events_already_ending_ids: List[str] = [ event.id for event in list(self._event_manager.get_active_events_by_guild(guild_id)) if event.current_stage_id == 'event_end' ]
                  for event_id_to_end in events_already_ending_ids: # Renamed event_id to event_id_to_end
                       await self.end_event(guild_id, event_id_to_end)

             if self._persistence_manager:
                  should_auto_save_logic_here = False
                  if should_auto_save_logic_here:
                       try:
                            await self._persistence_manager.save_game_state(guild_ids=[guild_id], **guild_tick_context)
                       except Exception as e: print(f"WorldSimulationProcessor: Error during auto-save for guild {guild_id}: {e}"); traceback.print_exc()

    async def generate_dynamic_event_narrative(self, guild_id: str, event_concept: str, related_entities: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        if not self._multilingual_prompt_generator:
            print("WorldSimulationProcessor ERROR: MultilingualPromptGenerator is not available.")
            return None
        if not self._openai_service:
            print("WorldSimulationProcessor ERROR: OpenAIService is not available.")
            return None
        if not self._settings:
            print("WorldSimulationProcessor ERROR: Settings are not available.")
            return None

        print(f"WorldSimulationProcessor: Generating AI narrative for event concept '{event_concept}' in guild {guild_id}.")

        # Ensure context_collector is available on multilingual_prompt_generator
        if not hasattr(self._multilingual_prompt_generator, 'context_collector') or \
           not hasattr(self._multilingual_prompt_generator.context_collector, 'get_full_context') or \
           not callable(getattr(self._multilingual_prompt_generator.context_collector, 'get_full_context')):
            print("WorldSimulationProcessor ERROR: MultilingualPromptGenerator.context_collector.get_full_context is not available or not callable.")
            return None

        context_data = await self._multilingual_prompt_generator.context_collector.get_full_context( # Added await
            guild_id=guild_id,
        )

        specific_task_prompt = f"""
        Generate a rich, atmospheric narrative or dynamic event description for the game world.
        Event Concept/Narrative Idea: {event_concept}
        Potentially involved entities (use context for them if provided): {related_entities if related_entities else "General world atmosphere"}

        The output should include:
        - title_i18n (multilingual title for this event/narrative snippet)
        - description_i18n (multilingual, detailed narrative text. This could describe changes in the world, a developing situation, or an unfolding event.)
        - affected_locations_i18n (optional, list of location names/IDs with multilingual notes on how they are affected)
        - involved_npcs_i18n (optional, list of NPC names/IDs with multilingual notes on their involvement)
        - potential_player_hooks_i18n (optional, multilingual ideas on how players might get involved or notice this)

        Ensure all textual fields are in the specified multilingual JSON format ({{"en": "...", "ru": "..."}}).
        Incorporate elements from the lore and current world state context.
        """

        # Ensure _build_full_prompt_for_openai is available
        if not hasattr(self._multilingual_prompt_generator, '_build_full_prompt_for_openai') or \
           not callable(getattr(self._multilingual_prompt_generator, '_build_full_prompt_for_openai')):
            print("WorldSimulationProcessor ERROR: MultilingualPromptGenerator._build_full_prompt_for_openai is not available or not callable.")
            return None


        prompt_messages = self._multilingual_prompt_generator._build_full_prompt_for_openai(
            specific_task_instruction=specific_task_prompt, # Corrected param name
            context_data=context_data,
            target_languages=["en", "ru"] # Assuming default, or get from context/settings
        )

        system_prompt = prompt_messages["system"]
        user_prompt = prompt_messages["user"]

        ai_settings = self._settings.get("world_event_ai_settings", {})
        max_tokens = ai_settings.get("max_tokens", 1500)
        temperature = ai_settings.get("temperature", 0.7)

        generated_data = await self._openai_service.generate_structured_multilingual_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )

        if generated_data and "error" not in generated_data:
            print(f"WorldSimulationProcessor: Successfully generated AI narrative for '{event_concept}'.")
            return generated_data
        else:
            error_detail = generated_data.get("error") if generated_data else "Unknown error"
            raw_text = generated_data.get("raw_text", "") if generated_data else ""
            print(f"WorldSimulationProcessor ERROR: Failed to generate AI narrative for '{event_concept}'. Error: {error_detail}")
            if raw_text:
                print(f"WorldSimulationProcessor: Raw response from AI was: {raw_text[:500]}...")
            return None

    def _check_event_for_auto_transition(self, event: "Event") -> Optional[str]:
        current_stage_data = getattr(event, 'stages_data', {}).get(event.current_stage_id)
        if not current_stage_data:
             print(f"WorldSimulationProcessor: Warning: _check_event_for_auto_transition: No stage data found for current stage {event.current_stage_id} in event {event.id}.")
             return None

        current_stage_obj: Union["EventStage", Dict[str, Any]] # Allow fallback to dict
        try:
             current_stage_obj = EventStage.model_validate(current_stage_data) # Changed from_dict to model_validate
        except Exception as e:
             print(f"WorldSimulationProcessor: Error creating EventStage from dict for event {event.id}, stage {event.current_stage_id}: {e}")
             traceback.print_exc()
             current_stage_obj = current_stage_data

        auto_transitions_rules: Optional[List[Dict[str, Any]]] = getattr(current_stage_obj, 'auto_transitions', []) if isinstance(current_stage_obj, EventStage) else current_stage_obj.get('auto_transitions', [])

        if isinstance(auto_transitions_rules, list):
            for rule in auto_transitions_rules:
                 if not isinstance(rule, dict): continue

                 rule_type = rule.get('type')
                 if rule_type == 'time_elapsed' and self._time_manager is not None:
                      timer_var = rule.get('state_var')
                      threshold = rule.get('threshold')
                      target_stage_id = rule.get('target_stage')
                      if isinstance(timer_var, str) and timer_var and \
                         threshold is not None and isinstance(threshold, (int, float)) and \
                         isinstance(target_stage_id, str) and target_stage_id:
                           current_timer_value: Any = getattr(event, 'state_variables', {}).get(timer_var, 0.0)
                           if isinstance(current_timer_value, (int, float)) and current_timer_value >= threshold:
                                return target_stage_id
                 elif rule_type == 'state_variable_threshold':
                      variable_name = rule.get('variable')
                      operator = rule.get('operator')
                      value_threshold = rule.get('value')
                      target_stage_id = rule.get('target_stage')
                      if isinstance(variable_name, str) and variable_name and \
                         isinstance(operator, str) and operator in ['<', '<=', '==', '>', '>=', '!='] and \
                         value_threshold is not None and \
                         isinstance(target_stage_id, str) and target_stage_id:
                           current_var_value: Any = getattr(event, 'state_variables', {}).get(variable_name)
                           if current_var_value is not None:
                                condition_met = False
                                try:
                                    if operator in ['<', '<=', '>', '>='] and (not isinstance(current_var_value, (int, float)) or not isinstance(value_threshold, (int, float))):
                                         pass
                                    else:
                                         if operator == "<":   condition_met = current_var_value < value_threshold
                                         elif operator == "<=": condition_met = current_var_value <= value_threshold
                                         elif operator == "==": condition_met = current_var_value == value_threshold
                                         elif operator == ">":   condition_met = current_var_value > value_threshold
                                         elif operator == ">=": condition_met = current_var_value >= value_threshold
                                         elif operator == "!=": condition_met = current_var_value != value_threshold
                                    if condition_met:
                                         return target_stage_id
                                except TypeError as e:
                                     print(f"WorldSimulationProcessor: Warning: _check_event_for_auto_transition: TypeError comparing variable '{variable_name}' ({type(current_var_value).__name__}) with threshold ({type(value_threshold).__name__}) for event {event.id}: {e}")
                                except Exception as e:
                                     print(f"WorldSimulationProcessor: Error during 'state_variable_threshold' check for variable '{variable_name}' for event {event.id}: {e}")
                                     traceback.print_exc()
        return None

    def _get_managers_for_rule_engine_context(self) -> Dict[str, Any]:
         return {
             'character_manager': self._character_manager,
             'event_manager': self._event_manager,
             'location_manager': self._location_manager,
             'rule_engine': self._rule_engine,
             'openai_service': self._openai_service,
             'event_stage_processor': self._event_stage_processor,
             'event_action_processor': self._event_action_processor,
             'persistence_manager': self._persistence_manager,
             'send_callback_factory': self._send_callback_factory,
             'character_action_processor': self._character_action_processor,
             'party_action_processor': self._party_action_processor,
             'npc_action_processor': self._npc_action_processor,
             'npc_manager': self._npc_manager,
             'combat_manager': self._combat_manager,
             'item_manager': self._item_manager,
             'time_manager': self._time_manager,
             'status_manager': self._status_manager,
             'crafting_manager': self._crafting_manager,
             'economy_manager': self._economy_manager,
             'party_manager': self._party_manager,
             'global_npc_manager': self._global_npc_manager,
             'mobile_group_manager': self._mobile_group_manager,
         }
# Конец класса WorldSimulationProcessor
