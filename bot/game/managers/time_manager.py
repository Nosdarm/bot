# bot/game/managers/time_manager.py

# --- Импорты ---
import asyncio
import traceback
import json # Нужен для сохранения/загрузки словарей/списков как JSON строк в БД
import uuid # Нужен для генерации UUID для таймеров
from typing import Optional, Dict, Any, List, Callable, Awaitable # Type hints

# TODO: Импортируйте модели, если TimeManager их использует (например, для аннотаций)
# from bot.game.models.game_time import GameTime # Если у вас есть модель для времени

# TODO: Импорт адаптера БД - используем наш конкретный SQLite адаптер
from bot.database.sqlite_adapter import SqliteAdapter # <-- Используем наш адаптер

# TODO: Импорт других менеджеров, если TimeManager их использует в своих методах
# Например, менеджеры, методы которых вызываются при срабатывании таймеров
# from bot.game.managers.event_manager import EventManager # Если таймер запускает переход стадии события (WorldSimulationProcessor вызывает EventStageProcessor, но TimeManager может получить EventManager через kwargs)
# from bot.game.managers.status_manager import StatusManager # Если таймер снимает статус
# from bot.game.managers.combat_manager import CombatManager # Если таймер влияет на бой


# TODO: Определите Type Alias для данных callback'а таймера, если они специфичны
# TimerCallbackData = Dict[str, Any]


