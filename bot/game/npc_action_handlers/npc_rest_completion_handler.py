# bot/game/npc_action_handlers/npc_rest_completion_handler.py

# --- Imports ---
import traceback
from typing import Dict, Any, Awaitable, Callable, Optional

# Import base handler (optional)
from .base_npc_action_handler import BaseNpcActionHandler, SendToChannelCallback

# Import models and managers needed for this specific handler's logic
from bot.game.models.npc import NPC # Need NPC model for type hint
from bot.game.rules.rule_engine import RuleEngine # Needed for recovery calculation
from bot.game.managers.status_manager import StatusManager # Needed to remove statuses
from bot.game.managers.npc_manager import NpcManager # Needed to mark NPC dirty


class NpcRestCompletionHandler(BaseNpcActionHandler): # Inherit from base (optional)
    """
    Обработчик завершения действия 'rest' для NPC.
    Применяет эффекты восстановления (здоровье, мана, снятие статусов).
    """
    def __init__(self,
                 # Inject managers needed SPECIFICALLY by this handler
                 rule_engine: RuleEngine,
                 status_manager: StatusManager,
                 npc_manager: NpcManager, # Need NpcManager to update NPC object and mark dirty
                 # Add other managers if needed
                ):
        print("Initializing NpcRestCompletionHandler...")
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._npc_manager = npc_manager
        print("NpcRestCompletionHandler initialized.")

    async def handle(self,
                     npc: NPC,
                     completed_action_data: Dict[str, Any],
                     # Pass necessary services/managers via kwargs from NpcActionProcessor
                     send_callback_factory: Callable[[int], SendToChannelCallback], # For GM notifications
                     **kwargs # Other managers passed from WSP -> Processor
                    ) -> None:
        """
        Handles the completion logic for an NPC 'rest' action.
        """
        print(f"NpcRestCompletionHandler: Handling completion for NPC {npc.id} rest action.")
        # callback_data = completed_action_data.get('callback_data', {}) # No specific callback data for rest yet

        # Helper for GM notification
        async def _notify_gm(message: str) -> None:
             gm_channel_id = kwargs.get('gm_channel_id')
             if gm_channel_id is not None and send_callback_factory is not None:
                 try:
                     callback = send_callback_factory(gm_channel_id)
                     await callback(message)
                 except Exception as e: print(f"NpcRestCompletionHandler: Error sending GM notification to channel {gm_channel_id}: {e}")
             else:
                  print(f"NpcRestCompletionHandler: GM Notification (No Channel ID or Factory): {message}")


        # Implement rest recovery logic (restore health, mana, remove statuses) using rule_engine and status_manager
        if self._rule_engine and hasattr(self._rule_engine, 'calculate_rest_recovery') and self._status_manager:
             try:
                  # calculate_rest_recovery needs npc object and duration, returns dict of recovery amounts
                  recovery = await self._rule_engine.calculate_rest_recovery(npc, duration=completed_action_data.get('total_duration', 0.0), **kwargs)
                  # Apply recovery to NPC object and mark dirty
                  if recovery:
                       if 'health' in recovery and hasattr(npc, 'health') and hasattr(npc, 'max_health'):
                            # Ensure health and max_health are numeric before using min() and addition
                            if isinstance(npc.health, (int, float)) and isinstance(npc.max_health, (int, float)):
                                npc.health = min(npc.health + recovery.get('health', 0), npc.max_health)
                                self._npc_manager._dirty_npcs.add(npc.id)
                            else:
                                print(f"NpcRestCompletionHandler: Warning: NPC {npc.id} health or max_health is not numeric ({npc.health}/{npc.max_health}). Cannot apply health recovery.")

                       # TODO: Apply mana/stamina recovery if applicable
                       # if 'mana' in recovery and hasattr(npc, 'mana') and hasattr(npc, 'max_mana'):
                       #      if isinstance(npc.mana, (int, float)) and isinstance(npc.max_mana, (int, float)):
                       #           npc.mana = min(npc.mana + recovery.get('mana', 0), npc.max_mana)
                       #           self._npc_manager._dirty_npcs.add(npc.id)
                       #      else: print(f"NpcRestCompletionHandler: Warning: NPC {npc.id} mana or max_mana is not numeric. Cannot apply mana recovery.")


                  # Remove fatigue statuses using StatusManager
                  # Assuming fatigue status type is 'Fatigue'. remove_status_effects_by_type needs target_id, target_type, type, kwargs
                  await self._status_manager.remove_status_effects_by_type('Fatigue', target_id=npc.id, target_type='NPC', **kwargs)

                  await _notify_gm(f"💤 NPC {npc.id}: Отдых завершен. Восстановлено: Здоровье={recovery.get('health', 0) if recovery else 0}...") # TODO: Сообщение о восстановлении

             except Exception as e:
                  print(f"NpcRestCompletionHandler: Error during rest recovery for NPC {npc.id}: {e}")
                  import traceback
                  print(traceback.format_exc())
                  await _notify_gm(f"❌ NPC {npc.id}: Ошибка при восстановлении после отдыха.")
        else:
             print(f"NpcRestCompletionHandler: Warning: Cannot complete rest action for NPC {npc.id}. RuleEngine or StatusManager not available or lacks method.")
             await _notify_gm(f"⚠️ NPC {npc.id}: Действие отдыха завершено, но обработчик восстановления недоступен.")


        # await _notify_gm(f"💤 NPC {npc.id}: Отдых завершен.") # Moved notification inside try/except

# End of NpcRestCompletionHandler class
