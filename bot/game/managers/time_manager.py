# bot/game/managers/time_manager.py

# --- Импорты ---
import asyncio
import traceback
import json
import uuid
from typing import Optional, Dict, Any, List, Callable, Awaitable, Union, Set # Добавляем Set


# TODO: Импортируйте модели, если TimeManager их использует (например, для аннотаций)
# from bot.game.models.game_time import GameTime # Если у вас есть модель для времени

# TODO: Импорт адаптера БД - используем наш конкретный SQLite адаптер
from bot.database.sqlite_adapter import SqliteAdapter

# TODO: Импорт других менеджеров, если TimeManager их использует в своих методах
# Например, менеджеры, методы которых вызываются при срабатывании таймеров
# from bot.game.managers.event_manager import EventManager
# from bot.game.managers.status_manager import StatusManager
# from bot.game.managers.combat_manager import CombatManager
# from bot.game.managers.character_manager import CharacterManager # Если таймеры привязаны к персонажам


# TODO: Определите Type Alias для данных callback'а таймера, если они специфичны
# TimerCallbackData = Dict[str, Any]


class TimeManager:
    """
    Менеджер для управления игровым временем и таймерами.
    Отвечает за обновление времени, срабатывание таймеров и их персистентность в БД.
    Работает на основе guild_id для многогильдийной поддержки.
    """
    # Добавляем required_args для совместимости с PersistenceManager
    required_args_for_load = ["guild_id"] # load_state фильтрует по guild_id
    required_args_for_save = ["guild_id"] # save_state фильтрует по guild_id
    required_args_for_rebuild = ["guild_id"] # rebuild_runtime_caches фильтрует по guild_id


    def __init__(self,
                 # Принимаем зависимости, которые передает GameManager.
                 db_adapter: Optional[SqliteAdapter] = None,
                 settings: Optional[Dict[str, Any]] = None,

                 # TODO: Добавьте другие зависимости, если TimeManager их требует
                 # event_manager: Optional['EventManager'] = None,
                 # status_manager: Optional['StatusManager'] = None,
                 # combat_manager: Optional['CombatManager'] = None,
                 # character_manager: Optional['CharacterManager'] = None,
                 ):
        print("Initializing TimeManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        # TODO: Сохраните другие зависимости
        # self._event_manager = event_manager
        # self._status_manager = status_manager
        # self._combat_manager = combat_manager
        # self._character_manager = character_manager


        # --- Хранилище для игрового времени и активных таймеров ---
        # NOTE: Если игровое время должно быть пер-гильдийным, _current_game_time
        # должен быть Dict[str, float] = {guild_id: game_time}.
        # В текущей реализации оно глобальное float. Переделываем на пер-гильдийное.
        self._current_game_time: Dict[str, float] = {} # <-- ИСПРАВЛЕНО: Пер-гильдийное время

        # Храним активные таймеры в словаре {guild_id: {timer_id: timer_data}}. Переделываем на пер-гильдийное.
        self._active_timers: Dict[str, Dict[str, Any]] = {} # <-- ИСПРАВЛЕНО: Пер-гильдийные таймеры


        print("TimeManager initialized.")

    # --- Методы получения времени и таймеров ---

    # ИСПРАВЛЕНИЕ: get_current_game_time должен принимать guild_id.
    def get_current_game_time(self, guild_id: str) -> float:
         """Возвращает текущее игровое время для определенной гильдии."""
         guild_id_str = str(guild_id)
         # Возвращаем время для гильдии, по умолчанию 0.0 если нет записи
         return self._current_game_time.get(guild_id_str, 0.0)

    # TODO: Добавьте метод для получения конкретного таймера

    # --- Методы управления таймерами (интеграция с БД) ---

    # ИСПРАВЛЕНИЕ: add_timer должен принимать guild_id.
    async def add_timer(self, guild_id: str, timer_type: str, duration: float, callback_data: Dict[str, Any], **kwargs: Any) -> Optional[str]:
        """
        Добавляет новый таймер, который сработает через указанное игровое время duration для определенной гильдии.
        Сохраняет его в БД и добавляет в кеш активных таймеров.
        :param guild_id: ID гильдии, к которой привязан таймер.
        :param timer_type: Строковый тип таймера (для идентификации логики срабатывания).
        :param duration: Длительность в игровом времени до срабатывания.
        :param callback_data: Словарь данных, необходимых при срабатывании (JSON-сериализуемый).
        :param kwargs: Дополнительный контекст, переданный из вызывающего метода.
        :return: ID созданного таймера или None при ошибке.
        """
        guild_id_str = str(guild_id)
        print(f"TimeManager: Adding timer of type '{timer_type}' with duration {duration} for guild {guild_id_str}.")

        if self._db_adapter is None:
             print(f"TimeManager: Error adding timer for guild {guild_id_str}: Database adapter is not available.")
             return None

        if duration <= 0:
             print(f"TimeManager: Warning: Attempted to add timer with non-positive duration ({duration}). Sparing immediately.")
             # TODO: Возможно, выполнить логику срабатывания callback_data сразу же?
             # await self._trigger_timer_callback(timer_type, callback_data, **kwargs) # Нужны kwargs! (они уже в сигнатуре add_timer)
             # Решите, как обрабатывать нулевую/отрицательную длительность - сразу срабатывать или игнорировать.
             # Игнорирование может быть безопаснее, если callback_data неполны.
             return None # Пока просто игнорируем и возвращаем None


        timer_id = str(uuid.uuid4())
        # Используем пер-гильдийное текущее время для расчета времени срабатывания
        ends_at = self.get_current_game_time(guild_id_str) + duration # Используем get_current_game_time с guild_id

        new_timer_data: Dict[str, Any] = { # Явная аннотация словаря
            'id': timer_id,
            'type': timer_type,
            'ends_at': ends_at,
            'callback_data': callback_data,
            'is_active': True,
            'guild_id': guild_id_str, # <-- СОХРАНЯЕМ guild_id в данных таймера
            # TODO: Добавьте другие поля для Timer, если есть (напр., target_id, target_type)
            # 'target_id': kwargs.get('target_id'),
            # 'target_type': kwargs.get('target_type'),
        }

        try:
            # TODO: Убедитесь, что SQL запрос соответствует ВСЕМ полям Timer модели, включая guild_id
            sql = '''
                INSERT INTO timers (id, type, ends_at, callback_data, is_active, guild_id)
                VALUES (?, ?, ?, ?, ?, ?)
                -- TODO: Добавить другие колонки в SQL
            '''
            params = (
                new_timer_data['id'],
                new_timer_data['type'],
                new_timer_data['ends_at'],
                json.dumps(new_timer_data['callback_data']),
                1 if new_timer_data['is_active'] else 0,
                new_timer_data['guild_id'] # <-- Параметр guild_id
                # TODO: Добавить другие параметры в кортеж
            )

            await self._db_adapter.execute(sql, params)
            # execute уже коммитит

            print(f"TimeManager: Timer '{timer_type}' added for guild {guild_id_str}, ends at {ends_at:.2f}, saved to DB with ID {timer_id}.")

            # --- Добавление в кеш после успешного сохранения ---
            # Добавляем в пер-гильдийный кеш таймеров
            self._active_timers.setdefault(guild_id_str, {})[timer_id] = new_timer_data
            print(f"TimeManager: Timer {timer_id} added to memory cache for guild {guild_id_str}.")

            return timer_id

        except Exception as e:
            print(f"TimeManager: ❌ Error adding or saving timer to DB for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # rollback уже в execute
            return None


    # ИСПРАВЛЕНИЕ: remove_timer должен принимать guild_id.
    async def remove_timer(self, guild_id: str, timer_id: str) -> None:
        """
        Удаляет таймер по ID из кеша и БД для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        timer_id_str = str(timer_id)
        print(f"TimeManager: Removing timer {timer_id_str} for guild {guild_id_str}...")

        # Проверяем наличие в пер-гильдийном кеше
        guild_timers_cache = self._active_timers.get(guild_id_str)

        if not guild_timers_cache or timer_id_str not in guild_timers_cache:
             print(f"TimeManager: Warning: Attempted to remove non-existent or inactive timer {timer_id_str} for guild {guild_id_str} (not found in cache).")
             # Продолжаем попытку удаления из БД, на случай если он там есть, но нет в кеше.
             pass


        try:
            # --- Удаляем из БД ---
            if self._db_adapter:
                # ИСПРАВЛЕНИЕ: Добавляем фильтр по guild_id в SQL DELETE
                sql = 'DELETE FROM timers WHERE id = ? AND guild_id = ?'
                await self._db_adapter.execute(sql, (timer_id_str, guild_id_str))
                # execute уже коммитит
                print(f"TimeManager: Timer {timer_id_str} deleted from DB for guild {guild_id_str}.")
            else:
                print(f"TimeManager: No DB adapter. Simulating delete from DB for timer {timer_id_str} for guild {guild_id_str}.")

            # --- Удаляем из кеша ---
            # Удаляем из пер-гильдийного кеша
            if guild_timers_cache: # Проверяем, что кеш для гильдии существует
                 guild_timers_cache.pop(timer_id_str, None) # Удаляем по ID
                 # Если после удаления кеш для гильдии опустел, можно удалить и сам ключ гильдии из self._active_timers
                 if not guild_timers_cache:
                      self._active_timers.pop(guild_id_str, None)
            print(f"TimeManager: Timer {timer_id_str} removed from cache for guild {guild_id_str}.")


        except Exception as e:
            print(f"TimeManager: ❌ Error removing timer {timer_id_str} for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # rollback уже в execute


    # Метод обработки тика (используется WorldSimulationProcessor)
    # ИСПРАВЛЕНИЕ: Добавляем guild_id и **kwargs к сигнатуре
    # ИСПРАВЛЕНИЕ: Аннотируем game_time_delta как float
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        """
        Обрабатывает тик игрового времени для определенной гильдии.
        Обновляет текущее время, проверяет и срабатывает активные таймеры для этой гильдии.
        Принимает game_time_delta и менеджеры/сервисы через kwargs для вызова callback'ов.
        """
        # print(f"TimeManager: Processing tick for guild {guild_id} with delta: {game_time_delta}") # Бывает очень шумно

        if self._db_adapter is None:
             print(f"TimeManager: Skipping tick processing for guild {guild_id} (no DB adapter).")
             return

        guild_id_str = str(guild_id)

        # --- Обновляем текущее игровое время для этой гильдии ---
        # Получаем текущее время для гильдии (по умолчанию 0.0), обновляем его и сохраняем в пер-гильдийном кеше
        current_game_time_for_guild = self._current_game_time.get(guild_id_str, 0.0)
        current_game_time_for_guild += float(game_time_delta)
        self._current_game_time[guild_id_str] = current_game_time_for_guild # Сохраняем обновленное время в пер-гильдийном кеше
        # print(f"TimeManager: Updated game time for guild {guild_id_str} to {self._current_game_time[guild_id_str]:.2f}.")

        # --- Проверяем и срабатываем активные таймеры для этой гильдии ---
        # Получаем пер-гильдийный кеш таймеров
        guild_timers_cache = self._active_timers.get(guild_id_str, {})

        if not guild_timers_cache:
             # print(f"TimeManager: No active timers in cache for guild {guild_id_str} to check.") # Too noisy
             return # Нет таймеров для этой гильдии в кеше

        timers_to_trigger: List[Dict[str, Any]] = [] # Список данных таймеров к срабатыванию

        # Проходим по всем активным таймерам в кеше ДЛЯ ЭТОЙ ГИЛЬДИИ
        # Итерируем по копии словаря values(), т.к. срабатывание может привести к удалению таймера из кеша
        for timer_data in list(guild_timers_cache.values()):
             # Таймер уже отфильтрован по guild_id, т.к. берется из guild_timers_cache
             # Проверяем только is_active (в кеше) и ends_at
             if timer_data.get('is_active', True) and timer_data.get('ends_at', float('inf')) <= current_game_time_for_guild: # Проверяем is_active и ends_at безопасно
                  # Проверяем наличие всех необходимых полей перед добавлением в список срабатывания
                  if 'id' in timer_data and 'type' in timer_data and 'ends_at' in timer_data:
                       # print(f"TimeManager: Timer '{timer_data.get('type', 'Unknown')}' with ID {timer_data.get('id', 'N/A')} for guild {guild_id_str} triggered at game time {current_game_time_for_guild:.2f}.") # Debug
                       timers_to_trigger.append(timer_data) # Добавляем весь словарь данных таймера
                       # Помечаем таймер как неактивный В КЕШЕ сразу, чтобы он не сработал повторно в этом тике
                       # Это важно, если _trigger_timer_callback сам не удаляет таймер немедленно.
                       timer_data['is_active'] = False # Устанавливаем флаг в кеше


                  else:
                       print(f"TimeManager: Warning: Skipping triggering invalid timer data in cache for guild {guild_id_str}: {timer_data}")


        # --- Вызываем callback'и для сработавших таймеров ---
        for timer_data in timers_to_trigger:
             # Вызываем callback'и ПОСЛЕ сбора списка таймеров к срабатыванию
             try:
                  # Вызываем вспомогательный метод для срабатывания
                  # Передаем guild_id и ВСЕ менеджеры/сервисы из kwargs process_tick
                  # _trigger_timer_callback принимает timer_type, callback_data, **kwargs
                  await self._trigger_timer_callback(timer_data['type'], timer_data.get('callback_data', {}), **kwargs) # Передаем kwargs из process_tick

                  # TODO: Удалить таймер из кеша и БД после успешного срабатывания (или пометить как выполненный в БД)
                  # Если is_active=False в кеше уже означает завершение,
                  # а remove_timer сам удаляет из БД, то здесь просто вызываем remove_timer.
                  # remove_timer принимает guild_id и timer_id
                  await self.remove_timer(guild_id_str, timer_data['id'])


             except Exception as e:
                  print(f"TimeManager: ❌ Error triggering timer callback for timer {timer_data.get('id', 'N/A')} ({timer_data.get('type', 'Unknown')}) for guild {guild_id_str}: {e}")
                  import traceback
                  print(traceback.format_exc())
                  # TODO: Логика обработки ошибки срабатывания таймера - возможно, пометить таймер как ошибочный в БД?

        # print(f"TimeManager: Tick processing finished for guild {guild_id_str}.")


    # --- Вспомогательный метод для срабатывания callback'ов таймеров ---
    # Этот метод принимает тип таймера и данные, а затем вызывает нужную логику,
    # используя менеджеры/сервисы, переданные в TimeManager (через __init__ или kwargs).
    # ИСПРАВЛЕНИЕ: Добавляем guild_id в сигнатуру, если логика callback'а зависит от гильдии
    # Callback'и обычно вызываются с контекстом WorldSimulationProcessor (kwargs).
    # WSP передает свой контекст в kwargs process_tick, а TimeManager передает этот kwargs дальше.
    # Значит, guild_id и все менеджеры УЖЕ ЕСТЬ в kwargs _trigger_timer_callback.
    async def _trigger_timer_callback(self, timer_type: str, callback_data: Dict[str, Any], **kwargs: Any) -> None:
        """
        Вызывает соответствующую логику при срабатывании таймера.
        :param timer_type: Тип сработавшего таймера.
        :param callback_data: Данные, связанные с таймером.
        :param kwargs: Дополнительные менеджеры/сервисы, переданные из WorldSimulationProcessor.
                      (Включает guild_id, менеджеры и т.д.)
        """
        # TODO: guild_id может быть нужен здесь, получить его из kwargs.get('guild_id')
        guild_id = kwargs.get('guild_id') # Получаем guild_id из контекста


        print(f"TimeManager: Triggering callback for timer type '{timer_type}' for guild {guild_id} with data {callback_data}.")


        if timer_type == 'event_stage_transition':
             # Пример: таймер для автоматического перехода стадии события
             event_id = callback_data.get('event_id')
             target_stage_id = callback_data.get('target_stage_id')
             if event_id and target_stage_id and guild_id is not None:
                  # Нужно получить EventManager, EventStageProcessor и другие зависимости из kwargs
                  event_manager = kwargs.get('event_manager')
                  event_stage_processor = kwargs.get('event_stage_processor')
                  send_callback_factory = kwargs.get('send_callback_factory')

                  if event_manager and event_stage_processor and send_callback_factory:
                       # EventManager.get_event должен принимать guild_id
                       event = event_manager.get_event(guild_id, event_id) # Передаем guild_id
                       if event:
                            print(f"TimeManager: Triggering auto-transition for event {event_id} to stage {target_stage_id} for guild {guild_id}...")
                            if event.channel_id is None:
                                 print(f"TimeManager: Warning: Cannot auto-advance event {event.id}. Event has no channel_id for notifications.")
                                 return # Не можем уведомить о переходе

                            event_channel_callback = send_callback_factory(event.channel_id)
                            # Вызываем EventStageProcessor
                            # StageProcessor.advance_stage ожидает context, который должен содержать guild_id
                            await event_stage_processor.advance_stage(
                                 event=event,
                                 target_stage_id=target_stage_id,
                                 # Передаем ВСЕ менеджеры/сервисы из kwargs TimeManager (это контекст из WSP)
                                 **kwargs, # Передаем весь контекст, включая guild_id и менеджеры
                                 # Перезаписываем callback на специфичный для канала события
                                 send_message_callback=event_channel_callback,
                                 transition_context={"trigger": "timer", "timer_type": timer_type, "guild_id": guild_id}
                             )
                            # TODO: Сохранить состояние игры после перехода (WorldSimulationProcessor делает это после World Tick)
                       else:
                            print(f"TimeManager: Error triggering event stage transition timer: Event {event_id} not found for guild {guild_id}.")
                  else:
                       print(f"TimeManager: Error triggering event stage transition timer for guild {guild_id}: Required managers/processors not available (Event/Stage/SendCallbackFactory).")
             elif guild_id is None:
                  print(f"TimeManager: Error triggering event stage transition timer for {event_id}: guild_id missing in context.")


        # TODO: Добавьте другие типы таймеров и логику их срабатывания
        # elif timer_type == 'status_effect_end':
        #      status_id = callback_data.get('status_id')
        #      if status_id and guild_id is not None and self._status_manager:
        #           # remove_status_effect должен принимать status_id, guild_id и context
        #           await self._status_manager.remove_status_effect(status_id, guild_id, **kwargs) # Передаем guild_id и контекст
        # elif timer_type == 'combat_end_delay':
        #      combat_id = callback_data.get('combat_id')
        #      if combat_id and guild_id is not None and self._combat_manager:
        #           # finalize_combat_outcome должен принимать combat_id, guild_id и context
        #           await self._combat_manager.finalize_combat_outcome(combat_id, guild_id, **kwargs) # Передаем guild_id и контекст

        else:
             print(f"TimeManager: Warning: Unhandled timer type '{timer_type}' triggered for guild {guild_id}.")


    # --- Методы персистентности (Используются PersistenceManager'ом) ---

    # ИСПРАВЛЕНИЕ: save_state должен принимать guild_id и **kwargs
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """
        Сохраняет состояние TimeManager (игровое время, активные таймеры) для определенной гильдии в БД.
        """
        print(f"TimeManager: Saving state for guild {guild_id}...")
        if self._db_adapter is None:
             print(f"TimeManager: Database adapter is not available. Skipping save for guild {guild_id}.")
             return

        guild_id_str = str(guild_id)

        try:
            # --- Сохранение текущего игрового времени для этой гильдии (в global_state) ---
            # Получаем текущее время для этой гильдии из кеша (обновлено в process_tick)
            current_game_time_for_guild = self._current_game_time.get(guild_id_str, 0.0)

            # Сохраняем текущее игровое время для этой гильдии в global_state
            await self._db_adapter.execute(
                "INSERT OR REPLACE INTO global_state (key, value) VALUES (?, ?)",
                (f'game_time_{guild_id_str}', json.dumps(current_game_time_for_guild)) # Ключ 'game_time_<guild_id>', значение как JSON
            )
            # execute уже коммитит (для этой одной операции)


            # --- Сохранение активных таймеров для этой гильдии (в таблице timers) ---
            # Удаляем ВСЕ таймеры для этой гильдии из БД перед вставкой
            await self._db_adapter.execute("DELETE FROM timers WHERE guild_id = ?", (guild_id_str,))
            # execute уже коммитит (для этой одной операции)

            # Вставляем все активные таймеры ИЗ КЕША, которые принадлежат этой гильдии
            # Получаем пер-гильдийный кеш таймеров
            guild_timers_cache = self._active_timers.get(guild_id_str, {})

            timers_to_save = [t for t in guild_timers_cache.values() if t.get('is_active', True)] # Фильтруем по is_active в кеше

            if timers_to_save:
                sql = '''
                    INSERT INTO timers (id, type, ends_at, callback_data, is_active, guild_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    -- TODO: Добавить другие колонки в SQL
                '''
                data_to_save = []
                for timer_data in timers_to_save:
                    # Убедимся, что guild_id присутствует в данных таймера
                    timer_guild_id = timer_data.get('guild_id')
                    if timer_guild_id is None or str(timer_guild_id) != guild_id_str:
                         print(f"TimeManager: Warning: Skipping save for timer {timer_data.get('id', 'N/A')} ({timer_data.get('type', 'Unknown')}) with missing or mismatched guild_id ({timer_guild_id}) in cache. Expected {guild_id_str}.")
                         continue # Пропускаем таймер с неправильной гильдией в кеше

                    data_to_save.append((
                        timer_data['id'],
                        timer_data['type'],
                        timer_data['ends_at'],
                        json.dumps(timer_data.get('callback_data', {})),
                        1, # is_active = 1 в БД для активных
                        timer_guild_id # <-- Параметр guild_id из данных таймера
                        # TODO: Добавить другие параметры в кортеж
                    ))
                # Используем execute_many для пакетной вставки таймеров
                if data_to_save: # Только если есть что сохранять
                     await self._db_adapter.execute_many(sql, data_to_save)
                     # execute_many коммитит сам

            # Note: При использовании execute и execute_many с авто-коммитом в каждом вызове,
            # нет необходимости в явном self._conn.commit() в конце save_state.

            print(f"TimeManager: Successfully saved state for guild {guild_id_str} (time: {current_game_time_for_guild:.2f}, timers: {len(timers_to_save)}).")

        except Exception as e:
            print(f"TimeManager: ❌ Error during saving state for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # При ошибке в execute_many, он сам откатит свою транзакцию.
            # Если ошибка в первом execute (game_time), только он откатится.
            # Явный rollback в конце save_state может откатить предыдущие операции,
            # если они не были закоммичены (но execute/execute_many авто-коммитят).
            # Если нужна атомарность всего save_state, нужно использовать одну транзакцию
            # через async with self._conn: или async with self._conn.cursor():
            # Для простоты пока оставим как есть с авто-коммитом по операциям.


    # ИСПРАВЛЕНИЕ: load_state должен принимать guild_id и **kwargs
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """
        Загружает состояние TimeManager (игровое время, активные таймеры) для определенной гильдии из БД в кеш.
        """
        print(f"TimeManager: Loading state for guild {guild_id}...")
        guild_id_str = str(guild_id)

        if self._db_adapter is None:
             print(f"TimeManager: Database adapter is not available. Loading placeholder state or leaving default for guild {guild_id_str}.")
             # Если игровое время пер-гильдийное, устанавливаем дефолтное время для этой гильдии
             if guild_id_str not in self._current_game_time: self._current_game_time[guild_id_str] = 0.0
             # Если таймеры пер-гильдийные, очищаем или инициализируем кеш для этой гильдии
             self._active_timers.pop(guild_id_str, None)
             self._active_timers[guild_id_str] = {}

             print(f"TimeManager: State is default after load (no DB adapter) for guild {guild_id_str}. Time = {self._current_game_time.get(guild_id_str, 0.0):.2f}, Timers = 0.")
             return

        try:
            # --- Загрузка текущего игрового времени для этой гильгии ---
            # Предполагаем, что время хранится per-guild в global_state с ключом 'game_time_<guild_id>'
            sql_time = '''SELECT value FROM global_state WHERE key = ?'''
            key = f'game_time_{guild_id_str}'
            row_time = await self._db_adapter.fetchone(sql_time, (key,))
            if row_time and row_time['value']:
                try:
                    loaded_time = json.loads(row_time['value'])
                    # ИСПРАВЛЕНИЕ: Если игровое время пер-гильдийное, сохраняем его в Dict
                    self._current_game_time[guild_id_str] = float(loaded_time)
                    print(f"TimeManager: Loaded game time for guild {guild_id_str}: {self._current_game_time[guild_id_str]:.2f}")

                except (json.JSONDecodeError, ValueError, TypeError) as e:
                     print(f"TimeManager: Error decoding or converting game time from DB for guild {guild_id_str}: {e}. Using default 0.0")
                     # Если игровое время пер-гильдийное: устанавливаем дефолт для этой гильдии
                     self._current_game_time[guild_id_str] = 0.0
            else:
                 print(f"TimeManager: No saved game time found for guild {guild_id_str}. Starting from 0.0.")
                 # Если игровое время пер-гильдийное: устанавливаем дефолт для этой гильгии
                 self._current_game_time[guild_id_str] = 0.0


            # --- Загрузка активных таймеров для этой гильдии ---
            # Очищаем кеш таймеров ДЛЯ ЭТОЙ ГИЛЬДИИ перед загрузкой
            self._active_timers.pop(guild_id_str, None)
            self._active_timers[guild_id_str] = {} # Создаем пустой кеш для этой гильдии
            guild_timers_cache = self._active_timers[guild_id_str] # Получаем ссылку на кеш гильдии


            # Выбираем таймеры ТОЛЬКО для этой гильдии и которые активны
            sql_timers = '''SELECT id, type, ends_at, callback_data, is_active, guild_id FROM timers WHERE guild_id = ? AND is_active = 1'''
            rows_timers = await self._db_adapter.fetchall(sql_timers, (guild_id_str,))

            if rows_timers:
                 print(f"TimeManager: Loaded {len(rows_timers)} active timers for guild {guild_id_str} from DB.")

                 for row in rows_timers:
                      try:
                           # Создаем словарь данных таймера из строки БД
                           timer_data: Dict[str, Any] = { # Явная аннотация
                                'id': row['id'],
                                'type': row['type'],
                                'ends_at': float(row['ends_at']), # assumed REAL type in DB, ensure float
                                'callback_data': json.loads(row['callback_data']) if row['callback_data'] else {},
                                'is_active': bool(row['is_active']), # Преобразуем 0/1 в bool
                                # ДОБАВЛЕНО: Загружаем guild_id из БД в данные таймера
                                'guild_id': row['guild_id'] # Сохраняем guild_id в данных таймера
                                # TODO: Загрузите другие поля (target_id, target_type и т.д.)
                           }
                           # Добавляем загруженный таймер в кеш ДЛЯ ЭТОЙ ГИЛЬДИИ
                           guild_timers_cache[timer_data['id']] = timer_data

                      except (json.JSONDecodeError, ValueError, TypeError) as e:
                           print(f"TimeManager: ❌ Error decoding or converting timer data from DB for ID {row.get('id', 'Unknown')} for guild {guild_id_str}: {e}. Skipping timer.")
                           import traceback
                           print(traceback.format_exc())


                 print(f"TimeManager: Successfully loaded {len(guild_timers_cache)} active timers into cache for guild {guild_id_str}.")

            else:
                 print(f"TimeManager: No active timers found in DB for guild {guild_id_str}.")


        except Exception as e:
            print(f"TimeManager: ❌ Error during loading state for guild {guild_id_str} from DB: {e}")
            import traceback
            print(traceback.format_exc())
            print(f"TimeManager: Loading failed for guild {guild_id_str}. State for this guild might be incomplete.")


    # --- Метод перестройки кешей (обычно простая заглушка для TimeManager) ---
    # ИСПРАВЛЕНИЕ: Добавляем guild_id и **kwargs
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
         """
         Перестраивает внутренние кеши TimeManager после загрузки для определенной гильдии.
         """
         print(f"TimeManager: Simulating rebuilding runtime caches for guild {guild_id}.")
         pass # TimeManager обычно не имеет сложных кешей, которые нужно перестраивать после загрузки.
             # Но метод должен существовать с правильной сигнатурой.


# Конец класса TimeManager
