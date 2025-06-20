# bot/game/managers/game_manager.py

import asyncio
import json
# import traceback # No longer used directly
import os
import io
import logging
import uuid
# from alembic.config import Config # Removed unused import
# from alembic import command # Removed unused import
from typing import Optional, Dict, Any, Callable, Awaitable, List, TYPE_CHECKING # Removed Set

from asyncpg import exceptions as asyncpg_exceptions
# from bot.database.postgres_adapter import SQLALCHEMY_DATABASE_URL as PG_URL_FOR_ALEMBIC # Not used here

import discord
from discord import Client

from bot.services.db_service import DBService
# from bot.ai.rules_schema import GameRules # Not used here
from bot.game.models.character import Character
from bot.database.models import RulesConfig, Player, PendingGeneration, GuildConfig, Location, QuestTable, QuestStepTable, Party
from bot.services.notification_service import NotificationService
from bot.game.managers.character_manager import CharacterManager, CharacterAlreadyExistsError
import random
# from sqlalchemy.future import select # Not directly used here
from bot.database.guild_transaction import GuildTransaction

# Import the new service
from bot.services.ai_generation_service import AIGenerationService
from bot.game.managers.undo_manager import UndoManager # Added import


if TYPE_CHECKING:
    from discord import Message
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.equipment_manager import EquipmentManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.crafting_manager import CraftingManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.party_manager import PartyManager
    from bot.services.openai_service import OpenAIService
    from bot.game.managers.persistence_manager import PersistenceManager
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
    from bot.game.command_handlers.party_handler import PartyCommandHandler
    from bot.game.command_router import CommandRouter
    from bot.game.managers.ability_manager import AbilityManager
    from bot.game.managers.spell_manager import SpellManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.lore_manager import LoreManager
    from bot.game.services.campaign_loader import CampaignLoaderService
    from bot.game.services.consequence_processor import ConsequenceProcessor
    from bot.services.nlu_data_service import NLUDataService
    from bot.game.conflict_resolver import ConflictResolver
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.ai.ai_response_validator import AIResponseValidator
    # NotificationService already imported
    from bot.game.turn_processing_service import TurnProcessingService
    from bot.game.turn_processor import TurnProcessor
    from bot.game.rules.check_resolver import CheckResolver
    from bot.game.managers.faction_manager import FactionManager
    from bot.game.services.location_interaction_service import LocationInteractionService
    # AIGenerationService already imported

logger = logging.getLogger(__name__)
logger.debug("--- Начинается загрузка: game_manager.py")

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

DEFAULT_RULES_CONFIG_ID = "main_rules_config"

