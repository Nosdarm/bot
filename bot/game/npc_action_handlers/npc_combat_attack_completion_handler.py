# bot/game/npc_action_handlers/npc_combat_attack_completion_handler.py

# --- Imports ---
import traceback
from typing import Dict, Any, Awaitable, Callable

# Import base handler (optional)
from .base_npc_action_handler import BaseNpcActionHandler, SendToChannelCallback

# Import models and managers needed for this specific handler's logic
from bot.game.models.npc import NPC # Need NPC model for type hint
from bot.game.managers.combat_manager import CombatManager # Needed to notify CombatManager


class NpcCombatAttackCompletionHandler(BaseNpcActionHandler): # Inherit from base (optional)
    """
    Обработчик завершения действия 'combat_attack' для NPC.
    Уведомляет CombatManager о завершении действия участника.
    """
    def __init__(self,
                 # Inject managers needed SPECIFICALLY by this handler
                 combat_manager: CombatManager,
                 # Add other managers if needed
                ):
        print("Initializing NpcCombatAttackCompletionHandler...")
        self._combat_manager = combat_manager
        print("NpcCombatAttackCompletionHandler initialized.")

    async def handle(self,
                     npc: NPC,
                     completed_action_data: Dict[str, Any],
                     # Pass necessary services/managers via kwargs from NpcActionProcessor
                     send_callback_factory: Callable[[int], SendToChannelCallback], # For GM notifications
                     **kwargs # Other managers passed from WSP -> Processor
                    ) -> None:
        """
        Handles the completion logic for an NPC 'combat_attack' action.
        """
        print(f"NpcCombatAttackCompletionHandler: Handling completion for NPC {npc.id} combat_attack action.")
        callback_data = completed_action_data.get('callback_data', {})
        combat_id = callback_data.get('combat_id')
        target_id = callback_data.get('target_id')
        target_type = callback_data.get('target_type')

        # Helper for GM notification
        async def _notify_gm(message: str) -> None:
             gm_channel_id = kwargs.get('gm_channel_id')
             if gm_channel_id is not None and send_callback_factory is not None:
                 try:
                     callback = send_callback_factory(gm_channel_id)
                     await callback(message)
                 except Exception as e: print(f"NpcCombatAttackCompletionHandler: Error sending GM notification to channel {gm_channel_id}: {e}")
             else:
                  print(f"NpcCombatAttackCompletionHandler: GM Notification (No Channel ID or Factory): {message}")


        # CombatManager handles the result of the attack action
        if combat_id and self._combat_manager and hasattr(self._combat_manager, 'handle_participant_action_complete'): # Assuming CombatManager has this method
             try:
                  print(f"NpcCombatAttackCompletionHandler: NPC combat action completed for {npc.id} in combat {combat_id}. Notifying CombatManager.")
                  # Pass all necessary managers in kwargs for CombatManager.handle_participant_action_complete
                  await self._combat_manager.handle_participant_action_complete(combat_id, npc.id, completed_action_data, **kwargs)
                  # The CombatManager's method is responsible for logging/notifying about the attack outcome.
                  # We might add a basic GM notification here if that's desired behavior regardless of CombatManager logging.
                  # await _notify_gm(f"💥 NPC {npc.id} завершил атаку на {target_type} {target_id} в бою {combat_id}.")

             except Exception as e:
                  print(f"NpcCombatAttackCompletionHandler: Error during CombatManager.handle_participant_action_complete for NPC {npc.id} in combat {combat_id}: {e}")
                  import traceback
                  print(traceback.format_exc())
                  await _notify_gm(f"❌ NPC {npc.id}: Ошибка при уведомлении CombatManager о завершении атаки в бою {combat_id}.")

        else:
             print(f"NpcCombatAttackCompletionHandler: Warning: Combat action completed for {npc.id} in combat {combat_id}, but CombatManager or method not available.")
             await _notify_gm(f"⚠️ NPC {npc.id}: Действие атаки завершено, но обработчик боя недоступен.")

# End of NpcCombatAttackCompletionHandler class
