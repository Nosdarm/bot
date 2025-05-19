# bot/game/managers/game_manager.py

print("--- Начинается загрузка: game_manager.py")
import asyncio
import traceback
# Импорт базовых типов
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set # Добавлен Set
# Импорт TYPE_CHECKING
from typing import TYPE_CHECKING

# Импорт для Discord Client и Message, если они используются для аннотаций
from discord import Client, Message

# Адаптер для работы с SQLite - Прямой импорт нужен, т.к. он инстанциируется здесь
from bot.database.sqlite_adapter import SqliteAdapter


if TYPE_CHECKING:
    # --- Импорты для Type Checking ---
    # Менеджеры
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.crafting_manager import CraftingManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.party_manager import PartyManager
    from bot.services.openai_service import OpenAIService
    from bot.game.managers.persistence_manager import PersistenceManager
    # Процессоры
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
    # Роутер команд
    from bot.game.command_router import CommandRouter

    # Типы Callable для Type Checking, если они используются в аннотациях (SendCallbackFactory используется напрямую в __init__)
    # SendToChannelCallback = Callable[..., Awaitable[Any]]
    # SendCallbackFactory = Callable[[int], SendToChannelCallback]


# Фабрика колбэков отправки сообщений: принимает произвольные аргументы (content, embed, files и т.д.)
# Используется для аннотации типа в __init__
SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class GameManager:
    def __init__(
        self,
        discord_client: Client,
        settings: Dict[str, Any],
        db_path: str
    ):
        print("Initializing GameManager…")
        self._discord_client = discord_client
        self._settings = settings
        self._db_path = db_path

        # Инициализация отложенных зависимостей
        self._db_adapter: Optional[SqliteAdapter] = None # SqliteAdapter инстанс
        self._persistence_manager: Optional["PersistenceManager"] = None # Строковый литерал
        self._world_simulation_processor: Optional["WorldSimulationProcessor"] = None # Строковый литерал
        self._command_router: Optional["CommandRouter"] = None # Строковый литерал

        # Основные менеджеры и сервисы (используем строковые литералы для единообразия с TYPE_CHECKING)
        self.rule_engine: Optional["RuleEngine"] = None
        self.time_manager: Optional["TimeManager"] = None
        self.location_manager: Optional["LocationManager"] = None
        self.event_manager: Optional["EventManager"] = None
        self.character_manager: Optional["CharacterManager"] = None
        self.item_manager: Optional["ItemManager"] = None
        self.status_manager: Optional["StatusManager"] = None
        self.combat_manager: Optional["CombatManager"] = None
        self.crafting_manager: Optional["CraftingManager"] = None
        self.economy_manager: Optional["EconomyManager"] = None
        self.npc_manager: Optional["NpcManager"] = None
        self.party_manager: Optional["PartyManager"] = None
        self.openai_service: Optional["OpenAIService"] = None

        # Процессоры и вспомогательные сервисы (используем строковые литералы)
        self._on_enter_action_executor: Optional["OnEnterActionExecutor"] = None
        self._stage_description_generator: Optional["StageDescriptionGenerator"] = None
        self._event_stage_processor: Optional["EventStageProcessor"] = None
        self._event_action_processor: Optional["EventActionProcessor"] = None
        self._character_action_processor: Optional["CharacterActionProcessor"] = None
        self._character_view_service: Optional["CharacterViewService"] = None
        self._party_action_processor: Optional["PartyActionProcessor"] = None

        # Цикл мирового тика
        self._world_tick_task: Optional[asyncio.Task] = None # Task аннотация, требует импорта asyncio
        self._tick_interval_seconds: float = settings.get('world_tick_interval_seconds', 60.0)

        # Список ID активных гильдий (нужен для PersistenceManager load/save)
        # Этот список нужно получить откуда-то при запуске бота
        # Пример: из настроек или из Discord API после подключения
        self._active_guild_ids: List[str] = self._settings.get('active_guild_ids', []) # <-- ПРИМЕР: получение из settings


        print("GameManager initialized.\n")

    async def setup(self) -> None:
        print("GameManager: Running setup…")
        try:
            # 1) Подключаемся к базе и инициализируем схему
            # SqliteAdapter уже импортирован напрямую, т.к. инстанциируется здесь
            self._db_adapter = SqliteAdapter(self._db_path)
            await self._db_adapter.connect()
            await self._db_adapter.initialize_database()
            print("GameManager: Database setup complete.")

            # 2) Импортируем классы менеджеров и процессоров для их ИНСТАНЦИАЦИИ
            # ЭТИ ИМПОРТЫ НУЖНЫ ЗДЕСЬ ДЛЯ RUNTIME, т.к. мы создаем экземпляры!
            # Убедитесь, что эти импорты не вызывают циклов, что достигается использованием TYPE_CHECKING в других файлах.
            from bot.game.rules.rule_engine import RuleEngine
            from bot.game.managers.time_manager import TimeManager
            from bot.game.managers.location_manager import LocationManager
            from bot.game.managers.event_manager import EventManager
            from bot.game.managers.character_manager import CharacterManager
            from bot.game.managers.item_manager import ItemManager
            from bot.game.managers.status_manager import StatusManager
            from bot.game.managers.combat_manager import CombatManager
            from bot.game.managers.crafting_manager import CraftingManager
            from bot.game.managers.economy_manager import EconomyManager
            from bot.game.managers.npc_manager import NpcManager
            from bot.game.managers.party_manager import PartyManager
            from bot.services.openai_service import OpenAIService # Сервис OpenAI
            # Процессоры
            from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
            from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
            from bot.game.event_processors.event_stage_processor import EventStageProcessor
            from bot.game.event_processors.event_action_processor import EventActionProcessor
            from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
            from bot.game.character_processors.character_action_processor import CharacterActionProcessor
            from bot.game.character_processors.character_view_service import CharacterViewService
            from bot.game.party_processors.party_action_processor import PartyActionProcessor
            # PersistenceManager
            from bot.game.managers.persistence_manager import PersistenceManager
            # Роутер команд
            from bot.game.command_router import CommandRouter

            # Core managers (создание экземпляров)
            self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}))
            self.time_manager = TimeManager(db_adapter=self._db_adapter, settings=self._settings.get('time_settings', {}))
            self.location_manager = LocationManager(db_adapter=self._db_adapter, settings=self._settings.get('location_settings', {}))
            self.event_manager = EventManager(db_adapter=self._db_adapter, settings=self._settings.get('event_settings', {}))
            # CharacterManager (создание экземпляра и внедрение части зависимостей)
            self.character_manager = CharacterManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('character_settings', {}),
                location_manager=self.location_manager, # Внедрение location_manager
                rule_engine=self.rule_engine # Внедрение rule_engine
                # Остальные зависимости CharacterManager внедряются ниже
            )
            print("GameManager: Core managers instantiated.")

            # OpenAIService (опционально)
            try:
                oset = self._settings.get('openai_settings', {})
                self.openai_service = OpenAIService(
                    api_key=oset.get('api_key'),
                    model=oset.get('model'),
                    default_max_tokens=oset.get('default_max_tokens')
                )
                print("GameManager: OpenAIService instantiated.")
            except Exception as e:
                print(f"GameManager: Warning: OpenAIService unavailable ({e})")
                self.openai_service = None

            # Зависимые менеджеры (создание экземпляров с внедрением зависимостей)
            self.item_manager = ItemManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('item_settings', {}),
                location_manager=self.location_manager, # Внедрение LocationManager
                rule_engine=self.rule_engine # Внедрение RuleEngine
            )
            self.status_manager = StatusManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('status_settings', {}),
                rule_engine=self.rule_engine, # Внедрение RuleEngine
                time_manager=self.time_manager # Внедрение TimeManager
            )
            self.combat_manager = CombatManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('combat_settings', {}),
                rule_engine=self.rule_engine, # Внедрение RuleEngine
                character_manager=self.character_manager, # Внедрение CharacterManager
                status_manager=self.status_manager, # Внедрение StatusManager
                item_manager=self.item_manager # Внедрение ItemManager
            )
            self.crafting_manager = CraftingManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('crafting_settings', {}),
                item_manager=self.item_manager, # Внедрение ItemManager
                character_manager=self.character_manager, # Внедрение CharacterManager
                time_manager=self.time_manager, # Внедрение TimeManager
                rule_engine=self.rule_engine # Внедрение RuleEngine
            )
            self.economy_manager = EconomyManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('economy_settings', {}),
                item_manager=self.item_manager, # Внедрение ItemManager
                location_manager=self.location_manager, # Внедрение LocationManager
                character_manager=self.character_manager, # Внедрение CharacterManager
                rule_engine=self.rule_engine, # Внедрение RuleEngine
                time_manager=self.time_manager # Внедрение TimeManager
            )
            self.npc_manager = NpcManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('npc_settings', {}),
                item_manager=self.item_manager, # Внедрение ItemManager
                rule_engine=self.rule_engine, # Внедрение RuleEngine
                combat_manager=self.combat_manager, # Внедрение CombatManager
                status_manager=self.status_manager # Внедрение StatusManager
                # NpcManager может нуждаться в других менеджерах (Location?) - проверить его __init__
            )
            self.party_manager = PartyManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('party_settings', {}),
                character_manager=self.character_manager, # Внедрение CharacterManager
                npc_manager=self.npc_manager # Внедрение NpcManager
                # PartyManager может нуждаться в других менеджерах (Combat?) - проверить его __init__
            )

            # Внедряем зависимости в CharacterManager (те, которые были circular dependencies при создании)
            if self.character_manager: # Убедимся, что CharacterManager был создан
                 self.character_manager._status_manager = self.status_manager
                 self.character_manager._party_manager = self.party_manager
                 self.character_manager._combat_manager = self.combat_manager
                 # Внедрить dialogue_manager, если он есть и CharacterManager его использует
                 # if hasattr(self, 'dialogue_manager'): # Проверка наличия dialogue_manager как атрибута GameManager
                 #      self.character_manager._dialogue_manager = self.dialogue_manager # Если CharacterManager его ожидает


            print("GameManager: Dependent managers instantiated.")

            # Процессоры и роутер команд (создание экземпляров)
            # Внедрение зависимостей в процессоры
            self._on_enter_action_executor = OnEnterActionExecutor(
                npc_manager=self.npc_manager,
                item_manager=self.item_manager,
                combat_manager=self.combat_manager,
                status_manager=self.status_manager
                # OnEnterActionExecutor может нуждаться в других менеджерах (Character?, Party?) - проверить его __init__
            )
            # StageDescriptionGenerator
            self._stage_description_generator = StageDescriptionGenerator(openai_service=self.openai_service) # Нуждается в OpenAIService (может быть None)

            # EventStageProcessor
            self._event_stage_processor = EventStageProcessor(
                on_enter_action_executor=self._on_enter_action_executor, # Внедрение OnEnterActionExecutor
                stage_description_generator=self._stage_description_generator, # Внедрение StageDescriptionGenerator
                # Внедрение менеджеров (Optional в EventStageProcessor)
                character_manager=self.character_manager,
                loc_manager=self.location_manager, # Передаем location_manager как loc_manager
                rule_engine=self.rule_engine,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager,
                # EventStageProcessor ожидает event_action_processor, dialogue_manager, crafting_manager - проверить __init__
            )

            # EventActionProcessor
            self._event_action_processor = EventActionProcessor(
                # Внедрение EventStageProcessor (круговая зависимость - решена TYPE_CHECKING)
                event_stage_processor=self._event_stage_processor,
                # Внедрение менеджеров и сервисов
                event_manager=self.event_manager,
                character_manager=self.character_manager,
                loc_manager=self.location_manager, # Передаем location_manager как loc_manager
                rule_engine=self.rule_engine,
                openai_service=self.openai_service, # Может быть None
                # EventActionProcessor ожидает npc, combat, item, time, status менеджеры (Optional) - проверить __init__
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                # EventActionProcessor ожидает send_callback_factory, dialogue_manager, crafting_manager, on_enter_action_executor, stage_description_generator
                # SendCallbackFactory нужно передать явно или через **kwargs контекста, т.к. он не сохраняется как self._ атрибут в Processors
                # Давайте передадим его и другие Processor-dependencies явно
                # EventActionProcessor ожидает send_callback_factory в __init__ - проверим __init__ EventActionProcessor
                # ДА, EventActionProcessor ожидает send_callback_factory в __init__. Передадим его.
                send_callback_factory=self._get_discord_send_callback, # Передаем фабрику
                # EventActionProcessor ожидает dialogue_manager, crafting_manager, on_enter_action_executor, stage_description_generator в __init__ (Optional)
                dialogue_manager=getattr(self, 'dialogue_manager', None), # Получаем из self, если существует (нужно проверить наличие атрибута в GM)
                crafting_manager=self.crafting_manager, # Проверяем, что crafting_manager создался выше
                on_enter_action_executor=self._on_enter_action_executor, # Проверяем, что on_enter_action_executor создался выше
                stage_description_generator=self._stage_description_generator, # Проверяем, что stage_description_generator создался выше
            )

            # CharacterActionProcessor
            self._character_action_processor = CharacterActionProcessor(
                character_manager=self.character_manager,
                send_callback_factory=self._get_discord_send_callback, # Передаем фабрику
                # CharacterActionProcessor ожидает item, location, rule, time, combat, status, party, npc, event_stage, event_action
                item_manager=self.item_manager,
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                time_manager=self.time_manager,
                combat_manager=self.combat_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager,
                npc_manager=self.npc_manager,
                event_stage_processor=self._event_stage_processor,
                event_action_processor=self._event_action_processor,
                # TODO: CharacterActionProcessor может нуждаться в crafting, economy, dialogue? Проверить __init__
            )

            # CharacterViewService
            self._character_view_service = CharacterViewService(
                character_manager=self.character_manager,
                item_manager=self.item_manager,
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                status_manager=self.status_manager,
                party_manager=self.party_manager
                # CharacterViewService может нуждаться в других менеджерах/сервисах (например, Formatter?) - проверить __init__
            )

            # PartyActionProcessor
            self._party_action_processor = PartyActionProcessor(
                party_manager=self.party_manager, # Проверяем, что party_manager создался выше
                send_callback_factory=self._get_discord_send_callback, # Передаем фабрику
                # PartyActionProcessor ожидает rule, location, character, npc, time, combat, event_stage
                rule_engine=self.rule_engine,
                location_manager=self.location_manager,
                character_manager=self.character_manager,
                npc_manager=self.npc_manager,
                time_manager=self.time_manager,
                combat_manager=self.combat_manager,
                event_stage_processor=self._event_stage_processor
                # TODO: PartyActionProcessor может нуждаться в других менеджерах (event_action?) - проверить __init__
            )
            # В оригинальном коде PartyActionProcessor обнулялся, если party_manager == None. Сохраним эту логику.
            if self.party_manager is None:
                self._party_action_processor = None
                print("GameManager: Warning: PartyManager not available, PartyActionProcessor is None.")


            # PersistenceManager (создание экземпляра с внедрением зависимостей)
            # Он принимает db_adapter и все менеджеры, чье состояние координирует
            self._persistence_manager = PersistenceManager(
                db_adapter=self._db_adapter, # Проверяем, что db_adapter создался выше
                event_manager=self.event_manager,
                character_manager=self.character_manager,
                location_manager=self.location_manager,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                crafting_manager=self.crafting_manager,
                economy_manager=self.economy_manager,
                party_manager=self.party_manager
                # TODO: PersistenceManager может нуждаться в других менеджерах
            )

            # WorldSimulationProcessor
            self._world_simulation_processor = WorldSimulationProcessor(
                # WorldSimulationProcessor ожидает event, character, location, rule, openai, event_stage, event_action, persistence, settings, send_callback_factory, character_action, party_action, npc, combat, item, time, status, crafting, economy
                event_manager=self.event_manager,
                character_manager=self.character_manager,
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                openai_service=self.openai_service, # Может быть None
                event_stage_processor=self._event_stage_processor,
                event_action_processor=self._event_action_processor,
                persistence_manager=self._persistence_manager,
                settings=self._settings,
                send_callback_factory=self._get_discord_send_callback, # Передаем фабрику
                character_action_processor=self._character_action_processor,
                party_action_processor=self._party_action_processor, # Может быть None
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                crafting_manager=self.crafting_manager,
                economy_manager=self.economy_manager
                # TODO: WorldSimulationProcessor может нуждаться в других менеджерах (dialogue?)
            )

            # CommandRouter
            self._command_router = CommandRouter(
                # CommandRouter ожидает character, event, event_action, event_stage, persistence, settings, world_simulation, send_callback_factory, character_action, character_view, party_action, location, rule, openai, item, npc, combat, time, status, party, crafting, economy
                character_manager=self.character_manager,
                event_manager=self.event_manager,
                event_action_processor=self._event_action_processor,
                event_stage_processor=self._event_stage_processor,
                persistence_manager=self._persistence_manager,
                settings=self._settings,
                world_simulation_processor=self._world_simulation_processor,
                send_callback_factory=self._get_discord_send_callback, # Передаем фабрику
                character_action_processor=self._character_action_processor,
                character_view_service=self._character_view_service,
                party_action_processor=self._party_action_processor, # Может быть None
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                openai_service=self.openai_service, # Может быть None
                item_manager=self.item_manager,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager, # Может быть None
                crafting_manager=self.crafting_manager,
                economy_manager=self.economy_manager
                # TODO: CommandRouter может нуждаться в других менеджерах (dialogue?)
            )

            # 5) Загрузка состояния
            print("GameManager: Loading game state...")
            # Определяем список ID гильдий для загрузки. В данном примере берем из settings.
            # В РЕАЛЬНОМ ПРИЛОЖЕНИИ этот список должен браться из более надежного источника
            # (например, из базы данных, где хранятся гильдии, или после подключения к Discord API).
            active_guild_ids: List[str] = self._active_guild_ids # Получаем список ID гильдий из атрибута self._active_guild_ids


            # Собираем все менеджеры, сервисы, процессоры и колбэки в словарь для передачи как **kwargs
            # Этот словарь будет передан PersistenceManager, а затем делегирован менеджерам при load_state и rebuild_runtime_caches.
            # Важно включить все, что может понадобиться менеджерам при загрузке или перестройке.
            load_context_kwargs: Dict[str, Any] = {
                # Передаем все инстанции менеджеров
                'rule_engine': self.rule_engine,
                'time_manager': self.time_manager,
                'location_manager': self.location_manager,
                'event_manager': self.event_manager,
                'character_manager': self.character_manager,
                'item_manager': self.item_manager,
                'status_manager': self.status_manager,
                'combat_manager': self.combat_manager,
                'crafting_manager': self.crafting_manager,
                'economy_manager': self.economy_manager,
                'npc_manager': self.npc_manager,
                'party_manager': self.party_manager,
                'openai_service': self.openai_service, # Может быть None
                # Передаем инстанции процессоров и вспомогательных сервисов
                'on_enter_action_executor': self._on_enter_action_executor,
                'stage_description_generator': self._stage_description_generator,
                'event_stage_processor': self._event_stage_processor,
                'event_action_processor': self._event_action_processor,
                'character_action_processor': self._character_action_processor,
                'character_view_service': self._character_view_service,
                'party_action_processor': self._party_action_processor, # Может быть None
                # Передаем сам PersistenceManager и WorldSimulationProcessor
                'persistence_manager': self._persistence_manager,
                'world_simulation_processor': self._world_simulation_processor, # Может понадобиться при rebuild
                # Передаем адаптер БД (хотя PersistenceManager его уже имеет, менеджеры тоже могут его ожидать в kwargs)
                'db_adapter': self._db_adapter,
                # Передаем фабрику колбэков
                'send_callback_factory': self._get_discord_send_callback,
                # Передаем settings (или только relevant части)
                'settings': self._settings,
                # Передаем Discord Client, если он может понадобиться (например, для получения информации о каналах/гильдиях в менеджерах при rebuild)
                'discord_client': self._discord_client,
                # Добавьте любые другие данные из setup, которые могут потребоваться при загрузке/перестройке
            }


            # Вызываем load_game_state на PersistenceManager с правильными аргументами
            # Он скоординирует загрузку для каждой гильдии, используя менеджеры.
            await self._persistence_manager.load_game_state(
                guild_ids=active_guild_ids, # Передаем список ID гильдий
                **load_context_kwargs # Передаем все собранные менеджеры и зависимости
            )
            print("GameManager: Game state loaded.")


            # Запуск цикла тика мира ТОЛЬКО после успешной загрузки
            self._world_tick_task = asyncio.create_task(self._world_tick_loop())
            print("GameManager: Setup complete.")

        except Exception as e:
            print(f"GameManager: ❌ CRITICAL ERROR during setup: {e}")
            traceback.print_exc()
            # TODO: Реализовать корректный shutdown при ошибке setup
            await self.shutdown() # Попытка корректно выключиться
            # Не рейзим здесь, GameManager сам обрабатывает свою ошибку и выключается

    async def handle_discord_message(self, message: Message) -> None:
        if message.author.bot:
            return
        if not self._command_router:
            print(f"GameManager: Warning: CommandRouter not available, message '{message.content}' dropped.")
            # Optional: Send error message to user
            # await self._get_discord_send_callback(message.channel.id)("Error: Game is not fully started yet.", None)
            return
        print(f"GameManager: Passing message from {message.author.name} (ID: {message.author.id}, Guild: {message.guild.id if message.guild else 'DM'}, Channel: {message.channel.id}) to CommandRouter: '{message.content}'")
        try:
            # CommandRouter ожидает Discord Message object
            await self._command_router.route(message)
        except Exception as e:
            print(f"GameManager: Error handling message '{message.content}': {e}")
            traceback.print_exc()
            # Отправляем сообщение об ошибке пользователю в канал команды
            try:
                 if message.channel:
                      send_callback = self._get_discord_send_callback(message.channel.id)
                      await send_callback(f"❌ Произошла ошибка при обработке вашей команды: {e}", None)
                 else:
                      print(f"GameManager: Warning: Cannot send error message to user (DM channel or channel not found).")
            except Exception as cb_e:
                 print(f"GameManager: Error sending error message back to channel {message.channel.id}: {cb_e}")


    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback:
        # Убедимся, что channel_id - это int, т.к. get_channel ожидает int
        channel_id_int = int(channel_id) # Пытаемся преобразовать на всякий случай

        async def _send(content: str = "", **kwargs: Any) -> None:
            # print(f"--- DIAGNOSTIC: _send function executed for channel {channel_id_int}. Accepts kwargs. ---")
            # Получаем канал через Discord Client
            channel = self._discord_client.get_channel(channel_id_int)
            if channel:
                try:
                    # channel.send ожидает content (str) и **kwargs
                    await channel.send(content, **kwargs)
                except Exception as e:
                    print(f"GameManager: Error sending message to channel {channel_id_int}: {e}")
                    traceback.print_exc()
            else:
                print(f"GameManager: Warning: Channel {channel_id_int} not found. Kwargs: {kwargs}")
                # Можно добавить логику fallback, например, логировать в консоль или GM канал


        # Возвращаем асинхронную функцию _send
        return _send

