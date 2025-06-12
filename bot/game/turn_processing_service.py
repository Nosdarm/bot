from __future__ import annotations
import json
import traceback
import asyncio # Added for asyncio.sleep
import uuid # Added for action_id_log fallback
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Callable, Awaitable

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.models.character import Character
    from bot.game.conflict_resolver import ConflictResolver
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.services.location_interaction_service import LocationInteractionService
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.equipment_manager import EquipmentManager
    from bot.game.managers.item_manager import ItemManager # Added for USE_ITEM

from bot.database.models import PendingConflict
from bot.ai.rules_schema import CoreGameRulesConfig

class TurnProcessingService:
    def __init__(self,
                 character_manager: CharacterManager,
                 conflict_resolver: ConflictResolver,
                 rule_engine: RuleEngine,
                 game_manager: GameManager,
                 game_log_manager: GameLogManager,
                 character_action_processor: CharacterActionProcessor,
                 combat_manager: CombatManager,
                 location_manager: LocationManager,
                 location_interaction_service: LocationInteractionService,
                 dialogue_manager: DialogueManager,
                 inventory_manager: InventoryManager,
                 equipment_manager: EquipmentManager,
                 item_manager: ItemManager, # Added for USE_ITEM
                 settings: Dict[str, Any]):
        self.character_manager = character_manager
        self.conflict_resolver = conflict_resolver
        self.rule_engine = rule_engine
        self.game_manager = game_manager
        self.game_log_manager = game_log_manager
        self.character_action_processor = character_action_processor
        self.combat_manager = combat_manager
        self.location_manager = location_manager
        self.location_interaction_service = location_interaction_service
        self.dialogue_manager = dialogue_manager
        self.inventory_manager = inventory_manager
        self.equipment_manager = equipment_manager
        self.item_manager = item_manager # Added for USE_ITEM
        self.settings = settings
        print("TurnProcessingService initialized.")

    async def run_turn_cycle_check(self, guild_id: str) -> None:
        # ... (existing run_turn_cycle_check logic - assuming it's correct) ...
        print(f"TurnProcessingService: Starting turn cycle check for guild {guild_id}.")
        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type="turn_cycle_check_start",
            message=f"Turn cycle check started for guild {guild_id}.",
            metadata={"guild_id": guild_id}
        )
        all_characters_in_guild = await self.character_manager.get_all_characters(guild_id)
        if not all_characters_in_guild:
            print(f"TurnProcessingService: No characters found in guild {guild_id} during turn cycle check.")
            await self.game_log_manager.log_event(guild_id, "turn_cycle_no_characters", "No characters in guild.")
            return

        pending_players = [
            p for p in all_characters_in_guild
            if hasattr(p, 'current_game_status') and p.current_game_status == 'ожидание_обработки'
        ]
        if not pending_players:
            print(f"TurnProcessingService: No players awaiting turn processing in guild {guild_id}.")
            await self.game_log_manager.log_event(guild_id, "turn_cycle_no_pending_players", "No players awaiting processing.")
            return

        player_ids_to_process = [p.id for p in pending_players]
        updated_char_ids_for_processing = []
        for player_id in player_ids_to_process:
            char = await self.character_manager.get_character(guild_id, player_id)
            if char and getattr(char, 'current_game_status', '') == 'ожидание_обработки':
                char.current_game_status = 'обрабатывается' # type: ignore
                self.character_manager.mark_character_dirty(guild_id, player_id)
                updated_char_ids_for_processing.append(player_id)

        if not updated_char_ids_for_processing:
            await self.game_log_manager.log_event(guild_id, "turn_cycle_no_players_updated", "No players updated to processing state.")
            return
        await self.game_manager.save_game_state_after_action(guild_id, reason="Pre-turn processing status update")

        await self.process_player_turns(updated_char_ids_for_processing, guild_id)

        await self.game_log_manager.log_event(
            guild_id=guild_id, event_type="turn_cycle_check_end",
            message=f"Turn cycle check completed for guild {guild_id}.",
            metadata={"processed_player_ids": updated_char_ids_for_processing}
        )


    async def process_player_turns(self, player_ids: List[str], guild_id: str) -> Dict[str, Any]:
        print(f"TurnProcessingService: Starting to process turns for players {player_ids} in guild {guild_id}.")
        player_actions_map: Dict[str, List[Dict[str, Any]]] = {}
        turn_feedback_reports: Dict[str, List[str]] = {pid: [] for pid in player_ids}
        all_processed_action_results: List[Dict[str, Any]] = []
        action_read_delay = self.settings.get("turn_processing_action_read_delay", 0.1)

        for player_id in player_ids:
            char = await self.character_manager.get_character(guild_id, player_id)
            if not char:
                turn_feedback_reports[player_id].append("Error: Your character data was not found.")
                continue

            raw_actions_json = getattr(char, 'collected_actions_json', None)
            if raw_actions_json:
                try:
                    actions = json.loads(raw_actions_json)
                    if isinstance(actions, list) and all(isinstance(act, dict) for act in actions):
                        player_actions_map[char.id] = actions
                        setattr(char, 'collected_actions_json', None)
                        self.character_manager.mark_character_dirty(guild_id, char.id)
                    else:
                        turn_feedback_reports[player_id].append("Warning: Your collected actions were in an invalid format.")
                        player_actions_map[char.id] = []
                except json.JSONDecodeError:
                    turn_feedback_reports[player_id].append("Error: Could not parse your collected actions.")
                    player_actions_map[char.id] = []
            else:
                player_actions_map[char.id] = []

        if not player_actions_map or all(not v for v in player_actions_map.values()):
             for pid in player_ids:
                if not turn_feedback_reports[pid]: turn_feedback_reports[pid].append("Вы не подали никаких действий в этом ходу.")
             for player_id_status_update in player_ids:
                char_to_update = await self.character_manager.get_character(guild_id, player_id_status_update)
                if char_to_update:
                    setattr(char_to_update, 'current_game_status', "turn_processed_no_actions")
                    self.character_manager.mark_character_dirty(guild_id, player_id_status_update)
             await self.game_manager.save_game_state_after_action(guild_id, reason="Post-turn, no actions submitted")
             return {"status": "no_actions", "feedback_per_player": turn_feedback_reports, "processed_action_details": all_processed_action_results}

        rules_config: Optional[CoreGameRulesConfig] = None
        if self.rule_engine and hasattr(self.rule_engine, 'rules_config_data') and isinstance(self.rule_engine.rules_config_data, CoreGameRulesConfig):
            rules_config = self.rule_engine.rules_config_data

        if not rules_config:
            print(f"TPS: CRITICAL - rules_config not available for guild {guild_id}. Aborting turn processing.")
            for pid in player_ids:
                turn_feedback_reports[pid].append("Критическая ошибка: правила игры не загружены. Обработка хода прервана.")
                char_to_update_err = await self.character_manager.get_character(guild_id, pid)
                if char_to_update_err:
                    setattr(char_to_update_err, 'current_game_status', "ожидание_обработки")
                    self.character_manager.mark_character_dirty(guild_id, pid)
            await self.game_manager.save_game_state_after_action(guild_id, reason="Turn processing aborted, no rules_config")
            return {"status": "error_no_rules_config", "feedback_per_player": turn_feedback_reports}

        analysis_result = await self.conflict_resolver.analyze_actions_for_conflicts(player_actions_map, guild_id, rules_config)
        for auto_res_outcome in analysis_result.get("auto_resolution_outcomes", []):
            all_processed_action_results.append(auto_res_outcome)
            res_char_id = auto_res_outcome.get("character_id")
            res_msg = auto_res_outcome.get("execution_result", {}).get("message", "Действие было автоматически разрешено.")
            if res_char_id and res_char_id in turn_feedback_reports:
                turn_feedback_reports[res_char_id].append(res_msg)

        if analysis_result.get("requires_manual_resolution"):
            pass

        actions_to_execute = analysis_result.get("actions_to_execute", [])
        for action_item_context in actions_to_execute:
            char_id_acting = action_item_context.get("character_id")
            action_data = action_item_context.get("action_data")
            if not char_id_acting or not action_data: continue

            acting_char = await self.character_manager.get_character(guild_id, char_id_acting)
            if not acting_char:
                turn_feedback_reports[char_id_acting].append("Ошибка: Ваш персонаж не найден для выполнения действия.")
                continue

            intent_type = action_data.get("intent_type", action_data.get("intent", "unknown_intent"))
            action_id_log = action_data.get("action_id", f"action_{uuid.uuid4().hex[:6]}")
            action_execution_result: Dict[str, Any] = {"success": False, "message": f"Действие '{intent_type}' не реализовано.", "state_changed": False}

            db_service = self.game_manager.db_service
            transaction_begun = False
            normalized_intent_type = intent_type.upper()

            try:
                if normalized_intent_type == "MOVE":
                    if db_service: await db_service.begin_transaction(); transaction_begun = True
                    target_entity = next((e for e in action_data.get("entities", []) if e.get("type") in ["location_name", "location_id", "portal_id"]), None)
                    if target_entity:
                        action_execution_result = await self.character_action_processor.handle_move_action(acting_char, target_entity, guild_id)
                    else:
                        action_execution_result = {"success": False, "message": "Куда идти? Цель не ясна.", "state_changed": False}

                elif normalized_intent_type == "ATTACK":
                    if db_service: await db_service.begin_transaction(); transaction_begun = True
                    action_execution_result = await self.character_action_processor.handle_attack_action(
                        character_attacker=acting_char, guild_id=guild_id, action_data=action_data, rules_config=rules_config
                    )

                elif normalized_intent_type == "TALK":
                    action_execution_result = await self.dialogue_manager.handle_talk_action(
                        character_speaker=acting_char, guild_id=guild_id, action_data=action_data, rules_config=rules_config
                    )

                elif normalized_intent_type == "USE_ITEM": # Corrected: Call ItemManager for use_item
                    if db_service: await db_service.begin_transaction(); transaction_begun = True
                    # ItemManager.use_item expects character_user (Character object) and item_template_id
                    # NLU should provide item_template_id or item_instance_id.
                    # If instance_id is provided, need to get template_id from it.
                    item_entity = next((e for e in action_data.get("entities", []) if e.get("type") in ["item", "item_template_id", "item_instance_id"]), None)
                    target_entity_data = next((e for e in action_data.get("entities", []) if e.get("type") in ["character", "npc", "player_character"]), None)

                    actual_target_entity_obj = None
                    if target_entity_data:
                        if target_entity_data.get("type") == "character" or target_entity_data.get("type") == "player_character":
                            actual_target_entity_obj = await self.character_manager.get_character(guild_id, target_entity_data.get("id"))
                        elif target_entity_data.get("type") == "npc":
                            # Assuming NpcManager has get_npc method
                            if hasattr(self.character_action_processor, '_npc_manager') and self.character_action_processor._npc_manager: # type: ignore
                                actual_target_entity_obj = await self.character_action_processor._npc_manager.get_npc(guild_id, target_entity_data.get("id")) # type: ignore

                    if item_entity and item_entity.get("id"):
                        item_id_from_nlu = item_entity.get("id")
                        # Determine if it's instance_id or template_id (NLU needs to be clear)
                        # For now, assume ItemManager.use_item can handle template_id
                        # If it's an instance_id, InventoryManager might be involved first to get template_id
                        action_execution_result = await self.item_manager.use_item( # Changed from inventory_manager
                            guild_id=guild_id, character_user=acting_char,
                            item_template_id=item_id_from_nlu, # Assuming NLU gives template_id for use
                            rules_config=rules_config,
                            target_entity=actual_target_entity_obj
                        )
                    else:
                        action_execution_result = {"success": False, "message": "Какой предмет использовать?", "state_changed": False}

                elif normalized_intent_type == "EQUIP":
                    if db_service: await db_service.begin_transaction(); transaction_begun = True
                    action_execution_result = await self.character_action_processor.handle_equip_item_action(
                        character=acting_char, guild_id=guild_id, action_data=action_data, rules_config=rules_config
                    )

                elif normalized_intent_type == "UNEQUIP":
                    if db_service: await db_service.begin_transaction(); transaction_begun = True
                    action_execution_result = await self.character_action_processor.handle_unequip_item_action(
                        character=acting_char, guild_id=guild_id, action_data=action_data, rules_config=rules_config
                    )

                elif normalized_intent_type == "DROP_ITEM":
                    if db_service: await db_service.begin_transaction(); transaction_begun = True
                    action_execution_result = await self.character_action_processor.handle_drop_item_action(
                        character=acting_char, guild_id=guild_id, action_data=action_data, rules_config=rules_config
                    )

                elif normalized_intent_type == "LOOK":
                    entities_for_look = action_data.get("entities", [])
                    action_execution_result = await self.character_action_processor.handle_explore_action(
                        character=acting_char, guild_id=guild_id, action_params={'entities': entities_for_look}
                    )
                    action_execution_result["state_changed"] = False

                elif normalized_intent_type == "SKILL_USE":
                    skill_id_entity = next((e for e in action_data.get("entities", []) if e.get("type") == "skill_name"), None)
                    skill_id = skill_id_entity.get("value") if skill_id_entity else action_data.get("skill_id")
                    target_entity = next((e for e in action_data.get("entities", []) if e.get("type") not in ["skill_name"]), None)
                    if skill_id:
                        action_execution_result = await self.character_action_processor.handle_skill_use_action(
                            acting_char, skill_id, target_entity, action_data, guild_id
                        )
                    else: action_execution_result = {"success": False, "message": "Какое умение использовать?", "state_changed": False}

                elif normalized_intent_type == "PICKUP_ITEM" or normalized_intent_type == "PICKUP":
                    if db_service: await db_service.begin_transaction(); transaction_begun = True
                    item_entity = next((e for e in action_data.get("entities", []) if e.get("type") in ["item_name", "item_id", "item"]), None)
                    if item_entity:
                        action_execution_result = await self.character_action_processor.handle_pickup_item_action(
                            acting_char, item_entity, guild_id
                        )
                    else: action_execution_result = {"success": False, "message": "Что подобрать?", "state_changed": False}

                elif normalized_intent_type in ["EXPLORE", "LOOK_AROUND", "SEARCH_AREA", "SEARCH"]:
                    entities_for_explore = action_data.get("entities", [])
                    action_execution_result = await self.character_action_processor.handle_explore_action(
                        character=acting_char, guild_id=guild_id, action_params={'entities': entities_for_explore}
                    )
                    action_execution_result["state_changed"] = False

                elif normalized_intent_type in ["INTERACT_OBJECT", "USE_SKILL_ON_OBJECT", "MOVE_TO_INTERACTIVE_FEATURE", "USE_ITEM_ON_OBJECT"]:
                    if db_service: await db_service.begin_transaction(); transaction_begun = True
                    action_execution_result = await self.location_interaction_service.process_interaction(
                        guild_id=guild_id, character_id=acting_char.id,
                        action_data=action_data, rules_config=rules_config)

                else:
                    await self.game_log_manager.log_event(guild_id=guild_id,event_type="action_dispatch_unhandled",
                        message=f"Player {char_id_acting} action '{intent_type}' unhandled.", metadata={"action_data": action_data})
                    action_execution_result = {"success": False, "message": f"Действие '{intent_type}' пока не поддерживается.", "state_changed": False}

                if transaction_begun and db_service:
                    if action_execution_result.get("success") and action_execution_result.get("state_changed", False):
                        await db_service.commit_transaction()
                    elif action_execution_result.get("state_changed", False):
                        await db_service.rollback_transaction()
                    else:
                        await db_service.rollback_transaction()
                transaction_begun = False

            except Exception as e_action:
                print(f"TPS: Exception during {normalized_intent_type} action {action_id_log} for {char_id_acting}: {e_action}")
                traceback.print_exc()
                if transaction_begun and db_service:
                    await db_service.rollback_transaction()
                action_execution_result = {"success": False, "message": f"Внутренняя ошибка при выполнении '{intent_type}': {str(e_action)}", "state_changed": False, "error": True}

            finally:
                if transaction_begun and db_service and hasattr(db_service, 'is_transaction_active') and db_service.is_transaction_active(): # type: ignore
                    print(f"TPS: WARNING - Transaction for action {action_id_log} ({normalized_intent_type}) was still active in finally block. Rolling back.")
                    await db_service.rollback_transaction()

            await self.game_log_manager.log_event(
                guild_id=guild_id, event_type="action_executed",
                message=f"Player {char_id_acting} action '{intent_type}' result: {action_execution_result.get('success')}. Msg: {action_execution_result.get('message')}",
                metadata={"action_data": action_data, "execution_result": action_execution_result}
            )
            if char_id_acting in turn_feedback_reports:
                turn_feedback_reports[char_id_acting].append(action_execution_result.get("message", "Действие обработано с неизвестным результатом."))
            all_processed_action_results.append({"character_id": char_id_acting, "action_data": action_data, "execution_result": action_execution_result})

            if action_execution_result.get("success") and action_execution_result.get("state_changed", False):
                await self.game_manager.save_game_state_after_action(guild_id, reason=f"Post-action: {normalized_intent_type}")

        for player_id_status_update in player_ids:
            char_to_update = await self.character_manager.get_character(guild_id, player_id_status_update)
            if char_to_update:
                final_status = "turn_processed"
                player_actions_this_turn = [res for res in all_processed_action_results if res.get("character_id") == player_id_status_update]
                if any(res.get("execution_result", {}).get("requires_gm_review", False) for res in player_actions_this_turn):
                    final_status = "awaiting_gm_resolution"
                elif not player_actions_map.get(player_id_status_update) and not any("Error" in msg for msg in turn_feedback_reports.get(player_id_status_update, [])):
                    final_status = "turn_processed_no_actions"

                setattr(char_to_update, 'current_game_status', final_status)
                self.character_manager.mark_character_dirty(guild_id, player_id_status_update)

        await self.game_manager.save_game_state_after_action(guild_id, reason="End of turn processing cycle")

        await self.game_log_manager.log_event(
            guild_id=guild_id, event_type="turn_processing_end",
            message=f"Turn processing finished for players: {player_ids}.",
            metadata={"player_ids": player_ids, "num_results": len(all_processed_action_results)}
        )
        return {"status": "completed", "feedback_per_player": turn_feedback_reports, "processed_action_details": all_processed_action_results}
