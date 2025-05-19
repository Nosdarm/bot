# bot/game/managers/persistence_manager.py

import asyncio # Нужен для await
import traceback # Для вывода трассировки ошибок
# Импорт базовых типов
from typing import Dict, Optional, Any, List, Set, Callable # Type hints
# Импорт TYPE_CHECKING
from typing import TYPE_CHECKING


# Импорт ВСЕХ менеджеров, которые этот менеджер будет координировать для сохранения/загрузки.
# Используем ИМПОРТЫ В TYPE_CHECKING, чтобы избежать потенциальных циклических зависимостей,
# если какие-то из этих менеджеров, в свою очередь, импортируют PersistenceManager.
if TYPE_CHECKING:
    # TODO: Импорт адаптера базы данных
    from bot.database.sqlite_adapter import SqliteAdapter

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
    from bot.game.managers.crafting_manager import CraftingManager # Если есть
    from bot.game.managers.economy_manager import EconomyManager # Если есть
    from bot.game.managers.party_manager import PartyManager # Если есть
    # TODO: Добавьте другие менеджеры, если они хранят персистентное состояние


# --- Импорты нужны при Runtime (крайне редко для PM, т.к. он работает с инстансами, а не классами) ---
# Если вы используете классы менеджеров для isinstance проверок, их нужно импортировать здесь.
# В вашем коде нет instanceof проверок на менеджерах в PM, поэтому runtime импорты классов не нужны.

# TODO: Импорт адаптера базы данных, если используется для реальной персистентности
# Если SqliteAdapter проинжектирован как инстанс, его класс не нужен для runtime импорта в PM.
# Но его класс может быть нужен для TYPE_CHECKING, если вы используете его в аннотациях.
# Судя по __init__, он используется в аннотации Optional[SqliteAdapter], но без строкового литерала.
# Если вы НЕ используете строковый литерал в __init__, SqliteAdapter должен быть импортирован здесь для Runtime.
# Давайте оставим его здесь для обратной совместимости с предыдущими версиями, но рекомендуется использовать строковые литералы.
# from bot.database.sqlite_adapter import SqliteAdapter # Если используется в __init__ без " "


print("DEBUG: persistence_manager.py module loaded.")


