# bot/game/event_processors/event_action_processor.py

# EventActionProcessor: Handles player commands/actions directed at an active event.
# Finds the relevant action in the event stage definition.
# Performs basic action processing (validation, effects).
# If the action triggers a stage change (via outcome_stage_id), calls EventStageProcessor.
# Called by the GameManager when a player command is routed to an event.

import json
import traceback
from typing import Dict, Optional, Any, List, Callable, Awaitable, TYPE_CHECKING, Set, Tuple

# --- Define Type Aliases ---
# Corrected alias for send message callback function signature
# This callback is assumed to be the one returned by send_callback_factory(channel_id)
# It takes the message string and optional data, and is awaitable.
SendChannelMessageCallback = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]

# SendCallbackFactory defined below (uses SendChannelMessageCallback)


# --- Imports needed ONLY for Type Checking ---
# Эти импорты игнорируются Python при runtime, помогая разорвать циклы импорта.
# Используйте строковые литералы ("ClassName") для type hints в __init__ и методах
# для классов, импортированных здесь.
if TYPE_CHECKING:
    # Models (needed for type hints or instance checks if they cause cycles elsewhere)
    from bot.game.models.event import Event, EventStage
    from bot.game.models.character import Character
    from bot.game.models.npc import NPC
    from bot.game.models.party import Party
    from bot.game.models.combat import Combat
    # TODO: Import other models if used in type hints and cause cycles
    # from bot.game.models.item import Item

    # Managers and Services
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.event_manager import EventManager # To retrieve the event object
    from bot.game.managers.location_manager import LocationManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.services.openai_service import OpenAIService
    # Optional Managers
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.crafting_manager import CraftingManager

    # Other Processors (needed for type hints in signatures)
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor # If needed in signatures


# --- Imports needed at Runtime ---
# These are minimal and typically limited to base types, models needed for isinstance,
# or utility modules (json, uuid, traceback).
# Managers and Processors should generally NOT be imported here if they are received via injection,
# to avoid circular dependency issues.

# Import Models needed for isinstance checks at runtime or static method calls
from bot.game.models.character import Character # Need for isinstance checks (e.g. in _check_skill_check)
# Added runtime import for Event and EventStage if EventStage.from_dict is used or isinstance(event, Event)
from bot.game.models.event import Event, EventStage # Need Event for isinstance check, EventStage for from_dict


# Define SendCallbackFactory here as it uses SendChannelMessageCallback which is defined above
SendCallbackFactory = Callable[[int], SendChannelMessageCallback]


print("DEBUG: event_action_processor.py module loading...")


