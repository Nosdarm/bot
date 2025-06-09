# bot/game/managers/game_log_manager.py
from __future__ import annotations
import json
import uuid
# import time # Not strictly needed if only using NOW()
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.services.db_service import DBService

class GameLogManager:
    # required_args_for_load and required_args_for_save seem generic, keeping them.
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]

    def __init__(self, db_service: Optional[DBService] = None, settings: Optional[Dict[str, Any]] = None):
        self._db_service = db_service
        self._settings = settings if settings is not None else {}
        # print("GameLogManager initialized.") # Consider removing for production

    async def log_event(
        self,
        guild_id: str,
        event_type: str,
        details: Dict[str, Any],
        player_id: Optional[str] = None,
        party_id: Optional[str] = None,
        location_id: Optional[str] = None,
        channel_id: Optional[str] = None, # Changed to Optional[str]
        message_key: Optional[str] = None,
        message_params: Optional[Dict[str, Any]] = None,
        involved_entities_ids: Optional[List[str]] = None
    ) -> None:
        if self._db_service is None or self._db_service.adapter is None:
            # Fallback logging if DB is not available
            log_message_fallback = f"Guild: {guild_id}, Event: {event_type}, Details: {details}"
            if message_key:
                log_message_fallback += f", MsgKey: {message_key}"
            print(f"GameLogManager: DB service not available. Log: {log_message_fallback}")
            return

        log_id = str(uuid.uuid4())

        # Prepare JSON fields
        message_params_json = json.dumps(message_params) if message_params is not None else None
        involved_entities_ids_json = json.dumps(involved_entities_ids) if involved_entities_ids is not None else None
        details_json = json.dumps(details) # details is Dict[str, Any], non-optional in this context

        sql = """
            INSERT INTO game_logs 
            (id, timestamp, guild_id, player_id, party_id, event_type,
            message_key, message_params, location_id, involved_entities_ids, details, channel_id)
            VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """
        params = (
            log_id, guild_id, player_id, party_id, event_type,
            message_key, message_params_json, location_id, involved_entities_ids_json,
            details_json, channel_id
        )

        try:
            await self._db_service.adapter.execute(sql, params)
        except Exception as e:
            print(f"GameLogManager: Failed to log event to DB for guild {guild_id}. Type: {event_type}, Error: {e}")
            # Fallback logging for detailed error context
            fallback_data = {
                "log_id": log_id, "guild_id": guild_id, "player_id": player_id, "party_id": party_id,
                "event_type": event_type, "message_key": message_key, "message_params": message_params,
                "location_id": location_id, "involved_entities_ids": involved_entities_ids,
                "details": details, "channel_id": channel_id
            }
            print(f"GameLogManager (DB-FAIL): Data: {json.dumps(fallback_data)}")

    async def get_logs_by_guild(
        self, 
        guild_id: str, 
        limit: int = 100, 
        offset: int = 0,
        event_type_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if self._db_service is None or self._db_service.adapter is None:
            print(f"GameLogManager: DB service or adapter not available. Cannot fetch logs for guild {guild_id}.")
            return []
        
        params_list: List[Any] = [guild_id]

        # Start with base query
        # Renamed log_id to id to match DB schema
        sql = """
            SELECT id, timestamp, guild_id, player_id, party_id, event_type,
                   message_key, message_params, location_id, involved_entities_ids,
                   details, channel_id
            FROM game_logs
            WHERE guild_id = $1
        """

        current_param_idx = 1 # Starts at 1 for guild_id

        if event_type_filter:
            current_param_idx += 1
            sql += f" AND event_type = ${current_param_idx}"
            params_list.append(event_type_filter)
        
        current_param_idx += 1
        sql += f" ORDER BY timestamp DESC LIMIT ${current_param_idx}"
        params_list.append(limit)

        current_param_idx += 1
        sql += f" OFFSET ${current_param_idx}"
        params_list.append(offset)

        try:
            rows = await self._db_service.adapter.fetchall(sql, tuple(params_list))
            return rows # Assuming fetchall returns List[Dict[str, Any]]
        except Exception as e:
            print(f"GameLogManager: Failed to fetch logs from DB for guild {guild_id}. Error: {e}")
            return []

    # load_state, save_state, rebuild_runtime_caches remain as they are not directly affected by log structure
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        # print(f"GameLogManager: Load state called for guild {str(guild_id)} (no specific state to load into manager).")
        pass

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        # print(f"GameLogManager: Save state called for guild {str(guild_id)} (logs are saved directly).")
        pass
            
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        # print(f"GameLogManager: Rebuild runtime caches for guild {str(guild_id)} (no runtime caches).")
        pass