class TimeManager:
    """
    Менеджер для управления игровым временем и таймерами.
    Отвечает за обновление времени, срабатывание таймеров и их персистентность в БД.
    """
    def __init__(self,
                 # Принимаем зависимости, которые передает GameManager.
                 db_adapter: Optional[SqliteAdapter] = None, # <-- Указываем конкретный тип адаптера
                 settings: Optional[Dict[str, Any]] = None, # Настройки (напр., начальное время, коэффициент времени)

                 # TODO: Добавьте другие зависимости, если TimeManager их требует и GameManager их передает.
                 # event_manager: Optional['EventManager'] = None, # Нужен для таймеров событий
                 # status_manager: Optional['StatusManager'] = None, # Нужен для таймеров статусов
                 # combat_manager: Optional['CombatManager'] = None, # Нужен для таймеров боя
                 ):
        print("Initializing TimeManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        # TODO: Сохраните другие зависимости
        # self._event_manager = event_manager
        # self._status_manager = status_manager
        # self._combat_manager = combat_manager


        # --- Хранилище для игрового времени и активных таймеров ---
        self._current_game_time: float = 0.0 # Игровое время в каком-то масштабе (секунды, минуты, тики)
        # Храним активные таймеры в словаре {timer_id: timer_data}
        # timer_data может быть словарем с полями из таблицы 'timers', например:
        # {'id': ..., 'type': ..., 'ends_at': ..., 'callback_data': {...}, 'is_active': True}
        self._active_timers: Dict[str, Dict[str, Any]] = {}


        print("TimeManager initialized.")

    # --- Методы получения времени и таймеров ---

    def get_current_game_time(self) -> float:
         """Возвращает текущее игровое время."""
         return self._current_game_time

    # TODO: Добавьте метод для получения конкретного таймера

    # --- Методы управления таймерами (интеграция с БД) ---

    async def add_timer(self, timer_type: str, duration: float, callback_data: Dict[str, Any]) -> Optional[str]:
        """
        Добавляет новый таймер, который сработает через указанное игровое время duration.
        Сохраняет его в БД и добавляет в кеш активных таймеров.
        :param timer_type: Строковый тип таймера (для идентификации логики срабатывания).
        :param duration: Длительность в игровом времени до срабатывания.
        :param callback_data: Словарь данных, необходимых при срабатывании (JSON-сериализуемый).
        :return: ID созданного таймера или None при ошибке.
        """
        print(f"TimeManager: Adding timer of type '{timer_type}' with duration {duration}.")

        if self._db_adapter is None:
             print("TimeManager: Error adding timer: Database adapter is not available.")
             return None

        if duration <= 0:
             print(f"TimeManager: Warning: Attempted to add timer with non-positive duration ({duration}). Sparing immediately.")
             # TODO: Возможно, выполнить логику срабатывания callback_data сразу же?
             # await self._trigger_timer_callback(timer_type, callback_data, **kwargs_from_tick_or_caller) # Нужны kwargs!
             return None # Не добавляем таймер с нулевой/отрицательной длительностью


        timer_id = str(uuid.uuid4()) # Генерируем ID для нового таймера
        ends_at = self._current_game_time + duration # Рассчитываем время срабатывания

        new_timer_data = {
            'id': timer_id,
            'type': timer_type,
            'ends_at': ends_at,
            'callback_data': callback_data,
            'is_active': True,
            # TODO: Добавьте другие поля для Timer
        }

        try:
            # --- Сохранение в БД через адаптер ---
            sql = '''
                INSERT INTO timers (id, type, ends_at, callback_data, is_active)
                VALUES (?, ?, ?, ?, ?)
            '''
            params = (
                new_timer_data['id'], new_timer_data['type'], new_timer_data['ends_at'],
                json.dumps(new_timer_data['callback_data']), 1 if new_timer_data['is_active'] else 0
                # TODO: Добавьте другие параметры
            )

            await self._db_adapter.execute(sql, params)
            await self._db_adapter.commit() # Фиксируем

            print(f"TimeManager: Timer '{timer_type}' added, ends at {ends_at:.2f}, saved to DB with ID {timer_id}.")

            # --- Добавление в кеш после успешного сохранения ---
            self._active_timers[timer_id] = new_timer_data
            print(f"TimeManager: Timer {timer_id} added to memory cache.")


            return timer_id # Возвращаем ID нового таймера

        except Exception as e:
            print(f"TimeManager: ❌ Error adding or saving timer to DB: {e}")
            import traceback
            print(traceback.format_exc())
            if self._db_adapter: await self._db_adapter.rollback()
            return None


    async def remove_timer(self, timer_id: str) -> None:
        """
        Удаляет таймер по ID из кеша и БД.
        """
        print(f"TimeManager: Removing timer {timer_id}...")
        timer_id_str = str(timer_id)

        if timer_id_str not in self._active_timers:
             print(f"TimeManager: Warning: Attempted to remove non-existent or inactive timer {timer_id}.")
             # Проверяем, возможно, нужно удалить его из БД, даже если нет в кеше активных
             pass # Продолжаем удаление из БД


        try:
            # --- Удаляем из БД ---
            if self._db_adapter:
                sql = 'DELETE FROM timers WHERE id = ?'
                await self._db_adapter.execute(sql, (timer_id_str,))
                await self._db_adapter.commit() # Фиксируем удаление
                print(f"TimeManager: Timer {timer_id} deleted from DB.")
            else:
                print(f"TimeManager: No DB adapter. Simulating delete from DB for {timer_id}.")

            # --- Удаляем из кеша ---
            self._active_timers.pop(timer_id_str, None)
            print(f"TimeManager: Timer {timer_id} removed from cache.")

        except Exception as e:
            print(f"TimeManager: ❌ Error removing timer {timer_id}: {e}")
            import traceback
            print(traceback.format_exc())
            if self._db_adapter: await self._db_adapter.rollback()


    # TODO: Метод обновления таймера (если его состояние может меняться, кроме ends_at)
    # async def update_timer(self, timer_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]: ... # Обновляет в кеше И БД


    # Метод обработки тика (используется WorldSimulationProcessor)
    async def process_tick(self, game_time_delta: Any, **kwargs) -> None:
        """
        Обрабатывает тик игрового времени.
        Обновляет текущее время, проверяет и срабатывает активные таймеры.
        Принимает game_time_delta и менеджеры/сервисы через kwargs для вызова callback'ов.
        """
        # print(f"TimeManager: Processing tick with delta {game_time_delta}...") # Бывает шумно

        if self._db_adapter is None:
             print("TimeManager: Skipping tick processing (no DB adapter). Cannot update time or check timers.")
             return

        # --- Обновляем текущее игровое время ---
        self._current_game_time += float(game_time_delta) # Убедимся, что это число
        # TODO: Сохранять текущее время в БД при каждом тике может быть излишне.
        # Можно сохранять его реже (напр., при авто-сохранении или завершении бота)
        # или сохранять его в отдельной таблице global_state.

        timers_to_trigger: List[str] = []

        # --- Проверяем и срабатываем активные таймеры ---
        # Итерируем по копии списка, потому что можем удалять элементы во время итерации через remove_timer
        # Сортируем по времени срабатывания, чтобы обрабатывать таймеры в хронологическом порядке
        sorted_active_timers = sorted(self._active_timers.values(), key=lambda t: t['ends_at'])

        for timer_data in sorted_active_timers:
             if timer_data['is_active'] and timer_data['ends_at'] <= self._current_game_time:
                  print(f"TimeManager: Timer '{timer_data['type']}' with ID {timer_data['id']} triggered at game time {self._current_game_time:.2f}.")
                  timers_to_trigger.append(timer_data['id'])
                  # TODO: Пометить таймер как неактивный в кеше сразу, чтобы он не сработал повторно в этом же тике
                  timer_data['is_active'] = False
                  # TODO: Обновить статус таймера в БД (is_active = False)
                  # await self._db_adapter.execute('UPDATE timers SET is_active = ? WHERE id = ?', (0, timer_data['id']))


        # --- Вызываем callback'и для сработавших таймеров ---
        # Вызываем callback'и ПОСЛЕ сбора списка таймеров к срабатыванию,
        # чтобы избежать изменения self._active_timers во время итерации.
        for timer_id in timers_to_trigger:
             timer_data = self._active_timers.get(timer_id) # Получаем данные из кеша (может быть уже удален, если один таймер удалил другой)
             if timer_data and not timer_data['is_active']: # Проверяем, что еще в кеше и помечен неактивным
                  try:
                       # TODO: Реализовать логику вызова callback'а на основе timer_data['type'] и timer_data['callback_data']
                       # Используйте переданные менеджеры/сервисы из kwargs
                       print(f"TimeManager: Triggering callback for timer {timer_id} ({timer_data['type']})...")
                       await self._trigger_timer_callback(timer_data['type'], timer_data['callback_data'], **kwargs) # Вызываем вспомогательный метод

                       # TODO: Удалить таймер из кеша и БД после успешного срабатывания (или пометить как выполненный)
                       # await self.remove_timer(timer_id) # Если таймеры одноразовые

                  except Exception as e:
                       print(f"TimeManager: ❌ Error triggering timer callback for timer {timer_id} ({timer_data['type']}): {e}")
                       import traceback
                       print(traceback.format_exc())
                       # TODO: Логика обработки ошибки срабатывания таймера

        # TODO: Сохранить текущее игровое время в БД, если оно хранится в global_state
        # if self._db_adapter:
        #      try:
        #           await self._db_adapter.execute("INSERT OR REPLACE INTO global_state (key, value) VALUES (?, ?)", ('game_time', json.dumps(self._current_game_time)))
        #           await self._db_adapter.commit()
        #           # print("TimeManager: Game time saved.") # Отладочный
        #      except Exception as e:
        #           print(f"TimeManager: Error saving game time: {e}")


        # print("TimeManager: Tick processing finished.")


    # --- Вспомогательный метод для срабатывания callback'ов таймеров ---
    # Этот метод принимает тип таймера и данные, а затем вызывает нужную логику,
    # используя менеджеры/сервисы, переданные в TimeManager (через __init__ или kwargs).
    async def _trigger_timer_callback(self, timer_type: str, callback_data: Dict[str, Any], **kwargs) -> None:
        """
        Вызывает соответствующую логику при срабатывании таймера.
        :param timer_type: Тип сработавшего таймера.
        :param callback_data: Данные, связанные с таймером.
        :param kwargs: Дополнительные менеджеры/сервисы, переданные из WorldSimulationProcessor.
        """
        print(f"TimeManager: Triggering callback for timer type '{timer_type}' with data {callback_data}.")

        # TODO: Здесь реализуйте логику вызова других менеджеров/процессоров в зависимости от timer_type
        # Используйте self._... атрибуты или kwargs.get('manager_name').

        if timer_type == 'event_stage_transition':
             # Пример: таймер для автоматического перехода стадии события
             event_id = callback_data.get('event_id')
             target_stage_id = callback_data.get('target_stage_id')
             if event_id and target_stage_id:
                  # Нужно получить EventManager, EventStageProcessor и другие зависимости, чтобы сделать переход
                  event_manager = kwargs.get('event_manager')
                  event_stage_processor = kwargs.get('event_stage_processor')
                  send_callback_factory = kwargs.get('send_callback_factory') # Фабрика callback'ов

                  if event_manager and event_stage_processor and send_callback_factory:
                       event = event_manager.get_event(event_id)
                       if event:
                            print(f"TimeManager: Triggering auto-transition for event {event_id} to stage {target_stage_id}...")
                            event_channel_callback = send_callback_factory(event.channel_id) # Получаем callback для канала события
                            # Вызываем EventStageProcessor
                            await event_stage_processor.advance_stage(
                                 event=event, # Передаем объект события
                                 target_stage_id=target_stage_id,
                                 # TODO: Передайте все необходимые зависимости StageProcessor'у из kwargs TimeManager
                                 character_manager=kwargs.get('character_manager'), loc_manager=kwargs.get('location_manager'),
                                 rule_engine=kwargs.get('rule_engine'), openai_service=kwargs.get('openai_service'),
                                 send_message_callback=event_channel_callback, # Callback для канала события
                                 npc_manager=kwargs.get('npc_manager'), combat_manager=kwargs.get('combat_manager'),
                                 item_manager=kwargs.get('item_manager'), time_manager=kwargs.get('time_manager'),
                                 status_manager=kwargs.get('status_manager'),
                                 transition_context={"trigger": "timer", "timer_type": timer_type} # Контекст перехода
                             )
                            # TODO: Сохранить состояние игры после перехода (WorldSimulationProcessor делает это после World Tick)
                       else:
                            print(f"TimeManager: Error triggering event stage transition timer: Event {event_id} not found.")
                  else:
                       print("TimeManager: Error triggering event stage transition timer: Required managers/processors not available (Event/Stage/SendCallbackFactory).")

        # TODO: Добавьте другие типы таймеров и логику их срабатывания
        # elif timer_type == 'status_effect_end':
        #      status_id = callback_data.get('status_id')
        #      if status_id and self._status_manager:
        #           await self._status_manager.remove_status_effect(status_id) # Снимаем статус
        # elif timer_type == 'combat_end_delay':
        #      combat_id = callback_data.get('combat_id')
        #      if combat_id and self._combat_manager:
        #           await self._combat_manager.finalize_combat_outcome(combat_id, **kwargs) # Завершаем бой после задержки

        else:
             print(f"TimeManager: Warning: Unhandled timer type '{timer_type}' triggered.")


    # --- Методы персистентности (Используются PersistenceManager'ом) ---

    async def save_state(self) -> None:
        """
        Сохраняет состояние TimeManager (игровое время, активные таймеры) в БД.
        """
        print("TimeManager: Saving state...")
        if self._db_adapter is None:
             print("TimeManager: Database adapter is not available. Skipping save.")
             return

        try:
            # --- Сохранение текущего игрового времени (в global_state) ---
            # Сохраняем только если оно есть
            if self._current_game_time is not None:
                 await self._db_adapter.execute(
                     "INSERT OR REPLACE INTO global_state (key, value) VALUES (?, ?)",
                     ('game_time', json.dumps(self._current_game_time)) # Ключ 'game_time', значение как JSON
                 )

            # --- Сохранение активных таймеров (в таблице timers) ---
            # Удаляем все текущие активные таймеры из БД перед вставкой (проще, чем искать изменения)
            await self._db_adapter.execute("DELETE FROM timers WHERE is_active = 1")

            # Вставляем все таймеры из кеша как активные
            for timer_data in self._active_timers.values():
                 # Убедимся, что сохраняем только активные или все, как нужно.
                 # В кеше _active_timers должны быть только активные.
                 sql = '''
                     INSERT INTO timers (id, type, ends_at, callback_data, is_active)
                     VALUES (?, ?, ?, ?, ?)
                 '''
                 params = (
                     timer_data['id'], timer_data['type'], timer_data['ends_at'],
                     json.dumps(timer_data.get('callback_data', {})), # callback_data как JSON
                     1 #is_active = 1
                 )
                 await self._db_adapter.execute(sql, params)

            await self._db_adapter.commit() # Фиксируем все изменения
            print(f"TimeManager: Successfully saved state (time: {self._current_game_time:.2f}, timers: {len(self._active_timers)}).")

        except Exception as e:
            print(f"TimeManager: ❌ Error during saving state: {e}")
            import traceback
            print(traceback.format_exc())
            if self._db_adapter: await self._db_adapter.rollback()
            # TODO: Логика обработки ошибки сохранения


    async def load_state(self) -> None:
        """
        Загружает состояние TimeManager (игровое время, активные таймеры) из БД в кеш.
        """
        print("TimeManager: Loading state...")
        # Сбрасываем кеш перед загрузкой
        self._current_game_time = 0.0
        self._active_timers = {}

        if self._db_adapter is None:
             print("TimeManager: Database adapter is not available. Loading placeholder state or leaving default.")
             # TODO: Загрузить тестовые данные, если нужно для работы без БД
             # self._current_game_time = 100.0 # Пример
             print("TimeManager: State is default after load (no DB adapter).")
             return

        try:
            # --- Загрузка текущего игрового времени ---
            sql_time = '''SELECT value FROM global_state WHERE key = 'game_time' '''
            row_time = await self._db_adapter.fetchone(sql_time)
            if row_time and row_time['value']:
                try:
                    loaded_time = json.loads(row_time['value'])
                    self._current_game_time = float(loaded_time) # Убедимся, что это число
                    print(f"TimeManager: Loaded game time: {self._current_game_time:.2f}")
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                     print(f"TimeManager: Error decoding or converting game time from DB: {e}. Using default 0.0")
                     self._current_game_time = 0.0
            else:
                 print("TimeManager: No saved game time found. Starting from 0.0.")
                 self._current_game_time = 0.0 # Дефолтное значение


            # --- Загрузка активных таймеров ---
            sql_timers = '''SELECT id, type, ends_at, callback_data, is_active FROM timers WHERE is_active = 1'''
            rows_timers = await self._db_adapter.fetchall(sql_timers)

            if rows_timers:
                 print(f"TimeManager: Loaded {len(rows_timers)} active timers from DB.")
                 for row in rows_timers:
                      try:
                           # Создаем словарь данных таймера из строки БД
                           timer_data = {
                                'id': row['id'],
                                'type': row['type'],
                                'ends_at': row['ends_at'], # assumed REAL type in DB
                                'callback_data': json.loads(row['callback_data']) if row['callback_data'] else {},
                                'is_active': bool(row['is_active']) # Преобразуем 0/1 в bool
                                # TODO: Загрузите другие поля
                           }
                           # Добавляем загруженный таймер в кеш
                           self._active_timers[timer_data['id']] = timer_data
                      except (json.JSONDecodeError, ValueError, TypeError) as e:
                           print(f"TimeManager: ❌ Error decoding or converting timer data from DB for ID {row.get('id', 'Unknown')}: {e}. Skipping timer.")
                           import traceback
                           print(traceback.format_exc())


                 print(f"TimeManager: Successfully loaded {len(self._active_timers)} active timers into cache.")

            else:
                 print("TimeManager: No active timers found in DB.")


        except Exception as e:
            print(f"TimeManager: ❌ Error during loading state from DB: {e}")
            import traceback
            print(traceback.format_exc())
            print("TimeManager: Loading failed. State remains default.")


    # --- Метод перестройки кешей (обычно простая заглушка для TimeManager) ---
    def rebuild_runtime_caches(self) -> None:
         """
         Перестраивает внутренние кеши после загрузки (обычно не применимо к TimeManager).
         """
         print("TimeManager: Simulating rebuilding runtime caches.")
         pass # TimeManager обычно не имеет сложных кешей, которые нужно перестраивать после загрузки.


# Конец класса TimeManager