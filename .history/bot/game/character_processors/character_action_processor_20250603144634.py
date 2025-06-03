# bot/game/character_processors/character_action_processor.py

# --- Импорты ---
import json
import uuid
import traceback
import asyncio
# ИСПРАВЛЕНИЕ: Убедимся, что все необходимые типы импортированы
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable


# Импорт модели Character (нужен для работы с объектами персонажей, полученными от CharacterManager)
from bot.game.models.character import Character
# TODO: Импорт модели действия, если таковая есть
# from bot.game.models.character_action import CharacterAction


# Импорт менеджера персонажей (CharacterActionProcessor нуждается в нем для получения объектов Character)
# CharacterActionProcessor не принимает CharacterManager в __init__.
from bot.game.managers.character_manager import CharacterManager

# TODO: Импорт других менеджеров/сервисов, которые нужны в start_action, add_action_to_queue, process_tick, complete_action
# Эти менеджеры будут использоваться для валидации действия, расчета длительности, применения эффектов завершения действия и т.п.
# Используйте строковые аннотации ('ManagerName') для Optional зависимостей, чтобы избежать циклов импорта.
# Раскомментируйте только те, которые нужны в методах НИЖЕ.
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.location_manager import LocationManager
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.party_manager import PartyManager # PartyManager нужен для is_busy
from bot.game.managers.npc_manager import NpcManager # Нужен для действий, взаимодействующих с NPC
from bot.game.managers.game_log_manager import GameLogManager # Import GameLogManager

# TODO: Импорт процессоров, если они нужны в complete_action (напр., EventStageProcessor для триггеров)
from bot.game.event_processors.event_stage_processor import EventStageProcessor
from bot.game.event_processors.event_action_processor import EventActionProcessor # Нужен для некоторых действий?


