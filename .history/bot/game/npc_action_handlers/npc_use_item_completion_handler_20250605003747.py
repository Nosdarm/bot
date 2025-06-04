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
                    # RuleEngine.resolve_item_use returns a Dict.
                    # Signature: resolve_item_use(self, character: Character, item_instance_data: Dict[str, Any], target_entity: Optional[Any], context: Dict[str, Any]) -> Dict[str, Any]
                    # NPC is passed as 'character' argument.
                    # item_obj here is item_instance_data.

                    # Ensure guild_id is in context for resolve_item_use if it needs it internally
                    context_for_resolve = {**kwargs, 'guild_id': getattr(npc, 'guild_id', kwargs.get('guild_id'))}

                    effect_result_dict = await self._rule_engine.resolve_item_use(
                        character=npc, # Pass NPC as the 'character'
                        item_instance_data=item_obj,
                        target_entity=target_obj,
                        context=context_for_resolve
                    )

                    # Process effect_result_dict (which includes success, message, consumed, effects)
                    if effect_result_dict.get("success"):
                        print(f"NpcUseItemCompletionHandler: NPC {npc.id} used item {item_id} ({item_obj.get('template_id', 'N/A')}) on {target_type} {target_id}. Effect: {effect_result_dict.get('message')}")
                        # TODO: Apply effects from effect_result_dict.get('effects') if any.
                        # This would involve StatusManager, CharacterManager/NpcManager for stat changes etc.
                        # Example:
                        # for effect_detail in effect_result_dict.get('effects', []):
                        #    if effect_detail.get('type') == 'heal' and self._status_manager:
                        #        # apply healing via status manager or directly modifying target_obj.hp
                        #        pass
                        #    elif effect_detail.get('type') == 'status' and self._status_manager:
                        #        # await self._status_manager.add_status_effect_to_entity(...)
                        #        pass

                        item_consumed = effect_result_dict.get('consumed', True)
                        if item_consumed:
                            success_remove = await self._npc_manager.remove_item_from_inventory(npc.id, item_id, **kwargs)
                            if success_remove:
                                await _notify_gm(f"✨ NPC {npc.id}: Использовал предмет {item_obj.get('template_id', item_id)} на {target_id} (потреблен). {effect_result_dict.get('message', '')}")
                            else:
                                await _notify_gm(f"❌ NPC {npc.id}: Использовал предмет {item_obj.get('template_id', item_id)}, но не удалось удалить из инвентаря. {effect_result_dict.get('message', '')}")
                        else:
                            await _notify_gm(f"💡 NPC {npc.id}: Использовал предмет {item_obj.get('template_id', item_id)} (не потреблен) на {target_id}. {effect_result_dict.get('message', '')}")
                    else: # resolve_item_use returned success: False
                        await _notify_gm(f"⚠️ NPC {npc.id}: Не удалось использовать предмет {item_obj.get('template_id', item_id)}. {effect_result_dict.get('message', '')}")

                elif not item_obj: # This check was already present
                    print(f"NpcUseItemCompletionHandler: Error completing use_item action: Item object {item_id} not found for NPC {npc.id}.")
                    await _notify_gm(f"❌ NPC {npc.id}: Ошибка при завершении use_item: Предмет {item_id} не найден.")
                # Removed the specific check for target_obj here as resolve_item_use might handle targetless items.
                # The original 'else' for RuleEngine method not available is covered if hasattr fails.

            except Exception as e:
                print(f"NpcUseItemCompletionHandler: Error during NPC use_item action completion for {npc.id}: {e}")
                import traceback
                print(traceback.format_exc())
                await _notify_gm(f"❌ NPC {npc.id}: Ошибка при завершении use_item.")

        else:
            print(f"NpcUseItemCompletionHandler: Warning: Cannot complete use_item action for NPC {npc.id}. Required managers/methods not available.")
            await _notify_gm(f"⚠️ NPC {npc.id}: Действие use_item завершено, но обработчик недоступен.")

# End of NpcUseItemCompletionHandler class
