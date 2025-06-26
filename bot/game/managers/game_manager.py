# bot/game/managers/game_manager.py

import asyncio
import json
import os
# import io # Unused
import logging
import uuid
from typing import Optional, Dict, Any, Callable, Awaitable, List, TYPE_CHECKING, cast

from sqlalchemy.exc import IntegrityError
from asyncpg import exceptions as asyncpg_exceptions

import discord
from discord import Client # Used for type hint of self._discord_client

from bot.services.db_service import DBService
from bot.game.models.character import Character
from bot.database.models import Player, GuildConfig # RulesConfig, Location, QuestTable, QuestStepTable, Party are not directly used here for instantiation
from bot.services.notification_service import NotificationService
from bot.game.managers.character_manager import CharacterManager # CharacterAlreadyExistsError unused
# import random # Unused
from bot.database.guild_transaction import GuildTransaction # Used if needed for direct DB ops, but mostly via DBService
from bot.services.ai_generation_service import AIGenerationService
from bot.game.managers.undo_manager import UndoManager
from bot.database.models.pending_generation import GenerationType # For trigger_ai_generation

if TYPE_CHECKING:
    from discord import Message, TextChannel
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

from bot.ai.rules_schema import CoreGameRulesConfig


logger = logging.getLogger(__name__)

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

# DEFAULT_RULES_CONFIG_ID = "main_rules_config" # Unused

