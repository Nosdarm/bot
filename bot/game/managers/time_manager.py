# bot/game/managers/time_manager.py

import asyncio
import traceback # Will be removed
import json
import uuid
import logging # Added
from typing import Optional, Dict, Any, List, Callable, Awaitable, Union, Set, TYPE_CHECKING

from bot.services.db_service import DBService

if TYPE_CHECKING: # Ensure TYPE_CHECKING is defined or imported if used
    pass

logger = logging.getLogger(__name__) # Added

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

class TimeManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    def __init__(self,
                 db_service: Optional[DBService] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 ):
        logger.info("Initializing TimeManager...") # Changed
        self._db_service = db_service
        self._settings = settings
        self._current_game_time: Dict[str, float] = {}
        self._active_timers: Dict[str, Dict[str, Any]] = {}
        logger.info("TimeManager initialized.") # Changed

    def get_current_game_time(self, guild_id: str) -> float:
         guild_id_str = str(guild_id)
         return self._current_game_time.get(guild_id_str, 0.0)

    async def add_timer(self, guild_id: str, timer_type: str, duration: float, callback_data: Dict[str, Any], **kwargs: Any) -> Optional[str]:
        guild_id_str = str(guild_id)
        logger.info("TimeManager: Adding timer of type '%s' with duration %.2f for guild %s.", timer_type, duration, guild_id_str) # Changed

        if self._db_service is None:
             logger.error("TimeManager: Error adding timer for guild %s: Database service is not available.", guild_id_str) # Changed
             return None

        if duration <= 0:
             logger.warning("TimeManager: Attempted to add timer with non-positive duration (%.2f) for guild %s. Sparing immediately or ignoring.", duration, guild_id_str) # Changed
             return None

        timer_id = str(uuid.uuid4())
        ends_at = self.get_current_game_time(guild_id_str) + duration
        new_timer_data: Dict[str, Any] = {
            'id': timer_id, 'type': timer_type, 'ends_at': ends_at,
            'callback_data': callback_data, 'is_active': True, 'guild_id': guild_id_str,
        }
        try:
            sql = 'INSERT INTO timers (id, type, ends_at, callback_data, is_active, guild_id) VALUES ($1, $2, $3, $4, $5, $6)'
            params = (
                new_timer_data['id'], new_timer_data['type'], new_timer_data['ends_at'],
                json.dumps(new_timer_data['callback_data']), bool(new_timer_data['is_active']),
                new_timer_data['guild_id']
            )
            await self._db_service.adapter.execute(sql, params)
            logger.info("TimeManager: Timer '%s' added for guild %s, ends at %.2f, saved to DB with ID %s.", timer_type, guild_id_str, ends_at, timer_id) # Changed
            self._active_timers.setdefault(guild_id_str, {})[timer_id] = new_timer_data
            logger.debug("TimeManager: Timer %s added to memory cache for guild %s.", timer_id, guild_id_str) # Changed
            return timer_id
        except Exception as e:
            logger.error("TimeManager: Error adding or saving timer to DB for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            return None

    async def remove_timer(self, guild_id: str, timer_id: str) -> None:
        guild_id_str, timer_id_str = str(guild_id), str(timer_id)
        logger.info("TimeManager: Removing timer %s for guild %s...", timer_id_str, guild_id_str) # Changed
        guild_timers_cache = self._active_timers.get(guild_id_str)
        if not guild_timers_cache or timer_id_str not in guild_timers_cache:
             logger.warning("TimeManager: Attempted to remove non-existent or inactive timer %s for guild %s (not found in cache).", timer_id_str, guild_id_str) # Changed
        try:
            if self._db_service:
                sql = 'DELETE FROM timers WHERE id = $1 AND guild_id = $2'
                await self._db_service.adapter.execute(sql, (timer_id_str, guild_id_str))
                logger.info("TimeManager: Timer %s deleted from DB for guild %s.", timer_id_str, guild_id_str) # Changed
            else:
                logger.warning("TimeManager: No DB service. Simulating delete from DB for timer %s for guild %s.", timer_id_str, guild_id_str) # Changed
            if guild_timers_cache:
                 guild_timers_cache.pop(timer_id_str, None)
                 if not guild_timers_cache: self._active_timers.pop(guild_id_str, None)
            logger.info("TimeManager: Timer %s removed from cache for guild %s.", timer_id_str, guild_id_str) # Changed
        except Exception as e:
            logger.error("TimeManager: Error removing timer %s for guild %s: %s", timer_id_str, guild_id_str, e, exc_info=True) # Changed

    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        # logger.debug("TimeManager: Processing tick for guild %s with delta: %.2f", guild_id_str, game_time_delta) # Too noisy for info
        if self._db_service is None:
             logger.warning("TimeManager: Skipping tick processing for guild %s (no DB service).", guild_id_str) # Changed
             return

        current_game_time_for_guild = self._current_game_time.get(guild_id_str, 0.0)
        current_game_time_for_guild += float(game_time_delta)
        self._current_game_time[guild_id_str] = current_game_time_for_guild
        # logger.debug("TimeManager: Updated game time for guild %s to %.2f.", guild_id_str, self._current_game_time[guild_id_str]) # Too noisy

        guild_timers_cache = self._active_timers.get(guild_id_str, {})
        if not guild_timers_cache: return

        timers_to_trigger: List[Dict[str, Any]] = []
        for timer_data in list(guild_timers_cache.values()):
             if timer_data.get('is_active', True) and timer_data.get('ends_at', float('inf')) <= current_game_time_for_guild:
                  if 'id' in timer_data and 'type' in timer_data and 'ends_at' in timer_data:
                       # logger.debug("TimeManager: Timer '%s' (ID %s) for guild %s triggered at game time %.2f.", timer_data.get('type', 'Unknown'), timer_data.get('id', 'N/A'), guild_id_str, current_game_time_for_guild) # Too noisy
                       timers_to_trigger.append(timer_data)
                       timer_data['is_active'] = False
                  else:
                       logger.warning("TimeManager: Skipping triggering invalid timer data in cache for guild %s: %s", guild_id_str, timer_data) # Changed

        for timer_data in timers_to_trigger:
             try:
                  await self._trigger_timer_callback(timer_data['type'], timer_data.get('callback_data', {}), **kwargs)
                  await self.remove_timer(guild_id_str, timer_data['id'])
             except Exception as e:
                  logger.error("TimeManager: Error triggering timer callback for timer %s (%s) for guild %s: %s", timer_data.get('id', 'N/A'), timer_data.get('type', 'Unknown'), guild_id_str, e, exc_info=True) # Changed
        # logger.debug("TimeManager: Tick processing finished for guild %s.", guild_id_str) # Too noisy

    async def _trigger_timer_callback(self, timer_type: str, callback_data: Dict[str, Any], **kwargs: Any) -> None:
        if not isinstance(callback_data, dict):
            logger.warning("TimeManager: callback_data is not a dictionary for timer type '%s'. Received: %s. Guild: %s. Skipping.", timer_type, type(callback_data), kwargs.get('guild_id'), exc_info=True) # Changed
            return
        guild_id = kwargs.get('guild_id')
        logger.info("TimeManager: Triggering callback for timer type '%s' for guild %s with data %s.", timer_type, guild_id, callback_data) # Changed

        if timer_type == 'event_stage_transition':
             event_id, target_stage_id = callback_data.get('event_id'), callback_data.get('target_stage_id')
             if event_id and target_stage_id and guild_id is not None:
                  event_manager, event_stage_processor, send_callback_factory = kwargs.get('event_manager'), kwargs.get('event_stage_processor'), kwargs.get('send_callback_factory')
                  if event_manager and event_stage_processor and send_callback_factory:
                       event = event_manager.get_event(guild_id, event_id)
                       if event:
                            logger.info("TimeManager: Triggering auto-transition for event %s to stage %s for guild %s...", event_id, target_stage_id, guild_id) # Changed
                            if event.channel_id is None:
                                 logger.warning("TimeManager: Cannot auto-advance event %s in guild %s. Event has no channel_id for notifications.", event.id, guild_id) # Changed
                                 return
                            event_channel_callback = send_callback_factory(event.channel_id)
                            await event_stage_processor.advance_stage(event=event, target_stage_id=target_stage_id, **kwargs, send_message_callback=event_channel_callback, transition_context={"trigger": "timer", "timer_type": timer_type, "guild_id": guild_id})
                       else: logger.error("TimeManager: Error triggering event stage transition timer: Event %s not found for guild %s.", event_id, guild_id) # Changed
                  else: logger.error("TimeManager: Error triggering event stage transition timer for guild %s: Required managers/processors not available.", guild_id) # Changed
             elif guild_id is None: logger.error("TimeManager: Error triggering event stage transition timer for %s: guild_id missing in context.", event_id) # Changed
        else:
             logger.warning("TimeManager: Unhandled timer type '%s' triggered for guild %s.", timer_type, guild_id) # Changed

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("TimeManager: Saving state for guild %s...", guild_id_str) # Changed
        if self._db_service is None:
             logger.error("TimeManager: Database service is not available. Skipping save for guild %s.", guild_id_str) # Changed
             return
        try:
            current_game_time_for_guild = self._current_game_time.get(guild_id_str, 0.0)
            await self._db_service.adapter.execute("INSERT INTO global_state (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (f'game_time_{guild_id_str}', json.dumps(current_game_time_for_guild)))
            await self._db_service.adapter.execute("DELETE FROM timers WHERE guild_id = $1", (guild_id_str,))
            guild_timers_cache = self._active_timers.get(guild_id_str, {})
            timers_to_save = [t for t in guild_timers_cache.values() if t.get('is_active', True)]
            if timers_to_save:
                sql = 'INSERT INTO timers (id, type, ends_at, callback_data, is_active, guild_id) VALUES ($1, $2, $3, $4, $5, $6)'
                data_to_save = []
                for timer_data in timers_to_save:
                    timer_guild_id = timer_data.get('guild_id')
                    if timer_guild_id is None or str(timer_guild_id) != guild_id_str:
                         logger.warning("TimeManager: Skipping save for timer %s (%s) with missing or mismatched guild_id (%s) in cache. Expected %s.", timer_data.get('id', 'N/A'), timer_data.get('type', 'Unknown'), timer_guild_id, guild_id_str) # Changed
                         continue
                    data_to_save.append((timer_data['id'], timer_data['type'], timer_data['ends_at'], json.dumps(timer_data.get('callback_data', {})), bool(timer_data.get('is_active', True)), timer_guild_id))
                if data_to_save:
                     await self._db_service.adapter.execute_many(sql, data_to_save)
            logger.info("TimeManager: Successfully saved state for guild %s (time: %.2f, timers: %s).", guild_id_str, current_game_time_for_guild, len(timers_to_save)) # Changed
        except Exception as e:
            logger.error("TimeManager: Error during saving state for guild %s: %s", guild_id_str, e, exc_info=True) # Changed

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("TimeManager: Loading state for guild %s...", guild_id_str) # Changed
        if self._db_service is None:
             logger.warning("TimeManager: Database service not available. Loading placeholder state or leaving default for guild %s.", guild_id_str) # Changed
             if guild_id_str not in self._current_game_time: self._current_game_time[guild_id_str] = 0.0
             self._active_timers.pop(guild_id_str, None); self._active_timers[guild_id_str] = {}
             logger.info("TimeManager: State is default after load (no DB adapter) for guild %s. Time = %.2f, Timers = 0.", guild_id_str, self._current_game_time.get(guild_id_str, 0.0)) # Changed
             return
        try:
            sql_time = 'SELECT value FROM global_state WHERE key = $1'
            key = f'game_time_{guild_id_str}'
            row_time = await self._db_service.adapter.fetchone(sql_time, (key,))
            if row_time and row_time['value']:
                try:
                    loaded_time = json.loads(row_time['value'])
                    self._current_game_time[guild_id_str] = float(loaded_time)
                    logger.info("TimeManager: Loaded game time for guild %s: %.2f", guild_id_str, self._current_game_time[guild_id_str]) # Changed
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                     logger.error("TimeManager: Error decoding or converting game time from DB for guild %s: %s. Using default 0.0", guild_id_str, e, exc_info=True) # Changed
                     self._current_game_time[guild_id_str] = 0.0
            else:
                 logger.info("TimeManager: No saved game time found for guild %s. Starting from 0.0.", guild_id_str) # Changed
                 self._current_game_time[guild_id_str] = 0.0

            self._active_timers.pop(guild_id_str, None); self._active_timers[guild_id_str] = {}
            guild_timers_cache = self._active_timers[guild_id_str]
            sql_timers = 'SELECT id, type, ends_at, callback_data, is_active, guild_id FROM timers WHERE guild_id = $1 AND is_active = TRUE'
            rows_timers = await self._db_service.adapter.fetchall(sql_timers, (guild_id_str,))
            if rows_timers:
                 logger.info("TimeManager: Loaded %s active timers for guild %s from DB.", len(rows_timers), guild_id_str) # Changed
                 time_mgr, current_game_time_for_guild = kwargs.get('time_manager', self), None
                 if time_mgr and hasattr(time_mgr, 'get_current_game_time'): current_game_time_for_guild = time_mgr.get_current_game_time(guild_id_str)
                 loaded_count = 0
                 for row in rows_timers:
                      try:
                           row_dict = dict(row); status_id_db = row_dict.get('id')
                           if status_id_db is None: continue
                           row_dict['callback_data'] = json.loads(row_dict.get('callback_data') or '{}') if isinstance(row_dict.get('callback_data'), (str, bytes)) else {}
                           row_dict['ends_at'] = float(row_dict['ends_at']) if row_dict.get('ends_at') is not None else float('inf')
                           row_dict['is_active'] = bool(row_dict.get('is_active'))
                           if str(row_dict.get('guild_id')) != guild_id_str: continue # Ensure guild match
                           timer_instance_data = {k: row_dict[k] for k in ['id', 'type', 'ends_at', 'callback_data', 'is_active', 'guild_id']}
                           if timer_instance_data['ends_at'] is not None and current_game_time_for_guild is not None:
                                if timer_instance_data['ends_at'] <= current_game_time_for_guild: # Timer already expired
                                    logger.info("TimeManager: Expired timer %s (type: %s) found during load for guild %s. Triggering immediately.", timer_instance_data['id'], timer_instance_data['type'], guild_id_str) # Added
                                    await self._trigger_timer_callback(timer_instance_data['type'], timer_instance_data.get('callback_data', {}), **kwargs)
                                    await self.remove_timer(guild_id_str, timer_instance_data['id']) # Remove after triggering
                                    continue # Don't add to active cache
                           guild_timers_cache[timer_instance_data['id']] = timer_instance_data
                           loaded_count += 1
                      except (json.JSONDecodeError, ValueError, TypeError) as e_row:
                           logger.error("TimeManager: Error decoding or converting timer data from DB for ID %s for guild %s: %s. Skipping timer.", row.get('id', 'Unknown'), guild_id_str, e_row, exc_info=True) # Changed
                 logger.info("TimeManager: Successfully loaded %s active timers into cache for guild %s.", loaded_count, guild_id_str) # Changed
            else:
                 logger.info("TimeManager: No active timers found in DB for guild %s.", guild_id_str) # Changed
        except Exception as e_load:
            logger.critical("TimeManager: CRITICAL ERROR loading state for guild %s from DB: %s", guild_id_str, e_load, exc_info=True) # Changed

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
         logger.info("TimeManager: Simulating rebuilding runtime caches for guild %s.", guild_id) # Changed
         pass
