from __future__ import annotations
import json
import traceback
import asyncio # Added for asyncio.sleep
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Callable, Awaitable

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.conflict_resolver import ConflictResolver
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.game_log_manager import GameLogManager
    # Forward declare other managers that will be needed for action dispatch
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.services.location_interaction_service import LocationInteractionService # Added
    # from bot.services.notification_service import NotificationService # For player feedback

from bot.database.models import PendingConflict # Import for manual conflict resolution
from bot.ai.rules_schema import CoreGameRulesConfig # For accessing conflict rules

class TurnProcessingService:
    def __init__(self,
                 character_manager: CharacterManager,
                 conflict_resolver: ConflictResolver,
                 rule_engine: RuleEngine,
                 game_manager: GameManager, # Full GameManager for save_game_state_after_action
                 game_log_manager: GameLogManager,
                 # Action dispatchers - specific managers for executing actions
                 character_action_processor: CharacterActionProcessor,
                 combat_manager: CombatManager,
                 location_manager: LocationManager,
                 location_interaction_service: LocationInteractionService, # Added
                 # notification_service: NotificationService # If sending direct feedback to players
                 settings: Dict[str, Any]):
        self.character_manager = character_manager
        self.conflict_resolver = conflict_resolver
        self.rule_engine = rule_engine
        self.game_manager = game_manager
        self.game_log_manager = game_log_manager
        self.character_action_processor = character_action_processor
        self.combat_manager = combat_manager
        self.location_manager = location_manager
        self.location_interaction_service = location_interaction_service # Added
        # self.notification_service = notification_service
        self.settings = settings
        print("TurnProcessingService initialized.")

    async def run_turn_cycle_check(self, guild_id: str) -> None:
        """
        Checks for players awaiting turn processing and initiates processing for them.
        This is intended to be called periodically by the game loop or an event.
        """
        print(f"TurnProcessingService: Starting turn cycle check for guild {guild_id}.")
        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type="turn_cycle_check_start",
            message=f"Turn cycle check started for guild {guild_id}.",
            metadata={"guild_id": guild_id}
        )

        # Dependency: self.character_manager.get_all_characters(guild_id)
        # Assuming it returns List[CharacterModel]
        # For this subtask, if it doesn't exist, this part would need mocking.
        # Let's assume it exists and works as expected for now.
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
        print(f"TurnProcessingService: Players to process in guild {guild_id}: {player_ids_to_process}")
        await self.game_log_manager.log_event(
            guild_id,
            "turn_cycle_players_to_process",
            f"Found {len(player_ids_to_process)} players for processing.",
            {"player_ids": player_ids_to_process}
        )

        # Crucially, update status BEFORE processing to prevent race conditions
        # if the cycle runs again quickly.
        updated_char_ids_for_processing = []
        for player_id in player_ids_to_process:
            char = await self.character_manager.get_character(guild_id, player_id)
            if char and getattr(char, 'current_game_status', '') == 'ожидание_обработки':
                char.current_game_status = 'обрабатывается'
                self.character_manager.mark_character_dirty(guild_id, player_id) # mark_character_dirty instead of mark_dirty
                updated_char_ids_for_processing.append(player_id)
            else:
                print(f"TurnProcessingService: Warning - Player {player_id} status changed or char not found before 'обрабатывается' update.")

        if not updated_char_ids_for_processing:
            print(f"TurnProcessingService: No players were successfully updated to 'обрабатывается'. Aborting processing for this cycle.")
            await self.game_log_manager.log_event(guild_id, "turn_cycle_no_players_updated", "No players updated to processing state.")
            return

        # Persist status changes immediately
        print(f"TurnProcessingService: Saving game state for guild {guild_id} after marking players as 'обрабатывается'.")
        await self.game_manager.save_game_state_after_action(guild_id)

        # Now process turns for those whose status was successfully updated
        # (or all in player_ids_to_process if we are optimistic that mark_dirty + save worked)
        # Using updated_char_ids_for_processing is safer.
        print(f"TurnProcessingService: Calling process_player_turns for players: {updated_char_ids_for_processing}")
        await self.process_player_turns(updated_char_ids_for_processing, guild_id)

        print(f"TurnProcessingService: Turn cycle check completed for guild {guild_id}.")
        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type="turn_cycle_check_end",
            message=f"Turn cycle check completed for guild {guild_id}.",
            metadata={"processed_player_ids": updated_char_ids_for_processing}
        )

    async def process_player_turns(self, player_ids: List[str], guild_id: str) -> Dict[str, Any]:
        """
        Processes turns for a list of players in a given guild.
        1. Collects all actions.
        2. Analyzes for conflicts.
        3. Executes non-conflicting or resolved actions.
        4. Saves state after each action.
        5. Reports outcomes.
        """
        print(f"TurnProcessingService: Starting to process turns for players {player_ids} in guild {guild_id}.")
        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type="turn_processing_start",
            message=f"Turn processing started for players: {player_ids}.",
            metadata={"player_ids": player_ids}
        )

        player_actions_map: Dict[str, List[Dict[str, Any]]] = {}
        turn_feedback_reports: Dict[str, List[str]] = {pid: [] for pid in player_ids} # Player_id -> List of feedback strings
        all_processed_action_results: List[Dict[str, Any]] = []

        # --- 1. Action Collection Phase ---
        action_read_delay = self.settings.get("turn_processing_action_read_delay", 0.5) # Get delay from settings or default
        for player_id in player_ids:
            char = await self.character_manager.get_character(guild_id, player_id)

            # Add small delay before reading char.collected_actions_json
            await asyncio.sleep(action_read_delay)

            if not char:
                print(f"TurnProcessingService: Character {player_id} not found in guild {guild_id} after delay. Skipping.")
                await self.game_log_manager.log_event(guild_id, "turn_processing_char_not_found", f"Character {player_id} not found post-delay.", {"player_id": player_id})
                turn_feedback_reports[player_id].append("Error: Your character data was not found.")
                continue

            if char.collected_actions_json:
                try:
                    actions = json.loads(char.collected_actions_json)
                    if isinstance(actions, list) and all(isinstance(act, dict) for act in actions):
                        player_actions_map[char.id] = actions
                        print(f"TurnProcessingService: Collected {len(actions)} actions for player {char.id}.")
                        await self.game_log_manager.log_event(guild_id, "actions_collected", f"Collected {len(actions)} for player {char.id}.", {"player_id": char.id, "num_actions": len(actions)})

                        # Clear actions from character object immediately after successful load into memory
                        char.collected_actions_json = None
                        self.character_manager.mark_character_dirty(guild_id, char.id)
                        print(f"TurnProcessingService: Cleared collected_actions_json for player {char.id} and marked dirty.")
                    else:
                        print(f"TurnProcessingService: Warning: Parsed collected_actions_json for player {char.id} is not a list of dicts. Found: {type(actions)}")
                        await self.game_log_manager.log_event(guild_id, "actions_invalid_format", f"Collected actions for {char.id} not list of dicts.", {"player_id": char.id, "type": str(type(actions))})
                        turn_feedback_reports[player_id].append("Warning: Your collected actions were in an invalid format.")
                        player_actions_map[char.id] = []
                except json.JSONDecodeError as e:
                    print(f"TurnProcessingService: Error decoding collected_actions_json for player {char.id}: {e}")
                    await self.game_log_manager.log_event(guild_id, "actions_decode_error", f"Error decoding actions for {char.id}.", {"player_id": char.id, "error": str(e)})
                    turn_feedback_reports[player_id].append("Error: Could not parse your collected actions.")
                    player_actions_map[char.id] = []
            else: # No char.collected_actions_json or it was empty
                print(f"TurnProcessingService: No actions collected for player {char.id} from char.collected_actions_json.")
                log_message = f"Player {char.id} had no actions in collected_actions_json. Original status might have been 'ожидание_обработки' and NLU processing might have been too slow or failed before this read."
                await self.game_log_manager.log_event(guild_id, "empty_action_queue_on_processing", log_message, {"player_id": char.id})

                if char.id in turn_feedback_reports:
                    turn_feedback_reports[char.id].append(
                        "No actions were detected for your turn. If you submitted actions recently, they might be processed in the next cycle. If this persists, please use /end_turn again or contact a GM."
                    )
                player_actions_map[char.id] = []

            # The clearing of char.collected_actions_json is now done right after successful loading (if actions were present)
            # or implicitly remains None/empty if they were not present or invalid.
            # The mark_dirty call is also done at the point of clearing or after processing the loaded JSON.
            # No need for the separate hasattr(char, 'clear_collected_actions') block here anymore for this specific purpose.
            # self.character_manager.mark_character_dirty(guild_id, char.id) # This is already called above if actions were loaded and cleared.

        if not player_actions_map or all(not v for v in player_actions_map.values()):
            print(f"TurnProcessingService: No actions found for any players in {player_ids}. Ending turn processing early.")
            await self.game_log_manager.log_event(guild_id, "turn_processing_no_actions_total", "No actions from any player.", {"player_ids": player_ids})
            for pid in player_ids:
                if not turn_feedback_reports[pid]: turn_feedback_reports[pid].append("You submitted no actions this turn.")
            # Update statuses before returning
            for player_id_status_update in player_ids:
                char_to_update = await self.character_manager.get_character(guild_id, player_id_status_update)
                if char_to_update:
                    char_to_update.current_game_status = "turn_processed_no_actions"
                    self.character_manager.mark_character_dirty(guild_id, player_id_status_update)
            await self.game_manager.save_game_state_after_action(guild_id) # Save status updates
            return {"status": "no_actions", "feedback_per_player": turn_feedback_reports, "processed_action_details": all_processed_action_results}

        # --- 2. Conflict Analysis & Resolution Phase ---
        # Load CoreGameRulesConfig
        rules_config: Optional[CoreGameRulesConfig] = None
        if self.rule_engine and hasattr(self.rule_engine, 'rules_config_data') and isinstance(self.rule_engine.rules_config_data, CoreGameRulesConfig):
            rules_config = self.rule_engine.rules_config_data

        if not rules_config:
            print(f"TurnProcessingService: CRITICAL - CoreGameRulesConfig not available for guild {guild_id}. Conflict resolution will be basic.")
            # Fallback to basic conflict analysis if rules are missing
            analysis_result = await self.conflict_resolver.analyze_actions_for_conflicts(player_actions_map, guild_id, None) # Pass None for rules_config
        else:
            # Pass rules_config to conflict_resolver (assuming it's updated to accept it)
            # For this subtask, we'll assume analyze_actions_for_conflicts is updated to use rules_config
            # and its return structure for "pending_conflict_details" is enhanced.
            print(f"TurnProcessingService: Analyzing actions for conflicts with rules. Action map: {json.dumps(player_actions_map, indent=2)}")
            analysis_result = await self.conflict_resolver.analyze_actions_for_conflicts(player_actions_map, guild_id, rules_config)

        for auto_res_outcome in analysis_result.get("auto_resolution_outcomes", []):
            involved_chars = [act_ctx["character_id"] for act_ctx in auto_res_outcome.get("involved_actions", [])]
            outcome_desc = auto_res_outcome.get('outcome', {}).get('description', 'Details unavailable.')
            for char_id_involved in involved_chars:
                if char_id_involved in turn_feedback_reports:
                    turn_feedback_reports[char_id_involved].append(f"Conflict involving your action was automatically resolved. Outcome: {outcome_desc}")
            all_processed_action_results.append(auto_res_outcome)

        if analysis_result.get("requires_manual_resolution"):
            print(f"TurnProcessingService: Manual resolution required for conflicts in guild {guild_id}.")
            db_service = self.game_manager.db_service # Assuming db_service is on game_manager
            if not db_service:
                print(f"TurnProcessingService: CRITICAL - DBService not available. Cannot save pending manual conflicts for guild {guild_id}.")
                # Handle this case: maybe all affected actions fail, or log extensively.
                # For now, players will get a generic "GM review" message but conflict won't be saved to DB.

            for conflict_detail in analysis_result.get("pending_conflict_details", []):
                # Assuming conflict_detail now contains necessary data due to ConflictResolver enhancements:
                # conflict_detail = {
                #     'conflict_type_id': 'some_conflict_rule_type',
                #     'involved_actions': [{'character_id': 'player1', 'action_data': {...}}, ...],
                #     'description': 'A summary of the conflict for GM'
                # }
                conflict_type_id = conflict_detail.get('conflict_type_id', 'unknown_manual_conflict')
                involved_actions_data = conflict_detail.get('involved_actions', [])
                conflict_description = conflict_detail.get('description', 'A conflict requires GM attention.')

                involved_player_ids = list(set(act_ctx['character_id'] for act_ctx in involved_actions_data))

                conflict_data_to_store = {
                    "conflict_type_id": conflict_type_id,
                    "involved_player_ids": involved_player_ids,
                    "involved_actions_details": involved_actions_data, # Storing the actions themselves
                    "description_for_gm": conflict_description,
                    "resolution_options": conflict_detail.get("manual_resolution_options") # If provided by ConflictResolver
                }

                if db_service:
                    try:
                        new_conflict_db_entry = PendingConflict(
                            guild_id=guild_id,
                            conflict_data_json=json.dumps(conflict_data_to_store), # Serialize to JSON string
                            status='pending_gm_resolution'
                        )
                        await db_service.add_entity(new_conflict_db_entry) # Assumes a generic add_entity method
                        conflict_db_id = new_conflict_db_entry.id
                        log_message = f"Manual conflict (Type: {conflict_type_id}, DB ID: {conflict_db_id}) detected and saved. Involved players: {involved_player_ids}. GM intervention required."
                        feedback_message_for_player = f"Your action is part of a conflict (Ref: {conflict_db_id[-8:]}) that requires Game Master review. It will be processed once resolved."
                    except Exception as e:
                        log_message = f"Manual conflict (Type: {conflict_type_id}) detected but FAILED TO SAVE to DB. Error: {e}. Involved players: {involved_player_ids}."
                        feedback_message_for_player = f"Your action is part of a conflict that requires Game Master review, but there was an issue logging the details. Please inform your GM."
                        traceback.print_exc()
                else: # No DB service
                    log_message = f"Manual conflict (Type: {conflict_type_id}) detected but DBService not available to save. Involved players: {involved_player_ids}."
                    feedback_message_for_player = "Your action is part of a conflict that requires Game Master review. It will be processed once resolved (logging to DB failed)."

                print(f"TurnProcessingService: {log_message}")
                await self.game_log_manager.log_event(guild_id, "manual_conflict_detected", log_message, conflict_data_to_store)

                for char_id_manual in involved_player_ids:
                    if char_id_manual in turn_feedback_reports:
                        turn_feedback_reports[char_id_manual].append(feedback_message_for_player)

                # Add the raw conflict_detail to results for now, as it's what ConflictResolver produced.
                # This might be redundant if a DB ID is now the primary reference.
                all_processed_action_results.append({
                    "type": "manual_conflict_deferred",
                    "conflict_data": conflict_detail, # Original data from ConflictResolver
                    "db_id": getattr(new_conflict_db_entry, 'id', None) if 'new_conflict_db_entry' in locals() else None
                })


        # --- 3. Action Execution Phase ---
        # Actions that were part of a manual conflict should have been filtered out
        # by ConflictResolver from the 'actions_to_execute' list.
        actions_to_execute = analysis_result.get("actions_to_execute", [])
        print(f"TurnProcessingService: Executing {len(actions_to_execute)} non-conflicting/resolved actions.")
        await self.game_log_manager.log_event(guild_id, "action_execution_start", f"Executing {len(actions_to_execute)} actions.", {"count": len(actions_to_execute)})

        if not actions_to_execute and not analysis_result.get("requires_manual_resolution") and not analysis_result.get("auto_resolution_outcomes"):
            print(f"TurnProcessingService: No actions to execute and no new conflicts. All original actions might have been invalid or empty.")
            await self.game_log_manager.log_event(guild_id, "turn_processing_no_actions_to_execute", "No actions to execute and no conflicts.")
            for pid in player_ids:
                if not turn_feedback_reports[pid]:
                    turn_feedback_reports[pid].append("No actions were processed this turn (they may have been invalid or part of an unresolvable conflict).")

        for action_item_context in actions_to_execute:
            char_id_acting = action_item_context.get("character_id")
            action_data = action_item_context.get("action_data")

            if not char_id_acting or not action_data:
                print(f"TurnProcessingService: Invalid action item context: {action_item_context}. Skipping.")
                await self.game_log_manager.log_event(guild_id, "action_execution_invalid_context", "Invalid action context.", {"context": action_item_context})
                continue

            acting_char = await self.character_manager.get_character(guild_id, char_id_acting)
            if not acting_char:
                print(f"TurnProcessingService: Character {char_id_acting} not found for executing action. Skipping.")
                if char_id_acting in turn_feedback_reports:
                    turn_feedback_reports[char_id_acting].append("Error: Your character data was not found when trying to execute your action.")
                await self.game_log_manager.log_event(guild_id, "action_execution_char_not_found", f"Character {char_id_acting} not found for execution.", {"player_id": char_id_acting})
                continue

            intent_type = action_data.get("intent_type", action_data.get("intent", "unknown_intent"))
            action_id_log = action_data.get("action_id", f"action_{traceback.extract_stack(limit=1)[0].lineno}") # temp unique id

            print(f"TurnProcessingService: Preparing to execute action '{intent_type}' (ID: {action_id_log}) for character {char_id_acting}.")
            action_execution_result: Dict[str, Any] = {"success": False, "message": f"Intent '{intent_type}' not implemented in TurnProcessingService dispatcher.", "state_changed": False}

            try:
                # ** Refined Action Dispatch Logic **
                normalized_intent_type = intent_type.upper() # Normalize intent for consistent matching

                # Example: Applying transaction logic to the 'MOVE' intent
                if normalized_intent_type == "MOVE":
                    transaction_begun = False
                    db_service = self.game_manager.db_service # Get DBService instance
                    try:
                        if db_service:
                            await db_service.begin_transaction()
                            transaction_begun = True

                        target_destination_entity = next((e for e in action_data.get("entities", []) if e.get("type") in ["location_name", "location_id", "portal_id"]), None)
                        if target_destination_entity:
                            action_execution_result = await self.character_action_processor.handle_move_action(
                                character=acting_char,
                                destination_entity=target_destination_entity,
                                guild_id=guild_id
                            )
                        else:
                            action_execution_result = {"success": False, "message": "You decided to move but didn't specify a valid destination.", "state_changed": False}

                        if transaction_begun and db_service:
                            if action_execution_result.get("success", False) and action_execution_result.get("state_changed", False):
                                await db_service.commit_transaction()
                                print(f"TurnProcessingService: Action {action_id_log} (MOVE) for {char_id_acting} committed.") # Using print for now, replace with logging
                            elif action_execution_result.get("state_changed", False): # Failed but state_changed was true
                                await db_service.rollback_transaction()
                                print(f"TurnProcessingService: Action {action_id_log} (MOVE) for {char_id_acting} rolled back due to failure with state change.")
                            else: # No state change, or no success and no state change
                                await db_service.rollback_transaction()
                                print(f"TurnProcessingService: Action {action_id_log} (MOVE) for {char_id_acting} was read-only or failed without state change; transaction ended (rolled back).")

                    except Exception as e_action_move:
                        print(f"TurnProcessingService: Exception during MOVE action {action_id_log} for {char_id_acting}: {e_action_move}") # Replace with logging
                        traceback.print_exc()
                        if transaction_begun and db_service:
                            await db_service.rollback_transaction()
                            print(f"TurnProcessingService: Action {action_id_log} (MOVE) for {char_id_acting} rolled back due to exception.")
                        action_execution_result = {"success": False, "message": f"An internal error occurred while moving: {e_action_move}", "state_changed": False, "error": True}

                # --- Template for other action handlers ---
                # elif intent_type == "SOME_OTHER_ACTION":
                #     transaction_begun = False
                #     db_service = self.game_manager.db_service
                #     try:
                #         if db_service:
                #             await db_service.begin_transaction()
                #             transaction_begun = True
                #
                #         # *** ACTION HANDLER CALL ***
                #         # action_execution_result = await self.some_other_handler.process(...)
                #
                #         if transaction_begun and db_service:
                #             if action_execution_result.get("success") and action_execution_result.get("state_changed"):
                #                 await db_service.commit_transaction()
                #                 print(f"TPS: Action {action_id_log} ({intent_type}) for {char_id_acting} committed.")
                #             elif action_execution_result.get("state_changed"):
                #                 await db_service.rollback_transaction()
                #                 print(f"TPS: Action {action_id_log} ({intent_type}) for {char_id_acting} rolled back (failure with state change).")
                #             else:
                #                 await db_service.rollback_transaction()
                #                 print(f"TPS: Action {action_id_log} ({intent_type}) for {char_id_acting} transaction ended (read-only/no state change).")
                #     except Exception as e_action_other:
                #         print(f"TPS: Exception during {intent_type} action {action_id_log} for {char_id_acting}: {e_action_other}")
                #         traceback.print_exc()
                #         if transaction_begun and db_service:
                #             await db_service.rollback_transaction()
                #             print(f"TPS: Action {action_id_log} ({intent_type}) for {char_id_acting} rolled back due to exception.")
                #         action_execution_result = {"success": False, "message": f"Internal error: {e_action_other}", "state_changed": False, "error": True}
                # --- End Template ---

                elif intent_type == "SKILL_USE":
                    transaction_begun = False
                    db_service = self.game_manager.db_service
                    try:
                        if db_service: await db_service.begin_transaction(); transaction_begun = True
                        skill_id = action_data.get("skill_id")
                        if not skill_id: skill_entity = next((e for e in action_data.get("entities", []) if e.get("type") == "skill_name"), None); \
                                         if skill_entity: skill_id = skill_entity.get("value")
                        target_entity = next((e for e in action_data.get("entities", []) if e.get("type") not in ["skill_name"]), None)
                        if skill_id:
                            action_execution_result = await self.character_action_processor.handle_skill_use_action(
                                character=acting_char, skill_id=skill_id, target_entity=target_entity,
                                action_params=action_data, guild_id=guild_id)
                        else: action_execution_result = {"success": False, "message": "Skill unclear.", "state_changed": False}
                        if transaction_begun and db_service:
                            if action_execution_result.get("success") and action_execution_result.get("state_changed"): await db_service.commit_transaction(); print(f"TPS: SKILL_USE {action_id_log} committed.")
                            elif action_execution_result.get("state_changed"): await db_service.rollback_transaction(); print(f"TPS: SKILL_USE {action_id_log} rolled back (fail with state change).")
                            else: await db_service.rollback_transaction(); print(f"TPS: SKILL_USE {action_id_log} transaction ended.")
                    except Exception as e_action_skill:
                        print(f"TPS: Exception SKILL_USE {action_id_log}: {e_action_skill}"); traceback.print_exc()
                        if transaction_begun and db_service: await db_service.rollback_transaction(); print(f"TPS: SKILL_USE {action_id_log} rolled back by exception.")
                        action_execution_result = {"success": False, "message": f"Internal error: {e_action_skill}", "state_changed": False, "error": True}

                elif intent_type == "PICKUP_ITEM" or intent_type == "PICKUP":
                    transaction_begun = False
                    db_service = self.game_manager.db_service
                    try:
                        if db_service: await db_service.begin_transaction(); transaction_begun = True
                        item_entity = next((e for e in action_data.get("entities", []) if e.get("type") in ["item_name", "item_id"]), None)
                        if item_entity:
                            action_execution_result = await self.character_action_processor.handle_pickup_item_action(
                                character=acting_char, item_entity=item_entity, guild_id=guild_id)
                        else: action_execution_result = {"success": False, "message": "Item unclear for pickup.", "state_changed": False}
                        if transaction_begun and db_service:
                            if action_execution_result.get("success") and action_execution_result.get("state_changed"): await db_service.commit_transaction(); print(f"TPS: PICKUP {action_id_log} committed.")
                            elif action_execution_result.get("state_changed"): await db_service.rollback_transaction(); print(f"TPS: PICKUP {action_id_log} rolled back (fail with state change).")
                            else: await db_service.rollback_transaction(); print(f"TPS: PICKUP {action_id_log} transaction ended.")
                    except Exception as e_action_pickup:
                        print(f"TPS: Exception PICKUP {action_id_log}: {e_action_pickup}"); traceback.print_exc()
                        if transaction_begun and db_service: await db_service.rollback_transaction(); print(f"TPS: PICKUP {action_id_log} rolled back by exception.")
                        action_execution_result = {"success": False, "message": f"Internal error: {e_action_pickup}", "state_changed": False, "error": True}

                elif intent_type == "EXPLORE" or intent_type == "LOOK_AROUND" or intent_type == "SEARCH_AREA" or intent_type == "SEARCH":
                    transaction_begun = False
                    db_service = self.game_manager.db_service
                    try:
                        if db_service: await db_service.begin_transaction(); transaction_begun = True
                        action_execution_result = await self.character_action_processor.handle_explore_action(
                            character=acting_char, guild_id=guild_id, action_params=action_data)
                        if transaction_begun and db_service: # Explore is usually read-only or changes non-DB state locally first
                            if action_execution_result.get("success") and action_execution_result.get("state_changed"): await db_service.commit_transaction(); print(f"TPS: EXPLORE {action_id_log} committed.")
                            else: await db_service.rollback_transaction(); print(f"TPS: EXPLORE {action_id_log} transaction ended (read-only or no state change).")
                    except Exception as e_action_explore:
                        print(f"TPS: Exception EXPLORE {action_id_log}: {e_action_explore}"); traceback.print_exc()
                        if transaction_begun and db_service: await db_service.rollback_transaction(); print(f"TPS: EXPLORE {action_id_log} rolled back by exception.")
                        action_execution_result = {"success": False, "message": f"Internal error: {e_action_explore}", "state_changed": False, "error": True}

                elif intent_type in ["INTERACT_OBJECT", "USE_SKILL_ON_OBJECT", "MOVE_TO_INTERACTIVE_FEATURE", "USE_ITEM_ON_OBJECT"]:
                    transaction_begun = False
                    db_service = self.game_manager.db_service
                    try:
                        if db_service: await db_service.begin_transaction(); transaction_begun = True
                        if not rules_config: action_execution_result = {"success": False, "message": "Game rules not available for interaction.", "state_changed": False}
                        else:
                            action_execution_result = await self.location_interaction_service.process_interaction(
                                guild_id=guild_id, character_id=acting_char.id,
                                action_data=action_data, rules_config=rules_config)
                        if transaction_begun and db_service:
                            if action_execution_result.get("success") and action_execution_result.get("state_changed"): await db_service.commit_transaction(); print(f"TPS: LIS Interaction {action_id_log} committed.")
                            elif action_execution_result.get("state_changed"): await db_service.rollback_transaction(); print(f"TPS: LIS Interaction {action_id_log} rolled back (fail with state change).")
                            else: await db_service.rollback_transaction(); print(f"TPS: LIS Interaction {action_id_log} transaction ended.")
                    except Exception as e_action_lis:
                        print(f"TPS: Exception LIS Interaction {action_id_log}: {e_action_lis}"); traceback.print_exc()
                        if transaction_begun and db_service: await db_service.rollback_transaction(); print(f"TPS: LIS Interaction {action_id_log} rolled back by exception.")
                        action_execution_result = {"success": False, "message": f"Internal error: {e_action_lis}", "state_changed": False, "error": True}

                elif normalized_intent_type == "ATTACK":
                    transaction_begun = False
                    db_service = self.game_manager.db_service
                    try:
                        if db_service: await db_service.begin_transaction(); transaction_begun = True
                        # Placeholder: Dispatch to CharacterActionProcessor.handle_attack_action
                        # action_execution_result = await self.character_action_processor.handle_attack_action(
                        #     character=acting_char, action_data=action_data, guild_id=guild_id,
                        #     combat_manager=self.combat_manager, rules_config=rules_config
                        # )
                        action_execution_result = {"success": False, "message": f"Attack action placeholder for {acting_char.id}.", "state_changed": False} # Placeholder
                        if transaction_begun and db_service:
                            if action_execution_result.get("success") and action_execution_result.get("state_changed"): await db_service.commit_transaction(); print(f"TPS: ATTACK {action_id_log} committed.")
                            else: await db_service.rollback_transaction(); print(f"TPS: ATTACK {action_id_log} transaction ended/rolled back.")
                    except Exception as e_action_attack:
                        print(f"TPS: Exception ATTACK {action_id_log}: {e_action_attack}"); traceback.print_exc()
                        if transaction_begun and db_service: await db_service.rollback_transaction(); print(f"TPS: ATTACK {action_id_log} rolled back by exception.")
                        action_execution_result = {"success": False, "message": f"Internal error: {e_action_attack}", "state_changed": False, "error": True}

                elif normalized_intent_type == "TALK":
                    transaction_begun = False
                    db_service = self.game_manager.db_service
                    try:
                        if db_service: await db_service.begin_transaction(); transaction_begun = True
                        # Placeholder: Dispatch to CharacterActionProcessor.handle_talk_action
                        # action_execution_result = await self.character_action_processor.handle_talk_action(
                        #     character=acting_char, action_data=action_data, guild_id=guild_id,
                        #     dialogue_manager=self.game_manager.dialogue_manager # Assuming dialogue_manager is on game_manager
                        # )
                        action_execution_result = {"success": False, "message": f"Talk action placeholder for {acting_char.id}.", "state_changed": False} # Placeholder
                        if transaction_begun and db_service:
                            if action_execution_result.get("success") and action_execution_result.get("state_changed"): await db_service.commit_transaction(); print(f"TPS: TALK {action_id_log} committed.")
                            else: await db_service.rollback_transaction(); print(f"TPS: TALK {action_id_log} transaction ended/rolled back.")
                    except Exception as e_action_talk:
                        print(f"TPS: Exception TALK {action_id_log}: {e_action_talk}"); traceback.print_exc()
                        if transaction_begun and db_service: await db_service.rollback_transaction(); print(f"TPS: TALK {action_id_log} rolled back by exception.")
                        action_execution_result = {"success": False, "message": f"Internal error: {e_action_talk}", "state_changed": False, "error": True}

                elif normalized_intent_type == "USE_ITEM": # General item usage not on an object
                    transaction_begun = False
                    db_service = self.game_manager.db_service
                    try:
                        if db_service: await db_service.begin_transaction(); transaction_begun = True
                        # This would call ItemManager.use_item, which needs item_template_id and target_entity (optional)
                        # These should be extracted from action_data.entities by CharacterActionProcessor
                        # Placeholder: Dispatch to CharacterActionProcessor.handle_nlu_use_item_action
                        # action_execution_result = await self.character_action_processor.handle_nlu_use_item_action(
                        #     character=acting_char, action_data=action_data, guild_id=guild_id,
                        #     item_manager=self.game_manager.item_manager, rules_config=rules_config
                        # )
                        action_execution_result = {"success": False, "message": f"Use Item (general) action placeholder for {acting_char.id}.", "state_changed": False} # Placeholder
                        if transaction_begun and db_service:
                            if action_execution_result.get("success") and action_execution_result.get("state_changed"): await db_service.commit_transaction(); print(f"TPS: USE_ITEM {action_id_log} committed.")
                            else: await db_service.rollback_transaction(); print(f"TPS: USE_ITEM {action_id_log} transaction ended/rolled back.")
                    except Exception as e_action_use_item:
                        print(f"TPS: Exception USE_ITEM {action_id_log}: {e_action_use_item}"); traceback.print_exc()
                        if transaction_begun and db_service: await db_service.rollback_transaction(); print(f"TPS: USE_ITEM {action_id_log} rolled back by exception.")
                        action_execution_result = {"success": False, "message": f"Internal error: {e_action_use_item}", "state_changed": False, "error": True}

                else:
                    # Fallback for other intent types not yet specifically dispatched - NO TRANSACTION
                    await self.game_log_manager.log_event(
                        guild_id=guild_id,
                        event_type="action_dispatch_unhandled",
                        message=f"Player {char_id_acting} action '{intent_type}' (ID: {action_id_log}) has no specific dispatcher yet.",
                        related_entities=[{"id": char_id_acting, "type": "Character"}],
                        metadata={"action_data": action_data}
                    )
                    # Default to not changing state if unhandled
                    action_execution_result = {"success": False, "message": f"The outcome of your attempt to '{intent_type}' is uncertain as this type of action is not fully processed by the current turn system.", "state_changed": False}

                # Log the executed action and its actual outcome from the handler
                await self.game_log_manager.log_event(
                    guild_id=guild_id,
                    event_type="action_executed",
                    message=f"Player {char_id_acting} action '{intent_type}' (ID: {action_id_log}) execution result: {action_execution_result.get('success')}. Message: {action_execution_result.get('message')}",
                    related_entities=[{"id": char_id_acting, "type": "Character"}],
                    metadata={"action_data": action_data, "execution_result": action_execution_result}
                )

                if char_id_acting in turn_feedback_reports:
                    turn_feedback_reports[char_id_acting].append(action_execution_result.get("message", "Your action was processed with an unknown outcome."))

                processed_result_entry = {
                    "character_id": char_id_acting,
                    "action_data": action_data,
                    "execution_result": action_execution_result
                }
                all_processed_action_results.append(processed_result_entry)

                if action_execution_result.get("state_changed", False):
                    print(f"TurnProcessingService: State potentially changed by action {action_id_log}. Marking character and saving game state for guild {guild_id}.")
                    self.character_manager.mark_character_dirty(guild_id, char_id_acting) # Assuming action affected the character
                    await self.game_manager.save_game_state_after_action(guild_id)

            except Exception as e:
                print(f"TurnProcessingService: Error executing action {intent_type} (ID: {action_id_log}) for player {char_id_acting}: {e}")
                traceback.print_exc()
                if char_id_acting in turn_feedback_reports:
                    turn_feedback_reports[char_id_acting].append(f"An error occurred while processing your action '{intent_type}'.")
                all_processed_action_results.append({
                    "character_id": char_id_acting,
                    "action_data": action_data,
                    "execution_result": {"success": False, "message": str(e), "error": True, "state_changed": False}
                })
                await self.game_log_manager.log_event(guild_id, "action_execution_error", f"Error executing action for {char_id_acting}.", {"player_id": char_id_acting, "action_data": action_data, "error": str(e)})

        # --- 4. Update Player Game Statuses ---
        for player_id_status_update in player_ids:
            char_to_update = await self.character_manager.get_character(guild_id, player_id_status_update)
            if char_to_update:
                final_status = "turn_processed"
                if any("requires Game Master review" in msg for msg in turn_feedback_reports.get(player_id_status_update, [])):
                    final_status = "awaiting_gm_resolution"
                elif not player_actions_map.get(player_id_status_update) and not any("Error" in msg for msg in turn_feedback_reports.get(player_id_status_update, [])): # No actions submitted and no errors
                    final_status = "turn_processed_no_actions"

                char_to_update.current_game_status = final_status
                self.character_manager.mark_character_dirty(guild_id, player_id_status_update)

        print(f"TurnProcessingService: Performing final save for guild {guild_id} after turn processing loop.")
        await self.game_manager.save_game_state_after_action(guild_id) # Saves all dirty objects

        await self.game_log_manager.log_event(
            guild_id=guild_id,
            event_type="turn_processing_end",
            message=f"Turn processing finished for players: {player_ids}.",
            metadata={"player_ids": player_ids, "num_results": len(all_processed_action_results)}
        )
        print(f"TurnProcessingService: Finished processing turns for players {player_ids} in guild {guild_id}.")
        return {"status": "completed", "feedback_per_player": turn_feedback_reports, "processed_action_details": all_processed_action_results}
