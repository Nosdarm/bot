# bot/game/managers/game_log_manager.py
from __future__ import annotations
import json
import uuid
import logging # Added
from typing import Optional, Dict, Any, List, TYPE_CHECKING
import asyncio
import asyncpg.exceptions # ADDED IMPORT
from sqlalchemy.ext.asyncio import AsyncSession # Added for type hinting
from sqlalchemy import text # Added for session.execute

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.services.relationship_event_processor import RelationshipEventProcessor
    from bot.game.ai.narrative_generator import AINarrativeGenerator # Added import

logger = logging.getLogger(__name__) # Added

class GameLogManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]

    def __init__(self,
                 db_service: Optional[DBService] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 relationship_event_processor: Optional[RelationshipEventProcessor] = None,
                 narrative_generator: Optional[AINarrativeGenerator] = None # Added parameter
                 ):
        self._db_service = db_service
        self._settings = settings if settings is not None else {}
        self._relationship_event_processor = relationship_event_processor
        self._narrative_generator = narrative_generator # Stored instance
        logger.info("GameLogManager initialized.") # Changed

    def get_guild_setting(self, guild_id: str, setting_key: str, default_value: Any) -> Any:
        """ Safely retrieves a nested guild setting. """
        try:
            # Assuming settings structure like: self._settings['guilds']['guild_id']['setting_key']
            return self._settings.get('guilds', {}).get(guild_id, {}).get(setting_key, default_value)
        except Exception:
            return default_value

    async def log_event(
        self,
        guild_id: str,
        event_type: str,
        details: Dict[str, Any],
        player_id: Optional[str] = None,
        party_id: Optional[str] = None,
        location_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        description_key: Optional[str] = None, # Renamed from message_key
        description_params: Optional[Dict[str, Any]] = None, # Renamed from message_params
        involved_entities_ids: Optional[List[str]] = None,
        source_entity_id: Optional[str] = None, # New
        source_entity_type: Optional[str] = None, # New
        target_entity_id: Optional[str] = None, # New
        target_entity_type: Optional[str] = None, # New
        generate_narrative: bool = False, # New parameter
        session: Optional[AsyncSession] = None # New parameter for transaction participation
    ) -> None:
        if self._db_service is None:
            logger.error("GameLogManager: DB service not available.")
            return

        local_session = session if session else self._db_service.get_session()

        try:
            async with local_session as sess:
                async with sess.begin():
                    from bot.database.models import StoryLog, GuildConfig
                    from sqlalchemy.future import select

                    # Check if GuildConfig exists
                    stmt = select(GuildConfig).where(GuildConfig.id == guild_id)
                    result = await sess.execute(stmt)
                    guild_config = result.scalars().first()

                    if not guild_config:
                        logger.critical(f"GameLogManager: GuildConfig for guild_id '{guild_id}' does NOT exist. Skipping log event.")
                        return

                    log_id = uuid.uuid4()
                    
                    current_details: Dict[str, Any] = {}
                    if isinstance(details, dict):
                        current_details = details.copy()
                    elif isinstance(details, str):
                        try:
                            current_details = json.loads(details)
                            if not isinstance(current_details, dict):
                                current_details = {"original_details_str": details, "parsing_error": "Loaded JSON was not a dict"}
                        except json.JSONDecodeError:
                            current_details = {"original_details_str": details, "json_decode_error": True}
                    elif details is not None:
                        current_details = {"original_details_str": str(details)}

                    if generate_narrative and self._narrative_generator:
                        # Narrative generation logic remains the same
                        pass

                    new_log = StoryLog(
                        id=log_id,
                        guild_id=guild_id,
                        event_type=event_type,
                        details_json=current_details,
                        player_id=player_id,
                        party_id=party_id,
                        location_id=location_id,
                        channel_id=channel_id,
                        description_key=description_key,
                        description_params_json=description_params,
                        involved_entities_ids=involved_entities_ids,
                        source_entity_id=source_entity_id,
                        source_entity_type=source_entity_type,
                        target_entity_id=target_entity_id,
                        target_entity_type=target_entity_type
                    )
                    sess.add(new_log)
                    await sess.flush()

            if self._relationship_event_processor:
                log_data_for_processor = {
                    "guild_id": guild_id, "event_type": event_type,
                    "details": json.dumps(current_details), "log_id": str(log_id), "player_id": player_id,
                    "source_entity_id": source_entity_id, "source_entity_type": source_entity_type,
                    "target_entity_id": target_entity_id, "target_entity_type": target_entity_type,
                    "description_key": description_key, "description_params_json": json.dumps(description_params)
                }
                asyncio.create_task(
                    self._relationship_event_processor.process_new_log_entry(log_data_for_processor)
                )
        except Exception as e:
            logger.error(f"GameLogManager: Failed to log event to DB for guild {guild_id}. Type: {event_type}, Error: {e}", exc_info=True)
            # Fallback logging can be added here if needed

    async def get_logs_by_guild(
        self, guild_id: str, limit: int = 100, offset: int = 0,
        event_type_filter: Optional[str] = None, player_id_filter: Optional[str] = None,
        party_id_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if self._db_service is None:
            logger.error("GameLogManager: DB service not available. Cannot fetch logs for guild %s.", guild_id)
            return []

        try:
            async with self._db_service.get_session() as session:
                from bot.database.models import StoryLog
                from sqlalchemy.future import select

                stmt = select(StoryLog).where(StoryLog.guild_id == guild_id)
                if event_type_filter:
                    stmt = stmt.where(StoryLog.event_type == event_type_filter)
                if player_id_filter:
                    stmt = stmt.where(StoryLog.player_id == player_id_filter)
                if party_id_filter:
                    stmt = stmt.where(StoryLog.party_id == party_id_filter)

                stmt = stmt.order_by(StoryLog.timestamp.desc()).limit(limit).offset(offset)
                
                result = await session.execute(stmt)
                logs = result.scalars().all()
                return [log.__dict__ for log in logs]
        except Exception as e:
            logger.error(f"GameLogManager: Failed to fetch logs from DB for guild {guild_id}. Error: {e}", exc_info=True)
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
        if self._db_service is None:
            logger.error("GameLogManager: DB service not available. Cannot delete log %s for guild %s.", log_id, guild_id)
            return False

        try:
            async with self._db_service.get_session() as session:
                async with session.begin():
                    from bot.database.models import StoryLog
                    from sqlalchemy.future import select

                    stmt = select(StoryLog).where(StoryLog.id == log_id, StoryLog.guild_id == guild_id)
                    result = await session.execute(stmt)
                    log_entry = result.scalars().first()

                    if log_entry:
                        await session.delete(log_entry)
                        logger.info("GameLogManager: Attempted deletion of log %s for guild %s.", log_id, guild_id)
                        return True
                    return False
        except Exception as e:
            logger.error(f"GameLogManager: Failed to delete log {log_id} from DB for guild {guild_id}. Error: {e}", exc_info=True)
            return False

    async def get_log_by_id(self, log_id: str, guild_id: str) -> Optional[Dict[str, Any]]:
        if self._db_service is None:
            logger.error("GameLogManager: DB service not available. Cannot fetch log %s for guild %s.", log_id, guild_id)
            return None

        try:
            async with self._db_service.get_session() as session:
                from bot.database.models import StoryLog
                from sqlalchemy.future import select

                stmt = select(StoryLog).where(StoryLog.id == log_id, StoryLog.guild_id == guild_id)
                result = await session.execute(stmt)
                log_entry = result.scalars().first()

                if log_entry:
                    return log_entry.__dict__
                return None
        except Exception as e:
            logger.error(f"GameLogManager: Failed to fetch log {log_id} from DB for guild {guild_id}. Error: {e}", exc_info=True)
            return None

    async def get_log_by_detail(self, guild_id: str, event_type: str, detail_key: str, detail_value: Any) -> Optional[Dict[str,Any]]:
        if self._db_service is None:
            logger.error("GameLogManager: DB service not available. Cannot fetch log by detail for guild %s.", guild_id)
            return None

        try:
            async with self._db_service.get_session() as session:
                from bot.database.models import StoryLog
                from sqlalchemy.future import select

                stmt = select(StoryLog).where(
                    StoryLog.guild_id == guild_id,
                    StoryLog.event_type == event_type,
                    StoryLog.details_json[detail_key].astext == str(detail_value)
                ).order_by(StoryLog.timestamp.desc()).limit(1)

                result = await session.execute(stmt)
                log_entry = result.scalars().first()

                if log_entry:
                    return log_entry.__dict__
                return None
        except Exception as e:
            logger.error(
                f"GameLogManager: Failed to fetch log by detail ('{detail_key}'='{detail_value}') for guild {guild_id}, event_type {event_type}. Error: {e}",
                exc_info=True
            )
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
