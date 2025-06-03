# bot/game/managers/game_manager.py

print("--- Начинается загрузка: game_manager.py")
import asyncio
import traceback
# Импорт базовых типов
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set
# Импорт TYPE_CHECKING
from typing import TYPE_CHECKING

import discord # For discord.abc.Messageable
# Импорт для Discord Client и Message, если они используются для аннотаций
# Use string literal if these are only used for type hints to avoid import cycles
from discord import Client # Direct import if Client is instantiated or directly used outside type hints
# from discord import Message # Use string literal if only used in type hints like message: Message


# Адаптер для работы с SQLite - Прямой импорт нужен, т.к. он инстанциируется здесь
from bot.database.sqlite_adapter import SqliteAdapter
from bot.services.db_service import DBService # Ensure DBService is imported for runtime


if TYPE_CHECKING:
    # --- Импорты для Type Checking ---
    # Discord types used in method signatures
    from discord import Message # Used in handle_discord_message

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
    # Обработчики команд
    from bot.game.command_handlers.party_handler import PartyCommandHandler # <--- ТИПИЗАЦИЯ PartyCommandHandler
    # Роутер команд
    from bot.game.command_router import CommandRouter
    from bot.game.managers.game_manager import GameManager # Add this line
    
    # Новые менеджеры и сервисы для TYPE_CHECKING
    from bot.game.managers.ability_manager import AbilityManager # Added for type hint
    from bot.game.managers.spell_manager import SpellManager # Added for type hint
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.services.campaign_loader import CampaignLoader
    from bot.game.services.consequence_processor import ConsequenceProcessor
    from bot.services.nlu_data_service import NLUDataService # For NLU Data Service
    from bot.game.conflict_resolver import ConflictResolver
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator


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
        self._db_adapter: Optional[SqliteAdapter] = None
        self._persistence_manager: Optional["PersistenceManager"] = None
        self._world_simulation_processor: Optional["WorldSimulationProcessor"] = None
        self._command_router: Optional["CommandRouter"] = None

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
        self.conflict_resolver: Optional["ConflictResolver"] = None
        
        # Новые менеджеры и сервисы
        self.quest_manager: Optional["QuestManager"] = None
        self.relationship_manager: Optional["RelationshipManager"] = None
        self.dialogue_manager: Optional["DialogueManager"] = None
        self.game_log_manager: Optional["GameLogManager"] = None
        self.campaign_loader: Optional["CampaignLoader"] = None
        self.consequence_processor: Optional["ConsequenceProcessor"] = None
        self.nlu_data_service: Optional["NLUDataService"] = None # For NLU Data Service
        self.ability_manager: Optional["AbilityManager"] = None # Added
        self.spell_manager: Optional["SpellManager"] = None   # Added
        self.prompt_context_collector: Optional["PromptContextCollector"] = None
        self.multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None

        # Процессоры и вспомогательные сервисы (используем строковые литералы)
        self._on_enter_action_executor: Optional["OnEnterActionExecutor"] = None
        self._stage_description_generator: Optional["StageDescriptionGenerator"] = None
        self._event_stage_processor: Optional["EventStageProcessor"] = None
        self._event_action_processor: Optional["EventActionProcessor"] = None
        self._character_action_processor: Optional["CharacterActionProcessor"] = None
        self._character_view_service: Optional["CharacterViewService"] = None
        self._party_action_processor: Optional["PartyActionProcessor"] = None
        self._party_command_handler: Optional["PartyCommandHandler"] = None # <--- Добавили атрибут для PartyCommandHandler

        # Цикл мирового тика
        self._world_tick_task: Optional[asyncio.Task] = None
        self._tick_interval_seconds: float = settings.get('world_tick_interval_seconds', 60.0)

        # Список ID активных гильдий (нужен для PersistenceManager load/save)
        self._active_guild_ids: List[str] = [str(gid) for gid in self._settings.get('active_guild_ids', [])] # Убедимся, что ID гильдий - строки


        print("GameManager initialized.\n")

    async def setup(self) -> None:
        print("GameManager: Running setup…")
        try:
            # 1) Инициализируем DBService (который внутри себя инициализирует SqliteAdapter)
            # и подключаемся к базе, инициализируем схему.
            self.db_service = DBService(db_path=self._db_path)
            await self.db_service.connect()
            await self.db_service.initialize_database() # This runs migrations via adapter
            self._db_adapter = self.db_service.adapter # Get the adapter instance if needed directly by other managers
            print("GameManager: DBService initialized, connected, and database schema updated.")

            # 2) Импортируем классы менеджеров и процессоров для их ИНСТАНЦИАЦИИ
            # ЭТИ ИМПОРТЫ НУЖНЫ ЗДЕСЬ ДЛЯ RUNTIME, т.к. мы создаем экземпляры!
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
            # Обработчики команд
            from bot.game.command_handlers.party_handler import PartyCommandHandler # <--- ИМПОРТИРУЕМ PartyCommandHandler для инстанциации
            
            # Новые импорты для инстанциации
            from bot.game.managers.quest_manager import QuestManager
            from bot.game.managers.relationship_manager import RelationshipManager
            from bot.game.managers.dialogue_manager import DialogueManager
            from bot.game.managers.game_log_manager import GameLogManager
            from bot.game.services.campaign_loader import CampaignLoader
            from bot.game.services.consequence_processor import ConsequenceProcessor
            from bot.services.nlu_data_service import NLUDataService # Import for instantiation
            
            # Conflict Resolver and its data
            from bot.game.conflict_resolver import ConflictResolver
            from bot.game.models.rules_config_definition import EXAMPLE_RULES_CONFIG
            from bot.ai.prompt_context_collector import PromptContextCollector
            from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    # from bot.services.db_service import DBService # This can be removed from TYPE_CHECKING if imported above

