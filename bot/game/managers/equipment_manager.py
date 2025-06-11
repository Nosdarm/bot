# bot/game/managers/equipment_manager.py
from __future__ import annotations
import json
from typing import Optional, Dict, Any, List, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.models.character import Character as CharacterModel # Use CharacterModel alias
    from bot.ai.rules_schema import CoreGameRulesConfig, ItemDefinition as ItemDefinitionModel, EquipmentSlotDefinition
    from bot.services.db_service import DBService

# calculate_effective_stats is directly used by CharacterManager now, so not imported here for direct use.
# from bot.game.utils.stats_calculator import calculate_effective_stats

class EquipmentManager:
    def __init__(self,
                 character_manager: "CharacterManager",
                 inventory_manager: "InventoryManager",
                 item_manager: "ItemManager",
                 status_manager: "StatusManager", # Required for item effects
                 rule_engine: "RuleEngine", # May not be directly used if rules_config is passed
                 db_service: "DBService"): # For potential direct DB needs, though CharacterManager handles most
        self._character_manager = character_manager
        self._inventory_manager = inventory_manager
        self._item_manager = item_manager
        self._status_manager = status_manager
        self._rule_engine = rule_engine # Keep for now, might be useful for complex rule checks
        self._db_service = db_service
        print("EquipmentManager initialized.")

    def _get_character_equipment_dict(self, character: "CharacterModel") -> Dict[str, Any]:
        """Safely gets and returns the character's equipment data as a mutable dictionary."""
        current_equipment_attr = getattr(character, 'equipment', None)

        if isinstance(current_equipment_attr, dict):
            # If it's already a dict (e.g., parsed in the same session), return a copy to avoid modifying the original if it's not intended
            # However, for this manager, we usually want to modify it and then save.
            # So, directly returning it is fine as CharacterManager will handle serialization.
            return current_equipment_attr

        if isinstance(current_equipment_attr, str):
            try:
                equipment_dict = json.loads(current_equipment_attr)
                if not isinstance(equipment_dict, dict):
                    equipment_dict = {} # Default to empty if JSON is not a dict
                # Store the parsed dict back onto the character object so it's consistently a dict hereafter in this session
                character.equipment = equipment_dict
                return equipment_dict
            except json.JSONDecodeError:
                character.equipment = {} # Default to empty on error
                return character.equipment

        # If None or any other type, initialize as empty dict
        character.equipment = {}
        return character.equipment


    async def equip_item(self, guild_id: str, character_id: str, item_instance_id: str,
                         slot_id_preference: Optional[str], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        """Equips an item from character's inventory to a specified or suitable slot."""
        log_prefix = f"EquipmentManager.equip_item(char='{character_id}', item_instance='{item_instance_id}'):"

        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return {"success": False, "message": "Персонаж не найден."}

        # Fetch the item instance from inventory using InventoryManager
        # This should return a dict copy of the item, including its unique instance_id and template_id
        item_instance_data = await self._inventory_manager.get_item_instance_by_id(guild_id, character_id, item_instance_id)
        if not item_instance_data:
            return {"success": False, "message": f"Предмет с ID экземпляра '{item_instance_id}' не найден в инвентаре."}

        item_template_id = item_instance_data.get('template_id') # Assuming InventoryManager uses 'template_id'
        if not item_template_id: # Should also check item_instance_data.get('item_id') if that's a possibility
            item_template_id = item_instance_data.get('item_id') # Fallback for old key
            if not item_template_id:
                return {"success": False, "message": "Ошибка данных предмета: отсутствует ID шаблона."}
            item_instance_data['template_id'] = item_template_id # Standardize

        item_definition: Optional[ItemDefinitionModel] = rules_config.item_definitions.get(item_template_id)
        if not item_definition:
            return {"success": False, "message": f"Определение для предмета '{item_template_id}' не найдено в правилах."}

        if not item_definition.equippable:
            return {"success": False, "message": f"Предмет '{item_definition.name}' не является экипируемым."}

        item_type = item_definition.type
        item_name = item_definition.name

        target_slot_id: Optional[str] = None
        equipment_slots_config: Dict[str, EquipmentSlotDefinition] = rules_config.equipment_slots
        character_equipment = self._get_character_equipment_dict(character) # Ensure it's a dict

        if slot_id_preference:
            slot_def = equipment_slots_config.get(slot_id_preference)
            if slot_def and item_type in slot_def.compatible_item_types:
                target_slot_id = slot_id_preference
            else:
                return {"success": False, "message": f"Слот '{slot_id_preference}' (предпочтительный) несовместим с типом предмета '{item_type}'."}
        else: # Auto-find slot
            # Priority 1: Empty compatible slot
            for s_id, s_def in equipment_slots_config.items():
                if item_type in s_def.compatible_item_types:
                    if s_id not in character_equipment or character_equipment.get(s_id) is None:
                        target_slot_id = s_id
                        break
            # Priority 2: Any compatible slot (will unequip existing item)
            if not target_slot_id:
                for s_id, s_def in equipment_slots_config.items():
                     if item_type in s_def.compatible_item_types:
                         target_slot_id = s_id
                         break

        if not target_slot_id:
            return {"success": False, "message": f"Нет подходящего слота для предмета '{item_name}' (тип: {item_type})."}

        # Unequip item if slot is occupied
        if target_slot_id in character_equipment and character_equipment.get(target_slot_id) is not None:
            print(f"{log_prefix} Slot '{target_slot_id}' is occupied by {character_equipment[target_slot_id].get('template_id')}. Unequipping it first.")
            unequip_result = await self.unequip_item(guild_id, character_id, target_slot_id, rules_config, is_internal_call=True)
            if not unequip_result["success"]:
                return {"success": False, "message": f"Не удалось освободить слот '{target_slot_id}': {unequip_result['message']}"}
            character_equipment = self._get_character_equipment_dict(character) # Refresh after unequip

        # Remove item from inventory (InventoryManager handles instance removal)
        removed_from_inv = await self._inventory_manager.remove_item(
            guild_id, character_id,
            item_instance_id=item_instance_id, # Crucial: remove by instance ID
            quantity_to_remove=1 # Assuming equippables are single quantity
        )
        if not removed_from_inv: # This also implies quantity check passed in InventoryManager
            return {"success": False, "message": f"Не удалось убрать предмет '{item_name}' из инвентаря (ID экземпляра: {item_instance_id})."}

        # Add to equipment slot
        character_equipment[target_slot_id] = item_instance_data
        character.equipment = json.dumps(character_equipment) # Update character model (will be saved by CharacterManager)

        # Apply item effects (passive stats are handled by stat recalculation, this is for statuses etc.)
        # item_instance_data must have 'instance_id' for effect tracking
        await self._item_manager.apply_item_effects(guild_id, character_id, item_instance_data, rules_config)

        await self._character_manager.calculate_and_update_effective_stats(guild_id, character_id, rules_config)
        self._character_manager.mark_character_dirty(guild_id, character_id)

        print(f"{log_prefix} Item '{item_name}' equipped to slot '{target_slot_id}'.")
        return {"success": True, "message": f"'{item_name}' экипирован(а) в слот '{target_slot_id}'.", "state_changed": True}

    async def unequip_item(self, guild_id: str, character_id: str, slot_id_to_unequip: str,
                           rules_config: "CoreGameRulesConfig", is_internal_call: bool = False) -> Dict[str, Any]:
        """Unequips an item from a specified slot and returns it to inventory."""
        log_prefix = f"EquipmentManager.unequip_item(char='{character_id}', slot='{slot_id_to_unequip}'):"

        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            return {"success": False, "message": "Персонаж не найден."}

        character_equipment = self._get_character_equipment_dict(character)
        if slot_id_to_unequip not in character_equipment or character_equipment.get(slot_id_to_unequip) is None:
            return {"success": False, "message": f"Слот '{slot_id_to_unequip}' уже пуст или не существует."}

        item_instance_data_to_unequip = character_equipment.pop(slot_id_to_unequip) # Remove from equipment dict
        character.equipment = json.dumps(character_equipment) # Update character model

        item_template_id = item_instance_data_to_unequip.get('template_id') or item_instance_data_to_unequip.get('item_id')
        item_name = item_instance_data_to_unequip.get('name', item_template_id) # 'name' might not be in instance data, fetch from def if needed

        if not item_template_id:
             # This should not happen if data is consistent
             print(f"{log_prefix} Critical error: item in slot '{slot_id_to_unequip}' has no template_id. Data: {item_instance_data_to_unequip}")
             # Attempt to add to inventory anyway but flag error
             # For now, let's assume it won't happen. If it does, inventory add might fail.
             pass

        # Remove item effects
        # item_instance_data_to_unequip must have 'instance_id'
        await self._item_manager.remove_item_effects(guild_id, character_id, item_instance_data_to_unequip, rules_config)

        # Add item back to inventory ONLY if not an internal call (e.g. swapping items)
        if not is_internal_call:
            # InventoryManager.add_item needs to correctly handle the full item_instance_data
            # to preserve its unique ID and state.
            added_to_inv_result = await self._inventory_manager.add_item(
                guild_id, character_id,
                item_data=item_instance_data_to_unequip # Pass the whole dict
                # quantity is part of item_instance_data_to_unequip.get('quantity', 1)
            )
            if not added_to_inv_result.get("success"):
                # Critical: Failed to add item back to inventory. Try to re-equip to prevent item loss.
                print(f"{log_prefix} CRITICAL: Failed to add '{item_name}' back to inventory: {added_to_inv_result.get('message')}. Attempting to re-equip.")
                character_equipment[slot_id_to_unequip] = item_instance_data_to_unequip # Put it back
                character.equipment = json.dumps(character_equipment)
                # Re-apply effects? This could be complex. For now, focus on not losing the item.
                # await self._item_manager.apply_item_effects(guild_id, character_id, item_instance_data_to_unequip, rules_config) # Re-apply
                self._character_manager.mark_character_dirty(guild_id, character_id) # Save the re-equip
                return {"success": False, "message": f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось вернуть '{item_name}' в инвентарь после снятия."}

        await self._character_manager.calculate_and_update_effective_stats(guild_id, character_id, rules_config)
        self._character_manager.mark_character_dirty(guild_id, character_id)

        print(f"{log_prefix} Item '{item_name}' unequipped from slot '{slot_id_to_unequip}'.")
        return {"success": True, "message": f"'{item_name}' снят(а) со слота '{slot_id_to_unequip}'." + ("" if is_internal_call else " и возвращен(а) в инвентарь."), "state_changed": True}

print("DEBUG: equipment_manager.py module loaded (after overwrite).")
