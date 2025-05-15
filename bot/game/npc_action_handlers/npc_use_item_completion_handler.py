# bot/game/npc_action_handlers/npc_use_item_completion_handler.py

# --- Imports ---
import traceback
from typing import Dict, Any, Awaitable, Callable, Optional

# Import base handler (optional)
from .base_npc_action_handler import BaseNpcActionHandler, SendToChannelCallback

# Import models and managers needed for this specific handler's logic
from bot.game.models.npc import NPC # Need NPC model for type hint
from bot.game.rules.rule_engine import RuleEngine # Needed to calculate item effect
from bot.game.managers.item_manager import ItemManager # Needed to get item object
from bot.game.managers.npc_manager import NpcManager # Needed to remove item from inventory / mark dirty
from bot.game.managers.character_manager import CharacterManager # Needed to get Character target object
from bot.game.managers.status_manager import StatusManager # Needed to apply status effects
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.location_manager import LocationManager

class NpcUseItemCompletionHandler(BaseNpcActionHandler): # Inherit from base (optional)
    """
    Обработчик завершения действия 'use_item' для NPC.
    Применяет эффект предмета на цель и удаляет предмет из инвентаря NPC (если потреблен).
    """
    def __init__(self,
                 # Inject managers needed SPECIFICALLY by this handler
                 item_manager: ItemManager,
                 rule_engine: RuleEngine,
                 npc_manager: NpcManager, # Need NpcManager to remove item and mark dirty
                 character_manager: Optional[CharacterManager] = None, # Needed to get Character target
                 status_manager: Optional[StatusManager] = None, # Needed to apply status effects
                 # Add other managers needed for item effects (e.g., CombatManager for combat items, LocationManager for area effects)
                 combat_manager: Optional['CombatManager'] = None, # If items have combat effects
                 location_manager: Optional['LocationManager'] = None, # If items have location effects
                ):
        print("Initializing NpcUseItemCompletionHandler...")
        self._item_manager = item_manager
        self._rule_engine = rule_engine
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._status_manager = status_manager
        self._combat_manager = combat_manager
        self._location_manager = location_manager
        print("NpcUseItemCompletionHandler initialized.")

    async def handle(self,
                     npc: NPC,
                     completed_action_data: Dict[str, Any],
                     # Pass necessary services/managers via kwargs from NpcActionProcessor
                     send_callback_factory: Callable[[int], SendToChannelCallback], # For GM notifications
                     **kwargs # Other managers passed from WSP -> Processor
                    ) -> None:
        """
        Handles the completion logic for an NPC 'use_item' action.
        """
        print(f"NpcUseItemCompletionHandler: Handling completion for NPC {npc.id} use_item action.")
        callback_data = completed_action_data.get('callback_data', {})
        # Retrieve use parameters from callback_data (item_id, target_id, target_type)
        item_id = callback_data.get('item_id')
        target_id = callback_data.get('target_id')
        target_type = callback_data.get('target_type')

        # Helper for GM notification
        async def _notify_gm(message: str) -> None:
             gm_channel_id = kwargs.get('gm_channel_id')
             if gm_channel_id is not None and send_callback_factory is not None:
                 try:
                     callback = send_callback_factory(gm_channel_id)
                     await callback(message)
                 except Exception as e: print(f"NpcUseItemCompletionHandler: Error sending GM notification to channel {gm_channel_id}: {e}")
             else:
                  print(f"NpcUseItemCompletionHandler: GM Notification (No Channel ID or Factory): {message}")


        # Requires ItemManager, RuleEngine, NpcManager (to remove item)
        if item_id and self._item_manager and self._rule_engine and self._npc_manager and hasattr(self._npc_manager, 'remove_item_from_inventory'):
             try:
                  # Get item object from ItemManager cache
                  item_obj = self._item_manager.get_item(item_id)

                  # Get target object based on target_id and target_type using Character/NpcManager
                  target_obj = None
                  if target_type == 'Character' and self._character_manager and hasattr(self._character_manager, 'get_character'):
                      target_obj = self._character_manager.get_character(target_id)
                  elif target_type == 'NPC' and self._npc_manager and hasattr(self._npc_manager, 'get_npc'):
                      target_obj = self._npc_manager.get_npc(target_id)
                  # TODO: Get Object if target_type is Object using ObjectManager?

                  if item_obj and target_obj and hasattr(self._rule_engine, 'calculate_item_use_effect'):
                       # calculate_item_use_effect needs user, item, target, context
                       # Pass all necessary managers in kwargs for RuleEngine
                       effect_result = await self._rule_engine.calculate_item_use_effect(npc, item_obj, target_obj, context=kwargs) # Pass NPC (user), item, target, context

                       # Apply the effect result (e.g., change stats, apply status, spawn item)
                       # This often involves calling other managers (StatusManager, CharacterManager/NpcManager for stats, ItemManager for spawning/dropping)
                       if effect_result:
                            print(f"NpcUseItemCompletionHandler: NPC {npc.id} used item {item_id} ({getattr(item_obj, 'template_id', 'N/A')}) on {target_type} {target_id}. Effect result: {effect_result}")
                            # TODO: Apply effect_result (e.g., healing, damage, status effect)
                            # This part is still a TODO as it depends heavily on your effect structure
                            # Example: Healing (requires target_obj to have health/max_health)
                            # if effect_result.get('type') == 'heal' and hasattr(target_obj, 'health') and hasattr(target_obj, 'max_health'):
                            #      heal_amount = effect_result.get('amount', 0)
                            #      if isinstance(target_obj.health, (int, float)) and isinstance(target_obj.max_health, (int, float)):
                            #           target_obj.health = min(target_obj.health + heal_amount, target_obj.max_health)
                            #           # Mark target dirty in its manager
                            #           if target_type == 'Character' and self._character_manager: self._character_manager._dirty_characters.add(target_id)
                            #           elif target_type == 'NPC' and self._npc_manager: self._npc_manager._dirty_npcs.add(target_id)
                            #      else: print(f"NpcUseItemCompletionHandler: Warning: Target {target_type} {target_id} health is not numeric. Cannot apply healing.")
                            # Example: Apply Status Effect (requires StatusManager)
                            # if effect_result.get('type') == 'status' and self._status_manager and hasattr(self._status_manager, 'add_status_effect_to_entity'):
                            #      status_type = effect_result.get('status_type')
                            #      duration = effect_result.get('duration')
                            #      await self._status_manager.add_status_effect_to_entity(target_id, target_type, status_type, duration, source_id=npc.id, **kwargs)

                       else:
                           print(f"NpcUseItemCompletionHandler: Info: Item use action completed for NPC {npc.id}, item {item_id} on {target_id}, but RuleEngine returned no effect.")


                       # Remove item from inventory (if consumed) - NpcManager handles this
                       # Check if item is consumed based on rule_engine result or item data
                       item_consumed = effect_result.get('consumed', True) # Assuming result includes consumption info, default to True
                       if item_consumed:
                            # remove_item_from_inventory needs npc_id, item_id, kwargs
                            success_remove = await self._npc_manager.remove_item_from_inventory(npc.id, item_id, **kwargs) # Removes from NPC inventory and saves NPC
                            if success_remove:
                                 # ItemManager.move_item (called by remove_item_from_inventory) handles item state (e.g., deleting it or dropping)
                                 print(f"NpcUseItemCompletionHandler: NPC {npc.id} consumed item {item_id}.")
                                 await _notify_gm(f"✨ NPC {npc.id}: Использовал предмет {getattr(item_obj, 'template_id', item_id)} на {target_id} (потреблен).")
                            else:
                                 print(f"NpcUseItemCompletionHandler: Error removing item {item_id} from NPC {npc.id} inventory after use.")
                                 await _notify_gm(f"❌ NPC {npc.id}: Использовал предмет {getattr(item_obj, 'template_id', item_id)}, но не удалось удалить из инвентаря.")
                       else:
                            # Item was not consumed
                            await _notify_gm(f"💡 NPC {npc.id}: Использовал предмет {getattr(item_obj, 'template_id', item_id)} (не потреблен) на {target_id}.")

                  elif not item_obj:
                       print(f"NpcUseItemCompletionHandler: Error completing use_item action: Item object {item_id} not found for NPC {npc.id}.")
                       await _notify_gm(f"❌ NPC {npc.id}: Ошибка при завершении use_item: Предмет {item_id} не найден.")
                  elif not target_obj:
                       print(f"NpcUseItemCompletionHandler: Error completing use_item action: Target object {target_type} ID {target_id} not found for NPC {npc.id}.")
                       await _notify_gm(f"❌ NPC {npc.id}: Ошибка при завершении use_item: Цель {target_id} не найдена.")
                  else: # Should not happen if item_obj and target_obj are checked above
                       print(f"NpcUseItemCompletionHandler: Warning: Cannot complete use_item action for NPC {npc.id}. RuleEngine or calculate_item_use_effect method not available.")
                       await _notify_gm(f"⚠️ NPC {npc.id}: Действие use_item завершено, но обработчик эффектов недоступен.")

             except Exception as e:
                  print(f"NpcUseItemCompletionHandler: Error during NPC use_item action completion for {npc.id}: {e}")
                  import traceback
                  print(traceback.format_exc())
                  await _notify_gm(f"❌ NPC {npc.id}: Ошибка при завершении use_item.")

        else:
             print(f"NpcUseItemCompletionHandler: Warning: Cannot complete use_item action for NPC {npc.id}. Required managers/methods not available.")
             await _notify_gm(f"⚠️ NPC {npc.id}: Действие use_item завершено, но обработчик недоступен.")

# End of NpcUseItemCompletionHandler class