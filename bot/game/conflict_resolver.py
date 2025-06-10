# bot/game/conflict_resolver.py
"""
Module for the ConflictResolver class, responsible for identifying and managing
game conflicts based on player actions and defined rules.
"""

# Импорты, необходимые для ConflictResolver
import json
import uuid
import traceback # <- Добавьте импорт traceback, он используется в Error handling
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union, Tuple # <- Убедитесь, что Union и Tuple импортированы
from typing import Set

# Используем TYPE_CHECKING для импорта, который нужен только для аннотаций типов
# и предотвращает циклический импорт, если адаптер БД зависит от моделей или других частей игры.
if TYPE_CHECKING:
    # Импорт для аннотаций типов
    # from ..database.sqlite_adapter import SqliteAdapter # Removed
    # Импорт класса Character для аннотаций типов
    # from .models.character import Character
    from .managers.game_log_manager import GameLogManager

from bot.services.db_service import DBService
from bot.ai.rules_schema import CoreGameRulesConfig, ActionConflictDefinition # Added

# Placeholder for actual RuleEngine classes
# from ..core.rule_engine import RuleEngine # Assuming RuleEngine might be in a core module
from ..services.notification_service import NotificationService # Actual import


class ConflictResolver:
    """
    Identifies, manages, and resolves conflicts that arise from player actions
    based on the game's rules configuration.
    """

    # Аннотация для db_service теперь ссылается на импортированный класс DBService
    def __init__(self, rule_engine: Any, notification_service: Any, db_service: 'DBService', game_log_manager: Optional['GameLogManager'] = None):
        """
        Инициализирует ConflictResolver.
        rules_config_data is now expected to be part of rule_engine or passed to analyze method.

        Args:
            rule_engine: An instance of the RuleEngine (placeholder: Any).
                         This engine will be used for checks like skill checks, stat checks, etc. Must be async-compatible.
            rules_config_data: A dictionary containing the loaded rules configuration.
            notification_service: A service object responsible for sending notifications (placeholder: Any). Must be async-compatible.
            db_service: An instance of the DBService for database operations.
        """
        self.rule_engine = rule_engine # RuleEngine should provide access to CoreGameRulesConfig
        # self.rules_config = rules_config_data # Removed, expect CoreGameRulesConfig via rule_engine or passed to analyze
        self.notification_service = notification_service
        self.db_service = db_service
        self.game_log_manager = game_log_manager
        print(f"ConflictResolver initialized with db_service and game_log_manager {'present' if game_log_manager else 'not present'}.")

    async def analyze_actions_for_conflicts(
        self,
        player_actions_map: Dict[str, List[Dict[str, Any]]],
        guild_id: str,
        rules_config: Optional[CoreGameRulesConfig] # Added rules_config parameter
    ) -> Dict[str, Any]:
        """
        Analyzes a map of player actions to identify potential conflicts using CoreGameRulesConfig.
        Prepares data for manual conflicts to be saved by TurnProcessingService.
        If automatic, it calls resolve_conflict_automatically.

        Args:
            player_actions_map: A dictionary where keys are player IDs (str) and
                                values are lists of actions (Dict[str, Any])
                                submitted by that player for the current turn/tick.
                                Each action is expected to be like:
                                {"intent": "move", "entities": [{"type": "location_name", "value": "forest"}], "original_text": "go to forest"}
            guild_id: The ID of the guild the actions belong to.
            context: Optional context dictionary that might be used by sub-methods.

        Returns:
            A dictionary with the analysis result:
            {
                "requires_manual_resolution": bool,
                "pending_conflict_details": List[Dict[str, Any]], // Conflicts needing GM
                "actions_to_execute": List[Dict[str, Any]], // Actions cleared for execution
                                                             // Each: {"character_id": str, "action_data": Dict, "original_action_context": Dict}
                "auto_resolution_outcomes": List[Dict[str, Any]] // Outcomes of auto-resolved conflicts
            }
        """
        if self.game_log_manager:
            action_summary_for_log = {pid: [a.get("intent_type", a.get("intent", "unknown_intent")) for a in actions] for pid, actions in player_actions_map.items()}
            await self.game_log_manager.log_event(
                guild_id=guild_id,
                event_type="conflict_analysis_start",
                message=f"Starting conflict analysis for {len(player_actions_map)} players.",
                metadata={"player_action_summary": action_summary_for_log, "context": context}
            )
        else:
            print(f"Analyzing actions for conflicts in guild {guild_id} using CoreGameRulesConfig.")

        # Initialize analysis_result structure
        analysis_result = {
            "actions_to_execute": [],
            "pending_conflict_details": [], # For data to be saved as PendingConflict
            "auto_resolution_outcomes": [],
            "requires_manual_resolution": False
        }

        if not rules_config or not rules_config.action_conflicts:
            # No rules, so all actions are considered non-conflicting for now
            print("ConflictResolver: No action conflict rules defined or rules_config not available. Passing all actions through.")
            for char_id, actions in player_actions_map.items():
                for action_data in actions:
                    analysis_result["actions_to_execute"].append({
                        "character_id": char_id,
                        "action_data": action_data
                        # "_original_list_index" and "_status" could be added if needed by downstream
                    })
            return analysis_result

        # Flatten all actions with context for easier processing
        all_actions_flat: List[Dict[str, Any]] = []
        for char_id, actions in player_actions_map.items():
            for i, action in enumerate(actions):
                action_data_copy = dict(action) # Make a copy
                if 'action_id' not in action_data_copy: # Ensure action_id
                    action_data_copy['action_id'] = f"action_{uuid.uuid4().hex[:8]}"

                all_actions_flat.append({
                    "character_id": char_id,
                    "action_data": action_data_copy,
                    "_original_player_actions_list_index": i, # In case we need to refer back
                    "_status": "pending" # 'pending', 'manual_pending', 'auto_resolved_proceed', 'auto_resolved_fail'
                })

        # --- Conflict Detection Loop ---
        for conflict_def in rules_config.action_conflicts:
            # This is a simplified detection logic placeholder.
            # A real implementation would need more sophisticated matching based on involved_intent_pattern,
            # target types, location conditions etc.

            # Example: Find actions matching the first intent in the pattern
            # This is VERY basic and needs to be expanded based on actual conflict_def structure.
            # For instance, if conflict_def.involved_intent_pattern = ["MOVE", "MOVE"] for same target.

            # Collect actions that match any of the involved intents for this conflict_def
            relevant_actions = []
            for action_wrapper in all_actions_flat:
                # Skip actions already part of another conflict or processed
                if action_wrapper["_status"] != "pending":
                    continue

                action_intent = action_wrapper["action_data"].get("intent", action_wrapper["action_data"].get("intent_type"))
                if action_intent in conflict_def.involved_intent_pattern:
                    relevant_actions.append(action_wrapper)

            # Simplistic: if more than one player has a relevant action, assume conflict.
            # This needs to be refined based on specific conflict types (e.g. same target, same location)
            if len(relevant_actions) > 1:
                # Check if actions are from different players (a conflict usually involves >1 player)
                involved_player_ids_for_this_conflict = list(set(aw["character_id"] for aw in relevant_actions))
                if len(involved_player_ids_for_this_conflict) > 1:
                    # This is a potential conflict group based on intents.
                    # Real logic would further filter based on targets, location, etc.
                    # For now, assume this group IS a conflict.
                    conflicting_action_wrappers = relevant_actions

                    print(f"ConflictResolver: Detected potential conflict type '{conflict_def.type}' involving actions: {[aw['action_data']['action_id'] for aw in conflicting_action_wrappers]}")

                    if conflict_def.resolution_type == "manual_resolve":
                        analysis_result["requires_manual_resolution"] = True
                        # Mark actions as manual_pending so they are not added to actions_to_execute later
                        for aw in conflicting_action_wrappers:
                            aw["_status"] = "manual_pending"

                        analysis_result["pending_conflict_details"].append({
                            "conflict_type_id": conflict_def.type,
                            "description_for_gm": conflict_def.description,
                            "involved_actions_data": [aw["action_data"] for aw in conflicting_action_wrappers],
                            "involved_player_ids": involved_player_ids_for_this_conflict,
                            "manual_resolution_options": conflict_def.manual_resolution_options,
                            "guild_id": guild_id # For DB storage by TurnProcessingService
                        })
                        if self.game_log_manager:
                             await self.game_log_manager.log_event(guild_id, "conflict_manual_flagged",
                                f"Conflict {conflict_def.type} flagged for manual resolution.",
                                {"type": conflict_def.type, "actions": [aw['action_data']['action_id'] for aw in conflicting_action_wrappers]})

                    elif conflict_def.resolution_type == "auto":
                        # Placeholder for automatic resolution
                        # For now, we'll log it and assume one action proceeds (e.g., the first one)
                        # A real auto-resolver would call CheckResolver, modify actions, etc.

                        # Mark all involved as auto_resolved (outcome pending)
                        for aw in conflicting_action_wrappers:
                            aw["_status"] = "auto_resolved_pending_outcome"

                        # Simplified auto-resolution: let the first action proceed, others fail/get modified
                        # This is a placeholder. Real auto-resolution is complex.
                        winner_action_wrapper = conflicting_action_wrappers[0]
                        winner_action_wrapper["_status"] = "auto_resolved_proceed" # This action will be executed

                        auto_res_outcome_detail = {
                            "conflict_type_id": conflict_def.type,
                            "description": f"Automatically processed conflict: {conflict_def.description}.",
                            "involved_actions": [aw["action_data"] for aw in conflicting_action_wrappers],
                            "outcome": {"winner_action_id": winner_action_wrapper["action_data"]["action_id"],
                                        "message": f"Action by {winner_action_wrapper['character_id']} proceeded by default auto-resolution."}
                        }
                        analysis_result["auto_resolution_outcomes"].append(auto_res_outcome_detail)
                        if self.game_log_manager:
                            await self.game_log_manager.log_event(guild_id, "conflict_auto_processed_placeholder",
                                f"Conflict {conflict_def.type} auto-processed (placeholder). Winner: {winner_action_wrapper['action_data']['action_id']}",
                                auto_res_outcome_detail)

        # Finalize actions_to_execute
        for action_wrapper in all_actions_flat:
            if action_wrapper["_status"] == "pending" or action_wrapper["_status"] == "auto_resolved_proceed":
                analysis_result["actions_to_execute"].append({
                    "character_id": action_wrapper["character_id"],
                    "action_data": action_wrapper["action_data"]
                })

        # Logging the overall result of conflict analysis
        if self.game_log_manager :
             await self.game_log_manager.log_event(
                guild_id=guild_id,
                event_type="conflict_analysis_no_actions",
                message="No actions submitted by any player for conflict analysis."
            )
        elif not pending_manual_conflicts and not auto_resolution_outcomes and actions_to_execute and self.game_log_manager:
             await self.game_log_manager.log_event(
                guild_id=guild_id,
                event_type="conflict_analysis_no_conflicts_found",
                message=f"No specific conflicts identified among {len(all_submitted_actions_with_context)} actions. Processed {len(processed_action_ids)} in conflicts. Adding {len(actions_to_execute)} to execution queue.",
                metadata={"num_submitted": len(all_submitted_actions_with_context), "num_processed_in_conflict": len(processed_action_ids), "num_to_execute_directly": len(actions_to_execute)}
            )

        if self.game_log_manager:
            await self.game_log_manager.log_event(
                guild_id=guild_id,
                event_type="conflict_analysis_end",
                message=(f"Conflict analysis finished. Manual resolution required: {requires_manual_resolution_flag}. "
                         f"Actions to execute: {len(actions_to_execute)}. "
                         f"Pending manual: {len(pending_manual_conflicts)}. Auto-resolved: {len(auto_resolution_outcomes)}."),
                metadata={
                    "requires_manual_resolution": requires_manual_resolution_flag,
                    "num_actions_to_execute": len(actions_to_execute),
                    "num_pending_manual": len(pending_manual_conflicts),
                    "num_auto_resolved": len(auto_resolution_outcomes)
                }
            )

        return {
            "requires_manual_resolution": requires_manual_resolution_flag,
            "pending_conflict_details": pending_manual_conflicts,
            "actions_to_execute": actions_to_execute,
            "auto_resolution_outcomes": auto_resolution_outcomes
        }

    async def resolve_conflict_automatically(self, conflict: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Attempts to resolve a given conflict automatically based on rules, using RuleEngine.

        Args:
            conflict: A conflict dictionary, as produced by analyze_actions_for_conflicts.
                      It should contain the 'type' key to look up rules in self.rules_config,
                      and 'involved_entities' (list of {'id': str, 'type': str}) and 'details'.

        Returns:
            The conflict dictionary updated with the resolution outcome.
        """
        conflict_type_id = conflict.get("type")
        conflict_id = conflict.get("conflict_id")
        if not conflict_id:
             conflict_id = f"auto_res_{uuid.uuid4().hex[:8]}"
             conflict["conflict_id"] = conflict_id

        guild_id_log = str(conflict.get("guild_id", "UNKNOWN_GUILD")) # Get guild_id for logging

        if self.game_log_manager:
            await self.game_log_manager.log_event(
                guild_id=guild_id_log,
                event_type="conflict_auto_resolve_start",
                message=f"Attempting automatic resolution for conflict: {conflict_id} (Type: {conflict_type_id}).",
                related_entities=conflict.get("involved_entities", []),
                metadata={"conflict_id": conflict_id, "conflict_type": conflict_type_id, "details": conflict.get("details")}
            )
        else:
            print(f"Attempting async automatic resolution for conflict: {conflict_id} ({conflict_type_id})")

        if not conflict_type_id or conflict_type_id not in self.rules_config:
            error_msg = f"Error resolving automatically: Unknown conflict type '{conflict_type_id}' for conflict {conflict_id}."
            if self.game_log_manager:
                await self.game_log_manager.log_event(guild_id=guild_id_log, event_type="conflict_auto_resolve_error", message=error_msg, metadata={"conflict_id": conflict_id})
            else:
                print(f"❌ {error_msg}")
            conflict["status"] = "resolution_failed_unknown_type"
            conflict["outcome"] = {"description": error_msg}
            return conflict

        rule = self.rules_config[conflict_type_id]
        auto_res_config = rule.get("automatic_resolution", {})
        config_check_type = auto_res_config.get("check_type")
        outcome_rules = auto_res_config.get("outcome_rules", {})

        if not config_check_type:
            error_msg = f"Automatic resolution rule for '{conflict_type_id}' missing 'check_type'."
            print(f"Error for conflict {conflict_id}: {error_msg}")

        # The 'check_type' from rules_config will be passed to RuleEngine.resolve_check
        rule_engine_check_type = auto_res_config.get("check_type")

        if not rule_engine_check_type:
            conflict["status"] = "resolution_failed_no_check_type"
            conflict["outcome"] = {"description": error_msg}
            return conflict

        involved_entities = conflict.get("involved_entities", [])
        if not involved_entities:
            error_msg = "No involved entities found for automatic resolution."
            print(f"Error for conflict {conflict_id}: {error_msg}")
            conflict["status"] = "resolution_failed_no_entities"
            conflict["outcome"] = {"description": error_msg}
            return conflict

        # --- Integrate RuleEngine.resolve_check ---
        actor_entity = involved_entities[0]
        actor_id = actor_entity["id"]
        actor_type = actor_entity["type"]

        target_entity = involved_entities[1] if len(involved_entities) > 1 else None
        target_id = target_entity["id"] if target_entity else None
        target_type = target_entity["type"] if target_entity else None

        actor_context = auto_res_config.get("actor_check_details", {})
        target_context = auto_res_config.get("target_check_details", {})

        try:
            print(f"Calling RuleEngine for actor '{actor_id}' check type '{config_check_type}'...")
            actor_check_result = await self.rule_engine.resolve_check(
                entity_id=actor_id,
                entity_type=actor_type,
                check_type=config_check_type,
                context=actor_context,
                target_id=target_id if config_check_type == "opposed_check" else None,
                target_type=target_type if config_check_type == "opposed_check" else None,
                conflict_details=conflict
            )
            print(f"RuleEngine actor check result for {actor_id}: {actor_check_result}")

            actor_roll = actor_check_result.get("total_roll_value")
            actor_check_outcome = actor_check_result.get("outcome") # e.g., "SUCCESS", "FAILURE"

            target_roll = None
            target_check_outcome = None
            target_check_result = None

            if config_check_type == "opposed_check" and target_id:
                 print(f"Calling RuleEngine for target '{target_id}' check type '{config_check_type}'...")
                 target_check_result = await self.rule_engine.resolve_check(
                    entity_id=target_id,
                    entity_type=target_type,
                    check_type=config_check_type,
                    context=target_context,
                    target_id=actor_id,
                    target_type=actor_type,
                    conflict_details=conflict
                 )
                 print(f"RuleEngine target check result for {target_id}: {target_check_result}")
                 target_roll = target_check_result.get("total_roll_value")
                 target_check_outcome = target_check_result.get("outcome")


            # Determine the *final* conflict outcome based on RuleEngine results and outcome_rules
            final_outcome_key = "tie" # Default
            winner_id = None # Default

            if config_check_type == "opposed_check" and target_id:
                if actor_roll > target_roll:
                    final_outcome_key = "actor_wins"
                    winner_id = actor_id
                elif target_roll > actor_roll:
                    final_outcome_key = "target_wins"
                    winner_id = target_id
                else: # Tie
                    tie_breaker = outcome_rules.get("tie_breaker_rule", "random")
                    if tie_breaker == "actor_preference":
                        final_outcome_key = "actor_wins"
                        winner_id = actor_id
                    elif tie_breaker == "target_preference":
                        final_outcome_key = "target_wins"
                        winner_id = target_id
                    elif tie_breaker == "random":
                        if self.rule_engine and hasattr(self.rule_engine, "resolve_dice_roll"):
                             print("Calling RuleEngine for random tie-breaker (1d2)...")
                             tie_roll_result = await self.rule_engine.resolve_dice_roll("1d2")
                             if tie_roll_result and tie_roll_result.get('total', 0) == 1:
                                 final_outcome_key = "actor_wins"
                                 winner_id = actor_id
                             else:
                                 final_outcome_key = "target_wins"
                                 winner_id = target_id
                             print(f"Tie-breaker roll result: {tie_roll_result}. Winner: {winner_id}")
                        else:
                            print("Warning: No RuleEngine dice roller for random tie-breaker. Defaulting to actor wins.")
                            final_outcome_key = "actor_wins"
                            winner_id = actor_id

            else: # Single entity check against a DC (or simple success/failure)
                if actor_check_outcome == "SUCCESS":
                    final_outcome_key = "actor_wins"
                    winner_id = actor_id
                elif actor_check_outcome == "FAILURE":
                    final_outcome_key = "target_wins"
                # Add handling for degrees of success/failure

        except Exception as e:
            error_msg = f"Error during RuleEngine check for conflict {conflict_id} ({conflict_type_id}): {e}"
            print(f"❌ {error_msg}")
            traceback.print_exc()
            conflict["status"] = "resolution_failed_rule_engine_error"
            conflict["outcome"] = {"description": error_msg}
            return conflict

        resolved_outcome_details = outcome_rules.get("outcomes", {}).get(final_outcome_key, {})

        conflict["status"] = "resolved_automatically"
        conflict["outcome"] = {
            "winner_id": winner_id,
            "actor_check_result": actor_check_result,
            "target_check_result": target_check_result if target_id else None,
            "outcome_key": final_outcome_key,
            "description": resolved_outcome_details.get("description", f"Automatic outcome: {final_outcome_key}"),
            "effects": resolved_outcome_details.get("effects", []),
            "resolution_timestamp": await self.rule_engine.get_game_time() if hasattr(self.rule_engine, 'get_game_time') else None
        }

        print(f"Conflict {conflict_id} ({conflict_type_id}) automatically resolved.")
        print(f"Outcome: {conflict['outcome']['outcome_key']}, Winner: {conflict['outcome'].get('winner_id')}")

        if self.game_log_manager:
            await self.game_log_manager.log_event(
                guild_id=guild_id_log, # Use already fetched guild_id
                event_type="conflict_auto_resolve_success", # More specific event type
                message=f"Conflict {conflict_id} ({conflict_type_id}) resolved automatically. Winner: {conflict['outcome'].get('winner_id')}. Outcome: {conflict['outcome']['outcome_key']}",
                related_entities=conflict.get("involved_entities", []),
                metadata={"conflict_id": conflict_id, "outcome": conflict['outcome']}
            )
        return conflict


    async def prepare_for_manual_resolution(self, conflict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepares a conflict for manual resolution by a Master/GM.
        Generates a unique ID, stores the conflict details in the database,
        and formats a notification message.

        Args:
            conflict: A conflict dictionary. It must include 'type', 'involved_entities',
                      'details', and 'guild_id'. 'conflict_id' can be pre-assigned.

        Returns:
            A dictionary containing the 'conflict_id', status, and a message for the caller.
        """
        conflict_type_id = conflict.get("type")
        guild_id = conflict.get("guild_id")

        if not conflict_type_id or conflict_type_id not in self.rules_config:
            error_msg = f"Error preparing for manual resolution: Unknown conflict type '{conflict_type_id}'."
            print(f"❌ {error_msg}")
            return {"status": "preparation_failed_unknown_type", "message": error_msg, "original_conflict": conflict}

        rule = self.rules_config[conflict_type_id]

        conflict_id = conflict.get("conflict_id") or uuid.uuid4().hex
        conflict["conflict_id"] = conflict_id # Ensure it's set in the conflict dict
        conflict["status"] = "awaiting_manual_resolution"

        guild_id_log = str(guild_id) if guild_id else "UNKNOWN_GUILD"


        if self.game_log_manager:
            await self.game_log_manager.log_event(
                guild_id=guild_id_log,
                event_type="conflict_manual_prepare_start",
                message=f"Preparing conflict '{conflict_id}' (Type: {conflict_type_id}) for manual resolution.",
                related_entities=conflict.get("involved_entities", []),
                metadata={"conflict_id": conflict_id, "conflict_type": conflict_type_id, "details": conflict.get("details")}
            )
        else:
            print(f"Preparing conflict '{conflict_id}' ({conflict_type_id}) for manual resolution.")

        try:
            if not guild_id: # guild_id is critical here
                 error_msg = f"Conflict {conflict_id} is missing guild_id, cannot save for manual resolution."
                 if self.game_log_manager:
                     await self.game_log_manager.log_event(guild_id=guild_id_log, event_type="conflict_manual_prepare_error", message=error_msg, metadata={"conflict_id": conflict_id})
                 else:
                    print(f"❌ {error_msg}")
                 conflict["status"] = "preparation_failed_no_guild_id"
                 return {"status": "preparation_failed_no_guild_id", "message": error_msg, "original_conflict": conflict}

            conflict_data_json = json.dumps(conflict)
            await self.db_service.save_pending_conflict( # Changed to db_service
                 conflict_id=conflict_id,
                 guild_id=str(guild_id), # Ensure guild_id is string for DB
                 conflict_data=conflict_data_json
            )
            if self.game_log_manager:
                await self.game_log_manager.log_event(guild_id=guild_id_log, event_type="conflict_manual_db_saved", message=f"Conflict {conflict_id} saved to DB.", metadata={"conflict_id": conflict_id})
            else:
                print(f"Conflict {conflict_id} saved to database for manual resolution.")

        except Exception as e:
            error_msg = f"Error saving conflict {conflict_id} to DB for manual resolution: {e}"
            if self.game_log_manager:
                await self.game_log_manager.log_event(guild_id=guild_id_log, event_type="conflict_manual_prepare_dberror", message=error_msg, metadata={"conflict_id": conflict_id, "error": str(e)})
            else:
                print(f"❌ {error_msg}")
            traceback.print_exc()
            conflict["status"] = "preparation_failed_db_error"
            return {"status": "preparation_failed_db_error", "message": error_msg, "original_conflict": conflict}

        notification_fmt = rule.get("notification_format", {})
        message_template = notification_fmt.get("message", "Manual resolution required for {conflict_id}: {type}")

        placeholders: Dict[str, Any] = {
            "conflict_id": conflict_id,
            "type": conflict_type_id,
            "description": rule.get("description", "N/A"),
            "involved_entities": conflict.get("involved_entities", []),
            "entity_ids_str": ", ".join([e.get('id', 'Unknown') for e in conflict.get("involved_entities", [])]),
            "entity_types_str": ", ".join([e.get('type', 'Unknown') for e in conflict.get("involved_entities", [])]),
            **(conflict.get('details', {}))
        }
        for i, entity in enumerate(conflict.get("involved_entities", [])):
            entity_id_val = entity.get('id', f'Unknown{i+1}')
            placeholders[f"entity{i+1}_id"] = entity_id_val
            placeholders[f"entity{i+1}_type"] = entity.get('type', 'Unknown')
            if i == 0: placeholders["actor_id"] = entity_id_val
            if i == 0: placeholders["actor_type"] = entity.get('type', 'Unknown')
            if i == 1: placeholders["target_id"] = entity_id_val
            if i == 1: placeholders["target_type"] = entity.get('type', 'Unknown')

        try:
            formatted_message = message_template.format_map(placeholders)
        except KeyError as e:
            formatted_message = f"Manual resolution required for {conflict_id} ({conflict_type_id}). Error formatting notification: Missing key {e}."
            print(f"❌ Error formatting notification for {conflict_id}: {e}. Template: '{message_template}', Placeholders: {list(placeholders.keys())}")


        if self.notification_service:
             # Ensure guild_id is a string, as validated earlier in the method
             # The method already checks for `if not guild_id:` and returns if it's missing.
             # So, guild_id here is expected to be a valid, non-None value.
             print(f"Attempting to send master alert via NotificationService for conflict {conflict_id} in guild {str(guild_id)}...")
             try:
                 await self.notification_service.send_master_alert(
                    conflict_id=conflict_id,
                    guild_id=str(guild_id), # Ensure guild_id is passed as string
                    message=formatted_message,
                    conflict_details=conflict # Pass the whole conflict dict as details
                 )
                 # Log success (NotificationService itself logs details)
                 print(f"Master alert initiated for conflict {conflict_id} via NotificationService.")
                 if self.game_log_manager:
                    await self.game_log_manager.log_event(guild_id=guild_id_log, event_type="conflict_manual_notification_sent", message=f"GM Notification sent for conflict {conflict_id}.", metadata={"conflict_id": conflict_id})

             except Exception as e:
                 # Log specific error from notification sending
                 error_msg_notification = f"Error sending GM notification for conflict {conflict_id} via NotificationService: {e}"
                 print(f"❌ {error_msg_notification}")
                 traceback.print_exc()
                 if self.game_log_manager:
                    await self.game_log_manager.log_event(guild_id=guild_id_log, event_type="conflict_manual_notification_error", message=error_msg_notification, metadata={"conflict_id": conflict_id, "error": str(e)})

        if self.game_log_manager:
            await self.game_log_manager.log_event(
                guild_id=guild_id_log, # Use already fetched guild_id
                event_type="conflict_manual_prepare_success", # More specific
                message=f"Conflict {conflict_id} ({conflict_type_id}) prepared for manual resolution. Notification: {formatted_message}",
                related_entities=conflict.get("involved_entities", []),
                metadata={"conflict_id": conflict_id, "notification_message": formatted_message}
            )

        return {
            "conflict_id": conflict_id,
            "status": "awaiting_manual_resolution",
            "message": f"Conflict '{conflict_id}' ({conflict_type_id}) requires manual resolution. Details saved and notification sent.",
            "details_for_master": formatted_message
        }

    async def process_master_resolution(self, conflict_id: str, outcome_type: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Processes the resolution details provided by a Master/GM for a conflict.
        Retrieves the conflict from the database, removes it, and determines the outcome.

        Args:
            conflict_id: The unique ID of the conflict being resolved.
            outcome_type: A string indicating the type of outcome chosen by the Master
                          (e.g., "actor_wins", "target_wins", "custom_outcome").
            params: Optional dictionary of parameters if the outcome requires them.

        Returns:
            A dictionary confirming the resolution and the outcome details (e.g., effects to apply).
        """
        # Try to get guild_id from params or context if available, otherwise it will be fetched from DB record
        guild_id_log_param = str(params.get("guild_id", "UNKNOWN_GUILD_PARAM")) if params else "UNKNOWN_GUILD_PARAM"

        if self.game_log_manager:
            await self.game_log_manager.log_event(
                guild_id=guild_id_log_param, # May not be the actual guild_id of conflict yet
                event_type="conflict_manual_resolve_start",
                message=f"Processing Master resolution for conflict_id: {conflict_id}, outcome: {outcome_type}.",
                metadata={"conflict_id": conflict_id, "chosen_outcome_type": outcome_type, "resolution_params": params}
            )
        else:
            print(f"Processing Master resolution for conflict_id: {conflict_id}, outcome_type: {outcome_type}, params: {params}")

        original_conflict: Optional[Dict[str, Any]] = None
        guild_id_from_db: Optional[str] = None

        try:
            pending_conflict_data = await self.db_service.get_pending_conflict(conflict_id) # Changed to db_service
            if not pending_conflict_data: # db_service.get_pending_conflict returns a dict or None
                 error_msg = f"Error: Conflict ID '{conflict_id}' not found in pending manual resolutions database table."
                 if self.game_log_manager:
                     await self.game_log_manager.log_event(guild_id=guild_id_log_param, event_type="conflict_manual_resolve_error", message=error_msg, metadata={"conflict_id": conflict_id})
                 else:
                    print(f"❌ {error_msg}")
                 return {
                    "success": False,
                    "conflict_id": conflict_id,
                    "message": error_msg
                 }

            # pending_conflict_data is already a dict, no need for json.loads(row['conflict_data'])
            # if db_service.get_pending_conflict correctly deserializes JSON from PostgresAdapter
            # Assuming PostgresAdapter's fetchone (used by get_pending_conflict) returns a dict
            # and the 'conflict_data' field within that dict is already parsed if it's JSONB in DB
            # If 'conflict_data' is still a JSON string, then json.loads is needed.
            # Based on current PostgresAdapter, it returns dicts, but JSON string fields are not auto-parsed by adapter.
            # So, if 'conflict_data' is stored as a JSON string in the DB, it needs parsing here.
            # The method signature in PostgresAdapter is `get_pending_conflict(...) -> Optional[Dict[str, Any]]`
            # and it does `SELECT id, guild_id, conflict_data ...`, so conflict_data is one of the keys.

            raw_conflict_json_payload = pending_conflict_data.get('conflict_data')
            if isinstance(raw_conflict_json_payload, str):
                original_conflict = json.loads(raw_conflict_json_payload)
            elif isinstance(raw_conflict_json_payload, dict): # If it's already a dict (e.g. JSONB auto-parsed)
                original_conflict = raw_conflict_json_payload
            else:
                # Handle case where 'conflict_data' is missing or not str/dict
                error_msg = f"Error: 'conflict_data' field is missing or invalid in pending_conflict_data for conflict ID '{conflict_id}'."
                if self.game_log_manager:
                    await self.game_log_manager.log_event(guild_id=guild_id_log_param, event_type="conflict_manual_resolve_error", message=error_msg, metadata={"conflict_id": conflict_id})
                else:
                    print(f"❌ {error_msg}")
                return {"success": False, "conflict_id": conflict_id, "message": error_msg}

            if not isinstance(original_conflict, dict): # Ensure it's a dict after loading/assignment
                # This might seem redundant if the above block is perfect, but good for safety against unexpected JSON structures.
                error_msg = f"Error: Loaded conflict_data for conflict ID '{conflict_id}' did not resolve to a dictionary."
                if self.game_log_manager:
                    await self.game_log_manager.log_event(guild_id=guild_id_log_param, event_type="conflict_manual_resolve_error", message=error_msg, metadata={"conflict_id": conflict_id})
                else:
                    print(f"❌ {error_msg}")
                return {"success": False, "conflict_id": conflict_id, "message": error_msg}

            original_conflict["status"] = "resolved_manually" # Tentative status
            # guild_id should also be directly available from pending_conflict_data if it's a top-level field
            guild_id_from_db = str(pending_conflict_data.get("guild_id", original_conflict.get("guild_id", guild_id_log_param)))

            await self.db_service.delete_pending_conflict(conflict_id) # Changed to db_service
            if self.game_log_manager:
                await self.game_log_manager.log_event(guild_id=guild_id_from_db, event_type="conflict_manual_db_deleted", message=f"Conflict {conflict_id} retrieved and removed from DB.", metadata={"conflict_id": conflict_id})
            else:
                print(f"Conflict {conflict_id} retrieved and removed from database.")

        except Exception as e:
            error_msg = f"Error retrieving/deleting conflict {conflict_id} from DB for manual resolution: {e}"
            if self.game_log_manager:
                 await self.game_log_manager.log_event(guild_id=guild_id_log_param, event_type="conflict_manual_resolve_dberror", message=error_msg, metadata={"conflict_id": conflict_id, "error": str(e)})
            else:
                print(f"❌ {error_msg}")
            traceback.print_exc()
            return {
                "success": False,
                "conflict_id": conflict_id,
                "message": error_msg
            }

        print(f"Retrieved original conflict data for {conflict_id} ({original_conflict.get('type')}): {original_conflict.get('involved_entities')}")

        conflict_type_id = original_conflict.get("type")
        rule = self.rules_config.get(conflict_type_id)

        if not rule:
            error_msg = f"Error processing manual resolution: Rule definition for conflict type '{conflict_type_id}' not found."
            print(f"❌ {error_msg}")
            original_conflict["status"] = "resolved_manually_failed_no_rule"
            original_conflict["outcome"] = {"description": error_msg}
            return {
                 "success": False,
                 "conflict_id": conflict_id,
                 "message": error_msg,
                 "resolution_details": original_conflict
            }

        manual_res_config = rule.get("manual_resolution", {})
        allowed_outcomes = manual_res_config.get("outcomes", {})

        chosen_outcome_details = allowed_outcomes.get(outcome_type)

        if not chosen_outcome_details:
             if outcome_type == "custom_outcome":
                  effects_to_apply = params.get("effects", [])
                  description = params.get("description", f"Master applied custom outcome.")
                  print(f"Processing custom outcome for {conflict_id} with params: {params}")
             else:
                error_msg = f"Warning: Master chose outcome type '{outcome_type}' which is not explicitly defined in rules for conflict type '{conflict_type_id}'. Using generic effects if any."
                print(error_msg)
                chosen_outcome_details = allowed_outcomes.get("default")
                if chosen_outcome_details:
                    effects_to_apply = chosen_outcome_details.get("effects", [])
                    description = chosen_outcome_details.get("description", f"Master chose undefined outcome '{outcome_type}'. Default applied.")
                else:
                    effects_to_apply = []
                    description = f"Master chose undefined outcome '{outcome_type}'. No specific outcome rule found and no default."
                    print(f"❌ No specific or default outcome found for {outcome_type} in manual resolution rules for {conflict_type_id}.")

             outcome_data = {
                 "outcome_key": outcome_type,
                 "description": description,
                 "effects": effects_to_apply,
                 "parameters_applied": params if params else {},
                 "manual_override": True
             }
        else:
            effects_to_apply = chosen_outcome_details.get("effects", [])
            description = chosen_outcome_details.get("description", f"Master chose defined outcome '{outcome_type}'.")
            outcome_data = {
                 "outcome_key": outcome_type,
                 "description": description,
                 "effects": effects_to_apply,
                 "parameters_applied": params if params else {},
                 "manual_override": True
            }

        original_conflict["outcome"] = outcome_data
        original_conflict["resolved_by"] = "master"
        original_conflict["resolution_timestamp"] = await self.rule_engine.get_game_time() if hasattr(self.rule_engine, 'get_game_time') else None


        print(f"Conflict {conflict_id} resolved manually by Master. Outcome: {outcome_type}. Details: {original_conflict['outcome']}")

        if self.game_log_manager:
            # Ensure original_conflict is not None before proceeding
            if not original_conflict: # Should have been caught by the return above, but as a safeguard
                # This path should ideally not be reached if original_conflict could not be loaded.
                # Logging here would be redundant with the one in the try-except block.
                return {"success": False, "conflict_id": conflict_id, "message": "Failed to load original conflict data."}

            # Use guild_id_from_db for subsequent logging if available
            final_guild_id_log = guild_id_from_db if guild_id_from_db != "UNKNOWN_GUILD_PARAM" else guild_id_log_param

            if self.game_log_manager:
                await self.game_log_manager.log_event(
                    guild_id=final_guild_id_log,
                    event_type="conflict_manual_resolve_success", # More specific
                    message=f"Conflict {conflict_id} resolved by master. Outcome: {outcome_type}. Details: {original_conflict['outcome'].get('description')}",
                    related_entities=original_conflict.get("involved_entities", []),
                    metadata={"conflict_id": conflict_id, "master_outcome": outcome_type, "resolution_params": params, "full_outcome": original_conflict['outcome']}
                )
            # Removed redundant warning log, final_guild_id_log should be best effort.

        return {
            "success": True,
            "message": f"Conflict '{conflict_id}' resolved by Master as '{outcome_type}'. Effects determined.",
            "resolution_details": original_conflict
        }

# The test block (`if __name__ == '__main__':`) with mock classes should be removed from this file.
# It belongs in a separate test file.

if __name__ == '__main__':
    # Example Usage (for testing purposes)
    print("--- ConflictResolver Example Usage ---")

    # Mock services and data
    mock_rule_engine = "MockRuleEngineInstance"
    mock_notification_service = "MockNotificationServiceInstance"
    
    # Simplified rules_config for example
    sample_rules_config = {
        "simultaneous_move_to_limited_space": {
            "description": "Two entities attempt to move into the same space that can only occupy one.",
            "manual_resolution_required": False,
            "automatic_resolution": {
                "check_type": "opposed_check",
                "actor_check_details": {"skill_or_stat_to_use": "agility"},
                "target_check_details": {"skill_or_stat_to_use": "agility"},
                "outcome_rules": {
                    "higher_wins": True,
                    "tie_breaker_rule": "random",
                    "outcomes": {
                        "actor_wins": {"description": "Actor gets space.", "effects": ["actor_moves"]},
                        "target_wins": {"description": "Target gets space.", "effects": ["target_moves"]},
                    }
                }
            },
            "notification_format": { # Even if auto, can have a format for logging/review
                 "message": "Conflict: {actor_id} vs {target_id} for space {space_id}.",
                 "placeholders": ["actor_id", "target_id", "space_id"]
            }
        },
        "item_dispute": {
            "description": "Two players claim the same item.",
            "manual_resolution_required": True,
            "notification_format": {
                "message": "Manual resolution needed: Player {actor_id} and Player {target_id} dispute item {item_id}.",
                "placeholders": ["actor_id", "target_id", "item_id"]
            }
        }
    }

    resolver = ConflictResolver(mock_rule_engine, sample_rules_config, mock_notification_service)

    print("\n--- Testing analyze_actions_for_conflicts ---")
    player_actions = {
        "player1": [{"type": "MOVE", "target_space": "X1Y1", "speed": 10}],
        "player2": [{"type": "MOVE", "target_space": "X1Y1", "speed": 12}],
        "player3": [{"type": "GRAB", "item_id": "gold_idol", "target_item_location": "altar"}],
        "player4": [{"type": "GRAB", "item_id": "gold_idol", "target_item_location": "altar"}], # Needs different conflict type
    }
    conflicts = resolver.analyze_actions_for_conflicts(player_actions)
    # Note: The example analyze_actions_for_conflicts only looks for MOVE conflicts.
    # To detect item_dispute, more logic would be needed there.

    if not conflicts:
        print("No conflicts identified by basic analyzer.")
    
    for conflict in conflicts:
        print(f"\n--- Processing Conflict: {conflict.get('conflict_id')} ---")
        
        rule_for_conflict = sample_rules_config.get(conflict["type"])
        if not rule_for_conflict:
            print(f"No rule found for conflict type {conflict['type']}")
            continue

        if rule_for_conflict.get("manual_resolution_required"):
            print("Manual resolution path:")
            prepared_conflict = resolver.prepare_for_manual_resolution(conflict)
            print(f"Prepared for manual: {prepared_conflict.get('manual_resolution_info')}")
            
            # Simulate Master resolving it
            if prepared_conflict.get('status') == 'awaiting_manual_resolution':
                resolved_manually = resolver.process_master_resolution(
                    conflict_id=prepared_conflict['conflict_id'],
                    outcome_type="actor_wins", # Example master decision
                    params={"reason": "Master decided player1 was quicker"}
                )
                print(f"Manually resolved outcome: {resolved_manually}")
        else:
            print("Automatic resolution path:")
            auto_resolved_conflict = resolver.resolve_conflict_automatically(conflict)
            print(f"Automatically resolved outcome: {auto_resolved_conflict}")

    # Example for a purely manual conflict
    print("\n--- Testing purely manual conflict ---")
    manual_conflict_example = {
        "conflict_id": "manual_item_dispute_001",
        "type": "item_dispute", # This type is set to manual_resolution_required = True
        "involved_players": ["player3", "player4"],
        "details": {"item_id": "gold_idol", "location": "altar"},
        "status": "pending_resolution"
    }
    
    prepared_manual_conflict = resolver.prepare_for_manual_resolution(manual_conflict_example)
    print(f"Prepared manual conflict: {prepared_manual_conflict.get('manual_resolution_info')}")
    
    if prepared_manual_conflict.get('status') == 'awaiting_manual_resolution':
        final_manual_outcome = resolver.process_master_resolution(
            conflict_id=prepared_manual_conflict['conflict_id'],
            outcome_type="custom_split",
            params={"player3_gets": "idol_top_half", "player4_gets": "idol_bottom_half"}
        )
        print(f"Final manual outcome: {final_manual_outcome}")

    print("\n--- End of Example Usage ---")

