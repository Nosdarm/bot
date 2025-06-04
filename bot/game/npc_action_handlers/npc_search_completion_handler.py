# bot/game/npc_action_handlers/npc_search_completion_handler.py

# --- Imports ---
import traceback
from typing import Dict, Any, Awaitable, Callable, List, Optional

# Import base handler (optional)
from .base_npc_action_handler import BaseNpcActionHandler, SendToChannelCallback

# Import models and managers needed for this specific handler's logic
from bot.game.models.npc import NPC # Need NPC model for type hint
from bot.game.rules.rule_engine import RuleEngine # Needed for loot determination
from bot.game.managers.item_manager import ItemManager # Needed to create/move items
from bot.game.managers.npc_manager import NpcManager # Needed to add items to inventory / mark dirty
# LocationManager needed in RuleEngine context, passed via kwargs


class NpcSearchCompletionHandler(BaseNpcActionHandler): # Inherit from base (optional)
    """
    Обработчик завершения действия 'search' для NPC.
    Определяет найденный лут и добавляет его NPC или в локацию.
    """
    def __init__(self,
                 # Inject managers needed SPECIFICALLY by this handler
                 rule_engine: RuleEngine,
                 item_manager: ItemManager,
                 npc_manager: NpcManager, # Need NpcManager to add items to inventory and mark dirty
                 # Add other managers if needed
                ):
        print("Initializing NpcSearchCompletionHandler...")
        self._rule_engine = rule_engine
        self._item_manager = item_manager
        self._npc_manager = npc_manager
        print("NpcSearchCompletionHandler initialized.")

    async def handle(self,
                     npc: NPC,
                     completed_action_data: Dict[str, Any],
                     # Pass necessary services/managers via kwargs from NpcActionProcessor
                     send_callback_factory: Callable[[int], SendToChannelCallback], # For GM notifications
                     **kwargs # Other managers passed from WSP -> Processor
                    ) -> None:
        """
        Handles the completion logic for an NPC 'search' action.
        """
        print(f"NpcSearchCompletionHandler: Handling completion for NPC {npc.id} search action.")
        callback_data = completed_action_data.get('callback_data', {})
        # Retrieve search parameters from callback_data (e.g., area to search, skill check result)
        search_area = callback_data.get('search_area') # Example
        skill_check_result = callback_data.get('skill_check_result') # Example


        # Helper for GM notification
        async def _notify_gm(message: str) -> None:
             gm_channel_id = kwargs.get('gm_channel_id')
             if gm_channel_id is not None and send_callback_factory is not None:
                 try:
                     callback = send_callback_factory(gm_channel_id)
                     await callback(message)
                 except Exception as e: print(f"NpcSearchCompletionHandler: Error sending GM notification to channel {gm_channel_id}: {e}")
             else:
                  print(f"NpcSearchCompletionHandler: GM Notification (No Channel ID or Factory): {message}")


        if self._item_manager and self._rule_engine and self._npc_manager: # Need ItemManager to create/move items, RuleEngine for loot determination, NpcManager to add items
             try:
                  # RuleEngine determines loot based on search parameters and NPC skill
                  # determine_search_loot should return a list of Item objects or template_ids and their destination ('inventory', 'location')
                  # Passing NPC object and location ID for context
                  search_context = {
                       'npc': npc,
                       'location_id': getattr(npc, 'location_id', None),
                       'search_area': search_area,
                       'skill_check_result': skill_check_result,
                       # Pass managers needed by RuleEngine, ItemManager methods, NpcManager methods (via kwargs)
                       **kwargs
                  }
                  # determine_search_loot needs context including managers
                  # RuleEngine does not have determine_search_loot. Using placeholder.
                  # TODO: Ensure RuleEngine.resolve_loot_generation is appropriate for NPC searching action or create a dedicated method.
                  found_items_info: List[Dict[str, Any]] = [] # Placeholder, original call: await self._rule_engine.determine_search_loot(search_context)
                  # Example of what a call to resolve_loot_generation might look like:
                  # location_id = getattr(npc, 'location_id', None)
                  # if location_id and hasattr(self._rule_engine, 'resolve_loot_generation'):
                  #     # This assumes the location itself has a loot_table_id or one can be inferred
                  #     # For simplicity, we are not fetching location_data here to get loot_table_id.
                  #     # A more complete implementation would fetch location data.
                  #     loot_table_id_to_use = callback_data.get('loot_table_id', f"search_{location_id}") # Example
                  #     generated_loot_result = await self._rule_engine.resolve_loot_generation(
                  #         guild_id=kwargs.get('guild_id'),
                  #         loot_table_id=loot_table_id_to_use,
                  #         looter_entity=npc,
                  #         context=search_context
                  #     )
                  #     found_items_info = generated_loot_result.get('items', [])
                  # else:
                  #     print(f"NpcSearchCompletionHandler: Could not determine location_id or resolve_loot_generation method not available in RuleEngine.")

                  if found_items_info: # This will be false with current placeholder
                       print(f"NpcSearchCompletionHandler: NPC {npc.id} found items during search: {found_items_info}")
                       items_added_count = 0
                       for item_info in found_items_info:
                            item_template_id = item_info.get('item_template_id')
                            quantity = item_info.get('quantity', 1) # Assume quantity for stackable
                            destination = item_info.get('destination', 'inventory') # 'inventory' or 'location'
                            if item_template_id:
                                 # Create item(s) and add to inventory or location
                                 # item_manager.create_item handles creation and initial save
                                 # item_manager.add_item_to_inventory_or_location handles moving
                                 # This might involve creating multiple items for quantity > 1
                                 for _ in range(quantity):
                                      # create_item needs template_id and optional state_variables, kwargs
                                      created_item_id = await self._item_manager.create_item({'template_id': item_template_id}, **kwargs) # Create item instance
                                      if created_item_id:
                                           success = False
                                           if destination == 'inventory' and hasattr(self._npc_manager, 'add_item_to_inventory'): # Assuming NpcManager has add_item
                                                # Add to NPC's inventory (updates NPC cache, calls ItemManager.move_item)
                                                # add_item_to_inventory needs npc_id, item_id, kwargs
                                                success = await self._npc_manager.add_item_to_inventory(npc.id, created_item_id, **kwargs)
                                                if success: items_added_count += 1
                                           elif destination == 'location' and hasattr(self._item_manager, 'move_item'):
                                                # Move item to NPC's current location (updates ItemManager cache)
                                                # move_item needs item_id, new_owner_id, new_location_id, kwargs
                                                target_location = getattr(npc, 'location_id', None)
                                                if target_location:
                                                     success = await self._item_manager.move_item(created_item_id, new_owner_id=None, new_location_id=target_location, **kwargs)
                                                     if success: items_added_count += 1
                                                else: print(f"NpcSearchCompletionHandler: Warning: NPC {npc.id} has no location to drop item {created_item_id} after search.")

                                           if not success:
                                                print(f"NpcSearchCompletionHandler: Error adding found item {created_item_id} ({item_template_id}) to destination '{destination}' for NPC {npc.id}.")
                                                await _notify_gm(f"⚠️ NPC {npc.id}: Ошибка при добавлении найденного предмета {item_template_id} ({destination}).")
                            else:
                                 print(f"NpcSearchCompletionHandler: Warning: Item template ID missing for found item info {item_info} for NPC {npc.id}. Skipping item.")

                       print(f"NpcSearchCompletionHandler: NPC {npc.id} search completed. Added {items_added_count} items.")
                       await _notify_gm(f"🔍 NPC {npc.id}: Поиск завершен. Найдено предметов: {items_added_count}.")
                  else:
                       print(f"NpcSearchCompletionHandler: NPC {npc.id} search completed. Found nothing.")
                       await _notify_gm(f"🔍 NPC {npc.id}: Поиск завершен. Ничего не найдено.")

             except Exception as e:
                   print(f"NpcSearchCompletionHandler: Error during NPC search action completion for {npc.id}: {e}")
                   import traceback
                   print(traceback.format_exc())
                   await _notify_gm(f"❌ NPC {npc.id}: Ошибка при завершении поиска.")

        else:
             print(f"NpcSearchCompletionHandler: Warning: Cannot complete search action for NPC {npc.id}. Required managers/methods not available.")
             await _notify_gm(f"⚠️ NPC {npc.id}: Действие поиска завершено, но обработчик недоступен.")


# End of NpcSearchCompletionHandler class
