# bot/game/managers/game_manager.py

import asyncio
import json
import os
import io
import logging
import uuid
from typing import Optional, Dict, Any, Callable, Awaitable, List, TYPE_CHECKING, cast

from sqlalchemy.exc import IntegrityError
from asyncpg import exceptions as asyncpg_exceptions

import discord
from discord import Client

from bot.services.db_service import DBService
from bot.game.models.character import Character
from bot.database.models import RulesConfig, Player, GuildConfig, Location, QuestTable, QuestStepTable, Party # Removed PendingGeneration as it's not directly used here
from bot.services.notification_service import NotificationService
from bot.game.managers.character_manager import CharacterManager, CharacterAlreadyExistsError
import random
from bot.database.guild_transaction import GuildTransaction
from bot.services.ai_generation_service import AIGenerationService
from bot.game.managers.undo_manager import UndoManager


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
    from bot.game.services.campaign_loader import CampaignLoader
    from bot.game.services.consequence_processor import ConsequenceProcessor
    from bot.services.nlu_data_service import NLUDataService
    from bot.game.conflict_resolver import ConflictResolver
    from bot.ai.prompt_context_collector import PromptContextCollector
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.game.turn_processing_service import TurnProcessingService
    from bot.game.turn_processor import TurnProcessor
    from bot.game.rules.check_resolver import CheckResolver
    from bot.game.managers.faction_manager import FactionManager
    from bot.game.services.location_interaction_service import LocationInteractionService
    from pydantic import ValidationError
    from bot.ai.rules_schema import CoreGameRulesConfig # Moved from TYPE_CHECKING

logger = logging.getLogger(__name__)
logger.debug("--- Начинается загрузка: game_manager.py")

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

DEFAULT_RULES_CONFIG_ID = "main_rules_config"

