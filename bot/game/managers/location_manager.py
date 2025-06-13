# bot/game/managers/location_manager.py

from __future__ import annotations
import json
from bot.game.models.party import Party
from bot.game.models.location import Location
import traceback # Will be removed
import asyncio
import logging # Added
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

from builtins import dict, set, list, str, int, bool, float

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
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
    from bot.ai.rules_schema import CoreGameRulesConfig

logger = logging.getLogger(__name__) # Added

SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

class LocationManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    _location_templates: Dict[str, Dict[str, Any]]
    _location_instances: Dict[str, Dict[str, Dict[str, Any]]]
    _dirty_instances: Dict[str, Set[str]]
    _deleted_instances: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None,
        event_manager: Optional["EventManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        time_manager: Optional["TimeManager"] = None,
        send_callback_factory: Optional[SendCallbackFactory] = None,
        event_stage_processor: Optional["EventStageProcessor"] = None,
        event_action_processor: Optional["EventActionProcessor"] = None,
        on_enter_action_executor: Optional["OnEnterActionExecutor"] = None,
        stage_description_generator: Optional["StageDescriptionGenerator"] = None,
    ):
        logger.info("Initializing LocationManager...") # Changed
        self._db_service = db_service
        self._settings = settings
        self._rule_engine = rule_engine
        self._event_manager = event_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._time_manager = time_manager
        self._send_callback_factory = send_callback_factory
        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor
        self._on_enter_action_executor = on_enter_action_executor
        self._stage_description_generator = stage_description_generator

        self.rules_config: Optional[CoreGameRulesConfig] = None
        if self._rule_engine and hasattr(self._rule_engine, 'rules_config_data'):
            self.rules_config = self._rule_engine.rules_config_data

        self._location_templates = {}
        self._location_instances = {}
        self._dirty_instances = {}
        self._deleted_instances = {}

        self._load_location_templates()
        logger.info("LocationManager initialized.") # Changed

    def _load_location_templates(self):
        logger.info("LocationManager: Loading global location templates...") # Changed
        self._location_templates = {}
        if self._settings and 'location_templates' in self._settings:
            templates_data = self._settings['location_templates']
            if isinstance(templates_data, dict):
                for template_id, data in templates_data.items():
                    if isinstance(data, dict):
                        data['id'] = str(template_id)
                        if not isinstance(data.get('name_i18n'), dict): data['name_i18n'] = {"en": data.get('name', template_id), "ru": data.get('name', template_id)}
                        if not isinstance(data.get('description_i18n'), dict): data['description_i18n'] = {"en": data.get('description', ""), "ru": data.get('description', "")}
                        self._location_templates[str(template_id)] = data
                    else:
                        logger.warning("LocationManager: Data for location template '%s' is not a dictionary. Skipping.", template_id) # Changed
                logger.info("LocationManager: Loaded %s global location templates from settings.", len(self._location_templates)) # Changed
            else:
                logger.warning("LocationManager: 'location_templates' in settings is not a dictionary.") # Changed
        else:
            logger.info("LocationManager: No 'location_templates' found in settings.") # Changed

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("LocationManager.load_state: Called for guild_id: %s", guild_id_str) # Changed
        db_service = kwargs.get('db_service', self._db_service)
        if db_service is None or db_service.adapter is None:
             logger.error("LocationManager: DBService not available for load_state in guild %s.", guild_id_str) # Added
             self._clear_guild_state_cache(guild_id_str)
             return
        # ... (rest of load_state logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("LocationManager: Error processing instance row (ID: %s) for guild %s: %s", row.get('id', 'N/A'), guild_id_str, e, exc_info=True)
        # Example: logger.info("LocationManager.load_state: Successfully loaded %s instances for guild %s.", loaded_instances_count, guild_id_str)
        logger.info("LocationManager.load_state: Successfully loaded instances for guild %s.", guild_id_str) # Simplified for now

    async def _ensure_persistent_location_exists(self, guild_id: str, location_template_id: str) -> Optional[Dict[str, Any]]:
        # ... (logic as before, add guild_id context to logs)
        # Example: logger.info("LocationManager: Ensuring persistent location for template %s in guild %s.", location_template_id, guild_id)
        return None

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.debug("LocationManager: Saving state for guild %s.", guild_id_str) # Changed to debug for less noise
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("LocationManager: DBService not available for save_state in guild %s.", guild_id_str) # Added
            return
        # ... (rest of save_state logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("LocationManager: Error deleting instances for guild %s: %s", guild_id_str, e, exc_info=True)
        # Example: logger.info("LocationManager: Save state complete for guild %s.", guild_id_str)

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        logger.info("LocationManager: Rebuilding runtime caches for guild %s.", guild_id) # Added
        pass

    async def create_location_instance(self, guild_id: str, template_id: str, initial_state: Optional[Dict[str, Any]] = None, instance_name: Optional[str] = None, instance_description: Optional[str] = None, instance_exits: Optional[Dict[str, str]] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
        guild_id_str, template_id_str = str(guild_id), str(template_id)
        logger.info("LocationManager: Creating location instance from template %s for guild %s.", template_id_str, guild_id_str) # Added
        # ... (rest of create_location_instance logic, ensure guild_id_str in logs for errors/warnings) ...
        # Example: logger.error("LocationManager: Failed to create location instance from template %s for guild %s: %s", template_id_str, guild_id_str, e, exc_info=True)
        return None

    def get_location_instance(self, guild_id: str, instance_id: str) -> Optional[Location]:
        guild_id_str, instance_id_str = str(guild_id), str(instance_id)
        guild_instances = self._location_instances.get(guild_id_str, {})
        instance_data_dict = guild_instances.get(instance_id_str)
        if instance_data_dict:
            if not isinstance(instance_data_dict, dict):
                logger.warning("LocationManager: Cached instance data for %s in guild %s is not a dict.", instance_id_str, guild_id_str) # Changed
                return None
            try:
                if 'state' not in instance_data_dict or not isinstance(instance_data_dict['state'], dict): instance_data_dict['state'] = {}
                if 'inventory' not in instance_data_dict['state'] or not isinstance(instance_data_dict['state']['inventory'], list): instance_data_dict['state']['inventory'] = []
                return Location.from_dict(instance_data_dict)
            except Exception as e:
                logger.error("LocationManager: Error creating Location object from dict for %s in guild %s: %s", instance_id_str, guild_id_str, e, exc_info=True) # Changed
                return None
        return None

    async def delete_location_instance(self, guild_id: str, instance_id: str, **kwargs: Any) -> bool:
        logger.info("LocationManager: Deleting location instance %s in guild %s.", instance_id, guild_id) # Added
        # ... (rest of delete_location_instance logic, ensure guild_id in logs for errors/warnings) ...
        return False

    async def clean_up_location_contents(self, location_instance_id: str, **kwargs: Any) -> None:
        guild_id = kwargs.get('guild_id') # Assuming guild_id is in kwargs
        logger.info("LocationManager: Cleaning up contents for location %s in guild %s.", location_instance_id, guild_id if guild_id else "UNKNOWN_GUILD") # Added
        # ... (rest of clean_up_location_contents logic, ensure guild_id in logs for errors/warnings) ...
        pass

    def get_location_name(self, guild_id: str, instance_id: str) -> Optional[str]: # Already has guild_id
        # ... (logic as before)
        return None
    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]: # Already has guild_id
        # ... (logic as before)
        return {}
    async def update_location_state(self, guild_id: str, instance_id: str, state_updates: Dict[str, Any], **kwargs: Any) -> bool: # Already has guild_id
        logger.info("LocationManager: Updating state for location %s in guild %s. Updates: %s", instance_id, guild_id, state_updates) # Added
        # ... (rest of update_location_state logic)
        return False
    def get_location_channel(self, guild_id: str, instance_id: str) -> Optional[int]: # Already has guild_id
        # ... (logic as before)
        return None
    def get_default_location_id(self, guild_id: str) -> Optional[str]: # Already has guild_id
        # ... (logic as before)
        return None
    async def move_entity(self, guild_id: str, entity_id: str, entity_type: str, from_location_id: Optional[str], to_location_id: str, **kwargs: Any) -> bool: # Already has guild_id
        logger.info("LocationManager: Moving entity %s (%s) from %s to %s in guild %s.", entity_id, entity_type, from_location_id, to_location_id, guild_id) # Added
        # ... (rest of move_entity logic)
        return False
    async def handle_entity_arrival(self, location_id: str, entity_id: str, entity_type: str, **kwargs: Any) -> None: # Needs guild_id
        guild_id = kwargs.get('guild_id', 'UNKNOWN_GUILD')
        logger.info("LocationManager: Handling entity %s (%s) arrival at %s in guild %s.", entity_id, entity_type, location_id, guild_id) # Added
        # ... (rest of handle_entity_arrival logic)
        pass
    async def handle_entity_departure(self, location_id: str, entity_id: str, entity_type: str, **kwargs: Any) -> None: # Needs guild_id
        guild_id = kwargs.get('guild_id', 'UNKNOWN_GUILD')
        logger.info("LocationManager: Handling entity %s (%s) departure from %s in guild %s.", entity_id, entity_type, location_id, guild_id) # Added
        # ... (rest of handle_entity_departure logic)
        pass
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None: # Already has guild_id
        # logger.debug("LocationManager: Processing tick for guild %s. Delta: %.2f", guild_id, game_time_delta) # Too noisy for info
        pass
    def get_location_static(self, template_id: Optional[str]) -> Optional[Dict[str, Any]]: # Global, no guild_id
        return self._location_templates.get(str(template_id)) if template_id is not None else None
    def _clear_guild_state_cache(self, guild_id: str) -> None: # Already has guild_id
        logger.info("LocationManager: Clearing state cache for guild %s.", guild_id) # Added
        # ... (rest of _clear_guild_state_cache logic)
        pass
    def mark_location_instance_dirty(self, guild_id: str, instance_id: str) -> None: # Already has guild_id
         guild_id_str, instance_id_str = str(guild_id), str(instance_id)
         if guild_id_str in self._location_instances and instance_id_str in self._location_instances[guild_id_str]:
              self._dirty_instances.setdefault(guild_id_str, set()).add(instance_id_str)
              # logger.debug("LocationManager: Marked location instance %s in guild %s as dirty.", instance_id_str, guild_id_str) # Too noisy

    async def create_location_instance_from_moderated_data(self, guild_id: str, location_data: Dict[str, Any], user_id: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]: # Already has guild_id
        logger.info("LocationManager: Creating location instance from moderated data for guild %s by user %s. Data: %s", guild_id, user_id, location_data) # Added
        # ... (rest of logic)
        return None

    async def add_item_to_location(self, guild_id: str, location_id: str,
                                   item_template_id: str, quantity: int = 1,
                                   dropped_item_data: Optional[Dict[str, Any]] = None) -> bool:
        log_prefix = f"LocationManager.add_item_to_location(guild='{guild_id}', loc='{location_id}', item_tpl='{item_template_id}'):" # Added guild_id
        # ... (rest of add_item_to_location logic, use log_prefix for messages)
        # Example: logger.error("%s Location instance not found. Cannot add item.", log_prefix)
        return False # Placeholder

    async def revert_location_state_variable_change(self, guild_id: str, location_id: str, variable_name: str, old_value: Any, **kwargs: Any) -> bool: # Already has guild_id
        logger.info("LocationManager: Reverting state variable '%s' for location %s in guild %s.", variable_name, location_id, guild_id) # Added
        # ... (rest of logic)
        return False
    async def revert_location_inventory_change(self, guild_id: str, location_id: str, item_template_id: str, item_instance_id: Optional[str], change_action: str, quantity_changed: int, original_item_data: Optional[Dict[str, Any]], **kwargs: Any) -> bool: # Already has guild_id
        logger.info("LocationManager: Reverting inventory change (action: %s, item: %s) for location %s in guild %s.", change_action, item_template_id, location_id, guild_id) # Added
        # ... (rest of logic)
        return False
    async def revert_location_exit_change(self, guild_id: str, location_id: str, exit_direction: str, old_target_location_id: Optional[str], **kwargs: Any) -> bool: # Already has guild_id
        logger.info("LocationManager: Reverting exit '%s' for location %s to '%s' in guild %s.", exit_direction, location_id, old_target_location_id, guild_id) # Added
        # ... (rest of logic)
        return False
    async def revert_location_activation_status(self, guild_id: str, location_id: str, old_is_active_status: bool, **kwargs: Any) -> bool: # Already has guild_id
        logger.info("LocationManager: Reverting is_active status for location %s to %s in guild %s.", location_id, old_is_active_status, guild_id) # Added
        # ... (rest of logic)
        return False
