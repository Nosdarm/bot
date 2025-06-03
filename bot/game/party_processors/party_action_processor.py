# bot/game/party_processors/party_action_processor.py

# --- Импорты ---
import json
import uuid
import traceback
import asyncio
# ИСПРАВЛЕНИЕ: Убедимся, что все необходимые типы импортированы
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable


# Импорт модели Party (нужен для работы с объектами партий, полученными от PartyManager)
from bot.game.models.party import Party
# TODO: Импорт модели группового действия, если таковая есть
# from bot.game.models.party_action import PartyAction


# Импорт менеджера партий (PartyActionProcessor нуждается в нем для получения объектов Party и доступа к его кешам)
# PartyActionProcessor принимает PartyManager в __init__.
from bot.game.managers.party_manager import PartyManager


# TODO: Импорт других менеджеров/сервисов, которые нужны в start_party_action, add_party_action_to_queue, process_tick, complete_party_action
# Эти менеджеры будут использоваться для валидации действия, расчета длительности, применения эффектов завершения действия и т.п.
# Используйте строковые аннотации ('ManagerName') для Optional зависимостей, чтобы избежать циклов импорта.
# Раскомментируйте только те, которые нужны в методах НИЖЕ.
from bot.game.rules.rule_engine import RuleEngine # Нужен для логики групповых действий, расчетов
from bot.game.managers.location_manager import LocationManager # Нужен для группового перемещения (валидация, триггеры)
from bot.game.managers.character_manager import CharacterManager # Нужен для доступа к участникам (Char)
from bot.game.managers.npc_manager import NpcManager # Нужен для доступа к участникам (NPC), логики AI партии
from bot.game.managers.time_manager import TimeManager # Нужен для получения текущего времени
from bot.game.managers.combat_manager import CombatManager # Нужен для начала боя
# from bot.game.managers.item_manager import ItemManager # Если у партии есть общий инвентарь или действия с предметами
# from bot.game.managers.status_manager import StatusManager # Если статусы могут быть наложены на партию или участников

# TODO: Импорт процессоров, если они вызываются (EventStageProcessor для триггеров, CharacterActionProcessor для координации индивидуальных действий)
from bot.game.event_processors.event_stage_processor import EventStageProcessor # Для триггеров в complete_party_action
# from bot.game.character_processors.character_action_processor import CharacterActionProcessor # Нужен для запуска индивидуальных действий участников (напр., following_party_move)
# from bot.game.npc_processors.npc_action_processor import NpcActionProcessor # Если NPC тоже имеют свой процессор действий


