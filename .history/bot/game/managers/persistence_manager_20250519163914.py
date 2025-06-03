# bot/game/managers/persistence_manager.py

print("DEBUG: persistence_manager.py module loaded.")

# Импорт базовых типов
from typing import Dict, Optional, Any, List, Set, Callable # Type hints
# Импорт TYPE_CHECKING
from typing import TYPE_CHECKING
# ИСПРАВЛЕНИЕ: Импорт Union для Tuple | List
from typing import Union, Tuple # Добавлен импорт Tuple

# Импорт async (используется в методах ниже)
import asyncio
import traceback # Для вывода трассировки ошибок

# TODO: Импорт адаптера базы данных - используем наш конкретный SQLite адаптер
# ИСПРАВЛЕНИЕ: Импортируем напрямую, так как используется в аннотациях БЕЗ строковых литералов
from bot.database.sqlite_adapter import SqliteAdapter


# Импорт ВСЕХ менеджеров, которые этот менеджер будет координировать для сохранения/загрузки.
# Используем ИМПОРТЫ В TYPE_CHECKING, чтобы избежать потенциальных циклических зависимостей,
# если какие-то из этих менеджеров, в свою очередь, импортируют PersistenceManager.
# Также это помогает Pylance с разрешением типов при использовании строковых литералов.
if TYPE_CHECKING:
    # TODO: Импорт адаптера базы данных (уже импортирован напрямую выше, нет необходимости здесь)
    # from bot.database.sqlite_adapter import SqliteAdapter # Не нужно

    # Обязательные менеджеры
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.location_manager import LocationManager

    # Опциональные менеджеры
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.crafting_manager import CraftingManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.party_manager import PartyManager
    # TODO: Добавьте другие менеджеры, если они хранят персистентное состояние

    # Определяем типы Callable для Type Checking, если они используются для аннотаций зависимостей-Callable
    # Например, если PersistenceManager получает SendCallbackFactory как зависимость в __init__ (маловероятно, но возможно)
    # SendCallbackFactory = Callable[[int], Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]]


# --- Импорты нужны при Runtime ---
# Для PersistenceManager крайне редко требуются runtime импорты менеджеров/адаптеров,
# т.к. он работает с инстансами, переданными через __init__.
# Здесь импортируются только вещи, нужные для логики самого PM, не для аннотаций типов зависимостей.


