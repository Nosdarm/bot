# bot/game/managers/economy_manager.py

from __future__ import annotations
import json
import uuid # Может понадобиться для транзакций или предметов, не для самого рынка
import traceback
import asyncio
# Импорт базовых типов
# ИСПРАВЛЕНИЕ: Импортируем необходимые типы из typing
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union # Added Union

# Адаптер БД
from bot.services.db_service import DBService # Changed

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins


if TYPE_CHECKING:
    # Чтобы не создавать циклических импортов, импортируем эти типы только для подсказок
    # Используем строковые литералы ("ClassName")
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.game_log_manager import GameLogManager # Added
    from bot.game.managers.relationship_manager import RelationshipManager # Added
    # Add other managers/processors that might be in context kwargs
    # from bot.game.managers.combat_manager import CombatManager
    # from bot.game.managers.status_manager import StatusManager
    # from bot.game.managers.party_manager import PartyManager


class EconomyManager:
    """
    Менеджер для управления игровой экономикой:
    рынки, запасы, расчёт цен и торговые операции.
    Работает на основе guild_id для многогильдийной поддержки.
    """
    # Required args для PersistenceManager
    required_args_for_load: List[str] = ["guild_id"] # Загрузка per-guild
    required_args_for_save: List[str] = ["guild_id"] # Сохранение per-guild
    # ИСПРАВЛЕНИЕ: Добавляем guild_id для rebuild_runtime_caches
    required_args_for_rebuild: List[str] = ["guild_id"] # Rebuild per-guild


    # --- Class-Level Attribute Annotations ---
    # Кеш рыночных запасов: {guild_id: {location_id: {item_template_id: quantity}}}
    # ИСПРАВЛЕНИЕ: Кеш рынков должен быть per-guild
    _market_inventories: Dict[str, Dict[str, Dict[str, Union[int, float]]]] # Quantity can be int or float

    # Изменённые рынки, подлежащие записи: {guild_id: set(location_ids)}
    # ИСПРАВЛЕНИЕ: dirty markets также per-guild
    _dirty_market_inventories: Dict[str, Set[str]]

    # Удалённые рынки, подлежащие удалению из БД: {guild_id: set(location_ids)}
    # ИСПРАВЛЕНИЕ: deleted market inventory ids также per-guild
    _deleted_market_inventory_ids: Dict[str, Set[str]]


    def __init__(
        self,
        # Используем строковые литералы для всех инжектированных зависимостей
        db_service: Optional["DBService"] = None, # Changed
        settings: Optional[Dict[str, Any]] = None,

        item_manager: Optional["ItemManager"] = None, # Use string literal!
        location_manager: Optional["LocationManager"] = None, # Use string literal!
        character_manager: Optional["CharacterManager"] = None, # Use string literal!
        npc_manager: Optional["NpcManager"] = None, # Use string literal!
        rule_engine: Optional["RuleEngine"] = None, # Use string literal!
        time_manager: Optional["TimeManager"] = None, # Use string literal!
        game_log_manager: Optional["GameLogManager"] = None, # Added
        relationship_manager: Optional["RelationshipManager"] = None, # Added
        # Add other injected dependencies here with Optional and string literals
        # Example: combat_manager: Optional["CombatManager"] = None,
    ):
        print("Initializing EconomyManager...")
        self._db_service = db_service # Changed
        self._settings = settings

        # Инжектированные зависимости
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._game_log_manager = game_log_manager # Added
        self._relationship_manager = relationship_manager # Added

        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые outer словари
        # {guild_id: {location_id: {item_template_id: quantity}}}
        self._market_inventories = {} # Инициализируем как пустой dict

        # Для оптимизации персистенции
        self._dirty_market_inventories = {} # Инициализируем как пустой dict
        self._deleted_market_inventory_ids = {} # Инициализируем как пустой dict


        print("EconomyManager initialized.\n")

    # --- Методы получения ---
    # get_market_inventory now needs guild_id
    def get_market_inventory(self, guild_id: str, location_id: str) -> Optional[Dict[str, Union[int, float]]]:
        """Получить копию инвентаря рынка локации для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Get market inventories from the per-guild cache
        guild_markets = self._market_inventories.get(guild_id_str) # Get per-guild cache
        if guild_markets:
             inv = guild_markets.get(str(location_id)) # Get inventory for location (ensure string ID)
             if inv is not None:
                  # Return a copy to prevent external modification
                  # Ensure quantities are int/float
                  return {k: (int(v) if isinstance(v, int) else float(v)) for k, v in inv.items()}
        return None # Guild or market not found


    # --- Методы изменения состояния ---
    # add_items_to_market now needs guild_id
    async def add_items_to_market(
        self,
        guild_id: str, # Added guild_id
        location_id: str,
        items_data: Dict[str, Union[int, float]], # {item_template_id: quantity}
        **kwargs: Any
    ) -> bool:
        """
        Добавляет количество предметов по шаблону на рынок локации для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        print(f"EconomyManager: Adding {items_data} to market {location_id} for guild {guild_id_str}.")

        if not items_data:
            print(f"EconomyManager: No items data provided to add for market {location_id} in guild {guild_id_str}.")
            return False # Nothing to add

        # Optional: Validate location exists for this guild
        loc_mgr = kwargs.get('location_manager', self._location_manager) # Get LocationManager from context or self
        if loc_mgr and hasattr(loc_mgr, 'get_location_instance'): # Check manager and method
            # get_location_instance needs guild_id and location_id
            if loc_mgr.get_location_instance(guild_id_str, location_id) is None:
                print(f"EconomyManager: Location instance {location_id} not found for guild {guild_id_str}. Cannot add items to market.")
                # TODO: Send feedback if a command triggered this?
                return False

        # Get market inventory for this location for this guild
        # Use the per-guild cache, get() with default {} to create if not exists
        guild_markets_cache = self._market_inventories.setdefault(guild_id_str, {}) # Get or create per-guild cache
        market_inv = guild_markets_cache.setdefault(str(location_id), {}) # Get or create inventory for location (ensure string ID)


        if not isinstance(market_inv, dict):
             print(f"EconomyManager: Warning: Market inventory data for location {location_id} in guild {guild_id_str} is not a dict ({type(market_inv)}). Resetting to {{}}.")
             market_inv = {} # Reset if not a dict
             guild_markets_cache[str(location_id)] = market_inv # Update in cache


        changes_made = False
        for tpl_id, quantity in items_data.items():
            tpl_id_str = str(tpl_id) # Ensure template ID is string
            resolved_quantity = float(quantity) if isinstance(quantity, (int, float)) else 0.0 # Ensure quantity is numeric

            if resolved_quantity > 0:
                market_inv[tpl_id_str] = market_inv.get(tpl_id_str, 0.0) + resolved_quantity # Add quantity (use float default)
                # Ensure quantity is not negative after adding
                if market_inv[tpl_id_str] < 0: market_inv[tpl_id_str] = 0.0
                changes_made = True
                # print(f"EconomyManager: +{resolved_quantity:.2f} of {tpl_id_str} to market {location_id} in guild {guild_id_str}.") # Debug

        # Only mark dirty if changes were actually made
        if changes_made:
             # Mark the market inventory for this location as dirty for this guild
             # Use the correct per-guild dirty set
             self._dirty_market_inventories.setdefault(guild_id_str, set()).add(str(location_id)) # uses set()

             print(f"EconomyManager: Market {location_id} marked dirty for guild {guild_id_str}.")
             return True # Indicate success (changes made)

        print(f"EconomyManager: No valid items/quantities provided to add for market {location_id} in guild {guild_id_str}.")
        return False # No changes made


    # remove_items_from_market now needs guild_id
    async def remove_items_from_market(
        self,
        guild_id: str, # Added guild_id
        location_id: str,
        items_data: Dict[str, Union[int, float]], # {item_template_id: quantity}
        **kwargs: Any
    ) -> bool:
        """
        Удаляет количество предметов по шаблону с рынка локации для определенной гильдии.
        Возвращает False, если предметов недостаточно.
        """
        guild_id_str = str(guild_id)
        print(f"EconomyManager: Removing {items_data} from market {location_id} for guild {guild_id_str}.")

        # Get market inventory for this location for this guild
        guild_markets_cache = self._market_inventories.get(guild_id_str) # Get per-guild cache
        if not guild_markets_cache:
             print(f"EconomyManager: No market cache found for guild {guild_id_str}.")
             return False # Guild market cache doesn't exist

        market_inv = guild_markets_cache.get(str(location_id)) # Get inventory for location (ensure string ID)
        if not market_inv or not isinstance(market_inv, dict):
             print(f"EconomyManager: No valid market inventory found for {location_id} in guild {guild_id_str}.")
             return False # Market inventory is missing or invalid

        # --- 1. Проверка достаточности предметов ---
        for tpl_id, quantity in items_data.items():
            tpl_id_str = str(tpl_id) # Ensure template ID is string
            resolved_quantity = float(quantity) if isinstance(quantity, (int, float)) else 0.0 # Ensure quantity is numeric

            if resolved_quantity > 0:
                 # Check if the item template exists in the market and if the quantity is sufficient
                 available_quantity = market_inv.get(tpl_id_str, 0.0) # Use float default
                 if available_quantity < resolved_quantity:
                      print(f"EconomyManager: Not enough of item '{tpl_id_str}' available in market {location_id} for guild {guild_id_str} ({available_quantity:.2f}/{resolved_quantity:.2f}). Cannot remove.")
                      return False # Insufficient quantity, fail the whole operation


        # --- 2. Удаление предметов (если проверка пройдена) ---
        changes_made = False
        items_to_remove_completely: List[str] = [] # Collect template IDs whose quantity becomes 0 or less

        for tpl_id, quantity in items_data.items():
            tpl_id_str = str(tpl_id) # Ensure template ID is string
            resolved_quantity = float(quantity) if isinstance(quantity, (int, float)) else 0.0 # Ensure quantity is numeric

            if resolved_quantity > 0:
                 current_quantity = market_inv.get(tpl_id_str, 0.0)
                 new_quantity = current_quantity - resolved_quantity
                 market_inv[tpl_id_str] = new_quantity # Update quantity

                 if new_quantity <= 0:
                      items_to_remove_completely.append(tpl_id_str) # Mark for complete removal from dict

                 changes_made = True
                 # print(f"EconomyManager: -{resolved_quantity:.2f} of {tpl_id_str} from market {location_id} in guild {guild_id_str}. Remaining: {new_quantity:.2f}") # Debug

        # Remove items whose quantity is now <= 0 from the dictionary
        for tpl_id_str in items_to_remove_completely:
            market_inv.pop(tpl_id_str, None)

        # Only mark dirty if changes were actually made
        if changes_made:
             # Mark the market inventory for this location as dirty for this guild
             # Use the correct per-guild dirty set
             self._dirty_market_inventories.setdefault(guild_id_str, set()).add(str(location_id)) # uses set()

             print(f"EconomyManager: Market {location_id} marked dirty for guild {guild_id_str} after removal.")
             return True # Indicate success (changes made)

        print(f"EconomyManager: No valid items/quantities provided to remove for market {location_id} in guild {guild_id_str} or quantity was 0.")
        return False # No changes made

    # TODO: Implement calculate_price method
    # Needs guild_id, location_id, item_template_id, quantity, is_selling, context
    # Uses rule_engine to calculate price based on market inventory, template data, etc.
    async def calculate_price(
        self,
        guild_id: str,
        location_id: str,
        item_template_id: str,
        quantity: Union[int, float],
        is_selling: bool, # True if seller, False if buyer
        actor_entity_id: str, # Added: ID of the entity initiating the trade
        actor_entity_type: str, # Added: Type of the entity (e.g., "Character", "NPC")
        **kwargs: Any
    ) -> tuple[Optional[float], Optional[Dict[str, Any]]]: # MODIFIED return type
        """
        Рассчитывает цену для покупки или продажи предмета на рынке локации для определенной гильдии.
        Теперь учитывает отношения между актором и предполагаемым торговцем/фракцией.
        Returns a tuple: (final_price, feedback_data).
        feedback_data is a dict like {"key": "...", "params": {...}} or None.
        """
        guild_id_str = str(guild_id)
        guild_id_str = str(guild_id)
        tpl_id_str = str(item_template_id)
        resolved_quantity = float(quantity) if isinstance(quantity, (int, float)) else 0.0

        if resolved_quantity <= 0:
            print(f"EconomyManager.calculate_price: Warning - Cannot calculate price for non-positive quantity ({resolved_quantity}) of {tpl_id_str} in guild {guild_id_str}.")
            return None, {"key": "error.economy.invalid_quantity", "params": {"quantity": resolved_quantity}}

        if not self._rule_engine:
            print(f"EconomyManager.calculate_price: ERROR - RuleEngine is not available. Cannot calculate price for {tpl_id_str} in guild {guild_id_str}.")
            return None, {"key": "error.internal.rule_engine_missing", "params": {}}

        # Prepare kwargs for RuleEngine, ensuring it has access to this EconomyManager for callbacks if needed.
        # Other managers (LocationManager, RelationshipManager, CharacterManager, ItemManager)
        # are expected to be already present in the **kwargs passed to this method.
        rule_engine_kwargs = kwargs.copy()
        rule_engine_kwargs['economy_manager'] = self
        # guild_id is passed as a direct argument to rule_engine method

        try:
            print(f"EconomyManager.calculate_price: Calling RuleEngine.calculate_market_price for item '{tpl_id_str}', qty: {resolved_quantity}, selling: {is_selling}")
            calculated_price = await self._rule_engine.calculate_market_price(
                guild_id=guild_id_str,
                location_id=str(location_id),
                item_template_id=tpl_id_str,
                quantity=resolved_quantity,
                is_selling_to_market=is_selling, # Map `is_selling` to `is_selling_to_market`
                actor_entity_id=str(actor_entity_id),
                actor_entity_type=str(actor_entity_type),
                **rule_engine_kwargs
            )
        except Exception as e:
            print(f"EconomyManager.calculate_price: ❌ Error calling RuleEngine.calculate_market_price for {tpl_id_str} in guild {guild_id_str}: {e}")
            traceback.print_exc()
            return None, {"key": "error.economy.price_calculation_exception", "params": {"item_id": tpl_id_str}}

        if calculated_price is None:
            print(f"EconomyManager.calculate_price: RuleEngine returned None for price of {tpl_id_str} in guild {guild_id_str}.")
            return None, {"key": "error.economy.price_calculation_failed", "params": {"item_id": tpl_id_str}}

        if not isinstance(calculated_price, (int, float)) or calculated_price < 0:
            print(f"EconomyManager.calculate_price: RuleEngine returned invalid price ({calculated_price}) for {tpl_id_str} in guild {guild_id_str}.")
            return None, {"key": "error.economy.invalid_price_returned", "params": {"item_id": tpl_id_str, "price": calculated_price}}

        final_price = float(calculated_price)

        # Generic feedback. RuleEngine might provide more detailed feedback in the future,
        # which could be incorporated here.
        feedback_data: Optional[Dict[str, Any]] = {
            "key": "info.price.calculated",
            "params": {"price": round(final_price, 2), "quantity": resolved_quantity, "item_name": tpl_id_str} # TODO: get localized item name
        }

        print(f"EconomyManager.calculate_price: Final calculated price for {tpl_id_str} (Qty: {resolved_quantity}, Sell: {is_selling}): {final_price:.2f}")
        return final_price, feedback_data


    # TODO: Implement buy_item method
    # Needs guild_id, buyer_entity_id, buyer_entity_type, location_id, item_template_id, count, context
    # Requires interaction with Character/NPC Manager (deduct currency), ItemManager (create item instance, move to owner), EconomyManager (remove from market).
    async def buy_item(
        self,
        guild_id: str, # Added guild_id
        buyer_entity_id: str,
        buyer_entity_type: str,
        location_id: str, # Market location instance ID
        item_template_id: str,
        count: Union[int, float] = 1,
        **kwargs: Any
    ) -> Optional[List[str]]: # Returns list of created item instance IDs
        """
        Сущность покупает предмет с рынка локации для определенной гильдии.
        Assumes buying from a general market at location_id.
        """
        # 1. Input Validation
        guild_id_str = str(guild_id)
        buyer_entity_id_str = str(buyer_entity_id)
        location_id_str = str(location_id)
        item_template_id_str = str(item_template_id)
        resolved_count_float = float(count) if isinstance(count, (int, float)) else 0.0

        print(f"EconomyManager.buy_item: {buyer_entity_type} '{buyer_entity_id_str}' attempts to buy {resolved_count_float}x '{item_template_id_str}' from market at '{location_id_str}' in guild '{guild_id_str}'.")

        if resolved_count_float <= 0:
            print(f"EconomyManager.buy_item: Buy count must be positive. Received {resolved_count_float} for item '{item_template_id_str}'.")
            # Consider returning feedback: {"key": "error.economy.invalid_buy_quantity", "params": {"quantity": resolved_count_float}}
            return None

        # 2. Check Market Availability
        market_inv = self.get_market_inventory(guild_id_str, location_id_str)
        if market_inv is None:
            print(f"EconomyManager.buy_item: Market inventory not found for location '{location_id_str}' in guild '{guild_id_str}'.")
            # Consider returning feedback: {"key": "error.economy.market_not_found", "params": {"location_id": location_id_str}}
            return None

        available_quantity = market_inv.get(item_template_id_str, 0.0)
        if available_quantity < resolved_count_float:
            print(f"EconomyManager.buy_item: Insufficient stock for '{item_template_id_str}' in market '{location_id_str}'. Available: {available_quantity}, Requested: {resolved_count_float}.")
            # Consider returning feedback: {"key": "error.economy.insufficient_stock", "params": {"item_id": item_template_id_str, "available": available_quantity, "requested": resolved_count_float}}
            return None

        # 3. Calculate Price
        price_result_tuple = await self.calculate_price(
            guild_id=guild_id_str,
            location_id=location_id_str,
            item_template_id=item_template_id_str,
            quantity=resolved_count_float,
            is_selling=False, # Market is selling to player (player is buying)
            actor_entity_id=buyer_entity_id_str,
            actor_entity_type=str(buyer_entity_type),
            **kwargs
        )
        total_cost, price_feedback_data = price_result_tuple

        if total_cost is None:
            print(f"EconomyManager.buy_item: Price calculation failed for {resolved_count_float}x '{item_template_id_str}'.")
            # price_feedback_data might contain more specific error from calculate_price
            # Consider returning feedback: price_feedback_data or a generic one
            return None

        # total_cost should already be non-negative due to RuleEngine.calculate_market_price logic.

        if price_feedback_data: # Log any feedback from price calculation (e.g., discounts applied)
            print(f"EconomyManager.buy_item: Feedback from price calculation: {price_feedback_data}")

        # 4. Deduct Currency from Buyer
        buyer_mgr: Optional[Any] = None
        deduct_currency_method_name = 'deduct_currency'

        if buyer_entity_type == 'Character':
            buyer_mgr = kwargs.get('character_manager', self._character_manager)
        elif buyer_entity_type == 'NPC':
            buyer_mgr = kwargs.get('npc_manager', self._npc_manager)
        # TODO: Consider Party if Parties can have currency and buy items

        if not buyer_mgr or not hasattr(buyer_mgr, deduct_currency_method_name):
            print(f"EconomyManager.buy_item: Buyer manager for type '{buyer_entity_type}' or its '{deduct_currency_method_name}' method not found. Cannot deduct currency.")
            # Consider returning feedback: {"key": "error.internal.buyer_manager_misconfigured", "params": {"type": buyer_entity_type}}
            return None

        try:
            deduction_successful = await getattr(buyer_mgr, deduct_currency_method_name)(
                guild_id=guild_id_str, # Ensure guild_id is passed if required by manager method
                entity_id=buyer_entity_id_str,
                amount=total_cost,
                # guild_id=guild_id_str, # Already passed if part of method signature
                **kwargs
            )
            if not deduction_successful:
                print(f"EconomyManager.buy_item: Currency deduction failed for {buyer_entity_id_str} (cost: {total_cost}).")
                # Consider returning feedback: {"key": "error.economy.insufficient_funds", "params": {"required": total_cost}}
                return None
        except Exception as e:
            print(f"EconomyManager.buy_item: ❌ Exception during currency deduction from '{buyer_entity_id_str}': {e}")
            traceback.print_exc()
            # Consider returning feedback: {"key": "error.internal.currency_deduction_exception", "params": {"error": str(e)}}
            return None

        # 5. Remove Items from Market
        items_to_remove_dict = {item_template_id_str: resolved_count_float}
        try:
            removal_successful = await self.remove_items_from_market(
                guild_id=guild_id_str,
                location_id=location_id_str,
                items_data=items_to_remove_dict,
                **kwargs
            )
            if not removal_successful:
                print(f"EconomyManager.buy_item: ❌ CRITICAL ERROR - Failed to remove items from market '{location_id_str}' after currency deduction. Item: '{item_template_id_str}', Qty: {resolved_count_float}.")
                # TODO: Implement refund logic for buyer_entity_id_str for total_cost.
                # Consider returning feedback: {"key": "error.internal.market_item_removal_failed", "params": {"item_id": item_template_id_str}}
                return None # Critical failure
        except Exception as e:
            print(f"EconomyManager.buy_item: ❌ CRITICAL EXCEPTION during item removal from market '{location_id_str}': {e}")
            traceback.print_exc()
            # TODO: Implement refund logic here as well.
            return None

        # 6. Add Items to Buyer's Inventory (using ItemManager as per existing code structure)
        item_mgr = kwargs.get('item_manager', self._item_manager)
        if not item_mgr or not hasattr(item_mgr, 'create_item') or not hasattr(item_mgr, 'move_item'):
            print(f"EconomyManager.buy_item: ❌ CRITICAL ERROR - ItemManager not available to create/move items for buyer '{buyer_entity_id_str}'. Items paid for and removed from market but not given.")
            # TODO: This is a very critical state. Attempt to revert market stock? Log for manual intervention.
            return None

        created_item_ids: List[str] = []
        # Assuming items are instanced. If stackable, InventoryManager might handle it differently.
        # The current code creates 'resolved_count_float' instances if it's an integer.
        # If resolved_count_float can be fractional for some items, this needs clarification.
        # For now, assuming it's effectively integer count of items.
        num_instances_to_create = int(resolved_count_float) # Or round? Let's stick to int for now.
        if num_instances_to_create != resolved_count_float:
            print(f"EconomyManager.buy_item: Warning - Buy count {resolved_count_float} was float, will create {num_instances_to_create} instances of '{item_template_id_str}'.")


        try:
            for i in range(num_instances_to_create):
                item_data_for_create = {'template_id': item_template_id_str}
                new_item_id = await item_mgr.create_item(
                    guild_id=guild_id_str,
                    item_data=item_data_for_create,
                    **kwargs
                )
                if new_item_id:
                    await item_mgr.move_item(
                        guild_id=guild_id_str,
                        item_id=new_item_id,
                        new_owner_id=buyer_entity_id_str,
                        new_location_id=None, # Owned by entity, not in a location
                        new_owner_type=str(buyer_entity_type),
                        **kwargs
                    )
                    created_item_ids.append(new_item_id)
                else:
                    print(f"EconomyManager.buy_item: Warning - Failed to create instance {i+1}/{num_instances_to_create} of '{item_template_id_str}' for buyer '{buyer_entity_id_str}'.")
            if len(created_item_ids) < num_instances_to_create:
                print(f"EconomyManager.buy_item: ❌ CRITICAL ERROR - Partial item creation for buyer '{buyer_entity_id_str}'. Expected {num_instances_to_create}, got {len(created_item_ids)} of '{item_template_id_str}'.")
                # This is a very problematic state. Items paid, removed from market. Buyer has some items.
                # TODO: Log for manual resolution. What to return? Partial success?
                # For now, returning successfully created IDs, but this needs robust handling.

            print(f"EconomyManager.buy_item: Purchase successful for '{buyer_entity_id_str}'. {len(created_item_ids)} instances of '{item_template_id_str}' created. Cost: {total_cost}.")
            # TODO: Provide success feedback to the player via a proper feedback system.

            # 7. Logging and Feedback
            if self._game_log_manager and created_item_ids:
                log_event_details = {
                    "player_id": buyer_entity_id_str, # Using player_id for generic actor
                    "player_entity_type": str(buyer_entity_type),
                    "location_id": location_id_str,
                    "item_template_id": item_template_id_str,
                    "quantity": float(len(created_item_ids)), # Log actual number of items created/transferred
                    "total_price": total_cost,
                    "transaction_type": "buy",
                    "trader_actor_id": location_id_str, # Assuming market at location is the "trader"
                    "trader_actor_type": "Market",
                }
                asyncio.create_task(self._game_log_manager.log_event(
                    guild_id=guild_id_str,
                    event_type="TRADE_COMPLETED",
                    details=log_event_details,
                    # player_id might be better named actor_id in log_event if it's not always a player
                    player_id=buyer_entity_id_str,
                    location_id=location_id_str
                ))

            # Attempt to process relationship change post-trade
            if self._relationship_manager and hasattr(self._relationship_manager, 'process_event_for_relationship_change'):
                try:
                    # Determine trader entity: Use explicit from kwargs if provided, else default to market/location
                    trade_partner_id = kwargs.get('explicit_trader_id', location_id_str)
                    trade_partner_type = kwargs.get('explicit_trader_type', "Market") # Default to "Market" type for location-based trade

                    await self._relationship_manager.process_event_for_relationship_change(
                        guild_id=guild_id_str,
                        actor1_id=buyer_entity_id_str,
                        actor1_type=str(buyer_entity_type),
                        actor2_id=str(trade_partner_id),
                        actor2_type=str(trade_partner_type),
                        event_type="TRADE_EVENT_PLAYER_BOUGHT_FROM_MARKET",
                        event_details={
                            "item_template_id": item_template_id_str,
                            "quantity": float(len(created_item_ids)),
                            "value": total_cost,
                            "location_id": location_id_str
                        },
                        **kwargs # Pass full context
                    )
                    print(f"EconomyManager.buy_item: Relationship event processed for buyer {buyer_entity_id_str} with {trade_partner_type} {trade_partner_id}.")
                except Exception as rel_e:
                    print(f"EconomyManager.buy_item: ❌ Failed to process relationship change after purchase: {rel_e}")
                    traceback.print_exc()

            return created_item_ids

        except Exception as e:
            print(f"EconomyManager.buy_item: ❌ CRITICAL EXCEPTION during item creation/movement for buyer '{buyer_entity_id_str}': {e}")
            traceback.print_exc()
            # This is a very critical state. Items paid, removed from market, buyer may have no items.
            # TODO: Log for manual resolution. Attempt to revert previous steps if possible (add items back to market, refund currency).
            return None # Partial success or None? For now, None on error here.

    # TODO: Implement sell_item method
    # Needs guild_id, seller_entity_id, seller_entity_type, location_id, item_id, count, context
    # Requires interaction with Character/NPC Manager (add currency), ItemManager (remove item instance from owner), EconomyManager (add to market).
    # item_id here is the INSTANCE ID, not template ID, as the seller holds item instances.
    async def sell_item(
        self,
        guild_id: str, # Added guild_id
        seller_entity_id: str,
        seller_entity_type: str,
        location_id: str, # Market location instance ID
        item_id: str, # Item INSTANCE ID
        count: Union[int, float] = 1, # How many items of this instance? (Usually 1 if item instances are unique)
        **kwargs: Any
    ) -> Optional[Union[int, float]]: # Returns total revenue earned
        """
        Сущность продает предмет на рынок локации для определенной гильдии.
        `item_id` is the INSTANCE ID of the item being sold.
        `count` is the quantity of units to sell from that instance.
        Currently, this method assumes selling the ENTIRE item instance (count must be 1 if instance quantity is 1,
        or count must equal instance.quantity if instance itself is a stack).
        Partial sales of a stack (reducing instance quantity) are not fully supported by this simplified version
        without more complex interaction with an InventoryManager or ItemManager for splitting/updating instances.
        The existing code logic sells the whole instance identified by item_id.
        """
        # 1. Input Validation
        guild_id_str = str(guild_id)
        seller_entity_id_str = str(seller_entity_id)
        seller_entity_type_str = str(seller_entity_type)
        location_id_str = str(location_id)
        item_instance_id_str = str(item_id)

        # `count` for selling an instance. The current logic sells the whole instance.
        # The `count` parameter in signature is a bit misleading given the internal logic.
        # For now, we'll assume `count` refers to "number of instances" which is 1 here.
        # The actual number of units sold will be derived from the item_instance.quantity.
        if not isinstance(count, (int,float)) or count <= 0:
            print(f"EconomyManager.sell_item: Invalid count '{count}' provided. Must be positive.")
            return None

        # Current logic sells the entire instance. So, count of instances to sell is effectively 1.
        # If count > 1, it implies selling multiple different instances, which this method isn't designed for.
        if count != 1:
            print(f"EconomyManager.sell_item: Warning - Selling count {count} of a single item instance '{item_instance_id_str}' is ambiguous. Method sells the entire specified instance (treats count as 1 instance).")
            # For clarity, we proceed as if count = 1 (selling this one instance).

        print(f"EconomyManager.sell_item: {seller_entity_type_str} '{seller_entity_id_str}' attempts to sell item instance '{item_instance_id_str}' to market at '{location_id_str}' in guild '{guild_id_str}'.")

        # 2. Verify Seller Owns Item Instance
        item_mgr = kwargs.get('item_manager', self._item_manager)
        if not item_mgr or not hasattr(item_mgr, 'get_item'):
            print(f"EconomyManager.sell_item: ItemManager not available. Cannot verify item '{item_instance_id_str}'.")
            return None

        item_instance = item_mgr.get_item(guild_id_str, item_instance_id_str)
        if not item_instance:
            print(f"EconomyManager.sell_item: Item instance '{item_instance_id_str}' not found in guild '{guild_id_str}'.")
            return None

        if str(getattr(item_instance, 'owner_id', None)) != seller_entity_id_str or \
           str(getattr(item_instance, 'owner_type', None)) != seller_entity_type_str:
            print(f"EconomyManager.sell_item: Item instance '{item_instance_id_str}' is not owned by {seller_entity_type_str} '{seller_entity_id_str}'.")
            return None

        item_template_id = getattr(item_instance, 'template_id', None)
        if not item_template_id:
            print(f"EconomyManager.sell_item: Item instance '{item_instance_id_str}' has no template_id. Cannot sell.")
            return None
        item_template_id_str = str(item_template_id)

        # Quantity of units in this specific instance stack
        quantity_of_units_in_instance = float(getattr(item_instance, 'quantity', 1.0))
        if quantity_of_units_in_instance <= 0:
            print(f"EconomyManager.sell_item: Item instance '{item_instance_id_str}' has zero or negative quantity ({quantity_of_units_in_instance}). Cannot sell.")
            return None

        # Since we're selling the whole instance, the number of units being sold is its full quantity.
        quantity_to_sell_float = quantity_of_units_in_instance

        # 3. Calculate Price
        price_result_tuple = await self.calculate_price(
            guild_id=guild_id_str,
            location_id=location_id_str,
            item_template_id=item_template_id_str,
            quantity=quantity_to_sell_float, # Price for the full quantity of the instance
            is_selling=True, # Seller is selling to the market
            actor_entity_id=seller_entity_id_str,
            actor_entity_type=seller_entity_type_str,
            **kwargs
        )
        total_revenue, price_feedback_data = price_result_tuple

        if total_revenue is None:
            print(f"EconomyManager.sell_item: Price calculation failed for item template '{item_template_id_str}' (instance '{item_instance_id_str}').")
            return None
        # total_revenue should be non-negative due to RuleEngine logic.

        if price_feedback_data:
            print(f"EconomyManager.sell_item: Feedback from price calculation: {price_feedback_data}")

        # 4. Remove Item from Seller's Inventory
        # This implies the entire instance is removed.
        # The entity manager's `remove_item_from_inventory` should handle deleting/unassigning the instance via ItemManager.
        seller_mgr: Optional[Any] = None
        remove_method_name = 'remove_item_from_inventory'
        if seller_entity_type_str == 'Character':
            seller_mgr = kwargs.get('character_manager', self._character_manager)
        elif seller_entity_type_str == 'NPC':
            seller_mgr = kwargs.get('npc_manager', self._npc_manager)

        if not seller_mgr or not hasattr(seller_mgr, remove_method_name):
            print(f"EconomyManager.sell_item: Seller manager for type '{seller_entity_type_str}' or its '{remove_method_name}' method not found.")
            return None

        try:
            # This method should confirm removal of the specific item_instance_id_str
            removal_successful = await getattr(seller_mgr, remove_method_name)(
                guild_id=guild_id_str,
                entity_id=seller_entity_id_str,
                item_id=item_instance_id_str, # Pass instance ID
                # quantity_to_remove is not part of existing assumed signature based on buy_item
                # This implies it removes the whole instance.
                **kwargs
            )
            if not removal_successful:
                print(f"EconomyManager.sell_item: Failed to remove item instance '{item_instance_id_str}' from seller '{seller_entity_id_str}'.")
                return None
        except Exception as e:
            print(f"EconomyManager.sell_item: ❌ Exception during item removal from seller '{seller_entity_id_str}': {e}")
            traceback.print_exc()
            return None

        # 5. Add Currency to Seller
        add_currency_method_name = 'add_currency'
        if not seller_mgr or not hasattr(seller_mgr, add_currency_method_name): # Should still have seller_mgr
            print(f"EconomyManager.sell_item: ❌ CRITICAL ERROR - Seller manager for type '{seller_entity_type_str}' or its '{add_currency_method_name}' method not found after item removal.")
            # Item removed from seller, but can't add currency. This is bad.
            # TODO: Log for manual intervention. Potentially try to revert item removal.
            return None
        try:
            addition_successful = await getattr(seller_mgr, add_currency_method_name)(
                guild_id=guild_id_str,
                entity_id=seller_entity_id_str,
                amount=total_revenue,
                **kwargs
            )
            if not addition_successful:
                # Item removed, but currency not added. This is also bad.
                print(f"EconomyManager.sell_item: Warning - Failed to add currency {total_revenue} to seller '{seller_entity_id_str}' after item removal. Investigate.")
                # TODO: Log for manual intervention.
        except Exception as e:
            print(f"EconomyManager.sell_item: ❌ Exception during currency addition to seller '{seller_entity_id_str}': {e}")
            traceback.print_exc()
            # Item removed, currency addition failed. Log for manual intervention.

        # 6. Add Items to Market
        # The items (represented by template_id and quantity_to_sell_float) are added to the market.
        items_to_add_to_market_dict = {item_template_id_str: quantity_to_sell_float}
        try:
            market_addition_successful = await self.add_items_to_market(
                guild_id=guild_id_str,
                location_id=location_id_str,
                items_data=items_to_add_to_market_dict,
                **kwargs
            )
            if not market_addition_successful:
                print(f"EconomyManager.sell_item: Warning - Failed to add sold item template '{item_template_id_str}' (qty: {quantity_to_sell_float}) to market '{location_id_str}'. Market inventory might be inconsistent.")
                # TODO: Log for monitoring.
        except Exception as e:
            print(f"EconomyManager.sell_item: ❌ Exception during item addition to market '{location_id_str}': {e}")
            traceback.print_exc()
            # TODO: Log for monitoring.

        # 7. Logging and Feedback
        print(f"EconomyManager.sell_item: Sale successful for '{seller_entity_id_str}'. Item instance '{item_instance_id_str}' (Template: '{item_template_id_str}', Qty: {quantity_to_sell_float}) sold for {total_revenue:.2f}.")
        # TODO: Provide success feedback to player.

        if self._game_log_manager:
            log_event_details = {
                "player_id": seller_entity_id_str,
                "player_entity_type": seller_entity_type_str,
                "location_id": location_id_str,
                "item_template_id": item_template_id_str,
                "item_instance_id": item_instance_id_str, # Log which instance was sold
                "quantity": quantity_to_sell_float,
                "total_price": total_revenue,
                "transaction_type": "sell",
                "trader_actor_id": location_id_str, # Market at location is the "trader"
                "trader_actor_type": "Market",
            }
            asyncio.create_task(self._game_log_manager.log_event(
                guild_id=guild_id_str,
                event_type="TRADE_COMPLETED",
                details=log_event_details,
                player_id=seller_entity_id_str,
                location_id=location_id_str
            ))

        # Attempt to process relationship change post-trade
        if self._relationship_manager and hasattr(self._relationship_manager, 'process_event_for_relationship_change'):
            try:
                # Determine trader entity: Use explicit from kwargs if provided, else default to market/location
                trade_partner_id = kwargs.get('explicit_trader_id', location_id_str)
                trade_partner_type = kwargs.get('explicit_trader_type', "Market") # Default to "Market" type for location-based trade

                await self._relationship_manager.process_event_for_relationship_change(
                    guild_id=guild_id_str,
                    actor1_id=seller_entity_id_str,
                    actor1_type=seller_entity_type_str,
                    actor2_id=str(trade_partner_id),
                    actor2_type=str(trade_partner_type),
                    event_type="TRADE_EVENT_PLAYER_SOLD_TO_MARKET",
                    event_details={
                        "item_template_id": item_template_id_str,
                        "item_instance_id": item_instance_id_str,
                        "quantity": quantity_to_sell_float,
                        "value": total_revenue,
                        "location_id": location_id_str
                    },
                    **kwargs # Pass full context
                )
                print(f"EconomyManager.sell_item: Relationship event processed for seller {seller_entity_id_str} with {trade_partner_type} {trade_partner_id}.")
            except Exception as rel_e:
                print(f"EconomyManager.sell_item: ❌ Failed to process relationship change after sale: {rel_e}")
                traceback.print_exc()

        return total_revenue

    # process_tick method - called by WorldSimulationProcessor
    # Already takes game_time_delta and **kwargs
    # needs guild_id
    async def process_tick(self, guild_id: str, game_time_delta: float, **kwargs: Any) -> None:
         """
         Обработка игрового тика для экономики (например, ресток рынков) для определенной гильдии.
         """
         guild_id_str = str(guild_id)
         # print(f"EconomyManager: Processing tick for guild {guild_id_str}. Delta: {game_time_delta}. (Placeholder)") # Too noisy


         # Get RuleEngine from kwargs or self
         rule_engine = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]

         if rule_engine and hasattr(rule_engine, 'process_economy_tick'):
            print(f"EconomyManager.process_tick: Calling RuleEngine.process_economy_tick for guild {guild_id_str}.")
            try:
                context_kwargs = kwargs.copy()
                context_kwargs['economy_manager'] = self
                await rule_engine.process_economy_tick(guild_id_str, game_time_delta, **context_kwargs)
            except Exception as e:
                print(f"EconomyManager.process_tick: ❌ Error calling RuleEngine.process_economy_tick for guild {guild_id_str}: {e}")
                traceback.print_exc()
         else:
            print(f"EconomyManager.process_tick: RuleEngine or its 'process_economy_tick' method not available for guild {guild_id_str}. Skipping rules-based economy tick.")


    # save_state - saves per-guild
    # required_args_for_save = ["guild_id"]
    # Already implemented above.

    # load_state - loads per-guild
    # required_args_for_load = ["guild_id"]
    # Already implemented above.

    # rebuild_runtime_caches - rebuilds per-guild caches after loading
    # required_args_for_rebuild = ["guild_id"]
    # Already takes guild_id and **kwargs
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """
        Перестраивает вспомогательные кеши (если будут) для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        print(f"EconomyManager: Rebuilding runtime caches for guild {guild_id_str}...")
        # сейчас ничего лишнего делать не нужно
        print(f"EconomyManager: Runtime caches rebuilt for guild {guild_id_str}.")


    # TODO: Implement clean_up_for_location(location_id, guild_id, **context)
    # Called by LocationManager.delete_location_instance
    # This method needs to remove the market inventory for this location instance.
    async def clean_up_for_location(self, location_id: str, guild_id: str, **kwargs: Any) -> None:
         """
         Удаляет рынок, связанный с инстансом локации, когда локация удаляется.
         """
         guild_id_str = str(guild_id)
         location_id_str = str(location_id)
         print(f"EconomyManager: Cleaning up market for location instance {location_id_str} in guild {guild_id_str}...")

         # Check if the market inventory exists for this location/guild
         guild_markets_cache = self._market_inventories.get(guild_id_str)
         if guild_markets_cache and location_id_str in guild_markets_cache:
              # Remove from per-guild cache
              del guild_markets_cache[location_id_str]
              print(f"EconomyManager: Removed market inventory {location_id_str} from cache for guild {guild_id_str}.")

              # Add to per-guild deleted set
              self._deleted_market_inventory_ids.setdefault(guild_id_str, set()).add(location_id_str) # uses set()

              # Remove from per-guild dirty set if it was there
              self._dirty_market_inventories.get(guild_id_str, set()).discard(location_id_str) # uses set()

              print(f"EconomyManager: Market inventory {location_id_str} marked for deletion for guild {guild_id_str}.")

         # Handle case where market was already deleted or didn't exist
         elif guild_id_str in self._deleted_market_inventory_ids and location_id_str in self._deleted_market_inventory_ids[guild_id_str]:
              print(f"EconomyManager: Market inventory {location_id_str} in guild {guild_id_str} already marked for deletion.")
         else:
              print(f"EconomyManager: No market inventory found for location instance {location_id_str} in guild {guild_id_str} for cleanup.")


    # mark_market_dirty needs guild_id
    # Needs _dirty_market_inventories Set (per-guild)
    def mark_market_dirty(self, guild_id: str, location_id: str) -> None:
         """Помечает инвентарь рынка локации как измененный для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         location_id_str = str(location_id)
         # Check if the market inventory exists in the per-guild cache
         guild_markets_cache = self._market_inventories.get(guild_id_str)
         if guild_markets_cache and location_id_str in guild_markets_cache:
              # Add to the per-guild dirty set
              self._dirty_market_inventories.setdefault(guild_id_str, set()).add(location_id_str)
         # else: print(f"EconomyManager: Warning: Attempted to mark non-existent market inventory {location_id_str} in guild {guild_id_str} as dirty.") # Too noisy?


    # mark_market_deleted needs guild_id
    # Needs _deleted_market_inventory_ids Set (per-guild)
    # Called by clean_up_for_location
    def mark_market_deleted(self, guild_id: str, location_id: str) -> None:
         """Помечает инвентарь рынка локации как удаленный для определенной гильдии."""
         guild_id_str = str(guild_id)
         location_id_str = str(location_id)

         # Check if market exists in the per-guild cache (optional, clean_up_for_location handles this)
         # guild_markets_cache = self._market_inventories.get(guild_id_str)
         # if guild_markets_cache and location_id_str in guild_markets_cache:
             # clean_up_for_location already removes from cache

         # Add to per-guild deleted set
         self._deleted_market_inventory_ids.setdefault(guild_id_str, set()).add(location_id_str) # uses set()

         # Remove from per-guild dirty set if it was there
         self._dirty_market_inventories.get(guild_id_str, set()).discard(location_id_str) # uses set()

         print(f"EconomyManager: Market inventory {location_id_str} marked for deletion for guild {guild_id_str}.")