async def _world_tick_loop(self) -> None:
        print(f"GameManager: Starting world tick loop with interval {self._tick_interval_seconds} seconds.")
        try:
            while True:
                await asyncio.sleep(self._tick_interval_seconds)
                if self._world_simulation_processor:
                    try:
                        # ИСПРАВЛЕНИЕ: Вызываем метод с правильным именем process_world_tick
                        # WorldSimulationProcessor.process_world_tick ожидает time_delta и **kwargs
                        # Передаем ВСЕ менеджеры/сервисы/колбэки в kwargs для WorldSimulationProcessor
                        tick_context_kwargs: Dict[str, Any] = {
                            'rule_engine': self.rule_engine,
                            'time_manager': self.time_manager,
                            'location_manager': self.location_manager,
                            'event_manager': self.event_manager,
                            'character_manager': self.character_manager,
                            'item_manager': self.item_manager,
                            'status_manager': self.status_manager,
                            'combat_manager': self.combat_manager,
                            'crafting_manager': self.crafting_manager,
                            'economy_manager': self.economy_manager,
                            'npc_manager': self.npc_manager,
                            'party_manager': self.party_manager,
                            'openai_service': self.openai_service, # Может быть None
                            'on_enter_action_executor': self._on_enter_action_executor,
                            'stage_description_generator': self._stage_description_generator,
                            'event_stage_processor': self._event_stage_processor,
                            'event_action_processor': self._event_action_processor,
                            'character_action_processor': self._character_action_processor,
                            'character_view_service': self._character_view_service,
                            'party_action_processor': self._party_action_processor, # Может быть None
                            'persistence_manager': self._persistence_manager,
                            # 'world_simulation_processor': self._world_simulation_processor, # Не передаем себя
                            'db_adapter': self._db_adapter,
                            'send_callback_factory': self._get_discord_send_callback,
                            'settings': self._settings,
                            'discord_client': self._discord_client,
                            # TODO: Другие менеджеры/процессоры/сервисы, нужные при тике
                        }
                        # Передаем time_delta (self._tick_interval_seconds) и собранный контекст (tick_context_kwargs)
                        await self._world_simulation_processor.process_world_tick(
                            game_time_delta=self._tick_interval_seconds, # Имя аргумента game_time_delta из сигнатуры
                            **tick_context_kwargs
                        )
                        # print("WorldSimulationProcessor tick processed.") # debug logging inside process_world_tick
                    except Exception as e:
                        print(f"GameManager: ❌ Error during world simulation tick: {e}")
                        traceback.print_exc()
                        # TODO: Обработка ошибки тика (логирование, оповещение GM, остановка симуляции?)
        except asyncio.CancelledError:
            print("GameManager: World tick loop cancelled.")
        except Exception as e:
            print(f"GameManager: ❌ Critical error in world tick loop: {e}")
            traceback.print_exc()
            # Критическая ошибка в самом цикле тика - может потребоваться полный shutdown
            # await self.shutdown() # Вызов shutdown может вызвать рекурсию, если сохранение упадет.
            # Лучше просто логировать и позволить внешней системе остановить бот.


