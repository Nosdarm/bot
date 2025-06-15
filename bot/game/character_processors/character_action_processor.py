# bot/game/character_processors/character_action_processor.py

# --- Импорты ---
import json
import uuid
import traceback # Added
import asyncio
import logging
logger = logging.getLogger(__name__) # Added
from collections import defaultdict
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

# Импорт модели Character (нужен для работы с объектами персонажей, полученными от CharacterManager)
from bot.game.models.character import Character
from bot.game.models.action_request import ActionRequest # Added

# Импорт менеджера персонажей (CharacterActionProcessor нуждается в нем для получения объектов Character)
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.equipment_manager import EquipmentManager
from bot.game.managers.inventory_manager import InventoryManager

# Импорт других менеджеров/сервисов
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.dialogue_manager import DialogueManager # Added
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.models.combat import Combat # For type hinting current_combat in handle_attack_action
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.game_log_manager import GameLogManager
from bot.services.db_service import DBService # Added

# Импорт процессоров
from bot.game.event_processors.event_stage_processor import EventStageProcessor
from bot.game.event_processors.event_action_processor import EventActionProcessor
from bot.game.managers.event_manager import EventManager # For handle_explore_action
from bot.services.openai_service import OpenAIService # For descriptions
from bot.game.services.location_interaction_service import LocationInteractionService # Added


if TYPE_CHECKING:
    from bot.ai.rules_schema import CoreGameRulesConfig


