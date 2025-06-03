# bot/game/npc_action_handlers/npc_move_completion_handler.py

# --- Imports ---
import traceback
from typing import Dict, Any, Awaitable, Callable, Optional

# Import base handler (optional)
from .base_npc_action_handler import BaseNpcActionHandler, SendToChannelCallback

# Import models and managers needed for this specific handler's logic
from bot.game.models.npc import NPC # Need NPC model for type hint
from bot.game.managers.location_manager import LocationManager # Needed for location updates and triggers
from bot.game.managers.npc_manager import NpcManager # Needed to mark NPC dirty


class NpcMoveCompletionHandler(BaseNpcActionHandler): # Inherit from base (optional)
    """
    Обработчик завершения действия 'move' для NPC.
    Обновляет локацию NPC и вызывает триггеры OnExit/OnEnter.
    """
    def __init__(self,
                 # Inject managers needed SPECIFICALLY by this handler
                 location_manager: LocationManager,
                 npc_manager: NpcManager, # Need NpcManager to update NPC object and mark dirty
                 # Add other managers if needed in this handler's logic
                ):
        print("Initializing NpcMoveCompletionHandler...")
        self._location_manager = location_manager
        self._npc_manager = npc_manager
        print("NpcMoveCompletionHandler initialized.")

    async def handle(self,
                     npc: NPC,
                     completed_action_data: Dict[str, Any],
                     # Pass necessary services/managers via kwargs from NpcActionProcessor
                     send_callback_factory: Callable[[int], SendToChannelCallback], # For GM notifications
                     **kwargs # Other managers passed from WSP -> Processor
                    ) -> None:
        """
        Handles the completion logic for an NPC 'move' action.
        """
        print(f"NpcMoveCompletionHandler: Handling completion for NPC {npc.id} move action.")
        callback_data = completed_action_data.get('callback_data', {})
        target_location_id = callback_data.get('target_location_id')
        old_location_id = getattr(npc, 'location_id', None) # Current location before update

        # Helper for GM notification (can be moved to a utility or base class)
        async def _notify_gm(message: str) -> None:
            gm_channel_id = kwargs.get('gm_channel_id') # Get GM channel ID from kwargs passed by processor
            if gm_channel_id is not None and send_callback_factory is not None:
                try:
                    callback = send_callback_factory(gm_channel_id)
                    await callback(message)
                except Exception as e: print(f"NpcMoveCompletionHandler: Error sending GM notification to channel {gm_channel_id}: {e}")
            else:
                 print(f"NpcMoveCompletionHandler: GM Notification (No Channel ID in kwargs or Factory): {message}")


        if target_location_id and self._location_manager and hasattr(self._location_manager, 'handle_entity_arrival') and hasattr(self._location_manager, 'handle_entity_departure'):
             try:
                  # 1. Update the NPC's location in the NpcManager cache
                  print(f"NpcMoveCompletionHandler: Updating NPC {npc.id} location in cache from {old_location_id} to {target_location_id}.")
                  npc.location_id = target_location_id
                  # Mark the NPC as dirty via its manager
                  self._npc_manager._dirty_npcs.add(npc.id)

                  # 2. Обработать триггеры OnExit для старой локации (если она была)
                  # Pass all managers/services from kwargs so triggers can use them
                  if old_location_id: # Don't call OnExit if NPC started without a location
                       print(f"NpcMoveCompletionHandler: Triggering OnExit for location {old_location_id}.")
                       await self._location_manager.handle_entity_departure(old_location_id, npc.id, 'NPC', **kwargs)

                  # 3. Обработать триггеры OnEnter для новой локации
                  # Pass all managers/services from kwargs so triggers can use them
                  print(f"NpcMoveCompletionHandler: Triggering OnEnter for location {target_location_id}.")
                  await self._location_manager.handle_entity_arrival(target_location_id, npc.id, 'NPC', **kwargs)


                  await _notify_gm(f"🚶 NPC {npc.id} прибыл в '{self._location_manager.get_location_name(target_location_id) or target_location_id}'.")
                  print(f"NpcMoveCompletionHandler: NPC {npc.id} completed move action to {target_location_id}. Triggers processed.")

             except Exception as e:
                   print(f"NpcMoveCompletionHandler: ❌ Error during NPC move completion logic for NPC {npc.id}: {e}")
                   import traceback
                   print(traceback.format_exc())
                   await _notify_gm(f"❌ NPC {npc.id}: Ошибка завершения перемещения. Произошла внутренняя ошибка.")


        else:
               print("NpcMoveCompletionHandler: Error completing NPC move action: Required managers/data not available or LocationManager trigger methods missing.")
               await _notify_gm(f"❌ NPC {npc.id}: Ошибка завершения перемещения. Необходимые компоненты недоступны.")

# End of NpcMoveCompletionHandler class
