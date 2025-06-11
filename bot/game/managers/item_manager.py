# bot/game/managers/item_manager.py
"""
Manages item instances and item templates within the game.
"""
from __future__ import annotations
import json
import uuid
import traceback
import asyncio

from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union, TypedDict

from builtins import dict, set, list, str, int, bool, float

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.models.item import Item
    from bot.game.models.character import Character as CharacterModel
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.crafting_manager import CraftingManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.inventory_manager import InventoryManager

from bot.game.models.item import Item
from bot.utils.i18n_utils import get_i18n_text
from bot.ai.rules_schema import CoreGameRulesConfig, EquipmentSlotDefinition, ItemEffectDefinition, EffectProperty # Added EffectProperty
from bot.game.utils.stats_calculator import calculate_effective_stats

print("DEBUG: item_manager.py module loaded.")

class EquipResult(TypedDict):
    success: bool
    message: str
    character_id: Optional[str]
    item_id: Optional[str]
    slot_id: Optional[str]

class ItemManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    _item_templates: Dict[str, Dict[str, Any]]
    _items: Dict[str, Dict[str, "Item"]]

    _items_by_owner: Dict[str, Dict[str, Set[str]]]
    _items_by_location: Dict[str, Dict[str, Set[str]]]
    _dirty_items: Dict[str, Set[str]]
    _deleted_items: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        economy_manager: Optional["EconomyManager"] = None,
        crafting_manager: Optional["CraftingManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        inventory_manager: Optional["InventoryManager"] = None,
    ):
        print("Initializing ItemManager...")
        self._db_service = db_service
        self._settings = settings
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._location_manager = location_manager
        self._party_manager = party_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._economy_manager = economy_manager
        self._crafting_manager = crafting_manager
        self._game_log_manager = game_log_manager
        self._inventory_manager = inventory_manager

        self.rules_config: Optional[CoreGameRulesConfig] = None
        if self._rule_engine and hasattr(self._rule_engine, 'rules_config_data'):
            self.rules_config = self._rule_engine.rules_config_data

        self._item_templates = {}
        self._items = {}
        self._items_by_owner = {}
        self._items_by_location = {}
        self._dirty_items = {}
        self._deleted_items = {}

        self._load_item_templates()
        print("ItemManager initialized.")

    async def apply_item_effects(self, guild_id: str, character_id: str, item_instance: Dict[str, Any], rules_config: CoreGameRulesConfig) -> bool:
        """Applies on-equip effects of an item to a character."""
        if not self._status_manager or not self._character_manager:
            print(f"{log_prefix} StatusManager or CharacterManager not available.")
            return False

        item_template_id = item_instance.get('template_id')
        item_instance_id = item_instance.get('instance_id') # Assuming item_instance has an 'instance_id'

        if not item_template_id or not item_instance_id:
            print(f"{log_prefix} Item template ID or instance ID missing.")
            return False

        log_prefix = f"ItemManager.apply_item_effects(char='{character_id}', item='{item_template_id}', instance='{item_instance_id}'):"

        item_definition = rules_config.item_definitions.get(item_template_id)
        if not item_definition or not item_definition.on_equip_effects:
            # print(f"{log_prefix} No on-equip effects defined for item.") # Common, not an error
            return False

        effects_applied = False
        for effect_prop in item_definition.on_equip_effects:
            effect: ItemEffectDefinition = rules_config.item_effects.get(effect_prop.effect_id)
            if not effect:
                print(f"{log_prefix} Effect definition for '{effect_prop.effect_id}' not found in rules_config.item_effects.")
                continue

            for specific_effect in effect.effects: # ItemEffectDefinition contains a list of SpecificEffect
                if specific_effect.type == "apply_status":
                    status_def = rules_config.status_effects.get(specific_effect.status_effect_id)
                    if not status_def:
                        print(f"{log_prefix} Status definition for '{specific_effect.status_effect_id}' not found.")
                        continue

                    duration = specific_effect.duration_turns if specific_effect.duration_turns is not None else status_def.default_duration_turns
                    # Pass item_instance_id as source_item_instance_id
                    await self._status_manager.apply_status(
                        target_id=character_id,
                        target_type="character",
                        status_id=specific_effect.status_effect_id,
                        guild_id=guild_id,
                        duration_turns=duration,
                        source_item_instance_id=item_instance_id,
                        source_item_template_id=item_template_id
                    )
                    print(f"{log_prefix} Applied status '{specific_effect.status_effect_id}'.")
                    effects_applied = True
                # TODO: Handle other effect types like "stat_modifier" if they are to be applied directly
                # For now, stat_modifiers from items are expected to be part of the item's base_stats
                # and reflected in calculate_effective_stats.

        if effects_applied:
            self._character_manager.mark_character_dirty(guild_id, character_id)
        return effects_applied

    async def remove_item_effects(self, guild_id: str, character_id: str, item_instance: Dict[str, Any], rules_config: CoreGameRulesConfig) -> bool:
        """Removes on-equip effects of an item from a character."""
        if not self._status_manager or not self._character_manager:
            print(f"{log_prefix} StatusManager or CharacterManager not available.")
            return False

        item_template_id = item_instance.get('template_id')
        item_instance_id = item_instance.get('instance_id') # Assuming item_instance has an 'instance_id'

        if not item_template_id or not item_instance_id:
            print(f"{log_prefix} Item template ID or instance ID missing.")
            return False

        log_prefix = f"ItemManager.remove_item_effects(char='{character_id}', item='{item_template_id}', instance='{item_instance_id}'):"

        item_definition = rules_config.item_definitions.get(item_template_id)
        # No specific on_unequip_effects are defined in schema, so we remove based on what was applied.
        # Primarily, this means removing statuses that were sourced from this item instance.

        effects_removed = False
        # We rely on StatusManager to find statuses by source_item_instance_id
        # No need to iterate item_definition.on_equip_effects here unless we need to trigger specific "on_remove" logic
        # not covered by just removing the status.

        # The StatusManager should have a method to remove statuses by their source item instance ID.
        # Let's assume it's named remove_statuses_by_source_item_instance
        if hasattr(self._status_manager, 'remove_statuses_by_source_item_instance'):
            removed_count = await self._status_manager.remove_statuses_by_source_item_instance(
                guild_id=guild_id,
                target_id=character_id,
                source_item_instance_id=item_instance_id
            )
            if removed_count > 0:
                print(f"{log_prefix} Removed {removed_count} status(es) sourced from item instance '{item_instance_id}'.")
                effects_removed = True
        else:
            print(f"{log_prefix} StatusManager does not have 'remove_statuses_by_source_item_instance' method.")
            # Fallback or alternative: iterate through active statuses and check source_item_instance_id
            # This is less efficient and should ideally be handled by StatusManager.
            # For now, we'll proceed assuming the method exists or will be added to StatusManager.

        # If there were other types of effects (e.g., direct stat modifications not handled by recalculation),
        # they would need to be reversed here.

        if effects_removed:
            self._character_manager.mark_character_dirty(guild_id, character_id)
        return effects_removed

    # --- Equip / Unequip Logic (largely managed by EquipmentManager now, but stubs might remain or be simplified) ---
    # These equip/unequip methods here are becoming simplified as EquipmentManager takes more control.
    # They might be used for internal inventory state updates if not fully deprecated.

    def _unequip_item_from_slot(self, character_inventory_data: List[Dict[str, Any]], slot_id_to_clear: str) -> bool:
        # This is a utility for manipulating the inventory list directly.
        item_was_unequipped = False
        for item_entry in character_inventory_data:
            if item_entry.get("equipped") and item_entry.get("slot_id") == slot_id_to_clear:
                item_entry["equipped"] = False
                item_entry.pop("slot_id", None)
                item_was_unequipped = True
        return item_was_unequipped

    async def equip_item(self,
                         character_id: str,
                         guild_id: str,
                         item_template_id_to_equip: str, # This should ideally be item_instance_id
                         rules_config: CoreGameRulesConfig,
                         slot_id_preference: Optional[str] = None
                        ) -> EquipResult:
        # This method should be significantly simplified or deprecated in favor of EquipmentManager.equip_item
        # EquipmentManager will handle fetching item_instance, checking rules, calling apply_item_effects,
        # and then updating character.equipment and character.inventory.
        # For now, keeping a structure similar to before but acknowledging its future deprecation.

        # log_prefix = f"ItemManager.equip_item(char='{character_id}', item_template='{item_template_id_to_equip}'):"
        # print(f"{log_prefix} Called. Note: This method is slated for simplification/deprecation by EquipmentManager.")

        if not self._character_manager or not self._db_service or not self._inventory_manager:
            return EquipResult(success=False, message="Core services (Character, DB, Inventory) not available.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)

        character: Optional["CharacterModel"] = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return EquipResult(success=False, message="Character not found.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)

        # This logic needs to use item_instance_id from InventoryManager instead of template_id
        # For now, we'll assume the caller (soon EquipmentManager) provides an item_instance_id
        # and this method is more about the raw DB update after EquipmentManager has done the checks.
        # The current implementation based on item_template_id_to_equip and direct inventory manipulation
        # is problematic and will be fixed when EquipmentManager is fully implemented.

        # --- Placeholder for new logic: ---
        # 1. EquipmentManager would call this with an item_instance_id.
        # 2. This method would update the character's inventory data (mark as equipped, set slot).
        # 3. CharacterManager.mark_character_dirty() would be called.
        # 4. calculate_effective_stats is called by EquipmentManager.
        # --- End Placeholder ---

        # Fallback to old logic for now, but with a warning
        # print(f"{log_prefix} WARNING: Using outdated inventory search logic. Needs update for item_instance_id.")
        inventory_list_json = getattr(character, 'inventory', "[]")
        character_inventory_data: List[Dict[str, Any]] = json.loads(inventory_list_json) if isinstance(inventory_list_json, str) else (inventory_list_json if isinstance(inventory_list_json, list) else [])

        item_entry_to_equip: Optional[Dict[str, Any]] = None
        item_index_in_inventory: Optional[int] = None

        # THIS SEARCH IS FLAWED - should use instance_id
        for i, entry in enumerate(character_inventory_data):
            entry_template_id = entry.get('template_id') # or entry.get('item_id') is old
            if entry_template_id == item_template_id_to_equip and not entry.get('equipped'):
                # We need to ensure this is the correct *instance* if multiple exist.
                # This is why item_instance_id is critical.
                item_entry_to_equip = entry
                item_index_in_inventory = i
                break

        if not item_entry_to_equip or item_index_in_inventory is None:
            return EquipResult(success=False, message=f"Unequipped item '{item_template_id_to_equip}' (by template) not found. Use instance ID.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)

        # The rest of the slot finding logic and inventory update can remain similar,
        # but it's being done on character_inventory_data which is a direct field manipulation.
        # EquipmentManager will provide the target_slot_id after its own checks.

        item_template = self.get_item_template(item_template_id_to_equip) # From rules_config ideally
        if not item_template: # Should use rules_config.item_definitions
            item_def_from_rules = rules_config.item_definitions.get(item_template_id_to_equip)
            if not item_def_from_rules:
                return EquipResult(success=False, message=f"Item template '{item_template_id_to_equip}' not found in rules.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)
            item_template = {"type": item_def_from_rules.type, "name": item_def_from_rules.name} # simplified

        item_type = item_template.get("type", "unknown")
        target_slot_id: Optional[str] = None

        current_rules_config = rules_config
        if not current_rules_config:
             return EquipResult(success=False, message="Game rules for equipment slots not available.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=None)

        if slot_id_preference:
            if slot_id_preference in current_rules_config.equipment_slots and \
               item_type in current_rules_config.equipment_slots[slot_id_preference].compatible_item_types:
                target_slot_id = slot_id_preference
            else:
                return EquipResult(success=False, message=f"Preferred slot '{slot_id_preference}' is not compatible with item type '{item_type}'.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)
        else: # Auto-find slot
            for slot_def_id, slot_def in current_rules_config.equipment_slots.items():
                if item_type in slot_def.compatible_item_types:
                    is_occupied = any(inv_item.get("equipped") and inv_item.get("slot_id") == slot_def_id for inv_item in character_inventory_data)
                    if not is_occupied:
                        target_slot_id = slot_def_id
                        break
            if not target_slot_id: # If all preferred slots are occupied, try to replace existing
                 for slot_def_id, slot_def in current_rules_config.equipment_slots.items():
                     if item_type in slot_def.compatible_item_types:
                         target_slot_id = slot_def_id
                         break # First compatible slot, even if it means unequipping
        if not target_slot_id:
            return EquipResult(success=False, message=f"No suitable slot found for item type '{item_type}'.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=None)

        # Unequip whatever is in target_slot_id (if anything)
        self._unequip_item_from_slot(character_inventory_data, target_slot_id)

        # Equip the new item
        character_inventory_data[item_index_in_inventory]["equipped"] = True
        character_inventory_data[item_index_in_inventory]["slot_id"] = target_slot_id
        character.inventory = json.dumps(character_inventory_data) # This direct manipulation is what EquipmentManager will abstract

        # Effects should be applied by EquipmentManager *before* this, or this method needs item_instance
        # await self.apply_item_effects(guild_id, character_id, item_entry_to_equip, current_rules_config) # item_entry_to_equip needs instance_id

        effective_stats = await calculate_effective_stats(self._db_service, character.id, "player", current_rules_config)
        character.effective_stats_json = json.dumps(effective_stats)
        self._character_manager.mark_character_dirty(guild_id, character_id)

        item_name_display = item_template.get('name', item_template_id_to_equip)
        return EquipResult(success=True, message=f"Item '{item_name_display}' equipped to slot '{target_slot_id}'. (Legacy IM method)", character_id=character_id, item_id=item_template_id_to_equip, slot_id=target_slot_id)

    async def unequip_item(self,
                           character_id: str,
                           guild_id: str,
                           rules_config: CoreGameRulesConfig,
                           # item_template_id_to_unequip: Optional[str] = None, # Should be item_instance_id
                           item_instance_id_to_unequip: Optional[str] = None,
                           slot_id_to_unequip: Optional[str] = None
                          ) -> EquipResult:
        # This method also needs to be simplified or deprecated for EquipmentManager.
        # log_prefix = f"ItemManager.unequip_item(char='{character_id}', item_instance='{item_instance_id_to_unequip}', slot='{slot_id_to_unequip}'):"
        # print(f"{log_prefix} Called. Note: This method is slated for simplification/deprecation by EquipmentManager.")

        item_template_id_to_unequip = None # Will be derived from instance if needed

        if not self._character_manager or not self._db_service or not self._inventory_manager:
             return EquipResult(success=False, message="Core services not available.", character_id=character_id, item_id=item_instance_id_to_unequip, slot_id=slot_id_to_unequip)

        character: Optional["CharacterModel"] = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return EquipResult(success=False, message="Character not found.", character_id=character_id, item_id=item_instance_id_to_unequip, slot_id=slot_id_to_unequip)

        inventory_list_json = getattr(character, 'inventory', "[]")
        character_inventory_data: List[Dict[str, Any]] = json.loads(inventory_list_json) if isinstance(inventory_list_json, str) else (inventory_list_json if isinstance(inventory_list_json, list) else [])

        item_found_and_unequipped = False
        unequipped_item_template_id: Optional[str] = None
        actual_slot_unequipped: Optional[str] = None
        item_instance_that_was_unequipped: Optional[Dict[str, Any]] = None

        current_rules_config = rules_config
        if not current_rules_config: # Should use self.rules_config if rules_config not passed
             return EquipResult(success=False, message="Game rules not available.", character_id=character_id, item_id=item_instance_id_to_unequip, slot_id=slot_id_to_unequip)

        if not item_instance_id_to_unequip and not slot_id_to_unequip:
            return EquipResult(success=False, message="No item instance ID or slot specified to unequip.", character_id=character_id)

        for item_entry in character_inventory_data:
            if item_entry.get("equipped"):
                matches_criteria = False
                if slot_id_to_unequip and item_entry.get("slot_id") == slot_id_to_unequip:
                    matches_criteria = True
                elif item_instance_id_to_unequip and item_entry.get("instance_id") == item_instance_id_to_unequip:
                    matches_criteria = True

                if matches_criteria:
                    unequipped_item_template_id = item_entry.get('template_id')
                    item_instance_that_was_unequipped = item_entry # Capture the whole entry
                    item_entry["equipped"] = False
                    actual_slot_unequipped = item_entry.pop("slot_id", None)
                    item_found_and_unequipped = True
                    break

        if not item_found_and_unequipped:
            msg = f"Equipped item matching criteria not found."
            if slot_id_to_unequip: msg = f"No item equipped in slot '{slot_id_to_unequip}'."
            elif item_instance_id_to_unequip: msg = f"Item instance '{item_instance_id_to_unequip}' is not equipped or not found."
            return EquipResult(success=False, message=msg, character_id=character_id, item_id=item_instance_id_to_unequip, slot_id=slot_id_to_unequip)

        character.inventory = json.dumps(character_inventory_data) # Direct manipulation

        # Effects should be removed by EquipmentManager *after* this, using item_instance_that_was_unequipped
        if item_instance_that_was_unequipped:
            pass # await self.remove_item_effects(guild_id, character_id, item_instance_that_was_unequipped, current_rules_config)

        effective_stats = await calculate_effective_stats(self._db_service, character.id, "player", current_rules_config)
        character.effective_stats_json = json.dumps(effective_stats)
        self._character_manager.mark_character_dirty(guild_id, character_id)

        item_name = unequipped_item_template_id # Fallback
        item_def_from_rules = current_rules_config.item_definitions.get(unequipped_item_template_id) if unequipped_item_template_id else None
        if item_def_from_rules: item_name = item_def_from_rules.name

        return EquipResult(success=True, message=f"Item '{item_name}' unequipped from slot '{actual_slot_unequipped}'. (Legacy IM method)", character_id=character_id, item_id=unequipped_item_template_id, slot_id=actual_slot_unequipped)


    async def use_item(self, guild_id: str, character_user: CharacterModel, item_template_id: str,
                       rules_config: CoreGameRulesConfig, target_entity: Optional[Any] = None) -> Dict[str, Any]:
        """Uses an item from character's inventory, applying its effects."""
        log_prefix = f"ItemManager.use_item(char='{character_user.id}', item='{item_template_id}'):"

        if not self._character_manager or not self._inventory_manager or not self._status_manager or not self._rule_engine:
            return {"success": False, "message": "Один из необходимых менеджеров не инициализирован.", "state_changed": False}
        if not rules_config: # Use self.rules_config if not passed
             return {"success": False, "message": "Конфигурация правил игры не доступна.", "state_changed": False}

        # This should use item_instance_id not item_template_id for consumption
        # For now, assumes InventoryManager.has_item and remove_item can work with template_id for stackable items.
        has_item_check = await self._inventory_manager.has_item(guild_id, character_user.id, item_template_id=item_template_id)
        if not has_item_check: # This will be true if any quantity exists
            return {"success": False, "message": "У вас нет такого предмета.", "state_changed": False}

        item_definition_from_rules = rules_config.item_definitions.get(item_template_id)
        if not item_definition_from_rules:
            return {"success": False, "message": "Неизвестный предмет (нет в rules_config).", "state_changed": False}

        item_name_display = item_definition_from_rules.name
        # Item effects are now directly on ItemDefinition in rules_config, not a separate item_effects config key
        item_effects_list = item_definition_from_rules.on_use_effects
        if not item_effects_list:
            return {"success": False, "message": f"{item_name_display} не имеет известных эффектов использования.", "state_changed": False}

        message_parts = [f"{character_user.name} использует {item_name_display}."]
        state_changed = False

        # Outer loop for each EffectProperty in on_use_effects
        for effect_prop in item_effects_list: # effect_prop is EffectProperty
            effect_def: Optional[ItemEffectDefinition] = rules_config.item_effects.get(effect_prop.effect_id)
            if not effect_def:
                message_parts.append(f"Определение эффекта '{effect_prop.effect_id}' не найдено.")
                continue

            # Determine the default target for this entire ItemEffectDefinition group
            default_target_for_effect_group: Optional[Union[CharacterModel, Any]] = character_user
            if effect_def.target_policy == "requires_target":
                if not target_entity:
                    message_parts.append(f"Эффект '{effect_prop.effect_id}' требует цель, но цель не указана.")
                    continue # Skip this ItemEffectDefinition
                default_target_for_effect_group = target_entity
            elif effect_def.target_policy == "optional_target" and target_entity:
                default_target_for_effect_group = target_entity
            elif effect_def.target_policy == "no_target": # E.g. summoning, environment effect
                 default_target_for_effect_group = None

            # Process direct_health_effects
            if effect_def.direct_health_effects:
                for dhe in effect_def.direct_health_effects:
                    target_obj_for_health = default_target_for_effect_group
                    if not target_obj_for_health:
                        message_parts.append(f"Эффект здоровья '{dhe.effect_type}' не может быть применен без цели.")
                        continue

                    target_id = getattr(target_obj_for_health, 'id', None)
                    target_name = getattr(target_obj_for_health, 'name', target_id)
                    # Assuming CharacterModel and NPC model have 'hp' and 'max_health' attributes
                    current_hp = getattr(target_obj_for_health, 'hp', None)
                    max_hp = getattr(target_obj_for_health, 'max_health', None)

                    if current_hp is None or max_hp is None:
                        message_parts.append(f"Не удалось получить информацию о здоровье для {target_name}.")
                        continue

                    if dhe.effect_type == "heal":
                        if current_hp < max_hp:
                            heal_amount = dhe.amount
                            new_hp = min(current_hp + heal_amount, max_hp)
                            setattr(target_obj_for_health, 'hp', new_hp)
                            message_parts.append(f"{target_name} исцелен(а) на {new_hp - current_hp} HP (стало {new_hp}/{max_hp}).")
                            state_changed = True
                        else:
                            message_parts.append(f"{target_name} уже имеет полное здоровье.")
                    elif dhe.effect_type == "damage":
                        damage_amount = dhe.amount
                        new_hp = current_hp - damage_amount
                        setattr(target_obj_for_health, 'hp', new_hp) # update_health might be better for death checks
                        message_parts.append(f"{target_name} получает {damage_amount} урона (стало {new_hp}/{max_hp}).")
                        # TODO: Call a method like character_manager.update_health(guild_id, target_id, -damage_amount)
                        # to properly handle damage and potential death.
                        state_changed = True
                    # Add more DirectHealthEffect types if necessary

            # Process apply_status_effects
            if effect_def.apply_status_effects:
                for aser in effect_def.apply_status_effects:
                    final_target_for_status = None
                    if aser.target == "self":
                        final_target_for_status = default_target_for_effect_group
                    elif aser.target == "target_entity":
                        if target_entity:
                            final_target_for_status = target_entity
                        else:
                            message_parts.append(f"Статус эффект '{aser.status_effect_id}' требует конкретную цель, но она не указана.")
                            continue # Skip this status effect
                    else: # Default to the main target of the effect group
                        final_target_for_status = default_target_for_effect_group

                    if not final_target_for_status:
                        message_parts.append(f"Не удалось определить цель для статуса '{aser.status_effect_id}'.")
                        continue

                    target_id = getattr(final_target_for_status, 'id', None)
                    target_name = getattr(final_target_for_status, 'name', target_id)

                    # Determine type for StatusManager
                    entity_type_for_status = "player" if hasattr(final_target_for_status, 'discord_id') else "npc"

                    if self._status_manager and target_id:
                        status_def_rules = rules_config.status_effects.get(aser.status_effect_id)
                        duration = aser.duration_turns
                        if duration is None and status_def_rules: # Fallback to default duration from StatusEffectDefinition
                            duration = status_def_rules.default_duration_turns

                        if duration is not None: # Ensure there is a duration to apply
                            await self._status_manager.apply_status(
                                target_id=target_id,
                                target_type=entity_type_for_status,
                                status_id=aser.status_effect_id,
                                guild_id=guild_id,
                                duration_turns=duration
                            )
                            message_parts.append(f"{target_name} получает эффект '{aser.status_effect_id}'.")
                            state_changed = True
                        else:
                            message_parts.append(f"Не удалось определить длительность для статуса '{aser.status_effect_id}'.")
                    else:
                        message_parts.append(f"StatusManager не доступен или цель некорректна для применения статуса '{aser.status_effect_id}'.")

            # Process learn_spells (applies to character_user only)
            if effect_def.learn_spells:
                for lsr in effect_def.learn_spells:
                    if self._character_manager:
                        # Assuming CharacterManager has a method like learn_spell
                        if hasattr(self._character_manager, 'learn_spell'):
                            # success = await self._character_manager.learn_spell(guild_id, character_user.id, lsr.spell_id)
                            # if success:
                            #     message_parts.append(f"{character_user.name} выучил(а) заклинание '{lsr.spell_id}'.")
                            #     state_changed = True
                            # else:
                            #     message_parts.append(f"{character_user.name} не смог(ла) выучить заклинание '{lsr.spell_id}'.")
                            print(f"PLACEHOLDER: Character {character_user.id} attempts to learn spell {lsr.spell_id}. Call CharacterManager.learn_spell.")
                            message_parts.append(f"{character_user.name} пытается выучить заклинание '{lsr.spell_id}'.") # Example message
                            state_changed = True # Assume learning changes state for now
                        else:
                            print(f"CharacterManager does not have 'learn_spell' method. Spell '{lsr.spell_id}' not learned by {character_user.id}.")
                            message_parts.append(f"Функция изучения заклинаний не доступна для '{lsr.spell_id}'.")
                    else:
                        message_parts.append("CharacterManager не доступен для изучения заклинаний.")

            # Process grant_resources
            if effect_def.grant_resources:
                for grr in effect_def.grant_resources:
                    target_obj_for_resource = default_target_for_effect_group
                    if not target_obj_for_resource:
                        message_parts.append(f"Ресурс '{grr.resource_name}' не может быть выдан без цели.")
                        continue

                    target_id = getattr(target_obj_for_resource, 'id', None)
                    target_name = getattr(target_obj_for_resource, 'name', target_id)

                    if grr.resource_name == "gold" and hasattr(target_obj_for_resource, 'gold'):
                        current_gold = getattr(target_obj_for_resource, 'gold', 0)
                        setattr(target_obj_for_resource, 'gold', current_gold + grr.amount)
                        message_parts.append(f"{target_name} получает {grr.amount} золота.")
                        state_changed = True
                    elif grr.resource_name == "xp" and hasattr(target_obj_for_resource, 'xp'):
                        current_xp = getattr(target_obj_for_resource, 'xp', 0)
                        setattr(target_obj_for_resource, 'xp', current_xp + grr.amount)
                        # May also need to update unspent_xp or call a level-up check
                        message_parts.append(f"{target_name} получает {grr.amount} опыта.")
                        state_changed = True
                    elif grr.resource_name == "mp" and hasattr(target_obj_for_resource, 'mp') and hasattr(target_obj_for_resource, 'max_mp'):
                        current_mp = getattr(target_obj_for_resource, 'mp', 0)
                        max_mp = getattr(target_obj_for_resource, 'max_mp', current_mp) # Assume max_mp if not present
                        new_mp = min(current_mp + grr.amount, max_mp)
                        setattr(target_obj_for_resource, 'mp', new_mp)
                        message_parts.append(f"{target_name} восстанавливает {new_mp - current_mp} MP.")
                        state_changed = True
                    else:
                        # Placeholder for other resource types
                        print(f"PLACEHOLDER: Grant resource '{grr.resource_name}' (amount: {grr.amount}) to {target_name} ({target_id}). Implement specific logic.")
                        message_parts.append(f"{target_name} получает {grr.amount} ресурса '{grr.resource_name}'.")
                        state_changed = True # Assume state changes for unknown resources for now

            # TODO: Handle effect_def.stat_modifiers if they are meant to be temporary "on_use" effects
            # This would require a mechanism to apply and possibly time out these direct modifiers
            # if they are not channeled through status effects. For now, assuming stat_modifiers on ItemEffectDefinition
            # are primarily for passive/equipped effects handled by calculate_effective_stats.

        if item_definition_from_rules.consumable:
            # InventoryManager needs to handle instance_id for non-stackables, or template_id + quantity for stackables
            # Assume remove_item can take item_template_id for stackable consumables
            removed = await self._inventory_manager.remove_item(guild_id, character_user.id, item_template_id=item_template_id, quantity_to_remove=1)
            if removed:
                message_parts.append(f"{item_name_display} был(а) использован(а).")
                state_changed = True # Already true if effects applied, but good to ensure
            else:
                # This is a critical failure if effects applied but item wasn't consumed.
                # Ideally, this would be a transaction or have rollback logic.
                message_parts.append(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось израсходовать {item_name_display} после применения эффектов.")
                # For now, we proceed, but this indicates a potential issue.

        if state_changed:
            # Update effective stats for the user
            if self._db_service and self.rules_config:
                try:
                    new_stats_user = await calculate_effective_stats(self._db_service, character_user.id, "player", self.rules_config)
                    character_user.effective_stats_json = json.dumps(new_stats_user)
                    # print(f"{log_prefix} Updated effective_stats_json for user {character_user.id}")
                except Exception as e:
                    print(f"{log_prefix} Error calculating/updating effective stats for user {character_user.id}: {e}")

            self._character_manager.mark_character_dirty(guild_id, character_user.id)

            # Update effective stats for the target if it exists, is different, and was affected
            if target_entity and hasattr(target_entity, 'id') and target_entity.id != character_user.id:
                target_entity_obj = None
                target_entity_type = None

                # Determine target type and fetch full object if necessary
                # (Assuming target_entity passed in might not be the full DB model instance from the right manager)
                if hasattr(target_entity, 'discord_id'): # Heuristic for Player object (CharacterModel)
                    target_entity_obj = await self._character_manager.get_character(guild_id, target_entity.id)
                    target_entity_type = "player"
                elif hasattr(target_entity, 'template_id'): # Heuristic for NPC object (assuming it has template_id)
                    # Need to ensure NpcManager is available and has get_npc method
                    if self._npc_manager:
                        target_entity_obj = await self._npc_manager.get_npc(guild_id, target_entity.id)
                        target_entity_type = "npc"
                    else:
                        print(f"{log_prefix} NpcManager not available to fetch target NPC {target_entity.id}")

                if target_entity_obj and target_entity_type and self._db_service and self.rules_config:
                    try:
                        new_stats_target = await calculate_effective_stats(self._db_service, target_entity_obj.id, target_entity_type, self.rules_config)
                        target_entity_obj.effective_stats_json = json.dumps(new_stats_target)
                        # print(f"{log_prefix} Updated effective_stats_json for target {target_entity_type} {target_entity_obj.id}")

                        if target_entity_type == "player":
                            self._character_manager.mark_character_dirty(guild_id, target_entity_obj.id)
                        elif target_entity_type == "npc" and self._npc_manager:
                            if hasattr(self._npc_manager, 'mark_npc_dirty'):
                                self._npc_manager.mark_npc_dirty(guild_id, target_entity_obj.id)
                            else:
                                print(f"{log_prefix} NpcManager does not have mark_npc_dirty method for {target_entity_obj.id}")
                                # Potentially save directly if NpcManager handles persistence differently
                                # await self._npc_manager.save_npc(guild_id, target_entity_obj) # Example if save_npc exists
                    except Exception as e:
                        print(f"{log_prefix} Error calculating/updating effective stats for target {target_entity_type} {target_entity_obj.id}: {e}")
                elif target_entity_obj is None and hasattr(target_entity, 'id'):
                    print(f"{log_prefix} Could not fully identify or fetch target entity {target_entity.id} for stat update.")


        return {"success": True, "message": " ".join(message_parts), "state_changed": state_changed}


    def _load_item_templates(self):
        # This method likely needs to be updated to load from rules_config.item_definitions
        # instead of self._settings, or self.rules_config is the source of truth after init.
        # For now, assuming self.rules_config.item_definitions is populated elsewhere (e.g. RuleEngine)
        # and this method is vestigial or for a different type of template.
        # If ItemManager is meant to be the source of truth for item_definitions by loading them,
        # this needs significant rework.
        # print("ItemManager: _load_item_templates called. Consider if this is still needed with CoreGameRulesConfig.")
        self._item_templates = {} # This might be for legacy item templates, not the rule_config ones.
                                 # If so, it needs to be clarified what these are.
                                 # If not, this should not be used, and get_item_template should use rules_config.
        # Example: if self.rules_config: self._item_templates = self.rules_config.item_definitions
        # This would make get_item_template directly use the Pydantic models.
        # However, the existing get_item_template returns Dict[str, Any], not Pydantic model.
        # This suggests a potential mismatch or transitional state.

    def get_item_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves an item template definition.
        Ideally, this should fetch from self.rules_config.item_definitions and return the Pydantic model
        or a dict representation of it.
        The current implementation using self._item_templates might be outdated if rules_config is primary.
        """
        if self.rules_config and template_id in self.rules_config.item_definitions:
            item_def_model = self.rules_config.item_definitions[template_id]
            # Convert Pydantic model to dict if the rest of the system expects dicts.
            # However, it's better to use the model directly if possible.
            # For now, returning as dict to match existing expectation.
            try:
                return item_def_model.model_dump(mode='python') #.dict() for Pydantic v1
            except AttributeError: # Fallback for older Pydantic or if model_dump is not preferred
                 return json.loads(item_def_model.model_dump_json()) #.json() for Pydantic v1


        # Fallback to old _item_templates if not in rules_config (should be deprecated)
        # print(f"ItemManager.get_item_template: Template '{template_id}' not in rules_config, checking legacy _item_templates.")
        return self._item_templates.get(str(template_id))


    async def get_all_item_instances(self, guild_id: str) -> List["Item"]:
        # This is for runtime Item instances, not templates. Seems okay.
        guild_id_str = str(guild_id)
        return list(self._items.get(guild_id_str, {}).values())

    async def get_items_by_owner(self, guild_id: str, owner_id: str) -> List["Item"]:
        guild_id_str = str(guild_id)
        owner_id_str = str(owner_id)
        owner_item_ids = self._items_by_owner.get(guild_id_str, {}).get(owner_id_str, set())
        guild_items_cache = self._items.get(guild_id_str, {})
        return [item_obj for item_id in owner_item_ids if (item_obj := guild_items_cache.get(item_id)) is not None]

    async def get_items_in_location(self, guild_id: str, location_id: str) -> List["Item"]:
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        location_item_ids = self._items_by_location.get(guild_id_str, {}).get(location_id_str, set())
        guild_items_cache = self._items.get(guild_id_str, {})
        return [item_obj for item_id in location_item_ids if (item_obj := guild_items_cache.get(item_id)) is not None]

    def get_item_template_display_name(self, template_id: str, lang: str, default_lang: str = "en") -> str:
        # Should use rules_config
        if self.rules_config and template_id in self.rules_config.item_definitions:
            item_def = self.rules_config.item_definitions[template_id]
            # Assuming ItemDefinition has i18n capabilities or a simple 'name' field
            return getattr(item_def, 'name', f"Item '{template_id}' name missing")
        return f"Item template '{template_id}' not found in rules"

    def get_item_template_display_description(self, template_id: str, lang: str, default_lang: str = "en") -> str:
        if self.rules_config and template_id in self.rules_config.item_definitions:
            item_def = self.rules_config.item_definitions[template_id]
            return getattr(item_def, 'description', f"Item '{template_id}' description missing")
        return f"Item template '{template_id}' not found in rules"

    def get_item_instance(self, guild_id: str, item_id: str) -> Optional["Item"]:
        # This is for runtime Item instances. Seems okay.
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        return self._items.get(guild_id_str, {}).get(item_id_str)

    # Methods like create_item_instance, remove_item_instance, update_item_instance,
    # save_item, load_state, etc. are complex and deal with DB/cache.
    # For now, assuming they are mostly compatible with InventoryManager handling the character.inventory (JSON list)
    # and this ItemManager handling the global item instances (if any are not just in inventories).
    # The distinction between Item (DB model) and item dicts in character.inventory needs to be clear.
    # InventoryManager should be the source of truth for what a character possesses.
    # ItemManager might manage items "in the world" or item templates.

    async def create_item_instance(self, guild_id: str, template_id: str, owner_id: Optional[str] = None, owner_type: Optional[str] = None, location_id: Optional[str] = None, quantity: float = 1.0, initial_state: Optional[Dict[str, Any]] = None, is_temporary: bool = False, **kwargs: Any) -> Optional["Item"]:
        guild_id_str = str(guild_id); template_id_str = str(template_id)
        if self._db_service is None: return None

        # Get template from rules_config
        if not self.rules_config or template_id_str not in self.rules_config.item_definitions:
            print(f"ItemManager.create_item_instance: Template '{template_id_str}' not found in rules_config.")
            return None
        # template = self.get_item_template(template_id_str) # Uses the new get_item_template
        # if not template: return None # Already checked by rules_config lookup

        if quantity <= 0: return None
        new_item_id = str(uuid.uuid4()) # This is for DB based items. InventoryManager might use its own IDs for inventory entries.

        item_data_for_model: Dict[str, Any] = {
            'id': new_item_id,
            'guild_id': guild_id_str,
            'template_id': template_id_str,
            'quantity': float(quantity),
            'owner_id': str(owner_id) if owner_id else None,
            'owner_type': str(owner_type) if owner_type else None,
            'location_id': str(location_id) if location_id else None,
            'state_variables': initial_state or {},
            'is_temporary': is_temporary
        }
        new_item = Item.from_dict(item_data_for_model)
        if not await self.save_item(new_item, guild_id_str): return None
        # self._update_lookup_caches_add(guild_id_str, new_item.to_dict()) # save_item should handle this
        if self._game_log_manager: asyncio.create_task(self._game_log_manager.log_event(guild_id=guild_id_str, event_type="ITEM_CREATED_WORLD", details={"item_id": new_item.id, "template_id": template_id_str, "location":location_id}))
        return new_item

    async def remove_item_instance(self, guild_id: str, item_id: str, **kwargs: Any) -> bool:
        # This removes a world item instance (from DB and cache)
        guild_id_str, item_id_str = str(guild_id), str(item_id)
        item_to_remove = self.get_item_instance(guild_id_str, item_id_str) # from self._items cache
        if not item_to_remove:
            # print(f"ItemManager.remove_item_instance: Item '{item_id_str}' not found in cache for guild '{guild_id_str}'.")
            # Check if already marked deleted
            return True if guild_id_str in self._deleted_items and item_id_str in self._deleted_items[guild_id_str] else False

        if self._db_service and self._db_service.adapter:
            await self._db_service.adapter.execute('DELETE FROM items WHERE id = $1 AND guild_id = $2', (item_id_str, guild_id_str))

        guild_items_cache = self._items.get(guild_id_str, {})
        guild_items_cache.pop(item_id_str, None)
        if not guild_items_cache: self._items.pop(guild_id_str, None)

        self._update_lookup_caches_remove(guild_id_str, item_to_remove.to_dict())
        self._dirty_items.get(guild_id_str, set()).discard(item_id_str)
        self._deleted_items.setdefault(guild_id_str, set()).add(item_id_str)
        # print(f"ItemManager.remove_item_instance: Item '{item_id_str}' removed from world.")
        return True

    async def update_item_instance(self, guild_id: str, item_id: str, updates: Dict[str, Any], **kwargs: Any) -> bool:
        # Updates a world item instance
        guild_id_str, item_id_str = str(guild_id), str(item_id)
        item_object = self.get_item_instance(guild_id_str, item_id_str)
        if not item_object: return False

        old_item_dict_for_lookup = item_object.to_dict()
        for key, value in updates.items():
            if hasattr(item_object, key):
                if key == 'state_variables' and isinstance(value, dict):
                    current_state = getattr(item_object, key, {})
                    if current_state is None: current_state = {} # Ensure it's a dict
                    current_state.update(value)
                    setattr(item_object, key, current_state)
                else: setattr(item_object, key, value)

        new_item_dict_for_lookup = item_object.to_dict()

        # Check if lookup-relevant fields changed
        if old_item_dict_for_lookup.get('owner_id') != new_item_dict_for_lookup.get('owner_id') or \
           old_item_dict_for_lookup.get('owner_type') != new_item_dict_for_lookup.get('owner_type') or \
           old_item_dict_for_lookup.get('location_id') != new_item_dict_for_lookup.get('location_id'):
            self._update_lookup_caches_remove(guild_id_str, old_item_dict_for_lookup)
            self._update_lookup_caches_add(guild_id_str, new_item_dict_for_lookup)

        self.mark_item_dirty(guild_id_str, item_id_str) # Marks for saving if persistence strategy requires it
        # print(f"ItemManager.update_item_instance: Item '{item_id_str}' updated.")
        # This method itself doesn't save to DB, relies on a periodic save_dirty_items or similar
        # Or save_item should be called explicitly after this if immediate persistence is needed.
        # For now, let's assume save_item is called separately or by a background task.
        # Re-saving it here:
        await self.save_item(item_object, guild_id_str)

        return True

    async def revert_item_creation(self, guild_id: str, item_id: str, **kwargs: Any) -> bool: return await self.remove_item_instance(guild_id, item_id, **kwargs)
    async def revert_item_deletion(self, guild_id: str, item_data: Dict[str, Any], **kwargs: Any) -> bool:
        item_id_to_recreate = item_data.get('id')
        item_data.setdefault('guild_id', guild_id)
        if not item_id_to_recreate or self.get_item_instance(guild_id, item_id_to_recreate): return True
        newly_created_item_object = Item.from_dict(item_data)
        return await self.save_item(newly_created_item_object, guild_id) # save_item also adds to cache
    async def revert_item_update(self, guild_id: str, item_id: str, old_field_values: Dict[str, Any], **kwargs: Any) -> bool: return await self.update_item_instance(guild_id, item_id, old_field_values, **kwargs)
    async def use_item_in_combat(self, guild_id: str, actor_id: str, item_instance_id: str, target_id: Optional[str] = None, game_log_manager: Optional['GameLogManager'] = None) -> Dict[str, Any]: return {"success": False, "consumed": False, "message": "Not implemented in detail."}

    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        for cache in [self._items, self._items_by_owner, self._items_by_location, self._dirty_items, self._deleted_items]: cache.pop(guild_id_str, None)
        self._items[guild_id_str] = {}
        self._items_by_owner[guild_id_str] = {}
        self._items_by_location[guild_id_str] = {}
        # print(f"ItemManager: Cleared runtime cache for guild '{guild_id_str}'.")

    def mark_item_dirty(self, guild_id: str, item_id: str) -> None:
         if str(guild_id) in self._items and str(item_id) in self._items[str(guild_id)]:
             self._dirty_items.setdefault(str(guild_id), set()).add(str(item_id))
             # print(f"ItemManager: Item '{item_id}' in guild '{guild_id}' marked dirty.")

    def _update_lookup_caches_add(self, guild_id: str, item_data: Dict[str, Any]) -> None:
        item_id, owner_id, loc_id = str(item_data.get('id')), item_data.get('owner_id'), item_data.get('location_id')
        guild_id_str = str(guild_id)
        if owner_id: self._items_by_owner.setdefault(guild_id_str, {}).setdefault(str(owner_id), set()).add(item_id)
        if loc_id: self._items_by_location.setdefault(guild_id_str, {}).setdefault(str(loc_id), set()).add(item_id)

    def _update_lookup_caches_remove(self, guild_id: str, item_data: Dict[str, Any]) -> None:
        item_id, owner_id, loc_id = str(item_data.get('id')), item_data.get('owner_id'), item_data.get('location_id')
        guild_id_str = str(guild_id)
        if owner_id and guild_id_str in self._items_by_owner and str(owner_id) in self._items_by_owner[guild_id_str]:
            self._items_by_owner[guild_id_str][str(owner_id)].discard(item_id)
            if not self._items_by_owner[guild_id_str][str(owner_id)]: self._items_by_owner[guild_id_str].pop(str(owner_id))
        if loc_id and guild_id_str in self._items_by_location and str(loc_id) in self._items_by_location[guild_id_str]:
            self._items_by_location[guild_id_str][str(loc_id)].discard(item_id)
            if not self._items_by_location[guild_id_str][str(loc_id)]: self._items_by_location[guild_id_str].pop(str(loc_id))

    async def save_item(self, item: "Item", guild_id: str) -> bool:
        # Saves a world item instance to DB and updates cache
        if self._db_service is None: return False
        item_id = getattr(item, 'id', None)
        guild_id_str = str(guild_id)
        if not item_id or str(getattr(item, 'guild_id', None)) != guild_id_str: return False

        item_data = item.to_dict()
        db_params = (
            item_data['id'], item_data['template_id'], guild_id_str,
            item_data['owner_id'], item_data['owner_type'], item_data['location_id'],
            float(item_data['quantity']), json.dumps(item_data['state_variables']),
            bool(item_data['is_temporary'])
        )
        upsert_sql = 'INSERT INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (id) DO UPDATE SET template_id=EXCLUDED.template_id, owner_id=EXCLUDED.owner_id, owner_type=EXCLUDED.owner_type, location_id=EXCLUDED.location_id, quantity=EXCLUDED.quantity, state_variables=EXCLUDED.state_variables, is_temporary=EXCLUDED.is_temporary'

        try:
            await self._db_service.adapter.execute(upsert_sql, db_params) # type: ignore
        except Exception as e:
            print(f"Error saving item {item_id} to DB: {e}")
            traceback.print_exc()
            return False

        self._items.setdefault(guild_id_str, {})[item_id] = item # Add/update in cache
        self._update_lookup_caches_add(guild_id_str, item.to_dict()) # Ensure lookups are updated
        self._dirty_items.get(guild_id_str, set()).discard(item_id) # No longer dirty after save
        if guild_id_str in self._deleted_items: self._deleted_items[guild_id_str].discard(item_id) # No longer deleted
        # print(f"ItemManager.save_item: Item '{item_id}' saved to DB and cache for guild '{guild_id_str}'.")
        return True

    async def get_items_in_location_async(self, guild_id: str, location_id: str) -> List["Item"]: return await self.get_items_in_location(guild_id, location_id)
    async def transfer_item_world_to_character(self, guild_id: str, character_id: str, item_instance_id: str, quantity: int = 1) -> bool:
        # This is a complex operation:
        # 1. Get world item instance.
        # 2. If valid and quantity allows:
        #    a. Add to character inventory (via InventoryManager). This is the tricky part due to different data structures.
        #    b. Decrease quantity or remove world item.
        # This needs careful implementation matching InventoryManager's expected item format.
        print(f"ItemManager.transfer_item_world_to_character: Placeholder for {item_instance_id} to char {character_id}.")
        return False # Placeholder

print("DEBUG: item_manager.py module loaded (after overwrite).")
