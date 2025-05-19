# bot/game/managers/game_manager.py

print("--- Начинается загрузка: game_manager.py")
import asyncio
import traceback
from typing import Optional, Dict, Any, Callable, Awaitable, TYPE_CHECKING, List

from discord import Client, Message

# Адаптер для работы с SQLite
from bot.database.sqlite_adapter import SqliteAdapter

if TYPE_CHECKING:
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

# Фабрика колбэков отправки сообщений: принимает произвольные аргументы (content, embed, files и т.д.)
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
        self._db_adapter: Optional[SqliteAdapter] = None
        self._persistence_manager: Optional[PersistenceManager] = None
        self._world_simulation_processor: Optional[WorldSimulationProcessor] = None
        self._command_router: Optional[CommandRouter] = None

        # Основные менеджеры и сервисы
        self.rule_engine: Optional[RuleEngine] = None
        self.time_manager: Optional[TimeManager] = None
        self.location_manager: Optional[LocationManager] = None
        self.event_manager: Optional[EventManager] = None
        self.character_manager: Optional[CharacterManager] = None
        self.item_manager: Optional[ItemManager] = None
        self.status_manager: Optional[StatusManager] = None
        self.combat_manager: Optional[CombatManager] = None
        self.crafting_manager: Optional[CraftingManager] = None
        self.economy_manager: Optional[EconomyManager] = None
        self.npc_manager: Optional[NpcManager] = None
        self.party_manager: Optional[PartyManager] = None
        self.openai_service: Optional[OpenAIService] = None

        # Процессоры и вспомогательные сервисы
        self._on_enter_action_executor: Optional[OnEnterActionExecutor] = None
        self._stage_description_generator: Optional[StageDescriptionGenerator] = None
        self._event_stage_processor: Optional[EventStageProcessor] = None
        self._event_action_processor: Optional[EventActionProcessor] = None
        self._character_action_processor: Optional[CharacterActionProcessor] = None
        self._character_view_service: Optional[CharacterViewService] = None
        self._party_action_processor: Optional[PartyActionProcessor] = None

        # Цикл мирового тика
        self._world_tick_task: Optional[asyncio.Task] = None
        self._tick_interval_seconds: float = settings.get('world_tick_interval_seconds', 60.0)

        print("GameManager initialized.\n")

    async def setup(self) -> None:
        print("GameManager: Running setup…")
        try:
            # 1) Подключаемся к базе и инициализируем схему
            self._db_adapter = SqliteAdapter(self._db_path)
            await self._db_adapter.connect()
            await self._db_adapter.initialize_database()
            print("GameManager: Database setup complete.")

            # 2) Импортируем и создаём менеджеры
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
            from bot.services.openai_service import OpenAIService
            from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
            from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
            from bot.game.event_processors.event_stage_processor import EventStageProcessor
            from bot.game.event_processors.event_action_processor import EventActionProcessor
            from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
            from bot.game.character_processors.character_action_processor import CharacterActionProcessor
            from bot.game.character_processors.character_view_service import CharacterViewService
            from bot.game.party_processors.party_action_processor import PartyActionProcessor
            from bot.game.managers.persistence_manager import PersistenceManager
            from bot.game.command_router import CommandRouter

            # Core managers
            self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}))
            self.time_manager = TimeManager(db_adapter=self._db_adapter, settings=self._settings.get('time_settings', {}))
            self.location_manager = LocationManager(db_adapter=self._db_adapter, settings=self._settings.get('location_settings', {}))
            self.event_manager = EventManager(db_adapter=self._db_adapter, settings=self._settings.get('event_settings', {}))
            self.character_manager = CharacterManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('character_settings', {}),
                location_manager=self.location_manager,
                rule_engine=self.rule_engine
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

            # Зависимые менеджеры
            self.item_manager = ItemManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('item_settings', {}),
                location_manager=self.location_manager,
                rule_engine=self.rule_engine
            )
            self.status_manager = StatusManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('status_settings', {}),
                rule_engine=self.rule_engine,
                time_manager=self.time_manager
            )
            self.combat_manager = CombatManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('combat_settings', {}),
                rule_engine=self.rule_engine,
                character_manager=self.character_manager,
                status_manager=self.status_manager,
                item_manager=self.item_manager
            )
            self.crafting_manager = CraftingManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('crafting_settings', {}),
                item_manager=self.item_manager,
                character_manager=self.character_manager,
                time_manager=self.time_manager,
                rule_engine=self.rule_engine
            )
            self.economy_manager = EconomyManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('economy_settings', {}),
                item_manager=self.item_manager,
                location_manager=self.location_manager,
                character_manager=self.character_manager,
                rule_engine=self.rule_engine,
                time_manager=self.time_manager
            )
            self.npc_manager = NpcManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('npc_settings', {}),
                item_manager=self.item_manager,
                rule_engine=self.rule_engine,
                combat_manager=self.combat_manager,
                status_manager=self.status_manager
            )
            self.party_manager = PartyManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('party_settings', {}),
                character_manager=self.character_manager,
                npc_manager=self.npc_manager
            )

            # Внедряем зависимости в CharacterManager
            self.character_manager._status_manager = self.status_manager
            self.character_manager._party_manager = self.party_manager
            self.character_manager._combat_manager = self.combat_manager

            print("GameManager: Dependent managers instantiated.")

            # Процессоры и роутер команд
            self._on_enter_action_executor = OnEnterActionExecutor(
                npc_manager=self.npc_manager,
                item_manager=self.item_manager,
                combat_manager=self.combat_manager,
                status_manager=self.status_manager
            )
            self._stage_description_generator = StageDescriptionGenerator(openai_service=self.openai_service)
            self._event_stage_processor = EventStageProcessor(
                on_enter_action_executor=self._on_enter_action_executor,
                stage_description_generator=self._stage_description_generator,
                character_manager=self.character_manager,
                loc_manager=self.location_manager,
                rule_engine=self.rule_engine,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager
            )
            self._event_action_processor = EventActionProcessor(
                event_stage_processor=self._event_stage_processor,
                event_manager=self.event_manager,
                character_manager=self.character_manager,
                loc_manager=self.location_manager,
                rule_engine=self.rule_engine,
                openai_service=self.openai_service,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager
            )
            self._character_action_processor = CharacterActionProcessor(
                character_manager=self.character_manager,
                send_callback_factory=self._get_discord_send_callback,
                item_manager=self.item_manager,
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                time_manager=self.time_manager,
                combat_manager=self.combat_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager,
                npc_manager=self.npc_manager,
                event_stage_processor=self._event_stage_processor,
                event_action_processor=self._event_action_processor
            )
            self._character_view_service = CharacterViewService(
                character_manager=self.character_manager,
                item_manager=self.item_manager,
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                status_manager=self.status_manager,
                party_manager=self.party_manager
            )
            self._party_action_processor = PartyActionProcessor(
                party_manager=self.party_manager,
                send_callback_factory=self._get_discord_send_callback,
                rule_engine=self.rule_engine,
                location_manager=self.location_manager,
                character_manager=self.character_manager,
                npc_manager=self.npc_manager,
                time_manager=self.time_manager,
                combat_manager=self.combat_manager,
                event_stage_processor=self._event_stage_processor
            )
            if self.party_manager is None:
                self._party_action_processor = None

            self._persistence_manager = PersistenceManager(
                db_adapter=self._db_adapter,
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
            )

            self._world_simulation_processor = WorldSimulationProcessor(
                event_manager=self.event_manager,
                character_manager=self.character_manager,
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                openai_service=self.openai_service,
                event_stage_processor=self._event_stage_processor,
                event_action_processor=self._event_action_processor,
                persistence_manager=self._persistence_manager,
                settings=self._settings,
                send_callback_factory=self._get_discord_send_callback,
                character_action_processor=self._character_action_processor,
                party_action_processor=self._party_action_processor,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                crafting_manager=self.crafting_manager,
                economy_manager=self.economy_manager
            )

            self._command_router = CommandRouter(
                character_manager=self.character_manager,
                event_manager=self.event_manager,
                event_action_processor=self._event_action_processor,
                event_stage_processor=self._event_stage_processor,
                persistence_manager=self._persistence_manager,
                settings=self._settings,
                world_simulation_processor=self._world_simulation_processor,
                send_callback_factory=self._get_discord_send_callback,
                character_action_processor=self._character_action_processor,
                character_view_service=self._character_view_service,
                party_action_processor=self._party_action_processor,
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                openai_service=self.openai_service,
                item_manager=self.item_manager,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager,
                crafting_manager=self.crafting_manager,
                economy_manager=self.economy_manager
            )

            # 5) Загрузка состояния и запуск цикла тика мира
            await self._persistence_manager.load_game_state(
                time_manager=self.time_manager,
                event_manager=self.event_manager,
                character_manager=self.character_manager,
                location_manager=self.location_manager,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                status_manager=self.status_manager,
                crafting_manager=self.crafting_manager,
                economy_manager=self.economy_manager,
                party_manager=self.party_manager
            )
            self._world_tick_task = asyncio.create_task(self._world_tick_loop())
            print("GameManager: Setup complete.")

        except Exception as e:
            print(f"GameManager: ❌ CRITICAL ERROR during setup: {e}")
            traceback.print_exc()
            raise

    async def handle_discord_message(self, message: Message) -> None:
        if message.author.bot:
            return
        if not self._command_router:
            print(f"GameManager: Warning: CommandRouter not available, message '{message.content}' dropped.")
            return
        print(f"GameManager: Passing message from {message.author.name} to CommandRouter: '{message.content}'")
        try:
            await self._command_router.route(message)
        except Exception as e:
            print(f"GameManager: Error handling message '{message.content}': {e}")
            traceback.print_exc()

    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback:
        async def _send(content: str = "", **kwargs: Any) -> None:
            print(f"--- DIAGNOSTIC: _send function executed for channel {channel_id}. Accepts kwargs. ---")
            channel = self._discord_client.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(content, **kwargs)
                except Exception as e:
                    print(f"GameManager: Error sending message to channel {channel_id}: {e}")
                    traceback.print_exc()
            else:
                print(f"GameManager: Warning: Channel {channel_id} not found. Kwargs: {kwargs}")
        return _send

    async def _world_tick_loop(self) -> None:
        print(f"GameManager: Starting world tick loop with interval {self._tick_interval_seconds} seconds.")
        try:
            while True:
                await asyncio.sleep(self._tick_interval_seconds)
                if self._world_simulation_processor:
                    try:
                        await self._world_simulation_processor.process_tick(self._tick_interval_seconds)
                    except Exception as e:
                        print(f"GameManager: Error during world simulation tick: {e}")
                        traceback.print_exc()
        except asyncio.CancelledError:
            print("GameManager: World tick loop cancelled.")
        except Exception as e:
            print(f"GameManager: Critical error in world tick loop: {e}")
            traceback.print_exc()

    async def shutdown(self) -> None:
        print("GameManager: Running shutdown...")
        # Останавливаем цикл тика мира
        if self._world_tick_task:
            self._world_tick_task.cancel()
            try:
                await self._world_tick_task
            except asyncio.CancelledError:
                pass

        # Сохраняем состояние
        if self._persistence_manager:
            try:
                await self._persistence_manager.save_game_state()
                print("GameManager: Game state saved on shutdown.")
            except Exception as e:
                print(f"GameManager: Error saving game state on shutdown: {e}")
                traceback.print_exc()

        # Закрываем соединение с БД
        if self._db_adapter:
            try:
                await self._db_adapter.close()
                print("GameManager: Database connection closed.")
            except Exception as e:
                print(f"GameManager: Error closing database adapter: {e}")
                traceback.print_exc()

        print("GameManager: Shutdown complete.")

# --- Конец класса GameManager ---