class EventActionProcessor:
    """
    Процессор, отвечающий за обработку команд игроков внутри контекста активного события.
    """
    # Define required args for persistence (if applicable for this processor)
    # required_args_for_load = [] # Add if load_state requires args
    # required_args_for_save = [] # Add if save_state requires args

    def __init__(self,
                 # --- Обязательные зависимости ---
                 # Используем строковые литералы для инжектированных зависимостей
                 event_stage_processor: "EventStageProcessor",
                 event_manager: "EventManager",
                 character_manager: "CharacterManager",
                 loc_manager: "LocationManager",
                 rule_engine: "RuleEngine",
                 openai_service: Optional["OpenAIService"], # Optional Service
                 # send_callback_factory - теперь обязательный аргумент для инициализации
                 send_callback_factory: SendCallbackFactory, # Factory for callbacks (Callable type)

                 # --- Опциональные зависимости ---
                 # Используйте строковые литералы для Optional зависимостей
                 npc_manager: Optional["NpcManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                 item_manager: Optional["ItemManager"] = None,
                 time_manager: Optional["TimeManager"] = None,
                 status_manager: Optional["StatusManager"] = None,
                 party_manager: Optional["PartyManager"] = None,
                 economy_manager: Optional["EconomyManager"] = None,
                 dialogue_manager: Optional["DialogueManager"] = None,
                 crafting_manager: Optional["CraftingManager"] = None,

                 # TODO: Добавьте другие зависимости
                 on_enter_action_executor: Optional["OnEnterActionExecutor"] = None,
                 stage_description_generator: Optional["StageDescriptionGenerator"] = None,
                 character_action_processor: Optional["CharacterActionProcessor"] = None,


                ):
        print("Initializing EventActionProcessor...")

        # --- Сохранение переданных зависимостей ---
        self._event_stage_processor = event_stage_processor
        self._event_manager = event_manager
        self._character_manager = character_manager
        self._loc_manager = loc_manager
        self._rule_engine = rule_engine
        self._openai_service = openai_service
        self._send_callback_factory = send_callback_factory # Save the factory

        # Сохраняем опциональные менеджеры
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._item_manager = item_manager
        self._time_manager = time_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._economy_manager = economy_manager
        self._dialogue_manager = dialogue_manager
        self._crafting_manager = crafting_manager

        # Сохраняем опциональные процессоры
        self._on_enter_action_executor = on_enter_action_executor
        self._stage_description_generator = stage_description_generator
        self._character_action_processor = character_action_processor


        print("EventActionProcessor initialized.")


    # --- Method to process a player's command within an event context ---
    # Called by the GameManager or CommandRouter. Receives event ID, player ID, command, args, and ALL dependencies via **kwargs.
    # send_message_callback will be obtained from send_callback_factory using channel_id
    async def process_player_action(self,
                                    event_id: str, # ID события, к которому относится действие
                                    player_id: str, # ID персонажа, выполняющего действие
                                    command_keyword: str, # Ключевое слово команды игрока (например, 'investigate')
                                    command_args: List[str], # Аргументы команды игрока
                                    # ВСЕ зависимости и контекст ПЕРЕДАЮТСЯ ЧЕРЕЗ **kwargs!
                                    **kwargs: Any # Catch all other arguments (managers, callbacks, context)
                                   ) -> Dict[str, Any]:
        """
        Обрабатывает команду игрока внутри контекста активного события.
        Returns a dictionary: {"stage_transitioned": bool, "message": Optional[str], "modified_entities": List[Any]}
        """
        print(f"EventActionProcessor: processing player '{player_id}' action '{command_keyword}' for event {event_id} with args {command_args}...")

        modified_entities: List[Any] = []
        return_message: Optional[str] = None
        stage_transitioned: bool = False

        # --- Get dependencies from kwargs or self attributes ---
        # Prioritize kwargs (allows passing specific instances for a call)
        # Use _inst suffix for clarity within this method
        event_manager_inst = kwargs.get('event_manager', self._event_manager) # type: Optional["EventManager"]
        character_manager_inst = kwargs.get('character_manager', self._character_manager) # type: Optional["CharacterManager"]
        loc_manager_inst = kwargs.get('loc_manager', self._loc_manager) # type: Optional["LocationManager"]
        rule_engine_inst = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]
        send_callback_factory_inst = kwargs.get('send_callback_factory', self._send_callback_factory) # type: Optional[SendCallbackFactory]

        # Get optional dependencies and context from kwargs or self
        # Use _inst suffix if these variables are used directly later, otherwise can get from context dict
        # openai_service_inst = kwargs.get('openai_service', self._openai_service) # Example

        # Also get channel_id from kwargs early, as event might not be found initially
        channel_id_from_kwargs = kwargs.get('channel_id')


        # --- Check essential dependencies are present ---
        # This check *must* happen on the _inst variables retrieved above
        # Ensure guild_id is available from context before fetching event
        guild_id_from_context = kwargs.get('guild_id') # Attempt to get guild_id from kwargs first

        if event_manager_inst is None or character_manager_inst is None or loc_manager_inst is None or rule_engine_inst is None or send_callback_factory_inst is None or guild_id_from_context is None:
             # Collect names of missing dependencies
             missing_deps = [name for name, dep in [
                 ('event_manager', event_manager_inst),
                 ('character_manager', character_manager_inst),
                 ('loc_manager', loc_manager_inst),
                 ('rule_engine', rule_engine_inst),
                 ('send_callback_factory', send_callback_factory_inst)
                 ] if dep is None]

             print(f"EventActionProcessor Error: Missing essential dependencies for process_player_action: {', '.join(missing_deps)}.")
             error_message = f"❌ Системная ошибка: Не удалось обработать команду. Отсутствуют ключевые компоненты: {', '.join(missing_deps)}."
             if channel_id_from_kwargs is not None and send_callback_factory_inst is not None:
                  try:
                       send_cb = send_callback_factory_inst(channel_id_from_kwargs)
                       await send_cb(error_message, None)
                  except Exception as cb_e:
                       print(f"EventActionProcessor Error sending initial error message: {cb_e}")
             elif send_callback_factory_inst is None:
                   print(f"EventActionProcessor Warning: Cannot send initial error message because send_callback_factory is missing.")
             elif channel_id_from_kwargs is None:
                  print(f"EventActionProcessor Warning: Cannot send initial error message because channel_id missing from kwargs.")
             return {"stage_transitioned": False, "message": error_message, "modified_entities": modified_entities}

        # --- Now that essential dependencies are confirmed, proceed using _inst variables ---
        # guild_id_from_context is confirmed not None here
        guild_id = str(guild_id_from_context) # Ensure it's a string

        event: Optional["Event"] = event_manager_inst.get_event(guild_id=guild_id, event_id=event_id) # Added guild_id
        if not event:
             print(f"EventActionProcessor Error: Event {event_id} not found for player action in guild {guild_id}.") # Added guild_id to log
             channel_id_for_error = channel_id_from_kwargs
             return_message = "❌ Ошибка: Событие не найдено."
             if channel_id_for_error is not None:
                 try:
                      send_cb = send_callback_factory_inst(channel_id_for_error)
                      await send_cb(return_message, None);
                 except Exception as cb_e: print(f"EventActionProcessor Error sending error message: {cb_e}");
             return {"stage_transitioned": False, "message": return_message, "modified_entities": modified_entities}

        guild_id = event.guild_id
        player_character = character_manager_inst.get_character(guild_id, player_id)
        if not player_character:
             print(f"EventActionProcessor Error: Player character {player_id} not found for event {event_id} in guild {guild_id}.")
             channel_id_for_error = event.channel_id
             return_message = "❌ Ошибка: Ваш персонаж не найден."
             if channel_id_for_error is not None:
                  try:
                      send_cb = send_callback_factory_inst(channel_id_for_error)
                      await send_cb(return_message, None);
                  except Exception as cb_e: print(f"EventActionProcessor Error sending error message: {cb_e}");
             return {"stage_transitioned": False, "message": return_message, "modified_entities": modified_entities}

        if event.channel_id is None:
             print(f"EventActionProcessor Error: Event {event.id} has no channel_id. Cannot send messages.")
             channel_id_for_error = channel_id_from_kwargs
             return_message = "❌ Ошибка: Событие не привязано к каналу для отправки сообщений."
             if channel_id_for_error is not None:
                 try:
                     send_cb = send_callback_factory_inst(channel_id_for_error)
                     await send_cb(return_message, None);
                 except Exception as cb_e: print(f"EventActionProcessor Error sending error message: {cb_e}");
             return {"stage_transitioned": False, "message": return_message, "modified_entities": modified_entities}

        send_message_callback = send_callback_factory_inst(event.channel_id)

        # Get current stage data from the event object
        current_stage_id = event.current_stage_id
        current_stage_data = event.stages_data.get(current_stage_id)

        if not current_stage_data:
             print(f"EventActionProcessor Error: Stage '{current_stage_id}' not found in event {event_id} data.")
             return_message = f"❌ Ошибка: Данные текущей стадии '{current_stage_id}' не найдены в событии."
             try: await send_message_callback(return_message, None);
             except Exception as cb_e: print(f"EventActionProcessor Error sending error message: {cb_e}");
             return {"stage_transitioned": False, "message": return_message, "modified_entities": modified_entities}

        try:
             current_stage: "EventStage" = EventStage.from_dict(current_stage_data)
             using_event_stage_object = True
        except (NameError, ImportError, TypeError) as e:
             print(f"EventActionProcessor Warning: EventStage model not available or from_dict failed ({e}). Working with raw stage data dictionary.")
             current_stage = current_stage_data
             using_event_stage_object = False

        allowed_actions_list = getattr(current_stage, 'allowed_actions', []) if using_event_stage_object else current_stage.get('allowed_actions', [])
        target_action_definition: Optional[Dict[str, Any]] = None
        current_stage_name = getattr(current_stage, 'name', current_stage_id) if using_event_stage_object else current_stage.get('name', current_stage_id)

        print(f"EventActionProcessor: Searching stage '{current_stage_name}' ({current_stage_id}) for command '{command_keyword}'...")

        for action_def in allowed_actions_list:
            if isinstance(action_def, dict) and action_def.get('command', '').lower() == command_keyword.lower():
                target_action_definition = action_def
                print(f"EventActionProcessor: Found potential action match for command '{command_keyword}'.")
                break

        if not target_action_definition:
             print(f"EventActionProcessor: Player action command '{command_keyword}' not found or not allowed in stage '{current_stage_name}' for event {event_id}.")
             event_name = getattr(event, 'name', event_id) if isinstance(event, Event) else event_id
             return_message = f"Действие `{command_keyword}` недоступно на текущей стадии **{event_name}** ('{current_stage_name}') или введено неверно для этой стадии."
             try: await send_message_callback(return_message, None);
             except Exception as cb_e: print(f"EventActionProcessor Error sending feedback message: {cb_e}");
             return {"stage_transitioned": False, "message": return_message, "modified_entities": modified_entities}

        # --- Execute the found action ---
        action_type = target_action_definition.get('type')
        action_params = target_action_definition.get('params', {})

        player_character_name = getattr(player_character, 'name', 'Unknown')
        print(f"EventActionProcessor: Executing player action type '{action_type}' for player '{player_character_name}'...")

        action_execution_outcome: str = "success"

        # Placeholder for results from action execution helpers
        action_helper_results: Dict[str, Any] = {}

        action_execution_context: Dict[str, Any] = {
             'event_manager': event_manager_inst,
             'character_manager': character_manager_inst,
             'loc_manager': loc_manager_inst, 'location_manager': loc_manager_inst,
             'rule_engine': rule_engine_inst,
             'openai_service': kwargs.get('openai_service', self._openai_service),
             'send_message_callback': send_message_callback,
             'send_callback_factory': send_callback_factory_inst,

             'npc_manager': kwargs.get('npc_manager', self._npc_manager),
             'combat_manager': kwargs.get('combat_manager', self._combat_manager),
             'item_manager': kwargs.get('item_manager', self._item_manager),
             'time_manager': kwargs.get('time_manager', self._time_manager),
             'status_manager': kwargs.get('status_manager', self._status_manager),
             'party_manager': kwargs.get('party_manager', self._party_manager),
             'economy_manager': kwargs.get('economy_manager', self._economy_manager),
             'dialogue_manager': kwargs.get('dialogue_manager', self._dialogue_manager),
             'crafting_manager': kwargs.get('crafting_manager', self._crafting_manager),

             'event_stage_processor': kwargs.get('event_stage_processor', self._event_stage_processor),
             'on_enter_action_executor': kwargs.get('on_enter_action_executor', self._on_enter_action_executor),
             'stage_description_generator': kwargs.get('stage_description_generator', self._stage_description_generator),
             'character_action_processor': kwargs.get('character_action_processor', self._character_action_processor),

             'event': event,
             'player_character': player_character,
             'player_id': player_id,
             'guild_id': guild_id,
             'current_stage_id': current_stage_id,
             'current_stage_data': current_stage_data,
             'command_keyword': command_keyword,
             'command_args': command_args,
             'action_data': target_action_definition,
             'action_params': action_params,
             'channel_id': channel_id_from_kwargs,
        }
        action_execution_context.update(kwargs)

        # --- Action Execution Logic (Placeholder) ---
        # This is where you'd call specific helper methods based on action_type
        # e.g., if action_type == "skill_check_event":
        #   action_helper_results = await self._execute_skill_check_for_event(action_execution_context)
        #   action_execution_outcome = action_helper_results.get("outcome_keyword", "failure")
        #   modified_entities.extend(action_helper_results.get("modified_entities", []))
        #   return_message = action_helper_results.get("message_to_player")

        if action_type == 'simple_transition':
            action_execution_outcome = 'success' # Triggers the transition defined in outcome_stage_id
            return_message = action_params.get("success_message", f"Действие '{command_keyword}' выполнено.")
            print(f"EventActionProcessor: Action type '{action_type}' has outcome '{action_execution_outcome}'.")
            # If simple_transition itself modifies something (e.g. event state_variables), it should be handled here
            # and the modified event object added to modified_entities.
            # For now, assume simple_transition only transitions.
            if event not in modified_entities: modified_entities.append(event) # Event state might be considered modified by action
        elif action_type is None:
             print(f"EventActionProcessor Warning: Action '{command_keyword}' has no defined 'type'. Assuming simple success outcome for transition purposes.")
             action_execution_outcome = 'success'
             return_message = f"Действие '{command_keyword}' выполнено (нет типа)."
             if event not in modified_entities: modified_entities.append(event)
        else:
            # For other action types, you'd have specific logic.
            # For now, just a placeholder:
            print(f"EventActionProcessor: Action type '{action_type}' executed (placeholder logic).")
            action_execution_outcome = "success" # Default for unknown actions for now
            return_message = f"Действие '{command_keyword}' (тип: {action_type}) выполнено."
            # Assume the action might have modified the player_character or the event itself.
            # These are added as they are part of the action context.
            if player_character and player_character not in modified_entities: modified_entities.append(player_character)
            if event and event not in modified_entities: modified_entities.append(event)

            # Example: If an action directly calls a rule_engine method that returns modified entities
            # if action_type == "trigger_complex_effect_event":
            #    complex_effect_result = await rule_engine_inst.some_complex_effect(
            #        character=player_character,
            #        event=event,
            #        guild_id=guild_id,
            #        **action_execution_context
            #    ) # Assuming this method exists and returns a dict with 'modified_entities'
            #    action_execution_outcome = complex_effect_result.get("outcome_keyword", "failure")
            #    return_message = complex_effect_result.get("message_to_player")
            #    entities_from_effect = complex_effect_result.get("modified_entities", [])
            #    for entity in entities_from_effect:
            #        if entity not in modified_entities:
            #            modified_entities.append(entity)


        # --- Determine Stage Transition ---
        outcome_stage_id_def: Optional[Any] = target_action_definition.get('outcome_stage_id')
        determined_next_stage_id: Optional[str] = None

        if isinstance(outcome_stage_id_def, str) and outcome_stage_id_def:
             determined_next_stage_id = outcome_stage_id_def
             print(f"Action defines a simple transition to '{determined_next_stage_id}'.")
        elif isinstance(outcome_stage_id_def, dict):
             determined_next_stage_id = outcome_stage_id_def.get(action_execution_outcome)
             print(f"Action defines outcome-based transition. Outcome '{action_execution_outcome}' maps to stage '{determined_next_stage_id}'.")

        event_stage_processor_inst = action_execution_context.get('event_stage_processor')
        if isinstance(determined_next_stage_id, str) and determined_next_stage_id and determined_next_stage_id != current_stage_id and \
           event_stage_processor_inst and hasattr(event_stage_processor_inst, 'advance_stage'):
             print(f"EventActionProcessor: Player action '{command_keyword}' triggers transition to stage '{determined_next_stage_id}'.")

             # advance_stage should also return a dict with "modified_entities"
             advance_result = await event_stage_processor_inst.advance_stage(
                 event=event,
                 target_stage_id=determined_next_stage_id,
                 **action_execution_context
             )
             stage_transitioned = True
             # Assuming advance_stage returns a dict like {"message": str, "modified_entities": List[Any]}
             # If it modifies entities (e.g. the event itself, or entities due to on-enter actions)
             if isinstance(advance_result, dict):
                 modified_from_advance = advance_result.get("modified_entities", [])
                 modified_entities.extend(entity for entity in modified_from_advance if entity not in modified_entities)
                 # Message from advance_stage might be more relevant or could be combined
                 # return_message = advance_result.get("message_to_player", return_message) # Or append

             print(f"EventActionProcessor: Player action triggered stage transition for event {event.id}.")
        else:
             stage_transitioned = False
             print(f"EventActionProcessor: Player action '{command_keyword}' processed, but did NOT trigger a stage transition.")
             if return_message: # Send feedback if a message was set by action execution
                  send_cb = action_execution_context.get('send_message_callback')
                  if send_cb:
                      try:
                        player_name_for_msg = getattr(player_character, 'name', 'Unknown')
                        await send_cb(f"**{player_name_for_msg}:** {return_message}", None)
                      except Exception as cb_e:
                        print(f"EventActionProcessor Error sending feedback message: {cb_e}")

        return {"stage_transitioned": stage_transitioned, "message": return_message, "modified_entities": modified_entities}

    # --- Optional: Helper methods for action processing ---
    # Implement helper methods here for different action types like skill checks, item usage, etc.
    # These methods would take the action_execution_context dictionary as an argument
    # and perform the core logic, returning an outcome string or other data.

    # async def _validate_player_action(self, player_character: Character, action_data: Dict[str, Any], context: Dict[str, Any]) -> bool:
    #     """Helper to check if player is allowed/capable of performing this action based on constraints/rules."""
    #     # Example: Check player status, inventory, location validity against action data requirements.
    #     # Use managers from the context dictionary.
    #     pass

    # async def _execute_skill_check(self, context: Dict[str, Any]) -> Dict[str, Any]:
    #      """Helper to perform a skill check and return the result/outcome."""
    #      # Use context['rule_engine'], context['player_character'], context['action_params'] etc.
    #      # Example: skill_name = context['action_params'].get('skill'), difficulty = context['action_params'].get('difficulty')
    #      # rule_engine_inst = context.get('rule_engine') # Get manager from context
    #      # if rule_engine_inst and hasattr(rule_engine_inst, 'perform_skill_check'):
    #      #     check_result_details = await rule_engine_inst.perform_skill_check(context['player_character'], skill_name, difficulty, context=context)
    #      #     return {'outcome': check_result_details.get('outcome', 'failure'), **check_result_details}
    #      # return {'outcome': 'failure'} # Default if cannot perform check

    # async def _execute_use_item(self, context: Dict[str, Any]) -> Dict[str, Any]:
    #      """Helper to execute item usage effects."""
    #      # Use context['item_manager'], context['player_character'], context['action_params'] etc.
    #      # Example: item_id = context['action_params'].get('item_id')
    #      # item_manager_inst = context.get('item_manager') # Get manager from context
    #      # if item_manager_inst and hasattr(item_manager_inst, 'use_item'):
    #      #     # Assuming use_item needs user, item_id, context, and returns a result dict
    #      #     usage_result = await item_manager_inst.use_item(context['player_character'], item_id, context=context)
    #      #     return {'outcome': usage_result.get('outcome', 'failure'), **usage_result}
    #      # return {'outcome': 'failure'} # Default if cannot use item


    # TODO: Add helper methods for other action types (e.g., _execute_combat_action, _execute_dialogue_choice)


print("DEBUG: event_action_processor.py module loaded.")