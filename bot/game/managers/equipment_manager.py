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
    from bot.game.models.character import Character as CharacterModel # This is likely the Pydantic wrapper
    from bot.database.models import Player as PlayerModel, NPC as NpcModel, Item # SQLAlchemy models
    from bot.ai.rules_schema import CoreGameRulesConfig, ItemDefinition as ItemDefinitionModel, EquipmentSlotDefinition
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
                 npc_manager: Optional["NpcManager"] = None, # Added
                 game_manager: Optional["GameManager"] = None): # Added
        self._character_manager = character_manager
        self._inventory_manager = inventory_manager
        self._item_manager = item_manager
        self._status_manager = status_manager
        self._rule_engine = rule_engine
        self._db_service = db_service
        self._npc_manager = npc_manager # Added
        self._game_manager = game_manager # Added
        logger.info("EquipmentManager initialized.") # Changed

    def _get_character_equipment_dict(self, character: Union["CharacterModel", "PlayerModel"]) -> Dict[str, str]:
        # This method now assumes 'character' is the SQLAlchemy Player model instance
        # or a Pydantic CharacterModel that directly mirrors PlayerModel's equipment_slots_json
        equipped_item_ids_by_slot = getattr(character, 'equipment_slots_json', None)
        if not isinstance(equipped_item_ids_by_slot, dict):
            logger.warning(f"Character {getattr(character, 'id', 'Unknown')} equipment_slots_json is not a dict or is None. Defaulting to empty. Type: {type(equipped_item_ids_by_slot)}")
            return {}
        return equipped_item_ids_by_slot # Returns {slot_id: item_instance_id}

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
        # Read from character.equipment_slots_json (dict of slot_id: item_instance_id)
        # The Pydantic CharacterModel should have equipment_slots_json attribute
        current_slots = getattr(character, 'equipment_slots_json', None)
        if not isinstance(current_slots, dict):
            current_slots = {} # Initialize if None or not a dict
            setattr(character, 'equipment_slots_json', current_slots) # Ensure it's on the model

        if slot_id_preference:
            slot_def = equipment_slots_config.get(slot_id_preference)
            if slot_def and item_type in slot_def.compatible_item_types:
                target_slot_id = slot_id_preference
            else:
                logger.info("%s Preferred slot '%s' is not compatible with item type '%s'.", log_prefix, slot_id_preference, item_type)
                return {"success": False, "message": f"Слот '{slot_id_preference}' (предпочтительный) несовместим с типом предмета '{item_type}'."}
        else:
            # Find an empty compatible slot
            for s_id, s_def in equipment_slots_config.items():
                if item_type in s_def.compatible_item_types:
                    if s_id not in current_slots or current_slots.get(s_id) is None:
                        target_slot_id = s_id
                        break
            # If no empty compatible slot, find any compatible slot (will overwrite)
            if not target_slot_id:
                for s_id, s_def in equipment_slots_config.items():
                     if item_type in s_def.compatible_item_types:
                         target_slot_id = s_id
                         break

        if not target_slot_id:
            logger.info("%s No suitable slot found for item '%s' (type: %s).", log_prefix, item_name, item_type)
            return {"success": False, "message": f"Нет подходящего слота для предмета '{item_name}' (тип: {item_type})."}

        # If slot is occupied, unequip existing item first
        if current_slots.get(target_slot_id) is not None:
            existing_item_id = current_slots[target_slot_id]
            logger.info("%s Slot '%s' is occupied by item ID %s. Unequipping it first.", log_prefix, target_slot_id, existing_item_id)
            unequip_result = await self.unequip_item(guild_id, character_id, target_slot_id, rules_config, is_internal_call=True)
            if not unequip_result["success"]:
                logger.error("%s Failed to free slot '%s': %s", log_prefix, target_slot_id, unequip_result['message'])
                return {"success": False, "message": f"Не удалось освободить слот '{target_slot_id}': {unequip_result['message']}"}
            # _get_character_equipment_dict is removed, current_slots should be up-to-date if unequip_item modified it.
            # Re-fetch or ensure character model's equipment_slots_json is the source of truth and modified by unequip_item.
            current_slots = getattr(character, 'equipment_slots_json', {}) # Re-access after unequip

        removed_from_inv = await self._inventory_manager.remove_item(
            guild_id, character_id, item_instance_id=item_instance_id, quantity_to_remove=1
        )
        if not removed_from_inv:
            logger.error("%s Failed to remove item '%s' (instance: %s) from inventory.", log_prefix, item_name, item_instance_id)
            return {"success": False, "message": f"Не удалось убрать предмет '{item_name}' из инвентаря (ID экземпляра: {item_instance_id})."}

        # Store item_instance_id in the slot
        current_slots[target_slot_id] = item_instance_id
        character.equipment_slots_json = current_slots # Update the character model attribute

        self._character_manager.mark_character_dirty(guild_id, character_id) # Mark for saving

        # Apply effects using item_instance_data (full data, not just ID)
        await self._item_manager.apply_item_effects(guild_id, character_id, item_instance_data, rules_config)
        await self._character_manager.trigger_stats_recalculation(guild_id, character_id)

        logger.info("%s Item '%s' (ID: %s) equipped to slot '%s'.", log_prefix, item_name, item_instance_id, target_slot_id)
        return {"success": True, "message": f"'{item_name}' экипирован(а) в слот '{target_slot_id}'.", "state_changed": True}

    async def unequip_item(self, guild_id: str, character_id: str, slot_id_to_unequip: str,
                           rules_config: "CoreGameRulesConfig", is_internal_call: bool = False) -> Dict[str, Any]:
        log_prefix = f"EquipmentManager.unequip_item(guild='{guild_id}', char='{character_id}', slot='{slot_id_to_unequip}'):" # Added guild_id

        character = await self._character_manager.get_character(guild_id, character_id)
        if not character:
            logger.warning("%s Character not found.", log_prefix) # Added
            return {"success": False, "message": "Персонаж не найден."}

        # Read from character.equipment_slots_json
        character_equipment_slots = getattr(character, 'equipment_slots_json', None)
        if not isinstance(character_equipment_slots, dict):
            character_equipment_slots = {} # Default to empty if None or not dict
            # No need to setattr here unless we intend to save an empty dict for a character who had nothing.
            # The pop below will handle non-existent slot gracefully.

        if slot_id_to_unequip not in character_equipment_slots or character_equipment_slots.get(slot_id_to_unequip) is None:
            logger.info("%s Slot '%s' is already empty or does not exist.", log_prefix, slot_id_to_unequip)
            return {"success": False, "message": f"Слот '{slot_id_to_unequip}' уже пуст или не существует."}

        item_instance_id_to_unequip = character_equipment_slots.pop(slot_id_to_unequip, None)

        if not item_instance_id_to_unequip: # Should not happen if previous check passed, but good for safety
            logger.error("%s Failed to get item_instance_id from slot '%s' though it was supposedly occupied.", log_prefix, slot_id_to_unequip)
            return {"success": False, "message": "Ошибка при извлечении предмета из слота."}

        # Update the character model's equipment slots
        character.equipment_slots_json = character_equipment_slots
        self._character_manager.mark_character_dirty(guild_id, character_id)

        # Fetch full item data for effects removal and adding to inventory
        # Change to use the new SQLAlchemy model fetching method
        item_instance_model_to_unequip = await self._item_manager.get_item_sqlalchemy_instance_by_id(guild_id, item_instance_id_to_unequip)

        item_instance_data_to_unequip: Optional[Dict[str, Any]] = None
        if item_instance_model_to_unequip:
            if hasattr(item_instance_model_to_unequip, 'to_dict') and callable(item_instance_model_to_unequip.to_dict):
                item_instance_data_to_unequip = item_instance_model_to_unequip.to_dict()
            else:
                # Fallback: Manually create a dict if no to_dict() method. This is less ideal.
                # This requires knowing the Item SQLAlchemy model's attributes.
                logger.warning(f"EquipmentManager: Item SQLAlchemy model {item_instance_id_to_unequip} missing to_dict(). Creating dict manually (may be incomplete).")
                item_instance_data_to_unequip = {
                    "id": str(item_instance_model_to_unequip.id), # Ensure it's string if UUID
                    "template_id": getattr(item_instance_model_to_unequip, 'template_id', None),
                    "name_i18n": getattr(item_instance_model_to_unequip, 'name_i18n', {}),
                    "properties": getattr(item_instance_model_to_unequip, 'properties', {}),
                    # Add other necessary fields that remove_item_effects/add_item might need
                }

        if not item_instance_data_to_unequip: # Check if conversion or fetch failed
            logger.critical("%s CRITICAL: Failed to fetch or convert item instance data for ID '%s' which was unequipped from slot '%s'. Effects cannot be removed, item not added to inventory.", log_prefix, item_instance_id_to_unequip, slot_id_to_unequip)
            # Decide if we should re-equip or just log. Re-equipping might be complex if item_instance_id is now invalid.
            # For now, log critical and proceed (stats recalc will happen).
            # The slot is already empty in character_equipment_slots.
            await self._character_manager.trigger_stats_recalculation(guild_id, character_id)
            return {"success": False, "message": f"КРИТИЧЕСКАЯ ОШИБКА: Данные для предмета ID '{item_instance_id_to_unequip}' не найдены после снятия."}

        item_template_id = item_instance_data_to_unequip.get('template_id') # Assuming item_instance_data_to_unequip is a dict
        item_name = item_instance_data_to_unequip.get('name', item_template_id if item_template_id else "Неизвестный предмет")


        await self._item_manager.remove_item_effects(guild_id, character_id, item_instance_data_to_unequip, rules_config)

        if not is_internal_call:
            # item_instance_data_to_unequip is already a dict here.
            # InventoryManager.add_item expects item_data which should be this dict.
            added_to_inv_result = await self._inventory_manager.add_item(
                guild_id, character_id, item_data=item_instance_data_to_unequip
            )
            if not added_to_inv_result.get("success"):
                logger.critical("%s CRITICAL: Failed to add '%s' (ID: %s) back to inventory: %s. Attempting to re-equip.", log_prefix, item_name, item_instance_id_to_unequip, added_to_inv_result.get('message'))
                # Re-equip logic (best effort)
                character_equipment_slots[slot_id_to_unequip] = item_instance_id_to_unequip # Add ID back
                character.equipment_slots_json = character_equipment_slots
                self._character_manager.mark_character_dirty(guild_id, character_id) # Mark dirty again
                # Also re-apply effects if possible
                await self._item_manager.apply_item_effects(guild_id, character_id, item_instance_data_to_unequip, rules_config)
                await self._character_manager.trigger_stats_recalculation(guild_id, character_id)
                return {"success": False, "message": f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось вернуть '{item_name}' в инвентарь после снятия. Предмет возвращен в слот."}

        await self._character_manager.trigger_stats_recalculation(guild_id, character_id)

        logger.info("%s Item '%s' (ID: %s) unequipped from slot '%s'. Internal call: %s.", log_prefix, item_name, item_instance_id_to_unequip, slot_id_to_unequip, is_internal_call)
        return {"success": True, "message": f"'{item_name}' снят(а) со слота '{slot_id_to_unequip}'." + ("" if is_internal_call else " и возвращен(а) в инвентарь."), "state_changed": True}

    async def get_equipped_item_instances(self, entity_id: str, entity_type: str, guild_id: str) -> List['Item']: # Item from bot.database.models
        """
        Retrieves a list of full Item model instances for all items equipped by the entity.
        """
        equipped_items: List['Item'] = []
        entity: Optional[Union["PlayerModel", "NpcModel"]] = None # Using SQLAlchemy model type hints
        equipment_slots_dict: Optional[Dict[str, str]] = None

        if entity_type.lower() == "player":
            if self._character_manager:
                # get_character returns a Pydantic model. We need the SQLAlchemy Player model
                # Assuming CharacterManager can provide the underlying PlayerModel or has a method for it.
                # For now, let's assume get_character can return PlayerModel if type hints are set up for it,
                # or CharacterManager needs a specific method for this.
                # This is a potential point of failure if get_character strictly returns Pydantic.
                # However, the CharacterManager._characters cache stores Pydantic Character objects.
                # The Character Pydantic model should have equipment_slots_json.
                pydantic_char_model = await self._character_manager.get_character(guild_id, entity_id)
                if pydantic_char_model and hasattr(pydantic_char_model, 'equipment_slots_json'):
                    equipment_slots_dict = getattr(pydantic_char_model, 'equipment_slots_json')
                entity = pydantic_char_model # For logging entity.id later, though not used for fetching IDs
            else:
                logger.warning(f"EquipmentManager: CharacterManager not available. Cannot get equipped items for player {entity_id}.")
                return []

        elif entity_type.lower() == "npc":
            if self._npc_manager:
                entity = await self._npc_manager.get_npc(guild_id, entity_id) # Assumes this returns NPC DB model
                if entity and hasattr(entity, 'equipment_data'):
                    equipment_slots_dict = getattr(entity, 'equipment_data')
            else:
                logger.warning(f"EquipmentManager: NpcManager not available. Cannot get equipped items for NPC {entity_id}.")
                return []

        if not isinstance(equipment_slots_dict, dict):
            logger.debug(f"EquipmentManager: No equipment data or not a dict for entity {entity_id} ({entity_type}).")
            return []

        if not self._item_manager:
            logger.error(f"EquipmentManager: ItemManager not available. Cannot fetch equipped item instances for {entity_id}.")
            return []

        for slot, item_id in equipment_slots_dict.items():
            if item_id and isinstance(item_id, str):
                # Use the new method that returns SQLAlchemy Item models
                item_instance_model = await self._item_manager.get_item_sqlalchemy_instance_by_id(guild_id, item_id)
                if item_instance_model:
                    equipped_items.append(item_instance_model) # List of SQLAlchemy Item models
                else:
                    logger.warning(f"EquipmentManager: Equipped item instance ID '{item_id}' in slot '{slot}' for entity {getattr(entity, 'id', entity_id)} not found.")

        return equipped_items

logger.debug("DEBUG: equipment_manager.py module loaded.") # Changed
