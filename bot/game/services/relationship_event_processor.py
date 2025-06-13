from __future__ import annotations
import asyncio
import json
import traceback
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.game.managers.rule_engine import RuleEngine
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.game_log_manager import GameLogManager

class RelationshipEventProcessor:
    def __init__(
        self,
        rule_engine: RuleEngine,
        relationship_manager: RelationshipManager,
        game_log_manager: GameLogManager # For logging issues within the processor itself
    ):
        self._rule_engine = rule_engine
        self._relationship_manager = relationship_manager
        self._game_log_manager = game_log_manager
        # _last_processed_log_timestamp is omitted for now as per subtask focus.
        # Reprocessing prevention would need a more robust mechanism (e.g., log IDs or a persistent queue).
        print("RelationshipEventProcessor initialized.")

    async def process_new_log_entry(self, log_entry_data: Dict[str, Any]) -> None:
        """
        Processes a single new log entry to potentially update relationships.
        log_entry_data is expected to contain:
        - guild_id: str
        - event_type: str
        - details: str (JSON string of the event details)
        - Optional: player_id, log_id for context/tracing
        """
        guild_id = log_entry_data.get('guild_id')
        event_type = log_entry_data.get('event_type')
        details_json_str = log_entry_data.get('details')
        log_id_for_trace = log_entry_data.get('log_id', 'N/A') # For logging/tracing

        if not all([guild_id, event_type, details_json_str]):
            error_msg = f"REP: Missing guild_id, event_type, or details in log entry (Log ID: {log_id_for_trace}). Cannot process."
            # print(error_msg) # Basic print for now
            if self._game_log_manager: # Log to GameLogManager if available
                 # This could create a feedback loop if REP logs trigger REP. Be cautious.
                 # For critical errors like this, it might be okay.
                 # Consider a separate, simple logger for REP's own operational logs.
                pass # For now, avoid logging REP's operational errors back through GameLogManager here to prevent loops.
            return

        try:
            # Check if there are any relationship change rules for this event_type
            # Assuming _rules_data is a dict-like structure on RuleEngine instance
            if not self._rule_engine._rules_data: # Ensure rules_data is loaded
                print(f"REP: Rule engine data not loaded. Cannot process event {event_type} (Log ID: {log_id_for_trace}).")
                return

            relation_change_rules = self._rule_engine._rules_data.get("relation_rules", {}) # Using "relation_rules" as per previous subtask
            if not relation_change_rules:
                relation_change_rules = self._rule_engine._rules_data.get("relation_change_rules", {})


            if event_type not in relation_change_rules:
                # print(f"REP: No relationship change rules for event_type '{event_type}'. Skipping. (Log ID: {log_id_for_trace})")
                return

            # Parse the JSON string details into a dictionary
            event_data: Dict[str, Any]
            try:
                if isinstance(details_json_str, dict): # If details is already a dict (e.g. from internal call)
                    event_data = details_json_str
                else:
                    event_data = json.loads(details_json_str)
                if not isinstance(event_data, dict):
                    raise ValueError("Parsed details is not a dictionary.")
            except (json.JSONDecodeError, ValueError) as e:
                error_msg = f"REP: Failed to parse 'details' JSON string for event_type '{event_type}' (Log ID: {log_id_for_trace}). Error: {e}. Details: '{details_json_str[:200]}...'"
                print(error_msg)
                # Potentially log this error using a dedicated logger or self._game_log_manager if safe
                return

            # Call RelationshipManager.update_relationship
            # update_relationship expects event_data as **kwargs
            print(f"REP: Processing event '{event_type}' for guild '{guild_id}' for relationship updates. (Log ID: {log_id_for_trace})")
            await self._relationship_manager.update_relationship(
                guild_id=str(guild_id), # Ensure string
                event_type=str(event_type), # Ensure string
                rule_engine=self._rule_engine, # Pass the rule_engine instance
                game_log_manager=self._game_log_manager, # Pass game_log_manager for its use
                **event_data # Unpack event_data dictionary as keyword arguments
            )
            # print(f"REP: Finished processing event '{event_type}' for guild '{guild_id}' for relationship updates. (Log ID: {log_id_for_trace})")

        except Exception as e:
            error_msg = f"REP: Unexpected error processing log entry (Log ID: {log_id_for_trace}, Event: {event_type}): {e}\n{traceback.format_exc()}"
            print(error_msg)
            # Potentially log this error
            # Be careful with logging to GameLogManager here to avoid loops.
            # Consider a simple file logger or print for REP's own operational issues.
```
