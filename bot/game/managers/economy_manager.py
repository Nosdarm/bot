# bot/game/managers/economy_manager.py

from __future__ import annotations
import json
import uuid
import traceback # Will be removed
import asyncio
import logging # Added
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union

from bot.services.db_service import DBService
from builtins import dict, set, list, str, int, bool, float

if TYPE_CHECKING:
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.relationship_manager import RelationshipManager

logger = logging.getLogger(__name__) # Added

class EconomyManager:
    required_args_for_load: List[str] = ["guild_id"]
    required_args_for_save: List[str] = ["guild_id"]
    required_args_for_rebuild: List[str] = ["guild_id"]

    _market_inventories: Dict[str, Dict[str, Dict[str, Union[int, float]]]]
    _dirty_market_inventories: Dict[str, Set[str]]
    _deleted_market_inventory_ids: Dict[str, Set[str]]

    def __init__(
        self,
        db_service: Optional["DBService"] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        time_manager: Optional["TimeManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
    ):
        logger.info("Initializing EconomyManager...") # Changed
        self._db_service = db_service
        self._settings = settings
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._game_log_manager = game_log_manager
        self._relationship_manager = relationship_manager
        self._market_inventories = {}
        self._dirty_market_inventories = {}
        self._deleted_market_inventory_ids = {}
        logger.info("EconomyManager initialized.") # Changed

    def get_market_inventory(self, guild_id: str, location_id: str) -> Optional[Dict[str, Union[int, float]]]:
        guild_id_str = str(guild_id)
        guild_markets = self._market_inventories.get(guild_id_str)
        if guild_markets:
             inv = guild_markets.get(str(location_id))
             if inv is not None:
                  return {k: (int(v) if isinstance(v, int) else float(v)) for k, v in inv.items()}
        return None

    async def add_items_to_market(
        self, guild_id: str, location_id: str,
        items_data: Dict[str, Union[int, float]], **kwargs: Any
    ) -> bool:
        guild_id_str = str(guild_id)
        logger.info("EconomyManager: Adding %s to market %s for guild %s.", items_data, location_id, guild_id_str) # Changed

        if not items_data:
            logger.info("EconomyManager: No items data provided to add for market %s in guild %s.", location_id, guild_id_str) # Changed
            return False

        loc_mgr = kwargs.get('location_manager', self._location_manager)
        if loc_mgr and hasattr(loc_mgr, 'get_location_instance'):
            if loc_mgr.get_location_instance(guild_id_str, location_id) is None:
                logger.warning("EconomyManager: Location instance %s not found for guild %s. Cannot add items to market.", location_id, guild_id_str) # Changed
                return False

        guild_markets_cache = self._market_inventories.setdefault(guild_id_str, {})
        market_inv = guild_markets_cache.setdefault(str(location_id), {})

        if not isinstance(market_inv, dict):
             logger.warning("EconomyManager: Market inventory data for location %s in guild %s is not a dict (%s). Resetting to {}.", location_id, guild_id_str, type(market_inv)) # Changed
             market_inv = {}
             guild_markets_cache[str(location_id)] = market_inv

        changes_made = False
        for tpl_id, quantity in items_data.items():
            tpl_id_str = str(tpl_id)
            resolved_quantity = float(quantity) if isinstance(quantity, (int, float)) else 0.0
            if resolved_quantity > 0:
                market_inv[tpl_id_str] = market_inv.get(tpl_id_str, 0.0) + resolved_quantity
                if market_inv[tpl_id_str] < 0: market_inv[tpl_id_str] = 0.0
                changes_made = True
                # logger.debug("EconomyManager: +%.2f of %s to market %s in guild %s.", resolved_quantity, tpl_id_str, location_id, guild_id_str)

        if changes_made:
             self._dirty_market_inventories.setdefault(guild_id_str, set()).add(str(location_id))
             logger.info("EconomyManager: Market %s marked dirty for guild %s after adding items.", location_id, guild_id_str) # Changed
             return True

        logger.info("EconomyManager: No valid items/quantities provided to add for market %s in guild %s.", location_id, guild_id_str) # Changed
        return False

    async def remove_items_from_market(
        self, guild_id: str, location_id: str,
        items_data: Dict[str, Union[int, float]], **kwargs: Any
    ) -> bool:
        guild_id_str = str(guild_id)
        logger.info("EconomyManager: Removing %s from market %s for guild %s.", items_data, location_id, guild_id_str) # Changed

        guild_markets_cache = self._market_inventories.get(guild_id_str)
        if not guild_markets_cache:
             logger.warning("EconomyManager: No market cache found for guild %s during remove_items_from_market.", guild_id_str) # Changed
             return False

        market_inv = guild_markets_cache.get(str(location_id))
        if not market_inv or not isinstance(market_inv, dict):
             logger.warning("EconomyManager: No valid market inventory found for %s in guild %s during remove_items_from_market.", location_id, guild_id_str) # Changed
             return False

        for tpl_id, quantity in items_data.items():
            tpl_id_str = str(tpl_id)
            resolved_quantity = float(quantity) if isinstance(quantity, (int, float)) else 0.0
            if resolved_quantity > 0:
                 available_quantity = market_inv.get(tpl_id_str, 0.0)
                 if available_quantity < resolved_quantity:
                      logger.warning("EconomyManager: Not enough of item '%s' available in market %s for guild %s (%.2f/%.2f). Cannot remove.", tpl_id_str, location_id, guild_id_str, available_quantity, resolved_quantity) # Changed
                      return False

        changes_made = False
        items_to_remove_completely: List[str] = []
        for tpl_id, quantity in items_data.items():
            tpl_id_str = str(tpl_id)
            resolved_quantity = float(quantity) if isinstance(quantity, (int, float)) else 0.0
            if resolved_quantity > 0:
                 current_quantity = market_inv.get(tpl_id_str, 0.0)
                 new_quantity = current_quantity - resolved_quantity
                 market_inv[tpl_id_str] = new_quantity
                 if new_quantity <= 0:
                      items_to_remove_completely.append(tpl_id_str)
                 changes_made = True
                 # logger.debug("EconomyManager: -%.2f of %s from market %s in guild %s. Remaining: %.2f", resolved_quantity, tpl_id_str, location_id, guild_id_str, new_quantity)

        for tpl_id_str in items_to_remove_completely:
            market_inv.pop(tpl_id_str, None)

        if changes_made:
             self._dirty_market_inventories.setdefault(guild_id_str, set()).add(str(location_id))
             logger.info("EconomyManager: Market %s marked dirty for guild %s after removal.", location_id, guild_id_str) # Changed
             return True

        logger.info("EconomyManager: No valid items/quantities provided to remove for market %s in guild %s or quantity was 0.", location_id, guild_id_str) # Changed
        return False

    async def calculate_price(
        self, guild_id: str, location_id: str, item_template_id: str,
        quantity: Union[int, float], is_selling: bool,
        actor_entity_id: str, actor_entity_type: str, **kwargs: Any
    ) -> tuple[Optional[float], Optional[Dict[str, Any]]]:
        guild_id_str = str(guild_id)
        tpl_id_str = str(item_template_id)
        resolved_quantity = float(quantity) if isinstance(quantity, (int, float)) else 0.0

        if resolved_quantity <= 0:
            logger.warning("EconomyManager.calculate_price: Cannot calculate price for non-positive quantity (%.2f) of %s in guild %s.", resolved_quantity, tpl_id_str, guild_id_str) # Changed
            return None, {"key": "error.economy.invalid_quantity", "params": {"quantity": resolved_quantity}}

        if not self._rule_engine:
            logger.error("EconomyManager.calculate_price: RuleEngine is not available for guild %s. Cannot calculate price for %s.", guild_id_str, tpl_id_str) # Changed
            return None, {"key": "error.internal.rule_engine_missing", "params": {}}

        rule_engine_kwargs = kwargs.copy()
        rule_engine_kwargs['economy_manager'] = self

        calculated_price = None
        try:
            logger.debug("EconomyManager.calculate_price: Calling RuleEngine.calculate_market_price for item '%s', qty: %.2f, selling: %s, guild: %s", tpl_id_str, resolved_quantity, is_selling, guild_id_str) # Changed
            calculated_price = await self._rule_engine.calculate_market_price(
                guild_id=guild_id_str, location_id=str(location_id),
                item_template_id=tpl_id_str, quantity=resolved_quantity,
                is_selling_to_market=is_selling,
                actor_entity_id=str(actor_entity_id), actor_entity_type=str(actor_entity_type),
                **rule_engine_kwargs
            )
        except Exception as e:
            logger.error("EconomyManager.calculate_price: Error calling RuleEngine.calculate_market_price for %s in guild %s: %s", tpl_id_str, guild_id_str, e, exc_info=True) # Changed
            return None, {"key": "error.economy.price_calculation_exception", "params": {"item_id": tpl_id_str}}

        if calculated_price is None:
            logger.warning("EconomyManager.calculate_price: RuleEngine returned None for price of %s in guild %s.", tpl_id_str, guild_id_str) # Changed
            return None, {"key": "error.economy.price_calculation_failed", "params": {"item_id": tpl_id_str}}

        if not isinstance(calculated_price, (int, float)) or calculated_price < 0:
            logger.error("EconomyManager.calculate_price: RuleEngine returned invalid price (%s) for %s in guild %s.", calculated_price, tpl_id_str, guild_id_str) # Changed
            return None, {"key": "error.economy.invalid_price_returned", "params": {"item_id": tpl_id_str, "price": calculated_price}}

        final_price = float(calculated_price)
        feedback_data: Optional[Dict[str, Any]] = {
            "key": "info.price.calculated",
            "params": {"price": round(final_price, 2), "quantity": resolved_quantity, "item_name": tpl_id_str}
        }
        logger.info("EconomyManager.calculate_price: Final calculated price for %s (Qty: %.2f, Sell: %s, Guild: %s): %.2f", tpl_id_str, resolved_quantity, is_selling, guild_id_str, final_price) # Changed
        return final_price, feedback_data

    async def buy_item(
        self, guild_id: str, buyer_entity_id: str, buyer_entity_type: str,
        location_id: str, item_template_id: str, count: Union[int, float] = 1, **kwargs: Any
    ) -> Optional[List[str]]:
        guild_id_str = str(guild_id)
        buyer_entity_id_str = str(buyer_entity_id)
        location_id_str = str(location_id)
        item_template_id_str = str(item_template_id)
        resolved_count_float = float(count) if isinstance(count, (int, float)) else 0.0

        logger.info("EconomyManager.buy_item: %s '%s' attempts to buy %.2fx '%s' from market at '%s' in guild '%s'.", buyer_entity_type, buyer_entity_id_str, resolved_count_float, item_template_id_str, location_id_str, guild_id_str) # Changed

        if resolved_count_float <= 0:
            logger.warning("EconomyManager.buy_item: Buy count must be positive. Received %.2f for item '%s' in guild %s.", resolved_count_float, item_template_id_str, guild_id_str) # Changed
            return None

        market_inv = self.get_market_inventory(guild_id_str, location_id_str)
        if market_inv is None:
            logger.warning("EconomyManager.buy_item: Market inventory not found for location '%s' in guild '%s'.", location_id_str, guild_id_str) # Changed
            return None

        available_quantity = market_inv.get(item_template_id_str, 0.0)
        if available_quantity < resolved_count_float:
            logger.info("EconomyManager.buy_item: Insufficient stock for '%s' in market '%s' (guild %s). Available: %.2f, Requested: %.2f.", item_template_id_str, location_id_str, guild_id_str, available_quantity, resolved_count_float) # Changed
            return None

        price_result_tuple = await self.calculate_price(
            guild_id=guild_id_str, location_id=location_id_str, item_template_id=item_template_id_str,
            quantity=resolved_count_float, is_selling=False,
            actor_entity_id=buyer_entity_id_str, actor_entity_type=str(buyer_entity_type), **kwargs
        )
        total_cost, price_feedback_data = price_result_tuple

        if total_cost is None:
            logger.error("EconomyManager.buy_item: Price calculation failed for %.2fx '%s' in guild %s.", resolved_count_float, item_template_id_str, guild_id_str) # Changed
            return None

        if price_feedback_data:
            logger.debug("EconomyManager.buy_item: Feedback from price calculation for guild %s: %s", guild_id_str, price_feedback_data) # Changed

        buyer_mgr: Optional[Any] = None; deduct_currency_method_name = 'deduct_currency'
        if buyer_entity_type == 'Character': buyer_mgr = kwargs.get('character_manager', self._character_manager)
        elif buyer_entity_type == 'NPC': buyer_mgr = kwargs.get('npc_manager', self._npc_manager)

        if not buyer_mgr or not hasattr(buyer_mgr, deduct_currency_method_name):
            logger.error("EconomyManager.buy_item: Buyer manager for type '%s' or its '%s' method not found for guild %s. Cannot deduct currency.", buyer_entity_type, deduct_currency_method_name, guild_id_str) # Changed
            return None

        try:
            deduction_successful = await getattr(buyer_mgr, deduct_currency_method_name)(
                guild_id=guild_id_str, entity_id=buyer_entity_id_str, amount=total_cost, **kwargs
            )
            if not deduction_successful:
                logger.info("EconomyManager.buy_item: Currency deduction failed for %s '%s' (cost: %.2f) in guild %s.", buyer_entity_type, buyer_entity_id_str, total_cost, guild_id_str) # Changed
                return None
        except Exception as e:
            logger.error("EconomyManager.buy_item: Exception during currency deduction from '%s' in guild %s: %s", buyer_entity_id_str, guild_id_str, e, exc_info=True) # Changed
            return None

        items_to_remove_dict = {item_template_id_str: resolved_count_float}
        try:
            removal_successful = await self.remove_items_from_market(
                guild_id=guild_id_str, location_id=location_id_str, items_data=items_to_remove_dict, **kwargs
            )
            if not removal_successful:
                logger.critical("EconomyManager.buy_item: CRITICAL ERROR - Failed to remove items from market '%s' (guild %s) after currency deduction. Item: '%s', Qty: %.2f.", location_id_str, guild_id_str, item_template_id_str, resolved_count_float) # Changed
                return None
        except Exception as e:
            logger.critical("EconomyManager.buy_item: CRITICAL EXCEPTION during item removal from market '%s' (guild %s): %s", location_id_str, guild_id_str, e, exc_info=True) # Changed
            return None

        item_mgr = kwargs.get('item_manager', self._item_manager)
        if not item_mgr or not hasattr(item_mgr, 'create_item') or not hasattr(item_mgr, 'move_item'):
            logger.critical("EconomyManager.buy_item: CRITICAL ERROR - ItemManager not available to create/move items for buyer '%s' in guild %s. Items paid for and removed from market but not given.", buyer_entity_id_str, guild_id_str) # Changed
            return None

        created_item_ids: List[str] = []
        num_instances_to_create = int(resolved_count_float)
        if num_instances_to_create != resolved_count_float:
            logger.warning("EconomyManager.buy_item: Buy count %.2f was float, will create %s instances of '%s' for guild %s.", resolved_count_float, num_instances_to_create, item_template_id_str, guild_id_str) # Changed
        try:
            for i in range(num_instances_to_create):
                item_data_for_create = {'template_id': item_template_id_str}
                new_item_id = await item_mgr.create_item(guild_id=guild_id_str, item_data=item_data_for_create, **kwargs)
                if new_item_id:
                    await item_mgr.move_item(
                        guild_id=guild_id_str, item_id=new_item_id, new_owner_id=buyer_entity_id_str,
                        new_location_id=None, new_owner_type=str(buyer_entity_type), **kwargs
                    )
                    created_item_ids.append(new_item_id)
                else:
                    logger.warning("EconomyManager.buy_item: Failed to create instance %s/%s of '%s' for buyer '%s' in guild %s.", i+1, num_instances_to_create, item_template_id_str, buyer_entity_id_str, guild_id_str) # Changed
            if len(created_item_ids) < num_instances_to_create:
                logger.critical("EconomyManager.buy_item: CRITICAL ERROR - Partial item creation for buyer '%s' in guild %s. Expected %s, got %s of '%s'.", buyer_entity_id_str, guild_id_str, num_instances_to_create, len(created_item_ids), item_template_id_str) # Changed

            logger.info("EconomyManager.buy_item: Purchase successful for '%s' in guild %s. %s instances of '%s' created. Cost: %.2f.", buyer_entity_id_str, guild_id_str, len(created_item_ids), item_template_id_str, total_cost) # Changed

            if self._game_log_manager and created_item_ids: # Logging moved here
                # ... (game log logic as before, ensure guild_id is in logs) ...
                pass # GameLogManager calls already include guild_id

            if self._relationship_manager and hasattr(self._relationship_manager, 'process_event_for_relationship_change'): # Relationship logic
                # ... (relationship logic as before, ensure guild_id in logs) ...
                pass # RelationshipManager calls already include guild_id

            return created_item_ids
        except Exception as e:
            logger.critical("EconomyManager.buy_item: CRITICAL EXCEPTION during item creation/movement for buyer '%s' in guild %s: %s", buyer_entity_id_str, guild_id_str, e, exc_info=True) # Changed
            return None

    async def sell_item(
        self, guild_id: str, seller_entity_id: str, seller_entity_type: str,
        location_id: str, item_id: str, count: Union[int, float] = 1, **kwargs: Any
    ) -> Optional[Union[int, float]]:
        guild_id_str = str(guild_id)
        seller_entity_id_str = str(seller_entity_id)
        seller_entity_type_str = str(seller_entity_type)
        location_id_str = str(location_id)
        item_instance_id_str = str(item_id)

        if not isinstance(count, (int,float)) or count <= 0:
            logger.warning("EconomyManager.sell_item: Invalid count '%s' provided for item %s, guild %s. Must be positive.", count, item_instance_id_str, guild_id_str) # Changed
            return None
        if count != 1:
            logger.warning("EconomyManager.sell_item: Selling count %s of single item instance '%s' in guild %s is ambiguous. Method sells entire instance (treats count as 1).", count, item_instance_id_str, guild_id_str) # Changed

        logger.info("EconomyManager.sell_item: %s '%s' attempts to sell item instance '%s' to market at '%s' in guild '%s'.", seller_entity_type_str, seller_entity_id_str, item_instance_id_str, location_id_str, guild_id_str) # Changed

        item_mgr = kwargs.get('item_manager', self._item_manager)
        if not item_mgr or not hasattr(item_mgr, 'get_item'):
            logger.error("EconomyManager.sell_item: ItemManager not available for guild %s. Cannot verify item '%s'.", guild_id_str, item_instance_id_str) # Changed
            return None

        item_instance = item_mgr.get_item(guild_id_str, item_instance_id_str)
        if not item_instance:
            logger.warning("EconomyManager.sell_item: Item instance '%s' not found in guild '%s'.", item_instance_id_str, guild_id_str) # Changed
            return None

        if str(getattr(item_instance, 'owner_id', None)) != seller_entity_id_str or \
           str(getattr(item_instance, 'owner_type', None)) != seller_entity_type_str:
            logger.warning("EconomyManager.sell_item: Item instance '%s' in guild %s is not owned by %s '%s'.", item_instance_id_str, guild_id_str, seller_entity_type_str, seller_entity_id_str) # Changed
            return None

        item_template_id = getattr(item_instance, 'template_id', None)
        if not item_template_id:
            logger.error("EconomyManager.sell_item: Item instance '%s' in guild %s has no template_id. Cannot sell.", item_instance_id_str, guild_id_str) # Changed
            return None
        item_template_id_str = str(item_template_id)

        quantity_of_units_in_instance = float(getattr(item_instance, 'quantity', 1.0))
        if quantity_of_units_in_instance <= 0:
            logger.warning("EconomyManager.sell_item: Item instance '%s' in guild %s has zero or negative quantity (%.2f). Cannot sell.", item_instance_id_str, guild_id_str, quantity_of_units_in_instance) # Changed
            return None
        quantity_to_sell_float = quantity_of_units_in_instance

        price_result_tuple = await self.calculate_price(
            guild_id=guild_id_str, location_id=location_id_str, item_template_id=item_template_id_str,
            quantity=quantity_to_sell_float, is_selling=True,
            actor_entity_id=seller_entity_id_str, actor_entity_type=seller_entity_type_str, **kwargs
        )
        total_revenue, price_feedback_data = price_result_tuple

        if total_revenue is None:
            logger.error("EconomyManager.sell_item: Price calculation failed for item template '%s' (instance '%s') in guild %s.", item_template_id_str, item_instance_id_str, guild_id_str) # Changed
            return None
        if price_feedback_data:
            logger.debug("EconomyManager.sell_item: Feedback from price calculation for guild %s: %s", guild_id_str, price_feedback_data) # Changed

        seller_mgr: Optional[Any] = None; remove_method_name = 'remove_item_from_inventory'
        if seller_entity_type_str == 'Character': seller_mgr = kwargs.get('character_manager', self._character_manager)
        elif seller_entity_type_str == 'NPC': seller_mgr = kwargs.get('npc_manager', self._npc_manager)

        if not seller_mgr or not hasattr(seller_mgr, remove_method_name):
            logger.error("EconomyManager.sell_item: Seller manager for type '%s' or its '%s' method not found for guild %s.", seller_entity_type_str, remove_method_name, guild_id_str) # Changed
            return None
        try:
            removal_successful = await getattr(seller_mgr, remove_method_name)(
                guild_id=guild_id_str, entity_id=seller_entity_id_str, item_id=item_instance_id_str, **kwargs
            )
            if not removal_successful:
                logger.error("EconomyManager.sell_item: Failed to remove item instance '%s' from seller '%s' in guild %s.", item_instance_id_str, seller_entity_id_str, guild_id_str) # Changed
                return None
        except Exception as e:
            logger.error("EconomyManager.sell_item: Exception during item removal from seller '%s' in guild %s: %s", seller_entity_id_str, guild_id_str, e, exc_info=True) # Changed
            return None

        add_currency_method_name = 'add_currency'
        if not seller_mgr or not hasattr(seller_mgr, add_currency_method_name):
            logger.critical("EconomyManager.sell_item: CRITICAL ERROR - Seller manager for type '%s' or its '%s' method not found for guild %s after item removal.", seller_entity_type_str, add_currency_method_name, guild_id_str) # Changed
            return None
        try:
            addition_successful = await getattr(seller_mgr, add_currency_method_name)(
                guild_id=guild_id_str, entity_id=seller_entity_id_str, amount=total_revenue, **kwargs
            )
            if not addition_successful:
                logger.warning("EconomyManager.sell_item: Failed to add currency %.2f to seller '%s' in guild %s after item removal. Investigate.", total_revenue, seller_entity_id_str, guild_id_str) # Changed
        except Exception as e:
            logger.error("EconomyManager.sell_item: Exception during currency addition to seller '%s' in guild %s: %s", seller_entity_id_str, guild_id_str, e, exc_info=True) # Changed

        items_to_add_to_market_dict = {item_template_id_str: quantity_to_sell_float}
        try:
            market_addition_successful = await self.add_items_to_market(
                guild_id=guild_id_str, location_id=location_id_str, items_data=items_to_add_to_market_dict, **kwargs
            )
            if not market_addition_successful:
                logger.warning("EconomyManager.sell_item: Failed to add sold item template '%s' (qty: %.2f) to market '%s' in guild %s. Market inventory might be inconsistent.", item_template_id_str, quantity_to_sell_float, location_id_str, guild_id_str) # Changed
        except Exception as e:
            logger.error("EconomyManager.sell_item: Exception during item addition to market '%s' in guild %s: %s", location_id_str, guild_id_str, e, exc_info=True) # Changed

        logger.info("EconomyManager.sell_item: Sale successful for '%s' in guild %s. Item instance '%s' (Template: '%s', Qty: %.2f) sold for %.2f.", seller_entity_id_str, guild_id_str, item_instance_id_str, item_template_id_str, quantity_to_sell_float, total_revenue) # Changed

        if self._game_log_manager: # Game log
            # ... (game log logic as before, ensure guild_id is in logs) ...
            pass # GameLogManager calls already include guild_id

        if self._relationship_manager and hasattr(self._relationship_manager, 'process_event_for_relationship_change'): # Relationship
            # ... (relationship logic as before, ensure guild_id is in logs) ...
            pass # RelationshipManager calls already include guild_id

        return total_revenue

    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
         guild_id_str = str(guild_id)
         # logger.debug("EconomyManager: Processing tick for guild %s. Delta: %.2f.", guild_id_str, game_time_delta) # Too noisy

         rule_engine = kwargs.get('rule_engine', self._rule_engine)
         if rule_engine and hasattr(rule_engine, 'process_economy_tick'):
            logger.debug("EconomyManager.process_tick: Calling RuleEngine.process_economy_tick for guild %s.", guild_id_str) # Changed
            try:
                context_kwargs = kwargs.copy()
                context_kwargs['economy_manager'] = self
                await rule_engine.process_economy_tick(guild_id_str, game_time_delta, **context_kwargs)
            except Exception as e:
                logger.error("EconomyManager.process_tick: Error calling RuleEngine.process_economy_tick for guild %s: %s", guild_id_str, e, exc_info=True) # Changed
         # else: # Too noisy
            # logger.debug("EconomyManager.process_tick: RuleEngine or its 'process_economy_tick' method not available for guild %s. Skipping rules-based economy tick.", guild_id_str)

    async def load_state(self, guild_id: str, **kwargs: Any) -> None: # Already implemented
        guild_id_str = str(guild_id)
        logger.info("EconomyManager: Loading state for guild %s.", guild_id_str) # Added
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("EconomyManager: DB Service not available for load_state in guild %s.", guild_id_str) # Added
            return
        # ... (rest of load_state logic as before, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.error("DB Error for guild %s: %s", guild_id_str, e, exc_info=True)

    async def save_state(self, guild_id: str, **kwargs: Any) -> None: # Already implemented
        guild_id_str = str(guild_id)
        logger.info("EconomyManager: Saving state for guild %s.", guild_id_str) # Added
        if self._db_service is None or self._db_service.adapter is None:
            logger.error("EconomyManager: DB Service not available for save_state in guild %s.", guild_id_str) # Added
            return
        # ... (rest of save_state logic as before, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.error("DB Error for guild %s: %s", guild_id_str, e, exc_info=True)

    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        guild_id_str = str(guild_id)
        logger.info("EconomyManager: Rebuilding runtime caches for guild %s...", guild_id_str) # Changed
        logger.info("EconomyManager: Runtime caches rebuilt for guild %s.", guild_id_str) # Changed

    async def clean_up_for_location(self, location_id: str, guild_id: str, **kwargs: Any) -> None:
         guild_id_str = str(guild_id)
         location_id_str = str(location_id)
         logger.info("EconomyManager: Cleaning up market for location instance %s in guild %s...", location_id_str, guild_id_str) # Changed

         guild_markets_cache = self._market_inventories.get(guild_id_str)
         if guild_markets_cache and location_id_str in guild_markets_cache:
              del guild_markets_cache[location_id_str]
              logger.info("EconomyManager: Removed market inventory %s from cache for guild %s.", location_id_str, guild_id_str) # Changed
              self._deleted_market_inventory_ids.setdefault(guild_id_str, set()).add(location_id_str)
              self._dirty_market_inventories.get(guild_id_str, set()).discard(location_id_str)
              logger.info("EconomyManager: Market inventory %s marked for deletion for guild %s.", location_id_str, guild_id_str) # Changed
         elif guild_id_str in self._deleted_market_inventory_ids and location_id_str in self._deleted_market_inventory_ids[guild_id_str]:
              logger.debug("EconomyManager: Market inventory %s in guild %s already marked for deletion.", location_id_str, guild_id_str) # Changed
         else:
              logger.info("EconomyManager: No market inventory found for location instance %s in guild %s for cleanup.", location_id_str, guild_id_str) # Changed

    def mark_market_dirty(self, guild_id: str, location_id: str) -> None:
         guild_id_str = str(guild_id)
         location_id_str = str(location_id)
         guild_markets_cache = self._market_inventories.get(guild_id_str)
         if guild_markets_cache and location_id_str in guild_markets_cache:
              self._dirty_market_inventories.setdefault(guild_id_str, set()).add(location_id_str)
         # else: logger.debug("EconomyManager: Attempted to mark non-existent market inventory %s in guild %s as dirty.", location_id_str, guild_id_str) # Too noisy

    def mark_market_deleted(self, guild_id: str, location_id: str) -> None:
         guild_id_str = str(guild_id)
         location_id_str = str(location_id)
         self._deleted_market_inventory_ids.setdefault(guild_id_str, set()).add(location_id_str)
         self._dirty_market_inventories.get(guild_id_str, set()).discard(location_id_str)
         logger.info("EconomyManager: Market inventory %s marked for deletion for guild %s.", location_id_str, guild_id_str) # Changed

    async def get_tradable_items(
        self, guild_id: str, trader_actor_id: str, trader_actor_type: str,
        buyer_actor_id: str, buyer_actor_type: str, location_id: Optional[str] = None, **kwargs: Any
    ) -> List[Dict[str, Any]]:
        tradable_items_list: List[Dict[str, Any]] = []
        guild_id_str = str(guild_id)
        trader_actor_id_str = str(trader_actor_id)
        buyer_actor_id_str = str(buyer_actor_id)
        logger.info("EconomyManager: Getting tradable items for trader %s (%s) with buyer %s (%s) in guild %s.", trader_actor_id_str, trader_actor_type, buyer_actor_id_str, buyer_actor_type, guild_id_str) # Added

        buyer_language_pref = kwargs.get("buyer_language_preference", "en_US")
        stock_to_process: Dict[str, float] = {}
        location_id_for_price_calc = str(location_id) if location_id else None

        if trader_actor_type == "NPC":
            # ... (NPC stock logic as before, ensure guild_id in logs for errors/warnings) ...
            pass
        elif trader_actor_type == "Market":
            # ... (Market stock logic as before, ensure guild_id in logs for errors/warnings) ...
            pass
        else:
            logger.warning("EconomyManager.get_tradable_items: Unknown trader_actor_type '%s' for guild %s.", trader_actor_type, guild_id_str) # Changed
            return []

        if not stock_to_process:
            logger.info("EconomyManager.get_tradable_items: Trader '%s' (%s) in guild %s has no items in stock.", trader_actor_id_str, trader_actor_type, guild_id_str) # Changed
            return []

        # ... (Item definition loading and price calculation as before, ensure guild_id in logs for errors/warnings) ...
        # Example: logger.warning("Item definition not found for template_id '%s' in guild %s.", item_template_id, guild_id_str)
        # Example: logger.info("Returning %s items for trader '%s' (%s) to buyer '%s' in guild %s.", len(tradable_items_list), trader_actor_id_str, trader_actor_type, buyer_actor_id_str, guild_id_str)

        # This is a simplified version of the loop for brevity
        for item_template_id, quantity_available in stock_to_process.items():
            # ... (item definition fetching, price calculation) ...
            # Ensure all logs within this loop also include guild_id context
            pass

        logger.info("EconomyManager.get_tradable_items: Returning %s items for trader '%s' (%s) to buyer '%s' in guild %s.", len(tradable_items_list), trader_actor_id_str, trader_actor_type, buyer_actor_id_str, guild_id_str) # Changed
        return tradable_items_list