# Define send callback type (нужен для отправки уведомлений о действиях партии)
# SendToChannelCallback определен в GameManager/WorldSimulationProcessor, его нужно импортировать или определить здесь
# Определим здесь, т.к. PartyActionProcessor получает его через kwargs
SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class PartyActionProcessor:
    """
    Процессор, отвечающий за управление групповыми действиями партий
    и их очередями.
    Обрабатывает начало, добавление в очередь, обновление прогресса и завершение групповых действий.
    Взаимодействует с PartyManager для доступа к объектам Party
    и с другими менеджерами/сервисами для логики самих групповых действий.
    """
    def __init__(self,
                 # --- Обязательные зависимости ---
                 # Процессор действий партии нуждается в менеджере партий для доступа к объектам Party
                 party_manager: PartyManager,
                 # Фабрика callback'ов для отправки сообщений (нужна для уведомлений партии)
                 send_callback_factory: SendCallbackFactory,

                 # --- Опциональные зависимости (ВСЕ менеджеры/сервисы, которые могут понадобиться при выполнении ЛЮБОГО группового действия) ---
                 # Получаем их из GameManager при инстанциировании Процессора.
                 # Раскомментируйте и добавьте в список параметров только те, которые реально нужны в логике start_party_action, add_party_action_to_queue, process_tick, complete_party_action
                 rule_engine: Optional['RuleEngine'] = None,
                 location_manager: Optional['LocationManager'] = None,
                 character_manager: Optional['CharacterManager'] = None, # Нужен для доступа к участникам Char
                 npc_manager: Optional['NpcManager'] = None, # Нужен для доступа к участникам NPC, логики AI партии
                 time_manager: Optional['TimeManager'] = None,
                 combat_manager: Optional['CombatManager'] = None, # Нужен для начала боя
                 # item_manager: Optional['ItemManager'] = None,
                 # status_manager: Optional['StatusManager'] = None,

                 # TODO: Добавьте другие менеджеры/сервисы, которые могут понадобиться
                 # economy_manager: Optional['EconomyManager'] = None,

                 # Процессоры, которые могут понадобиться для триггеров в complete_party_action или координации участников
                 event_stage_processor: Optional['EventStageProcessor'] = None,
                 # event_action_processor: Optional['EventActionProcessor'] = None, # Если действие триггерит действие события
                 # character_action_processor: Optional['CharacterActionProcessor'] = None, # Нужен для запуска индивидуальных действий участников (напр., following_party_move)
                 # npc_action_processor: Optional['NpcActionProcessor'] = None, # Если NPC тоже имеют свой процессор действий
                ):
        print("Initializing PartyActionProcessor...")
        # --- Сохранение всех переданных аргументов в self._... ---
        # Обязательные
        self._party_manager = party_manager
        self._send_callback_factory = send_callback_factory

        # Опциональные
        self._rule_engine = rule_engine
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._time_manager = time_manager
        self._combat_manager = combat_manager
        # self._item_manager = item_manager
        # self._status_manager = status_manager
        # self._economy_manager = economy_manager

        self._event_stage_processor = event_stage_processor
        # self._event_action_processor = event_action_processor
        # self._character_action_processor = character_action_processor
        # self._npc_action_processor = npc_action_processor


        print("PartyActionProcessor initialized.")

    # Method to check if a party is busy (STAYS IN PartyManager)
    # def is_party_busy(self, party_id: str) -> bool: ... (STAYS IN PartyManager)


    # Methods for managing party group actions (MOVED FROM PartyManager)

    async def start_party_action(self, party_id: str, action_data: Dict[str, Any], **kwargs) -> bool:
        """
        Starts a new GROUP action for the party.
        action_data: Dict containing action details (type, target_id, callback_data, etc.).
        kwargs: Additional managers/services passed during the call (e.g., from CommandRouter).
        These managers can be used for validation or duration calculation.
        Returns True if the action was successfully started, False otherwise (e.g., party is busy or validation failed).
        """
        print(f"PartyActionProcessor: Attempting to start party action for party {party_id}: {action_data.get('type')}")
        # Get the party object from the party manager (synchronous call)
        party = self._party_manager.get_party(party_id)
        if not party:
             print(f"PartyActionProcessor: Error starting party action: Party {party_id} not found.")
             return False

        action_type = action_data.get('type')
        if not action_type:
             print(f"PartyActionProcessor: Error starting party action: action_data is missing 'type'.")
             await self._notify_party(party_id, f"❌ Failed to start group action: Action type is missing.") # Example
             return False

        # Check if the party is busy (using PartyManager's method)
        if self._party_manager.is_party_busy(party_id):
             print(f"PartyActionProcessor: Party {party_id} is busy. Cannot start new action directly.")
             # TODO: Determine if this action type is allowed to be queued.
             # If allowed:
             # return await self.add_party_action_to_queue(party_id, action_data, **kwargs) # Pass all kwargs along
             # If not allowed:
             await self._notify_party(party_id, f"❌ Your party is busy and cannot start action '{action_type}'.") # Example notification
             return False # Party is busy and cannot start the action immediately or queue it


        # --- Perform start action logic: validation and duration calculation ---
        # Delegate to a helper method to keep this method cleaner. Pass party_id and action_data.
        # FIX: Pass party_id explicitly to the helper method
        start_successful = await self._execute_start_action_logic(party_id, action_data, **kwargs)
        if not start_successful:
             # If the start logic returned False (e.g., validation failed)
             return False


        # --- Set the current group action in the Party object ---
        # Get the party again in case _execute_start_action_logic was async and state could have changed
        party = self._party_manager.get_party(party_id)
        if not party: # Check just in case
             print(f"PartyActionProcessor: Error starting party action after start logic: Party {party_id} not found.")
             return False # Cannot set action if party disappeared

        party.current_action = action_data # action_data is already populated in _execute_start_action_logic
        # Mark the party as dirty via its manager
        # PartyManager._dirty_parties is directly accessible to the processor
        self._party_manager._dirty_parties.add(party_id)
        # Add the party to the active entities cache via its manager
        # PartyManager._parties_with_active_action is directly accessible
        self._party_manager._parties_with_active_action.add(party_id)


        print(f"PartyActionProcessor: Party {party_id} action '{action_data['type']}' started. Duration: {action_data.get('total_duration', 0.0):.1f}. Marked as dirty.")

        # Saving to DB will happen when save_all_parties is called via PersistenceManager (called by WorldSimulationProcessor)

        # TODO: Notify the party about the action start? Requires send_callback_factory (injected)
        # await self._notify_party(party_id, f"Your party started action: '{action_type}'.") # Needs _notify_party method

        return True # Successfully started

    async def _execute_start_action_logic(self, party_id: str, action_data: Dict[str, Any], **kwargs) -> bool:
         """
         Helper method to perform validation and duration calculation for a party action
         that is about to start. Modifies action_data in place.
         Returns True if validation passes, False otherwise.
         kwargs: Managers/services needed for validation/calculation.
         """
         party = self._party_manager.get_party(party_id)
         if not party: return False # Should not happen if called from start_party_action, but safety check

         action_type = action_data.get('type')
         print(f"PartyActionProcessor: Executing start logic for party {party_id}, action type '{action_type}'.")

         # Get necessary managers from kwargs or processor's __init__ attributes.
         # Use kwargs.get(..., self._attribute) for flexibility.
         time_manager = kwargs.get('time_manager', self._time_manager)
         rule_engine = kwargs.get('rule_engine', self._rule_engine)
         location_manager = kwargs.get('location_manager', self._location_manager) # Needed for move validation
         # TODO: Get other managers needed for action_data validation (ItemManager, NpcManager, CombatManager, etc.)


         # TODO: Implement validation and total_duration calculation using RuleEngine
         calculated_duration = action_data.get('total_duration', 0.0) # Default to value in data, if any
         if rule_engine and hasattr(rule_engine, 'calculate_party_action_duration'): # Assuming RuleEngine has this method
              try:
                   # RuleEngine can calculate duration based on action type, party, context, managers.
                   # Pass all kwargs along so RuleEngine can use other managers.
                   calculated_duration = await rule_engine.calculate_party_action_duration(action_type, party=party, action_context=action_data, **kwargs)
              except Exception as e:
                   print(f"PartyActionProcessor: Error calculating duration for party action type '{action_type}' for party {party_id}: {e}")
                   import traceback
                   print(traceback.format_exc())
                   # Fallback to default or provided duration on error
                   calculated_duration = action_data.get('total_duration', 0.0)

         # Ensure duration is float/int
         try:
             action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
         except (ValueError, TypeError):
              print(f"PartyActionProcessor: Warning: Calculated duration is not a valid number for party action type '{action_type}'. Setting to 0.0.")
              action_data['total_duration'] = 0.0


         # TODO: Add other validations (target exists? party location allows action? party members meet requirements? etc.)
         if action_type == 'move':
              target_location_id = action_data.get('target_location_id')
              if not target_location_id:
                   print(f"PartyActionProcessor: Error starting party move action: Missing target_location_id in action_data.")
                   await self._notify_party(party_id, f"❌ Move error: Target location is missing.") # Example
                   return False

              # Validation: Does the target location exist?
              if location_manager and hasattr(location_manager, 'get_location_static') and location_manager.get_location_static(target_location_id) is None:
                  print(f"PartyActionProcessor: Error starting party move action: Target location '{target_location_id}' does not exist.")
                  await self._notify_party(party_id, f"❌ Move error: Location '{target_location_id}' does not exist.") # Example
                  return False

              # TODO: Additional validation: Is the location accessible from the party's current location?
              # current_location_id = getattr(party, 'location_id', None)
              # if current_location_id and location_manager and hasattr(location_manager, 'get_connected_locations'):
              #      connected_locations = location_manager.get_connected_locations(current_location_id)
              #      # Need to check if target_location_id is a value in connected_locations (where keys are exit names)
              #      is_accessible = target_location_id in connected_locations.values()
              #      if not is_accessible:
              #           print(f"PartyActionProcessor: Error starting party move action: Target location '{target_location_id}' is not accessible from '{current_location_id}'.")
              #           await self._notify_party(party_id, f"❌ Move error: Location '{target_location_id}' is not accessible from your current location.") # Example
              #           return False


              # Save target_location_id in callback_data for use in complete_party_action
              if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                  action_data['callback_data'] = {}
              action_data['callback_data']['target_location_id'] = target_location_id


         # TODO: Add validation and duration calculation for other party action types
         # elif action_type == 'party_craft':
         #     recipe_id = action_data.get('recipe_id')
         #     if not recipe_id: ... error ...
         #     # TODO: Check inventory (Party Inventory or members' inventory), skills, etc. (ItemManager, PartyManager/RuleEngine, CharacterManager/NpcManager)
         #     # TODO: Calculate total_duration for crafting (RuleEngine)
         #     pass
         # elif action_type == 'explore': ...
         # elif action_type == 'combat_setup': # Action to initiate combat with target(s)
         #      # Requires CombatManager, CharacterManager, NpcManager
         #      target_ids = action_data.get('target_entity_ids', [])
         #      if not target_ids: ... error ...
         #      # TODO: Validate targets exist, are attackable, are in the same location?
         #      # duration might be 0 for instant combat start, or short delay to gather
         #      pass


         else:
              # For unknown or instant actions, if no specific validation is needed,
              # just ensure total_duration is set (can be 0).
              if 'total_duration' not in action_data or action_data['total_duration'] is None:
                   print(f"PartyActionProcessor: Warning: Party action type '{action_type}' has no total_duration specified. Setting to 0.0.")
                   action_data['total_duration'] = 0.0
              try: action_data['total_duration'] = float(action_data['total_duration'])
              except (ValueError, TypeError): action_data['total_duration'] = 0.0


         # --- Set start time and progress ---
         # Start time is set here during the start logic, not in process_tick.
         if time_manager and hasattr(time_manager, 'get_current_game_time'):
              action_data['start_game_time'] = time_manager.get_current_game_time()
         else:
              print(f"PartyActionProcessor: Warning: Cannot get current game time for party action '{action_type}'. TimeManager not available or has no get_current_game_time method. Start time is None.")
              action_data['start_game_time'] = None # Or could this be an error and return False? Leaving None for now.

         action_data['progress'] = 0.0 # Progress starts at 0

         print(f"PartyActionProcessor: Start logic successful for party {party_id}, action type '{action_type}'. Duration: {action_data.get('total_duration', 0.0):.1f}")

         return True # Validation passed, action_data is ready


    async def add_party_action_to_queue(self, party_id: str, action_data: Dict[str, Any], **kwargs) -> bool:
        """
        Adds a new GROUP action to the party's queue.
        kwargs: Additional managers/services for validation or duration calculation.
        Returns True if the action was successfully added, False otherwise.
        """
        print(f"PartyActionProcessor: Attempting to add party action to queue for party {party_id}: {action_data.get('type')}")
        # Get the party object from the party manager
        party = self._party_manager.get_party(party_id)
        if not party:
             print(f"PartyActionProcessor: Error adding action to queue: Party {party_id} not found.")
             return False

        action_type = action_data.get('type')
        if not action_type:
             print(f"PartyActionProcessor: Error adding action to queue: action_data is missing 'type'.")
             await self._notify_party(party_id, f"❌ Failed to add action to queue: Action type is missing.") # Example
             return False

        # --- Validation for adding to queue (can be less strict than for starting) ---
        # Get necessary managers from kwargs or processor's __init__ attributes.
        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        location_manager = kwargs.get('location_manager', self._location_manager) # Get LocationManager for move validation


        if action_type == 'move':
             target_location_id = action_data.get('target_location_id')
             if not target_location_id:
                  print(f"PartyActionProcessor: Error adding party move action to queue: Missing target_location_id in action_data.")
                  await self._notify_party(party_id, f"❌ Failed to add move to queue: Target location is missing.") # Example
                  return False
             # Basic validation: Does the target location exist? (optional for queue)
             if location_manager and hasattr(location_manager, 'get_location_static') and location_manager.get_location_static(target_location_id) is None:
                 print(f"PartyActionProcessor: Error adding party move action to queue: Target location '{target_location_id}' does not exist.")
                 await self._notify_party(party_id, f"❌ Failed to add move to queue: Location '{target_location_id}' does not exist.") # Example
                 return False
             # Save target_location_id in callback_data for complete_party_action
             if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                 action_data['callback_data'] = {}
             action_data['callback_data']['target_location_id'] = action_data.get('target_location_id')


        # TODO: Implement total_duration calculation using RuleEngine (if injected and has method)
        # It's important to calculate duration BEFORE adding to the queue so it's saved.
        calculated_duration = action_data.get('total_duration', 0.0) # Default to value in data, if any
        if rule_engine and hasattr(rule_engine, 'calculate_party_action_duration'): # Use the same duration calculation method as for starting
             try:
                  # Pass context including location_manager for move duration calculation if needed
                  # Pass all kwargs along so RuleEngine can use other managers.
                  calculated_duration = await rule_engine.calculate_party_action_duration(action_type, party=party, action_context=action_data, **kwargs)
             except Exception as e:
                  print(f"PartyActionProcessor: Error calculating duration for party action type '{action_type}' for party {party_id} in queue: {e}")
                  import traceback
                  print(traceback.format_exc())
                  # Fallback to default or provided duration on error
                  calculated_duration = action_data.get('total_duration', 0.0)

        try: action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
        except (ValueError, TypeError): action_data['total_duration'] = 0.0


        action_data['start_game_time'] = None # Start time is not known while the action is in the queue
        action_data['progress'] = 0.0 # Progress is always 0 in the queue


        # Add the action to the end of the queue
        # Ensure action_queue exists and is a list in the Party model
        if not hasattr(party, 'action_queue') or not isinstance(party.action_queue, list):
             print(f"PartyActionProcessor: Warning: Party {party_id} model has no 'action_queue' list or it's incorrect type. Creating empty list.")
             party.action_queue = [] # Create an empty queue if it doesn't exist or is incorrect

        party.action_queue.append(action_data)
        # Mark the party as dirty via its manager
        self._party_manager._dirty_parties.add(party_id)
        # A party is considered "active" for tick purposes as long as it has a queue or an action.
        self._party_manager._parties_with_active_action.add(party_id)


        print(f"PartyActionProcessor: Action '{action_data['type']}' added to queue for party {party_id}. Queue length: {len(party.action_queue)}. Marked as dirty.")

        # Saving to DB will happen when save_all_parties is called via PersistenceManager

        # TODO: Notify the party about successful queuing? Requires send_callback_factory (injected)
        # await self._notify_party(party_id, f"Action '{action_type}' added to your party's queue.") # Example

        return True # Successfully added to queue


    # Method to process tick for ONE party (MOVED FROM PartyManager)
    # WorldSimulationProcessor will call this method for each party ID that is in the PartyManager._parties_with_active_action cache.
    async def process_tick(self, party_id: str, game_time_delta: float, **kwargs) -> None:
        """
        Processes the tick for the party's current GROUP action.
        This method is called by WorldSimulationProcessor for each active party.
        Updates progress, completes the action if necessary, starts the next from the queue.
        kwargs: Additional managers/services (time_manager, send_callback_factory, etc.) passed by WSP.
        """
        # print(f"PartyActionProcessor: Processing tick for party {party_id}...") # Can be very noisy

        # Get the party object from the party manager (synchronous call)
        party = self._party_manager.get_party(party_id)
        # Check if the party is still in the cache. If not, or if it has no action AND an empty queue, remove from active (in party manager) and exit.
        # Ensure the Party object has current_action and action_queue attributes before checking
        if not party or (getattr(party, 'current_action', None) is None and (hasattr(party, 'action_queue') and not party.action_queue)):
             # Remove from the active entities cache via the party manager.
             # _parties_with_active_action is directly accessible to the processor.
             self._party_manager._parties_with_active_action.discard(party_id)
             # print(f"PartyActionProcessor: Skipping tick for party {party_id} (not found, no action, or empty queue).")
             return

        current_action = getattr(party, 'current_action', None)
        action_completed = False # Completion flag


        # --- Update progress of the current action (if there is one) ---
        if current_action is not None:
             duration = current_action.get('total_duration', 0.0)
             if duration is None: # Handle case if total_duration is None (e.g., permanent action)
                 # print(f"PartyActionProcessor: Party {party_id} action '{current_action.get('type', 'Unknown')}' has None duration. Assuming it's ongoing.") # Can be noisy
                 # Do nothing with progress, action continues permanently until cancelled or triggered otherwise.
                 pass # Progress doesn't change, dirty is not marked due to progress.
             elif duration <= 0:
                  print(f"PartyActionProcessor: Party {party_id} action '{current_action.get('type', 'Unknown')}' is instant (duration <= 0). Marking as completed.")
                  action_completed = True
             else:
                  progress = current_action.get('progress', 0.0)
                  if not isinstance(progress, (int, float)):
                       print(f"PartyActionProcessor: Warning: Progress for party {party_id} action '{current_action.get('type', 'Unknown')}' is not a number ({progress}). Resetting to 0.0.")
                       progress = 0.0

                  current_action['progress'] = progress + game_time_delta
                  party.current_action = current_action # Ensure the change is saved in the Party object
                  # Mark the party as dirty via its manager
                  self._party_manager._dirty_parties.add(party_id)

                  # print(f"PartyActionProcessor: Party {party_id} action '{current_action.get('type', 'Unknown')}'. Progress: {current_action['progress']:.2f}/{duration:.1f}") # Debug

                  # --- Check for action completion ---
                  if current_action['progress'] >= duration:
                       print(f"PartyActionProcessor: Party {party_id} action '{current_action.get('type', 'Unknown')}' completed.")
                       action_completed = True


        # --- Handle action completion ---
        # This block executes IF the action completed in THIS tick.
        if action_completed and current_action is not None: # Check current_action != None in case it was reset externally
             # complete_party_action will reset current_action, mark dirty, and start the next from the queue (if any)
             # Pass all kwargs from WorldTick along to complete_party_action
             await self.complete_party_action(party_id, current_action, **kwargs)


        # --- Check if the party should be removed from active after completion or if there was no action and the queue is empty ---
        # complete_party_action has already started the next action OR left current_action = None.
        # process_tick needs to remove from _parties_with_active_action if the party is no longer active.
        # Check the party's state AGAIN after potential action completion and starting the next one.
        # Ensure the Party object has current_action and action_queue attributes before checking
        if getattr(party, 'current_action', None) is None and (hasattr(party, 'action_queue') and not party.action_queue):
             # Remove from the active entities cache via the party manager.
             # _parties_with_active_action is directly accessible to the processor.
             self._party_manager._parties_with_active_action.discard(party_id)
             # print(f"PartyActionProcessor: Party {party_id} has no more actions. Removed from active list.")


        # Saving the updated party state (if it was marked dirty) will happen in save_all_parties.
        # process_tick marked the party dirty if progress changed.
        # complete_party_action will mark the party dirty if the action completed and/or the queue changed.


    # Method to complete a GROUP action for the party (MOVED FROM PartyManager)
    # Called from process_tick when the action is completed.
    async def complete_party_action(self, party_id: str, completed_action_data: Dict[str, Any], **kwargs) -> None:
        """
        Handles the completion of a GROUP action for the party.
        Executes completion logic, resets current_action, starts the next from the queue.
        kwargs: Additional managers/services passed from WorldTick (send_callback_factory, item_manager, location_manager, etc.).
        """
        print(f"PartyActionProcessor: Completing action for party {party_id}: {completed_action_data.get('type')}")
        # Get the party object from the party manager
        party = self._party_manager.get_party(party_id)
        if not party:
             print(f"PartyActionProcessor: Error completing action: Party {party_id} not found.")
             return # Cannot complete action

        # TODO: --- EXECUTE ACTION COMPLETION LOGIC ---
        action_type = completed_action_data.get('type')
        callback_data = completed_action_data.get('callback_data', {})
        # Get necessary managers from kwargs or processor's __init__ attributes
        send_callback_factory = kwargs.get('send_callback_factory', self._send_callback_factory) # Get send callback factory
        item_manager = kwargs.get('item_manager', self._item_manager)
        location_manager = kwargs.get('location_manager', self._location_manager)
        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        status_manager = kwargs.get('status_manager', self._status_manager)
        combat_manager = kwargs.get('combat_manager', self._combat_manager)
        character_manager = kwargs.get('character_manager', self._character_manager) # Need for party members
        npc_manager = kwargs.get('npc_manager', self._npc_manager) # Need for party members (NPCs)
        # TODO: Get other managers/processors needed for completion logic (EventStageProcessor, EventActionProcessor?)
        event_stage_processor = kwargs.get('event_stage_processor', self._event_stage_processor)
        # event_action_processor = kwargs.get('event_action_processor', self._event_action_processor)
        # character_action_processor = kwargs.get('character_action_processor', self._character_action_processor) # Need for coordinating member actions


        # TODO: Define how to get the notification channel for the party (e.g., from Party model or leader's channel)
        # For now, use _notify_party helper which iterates members.


        try:
            if action_type == 'move':
                 # Party movement action completed. Party has arrived at the location.
                 target_location_id = callback_data.get('target_location_id')
                 old_location_id = getattr(party, 'location_id', None) # Current location before update

                 # For movement, LocationManager must be available for triggers
                 if target_location_id and location_manager and hasattr(location_manager, 'handle_entity_arrival') and hasattr(location_manager, 'handle_entity_departure'): # Ensure trigger methods are available
                      # 1. Update the party's location in the PartyManager cache
                      # NOTE: Location is updated only ON COMPLETION of the long-duration move action.
                      # If the action is instant (duration <= 0), this happens in the same tick it was started.
                      print(f"PartyActionProcessor: Updating party {party_id} location in cache from {old_location_id} to {target_location_id}.")
                      party.location_id = target_location_id
                      # Mark the party as dirty via its manager
                      self._party_manager._dirty_parties.add(party_id)

                      # 2. Handle OnExit triggers for the old location (if there was one)
                      # Pass all managers/services from kwargs so triggers can use them
                      if old_location_id: # Don't call OnExit if the party started without a location
                           print(f"PartyActionProcessor: Triggering OnExit for location {old_location_id}.")
                           # LocationManager handles triggers for the party itself
                           await location_manager.handle_entity_departure(old_location_id, party_id, 'Party', **kwargs)
                           # TODO: Optionally, trigger OnExit for EACH MEMBER if needed? Probably not necessary if party handles location.


                      # 3. Handle OnEnter triggers for the new location
                      # Pass all managers/services from kwargs so triggers can use them
                      print(f"PartyActionProcessor: Triggering OnEnter for location {target_location_id}.")
                      # LocationManager handles triggers for the party itself
                      await location_manager.handle_entity_arrival(target_location_id, party_id, 'Party', **kwargs)

                      # TODO: Coordinate party members' locations?
                      # If members are explicitly following the party, their individual move actions
                      # might complete around the same time or be cancelled/updated by this.
                      # The 'following_party' action type could be instant for members,
                      # and their ActionProcessors call their own move completion logic,
                      # which just updates their location to the party's location.
                      # Or, PartyActionProcessor explicitly tells CharacterActionProcessor/NpcActionProcessor
                      # to set the member's location.
                      # Example: Iterate through members and tell their action processors to move them instantly
                      # if character_action_processor and character_manager and npc_manager:
                      #      member_ids = list(party.members) # Copy list to avoid modification issues
                      #      for member_id in member_ids:
                      #           member_char = character_manager.get_character(member_id) if character_manager and hasattr(character_manager, 'get_character') else None
                      #           member_npc = npc_manager.get_npc(member_id) if not member_char and npc_manager and hasattr(npc_manager, 'get_npc') else None
                      #           if member_char:
                      #               # Tell CharacterActionProcessor to move this character instantly
                      #               # This assumes CharAP has a method like set_location_instantly or similar
                      #               # which just updates the character's location in CharManager and marks dirty.
                      #               # await character_action_processor.set_location_instantly(member_id, target_location_id, **kwargs) # Example
                      #               # OR, if members have the 'following_party' action, trigger its completion?
                      #               pass # How members' location syncs is a key design point

                      # TODO: Notify the party about arrival.
                      # location_name = location_manager.get_location_name(target_location_id) if location_manager and hasattr(location_manager, 'get_location_name') else target_location_id
                      # await self._notify_party(party_id, f"Your party arrived at '{location_name}'.") # Example
                      print(f"PartyActionProcessor: Party {party_id} completed move action to {target_location_id}. Triggers processed.")


                 else:
                       print("PartyActionProcessor: Error completing party move action: Required managers/data not available or LocationManager trigger methods missing.")
                       # TODO: What to do if move completed but arrival/trigger logic failed?
                       # Notify the party of the error? Rollback move? (Complex)
                       await self._notify_party(party_id, f"❌ Error completing party move. An internal error occurred.") # Example


            # TODO: Add completion logic for other party action types
            # elif action_type == 'party_craft':
            #      # Party crafting action completed. Create item(s), add to party inventory.
            #      # Requires ItemManager, PartyManager (for party inventory), RuleEngine?
            #      item_template_id = callback_data.get('item_template_id') or completed_action_data.get('item_template_id')
            #      if item_template_id:
            #           item_manager = kwargs.get('item_manager', self._item_manager)
            #           party_manager = self._party_manager # Already have it
            #           if item_manager and party_manager and hasattr(party_manager, 'add_item_to_party_inventory'): # Need add_item_to_party_inventory in PartyManager
            #                try:
            #                     item_data_for_creation = {'template_id': item_template_id, 'state_variables': completed_action_data.get('result_state_variables', {})}
            #                     item_id = await item_manager.create_item(item_data_for_creation, **kwargs) # ItemManager creates and saves item
            #                     if item_id:
            #                          success = await party_manager.add_item_to_party_inventory(party_id, item_id, **kwargs) # PartyManager adds item ID to party inventory list and saves party
            #                          if success:
            #                               print(f"PartyActionProcessor: Created item {item_id} added to inventory of party {party_id}.")
            #                               # TODO: Notify party
            #                          else:
            #                               print(f"PartyActionProcessor: Error adding created item {item_id} to party inventory.")
            #                               # TODO: What to do with item? Drop? Delete? Notify?
            #                     else:
            #                          print(f"PartyActionProcessor: Error creating item from template '{item_template_id}'.")
            #                          # TODO: What to do?
            #                except Exception as e: ... error handling ...
            #           else: ... warning ...
            #      else: ... warning ...

            # elif action_type == 'combat_setup':
            #      # Party action to setup/initiate combat has completed.
            #      # This action might represent the 'time to get ready'.
            #      # Now, initiate the actual combat.
            #      # Requires CombatManager, CharacterManager, NpcManager
            #      combat_manager = kwargs.get('combat_manager', self._combat_manager)
            #      target_ids = completed_action_data.get('target_entity_ids', [])
            #      # Ensure all members are in the same location and not busy with conflicting actions?
            #      if combat_manager and hasattr(combat_manager, 'start_combat_from_party_action'): # Assuming CombatManager has this method
            #           print(f"PartyActionProcessor: Party {party_id} combat setup completed. Initiating combat.")
            #           # CombatManager handles creating the combat instance, adding participants, and starting the first round.
            #           # It needs the party, target IDs, location, and access to all other managers/processors.
            #           # Pass all relevant data and kwargs.
            #           await combat_manager.start_combat_from_party_action(party, target_ids, **kwargs) # start_combat_from_party_action expects party object and kwargs
            #      else:
            #           print(f"PartyActionProcessor: Warning: Cannot initiate combat. CombatManager or start_combat_from_party_action method not available.")
            #           await self._notify_party(party_id, f"❌ Error initiating combat.") # Example

            # elif action_type == 'rest':
            #      # Party rest action completed. Restore health/mana, remove statuses for members.
            #      # Requires CharacterManager, NpcManager, StatusManager, RuleEngine
            #      character_manager = kwargs.get('character_manager', self._character_manager)
            #      npc_manager = kwargs.get('npc_manager', self._npc_manager)
            #      status_manager = kwargs.get('status_manager', self._status_manager)
            #      rule_engine = kwargs.get('rule_engine', self._rule_engine)
            #      # ... rest logic ...
            #      # Example: Iterate through members and apply rest effects via their managers or directly
            #      # member_ids = list(party.members)
            #      # for member_id in member_ids:
            #      #      member_char = character_manager.get_character(member_id) if character_manager and hasattr(character_manager, 'get_character') else None
            #      #      member_npc = npc_manager.get_npc(member_id) if not member_char and npc_manager and hasattr(npc_manager, 'get_npc') else None
            #      #      if member_char and rule_engine and hasattr(rule_engine, 'calculate_rest_recovery'):
            #      #           recovery = await rule_engine.calculate_rest_recovery(member_char, duration=completed_action_data.get('total_duration'), party_context=party, **kwargs)
            #      #           member_char.health = min(member_char.health + recovery.get('health', 0), member_char.max_health)
            #      #           character_manager._dirty_characters.add(member_id) # Mark member dirty
            #      #      # TODO: Remove fatigue/other rest-specific statuses via StatusManager


            else:
                 print(f"PartyActionProcessor: Warning: Unhandled group action type '{action_type}' completed for party {party_id}. No specific completion logic executed.")
                 await self._notify_party(party_id, f"Party action '{action_type}' completed.")


        except Exception as e:
            print(f"PartyActionProcessor: ❌ CRITICAL ERROR during party action completion logic for party {party_id} action '{action_type}': {e}")
            import traceback
            print(traceback.format_exc())
            # TODO: Logic to handle critical error (notify GM?)
            await self._notify_party(party_id, f"❌ A critical error occurred while completing party action '{action_type}'.")


        # --- Reset current_action and start the next action from the queue ---
        party.current_action = None # Reset the current action
        # Mark the party as dirty via its manager (current_action became None)
        self._party_manager._dirty_parties.add(party_id)


        # Check the queue after completing the current action
        action_queue = getattr(party, 'action_queue', []) or []
        if action_queue:
             next_action_data = action_queue.pop(0) # Remove from the start of the queue
             # Mark the party as dirty via its manager (queue changed)
             self._party_manager._dirty_parties.add(party_id)

             print(f"PartyActionProcessor: Party {party_id} starting next action from queue: {next_action_data.get('type')}.")

             # Start the next action (call start_party_action of THIS processor)
             # Pass all necessary managers from kwargs along
             await self.start_party_action(party_id, next_action_data, **kwargs) # <-- Recursive call to processor's start_party_action


        # If the queue is empty after action completion and current_action became None,
        # the party will be removed from _parties_with_active_action at the end of process_tick.
        # (Logic for removing from _parties_with_active_action is already in process_tick of this processor)


    # Helper method to send messages to the party (requires send_callback_factory)
    # This method stays here as the Processor is responsible for action-related notifications.
    async def _notify_party(self, party_id: str, message: str) -> None:
         """
         Finds the party, determines the party's channel(s) or leader's channel, and sends a message via the send callback factory.
         Currently iterates through Character members and notifies their individual channels.
         """
         # send_callback_factory is injected in the processor's __init__
         if self._send_callback_factory is None:
              print(f"PartyActionProcessor: Warning: Cannot notify party {party_id}. SendCallbackFactory not available.")
              return

         # Get the party object from the party manager (synchronous call)
         party = self._party_manager.get_party(party_id)
         if not party:
              print(f"PartyActionProcessor: Warning: Cannot notify party {party_id}. Party not found.")
              return

         # Get CharacterManager and NpcManager to access member details
         character_manager = getattr(self, '_character_manager', None)
         # npc_manager = getattr(self, '_npc_manager', None) # If NPC members can receive messages directly

         if not character_manager:
             print(f"PartyActionProcessor: Warning: Cannot notify party {party_id}. CharacterManager not available.")
             return

         # TODO: Determine the party's primary notification channel(s).
         # Option 1: A dedicated party channel (store channel_id in Party model state_variables?).
         # Option 2: Notify each member's individual channel.
         # Option 3: Notify the leader's channel.
         # Let's implement Option 2 (notify each character member) as it's the most general for now.

         notified_users = set() # To avoid sending duplicate messages if a user has multiple characters in the party

         member_ids = getattr(party, 'members', []) or []
         for member_id in member_ids:
              # Try getting as Character first
              member_char = character_manager.get_character(member_id)
              if member_char:
                   # Assuming Character model has discord_user_id and discord_channel_id (or a method to get it)
                   discord_user_id = getattr(member_char, 'discord_user_id', None)
                   # TODO: Method to get notification channel for a Character?
                   # Example: Use discord_user_id to find the user's primary bot channel (e.g., from GameManager/UserRegistry)
                   # For now, let's assume discord_channel_id is directly on the Character model (less ideal but simple)
                   discord_channel_id = getattr(member_char, 'discord_channel_id', None)


                   if discord_user_id is not None and discord_user_id not in notified_users and discord_channel_id is not None:
                        # We have a user ID and a channel ID, and haven't notified this user yet
                        send_callback = self._send_callback_factory(discord_channel_id)
                        try:
                            await send_callback(message)
                            notified_users.add(discord_user_id) # Mark user as notified
                        except Exception as e:
                            print(f"PartyActionProcessor: Error sending notification to character {member_id} (user {discord_user_id}) in channel {discord_channel_id}: {e}")
                   elif discord_user_id is not None and discord_user_id in notified_users:
                        # User already notified via another character in the party
                        pass
                   else:
                         # No Discord user ID or channel ID for this character member
                         print(f"PartyActionProcessor: Warning: Cannot notify character member {member_id} of party {party_id}. No Discord user ID or channel ID found on character model.")

              # TODO: Handle notifying NPC members if applicable (e.g., logging their "thoughts"?)
              # elif npc_manager:
              #      member_npc = npc_manager.get_npc(member_id)
              #      if member_npc:
              #           # NPC specific notification logic? Log to GM channel?
              #           pass


         if not notified_users:
             print(f"PartyActionProcessor: Warning: No players were notified for party {party_id} action update.")


    # NOTE: get_parties_with_active_action remains in PartyManager.

    # NOTE: process_tick (for ONE party) is here and implemented above.


# End of PartyActionProcessor class