class PersistenceManager:
    """
    Координирует сохранение и загрузку состояния игры, делегируя работу
    специализированным менеджерам.
    Этот менеджер владеет ссылками на другие менеджеры, чье состояние он сохраняет/загружает.
    """
    def __init__(self,
                 # Принимаем зависимости, которые передает GameManager.
                 # Используйте СТРОКОВЫЕ ЛИТЕРАЛЫ для аннотаций всех инжектированных зависимостей.
                 # Исключение: db_adapter, так как он импортирован напрямую.

                 # ОБЯЗАТЕЛЬНЫЕ зависимости
                 event_manager: "EventManager", # Use string literal!
                 character_manager: "CharacterManager", # Use string literal!
                 location_manager: "LocationManager", # Use string literal!
                 # ИСПРАВЛЕНИЕ: Убираем строковый литерал, т.к. SqliteAdapter импортирован напрямую
                 db_adapter: Optional[SqliteAdapter] = None, # Use direct type hint!

                 # ОПЦИОНАЛЬНЫЕ зависимости
                 npc_manager: Optional["NpcManager"] = None, # Use string literal!
                 combat_manager: Optional["CombatManager"] = None, # Use string literal!
                 item_manager: Optional["ItemManager"] = None, # Use string literal!
                 time_manager: Optional["TimeManager"] = None, # Use string literal!
                 status_manager: Optional["StatusManager"] = None, # Use string literal!
                 crafting_manager: Optional["CraftingManager"] = None, # Use string literal!
                 economy_manager: Optional["EconomyManager"] = None, # Use string literal!
                 party_manager: Optional["PartyManager"] = None, # Use string literal!

                 # TODO: Добавьте другие менеджеры
                ):
        print("Initializing PersistenceManager...")
        # Сохраняем ССЫЛКИ на менеджеры и адаптер как АТРИБУТЫ экземпляра
        # Используем те же аннотации
        # ИСПРАВЛЕНИЕ: Убираем строковый литерал для db_adapter
        self._db_adapter: Optional[SqliteAdapter] = db_adapter # Use direct type hint!

        # Обязательные (строковые литералы)
        self._event_manager: "EventManager" = event_manager
        self._character_manager: "CharacterManager" = character_manager
        self._location_manager: "LocationManager" = location_manager

        # Опциональные (строковые литералы)
        self._npc_manager: Optional["NpcManager"] = npc_manager
        self._combat_manager: Optional["CombatManager"] = combat_manager
        self._item_manager: Optional["ItemManager"] = item_manager
        self._time_manager: Optional["TimeManager"] = time_manager
        self._status_manager: Optional["StatusManager"] = status_manager
        self._crafting_manager: Optional["CraftingManager"] = crafting_manager
        self._economy_manager: Optional["EconomyManager"] = economy_manager
        self._party_manager: Optional["PartyManager"] = party_manager
        # TODO: Сохраните другие менеджеры


        print("PersistenceManager initialized.")


    async def save_game_state(self, guild_ids: List[str], **kwargs: Any) -> None:
        """
        Координирует сохранение состояния всех менеджеров для указанных гильдий.
        Каждый менеджер отвечает за сохранение СВОИХ данных per-guild, используя db_adapter.
        Вызывается из GameManager или CommandRouter (GM команды).
        guild_ids: Список ID гильдий, для которых нужно сохранить состояние.
        kwargs: Дополнительный контекст (напр., time_manager, send_callback_factory) для передачи менеджерам.
        """
        if not guild_ids:
            print("PersistenceManager: No guild IDs provided for save. Skipping state save.")
            return

        print(f"PersistenceManager: Initiating game state save for {len(guild_ids)} guilds...")

        # Передаем менеджеры и контекст в kwargs для _call_manager_save
        call_kwargs = {**kwargs} # Копируем входящие kwargs

        if self._db_adapter is None:
            print("PersistenceManager: Database adapter not provided. Managers will simulate save (if they support no DB).")
            # В режиме без БД, просто вызываем save_state у менеджеров.
            for guild_id in guild_ids:
                 await self._call_manager_save(guild_id, **call_kwargs) # Передаем guild_id и kwargs
            print("PersistenceManager: Game state save simulation finished.")

        else:
            print("PersistenceManager: Database adapter found, attempting to save via managers.")
            # При использовании execute/execute_many с авто-коммитом в SqliteAdapter,
            # нет необходимости в явной общей транзакции здесь.
            # Каждый менеджер отвечает за атомарность своих операций.
            # Если нужна одна большая атомарная транзакция для ВСЕГО сохранения,
            # нужно убрать авто-коммит из execute/execute_many в SqliteAdapter
            # и использовать async with self._db_adapter: или async with self._db_adapter.cursor():
            # и явный commit/rollback здесь.
            # Для простоты текущей схемы, полагаемся на авто-коммит по операциям менеджеров.

            try:
                # Вызываем методы сохранения для каждого менеджера и каждой гильдии
                for guild_id in guild_ids:
                    await self._call_manager_save(guild_id, **call_kwargs) # Передаем guild_id и kwargs

                # Если все вызовы _call_manager_save завершились без проброса исключения,
                # считаем сохранение успешным на уровне делегирования.
                print("PersistenceManager: ✅ Game state save delegation finished (individual managers handle commit).")

            except Exception as e:
                print(f"PersistenceManager: ❌ Error during game state save delegation via managers: {e}")
                # Логируем ошибку, но не пытаемся откатывать общую транзакцию, т.к. ее нет в текущей схеме.
                import traceback
                print(traceback.format_exc())
                # TODO: Добавить логику обработки ошибок сохранения (оповещение GM, попытки повтора?)
                raise # Пробрасываем исключение, чтобы GameManager знал об ошибке


    # Вспомогательный метод для вызова save_state у всех менеджеров для одной гильдии
    # ИСПРАВЛЕНО: Сигнатура соответствует вызову
    async def _call_manager_save(self, guild_id: str, **kwargs: Any) -> None:
         """Вызывает save_state у каждого менеджера, который поддерживает персистентность, для одной гильдии."""
         # Передаем guild_id и kwargs дальше менеджерам
         call_kwargs = {'guild_id': guild_id, **kwargs}

         # Список кортежей (атрибут менеджера, имя ожидаемого метода)
         managers_to_save = [
             (self._event_manager, 'save_state'),
             (self._character_manager, 'save_state'),
             (self._location_manager, 'save_state'),
             (self._npc_manager, 'save_state'),
             (self._item_manager, 'save_state'),
             (self._combat_manager, 'save_state'),
             (self._time_manager, 'save_state'),
             (self._status_manager, 'save_state'),
             (self._crafting_manager, 'save_state'),
             (self._economy_manager, 'save_state'),
             (self._party_manager, 'save_state'),
             # TODO: Добавьте другие менеджеры здесь
         ]

         for manager_attr, method_name in managers_to_save:
              manager = manager_attr # type: Optional[Any]
              # Проверяем наличие менеджера и метода
              if manager and hasattr(manager, method_name):
                   try:
                       # Менеджер сам внутри должен игнорировать ненужные kwargs или рейзить ошибку, если mandatory args не переданы.
                       # Передаем словарь аргументов через **call_kwargs.
                       await getattr(manager, method_name)(**call_kwargs)
                   except Exception as e:
                       print(f"PersistenceManager: ❌ Error saving state for guild {guild_id} in manager {type(manager).__name__}: {e}")
                       # Не пробрасываем здесь, чтобы не остановить сохранение других менеджеров/гильдий.
                       import traceback
                       print(traceback.format_exc())

              # Опционально: логировать, если менеджер отсутствует, но ожидался
              # elif manager_attr: # Проверяем, что ссылка на менеджер вообще была (т.е. не None)
              #     print(f"PersistenceManager: Info: Optional manager {type(manager_attr).__name__} is None. Skipping save for guild {guild_id}.")


    async def load_game_state(self, guild_ids: List[str], **kwargs: Any) -> None:
        """
        Координирует загрузку состояния всех менеджеров для указанных гильдий при запуске бота.
        Каждый менеджер отвечает за загрузку СВОИХ данных per-guild, используя db_adapter.
        kwargs: Передаются в load_state менеджеров (напр., time_manager для StatusManager).
        Этот метод вызывается из GameManager или CommandRouter (GM команды).
        guild_ids: Список ID гильдий, для которых нужно загрузить состояние.
        """
        if not guild_ids:
            print("PersistenceManager: No guild IDs provided for load. Skipping state load.")
            # TODO: Решите, что делать, если нет гильдий. Возможно, бот должен загрузить глобальное состояние или упасть?
            # Пока просто ничего не делаем и возвращаемся. GameManager решит, что делать дальше.
            return

        print(f"PersistenceManager: Initiating game state load for {len(guild_ids)} guilds...")

        # Передаем менеджеры и контекст в kwargs для _call_manager_load и _call_manager_rebuild_caches
        call_kwargs = {**kwargs} # Копируем входящие kwargs


        if self._db_adapter is None: # Если адаптер БД не был предоставлен
            print("PersistenceManager: Database adapter not provided. Loading placeholder state (simulated loading).")
            # В режиме без БД, менеджеры должны загрузить свои in-memory заглушки.
            # Вызываем load_state (они должны сами симулировать/логировать) для каждой гильдии.
            for guild_id in guild_ids:
                 await self._call_manager_load(guild_id, **call_kwargs)
                 # В режиме заглушки rebuild_runtime_caches может быть вызван сразу после load_state для каждой гильдии
                 await self._call_manager_rebuild_caches(guild_id, **call_kwargs) # Вызываем rebuild после load каждой гильдии

            print("PersistenceManager: Game state load simulation finished.")


        else: # Если адаптер БД есть
            print("PersistenceManager: Database adapter found, attempting to load via managers.")
            # При загрузке, атомарность не так критична, как при сохранении.
            # Если загрузка одного менеджера упадет, это не повредит БД,
            # но может оставить состояние в памяти inconsistent.
            # Пока просто логируем ошибки загрузки каждого менеджера.

            try:
                 # Вызываем методы загрузки для каждой гильдии
                 for guild_id in guild_ids:
                     print(f"PersistenceManager: Loading state for guild {guild_id} via managers...")
                     await self._call_manager_load(guild_id, **call_kwargs) # Передаем guild_id и kwargs
                     print(f"PersistenceManager: Load delegation finished for guild {guild_id}.")


                 # После загрузки СОСТОЯНИЯ ВСЕХ ГИЛЬДИЙ всеми менеджерами, вызываем rebuild_runtime_caches для каждой гильдии
                 # Перестройка часто зависит от данных из РАЗНЫХ менеджеров для ОДНОЙ гильдии,
                 # поэтому лучше загрузить все состояние по гильдиям, а потом пройтись по rebuild.
                 print("PersistenceManager: Rebuilding runtime caches for loaded guilds...")
                 for guild_id in guild_ids:
                      print(f"PersistenceManager: Rebuilding caches for guild {guild_id} via managers...")
                      await self._call_manager_rebuild_caches(guild_id, **call_kwargs) # Передаем guild_id и kwargs
                      print(f"PersistenceManager: Rebuild delegation finished for guild {guild_id}.")


                 print("PersistenceManager: ✅ Game state loaded successfully (via managers).")

                 # Optional: Log counts after successful load for all guilds
                 # Это сложнее в многогильдийном режиме без агрегирующих методов в менеджерах.
                 # Например, CharacterManager в текущей версии кеширует персонажей по гильдиям.
                 # total_loaded_chars = sum(len(guild_chars) for guild_chars in self._character_manager._characters.values()) if self._character_manager and hasattr(self._character_manager, '_characters') else 0
                 # print(f"PersistenceManager: Loaded {total_loaded_chars} characters into cache (total across guilds).")


            except Exception as e:
                 print(f"PersistenceManager: ❌ CRITICAL ERROR during game state load via managers: {e}")
                 # КРИТИЧЕСКАЯ ОШИБКА ЗАГРУЗКИ - возможно, нужно остановить бот.
                 import traceback
                 print(traceback.format_exc())
                 # TODO: Добавить логику обработки критических ошибок загрузки (оповещение GM, режим обслуживания?)
                 raise # Пробрасываем исключение, чтобы GameManager знал об ошибке


    # Вспомогательный метод для вызова load_state у всех менеджеров для одной гильдии
    # ИСПРАВЛЕНО: Сигнатура соответствует вызову
    async def _call_manager_load(self, guild_id: str, **kwargs: Any) -> None:
         """Вызывает load_state у каждого менеджера, который поддерживает персистентность, для одной гильдии."""
         # Передаем guild_id и kwargs дальше менеджерам
         call_kwargs = {'guild_id': guild_id, **kwargs}

         # Список кортежей (атрибут менеджера, имя ожидаемого метода)
         managers_to_load = [
             (self._event_manager, 'load_state'),
             (self._character_manager, 'load_state'),
             (self._location_manager, 'load_state'),
             (self._npc_manager, 'load_state'),
             (self._item_manager, 'load_state'),
             (self._combat_manager, 'load_state'),
             (self._time_manager, 'load_state'),
             (self._status_manager, 'load_state'),
             (self._crafting_manager, 'load_state'),
             (self._economy_manager, 'load_state'),
             (self._party_manager, 'load_state'),
             # TODO: Добавьте другие менеджеры здесь
         ]

         for manager_attr, method_name in managers_to_load:
              manager = manager_attr # type: Optional[Any]
              # Проверяем наличие менеджера и метода
              if manager and hasattr(manager, method_name):
                   try:
                        # Менеджер сам внутри должен игнорировать ненужные kwargs или рейзить ошибку.
                        # Мы передаем guild_id и все kwargs.
                        # Передаем словарь аргументов через **call_kwargs.
                        await getattr(manager, method_name)(**call_kwargs)
                   except Exception as e:
                       print(f"PersistenceManager: ❌ Error loading state for guild {guild_id} in manager {type(manager).__name__}: {e}")
                       # Не пробрасываем здесь, чтобы не остановить загрузку других менеджеров/гильдий.
                       import traceback
                       print(traceback.format_exc())

              # Опционально: логировать, если менеджер отсутствует, но ожидался
              # elif manager_attr:
              #     print(f"PersistenceManager: Info: Optional manager {type(manager_attr).__name__} is None. Skipping load for guild {guild_id}.")


    # Вспомогательный метод для вызова rebuild_runtime_caches у всех менеджеров для одной гильдии
    # ИСПРАВЛЕНО: Сигнатура соответствует вызову
    async def _call_manager_rebuild_caches(self, guild_id: str, **kwargs: Any) -> None:
         """Вызывает rebuild_runtime_caches у каждого менеджера, который поддерживает его, для одной гильдии."""
         # Передаем guild_id и kwargs дальше менеджерам
         call_kwargs = {'guild_id': guild_id, **kwargs}

         # Список кортежей (атрибут менеджера, имя ожидаемого метода)
         managers_to_rebuild = [
             (self._event_manager, 'rebuild_runtime_caches'),
             (self._character_manager, 'rebuild_runtime_caches'),
             (self._location_manager, 'rebuild_runtime_caches'),
             (self._npc_manager, 'rebuild_runtime_caches'),
             (self._item_manager, 'rebuild_runtime_caches'),
             (self._combat_manager, 'rebuild_runtime_caches'),
             (self._time_manager, 'rebuild_runtime_caches'),
             (self._status_manager, 'rebuild_runtime_caches'),
             (self._crafting_manager, 'rebuild_runtime_caches'),
             (self._economy_manager, 'rebuild_runtime_caches'),
             (self._party_manager, 'rebuild_runtime_caches'),
             # TODO: Добавьте другие менеджеры здесь
         ]

         for manager_attr, method_name in managers_to_rebuild:
              manager = manager_attr # type: Optional[Any]
              # Проверяем наличие менеджера и метода
              if manager and hasattr(manager, method_name):
                   try:
                       # Менеджер сам внутри должен использовать guild_id и kwargs для перестройки.
                       # Передаем словарь аргументов через **call_kwargs.
                       await getattr(manager, method_name)(**call_kwargs)
                   except Exception as e:
                       print(f"PersistenceManager: ❌ Error rebuilding caches for guild {guild_id} in manager {type(manager).__name__}: {e}")
                       # Не пробрасываем здесь, чтобы не остановить перестройку других менеджеров/гильдий.
                       import traceback
                       print(traceback.format_exc())

              # Опционально: логировать, если менеджер отсутствует, но ожидался
              # elif manager_attr:
              #     print(f"PersistenceManager: Info: Optional manager {type(manager_attr).__name__} is None. Skipping rebuild for guild {guild_id}.")


    # ... (Дополнительные вспомогательные методы остаются прежними) ...

# Конец класса PersistenceManager

# TODO: Здесь могут быть другие классы менеджеров или хелперы, если они не являются частью GameManager.

print("DEBUG: persistence_manager.py module loaded.")