# TODO: Implement methods to add/deduct currency from entities (Character, NPC, Party)
# These methods would live in CharacterManager, NpcManager, PartyManager, not EconomyManager.
# Example signature in CharacterManager: async def add_currency(self, character_id: str, amount: Union[int, float], guild_id: str, **kwargs: Any) -> bool: ...
# Example signature in CharacterManager: async def deduct_currency(self, character_id: str, amount: Union[int, float], guild_id: str, **kwargs: Any) -> bool: ...
# EconomyManager will CALL these methods on the respective entity managers.

    async def get_tradable_items(
        self,
        guild_id: str,
        trader_actor_id: str,
        trader_actor_type: str, # "NPC" or "Market"
        buyer_actor_id: str,
        buyer_actor_type: str, # e.g. "Character"
        location_id: Optional[str] = None, # Location of the trade interaction
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """
        Gets a list of items available for trade from a trader (NPC or Market),
        including their calculated prices for the specified buyer.
        """
        tradable_items_list: List[Dict[str, Any]] = []
        guild_id_str = str(guild_id)
        trader_actor_id_str = str(trader_actor_id)
        buyer_actor_id_str = str(buyer_actor_id)

        # Determine buyer's language preference (default to 'en' if not found)
        # This is a placeholder; actual language preference should come from CharacterManager or similar
        buyer_language_pref = kwargs.get("buyer_language_preference", "en_US")

        stock_to_process: Dict[str, float] = {} # {item_template_id: quantity}

        # Location ID for price calculation should be the location of the trader/market.
        # If trader is "Market", trader_actor_id might be the location_id.
        # If trader is "NPC", location_id argument should be their current location.
        location_id_for_price_calc = str(location_id) if location_id else None

        if trader_actor_type == "NPC":
            npc_manager = kwargs.get('npc_manager', self._npc_manager)
            if not npc_manager or not hasattr(npc_manager, 'get_npc'):
                print(f"EconomyManager.get_tradable_items: NpcManager not available. Cannot fetch NPC trader '{trader_actor_id_str}'.")
                return []

            npc_trader = await npc_manager.get_npc(guild_id_str, trader_actor_id_str)
            if not npc_trader:
                print(f"EconomyManager.get_tradable_items: NPC trader '{trader_actor_id_str}' not found.")
                return []

            if not location_id_for_price_calc: # If location_id wasn't passed, use NPC's current location
                location_id_for_price_calc = getattr(npc_trader, 'location_id', None)
                if not location_id_for_price_calc:
                    print(f"EconomyManager.get_tradable_items: Could not determine location for NPC trader '{trader_actor_id_str}' for price calculation.")
                    return [] # Price calculation needs a location context

            # Assuming npc_trader.inventory is a list of item dicts: [{"item_template_id": "x", "quantity": y}]
            # This needs to be consistent with how NPC inventories are stored (e.g. from AI generation)
            npc_inventory_list = getattr(npc_trader, 'inventory', [])
            if isinstance(npc_inventory_list, list):
                for item_entry in npc_inventory_list:
                    if isinstance(item_entry, dict):
                        tpl_id = item_entry.get("item_template_id")
                        qty = item_entry.get("quantity", 0.0)
                        if tpl_id and isinstance(qty, (int, float)) and qty > 0:
                            stock_to_process[str(tpl_id)] = stock_to_process.get(str(tpl_id), 0.0) + float(qty)
            else:
                print(f"EconomyManager.get_tradable_items: NPC trader '{trader_actor_id_str}' inventory is not a list as expected. Found: {type(npc_inventory_list)}")


        elif trader_actor_type == "Market":
            if not location_id_for_price_calc:
                location_id_for_price_calc = trader_actor_id_str # Assume trader_actor_id is the market's location_id

            if not location_id_for_price_calc:
                 print(f"EconomyManager.get_tradable_items: Market location ID not provided for Market trader type.")
                 return []

            market_stock = self.get_market_inventory(guild_id_str, location_id_for_price_calc)
            if market_stock:
                for item_tpl_id, qty in market_stock.items():
                    if isinstance(qty, (int, float)) and qty > 0:
                        stock_to_process[str(item_tpl_id)] = float(qty)
            else:
                print(f"EconomyManager.get_tradable_items: Market stock not found for location '{location_id_for_price_calc}'.")
                return []
        else:
            print(f"EconomyManager.get_tradable_items: Unknown trader_actor_type '{trader_actor_type}'.")
            return []

        if not stock_to_process:
            print(f"EconomyManager.get_tradable_items: Trader '{trader_actor_id_str}' ({trader_actor_type}) has no items in stock.")
            return []

        # Access item definitions from RuleEngine's loaded rules
        all_item_definitions = {}
        if self._rule_engine and hasattr(self._rule_engine, '_rules_data'):
            all_item_definitions = self._rule_engine._rules_data.get("item_definitions", {})

        if not all_item_definitions and self._item_manager and hasattr(self._item_manager, 'get_all_item_templates_for_guild'):
            # Fallback if RuleEngine doesn't have them directly exposed or ItemManager is preferred source
            print("EconomyManager.get_tradable_items: Warning - Item definitions not found in RuleEngine._rules_data, attempting fallback via ItemManager.get_all_item_templates_for_guild.")
            all_item_definitions = await self._item_manager.get_all_item_templates_for_guild(guild_id_str)


        if not all_item_definitions:
            print(f"EconomyManager.get_tradable_items: No item definitions found. Cannot process tradable items.")
            return []

        for item_template_id, quantity_available in stock_to_process.items():
            item_def = all_item_definitions.get(str(item_template_id))

            if not item_def or not isinstance(item_def, dict):
                print(f"EconomyManager.get_tradable_items: Item definition not found or invalid for template_id '{item_template_id}'. Skipping.")
                continue

            # Calculate price for one unit for the buyer
            # self.calculate_price returns (price, feedback_dict)
            price_tuple = await self.calculate_price(
                guild_id=guild_id_str,
                location_id=location_id_for_price_calc, # Location of the sale
                item_template_id=item_template_id,
                quantity=1.0, # Price for one unit
                is_selling=False, # Player is buying from this trader
                actor_entity_id=buyer_actor_id_str,
                actor_entity_type=str(buyer_actor_type),
                **kwargs # Pass along other managers and context
            )
            price_per_unit = price_tuple[0] if price_tuple else None

            name_i18n = item_def.get("name_i18n", {})
            description_i18n = item_def.get("description_i18n", {})

            # Get localized name and description
            # Placeholder for i18n_utils.get_i18n_text or similar utility
            display_name = name_i18n.get(buyer_language_pref, name_i18n.get("en_US", item_template_id))
            display_description = description_i18n.get(buyer_language_pref, description_i18n.get("en_US", "No description available."))

            item_data_for_list = {
                "template_id": item_template_id,
                "name_i18n": name_i18n,
                "description_i18n": description_i18n,
                "display_name": display_name,
                "display_description": display_description,
                "quantity_available": float(quantity_available),
                "price_per_unit": price_per_unit, # Can be None if price calculation failed
                "item_type": item_def.get("item_type", "unknown"),
                "rarity": item_def.get("rarity", "common"),
                "weight": item_def.get("weight", 0.0),
                "stackable": item_def.get("stackable", False),
                "icon": item_def.get("icon"),
                "properties_i18n": item_def.get("properties_i18n", {}),
                "equipable_slot": item_def.get("equipable_slot"),
                "requirements": item_def.get("requirements")
                # Add other relevant fields from item_def as needed by UI
            }
            tradable_items_list.append(item_data_for_list)

        print(f"EconomyManager.get_tradable_items: Returning {len(tradable_items_list)} items for trader '{trader_actor_id_str}' ({trader_actor_type}) to buyer '{buyer_actor_id_str}'.")
        return tradable_items_list

# --- Конец класса EconomyManager ---
