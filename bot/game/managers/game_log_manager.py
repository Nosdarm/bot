# bot/game/managers/game_log_manager.py
from __future__ import annotations
import json
import uuid
import time
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter

class GameLogManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]

    def __init__(self, db_adapter: Optional[SqliteAdapter] = None, settings: Optional[Dict[str, Any]] = None):
        self._db_adapter = db_adapter
        self._settings = settings if settings is not None else {}
        print("GameLogManager initialized.")

    async def log_event(
        self,
        guild_id: str,
        event_type: str,
        message: str,
        related_entities: Optional[List[Dict[str, str]]] = None,
        channel_id: Optional[int] = None,
        **kwargs: Any # For additional context/data
    ) -> None:
        if not self._db_adapter:
            print(f"GameLogManager: DB adapter not available. Log for guild {guild_id} (type: {event_type}): {message}")
            return

        log_id = str(uuid.uuid4())
        timestamp = time.time()
        guild_id_str = str(guild_id)
        event_type_str = str(event_type)
        message_str = str(message)
        related_entities_json = json.dumps(related_entities) if related_entities else None
        channel_id_int = int(channel_id) if channel_id is not None else None
        context_data_json = json.dumps(kwargs) if kwargs else None

        sql = """
            INSERT INTO game_logs 
            (log_id, timestamp, guild_id, channel_id, event_type, message, related_entities, context_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (log_id, timestamp, guild_id_str, channel_id_int, event_type_str, message_str, related_entities_json, context_data_json)

        try:
            await self._db_adapter.execute(sql, params)
            # print(f"GameLogManager: Logged event {log_id} for guild {guild_id_str}.") # Can be too verbose
        except Exception as e:
            print(f"GameLogManager: Failed to log event to DB for guild {guild_id_str}. Type: {event_type_str}, Error: {e}")
            # Fallback to console if DB fails
            print(f"GameLogManager (DB-FAIL): Guild {guild_id_str}, Type: {event_type_str}, Msg: {message_str}, Entities: {related_entities_json}, Context: {context_data_json}")

    async def get_logs_by_guild(
        self, 
        guild_id: str, 
        limit: int = 100, 
        offset: int = 0,
        event_type_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if not self._db_adapter:
            print(f"GameLogManager: DB adapter not available. Cannot fetch logs for guild {guild_id}.")
            return []
        
        guild_id_str = str(guild_id)
        base_sql = "SELECT log_id, timestamp, guild_id, channel_id, event_type, message, related_entities, context_data FROM game_logs WHERE guild_id = ?"
        params: List[Any] = [guild_id_str]

        if event_type_filter:
            base_sql += " AND event_type = ?"
            params.append(str(event_type_filter))
        
        base_sql += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])

        try:
            rows = await self._db_adapter.fetchall(base_sql, tuple(params))
            return [dict(row) for row in rows] # Convert Row objects to dicts
        except Exception as e:
            print(f"GameLogManager: Failed to fetch logs from DB for guild {guild_id_str}. Error: {e}")
            return []

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        print(f"GameLogManager: Load state called for guild {str(guild_id)} (no specific state to load into manager).")
        pass

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        print(f"GameLogManager: Save state called for guild {str(guild_id)} (logs are saved directly).")
        pass
            
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        print(f"GameLogManager: Rebuild runtime caches for guild {str(guild_id)} (no runtime caches).")
        pass
