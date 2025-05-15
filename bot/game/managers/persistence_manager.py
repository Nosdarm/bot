# bot/game/managers/persistence_manager.py

import asyncio # Нужен для await
import traceback # Для вывода трассировки ошибок
from typing import Dict, Optional, Any, List # Type hints

# Импорт ВСЕХ менеджеров, которые этот менеджер будет координировать для сохранения/загрузки.
# Убедитесь, что эти пути импорта и имена классов верны для ВАШЕГО проекта.
# PersistenceManager координирует сохранение/загрузку других менеджеров.
# ЭТИ ИМПОРТЫ ДОЛЖНЫ БЫТЬ В ЭТОМ ФАЙЛЕ, ОТНОСИТЕЛЬНО КОРНЯ ПРОЕКТА (bot/game/managers)

# Обязательные менеджеры
from bot.game.managers.event_manager import EventManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager # LocationManager может хранить только статику, но часто участвует в load/rebuild

# Опциональные менеджеры
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.crafting_manager import CraftingManager # Если есть
from bot.game.managers.economy_manager import EconomyManager # Если есть
from bot.game.managers.party_manager import PartyManager # Если есть


# TODO: Импорт адаптера базы данных, если используется для реальной персистентности
from bot.database.sqlite_adapter import SqliteAdapter # <-- Используем наш адаптер