# Ensure no duplicate or misplaced DBService import within methods or other blocks

            # Core managers (создание экземпляров)
            self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}))
            self.time_manager = TimeManager(db_adapter=self._db_adapter, settings=self._settings.get('time_settings', {}))
            self.location_manager = LocationManager(db_adapter=self._db_adapter, settings=self._settings.get('location_settings', {}))
            self.event_manager = EventManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('event_settings', {}),
                openai_service=self.openai_service
                # multilingual_prompt_generator will be set later
            )
            # CharacterManager (создание экземпляра и внедрение части зависимостей)
            self.character_manager = CharacterManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('character_settings', {}),
                location_manager=self.location_manager, # Внедрение location_manager
                rule_engine=self.rule_engine # Внедрение rule_engine
                # Остальные зависимости CharacterManager внедряются ниже (circular dependencies)
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
                if not self.openai_service.is_available(): # Добавлена проверка доступности API ключа/модели
                     print("GameManager: Warning: OpenAIService settings incomplete or invalid.")
                     self.openai_service = None # Устанавливаем в None, если не настроен
                else:
                    print("GameManager: OpenAIService instantiated and available.")

            except Exception as e:
                print(f"GameManager: Warning: Failed to instantiate OpenAIService ({e})")
                self.openai_service = None

            # Зависимые менеджеры (создание экземпляров с внедрением зависимостей)
            self.item_manager = ItemManager(
                db_adapter=self._db_adapter, settings=self._settings.get('item_settings', {}),
                location_manager=self.location_manager, rule_engine=self.rule_engine
            )
            self.status_manager = StatusManager(
                db_adapter=self._db_adapter, settings=self._settings.get('status_settings', {}),
                rule_engine=self.rule_engine, time_manager=self.time_manager
            )
            self.combat_manager = CombatManager(
                db_adapter=self._db_adapter, settings=self._settings.get('combat_settings', {}),
                rule_engine=self.rule_engine, character_manager=self.character_manager,
                status_manager=self.status_manager, item_manager=self.item_manager
            )
            self.crafting_manager = CraftingManager(
                db_adapter=self._db_adapter, settings=self._settings.get('crafting_settings', {}),
                item_manager=self.item_manager, character_manager=self.character_manager,
                time_manager=self.time_manager, rule_engine=self.rule_engine
            )
            self.economy_manager = EconomyManager(
                db_adapter=self._db_adapter, settings=self._settings.get('economy_settings', {}),
                item_manager=self.item_manager, location_manager=self.location_manager,
                character_manager=self.character_manager, rule_engine=self.rule_engine, time_manager=self.time_manager
            )
            self.npc_manager = NpcManager(
                db_adapter=self._db_adapter, settings=self._settings.get('npc_settings', {}),
                item_manager=self.item_manager, rule_engine=self.rule_engine,
                combat_manager=self.combat_manager, status_manager=self.status_manager,
                # dialogue_manager, location_manager, game_log_manager are already passed later via direct attribute assignment
                # Add the new AI services here:
                openai_service=self.openai_service # Pass the instance
            )
            self.party_manager = PartyManager(
                db_adapter=self._db_adapter, settings=self._settings.get('party_settings', {}),
                character_manager=self.character_manager, npc_manager=self.npc_manager
                # PartyManager может нуждаться в других менеджерах (Combat?) - проверить его __init__
            )

            # Внедряем зависимости в CharacterManager (те, которые были circular dependencies при создании)
            if self.character_manager:
                 self.character_manager._status_manager = self.status_manager
                 self.character_manager._party_manager = self.party_manager
                 self.character_manager._combat_manager = self.combat_manager
                 self.character_manager._dialogue_manager = self.dialogue_manager # New
                 self.character_manager._relationship_manager = self.relationship_manager # New
                 self.character_manager._game_log_manager = self.game_log_manager # New


            print("GameManager: Dependent managers instantiated.")

            # Новые менеджеры и сервисы (продолжение)
            self.game_log_manager = GameLogManager(db_adapter=self._db_adapter, settings=self._settings.get('game_log_settings'))
            self.relationship_manager = RelationshipManager(db_adapter=self._db_adapter, settings=self._settings.get('relationship_settings'))

            # Instantiate CampaignLoader with DBService
            self.campaign_loader = CampaignLoader(settings=self._settings, db_service=self.db_service)
            print("GameManager: CampaignLoader instantiated with DBService.")

            # Populate game data using CampaignLoader
            # This needs to happen after DB init but before other managers might rely on this data.
            if self._active_guild_ids:
                for guild_id_str in self._active_guild_ids:
                    print(f"GameManager: Populating game data for guild_id: {guild_id_str}...")
                    # campaign_identifier can be passed if specific campaigns per guild are a feature.
                    await self.campaign_loader.populate_all_game_data(guild_id=guild_id_str, campaign_identifier=None)
            else:
                print("GameManager: No active_guild_ids configured. Attempting to load global items only.")
                # Call with a placeholder or handle in CampaignLoader if guild_id is None for global items
                await self.campaign_loader.load_and_populate_items() # Ensures global items are loaded

            self.dialogue_manager = DialogueManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('dialogue_settings', {}),
                character_manager=self.character_manager,
                npc_manager=self.npc_manager,
                rule_engine=self.rule_engine,
                time_manager=self.time_manager,
                openai_service=self.openai_service,
                relationship_manager=self.relationship_manager
            )
            
            # NpcManager update (add dialogue_manager, location_manager, game_log_manager)
            if self.npc_manager: # Check if npc_manager was instantiated
                self.npc_manager._dialogue_manager = self.dialogue_manager
                self.npc_manager._location_manager = self.location_manager # Ensure this was intended
                self.npc_manager._game_log_manager = self.game_log_manager


            self.consequence_processor = ConsequenceProcessor(
                quest_manager=None, # To be set after QuestManager is created
                character_manager=self.character_manager,
                npc_manager=self.npc_manager,
                item_manager=self.item_manager,
                location_manager=self.location_manager, # Added LocationManager
                event_manager=self.event_manager,
                status_manager=self.status_manager,
                rule_engine=self.rule_engine,
                economy_manager=self.economy_manager, # Added EconomyManager
                relationship_manager=self.relationship_manager, # Added RelationshipManager
                game_log_manager=self.game_log_manager # Added GameLogManager
                # game_state will be self (GameManager), but pass None for now if not used in __init__
            )

            self.quest_manager = QuestManager(
                db_adapter=self._db_adapter,
                settings=self._settings.get('quest_settings', {}),
                consequence_processor=self.consequence_processor,
                character_manager=self.character_manager,
                game_log_manager=self.game_log_manager,
                # Add openai_service here
                openai_service=self.openai_service
                # multilingual_prompt_generator will be set later
            )

            if self.consequence_processor is not None and self.quest_manager is not None:
                self.consequence_processor._quest_manager = self.quest_manager
            
            # NLUDataService
            if self._db_adapter:
                self.nlu_data_service = NLUDataService(db_adapter=self._db_adapter)
                print("GameManager: NLUDataService instantiated.")
            else:
                self.nlu_data_service = None
                print("GameManager: Warning: DB adapter is None, NLUDataService not instantiated.")

            print("GameManager: New services and managers instantiated.")

            # Процессоры и роутер команд (создание экземпляров)
            # Внедрение зависимостей в процессоры
            self._on_enter_action_executor = OnEnterActionExecutor(
                npc_manager=self.npc_manager, item_manager=self.item_manager,
                combat_manager=self.combat_manager, status_manager=self.status_manager
                # OnEnterActionExecutor может нуждаться в других менеджерах (Character?, Party?) - проверить его __init__
            )
            # StageDescriptionGenerator
            self._stage_description_generator = StageDescriptionGenerator(openai_service=self.openai_service)

            # EventStageProcessor
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
                # EventStageProcessor ожидает event_action_processor, dialogue_manager, crafting_manager - проверить __init__
            )

            # EventActionProcessor
            self._event_action_processor = EventActionProcessor(
                event_stage_processor=self._event_stage_processor,
                event_manager=self.event_manager, character_manager=self.character_manager,
                loc_manager=self.location_manager, rule_engine=self.rule_engine,
                openai_service=self.openai_service,
                npc_manager=self.npc_manager, combat_manager=self.combat_manager,
                item_manager=self.item_manager, time_manager=self.time_manager,
                status_manager=self.status_manager,
                send_callback_factory=self._get_discord_send_callback,
                dialogue_manager=getattr(self, 'dialogue_manager', None),
                crafting_manager=self.crafting_manager,
                on_enter_action_executor=self._on_enter_action_executor,
                stage_description_generator=self._stage_description_generator,
            )

            # CharacterActionProcessor
            self._character_action_processor = CharacterActionProcessor(
                character_manager=self.character_manager, send_callback_factory=self._get_discord_send_callback,
                item_manager=self.item_manager, location_manager=self.location_manager,
                rule_engine=self.rule_engine, time_manager=self.time_manager,
                combat_manager=self.combat_manager, status_manager=self.status_manager,
                party_manager=self.party_manager, npc_manager=self.npc_manager,
                event_stage_processor=self._event_stage_processor, event_action_processor=self._event_action_processor
                # TODO: CharacterActionProcessor может нуждаться в crafting, economy, dialogue? Проверить __init__
            )

            # CharacterViewService
            self._character_view_service = CharacterViewService(
                character_manager=self.character_manager, item_manager=self.item_manager,
                location_manager=self.location_manager, rule_engine=self.rule_engine,
                status_manager=self.status_manager, party_manager=self.party_manager
                # CharacterViewService может нуждаться в других менеджерах/сервисах (например, Formatter?) - проверить __init__
            )

            # PartyActionProcessor
            self._party_action_processor = PartyActionProcessor(
                party_manager=self.party_manager, send_callback_factory=self._get_discord_send_callback,
                rule_engine=self.rule_engine, location_manager=self.location_manager,
                character_manager=self.character_manager, npc_manager=self.npc_manager,
                time_manager=self.time_manager, combat_manager=self.combat_manager,
                event_stage_processor=self._event_stage_processor
                # TODO: PartyActionProcessor может нуждаться в других менеджерах (event_action?) - проверить __init__
            )
            # В оригинальном коде PartyActionProcessor обнулялся, если party_manager == None. Сохраним эту логику.
            if self.party_manager is None:
                self._party_action_processor = None
                print("GameManager: Warning: PartyManager not available, PartyActionProcessor is None.")
            
            # Instantiate ConflictResolver
            # For NotificationService, using a placeholder string or a mock object for now.
            # In a real scenario, a NotificationService instance would be passed.
            mock_notification_service = "PlaceholderNotificationService" # Or an actual mock instance
            self.conflict_resolver = ConflictResolver(
                rule_engine=self.rule_engine,
                rules_config_data=EXAMPLE_RULES_CONFIG, # Using example data for now
                notification_service=mock_notification_service
            )
            print("GameManager: ConflictResolver instantiated.")

            # --- Создание экземпляра PartyCommandHandler ---
            # PartyCommandHandler ожидает character_manager, party_manager, party_action_processor, settings (обязательные), npc_manager (опциональный)
            # Все эти зависимости уже созданы выше
            if self.character_manager and self.party_manager and self._party_action_processor: # Проверяем наличие обязательных для PartyCommandHandler
                 self._party_command_handler = PartyCommandHandler(
                     character_manager=self.character_manager,
                     party_manager=self.party_manager,
                     party_action_processor=self._party_action_processor,
                     settings=self._settings, # Передаем общие настройки
                     npc_manager=self.npc_manager # Передаем опциональный npc_manager
                     # TODO: Передать другие опциональные зависимости PartyCommandHandler, если есть (party_view_service?)
                     # party_view_service = ... # Если PartyViewService создан и используется
                 )
                 print("GameManager: PartyCommandHandler instantiated.")
            else:
                 self._party_command_handler = None
                 print("GameManager: Warning: Cannot instantiate PartyCommandHandler. Missing one or more required managers (Character, Party, PartyActionProcessor).")


            # PersistenceManager (создание экземпляра с внедрением зависимостей)
            # Он принимает db_adapter и все менеджеры, чье состояние координирует
            if self._db_adapter: # Убедимся, что db_adapter был создан
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
                     party_manager=self.party_manager # Может быть None
                     # TODO: PersistenceManager может нуждаться в других менеджерах
                 )
                 print("GameManager: PersistenceManager instantiated.")
            else:
                 self._persistence_manager = None
                 print("GameManager: Warning: DB adapter is None, PersistenceManager not instantiated.")


            # WorldSimulationProcessor
            self._world_simulation_processor = WorldSimulationProcessor(
                event_manager=self.event_manager, character_manager=self.character_manager,
                location_manager=self.location_manager, rule_engine=self.rule_engine,
                openai_service=self.openai_service, event_stage_processor=self._event_stage_processor,
                event_action_processor=self._event_action_processor, persistence_manager=self._persistence_manager, # Может быть None
                settings=self._settings, send_callback_factory=self._get_discord_send_callback,
                character_action_processor=self._character_action_processor, party_action_processor=self._party_action_processor, # Может быть None
                npc_manager=self.npc_manager, combat_manager=self.combat_manager,
                item_manager=self.item_manager, time_manager=self.time_manager,
                status_manager=self.status_manager, crafting_manager=self.crafting_manager,
                economy_manager=self.economy_manager,
                # New injections for WorldSimulationProcessor
                dialogue_manager=self.dialogue_manager,
                quest_manager=self.quest_manager,
                relationship_manager=self.relationship_manager,
                game_log_manager=self.game_log_manager,
                # Add multilingual_prompt_generator here
                multilingual_prompt_generator=self.multilingual_prompt_generator
            )
            print("GameManager: WorldSimulationProcessor instantiated.")


            # CommandRouter
            # CommandRouter ожидает party_command_handler как ОБЯЗАТЕЛЬНЫЙ аргумент
            # Убедимся, что PartyCommandHandler был успешно создан
            if self._party_command_handler:
                self._command_router = CommandRouter(
                    character_manager=self.character_manager, event_manager=self.event_manager,
                    event_action_processor=self._event_action_processor, event_stage_processor=self._event_stage_processor,
                    persistence_manager=self._persistence_manager, # Может быть None
                    settings=self._settings, world_simulation_processor=self._world_simulation_processor,
                    send_callback_factory=self._get_discord_send_callback,
                    character_action_processor=self._character_action_processor, character_view_service=self._character_view_service,
                    party_action_processor=self._party_action_processor, # Может быть None
                    location_manager=self.location_manager, rule_engine=self.rule_engine,
                    openai_service=self.openai_service, # Может быть None
                    item_manager=self.item_manager, npc_manager=self.npc_manager,
                    combat_manager=self.combat_manager, time_manager=self.time_manager,
                    status_manager=self.status_manager, party_manager=self.party_manager, # Может быть None
                    crafting_manager=self.crafting_manager, economy_manager=self.economy_manager, # Already present
                    # --- Передаем созданный PartyCommandHandler ---
                    party_command_handler=self._party_command_handler, # <--- ДОБАВЛЕНО!
                    conflict_resolver=self.conflict_resolver, # Pass ConflictResolver to CommandRouter
                    game_manager=self, # Add this argument
                    # New injections for CommandRouter
                    quest_manager=self.quest_manager,
                    dialogue_manager=self.dialogue_manager,
                    relationship_manager=self.relationship_manager,
                    game_log_manager=self.game_log_manager
                    # TODO: Добавить view services, которые могут понадобиться в context (например, party_view_service)
                    # party_view_service=...
                    # location_view_service=...
                )
                print("GameManager: CommandRouter instantiated.")
            else:
                 self._command_router = None
                 print("GameManager: Warning: CommandRouter not instantiated because PartyCommandHandler is not available.")


            # 5) Загрузка состояния
            # Загрузка происходит ТОЛЬКО если PersistenceManager доступен
            if self._persistence_manager:
                print("GameManager: Loading game state...")
                active_guild_ids: List[str] = self._active_guild_ids

                load_context_kwargs: Dict[str, Any] = {
                    # Передаем все инстанции менеджеров/процессоров (могут быть None)
                    'rule_engine': self.rule_engine, 'time_manager': self.time_manager,
                    'location_manager': self.location_manager, 'event_manager': self.event_manager,
                    'character_manager': self.character_manager, 'item_manager': self.item_manager,
                    'status_manager': self.status_manager, 'combat_manager': self.combat_manager,
                    'crafting_manager': self.crafting_manager, 'economy_manager': self.economy_manager,
                    'npc_manager': self.npc_manager, 'party_manager': self.party_manager,
                    'openai_service': self.openai_service,
                    # New managers/services for load_context_kwargs
                    'quest_manager': self.quest_manager,
                    'relationship_manager': self.relationship_manager,
                    'dialogue_manager': self.dialogue_manager,
                    'game_log_manager': self.game_log_manager,
                    'campaign_loader': self.campaign_loader,
                    'consequence_processor': self.consequence_processor,
                    'on_enter_action_executor': self._on_enter_action_executor,
                    'stage_description_generator': self._stage_description_generator,
                    'event_stage_processor': self._event_stage_processor,
                    'event_action_processor': self._event_action_processor,
                    'character_action_processor': self._character_action_processor,
                    'character_view_service': self._character_view_service,
                    'party_action_processor': self._party_action_processor,
                    'persistence_manager': self._persistence_manager,
                    'world_simulation_processor': self._world_simulation_processor,
                    'conflict_resolver': self.conflict_resolver, # For loading context
                    'db_adapter': self._db_adapter, # Still passing adapter directly if some old components need it
                    'db_service': self.db_service,   # Pass DBService as well
                    'nlu_data_service': self.nlu_data_service, # Pass NLUDataService
                    'prompt_context_collector': self.prompt_context_collector,
                    'multilingual_prompt_generator': self.multilingual_prompt_generator,
                    'send_callback_factory': self._get_discord_send_callback,
                    'settings': self._settings,
                    'discord_client': self._discord_client,
                    # TODO: Добавьте любые другие данные из setup, которые могут потребоваться при загрузке/перестройке
                }

                # Load game state *after* initial data (items, locations, default NPCs) is populated.
                # This ensures that loaded game states referencing these entities find them in the DB.
                await self._persistence_manager.load_game_state(
                    guild_ids=active_guild_ids,
                    **load_context_kwargs
                )
                print("GameManager: Game state loaded.")
            else:
                print("GameManager: Warning: Skipping state load, PersistenceManager not available.")

            # Initial data population is done before this point.

            # --- Instantiate AI Content Generation Services ---
            if self.character_manager and \
               self.npc_manager and \
               self.quest_manager and \
               self.relationship_manager and \
               self.item_manager and \
               self.location_manager and \
               self.event_manager and \
               hasattr(self, 'ability_manager') and self.ability_manager and \
               hasattr(self, 'spell_manager') and self.spell_manager: # Check for new ability/spell managers

                print("GameManager: Instantiating PromptContextCollector...")
                self.prompt_context_collector = PromptContextCollector(
                    settings=self._settings, # Pass the main settings dictionary
                    character_manager=self.character_manager,
                    npc_manager=self.npc_manager,
                    quest_manager=self.quest_manager,
                    relationship_manager=self.relationship_manager,
                    item_manager=self.item_manager,
                    location_manager=self.location_manager,
                    ability_manager=self.ability_manager, # Pass AbilityManager
                    spell_manager=self.spell_manager,     # Pass SpellManager
                    event_manager=self.event_manager
                )
                print("GameManager: PromptContextCollector instantiated.")

                # Determine main bot language
                # Assumes 'main_language_code' is in the global settings file (data/settings.json)
                # and loaded into self._settings
                main_bot_language = self._settings.get('main_language_code', 'ru') # Default to 'ru'
                print(f"GameManager: Main bot language code: {main_bot_language}")

                print("GameManager: Instantiating MultilingualPromptGenerator...")
                self.multilingual_prompt_generator = MultilingualPromptGenerator(
                    context_collector=self.prompt_context_collector,
                    main_bot_language=main_bot_language
                )
                print("GameManager: MultilingualPromptGenerator instantiated.")
            else:
                self.prompt_context_collector = None
                self.multilingual_prompt_generator = None
                print("GameManager: Warning: Could not instantiate AI prompt generation services due to missing manager dependencies.")

            # Ensure these new services are passed to other components that might need them,
            # for example, WorldSimulationProcessor or CommandRouter if they directly trigger content generation.
            # Example: (Update constructor or add setters to these classes if they need the generator)
            # if self._world_simulation_processor and self.multilingual_prompt_generator:
            #     self._world_simulation_processor.set_prompt_generator(self.multilingual_prompt_generator)
            # if self._command_router and self.multilingual_prompt_generator:
            #     self._command_router.set_prompt_generator(self.multilingual_prompt_generator)

            if self.npc_manager and hasattr(self.npc_manager, '_multilingual_prompt_generator') and self.multilingual_prompt_generator:
                self.npc_manager._multilingual_prompt_generator = self.multilingual_prompt_generator
                print("GameManager: Assigned MultilingualPromptGenerator to NpcManager.")

            if self.quest_manager and hasattr(self.quest_manager, '_multilingual_prompt_generator') and self.multilingual_prompt_generator:
                self.quest_manager._multilingual_prompt_generator = self.multilingual_prompt_generator
                print("GameManager: Assigned MultilingualPromptGenerator to QuestManager.")

            if self.event_manager and hasattr(self.event_manager, '_multilingual_prompt_generator') and self.multilingual_prompt_generator:
                self.event_manager._multilingual_prompt_generator = self.multilingual_prompt_generator
                print("GameManager: Assigned MultilingualPromptGenerator to EventManager.")

            # 6) Запуск цикла тика мира
            # Запускаем цикл тика ТОЛЬКО если WorldSimulationProcessor доступен
            if self._world_simulation_processor:
                self._world_tick_task = asyncio.create_task(self._world_tick_loop())
                print("GameManager: World tick loop started.")
            else:
                 print("GameManager: Warning: Skipping world tick loop start, WorldSimulationProcessor not available.")

            print("GameManager: Setup complete.")

        except Exception as e:
            print(f"GameManager: ❌ CRITICAL ERROR during setup: {e}")
            traceback.print_exc()
            # Реализован корректный shutdown при ошибке setup
            try:
                 await self.shutdown() # Попытка корректно выключиться
            except Exception as shutdown_e:
                 print(f"GameManager: ❌ Error during shutdown initiated by setup failure: {shutdown_e}")
                 traceback.print_exc()


    async def handle_discord_message(self, message: "Message") -> None: # Added type hint for Message
        if message.author.bot:
            return
        if not self._command_router:
            print(f"GameManager: Warning: CommandRouter not available, message '{message.content}' dropped.")
            # Optional: Send error message to user if possible
            # The _get_discord_send_callback might fail if CommandRouter init failed critically
            # but let's try. Ensure message.channel exists.
            if message.channel:
                try:
                     send_callback = self._get_discord_send_callback(message.channel.id)
                     await send_callback(f"❌ Игра еще не полностью запущена. Попробуйте позже.", None)
                except Exception as cb_e:
                     print(f"GameManager: Error sending startup error message back to channel {message.channel.id}: {cb_e}")
            return

        # Check if the message starts with the command prefix before passing to router
        # CommandRouter route() method does this check internally, but doing it here
        # allows logging *only* messages that look like commands if needed.
        command_prefix = self._settings.get('command_prefix', '/') # Assuming prefix is in settings
        if message.content.startswith(command_prefix):
             print(f"GameManager: Passing command from {message.author.name} (ID: {message.author.id}, Guild: {message.guild.id if message.guild else 'DM'}, Channel: {message.channel.id}) to CommandRouter: '{message.content}'")
        else:
             # If it's not a command, might be game chat? Pass it to another handler?
             # Or simply ignore non-command messages in GameManager.
             # For now, CommandRouter ignores non-prefixed messages anyway.
             pass # Ignore non-command messages at this level


        try:
            # CommandRouter ожидает Discord Message object
            await self._command_router.route(message)
        except Exception as e:
            print(f"GameManager: Error handling message '{message.content}': {e}")
            traceback.print_exc()
            # CommandRouter.route should handle sending execution errors to the user.
            # If an error reaches here, it might be a critical failure *before* the handler was called
            # or an error *within* CommandRouter itself.
            # Sending a generic error message back is still a good idea.
            try:
                 if message.channel:
                      send_callback = self._get_discord_send_callback(message.channel.id)
                      # CommandRouter already logs detailed traceback and attempts user notification.
                      # This fallback message is less detailed to avoid spam/duplication if the router's
                      # error handling *did* work.
                      await send_callback(f"❌ Произошла внутренняя ошибка при обработке команды. Подробности в логах бота.", None)
                 else:
                      print(f"GameManager: Warning: Cannot send error message to user (DM channel or channel not found).")
            except Exception as cb_e:
                 print(f"GameManager: Error sending generic internal error message back to channel {message.channel.id}: {cb_e}")


    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback:
        channel_id_int = int(channel_id) # Пытаемся преобразовать на всякий случай

        async def _send(content: str = "", **kwargs: Any) -> None:
            channel = self._discord_client.get_channel(channel_id_int)
            if channel:
                if isinstance(channel, discord.abc.Messageable): # Added check
                    try:
                        await channel.send(content, **kwargs)
                    except Exception as e:
                        print(f"GameManager: Error sending message to channel {channel_id_int}: {e}")
                        traceback.print_exc()
                else:
                    print(f"GameManager: Warning: Channel {channel_id_int} is not Messageable (type: {type(channel)}).")
            else:
                print(f"GameManager: Warning: Channel {channel_id_int} not found in Discord client cache. Cannot send message. Kwargs: {kwargs}")

        return _send

    async def _world_tick_loop(self) -> None:
        print(f"GameManager: Starting world tick loop with interval {self._tick_interval_seconds} seconds.")
        try:
            while True:
                # Use sleep with a check to allow cancellation
                await asyncio.sleep(self._tick_interval_seconds)

                if self._world_simulation_processor:
                    try:
                        tick_context_kwargs: Dict[str, Any] = {
                            # Pass all available managers/processors (check if they are None)
                            'rule_engine': self.rule_engine, 'time_manager': self.time_manager,
                            'location_manager': self.location_manager, 'event_manager': self.event_manager,
                            'character_manager': self.character_manager, 'item_manager': self.item_manager,
                            'status_manager': self.status_manager, 'combat_manager': self.combat_manager,
                            'crafting_manager': self.crafting_manager, 'economy_manager': self.economy_manager,
                            'npc_manager': self.npc_manager, 'party_manager': self.party_manager,
                            'openai_service': self.openai_service,
                             # New managers/services for tick_context_kwargs
                            'quest_manager': self.quest_manager,
                            'relationship_manager': self.relationship_manager,
                            'dialogue_manager': self.dialogue_manager,
                            'game_log_manager': self.game_log_manager,
                            'consequence_processor': self.consequence_processor,
                            'campaign_loader': self.campaign_loader, # Though likely not used in tick directly
                            'on_enter_action_executor': self._on_enter_action_executor,
                            'stage_description_generator': self._stage_description_generator,
                            'event_stage_processor': self._event_stage_processor,
                            'event_action_processor': self._event_action_processor,
                            'character_action_processor': self._character_action_processor,
                            'character_view_service': self._character_view_service,
                            'party_action_processor': self._party_action_processor,
                            'persistence_manager': self._persistence_manager,
                            'conflict_resolver': self.conflict_resolver, # For tick context
                            'db_adapter': self._db_adapter,
                            'nlu_data_service': self.nlu_data_service, # Pass NLUDataService
                            'prompt_context_collector': self.prompt_context_collector,
                            'multilingual_prompt_generator': self.multilingual_prompt_generator,
                            'send_callback_factory': self._get_discord_send_callback,
                            'settings': self._settings,
                            'discord_client': self._discord_client,
                            # TODO: Другие менеджеры/процессоры/сервисы, нужные при тике
                        }
                        # Filter None values if process_world_tick cannot handle them
                        # tick_context_kwargs = {k: v for k, v in tick_context_kwargs.items() if v is not None}

                        await self._world_simulation_processor.process_world_tick(
                            game_time_delta=self._tick_interval_seconds,
                            **tick_context_kwargs
                        )
                    except Exception as e:
                        print(f"GameManager: ❌ Error during world simulation tick: {e}")
                        traceback.print_exc()
                        # TODO: Обработка ошибки тика (логирование, оповещение GM, остановка симуляции?)
                # else:
                #     print("GameManager: Warning: WorldSimulationProcessor is None. Skipping tick.")


        except asyncio.CancelledError:
            print("GameManager: World tick loop cancelled.")
        except Exception as e:
            print(f"GameManager: ❌ Critical error in world tick loop: {e}")
            traceback.print_exc()

    async def save_game_state_after_action(self, guild_id: str) -> None:
        """
        Saves the game state for a specific guild after an action has been processed.
        """
        if not self._persistence_manager:
            print(f"GameManager: PersistenceManager not available. Cannot save game state for guild {guild_id} after action.")
            return

        print(f"GameManager: Saving game state for guild {guild_id} after action...")
        try:
            save_context_kwargs: Dict[str, Any] = {
                'rule_engine': self.rule_engine, 'time_manager': self.time_manager,
                'location_manager': self.location_manager, 'event_manager': self.event_manager,
                'character_manager': self.character_manager, 'item_manager': self.item_manager,
                'status_manager': self.status_manager, 'combat_manager': self.combat_manager,
                'crafting_manager': self.crafting_manager, 'economy_manager': self.economy_manager,
                'npc_manager': self.npc_manager, 'party_manager': self.party_manager,
                'dialogue_manager': self.dialogue_manager,
                'quest_manager': self.quest_manager,
                'relationship_manager': self.relationship_manager,
                'game_log_manager': self.game_log_manager,
                'conflict_resolver': self.conflict_resolver,
                'prompt_context_collector': self.prompt_context_collector,
                'multilingual_prompt_generator': self.multilingual_prompt_generator,
                'db_adapter': self._db_adapter,
                'send_callback_factory': self._get_discord_send_callback,
                'settings': self._settings,
                'discord_client': self._discord_client,
            }
            await self._persistence_manager.save_game_state(
                guild_ids=[str(guild_id)],
                **save_context_kwargs
            )
            print(f"GameManager: Game state saved successfully for guild {guild_id} after action.")
        except Exception as e:
            print(f"GameManager: ❌ Error saving game state for guild {guild_id} after action: {e}")
            traceback.print_exc()


    async def shutdown(self) -> None:
        print("GameManager: Running shutdown...")
        if self._world_tick_task:
            print("GameManager: Cancelling world tick loop...")
            self._world_tick_task.cancel()
            try:
                # Ждем до 5 секунд, пока задача завершится
                await asyncio.wait_for(self._world_tick_task, timeout=5.0)
                print("GameManager: World tick loop task finished.")
            except asyncio.CancelledError:
                 print("GameManager: World tick loop task confirmed cancelled.")
            except asyncio.TimeoutError:
                 print("GameManager: Warning: Timeout waiting for world tick task to cancel.")
            except Exception as e:
                 print(f"GameManager: Error waiting for world tick task to complete after cancel: {e}")
                 traceback.print_exc()


        if self._persistence_manager:
            try:
                print("GameManager: Saving game state on shutdown...")
                active_guild_ids: List[str] = self._active_guild_ids

                save_context_kwargs: Dict[str, Any] = {
                    # Pass all available managers/processors (check if they are None)
                    'rule_engine': self.rule_engine, 'time_manager': self.time_manager,
                    'location_manager': self.location_manager, 'event_manager': self.event_manager,
                    'character_manager': self.character_manager, 'item_manager': self.item_manager,
                    'status_manager': self.status_manager, 'combat_manager': self.combat_manager,
                    'crafting_manager': self.crafting_manager, 'economy_manager': self.economy_manager,
                    'npc_manager': self.npc_manager, 'party_manager': self.party_manager,
                    # New managers for save_context_kwargs (match PersistenceManager __init__)
                    'dialogue_manager': self.dialogue_manager,
                    'quest_manager': self.quest_manager,
                    'relationship_manager': self.relationship_manager,
                    'game_log_manager': self.game_log_manager,
                    'conflict_resolver': self.conflict_resolver, # For save context
                    'prompt_context_collector': self.prompt_context_collector,
                    'multilingual_prompt_generator': self.multilingual_prompt_generator,
                    'db_adapter': self._db_adapter,
                    'send_callback_factory': self._get_discord_send_callback,
                    'settings': self._settings,
                    'discord_client': self._discord_client,
                    # TODO: Другие менеджеры/процессоры/сервисы, нужные при сохранении
                }
                # Optional: Filter None values from context if necessary for save_game_state
                # save_context_kwargs = {k: v for k, v in save_context_kwargs.items() if v is not None}


                if self._db_adapter: # Double check db_adapter availability
                    await self._persistence_manager.save_game_state(
                        guild_ids=active_guild_ids,
                        **save_context_kwargs
                    )
                    print("GameManager: Game state saved on shutdown.")
                else:
                     print("GameManager: Warning: Skipping state save on shutdown, DB adapter is None.")

            except Exception as e:
                print(f"GameManager: ❌ Error saving game state on shutdown: {e}")
                traceback.print_exc()


        if self._db_adapter:
            try:
                await self._db_adapter.close()
                print("GameManager: Database connection closed.")
            except Exception as e:
                print(f"GameManager: ❌ Error closing database adapter: {e}")
                traceback.print_exc()

        print("GameManager: Shutdown complete.")

    async def save_specific_entities(self, modified_entities: List[Any]) -> None:
        """
        Saves a list of specific modified entity objects using their respective managers.
        """
        if not modified_entities:
            return

        print(f"GameManager: Received {len(modified_entities)} entities for specific saving.")

        # Import models needed for isinstance checks INSIDE the method or at TYPE_CHECKING level
        # to avoid circular dependencies at module load time if GameManager is imported by models.
        # However, for runtime isinstance checks, they need to be available.
        # Assuming models are structured not to import GameManager directly.
        from bot.game.models.character import Character
        from bot.game.models.location import Location # Assuming Location model exists
        from bot.game.models.event import Event
        from bot.game.models.item import Item
        from bot.game.models.status_effect import StatusEffect
        from bot.game.models.npc import NPC
        from bot.game.models.party import Party

        for entity in modified_entities:
            entity_id = getattr(entity, 'id', 'UnknownID')
            guild_id_from_entity = getattr(entity, 'guild_id', None)

            if not guild_id_from_entity:
                # Attempt to get guild_id from context if available (e.g. from a Character or NPC's location)
                # This is a fallback and might not always be reliable.
                # Best if entities consistently have .guild_id
                if hasattr(entity, 'location_id') and self.location_manager and entity.location_id:
                    loc_instance = self.location_manager.get_location_instance(entity.location_id) # Needs guild for loc
                    # This path is tricky, get_location_instance needs guild_id itself.
                    # For now, we strongly rely on entity.guild_id
                    pass # Placeholder for more complex guild_id derivation

                if not guild_id_from_entity:
                    print(f"GameManager (save_specific_entities): Warning - Could not determine guild_id for entity ID {entity_id} of type {type(entity).__name__}. Skipping save.")
                    continue

            guild_id_str = str(guild_id_from_entity)

            try:
                if isinstance(entity, Character):
                    if self.character_manager:
                        await self.character_manager.save_character(entity, guild_id_str)
                    else: print(f"GameManager: CharacterManager not available. Cannot save Character {entity_id}.")

                elif isinstance(entity, NPC):
                    if self.npc_manager:
                        await self.npc_manager.save_npc(entity, guild_id_str)
                    else: print(f"GameManager: NpcManager not available. Cannot save NPC {entity_id}.")

                elif isinstance(entity, Party):
                    if self.party_manager:
                        await self.party_manager.save_party(entity, guild_id_str)
                    else: print(f"GameManager: PartyManager not available. Cannot save Party {entity_id}.")

                elif isinstance(entity, Location): # Actual Location model objects
                    if self.location_manager:
                        await self.location_manager.save_location(entity, guild_id_str)
                    else: print(f"GameManager: LocationManager not available. Cannot save Location {entity_id}.")

                elif isinstance(entity, dict) and 'template_id' in entity and entity.get('guild_id') == guild_id_str and 'state' in entity:
                    # This is a fallback for location instances if they are still dicts in some paths
                    if self.location_manager and hasattr(self.location_manager, 'save_location_instance_data'): # Requires specific method
                        # await self.location_manager.save_location_instance_data(entity, guild_id_str)
                        print(f"GameManager: Location instance (dict) {entity_id} would be saved by LocationManager if save_location_instance_data existed.")
                    elif self.location_manager and hasattr(self.location_manager, 'save_location'):
                         print(f"GameManager: Attempting to save location instance (dict) {entity_id} via save_location. This might fail if it expects a Location object.")
                         # This will likely fail if save_location expects a Location model object.
                         # For now, this path is mostly a placeholder unless Location objects are always passed.
                    else: print(f"GameManager: LocationManager not available or no suitable save method for location dict {entity_id}.")


                elif isinstance(entity, Event):
                    if self.event_manager:
                        await self.event_manager.save_event(entity, guild_id_str)
                    else: print(f"GameManager: EventManager not available. Cannot save Event {entity_id}.")

                elif isinstance(entity, Item):
                    if self.item_manager:
                        await self.item_manager.save_item(entity, guild_id_str)
                    else: print(f"GameManager: ItemManager not available. Cannot save Item {entity_id}.")

                elif isinstance(entity, StatusEffect):
                    if self.status_manager:
                        await self.status_manager.save_status_effect(entity, guild_id_str)
                    else: print(f"GameManager: StatusManager not available. Cannot save StatusEffect {entity_id}.")

                else:
                    print(f"GameManager (save_specific_entities): Unknown entity type for saving: {type(entity).__name__} (ID: {entity_id}). Skipping.")

            except Exception as e:
                print(f"GameManager (save_specific_entities): Error saving entity ID {entity_id} of type {type(entity).__name__} for guild {guild_id_str}: {e}")
                traceback.print_exc()

        print(f"GameManager: Finished specific saving for {len(modified_entities)} entities.")


print("DEBUG: game_manager.py module loaded.")