class PersistenceManager:
    """
    Координирует сохранение и загрузку состояния игры, делегируя работу
    специализированным менеджерам.
    Этот менеджер владеет ссылками на другие менеджеры, чье состояние он сохраняет/загружает.
    """
    def __init__(self,
                 # Принимаем зависимости, которые передает GameManager.
                 # Используйте строковые литералы для инжектированных зависимостей, если импорт в TYPE_CHECKING.
                 # Если импорт прямой (например, SqliteAdapter выше), строковый литерал не нужен.
                 # Рекомендуется использовать строковые литералы и импорт в TYPE_CHECKING для всех зависимостей.

                 # ОБЯЗАТЕЛЬНЫЕ зависимости
                 # event_manager: EventManager, # Прямой импорт, без " "
                 # character_manager: CharacterManager, # Прямой импорт, без " "
                 # location_manager: LocationManager, # Прямой импорт, без " "
                 # db_adapter: Optional[SqliteAdapter] = None, # Прямой импорт SqliteAdapter, без " "

                 # Давайте перейдем к использованию строковых литералов для всех зависимостей для консистентности
                 event_manager: "EventManager", # Use string literal!
                 character_manager: "CharacterManager", # Use string literal!
                 location_manager: "LocationManager", # Use string literal!
                 db_adapter: Optional["SqliteAdapter"] = None, # Use string literal!

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
        self._db_adapter: Optional["SqliteAdapter"] = db_adapter # Сохраняем адаптер БД

        # Сохраняем ССЫЛКИ на менеджеры как АТРИБУТЫ экземпляра
        # Используем те же аннотации, что и в сигнатуре __init__
        self._event_manager: "EventManager" = event_manager
        self._character_manager: "CharacterManager" = character_manager
        self._location_manager: "LocationManager" = location_manager # Сохраняем, даже если он только загружает статику

        # Опциональные
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


    async def save_game_state(self, guild_ids: List[str], **kwargs: Any) -> None: # Добавили guild_ids и **kwargs
        """
        Координирует сохранение состояния всех менеджеров для указанных гильдий.
        Каждый менеджер отвечает за сохранение СВОИХ данных per-guild, используя db_adapter.
        """
        print(f"PersistenceManager: Initiating game state save for {len(guild_ids)} guilds...")

        if self._db_adapter is None: # Если адаптер БД не был предоставлен
            print("PersistenceManager: Database adapter not provided. Simulating state save (managers will log their saves).")
            # В режиме без БД, просто вызываем save_state (они должны сами симулировать/логировать) для каждой гильдии.
            # Передаем guild_id и kwargs в save_state менеджеров.
            for guild_id in guild_ids:
                await self._call_manager_save(guild_id, **kwargs) # Используем вспомогательный метод

        else: # Если адаптер БД есть, выполняем сохранение с транзакцией
            print("PersistenceManager: Database adapter found, attempting to save via managers.")
            try:
                # Запускаем транзакцию
                # await self._db_adapter.begin_transaction() # Если адаптер имеет begin_transaction

                # Вызываем методы сохранения для каждого менеджера и каждой гильдии
                # Менеджеры сами взаимодействуют с self._db_adapter для выполнения записи.
                for guild_id in guild_ids:
                    await self._call_manager_save(guild_id, **kwargs) # Используем вспомогательный метод

                # Фиксируем транзакцию после успешного сохранения всех гильдий/менеджеров.
                await self._db_adapter.commit()
                print("PersistenceManager: ✅ Game state saved successfully (via managers).")

            except Exception as e:
                print(f"PersistenceManager: ❌ Error during game state save via managers: {e}")
                # Важно: при ошибке сохранения - откатить транзакцию!
                if self._db_adapter:
                     # Если адаптер имеет rollback, используем его
                     if hasattr(self._db_adapter, 'rollback'):
                        await self._db_adapter.rollback()
                     else:
                         print("PersistenceManager: Warning: Database adapter has no 'rollback' method.")

                import traceback
                print(traceback.format_exc())
                # TODO: Добавить логику обработки ошибок сохранения (оповещение GM, попытки повтора?)
                raise # Пробрасываем исключение, чтобы GameManager знал об ошибке


    # Вспомогательный метод для вызова save_state у всех менеджеров для одной гильдии
    async def _call_manager_save(self, guild_id: str, **kwargs: Any) -> None: # Добавили guild_id и **kwargs
         """Вызывает save_state у каждого менеджера, который поддерживает персистентность, для одной гильдии."""
         # Передаем kwargs дальше менеджерам
         call_kwargs = {'guild_id': guild_id, **kwargs}

         # Список кортежей (атрибут менеджера, имя ожидаемого метода)
         managers_to_save = [
             (self._event_manager, 'save_state'), # Переименован load_all_events/save_all_events -> load_state/save_state
             (self._character_manager, 'save_state'), # Переименован save_all_characters -> save_state
             (self._location_manager, 'save_state'), # Если LocationManager сохраняет динамику
             (self._npc_manager, 'save_state'),
             (self._item_manager, 'save_state'),
             (self._combat_manager, 'save_state'),
             (self._time_manager, 'save_state'), # TimeManager может сохранять глобальное время, guild_id может игнорировать
             (self._status_manager, 'save_state'),
             (self._crafting_manager, 'save_state'),
             (self._economy_manager, 'save_state'),
             (self._party_manager, 'save_state'),
             # TODO: Добавьте другие менеджеры здесь
         ]

         for manager_attr, method_name in managers_to_save:
              manager = manager_attr # type: Optional[Any] # Use Any because manager can be different types
              if manager and hasattr(manager, method_name):
                   try:
                       # Проверяем наличие required_args, хотя в PersistenceManager мы должны передавать все, что есть.
                       # Менеджер сам внутри должен игнорировать ненужные kwargs или рейзить ошибку, если mandatory args не переданы.
                       # Мы уже знаем, что save_state ожидает guild_id и **kwargs.
                       await getattr(manager, method_name)(**call_kwargs) # Вызываем save_state(guild_id, **kwargs)
                   except Exception as e:
                       print(f"PersistenceManager: ❌ Error saving state for guild {guild_id} in manager {type(manager).__name__}: {e}")
                       # Не пробрасываем здесь, чтобы не остановить сохранение других менеджеров/гильдий.
                       # Основной save_game_state обработчик словит ошибку транзакции (если была),
                       # или мы просто логируем проблему с конкретным менеджером/гильдией.
                       import traceback
                       print(traceback.format_exc())
                       # Если менеджер поднял AttributeError, значит, у него нет save_state метода.
                       # Это указывает на ошибку конфигурации или опечатку в managers_to_save.

              # Логируем, если менеджер был предоставлен, но у него нет ожидаемого save_state метода
              elif manager:
                   print(f"PersistenceManager: Warning: Manager {type(manager).__name__} was provided but does not have expected method '{method_name}'. Skipping save for guild {guild_id}.")


    async def load_game_state(self, guild_ids: List[str], **kwargs: Any) -> None: # Добавили guild_ids и **kwargs
        """
        Координирует загрузку состояния всех менеджеров для указанных гильдий при запуске бота.
        Каждый менеджер отвечает за загрузку СВОИХ данных per-guild, используя db_adapter.
        Передаются в load_state менеджеров (напр., time_manager для StatusManager).
        """
        print(f"PersistenceManager: Initiating game state load for {len(guild_ids)} guilds...")

        if self._db_adapter is None: # Если адаптер БД не был предоставлен
            print("PersistenceManager: Database adapter not provided. Loading placeholder state (simulated loading).")
            # В режиме без БД, менеджеры должны загрузить свои in-memory заглушки.
            # Вызываем load_state (они должны сами симулировать/логировать) для каждой гильдии.
            for guild_id in guild_ids:
                 await self._call_manager_load(guild_id, **kwargs) # Используем вспомогательный метод
                 # В режиме заглушки rebuild_runtime_caches может быть вызван сразу после load_state для каждой гильдии

        else: # Если адаптер БД есть
            print("PersistenceManager: Database adapter found, attempting to load via managers.")
            try:
                 # Загружаем состояние для каждой гильдии
                 for guild_id in guild_ids:
                     await self._call_manager_load(guild_id, **kwargs) # Используем вспомогательный метод

                 # После загрузки СОСТОЯНИЯ ВСЕХ ГИЛЬДИЙ всеми менеджерами, вызываем rebuild_runtime_caches для каждой гильдии
                 # Перестройка часто зависит от данных из РАЗНЫХ менеджеров для ОДНОЙ гильдии,
                 # поэтому лучше загрузить все состояние по гильдиям, а потом пройтись по rebuild.
                 print("PersistenceManager: Rebuilding runtime caches for loaded guilds...")
                 for guild_id in guild_ids:
                      await self._call_manager_rebuild_caches(guild_id, **kwargs) # Используем вспомогательный метод


                 print("PersistenceManager: ✅ Game state loaded successfully (via managers).")

                 # Optional: Log counts after successful load for all guilds
                 # Это сложнее в многогильдийном режиме без агрегирующих методов в менеджерах.
                 # active_events_count = sum(len(self._event_manager.get_active_events(guild_id)) for guild_id in guild_ids) if self._event_manager and hasattr(self._event_manager, 'get_active_events') else 0
                 # print(f"PersistenceManager: Loaded {active_events_count} active events total.")
                 loaded_chars_count = len(self._character_manager._characters) if self._character_manager and hasattr(self._character_manager, '_characters') else 0 # Пример доступа к приватному атрибуту
                 print(f"PersistenceManager: Loaded {loaded_chars_count} characters into cache (total, may include other guilds if cache not filtered).")


            except Exception as e:
                 print(f"PersistenceManager: ❌ Error during game state load via managers: {e}")
                 # КРИТИЧЕСКАЯ ОШИБКА ЗАГРУЗКИ
                 import traceback
                 print(traceback.format_exc())
                 # TODO: Добавить логику обработки критических ошибок загрузки (оповещение GM, режим обслуживания?)
                 raise # Пробрасываем исключение, чтобы GameManager знал об ошибке


    # Вспомогательный метод для вызова load_state у всех менеджеров для одной гильдии
    async def _call_manager_load(self, guild_id: str, **kwargs: Any) -> None: # Добавили guild_id и **kwargs
         """Вызывает load_state у каждого менеджера, который поддерживает персистентность, для одной гильдии."""
         # Передаем kwargs дальше менеджерам
         call_kwargs = {'guild_id': guild_id, **kwargs}

         # Список кортежей (атрибут менеджера, имя ожидаемого метода)
         managers_to_load = [
             (self._event_manager, 'load_state'), # Переименован load_all_events -> load_state
             (self._character_manager, 'load_state'), # Переименован load_all_characters -> load_state
             (self._location_manager, 'load_state'), # LocationManager загружает шаблоны/инстансы
             (self._npc_manager, 'load_state'),
             (self._item_manager, 'load_state'),
             (self._combat_manager, 'load_state'),
             (self._time_manager, 'load_state'), # TimeManager может игнорировать guild_id
             (self._status_manager, 'load_state'),
             (self._crafting_manager, 'load_state'),
             (self._economy_manager, 'load_state'),
             (self._party_manager, 'load_state'),
             # TODO: Добавьте другие менеджеры здесь
         ]

         for manager_attr, method_name in managers_to_load:
              manager = manager_attr # type: Optional[Any] # Use Any because manager can be different types
              if manager and hasattr(manager, method_name):
                   try:
                        # Менеджер сам внутри должен игнорировать ненужные kwargs или рейзить ошибку.
                        # Мы передаем guild_id и все kwargs.
                        await getattr(manager, method_name)(**call_kwargs) # Вызываем load_state(guild_id, **kwargs)
                   except Exception as e:
                       print(f"PersistenceManager: ❌ Error loading state for guild {guild_id} in manager {type(manager).__name__}: {e}")
                       # Не пробрасываем здесь, чтобы не остановить загрузку других менеджеров/гильдий.
                       # Основной load_game_state обработчик выше словит, если нужно полностью остановить загрузку.
                       import traceback
                       print(traceback.format_exc())
                       # Если менеджер поднял AttributeError, значит, у него нет load_state метода.


              elif manager:
                   print(f"PersistenceManager: Warning: Manager {type(manager).__name__} was provided but does not have expected method '{method_name}'. Skipping load for guild {guild_id}.")


    # Вспомогательный метод для вызова rebuild_runtime_caches у всех менеджеров для одной гильдии
    async def _call_manager_rebuild_caches(self, guild_id: str, **kwargs: Any) -> None: # Добавили guild_id и **kwargs
         """Вызывает rebuild_runtime_caches у каждого менеджера, который поддерживает его, для одной гильдии."""
         # Передаем kwargs дальше менеджерам
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
              if manager and hasattr(manager, method_name):
                   try:
                       # Менеджер сам внутри должен использовать guild_id и kwargs для перестройки.
                       await getattr(manager, method_name)(**call_kwargs) # Вызываем rebuild_runtime_caches(guild_id, **kwargs)
                   except Exception as e:
                       print(f"PersistenceManager: ❌ Error rebuilding caches for guild {guild_id} in manager {type(manager).__name__}: {e}")
                       # Не пробрасываем здесь, чтобы не остановить перестройку других менеджеров/гильдий.
                       import traceback
                       print(traceback.format_exc())
                       # Если менеджер поднял AttributeError, значит, у него нет rebuild_runtime_caches метода.


              elif manager:
                   print(f"PersistenceManager: Warning: Manager {type(manager).__name__} was provided but does not have expected method '{method_name}'. Skipping rebuild for guild {guild_id}.")


    # ... (Дополнительные вспомогательные методы остаются прежними) ...

# Конец класса PersistenceManager

# TODO: Здесь могут быть другие классы менеджеров или хелперы, если они не являются частью GameManager.