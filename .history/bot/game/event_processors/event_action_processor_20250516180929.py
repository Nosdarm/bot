# bot/game/event_processors/event_action_processor.py

# EventActionProcessor: Handles player commands/actions directed at an active event.
# Finds the relevant action in the event stage definition.
# Performs basic action processing (validation, effects).
# If the action triggers a stage change (via outcome_stage_id), calls EventStageProcessor.
# Called by the GameManager when a player command is routed to an event.

import json
from typing import Dict, Optional, Any, List, Callable # Ensure all typing components are imported correctly

# --- Define Type Aliases ---
# Define alias for send message callback function signature
SendCallback = Callable[[int, str], Any]


# --- Import Models (needed for type hints) ---
# Ensure correct import paths.
# Model imports first is a common convention to help avoid cyclic dependencies during loading.
from bot.game.models.event import Event, EventStage # Needs Explicit Import of Event and EventStage
from bot.game.models.character import Character # Needs Explicit Import of Character class
# Add other model imports needed for type hints in this file (e.g., Item, Npc, Combat)
# from bot.game.models.item import Item
# from bot.game.models.npc import Npc
# from bot.game.models.combat import Combat # If action result involves Combat objects


# --- Import Managers and Services (needed as method arguments) ---
# Ensure correct import paths. These are the dependencies PASSED to process_player_action.
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.event_manager import EventManager # To retrieve the event object
from bot.game.managers.location_manager import LocationManager
from bot.game.rules.rule_engine import RuleEngine
from bot.services.openai_service import OpenAIService # Required by StageProcessor -> Generator

# --- Import OPTIONAL Managers needed for type hints in process_player_action signature ---
# Ensure these are imported. If NameError persists, check these specific imports/files again.
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.time_manager import TimeManager # <--- Check this one! Is TimeManager in bot.game.managers.time_manager imported correctly?
# Add other Optional manager imports if you use them in the signature:
from bot.game.managers.status_manager import StatusManager # Import if used in signature
# -------------------------------------------------------------------------------------


# --- Import other Processors THIS processor might call ---
# EventActionProcessor calls EventStageProcessor
from bot.game.event_processors.event_stage_processor import EventStageProcessor


print("DEBUG: Successfully imported dependencies in event_action_processor.py")


# --- This class handles processing player commands related to an active event ---
# The NameError on line 67 points to the signature of process_player_action or the class definition itself.
# It should be specifically at the argument definition: time_manager: Optional[TimeManager].
# This confirms Python has loaded this file, processed the imports *above*,
# but when trying to resolve the *type hint* TimeManager, it fails.
# This is highly indicative that the import for TimeManager (which IS in the imports list)
# somehow didn't properly define the *name* TimeManager in this file's scope by this line.
# Possible (rare) causes: complex import logic, subtle caching, or maybe TimeManager file
# itself had an error during its loading that prevented its name from being registered globally?


