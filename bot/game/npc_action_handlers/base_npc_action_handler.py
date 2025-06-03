# bot/game/npc_action_handlers/base_npc_action_handler.py

from typing import Dict, Any, Awaitable, Callable # Import needed types

# Import models needed for type hints
from bot.game.models.npc import NPC

# Define send callback type here or import from a common place
SendToChannelCallback = Callable[[str], Awaitable[Any]]


class BaseNpcActionHandler:
    """
    Базовый класс для обработчиков завершения действий NPC.
    Определяет стандартный метод handle.
    """
    async def handle(self,
                     npc: NPC, # Объект NPC, чье действие завершилось
                     completed_action_data: Dict[str, Any], # Данные завершенного действия
                     # Передаем все необходимые менеджеры/сервисы через kwargs
                     # WorldSimulationProcessor -> NpcActionProcessor -> Handler
                     send_callback_factory: Callable[[int], SendToChannelCallback], # Фабрика для уведомлений (включая GM)
                     **kwargs # Остальные менеджеры/сервисы из kwargs WSP
                    ) -> None:
        """
        Обрабатывает логику завершения конкретного действия NPC.
        Должен быть переопределен в классах-наследниках.
        """
        raise NotImplementedError("Handler must implement the async handle method")

# End of BaseNpcActionHandler class
