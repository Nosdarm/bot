# bot/game/npc_action_handlers/npc_craft_completion_handler.py

# --- Imports ---
import traceback
from typing import Dict, Any, Awaitable, Callable, List, Optional

# Import base handler (optional)
from .base_npc_action_handler import BaseNpcActionHandler, SendToChannelCallback

# Import models and managers needed for this specific handler's logic
from bot.game.models.npc import NPC # Need NPC model for type hint
from bot.game.managers.crafting_manager import CraftingManager # Needed for crafting logic (if any completion logic remains here)
from bot.game.managers.item_manager import ItemManager # Needed to create items
from bot.game.managers.npc_manager import NpcManager # Needed to add items to inventory / mark dirty
# RuleEngine might be needed for result determination, passed via kwargs


class NpcCraftCompletionHandler(BaseNpcActionHandler): # Inherit from base (optional)
    """
    Обработчик завершения действия 'craft' для NPC.
    Создает результат крафта и добавляет его NPC (или в локацию).
    """
    def __init__(self,
                 # Inject managers needed SPECIFICALLY by this handler
                 crafting_manager: CraftingManager,
                 item_manager: ItemManager,
                 npc_manager: NpcManager, # Need NpcManager to add items to inventory and mark dirty
                 # Add other managers if needed
                ):
        print("Initializing NpcCraftCompletionHandler...")
        self._crafting_manager = crafting_manager
        self._item_manager = item_manager
        self._npc_manager = npc_manager
        print("NpcCraftCompletionHandler initialized.")

    async def handle(self,
                     npc: NPC,
                     completed_action_data: Dict[str, Any],
                     # Pass necessary services/managers via kwargs from NpcActionProcessor
                     send_callback_factory: Callable[[int], SendToChannelCallback], # For GM notifications
                     **kwargs # Other managers passed from WSP -> Processor
                    ) -> None:
        """
        Handles the completion logic for an NPC 'craft' action.
        """
        print(f"NpcCraftCompletionHandler: Handling completion for NPC {npc.id} craft action.")
        callback_data = completed_action_data.get('callback_data', {})
        # Retrieve craft parameters from callback_data (e.g., recipe_id, result_item_template_id, used_ingredients)
        recipe_id = callback_data.get('recipe_id')
        result_item_template_id = callback_data.get('result_item_template_id') # Determined in start_action logic
        used_ingredients = callback_data.get('used_ingredients', []) # Determined in start_action logic - TODO: Consumption logic might be here or at start


        # Helper for GM notification
        async def _notify_gm(message: str) -> None:
             gm_channel_id = kwargs.get('gm_channel_id')
             if gm_channel_id is not None and send_callback_factory is not None:
                 try:
                     callback = send_callback_factory(gm_channel_id)
                     await callback(message)
                 except Exception as e: print(f"NpcCraftCompletionHandler: Error sending GM notification to channel {gm_channel_id}: {e}")
             else:
                  print(f"NpcCraftCompletionHandler: GM Notification (No Channel ID or Factory): {message}")

        # TODO: Handle ingredient consumption? (Should happen at START of craft action? Or here at completion?)
        # If consumption happens here:
        # if used_ingredients and hasattr(self._npc_manager, 'remove_item_from_inventory'):
        #      consumed_count = 0
        #      for item_id_to_consume in used_ingredients:
        #           try:
        #                # remove_item_from_inventory needs npc_id, item_id, kwargs
        #                success_remove = await self._npc_manager.remove_item_from_inventory(npc.id, item_id_to_consume, **kwargs)
        #                if success_remove: consumed_count += 1
        #                else: print(f"NpcCraftCompletionHandler: Warning: Could not consume ingredient item {item_id_to_consume} from NPC {npc.id} inventory.")
        #           except Exception as e: print(f"NpcCraftCompletionHandler: Error consuming ingredient {item_id_to_consume} for NPC {npc.id}: {e}"); traceback.print_exc()
        #      if consumed_count < len(used_ingredients):
        #           print(f"NpcCraftCompletionHandler: Warning: Only {consumed_count}/{len(used_ingredients)} ingredients consumed for craft action for NPC {npc.id}. Recipe ID: {recipe_id}")
        #           # TODO: Decide policy if ingredient consumption fails at completion (cancel craft result?)
        #           # await _notify_gm(f"⚠️ NPC {npc.id}: Не все ингредиенты потреблены для крафта {recipe_id}.")


        if self._item_manager and self._npc_manager and hasattr(self._npc_manager, 'add_item_to_inventory'): # Need ItemManager to create item, NpcManager to add to inventory
             try:
                  if result_item_template_id:
                       # Create the result item
                       # create_item needs template_id and optional state_variables, kwargs
                       created_item_id = await self._item_manager.create_item({'template_id': result_item_template_id}, **kwargs) # Create and save item instance
                       if created_item_id:
                            # Add result item to NPC inventory
                            # add_item_to_inventory needs npc_id, item_id, kwargs
                            success = await self._npc_manager.add_item_to_inventory(npc.id, created_item_id, **kwargs) # Add to NPC inventory and save NPC
                            if success:
                                 print(f"NpcCraftCompletionHandler: NPC {npc.id} crafted item {created_item_id} ({result_item_template_id}) and added to inventory.")
                                 await _notify_gm(f"🔨 NPC {npc.id}: Крафт завершен! Создан {result_item_template_id}.")
                            else:
                                 print(f"NpcCraftCompletionHandler: Error adding crafted item {created_item_id} to NPC {npc.id} inventory.")
                                 await _notify_gm(f"❌ NPC {npc.id}: Крафт завершен, но не удалось добавить {result_item_template_id} в инвентарь.")
                       else:
                            print(f"NpcCraftCompletionHandler: Error creating crafted item {result_item_template_id} for NPC {npc.id}.")
                            await _notify_gm(f"❌ NPC {npc.id}: Не удалось создать предмет {result_item_template_id} после крафта.")
                  else:
                        print(f"NpcCraftCompletionHandler: Warning: Craft action completed for NPC {npc.id} but no result_item_template_id specified in callback_data for recipe {recipe_id}.")
                        await _notify_gm(f"⚠️ NPC {npc.id}: Крафт завершен (рецепт {recipe_id}), но без результата.")
             except Exception as e:
                  print(f"NpcCraftCompletionHandler: Error during NPC craft action completion for {npc.id}: {e}")
                  import traceback
                  print(traceback.format_exc())
                  await _notify_gm(f"❌ NPC {npc.id}: Ошибка при завершении крафта.")

        else:
             print(f"NpcCraftCompletionHandler: Warning: Cannot complete craft action for NPC {npc.id}. Required managers/methods not available (ItemManager, NpcManager).")
             await _notify_gm(f"⚠️ NPC {npc.id}: Действие крафта завершено, но обработчик недоступен.")


# End of NpcCraftCompletionHandler class
