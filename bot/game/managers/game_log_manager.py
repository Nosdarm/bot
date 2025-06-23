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
        if self._db_service is None or self._db_service.adapter is None or self._db_service.async_session_factory is None:
            log_message_fallback = (
                f"GameLogManager: DB service, adapter, or session factory not available. Log: "
                f"Guild: {guild_id}, Event: {event_type}, Details: {details}, "
                f"Player: {player_id}, Party: {party_id}, Location: {location_id}, Channel: {channel_id}, "
                f"DescKey: {description_key}, DescParams: {description_params}, Involved: {involved_entities_ids}, "
                f"SrcID: {source_entity_id}, SrcType: {source_entity_type}, TgtID: {target_entity_id}, TgtType: {target_entity_type}"
            )
            logger.error("GameLogManager: DB service not available. Log: %s", log_message_fallback)
            return

        # --- Fallback Check for GuildConfig ---
        guild_config_exists = False
        if session: # If a session is provided, use it for the check
            try:
                from bot.database.models import GuildConfig # Local import
                from sqlalchemy.future import select
                stmt = select(GuildConfig.guild_id).where(GuildConfig.guild_id == guild_id).limit(1)
                result = await session.execute(stmt)
                guild_config_exists = result.scalars().first() is not None
            except Exception as e_check_session:
                logger.error(f"GameLogManager: Error checking GuildConfig within provided session for guild {guild_id}: {e_check_session}", exc_info=True)
                # Proceed cautiously, or decide to bail if check fails
        else: # Otherwise, use a new session from the factory
            async with self._db_service.async_session_factory() as check_session:
                try:
                    from bot.database.models import GuildConfig # Local import
                    from sqlalchemy.future import select
                    stmt = select(GuildConfig.guild_id).where(GuildConfig.guild_id == guild_id).limit(1)
                    result = await check_session.execute(stmt)
                    guild_config_exists = result.scalars().first() is not None
                except Exception as e_check_new_session:
                    logger.error(f"GameLogManager: Error checking GuildConfig with new session for guild {guild_id}: {e_check_new_session}", exc_info=True)
                    # Decide whether to bail or proceed; for now, assume it might exist if check fails.

        if not guild_config_exists:
            logger.critical(f"GameLogManager: GuildConfig for guild_id '{guild_id}' does NOT exist prior to logging event '{event_type}'. Attempting last-chance initialization.")
            try:
                async with self._db_service.async_session_factory() as init_session: # type: ignore
                    from bot.game.guild_initializer import initialize_new_guild # Local import
                    init_success = await initialize_new_guild(init_session, guild_id, force_reinitialize=False)
                    if init_success:
                        logger.info(f"GameLogManager: Last-chance initialization for guild {guild_id} SUCCEEDED.")
                        guild_config_exists = True # Now it should exist
                    else:
                        logger.error(f"GameLogManager: Last-chance initialization for guild {guild_id} FAILED or reported no change. Log event for type '{event_type}' will be SKIPPED to prevent ForeignKeyViolation.")
                        # Log the original event details to logger as a fallback
                        details_for_fallback_log = {
                             "guild_id": guild_id, "event_type": f"SKIPPED_{event_type}", "original_details": details,
                             "reason": "GuildConfig missing and last-chance init failed.",
                             "player_id": player_id, "party_id": party_id, "location_id": location_id
                        }
                        logger.error(f"GameLogManager (FALLBACK_LOG_SKIP): {json.dumps(details_for_fallback_log)}")
                        return # CRITICAL: Skip logging to DB
            except Exception as e_init:
                logger.error(f"GameLogManager: Exception during last-chance initialization for guild {guild_id}: {e_init}. Log event for type '{event_type}' will be SKIPPED.", exc_info=True)
                details_for_fallback_log_exc = {
                    "guild_id": guild_id, "event_type": f"SKIPPED_{event_type}", "original_details": details,
                    "reason": "Exception during last-chance init.", "exception_details": str(e_init),
                    "player_id": player_id, "party_id": party_id, "location_id": location_id
                }
                logger.error(f"GameLogManager (FALLBACK_LOG_SKIP_EXCEPTION): {json.dumps(details_for_fallback_log_exc)}")
                return # CRITICAL: Skip logging to DB
        # --- End Fallback Check ---

        log_id = str(uuid.uuid4())
        description_params_json = json.dumps(description_params) if description_params is not None else None
        involved_entities_ids_json = json.dumps(involved_entities_ids) if involved_entities_ids is not None else None

        # Ensure details is a mutable dictionary if it's not already
        # This is crucial because we might add ai_narrative keys to it.
        current_details: Dict[str, Any] = {}
        if isinstance(details, dict):
            current_details = details.copy() # Work with a copy if it's already a dict
        elif isinstance(details, str):
            try:
                current_details = json.loads(details)
                if not isinstance(current_details, dict): # Ensure loaded JSON is a dict
                    current_details = {"original_details_str": details, "parsing_error": "Loaded JSON was not a dict"}
            except json.JSONDecodeError:
                current_details = {"original_details_str": details, "json_decode_error": True}
        elif details is not None: # Handle other non-dict, non-str types by converting to str
             current_details = {"original_details_str": str(details)}


        if generate_narrative and self._narrative_generator:
            source_name = current_details.get("source_name", source_entity_id or player_id or "Unknown Source")
            target_name = current_details.get("target_name", target_entity_id)

            key_details_list = []
            # Example: More specific detail extraction based on event_type
            if event_type == "PLAYER_MOVE": # Assuming event_type strings are consistent
                key_details_list.append(f"to location {current_details.get('target_location_name', current_details.get('target_location_id', 'somewhere'))}")
            elif event_type == "ITEM_PICKUP":
                 key_details_list.append(f"item '{current_details.get('item_name', current_details.get('item_id', 'something'))}'")
            elif event_type == "NPC_ATTACK": # Example for another type
                 key_details_list.append(f"target '{current_details.get('target_name', target_name or 'someone')}' with '{current_details.get('action_name', 'an attack')}'")


            if not key_details_list: # Fallback if no specific details extracted
                temp_details_for_str = {k: v for k, v in current_details.items() if not k.startswith('ai_narrative_') and k not in ['source_name', 'target_name']}
                if temp_details_for_str:
                    key_details_list.append(str(temp_details_for_str))

            key_details_str = ". ".join(key_details_list) if key_details_list else "something notable occurred."

            event_data_for_narrative = {
                "event_type": event_type,
                "source_name": str(source_name),
                "target_name": str(target_name) if target_name else None,
                "key_details_str": key_details_str
            }

            world_setting = self.get_guild_setting(guild_id, "world_setting", "generic fantasy")
            tone = self.get_guild_setting(guild_id, "narrative_tone", "neutral")
            langs_to_generate = self.get_guild_setting(guild_id, "narrative_langs", ["en"])

            guild_context_for_narrative = {
                "world_setting": world_setting,
                "tone": tone
            }

            for lang_code in langs_to_generate:
                try:
                    narrative = await self._narrative_generator.generate_narrative_for_event(
                        event_data=event_data_for_narrative,
                        guild_context=guild_context_for_narrative,
                        lang=lang_code
                    )
                    if narrative and not narrative.startswith("Error:"):
                        current_details[f'ai_narrative_{lang_code}'] = narrative
                    elif narrative:
                        current_details[f'ai_narrative_{lang_code}_error'] = narrative
                except Exception as e:
                    current_details[f'ai_narrative_{lang_code}_error'] = f"Failed to generate narrative for {lang_code}: {str(e)}"
                    logger.error(f"GameLogManager: Exception during narrative generation for lang {lang_code}, guild {guild_id}: {e}", exc_info=True)

        details_json = json.dumps(current_details) # Serialize final details (potentially with narrative)

        sql = """
            INSERT INTO game_logs 
            (id, timestamp, guild_id, player_id, party_id, event_type,
            description_key, description_params_json, location_id, involved_entities_ids, details, channel_id,
            source_entity_id, source_entity_type, target_entity_id, target_entity_type)
            VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        """
        params = (
            log_id, guild_id, player_id, party_id, event_type,
            description_key, description_params_json, location_id, involved_entities_ids_json,
            details_json, channel_id,
            source_entity_id, source_entity_type, target_entity_id, target_entity_type # New params
        )

        try:
            if session:
                await session.execute(text(sql), params)
            else:
                await self._db_service.adapter.execute(sql, params)
            logger.debug("GameLogManager: Logged event %s (desc_key: %s) to DB for guild %s. ID: %s", event_type, description_key or 'N/A', guild_id, log_id)

            if self._relationship_event_processor:
                # Ensure details being passed are stringified JSON if RelationshipEventProcessor expects that
                log_data_for_processor = {
                    "guild_id": guild_id, "event_type": event_type,
                    "details": details_json, "log_id": log_id, "player_id": player_id,
                    "source_entity_id": source_entity_id, "source_entity_type": source_entity_type,
                    "target_entity_id": target_entity_id, "target_entity_type": target_entity_type,
                    "description_key": description_key, "description_params_json": description_params_json
                }
                asyncio.create_task(
                    self._relationship_event_processor.process_new_log_entry(log_data_for_processor)
                )
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("GameLogManager: 'game_logs' table not found in database for guild %s. Log event (type: %s) will be skipped.", guild_id, event_type)
        except Exception as e:
            logger.error("GameLogManager: Failed to log event to DB for guild %s. Type: %s, Error: %s", guild_id, event_type, e, exc_info=True)
            fallback_data = {
                "log_id": log_id, "guild_id": guild_id, "player_id": player_id, "party_id": party_id,
                "event_type": event_type, "description_key": description_key, "description_params": description_params,
                "location_id": location_id, "involved_entities_ids": involved_entities_ids,
                "details": details, "channel_id": channel_id,
                "source_entity_id": source_entity_id, "source_entity_type": source_entity_type,
                "target_entity_id": target_entity_id, "target_entity_type": target_entity_type
            }
            logger.error("GameLogManager (DB-FAIL): Data: %s", json.dumps(fallback_data))

    async def get_logs_by_guild(
        self, guild_id: str, limit: int = 100, offset: int = 0,
        event_type_filter: Optional[str] = None, player_id_filter: Optional[str] = None,
        party_id_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("GameLogManager: DB service or adapter not available. Cannot fetch logs for guild %s.", guild_id)
            return []
        
        params_list: List[Any] = [guild_id]
        sql = """SELECT id, timestamp, guild_id, player_id, party_id, event_type,
                      description_key, description_params_json, location_id,
                      involved_entities_ids, details, channel_id,
                      source_entity_id, source_entity_type, target_entity_id, target_entity_type
               FROM game_logs WHERE guild_id = $1"""
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
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("GameLogManager: 'game_logs' table not found when fetching logs for guild %s. Returning empty list.", guild_id)
            return []
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
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("GameLogManager: 'game_logs' table not found for deleting log %s in guild %s. Operation skipped.", log_id, guild_id)
            return False # Indicate that deletion didn't occur in DB
        except Exception as e:
            logger.error("GameLogManager: Failed to delete log %s from DB for guild %s. Error: %s", log_id, guild_id, e, exc_info=True) # Changed
            return False

    async def get_log_by_id(self, log_id: str, guild_id: str) -> Optional[Dict[str, Any]]:
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("GameLogManager: DB service or adapter not available. Cannot fetch log %s for guild %s.", log_id, guild_id)
            return None

        sql = """SELECT id, timestamp, guild_id, player_id, party_id, event_type,
                      description_key, description_params_json, location_id,
                      involved_entities_ids, details, channel_id,
                      source_entity_id, source_entity_type, target_entity_id, target_entity_type
               FROM game_logs WHERE id = $1 AND guild_id = $2"""
        try:
            row = await self._db_service.adapter.fetchone(sql, (log_id, guild_id))
            if row:
                return dict(row)
            return None
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("GameLogManager: 'game_logs' table not found when fetching log %s for guild %s.", log_id, guild_id)
            return None
        except Exception as e:
            logger.error("GameLogManager: Failed to fetch log %s from DB for guild %s. Error: %s", log_id, guild_id, e, exc_info=True) # Changed
            return None

    async def get_log_by_detail(self, guild_id: str, event_type: str, detail_key: str, detail_value: Any) -> Optional[Dict[str,Any]]:
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("GameLogManager: DB service or adapter not available. Cannot fetch log by detail for guild %s.", guild_id)
            return None

        # Basic validation for detail_key to prevent trivial SQL injection if it were less controlled.
        # For "report_id", this is safe.
        if not detail_key.replace('_','').isalnum(): # Allow underscores
            logger.error(f"GameLogManager: Invalid detail_key format: {detail_key}")
            return None

        # The query uses ->> to get the value as text, so detail_value should be stringified for comparison.
        # This is suitable for simple key-value lookups where value is text or can be unambiguously cast to text.
        # For more complex JSON queries (e.g., numeric comparisons, existence of keys, array contents),
        # the query or parameters might need adjustment.
        sql = f"""
            SELECT id, timestamp, guild_id, player_id, party_id, event_type,
                   description_key, description_params_json, location_id,
                   involved_entities_ids, details, channel_id,
                   source_entity_id, source_entity_type, target_entity_id, target_entity_type
            FROM game_logs
            WHERE guild_id = $1
              AND event_type = $2
              AND (details->>'{detail_key}') = $3
            ORDER BY timestamp DESC
            LIMIT 1
        """
        # Ensure detail_value is passed as a string for the comparison with ->>
        params = (guild_id, event_type, str(detail_value))

        try:
            row = await self._db_service.adapter.fetchone(sql, params)
            if row:
                return dict(row)
            return None
        except asyncpg.exceptions.UndefinedTableError:
            logger.warning("GameLogManager: 'game_logs' table not found when fetching log by detail ('%s'='%s') for guild %s.", detail_key, detail_value, guild_id)
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
