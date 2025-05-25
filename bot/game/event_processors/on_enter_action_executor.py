# bot/game/event_processors/on_enter_action_executor.py

import traceback
from typing import Any, List, Dict

# Тип для отправки сообщений
from typing import Callable, Awaitable, TYPE_CHECKING # Added TYPE_CHECKING
SendToChannelCallback = Callable[[str], Awaitable[Any]]

if TYPE_CHECKING:
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager

class OnEnterActionExecutor:
    """
    Обрабатывает выполнение списка действий (send_message, give_item и др.)
    для событий и результата проверок.
    """
    def __init__(
        self,
        npc_manager: "NpcManager",
        item_manager: "ItemManager",
        combat_manager: "CombatManager",
        status_manager: "StatusManager"
    ):
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager

    async def execute_actions(
        self,
        event,
        actions: List[Dict[str, Any]],
        **kwargs
    ):
        """
        Выполняет переданный список действий. Каждый action dict содержит:
        - type: str
        - data: dict
        """
        for action in actions:
            try:
                action_type = action.get('type')
                data = action.get('data', {})

                if action_type == 'send_message':
                    # data: {'content': '...'}, kwargs должен содержать send_message_callback
                    callback = kwargs.get('send_message_callback')
                    if callback:
                        await callback(data.get('content', ''))

                elif action_type == 'spawn_npc':
                    # data: {'npc_template_id': '...'}
                    npc_id = data.get('npc_template_id')
                    if self._npc_manager and npc_id:
                        await self._npc_manager.spawn_npc(npc_id)

                elif action_type == 'give_item':
                    # data: {'character_id': '...', 'item_template_id': '...'}
                    char_id = data.get('character_id')
                    item_tpl = data.get('item_template_id')
                    if self._item_manager and char_id and item_tpl:
                        await self._item_manager.give_item(char_id, item_tpl)

                elif action_type == 'start_combat':
                    # data: {'player_id': '...', 'npc_id': '...'}
                    player = data.get('player_id')
                    npc = data.get('npc_id')
                    if self._combat_manager and player and npc:
                        await self._combat_manager.initiate_combat(player, npc)

                elif action_type == 'apply_status':
                    # data: {'character_id': '...', 'status_id': '...'}
                    char_id = data.get('character_id')
                    status_id = data.get('status_id')
                    if self._status_manager and char_id and status_id:
                        await self._status_manager.apply_status(char_id, status_id)

                # Добавьте другие типы действий по необходимости

            except Exception as e:
                print(f"OnEnterActionExecutor: Error executing action {action}: {e}")
                traceback.print_exc()
