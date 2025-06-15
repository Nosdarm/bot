# bot/game/managers/game_manager.py

import asyncio
import json
import traceback # Will be removed
import os
import io
import logging # Added
from alembic.config import Config
from alembic import command
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING

from asyncpg import exceptions as asyncpg_exceptions
from bot.database.postgres_adapter import SQLALCHEMY_DATABASE_URL as PG_URL_FOR_ALEMBIC

import discord
from discord import Client

from bot.services.db_service import DBService
from bot.ai.rules_schema import GameRules
from bot.game.models.character import Character
from bot.services.notification_service import NotificationService # Added runtime import

if TYPE_CHECKING:
    from discord import Message
    # from bot.game.models.character import Character # Already imported
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.inventory_manager import InventoryManager # Added
    from bot.game.managers.equipment_manager import EquipmentManager # Added
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
    from bot.services.notification_service import NotificationService
    from bot.game.turn_processing_service import TurnProcessingService

logger = logging.getLogger(__name__) # Added
logger.debug("--- Начинается загрузка: game_manager.py") # Changed

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

DEFAULT_RULES_CONFIG_ID = "main_rules_config"

class GameManager:
    def __init__(
        self,
        discord_client: Client,
        settings: Dict[str, Any]
    ):
        logger.info("Initializing GameManager…") # Changed
        self._discord_client = discord_client
        self._settings = settings
        self._rules_config_cache: Optional[Dict[str, Any]] = None
        self.db_service: Optional[DBService] = None
        self._persistence_manager: Optional["PersistenceManager"] = None
        self._world_simulation_processor: Optional["WorldSimulationProcessor"] = None
        self._command_router: Optional["CommandRouter"] = None
        self.rule_engine: Optional["RuleEngine"] = None
        self.time_manager: Optional["TimeManager"] = None
        self.location_manager: Optional["LocationManager"] = None
        self.event_manager: Optional["EventManager"] = None
        self.character_manager: Optional["CharacterManager"] = None
        self.item_manager: Optional["ItemManager"] = None
        self.inventory_manager: Optional["InventoryManager"] = None # Added
        self.equipment_manager: Optional["EquipmentManager"] = None # Added
        self.status_manager: Optional["StatusManager"] = None
        self.combat_manager: Optional["CombatManager"] = None
        self.crafting_manager: Optional["CraftingManager"] = None
        self.economy_manager: Optional["EconomyManager"] = None
        self.npc_manager: Optional["NpcManager"] = None
        self.party_manager: Optional["PartyManager"] = None
        self.openai_service: Optional["OpenAIService"] = None
        self.conflict_resolver: Optional["ConflictResolver"] = None
        self.notification_service: Optional["NotificationService"] = None
        self.turn_processing_service: Optional["TurnProcessingService"] = None
        self.quest_manager: Optional["QuestManager"] = None
        self.relationship_manager: Optional["RelationshipManager"] = None
        self.dialogue_manager: Optional["DialogueManager"] = None
        self.game_log_manager: Optional["GameLogManager"] = None
        self.campaign_loader: Optional["CampaignLoader"] = None
        self.consequence_processor: Optional["ConsequenceProcessor"] = None
        self.nlu_data_service: Optional["NLUDataService"] = None
        self.ability_manager: Optional["AbilityManager"] = None
        self.spell_manager: Optional["SpellManager"] = None
        self.lore_manager: Optional["LoreManager"] = None
        self.prompt_context_collector: Optional["PromptContextCollector"] = None
        self.multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None
        self._on_enter_action_executor: Optional["OnEnterActionExecutor"] = None
        self._stage_description_generator: Optional["StageDescriptionGenerator"] = None
        self._event_stage_processor: Optional["EventStageProcessor"] = None
        self._event_action_processor: Optional["EventActionProcessor"] = None
        self._character_action_processor: Optional["CharacterActionProcessor"] = None
        self._character_view_service: Optional["CharacterViewService"] = None
        self._party_action_processor: Optional["PartyActionProcessor"] = None
        self._party_command_handler: Optional["PartyCommandHandler"] = None
        self._world_tick_task: Optional[asyncio.Task] = None
        self._tick_interval_seconds: float = settings.get('world_tick_interval_seconds', 60.0)
        self._active_guild_ids: List[str] = [str(gid) for gid in self._settings.get('active_guild_ids', [])]
        logger.info("GameManager initialized.") # Changed

    async def _load_or_initialize_rules_config(self):
        logger.info("GameManager: Loading or initializing rules configuration...") # Changed
        self._rules_config_cache = {}
        if not self.db_service:
            logger.error("GameManager: DBService not available for loading rules config.") # Changed
            self._rules_config_cache = { # Fallback
                "default_bot_language": "en", "game_world_name": "Default World (DB Error)",
                # ... (other default rules as before)
            }
            logger.warning("GameManager: Used fallback default rules due to DBService unavailability at time of call.") # Changed
            return

        data = None
        try:
            data = await self.db_service.get_entity(table_name='rules_config', entity_id=DEFAULT_RULES_CONFIG_ID, id_field='guild_id')
        except Exception as e:
            logger.error("GameManager: Error fetching rules_config from DB: %s", e, exc_info=True) # Changed

        if data and 'config_data' in data:
            try:
                self._rules_config_cache = data['config_data']
                logger.info("GameManager: Successfully loaded rules from DB for ID %s.", DEFAULT_RULES_CONFIG_ID) # Changed
                if "default_bot_language" not in self._rules_config_cache:
                    logger.warning("GameManager: Loaded rules lack 'default_bot_language'. Consider migration or re-init.") # Changed
            except json.JSONDecodeError as e:
                logger.error("GameManager: Error decoding JSON from rules_config DB: %s. Proceeding with default rules.", e, exc_info=True) # Changed
                data = None
            except Exception as e:
                logger.error("GameManager: Unexpected error loading/parsing rules_config: %s. Proceeding with default rules.", e, exc_info=True) # Changed
                data = None

        if not data or 'config_data' not in data or self._rules_config_cache is None or not self._rules_config_cache : # Ensure cache is not empty
            logger.info("GameManager: No valid rules found in DB for ID %s or error during load. Creating default rules...", DEFAULT_RULES_CONFIG_ID) # Changed
            default_rules = {
                "default_bot_language": "en", "game_world_name": "Default World",
                # ... (other default rules as before)
                 "party_rules": {"max_size": 4}
            }
            self._rules_config_cache = default_rules
            logger.info("GameManager: Default rules created and cached.") # Changed

            rules_entity_data = {'guild_id': DEFAULT_RULES_CONFIG_ID, 'config_data': json.dumps(self._rules_config_cache)}
            try:
                existing_config = await self.db_service.get_entity('rules_config', DEFAULT_RULES_CONFIG_ID, id_field='guild_id')
                if existing_config is not None:
                    logger.info("GameManager: Attempting to update existing default rules in DB (GuildID: %s).", DEFAULT_RULES_CONFIG_ID) # Changed
                    success = await self.db_service.update_entity('rules_config', DEFAULT_RULES_CONFIG_ID, {'config_data': json.dumps(self._rules_config_cache)}, guild_id=DEFAULT_RULES_CONFIG_ID, id_field='guild_id')
                    if success: logger.info("GameManager: Successfully updated default rules in DB.") # Changed
                    else: logger.error("GameManager: Failed to update default rules in DB.") # Changed
                else:
                    logger.info("GameManager: Attempting to create new default rules in DB (GuildID: %s).", DEFAULT_RULES_CONFIG_ID) # Changed
                    # For create_entity, the entity_id (DEFAULT_RULES_CONFIG_ID) is part of rules_entity_data if it's the PK.
                    # If guild_id is the PK, rules_entity_data should contain it.
                    # The id_field in create_entity refers to the field name that is the ID, not necessarily 'id'.
                    # Assuming 'guild_id' is now the primary key or unique identifier for rules_config.
                    new_id = await self.db_service.create_entity('rules_config', rules_entity_data, id_field='guild_id')
                    if new_id is not None: logger.info("GameManager: Successfully created default rules in DB with GuildID %s.", new_id) # Changed
                    else: logger.error("GameManager: Failed to create default rules in DB.") # Changed
            except Exception as e:
                logger.error("GameManager: Error during upsert of default rules to DB: %s", e, exc_info=True) # Changed

        if self._rules_config_cache is None or not self._rules_config_cache : # Final check
            logger.critical("GameManager: CRITICAL - Rules cache is still None or empty after load/init. Using emergency fallback.") # Changed
            self._rules_config_cache = { "default_bot_language": "en", "emergency_mode": True }

    async def _initialize_database(self):
        logger.info("GameManager: Initializing database service...") # Changed
        self.db_service = DBService()
        await self.db_service.connect()
        # Alembic logic commented out, assuming it's handled elsewhere or not used in this flow.
        # If Alembic is used, its logs should be configured separately if needed.
        await self.db_service.initialize_database()
        logger.info("GameManager: DBService initialized.") # Changed

    async def _initialize_core_managers_and_services(self):
        logger.info("GameManager: Initializing core managers and services...") # Changed
        from bot.game.rules.rule_engine import RuleEngine
        from bot.game.managers.time_manager import TimeManager
        from bot.game.managers.location_manager import LocationManager
        from bot.game.managers.event_manager import EventManager
        # CharacterManager import moved to _initialize_dependent_managers
        from bot.services.openai_service import OpenAIService

        await self._load_or_initialize_rules_config()
        self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}), rules_data=self._rules_config_cache)
        self.time_manager = TimeManager(db_service=self.db_service, settings=self._settings.get('time_settings', {}))
        self.location_manager = LocationManager(db_service=self.db_service, settings=self._settings)
        try:
            oset = self._settings.get('openai_settings', {})
            self.openai_service = OpenAIService(api_key=oset.get('api_key'), model=oset.get('model'), default_max_tokens=oset.get('default_max_tokens'))
            if not self.openai_service.is_available(): self.openai_service = None
        except Exception as e: self.openai_service = None; logger.warning("GameManager: Failed OpenAIService init (%s)", e, exc_info=True)

        self.event_manager = EventManager(db_service=self.db_service, settings=self._settings.get('event_settings', {}), openai_service=self.openai_service)
        # CharacterManager initialization moved
        logger.info("GameManager: Core managers (excluding CharacterManager) and OpenAI service initialized.")

    async def _initialize_dependent_managers(self):
        logger.info("GameManager: Initializing dependent managers...")
        from bot.game.managers.item_manager import ItemManager
        from bot.game.managers.status_manager import StatusManager
        from bot.game.managers.npc_manager import NpcManager
        from bot.game.managers.character_manager import CharacterManager # Moved import
        from bot.game.managers.inventory_manager import InventoryManager # Added import
        from bot.game.managers.equipment_manager import EquipmentManager # Added import
        from bot.game.managers.combat_manager import CombatManager # Ensure it's imported if not already
        # ... (other necessary imports like PartyManager, DialogueManager, etc. will be here or in their respective init blocks)
        from bot.game.managers.lore_manager import LoreManager

        self.item_manager = ItemManager(db_service=self.db_service, settings=self._settings, location_manager=self.location_manager, rule_engine=self.rule_engine)
        logger.info("GameManager: ItemManager initialized.")
        self.status_manager = StatusManager(db_service=self.db_service, settings=self._settings.get('status_settings', {}))
        logger.info("GameManager: StatusManager initialized.")

        # GameLogManager needs to be initialized before CharacterManager if CharacterManager logs extensively at init or uses it early.
        if not hasattr(self, 'game_log_manager') or self.game_log_manager is None:
            from bot.game.managers.game_log_manager import GameLogManager
            self.game_log_manager = GameLogManager(db_service=self.db_service)
            logger.info("GameManager: GameLogManager initialized (early in _initialize_dependent_managers).")

        if not hasattr(self, 'campaign_loader') or self.campaign_loader is None:
            from bot.game.services.campaign_loader import CampaignLoader
            self.campaign_loader = CampaignLoader(settings=self._settings, db_service=self.db_service)
            logger.info("GameManager: Initialized CampaignLoader.")

        if self.campaign_loader:
            campaign_identifier = self._settings.get('default_campaign_identifier')
            default_campaign_data = await self.campaign_loader.load_campaign_data_from_source(campaign_identifier=campaign_identifier)
            if default_campaign_data and isinstance(default_campaign_data.get('npc_archetypes'), dict):
                npc_archetypes_from_campaign = default_campaign_data['npc_archetypes']
                logger.info("GameManager: Loaded %s NPC archetypes from campaign '%s'.", len(npc_archetypes_from_campaign), campaign_identifier or 'default')
            else:
                npc_archetypes_from_campaign = {}
                logger.warning("GameManager: Could not load NPC archetypes from campaign '%s'. Using empty dict.", campaign_identifier or 'default')
        else:
            npc_archetypes_from_campaign = {}
            logger.warning("GameManager: CampaignLoader not available. NPC archetypes will be empty.")

        npc_manager_settings = self._settings.get('npc_settings', {}).copy()
        npc_manager_settings['loaded_npc_archetypes_from_campaign'] = npc_archetypes_from_campaign

        # NpcManager needs status_manager (now available) and potentially combat_manager.
        # CombatManager initialization is further down, so self.combat_manager might be None here.
        # NpcManager's __init__ must be able to handle combat_manager=None if it's a dependency.
        self.npc_manager = NpcManager(
            db_service=self.db_service,
            settings=npc_manager_settings,
            item_manager=self.item_manager,
            rule_engine=self.rule_engine,
            combat_manager=self.combat_manager,
            status_manager=self.status_manager,
            openai_service=self.openai_service,
            campaign_loader=self.campaign_loader
        )
        logger.info("GameManager: NpcManager initialized.")

        # Initialize CharacterManager (must be before InventoryManager and EquipmentManager)
        # As per previous subtask, CharacterManager needs InventoryManager and EquipmentManager in constructor.
        # However, current subtask makes InventoryManager need CharacterManager.
        # To break the immediate cycle for this step, CharacterManager is created,
        # then InventoryManager, then EquipmentManager.
        # This implies CharacterManager might need setters for Inventory/Equipment managers or handle them being None initially.
        self.character_manager = CharacterManager(
            db_service=self.db_service,
            settings=self._settings,
            item_manager=self.item_manager,
            location_manager=self.location_manager,
            rule_engine=self.rule_engine,
            status_manager=self.status_manager,
            # party_manager, combat_manager, dialogue_manager, relationship_manager will be None if not yet initialized
            party_manager=self.party_manager,
            combat_manager=self.combat_manager,
            dialogue_manager=self.dialogue_manager,
            relationship_manager=self.relationship_manager,
            game_log_manager=self.game_log_manager,
            npc_manager=self.npc_manager,
            # inventory_manager and equipment_manager are not passed here to break constructor cycle
            inventory_manager=None,
            equipment_manager=None,
            game_manager=self
        )
        logger.info("GameManager: CharacterManager initialized (inventory/equipment managers will be set if needed).")

        # Initialize InventoryManager (Corrected: needs CharacterManager)
        self.inventory_manager = InventoryManager(character_manager=self.character_manager, item_manager=self.item_manager)
        logger.info("GameManager: InventoryManager initialized.")
        # If CharacterManager has a setter for inventory_manager:
        if hasattr(self.character_manager, '_inventory_manager') and self.character_manager._inventory_manager is None:
             self.character_manager._inventory_manager = self.inventory_manager # Or a public setter method
             logger.info("GameManager: Set inventory_manager in CharacterManager.")


        # Initialize EquipmentManager (Corrected: needs multiple managers)
        self.equipment_manager = EquipmentManager(
            character_manager=self.character_manager,
            inventory_manager=self.inventory_manager,
            item_manager=self.item_manager,
            status_manager=self.status_manager,
            rule_engine=self.rule_engine,
            db_service=self.db_service
        )
        logger.info("GameManager: EquipmentManager initialized.")
        # If CharacterManager has a setter for equipment_manager:
        if hasattr(self.character_manager, '_equipment_manager') and self.character_manager._equipment_manager is None:
             self.character_manager._equipment_manager = self.equipment_manager # Or a public setter method
             logger.info("GameManager: Set equipment_manager in CharacterManager.")

        # Initialize CombatManager (depends on CharacterManager, NpcManager, StatusManager, etc.)
        # Moved up to be available for PartyManager
        if not hasattr(self, 'combat_manager') or self.combat_manager is None:
             from bot.game.managers.combat_manager import CombatManager
             self.combat_manager = CombatManager(
                 db_service=self.db_service,
                 settings=self._settings.get('combat_settings',{}),
                 rule_engine=self.rule_engine,
                 character_manager=self.character_manager,
                 npc_manager=self.npc_manager,
                 party_manager=self.party_manager, # party_manager might be None here if not moved before CombatManager
                 status_manager=self.status_manager,
                 item_manager=self.item_manager,
                 location_manager=self.location_manager
            )
             logger.info("GameManager: CombatManager initialized.")
             if self.character_manager and self.character_manager._combat_manager is None:
                 self.character_manager._combat_manager = self.combat_manager
                 logger.info("GameManager: Updated combat_manager in CharacterManager.")
             if self.npc_manager and self.npc_manager._combat_manager is None: # Changed to _combat_manager
                 self.npc_manager._combat_manager = self.combat_manager # Changed to _combat_manager
                 logger.info("GameManager: Updated combat_manager in NpcManager.")

        # Initialize PartyManager (Corrected: needs CombatManager)
        if not hasattr(self, 'party_manager') or self.party_manager is None:
            from bot.game.managers.party_manager import PartyManager
            self.party_manager = PartyManager(
                db_service=self.db_service,
                settings=self._settings.get('party_settings', {}),
                npc_manager=self.npc_manager,
                character_manager=self.character_manager,
                combat_manager=self.combat_manager # Added combat_manager
            )
            logger.info("GameManager: PartyManager initialized.")
            if self.character_manager and not self.character_manager._party_manager:
                 self.character_manager._party_manager = self.party_manager
                 logger.info("GameManager: Updated party_manager in CharacterManager.")
            # If CombatManager needs PartyManager and was initialized with None for it:
            if self.combat_manager and self.combat_manager._party_manager is None: # Changed to _party_manager
                self.combat_manager._party_manager = self.party_manager # Changed to _party_manager
                logger.info("GameManager: Updated party_manager in CombatManager.")

        self.lore_manager = LoreManager(settings=self._settings.get('lore_settings', {}), db_service=self.db_service)
        logger.info("GameManager: LoreManager initialized.")

        # Initialize NotificationService (depends on CharacterManager)
        if self.character_manager:
            self.notification_service = NotificationService(
                send_callback_factory=self._get_discord_send_callback,
                settings=self._settings,
                i18n_utils=None,
                character_manager=self.character_manager
            )
            logger.info("GameManager: NotificationService initialized.")
        else:
            logger.error("GameManager: CharacterManager not available, cannot initialize NotificationService.")
            self.notification_service = None

        # Other managers like QuestManager, DialogueManager, RelationshipManager, etc.
        # should be initialized here, ensuring their dependencies are met. (PartyManager moved up)
        # For example, DialogueManager might need NpcManager and CharacterManager.
        # from bot.game.managers.dialogue_manager import DialogueManager
        # self.dialogue_manager = DialogueManager(db_service=self.db_service, character_manager=self.character_manager, npc_manager=self.npc_manager, ...)
        # logger.info("GameManager: DialogueManager initialized.")
        # if self.character_manager and not self.character_manager._dialogue_manager:
        #    self.character_manager._dialogue_manager = self.dialogue_manager
        # if self.npc_manager and not self.npc_manager.dialogue_manager:
        #    self.npc_manager.dialogue_manager = self.dialogue_manager


        logger.info("GameManager: Dependent managers initialized.")

    async def _initialize_processors_and_command_system(self):
        logger.info("GameManager: Initializing processors and command system...") # Changed
        # ... (Imports as before)
        from bot.game.managers.undo_manager import UndoManager
        from bot.game.character_processors.character_action_processor import CharacterActionProcessor
        from bot.game.character_processors.character_view_service import CharacterViewService
        from bot.game.party_processors.party_action_processor import PartyActionProcessor
        from bot.game.command_handlers.party_handler import PartyCommandHandler
        from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
        from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
        from bot.game.event_processors.event_stage_processor import EventStageProcessor
        from bot.game.event_processors.event_action_processor import EventActionProcessor
        from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
        from bot.game.managers.persistence_manager import PersistenceManager
        from bot.game.command_router import CommandRouter
        # Ensure all managers that are dependencies here are imported or initialized before this function
        from bot.game.managers.crafting_manager import CraftingManager
        from bot.game.managers.economy_manager import EconomyManager
        # PartyManager already imported and initialized in _initialize_dependent_managers
        from bot.game.managers.quest_manager import QuestManager # Ensure QuestManager is available
        from bot.game.managers.relationship_manager import RelationshipManager
        from bot.game.managers.dialogue_manager import DialogueManager
        # GameLogManager already initialized in _initialize_dependent_managers
        from bot.game.managers.ability_manager import AbilityManager
        from bot.game.managers.spell_manager import SpellManager
        from bot.game.conflict_resolver import ConflictResolver
        from bot.game.turn_processing_service import TurnProcessingService


        # Initialize managers that might not have been initialized yet or are specific to this stage
        # QuestManager example (if not already initialized and is needed by UndoManager or others)
        if not hasattr(self, 'quest_manager') or self.quest_manager is None:
            # Assuming QuestManager needs at least db_service. Add other dependencies as required.
            self.quest_manager = QuestManager(db_service=self.db_service, character_manager=self.character_manager, settings=self._settings.get('quest_settings', {}))
            logger.info("GameManager: QuestManager initialized in _initialize_processors_and_command_system.")

        if not hasattr(self, 'dialogue_manager') or self.dialogue_manager is None:
            from bot.game.managers.dialogue_manager import DialogueManager
            # Make sure all managers DialogueManager *does* accept and are available are passed.
            # Based on DialogueManager.__init__ these are:
            # db_service, settings, character_manager, npc_manager, rule_engine,
            # event_stage_processor, time_manager, openai_service, relationship_manager,
            # game_log_manager, quest_manager, notification_service.

            self.dialogue_manager = DialogueManager(
                db_service=self.db_service,
                settings=self._settings.get('dialogue_settings', {}),
                character_manager=self.character_manager,
                npc_manager=self.npc_manager,
                rule_engine=self.rule_engine,
                # event_stage_processor is self._event_stage_processor, ensure it's initialized *before* DialogueManager if passed.
                # For now, let's assume EventStageProcessor might not be ready or strictly needed for DialogueManager init
                # and rely on DialogueManager's optional nature for these.
                # The critical fix is removing event_manager.
                # Let's add the ones that are definitely available and were in its __init__
                time_manager=self.time_manager,
                openai_service=self.openai_service,
                relationship_manager=self.relationship_manager, # This itself might not be initialized yet.
                game_log_manager=self.game_log_manager,
                quest_manager=self.quest_manager, # This is initialized earlier in this method.
                notification_service=self.notification_service # This is initialized in _initialize_dependent_managers
                # event_stage_processor=self._event_stage_processor # Let's defer adding this unless a new error points to it.
            )
            logger.info("GameManager: DialogueManager initialized in _initialize_processors_and_command_system.")
            if self.character_manager and hasattr(self.character_manager, '_dialogue_manager') and self.character_manager._dialogue_manager is None:
                self.character_manager._dialogue_manager = self.dialogue_manager
            if self.npc_manager and hasattr(self.npc_manager, 'dialogue_manager') and self.npc_manager.dialogue_manager is None:
                self.npc_manager.dialogue_manager = self.dialogue_manager

        if self.db_service and self.game_log_manager and self.character_manager and self.item_manager and self.quest_manager and self.party_manager:
            self.undo_manager = UndoManager(db_service=self.db_service, game_log_manager=self.game_log_manager, character_manager=self.character_manager, item_manager=self.item_manager, quest_manager=self.quest_manager, party_manager=self.party_manager)
            logger.info("GameManager: UndoManager initialized.")
        else:
            logger.critical("GameManager: UndoManager could not be initialized due to missing dependencies (QuestManager or others might be missing).")
            self.undo_manager = None

        if not hasattr(self, '_on_enter_action_executor') or self._on_enter_action_executor is None:
            from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
            self._on_enter_action_executor = OnEnterActionExecutor(
                npc_manager=self.npc_manager,
                item_manager=self.item_manager,
                combat_manager=self.combat_manager,
                status_manager=self.status_manager
            )
            logger.info("GameManager: OnEnterActionExecutor initialized.")

        if not hasattr(self, '_stage_description_generator') or self._stage_description_generator is None:
            from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
            self._stage_description_generator = StageDescriptionGenerator(
                openai_service=self.openai_service
            )
            logger.info("GameManager: StageDescriptionGenerator initialized.")

        # EventStageProcessor and EventActionProcessor are initialized here in original code
        # These might be needed by CharacterActionProcessor
        # Ensure their dependencies are met
        # For now, assuming they might be initialized later or CAP handles None
        # self._event_stage_processor = EventStageProcessor(...)
        # self._event_action_processor = EventActionProcessor(...)


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
            event_stage_processor=self._event_stage_processor, # Ensure this is initialized before CAP or CAP handles None
            event_action_processor=self._event_action_processor, # Ensure this is initialized before CAP or CAP handles None
            game_log_manager=self.game_log_manager,
            openai_service=self.openai_service,
            event_manager=self.event_manager,
            equipment_manager=self.equipment_manager,
            inventory_manager=self.inventory_manager
        )
        logger.info("GameManager: CharacterActionProcessor initialized.")

        # Initialize other processors and services like CharacterViewService, PartyActionProcessor, etc.
        # Ensure their dependencies, including those from the newly reordered managers, are available.
        if not hasattr(self, '_character_view_service') or not self._character_view_service:
            self._character_view_service = CharacterViewService(
                character_manager=self.character_manager,
                item_manager=self.item_manager,
                # Add other necessary dependencies for CharacterViewService
                status_manager=self.status_manager,
                equipment_manager=self.equipment_manager,
                inventory_manager=self.inventory_manager,
                ability_manager=self.ability_manager, # Ensure AbilityManager is initialized
                spell_manager=self.spell_manager # Ensure SpellManager is initialized
            )
            logger.info("GameManager: CharacterViewService initialized.")

        if not hasattr(self, '_party_action_processor') or not self._party_action_processor:
            self._party_action_processor = PartyActionProcessor(
                party_manager=self.party_manager,
                character_manager=self.character_manager,
                send_callback_factory=self._get_discord_send_callback,
                # Add other necessary dependencies for PartyActionProcessor
                location_manager=self.location_manager,
                time_manager=self.time_manager,
                game_log_manager=self.game_log_manager
            )
            logger.info("GameManager: PartyActionProcessor initialized.")

        if not hasattr(self, '_party_command_handler') or not self._party_command_handler:
            self._party_command_handler = PartyCommandHandler(
                character_manager=self.character_manager,
                party_manager=self.party_manager,
                party_action_processor=self._party_action_processor,
                settings=self._settings,
                npc_manager=self.npc_manager
            )
            logger.info("GameManager: PartyCommandHandler initialized.")

        # Initialize EventStageProcessor and EventActionProcessor if they haven't been already
        # These are dependencies for CharacterActionProcessor
        if not hasattr(self, '_event_stage_processor') or self._event_stage_processor is None:
            # from bot.game.event_processors.event_stage_processor import EventStageProcessor # Already imported
            self._event_stage_processor = EventStageProcessor(
                on_enter_action_executor=self._on_enter_action_executor, # Now initialized
                stage_description_generator=self._stage_description_generator, # Now initialized
                rule_engine=self.rule_engine,
                character_manager=self.character_manager,
                loc_manager=self.location_manager, # Alias for location_manager
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager,
                dialogue_manager=self.dialogue_manager, # Now initialized
                # economy_manager=self.economy_manager, # Optional, pass if available
                # crafting_manager=self.crafting_manager, # Optional, pass if available
                event_action_processor=None # Pass None initially to avoid circular dependency with EventActionProcessor. EventStageProcessor lists it as Optional.
            )
            logger.info("GameManager: EventStageProcessor correctly initialized.")


        if not hasattr(self, '_event_action_processor') or self._event_action_processor is None:
            # from bot.game.event_processors.event_action_processor import EventActionProcessor # Already imported
            self._event_action_processor = EventActionProcessor(
                event_stage_processor=self._event_stage_processor, # Now correctly initialized
                event_manager=self.event_manager,
                character_manager=self.character_manager,
                loc_manager=self.location_manager, # Pass location_manager as loc_manager
                rule_engine=self.rule_engine,
                openai_service=self.openai_service, # Is Optional in EAP's init
                send_callback_factory=self._get_discord_send_callback,

                # Optional managers accepted by EventActionProcessor
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager,
                dialogue_manager=self.dialogue_manager, # Now initialized
                # economy_manager=self.economy_manager, # Pass if available
                # crafting_manager=self.crafting_manager, # Pass if available
                on_enter_action_executor=self._on_enter_action_executor, # Pass if EAP uses it
                stage_description_generator=self._stage_description_generator, # Pass if EAP uses it
                character_action_processor=self._character_action_processor # Pass if EAP uses it
            )
            logger.info("GameManager: EventActionProcessor correctly initialized.")

        # PersistenceManager initialization
        if not hasattr(self, '_persistence_manager') or not self._persistence_manager:
            # from bot.game.managers.persistence_manager import PersistenceManager # Already imported
            self._persistence_manager = PersistenceManager(
                event_manager=self.event_manager,
                character_manager=self.character_manager,
                location_manager=self.location_manager,
                db_service=self.db_service,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager,
                quest_manager=self.quest_manager,
                game_log_manager=self.game_log_manager
                # Other optional managers like dialogue, relationship, skill, spell, crafting, economy
                # will be omitted for now as their initialization order relative to PersistenceManager
                # is less clear or they might not be strictly required for its core functions.
                # PersistenceManager is designed to handle None for these.
            )
            logger.info("GameManager: PersistenceManager initialized in _initialize_processors_and_command_system.")

        if not hasattr(self, '_world_simulation_processor') or self._world_simulation_processor is None:
            # from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor # Already imported at top of method

            # Ensure all WSP dependencies that are managers are explicitly available
            # For example, RelationshipManager might not be initialized yet.
            # For now, we assume managers like RelationshipManager are either initialized
            # before this point or WSP can handle them being None if passed as optional.
            # The WSP __init__ signature lists many as Optional.

            self._world_simulation_processor = WorldSimulationProcessor(
                # Mandatory arguments from WSP's __init__
                event_manager=self.event_manager,
                character_manager=self.character_manager,
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                openai_service=self.openai_service,
                event_stage_processor=self._event_stage_processor,
                event_action_processor=self._event_action_processor,
                persistence_manager=self._persistence_manager, # This is initialized just before CommandRouter in the original problematic code
                settings=self._settings,
                send_callback_factory=self._get_discord_send_callback,
                character_action_processor=self._character_action_processor,
                party_action_processor=self._party_action_processor,

                # Optional arguments for WSP, provide if available and initialized
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                item_manager=self.item_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                crafting_manager=self.crafting_manager, # Assuming it's initialized or WSP handles None
                economy_manager=self.economy_manager,   # Assuming it's initialized or WSP handles None
                party_manager=self.party_manager,
                dialogue_manager=self.dialogue_manager, # Now initialized
                quest_manager=self.quest_manager,       # Now initialized
                relationship_manager=self.relationship_manager, # Assuming it's initialized or WSP handles None
                game_log_manager=self.game_log_manager,
                multilingual_prompt_generator=self.multilingual_prompt_generator # This is on GameManager, pass if available
            )
            logger.info("GameManager: WorldSimulationProcessor initialized.")

        # CommandRouter is typically one of the last things in this setup phase
        if not hasattr(self, '_command_router') or self._command_router is None:
            # from bot.game.command_router import CommandRouter # Already imported at top of method
            self._command_router = CommandRouter(
                # Mandatory arguments based on TypeError and __init__ signature
                character_manager=self.character_manager,
                event_manager=self.event_manager,
                persistence_manager=self._persistence_manager,
                settings=self._settings,
                world_simulation_processor=self._world_simulation_processor, # Now initialized
                send_callback_factory=self._get_discord_send_callback,
                character_action_processor=self._character_action_processor,
                character_view_service=self._character_view_service,
                location_manager=self.location_manager,
                rule_engine=self.rule_engine,
                party_command_handler=self._party_command_handler,

                # Optional arguments for CommandRouter, provide if available
                openai_service=self.openai_service,
                item_manager=self.item_manager,
                npc_manager=self.npc_manager,
                combat_manager=self.combat_manager,
                time_manager=self.time_manager,
                status_manager=self.status_manager,
                party_manager=self.party_manager,
                crafting_manager=self.crafting_manager, # If available, else CommandRouter should handle None
                economy_manager=self.economy_manager,   # If available, else CommandRouter should handle None
                party_action_processor=self._party_action_processor,
                event_action_processor=self._event_action_processor, # Now initialized
                event_stage_processor=self._event_stage_processor, # Now initialized
                quest_manager=self.quest_manager,
                dialogue_manager=self.dialogue_manager, # Now initialized
                # campaign_loader=self.campaign_loader, # GameManager.campaign_loader is type CampaignLoader, CommandRouter expects CampaignLoaderService. This might be an issue or handled by CommandRouter if it's a subtype or duck-typed. Pass for now.
                campaign_loader=self.campaign_loader, # Using self.campaign_loader directly as per subtask note.
                relationship_manager=self.relationship_manager, # If available, else CommandRouter should handle None
                game_log_manager=self.game_log_manager,
                conflict_resolver=self.conflict_resolver, # If available, else CommandRouter should handle None
                game_manager=self, # Explicitly passing self as game_manager
                ai_validator=getattr(self, 'ai_validator', None) # Pass if GameManager has an ai_validator attribute
            )
            logger.info("GameManager: CommandRouter initialized.")


        logger.info("GameManager: Processors and command system initialized.")

    async def _load_initial_data_and_state(self):
        logger.info("GameManager: Loading initial game data and state...") # Changed
        if self.campaign_loader:
            if self._active_guild_ids:
                for guild_id_str in self._active_guild_ids:
                    logger.info("GameManager: Populating game data for guild %s.", guild_id_str) # Added
                    await self.campaign_loader.populate_all_game_data(guild_id=guild_id_str, campaign_identifier=None)
            else:
                logger.warning("GameManager: No active guilds specified. Item template loading will be skipped as item templates require a guild_id due to schema constraints.")

        if self._persistence_manager:
            # ... (load_context_kwargs setup)
            load_context_kwargs = { # Re-defined for safety
                # ... (all managers and services)
                 'undo_manager': self.undo_manager # Added undo_manager
            }
            load_context_kwargs.update({'send_callback_factory': self._get_discord_send_callback, 'settings': self._settings, 'discord_client': self._discord_client})
            await self._persistence_manager.load_game_state(guild_ids=self._active_guild_ids, **load_context_kwargs)
        logger.info("GameManager: Initial data and game state loaded.") # Changed

    async def _initialize_ai_content_services(self):
        logger.info("GameManager: Initializing AI content generation services...") # Changed
        # ... (AI services initialization, replace print with logger.warning if needed)
        if not self.prompt_context_collector or not self.multilingual_prompt_generator:
            logger.warning("GameManager: AI prompt services not fully inited due to missing managers.") # Changed
        logger.info("GameManager: AI content services initialized.") # Changed

    async def _start_background_tasks(self):
        logger.info("GameManager: Starting background tasks...") # Changed
        if self._world_simulation_processor:
            self._world_tick_task = asyncio.create_task(self._world_tick_loop())
            logger.info("GameManager: World tick loop started.") # Changed
        else: logger.warning("GameManager: World tick loop not started, WSP unavailable.") # Changed
        logger.info("GameManager: Background tasks started.") # Changed

    async def setup(self) -> None:
        logger.info("GameManager: Running setup…") # Changed
        try:
            await self._initialize_database()
            await self._initialize_core_managers_and_services()
            await self._initialize_dependent_managers()
            await self._initialize_processors_and_command_system()
            await self._load_initial_data_and_state()
            await self._initialize_ai_content_services()
            await self._start_background_tasks()
            logger.info("GameManager: Setup complete.") # Changed
        except Exception as e:
            is_db_connection_error = isinstance(e, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError)) or \
                                     (hasattr(e, '__cause__') and isinstance(e.__cause__, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError)))
            if is_db_connection_error:
                logger.critical("\n" + "="*80 + "\nGameManager: CRITICAL: Failed to establish database connection.\n" +
                               "The bot cannot start without a valid database connection.\n" +
                               "Please check the database server status and the `DATABASE_URL` environment variable.\n" +
                               f"Specific error details: {e}\n" + "="*80 + "\n", exc_info=True) # Changed
            else:
                logger.critical("GameManager: CRITICAL ERROR during setup: %s", e, exc_info=True) # Changed
            try:
                logger.info("GameManager: Attempting graceful shutdown due to setup failure...") # Changed
                await self.shutdown()
            except Exception as shutdown_e:
                logger.error("GameManager: Error during shutdown from setup failure: %s", shutdown_e, exc_info=True) # Changed
            raise

    async def handle_discord_message(self, message: "Message") -> None:
        if message.author.bot: return
        if not self._command_router:
            logger.warning("GameManager: CommandRouter not available, message '%s' from guild %s dropped.", message.content, message.guild.id if message.guild else "DM") # Changed
            if message.channel:
                try:
                     send_callback = self._get_discord_send_callback(message.channel.id)
                     await send_callback(f"❌ Игра еще не полностью запущена. Попробуйте позже.", None)
                except Exception as cb_e:
                     logger.error("GameManager: Error sending startup error message to channel %s: %s", message.channel.id, cb_e, exc_info=True) # Changed
            return

        command_prefix = self._settings.get('command_prefix', '/')
        if message.content.startswith(command_prefix):
             logger.info("GameManager: Passing command from %s (ID: %s, Guild: %s, Channel: %s) to CommandRouter: '%s'", message.author.name, message.author.id, message.guild.id if message.guild else 'DM', message.channel.id, message.content) # Changed
        # else: # No need to log non-command messages unless for debug
        #      logger.debug("GameManager: Non-command message from %s: '%s'", message.author.name, message.content)

        try:
            await self._command_router.route(message)
        except Exception as e:
            logger.error("GameManager: Error handling message '%s' from guild %s: %s", message.content, message.guild.id if message.guild else "DM", e, exc_info=True) # Changed
            try:
                 if message.channel:
                      send_callback = self._get_discord_send_callback(message.channel.id)
                      await send_callback(f"❌ Произошла внутренняя ошибка при обработке команды. Подробности в логах бота.", None)
                 else:
                      logger.warning("GameManager: Cannot send error message to user (DM channel or channel not found).") # Changed
            except Exception as cb_e:
                 logger.error("GameManager: Error sending generic internal error message to channel %s: %s", message.channel.id, cb_e, exc_info=True) # Changed

    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback:
        channel_id_int = int(channel_id)
        async def _send(content: str = "", **kwargs: Any) -> None:
            channel = self._discord_client.get_channel(channel_id_int)
            if channel and isinstance(channel, discord.abc.Messageable):
                try: await channel.send(content, **kwargs)
                except Exception as e:
                    logger.error("GameManager: Error sending message to channel %s: %s", channel_id_int, e, exc_info=True) # Changed
            elif not channel: logger.warning("GameManager: Channel %s not found in Discord client cache. Cannot send message. Content: '%s'", channel_id_int, content[:50]) # Changed
            else: logger.warning("GameManager: Channel %s is not Messageable (type: %s). Content: '%s'", channel_id_int, type(channel), content[:50]) # Changed
        return _send

    async def _process_player_turns_for_tick(self, guild_id_str: str) -> None:
        if not self.turn_processing_service or not self.character_manager:
            if not self.turn_processing_service: logger.warning("GameManager (Tick-%s): TurnProcessingService not available.", guild_id_str) # Changed
            if not self.character_manager: logger.warning("GameManager (Tick-%s): CharacterManager not available.", guild_id_str) # Changed
            logger.warning("GameManager (Tick-%s): Skipping player turn processing phase for this guild.", guild_id_str) # Changed
            return
        try:
            all_chars_in_guild = self.character_manager.get_all_characters(guild_id_str)
            players_with_actions = [char.id for char_obj in all_chars_in_guild if (char := char_obj) and char.collected_actions_json] # Python 3.8+ walrus
            if players_with_actions:
                logger.info("GameManager (Tick-%s): Found %s players with actions. Processing turns...", guild_id_str, len(players_with_actions)) # Changed
                # ... (rest of turn processing logic, ensure guild_id_str is in logs) ...
                # Example: logger.info("GameManager (Tick-%s Feedback for %s): %s", guild_id_str, p_id, feedback_summary)
                # Example: logger.error("GameManager (Tick-%s): Error sending DM feedback to character %s: %s", guild_id_str, p_id, dm_e, exc_info=True)
            # else: logger.debug("GameManager (Tick-%s): No players with pending actions found for turn processing.", guild_id_str) # Too noisy for info
        except Exception as tps_e:
            logger.error("GameManager (Tick-%s): Error during TurnProcessingService call or subsequent handling: %s", guild_id_str, tps_e, exc_info=True) # Changed

    async def _world_tick_loop(self) -> None:
        logger.info("GameManager: Starting world tick loop with interval %.2f seconds.", self._tick_interval_seconds) # Changed
        try:
            while True:
                await asyncio.sleep(self._tick_interval_seconds)
                logger.debug("GameManager: World tick executing...") # Added
                if self._world_simulation_processor:
                    try:
                        # ... (tick_context_kwargs setup as before)
                        tick_context_kwargs: Dict[str, Any] = { # Re-defined for safety
                            # ... (all managers and services)
                        }
                        await self._world_simulation_processor.process_world_tick(game_time_delta=self._tick_interval_seconds, **tick_context_kwargs)
                    except Exception as e:
                        logger.error("GameManager: Error during world simulation tick: %s", e, exc_info=True) # Changed
                for guild_id_str in self._active_guild_ids:
                    await self._process_player_turns_for_tick(guild_id_str)
                logger.debug("GameManager: World tick completed.") # Added
        except asyncio.CancelledError:
            logger.info("GameManager: World tick loop cancelled.") # Changed
        except Exception as e:
            logger.critical("GameManager: Critical error in world tick loop: %s", e, exc_info=True) # Changed

    async def save_game_state_after_action(self, guild_id: str) -> None:
        if not self._persistence_manager:
            logger.warning("GameManager: PersistenceManager not available. Cannot save game state for guild %s after action.", guild_id) # Changed
            return
        logger.info("GameManager: Saving game state for guild %s after action...", guild_id) # Changed
        try:
            # ... (save_context_kwargs setup as before)
            save_context_kwargs: Dict[str, Any] = { # Re-defined for safety
                # ... (all managers and services)
            }
            await self._persistence_manager.save_game_state(guild_ids=[str(guild_id)], **save_context_kwargs)
            logger.info("GameManager: Game state saved successfully for guild %s after action.", guild_id) # Changed
        except Exception as e:
            logger.error("GameManager: Error saving game state for guild %s after action: %s", guild_id, e, exc_info=True) # Changed

    async def shutdown(self) -> None:
        logger.info("GameManager: Running shutdown...") # Changed
        if self._world_tick_task:
            logger.info("GameManager: Cancelling world tick loop...") # Changed
            self._world_tick_task.cancel()
            try:
                await asyncio.wait_for(self._world_tick_task, timeout=5.0)
                logger.info("GameManager: World tick loop task finished.") # Changed
            except asyncio.CancelledError: logger.info("GameManager: World tick loop task confirmed cancelled.") # Changed
            except asyncio.TimeoutError: logger.warning("GameManager: Timeout waiting for world tick task to cancel.") # Changed
            except Exception as e: logger.error("GameManager: Error waiting for world tick task to complete after cancel: %s", e, exc_info=True) # Changed

        if self._persistence_manager:
            try:
                logger.info("GameManager: Saving game state on shutdown...") # Changed
                # ... (save_context_kwargs setup as before)
                save_context_kwargs: Dict[str, Any] = { # Re-defined for safety
                    # ... (all managers and services)
                }
                if self.db_service:
                    await self._persistence_manager.save_game_state(guild_ids=self._active_guild_ids, **save_context_kwargs)
                    logger.info("GameManager: Game state saved on shutdown.") # Changed
                else: logger.warning("GameManager: Skipping state save on shutdown, DB service is None.") # Changed
            except Exception as e:
                logger.error("GameManager: Error saving game state on shutdown: %s", e, exc_info=True) # Changed

        if self.db_service:
            try:
                await self.db_service.close()
                logger.info("GameManager: Database connection closed.") # Changed
            except Exception as e:
                logger.error("GameManager: Error closing database service: %s", e, exc_info=True) # Changed
        logger.info("GameManager: Shutdown complete.") # Changed

    async def get_player_by_discord_id(self, discord_id: int, guild_id: str) -> Optional[Character]:
        if not self.character_manager:
            logger.warning("GameManager: CharacterManager not available. Cannot get player by Discord ID %s in guild %s.", discord_id, guild_id) # Changed
            return None
        try:
            player_obj_from_cm = self.character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_id)
            if player_obj_from_cm and not isinstance(player_obj_from_cm, Character):
                logger.warning("GameManager: CharacterManager.get_character_by_discord_id returned type %s instead of Character or None for discord_id %s in guild %s.", type(player_obj_from_cm), discord_id, guild_id) # Changed
            return player_obj_from_cm
        except Exception as e:
            logger.error("GameManager: Error calling get_character_by_discord_id for discord_id %s in guild %s: %s", discord_id, guild_id, e, exc_info=True) # Changed
            return None

    def get_default_bot_language(self) -> str:
        if self._rules_config_cache is None:
            logger.warning("GameManager: RulesConfig cache is not populated. Defaulting bot language to 'en'.") # Changed
            return "en"
        return self._rules_config_cache.get('default_bot_language', 'en')

    def get_max_party_size(self) -> int:
        default_size = 4
        if self._rules_config_cache is None:
            logger.warning("GameManager: RulesConfig cache not populated. Defaulting max_party_size to %s.", default_size) # Changed
            return default_size
        party_rules = self._rules_config_cache.get('party_rules')
        if not isinstance(party_rules, dict):
            logger.warning("GameManager: 'party_rules' not found or not a dict in RulesConfig. Defaulting max_party_size to %s.", default_size) # Changed
            return default_size
        max_size = party_rules.get('max_size')
        if not isinstance(max_size, int):
            logger.warning("GameManager: 'max_size' not found or not an int in party_rules. Defaulting max_party_size to %s.", default_size) # Changed
            return default_size
        return max_size

    def get_action_cooldown(self, action_type: str) -> float:
        default_cooldown = 5.0
        if self._rules_config_cache is None:
            logger.warning("GameManager: RulesConfig cache not populated. Defaulting cooldown for '%s' to %.1fs.", action_type, default_cooldown) # Changed
            return default_cooldown
        cooldown_rules = self._rules_config_cache.get('action_rules', {}).get('cooldowns')
        if not isinstance(cooldown_rules, dict):
            logger.warning("GameManager: 'action_rules.cooldowns' not found or not a dict in RulesConfig. Defaulting cooldown for '%s' to %.1fs.", action_type, default_cooldown) # Changed
            return default_cooldown
        cooldown = cooldown_rules.get(action_type)
        if not isinstance(cooldown, (float, int)):
            logger.warning("GameManager: Cooldown for '%s' not found or not a number in action_rules.cooldowns. Defaulting to %.1fs.", action_type, default_cooldown) # Changed
            return default_cooldown
        return float(cooldown)

    def get_game_channel_ids(self, guild_id: str) -> List[int]:
        if not self.location_manager:
            logger.warning("GameManager: LocationManager not available. Cannot get game channel IDs for guild %s.", guild_id) # Changed
            return []
        guild_id_str = str(guild_id)
        try:
            if hasattr(self.location_manager, 'get_active_channel_ids_for_guild'):
                channel_ids = self.location_manager.get_active_channel_ids_for_guild(guild_id_str)
                if not isinstance(channel_ids, list):
                    logger.warning("GameManager: get_active_channel_ids_for_guild for guild %s did not return a list. Got %s. Returning empty list.", guild_id_str, type(channel_ids)) # Changed
                    return []
                valid_channel_ids = [cid for cid in channel_ids if isinstance(cid, int)] # Filter non-int IDs
                if len(valid_channel_ids) != len(channel_ids):
                    logger.warning("GameManager: LocationManager returned non-integer channel IDs for guild %s. Filtered list: %s", guild_id_str, valid_channel_ids) # Added
                return valid_channel_ids
            else:
                logger.error("GameManager: LocationManager is missing 'get_active_channel_ids_for_guild' method. Cannot get game channel IDs for guild %s.", guild_id_str) # Changed
                return []
        except Exception as e:
            logger.error("GameManager: Error calling get_active_channel_ids_for_guild for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
            return []

    async def set_default_bot_language(self, language: str, guild_id: Optional[str] = None) -> bool:
        if guild_id: # Guild-specific language setting is not supported by this global config
            logger.warning("GameManager (set_default_bot_language): Received guild_id '%s', but rules_config for language is currently global. Change will affect all guilds.", guild_id) # Changed
        if self._rules_config_cache is None:
            logger.error("GameManager: RulesConfig cache is not populated. Cannot set default bot language.") # Changed
            return False
        if not self.db_service:
            logger.error("GameManager: DBService not available. Cannot save default bot language.") # Changed
            return False

        original_language = self._rules_config_cache.get('default_bot_language')
        self._rules_config_cache['default_bot_language'] = language
        try:
            success = await self.db_service.update_entity('rules_config', DEFAULT_RULES_CONFIG_ID, {'config_data': json.dumps(self._rules_config_cache)})
            if success:
                logger.info("GameManager: Default bot language successfully updated to '%s' and saved.", language) # Changed
                if self.multilingual_prompt_generator:
                    self.multilingual_prompt_generator.update_main_bot_language(language)
                    logger.info("GameManager: Updated main_bot_language in MultilingualPromptGenerator.") # Changed
                return True
            else:
                logger.error("GameManager: Failed to save default bot language update to database. Reverting cache.") # Changed
                if original_language is not None: self._rules_config_cache['default_bot_language'] = original_language
                elif 'default_bot_language' in self._rules_config_cache and language == self._rules_config_cache['default_bot_language']: del self._rules_config_cache['default_bot_language']
                return False
        except Exception as e:
            logger.error("GameManager: Exception while saving default bot language: %s. Reverting cache.", e, exc_info=True) # Changed
            if original_language is not None: self._rules_config_cache['default_bot_language'] = original_language
            elif 'default_bot_language' in self._rules_config_cache and language == self._rules_config_cache['default_bot_language']: del self._rules_config_cache['default_bot_language']
            return False

    async def trigger_manual_simulation_tick(self, server_id: int) -> None: # server_id is likely guild_id
        guild_id_str = str(server_id)
        logger.info("GameManager: Manual simulation tick triggered for guild_id: %s.", guild_id_str) # Changed

        if not self._world_simulation_processor:
            logger.warning("GameManager: WorldSimulationProcessor not available. Cannot trigger manual tick for guild %s.", guild_id_str) # Changed
            return

        game_time_delta = 0.0 # Manual tick usually implies immediate or minimal time progression
        logger.info("GameManager: Using game_time_delta: %.2f for manual tick in guild %s.", game_time_delta, guild_id_str) # Changed

        try:
            tick_context_kwargs: Dict[str, Any] = { # Re-defined for safety
                # ... (all managers and services)
            }
            logger.info("GameManager: Executing manual process_world_tick for guild_id: %s...", guild_id_str) # Changed
            await self._world_simulation_processor.process_world_tick(game_time_delta=game_time_delta, **tick_context_kwargs)
            logger.info("GameManager: Manual simulation tick completed for guild_id: %s.", guild_id_str) # Changed
        except Exception as e:
            logger.error("GameManager: Error during manual simulation tick for guild_id %s: %s", guild_id_str, e, exc_info=True) # Changed

    async def start_new_character_session(self, user_id: int, guild_id: str, character_name: str) -> Optional["Character"]:
        logger.info("GameManager: Attempting to start new character session for user %s in guild %s with name %s.", user_id, guild_id, character_name) # Changed
        if not self.character_manager:
            logger.error("GameManager: CharacterManager not available. Cannot start new character session for user %s in guild %s.", user_id, guild_id) # Changed
            return None
        try:
            character = await self.character_manager.create_character(discord_id=user_id, name=character_name, guild_id=guild_id)
            if character:
                char_id_log = getattr(character, 'id', "N/A"); char_name_log = getattr(character, 'name', "N/A")
                char_loc_id_log = getattr(character, 'current_location_id', "N/A") # Adjusted attribute
                logger.info("GameManager: Successfully started new character session for guild %s. Character ID: %s, Name: %s, Location ID: %s.", guild_id, char_id_log, char_name_log, char_loc_id_log) # Changed
            else:
                logger.error("GameManager: Failed to start new character session for user %s in guild %s, character creation failed.", user_id, guild_id) # Changed
            return character
        except Exception as e:
            logger.error("GameManager: Error in start_new_character_session for user %s in guild %s: %s", user_id, guild_id, e, exc_info=True) # Changed
            return None

logger.debug("DEBUG: Finished loading game_manager.py from: %s", __file__) # Changed