class PersistenceManager:
    """
    Координирует сохранение и загрузку состояния игры, делегируя работу
    специализированным менеджерам.
    Этот менеджер владеет ссылками на другие менеджеры, чье состояние он сохраняет/загружает.
    """
    def __init__(self,
                 # Принимаем зависимости, которые передает GameManager.
                 # Убедитесь, что порядок аргументов здесь соответствует порядку, в котором GameManager их передает.

                 # ОБЯЗАТЕЛЬНЫЕ зависимости для PersistenceManager (те, чьи load/save методы он вызывает и без которых не имеет смысла)
                 # EventManager и CharacterManager почти всегда обязательны для любой игры.
                 event_manager: EventManager,
                 character_manager: CharacterManager,
                 location_manager: LocationManager, # LocationManager может быть нужен для load/rebuild, даже если не сохраняет динамику
                 db_adapter: Optional[SqliteAdapter] = None, # DB адаптер

                 # ОПЦИОНАЛЬНЫЕ зависимости (те, чьи load/save методы вызываются, но их наличие не критично для PersistenceManager)
                 npc_manager: Optional[NpcManager] = None,
                 combat_manager: Optional[CombatManager] = None,
                 item_manager: Optional[ItemManager] = None,
                 time_manager: Optional[TimeManager] = None,
                 status_manager: Optional[StatusManager] = None,
                 crafting_manager: Optional[CraftingManager] = None,
                 economy_manager: Optional[EconomyManager] = None,
                 party_manager: Optional[PartyManager] = None,

                 # TODO: Добавьте другие менеджеры, если они хранят персистентное состояние
                ):
        print("Initializing PersistenceManager...")
        self._db_adapter = db_adapter # Сохраняем адаптер БД

        # Сохраняем ССЫЛКИ на менеджеры как АТРИБУТЫ экземпляра
        # Обязательные
        self._event_manager = event_manager
        self._character_manager = character_manager
        self._location_manager = location_manager # Сохраняем, даже если он только загружает статику

        # Опциональные
        self._npc_manager = npc_manager # Сохраняем NPCManager
        self._combat_manager = combat_manager # Сохраняем CombatManager
        self._item_manager = item_manager # Сохраняем ItemManager
        self._time_manager = time_manager # Сохраняем TimeManager
        self._status_manager = status_manager # Сохраняем StatusManager
        self._crafting_manager = crafting_manager # Сохраняем CraftingManager
        self._economy_manager = economy_manager # Сохраняем EconomyManager
        self._party_manager = party_manager # Сохраняем PartyManager
        # TODO: Сохраните другие менеджеры


        print("PersistenceManager initialized.")


    async def save_game_state(self) -> None:
        """
        Координирует сохранение состояния всех менеджеров, управляющих изменяемыми данными.
        Каждый менеджер отвечает за сохранение СВОИХ данных, используя db_adapter (если есть).
        Этот метод вызывается из GameManager или CommandRouter (GM команды).
        """
        print("PersistenceManager: Initiating game state save...")

        if self._db_adapter: # Если адаптер БД был предоставлен при инициализации
            print("PersistenceManager: Database adapter found, attempting to save via managers.")
            try:
                 # Вызываем асинхронные методы сохранения у каждого менеджера, который управляет изменяемыми данными
                 # УБЕДИТЕСЬ, что у каждого такого менеджера есть асинхронный метод save_all_X()
                 # Менеджеры сами взаимодействуют с self._db_adapter для выполнения записи.
                 await self._event_manager.save_all_events() # EventManager почти всегда хранит изменяемые активные события
                 await self._character_manager.save_all_characters() # CharacterManager почти всегда хранит изменяемых персонажей
                 # LocationManager обычно загружает статику, его load/save методы для динамики опциональны.
                 # Если LocationManager имеет save_all_locations для динамики, раскомментируйте:
                 # if self._location_manager and hasattr(self._location_manager, 'save_all_locations'):
                 #      await self._location_manager.save_all_locations()

                 # TODO: Вызовите save методы для других менеджеров, если они хранят изменяемое состояние
                 # Проверяем наличие менеджера перед вызовом и наличие метода.
                 if self._npc_manager and hasattr(self._npc_manager, 'save_all_npcs'):
                      await self._npc_manager.save_all_npcs()
                 if self._item_manager and hasattr(self._item_manager, 'save_all_items'):
                      await self._item_manager.save_all_items()
                 if self._combat_manager and hasattr(self._combat_manager, 'save_all_combats'):
                      await self._combat_manager.save_all_combats()
                 if self._time_manager and hasattr(self._time_manager, 'save_state'):
                      await self._time_manager.save_state()
                 if self._status_manager and hasattr(self._status_manager, 'save_all_statuses'):
                      await self._status_manager.save_all_statuses() # Вызываем save для StatusManager
                 if self._crafting_manager and hasattr(self._crafting_manager, 'save_all_crafting_queues'):
                      await self._crafting_manager.save_all_crafting_queues()
                 if self._economy_manager and hasattr(self._economy_manager, 'save_all_state'):
                      await self._economy_manager.save_all_state()
                 if self._party_manager and hasattr(self._party_manager, 'save_all_parties'):
                      await self._party_manager.save_all_parties()

                 # TODO: Добавьте вызовы save для других менеджеров с персистентностью.

                 # Фиксируем все изменения. Commit делается здесь, на уровне PersistenceManager.
                 await self._db_adapter.commit()
                 print("PersistenceManager: ✅ Game state saved successfully (via managers).")
            except Exception as e:
                 print(f"PersistenceManager: ❌ Error during game state save via managers: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # Важно: при ошибке сохранения - откатить транзакцию!
                 if self._db_adapter: await self._db_adapter.rollback()
                 # TODO: Добавить логику обработки ошибок сохранения (оповещение GM, попытки повтора?)
                 raise # Пробрасываем исключение, чтобы GameManager знал об ошибке


        else:
            print("PersistenceManager: Database adapter not provided. Simulating state save (managers will log their saves).")
            # Если нет БД, менеджеры-заглушки могут просто логировать попытку сохранения.
            # Вызываем их методы, даже если они заглушки, для консистентности.
            # Важно: вызываем save методы, а не load! И проверяем наличие метода, особенно для опциональных.
            if self._event_manager and hasattr(self._event_manager, 'save_all_events'):
                 await self._event_manager.save_all_events()
            if self._character_manager and hasattr(self._character_manager, 'save_all_characters'):
                 await self._character_manager.save_all_characters()
            # if self._location_manager and hasattr(self._location_manager, 'save_all_locations'):
            #      await self._location_manager.save_all_locations() # Обычно статические данные локаций не сохраняются в этом потоке

            if self._npc_manager and hasattr(self._npc_manager, 'save_all_npcs'):
                 await self._npc_manager.save_all_npcs()
            if self._item_manager and hasattr(self._item_manager, 'save_all_items'):
                 await self._item_manager.save_all_items()
            if self._combat_manager and hasattr(self._combat_manager, 'save_all_combats'):
                 await self._combat_manager.save_all_combats()
            if self._time_manager and hasattr(self._time_manager, 'save_state'):
                 await self._time_manager.save_state()
            if self._status_manager and hasattr(self._status_manager, 'save_all_statuses'):
                 await self._status_manager.save_all_statuses() # Вызываем save для StatusManager
            if self._crafting_manager and hasattr(self._crafting_manager, 'save_all_crafting_queues'):
                 await self._crafting_manager.save_all_crafting_queues()
            if self._economy_manager and hasattr(self._economy_manager, 'save_all_state'):
                 await self._economy_manager.save_all_state()
            if self._party_manager and hasattr(self._party_manager, 'save_all_parties'):
                 await self._party_manager.save_all_parties()

            # TODO: Добавьте вызовы save для других менеджеров


    async def load_game_state(self, **kwargs) -> None: # load_game_state ожидает TimeManager в kwargs для StatusManager
        """
        Координирует загрузку состояния игры при запуске бота или по запросу.
        Каждый менеджер отвечает за загрузку СВОИХ данных, используя db_adapter (если есть).
        kwargs: Передаются в load_all_X менеджеров (напр., time_manager для StatusManager).
        Этот метод вызывается из GameManager или CommandRouter (GM команды).
        """
        print("PersistenceManager: Initiating game state load...")

        if self._db_adapter: # Если адаптер БД был предоставлен
            print("PersistenceManager: Database adapter found, attempting to load via managers.")
            try:
                 # TimeManager может быть нужен другим менеджерам при загрузке (StatusManager для пересчета длительности)
                 # Получаем TimeManager из kwargs или атрибутов
                 time_manager_for_load = kwargs.get('time_manager', self._time_manager)


                 # Вызываем асинхронные методы загрузки у каждого менеджера
                 # УБЕДИТЕСЬ, что у каждого такого менеджера есть асинхронный метод load_all_X()
                 # Менеджеры сами используют self._db_adapter для чтения данных и наполнения своего кеша.
                 await self._event_manager.load_all_events() # EventManager всегда нужно загружать активные события
                 await self._character_manager.load_all_characters() # CharacterManager всегда нужно загружать персонажей
                 # LocationManager обычно загружает статику, но может иметь load_all_locations метод для динамики
                 if self._location_manager and hasattr(self._location_manager, 'load_all_locations'):
                      await self._location_manager.load_all_locations()


                 # TODO: Вызовите load методы для других менеджеров, если они хранят загружаемое состояние
                 # Передаем необходимые менеджеры в kwargs, если load_all_X их ожидает.
                 if self._npc_manager and hasattr(self._npc_manager, 'load_all_npcs'):
                      await self._npc_manager.load_all_npcs() # NPCManager может не требовать kwargs при загрузке
                 if self._item_manager and hasattr(self._item_manager, 'load_all_items'):
                      await self._item_manager.load_all_items()
                 if self._combat_manager and hasattr(self._combat_manager, 'load_all_combats'):
                      await self._combat_manager.load_all_combats()
                 if self._time_manager and hasattr(self._time_manager, 'load_state'):
                      await self._time_manager.load_state() # TimeManager должен загрузить глобальное время
                 if self._status_manager and hasattr(self._status_manager, 'load_all_statuses'):
                      # StatusManager.load_all_statuses ожидает time_manager в kwargs для пересчета длительности
                      await self._status_manager.load_all_statuses(time_manager=time_manager_for_load) # Передаем TimeManager
                 if self._crafting_manager and hasattr(self._crafting_manager, 'load_all_crafting_queues'):
                      await self._crafting_manager.load_all_crafting_queues()
                 if self._economy_manager and hasattr(self._economy_manager, 'load_all_state'):
                      await self._economy_manager.load_all_state()
                 if self._party_manager and hasattr(self._party_manager, 'load_all_parties'):
                      await self._party_manager.load_all_parties()

                 # TODO: Добавьте вызовы load для других менеджеров с персистентностью.


                 # После загрузки, менеджеры могут нуждаться в перестройке внутренних кешей или индексов
                 # Например, построение словаря активных событий по channel_id в EventManager.
                 print("PersistenceManager: Rebuilding runtime caches after loading...")
                 # УБЕДИТЕСЬ, что у каждого менеджера, который нуждается в перестройке кеша после загрузки, есть метод rebuild_runtime_caches()
                 # Вызываем rebuild_runtime_caches для менеджеров, используя СОХРАНЕННЫЕ АТРИБУТЫ self._... И ПРОВЕРЯЕМ HASATTR
                 if self._event_manager and hasattr(self._event_manager, 'rebuild_runtime_caches'):
                      self._event_manager.rebuild_runtime_caches()
                 if self._character_manager and hasattr(self._character_manager, 'rebuild_runtime_caches'):
                      self._character_manager.rebuild_runtime_caches()
                 # Вызываем rebuild_runtime_caches для других менеджеров, если они их имеют
                 if self._location_manager and hasattr(self._location_manager, 'rebuild_runtime_caches'):
                      self._location_manager.rebuild_runtime_caches()
                 if self._npc_manager and hasattr(self._npc_manager, 'rebuild_runtime_caches'):
                      self._npc_manager.rebuild_runtime_caches()
                 if self._combat_manager and hasattr(self._combat_manager, 'rebuild_runtime_caches'):
                      self._combat_manager.rebuild_runtime_caches()
                 if self._item_manager and hasattr(self._item_manager, 'rebuild_runtime_caches'):
                      self._item_manager.rebuild_runtime_caches()
                 if self._time_manager and hasattr(self._time_manager, 'rebuild_runtime_caches'):
                      self._time_manager.rebuild_runtime_caches()
                 if self._status_manager and hasattr(self._status_manager, 'rebuild_runtime_caches'):
                      self._status_manager.rebuild_runtime_caches()
                 if self._crafting_manager and hasattr(self._crafting_manager, 'rebuild_runtime_caches'):
                      self._crafting_manager.rebuild_runtime_caches()
                 if self._economy_manager and hasattr(self._economy_manager, 'rebuild_runtime_caches'):
                      self._economy_manager.rebuild_runtime_caches()
                 if self._party_manager and hasattr(self._party_manager, 'rebuild_runtime_caches'):
                      self._party_manager.rebuild_runtime_caches()

                 print("PersistenceManager: ✅ Game state loaded successfully (via managers).")

                 # Optional: Log counts
                 active_events_count = len(self._event_manager.get_active_events()) if self._event_manager and hasattr(self._event_manager, 'get_active_events') else 0
                 print(f"PersistenceManager: Loaded {active_events_count} active events.")
                 loaded_chars_count = len(self._character_manager.get_all_characters()) if self._character_manager and hasattr(self._character_manager, 'get_all_characters') else 0
                 print(f"PersistenceManager: Loaded {loaded_chars_count} characters.")
                 loaded_npcs_count = len(self._npc_manager._npcs) if self._npc_manager and hasattr(self._npc_manager, '_npcs') else 0 # Пример доступа к приватному атрибуту, лучше использовать public метод
                 print(f"PersistenceManager: Loaded {loaded_npcs_count} NPCs.")


            except Exception as e:
                 print(f"PersistenceManager: ❌ Error during game state load via managers: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # КРИТИЧЕСКАЯ ОШИБКА ЗАГРУЗКИ - возможно, нужно остановить бот.
                 # TODO: Добавить логику обработки критических ошибок загрузки (оповещение GM, режим обслуживания?)
                 raise # Пробрасываем исключение, чтобы GameManager знал об ошибке

        else:
            print("PersistenceManager: Database adapter not provided. Loading placeholder state (simulated loading).")
            # Если нет БД, менеджеры должны загрузить свои in-memory заглушки (placeholders).
            # Их load_all_X() методы должны быть реализованы так, чтобы в случае отсутствия db_adapter
            # они загружали placeholder данные (например, вызывая _load_placeholder_data()).
            # Вызываем load методы, даже если нет адаптера БД, и проверяем наличие метода.
            # Передаем kwargs в load_all_statuses для TimeManager.
            if self._event_manager and hasattr(self._event_manager, 'load_all_events'):
                 await self._event_manager.load_all_events()
            if self._character_manager and hasattr(self._character_manager, 'load_all_characters'):
                 await self._character_manager.load_all_characters()
            if self._location_manager and hasattr(self._location_manager, 'load_all_locations'):
                 await self._location_manager.load_all_locations() # Вызываем load, даже если нет БД, чтобы загрузить статику/заглушки

            if self._npc_manager and hasattr(self._npc_manager, 'load_all_npcs'):
                 await self._npc_manager.load_all_npcs()
            if self._item_manager and hasattr(self._item_manager, 'load_all_items'):
                 await self._item_manager.load_all_items()
            if self._combat_manager and hasattr(self._combat_manager, 'load_all_combats'):
                 await self._combat_manager.load_all_combats()
            if self._time_manager and hasattr(self._time_manager, 'load_state'):
                 await self._time_manager.load_state()
            if self._status_manager and hasattr(self._status_manager, 'load_all_statuses'):
                 await self._status_manager.load_all_statuses(**kwargs) # Передаем TimeManager из kwargs PersistenceManager
            if self._crafting_manager and hasattr(self._crafting_manager, 'load_all_crafting_queues'):
                 await self._crafting_manager.load_all_crafting_queues()
            if self._economy_manager and hasattr(self._economy_manager, 'load_all_state'):
                 await self._economy_manager.load_all_state()
            if self._party_manager and hasattr(self._party_manager, 'load_all_parties'):
                 await self._party_manager.load_all_parties()

            # TODO: Добавьте вызовы load для других менеджеров


    # ... (Дополнительные вспомогательные методы остаются прежними) ...

# Конец класса PersistenceManager

# TODO: Здесь могут быть другие классы менеджеров или хелперы, если они не являются частью GameManager.