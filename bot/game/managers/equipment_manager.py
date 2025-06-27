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
    from bot.game.models.character import Character as CharacterPydanticModel # Renamed for clarity
    from bot.database.models.item_related import Item as ItemSQLAlchemyModel # Specific SQLAlchemy model
    from bot.database.models.character_related import Player as PlayerSQLAlchemyModel # Specific SQLAlchemy model
    from bot.database.models.character_related import NPC as NpcSQLAlchemyModel # Specific SQLAlchemy model
    from bot.ai.rules_schema import CoreGameRulesConfig, ItemDefinition as ItemDefinitionSchema, EquipmentSlotDefinition
    from bot.services.db_service import DBService
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.game_manager import GameManager


logger = logging.getLogger(__name__) # Added

class EquipmentManager:
    def __init__(self,
                 character_manager: "CharacterManager",
                 inventory_manager: "InventoryManager",
                 item_manager: "ItemManager",
                 status_manager: "StatusManager",
                 rule_engine: "RuleEngine",
                 db_service: "DBService",
                 npc_manager: Optional["NpcManager"] = None,
                 game_manager: Optional["GameManager"] = None):
        self._character_manager = character_manager
        self._inventory_manager = inventory_manager
        self._item_manager = item_manager
        self._status_manager = status_manager
        self._rule_engine = rule_engine
        self._db_service = db_service
        self._npc_manager = npc_manager
        self._game_manager = game_manager
        logger.info("EquipmentManager initialized.")

    def _get_character_equipment_dict(self, character: Union["CharacterPydanticModel", "PlayerSQLAlchemyModel"]) -> Dict[str, str]:
        equipped_item_ids_by_slot = getattr(character, 'equipment_slots_json', None)
        if not isinstance(equipped_item_ids_by_slot, dict):
            logger.warning(f"Character {getattr(character, 'id', 'Unknown')} equipment_slots_json is not a dict or is None. Defaulting to empty. Type: {type(equipped_item_ids_by_slot)}")
            return {}
        return equipped_item_ids_by_slot

    async def equip_item(self, guild_id: str, character_id: str, item_instance_id: str,
                         slot_id_preference: Optional[str], rules_config: "CoreGameRulesConfig") -> Dict[str, Any]:
        log_prefix = f"EquipmentManager.equip_item(guild='{guild_id}', char='{character_id}', item_instance='{item_instance_id}'):"

        character: Optional["CharacterPydanticModel"] = None
        if self._character_manager:
            character = await self._character_manager.get_character(guild_id, character_id)

        if not character:
            logger.warning("%s Character not found.", log_prefix)
            return {"success": False, "message": "Персонаж не найден."}

        item_instance_data: Optional[Dict[str, Any]] = None
        if self._inventory_manager and hasattr(self._inventory_manager, 'get_item_instance_by_id') and callable(self._inventory_manager.get_item_instance_by_id):
            item_instance_data = await self._inventory_manager.get_item_instance_by_id(guild_id, character_id, item_instance_id)

        if not item_instance_data:
            logger.warning("%s Item instance '%s' not found in inventory.", log_prefix, item_instance_id)
            return {"success": False, "message": f"Предмет с ID экземпляра '{item_instance_id}' не найден в инвентаре."}

        item_template_id = item_instance_data.get('template_id')
        if not item_template_id: # Fallback if template_id is missing but item_id (referring to template) is present
            item_template_id = item_instance_data.get('item_id')
            if not item_template_id:
                logger.error("%s Item data error: missing template_id for instance %s.", log_prefix, item_instance_id)
                return {"success": False, "message": "Ошибка данных предмета: отсутствует ID шаблона."}
            item_instance_data['template_id'] = item_template_id # Ensure template_id is set in the dict for later use

        item_definition: Optional[ItemDefinitionSchema] = None
        if hasattr(rules_config, 'item_definitions') and isinstance(rules_config.item_definitions, dict):
            item_definition = rules_config.item_definitions.get(item_template_id)

        if not item_definition:
            logger.warning("%s Item definition for template '%s' not found in rules_config.", log_prefix, item_template_id)
            return {"success": False, "message": f"Определение для предмета '{item_template_id}' не найдено в правилах."}

        if not getattr(item_definition, 'equippable', False):
            item_def_name = getattr(item_definition, 'name', item_template_id)
            logger.info("%s Item '%s' (template: %s) is not equippable.", log_prefix, item_def_name, item_template_id)
            return {"success": False, "message": f"Предмет '{item_def_name}' не является экипируемым."}

        item_type = getattr(item_definition, 'type', None)
        item_name = getattr(item_definition, 'name', item_template_id)
        target_slot_id: Optional[str] = None

        equipment_slots_config: Dict[str, EquipmentSlotDefinition] = {}
        if hasattr(rules_config, 'equipment_slots') and isinstance(rules_config.equipment_slots, dict):
            equipment_slots_config = rules_config.equipment_slots

        current_slots = getattr(character, 'equipment_slots_json', None)
        if not isinstance(current_slots, dict):
            current_slots = {}
            setattr(character, 'equipment_slots_json', current_slots)

        if slot_id_preference:
            slot_def = equipment_slots_config.get(slot_id_preference)
            compatible_types = getattr(slot_def, 'compatible_item_types', [])
            if slot_def and item_type in compatible_types:
                target_slot_id = slot_id_preference
            else:
                logger.info("%s Preferred slot '%s' is not compatible with item type '%s'. Compatible: %s", log_prefix, slot_id_preference, item_type, compatible_types)
                return {"success": False, "message": f"Слот '{slot_id_preference}' (предпочтительный) несовместим с типом предмета '{item_type}'."}
        else:
            for s_id, s_def_loop in equipment_slots_config.items():
                loop_compatible_types = getattr(s_def_loop, 'compatible_item_types', [])
                if item_type in loop_compatible_types:
                    if s_id not in current_slots or current_slots.get(s_id) is None:
                        target_slot_id = s_id
                        break
            if not target_slot_id: # If no empty compatible slot, find any compatible slot
                for s_id_overwrite, s_def_overwrite in equipment_slots_config.items():
                    overwrite_compatible_types = getattr(s_def_overwrite, 'compatible_item_types', [])
                    if item_type in overwrite_compatible_types:
                        target_slot_id = s_id_overwrite
                        break

        if not target_slot_id:
            logger.info("%s No suitable slot found for item '%s' (type: %s).", log_prefix, item_name, item_type)
            return {"success": False, "message": f"Нет подходящего слота для предмета '{item_name}' (тип: {item_type})."}

        if current_slots.get(target_slot_id) is not None:
            existing_item_id = current_slots[target_slot_id]
            logger.info("%s Slot '%s' is occupied by item ID %s. Unequipping it first.", log_prefix, target_slot_id, existing_item_id)
            unequip_result = await self.unequip_item(guild_id, character_id, target_slot_id, rules_config, is_internal_call=True)
            if not unequip_result["success"]:
                logger.error("%s Failed to free slot '%s': %s", log_prefix, target_slot_id, unequip_result['message'])
                return {"success": False, "message": f"Не удалось освободить слот '{target_slot_id}': {unequip_result['message']}"}
            current_slots = getattr(character, 'equipment_slots_json', {})

        removed_success = False
        if self._inventory_manager and hasattr(self._inventory_manager, 'remove_item') and callable(self._inventory_manager.remove_item):
            removed_from_inv_result = await self._inventory_manager.remove_item( # Expects a result dict
                guild_id, character_id, item_instance_id=item_instance_id, quantity_to_remove=1
            )
            removed_success = removed_from_inv_result.get("success", False) if isinstance(removed_from_inv_result, dict) else False


        if not removed_success:
            logger.error("%s Failed to remove item '%s' (instance: %s) from inventory.", log_prefix, item_name, item_instance_id)
            return {"success": False, "message": f"Не удалось убрать предмет '{item_name}' из инвентаря (ID экземпляра: {item_instance_id})."}

        current_slots[target_slot_id] = item_instance_id
        setattr(character, 'equipment_slots_json', current_slots) # Use setattr for Pydantic model

        if self._character_manager:
            self._character_manager.mark_character_dirty(guild_id, character_id)

        if self._item_manager and self._character_manager: # Ensure managers exist
            await self._item_manager.apply_item_effects(guild_id, character_id, item_instance_data, rules_config)
            await self._character_manager.trigger_stats_recalculation(guild_id, character_id)

        logger.info("%s Item '%s' (ID: %s) equipped to slot '%s'.", log_prefix, item_name, item_instance_id, target_slot_id)
        return {"success": True, "message": f"'{item_name}' экипирован(а) в слот '{target_slot_id}'.", "state_changed": True}

    async def unequip_item(self, guild_id: str, character_id: str, slot_id_to_unequip: str,
                           rules_config: "CoreGameRulesConfig", is_internal_call: bool = False) -> Dict[str, Any]:
        log_prefix = f"EquipmentManager.unequip_item(guild='{guild_id}', char='{character_id}', slot='{slot_id_to_unequip}'):"

        character: Optional["CharacterPydanticModel"] = None
        if self._character_manager:
            character = await self._character_manager.get_character(guild_id, character_id)

        if not character:
            logger.warning("%s Character not found.", log_prefix)
            return {"success": False, "message": "Персонаж не найден."}

        character_equipment_slots = getattr(character, 'equipment_slots_json', None)
        if not isinstance(character_equipment_slots, dict):
            character_equipment_slots = {}

        if slot_id_to_unequip not in character_equipment_slots or character_equipment_slots.get(slot_id_to_unequip) is None:
            logger.info("%s Slot '%s' is already empty or does not exist.", log_prefix, slot_id_to_unequip)
            return {"success": False, "message": f"Слот '{slot_id_to_unequip}' уже пуст или не существует."}

        item_instance_id_to_unequip = character_equipment_slots.pop(slot_id_to_unequip, None)

        if not item_instance_id_to_unequip:
            logger.error("%s Failed to get item_instance_id from slot '%s' though it was supposedly occupied.", log_prefix, slot_id_to_unequip)
            return {"success": False, "message": "Ошибка при извлечении предмета из слота."}

        setattr(character, 'equipment_slots_json', character_equipment_slots) # Use setattr
        if self._character_manager:
            self._character_manager.mark_character_dirty(guild_id, character_id)

        item_instance_model_to_unequip: Optional[ItemSQLAlchemyModel] = None
        if self._item_manager and hasattr(self._item_manager, 'get_item_sqlalchemy_instance_by_id') and callable(self._item_manager.get_item_sqlalchemy_instance_by_id):
            item_instance_model_to_unequip = await self._item_manager.get_item_sqlalchemy_instance_by_id(guild_id, item_instance_id_to_unequip)

        item_instance_data_to_unequip: Optional[Dict[str, Any]] = None
        if item_instance_model_to_unequip:
            if hasattr(item_instance_model_to_unequip, 'to_dict') and callable(item_instance_model_to_unequip.to_dict):
                item_instance_data_to_unequip = item_instance_model_to_unequip.to_dict()
            else:
                logger.warning(f"EquipmentManager: Item SQLAlchemy model {item_instance_id_to_unequip} missing to_dict(). Creating dict manually.")
                item_instance_data_to_unequip = {
                    "id": str(getattr(item_instance_model_to_unequip, 'id', item_instance_id_to_unequip)),
                    "template_id": getattr(item_instance_model_to_unequip, 'template_id', None),
                    "name_i18n": getattr(item_instance_model_to_unequip, 'name_i18n', {}),
                    "properties": getattr(item_instance_model_to_unequip, 'properties', {}),
                }

        if not item_instance_data_to_unequip:
            logger.critical("%s CRITICAL: Failed to fetch or convert item instance data for ID '%s'.", log_prefix, item_instance_id_to_unequip)
            if self._character_manager: await self._character_manager.trigger_stats_recalculation(guild_id, character_id)
            return {"success": False, "message": f"КРИТИЧЕСКАЯ ОШИБКА: Данные для предмета ID '{item_instance_id_to_unequip}' не найдены."}

        item_template_id = item_instance_data_to_unequip.get('template_id')
        item_name_i18n = item_instance_data_to_unequip.get('name_i18n', {})
        item_name = item_name_i18n.get("en", item_template_id if item_template_id else "Неизвестный предмет") if isinstance(item_name_i18n, dict) else (item_template_id or "Неизвестный предмет")


        if self._item_manager:
            await self._item_manager.remove_item_effects(guild_id, character_id, item_instance_data_to_unequip, rules_config)

        if not is_internal_call:
            added_to_inv_result: Dict[str, Any] = {"success": False, "message": "InventoryManager not available"}
            if self._inventory_manager and hasattr(self._inventory_manager, 'add_item') and callable(self._inventory_manager.add_item):
                added_to_inv_result = await self._inventory_manager.add_item(
                    guild_id, character_id, item_data=item_instance_data_to_unequip
                )

            if not added_to_inv_result.get("success"):
                logger.critical("%s CRITICAL: Failed to add '%s' (ID: %s) back to inventory: %s. Attempting to re-equip.", log_prefix, item_name, item_instance_id_to_unequip, added_to_inv_result.get('message'))
                character_equipment_slots[slot_id_to_unequip] = item_instance_id_to_unequip
                setattr(character, 'equipment_slots_json', character_equipment_slots) # Use setattr
                if self._character_manager: self._character_manager.mark_character_dirty(guild_id, character_id)
                if self._item_manager: await self._item_manager.apply_item_effects(guild_id, character_id, item_instance_data_to_unequip, rules_config)
                if self._character_manager: await self._character_manager.trigger_stats_recalculation(guild_id, character_id)
                return {"success": False, "message": f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось вернуть '{item_name}' в инвентарь после снятия. Предмет возвращен в слот."}

        if self._character_manager:
            await self._character_manager.trigger_stats_recalculation(guild_id, character_id)

        logger.info("%s Item '%s' (ID: %s) unequipped from slot '%s'. Internal call: %s.", log_prefix, item_name, item_instance_id_to_unequip, slot_id_to_unequip, is_internal_call)
        return {"success": True, "message": f"'{item_name}' снят(а) со слота '{slot_id_to_unequip}'." + ("" if is_internal_call else " и возвращен(а) в инвентарь."), "state_changed": True}

    async def get_equipped_item_instances(self, entity_id: str, entity_type: str, guild_id: str) -> List['ItemSQLAlchemyModel']:
        """
        Retrieves a list of full Item SQLAlchemy model instances for all items equipped by the entity.
        """
        equipped_items: List['ItemSQLAlchemyModel'] = []
        entity: Optional[Union["PlayerSQLAlchemyModel", "NpcSQLAlchemyModel", "CharacterPydanticModel"]] = None
        equipment_slots_dict: Optional[Dict[str, str]] = None

        if entity_type.lower() == "player":
            if self._character_manager:
                # get_character returns a Pydantic model.
                pydantic_char_model = await self._character_manager.get_character(guild_id, entity_id)
                if pydantic_char_model and hasattr(pydantic_char_model, 'equipment_slots_json'):
                    equipment_slots_dict = getattr(pydantic_char_model, 'equipment_slots_json')
                entity = pydantic_char_model
            else:
                logger.warning(f"EquipmentManager: CharacterManager not available. Cannot get equipped items for player {entity_id}.")
                return []

        elif entity_type.lower() == "npc":
            if self._npc_manager:
                # Assuming get_npc returns an NPC Pydantic model or SQLAlchemy model that has equipment_data
                npc_model_or_data = await self._npc_manager.get_npc(guild_id, entity_id)
                if npc_model_or_data and hasattr(npc_model_or_data, 'equipment_data'): # Check for Pydantic or direct dict
                    equipment_slots_dict = getattr(npc_model_or_data, 'equipment_data')
                elif npc_model_or_data and isinstance(npc_model_or_data, dict) and 'equipment_data' in npc_model_or_data: # if get_npc returns dict
                    equipment_slots_dict = npc_model_or_data['equipment_data']
                entity = npc_model_or_data
            else:
                logger.warning(f"EquipmentManager: NpcManager not available. Cannot get equipped items for NPC {entity_id}.")
                return []

        if not isinstance(equipment_slots_dict, dict):
            logger.debug(f"EquipmentManager: No equipment data or not a dict for entity {entity_id} ({entity_type}).")
            return []

        if not self._item_manager or not hasattr(self._item_manager, 'get_item_sqlalchemy_instance_by_id') or not callable(self._item_manager.get_item_sqlalchemy_instance_by_id):
            logger.error(f"EquipmentManager: ItemManager or get_item_sqlalchemy_instance_by_id method not available. Cannot fetch equipped item instances for {entity_id}.")
            return []

        for slot, item_id_str in equipment_slots_dict.items():
            if item_id_str and isinstance(item_id_str, str):
                item_instance_model = await self._item_manager.get_item_sqlalchemy_instance_by_id(guild_id, item_id_str)
                if item_instance_model:
                    equipped_items.append(item_instance_model)
                else:
                    entity_display_id = getattr(entity, 'id', entity_id) if entity else entity_id
                    logger.warning(f"EquipmentManager: Equipped item instance ID '{item_id_str}' in slot '{slot}' for entity {entity_display_id} not found.")

        return equipped_items

# logger.debug("DEBUG: equipment_manager.py module loaded.")
