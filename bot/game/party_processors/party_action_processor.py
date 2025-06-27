# bot/game/party_processors/party_action_processor.py

import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from bot.game.models.party import Party
    from bot.game.managers.party_manager import PartyManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.managers.game_manager import GameManager
    from bot.services.turn_processing_service import TurnProcessingService


SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

logger = logging.getLogger(__name__) # Initialize logger

class PartyActionProcessor:
    def __init__(self,
                 party_manager: "PartyManager",
                 send_callback_factory: SendCallbackFactory,
                 rule_engine: Optional["RuleEngine"] = None,
                 location_manager: Optional["LocationManager"] = None,
                 character_manager: Optional["CharacterManager"] = None,
                 npc_manager: Optional["NpcManager"] = None,
                 time_manager: Optional["TimeManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                 item_manager: Optional["ItemManager"] = None, # Added ItemManager
                 status_manager: Optional["StatusManager"] = None, # Added StatusManager
                 event_stage_processor: Optional["EventStageProcessor"] = None,
                 game_log_manager: Optional["GameLogManager"] = None,
                 # Added game_manager to access other managers if not directly passed
                 game_manager: Optional["GameManager"] = None
                ):
        logger.info("Initializing PartyActionProcessor...") # Use logger
        self._party_manager = party_manager
        self._send_callback_factory = send_callback_factory
        self._rule_engine = rule_engine
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._time_manager = time_manager
        self._combat_manager = combat_manager
        self._item_manager = item_manager # Store ItemManager
        self._status_manager = status_manager # Store StatusManager
        self._event_stage_processor = event_stage_processor
        self._game_log_manager = game_log_manager
        self._game_manager = game_manager # Store GameManager
        logger.info("PartyActionProcessor initialized.") # Use logger

    async def start_party_action(self, guild_id: str, party_id: str, action_data: Dict[str, Any], **kwargs) -> bool: # Added guild_id
        logger.info(f"PartyActionProcessor: Attempting to start party action for party {party_id} in guild {guild_id}: {action_data.get('type')}") # Use logger
        party = self._party_manager.get_party(guild_id, party_id)
        if not party:
             logger.error(f"PartyActionProcessor: Error starting party action: Party {party_id} not found in guild {guild_id}.") # Use logger
             return False

        action_type = action_data.get('type')
        if not action_type:
             logger.error(f"PartyActionProcessor: Error starting party action: action_data is missing 'type'.") # Use logger
             await self._notify_party(guild_id, party_id, f"❌ Failed to start group action: Action type is missing.")
             return False

        if self._party_manager.is_party_busy(guild_id, party_id):
             logger.info(f"PartyActionProcessor: Party {party_id} in guild {guild_id} is busy. Cannot start new action directly.") # Use logger
             await self._notify_party(guild_id, party_id, f"❌ Your party is busy and cannot start action '{action_type}'.")
             return False

        start_successful = await self._execute_start_action_logic(guild_id, party_id, action_data, **kwargs)
        if not start_successful:
             return False

        party = self._party_manager.get_party(guild_id, party_id) # Re-fetch party
        if not party:
             logger.error(f"PartyActionProcessor: Error starting party action after start logic: Party {party_id} not found in guild {guild_id}.") # Use logger
             return False

        party.current_action = action_data
        self._party_manager.mark_party_dirty(guild_id, party_id) # Pass guild_id

        # Access _parties_with_active_action safely
        if hasattr(self._party_manager, '_parties_with_active_action') and isinstance(self._party_manager._parties_with_active_action, dict):
            self._party_manager._parties_with_active_action.setdefault(guild_id, set()).add(party_id)
        else:
            logger.warning(f"PartyActionProcessor: _parties_with_active_action not found or not a dict in PartyManager for guild {guild_id}.")


        logger.info(f"PartyActionProcessor: Party {party_id} action '{action_data['type']}' started. Duration: {action_data.get('total_duration', 0.0):.1f}. Marked as dirty.") # Use logger
        return True

    async def _execute_start_action_logic(self, guild_id: str, party_id: str, action_data: Dict[str, Any], **kwargs) -> bool:
         party = self._party_manager.get_party(guild_id, party_id)
         if not party: return False

         action_type = action_data.get('type')
         logger.info(f"PartyActionProcessor: Executing start logic for party {party_id} in guild {guild_id}, action type '{action_type}'.") # Use logger

         time_manager = kwargs.get('time_manager', self._time_manager)
         rule_engine = kwargs.get('rule_engine', self._rule_engine)
         location_manager = kwargs.get('location_manager', self._location_manager)

         calculated_duration = action_data.get('total_duration', 0.0)
         if rule_engine and hasattr(rule_engine, 'calculate_party_action_duration') and callable(getattr(rule_engine, 'calculate_party_action_duration')):
              try:
                   calculated_duration = await rule_engine.calculate_party_action_duration(action_type, party=party, action_context=action_data, **kwargs)
              except Exception as e:
                   logger.error(f"PartyActionProcessor: Error calculating duration for party action type '{action_type}' for party {party_id}: {e}", exc_info=True) # Use logger
                   calculated_duration = action_data.get('total_duration', 0.0)
         try:
             action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
         except (ValueError, TypeError):
              logger.warning(f"PartyActionProcessor: Calculated duration is not a valid number for party action type '{action_type}'. Setting to 0.0.") # Use logger
              action_data['total_duration'] = 0.0

         if action_type == 'move':
              target_location_id = action_data.get('target_location_id')
              if not target_location_id:
                   logger.error(f"PartyActionProcessor: Error starting party move action: Missing target_location_id in action_data.") # Use logger
                   await self._notify_party(guild_id, party_id, f"❌ Move error: Target location is missing.")
                   return False
              if location_manager and hasattr(location_manager, 'get_location_static') and callable(getattr(location_manager, 'get_location_static')) and await location_manager.get_location_static(guild_id, target_location_id) is None:
                  logger.error(f"PartyActionProcessor: Error starting party move action: Target location '{target_location_id}' does not exist.") # Use logger
                  await self._notify_party(guild_id, party_id, f"❌ Move error: Location '{target_location_id}' does not exist.")
                  return False
              if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                  action_data['callback_data'] = {}
              action_data['callback_data']['target_location_id'] = target_location_id
         else:
              if 'total_duration' not in action_data or action_data['total_duration'] is None:
                   logger.warning(f"PartyActionProcessor: Party action type '{action_type}' has no total_duration specified. Setting to 0.0.") # Use logger
                   action_data['total_duration'] = 0.0
              try: action_data['total_duration'] = float(action_data['total_duration'])
              except (ValueError, TypeError): action_data['total_duration'] = 0.0

         if time_manager and hasattr(time_manager, 'get_current_game_time') and callable(getattr(time_manager, 'get_current_game_time')):
              action_data['start_game_time'] = time_manager.get_current_game_time()
         else:
              logger.warning(f"PartyActionProcessor: Cannot get current game time for party action '{action_type}'. TimeManager not available or method missing. Start time is None.") # Use logger
              action_data['start_game_time'] = None
         action_data['progress'] = 0.0
         logger.info(f"PartyActionProcessor: Start logic successful for party {party_id}, action type '{action_type}'. Duration: {action_data.get('total_duration', 0.0):.1f}") # Use logger
         return True

    async def add_party_action_to_queue(self, guild_id: str, party_id: str, action_data: Dict[str, Any], **kwargs) -> bool: # Added guild_id
        logger.info(f"PartyActionProcessor: Attempting to add party action to queue for party {party_id} in guild {guild_id}: {action_data.get('type')}") # Use logger
        party = self._party_manager.get_party(guild_id, party_id)
        if not party:
             logger.error(f"PartyActionProcessor: Error adding action to queue: Party {party_id} not found in guild {guild_id}.") # Use logger
             return False

        action_type = action_data.get('type')
        if not action_type:
             logger.error(f"PartyActionProcessor: Error adding action to queue: action_data is missing 'type'.") # Use logger
             await self._notify_party(guild_id, party_id, f"❌ Failed to add action to queue: Action type is missing.")
             return False

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        location_manager = kwargs.get('location_manager', self._location_manager)

        if action_type == 'move':
             target_location_id = action_data.get('target_location_id')
             if not target_location_id:
                  logger.error(f"PartyActionProcessor: Error adding party move action to queue: Missing target_location_id in action_data.") # Use logger
                  await self._notify_party(guild_id, party_id, f"❌ Failed to add move to queue: Target location is missing.")
                  return False
             if location_manager and hasattr(location_manager, 'get_location_static') and callable(getattr(location_manager, 'get_location_static')) and await location_manager.get_location_static(guild_id, target_location_id) is None:
                 logger.error(f"PartyActionProcessor: Error adding party move action to queue: Target location '{target_location_id}' does not exist.") # Use logger
                 await self._notify_party(guild_id, party_id, f"❌ Failed to add move to queue: Location '{target_location_id}' does not exist.")
                 return False
             if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                 action_data['callback_data'] = {}
             action_data['callback_data']['target_location_id'] = action_data.get('target_location_id')

        calculated_duration = action_data.get('total_duration', 0.0)
        if rule_engine and hasattr(rule_engine, 'calculate_party_action_duration') and callable(getattr(rule_engine, 'calculate_party_action_duration')):
             try:
                  calculated_duration = await rule_engine.calculate_party_action_duration(action_type, party=party, action_context=action_data, **kwargs)
             except Exception as e:
                  logger.error(f"PartyActionProcessor: Error calculating duration for party action type '{action_type}' for party {party_id} in queue: {e}", exc_info=True) # Use logger
                  calculated_duration = action_data.get('total_duration', 0.0)
        try: action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
        except (ValueError, TypeError): action_data['total_duration'] = 0.0
        action_data['start_game_time'] = None
        action_data['progress'] = 0.0

        if not hasattr(party, 'action_queue') or not isinstance(party.action_queue, list):
             logger.warning(f"PartyActionProcessor: Party {party_id} model has no 'action_queue' list or it's incorrect type. Creating empty list.") # Use logger
             party.action_queue = []
        party.action_queue.append(action_data)
        self._party_manager.mark_party_dirty(guild_id, party_id) # Pass guild_id
        if hasattr(self._party_manager, '_parties_with_active_action') and isinstance(self._party_manager._parties_with_active_action, dict):
            self._party_manager._parties_with_active_action.setdefault(guild_id, set()).add(party_id)
        else:
            logger.warning(f"PartyActionProcessor: _parties_with_active_action not found or not a dict in PartyManager for guild {guild_id}.")

        logger.info(f"PartyActionProcessor: Action '{action_data['type']}' added to queue for party {party_id}. Queue length: {len(party.action_queue)}. Marked as dirty.") # Use logger
        return True

    async def process_tick(self, guild_id: str, party_id: str, game_time_delta: float, **kwargs) -> None: # Added guild_id to signature
        party = self._party_manager.get_party(guild_id, party_id)
        if not party or (getattr(party, 'current_action', None) is None and (not hasattr(party, 'action_queue') or not getattr(party, 'action_queue'))):
             if hasattr(self._party_manager, '_parties_with_active_action') and isinstance(self._party_manager._parties_with_active_action, dict):
                 self._party_manager._parties_with_active_action.get(guild_id, set()).discard(party_id)
             return

        current_action = getattr(party, 'current_action', None)
        action_completed = False
        if current_action is not None:
             duration = current_action.get('total_duration', 0.0)
             if duration is None:
                 pass
             elif duration <= 0:
                  logger.info(f"PartyActionProcessor: Party {party_id} action '{current_action.get('type', 'Unknown')}' is instant (duration <= 0). Marking as completed.") # Use logger
                  action_completed = True
             else:
                  progress = current_action.get('progress', 0.0)
                  if not isinstance(progress, (int, float)):
                       logger.warning(f"PartyActionProcessor: Progress for party {party_id} action '{current_action.get('type', 'Unknown')}' is not a number ({progress}). Resetting to 0.0.") # Use logger
                       progress = 0.0
                  current_action['progress'] = progress + game_time_delta
                  party.current_action = current_action
                  self._party_manager.mark_party_dirty(guild_id, party_id) # Pass guild_id
                  if current_action['progress'] >= duration:
                       logger.info(f"PartyActionProcessor: Party {party_id} action '{current_action.get('type', 'Unknown')}' completed.") # Use logger
                       action_completed = True
        if action_completed and current_action is not None:
             await self.complete_party_action(guild_id, party_id, current_action, **kwargs)
        if getattr(party, 'current_action', None) is None and (not hasattr(party, 'action_queue') or not getattr(party, 'action_queue')):
            if hasattr(self._party_manager, '_parties_with_active_action') and isinstance(self._party_manager._parties_with_active_action, dict):
                self._party_manager._parties_with_active_action.get(guild_id, set()).discard(party_id)

    async def complete_party_action(self, guild_id: str, party_id: str, completed_action_data: Dict[str, Any], **kwargs) -> None:
        logger.info(f"PartyActionProcessor: Completing action for party {party_id} in guild {guild_id}: {completed_action_data.get('type')}") # Use logger
        party = self._party_manager.get_party(guild_id, party_id)
        if not party:
             logger.error(f"PartyActionProcessor: Error completing action: Party {party_id} not found in guild {guild_id}.") # Use logger
             return

        action_type = completed_action_data.get('type')
        callback_data = completed_action_data.get('callback_data', {})
        location_manager = kwargs.get('location_manager', self._location_manager)

        try:
            if action_type == 'move':
                 target_location_id = callback_data.get('target_location_id')
                 old_location_id = getattr(party, 'current_location_id', None)
                 if target_location_id and location_manager and hasattr(location_manager, 'handle_entity_arrival') and callable(getattr(location_manager, 'handle_entity_arrival')) and hasattr(location_manager, 'handle_entity_departure') and callable(getattr(location_manager, 'handle_entity_departure')):
                      logger.info(f"PartyActionProcessor: Updating party {party_id} location in cache from {old_location_id} to {target_location_id}.") # Use logger
                      party.current_location_id = target_location_id
                      self._party_manager.mark_party_dirty(guild_id, party_id) # Pass guild_id
                      if old_location_id:
                           logger.info(f"PartyActionProcessor: Triggering OnExit for location {old_location_id}.") # Use logger
                           await location_manager.handle_entity_departure(guild_id, old_location_id, party_id, 'Party', **kwargs)
                      logger.info(f"PartyActionProcessor: Triggering OnEnter for location {target_location_id}.") # Use logger
                      await location_manager.handle_entity_arrival(guild_id, target_location_id, party_id, 'Party', **kwargs)
                      logger.info(f"PartyActionProcessor: Party {party_id} completed move action to {target_location_id}. Triggers processed.") # Use logger
                 else:
                       logger.error("PartyActionProcessor: Error completing party move action: Required managers/data not available or LocationManager trigger methods missing.") # Use logger
                       await self._notify_party(guild_id, party_id, f"❌ Error completing party move. An internal error occurred.")
            else:
                 logger.warning(f"PartyActionProcessor: Unhandled group action type '{action_type}' completed for party {party_id}. No specific completion logic executed.") # Use logger
                 await self._notify_party(guild_id, party_id, f"Party action '{action_type}' completed.")
        except Exception as e:
            logger.error(f"PartyActionProcessor: ❌ CRITICAL ERROR during party action completion logic for party {party_id} action '{action_type}': {e}", exc_info=True) # Use logger
            await self._notify_party(guild_id, party_id, f"❌ A critical error occurred while completing party action '{action_type}'.")

        party.current_action = None
        self._party_manager.mark_party_dirty(guild_id, party_id) # Pass guild_id
        action_queue = getattr(party, 'action_queue', []) or []
        if action_queue:
             next_action_data = action_queue.pop(0)
             self._party_manager.mark_party_dirty(guild_id, party_id) # Pass guild_id
             logger.info(f"PartyActionProcessor: Party {party_id} starting next action from queue: {next_action_data.get('type')}.") # Use logger
             await self.start_party_action(guild_id, party_id, next_action_data, **kwargs) # Added guild_id

    async def _notify_party(self, guild_id: str, party_id: str, message: str) -> None: # Added guild_id
         if self._send_callback_factory is None:
              logger.warning(f"PartyActionProcessor: Cannot notify party {party_id}. SendCallbackFactory not available.") # Use logger
              return
         party = self._party_manager.get_party(guild_id, party_id) # Pass guild_id
         if not party:
              logger.warning(f"PartyActionProcessor: Cannot notify party {party_id}. Party not found in guild {guild_id}.") # Use logger
              return
         character_manager = getattr(self, '_character_manager', None)
         if not character_manager:
             logger.warning(f"PartyActionProcessor: Cannot notify party {party_id}. CharacterManager not available.") # Use logger
             return

         notified_users: Set[str] = set()
         member_ids = getattr(party, 'player_ids_list', []) or []
         for member_id_str in member_ids:
              member_char = await character_manager.get_character_by_id(guild_id, member_id_str) if hasattr(character_manager, 'get_character_by_id') and callable(getattr(character_manager, 'get_character_by_id')) else None
              if member_char:
                   discord_user_id_val = getattr(member_char, 'discord_user_id', None)
                   party_channel_id_any = getattr(party, 'discord_channel_id', None)
                   party_channel_id = int(party_channel_id_any) if isinstance(party_channel_id_any, (str, int)) and str(party_channel_id_any).isdigit() else None


                   if party_channel_id and isinstance(party_channel_id, int):
                        if party_id not in notified_users:
                            send_callback = self._send_callback_factory(party_channel_id)
                            try:
                                await send_callback(message)
                                notified_users.add(party_id)
                                break
                            except Exception as e:
                                logger.error(f"PartyActionProcessor: Error sending notification to party channel {party_channel_id} for party {party_id}: {e}", exc_info=True) # Use logger
                   elif discord_user_id_val and str(discord_user_id_val) not in notified_users: # Ensure discord_user_id_val is str for set
                        logger.info(f"PartyActionProcessor: No party channel for party {party_id}. Cannot send direct message to user {discord_user_id_val} without channel mapping.") # Use logger
                        # notified_users.add(str(discord_user_id_val))
         if not notified_users:
             logger.warning(f"PartyActionProcessor: No players were notified for party {party_id} action update.") # Use logger

    async def gm_force_end_party_turn(self, guild_id: str, context: Dict[str, Any]): # Added type hint for guild_id and context
        game_mngr: Optional["GameManager"] = context.get("game_manager") # Added type hint
        if not game_mngr:
            return "Error: GameManager not found in context."

        character_mngr: Optional["CharacterManager"] = game_mngr.character_manager # type: ignore[assignment]
        party_mngr: Optional["PartyManager"] = game_mngr.party_manager # type: ignore[assignment]
        turn_processing_service: Optional["TurnProcessingService"] = game_mngr.turn_processing_service # type: ignore[assignment]

        if not character_mngr or not party_mngr or not turn_processing_service:
            return "Error: CharacterManager, PartyManager, or TurnProcessingService not found in GameManager."

        active_party_id: Optional[str] = None
        if hasattr(game_mngr, 'guild_game_state_manager') and callable(getattr(game_mngr, 'guild_game_state_manager')) \
           and hasattr(game_mngr.guild_game_state_manager, 'get_guild_game_state') and callable(getattr(game_mngr.guild_game_state_manager, 'get_guild_game_state')): # Added callable checks
            guild_game_state = game_mngr.guild_game_state_manager.get_guild_game_state(guild_id)
            if guild_game_state and hasattr(guild_game_state, 'state_variables'):
                active_party_id = guild_game_state.state_variables.get("active_party_id")

        party: Optional["Party"] = None # Added type hint
        if active_party_id:
            party = party_mngr.get_party(guild_id, active_party_id)
        if not party:
            all_parties = party_mngr.get_all_parties(guild_id)
            if all_parties:
                party = all_parties[0]
        if not party:
            return "Error: No party found to end turn for."

        player_member_ids: List[str] = getattr(party, 'player_ids_list', []) # Ensure list
        if not player_member_ids:
            return "Error: No player members found in the party."

        player_ids_for_processing: List[str] = []
        for player_id_str in player_member_ids:
            player = await character_mngr.get_character_by_id(guild_id, player_id_str)
            if player:
                setattr(player, 'current_game_status', 'processing_turn')
                await character_mngr.mark_character_dirty(guild_id, player.id)
                player_ids_for_processing.append(str(player.id))
        if not player_ids_for_processing:
             return "Error: No valid player members could be prepared for turn processing."

        party.turn_status = 'processing'
        await party_mngr.mark_party_dirty(guild_id, party.id)
        await asyncio.sleep(0.5)
        result = await turn_processing_service.process_player_turns(player_ids_for_processing, guild_id)
        party.turn_status = 'turn_completed'
        await party_mngr.mark_party_dirty(guild_id, party.id)

        players_with_no_actions = 0
        total_players_processed = len(player_ids_for_processing)
        if result.get("status") == "no_actions":
            players_with_no_actions = total_players_processed
        else:
            processed_action_details = result.get("processed_action_details", [])
            for player_id_str_check in player_ids_for_processing:
                player_had_action = False
                for detail in processed_action_details:
                    if detail.get("player_id") == player_id_str_check and detail.get("actions"):
                        player_had_action = True
                        break
                if not player_had_action:
                    feedback_msgs = result.get("feedback_per_player", {}).get(player_id_str_check, [])
                    if any("no actions taken" in msg.lower() for msg in feedback_msgs):
                         pass
                    elif not any(detail.get("player_id") == player_id_str_check and detail.get("actions") for detail in processed_action_details):
                         players_with_no_actions +=1

        feedback_message = f"DEBUG: Party {party.id} turn processing default message."
        log_details = f"Party ID: {party.id}, Total Players: {total_players_processed}, Players with no actions: {players_with_no_actions}, TPS Status: {result.get('status')}"

        if players_with_no_actions == total_players_processed:
            feedback_message = f"Ход партии {party.id} завершен. Ни для одного из игроков ({total_players_processed}) не было обнаружено действий для обработки."
            logging.info(f"gm_force_end_party_turn: All players had no actions. {log_details}")
        elif players_with_no_actions > 0:
            feedback_message = (
                f"Ход партии {party.id} завершен. "
                f"Для {players_with_no_actions} из {total_players_processed} игроков не было обнаружено действий для обработки."
            )
            logging.info(f"gm_force_end_party_turn: Some players had no actions. {log_details}")
        else:
            feedback_message = f"Ход партии {party.id} успешно обработан для всех {total_players_processed} игроков."
            logging.info(f"gm_force_end_party_turn: Actions processed for all players. {log_details}")
        if result.get("status") == "error":
            logging.error(f"gm_force_end_party_turn: Error during party turn processing. {log_details}. Result: {result}")
            feedback_message += " Обнаружена ошибка в процессе обработки хода партии."

        send_to_command_channel: Optional[Callable[[str], Awaitable[Any]]] = context.get("send_to_command_channel") # Added type hint
        if send_to_command_channel and callable(send_to_command_channel):
            try:
                await send_to_command_channel(feedback_message)
            except Exception as e:
                logging.error(f"gm_force_end_party_turn: Failed to send feedback to command channel. Error: {e}. {log_details}")
                return f"Error: Failed to send feedback: {e}. Original outcome: {feedback_message}"
        else:
            logging.warning(f"gm_force_end_party_turn: 'send_to_command_channel' not in context or not callable. Cannot send feedback. {log_details}")
            return feedback_message
        return {"status": "completed", "message": feedback_message, "details": log_details}
# End of PartyActionProcessor class