class GameManager:
    def __init__(self, discord_client: Client, settings: Dict[str, Any]):
        logger.info("Initializing GameManager…")
        self._discord_client: Client = discord_client
        self._settings: Dict[str, Any] = settings
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
        self._world_tick_task: Optional[asyncio.Task[None]] = None
        self._tick_interval_seconds: float = float(settings.get('world_tick_interval_seconds', 60.0))
        self._active_guild_ids: List[str] = [str(gid) for gid in self._settings.get('active_guild_ids', []) if gid is not None]
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
            if self.db_service and hasattr(self.db_service, 'initialize_database') and callable(getattr(self.db_service, 'initialize_database')):
                 await self.db_service.initialize_database()
            else:
                logger.error("DBService not available or initialize_database method missing for MIGRATE_ON_INIT.")
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
        db_service = cast(DBService, self.db_service) # Cast for type safety

        rules_data_for_engine: Dict[str, Any] = {}
        if self._active_guild_ids:
            first_guild_id = self._active_guild_ids[0]
            await self._load_or_initialize_rules_config(first_guild_id) # This ensures cache is populated
            rules_data_for_engine = self._rules_config_cache.get(first_guild_id, {}) # Default to empty if somehow still missing
        else:
            logger.warning("GameManager: No active guild IDs for RuleEngine init. Using fallback rules.")
            self._rules_config_cache["__global_fallback__"] = {"default_bot_language": "en", "emergency_mode": True, "reason": "No active guilds for RuleEngine init"}
            rules_data_for_engine = self._rules_config_cache["__global_fallback__"]

        self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}), rules_data=rules_data_for_engine, game_manager=self)
        self.time_manager = TimeManager(db_service=db_service, settings=self._settings.get('time_settings', {}))
        self.location_manager = LocationManager(db_service=db_service, settings=self._settings, game_manager=self)

        try:
            oset = self._settings.get('openai_settings', {})
            self.openai_service = OpenAIService(api_key=str(oset.get('api_key')), model=str(oset.get('model')), default_max_tokens=int(oset.get('default_max_tokens', 150)))
            if self.openai_service and not self.openai_service.is_available(): self.openai_service = None
        except Exception as e: self.openai_service = None; logger.warning("GameManager: Failed OpenAIService init (%s)", e, exc_info=True)

        if not self.location_manager : raise RuntimeError("LocationManager not initialized before EventManager.")
        location_manager_casted = cast(LocationManager, self.location_manager)
        self.event_manager = EventManager(db_service=db_service, settings=self._settings.get('event_settings', {}), openai_service=self.openai_service, game_manager=self, location_manager=location_manager_casted)
        logger.info("GameManager: Core managers and OpenAI service initialized.")

    async def _initialize_dependent_managers(self):
        logger.info("GameManager: Initializing dependent managers...")
        from bot.game.managers.item_manager import ItemManager
        from bot.game.managers.status_manager import StatusManager
        from bot.game.managers.npc_manager import NpcManager
        from bot.game.managers.inventory_manager import InventoryManager
        from bot.game.managers.equipment_manager import EquipmentManager
        from bot.game.managers.combat_manager import CombatManager
        from bot.game.managers.party_manager import PartyManager
        from bot.game.managers.lore_manager import LoreManager
        from bot.game.managers.game_log_manager import GameLogManager
        from bot.game.services.campaign_loader import CampaignLoader
        from bot.game.managers.faction_manager import FactionManager
        from bot.game.managers.relationship_manager import RelationshipManager
        from bot.game.managers.dialogue_manager import DialogueManager
        from bot.game.managers.quest_manager import QuestManager
        from bot.game.services.consequence_processor import ConsequenceProcessor
        from bot.game.managers.ability_manager import AbilityManager
        from bot.game.managers.spell_manager import SpellManager
        from bot.game.managers.crafting_manager import CraftingManager
        from bot.game.managers.economy_manager import EconomyManager

        critical_managers_map = {
            "DBService": self.db_service, "RuleEngine": self.rule_engine,
            "LocationManager": self.location_manager, "TimeManager": self.time_manager,
            "EventManager": self.event_manager
        }
        for name, manager_instance in critical_managers_map.items():
            if not manager_instance: raise RuntimeError(f"{name} not initialized for dependent managers.")

        db_service = cast(DBService, self.db_service)
        rule_engine = cast(RuleEngine, self.rule_engine)
        location_manager = cast(LocationManager, self.location_manager)
        time_manager = cast(TimeManager, self.time_manager)
        event_manager = cast(EventManager, self.event_manager)

        self.item_manager = ItemManager(db_service=db_service, settings=self._settings, location_manager=location_manager, rule_engine=rule_engine);
        self.status_manager = StatusManager(db_service=db_service, settings=self._settings.get('status_settings', {}));
        self.game_log_manager = GameLogManager(db_service=db_service);
        self.lore_manager = LoreManager(settings=self._settings.get('lore_settings', {}), db_service=db_service);
        self.ability_manager = AbilityManager(db_service=db_service);
        self.spell_manager = SpellManager(db_service=db_service);

        if not self.item_manager: raise RuntimeError("ItemManager not initialized for Crafting/EconomyManager.")
        item_manager_casted = cast(ItemManager, self.item_manager)
        self.crafting_manager = CraftingManager(db_service=db_service, item_manager=item_manager_casted);
        self.economy_manager = EconomyManager(db_service=db_service, item_manager=item_manager_casted, rule_engine=rule_engine)

        self.campaign_loader = CampaignLoader(settings=self._settings, db_service=db_service);
        npc_archetypes_from_campaign: Dict[str, Any] = {};

        npc_manager_settings = self._settings.get('npc_settings', {}).copy(); npc_manager_settings['loaded_npc_archetypes_from_campaign'] = npc_archetypes_from_campaign
        self.relationship_manager = RelationshipManager(db_service=db_service, settings=self._settings.get('relationship_settings', {}))

        if not self.status_manager: raise RuntimeError("StatusManager not initialized for NpcManager.")
        status_manager_casted = cast(StatusManager, self.status_manager)
        campaign_loader_casted = cast(CampaignLoader, self.campaign_loader) # May be None if not initialized
        self.npc_manager = NpcManager(db_service=db_service, settings=npc_manager_settings, item_manager=item_manager_casted, rule_engine=rule_engine, combat_manager=None, status_manager=status_manager_casted, openai_service=self.openai_service, campaign_loader=campaign_loader_casted, game_manager=self)

        if not self.relationship_manager: raise RuntimeError("RelationshipManager not initialized for CharacterManager.")
        if not self.game_log_manager: raise RuntimeError("GameLogManager not initialized for CharacterManager.")
        if not self.npc_manager: raise RuntimeError("NpcManager not initialized for CharacterManager.")
        relationship_manager_casted = cast(RelationshipManager, self.relationship_manager)
        game_log_manager_casted = cast(GameLogManager, self.game_log_manager)
        npc_manager_casted = cast(NpcManager, self.npc_manager)

        self.character_manager = CharacterManager(db_service=db_service, settings=self._settings, item_manager=item_manager_casted, location_manager=location_manager, rule_engine=rule_engine, status_manager=status_manager_casted, party_manager=None, combat_manager=None, dialogue_manager=None, relationship_manager=relationship_manager_casted, game_log_manager=game_log_manager_casted, npc_manager=npc_manager_casted, inventory_manager=None, equipment_manager=None, game_manager=self)

        if not self.character_manager: raise RuntimeError("CharacterManager not initialized for Inventory/Equipment/PartyManager.")
        character_manager_casted = cast(CharacterManager, self.character_manager)
        self.inventory_manager = InventoryManager(character_manager=character_manager_casted, item_manager=item_manager_casted, db_service=db_service);
        if hasattr(self.character_manager, '_inventory_manager'): self.character_manager._inventory_manager = self.inventory_manager
        self.equipment_manager = EquipmentManager(character_manager=character_manager_casted, inventory_manager=self.inventory_manager, item_manager=item_manager_casted, status_manager=status_manager_casted, rule_engine=rule_engine, db_service=db_service);
        if hasattr(self.character_manager, '_equipment_manager'): self.character_manager._equipment_manager = self.equipment_manager
        self.party_manager = PartyManager(db_service=db_service, settings=self._settings.get('party_settings', {}), character_manager=character_manager_casted, game_manager=self);
        if hasattr(self.character_manager, '_party_manager'): self.character_manager._party_manager = self.party_manager

        if not self.party_manager: raise RuntimeError("PartyManager not initialized for CombatManager.")
        party_manager_casted = cast(PartyManager, self.party_manager)
        self.combat_manager = CombatManager(db_service=db_service, settings=self._settings.get('combat_settings',{}), rule_engine=rule_engine, character_manager=character_manager_casted, npc_manager=npc_manager_casted, party_manager=party_manager_casted, status_manager=status_manager_casted, item_manager=item_manager_casted, location_manager=location_manager, game_manager=self);
        if hasattr(self.npc_manager, '_combat_manager'): self.npc_manager._combat_manager = self.combat_manager
        if hasattr(self.character_manager, '_combat_manager'): self.character_manager._combat_manager = self.combat_manager
        if self.party_manager and hasattr(self.party_manager, 'combat_manager'): self.party_manager.combat_manager = self.combat_manager

        self.dialogue_manager = DialogueManager(db_service=db_service, settings=self._settings.get('dialogue_settings', {}), character_manager=character_manager_casted, npc_manager=npc_manager_casted, rule_engine=rule_engine, time_manager=time_manager, openai_service=self.openai_service, relationship_manager=relationship_manager_casted, game_log_manager=game_log_manager_casted, quest_manager=None, notification_service=None, game_manager=self);
        if self.character_manager and hasattr(self.character_manager, '_dialogue_manager'): self.character_manager._dialogue_manager = self.dialogue_manager
        if self.npc_manager and hasattr(self.npc_manager, 'dialogue_manager'): self.npc_manager.dialogue_manager = self.dialogue_manager

        if not self.economy_manager: raise RuntimeError("EconomyManager not initialized for ConsequenceProcessor.")
        economy_manager_casted = cast(EconomyManager, self.economy_manager)
        self.consequence_processor = ConsequenceProcessor(character_manager=character_manager_casted, npc_manager=npc_manager_casted, item_manager=item_manager_casted, location_manager=location_manager, event_manager=event_manager, quest_manager=None, status_manager=status_manager_casted, dialogue_manager=self.dialogue_manager, rule_engine=rule_engine, economy_manager=economy_manager_casted, relationship_manager=relationship_manager_casted, game_log_manager=game_log_manager_casted, notification_service=None, prompt_context_collector=None)

        if not self.consequence_processor: raise RuntimeError("ConsequenceProcessor not initialized for QuestManager.")
        if not self.dialogue_manager: raise RuntimeError("DialogueManager not initialized for QuestManager.")
        consequence_processor_casted = cast(ConsequenceProcessor, self.consequence_processor)
        dialogue_manager_casted = cast(DialogueManager, self.dialogue_manager)
        self.quest_manager = QuestManager(db_service=db_service, settings=self._settings.get('quest_settings', {}), npc_manager=npc_manager_casted, character_manager=character_manager_casted, item_manager=item_manager_casted, rule_engine=rule_engine, relationship_manager=relationship_manager_casted, consequence_processor=consequence_processor_casted, game_log_manager=game_log_manager_casted, multilingual_prompt_generator=None, openai_service=self.openai_service, ai_validator=None, notification_service=None, game_manager=self);
        if hasattr(self.consequence_processor, 'quest_manager'): self.consequence_processor.quest_manager = self.quest_manager
        if hasattr(self.dialogue_manager, 'quest_manager'): self.dialogue_manager.quest_manager = self.quest_manager

        self.faction_manager = FactionManager(game_manager=self)
        self.notification_service = NotificationService(send_callback_factory=self._get_discord_send_callback, settings=self._settings, i18n_utils=None, character_manager=character_manager_casted);
        if self.dialogue_manager and hasattr(self.dialogue_manager, 'notification_service'): self.dialogue_manager.notification_service = self.notification_service
        if self.quest_manager and hasattr(self.quest_manager, 'notification_service'): self.quest_manager.notification_service = self.notification_service
        if self.consequence_processor and hasattr(self.consequence_processor, 'notification_service'): self.consequence_processor.notification_service = self.notification_service
        logger.info("GameManager: Dependent managers initialized.")

    async def _initialize_processors_and_command_system(self):
        logger.info("GameManager: Initializing processors and command system...")
        from bot.game.character_processors.character_action_processor import CharacterActionProcessor; from bot.game.character_processors.character_view_service import CharacterViewService; from bot.game.party_processors.party_action_processor import PartyActionProcessor; from bot.game.command_handlers.party_handler import PartyCommandHandler; from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor; from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator; from bot.game.event_processors.event_stage_processor import EventStageProcessor; from bot.game.event_processors.event_action_processor import EventActionProcessor; from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor; from bot.game.managers.persistence_manager import PersistenceManager; from bot.game.command_router import CommandRouter; from bot.game.conflict_resolver import ConflictResolver; from bot.game.turn_processing_service import TurnProcessingService; from bot.game.turn_processor import TurnProcessor; from bot.game.services.location_interaction_service import LocationInteractionService
        from bot.game.rules.check_resolver import CheckResolver
        from bot.game.action_scheduler import GuildActionScheduler
        from bot.game.ai.npc_action_planner import NPCActionPlanner
        from bot.game.npc_action_processor import NPCActionProcessor

        crit_managers_map_proc = {
            "DBService": self.db_service, "GameLogManager": self.game_log_manager,
            "CharacterManager": self.character_manager, "ItemManager": self.item_manager,
            "QuestManager": self.quest_manager, "PartyManager": self.party_manager,
            "NpcManager": self.npc_manager, "CombatManager": self.combat_manager,
            "StatusManager": self.status_manager, "LocationManager": self.location_manager,
            "RuleEngine": self.rule_engine, "EventManager": self.event_manager,
            "TimeManager": self.time_manager, "DialogueManager": self.dialogue_manager,
            "EquipmentManager": self.equipment_manager, "InventoryManager": self.inventory_manager,
            "CraftingManager": self.crafting_manager, "EconomyManager": self.economy_manager,
            "RelationshipManager": self.relationship_manager, "AbilityManager": self.ability_manager,
            "SpellManager": self.spell_manager
        }
        for name, manager_instance in crit_managers_map_proc.items():
            if not manager_instance: raise RuntimeError(f"{name} not initialized for processors/command system.")

        db_service_proc = cast(DBService, self.db_service)
        game_log_manager_proc = cast(GameLogManager, self.game_log_manager)
        character_manager_proc = cast(CharacterManager, self.character_manager)
        item_manager_proc = cast(ItemManager, self.item_manager)
        quest_manager_proc = cast(QuestManager, self.quest_manager)
        party_manager_proc = cast(PartyManager, self.party_manager)
        npc_manager_proc = cast(NpcManager, self.npc_manager)
        combat_manager_proc = cast(CombatManager, self.combat_manager)
        status_manager_proc = cast(StatusManager, self.status_manager)
        location_manager_proc = cast(LocationManager, self.location_manager)
        rule_engine_proc = cast(RuleEngine, self.rule_engine)
        event_manager_proc = cast(EventManager, self.event_manager)
        time_manager_proc = cast(TimeManager, self.time_manager)
        dialogue_manager_proc = cast(DialogueManager, self.dialogue_manager)
        equipment_manager_proc = cast(EquipmentManager, self.equipment_manager)
        inventory_manager_proc = cast(InventoryManager, self.inventory_manager)
        crafting_manager_proc = cast(CraftingManager, self.crafting_manager)
        economy_manager_proc = cast(EconomyManager, self.economy_manager)
        relationship_manager_proc = cast(RelationshipManager, self.relationship_manager)
        ability_manager_proc = cast(AbilityManager, self.ability_manager)
        spell_manager_proc = cast(SpellManager, self.spell_manager)


        self.undo_manager = UndoManager(db_service=db_service_proc, game_log_manager=game_log_manager_proc, character_manager=character_manager_proc, item_manager=item_manager_proc, quest_manager=quest_manager_proc, party_manager=party_manager_proc)
        self._on_enter_action_executor = OnEnterActionExecutor(npc_manager=npc_manager_proc, item_manager=item_manager_proc, combat_manager=combat_manager_proc, status_manager=status_manager_proc)
        self._stage_description_generator = StageDescriptionGenerator(openai_service=self.openai_service)

        self._event_action_processor = EventActionProcessor(event_stage_processor=None, event_manager=event_manager_proc, character_manager=character_manager_proc, loc_manager=location_manager_proc, rule_engine=rule_engine_proc, openai_service=self.openai_service, send_callback_factory=self._get_discord_send_callback, game_manager=self)
        self._event_stage_processor = EventStageProcessor(on_enter_action_executor=self._on_enter_action_executor, stage_description_generator=self._stage_description_generator, rule_engine=rule_engine_proc, character_manager=character_manager_proc, loc_manager=location_manager_proc, game_manager=self, event_action_processor=self._event_action_processor)
        if self._event_action_processor and hasattr(self._event_action_processor, 'event_stage_processor'): self._event_action_processor.event_stage_processor = self._event_stage_processor

        self.location_interaction_service = LocationInteractionService(game_manager=self)

        if not self._event_stage_processor: raise RuntimeError("EventStageProcessor not init for CharacterActionProcessor")
        if not self.location_interaction_service: raise RuntimeError("LocationInteractionService not init for CharacterActionProcessor")
        event_stage_processor_casted = cast(EventStageProcessor, self._event_stage_processor) # Cast after check
        location_interaction_service_casted = cast(LocationInteractionService, self.location_interaction_service)


        self._character_action_processor = CharacterActionProcessor(character_manager=character_manager_proc, send_callback_factory=self._get_discord_send_callback, db_service=db_service_proc, item_manager=item_manager_proc, location_manager=location_manager_proc, dialogue_manager=dialogue_manager_proc, rule_engine=rule_engine_proc, time_manager=time_manager_proc, combat_manager=combat_manager_proc, status_manager=status_manager_proc, party_manager=party_manager_proc, npc_manager=npc_manager_proc, event_stage_processor=event_stage_processor_casted, event_action_processor=self._event_action_processor, game_log_manager=game_log_manager_proc, openai_service=self.openai_service, event_manager=event_manager_proc, equipment_manager=equipment_manager_proc, inventory_manager=inventory_manager_proc, location_interaction_service=location_interaction_service_casted)
        self._character_view_service = CharacterViewService(character_manager=character_manager_proc, item_manager=item_manager_proc, location_manager=location_manager_proc, rule_engine=rule_engine_proc, status_manager=status_manager_proc, party_manager=party_manager_proc, equipment_manager=equipment_manager_proc, inventory_manager=inventory_manager_proc, ability_manager=ability_manager_proc, spell_manager=spell_manager_proc)
        self._party_action_processor = PartyActionProcessor(party_manager=party_manager_proc, send_callback_factory=self._get_discord_send_callback, rule_engine=rule_engine_proc, location_manager=location_manager_proc, character_manager=character_manager_proc, npc_manager=npc_manager_proc, time_manager=time_manager_proc, combat_manager=combat_manager_proc, event_stage_processor=event_stage_processor_casted, game_log_manager=game_log_manager_proc)
        self._party_command_handler = PartyCommandHandler(character_manager=character_manager_proc, party_manager=party_manager_proc, party_action_processor=self._party_action_processor, settings=self._settings, npc_manager=npc_manager_proc)

        self._persistence_manager = PersistenceManager(event_manager=event_manager_proc, character_manager=character_manager_proc, location_manager=location_manager_proc, db_service=db_service_proc, npc_manager=npc_manager_proc, combat_manager=combat_manager_proc, item_manager=item_manager_proc, time_manager=time_manager_proc, status_manager=status_manager_proc, crafting_manager=self.crafting_manager, economy_manager=self.economy_manager, party_manager=party_manager_proc, quest_manager=quest_manager_proc, relationship_manager=relationship_manager_proc, game_log_manager=game_log_manager_proc, dialogue_manager=dialogue_manager_proc, skill_manager=None, spell_manager=spell_manager_proc )

        self.guild_action_scheduler = GuildActionScheduler()
        npc_planner_services = {'rule_engine': rule_engine_proc, 'relationship_manager': relationship_manager_proc, 'location_manager': location_manager_proc }
        self.npc_action_planner = NPCActionPlanner(context_providing_services=npc_planner_services)
        npc_processor_managers = {'game_log_manager': game_log_manager_proc, 'location_manager': location_manager_proc, 'combat_manager': combat_manager_proc, 'character_manager': character_manager_proc, 'npc_manager': npc_manager_proc, 'item_manager': item_manager_proc, 'status_manager': status_manager_proc, 'event_manager': event_manager_proc, 'rule_engine': rule_engine_proc }
        self.npc_action_processor = NPCActionProcessor(managers=npc_processor_managers)

        if not self._character_action_processor: raise RuntimeError("CharacterActionProcessor not initialized for TurnProcessingService.")
        character_action_processor_casted = cast(CharacterActionProcessor, self._character_action_processor)

        self.turn_processing_service = TurnProcessingService(character_manager=character_manager_proc, rule_engine=rule_engine_proc, game_manager=self, game_log_manager=game_log_manager_proc, character_action_processor=character_action_processor_casted, combat_manager=combat_manager_proc, location_manager=location_manager_proc, location_interaction_service=location_interaction_service_casted, dialogue_manager=dialogue_manager_proc, inventory_manager=inventory_manager_proc, equipment_manager=equipment_manager_proc, item_manager=item_manager_proc, action_scheduler=self.guild_action_scheduler, npc_action_planner=self.npc_action_planner, npc_action_processor=self.npc_action_processor, npc_manager=npc_manager_proc, settings=self._settings)

        if not self._persistence_manager: raise RuntimeError("PersistenceManager not initialized for WorldSimulationProcessor.")
        if not self._party_action_processor: raise RuntimeError("PartyActionProcessor not initialized for WorldSimulationProcessor.")
        persistence_manager_casted = cast(PersistenceManager, self._persistence_manager)
        party_action_processor_casted = cast(PartyActionProcessor, self._party_action_processor)


        self.multilingual_prompt_generator_instance = getattr(self, 'multilingual_prompt_generator', None)

        self._world_simulation_processor = WorldSimulationProcessor(event_manager=event_manager_proc, character_manager=character_manager_proc, location_manager=location_manager_proc, rule_engine=rule_engine_proc, openai_service=self.openai_service, event_stage_processor=event_stage_processor_casted, event_action_processor=self._event_action_processor, persistence_manager=persistence_manager_casted, settings=self._settings, send_callback_factory=self._get_discord_send_callback, character_action_processor=character_action_processor_casted, party_action_processor=party_action_processor_casted, npc_manager=npc_manager_proc, combat_manager=combat_manager_proc, item_manager=item_manager_proc, time_manager=time_manager_proc, status_manager=status_manager_proc, crafting_manager=crafting_manager_proc, economy_manager=economy_manager_proc, party_manager=party_manager_proc, dialogue_manager=dialogue_manager_proc, quest_manager=quest_manager_proc, relationship_manager=relationship_manager_proc, game_log_manager=game_log_manager_proc, multilingual_prompt_generator=self.multilingual_prompt_generator_instance)

        self.turn_processor = TurnProcessor(game_manager=self)
        self.check_resolver = CheckResolver(game_manager=self)
        self.conflict_resolver = ConflictResolver(rule_engine=rule_engine_proc, notification_service=self.notification_service, db_service=db_service_proc, game_log_manager=game_log_manager_proc)

        if not self._world_simulation_processor: raise RuntimeError("WorldSimulationProcessor not initialized for CommandRouter.")
        if not self._character_view_service: raise RuntimeError("CharacterViewService not initialized for CommandRouter.")
        if not self._party_command_handler: raise RuntimeError("PartyCommandHandler not initialized for CommandRouter.")
        world_sim_proc_casted = cast(WorldSimulationProcessor, self._world_simulation_processor)
        char_view_svc_casted = cast(CharacterViewService, self._character_view_service)
        party_cmd_hdlr_casted = cast(PartyCommandHandler, self._party_command_handler)
        campaign_loader_casted = cast(CampaignLoader, self.campaign_loader)
        conflict_resolver_casted = cast(ConflictResolver, self.conflict_resolver)


        self._command_router = CommandRouter(character_manager=character_manager_proc, event_manager=event_manager_proc, persistence_manager=persistence_manager_casted, settings=self._settings, world_simulation_processor=world_sim_proc_casted, send_callback_factory=self._get_discord_send_callback, character_action_processor=character_action_processor_casted, character_view_service=char_view_svc_casted, location_manager=location_manager_proc, rule_engine=rule_engine_proc, party_command_handler=party_cmd_hdlr_casted, openai_service=self.openai_service, item_manager=item_manager_proc, npc_manager=npc_manager_proc, combat_manager=combat_manager_proc, time_manager=time_manager_proc, status_manager=status_manager_proc, party_manager=party_manager_proc, crafting_manager=crafting_manager_proc, economy_manager=economy_manager_proc, party_action_processor=party_action_processor_casted, event_action_processor=self._event_action_processor, event_stage_processor=event_stage_processor_casted, quest_manager=quest_manager_proc, dialogue_manager=dialogue_manager_proc, campaign_loader=campaign_loader_casted, relationship_manager=relationship_manager_proc, game_log_manager=game_log_manager_proc, conflict_resolver=conflict_resolver_casted, game_manager=self)
        logger.info("GameManager: Processors and command system initialized.")

    async def _initialize_ai_content_services(self):
        logger.info("GameManager: Initializing AI content generation services...")
        from bot.ai.prompt_context_collector import PromptContextCollector
        from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
        from bot.ai.ai_response_validator import AIResponseValidator
        from bot.services.nlu_data_service import NLUDataService

        crit_managers_ai_map = {
            "DBService": self.db_service, "CharacterManager": self.character_manager,
            "NpcManager": self.npc_manager, "QuestManager": self.quest_manager,
            "RelationshipManager": self.relationship_manager, "ItemManager": self.item_manager,
            "LocationManager": self.location_manager, "EventManager": self.event_manager,
            "AbilityManager": self.ability_manager, "SpellManager": self.spell_manager,
            "PartyManager": self.party_manager, "LoreManager": self.lore_manager
        }
        for name, manager_instance in crit_managers_ai_map.items():
            if not manager_instance: raise RuntimeError(f"{name} not initialized for AI content services.")

        db_service_ai = cast(DBService, self.db_service)
        char_manager_ai = cast(CharacterManager, self.character_manager)
        npc_manager_ai = cast(NpcManager, self.npc_manager)
        quest_manager_ai = cast(QuestManager, self.quest_manager)
        rel_manager_ai = cast(RelationshipManager, self.relationship_manager)
        item_manager_ai = cast(ItemManager, self.item_manager)
        loc_manager_ai = cast(LocationManager, self.location_manager)
        event_manager_ai = cast(EventManager, self.event_manager)
        ability_manager_ai = cast(AbilityManager, self.ability_manager)
        spell_manager_ai = cast(SpellManager, self.spell_manager)
        party_manager_ai = cast(PartyManager, self.party_manager)
        lore_manager_ai = cast(LoreManager, self.lore_manager)


        self.nlu_data_service = NLUDataService(db_service=db_service_ai)
        self.prompt_context_collector = PromptContextCollector(settings=self._settings, db_service=db_service_ai, character_manager=char_manager_ai, npc_manager=npc_manager_ai, quest_manager=quest_manager_ai, relationship_manager=rel_manager_ai, item_manager=item_manager_ai, location_manager=loc_manager_ai, event_manager=event_manager_ai, ability_manager=ability_manager_ai, spell_manager=spell_manager_ai, party_manager=party_manager_ai, lore_manager=lore_manager_ai, game_manager=self)

        main_bot_lang = "en"
        if self._active_guild_ids and self._rules_config_cache and self._active_guild_ids[0] in self._rules_config_cache:
            first_guild_id = self._active_guild_ids[0]
            main_bot_lang = str(self._rules_config_cache.get(first_guild_id, {}).get('default_language', 'en'))

        self.multilingual_prompt_generator = MultilingualPromptGenerator(context_collector=self.prompt_context_collector, main_bot_language=main_bot_lang, settings=self._settings)
        if self.quest_manager and hasattr(self.quest_manager, 'multilingual_prompt_generator'): self.quest_manager.multilingual_prompt_generator = self.multilingual_prompt_generator
        if self.consequence_processor and hasattr(self.consequence_processor, 'prompt_context_collector'): self.consequence_processor.prompt_context_collector = self.prompt_context_collector

        self.ai_response_validator = AIResponseValidator()
        if self.quest_manager and hasattr(self.quest_manager, 'ai_validator'): self.quest_manager.ai_validator = self.ai_response_validator

        self.ai_generation_service = AIGenerationService(game_manager=self)
        logger.info("GameManager: AIGenerationService initialized.")
        logger.info("GameManager: AI content services initialized.")

    async def _ensure_guild_configs_exist(self) -> List[str]:
        logger.info("GameManager: Ensuring guild configurations exist before data loading...")
        if not self.db_service or not hasattr(self.db_service, 'get_session') or not callable(getattr(self.db_service, 'get_session')):
            logger.error("DBService or get_session method not available for _ensure_guild_configs_exist."); return []
        from bot.game.guild_initializer import initialize_new_guild
        successfully_initialized_guild_ids: List[str] = []
        guild_ids_to_process = list(self._active_guild_ids)
        if not guild_ids_to_process:
            default_id_for_setup = str(self._settings.get('default_guild_id_for_setup', "1364930265591320586"))
            logger.warning(f"No active_guild_ids. Using default: {default_id_for_setup}")
            guild_ids_to_process = [default_id_for_setup]
            if default_id_for_setup not in self._active_guild_ids: self._active_guild_ids.append(default_id_for_setup)

        get_session_method = getattr(self.db_service, 'get_session')

        for guild_id_str in guild_ids_to_process:
            logger.info(f"Processing guild_id: {guild_id_str}")
            op_success = False
            try:
                async with get_session_method() as session: # type: ignore[operator] # get_session_method is callable
                    async with session.begin():
                        test_guild_id_to_force_reinit = "1364930265591320586"
                        current_force_reinitialize_flag = (guild_id_str == test_guild_id_to_force_reinit)
                        if current_force_reinitialize_flag: logger.warning(f"FORCING REINITIALIZE for {guild_id_str}")
                        await initialize_new_guild(session, guild_id_str, force_reinitialize=current_force_reinitialize_flag)
                        op_success = True
                if op_success: logger.info(f"Successfully ensured/initialized GuildConfig for {guild_id_str}."); successfully_initialized_guild_ids.append(guild_id_str)
            except IntegrityError as ie: logger.exception(f"IntegrityError for guild {guild_id_str}")
            except Exception as e: logger.exception(f"Exception ensuring guild config for {guild_id_str}")
        logger.info(f"Completed. Successfully confirmed/initialized for: {successfully_initialized_guild_ids}")
        return successfully_initialized_guild_ids

    async def _load_initial_data_and_state(self, confirmed_guild_ids: List[str]):
        logger.info(f"Loading initial game data for confirmed_guild_ids: {confirmed_guild_ids}")
        if not confirmed_guild_ids: logger.warning("No confirmed_guild_ids. Skipping data load."); return
        if self.campaign_loader:
            for guild_id_str in confirmed_guild_ids:
                logger.info(f"Populating via CampaignLoader for guild {guild_id_str}.")
                try: await self.campaign_loader.populate_all_game_data(guild_id=guild_id_str, campaign_identifier=None)
                except Exception as e: logger.exception(f"Error populating game data for {guild_id_str}")
        else: logger.warning("CampaignLoader not available.")
        if self._persistence_manager:
            logger.info(f"PersistenceManager loading game state for confirmed guilds: {confirmed_guild_ids}")
            try: await self._persistence_manager.load_game_state(guild_ids=confirmed_guild_ids)
            except Exception as e: logger.exception(f"Error loading game state")
        else: logger.warning("PersistenceManager not available.")
        logger.info("Finished _load_initial_data_and_state.")

    async def _start_background_tasks(self):
        logger.info("Starting background tasks...")
        if self._world_simulation_processor:
            self._world_tick_task = asyncio.create_task(self._world_tick_loop())
            logger.info("World tick loop started.")
        else: logger.warning("World tick loop not started, WorldSimulationProcessor unavailable.")
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
            except Exception as shutdown_e: logger.exception(f"Error during shutdown from setup failure")
            raise

    async def handle_discord_message(self, message: "Message") -> None:
        if message.author.bot: return
        if not self._command_router:
            logger.warning("CommandRouter not available, message '%s' from guild %s dropped.", message.content, message.guild.id if message.guild else "DM")
            if message.channel and hasattr(message.channel, 'send'): # Check if channel can send messages
                try: await message.channel.send(f"❌ Игра еще не полностью запущена...")
                except Exception as cb_e: logger.exception("Error sending startup error")
            return
        if message.content.startswith(str(self._settings.get('command_prefix', '/'))): # Ensure command_prefix is str
            logger.info("Passing command from %s (Guild: %s) to CommandRouter: '%s'", message.author.name, message.guild.id if message.guild else 'DM', message.content)
        try:
            if self._command_router: # Re-check after initial None check, for safety
                await self._command_router.route(message)
        except Exception as e:
            logger.exception(f"Error handling message '{message.content}'")
            try:
                if message.channel and hasattr(message.channel, 'send'):
                    await message.channel.send(f"❌ Внутренняя ошибка.")
                else: logger.warning("Cannot send error (DM or no channel).")
            except Exception as cb_e: logger.exception("Error sending internal error message")

    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback:
        async def _send(content: str = "", **kwargs: Any) -> None:
            channel: Optional[discord.abc.Messageable] = cast(Optional[discord.abc.Messageable], self._discord_client.get_channel(channel_id))
            if channel and isinstance(channel, discord.abc.Messageable):
                try: await channel.send(content, **kwargs)
                except Exception as e: logger.exception(f"Error sending to {channel_id}")
            else: logger.warning(f"Channel {channel_id} not found or not Messageable.")
        return _send

    async def _process_player_turns_for_tick(self, guild_id_str: str) -> None:
        if not self.turn_processor or not self.character_manager: logger.warning(f"Tick-{guild_id_str}: TurnProcessor/CharacterManager unavailable."); return
        try:
            if self.turn_processor: await self.turn_processor.process_turns_for_guild(guild_id_str)
        except Exception as tps_e: logger.exception(f"Tick-{guild_id_str}: Error in TurnProcessor")

    async def _world_tick_loop(self) -> None:
        logger.info("Starting world tick loop...")
        try:
            while True:
                await asyncio.sleep(self._tick_interval_seconds)
                if self._world_simulation_processor:
                    try: await self._world_simulation_processor.process_world_tick(game_time_delta=self._tick_interval_seconds)
                    except Exception as e: logger.exception(f"Error during world sim tick")
                for guild_id_str in self._active_guild_ids: await self._process_player_turns_for_tick(guild_id_str)
        except asyncio.CancelledError: logger.info("World tick loop cancelled.")
        except Exception as e: logger.critical(f"Critical error in world tick loop: {e}", exc_info=True)

    async def save_game_state_after_action(self, guild_id: str) -> None:
        if not self._persistence_manager: logger.warning(f"PersistenceManager unavailable for guild {guild_id}."); return
        try: await self._persistence_manager.save_game_state(guild_ids=[str(guild_id)])
        except Exception as e: logger.exception(f"Error saving game state for {guild_id}")

    async def shutdown(self) -> None:
        logger.info("Running shutdown...")
        if self._world_tick_task and not self._world_tick_task.done():
            self._world_tick_task.cancel()
            try: await asyncio.wait_for(self._world_tick_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError): logger.info("World tick task cancelled/timed out.")
            except Exception as e: logger.exception(f"Error waiting for world tick task")
        if self._persistence_manager and self.db_service:
            try: await self._persistence_manager.save_game_state(guild_ids=self._active_guild_ids)
            except Exception as e: logger.exception(f"Error saving game state on shutdown")
        if self.db_service:
            try: await self.db_service.close()
            except Exception as e: logger.exception(f"Error closing DB service")
        logger.info("Shutdown complete.")

    async def get_player_by_discord_id(self, discord_id: int, guild_id: str) -> Optional[Character]:
        if not self.character_manager: return None
        try:
            char_result = await self.character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_id)
            if isinstance(char_result, Character):
                return char_result
            return None
        except Exception as e: logger.exception(f"Error in get_player_by_discord_id"); return None

    async def _load_or_initialize_rules_config(self, guild_id: str):
        logger.info(f"Loading/Init rules for guild_id: {guild_id}...")
        self._rules_config_cache.setdefault(guild_id, {}) # Ensure guild_id key exists
        if not self.db_service:
            logger.error(f"DBService unavailable for rules config of guild {guild_id}.")
            self._rules_config_cache[guild_id] = {"default_bot_language": "en", "error_state": "DBService unavailable", "emergency_mode": True}
            return

        from bot.utils.config_utils import load_rules_config as util_load_rules_config
        try:
            get_session_method = getattr(self.db_service, "get_session", None)
            if not callable(get_session_method):
                logger.error(f"DBService for guild {guild_id} missing 'get_session' method for rules config.")
                self._rules_config_cache[guild_id] = {"default_bot_language": "en", "error_state": "DBService.get_session missing", "emergency_mode": True}
                return

            async with get_session_method() as session: # type: ignore[operator]
                guild_rules_dict = await util_load_rules_config(session, guild_id)

            if guild_rules_dict and isinstance(guild_rules_dict, dict): # Check if it's a dict
                self._rules_config_cache[guild_id] = guild_rules_dict
                logger.info(f"RulesConfig for {guild_id} loaded ({len(guild_rules_dict)} rules).")
            else:
                logger.warning(f"No rules for guild {guild_id} in DB or not a dict. Initializing.")
                from bot.game.guild_initializer import initialize_new_guild
                async with get_session_method() as init_session: # type: ignore[operator]
                    async with init_session.begin(): # Ensure transaction for initialization
                        await initialize_new_guild(init_session, guild_id, force_reinitialize=False)
                    # Re-fetch after initialization
                    guild_rules_dict_after_init = await util_load_rules_config(init_session, guild_id)
                    self._rules_config_cache[guild_id] = guild_rules_dict_after_init if isinstance(guild_rules_dict_after_init, dict) else {}
                    logger.info(f"RulesConfig for {guild_id} initialized ({len(self._rules_config_cache[guild_id])} rules).")
                if not self._rules_config_cache.get(guild_id):
                    self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": "Init failed or no rules after re-fetch."};
                    logger.error(f"Failed to load/init rules for {guild_id} even after initialization attempt.")
        except Exception as e:
            logger.exception(f"Exception during rules config for {guild_id}")
            self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": f"Exception: {str(e)}"}


    async def get_rule(self, guild_id: str, key: str, default: Optional[Any] = None) -> Optional[Any]:
        if guild_id not in self._rules_config_cache: await self._load_or_initialize_rules_config(guild_id)
        guild_specific_cache = self._rules_config_cache.get(guild_id)
        if guild_specific_cache is not None and isinstance(guild_specific_cache, dict):
            return guild_specific_cache.get(key, default)
        logger.warning(f"Guild {guild_id} not in cache or cache is not a dict for rule '{key}'. Returning default."); return default

    async def get_location_type_i18n_map(self, guild_id: str, type_key: str) -> Optional[Dict[str, str]]:
        if not self.rule_engine: logger.warning(f"RuleEngine unavailable for guild {guild_id}."); return None
        try:
            rules_config_model = await self.get_core_rules_config_for_guild(guild_id)
            if rules_config_model and hasattr(rules_config_model, 'location_type_definitions') and \
               isinstance(rules_config_model.location_type_definitions, dict):
                i18n_map_any = rules_config_model.location_type_definitions.get(type_key)
                if i18n_map_any is None: logger.warning(f"Key '{type_key}' not in location_type_definitions for {guild_id}.")
                elif isinstance(i18n_map_any, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in i18n_map_any.items()):
                    return cast(Dict[str,str], i18n_map_any)
                else:
                    logger.warning(f"Value for key '{type_key}' in location_type_definitions is not Dict[str, str] for {guild_id}.")

            elif rules_config_model: logger.warning(f"location_type_definitions not in CoreGameRulesConfig or not a dict for {guild_id}.")
            else: logger.warning(f"CoreGameRulesConfig not available for {guild_id}.")
        except Exception as e: logger.exception(f"Error retrieving location type defs for {guild_id}, key '{type_key}'")
        return None

    async def get_core_rules_config_for_guild(self, guild_id: str) -> Optional[CoreGameRulesConfig]:
        if guild_id not in self._rules_config_cache: await self._load_or_initialize_rules_config(guild_id)
        raw_rules_dict = self._rules_config_cache.get(guild_id)
        if not raw_rules_dict or not isinstance(raw_rules_dict, dict):
            logger.warning(f"No raw rules dict or not a dict for {guild_id}."); return None
        try:
            return CoreGameRulesConfig(**raw_rules_dict)
        except ValidationError as ve:
            logger.exception(f"Pydantic validation error for CoreGameRulesConfig guild {guild_id}")
            logger.debug(f"Problematic dict for CoreGameRulesConfig {guild_id}: {raw_rules_dict}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error parsing CoreGameRulesConfig for {guild_id}")
            return None

    async def update_rule_config(self, guild_id: str, key: str, value: Any) -> bool:
        if not self.db_service: logger.error(f"DBService unavailable for update_rule_config (guild {guild_id})."); return False
        from bot.utils.config_utils import update_rule_config as util_update_rule_config
        try:
            get_session_method = getattr(self.db_service, "get_session", None)
            if not callable(get_session_method):
                logger.error(f"DBService for guild {guild_id} missing 'get_session' for update_rule_config.")
                return False
            async with get_session_method() as session: # type: ignore[operator]
                await util_update_rule_config(session, guild_id, key, value)
            self._rules_config_cache.setdefault(guild_id, {})[key] = value # Ensure guild_id key exists
            logger.info(f"Rule '{key}' for {guild_id} updated in DB and cache."); return True
        except Exception as e:
            logger.exception(f"Exception updating rule '{key}' for {guild_id}")
            if guild_id in self._rules_config_cache and isinstance(self._rules_config_cache[guild_id], dict):
                self._rules_config_cache[guild_id].pop(key, None)
                logger.info(f"Cache for rule '{key}' ({guild_id}) cleared due to error.")
            return False

    async def set_default_bot_language(self, language: str, guild_id: Optional[str] = None) -> bool:
        if not guild_id: return False
        success = await self.update_rule_config(guild_id, "default_language", language)
        if success and self.multilingual_prompt_generator and hasattr(self.multilingual_prompt_generator, 'update_main_bot_language') and callable(getattr(self.multilingual_prompt_generator, 'update_main_bot_language')):
            if self._active_guild_ids and guild_id == self._active_guild_ids[0]: # Check if it's the primary guild for MPG
                 update_main_lang_method = getattr(self.multilingual_prompt_generator, 'update_main_bot_language')
                 update_main_lang_method(language)
                 logger.info(f"Updated MultilingualPromptGenerator main lang to '{language}' for primary guild '{guild_id}'.")
            else: logger.info(f"Default lang for '{guild_id}' to '{language}', not updating global prompt gen lang as it's not primary guild or MPG missing method.")
        return success

    async def get_player_model_by_discord_id(self, guild_id: str, discord_id: str) -> Optional[Player]:
        if not self.db_service or not hasattr(self.db_service, 'get_entities_by_conditions') or not callable(getattr(self.db_service, 'get_entities_by_conditions')):
            logger.warning("DBService or get_entities_by_conditions not available for get_player_model_by_discord_id.")
            return None
        get_entities_method = getattr(self.db_service, 'get_entities_by_conditions')
        results: Optional[List[Player]] = await get_entities_method(Player, conditions={'guild_id': str(guild_id), 'discord_id': str(discord_id)})
        return results[0] if results else None

    async def get_player_model_by_id(self, guild_id: str, player_id: str) -> Optional[Player]:
        if not self.db_service or not hasattr(self.db_service, 'get_entity_by_pk') or not callable(getattr(self.db_service, 'get_entity_by_pk')):
            logger.warning("DBService or get_entity_by_pk not available for get_player_model_by_id.")
            return None
        get_entity_pk_method = getattr(self.db_service, 'get_entity_by_pk')
        result: Optional[Player] = await get_entity_pk_method(Player, pk_value=str(player_id), guild_id=str(guild_id))
        return result

    async def get_players_in_location(self, guild_id: str, location_id: str) -> List[Player]:
        if not self.db_service or not hasattr(self.db_service, 'get_entities_by_conditions') or not callable(getattr(self.db_service, 'get_entities_by_conditions')):
            logger.warning("DBService or get_entities_by_conditions not available for get_players_in_location.")
            return []
        get_entities_method = getattr(self.db_service, 'get_entities_by_conditions')
        results: Optional[List[Player]] = await get_entities_method(Player, conditions={'guild_id': str(guild_id), 'current_location_id': str(location_id)})
        return results if results else []

    async def handle_move_action(self, guild_id: str, character_id: str, target_location_identifier: str) -> bool:
        if not self.location_manager or not hasattr(self.location_manager, 'process_character_move') or not callable(getattr(self.location_manager, 'process_character_move')):
            logger.error("LocationManager or process_character_move method unavailable."); return False
        process_move_method = getattr(self.location_manager, 'process_character_move')
        return await process_move_method(guild_id=guild_id, character_id=character_id, target_location_identifier=target_location_identifier)

    async def trigger_ai_generation(self, guild_id: str, request_type: str, request_params: Dict[str, Any], created_by_user_id: Optional[str] = None) -> Optional[str]:
        if not self.ai_generation_service or not hasattr(self.ai_generation_service, 'request_content_generation') or not callable(getattr(self.ai_generation_service, 'request_content_generation')):
            logger.error("AIGenerationService or request_content_generation method unavailable."); return None

        try: req_type_enum = GenerationType(request_type)
        except ValueError: logger.error(f"Invalid request_type string '{request_type}' for AI generation."); return None

        # Example structure for context_params and prompt_params, adjust as per actual usage
        context_params_extracted = request_params.get("context_params", {}) if isinstance(request_params.get("context_params"), dict) else {}
        prompt_params_extracted = request_params.get("prompt_params", {}) if isinstance(request_params.get("prompt_params"), dict) else {}


        pending_gen_record = await self.ai_generation_service.request_content_generation(
            guild_id=guild_id,
            request_type=req_type_enum,
            context_params=context_params_extracted,
            prompt_params=prompt_params_extracted,
            created_by_user_id=created_by_user_id
        )
        return str(pending_gen_record.id) if pending_gen_record and hasattr(pending_gen_record, 'id') and pending_gen_record.id else None

    async def apply_approved_generation(self, pending_gen_id: str, guild_id: str) -> bool:
        if not self.ai_generation_service or not hasattr(self.ai_generation_service, 'process_approved_generation') or not callable(getattr(self.ai_generation_service, 'process_approved_generation')):
            logger.error("AIGenerationService or process_approved_generation method unavailable."); return False
        process_approved_method = getattr(self.ai_generation_service, 'process_approved_generation')
        return await process_approved_method(pending_gen_id=pending_gen_id, guild_id=guild_id, moderator_user_id="SYSTEM_AUTO_APPROVE")

    async def is_user_master(self, guild_id: str, user_id: int) -> bool:
        """Checks if a user is a master for the given guild."""
        # This is a placeholder implementation.
        # In a real scenario, this would likely check against a list of master user IDs
        # stored in GuildConfig or another configuration mechanism.
        # For now, let's assume it checks a simple rule or a hardcoded list for testing.
        # It might also involve checking roles if masters are defined by a Discord role.

        # Example: Check against a rule in RulesConfig
        master_user_ids_raw = await self.get_rule(guild_id, "master_user_ids", default=[])
        master_user_ids = [str(uid) for uid in master_user_ids_raw] if isinstance(master_user_ids_raw, list) else []

        if str(user_id) in master_user_ids:
            return True

        # Fallback or additional checks (e.g., admin roles) could go here.
        # For simplicity, this example only checks the list.
        return False


# logger.debug("DEBUG: Finished loading game_manager.py from: %s", __file__) # Debug log can be noisy
