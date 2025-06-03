# bot/game/conflict_resolver.py
"""
Module for the ConflictResolver class, responsible for identifying and managing
game conflicts based on player actions and defined rules.
"""

import json # Required for dumping/loading conflict data to/from JSON string
import uuid # For generating unique conflict IDs
from typing import Any, Dict, List, Optional, TYPE_CHECKING

# Placeholder for actual RuleEngine and NotificationService classes
# from ..core.rule_engine import RuleEngine # Assuming RuleEngine might be in a core module
# from ..services.notification_service import NotificationService # Assuming a notification service
# Need a way to access db_adapter, maybe passed in init or accessed via a service locator
# from ..database.sqlite_adapter import SqliteAdapter # Assuming SqliteAdapter is needed directly

# Use TYPE_CHECKING to avoid circular dependencies if DbAdapter imports models
if TYPE_CHECKING:
    from ..database.sqlite_adapter import SqliteAdapter # Import for type hinting


class ConflictResolver:
    """
    Identifies, manages, and resolves conflicts that arise from player actions
    based on the game's rules configuration.
    """

    # Remove the in-memory dictionary storage
    # self.pending_manual_resolutions: Dict[str, Dict[str, Any]] = {} # REMOVE

    def __init__(self, rule_engine: Any, rules_config_data: Dict[str, Any], notification_service: Any, db_adapter: 'SqliteAdapter'):
        """
        Инициализирует ConflictResolver.

        Args:
            rule_engine: An instance of the RuleEngine (placeholder: Any).
                         This engine will be used for checks like skill checks, stat checks, etc. Must be async-compatible.
            rules_config_data: A dictionary containing the loaded rules configuration.
            notification_service: A service object responsible for sending notifications (placeholder: Any). Must be async-compatible.
            db_adapter: An instance of the SqliteAdapter for database operations.
        """
        self.rule_engine = rule_engine
        self.rules_config = rules_config_data
        self.notification_service = notification_service
        self.db_adapter = db_adapter # Store the db_adapter
        # The pending_manual_resolutions are now managed in the database
        print(f"ConflictResolver initialized. Database adapter integrated.")

    async def analyze_actions_for_conflicts(self, player_actions_map: Dict[str, List[Dict[str, Any]]], guild_id: str) -> List[Dict[str, Any]]:
        """
        Analyzes a map of player actions to identify potential conflicts.
        If a conflict requires manual resolution, it calls prepare_for_manual_resolution.
        If automatic, it calls resolve_conflict_automatically.

        Args:
            player_actions_map: A dictionary where keys are player IDs (str) and
                                values are lists of actions (Dict[str, Any])
                                submitted by that player for the current turn/tick.
                                Example action: {'type': 'MOVE', 'target_space': 'A1', 'player_id': 'p1', 'guild_id': 'g1'}
            guild_id: The ID of the guild the actions belong to.

        Returns:
            A list of conflict resolution instruction dictionaries.
            For automatic conflicts, this will be the resolved conflict structure.
            For manual conflicts, this will be the result of prepare_for_manual_resolution
            (which includes the conflict_id and status).
        """
        print(f"Analyzing actions for conflicts in guild {guild_id}: {player_actions_map}")
        
        processed_conflict_results: List[Dict[str, Any]] = []

        # Example: Simple check for two players moving to the same space
        space_claims: Dict[str, List[Dict[str, Any]]] = {}
        for player_id, actions in player_actions_map.items():
            for action in actions:
                # Ensure action has guild_id and player_id for conflict tracking
                action_with_context = action.copy()
                action_with_context["player_id"] = player_id
                action_with_context["guild_id"] = guild_id # Add guild_id to action context

                # Assuming action format is like {'type': 'MOVE', 'target_space': 'A1', ...}
                if action.get("type") == "MOVE":
                    target_space = action.get("target_space")
                    if target_space:
                        if target_space not in space_claims:
                            space_claims[target_space] = []
                        space_claims[target_space].append(action_with_context)
        
        for space_id, conflicting_actions in space_claims.items():
            if len(conflicting_actions) > 1: # Potential conflict
                conflict_type_id = "simultaneous_move_to_limited_space" # Example type
                rule_definition = self.rules_config.get(conflict_type_id)

                if not rule_definition:
                    print(f"Warning: No rule definition found for conflict type '{conflict_type_id}'. Skipping.")
                    continue

                # Extract involved players/entities and their types
                involved_entities: List[Dict[str, Any]] = []
                involved_player_ids = set()
                for action in conflicting_actions:
                    entity_id = action.get("player_id") # Assuming player actions cause this
                    # TODO: Determine entity type more dynamically. For now, assume Character from player_actions_map.
                    entity_type = "Character" 
                    if entity_id and entity_id not in involved_player_ids:
                         involved_entities.append({"id": entity_id, "type": entity_type})
                         involved_player_ids.add(entity_id)

                if not involved_entities:
                    print(f"Warning: Conflict identified ({conflict_type_id}) but no involved entities found. Skipping.")
                    continue

                # Construct a preliminary conflict object
                # conflict_id will be generated by prepare_for_manual_resolution or resolve_conflict_automatically
                current_conflict_details = {
                    "guild_id": guild_id, # Add guild_id
                    "type": conflict_type_id,
                    "involved_entities": involved_entities, # Use involved_entities list with type
                    "details": { # Details specific to this conflict type
                        "space_id": space_id,
                        "actions": conflicting_actions # The raw actions that caused it
                    },
                    "status": "identified" 
                }
                print(f"Identified preliminary conflict: {current_conflict_details}")

                if rule_definition.get("manual_resolution_required"):
                    # This will generate ID, store in DB, and notify
                    prepared_manual_conflict_result = await self.prepare_for_manual_resolution(current_conflict_details)
                    processed_conflict_results.append(prepared_manual_conflict_result)
                else:
                    # Resolve automatically and add the result
                    resolved_auto_conflict_result = await self.resolve_conflict_automatically(current_conflict_details)
                    processed_conflict_results.append(resolved_auto_conflict_result)
        
        # TODO: Add logic for other conflict types (e.g., item_dispute) based on rules_config

        return processed_conflict_results

    async def resolve_conflict_automatically(self, conflict: Dict[str, Any]) -> Dict[str, Any]:
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
        # If called directly, generate an ID. If routed from prepare_for_manual, it might have one.
        if not conflict_id:
             conflict_id = f"auto_res_{uuid.uuid4().hex[:8]}"
             conflict["conflict_id"] = conflict_id # Add ID to the object being processed

        print(f"Attempting async automatic resolution for conflict: {conflict_id} ({conflict_type_id})")

        if not conflict_type_id or conflict_type_id not in self.rules_config:
            error_msg = f"Error resolving automatically: Unknown conflict type '{conflict_type_id}' for conflict {conflict_id}."
            print(error_msg)
            conflict["status"] = "resolution_failed_unknown_type"
            conflict["outcome"] = {"description": error_msg}
            return conflict

        rule = self.rules_config[conflict_type_id]
        auto_res_config = rule.get("automatic_resolution", {})
        config_check_type = auto_res_config.get("check_type") # This is the key for RuleEngine's _rules_data.checks
        outcome_rules = auto_res_config.get("outcome_rules", {})

        if not config_check_type:
            error_msg = f"Automatic resolution rule for '{conflict_type_id}' missing 'check_type'."
            print(f"Error for conflict {conflict_id}: {error_msg}")
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
        # Determine actor and target based on rules config or convention
        # Assume the first entity in involved_entities is the actor, second is the target if exists.
        # This is a simplification and might need more complex logic based on specific conflict rules.
        actor_entity = involved_entities[0]
        actor_id = actor_entity["id"]
        actor_type = actor_entity["type"]

        target_entity = involved_entities[1] if len(involved_entities) > 1 else None
        target_id = target_entity["id"] if target_entity else None
        target_type = target_entity["type"] if target_entity else None

        # Context passed to RuleEngine should include anything needed for the check
        # This might include skills/stats to use (if not implicit in check_type), modifiers, etc.
        # Example context based on rules_config structure:
        actor_context = auto_res_config.get("actor_check_details", {})
        target_context = auto_res_config.get("target_check_details", {})

        try:
            # Perform the actor's check
            print(f"Calling RuleEngine for actor '{actor_id}' check type '{config_check_type}'...")
            # Assuming resolve_check is async and takes entity ID, type, check_type, and context
            actor_check_result = await self.rule_engine.resolve_check(
                entity_id=actor_id,
                entity_type=actor_type,
                check_type=config_check_type,
                context=actor_context, # Pass specific context for actor
                # Additional parameters might be needed by RuleEngine based on check_type
                # e.g., target_id, difficulty_class (DC)
                target_id=target_id if config_check_type == "opposed_check" else None,
                target_type=target_type if config_check_type == "opposed_check" else None,
                # If this is a check vs DC, DC might be in rules_config or conflict details
                # dc = outcome_rules.get("success_threshold"), # Example if RuleEngine takes DC directly
                conflict_details=conflict # Provide full conflict for context if needed by rules
            )
            print(f"RuleEngine actor check result for {actor_id}: {actor_check_result}")
            
            actor_roll = actor_check_result.get("total_roll_value")
            actor_check_outcome = actor_check_result.get("outcome") # e.g., "SUCCESS", "FAILURE"

            target_roll = None
            target_check_outcome = None

            # Perform target's check if it's an opposed check
            if config_check_type == "opposed_check" and target_id:
                 print(f"Calling RuleEngine for target '{target_id}' check type '{config_check_type}'...")
                 target_check_result = await self.rule_engine.resolve_check(
                    entity_id=target_id,
                    entity_type=target_type,
                    check_type=config_check_type, # Often the same check type for opposed
                    context=target_context, # Pass specific context for target
                    target_id=actor_id, # Target's perspective
                    target_type=actor_type,
                    conflict_details=conflict
                 )
                 print(f"RuleEngine target check result for {target_id}: {target_check_result}")
                 target_roll = target_check_result.get("total_roll_value")
                 target_check_outcome = target_check_result.get("outcome")


            # Determine the *final* conflict outcome based on RuleEngine results and outcome_rules
            # This logic depends heavily on how outcome_rules map RuleEngine results to conflict outcomes
            final_outcome_key = "tie" # Default
            winner_id = None # Default

            # Example simple outcome determination logic based on check_type and outcome_rules
            if config_check_type == "opposed_check" and target_id:
                # Compare rolls for opposed checks
                if actor_roll > target_roll:
                    final_outcome_key = "actor_wins"
                    winner_id = actor_id
                elif target_roll > actor_roll:
                    final_outcome_key = "target_wins"
                    winner_id = target_id
                else: # Tie
                    # Apply tie-breaker rule using RuleEngine if needed, or simple logic
                    tie_breaker = outcome_rules.get("tie_breaker_rule", "random")
                    if tie_breaker == "actor_preference":
                        final_outcome_key = "actor_wins" 
                        winner_id = actor_id
                    elif tie_breaker == "target_preference":
                        final_outcome_key = "target_wins" 
                        winner_id = target_id
                    elif tie_breaker == "random":
                        # Use RuleEngine for a random roll tie-breaker if available/configured
                        if self.rule_engine and hasattr(self.rule_engine, "resolve_dice_roll"):
                             # Assuming a simple 1d2 roll where 1 means actor wins, 2 means target wins
                             print("Calling RuleEngine for random tie-breaker (1d2)...")
                             tie_roll_result = await self.rule_engine.resolve_dice_roll("1d2")
                             if tie_roll_result and tie_roll_result.get('total', 0) == 1:
                                 final_outcome_key = "actor_wins"
                                 winner_id = actor_id
                             else:
                                 final_outcome_key = "target_wins"
                                 winner_id = target_id
                             print(f"Tie-breaker roll result: {tie_roll_result}. Winner: {winner_id}")
                        else: # Fallback if no dice roller or tie-breaker not configured
                            print("Warning: No RuleEngine dice roller for random tie-breaker. Defaulting to actor wins.")
                            final_outcome_key = "actor_wins"
                            winner_id = actor_id
                    # TODO: Implement "stat_comparison:stat_name" tie-breaker using RuleEngine.resolve_stat_comparison

            else: # Single entity check against a DC (or simple success/failure)
                # Map RuleEngine outcome (SUCCESS/FAILURE) to conflict outcome key
                if actor_check_outcome == "SUCCESS":
                    final_outcome_key = "actor_wins" # Represents success for the actor's action
                    winner_id = actor_id
                elif actor_check_outcome == "FAILURE":
                    final_outcome_key = "target_wins" # Represents failure for the actor (or environment "wins")
                # Add handling for degrees of success/failure if RuleEngine supports them


        except Exception as e:
            # Handle errors during RuleEngine calls
            error_msg = f"Error during RuleEngine check for conflict {conflict_id} ({conflict_type_id}): {e}"
            print(f"❌ {error_msg}")
            traceback.print_exc()
            conflict["status"] = "resolution_failed_rule_engine_error"
            conflict["outcome"] = {"description": error_msg}
            return conflict


        # Get the descriptive outcome based on the final_outcome_key
        resolved_outcome_details = outcome_rules.get("outcomes", {}).get(final_outcome_key, {})

        # Structure the final resolved conflict object
        conflict["status"] = "resolved_automatically"
        conflict["outcome"] = {
            "winner_id": winner_id,
            "actor_check_result": actor_check_result, # Include full result from RuleEngine
            "target_check_result": target_check_result if target_id else None,
            "outcome_key": final_outcome_key,
            "description": resolved_outcome_details.get("description", f"Automatic outcome: {final_outcome_key}"),
            "effects": resolved_outcome_details.get("effects", []), # Effects defined in rules_config
            "resolution_timestamp": await self.rule_engine.get_game_time() # Assume RuleEngine or similar provides game time
        }
        
        print(f"Conflict {conflict_id} ({conflict_type_id}) automatically resolved.")
        print(f"Outcome: {conflict['outcome']['outcome_key']}, Winner: {conflict['outcome'].get('winner_id')}")
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
            # Avoid saving/notifying if type is invalid
            return {"status": "preparation_failed_unknown_type", "message": error_msg, "original_conflict": conflict}

        rule = self.rules_config[conflict_type_id]
        if not rule.get("manual_resolution_required"):
             print(f"Warning: Conflict {conflict_type_id} is marked for automatic resolution but routed to manual preparation. Processing as manual.")
             # This shouldn't happen if analyze_actions_for_conflicts works correctly, but handle defensively.

        conflict_id = conflict.get("conflict_id") or uuid.uuid4().hex
        conflict["conflict_id"] = conflict_id # Ensure the conflict object has the ID
        conflict["status"] = "awaiting_manual_resolution" # Update status

        print(f"Preparing conflict '{conflict_id}' ({conflict_type_id}) for manual resolution.")

        try:
            # Store the conflict in the database
            # Assuming db_adapter has a method like save_pending_conflict
            # Need guild_id for partitioning/querying in the DB
            if not guild_id:
                 error_msg = f"Conflict {conflict_id} is missing guild_id, cannot save for manual resolution."
                 print(f"❌ {error_msg}")
                 conflict["status"] = "preparation_failed_no_guild_id"
                 return {"status": "preparation_failed_no_guild_id", "message": error_msg, "original_conflict": conflict}

            conflict_data_json = json.dumps(conflict) # Serialize the whole conflict dict
            await self.db_adapter.save_pending_conflict(
                 conflict_id=conflict_id,
                 guild_id=guild_id,
                 conflict_data=conflict_data_json
            )
            print(f"Conflict {conflict_id} saved to database for manual resolution.")

        except Exception as e:
            error_msg = f"Error saving conflict {conflict_id} to DB for manual resolution: {e}"
            print(f"❌ {error_msg}")
            traceback.print_exc()
            conflict["status"] = "preparation_failed_db_error"
            return {"status": "preparation_failed_db_error", "message": error_msg, "original_conflict": conflict}


        # Prepare notification message using the updated conflict object
        notification_fmt = rule.get("notification_format", {})
        message_template = notification_fmt.get("message", "Manual resolution required for {conflict_id}: {type}")
        
        # Prepare placeholders from the conflict data
        placeholders: Dict[str, Any] = {
            "conflict_id": conflict_id,
            "type": conflict_type_id,
            "description": rule.get("description", "N/A"),
            "involved_entities": conflict.get("involved_entities", []),
            # Add common simple placeholders
            "entity_ids_str": ", ".join([e.get('id', 'Unknown') for e in conflict.get("involved_entities", [])]),
            "entity_types_str": ", ".join([e.get('type', 'Unknown') for e in conflict.get("involved_entities", [])]),
            **(conflict.get('details', {})) # Include details from the conflict
        }
        # Add individual entity placeholders (e.g., entity1_id, actor_id)
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

        # Use the notification_service (assuming it's async)
        if self.notification_service:
             print(f"Simulating async notification service call for conflict {conflict_id}...")
             try:
                 # Assuming send_master_alert is async
                 await self.notification_service.send_master_alert(
                    conflict_id=conflict_id,
                    guild_id=guild_id, # Notification service needs guild_id
                    message=formatted_message,
                    conflict_details=conflict # Pass the full conflict data for context in the notification system
                 )
                 print(f"Notification sent for conflict {conflict_id}.")
             except Exception as e:
                 print(f"❌ Error sending notification for conflict {conflict_id}: {e}")
                 traceback.print_exc()


        # Return the status/info to the caller (e.g., ActionProcessor)
        return {
            "conflict_id": conflict_id,
            "status": "awaiting_manual_resolution",
            "message": f"Conflict '{conflict_id}' ({conflict_type_id}) requires manual resolution. Details saved and notification sent.",
            "details_for_master": formatted_message # Include formatted message in the return
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
        print(f"Processing Master resolution for conflict_id: {conflict_id}, outcome_type: {outcome_type}, params: {params}")

        try:
            # Retrieve the conflict from the database
            pending_conflict_row = await self.db_adapter.get_pending_conflict(conflict_id)
            if not pending_conflict_row:
                 print(f"❌ Error: Conflict ID '{conflict_id}' not found in pending manual resolutions database table.")
                 return {
                    "success": False,
                    "conflict_id": conflict_id,
                    "message": f"Error: Conflict ID '{conflict_id}' not found in pending manual resolutions."
                 }

            # Deserialize the stored conflict data
            original_conflict = json.loads(pending_conflict_row['conflict_data'])
            original_conflict["status"] = "resolved_manually" # Update status

            # Immediately remove the conflict from the pending table after retrieval
            await self.db_adapter.delete_pending_conflict(conflict_id)
            print(f"Conflict {conflict_id} retrieved and removed from database.")

        except Exception as e:
            error_msg = f"Error retrieving/deleting conflict {conflict_id} from DB for manual resolution: {e}"
            print(f"❌ {error_msg}")
            traceback.print_exc()
            return {
                "success": False,
                "conflict_id": conflict_id,
                "message": error_msg
            }

        print(f"Retrieved original conflict data for {conflict_id} ({original_conflict.get('type')}): {original_conflict.get('involved_entities')}")

        # --- Determine Outcome and Effects based on Master's choice and rules ---
        # Look up the rule for the original conflict type
        conflict_type_id = original_conflict.get("type")
        rule = self.rules_config.get(conflict_type_id)

        if not rule:
            error_msg = f"Error processing manual resolution: Rule definition for conflict type '{conflict_type_id}' not found."
            print(f"❌ {error_msg}")
            # Even though processed, mark outcome as failed internally
            original_conflict["status"] = "resolved_manually_failed_no_rule"
            original_conflict["outcome"] = {"description": error_msg}
            return {
                 "success": False,
                 "conflict_id": conflict_id,
                 "message": error_msg,
                 "resolution_details": original_conflict # Return the updated object
            }

        manual_res_config = rule.get("manual_resolution", {})
        # Manual outcomes might be explicitly listed under 'manual_resolution.outcomes'
        allowed_outcomes = manual_res_config.get("outcomes", {})

        # Find the effects associated with the chosen outcome_type
        # If the chosen outcome_type is not specifically defined, handle as a generic outcome or error
        chosen_outcome_details = allowed_outcomes.get(outcome_type)

        if not chosen_outcome_details:
             # Handle cases like a generic "custom" outcome or an invalid outcome type
             if outcome_type == "custom_outcome":
                  # Master provided custom details via params
                  effects_to_apply = params.get("effects", []) # Assume custom effects are passed in params
                  description = params.get("description", f"Master applied custom outcome.")
                  print(f"Processing custom outcome for {conflict_id} with params: {params}")
             else:
                error_msg = f"Warning: Master chose outcome type '{outcome_type}' which is not explicitly defined in rules for conflict type '{conflict_type_id}'. Using generic effects if any."
                print(error_msg)
                # Fallback: look for a generic 'default' or 'fallback' outcome, or use params if available
                chosen_outcome_details = allowed_outcomes.get("default") # Try a default outcome
                if chosen_outcome_details:
                    effects_to_apply = chosen_outcome_details.get("effects", [])
                    description = chosen_outcome_details.get("description", f"Master chose undefined outcome '{outcome_type}'. Default applied.")
                else:
                    # No specific or default outcome found, perhaps apply no effects or log an error
                    effects_to_apply = []
                    description = f"Master chose undefined outcome '{outcome_type}'. No specific outcome rule found and no default."
                    print(f"❌ No specific or default outcome found for {outcome_type} in manual resolution rules for {conflict_type_id}.")

             # Construct outcome details for a custom/undefined case
             outcome_data = {
                 "outcome_key": outcome_type,
                 "description": description,
                 "effects": effects_to_apply,
                 "parameters_applied": params if params else {},
                 "manual_override": True
             }
        else:
            # Found a specific defined outcome
            effects_to_apply = chosen_outcome_details.get("effects", [])
            description = chosen_outcome_details.get("description", f"Master chose defined outcome '{outcome_type}'.")
            outcome_data = {
                 "outcome_key": outcome_type,
                 "description": description,
                 "effects": effects_to_apply,
                 "parameters_applied": params if params else {}, # Still include params for context
                 "manual_override": True
            }


        # Structure the final resolved conflict object
        original_conflict["outcome"] = outcome_data
        original_conflict["resolved_by"] = "master"
        original_conflict["resolution_timestamp"] = await self.rule_engine.get_game_time() # Use game time

        print(f"Conflict {conflict_id} resolved manually by Master. Outcome: {outcome_type}. Details: {original_conflict['outcome']}")

        # The caller (e.g., ActionProcessor) is responsible for applying these effects to the game state.
        return {
            "success": True,
            "message": f"Conflict '{conflict_id}' resolved by Master as '{outcome_type}'. Effects determined.",
            "resolution_details": original_conflict # Return the full, updated conflict object
        }


# bot/database/sqlite_adapter.py
# --- Placeholder methods for pending_conflicts table ---
# IMPORTANT: These are examples. You need to integrate them into your actual SqliteAdapter class.

print(f"DEBUG: Adding pending_conflicts methods and migration to SqliteAdapter sketch.")

# Add a new LATEST_SCHEMA_VERSION
# LATEST_SCHEMA_VERSION = 12 # Old
LATEST_SCHEMA_VERSION = 13 # New version for pending_conflicts table

# Add the new migration method
async def _migrate_v12_to_v13(self, cursor: 'aiosqlite.Cursor') -> None:
    """Миграция с Версии 12 на Версию 13 (добавление таблицы pending_conflicts)."""
    print("SqliteAdapter: Running v12 to v13 migration (creating pending_conflicts table)...")
    await cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_conflicts (
            id TEXT PRIMARY KEY, -- Conflict ID
            guild_id TEXT NOT NULL, -- Which guild this conflict belongs to
            conflict_data TEXT NOT NULL, -- JSON string of the conflict dictionary
            created_at REAL NOT NULL DEFAULT (strftime('%s','now')) -- Timestamp when it was created
        );
    ''')
    await cursor.execute('''CREATE INDEX IF NOT EXISTS idx_pending_conflicts_guild_id ON pending_conflicts (guild_id);''')
    print("SqliteAdapter: 'pending_conflicts' table created and index applied IF NOT EXISTS.")
    print("SqliteAdapter: v12 to v13 migration complete.")


# Add placeholder methods to the SqliteAdapter class
async def save_pending_conflict(self, conflict_id: str, guild_id: str, conflict_data: str) -> None:
    """Saves or updates a pending manual conflict in the database."""
    sql = """
        INSERT INTO pending_conflicts (id, guild_id, conflict_data)
        VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            guild_id = excluded.guild_id,
            conflict_data = excluded.conflict_data,
            created_at = strftime('%s','now');
    """
    await self.execute(sql, (conflict_id, guild_id, conflict_data))
    print(f"SqliteAdapter: Saved pending conflict '{conflict_id}' for guild '{guild_id}'.")

async def get_pending_conflict(self, conflict_id: str) -> Optional['aiosqlite.Row']:
    """Retrieves a pending manual conflict by its ID."""
    sql = "SELECT id, guild_id, conflict_data FROM pending_conflicts WHERE id = ?;"
    row = await self.fetchone(sql, (conflict_id,))
    # Note: aiosqlite Row objects can be accessed like dictionaries
    print(f"SqliteAdapter: Fetched pending conflict '{conflict_id}': {row is not None}")
    return row

async def delete_pending_conflict(self, conflict_id: str) -> None:
    """Deletes a pending manual conflict by its ID."""
    sql = "DELETE FROM pending_conflicts WHERE id = ?;"
    await self.execute(sql, (conflict_id,))
    print(f"SqliteAdapter: Deleted pending conflict '{conflict_id}'.")

# --- End of Placeholder methods ---


# Example Usage (for testing purposes) - UPDATED FOR ASYNC AND DB ADAPTER MOCK
import asyncio
import traceback

# Mock the SqliteAdapter with the new methods for testing
class MockSqliteAdapter:
    def __init__(self):
        self._db = {} # In-memory dict to simulate DB table
        print("MockSqliteAdapter initialized (in-memory).")

    async def execute(self, sql: str, params: Optional[Union[Tuple, List]] = None):
        print(f"MockSqliteAdapter: Execute | SQL: {sql} | Params: {params}")
        # Simple simulation for ON CONFLICT (UPSERT)
        if sql.strip().startswith("INSERT"):
             if "ON CONFLICT" in sql:
                  # Very basic UPSERT simulation for pending_conflicts
                  if "pending_conflicts" in sql and params and len(params) >= 3:
                       conflict_id, guild_id, conflict_data = params[:3]
                       self._db[conflict_id] = {'id': conflict_id, 'guild_id': guild_id, 'conflict_data': conflict_data}
                       print(f"MockSqliteAdapter: Upserted pending conflict {conflict_id}")
                       return None # Simulate cursor behavior
                  else:
                       print("MockSqliteAdapter: Unhandled INSERT ON CONFLICT type")
                       return None
             else:
                  print("MockSqliteAdapter: Unhandled simple INSERT type")
                  return None
        elif sql.strip().startswith("DELETE"):
             if "pending_conflicts" in sql and params and len(params) >= 1:
                  conflict_id = params[0]
                  if conflict_id in self._db:
                       del self._db[conflict_id]
                       print(f"MockSqliteAdapter: Deleted pending conflict {conflict_id}")
                  else:
                       print(f"MockSqliteAdapter: Delete called for non-existent conflict {conflict_id}")
                  return None
             else:
                 print("MockSqliteAdapter: Unhandled DELETE type")
                 return None
        elif sql.strip().startswith("PRAGMA"):
             # Simulate schema version checks needed by SqliteAdapter init, but not by MockDb itself
             if 'user_version' in sql:
                 return MockCursor([('13',)], None) # Simulate latest version for simplicity
             if 'table_info(players)' in sql:
                  # Simulate needed columns for player loading
                  mock_player_cols = [
                      {'name': 'id'}, {'name': 'discord_user_id'}, {'name': 'name'}, {'name': 'name_i18n'},
                      {'name': 'guild_id'}, {'name': 'location_id'}, {'name': 'stats'}, {'name': 'inventory'},
                      {'name': 'current_action'}, {'name': 'action_queue'}, {'name': 'party_id'},
                      {'name': 'state_variables'}, {'name': 'health'}, {'name': 'max_health'}, {'name': 'is_alive'},
                      {'name': 'status_effects'}, {'name': 'level'}, {'name': 'experience'}, {'name': 'active_quests'},
                      {'name': 'created_at'}, {'name': 'last_played_at'}, {'name': 'race'}, {'name': 'mp'},
                      {'name': 'attack'}, {'name': 'defense'}, {'name': 'hp'}, {'name': 'unspent_xp'},
                      {'name': 'selected_language'}, {'name': 'current_game_status'}, {'name': 'collected_actions_json'},
                      {'name': 'current_party_id'}
                   ]
                  return MockCursor(mock_player_cols, ['name']) # Return columns like Row object
             if 'table_info(inventory)' in sql:
                  mock_inv_cols = [{'name': 'inventory_id'}, {'name': 'player_id'}, {'name': 'item_template_id'}, {'name': 'quantity'}, {'name': 'amount'}]
                  return MockCursor(mock_inv_cols, ['name'])
             # Add other PRAGMAs as needed for the mocked migrations if running SqliteAdapter.initialize_database
             print(f"MockSqliteAdapter: Unhandled PRAGMA: {sql}")
             return MockCursor([], None) # Return empty cursor for unhandled PRAGMAs
        else:
             print(f"MockSqliteAdapter: Unhandled execute type: {sql}")
             return None

    async def fetchone(self, sql: str, params: Optional[Union[Tuple, List]] = None):
        print(f"MockSqliteAdapter: FetchOne | SQL: {sql} | Params: {params}")
        if sql.strip().startswith("SELECT"):
            if "pending_conflicts" in sql and "WHERE id = ?" in sql and params and len(params) >= 1:
                conflict_id = params[0]
                row = self._db.get(conflict_id)
                if row:
                    # Simulate aiosqlite.Row
                    return MockRow(row)
                else:
                    return None
            else:
                 print(f"MockSqliteAdapter: Unhandled SELECT type: {sql}")
                 return None
        else:
            print(f"MockSqliteAdapter: Unhandled fetchone type: {sql}")
            return None
    
    async def fetchall(self, sql: str, params: Optional[Union[Tuple, List]] = None) -> List['aiosqlite.Row']:
         print(f"MockSqliteAdapter: FetchAll | SQL: {sql} | Params: {params}")
         if sql.strip().startswith("SELECT"):
             if "pending_conflicts" in sql and "WHERE guild_id = ?" in sql:
                  guild_id = params[0] if params else None
                  rows = [MockRow(c) for c in self._db.values() if c.get('guild_id') == guild_id]
                  print(f"MockSqliteAdapter: Found {len(rows)} pending conflicts for guild {guild_id}")
                  return rows
             # Add other select queries as needed
             else:
                print(f"MockSqliteAdapter: Unhandled SELECT ALL type: {sql}")
                return []
         else:
              print(f"MockSqliteAdapter: Unhandled fetchall type: {sql}")
              return []

    async def commit(self):
        print("MockSqliteAdapter: Commit (simulated)")
        pass # No-op for in-memory mock

    async def rollback(self):
        print("MockSqliteAdapter: Rollback (simulated)")
        pass # No-op for in-memory mock

    # Need to add the placeholder methods defined above to this mock class
    async def save_pending_conflict(self, conflict_id: str, guild_id: str, conflict_data: str) -> None:
         # This mock method replaces the execute call in the real adapter method
         print(f"MockSqliteAdapter: Calling save_pending_conflict('{conflict_id}', '{guild_id}', data_length={len(conflict_data)})")
         # Simulate upsert
         self._db[conflict_id] = {'id': conflict_id, 'guild_id': guild_id, 'conflict_data': conflict_data}
         print(f"MockSqliteAdapter: Saved/Updated pending conflict {conflict_id} in mock DB.")

    async def get_pending_conflict(self, conflict_id: str) -> Optional['aiosqlite.Row']:
         # This mock method replaces the fetchone call in the real adapter method
         print(f"MockSqliteAdapter: Calling get_pending_conflict('{conflict_id}')")
         row_data = self._db.get(conflict_id)
         if row_data:
              print(f"MockSqliteAdapter: Found pending conflict {conflict_id} in mock DB.")
              return MockRow(row_data) # Return a MockRow object
         else:
              print(f"MockSqliteAdapter: Pending conflict {conflict_id} not found in mock DB.")
              return None

    async def delete_pending_conflict(self, conflict_id: str) -> None:
         # This mock method replaces the execute call in the real adapter method
         print(f"MockSqliteAdapter: Calling delete_pending_conflict('{conflict_id}')")
         if conflict_id in self._db:
              del self._db[conflict_id]
              print(f"MockSqliteAdapter: Deleted pending conflict {conflict_id} from mock DB.")
         else:
              print(f"MockSqliteAdapter: Delete called for non-existent pending conflict {conflict_id} in mock DB.")

# Helper mock class to simulate aiosqlite.Row
class MockRow:
    def __init__(self, data):
        self._data = data
        self._keys = list(data.keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._keys

    def __repr__(self):
        return f"MockRow({self._data})"

# Helper mock class for RuleEngine (assuming async methods)
class MockRuleEngine:
    def __init__(self):
        print("MockRuleEngine initialized.")

    async def resolve_check(self, entity_id: str, entity_type: str, check_type: str, context: Dict[str, Any], target_id: Optional[str] = None, target_type: Optional[str] = None, conflict_details: Dict[str, Any] = None) -> Dict[str, Any]:
        print(f"MockRuleEngine: Simulating async resolve_check for {entity_type} '{entity_id}', type '{check_type}'...")
        await asyncio.sleep(0.01) # Simulate async delay

        # Simple mock logic: Actor roll is 15, Target roll is 12
        # This will make actor_wins in opposed checks based on 'higher_wins'
        mock_roll = 15 if entity_id.startswith('player1') else 12 # Simple bias for testing
        outcome = "SUCCESS" if mock_roll >= 10 else "FAILURE" # Simple DC simulation

        return {
            "total_roll_value": mock_roll,
            "is_success": outcome == "SUCCESS",
            "outcome": outcome,
            "description": f"Mock {check_type} for {entity_id}",
            "rolls": [mock_roll - 5], # Simulate a die roll + modifier
            "modifier_applied": 5
        }
    
    async def resolve_dice_roll(self, dice_notation: str) -> Dict[str, Any]:
        print(f"MockRuleEngine: Simulating async resolve_dice_roll('{dice_notation}')")
        await asyncio.sleep(0.01) # Simulate async delay
        # Simple mock for 1d2 tie-breaker: always return 1 (actor wins)
        if dice_notation == "1d2":
             return {"total": 1, "rolls": [1], "modifier_applied": 0}
        # Add other simple mocks if needed
        return {"total": 1, "rolls": [1], "modifier_applied": 0}
        
    async def get_game_time(self) -> float:
        """Simulate getting current game time."""
        return asyncio.get_event_loop().time() # Use real elapsed time for mock timestamp

# Helper mock class for NotificationService (assuming async methods)
class MockNotificationService:
    def __init__(self):
        print("MockNotificationService initialized.")

    async def send_master_alert(self, conflict_id: str, guild_id: str, message: str, conflict_details: Dict[str, Any]):
        print(f"MockNotificationService: Simulating async send_master_alert for conflict '{conflict_id}' in guild '{guild_id}'")
        print(f"Message: {message}")
        print(f"Conflict Details (partial): Type={conflict_details.get('type')}, Entities={[e['id'] for e in conflict_details.get('involved_entities',[])]}")
        print("--- END MOCK NOTIFICATION ---")
        await asyncio.sleep(0.01) # Simulate async delay


async def main():
    print("--- Async ConflictResolver Example Usage (Mocked) ---")

    # Mock services and data
    mock_rule_engine = MockRuleEngine()
    mock_db_adapter = MockSqliteAdapter()
    mock_notification_service = MockNotificationService()
    
    # Simplified rules_config for example
    sample_rules_config = {
        "simultaneous_move_to_limited_space": {
            "description": "Two entities attempt to move into the same space that can only occupy one.",
            "manual_resolution_required": False,
            "automatic_resolution": {
                "check_type": "opposed_skill_check", # Changed to opposed_skill_check for example RuleEngine mock
                "actor_check_details": {"skill_to_use": "agility"}, # Context for RuleEngine
                "target_check_details": {"skill_to_use": "agility"}, # Context for RuleEngine
                "outcome_rules": {
                    "higher_wins": True,
                    "tie_breaker_rule": "random", # Uses RuleEngine.resolve_dice_roll("1d2")
                    "outcomes": {
                        "actor_wins": {"description": "Actor gets space.", "effects": [{"type": "move_entity", "target": "actor", "location_id": "{space_id}"}, {"type": "fail_action", "target": "target"}]}, # Example effects using placeholders
                        "target_wins": {"description": "Target gets space.", "effects": [{"type": "move_entity", "target": "target", "location_id": "{space_id}"}, {"type": "fail_action", "target": "actor"}]},
                        "tie": {"description": "Tie breaker applied.", "effects": []} # Effects would come from the tie winner outcome
                    }
                }
            },
            "notification_format": { # Even if auto, can have a format for logging/review
                 "message": "Conflict: {actor_id} vs {target_id} for space {space_id}. Result: Auto resolved.",
                 "placeholders": ["actor_id", "target_id", "space_id"]
            }
        },
        "item_dispute": {
            "description": "Two players claim the same item.",
            "manual_resolution_required": True,
             "manual_resolution": {
                "outcomes": { # Explicitly defined manual outcomes
                    "player1_wins": {"description": "{actor_id} gets the item.", "effects": [{"type": "give_item", "target": "{actor_id}", "item_id": "{item_id}"}, {"type": "notify_player", "target": "{target_id}", "message": "You lost the item dispute."}]},
                    "player2_wins": {"description": "{target_id} gets the item.", "effects": [{"type": "give_item", "target": "{target_id}", "item_id": "{item_id}"}, {"type": "notify_player", "target": "{actor_id}", "message": "You lost the item dispute."}]},
                    "split_item": {"description": "Master split the item.", "effects": [{"type": "give_item", "target": "{actor_id}", "item_id": "{item_id}_half"}, {"type": "give_item", "target": "{target_id}", "item_id": "{item_id}_half"}]} # Example split
                    # "custom_outcome": {} # Could define a placeholder if custom is handled generically
                }
             },
            "notification_format": {
                "message": "Manual resolution needed (ID: {conflict_id}): Player {actor_id} and Player {target_id} dispute item {item_id} in {location}.",
                "placeholders": ["conflict_id", "actor_id", "target_id", "item_id", "location"] # location from conflict['details']
            }
        }
    }

    resolver = ConflictResolver(mock_rule_engine, sample_rules_config, mock_notification_service, mock_db_adapter)

    print("\n--- Testing analyze_actions_for_conflicts (Automatic) ---")
    guild_id_1 = "guild_abc"
    player_actions_auto = {
        "player1": [{"type": "MOVE", "target_space": "X1Y1", "speed": 10}],
        "player2": [{"type": "MOVE", "target_space": "X1Y1", "speed": 12}],
    }
    conflicts_auto = await resolver.analyze_actions_for_conflicts(player_actions_auto, guild_id_1)

    print("\nIdentified/Processed Automatic Conflicts:")
    for c in conflicts_auto:
         print(f"- ID: {c.get('conflict_id')}, Type: {c.get('type')}, Status: {c.get('status')}, Outcome: {c.get('outcome', {}).get('outcome_key')}")
         # In real code, you'd now queue the effects from c['outcome']['effects'] for application

    print("\n--- Testing analyze_actions_for_conflicts (Manual) ---")
    guild_id_2 = "guild_xyz"
    player_actions_manual = {
        "player3": [{"type": "GRAB", "item_id": "gold_idol", "target_item_location": "altar_room"}],
        "player4": [{"type": "GRAB", "item_id": "gold_idol", "target_item_location": "altar_room"}],
    }
    # NOTE: The current simple analyze_actions_for_conflicts only detects MOVE conflicts.
    # To test the manual path, we need to manually create a conflict object and pass it
    # through prepare_for_manual_resolution, simulating what a more complete analyzer would do.
    
    print("Simulating creation of a manual conflict by a more complete analyzer...")
    manual_conflict_simulated = {
        "guild_id": guild_id_2,
        "type": "item_dispute",
        "involved_entities": [{"id": "player3", "type": "Character"}, {"id": "player4", "type": "Character"}],
        "details": {"item_id": "gold_idol", "location": "altar_room"},
        "status": "identified"
    }
    
    # This would normally be part of the list returned by analyze_actions_for_conflicts
    prepared_manual_conflict_result = await resolver.prepare_for_manual_resolution(manual_conflict_simulated)
    print("\nPrepared Manual Conflict:")
    print(f"- ID: {prepared_manual_conflict_result.get('conflict_id')}, Status: {prepared_manual_conflict_result.get('status')}")
    print(f"  Message for Master: {prepared_manual_conflict_result.get('details_for_master')}")
    
    conflict_id_manual = prepared_manual_conflict_result.get('conflict_id')

    print("\n--- Simulating Master Resolution ---")
    if prepared_manual_conflict_result.get('status') == 'awaiting_manual_resolution':
        print(f"Master deciding outcome for conflict {conflict_id_manual}...")
        master_outcome_type = "player1_wins" # Master chooses player3 (actor) wins
        master_resolution_params = {"reason": "Player3 reached it first"}
        
        final_manual_outcome = await resolver.process_master_resolution(
            conflict_id=conflict_id_manual,
            outcome_type=master_outcome_type,
            params=master_resolution_params
        )
        print("\nFinal Manual Resolution Outcome:")
        print(f"- Success: {final_manual_outcome.get('success')}")
        print(f"- Message: {final_manual_outcome.get('message')}")
        resolution_details = final_manual_outcome.get('resolution_details', {})
        print(f"- Conflict Status: {resolution_details.get('status')}")
        print(f"- Chosen Outcome Key: {resolution_details.get('outcome', {}).get('outcome_key')}")
        print(f"- Effects to Apply: {resolution_details.get('outcome', {}).get('effects')}")

        # Test getting the conflict again (should be gone)
        print(f"\nAttempting to retrieve conflict {conflict_id_manual} from mock DB after resolution...")
        should_be_none = await mock_db_adapter.get_pending_conflict(conflict_id_manual)
        print(f"Result: {should_be_none}")


    print("\n--- End of Async Example Usage ---")


if __name__ == '__main__':
    # This block is standard for running async examples
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"An error occurred during example execution: {e}")
        traceback.print_exc()
