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
                                   ) -> bool: # Returns True if stage transition occurred, False otherwise.
        """
        Обрабатывает команду игрока внутри контекста активного события.
        """
        print(f"EventActionProcessor: processing player '{player_id}' action '{command_keyword}' for event {event_id} with args {command_args}...")

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
        if event_manager_inst is None or character_manager_inst is None or loc_manager_inst is None or rule_engine_inst is None or send_callback_factory_inst is None:
             # Collect names of missing dependencies
             missing_deps = [name for name, dep in [
                 ('event_manager', event_manager_inst),
                 ('character_manager', character_manager_inst),
                 ('loc_manager', loc_manager_inst),
                 ('rule_engine', rule_engine_inst),
                 ('send_callback_factory', send_callback_factory_inst)
                 ] if dep is None]

             print(f"EventActionProcessor Error: Missing essential dependencies for process_player_action: {', '.join(missing_deps)}.")

             # Use the available channel_id (from kwargs) and factory (_inst) to send error message if possible
             error_message = f"❌ Системная ошибка: Не удалось обработать команду. Отсутствуют ключевые компоненты: {', '.join(missing_deps)}."
             if channel_id_from_kwargs is not None and send_callback_factory_inst is not None:
                  try:
                       # Use the _inst variable here
                       send_cb = send_callback_factory_inst(channel_id_from_kwargs)
                       await send_cb(error_message, None)
                  except Exception as cb_e:
                       print(f"EventActionProcessor Error sending initial error message: {cb_e}")
             elif send_callback_factory_inst is None:
                   print(f"EventActionProcessor Warning: Cannot send initial error message because send_callback_factory is missing.")
             elif channel_id_from_kwargs is None:
                  print(f"EventActionProcessor Warning: Cannot send initial error message because channel_id missing from kwargs.")

             # Always return False after critical error
             return False # Cannot proceed

        # --- Now that essential dependencies are confirmed, proceed using _inst variables ---

        # Get event object using the event manager instance
        event: Optional["Event"] = event_manager_inst.get_event(event_id) # FIX: Use _inst variable
        if not event:
             print(f"EventActionProcessor Error: Event {event_id} not found for player action.")
             # Use channel_id from kwargs if event is not found to send error message back
             channel_id_for_error = channel_id_from_kwargs # Use kwargs channel_id as fallback
             if channel_id_for_error is not None: # Factory is confirmed not None above
                 try:
                      # Use the _inst variable here
                      send_cb = send_callback_factory_inst(channel_id_for_error)
                      await send_cb("❌ Ошибка: Событие не найдено.", None);
                 except Exception as cb_e: print(f"EventActionProcessor Error sending error message: {cb_e}");
             return False # Failed to process due to missing event


        # Get player character object (needed for context/checks)
        # Assuming character_manager needs guild_id and player_id
        guild_id = event.guild_id # Get guild_id from the event object
        player_character = character_manager_inst.get_character(guild_id, player_id) # type: Optional["Character"] # FIX: Use _inst variable
        if not player_character:
             print(f"EventActionProcessor Error: Player character {player_id} not found for event {event_id} in guild {guild_id}.")
             # Use the event's channel ID to send error message
             channel_id_for_error = event.channel_id # Get channel ID from event
             if channel_id_for_error is not None: # Factory is confirmed not None above
                  try:
                      # Use the _inst variable here
                      send_cb = send_callback_factory_inst(channel_id_for_error)
                      await send_cb("❌ Ошибка: Ваш персонаж не найден.", None);
                  except Exception as cb_e: print(f"EventActionProcessor Error sending error message: {cb_e}");
             return False # Failed to process due to missing player

        # Now that event and player character are confirmed, get the send callback for the event channel
        # Make sure event has a channel_id
        if event.channel_id is None:
             print(f"EventActionProcessor Error: Event {event.id} has no channel_id. Cannot send messages.")
             # Try sending error back to the original channel if possible (channel_id from kwargs)
             channel_id_for_error = channel_id_from_kwargs # Fallback to kwargs channel_id
             if channel_id_for_error is not None: # Factory is confirmed not None above
                 try:
                     # Use the _inst variable here
                     send_cb = send_callback_factory_inst(channel_id_for_error)
                     await send_cb("❌ Ошибка: Событие не привязано к каналу для отправки сообщений.", None);
                 except Exception as cb_e: print(f"EventActionProcessor Error sending error message: {cb_e}");
             return False

        # Use the factory to get the specific channel callback
        # Use send_callback_factory_inst
        send_message_callback = send_callback_factory_inst(event.channel_id) # FIX: Use _inst variable


        # Get current stage data from the event object
        current_stage_id = event.current_stage_id # Keep track of current stage ID
        current_stage_data = event.stages_data.get(current_stage_id)

        if not current_stage_data:
             print(f"EventActionProcessor Error: Stage '{current_stage_id}' not found in event {event_id} data.")
             try: await send_message_callback(f"❌ Ошибка: Данные текущей стадии '{current_stage_id}' не найдены в событии.", None);
             except Exception as cb_e: print(f"EventActionProcessor Error sending error message: {cb_e}");
             return False

        # Convert stage data to EventStage object if possible
        try:
             # EventStage needs to be imported at runtime if EventStage.from_dict is called
             current_stage: "EventStage" = EventStage.from_dict(current_stage_data)
             using_event_stage_object = True
        except (NameError, ImportError, TypeError) as e: # Catch NameError, ImportError (if import fails), or TypeError (if from_dict fails)
             print(f"EventActionProcessor Warning: EventStage model not available or from_dict failed ({e}). Working with raw stage data dictionary.")
             current_stage = current_stage_data # Use the dictionary directly
             using_event_stage_object = False

        # --- Find the matching action in allowed_actions ---
        # Adapt access based on whether current_stage is dict or object
        allowed_actions_list = getattr(current_stage, 'allowed_actions', []) if using_event_stage_object else current_stage.get('allowed_actions', [])
        target_action_definition: Optional[Dict[str, Any]] = None

        # Get stage name safely
        current_stage_name = getattr(current_stage, 'name', current_stage_id) if using_event_stage_object else current_stage.get('name', current_stage_id)


        print(f"EventActionProcessor: Searching stage '{current_stage_name}' ({current_stage_id}) for command '{command_keyword}'...")

        for action_def in allowed_actions_list:
            # Simple check: match command keyword (case-insensitive)
            if isinstance(action_def, dict) and action_def.get('command', '').lower() == command_keyword.lower():
                # TODO: Add more sophisticated matching based on command_args and action_def parameters/requirements
                target_action_definition = action_def
                print(f"EventActionProcessor: Found potential action match for command '{command_keyword}'.")
                break # Found a match

        if not target_action_definition:
             print(f"EventActionProcessor: Player action command '{command_keyword}' not found or not allowed in stage '{current_stage_name}' for event {event_id}.")
             # Use getattr for event name safely
             event_name = getattr(event, 'name', event_id) if isinstance(event, Event) else event_id
             try: await send_message_callback(f"Действие `{command_keyword}` недоступно на текущей стадии **{event_name}** ('{current_stage_name}') или введено неверно для этой стадии.", None);
             except Exception as cb_e: print(f"EventActionProcessor Error sending feedback message: {cb_e}");
             return False # Command not allowed or not found


        # --- Execute the found action ---
        action_type = target_action_definition.get('type')
        action_params = target_action_definition.get('params', {}) # Parameters for the action logic

        player_character_name = getattr(player_character, 'name', 'Unknown') # Get player name safely
        print(f"EventActionProcessor: Executing player action type '{action_type}' for player '{player_character_name}'...")

        # --- Determine the outcome of the action execution (if applicable) ---
        # This needs actual action logic based on action_type.
        # Initialize with a default outcome
        action_execution_outcome: str = "success" # Default outcome

        # Create a context dictionary containing all managers and relevant info for action execution
        # Get all managers/processors from kwargs or self attributes (if they were injected in __init__)
        # Prioritize managers passed in kwargs (more specific context)
        action_execution_context: Dict[str, Any] = {
             # Passed Dependencies (should be in kwargs from GameManager/CommandRouter)
             # FIX: Use the _inst variables here
             'event_manager': event_manager_inst,
             'character_manager': character_manager_inst,
             'loc_manager': loc_manager_inst, 'location_manager': loc_manager_inst, # Alias for loc_manager
             'rule_engine': rule_engine_inst,
             'openai_service': kwargs.get('openai_service', self._openai_service), # Use kwargs or self attribute
             'send_message_callback': send_message_callback, # Specific channel callback, already got above from factory_inst
             'send_callback_factory': send_callback_factory_inst, # Factory itself - FIX: Use _inst variable

             # Other Managers (get from kwargs or self attributes)
             'npc_manager': kwargs.get('npc_manager', self._npc_manager),
             'combat_manager': kwargs.get('combat_manager', self._combat_manager),
             'item_manager': kwargs.get('item_manager', self._item_manager),
             'time_manager': kwargs.get('time_manager', self._time_manager),
             'status_manager': kwargs.get('status_manager', self._status_manager),
             'party_manager': kwargs.get('party_manager', self._party_manager),
             'economy_manager': kwargs.get('economy_manager', self._economy_manager),
             'dialogue_manager': kwargs.get('dialogue_manager', self._dialogue_manager),
             'crafting_manager': kwargs.get('crafting_manager', self._crafting_manager),

             # Processors (get from kwargs or self attributes)
             'event_stage_processor': kwargs.get('event_stage_processor', self._event_stage_processor),
             'on_enter_action_executor': kwargs.get('on_enter_action_executor', self._on_enter_action_executor),
             'stage_description_generator': kwargs.get('stage_description_generator', self._stage_description_generator),
             'character_action_processor': kwargs.get('character_action_processor', self._character_action_processor),
             # Add other processors if needed (e.g. PartyActionProcessor?)

             # Action Specific Context
             'event': event, # Event object
             'player_character': player_character, # Player Character object
             'player_id': player_id,
             'guild_id': guild_id, # Add guild_id
             'current_stage_id': current_stage_id,
             'current_stage_data': current_stage_data, # Pass raw data too
             'command_keyword': command_keyword,
             'command_args': command_args,
             'action_data': target_action_definition, # Full action definition
             'action_params': action_params, # Just the params part

             # Include any other kwargs passed to process_player_action
             # channel_id_from_kwargs can be added here if needed in action logic
             'channel_id': channel_id_from_kwargs,
        }
        # Use update() to add kwargs safely without Pylance warning
        action_execution_context.update(kwargs) # This might overwrite existing keys, review if needed


        # TODO: Implement the action execution logic based on action_type.
        # This logic should use the managers/services from action_execution_context
        # and determine the 'action_execution_outcome' string.
        # This might involve calling methods on managers like rule_engine, combat_manager etc.
        # Example placeholder:
        # if action_type == 'skill_check_player':
        #     check_result = await self._execute_skill_check(action_execution_context) # Call a helper method
        #     action_execution_outcome = check_result.get('outcome', 'failure')
        #     # Potentially send intermediate feedback about the check result here using send_message_callback
        # elif action_type == 'use_item':
        #     use_result = await self._execute_use_item(action_execution_context) # Call a helper method
        #     action_execution_outcome = use_result.get('outcome', 'failure')
        #     # Potentially send intermediate feedback about item usage here
        # ... other action types ...

        # For 'simple_transition', the outcome is conceptually always success in terms of triggering the transition below.
        # Actual side-effects (if any) for simple_transition actions should still be handled here or delegated.
        if action_type == 'simple_transition':
            action_execution_outcome = 'success'
            print(f"EventActionProcessor: Action type '{action_type}' has outcome '{action_execution_outcome}'.")
            # Note: Side effects for simple transitions (if any) could be implemented here or in a helper.
        elif action_type is None:
             print(f"EventActionProcessor Warning: Action '{command_keyword}' has no defined 'type'. Assuming simple success outcome.")
             action_execution_outcome = 'success' # Default for actions without a type? Or should this be an error?
        # Handle other action types here (skill checks, combat actions, item usage, etc.)
        # based on the determined 'action_execution_outcome' from their execution logic.


        # --- Determine if the action triggers a stage transition ---
        outcome_stage_id_def: Optional[Any] = target_action_definition.get('outcome_stage_id')
        determined_next_stage_id: Optional[str] = None

        # Map the determined action outcome to the next stage ID if outcome_stage_id_def is a dictionary.
        if isinstance(outcome_stage_id_def, str) and outcome_stage_id_def:
             # Simple case: 'outcome_stage_id' is just a stage ID string. Action always transitions here regardless of detailed outcome.
             determined_next_stage_id = outcome_stage_id_def
             print(f"Action defines a simple transition to '{determined_next_stage_id}'.")
        elif isinstance(outcome_stage_id_def, dict):
             # Complex case: 'outcome_stage_id' is a dictionary mapping outcomes to stage IDs.
             # Use the determined 'action_execution_outcome'
             determined_next_stage_id = outcome_stage_id_def.get(action_execution_outcome)
             print(f"Action defines outcome-based transition. Outcome '{action_execution_outcome}' maps to stage '{determined_next_stage_id}'.")

             # Optional: Handle specific critical outcomes if they exist and map to different stages
             # if action_execution_outcome == 'critical_success': determined_next_stage_id = outcome_stage_id_def.get('critical_success', determined_next_stage_id)
             # elif action_execution_outcome == 'critical_failure': determined_next_stage_id = outcome_stage_id_def.get('critical_failure', determined_next_stage_id)


        # --- Trigger Stage Transition if a next stage ID was determined ---
        # If a valid next stage ID string was found AND it's different from the current stage
        # Get processor from context (should be event_stage_processor_inst)
        event_stage_processor_inst = action_execution_context.get('event_stage_processor') # Use the instance name for clarity
        # Check if event_stage_processor_inst is available and has advance_stage method
        if isinstance(determined_next_stage_id, str) and determined_next_stage_id and determined_next_stage_id != current_stage_id and \
           event_stage_processor_inst and hasattr(event_stage_processor_inst, 'advance_stage'):
             print(f"EventActionProcessor: Player action '{command_keyword}' triggers transition to stage '{determined_next_stage_id}'.")

             # Call the injected EventStageProcessor's advance_stage method.
             # Use the _inst variable
             await event_stage_processor_inst.advance_stage(
                 event=event, # Pass event object by reference
                 target_stage_id=determined_next_stage_id, # Target stage determined by player action outcome
                 # Pass the consolidated managers/context dictionary
                 # send_message_callback is included in action_execution_context
                 **action_execution_context # Unpack the context dictionary as kwargs for advance_stage
             )

             # Event state (current_stage_id etc.) has been updated by the advance_stage call.
             # GameManager (the caller of process_player_action) is responsible for saving this state.

             print(f"EventActionProcessor: Player action triggered stage transition for event {event.id}.")
             return True # Indicate a stage transition occurred


        else: # The action did NOT define a valid/different outcome_stage_id for the determined outcome.
             # Or it defined an outcome_stage_id that is the same as the current stage (no explicit transition).
             # In this case, the action's primary effect should happen *without* changing the stage.

             print(f"EventActionProcessor: Player action '{command_keyword}' processed, but did NOT trigger a stage transition.")

             # TODO: Execute side effects of actions that do NOT trigger a stage transition (if not done above in the first TODO block)
             # For example, using an item, attacking an NPC, casting a non-transitioning spell.
             # Example: If the action type required a skill check but failed, and failure didn't have an outcome_stage_id
             # if action_type == 'skill_check_player' and action_execution_outcome == 'failure':
             #     feedback_message = "Проверка действия не удалась."
             # elif action_type == 'use_item' and action_execution_outcome == 'success':
             #     feedback_message = f"Вы использовали предмет." # More specific feedback
             # ... default feedback if no specific type feedback is given ...
             feedback_message = "Действие выполнено." # Default fallback message for non-transitioning actions

             # Note: More specific feedback should ideally come from the action execution logic itself (first TODO block).
             # This is just a generic fallback.

             # Send basic feedback to the player using the provided callback.
             # send_message_callback is available in action_execution_context
             send_message_callback = action_execution_context.get('send_message_callback')

             if send_message_callback:
                  # Send to the event channel (callback is already bound to the channel)
                  # Add player name for context
                  try:
                    # Ensure player_character is available in context for the name
                    player_character_in_context = action_execution_context.get('player_character')
                    player_name = getattr(player_character_in_context, 'name', 'Unknown') # Safely get name
                    await send_message_callback(f"**{player_name}:** {feedback_message}", None) # The warning was likely on a call *site* related to this callback chain
                  except Exception as cb_e:
                    print(f"EventActionProcessor: Error sending feedback message: {cb_e}")


             print(f"EventActionProcessor: No stage transition triggered for event {event.id}.")
             return False # Indicate no stage transition occurred


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