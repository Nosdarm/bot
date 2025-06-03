# bot/game/event_processors/on_enter_action_executor.py

import traceback
from typing import Any, List, Dict

# Тип для отправки сообщений
from typing import Callable, Awaitable, TYPE_CHECKING, Optional # Added Optional

SendToChannelCallback = Callable[[str], Awaitable[Any]]

if TYPE_CHECKING:
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.character_manager import CharacterManager # Added for give_item
    from bot.game.models.event import Event # For type hint

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
        # CharacterManager will be passed in kwargs for execute_actions if needed by give_item
    ):
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager

    async def execute_actions(
        self,
        event: "Event", # Added type hint for event
        actions: List[Dict[str, Any]],
        **kwargs # Context including other managers, guild_id, etc.
    ):
        """
        Выполняет переданный список действий. Каждый action dict содержит:
        - type: str
        - data: dict (параметры для действия)
        kwargs содержит контекст, включая guild_id, character_id (если применимо), send_message_callback, и другие менеджеры.
        """
        for action in actions:
            try:
                action_type = action.get('type')
                data = action.get('data', {})

                guild_id = kwargs.get('guild_id') # Expect guild_id in context

                if action_type == 'send_message':
                    callback = kwargs.get('send_message_callback')
                    if callback:
                        await callback(data.get('content', ''))

                elif action_type == 'spawn_npc':
                    npc_template_id = data.get('npc_template_id')
                    # Location for NPC spawn could be event's location or specified in action data
                    location_id = data.get('location_id', event.location_id if hasattr(event, 'location_id') else None)

                    if self._npc_manager and npc_template_id and guild_id:
                        await self._npc_manager.create_npc( # Changed from spawn_npc
                            guild_id=str(guild_id),
                            npc_template_id=str(npc_template_id),
                            location_id=str(location_id) if location_id else None,
                            name=data.get('name'), # Optional name from action data
                            is_temporary=data.get('is_temporary', True), # NPCs spawned by events often temporary
                            event_id=event.id if hasattr(event, 'id') else None, # Pass event_id for context
                            **kwargs # Pass full context
                        )
                    elif not guild_id:
                        print(f"OnEnterActionExecutor: Missing guild_id for spawn_npc action. Event: {event.id if hasattr(event, 'id') else 'N/A'}")


                elif action_type == 'give_item':
                    character_id = data.get('character_id', kwargs.get('player_id')) # Target character
                    item_template_id = data.get('item_template_id')
                    quantity = data.get('quantity', 1)
                    character_manager: Optional["CharacterManager"] = kwargs.get('character_manager')

                    if self._item_manager and character_manager and character_id and item_template_id and guild_id:
                        # CharacterManager's add_item_to_inventory is more direct for giving items to players
                        success = await character_manager.add_item_to_inventory(
                            guild_id=str(guild_id),
                            character_id=str(character_id),
                            item_id=str(item_template_id), # This is template_id
                            quantity=int(quantity),
                            context=kwargs # Pass context which includes item_manager if needed by add_item_to_inventory indirectly
                        )
                        if success:
                            print(f"Item {item_template_id} x{quantity} given to character {character_id} via OnEnterAction.")
                        else:
                            print(f"Failed to give item {item_template_id} to character {character_id} via OnEnterAction.")
                    elif not guild_id:
                         print(f"OnEnterActionExecutor: Missing guild_id for give_item action. Event: {event.id if hasattr(event, 'id') else 'N/A'}")


                elif action_type == 'start_combat':
                    # Assuming player_id in data refers to the character initiating or primarily involved from player side
                    player_id = data.get('player_id', kwargs.get('player_id')) # ID of a player character
                    npc_id = data.get('npc_id') # ID of an NPC

                    location_id = event.location_id if hasattr(event, 'location_id') else None
                    channel_id = event.channel_id if hasattr(event, 'channel_id') else None

                    if self._combat_manager and player_id and npc_id and guild_id and location_id and channel_id:
                        participants = [
                            (str(player_id), "Character"),
                            (str(npc_id), "NPC")
                        ]
                        await self._combat_manager.start_combat( # Changed from initiate_combat
                            guild_id=str(guild_id),
                            location_id=str(location_id),
                            participant_ids_types=participants,
                            channel_id=int(channel_id),
                            event_id=event.id if hasattr(event, 'id') else None, # Link combat to event
                            **kwargs # Pass full context
                        )
                    elif not guild_id:
                        print(f"OnEnterActionExecutor: Missing guild_id for start_combat action. Event: {event.id if hasattr(event, 'id') else 'N/A'}")
                    elif not location_id:
                        print(f"OnEnterActionExecutor: Missing location_id for start_combat action. Event: {event.id if hasattr(event, 'id') else 'N/A'}")
                    elif not channel_id:
                         print(f"OnEnterActionExecutor: Missing channel_id for start_combat action. Event: {event.id if hasattr(event, 'id') else 'N/A'}")


                elif action_type == 'apply_status_effect': # Renamed from apply_status for clarity
                    target_id = data.get('target_id', kwargs.get('player_id')) # Target of the status
                    target_type = data.get('target_type', "Character") # Default to Character if not specified
                    status_type = data.get('status_type', data.get('status_id')) # status_id is old name
                    duration = data.get('duration') # Optional duration

                    if self._status_manager and target_id and status_type and guild_id:
                        await self._status_manager.add_status_effect_to_entity( # Changed from apply_status
                            target_id=str(target_id),
                            target_type=str(target_type),
                            status_type=str(status_type),
                            duration=float(duration) if duration is not None else None,
                            guild_id=str(guild_id),
                            source_id=event.id if hasattr(event, 'id') else "event_action",
                            initial_state_vars=data.get('state_variables'), # Optional state vars for status
                            **kwargs # Pass context
                        )
                    elif not guild_id:
                         print(f"OnEnterActionExecutor: Missing guild_id for apply_status_effect action. Event: {event.id if hasattr(event, 'id') else 'N/A'}")

                # Добавьте другие типы действий по необходимости

            except Exception as e:
                print(f"OnEnterActionExecutor: Error executing action {action}: {e}")
                traceback.print_exc()
