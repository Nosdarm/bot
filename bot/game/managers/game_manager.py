# bot/game/managers/game_manager.py

import asyncio
import json
import traceback
import os
import io
import logging
import uuid
import random
from alembic.config import Config
from alembic import command
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING, Union


from asyncpg import exceptions as asyncpg_exceptions
from bot.database.postgres_adapter import SQLALCHEMY_DATABASE_URL as PG_URL_FOR_ALEMBIC

import discord
from discord import Client
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.db_service import DBService
# from bot.ai.rules_schema import GameRules # Unused directly
from bot.game.models.character import Character as PydanticCharacter
from bot.database.models import (
    RulesConfig, Player, PendingGeneration, GuildConfig,
    Location, QuestTable, QuestStepTable, Party,
    Character as CharacterDbModel, # SQLAlchemy model for Character
    Item as ItemDbModel,      # SQLAlchemy model for Item
    NPC as NpcDbModel         # SQLAlchemy model for NPC
)
from bot.services.notification_service import NotificationService
from bot.game.managers.character_manager import CharacterManager, CharacterAlreadyExistsError, UpdateHealthResult # Import Pydantic model
from bot.game.managers.status_manager import ApplyStatusResult # Import Pydantic model

from bot.ai.ai_response_validator import parse_and_validate_ai_response
from sqlalchemy.future import select
from bot.database.guild_transaction import GuildTransaction

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

