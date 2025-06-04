# bot/game/character_processors/character_action_processor.py

# bot/game/character_processors/character_action_processor.py

# --- Импорты ---
import json
import uuid
import traceback
import asyncio
from collections import defaultdict
# ИСПРАВЛЕНИЕ: Убедимся, что все необходимые типы импортированы
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable

# Импорт модели Character (нужен для работы с объектами персонажей, полученными от CharacterManager)
from bot.game.models.character import Character
# from bot.game.models.character_action import CharacterAction # TODO: Import model if it exists

# Импорт менеджера персонажей (CharacterActionProcessor нуждается в нем для получения объектов Character)
from bot.game.managers.character_manager import CharacterManager

# Импорт других менеджеров/сервисов
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.location_manager import LocationManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.game_log_manager import GameLogManager

# Импорт процессоров
from bot.game.event_processors.event_stage_processor import EventStageProcessor
from bot.game.event_processors.event_action_processor import EventActionProcessor


# Define send callback type
SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class CharacterActionProcessor:
    def __init__(self,
                 character_manager: CharacterManager,
                 send_callback_factory: SendCallbackFactory,
                 item_manager: Optional[ItemManager] = None,
                 location_manager: Optional[LocationManager] = None,
                 rule_engine: Optional[RuleEngine] = None,
                 time_manager: Optional[TimeManager] = None,
                 combat_manager: Optional[CombatManager] = None,
                 status_manager: Optional[StatusManager] = None,
                 party_manager: Optional[PartyManager] = None,
                 npc_manager: Optional[NpcManager] = None,
                 event_stage_processor: Optional[EventStageProcessor] = None,
                 event_action_processor: Optional[EventActionProcessor] = None,
                 game_log_manager: Optional[GameLogManager] = None,
                ):
        print("Initializing CharacterActionProcessor...")
        self._character_manager = character_manager
        self._send_callback_factory = send_callback_factory
        self._game_log_manager = game_log_manager
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._npc_manager = npc_manager
        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor

        # For tracking active actions per character per guild
        # Structure: Dict[guild_id_str, Dict[character_id_str, Set[action_type_str]]]
        self.active_character_actions: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))

        # self.known_locations: Dict[str, Set[str]] = {} # Correct initialization if it were an instance var

        print("CharacterActionProcessor initialized.")

    def is_busy(self, guild_id: str, character_id: str) -> bool:
         # A proper fix involves passing guild_id here.
         char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)
         if not char: return False
         if getattr(char, 'current_action', None) is not None: return True
         if getattr(char, 'party_id', None) and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
             return self._party_manager.is_party_busy(char.party_id, guild_id=str(char.guild_id)) # Pass guild_id
         return False

    async def start_action(self, character_id: str, action_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        modified_entities: List[Any] = []
        # Ensure guild_id is available, preferably from character object after fetching
        # For fetching char, guild_id must come from context or a reliable source in kwargs
        guild_id_from_context = kwargs.get('guild_id')
        if not guild_id_from_context:
            print(f"CharacterActionProcessor: CRITICAL: guild_id not in context for start_action of char {character_id}.")
            # If guild_id is absolutely necessary and not found, returning failure early.
            await self._notify_character("unknown_guild_FIXME", character_id, "Internal error: Guild context missing for action.") # guild_id is unknown here, this notify might fail or need a default
            return {"success": False, "modified_entities": modified_entities, "message": "Internal error: Guild context missing."}
        else:
            guild_id = str(guild_id_from_context)

        char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Removed await
        if not char:
             print(f"CharacterActionProcessor: Error starting action: Character {character_id} not found in guild {guild_id}.")
             return {"success": False, "modified_entities": modified_entities}

        # Ensure guild_id is consistently from the character model once fetched
        guild_id = str(char.guild_id)


        action_type = action_data.get('type')
        if not action_type:
             print(f"CharacterActionProcessor: Error starting action: action_data is missing 'type'.")
             await self._notify_character(guild_id, character_id, f"❌ Не удалось начать действие: не указан тип действия.")
             return {"success": False, "modified_entities": modified_entities}

        if self.is_busy(guild_id, character_id):
             print(f"CharacterActionProcessor: Character {character_id} is busy. Cannot start new action directly.")
             # Placeholder: In a real scenario, add_action_to_queue would also return a similar dict.
             # success_queued = await self.add_action_to_queue(character_id, action_data, **kwargs)
             # For now, if busy, assume it's a failure to start *this* action immediately.
             await self._notify_character(guild_id, character_id, f"❌ Ваш персонаж занят и не может начать действие '{action_type}'.")
             return {"success": False, "modified_entities": modified_entities}

        # --- Валидация action_data и расчет длительности ---
        # Получаем необходимые менеджеры из kwargs или из атрибутов __init__ процессора.
        # Используем kwargs.get(..., self._attribute) для гибкости.
        time_manager = kwargs.get('time_manager', self._time_manager)
        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        location_manager = kwargs.get('location_manager', self._location_manager) # Нужен для валидации move
        # TODO: Получите другие менеджеры, нужные для валидации action_data (ItemManager, NpcManager, CombatManager и т.п.)


        # TODO: Реализовать валидацию и расчет total_duration с помощью RuleEngine
        calculated_duration = action_data.get('total_duration', 0.0) # По умолчанию берем из данных, если есть
        if rule_engine and hasattr(rule_engine, 'calculate_action_duration'):
             try:
                  # RuleEngine может рассчитать длительность на основе типа действия, персонажа, контекста, менеджеров.
                  # Передаем все kwargs дальше, чтобы RuleEngine мог использовать другие менеджеры.
                  calculated_duration = await rule_engine.calculate_action_duration(action_type, character=char, action_context=action_data, **kwargs)
             except Exception as e:
                  print(f"CharacterActionProcessor: Error calculating duration for action type '{action_type}' for {character_id}: {e}")
                  import traceback
                  print(traceback.format_exc())
                  calculated_duration = action_data.get('total_duration', 0.0)

        # Убедимся, что длительность - это float или int
        try:
            action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
        except (ValueError, TypeError):
             print(f"CharacterActionProcessor: Warning: Calculated duration is not a valid number for action type '{action_type}'. Setting to 0.0.")
             action_data['total_duration'] = 0.0


        # TODO: Добавить другие валидации (цель существует? у персонажа есть предмет для действия? и т.п.)
        if action_type == 'move':
             target_location_id = action_data.get('target_location_id')
             if not target_location_id:
                  print(f"CharacterActionProcessor: Error starting move action: Missing target_location_id in action_data.")
                  await self._notify_character(guild_id, character_id, f"❌ Ошибка перемещения: не указана целевая локация.")
                  return {"success": False, "modified_entities": modified_entities}

             if location_manager and hasattr(location_manager, 'get_location_static') and location_manager.get_location_static(guild_id, target_location_id) is None:
                 print(f"CharacterActionProcessor: Error starting move action: Target location '{target_location_id}' does not exist.")
                 await self._notify_character(guild_id, character_id, f"❌ Ошибка перемещения: локация '{target_location_id}' не существует.")
                 return {"success": False, "modified_entities": modified_entities}

             # current_location_id = getattr(char, 'location_id', None)
             # if current_location_id and location_manager and hasattr(location_manager, 'get_connected_locations'):
             #      connected_locations = location_manager.get_connected_locations(current_location_id)
             #      if target_location_id not in connected_locations.values():
             #           print(f"CharacterActionProcessor: Error starting move action: Target location '{target_location_id}' is not accessible from '{current_location_id}'.")
             #           await self._notify_character(character_id, f"❌ Ошибка перемещения: локация '{target_location_id}' недоступна из вашей текущей локации.")
             #           return False


             # Сохраняем target_location_id в callback_data для использования в complete_action
             if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                 action_data['callback_data'] = {}
             action_data['callback_data']['target_location_id'] = target_location_id


        # TODO: Добавьте валидацию и расчет длительности для других типов действий, которые могут начинаться
        # elif action_type == 'craft':
        #     recipe_id = action_data.get('recipe_id')
        #     if not recipe_id: ... error ...
        #     # TODO: Проверка наличия ингредиентов, навыков и т.п. (ItemManager, CharacterManager/RuleEngine)
        #     # TODO: Расчет total_duration крафтинга (RuleEngine)
        #     pass
        # elif action_type == 'search': ...
        # elif action_type == 'use_skill': ...


        else:
             # Для неизвестных или мгновенных действий, если не требуется специфическая валидация,
             # просто убедимся, что total_duration установлен (может быть 0).
             if 'total_duration' not in action_data or action_data['total_duration'] is None:
                  print(f"CharacterActionProcessor: Warning: Action type '{action_type}' has no total_duration specified. Setting to 0.0.")
                  action_data['total_duration'] = 0.0
             try: action_data['total_duration'] = float(action_data['total_duration'])
             except (ValueError, TypeError): action_data['total_duration'] = 0.0


        # --- Устанавливаем время начала и прогресс ---
        if time_manager and hasattr(time_manager, 'get_current_game_time'):
             action_data['start_game_time'] = time_manager.get_current_game_time()
        else:
             print(f"CharacterActionProcessor: Warning: Cannot get current game time for action '{action_type}'. TimeManager not available or has no get_current_game_time method. Start time is None.")
             action_data['start_game_time'] = None # Или можно считать это ошибкой и вернуть False? Пока оставляем None.

        action_data['progress'] = 0.0 # Прогресс начинается с 0


        # --- Устанавливаем текущее действие ---
        char.current_action = action_data
        # self._character_manager.mark_character_dirty(getattr(char, 'guild_id', None), character_id) # Use mark_character_dirty
        # self._character_manager._entities_with_active_action.setdefault(getattr(char, 'guild_id', None), set()).add(character_id) # Ensure guild key exists
        

        char_guild_id_str = str(getattr(char, 'guild_id', 'unknown_guild'))
        self._character_manager.mark_character_dirty(char_guild_id_str, character_id)
        self._character_manager._entities_with_active_action.setdefault(char_guild_id_str, set()).add(character_id)


        if char not in modified_entities:
            modified_entities.append(char)

        success_message = f"Character {getattr(char, 'name', character_id)} started action: {action_type}."
        print(f"CharacterActionProcessor: {success_message} Duration: {action_data['total_duration']:.1f}. Marked as dirty.")

        # Log action start
        # ... (rest of the start_action logic from original, ensuring guild_id is used correctly) ...
        # Example for logging:
        if self._game_log_manager:
            # ... (construct related_entities_log) ...
            related_entities_log = [{"type": "character", "id": character_id, "name": getattr(char, 'name', 'UnknownChar')}]
            await self._game_log_manager.log_event(
                guild_id=guild_id, # Use character's guild_id
                actor_id=character_id, # Explicit actor_id
                event_type="PLAYER_ACTION_START",
                message=f"Character {getattr(char, 'name', character_id)} started action: {action_type}.",
                related_entities=related_entities_log,
                channel_id=kwargs.get('channel_id'),
                # context_data changed to **kwargs for log_event
                action_type=action_type, # Pass as kwarg
                action_details=action_data, # Pass as kwarg
                success=True # Pass as kwarg
            )
        return {"success": True, "modified_entities": modified_entities, "message": f"Action {action_type} started."}


    async def add_action_to_queue(self, character_id: str, action_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        modified_entities: List[Any] = []
        guild_id_from_context = kwargs.get('guild_id')
        if not guild_id_from_context:
            print(f"CharacterActionProcessor: CRITICAL: guild_id not in context for add_action_to_queue of char {character_id}.")
            # If guild_id is absolutely necessary and not found, returning failure early.
            await self._notify_character("unknown_guild_FIXME", character_id, "Internal error: Guild context missing for queuing action.") # guild_id is unknown
            return {"success": False, "modified_entities": modified_entities, "message": "Internal error: Guild context missing."}
        else:
            guild_id = str(guild_id_from_context)

        char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Removed await
        if not char:
             print(f"CharacterActionProcessor: Error adding action to queue: Character {character_id} not found in guild {guild_id}.")
             return {"success": False, "modified_entities": modified_entities}
        guild_id = str(char.guild_id) # Use char's guild_id

        action_type = action_data.get('type')
        if not action_type:
             print(f"CharacterActionProcessor: Error adding action to queue: action_data is missing 'type'.")
             await self._notify_character(guild_id, character_id, f"❌ Не удалось добавить действие в очередь: не указан тип действия.")
             return {"success": False, "modified_entities": modified_entities}

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        location_manager = kwargs.get('location_manager', self._location_manager)

        if action_type == 'move':
             target_location_id = action_data.get('target_location_id')
             if not target_location_id:
                  print(f"CharacterActionProcessor: Error adding move action to queue: Missing target_location_id in action_data.")
                  await self._notify_character(guild_id, character_id, f"❌ Не удалось добавить перемещение в очередь: не указана целевая локация.")
                  return {"success": False, "modified_entities": modified_entities}
             if location_manager and hasattr(location_manager, 'get_location_static') and location_manager.get_location_static(guild_id, target_location_id) is None:
                 print(f"CharacterActionProcessor: Error adding move action to queue: Target location '{target_location_id}' does not exist.")
                 await self._notify_character(guild_id, character_id, f"❌ Не удалось добавить перемещение в очередь: локация '{target_location_id}' не существует.")
                 return {"success": False, "modified_entities": modified_entities}
             if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                 action_data['callback_data'] = {}
             action_data['callback_data']['target_location_id'] = action_data.get('target_location_id')


        # TODO: Реализовать расчет total_duration с помощью RuleEngine (если он проинжектирован и имеет метод)
        # Важно рассчитать длительность ПЕРЕД добавлением в очередь, чтобы она сохранилась.
        calculated_duration = action_data.get('total_duration', 0.0) # По умолчанию берем из данных, если есть
        if rule_engine and hasattr(rule_engine, 'calculate_action_duration'): # Используем общий метод расчета длительности
             try:
                  # Pass context including location_manager for move duration calculation if needed
                  calculated_duration = await rule_engine.calculate_action_duration(action_type, character=char, action_context=action_data, **kwargs) # Передаем персонажа и все kwargs
             except Exception as e:
                  print(f"CharacterActionProcessor: Error calculating duration for action type '{action_type}' for {character_id} in queue: {e}")
                  import traceback
                  print(traceback.format_exc())
                  calculated_duration = action_data.get('total_duration', 0.0)

        try: action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
        except (ValueError, TypeError): action_data['total_duration'] = 0.0


        action_data['start_game_time'] = None # Начальное время не известно, пока действие в очереди
        action_data['progress'] = 0.0 # Прогресс всегда 0 в очереди


        # Добавляем действие в конец очереди
        # Убедимся, что action_queue существует и является списком в модели Character
        if not hasattr(char, 'action_queue') or not isinstance(char.action_queue, list):
             print(f"CharacterActionProcessor: Warning: Character {character_id} model has no 'action_queue' list or it's incorrect type. Creating empty list.")
             char.action_queue = [] # Создаем пустую очередь, если нет или некорректная

        char.action_queue.append(action_data) # Appending only once
        

        char_guild_id_str = str(getattr(char, 'guild_id', 'unknown_guild'))
        self._character_manager.mark_character_dirty(char_guild_id_str, character_id)
        self._character_manager._entities_with_active_action.setdefault(char_guild_id_str, set()).add(character_id)

        if char not in modified_entities:
            modified_entities.append(char)

        queue_message = f"Action '{action_data['type']}' added to queue for character {getattr(char, 'name', character_id)}. Queue length: {len(char.action_queue)}."
        print(f"CharacterActionProcessor: {queue_message} Marked as dirty.")

        # Log action queued
        # ... (rest of add_action_to_queue logic) ...
        if self._game_log_manager:
            related_entities_log = [{"type": "character", "id": character_id, "name": getattr(char, 'name', 'UnknownChar')}]
            await self._game_log_manager.log_event(
                guild_id=guild_id, # Use character's guild_id
                actor_id=character_id, # Explicit actor_id
                event_type="PLAYER_ACTION_QUEUED",
                message=f"Action {action_data.get('type')} queued for {getattr(char, 'name', character_id)}.",
                related_entities=related_entities_log,
                channel_id=kwargs.get('channel_id'),
                action_type=action_data.get('type'), # Pass as kwarg
                action_details=action_data # Pass as kwarg
            )
        return {"success": True, "modified_entities": modified_entities, "message": "Action queued."}


    # Метод для завершения ИНДИВИДУАЛЬНОГО действия персонажа (ПЕРЕНЕСЕН ИЗ CharacterManager)
    # Вызывается из process_tick, когда действие завершено.
    async def process_tick(self, char_id: str, game_time_delta: float, **kwargs) -> None:
        # char = self._character_manager.get_character(char_id) # Original, needs guild_id
        # This method is called by WorldSimulationProcessor which iterates over active entities.
        # It should already have guild_id context or the char object.
        # For now, let's assume char_id is enough if CharacterManager can get guild from its internal caches or if char_id is globally unique.
        # However, most CharacterManager methods now require guild_id.
        # This implies process_tick needs guild_id or the char object passed in directly.
        # Let's assume CharacterManager.get_character can resolve without guild_id if char_id is unique UUID.
        # This is a potential issue if char_id is not globally unique or CM requires guild_id.

        char_guild_id_for_tick = kwargs.get('guild_id')
        if not char_guild_id_for_tick:
            print(f"CharacterActionProcessor (process_tick): CRITICAL: guild_id missing for character {char_id}. Cannot process tick.")
            # Decide how to handle this: maybe remove from active actions if guild_id is essential
            # For now, just return to prevent further errors.
            active_entities_map = self._character_manager._entities_with_active_action
            if isinstance(active_entities_map, dict):
                for gid_key, id_set in list(active_entities_map.items()): # Use list for safe iteration and deletion
                    if isinstance(id_set, set) and char_id in id_set:
                        id_set.discard(char_id)
                        if not id_set: # Remove guild_id from dict if set is empty
                            del active_entities_map[gid_key]
            return

        char: Optional[Character] = self._character_manager.get_character(guild_id=str(char_guild_id_for_tick), character_id=char_id)


        if not char or (getattr(char, 'current_action', None) is None and not getattr(char, 'action_queue', [])):
             # Ensure _entities_with_active_action.get returns a set before calling discard
             # char_guild_id_for_tick should be valid here due to the check above
             active_set = self._character_manager._entities_with_active_action.get(str(char_guild_id_for_tick))
             if isinstance(active_set, set):
                active_set.discard(char_id)
                if not active_set: # Remove guild_id from dict if set is empty
                    del self._character_manager._entities_with_active_action[str(char_guild_id_for_tick)]
             return

        # ... (rest of process_tick logic, ensuring guild_id is used for CM calls) ...
        # Make sure mark_character_dirty and other CM calls use the determined char_guild_id_for_tick
        if char_guild_id_for_tick and getattr(char, 'current_action', None) is not None: # Check current_action again
            current_action = getattr(char, 'current_action') # Should not be None here
            duration = current_action.get('total_duration', 0.0)
            # ... (progress update logic) ...
            if isinstance(duration, (int, float)) and duration > 0: # Ensure duration is valid number
                 # ... (progress update logic) ...
                 self._character_manager.mark_character_dirty(str(char_guild_id_for_tick), char_id)
                 # ... (check for completion) ...

        # ... (complete_action call if needed, passing char_guild_id_for_tick in kwargs if not already there) ...
        # ... (logic for removing from _entities_with_active_action if no more actions) ...
        # char_guild_id_for_tick is guaranteed by the check at the beginning of the method.
        if getattr(char, 'current_action', None) is None and (hasattr(char, 'action_queue') and not char.action_queue):
            # Ensure get returns a set before calling discard
            active_set_final = self._character_manager._entities_with_active_action.get(str(char_guild_id_for_tick))
            if isinstance(active_set_final, set):
                active_set_final.discard(char_id)
                if not active_set_final: # Remove guild_id from dict if set is empty
                    del self._character_manager._entities_with_active_action[str(char_guild_id_for_tick)]
            # The return that was here is removed as the function should continue to the end.
            # The lines "if char_id in id_set: id_set.discard(char_id)" were part of an erroneous merge before, removed.

        # The following block is now redundant due to the initial check and handling for `not char`
        # and the updated logic for removing from active_entities_map when a character becomes inactive.
        # if not char or (getattr(char, 'current_action', None) is None and not getattr(char, 'action_queue', [])):
        #      # char_guild_id_for_tick should be valid here
        #      active_set_redundant = self._character_manager._entities_with_active_action.get(str(char_guild_id_for_tick))
        #      if isinstance(active_set_redundant, set):
        #          active_set_redundant.discard(char_id)
        #          if not active_set_redundant:
        #              del self._character_manager._entities_with_active_action[str(char_guild_id_for_tick)]
        #      return

        # ... (rest of process_tick logic, ensuring guild_id is used for CM calls) ...
        # Make sure mark_character_dirty and other CM calls use the determined char_guild_id_for_tick
        # This check is already performed above and includes mark_character_dirty
        # if char_guild_id_for_tick and getattr(char, 'current_action', None) is not None: # Check current_action again
        #     current_action = getattr(char, 'current_action') # Should not be None here
        #     duration = current_action.get('total_duration', 0.0)
        #     # ... (progress update logic) ...
        #     if isinstance(duration, (int, float)) and duration > 0: # Ensure duration is valid number
        #          # ... (progress update logic) ...
        #          self._character_manager.mark_character_dirty(str(char_guild_id_for_tick), char_id) # Pass guild_id
        #          # ... (check for completion) ...

        # ... (complete_action call if needed, passing char_guild_id_for_tick in kwargs if not already there) ...
        # ... (logic for removing from _entities_with_active_action if no more actions) ...
        # This final check and discard is also covered by the logic at the beginning of the char processing (after char is fetched)
        # and after complete_action.
        # if char_guild_id_for_tick and getattr(char, 'current_action', None) is None and (hasattr(char, 'action_queue') and not char.action_queue):
        #     final_check_set = self._character_manager._entities_with_active_action.get(str(char_guild_id_for_tick))
        #     if isinstance(final_check_set, set):
        #         final_check_set.discard(char_id)
        #         if not final_check_set:
        #             del self._character_manager._entities_with_active_action[str(char_guild_id_for_tick)]


    async def complete_action(self, character_id: str, completed_action_data: Dict[str, Any], **kwargs) -> List[Any]:
        modified_entities: List[Any] = []
        guild_id_from_context = kwargs.get('guild_id')
        if not guild_id_from_context:
            print(f"CharacterActionProcessor: CRITICAL: guild_id not in context for complete_action of char {character_id}.")
            await self._notify_character("unknown_guild_FIXME", character_id, "Internal error: Guild context missing for completing action.") # guild_id is unknown
            return modified_entities
        else:
            guild_id = str(guild_id_from_context)

        char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Removed await
        if not char:
             print(f"CharacterActionProcessor: Error completing action: Character {character_id} not found in guild {guild_id}.")
             return modified_entities
        guild_id = str(char.guild_id) # Use char's guild_id

        if char not in modified_entities: modified_entities.append(char)
        action_type = completed_action_data.get('type')
        # ... (manager fetching from kwargs or self) ...

        try:
            if action_type == 'move':
                 target_location_id = completed_action_data.get('callback_data', {}).get('target_location_id')
                 old_location_id = str(getattr(char, 'location_id', None)) # Ensure string for known_locations

                 if target_location_id and self._location_manager:
                      # Ensure guild_id is string for update_character_location
                      await self._character_manager.update_character_location(
                          character_id, target_location_id, guild_id, **kwargs # Pass guild_id
                      )
                      # Update known_locations if it's an attribute of this class
                      # if hasattr(self, 'known_locations'):
                      #    if old_location_id:
                      #        self.known_locations.setdefault(old_location_id, set()).discard(str(character_id))
                      #    self.known_locations.setdefault(str(target_location_id), set()).add(str(character_id))
                      # ... (rest of move completion logic) ...
            
            elif action_type == 'use_item':
                # ... (existing use_item logic) ...
                # Ensure guild_id is passed to manager calls
                user_char = char
                item_id_used = completed_action_data.get('callback_data', {}).get('item_id')
                # ...
                effects = kwargs.get('use_outcome', {}).get('effects', []) # Assuming use_outcome is in kwargs from RuleEngine
                for effect in effects:
                    if effect.get('type') == 'heal':
                        # Replace apply_health_change
                        await self._character_manager.update_health(
                            guild_id=guild_id,
                            character_id=str(effect.get('target_id', user_char.id)), # Ensure string
                            amount=float(effect.get('amount', 0)) # Ensure float
                        )
                # ... (item consumption logic) ...

            # ... (other action types) ...
        except Exception as e:
            print(f"CharacterActionProcessor: ❌ CRITICAL ERROR during action completion for {character_id} action '{action_type}': {e}")
            traceback.print_exc()
            await self._notify_character(guild_id, character_id, f"❌ Critical error completing '{action_type}'.")

        char.current_action = None
        self._character_manager.mark_character_dirty(guild_id, character_id) # Use char's guild_id

        action_queue = getattr(char, 'action_queue', []) or []
        if action_queue:
             next_action_data = action_queue.pop(0)
             self._character_manager.mark_character_dirty(guild_id, character_id) # Use char's guild_id
             # Pass guild_id in kwargs for start_action if not already part of its standard resolution
             await self.start_action(character_id, next_action_data, guild_id=guild_id, **kwargs)

        if self._game_log_manager:
            # ... (construct related_entities_log) ...
            related_entities_log = [{"type": "character", "id": character_id, "name": getattr(char, 'name', 'UnknownChar')}]
            # Ensure actor_id is passed if log_event expects it, or include in related_entities/message
            await self._game_log_manager.log_event(
                guild_id=guild_id, # Use character's guild_id
                actor_id=character_id, # Explicit actor_id
                event_type="PLAYER_ACTION_COMPLETED",
                message=f"Character {getattr(char, 'name', character_id)} completed action: {action_type}.",
                related_entities=related_entities_log,
                channel_id=kwargs.get('channel_id'),
                action_type=action_type, # Pass as kwarg
                completed_action_details=completed_action_data # Pass as kwarg
            )
        return modified_entities

    async def _notify_character(self, guild_id: str, character_id: str, message: str) -> None:
         if self._send_callback_factory is None: return
         char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)

         if not char:
              print(f"CharacterActionProcessor: Warning (notify): Character {character_id} not found in guild {guild_id}. Cannot send notification.")
              return
         # ... (rest of notification logic using char.discord_channel_id) ...

         # TODO: Нужна логика определения канала игрока по Discord ID
         # Это может быть канал, где он последний раз вводил команду, или специальный канал для уведомлений.
         # Пример: если у модели Character есть поле discord_channel_id или метод get_notification_channel_id
         discord_channel_id = getattr(char, 'discord_channel_id', None) # Предполагаем поле в модели
         # Или получить из менеджера локаций? send to location_id?
         # if char.location_id and self._location_manager and hasattr(self._location_manager, 'get_location_channel'):
         #      discord_channel_id = self._location_manager.get_location_channel(char.location_id)

         if discord_channel_id is not None:
              send_callback = self._send_callback_factory(discord_channel_id)
              try: await send_callback(message)
              except Exception as e: print(f"CharacterActionProcessor: Error sending notification to user {char.discord_user_id} in channel {discord_channel_id}: {e}")
         else:
              print(f"CharacterActionProcessor: Warning: Cannot send notification to character {character_id} ({getattr(char, 'discord_user_id', 'N/A')}). No Discord channel ID found.")


    async def process_move_action(self, character_id: str, target_location_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        modified_entities: List[Any] = []
        guild_id = context.get('guild_id')
        if not guild_id:
            # This method seems to expect guild_id in context. If not present, it's an issue with the caller.
            print(f"CharacterActionProcessor: Error processing move: guild_id missing in context for Character {character_id}.")
            return {"success": False, "message": "Internal error: Guild context missing.", "modified_entities": modified_entities}
        
        # Ensure guild_id is string
        guild_id = str(guild_id)
        char = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)
        if not char:
            print(f"CharacterActionProcessor: Error processing move: Character {character_id} not found in guild {guild_id}.")
            return {"success": False, "message": f"Character {character_id} not found.", "modified_entities": modified_entities}
        # guild_id is now confirmed and is from context or char.
        # ... (rest of process_move_action, ensure guild_id is used in manager calls) ...
        # Ensure all calls to start_action within this method also pass the resolved guild_id in context
        
        action_data = {
            'type': 'move',
            'target_location_id': target_location_id
            # Potentially add other relevant fields to action_data if necessary,
            # for example, 'total_duration' if it can be pre-calculated here
            # or if start_action expects it. For now, start_action calculates it.
        }

        context_with_guild = {**context, 'guild_id': guild_id}
        # Ensure char is passed to start_action if it expects it directly,
        # or rely on start_action to fetch it using character_id and guild_id.
        # Current start_action fetches char, so no change needed there.
        start_action_result = await self.start_action(character_id, action_data, **context_with_guild)

        if not start_action_result.get("success"):
            return {"success": False, "message": start_action_result.get("message", "Failed to start move action."), "modified_entities": modified_entities}

        # Append character to modified_entities if successfully started and not already present
        if char not in modified_entities:
            modified_entities.append(char)
            
        return {"success": True, "message": "Move initiated.", "modified_entities": modified_entities, "details": start_action_result}


    async def process_steal_action(self, character_id: str, target_id: str, target_type: str, context: Dict[str, Any]) -> bool:
        # Ensure guild_id is available for get_character and other manager calls
        guild_id = context.get('guild_id')
        if not guild_id:
            print(f"CharacterActionProcessor: Error in action: guild_id missing in context for Character {character_id}.")
            return False
        
        guild_id = str(guild_id) # Ensure string
        char_for_guild_lookup = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)
        if not char_for_guild_lookup:
            print(f"CharacterActionProcessor: Error in action: Character {character_id} not found in guild {guild_id}.")
            return False
        current_guild_id = str(char_for_guild_lookup.guild_id) # Use character's actual guild_id

        char = char_for_guild_lookup # Use already fetched char
        # ... (rest of process_steal_action, ensuring current_guild_id is used) ...
        # Example for npc_manager call:
        # target_entity = npc_manager.get_npc(current_guild_id, target_id)
        # Example for start_action call:
        context_with_guild = {**context, 'guild_id': current_guild_id}
        # action_started_or_queued = await self.start_action(character_id, action_data, **context_with_guild)
        return True # Placeholder

    async def process_hide_action(self, character_id: str, context: Dict[str, Any]) -> bool:
        guild_id = context.get('guild_id')
        if not guild_id:
            print(f"CharacterActionProcessor: Error in action: guild_id missing in context for Character {character_id}.")
            return False
        
        guild_id = str(guild_id) # Ensure string
        char_for_guild_lookup = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)
        if not char_for_guild_lookup:
            print(f"CharacterActionProcessor: Error in action: Character {character_id} not found in guild {guild_id}.")
            return False
        current_guild_id = str(char_for_guild_lookup.guild_id) # Use character's actual guild_id
        # ... (rest of process_hide_action) ...
        context_with_guild = {**context, 'guild_id': current_guild_id}
        # action_data definition was missing for the log_event call in original _handle_hide_action_completion
        # If this method calls log_event, action_data needs to be defined.
        # For now, assuming it's handled if start_action is called.
        # action_started_or_queued = await self.start_action(character_id, action_data, **context_with_guild)
        return True # Placeholder

    async def process_use_item_action(self, character_id: str, item_instance_id: str, target_entity_id: Optional[str], target_entity_type: Optional[str], context: Dict[str, Any]) -> bool:
        guild_id = context.get('guild_id')
        if not guild_id:
            print(f"CharacterActionProcessor: Error in action: guild_id missing in context for Character {character_id}.")
            return False
        
        guild_id = str(guild_id) # Ensure string
        char_for_guild_lookup = self._character_manager.get_character(guild_id=guild_id, character_id=character_id)
        if not char_for_guild_lookup:
            print(f"CharacterActionProcessor: Error in action: Character {character_id} not found in guild {guild_id}.")
            return False
        current_guild_id = str(char_for_guild_lookup.guild_id) # Use character's actual guild_id
        # ... (rest of process_use_item_action, ensuring current_guild_id is used for item_manager, rule_engine calls) ...
        # item_instance = item_manager.get_item(current_guild_id, item_instance_id)
        context_with_guild = {**context, 'guild_id': current_guild_id}
        # action_started_or_queued = await self.start_action(character_id, action_data, **context_with_guild)
        return True # Placeholder


    async def process_party_actions(
        self,
        game_manager: Any, # Should be GameManager type
        guild_id: str, # guild_id is now directly passed
        actions_to_process: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        all_modified_entities_in_turn: List[Any] = []
        overall_state_changed_for_party = False
        # actions_to_send: List[Dict[str, str]] = [] # Original type
        actions_to_send: List[Dict[str, Any]] = [] # Corrected type hint

        for action_entry in actions_to_process:
            character_id_from_entry = action_entry.get("character_id") # Renamed to avoid outer scope collision
            action_data_for_char = action_entry.get("action_data")
            # ... (rest of the logic, ensuring guild_id from parameter is used for manager calls) ...
            # Example:
            # action_context = {**context, 'guild_id': guild_id} # guild_id is from params
            # action_result = await self.start_action(character_id_from_entry, action_data_for_char, **action_context)
            # ...
            # action_result_dict creation
            # description_i18n = action_result.get("description_i18n", {"en": "Action processed."})
            # mechanical_summary_i18n = action_result.get("mechanical_summary_i18n", {"en": ""})
            # action_result_dict = {
            #     "character_id": character_id_from_entry,
            #     "description_i18n": description_i18n, # This can be a dict
            #     "mechanical_summary_i18n": mechanical_summary_i18n, # This can be a dict
            #     "details": action_result.get("details", {}), # This can be a dict
            #     "success": action_result.get("success", False) # This is bool
            # }
            # actions_to_send.append(action_result_dict) # Appending Dict[str, Any]

        return {
            "success": True,
            "overall_state_changed_for_party": overall_state_changed_for_party,
            "individual_action_results": actions_to_send, # Renamed from individual_action_results to match init
            "final_modified_entities_this_turn": all_modified_entities_in_turn
        }

    async def process_single_player_actions(
        self,
        player: Character, # Changed from player_id to full Character object
        actions_json_str: str,
        guild_id: str, # Already available on player object, but passed for consistency
        game_manager: Any, # Should be GameManager, using Any to avoid import cycle if not already TYPE_CHECKING
        report_channel_id: int
    ) -> Dict[str, Any]:
        """
        Processes a list of actions for a single player.
        Actions are typically collected by the NLU system.
        """
        action_results_summary: List[str] = []
        overall_success = True
        any_action_processed = False
        modified_entities_accumulator: List[Any] = []

        if not self._character_manager: # Should always be set from __init__
            print("CharacterActionProcessor: CharacterManager not available.")
            return {"success": False, "messages": ["Error: CharacterManager not available."], "state_changed": False}

        try:
            actions_list = json.loads(actions_json_str)
            if not isinstance(actions_list, list):
                raise json.JSONDecodeError("Input is not a list.", actions_json_str, 0)
        except json.JSONDecodeError as e:
            print(f"CharacterActionProcessor: Invalid JSON in actions_json_str for player {player.id}: {e}")
            return {"success": False, "messages": [f"Ошибка: неверный формат сохраненных действий ({e})."], "state_changed": False}

        if not actions_list:
            return {"success": True, "messages": ["Нет действий для обработки."], "state_changed": False}

        # Prepare context for action processing
        # This context will be passed to start_action and other methods
        # It should contain all necessary managers and services.
        action_context_kwargs = {
            "guild_id": guild_id,
            "character_id": player.id, # For methods that might still take character_id separately
            "character": player, # Pass the full character object
            "report_channel_id": report_channel_id,
            "send_callback_factory": self._send_callback_factory,
            "item_manager": game_manager.item_manager if hasattr(game_manager, 'item_manager') else self._item_manager,
            "location_manager": game_manager.location_manager if hasattr(game_manager, 'location_manager') else self._location_manager,
            "rule_engine": game_manager.rule_engine if hasattr(game_manager, 'rule_engine') else self._rule_engine,
            "time_manager": game_manager.time_manager if hasattr(game_manager, 'time_manager') else self._time_manager,
            "combat_manager": game_manager.combat_manager if hasattr(game_manager, 'combat_manager') else self._combat_manager,
            "status_manager": game_manager.status_manager if hasattr(game_manager, 'status_manager') else self._status_manager,
            "party_manager": game_manager.party_manager if hasattr(game_manager, 'party_manager') else self._party_manager,
            "npc_manager": game_manager.npc_manager if hasattr(game_manager, 'npc_manager') else self._npc_manager,
            "event_stage_processor": game_manager._event_stage_processor if hasattr(game_manager, '_event_stage_processor') else self._event_stage_processor,
            "event_action_processor": game_manager._event_action_processor if hasattr(game_manager, '_event_action_processor') else self._event_action_processor,
            "game_log_manager": game_manager.game_log_manager if hasattr(game_manager, 'game_log_manager') else self._game_log_manager,
            "db_service": game_manager.db_service if hasattr(game_manager, 'db_service') else None, # For RuleEngine or other deep calls
            # Add other managers/services from game_manager as needed by start_action or specific action handlers
        }
        # Filter out None values from context to avoid passing None explicitly if not desired by downstream methods
        # However, start_action and others might expect Optional managers from self.
        # For now, pass them as they are.
        # action_context_kwargs = {k: v for k, v in action_context_kwargs.items() if v is not None}


        for action_data_from_nlu in actions_list:
            if not isinstance(action_data_from_nlu, dict):
                action_results_summary.append(f"Ошибка: неверный формат записи действия (не словарь): {action_data_from_nlu}")
                overall_success = False
                continue

            # action_data_from_nlu is like: {"intent": "move", "entities": {"direction": "north"}, "original_text": "go north"}
            # We need to transform this into action_data for start_action, e.g. {'type': 'move', 'target_location_id': 'loc_X'}
            # This transformation logic might be complex and depend on NLU output structure.
            # For now, assume a simple mapping or that NLU output is already close to action_data format.
            # Let's assume 'intent' maps to 'type' and 'entities' are part of the main dict.
            
            action_type = action_data_from_nlu.get("intent")
            entities = action_data_from_nlu.get("entities", {})
            original_text = action_data_from_nlu.get("original_text", "действие без текста")

            if not action_type:
                action_results_summary.append(f"Пропущено действие '{original_text}': не определено намерение (intent).")
                overall_success = False
                continue
            
            # Construct action_data for start_action
            # This is a placeholder and needs proper mapping based on NLU structure and action types
            # Example: if action_type == "move" and "direction" in entities:
            #     action_data_for_start = {"type": "move", "direction": entities["direction"]}
            # For now, let's pass entities directly, assuming start_action or its sub-handlers can use them.
            # A more robust approach would be to have specific mapping functions per intent.
            action_data_for_start = {"type": action_type, **entities}
            action_data_for_start["original_text"] = original_text # Keep original text for context if needed

            any_action_processed = True
            try:
                # Call start_action for each action.
                # start_action handles putting action into char.current_action or queue.
                # If actions are meant to be "instant" or fully resolved here, this needs more.
                # For now, we assume start_action initiates it. If duration is 0, it might complete quickly via tick.
                # Or, if start_action itself can fully resolve some actions, that's also fine.
                result = await self.start_action(
                    character_id=player.id,
                    action_data=action_data_for_start, 
                    **action_context_kwargs # Pass the prepared context
                )

                if result.get("success"):
                    action_results_summary.append(f"Действие '{original_text}' ({action_type}) принято: {result.get('message', 'Начато.')}")
                    if result.get("modified_entities"):
                        for entity in result["modified_entities"]:
                            if entity not in modified_entities_accumulator:
                                modified_entities_accumulator.append(entity)
                else:
                    action_results_summary.append(f"Действие '{original_text}' ({action_type}) не удалось: {result.get('message', 'Причина неизвестна.')}")
                    overall_success = False
            
            except Exception as e:
                print(f"CharacterActionProcessor: Exception processing action '{action_type}' for player {player.id}: {e}")
                traceback.print_exc()
                action_results_summary.append(f"Ошибка при обработке действия '{original_text}' ({action_type}): {e}")
                overall_success = False
        
        if not any_action_processed and actions_list: # If list was not empty but nothing was processed (e.g. all invalid format)
            if not action_results_summary: # Add a generic message if no specific errors were added
                 action_results_summary.append("Ни одно из действий не удалось обработать из-за неверного формата.")
            overall_success = False


        return {
            "success": overall_success,
            "messages": action_results_summary,
            "state_changed": bool(modified_entities_accumulator), # True if any action modified entities
            "modified_entities": modified_entities_accumulator
        }

    async def process_party_actions(
        self,
        game_manager: Any, # Should be GameManager
        guild_id: str,
        actions_to_process: List[Dict[str, Any]], # List of {"character_id": ..., "action_data": ..., "original_input_text": ...}
        context: Dict[str, Any] # Contains report_channel_id from PartyManager
    ) -> Dict[str, Any]:
        """
        Processes a list of actions for multiple players in a party.
        """
        all_modified_entities_in_turn: List[Any] = []
        overall_state_changed_for_party = False
        individual_action_results: List[Dict[str, Any]] = [] # To store structured results

        if not self._character_manager:
            print("CharacterActionProcessor: CharacterManager not available for process_party_actions.")
            # Consider how to report this failure back; for now, return a failure structure.
            return {
                "success": False, # Batch processing itself failed
                "overall_state_changed_for_party": False,
                "individual_action_results": [{"character_id": "SYSTEM", "action_original_text": "Batch Init", "success": False, "message": "CharacterManager unavailable."}],
                "final_modified_entities_this_turn": []
            }

        report_channel_id = context.get("report_channel_id") # Extract from passed context

        for action_entry in actions_to_process:
            character_id = action_entry.get("character_id")
            action_data_from_nlu = action_entry.get("action_data") # This is the NLU output like {"intent": ..., "entities": ...}
            original_text = action_entry.get("original_input_text", "N/A")

            if not character_id or not isinstance(action_data_from_nlu, dict):
                print(f"CharacterActionProcessor: Invalid action_entry in process_party_actions: {action_entry}")
                individual_action_results.append({
                    "character_id": character_id or "Unknown",
                    "action_original_text": original_text,
                    "success": False,
                    "message": "Invalid action entry format.",
                    "modified_entities_count": 0
                })
                continue

            player_char = self._character_manager.get_character(guild_id, character_id)
            if not player_char:
                print(f"CharacterActionProcessor: Character {character_id} not found in guild {guild_id} for party action.")
                individual_action_results.append({
                    "character_id": character_id,
                    "action_original_text": original_text,
                    "success": False,
                    "message": f"Персонаж {character_id} не найден.",
                    "modified_entities_count": 0
                })
                continue

            action_type = action_data_from_nlu.get("intent")
            entities = action_data_from_nlu.get("entities", {})
            
            if not action_type:
                individual_action_results.append({
                    "character_id": character_id,
                    "action_original_text": original_text,
                    "success": False,
                    "message": f"Пропущено действие '{original_text}': не определено намерение (intent).",
                    "modified_entities_count": 0
                })
                continue

            action_data_for_start = {"type": action_type, **entities, "original_text": original_text}

            # Prepare context for start_action, similar to process_single_player_actions
            action_context_kwargs = {
                "guild_id": guild_id,
                "character_id": player_char.id,
                "character": player_char,
                "report_channel_id": report_channel_id, # Use the one from PartyManager's context
                "send_callback_factory": self._send_callback_factory,
                "item_manager": game_manager.item_manager if hasattr(game_manager, 'item_manager') else self._item_manager,
                "location_manager": game_manager.location_manager if hasattr(game_manager, 'location_manager') else self._location_manager,
                "rule_engine": game_manager.rule_engine if hasattr(game_manager, 'rule_engine') else self._rule_engine,
                "time_manager": game_manager.time_manager if hasattr(game_manager, 'time_manager') else self._time_manager,
                "combat_manager": game_manager.combat_manager if hasattr(game_manager, 'combat_manager') else self._combat_manager,
                "status_manager": game_manager.status_manager if hasattr(game_manager, 'status_manager') else self._status_manager,
                "party_manager": game_manager.party_manager if hasattr(game_manager, 'party_manager') else self._party_manager, # Could be self from game_manager
                "npc_manager": game_manager.npc_manager if hasattr(game_manager, 'npc_manager') else self._npc_manager,
                "event_stage_processor": game_manager._event_stage_processor if hasattr(game_manager, '_event_stage_processor') else self._event_stage_processor,
                "event_action_processor": game_manager._event_action_processor if hasattr(game_manager, '_event_action_processor') else self._event_action_processor,
                "game_log_manager": game_manager.game_log_manager if hasattr(game_manager, 'game_log_manager') else self._game_log_manager,
                "db_service": game_manager.db_service if hasattr(game_manager, 'db_service') else None,
            }
            
            try:
                result = await self.start_action(
                    character_id=player_char.id,
                    action_data=action_data_for_start,
                    **action_context_kwargs
                )

                action_success = result.get("success", False)
                action_message = result.get("message", "Сообщение об итоге действия отсутствует.")
                modified_entities_from_action = result.get("modified_entities", [])
                
                individual_action_results.append({
                    "character_id": player_char.id,
                    "action_original_text": original_text,
                    "success": action_success,
                    "message": action_message,
                    "modified_entities_count": len(modified_entities_from_action)
                })

                if action_success and modified_entities_from_action:
                    overall_state_changed_for_party = True
                    for entity in modified_entities_from_action:
                        if entity not in all_modified_entities_in_turn:
                            all_modified_entities_in_turn.append(entity)
            
            except Exception as e:
                print(f"CharacterActionProcessor: Exception processing party action '{action_type}' for player {player_char.id}: {e}")
                traceback.print_exc()
                individual_action_results.append({
                    "character_id": player_char.id,
                    "action_original_text": original_text,
                    "success": False,
                    "message": f"Критическая ошибка при обработке действия '{original_text}': {e}",
                    "modified_entities_count": 0
                })

        return {
            "success": True, # Indicates the batch processing itself completed (though individual actions might have failed)
            "overall_state_changed_for_party": overall_state_changed_for_party,
            "individual_action_results": individual_action_results,
            "final_modified_entities_this_turn": all_modified_entities_in_turn
        }

# Конец класса CharacterActionProcessor