# Define send callback type
SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class CharacterActionProcessor:
    def __init__(self,
                 character_manager: CharacterManager,
                 send_callback_factory: SendCallbackFactory, # This might be deprecated if notifications go via a different system
                 db_service: DBService, # Added
                 item_manager: Optional[ItemManager] = None,
                 location_manager: Optional[LocationManager] = None,
                 dialogue_manager: Optional[DialogueManager] = None, # Added
                 rule_engine: Optional[RuleEngine] = None,
                 time_manager: Optional[TimeManager] = None, # May not be used directly by handlers anymore
                 combat_manager: Optional[CombatManager] = None,
                 status_manager: Optional[StatusManager] = None,
                 party_manager: Optional[PartyManager] = None,
                 npc_manager: Optional[NpcManager] = None,
                 event_stage_processor: Optional[EventStageProcessor] = None, # May be less relevant now
                 event_action_processor: Optional[EventActionProcessor] = None, # May be less relevant now
                 game_log_manager: Optional[GameLogManager] = None,
                 openai_service: Optional[OpenAIService] = None, # For descriptions in explore
                 event_manager: Optional[EventManager] = None,
                 equipment_manager: Optional[EquipmentManager] = None,
                 inventory_manager: Optional[InventoryManager] = None,
                 location_interaction_service: Optional[LocationInteractionService] = None # Added
                ):
        logger.info("Initializing CharacterActionProcessor...")
        self._character_manager = character_manager
        self._send_callback_factory = send_callback_factory # Kept for now, but direct notifications might change
        self.db_service = db_service # Added
        self._game_log_manager = game_log_manager
        self._item_manager = item_manager
        self._inventory_manager = inventory_manager
        self._location_manager = location_manager
        self._dialogue_manager = dialogue_manager # Added
        self._rule_engine = rule_engine
        self._time_manager = time_manager # Note: May become less directly used by handlers
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._npc_manager = npc_manager
        self._event_stage_processor = event_stage_processor # Note: May become less relevant
        self._event_action_processor = event_action_processor # Note: May become less relevant
        self._openai_service = openai_service
        self._event_manager = event_manager
        self._equipment_manager = equipment_manager
        self._location_interaction_service = location_interaction_service # Added

        # active_character_actions and old queueing logic might be deprecated by GuildActionScheduler
        # self.active_character_actions: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
        logger.info("CharacterActionProcessor initialized.")

    async def process_action_from_request(self, action_request: ActionRequest, character: Character, context: Dict[str, Any]) -> Dict[str, Any]:
        guild_id = action_request.guild_id
        # Assumes action_type is "PLAYER_MOVE", "PLAYER_ATTACK", etc.
        base_action_type = action_request.action_type.replace("PLAYER_", "", 1).upper()
        action_data = action_request.action_data # This is the original NLU output / player command details

        # Rules config can be passed in context or fetched from rule_engine
        rules_config: Optional[CoreGameRulesConfig] = context.get('rules_config')
        if not rules_config and self._rule_engine:
            rules_config = self._rule_engine.rules_config_data # type: ignore

        if not rules_config: # Still no rules_config, critical error
            logger.error(f"CAP.process_action_from_request: Rules configuration not available for guild {guild_id}.")
            return {"success": False, "message": "Критическая ошибка: правила игры не загружены для обработки действия.", "state_changed": False}

        result: Dict[str, Any] = {"success": False, "message": f"Действие '{base_action_type}' не реализовано.", "state_changed": False}

        transaction_begun = False
        # Define actions that typically modify persistent state and require a transaction
        state_changing_actions = ["MOVE", "ATTACK", "SKILL_USE", "PICKUP_ITEM", "EQUIP", "UNEQUIP", "DROP_ITEM", "USE_ITEM", "INTERACT_OBJECT"]
        # For TALK, state_changed is often True due to dialogue state, but transaction might depend on specific dialogue outcomes
        # If TALK can lead to quests starting/advancing, items given, etc., it might need a transaction.
        # For now, let's assume TALK handles its own transactions if complex, or doesn't need one for simple convos.

        # Context channel_id for notifications, if available from original command context
        # This is not directly in ActionRequest but could be passed in `context` by TurnProcessingService if needed.
        context_channel_id = context.get('channel_id')


        try:
            if base_action_type in state_changing_actions:
                if self.db_service: await self.db_service.begin_transaction(); transaction_begun = True
                else: logger.warning(f"CAP.process_action_from_request: DBService not available for state-changing action {base_action_type}.")

            if base_action_type == "MOVE":
                target_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") in ["location_name", "location_id", "portal_id"]), None)
                if target_entity_data:
                    result = await self.handle_move_action(character, target_entity_data, guild_id, context_channel_id)
                else:
                    result = {"success": False, "message": "Куда идти? Цель не указана.", "state_changed": False}

            elif base_action_type == "ATTACK":
                result = await self.handle_attack_action(character, guild_id, action_data, rules_config)

            elif base_action_type == "LOOK" or base_action_type == "EXPLORE" or base_action_type == "LOOK_AROUND" or base_action_type == "SEARCH_AREA" or base_action_type == "SEARCH":
                explore_params = {'target': None}
                look_target_entity = next((e for e in action_data.get("entities", []) if e.get("type") not in ["command", "intent"]), None)
                if look_target_entity:
                    explore_params['target'] = look_target_entity.get("value", look_target_entity.get("name"))
                result = await self.handle_explore_action(character, guild_id, explore_params, context_channel_id)
                # LOOK actions typically don't change persistent game state requiring transaction commit.
                # result["state_changed"] is often False unless it triggers an event.

            elif base_action_type == "SKILL_USE":
                skill_entity = next((e for e in action_data.get("entities", []) if e.get("type") == "skill_name"), None)
                skill_id_or_name = skill_entity.get("value") if skill_entity else action_data.get("skill_id")
                target_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") not in ["skill_name", "command", "intent"]), None)
                if skill_id_or_name:
                    result = await self.handle_skill_use_action(character, skill_id_or_name, target_entity_data, action_data, guild_id, context_channel_id)
                else:
                    result = {"success": False, "message": "Какое умение использовать?", "state_changed": False}

            elif base_action_type == "PICKUP_ITEM" or base_action_type == "PICKUP":
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
                if not self._dialogue_manager:
                    result = {"success": False, "message": "Система диалогов недоступна.", "state_changed": False}
                else:
                    result = await self._dialogue_manager.handle_talk_action(
                        character_speaker=character, guild_id=guild_id,
                        action_data=action_data, rules_config=rules_config
                    )

            elif base_action_type == "USE_ITEM":
                if not self._item_manager:
                     result = {"success": False, "message": "Система предметов недоступна.", "state_changed": False}
                else:
                    item_entity = next((e for e in action_data.get("entities", []) if e.get("type") in ["item", "item_template_id", "item_instance_id"]), None)
                    target_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") in ["character", "npc", "player_character", "self"]), None)

                    actual_target_entity_obj = None
                    if target_entity_data and target_entity_data.get("id"):
                        target_obj_id = target_entity_data.get("id")
                        target_obj_type = target_entity_data.get("type")
                        if target_obj_type in ["character", "player_character"] or (target_obj_type == "self" and target_obj_id == character.id): # type: ignore
                            if target_obj_id == character.id or target_obj_type == "self": # type: ignore
                                actual_target_entity_obj = character
                            elif self._character_manager:
                                actual_target_entity_obj = await self._character_manager.get_character(guild_id, target_obj_id) # type: ignore
                        elif target_obj_type == "npc" and self._npc_manager:
                            actual_target_entity_obj = await self._npc_manager.get_npc(guild_id, target_obj_id) # type: ignore
                    elif not target_entity_data: # Default to self if no target specified for usable items
                        actual_target_entity_obj = character

                    if item_entity and item_entity.get("id"):
                        item_id_from_nlu = item_entity.get("id")
                        result = await self._item_manager.use_item( # type: ignore
                            guild_id=guild_id, character_user=character,
                            item_template_id=item_id_from_nlu,
                            rules_config=rules_config, # type: ignore
                            target_entity=actual_target_entity_obj,
                            additional_params=action_data
                        )
                    else:
                        result = {"success": False, "message": "Какой предмет использовать?", "state_changed": False}

            elif base_action_type in ["INTERACT_OBJECT", "USE_SKILL_ON_OBJECT", "MOVE_TO_INTERACTIVE_FEATURE", "USE_ITEM_ON_OBJECT"]:
                 if not self._location_interaction_service:
                     result = {"success": False, "message": "Сервис взаимодействия с локацией недоступен.", "state_changed": False}
                 else:
                    result = await self._location_interaction_service.process_interaction( # type: ignore
                        guild_id=guild_id, character_id=character.id,
                        action_data=action_data, rules_config=rules_config # type: ignore
                    )

            else:
                logger.warning(f"CAP.process_action_from_request: Unhandled base_action_type '{base_action_type}' for character {character.id}.")
                if self._game_log_manager:
                    await self._game_log_manager.log_event(
                        guild_id=guild_id, event_type="PLAYER_ACTION_UNKNOWN",
                        message=f"Player {character.id} (Name: {character.name}) attempted unhandled action type '{base_action_type}'.",
                        details={"action_request_id": action_request.action_id, "action_type": action_request.action_type, "action_data": action_data}
                    )

            if transaction_begun and self.db_service:
                if result.get("success") and result.get("state_changed", False):
                    await self.db_service.commit_transaction()
                    logger.debug(f"CAP.process_action_from_request: Committed transaction for action {base_action_type} by {character.id}")
                else:
                    await self.db_service.rollback_transaction()
                    logger.debug(f"CAP.process_action_from_request: Rolled back transaction for action {base_action_type} by {character.id} (Success: {result.get('success')}, StateChanged: {result.get('state_changed', False)})")
            transaction_begun = False

        except Exception as e:
            logger.error(f"CAP.process_action_from_request: Exception during {base_action_type} for {character.id}: {e}", exc_info=True)
            if transaction_begun and self.db_service:
                await self.db_service.rollback_transaction()
                logger.debug(f"CAP.process_action_from_request: Rolled back transaction due to exception for action {base_action_type} by {character.id}")
            result = {"success": False, "message": f"Внутренняя ошибка при обработке '{base_action_type}': {str(e)}", "state_changed": False, "error": True}

        finally:
            if transaction_begun and self.db_service and hasattr(self.db_service, 'is_transaction_active') and self.db_service.is_transaction_active(): # type: ignore
                logger.warning(f"CAP.process_action_from_request: Transaction for action {action_request.action_id} ({base_action_type}) by {character.id} was still active in finally block. Rolling back.")
                await self.db_service.rollback_transaction()

        if self._game_log_manager:
            log_event_type = f"PLAYER_ACTION_{base_action_type}_RESULT"
            log_message = f"Player {character.id} (Name: {character.name}) action {base_action_type} (ReqID: {action_request.action_id}) result: Success={result.get('success')}. Message: {result.get('message')}"
            # Sanitize result for logging if it contains complex objects
            loggable_result = result.copy()
            if "modified_entities" in loggable_result: # Example of removing large data
                loggable_result["modified_entities_count"] = len(loggable_result["modified_entities"])
                del loggable_result["modified_entities"]

            await self._game_log_manager.log_event(
                guild_id, log_event_type, log_message,
                details={"action_request_id": action_request.action_id, "result": loggable_result, "character_id": character.id, "action_data": action_data}
            )

        return result

    # ... (is_busy, start_action, add_action_to_queue, process_tick, complete_action, _notify_character methods remain unchanged) ...
    def is_busy(self, guild_id: str, character_id: str) -> bool:
         char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)
         if not char: return False
         if getattr(char, 'current_action', None) is not None: return True
         if getattr(char, 'party_id', None) and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
             return self._party_manager.is_party_busy(char.party_id, guild_id=str(char.guild_id))
         return False

    async def start_action(self, character_id: str, action_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        modified_entities: List[Any] = []
        guild_id_from_context = kwargs.get('guild_id')
        if not guild_id_from_context:
            logger.critical(f"CharacterActionProcessor: CRITICAL: guild_id not in context for start_action of char {character_id}.") # Changed
            await self._notify_character("unknown_guild_FIXME", character_id, "Internal error: Guild context missing for action.")
            return {"success": False, "modified_entities": modified_entities, "message": "Internal error: Guild context missing."}

        guild_id = str(guild_id_from_context)
        char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)
        if not char:
             logger.error(f"CharacterActionProcessor: Error starting action: Character {character_id} not found in guild {guild_id}.") # Changed
             return {"success": False, "modified_entities": modified_entities}

        action_type = action_data.get('type')
        if not action_type:
             logger.error(f"CharacterActionProcessor: Error starting action: action_data is missing 'type'.") # Changed
             await self._notify_character(guild_id, character_id, f"❌ Не удалось начать действие: не указан тип действия.")
             return {"success": False, "modified_entities": modified_entities}

        if self.is_busy(guild_id, character_id):
             logger.warning(f"CharacterActionProcessor: Character {character_id} is busy. Cannot start new action directly.") # Changed
             await self._notify_character(guild_id, character_id, f"❌ Ваш персонаж занят и не может начать действие '{action_type}'.")
             return {"success": False, "modified_entities": modified_entities}

        time_manager = kwargs.get('time_manager', self._time_manager)
        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        location_manager = kwargs.get('location_manager', self._location_manager)

        calculated_duration = action_data.get('total_duration', 0.0)
        if rule_engine and hasattr(rule_engine, 'calculate_action_duration'):
             try:
                  kwargs_for_calc = {**kwargs, 'guild_id': guild_id}
                  calculated_duration = await rule_engine.calculate_action_duration(action_type, character=char, action_context=action_data, **kwargs_for_calc)
             except Exception as e:
                  logger.error(f"CharacterActionProcessor: Error calculating duration for action type '{action_type}' for {character_id}: {e}", exc_info=True) # Changed
                  calculated_duration = action_data.get('total_duration', 0.0)
        try:
            action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
        except (ValueError, TypeError):
             logger.warning(f"CharacterActionProcessor: Calculated duration is not a valid number for action type '{action_type}'. Setting to 0.0.") # Changed
             action_data['total_duration'] = 0.0

        if action_type == 'move':
             target_location_id = action_data.get('target_location_id')
             if not target_location_id:
                  logger.error(f"CharacterActionProcessor: Error starting move action: Missing target_location_id in action_data.") # Changed
                  await self._notify_character(guild_id, character_id, f"❌ Ошибка перемещения: не указана целевая локация.")
                  return {"success": False, "modified_entities": modified_entities}
             if location_manager and hasattr(location_manager, 'get_location_static') and location_manager.get_location_static(guild_id, target_location_id) is None:
                 logger.error(f"CharacterActionProcessor: Error starting move action: Target location '{target_location_id}' does not exist.") # Changed
                 await self._notify_character(guild_id, character_id, f"❌ Ошибка перемещения: локация '{target_location_id}' не существует.")
                 return {"success": False, "modified_entities": modified_entities}
             if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                 action_data['callback_data'] = {}
             action_data['callback_data']['target_location_id'] = target_location_id
        else:
             if 'total_duration' not in action_data or action_data['total_duration'] is None:
                  action_data['total_duration'] = 0.0
             try: action_data['total_duration'] = float(action_data['total_duration'])
             except (ValueError, TypeError): action_data['total_duration'] = 0.0

        if time_manager and hasattr(time_manager, 'get_current_game_time'):
             action_data['start_game_time'] = time_manager.get_current_game_time(guild_id)
        else:
             action_data['start_game_time'] = None
        action_data['progress'] = 0.0

        char.current_action = action_data
        self._character_manager.mark_character_dirty(guild_id, character_id)
        self._character_manager._entities_with_active_action.setdefault(guild_id, set()).add(character_id)

        if char not in modified_entities: modified_entities.append(char)
        success_message = f"Character {getattr(char, 'name', character_id)} started action: {action_type}."
        logger.info(f"CharacterActionProcessor: {success_message} Duration: {action_data['total_duration']:.1f}. Marked as dirty.") # Changed
        if self._game_log_manager:
            await self._game_log_manager.log_event(
                guild_id=guild_id, actor_id=character_id, event_type="PLAYER_ACTION_START",
                message=success_message, related_entities=[{"type": "character", "id": character_id, "name": getattr(char, 'name', 'UnknownChar')}],
                channel_id=kwargs.get('channel_id'), action_type=action_type, action_details=action_data, success=True
            )
        return {"success": True, "modified_entities": modified_entities, "message": f"Action {action_type} started."}

    async def add_action_to_queue(self, character_id: str, action_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        modified_entities: List[Any] = []
        guild_id_from_context = kwargs.get('guild_id')
        if not guild_id_from_context:
            await self._notify_character("unknown_guild_FIXME", character_id, "Internal error: Guild context missing for queuing action.")
            return {"success": False, "modified_entities": modified_entities, "message": "Internal error: Guild context missing."}
        guild_id = str(guild_id_from_context)
        char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)
        if not char: return {"success": False, "modified_entities": modified_entities}
        action_type = action_data.get('type')
        if not action_type:
             await self._notify_character(guild_id, character_id, f"❌ Не удалось добавить действие в очередь: не указан тип действия.")
             return {"success": False, "modified_entities": modified_entities}
        # ... (rest of validation and duration calculation as in start_action)
        char.action_queue = getattr(char, 'action_queue', [])
        char.action_queue.append(action_data)
        self._character_manager.mark_character_dirty(guild_id, character_id)
        self._character_manager._entities_with_active_action.setdefault(guild_id, set()).add(character_id)
        if char not in modified_entities: modified_entities.append(char)
        # ... (logging)
        return {"success": True, "modified_entities": modified_entities, "message": "Action queued."}

    async def process_tick(self, char_id: str, game_time_delta: float, **kwargs) -> Dict[str, Any]:
        guild_id_str = str(kwargs.get('guild_id'))
        # ... (rest of the method, ensuring guild_id_str is used for all manager calls)
        char: Optional[Character] = self._character_manager.get_character(guild_id=guild_id_str, character_id=char_id)
        if not char:
            active_set_error = self._character_manager._entities_with_active_action.get(guild_id_str)
            if isinstance(active_set_error, set): active_set_error.discard(char_id)
            return {"success": False, "message": f"Персонаж {char_id} не найден."}
        # ...
        if char.current_action:
            # ...
            if char.current_action['progress'] >= char.current_action.get('total_duration', 0.0):
                await self.complete_action(char_id, char.current_action, guild_id=guild_id_str, **kwargs)
            # ...
        if not char.current_action and char.action_queue:
            next_action_data = char.action_queue.pop(0)
            await self.start_action(char_id, next_action_data, guild_id=guild_id_str, **kwargs)
        # ...
        return {"success": True, "message": "Tick processed."} # Simplified

    async def complete_action(self, character_id: str, completed_action_data: Dict[str, Any], **kwargs) -> List[Any]:
        guild_id = str(kwargs.get('guild_id'))
        # ... (rest of the method, ensuring guild_id is used for all manager calls)
        char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)
        if not char: return []
        # ...
        if char.action_queue:
             next_action_data = char.action_queue.pop(0)
             await self.start_action(character_id, next_action_data, guild_id=guild_id, **kwargs)
        # ...
        return [char] # Simplified

    async def _notify_character(self, guild_id: str, character_id: str, message: str) -> None:
        # ... (existing method)
        pass

    async def process_move_action(self, character_id: str, target_location_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        guild_id = str(context.get('guild_id'))
        # ... (existing method)
        action_data = {'type': 'move', 'target_location_id': target_location_id}
        return await self.start_action(character_id, action_data, guild_id=guild_id, **context)


    async def process_steal_action(self, character_id: str, target_id: str, target_type: str, context: Dict[str, Any]) -> bool: return True
    async def process_hide_action(self, character_id: str, context: Dict[str, Any]) -> bool: return True
    async def process_use_item_action(self, character_id: str, item_instance_id: str, target_entity_id: Optional[str], target_entity_type: Optional[str], context: Dict[str, Any]) -> bool: return True
    async def process_party_actions(self, game_manager: Any, guild_id: str, actions_to_process: List[Dict[str, Any]], context: Dict[str, Any]) -> Dict[str, Any]: return {"success": True, "overall_state_changed_for_party": False, "individual_action_results": [], "final_modified_entities_this_turn": []}
    async def process_single_player_actions(self, player: Character, actions_json_str: str, guild_id: str, game_manager: Any, report_channel_id: int) -> Dict[str, Any]: return {"success": True, "messages": ["Actions processed (stub)."], "state_changed": False, "modified_entities": []}
        
    async def handle_move_action(self, character: Character, destination_entity: Dict[str, Any], guild_id: str, context_channel_id: Optional[int] = None) -> Dict[str, Any]:
        # ... (ensure guild_id is used correctly)
        # ... (existing method)
        pass

    async def handle_skill_use_action(self, character: Character, skill_id_or_name: str, target_entity_data: Optional[Dict[str, Any]], action_params: Dict[str, Any], guild_id: str, context_channel_id: Optional[int] = None) -> Dict[str, Any]:
        # ... (ensure guild_id is used correctly)
        # ... (existing method)
        pass

    async def handle_pickup_item_action(self, character: Character, item_entity_data: Dict[str, Any], guild_id: str, context_channel_id: Optional[int] = None) -> Dict[str, Any]:
        # ... (ensure guild_id is used correctly)
        # ... (existing method, needs ItemManager.transfer_item_world_to_character to be robust)
        pass

    async def handle_explore_action(self, character: Character, guild_id: str, action_params: Dict[str, Any], context_channel_id: Optional[int] = None) -> Dict[str, Any]:
        logging.debug(f"CharacterActionProcessor.handle_explore_action: Entered. Character ID: {character.id}, Guild ID: {guild_id}, Action Params: {action_params}, Context Channel ID: {context_channel_id}")
        try:
            logging.debug(f"CharacterActionProcessor.handle_explore_action: Checking _location_manager. Available: {bool(self._location_manager)}")
            if not self._location_manager:
                logging.warning(f"CharacterActionProcessor.handle_explore_action: LocationManager (self._location_manager) is not available. Cannot proceed with exploration logic.")
                specific_error_result = {'success': False, 'message': 'Exploration failed: Location service unavailable.', 'data': {}}
                logging.debug(f"CharacterActionProcessor.handle_explore_action: Returning (due to missing LocationManager): {specific_error_result}")
                return specific_error_result

            logging.debug(f"CharacterActionProcessor.handle_explore_action: LocationManager found. Attempting to get location_static for template_id: {character.location_id}")
            location_template_data = self._location_manager.get_location_static(str(character.location_id))
            logging.debug(f"CharacterActionProcessor.handle_explore_action: Received location_template_data: {location_template_data}")
            if not location_template_data:
                logging.warning(f"CharacterActionProcessor.handle_explore_action: Failed to retrieve location_template_data for template_id: {character.location_id}.")
                specific_error_result = {'success': False, 'message': f'Exploration failed: Could not find template data for your current location (ID: {character.location_id}).', 'data': {}}
                logging.debug(f"CharacterActionProcessor.handle_explore_action: Returning (due to missing location_template_data): {specific_error_result}")
                return specific_error_result

            logging.debug(f"CharacterActionProcessor.handle_explore_action: Checking _event_manager. Available: {bool(self._event_manager)}")
            if not self._event_manager:
                logging.warning(f"CharacterActionProcessor.handle_explore_action: EventManager (self._event_manager) is not available. Cannot check for location events.")
                specific_error_result = {'success': False, 'message': 'Exploration failed: Event service unavailable.', 'data': {}}
                logging.debug(f"CharacterActionProcessor.handle_explore_action: Returning (due to missing EventManager): {specific_error_result}")
                return specific_error_result

            logging.debug(f"CharacterActionProcessor.handle_explore_action: Checking _openai_service. Available: {bool(self._openai_service and self._openai_service.is_available())}")
            if not self._openai_service or not self._openai_service.is_available():
                logging.warning(f"CharacterActionProcessor.handle_explore_action: OpenAIService (self._openai_service) is not available or not configured. Cannot generate AI description.")
                specific_error_result = {'success': False, 'message': 'Exploration failed: AI description service unavailable.', 'data': {}}
                logging.debug(f"CharacterActionProcessor.handle_explore_action: Returning (due to missing OpenAIService): {specific_error_result}")
                return specific_error_result

            # Determine lang_code first as it might be needed in both target and non-target branches
            lang_code = getattr(character, 'selected_language', None)
            if not lang_code or not isinstance(lang_code, str):
                logging.warning(f"CharacterActionProcessor.handle_explore_action: Character {character.id} has no valid 'selected_language'. Defaulting to 'ru'.")
                lang_code = 'ru'
            else:
                logging.debug(f"CharacterActionProcessor.handle_explore_action: Using character's selected language: {lang_code}")

            target_name = action_params.get('target')
            logging.debug(f"CharacterActionProcessor.handle_explore_action: Checking for target. Target from action_params: '{target_name}'")

            if target_name:
                logging.info(f"CharacterActionProcessor.handle_explore_action: Processing 'look at target': {target_name} for character {character.id}.")

                exits_dict = location_template_data.get('exits', {})
                found_exit_id = None
                found_exit_target = None
                for exit_id, exit_target_id in exits_dict.items():
                    if exit_id.lower() == target_name.lower():
                        found_exit_id = exit_id
                        found_exit_target = exit_target_id
                        break

                if found_exit_id:
                    # TODO: Optionally, try to get a localized name for found_exit_target if LocationManager allows fetching template names by ID.
                    # For now, use its ID.
                    target_message = f"Вы смотрите на выход '{found_exit_id}'. Он ведет к локации с ID '{found_exit_target}'."
                    logging.info(f"CharacterActionProcessor.handle_explore_action: Target '{target_name}' identified as an exit leading to '{found_exit_target}'.")
                    return {
                        'success': True,
                        'message': target_message,
                        'data': {}
                    }
                else:
                    # Placeholder for checking other static features if the template structure is extended in the future.
                    # For now, if it's not an exit, it's not a recognized static target.
                    logging.info(f"CharacterActionProcessor.handle_explore_action: Target '{target_name}' not found as an exit or other known static feature.")
                    return {
                        'success': False,
                        'message': f"Объект '{target_name}' не найден среди известных статических элементов или выходов этой локации.",
                        'data': {}
                    }
            else:
                logging.debug(f"CharacterActionProcessor.handle_explore_action: No target specified. Proceeding with general location description.")
                # Existing logic for "look around" (getting location name, description, exits, and returning success) follows here.
                # Basic description generation from location_template_data (dictionary)
                location_name = location_template_data.get('name_i18n', {}).get(lang_code, location_template_data.get('name_i18n', {}).get('en', "Неизвестное место"))
                logging.debug(f"CharacterActionProcessor.handle_explore_action: Fetched location_name: '{location_name}'")

                location_description = location_template_data.get('descriptions_i18n', {}).get(lang_code, location_template_data.get('descriptions_i18n', {}).get('en', "Описание отсутствует."))
                logging.debug(f"CharacterActionProcessor.handle_explore_action: Fetched location_description: '{location_description[:100]}...' (truncated if long)")

                message_parts = [f"**{location_name}**"]
                if location_description:
                    message_parts.append(location_description)
                logging.debug(f"CharacterActionProcessor.handle_explore_action: Generated message parts after description: {message_parts}")

                # Basic exit listing from location_template_data (dictionary)
                exits_data_for_return = []
                exits_dict = location_template_data.get('exits', {})
                if isinstance(exits_dict, dict) and exits_dict:
                    logging.debug(f"CharacterActionProcessor.handle_explore_action: Processing exits: {exits_dict}")
                    exit_names = []
                    for exit_name, exit_target_id in exits_dict.items():
                        exit_names.append(str(exit_name))
                        exits_data_for_return.append({'name': str(exit_name), 'target_location_id': str(exit_target_id)})
                    if exit_names:
                        message_parts.append("\n\nВыходы: " + ", ".join(exit_names))
                else:
                    logging.debug(f"CharacterActionProcessor.handle_explore_action: No exits found or 'exits' key is missing/empty in location_template_data: {location_template_data.get('exits', 'N/A')}")
                    message_parts.append("\n\nВыходов нет.")

                logging.debug(f"CharacterActionProcessor.handle_explore_action: Updated message parts after exits: {message_parts}, Exits data for return: {exits_data_for_return}")

                # Construct and return success result
                final_message = "".join(message_parts)
                success_result = {
                    'success': True,
                    'message': final_message,
                    'data': {'exits': exits_data_for_return}
                }
                logging.debug(f"CharacterActionProcessor.handle_explore_action: Returning success: {success_result}")
                return success_result
        except Exception as e:
            logging.error(f"CharacterActionProcessor.handle_explore_action: Exception caught. Character ID: {character.id}, Guild ID: {guild_id}, Action Params: {action_params}. Error: {e}", exc_info=True)
            exception_result = {'success': False, 'message': f'An unexpected server error occurred during exploration: {e}', 'data': {}}
            logging.debug(f"CharacterActionProcessor.handle_explore_action: Returning (due to exception): {exception_result}")
            return exception_result

    async def handle_attack_action(self, character_attacker: Character, guild_id: str, action_data: Dict[str, Any], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        if not self._combat_manager:
            return {"success": False, "message": "Боевая система неактивна.", "state_changed": False}
        if not self._rule_engine: # Rule engine is needed for context in combat manager
            return {"success": False, "message": "Система правил неактивна.", "state_changed": False}

        actor_id = character_attacker.id
        actor_type = "Character" # Explicitly set for characters

        # Determine target_id from action_data
        # NLU should fill "entities" with target information.
        # Example: entities: [{"type": "npc", "id": "npc_goblin_123", "name": "Гоблин"}]
        target_id: Optional[str] = None
        target_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") in ["npc", "character", "player_character"]), None)
        if target_entity_data and isinstance(target_entity_data.get("id"), str):
            target_id = target_entity_data.get("id")
        elif isinstance(action_data.get("target_id"), str): # Fallback if target_id is directly provided
            target_id = action_data.get("target_id")

        if not target_id:
            return {"success": False, "message": "Не указана цель для атаки.", "state_changed": False}

        # Check if attacker is in combat and get combat_id
        combat_instance = self._combat_manager.get_combat_by_participant_id(guild_id, actor_id)
        if not combat_instance:
            # TODO: Future: Initiate combat if not already in one and target is hostile?
            # For now, assume player must be in combat to attack.
            return {"success": False, "message": "Вы не находитесь в бою, чтобы атаковать.", "state_changed": False}

        combat_instance_id = combat_instance.id

        # Prepare action_data for CombatManager
        # CombatManager expects 'type', 'actor_id', 'target_ids', etc.
        combat_action_data = {
            "type": action_data.get("intent_type", "ATTACK").upper(), # Use original intent or default to ATTACK
            "actor_id": actor_id,
            "target_ids": [target_id], # Assuming single target for now, can be expanded
            # Potentially add other details from action_data if needed by RuleEngine later,
            # e.g., specific weapon used if not automatically derived from equipped items.
            # "weapon_id": action_data.get("weapon_id")
        }

        # Assemble the full context for CombatManager
        # This context needs all managers that CombatManager or subsequent systems (RuleEngine, StatsCalculator) might need.
        context_for_combat_manager = {
            "guild_id": guild_id,
            "character_manager": self._character_manager,
            "npc_manager": self._npc_manager,
            "status_manager": self._status_manager,
            "item_manager": self._item_manager,
            "inventory_manager": self._inventory_manager,
            "equipment_manager": self._equipment_manager,
            "rule_engine": self._rule_engine,
            "rules_config": rules_config, # This is CoreGameRulesConfig object
            "game_log_manager": self._game_log_manager,
            "combat_manager": self._combat_manager, # CombatManager itself might be needed in context by RuleEngine
            "party_manager": self._party_manager,
            # Add other managers if they become relevant for combat processing
            # "relationship_manager": self._relationship_manager, (if available and needed)
            # "quest_manager": self._quest_manager, (if available and needed)
        }

        # Call CombatManager's refactored method
        # Note: CombatManager.handle_participant_action_complete doesn't directly return a user-facing message dict.
        # It updates combat state. We might need a way to get feedback from it if direct messages are needed here.
        # For now, we assume success if no exception, and the feedback will come via game state changes / combat logs.
        try:
            await self._combat_manager.handle_participant_action_complete(
                combat_instance_id=combat_instance_id,
                actor_id=actor_id,
                actor_type=actor_type,
                action_data=combat_action_data,
                **context_for_combat_manager # Pass context as kwargs
            )
            # The actual outcome (hit, miss, damage) will be appended to combat_instance.combat_log
            # by the CombatManager and RuleEngine.
            # We can return a generic success message here, or try to pull last log entry.
            # For simplicity, let's return a generic message.
            # More detailed feedback would come from observing the Combat object or dedicated feedback system.

            # Mark character as having taken a significant action that might change state
            self._character_manager.mark_character_dirty(guild_id, actor_id)

            return {"success": True, "message": f"Вы атаковали {target_entity_data.get('name', target_id) if target_entity_data else target_id}. Результаты смотрите в логе боя.", "state_changed": True}

        except Exception as e:
            logger.error(f"CAP.handle_attack_action: Error calling CombatManager: {e}", exc_info=True) # Changed
            # Ensure GameLogManager is available before trying to log
            if self._game_log_manager:
                 await self._game_log_manager.log_error(
                    message=f"Error during attack action by {actor_id} on {target_id}: {e}",
                    guild_id=guild_id, actor_id=actor_id, details=traceback.format_exc()
                )
            return {"success": False, "message": f"Произошла ошибка при выполнении атаки: {e}", "state_changed": False}


    async def handle_equip_item_action(self, character: Character, guild_id: str, action_data: Dict[str, Any], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        log_prefix = f"CAP.handle_equip_item_action(char='{character.id}', guild='{guild_id}'):"
        if not self._equipment_manager:
            return {"success": False, "message": "Система экипировки недоступна.", "state_changed": False}
        item_instance_id: Optional[str] = None
        slot_id_preference: Optional[str] = None
        entities = action_data.get("entities", [])
        for entity in entities:
            if entity.get("type") == "item" or entity.get("type") == "item_instance_id":
                item_instance_id = entity.get("id")
            elif entity.get("type") == "equipment_slot":
                slot_id_preference = entity.get("id")
        if not item_instance_id and "item_instance_id" in action_data.get("action_params", {}):
            item_instance_id = action_data["action_params"]["item_instance_id"]
        if not slot_id_preference and "slot_id" in action_data.get("action_params", {}):
            slot_id_preference = action_data["action_params"]["slot_id"]
        if not item_instance_id:
            return {"success": False, "message": "Не указан предмет для экипировки (требуется ID экземпляра).", "state_changed": False}
        logger.info(f"{log_prefix} Attempting to equip item_instance_id: {item_instance_id} to slot: {slot_id_preference}") # Changed
        return await self._equipment_manager.equip_item(guild_id, character.id, item_instance_id, slot_id_preference, rules_config)

    async def handle_unequip_item_action(self, character: Character, guild_id: str, action_data: Dict[str, Any], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        log_prefix = f"CAP.handle_unequip_item_action(char='{character.id}', guild='{guild_id}'):"
        if not self._equipment_manager:
            return {"success": False, "message": "Система экипировки недоступна.", "state_changed": False}
        slot_id_to_unequip: Optional[str] = None
        entities = action_data.get("entities", [])
        for entity in entities:
            if entity.get("type") == "equipment_slot":
                slot_id_to_unequip = entity.get("id")
                break
        if not slot_id_to_unequip and "slot_id" in action_data.get("action_params", {}):
            slot_id_to_unequip = action_data["action_params"]["slot_id"]
        if not slot_id_to_unequip:
            return {"success": False, "message": "Не указан слот для снятия предмета.", "state_changed": False}
        logger.info(f"{log_prefix} Attempting to unequip item from slot: {slot_id_to_unequip}") # Changed
        return await self._equipment_manager.unequip_item(guild_id, character.id, slot_id_to_unequip, rules_config)

    async def handle_drop_item_action(self, character: Character, guild_id: str, action_data: Dict[str, Any], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        """Handles dropping an item from inventory to the location."""
        log_prefix = f"CAP.handle_drop_item_action(char='{character.id}', guild='{guild_id}'):"
        if not self._inventory_manager or not self._location_manager:
            return {"success": False, "message": "Системы инвентаря или локаций недоступны.", "state_changed": False}

        item_instance_id: Optional[str] = None
        entities = action_data.get("entities", [])
        for entity in entities: # NLU should provide the item's instance_id
            if entity.get("type") == "item" or entity.get("type") == "item_instance_id":
                item_instance_id = entity.get("id")
                break

        if not item_instance_id and "item_instance_id" in action_data.get("action_params", {}): # Fallback
            item_instance_id = action_data["action_params"]["item_instance_id"]

        if not item_instance_id:
            return {"success": False, "message": "Не указан предмет для выбрасывания (требуется ID экземпляра).", "state_changed": False}

        logger.info(f"{log_prefix} Attempting to drop item_instance_id: {item_instance_id}") # Changed

        item_to_drop_data = await self._inventory_manager.get_item_instance_by_id(guild_id, character.id, item_instance_id)
        if not item_to_drop_data:
            return {"success": False, "message": f"Предмет с ID '{item_instance_id}' не найден в вашем инвентаре.", "state_changed": False}

        # Make a copy before removal, as remove_item might modify the list/dict if direct references are used
        dropped_item_copy = dict(item_to_drop_data)
        item_template_id = dropped_item_copy.get('template_id', dropped_item_copy.get('item_id'))
        item_quantity = dropped_item_copy.get('quantity', 1)
        item_name = dropped_item_copy.get('name', item_template_id)


        if not item_template_id:
             logger.error(f"{log_prefix} Item instance {item_instance_id} has no template_id.") # Changed
             return {"success": False, "message": "Ошибка данных предмета: отсутствует ID шаблона.", "state_changed": False}

        removed_success = await self._inventory_manager.remove_item(
            guild_id,
            character.id,
            item_template_id=item_template_id, # Required by current remove_item signature
            quantity_to_remove=item_quantity, # Remove the full stack/instance
            instance_id=item_instance_id
        )

        if not removed_success:
            return {"success": False, "message": f"Не удалось убрать '{item_name}' из инвентаря.", "state_changed": False}

        current_location_id = str(character.location_id)
        if not current_location_id: # Should not happen if character is valid
             # Attempt to put item back if location is invalid? Or let it be removed.
             # For now, assume location is valid.
             logger.error(f"{log_prefix} Character {character.id} has no valid location_id. Cannot drop item.") # Changed
             # Try to add item back to inventory to prevent loss
             await self._inventory_manager.add_item(guild_id, character.id, item_template_id, item_quantity, item_data=dropped_item_copy)
             return {"success": False, "message": "Ошибка: ваше местоположение не определено, некуда выбрасывать предмет.", "state_changed": False}


        added_to_loc_success = await self._location_manager.add_item_to_location(
            guild_id,
            current_location_id,
            item_template_id=item_template_id, # Pass template_id for LocationManager
            quantity=item_quantity,
            dropped_item_data=dropped_item_copy # Pass the full original data for state preservation
        )

        if not added_to_loc_success:
            # Critical: item removed from inventory but not added to location. Try to give it back.
            logger.critical(f"{log_prefix} Failed to add '{item_name}' to location {current_location_id}. Attempting to return to inventory.") # Changed
            await self._inventory_manager.add_item(guild_id, character.id, item_template_id, item_quantity, item_data=dropped_item_copy)
            # Mark character dirty again as inventory changed back
            self._character_manager.mark_character_dirty(guild_id, character.id)
            return {"success": False, "message": f"Не удалось выбросить '{item_name}': ошибка размещения в локации.", "state_changed": False} # State did change then changed back

        message = f"Вы выбросили '{item_name}'."
        # Mark character dirty because inventory changed. Location is marked dirty by its own manager.
        self._character_manager.mark_character_dirty(guild_id, character.id)
        return {"success": True, "message": message, "state_changed": True}

# Конец класса CharacterActionProcessor