class EventActionProcessor:

    
    def __init__(self,
                 event_stage_processor: EventStageProcessor,
                 event_manager: EventManager,
                 character_manager: CharacterManager,
                 loc_manager: LocationManager,
                 rule_engine: RuleEngine,
                 openai_service: OpenAIService,
                 # Добавьте опциональные менеджеры, если они нужны EventActionProcessor
                 npc_manager: Optional[NpcManager] = None,
                 combat_manager: Optional[CombatManager] = None,
                 item_manager: Optional[ItemManager] = None,
                 time_manager: Optional[TimeManager] = None,
                 status_manager: Optional[StatusManager] = None, # <-- ДОБАВЬТЕ ЭТОТ ПАРАМЕТР

                 # TODO: Добавьте другие зависимости, если EventActionProcessor их требует
                 ):
        print("Initializing EventActionProcessor...")

        # --- Сохранение переданных зависимостей ---
        self._event_stage_processor = event_stage_processor
        self._event_manager = event_manager
        self._character_manager = character_manager
        self._loc_manager = loc_manager
        self._rule_engine = rule_engine
        self._openai_service = openai_service

        # Сохраняем опциональные менеджеры
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._item_manager = item_manager
        self._time_manager = time_manager
        self._status_manager = status_manager # <-- СОХРАНИТЕ ЕГО КАК АТРИБУТ

        # TODO: Сохраните другие зависимости

        print("EventActionProcessor initialized.")


    # --- Method to process a player's command within an event context ---
    # Called by the GameManager. Receives event ID, player ID, command, args, and ALL dependencies.
    # ОПРЕДЕЛЕНИЕ МЕТОДА С ОТСТУПОМ (ВНУТРИ КЛАССА, ТАКОЙ ЖЕ ОТСТУП, КАК У __init__)
    # Проверьте ТОЧНУЮ сигнатуру process_player_action!
    async def process_player_action(self,
                                    event_id: str, # ID события, к которому относится действие
                                    player_id: str, # ID персонажа, выполняющего действие
                                    command_keyword: str, # Ключевое слово команды игрока (например, 'investigate')
                                    command_args: List[str], # Аргументы команды игрока

                                    # --- Зависимости, переданные в этот метод при вызове ---
                                    # ЭТИ ЗАВИСИМОСТИ ПЕРЕДАЮТСЯ ПРИ ВЫЗОВЕ МЕТОДА, А НЕ В КОНСТРУКТОР КЛАССА!
                                    # GameManager.handle_player_command передает их сюда.
                                    event_manager: EventManager, # Нужен для доступа к данным события
                                    character_manager: CharacterManager, # Нужен для доступа/изменения персонажей
                                    loc_manager: LocationManager, # Нужен для доступа к данным локаций
                                    rule_engine: RuleEngine, # Нужен для проверок навыков и т.п.
                                    openai_service: OpenAIService, # Может быть нужен для генерации ответов
                                    send_message_callback: SendCallback, # Callback для отправки сообщений

                                    # --- ОПЦИОНАЛЬНЫЕ Менеджеры, переданные в этот метод ---
                                    # Проверьте ТОЧНУЮ сигнатуру process_player_action!
                                    npc_manager: Optional[NpcManager] = None,
                                    combat_manager: Optional[CombatManager] = None,
                                    item_manager: Optional[ItemManager] = None,
                                    time_manager: Optional[TimeManager] = None,
                                    # ... другие опциональные менеджеры ...


                                   ) -> bool: # Optional return: True if transition, False otherwise.
        """
        Обрабатывает команду игрока внутри контекста активного события.
        """
        # print("EventActionProcessor: processing player action...") # Опционально: логирование начала метода

        # Здесь будет логика поиска команды в allowed_actions текущей стадии события
        # Получение объекта события из EventManager (передан как зависимость)
        event: Optional[Event] = event_manager.get_event(event_id)
        if not event:
             print(f"EventActionProcessor Error: Event {event_id} not found for player action.")
             await send_message_callback(event_manager.get_event_channel_id(event_id), "❌ Ошибка: Событие не найдено.") # Пример сообщения об ошибке
             return False # Не удалось обработать

        # Получение данных текущей стадии из объекта события
        current_stage_data = event.stages_data.get(event.current_stage_id)
        if not current_stage_data:
             print(f"EventActionProcessor Error: Stage {event.current_stage_id} not found in event {event_id} data.")
             # Отправить сообщение об ошибке?
             return False

        current_stage: EventStage = EventStage.from_dict(current_stage_data)


        # Поиск команды игрока в списке allowed_actions текущей стадии
        allowed_actions_list = getattr(current_stage, 'allowed_actions', [])
        target_action_definition: Optional[Dict[str, Any]] = None
        for action_def in allowed_actions_list:
            if isinstance(action_def, dict) and action_def.get('command', '').lower() == command_keyword.lower():
                target_action_definition = action_def
                break

        if not target_action_definition:
             print(f"EventActionProcessor: Player action command '{command_keyword}' not allowed in stage '{current_stage.name}' for event {event_id}.")
             # Отправить сообщение игроку, что команда не разрешена на этой стадии
             await send_message_callback(event.channel_id, f"Действие `{command_keyword}` не разрешено на текущей стадии **{current_stage.name}**.")
             return False # Команда не разрешена


        # --- Выполнение логики действия игрока ---
        action_type = target_action_definition.get('type')
        print(f"EventActionProcessor: Found allowed action '{command_keyword}', type '{action_type}'. Executing...")

        # TODO: Implement execution logic for different action types (skill_check_player, simple_transition, etc.)
        # Эта логика будет похожа на OnEnterActionExecutor, но для действий ИГРОКА.
        # Возможно, понадобится отдельный Executor для Player Actions, или интегрировать в OnEnterActionExecutor.
        # Или просто реализовать switch/case по action_type здесь.

        # Пример обработки типа действия simple_transition:
        if action_type == 'simple_transition':
            outcome_stage_id = target_action_definition.get('outcome_stage_id')
            if isinstance(outcome_stage_id, str) and outcome_stage_id:
                 print(f"EventActionProcessor: Action '{command_keyword}' triggered simple transition to stage '{outcome_stage_id}'.")
                 # Вызываем EventStageProcessor для продвижения на новую стадию
                 # Передаем Event object и ВСЕ зависимости, которые получил process_player_action
                 await self._event_stage_processor.advance_stage(
                     event=event, # Передаем объект события
                     target_stage_id=outcome_stage_id, # Целевая стадия
                     # Передаем все зависимости, полученные этим методом
                     character_manager=character_manager, loc_manager=loc_manager, rule_engine=rule_engine, openai_service=openai_service,
                     send_message_callback=send_message_callback, # Callback для канала события
                     # Опциональные менеджеры
                     npc_manager=npc_manager, combat_manager=combat_manager, item_manager=item_manager, time_manager=time_manager,
                     # Контекст перехода
                     transition_context={"trigger": f"player_action_{command_keyword}", "player_id": player_id, "from_stage_id": current_stage.id, "to_stage_id": outcome_stage_id}
                 )
                 print(f"EventActionProcessor: Simple transition to '{outcome_stage_id}' completed.")
                 return True # Произошел переход

            else:
                 print(f"EventActionProcessor Error: Action '{command_keyword}' (simple_transition) has invalid 'outcome_stage_id' in template: {outcome_stage_id}")
                 # Отправить сообщение об ошибке GM?
                 return False # Ошибка в шаблоне действия


        # Пример обработки типа действия skill_check_player:
        # Этот тип требует более сложную логику, вероятно, вызов RuleEngine и условный переход.
        # if action_type == 'skill_check_player':
        #      params = target_action_definition.get('params', {})
        #      outcome_stage_ids = target_action_definition.get('outcome_stage_id', {}) # Это словарь исходов
        #      # ... Логика проверки навыка, используя character_manager, rule_engine и params ...
        #      # result = await rule_engine.perform_check(player_character, check_params, ...) # Пример
        #      # Determine next_stage_id based on result ('success', 'failure', 'critical_success', 'critical_failure')
        #      # next_stage_id = outcome_stage_ids.get(result)
        #      # if next_stage_id:
        #      #      await self._event_stage_processor.advance_stage(event, next_stage_id, ...)
        #      #      return True # Произошел переход
        #      # else:
        #      #      print(f"EventActionProcessor Error: Skill check action '{command_keyword}' has no outcome_stage_id defined for result '{result}' in template.")
        #      #      # Отправить сообщение об ошибке GM?
        #      #      return False # Ошибка в шаблоне или не удалось определить переход
        #      # else:
        #      #      print(f"EventActionProcessor Error: Skill check action '{command_keyword}' failed to perform check.")
        #      #      # Отправить сообщение об ошибке игроку/GM?
        #      #      return False # Ошибка выполнения проверки


        # TODO: Реализовать другие типы действий игрока

        else:
            print(f"EventActionProcessor Warning: Unhandled player action type '{action_type}' for command '{command_keyword}' in stage '{current_stage.name}' for event {event_id}.")
            # Отправить сообщение игроку об неизвестной команде? (Хотя роутинг в GameManager должен был это отловить)
            return False # Нет перехода или не удалось обработать



        # --- 3. Find the matching action in allowed_actions ---
        found_action_data: Optional[Dict[str, Any]] = None
        # print(f"EventActionProcessor: Searching 'allowed_actions' ({len(current_stage.allowed_actions)} defined) for command '{command_keyword}'...") # Can be noisy

        for action_data in current_stage.allowed_actions:
             action_command_in_template = action_data.get('command')
             action_type_in_template = action_data.get('type')

             if isinstance(action_command_in_template, str) and action_command_in_template.lower() == command_keyword.lower():
                  # Potential match by command keyword. Add further checks based on args if needed.
                  # TODO: Implement more sophisticated matching based on command_args vs action_data (e.g., check params)
                  found_action_data = action_data
                  # print(f"EventActionProcessor: Found action match: command '{command_keyword}' (type: {action_type_in_template or 'N/A'}).") # Can be noisy
                  break # Found a match


        if not found_action_data:
             print(f"EventActionProcessor: Event {event.id} stage '{current_stage.name}': No matching action found in 'allowed_actions' for command '{command_keyword}' and arguments. Command Args: {command_args}. Action: {json.dumps(found_action_data)}")
             # This feedback is also handled by the 'not current_stage.allowed_actions' block above, but here is more specific.
             if send_message_callback and event.channel_id:
                  await send_message_callback(event.channel_id, f"Действие `{command_keyword}` недоступно на текущей стадии **{event.name}** ('{current_stage.name}') или введено неверно для этой стадии.")
             return False # Action not found or did not match specific argument requirements


        # --- 4. Process the found action ---
        action_type_found: Optional[str] = found_action_data.get('type')
        # action_params: Dict[str, Any] = found_action_data.get('params', {}) # Parameters nested under 'params' or directly in action_data

        print(f"EventActionProcessor: Processing player action type '{action_type_found}' triggered by player '{player_character.name}' ({player_id}).")


        # --- Determine if the action triggers a stage transition ---
        # This depends on the 'outcome_stage_id' defined in the action data.
        # 'outcome_stage_id' can be a simple string or a dictionary mapping action outcomes ('success', 'failure' etc.) to stage IDs.
        outcome_stage_id_def: Optional[Any] = found_action_data.get('outcome_stage_id')
        determined_next_stage_id: Optional[str] = None

        # Determine the outcome of the action execution (if applicable)
        # This needs actual action logic to be implemented first (e.g., calling RuleEngine, processing combat, using item).
        # For this basic flow, let's assume action success is the default unless the action_type requires a specific check first.
        # Simple default outcome: Assume action "succeeds" unless it's a check action type that determines outcome.
        action_execution_outcome: str = "success" # Default outcome


        # TODO: IMPLEMENT ACTION EXECUTION LOGIC HERE or delegate it!
        # The outcome might be determined by THIS logic. Example for a player skill check action type:
        # if action_type_found == 'skill_check_player' and rule_engine and character_manager and loc_manager and openai_service and send_message_callback:
        #      # Need to get check definition from action_data['params'] or linked data
        #      check_params = found_action_data.get('params', {})
        #      # Run the check using RuleEngine, passing managers
        #      check_result = await rule_engine.perform_check(...)
        #      # Determine action_execution_outcome from check_result ('success', 'failure', etc.)
        #      action_execution_outcome = check_result.get('outcome', action_execution_outcome)
        #      # Describe the check result via AI if needed (might be an OnEnter action consequences or here)


        # Map the determined action outcome to the next stage ID if outcome_stage_id_def is a dictionary.
        if isinstance(outcome_stage_id_def, str) and outcome_stage_id_def:
             # Simple case: 'outcome_stage_id' is just a stage ID string. Action always transitions here.
             determined_next_stage_id = outcome_stage_id_def
             # print("Action defines a simple transition.")
        elif isinstance(outcome_stage_id_def, dict):
             # Complex case: 'outcome_stage_id' is a dictionary mapping outcomes to stage IDs.
             # Use the determined 'action_execution_outcome' (from actual action logic above)
             determined_next_stage_id = outcome_stage_id_def.get(action_execution_outcome) # Get stage ID based on outcome string

             # Also check for critical outcomes if applicable (needs outcome logic to produce 'critical_success'/'critical_failure')
             # if action_execution_outcome == 'critical_success': determined_next_stage_id = outcome_stage_id_def.get('critical_success', determined_next_stage_id)
             # elif action_execution_outcome == 'critical_failure': determined_next_stage_id = outcome_stage_id_def.get('critical_critical', determined_next_stage_id)


        # --- Trigger Stage Transition if a next stage ID was determined ---
        # If a valid next stage ID string was found AND it's different from the current stage (prevent looping)
        # AND it's not the 'event_end' signal (unless player action is explicitly ending the event?)
        if isinstance(determined_next_stage_id, str) and determined_next_stage_id and determined_next_stage_id != event.current_stage_id:
             print(f"EventActionProcessor: Player action '{command_keyword}' ({action_type_found or 'N/A'}) triggers transition to stage '{determined_next_stage_id}'.")

             # Call the injected EventStageProcessor's advance_stage method.
             # Pass the event, the determined target stage ID, and ALL necessary dependencies.
             # EventStageProcessor handles OnEnter actions, auto-transitions checks, and description generation for the NEW stage.
             await self._event_stage_processor.advance_stage(
                 event=event, # Pass event object by reference
                 target_stage_id=determined_next_stage_id, # Target stage determined by player action outcome

                 # Pass ALL managers/services/callbacks that StageProcessor and its dependencies need:
                 character_manager=character_manager, loc_manager=loc_manager, rule_engine=rule_engine, openai_service=openai_service,
                 send_message_callback=send_message_callback, # Callback from GameManager for event channel

                 # Pass OPTIONAL managers (if instantiated and needed by downstream processors)
                 npc_manager=npc_manager, combat_manager=combat_manager, item_manager=item_manager, time_manager=time_manager,
                 # ... other optional managers ...

                 # Provide context for the transition
                 transition_context={
                     "trigger": "player_action",
                     "action_keyword": command_keyword,
                     "action_type": action_type_found,
                     "player_id": player_id,
                     "player_name": player_character.name if player_character else 'Unknown',
                     "from_stage_id": current_stage_id,
                     "to_stage_id": determined_next_stage_id,
                     "action_outcome": action_execution_outcome, # Include determined outcome
                     # Include command args and action data for full context? (Can be large)
                     #"command_args": command_args,
                     #"action_data": found_action_data
                 }
             )

             # Event state (current_stage_id etc.) has been updated by the advance_stage call.
             # GameManager (the caller of process_player_action) is responsible for saving this state.

             print(f"EventActionProcessor: Player action triggered stage transition for event {event.id}.")
             return True # Indicate a stage transition occurred


        else: # The action did NOT define a valid/different outcome_stage_id for the determined outcome.
             # OR it defined an outcome_stage_id that is the same as the current stage.
             # This action's *immediate effects* (like applying status, dealing damage, giving item etc.,
             # if they are not tied to stage transitions) should happen here if not already implemented above.
             # They don't cause a stage transition, but affect game state.

             print(f"EventActionProcessor: Player action '{command_keyword}' ({action_type_found or 'N/A'}) processed, but did NOT trigger a stage transition.")

             # TODO: IMPLEMENT EXECUTION OF ACTION SIDE EFFECTS HERE OR DELEGATE IT
             # For actions without transitions (e.g., /event use potion), their effects must happen now.
             # Example: Call a method _execute_non_transition_action(action_type_found, action_params, ...)
             # This would contain the if/elif logic for types like 'use_item', 'attack_target', 'deal_damage'.

             # Send basic feedback to the player using the provided callback.
             # More detailed feedback might come from the action effect execution itself (if implemented).
             feedback_message = "Действие выполнено." # Default success message

             # Simple outcome-based feedback if action execution logic provides an outcome:
             # if action_execution_outcome == 'failure': feedback_message = "Действие не удалось."
             # elif action_execution_outcome == 'critical_success': feedback_message = "Критический успех!"

             if send_message_callback and event.channel_id and player_character:
                  # Send to the event channel from which command likely originated.
                  await send_message_callback(event.channel_id, f"**{player_character.name}:** {feedback_message}")


             print(f"EventActionProcessor: No stage transition triggered for event {event.id}.")
             return False # Indicate no stage transition occurred


    # --- Optional: Helper methods for action processing ---
    # async def _validate_player_action(self, player_character: Character, action_data: Dict[str, Any], managers: Dict[str, Any]) -> bool:
    #     """Helper to check if player is allowed/capable of performing this action based on constraints/rules."""
    #     # Example: Check player status, inventory, location validity against action data requirements.
    #     pass

    # async def _execute_non_transition_action_effects(self, event: Event, player_character: Character, action_data: Dict[str, Any], managers: Dict[str, Any], send_callback: SendCallback) -> str:
    #     """Helper to execute side effects of actions that do NOT cause a stage transition. Returns outcome string."""
    #     # This would be the counterpart to OnEnterActionExecutor for player-initiated effects.
    #     # Contains the if/elif chain for action types like 'use_item', 'deal_damage_player', 'apply_status_player'.
    #     pass