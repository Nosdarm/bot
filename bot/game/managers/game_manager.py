# bot/game/managers/game_manager.py

import asyncio
import json
import traceback # Will be removed
import os
import io
import logging # Added
import uuid # Added for quest generation
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
from bot.database.models import RulesConfig, Player, PendingGeneration, GuildConfig, Location, QuestTable, QuestStepTable # Added QuestTable, QuestStepTable
from bot.services.notification_service import NotificationService # Added runtime import
from bot.game.managers.character_manager import CharacterManager, CharacterAlreadyExistsError
from bot.ai.ai_response_validator import parse_and_validate_ai_response # Added

if TYPE_CHECKING:
    from discord import Message
    # from bot.game.models.character import Character # Already imported
    # from bot.game.managers.character_manager import CharacterManager, CharacterAlreadyExistsError # Moved to global
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
    from bot.ai.ai_response_validator import AIResponseValidator # Added import
    from bot.services.notification_service import NotificationService
    from bot.game.turn_processing_service import TurnProcessingService
    from bot.game.turn_processor import TurnProcessor # Added for TurnProcessor integration
    from bot.game.rules.check_resolver import CheckResolver # Added for CheckResolver integration
    from bot.game.managers.faction_manager import FactionManager # Added for FactionManager integration
    from bot.game.managers.quest_manager import QuestManager # Ensured direct import for runtime
    from bot.game.services.location_interaction_service import LocationInteractionService # For Part 2

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
        self.ai_response_validator: Optional[AIResponseValidator] = None # Added attribute
        self.turn_processor: Optional[TurnProcessor] = None # Added for TurnProcessor
        self.check_resolver: Optional[CheckResolver] = None # Added for CheckResolver
        self.faction_manager: Optional[FactionManager] = None # Added for FactionManager
        self.location_interaction_service: Optional[LocationInteractionService] = None # For Part 2
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

    async def _load_or_initialize_rules_config(self, guild_id: str):
        logger.info(f"GameManager: Loading or initializing rules configuration for guild_id: {guild_id}...")
        # Initialize cache for this guild if it doesn't exist
        if self._rules_config_cache is None:
            self._rules_config_cache = {}

        # Ensure guild-specific cache exists
        if guild_id not in self._rules_config_cache:
            self._rules_config_cache[guild_id] = {}

        if not self.db_service:
            logger.error(f"GameManager: DBService not available for loading rules config for guild {guild_id}.")
            # Use fallback defaults for this specific guild's cache
            self._rules_config_cache[guild_id] = {
                "default_bot_language": "en",
                "experience_rate": 1.0,
                "loot_drop_chance": 0.5,
                "max_party_size": 4,
                "action_cooldown_seconds": 30,
                "error_state": "DBService unavailable"
            }
            logger.warning(f"GameManager: Used fallback default rules for guild {guild_id} due to DBService unavailability.")
            return

        try:
            # Fetch all RulesConfig entries for the guild
            rules_entries = await self.db_service.get_entities_by_conditions(
                table_name='rules_config',
                conditions={'guild_id': guild_id}
            )

            if rules_entries:
                guild_rules_dict = {}
                for entry in rules_entries:
                    if 'key' in entry and 'value' in entry:
                        guild_rules_dict[entry['key']] = entry['value']
                    else:
                        logger.warning(f"GameManager: Rule entry for guild {guild_id} is missing 'key' or 'value': {entry}")

                if guild_rules_dict:
                    self._rules_config_cache[guild_id] = guild_rules_dict
                    logger.info(f"GameManager: Successfully loaded {len(guild_rules_dict)} rules from DB for guild {guild_id}.")
                else:
                    logger.info(f"GameManager: No valid rule entries found in DB for guild {guild_id} after filtering. Will attempt initialization.")
                    # Proceed to initialization logic below
            else:
                logger.info(f"GameManager: No rules found in DB for guild {guild_id}. Attempting to initialize default rules...")
                # Fall through to initialization logic if no rules are found

            # If cache for guild is still empty (either no rules found or they were invalid), initialize them.
            if not self._rules_config_cache.get(guild_id):
                from bot.game.guild_initializer import initialize_new_guild # Local import
                logger.info(f"GameManager: Calling guild_initializer for guild {guild_id} as no rules were loaded.")
                async with self.db_service.get_session() as session: # type: ignore
                    success = await initialize_new_guild(session, guild_id)
                    if success:
                        logger.info(f"GameManager: Default rules initialized by guild_initializer for guild {guild_id}. Reloading...")
                        # Reload after initialization
                        # Fetch again as initialize_new_guild would have added them
                        rules_entries_after_init = await self.db_service.get_entities_by_conditions(
                            table_name='rules_config',
                            conditions={'guild_id': guild_id}
                        )
                        reloaded_rules_dict = {}
                        for entry in rules_entries_after_init:
                            if 'key' in entry and 'value' in entry:
                                reloaded_rules_dict[entry['key']] = entry['value']
                        if reloaded_rules_dict:
                            self._rules_config_cache[guild_id] = reloaded_rules_dict
                            logger.info(f"GameManager: Successfully reloaded {len(reloaded_rules_dict)} rules after initialization for guild {guild_id}.")
                        else:
                            logger.error(f"GameManager: Failed to reload rules for guild {guild_id} after initialization. Cache may be empty.")
                            # Populate with minimal emergency defaults if reload fails
                            self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": "Failed reload after init"}
                    else:
                        logger.error(f"GameManager: guild_initializer failed for guild {guild_id}. Rules cache will be empty or fallback.")
                        # Populate with minimal emergency defaults if init fails
                        self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": "Guild initializer failed"}

        except Exception as e:
            logger.error(f"GameManager: Unexpected error loading/initializing rules_config for guild {guild_id}: {e}", exc_info=True)
            # Populate with minimal emergency defaults in case of other errors
            self._rules_config_cache[guild_id] = {
                "default_bot_language": "en",
                "emergency_mode": True,
                "reason": f"Exception: {str(e)}"
            }

        # Final check for this guild's cache
        if not self._rules_config_cache.get(guild_id):
            logger.critical(f"GameManager: CRITICAL - Rules cache for guild {guild_id} is still empty after all attempts. Using emergency fallback.")
            self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": "Final fallback"}

    async def get_rule(self, guild_id: str, key: str, default: Any = None) -> Any:
        """
        Retrieves a rule value for a given guild and key from the cache.
        Loads the cache for the guild if it's not already populated.
        """
        if self._rules_config_cache is None or guild_id not in self._rules_config_cache:
            logger.info(f"GameManager.get_rule: Cache miss for guild {guild_id}. Loading rules config.")
            await self._load_or_initialize_rules_config(guild_id)

        # After loading, check again
        if self._rules_config_cache is None or guild_id not in self._rules_config_cache:
            logger.warning(f"GameManager.get_rule: Rules config still not available for guild {guild_id} after load attempt. Returning default for key '{key}'.")
            return default

        guild_cache = self._rules_config_cache.get(guild_id, {})
        value = guild_cache.get(key, default)

        if value is default and key not in guild_cache:
            logger.info(f"GameManager.get_rule: Key '{key}' not found for guild {guild_id}. Returned default value: {default}.")
        else:
            logger.debug(f"GameManager.get_rule: Key '{key}' for guild {guild_id} retrieved. Value: {value}.")
        return value

    async def update_rule_config(self, guild_id: str, key: str, value: Any) -> bool:
        """
        Updates a rule in the cache and database for a given guild.
        """
        logger.info(f"GameManager.update_rule_config: Attempting to update rule '{key}' to '{value}' for guild {guild_id}.")
        if self._rules_config_cache is None or guild_id not in self._rules_config_cache:
            logger.info(f"GameManager.update_rule_config: Cache for guild {guild_id} not populated. Loading before update.")
            await self._load_or_initialize_rules_config(guild_id)
            if self._rules_config_cache is None or guild_id not in self._rules_config_cache:
                logger.error(f"GameManager.update_rule_config: Failed to load rules config for guild {guild_id}. Cannot update rule '{key}'.")
                return False

        if not self.db_service:
            logger.error(f"GameManager.update_rule_config: DBService not available. Cannot update rule '{key}' for guild {guild_id}.")
            return False

        guild_cache = self._rules_config_cache.get(guild_id, {})
        original_value = guild_cache.get(key) # Could be None if key didn't exist

        # Update cache first
        guild_cache[key] = value
        # Ensure the guild_cache (which is a reference to self._rules_config_cache[guild_id]) is updated in the main cache
        self._rules_config_cache[guild_id] = guild_cache

        async with self.db_service.get_session() as session:
            try:
                from bot.database.models import RulesConfig # Local import for model
                from sqlalchemy.future import select

                stmt = select(RulesConfig).where(RulesConfig.guild_id == guild_id, RulesConfig.key == key)
                result = await session.execute(stmt)
                existing_rule = result.scalars().first()

                if existing_rule:
                    existing_rule.value = value
                    session.add(existing_rule)
                    logger.info(f"GameManager.update_rule_config: Updating existing rule '{key}' for guild {guild_id} in DB.")
                else:
                    new_rule = RulesConfig(guild_id=guild_id, key=key, value=value)
                    session.add(new_rule)
                    logger.info(f"GameManager.update_rule_config: Creating new rule '{key}' for guild {guild_id} in DB.")

                await session.commit()
                logger.info(f"GameManager.update_rule_config: Rule '{key}' successfully updated to '{value}' for guild {guild_id} in cache and DB.")
                return True
            except Exception as e:
                logger.error(f"GameManager.update_rule_config: DB error updating rule '{key}' for guild {guild_id}: {e}", exc_info=True)
                await session.rollback()
                # Revert cache change
                if original_value is not None:
                    guild_cache[key] = original_value
                else: # Key did not exist before
                    if key in guild_cache:
                        del guild_cache[key]
                self._rules_config_cache[guild_id] = guild_cache # Ensure main cache is updated with reverted guild_cache
                logger.info(f"GameManager.update_rule_config: Reverted cache for rule '{key}' for guild {guild_id} due to DB error.")
                return False

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

        # Rules config needs to be loaded per guild.
        # This is problematic here as this method is not guild-specific.
        # For now, let's assume a global or first-guild load for RuleEngine.
        # This part will need significant refactoring if RuleEngine itself becomes guild-aware.
        # Option 1: Load for all active guilds.
        # Option 2: Postpone RuleEngine init or make it load rules on demand.
        # For this step, we'll load for the first active guild if available,
        # otherwise, RuleEngine might get an empty or None rules_data.
        # This is a temporary measure.
        if self._active_guild_ids:
            first_guild_id = self._active_guild_ids[0]
            await self._load_or_initialize_rules_config(first_guild_id)
            # RuleEngine expects a single dict, not a dict of dicts.
            # This means RuleEngine currently can't support per-guild rules directly
            # unless it's refactored or we pass only one guild's rules.
            # Passing the first guild's rules as a temporary measure.
            rules_data_for_engine = self._rules_config_cache.get(first_guild_id, {}) if self._rules_config_cache else {}
        else:
            logger.warning("GameManager: No active guild IDs found. RuleEngine will be initialized with empty rules.")
            # Initialize an empty structure for the first guild to prevent KeyErrors if _load_or_initialize_rules_config was skipped
            # This is a placeholder for a more robust solution for non-guild specific contexts or a default global ruleset.
            # For now, we ensure _rules_config_cache is not None before trying to get a non-existent guild's rules.
            if self._rules_config_cache is None: self._rules_config_cache = {}
            self._rules_config_cache["__global_fallback__"] = {"default_bot_language": "en", "emergency_mode": True, "reason": "No active guilds for RuleEngine init"}
            rules_data_for_engine = self._rules_config_cache["__global_fallback__"]


        self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}), rules_data=rules_data_for_engine)
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

        self.faction_manager = FactionManager(game_manager=self)
        logger.info("GameManager: FactionManager initialized.")

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
        from bot.game.managers.quest_manager import QuestManager # Ensure runtime import
        from bot.game.managers.relationship_manager import RelationshipManager
        # DialogueManager already imported (or should be) if it's a dependency for others here
        # GameLogManager already initialized in _initialize_dependent_managers
        from bot.game.managers.ability_manager import AbilityManager
        from bot.game.managers.spell_manager import SpellManager
        from bot.game.conflict_resolver import ConflictResolver
        # TurnProcessingService already imported
        # TurnProcessor is imported at the top of the file.

        # Initialize managers that might not have been initialized yet or are specific to this stage
        # Initialize QuestManager with its full dependency list
        if not hasattr(self, 'quest_manager') or self.quest_manager is None:
            # Ensure dependencies for QuestManager's internal ConsequenceProcessor are met first
            # RelationshipManager is needed by DialogueManager which might be used by ConsequenceProcessor
            if not hasattr(self, 'relationship_manager') or self.relationship_manager is None:
                self.relationship_manager = RelationshipManager(db_service=self.db_service, settings=self._settings.get('relationship_settings', {}))
                logger.info("GameManager: RelationshipManager initialized (dependency for QuestManager/ConsequenceProcessor).")
                if self.character_manager and hasattr(self.character_manager, '_relationship_manager') and self.character_manager._relationship_manager is None:
                    setattr(self.character_manager, '_relationship_manager', self.relationship_manager)
                    logger.info("GameManager: Updated relationship_manager in CharacterManager.")

            # ConsequenceProcessor initialization (if not already done)
            if not hasattr(self, 'consequence_processor') or self.consequence_processor is None:
                from bot.game.services.consequence_processor import ConsequenceProcessor # Local import
                self.consequence_processor = ConsequenceProcessor(
                    character_manager=self.character_manager, npc_manager=self.npc_manager,
                    item_manager=self.item_manager, location_manager=self.location_manager,
                    event_manager=self.event_manager, quest_manager=None, # Pass None for QM initially if QM needs CP
                    status_manager=self.status_manager, dialogue_manager=self.dialogue_manager, # DialogueManager might be None here
                    game_state=None, rule_engine=self.rule_engine, economy_manager=self.economy_manager,
                    relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager,
                    notification_service=self.notification_service, prompt_context_collector=self.prompt_context_collector
                )
                logger.info("GameManager: ConsequenceProcessor initialized (dependency for QuestManager).")

            self.quest_manager = QuestManager(
                db_service=self.db_service,
                settings=self._settings.get('quest_settings', {}),
                npc_manager=self.npc_manager,
                character_manager=self.character_manager,
                item_manager=self.item_manager,
                rule_engine=self.rule_engine,
                relationship_manager=self.relationship_manager,
                consequence_processor=self.consequence_processor, # Now ensured to be initialized
                game_log_manager=self.game_log_manager,
                multilingual_prompt_generator=self.multilingual_prompt_generator,
                openai_service=self.openai_service,
                ai_validator=self.ai_response_validator,
                notification_service=self.notification_service
                # Note: QuestManager's __init__ also internally initializes its own ConsequenceProcessor
                # if one is not passed. The one created above will be passed.
                # It also expects _location_manager, _event_manager, _status_manager for its internal CP.
                # These are not directly passed to QM constructor by this logic, but QM's internal CP would get them from its own GM ref.
            )
            logger.info("GameManager: QuestManager initialized correctly in _initialize_processors_and_command_system.")

            # Update CharacterManager with QuestManager if it has a placeholder
            if self.character_manager and hasattr(self.character_manager, 'quest_manager') and self.character_manager.quest_manager is None:
                setattr(self.character_manager, 'quest_manager', self.quest_manager)
                logger.info("GameManager: Updated quest_manager in CharacterManager.")

            # If ConsequenceProcessor was initialized with QM=None, update it now
            if self.consequence_processor and hasattr(self.consequence_processor, 'quest_manager') and self.consequence_processor.quest_manager is None:
                setattr(self.consequence_processor, 'quest_manager', self.quest_manager)
                logger.info("GameManager: Updated quest_manager in self.consequence_processor.")


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
            inventory_manager=self.inventory_manager,
            db_service=self.db_service
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

        # Initialize TurnProcessor
        self.turn_processor = TurnProcessor(game_manager=self)
        logger.info("GameManager: TurnProcessor initialized.")

        # Initialize CheckResolver
        self.check_resolver = CheckResolver(game_manager=self)
        logger.info("GameManager: CheckResolver initialized.")

        # Initialize LocationInteractionService (Part 2 of current subtask)
        self.location_interaction_service = LocationInteractionService(game_manager=self)
        logger.info("GameManager: LocationInteractionService initialized.")

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
        if not self.prompt_context_collector or not self.multilingual_prompt_generator: # Keep existing checks
            logger.warning("GameManager: AI prompt services (collector or generator) not fully inited due to missing managers.")

        self.ai_response_validator = AIResponseValidator()
        logger.info("GameManager: AIResponseValidator initialized.")

        logger.info("GameManager: AI content services initialized.") # Existing log, keep it last in this block

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

    def get_default_bot_language(self, guild_id: str) -> str: # Added guild_id
        # Ensure rules are loaded for the guild
        if self._rules_config_cache is None or guild_id not in self._rules_config_cache:
            # This is a synchronous method, so we can't call async _load_or_initialize_rules_config here.
            # This indicates a design issue: rules should be pre-loaded for active guilds,
            # or this method needs to become async, or RuleEngine needs to handle missing rules.
            logger.warning(f"GameManager: RulesConfig cache for guild {guild_id} not populated when get_default_bot_language called. Defaulting to 'en'.")
            # Attempt to load them if called from an async context that somehow allows this, though it's not ideal.
            # For a sync context, this won't work. This implies GameManager needs an async variant or a different loading strategy.
            # For now, returning a hardcoded default if not found.
            if asyncio.get_event_loop().is_running(): # Basic check, not foolproof for all contexts
                 # This is a temporary workaround and might block if called from a sync part of an async app.
                 # Proper solution is to ensure cache is populated before sync calls.
                 asyncio.ensure_future(self._load_or_initialize_rules_config(guild_id)) # Fire and forget, cache might not be ready immediately.
            return "en" # Fallback

        guild_cache = self._rules_config_cache.get(guild_id, {})
        return guild_cache.get('default_language', 'en')


    def get_max_party_size(self, guild_id: str) -> int: # Added guild_id
        default_size = 4
        if self._rules_config_cache is None or guild_id not in self._rules_config_cache:
            logger.warning(f"GameManager: RulesConfig cache for guild {guild_id} not populated. Defaulting max_party_size to {default_size}.")
            # Similar issue as above with sync access to async loaded cache.
            if asyncio.get_event_loop().is_running():
                 asyncio.ensure_future(self._load_or_initialize_rules_config(guild_id))
            return default_size

        guild_cache = self._rules_config_cache.get(guild_id, {})
        # The new structure stores keys directly, e.g., "max_party_size": 4
        max_size = guild_cache.get('max_party_size')
        if not isinstance(max_size, int):
            logger.warning(f"GameManager: 'max_party_size' not found or not an int in RulesConfig for guild {guild_id}. Defaulting to {default_size}.")
            return default_size
        return max_size

    def get_action_cooldown(self, guild_id: str, action_type: str) -> float: # Added guild_id
        default_cooldown = 30.0 # Default based on new guild_initializer defaults
        if self._rules_config_cache is None or guild_id not in self._rules_config_cache:
            logger.warning(f"GameManager: RulesConfig cache for guild {guild_id} not populated. Defaulting cooldown for '{action_type}' to {default_cooldown}s.")
            if asyncio.get_event_loop().is_running():
                asyncio.ensure_future(self._load_or_initialize_rules_config(guild_id))
            return default_cooldown

        guild_cache = self._rules_config_cache.get(guild_id, {})
        # Assuming cooldowns might be stored under a general key like "action_cooldown_seconds" or specific ones
        # For this example, let's assume a general key "action_cooldown_seconds" from the initializer.
        # If action_type specific cooldowns are needed, the key structure would be e.g. "cooldowns": {"action_type_1": X, ...}
        cooldown = guild_cache.get('action_cooldown_seconds')

        if not isinstance(cooldown, (float, int)):
            # Fallback to a more specific key if the general one isn't found/valid, e.g. looking into a "cooldowns" dict
            # This part depends on how you decide to store these: flat like "action_cooldown_seconds" or nested.
            # For now, using the flat "action_cooldown_seconds" as per example.
            logger.warning(f"GameManager: Cooldown 'action_cooldown_seconds' for guild {guild_id} not found or not a number. Defaulting to {default_cooldown}s for action '{action_type}'.")
            return default_cooldown
        return float(cooldown)

    def get_game_channel_ids(self, guild_id: str) -> List[int]:
        # This method does not directly use _rules_config_cache, so no changes needed for guild_id handling here
        # other than ensuring guild_id is passed correctly to other services if they become guild-specific.
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

    async def get_master_role_id(self, guild_id: str) -> Optional[str]:
        """Fetches the master role ID for the given guild."""
        if not self.db_service:
            logger.warning("GameManager: DBService not available. Cannot get master_role_id for guild %s.", guild_id)
            return None
        try:
            # This could use the new get_rule method if master_role_id is stored in RulesConfig
            # For now, assuming get_guild_setting is a separate mechanism or will be refactored.
            # role_id = await self.get_rule(guild_id, 'master_role_id')
            role_id = await self.db_service.get_guild_setting(guild_id, 'master_role_id') # Kept existing logic
            if role_id and isinstance(role_id, str):
                return role_id
            elif role_id:
                logger.warning("GameManager: master_role_id for guild %s was not a string: %s. Returning as str.", guild_id, role_id)
                return str(role_id) # Attempt to cast, though settings should store as string
            return None
        except Exception as e:
            logger.error("GameManager: Error fetching master_role_id for guild %s: %s", guild_id, e, exc_info=True)
            return None

    async def get_player_model_by_discord_id(self, guild_id: str, discord_id: str) -> Optional[Player]:
        """
        Retrieves a Player model instance by their Discord ID and Guild ID.
        """
        guild_id_str = str(guild_id)
        discord_id_str = str(discord_id)
        logger.debug(f"GameManager: Attempting to get Player model for discord_id '{discord_id_str}' in guild '{guild_id_str}'.")

        if not self.db_service:
            logger.error("GameManager: DBService not available. Cannot fetch Player by Discord ID.")
            return None

        try:
            player_obj = await self.db_service.get_entity_by_conditions(
                table_name='players',
                conditions={'guild_id': guild_id_str, 'discord_id': discord_id_str},
                model_class=Player,
                single_entity=True
            )
            if player_obj:
                logger.info(f"GameManager: Found Player model for discord_id '{discord_id_str}' in guild '{guild_id_str}'. Player ID: {player_obj.id}")
                return player_obj
            else:
                logger.info(f"GameManager: Player model not found for discord_id '{discord_id_str}' in guild '{guild_id_str}'.")
                return None
        except Exception as e:
            logger.error(f"GameManager: Database error when fetching Player by discord_id '{discord_id_str}' for guild '{guild_id_str}': {e}", exc_info=True)
            return None

    async def get_player_model_by_id(self, guild_id: str, player_id: str) -> Optional[Player]:
        """
        Retrieves a Player model instance by their internal Player ID and Guild ID.
        """
        guild_id_str = str(guild_id) # Ensure guild_id is string, though db_service might handle it
        player_id_str = str(player_id)
        logger.debug(f"GameManager: Attempting to get Player model for player_id '{player_id_str}' in guild '{guild_id_str}'.")

        if not self.db_service:
            logger.error("GameManager: DBService not available. Cannot fetch Player by ID.")
            return None

        try:
            player_obj = await self.db_service.get_entity_by_pk(
                table_name='players',
                pk_value=player_id_str,
                guild_id=guild_id_str, # Pass guild_id if your db_service.get_entity_by_pk supports/requires it for namespacing or checks
                model_class=Player
            )
            if player_obj:
                logger.info(f"GameManager: Found Player model for player_id '{player_id_str}' in guild '{guild_id_str}'.")
                return player_obj
            else:
                logger.info(f"GameManager: Player model not found for player_id '{player_id_str}' in guild '{guild_id_str}'.")
                return None
        except Exception as e:
            logger.error(f"GameManager: Database error when fetching Player by player_id '{player_id_str}' for guild '{guild_id_str}': {e}", exc_info=True)
            return None

    async def get_player_model_by_discord_id(self, guild_id: str, discord_id: str) -> Optional[Player]:
        """
        Retrieves a Player model instance by their Discord ID and Guild ID.
        """
        guild_id_str = str(guild_id)
        discord_id_str = str(discord_id)
        logger.debug(f"GameManager: Attempting to get Player model for discord_id '{discord_id_str}' in guild '{guild_id_str}'.")

        if not self.db_service:
            logger.error("GameManager: DBService not available. Cannot fetch Player by Discord ID.")
            return None

        try:
            player_obj = await self.db_service.get_entity_by_conditions(
                table_name='players',
                conditions={'guild_id': guild_id_str, 'discord_id': discord_id_str},
                model_class=Player,
                single_entity=True
            )
            if player_obj:
                logger.info(f"GameManager: Found Player model for discord_id '{discord_id_str}' in guild '{guild_id_str}'. Player ID: {player_obj.id}")
                return player_obj
            else:
                logger.info(f"GameManager: Player model not found for discord_id '{discord_id_str}' in guild '{guild_id_str}'.")
                return None
        except Exception as e:
            logger.error(f"GameManager: Database error when fetching Player by discord_id '{discord_id_str}' for guild '{guild_id_str}': {e}", exc_info=True)
            return None

    async def get_player_model_by_id(self, guild_id: str, player_id: str) -> Optional[Player]:
        """
        Retrieves a Player model instance by their internal Player ID and Guild ID.
        """
        guild_id_str = str(guild_id)
        player_id_str = str(player_id)
        logger.debug(f"GameManager: Attempting to get Player model for player_id '{player_id_str}' in guild '{guild_id_str}'.")

        if not self.db_service:
            logger.error("GameManager: DBService not available. Cannot fetch Player by ID.")
            return None

        try:
            player_obj = await self.db_service.get_entity_by_pk(
                table_name='players', # In DBService, model_class implies table name, but good to be explicit if needed
                pk_value=player_id_str,
                guild_id=guild_id_str,
                model_class=Player
            )
            if player_obj:
                logger.info(f"GameManager: Found Player model for player_id '{player_id_str}' in guild '{guild_id_str}'.")
                return player_obj
            else:
                logger.info(f"GameManager: Player model not found for player_id '{player_id_str}' in guild '{guild_id_str}'.")
                return None
        except Exception as e:
            logger.error(f"GameManager: Database error when fetching Player by player_id '{player_id_str}' for guild '{guild_id_str}': {e}", exc_info=True)
            return None

    async def get_players_in_location(self, guild_id: str, location_id: str) -> List[Player]:
        """
        Retrieves a list of Player model instances currently in a specific location.
        """
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        logger.debug(f"GameManager: Attempting to get Players in location_id '{location_id_str}' for guild '{guild_id_str}'.")

        if not self.db_service:
            logger.error("GameManager: DBService not available. Cannot fetch Players in location.")
            return []

        try:
            players_list = await self.db_service.get_entities_by_conditions(
                table_name='players',
                conditions={'guild_id': guild_id_str, 'current_location_id': location_id_str},
                model_class=Player
            )
            if players_list:
                logger.info(f"GameManager: Found {len(players_list)} Players in location '{location_id_str}' for guild '{guild_id_str}'.")
                return players_list
            else:
                logger.info(f"GameManager: No Players found in location '{location_id_str}' for guild '{guild_id_str}'.")
                return []
        except Exception as e:
            logger.error(f"GameManager: Database error when fetching Players in location '{location_id_str}' for guild '{guild_id_str}': {e}", exc_info=True)
            return []

    async def get_rule(self, guild_id: str, key: str, default: Optional[Any] = None) -> Optional[Any]:
        """
        Retrieves a specific rule value for a guild from the cache.
        Loads the guild's rules if not already cached.
        """
        if self._rules_config_cache is None or guild_id not in self._rules_config_cache:
            logger.info(f"GameManager: Rules for guild {guild_id} not in cache for key '{key}'. Loading.")
            await self._load_or_initialize_rules_config(guild_id)

        # After attempting to load, check again. _load_or_initialize_rules_config should populate it.
        if self._rules_config_cache and guild_id in self._rules_config_cache:
            rule_value = self._rules_config_cache[guild_id].get(key, default)
            logger.debug(f"GameManager: Rule '{key}' for guild {guild_id} retrieved. Value: '{rule_value}', Default: '{default}'")
            return rule_value
        else:
            # This case implies _load_or_initialize_rules_config failed to populate the cache for this guild
            logger.warning(f"GameManager: Rules for guild {guild_id} could not be loaded or initialized. Returning default for key '{key}'.")
            return default

    async def update_rule_config(self, guild_id: str, key: str, value: Any) -> bool:
        """
        Updates or creates a rule in the database and then updates the cache.
        """
        logger.info(f"GameManager: Attempting to update rule '{key}' to '{value}' for guild {guild_id}.")
        if not self.db_service:
            logger.error(f"GameManager: DBService not available. Cannot update rule '{key}' for guild {guild_id}.")
            return False

        try:
            # Check if the rule already exists in DB
            existing_rule_entry = await self.db_service.get_entity_by_conditions(
                table_name='rules_config',
                conditions={'guild_id': guild_id, 'key': key},
                model_class=RulesConfig,
                single_entity=True
            )

            db_success: bool = False
            if existing_rule_entry:
                # Update existing entry
                # Ensure 'value' is appropriate for JSONB if db_service doesn't handle serialization
                update_result = await self.db_service.update_entities_by_conditions(
                    table_name='rules_config',
                    conditions={'guild_id': guild_id, 'key': key},
                    updates={'value': value}
                )
                db_success = bool(update_result) # Assuming truthy non-None means success
                if not db_success:
                    logger.warning(f"GameManager: update_entities_by_conditions returned falsy for rule '{key}', guild {guild_id}.")

            else: # Create new entry
                new_rule_data = {
                    'guild_id': guild_id,
                    'key': key,
                    'value': value
                }
                created_entity = await self.db_service.create_entity(
                    table_name='rules_config',
                    entity_data=new_rule_data,
                    model_class=RulesConfig
                )
                db_success = created_entity is not None

            if db_success:
                logger.info(f"GameManager: Rule '{key}' for guild {guild_id} successfully updated/created in DB. Value: '{value}'.")
                # Ensure cache structure exists then update
                if self._rules_config_cache is None:
                    self._rules_config_cache = {}
                if guild_id not in self._rules_config_cache:
                    logger.info(f"GameManager: Initializing cache for guild {guild_id} during update of rule '{key}'.")
                    self._rules_config_cache[guild_id] = {}

                self._rules_config_cache[guild_id][key] = value
                logger.debug(f"GameManager: Cache for guild {guild_id} updated for rule '{key}'. New cache: {self._rules_config_cache[guild_id]}")
                return True
            else:
                logger.error(f"GameManager: Failed to save rule '{key}' (value: '{value}') for guild {guild_id} to database.")
                return False
        except Exception as e:
            logger.error(f"GameManager: Exception while saving rule '{key}' for guild {guild_id}: {e}. Cache not changed.", exc_info=True)
            return False

    async def set_default_bot_language(self, language: str, guild_id: Optional[str] = None) -> bool:
        if not guild_id:
            logger.error("GameManager (set_default_bot_language): guild_id must be provided to set default language.")
            return False

        success = await self.update_rule_config(guild_id, "default_language", language)

        if success:
            if self.multilingual_prompt_generator:
                # This logic for MPG might need refinement if it's supposed to handle multiple guilds
                # or if the "main" guild concept is different.
                if self._active_guild_ids and guild_id == self._active_guild_ids[0]:
                    self.multilingual_prompt_generator.update_main_bot_language(language)
                    logger.info(f"GameManager: Updated main_bot_language in MultilingualPromptGenerator (due to update for guild {guild_id}).")
                elif not self._active_guild_ids:
                     logger.warning("GameManager: No active_guild_ids defined, MPG main language not updated via set_default_bot_language.")
            return True
        else:
            logger.error(f"GameManager: Failed to set default bot language to '{language}' for guild {guild_id} using update_rule_config.")
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
                char_id_log = getattr(character, 'id', "N/A")
                char_name_log = getattr(character, 'name', "N/A")
                char_loc_id_log = getattr(character, 'current_location_id', "N/A")
                logger.info("GameManager: Successfully started new character session for guild %s. Character ID: %s, Name: %s, Location ID: %s.", guild_id, char_id_log, char_name_log, char_loc_id_log)
                return character # Return character on success
            else:
                # This case implies create_character returned None for reasons other than an exception
                # (e.g., pre-check like name already taken if that logic exists and returns None).
                logger.warning("GameManager: Character creation returned None for user %s in guild %s (e.g. name conflict or other pre-DB check).", user_id, guild_id)
                return None # Return None if create_character returns None without exception
        except CharacterAlreadyExistsError: # Specific exception first
            logger.warning("GameManager: Character creation explicitly failed for user %s in guild %s because the character already exists.", user_id, guild_id)
            raise # Re-raise for the command layer to handle
        except Exception as e:
            # This catches other unexpected errors from create_character
            logger.error("GameManager: Unhandled error in start_new_character_session during character creation for user %s in guild %s: %s", user_id, guild_id, e, exc_info=True)
            return None # Return None for other types of exceptions, maintaining previous behavior for generic errors

    async def handle_move_action(self, guild_id: str, player_id: str, target_location_identifier: str) -> bool:
        """
        Handles a player's request to move to a new location.
        Returns True if the move was successful, False otherwise.
        """
        guild_id_str = str(guild_id)
        player_id_str = str(player_id)
        logger.info(f"GameManager: Handling move action for player {player_id_str} in guild {guild_id_str} to '{target_location_identifier}'.")

        if not self.db_service or not self.location_manager:
            logger.error("GameManager: DBService or LocationManager not available. Cannot handle move action.")
            return False

        # 1. Fetch Player
        player = await self.get_player_model_by_id(guild_id_str, player_id_str)
        if not player:
            logger.error(f"GameManager: Player {player_id_str} not found in guild {guild_id_str} for move action.")
            return False
        if not player.current_location_id:
            logger.error(f"GameManager: Player {player_id_str} in guild {guild_id_str} has no current_location_id. Cannot move.")
            return False

        # 2. Fetch Current Location
        # get_location_instance returns a Location model object directly because Location.from_dict is used inside it
        current_location = await self.location_manager.get_location_instance(guild_id_str, player.current_location_id)
        if not current_location:
            logger.error(f"GameManager: Data inconsistency. Current location {player.current_location_id} for player {player_id_str} (guild {guild_id_str}) not found.")
            return False

        # 3. Resolve Target Location Identifier
        target_location = await self.location_manager.get_location_by_static_id(guild_id_str, target_location_identifier)

        if not target_location:
            logger.debug(f"GameManager: Target location '{target_location_identifier}' not found by static_id for guild {guild_id_str}. Trying by name...")
            # Fallback: search by name in location_manager's cache
            # LocationManager._location_instances stores dicts, not Location objects directly.
            # We need to convert them to Location objects to check name_i18n properly or access name_i18n from dict.

            # Accessing protected member _location_instances for this fallback is not ideal but used as per prompt.
            # A public method in LocationManager to search by name would be better.
            cached_locations = self.location_manager._location_instances.get(guild_id_str, {}).values()
            found_by_name: List[Location] = []
            for loc_data_dict in cached_locations:
                if isinstance(loc_data_dict.get('name_i18n'), dict):
                    if any(name.lower() == target_location_identifier.lower() for name in loc_data_dict['name_i18n'].values()):
                        try:
                            # Convert dict to Location model instance to ensure consistent object type
                            found_by_name.append(Location.from_dict(loc_data_dict))
                        except Exception as e:
                            logger.warning(f"GameManager: Error converting cached location data {loc_data_dict.get('id')} to Location object: {e}")

            if len(found_by_name) == 1:
                target_location = found_by_name[0]
                logger.info(f"GameManager: Target location resolved by name to '{target_location.id}' for identifier '{target_location_identifier}'.")
            elif len(found_by_name) > 1:
                logger.warning(f"GameManager: Ambiguous target location name '{target_location_identifier}' for player {player_id_str}. Multiple matches found. Move failed.")
                # For now, fail on ambiguity. Could potentially ask user to clarify via command response.
                return False

        if not target_location:
            logger.warning(f"GameManager: Target location '{target_location_identifier}' for player {player_id_str} not found by static_id or name. Move failed.")
            return False

        # 4. Check Connectivity
        if not current_location.neighbor_locations_json or not isinstance(current_location.neighbor_locations_json, dict):
            logger.warning(f"GameManager: Player {player_id_str} current location {current_location.id} has no valid neighbor_locations_json. Cannot move.")
            return False

        if target_location.id not in current_location.neighbor_locations_json:
            logger.info(f"GameManager: Player {player_id_str} cannot move from {current_location.id} to {target_location.id}. Not directly connected.")
            return False

        # Check if player is trying to move to the same location
        if current_location.id == target_location.id:
            logger.info(f"GameManager: Player {player_id_str} is already at location {target_location.id}. Move action considered successful but no change.")
            # Depending on game rules, you might want to return False or handle this differently.
            # For now, let's say it's not an error, but no actual move occurs.
            return True # Or False if moving to same spot is an invalid action.

        # 5. Update Player Location
        old_location_id = player.current_location_id
        update_success = await self.db_service.update_player_field(
            player_id=player.id,
            field_name='current_location_id',
            value=target_location.id,
            guild_id_str=guild_id_str
        )

        if not update_success:
            logger.error(f"GameManager: Failed to update player {player_id_str}'s location in DB to {target_location.id}.")
            return False

        logger.info(f"GameManager: Player {player_id_str} successfully moved from {old_location_id} to {target_location.id}.")
        # player.current_location_id = target_location.id # Update local object if it were cached by GM

        # 6. Log Event
        if self.game_log_manager:
            try:
                await self.game_log_manager.log_event(
                    guild_id=guild_id_str,
                    event_type="player_move",
                    details_json={
                        'player_id': player_id_str,
                        'old_location_id': old_location_id,
                        'new_location_id': target_location.id,
                        'method': 'direct_move_command' # Indicates this was a direct move, not part of another action
                    },
                    player_id=player_id_str, # Associate log with the player
                    location_id=target_location.id # New location for context
                )
            except Exception as log_e:
                logger.error(f"GameManager: Failed to log player move event: {log_e}", exc_info=True)

        # TODO: Future: Trigger on_enter/on_exit events for locations if applicable.
        # This would involve calling methods on LocationManager or an EventProcessor.
        # e.g., await self.location_manager.handle_entity_departure(guild_id_str, player.id, "Player", old_location_id)
        # e.g., await self.location_manager.handle_entity_arrival(guild_id_str, player.id, "Player", target_location.id)

        return True

    async def trigger_ai_generation(
        self,
        guild_id: str,
        request_type: str,
        request_params: Dict[str, Any],
        created_by_user_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Triggers an AI generation task, stores the pending request, and notifies for moderation if needed.
        Returns the ID of the PendingGeneration record, or None if the process fails early.
        """
        logger.info(f"GameManager: Triggering AI generation for guild {guild_id}, type '{request_type}', params: {request_params}")

        if not all([self.multilingual_prompt_generator, self.openai_service, self.db_service]):
            logger.error("GameManager: AI generation services (prompt generator, OpenAI, DBService) not fully available. Cannot trigger generation.")
            return None

        # Determine specific task instruction for the prompt generator
        specific_task_instruction = ""
        if request_type == "location_content_generation":
            specific_task_instruction = "Generate detailed content for a game location based on the provided context and parameters, including name, atmospheric description, points of interest, and connections."
        elif request_type == "npc_profile_generation":
            specific_task_instruction = "Generate a complete NPC profile based on the provided context and parameters, including template_id, name, role, archetype, backstory, personality, motivation, visual description, dialogue hints, stats, skills, abilities, spells, inventory, faction affiliations, and relationships."
        elif request_type == "quest_generation":
            specific_task_instruction = "Generate a complete quest structure based on the provided context and parameters, including name, description, steps (with mechanics, goals, consequences), overall consequences, and prerequisites."
        else:
            specific_task_instruction = "Perform the requested AI generation task based on the provided context and parameters."

        # Location ID is a required parameter for prepare_ai_prompt
        location_id_for_prompt = request_params.get("location_id")
        if not location_id_for_prompt:
            # For some request types, location_id might be optional or derived differently.
            # This needs careful consideration based on how prompts are built.
            # For now, if prepare_ai_prompt strictly requires it, we must ensure it's present.
            # If it's a new location being generated, perhaps a placeholder or parent location ID is used.
            logger.warning(f"GameManager: location_id not found in request_params for AI generation type '{request_type}'. Prepare_ai_prompt might fail or use a default.")
            # If location_id is absolutely critical for all prompt types, could return None here.
            # For now, let prepare_ai_prompt handle it if it can.

        prompt_str = await self.multilingual_prompt_generator.prepare_ai_prompt(
            guild_id=guild_id,
            location_id=str(location_id_for_prompt) if location_id_for_prompt else "", # Pass empty string if None, prepare_ai_prompt needs str
            player_id=request_params.get("player_id"),
            party_id=request_params.get("party_id"),
            specific_task_instruction=specific_task_instruction,
            additional_request_params=request_params
        )

        raw_ai_output = await self.openai_service.get_completion(prompt_str)

        pending_status = "pending_validation"
        parsed_data_dict: Optional[Dict[str, Any]] = None
        validation_issues_list: Optional[List[Dict[str, Any]]] = None

        if not raw_ai_output:
            logger.error(f"GameManager: AI generation failed for type '{request_type}', guild {guild_id}. No output from OpenAI service.")
            pending_status = "failed_validation"
            validation_issues_list = [{"type": "generation_error", "msg": "AI service returned no output."}]
        else:
            parsed_data_dict, validation_issues_list = await parse_and_validate_ai_response(
                raw_ai_output_text=raw_ai_output,
                guild_id=guild_id,
                request_type=request_type,
                game_manager=self
            )
            if validation_issues_list:
                pending_status = "failed_validation"
            else: # Pydantic validation passed
                pending_status = "pending_moderation" # Requires human review after structural validation

        pending_gen_data = {
            "guild_id": guild_id,
            "request_type": request_type,
            "request_params_json": json.dumps(request_params) if request_params else None,
            "raw_ai_output_text": raw_ai_output,
            "parsed_data_json": parsed_data_dict, # This is already a dict from parse_and_validate
            "validation_issues_json": validation_issues_list,
            "status": pending_status,
            "created_by_user_id": created_by_user_id
        }

        pending_gen_record = await self.db_service.create_entity(
            model_class=PendingGeneration,
            entity_data=pending_gen_data
            # guild_id is part of entity_data, db_service.create_entity might not need it separately
        )

        if not pending_gen_record or not pending_gen_record.id:
            logger.error(f"GameManager: Failed to create PendingGeneration record in DB for type '{request_type}', guild {guild_id}.")
            return None

        logger.info(f"GameManager: PendingGeneration record {pending_gen_record.id} created with status '{pending_status}' for type '{request_type}', guild {guild_id}.")

        if pending_status == "pending_moderation" and self.notification_service:
            guild_config_obj: Optional[GuildConfig] = await self.db_service.get_entity_by_pk(GuildConfig, pk_value=guild_id) # Fetch by PK
            if guild_config_obj:
                notification_channel_id_to_use = guild_config_obj.notification_channel_id or \
                                                 guild_config_obj.master_channel_id or \
                                                 guild_config_obj.system_channel_id

                if notification_channel_id_to_use:
                    try:
                        await self.notification_service.send_notification(
                            target_channel_id=int(notification_channel_id_to_use),
                            message=f"New content of type '{request_type}' (Request ID: {pending_gen_record.id}) is pending moderation."
                        )
                        logger.info(f"Sent moderation pending notification to channel {notification_channel_id_to_use} for PG ID {pending_gen_record.id}.")
                    except ValueError:
                        logger.error(f"Invalid channel ID format for notification: {notification_channel_id_to_use}")
                    except Exception as e:
                        logger.error(f"Failed to send moderation notification for PG ID {pending_gen_record.id}: {e}", exc_info=True)
                else:
                    logger.warning(f"No suitable notification channel configured for guild {guild_id} to send moderation pending message for PG ID {pending_gen_record.id}.")
            else:
                logger.warning(f"Could not fetch GuildConfig for guild {guild_id} to send moderation notification for PG ID {pending_gen_record.id}.")

        return pending_gen_record.id

    async def apply_approved_generation(self, pending_gen_id: str, guild_id: str) -> bool:
        """
        Applies an approved AI generation to the game state.
        Currently handles "npc_profile_generation".
        """
        logger.info(f"GameManager: Applying approved generation {pending_gen_id} for guild {guild_id}.")
        if not self.db_service:
            logger.error("GameManager: DBService not available. Cannot apply generation.")
            return False

        # Fetch PendingGeneration record safely
        record: Optional[PendingGeneration] = await self.db_service.get_entity_by_conditions(
            PendingGeneration,
            conditions={'id': pending_gen_id, 'guild_id': guild_id},
            single_entity=True
        )

        if not record:
            logger.error(f"GameManager: PendingGeneration record {pending_gen_id} not found or does not belong to guild {guild_id}.")
            return False

        if record.status != "approved":
            logger.warning(f"GameManager: PendingGeneration record {pending_gen_id} is not in 'approved' status (current: {record.status}). Cannot apply.")
            return False

        if not record.parsed_data_json or not isinstance(record.parsed_data_json, dict):
            logger.error(f"GameManager: Parsed data for {pending_gen_id} is missing or invalid. Cannot apply.")
            record.status = "application_failed"
            record.validation_issues_json = (record.validation_issues_json or []) + [{"type": "application_error", "msg": "Parsed data missing or invalid for application."}] # type: ignore
            await self.db_service.update_entity_by_pk(PendingGeneration, record.id, {"status": record.status, "validation_issues_json": record.validation_issues_json}, guild_id=guild_id)
            return False

        application_successful = False
        try:
            if record.request_type == "npc_profile_generation":
                npc_data = record.parsed_data_json
                request_params = json.loads(record.request_params_json) if record.request_params_json else {}

                # Prepare data for NPC model
                npc_id = str(uuid.uuid4())

                # Default health/max_health, can be overridden by stats from AI
                default_hp = 100.0
                stats_data = npc_data.get("stats", {})
                health = float(stats_data.get("hp", default_hp)) if "hp" in stats_data else float(stats_data.get("health", default_hp)) # common variations
                max_health_val = float(stats_data.get("max_hp", default_hp)) if "max_hp" in stats_data else float(stats_data.get("max_health", health))


                npc_db_data = {
                    "id": npc_id,
                    "guild_id": guild_id,
                    "name_i18n": npc_data.get("name_i18n"),
                    "description_i18n": npc_data.get("visual_description_i18n"), # Mapping visual desc to main desc
                    "backstory_i18n": npc_data.get("backstory_i18n"),
                    "persona_i18n": npc_data.get("personality_i18n"), # Mapping personality to persona
                    "stats": stats_data,
                    "inventory": npc_data.get("inventory", []), # Expects list of dicts from pydantic model
                    "archetype": npc_data.get("archetype"),
                    "template_id": npc_data.get("template_id"), # This is AI generated template_id for this NPC
                    "location_id": request_params.get("initial_location_id"), # from original request
                    "health": health,
                    "max_health": max_health_val,
                    "is_alive": True,
                    "faction_id": None, # Default, can be complex
                    # Ensure other nullable fields default to None or their DB default if not in npc_data
                    "motives": npc_data.get("motivation_i18n"), # Mapping motivation to motives
                    "skills_data": npc_data.get("skills"),
                    "abilities_data": {"ids": npc_data.get("abilities", [])}, # Example structure
                    "equipment_data": {}, # Needs definition based on how equipment is handled
                    "state_variables": {}, # Default empty
                    "is_temporary": request_params.get("is_temporary", False)
                }

                # Handle faction_id (simplified: take first if exists)
                faction_affiliations = npc_data.get("faction_affiliations")
                if faction_affiliations and isinstance(faction_affiliations, list) and len(faction_affiliations) > 0:
                    first_faction = faction_affiliations[0]
                    if isinstance(first_faction, dict) and "faction_id" in first_faction:
                        npc_db_data["faction_id"] = first_faction["faction_id"]

                from bot.database.models import NPC # Local import to avoid circularity at top level
                new_npc = await self.db_service.create_entity(model_class=NPC, entity_data=npc_db_data)

                if new_npc:
                    logger.info(f"GameManager: Successfully applied NPC generation {pending_gen_id}. New NPC ID: {new_npc.id}")
                    record.status = "applied"
                    application_successful = True
                else:
                    logger.error(f"GameManager: Failed to create NPC in DB for {pending_gen_id}.")
                    record.status = "application_failed"
                    record.validation_issues_json = (record.validation_issues_json or []) + [{"type": "application_error", "msg": "NPC database creation failed."}] # type: ignore

            elif record.request_type == "location_content_generation":
                logger.info(f"GameManager: Applying 'location_content_generation' for PG ID: {pending_gen_id}")
                location_gen_data = record.parsed_data_json # This is a dict from GeneratedLocationContent.model_dump()
                request_params = json.loads(record.request_params_json) if record.request_params_json else {}

                new_loc_id = str(uuid.uuid4())
                guild_id_str = record.guild_id

                # Prepare neighbor_locations_json from connections_data
                neighbor_locations = {}
                connections_data = location_gen_data.get("connections", [])
                if isinstance(connections_data, list):
                    for conn in connections_data:
                        if isinstance(conn, dict):
                            target_id = conn.get("to_location_id")
                            # Use 'en' path description as a simple key, or create a more robust key if needed
                            path_desc_key = conn.get("path_description_i18n", {}).get("en", f"path_to_{target_id}")
                            if target_id:
                                neighbor_locations[target_id] = path_desc_key

                # Prepare points_of_interest_json (assuming this field will be added to Location model)
                points_of_interest_data = location_gen_data.get("points_of_interest", [])

                # Prepare ai_metadata_json
                ai_metadata = {
                    "original_request_params": request_params,
                    "ai_generated_template_id": location_gen_data.get("template_id")
                }

                # Ensure static_id: use AI's template_id, or generate a new one if missing/empty
                static_id_val = location_gen_data.get("template_id")
                if not static_id_val or not static_id_val.strip():
                    static_id_val = f"ai_loc_{new_loc_id[:12]}" # Shorter to fit typical DB limits if any

                location_db_data = {
                    "id": new_loc_id,
                    "guild_id": guild_id_str,
                    "name_i18n": location_gen_data.get("name_i18n", {"en": "Unnamed AI Location"}),
                    "descriptions_i18n": location_gen_data.get("atmospheric_description_i18n", {"en": "No description provided."}),
                    "static_id": static_id_val,
                    "template_id": location_gen_data.get("template_id"), # This might be redundant if static_id is the same
                    "type_i18n": location_gen_data.get("type_i18n", {"en": "AI Generated Area", "ru": "Сгенерированная область"}),
                    "neighbor_locations_json": neighbor_locations,
                    "points_of_interest_json": points_of_interest_data, # Data for the new field
                    "ai_metadata_json": ai_metadata,
                    "inventory": {}, # Default
                    "npc_ids": [],   # Default
                    "event_triggers": [], # Default
                    "state_variables": {}, # Default
                    "coordinates": location_gen_data.get("coordinates", {}), # If AI provides, else default
                    "is_active": True,
                    "channel_id": None, # Usually not set by AI directly
                    "image_url": None   # Usually not set by AI directly
                }

                # Location model needs to be imported at the top of the file
                # from bot.database.models import Location
                new_location = await self.db_service.create_entity(model_class=Location, entity_data=location_db_data)

                if new_location:
                    logger.info(f"GameManager: Successfully applied Location generation {pending_gen_id}. New Location ID: {new_location.id}, Static ID: {new_location.static_id}")
                    record.status = "applied"
                    application_successful = True
                else:
                    logger.error(f"GameManager: Failed to create Location in DB for {pending_gen_id}.")
                    record.status = "application_failed"
                    record.validation_issues_json = (record.validation_issues_json or []) + [{"type": "application_error", "msg": "Location database creation failed."}] # type: ignore

            elif record.request_type == "quest_generation":
                logger.info(f"GameManager: Applying 'quest_generation' for PG ID: {pending_gen_id}")
                application_successful = False # Initialize for this block
                quest_gen_data = record.parsed_data_json
                guild_id_str = record.guild_id

                async with self.db_service.get_session() as session: # Start transaction
                    try:
                        new_quest_id = str(uuid.uuid4())

                        # Prepare QuestTable data
                        quest_db_data = {
                            "id": new_quest_id,
                            "guild_id": guild_id_str,
                            "name_i18n": quest_gen_data.get("name_i18n", quest_gen_data.get("title_i18n", {"en": "Untitled Quest"})),
                            "description_i18n": quest_gen_data.get("description_i18n", {"en": "No description."}),
                            "status": "available", # Default status
                            "influence_level": quest_gen_data.get("influence_level"),
                            "prerequisites_json_str": json.dumps(quest_gen_data.get("prerequisites_json")) if quest_gen_data.get("prerequisites_json") else None,
                            "rewards_json_str": json.dumps(quest_gen_data.get("rewards_json", quest_gen_data.get("consequences_json"))) if quest_gen_data.get("rewards_json", quest_gen_data.get("consequences_json")) else None,
                            "consequences_json_str": json.dumps(quest_gen_data.get("consequences_json")) if quest_gen_data.get("consequences_json") else None,
                            "npc_involvement_json": quest_gen_data.get("npc_involvement", {}),
                            "quest_giver_details_i18n": quest_gen_data.get("quest_giver_details_i18n"),
                            "consequences_summary_i18n": quest_gen_data.get("consequences_summary_i18n"),
                            "is_ai_generated": True,
                            "ai_prompt_context_json_str": json.dumps(quest_gen_data.get("ai_prompt_context_json")) if quest_gen_data.get("ai_prompt_context_json") else None,
                        }

                        new_quest = await self.db_service.create_entity(
                            model_class=QuestTable,
                            entity_data=quest_db_data,
                            session=session,
                            guild_id=guild_id_str
                        )

                        if not new_quest:
                            logger.error(f"GameManager: Failed to create QuestTable record for PG ID {pending_gen_id}. Transaction will be rolled back.")
                            # application_successful remains False
                        else:
                            logger.info(f"GameManager: QuestTable record {new_quest.id} created for PG ID {pending_gen_id}.")
                            steps_data = quest_gen_data.get("steps", [])
                            all_steps_created = True
                            for step_data in steps_data:
                                new_step_id = str(uuid.uuid4())
                                step_db_data = {
                                    "id": new_step_id,
                                    "guild_id": guild_id_str,
                                    "quest_id": new_quest.id,
                                    "title_i18n": step_data.get("title_i18n"),
                                    "description_i18n": step_data.get("description_i18n"),
                                    "requirements_i18n": step_data.get("requirements_i18n", {}),
                                    "required_mechanics_json": json.dumps(step_data.get("required_mechanics_json", {})) if step_data.get("required_mechanics_json") else json.dumps({}),
                                    "abstract_goal_json": json.dumps(step_data.get("abstract_goal_json", {})) if step_data.get("abstract_goal_json") else json.dumps({}),
                                    "conditions_json": json.dumps(step_data.get("conditions_json", {})) if step_data.get("conditions_json") else json.dumps({}),
                                    "consequences_json": json.dumps(step_data.get("consequences_json", {})) if step_data.get("consequences_json") else json.dumps({}),
                                    "step_order": step_data.get("step_order", 0),
                                    "status": step_data.get("status", "pending"),
                                    "assignee_type": step_data.get("assignee_type"),
                                    "assignee_id": step_data.get("assignee_id")
                                }
                                new_step = await self.db_service.create_entity(
                                    model_class=QuestStepTable,
                                    entity_data=step_db_data,
                                    session=session,
                                    guild_id=guild_id_str
                                )
                                if not new_step:
                                    logger.error(f"GameManager: Failed to create QuestStepTable record for quest {new_quest.id} (PG ID {pending_gen_id}). Transaction will be rolled back.")
                                    all_steps_created = False
                                    break

                            if all_steps_created:
                                await session.commit() # Commit transaction
                                application_successful = True # Set true only after successful commit
                                logger.info(f"GameManager: Successfully applied Quest generation {pending_gen_id} with {len(steps_data)} steps. New Quest ID: {new_quest.id}")
                            else:
                                # application_successful remains False, transaction will rollback automatically
                                logger.error(f"GameManager: Quest step creation failed, quest {new_quest.id} (PG ID {pending_gen_id}) will be rolled back.")

                    except Exception as transaction_e:
                        logger.error(f"GameManager: Exception during quest application transaction for PG ID {pending_gen_id}: {transaction_e}", exc_info=True)
                        application_successful = False # Ensure this is false on any exception within try
                        # Transaction will rollback automatically due to 'async with' context manager if commit wasn't reached or exception occurred after commit (though less likely for commit itself to raise often)

                # Update record status based on transaction outcome, outside the transaction block
                if application_successful: # This is True only if commit was successful
                    record.status = "applied"
                else:
                    record.status = "application_failed"
                    # Add a generic error if not already set by specific failures inside the transaction
                    current_issues = record.validation_issues_json if isinstance(record.validation_issues_json, list) else []
                    if not any(issue.get("type") == "application_error" for issue in current_issues): # type: ignore
                        current_issues.append({"type": "application_error", "msg": "Quest application transaction failed or was rolled back."}) # type: ignore
                        record.validation_issues_json = current_issues

            else:
                logger.warning(f"GameManager: Application logic for request_type '{record.request_type}' (PG ID: {pending_gen_id}) not yet implemented.")
                record.status = "application_pending_logic"
                application_successful = False # Or True if you consider "pending_logic" a successful handoff

        except Exception as e: # Catch exceptions outside the transaction block or if transaction itself fails to start
            logger.error(f"GameManager: General exception during application of {pending_gen_id} ({record.request_type}): {e}", exc_info=True)
            record.status = "application_failed" # Ensure status reflects failure
            current_issues = record.validation_issues_json if isinstance(record.validation_issues_json, list) else []
            current_issues.append({"type": "application_error", "msg": f"Outer exception during application: {str(e)}"}) # type: ignore
            record.validation_issues_json = current_issues
            application_successful = False

        # Save updated PendingGeneration status (outside transaction block)
        update_payload = {"status": record.status}
        # Ensure validation_issues_json is included in the update if it was modified
        if hasattr(record, 'validation_issues_json') and record.validation_issues_json is not None:
             update_payload["validation_issues_json"] = record.validation_issues_json

        # Use a new session for this update as the previous one might have been rolled back or closed.
        await self.db_service.update_entity_by_pk(PendingGeneration, record.id, update_payload, guild_id=guild_id)

        return application_successful

logger.debug("DEBUG: Finished loading game_manager.py from: %s", __file__) # Changed
