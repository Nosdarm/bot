from __future__ import annotations
import json
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.npc_manager import NpcManager # Added
    from bot.game.managers.location_manager import LocationManager # Added
    # Add other managers if they become necessary for more complex undo scenarios

class UndoManager:
    def __init__(
        self,
        db_service: Optional[DBService] = None,
        game_log_manager: Optional[GameLogManager] = None,
        character_manager: Optional[CharacterManager] = None,
        item_manager: Optional[ItemManager] = None,
        quest_manager: Optional[QuestManager] = None,
        party_manager: Optional[PartyManager] = None,
        npc_manager: Optional[NpcManager] = None, # Added
        location_manager: Optional[LocationManager] = None, # Added
        # settings: Optional[Dict[str, Any]] = None, # If needed later
    ):
        self._db_service = db_service
        self._game_log_manager = game_log_manager
        self._character_manager = character_manager
        self._item_manager = item_manager
        self._quest_manager = quest_manager
        self._party_manager = party_manager
        self._npc_manager = npc_manager # Added
        self._location_manager = location_manager # Added
        # self._settings = settings

        if not self._game_log_manager:
            print("CRITICAL: UndoManager initialized without GameLogManager!")
        # Add similar checks for other essential managers

    async def undo_last_player_event(self, guild_id: str, player_id: str, num_steps: int = 1) -> bool:
        """Undoes the last 'num_steps' events for a specific player."""
        print(f"UndoManager: Attempting to undo last {num_steps} events for player {player_id} in guild {guild_id}.")
        if not self._game_log_manager:
            print("UndoManager Error: GameLogManager not available.")
            return False

        # Assuming get_logs_by_guild fetches logs in descending order (newest first)
        # and player_id_filter works as intended.
        # If player_id_filter is not available, this would need to fetch more broadly
        # and then filter locally, which is less efficient.
        logs = await self._game_log_manager.get_logs_by_guild(
            guild_id,
            limit=num_steps,
            player_id_filter=player_id
        )

        if not logs:
            print(f"UndoManager: No logs found for player {player_id} in guild {guild_id} to undo.")
            return True # Nothing to undo

        for log_entry in logs: # Logs are newest first
            log_id = log_entry.get('id')
            if not log_id:
                print(f"UndoManager Warning: Log entry missing ID. Data: {log_entry}")
                continue # Skip this log entry

            print(f"UndoManager: Preparing to revert log entry ID: {log_id}")
            revert_ok = await self._process_log_entry_for_revert(guild_id, log_entry)

            if revert_ok:
                # Assuming delete_log_entry method will be added to GameLogManager
                if hasattr(self._game_log_manager, 'delete_log_entry'):
                    delete_ok = await self._game_log_manager.delete_log_entry(log_id)
                    if not delete_ok:
                        print(f"UndoManager Warning: Log entry {log_id} successfully reverted but could not be deleted.")
                else:
                    print(f"UndoManager Warning: GameLogManager does not have delete_log_entry method. Log entry {log_id} not deleted after revert.")
            else:
                print(f"UndoManager Error: Failed to revert log entry ID: {log_id}. Stopping further undo operations for this request.")
                return False # Stop further undo operations if one fails

        print(f"UndoManager: Successfully processed undo for {len(logs)} events for player {player_id}.")
        return True

    async def undo_last_party_event(self, guild_id: str, party_id: str, num_steps: int = 1) -> bool:
        """Undoes the last 'num_steps' events for an entire party."""
        print(f"UndoManager: Attempting to undo last {num_steps} events for party {party_id} in guild {guild_id}.")
        if not self._game_log_manager:
            print("UndoManager Error: GameLogManager not available for party event undo.")
            return False
        if not self._party_manager: # Assuming PartyManager might be needed to confirm members if logs are player-specific
            print("UndoManager Error: PartyManager not available for party event undo (needed for member context).")
            return False

        # Fetch logs related to the party.
        # This assumes get_logs_by_guild can filter by party_id or we fetch broadly and filter.
        # For now, assume party_id_filter works. Logs are newest first.
        logs = await self._game_log_manager.get_logs_by_guild(
            guild_id,
            limit=num_steps, # This might need adjustment if logs are not strictly party-wide
            party_id_filter=party_id
        )

        if not logs:
            print(f"UndoManager: No logs found for party {party_id} in guild {guild_id} to undo.")
            return True

        for log_entry in logs: # Logs are newest first
            log_id = log_entry.get('id')
            if not log_id:
                print(f"UndoManager Warning: Log entry missing ID during party undo. Data: {log_entry}")
                continue

            # player_id_from_log = log_entry.get('player_id') # Could be used for more complex party logic
            log_party_id_field = log_entry.get('party_id')

            # Ensure the log is relevant to the target party.
            # If party_id_filter is perfect, this check is redundant but safe.
            if log_party_id_field == party_id:
                print(f"UndoManager: Preparing to revert party-related log entry ID: {log_id}")
                revert_ok = await self._process_log_entry_for_revert(guild_id, log_entry)

                if revert_ok:
                    if hasattr(self._game_log_manager, 'delete_log_entry'):
                        delete_ok = await self._game_log_manager.delete_log_entry(log_id)
                        if not delete_ok:
                            print(f"UndoManager Warning: Log entry {log_id} (party {party_id}) successfully reverted but could not be deleted.")
                    else:
                        print(f"UndoManager Warning: GameLogManager does not have delete_log_entry method. Log entry {log_id} not deleted after party revert.")
                else:
                    print(f"UndoManager Error: Failed to revert log entry ID: {log_id} (party {party_id}). Stopping further undo operations for this party request.")
                    return False
            else:
                # This case implies the party_id_filter might not be exact or the log is player-specific
                # but still somehow fetched under a party context.
                # For simplicity, if party_id_filter is trusted, this 'else' might not be hit often.
                # If it is hit, it means a log not directly tagged with this party_id was fetched.
                # We might need to check if log_entry.player_id was part of party_id at that time.
                # For now, strict matching on log_entry.party_id.
                print(f"UndoManager Debug: Log entry {log_id} skipped during party undo; its party_id '{log_party_id_field}' does not match target '{party_id}'.")

        print(f"UndoManager: Successfully processed undo for {len(logs)} relevant events for party {party_id}.")
        return True

    async def undo_specific_log_entry(self, guild_id: str, log_id_to_revert: str) -> bool:
        """
        Fetches a specific log entry by its ID and processes it for revert.
        If successful, the log entry is deleted.
        """
        print(f"UndoManager: Attempting to undo specific log entry ID: {log_id_to_revert} in guild {guild_id}.")
        if not self._game_log_manager:
            print("UndoManager Error: GameLogManager not available.")
            return False

        # GameLogManager needs a method to fetch a single log by its ID.
        # Assuming get_log_by_id(log_id, guild_id) exists or can be added.
        log_entry: Optional[Dict[str, Any]] = await self._game_log_manager.get_log_by_id(log_id_to_revert, guild_id)

        if not log_entry:
            print(f"UndoManager Error: Log entry ID {log_id_to_revert} not found in guild {guild_id}.")
            return False

        revert_ok = await self._process_log_entry_for_revert(guild_id, log_entry)

        if revert_ok:
            if hasattr(self._game_log_manager, 'delete_log_entry'):
                delete_ok = await self._game_log_manager.delete_log_entry(log_id_to_revert)
                if not delete_ok:
                    print(f"UndoManager Warning: Log entry {log_id_to_revert} successfully reverted but could not be deleted.")
                else:
                    print(f"UndoManager: Log entry {log_id_to_revert} successfully reverted and deleted.")
            else:
                print(f"UndoManager Warning: GameLogManager does not have delete_log_entry method. Log entry {log_id_to_revert} not deleted after revert.")
            return True
        else:
            print(f"UndoManager Error: Failed to revert log entry ID: {log_id_to_revert}.")
            return False

    async def undo_to_log_entry(self, guild_id: str, target_log_id: str, player_or_party_id: Optional[str] = None, entity_type: Optional[str] = None) -> bool:
        """
        Undoes events sequentially until the state *after* target_log_id is reached.
        If player_or_party_id and entity_type ('player' or 'party') are provided,
        it will only consider logs related to that entity when determining the sequence.
        Otherwise, it considers all logs for the guild (potentially more dangerous).
        """
        print(f"UndoManager: Attempting to undo events up to (but not including actions that led to) log entry {target_log_id} in guild {guild_id}.")
        if not self._game_log_manager:
            print("UndoManager Error: GameLogManager not available.")
            return False

        # Fetch all logs for the guild. A very large limit is used as a placeholder.
        # In a real scenario, pagination or a more targeted fetch would be better.
        # Assumes logs are returned newest first.
        all_guild_logs = await self._game_log_manager.get_logs_by_guild(guild_id, limit=10000)

        if not all_guild_logs:
            print(f"UndoManager: No logs found for guild {guild_id}.")
            return False

        target_log_index = -1
        for i, log_entry_iter in enumerate(all_guild_logs): # Renamed log_entry to avoid conflict
            if log_entry_iter.get('id') == target_log_id:
                target_log_index = i
                break

        if target_log_index == -1:
            print(f"UndoManager Error: Target log ID {target_log_id} not found in guild {guild_id} logs.")
            return False

        # Logs to revert are from the newest (index 0) up to, but not including, the target log.
        # So, if target_log_id is at index `target_log_index`, we revert logs from index 0 to `target_log_index - 1`.
        # The slice `all_guild_logs[0:target_log_index]` correctly captures these logs.
        logs_to_process_potentially = all_guild_logs[0:target_log_index]

        # Further filter if player_or_party_id and entity_type are provided
        if player_or_party_id and entity_type:
            filtered_logs_to_process = []
            for log_entry_filter in logs_to_process_potentially: # Renamed log_entry
                if entity_type == 'player' and log_entry_filter.get('player_id') == player_or_party_id:
                    filtered_logs_to_process.append(log_entry_filter)
                elif entity_type == 'party' and log_entry_filter.get('party_id') == player_or_party_id:
                    filtered_logs_to_process.append(log_entry_filter)
            logs_to_revert = filtered_logs_to_process
            print(f"UndoManager: Filtered logs for {entity_type} {player_or_party_id}. Found {len(logs_to_revert)} logs to revert before target {target_log_id}.")
        else:
            logs_to_revert = logs_to_process_potentially
            print(f"UndoManager: Found {len(logs_to_revert)} logs to revert before target {target_log_id} (no specific entity filter).")

        if not logs_to_revert:
            print(f"UndoManager: No logs to revert before target {target_log_id} after filtering. State is considered current.")
            return True

        # Iterate through the selected logs. Since they are already newest first,
        # processing them in this order effectively undoes them chronologically backward.
        for log_entry_to_revert in logs_to_revert:
            log_id_to_revert = log_entry_to_revert.get('id')
            if not log_id_to_revert:
                print(f"UndoManager Warning: Log entry missing ID during undo_to_log_entry. Data: {log_entry_to_revert}")
                continue

            print(f"UndoManager (undo_to_log_entry): Preparing to revert log entry ID: {log_id_to_revert}")
            revert_ok = await self._process_log_entry_for_revert(guild_id, log_entry_to_revert)

            if revert_ok:
                if hasattr(self._game_log_manager, 'delete_log_entry'):
                    delete_ok = await self._game_log_manager.delete_log_entry(log_id_to_revert)
                    if not delete_ok:
                        print(f"UndoManager Warning: Log entry {log_id_to_revert} successfully reverted but could not be deleted (during undo_to_log_entry).")
                else:
                    print(f"UndoManager Warning: GameLogManager does not have delete_log_entry method. Log entry {log_id_to_revert} not deleted (during undo_to_log_entry).")
            else:
                print(f"UndoManager Error: Failed to revert log entry ID: {log_id_to_revert} (during undo_to_log_entry). Stopping further undo operations.")
                return False

        print(f"UndoManager: Successfully reverted {len(logs_to_revert)} log entries up to target {target_log_id}.")
        return True

    async def _process_log_entry_for_revert(self, guild_id: str, log_entry: Dict[str, Any]) -> bool:
        """Internal method to parse a single log entry and call relevant revert methods."""
        event_type = log_entry.get('event_type')
        # Details might be a dict if already parsed, or JSON string if fetched directly from DB
        details_raw = log_entry.get('details', log_entry.get('metadata')) # Check both common keys

        player_id = log_entry.get('player_id', log_entry.get('actor_id')) # Check common keys for player context
        party_id = log_entry.get('party_id') # Might be None

        details: Optional[Dict[str, Any]] = None

        if isinstance(details_raw, dict):
            details = details_raw
        elif isinstance(details_raw, str):
            try:
                details = json.loads(details_raw)
            except json.JSONDecodeError:
                print(f"UndoManager Error: Failed to parse JSON details for log entry {log_entry.get('id')}. Details: {details_raw}")
                return False
        else:
            print(f"UndoManager Warning: Log entry {log_entry.get('id')} has no details or details are of unexpected type. Cannot revert event type {event_type}.")
            return False

        if not details: # Should be caught by else above, but as a safeguard
            print(f"UndoManager Warning: Log entry {log_entry.get('id')} resulted in empty details after parsing. Cannot revert event type {event_type}.")
            return False


        print(f"UndoManager: Processing revert for log {log_entry.get('id')}, event type {event_type}...")
        revert_successful = False

        # --- Character-related events ---
        if event_type == "PLAYER_ACTION_COMPLETED":
            # The 'details' for PLAYER_ACTION_COMPLETED should be the 'completed_action_details'
            # which is the original action_data. The *undo* data should be explicitly logged by the action.
            # For example, if moving from A to B, 'PLAYER_ACTION_COMPLETED' for move to B
            # should have logged 'old_location_id': 'A'.

            action_specific_details = details.get("completed_action_details", details) # Use 'details' if 'completed_action_details' isn't there

            # Example: Reverting a location change that was logged by the MOVE action
            if action_specific_details.get("type") == "move" or action_specific_details.get("action_type") == "MOVE": # Check both 'type' and 'action_type'
                old_loc_id = action_specific_details.get("revert_data", {}).get("old_location_id")
                if self._character_manager and player_id and old_loc_id is not None:
                    revert_successful = await self._character_manager.revert_location_change(
                        guild_id, player_id, old_loc_id
                    )
                elif not self._character_manager: print("UndoManager Error: CharacterManager not available for MOVE revert.")
                elif not player_id: print("UndoManager Error: player_id missing for MOVE revert.")
                elif old_loc_id is None: print(f"UndoManager Error: 'old_location_id' not found in revert_data for MOVE action in log {log_entry.get('id')}.")


            # Example: Reverting a direct HP change (e.g. using a potion)
            # This assumes the "use_item" action that resulted in HP_CHANGE logged the "revert_data"
            elif action_specific_details.get("type") == "use_item" and action_specific_details.get("revert_data", {}).get("hp_changed"):
                revert_data = action_specific_details.get("revert_data", {})
                old_hp = revert_data.get("old_hp")
                old_is_alive = revert_data.get("old_is_alive")
                if self._character_manager and player_id and old_hp is not None and old_is_alive is not None:
                    revert_successful = await self._character_manager.revert_hp_change(
                        guild_id, player_id, old_hp, old_is_alive
                    )
                elif not self._character_manager: print("UndoManager Error: CharacterManager not available for HP_CHANGE revert.")
                # Add more specific checks for missing data if needed

            # Generic stat changes logged within PLAYER_ACTION_COMPLETED (e.g. skill use outcome)
            elif action_specific_details.get("revert_data", {}).get("stat_changes"):
                if self._character_manager and player_id:
                    revert_successful = await self._character_manager.revert_stat_changes(
                        guild_id, player_id, action_specific_details["revert_data"]["stat_changes"]
                    )
                elif not self._character_manager: print("UndoManager Error: CharacterManager not available for stat_changes revert.")

            # Generic inventory changes logged within PLAYER_ACTION_COMPLETED (e.g. item pickup/drop)
            elif action_specific_details.get("revert_data", {}).get("inventory_changes"):
                 if self._character_manager and player_id:
                     revert_successful = await self._character_manager.revert_inventory_changes(
                        guild_id, player_id, action_specific_details["revert_data"]["inventory_changes"]
                    )
                 elif not self._character_manager: print("UndoManager Error: CharacterManager not available for inventory_changes revert.")

            # Generic status effect changes logged within PLAYER_ACTION_COMPLETED
            elif action_specific_details.get("revert_data", {}).get("status_effect_change"):
                if self._character_manager and player_id:
                    change_info = action_specific_details["revert_data"]["status_effect_change"]
                    revert_successful = await self._character_manager.revert_status_effect_change(
                        guild_id, player_id,
                        change_info.get("action_taken"),
                        change_info.get("status_effect_id"),
                        change_info.get("full_status_effect_data")
                    )
                elif not self._character_manager: print("UndoManager Error: CharacterManager not available for status_effect_change revert.")

            else:
                action_type_for_log = action_specific_details.get("type", action_specific_details.get("action_type", "UNKNOWN"))
                print(f"UndoManager Warning: No specific revert logic for PLAYER_ACTION_COMPLETED subtype '{action_type_for_log}' in log {log_entry.get('id')}. Check 'revert_data' structure.")


        elif event_type == "ENTITY_DEATH": # From RuleEngine usually
            # 'details' here should contain info logged by RuleEngine.process_entity_death
            deceased_entity_id = details.get("deceased_entity_id", details.get("id")) # 'id' might be from related_entities[0]
            deceased_entity_type = details.get("deceased_entity_type", details.get("type"))
            previous_hp = details.get("revert_data", {}).get("previous_hp")
            previous_is_alive = details.get("revert_data", {}).get("previous_is_alive_status")

            if self._character_manager and deceased_entity_id and deceased_entity_type == "Player" and previous_hp is not None and previous_is_alive is not None:
                revert_successful = await self._character_manager.revert_hp_change(
                    guild_id, deceased_entity_id, previous_hp, previous_is_alive
                )
            # TODO: Add NPCManager.revert_death if applicable
            # elif self._npc_manager and deceased_entity_id and deceased_entity_type == "NPC" ...
            elif not self._character_manager and deceased_entity_type == "Player": print("UndoManager Error: CharacterManager not available for ENTITY_DEATH (Player) revert.")
            else: print(f"UndoManager Warning: Could not revert ENTITY_DEATH for {deceased_entity_type} {deceased_entity_id}. Missing data or manager. Details: {details}")
            # TODO: Also revert dropped items, lost status effects if logged for ENTITY_DEATH revert_data

        # --- Item-related events (direct item manager events) ---
        elif event_type == "ITEM_CREATED":
            item_id_created = details.get("item_id")
            if self._item_manager and item_id_created:
                revert_successful = await self._item_manager.revert_item_creation(
                    guild_id, item_id_created
                )
            elif not self._item_manager: print("UndoManager Error: ItemManager not available for ITEM_CREATED revert.")
            else: print(f"UndoManager Error: Missing 'item_id' in details for ITEM_CREATED. Log ID: {log_entry.get('id')}")

        elif event_type == "ITEM_DELETED":
            original_item_data = details.get("revert_data", {}).get("original_item_data")
            if self._item_manager and original_item_data:
                revert_successful = await self._item_manager.revert_item_deletion(
                    guild_id, original_item_data
                )
            elif not self._item_manager: print("UndoManager Error: ItemManager not available for ITEM_DELETED revert.")
            else: print(f"UndoManager Error: Missing 'original_item_data' in revert_data for ITEM_DELETED. Log ID: {log_entry.get('id')}")

        elif event_type == "ITEM_UPDATED":
            item_id_updated = details.get("item_id")
            old_field_values = details.get("revert_data", {}).get("old_field_values")
            if self._item_manager and item_id_updated and old_field_values:
                revert_successful = await self._item_manager.revert_item_update(
                    guild_id, item_id_updated, old_field_values
                )
            elif not self._item_manager: print("UndoManager Error: ItemManager not available for ITEM_UPDATED revert.")
            else: print(f"UndoManager Error: Missing 'item_id' or 'old_field_values' in revert_data for ITEM_UPDATED. Log ID: {log_entry.get('id')}")

        # --- Quest-related events ---
        elif event_type == "QUEST_STARTED":
            quest_id_started = details.get("quest_id")
            # player_id for quests usually comes from the log_entry directly
            if self._quest_manager and player_id and quest_id_started:
                revert_successful = await self._quest_manager.revert_quest_start(
                    guild_id, player_id, quest_id_started
                )
            elif not self._quest_manager: print("UndoManager Error: QuestManager not available for QUEST_STARTED revert.")
            else: print(f"UndoManager Error: Missing player_id or quest_id for QUEST_STARTED. Log ID: {log_entry.get('id')}")

        elif event_type == "QUEST_STATUS_CHANGED": # For completed/failed
            quest_id_status_changed = details.get("quest_id")
            old_status = details.get("revert_data", {}).get("old_status")
            old_quest_data = details.get("revert_data", {}).get("old_quest_data")
            if self._quest_manager and player_id and quest_id_status_changed and old_status and old_quest_data:
                revert_successful = await self._quest_manager.revert_quest_status_change(
                    guild_id, player_id, quest_id_status_changed, old_status, old_quest_data
                )
            elif not self._quest_manager: print("UndoManager Error: QuestManager not available for QUEST_STATUS_CHANGED revert.")
            else: print(f"UndoManager Error: Missing data for QUEST_STATUS_CHANGED revert (player_id, quest_id, old_status, or old_quest_data). Log ID: {log_entry.get('id')}")

        elif event_type == "QUEST_PROGRESS_UPDATED":
            quest_id_progress = details.get("quest_id")
            objective_id = details.get("objective_id")
            old_progress = details.get("revert_data", {}).get("old_progress")
            if self._quest_manager and player_id and quest_id_progress and objective_id and old_progress is not None:
                revert_successful = await self._quest_manager.revert_quest_progress_update(
                    guild_id, player_id, quest_id_progress, objective_id, old_progress
                )
            elif not self._quest_manager: print("UndoManager Error: QuestManager not available for QUEST_PROGRESS_UPDATED revert.")
            else: print(f"UndoManager Error: Missing data for QUEST_PROGRESS_UPDATED revert. Log ID: {log_entry.get('id')}")

        # --- GM Actions ---
        elif event_type == "GM_ACTION_DELETE_CHARACTER":
            # Reverting character deletion is complex. Requires full character data to be logged.
            # CharacterManager would need a `recreate_character(guild_id, char_data)` method.
            char_id_deleted = details.get("character_id")
            original_char_data = details.get("revert_data", {}).get("original_character_data")
            print(f"UndoManager Info: GM_ACTION_DELETE_CHARACTER for char ID {char_id_deleted}. Full character recreation from data is needed.")
            if self._character_manager and original_char_data:
                # Placeholder for actual recreation method
                # revert_successful = await self._character_manager.recreate_character_from_data(guild_id, original_char_data)
                print(f"UndoManager Warning: Reverting GM_ACTION_DELETE_CHARACTER (char ID: {char_id_deleted}) is not fully implemented. Character was NOT restored.")
                revert_successful = True # Allow other undos to proceed, but this one is a no-op with warning.
            elif not self._character_manager: print("UndoManager Error: CharacterManager not available for GM_ACTION_DELETE_CHARACTER revert.")
            else: print(f"UndoManager Error: Missing 'original_character_data' for GM_ACTION_DELETE_CHARACTER. Log ID: {log_entry.get('id')}")


        # TODO: Add more event_type handlers here based on the defined structures from Step 1
        # and the revert methods implemented in Step 2.
        # Example: Party changes, NPC state changes, Location state changes, etc.

        else:
            print(f"UndoManager Warning: No revert logic defined for event type '{event_type}'. Log ID: {log_entry.get('id')}")
            return False # Cannot revert unknown event types

        if revert_successful:
            print(f"UndoManager: Successfully processed revert for log {log_entry.get('id')}, event type {event_type}.")
            # TODO: Mark log as undone or delete it? This is a critical decision.
            # For now, we assume the calling method handles log management after successful revert.
        else:
            print(f"UndoManager Error: Failed to process revert for log {log_entry.get('id')}, event type {event_type}.")

        # --- CharacterManager Events ---
        elif event_type == "PLAYER_XP_CHANGED":
            if self._character_manager and player_id:
                revert_data = details.get('revert_data', {})
                old_xp = revert_data.get('old_xp')
                old_level = revert_data.get('old_level')
                old_unspent_xp = revert_data.get('old_unspent_xp')
                if old_xp is not None and old_level is not None and old_unspent_xp is not None:
                    revert_successful = await self._character_manager.revert_xp_change(
                        guild_id, player_id, old_xp, old_level, old_unspent_xp
                    )
                else:
                    print(f"UndoManager Error: Missing data for PLAYER_XP_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._character_manager: print("UndoManager Error: CharacterManager not available for PLAYER_XP_CHANGED.")
            else: print(f"UndoManager Error: player_id missing for PLAYER_XP_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "PLAYER_GOLD_CHANGED":
            if self._character_manager and player_id:
                revert_data = details.get('revert_data', {})
                old_gold = revert_data.get('old_gold')
                if old_gold is not None:
                    revert_successful = await self._character_manager.revert_gold_change(
                        guild_id, player_id, old_gold
                    )
                else:
                    print(f"UndoManager Error: Missing data for PLAYER_GOLD_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._character_manager: print("UndoManager Error: CharacterManager not available for PLAYER_GOLD_CHANGED.")
            else: print(f"UndoManager Error: player_id missing for PLAYER_GOLD_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "PLAYER_ACTION_QUEUE_CHANGED":
            if self._character_manager and player_id:
                revert_data = details.get('revert_data', {})
                old_action_queue_json = revert_data.get('old_action_queue_json')
                if old_action_queue_json is not None: # Should be a JSON string
                    revert_successful = await self._character_manager.revert_action_queue_change(
                        guild_id, player_id, old_action_queue_json
                    )
                else:
                    print(f"UndoManager Error: Missing data for PLAYER_ACTION_QUEUE_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._character_manager: print("UndoManager Error: CharacterManager not available for PLAYER_ACTION_QUEUE_CHANGED.")
            else: print(f"UndoManager Error: player_id missing for PLAYER_ACTION_QUEUE_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "PLAYER_COLLECTED_ACTIONS_CHANGED":
            if self._character_manager and player_id:
                revert_data = details.get('revert_data', {})
                old_collected_actions_json = revert_data.get('old_collected_actions_json')
                # This can be None if actions were cleared, so allow None
                if old_collected_actions_json is not None or ('old_collected_actions_json' in revert_data):
                    revert_successful = await self._character_manager.revert_collected_actions_change(
                        guild_id, player_id, old_collected_actions_json
                    )
                else:
                    print(f"UndoManager Error: Missing 'old_collected_actions_json' key in revert_data for PLAYER_COLLECTED_ACTIONS_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._character_manager: print("UndoManager Error: CharacterManager not available for PLAYER_COLLECTED_ACTIONS_CHANGED.")
            else: print(f"UndoManager Error: player_id missing for PLAYER_COLLECTED_ACTIONS_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "PLAYER_CREATED":
            # player_id from log entry is the character_id to delete
            if self._character_manager and player_id:
                revert_successful = await self._character_manager.revert_character_creation(guild_id, player_id)
            elif not self._character_manager: print("UndoManager Error: CharacterManager not available for PLAYER_CREATED revert.")
            else: print(f"UndoManager Error: player_id (for character_id) missing for PLAYER_CREATED. Log ID: {log_entry.get('id')}")

        elif event_type == "GM_CHARACTER_RECREATED":
            character_id_recreated = details.get('character_id')
            if self._character_manager and character_id_recreated:
                revert_successful = await self._character_manager.revert_character_creation(guild_id, character_id_recreated)
            elif not self._character_manager: print("UndoManager Error: CharacterManager not available for GM_CHARACTER_RECREATED revert.")
            else: print(f"UndoManager Error: Missing 'character_id' for GM_CHARACTER_RECREATED. Log ID: {log_entry.get('id')}")

        # --- NPCManager Events ---
        elif event_type == "NPC_SPAWNED":
            npc_id_spawned = details.get('npc_id')
            if self._npc_manager and npc_id_spawned:
                revert_successful = await self._npc_manager.revert_npc_spawn(guild_id, npc_id_spawned)
            elif not self._npc_manager: print("UndoManager Error: NpcManager not available for NPC_SPAWNED revert.")
            else: print(f"UndoManager Error: Missing 'npc_id' for NPC_SPAWNED. Log ID: {log_entry.get('id')}")

        elif event_type == "NPC_LOCATION_CHANGED":
            npc_id_moved = details.get('npc_id')
            revert_data = details.get('revert_data', {})
            old_location_id = revert_data.get('old_location_id') # Can be None
            if self._npc_manager and npc_id_moved:
                # old_location_id can be None, revert_npc_location_change should handle it
                if 'old_location_id' in revert_data: # Check key existence for None case
                    revert_successful = await self._npc_manager.revert_npc_location_change(
                        guild_id, npc_id_moved, old_location_id
                    )
                else:
                    print(f"UndoManager Error: Missing 'old_location_id' key in revert_data for NPC_LOCATION_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._npc_manager: print("UndoManager Error: NpcManager not available for NPC_LOCATION_CHANGED.")
            else: print(f"UndoManager Error: Missing 'npc_id' for NPC_LOCATION_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "NPC_HP_CHANGED":
            npc_id_hp_changed = details.get('npc_id')
            revert_data = details.get('revert_data', {})
            old_hp = revert_data.get('old_hp')
            old_is_alive = revert_data.get('old_is_alive')
            if self._npc_manager and npc_id_hp_changed and old_hp is not None and old_is_alive is not None:
                revert_successful = await self._npc_manager.revert_npc_hp_change(
                    guild_id, npc_id_hp_changed, old_hp, old_is_alive
                )
            elif not self._npc_manager: print("UndoManager Error: NpcManager not available for NPC_HP_CHANGED.")
            else: print(f"UndoManager Error: Missing data for NPC_HP_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "NPC_STATS_UPDATED":
            npc_id_stats_updated = details.get('npc_id')
            revert_data = details.get('revert_data', {})
            stat_changes = revert_data.get('stat_changes')
            if self._npc_manager and npc_id_stats_updated and isinstance(stat_changes, list):
                revert_successful = await self._npc_manager.revert_npc_stat_changes(
                    guild_id, npc_id_stats_updated, stat_changes
                )
            elif not self._npc_manager: print("UndoManager Error: NpcManager not available for NPC_STATS_UPDATED.")
            else: print(f"UndoManager Error: Missing or invalid data for NPC_STATS_UPDATED (npc_id, stat_changes list). Log ID: {log_entry.get('id')}")

        elif event_type == "NPC_INVENTORY_CHANGED":
            npc_id_inv_changed = details.get('npc_id')
            revert_data = details.get('revert_data', {})
            inventory_changes = revert_data.get('inventory_changes')
            if self._npc_manager and npc_id_inv_changed and isinstance(inventory_changes, list):
                revert_successful = await self._npc_manager.revert_npc_inventory_changes(
                    guild_id, npc_id_inv_changed, inventory_changes
                )
            elif not self._npc_manager: print("UndoManager Error: NpcManager not available for NPC_INVENTORY_CHANGED.")
            else: print(f"UndoManager Error: Missing or invalid data for NPC_INVENTORY_CHANGED (npc_id, inventory_changes list). Log ID: {log_entry.get('id')}")

        elif event_type == "NPC_PARTY_CHANGED":
            npc_id_party_changed = details.get('npc_id')
            revert_data = details.get('revert_data', {})
            old_party_id = revert_data.get('old_party_id') # Can be None
            if self._npc_manager and npc_id_party_changed:
                if 'old_party_id' in revert_data: # Check key existence for None case
                    revert_successful = await self._npc_manager.revert_npc_party_change(
                        guild_id, npc_id_party_changed, old_party_id
                    )
                else:
                    print(f"UndoManager Error: Missing 'old_party_id' key in revert_data for NPC_PARTY_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._npc_manager: print("UndoManager Error: NpcManager not available for NPC_PARTY_CHANGED.")
            else: print(f"UndoManager Error: Missing 'npc_id' for NPC_PARTY_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "NPC_STATE_VARIABLES_CHANGED":
            npc_id_state_changed = details.get('npc_id')
            revert_data = details.get('revert_data', {})
            old_state_variables_json = revert_data.get('old_state_variables_json')
            if self._npc_manager and npc_id_state_changed and old_state_variables_json is not None:
                revert_successful = await self._npc_manager.revert_npc_state_variables_change(
                    guild_id, npc_id_state_changed, old_state_variables_json
                )
            elif not self._npc_manager: print("UndoManager Error: NpcManager not available for NPC_STATE_VARIABLES_CHANGED.")
            else: print(f"UndoManager Error: Missing data for NPC_STATE_VARIABLES_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "GM_NPC_RECREATED":
            npc_id_recreated = details.get('npc_id')
            if self._npc_manager and npc_id_recreated:
                revert_successful = await self._npc_manager.revert_npc_spawn(guild_id, npc_id_recreated)
            elif not self._npc_manager: print("UndoManager Error: NpcManager not available for GM_NPC_RECREATED revert.")
            else: print(f"UndoManager Error: Missing 'npc_id' for GM_NPC_RECREATED. Log ID: {log_entry.get('id')}")

        # --- ItemManager Events (already has some, adding new ones if any) ---
        elif event_type == "ITEM_OWNER_CHANGED":
            item_id_owner_changed = details.get('item_id')
            revert_data = details.get('revert_data', {})
            old_owner_id = revert_data.get('old_owner_id') # Can be None
            old_owner_type = revert_data.get('old_owner_type') # Can be None
            old_loc_id_if_unowned = revert_data.get('old_location_id_if_unowned') # Can be None
            if self._item_manager and item_id_owner_changed:
                # Check key existence for None cases
                if 'old_owner_id' in revert_data and 'old_owner_type' in revert_data and 'old_location_id_if_unowned' in revert_data:
                    revert_successful = await self._item_manager.revert_item_owner_change(
                        guild_id, item_id_owner_changed, old_owner_id, old_owner_type, old_loc_id_if_unowned
                    )
                else:
                    print(f"UndoManager Error: Missing one or more keys in revert_data for ITEM_OWNER_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._item_manager: print("UndoManager Error: ItemManager not available for ITEM_OWNER_CHANGED.")
            else: print(f"UndoManager Error: Missing 'item_id' for ITEM_OWNER_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "ITEM_QUANTITY_CHANGED":
            item_id_qty_changed = details.get('item_id')
            revert_data = details.get('revert_data', {})
            old_quantity = revert_data.get('old_quantity')
            if self._item_manager and item_id_qty_changed and old_quantity is not None:
                revert_successful = await self._item_manager.revert_item_quantity_change(
                    guild_id, item_id_qty_changed, old_quantity
                )
            elif not self._item_manager: print("UndoManager Error: ItemManager not available for ITEM_QUANTITY_CHANGED.")
            else: print(f"UndoManager Error: Missing data for ITEM_QUANTITY_CHANGED. Log ID: {log_entry.get('id')}")

        # --- LocationManager Events ---
        elif event_type == "LOCATION_STATE_VARIABLE_CHANGED":
            location_id_state_var_changed = details.get('location_id', log_entry.get('location_id'))
            variable_name = details.get('variable_name')
            revert_data = details.get('revert_data', {})
            old_value = revert_data.get('old_value') # Can be any type, including None
            if self._location_manager and location_id_state_var_changed and variable_name is not None:
                if 'old_value' in revert_data: # Check key existence for None case
                    revert_successful = await self._location_manager.revert_location_state_variable_change(
                        guild_id, location_id_state_var_changed, variable_name, old_value
                    )
                else:
                    print(f"UndoManager Error: Missing 'old_value' key in revert_data for LOCATION_STATE_VARIABLE_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._location_manager: print("UndoManager Error: LocationManager not available for LOCATION_STATE_VARIABLE_CHANGED.")
            else: print(f"UndoManager Error: Missing data for LOCATION_STATE_VARIABLE_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "LOCATION_INVENTORY_CHANGED":
            loc_id_inv_changed = details.get('location_id', log_entry.get('location_id'))
            item_template_id = details.get('item_template_id')
            item_instance_id = details.get('item_instance_id') # Optional
            change_action = details.get('change_action') # 'added' or 'removed'
            quantity_changed = details.get('quantity_changed')
            revert_data = details.get('revert_data', {})
            original_item_data = revert_data.get('original_item_data') # Optional, crucial for 'removed' revert

            if self._location_manager and loc_id_inv_changed and item_template_id and change_action and quantity_changed is not None:
                # original_item_data is only strictly needed if change_action was 'removed'
                if change_action == "removed" and original_item_data is None:
                    print(f"UndoManager Warning: Missing 'original_item_data' for LOCATION_INVENTORY_CHANGED (removed action). Revert might be incomplete. Log ID: {log_entry.get('id')}")

                revert_successful = await self._location_manager.revert_location_inventory_change(
                    guild_id, loc_id_inv_changed, item_template_id, item_instance_id,
                    change_action, quantity_changed, original_item_data
                )
            elif not self._location_manager: print("UndoManager Error: LocationManager not available for LOCATION_INVENTORY_CHANGED.")
            else: print(f"UndoManager Error: Missing critical data for LOCATION_INVENTORY_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "LOCATION_EXIT_CHANGED":
            loc_id_exit_changed = details.get('location_id', log_entry.get('location_id'))
            exit_direction = details.get('exit_direction')
            revert_data = details.get('revert_data', {})
            old_target_location_id = revert_data.get('old_target_location_id') # Can be None
            if self._location_manager and loc_id_exit_changed and exit_direction:
                if 'old_target_location_id' in revert_data: # Check key for None case
                    revert_successful = await self._location_manager.revert_location_exit_change(
                        guild_id, loc_id_exit_changed, exit_direction, old_target_location_id
                    )
                else:
                    print(f"UndoManager Error: Missing 'old_target_location_id' key in revert_data for LOCATION_EXIT_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._location_manager: print("UndoManager Error: LocationManager not available for LOCATION_EXIT_CHANGED.")
            else: print(f"UndoManager Error: Missing data for LOCATION_EXIT_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "LOCATION_ACTIVATION_STATUS_CHANGED":
            loc_id_status_changed = details.get('location_id', log_entry.get('location_id'))
            revert_data = details.get('revert_data', {})
            old_is_active_status = revert_data.get('old_is_active_status')
            if self._location_manager and loc_id_status_changed and old_is_active_status is not None:
                revert_successful = await self._location_manager.revert_location_activation_status(
                    guild_id, loc_id_status_changed, old_is_active_status
                )
            elif not self._location_manager: print("UndoManager Error: LocationManager not available for LOCATION_ACTIVATION_STATUS_CHANGED.")
            else: print(f"UndoManager Error: Missing data for LOCATION_ACTIVATION_STATUS_CHANGED. Log ID: {log_entry.get('id')}")

        # --- PartyManager Events ---
        elif event_type == "PARTY_CREATED":
            party_id_created = details.get('party_id', party_id) # party_id from log_entry if available
            if self._party_manager and party_id_created:
                revert_successful = await self._party_manager.revert_party_creation(guild_id, party_id_created)
            elif not self._party_manager: print("UndoManager Error: PartyManager not available for PARTY_CREATED revert.")
            else: print(f"UndoManager Error: Missing 'party_id' for PARTY_CREATED. Log ID: {log_entry.get('id')}")

        elif event_type == "PARTY_MEMBER_ADDED":
            party_id_member_added_to = details.get('party_id', party_id)
            member_id_added = details.get('member_id', player_id) # player_id might be the member if logged that way
            if self._party_manager and party_id_member_added_to and member_id_added:
                revert_successful = await self._party_manager.revert_party_member_add(
                    guild_id, party_id_member_added_to, member_id_added
                )
            elif not self._party_manager: print("UndoManager Error: PartyManager not available for PARTY_MEMBER_ADDED.")
            else: print(f"UndoManager Error: Missing data for PARTY_MEMBER_ADDED. Log ID: {log_entry.get('id')}")

        elif event_type == "PARTY_MEMBER_REMOVED":
            party_id_member_removed_from = details.get('party_id', party_id)
            member_id_removed = details.get('member_id', player_id)
            revert_data = details.get('revert_data', {})
            old_leader_id_if_changed = revert_data.get('old_leader_id_if_changed') # Can be None
            if self._party_manager and party_id_member_removed_from and member_id_removed:
                # old_leader_id_if_changed existence is checked by the revert method
                revert_successful = await self._party_manager.revert_party_member_remove(
                    guild_id, party_id_member_removed_from, member_id_removed, old_leader_id_if_changed
                )
            elif not self._party_manager: print("UndoManager Error: PartyManager not available for PARTY_MEMBER_REMOVED.")
            else: print(f"UndoManager Error: Missing data for PARTY_MEMBER_REMOVED. Log ID: {log_entry.get('id')}")

        elif event_type == "PARTY_LEADER_CHANGED":
            party_id_leader_changed = details.get('party_id', party_id)
            revert_data = details.get('revert_data', {})
            old_leader_id = revert_data.get('old_leader_id')
            if self._party_manager and party_id_leader_changed and old_leader_id:
                revert_successful = await self._party_manager.revert_party_leader_change(
                    guild_id, party_id_leader_changed, old_leader_id
                )
            elif not self._party_manager: print("UndoManager Error: PartyManager not available for PARTY_LEADER_CHANGED.")
            else: print(f"UndoManager Error: Missing data for PARTY_LEADER_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "PARTY_LOCATION_CHANGED":
            party_id_loc_changed = details.get('party_id', party_id)
            revert_data = details.get('revert_data', {})
            old_location_id = revert_data.get('old_location_id') # Can be None
            if self._party_manager and party_id_loc_changed:
                if 'old_location_id' in revert_data: # Check key for None case
                    revert_successful = await self._party_manager.revert_party_location_change(
                        guild_id, party_id_loc_changed, old_location_id
                    )
                else:
                    print(f"UndoManager Error: Missing 'old_location_id' key in revert_data for PARTY_LOCATION_CHANGED. Log ID: {log_entry.get('id')}")
            elif not self._party_manager: print("UndoManager Error: PartyManager not available for PARTY_LOCATION_CHANGED.")
            else: print(f"UndoManager Error: Missing 'party_id' for PARTY_LOCATION_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "PARTY_TURN_STATUS_CHANGED":
            party_id_turn_status_changed = details.get('party_id', party_id)
            revert_data = details.get('revert_data', {})
            old_turn_status = revert_data.get('old_turn_status')
            if self._party_manager and party_id_turn_status_changed and old_turn_status:
                revert_successful = await self._party_manager.revert_party_turn_status_change(
                    guild_id, party_id_turn_status_changed, old_turn_status
                )
            elif not self._party_manager: print("UndoManager Error: PartyManager not available for PARTY_TURN_STATUS_CHANGED.")
            else: print(f"UndoManager Error: Missing data for PARTY_TURN_STATUS_CHANGED. Log ID: {log_entry.get('id')}")

        elif event_type == "GM_PARTY_RECREATED":
            party_id_recreated = details.get('party_id')
            if self._party_manager and party_id_recreated:
                revert_successful = await self._party_manager.revert_party_creation(guild_id, party_id_recreated)
            elif not self._party_manager: print("UndoManager Error: PartyManager not available for GM_PARTY_RECREATED revert.")
            else: print(f"UndoManager Error: Missing 'party_id' for GM_PARTY_RECREATED. Log ID: {log_entry.get('id')}")

        # --- End of new event types ---
        else:
            print(f"UndoManager Warning: No revert logic defined for event type '{event_type}'. Log ID: {log_entry.get('id')}")
            return False # Cannot revert unknown event types

        if revert_successful:
            print(f"UndoManager: Successfully processed revert for log {log_entry.get('id')}, event type {event_type}.")
        else:
            # More detailed error messages should be printed by the specific handlers above
            print(f"UndoManager Error: Failed to process revert for log {log_entry.get('id')}, event type {event_type}. Check previous logs for specific reason.")

        return revert_successful
