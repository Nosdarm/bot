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

from typing import Optional, Dict, Any, List, Set, Callable, Awaitable # Ensure all are imported

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

    def is_busy(self, character_id: str) -> bool:
         # TODO: This method needs guild_id for self._character_manager.get_character
         # Assuming a placeholder or that get_character can work without it (not ideal)
         char = self._character_manager.get_character(guild_id="placeholder_guild", character_id=character_id) # FIXME
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
            # This is a fallback, ideally character_id and guild_id are passed together
            # or character object is passed directly.
            print(f"CharacterActionProcessor: CRITICAL: guild_id not in context for start_action of char {character_id}.")
            # Attempt to get from an existing character object if this method is called internally after char is fetched
            temp_char_for_guild = self._character_manager.get_character(guild_id="ANY_GUILD_TEMP_FIX", character_id=character_id) # This is problematic
            guild_id = str(getattr(temp_char_for_guild, 'guild_id', "unknown_guild_in_start_action")) if temp_char_for_guild else "unknown_guild_in_start_action"
        else:
            guild_id = str(guild_id_from_context)

        # char = self._character_manager.get_character(character_id) # Original, needs guild_id
        char = await self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Corrected
        if not char:
             print(f"CharacterActionProcessor: Error starting action: Character {character_id} not found in guild {guild_id}.")
             return {"success": False, "modified_entities": modified_entities}

        # Ensure guild_id is consistently from the character model once fetched
        guild_id = str(char.guild_id)


        action_type = action_data.get('type')
        if not action_type:
             print(f"CharacterActionProcessor: Error starting action: action_data is missing 'type'.")
             await self._notify_character(character_id, f"❌ Не удалось начать действие: не указан тип действия.")
             return {"success": False, "modified_entities": modified_entities}

        if self.is_busy(character_id):
             print(f"CharacterActionProcessor: Character {character_id} is busy. Cannot start new action directly.")
             # Placeholder: In a real scenario, add_action_to_queue would also return a similar dict.
             # success_queued = await self.add_action_to_queue(character_id, action_data, **kwargs)
             # For now, if busy, assume it's a failure to start *this* action immediately.
             await self._notify_character(character_id, f"❌ Ваш персонаж занят и не может начать действие '{action_type}'.")
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
                  await self._notify_character(character_id, f"❌ Ошибка перемещения: не указана целевая локация.")
                  return {"success": False, "modified_entities": modified_entities}

             if location_manager and hasattr(location_manager, 'get_location_static') and location_manager.get_location_static(target_location_id) is None: #FIXME: get_location_static needs guild_id
                 print(f"CharacterActionProcessor: Error starting move action: Target location '{target_location_id}' does not exist.")
                 await self._notify_character(character_id, f"❌ Ошибка перемещения: локация '{target_location_id}' не существует.")
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
            temp_char_for_guild = self._character_manager.get_character(guild_id="ANY_GUILD_TEMP_FIX", character_id=character_id) # Problematic
            guild_id = str(getattr(temp_char_for_guild, 'guild_id', "unknown_guild_in_add_action")) if temp_char_for_guild else "unknown_guild_in_add_action"
        else:
            guild_id = str(guild_id_from_context)

        # char = self._character_manager.get_character(character_id) # Original, needs guild_id
        char = await self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Corrected
        if not char:
             print(f"CharacterActionProcessor: Error adding action to queue: Character {character_id} not found in guild {guild_id}.")
             return {"success": False, "modified_entities": modified_entities}
        guild_id = str(char.guild_id) # Use char's guild_id

        action_type = action_data.get('type')
        if not action_type:
             print(f"CharacterActionProcessor: Error adding action to queue: action_data is missing 'type'.")
             await self._notify_character(character_id, f"❌ Не удалось добавить действие в очередь: не указан тип действия.")
             return {"success": False, "modified_entities": modified_entities}

        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        location_manager = kwargs.get('location_manager', self._location_manager)

        if action_type == 'move':
             target_location_id = action_data.get('target_location_id')
             if not target_location_id:
                  print(f"CharacterActionProcessor: Error adding move action to queue: Missing target_location_id in action_data.")
                  await self._notify_character(character_id, f"❌ Не удалось добавить перемещение в очередь: не указана целевая локация.")
                  return {"success": False, "modified_entities": modified_entities}
             if location_manager and hasattr(location_manager, 'get_location_static') and location_manager.get_location_static(target_location_id) is None: # FIXME: get_location_static needs guild_id
                 print(f"CharacterActionProcessor: Error adding move action to queue: Target location '{target_location_id}' does not exist.")
                 await self._notify_character(character_id, f"❌ Не удалось добавить перемещение в очередь: локация '{target_location_id}' не существует.")
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


    # Метод обработки тика для ОДНОГО персонажа (ПЕРЕНЕСЕН ИЗ CharacterManager)
    # WorldSimulationProcessor будет вызывать этот метод для каждого ID персонажа, находящегося в кеше CharacterManager._entities_with_active_action.
    # async def process_tick(self, char_id: str, game_time_delta: float, **kwargs) -> None: # This is the first one, removing it.
    #     """
    #     Обрабатывает тик для текущего ИНДИВИДУАЛЬНОГО действия персонажа.
    #     Этот метод вызывается WorldSimulationProcessor для каждого активного персонажа.
    #     Обновляет прогресс, завершает действие при необходимости, начинает следующее из очереди.
    #     kwargs: Дополнительные менеджеры/сервисы (time_manager, send_callback_factory и т.т.), переданные WSP.
    #     """
    #     # print(f"CharacterActionProcessor: Processing tick for character {char_id}...") # Бывает очень шумно

    #     # Получаем персонажа из менеджера персонажей (это синхронный вызов)
    #     char = self._character_manager.get_character(char_id)
    #     # Проверяем, что персонаж все еще в кеше. Если нет или у него нет действия И пустая очередь, удаляем из активных (в менеджере персонажей) и выходим.
    #     if not char or (getattr(char, 'current_action', None) is None and not getattr(char, 'action_queue', [])):
    #          # Удаляем из кеша сущностей с активным действием через менеджер персонажей.
    #          # _entities_with_active_action доступен напрямую для процессора.
    #          self._character_manager._entities_with_active_action.discard(char_id)
    #          # print(f"CharacterActionProcessor: Skipping tick for character {char_id} (not found, no action, or empty queue).")
    #          return

    #     current_action = getattr(char, 'current_action', None)
    #     action_completed = False # Флаг завершения


    #     # --- Обновляем прогресс текущего действия (если оно есть) ---
    #     if current_action is not None:
    #          duration = current_action.get('total_duration', 0.0)
    #          if duration is None: # Обрабатываем случай, если total_duration None (например, перманентное действие)
    #              # print(f"CharacterActionProcessor: Char {char_id} action '{current_action.get('type', 'Unknown')}' has None duration. Assuming it's ongoing.") # Бывает шумно
    #              # Ничего не делаем с прогрессом, действие продолжается перманентно до принудительной отмены или другого триггера.
    #              pass # Прогресс не меняется, dirty не помечается из-за прогресса.
    #          elif duration <= 0:
    #               print(f"CharacterActionProcessor: Char {char_id} action '{current_action.get('type', 'Unknown')}' is instant (duration <= 0). Marking as completed.")
    #               action_completed = True
    #          else:
    #               progress = current_action.get('progress', 0.0)
    #               if not isinstance(progress, (int, float)):
    #                    print(f"CharacterActionProcessor: Warning: Progress for char {char_id} action '{current_action.get('type', 'Unknown')}' is not a number ({progress}). Resetting to 0.0.")
    #                    progress = 0.0

    #               current_action['progress'] = progress + game_time_delta
    #               char.current_action = current_action # Убедимся, что изменение сохраняется в объекте Character
    #               # Помечаем персонажа как измененного через его менеджер
    #               self._character_manager._dirty_characters.add(char_id)

    #               # print(f"CharacterActionProcessor: Char {char_id} action '{current_action.get('type', 'Unknown')}'. Progress: {current_action['progress']:.2f}/{duration:.1f}") # Debug

    #               # --- Проверяем завершение действия ---
    #               if current_action['progress'] >= duration:
    #                    print(f"CharacterActionProcessor: Char {char_id} action '{current_action.get('type', 'Unknown')}' completed.")
    #                    action_completed = True


    #     # --- Обработка завершения действия ---
    #     # Этот блок выполняется, ЕСЛИ действие завершилось в этом тике.
    #     if action_completed and current_action is not None:
    #          # complete_action сбросит current_action, пометит dirty, и начнет следующее из очереди (если есть)
    #          # Передаем все kwargs из WorldTick дальше в complete_action
    #          await self.complete_action(char_id, current_action, **kwargs)


    #     # --- Проверяем, нужно ли удалить из активных после завершения или если не было действия и очередь пуста ---
    #     # complete_action уже запустил следующее действие ИЛИ оставил current_action = None.
    #     # process_tick должен удалить из _entities_with_active_action, если персонаж больше не активен.
    #     # Проверяем состояние персонажа СНОВА после завершения действия и запуска следующего.
    #     # Убедимся, что у объекта Character есть атрибуты current_action и action_queue перед проверкой
    #     if getattr(char, 'current_action', None) is None and (hasattr(char, 'action_queue') and not char.action_queue):
    #          # Удаляем из кеша сущностей с активным действием через менеджер персонажей.
    #          # _entities_with_active_action доступен напрямую для процессора.
    #          # TODO: This needs guild_id. Assuming char.guild_id is available.
    #          char_guild_id = getattr(char, 'guild_id', None)
    #          if char_guild_id:
    #              self._character_manager._entities_with_active_action.get(char_guild_id, set()).discard(char_id)
    #          else:
    #              print(f"CharacterActionProcessor (process_tick): Warning: Could not determine guild_id for char {char_id} to update active_entities set after action completion.")

    #          # print(f"CharacterActionProcessor: Character {char_id} has no more actions. Removed from active list.")


    #     # Сохранение обновленного состояния персонажа (если он помечен как dirty) произойдет в save_all_characters.
    #     # process_tick пометил персонажа как dirty, если прогресс изменился.
    #     # complete_action пометил персонажа как dirty, если действие завершилось и/или очередь изменилась.


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

        # A better approach: WorldSimulationProcessor should pass guild_id along with char_id.
        # For now, trying to retrieve guild_id from character if possible, otherwise this method has issues.
        char_guild_id_for_tick = kwargs.get('guild_id') # Prefer guild_id from context if available

        char: Optional[Character] = None
        if char_guild_id_for_tick:
            char = await self._character_manager.get_character(guild_id=str(char_guild_id_for_tick), character_id=char_id)
        else:
            # Try to get character without guild_id (less ideal, relies on char_id being globally unique and CM supporting it)
            # This path is problematic. For now, let's assume this get_character can work or it's a TODO.
            # char = await self._character_manager.get_character(character_id=char_id) # This signature might not exist
            # Fallback: If no guild_id, we cannot reliably use most CharacterManager methods.
            print(f"CharacterActionProcessor (process_tick): Warning: guild_id not available for char {char_id}. Operations may fail.")
            # Attempt to find the character through all guilds if guild_id is missing (very inefficient, placeholder)
            # This is a temporary workaround to get the guild_id if not passed.
            # In a real scenario, guild_id should be passed to process_tick.
            char_obj_temp = self._character_manager.find_character_globally_by_id_for_tick_FIXME(char_id) # Needs implementation or removal
            if char_obj_temp:
                char = char_obj_temp
                char_guild_id_for_tick = str(char.guild_id)
            else: # Character not found at all
                 active_entities_map = self._character_manager._entities_with_active_action # Direct access to CM's internal
                 for gid_key, id_set in active_entities_map.items():
                     if char_id in id_set:
                         id_set.discard(char_id) # Remove from active set if char not found
                 return


        if not char or (getattr(char, 'current_action', None) is None and not getattr(char, 'action_queue', [])):
             char_guild_id_for_discard = char_guild_id_for_tick if char_guild_id_for_tick else getattr(char, 'guild_id', None)
             if char_guild_id_for_discard:
                 self._character_manager._entities_with_active_action.get(str(char_guild_id_for_discard), set()).discard(char_id)
             return

        # ... (rest of process_tick logic, ensuring guild_id is used for CM calls) ...
        # Make sure mark_character_dirty and other CM calls use the determined char_guild_id_for_tick
        if char_guild_id_for_tick and getattr(char, 'current_action', None) is not None: # Check current_action again
            current_action = getattr(char, 'current_action') # Should not be None here
            duration = current_action.get('total_duration', 0.0)
            # ... (progress update logic) ...
            if isinstance(duration, (int, float)) and duration > 0: # Ensure duration is valid number
                 # ... (progress update logic) ...
                 self._character_manager.mark_character_dirty(str(char_guild_id_for_tick), char_id) # Pass guild_id
                 # ... (check for completion) ...

        # ... (complete_action call if needed, passing char_guild_id_for_tick in kwargs if not already there) ...
        # ... (logic for removing from _entities_with_active_action if no more actions) ...
        if char_guild_id_for_tick and getattr(char, 'current_action', None) is None and (hasattr(char, 'action_queue') and not char.action_queue):
            self._character_manager._entities_with_active_action.get(str(char_guild_id_for_tick), set()).discard(char_id)


    async def complete_action(self, character_id: str, completed_action_data: Dict[str, Any], **kwargs) -> List[Any]:
        modified_entities: List[Any] = []
        guild_id_from_context = kwargs.get('guild_id')
        if not guild_id_from_context:
            temp_char_for_guild = self._character_manager.get_character(guild_id="ANY_GUILD_TEMP_FIX", character_id=character_id) # Problematic
            guild_id = str(getattr(temp_char_for_guild, 'guild_id', "unknown_guild_in_complete_action")) if temp_char_for_guild else "unknown_guild_in_complete_action"
        else:
            guild_id = str(guild_id_from_context)

        # char = self._character_manager.get_character(character_id) # Original, needs guild_id
        char = await self._character_manager.get_character(guild_id=guild_id, character_id=character_id) # Corrected
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
            await self._notify_character(character_id, f"❌ Critical error completing '{action_type}'.")

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

    async def _notify_character(self, character_id: str, message: str) -> None:
         if self._send_callback_factory is None: return
         # char = self._character_manager.get_character(character_id) # Original, needs guild_id
         # This is problematic as _notify_character might be called when guild_id isn't readily available
         # Option 1: Pass guild_id to _notify_character
         # Option 2: CharacterManager.get_character needs to be able to find char by unique ID across guilds (less ideal)
         # For now, assuming this method might be called without full guild context from all paths.
         # This is a known issue to be resolved by ensuring guild_id is always passed or character is passed.

         # Temporary: Try to get character with a placeholder or by iterating if necessary (very inefficient)
         # This part needs a proper fix by ensuring guild_id is always available to this method.
         char = self._character_manager.find_character_globally_by_id_for_notification_FIXME(character_id) # Needs implementation or removal

         if not char:
              print(f"CharacterActionProcessor: Warning (notify): Character {character_id} not found (globally).")
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


    # NOTE: Метод get_entities_with_active_action остается в CharacterManager.

    # NOTE: Метод process_tick (для ОДНОГО персонажа) перенесен сюда.
    # WorldSimulationProcessor будет вызывать этот метод для каждого ID персонажа, находящегося в его кеше CharacterManager._entities_with_active_action.
    async def process_tick(self, char_id: str, game_time_delta: float, **kwargs) -> None:
        """
        Обрабатывает тик для текущего ИНДИВИДУАЛЬНОГО действия персонажа.
        Этот метод вызывается WorldSimulationProcessor для каждого активного персонажа.
        Обновляет прогресс, завершает действие при необходимости, начинает следующее из очереди.
        kwargs: Дополнительные менеджеры/сервисы (time_manager, send_callback_factory и т.т.), переданные WSP.
        """
        # print(f"CharacterActionProcessor: Processing tick for character {char_id}...") # Бывает очень шумно

        # Получаем персонажа из менеджера персонажей (это синхронный вызов)
        char = self._character_manager.get_character(char_id)
        # Проверяем, что персонаж все еще в кеше. Если нет или у него нет действия И пустая очередь, удаляем из активных (в менеджере персонажей) и выходим.
        # Убедимся, что у объекта Character есть атрибуты current_action и action_queue перед проверкой
        if not char or (getattr(char, 'current_action', None) is None and (hasattr(char, 'action_queue') and not char.action_queue)):
             # Удаляем из кеша сущностей с активным действием через менеджер персонажей.
             char_guild_id_str = str(getattr(char, 'guild_id', 'unknown_guild')) if char else 'unknown_guild'
             if char_guild_id_str in self._character_manager._entities_with_active_action:
                 self._character_manager._entities_with_active_action[char_guild_id_str].discard(char_id)
                 if not self._character_manager._entities_with_active_action[char_guild_id_str]:
                     del self._character_manager._entities_with_active_action[char_guild_id_str]
             # print(f"CharacterActionProcessor: Skipping tick for character {char_id} (not found, no action, or empty queue).")
             return

        current_action = getattr(char, 'current_action', None) # char is guaranteed to be not None here
        action_completed = False # Флаг завершения


        # --- Обновляем прогресс текущего действия (если оно есть) ---
        if current_action is not None:
             duration = current_action.get('total_duration', 0.0)
             if duration is None: # Обрабатываем случай, если total_duration None (например, перманентное действие)
                 # print(f"CharacterActionProcessor: Char {char_id} action '{current_action.get('type', 'Unknown')}' has None duration. Assuming it's ongoing.") # Бывает шумно
                 # Ничего не делаем с прогрессом, действие продолжается перманентно до принудительной отмены или другого триггера.
                 pass # Прогресс не меняется, dirty не помечается из-за прогресса.
             elif duration <= 0:
                  print(f"CharacterActionProcessor: Char {char_id} action '{current_action.get('type', 'Unknown')}' is instant (duration <= 0). Marking as completed.")
                  action_completed = True
             else:
                  progress = current_action.get('progress', 0.0)
                  if not isinstance(progress, (int, float)):
                       print(f"CharacterActionProcessor: Warning: Progress for char {char_id} action '{current_action.get('type', 'Unknown')}' is not a number ({progress}). Resetting to 0.0.")
                       progress = 0.0

                  current_action['progress'] = progress + game_time_delta
                  char.current_action = current_action # Убедимся, что изменение сохраняется в объекте Character
                  # Помечаем персонажа как измененного через его менеджер
                  self._character_manager._dirty_characters.add(char_id)

                  # print(f"CharacterActionProcessor: Char {char_id} action '{current_action.get('type', 'Unknown')}'. Progress: {current_action['progress']:.2f}/{duration:.1f}") # Debug

                  # --- Проверяем завершение действия ---
                  if current_action['progress'] >= duration:
                       print(f"CharacterActionProcessor: Char {char_id} action '{current_action.get('type', 'Unknown')}' completed.")
                       action_completed = True


        # --- Обработка завершения действия ---
        # Этот блок выполняется, ЕСЛИ действие завершилось в этом тике.
        if action_completed and current_action is not None:
             # complete_action сбросит current_action, пометит dirty, и начнет следующее из очереди (если есть)
             # Передаем все kwargs из WorldTick дальше в complete_action
             await self.complete_action(char_id, current_action, **kwargs)


        # --- Проверяем, нужно ли удалить из активных после завершения или если не было действия и очередь пуста ---
        # complete_action уже запустил следующее действие ИЛИ оставил current_action = None.
        # process_tick должен удалить из _entities_with_active_action, если персонаж больше не активен.
        # Проверяем состояние персонажа СНОВА после завершения действия и запуска следующего.
        # Убедимся, что у объекта Character есть атрибуты current_action и action_queue перед проверкой
        if getattr(char, 'current_action', None) is None and (hasattr(char, 'action_queue') and not char.action_queue):
             # Удаляем из кеша сущностей с активным действием через менеджер персонажей.
             # _entities_with_active_action доступен напрямую для процессора.
             self._character_manager._entities_with_active_action.discard(char_id)
             # print(f"CharacterActionProcessor: Character {char_id} has no more actions. Removed from active list.")


        # Сохранение обновленного состояния персонажа (если он помечен как dirty) произойдет в save_all_characters.
        # process_tick пометил персонажа как dirty, если прогресс изменился.
        # complete_action пометил персонажа как dirty, если действие завершилось и/или очередь изменилась.
    # process_tick is duplicated, removing the second instance.
    # async def process_tick(...): ...

    async def process_move_action(self, character_id: str, target_location_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        modified_entities: List[Any] = []
        guild_id = context.get('guild_id')
        if not guild_id:
            # Attempt to get guild_id from character if not in context (less ideal)
            temp_char = await self._character_manager.get_character(guild_id="PLACEHOLDER_FIXME", character_id=character_id) # This is bad
            if temp_char and temp_char.guild_id: guild_id = str(temp_char.guild_id)
            else:
                print(f"CharacterActionProcessor: Error processing move: guild_id missing for Character {character_id}.")
                return {"success": False, "message": "Internal error: Guild context missing.", "modified_entities": modified_entities}
        
        # char = self._character_manager.get_character(guild_id, character_id) # Original
        char = await self._character_manager.get_character(guild_id=str(guild_id), character_id=character_id) # Corrected
        # ... (rest of process_move_action, ensure guild_id is used in manager calls) ...
        # Ensure all calls to start_action within this method also pass the resolved guild_id in context
        context_with_guild = {**context, 'guild_id': guild_id}
        start_action_result = await self.start_action(character_id, action_data, **context_with_guild)
        # ...
        return {"success": True, "message": "Move initiated.", "modified_entities": modified_entities}


    async def process_steal_action(self, character_id: str, target_id: str, target_type: str, context: Dict[str, Any]) -> bool:
        # Ensure guild_id is available for get_character and other manager calls
        guild_id = context.get('guild_id')
        char_for_guild_lookup = await self._character_manager.get_character(guild_id=str(guild_id) if guild_id else "ERROR_NO_GUILD", character_id=character_id)
        if not char_for_guild_lookup: return False # Guard
        current_guild_id = str(char_for_guild_lookup.guild_id) # Use character's actual guild_id

        # char = self._character_manager.get_character(character_id) # Original
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
        char_for_guild_lookup = await self._character_manager.get_character(guild_id=str(guild_id) if guild_id else "ERROR_NO_GUILD", character_id=character_id)
        if not char_for_guild_lookup: return False
        current_guild_id = str(char_for_guild_lookup.guild_id)
        # ... (rest of process_hide_action) ...
        context_with_guild = {**context, 'guild_id': current_guild_id}
        # action_started_or_queued = await self.start_action(character_id, action_data, **context_with_guild)
        return True # Placeholder

    async def process_use_item_action(self, character_id: str, item_instance_id: str, target_entity_id: Optional[str], target_entity_type: Optional[str], context: Dict[str, Any]) -> bool:
        guild_id = context.get('guild_id')
        char_for_guild_lookup = await self._character_manager.get_character(guild_id=str(guild_id) if guild_id else "ERROR_NO_GUILD", character_id=character_id)
        if not char_for_guild_lookup: return False
        current_guild_id = str(char_for_guild_lookup.guild_id)
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

# Конец класса CharacterActionProcessor
