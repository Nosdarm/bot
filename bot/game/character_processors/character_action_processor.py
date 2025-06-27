# bot/game/character_processors/character_action_processor.py

import json
import uuid
import asyncio
import logging
logger = logging.getLogger(__name__)
from collections import defaultdict
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING, Union, cast

from bot.game.models.character import Character
from bot.game.models.action_request import ActionRequest

from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.equipment_manager import EquipmentManager
from bot.game.managers.inventory_manager import InventoryManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.dialogue_manager import DialogueManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.models.combat import Combat
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.services.db_service import DBService

from bot.game.event_processors.event_stage_processor import EventStageProcessor
from bot.game.event_processors.event_action_processor import EventActionProcessor
from bot.game.managers.event_manager import EventManager
from bot.services.openai_service import OpenAIService
from bot.game.services.location_interaction_service import LocationInteractionService


if TYPE_CHECKING:
    from bot.ai.rules_schema import CoreGameRulesConfig


SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class CharacterActionProcessor:
    def __init__(self,
                 character_manager: CharacterManager,
                 send_callback_factory: SendCallbackFactory,
                 db_service: DBService,
                 item_manager: Optional[ItemManager] = None,
                 location_manager: Optional[LocationManager] = None,
                 dialogue_manager: Optional[DialogueManager] = None,
                 rule_engine: Optional[RuleEngine] = None,
                 time_manager: Optional[TimeManager] = None,
                 combat_manager: Optional[CombatManager] = None,
                 status_manager: Optional[StatusManager] = None,
                 party_manager: Optional[PartyManager] = None,
                 npc_manager: Optional[NpcManager] = None,
                 event_stage_processor: Optional[EventStageProcessor] = None,
                 event_action_processor: Optional[EventActionProcessor] = None,
                 game_log_manager: Optional[GameLogManager] = None,
                 openai_service: Optional[OpenAIService] = None,
                 event_manager: Optional[EventManager] = None,
                 equipment_manager: Optional[EquipmentManager] = None,
                 inventory_manager: Optional[InventoryManager] = None,
                 location_interaction_service: Optional[LocationInteractionService] = None
                ):
        logger.info("Initializing CharacterActionProcessor...")
        self._character_manager = character_manager
        self._send_callback_factory = send_callback_factory
        self.db_service = db_service
        self._game_log_manager = game_log_manager
        self._item_manager = item_manager
        self._inventory_manager = inventory_manager
        self._location_manager = location_manager
        self._dialogue_manager = dialogue_manager
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._npc_manager = npc_manager
        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor
        self._openai_service = openai_service
        self._event_manager = event_manager
        self._equipment_manager = equipment_manager
        self._location_interaction_service = location_interaction_service

        logger.info("CharacterActionProcessor initialized.")

    async def process_action_from_request(self, action_request: ActionRequest, character: Character, context: Dict[str, Any]) -> Dict[str, Any]:
        guild_id = action_request.guild_id
        base_action_type = action_request.action_type.replace("PLAYER_", "", 1).upper()
        action_data = action_request.action_data
        result: Dict[str, Any] = {"success": False, "message": f"Действие '{base_action_type}' не реализовано.", "state_changed": False}


        rules_config: Optional["CoreGameRulesConfig"] = context.get('rules_config') # type: ignore
        if not rules_config and self._rule_engine and hasattr(self._rule_engine, 'rules_config_data'):
            rules_config = self._rule_engine.rules_config_data

        if not rules_config:
            logger.error(f"CAP.process_action_from_request: Rules configuration not available for guild {guild_id}.")
            return {"success": False, "message": "Критическая ошибка: правила игры не загружены для обработки действия.", "state_changed": False}

        transaction_begun = False
        state_changing_actions = ["MOVE", "ATTACK", "SKILL_USE", "PICKUP_ITEM", "EQUIP", "UNEQUIP", "DROP_ITEM", "USE_ITEM", "INTERACT_OBJECT"]
        context_channel_id: Optional[int] = context.get('channel_id')


        try:
            if base_action_type in state_changing_actions:
                if self.db_service and hasattr(self.db_service, 'begin_transaction') and callable(self.db_service.begin_transaction):
                    await self.db_service.begin_transaction()
                    transaction_begun = True
                else:
                    logger.warning(f"CAP.process_action_from_request: DBService not available or begin_transaction not callable for state-changing action {base_action_type}.")

            if base_action_type == "MOVE":
                target_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") in ["location_name", "location_id", "portal_id"]), None)
                if target_entity_data:
                    result = await self.handle_move_action(character, target_entity_data, guild_id, context_channel_id)
                else:
                    result = {"success": False, "message": "Куда идти? Цель не указана.", "state_changed": False}

            elif base_action_type == "ATTACK":
                result = await self.handle_attack_action(character, guild_id, action_data, rules_config)

            elif base_action_type in ["LOOK", "EXPLORE", "LOOK_AROUND", "SEARCH_AREA", "SEARCH"]:
                explore_params = {'target': None}
                look_target_entity = next((e for e in action_data.get("entities", []) if e.get("type") not in ["command", "intent"]), None)
                if look_target_entity:
                    explore_params['target'] = look_target_entity.get("value", look_target_entity.get("name"))
                result = await self.handle_explore_action(character, guild_id, explore_params, context_channel_id)

            elif base_action_type == "SKILL_USE":
                skill_entity = next((e for e in action_data.get("entities", []) if e.get("type") == "skill_name"), None)
                skill_id_or_name = skill_entity.get("value") if skill_entity else action_data.get("skill_id")
                target_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") not in ["skill_name", "command", "intent"]), None)
                if skill_id_or_name:
                    result = await self.handle_skill_use_action(character, skill_id_or_name, target_entity_data, action_data, guild_id, context_channel_id)
                else:
                    result = {"success": False, "message": "Какое умение использовать?", "state_changed": False}

            elif base_action_type in ["PICKUP_ITEM", "PICKUP"]:
                item_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") in ["item_name", "item_id", "item"]), None)
                if item_entity_data:
                    result = await self.handle_pickup_item_action(character, item_entity_data, guild_id, context_channel_id)
                else:
                    result = {"success": False, "message": "Что подобрать?", "state_changed": False}

            elif base_action_type == "EQUIP":
                result = await self.handle_equip_item_action(character, guild_id, action_data, rules_config)

            elif base_action_type == "UNEQUIP":
                result = await self.handle_unequip_item_action(character, guild_id, action_data, rules_config)

            elif base_action_type == "DROP_ITEM":
                result = await self.handle_drop_item_action(character, guild_id, action_data, rules_config)

            elif base_action_type == "TALK":
                if not self._dialogue_manager or not hasattr(self._dialogue_manager, 'handle_talk_action') or not callable(self._dialogue_manager.handle_talk_action):
                    result = {"success": False, "message": "Система диалогов недоступна.", "state_changed": False}
                else:
                    result = await self._dialogue_manager.handle_talk_action(
                        character_speaker=character, guild_id=guild_id,
                        action_data=action_data, rules_config=rules_config
                    )

            elif base_action_type == "USE_ITEM":
                if not self._item_manager or not hasattr(self._item_manager, 'use_item') or not callable(self._item_manager.use_item):
                     result = {"success": False, "message": "Система предметов недоступна.", "state_changed": False}
                else:
                    item_entity = next((e for e in action_data.get("entities", []) if e.get("type") in ["item", "item_template_id", "item_instance_id"]), None)
                    target_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") in ["character", "npc", "player_character", "self"]), None)

                    actual_target_entity_obj = None
                    if target_entity_data and target_entity_data.get("id"):
                        target_obj_id = str(target_entity_data.get("id"))
                        target_obj_type = str(target_entity_data.get("type"))
                        if target_obj_type in ["character", "player_character"] or (target_obj_type == "self" and target_obj_id == character.id):
                            if target_obj_id == character.id or target_obj_type == "self":
                                actual_target_entity_obj = character
                            elif self._character_manager:
                                actual_target_entity_obj = await self._character_manager.get_character(guild_id, target_obj_id)
                        elif target_obj_type == "npc" and self._npc_manager:
                            actual_target_entity_obj = await self._npc_manager.get_npc(guild_id, target_obj_id)
                    elif not target_entity_data:
                        actual_target_entity_obj = character

                    if item_entity and item_entity.get("id"):
                        item_id_from_nlu = str(item_entity.get("id"))
                        result = await self._item_manager.use_item(
                            guild_id=guild_id, character_user=character,
                            item_template_id=item_id_from_nlu, # Assuming use_item takes template_id or instance_id
                            rules_config=rules_config,
                            target_entity=actual_target_entity_obj,
                            additional_params=action_data
                        )
                    else:
                        result = {"success": False, "message": "Какой предмет использовать?", "state_changed": False}

            elif base_action_type in ["INTERACT_OBJECT", "USE_SKILL_ON_OBJECT", "MOVE_TO_INTERACTIVE_FEATURE", "USE_ITEM_ON_OBJECT"]:
                 if not self._location_interaction_service or not hasattr(self._location_interaction_service, 'process_interaction') or not callable(self._location_interaction_service.process_interaction):
                     result = {"success": False, "message": "Сервис взаимодействия с локацией недоступен.", "state_changed": False}
                 else:
                    result = await self._location_interaction_service.process_interaction(
                        guild_id=guild_id, character_id=character.id,
                        action_data=action_data, rules_config=rules_config
                    )

            else:
                logger.warning(f"CAP.process_action_from_request: Unhandled base_action_type '{base_action_type}' for character {character.id}.")
                if self._game_log_manager and hasattr(self._game_log_manager, 'log_event') and callable(self._game_log_manager.log_event):
                    await self._game_log_manager.log_event(
                        guild_id=guild_id, event_type="PLAYER_ACTION_UNKNOWN",
                        details={"message":f"Player {character.id} (Name: {character.name}) attempted unhandled action type '{base_action_type}'.", "action_request_id": action_request.action_id, "action_type": action_request.action_type, "action_data": action_data}
                    )

            if transaction_begun and self.db_service:
                if result.get("success") and result.get("state_changed", False):
                    if hasattr(self.db_service, 'commit_transaction') and callable(self.db_service.commit_transaction): await self.db_service.commit_transaction()
                    logger.debug(f"CAP.process_action_from_request: Committed transaction for action {base_action_type} by {character.id}")
                else:
                    if hasattr(self.db_service, 'rollback_transaction') and callable(self.db_service.rollback_transaction): await self.db_service.rollback_transaction()
                    logger.debug(f"CAP.process_action_from_request: Rolled back transaction for action {base_action_type} by {character.id} (Success: {result.get('success')}, StateChanged: {result.get('state_changed', False)})")
            transaction_begun = False

        except Exception as e:
            logger.error(f"CAP.process_action_from_request: Exception during {base_action_type} for {character.id}: {e}", exc_info=True)
            if transaction_begun and self.db_service and hasattr(self.db_service, 'rollback_transaction') and callable(self.db_service.rollback_transaction):
                await self.db_service.rollback_transaction()
                logger.debug(f"CAP.process_action_from_request: Rolled back transaction due to exception for action {base_action_type} by {character.id}")
            result = {"success": False, "message": f"Внутренняя ошибка при обработке '{base_action_type}': {str(e)}", "state_changed": False, "error": True}

        finally:
            if transaction_begun and self.db_service and hasattr(self.db_service, 'is_transaction_active') and callable(self.db_service.is_transaction_active) and self.db_service.is_transaction_active():
                logger.warning(f"CAP.process_action_from_request: Transaction for action {action_request.action_id} ({base_action_type}) by {character.id} was still active in finally block. Rolling back.")
                if hasattr(self.db_service, 'rollback_transaction') and callable(self.db_service.rollback_transaction): await self.db_service.rollback_transaction()

        if self._game_log_manager and hasattr(self._game_log_manager, 'log_event') and callable(self._game_log_manager.log_event):
            log_event_type = f"PLAYER_ACTION_{base_action_type}_RESULT"
            log_message = f"Player {character.id} (Name: {character.name}) action {base_action_type} (ReqID: {action_request.action_id}) result: Success={result.get('success')}. Message: {result.get('message')}"
            loggable_result = result.copy()
            if "modified_entities" in loggable_result:
                loggable_result["modified_entities_count"] = len(loggable_result["modified_entities"])
                del loggable_result["modified_entities"]

            await self._game_log_manager.log_event(
                guild_id, log_event_type,
                details={"message": log_message, "action_request_id": action_request.action_id, "result": loggable_result, "character_id": character.id, "action_data": action_data}
            )

        return result

    # ... (is_busy, start_action, add_action_to_queue, process_tick, complete_action, _notify_character methods remain unchanged) ...
    async def is_busy(self, guild_id: str, character_id: str) -> bool: # Added async
         if not self._character_manager: return False
         char = await self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Add await
         if not char: return False
         if getattr(char, 'current_action', None) is not None: return True

         party_id_val = getattr(char, 'party_id', None)
         if party_id_val and self._party_manager and hasattr(self._party_manager, 'is_party_busy') and callable(self._party_manager.is_party_busy):
             return await self._party_manager.is_party_busy(str(party_id_val), guild_id=str(char.guild_id)) # Add await, ensure IDs are str
         return False

    async def start_action(self, character_id: str, action_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        modified_entities: List[Any] = []
        guild_id_from_context = kwargs.get('guild_id')
        if not guild_id_from_context:
            logger.critical(f"CharacterActionProcessor: CRITICAL: guild_id not in context for start_action of char {character_id}.")
            await self._notify_character("unknown_guild_FIXME", character_id, "Internal error: Guild context missing for action.")
            return {"success": False, "modified_entities": modified_entities, "message": "Internal error: Guild context missing."}

        guild_id = str(guild_id_from_context)
        if not self._character_manager:
            logger.error(f"CharacterActionProcessor: CharacterManager not available for start_action in guild {guild_id}.")
            return {"success": False, "modified_entities": modified_entities, "message":"Character service unavailable."}

        char = await self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Add await
        if not char:
             logger.error(f"CharacterActionProcessor: Error starting action: Character {character_id} not found in guild {guild_id}.")
             return {"success": False, "modified_entities": modified_entities, "message": f"Character {character_id} not found."}

        action_type = action_data.get('type')
        if not action_type:
             logger.error(f"CharacterActionProcessor: Error starting action: action_data is missing 'type'.")
             await self._notify_character(guild_id, character_id, f"❌ Не удалось начать действие: не указан тип действия.")
             return {"success": False, "modified_entities": modified_entities, "message": "Action type missing."}

        if await self.is_busy(guild_id, character_id): # Add await
             logger.warning(f"CharacterActionProcessor: Character {character_id} is busy. Cannot start new action directly.")
             await self._notify_character(guild_id, character_id, f"❌ Ваш персонаж занят и не может начать действие '{action_type}'.")
             return {"success": False, "modified_entities": modified_entities, "message": "Character is busy."}

        time_manager = kwargs.get('time_manager', self._time_manager)
        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        location_manager = kwargs.get('location_manager', self._location_manager)

        calculated_duration = action_data.get('total_duration', 0.0)
        if rule_engine and hasattr(rule_engine, 'calculate_action_duration') and callable(rule_engine.calculate_action_duration):
             try:
                  kwargs_for_calc = {**kwargs, 'guild_id': guild_id} # Ensure guild_id is in context
                  calculated_duration = await rule_engine.calculate_action_duration(str(action_type), character=char, action_context=action_data, **kwargs_for_calc) # Cast action_type
             except Exception as e:
                  logger.error(f"CharacterActionProcessor: Error calculating duration for action type '{action_type}' for {character_id}: {e}", exc_info=True)
                  calculated_duration = action_data.get('total_duration', 0.0) # Fallback
        try:
            action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
        except (ValueError, TypeError):
             logger.warning(f"CharacterActionProcessor: Calculated duration is not a valid number for action type '{action_type}'. Setting to 0.0.")
             action_data['total_duration'] = 0.0

        if action_type == 'move':
             target_location_id = str(action_data.get('target_location_id')) if action_data.get('target_location_id') else None # Ensure string
             if not target_location_id:
                  logger.error(f"CharacterActionProcessor: Error starting move action: Missing target_location_id in action_data.")
                  await self._notify_character(guild_id, character_id, f"❌ Ошибка перемещения: не указана целевая локация.")
                  return {"success": False, "modified_entities": modified_entities, "message": "Missing target location for move."}
             # Assuming get_location_static is synchronous or location_manager is correctly mocked/handled for sync access if needed
             if location_manager and hasattr(location_manager, 'get_location_static') and callable(location_manager.get_location_static) and location_manager.get_location_static(guild_id, target_location_id) is None:
                 logger.error(f"CharacterActionProcessor: Error starting move action: Target location '{target_location_id}' does not exist.")
                 await self._notify_character(guild_id, character_id, f"❌ Ошибка перемещения: локация '{target_location_id}' не существует.")
                 return {"success": False, "modified_entities": modified_entities, "message": f"Target location {target_location_id} not found."}
             if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                 action_data['callback_data'] = {}
             action_data['callback_data']['target_location_id'] = target_location_id
        else:
             if 'total_duration' not in action_data or action_data['total_duration'] is None:
                  action_data['total_duration'] = 0.0
             try: action_data['total_duration'] = float(action_data['total_duration'])
             except (ValueError, TypeError): action_data['total_duration'] = 0.0

        if time_manager and hasattr(time_manager, 'get_current_game_time') and callable(time_manager.get_current_game_time):
             action_data['start_game_time'] = time_manager.get_current_game_time(guild_id)
        else:
             action_data['start_game_time'] = None # Or a sensible default like time.time() if real-time fallback is okay
        action_data['progress'] = 0.0

        char.current_action = action_data
        # Assuming mark_character_dirty is synchronous
        if hasattr(self._character_manager, 'mark_character_dirty') and callable(self._character_manager.mark_character_dirty):
            self._character_manager.mark_character_dirty(guild_id, character_id)

        # Assuming _entities_with_active_action is on CharacterManager
        if hasattr(self._character_manager, '_entities_with_active_action') and isinstance(self._character_manager._entities_with_active_action, dict):
            self._character_manager._entities_with_active_action.setdefault(guild_id, set()).add(character_id)


        if char not in modified_entities: modified_entities.append(char)
        success_message = f"Character {getattr(char, 'name', character_id)} started action: {action_type}."
        logger.info(f"CharacterActionProcessor: {success_message} Duration: {action_data['total_duration']:.1f}. Marked as dirty.")
        if self._game_log_manager and hasattr(self._game_log_manager, 'log_event') and callable(self._game_log_manager.log_event):
            await self._game_log_manager.log_event(
                guild_id=guild_id, event_type="PLAYER_ACTION_START",
                details={"message":success_message, "related_entities":[{"type": "character", "id": character_id, "name": getattr(char, 'name', 'UnknownChar')}],
                "channel_id":kwargs.get('channel_id'), "action_type":action_type, "action_details":action_data, "success":True}
            )
        return {"success": True, "modified_entities": modified_entities, "message": f"Action {action_type} started."}

    async def add_action_to_queue(self, character_id: str, action_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        modified_entities: List[Any] = []
        guild_id_from_context = kwargs.get('guild_id')
        if not guild_id_from_context:
            await self._notify_character("unknown_guild_FIXME", character_id, "Internal error: Guild context missing for queuing action.")
            return {"success": False, "modified_entities": modified_entities, "message": "Internal error: Guild context missing."}
        guild_id = str(guild_id_from_context)

        if not self._character_manager:
            logger.error(f"CharacterActionProcessor: CharacterManager not available for add_action_to_queue in guild {guild_id}.")
            return {"success": False, "modified_entities": modified_entities, "message":"Character service unavailable."}

        char = await self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Add await
        if not char: return {"success": False, "modified_entities": modified_entities, "message": f"Character {character_id} not found."}

        action_type = action_data.get('type')
        if not action_type:
             await self._notify_character(guild_id, character_id, f"❌ Не удалось добавить действие в очередь: не указан тип действия.")
             return {"success": False, "modified_entities": modified_entities, "message": "Action type missing."}

        char_action_queue = getattr(char, 'action_queue', [])
        if not isinstance(char_action_queue, list): char_action_queue = [] # Ensure it's a list

        char_action_queue.append(action_data)
        char.action_queue = char_action_queue # Assign back if it was potentially created new

        if hasattr(self._character_manager, 'mark_character_dirty') and callable(self._character_manager.mark_character_dirty):
            self._character_manager.mark_character_dirty(guild_id, character_id)

        if hasattr(self._character_manager, '_entities_with_active_action') and isinstance(self._character_manager._entities_with_active_action, dict):
            self._character_manager._entities_with_active_action.setdefault(guild_id, set()).add(character_id)

        if char not in modified_entities: modified_entities.append(char)
        return {"success": True, "modified_entities": modified_entities, "message": "Action queued."}

    async def process_tick(self, char_id: str, game_time_delta: float, **kwargs) -> Dict[str, Any]:
        guild_id_str = str(kwargs.get('guild_id'))
        if not self._character_manager:
            return {"success": False, "message": "CharacterManager not available for process_tick."}

        char: Optional[Character] = await self._character_manager.get_character(guild_id=guild_id_str, character_id=char_id) # Add await
        if not char:
            # Ensure _entities_with_active_action is dict before get
            active_actions_for_guild = getattr(self._character_manager, '_entities_with_active_action', {}).get(guild_id_str)
            if isinstance(active_actions_for_guild, set): active_actions_for_guild.discard(char_id)
            return {"success": False, "message": f"Персонаж {char_id} не найден."}

        current_action = getattr(char, 'current_action', None)
        if current_action and isinstance(current_action, dict): # Check if dict
            current_action['progress'] = current_action.get('progress', 0.0) + game_time_delta
            if current_action['progress'] >= current_action.get('total_duration', 0.0):
                await self.complete_action(char_id, current_action, guild_id=guild_id_str, **kwargs)
            else: # Action still in progress, mark char dirty if not already
                if hasattr(self._character_manager, 'mark_character_dirty') and callable(self._character_manager.mark_character_dirty):
                    self._character_manager.mark_character_dirty(guild_id_str, char_id)


        action_queue_val = getattr(char, 'action_queue', [])
        if not current_action and isinstance(action_queue_val, list) and action_queue_val: # Check if list
            next_action_data = action_queue_val.pop(0)
            char.action_queue = action_queue_val # Assign back modified queue
            await self.start_action(char_id, next_action_data, guild_id=guild_id_str, **kwargs)

        return {"success": True, "message": "Tick processed."}

    async def complete_action(self, character_id: str, completed_action_data: Dict[str, Any], **kwargs) -> List[Any]:
        guild_id = str(kwargs.get('guild_id'))
        if not self._character_manager: return []

        char = await self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Add await
        if not char: return []

        # ... (logic for completing action, e.g., applying effects, moving player)
        char.current_action = None # Clear current action

        if hasattr(self._character_manager, 'mark_character_dirty') and callable(self._character_manager.mark_character_dirty):
            self._character_manager.mark_character_dirty(guild_id, character_id)

        action_queue_val = getattr(char, 'action_queue', [])
        if isinstance(action_queue_val, list) and action_queue_val: # Check if list
             next_action_data = action_queue_val.pop(0)
             char.action_queue = action_queue_val
             await self.start_action(character_id, next_action_data, guild_id=guild_id, **kwargs)
        else: # No more actions in queue
            if hasattr(self._character_manager, '_entities_with_active_action') and isinstance(self._character_manager._entities_with_active_action, dict):
                active_set_complete = self._character_manager._entities_with_active_action.get(guild_id)
                if isinstance(active_set_complete, set): active_set_complete.discard(character_id)

        return [char]

    async def _notify_character(self, guild_id: str, character_id: str, message: str) -> None:
        # Placeholder: actual notification might go through a NotificationService or similar
        logger.info(f"Notify char {character_id} in guild {guild_id}: {message}")
        # If send_callback_factory is still relevant and needs to be async:
        # send_to_channel = self._send_callback_factory(int(guild_id)) # Assuming guild_id can be channel_id for DMs or a lookup happens
        # await send_to_channel(message)
        pass

    async def process_move_action(self, character_id: str, target_location_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        guild_id = str(context.get('guild_id'))
        action_data = {'type': 'move', 'target_location_id': target_location_id}
        # Pass guild_id explicitly to start_action
        return await self.start_action(character_id, action_data, guild_id=guild_id, **context)


    async def process_steal_action(self, character_id: str, target_id: str, target_type: str, context: Dict[str, Any]) -> bool: return True # type: ignore[misc]
    async def process_hide_action(self, character_id: str, context: Dict[str, Any]) -> bool: return True # type: ignore[misc]
    async def process_use_item_action(self, character_id: str, item_instance_id: str, target_entity_id: Optional[str], target_entity_type: Optional[str], context: Dict[str, Any]) -> bool: return True # type: ignore[misc]
    async def process_party_actions(self, game_manager: Any, guild_id: str, actions_to_process: List[Dict[str, Any]], context: Dict[str, Any]) -> Dict[str, Any]: return {"success": True, "overall_state_changed_for_party": False, "individual_action_results": [], "final_modified_entities_this_turn": []} # type: ignore[misc]
    async def process_single_player_actions(self, player: Character, actions_json_str: str, guild_id: str, game_manager: Any, report_channel_id: int) -> Dict[str, Any]: return {"success": True, "messages": ["Actions processed (stub)."], "state_changed": False, "modified_entities": []} # type: ignore[misc]
        
    async def handle_move_action(self, character: Character, destination_entity: Dict[str, Any], guild_id: str, context_channel_id: Optional[int] = None) -> Dict[str, Any]:
        # ... (ensure guild_id is used correctly)
        # ... (existing method)
        # This method would call start_action or similar logic for move
        target_location_id = destination_entity.get("id") or destination_entity.get("value") # NLU might use 'id' or 'value'
        if not target_location_id:
            return {"success": False, "message": "Не указана цель для перемещения.", "state_changed": False}

        return await self.process_move_action(character.id, str(target_location_id), {"guild_id": guild_id, "channel_id": context_channel_id})


    async def handle_skill_use_action(self, character: Character, skill_id_or_name: str, target_entity_data: Optional[Dict[str, Any]], action_params: Dict[str, Any], guild_id: str, context_channel_id: Optional[int] = None) -> Dict[str, Any]:
        # ... (ensure guild_id is used correctly)
        # ... (existing method)
        # This method would call start_action or similar logic for skill use
        # Placeholder implementation
        logger.info(f"Handling skill use: {skill_id_or_name} by {character.id} on {target_entity_data}")
        return {"success": True, "message": f"Умение '{skill_id_or_name}' использовано (симуляция).", "state_changed": True}


    async def handle_pickup_item_action(self, character: Character, item_entity_data: Dict[str, Any], guild_id: str, context_channel_id: Optional[int] = None) -> Dict[str, Any]:
        # ... (ensure guild_id is used correctly)
        # ... (existing method, needs ItemManager.transfer_item_world_to_character to be robust)
        # Placeholder implementation
        item_id = item_entity_data.get("id") or item_entity_data.get("value")
        logger.info(f"Handling pickup item: {item_id} by {character.id}")
        if not self._inventory_manager or not self._item_manager or not character.current_location_id:
            return {"success": False, "message": "Сервисы для подбора предметов недоступны.", "state_changed": False}

        # Simplified: Assume item_id is template_id for world item
        # In reality, world items might be instances or need more complex lookup
        item_template_id = item_id
        if not item_template_id:
            return {"success": False, "message": "Не указан предмет для подбора.", "state_changed": False}

        # Simulate removing from world (LocationManager responsibility, simplified here)
        # Simulate adding to inventory
        # For now, assume success
        transfer_success = await self._item_manager.transfer_item_world_to_character(
            guild_id, str(character.current_location_id), character.id, item_template_id, 1.0
        )
        if transfer_success:
            return {"success": True, "message": f"Предмет '{item_id}' подобран (симуляция).", "state_changed": True}
        else:
            return {"success": False, "message": f"Не удалось подобрать предмет '{item_id}'.", "state_changed": False}


    async def handle_explore_action(self, character: Character, guild_id: str, action_params: Dict[str, Any], context_channel_id: Optional[int] = None) -> Dict[str, Any]:
        logging.debug(f"CharacterActionProcessor.handle_explore_action: Entered. Character ID: {character.id}, Guild ID: {guild_id}, Action Params: {action_params}, Context Channel ID: {context_channel_id}")
        try:
            logging.debug(f"CharacterActionProcessor.handle_explore_action: Checking _location_manager. Available: {bool(self._location_manager)}")
            if not self._location_manager or not hasattr(self._location_manager, 'get_location_static') or not callable(self._location_manager.get_location_static):
                logging.warning(f"CharacterActionProcessor.handle_explore_action: LocationManager or get_location_static not available. Cannot proceed.")
                return {'success': False, 'message': 'Exploration failed: Location service unavailable.', 'data': {}}

            current_loc_id_val = character.current_location_id
            if not current_loc_id_val:
                logger.warning(f"Character {character.id} has no current_location_id.")
                return {'success': False, 'message': 'Exploration failed: Current location unknown.', 'data': {}}

            logging.debug(f"CharacterActionProcessor.handle_explore_action: LocationManager found. Attempting to get location_static for template_id: {current_loc_id_val}")
            location_template_data = self._location_manager.get_location_static(str(current_loc_id_val)) # Ensure string
            logging.debug(f"CharacterActionProcessor.handle_explore_action: Received location_template_data: {location_template_data}")
            if not location_template_data or not isinstance(location_template_data, dict): # Ensure it's a dict
                logging.warning(f"CharacterActionProcessor.handle_explore_action: Failed to retrieve valid location_template_data for template_id: {current_loc_id_val}.")
                return {'success': False, 'message': f'Exploration failed: Could not find template data for your current location (ID: {current_loc_id_val}).', 'data': {}}

            # Removed EventManager check as it's not used in this simplified version.
            # Removed OpenAIService check as AI description is not generated here.

            lang_code = getattr(character, 'selected_language', None)
            if not lang_code or not isinstance(lang_code, str):
                lang_code = 'ru'

            target_name = action_params.get('target')
            if target_name:
                logging.info(f"CharacterActionProcessor.handle_explore_action: Processing 'look at target': {target_name} for character {character.id}.")
                exits_dict = location_template_data.get('exits', {})
                found_exit_id = None; found_exit_target = None
                if isinstance(exits_dict, dict): # Ensure exits_dict is a dict
                    for exit_id, exit_target_id in exits_dict.items():
                        if str(exit_id).lower() == str(target_name).lower(): # Compare as strings
                            found_exit_id = exit_id; found_exit_target = exit_target_id; break
                if found_exit_id:
                    target_message = f"Вы смотрите на выход '{found_exit_id}'. Он ведет к локации с ID '{found_exit_target}'."
                    return {'success': True, 'message': target_message, 'data': {}}
                else:
                    return {'success': False, 'message': f"Объект '{target_name}' не найден.", 'data': {}}
            else:
                location_name_i18n = location_template_data.get('name_i18n', {})
                location_name = location_name_i18n.get(lang_code, location_name_i18n.get('en', "Неизвестное место")) if isinstance(location_name_i18n, dict) else "Неизвестное место"

                desc_i18n = location_template_data.get('descriptions_i18n', {})
                location_description = desc_i18n.get(lang_code, desc_i18n.get('en', "Описание отсутствует.")) if isinstance(desc_i18n, dict) else "Описание отсутствует."

                message_parts = [f"**{location_name}**"]
                if location_description: message_parts.append(location_description)

                exits_data_for_return = []
                exits_dict = location_template_data.get('exits', {})
                if isinstance(exits_dict, dict) and exits_dict:
                    exit_names = [str(e_name) for e_name in exits_dict.keys()]
                    if exit_names: message_parts.append("\n\nВыходы: " + ", ".join(exit_names))
                    for exit_name, exit_target_id in exits_dict.items():
                         exits_data_for_return.append({'name': str(exit_name), 'target_location_id': str(exit_target_id)})
                else:
                    message_parts.append("\n\nВыходов нет.")

                return {'success': True, 'message': "\n".join(message_parts), 'data': {'exits': exits_data_for_return}}
        except Exception as e:
            logger.error(f"CharacterActionProcessor.handle_explore_action: Exception caught. Character ID: {character.id}, Guild ID: {guild_id}, Action Params: {action_params}. Error: {e}", exc_info=True)
            return {'success': False, 'message': f'An unexpected server error occurred during exploration: {e}', 'data': {}}

    async def handle_attack_action(self, character_attacker: Character, guild_id: str, action_data: Dict[str, Any], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        if not self._combat_manager or not hasattr(self._combat_manager, 'get_combat_by_participant_id') or not callable(self._combat_manager.get_combat_by_participant_id) or \
           not hasattr(self._combat_manager, 'handle_participant_action_complete') or not callable(self._combat_manager.handle_participant_action_complete) :
            return {"success": False, "message": "Боевая система неактивна или не полностью настроена.", "state_changed": False}
        if not self._rule_engine:
            return {"success": False, "message": "Система правил неактивна.", "state_changed": False}

        actor_id = str(character_attacker.id) # Ensure string
        actor_type = "Character"

        target_id: Optional[str] = None
        target_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") in ["npc", "character", "player_character"]), None)
        if target_entity_data and isinstance(target_entity_data.get("id"), str):
            target_id = str(target_entity_data.get("id"))
        elif isinstance(action_data.get("target_id"), str):
            target_id = str(action_data.get("target_id"))

        if not target_id:
            return {"success": False, "message": "Не указана цель для атаки.", "state_changed": False}

        combat_instance = await self._combat_manager.get_combat_by_participant_id(guild_id, actor_id) # Add await
        if not combat_instance or not hasattr(combat_instance, 'id'): # Check if combat_instance and its id are valid
            return {"success": False, "message": "Вы не находитесь в бою, чтобы атаковать.", "state_changed": False}

        combat_instance_id = str(combat_instance.id) # Ensure string

        combat_action_data = {
            "type": str(action_data.get("intent_type", "ATTACK")).upper(),
            "actor_id": actor_id,
            "target_ids": [target_id],
        }

        context_for_combat_manager = {
            "guild_id": guild_id, "character_manager": self._character_manager, "npc_manager": self._npc_manager,
            "status_manager": self._status_manager, "item_manager": self._item_manager,
            "inventory_manager": self._inventory_manager, "equipment_manager": self._equipment_manager,
            "rule_engine": self._rule_engine, "rules_config": rules_config,
            "game_log_manager": self._game_log_manager, "combat_manager": self._combat_manager,
            "party_manager": self._party_manager,
        }

        try:
            await self._combat_manager.handle_participant_action_complete(
                combat_instance_id=combat_instance_id, actor_id=actor_id, actor_type=actor_type,
                action_data=combat_action_data, **context_for_combat_manager
            )

            if self._character_manager and hasattr(self._character_manager, 'mark_character_dirty') and callable(self._character_manager.mark_character_dirty):
                self._character_manager.mark_character_dirty(guild_id, actor_id)

            return {"success": True, "message": f"Вы атаковали {target_entity_data.get('name', target_id) if target_entity_data else target_id}. Результаты смотрите в логе боя.", "state_changed": True}

        except Exception as e:
            logger.error(f"CAP.handle_attack_action: Error calling CombatManager: {e}", exc_info=True)
            if self._game_log_manager and hasattr(self._game_log_manager, 'log_error') and callable(self._game_log_manager.log_error):
                 await self._game_log_manager.log_error( # Add await
                    message=f"Error during attack action by {actor_id} on {target_id}: {e}",
                    guild_id=guild_id, actor_id=actor_id, details={"traceback": traceback.format_exc()} # Use details for traceback
                )
            return {"success": False, "message": f"Произошла ошибка при выполнении атаки: {e}", "state_changed": False}


    async def handle_equip_item_action(self, character: Character, guild_id: str, action_data: Dict[str, Any], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        log_prefix = f"CAP.handle_equip_item_action(char='{character.id}', guild='{guild_id}'):"
        if not self._equipment_manager or not hasattr(self._equipment_manager, 'equip_item') or not callable(self._equipment_manager.equip_item):
            return {"success": False, "message": "Система экипировки недоступна.", "state_changed": False}
        item_instance_id: Optional[str] = None
        slot_id_preference: Optional[str] = None
        entities = action_data.get("entities", [])
        for entity in entities:
            if entity.get("type") == "item" or entity.get("type") == "item_instance_id":
                item_instance_id = str(entity.get("id")) if entity.get("id") else None # Ensure string
            elif entity.get("type") == "equipment_slot":
                slot_id_preference = str(entity.get("id")) if entity.get("id") else None # Ensure string

        action_params_val = action_data.get("action_params")
        if not item_instance_id and isinstance(action_params_val, dict) and "item_instance_id" in action_params_val: # Check if dict
            item_instance_id = str(action_params_val["item_instance_id"]) if action_params_val["item_instance_id"] else None
        if not slot_id_preference and isinstance(action_params_val, dict) and "slot_id" in action_params_val: # Check if dict
            slot_id_preference = str(action_params_val["slot_id"]) if action_params_val["slot_id"] else None

        if not item_instance_id:
            return {"success": False, "message": "Не указан предмет для экипировки (требуется ID экземпляра).", "state_changed": False}
        logger.info(f"{log_prefix} Attempting to equip item_instance_id: {item_instance_id} to slot: {slot_id_preference}")
        return await self._equipment_manager.equip_item(guild_id, str(character.id), item_instance_id, slot_id_preference, rules_config) # Ensure char_id is string

    async def handle_unequip_item_action(self, character: Character, guild_id: str, action_data: Dict[str, Any], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        log_prefix = f"CAP.handle_unequip_item_action(char='{character.id}', guild='{guild_id}'):"
        if not self._equipment_manager or not hasattr(self._equipment_manager, 'unequip_item') or not callable(self._equipment_manager.unequip_item):
            return {"success": False, "message": "Система экипировки недоступна.", "state_changed": False}
        slot_id_to_unequip: Optional[str] = None
        entities = action_data.get("entities", [])
        for entity in entities:
            if entity.get("type") == "equipment_slot":
                slot_id_to_unequip = str(entity.get("id")) if entity.get("id") else None # Ensure string
                break

        action_params_val = action_data.get("action_params")
        if not slot_id_to_unequip and isinstance(action_params_val, dict) and "slot_id" in action_params_val: # Check if dict
            slot_id_to_unequip = str(action_params_val["slot_id"]) if action_params_val["slot_id"] else None

        if not slot_id_to_unequip:
            return {"success": False, "message": "Не указан слот для снятия предмета.", "state_changed": False}
        logger.info(f"{log_prefix} Attempting to unequip item from slot: {slot_id_to_unequip}")
        return await self._equipment_manager.unequip_item(guild_id, str(character.id), slot_id_to_unequip, rules_config) # Ensure char_id is string

    async def handle_drop_item_action(self, character: Character, guild_id: str, action_data: Dict[str, Any], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        log_prefix = f"CAP.handle_drop_item_action(char='{character.id}', guild='{guild_id}'):"
        if not self._inventory_manager or not self._location_manager or \
           not hasattr(self._inventory_manager, 'get_item_instance_by_id') or not callable(self._inventory_manager.get_item_instance_by_id) or \
           not hasattr(self._inventory_manager, 'remove_item') or not callable(self._inventory_manager.remove_item) or \
           not hasattr(self._inventory_manager, 'add_item') or not callable(self._inventory_manager.add_item) or \
           not hasattr(self._location_manager, 'add_item_to_location') or not callable(self._location_manager.add_item_to_location):
            return {"success": False, "message": "Системы инвентаря или локаций недоступны или не полностью настроены.", "state_changed": False}


        item_instance_id: Optional[str] = None
        entities = action_data.get("entities", [])
        for entity in entities:
            if entity.get("type") == "item" or entity.get("type") == "item_instance_id":
                item_instance_id = str(entity.get("id")) if entity.get("id") else None # Ensure string
                break

        action_params_val = action_data.get("action_params")
        if not item_instance_id and isinstance(action_params_val, dict) and "item_instance_id" in action_params_val:
            item_instance_id = str(action_params_val["item_instance_id"]) if action_params_val["item_instance_id"] else None

        if not item_instance_id:
            return {"success": False, "message": "Не указан предмет для выбрасывания (требуется ID экземпляра).", "state_changed": False}

        logger.info(f"{log_prefix} Attempting to drop item_instance_id: {item_instance_id}")

        item_to_drop_data = await self._inventory_manager.get_item_instance_by_id(guild_id, str(character.id), item_instance_id) # Ensure char_id is string
        if not item_to_drop_data or not isinstance(item_to_drop_data, dict): # Check if dict
            return {"success": False, "message": f"Предмет с ID '{item_instance_id}' не найден в вашем инвентаре или данные некорректны.", "state_changed": False}

        dropped_item_copy = dict(item_to_drop_data)
        item_template_id_any = dropped_item_copy.get('template_id', dropped_item_copy.get('item_id'))
        item_template_id = str(item_template_id_any) if item_template_id_any else None

        item_quantity_any = dropped_item_copy.get('quantity', 1.0)
        item_quantity = float(item_quantity_any) if item_quantity_any is not None else 1.0

        item_name = str(dropped_item_copy.get('name', item_template_id if item_template_id else "Unknown Item"))


        if not item_template_id:
             logger.error(f"{log_prefix} Item instance {item_instance_id} has no template_id.")
             return {"success": False, "message": "Ошибка данных предмета: отсутствует ID шаблона.", "state_changed": False}

        removed_success = await self._inventory_manager.remove_item(
            guild_id, str(character.id), # Ensure char_id is string
            item_template_id=item_template_id,
            quantity_to_remove=item_quantity,
            instance_id=item_instance_id
        )

        if not removed_success:
            return {"success": False, "message": f"Не удалось убрать '{item_name}' из инвентаря.", "state_changed": False}

        current_location_id_val = str(character.current_location_id) if character.current_location_id else None
        if not current_location_id_val:
             logger.error(f"{log_prefix} Character {character.id} has no valid current_location_id. Cannot drop item.")
             await self._inventory_manager.add_item(guild_id, str(character.id), item_template_id, item_quantity, item_data=dropped_item_copy) # Ensure char_id is string
             return {"success": False, "message": "Ошибка: ваше местоположение не определено, некуда выбрасывать предмет.", "state_changed": False}


        added_to_loc_success = await self._location_manager.add_item_to_location(
            guild_id, current_location_id_val,
            item_template_id=item_template_id,
            quantity=item_quantity,
            dropped_item_data=dropped_item_copy
        )

        if not added_to_loc_success:
            logger.critical(f"{log_prefix} Failed to add '{item_name}' to location {current_location_id_val}. Attempting to return to inventory.")
            await self._inventory_manager.add_item(guild_id, str(character.id), item_template_id, item_quantity, item_data=dropped_item_copy) # Ensure char_id is string
            if self._character_manager and hasattr(self._character_manager, 'mark_character_dirty') and callable(self._character_manager.mark_character_dirty):
                self._character_manager.mark_character_dirty(guild_id, str(character.id)) # Ensure char_id is string
            return {"success": False, "message": f"Не удалось выбросить '{item_name}': ошибка размещения в локации.", "state_changed": False}

        message = f"Вы выбросили '{item_name}'."
        if self._character_manager and hasattr(self._character_manager, 'mark_character_dirty') and callable(self._character_manager.mark_character_dirty):
            self._character_manager.mark_character_dirty(guild_id, str(character.id)) # Ensure char_id is string
        return {"success": True, "message": message, "state_changed": True}

# Конец класса CharacterActionProcessor