# Define send callback type (нужен для уведомлений о действиях)
# SendToChannelCallback определен в GameManager/WorldSimulationProcessor, его нужно импортировать или определить здесь
# Определим здесь, чтобы избежать циклического импорта
SendToChannelCallback = Callable[[str], Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


class CharacterActionProcessor:
    """
    Процессор, отвечающий за управление индивидуальными действиями персонажей
    и их очередями.
    Обрабатывает начало, добавление в очередь, обновление прогресса и завершение действий.
    Взаимодействует с CharacterManager для доступа к объектам Character
    и с другими менеджерами/сервисами для логики самих действий.
    """
    def __init__(self,
                 # --- Обязательные зависимости ---
                 # Процессор действий нуждается в менеджере персонажей для доступа к объектам Character
                 character_manager: CharacterManager,
                 # Фабрика callback'ов для отправки сообщений (нужна для уведомлений игрока о начале/завершении)
                 send_callback_factory: SendCallbackFactory,

                 # --- Опциональные зависимости (ВСЕ менеджеры/сервисы, которые могут понадобиться при выполнении ЛЮБОГО действия) ---
                 # Получаем их из GameManager при инстанциировании Процессора.
                 # Раскомментируйте и добавьте в список параметров только те, которые реально нужны в логике start_action, add_action_to_queue, process_tick, complete_action
                 item_manager: Optional['ItemManager'] = None,
                 location_manager: Optional['LocationManager'] = None,
                 rule_engine: Optional['RuleEngine'] = None,
                 time_manager: Optional['TimeManager'] = None,
                 combat_manager: Optional['CombatManager'] = None,
                 status_manager: Optional['StatusManager'] = None,
                 party_manager: Optional['PartyManager'] = None, # PartyManager нужен для is_busy
                 npc_manager: Optional['NpcManager'] = None, # Нужен для действий с NPC

                 # TODO: Добавьте другие менеджеры/сервисы, которые могут понадобиться (EconomyManager?)
                 # economy_manager: Optional['EconomyManager'] = None,

                 # Процессоры, которые могут понадобиться для триггеров в complete_action
                 event_stage_processor: Optional['EventStageProcessor'] = None,
                 event_action_processor: Optional['EventActionProcessor'] = None, # Если действие триггерит действие события
                 game_log_manager: Optional['GameLogManager'] = None, # Added GameLogManager
                ):
        print("Initializing CharacterActionProcessor...")
        # --- Сохранение всех переданных аргументов в self._... ---
        # Обязательные
        self._character_manager = character_manager
        self._send_callback_factory = send_callback_factory

        # Опциональные
        self._game_log_manager = game_log_manager # Store GameLogManager
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._time_manager = time_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._npc_manager = npc_manager
        # self._economy_manager = economy_manager

        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor


        print("CharacterActionProcessor initialized.")

    # Метод для проверки занятости (ПЕРЕНЕСЕН ИЗ CharacterManager)
    # Этот метод проверяет только атрибут current_action персонажа и вызывает PartyManager.is_party_busy.
    # Он получает PartyManager из своих атрибутов.
    def is_busy(self, character_id: str) -> bool:
         """
         Проверяет, занят ли персонаж выполнением индивидуального действия.
         ИЛИ группового действия партии, если персонаж в партии.
         PartyManager должен быть доступен (проинжектирован) для проверки занятости партии.
         """
         # Этот метод получает Character из своего manager'а
         char = self._character_manager.get_character(character_id)
         if not char:
              return False # Несуществующий персонаж не занят

         # Занят, если у него есть активное ИНДИВИДУАЛЬНОЕ действие
         if getattr(char, 'current_action', None) is not None:
              return True

         # Занят, если он в партии И у этой партии есть активное действие
         # Используем self._party_manager, который должен быть проинжектирован
         if getattr(char, 'party_id', None) and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
             # NOTE: PartyManager.is_party_busy может потребовать ссылку на CharacterManager
             # в своих kwargs, если PartyManager сам вызывает is_busy для участников.
             # Это передается через **kwargs в process_tick WSP.
             # Но здесь мы в is_busy CharacterActionProcessor. is_party_busy PartyManager
             # может вызывать is_busy на CharacterManager, что приведет к рекурсии!
             # Альтернатива: PartyManager.is_party_busy просто проверяет party.current_action.
             # Давайте предположим, что PartyManager.is_party_busy просто проверяет party.current_action.
             return self._party_manager.is_party_busy(char.party_id)

         return False # Не занят


    # Метод для начала действия (ПЕРЕНЕСЕН ИЗ CharacterManager)
    # Вызывается из CommandRouter или других мест, инициирующих действие.
    async def start_action(self, character_id: str, action_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Начинает новое ИНДИВИДУАЛЬНОЕ действие для персонажа.
        action_data: Словарь с данными действия (type, target_id, callback_data и т.д.).
        kwargs: Дополнительные менеджеры/сервисы.
        Возвращает Dict: {"success": bool, "modified_entities": List[Any]}
        """
        modified_entities: List[Any] = []
        print(f"CharacterActionProcessor: Attempting to start action for character {character_id}: {action_data.get('type')}")

        char = self._character_manager.get_character(character_id)
        if not char:
             print(f"CharacterActionProcessor: Error starting action: Character {character_id} not found.")
             return {"success": False, "modified_entities": modified_entities}

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
        char.current_action = action_data
        self._character_manager.mark_character_dirty(getattr(char, 'guild_id', None), character_id) # Use mark_character_dirty
        self._character_manager._entities_with_active_action.setdefault(getattr(char, 'guild_id', None), set()).add(character_id) # Ensure guild key exists

        if char not in modified_entities:
            modified_entities.append(char)

        success_message = f"Character {getattr(char, 'name', character_id)} started action: {action_type}."
        print(f"CharacterActionProcessor: {success_message} Duration: {action_data['total_duration']:.1f}. Marked as dirty.")

        # Log action start
        if self._game_log_manager:
            log_message = f"Character {getattr(char, 'name', character_id)} started action: {action_type}."
            related_entities_log = [{"type": "character", "id": character_id}]
            if action_data.get('target_id'):
                related_entities_log.append({"type": action_data.get('target_type', 'unknown'), "id": action_data.get('target_id')})

            await self._game_log_manager.log_event(
                guild_id=getattr(char, 'guild_id', 'unknown_guild'),
                event_type="PLAYER_ACTION_START",
                message=success_message, # Use the prepared message
                related_entities=related_entities_log,
                channel_id=kwargs.get('channel_id'), # Assuming channel_id might be in kwargs
                context_data={
                    "action_type": action_type,
                    "action_details": action_data,
                    "success": True
                }
            )
        return {"success": True, "modified_entities": modified_entities, "message": success_message}


    async def add_action_to_queue(self, character_id: str, action_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Добавляет новое ИНДИВИДУАЛЬНОЕ действие в очередь персонажа.
        kwargs: Дополнительные менеджеры/сервисы для валидации или расчета длительности.
        Возвращает Dict: {"success": bool, "modified_entities": List[Any]}
        """
        modified_entities: List[Any] = []
        """
        Добавляет новое ИНДИВИДУАЛЬНОЕ действие в очередь персонажа.
        kwargs: Дополнительные менеджеры/сервисы для валидации или расчета длительности.
        Возвращает True, если действие успешно добавлено, False иначе.
        """
        print(f"CharacterActionProcessor: Attempting to add action to queue for character {character_id}: {action_data.get('type')}")
        char = self._character_manager.get_character(character_id) # TODO: Needs guild_id
        if not char:
             print(f"CharacterActionProcessor: Error adding action to queue: Character {character_id} not found.")
             return {"success": False, "modified_entities": modified_entities}

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

        char.action_queue.append(action_data)
        char.action_queue.append(action_data)
        self._character_manager.mark_character_dirty(getattr(char, 'guild_id', None), character_id)
        self._character_manager._entities_with_active_action.setdefault(getattr(char, 'guild_id', None), set()).add(character_id)

        if char not in modified_entities:
            modified_entities.append(char)

        queue_message = f"Action '{action_data['type']}' added to queue for character {getattr(char, 'name', character_id)}. Queue length: {len(char.action_queue)}."
        print(f"CharacterActionProcessor: {queue_message} Marked as dirty.")

        # Log action queued
        if self._game_log_manager:
            log_message = f"Character {getattr(char, 'name', character_id)} queued action: {action_type}."
            related_entities_log = [{"type": "character", "id": character_id}]
            await self._game_log_manager.log_event(
                guild_id=getattr(char, 'guild_id', 'unknown_guild'),
                event_type="PLAYER_ACTION_QUEUED",
                message=queue_message, # Use the prepared message
                related_entities=related_entities_log,
                channel_id=kwargs.get('channel_id'),
                context_data={
                    "action_type": action_type,
                    "action_details": action_data
                }
            )
        # await self._notify_character(character_id, f"Действие '{action_type}' добавлено в вашу очередь.")
        return {"success": True, "modified_entities": modified_entities, "message": queue_message}


    # Метод обработки тика для ОДНОГО персонажа (ПЕРЕНЕСЕН ИЗ CharacterManager)
    # WorldSimulationProcessor будет вызывать этот метод для каждого ID персонажа, находящегося в кеше CharacterManager._entities_with_active_action.
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
        if not char or (getattr(char, 'current_action', None) is None and not getattr(char, 'action_queue', [])):
             # Удаляем из кеша сущностей с активным действием через менеджер персонажей.
             # _entities_with_active_action доступен напрямую для процессора.
             self._character_manager._entities_with_active_action.discard(char_id)
             # print(f"CharacterActionProcessor: Skipping tick for character {char_id} (not found, no action, or empty queue).")
             return

        current_action = getattr(char, 'current_action', None)
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
             # TODO: This needs guild_id. Assuming char.guild_id is available.
             char_guild_id = getattr(char, 'guild_id', None)
             if char_guild_id:
                 self._character_manager._entities_with_active_action.get(char_guild_id, set()).discard(char_id)
             else:
                 print(f"CharacterActionProcessor (process_tick): Warning: Could not determine guild_id for char {char_id} to update active_entities set.")

             # print(f"CharacterActionProcessor: Character {char_id} has no more actions. Removed from active list.")


        # Сохранение обновленного состояния персонажа (если он помечен как dirty) произойдет в save_all_characters.
        # process_tick пометил персонажа как dirty, если прогресс изменился.
        # complete_action пометил персонажа как dirty, если действие завершилось и/или очередь изменилась.


    # Метод для завершения ИНДИВИДУАЛЬНОГО действия персонажа (ПЕРЕНЕСЕН ИЗ CharacterManager)
    # Вызывается из process_tick, когда действие завершено.
    async def complete_action(self, character_id: str, completed_action_data: Dict[str, Any], **kwargs) -> List[Any]:
        """
        Обрабатывает завершение ИНДИВИДУАЛЬНОГО действия для персонажа.
        Вызывает логику завершения действия, сбрасывает current_action, начинает следующее из очереди.
        kwargs: Дополнительные менеджеры/сервисы, переданные из WorldTick.
        Returns: A list of modified entity objects.
        """
        modified_entities: List[Any] = []
        print(f"CharacterActionProcessor: Completing action for character {character_id}: {completed_action_data.get('type')}")

        char = self._character_manager.get_character(character_id)
        if not char:
             print(f"CharacterActionProcessor: Error completing action: Character {character_id} not found.")
             return modified_entities

        # Add character to modified_entities by default as action completion likely changes it (current_action, queue)
        if char not in modified_entities:
            modified_entities.append(char)

        action_type = completed_action_data.get('type')
        callback_data = completed_action_data.get('callback_data', {})
        # Получаем необходимые менеджеры из kwargs или из атрибутов __init__ процессора
        send_callback_factory = kwargs.get('send_callback_factory', self._send_callback_factory) # Получаем фабрику callback'ов
        item_manager = kwargs.get('item_manager', self._item_manager)
        location_manager = kwargs.get('location_manager', self._location_manager)
        rule_engine = kwargs.get('rule_engine', self._rule_engine)
        status_manager = kwargs.get('status_manager', self._status_manager)
        combat_manager = kwargs.get('combat_manager', self._combat_manager)
        npc_manager = kwargs.get('npc_manager', self._npc_manager)
        # TODO: Получите другие менеджеры/процессоры, нужные для логики завершения (EventStageProcessor, EventActionProcessor?)
        event_stage_processor = kwargs.get('event_stage_processor', self._event_stage_processor)
        event_action_processor = kwargs.get('event_action_processor', self._event_action_processor)


        # TODO: Определите канал для уведомлений игрока (например, из модели Character)
        # async def player_callback(message_content: str): # Вспомогательная функция для отправки игроку
        #      char_discord_id = getattr(char, 'discord_user_id', None)
        #      if char_discord_id is not None and send_callback_factory:
        #           # TODO: Нужна логика определения канала игрока по Discord ID
        #           # Пока используем заглушку
        #           channel_id = 12345 # Заглушка ID канала игрока
        #           if channel_id:
        #                callback = send_callback_factory(channel_id)
        #                await callback(message_content)
        #           else:
        #                print(f"CharacterActionProcessor: Warning: Cannot find Discord channel for character {character_id} ({char_discord_id}).")
        #      else:
        #           print(f"CharacterActionProcessor: Warning: Cannot notify character {character_id}. Not found or not linked to Discord.")


        try:
            if action_type == 'move':
                 target_location_id = callback_data.get('target_location_id')
                 old_location_id = getattr(char, 'location_id', None)

                 if target_location_id and location_manager and hasattr(location_manager, 'handle_entity_arrival') and hasattr(location_manager, 'handle_entity_departure'):
                      print(f"CharacterActionProcessor: Updating character {character_id} location in cache from {old_location_id} to {target_location_id}.")

                      # CharacterManager.update_character_location now returns the modified character
                      modified_char_from_location_update = await self._character_manager.update_character_location(
                          character_id, target_location_id, getattr(char, 'guild_id', None), **kwargs
                      )
                      if modified_char_from_location_update and modified_char_from_location_update not in modified_entities:
                          # Replace char in modified_entities if it's already there, or add.
                          try: modified_entities.remove(char) # Remove old instance if present
                          except ValueError: pass
                          modified_entities.append(modified_char_from_location_update)
                          char = modified_char_from_location_update # Use the updated char object moving forward

                      # TODO: LocationManager.handle_entity_departure/arrival should return modified locations
                      # and RuleEngine.execute_triggers should propagate them.
                      # For now, these calls won't add to modified_entities here.
                      if old_location_id: # Не вызываем OnExit, если персонаж начинал без локации
                           print(f"CharacterActionProcessor: Triggering OnExit for location {old_location_id}.")
                           await location_manager.handle_entity_departure(old_location_id, character_id, 'Character', **kwargs)

                      # 3. Обработать триггеры OnEnter для новой локации
                      # Передаем все менеджеры/сервисы из kwargs, чтобы триггеры могли их использовать
                      print(f"CharacterActionProcessor: Triggering OnEnter for location {target_location_id}.")
                      await location_manager.handle_entity_arrival(target_location_id, character_id, 'Character', **kwargs)

                      # TODO: Отправить сообщение о прибытии в локацию игроку.
                      # location_name = location_manager.get_location_name(target_location_id) if location_manager and hasattr(location_manager, 'get_location_name') else target_location_id
                      # await player_callback(f"Вы прибыли в '{location_name}'.")
                      print(f"CharacterActionProcessor: Character {character_id} completed move action to {target_location_id}. Triggers processed.")


                 else:
                       print("CharacterActionProcessor: Error completing move action: Required managers/data not available or LocationManager trigger methods missing.")
                       # TODO: Что делать, если перемещение завершилось, но логику прибытия/триггеров не удалось выполнить?
                       # Уведомить игрока об ошибке? Откатить перемещение? (Сложно)
                       await self._notify_character(character_id, f"❌ Ошибка завершения перемещения. Произошла внутренняя ошибка.") # Пример


            elif action_type == 'craft':
                 # Пример: действие крафтинга завершено. Создать предмет и добавить в инвентарь.
                 item_template_id = callback_data.get('item_template_id') or completed_action_data.get('item_template_id') # Получаем ID шаблона предмета

                 # ItemManager должен быть доступен для создания предмета
                 # CharacterManager должен быть доступен для добавления предмета в инвентарь
                 if item_manager and self._character_manager and hasattr(self._character_manager, 'add_item_to_inventory'): # Убедимся, что add_item_to_inventory в менеджере персонажей
                       try:
                            # Создать готовый предмет (сохранится в БД внутри ItemManager.create_item)
                            # Передаем все kwargs дальше, т.к. ItemManager.create_item может нуждаться в других менеджерах.
                            item_data_for_creation = {'template_id': item_template_id, 'state_variables': completed_action_data.get('result_state_variables', {})}
                            item_id = await item_manager.create_item(item_data_for_creation, **kwargs)

                            if item_id:
                                 # Добавить предмет в инвентарь персонажа (вызывает ItemManager.move_item и помечает персонажа dirty)
                                 # add_item_to_inventory в CharacterManager уже вызывает ItemManager.move_item.
                                 # Передаем все kwargs дальше, т.к. CharacterManager.add_item_to_inventory может нуждаться в ItemManager и др.
                                 success = await self._character_manager.add_item_to_inventory(character_id, item_id, **kwargs)
                                 if success:
                                      print(f"CharacterActionProcessor: Created item {item_id} from recipe '{completed_action_data.get('recipe_id')}' added to inventory of {character_id}.")
                                      # Уведомить игрока
                                      # item_name = item_manager.get_item_template_name(item_template_id) if hasattr(item_manager, 'get_item_template_name') else item_template_id
                                      # await player_callback(f"✅ Крафтинг завершен! Получен '{item_name}'.")
                                 else:
                                      print(f"CharacterActionProcessor: Error adding created item {item_id} to inventory of {character_id}.")
                                      # TODO: Что делать с предметом, который не удалось добавить в инвентарь? Выбросить на землю? Удалить? Уведомить игрока?
                                      await self._notify_character(character_id, f"❌ Крафтинг завершен, но не удалось добавить предмет в инвентарь.") # Пример

                            else:
                                 print(f"CharacterActionProcessor: Error creating item from template '{item_template_id}'. ItemManager.create_item returned None.")
                                 # TODO: Что делать с не созданными предметами? Уведомить игрока?
                                 await self._notify_character(character_id, f"❌ Не удалось создать предмет после завершения крафтинга.") # Пример


                       except Exception as e:
                            print(f"CharacterActionProcessor: ❌ Error during craft action completion for {character_id}: {e}")
                            import traceback
                            print(traceback.format_exc())
                            # TODO: Уведомить игрока об ошибке завершения крафтинга?
                            await self._notify_character(character_id, f"❌ Произошла ошибка при завершении крафтинга.") # Пример


                       else:
                           print(f"CharacterActionProcessor: Warning: Cannot complete craft action. Required managers not available (ItemManager or CharacterManager.add_item_to_inventory).")
                           # TODO: Уведомить игрока об ошибке?
                           await self._notify_character(character_id, f"❌ Произошла внутренняя ошибка при завершении крафтинга.") # Пример


            # TODO: Добавьте логику завершения для других типов индивидуальных действий (search, use_skill, rest, dialog, combat_action и т.п.)
            # elif action_type == 'search':
            #      # Логика поиска: определить результат (Item/Location/Info), добавить в инвентарь/дать инфу.
            #      # Используйте ItemManager, LocationManager, RuleEngine
            #      item_manager = kwargs.get('item_manager', self._item_manager)
            #      location_manager = kwargs.get('location_manager', self._location_manager)
            #      rule_engine = kwargs.get('rule_engine', self._rule_engine)
            #      # ... логика поиска ...
            #      # Пример: найдено несколько предметов, добавить в инвентарь:
            #      # if rule_engine and hasattr(rule_engine, 'determine_search_loot') and item_manager and hasattr(self._character_manager, 'add_item_to_inventory'):
            #      #      # rule_engine.determine_search_loot вернет список Item IDs или template_ids
            #      #      found_item_ids = await rule_engine.determine_search_loot(char, location_id=getattr(char, 'location_id', None), skill_check_result=callback_data.get('skill_check_result'), **kwargs) # Передаем менеджеры
            #      #      for found_item_id in found_item_ids: # Это ID уже существующих Item
            #      #           await self._character_manager.add_item_to_inventory(character_id, found_item_id, **kwargs) # Вызываем метод менеджера персонажей


            # elif action_type == 'use_skill':
            #      # Логика использования навыка: выполнить проверку, применить эффект, изменить состояние.
            #      # Используйте RuleEngine, StatusManager, CombatManager, NpcManager, CharacterManager
            #      rule_engine = kwargs.get('rule_engine', self._rule_engine)
            #      status_manager = kwargs.get('status_manager', self._status_manager)
            #      combat_manager = kwargs.get('combat_manager', self._combat_manager) # Если навык используется в бою
            #      # ... логика использования навыка ...
            #      # Пример: применен статус-эффект:
            #      # if status_manager and hasattr(status_manager, 'add_status_effect_to_entity') and rule_engine and hasattr(rule_engine, 'calculate_skill_effect'):
            #      #      # RuleEngine рассчитывает эффект навыка (напр., статус)
            #      #      effect_data = await rule_engine.calculate_skill_effect(skill_id=callback_data.get('skill_id'), user=char, target_id=callback_data.get('target_id'), target_type=callback_data.get('target_type'), **kwargs)
            #      #      if effect_data and effect_data.get('type') == 'status_effect' and effect_data.get('status_type'):
            #      #           await status_manager.add_status_effect_to_entity(
            #      #               target_id=effect_data.get('target_id'), target_type=effect_data.get('target_type'),
            #      #               status_type=effect_data.get('status_type'), duration=effect_data.get('duration'), source_id=character_id,
            #      #               **kwargs # Передаем менеджеры дальше
            #      #           )


            # elif action_type == 'rest':
            #      # Логика отдыха: восстановить здоровье/ману, снять статусы.
            #      # Используйте StatusManager, RuleEngine
            #      status_manager = kwargs.get('status_manager', self._status_manager)
            #      rule_engine = kwargs.get('rule_engine', self._rule_engine)
            #      # ... логика отдыха ...
            #      # Пример:
            #      # if rule_engine and hasattr(rule_engine, 'calculate_rest_recovery'):
            #      #      recovery = await rule_engine.calculate_rest_recovery(char, duration=completed_action_data.get('total_duration'), **kwargs)
            #      #      char.health = min(char.health + recovery.get('health', 0), char.max_health)
            #      #      self._character_manager._dirty_characters.add(character_id) # Помечаем персонажа dirty
            #      # if status_manager and hasattr(status_manager, 'remove_status_effects_by_type'):
            #      #      # Снять статусы усталости, используя StatusManager
            #      #      await status_manager.remove_status_effects_by_type('Fatigue', target_id=character_id, target_type='Character', **kwargs)

            # elif action_type == 'dialog':
            #      # Логика диалога с NPC: продвинуть диалог, триггернуть события.
            #      # Используйте NpcManager, EventStageProcessor, EventActionProcessor
            #      npc_manager = kwargs.get('npc_manager', self._npc_manager)
            #      event_stage_processor = kwargs.get('event_stage_processor', self._event_stage_processor)
            #      event_action_processor = kwargs.get('event_action_processor', self._event_action_processor)
            #      # ... логика диалога ...
            #      # Пример: триггер следующей стадии события
            #      # event_id = callback_data.get('event_id')
            #      # next_stage = callback_data.get('next_stage_id')
            #      # if event_id and next_stage and event_stage_processor and kwargs.get('event_manager'):
            #      #      event = kwargs.get('event_manager').get_event(event_id) # EventManager из kwargs
            #      #      if event: await event_stage_processor.advance_stage(event, next_stage, **kwargs)


            # elif action_type == 'combat_action': # Действие в бою
            #      # Логика завершения действия участника боя
            #      # Используйте CombatManager
            #      combat_id = callback_data.get('combat_id')
            #      if combat_id and combat_manager and hasattr(combat_manager, 'handle_participant_action_complete'): # Нужен метод в CombatManager
            #          print(f"CharacterActionProcessor: Combat action completed for {character_id} in combat {combat_id}. Notifying CombatManager.")
            #          # CombatManager обрабатывает завершение действия участника (переход хода, следующий раунд и т.т.)
            #          # Передаем все kwargs, т.к. CombatManager нуждается в других менеджерах
            #          await combat_manager.handle_participant_action_complete(combat_id, character_id, completed_action_data, **kwargs)
            #      else:
            #          print(f"CharacterActionProcessor: Warning: Combat action completed for {character_id} in combat {combat_id}, but CombatManager or method not available.")
            #          # TODO: Логировать ошибку?

            elif action_type == 'steal':
                target_id = callback_data.get('target_id')
                target_type = callback_data.get('target_type')
                target_name = callback_data.get('target_name', target_id) # Use stored name

                if not target_id or not target_type:
                    await self._notify_character(character_id, "❌ Error completing steal: Target information missing.")
                elif not rule_engine or not hasattr(rule_engine, 'resolve_steal_attempt'):
                    await self._notify_character(character_id, f"❌ Cannot determine outcome of stealing from {target_name}: Rule system unavailable.")
                else:
                    target_entity = None
                    guild_id = getattr(char, 'guild_id', None) # Get guild_id from character

                    if not guild_id:
                        await self._notify_character(character_id, "❌ Error completing steal: Cannot determine current guild.")
                    elif target_type.lower() == 'npc':
                        if npc_manager and hasattr(npc_manager, 'get_npc'):
                            target_entity = npc_manager.get_npc(guild_id, target_id)
                        else:
                            await self._notify_character(character_id, f"❌ Cannot verify target {target_name}: NPC system unavailable.")
                    # TODO: Add support for stealing from other entity types (e.g., containers)
                    else:
                        await self._notify_character(character_id, f"❌ Stealing from target type '{target_type}' is not supported.")

                    if target_entity:
                        # Pass the full context (kwargs) which includes all managers
                        steal_outcome = await rule_engine.resolve_steal_attempt(char, target_entity, context=kwargs)
                        
                        outcome_message = steal_outcome.get('message', f"You attempted to steal from {target_name}.")
                        await self._notify_character(character_id, outcome_message)

                        if steal_outcome.get('success') and steal_outcome.get('stolen_item_id'):
                            stolen_item_id = steal_outcome['stolen_item_id']
                            stolen_item_name = steal_outcome.get('stolen_item_name', 'an item')
                            
                            if item_manager and hasattr(item_manager, 'move_item'):
                                # Move item to stealer's inventory
                                move_success = await item_manager.move_item(
                                    item_id=stolen_item_id,
                                    new_owner_id=character_id,
                                    new_owner_type='Character',
                                    new_location_id=None, # No longer on ground/in container if owned
                                    guild_id=guild_id,
                                    **kwargs # Pass context
                                )
                                if move_success:
                                    # ItemManager.move_item should handle adding to character's inventory list
                                    # and marking character dirty.
                                    # Now, explicitly remove from target's inventory list and mark target dirty.
                                    if hasattr(target_entity, 'inventory') and isinstance(target_entity.inventory, list):
                                        try:
                                            target_entity.inventory.remove(stolen_item_id)
                                            if target_type.lower() == 'npc' and npc_manager and hasattr(npc_manager, 'mark_npc_dirty'):
                                                npc_manager.mark_npc_dirty(guild_id, target_id)
                                            # TODO: Handle Character target inventory and dirty marking
                                            print(f"CharacterActionProcessor: Item {stolen_item_id} removed from target {target_id}'s inventory list.")
                                        except ValueError:
                                            print(f"CharacterActionProcessor: Warning: Stolen item {stolen_item_id} not found in target {target_id}'s inventory list for removal.")
                                    
                                    await self._notify_character(character_id, f"🎒 You obtained {stolen_item_name}!")
                                else:
                                    await self._notify_character(character_id, f"⚠️ You managed to snatch {stolen_item_name}, but there was an issue placing it in your inventory.")
                            else:
                                await self._notify_character(character_id, f"⚠️ Item system unavailable to finalize theft of {stolen_item_name}.")
                        
                        # Optional: Process other consequences from steal_outcome
                        # if steal_outcome.get('consequences') and 'consequence_processor' in kwargs:
                        #     con_proc = kwargs['consequence_processor']
                        #     await con_proc.process_consequences(guild_id, steal_outcome['consequences'], source_entity_id=character_id, target_entity_id=target_id, event_context=kwargs)

                    elif target_type.lower() == 'npc' and not target_entity : # Only notify if target was NPC and not found
                        await self._notify_character(character_id, f"❌ Target {target_name} seems to have vanished before you could complete the theft.")

            elif action_type == 'hide':
                if not rule_engine or not hasattr(rule_engine, 'resolve_hide_attempt'):
                    await self._notify_character(character_id, "❌ Cannot determine outcome of hiding: Rule system unavailable.")
                    print(f"CharacterActionProcessor: RuleEngine or resolve_hide_attempt missing for 'hide' action completion for char {character_id}.")
                else:
                    # Pass the full context (kwargs) to resolve_hide_attempt
                    hide_outcome = await rule_engine.resolve_hide_attempt(char, context=kwargs)
                    
                    outcome_message = hide_outcome.get('message', "You attempt to hide...") # Default message if none from outcome
                    await self._notify_character(character_id, outcome_message)

                    if hide_outcome.get('success'):
                        if status_manager and hasattr(status_manager, 'add_status_effect_to_entity'):
                            guild_id_for_status = getattr(char, 'guild_id', None)
                            if guild_id_for_status:
                                # add_status_effect_to_entity returns the StatusEffect object or None
                                new_status_effect = await status_manager.add_status_effect_to_entity(
                                    target_id=char.id,
                                    target_type="Character",
                                    status_type="Hidden", # Standardized status type
                                    duration=None,  # Persists until broken or a specific duration
                                    source_id=char.id, # Self-inflicted status
                                    guild_id=guild_id_for_status,
                                    **kwargs # Pass full context for other potential needs
                                )
                                if new_status_effect:
                                    if new_status_effect not in modified_entities:
                                        modified_entities.append(new_status_effect)
                                    # Character (char) is already added to modified_entities at the start of complete_action
                                print(f"CharacterActionProcessor: 'Hidden' status applied to {character_id}. Status ID: {getattr(new_status_effect, 'id', 'N/A')}")
                            else:
                                print(f"CharacterActionProcessor: Warning: Could not determine guild_id for char {character_id} to apply 'Hidden' status.")
                                await self._notify_character(character_id, "⚠️ Could not properly apply hidden status (guild error).")
                        else:
                            print(f"CharacterActionProcessor: Warning: StatusManager unavailable. Cannot apply 'Hidden' status to {character_id}.")
                            await self._notify_character(character_id, "⚠️ You are hidden, but the effect couldn't be formally applied (system issue).")

            elif action_type == 'use_item':
                item_id = callback_data.get('item_id')
                original_item_data = callback_data.get('original_item_data') # This is the item_instance_data
                target_id_from_callback = callback_data.get('target_id')
                target_type_from_callback = callback_data.get('target_type')
                
                user_char = char # char is the user of the item

                if not item_id or not original_item_data:
                    await self._notify_character(character_id, "❌ Error completing item use: Item information missing.")
                elif not rule_engine or not hasattr(rule_engine, 'resolve_item_use'):
                    await self._notify_character(character_id, "❌ Cannot determine item effect: Rule system unavailable.")
                else:
                    target_entity = None
                    guild_id = getattr(user_char, 'guild_id', None)

                    if not guild_id:
                         await self._notify_character(character_id, "❌ Error using item: Cannot determine current guild.")
                    else:
                        if target_id_from_callback and target_type_from_callback:
                            if target_type_from_callback.lower() == 'character':
                                if self._character_manager and hasattr(self._character_manager, 'get_character'):
                                    target_entity = self._character_manager.get_character(guild_id, target_id_from_callback)
                            elif target_type_from_callback.lower() == 'npc':
                                if npc_manager and hasattr(npc_manager, 'get_npc'):
                                    target_entity = npc_manager.get_npc(guild_id, target_id_from_callback)
                            # Add other entity types if items can target them

                        # Call RuleEngine to resolve the item use
                        # kwargs here is the context passed to complete_action
                        use_outcome = await rule_engine.resolve_item_use(user_char, original_item_data, target_entity, context=kwargs)
                        
                        outcome_message = use_outcome.get('message', "You used the item.")
                        await self._notify_character(character_id, outcome_message)

                        if use_outcome.get('success'):
                            # Apply effects
                            for effect in use_outcome.get('effects', []):
                                effect_type = effect.get('type')
                                effect_target_id = effect.get('target_id', user_char.id) # Default to self if not specified in effect

                                if effect_type == 'heal':
                                    if self._character_manager and hasattr(self._character_manager, 'apply_health_change'):
                                        # Assuming apply_health_change can handle both Character and NPC if target_id matches
                                        await self._character_manager.apply_health_change(
                                            guild_id, effect_target_id, effect.get('amount', 0), healer_id=character_id
                                        )
                                    else: print(f"CharacterActionProcessor: Warning: CharacterManager.apply_health_change not available for heal effect.")
                                
                                elif effect_type == 'status':
                                    if status_manager and hasattr(status_manager, 'add_status_effect_to_entity'):
                                        # Determine target_type for status effect if not explicitly provided by effect data
                                        status_target_type = effect.get('target_type')
                                        if not status_target_type: # Infer from target_entity or default to Character for self-target
                                            if target_entity: status_target_type = target_entity.__class__.__name__ # 'Character' or 'NPC'
                                            elif effect_target_id == user_char.id: status_target_type = "Character"
                                            else: print(f"CharacterActionProcessor: Warning: Could not determine target_type for status effect on {effect_target_id}."); continue
                                        
                                        await status_manager.add_status_effect_to_entity(
                                            target_id=effect_target_id,
                                            target_type=status_target_type,
                                            status_type=effect.get('status_type'),
                                            duration=effect.get('duration'),
                                            source_id=character_id,
                                            guild_id=guild_id,
                                            **kwargs # Pass context
                                        )
                                    else: print(f"CharacterActionProcessor: Warning: StatusManager.add_status_effect_to_entity not available for status effect.")
                                # Add other effect processors here (e.g., damage, stat_modify)

                            # Consume item if specified
                            if use_outcome.get('consumed'):
                                if item_manager and hasattr(item_manager, 'delete_item_instance'):
                                    # This assumes item_manager.delete_item_instance also removes it from character's inventory list attribute
                                    # If not, manual removal is needed here.
                                    delete_success = await item_manager.delete_item_instance(guild_id, item_id, context=kwargs)
                                    if delete_success:
                                        # Explicitly remove from character's inventory list if ItemManager doesn't do it
                                        if hasattr(user_char, 'inventory') and isinstance(user_char.inventory, list) and item_id in user_char.inventory:
                                            user_char.inventory.remove(item_id)
                                            self._character_manager.mark_character_dirty(guild_id, user_char.id)
                                            print(f"CharacterActionProcessor: Item {item_id} explicitly removed from char {user_char.id} inventory list.")
                                        print(f"CharacterActionProcessor: Item {item_id} consumed by {character_id}.")
                                    else:
                                        print(f"CharacterActionProcessor: Warning: Failed to delete consumed item {item_id} via ItemManager for {character_id}.")
                                        await self._notify_character(character_id, "⚠️ The item should have been consumed, but an error occurred.")
                                else:
                                    print(f"CharacterActionProcessor: Warning: ItemManager.delete_item_instance not available. Cannot consume item {item_id} for {character_id}.")
                                    await self._notify_character(character_id, "⚠️ Item consumption failed (system issue).")
            
            else:
                 print(f"CharacterActionProcessor: Warning: Unhandled individual action type '{action_type}' completed for character {character_id}. No specific completion logic executed.")
                 await self._notify_character(character_id, f"Действие '{action_type}' завершено.")


        except Exception as e:
            print(f"CharacterActionProcessor: ❌ CRITICAL ERROR during action completion logic for character {character_id} action '{action_type}': {e}")
            import traceback
            print(traceback.format_exc())
            # TODO: Логика обработки критической ошибки завершения действия (сообщить GM?)
            await self._notify_character(character_id, f"❌ Произошла критическая ошибка при завершении действия '{action_type}'.")


        # --- Сбросить current_action и начать следующее действие из очереди ---
        char.current_action = None # Сбрасываем текущее действие
        # Помечаем персонажа как измененного через его менеджер (current_action стал None)
        self._character_manager._dirty_characters.add(character_id)


        # Проверяем очередь после завершения текущего действия
        action_queue = getattr(char, 'action_queue', []) or []
        if action_queue:
             next_action_data = action_queue.pop(0) # Удаляем из начала очереди
             # Помечаем персонажа как измененного через его менеджер (очередь изменилась)
             self._character_manager._dirty_characters.add(character_id)

             print(f"CharacterActionProcessor: Character {character_id} starting next action from queue: {next_action_data.get('type')}.")

             # Начинаем следующее действие (вызываем start_action этого же процессора)
             # Передаем все необходимые менеджеры из kwargs дальше
             await self.start_action(character_id, next_action_data, **kwargs) # <-- Рекурсивный вызов start_action процессора


        # Если очередь пуста после завершения действия и current_action стал None,
        # персонаж будет удален из _entities_with_active_action в конце process_tick.
        # (Логика удаления из _entities_with_active_action уже в process_tick этого процессора)

        # Log action completion
        if self._game_log_manager:
            log_message = f"Character {getattr(char, 'name', character_id)} completed action: {action_type}."
            # related_entities could include target if relevant and available in completed_action_data or callback_data
            related_entities_log = [{"type": "character", "id": character_id}]
            if callback_data.get('target_id'):
                 related_entities_log.append({"type": callback_data.get('target_type', 'unknown'), "id": callback_data.get('target_id')})

            await self._game_log_manager.log_event(
                guild_id=getattr(char, 'guild_id', 'unknown_guild'),
                event_type="PLAYER_ACTION_COMPLETED",
                message=log_message,
                related_entities=related_entities_log,
                channel_id=kwargs.get('channel_id'), # Assuming channel_id might be in kwargs context
                context_data={
                    "action_type": action_type,
                    "completed_action_details": completed_action_data,
                    # Include any specific results if available, e.g. if steal was successful
                    # "outcome_details": steal_outcome if action_type == 'steal' else None
                }
            )

        return modified_entities


    # Вспомогательный метод для отправки сообщений конкретному персонажу (нужен send_callback_factory)
    # Этот метод остается здесь, т.к. Processor отвечает за уведомления, связанные с действиями.
    async def _notify_character(self, character_id: str, message: str) -> None:
         """
         Находит персонажа, определяет его Discord канал и отправляет сообщение через фабрику callback'ов.
         """
         # send_callback_factory проинжектирован в __init__ процессора
         if self._send_callback_factory is None:
              print(f"CharacterActionProcessor: Warning: Cannot notify character {character_id}. SendCallbackFactory not available.")
              return

         # Получаем персонажа из менеджера персонажей (это синхронный вызов)
         char = self._character_manager.get_character(character_id)
         if not char:
              print(f"CharacterActionProcessor: Warning: Cannot notify character {character_id}. Character not found.")
              return

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
             # _entities_with_active_action доступен напрямую для процессора.
             self._character_manager._entities_with_active_action.discard(char_id)
             # print(f"CharacterActionProcessor: Skipping tick for character {char_id} (not found, no action, or empty queue).")
             return

        current_action = getattr(char, 'current_action', None)
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

    async def process_move_action(self, character_id: str, target_location_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Initiates a move action for a character.
        Returns: Dict {"success": bool, "message": Optional[str], "modified_entities": List[Any]}
        """
        modified_entities: List[Any] = []
        print(f"CharacterActionProcessor: Processing move action for char {character_id} to loc {target_location_id}.")

        # TODO: CharacterManager.get_character needs guild_id. This context must provide it.
        guild_id = context.get('guild_id')
        if not guild_id:
            print(f"CharacterActionProcessor: Error processing move: guild_id missing in context for Character {character_id}.")
            return {"success": False, "message": "Internal error: Guild context missing.", "modified_entities": modified_entities}

        char = self._character_manager.get_character(guild_id, character_id)
        if not char:
            print(f"CharacterActionProcessor: Error processing move: Character {character_id} in guild {guild_id} not found.")
            return {"success": False, "message": "Character not found.", "modified_entities": modified_entities}

        if char not in modified_entities: # Add char if found, as it might be modified by starting action
            modified_entities.append(char)

        action_data = {
            'type': 'move',
            'target_location_id': target_location_id,
            'callback_data': {'target_location_id': target_location_id}
        }

        start_action_result = await self.start_action(character_id, action_data, **context)
        success = start_action_result.get("success", False)
        entities_from_start = start_action_result.get("modified_entities", [])
        for entity in entities_from_start:
            if entity not in modified_entities:
                modified_entities.append(entity)

        if success:
            location_manager = context.get('location_manager', self._location_manager)
            location_name = target_location_id
            if location_manager and hasattr(location_manager, 'get_location_name'):
                char_guild_id = getattr(char, 'guild_id', guild_id) # Use guild_id from context as fallback
                if char_guild_id:
                    name_from_manager = location_manager.get_location_name(char_guild_id, target_location_id)
                    if name_from_manager: location_name = name_from_manager
                else:
                    print(f"CharacterActionProcessor: Warning: Could not determine guild_id for location name lookup during move notification for char {character_id}.")

            current_char_action = getattr(char, 'current_action', None)
            message_to_player = f"🚶 Запрос на перемещение к локации '{location_name}' принят."
            if current_char_action and current_char_action.get('type') == 'move' and current_char_action.get('target_location_id') == target_location_id:
                message_to_player = f"🚶 Вы начинаете движение к локации '{location_name}'."
            
            await self._notify_character(character_id, message_to_player)
            print(f"CharacterActionProcessor: Move action for {character_id} to {target_location_id} successfully initiated/queued.")
            return {"success": True, "message": message_to_player, "modified_entities": modified_entities}
        else:
            print(f"CharacterActionProcessor: Failed to start/queue move action for {character_id} to {target_location_id}.")
            # Assuming start_action handles its own failure notifications if appropriate.
            return {"success": False, "message": "Failed to start move action.", "modified_entities": modified_entities}

    async def process_steal_action(self, character_id: str, target_id: str, target_type: str, context: Dict[str, Any]) -> bool:
        """
        Initiates a steal action for a character against a target entity.
        """
        print(f"CharacterActionProcessor: Processing steal action by char {character_id} on target {target_type} {target_id}.")
        
        char = self._character_manager.get_character(character_id)
        if not char:
            print(f"CharacterActionProcessor: Error processing steal: Character {character_id} not found.")
            # Cannot notify if char object is not found. Command handler should handle.
            return False

        # Retrieve target entity
        target_entity = None
        target_name = target_id # Default to ID
        
        if target_type.lower() == 'npc':
            npc_manager = context.get('npc_manager', self._npc_manager)
            if not npc_manager:
                await self._notify_character(character_id, "❌ NPC system is unavailable for stealing.")
                return False
            target_entity = npc_manager.get_npc(getattr(char, 'guild_id', None), target_id)
            if target_entity: target_name = getattr(target_entity, 'name', target_id)
        # TODO: Extend here for other target types like 'container' or 'player_character'
        else:
            await self._notify_character(character_id, f"❌ Cannot steal from target type '{target_type}'.")
            return False

        if not target_entity:
            await self._notify_character(character_id, f"❌ Target '{target_id}' ({target_type}) not found.")
            return False

        # Location Check
        location_manager = context.get('location_manager', self._location_manager)
        if not location_manager:
            await self._notify_character(character_id, "❌ Location system is unavailable for stealing.")
            return False
            
        char_loc_id = getattr(char, 'location_id', None)
        target_loc_id = getattr(target_entity, 'location_id', None)

        if char_loc_id != target_loc_id:
            char_loc_name = location_manager.get_location_name(getattr(char, 'guild_id', None), char_loc_id) or "Unknown Location"
            target_loc_name = location_manager.get_location_name(getattr(target_entity, 'guild_id', None), target_loc_id) or "an unknown place"
            await self._notify_character(character_id, f"❌ You must be in the same location as {target_name} to steal. You are in {char_loc_name}, they are in {target_loc_name}.")
            return False

        # Construct action data
        action_data = {
            'type': 'steal',
            'target_id': target_id,
            'target_type': target_type,
            'total_duration': 0.1,  # Stealing is a quick attempt.
            'callback_data': {  # To pass to complete_action
                'target_id': target_id,
                'target_type': target_type,
                'target_name': target_name # Store for notification in complete_action
            }
        }

        action_started_or_queued = await self.start_action(character_id, action_data, **context)

        if action_started_or_queued:
            await self._notify_character(character_id, f"🤫 You attempt to steal from {target_name}...")
            print(f"CharacterActionProcessor: Steal action for {character_id} on {target_type} {target_id} successfully initiated/queued.")
            return True
        else:
            # start_action should handle notifications for busy state or other validation failures.
            print(f"CharacterActionProcessor: Failed to start/queue steal action for {character_id} on {target_type} {target_id}.")
            return False

    async def process_hide_action(self, character_id: str, context: Dict[str, Any]) -> bool:
        """
        Initiates a hide action for a character.
        """
        print(f"CharacterActionProcessor: Processing hide action for char {character_id}.")
        
        char = self._character_manager.get_character(character_id)
        if not char:
            print(f"CharacterActionProcessor: Error processing hide: Character {character_id} not found.")
            # Cannot notify if char object is not found. Command handler should handle.
            return False

        # Construct action data
        action_data = {
            'type': 'hide',
            'total_duration': 2.0,  # Example: 2 seconds to attempt to hide
            'callback_data': {} 
        }

        # Attempt to start the action. start_action handles busy checks, duration calculation, etc.
        # It also handles notifications for busy state.
        # We pass the full context down, which includes all managers and the send_callback_factory.
        action_started_or_queued = await self.start_action(character_id, action_data, **context)

        if action_started_or_queued:
            await self._notify_character(character_id, "🤫 You attempt to find a hiding spot...")
            print(f"CharacterActionProcessor: Hide action for {character_id} successfully initiated/queued.")
            return True
        else:
            # start_action would have sent a notification if the character was busy or if validation failed.
            print(f"CharacterActionProcessor: Failed to start/queue hide action for {character_id}.")
            return False

    async def process_use_item_action(self, character_id: str, item_instance_id: str, target_entity_id: Optional[str], target_entity_type: Optional[str], context: Dict[str, Any]) -> bool:
        """
        Initiates a 'use_item' action for a character.
        """
        print(f"CharacterActionProcessor: Processing use_item action for char {character_id}, item {item_instance_id}, target: {target_entity_type} {target_entity_id}.")
        
        char = self._character_manager.get_character(character_id)
        if not char:
            print(f"CharacterActionProcessor: Error processing use_item: Character {character_id} not found.")
            # Cannot notify if char object is not found. Command handler should handle.
            return False

        item_manager = context.get('item_manager', self._item_manager)
        if not item_manager:
            await self._notify_character(character_id, "❌ Item system is unavailable.")
            print(f"CharacterActionProcessor: ItemManager not found in context or self for use_item action by char {character_id}.")
            return False

        # Verify Item Ownership
        char_inventory = getattr(char, 'inventory', [])
        if item_instance_id not in char_inventory:
            await self._notify_character(character_id, "❌ You do not possess that item.")
            print(f"CharacterActionProcessor: Item {item_instance_id} not in inventory of char {character_id}.")
            return False

        # Fetch item instance data
        guild_id = getattr(char, 'guild_id', context.get('guild_id'))
        if not guild_id:
            await self._notify_character(character_id, "❌ Cannot determine current guild for item use.")
            return False
            
        item_instance = item_manager.get_item(guild_id, item_instance_id) # This should return a dict or Item model instance
        if not item_instance:
            await self._notify_character(character_id, "❌ The item could not be found or is invalid.")
            print(f"CharacterActionProcessor: Item instance {item_instance_id} not found via ItemManager for char {character_id}.")
            return False
        
        item_template_id = getattr(item_instance, 'template_id', None)
        if isinstance(item_instance, dict): # If get_item returns a dict
            item_template_id = item_instance.get('template_id')


        # Determine action duration
        action_duration = 0.5 # Default quick use time
        if self._rule_engine and item_template_id:
            try:
                action_duration = await self._rule_engine.calculate_action_duration(
                    action_type='use_item',
                    action_context={'item_template_id': item_template_id, 'item_id': item_instance_id},
                    character=char,
                    context=context # Pass the full context
                )
            except Exception as e:
                print(f"CharacterActionProcessor: Error calculating 'use_item' duration: {e}")
        
        # Construct action data
        action_data = {
            'type': 'use_item',
            'item_id': item_instance_id,
            'item_template_id': item_template_id,
            'target_id': target_entity_id,
            'target_type': target_entity_type,
            'total_duration': action_duration, 
            'callback_data': {
                'item_id': item_instance_id,
                'original_item_data': dict(item_instance) if isinstance(item_instance, dict) else item_instance.to_dict() if hasattr(item_instance, 'to_dict') else {}, # Pass a copy of item data
                'target_id': target_entity_id,
                'target_type': target_entity_type
            }
        }

        action_started_or_queued = await self.start_action(character_id, action_data, **context)

        if action_started_or_queued:
            item_name = "the item" # Default
            if item_template_id:
                item_template = item_manager.get_item_template(guild_id, item_template_id)
                if item_template:
                    item_name = getattr(item_template, 'name', item_template_id)
            
            await self._notify_character(character_id, f"You begin to use {item_name}...")
            print(f"CharacterActionProcessor: use_item action for {character_id} (item: {item_instance_id}) successfully initiated/queued.")
            return True
        else:
            print(f"CharacterActionProcessor: Failed to start/queue use_item action for {character_id} (item: {item_instance_id}).")
            # start_action should handle specific notifications (e.g., busy)
            return False

    async def process_party_actions(
        self,
        game_manager: Any,
        guild_id: str,
        actions_to_process: List[Dict[str, Any]], # This now expects a flat list of actions, potentially ordered
        context: Dict[str, Any]
        # removed party_actions_data, replaced with actions_to_process
        # Optional[List[str]] action_order parameter is implicitly handled if actions_to_process is already ordered
    ) -> Dict[str, Any]:
        """
        Processes a list of actions for party members, potentially in a specified order.
        Saves modified entities after each individual action processing.
        Each item in actions_to_process should be a dict like:
        {"character_id": "id1", "action_data": {...}, "original_input_text": "...", "unique_action_id": "uuid_action_1"}
        """
        all_modified_entities_in_turn: List[Any] = []
        overall_state_changed_for_party = False
        individual_action_results = []

        # The actions_to_process list is now assumed to be in the correct execution order
        # if reordering was done by PartyManager (after ConflictResolver).
        for action_entry in actions_to_process:
            character_id = action_entry.get("character_id")
            action_data_for_char = action_entry.get("action_data")
            original_input_text = action_entry.get("original_input_text", action_data_for_char.get("type") if action_data_for_char else "Unknown Action")

            if not character_id or not isinstance(action_data_for_char, dict):
                print(f"CharacterActionProcessor (process_party_actions): Skipping invalid action entry: {action_entry}")
                individual_action_results.append({
                    "character_id": character_id,
                    "action_original_text": original_input_text,
                    "success": False,
                    "message": "Invalid action entry structure.",
                    "modified_entities": []
                })
                continue

            action_context = {**context, 'guild_id': guild_id}
            action_result = await self.start_action(character_id, action_data_for_char, **action_context)

            action_succeeded = action_result.get("success", False)
            entities_modified_by_action = action_result.get("modified_entities", [])

            individual_action_results.append({
                "character_id": character_id,
                "action_type": action_data_for_char.get("type"),
                "action_original_text": original_input_text,
                "success": action_succeeded,
                "message": action_result.get("message"),
                "modified_entities_count": len(entities_modified_by_action)
            })

            if action_succeeded:
                overall_state_changed_for_party = True
                for entity in entities_modified_by_action:
                    if entity not in all_modified_entities_in_turn:
                        all_modified_entities_in_turn.append(entity)

                # Save entities modified by this specific action immediately
                if entities_modified_by_action:
                    print(f"CharacterActionProcessor (process_party_actions): Saving {len(entities_modified_by_action)} entities for char {character_id} action.")
                    # Ensure game_manager has save_specific_entities and is the correct type
                    if hasattr(game_manager, 'save_specific_entities') and callable(game_manager.save_specific_entities):
                        await game_manager.save_specific_entities(entities_modified_by_action)
                    else:
                        print(f"CharacterActionProcessor (process_party_actions): ERROR - game_manager does not have save_specific_entities method.")

            # NOTE: For durational actions, start_action only initiates.
            # Modifications often happen in complete_action, called by process_tick.
            # The immediate save here will only save changes from start_action.
            # Changes from complete_action would need to be saved when process_tick -> complete_action runs.
            # This implies that WorldSimulationProcessor.process_world_tick also needs to gather
            # modified_entities from CharacterActionProcessor.process_tick (if it were to return them)
            # and then call game_manager.save_specific_entities. This is a larger change.
            # For now, this fulfills saving after each call to "self.process()" equivalent (start_action).

        return {
            "success": True, # Overall success of processing the batch
            "overall_state_changed_for_party": overall_state_changed_for_party,
            "individual_action_results": individual_action_results,
            "final_modified_entities_this_turn": all_modified_entities_in_turn # Entities modified by start_action calls
        }

# Конец класса CharacterActionProcessor