async def shutdown(self) -> None:
        print("GameManager: Running shutdown...")
        # Останавливаем цикл тика мира
        if self._world_tick_task:
            self._world_tick_task.cancel()
            try:
                await self._world_tick_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                 print(f"GameManager: Error waiting for world tick task to cancel: {e}")


        # Сохраняем состояние
        if self._persistence_manager:
            try:
                print("GameManager: Saving game state on shutdown...")
                # Определяем список ID гильдий для сохранения. Используем тот же список, что и для загрузки.
                active_guild_ids: List[str] = self._active_guild_ids # Получаем список ID гильдий


                # Собираем все менеджеры, сервисы, процессоры и колбэки в словарь для передачи как **kwargs
                # Менеджерам при сохранении обычно нужно меньше зависимостей, чем при загрузке/rebuild.
                # Но safe-способ - передать все инстанции менеджеров и DB адаптер.
                save_context_kwargs: Dict[str, Any] = {
                    # Передаем все инстанции менеджеров
                    'rule_engine': self.rule_engine,
                    'time_manager': self.time_manager,
                    'location_manager': self.location_manager,
                    'event_manager': self.event_manager,
                    'character_manager': self.character_manager,
                    'item_manager': self.item_manager,
                    'status_manager': self.status_manager,
                    'combat_manager': self.combat_manager,
                    'crafting_manager': self.crafting_manager,
                    'economy_manager': self.economy_manager,
                    'npc_manager': self.npc_manager,
                    'party_manager': self.party_manager,
                    # Передаем адаптер БД (хотя PersistenceManager его уже имеет, менеджеры могут его ожидать в kwargs)
                    'db_adapter': self._db_adapter,
                    # Передаем фабрику колбэков (для логирования ошибок в менеджерах при сохранении)
                    'send_callback_factory': self._get_discord_send_callback,
                    # TODO: Другие менеджеры/сервисы/процессоры, нужные при сохранении
                    'settings': self._settings, # Настройки могут понадобиться менеджерам при сохранении
                }

                # Вызываем save_game_state на PersistenceManager с правильными аргументами
                await self._persistence_manager.save_game_state(
                    guild_ids=active_guild_ids, # Передаем список ID гильдий
                    **save_context_kwargs # Передаем все собранные менеджеры и зависимости
                )
                print("GameManager: Game state saved on shutdown.")
            except Exception as e:
                print(f"GameManager: ❌ Error saving game state on shutdown: {e}")
                traceback.print_exc()
                # Ошибка сохранения при выключении - возможно, нужно сделать что-то еще (уведомить GM?)

        # Закрываем соединение с БД (делается здесь, в GameManager, т.к. GameManager владеет адаптером)
        # PersistenceManager только ИСПОЛЬЗУЕТ адаптер, но не закрывает его.
        if self._db_adapter:
            try:
                await self._db_adapter.close()
                print("GameManager: Database connection closed.")
            except Exception as e:
                print(f"GameManager: ❌ Error closing database adapter: {e}")
                traceback.print_exc()

        print("GameManager: Shutdown complete.")

# --- Конец класса GameManager ---

print("DEBUG: game_manager.py module loaded.")