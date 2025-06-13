# bot/game/managers/game_log_manager.py
from __future__ import annotations
import json
import uuid
import logging # Added
from typing import Optional, Dict, Any, List, TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.services.relationship_event_processor import RelationshipEventProcessor

logger = logging.getLogger(__name__) # Added

class GameLogManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]

    def __init__(self,
                 db_service: Optional[DBService] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 relationship_event_processor: Optional[RelationshipEventProcessor] = None
                 ):
        self._db_service = db_service
        self._settings = settings if settings is not None else {}
        self._relationship_event_processor = relationship_event_processor
        logger.info("GameLogManager initialized.") # Changed

    async def log_event(
        self,
        guild_id: str,
        event_type: str,
        details: Dict[str, Any],
        player_id: Optional[str] = None,
        party_id: Optional[str] = None,
        location_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        message_key: Optional[str] = None,
        message_params: Optional[Dict[str, Any]] = None,
        involved_entities_ids: Optional[List[str]] = None
    ) -> None:
        if self._db_service is None or self._db_service.adapter is None:
            log_message_fallback = f"Guild: {guild_id}, Event: {event_type}, Details: {details}"
            if message_key:
                log_message_fallback += f", MsgKey: {message_key}"
            logger.error("GameLogManager: DB service not available. Log: %s", log_message_fallback) # Changed
            return

        log_id = str(uuid.uuid4())
        message_params_json = json.dumps(message_params) if message_params is not None else None
        involved_entities_ids_json = json.dumps(involved_entities_ids) if involved_entities_ids is not None else None
        details_json = json.dumps(details)

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
            logger.debug("GameLogManager: Logged event %s (type: %s) to DB for guild %s. ID: %s", event_type, message_key or 'N/A', guild_id, log_id) # Added debug log

            if self._relationship_event_processor:
                log_data_for_processor = {
                    "guild_id": guild_id, "event_type": event_type,
                    "details": details_json, "log_id": log_id, "player_id": player_id
                }
                asyncio.create_task(
                    self._relationship_event_processor.process_new_log_entry(log_data_for_processor)
                )
        except Exception as e:
            logger.error("GameLogManager: Failed to log event to DB for guild %s. Type: %s, Error: %s", guild_id, event_type, e, exc_info=True) # Changed
            fallback_data = {
                "log_id": log_id, "guild_id": guild_id, "player_id": player_id, "party_id": party_id,
                "event_type": event_type, "message_key": message_key, "message_params": message_params,
                "location_id": location_id, "involved_entities_ids": involved_entities_ids,
                "details": details, "channel_id": channel_id
            }
            logger.error("GameLogManager (DB-FAIL): Data: %s", json.dumps(fallback_data)) # Changed

    async def get_logs_by_guild(
        self, guild_id: str, limit: int = 100, offset: int = 0,
        event_type_filter: Optional[str] = None, player_id_filter: Optional[str] = None,
        party_id_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("GameLogManager: DB service or adapter not available. Cannot fetch logs for guild %s.", guild_id) # Changed
            return []
        
        params_list: List[Any] = [guild_id]
        sql = "SELECT id, timestamp, guild_id, player_id, party_id, event_type, message_key, message_params, location_id, involved_entities_ids, details, channel_id FROM game_logs WHERE guild_id = $1"
        current_param_idx = 1

        if event_type_filter:
            current_param_idx += 1; sql += f" AND event_type = ${current_param_idx}"; params_list.append(event_type_filter)
        if player_id_filter:
            current_param_idx += 1; sql += f" AND player_id = ${current_param_idx}"; params_list.append(player_id_filter)
        if party_id_filter:
            current_param_idx += 1; sql += f" AND party_id = ${current_param_idx}"; params_list.append(party_id_filter)
        
        current_param_idx += 1; sql += f" ORDER BY timestamp DESC LIMIT ${current_param_idx}"; params_list.append(limit)
        current_param_idx += 1; sql += f" OFFSET ${current_param_idx}"; params_list.append(offset)

        try:
            rows = await self._db_service.adapter.fetchall(sql, tuple(params_list))
            return rows
        except Exception as e:
            logger.error("GameLogManager: Failed to fetch logs from DB for guild %s. Error: %s", guild_id, e, exc_info=True) # Changed
            return []

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.debug("GameLogManager: Load state called for guild %s (no specific state to load into manager).", str(guild_id)) # Changed
        pass

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        logger.debug("GameLogManager: Save state called for guild %s (logs are saved directly).", str(guild_id)) # Changed
        pass
            
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.debug("GameLogManager: Rebuild runtime caches for guild %s (no runtime caches).", str(guild_id)) # Changed
        pass

    async def delete_log_entry(self, log_id: str, guild_id: str) -> bool:
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("GameLogManager: DB service or adapter not available. Cannot delete log %s for guild %s.", log_id, guild_id) # Changed
            return False

        sql = "DELETE FROM game_logs WHERE id = $1 AND guild_id = $2"
        try:
            await self._db_service.adapter.execute(sql, (log_id, guild_id))
            logger.info("GameLogManager: Attempted deletion of log %s for guild %s.", log_id, guild_id) # Changed
            return True
        except Exception as e:
            logger.error("GameLogManager: Failed to delete log %s from DB for guild %s. Error: %s", log_id, guild_id, e, exc_info=True) # Changed
            return False

    async def get_log_by_id(self, log_id: str, guild_id: str) -> Optional[Dict[str, Any]]:
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("GameLogManager: DB service or adapter not available. Cannot fetch log %s for guild %s.", log_id, guild_id) # Changed
            return None

        sql = "SELECT id, timestamp, guild_id, player_id, party_id, event_type, message_key, message_params, location_id, involved_entities_ids, details, channel_id FROM game_logs WHERE id = $1 AND guild_id = $2"
        try:
            row = await self._db_service.adapter.fetchone(sql, (log_id, guild_id))
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error("GameLogManager: Failed to fetch log %s from DB for guild %s. Error: %s", log_id, guild_id, e, exc_info=True) # Changed
            return None

    # Convenience methods for different log levels
    async def log_debug(self, message: str, guild_id: str, **kwargs: Any) -> None: # Added
        details = {'message': message, **kwargs.pop('details', {})}
        await self.log_event(guild_id, "DEBUG", details, **kwargs)

    async def log_info(self, message: str, guild_id: str, **kwargs: Any) -> None: # Added
        details = {'message': message, **kwargs.pop('details', {})}
        await self.log_event(guild_id, "INFO", details, **kwargs)

    async def log_warning(self, message: str, guild_id: str, **kwargs: Any) -> None: # Added
        details = {'message': message, **kwargs.pop('details', {})}
        await self.log_event(guild_id, "WARNING", details, **kwargs)

    async def log_error(self, message: str, guild_id: str, exc: Optional[Exception] = None, **kwargs: Any) -> None: # Added
        details = {'message': message, **kwargs.pop('details', {})}
        if exc: # Add exception info if provided
            details['exception_type'] = type(exc).__name__
            details['exception_message'] = str(exc)
            # details['traceback'] = traceback.format_exc() # Consider if full traceback is needed in DB
        await self.log_event(guild_id, "ERROR", details, **kwargs)

    async def log_critical(self, message: str, guild_id: str, exc: Optional[Exception] = None, **kwargs: Any) -> None: # Added
        details = {'message': message, **kwargs.pop('details', {})}
        if exc:
            details['exception_type'] = type(exc).__name__
            details['exception_message'] = str(exc)
        await self.log_event(guild_id, "CRITICAL", details, **kwargs)
