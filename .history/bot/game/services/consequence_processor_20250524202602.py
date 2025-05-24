# bot/game/services/consequence_processor.py

from __future__ import annotations
import traceback
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Callable, Awaitable

if TYPE_CHECKING:
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.managers.status_manager import StatusManager
    # from bot.game.managers.dialogue_manager import DialogueManager # If needed for dialogue consequences
    # from bot.game.managers.combat_manager import CombatManager # If needed for combat consequences
    from bot.game.game_state import GameState

    # Define a type for custom function callbacks if they are complex
    CustomFunctionCallback = Callable[[GameState, Dict[str, Any]], Awaitable[None]]


class ConsequenceProcessor:
    """
    Processes various types of consequences that can occur in the game,
    affecting characters, NPCs, items, locations, events, or quests.
    """

    def __init__(
        self,
        character_manager: CharacterManager,
        npc_manager: NpcManager,
        item_manager: ItemManager,
        location_manager: LocationManager,
        event_manager: EventManager,
        quest_manager: QuestManager,
        status_manager: StatusManager,
        # dialogue_manager: Optional[DialogueManager] = None, # Add if dialogue consequences are handled
        # combat_manager: Optional[CombatManager] = None, # Add if combat consequences are handled
        game_state: Optional[GameState] = None # For global state or complex interactions
    ):
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._event_manager = event_manager
        self._quest_manager = quest_manager
        self._status_manager = status_manager
        # self._dialogue_manager = dialogue_manager
        # self._combat_manager = combat_manager
        self._game_state = game_state # Provides access to guild_id and other managers if needed

        # A registry for custom functions if you want to make it extensible
        self._custom_functions: Dict[str, CustomFunctionCallback] = {}
        print("ConsequenceProcessor initialized.")

    def register_custom_function(self, name: str, func: CustomFunctionCallback) -> None:
        """Registers a custom consequence function."""
        if name in self._custom_functions:
            print(f"Warning: Overwriting custom consequence function '{name}'.")
        self._custom_functions[name] = func
        print(f"Custom consequence function '{name}' registered.")

    async def process_consequences(
        self,
        guild_id: str,
        consequences: List[Dict[str, Any]],
        source_entity_id: Optional[str] = None, # e.g., NPC causing the consequence
        target_entity_id: Optional[str] = None, # e.g., Character affected
        event_context: Optional[Dict[str, Any]] = None, # Context from an event or action
        send_callback_factory: Optional[Callable[[int], Callable[[str], Awaitable[None]]]] = None
    ) -> None:
        """
        Processes a list of consequence dictionaries.

        Args:
            guild_id: The ID of the guild where consequences occur.
            consequences: A list of dictionaries, each defining a consequence.
                          Example: {'action_type': 'ADD_ITEM_TO_CHARACTER', 'item_template_id': 'sword', 'character_id': 'char123', 'quantity': 1}
            source_entity_id: Optional ID of the entity that is the source of these consequences.
            target_entity_id: Optional ID of the primary entity targeted by these consequences.
                              This can be overridden by 'character_id', 'npc_id' etc. within a consequence.
            event_context: Optional dictionary providing context from the event or action triggering these consequences.
            send_callback_factory: Optional factory to create send_message callbacks for specific channels.
        """
        if not consequences:
            return

        print(f"ConsequenceProcessor: Processing {len(consequences)} consequences for guild {guild_id}.")

        for i, cons in enumerate(consequences):
            action_type = cons.get('action_type')
            if not action_type:
                print(f"Warning: Consequence {i+1} missing 'action_type'. Skipping: {cons}")
                continue

            # Resolve target_id: use specific ID from consequence, fallback to primary target_entity_id
            # This helps direct consequences correctly when a list has mixed targets.
            current_target_id = cons.get('character_id') or cons.get('npc_id') or cons.get('entity_id') or target_entity_id

            print(f"ConsequenceProcessor: Executing consequence {i+1}/{len(consequences)}: {action_type} for target '{current_target_id}' (Source: '{source_entity_id}')")

            try:
                if action_type == "MODIFY_NPC_STATS":
                    npc_id = cons.get('npc_id', current_target_id)
                    stats_changes = cons.get('stats_changes') # {'health': -10, 'mana': 5}
                    if npc_id and stats_changes:
                        await self._npc_manager.modify_npc_stats(guild_id, npc_id, stats_changes)
                    else:
                        print(f"Warning: Missing npc_id or stats_changes for MODIFY_NPC_STATS: {cons}")

                elif action_type == "MODIFY_CHARACTER_STATS":
                    char_id = cons.get('character_id', current_target_id)
                    stats_changes = cons.get('stats_changes')
                    if char_id and stats_changes:
                        await self._character_manager.modify_character_stats(guild_id, char_id, stats_changes)
                    else:
                        print(f"Warning: Missing character_id or stats_changes for MODIFY_CHARACTER_STATS: {cons}")

                elif action_type == "ADD_ITEM_TO_CHARACTER":
                    char_id = cons.get('character_id', current_target_id)
                    item_template_id = cons.get('item_template_id')
                    quantity = cons.get('quantity', 1.0) # Default to 1.0 as items use REAL for quantity
                    state_vars = cons.get('state_variables', {})
                    if char_id and item_template_id:
                        await self._item_manager.give_item_to_character(guild_id, char_id, item_template_id, quantity, state_vars)
                    else:
                        print(f"Warning: Missing character_id or item_template_id for ADD_ITEM_TO_CHARACTER: {cons}")

                elif action_type == "REMOVE_ITEM_FROM_CHARACTER":
                    char_id = cons.get('character_id', current_target_id)
                    item_id_or_template_id = cons.get('item_id') or cons.get('item_template_id')
                    quantity = cons.get('quantity', 1.0)
                    if char_id and item_id_or_template_id:
                        # Determine if removing by specific instance ID or by template ID
                        if cons.get('item_id'):
                             await self._item_manager.remove_item_from_character_by_instance_id(guild_id, char_id, cons.get('item_id'), quantity)
                        else: # by template_id
                             await self._item_manager.remove_item_from_character_by_template_id(guild_id, char_id, cons.get('item_template_id'), quantity)
                    else:
                        print(f"Warning: Missing character_id or item_id/item_template_id for REMOVE_ITEM_FROM_CHARACTER: {cons}")

                elif action_type == "CHANGE_LOCATION":
                    entity_id = cons.get('entity_id', current_target_id) # Can be character or NPC
                    entity_type = cons.get('entity_type') # 'character' or 'npc'
                    new_location_id = cons.get('new_location_id')
                    if entity_id and entity_type and new_location_id:
                        if entity_type.lower() == 'character':
                            await self._character_manager.move_character_to_location(guild_id, entity_id, new_location_id)
                        elif entity_type.lower() == 'npc':
                            await self._npc_manager.move_npc_to_location(guild_id, entity_id, new_location_id)
                        else:
                            print(f"Warning: Unknown entity_type '{entity_type}' for CHANGE_LOCATION: {cons}")
                    else:
                        print(f"Warning: Missing entity_id, entity_type, or new_location_id for CHANGE_LOCATION: {cons}")

                elif action_type == "START_EVENT":
                    event_template_id = cons.get('event_template_id')
                    channel_id = cons.get('channel_id') # Optional, might come from context
                    involved_character_ids = cons.get('character_ids', [])
                    involved_npc_ids = cons.get('npc_ids', [])
                    initial_state = cons.get('initial_state', {})

                    if event_template_id:
                        # Ensure involved_character_ids has the primary target if applicable
                        if current_target_id and current_target_id not in involved_character_ids and self._character_manager.get_character(guild_id, current_target_id):
                             involved_character_ids.append(current_target_id)

                        await self._event_manager.start_event(
                            guild_id=guild_id,
                            event_template_id=event_template_id,
                            channel_id=channel_id, # Needs a valid channel
                            involved_character_ids=involved_character_ids,
                            involved_npc_ids=involved_npc_ids,
                            initial_state_data=initial_state,
                            send_callback_factory=send_callback_factory # Pass this down
                        )
                    else:
                        print(f"Warning: Missing event_template_id for START_EVENT: {cons}")

                elif action_type == "UPDATE_QUEST_STATE":
                    quest_id = cons.get('quest_id')
                    character_id = cons.get('character_id', current_target_id)
                    new_stage_id = cons.get('new_stage_id')
                    objective_updates = cons.get('objective_updates') # e.g., {'kill_goblins': {'increment': 5}}
                    is_completed = cons.get('is_completed')
                    is_failed = cons.get('is_failed')

                    if quest_id and character_id:
                        await self._quest_manager.update_quest_progress(
                            guild_id=guild_id,
                            character_id=character_id,
                            quest_id=quest_id,
                            new_stage_id=new_stage_id,
                            objective_updates=objective_updates,
                            completed=is_completed,
                            failed=is_failed
                        )
                    else:
                        print(f"Warning: Missing quest_id or character_id for UPDATE_QUEST_STATE: {cons}")

                elif action_type == "APPLY_STATUS_EFFECT":
                    target_id = cons.get('target_id', current_target_id)
                    target_type = cons.get('target_type') # 'character', 'npc', 'party', 'location'
                    status_type = cons.get('status_type')
                    duration = cons.get('duration') # Optional, in game seconds
                    source_id = cons.get('source_id', source_entity_id)
                    status_state_vars = cons.get('state_variables', {})

                    if target_id and target_type and status_type:
                        await self._status_manager.apply_status_effect(
                            guild_id=guild_id,
                            target_id=target_id,
                            target_type=target_type,
                            status_type=status_type,
                            duration=duration,
                            source_id=source_id,
                            state_variables=status_state_vars
                        )
                    else:
                        print(f"Warning: Missing target_id, target_type, or status_type for APPLY_STATUS_EFFECT: {cons}")

                elif action_type == "CUSTOM_FUNCTION":
                    func_name = cons.get('function_name')
                    params = cons.get('params', {})
                    if func_name and func_name in self._custom_functions:
                        # Ensure GameState is passed if the custom function expects it
                        # This example assumes GameState might not always be available or needed
                        # but if it is, it should be passed from self._game_state
                        gs = self._game_state
                        if not gs:
                             print(f"Warning: GameState not available for CUSTOM_FUNCTION '{func_name}'. Some operations might fail.")
                        # We might need to pass more context to custom functions
                        full_params = {
                            **params,
                            'guild_id': guild_id,
                            'source_entity_id': source_entity_id,
                            'target_entity_id': current_target_id, # current_target_id is better here
                            'event_context': event_context,
                            'send_callback_factory': send_callback_factory
                        }
                        await self._custom_functions[func_name](gs, full_params)
                    elif func_name:
                        print(f"Warning: Custom function '{func_name}' not registered. Skipping.")
                    else:
                        print(f"Warning: Missing function_name for CUSTOM_FUNCTION: {cons}")

                # Add more consequence types here
                # elif action_type == "START_DIALOGUE":
                #     # Requires DialogueManager
                #     pass
                # elif action_type == "TRIGGER_COMBAT":
                #     # Requires CombatManager
                #     pass

                else:
                    print(f"Warning: Unknown action_type '{action_type}'. Skipping: {cons}")

            except Exception as e:
                print(f"Error processing consequence: {cons}")
                print(f"Exception: {e}")
                traceback.print_exc()
        print(f"ConsequenceProcessor: Finished processing consequences for guild {guild_id}.")

    async def _placeholder_send_message(self, message: str) -> None:
        """Placeholder for sending messages if no callback is provided."""
        print(f"[ConsequenceProcessor Send (Placeholder)] {message}")
