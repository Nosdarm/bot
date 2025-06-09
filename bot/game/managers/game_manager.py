# bot/game/managers/game_manager.py

print("--- Начинается загрузка: game_manager.py")
import asyncio
import json
import traceback
import os
import io
from alembic.config import Config
from alembic import command
# from bot.alembic.env import run_async_upgrade # Removed
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING

from asyncpg import exceptions as asyncpg_exceptions # For specific DB error types
from bot.database.postgres_adapter import SQLALCHEMY_DATABASE_URL as PG_URL_FOR_ALEMBIC

import discord
from discord import Client

from bot.services.db_service import DBService
from bot.ai.rules_schema import GameRules

from bot.game.models.character import Character

if TYPE_CHECKING:
    from discord import Message
    from bot.game.models.character import Character
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
    from bot.game.turn_processing_service import TurnProcessingService # Added import

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

DEFAULT_RULES_CONFIG_ID = "main_rules_config"

class GameManager:
    def __init__(
        self,
        discord_client: Client,
        settings: Dict[str, Any]
    ):
        print("Initializing GameManager…")
        self._discord_client = discord_client
        self._settings = settings
        self._rules_config_cache: Optional[Dict[str, Any]] = None

        self.db_service: Optional[DBService] = None # Changed from _db_adapter
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
        self.turn_processing_service: Optional["TurnProcessingService"] = None # Added attribute
        
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

        print("GameManager initialized.\n")

    # --- Private Helper Methods for Setup ---
    async def _load_or_initialize_rules_config(self):
        print("GameManager: Loading or initializing rules configuration...")
        self._rules_config_cache = {} # Initialize to empty dict
        if not self.db_service:
            print("GameManager: Error - DBService not available for loading rules config.")
            # Fallback to default rules if DB service is not up yet (should ideally not happen if called after DB init)
            self._rules_config_cache = {
                "default_bot_language": "en", "game_world_name": "Default World (DB Error)",
                "story_elements": {"plot_points": [], "themes": ["adventure"]},
                "character_rules": {"max_level": 100, "base_stats": {"health": 100, "mana": 50}},
                "skill_rules": {"max_skill_level": 10, "skills_list": ["mining", "herbalism"]},
                "item_rules": {"max_inventory_size": 20},
                "combat_rules": {"turn_time_limit_seconds": 30},
                "economy_rules": {"starting_gold": 100},
                "npc_rules": {"max_npcs_per_location": 10},
                "quest_rules": {"max_active_quests": 5},
                "event_rules": {"global_event_chance": 0.05},
                "world_rules": {"time_scale_factor": 1.0},
                "action_rules": {"cooldowns": {"attack": 5.0, "explore": 10.0}},
                "party_rules": {"max_size": 4}
            }
            print("GameManager: Used fallback default rules due to DBService unavailability at time of call.")
            return

        data = None
        try:
            data = await self.db_service.get_entity(table_name='rules_config', entity_id=DEFAULT_RULES_CONFIG_ID, id_field='id')
        except Exception as e:
            print(f"GameManager: Error fetching rules_config from DB: {e}")
            # Proceed to default initialization as if data was None

        if data and 'config_data' in data:
            try:
                self._rules_config_cache = data['config_data']
                print(f"GameManager: Successfully loaded rules from DB for ID {DEFAULT_RULES_CONFIG_ID}.")
                # Ensure essential keys are present, migrate if necessary (future enhancement)
                if "default_bot_language" not in self._rules_config_cache: # Basic check
                    print("GameManager: Warning - loaded rules lack 'default_bot_language'. Consider migration or re-init.")
                    # Potentially force re-init or merge with defaults here
            except json.JSONDecodeError as e:
                print(f"GameManager: Error decoding JSON from rules_config DB: {e}. Proceeding with default rules.")
                data = None # Force default initialization
            except Exception as e: # Catch other potential errors during loading/parsing
                print(f"GameManager: Unexpected error loading/parsing rules_config: {e}. Proceeding with default rules.")
                data = None # Force default initialization


        if not data or 'config_data' not in data or self._rules_config_cache is None: # condition implies cache wasn't set or forced to None
            print(f"GameManager: No valid rules found in DB for ID {DEFAULT_RULES_CONFIG_ID} or error during load. Creating default rules...")
            default_rules = {
                "default_bot_language": "en",
                "game_world_name": "Default World",
                "story_elements": {"plot_points": [], "themes": ["adventure"]},
                "character_rules": {"max_level": 100, "base_stats": {"health": 100, "mana": 50}},
                "skill_rules": {"max_skill_level": 10, "skills_list": ["mining", "herbalism"]},
                "item_rules": {"max_inventory_size": 20},
                "combat_rules": {"turn_time_limit_seconds": 30},
                "economy_rules": {"starting_gold": 100},
                "npc_rules": {"max_npcs_per_location": 10},
                "quest_rules": {"max_active_quests": 5},
                "event_rules": {"global_event_chance": 0.05},
                "world_rules": {"time_scale_factor": 1.0},
                "action_rules": {"cooldowns": {"attack": 5.0, "explore": 10.0}},
                "party_rules": {"max_size": 4}
            }
            self._rules_config_cache = default_rules
            print("GameManager: Default rules created and cached.")

            rules_entity_data = {
                'id': DEFAULT_RULES_CONFIG_ID,
                'config_data': json.dumps(self._rules_config_cache)
            }

            try:
                existing_config = await self.db_service.get_entity(
                    table_name='rules_config',
                    entity_id=DEFAULT_RULES_CONFIG_ID,
                    id_field='id'
                )

                if existing_config is not None:
                    print(f"GameManager: Attempting to update existing default rules in DB (ID: {DEFAULT_RULES_CONFIG_ID}).")
                    success = await self.db_service.update_entity(
                        table_name='rules_config',
                        entity_id=DEFAULT_RULES_CONFIG_ID,
                        data={'config_data': json.dumps(self._rules_config_cache)}, # Only update config_data
                        id_field='id'
                    )
                    if success:
                        print(f"GameManager: Successfully updated default rules in DB.")
                    else:
                        print(f"GameManager: Failed to update default rules in DB.")
                else:
                    print(f"GameManager: Attempting to create new default rules in DB (ID: {DEFAULT_RULES_CONFIG_ID}).")
                    # Ensure 'id' is part of the data for create_entity if your DB adapter expects it directly
                    # For SqliteAdapter, id_field='id' means it will look for data['id'] if PK is not autoincrement
                    # or handle autoincrement if data['id'] is not provided and PK is autoincrement.
                    # Since 'id' is explicitly DEFAULT_RULES_CONFIG_ID, we must provide it.
                    new_id = await self.db_service.create_entity(
                        table_name='rules_config',
                        data=rules_entity_data, # includes 'id' and 'config_data'
                        id_field='id' # Specify the ID field for clarity, though adapter might infer
                    )
                    if new_id is not None: # create_entity usually returns the ID of the new row
                        print(f"GameManager: Successfully created default rules in DB with ID {new_id}.")
                    else:
                        print(f"GameManager: Failed to create default rules in DB.")
            except Exception as e:
                print(f"GameManager: Error during upsert of default rules to DB: {e}")

        # Final check to ensure cache is not None, even if all else failed.
        if self._rules_config_cache is None:
            print("GameManager: CRITICAL - Rules cache is still None after load/init. Using emergency fallback.")
            self._rules_config_cache = { "default_bot_language": "en", "emergency_mode": True }


    async def _initialize_database(self):
        print("GameManager: Initializing database service...")
        self.db_service = DBService() # Removed db_path
        await self.db_service.connect()

        # try:
        #     print("GameManager: Preparing Alembic configuration for programmatic upgrade...")
        #     alembic_cfg = Config()
        #     # Assuming alembic.ini is in the root of the project, and this script is in a subfolder.
        #     # Adjust "bot/alembic" if script_location is different relative to project root
        #     # where alembic.ini is expected or where alembic commands are typically run from.
        #     # For many projects, alembic.ini is in the root, and script_location points to the alembic scripts directory.
        #     # If alembic.ini is *inside* 'bot/alembic', then config_file_name should be set.
        #     # Let's assume script_location is 'bot/alembic' and alembic.ini is not explicitly loaded here,
        #     # relying on defaults or that script_location implies enough.
        #     # A common practice is to have alembic.ini in the repo root.
        #     # If so, script_location should point to the directory with env.py
        #     alembic_cfg.set_main_option("script_location", "bot/alembic") # Path to the alembic environment directory
        #
        #     alembic_cfg.set_main_option("sqlalchemy.url", PG_URL_FOR_ALEMBIC)
        #
        #     print(f"GameManager: Running alembic.command.upgrade('head') for URL: {PG_URL_FOR_ALEMBIC} using script location: bot/alembic")
        #
        #     # Run synchronous Alembic command in a separate thread
        #     await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        #
        #     print("GameManager: Alembic upgrade via command.upgrade completed successfully.")
        # except Exception as e:
        #     print(f"GameManager: ❌ ERROR running alembic.command.upgrade: {e}")
        #     sio = io.StringIO() # Ensure io is imported
        #     traceback.print_exc(file=sio)
        #     print(sio.getvalue())
        #     # Consider re-raising or specific error handling

        # This might be redundant if alembic handles all table creation,
        # or could be for other non-schema initializations.
        # Ensure initialize_database is still called if it does more than schema creation.
        # If it's purely for schema (which Alembic now handles), it might be removable.
        # For now, keeping it to be safe, assuming it might do other setup.
        await self.db_service.initialize_database()
        # self._db_adapter = self.db_service.adapter # Removed, GameManager holds db_service instance
        print("GameManager: DBService initialized post-Alembic.")

    async def _initialize_core_managers_and_services(self):
        print("GameManager: Initializing core managers and services...")
        from bot.game.rules.rule_engine import RuleEngine
        from bot.game.managers.time_manager import TimeManager
        from bot.game.managers.location_manager import LocationManager
        from bot.game.managers.event_manager import EventManager
        from bot.game.managers.character_manager import CharacterManager
        from bot.services.openai_service import OpenAIService

        # Load or initialize RulesConfig first as RuleEngine might depend on it
        await self._load_or_initialize_rules_config()
        self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}), rules_data=self._rules_config_cache)

        self.time_manager = TimeManager(db_service=self.db_service, settings=self._settings.get('time_settings', {})) # Changed
        self.location_manager = LocationManager(db_service=self.db_service, settings=self._settings) # Changed

        try:
            oset = self._settings.get('openai_settings', {})
            self.openai_service = OpenAIService(
                api_key=oset.get('api_key'), model=oset.get('model'), default_max_tokens=oset.get('default_max_tokens')
            )
            if not self.openai_service.is_available(): self.openai_service = None
        except Exception as e: self.openai_service = None; print(f"GameManager: Warn: Failed OpenAIService init ({e})")

        self.event_manager = EventManager(db_service=self.db_service, settings=self._settings.get('event_settings', {}), openai_service=self.openai_service) # Changed
        self.character_manager = CharacterManager(db_service=self.db_service, settings=self._settings.get('character_settings', {}), location_manager=self.location_manager, rule_engine=self.rule_engine) # Changed
        print("GameManager: Core managers and OpenAI service initialized.")

    async def _initialize_dependent_managers(self):
        print("GameManager: Initializing dependent managers...")
        from bot.game.managers.item_manager import ItemManager
        from bot.game.managers.status_manager import StatusManager
        from bot.game.managers.combat_manager import CombatManager
        from bot.game.managers.crafting_manager import CraftingManager
        from bot.game.managers.economy_manager import EconomyManager
        from bot.game.managers.npc_manager import NpcManager
        from bot.game.managers.party_manager import PartyManager
        from bot.game.managers.ability_manager import AbilityManager
        from bot.game.managers.spell_manager import SpellManager
        from bot.game.managers.game_log_manager import GameLogManager
        from bot.game.managers.relationship_manager import RelationshipManager
        from bot.game.services.campaign_loader import CampaignLoader
        from bot.game.managers.dialogue_manager import DialogueManager
        from bot.game.services.consequence_processor import ConsequenceProcessor
        from bot.game.managers.quest_manager import QuestManager
        from bot.services.nlu_data_service import NLUDataService
        from bot.game.managers.lore_manager import LoreManager

        self.item_manager = ItemManager(db_service=self.db_service, settings=self._settings, location_manager=self.location_manager, rule_engine=self.rule_engine) # Changed
        self.status_manager = StatusManager(db_service=self.db_service, settings=self._settings, rule_engine=self.rule_engine, time_manager=self.time_manager) # Changed
        self.combat_manager = CombatManager(db_service=self.db_service, settings=self._settings.get('combat_settings', {}), rule_engine=self.rule_engine, character_manager=self.character_manager, status_manager=self.status_manager, item_manager=self.item_manager) # Changed
        self.crafting_manager = CraftingManager(db_service=self.db_service, settings=self._settings, item_manager=self.item_manager, character_manager=self.character_manager, time_manager=self.time_manager, rule_engine=self.rule_engine) # Changed
        self.economy_manager = EconomyManager(db_service=self.db_service, settings=self._settings.get('economy_settings', {}), item_manager=self.item_manager, location_manager=self.location_manager, character_manager=self.character_manager, rule_engine=self.rule_engine, time_manager=self.time_manager) # Changed

        # Initialize CampaignLoader before NpcManager if not already done
        if not hasattr(self, 'campaign_loader') or self.campaign_loader is None:
            self.campaign_loader = CampaignLoader(settings=self._settings, db_service=self.db_service)
            print("GameManager: Initialized CampaignLoader directly before NpcManager.")

        # Load NPC archetypes from campaign to pass to NpcManager
        npc_archetypes_from_campaign = []
        if self.campaign_loader:
            # Assuming load_campaign_data_from_source() is the method to get all data for a campaign.
            # This might need adjustment based on actual CampaignLoader methods.
            # For simplicity, using a default campaign or a specific one if defined in settings.
            campaign_identifier = self._settings.get('default_campaign_identifier') # Or some other logic
            default_campaign_data = await self.campaign_loader.load_campaign_data_from_source(campaign_identifier=campaign_identifier)
            if default_campaign_data and isinstance(default_campaign_data.get('npc_archetypes'), list):
                npc_archetypes_from_campaign = default_campaign_data['npc_archetypes']
                print(f"GameManager: Loaded {len(npc_archetypes_from_campaign)} NPC archetypes from campaign '{campaign_identifier or 'default'}'.")
            else:
                print(f"GameManager: Warning - Could not load NPC archetypes from campaign '{campaign_identifier or 'default'}'. Using empty list.")
        else:
            print("GameManager: Warning - CampaignLoader not available. NPC archetypes will be empty for NpcManager.")

        # Prepare NpcManager settings, ensuring 'npc_archetypes' key is present
        npc_manager_settings = self._settings.get('npc_settings', {}).copy() # Start with existing npc_settings
        npc_manager_settings['npc_archetypes'] = npc_archetypes_from_campaign # Add/overwrite with loaded archetypes

        self.npc_manager = NpcManager(
            db_service=self.db_service,
            settings=npc_manager_settings, # Pass the combined settings
            item_manager=self.item_manager,
            rule_engine=self.rule_engine,
            combat_manager=self.combat_manager,
            status_manager=self.status_manager,
            openai_service=self.openai_service,
            campaign_loader=self.campaign_loader # Pass campaign_loader instance
        )

        self.party_manager = PartyManager(db_service=self.db_service, settings=self._settings.get('party_settings', {}), character_manager=self.character_manager, npc_manager=self.npc_manager) # Changed
        self.ability_manager = AbilityManager(db_service=self.db_service, settings=self._settings.get('ability_settings', {}), character_manager=self.character_manager, rule_engine=self.rule_engine, status_manager=self.status_manager) # Changed
        self.spell_manager = SpellManager(db_service=self.db_service, settings=self._settings.get('spell_settings', {}), character_manager=self.character_manager, rule_engine=self.rule_engine, status_manager=self.status_manager) # Changed
        self.game_log_manager = GameLogManager(db_service=self.db_service, settings=self._settings.get('game_log_settings')) # Changed
        self.relationship_manager = RelationshipManager(db_service=self.db_service, settings=self._settings.get('relationship_settings')) # Changed
        # self.campaign_loader = CampaignLoader(settings=self._settings, db_service=self.db_service) # Moved up
        self.dialogue_manager = DialogueManager(db_service=self.db_service, settings=self._settings.get('dialogue_settings', {}), character_manager=self.character_manager, npc_manager=self.npc_manager, rule_engine=self.rule_engine, time_manager=self.time_manager, openai_service=self.openai_service, relationship_manager=self.relationship_manager) # Changed
        self.consequence_processor = ConsequenceProcessor(quest_manager=None, character_manager=self.character_manager, npc_manager=self.npc_manager, item_manager=self.item_manager, location_manager=self.location_manager, event_manager=self.event_manager, status_manager=self.status_manager, rule_engine=self.rule_engine, economy_manager=self.economy_manager, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager)
        self.quest_manager = QuestManager(db_service=self.db_service, settings=self._settings.get('quest_settings', {}), consequence_processor=self.consequence_processor, character_manager=self.character_manager, game_log_manager=self.game_log_manager, openai_service=self.openai_service) # Changed
        if self.consequence_processor: self.consequence_processor._quest_manager = self.quest_manager
        if self.db_service: self.nlu_data_service = NLUDataService(db_service=self.db_service) # Changed
        else: self.nlu_data_service = None
        self.lore_manager = LoreManager(settings=self._settings.get('lore_settings', {}), db_service=self.db_service) # Changed

        if self.character_manager:
            self.character_manager._status_manager = self.status_manager
            self.character_manager._party_manager = self.party_manager
            self.character_manager._combat_manager = self.combat_manager
            self.character_manager._dialogue_manager = self.dialogue_manager
            self.character_manager._relationship_manager = self.relationship_manager
            self.character_manager._game_log_manager = self.game_log_manager
        if self.npc_manager:
            self.npc_manager._dialogue_manager = self.dialogue_manager
            self.npc_manager._location_manager = self.location_manager
            self.npc_manager._game_log_manager = self.game_log_manager
        print("GameManager: Dependent managers initialized and cross-references set.")

    async def _initialize_processors_and_command_system(self):
        print("GameManager: Initializing processors and command system...")
        from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
        from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
        from bot.game.event_processors.event_stage_processor import EventStageProcessor
        from bot.game.event_processors.event_action_processor import EventActionProcessor
        from bot.game.character_processors.character_action_processor import CharacterActionProcessor
        from bot.game.character_processors.character_view_service import CharacterViewService
        from bot.game.party_processors.party_action_processor import PartyActionProcessor
        from bot.game.command_handlers.party_handler import PartyCommandHandler
        from bot.game.conflict_resolver import ConflictResolver
        from bot.game.managers.persistence_manager import PersistenceManager
        from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
        from bot.game.command_router import CommandRouter
        # TurnProcessingService is imported at the top level

        self._on_enter_action_executor = OnEnterActionExecutor(npc_manager=self.npc_manager, item_manager=self.item_manager, combat_manager=self.combat_manager, status_manager=self.status_manager)
        self._stage_description_generator = StageDescriptionGenerator(openai_service=self.openai_service)
        self._event_stage_processor = EventStageProcessor(on_enter_action_executor=self._on_enter_action_executor, stage_description_generator=self._stage_description_generator, character_manager=self.character_manager, loc_manager=self.location_manager, rule_engine=self.rule_engine, npc_manager=self.npc_manager, combat_manager=self.combat_manager, item_manager=self.item_manager, time_manager=self.time_manager, status_manager=self.status_manager, party_manager=self.party_manager)
        self._event_action_processor = EventActionProcessor(event_stage_processor=self._event_stage_processor, event_manager=self.event_manager, character_manager=self.character_manager, loc_manager=self.location_manager, rule_engine=self.rule_engine, openai_service=self.openai_service, npc_manager=self.npc_manager, combat_manager=self.combat_manager, item_manager=self.item_manager, time_manager=self.time_manager, status_manager=self.status_manager, send_callback_factory=self._get_discord_send_callback, dialogue_manager=self.dialogue_manager, crafting_manager=self.crafting_manager, on_enter_action_executor=self._on_enter_action_executor, stage_description_generator=self._stage_description_generator)
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
            event_action_processor=self._event_action_processor,
            game_log_manager=self.game_log_manager,
            openai_service=self.openai_service,
            event_manager=self.event_manager
        )
        self._character_view_service = CharacterViewService(character_manager=self.character_manager, item_manager=self.item_manager, location_manager=self.location_manager, rule_engine=self.rule_engine, status_manager=self.status_manager, party_manager=self.party_manager)
        self._party_action_processor = PartyActionProcessor(party_manager=self.party_manager, send_callback_factory=self._get_discord_send_callback, rule_engine=self.rule_engine, location_manager=self.location_manager, character_manager=self.character_manager, npc_manager=self.npc_manager, time_manager=self.time_manager, combat_manager=self.combat_manager, event_stage_processor=self._event_stage_processor)
        if self.party_manager is None: self._party_action_processor = None

        self.conflict_resolver = ConflictResolver(rule_engine=self.rule_engine, rules_config_data=self._rules_config_cache, notification_service="PlaceholderNotificationService", db_service=self.db_service, game_log_manager=self.game_log_manager) # Changed
        if self.character_manager and self.party_manager and self._party_action_processor:
            self._party_command_handler = PartyCommandHandler(character_manager=self.character_manager, party_manager=self.party_manager, party_action_processor=self._party_action_processor, settings=self._settings, npc_manager=self.npc_manager)
        else: self._party_command_handler = None

        if self.db_service: # Changed
            self._persistence_manager = PersistenceManager(db_service=self.db_service, event_manager=self.event_manager, character_manager=self.character_manager, location_manager=self.location_manager, npc_manager=self.npc_manager, combat_manager=self.combat_manager, item_manager=self.item_manager, time_manager=self.time_manager, status_manager=self.status_manager, crafting_manager=self.crafting_manager, economy_manager=self.economy_manager, party_manager=self.party_manager) # Changed
        else: self._persistence_manager = None

        self._world_simulation_processor = WorldSimulationProcessor(event_manager=self.event_manager, character_manager=self.character_manager, location_manager=self.location_manager, rule_engine=self.rule_engine, openai_service=self.openai_service, event_stage_processor=self._event_stage_processor, event_action_processor=self._event_action_processor, persistence_manager=self._persistence_manager, settings=self._settings, send_callback_factory=self._get_discord_send_callback, character_action_processor=self._character_action_processor, party_action_processor=self._party_action_processor, npc_manager=self.npc_manager, combat_manager=self.combat_manager, item_manager=self.item_manager, time_manager=self.time_manager, status_manager=self.status_manager, crafting_manager=self.crafting_manager, economy_manager=self.economy_manager, dialogue_manager=self.dialogue_manager, quest_manager=self.quest_manager, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager, multilingual_prompt_generator=self.multilingual_prompt_generator)

        if self._party_command_handler:
            self._command_router = CommandRouter(character_manager=self.character_manager, event_manager=self.event_manager, event_action_processor=self._event_action_processor, event_stage_processor=self._event_stage_processor, persistence_manager=self._persistence_manager, settings=self._settings, world_simulation_processor=self._world_simulation_processor, send_callback_factory=self._get_discord_send_callback, character_action_processor=self._character_action_processor, character_view_service=self._character_view_service, party_action_processor=self._party_action_processor, location_manager=self.location_manager, rule_engine=self.rule_engine, openai_service=self.openai_service, item_manager=self.item_manager, npc_manager=self.npc_manager, combat_manager=self.combat_manager, time_manager=self.time_manager, status_manager=self.status_manager, party_manager=self.party_manager, crafting_manager=self.crafting_manager, economy_manager=self.economy_manager, party_command_handler=self._party_command_handler, conflict_resolver=self.conflict_resolver, game_manager=self, quest_manager=self.quest_manager, dialogue_manager=self.dialogue_manager, relationship_manager=self.relationship_manager, game_log_manager=self.game_log_manager)
        else: self._command_router = None
        print("GameManager: Processors and command system initialized.")

    async def _load_initial_data_and_state(self):
        print("GameManager: Loading initial game data and state...")
        if self.campaign_loader:
            if self._active_guild_ids:
                for guild_id_str in self._active_guild_ids:
                    await self.campaign_loader.populate_all_game_data(guild_id=guild_id_str, campaign_identifier=None)
            else: await self.campaign_loader.load_and_populate_items()

        if self._persistence_manager:
            load_context_kwargs = {k: getattr(self, k, None) for k in ['rule_engine', 'time_manager', 'location_manager', 'event_manager', 'character_manager', 'item_manager', 'status_manager', 'combat_manager', 'crafting_manager', 'economy_manager', 'npc_manager', 'party_manager', 'openai_service', 'quest_manager', 'relationship_manager', 'dialogue_manager', 'game_log_manager', 'lore_manager', 'campaign_loader', 'consequence_processor', '_on_enter_action_executor', '_stage_description_generator', '_event_stage_processor', '_event_action_processor', '_character_action_processor', '_character_view_service', '_party_action_processor', '_persistence_manager', '_world_simulation_processor', 'conflict_resolver', 'db_service', 'nlu_data_service', 'ability_manager', 'spell_manager', 'prompt_context_collector', 'multilingual_prompt_generator']} # Removed _db_adapter
            load_context_kwargs.update({'send_callback_factory': self._get_discord_send_callback, 'settings': self._settings, 'discord_client': self._discord_client})
            await self._persistence_manager.load_game_state(guild_ids=self._active_guild_ids, **load_context_kwargs)
        print("GameManager: Initial data and game state loaded.")

    async def _initialize_ai_content_services(self):
        print("GameManager: Initializing AI content generation services...")
        from bot.ai.prompt_context_collector import PromptContextCollector
        from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
        if all([self.character_manager, self.npc_manager, self.quest_manager, self.relationship_manager, self.item_manager, self.location_manager, self.event_manager, self.ability_manager, self.spell_manager]):
            self.prompt_context_collector = PromptContextCollector(settings=self._settings, character_manager=self.character_manager, npc_manager=self.npc_manager, quest_manager=self.quest_manager, relationship_manager=self.relationship_manager, item_manager=self.item_manager, location_manager=self.location_manager, ability_manager=self.ability_manager, spell_manager=self.spell_manager, event_manager=self.event_manager)
            main_bot_language = self.get_default_bot_language()
            self.multilingual_prompt_generator = MultilingualPromptGenerator(context_collector=self.prompt_context_collector, main_bot_language=main_bot_language)
            if self.npc_manager and hasattr(self.npc_manager, '_multilingual_prompt_generator'): self.npc_manager._multilingual_prompt_generator = self.multilingual_prompt_generator
            if self.quest_manager and hasattr(self.quest_manager, '_multilingual_prompt_generator'): self.quest_manager._multilingual_prompt_generator = self.multilingual_prompt_generator
            if self.event_manager and hasattr(self.event_manager, '_multilingual_prompt_generator'): self.event_manager._multilingual_prompt_generator = self.multilingual_prompt_generator
            if self._world_simulation_processor and hasattr(self._world_simulation_processor, 'multilingual_prompt_generator'): self._world_simulation_processor.multilingual_prompt_generator = self.multilingual_prompt_generator
        else: self.prompt_context_collector = None; self.multilingual_prompt_generator = None; print("GameManager: Warn: AI prompt services not fully inited due to missing managers.")
        print("GameManager: AI content services initialized.")

    async def _start_background_tasks(self):
        print("GameManager: Starting background tasks...")
        if self._world_simulation_processor:
            self._world_tick_task = asyncio.create_task(self._world_tick_loop())
            print("GameManager: World tick loop started.")
        else: print("GameManager: Warn: World tick loop not started, WSP unavailable.")
        print("GameManager: Background tasks started.")

    async def setup(self) -> None:
        print("GameManager: Running setup…")
        try:
            await self._initialize_database()
            await self._initialize_core_managers_and_services()
            await self._initialize_dependent_managers()
            await self._initialize_processors_and_command_system()
            await self._load_initial_data_and_state()
            await self._initialize_ai_content_services()
            await self._start_background_tasks()
            print("GameManager: Setup complete.")
        except Exception as e:
            # Check if the error is a database connection error
            is_db_connection_error = isinstance(e, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError))
            if hasattr(e, '__cause__') and isinstance(e.__cause__, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError)):
                is_db_connection_error = True

            if is_db_connection_error:
                print("\n" + "="*80)
                print("GameManager: ❌ CRITICAL: Failed to establish database connection.")
                print("The bot cannot start without a valid database connection.")
                print("Please check the database server status and the `DATABASE_URL` environment variable.")
                print(f"Specific error details: {e}")
                print("="*80 + "\n")
            else:
                print(f"GameManager: ❌ CRITICAL ERROR during setup: {e}")

            traceback.print_exc()
            try:
                print("GameManager: Attempting graceful shutdown due to setup failure...")
                await self.shutdown()
            except Exception as shutdown_e:
                print(f"GameManager: ❌ Error during shutdown from setup failure: {shutdown_e}")
                traceback.print_exc() # Also print traceback for shutdown error
            raise

    async def handle_discord_message(self, message: "Message") -> None:
        if message.author.bot:
            return
        if not self._command_router:
            print(f"GameManager: Warning: CommandRouter not available, message '{message.content}' dropped.")
            if message.channel:
                try:
                     send_callback = self._get_discord_send_callback(message.channel.id)
                     await send_callback(f"❌ Игра еще не полностью запущена. Попробуйте позже.", None)
                except Exception as cb_e:
                     print(f"GameManager: Error sending startup error message back to channel {message.channel.id}: {cb_e}")
            return

        command_prefix = self._settings.get('command_prefix', '/')
        if message.content.startswith(command_prefix):
             print(f"GameManager: Passing command from {message.author.name} (ID: {message.author.id}, Guild: {message.guild.id if message.guild else 'DM'}, Channel: {message.channel.id}) to CommandRouter: '{message.content}'")
        else:
             pass

        try:
            await self._command_router.route(message)
        except Exception as e:
            print(f"GameManager: Error handling message '{message.content}': {e}")
            traceback.print_exc()
            try:
                 if message.channel:
                      send_callback = self._get_discord_send_callback(message.channel.id)
                      await send_callback(f"❌ Произошла внутренняя ошибка при обработке команды. Подробности в логах бота.", None)
                 else:
                      print(f"GameManager: Warning: Cannot send error message to user (DM channel or channel not found).")
            except Exception as cb_e:
                 print(f"GameManager: Error sending generic internal error message back to channel {message.channel.id}: {cb_e}")


    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback:
        channel_id_int = int(channel_id)

        async def _send(content: str = "", **kwargs: Any) -> None:
            channel = self._discord_client.get_channel(channel_id_int)
            if channel:
                if isinstance(channel, discord.abc.Messageable):
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
                await asyncio.sleep(self._tick_interval_seconds)

                if self._world_simulation_processor:
                    try:
                        tick_context_kwargs: Dict[str, Any] = {
                            'rule_engine': self.rule_engine, 'time_manager': self.time_manager,
                            'location_manager': self.location_manager, 'event_manager': self.event_manager,
                            'character_manager': self.character_manager, 'item_manager': self.item_manager,
                            'status_manager': self.status_manager, 'combat_manager': self.combat_manager,
                            'crafting_manager': self.crafting_manager, 'economy_manager': self.economy_manager,
                            'npc_manager': self.npc_manager, 'party_manager': self.party_manager,
                            'openai_service': self.openai_service,
                            'quest_manager': self.quest_manager,
                            'relationship_manager': self.relationship_manager,
                            'dialogue_manager': self.dialogue_manager,
                            'game_log_manager': self.game_log_manager,
                            'lore_manager': self.lore_manager,
                            'consequence_processor': self.consequence_processor,
                            'campaign_loader': self.campaign_loader,
                            'on_enter_action_executor': self._on_enter_action_executor,
                            'stage_description_generator': self._stage_description_generator,
                            'event_stage_processor': self._event_stage_processor,
                            'event_action_processor': self._event_action_processor,
                            'character_action_processor': self._character_action_processor,
                            'character_view_service': self._character_view_service,
                            'party_action_processor': self._party_action_processor,
                            'persistence_manager': self._persistence_manager,
                            'conflict_resolver': self.conflict_resolver,
                            'db_service': self.db_service, # Changed
                            'nlu_data_service': self.nlu_data_service,
                            'prompt_context_collector': self.prompt_context_collector,
                            'multilingual_prompt_generator': self.multilingual_prompt_generator,
                            'send_callback_factory': self._get_discord_send_callback,
                            'settings': self._settings,
                            'discord_client': self._discord_client,
                        }
                        await self._world_simulation_processor.process_world_tick(
                            game_time_delta=self._tick_interval_seconds,
                            **tick_context_kwargs
                        )
                    except Exception as e:
                        print(f"GameManager: ❌ Error during world simulation tick: {e}")
                        traceback.print_exc()

                # --- Player Turn Processing (after WSP tick) ---
                if self.turn_processing_service and self.character_manager:
                    for guild_id_str in self._active_guild_ids: # Assuming _active_guild_ids holds strings
                        try:
                            # Identify players ready for turn processing in this guild
                            # get_all_characters is synchronous as per CharacterManager definition
                            all_chars_in_guild = self.character_manager.get_all_characters(guild_id_str)

                            players_with_actions: List[str] = []
                            if all_chars_in_guild: # Ensure the list is not None or empty
                                for char_obj in all_chars_in_guild:
                                    if char_obj and char_obj.collected_actions_json: # Check if there are actions to process
                                        players_with_actions.append(char_obj.id)

                            if players_with_actions:
                                print(f"GameManager (Tick): Found {len(players_with_actions)} players with actions in guild {guild_id_str}. Processing turns...")
                                if self.game_log_manager:
                                    await self.game_log_manager.log_event(
                                        guild_id=guild_id_str,
                                        event_type="gm_turn_processing_batch_start",
                                        message=f"Starting turn processing for {len(players_with_actions)} players.",
                                        metadata={"player_ids": players_with_actions}
                                    )

                                turn_results = await self.turn_processing_service.process_player_turns(
                                    player_ids=players_with_actions,
                                    guild_id=guild_id_str
                                )

                                # Log summary and feedback
                                print(f"GameManager (Tick): Turn processing completed for guild {guild_id_str}. Status: {turn_results.get('status')}")
                                if self.game_log_manager:
                                     await self.game_log_manager.log_event(
                                        guild_id=guild_id_str,
                                        event_type="gm_turn_processing_batch_end",
                                        message=f"Turn processing finished for guild {guild_id_str}. Status: {turn_results.get('status')}.",
                                        metadata={"results_summary": turn_results.get('status'), "num_players_processed": len(players_with_actions)}
                                    )

                                feedback_map = turn_results.get('feedback_per_player', {})
                                if feedback_map:
                                    for p_id, feedback_list in feedback_map.items():
                                        if feedback_list:
                                            feedback_summary = '; '.join(feedback_list)
                                            print(f"GameManager (Tick Feedback for {p_id} in {guild_id_str}): {feedback_summary}")
                                            if self.game_log_manager:
                                                await self.game_log_manager.log_event(
                                                    guild_id=guild_id_str,
                                                    event_type="player_turn_feedback_logged", # Renamed for clarity
                                                    message=f"Raw feedback for player {p_id}: {feedback_summary}",
                                                    related_entities=[{"id": p_id, "type": "Character"}],
                                                    metadata={"feedback_list": feedback_list} # Log the list itself
                                                )

                                            # DM Delivery
                                            player_char_obj = await self.character_manager.get_character(guild_id_str, p_id)
                                            if player_char_obj and player_char_obj.discord_user_id:
                                                try:
                                                    # Ensure discord_user_id is an int
                                                    discord_user_id_int = int(player_char_obj.discord_user_id)
                                                    discord_user = await self._discord_client.fetch_user(discord_user_id_int)

                                                    if discord_user:
                                                        dm_channel = discord_user.dm_channel or await discord_user.create_dm()
                                                        # Prepend a title to the feedback
                                                        dm_report_title = "**Game Update / Your Turn Report:**"
                                                        full_dm_message = f"{dm_report_title}\n- " + "\n- ".join(feedback_list)

                                                        max_len = 1980 # Discord limit is 2000, leave some room for title and formatting

                                                        if len(full_dm_message) > max_len:
                                                            messages_to_send = []
                                                            current_part = dm_report_title + "\n"
                                                            for entry in feedback_list:
                                                                entry_line = "- " + entry + "\n"
                                                                if len(current_part) + len(entry_line) > max_len:
                                                                    messages_to_send.append(current_part)
                                                                    current_part = dm_report_title + " (continued)\n" + entry_line
                                                                else:
                                                                    current_part += entry_line
                                                            if current_part.strip() != dm_report_title + " (continued)": # Add last part if it has content
                                                                messages_to_send.append(current_part)

                                                            for i, part_msg in enumerate(messages_to_send):
                                                                await dm_channel.send(part_msg)
                                                                if self.game_log_manager:
                                                                    await self.game_log_manager.log_event(guild_id_str, "player_turn_feedback_dm_sent_part", f"Sent DM part {i+1}/{len(messages_to_send)} to {p_id}", metadata={"char_id": p_id})
                                                        elif full_dm_message.strip() and full_dm_message.strip() != dm_report_title: # Send only if not empty after join
                                                             await dm_channel.send(full_dm_message)
                                                             if self.game_log_manager:
                                                                await self.game_log_manager.log_event(guild_id_str, "player_turn_feedback_dm_sent", f"Sent DM to {p_id}", metadata={"char_id": p_id})

                                                        print(f"GameManager (Tick): Sent DM feedback to user {discord_user_id_int} for character {p_id}.")
                                                    else:
                                                        print(f"GameManager (Tick): Could not fetch discord user for ID {discord_user_id_int} (character {p_id}).")
                                                        if self.game_log_manager:
                                                            await self.game_log_manager.log_event(guild_id_str, "player_turn_feedback_dm_error", f"Discord user {discord_user_id_int} not found for char {p_id}.", metadata={"char_id": p_id})
                                                except discord.Forbidden:
                                                    print(f"GameManager (Tick): Cannot send DM to user {player_char_obj.discord_user_id} (character {p_id}) - DMs might be disabled or bot blocked.")
                                                    if self.game_log_manager:
                                                        await self.game_log_manager.log_event(guild_id_str, "player_turn_feedback_dm_forbidden", f"DM forbidden for char {p_id}.", metadata={"char_id": p_id})
                                                except Exception as dm_e:
                                                    print(f"GameManager (Tick): Error sending DM feedback to character {p_id}: {dm_e}")
                                                    traceback.print_exc()
                                                    if self.game_log_manager:
                                                        await self.game_log_manager.log_event(guild_id_str, "player_turn_feedback_dm_exception", f"Exception sending DM to {p_id}: {str(dm_e)}", metadata={"char_id": p_id, "error": str(dm_e)})
                                            elif player_char_obj: # Character found but no discord_user_id
                                                print(f"GameManager (Tick): Character {p_id} found, but missing discord_user_id. Cannot send DM.")
                                                if self.game_log_manager:
                                                    await self.game_log_manager.log_event(guild_id_str, "player_turn_feedback_dm_error", f"Char {p_id} missing discord_user_id.", metadata={"char_id": p_id})
                                            # else: Character object not found - this case should ideally be rare if players_with_actions had the ID
                            # else:
                            #    print(f"GameManager (Tick): No players with pending actions found in guild {guild_id_str} for turn processing.")

                        except Exception as tps_e:
                            print(f"GameManager (Tick): Error during TurnProcessingService call or subsequent handling for guild {guild_id_str}: {tps_e}")
                            traceback.print_exc()
                            if self.game_log_manager:
                                await self.game_log_manager.log_event(
                                    guild_id=guild_id_str,
                                    event_type="gm_turn_processing_error",
                                    message=f"Error in turn processing logic: {str(tps_e)}",
                                    metadata={"error": traceback.format_exc()}
                                )
                # else:
                #    if not self.turn_processing_service: print("GameManager (Tick): TurnProcessingService not available.")
                #    if not self.character_manager: print("GameManager (Tick): CharacterManager not available.")
                #    print("GameManager (Tick): Skipping player turn processing phase.")


        except asyncio.CancelledError:
            print("GameManager: World tick loop cancelled.")
        except Exception as e:
            print(f"GameManager: ❌ Critical error in world tick loop: {e}")
            traceback.print_exc()

    async def save_game_state_after_action(self, guild_id: str) -> None:
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
                'ability_manager': self.ability_manager,
                'spell_manager': self.spell_manager,
                'conflict_resolver': self.conflict_resolver,
                'prompt_context_collector': self.prompt_context_collector,
                'multilingual_prompt_generator': self.multilingual_prompt_generator,
                'db_service': self.db_service, # Changed
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
                    'lore_manager': self.lore_manager,
                    'ability_manager': self.ability_manager,
                    'spell_manager': self.spell_manager,
                    'conflict_resolver': self.conflict_resolver,
                    'prompt_context_collector': self.prompt_context_collector,
                    'multilingual_prompt_generator': self.multilingual_prompt_generator,
                    'db_service': self.db_service, # Changed
                    'send_callback_factory': self._get_discord_send_callback,
                    'settings': self._settings,
                    'discord_client': self._discord_client,
                }
                if self.db_service: # Changed
                    await self._persistence_manager.save_game_state(
                        guild_ids=active_guild_ids,
                        **save_context_kwargs
                    )
                    print("GameManager: Game state saved on shutdown.")
                else:
                     print("GameManager: Warning: Skipping state save on shutdown, DB service is None.") # Changed

            except Exception as e:
                print(f"GameManager: ❌ Error saving game state on shutdown: {e}")
                traceback.print_exc()


        if self.db_service: # Changed
            try:
                await self.db_service.close() # Changed
                print("GameManager: Database connection closed.")
            except Exception as e:
                print(f"GameManager: ❌ Error closing database service: {e}") # Changed
                traceback.print_exc()

        print("GameManager: Shutdown complete.")

    async def get_player_by_discord_id(self, discord_id: int, guild_id: str) -> Optional[Character]:
        if not self.character_manager:
            print(f"GameManager: CharacterManager not available. Cannot get player by Discord ID {discord_id}.")
            return None
        
        try:
            player_obj_from_cm = self.character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_id)

            if player_obj_from_cm:
                if not isinstance(player_obj_from_cm, Character) and player_obj_from_cm is not None:
                    print(f"GameManager: Warning - CharacterManager.get_character_by_discord_id returned type {type(player_obj_from_cm)} instead of Character or None for discord_id {discord_id}.")
                return player_obj_from_cm
            else:
                return None
        except Exception as e:
            print(f"GameManager: Error calling get_character_by_discord_id for discord_id {discord_id}: {e}")
            traceback.print_exc()
            return None

    def get_default_bot_language(self) -> str:
        if self._rules_config_cache is None:
            print("GameManager: Warning - RulesConfig cache is not populated. Defaulting bot language to 'en'.")
            return "en"
        return self._rules_config_cache.get('default_bot_language', 'en')

    def get_max_party_size(self) -> int:
        default_size = 4
        if self._rules_config_cache is None:
            print("GameManager: Warning - RulesConfig cache is not populated. Defaulting max_party_size to 4.")
            return default_size

        party_rules = self._rules_config_cache.get('party_rules')
        if not isinstance(party_rules, dict):
            print(f"GameManager: Warning - 'party_rules' not found or not a dict in RulesConfig. Defaulting max_party_size to {default_size}.")
            return default_size

        max_size = party_rules.get('max_size')
        if not isinstance(max_size, int):
            print(f"GameManager: Warning - 'max_size' not found or not an int in party_rules. Defaulting max_party_size to {default_size}.")
            return default_size

        return max_size

    def get_action_cooldown(self, action_type: str) -> float:
        default_cooldown = 5.0
        if self._rules_config_cache is None:
            print(f"GameManager: Warning - RulesConfig cache is not populated. Defaulting cooldown for '{action_type}' to {default_cooldown}s.")
            return default_cooldown

        cooldown_rules = self._rules_config_cache.get('action_rules', {}).get('cooldowns')
        if not isinstance(cooldown_rules, dict):
            print(f"GameManager: Warning - 'action_rules.cooldowns' not found or not a dict in RulesConfig. Defaulting cooldown for '{action_type}' to {default_cooldown}s.")
            return default_cooldown

        cooldown = cooldown_rules.get(action_type)
        if not isinstance(cooldown, (float, int)):
            print(f"GameManager: Warning - Cooldown for '{action_type}' not found or not a number in action_rules.cooldowns. Defaulting to {default_cooldown}s.")
            return default_cooldown

        return float(cooldown)

    def get_game_channel_ids(self, guild_id: str) -> List[int]:
        if not self.location_manager:
            print(f"GameManager: LocationManager not available. Cannot get game channel IDs for guild {guild_id}.")
            return []

        guild_id_str = str(guild_id)
        
        try:
            if hasattr(self.location_manager, 'get_active_channel_ids_for_guild'):
                channel_ids = self.location_manager.get_active_channel_ids_for_guild(guild_id_str)
                if not isinstance(channel_ids, list):
                    print(f"GameManager: Warning - get_active_channel_ids_for_guild for guild {guild_id_str} did not return a list. Got {type(channel_ids)}. Returning empty list.")
                    return []
                valid_channel_ids = []
                for cid in channel_ids:
                    if isinstance(cid, int):
                        valid_channel_ids.append(cid)
                    else:
                        print(f"GameManager: Warning - LocationManager returned a non-integer channel ID '{cid}' for guild {guild_id_str}. Skipping.")
                return valid_channel_ids
            else:
                print(f"GameManager: LocationManager is missing the 'get_active_channel_ids_for_guild' method. Cannot get game channel IDs for guild {guild_id_str}.")
                return []
        except Exception as e:
            print(f"GameManager: Error calling get_active_channel_ids_for_guild for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return []

    async def set_default_bot_language(self, language: str, guild_id: Optional[str] = None) -> bool:
        if guild_id:
            print(f"GameManager (set_default_bot_language): Received guild_id '{guild_id}', but rules_config is currently global.")

        if self._rules_config_cache is None:
            print("GameManager: Error - RulesConfig cache is not populated. Cannot set default bot language.")
            return False

        if not self.db_service:
            print("GameManager: Error - DBService not available. Cannot save default bot language.")
            return False

        original_language = self._rules_config_cache.get('default_bot_language')
        self._rules_config_cache['default_bot_language'] = language

        try:
            success = await self.db_service.update_entity(
                'rules_config',
                DEFAULT_RULES_CONFIG_ID,
                {'config_data': json.dumps(self._rules_config_cache)}
            )
            if success:
                print(f"GameManager: Default bot language successfully updated to '{language}' and saved.")
                if self.multilingual_prompt_generator:
                    self.multilingual_prompt_generator.update_main_bot_language(language)
                    print("GameManager: Updated main_bot_language in MultilingualPromptGenerator.")
                return True
            else:
                print(f"GameManager: Failed to save default bot language update to database. Reverting cache.")
                if original_language is not None:
                    self._rules_config_cache['default_bot_language'] = original_language
                else:
                    if 'default_bot_language' in self._rules_config_cache and language == self._rules_config_cache['default_bot_language']:
                         del self._rules_config_cache['default_bot_language']
                return False
        except Exception as e:
            print(f"GameManager: Exception while saving default bot language: {e}. Reverting cache.")
            traceback.print_exc()
            if original_language is not None:
                self._rules_config_cache['default_bot_language'] = original_language
            else:
                if 'default_bot_language' in self._rules_config_cache and language == self._rules_config_cache['default_bot_language']:
                    del self._rules_config_cache['default_bot_language']
            return False

    async def trigger_manual_simulation_tick(self, server_id: int) -> None:
        print(f"GameManager: Manual simulation tick triggered for server_id: {server_id}.")

        if not self._world_simulation_processor:
            print("GameManager: Warning - WorldSimulationProcessor not available. Cannot trigger manual tick.")
            return

        if not self.time_manager:
            print("GameManager: Warning - TimeManager not available. Cannot determine game_time_delta for manual tick.")
            game_time_delta = 0.0
        else:
            game_time_delta = 0.0
            print(f"GameManager: Using game_time_delta: {game_time_delta} for manual tick.")

        try:
            tick_context_kwargs: Dict[str, Any] = {
                'rule_engine': self.rule_engine, 'time_manager': self.time_manager,
                'location_manager': self.location_manager, 'event_manager': self.event_manager,
                'character_manager': self.character_manager, 'item_manager': self.item_manager,
                'status_manager': self.status_manager, 'combat_manager': self.combat_manager,
                'crafting_manager': self.crafting_manager, 'economy_manager': self.economy_manager,
                'npc_manager': self.npc_manager, 'party_manager': self.party_manager,
                'openai_service': self.openai_service,
                'quest_manager': self.quest_manager,
                'relationship_manager': self.relationship_manager,
                'dialogue_manager': self.dialogue_manager,
                'game_log_manager': self.game_log_manager,
                'lore_manager': self.lore_manager,
                'consequence_processor': self.consequence_processor,
                'campaign_loader': self.campaign_loader,
                'on_enter_action_executor': self._on_enter_action_executor,
                'stage_description_generator': self._stage_description_generator,
                'event_stage_processor': self._event_stage_processor,
                'event_action_processor': self._event_action_processor,
                'character_action_processor': self._character_action_processor,
                'character_view_service': self._character_view_service,
                'party_action_processor': self._party_action_processor,
                'persistence_manager': self._persistence_manager,
                'conflict_resolver': self.conflict_resolver,
                'db_service': self.db_service, # Changed
                'nlu_data_service': self.nlu_data_service,
                'prompt_context_collector': self.prompt_context_collector,
                'multilingual_prompt_generator': self.multilingual_prompt_generator,
                'send_callback_factory': self._get_discord_send_callback,
                'settings': self._settings,
                'discord_client': self._discord_client,
            }
            print(f"GameManager: Executing manual process_world_tick for server_id: {server_id}...")
            await self._world_simulation_processor.process_world_tick(
                game_time_delta=game_time_delta,
                **tick_context_kwargs
            )
            print(f"GameManager: Manual simulation tick completed for server_id: {server_id}.")
        except Exception as e:
            print(f"GameManager: ❌ Error during manual simulation tick for server_id {server_id}: {e}")
            traceback.print_exc()

    async def start_new_character_session(self, user_id: int, guild_id: str, character_name: str) -> Optional["Character"]:
        """
        Initiates a new character for a user in a guild.
        This might involve just creating the character or setting up an initial session state.
        For now, it primarily delegates to CharacterManager.create_character.
        """
        print(f"GameManager: Attempting to start new character session for user {user_id} in guild {guild_id} with name {character_name}.")
        if not self.character_manager:
            print("GameManager: CharacterManager not available. Cannot start new character session.")
            return None

        # print(f"GameManager: Starting new character session for user {user_id} in guild {guild_id} with name {character_name}") # Original log, now covered by the one above
        try:
            # import traceback # Already imported at the top of the file
            character = await self.character_manager.create_character(
                discord_id=user_id,
                name=character_name,
                guild_id=guild_id
                # Other parameters like initial_location_id, stats, etc.,
                # are handled by CharacterManager.create_character using its defaults or settings.
            )
            if character:
                # Safely access attributes for logging
                char_id_log = getattr(character, 'id', "N/A")
                char_name_log = getattr(character, 'name', "N/A")
                char_loc_id_log = getattr(character, 'location_id', "N/A") # or current_location_id depending on model
                print(f"GameManager: Successfully started new character session. Character ID: {char_id_log}, Name: {char_name_log}, Location ID: {char_loc_id_log}.")
            else:
                print(f"GameManager: Failed to start new character session for user {user_id}, character creation failed.")
            return character
        except Exception as e:
            print(f"GameManager: Error in start_new_character_session for user {user_id}: {e}")
            traceback.print_exc()
            return None

print(f"DEBUG: Finished loading game_manager.py from: {__file__}")
