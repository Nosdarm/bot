# bot/game/managers/location_manager.py

from __future__ import annotations
import json
import uuid
from bot.game.models.party import Party
from bot.game.models.location import Location
from bot.game.models.character import Character # Added for type hinting
import traceback
import asyncio
import logging
import sys
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

from sqlalchemy.future import select # For direct queries if needed
from bot.database.guild_transaction import GuildTransaction # For DB operations

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.game_log_manager import GameLogManager # Added
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
    from bot.ai.rules_schema import CoreGameRulesConfig
    from sqlalchemy.ext.asyncio import AsyncSession
    # GameManager will be imported for type hinting to access its attributes
    from bot.game.managers.game_manager import GameManager


logger = logging.getLogger(__name__)

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

class LocationManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _location_templates: Dict[str, Dict[str, Any]]
    _location_instances: Dict[str, Dict[str, Dict[str, Any]]]
    _dirty_instances: Dict[str, Set[str]]
    _deleted_instances: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        game_manager: Optional["GameManager"] = None,
        send_callback_factory: Optional[SendCallbackFactory] = None
    ):
        self._diagnostic_log = []
        self._diagnostic_log.append("DEBUG_LM: Initializing LocationManager...")
        self._db_service = db_service
        self._settings = settings
        self._game_manager = game_manager

        self._rule_engine = game_manager.rule_engine if game_manager else None
        self._event_manager = game_manager.event_manager if game_manager else None
        self._character_manager = game_manager.character_manager if game_manager else None
        self._npc_manager = game_manager.npc_manager if game_manager else None
        self._item_manager = game_manager.item_manager if game_manager else None
        self._combat_manager = game_manager.combat_manager if game_manager else None
        self._status_manager = game_manager.status_manager if game_manager else None
        self._party_manager = game_manager.party_manager if game_manager else None
        self._time_manager = game_manager.time_manager if game_manager else None
        self._game_log_manager = game_manager.game_log_manager if game_manager else None


        self._send_callback_factory = send_callback_factory
        self._event_stage_processor = game_manager._event_stage_processor if game_manager and hasattr(game_manager, '_event_stage_processor') else None
        self._event_action_processor = game_manager._event_action_processor if game_manager and hasattr(game_manager, '_event_action_processor') else None
        self._on_enter_action_executor = game_manager._on_enter_action_executor if game_manager and hasattr(game_manager, '_on_enter_action_executor') else None
        self._stage_description_generator = game_manager._stage_description_generator if game_manager and hasattr(game_manager, '_stage_description_generator') else None


        self.rules_config: Optional[CoreGameRulesConfig] = None
        if self._rule_engine and hasattr(self._rule_engine, '_rules_data'):
            self.rules_config = self._rule_engine._rules_data # type: ignore

        self._location_templates = {}
        self._location_instances = {}
        self._dirty_instances = {}
        self._deleted_instances = {}

        self._load_location_templates()
        self._diagnostic_log.append("DEBUG_LM: LocationManager initialized.")

    def _load_location_templates(self):
        self._diagnostic_log.append("DEBUG_LM: ENTERING _load_location_templates")
        self._location_templates = {}
        self._diagnostic_log.append(f"DEBUG_LM: self._settings type: {type(self._settings)}")

        if self._settings:
            self._diagnostic_log.append(f"DEBUG_LM: self._settings value (first 100 chars): {str(self._settings)[:100]}")
            templates_data = self._settings.get('location_templates')
            self._diagnostic_log.append(f"DEBUG_LM: templates_data type: {type(templates_data)}")
            if isinstance(templates_data, dict):
                self._diagnostic_log.append(f"DEBUG_LM: Processing {len(templates_data)} templates from settings.")
                for template_id, data in templates_data.items():
                    self._diagnostic_log.append(f"DEBUG_LM: Processing template_id: {template_id}")
                    if isinstance(data, dict):
                        data['id'] = str(template_id)
                        if not isinstance(data.get('name_i18n'), dict): data['name_i18n'] = {"en": data.get('name', template_id), "ru": data.get('name', template_id)}
                        if not isinstance(data.get('description_i18n'), dict): data['description_i18n'] = {"en": data.get('description', ""), "ru": data.get('description', "")}
                        self._location_templates[str(template_id)] = data
                        self._diagnostic_log.append(f"DEBUG_LM: Loaded template '{template_id}'.")
                    else:
                        self._diagnostic_log.append(f"DEBUG_LM: Data for template '{template_id}' is not a dictionary. Skipping.")
                self._diagnostic_log.append(f"DEBUG_LM: Finished loop. Loaded {len(self._location_templates)} templates.")
            else:
                self._diagnostic_log.append("DEBUG_LM: 'location_templates' in settings is not a dictionary or not found.")
        else:
            self._diagnostic_log.append("DEBUG_LM: No settings provided.")
        self._diagnostic_log.append(f"DEBUG_LM: EXITING _load_location_templates. Final keys: {list(self._location_templates.keys())}")

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        self._diagnostic_log.append(f"DEBUG_LM: ENTERING load_state for guild_id: {guild_id_str}")
        db_service_to_use = self._db_service or (self._game_manager.db_service if self._game_manager else None)
        if not db_service_to_use or not hasattr(db_service_to_use, 'get_session_factory'):
            self._diagnostic_log.append(f"DEBUG_LM: DBService or session factory not available for load_state in guild {guild_id_str}.")
            self._clear_guild_state_cache(guild_id_str)
            return
        self._clear_guild_state_cache(guild_id_str)
        from bot.database.crud_utils import get_entities
        loaded_instances_count = 0
        try:
            async with GuildTransaction(db_service_to_use.get_session_factory, guild_id_str, commit_on_exit=False) as session:
                all_locations_in_guild = await get_entities(session, Location, guild_id=guild_id_str)
                guild_instances_cache = self._location_instances.setdefault(guild_id_str, {})
                for loc_model_instance in all_locations_in_guild:
                    try:
                        instance_data_dict = loc_model_instance.to_dict()
                        guild_instances_cache[loc_model_instance.id] = instance_data_dict
                        loaded_instances_count += 1
                    except Exception as e_proc:
                        self._diagnostic_log.append(f"DEBUG_LM: Error processing location model instance (ID: {loc_model_instance.id}) for guild {guild_id_str}: {e_proc}")
                        logger.error("LocationManager: Error processing location model instance (ID: %s) for guild %s: %s", loc_model_instance.id, guild_id_str, e_proc, exc_info=True)
            self._diagnostic_log.append(f"DEBUG_LM: Successfully loaded {loaded_instances_count} instances for guild {guild_id_str} using crud_utils.")
            logger.info("LocationManager.load_state: Successfully loaded %s instances for guild %s using crud_utils.", loaded_instances_count, guild_id_str)
        except ValueError as ve:
            self._diagnostic_log.append(f"DEBUG_LM: GuildTransaction integrity error during load_state for guild {guild_id_str}: {ve}")
            logger.error(f"LocationManager: GuildTransaction integrity error during load_state for guild {guild_id_str}: {ve}", exc_info=True)
        except Exception as e:
            self._diagnostic_log.append(f"DEBUG_LM: CRITICAL DB error loading instances for guild {guild_id_str}: {e}")
            logger.critical("LocationManager: CRITICAL DB error loading instances for guild %s: %s", guild_id_str, e, exc_info=True)

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.debug("LocationManager: Saving state for guild %s.", guild_id_str)
        db_service_to_use = self._db_service or (self._game_manager.db_service if self._game_manager else None)
        if not db_service_to_use or not hasattr(db_service_to_use, 'get_session_factory'):
            logger.error(f"LocationManager: DB service or session factory not available for save_state in guild {guild_id_str}.")
            return
        from sqlalchemy import delete as sqlalchemy_delete
        deleted_ids_for_guild = list(self._deleted_instances.get(guild_id_str, set()))
        dirty_ids_for_guild = list(self._dirty_instances.get(guild_id_str, set()))
        processed_dirty_ids_in_transaction = set()
        if not deleted_ids_for_guild and not dirty_ids_for_guild: return
        try:
            async with GuildTransaction(db_service_to_use.get_session_factory, guild_id_str) as session:
                if deleted_ids_for_guild:
                    stmt = sqlalchemy_delete(Location).where(Location.id.in_(deleted_ids_for_guild), Location.guild_id == guild_id_str)
                    await session.execute(stmt)
                guild_cache = self._location_instances.get(guild_id_str, {})
                for instance_id in dirty_ids_for_guild:
                    instance_data_dict = guild_cache.get(instance_id)
                    if instance_data_dict and isinstance(instance_data_dict, dict) and str(instance_data_dict.get('guild_id')) == guild_id_str and 'id' in instance_data_dict:
                        loc_to_merge = Location(**instance_data_dict); await session.merge(loc_to_merge)
                        processed_dirty_ids_in_transaction.add(instance_id)
            if guild_id_str in self._deleted_instances: self._deleted_instances[guild_id_str].clear()
            if guild_id_str in self._dirty_instances: self._dirty_instances[guild_id_str].difference_update(processed_dirty_ids_in_transaction)
            if guild_id_str in self._dirty_instances and not self._dirty_instances[guild_id_str]: del self._dirty_instances[guild_id_str]
        except ValueError as ve: logger.error(f"LM: GuildTransaction error during save_state for guild {guild_id_str}: {ve}", exc_info=True)
        except Exception as e: logger.error(f"LM: Error during save_state for guild {guild_id_str}: {e}", exc_info=True)

    async def process_character_move(self, guild_id: str, character_id: str, target_location_identifier: str) -> bool:
        guild_id_str = str(guild_id)
        character_id_str = str(character_id)
        logger.info(f"LocationManager: Processing move for CHARACTER {character_id_str} in guild {guild_id_str} to '{target_location_identifier}'.")

        if not self._game_manager or not self._game_manager.db_service or \
           not self._game_manager.game_log_manager or not self._game_manager.party_manager or \
           not self._game_manager.rule_engine:
            logger.error("LocationManager: Essential GameManager components (DB, GameLog, PartyManager, RuleEngine) not available.")
            return False

        db_service = self._game_manager.db_service
        game_log_manager = self._game_manager.game_log_manager
        party_manager = self._game_manager.party_manager
        rule_engine = self._game_manager.rule_engine

        event_entity_id: Optional[str] = None
        event_entity_type: str = "Character"
        event_target_location_id: Optional[str] = None
        initial_character_location_id_for_event: Optional[str] = None
        current_location_obj_for_final_check: Optional[Location] = None

        session_factory = db_service.async_session_factory
        async with GuildTransaction(session_factory, guild_id_str) as session:
            character = await session.get(Character, character_id_str)
            if not character or str(character.guild_id) != guild_id_str:
                logger.error(f"LocationManager: Character {character_id_str} not found in guild {guild_id_str} or guild mismatch.")
                return False

            initial_character_location_id_for_event = character.current_location_id
            if not character.current_location_id:
                logger.error(f"LocationManager: Character {character_id_str} has no current_location_id. Cannot move.")
                return False

            current_location_obj = self.get_location_instance(guild_id_str, character.current_location_id)
            current_location_obj_for_final_check = current_location_obj
            if not current_location_obj:
                logger.error(f"LocationManager: Current location {character.current_location_id} (Character: {character_id_str}) not found in cache.")
                return False

            target_location_obj = await self.get_location_by_static_id(guild_id_str, target_location_identifier, session=session)
            if not target_location_obj:
                cached_locations = self._location_instances.get(guild_id_str, {}).values()
                found_by_name: List[Location] = [Location.from_dict(loc_data) for loc_data in cached_locations if isinstance(loc_data.get('name_i18n'), dict) and any(name.lower() == target_location_identifier.lower() for name in loc_data['name_i18n'].values())]
                if len(found_by_name) == 1: target_location_obj = found_by_name[0]
                elif len(found_by_name) > 1: logger.warning(f"Ambiguous target location name '{target_location_identifier}'. Move failed."); return False
            if not target_location_obj: logger.warning(f"Target location '{target_location_identifier}' not found. Move failed."); return False

            if not current_location_obj.neighbor_locations_json or target_location_obj.id not in current_location_obj.neighbor_locations_json:
                logger.info(f"Character {character.id} cannot move from {current_location_obj.id} to {target_location_obj.id}. Not connected."); return False

            if current_location_obj.id == target_location_obj.id:
                logger.info(f"Character {character.id} is already at {target_location_obj.id}. Triggering on_enter.")
                event_entity_id = character.id; event_target_location_id = target_location_obj.id
            else:
                old_location_id = character.current_location_id
                party_moved_as_primary = False
                party_id_for_event_details = character.current_party_id
                party_movement_rules = await rule_engine.get_rule(guild_id_str, "party_movement_rules", default={})

                if character.current_party_id:
                    party = await session.get(Party, character.current_party_id)
                    if party and str(party.guild_id) == guild_id_str:
                        is_leader = (character.id == party.leader_id)
                        allow_leader_only_move = party_movement_rules.get("allow_leader_only_move", True)
                        can_player_move_party = is_leader or not allow_leader_only_move
                        if can_player_move_party:
                            party.current_location_id = target_location_obj.id
                            session.add(party)
                            event_entity_id = party.id; event_entity_type = "Party"; party_moved_as_primary = True
                            if party_movement_rules.get("teleport_all_members", True) and party.player_ids_json:
                                for member_char_id_str in party.player_ids_json:
                                    member_char = await session.get(Character, member_char_id_str)
                                    if member_char and str(member_char.guild_id) == guild_id_str:
                                        member_char.current_location_id = target_location_obj.id
                                        session.add(member_char)

                character_needs_individual_move = True
                party_ref_for_check = await session.get(Party, character.current_party_id) if character.current_party_id else None
                if party_moved_as_primary and party_movement_rules.get("teleport_all_members", True):
                    if party_ref_for_check and character.id in (party_ref_for_check.player_ids_json or []):
                        character_needs_individual_move = False

                if character_needs_individual_move:
                    character.current_location_id = target_location_obj.id
                    session.add(character)

                if not party_moved_as_primary: event_entity_id = character.id
                event_target_location_id = target_location_obj.id

                await game_log_manager.log_event(
                    guild_id=guild_id_str, event_type="character_move",
                    details_json={'character_id': character.id, 'player_account_id': character.player_id,
                                  'party_id': party_id_for_event_details, 'old_location_id': old_location_id,
                                  'new_location_id': target_location_obj.id, 'method': 'direct_move_command',
                                  'party_moved_as_primary': party_moved_as_primary},
                    player_id=character.player_id, location_id=target_location_obj.id, session=session)

        if event_entity_id and event_target_location_id and self._game_manager and self._game_manager.location_interaction_service:
            asyncio.create_task(self._game_manager.location_interaction_service.process_on_enter_location_events(guild_id_str, event_entity_id, event_entity_type, event_target_location_id))
            return True
        elif current_location_obj_for_final_check and target_location_obj and \
             current_location_obj_for_final_check.id == target_location_obj.id and \
             initial_character_location_id_for_event and self._game_manager and self._game_manager.location_interaction_service:
            asyncio.create_task(self._game_manager.location_interaction_service.process_on_enter_location_events(guild_id_str, character_id_str, "Character", initial_character_location_id_for_event))
            return True

        logger.warning(f"LocationManager: Move action for char {character_id_str} to '{target_location_identifier}' did not result in state change or event dispatch, or LIS not found.")
        return False

    async def generate_location_details_from_ai(self, guild_id: str, generation_prompt_key: str, player_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        logger.warning("generate_location_details_from_ai is not fully implemented in LocationManager based on provided code.")
        return None

    async def _ensure_persistent_location_exists(self, guild_id: str, location_template_id: str) -> Optional[Dict[str, Any]]: return None
    def get_location_name(self, guild_id: str, instance_id: str) -> Optional[str]: return None
    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]: return {}
    async def update_location_state(self, guild_id: str, instance_id: str, state_updates: Dict[str, Any], **kwargs: Any) -> bool: return False
    def get_location_channel(self, guild_id: str, instance_id: str) -> Optional[int]: return None
    def get_default_location_id(self, guild_id: str) -> Optional[str]: return None
    async def move_entity(self, guild_id: str, entity_id: str, entity_type: str, from_location_id: Optional[str], to_location_id: str, **kwargs: Any) -> bool: return False
    async def handle_entity_arrival(self, location_id: str, entity_id: str, entity_type: str, **kwargs: Any) -> None: pass
    async def handle_entity_departure(self, location_id: str, entity_id: str, entity_type: str, **kwargs: Any) -> None: pass
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None: pass
    def get_location_static(self, template_id: Optional[str]) -> Optional[Dict[str, Any]]: return self._location_templates.get(str(template_id)) if template_id is not None else None
    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id); self._location_instances.pop(guild_id_str, None); self._dirty_instances.pop(guild_id_str, None); self._deleted_instances.pop(guild_id_str, None)
    def mark_location_instance_dirty(self, guild_id: str, instance_id: str) -> None:
        guild_id_str, instance_id_str = str(guild_id), str(instance_id)
        if guild_id_str in self._location_instances and instance_id_str in self._location_instances[guild_id_str]: self._dirty_instances.setdefault(guild_id_str, set()).add(instance_id_str)
    async def create_location_instance(self, guild_id: str, template_id: str, initial_state: Optional[Dict[str, Any]] = None, instance_name: Optional[str] = None, instance_description: Optional[str] = None, instance_exits: Optional[Dict[str, str]] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
        template_data = self.get_location_static(template_id)
        if not template_data: return None
        new_id = str(uuid.uuid4())
        instance_data = {"id": new_id, "guild_id": guild_id, "template_id": template_id, "name_i18n": {"en": instance_name or new_id}}
        self._location_instances.setdefault(str(guild_id), {})[new_id] = instance_data
        self.mark_location_instance_dirty(str(guild_id), new_id)
        return instance_data

    async def delete_location_instance(self, guild_id: str, instance_id: str, **kwargs: Any) -> bool: return False
    async def clean_up_location_contents(self, location_instance_id: str, **kwargs: Any) -> None: pass
    async def create_location_instance_from_moderated_data(self, guild_id: str, location_data: Dict[str, Any], user_id: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]: return None
    async def add_item_to_location(self, guild_id: str, location_id: str, item_template_id: str, quantity: int = 1, dropped_item_data: Optional[Dict[str, Any]] = None) -> bool: return False
    async def revert_location_state_variable_change(self, guild_id: str, location_id: str, variable_name: str, old_value: Any, **kwargs: Any) -> bool: return False
    async def revert_location_inventory_change(self, guild_id: str, location_id: str, item_template_id: str, item_instance_id: Optional[str], change_action: str, quantity_changed: int, original_item_data: Optional[Dict[str, Any]], **kwargs: Any) -> bool: return False
    async def revert_location_exit_change(self, guild_id: str, location_id: str, exit_direction: str, old_target_location_id: Optional[str], **kwargs: Any) -> bool: return False
    async def revert_location_activation_status(self, guild_id: str, location_id: str, old_is_active_status: bool, **kwargs: Any) -> bool: return False
    async def get_location_by_static_id(self, guild_id: str, static_id: str, session: Optional[AsyncSession] = None) -> Optional[Location]:
        guild_id_str = str(guild_id); static_id_str = str(static_id)
        guild_cache = self._location_instances.get(guild_id_str, {})
        for loc_id, loc_data_dict in guild_cache.items():
            if isinstance(loc_data_dict, dict) and loc_data_dict.get('static_id') == static_id_str:
                try: return Location.from_dict(loc_data_dict)
                except Exception: return None
        db_service_to_use = self._db_service or (self._game_manager.db_service if self._game_manager else None)
        if session:
            stmt = select(Location).where(Location.guild_id == guild_id_str, Location.static_id == static_id_str); result = await session.execute(stmt); loc_model = result.scalars().first()
            if loc_model: self._location_instances.setdefault(guild_id_str, {})[loc_model.id] = loc_model.to_dict(); return loc_model
        elif db_service_to_use:
            from bot.database.crud_utils import get_entity_by_attributes
            async with GuildTransaction(db_service_to_use.get_session_factory, guild_id_str, commit_on_exit=False) as crud_session:
                loc_model = await get_entity_by_attributes(crud_session, Location, attributes={'static_id': static_id_str}, guild_id=guild_id_str)
            if loc_model: self._location_instances.setdefault(guild_id_str, {})[loc_model.id] = loc_model.to_dict(); return loc_model
        return None

logger.debug("DEBUG: location_manager.py module loaded (after overwrite).")
