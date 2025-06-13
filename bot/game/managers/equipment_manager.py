# bot/game/managers/equipment_manager.py
from __future__ import annotations
import json
import logging # Added
from typing import Optional, Dict, Any, List, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.models.character import Character as CharacterModel
    from bot.ai.rules_schema import CoreGameRulesConfig, ItemDefinition as ItemDefinitionModel, EquipmentSlotDefinition
    from bot.services.db_service import DBService

logger = logging.getLogger(__name__) # Added

class EquipmentManager:
    def __init__(self,
                 character_manager: "CharacterManager",
                 inventory_manager: "InventoryManager",
                 item_manager: "ItemManager",
                 status_manager: "StatusManager",
                 rule_engine: "RuleEngine",
                 db_service: "DBService"):
        self._character_manager = character_manager
        self._inventory_manager = inventory_manager
        self._item_manager = item_manager
        self._status_manager = status_manager
        self._rule_engine = rule_engine
        self._db_service = db_service
        logger.info("EquipmentManager initialized.") # Changed

    def _get_character_equipment_dict(self, character: "CharacterModel") -> Dict[str, Any]:
        current_equipment_attr = getattr(character, 'equipment', None)
        if isinstance(current_equipment_attr, dict):
            return current_equipment_attr
        if isinstance(current_equipment_attr, str):
            try:
                equipment_dict = json.loads(current_equipment_attr)
                if not isinstance(equipment_dict, dict):
                    equipment_dict = {}
                character.equipment = equipment_dict
                return equipment_dict
            except json.JSONDecodeError:
                logger.warning("Failed to decode equipment JSON for character %s. Defaulting to empty. Data: %s", character.id, current_equipment_attr) # Added
                character.equipment = {}
                return character.equipment
        character.equipment = {}
        return character.equipment

    async def equip_item(self, guild_id: str, character_id: str, item_instance_id: str,
                         slot_id_preference: Optional[str], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        log_prefix = f"EquipmentManager.equip_item(guild='{guild_id}', char='{character_id}', item_instance='{item_instance_id}'):" # Added guild_id

        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            logger.warning("%s Character not found.", log_prefix) # Added
            return {"success": False, "message": "Персонаж не найден."}

        item_instance_data = await self._inventory_manager.get_item_instance_by_id(guild_id, character_id, item_instance_id)
        if not item_instance_data:
            logger.warning("%s Item instance '%s' not found in inventory.", log_prefix, item_instance_id) # Added
            return {"success": False, "message": f"Предмет с ID экземпляра '{item_instance_id}' не найден в инвентаре."}

        item_template_id = item_instance_data.get('template_id')
        if not item_template_id:
            item_template_id = item_instance_data.get('item_id')
            if not item_template_id:
                logger.error("%s Item data error: missing template_id for instance %s.", log_prefix, item_instance_id) # Added
                return {"success": False, "message": "Ошибка данных предмета: отсутствует ID шаблона."}
            item_instance_data['template_id'] = item_template_id

        item_definition: Optional[ItemDefinitionModel] = rules_config.item_definitions.get(item_template_id)
        if not item_definition:
            logger.warning("%s Item definition for template '%s' not found in rules_config.", log_prefix, item_template_id) # Added
            return {"success": False, "message": f"Определение для предмета '{item_template_id}' не найдено в правилах."}

        if not item_definition.equippable:
            logger.info("%s Item '%s' (template: %s) is not equippable.", log_prefix, item_definition.name, item_template_id) # Added
            return {"success": False, "message": f"Предмет '{item_definition.name}' не является экипируемым."}

        item_type = item_definition.type
        item_name = item_definition.name
        target_slot_id: Optional[str] = None
        equipment_slots_config: Dict[str, EquipmentSlotDefinition] = rules_config.equipment_slots
        character_equipment = self._get_character_equipment_dict(character)

        if slot_id_preference:
            slot_def = equipment_slots_config.get(slot_id_preference)
            if slot_def and item_type in slot_def.compatible_item_types:
                target_slot_id = slot_id_preference
            else:
                logger.info("%s Preferred slot '%s' is not compatible with item type '%s'.", log_prefix, slot_id_preference, item_type) # Added
                return {"success": False, "message": f"Слот '{slot_id_preference}' (предпочтительный) несовместим с типом предмета '{item_type}'."}
        else:
            for s_id, s_def in equipment_slots_config.items():
                if item_type in s_def.compatible_item_types:
                    if s_id not in character_equipment or character_equipment.get(s_id) is None:
                        target_slot_id = s_id; break
            if not target_slot_id:
                for s_id, s_def in equipment_slots_config.items():
                     if item_type in s_def.compatible_item_types:
                         target_slot_id = s_id; break

        if not target_slot_id:
            logger.info("%s No suitable slot found for item '%s' (type: %s).", log_prefix, item_name, item_type) # Added
            return {"success": False, "message": f"Нет подходящего слота для предмета '{item_name}' (тип: {item_type})."}

        if target_slot_id in character_equipment and character_equipment.get(target_slot_id) is not None:
            logger.info("%s Slot '%s' is occupied by %s. Unequipping it first.", log_prefix, target_slot_id, character_equipment[target_slot_id].get('template_id')) # Changed
            unequip_result = await self.unequip_item(guild_id, character_id, target_slot_id, rules_config, is_internal_call=True)
            if not unequip_result["success"]:
                logger.error("%s Failed to free slot '%s': %s", log_prefix, target_slot_id, unequip_result['message']) # Added
                return {"success": False, "message": f"Не удалось освободить слот '{target_slot_id}': {unequip_result['message']}"}
            character_equipment = self._get_character_equipment_dict(character)

        removed_from_inv = await self._inventory_manager.remove_item(
            guild_id, character_id, item_instance_id=item_instance_id, quantity_to_remove=1
        )
        if not removed_from_inv:
            logger.error("%s Failed to remove item '%s' (instance: %s) from inventory.", log_prefix, item_name, item_instance_id) # Added
            return {"success": False, "message": f"Не удалось убрать предмет '{item_name}' из инвентаря (ID экземпляра: {item_instance_id})."}

        character_equipment[target_slot_id] = item_instance_data
        character.equipment = json.dumps(character_equipment)
        await self._item_manager.apply_item_effects(guild_id, character_id, item_instance_data, rules_config)
        await self._character_manager.trigger_stats_recalculation(guild_id, character_id)

        logger.info("%s Item '%s' equipped to slot '%s'.", log_prefix, item_name, target_slot_id) # Changed
        return {"success": True, "message": f"'{item_name}' экипирован(а) в слот '{target_slot_id}'.", "state_changed": True}

    async def unequip_item(self, guild_id: str, character_id: str, slot_id_to_unequip: str,
                           rules_config: "CoreGameRulesConfig", is_internal_call: bool = False) -> Dict[str, Any]:
        log_prefix = f"EquipmentManager.unequip_item(guild='{guild_id}', char='{character_id}', slot='{slot_id_to_unequip}'):" # Added guild_id

        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            logger.warning("%s Character not found.", log_prefix) # Added
            return {"success": False, "message": "Персонаж не найден."}

        character_equipment = self._get_character_equipment_dict(character)
        if slot_id_to_unequip not in character_equipment or character_equipment.get(slot_id_to_unequip) is None:
            logger.info("%s Slot '%s' is already empty or does not exist.", log_prefix, slot_id_to_unequip) # Added
            return {"success": False, "message": f"Слот '{slot_id_to_unequip}' уже пуст или не существует."}

        item_instance_data_to_unequip = character_equipment.pop(slot_id_to_unequip)
        character.equipment = json.dumps(character_equipment)

        item_template_id = item_instance_data_to_unequip.get('template_id') or item_instance_data_to_unequip.get('item_id')
        item_name = item_instance_data_to_unequip.get('name', item_template_id)

        if not item_template_id:
             logger.critical("%s Item in slot '%s' has no template_id. Data: %s", log_prefix, slot_id_to_unequip, item_instance_data_to_unequip) # Changed
             pass

        await self._item_manager.remove_item_effects(guild_id, character_id, item_instance_data_to_unequip, rules_config)

        if not is_internal_call:
            added_to_inv_result = await self._inventory_manager.add_item(
                guild_id, character_id, item_data=item_instance_data_to_unequip
            )
            if not added_to_inv_result.get("success"):
                logger.critical("%s CRITICAL: Failed to add '%s' back to inventory: %s. Attempting to re-equip.", log_prefix, item_name, added_to_inv_result.get('message')) # Changed
                character_equipment[slot_id_to_unequip] = item_instance_data_to_unequip
                character.equipment = json.dumps(character_equipment)
                await self._character_manager.trigger_stats_recalculation(guild_id, character_id)
                return {"success": False, "message": f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось вернуть '{item_name}' в инвентарь после снятия."}

        await self._character_manager.trigger_stats_recalculation(guild_id, character_id)

        logger.info("%s Item '%s' unequipped from slot '%s'. Internal call: %s.", log_prefix, item_name, slot_id_to_unequip, is_internal_call) # Changed
        return {"success": True, "message": f"'{item_name}' снят(а) со слота '{slot_id_to_unequip}'." + ("" if is_internal_call else " и возвращен(а) в инвентарь."), "state_changed": True}

logger.debug("DEBUG: equipment_manager.py module loaded.") # Changed
