# bot/game/services/consequence_processor.py

from __future__ import annotations
import traceback
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Callable, Awaitable, cast

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.services.notification_service import NotificationService
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.models.character import Character as CharacterModel # For type hint

    CustomFunctionCallback = Callable[[Any, Dict[str, Any]], Awaitable[None]]

import logging
logger = logging.getLogger(__name__)

class ConsequenceProcessor:
    def __init__(
        self,
        character_manager: Optional[CharacterManager] = None,
        npc_manager: Optional[NpcManager] = None,
        item_manager: Optional[ItemManager] = None,
        location_manager: Optional[LocationManager] = None,
        event_manager: Optional[EventManager] = None,
        quest_manager: Optional[QuestManager] = None,
        status_manager: Optional[StatusManager] = None,
        dialogue_manager: Optional[DialogueManager] = None,
        game_state: Optional[Any] = None, # Consider a more specific GameState type
        rule_engine: Optional[RuleEngine] = None,
        economy_manager: Optional[EconomyManager] = None,
        relationship_manager: Optional[RelationshipManager] = None,
        game_log_manager: Optional[GameLogManager] = None,
        notification_service: Optional[NotificationService] = None,
        prompt_context_collector: Optional[PromptContextCollector] = None
    ):
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._event_manager = event_manager
        self._quest_manager = quest_manager
        self._status_manager = status_manager
        self._dialogue_manager = dialogue_manager
        self._game_state = game_state
        self._rule_engine = rule_engine
        self._economy_manager = economy_manager
        self._relationship_manager = relationship_manager
        self._game_log_manager = game_log_manager
        self._notification_service = notification_service
        self._prompt_context_collector = prompt_context_collector

        self._custom_functions: Dict[str, CustomFunctionCallback] = {}
        logger.info("ConsequenceProcessor initialized.")

    def register_custom_function(self, name: str, func: CustomFunctionCallback) -> None:
        if name in self._custom_functions:
            logger.warning(f"Overwriting custom consequence function '{name}'.")
        self._custom_functions[name] = func
        logger.info(f"Custom consequence function '{name}' registered.")

    async def process_consequences(
        self,
        guild_id: str,
        consequences: List[Dict[str, Any]],
        source_entity_id: Optional[str] = None,
        target_entity_id: Optional[str] = None,
        event_context: Optional[Dict[str, Any]] = None,
        send_callback_factory: Optional[Callable[[int], Callable[[str], Awaitable[None]]]] = None
    ) -> None:
        if not consequences:
            return
        logger.info(f"Processing {len(consequences)} consequences for guild {guild_id}. Source: {source_entity_id}, Target: {target_entity_id}")

        for i, cons_dict in enumerate(consequences):
            action_type = cons_dict.get('action_type')
            if not action_type:
                logger.warning(f"Consequence {i+1} missing 'action_type'. Skipping: {cons_dict}")
                continue

            current_target_id = cons_dict.get('character_id') or cons_dict.get('npc_id') or cons_dict.get('entity_id') or target_entity_id
            target_entity_type_str = "Unknown"
            log_player_id = None

            logger.debug(f"Executing consequence {i+1}/{len(consequences)}: {action_type} for target '{current_target_id}' (Source: '{source_entity_id}')")

            try:
                if action_type == "MODIFY_NPC_STATS":
                    npc_id = cons_dict.get('npc_id', current_target_id)
                    stats_changes = cons_dict.get('stats_changes')
                    if npc_id and stats_changes and self._npc_manager and hasattr(self._npc_manager, 'modify_npc_stats') and callable(getattr(self._npc_manager, 'modify_npc_stats')):
                        await self._npc_manager.modify_npc_stats(guild_id, npc_id, stats_changes)
                        target_entity_type_str = "NPC"
                        if self._game_log_manager: await self._game_log_manager.log_event(guild_id, "CONSEQUENCE_NPC_STAT_MODIFIED", {"consequence": cons_dict, "npc_id": npc_id, "changes": stats_changes}, source_entity_id, npc_id, target_entity_type_str)
                    else: logger.warning(f"Missing data or NpcManager.modify_npc_stats for MODIFY_NPC_STATS: {cons_dict}")

                elif action_type == "MODIFY_CHARACTER_STATS":
                    char_id = cons_dict.get('character_id', current_target_id)
                    stats_changes = cons_dict.get('stats_changes')
                    if char_id and stats_changes and self._character_manager and hasattr(self._character_manager, 'modify_character_stats') and callable(getattr(self._character_manager, 'modify_character_stats')):
                        await self._character_manager.modify_character_stats(guild_id, char_id, stats_changes)
                        target_entity_type_str = "Character"; log_player_id = char_id
                        if self._game_log_manager: await self._game_log_manager.log_event(guild_id, "CONSEQUENCE_CHAR_STAT_MODIFIED", {"consequence": cons_dict, "character_id": char_id, "changes": stats_changes}, log_player_id, source_entity_id, char_id, target_entity_type_str)
                    else: logger.warning(f"Missing data or CharacterManager.modify_character_stats for MODIFY_CHARACTER_STATS: {cons_dict}")

                elif action_type == "ADD_ITEM_TO_CHARACTER":
                    char_id = cons_dict.get('character_id', current_target_id)
                    item_template_id = cons_dict.get('item_template_id')
                    quantity = int(cons_dict.get('quantity', 1))
                    state_vars = cons_dict.get('state_variables', {})
                    if char_id and item_template_id and self._item_manager and hasattr(self._item_manager, 'give_item_to_character') and callable(getattr(self._item_manager, 'give_item_to_character')):
                        await self._item_manager.give_item_to_character(guild_id, char_id, item_template_id, quantity, state_vars)
                        target_entity_type_str = "Character"; log_player_id = char_id
                        if self._game_log_manager: await self._game_log_manager.log_event(guild_id, "CONSEQUENCE_ITEM_ADDED_TO_CHAR", {"consequence": cons_dict, "item_template_id": item_template_id, "quantity": quantity, "character_id": char_id}, log_player_id, source_entity_id, char_id, target_entity_type_str)
                        if self._notification_service and hasattr(self._notification_service, 'notify_player') and callable(getattr(self._notification_service, 'notify_player')):
                            item_name = item_template_id # Placeholder
                            await self._notification_service.notify_player(char_id, "item_received", {"message": f"You received {quantity}x {item_name}.", "item_name": item_name, "quantity": quantity, "source": source_entity_id or "Unknown Source"})
                    else: logger.warning(f"Missing data or ItemManager.give_item_to_character for ADD_ITEM_TO_CHARACTER: {cons_dict}")

                elif action_type == "REMOVE_ITEM_FROM_CHARACTER":
                    char_id = cons_dict.get('character_id', current_target_id)
                    item_id_or_template_id = cons_dict.get('item_id') or cons_dict.get('item_template_id')
                    quantity = int(cons_dict.get('quantity', 1))
                    if char_id and item_id_or_template_id and self._item_manager:
                        removed_by_instance = bool(cons_dict.get('item_id'))
                        if removed_by_instance and hasattr(self._item_manager, 'remove_item_from_character_by_instance_id') and callable(getattr(self._item_manager, 'remove_item_from_character_by_instance_id')):
                             await self._item_manager.remove_item_from_character_by_instance_id(guild_id, char_id, str(cons_dict.get('item_id')), quantity)
                        elif not removed_by_instance and hasattr(self._item_manager, 'remove_item_from_character_by_template_id') and callable(getattr(self._item_manager, 'remove_item_from_character_by_template_id')):
                             await self._item_manager.remove_item_from_character_by_template_id(guild_id, char_id, str(cons_dict.get('item_template_id')), quantity)
                        else: logger.warning(f"Missing specific ItemManager method for REMOVE_ITEM_FROM_CHARACTER: {cons_dict}"); continue

                        target_entity_type_str = "Character"; log_player_id = char_id
                        if self._game_log_manager: await self._game_log_manager.log_event(guild_id, "CONSEQUENCE_ITEM_REMOVED_FROM_CHAR", {"consequence": cons_dict, "item_id_or_template": item_id_or_template_id, "quantity": quantity, "character_id": char_id}, log_player_id, source_entity_id, char_id, target_entity_type_str)
                        if self._notification_service and hasattr(self._notification_service, 'notify_player') and callable(getattr(self._notification_service, 'notify_player')):
                             item_name = str(item_id_or_template_id)
                             await self._notification_service.notify_player(char_id, "item_lost", {"message": f"{quantity}x {item_name} removed.", "item_name": item_name, "quantity": quantity, "source": source_entity_id or "Unknown Source"})
                    else: logger.warning(f"Missing data or ItemManager for REMOVE_ITEM_FROM_CHARACTER: {cons_dict}")

                elif action_type == "CHANGE_LOCATION":
                    entity_id = cons_dict.get('entity_id', current_target_id)
                    entity_type_param = cons_dict.get('entity_type')
                    new_location_id = cons_dict.get('new_location_id')
                    if entity_id and entity_type_param and new_location_id:
                        moved = False
                        if entity_type_param.lower() == 'character' and self._character_manager and hasattr(self._character_manager, 'move_character_to_location') and callable(getattr(self._character_manager, 'move_character_to_location')):
                            await self._character_manager.move_character_to_location(guild_id, entity_id, new_location_id)
                            target_entity_type_str = "Character"; log_player_id = entity_id; moved = True
                        elif entity_type_param.lower() == 'npc' and self._npc_manager and hasattr(self._npc_manager, 'move_npc_to_location') and callable(getattr(self._npc_manager, 'move_npc_to_location')):
                            await self._npc_manager.move_npc_to_location(guild_id, entity_id, new_location_id)
                            target_entity_type_str = "NPC"; moved = True
                        else: logger.warning(f"Unknown entity_type or missing manager method for CHANGE_LOCATION: {cons_dict}")
                        if moved and self._game_log_manager: await self._game_log_manager.log_event(guild_id, "CONSEQUENCE_ENTITY_LOCATION_CHANGED", {"consequence": cons_dict, "entity_id": entity_id, "new_location_id": new_location_id, "entity_type": entity_type_param}, log_player_id, source_entity_id, entity_id, target_entity_type_str)
                    else: logger.warning(f"Missing data for CHANGE_LOCATION: {cons_dict}")

                elif action_type == "START_EVENT":
                    event_template_id = cons_dict.get('event_template_id')
                    if event_template_id and self._event_manager and hasattr(self._event_manager, 'start_event') and callable(getattr(self._event_manager, 'start_event')):
                        involved_character_ids = cons_dict.get('character_ids', [])
                        if current_target_id and self._character_manager: # Check _character_manager before get_character
                            char_obj = await self._character_manager.get_character(guild_id, current_target_id) # Await the getter
                            if char_obj and current_target_id not in involved_character_ids: # Check char_obj
                                involved_character_ids.append(current_target_id)
                        await self._event_manager.start_event(guild_id, event_template_id, cons_dict.get('channel_id'), involved_character_ids, cons_dict.get('npc_ids', []), cons_dict.get('initial_state', {}), send_callback_factory)
                        if self._game_log_manager: await self._game_log_manager.log_event(guild_id, "CONSEQUENCE_EVENT_STARTED", {"consequence": cons_dict, "event_template_id": event_template_id}, source_entity_id=source_entity_id)
                    else: logger.warning(f"Missing event_template_id or EventManager.start_event for START_EVENT: {cons_dict}")

                elif action_type == "UPDATE_QUEST_STATE":
                    quest_id = cons_dict.get('quest_id')
                    character_id = cons_dict.get('character_id', current_target_id)
                    if quest_id and character_id and self._quest_manager and hasattr(self._quest_manager, 'update_quest_progress') and callable(getattr(self._quest_manager, 'update_quest_progress')):
                        await self._quest_manager.update_quest_progress(guild_id, character_id, quest_id, cons_dict.get('new_stage_id'), cons_dict.get('objective_updates'), cons_dict.get('is_completed'), cons_dict.get('is_failed'))
                        target_entity_type_str = "Character"; log_player_id = character_id
                        if self._game_log_manager: await self._game_log_manager.log_event(guild_id, "CONSEQUENCE_QUEST_STATE_UPDATED", {"consequence": cons_dict, "quest_id": quest_id, "character_id": character_id}, log_player_id, source_entity_id, character_id, target_entity_type_str)
                        if self._notification_service and hasattr(self._notification_service, 'notify_player') and callable(getattr(self._notification_service, 'notify_player')):
                            status_str = "updated";
                            if cons_dict.get('is_completed'): status_str = "completed"
                            elif cons_dict.get('is_failed'): status_str = "failed"
                            await self._notification_service.notify_player(character_id, "quest_update", {"message": f"Quest '{quest_id}' status: {status_str}.", "quest_id": quest_id, "new_status": status_str, "source": source_entity_id or "Unknown Source"})
                    else: logger.warning(f"Missing data or QuestManager.update_quest_progress for UPDATE_QUEST_STATE: {cons_dict}")

                elif action_type == "APPLY_STATUS_EFFECT":
                    target_id = cons_dict.get('target_id', current_target_id)
                    target_type_param = cons_dict.get('target_type')
                    status_type_val = cons_dict.get('status_type')
                    if target_id and target_type_param and status_type_val and self._status_manager and hasattr(self._status_manager, 'apply_status_effect') and callable(getattr(self._status_manager, 'apply_status_effect')): # Changed from apply_status_effect to apply_status_effect
                        await self._status_manager.apply_status_effect(guild_id, target_id, target_type_param, status_type_val, cons_dict.get('duration'), cons_dict.get('source_id', source_entity_id), cons_dict.get('state_variables', {}))
                        target_entity_type_str = target_type_param.capitalize()
                        log_player_id = target_id if target_type_param.lower() == 'character' else None
                        if self._game_log_manager: await self._game_log_manager.log_event(guild_id, "CONSEQUENCE_STATUS_EFFECT_APPLIED", {"consequence": cons_dict, "target_id": target_id, "status": status_type_val}, log_player_id, source_entity_id, target_id, target_entity_type_str)
                    else: logger.warning(f"Missing data or StatusManager.apply_status_effect for APPLY_STATUS_EFFECT: {cons_dict}")

                elif action_type == "AWARD_XP":
                    char_id = cons_dict.get('character_id', current_target_id)
                    xp_amount_val = cons_dict.get('amount')
                    if not char_id: logger.warning(f"Missing character_id for AWARD_XP: {cons_dict}")
                    elif xp_amount_val is None: logger.warning(f"Missing amount for AWARD_XP: {cons_dict}")
                    else:
                        try:
                            xp_amount = int(xp_amount_val)
                            if xp_amount <= 0: logger.info(f"AWARD_XP amount is zero or negative ({xp_amount}). Skipping for char {char_id}.")
                            elif not self._character_manager or not self._rule_engine or not hasattr(self._rule_engine, 'award_experience') or not callable(getattr(self._rule_engine, 'award_experience')):
                                logger.warning(f"CharacterManager or RuleEngine.award_experience not available. Cannot award XP for AWARD_XP: {cons_dict}")
                            else:
                                character_obj = await self._character_manager.get_character(guild_id, char_id) # Await the getter
                                if character_obj:
                                    # Cast self._rule_engine to RuleEngine to satisfy Pyright after check
                                    rule_engine_checked = cast("RuleEngine", self._rule_engine)
                                    await rule_engine_checked.award_experience(character_obj, xp_amount, cons_dict.get('source_type', "quest"), guild_id, cons_dict.get('source_id', source_entity_id), **(event_context if event_context else {}))
                                    target_entity_type_str = "Character"; log_player_id = char_id
                                    if self._game_log_manager: await self._game_log_manager.log_event(guild_id, "CONSEQUENCE_XP_AWARDED", {"consequence": cons_dict, "character_id": char_id, "amount": xp_amount}, log_player_id, source_entity_id, char_id, target_entity_type_str)
                                    if self._notification_service and hasattr(self._notification_service, 'notify_player') and callable(getattr(self._notification_service, 'notify_player')):
                                        await self._notification_service.notify_player(char_id, "xp_gained", {"message": f"You gained {xp_amount} XP!", "amount": xp_amount, "source": source_entity_id or "Unknown Source"})
                                else: logger.warning(f"Character {char_id} not found for AWARD_XP: {cons_dict}")
                        except ValueError: logger.warning(f"Invalid amount '{xp_amount_val}' for AWARD_XP: {cons_dict}")
                        except Exception as e_xp: logger.error(f"Error processing AWARD_XP consequence: {cons_dict}, Exception: {e_xp}", exc_info=True)

                elif action_type == "CUSTOM_FUNCTION":
                    func_name = cons_dict.get('function_name')
                    params = cons_dict.get('params', {})
                    if func_name and func_name in self._custom_functions:
                        gs = self._game_state
                        if not gs: logger.warning(f"GameState not available for CUSTOM_FUNCTION '{func_name}'.")
                        full_params = {**params, 'guild_id': guild_id, 'source_entity_id': source_entity_id, 'target_entity_id': current_target_id, 'event_context': event_context, 'send_callback_factory': send_callback_factory}
                        await self._custom_functions[func_name](gs, full_params) # type: ignore
                        if self._game_log_manager: await self._game_log_manager.log_event(guild_id, f"CONSEQUENCE_CUSTOM_FUNC_{func_name.upper()}", {"consequence": cons_dict, "function_name": func_name, "params": params}, source_entity_id=source_entity_id, target_entity_id=current_target_id)
                    elif func_name: logger.warning(f"Custom function '{func_name}' not registered. Skipping.")
                    else: logger.warning(f"Missing function_name for CUSTOM_FUNCTION: {cons_dict}")
                else:
                    logger.warning(f"Unknown action_type '{action_type}'. Skipping: {cons_dict}")
            except Exception as e:
                logger.error(f"Error processing consequence: {cons_dict}. Exception: {e}", exc_info=True)
        logger.info(f"Finished processing consequences for guild {guild_id}.")

    async def _placeholder_send_message(self, message: str) -> None:
        print(f"[ConsequenceProcessor Send (Placeholder)] {message}")
