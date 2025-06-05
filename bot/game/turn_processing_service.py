from __future__ import annotations
import json
import traceback
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
    # from bot.services.notification_service import NotificationService # For player feedback

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
        # self.notification_service = notification_service
        self.settings = settings
        print("TurnProcessingService initialized.")

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
        for player_id in player_ids:
            char = await self.character_manager.get_character(guild_id, player_id) # Ensure get_character is async or adjust
            if not char:
                print(f"TurnProcessingService: Character {player_id} not found in guild {guild_id}. Skipping.")
                await self.game_log_manager.log_event(guild_id, "turn_processing_char_not_found", f"Character {player_id} not found.", {"player_id": player_id})
                turn_feedback_reports[player_id].append("Error: Your character data was not found.")
                continue

            if char.collected_actions_json:
                try:
                    actions = json.loads(char.collected_actions_json)
                    if isinstance(actions, list) and all(isinstance(act, dict) for act in actions):
                        player_actions_map[char.id] = actions
                        print(f"TurnProcessingService: Collected {len(actions)} actions for player {char.id}.")
                        await self.game_log_manager.log_event(guild_id, "actions_collected", f"Collected {len(actions)} for player {char.id}.", {"player_id": char.id, "num_actions": len(actions)})
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
            else:
                print(f"TurnProcessingService: No actions collected for player {char.id}.")
                await self.game_log_manager.log_event(guild_id, "no_actions_collected", f"No actions for player {char.id}.", {"player_id": char.id})
                player_actions_map[char.id] = []

            # Clear collected actions using the new method
            if hasattr(char, 'clear_collected_actions'):
                char.clear_collected_actions() # This sets collected_actions_json to None
            else: # Fallback if method not yet on all Character instances
                char.collected_actions_json = None
            self.character_manager.mark_character_dirty(guild_id, char.id)
            # Save will be handled by game_manager at end of processing or after state-changing actions.

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
        print(f"TurnProcessingService: Analyzing actions for conflicts. Action map: {json.dumps(player_actions_map, indent=2)}")
        analysis_result = await self.conflict_resolver.analyze_actions_for_conflicts(player_actions_map, guild_id)

        for auto_res_outcome in analysis_result.get("auto_resolution_outcomes", []):
            involved_chars = [act_ctx["character_id"] for act_ctx in auto_res_outcome.get("involved_actions", [])]
            outcome_desc = auto_res_outcome.get('outcome', {}).get('description', 'Details unavailable.')
            for char_id_involved in involved_chars:
                if char_id_involved in turn_feedback_reports:
                    turn_feedback_reports[char_id_involved].append(f"Conflict involving your action was automatically resolved. Outcome: {outcome_desc}")
            all_processed_action_results.append(auto_res_outcome)

        if analysis_result.get("requires_manual_resolution"):
            print(f"TurnProcessingService: Manual resolution required for some conflicts.")
            for pending_conflict in analysis_result.get("pending_conflict_details", []):
                conflict_id_manual = pending_conflict.get('conflict_id', 'UnknownConflict')
                # The `pending_conflict` is the dict returned by `prepare_for_manual_resolution`.
                # The actual actions are within the data saved to DB, and what `NotificationService` gets.
                # To get involved players for feedback, we need to ensure `involved_actions` (or at least player IDs)
                # are part of what `analyze_actions_for_conflicts` returns in `pending_conflict_details`.
                # `current_conflict_details` in `analyze_actions_for_conflicts` has `involved_actions`.
                # This `current_conflict_details` becomes an item in `pending_manual_conflicts`.
                involved_char_ids_in_pending = [action_ctx['character_id'] for action_ctx in pending_conflict.get('involved_actions', [])]

                for char_id_manual in involved_char_ids_in_pending:
                    if char_id_manual in turn_feedback_reports:
                        turn_feedback_reports[char_id_manual].append(
                            f"Your action is part of a conflict (ID: {conflict_id_manual}) that requires Game Master review. It will be processed once resolved."
                        )
                all_processed_action_results.append(pending_conflict)

        # --- 3. Action Execution Phase ---
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
                if intent_type == "MOVE":
                    # Entity extraction: NLU should provide entities.
                    # Example: {"intent_type": "MOVE", "entities": [{"type": "location_name", "value": "the forest", "id": "loc_forest_id"}]}
                    target_destination_entity = next((e for e in action_data.get("entities", []) if e.get("type") in ["location_name", "location_id", "portal_id"]), None)
                    if target_destination_entity:
                        # Conceptual call to a new method on CharacterActionProcessor
                        # This method would encapsulate logic from CommandRouter/CAP.process_action for 'move'
                        action_execution_result = await self.character_action_processor.handle_move_action(
                            character=acting_char,
                            destination_entity=target_destination_entity,
                            guild_id=guild_id
                            # Context/callback for messages not directly passed from here for now
                        )
                    else:
                        action_execution_result = {"success": False, "message": "You decided to move but didn't specify a valid destination.", "state_changed": False}

                elif intent_type == "SKILL_USE":
                    # Example: {"intent_type": "SKILL_USE", "skill_id": "lockpicking", "entities": [{"type": "target_object", "value": "chest", "id": "chest_001"}]}
                    # Or: {"intent_type": "SKILL_USE", "entities": [{"type": "skill_name", "value": "persuasion"}, {"type": "target_npc", "id": "npc_guard_002"}]}
                    skill_id = action_data.get("skill_id")
                    if not skill_id: # Try to get from entities if not top-level
                        skill_entity = next((e for e in action_data.get("entities", []) if e.get("type") == "skill_name"), None)
                        if skill_entity: skill_id = skill_entity.get("value")

                    target_entity = next((e for e in action_data.get("entities", []) if e.get("type") not in ["skill_name"]), None) # Simplistic target extraction

                    if skill_id:
                        # Conceptual call
                        action_execution_result = await self.character_action_processor.handle_skill_use_action(
                            character=acting_char,
                            skill_id=skill_id,
                            target_entity=target_entity, # This could be an item, NPC, or None
                            action_params=action_data, # Pass full action_data for extra params like difficulty, specific tool, etc.
                            guild_id=guild_id
                        )
                    else:
                        action_execution_result = {"success": False, "message": "You tried to use a skill, but the skill was unclear.", "state_changed": False}

                elif intent_type == "PICKUP_ITEM" or intent_type == "PICKUP": # NLU might use "PICKUP" or "PICKUP_ITEM"
                    # Example: {"intent_type": "PICKUP_ITEM", "entities": [{"type": "item_name", "value": "sword", "id": "item_sword_003"}]}
                    item_entity = next((e for e in action_data.get("entities", []) if e.get("type") in ["item_name", "item_id"]), None)
                    if item_entity:
                        # Conceptual call
                        action_execution_result = await self.character_action_processor.handle_pickup_item_action(
                            character=acting_char,
                            item_entity=item_entity,
                            guild_id=guild_id
                        )
                    else:
                        action_execution_result = {"success": False, "message": "You tried to pick something up, but it was unclear what.", "state_changed": False}

                elif intent_type == "EXPLORE" or intent_type == "LOOK_AROUND":
                     action_execution_result = await self.character_action_processor.handle_explore_action(
                        character=acting_char,
                        guild_id=guild_id,
                        action_params=action_data # For specific focus, if any
                     )

                else:
                    # Fallback for other intent types not yet specifically dispatched
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
