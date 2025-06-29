# bot/game/managers/game_manager.py

import asyncio
import json
import os
import logging
import uuid
from typing import Optional, Dict, Any, Callable, Awaitable, List, TYPE_CHECKING, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
# from asyncpg import exceptions as asyncpg_exceptions # Not directly used, can be removed if sqlalchemy handles all specific db exceptions

import discord
from discord import Client

from bot.services.db_service import DBService
from bot.game.models.character import Character
from bot.database.models import Player, GuildConfig
from bot.services.notification_service import NotificationService
from bot.game.managers.character_manager import CharacterManager
from bot.database.guild_transaction import GuildTransaction
from bot.services.ai_generation_service import AIGenerationService
from bot.game.managers.undo_manager import UndoManager
from bot.database.models import GenerationType as PendingGenerationTypeEnum # Corrected import

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
    from pydantic import ValidationError # For CoreGameRulesConfig validation
    # from bot.ai.rules_schema import CoreGameRulesConfig # Moved out of TYPE_CHECKING
from bot.ai.rules_schema import CoreGameRulesConfig # Ensure it's available at runtime

logger = logging.getLogger(__name__)

SendToChannelCallback = Callable[[str], Awaitable[Any]] # Simplified: takes message string
SendCallbackFactory = Callable[[int], SendToChannelCallback]


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
        self._tick_interval_seconds: float = float(self._settings.get('world_tick_interval_seconds', 60.0))
        self._active_guild_ids: List[str] = [str(gid) for gid in self._settings.get('active_guild_ids', []) if gid is not None]
        self.undo_manager: Optional[UndoManager] = None
        logger.info("GameManager initialized with attributes set to None.")

    async def _initialize_database(self):
        logger.info("GM: Init DB service...")
        self.db_service = DBService()
        await self.db_service.connect()
        if os.getenv("TESTING_MODE") == "true": logger.info("GM (TESTING_MODE): Skipping DB init.")
        elif os.getenv("MIGRATE_ON_INIT", "false").lower() == "true":
            logger.info("GM: MIGRATE_ON_INIT true, calling DBService.initialize_database().")
            if self.db_service and hasattr(self.db_service, 'initialize_database') and callable(getattr(self.db_service, 'initialize_database')):
                 await self.db_service.initialize_database()
            else: logger.error("DBService NA or initialize_database missing for MIGRATE_ON_INIT.")
        else: logger.info("GM: MIGRATE_ON_INIT false/not set & not TESTING_MODE. Skipping DB init.")
        logger.info("GM: DBService connection established & init logic (if any) completed.")

    async def _initialize_core_managers_and_services(self):
        logger.info("GM: Init core managers (RuleEngine, Time, Location, Event, OpenAI)...")
        from bot.game.rules.rule_engine import RuleEngine
        from bot.game.managers.time_manager import TimeManager
        from bot.game.managers.location_manager import LocationManager
        from bot.game.managers.event_manager import EventManager
        from bot.services.openai_service import OpenAIService

        if not self.db_service: raise RuntimeError("DBService NA for core managers.")
        db_s = cast(DBService, self.db_service)

        rules_data: Dict[str, Any] = {}
        if self._active_guild_ids:
            await self._load_or_initialize_rules_config(self._active_guild_ids[0])
            rules_data = self._rules_config_cache.get(self._active_guild_ids[0], {})
        else:
            logger.warning("GM: No active guilds for RuleEngine init. Using fallback."); rules_data = {"default_bot_language": "en", "emergency_mode": True}
            self._rules_config_cache["__fallback__"] = rules_data

        self.rule_engine = RuleEngine(settings=self._settings.get('rule_settings', {}), rules_data=rules_data, game_manager=self)
        self.time_manager = TimeManager(db_service=db_s, settings=self._settings.get('time_settings', {}))
        self.location_manager = LocationManager(db_service=db_s, settings=self._settings, game_manager=self)

        try:
            oset = self._settings.get('openai_settings', {})
            self.openai_service = OpenAIService(api_key=str(oset.get('api_key')), model=str(oset.get('model')), default_max_tokens=int(oset.get('default_max_tokens', 150)))
            if self.openai_service and not self.openai_service.is_available(): self.openai_service = None
        except Exception as e: self.openai_service = None; logger.warning(f"GM: Failed OpenAIService init: {e}", exc_info=True)

        if not self.location_manager : raise RuntimeError("LocationManager NA for EventManager.")
        loc_m = cast(LocationManager, self.location_manager)
        self.event_manager = EventManager(db_service=db_s, settings=self._settings.get('event_settings', {}), openai_service=self.openai_service, game_manager=self, location_manager=loc_m)
        logger.info("GM: Core managers & OpenAI service initialized.")

    async def _initialize_dependent_managers(self):
        logger.info("GM: Init dependent managers...")
        from bot.game.managers.item_manager import ItemManager; from bot.game.managers.status_manager import StatusManager; from bot.game.managers.npc_manager import NpcManager; from bot.game.managers.inventory_manager import InventoryManager; from bot.game.managers.equipment_manager import EquipmentManager; from bot.game.managers.combat_manager import CombatManager; from bot.game.managers.party_manager import PartyManager; from bot.game.managers.lore_manager import LoreManager; from bot.game.managers.game_log_manager import GameLogManager; from bot.game.services.campaign_loader import CampaignLoader; from bot.game.managers.faction_manager import FactionManager; from bot.game.managers.relationship_manager import RelationshipManager; from bot.game.managers.dialogue_manager import DialogueManager; from bot.game.managers.quest_manager import QuestManager; from bot.game.services.consequence_processor import ConsequenceProcessor; from bot.game.managers.ability_manager import AbilityManager; from bot.game.managers.spell_manager import SpellManager; from bot.game.managers.crafting_manager import CraftingManager; from bot.game.managers.economy_manager import EconomyManager

        deps = {"DBService": self.db_service, "RuleEngine": self.rule_engine, "LocationManager": self.location_manager, "TimeManager": self.time_manager, "EventManager": self.event_manager}
        for name, inst in deps.items():
            if not inst: raise RuntimeError(f"{name} NA for dependent managers.")

        db_s, rl_e, loc_m, time_m, evt_m = cast(DBService, deps["DBService"]), cast("RuleEngine", deps["RuleEngine"]), cast("LocationManager", deps["LocationManager"]), cast("TimeManager", deps["TimeManager"]), cast("EventManager", deps["EventManager"])

        self.item_manager = ItemManager(db_service=db_s, settings=self._settings, location_manager=loc_m, rule_engine=rl_e); item_m = cast(ItemManager, self.item_manager)
        self.status_manager = StatusManager(db_service=db_s, settings=self._settings.get('status_settings', {})); status_m = cast(StatusManager, self.status_manager)
        self.game_log_manager = GameLogManager(db_service=db_s); game_log_m = cast(GameLogManager, self.game_log_manager)
        self.lore_manager = LoreManager(settings=self._settings.get('lore_settings', {}), db_service=db_s);
        self.ability_manager = AbilityManager(db_service=db_s); self.spell_manager = SpellManager(db_service=db_s);
        self.crafting_manager = CraftingManager(db_service=db_s, item_manager=item_m); self.economy_manager = EconomyManager(db_service=db_s, item_manager=item_m, rule_engine=rl_e);
        self.campaign_loader = CampaignLoader(settings=self._settings, db_service=db_s); camp_loader = cast(CampaignLoader, self.campaign_loader)
        self.relationship_manager = RelationshipManager(db_service=db_s, settings=self._settings.get('relationship_settings', {})); rel_m = cast(RelationshipManager, self.relationship_manager)

        npc_sets = self._settings.get('npc_settings', {}).copy(); npc_sets['loaded_npc_archetypes_from_campaign'] = {} # Placeholder
        self.npc_manager = NpcManager(db_service=db_s, settings=npc_sets, item_manager=item_m, rule_engine=rl_e, combat_manager=None, status_manager=status_m, openai_service=self.openai_service, campaign_loader=camp_loader, game_manager=self); npc_m = cast(NpcManager, self.npc_manager)

        self.character_manager = CharacterManager(db_service=db_s, settings=self._settings, item_manager=item_m, location_manager=loc_m, rule_engine=rl_e, status_manager=status_m, party_manager=None, combat_manager=None, dialogue_manager=None, relationship_manager=rel_m, game_log_manager=game_log_m, npc_manager=npc_m, inventory_manager=None, equipment_manager=None, game_manager=self); char_m = cast(CharacterManager, self.character_manager)

        self.inventory_manager = InventoryManager(character_manager=char_m, item_manager=item_m, db_service=db_s); setattr(self.character_manager, '_inventory_manager', self.inventory_manager) # type: ignore[attr-defined]
        self.equipment_manager = EquipmentManager(character_manager=char_m, inventory_manager=self.inventory_manager, item_manager=item_m, status_manager=status_m, rule_engine=rl_e, db_service=db_s); setattr(self.character_manager, '_equipment_manager', self.equipment_manager) # type: ignore[attr-defined]
        self.party_manager = PartyManager(db_service=db_s, settings=self._settings.get('party_settings', {}), character_manager=char_m, game_manager=self); party_m = cast(PartyManager, self.party_manager); setattr(self.character_manager, '_party_manager', self.party_manager) # type: ignore[attr-defined]

        self.combat_manager = CombatManager(db_service=db_s, settings=self._settings.get('combat_settings',{}), rule_engine=rl_e, character_manager=char_m, npc_manager=npc_m, party_manager=party_m, status_manager=status_m, item_manager=item_m, location_manager=loc_m, game_manager=self); combat_m = cast(CombatManager, self.combat_manager)
        setattr(self.npc_manager, '_combat_manager', self.combat_manager); setattr(self.character_manager, '_combat_manager', self.combat_manager) # type: ignore[attr-defined]
        if self.party_manager: setattr(self.party_manager, 'combat_manager', self.combat_manager) # type: ignore[attr-defined]

        self.dialogue_manager = DialogueManager(db_service=db_s, settings=self._settings.get('dialogue_settings', {}), character_manager=char_m, npc_manager=npc_m, rule_engine=rl_e, time_manager=time_m, openai_service=self.openai_service, relationship_manager=rel_m, game_log_manager=game_log_m, quest_manager=None, notification_service=None, game_manager=self); dialog_m = cast(DialogueManager, self.dialogue_manager)
        if self.character_manager: setattr(self.character_manager, '_dialogue_manager', self.dialogue_manager) # type: ignore[attr-defined]
        if self.npc_manager: setattr(self.npc_manager, 'dialogue_manager', self.dialogue_manager) # type: ignore[attr-defined]

        econ_m = cast(EconomyManager, self.economy_manager) # Ensure it's not None
        self.consequence_processor = ConsequenceProcessor(character_manager=char_m, npc_manager=npc_m, item_manager=item_m, location_manager=loc_m, event_manager=evt_m, quest_manager=None, status_manager=status_m, dialogue_manager=dialog_m, rule_engine=rl_e, economy_manager=econ_m, relationship_manager=rel_m, game_log_manager=game_log_m, notification_service=None, prompt_context_collector=None); cons_proc = cast(ConsequenceProcessor, self.consequence_processor)

        self.quest_manager = QuestManager(db_service=db_s, settings=self._settings.get('quest_settings', {}), npc_manager=npc_m, character_manager=char_m, item_manager=item_m, rule_engine=rl_e, relationship_manager=rel_m, consequence_processor=cons_proc, game_log_manager=game_log_m, multilingual_prompt_generator=None, openai_service=self.openai_service, ai_validator=None, notification_service=None, game_manager=self); quest_m = cast(QuestManager, self.quest_manager)
        setattr(self.consequence_processor, 'quest_manager', self.quest_manager) # type: ignore[attr-defined]
        setattr(self.dialogue_manager, 'quest_manager', self.quest_manager) # type: ignore[attr-defined]

        self.faction_manager = FactionManager(game_manager=self);
        self.notification_service = NotificationService(send_callback_factory=self._get_discord_send_callback, settings=self._settings, i18n_utils=None, character_manager=char_m); notif_s = cast(NotificationService, self.notification_service)
        setattr(self.dialogue_manager, 'notification_service', notif_s) # type: ignore[attr-defined]
        setattr(self.quest_manager, 'notification_service', notif_s) # type: ignore[attr-defined]
        setattr(self.consequence_processor, 'notification_service', notif_s) # type: ignore[attr-defined]
        logger.info("GM: Dependent managers initialized.")

    async def _initialize_processors_and_command_system(self):
        logger.info("GM: Init processors & command system...")
        from bot.game.character_processors.character_action_processor import CharacterActionProcessor; from bot.game.character_processors.character_view_service import CharacterViewService; from bot.game.party_processors.party_action_processor import PartyActionProcessor; from bot.game.command_handlers.party_handler import PartyCommandHandler; from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor; from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator; from bot.game.event_processors.event_stage_processor import EventStageProcessor; from bot.game.event_processors.event_action_processor import EventActionProcessor; from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor; from bot.game.managers.persistence_manager import PersistenceManager; from bot.game.command_router import CommandRouter; from bot.game.conflict_resolver import ConflictResolver; from bot.game.turn_processing_service import TurnProcessingService; from bot.game.turn_processor import TurnProcessor; from bot.game.services.location_interaction_service import LocationInteractionService; from bot.game.rules.check_resolver import CheckResolver
        # from bot.game.action_scheduler import GuildActionScheduler # Not used currently
        # from bot.game.ai.npc_action_planner import NPCActionPlanner # Not used currently
        # from bot.game.npc_action_processor import NPCActionProcessor # Not used currently

        proc_deps_map = {name: getattr(self, name.lower().replace("manager", "_manager") if "Manager" in name else name.lower(), None) for name in ["DBService", "GameLogManager", "CharacterManager", "ItemManager", "QuestManager", "PartyManager", "NpcManager", "CombatManager", "StatusManager", "LocationManager", "RuleEngine", "EventManager", "TimeManager", "DialogueManager", "EquipmentManager", "InventoryManager", "CraftingManager", "EconomyManager", "RelationshipManager", "AbilityManager", "SpellManager"]}
        for name, inst in proc_deps_map.items():
            if not inst: raise RuntimeError(f"{name} NA for processors/command system.")

        # Cast all for safety within this scope
        db_s, gl_m, char_m, item_m, quest_m, party_m, npc_m, combat_m, status_m, loc_m, rl_e, evt_m, time_m, dialog_m, equip_m, inv_m, craft_m, econ_m, rel_m, abil_m, spell_m = (cast(Any, proc_deps_map[k]) for k in proc_deps_map) # type: ignore

        self.undo_manager = UndoManager(db_service=db_s, game_log_manager=gl_m, character_manager=char_m, item_manager=item_m, quest_manager=quest_m, party_manager=party_m)
        self._on_enter_action_executor = OnEnterActionExecutor(npc_manager=npc_m, item_manager=item_m, combat_manager=combat_m, status_manager=status_m)
        self._stage_description_generator = StageDescriptionGenerator(openai_service=self.openai_service)

        self._event_action_processor = EventActionProcessor(event_stage_processor=None, event_manager=evt_m, character_manager=char_m, loc_manager=loc_m, rule_engine=rl_e, openai_service=self.openai_service, send_callback_factory=self._get_discord_send_callback, game_manager=self); evt_act_proc = cast(EventActionProcessor, self._event_action_processor)
        self._event_stage_processor = EventStageProcessor(on_enter_action_executor=self._on_enter_action_executor, stage_description_generator=self._stage_description_generator, rule_engine=rl_e, character_manager=char_m, loc_manager=loc_m, game_manager=self, event_action_processor=evt_act_proc); evt_stage_proc = cast(EventStageProcessor, self._event_stage_processor)
        setattr(self._event_action_processor, 'event_stage_processor', evt_stage_proc) # type: ignore[attr-defined]

        self.location_interaction_service = LocationInteractionService(game_manager=self); loc_inter_svc = cast(LocationInteractionService, self.location_interaction_service)

        self._character_action_processor = CharacterActionProcessor(character_manager=char_m, send_callback_factory=self._get_discord_send_callback, db_service=db_s, item_manager=item_m, location_manager=loc_m, dialogue_manager=dialog_m, rule_engine=rl_e, time_manager=time_m, combat_manager=combat_m, status_manager=status_m, party_manager=party_m, npc_manager=npc_m, event_stage_processor=evt_stage_proc, event_action_processor=evt_act_proc, game_log_manager=gl_m, openai_service=self.openai_service, event_manager=evt_m, equipment_manager=equip_m, inventory_manager=inv_m, location_interaction_service=loc_inter_svc); char_act_proc = cast(CharacterActionProcessor, self._character_action_processor)
        self._character_view_service = CharacterViewService(character_manager=char_m, item_manager=item_m, location_manager=loc_m, rule_engine=rl_e, status_manager=status_m, party_manager=party_m, equipment_manager=equip_m, inventory_manager=inv_m, ability_manager=abil_m, spell_manager=spell_m); char_view_svc = cast(CharacterViewService, self._character_view_service)
        self._party_action_processor = PartyActionProcessor(party_manager=party_m, send_callback_factory=self._get_discord_send_callback, rule_engine=rl_e, location_manager=loc_m, character_manager=char_m, npc_manager=npc_m, time_manager=time_m, combat_manager=combat_m, event_stage_processor=evt_stage_proc, game_log_manager=gl_m); party_act_proc = cast(PartyActionProcessor, self._party_action_processor)
        self._party_command_handler = PartyCommandHandler(character_manager=char_m, party_manager=party_m, party_action_processor=party_act_proc, settings=self._settings, npc_manager=npc_m); party_cmd_hdlr = cast(PartyCommandHandler, self._party_command_handler)

        self._persistence_manager = PersistenceManager(event_manager=evt_m, character_manager=char_m, location_manager=loc_m, db_service=db_s, npc_manager=npc_m, combat_manager=combat_m, item_manager=item_m, time_manager=time_m, status_manager=status_m, crafting_manager=craft_m, economy_manager=econ_m, party_manager=party_m, quest_manager=quest_m, relationship_manager=rel_m, game_log_manager=gl_m, dialogue_manager=dialog_m, skill_manager=None, spell_manager=spell_m ); persist_m = cast(PersistenceManager, self._persistence_manager)

        # self.guild_action_scheduler = GuildActionScheduler() # Currently unused
        # npc_planner_services = {'rule_engine': rl_e, 'relationship_manager': rel_m, 'location_manager': loc_m } # Currently unused
        # self.npc_action_planner = NPCActionPlanner(context_providing_services=npc_planner_services) # Currently unused
        # npc_processor_managers = {'game_log_manager': gl_m, 'location_manager': loc_m, 'combat_manager': combat_m, 'character_manager': char_m, 'npc_manager': npc_m, 'item_manager': item_m, 'status_manager': status_m, 'event_manager': evt_m, 'rule_engine': rl_e } # Currently unused
        # self.npc_action_processor = NPCActionProcessor(managers=npc_processor_managers) # Currently unused

        self.turn_processing_service = TurnProcessingService(character_manager=char_m, rule_engine=rl_e, game_manager=self, game_log_manager=gl_m, character_action_processor=char_act_proc, combat_manager=combat_m, location_manager=loc_m, location_interaction_service=loc_inter_svc, dialogue_manager=dialog_m, inventory_manager=inv_m, equipment_manager=equip_m, item_manager=item_m, action_scheduler=None, npc_action_planner=None, npc_action_processor=None, npc_manager=npc_m, settings=self._settings)

        self._world_simulation_processor = WorldSimulationProcessor(event_manager=evt_m, character_manager=char_m, location_manager=loc_m, rule_engine=rl_e, openai_service=self.openai_service, event_stage_processor=evt_stage_proc, event_action_processor=evt_act_proc, persistence_manager=persist_m, settings=self._settings, send_callback_factory=self._get_discord_send_callback, character_action_processor=char_act_proc, party_action_processor=party_act_proc, npc_manager=npc_m, combat_manager=combat_m, item_manager=item_m, time_manager=time_m, status_manager=status_m, crafting_manager=craft_m, economy_manager=econ_m, party_manager=party_m, dialogue_manager=dialog_m, quest_manager=quest_m, relationship_manager=rel_m, game_log_manager=gl_m, multilingual_prompt_generator=self.multilingual_prompt_generator) # Pass self.multilingual_prompt_generator
        world_sim_proc = cast(WorldSimulationProcessor, self._world_simulation_processor)

        self.turn_processor = TurnProcessor(game_manager=self)
        self.check_resolver = CheckResolver(game_manager=self)
        self.conflict_resolver = ConflictResolver(rule_engine=rl_e, notification_service=self.notification_service, db_service=db_s, game_log_manager=gl_m); conflict_res = cast(ConflictResolver, self.conflict_resolver)

        camp_loader = cast(CampaignLoader, self.campaign_loader) # Ensure it's not None if used
        self._command_router = CommandRouter(character_manager=char_m, event_manager=evt_m, persistence_manager=persist_m, settings=self._settings, world_simulation_processor=world_sim_proc, send_callback_factory=self._get_discord_send_callback, character_action_processor=char_act_proc, character_view_service=char_view_svc, location_manager=loc_m, rule_engine=rl_e, party_command_handler=party_cmd_hdlr, openai_service=self.openai_service, item_manager=item_m, npc_manager=npc_m, combat_manager=combat_m, time_manager=time_m, status_manager=status_m, party_manager=party_m, crafting_manager=craft_m, economy_manager=econ_m, party_action_processor=party_act_proc, event_action_processor=evt_act_proc, event_stage_processor=evt_stage_proc, quest_manager=quest_m, dialogue_manager=dialog_m, campaign_loader=camp_loader, relationship_manager=rel_m, game_log_manager=gl_m, conflict_resolver=conflict_res, game_manager=self)
        logger.info("GM: Processors & command system initialized.")

    async def _initialize_ai_content_services(self):
        logger.info("GM: Init AI content services...")
        from bot.ai.prompt_context_collector import PromptContextCollector; from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator; from bot.ai.ai_response_validator import AIResponseValidator; from bot.services.nlu_data_service import NLUDataService

        ai_deps_map = {name: getattr(self, name.lower().replace("manager", "_manager"), None) for name in ["DBService", "CharacterManager", "NpcManager", "QuestManager", "RelationshipManager", "ItemManager", "LocationManager", "EventManager", "AbilityManager", "SpellManager", "PartyManager", "LoreManager"]}
        for name, inst in ai_deps_map.items():
            if not inst: raise RuntimeError(f"{name} NA for AI content services.")

        db_s_ai, char_m_ai, npc_m_ai, quest_m_ai, rel_m_ai, item_m_ai, loc_m_ai, evt_m_ai, abil_m_ai, spell_m_ai, party_m_ai, lore_m_ai = (cast(Any, ai_deps_map[k]) for k in ai_deps_map) # type: ignore

        self.nlu_data_service = NLUDataService(db_service=db_s_ai)
        self.prompt_context_collector = PromptContextCollector(settings=self._settings, db_service=db_s_ai, character_manager=char_m_ai, npc_manager=npc_m_ai, quest_manager=quest_m_ai, relationship_manager=rel_m_ai, item_manager=item_m_ai, location_manager=loc_m_ai, event_manager=evt_m_ai, ability_manager=abil_m_ai, spell_manager=spell_m_ai, party_manager=party_m_ai, lore_manager=lore_m_ai, game_manager=self); prom_coll = cast(PromptContextCollector, self.prompt_context_collector)

        main_bot_lang = "en" # Default
        if self._active_guild_ids and self._rules_config_cache.get(self._active_guild_ids[0]):
            main_bot_lang = str(self._rules_config_cache[self._active_guild_ids[0]].get('default_language', 'en'))

        # Pass self.openai_service if it's initialized
        openai_service_for_mpg = self.openai_service if self.openai_service else None
        self.multilingual_prompt_generator = MultilingualPromptGenerator(context_collector=prom_coll, main_bot_language=main_bot_lang, settings=self._settings, openai_service=openai_service_for_mpg); multi_prompt_gen = cast(MultilingualPromptGenerator, self.multilingual_prompt_generator)

        if self.quest_manager: setattr(self.quest_manager, 'multilingual_prompt_generator', multi_prompt_gen) # type: ignore[attr-defined]
        if self.consequence_processor: setattr(self.consequence_processor, 'prompt_context_collector', prom_coll) # type: ignore[attr-defined]

        self.ai_response_validator = AIResponseValidator()
        if self.quest_manager: setattr(self.quest_manager, 'ai_validator', self.ai_response_validator) # type: ignore[attr-defined]

        self.ai_generation_service = AIGenerationService(game_manager=self)
        logger.info("GM: AI content services initialized.")

    async def _ensure_guild_configs_exist(self) -> List[str]:
        logger.info("GM: Ensuring guild configs exist...")
        if not self.db_service or not hasattr(self.db_service, 'get_session') or not callable(getattr(self.db_service, 'get_session')):
            logger.error("DBService or get_session NA for _ensure_guild_configs_exist."); return []
        from bot.game.guild_initializer import initialize_new_guild # Local import

        succeeded_ids: List[str] = []
        guild_ids_to_proc = list(self._active_guild_ids)
        if not guild_ids_to_proc:
            def_id = str(self._settings.get('default_guild_id_for_setup', "1364930265591320586"))
            logger.warning(f"No active_guild_ids. Using default: {def_id}"); guild_ids_to_proc = [def_id]
            if def_id not in self._active_guild_ids: self._active_guild_ids.append(def_id)

        get_sess_method = getattr(self.db_service, 'get_session')
        for gid_str in guild_ids_to_proc:
            try:
                async with get_sess_method() as session_context: # type: ignore[operator]
                    session = cast(AsyncSession, session_context)
                    async with session.begin():
                        # force_reinit = (gid_str == "1364930265591320586") # Example: force for specific guild
                        # if force_reinit: logger.warning(f"FORCING REINITIALIZE for {gid_str}")
                        await initialize_new_guild(session, gid_str, force_reinitialize=False) # Set force_reinitialize as needed
                logger.info(f"Ensured/initialized GuildConfig for {gid_str}."); succeeded_ids.append(gid_str)
            except Exception as e: logger.exception(f"Exception ensuring guild config for {gid_str}")
        logger.info(f"Completed. Succeeded for: {succeeded_ids}"); return succeeded_ids

    async def _load_initial_data_and_state(self, confirmed_guild_ids: List[str]):
        logger.info(f"Loading initial game data for guilds: {confirmed_guild_ids}")
        if not confirmed_guild_ids: logger.warning("No confirmed_guild_ids. Skipping data load."); return
        if self.campaign_loader and hasattr(self.campaign_loader, 'populate_all_game_data'):
            for gid_str in confirmed_guild_ids:
                logger.info(f"Populating via CampaignLoader for guild {gid_str}.")
                try: await self.campaign_loader.populate_all_game_data(guild_id=gid_str, campaign_identifier=None)
                except Exception as e: logger.exception(f"Error populating game data for {gid_str}")
        else: logger.warning("CampaignLoader NA or populate_all_game_data missing.")

        if self._persistence_manager and hasattr(self._persistence_manager, 'load_game_state'):
            logger.info(f"PersistenceManager loading game state for guilds: {confirmed_guild_ids}")
            try: await self._persistence_manager.load_game_state(guild_ids=confirmed_guild_ids)
            except Exception as e: logger.exception(f"Error loading game state")
        else: logger.warning("PersistenceManager NA or load_game_state missing.")
        logger.info("Finished _load_initial_data_and_state.")

    async def _start_background_tasks(self):
        logger.info("Starting background tasks...")
        if self._world_simulation_processor and hasattr(self._world_simulation_processor, 'process_world_tick'):
            self._world_tick_task = asyncio.create_task(self._world_tick_loop())
            logger.info("World tick loop started.")
        else: logger.warning("World tick loop not started, WorldSimProc or process_world_tick NA.")
        logger.info("Background tasks started.")

    async def setup(self) -> None:
        logger.info("GM: Running setup…")
        try:
            await self._initialize_database()
            await self._initialize_core_managers_and_services()
            await self._initialize_dependent_managers()
            await self._initialize_processors_and_command_system()
            await self._initialize_ai_content_services()
            confirmed_gids = await self._ensure_guild_configs_exist()
            await self._load_initial_data_and_state(confirmed_gids)
            await self._start_background_tasks()
            logger.info("GM: Setup complete.")
        except Exception as e:
            # Check for asyncpg specific connection error if asyncpg is used directly or by SQLAlchemy
            # is_db_conn_err = isinstance(e, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError if 'asyncpg_exceptions' in locals() else ConnectionRefusedError)) or \
            #                  (hasattr(e, '__cause__') and isinstance(e.__cause__, (ConnectionRefusedError, asyncpg_exceptions.CannotConnectNowError if 'asyncpg_exceptions' in locals() else ConnectionRefusedError)))
            # Simplified check for now
            is_db_conn_err = "connect" in str(e).lower() and ("fail" in str(e).lower() or "refused" in str(e).lower())

            if is_db_conn_err: logger.critical(f"DB Connection Error: {e}", exc_info=True)
            else: logger.critical(f"GM Critical Setup Error: {e}", exc_info=True)
            try: await self.shutdown()
            except Exception as shutdown_e: logger.exception(f"Error during shutdown from setup failure: {shutdown_e}")
            raise

    async def handle_discord_message(self, message: "Message") -> None:
        if message.author.bot: return
        if not self._command_router or not hasattr(self._command_router, 'route') or not callable(getattr(self._command_router, 'route')):
            logger.warning("CommandRouter NA, msg '%s' from guild %s dropped.", message.content, message.guild.id if message.guild else "DM")
            if message.channel and hasattr(message.channel, 'send'):
                try: await message.channel.send(f"❌ Game systems not ready...")
                except Exception: logger.exception("Error sending startup error to channel")
            return

        cmd_prefix = str(self._settings.get('command_prefix', '/'))
        if message.content.startswith(cmd_prefix):
            logger.info("Passing command from %s (Guild: %s) to CommandRouter: '%s'", message.author.name, message.guild.id if message.guild else 'DM', message.content)
        try:
            await self._command_router.route(message)
        except Exception as e:
            logger.exception(f"Error handling message '{message.content}'")
            try:
                if message.channel and hasattr(message.channel, 'send'): await message.channel.send(f"❌ Internal error.")
                else: logger.warning("Cannot send error (DM or no channel).")
            except Exception: logger.exception("Error sending internal error message to channel")

    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback:
        async def _send(content: str = "", **kwargs: Any) -> None: # Ensure content is first arg
            channel = self._discord_client.get_channel(channel_id)
            if isinstance(channel, discord.abc.Messageable): # Check if it's Messageable
                try: await channel.send(content, **kwargs)
                except Exception as e: logger.exception(f"Error sending to {channel_id}: {e}")
            else: logger.warning(f"Channel {channel_id} not found or not Messageable.")
        return _send

    async def _process_player_turns_for_tick(self, guild_id_str: str) -> None:
        if not self.turn_processor or not hasattr(self.turn_processor, 'process_turns_for_guild') or \
           not self.character_manager:
            logger.warning(f"Tick-{guild_id_str}: TurnProcessor/CharMgr NA."); return
        try:
            await self.turn_processor.process_turns_for_guild(guild_id_str)
        except Exception as tps_e: logger.exception(f"Tick-{guild_id_str}: Error in TurnProcessor: {tps_e}")

    async def _world_tick_loop(self) -> None:
        logger.info("Starting world tick loop...")
        try:
            while True:
                await asyncio.sleep(self._tick_interval_seconds)
                if self._world_simulation_processor and hasattr(self._world_simulation_processor, 'process_world_tick') and callable(getattr(self._world_simulation_processor, 'process_world_tick')):
                    try: await self._world_simulation_processor.process_world_tick(game_time_delta=self._tick_interval_seconds)
                    except Exception as e: logger.exception(f"Error during world sim tick: {e}")
                for guild_id_str in self._active_guild_ids: await self._process_player_turns_for_tick(guild_id_str)
        except asyncio.CancelledError: logger.info("World tick loop cancelled.")
        except Exception as e: logger.critical(f"Critical error in world tick loop: {e}", exc_info=True)

    async def save_game_state_after_action(self, guild_id: str) -> None:
        if not self._persistence_manager or not hasattr(self._persistence_manager, 'save_game_state') or not callable(getattr(self._persistence_manager, 'save_game_state')):
            logger.warning(f"PersistenceManager NA for guild {guild_id}."); return
        try: await self._persistence_manager.save_game_state(guild_ids=[str(guild_id)])
        except Exception as e: logger.exception(f"Error saving game state for {guild_id}: {e}")

    async def shutdown(self) -> None:
        logger.info("Running shutdown...")
        if self._world_tick_task and not self._world_tick_task.done():
            self._world_tick_task.cancel()
            try: await asyncio.wait_for(self._world_tick_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError): logger.info("World tick task cancelled/timed out.")
            except Exception as e: logger.exception(f"Error waiting for world tick task: {e}")

        if self._persistence_manager and hasattr(self._persistence_manager, 'save_game_state') and callable(getattr(self._persistence_manager, 'save_game_state')) and self.db_service:
            try: await self._persistence_manager.save_game_state(guild_ids=self._active_guild_ids)
            except Exception as e: logger.exception(f"Error saving game state on shutdown: {e}")

        if self.db_service and hasattr(self.db_service, 'close') and callable(getattr(self.db_service, 'close')):
            try: await self.db_service.close()
            except Exception as e: logger.exception(f"Error closing DB service: {e}")
        logger.info("Shutdown complete.")

    async def get_player_by_discord_id(self, discord_id: int, guild_id: str) -> Optional[Character]: # Pydantic Character
        if not self.character_manager or not hasattr(self.character_manager, 'get_character_by_discord_id') or not callable(getattr(self.character_manager, 'get_character_by_discord_id')):
            logger.warning("CharacterManager or get_character_by_discord_id NA."); return None
        try:
            char_result = await self.character_manager.get_character_by_discord_id(guild_id=guild_id, discord_user_id=discord_id)
            return char_result # Already Pydantic Character or None
        except Exception as e: logger.exception(f"Error in get_player_by_discord_id: {e}"); return None

    async def _load_or_initialize_rules_config(self, guild_id: str):
        logger.info(f"Loading/Init rules for guild_id: {guild_id}...")
        self._rules_config_cache.setdefault(guild_id, {})
        if not self.db_service or not hasattr(self.db_service, 'get_session') or not callable(getattr(self.db_service, 'get_session')):
            logger.error(f"DBService NA for rules config of guild {guild_id}."); self._rules_config_cache[guild_id] = {"default_bot_language": "en", "error_state": "DBService unavailable", "emergency_mode": True}; return

        from bot.utils.config_utils import load_rules_config as util_load_rules_config # Local import
        get_session_method = getattr(self.db_service, 'get_session')
        try:
            async with get_session_method() as session_context: # type: ignore[operator]
                session = cast(AsyncSession, session_context)
                guild_rules_dict = await util_load_rules_config(session, guild_id)
            if guild_rules_dict and isinstance(guild_rules_dict, dict):
                self._rules_config_cache[guild_id] = guild_rules_dict; logger.info(f"RulesConfig for {guild_id} loaded.")
            else:
                logger.warning(f"No rules for guild {guild_id} in DB or not a dict. Initializing.")
                from bot.game.guild_initializer import initialize_new_guild # Local import
                async with get_session_method() as init_session_context: # type: ignore[operator]
                    init_session = cast(AsyncSession, init_session_context)
                    async with init_session.begin(): await initialize_new_guild(init_session, guild_id, force_reinitialize=False)
                    guild_rules_dict_after_init = await util_load_rules_config(init_session, guild_id)
                self._rules_config_cache[guild_id] = guild_rules_dict_after_init if isinstance(guild_rules_dict_after_init, dict) else {}
                logger.info(f"RulesConfig for {guild_id} initialized ({len(self._rules_config_cache[guild_id])} rules).")
                if not self._rules_config_cache.get(guild_id): self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": "Init failed or no rules after re-fetch."}; logger.error(f"Failed to load/init rules for {guild_id} even after init attempt.")
        except Exception as e: logger.exception(f"Exception during rules config for {guild_id}"); self._rules_config_cache[guild_id] = {"default_bot_language": "en", "emergency_mode": True, "reason": f"Exception: {str(e)}"}

    async def get_rule(self, guild_id: str, key: str, default: Optional[Any] = None) -> Optional[Any]:
        if guild_id not in self._rules_config_cache: await self._load_or_initialize_rules_config(guild_id)
        guild_specific_cache = self._rules_config_cache.get(guild_id)
        if isinstance(guild_specific_cache, dict): return guild_specific_cache.get(key, default)
        logger.warning(f"Guild {guild_id} not in cache or cache not dict for rule '{key}'. Returning default."); return default

    async def get_location_type_i18n_map(self, guild_id: str, type_key: str) -> Optional[Dict[str, str]]:
        if not self.rule_engine: logger.warning(f"RuleEngine NA for guild {guild_id}."); return None
        try:
            rules_config_model = await self.get_core_rules_config_for_guild(guild_id)
            if rules_config_model and hasattr(rules_config_model, 'location_type_definitions') and isinstance(rules_config_model.location_type_definitions, dict):
                i18n_map_any = rules_config_model.location_type_definitions.get(type_key)
                if i18n_map_any is None: logger.warning(f"Key '{type_key}' not in location_type_definitions for {guild_id}.")
                elif isinstance(i18n_map_any, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in i18n_map_any.items()):
                    return cast(Dict[str,str], i18n_map_any)
                else: logger.warning(f"Value for key '{type_key}' in location_type_definitions not Dict[str, str] for {guild_id}.")
            elif rules_config_model: logger.warning(f"location_type_definitions not in CoreGameRulesConfig or not dict for {guild_id}.")
            else: logger.warning(f"CoreGameRulesConfig NA for {guild_id}.")
        except Exception as e: logger.exception(f"Error retrieving location type defs for {guild_id}, key '{type_key}'")
        return None

    async def get_core_rules_config_for_guild(self, guild_id: str) -> Optional[CoreGameRulesConfig]:
        if guild_id not in self._rules_config_cache: await self._load_or_initialize_rules_config(guild_id)
        raw_rules_dict = self._rules_config_cache.get(guild_id)
        if not isinstance(raw_rules_dict, dict): logger.warning(f"No raw rules dict or not a dict for {guild_id}."); return None
        try: return CoreGameRulesConfig(**raw_rules_dict)
        except ValidationError as ve: logger.exception(f"Pydantic validation error for CoreGameRulesConfig guild {guild_id}"); logger.debug(f"Problematic dict for CoreGameRulesConfig {guild_id}: {raw_rules_dict}"); return None
        except Exception as e: logger.exception(f"Unexpected error parsing CoreGameRulesConfig for {guild_id}"); return None

    async def update_rule_config(self, guild_id: str, key: str, value: Any) -> bool:
        if not self.db_service or not hasattr(self.db_service, 'get_session') or not callable(getattr(self.db_service, 'get_session')):
            logger.error(f"DBService or get_session NA for update_rule_config (guild {guild_id})."); return False
        from bot.utils.config_utils import update_rule_config as util_update_rule_config # Local import
        get_session_method = getattr(self.db_service, 'get_session')
        try:
            async with get_session_method() as session_context: # type: ignore[operator]
                session = cast(AsyncSession, session_context)
                await util_update_rule_config(session, guild_id, key, value)
            self._rules_config_cache.setdefault(guild_id, {})[key] = value
            logger.info(f"Rule '{key}' for {guild_id} updated in DB and cache."); return True
        except Exception as e:
            logger.exception(f"Exception updating rule '{key}' for {guild_id}")
            if guild_id in self._rules_config_cache and isinstance(self._rules_config_cache[guild_id], dict):
                self._rules_config_cache[guild_id].pop(key, None); logger.info(f"Cache for rule '{key}' ({guild_id}) cleared due to error.")
            return False

    async def set_default_bot_language(self, language: str, guild_id: Optional[str] = None) -> bool:
        if not guild_id: return False
        success = await self.update_rule_config(guild_id, "default_language", language)
        if success and self.multilingual_prompt_generator and hasattr(self.multilingual_prompt_generator, 'update_main_bot_language') and callable(getattr(self.multilingual_prompt_generator, 'update_main_bot_language')):
            if self._active_guild_ids and guild_id == self._active_guild_ids[0]:
                 update_main_lang_method = getattr(self.multilingual_prompt_generator, 'update_main_bot_language')
                 update_main_lang_method(language)
                 logger.info(f"Updated MPG main lang to '{language}' for primary guild '{guild_id}'.")
        return success

    async def get_player_model_by_discord_id(self, guild_id: str, discord_id: str) -> Optional[Player]:
        if not self.db_service or not hasattr(self.db_service, 'get_entities_by_conditions') or not callable(getattr(self.db_service, 'get_entities_by_conditions')): return None
        get_entities_method = getattr(self.db_service, 'get_entities_by_conditions')
        results: Optional[List[Player]] = await get_entities_method(Player, conditions={'guild_id': str(guild_id), 'discord_id': str(discord_id)})
        return results[0] if results else None

    async def get_player_model_by_id(self, guild_id: str, player_id: str) -> Optional[Player]:
        if not self.db_service or not hasattr(self.db_service, 'get_entity_by_pk') or not callable(getattr(self.db_service, 'get_entity_by_pk')): return None
        get_entity_pk_method = getattr(self.db_service, 'get_entity_by_pk')
        result: Optional[Player] = await get_entity_pk_method(Player, pk_value=str(player_id), guild_id=str(guild_id))
        return result

    async def get_players_in_location(self, guild_id: str, location_id: str) -> List[Player]:
        if not self.db_service or not hasattr(self.db_service, 'get_entities_by_conditions') or not callable(getattr(self.db_service, 'get_entities_by_conditions')): return []
        get_entities_method = getattr(self.db_service, 'get_entities_by_conditions')
        results: Optional[List[Player]] = await get_entities_method(Player, conditions={'guild_id': str(guild_id), 'current_location_id': str(location_id)})
        return results if results else []

    async def handle_move_action(self, guild_id: str, character_id: str, target_location_identifier: str) -> bool: # Added session=None
        if not self.location_manager or not hasattr(self.location_manager, 'process_character_move') or not callable(getattr(self.location_manager, 'process_character_move')): return False
        process_move_method = getattr(self.location_manager, 'process_character_move')
        # process_character_move in LocationManager might need a session if it does DB updates directly
        return await process_move_method(guild_id=guild_id, character_id=character_id, target_location_identifier=target_location_identifier)


    async def trigger_ai_generation(self, guild_id: str, request_type: str, request_params: Dict[str, Any], created_by_user_id: Optional[str] = None) -> Optional[str]:
        if not self.ai_generation_service or not hasattr(self.ai_generation_service, 'request_content_generation') or not callable(getattr(self.ai_generation_service, 'request_content_generation')):
            logger.error("AIGenService or request_content_generation NA."); return None
        req_gen_method = getattr(self.ai_generation_service, 'request_content_generation')
        try: req_type_enum = PendingGenerationTypeEnum(request_type)
        except ValueError: logger.error(f"Invalid request_type '{request_type}' for AI gen."); return None

        ctx_params = request_params.get("context_params", {}) if isinstance(request_params.get("context_params"), dict) else {}
        prompt_params = request_params.get("prompt_params", {}) if isinstance(request_params.get("prompt_params"), dict) else {}

        pending_rec = await req_gen_method(guild_id, req_type_enum, ctx_params, prompt_params, created_by_user_id)
        return str(pending_rec.id) if pending_rec and hasattr(pending_rec, 'id') else None

    async def apply_approved_generation(self, pending_gen_id: str, guild_id: str) -> bool:
        if not self.ai_generation_service or not hasattr(self.ai_generation_service, 'process_approved_generation') or not callable(getattr(self.ai_generation_service, 'process_approved_generation')):
            logger.error("AIGenService or process_approved_generation NA."); return False
        proc_appr_method = getattr(self.ai_generation_service, 'process_approved_generation')
        return await proc_appr_method(pending_gen_id=pending_gen_id, guild_id=guild_id, moderator_user_id="SYSTEM_AUTO_APPROVE")

    async def is_user_master(self, guild_id: str, user_id: int) -> bool:
        master_ids_raw = await self.get_rule(guild_id, "master_user_ids", default=[])
        master_ids = [str(uid) for uid in master_ids_raw] if isinstance(master_ids_raw, list) else []
        return str(user_id) in master_ids

    async def get_default_bot_language(self, guild_id: str) -> str: # Added method
        lang = await self.get_rule(guild_id, "default_language", "en")
        return str(lang) if lang else "en"
