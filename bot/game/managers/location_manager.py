# bot/game/managers/location_manager.py

from __future__ import annotations
import json
from bot.game.models.party import Party
from bot.game.models.location import Location
import traceback
import asyncio
# --- Необходимые импорты для runtime ---
import uuid # uuid нужен для генерации ID инстансов

# --- Базовые типы и TYPE_CHECKING ---
# Set и другие типы нужны для аннотаций
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins

# --- Imports needed ONLY for Type Checking ---
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
    from bot.ai.rules_schema import CoreGameRulesConfig # Added


# Define Callback Types
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
        print("Initializing LocationManager...")
        self._db_service = db_service
        self._settings = settings
        self._rule_engine = rule_engine
        self._event_manager = event_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._item_manager = item_manager # ItemManager is needed to get item definitions for stacking logic
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
        print("LocationManager initialized.")

    def _load_location_templates(self):
        # ... (existing _load_location_templates logic - assuming it's correct) ...
        print("LocationManager: Loading global location templates...")
        self._location_templates = {}
        if self._settings and 'location_templates' in self._settings:
            templates_data = self._settings['location_templates']
            if isinstance(templates_data, dict):
                for template_id, data in templates_data.items():
                    if isinstance(data, dict):
                        data['id'] = str(template_id)
                        if not isinstance(data.get('name_i18n'), dict):
                            data['name_i18n'] = {"en": data.get('name', template_id), "ru": data.get('name', template_id)}
                        if not isinstance(data.get('description_i18n'), dict):
                            data['description_i18n'] = {"en": data.get('description', ""), "ru": data.get('description', "")}
                        self._location_templates[str(template_id)] = data
                    else:
                        print(f"LocationManager: Warning: Data for location template '{template_id}' is not a dictionary. Skipping.")
                print(f"LocationManager: Loaded {len(self._location_templates)} global location templates from settings.")
            else:
                print("LocationManager: 'location_templates' in settings is not a dictionary.")
        else:
            print("LocationManager: No 'location_templates' found in settings.")


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        # ... (existing load_state logic - assuming it's correct) ...
        guild_id_str = str(guild_id)
        print(f"LocationManager.load_state: Called for guild_id: {guild_id_str}")
        db_service = kwargs.get('db_service', self._db_service)
        if db_service is None or db_service.adapter is None:
             self._clear_guild_state_cache(guild_id_str)
             return
        self._location_instances[guild_id_str] = {}
        self._dirty_instances.pop(guild_id_str, None)
        self._deleted_instances.pop(guild_id_str, None)
        guild_instances_cache = self._location_instances[guild_id_str]
        loaded_instances_count = 0
        try:
            sql_instances = 'SELECT id, template_id, name_i18n, descriptions_i18n, exits, state_variables, is_active, guild_id, static_name, static_connections FROM locations WHERE guild_id = $1'
            rows_instances = await db_service.adapter.fetchall(sql_instances, (guild_id_str,))
            if rows_instances:
                 for row in rows_instances:
                      try:
                           instance_id_raw = row['id']; loaded_guild_id_raw = row['guild_id']
                           if instance_id_raw is None or str(loaded_guild_id_raw) != guild_id_str: continue
                           instance_id = str(instance_id_raw); template_id = str(row['template_id']) if row['template_id'] is not None else None
                           name_i18n_json = row['name_i18n']; descriptions_i18n_json = row['descriptions_i18n']
                           instance_name_i18n_dict = json.loads(name_i18n_json) if isinstance(name_i18n_json, str) else (name_i18n_json if isinstance(name_i18n_json, dict) else {})
                           instance_descriptions_i18n_dict = json.loads(descriptions_i18n_json) if isinstance(descriptions_i18n_json, str) else (descriptions_i18n_json if isinstance(descriptions_i18n_json, dict) else {})
                           instance_exits = json.loads(row['exits'] or '{}') if isinstance(row['exits'], (str, bytes)) else {}
                           # Ensure state_variables is always a dict, and inventory is a list within it
                           instance_state_data = json.loads(row['state_variables'] or '{}') if isinstance(row['state_variables'], (str, bytes)) else {}
                           if not isinstance(instance_state_data.get('inventory'), list): instance_state_data['inventory'] = []

                           is_active = row['is_active'] if 'is_active' in row.keys() else 0 # type: ignore
                           instance_data_for_model: Dict[str, Any] = { 'id': instance_id, 'guild_id': guild_id_str, 'template_id': template_id, 'name_i18n': instance_name_i18n_dict, 'descriptions_i18n': instance_descriptions_i18n_dict, 'exits': instance_exits, 'state': instance_state_data, 'is_active': bool(is_active), 'static_name': row.get('static_name'), 'static_connections': row.get('static_connections') }
                           location_obj = Location.from_dict(instance_data_for_model)
                           guild_instances_cache[location_obj.id] = location_obj.to_dict() # Store as dict
                           if template_id and not self.get_location_static(template_id): print(f"LocationManager: Warning: Template '{template_id}' not found for instance '{instance_id}'.")
                           loaded_instances_count += 1
                      except Exception as e: print(f"LocationManager: Error processing instance row (ID: {row.get('id', 'N/A')}): {e}."); traceback.print_exc();
        except Exception as e: print(f"LocationManager: ❌ Error during DB instance load for guild {guild_id_str}: {e}"); traceback.print_exc(); raise
        print(f"LocationManager.load_state: Successfully loaded {loaded_instances_count} instances for guild {guild_id_str}.")
        if self._settings: # Check if _settings is not None
            guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {})
            default_start_location_template_id = guild_settings.get('default_start_location_id', self._settings.get('default_start_location_id'))
            if default_start_location_template_id: await self._ensure_persistent_location_exists(guild_id_str, str(default_start_location_template_id))

    async def _ensure_persistent_location_exists(self, guild_id: str, location_template_id: str) -> Optional[Dict[str, Any]]:
        # ... (existing _ensure_persistent_location_exists logic - assuming it's correct) ...
        return None # Placeholder

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        # ... (existing save_state logic - assuming it's correct) ...
        pass

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        # ... (existing rebuild_runtime_caches logic - assuming it's correct) ...
        pass

    async def create_location_instance(self, guild_id: str, template_id: str, initial_state: Optional[Dict[str, Any]] = None, instance_name: Optional[str] = None, instance_description: Optional[str] = None, instance_exits: Optional[Dict[str, str]] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
        # ... (existing create_location_instance logic - assuming it's correct) ...
        return None # Placeholder

    def get_location_instance(self, guild_id: str, instance_id: str) -> Optional[Location]:
        guild_id_str = str(guild_id)
        instance_id_str = str(instance_id)
        guild_instances = self._location_instances.get(guild_id_str, {})
        instance_data_dict = guild_instances.get(instance_id_str) # This is already a dict
        if instance_data_dict:
            if not isinstance(instance_data_dict, dict):
                print(f"LocationManager: Warning: Cached instance data for {instance_id_str} is not a dict.")
                return None
            try:
                # Ensure 'state' which contains 'inventory' is properly handled
                if 'state' not in instance_data_dict or not isinstance(instance_data_dict['state'], dict):
                    instance_data_dict['state'] = {}
                if 'inventory' not in instance_data_dict['state'] or not isinstance(instance_data_dict['state']['inventory'], list):
                    instance_data_dict['state']['inventory'] = []
                return Location.from_dict(instance_data_dict)
            except Exception as e:
                print(f"LocationManager: Error creating Location object from dict for {instance_id_str}: {e}")
                traceback.print_exc()
                return None
        return None


    async def delete_location_instance(self, guild_id: str, instance_id: str, **kwargs: Any) -> bool:
        # ... (existing delete_location_instance logic - assuming it's correct) ...
        return False # Placeholder

    async def clean_up_location_contents(self, location_instance_id: str, **kwargs: Any) -> None:
        # ... (existing clean_up_location_contents logic - assuming it's correct) ...
        pass

    def get_location_name(self, guild_id: str, instance_id: str) -> Optional[str]:
        # ... (existing get_location_name logic - assuming it's correct) ...
        return None # Placeholder

    def get_connected_locations(self, guild_id: str, instance_id: str) -> Dict[str, str]:
        # ... (existing get_connected_locations logic - assuming it's correct) ...
        return {} # Placeholder

    async def update_location_state(self, guild_id: str, instance_id: str, state_updates: Dict[str, Any], **kwargs: Any) -> bool:
        # ... (existing update_location_state logic - assuming it's correct) ...
        return False # Placeholder

    def get_location_channel(self, guild_id: str, instance_id: str) -> Optional[int]:
        # ... (existing get_location_channel logic - assuming it's correct) ...
        return None # Placeholder

    def get_default_location_id(self, guild_id: str) -> Optional[str]:
        # ... (existing get_default_location_id logic - assuming it's correct) ...
        return None # Placeholder

    async def move_entity(self, guild_id: str, entity_id: str, entity_type: str, from_location_id: Optional[str], to_location_id: str, **kwargs: Any) -> bool:
        # ... (existing move_entity logic - assuming it's correct) ...
        return False # Placeholder

    async def handle_entity_arrival(self, location_id: str, entity_id: str, entity_type: str, **kwargs: Any) -> None:
        # ... (existing handle_entity_arrival logic - assuming it's correct) ...
        pass

    async def handle_entity_departure(self, location_id: str, entity_id: str, entity_type: str, **kwargs: Any) -> None:
        # ... (existing handle_entity_departure logic - assuming it's correct) ...
        pass

    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
        # ... (existing process_tick logic - assuming it's correct) ...
        pass

    def get_location_static(self, template_id: Optional[str]) -> Optional[Dict[str, Any]]:
        return self._location_templates.get(str(template_id)) if template_id is not None else None

    def _clear_guild_state_cache(self, guild_id: str) -> None:
        # ... (existing _clear_guild_state_cache logic - assuming it's correct) ...
        pass

    def mark_location_instance_dirty(self, guild_id: str, instance_id: str) -> None:
         guild_id_str = str(guild_id)
         instance_id_str = str(instance_id)
         if guild_id_str in self._location_instances and instance_id_str in self._location_instances[guild_id_str]:
              self._dirty_instances.setdefault(guild_id_str, set()).add(instance_id_str)

    async def create_location_instance_from_moderated_data(self, guild_id: str, location_data: Dict[str, Any], user_id: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # ... (existing create_location_instance_from_moderated_data logic - assuming it's correct) ...
        return None # Placeholder

    async def add_item_to_location(self, guild_id: str, location_id: str,
                                   item_template_id: str, quantity: int = 1,
                                   dropped_item_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Adds an item to a location's inventory (stored in location.state['inventory']).
        If dropped_item_data is provided, it uses that as a base.
        Otherwise, creates a new item entry from item_template_id.
        """
        log_prefix = f"LocationManager.add_item_to_location(loc='{location_id}', item_tpl='{item_template_id}'):"
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)

        location_obj = self.get_location_instance(guild_id_str, location_id_str)
        if not location_obj:
            print(f"{log_prefix} Location instance not found. Cannot add item.")
            return False

        # Ensure location_obj.state and location_obj.state['inventory'] exist and are correct types
        if not isinstance(location_obj.state, dict):
            location_obj.state = {} # Initialize state if it's not a dict
        if not isinstance(location_obj.state.get('inventory'), list):
            location_obj.state['inventory'] = []

        # The inventory is directly on the Location object if the model is set up that way,
        # or via location_obj.state['inventory']. Let's assume direct access via location_obj.inventory
        # which should map to location_obj.state['inventory'] by the model's properties.
        # For safety, we'll access via location_obj.state['inventory'] here.
        location_inventory: List[Dict[str, Any]] = location_obj.state['inventory']

        item_definition = None
        if self.rules_config and self.rules_config.item_definitions:
            item_definition = self.rules_config.item_definitions.get(item_template_id)

        is_stackable = item_definition.stackable if item_definition else True # Default to stackable if no def

        final_item_template_id = item_template_id
        final_quantity = quantity
        final_state_variables = {}
        # Use name from definition if available, otherwise fallback to template_id for new items
        item_name_for_new = item_definition.name if item_definition else item_template_id

        if dropped_item_data:
            final_item_template_id = dropped_item_data.get('template_id', dropped_item_data.get('item_id', item_template_id))
            final_quantity = dropped_item_data.get('quantity', quantity)
            final_state_variables = dropped_item_data.get('state_variables', {})
            # Potentially carry over custom name if items can have them, else use template name
            item_name_for_new = dropped_item_data.get('name', (item_definition.name if item_definition and item_definition.name else final_item_template_id))


        if is_stackable:
            for item_stack in location_inventory:
                if isinstance(item_stack, dict) and item_stack.get('template_id', item_stack.get('item_id')) == final_item_template_id:
                    # Basic stacking: just update quantity. More complex state merging might be needed if states differ.
                    # For now, assume states don't prevent stacking if template_id is same.
                    current_qty = item_stack.get('quantity', 0)
                    item_stack['quantity'] = current_qty + final_quantity
                    # If dropped item had state_variables, decide how/if to merge them.
                    # Simplest: last dropped item's state overwrites if not merging.
                    if final_state_variables: item_stack['state_variables'] = final_state_variables
                    self.mark_location_instance_dirty(guild_id_str, location_id_str)
                    print(f"{log_prefix} Added {final_quantity} of '{final_item_template_id}' to existing stack. New qty: {item_stack['quantity']}.")
                    return True

        # If not stackable, or no existing stack found, add new entry/entries
        # If not stackable, add 'quantity' number of individual items.
        # If stackable and new, add one stack with 'final_quantity'.
        num_individual_items_to_add = final_quantity if not is_stackable else 1
        quantity_per_new_item_entry = 1 if not is_stackable else final_quantity

        for _ in range(num_individual_items_to_add):
            new_item_entry: Dict[str, Any] = {
                "template_id": final_item_template_id, # Use 'template_id' consistently
                "quantity": quantity_per_new_item_entry,
                "instance_id": str(uuid.uuid4()), # New instance ID for this item on the ground
                "state_variables": final_state_variables.copy(), # Copy state vars
                "name": item_name_for_new # Store current name for display
            }
            location_inventory.append(new_item_entry)

        self.mark_location_instance_dirty(guild_id_str, location_id_str)
        print(f"{log_prefix} Added new stack/instance(s) of '{final_item_template_id}' (total qty: {final_quantity}) to location.")
        return True

    async def revert_location_state_variable_change(self, guild_id: str, location_id: str, variable_name: str, old_value: Any, **kwargs: Any) -> bool:
        """Reverts a specific state variable of a location instance."""
        location = self.get_location_instance(guild_id, location_id)
        if not location:
            print(f"LocationManager.revert_location_state_variable_change: Location {location_id} not found in guild {guild_id}.")
            return False

        if not isinstance(location.state, dict):
            location.state = {} # Should not happen if model is consistent

        location.state[variable_name] = old_value
        self.mark_location_instance_dirty(guild_id, location_id)
        # Consider calling save_state or a specific save_location_instance if immediate persistence needed
        print(f"LocationManager.revert_location_state_variable_change: Reverted state variable '{variable_name}' for location {location_id} in guild {guild_id}.")
        return True

    async def revert_location_inventory_change(
        self, guild_id: str, location_id: str,
        item_template_id: str, # Template ID of the item affected
        item_instance_id: Optional[str], # Instance ID, if applicable (e.g., for non-stackable or specific instance removal)
        change_action: str, # "added" (item was added to loc, revert is remove) or "removed" (item was removed from loc, revert is add back)
        quantity_changed: int,
        original_item_data: Optional[Dict[str, Any]], # Full data of the item if it was "removed" and needs to be "added" back
        **kwargs: Any
    ) -> bool:
        """Reverts a change in a location's inventory."""
        location = self.get_location_instance(guild_id, location_id)
        if not location:
            print(f"LocationManager.revert_location_inventory_change: Location {location_id} not found in guild {guild_id}.")
            return False

        if not isinstance(location.state, dict): location.state = {}
        if not isinstance(location.state.get('inventory'), list): location.state['inventory'] = []

        location_inventory: List[Dict[str, Any]] = location.state['inventory']

        if change_action == "added": # Item was originally added to location, so revert by removing it
            item_found_to_remove = False
            # Try to remove by instance_id first if provided and unique
            if item_instance_id:
                for i, item_entry in enumerate(location_inventory):
                    if item_entry.get("instance_id") == item_instance_id:
                        current_qty = item_entry.get('quantity', 0)
                        if current_qty > quantity_changed:
                            item_entry['quantity'] = current_qty - quantity_changed
                        else:
                            location_inventory.pop(i)
                        item_found_to_remove = True
                        break

            if not item_found_to_remove: # Fallback to template_id if instance_id not found or not provided
                for i, item_entry in enumerate(location_inventory):
                    entry_tpl_id = item_entry.get('template_id', item_entry.get('item_id'))
                    if entry_tpl_id == item_template_id:
                        current_qty = item_entry.get('quantity', 0)
                        if current_qty > quantity_changed:
                            item_entry['quantity'] = current_qty - quantity_changed
                        else:
                            location_inventory.pop(i) # Remove the whole stack if qty <= 0
                        item_found_to_remove = True
                        break

            if not item_found_to_remove:
                print(f"LocationManager.revert_location_inventory_change: Item (template: {item_template_id}, instance: {item_instance_id}) to revert 'added' action not found in location {location_id}.")
                # return False # Or True if "already gone" is acceptable for revert

        elif change_action == "removed": # Item was originally removed from location, so revert by adding it back
            if original_item_data:
                # If full data is provided, add it back. This is the safest way.
                # Need to decide if it merges with existing stacks or adds as new.
                # For simplicity, let's use add_item_to_location which handles stacking.
                await self.add_item_to_location(
                    guild_id, location_id,
                    item_template_id=original_item_data.get('template_id', item_template_id),
                    quantity=original_item_data.get('quantity', quantity_changed),
                    dropped_item_data=original_item_data # Pass full data for potential merging/state restoration
                )
            else:
                # If no original_item_data, create a new basic item entry. This might lose specific instance data.
                print(f"LocationManager.revert_location_inventory_change: Warning - No original_item_data for 'removed' action on item {item_template_id} in location {location_id}. Adding basic item.")
                await self.add_item_to_location(guild_id, location_id, item_template_id, quantity_changed)
        else:
            print(f"LocationManager.revert_location_inventory_change: Unknown change_action '{change_action}' for location {location_id}.")
            return False

        self.mark_location_instance_dirty(guild_id, location_id)
        print(f"LocationManager.revert_location_inventory_change: Reverted inventory change (action: {change_action}, item: {item_template_id}) for location {location_id}.")
        return True

    async def revert_location_exit_change(self, guild_id: str, location_id: str, exit_direction: str, old_target_location_id: Optional[str], **kwargs: Any) -> bool:
        """Reverts an exit in a location to its old target location ID."""
        location = self.get_location_instance(guild_id, location_id)
        if not location:
            print(f"LocationManager.revert_location_exit_change: Location {location_id} not found in guild {guild_id}.")
            return False

        if not isinstance(location.exits, dict):
            location.exits = {} # Should not happen

        if old_target_location_id is None:
            if exit_direction in location.exits:
                location.exits.pop(exit_direction)
        else:
            location.exits[exit_direction] = old_target_location_id

        self.mark_location_instance_dirty(guild_id, location_id)
        print(f"LocationManager.revert_location_exit_change: Reverted exit '{exit_direction}' for location {location_id} to '{old_target_location_id}'.")
        return True

    async def revert_location_activation_status(self, guild_id: str, location_id: str, old_is_active_status: bool, **kwargs: Any) -> bool:
        """Reverts the is_active status of a location instance."""
        location = self.get_location_instance(guild_id, location_id)
        if not location:
            print(f"LocationManager.revert_location_activation_status: Location {location_id} not found in guild {guild_id}.")
            return False

        location.is_active = old_is_active_status
        self.mark_location_instance_dirty(guild_id, location_id)
        print(f"LocationManager.revert_location_activation_status: Reverted is_active status for location {location_id} to {old_is_active_status}.")
        return True

# --- Конец класса LocationManager ---