class GameManager:
    def __init__(self, discord_client: Client, settings: Dict[str, Any]):
        logger.info("Initializing GameManager…")
        self._discord_client = discord_client
        self._settings = settings
        self._rules_config_cache: Dict[str, Dict[str, Any]] = {}

        self.db_service: Optional[DBService] = None
        self.rule_engine: Optional[RuleEngine] = None
        self.time_manager: Optional[TimeManager] = None
        self.openai_service: Optional[OpenAIService] = None
        self.notification_service: Optional[NotificationService] = None
        self.location_manager: Optional[LocationManager] = None
        self.event_manager: Optional[EventManager] = None
        self.item_manager: Optional[ItemManager] = None
        self.status_manager: Optional[StatusManager] = None
        self.character_manager: Optional[CharacterManager] = None
        self.npc_manager: Optional[NpcManager] = None
        self.party_manager: Optional[PartyManager] = None
        self.inventory_manager: Optional[InventoryManager] = None
        self.equipment_manager: Optional[EquipmentManager] = None
        self.combat_manager: Optional[CombatManager] = None
        self.crafting_manager: Optional[CraftingManager] = None
        self.economy_manager: Optional[EconomyManager] = None
        self.quest_manager: Optional[QuestManager] = None
        self.relationship_manager: Optional[RelationshipManager] = None
        self.dialogue_manager: Optional[DialogueManager] = None
        self.game_log_manager: Optional[GameLogManager] = None
        self.lore_manager: Optional[LoreManager] = None
        self.ability_manager: Optional[AbilityManager] = None
        self.spell_manager: Optional[SpellManager] = None
        self.faction_manager: Optional[FactionManager] = None
        self.prompt_context_collector: Optional[PromptContextCollector] = None
        self.multilingual_prompt_generator: Optional[MultilingualPromptGenerator] = None
        self.ai_response_validator: Optional[AIResponseValidator] = None
        self.ai_generation_service: Optional[AIGenerationService] = None
        self._persistence_manager: Optional[PersistenceManager] = None
        self._world_simulation_processor: Optional[WorldSimulationProcessor] = None
        self._command_router: Optional[CommandRouter] = None
        self.turn_processing_service: Optional[TurnProcessingService] = None
        self.turn_processor: Optional[TurnProcessor] = None
        self.check_resolver: Optional[CheckResolver] = None
        self.location_interaction_service: Optional[LocationInteractionService] = None
        self._on_enter_action_executor: Optional[OnEnterActionExecutor] = None
        self._stage_description_generator: Optional[StageDescriptionGenerator] = None
        self._event_stage_processor: Optional[EventStageProcessor] = None
        self._event_action_processor: Optional[EventActionProcessor] = None
        self._character_action_processor: Optional[CharacterActionProcessor] = None
        self._character_view_service: Optional[CharacterViewService] = None
        self._party_action_processor: Optional[PartyActionProcessor] = None
        self._party_command_handler: Optional[PartyCommandHandler] = None
        self.conflict_resolver: Optional[ConflictResolver] = None
        self.campaign_loader: Optional[CampaignLoader] = None
        self.consequence_processor: Optional[ConsequenceProcessor] = None
        self.nlu_data_service: Optional[NLUDataService] = None
        self._world_tick_task: Optional[asyncio.Task] = None
        self._tick_interval_seconds: float = settings.get('world_tick_interval_seconds', 60.0)
        self._active_guild_ids: List[str] = [str(gid) for gid in self._settings.get('active_guild_ids', [])]
        self.undo_manager: Optional[UndoManager] = None
        logger.info("GameManager initialized with attributes set to None.")

    async def _initialize_database(self):
        logger.info("GameManager: Initializing database service...")
        self.db_service = DBService()
        await self.db_service.connect()
        if os.getenv("TESTING_MODE") == "true":
            logger.info("GameManager (TESTING_MODE): Skipping db_service.initialize_database() as schema is handled by test fixtures.")
        elif os.getenv("MIGRATE_ON_INIT", "false").lower() == "true":
            logger.info("GameManager: MIGRATE_ON_INIT is true, calling db_service.initialize_database().")
            if self.db_service: await self.db_service.initialize_database()
        else:
            logger.info("GameManager: MIGRATE_ON_INIT is false or not set, and not in TESTING_MODE. Skipping db_service.initialize_database().")
        logger.info("GameManager: DBService connection established and initialization logic (if applicable) completed.")

    async def _initialize_core_managers_and_services(self):
        logger.info("GameManager: Initializing core managers and services (RuleEngine, TimeManager, LocationManager, EventManager, OpenAIService)...")
        from bot.game.rules.rule_engine import RuleEngine
        from bot.game.managers.time_manager import TimeManager
        from bot.game.managers.location_manager import LocationManager
        from bot.game.managers.event_manager import EventManager
        from bot.services.openai_service import OpenAIService

        if not self.db_service: raise RuntimeError("DBService not initialized before core managers.")

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

        if not self.location_manager : raise RuntimeError("LocationManager not initialized before EventManager.")
        self.event_manager = EventManager(db_service=self.db_service, settings=self._settings.get('event_settings', {}), openai_service=self.openai_service, game_manager=self, location_manager=self.location_manager)
        logger.info("GameManager: Core managers and OpenAI service initialized.")

    async def _initialize_dependent_managers(self):
        logger.info("GameManager: Initializing dependent managers...")
        from bot.game.managers.item_manager import ItemManager; from bot.game.managers.status_manager import StatusManager; from bot.game.managers.npc_manager import NpcManager; from bot.game.managers.inventory_manager import InventoryManager; from bot.game.managers.equipment_manager import EquipmentManager; from bot.game.managers.combat_manager import CombatManager; from bot.game.managers.party_manager import PartyManager; from bot.game.managers.lore_manager import LoreManager; from bot.game.managers.game_log_manager import GameLogManager; from bot.game.services.campaign_loader import CampaignLoader; from bot.game.managers.faction_manager import FactionManager; from bot.game.managers.relationship_manager import RelationshipManager; from bot.game.managers.dialogue_manager import DialogueManager; from bot.game.managers.quest_manager import QuestManager; from bot.game.services.consequence_processor import ConsequenceProcessor; from bot.game.managers.ability_manager import AbilityManager; from bot.game.managers.spell_manager import SpellManager; from bot.game.managers.crafting_manager import CraftingManager; from bot.game.managers.economy_manager import EconomyManager

        if not self.db_service: raise RuntimeError("DBService not initialized for dependent managers.")
        if not self.rule_engine: raise RuntimeError("RuleEngine not initialized for dependent managers.")
        if not self.location_manager: raise RuntimeError("LocationManager not initialized for dependent managers.")
        if not self.time_manager: raise RuntimeError("TimeManager not initialized for dependent managers.")
        if not self.event_manager: raise RuntimeError("EventManager not initialized for dependent managers.")

        self.item_manager = ItemManager(db_service=self.db_service, settings=self._settings, location_manager=self.location_manager, rule_engine=self.rule_engine);
        self.status_manager = StatusManager(db_service=self.db_service, settings=self._settings.get('status_settings', {}));
        self.game_log_manager = GameLogManager(db_service=self.db_service);
        self.lore_manager = LoreManager(settings=self._settings.get('lore_settings', {}), db_service=self.db_service);
        self.ability_manager = AbilityManager(db_service=self.db_service);
        self.spell_manager = SpellManager(db_service=self.db_service);

        if not self.item_manager: raise RuntimeError("ItemManager not initialized for Crafting/EconomyManager.")
        self.crafting_manager = CraftingManager(db_service=self.db_service, item_manager=self.item_manager);
        self.economy_manager = EconomyManager(db_service=self.db_service, item_manager=self.item_manager, rule_engine=self.rule_engine)

        self.campaign_loader = CampaignLoader(settings=self._settings, db_service=self.db_service);
        npc_archetypes_from_campaign = {};

        npc_manager_settings = self._settings.get('npc_settings', {}).copy(); npc_manager_settings['loaded_npc_archetypes_from_campaign'] = npc_archetypes_from_campaign
        self.relationship_manager = RelationshipManager(db_service=self.db_service, settings=self._settings.get('relationship_settings', {}))

        if not self.status_manager: raise RuntimeError("StatusManager not initialized for NpcManager.")
        self.npc_manager = NpcManager(db_service=self.db_service, settings=npc_manager_settings, item_manager=self.item_manager, rule_engine=self.rule_engine, combat_manager=None, status_manager=self.status_manager, openai_service=self.openai_service, campaign_loader=self.campaign_loader, game_manager=self)

        if not self.relationship_manager: raise RuntimeError("RelationshipManager not initialized for CharacterManager.")
        if not self.game_log_manager: raise RuntimeError("GameLogManager not initialized for CharacterManager.")
        if not self.npc_manager: raise RuntimeError("NpcManager not initialized for CharacterManager.")
        self.character_manager = CharacterManager(db_service=self.db_service, settings=self._settings, item_manager=self.item_manager, location_manager=self.location_manager, rule_engine=self.rule_engine, status_manager=self.status_manager, party_manager=None, combat_manager=None, dialogue_manager=None, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager, npc_manager=self.npc_manager, inventory_manager=None, equipment_manager=None, game_manager=self)

        if not self.character_manager: raise RuntimeError("CharacterManager not initialized for Inventory/Equipment/PartyManager.")
        self.inventory_manager = InventoryManager(character_manager=self.character_manager, item_manager=self.item_manager, db_service=self.db_service);
        self.character_manager._inventory_manager = self.inventory_manager # type: ignore[attr-defined]
        self.equipment_manager = EquipmentManager(character_manager=self.character_manager, inventory_manager=self.inventory_manager, item_manager=self.item_manager, status_manager=self.status_manager, rule_engine=self.rule_engine, db_service=self.db_service);
        self.character_manager._equipment_manager = self.equipment_manager # type: ignore[attr-defined]
        self.party_manager = PartyManager(db_service=self.db_service, settings=self._settings.get('party_settings', {}), character_manager=self.character_manager, game_manager=self);
        self.character_manager._party_manager = self.party_manager # type: ignore[attr-defined]

        if not self.party_manager: raise RuntimeError("PartyManager not initialized for CombatManager.")
        self.combat_manager = CombatManager(db_service=self.db_service, settings=self._settings.get('combat_settings',{}), rule_engine=self.rule_engine, character_manager=self.character_manager, npc_manager=self.npc_manager, party_manager=self.party_manager, status_manager=self.status_manager, item_manager=self.item_manager, location_manager=self.location_manager, game_manager=self);
        self.npc_manager._combat_manager = self.combat_manager # type: ignore[attr-defined]
        self.character_manager._combat_manager = self.combat_manager # type: ignore[attr-defined]
        if self.party_manager: self.party_manager.combat_manager = self.combat_manager # type: ignore[attr-defined] # party_manager might be None if check fails

        self.dialogue_manager = DialogueManager(db_service=self.db_service, settings=self._settings.get('dialogue_settings', {}), character_manager=self.character_manager, npc_manager=self.npc_manager, rule_engine=self.rule_engine, time_manager=self.time_manager, openai_service=self.openai_service, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager, quest_manager=None, notification_service=None, game_manager=self);
        if self.character_manager: self.character_manager._dialogue_manager = self.dialogue_manager # type: ignore[attr-defined]
        if hasattr(self.npc_manager, 'dialogue_manager'): self.npc_manager.dialogue_manager = self.dialogue_manager # type: ignore[union-attr]

        self.consequence_processor = ConsequenceProcessor(character_manager=self.character_manager, npc_manager=self.npc_manager, item_manager=self.item_manager, location_manager=self.location_manager, event_manager=self.event_manager, quest_manager=None, status_manager=self.status_manager, dialogue_manager=self.dialogue_manager, rule_engine=self.rule_engine, economy_manager=self.economy_manager, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager, notification_service=None, prompt_context_collector=None)

        if not self.consequence_processor: raise RuntimeError("ConsequenceProcessor not initialized for QuestManager.")
        if not self.dialogue_manager: raise RuntimeError("DialogueManager not initialized for QuestManager.")
        self.quest_manager = QuestManager(db_service=self.db_service, settings=self._settings.get('quest_settings', {}), npc_manager=self.npc_manager, character_manager=self.character_manager, item_manager=self.item_manager, rule_engine=self.rule_engine, relationship_manager=self.relationship_manager, consequence_processor=self.consequence_processor, game_log_manager=self.game_log_manager, multilingual_prompt_generator=None, openai_service=self.openai_service, ai_validator=None, notification_service=None, game_manager=self);
        self.consequence_processor.quest_manager = self.quest_manager # type: ignore[attr-defined]
        self.dialogue_manager.quest_manager = self.quest_manager # type: ignore[attr-defined]

        self.faction_manager = FactionManager(game_manager=self)
        self.notification_service = NotificationService(send_callback_factory=self._get_discord_send_callback, settings=self._settings, i18n_utils=None, character_manager=self.character_manager);
        if self.dialogue_manager: self.dialogue_manager.notification_service = self.notification_service # type: ignore[union-attr]
        if self.quest_manager: self.quest_manager.notification_service = self.notification_service # type: ignore[union-attr]
        if self.consequence_processor: self.consequence_processor.notification_service = self.notification_service # type: ignore[union-attr]
        logger.info("GameManager: Dependent managers initialized.")

    async def _initialize_processors_and_command_system(self):
        logger.info("GameManager: Initializing processors and command system...")
        from bot.game.character_processors.character_action_processor import CharacterActionProcessor; from bot.game.character_processors.character_view_service import CharacterViewService; from bot.game.party_processors.party_action_processor import PartyActionProcessor; from bot.game.command_handlers.party_handler import PartyCommandHandler; from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor; from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator; from bot.game.event_processors.event_stage_processor import EventStageProcessor; from bot.game.event_processors.event_action_processor import EventActionProcessor; from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor; from bot.game.managers.persistence_manager import PersistenceManager; from bot.game.command_router import CommandRouter; from bot.game.conflict_resolver import ConflictResolver; from bot.game.turn_processing_service import TurnProcessingService; from bot.game.turn_processor import TurnProcessor; from bot.game.services.location_interaction_service import LocationInteractionService
        from bot.game.rules.check_resolver import CheckResolver
        from bot.game.action_scheduler import GuildActionScheduler
        from bot.game.ai.npc_action_planner import NPCActionPlanner
        from bot.game.npc_action_processor import NPCActionProcessor

        if not self.db_service or not self.game_log_manager or not self.character_manager or \
           not self.item_manager or not self.quest_manager or not self.party_manager or \
           not self.npc_manager or not self.combat_manager or not self.status_manager or \
           not self.location_manager or not self.rule_engine or not self.event_manager or \
           not self.time_manager or not self.dialogue_manager or not self.equipment_manager or \
           not self.inventory_manager or not self.crafting_manager or not self.economy_manager or \
           not self.relationship_manager or not self.ability_manager or not self.spell_manager:
            raise RuntimeError("One or more core managers for processors not initialized.")

        self.undo_manager = UndoManager(db_service=self.db_service, game_log_manager=self.game_log_manager, character_manager=self.character_manager, item_manager=self.item_manager, quest_manager=self.quest_manager, party_manager=self.party_manager)
        self._on_enter_action_executor = OnEnterActionExecutor(npc_manager=self.npc_manager, item_manager=self.item_manager, combat_manager=self.combat_manager, status_manager=self.status_manager)
        self._stage_description_generator = StageDescriptionGenerator(openai_service=self.openai_service)

        self._event_action_processor = EventActionProcessor(event_stage_processor=None, event_manager=self.event_manager, character_manager=self.character_manager, loc_manager=self.location_manager, rule_engine=self.rule_engine, openai_service=self.openai_service, send_callback_factory=self._get_discord_send_callback, game_manager=self)
        self._event_stage_processor = EventStageProcessor(on_enter_action_executor=self._on_enter_action_executor, stage_description_generator=self._stage_description_generator, rule_engine=self.rule_engine, character_manager=self.character_manager, loc_manager=self.location_manager, game_manager=self, event_action_processor=self._event_action_processor)
        if self._event_action_processor: self._event_action_processor.event_stage_processor = self._event_stage_processor # type: ignore[attr-defined]

        self.location_interaction_service = LocationInteractionService(game_manager=self) # Initialize before passing to CharacterActionProcessor

        self._character_action_processor = CharacterActionProcessor(character_manager=self.character_manager, send_callback_factory=self._get_discord_send_callback, db_service=self.db_service, item_manager=self.item_manager, location_manager=self.location_manager, dialogue_manager=self.dialogue_manager, rule_engine=self.rule_engine, time_manager=self.time_manager, combat_manager=self.combat_manager, status_manager=self.status_manager, party_manager=self.party_manager, npc_manager=self.npc_manager, event_stage_processor=self._event_stage_processor, event_action_processor=self._event_action_processor, game_log_manager=self.game_log_manager, openai_service=self.openai_service, event_manager=self.event_manager, equipment_manager=self.equipment_manager, inventory_manager=self.inventory_manager, location_interaction_service=self.location_interaction_service)
        self._character_view_service = CharacterViewService(character_manager=self.character_manager, item_manager=self.item_manager, location_manager=self.location_manager, rule_engine=self.rule_engine, status_manager=self.status_manager, party_manager=self.party_manager, equipment_manager=self.equipment_manager, inventory_manager=self.inventory_manager, ability_manager=self.ability_manager, spell_manager=self.spell_manager)
        self._party_action_processor = PartyActionProcessor(party_manager=self.party_manager, send_callback_factory=self._get_discord_send_callback, rule_engine=self.rule_engine, location_manager=self.location_manager, character_manager=self.character_manager, npc_manager=self.npc_manager, time_manager=self.time_manager, combat_manager=self.combat_manager, event_stage_processor=self._event_stage_processor, game_log_manager=self.game_log_manager)
        self._party_command_handler = PartyCommandHandler(character_manager=self.character_manager, party_manager=self.party_manager, party_action_processor=self._party_action_processor, settings=self._settings, npc_manager=self.npc_manager)

        self._persistence_manager = PersistenceManager(event_manager=self.event_manager, character_manager=self.character_manager, location_manager=self.location_manager, db_service=self.db_service, npc_manager=self.npc_manager, combat_manager=self.combat_manager, item_manager=self.item_manager, time_manager=self.time_manager, status_manager=self.status_manager, crafting_manager=self.crafting_manager, economy_manager=self.economy_manager, party_manager=self.party_manager, quest_manager=self.quest_manager, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager, dialogue_manager=self.dialogue_manager, skill_manager=None, spell_manager=self.spell_manager )

        self.guild_action_scheduler = GuildActionScheduler()
        npc_planner_services = {'rule_engine': self.rule_engine, 'relationship_manager': self.relationship_manager, 'location_manager': self.location_manager }
        self.npc_action_planner = NPCActionPlanner(context_providing_services=npc_planner_services)
        npc_processor_managers = {'game_log_manager': self.game_log_manager, 'location_manager': self.location_manager, 'combat_manager': self.combat_manager, 'character_manager': self.character_manager, 'npc_manager': self.npc_manager, 'item_manager': self.item_manager, 'status_manager': self.status_manager, 'event_manager': self.event_manager, 'rule_engine': self.rule_engine }
        self.npc_action_processor = NPCActionProcessor(managers=npc_processor_managers)

        if not self._character_action_processor: raise RuntimeError("CharacterActionProcessor not initialized for TurnProcessingService.")
        if not self.location_interaction_service: raise RuntimeError("LocationInteractionService not initialized for TurnProcessingService.")

        self.turn_processing_service = TurnProcessingService(character_manager=self.character_manager, rule_engine=self.rule_engine, game_manager=self, game_log_manager=self.game_log_manager, character_action_processor=self._character_action_processor, combat_manager=self.combat_manager, location_manager=self.location_manager, location_interaction_service=self.location_interaction_service, dialogue_manager=self.dialogue_manager, inventory_manager=self.inventory_manager, equipment_manager=self.equipment_manager, item_manager=self.item_manager, action_scheduler=self.guild_action_scheduler, npc_action_planner=self.npc_action_planner, npc_action_processor=self.npc_action_processor, npc_manager=self.npc_manager, settings=self._settings)

        if not self._persistence_manager: raise RuntimeError("PersistenceManager not initialized for WorldSimulationProcessor.")
        if not self._event_stage_processor: raise RuntimeError("EventStageProcessor not initialized for WorldSimulationProcessor.")
        if not self._party_action_processor: raise RuntimeError("PartyActionProcessor not initialized for WorldSimulationProcessor.")

        self.multilingual_prompt_generator_instance = getattr(self, 'multilingual_prompt_generator', None) # Will be set in _initialize_ai_content_services

        self._world_simulation_processor = WorldSimulationProcessor(event_manager=self.event_manager, character_manager=self.character_manager, location_manager=self.location_manager, rule_engine=self.rule_engine, openai_service=self.openai_service, event_stage_processor=self._event_stage_processor, event_action_processor=self._event_action_processor, persistence_manager=self._persistence_manager, settings=self._settings, send_callback_factory=self._get_discord_send_callback, character_action_processor=self._character_action_processor, party_action_processor=self._party_action_processor, npc_manager=self.npc_manager, combat_manager=self.combat_manager, item_manager=self.item_manager, time_manager=self.time_manager, status_manager=self.status_manager, crafting_manager=self.crafting_manager, economy_manager=self.economy_manager, party_manager=self.party_manager, dialogue_manager=self.dialogue_manager, quest_manager=self.quest_manager, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager, multilingual_prompt_generator=self.multilingual_prompt_generator_instance) # type: ignore

        self.turn_processor = TurnProcessor(game_manager=self)
        self.check_resolver = CheckResolver(game_manager=self)
        self.conflict_resolver = ConflictResolver(rule_engine=self.rule_engine, notification_service=self.notification_service, db_service=self.db_service, game_log_manager=self.game_log_manager)

        if not self._world_simulation_processor: raise RuntimeError("WorldSimulationProcessor not initialized for CommandRouter.")
        if not self._character_view_service: raise RuntimeError("CharacterViewService not initialized for CommandRouter.")
        if not self._party_command_handler: raise RuntimeError("PartyCommandHandler not initialized for CommandRouter.")

        self._command_router = CommandRouter(character_manager=self.character_manager, event_manager=self.event_manager, persistence_manager=self._persistence_manager, settings=self._settings, world_simulation_processor=self._world_simulation_processor, send_callback_factory=self._get_discord_send_callback, character_action_processor=self._character_action_processor, character_view_service=self._character_view_service, location_manager=self.location_manager, rule_engine=self.rule_engine, party_command_handler=self._party_command_handler, openai_service=self.openai_service, item_manager=self.item_manager, npc_manager=self.npc_manager, combat_manager=self.combat_manager, time_manager=self.time_manager, status_manager=self.status_manager, party_manager=self.party_manager, crafting_manager=self.crafting_manager, economy_manager=self.economy_manager, party_action_processor=self._party_action_processor, event_action_processor=self._event_action_processor, event_stage_processor=self._event_stage_processor, quest_manager=self.quest_manager, dialogue_manager=self.dialogue_manager, campaign_loader=self.campaign_loader, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager, conflict_resolver=self.conflict_resolver, game_manager=self)
        logger.info("GameManager: Processors and command system initialized.")

    async def _initialize_ai_content_services(self):
        logger.info("GameManager: Initializing AI content generation services...")
        from bot.ai.prompt_context_collector import PromptContextCollector
        from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
        from bot.ai.ai_response_validator import AIResponseValidator
        from bot.services.nlu_data_service import NLUDataService

        if not self.db_service or not self.character_manager or not self.npc_manager or \
           not self.quest_manager or not self.relationship_manager or not self.item_manager or \
           not self.location_manager or not self.event_manager:
            raise RuntimeError("One or more core managers for AI content services not initialized.")

        self.nlu_data_service = NLUDataService(db_service=self.db_service)
        self.prompt_context_collector = PromptContextCollector(settings=self._settings, db_service=self.db_service, character_manager=self.character_manager, npc_manager=self.npc_manager, quest_manager=self.quest_manager, relationship_manager=self.relationship_manager, item_manager=self.item_manager, location_manager=self.location_manager, event_manager=self.event_manager, ability_manager=self.ability_manager, spell_manager=self.spell_manager, party_manager=self.party_manager, lore_manager=self.lore_manager, game_manager=self)

        main_bot_lang = "en"
        if self._active_guild_ids and self._rules_config_cache: # Ensure cache is not None
            first_guild_id = self._active_guild_ids[0]
            main_bot_lang = (self._rules_config_cache.get(first_guild_id, {}).get('default_language', 'en'))

        self.multilingual_prompt_generator = MultilingualPromptGenerator(context_collector=self.prompt_context_collector, main_bot_language=main_bot_lang, settings=self._settings)
        if self.quest_manager: self.quest_manager.multilingual_prompt_generator = self.multilingual_prompt_generator
        if self.consequence_processor: self.consequence_processor.prompt_context_collector = self.prompt_context_collector

        self.ai_response_validator = AIResponseValidator()
        if self.quest_manager: self.quest_manager.ai_validator = self.ai_response_validator

        self.ai_generation_service = AIGenerationService(game_manager=self)
        logger.info("GameManager: AIGenerationService initialized.")
        logger.info("GameManager: AI content services initialized.")

    async def _ensure_guild_configs_exist(self) -> List[str]:
        logger.info("GameManager: Ensuring guild configurations exist before data loading...")
        if not self.db_service: logger.error("DBService not available."); return []
        from bot.game.guild_initializer import initialize_new_guild
        successfully_initialized_guild_ids: List[str] = []
        guild_ids_to_process = list(self._active_guild_ids)
        if not guild_ids_to_process:
            default_id_for_setup = self._settings.get('default_guild_id_for_setup', "1364930265591320586")
            logger.warning(f"No active_guild_ids. Using default: {default_id_for_setup}")
            guild_ids_to_process = [default_id_for_setup]
            if default_id_for_setup not in self._active_guild_ids: self._active_guild_ids.append(default_id_for_setup)

        for guild_id_str in guild_ids_to_process:
            logger.info(f"Processing guild_id: {guild_id_str}")
            op_success = False
            try:
                async with self.db_service.get_session() as session: # type: ignore[attr-defined]
                    async with session.begin():
                        test_guild_id_to_force_reinit = "1364930265591320586" # Example
                        current_force_reinitialize_flag = (guild_id_str == test_guild_id_to_force_reinit) # Simplified
                        if current_force_reinitialize_flag: logger.warning(f"FORCING REINITIALIZE for {guild_id_str}")
                        await initialize_new_guild(session, guild_id_str, force_reinitialize=current_force_reinitialize_flag)
                        op_success = True
                if op_success: logger.info(f"Successfully ensured/initialized GuildConfig for {guild_id_str}."); successfully_initialized_guild_ids.append(guild_id_str)
            except IntegrityError as ie: logger.error(f"IntegrityError for guild {guild_id_str}: {ie}.", exc_info=True)
            except Exception as e: logger.error(f"Exception for guild {guild_id_str}: {e}.", exc_info=True)
        logger.info(f"Completed. Successfully confirmed/initialized for: {successfully_initialized_guild_ids}")
        return successfully_initialized_guild_ids

    async def _load_initial_data_and_state(self, confirmed_guild_ids: List[str]):
        logger.info(f"Loading initial game data for confirmed_guild_ids: {confirmed_guild_ids}")
        if not confirmed_guild_ids: logger.warning("No confirmed_guild_ids. Skipping data load."); return
        if self.campaign_loader:
            for guild_id_str in confirmed_guild_ids:
                logger.info(f"Populating via CampaignLoader for guild {guild_id_str}.")
                try: await self.campaign_loader.populate_all_game_data(guild_id=guild_id_str, campaign_identifier=None)
                except Exception as e: logger.error(f"Error populating game data for {guild_id_str}: {e}", exc_info=True)
        else: logger.warning("CampaignLoader not available.")
        if self._persistence_manager:
            logger.info(f"PersistenceManager loading game state for active guilds: {self._active_guild_ids}") # Should use confirmed_guild_ids
            try: await self._persistence_manager.load_game_state(guild_ids=confirmed_guild_ids) # Corrected to use confirmed
            except Exception as e: logger.error(f"Error loading game state: {e}", exc_info=True)
        else: logger.warning("PersistenceManager not available.")
        logger.info("Finished _load_initial_data_and_state.")

    async def _start_background_tasks(self):
        logger.info("Starting background tasks...")
        if self._world_simulation_processor: self._world_tick_task = asyncio.create_task(self._world_tick_loop()); logger.info("World tick loop started.")
        else: logger.warning("World tick loop not started, WSP unavailable.")
        logger.info("Background tasks started.")

    async def setup(self) -> None:
        logger.info("GameManager: Running setup…")
        try:
            await self._initialize_database()
            await self._initialize_core_managers_and_services()
            await self._initialize_dependent_managers()
            await self._initialize_processors_and_command_system()
            await self._initialize_ai_content_services()
            confirmed_guild_ids = await self._ensure_guild_configs_exist()
            await self._load_initial_data_and_state(confirmed_guild_ids)
            await self._start_background_tasks()
            logger.info("GameManager: Setup complete.")
        except Exception as e:
            is_db_conn_err = isinstance(e, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError)) or \
                             (hasattr(e, '__cause__') and isinstance(e.__cause__, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError)))
            if is_db_conn_err: logger.critical(f"DB Connection Error: {e}", exc_info=True)
            else: logger.critical(f"GameManager Critical Setup Error: {e}", exc_info=True)
            try: await self.shutdown()
            except Exception as shutdown_e: logger.error(f"Error during shutdown from setup failure: {shutdown_e}", exc_info=True)
            raise

    async def handle_discord_message(self, message: "Message") -> None:
        if message.author.bot: return
        if not self._command_router:
            logger.warning("CommandRouter not available, message '%s' from guild %s dropped.", message.content, message.guild.id if message.guild else "DM")
            if message.channel:
                try: await self._get_discord_send_callback(message.channel.id)(f"❌ Игра еще не полностью запущена...")
                except Exception as cb_e: logger.error("Error sending startup error: %s", cb_e, exc_info=True)
            return
        if message.content.startswith(self._settings.get('command_prefix', '/')):
            logger.info("Passing command from %s (Guild: %s) to CommandRouter: '%s'", message.author.name, message.guild.id if message.guild else 'DM', message.content)
        try: await self._command_router.route(message)
        except Exception as e:
            logger.error("Error handling message '%s': %s", message.content, e, exc_info=True)
            try:
                if message.channel: await self._get_discord_send_callback(message.channel.id)(f"❌ Внутренняя ошибка.")
                else: logger.warning("Cannot send error (DM or no channel).")
            except Exception as cb_e: logger.error("Error sending internal error message: %s", cb_e, exc_info=True)

    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback:
        async def _send(content: str = "", **kwargs: Any) -> None:
            channel = self._discord_client.get_channel(channel_id)
            if isinstance(channel, discord.abc.Messageable): # Check if it's Messageable
                try: await channel.send(content, **kwargs)
                except Exception as e: logger.error(f"Error sending to {channel_id}: {e}", exc_info=True)
            else: logger.warning(f"Channel {channel_id} not found or not Messageable.")
        return _send

    async def _process_player_turns_for_tick(self, guild_id_str: str) -> None:
        if not self.turn_processor or not self.character_manager: logger.warning(f"Tick-{guild_id_str}: TurnProcessor/CharacterManager unavailable."); return
        try:
            if self.turn_processor: await self.turn_processor.process_turns_for_guild(guild_id_str)
        except Exception as tps_e: logger.error(f"Tick-{guild_id_str}: Error in TurnProcessor: {tps_e}", exc_info=True)

    async def _world_tick_loop(self) -> None:
        logger.info("Starting world tick loop...")
        try:
            while True:
                await asyncio.sleep(self._tick_interval_seconds)
                if self._world_simulation_processor:
                    try: await self._world_simulation_processor.process_world_tick(game_time_delta=self._tick_interval_seconds)
                    except Exception as e: logger.error(f"Error during world sim tick: {e}", exc_info=True)
                for guild_id_str in self._active_guild_ids: await self._process_player_turns_for_tick(guild_id_str)
        except asyncio.CancelledError: logger.info("World tick loop cancelled.")
        except Exception as e: logger.critical(f"Critical error in world tick loop: {e}", exc_info=True)

    async def save_game_state_after_action(self, guild_id: str) -> None:
        if not self._persistence_manager: logger.warning(f"PersistenceManager unavailable for guild {guild_id}."); return
        try: await self._persistence_manager.save_game_state(guild_ids=[str(guild_id)])
        except Exception as e: logger.error(f"Error saving game state for {guild_id}: {e}", exc_info=True)

    async def shutdown(self) -> None:
        logger.info("Running shutdown...")
        if self._world_tick_task and not self._world_tick_task.done():
            self._world_tick_task.cancel()
            try: await asyncio.wait_for(self._world_tick_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError): logger.info("World tick task cancelled/timed out.")
            except Exception as e: logger.error(f"Error waiting for world tick task: {e}", exc_info=True)
        if self._persistence_manager and self.db_service:
            try: await self._persistence_manager.save_game_state(guild_ids=self._active_guild_ids)
            except Exception as e: logger.error(f"Error saving game state on shutdown: {e}", exc_info=True)
        if self.db_service:
            try: await self.db_service.close()
            except Exception as e: logger.error(f"Error closing DB service: {e}", exc_info=True)
        logger.info("Shutdown complete.")

    async def get_player_by_discord_id(self, discord_id: int, guild_id: str) -> Optional[Character]:
        if not self.character_manager: return None
        try:
            # Ensure character_manager.get_character_by_discord_id is awaited if it's async
            # Assuming it's async based on previous patterns.
            char = await self.character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_id)
            return char # type: ignore # Pyright might still complain if return type of get_character_by_discord_id is Coroutine
        except Exception as e: logger.error(f"Error in get_player_by_discord_id: {e}", exc_info=True); return None

    async def _load_or_initialize_rules_config(self, guild_id: str):
        logger.info(f"Loading/Init rules for guild_id: {guild_id}...")
        self._rules_config_cache.setdefault(guild_id, {})
        if not self.db_service:
            logger.error(f"DBService unavailable for rules config of guild {guild_id}.")
            self._rules_config_cache[guild_id] = {"default_bot_language": "en", "error_state": "DBService unavailable", "emergency_mode": True}
            return
        from bot.utils.config_utils import load_rules_config as util_load_rules_config
        try:
            async with self.db_service.get_session() as session: # type: ignore[attr-defined]
                guild_rules_dict = await util_load_rules_config(session, guild_id)
            if guild_rules_dict: self._rules_config_cache[guild_id] = guild_rules_dict; logger.info(f"RulesConfig for {guild_id} loaded ({len(guild_rules_dict)} rules).")
            else:
                logger.warning(f"No rules for guild {guild_id} in DB. Initializing.")
                from bot.game.guild_initializer import initialize_new_guild
                async with self.db_service.get_session() as init_session: # type: ignore[attr-defined]
                    async with init_session.begin(): await initialize_new_guild(init_session, guild_id, force_reinitialize=False)
                    async with self.db_service.get_session() as reload_session: # type: ignore[attr-defined]
                         guild_rules_dict_after_init = await util_load_rules_config(reload_session, guild_id)
                         self._rules_config_cache[guild_id] = guild_rules_dict_after_init # type: ignore
                         logger.info(f"RulesConfig for {guild_id} initialized ({len(guild_rules_dict_after_init or {})} rules).") # type: ignore
                if not self._rules_config_cache.get(guild_id): self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": "Init failed or no rules."}; logger.error(f"Failed to load/init rules for {guild_id}.")
        except Exception as e: logger.error(f"Exception during rules config for {guild_id}: {e}", exc_info=True); self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": f"Exception: {str(e)}"}

    async def get_rule(self, guild_id: str, key: str, default: Optional[Any] = None) -> Optional[Any]:
        if guild_id not in self._rules_config_cache: await self._load_or_initialize_rules_config(guild_id)
        guild_specific_cache = self._rules_config_cache.get(guild_id)
        if guild_specific_cache is not None: return guild_specific_cache.get(key, default)
        logger.warning(f"Guild {guild_id} not in cache for rule '{key}'. Returning default."); return default

    async def get_location_type_i18n_map(self, guild_id: str, type_key: str) -> Optional[Dict[str, str]]:
        if not self.rule_engine: logger.warning(f"RuleEngine unavailable for guild {guild_id}."); return None
        try:
            rules_config_model = await self.get_core_rules_config_for_guild(guild_id)
            if rules_config_model and rules_config_model.location_type_definitions:
                i18n_map = rules_config_model.location_type_definitions.get(type_key)
                if i18n_map is None: logger.warning(f"Key '{type_key}' not in location_type_definitions for {guild_id}.")
                return i18n_map
            elif rules_config_model: logger.warning(f"location_type_definitions not in CoreGameRulesConfig for {guild_id}.")
            else: logger.warning(f"CoreGameRulesConfig not available for {guild_id}.")
        except Exception as e: logger.error(f"Error retrieving location type defs for {guild_id}, key '{type_key}': {e}", exc_info=True)
        return None

    async def get_core_rules_config_for_guild(self, guild_id: str) -> Optional[CoreGameRulesConfig]: # type: ignore[name-defined]
        if guild_id not in self._rules_config_cache: await self._load_or_initialize_rules_config(guild_id)
        raw_rules_dict = self._rules_config_cache.get(guild_id)
        if not raw_rules_dict: logger.warning(f"No raw rules dict for {guild_id}."); return None
        try:
            # Assuming raw_rules_dict needs to be structured for CoreGameRulesConfig
            # This might involve a transformation step if load_rules_config returns a flat dict.
            # For now, direct parsing attempt.
            return CoreGameRulesConfig(**raw_rules_dict) # type: ignore[name-defined]
        except ValidationError as ve: logger.error(f"Pydantic validation error for {guild_id}: {ve}", exc_info=True); logger.debug(f"Problematic dict for {guild_id}: {raw_rules_dict}"); return None # type: ignore[name-defined]
        except Exception as e: logger.error(f"Unexpected error parsing rules for {guild_id}: {e}", exc_info=True); return None

    async def update_rule_config(self, guild_id: str, key: str, value: Any) -> bool:
        if not self.db_service: logger.error(f"DBService unavailable for update_rule_config (guild {guild_id})."); return False
        from bot.utils.config_utils import update_rule_config as util_update_rule_config
        try:
            async with self.db_service.get_session() as session: # type: ignore[attr-defined]
                await util_update_rule_config(session, guild_id, key, value)
            self._rules_config_cache.setdefault(guild_id, {})[key] = value
            logger.info(f"Rule '{key}' for {guild_id} updated in DB and cache."); return True
        except Exception as e:
            logger.error(f"Exception updating rule '{key}' for {guild_id}: {e}", exc_info=True)
            if guild_id in self._rules_config_cache: self._rules_config_cache[guild_id].pop(key, None); logger.info(f"Cache for rule '{key}' ({guild_id}) cleared due to error.")
            return False

    async def set_default_bot_language(self, language: str, guild_id: Optional[str] = None) -> bool:
        if not guild_id: return False
        success = await self.update_rule_config(guild_id, "default_language", language)
        if success and self.multilingual_prompt_generator:
            if self._active_guild_ids and guild_id == self._active_guild_ids[0]:
                 self.multilingual_prompt_generator.update_main_bot_language(language)
                 logger.info(f"Updated MultilingualPromptGenerator main lang to '{language}' for primary guild '{guild_id}'.")
            else: logger.info(f"Default lang for '{guild_id}' to '{language}', not updating global prompt gen lang.")
        return success

    async def get_player_model_by_discord_id(self, guild_id: str, discord_id: str) -> Optional[Player]: # Corrected type hint for discord_id
        if not self.db_service: return None
        return await self.db_service.get_entity_by_conditions(Player, conditions={'guild_id': str(guild_id), 'discord_id': str(discord_id)}) # type: ignore[attr-defined]

    async def get_player_model_by_id(self, guild_id: str, player_id: str) -> Optional[Player]:
        if not self.db_service: return None
        return await self.db_service.get_entity_by_pk(Player, pk_value=str(player_id), guild_id=str(guild_id)) # type: ignore[attr-defined]

    async def get_players_in_location(self, guild_id: str, location_id: str) -> List[Player]:
        if not self.db_service: return []
        return await self.db_service.get_entities_by_conditions(Player, conditions={'guild_id': str(guild_id), 'current_location_id': str(location_id)}) or [] # type: ignore[attr-defined]

    async def handle_move_action(self, guild_id: str, character_id: str, target_location_identifier: str) -> bool:
        if not self.location_manager: logger.error("LocationManager unavailable."); return False
        return await self.location_manager.process_character_move(guild_id=guild_id, character_id=character_id, target_location_identifier=target_location_identifier)

    async def trigger_ai_generation(self, guild_id: str, request_type: str, request_params: Dict[str, Any], created_by_user_id: Optional[str] = None) -> Optional[str]: # Return type changed to Optional[str] for pending_id
        if not self.ai_generation_service: logger.error("AIGenerationService unavailable."); return None
        pending_gen_record = await self.ai_generation_service.request_content_generation(guild_id=guild_id, request_type=GenerationType(request_type), request_params_json=request_params, created_by_user_id=created_by_user_id) # type: ignore # request_params_json vs context/prompt
        return pending_gen_record.id if pending_gen_record else None

    async def apply_approved_generation(self, pending_gen_id: str, guild_id: str) -> bool:
        if not self.ai_generation_service: logger.error("AIGenerationService unavailable."); return False
        return await self.ai_generation_service.process_approved_generation(pending_gen_id=pending_gen_id, guild_id=guild_id, moderator_user_id="SYSTEM_AUTO_APPROVE") # Assuming moderator_id for now

logger.debug("DEBUG: Finished loading game_manager.py from: %s", __file__)
