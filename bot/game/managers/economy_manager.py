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
        **kwargs: Any
    ) -> Optional[Union[int, float]]:
        """
        Рассчитывает цену для покупки или продажи предмета на рынке локации для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        tpl_id_str = str(item_template_id)
        resolved_quantity = float(quantity) if isinstance(quantity, (int, float)) else 0.0

        if resolved_quantity <= 0:
             print(f"EconomyManager: Warning: Cannot calculate price for non-positive quantity ({resolved_quantity}) of {tpl_id_str} in guild {guild_id_str}.")
             return None

        # Get market inventory for this location/guild
        market_inv = self.get_market_inventory(guild_id_str, location_id) # Use get_market_inventory with guild_id
        if market_inv is None:
             # Market doesn't exist or invalid location
             print(f"EconomyManager: Market inventory not found for location {location_id} in guild {guild_id_str}. Cannot calculate price.")
             return None

        # Get item template data for this guild
        item_mgr = kwargs.get('item_manager', self._item_manager) # Get ItemManager from context or self
        item_template = None
        if item_mgr and hasattr(item_mgr, 'get_item_template'): # Check manager and method
             # get_item_template needs guild_id and template_id
             item_template = item_mgr.get_item_template(guild_id_str, tpl_id_str)

        if item_template is None:
             print(f"EconomyManager: Item template '{tpl_id_str}' not found for guild {guild_id_str}. Cannot calculate price.")
             # TODO: Send feedback?
             return None

        # Get RuleEngine from kwargs or self
        rule_engine = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]

        if rule_engine and hasattr(rule_engine, 'calculate_market_price'):
             try:
                  # calculate_market_price needs market inventory, item template, quantity, is_selling, context
                  # Pass the retrieved market_inv (copy), item_template (dict), quantity, is_selling flag, and the full kwargs context
                  # RuleEngine is expected to use guild_id from context or implicitly from managers in context
                  # FIXME: RuleEngine.calculate_market_price method does not exist. Implement or remove.
                  # price = await rule_engine.calculate_market_price(
                  #     market_inventory=market_inv, # Pass the market inventory data (copy)
                  #     item_template=item_template, # Pass the item template data (dict)
                  #     quantity=resolved_quantity,
                  #     is_selling=is_selling,
                  #     context=kwargs # Pass the full kwargs context (includes guild_id, managers etc.)
                  # )
                  price = None # Fallback since method is missing
                  print(f"EconomyManager: FIXME: Call to rule_engine.calculate_market_price skipped for item {tpl_id_str} as method is missing.")
                  # Ensure returned price is numeric
                  if isinstance(price, (int, float)) and price >= 0:
                       return price
                  elif price is not None:
                       print(f"EconomyManager: Warning: RuleEngine.calculate_market_price returned non-numeric or negative price ({price}) for {tpl_id_str} in guild {guild_id_str}. Returning None.")
                       return None

             except Exception as e:
                  print(f"EconomyManager: ❌ Error calculating market price via RuleEngine for {tpl_id_str} in guild {guild_id_str}: {e}")
                  traceback.print_exc()
                  # Decide error handling: return None or raise? Return None is safer for commands.
                  return None

        else:
             print(f"EconomyManager: Warning: RuleEngine or calculate_market_price method not available for guild {guild_id_str}. Cannot calculate price.")
             # TODO: Fallback to a default price based on item template data directly?
             base_price = float(item_template.get('base_price', 0.0)) # Use base_price from template
             if base_price > 0:
                 calculated_price = base_price * resolved_quantity # Simple calculation
                 # Adjust for buying/selling? (e.g., selling price might be lower than buying)
                 if is_selling: calculated_price *= 0.8 # Example markdown
                 print(f"EconomyManager: Using fallback base price calculation for {tpl_id_str} in guild {guild_id_str}. Price: {calculated_price:.2f}")
                 return calculated_price
             return None # No RuleEngine and no fallback price


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
        """
        guild_id_str = str(guild_id)
        tpl_id_str = str(item_template_id)
        resolved_count = float(count) if isinstance(count, (int, float)) else 1.0

        print(f"EconomyManager: Attempting to buy {resolved_count:.2f}×'{tpl_id_str}' at market {location_id} by {buyer_entity_type} {buyer_entity_id} in guild {guild_id_str}.")

        if resolved_count <= 0:
             print(f"EconomyManager: Warning: Buy count must be positive ({resolved_count}) for {tpl_id_str} in guild {guild_id_str}.")
             return None

        # --- 1. Check if item template exists and market inventory is sufficient ---
        # get_market_inventory needs guild_id
        market_inv = self.get_market_inventory(guild_id_str, location_id)
        if market_inv is None:
            print(f"EconomyManager: Market inventory not found for location {location_id} in guild {guild_id_str}.")
            # TODO: Send feedback?
            return None
        available_quantity = market_inv.get(tpl_id_str, 0.0)
        if available_quantity < resolved_count:
            print(f"EconomyManager: Not enough '{tpl_id_str}' available in market {location_id} for guild {guild_id_str} ({available_quantity:.2f}/{resolved_count:.2f}).")
            # TODO: Send feedback?
            return None

        # --- 2. Calculate price ---
        # calculate_price needs guild_id, location_id, tpl_id, count, is_selling=False, context
        total_cost = await self.calculate_price(
            guild_id=guild_id_str,
            location_id=location_id,
            item_template_id=tpl_id_str,
            quantity=resolved_count,
            is_selling=False, # Buying
            **kwargs # Pass context
        )

        if total_cost is None:
            print(f"EconomyManager: Failed to calculate price for buying {resolved_count:.2f}×'{tpl_id_str}' in guild {guild_id_str}.")
            # TODO: Send feedback?
            return None
        # Ensure total_cost is non-negative (RuleEngine should handle this)
        if total_cost < 0: total_cost = 0 # Should not happen with correct price calculation


        # --- 3. Deduct currency from buyer ---
        # This requires the buyer's manager (CharacterManager, NpcManager) and a method like deduct_currency.
        # Get manager from context
        buyer_mgr: Optional[Any] = None
        deduct_currency_method_name = 'deduct_currency' # Assuming a method like deduct_currency(entity_id, amount, context) exists

        if buyer_entity_type == 'Character':
            buyer_mgr = kwargs.get('character_manager', self._character_manager)
        elif buyer_entity_type == 'NPC':
            buyer_mgr = kwargs.get('npc_manager', self._npc_manager)
        # TODO: Add Party if Parties can buy items

        if not buyer_mgr or not hasattr(buyer_mgr, deduct_currency_method_name):
            print(f"EconomyManager: No suitable manager ({buyer_entity_type}) or '{deduct_currency_method_name}' method found for buyer {buyer_entity_id} in guild {guild_id_str}. Cannot deduct currency.")
            # TODO: Send feedback?
            return None

        # Check if buyer has enough currency (optional, deduct_currency should handle this)
        # Requires a get_currency method on the buyer's manager.
        # has_currency_method_name = 'has_currency' # Assuming has_currency(entity_id, amount, context) exists
        # if hasattr(buyer_mgr, has_currency_method_name):
        #      try:
        #           has_enough = await getattr(buyer_mgr, has_currency_method_name)(buyer_entity_id, total_cost, **kwargs)
        #           if not has_enough:
        #                print(f"EconomyManager: Buyer {buyer_entity_id} does not have enough currency ({total_cost:.2f}) for guild {guild_id_str}.")
        #                # TODO: Send feedback?
        #                return None
        #      except Exception: traceback.print_exc(); # Log error and continue (let deduct handle final check)


        try:
            # Call deduct_currency method, passing buyer ID, cost, and context
            # Deduct currency method is expected to handle success/failure internally.
            # Assuming it returns True on success, False on failure (e.g. insufficient funds).
            # deduct_currency needs entity_id, amount, guild_id, **context
            deduction_successful = await getattr(buyer_mgr, deduct_currency_method_name)(
                buyer_entity_id,
                total_cost,
                guild_id=guild_id_str, # Pass guild_id to entity manager method
                **kwargs # Pass context
            )
            if not deduction_successful:
                 print(f"EconomyManager: Failed to deduct currency ({total_cost:.2f}) from buyer {buyer_entity_id} for guild {guild_id_str}. Purchase failed.")
                 # TODO: Send feedback (e.g., Insufficient funds)?
                 return None

        except Exception as e:
            print(f"EconomyManager: ❌ Error deducting currency from buyer {buyer_entity_id} for guild {guild_id_str}: {e}")
            traceback.print_exc()
            # TODO: Send feedback?
            return None


        # --- 4. Remove items from market inventory ---
        # remove_items_from_market needs guild_id, location_id, items_data, context
        items_to_remove_dict = {tpl_id_str: resolved_count} # Dict for remove_items_from_market
        try:
            removal_successful = await self.remove_items_from_market(
                guild_id=guild_id_str,
                location_id=location_id,
                items_data=items_to_remove_dict,
                **kwargs # Pass context
            )
            # This should always succeed if the initial quantity check passed, but check anyway.
            if not removal_successful:
                # CRITICAL ERROR: Currency deducted, but items not removed from market!
                print(f"EconomyManager: ❌ CRITICAL ERROR: Currency deducted from {buyer_entity_id} ({total_cost:.2f}), but failed to remove {resolved_count:.2f}×'{tpl_id_str}' from market {location_id} in guild {guild_id_str}.")
                # TODO: Handle this severe error - potentially refund currency? Alert GM?
                # For now, log and return None.
                return None # Indicate failure


        except Exception as e:
             print(f"EconomyManager: ❌ CRITICAL ERROR during item removal from market {location_id} for guild {guild_id_str} after successful deduction from {buyer_entity_id}: {e}")
             traceback.print_exc()
             # TODO: Handle this severe error - potentially refund currency? Alert GM?
             # For now, log and return None.
             return None


        # --- 5. Create new item instance(s) and give to buyer ---
        # This requires ItemManager.create_item and ItemManager.move_item
        item_mgr = kwargs.get('item_manager', self._item_manager) # Get ItemManager from context or self
        if not item_mgr or not hasattr(item_mgr, 'create_item') or not hasattr(item_mgr, 'move_item'):
             print(f"EconomyManager: ❌ CRITICAL ERROR: Currency deducted and items removed from market, but ItemManager is not available to create/move items for buyer {buyer_entity_id} in guild {guild_id_str}.")
             # TODO: Handle this severe error!
             return None

        created_item_ids: List[str] = []
        try:
             # Create item instances. Note: Items are typically created as instances, not stacked by quantity in the world.
             # If quantity > 1, you likely create multiple item instances.
             # If your Item model supports quantity on instances, adjust this.
             # Assuming creating 'count' individual instances:
             # Round count down to nearest integer if items cannot be fractional instances
             num_instances_to_create = int(resolved_count) if isinstance(resolved_count, int) else int(resolved_count + 0.5) # Round or truncate? Let's truncate to int for item instances

             for i in range(num_instances_to_create): # Create integer number of items
                  # create_item needs guild_id, item_data, **kwargs
                  # item_data needs template_id, and maybe initial state/temporary flag
                  # We don't set owner/location here, move_item does that.
                  item_data_for_create = {'template_id': tpl_id_str} # Basic data for create_item

                  # Pass guild_id
                  iid = await item_mgr.create_item(
                      guild_id=guild_id_str,
                      item_data=item_data_for_create,
                      **kwargs # Pass context
                  )
                  if iid:
                       created_item_ids.append(iid)
                       # Move the created item instance to the buyer
                       # move_item needs guild_id, item_id, new_owner_id, new_location_id=None, new_owner_type, **kwargs
                       await item_mgr.move_item(
                           guild_id=guild_id_str, # Pass guild_id
                           item_id=iid,
                           new_owner_id=buyer_entity_id, # Buyer is the new owner
                           new_location_id=None, # Item is now owned, not in location
                           new_owner_type=buyer_entity_type, # Specify owner type
                           **kwargs # Pass context
                       )
                  else:
                       print(f"EconomyManager: Warning: Failed to create item instance {i+1}/{num_instances_to_create} for buyer {buyer_entity_id} in guild {guild_id_str}.")
                       # Decide what to do if some items fail to create/move. Refund partially? Alert GM?
                       # Continue loop for now.


             # If the number of successfully created/moved items is less than requested, handle it.
             if len(created_item_ids) < num_instances_to_create:
                  print(f"EconomyManager: Warning: Only created/moved {len(created_item_ids)} of {num_instances_to_create} items for buyer {buyer_entity_id} in guild {guild_id_str}. Partial purchase?")
                  # This is a complex scenario. For now, return the list of successful IDs.

        except Exception as e:
             print(f"EconomyManager: ❌ CRITICAL ERROR during item creation/movement after purchase by {buyer_entity_id} in guild {guild_id_str}: {e}")
             traceback.print_exc()
             # TODO: Handle this severe error! Items/currency inconsistent state.
             # Return the IDs of items that were successfully created/moved before the error.
             return created_item_ids if created_item_ids else None # Return partial success or None

        print(f"EconomyManager: Purchase successful for {buyer_entity_id} in guild {guild_id_str}. Created items: {created_item_ids}.")
        # TODO: Send feedback (e.g., "You bought X items for Y currency.")
        return created_item_ids # Return list of IDs of purchased items


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
        """
        guild_id_str = str(guild_id)
        item_id_str = str(item_id)
        resolved_count = float(count) if isinstance(count, (int, float)) else 1.0 # How many instances? Assuming 1 for now.

        print(f"EconomyManager: Attempting to sell {resolved_count:.2f}× item instance '{item_id_str}' at market {location_id} by {seller_entity_type} {seller_entity_id} in guild {guild_id_str}.")

        # Let's assume selling means selling one specific instance (count is always 1).
        # If you need to sell multiple instances, the command/logic needs to handle providing multiple item_ids.
        # If you need to sell X units from a stack, the command/logic needs to handle that quantity.
        # For this sell_item method, assume selling one *instance*.
        if resolved_count != 1.0:
             print(f"EconomyManager: Warning: sell_item currently only supports selling count=1 of a specific item instance. Received count={resolved_count} for item instance {item_id_str}.")
             return None # Only support selling 1 instance at a time for now


        # --- 1. Check if seller owns the item instance and if market exists ---
        # Requires ItemManager.get_item
        item_mgr = kwargs.get('item_manager', self._item_manager) # Get ItemManager from context or self
        if not item_mgr or not hasattr(item_mgr, 'get_item') or not hasattr(item_mgr, 'move_item') or not hasattr(item_mgr, 'mark_item_deleted'):
             print(f"EconomyManager: ItemManager or required methods are not available to process sale for guild {guild_id_str}.")
             # TODO: Send feedback?
             return None

        # get_item needs guild_id
        item_instance = item_mgr.get_item(guild_id_str, item_id_str)
        if not item_instance or str(getattr(item_instance, 'guild_id', None)) != guild_id_str: # Check exists and guild
             print(f"EconomyManager: Item instance '{item_id_str}' not found or does not belong to guild {guild_id_str}.")
             # TODO: Send feedback?
             return None

        # Check if the item instance is owned by the seller
        item_owner_id = getattr(item_instance, 'owner_id', None)
        item_owner_type = getattr(item_instance, 'owner_type', None)
        if item_owner_id != seller_entity_id or item_owner_type != seller_entity_type:
             print(f"EconomyManager: Item instance '{item_id_str}' is not owned by {seller_entity_type} {seller_entity_id} in guild {guild_id_str}. Owned by {item_owner_type} {item_owner_id}.")
             # TODO: Send feedback?
             return None

        # get_market_inventory needs guild_id
        market_inv = self.get_market_inventory(guild_id_str, location_id)
        if market_inv is None:
            print(f"EconomyManager: Market inventory not found for location {location_id} in guild {guild_id_str}.")
            # TODO: Send feedback?
            return None


        # Get the item template ID from the instance
        item_template_id = getattr(item_instance, 'template_id', None)
        if not item_template_id:
             print(f"EconomyManager: Item instance '{item_id_str}' has no template_id in guild {guild_id_str}. Cannot sell.")
             # TODO: Send feedback?
             return None

        # --- 2. Calculate price ---
        # calculate_price needs guild_id, location_id, item_template_id, quantity, is_selling=True, context
        # Price is calculated based on the template ID and the *quantity of units* being sold.
        # If selling 1 instance, the quantity of units is the instance's quantity.
        quantity_of_units_sold = float(getattr(item_instance, 'quantity', 1.0)) # Quantity of the instance being sold

        total_revenue = await self.calculate_price(
            guild_id=guild_id_str,
            location_id=location_id,
            item_template_id=item_template_id,
            quantity=quantity_of_units_sold, # Calculate price based on total units
            is_selling=True, # Selling
            **kwargs # Pass context
        )

        if total_revenue is None:
            print(f"EconomyManager: Failed to calculate price for selling instance '{item_id_str}' ({quantity_of_units_sold:.2f} units) in guild {guild_id_str}.")
            # TODO: Send feedback?
            return None
        # Ensure total_revenue is non-negative (RuleEngine should handle this)
        if total_revenue < 0: total_revenue = 0 # Should not happen with correct price calculation


        # --- 3. Remove item instance from seller's inventory ---
        # Simplest way is to mark the specific item instance for deletion.
        # The entity manager's inventory logic should use ItemManager to manage the list of item IDs.
        # When the Item is marked for deletion, the entity manager should ideally remove its ID from the inventory list on save.
        # Or, CharacterManager/NpcManager should have a remove_item_from_inventory method that calls ItemManager.mark_item_deleted
        # and updates its own inventory list.
        # Let's assume the entity manager (seller_mgr) has a specific method for this.
        remove_item_from_inventory_method_name = 'remove_item_from_inventory' # Assuming method like remove_item_from_inventory(entity_id, item_id, context) exists
        seller_mgr: Optional[Any] = None # Get manager from context
        if seller_entity_type == 'Character': seller_mgr = kwargs.get('character_manager', self._character_manager)
        elif seller_entity_type == 'NPC': seller_mgr = kwargs.get('npc_manager', self._npc_manager)
        # TODO: Add Party

        if not seller_mgr or not hasattr(seller_mgr, remove_item_from_inventory_method_name):
             print(f"EconomyManager: No suitable manager ({seller_entity_type}) or '{remove_item_from_inventory_method_name}' method found for seller {seller_entity_id} in guild {guild_id_str}. Cannot remove item from inventory.")
             # TODO: Send feedback?
             # Critical failure - item not removed from seller.
             return None

        try:
            # Call remove_item_from_inventory method on the seller's manager
            # It should remove the item ID from the entity's inventory list and potentially mark the item for deletion via ItemManager.
            # Assuming remove_item_from_inventory needs entity_id, item_id, guild_id, **context
            item_removal_successful = await getattr(seller_mgr, remove_item_from_inventory_method_name)(
                seller_entity_id,
                item_id_str,
                guild_id=guild_id_str, # Pass guild_id
                **kwargs # Pass context
            )
            if not item_removal_successful:
                 # Seller manager reported failure to remove item from inventory.
                 print(f"EconomyManager: Failed to remove item instance '{item_id_str}' from seller {seller_entity_id} inventory for guild {guild_id_str}. Sale failed before currency/market update.")
                 # TODO: Send feedback?
                 return None

            # Note: Assuming the entity manager's remove_item_from_inventory calls ItemManager.mark_item_deleted.
            # If it doesn't, we need to call mark_item_deleted here.
            # Let's assume for now the entity manager handles the mark_item_deleted call.


        except Exception as e:
             print(f"EconomyManager: ❌ Error removing item from seller {seller_entity_id} inventory for guild {guild_id_str}: {e}")
             traceback.print_exc()
             # TODO: Send feedback?
             return None


        # --- 4. Add currency to seller ---
        # Requires the seller's manager and add_currency method.
        add_currency_method_name = 'add_currency' # Assuming method like add_currency(entity_id, amount, guild_id, context) exists

        # Seller manager lookup already done above. Check for add_currency method specifically.
        if not seller_mgr or not hasattr(seller_mgr, add_currency_method_name):
            # This is a severe inconsistency if remove_item_from_inventory worked but add_currency is missing.
             print(f"EconomyManager: ❌ CRITICAL ERROR: Item removed from seller inventory, but seller manager ({seller_entity_type}) or '{add_currency_method_name}' method is not available to add currency for {seller_entity_id} in guild {guild_id_str}. Item lost, no revenue!")
             # TODO: Alert GM? Send feedback?
             return None # Indicate failure


        try:
            # Call add_currency method, passing seller ID, revenue, and context
            # add_currency needs entity_id, amount, guild_id, **context
            addition_successful = await getattr(seller_mgr, add_currency_method_name)(
                seller_entity_id,
                total_revenue,
                guild_id=guild_id_str, # Pass guild_id to entity manager method
                **kwargs # Pass context
            )
            if not addition_successful:
                 # Seller manager reported failure to add currency. Item is removed, seller gets no money.
                 print(f"EconomyManager: Warning: Failed to add currency ({total_revenue:.2f}) to seller {seller_entity_id} for guild {guild_id_str}. Item sold but no revenue added.")
                 # TODO: Alert GM? Send feedback?
                 # Continue process, the item is removed anyway.

        except Exception as e:
            print(f"EconomyManager: ❌ Error adding currency to seller {seller_entity_id} for guild {guild_id_str}: {e}")
            traceback.print_exc()
            # TODO: Alert GM? Send feedback?
            # Continue process, the item is removed anyway.


        # --- 5. Add units back to market inventory ---
        # add_items_to_market needs guild_id, location_id, items_data, context
        # items_data is {item_template_id: quantity}
        items_to_add_dict = {item_template_id: quantity_of_units_sold} # Add total units sold back to market
        try:
            addition_successful = await self.add_items_to_market(
                guild_id=guild_id_str,
                location_id=location_id,
                items_data=items_to_add_dict,
                **kwargs # Pass context
            )
            # This should always succeed unless market data is corrupted.
            if not addition_successful:
                 print(f"EconomyManager: Warning: Failed to add {quantity_of_units_sold:.2f}×'{item_template_id}' back to market {location_id} for guild {guild_id_str} after sale. Market inventory inconsistency.")
                 # TODO: Alert GM? Log?
                 # Continue process.

        except Exception as e:
             print(f"EconomyManager: ❌ Error during item addition back to market {location_id} for guild {guild_id_str} after sale: {e}")
             traceback.print_exc()
             # TODO: Alert GM? Log?
             # Continue process.


        print(f"EconomyManager: Sale successful for {seller_entity_id} in guild {guild_id_str}. Earned revenue: {total_revenue:.2f}.")
        # TODO: Send feedback (e.g., "You sold X items for Y currency.")
        return total_revenue # Return revenue earned

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
              try:
                   # process_economy_tick needs guild_id and context
                   # RuleEngine is expected to iterate through markets for this guild, apply restock/price changes etc.
                   # RuleEngine should call add/remove_items_to_market and mark_market_dirty on this manager.
                   # FIXME: RuleEngine.process_economy_tick method does not exist. Implement or remove.
                   # await rule_engine.process_economy_tick(guild_id=guild_id_str, context=kwargs)
                   print(f"EconomyManager: FIXME: Call to rule_engine.process_economy_tick skipped for guild {guild_id_str} as method is missing.")

              except Exception as e:
                   print(f"EconomyManager: ❌ Error processing economy tick for guild {guild_id_str}: {e}")
                   traceback.print_exc()
         # else: print(f"EconomyManager: Warning: RuleEngine or process_economy_tick method not available for guild {guild_id_str}. Skipping economy tick.") # Too noisy?


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

# --- Конец класса EconomyManager ---
