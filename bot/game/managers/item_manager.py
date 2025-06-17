# bot/game/managers/item_manager.py
"""
Manages item instances and item templates within the game.
"""
from __future__ import annotations
import json
import uuid
import traceback # Will be removed
import asyncio
import logging # Added
import sys # Added for debug printing
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
from bot.ai.rules_schema import CoreGameRulesConfig, EquipmentSlotDefinition, ItemEffectDefinition, EffectProperty
from bot.database.models import Item as SQLAlchemyItem # Added for new method

logger = logging.getLogger(__name__)
logger.debug("DEBUG: item_manager.py module loaded.")

class EquipResult(TypedDict):
    success: bool
    message: str
    character_id: Optional[str]
    item_id: Optional[str]
    slot_id: Optional[str]

class ItemManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

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
        logger.info("Initializing ItemManager...")
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
        self._diagnostic_log = [] # Added diagnostic log


        self._load_item_templates()
        logger.info("ItemManager initialized.")

    def _load_item_templates(self):
        self._diagnostic_log.append("DEBUG: ENTERING _load_item_templates")
        self._item_templates = {}

        self._diagnostic_log.append(f"DEBUG: self._settings type: {type(self._settings)}")
        self._diagnostic_log.append(f"DEBUG: self._settings value: {self._settings}")

        if self._settings:
            legacy_templates = self._settings.get("item_templates")
            self._diagnostic_log.append(f"DEBUG: legacy_templates type: {type(legacy_templates)}")
            self._diagnostic_log.append(f"DEBUG: legacy_templates value: {legacy_templates}")

            if isinstance(legacy_templates, dict):
                default_lang = self._settings.get("default_language", "en")
                self._diagnostic_log.append(f"DEBUG: Processing legacy_templates. Default lang: {default_lang}")
                for template_id, template_data in legacy_templates.items():
                    self._diagnostic_log.append(f"DEBUG: Processing template_id: {template_id}")
                    if isinstance(template_data, dict):
                        processed_template = template_data.copy()
                        name_i18n = processed_template.get("name_i18n")
                        plain_name = processed_template.get("name")
                        if not isinstance(name_i18n, dict):
                            name_i18n = {"en": plain_name} if plain_name else {"en": template_id}
                        processed_template["name_i18n"] = name_i18n
                        processed_template["name"] = name_i18n.get(default_lang, next(iter(name_i18n.values()), template_id))

                        desc_i18n = processed_template.get("description_i18n")
                        plain_desc = processed_template.get("description")
                        if not isinstance(desc_i18n, dict):
                            desc_i18n = {"en": plain_desc} if plain_desc else {"en": ""}
                        processed_template["description_i18n"] = desc_i18n
                        processed_template["description"] = desc_i18n.get(default_lang, next(iter(desc_i18n.values()), ""))

                        self._item_templates[str(template_id)] = processed_template
                        self._diagnostic_log.append(f"DEBUG: Loaded template '{template_id}' into self._item_templates.")
                self._diagnostic_log.append(f"DEBUG: Finished loop. Loaded {len(self._item_templates)} templates. Keys: {list(self._item_templates.keys())}")
            else:
                self._diagnostic_log.append("DEBUG: No 'item_templates' dictionary found in settings or it's not a dict.")
        else:
            self._diagnostic_log.append("DEBUG: No settings provided, cannot load legacy item templates.")
        self._diagnostic_log.append(f"DEBUG: EXITING _load_item_templates. Final _item_templates keys: {list(self._item_templates.keys())}")


    async def apply_item_effects(self, guild_id: str, character_id: str, item_instance: Dict[str, Any], rules_config: CoreGameRulesConfig) -> bool:
        log_prefix = f"ItemManager.apply_item_effects(guild='{guild_id}', char='{character_id}', item_instance='{item_instance.get('instance_id', 'N/A')}'):"
        if not self._status_manager or not self._character_manager:
            logger.error("%s StatusManager or CharacterManager not available.", log_prefix)
            return False

        item_template_id = item_instance.get('template_id')
        item_instance_id = item_instance.get('instance_id')

        if not item_template_id or not item_instance_id:
            logger.error("%s Item template ID or instance ID missing.", log_prefix)
            return False

        log_prefix = f"ItemManager.apply_item_effects(guild='{guild_id}', char='{character_id}', item='{item_template_id}', instance='{item_instance_id}'):"


        item_definition = rules_config.item_definitions.get(item_template_id)
        if not item_definition or not item_definition.on_equip_effects:
            logger.debug("%s No on-equip effects defined for item.", log_prefix)
            return False

        effects_applied = False
        for effect_prop in item_definition.on_equip_effects:
            effect: ItemEffectDefinition = rules_config.item_effects.get(effect_prop.effect_id)
            if not effect:
                logger.warning("%s Effect definition for '%s' not found in rules_config.item_effects.", log_prefix, effect_prop.effect_id)
                continue

            for specific_effect in effect.effects:
                if specific_effect.type == "apply_status":
                    status_def = rules_config.status_effects.get(specific_effect.status_effect_id)
                    if not status_def:
                        logger.warning("%s Status definition for '%s' not found.", log_prefix, specific_effect.status_effect_id)
                        continue
                    duration = specific_effect.duration_turns if specific_effect.duration_turns is not None else status_def.default_duration_turns
                    await self._status_manager.apply_status(
                        target_id=character_id, target_type="character", status_id=specific_effect.status_effect_id,
                        guild_id=guild_id, duration_turns=duration,
                        source_item_instance_id=item_instance_id, source_item_template_id=item_template_id
                    )
                    logger.info("%s Applied status '%s'.", log_prefix, specific_effect.status_effect_id)
                    effects_applied = True
        if effects_applied:
            self._character_manager.mark_character_dirty(guild_id, character_id)
        return effects_applied

    async def remove_item_effects(self, guild_id: str, character_id: str, item_instance: Dict[str, Any], rules_config: CoreGameRulesConfig) -> bool:
        log_prefix = f"ItemManager.remove_item_effects(guild='{guild_id}', char='{character_id}', item_instance='{item_instance.get('instance_id', 'N/A')}'):"
        if not self._status_manager or not self._character_manager:
            logger.error("%s StatusManager or CharacterManager not available.", log_prefix)
            return False

        item_template_id = item_instance.get('template_id')
        item_instance_id = item_instance.get('instance_id')

        if not item_template_id or not item_instance_id:
            logger.error("%s Item template ID or instance ID missing.", log_prefix)
            return False

        log_prefix = f"ItemManager.remove_item_effects(guild='{guild_id}', char='{character_id}', item='{item_template_id}', instance='{item_instance_id}'):"


        item_definition = rules_config.item_definitions.get(item_template_id)
        effects_removed = False
        if hasattr(self._status_manager, 'remove_statuses_by_source_item_instance'):
            removed_count = await self._status_manager.remove_statuses_by_source_item_instance(
                guild_id=guild_id, target_id=character_id, source_item_instance_id=item_instance_id
            )
            if removed_count > 0:
                logger.info("%s Removed %s status(es) sourced from item instance '%s'.", log_prefix, removed_count, item_instance_id)
                effects_removed = True
        else:
            logger.warning("%s StatusManager does not have 'remove_statuses_by_source_item_instance' method.", log_prefix)

        if effects_removed:
            self._character_manager.mark_character_dirty(guild_id, character_id)
        return effects_removed

    def _unequip_item_from_slot(self, character_inventory_data: List[Dict[str, Any]], slot_id_to_clear: str) -> bool:
        item_was_unequipped = False
        for item_entry in character_inventory_data:
            if item_entry.get("equipped") and item_entry.get("slot_id") == slot_id_to_clear:
                item_entry["equipped"] = False
                item_entry.pop("slot_id", None)
                item_was_unequipped = True
        return item_was_unequipped

    async def equip_item(self, character_id: str, guild_id: str, item_template_id_to_equip: str,
                         rules_config: CoreGameRulesConfig, slot_id_preference: Optional[str] = None
                        ) -> EquipResult:
        log_prefix = f"ItemManager.equip_item(guild='{guild_id}', char='{character_id}', item_template='{item_template_id_to_equip}'):"
        logger.debug("%s Called. Note: This method is slated for simplification/deprecation by EquipmentManager.", log_prefix)

        if not self._character_manager or not self._db_service or not self._inventory_manager:
            logger.error("%s Core services (Character, DB, Inventory) not available.", log_prefix)
            return EquipResult(success=False, message="Core services not available.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)

        return EquipResult(success=False, message="Legacy method, full refactor pending EquipmentManager.", character_id=character_id, item_id=item_template_id_to_equip, slot_id=slot_id_preference)

    async def unequip_item(self, character_id: str, guild_id: str, rules_config: CoreGameRulesConfig,
                           item_instance_id_to_unequip: Optional[str] = None, slot_id_to_unequip: Optional[str] = None
                          ) -> EquipResult:
        log_prefix = f"ItemManager.unequip_item(guild='{guild_id}', char='{character_id}', item_instance='{item_instance_id_to_unequip}', slot='{slot_id_to_unequip}'):"
        logger.debug("%s Called. Note: This method is slated for simplification/deprecation by EquipmentManager.", log_prefix)

        return EquipResult(success=False, message="Legacy method, full refactor pending EquipmentManager.", character_id=character_id, item_id=item_instance_id_to_unequip, slot_id=slot_id_to_unequip)

    async def use_item(self, guild_id: str, character_user: CharacterModel, item_template_id: str,
                       rules_config: CoreGameRulesConfig, target_entity: Optional[Any] = None) -> Dict[str, Any]:
        log_prefix = f"ItemManager.use_item(guild='{guild_id}', char='{character_user.id}', item='{item_template_id}'):"

        return {"success": False, "message": "Not fully implemented with new logging.", "state_changed": False}

    def get_item_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        if self.rules_config and template_id in self.rules_config.item_definitions:
            item_def_model = self.rules_config.item_definitions[template_id]
            try: return item_def_model.model_dump(mode='python')
            except AttributeError: return json.loads(item_def_model.model_dump_json())
        logger.debug("ItemManager.get_item_template: Template '%s' not in rules_config, checking legacy _item_templates.", template_id)
        return self._item_templates.get(str(template_id))

    async def get_all_item_instances(self, guild_id: str) -> List["Item"]:
        guild_id_str = str(guild_id)
        return list(self._items.get(guild_id_str, {}).values())

    async def get_items_by_owner(self, guild_id: str, owner_id: str) -> List["Item"]:
        return []

    async def get_items_in_location(self, guild_id: str, location_id: str) -> List["Item"]:
        return []

    def get_item_template_display_name(self, template_id: str, lang: str, default_lang: str = "en") -> str:
        template = self.get_item_template(template_id)
        if template:
            name_i18n = template.get("name_i18n")
            if isinstance(name_i18n, dict):
                return name_i18n.get(lang, name_i18n.get(default_lang, template_id))
            return template.get("name", template_id) # Fallback to plain name or ID
        return f"Item template '{template_id}' not found"


    def get_item_template_display_description(self, template_id: str, lang: str, default_lang: str = "en") -> str:
        template = self.get_item_template(template_id)
        if template:
            desc_i18n = template.get("description_i18n")
            if isinstance(desc_i18n, dict):
                return desc_i18n.get(lang, desc_i18n.get(default_lang, "No description available."))
            return template.get("description", "No description available.") # Fallback
        return f"Item template '{template_id}' not found"


    def get_item_instance(self, guild_id: str, item_id: str) -> Optional["Item"]:
        guild_id_str, item_id_str = str(guild_id), str(item_id)
        return self._items.get(guild_id_str, {}).get(item_id_str)

    async def create_item_instance(self, guild_id: str, template_id: str, owner_id: Optional[str] = None, owner_type: Optional[str] = None, location_id: Optional[str] = None, quantity: float = 1.0, initial_state: Optional[Dict[str, Any]] = None, is_temporary: bool = False, **kwargs: Any) -> Optional["Item"]:
        guild_id_str, template_id_str = str(guild_id), str(template_id)
        log_prefix = f"ItemManager.create_item_instance(guild='{guild_id_str}', template='{template_id_str}'):"
        if self._db_service is None:
            logger.error("%s DBService is None.", log_prefix)
            return None
        if not self.rules_config or template_id_str not in self.rules_config.item_definitions:
            logger.warning("%s Template '%s' not found in rules_config.", log_prefix, template_id_str)
            return None
        if quantity <= 0:
            logger.warning("%s Attempted to create item with non-positive quantity %.2f.", log_prefix, quantity)
            return None

        return None

    async def remove_item_instance(self, guild_id: str, item_id: str, **kwargs: Any) -> bool:

        return False

    async def update_item_instance(self, guild_id: str, item_id: str, updates: Dict[str, Any], **kwargs: Any) -> bool:

        return False

    async def revert_item_creation(self, guild_id: str, item_id: str, **kwargs: Any) -> bool: return await self.remove_item_instance(guild_id, item_id, **kwargs)
    async def revert_item_deletion(self, guild_id: str, item_data: Dict[str, Any], **kwargs: Any) -> bool:

        return False
    async def revert_item_update(self, guild_id: str, item_id: str, old_field_values: Dict[str, Any], **kwargs: Any) -> bool: return await self.update_item_instance(guild_id, item_id, old_field_values, **kwargs)
    async def use_item_in_combat(self, guild_id: str, actor_id: str, item_instance_id: str, target_id: Optional[str] = None, game_log_manager: Optional['GameLogManager'] = None) -> Dict[str, Any]:
        logger.debug("ItemManager.use_item_in_combat called for actor %s, item_instance %s, target %s in guild %s.", actor_id, item_instance_id, target_id, guild_id)
        return {"success": False, "consumed": False, "message": "Not implemented in detail."}

    def _clear_guild_state_cache(self, guild_id: str) -> None:
        guild_id_str = str(guild_id)
        for cache in [self._items, self._items_by_owner, self._items_by_location, self._dirty_items, self._deleted_items]: cache.pop(guild_id_str, None)
        self._items[guild_id_str] = {}
        self._items_by_owner[guild_id_str] = {}
        self._items_by_location[guild_id_str] = {}
        logger.info("ItemManager: Cleared runtime cache for guild '%s'.", guild_id_str)

    def mark_item_dirty(self, guild_id: str, item_id: str) -> None:
         if str(guild_id) in self._items and str(item_id) in self._items[str(guild_id)]:
             self._dirty_items.setdefault(str(guild_id), set()).add(str(item_id))


    def _update_lookup_caches_add(self, guild_id: str, item_data: Dict[str, Any]) -> None:

        pass
    def _update_lookup_caches_remove(self, guild_id: str, item_data: Dict[str, Any]) -> None:

        pass

    async def save_item(self, item: "Item", guild_id: str) -> bool:


        return False

    async def get_items_in_location_async(self, guild_id: str, location_id: str) -> List["Item"]: return await self.get_items_in_location(guild_id, location_id)
    async def transfer_item_world_to_character(self, guild_id: str, character_id: str, item_instance_id: str, quantity: int = 1) -> bool:
        logger.info("ItemManager.transfer_item_world_to_character: Placeholder for item %s to char %s in guild %s.", item_instance_id, character_id, guild_id)
        return False

    async def revert_item_owner_change(self, guild_id: str, item_id: str, old_owner_id: Optional[str], old_owner_type: Optional[str], old_location_id_if_unowned: Optional[str], **kwargs: Any) -> bool:


        return False

    async def revert_item_quantity_change(self, guild_id: str, item_id: str, old_quantity: float, **kwargs: Any) -> bool:


        return False

    async def get_item_sqlalchemy_instance_by_id(self, guild_id: str, item_instance_id: str) -> Optional[SQLAlchemyItem]:
        """
        Fetches a single item instance (SQLAlchemy model) by its ID from the database.
        """
        if not self._db_service:
            logger.error(f"ItemManager: DBService not available, cannot fetch item instance {item_instance_id}.")
            return None
        try:
            # Ensure model_class is the SQLAlchemy model, not Pydantic
            item_model_instance = await self._db_service.get_entity_by_pk(
                table_name='items',
                pk_value=item_instance_id,
                guild_id=guild_id,
                model_class=SQLAlchemyItem
            )
            return item_model_instance
        except Exception as e:
            logger.error(f"ItemManager: Error fetching SQLAlchemy item instance {item_instance_id} for guild {guild_id}: {e}", exc_info=True)
            return None

logger.debug("DEBUG: item_manager.py module loaded (after overwrite).")
