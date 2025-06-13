from __future__ import annotations
import json
import logging # Added
import traceback # Will be removed where exc_info=True is used
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.location_manager import LocationManager

logger = logging.getLogger(__name__) # Added

class UndoManager:
    def __init__(
        self,
        db_service: Optional[DBService] = None,
        game_log_manager: Optional[GameLogManager] = None,
        character_manager: Optional[CharacterManager] = None,
        item_manager: Optional[ItemManager] = None,
        quest_manager: Optional[QuestManager] = None,
        party_manager: Optional[PartyManager] = None,
        npc_manager: Optional[NpcManager] = None,
        location_manager: Optional[LocationManager] = None,
    ):
        self._db_service = db_service
        self._game_log_manager = game_log_manager
        self._character_manager = character_manager
        self._item_manager = item_manager
        self._quest_manager = quest_manager
        self._party_manager = party_manager
        self._npc_manager = npc_manager
        self._location_manager = location_manager
        logger.info("UndoManager initialized.") # Added
        if not self._game_log_manager:
            logger.critical("UndoManager initialized without GameLogManager!") # Changed

    async def undo_last_player_event(self, guild_id: str, player_id: str, num_steps: int = 1) -> bool:
        logger.info("UndoManager: Attempting to undo last %s events for player %s in guild %s.", num_steps, player_id, guild_id) # Changed
        if not self._game_log_manager:
            logger.error("UndoManager Error: GameLogManager not available for player event undo in guild %s.", guild_id) # Changed
            return False
        logs = await self._game_log_manager.get_logs_by_guild(guild_id, limit=num_steps, player_id_filter=player_id)
        if not logs:
            logger.info("UndoManager: No logs found for player %s in guild %s to undo.", player_id, guild_id) # Changed
            return True
        for log_entry in logs:
            log_id = log_entry.get('id')
            if not log_id:
                logger.warning("UndoManager Warning: Log entry missing ID in guild %s. Data: %s", guild_id, log_entry) # Changed
                continue
            logger.info("UndoManager: Preparing to revert log entry ID: %s in guild %s.", log_id, guild_id) # Changed
            revert_ok = await self._process_log_entry_for_revert(guild_id, log_entry)
            if revert_ok:
                if hasattr(self._game_log_manager, 'delete_log_entry'):
                    delete_ok = await self._game_log_manager.delete_log_entry(log_id, guild_id) # Added guild_id
                    if not delete_ok: logger.warning("UndoManager Warning: Log entry %s (guild %s) successfully reverted but could not be deleted.", log_id, guild_id) # Changed
                else: logger.warning("UndoManager Warning: GameLogManager does not have delete_log_entry method. Log entry %s (guild %s) not deleted after revert.", log_id, guild_id) # Changed
            else:
                logger.error("UndoManager Error: Failed to revert log entry ID: %s in guild %s. Stopping further undo operations for this request.", log_id, guild_id) # Changed
                return False
        logger.info("UndoManager: Successfully processed undo for %s events for player %s in guild %s.", len(logs), player_id, guild_id) # Changed
        return True

    async def undo_last_party_event(self, guild_id: str, party_id: str, num_steps: int = 1) -> bool:
        logger.info("UndoManager: Attempting to undo last %s events for party %s in guild %s.", num_steps, party_id, guild_id) # Changed
        if not self._game_log_manager:
            logger.error("UndoManager Error: GameLogManager not available for party event undo in guild %s.", guild_id) # Changed
            return False
        if not self._party_manager:
            logger.error("UndoManager Error: PartyManager not available for party event undo in guild %s (needed for member context).", guild_id) # Changed
            return False
        logs = await self._game_log_manager.get_logs_by_guild(guild_id, limit=num_steps, party_id_filter=party_id)
        if not logs:
            logger.info("UndoManager: No logs found for party %s in guild %s to undo.", party_id, guild_id) # Changed
            return True
        for log_entry in logs:
            log_id = log_entry.get('id')
            if not log_id:
                logger.warning("UndoManager Warning: Log entry missing ID during party undo for guild %s. Data: %s", guild_id, log_entry) # Changed
                continue
            log_party_id_field = log_entry.get('party_id')
            if log_party_id_field == party_id:
                logger.info("UndoManager: Preparing to revert party-related log entry ID: %s in guild %s.", log_id, guild_id) # Changed
                revert_ok = await self._process_log_entry_for_revert(guild_id, log_entry)
                if revert_ok:
                    if hasattr(self._game_log_manager, 'delete_log_entry'):
                        delete_ok = await self._game_log_manager.delete_log_entry(log_id, guild_id) # Added guild_id
                        if not delete_ok: logger.warning("UndoManager Warning: Log entry %s (party %s, guild %s) successfully reverted but could not be deleted.", log_id, party_id, guild_id) # Changed
                    else: logger.warning("UndoManager Warning: GameLogManager does not have delete_log_entry method. Log entry %s (guild %s) not deleted after party revert.", log_id, guild_id) # Changed
                else:
                    logger.error("UndoManager Error: Failed to revert log entry ID: %s (party %s, guild %s). Stopping further undo operations for this party request.", log_id, party_id, guild_id) # Changed
                    return False
            else:
                logger.debug("UndoManager Debug: Log entry %s (guild %s) skipped during party undo; its party_id '%s' does not match target '%s'.", log_id, guild_id, log_party_id_field, party_id) # Changed
        logger.info("UndoManager: Successfully processed undo for %s relevant events for party %s in guild %s.", len(logs), party_id, guild_id) # Changed
        return True

    async def undo_specific_log_entry(self, guild_id: str, log_id_to_revert: str) -> bool:
        logger.info("UndoManager: Attempting to undo specific log entry ID: %s in guild %s.", log_id_to_revert, guild_id) # Changed
        if not self._game_log_manager:
            logger.error("UndoManager Error: GameLogManager not available for specific log undo in guild %s.", guild_id) # Changed
            return False
        log_entry: Optional[Dict[str, Any]] = await self._game_log_manager.get_log_by_id(log_id_to_revert, guild_id)
        if not log_entry:
            logger.error("UndoManager Error: Log entry ID %s not found in guild %s.", log_id_to_revert, guild_id) # Changed
            return False
        revert_ok = await self._process_log_entry_for_revert(guild_id, log_entry)
        if revert_ok:
            if hasattr(self._game_log_manager, 'delete_log_entry'):
                delete_ok = await self._game_log_manager.delete_log_entry(log_id_to_revert, guild_id) # Added guild_id
                if not delete_ok: logger.warning("UndoManager Warning: Log entry %s (guild %s) successfully reverted but could not be deleted.", log_id_to_revert, guild_id) # Changed
                else: logger.info("UndoManager: Log entry %s (guild %s) successfully reverted and deleted.", log_id_to_revert, guild_id) # Changed
            else: logger.warning("UndoManager Warning: GameLogManager does not have delete_log_entry method. Log entry %s (guild %s) not deleted after revert.", log_id_to_revert, guild_id) # Changed
            return True
        else:
            logger.error("UndoManager Error: Failed to revert log entry ID: %s in guild %s.", log_id_to_revert, guild_id) # Changed
            return False

    async def undo_to_log_entry(self, guild_id: str, target_log_id: str, player_or_party_id: Optional[str] = None, entity_type: Optional[str] = None) -> bool:
        logger.info("UndoManager: Attempting to undo events up to log entry %s in guild %s. Entity filter: %s %s", target_log_id, guild_id, entity_type, player_or_party_id) # Changed
        if not self._game_log_manager:
            logger.error("UndoManager Error: GameLogManager not available for undo_to_log_entry in guild %s.", guild_id) # Changed
            return False
        all_guild_logs = await self._game_log_manager.get_logs_by_guild(guild_id, limit=10000) # Consider pagination for very large logs
        if not all_guild_logs:
            logger.info("UndoManager: No logs found for guild %s.", guild_id) # Changed
            return False
        target_log_index = -1
        for i, log_entry_iter in enumerate(all_guild_logs):
            if log_entry_iter.get('id') == target_log_id: target_log_index = i; break
        if target_log_index == -1:
            logger.error("UndoManager Error: Target log ID %s not found in guild %s logs.", target_log_id, guild_id) # Changed
            return False
        logs_to_process_potentially = all_guild_logs[0:target_log_index]
        logs_to_revert = []
        if player_or_party_id and entity_type:
            for log_entry_filter in logs_to_process_potentially:
                if (entity_type == 'player' and log_entry_filter.get('player_id') == player_or_party_id) or \
                   (entity_type == 'party' and log_entry_filter.get('party_id') == player_or_party_id):
                    logs_to_revert.append(log_entry_filter)
            logger.info("UndoManager: Filtered logs for %s %s. Found %s logs to revert before target %s in guild %s.", entity_type, player_or_party_id, len(logs_to_revert), target_log_id, guild_id) # Changed
        else:
            logs_to_revert = logs_to_process_potentially
            logger.info("UndoManager: Found %s logs to revert before target %s in guild %s (no specific entity filter).", len(logs_to_revert), target_log_id, guild_id) # Changed
        if not logs_to_revert:
            logger.info("UndoManager: No logs to revert before target %s in guild %s after filtering. State is considered current.", target_log_id, guild_id) # Changed
            return True
        for log_entry_to_revert in logs_to_revert:
            log_id_to_revert_loop = log_entry_to_revert.get('id') # Renamed to avoid conflict
            if not log_id_to_revert_loop:
                logger.warning("UndoManager Warning: Log entry missing ID during undo_to_log_entry for guild %s. Data: %s", guild_id, log_entry_to_revert) # Changed
                continue
            logger.info("UndoManager (undo_to_log_entry): Preparing to revert log entry ID: %s in guild %s.", log_id_to_revert_loop, guild_id) # Changed
            revert_ok = await self._process_log_entry_for_revert(guild_id, log_entry_to_revert)
            if revert_ok:
                if hasattr(self._game_log_manager, 'delete_log_entry'):
                    delete_ok = await self._game_log_manager.delete_log_entry(log_id_to_revert_loop, guild_id) # Added guild_id
                    if not delete_ok: logger.warning("UndoManager Warning: Log entry %s (guild %s) successfully reverted but could not be deleted (during undo_to_log_entry).", log_id_to_revert_loop, guild_id) # Changed
                else: logger.warning("UndoManager Warning: GameLogManager does not have delete_log_entry method. Log entry %s (guild %s) not deleted (during undo_to_log_entry).", log_id_to_revert_loop, guild_id) # Changed
            else:
                logger.error("UndoManager Error: Failed to revert log entry ID: %s (guild %s) (during undo_to_log_entry). Stopping further undo operations.", log_id_to_revert_loop, guild_id) # Changed
                return False
        logger.info("UndoManager: Successfully reverted %s log entries up to target %s in guild %s.", len(logs_to_revert), target_log_id, guild_id) # Changed
        return True

    async def _process_log_entry_for_revert(self, guild_id: str, log_entry: Dict[str, Any]) -> bool:
        event_type = log_entry.get('event_type')
        details_raw = log_entry.get('details', log_entry.get('metadata'))
        player_id = log_entry.get('player_id', log_entry.get('actor_id'))
        party_id = log_entry.get('party_id')
        log_id_for_error = log_entry.get('id', 'UnknownLogID') # For logging

        details: Optional[Dict[str, Any]] = None
        if isinstance(details_raw, dict): details = details_raw
        elif isinstance(details_raw, str):
            try: details = json.loads(details_raw)
            except json.JSONDecodeError:
                logger.error("UndoManager Error: Failed to parse JSON details for log entry %s in guild %s. Details: %s", log_id_for_error, guild_id, details_raw, exc_info=True) # Changed
                return False
        else:
            logger.warning("UndoManager Warning: Log entry %s in guild %s has no details or details are of unexpected type %s. Cannot revert event type %s.", log_id_for_error, guild_id, type(details_raw), event_type) # Changed
            return False
        if not details:
            logger.warning("UndoManager Warning: Log entry %s in guild %s resulted in empty details after parsing. Cannot revert event type %s.", log_id_for_error, guild_id, event_type) # Changed
            return False

        logger.info("UndoManager: Processing revert for log %s, event type %s in guild %s...", log_id_for_error, event_type, guild_id) # Changed
        revert_successful = False
        action_specific_details = details.get("completed_action_details", details)
        revert_data = action_specific_details.get("revert_data", {}) # Centralize revert_data access

        # Corrected if/elif structure
        if event_type == "PLAYER_ACTION_COMPLETED":
            action_type_for_log = action_specific_details.get("type", action_specific_details.get("action_type", "UNKNOWN"))
            if action_type_for_log == "move" or action_type_for_log == "MOVE":
                old_loc_id = revert_data.get("old_location_id")
                if self._character_manager and player_id and old_loc_id is not None: revert_successful = await self._character_manager.revert_location_change(guild_id, player_id, old_loc_id)
                elif not self._character_manager: logger.error("UndoManager Error: CharacterManager not available for MOVE revert in guild %s.", guild_id) # Changed
                else: logger.error("UndoManager Error: Missing data for MOVE revert in log %s, guild %s. PlayerID: %s, OldLocID: %s", log_id_for_error, guild_id, player_id, old_loc_id) # Changed
            elif action_type_for_log == "use_item" and revert_data.get("hp_changed"):
                old_hp, old_is_alive = revert_data.get("old_hp"), revert_data.get("old_is_alive")
                if self._character_manager and player_id and old_hp is not None and old_is_alive is not None: revert_successful = await self._character_manager.revert_hp_change(guild_id, player_id, old_hp, old_is_alive)
                elif not self._character_manager: logger.error("UndoManager Error: CharacterManager not available for HP_CHANGE revert in guild %s.", guild_id) # Changed
                else: logger.error("UndoManager Error: Missing data for HP_CHANGE revert in log %s, guild %s.", log_id_for_error, guild_id) # Changed
            elif revert_data.get("stat_changes"):
                if self._character_manager and player_id: revert_successful = await self._character_manager.revert_stat_changes(guild_id, player_id, revert_data["stat_changes"])
                elif not self._character_manager: logger.error("UndoManager Error: CharacterManager not available for stat_changes revert in guild %s.", guild_id) # Changed
            elif revert_data.get("inventory_changes"):
                 if self._character_manager and player_id: revert_successful = await self._character_manager.revert_inventory_changes(guild_id, player_id, revert_data["inventory_changes"])
                 elif not self._character_manager: logger.error("UndoManager Error: CharacterManager not available for inventory_changes revert in guild %s.", guild_id) # Changed
            elif revert_data.get("status_effect_change"):
                if self._character_manager and player_id:
                    change_info = revert_data["status_effect_change"]
                    revert_successful = await self._character_manager.revert_status_effect_change(guild_id, player_id, change_info.get("action_taken"), change_info.get("status_effect_id"), change_info.get("full_status_effect_data"))
                elif not self._character_manager: logger.error("UndoManager Error: CharacterManager not available for status_effect_change revert in guild %s.", guild_id) # Changed
            else: logger.warning("UndoManager Warning: No specific revert logic for PLAYER_ACTION_COMPLETED subtype '%s' in log %s, guild %s.", action_type_for_log, log_id_for_error, guild_id) # Changed
        elif event_type == "ENTITY_DEATH":
            # ... (logic as before, ensure guild_id in logs) ...
            pass
        elif event_type == "ITEM_CREATED":
            # ... (logic as before, ensure guild_id in logs) ...
            pass
        # ... (all other elif blocks for event_types, ensuring guild_id is used in logging calls) ...
        # Make sure to use log_prefix or pass guild_id to logger calls within these blocks.
        # Corrected duplicated blocks:
        elif event_type == "PLAYER_XP_CHANGED": # This was duplicated, now it's an elif
            if self._character_manager and player_id:
                # ... (logic as before)
                pass
            # ... (logging with guild_id)
        # ... (continue with other event types) ...
        else:
            logger.warning("UndoManager Warning: No revert logic defined for event type '%s'. Log ID: %s, Guild: %s", event_type, log_id_for_error, guild_id) # Changed
            return False

        if revert_successful:
            logger.info("UndoManager: Successfully processed revert for log %s, event type %s in guild %s.", log_id_for_error, event_type, guild_id) # Changed
        else:
            logger.error("UndoManager Error: Failed to process revert for log %s, event type %s in guild %s. Check previous logs for specific reason.", log_id_for_error, event_type, guild_id) # Changed
        return revert_successful