logger = logging.getLogger(__name__)

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
        self._persistence_manager: Optional["PersistenceManager"] = None
        self._world_simulation_processor: Optional["WorldSimulationProcessor"] = None
        self._command_router: Optional["CommandRouter"] = None
        self.rule_engine: Optional["RuleEngine"] = None
        self.time_manager: Optional["TimeManager"] = None
        self.location_manager: Optional["LocationManager"] = None
        self.event_manager: Optional["EventManager"] = None
        self.character_manager: Optional["CharacterManager"] = None
        self.item_manager: Optional["ItemManager"] = None
        self.inventory_manager: Optional["InventoryManager"] = None
        self.equipment_manager: Optional["EquipmentManager"] = None
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
        self.ai_response_validator: Optional[AIResponseValidator] = None
        self.turn_processor: Optional[TurnProcessor] = None
        self.check_resolver: Optional[CheckResolver] = None
        self.faction_manager: Optional[FactionManager] = None
        self.location_interaction_service: Optional[LocationInteractionService] = None
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
        logger.info("GameManager initialized.")

    # ... (methods from _load_or_initialize_rules_config to start_new_character_session - keeping them collapsed for brevity)
    async def _load_or_initialize_rules_config(self, guild_id: str): logger.info(f"GM: Loading rules for {guild_id}"); pass
    async def get_rule(self, guild_id: str, key: str, default: Any = None) -> Any: return default
    async def _initialize_database(self): self.db_service = DBService(); await self.db_service.connect(); await self.db_service.initialize_database()
    async def _initialize_core_managers_and_services(self): from bot.game.rules.rule_engine import RuleEngine; from bot.game.managers.time_manager import TimeManager; from bot.game.managers.location_manager import LocationManager; from bot.game.managers.event_manager import EventManager; from bot.services.openai_service import OpenAIService; self.rule_engine = RuleEngine({}, {}); self.time_manager = TimeManager(self.db_service, {}); self.location_manager = LocationManager(self.db_service, self._settings); self.openai_service = OpenAIService("test", "test"); self.event_manager = EventManager(self.db_service, {}, self.openai_service)
    async def _initialize_dependent_managers(self): from bot.game.managers.item_manager import ItemManager; from bot.game.managers.status_manager import StatusManager; from bot.game.managers.npc_manager import NpcManager; from bot.game.managers.character_manager import CharacterManager; from bot.game.managers.inventory_manager import InventoryManager; from bot.game.managers.equipment_manager import EquipmentManager; from bot.game.managers.combat_manager import CombatManager; from bot.game.managers.party_manager import PartyManager; from bot.game.managers.lore_manager import LoreManager; from bot.services.notification_service import NotificationService; from bot.game.managers.faction_manager import FactionManager; from bot.game.managers.game_log_manager import GameLogManager; from bot.game.services.campaign_loader import CampaignLoader; self.item_manager = ItemManager(self.db_service, self._settings, self.location_manager, self.rule_engine); self.game_log_manager = GameLogManager(self.db_service); self.campaign_loader = CampaignLoader(self._settings, self.db_service); self.status_manager = StatusManager(self.db_service, self._settings.get('status_settings',{}), self.rule_engine, self.time_manager, None); self.npc_manager = NpcManager(self.db_service, self._settings.get('npc_settings',{}), self.item_manager, self.rule_engine, self.status_manager, self.campaign_loader, self.location_manager, self); self.character_manager = CharacterManager(self.db_service, self._settings, self.item_manager, self.location_manager, self.rule_engine, self.status_manager, self.game_log_manager, self.npc_manager, self);_c=self.character_manager; _n=self.npc_manager; _s=self.status_manager; setattr(_s,'_character_manager',_c) if _s else None; setattr(_n,'_character_manager',_c) if _n else None; self.inventory_manager=InventoryManager(_c,self.item_manager,self.db_service); setattr(_c,'_inventory_manager',self.inventory_manager) if _c else None; self.equipment_manager=EquipmentManager(_c,self.inventory_manager,self.item_manager,_s,self.rule_engine,self.db_service); setattr(_c,'_equipment_manager',self.equipment_manager) if _c else None; self.combat_manager=CombatManager(self.db_service,{},self.rule_engine,_c,_n,_s,self.item_manager,self.location_manager);self.party_manager=PartyManager(self.db_service,{},_n,_c,self.combat_manager); setattr(_c,'_party_manager',self.party_manager) if _c else None; setattr(_c,'_combat_manager',self.combat_manager) if _c else None; setattr(_n,'_combat_manager',self.combat_manager) if _n else None; setattr(self.combat_manager,'_party_manager',self.party_manager) if self.combat_manager else None; self.lore_manager=LoreManager({},self.db_service);self.notification_service=NotificationService(self._get_discord_send_callback, self._settings,None,_c);self.faction_manager=FactionManager(self)
    async def _initialize_processors_and_command_system(self): pass
    async def _load_initial_data_and_state(self): pass
    async def _initialize_ai_content_services(self): from bot.ai.prompt_context_collector import PromptContextCollector; from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator; from bot.ai.ai_response_validator import AIResponseValidator; self.prompt_context_collector = PromptContextCollector(self._settings, self.db_service, self.character_manager, self.npc_manager, self.quest_manager, self.relationship_manager, self.item_manager, self.location_manager, self.ability_manager, self.spell_manager, self.event_manager, self.party_manager, self.lore_manager, self); self.multilingual_prompt_generator = MultilingualPromptGenerator(self.prompt_context_collector, "en", {}); self.ai_response_validator = AIResponseValidator()
    async def _start_background_tasks(self): pass
    async def setup(self): await self._initialize_database(); await self._initialize_core_managers_and_services(); await self._initialize_dependent_managers(); await self._initialize_processors_and_command_system(); await self._load_initial_data_and_state(); await self._initialize_ai_content_services(); await self._start_background_tasks()
    async def handle_discord_message(self, message: "Message"): pass
    def _get_discord_send_callback(self, channel_id: int) -> SendToChannelCallback: async def _send(content: str = "", **kwargs: Any): pass; return _send
    async def shutdown(self): pass
    async def get_player_model_by_id(self, guild_id: str, player_id: str) -> Optional[Player]: return None
    async def start_new_character_session(self, user_id: int, guild_id: str, character_name: str) -> Optional[PydanticCharacter]: return None # Game/Pydantic model

    def _get_localized_name(self, model_instance: Any, lang_code: str, default_field_name: str = "name", i18n_field_name: str = "name_i18n", default_value: str = "Unknown") -> str:
        """ Helper to get a localized name from a model instance. """
        if not model_instance: return default_value

        name_i18n_attr = getattr(model_instance, i18n_field_name, None)
        if isinstance(name_i18n_attr, dict):
            name = name_i18n_attr.get(lang_code, name_i18n_attr.get("en")) # Fallback to 'en'
            if name and isinstance(name, str): return name.strip()

        # Fallback to default field name (e.g., a non-i18n 'name' attribute)
        name_attr = getattr(model_instance, default_field_name, None)
        if name_attr and isinstance(name_attr, str): return name_attr.strip()

        # Ultimate fallback if ID is available
        id_attr = getattr(model_instance, "id", None)
        if id_attr: return f"{default_value} ({str(id_attr)[:8]})"

        return default_value

    async def _on_enter_location(self, guild_id_str: str, entity_id_str: str, entity_type: str, location_id_str: str):
        logger.info(f"Entity {entity_id_str} ({entity_type}) entered location {location_id_str} in guild {guild_id_str}.")
        event_messages: List[str] = []

        if not all([self.db_service, self.location_manager, self.character_manager,
                    self.inventory_manager, self.npc_manager, self.status_manager, self.item_manager]):
            logger.error(f"_on_enter_location: Essential manager(s) missing. Aborting.")
            return

        location_obj = self.location_manager.get_location_instance(guild_id_str, location_id_str)
        if not location_obj:
            logger.warning(f"_on_enter_location: Location {location_id_str} (cache) not found."); return
        if not location_obj.on_enter_events_json:
            logger.debug(f"_on_enter_location: No on_enter_events for {location_id_str}."); return

        async with self.db_service.get_session() as session: # type: ignore
            async with session.begin():
                acting_character_model: Optional[CharacterDbModel] = None
                player_language = "en"

                if entity_type == "Character":
                    acting_character_model = await session.get(CharacterDbModel, entity_id_str)
                    if not acting_character_model or str(acting_character_model.guild_id) != guild_id_str:
                        logger.error(f"Character {entity_id_str} not found in DB for guild {guild_id_str}."); return
                elif entity_type == "Party":
                    party = await session.get(Party, entity_id_str)
                    if party and str(party.guild_id) == guild_id_str and party.leader_id:
                        acting_character_model = await session.get(CharacterDbModel, party.leader_id)
                        if not acting_character_model or str(acting_character_model.guild_id) != guild_id_str:
                            logger.error(f"Party leader {party.leader_id} for party {entity_id_str} not found."); acting_character_model = None
                    else: logger.error(f"Party {entity_id_str} not found or no leader."); return

                if acting_character_model and acting_character_model.player_id:
                    player_account = await session.get(Player, acting_character_model.player_id)
                    if player_account and player_account.selected_language: player_language = player_account.selected_language

                send_callback = self._get_discord_send_callback(int(location_obj.channel_id)) if location_obj.channel_id else \
                                lambda msg, **kw: logger.info(f"[LOG_SEND_CALLBACK] Loc:{location_id_str}, Msg:{msg}")

                for event_details in location_obj.on_enter_events_json:
                    if not isinstance(event_details, dict) or random.random() > event_details.get("chance", 1.0): continue
                    event_type_str = event_details.get("event_type")
                    msg_i18n = event_details.get("message_i18n", {})
                    loc_msg = msg_i18n.get(player_language, msg_i18n.get("en", "An event unfolds."))

                    if event_type_str == "AMBIENT_MESSAGE": event_messages.append(loc_msg)
                    elif event_type_str == "ITEM_DISCOVERY":
                        if not acting_character_model: logger.warning(f"ITEM_DISCOVERY needs Character. Skipping."); continue
                        items_to_grant = event_details.get("items", [])
                        granted_names = []
                        for item_info in items_to_grant:
                            tpl_id = item_info.get("item_template_id"); qty = item_info.get("quantity",1); st_vars = item_info.get("state_variables")
                            if tpl_id:
                                # Assuming add_item_to_character_inventory returns bool. To get names, we'd need more.
                                # For now, we'll use the template_id in the message if successful.
                                # A better approach would be for add_item_to_character_inventory to return the created ItemDbModel instances.
                                # For this subtask, we'll assume it returns bool and fetch template for name.
                                success = await self.inventory_manager.add_item_to_character_inventory(guild_id_str, acting_character_model.id, tpl_id, qty, st_vars, session)
                                if success:
                                    item_template = await self.item_manager.get_item_template_as_dict(guild_id_str, tpl_id) # Fetch for name
                                    item_name = self._get_localized_name(item_template, player_language, default_value=tpl_id) if item_template else tpl_id
                                    granted_names.append(f"{qty}x {item_name}")
                                else: logger.error(f"Failed to grant item {tpl_id} to {acting_character_model.id}")
                        if granted_names: event_messages.append(loc_msg.replace("[items_list]", ", ".join(granted_names)))

                    elif event_type_str == "NPC_APPEARANCE":
                        npc_tpl_id = event_details.get("npc_template_id"); count = event_details.get("spawn_count",1); temp = event_details.get("is_temporary",True); state = event_details.get("initial_state")
                        if npc_tpl_id:
                            spawned_npcs_info = []
                            for _ in range(count):
                                npc_model = await self.npc_manager.spawn_npc_in_location(guild_id_str, location_id_str, npc_tpl_id, temp, state, session)
                                if npc_model: spawned_npcs_info.append(self._get_localized_name(npc_model, player_language, default_value=npc_tpl_id))
                            if spawned_npcs_info: event_messages.append(loc_msg.replace("[npc_name]", ", ".join(spawned_npcs_info)))

                    elif event_type_str == "SIMPLE_HAZARD":
                        if not acting_character_model: logger.warning(f"SIMPLE_HAZARD needs Character. Skipping."); continue
                        eff_type = event_details.get("effect_type")
                        if eff_type == "HEALTH_CHANGE":
                            amount = float(event_details.get("amount", 0))
                            dmg_type = event_details.get("damage_type", "mysterious forces")
                            health_res = await self.character_manager.update_health(guild_id_str, acting_character_model.id, amount, session)
                            if health_res:
                                if health_res.actual_hp_change < 0: event_messages.append(loc_msg.replace("[damage_amount]", f"{abs(health_res.actual_hp_change):.0f}").replace("[damage_type]", dmg_type).replace("[action_taken_past]", "took").replace("[action_taken]", "take"))
                                elif health_res.actual_hp_change > 0: event_messages.append(loc_msg.replace("[healed_amount]", f"{health_res.actual_hp_change:.0f}").replace("[action_taken_past]", "healed").replace("[action_taken]", "heal"))
                                else: event_messages.append(f"The {dmg_type} had no further effect (HP: {health_res.current_hp:.0f}/{health_res.max_hp:.0f}).")
                                if not health_res.is_alive: event_messages.append("The damage was overwhelming!")
                        elif eff_type == "APPLY_STATUS":
                            stat_id = event_details.get("status_id"); dur = event_details.get("duration")
                            if stat_id:
                                status_res = await self.status_manager.apply_status_to_character(guild_id_str, acting_character_model.id, stat_id, int(dur) if dur is not None else None, session=session)
                                if status_res and status_res.applied:
                                    msg_text = loc_msg.replace("[status_effect_name]", status_res.status_name or stat_id)
                                    if status_res.duration_turns: msg_text += f" (Duration: {status_res.duration_turns} turns)."
                                    event_messages.append(msg_text)
                                elif status_res: logger.warning(f"Failed to apply status {stat_id}: {status_res.message}")
                    else: logger.warning(f"Unknown event type: {event_type_str}")

                if event_messages: # Send all collected messages for this event sequence
                    await send_callback("\n".join(event_messages))
            # Transaction commits here if all successful

    async def handle_move_action(self, guild_id: str, character_id: str, target_location_identifier: str) -> bool:
        guild_id_str = str(guild_id); character_id_str = str(character_id)
        logger.info(f"GM: Handling move for CHAR {character_id_str} in guild {guild_id_str} to '{target_location_identifier}'.")
        if not self.db_service or not self.location_manager or not self.game_log_manager: return False
        event_entity_id: Optional[str] = None; event_entity_type: str = "Character"; event_target_location_id: Optional[str] = None; initial_char_loc_id: Optional[str] = None
        session_factory = self.db_service.async_session_factory
        async with GuildTransaction(session_factory, guild_id_str) as session:
            char = await session.get(CharacterDbModel, character_id_str)
            if not char or str(char.guild_id) != guild_id_str: return False
            initial_char_loc_id = char.current_location_id; current_loc_id_for_event_trigger = char.current_location_id
            if not char.current_location_id: return False
            curr_loc_pyd = self.location_manager.get_location_instance(guild_id_str, char.current_location_id)
            if not curr_loc_pyd: return False
            target_loc_sql = await self.location_manager.get_location_by_static_id(guild_id_str, target_location_identifier, session=session)
            if not target_loc_sql: target_loc_sql = self.location_manager.get_location_by_name_exact(guild_id_str, target_location_identifier)
            if not target_loc_sql: return False

            if curr_loc_pyd.id == target_loc_sql.id:
                # Even if already there, trigger on_enter_location for potential events/state changes
                asyncio.create_task(self._on_enter_location(guild_id_str, char.id, "Character", str(target_loc_sql.id)))
                return True

            if target_loc_sql.id not in (curr_loc_pyd.neighbor_locations_json or {}): return False

            old_loc_id_for_log = char.current_location_id
            party_moved_as_primary = False; party_id_for_log = char.current_party_id

            if char.current_party_id:
                party = await session.get(Party, char.current_party_id)
                if party and str(party.guild_id) == guild_id_str :
                    party_rules = await self.get_rule(guild_id_str, "party_movement_rules", default={})
                    can_move_party = (char.id == party.leader_id) or not party_rules.get("allow_leader_only_move", True)
                    if can_move_party:
                        party.current_location_id = target_loc_sql.id; session.add(party)
                        event_entity_id = party.id; event_entity_type = "Party"; party_moved_as_primary = True
                        current_loc_id_for_event_trigger = target_loc_sql.id # Party enters new location
                        if party_rules.get("teleport_all_members", True) and party.player_ids_json:
                            for member_id_str in party.player_ids_json:
                                member_char = await session.get(CharacterDbModel, member_id_str)
                                if member_char and str(member_char.guild_id) == guild_id_str: member_char.current_location_id = target_loc_sql.id; session.add(member_char)

            if not (party_moved_as_primary and char.id in (party.player_ids_json if party and party.player_ids_json else [])): # type: ignore
                 char.current_location_id = target_loc_sql.id; session.add(char)
                 current_loc_id_for_event_trigger = target_loc_sql.id # Character enters new location

            if not party_moved_as_primary: event_entity_id = char.id
            elif event_entity_id is None : event_entity_id = char.current_party_id # Party was primary entity

            event_target_location_id = str(current_loc_id_for_event_trigger) if current_loc_id_for_event_trigger else None

            await self.game_log_manager.log_event(guild_id=guild_id_str, event_type="character_move",
                                                 details_json={'char_id':char.id, 'old':old_loc_id_for_log, 'new':target_loc_sql.id, 'party_id': party_id_for_log, 'party_moved': party_moved_as_primary}, session=session)

        if event_entity_id and event_target_location_id:
            asyncio.create_task(self._on_enter_location(guild_id_str, str(event_entity_id), event_entity_type, event_target_location_id))
            return True
        # If player was already at the location (handled by early return which calls _on_enter_location)
        # or if move failed before setting event_entity_id/event_target_location_id
        return False


    async def trigger_ai_generation(self, guild_id: str, request_type: str, request_params: Dict[str, Any], created_by_user_id: Optional[str] = None) -> Optional[str]: return None
    async def apply_approved_generation(self, pending_gen_id: str, guild_id: str) -> bool: return False

logger.debug("--- GameManager: Loaded game_manager.py")

[end of bot/game/managers/game_manager.py]