class GameManager:
    def __init__(
        self,
        discord_client: Client,
        settings: Dict[str, Any]
    ):
        logger.info("Initializing GameManager…")
        self._discord_client = discord_client
        self._settings = settings
        self._rules_config_cache: Optional[Dict[str, Any]] = None

        self.db_service: Optional[DBService] = None
        self.rule_engine: Optional["RuleEngine"] = None
        self.time_manager: Optional["TimeManager"] = None
        self.openai_service: Optional["OpenAIService"] = None
        self.notification_service: Optional["NotificationService"] = None
        self.location_manager: Optional["LocationManager"] = None
        self.event_manager: Optional["EventManager"] = None
        self.item_manager: Optional["ItemManager"] = None
        self.status_manager: Optional["StatusManager"] = None
        self.character_manager: Optional["CharacterManager"] = None
        self.npc_manager: Optional["NpcManager"] = None
        self.party_manager: Optional["PartyManager"] = None
        self.inventory_manager: Optional["InventoryManager"] = None
        self.equipment_manager: Optional["EquipmentManager"] = None
        self.combat_manager: Optional["CombatManager"] = None
        self.crafting_manager: Optional["CraftingManager"] = None
        self.economy_manager: Optional["EconomyManager"] = None
        self.quest_manager: Optional["QuestManager"] = None
        self.relationship_manager: Optional["RelationshipManager"] = None
        self.dialogue_manager: Optional["DialogueManager"] = None
        self.game_log_manager: Optional["GameLogManager"] = None
        self.lore_manager: Optional["LoreManager"] = None
        self.ability_manager: Optional["AbilityManager"] = None
        self.spell_manager: Optional["SpellManager"] = None
        self.faction_manager: Optional["FactionManager"] = None
        self.prompt_context_collector: Optional["PromptContextCollector"] = None
        self.multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None
        self.ai_response_validator: Optional["AIResponseValidator"] = None
        self.ai_generation_service: Optional[AIGenerationService] = None
        self._persistence_manager: Optional["PersistenceManager"] = None
        self._world_simulation_processor: Optional["WorldSimulationProcessor"] = None
        self._command_router: Optional["CommandRouter"] = None
        self.turn_processing_service: Optional["TurnProcessingService"] = None
        self.turn_processor: Optional["TurnProcessor"] = None
        self.check_resolver: Optional["CheckResolver"] = None
        self.location_interaction_service: Optional["LocationInteractionService"] = None
        self._on_enter_action_executor: Optional["OnEnterActionExecutor"] = None
        self._stage_description_generator: Optional["StageDescriptionGenerator"] = None
        self._event_stage_processor: Optional["EventStageProcessor"] = None
        self._event_action_processor: Optional["EventActionProcessor"] = None
        self._character_action_processor: Optional["CharacterActionProcessor"] = None
        self._character_view_service: Optional["CharacterViewService"] = None
        self._party_action_processor: Optional["PartyActionProcessor"] = None
        self._party_command_handler: Optional["PartyCommandHandler"] = None
        self.conflict_resolver: Optional["ConflictResolver"] = None
        self.campaign_loader: Optional["CampaignLoaderService"] = None
        self.consequence_processor: Optional["ConsequenceProcessor"] = None
        self.nlu_data_service: Optional["NLUDataService"] = None
        self._world_tick_task: Optional[asyncio.Task] = None
        self._tick_interval_seconds: float = settings.get('world_tick_interval_seconds', 60.0)
        self._active_guild_ids: List[str] = [str(gid) for gid in self._settings.get('active_guild_ids', [])]
        self.undo_manager: Optional[UndoManager] = None
        logger.info("GameManager initialized with attributes set to None.")

    async def _initialize_database(self):
        logger.info("GameManager: Initializing database service...")
        self.db_service = DBService()
        await self.db_service.connect()
        await self.db_service.initialize_database()
        logger.info("GameManager: DBService initialized.")

    async def _initialize_core_managers_and_services(self):
        logger.info("GameManager: Initializing core managers and services (RuleEngine, TimeManager, LocationManager, EventManager, OpenAIService)...")
        from bot.game.rules.rule_engine import RuleEngine
        from bot.game.managers.time_manager import TimeManager
        from bot.game.managers.location_manager import LocationManager
        from bot.game.managers.event_manager import EventManager
        from bot.services.openai_service import OpenAIService
        rules_data_for_engine = {}
        if self._active_guild_ids:
            first_guild_id = self._active_guild_ids[0]
            await self._load_or_initialize_rules_config(first_guild_id)
            rules_data_for_engine = self._rules_config_cache.get(first_guild_id, {}) if self._rules_config_cache else {}
        else:
            logger.warning("GameManager: No active guild IDs for RuleEngine init. Using fallback rules.")
            if self._rules_config_cache is None: self._rules_config_cache = {}
            self._rules_config_cache["__global_fallback__"] = {"default_bot_language": "en", "emergency_mode": True, "reason": "No active guilds for RuleEngine init"}
            rules_data_for_engine = self._rules_config_cache["__global_fallback__"]
        self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}), rules_data=rules_data_for_engine, game_manager=self)
        self.time_manager = TimeManager(db_service=self.db_service, settings=self._settings.get('time_settings', {}))
        self.location_manager = LocationManager(db_service=self.db_service, settings=self._settings, game_manager=self)
        try:
            oset = self._settings.get('openai_settings', {})
            self.openai_service = OpenAIService(api_key=oset.get('api_key'), model=oset.get('model'), default_max_tokens=oset.get('default_max_tokens'))
            if not self.openai_service.is_available(): self.openai_service = None
        except Exception as e: self.openai_service = None; logger.warning("GameManager: Failed OpenAIService init (%s)", e, exc_info=True)
        self.event_manager = EventManager(db_service=self.db_service, settings=self._settings.get('event_settings', {}), openai_service=self.openai_service, game_manager=self)
        logger.info("GameManager: Core managers and OpenAI service initialized.")

    async def _initialize_dependent_managers(self):
        logger.info("GameManager: Initializing dependent managers...")
        from bot.game.managers.item_manager import ItemManager; from bot.game.managers.status_manager import StatusManager; from bot.game.managers.npc_manager import NpcManager; from bot.game.managers.inventory_manager import InventoryManager; from bot.game.managers.equipment_manager import EquipmentManager; from bot.game.managers.combat_manager import CombatManager; from bot.game.managers.party_manager import PartyManager; from bot.game.managers.lore_manager import LoreManager; from bot.game.managers.game_log_manager import GameLogManager; from bot.services.campaign_loader import CampaignLoaderService; from bot.game.managers.faction_manager import FactionManager; from bot.game.managers.relationship_manager import RelationshipManager; from bot.game.managers.dialogue_manager import DialogueManager; from bot.game.managers.quest_manager import QuestManager; from bot.game.services.consequence_processor import ConsequenceProcessor; from bot.game.managers.ability_manager import AbilityManager; from bot.game.managers.spell_manager import SpellManager; from bot.game.managers.crafting_manager import CraftingManager; from bot.game.managers.economy_manager import EconomyManager
        self.item_manager = ItemManager(db_service=self.db_service, settings=self._settings, location_manager=self.location_manager, rule_engine=self.rule_engine); self.status_manager = StatusManager(db_service=self.db_service, settings=self._settings.get('status_settings', {})); self.game_log_manager = GameLogManager(db_service=self.db_service); self.lore_manager = LoreManager(settings=self._settings.get('lore_settings', {}), db_service=self.db_service); self.ability_manager = AbilityManager(db_service=self.db_service); self.spell_manager = SpellManager(db_service=self.db_service); self.crafting_manager = CraftingManager(db_service=self.db_service, item_manager=self.item_manager); self.economy_manager = EconomyManager(db_service=self.db_service, item_manager=self.item_manager, rule_engine=self.rule_engine)
        self.campaign_loader = CampaignLoaderService(settings=self._settings); npc_archetypes_from_campaign = {};
        if self.campaign_loader: campaign_identifier = self._settings.get('default_campaign_identifier'); default_campaign_data = self.campaign_loader.load_campaign_by_identifier(identifier=campaign_identifier); npc_archetypes_from_campaign = default_campaign_data.get('npc_archetypes', {}) if default_campaign_data and isinstance(default_campaign_data.get('npc_archetypes'), dict) else {}
        npc_manager_settings = self._settings.get('npc_settings', {}).copy(); npc_manager_settings['loaded_npc_archetypes_from_campaign'] = npc_archetypes_from_campaign
        self.relationship_manager = RelationshipManager(db_service=self.db_service, settings=self._settings.get('relationship_settings', {}))
        self.npc_manager = NpcManager(db_service=self.db_service, settings=npc_manager_settings, item_manager=self.item_manager, rule_engine=self.rule_engine, combat_manager=None, status_manager=self.status_manager, openai_service=self.openai_service, campaign_loader=self.campaign_loader, game_manager=self)
        self.character_manager = CharacterManager(db_service=self.db_service, settings=self._settings, item_manager=self.item_manager, location_manager=self.location_manager, rule_engine=self.rule_engine, status_manager=self.status_manager, party_manager=None, combat_manager=None, dialogue_manager=None, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager, npc_manager=self.npc_manager, inventory_manager=None, equipment_manager=None, game_manager=self)
        self.inventory_manager = InventoryManager(character_manager=self.character_manager, item_manager=self.item_manager, db_service=self.db_service); self.character_manager._inventory_manager = self.inventory_manager
        self.equipment_manager = EquipmentManager(character_manager=self.character_manager, inventory_manager=self.inventory_manager, item_manager=self.item_manager, status_manager=self.status_manager, rule_engine=self.rule_engine, db_service=self.db_service); self.character_manager._equipment_manager = self.equipment_manager
        self.party_manager = PartyManager(db_service=self.db_service, settings=self._settings.get('party_settings', {}), character_manager=self.character_manager, game_manager=self); self.character_manager._party_manager = self.party_manager
        self.combat_manager = CombatManager(db_service=self.db_service, settings=self._settings.get('combat_settings',{}), rule_engine=self.rule_engine, character_manager=self.character_manager, npc_manager=self.npc_manager, party_manager=self.party_manager, status_manager=self.status_manager, item_manager=self.item_manager, location_manager=self.location_manager, game_manager=self); self.npc_manager._combat_manager = self.combat_manager; self.character_manager._combat_manager = self.combat_manager; self.party_manager.combat_manager = self.combat_manager
        self.dialogue_manager = DialogueManager(db_service=self.db_service, settings=self._settings.get('dialogue_settings', {}), character_manager=self.character_manager, npc_manager=self.npc_manager, rule_engine=self.rule_engine, time_manager=self.time_manager, openai_service=self.openai_service, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager, quest_manager=None, notification_service=None, game_manager=self); self.character_manager._dialogue_manager = self.dialogue_manager; # type: ignore
        if hasattr(self.npc_manager, 'dialogue_manager'): self.npc_manager.dialogue_manager = self.dialogue_manager # type: ignore
        self.consequence_processor = ConsequenceProcessor(
            character_manager=self.character_manager,
            npc_manager=self.npc_manager,
            item_manager=self.item_manager,
            location_manager=self.location_manager,
            event_manager=self.event_manager,
            quest_manager=None,  # This will be set by QuestManager's __init__ or a setter
            status_manager=self.status_manager,
            dialogue_manager=None, # This will be set by DialogueManager's __init__ or a setter
            rule_engine=self.rule_engine,
            economy_manager=self.economy_manager,
            relationship_manager=self.relationship_manager,
            game_log_manager=self.game_log_manager,
            notification_service=None, # This will be set later
            prompt_context_collector=None # This will be set later
        )
        self.quest_manager = QuestManager(db_service=self.db_service, settings=self._settings.get('quest_settings', {}), npc_manager=self.npc_manager, character_manager=self.character_manager, item_manager=self.item_manager, rule_engine=self.rule_engine, relationship_manager=self.relationship_manager, consequence_processor=self.consequence_processor, game_log_manager=self.game_log_manager, multilingual_prompt_generator=None, openai_service=self.openai_service, ai_validator=None, notification_service=None, game_manager=self); self.consequence_processor.quest_manager = self.quest_manager; self.dialogue_manager.quest_manager = self.quest_manager
        self.faction_manager = FactionManager(game_manager=self)
        self.notification_service = NotificationService(send_callback_factory=self._get_discord_send_callback, settings=self._settings, i18n_utils=None, character_manager=self.character_manager); self.dialogue_manager.notification_service = self.notification_service; self.quest_manager.notification_service = self.notification_service
        if self.consequence_processor: self.consequence_processor.notification_service = self.notification_service
        logger.info("GameManager: Dependent managers initialized.")

    async def _initialize_processors_and_command_system(self):
        logger.info("GameManager: Initializing processors and command system...")
        # from bot.game.managers.undo_manager import UndoManager # Already imported globally
        from bot.game.character_processors.character_action_processor import CharacterActionProcessor; from bot.game.character_processors.character_view_service import CharacterViewService; from bot.game.party_processors.party_action_processor import PartyActionProcessor; from bot.game.command_handlers.party_handler import PartyCommandHandler; from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor; from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator; from bot.game.event_processors.event_stage_processor import EventStageProcessor; from bot.game.event_processors.event_action_processor import EventActionProcessor; from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor; from bot.game.managers.persistence_manager import PersistenceManager; from bot.game.command_router import CommandRouter; from bot.game.conflict_resolver import ConflictResolver; from bot.game.turn_processing_service import TurnProcessingService; from bot.game.turn_processor import TurnProcessor; from bot.game.services.location_interaction_service import LocationInteractionService
        from bot.game.rules.check_resolver import CheckResolver
        self.undo_manager = UndoManager(db_service=self.db_service, game_log_manager=self.game_log_manager, character_manager=self.character_manager, item_manager=self.item_manager, quest_manager=self.quest_manager, party_manager=self.party_manager)
        self._on_enter_action_executor = OnEnterActionExecutor(npc_manager=self.npc_manager, item_manager=self.item_manager, combat_manager=self.combat_manager, status_manager=self.status_manager)
        self._stage_description_generator = StageDescriptionGenerator(openai_service=self.openai_service)
        self._event_action_processor = EventActionProcessor(event_stage_processor=None, event_manager=self.event_manager, character_manager=self.character_manager, loc_manager=self.location_manager, rule_engine=self.rule_engine, openai_service=self.openai_service, send_callback_factory=self._get_discord_send_callback, game_manager=self)
        self._event_stage_processor = EventStageProcessor(on_enter_action_executor=self._on_enter_action_executor, stage_description_generator=self._stage_description_generator, rule_engine=self.rule_engine, character_manager=self.character_manager, loc_manager=self.location_manager, game_manager=self, event_action_processor=self._event_action_processor)
        self._event_action_processor.event_stage_processor = self._event_stage_processor
        self._character_action_processor = CharacterActionProcessor(
            character_manager=self.character_manager,
            send_callback_factory=self._get_discord_send_callback,
            db_service=self.db_service,
            item_manager=self.item_manager,
            location_manager=self.location_manager,
            dialogue_manager=self.dialogue_manager,
            rule_engine=self.rule_engine,
            time_manager=self.time_manager,
            combat_manager=self.combat_manager,
            status_manager=self.status_manager,
            party_manager=self.party_manager,
            npc_manager=self.npc_manager,
            event_stage_processor=self._event_stage_processor,
            event_action_processor=self._event_action_processor,
            game_log_manager=self.game_log_manager,
            openai_service=self.openai_service,
            event_manager=self.event_manager,
            equipment_manager=self.equipment_manager,
            inventory_manager=self.inventory_manager,
            location_interaction_service=None # Passed as None for now
        )
        self._character_view_service = CharacterViewService(
            character_manager=self.character_manager,
            item_manager=self.item_manager,
            location_manager=self.location_manager,
            rule_engine=self.rule_engine,
            status_manager=self.status_manager,
            party_manager=self.party_manager,
            equipment_manager=self.equipment_manager,
            inventory_manager=self.inventory_manager,
            ability_manager=self.ability_manager,
            spell_manager=self.spell_manager
        )
        self._party_action_processor = PartyActionProcessor(game_manager=self)
        self._party_command_handler = PartyCommandHandler(game_manager=self)
        self._persistence_manager = PersistenceManager(game_manager=self)
        self._world_simulation_processor = WorldSimulationProcessor(game_manager=self)
        self.turn_processing_service = TurnProcessingService(game_manager=self)
        self.turn_processor = TurnProcessor(game_manager=self)
        self.check_resolver = CheckResolver(game_manager=self)
        self.conflict_resolver = ConflictResolver(game_manager=self)
        self.location_interaction_service = LocationInteractionService(game_manager=self)
        self._command_router = CommandRouter(game_manager=self)
        logger.info("GameManager: Processors and command system initialized.")

    async def _initialize_ai_content_services(self):
        logger.info("GameManager: Initializing AI content generation services...")
        from bot.ai.prompt_context_collector import PromptContextCollector
        from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
        from bot.ai.ai_response_validator import AIResponseValidator
        from bot.services.nlu_data_service import NLUDataService

        self.nlu_data_service = NLUDataService(db_service=self.db_service)
        self.prompt_context_collector = PromptContextCollector(game_manager=self)

        main_bot_lang = "en"
        if self._active_guild_ids:
            first_guild_id = self._active_guild_ids[0]
            main_bot_lang = (self._rules_config_cache.get(first_guild_id, {}).get('default_language', 'en')
                             if self._rules_config_cache else 'en')

        self.multilingual_prompt_generator = MultilingualPromptGenerator(
            prompt_context_collector=self.prompt_context_collector,
            game_rules_data_source_func=lambda: self._rules_data,
            main_bot_language=main_bot_lang,
            target_languages=self._settings.get('target_languages', ['en', 'ru'])
        )
        if self.quest_manager: self.quest_manager.multilingual_prompt_generator = self.multilingual_prompt_generator
        if self.consequence_processor: self.consequence_processor.prompt_context_collector = self.prompt_context_collector

        self.ai_response_validator = AIResponseValidator(game_manager=self)
        if self.quest_manager: self.quest_manager.ai_validator = self.ai_response_validator

        self.ai_generation_service = AIGenerationService(game_manager=self)
        logger.info("GameManager: AIGenerationService initialized.")
        logger.info("GameManager: AI content services initialized.")

    async def _load_initial_data_and_state(self):
        logger.info("GameManager: Loading initial game data and state...")
        if self.campaign_loader:
            if self._active_guild_ids:
                for guild_id_str in self._active_guild_ids:
                    logger.info("GameManager: Populating game data for guild %s.", guild_id_str)
                    await self.campaign_loader.populate_all_game_data(guild_id=guild_id_str, campaign_identifier=None)
            else: logger.warning("GameManager: No active guilds specified for data loading.")
        if self._persistence_manager: await self._persistence_manager.load_game_state(guild_ids=self._active_guild_ids)
        logger.info("GameManager: Initial data and game state loaded.")

    async def _start_background_tasks(self):
        logger.info("GameManager: Starting background tasks...")
        if self._world_simulation_processor: self._world_tick_task = asyncio.create_task(self._world_tick_loop()); logger.info("GameManager: World tick loop started.")
        else: logger.warning("GameManager: World tick loop not started, WSP unavailable.")
        logger.info("GameManager: Background tasks started.")

    async def setup(self) -> None:
        logger.info("GameManager: Running setup…")
        try:
            await self._initialize_database()
            await self._initialize_core_managers_and_services()
            await self._initialize_dependent_managers()
            await self._initialize_processors_and_command_system()
            await self._initialize_ai_content_services()
            await self._load_initial_data_and_state()
            await self._start_background_tasks()
            logger.info("GameManager: Setup complete.")
        except Exception as e:
            is_db_connection_error = isinstance(e, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError)) or (hasattr(e, '__cause__') and isinstance(e.__cause__, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError)))
            if is_db_connection_error: logger.critical(f"DB Connection Error: {e}", exc_info=True)
            else: logger.critical(f"GameManager Critical Setup Error: {e}", exc_info=True)
            try: await self.shutdown()
            except Exception as shutdown_e: logger.error(f"Error during shutdown from setup failure: {shutdown_e}", exc_info=True)
            raise

    async def handle_discord_message(self, message: "Message") -> None:
        if message.author.bot: return
        if not self._command_router:
            logger.warning("GameManager: CommandRouter not available, message '%s' from guild %s dropped.", message.content, message.guild.id if message.guild else "DM")
            if message.channel:
                try:
                    send_callback = self._get_discord_send_callback(message.channel.id)
                    await send_callback(f"❌ Игра еще не полностью запущена...")
                except Exception as cb_e:
                    logger.error("GameManager: Error sending startup error message to channel %s: %s", message.channel.id, cb_e, exc_info=True)
            return

        command_prefix = self._settings.get('command_prefix', '/')
        if message.content.startswith(command_prefix):
            logger.info("GameManager: Passing command from %s (ID: %s, Guild: %s, Channel: %s) to CommandRouter: '%s'",
                        message.author.name, message.author.id, message.guild.id if message.guild else 'DM',
                        message.channel.id, message.content)

        try:
            await self._command_router.route(message)
        except Exception as e:
            logger.error("GameManager: Error handling message '%s' from guild %s: %s", message.content, message.guild.id if message.guild else "DM", e, exc_info=True)
            try:
                if message.channel:
                    send_callback = self._get_discord_send_callback(message.channel.id)
                    await send_callback(f"❌ Произошла внутренняя ошибка при обработке команды. Подробности в логах бота.")
                else:
                    logger.warning("GameManager: Cannot send error message to user (DM channel or channel not found).")
            except Exception as cb_e:
                logger.error("GameManager: Error sending generic internal error message to channel %s: %s", message.channel.id, cb_e, exc_info=True)

    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback:
        channel_id_int = int(channel_id)
        async def _send(content: str = "", **kwargs: Any) -> None:
            channel = self._discord_client.get_channel(channel_id_int)
            if channel and isinstance(channel, discord.abc.Messageable):
                try: await channel.send(content, **kwargs)
                except Exception as e: logger.error(f"Error sending to channel {channel_id_int}: {e}", exc_info=True)
            elif not channel: logger.warning(f"Channel {channel_id_int} not found.")
            else: logger.warning(f"Channel {channel_id_int} not Messageable.")
        return _send

    async def _process_player_turns_for_tick(self, guild_id_str: str) -> None:
        if not self.turn_processor or not self.character_manager: logger.warning(f"GameManager (Tick-{guild_id_str}): TurnProcessor or CharacterManager not available."); return
        try:
            if self.turn_processor: await self.turn_processor.process_turns_for_guild(guild_id_str)
        except Exception as tps_e: logger.error(f"GameManager (Tick-{guild_id_str}): Error during TurnProcessor call: {tps_e}", exc_info=True)

    async def _world_tick_loop(self) -> None:
        logger.info("GameManager: Starting world tick loop...")
        try:
            while True:
                await asyncio.sleep(self._tick_interval_seconds)
                if self._world_simulation_processor:
                    try: await self._world_simulation_processor.process_world_tick(game_time_delta=self._tick_interval_seconds)
                    except Exception as e: logger.error(f"Error during world sim tick: {e}", exc_info=True)
                for guild_id_str in self._active_guild_ids: await self._process_player_turns_for_tick(guild_id_str)
        except asyncio.CancelledError: logger.info("GameManager: World tick loop cancelled.")
        except Exception as e: logger.critical(f"Critical error in world tick loop: {e}", exc_info=True)

    async def save_game_state_after_action(self, guild_id: str) -> None:
        if not self._persistence_manager: logger.warning(f"PersistenceManager not available for guild {guild_id}."); return
        try: await self._persistence_manager.save_game_state(guild_ids=[str(guild_id)])
        except Exception as e: logger.error(f"Error saving game state for guild {guild_id}: {e}", exc_info=True)

    async def shutdown(self) -> None:
        logger.info("GameManager: Running shutdown...")
        if self._world_tick_task:
            self._world_tick_task.cancel()
            try: await asyncio.wait_for(self._world_tick_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError): pass
            except Exception as e: logger.error(f"Error waiting for world tick task: {e}", exc_info=True)
        if self._persistence_manager and self.db_service:
            try: await self._persistence_manager.save_game_state(guild_ids=self._active_guild_ids)
            except Exception as e: logger.error(f"Error saving game state on shutdown: {e}", exc_info=True)
        if self.db_service:
            try: await self.db_service.close()
            except Exception as e: logger.error(f"Error closing DB service: {e}", exc_info=True)
        logger.info("GameManager: Shutdown complete.")

    async def get_player_by_discord_id(self, discord_id: int, guild_id: str) -> Optional[Character]:
        if not self.character_manager: return None
        try: return self.character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_id)
        except Exception as e: logger.error(f"Error in get_player_by_discord_id: {e}", exc_info=True); return None

    async def _load_or_initialize_rules_config(self, guild_id: str):
        logger.info(f"GameManager: Loading/Init rules for guild_id: {guild_id}...")
        if self._rules_config_cache is None: self._rules_config_cache = {}
        if guild_id not in self._rules_config_cache: self._rules_config_cache[guild_id] = {}
        if not self.db_service: self._rules_config_cache[guild_id] = {"default_bot_language": "en", "error_state": "DBService unavailable"}; return
        try:
            rules_entries = await self.db_service.get_entities_by_conditions(table_name='rules_config', conditions={'guild_id': guild_id})
            guild_rules_dict = {entry['key']: entry['value'] for entry in rules_entries if 'key' in entry and 'value' in entry}
            if guild_rules_dict: self._rules_config_cache[guild_id] = guild_rules_dict
            else:
                from bot.game.guild_initializer import initialize_new_guild
                async with self.db_service.get_session() as session: # type: ignore
                    if await initialize_new_guild(session, guild_id):
                        rules_entries_after_init = await self.db_service.get_entities_by_conditions(table_name='rules_config', conditions={'guild_id': guild_id})
                        self._rules_config_cache[guild_id] = {entry['key']: entry['value'] for entry in rules_entries_after_init if 'key' in entry and 'value' in entry}
                    else: self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": "Guild initializer failed"}
        except Exception as e: self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": f"Exception: {str(e)}"}
        if not self._rules_config_cache.get(guild_id): self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": "Final fallback"}

    async def get_rule(self, guild_id: str, key: str, default: Optional[Any] = None) -> Optional[Any]:
        if self._rules_config_cache is None or guild_id not in self._rules_config_cache: await self._load_or_initialize_rules_config(guild_id)
        if self._rules_config_cache and guild_id in self._rules_config_cache: return self._rules_config_cache[guild_id].get(key, default)
        return default

    async def get_location_type_i18n_map(self, guild_id: str, type_key: str) -> Optional[Dict[str, str]]:
        """
        Retrieves the i18n map (e.g., {"en": "Name", "ru": "Имя"}) for a given location type key.
        Returns None if the key is not found or definitions are not loaded.
        """
        if not self.rule_engine:
            logger.warning(f"RuleEngine not available in GameManager for guild {guild_id}. Cannot fetch location type definitions.")
            return None

        try:
            # Assuming rule_engine has a method to get the fully loaded CoreGameRulesConfig
            # This matches the assumption made when designing this method.
            # If RuleEngine stores it as a direct attribute (e.g., self.rule_engine.core_config_data after parsing),
            # this would be: rules_config = self.rule_engine.core_config_data.get(guild_id) or self.rule_engine.core_config_data
            # For now, proceeding with get_rules_config as an async method on RuleEngine.
            rules_config = await self.rule_engine.get_rules_config(guild_id)

            if rules_config and rules_config.location_type_definitions:
                i18n_map = rules_config.location_type_definitions.get(type_key)
                if i18n_map is None:
                    logger.warning(f"Location type key '{type_key}' not found in location_type_definitions for guild {guild_id}. Definitions are present but key is missing.")
                return i18n_map
            elif rules_config:
                logger.warning(f"location_type_definitions not found in CoreGameRulesConfig for guild {guild_id}.")
            else:
                logger.warning(f"CoreGameRulesConfig not loaded for guild {guild_id}.")
        except Exception as e:
            logger.error(f"Error retrieving location type definitions for guild {guild_id}, key '{type_key}': {e}", exc_info=True)

        return None

    async def update_rule_config(self, guild_id: str, key: str, value: Any) -> bool:
        if not self.db_service: return False
        try:
            existing_rule_entry = await self.db_service.get_entity_by_conditions(table_name='rules_config', conditions={'guild_id': guild_id, 'key': key}, model_class=RulesConfig, single_entity=True)
            db_success = False
            if existing_rule_entry: update_result = await self.db_service.update_entities_by_conditions(table_name='rules_config', conditions={'guild_id': guild_id, 'key': key}, updates={'value': value}); db_success = bool(update_result)
            else: new_rule_data = {'guild_id': guild_id, 'key': key, 'value': value}; created_entity = await self.db_service.create_entity(table_name='rules_config', entity_data=new_rule_data, model_class=RulesConfig); db_success = created_entity is not None
            if db_success:
                if self._rules_config_cache is None: self._rules_config_cache = {}
                if guild_id not in self._rules_config_cache: self._rules_config_cache[guild_id] = {}
                self._rules_config_cache[guild_id][key] = value; return True
            return False
        except Exception as e: logger.error(f"Exception saving rule '{key}' for guild {guild_id}: {e}", exc_info=True); return False

    async def set_default_bot_language(self, language: str, guild_id: Optional[str] = None) -> bool:
        if not guild_id: return False
        success = await self.update_rule_config(guild_id, "default_language", language)
        if success and self.multilingual_prompt_generator:
            if self._active_guild_ids and guild_id == self._active_guild_ids[0]: self.multilingual_prompt_generator.update_main_bot_language(language)
        return success

    async def get_player_model_by_discord_id(self, guild_id: str, discord_id: str) -> Optional[Player]:
        if not self.db_service: return None
        return await self.db_service.get_entity_by_conditions(table_name='players', conditions={'guild_id': str(guild_id), 'discord_id': str(discord_id)}, model_class=Player, single_entity=True)

    async def get_player_model_by_id(self, guild_id: str, player_id: str) -> Optional[Player]:
        if not self.db_service: return None
        return await self.db_service.get_entity_by_pk(table_name='players', pk_value=str(player_id), guild_id=str(guild_id), model_class=Player)

    async def get_players_in_location(self, guild_id: str, location_id: str) -> List[Player]:
        if not self.db_service: return []
        return await self.db_service.get_entities_by_conditions(table_name='players', conditions={'guild_id': str(guild_id), 'current_location_id': str(location_id)}, model_class=Player) or []

    async def handle_move_action(self, guild_id: str, character_id: str, target_location_identifier: str) -> bool:
        if not self.location_manager:
            logger.error("GameManager: LocationManager not available. Cannot handle move action.")
            return False
        return await self.location_manager.process_character_move(
            guild_id=guild_id,
            character_id=character_id,
            target_location_identifier=target_location_identifier
        )

    # --- AI Generation Wrappers ---
    async def trigger_ai_generation(self, guild_id: str, request_type: str, request_params: Dict[str, Any], created_by_user_id: Optional[str] = None) -> Optional[str]:
        if not self.ai_generation_service:
            logger.error("GameManager: AIGenerationService not available. Cannot trigger AI generation.")
            return None
        return await self.ai_generation_service.trigger_ai_generation(
            guild_id=guild_id,
            request_type=request_type,
            request_params=request_params,
            created_by_user_id=created_by_user_id
        )

    async def apply_approved_generation(self, pending_gen_id: str, guild_id: str) -> bool:
        if not self.ai_generation_service:
            logger.error("GameManager: AIGenerationService not available. Cannot apply approved generation.")
            return False
        return await self.ai_generation_service.apply_approved_generation(
            pending_gen_id=pending_gen_id,
            guild_id=guild_id
        )

    # _on_enter_location was moved to LocationInteractionService.process_on_enter_location_events

logger.debug("DEBUG: Finished loading game_manager.py from: %s", __file__)


