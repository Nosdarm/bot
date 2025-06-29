# bot/game/party_processors/party_action_processor.py

import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, cast, Union
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
    from bot.game.guild_game_state_manager import GuildGameStateManager # For type hint
    from bot.game.models.guild_game_state import GuildGameState # For type hint


SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

logger = logging.getLogger(__name__)

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
                 item_manager: Optional["ItemManager"] = None,
                 status_manager: Optional["StatusManager"] = None,
                 event_stage_processor: Optional["EventStageProcessor"] = None,
                 game_log_manager: Optional["GameLogManager"] = None,
                 game_manager: Optional["GameManager"] = None
                ):
        logger.info("Initializing PartyActionProcessor...")
        self._party_manager = party_manager
        self._send_callback_factory = send_callback_factory
        self._rule_engine = rule_engine
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._time_manager = time_manager
        self._combat_manager = combat_manager
        self._item_manager = item_manager
        self._status_manager = status_manager
        self._event_stage_processor = event_stage_processor
        self._game_log_manager = game_log_manager
        self._game_manager = game_manager
        logger.info("PartyActionProcessor initialized.")

    async def start_party_action(self, guild_id: str, party_id: str, action_data: Dict[str, Any], **kwargs) -> bool:
        logger.info(f"PAP: Start action for party {party_id} in guild {guild_id}: {action_data.get('type')}")
        party = self._party_manager.get_party(guild_id, party_id)
        if not party:
             logger.error(f"PAP: Error starting action: Party {party_id} not found in guild {guild_id}.")
             return False

        action_type = action_data.get('type')
        if not action_type:
             logger.error(f"PAP: Error starting action: action_data missing 'type'.")
             await self._notify_party(guild_id, party_id, "❌ Failed to start group action: Action type missing.")
             return False

        if self._party_manager.is_party_busy(guild_id, party_id): # Added guild_id
             logger.info(f"PAP: Party {party_id} in guild {guild_id} is busy.")
             await self._notify_party(guild_id, party_id, f"❌ Your party is busy and cannot start action '{action_type}'.")
             return False

        start_successful = await self._execute_start_action_logic(guild_id, party_id, action_data, **kwargs)
        if not start_successful: return False

        party = self._party_manager.get_party(guild_id, party_id) # Re-fetch
        if not party:
             logger.error(f"PAP: Error starting action post-logic: Party {party_id} not found in guild {guild_id}.")
             return False

        party.current_action = action_data
        self._party_manager.mark_party_dirty(guild_id, party_id)

        if hasattr(self._party_manager, 'add_party_to_active_set') and callable(getattr(self._party_manager, 'add_party_to_active_set')):
            self._party_manager.add_party_to_active_set(guild_id, party_id)
        elif hasattr(self._party_manager, '_parties_with_active_action') and isinstance(self._party_manager._parties_with_active_action, dict):
            self._party_manager._parties_with_active_action.setdefault(guild_id, set()).add(party_id) # type: ignore[attr-defined]
        else:
            logger.warning(f"PAP: Could not add party {party_id} to active set in PartyManager for guild {guild_id}.")

        logger.info(f"PAP: Party {party_id} action '{action_data['type']}' started. Duration: {action_data.get('total_duration', 0.0):.1f}. Marked dirty.")
        return True

    async def _execute_start_action_logic(self, guild_id: str, party_id: str, action_data: Dict[str, Any], **kwargs) -> bool:
         party = self._party_manager.get_party(guild_id, party_id)
         if not party: return False
         action_type = action_data.get('type')
         logger.info(f"PAP: Executing start logic for party {party_id}, guild {guild_id}, action '{action_type}'.")
         # ... (rest of the logic, ensure managers are checked before use)
         calculated_duration = 0.0 # Default
         if self._rule_engine and hasattr(self._rule_engine, 'calculate_party_action_duration') and callable(getattr(self._rule_engine, 'calculate_party_action_duration')):
             calculated_duration = await self._rule_engine.calculate_party_action_duration(action_type, party=party, action_context=action_data, **kwargs)
         action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
         # ...
         return True


    async def add_party_action_to_queue(self, guild_id: str, party_id: str, action_data: Dict[str, Any], **kwargs) -> bool:
        logger.info(f"PAP: Add action to queue for party {party_id}, guild {guild_id}: {action_data.get('type')}")
        party = self._party_manager.get_party(guild_id, party_id)
        if not party:
             logger.error(f"PAP: Error adding to queue: Party {party_id} not found in guild {guild_id}.")
             return False
        # ... (rest of the logic, ensure managers are checked before use)
        if not hasattr(party, 'action_queue') or not isinstance(party.action_queue, list):
             party.action_queue = []
        party.action_queue.append(action_data)
        self._party_manager.mark_party_dirty(guild_id, party_id)

        if hasattr(self._party_manager, 'add_party_to_active_set') and callable(getattr(self._party_manager, 'add_party_to_active_set')):
            self._party_manager.add_party_to_active_set(guild_id, party_id)
        elif hasattr(self._party_manager, '_parties_with_active_action') and isinstance(self._party_manager._parties_with_active_action, dict): # type: ignore[attr-defined]
            self._party_manager._parties_with_active_action.setdefault(guild_id, set()).add(party_id) # type: ignore[attr-defined]
        else:
            logger.warning(f"PAP: Could not add party {party_id} to active set in PartyManager (queue) for guild {guild_id}.")

        logger.info(f"PAP: Action '{action_data.get('type')}' added to queue for party {party_id}. Queue: {len(party.action_queue)}. Marked dirty.")
        return True

    async def process_tick(self, guild_id: str, party_id: str, game_time_delta: float, **kwargs) -> None:
        party = self._party_manager.get_party(guild_id, party_id)
        if not party or (getattr(party, 'current_action', None) is None and (not hasattr(party, 'action_queue') or not getattr(party, 'action_queue'))):
            if hasattr(self._party_manager, 'remove_party_from_active_set') and callable(getattr(self._party_manager, 'remove_party_from_active_set')):
                self._party_manager.remove_party_from_active_set(guild_id, party_id)
            elif hasattr(self._party_manager, '_parties_with_active_action') and isinstance(self._party_manager._parties_with_active_action, dict): # type: ignore[attr-defined]
                 cast(Dict[str, Set[str]], self._party_manager._parties_with_active_action).get(guild_id, set()).discard(party_id) # type: ignore[attr-defined]
            return
        # ... (rest of the logic)
        current_action = getattr(party, 'current_action', None)
        action_completed = False
        if current_action:
            duration = float(current_action.get('total_duration', 0.0) or 0.0)
            progress = float(current_action.get('progress', 0.0) or 0.0)
            current_action['progress'] = progress + game_time_delta
            party.current_action = current_action # Ensure current_action is updated on party
            self._party_manager.mark_party_dirty(guild_id, party_id)
            if current_action['progress'] >= duration: action_completed = True

        if action_completed and current_action:
            await self.complete_party_action(guild_id, party_id, current_action, **kwargs)

        # Check again after completion if queue is empty
        if getattr(party, 'current_action', None) is None and (not hasattr(party, 'action_queue') or not getattr(party, 'action_queue')):
            if hasattr(self._party_manager, 'remove_party_from_active_set') and callable(getattr(self._party_manager, 'remove_party_from_active_set')):
                self._party_manager.remove_party_from_active_set(guild_id, party_id)
            elif hasattr(self._party_manager, '_parties_with_active_action') and isinstance(self._party_manager._parties_with_active_action, dict): # type: ignore[attr-defined]
                cast(Dict[str, Set[str]], self._party_manager._parties_with_active_action).get(guild_id, set()).discard(party_id) # type: ignore[attr-defined]


    async def complete_party_action(self, guild_id: str, party_id: str, completed_action_data: Dict[str, Any], **kwargs) -> None:
        logger.info(f"PAP: Completing action for party {party_id}, guild {guild_id}: {completed_action_data.get('type')}")
        party = self._party_manager.get_party(guild_id, party_id)
        if not party: logger.error(f"PAP: Error completing action: Party {party_id} not found in guild {guild_id}."); return

        action_type = completed_action_data.get('type')
        # Ensure item_manager and status_manager are available if needed by actions
        item_manager = kwargs.get('item_manager', self._item_manager)
        status_manager = kwargs.get('status_manager', self._status_manager)

        # ... (rest of the logic, ensure managers like location_manager are checked before use)
        if action_type == 'move':
            target_location_id = completed_action_data.get('callback_data', {}).get('target_location_id')
            old_location_id = getattr(party, 'current_location_id', None)
            if target_location_id and self._location_manager and \
               hasattr(self._location_manager, 'handle_entity_arrival') and callable(getattr(self._location_manager, 'handle_entity_arrival')) and \
               hasattr(self._location_manager, 'handle_entity_departure') and callable(getattr(self._location_manager, 'handle_entity_departure')):
                party.current_location_id = target_location_id
                self._party_manager.mark_party_dirty(guild_id, party_id)
                if old_location_id: await self._location_manager.handle_entity_departure(guild_id, old_location_id, party_id, 'Party', **kwargs)
                await self._location_manager.handle_entity_arrival(guild_id, target_location_id, party_id, 'Party', **kwargs)
            else: logger.error(f"PAP: Error completing move for party {party_id}: LocationManager or methods missing.")

        party.current_action = None
        self._party_manager.mark_party_dirty(guild_id, party_id)
        action_queue = getattr(party, 'action_queue', []) or []
        if action_queue:
             next_action_data = action_queue.pop(0)
             self._party_manager.mark_party_dirty(guild_id, party_id)
             logger.info(f"PAP: Party {party_id} starting next action from queue: {next_action_data.get('type')}.")
             await self.start_party_action(guild_id, party_id, next_action_data, **kwargs)


    async def _notify_party(self, guild_id: str, party_id: str, message: str) -> None:
         # ... (ensure character_manager is checked)
         if not self._character_manager: logger.warning(f"PAP: Cannot notify party {party_id}. CharacterManager not set."); return
         # ...
         pass # Rest of the implementation

    async def gm_force_end_party_turn(self, guild_id: str, context: Dict[str, Any]) -> Union[str, Dict[str,Any]]:
        game_mngr = cast(Optional["GameManager"], context.get("game_manager"))
        if not game_mngr: return "Error: GameManager not found."

        character_mngr = cast(Optional["CharacterManager"], getattr(game_mngr, 'character_manager', None))
        party_mngr = cast(Optional["PartyManager"], getattr(game_mngr, 'party_manager', None))
        turn_processing_service = cast(Optional["TurnProcessingService"], getattr(game_mngr, 'turn_processing_service', None))

        if not all([character_mngr, party_mngr, turn_processing_service]):
            return "Error: Core managers not found in GameManager."

        # ... (rest of the logic, ensure guild_game_state_manager and its methods are checked)
        guild_game_state_manager = cast(Optional["GuildGameStateManager"], getattr(game_mngr, 'guild_game_state_manager', None))
        active_party_id: Optional[str] = None
        if guild_game_state_manager and hasattr(guild_game_state_manager, 'get_guild_game_state') and callable(getattr(guild_game_state_manager, 'get_guild_game_state')):
            guild_game_state = guild_game_state_manager.get_guild_game_state(guild_id)
            if guild_game_state and hasattr(guild_game_state, 'state_variables') and isinstance(guild_game_state.state_variables, dict):
                active_party_id = guild_game_state.state_variables.get("active_party_id")
        # ...
        return {"status": "completed", "message": "Forced party turn end (mocked).", "details": {}}
