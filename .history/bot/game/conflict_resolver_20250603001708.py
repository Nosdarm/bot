# bot/game/conflict_resolver.py
"""
Module for the ConflictResolver class, responsible for identifying and managing
game conflicts based on player actions and defined rules.
"""

# Импорты, необходимые для ConflictResolver
import json
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union, Tuple

# Используем TYPE_CHECKING для импорта, который нужен только для аннотаций типов
# и предотвращает циклический импорт, если адаптер БД зависит от моделей или других частей игры.
if TYPE_CHECKING:
    from ..database.sqlite_adapter import SqliteAdapter # Import for type hinting (forward reference)

# Placeholder for actual RuleEngine and NotificationService classes
# from ..core.rule_engine import RuleEngine # Assuming RuleEngine might be in a core module
# from ..services.notification_service import NotificationService # Assuming a notification service


class ConflictResolver:
    """
    Identifies, manages, and resolves conflicts that arise from player actions
    based on the game's rules configuration.
    """

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
        print(f"ConflictResolver initialized with db_adapter.")

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
        if not conflict_id:
             conflict_id = f"auto_res_{uuid.uuid4().hex[:8]}"
             conflict["conflict_id"] = conflict_id # Add ID to the object being processed

        print(f"Attempting async automatic resolution for conflict: {conflict_id} ({conflict_type_id})")

        if not conflict_type_id or conflict_type_id not in self.rules_config:
            error_msg = f"Error resolving automatically: Unknown conflict type '{conflict_type_id}' for conflict {conflict_id}."
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
            target_check_result = None # Initialize to None

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
            import traceback
            traceback.print_exc()
            conflict["status"] = "resolution_failed_rule_engine_error"
            conflict["outcome"] = {"description": error_msg}
            return conflict

        resolved_outcome_details = outcome_rules.get("outcomes", {}).get(final_outcome_key, {})

        conflict["status"] = "resolved_automatically"
        # Populate outcome using results from RuleEngine and rules_config
        conflict["outcome"] = {
            "winner_id": winner_id,
            "actor_check_result": actor_check_result,
            "target_check_result": target_check_result if target_id else None,
            "outcome_key": final_outcome_key,
            "description": resolved_outcome_details.get("description", f"Automatic outcome: {final_outcome_key}"),
            "effects": resolved_outcome_details.get("effects", []),
            "resolution_timestamp": await self.rule_engine.get_game_time() if hasattr(self.rule_engine, 'get_game_time') else None # Get game time if possible
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
            return {"status": "preparation_failed_unknown_type", "message": error_msg, "original_conflict": conflict}

        rule = self.rules_config[conflict_type_id]
        # Check rule.get("manual_resolution_required") is implicitly handled by where this method is called

        conflict_id = conflict.get("conflict_id") or uuid.uuid4().hex
        conflict["conflict_id"] = conflict_id
        conflict["status"] = "awaiting_manual_resolution"

        print(f"Preparing conflict '{conflict_id}' ({conflict_type_id}) for manual resolution.")

        try:
            if not guild_id:
                 error_msg = f"Conflict {conflict_id} is missing guild_id, cannot save for manual resolution."
                 print(f"❌ {error_msg}")
                 conflict["status"] = "preparation_failed_no_guild_id"
                 return {"status": "preparation_failed_no_guild_id", "message": error_msg, "original_conflict": conflict}

            conflict_data_json = json.dumps(conflict)
            # Use the db_adapter instance passed in __init__
            await self.db_adapter.save_pending_conflict(
                 conflict_id=conflict_id,
                 guild_id=guild_id,
                 conflict_data=conflict_data_json
            )
            print(f"Conflict {conflict_id} saved to database for manual resolution.")

        except Exception as e:
            error_msg = f"Error saving conflict {conflict_id} to DB for manual resolution: {e}"
            print(f"❌ {error_msg}")
            import traceback
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
             print(f"Simulating async notification service call for conflict {conflict_id}...")
             try:
                 # Use the notification_service instance passed in __init__
                 await self.notification_service.send_master_alert(
                    conflict_id=conflict_id,
                    guild_id=guild_id,
                    message=formatted_message,
                    conflict_details=conflict
                 )
                 print(f"Notification sent for conflict {conflict_id}.")
             except Exception as e:
                 print(f"❌ Error sending notification for conflict {conflict_id}: {e}")
                 import traceback
                 traceback.print_exc()


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
        print(f"Processing Master resolution for conflict_id: {conflict_id}, outcome_type: {outcome_type}, params: {params}")

        try:
            # Use the db_adapter instance passed in __init__
            pending_conflict_row = await self.db_adapter.get_pending_conflict(conflict_id)
            if not pending_conflict_row:
                 print(f"❌ Error: Conflict ID '{conflict_id}' not found in pending manual resolutions database table.")
                 return {
                    "success": False,
                    "conflict_id": conflict_id,
                    "message": f"Error: Conflict ID '{conflict_id}' not found in pending manual resolutions."
                 }

            original_conflict = json.loads(pending_conflict_row['conflict_data'])
            original_conflict["status"] = "resolved_manually" # Update status

            # Immediately remove the conflict from the pending table after retrieval
            await self.db_adapter.delete_pending_conflict(conflict_id)
            print(f"Conflict {conflict_id} retrieved and removed from database.")

        except Exception as e:
            error_msg = f"Error retrieving/deleting conflict {conflict_id} from DB for manual resolution: {e}"
            print(f"❌ {error_msg}")
            import traceback
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
        original_conflict["resolution_timestamp"] = await self.rule_engine.get_game_time() if hasattr(self.rule_engine, 'get_game_time') else None # Get game time if possible


        print(f"Conflict {conflict_id} resolved manually by Master. Outcome: {outcome_type}. Details: {original_conflict['outcome']}")

        return {
            "success": True,
            "message": f"Conflict '{conflict_id}' resolved by Master as '{outcome_type}'. Effects determined.",
            "resolution_details": original_conflict
        }

# Keep the Character model definition here as it was provided and confirmed correct
@dataclass
class Character:
    # ... (определение класса Character без изменений) ...
    id: str
    discord_user_id: int
    name_i18n: Dict[str, str]
    guild_id: str

    location_id: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    inventory: List[Dict[str, Any]] = field(default_factory=list)
    current_action: Optional[Dict[str, Any]] = None
    action_queue: List[Dict[str, Any]] = field(default_factory=list)
    party_id: Optional[str] = None
    state_variables: Dict[str, Any] = field(default_factory=dict)

    hp: float = 100.0
    max_health: float = 100.0
    is_alive: bool = True

    status_effects: List[Dict[str, Any]] = field(default_factory=list)
    level: int = 1
    experience: int = 0
    unspent_xp: int = 0
    active_quests: List[str] = field(default_factory=list)

    known_spells: List[str] = field(default_factory=list)
    spell_cooldowns: Dict[str, float] = field(default_factory=dict)
    skills: Dict[str, int] = field(default_factory=dict)

    known_abilities: List[str] = field(default_factory=list)
    ability_cooldowns: Dict[str, float] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)
    char_class: Optional[str] = None

    selected_language: Optional[str] = None
    current_game_status: Optional[str] = None
    collected_actions_json: Optional[str] = None
    current_party_id: Optional[str] = None

    def __post_init__(self):
        if 'hp' not in self.stats:
            self.stats['hp'] = self.hp
        else:
            self.hp = float(self.stats.get('hp', self.hp))

        if 'max_health' not in self.stats:
            self.stats['max_health'] = self.max_health
        else:
            self.max_health = float(self.stats.get('max_health', self.max_health))

        if 'mana' not in self.stats:
            self.stats['mana'] = self.stats.get('max_mana', 50)
        if 'max_mana' not in self.stats:
            self.stats['max_mana'] = self.stats.get('mana', 50)
        if 'intelligence' not in self.stats:
            self.stats['intelligence'] = 10

        if self.collected_actions_json is not None and not isinstance(self.collected_actions_json, str):
             try:
                 self.collected_actions_json = json.dumps(self.collected_actions_json)
             except TypeError as e:
                 print(f"WARNING: Could not json.dumps collected_actions_json in __post_init__: {e}. Value was: {self.collected_actions_json}")
                 self.collected_actions_json = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Character:
        if 'guild_id' not in data:
            raise ValueError("Missing 'guild_id' key in data for Character.from_dict")
        if 'id' not in data or 'discord_user_id' not in data or ('name' not in data and 'name_i18n' not in data):
            raise ValueError("Missing core fields (id, discord_user_id, and name/name_i18n) for Character.from_dict")

        data_copy = data.copy()

        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {"en": data_copy.pop("name")}
        elif "name" in data_copy and "name_i18n" in data_copy:
             data_copy.pop("name")

        collected_actions_data = data_copy.get('collected_actions_json')
        if collected_actions_data is None:
             collected_actions_data = data_copy.get('собранные_действия_JSON')

        init_data = {
            'id': data_copy.get('id'),
            'discord_user_id': data_copy.get('discord_user_id'),
            'name_i18n': data_copy.get('name_i18n'),
            'guild_id': data_copy.get('guild_id'),
            'location_id': data_copy.get('location_id'),
            'stats': data_copy.get('stats', {}),
            'inventory': data_copy.get('inventory', []),
            'current_action': data_copy.get('current_action'),
            'action_queue': data_copy.get('action_queue', []),
            'party_id': data_copy.get('party_id'),
            'state_variables': data_copy.get('state_variables', {}),

            'hp': float(data_copy.get('hp', data_copy['stats'].get('hp', 100.0)) if 'stats' in data_copy else data_copy.get('hp', 100.0)),
            'max_health': float(data_copy.get('max_health', data_copy['stats'].get('max_health', 100.0)) if 'stats' in data_copy else data_copy.get('max_health', 100.0)),

            'is_alive': bool(data_copy.get('is_alive', True)),
            'status_effects': data_copy.get('status_effects', []),
            'level': int(data_copy.get('level', 1)),
            'experience': int(data_copy.get('experience', 0)),
            'unspent_xp': int(data_copy.get('unspent_xp', 0)),
            'active_quests': data_copy.get('active_quests', []),

            'known_spells': data_copy.get('known_spells', []),
            'spell_cooldowns': data_copy.get('spell_cooldowns', {}),
            'skills': data_copy.get('skills', {}),

            'known_abilities': data_copy.get('known_abilities', []),
            'ability_cooldowns': data_copy.get('ability_cooldowns', {}),
            'flags': data_copy.get('flags', []),
            'char_class': data_copy.get('char_class'),

            'selected_language': data_copy.get('selected_language'),
            'current_game_status': data_copy.get('current_game_status'),
            'collected_actions_json': collected_actions_data,
            'current_party_id': data_copy.get('current_party_id'),
        }

        if 'stats' in init_data:
             init_data['stats']['hp'] = float(init_data['hp'])
             init_data['stats']['max_health'] = float(init_data['max_health'])
        else:
             init_data['stats'] = {'hp': float(init_data['hp']), 'max_health': float(init_data['max_health'])}


        return cls(**init_data)

    def to_dict(self) -> Dict[str, Any]:
        if self.stats is None:
            self.stats = {}
        self.stats['hp'] = self.hp
        self.stats['max_health'] = self.max_health

        return {
            "id": self.id,
            "discord_user_id": self.discord_user_id,
            "name_i18n": self.name_i18n,
            "guild_id": self.guild_id,
            "location_id": self.location_id,
            "stats": self.stats,
            "inventory": self.inventory,
            "current_action": self.current_action,
            "action_queue": self.action_queue,
            "party_id": self.party_id,
            "state_variables": self.state_variables,
            "hp": self.hp,
            "max_health": self.max_health,
            "is_alive": self.is_alive,
            "status_effects": self.status_effects,
            "level": self.level,
            "experience": self.experience,
            "unspent_xp": self.unspent_xp,
            "active_quests": self.active_quests,
            "known_spells": self.known_spells,
            "spell_cooldowns": self.spell_cooldowns,
            "skills": self.skills,
            "known_abilities": self.known_abilities,
            "ability_cooldowns": self.ability_cooldowns,
            "flags": self.flags,
            "char_class": self.char_class,
            "selected_language": self.selected_language,
            "current_game_status": self.current_game_status,
            "collected_actions_json": self.collected_actions_json,
            "current_party_id": self.current_party_id,
        }
