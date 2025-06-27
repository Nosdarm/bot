# bot/game/npc_processors/npc_action_processor.py

import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from bot.game.models.npc import NPC
    from bot.game.models.character import Character
    from bot.game.models.party import Party
    from bot.game.models.combat import Combat
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.crafting_manager import CraftingManager
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.npc_action_handlers.npc_action_handler_registry import NpcActionHandlerRegistry

import logging
logger = logging.getLogger(__name__)

SendChannelMessageCallback = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendChannelMessageCallback]

class NpcActionProcessor:
    def __init__(self,
                 npc_manager: "NpcManager",
                 send_callback_factory: SendCallbackFactory,
                 settings: Dict[str, Any],
                 handler_registry: "NpcActionHandlerRegistry",
                 rule_engine: Optional["RuleEngine"] = None,
                 location_manager: Optional["LocationManager"] = None,
                 character_manager: Optional["CharacterManager"] = None,
                 time_manager: Optional["TimeManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                 status_manager: Optional["StatusManager"] = None,
                 party_manager: Optional["PartyManager"] = None,
                 item_manager: Optional["ItemManager"] = None,
                 economy_manager: Optional["EconomyManager"] = None,
                 dialogue_manager: Optional["DialogueManager"] = None,
                 crafting_manager: Optional["CraftingManager"] = None,
                 event_stage_processor: Optional["EventStageProcessor"] = None,
                 event_action_processor: Optional["EventActionProcessor"] = None,
                 character_action_processor: Optional["CharacterActionProcessor"] = None):
        logger.info("Initializing NpcActionProcessor...")
        self._npc_manager = npc_manager
        self._send_callback_factory = send_callback_factory
        self._settings = settings
        self._handler_registry = handler_registry
        self._rule_engine = rule_engine
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._time_manager = time_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._item_manager = item_manager
        self._economy_manager = economy_manager
        self._dialogue_manager = dialogue_manager
        self._crafting_manager = crafting_manager
        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor
        self._character_action_processor = character_action_processor

        gm_channel_id_setting = self._settings.get('gm_channel_id')
        self._gm_channel_id: Optional[int] = None
        if isinstance(gm_channel_id_setting, (int, str)) and str(gm_channel_id_setting).isdigit():
             try: self._gm_channel_id = int(gm_channel_id_setting)
             except ValueError: logger.warning(f"NpcActionProcessor: Invalid 'gm_channel_id': '{gm_channel_id_setting}'. GM notifications disabled.")
        else: logger.warning(f"NpcActionProcessor: 'gm_channel_id' not found or invalid. GM notifications disabled.")
        logger.info("NpcActionProcessor initialized.")

    async def _notify_gm(self, guild_id: str, message: str, **kwargs: Any) -> None:
         if self._send_callback_factory is None:
              logger.warning(f"NpcActionProcessor: SendCallbackFactory NA. GM Notification (Guild {guild_id}): {message}")
              return
         if self._gm_channel_id is not None:
              send_callback = self._send_callback_factory(self._gm_channel_id)
              try: await send_callback(f"[Guild: {guild_id}] {message}", None)
              except Exception as e: logger.error(f"NpcActionProcessor: Error sending GM notification to channel {self._gm_channel_id} for guild {guild_id}: {e}")
         else: logger.info(f"NpcActionProcessor (Console Fallback): GM Notification (Guild {guild_id}): {message}")

    async def start_action(self, guild_id: str, npc_id: str, action_data: Dict[str, Any], **kwargs: Any) -> bool:
        logger.debug(f"NpcAP: Start action for NPC {npc_id} in guild {guild_id}: {action_data.get('type')}")
        npc = self._npc_manager.get_npc(guild_id, npc_id)
        if not npc:
             logger.error(f"NpcAP: NPC {npc_id} not found in guild {guild_id} to start action.")
             return False
        action_type = action_data.get('type')
        if not action_type:
             logger.error(f"NpcAP: Action data for NPC {npc_id} missing 'type'.")
             await self._notify_gm(guild_id, f"❌ NPC {npc_id}: Failed start action: no type.")
             return False

        is_npc_busy = False
        if hasattr(self._npc_manager, 'is_busy') and callable(getattr(self._npc_manager, 'is_busy')):
            is_npc_busy = self._npc_manager.is_busy(guild_id, npc_id) # Pass guild_id

        if is_npc_busy:
             logger.info(f"NpcAP: NPC {npc_id} is busy. Cannot start action '{action_type}'.")
             await self._notify_gm(guild_id, f"ℹ️ NPC {npc_id}: Attempt to start action '{action_type}' while busy.")
             return False

        start_successful = await self._execute_start_action_logic(guild_id, npc_id, action_data, **kwargs)
        if not start_successful:
             logger.warning(f"NpcAP: Start logic failed for NPC {npc_id} action '{action_type}'.")
             return False

        if hasattr(npc, 'current_action'): npc.current_action = action_data
        else: logger.error(f"NpcAP: NPC model for {npc_id} missing 'current_action'."); return False

        self._npc_manager.mark_npc_dirty(guild_id, npc_id)
        self._npc_manager.add_entity_with_active_action(guild_id, npc_id)

        logger.info(f"NpcAP: NPC {npc_id} action '{action_type}' started. Duration: {action_data.get('total_duration', 0.0):.1f}.")
        await self._notify_gm(guild_id, f"▶️ NPC {npc_id} started: '{action_type}'. Duration: {action_data.get('total_duration', 0.0):.1f} min.")
        return True

    async def _execute_start_action_logic(self, guild_id: str, npc_id: str, action_data: Dict[str, Any], **kwargs: Any) -> bool:
         npc = self._npc_manager.get_npc(guild_id, npc_id)
         if not npc: return False
         action_type = action_data.get('type')
         logger.debug(f"NpcAP: Executing start logic for NPC {npc_id}, action '{action_type}', guild {guild_id}.")

         time_mgr: Optional["TimeManager"] = kwargs.get('time_manager', self._time_manager)
         rule_eng: Optional["RuleEngine"] = kwargs.get('rule_engine', self._rule_engine)
         loc_mgr: Optional["LocationManager"] = kwargs.get('location_manager', self._location_manager)

         calculated_duration = action_data.get('total_duration', 0.0)
         is_valid = True

         if action_type == 'move':
              target_loc_id = action_data.get('target_location_id')
              if not target_loc_id: is_valid = False; await self._notify_gm(guild_id, f"❌ NPC {npc_id} move error: no target_loc_id.")
              elif loc_mgr and hasattr(loc_mgr, 'get_location_static_by_id') and not loc_mgr.get_location_static_by_id(guild_id, target_loc_id): # Corrected method name
                   is_valid = False; await self._notify_gm(guild_id, f"❌ NPC {npc_id} move error: target loc {target_loc_id} not found.")
              if is_valid: action_data.setdefault('callback_data', {})['target_location_id'] = target_loc_id

         # Simplified duration calculation for other types
         if is_valid and rule_eng and hasattr(rule_eng, 'calculate_action_duration') and callable(getattr(rule_eng, 'calculate_action_duration')):
             try: calculated_duration = await rule_eng.calculate_action_duration(action_type=action_type, npc=npc, action_context=action_data, guild_id=guild_id, **kwargs)
             except Exception as e: logger.error(f"NpcAP: Error calc duration for {npc_id} action {action_type}: {e}", exc_info=True)

         action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0

         current_time = 0.0
         if time_mgr and hasattr(time_mgr, 'get_current_game_time') and callable(getattr(time_mgr, 'get_current_game_time')):
             get_time_method = getattr(time_mgr, 'get_current_game_time')
             current_time = await get_time_method(guild_id=guild_id) if asyncio.iscoroutinefunction(get_time_method) else get_time_method(guild_id=guild_id) # Pass guild_id
         action_data['start_game_time'] = current_time
         action_data['progress'] = 0.0

         if not is_valid: return False
         logger.debug(f"NpcAP: Start logic OK for NPC {npc_id}, action '{action_type}', duration {action_data['total_duration']:.1f}.")
         return True

    async def add_action_to_queue(self, guild_id: str, npc_id: str, action_data: Dict[str, Any], **kwargs: Any) -> bool:
        logger.debug(f"NpcAP: Add action to queue for NPC {npc_id}, guild {guild_id}: {action_data.get('type')}")
        npc = self._npc_manager.get_npc(guild_id, npc_id)
        if not npc: return False
        action_type = action_data.get('type')
        if not action_type: await self._notify_gm(guild_id, f"❌ NPC {npc_id} queue error: no action type."); return False

        is_valid = True # Basic validation for queue
        if action_type == 'move' and not action_data.get('target_location_id'):
            is_valid = False; await self._notify_gm(guild_id, f"❌ NPC {npc_id} queue move error: no target_loc_id.")
        # Add other basic pre-checks if needed for other action_types

        if not is_valid: return False

        rule_eng: Optional["RuleEngine"] = kwargs.get('rule_engine', self._rule_engine)
        calculated_duration = action_data.get('total_duration', 0.0)
        if rule_eng and hasattr(rule_eng, 'calculate_action_duration') and callable(getattr(rule_eng, 'calculate_action_duration')):
             try: calculated_duration = await rule_eng.calculate_action_duration(action_type=action_type, npc=npc, action_context=action_data, guild_id=guild_id, **kwargs)
             except Exception as e: logger.error(f"NpcAP: Error calc duration for queue, NPC {npc_id}, action {action_type}: {e}", exc_info=True)
        action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
        action_data['start_game_time'] = None; action_data['progress'] = 0.0

        if hasattr(npc, 'action_queue') and isinstance(npc.action_queue, list): npc.action_queue.append(action_data)
        else: npc.action_queue = [action_data] # Initialize if not list

        self._npc_manager.mark_npc_dirty(guild_id, npc_id)
        self._npc_manager.add_entity_with_active_action(guild_id, npc_id)
        logger.info(f"NpcAP: Action '{action_type}' added to queue for NPC {npc_id}. Queue: {len(npc.action_queue)}.")
        await self._notify_gm(guild_id, f"➡️ NPC {npc_id} action '{action_type}' queued. Duration: {action_data['total_duration']:.1f} min. Queue: {len(npc.action_queue)}")
        return True

    async def process_tick(self, guild_id: str, npc_id: str, game_time_delta: float, **kwargs: Any) -> None:
        npc = self._npc_manager.get_npc(guild_id, npc_id)
        if not npc or (getattr(npc, 'current_action', None) is None and not getattr(npc, 'action_queue', [])):
             self._npc_manager.remove_entity_with_active_action(guild_id, npc_id)
             return

        current_action = getattr(npc, 'current_action', None)
        action_completed = False

        if current_action:
             duration = float(current_action.get('total_duration', 0.0))
             if duration <= 0: action_completed = True
             else:
                  progress = float(current_action.get('progress', 0.0))
                  current_action['progress'] = progress + game_time_delta
                  self._npc_manager.mark_npc_dirty(guild_id, npc_id)
                  if current_action['progress'] >= duration: action_completed = True

        if action_completed and current_action:
             await self.complete_action(guild_id, npc_id, current_action, **kwargs)

        # Re-check state after potential completion/next action start
        npc_recheck = self._npc_manager.get_npc(guild_id, npc_id) # Get potentially updated NPC
        if npc_recheck and getattr(npc_recheck, 'current_action', None) is None and not getattr(npc_recheck, 'action_queue', []):
            self._npc_manager.remove_entity_with_active_action(guild_id, npc_id)


    async def complete_action(self, guild_id: str, npc_id: str, completed_action_data: Dict[str, Any], **kwargs: Any) -> None:
        logger.debug(f"NpcAP: Complete action for NPC {npc_id}, guild {guild_id}: {completed_action_data.get('type')}")
        npc = self._npc_manager.get_npc(guild_id, npc_id)
        if not npc: return

        action_type = completed_action_data.get('type')
        handler_obj = self._handler_registry.get_handler(action_type) # Renamed handler to handler_obj

        if handler_obj and hasattr(handler_obj, 'handle') and callable(getattr(handler_obj, 'handle')):
            logger.info(f"NpcAP: Handler '{type(handler_obj).__name__}' found for action '{action_type}'. Executing for NPC {npc_id}.")
            try:
                # Pass guild_id explicitly to handler context if needed, or it's in kwargs
                kwargs_for_handler = {**kwargs, 'guild_id': guild_id}
                await handler_obj.handle(npc, completed_action_data, send_callback_factory=self._send_callback_factory, **kwargs_for_handler)
            except Exception as e:
                 logger.error(f"NpcAP: Error executing handler for action '{action_type}', NPC {npc_id}: {e}", exc_info=True)
                 await self._notify_gm(guild_id, f"❌ NPC {npc_id} error completing '{action_type}': {e}")
        elif action_type:
            logger.warning(f"NpcAP: No handler for action type '{action_type}' for NPC {npc_id}.")
            await self._notify_gm(guild_id, f"☑️ NPC {npc_id} action '{action_type}' completed (no specific handler).")

        if hasattr(npc, 'current_action'): npc.current_action = None
        self._npc_manager.mark_npc_dirty(guild_id, npc_id)

        action_queue = getattr(npc, 'action_queue', [])
        if action_queue:
             next_action_data = action_queue.pop(0)
             self._npc_manager.mark_npc_dirty(guild_id, npc_id) # Queue changed
             logger.info(f"NpcAP: NPC {npc_id} starting next from queue: {next_action_data.get('type')}. Queue left: {len(action_queue)}.")
             await self.start_action(guild_id, npc_id, next_action_data, **kwargs)
        else:
            logger.info(f"NpcAP: NPC {npc_id} queue empty. Selecting next action via AI.")
            await self.select_next_action(guild_id, npc_id, **kwargs)


    async def select_next_action(self, guild_id: str, npc_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        logger.debug(f"NpcAP: NPC {npc_id} (guild {guild_id}) selecting next action...")
        npc = self._npc_manager.get_npc(guild_id, npc_id)
        if not npc: return None

        next_action_data: Optional[Dict[str, Any]] = None
        ai_context = {**kwargs, 'guild_id': guild_id} # Ensure guild_id is in context for RuleEngine

        rule_eng: Optional["RuleEngine"] = ai_context.get('rule_engine', self._rule_engine)
        combat_mgr: Optional["CombatManager"] = ai_context.get('combat_manager', self._combat_manager)

        if combat_mgr and hasattr(combat_mgr, 'get_combat_by_participant_id') and callable(getattr(combat_mgr, 'get_combat_by_participant_id')):
             current_combat = await combat_mgr.get_combat_by_participant_id(guild_id, npc_id) # Pass guild_id
             if current_combat and rule_eng and hasattr(rule_eng, 'choose_combat_action_for_npc') and callable(getattr(rule_eng, 'choose_combat_action_for_npc')):
                  try: next_action_data = await rule_eng.choose_combat_action_for_npc(npc, current_combat, **ai_context) # Pass full context
                  except Exception as e: logger.error(f"NpcAP: Error in choose_combat_action_for_npc for {npc_id}: {e}", exc_info=True)
                  if next_action_data: logger.debug(f"NpcAP: NPC {npc_id} chose combat action: {next_action_data.get('type')}")

        if not next_action_data and hasattr(npc, 'health') and isinstance(npc.health, (int, float)) and \
           hasattr(npc, 'max_health') and isinstance(npc.max_health, (int, float)) and npc.max_health > 0 and \
           npc.health < npc.max_health * 0.5:
            if rule_eng and hasattr(rule_eng, 'can_rest') and callable(getattr(rule_eng, 'can_rest')):
                 try:
                      if await rule_eng.can_rest(npc, **ai_context): # Pass full context
                           next_action_data = {'type': 'rest'}
                           logger.debug(f"NpcAP: NPC {npc_id} wounded, chose rest.")
                 except Exception as e: logger.error(f"NpcAP: Error checking can_rest for {npc_id}: {e}", exc_info=True)

        if not next_action_data and rule_eng and hasattr(rule_eng, 'choose_peaceful_action_for_npc') and callable(getattr(rule_eng, 'choose_peaceful_action_for_npc')):
             try: next_action_data = await rule_eng.choose_peaceful_action_for_npc(npc, **ai_context) # Pass full context
             except Exception as e: logger.error(f"NpcAP: Error in choose_peaceful_action_for_npc for {npc_id}: {e}", exc_info=True)
             if next_action_data: logger.debug(f"NpcAP: NPC {npc_id} chose peaceful action: {next_action_data.get('type')}")

        if next_action_data:
            await self.start_action(guild_id, npc_id, next_action_data, **ai_context) # Pass full context
            return next_action_data

        logger.debug(f"NpcAP: NPC {npc_id} AI did not select a specific action. Will remain idle if queue is empty.")
        return None

logger.info("DEBUG: npc_action_processor.py module loaded successfully.")
