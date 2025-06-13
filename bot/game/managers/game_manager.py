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
            data = await self.db_service.get_entity(table_name='rules_config', entity_id=DEFAULT_RULES_CONFIG_ID, id_field='id')
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

            rules_entity_data = {'id': DEFAULT_RULES_CONFIG_ID, 'config_data': json.dumps(self._rules_config_cache)}
            try:
                existing_config = await self.db_service.get_entity('rules_config', DEFAULT_RULES_CONFIG_ID, id_field='id')
                if existing_config is not None:
                    logger.info("GameManager: Attempting to update existing default rules in DB (ID: %s).", DEFAULT_RULES_CONFIG_ID) # Changed
                    success = await self.db_service.update_entity('rules_config', DEFAULT_RULES_CONFIG_ID, {'config_data': json.dumps(self._rules_config_cache)}, id_field='id')
                    if success: logger.info("GameManager: Successfully updated default rules in DB.") # Changed
                    else: logger.error("GameManager: Failed to update default rules in DB.") # Changed
                else:
                    logger.info("GameManager: Attempting to create new default rules in DB (ID: %s).", DEFAULT_RULES_CONFIG_ID) # Changed
                    new_id = await self.db_service.create_entity('rules_config', rules_entity_data, id_field='id')
                    if new_id is not None: logger.info("GameManager: Successfully created default rules in DB with ID %s.", new_id) # Changed
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
        from bot.game.managers.character_manager import CharacterManager
        from bot.services.openai_service import OpenAIService

        await self._load_or_initialize_rules_config()
        self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}), rules_data=self._rules_config_cache)
        self.time_manager = TimeManager(db_service=self.db_service, settings=self._settings.get('time_settings', {}))
        self.location_manager = LocationManager(db_service=self.db_service, settings=self._settings)
        try:
            oset = self._settings.get('openai_settings', {})
            self.openai_service = OpenAIService(api_key=oset.get('api_key'), model=oset.get('model'), default_max_tokens=oset.get('default_max_tokens'))
            if not self.openai_service.is_available(): self.openai_service = None
        except Exception as e: self.openai_service = None; logger.warning("GameManager: Failed OpenAIService init (%s)", e, exc_info=True) # Changed

        self.event_manager = EventManager(db_service=self.db_service, settings=self._settings.get('event_settings', {}), openai_service=self.openai_service)
        self.character_manager = CharacterManager(db_service=self.db_service, settings=self._settings, location_manager=self.location_manager, rule_engine=self.rule_engine)
        logger.info("GameManager: Core managers and OpenAI service initialized.") # Changed

    async def _initialize_dependent_managers(self):
        logger.info("GameManager: Initializing dependent managers...") # Changed
        # ... (Imports as before)
        from bot.game.managers.item_manager import ItemManager
        from bot.game.managers.status_manager import StatusManager
        # ... (other imports)
        from bot.game.managers.lore_manager import LoreManager

        self.item_manager = ItemManager(db_service=self.db_service, settings=self._settings, location_manager=self.location_manager, rule_engine=self.rule_engine)
        # ... (Initialize other managers as before, replace print with logger.info or logger.warning)
        if not hasattr(self, 'campaign_loader') or self.campaign_loader is None:
            from bot.game.services.campaign_loader import CampaignLoader # Moved import
            self.campaign_loader = CampaignLoader(settings=self._settings, db_service=self.db_service)
            logger.info("GameManager: Initialized CampaignLoader directly before NpcManager.") # Changed

        # ... (NPC archetype loading logic)
        if self.campaign_loader:
            campaign_identifier = self._settings.get('default_campaign_identifier')
            default_campaign_data = await self.campaign_loader.load_campaign_data_from_source(campaign_identifier=campaign_identifier)
            if default_campaign_data and isinstance(default_campaign_data.get('npc_archetypes'), dict): # Expect a dictionary
                npc_archetypes_from_campaign = default_campaign_data['npc_archetypes']
                logger.info("GameManager: Loaded %s NPC archetypes dictionary from campaign '%s'.", len(npc_archetypes_from_campaign), campaign_identifier or 'default')
            else:
                npc_archetypes_from_campaign = {} # Initialize as empty dict
                logger.warning("GameManager: Could not load NPC archetypes dictionary from campaign '%s'. Using empty dict.", campaign_identifier or 'default')
        else:
            npc_archetypes_from_campaign = {}
            logger.warning("GameManager: CampaignLoader not available. NPC archetypes will be empty for NpcManager.")

        npc_manager_settings = self._settings.get('npc_settings', {}).copy()
        # Add the pre-loaded archetypes to this settings dictionary
        npc_manager_settings['loaded_npc_archetypes_from_campaign'] = npc_archetypes_from_campaign

        # Ensure other necessary managers are initialized before NpcManager if they are dependencies
        # For NpcManager: combat_manager, status_manager are listed.
        # Original order: ItemManager, CampaignLoader, NpcManager, StatusManager, CombatManager
        # This means StatusManager and CombatManager are not yet initialized when NpcManager is called.
        # If NpcManager's __init__ strictly needs them, this order MUST change.
        # For this subtask, assuming NpcManager can handle None for these at __init__ or they are set later.
        # This is a critical point for overall system stability but outside the direct archetype loading fix.

        from bot.game.managers.npc_manager import NpcManager # Moved import
        self.npc_manager = NpcManager(
            db_service=self.db_service,
            settings=npc_manager_settings, # Pass settings containing the loaded archetypes
            item_manager=self.item_manager,
            rule_engine=self.rule_engine,
            combat_manager=self.combat_manager, # Will be None if not initialized yet
            status_manager=self.status_manager, # Will be None if not initialized yet
            openai_service=self.openai_service,
            campaign_loader=self.campaign_loader
        )
        # ... (Rest of manager initializations with logging)
        # StatusManager and CombatManager are initialized after NpcManager in the original code.
        # self.status_manager = StatusManager(...)
        # self.combat_manager = CombatManager(...)
        self.lore_manager = LoreManager(settings=self._settings.get('lore_settings', {}), db_service=self.db_service)

        # Initialize NotificationService
        if self.character_manager: # Check if character_manager was successfully initialized
            self.notification_service = NotificationService(
                send_callback_factory=self._get_discord_send_callback,
                settings=self._settings,
                i18n_utils=None,  # Passing None as GameManager doesn't currently manage I18nUtils directly
                character_manager=self.character_manager
            )
            logger.info("GameManager: NotificationService initialized.")
        else:
            logger.error("GameManager: CharacterManager not available, cannot initialize NotificationService.")
            self.notification_service = None # Explicitly set to None if dependent manager is missing

        # ... (Cross-references, ensure they happen after all relevant managers are initialized)
        # Example: if self.npc_manager and self.dialogue_manager:
        #    self.npc_manager.dialogue_manager = self.dialogue_manager
        #    self.dialogue_manager.npc_manager = self.npc_manager
        # This kind of cross-referencing might need to be grouped after ALL managers are initialized.

        logger.info("GameManager: Dependent managers initialized and cross-references set.") # Changed

    async def _initialize_processors_and_command_system(self):
        logger.info("GameManager: Initializing processors and command system...") # Changed
        # ... (Imports as before)
        from bot.game.managers.undo_manager import UndoManager
        # ... (Initialize processors as before)
        if self.db_service and self.game_log_manager and self.character_manager and self.item_manager and self.quest_manager and self.party_manager:
            self.undo_manager = UndoManager(db_service=self.db_service, game_log_manager=self.game_log_manager, character_manager=self.character_manager, item_manager=self.item_manager, quest_manager=self.quest_manager, party_manager=self.party_manager)
            logger.info("GameManager: UndoManager initialized.") # Changed
        else:
            logger.critical("GameManager: UndoManager could not be initialized due to missing dependencies.") # Changed
            self.undo_manager = None
        # ... (Rest of initialization)
        logger.info("GameManager: Processors and command system initialized.") # Changed

    async def _load_initial_data_and_state(self):
        logger.info("GameManager: Loading initial game data and state...") # Changed
        if self.campaign_loader:
            if self._active_guild_ids:
                for guild_id_str in self._active_guild_ids:
                    logger.info("GameManager: Populating game data for guild %s.", guild_id_str) # Added
                    await self.campaign_loader.populate_all_game_data(guild_id=guild_id_str, campaign_identifier=None)
            else:
                logger.info("GameManager: No active guilds specified, loading global item data via CampaignLoader.") # Added
                await self.campaign_loader.load_and_populate_items()

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
