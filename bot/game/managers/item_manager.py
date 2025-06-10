# bot/game/managers/item_manager.py
from __future__ import annotations # Enables using type hints as strings implicitly, simplifying things
import json
import uuid
import traceback
import asyncio

# Import typing components
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union, TypedDict

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float

# --- Imports needed ONLY for Type Checking ---
if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.models.item import Item
    from bot.game.models.character import Character as CharacterModel # For type hinting
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

# --- Imports needed at Runtime ---
from bot.game.models.item import Item
from bot.utils.i18n_utils import get_i18n_text
from bot.ai.rules_schema import CoreGameRulesConfig, EquipmentSlotDefinition # For equip/unequip logic
from bot.game.utils.stats_calculator import calculate_effective_stats # For equip/unequip logic

print("DEBUG: item_manager.py module loaded.")

# --- Data Classes for Method Results ---
class EquipResult(TypedDict):
    success: bool
    message: str
    character_id: Optional[str]
    item_id: Optional[str] # template_id of item involved
    slot_id: Optional[str]

class ItemManager:
    required_args_for_load = ["guild_id"]
    required_args_for_save = ["guild_id"]
    required_args_for_rebuild = ["guild_id"]

    _item_templates: Dict[str, Dict[str, Any]]
    _items: Dict[str, Dict[str, "Item"]] # Stores Item objects

    _items_by_owner: Dict[str, Dict[str, Set[str]]]
    _items_by_location: Dict[str, Dict[str, Set[str]]]
    _dirty_items: Dict[str, Set[str]]
    _deleted_items: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None, # Changed
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

        self._item_templates = {}
        self._items = {}
        self._items_by_owner = {}
        self._items_by_location = {}
        self._dirty_items = {}
        self._deleted_items = {}

        self._load_item_templates()
        print("ItemManager initialized.")

    # --- Equip / Unequip Logic ---

    def _unequip_item_from_slot(self, character_inventory_data: List[Dict[str, Any]], slot_id_to_clear: str) -> bool:
        """
        Synchronous helper to mark an item in a specific slot as unequipped in the inventory list.
        Modifies character_inventory_data directly.
        Returns True if an item was unequipped, False otherwise.
        """
        item_was_unequipped = False
        for item_entry in character_inventory_data:
            if item_entry.get("equipped") and item_entry.get("slot_id") == slot_id_to_clear:
                item_entry["equipped"] = False
                item_entry.pop("slot_id", None) # Remove slot_id
                item_was_unequipped = True
                # Do not break; clear all items from this slot if multiple (though rules should prevent this for most slots)
        return item_was_unequipped

    async def equip_item(self,
                         character_id: str,
                         guild_id: str,
                         item_template_id_to_equip: str,
                         rules_config: CoreGameRulesConfig, # Added
                         slot_id_preference: Optional[str] = None
                        ) -> EquipResult:

        if not self._character_manager or not self._db_service: # Ensure critical managers are present
            return EquipResult(success=False, message="Character or DB service not available.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)

        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return EquipResult(success=False, message="Character not found.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)

        inventory_list_json = getattr(character, 'inventory', "[]")
        character_inventory_data: List[Dict[str, Any]] = json.loads(inventory_list_json) if isinstance(inventory_list_json, str) else inventory_list_json

        item_entry_to_equip: Optional[Dict[str, Any]] = None
        item_index_in_inventory: Optional[int] = None

        for i, entry in enumerate(character_inventory_data):
            entry_template_id = entry.get('template_id') or entry.get('item_id')
            if entry_template_id == item_template_id_to_equip and not entry.get('equipped'):
                item_entry_to_equip = entry
                item_index_in_inventory = i
                break

        if not item_entry_to_equip or item_index_in_inventory is None:
            return EquipResult(success=False, message=f"Unequipped item '{item_template_id_to_equip}' not found in inventory.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)

        item_template = self.get_item_template(item_template_id_to_equip)
        if not item_template:
            return EquipResult(success=False, message=f"Item template '{item_template_id_to_equip}' not found.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)

        item_type = item_template.get("type", "unknown")

        target_slot_id: Optional[str] = None
        if slot_id_preference:
            if slot_id_preference in rules_config.equipment_slots and \
               item_type in rules_config.equipment_slots[slot_id_preference].compatible_item_types:
                target_slot_id = slot_id_preference
            else:
                return EquipResult(success=False, message=f"Preferred slot '{slot_id_preference}' is not compatible with item type '{item_type}'.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)
        else:
            # Find first available compatible slot
            for slot_def_id, slot_def in rules_config.equipment_slots.items():
                if item_type in slot_def.compatible_item_types:
                    # Check if slot is already occupied
                    is_occupied = any(inv_item.get("equipped") and inv_item.get("slot_id") == slot_def_id for inv_item in character_inventory_data)
                    if not is_occupied:
                        target_slot_id = slot_def_id
                        break
            if not target_slot_id: # If all compatible slots are occupied, try to find one to suggest unequip or use first one
                 for slot_def_id, slot_def in rules_config.equipment_slots.items():
                     if item_type in slot_def.compatible_item_types:
                         target_slot_id = slot_def_id # Will overwrite if occupied
                         break

        if not target_slot_id:
            return EquipResult(success=False, message=f"No suitable slot found for item type '{item_type}'.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=None)

        # Unequip any item currently in the target_slot_id
        self._unequip_item_from_slot(character_inventory_data, target_slot_id)

        # Equip the new item
        character_inventory_data[item_index_in_inventory]["equipped"] = True
        character_inventory_data[item_index_in_inventory]["slot_id"] = target_slot_id

        character.inventory = json.dumps(character_inventory_data)

        # Update effective stats
        # Ensure nlu_data_service is available if calculate_effective_stats needs it for some reason (not typical)
        effective_stats = await calculate_effective_stats(self._db_service, character.id, "player", rules_config)
        character.effective_stats_json = json.dumps(effective_stats)

        self._character_manager.mark_dirty(character.id, guild_id)
        # await self._character_manager.save_character(character) # Or ensure save happens

        return EquipResult(success=True, message=f"Item '{item_template.get('name', item_template_id_to_equip)}' equipped to slot '{target_slot_id}'.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=target_slot_id)

    async def unequip_item(self,
                           character_id: str,
                           guild_id: str,
                           rules_config: CoreGameRulesConfig, # Added
                           item_template_id_to_unequip: Optional[str] = None,
                           slot_id_to_unequip: Optional[str] = None
                          ) -> EquipResult:

        if not self._character_manager or not self._db_service:
             return EquipResult(success=False, message="Character or DB service not available.", character_id=character_id, item_id=item_template_id_to_unequip, slot_id=slot_id_to_unequip)

        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return EquipResult(success=False, message="Character not found.", character_id=character_id, item_id=item_template_id_to_unequip, slot_id=slot_id_to_unequip)

        inventory_list_json = getattr(character, 'inventory', "[]")
        character_inventory_data: List[Dict[str, Any]] = json.loads(inventory_list_json) if isinstance(inventory_list_json, str) else inventory_list_json

        item_found_and_unequipped = False
        unequipped_item_template_id: Optional[str] = None
        actual_slot_unequipped: Optional[str] = None

        if slot_id_to_unequip:
            for item_entry in character_inventory_data:
                if item_entry.get("equipped") and item_entry.get("slot_id") == slot_id_to_unequip:
                    unequipped_item_template_id = item_entry.get('template_id') or item_entry.get('item_id')
                    item_entry["equipped"] = False
                    actual_slot_unequipped = item_entry.pop("slot_id", None)
                    item_found_and_unequipped = True
                    break
        elif item_template_id_to_unequip:
            for item_entry in character_inventory_data:
                entry_template_id = item_entry.get('template_id') or item_entry.get('item_id')
                if entry_template_id == item_template_id_to_unequip and item_entry.get('equipped'):
                    unequipped_item_template_id = entry_template_id
                    item_entry["equipped"] = False
                    actual_slot_unequipped = item_entry.pop("slot_id", None)
                    item_found_and_unequipped = True
                    break
        else:
            return EquipResult(success=False, message="No item or slot specified to unequip.", character_id=character_id)

        if not item_found_and_unequipped:
            msg = f"Equipped item matching criteria not found."
            if slot_id_to_unequip: msg = f"No item equipped in slot '{slot_id_to_unequip}'."
            elif item_template_id_to_unequip: msg = f"Item '{item_template_id_to_unequip}' is not equipped."
            return EquipResult(success=False, message=msg, character_id=character_id, item_id=item_template_id_to_unequip, slot_id=slot_id_to_unequip)

        character.inventory = json.dumps(character_inventory_data)

        effective_stats = await calculate_effective_stats(self._db_service, character.id, "player", rules_config)
        character.effective_stats_json = json.dumps(effective_stats)

        self._character_manager.mark_dirty(character.id, guild_id)
        # await self._character_manager.save_character(character)

        item_template = self.get_item_template(unequipped_item_template_id) if unequipped_item_template_id else None
        item_name = item_template.get('name', unequipped_item_template_id) if item_template else unequipped_item_template_id

        return EquipResult(success=True, message=f"Item '{item_name}' unequipped from slot '{actual_slot_unequipped}'.", character_id=character_id, item_id=unequipped_item_template_id, slot_id=actual_slot_unequipped)

    async def use_item(self,
                       character_id: str,
                       guild_id: str,
                       item_template_id: str,
                       rules_config: CoreGameRulesConfig,
                       target_entity_id: Optional[str] = None,
                       target_entity_type: Optional[str] = None
                      ) -> EquipResult: # Reusing EquipResult for now, can be renamed to UseItemResult

        if not self._character_manager or not self._db_service or not self._status_manager: # Added _status_manager check
            return EquipResult(success=False, message="Required services (Character, DB, Status) not available.", character_id=character_id, item_id=item_template_id, slot_id=None)

        char_model_type = "player" # Assuming player for now, could be expanded
        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return EquipResult(success=False, message="Character not found.", character_id=character_id, item_id=item_template_id, slot_id=None)

        inventory_list_json = getattr(character, 'inventory', "[]")
        character_inventory_data: List[Dict[str, Any]] = json.loads(inventory_list_json) if isinstance(inventory_list_json, str) else inventory_list_json

        item_entry_to_use: Optional[Dict[str, Any]] = None
        item_index_in_inventory: Optional[int] = None

        for i, entry in enumerate(character_inventory_data):
            entry_template_id = entry.get('template_id') or entry.get('item_id')
            if entry_template_id == item_template_id:
                item_entry_to_use = entry
                item_index_in_inventory = i
                break

        if not item_entry_to_use or item_index_in_inventory is None:
            return EquipResult(success=False, message=f"Item '{item_template_id}' not found in inventory.", character_id=character_id, item_id=item_template_id, slot_id=None)

        item_effect_def = rules_config.item_effects.get(item_template_id)
        if not item_effect_def:
            return EquipResult(success=False, message=f"No defined effects for item '{item_template_id}'.", character_id=character_id, item_id=item_template_id, slot_id=None)

        # Target policy check
        actual_target_id = character_id # Default to self
        actual_target_type = char_model_type # Default to self type

        if item_effect_def.target_policy == "requires_target":
            if not target_entity_id or not target_entity_type:
                return EquipResult(success=False, message=f"Item '{item_template_id}' requires a target, but none was provided.", character_id=character_id, item_id=item_template_id, slot_id=None)
            actual_target_id = target_entity_id
            actual_target_type = target_entity_type
        elif item_effect_def.target_policy == "no_target":
            actual_target_id = None # Explicitly no target
            actual_target_type = None


        # --- Apply Effects ---
        # This section requires careful interaction with CharacterManager, NPCManager, StatusManager
        # For now, direct modifications to character object are shown for some, assuming CM saves later.
        # A more robust solution would involve methods on those managers.

        # Direct Health Effects
        if item_effect_def.direct_health_effects:
            for health_effect in item_effect_def.direct_health_effects:
                target_hp_changed = False
                # This needs to fetch the target entity (player or NPC) and modify its HP
                # Simplified: if target is self (the character using the item)
                if actual_target_id == character.id and actual_target_type == char_model_type:
                    if health_effect.effect_type == "heal":
                        character.hp = min(getattr(character, 'max_health', character.hp), getattr(character, 'hp', 0) + health_effect.amount)
                        target_hp_changed = True
                    elif health_effect.effect_type == "damage":
                        character.hp = getattr(character, 'hp', 0) - health_effect.amount
                        target_hp_changed = True
                    # TODO: Add handling for other targets (NPCs) via NPCManager
                if target_hp_changed: print(f"Applied health effect: {health_effect.amount} to {actual_target_id}")


        # Apply Status Effects
        if item_effect_def.apply_status_effects:
            for status_rule in item_effect_def.apply_status_effects:
                eff_target_id = character.id if status_rule.target == "self" else actual_target_id
                eff_target_type = char_model_type if status_rule.target == "self" else actual_target_type

                if eff_target_id and eff_target_type:
                    # Assuming StatusManager.apply_status takes these args. Duration from rule or status_def.
                    status_def = rules_config.status_effects.get(status_rule.status_effect_id)
                    duration = status_rule.duration_turns if status_rule.duration_turns is not None else (status_def.default_duration_turns if status_def else None)

                    await self._status_manager.apply_status(
                        target_id=eff_target_id,
                        target_type=eff_target_type,
                        status_id=status_rule.status_effect_id,
                        guild_id=guild_id,
                        duration_turns=duration
                        # source_id (e.g. item_instance_id) could be added if StatusManager supports it
                    )
                    print(f"Applied status {status_rule.status_effect_id} to {eff_target_id}")

        # Learn Spells (applies only to self - the character using the item)
        if item_effect_def.learn_spells:
            if hasattr(character, 'known_spells') and isinstance(character.known_spells, list):
                for spell_rule in item_effect_def.learn_spells:
                    if spell_rule.spell_id not in character.known_spells:
                        character.known_spells.append(spell_rule.spell_id)
                        print(f"Character {character.id} learned spell {spell_rule.spell_id}")
            else: # Fallback or if known_spells is JSON string
                try:
                    known_spells_list = json.loads(getattr(character, 'known_spells', "[]")) if isinstance(getattr(character, 'known_spells', "[]"), str) else (getattr(character, 'known_spells', []) or [])
                    for spell_rule in item_effect_def.learn_spells:
                        if spell_rule.spell_id not in known_spells_list:
                            known_spells_list.append(spell_rule.spell_id)
                    character.known_spells = json.dumps(known_spells_list)
                    print(f"Character {character.id} learned spells (JSON update)")
                except json.JSONDecodeError:
                    print(f"Error parsing known_spells JSON for character {character.id}")


        # Grant Resources (applies only to self)
        if item_effect_def.grant_resources:
            for resource_rule in item_effect_def.grant_resources:
                current_val = getattr(character, resource_rule.resource_name, 0)
                if isinstance(current_val, (int, float)): # Ensure it's a number
                    setattr(character, resource_rule.resource_name, current_val + resource_rule.amount)
                    print(f"Granted {resource_rule.amount} of {resource_rule.resource_name} to character {character.id}")


        # Stat Modifiers (typically for ongoing effects from equipped, but could be instant for consumables via a status)
        # If consumable applies direct stat changes not via a status, it's more complex.
        # For now, assuming stat_modifiers on consumables are applied via a temporary status effect defined in apply_status_effects.
        # If they are direct, permanent changes for a consumable, that's unusual but could be handled.
        # This `stats_calculator` call is mainly if an equipped item is consumed, or if a consumable grants a status that then needs recalc.
        stats_changed_by_consumption_or_status = False
        if item_effect_def.apply_status_effects or (item_effect_def.consumable and item_entry_to_use.get("equipped")):
            stats_changed_by_consumption_or_status = True


        # Consume Item
        if item_effect_def.consumable:
            current_quantity = item_entry_to_use.get('quantity', 1)
            if current_quantity > 1:
                character_inventory_data[item_index_in_inventory]['quantity'] = current_quantity - 1
            else:
                character_inventory_data.pop(item_index_in_inventory)

            character.inventory = json.dumps(character_inventory_data)
            print(f"Item {item_template_id} consumed by {character.id}")
            # If the consumed item was equipped and provided stats, a recalc is needed.
            if item_entry_to_use.get("equipped"):
                 stats_changed_by_consumption_or_status = True # Ensure recalc if equipped item consumed

        if stats_changed_by_consumption_or_status:
            effective_stats = await calculate_effective_stats(self._db_service, character.id, char_model_type, rules_config)
            character.effective_stats_json = json.dumps(effective_stats)

        self._character_manager.mark_dirty(character.id, guild_id)
        # await self._character_manager.save_character(character) # Or ensure save happens

        item_template_for_name = self.get_item_template(item_template_id)
        item_name_display = item_template_for_name.get('name', item_template_id) if item_template_for_name else item_template_id

        return EquipResult(success=True, message=f"Used '{item_name_display}'.", character_id=character_id, item_id=item_template_id, slot_id=None)


    def _load_item_templates(self):
        print("ItemManager: Loading global item templates...")
        self._item_templates = {}

        try:
            if self._settings and 'item_templates' in self._settings and isinstance(self._settings['item_templates'], dict):
                processed_templates = {}
                default_lang_setting = self._settings.get('game_rules', {}).get('default_bot_language', 'en')

                for template_id, template_data_orig in self._settings['item_templates'].items():
                    template_data = template_data_orig.copy()
                    template_data['id'] = template_id

                    if not isinstance(template_data.get('name_i18n'), dict):
                        if 'name' in template_data and isinstance(template_data['name'], str):
                            template_data['name_i18n'] = {default_lang_setting: template_data['name']}
                        else:
                            template_data['name_i18n'] = {default_lang_setting: template_id}

                    if not isinstance(template_data.get('description_i18n'), dict):
                        if 'description' in template_data and isinstance(template_data['description'], str):
                            template_data['description_i18n'] = {default_lang_setting: template_data['description']}
                        else:
                            template_data['description_i18n'] = {default_lang_setting: "An item of unclear nature."}

                    template_data.setdefault('type', "misc")
                    template_data.setdefault('properties', {})
                    processed_templates[template_id] = template_data

                self._item_templates = processed_templates
                loaded_count = len(self._item_templates)
                print(f"ItemManager: Successfully loaded and processed {loaded_count} item templates from settings.")
            else:
                print("ItemManager: No item templates found in settings or 'item_templates' is not a dict.")
        except Exception as e:
            print(f"ItemManager: Error loading item templates from settings: {e}")
            traceback.print_exc()

    def get_item_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        return self._item_templates.get(str(template_id))

    def get_item_template_display_name(self, template_id: str, lang: str, default_lang: str = "en") -> str:
        template = self.get_item_template(template_id)
        if not template:
            return f"Item template '{template_id}' not found"
        return get_i18n_text(template, "name", lang, default_lang)

    def get_item_template_display_description(self, template_id: str, lang: str, default_lang: str = "en") -> str:
        template = self.get_item_template(template_id)
        if not template:
            return f"Item template '{template_id}' not found"
        return get_i18n_text(template, "description", lang, default_lang)

    def get_item_instance(self, guild_id: str, item_id: str) -> Optional["Item"]:
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        return self._items.get(guild_id_str, {}).get(item_id_str)

    async def get_all_item_instances(self, guild_id: str) -> List["Item"]:
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

    async def create_item_instance(self,
                                   guild_id: str,
                                   template_id: str,
                                   owner_id: Optional[str] = None,
                                   owner_type: Optional[str] = None,
                                   location_id: Optional[str] = None,
                                   quantity: float = 1.0,
                                   initial_state: Optional[Dict[str, Any]] = None,
                                   is_temporary: bool = False,
                                   **kwargs: Any
                                  ) -> Optional["Item"]:
        guild_id_str = str(guild_id)
        template_id_str = str(template_id)

        if self._db_service is None or self._db_service.adapter is None:
            print(f"ItemManager: No DB service or adapter for guild {guild_id_str}. Cannot create item instance.")
            return None

        template = self.get_item_template(template_id_str)
        if not template:
            print(f"ItemManager: Error creating instance: Template '{template_id_str}' not found globally.")
            return None

        if quantity <= 0:
            print(f"ItemManager: Warning creating instance: Quantity must be positive ({quantity}). Cannot create.")
            return None

        resolved_location_id: Optional[str] = str(location_id) if location_id else None
        resolved_owner_id: Optional[str] = str(owner_id) if owner_id else None
        resolved_owner_type: Optional[str] = str(owner_type) if owner_type else None

        if resolved_owner_type and resolved_owner_id and resolved_owner_type.lower() == 'location':
             resolved_location_id = resolved_owner_id
        elif resolved_owner_type is None and location_id is not None:
             resolved_location_id = str(location_id)

        new_item_id = str(uuid.uuid4())

        item_data_for_model: Dict[str, Any] = {
            'id': new_item_id,
            'guild_id': guild_id_str,
            'template_id': template_id_str,
            'quantity': float(quantity),
            'owner_id': resolved_owner_id,
            'owner_type': resolved_owner_type,
            'location_id': resolved_location_id,
            'state_variables': initial_state if initial_state is not None else {},
            'is_temporary': is_temporary
        }

        new_item = Item.from_dict(item_data_for_model)

        try:
            if not await self.save_item(new_item, guild_id_str):
                print(f"ItemManager: Failed to save new item {new_item_id} to DB for guild {guild_id_str}.")
                return None

            if self._game_log_manager:
                revert_data = {"item_id": new_item.id}
                log_details = {
                    "action_type": "ITEM_INSTANCE_CREATE", "item_id": new_item.id,
                    "template_id": new_item.template_id, "owner_id": new_item.owner_id,
                    "owner_type": new_item.owner_type, "location_id": new_item.location_id,
                    "quantity": new_item.quantity, "revert_data": revert_data
                }
                player_id_context = kwargs.get('player_id_context')
                asyncio.create_task(self._game_log_manager.log_event(
                    guild_id=guild_id_str, event_type="ITEM_CREATED",
                    details=log_details, player_id=player_id_context
                ))
            print(f"ItemManager: Item instance {new_item_id} (Template: {template_id_str}) created, saved, and cached for guild {guild_id_str}.")
            return new_item
        except Exception as e:
            print(f"ItemManager: ❌ Error during item instance creation or saving for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return None

    async def remove_item_instance(self, guild_id: str, item_id: str, **kwargs: Any) -> bool:
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        item_to_remove = self.get_item_instance(guild_id_str, item_id_str)

        if not item_to_remove:
            if guild_id_str in self._deleted_items and item_id_str in self._deleted_items[guild_id_str]:
                 print(f"ItemManager.remove_item_instance: Item {item_id_str} already marked as deleted or not found in active cache for guild {guild_id_str}.")
                 return True
            print(f"ItemManager.remove_item_instance: Item {item_id_str} not found for removal in guild {guild_id_str}.")
            return False

        if self._game_log_manager:
            revert_data = {"original_item_data": item_to_remove.to_dict()}
            log_details = {
                "action_type": "ITEM_INSTANCE_DELETE", "item_id": item_to_remove.id,
                "template_id": item_to_remove.template_id, "owner_id": item_to_remove.owner_id,
                "location_id": item_to_remove.location_id, "revert_data": revert_data
            }
            player_id_context = kwargs.get('player_id_context')
            await self._game_log_manager.log_event(
                guild_id=guild_id_str, event_type="ITEM_DELETED",
                details=log_details, player_id=player_id_context
            )

        try:
            if self._db_service and self._db_service.adapter:
                sql = 'DELETE FROM items WHERE id = $1 AND guild_id = $2'
                await self._db_service.adapter.execute(sql, (item_id_str, guild_id_str))

            guild_items_cache = self._items.get(guild_id_str, {})
            if item_id_str in guild_items_cache:
                 del guild_items_cache[item_id_str]
                 if not guild_items_cache: self._items.pop(guild_id_str, None)

            self._update_lookup_caches_remove(guild_id_str, item_to_remove.to_dict())
            self._dirty_items.get(guild_id_str, set()).discard(item_id_str)
            self._deleted_items.setdefault(guild_id_str, set()).add(item_id_str)
            return True
        except Exception as e:
            print(f"ItemManager: ❌ Error removing item instance {item_id_str} for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return False

    async def update_item_instance(self, guild_id: str, item_id: str, updates: Dict[str, Any], **kwargs: Any) -> bool:
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        item_object = self.get_item_instance(guild_id_str, item_id_str)

        if not item_object:
            print(f"ItemManager.update_item_instance: Item {item_id_str} not found in guild {guild_id_str}.")
            return False

        old_item_dict_for_lookup = item_object.to_dict()

        old_field_values = {}
        for key_to_update in updates.keys():
            if hasattr(item_object, key_to_update):
                old_field_values[key_to_update] = getattr(item_object, key_to_update)
                if isinstance(old_field_values[key_to_update], dict):
                     old_field_values[key_to_update] = json.loads(json.dumps(old_field_values[key_to_update]))

        for key, value in updates.items():
            if hasattr(item_object, key):
                if key == 'state_variables' and isinstance(value, dict):
                    current_state = getattr(item_object, key, {})
                    if not isinstance(current_state, dict) : current_state = {}
                    current_state.update(value)
                    setattr(item_object, key, current_state)
                else:
                    setattr(item_object, key, value)
            else:
                print(f"ItemManager: Warning - Attempted to update unknown attribute {key} for item {item_id_str}")

        if self._game_log_manager and old_field_values:
            revert_data = {"item_id": item_object.id, "old_field_values": old_field_values}
            log_details = {
                "action_type": "ITEM_INSTANCE_UPDATE", "item_id": item_object.id,
                "updated_fields_new_values": updates,
                "revert_data": revert_data
            }
            player_id_context = kwargs.get('player_id_context')
            await self._game_log_manager.log_event(
                guild_id=guild_id_str, event_type="ITEM_UPDATED",
                details=log_details, player_id=player_id_context
            )

        new_item_dict_for_lookup = item_object.to_dict()
        owner_changed = old_item_dict_for_lookup.get('owner_id') != new_item_dict_for_lookup.get('owner_id') or \
                        old_item_dict_for_lookup.get('owner_type') != new_item_dict_for_lookup.get('owner_type')
        location_changed = old_item_dict_for_lookup.get('location_id') != new_item_dict_for_lookup.get('location_id')

        if owner_changed or location_changed:
            self._update_lookup_caches_remove(guild_id_str, old_item_dict_for_lookup)
            self._update_lookup_caches_add(guild_id_str, new_item_dict_for_lookup)

        self.mark_item_dirty(guild_id_str, item_id_str)
        return True

    async def revert_item_creation(self, guild_id: str, item_id: str, **kwargs: Any) -> bool:
        print(f"ItemManager.revert_item_creation: Attempting to remove item {item_id} for guild {guild_id}.")
        success = await self.remove_item_instance(guild_id, item_id, **kwargs)
        if success:
            print(f"ItemManager.revert_item_creation: Successfully removed item {item_id} for guild {guild_id}.")
        else:
            print(f"ItemManager.revert_item_creation: Failed to remove item {item_id} for guild {guild_id}.")
        return success

    async def revert_item_deletion(self, guild_id: str, item_data: Dict[str, Any], **kwargs: Any) -> bool:
        item_id_to_recreate = item_data.get('id')
        if not item_id_to_recreate:
            print(f"ItemManager.revert_item_deletion: Invalid item_data, missing 'id'. Cannot revert deletion for guild {guild_id}.")
            return False

        print(f"ItemManager.revert_item_deletion: Attempting to recreate item {item_id_to_recreate} for guild {guild_id} from data: {item_data}")

        existing_item = self.get_item_instance(guild_id, item_id_to_recreate)
        if existing_item:
            print(f"ItemManager.revert_item_deletion: Item {item_id_to_recreate} already exists in guild {guild_id}. Assuming already reverted.")
            return True

        try:
            item_data.setdefault('guild_id', guild_id)
            item_data.setdefault('state_variables', item_data.get('state_variables', {}))
            item_data.setdefault('is_temporary', item_data.get('is_temporary', False))
            item_data['quantity'] = float(item_data.get('quantity', 1.0))
            newly_created_item_object = Item.from_dict(item_data)
            save_success = await self.save_item(newly_created_item_object, guild_id)

            if save_success:
                print(f"ItemManager.revert_item_deletion: Successfully recreated and saved item {item_id_to_recreate} for guild {guild_id}.")
                return True
            else:
                print(f"ItemManager.revert_item_deletion: Failed to save recreated item {item_id_to_recreate} for guild {guild_id}.")
                return False
        except Exception as e:
            print(f"ItemManager.revert_item_deletion: Error during item recreation for {item_id_to_recreate} in guild {guild_id}: {e}")
            traceback.print_exc()
            return False

    async def revert_item_update(self, guild_id: str, item_id: str, old_field_values: Dict[str, Any], **kwargs: Any) -> bool:
        item = self.get_item_instance(guild_id, item_id)
        if not item:
            print(f"ItemManager.revert_item_update: Item {item_id} not found in guild {guild_id}. Cannot revert update.")
            return False

        print(f"ItemManager.revert_item_update: Reverting fields for item {item_id} in guild {guild_id}. Old values: {old_field_values}")
        old_item_dict_for_lookup = item.to_dict()

        for field_name, old_value in old_field_values.items():
            if hasattr(item, field_name):
                if field_name == 'quantity' and old_value is not None:
                    try: setattr(item, field_name, float(old_value))
                    except ValueError:
                        print(f"ItemManager.revert_item_update: Invalid old_value '{old_value}' for quantity on item {item_id}. Skipping field.")
                        continue
                else: setattr(item, field_name, old_value)
            else:
                print(f"ItemManager.revert_item_update: Warning - Item {item_id} has no attribute '{field_name}'. Skipping field.")

        new_item_dict_for_lookup = item.to_dict()
        owner_changed = (old_item_dict_for_lookup.get('owner_id') != new_item_dict_for_lookup.get('owner_id') or
                         old_item_dict_for_lookup.get('owner_type') != new_item_dict_for_lookup.get('owner_type'))
        location_changed = old_item_dict_for_lookup.get('location_id') != new_item_dict_for_lookup.get('location_id')

        if owner_changed or location_changed:
            print(f"ItemManager.revert_item_update: Owner or location changed for item {item_id}. Updating lookup caches.")
            self._update_lookup_caches_remove(guild_id, old_item_dict_for_lookup)
            self._update_lookup_caches_add(guild_id, new_item_dict_for_lookup)

        self.mark_item_dirty(guild_id, item_id)
        print(f"ItemManager.revert_item_update: Successfully reverted fields for item {item_id} in guild {guild_id}.")
        return True

    async def use_item_in_combat(
        self,
        guild_id: str,
        actor_id: str,
        item_instance_id: str,
        target_id: Optional[str] = None,
        game_log_manager: Optional['GameLogManager'] = None
    ) -> Dict[str, Any]:
        guild_id_str = str(guild_id)
        item_instance = self.get_item_instance(guild_id_str, item_instance_id)

        if not item_instance:
            return {"success": False, "consumed": False, "message": "Item instance not found."}

        item_template = self.get_item_template(item_instance.template_id)
        if not item_template: # get_item_template returns Dict[str, Any] or None
            return {"success": False, "consumed": False, "message": "Item template not found."}

        item_name = item_template.get('name_i18n', {}).get('en', item_instance.template_id)
        properties = item_template.get('properties', {})

        if not properties.get("usable_in_combat", False):
            return {"success": False, "consumed": False, "message": f"{item_name} is not usable in combat."}

        required_target_type = properties.get("target_type") # e.g. "self", "enemy", "ally", "any"
        if required_target_type and required_target_type not in ["self", "area_implicit"] and not target_id:
            return {"success": False, "consumed": False, "message": f"{item_name} requires a target."}

        resolved_target_id = target_id
        if not target_id and required_target_type == "self":
            resolved_target_id = actor_id

        # Consume the item
        if item_instance.quantity > 1:
            update_success = await self.update_item_instance(
                guild_id_str,
                item_instance_id,
                {"quantity": item_instance.quantity - 1},
                player_id_context=actor_id # Pass actor_id as context for logging if needed
            )
            if not update_success:
                 return {"success": False, "consumed": False, "message": f"Failed to update quantity for {item_name}."}
        else:
            remove_success = await self.remove_item_instance(
                guild_id_str,
                item_instance_id,
                player_id_context=actor_id # Pass actor_id as context for logging if needed
            )
            if not remove_success:
                return {"success": False, "consumed": False, "message": f"Failed to remove {item_name} after use."}

        consume_log_message = f"Item '{item_name}' (ID: {item_instance_id}) consumed by {actor_id}."
        # Use the passed game_log_manager if available
        actual_log_manager = game_log_manager if game_log_manager else self._game_log_manager
        if actual_log_manager:
            await actual_log_manager.log_event(guild_id_str, "ITEM_CONSUMED",
                                               details={"message": consume_log_message, "item_id": item_instance_id, "actor_id": actor_id},
                                               player_id=actor_id) # Log with player_id if applicable
        else:
            print(f"ItemManager: {consume_log_message}")

        item_effects = item_template.get("effects", [])
        return {
            "success": True, "consumed": True,
            "message": f"{item_name} used by {actor_id}.",
            "item_name": item_name, "effects": item_effects,
            "actor_id": actor_id,
            "original_target_id": target_id,
            "resolved_target_id": resolved_target_id
        }

    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None:
             self._clear_guild_state_cache(guild_id_str)
             return

        self._clear_guild_state_cache(guild_id_str)
        guild_items_cache = self._items[guild_id_str]

        try:
            sql_items = 'SELECT id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary FROM items WHERE guild_id = $1'
            rows_items = await self._db_service.adapter.fetchall(sql_items, (guild_id_str,))
            loaded_count = 0
            for row in rows_items:
                try:
                    item_data_dict: Dict[str, Any] = {
                       'id': row['id'],
                       'template_id': str(row['template_id']) if row['template_id'] is not None else None,
                       'guild_id': str(row['guild_id']),
                       'owner_id': str(row['owner_id']) if row['owner_id'] is not None else None,
                       'owner_type': str(row['owner_type']) if row['owner_type'] is not None else None,
                       'location_id': str(row['location_id']) if row['location_id'] is not None else None,
                       'quantity': float(row['quantity']) if row['quantity'] is not None else 1.0,
                       'state_variables': json.loads(row['state_variables'] or '{}') if isinstance(row['state_variables'], (str, bytes)) else {},
                       'is_temporary': bool(row['is_temporary'])
                    }
                    if item_data_dict['template_id'] is None or item_data_dict['guild_id'] != guild_id_str:
                        continue

                    item_object = Item.from_dict(item_data_dict)
                    guild_items_cache[item_object.id] = item_object
                    loaded_count += 1
                    self._update_lookup_caches_add(guild_id_str, item_object.to_dict())
                except Exception as e:
                   print(f"ItemManager: ❌ Error processing item row ID {row['id'] if row and 'id' in row else 'Unknown'}: {e}")
                   traceback.print_exc()
            print(f"ItemManager: Loaded {loaded_count} item instances for guild {guild_id_str}.")
        except Exception as e:
            print(f"ItemManager: ❌ CRITICAL ERROR loading items for guild {guild_id_str}: {e}")
            self._clear_guild_state_cache(guild_id_str)
            raise

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        if self._db_service is None or self._db_service.adapter is None: return

        dirty_ids = self._dirty_items.get(guild_id_str, set()).copy()
        deleted_ids = self._deleted_items.get(guild_id_str, set()).copy()

        if not dirty_ids and not deleted_ids:
            self._dirty_items.pop(guild_id_str, None)
            self._deleted_items.pop(guild_id_str, None)
            return

        if deleted_ids:
            if deleted_ids:
                placeholders = ','.join([f'${i+2}' for i in range(len(deleted_ids))])
                sql_delete = f"DELETE FROM items WHERE guild_id = $1 AND id IN ({placeholders})"
                try:
                    await self._db_service.adapter.execute(sql_delete, (guild_id_str, *list(deleted_ids)))
                    self._deleted_items.pop(guild_id_str, None)
                except Exception as e: print(f"ItemManager: Error deleting items: {e}")
            else:
                self._deleted_items.pop(guild_id_str, None)

        items_to_upsert = [obj.to_dict() for id_str in dirty_ids if (obj := self._items.get(guild_id_str, {}).get(id_str))]

        if items_to_upsert:
            upsert_sql = '''
            INSERT INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (id) DO UPDATE SET
                template_id = EXCLUDED.template_id, guild_id = EXCLUDED.guild_id,
                owner_id = EXCLUDED.owner_id, owner_type = EXCLUDED.owner_type,
                location_id = EXCLUDED.location_id, quantity = EXCLUDED.quantity,
                state_variables = EXCLUDED.state_variables, is_temporary = EXCLUDED.is_temporary
            '''
            data_tuples = []
            processed_ids = set()
            for item_data in items_to_upsert:
                try:
                    data_tuples.append((
                        item_data['id'], item_data['template_id'], item_data['guild_id'],
                        item_data['owner_id'], item_data['owner_type'], item_data['location_id'],
                        item_data['quantity'], json.dumps(item_data['state_variables']),
                        bool(item_data['is_temporary'])
                    ))
                    processed_ids.add(item_data['id'])
                except Exception as e: print(f"ItemManager: Error preparing item {item_data.get('id')} for save: {e}")

            if data_tuples:
                try:
                    await self._db_service.adapter.execute_many(upsert_sql, data_tuples)
                    if guild_id_str in self._dirty_items:
                        self._dirty_items[guild_id_str].difference_update(processed_ids)
                        if not self._dirty_items[guild_id_str]: del self._dirty_items[guild_id_str]
                except Exception as e: print(f"ItemManager: Error batch upserting items: {e}")
        print(f"ItemManager: Save state complete for guild {guild_id_str}.")

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
         guild_id_str = str(guild_id)
         self._items_by_owner.pop(guild_id_str, None)
         self._items_by_owner[guild_id_str] = {}
         self._items_by_location.pop(guild_id_str, None)
         self._items_by_location[guild_id_str] = {}

         guild_items_cache = self._items.get(guild_id_str, {})
         for item_id, item_obj in guild_items_cache.items():
              self._update_lookup_caches_add(guild_id_str, item_obj.to_dict())
         print(f"ItemManager: Runtime caches rebuilt for guild {guild_id_str}.")

    async def clean_up_for_character(self, character_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
         guild_id = context.get('guild_id')
         if not guild_id: return
         loc_mgr = context.get('location_manager', self._location_manager)
         char_loc_id = context.get('location_instance_id')
         if loc_mgr and hasattr(loc_mgr, 'get_location_instance') and char_loc_id:
              drop_location_instance = loc_mgr.get_location_instance(str(guild_id), str(char_loc_id))

    async def clean_up_for_npc(self, npc_id: str, context: Dict[str, Any], **kwargs: Any) -> None:
         guild_id = context.get('guild_id')
         if not guild_id: return
         loc_mgr = context.get('location_manager', self._location_manager)
         npc_loc_id = context.get('location_instance_id')
         if loc_mgr and hasattr(loc_mgr, 'get_location_instance') and npc_loc_id:
             drop_location_instance = loc_mgr.get_location_instance(str(guild_id), str(npc_loc_id))

    async def remove_items_by_location(self, location_id: str, guild_id: str, **kwargs: Any) -> None:
         guild_id_str = str(guild_id)
         location_id_str = str(location_id)
         items_to_remove = await self.get_items_in_location(guild_id_str, location_id_str)
         for item_obj in list(items_to_remove):
              await self.remove_item_instance(guild_id_str, item_obj.id, **kwargs)

    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        self._items.pop(guild_id_str, None)
        self._items[guild_id_str] = {}
        self._items_by_owner.pop(guild_id_str, None)
        self._items_by_owner[guild_id_str] = {}
        self._items_by_location.pop(guild_id_str, None)
        self._items_by_location[guild_id_str] = {}
        self._dirty_items.pop(guild_id_str, None)
        self._deleted_items.pop(guild_id_str, None)

    def mark_item_dirty(self, guild_id: str, item_id: str) -> None:
         guild_id_str = str(guild_id)
         item_id_str = str(item_id)
         if guild_id_str in self._items and item_id_str in self._items[guild_id_str]:
              self._dirty_items.setdefault(guild_id_str, set()).add(item_id_str)

    def _update_lookup_caches_add(self, guild_id: str, item_data: Dict[str, Any]) -> None:
        guild_id_str = str(guild_id)
        item_id_str = str(item_data.get('id'))
        owner_id = item_data.get('owner_id')
        location_id = item_data.get('location_id')
        if owner_id is not None:
             self._items_by_owner.setdefault(guild_id_str, {}).setdefault(str(owner_id), set()).add(item_id_str)
        if location_id is not None:
             self._items_by_location.setdefault(guild_id_str, {}).setdefault(str(location_id), set()).add(item_id_str)

    def _update_lookup_caches_remove(self, guild_id: str, item_data: Dict[str, Any]) -> None:
        guild_id_str = str(guild_id)
        item_id_str = str(item_data.get('id'))
        owner_id = item_data.get('owner_id')
        location_id = item_data.get('location_id')
        if owner_id is not None:
             owner_id_str = str(owner_id)
             guild_owner_cache = self._items_by_owner.get(guild_id_str)
             if guild_owner_cache and owner_id_str in guild_owner_cache:
                  guild_owner_cache[owner_id_str].discard(item_id_str)
                  if not guild_owner_cache[owner_id_str]:
                       guild_owner_cache.pop(owner_id_str)
                       if not guild_owner_cache: self._items_by_owner.pop(guild_id_str, None)
        if location_id is not None:
             location_id_str = str(location_id)
             guild_location_cache = self._items_by_location.get(guild_id_str)
             if guild_location_cache and location_id_str in guild_location_cache:
                  guild_location_cache[location_id_str].discard(item_id_str)
                  if not guild_location_cache[location_id_str]:
                       guild_location_cache.pop(location_id_str)
                       if not guild_location_cache: self._items_by_location.pop(guild_id_str, None)

    async def save_item(self, item: "Item", guild_id: str) -> bool:
        if self._db_service is None or self._db_service.adapter is None: return False
        guild_id_str = str(guild_id)
        item_id = getattr(item, 'id', None)
        if not item_id: return False
        if str(getattr(item, 'guild_id', None)) != guild_id_str: return False

        try:
            item_data_from_model = item.to_dict()
            db_params = (
                item_data_from_model.get('id'), item_data_from_model.get('template_id'),
                guild_id_str,
                item_data_from_model.get('owner_id'), item_data_from_model.get('owner_type'),
                item_data_from_model.get('location_id'),
                float(item_data_from_model.get('quantity', 1.0)),
                json.dumps(item_data_from_model.get('state_variables', {})),
                bool(item_data_from_model.get('is_temporary', False))
            )
            upsert_sql = '''
            INSERT INTO items (id, template_id, guild_id, owner_id, owner_type, location_id, quantity, state_variables, is_temporary)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (id) DO UPDATE SET
                template_id = EXCLUDED.template_id, guild_id = EXCLUDED.guild_id,
                owner_id = EXCLUDED.owner_id, owner_type = EXCLUDED.owner_type,
                location_id = EXCLUDED.location_id, quantity = EXCLUDED.quantity,
                state_variables = EXCLUDED.state_variables, is_temporary = EXCLUDED.is_temporary
            '''
            await self._db_service.adapter.execute(upsert_sql, db_params)

            guild_dirty_set = self._dirty_items.get(guild_id_str)
            if guild_dirty_set:
                guild_dirty_set.discard(item_id)
                if not guild_dirty_set: del self._dirty_items[guild_id_str]

            self._items.setdefault(guild_id_str, {})[item_id] = item

            item_as_dict_for_lookup = item.to_dict()
            self._update_lookup_caches_remove(guild_id_str, item_as_dict_for_lookup)
            self._update_lookup_caches_add(guild_id_str, item_as_dict_for_lookup)
            return True
        except Exception as e:
            print(f"ItemManager: Error saving item {item_id} for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return False

    async def get_items_in_location_async(self, guild_id: str, location_id: str) -> List["Item"]:
        if not self._db_service:
            print(f"ItemManager: DBService not available. Cannot get items in location {location_id} for guild {guild_id}.")
            return []
        item_data_list = await self._db_service.get_item_instances_in_location(location_id=location_id, guild_id=guild_id)
        items: List[Item] = []
        for data in item_data_list:
            try:
                item_properties = data.get('properties', {})
                state_variables = data.get('state_variables', {})
                item_init_data = {
                    "id": data.get("item_instance_id"),
                    "template_id": data.get("template_id"), "guild_id": guild_id,
                    "name": data.get("name"), "description": data.get("description"),
                    "item_type": data.get("item_type"),
                    "quantity": data.get("quantity"),
                    "properties": item_properties, "state_variables": state_variables,
                    "owner_id": None, "owner_type": "location",
                    "location_id": location_id
                }
                if not item_init_data["id"] or not item_init_data["template_id"]:
                    print(f"ItemManager: Skipping item data due to missing id or template_id: {item_init_data}")
                    continue
                items.append(Item.from_dict(item_init_data))
            except Exception as e:
                print(f"ItemManager: Error converting data to Item object for item in location {location_id}: {data}, Error: {e}")
                traceback.print_exc()
        return items

    async def transfer_item_world_to_character(self, guild_id: str, character_id: str, item_instance_id: str, quantity: int = 1) -> bool:
        if not self._db_service or not self._character_manager:
            print("ItemManager: DBService or CharacterManager not available. Cannot transfer item.")
            return False

        item_instance_data = await self._db_service.get_entity(table_name="items", entity_id=item_instance_id, guild_id=guild_id)
        if not item_instance_data:
            print(f"ItemManager: Item instance {item_instance_id} not found in guild {guild_id}.")
            return False

        current_quantity_in_world = item_instance_data.get('quantity', 0.0)
        if not isinstance(current_quantity_in_world, (int, float)): current_quantity_in_world = 0.0
        template_id = item_instance_data.get('template_id')
        if not template_id:
             print(f"ItemManager: Item instance {item_instance_id} is missing a template_id.")
             return False
        if current_quantity_in_world < quantity:
            print(f"ItemManager: Not enough quantity of item {item_instance_id} in world. Has {current_quantity_in_world}, needs {quantity}.")
            return False

        add_success = await self._character_manager.add_item_to_inventory(
            guild_id=guild_id, character_id=character_id,
            item_id=template_id, quantity=quantity
        )
        if not add_success:
            print(f"ItemManager: Failed to add item (template: {template_id}) to character {character_id} inventory.")
            return False

        if current_quantity_in_world == quantity:
            delete_success = await self._db_service.delete_entity(table_name="items", entity_id=item_instance_id, guild_id=guild_id)
            if not delete_success:
                print(f"ItemManager: Failed to delete item instance {item_instance_id} from world. Manual cleanup may be needed.")
            else:
                print(f"ItemManager: Item instance {item_instance_id} deleted from world.")
                guild_items_cache = self._items.get(guild_id, {})
                if item_instance_id in guild_items_cache: del guild_items_cache[item_instance_id]
                self._update_lookup_caches_remove(guild_id, item_instance_data)
                self._dirty_items.get(guild_id, set()).discard(item_instance_id)
                self._deleted_items.setdefault(guild_id, set()).add(item_instance_id)
        else:
            new_world_quantity = current_quantity_in_world - quantity
            update_success = await self._db_service.update_entity(
                table_name="items", entity_id=item_instance_id,
                data={'quantity': new_world_quantity}, guild_id=guild_id
            )
            if not update_success:
                print(f"ItemManager: Failed to update quantity for item instance {item_instance_id} in world.")
            else:
                print(f"ItemManager: Item instance {item_instance_id} quantity updated in world to {new_world_quantity}.")
                cached_item = self.get_item_instance(guild_id, item_instance_id)
                if cached_item:
                    cached_item.quantity = new_world_quantity
                    self.mark_item_dirty(guild_id, item_instance_id)
        return True

print("DEBUG: item_manager.py module loaded.")
