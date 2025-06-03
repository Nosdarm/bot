# bot/game/npc_processors/npc_action_processor.py

# --- Импорты ---
import json
import uuid
import traceback
import asyncio
# Убедимся, что все необходимые типы импортированы
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING


# --- Imports needed ONLY for Type Checking ---
# Эти модули импортируются ТОЛЬКО для статического анализа (Pylance/Mypy).
# Это разрывает циклы импорта при runtime и помогает Pylance правильно резолвить типы.
# Используйте строковые литералы ("ClassName") для type hints в __init__ и методах
# для классов, импортированных здесь.
if TYPE_CHECKING:
    # Модели
    from bot.game.models.npc import NPC # Используется в аннотациях методов
    # TODO: Импорт модели действия NPC, если таковая есть
    # from bot.game.models.npc_action import NpcAction # Если используете модель действия
    from bot.game.models.character import Character # Если Character модель используется только в аннотациях методов
    from bot.game.models.party import Party # Если Party модель используется только в аннотациях методов
    from bot.game.models.combat import Combat # Если Combat модель используется только в аннотациях методов

    # Менеджеры
    from bot.game.managers.npc_manager import NpcManager # Нужен для Type Hinting в __init__
    from bot.game.rules.rule_engine import RuleEngine # Нужен для Type Hinting в __init__ и методах
    from bot.game.managers.location_manager import LocationManager # Нужен для Type Hinting
    from bot.game.managers.character_manager import CharacterManager # Нужен для Type Hinting
    from bot.game.managers.time_manager import TimeManager # Нужен для Type Hinting
    from bot.game.managers.combat_manager import CombatManager # Нужен для Type Hinting
    from bot.game.managers.status_manager import StatusManager # Нужен для Type Hinting
    from bot.game.managers.party_manager import PartyManager # Нужен для Type Hinting
    from bot.game.managers.item_manager import ItemManager # Нужен для Type Hinting
    from bot.game.managers.economy_manager import EconomyManager # Нужен для Type Hinting
    from bot.game.managers.dialogue_manager import DialogueManager # Нужен для Type Hinting
    from bot.game.managers.crafting_manager import CraftingManager # Нужен для Type Hinting

    # Процессоры
    from bot.game.event_processors.event_stage_processor import EventStageProcessor # Нужен для Type Hinting
    from bot.game.event_processors.event_action_processor import EventActionProcessor # Нужен для Type Hinting
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor # Нужен для Type Hinting
    from bot.game.event_processors.on_enter_action_executor import OnEnterActionExecutor # Возможно, нужен для Type Hinting
    from bot.game.event_processors.stage_description_generator import StageDescriptionGenerator # Возможно, нужен для Type Hinting

    # Обработчики действий NPC (Источник ModuleNotFoundError - нужно импортировать только для TYPE_CHECKING)
    # !!! ВНИМАНИЕ: ПУТЬ ИМПОРТА ДОЛЖЕН СООТВЕТСТВОВАТЬ ВАШЕЙ СТРУКТУРЕ ПАПОК !!!
    # Если папка npc_action_handlers находится внутри bot.game, используйте:
    from bot.game.npc_action_handlers.npc_action_handler_registry import NpcActionHandlerRegistry # <--- ИСПРАВЛЕН ПУТЬ? ПРОВЕРЬТЕ У СЕБЯ
    # Если папка npc_action_handlers находится внутри bot, используйте:
    # from bot.npc_action_handlers.npc_action_handler_registry import NpcActionHandlerRegistry
    # Если папка npc_action_handlers находится в корне проекта, возможно, текущий путь верен, но Python его не находит (нужна настройка PYTHONPATH).


# --- Imports needed at Runtime ---
# Эти модули/классы необходимы для выполнения кода (например, для создания экземпляров, вызовов статических методов, isinstance проверок).
# Если класс используется только для аннотации типов, импортируйте его в TYPE_CHECKING блок выше.

# Прямой импорт модели Character, если она нужна для isinstance (как видно в методах ниже)
from bot.game.models.character import Character

# Прямой импорт NPCActionHandlerRegistry - ЭТО ВЫЗЫВАЕТ ModuleNotFoundError!
# Его нужно получать через Dependency Injection или фабрику, если он нужен при Runtime.
# Если Handler Registry нужен только для вызова get_handler в complete_action,
# и сам registry проинжектирован в __init__, то прямой импорт класса Registry не нужен здесь для Runtime,
# его нужно импортировать только в TYPE_CHECKING для аннотации в __init__.

# NpcManager импортируем напрямую, т.к. он проинжектирован и используется как self._npc_manager
# from bot.game.managers.npc_manager import NpcManager # Уже был в TYPE_CHECKING. Удаляем прямой, используем из self.

# SendCallbackFactory тоже используется как self._send_callback_factory, не нужно импортировать класс напрямую для runtime
# from NpcActionHandlerRegistry... # Удаляем прямой импорт Registry class

print("DEBUG: npc_action_processor.py module loading...")


# Define send callback type (нужен для уведомлений - вероятно, для логирования действий NPC или уведомлений GM)
# Определим здесь, чтобы избежать циклического импорта
SendChannelMessageCallback = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]] # Используем ту же сигнатуру, что и в Location/Event Managers
SendCallbackFactory = Callable[[int], SendChannelMessageCallback] # Фабрика callback'ов


class NpcActionProcessor:
    """
    Процессор, отвечающий за управление индивидуальными действиями NPC
    и их очередями.
    Обрабатывает начало, добавление в очередь, обновление прогресса и завершение действий NPC.
    Также может содержать базовую логику AI для принятия решений о следующем действии.
    Взаимодействует с NpcManager для доступа к объектам NPC
    и с другими менеджерами/сервисами для логики самих действий.
    Делегирует логику завершения конкретных действий обработчикам.
    """
    def __init__(self,
                 # --- Обязательные зависимости ---
                 # Используем строковые литералы для инжектированных зависимостей
                 npc_manager: "NpcManager", # Use string literal!
                 # Фабрика callback'ов для отправки сообщений
                 send_callback_factory: SendCallbackFactory, # Callable тип, не требует строкового литерала
                 # Settings могут понадобиться для получения GM channel ID
                 settings: Dict[str, Any],
                 # Реестр обработчиков завершения действий (проинжектирован как инстанс)
                 handler_registry: "NpcActionHandlerRegistry", # Use string literal!

                 # --- Опциональные зависимости (которые НУЖНЫ В МЕТОДАХ САМОГО ПРОЦЕССОРА start/add/select_next_action) ---
                 # Получаем их из GameManager при инстанциировании Процессора.
                 # Эти же менеджеры будут переданы обработчикам через kwargs из complete_action
                 # Используйте строковые литералы для Optional зависимостей
                 rule_engine: Optional["RuleEngine"] = None, # Use string literal!
                 location_manager: Optional["LocationManager"] = None, # Use string literal!
                 character_manager: Optional["CharacterManager"] = None, # Use string literal!
                 time_manager: Optional["TimeManager"] = None, # Use string literal!
                 combat_manager: Optional["CombatManager"] = None, # Use string literal!
                 status_manager: Optional["StatusManager"] = None, # Use string literal!
                 party_manager: Optional["PartyManager"] = None, # Use string literal!
                 item_manager: Optional["ItemManager"] = None, # Use string literal!
                 economy_manager: Optional["EconomyManager"] = None, # Use string literal!
                 dialogue_manager: Optional["DialogueManager"] = None, # Use string literal!
                 crafting_manager: Optional["CraftingManager"] = None, # Use string literal!

                 # Processors needed in select_next_action or start/add logic
                 event_stage_processor: Optional["EventStageProcessor"] = None, # Use string literal!
                 event_action_processor: Optional["EventActionProcessor"] = None, # Use string literal!
                 character_action_processor: Optional["CharacterActionProcessor"] = None, # Use string literal!
                ):
        print("Initializing NpcActionProcessor...")
        # --- Сохранение всех переданных аргументов в self._... ---
        # Обязательные
        self._npc_manager = npc_manager # Сохраняем инстанс
        self._send_callback_factory = send_callback_factory
        self._settings = settings
        self._handler_registry = handler_registry # Сохраняем инстанс реестра обработчиков

        # TODO: Получить ID GM канала из settings при инициализации
        # Убедимся, что 'gm_channel_id' существует в settings и является числом (или строкой с числом)
        gm_channel_id_setting = self._settings.get('gm_channel_id')
        if isinstance(gm_channel_id_setting, (int, str)) and str(gm_channel_id_setting).isdigit(): # Check if int or digit string
             try:
                  self._gm_channel_id: Optional[int] = int(gm_channel_id_setting)
             except ValueError: # Should not happen if isdigit() passed, but for safety
                  print(f"NpcActionProcessor: Warning: Invalid 'gm_channel_id' in settings: '{gm_channel_id_setting}'. Expected integer or digit string. GM notifications disabled.")
                  self._gm_channel_id = None
        else:
             # Если не int и не строка с числом
             print(f"NpcActionProcessor: Warning: 'gm_channel_id' not found, not an integer, or not a digit string in settings. GM notifications disabled.")
             self._gm_channel_id = None


        # Опциональные менеджеры, которые НУЖНЫ В МЕТОДАХ САМОГО ПРОЦЕССОРА
        self._rule_engine = rule_engine
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._time_manager = time_manager
        self._combat_manager = combat_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._item_manager = item_manager
        self._economy_manager = economy_manager
        self._dialogue_manager = dialogue_manager # Сохраняем dialogue_manager
        self._crafting_manager = crafting_manager


        # Опциональные процессоры, которые НУЖНЫ В МЕТОДАХ САМОГО ПРОЦЕССОРА
        self._event_stage_processor = event_stage_processor
        self._event_action_processor = event_action_processor # Удален из нужных самому процессору в предыдущей версии RuleEngine, но возможно нужен?
        self._character_action_processor = character_action_processor # Удален из нужных самому процессору в предыдущей версии RuleEngine, но возможно нужен?


        print("NpcActionProcessor initialized.")

    # Метод для проверки занятости (ОСТАЕТСЯ В NpcManager)
    # def is_busy(self, npc_id: str) -> bool: ... (ОСТАЕТСЯ В NpcManager)


    # Methods for managing NPC individual actions (MOVED FROM NpcManager?)

    async def start_action(self, npc_id: str, action_data: Dict[str, Any], **kwargs: Any) -> bool: # Добавлена аннотация **kwargs
        """
        Начинает новое ИНДИВИДУАЛЬНОЕ действие для NPC.
        action_data: Словарь с данными действия (type, target_id, callback_data и т.п.).
        kwargs: Дополнительные менеджеры/сервисы, переданные при вызове (например, из WorldSimulationProcessor).
        Эти менеджеры могут быть использованы для валидации или расчета длительности.
        Возвращает True, если действие успешно начато, False иначе (напр., NPC занят).
        """
        print(f"NpcActionProcessor: Attempting to start action for NPC {npc_id}: {action_data.get('type')}")
        # Получаем NPC из менеджера NPC (это синхронный вызов)
        # Используем get_npc из _npc_manager
        npc = self._npc_manager.get_npc(npc_id) # type: Optional["NPC"] # Аннотация NPC
        if not npc:
             print(f"NpcActionProcessor: Error starting action: NPC {npc_id} not found.")
             # Не помечаем как dirty, потому что NPC не найден
             return False

        action_type = action_data.get('type')
        if not action_type:
             print(f"NpcActionProcessor: Error starting action: action_data is missing 'type'.")
             await self._notify_gm(f"❌ NPC {npc_id}: Не удалось начать действие: не указан тип действия.") # Пример
             return False

        # Проверяем, занят ли NPC (используя метод NpcManager)
        # NpcManager.is_busy учитывает индивидуальное действие И групповое действие партии (если NPC в партии).
        # Используем is_busy из _npc_manager
        if self._npc_manager.is_busy(npc_id): # Предполагается синхронный метод
             print(f"NpcActionProcessor: NPC {npc_id} is busy. Cannot start new action directly.")
             # TODO: Определить, разрешено ли добавлять этот тип действия в очередь для NPC. (Пока считаем, что нет)
             # Если разрешено:
             # return await self.add_action_to_queue(npc_id, action_data, **kwargs) # Передаем все kwargs дальше
             # Если не разрешено:
             await self._notify_gm(f"ℹ️ NPC {npc_id}: попытка начать действие '{action_type}' отменена - NPC занят.") # Пример уведомления
             return False # NPC занят и не может начать действие сразу или добавить в очередь


        # --- Выполнить логику старта действия: валидация и расчет длительности ---
        # Делегируем вспомогательному методу. Передаем npc_id и action_data.
        # Передаем все kwargs дальше (менеджеры из WSP)
        start_successful = await self._execute_start_action_logic(npc_id, action_data, **kwargs)
        if not start_successful:
             # Если логика старта вернула False (например, валидация не пройдена)
             print(f"NpcActionProcessor: Start logic failed for NPC {npc_id} action '{action_type}'. Action not started.")
             # _execute_start_action_logic уже отправил уведомление GM
             return False


        # --- Устанавливаем текущее действие в объекте NPC ---
        # Получаем NPC еще раз на случай, если _execute_start_action_logic была асинхронной и состояние могло измениться
        npc = self._npc_manager.get_npc(npc_id) # type: Optional["NPC"]
        if not npc: # Проверка на всякий случай
             print(f"NpcActionProcessor: Error starting action after start logic: NPC {npc_id} not found.")
             return False # Не можем установить действие, если NPC исче

        # Ensure npc object has current_action attribute
        if not hasattr(npc, 'current_action'):
            print(f"NpcActionProcessor: Error: NPC model for {npc_id} is missing 'current_action' attribute.")
            return False

        npc.current_action = action_data # action_data уже заполнен в _execute_start_action_logic
        # Помечаем NPC как измененного через его менеджер
        # NpcManager._dirty_npcs доступен напрямую для процессора
        # Используем _npc_manager._dirty_npcs
        if hasattr(self._npc_manager, '_dirty_npcs') and isinstance(self._npc_manager._dirty_npcs, set):
             self._npc_manager._dirty_npcs.add(npc_id)
        else:
             print(f"NpcActionProcessor: Warning: Cannot mark NPC {npc_id} dirty. _npc_manager._dirty_npcs is not a set or does not exist.")

        # Добавляем NPC в кеш сущностей с активным действием через его менеджер
        # NpcManager._entities_with_active_action доступен напрямую
        # Используем _npc_manager._entities_with_active_action
        if hasattr(self._npc_manager, '_entities_with_active_action') and isinstance(self._npc_manager._entities_with_active_action, set):
             self._npc_manager._entities_with_active_action.add(npc_id) # Uses Set (should be defined via typing)
        else:
             print(f"NpcActionProcessor: Warning: Cannot add NPC {npc_id} to active list. _npc_manager._entities_with_active_action is not a set or does not exist.")


        print(f"NpcActionProcessor: NPC {npc_id} action '{action_data['type']}' started. Duration: {action_data.get('total_duration', 0.0):.1f}. Marked as dirty.")

        # Сохранение в БД произойдет при вызове save_all_npcs через PersistenceManager (вызывается WorldSimulationProcessor)

        # TODO: Уведомить GM о начале действия NPC?
        await self._notify_gm(f"▶️ NPC {npc_id} начал действие: '{action_type}'. Длительность: {action_data.get('total_duration', 0.0):.1f} мин.")

        return True # Успешно начато

    async def _execute_start_action_logic(self, npc_id: str, action_data: Dict[str, Any], **kwargs: Any) -> bool: # Добавлена аннотация **kwargs
         """
         Вспомогательный метод для выполнения валидации и расчета длительности для действия NPC,
         которое собирается начаться. Модифицирует action_data in place.
         Возвращает True, если валидация пройдена, False иначе.
         kwargs: Менеджеры/сервисы, нужные для валидации/расчета.
         """
         npc = self._npc_manager.get_npc(npc_id) # type: Optional["NPC"]
         if not npc: return False # Should not happen if called from start_action, but safety check

         action_type = action_data.get('type')
         print(f"NpcActionProcessor: Executing start logic для NPC {npc_id}, action type '{action_type}'.")

         # Получаем необходимые менеджеры из kwargs. kwargs должны содержать ВСЕ менеджеры из WSP.
         # Используем kwargs.get(ключ, self._атрибут) для доступа к менеджерам, проинжектированным в __init__ процессора.
         # Это гарантирует, что менеджер будет доступен, даже если WSP не передал его в kwargs (что нежелательно).
         # Используем строковые литералы в аннотациях переменных, извлеченных из kwargs
         time_manager: Optional["TimeManager"] = kwargs.get('time_manager', self._time_manager)
         rule_engine: Optional["RuleEngine"] = kwargs.get('rule_engine', self._rule_engine)
         location_manager: Optional["LocationManager"] = kwargs.get('location_manager', self._location_manager)
         character_manager: Optional["CharacterManager"] = kwargs.get('character_manager', self._character_manager)
         combat_manager: Optional["CombatManager"] = kwargs.get('combat_manager', self._combat_manager)
         item_manager: Optional["ItemManager"] = kwargs.get('item_manager', self._item_manager)
         party_manager: Optional["PartyManager"] = kwargs.get('party_manager', self._party_manager)
         status_manager: Optional["StatusManager"] = kwargs.get('status_manager', self._status_manager)
         dialogue_manager: Optional["DialogueManager"] = kwargs.get('dialogue_manager', self._dialogue_manager) # Используем self._dialogue_manager
         crafting_manager: Optional["CraftingManager"] = kwargs.get('crafting_manager', self._crafting_manager) # Используем self._crafting_manager
         event_stage_processor: Optional["EventStageProcessor"] = kwargs.get('event_stage_processor', self._event_stage_processor)
         event_action_processor: Optional["EventActionProcessor"] = kwargs.get('event_action_processor', self._event_action_processor)
         character_action_processor: Optional["CharacterActionProcessor"] = kwargs.get('character_action_processor', self._character_action_processor)
         # Добавьте другие менеджеры по мере необходимости


         # Реализовать валидацию action_data специфичную для NPC и расчет total_duration с помощью RuleEngine
         # Передаем ВСЕ менеджеры из kwargs в контекст RuleEngine (или в вызовы методов других менеджеров)
         # Используем update для добавления kwargs в контекст RuleEngine, чтобы избежать Pylance Warning
         rule_context_kwargs: Dict[str, Any] = {}
         rule_context_kwargs.update(kwargs) # Добавляем все переданные kwargs

         calculated_duration = action_data.get('total_duration', 0.0) # Default to value in data, if any
         is_validation_successful = True # Флаг успешной валидации


         if action_type == 'move':
              target_location_id = action_data.get('target_location_id')
              if not target_location_id:
                   print(f"NpcActionProcessor: Error starting NPC move action: Missing target_location_id in action_data.")
                   await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта перемещения: не указана целевая локация.") # Пример
                   is_validation_successful = False
              # Валидация: существует ли целевая локация?
              # Assuming location_manager.get_location_static requires guild_id
              guild_id = kwargs.get('guild_id') # Need guild_id from kwargs/context
              if is_validation_successful and location_manager and hasattr(location_manager, 'get_location_static') and guild_id is not None and location_manager.get_location_static(guild_id, target_location_id) is None: # Add guild_id to get_location_static call
                 print(f"NpcActionProcessor: Error starting NPC move action: Target location '{target_location_id}' does not exist for guild {guild_id}.")
                 await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта перемещения: локация '{target_location_id}' не существует для гильдии {guild_id}.") # Пример
                 is_validation_successful = False
             # TODO: Дополнительная валидация: доступна ли локация из текущей (через выходы NPC)? (нужен rule_engine)
             # elif is_validation_successful and rule_engine and hasattr(rule_engine, 'is_location_accessible') and location_manager and guild_id is not None: # Only check if already successful
             #      current_location_id = getattr(npc, 'location_id', None)
             #      if current_location_id and not await rule_engine.is_location_accessible(current_location_id, target_location_id, context=rule_context_kwargs): # Pass context
             #           print(f"NpcActionProcessor: Error starting NPC move action: Target location '{target_location_id}' is not accessible from '{current_location_id}'.")
             #           await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта перемещения: локация '{target_location_id}' недоступна из текущей.") # Пример
             #           is_validation_successful = False


              # Если валидация перемещения успешна, сохраняем target_location_id в callback_data
              if is_validation_successful:
                   if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                       action_data['callback_data'] = {}
                   action_data['callback_data']['target_location_id'] = target_location_id

              # Расчет длительности перемещения (нужен rule_engine) - Только если валидация успешна
              # RuleEngine.calculate_npc_action_duration
              if is_validation_successful and rule_engine and hasattr(rule_engine, 'calculate_npc_action_duration'):
                  try:
                       # RuleEngine может рассчитать длительность на основе типа действия, NPC, контекста (включая location_manager).
                       calculated_duration = await rule_engine.calculate_npc_action_duration(action_type, npc=npc, action_context=action_data, **rule_context_kwargs) # Pass context
                  except Exception as e:
                       print(f"NpcActionProcessor: Error calculating move duration for NPC {npc_id}: {e}")
                       traceback.print_exc()
                       calculated_duration = action_data.get('total_duration', 0.0) # Fallback on error
              else:
                   # Fallback if no rule_engine or method, or validation failed
                   calculated_duration = action_data.get('total_duration', 0.0)


         elif action_type == 'combat_attack':
              target_id = action_data.get('target_id')
              target_type = action_data.get('target_type') # 'Character', 'NPC', 'Object'
              # Валидация цели (существует? в той же локации? валидный тип для атаки?)
              if not target_id or not target_type:
                   print(f"NpcActionProcessor: Error starting NPC attack action: Missing target_id or target_type.")
                   await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта атаки: не указана цель.")
                   is_validation_successful = False
              # TODO: Реализовать проверку существования и валидности цели (используя character_manager, npc_manager, item_manager/object_manager) и ее локации (location_manager)
              # requires guild_id if managers are per-guild
              # guild_id = kwargs.get('guild_id') # Need guild_id from kwargs/context
              # elif is_validation_successful and rule_engine and hasattr(rule_engine, 'is_attack_target_valid'): # Only check if already successful
              #      if not await rule_engine.is_attack_target_valid(npc, target_id, target_type, context=rule_context_kwargs): # Pass context
              #           print(f"NpcActionProcessor: Error starting NPC attack action: Target {target_type} ID {target_id} is not a valid attack target for {npc_id}.")
              #           await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта атаки: цель {target_id} недоступна или невалидна.")
              #           is_validation_successful = False
              # TODO: Проверить, находится ли NPC в бою (используя combat_manager). Атака возможна только в бою? (Политика игры)
              # elif is_validation_successful and combat_manager and hasattr(combat_manager, 'get_combat_by_participant_id'): # Only check if already successful
              #      # Assumes get_combat_by_participant_id needs participant_id and context
              #      if combat_manager.get_combat_by_participant_id(npc_id, context=rule_context_kwargs) is None: # Pass context
              #           print(f"NpcActionProcessor: Error starting NPC attack action: NPC {npc_id} is not in combat.")
              #           await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта атаки: NPC не в бою.")
              #           is_validation_successful = False


              # Расчет длительности атаки (нужен rule_engine, статы NPC, тип атаки) - Только если валидация успешна
              # RuleEngine.calculate_npc_action_duration
              if is_validation_successful and rule_engine and hasattr(rule_engine, 'calculate_npc_action_duration'):
                  try:
                       calculated_duration = await rule_engine.calculate_npc_action_duration(action_type, npc=npc, action_context=action_data, **rule_context_kwargs) # Pass context
                  except Exception as e:
                       print(f"NpcActionProcessor: Error calculating attack duration for NPC {npc_id}: {e}")
                       traceback.print_exc()
                       calculated_duration = action_data.get('total_duration', 0.0)
              else:
                   # Fallback if no rule_engine or method, or validation failed
                   calculated_duration = action_data.get('total_duration', 0.0)

              # Если валидация успешна, сохраняем данные цели в callback_data
              if is_validation_successful:
                   if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                       action_data['callback_data'] = {}
                   action_data['callback_data']['target_id'] = target_id
                   action_data['callback_data']['target_type'] = target_type
                   # TODO: Добавить combat_id в callback_data (если оно есть в контексте или бое)

         elif action_type == 'rest':
             # Валидация (NPC может отдыхать? Не в бою? Не под сильным эффектом?)
             # RuleEngine.can_rest
             # if rule_engine and hasattr(rule_engine, 'can_rest'):
             #      try:
             #           if not await rule_engine.can_rest(npc, context=rule_context_kwargs): # Pass context
             #                print(f"NpcActionProcessor: Error starting NPC rest action: NPC {npc_id} cannot rest now.")
             #                await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта отдыха: NPC не может сейчас отдыхать.")
             #                is_validation_successful = False
             #      except Exception as e: print(f"NpcActionProcessor: Error checking can_rest for {npc_id}: {e}"); traceback.print_exc(); is_validation_successful = False


             # Расчет длительности отдыха (нужен rule_engine) - Только если валидация успешна
             # RuleEngine.calculate_npc_action_duration
             if is_validation_successful and rule_engine and hasattr(rule_engine, 'calculate_npc_action_duration'):
                  try:
                       calculated_duration = await rule_engine.calculate_npc_action_duration(action_type, npc=npc, action_context=action_data, **rule_context_kwargs) # Pass context
                  except Exception as e:
                       print(f"NpcActionProcessor: Error calculating rest duration for NPC {npc_id}: {e}")
                       traceback.print_exc()
                       calculated_duration = action_data.get('total_duration', 10.0) # Fallback default
             else:
                   # Fallback if no rule_engine or method, or validation failed
                   calculated_duration = action_data.get('total_duration', 10.0)

             # TODO: Сохранить данные для завершения отдыха (callback_data), если нужно

         elif action_type == 'ai_dialogue': # Начать или продолжить диалог
              target_id = action_data.get('target_id')
              target_type = action_data.get('target_type')
              # Validate target exists and is in the same location (using character_manager, npc_manager, location_manager)
              # Validate if dialogue is possible (RuleEngine, DialogueManager?)
              if not target_id or not target_type:
                   print(f"NpcActionProcessor: Error starting NPC dialogue action: Missing target_id or target_type.")
                   await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта диалога: не указана цель.")
                   is_validation_successful = False
              # TODO: Реализовать проверку существования и валидности цели для диалога (character_manager, npc_manager) и ее локации (location_manager)
              # requires guild_id
              # guild_id = kwargs.get('guild_id') # Need guild_id
              # elif is_validation_successful and (character_manager or npc_manager) and dialogue_manager and location_manager and guild_id is not None and rule_engine and hasattr(rule_engine, 'is_dialogue_target_valid'): # Check managers and method existence
              #      target_obj = None # type: Optional["Character"] or Optional["NPC"]
              #      if target_type == 'Character' and character_manager: target_obj = character_manager.get_character(target_id) # Assuming get_character takes only id
              #      elif target_type == 'NPC' and npc_manager: target_obj = npc_manager.get_npc(target_id) # Assuming get_npc takes only id

              #      if target_obj and hasattr(target_obj, 'location_id') and target_obj.location_id is not None: # Check if target object found and has location
              #           npc_location_id = getattr(npc, 'location_id', None) # Check NPC location
              #           if npc_location_id is not None and str(target_obj.location_id) == str(npc_location_id): # Check if they are in the same location instance
              #                # Check RuleEngine specific dialogue rules
              #                try:
              #                     if not await rule_engine.is_dialogue_target_valid(npc, target_obj, context=rule_context_kwargs): # Pass context
              #                          print(f"NpcActionProcessor: Error starting NPC dialogue action: Target {target_type} ID {target_id} is not a valid dialogue target for {npc_id} (RuleEngine validation failed).")
              #                          await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта диалога: цель {target_id} недоступна или невалидна для диалога.")
              #                          is_validation_successful = False
              #                except Exception as e: print(f"NpcActionProcessor: Error checking RuleEngine.is_dialogue_target_valid for {npc_id}: {e}"); traceback.print_exc(); is_validation_successful = False

              #           else:
              #                print(f"NpcActionProcessor: Error starting NPC dialogue action: Target {target_type} ID {target_id} not found or not in the same location as NPC {npc_id}.")
              #                await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта диалога: цель {target_id} не найдена или не рядом.")
              #                is_validation_successful = False
              #      elif is_validation_successful: # If managers or rule_engine method are not available, assume invalid
              #           print(f"NpcActionProcessor: Warning: Dialogue validation attempted but required managers/methods not available for NPC {npc_id}.")
              #           await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта диалога: менеджеры валидации недоступны.")
              #           is_validation_successful = False


              # TODO: Если валидация успешна, сохранить данные цели и начальное состояние диалога в callback_data
              if is_validation_successful:
                   if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                       action_data['callback_data'] = {}
                   action_data['callback_data']['target_id'] = target_id
                   action_data['callback_data']['target_type'] = target_type
                   # TODO: action_data['callback_data']['dialogue_state'] = ... # Определить начальное состояние диалога (from DialogueManager?)
                   # TODO: action_data['callback_data']['event_id'] = ... # Store event ID if dialogue is event-bound


              # Расчет длительности диалога (может быть 0 или короткая задержка) - Только если валидация успешна
              # RuleEngine.calculate_npc_action_duration
              if is_validation_successful and rule_engine and hasattr(rule_engine, 'calculate_npc_action_duration'):
                  try:
                       calculated_duration = await rule_engine.calculate_npc_action_duration(action_type, npc=npc, action_context=action_data, **rule_context_kwargs) # Pass context
                  except Exception as e:
                       print(f"NpcActionProcessor: Error calculating dialogue duration for NPC {npc_id}: {e}")
                       traceback.print_exc()
                       calculated_duration = action_data.get('total_duration', 0.0) # Fallback default
              else:
                   # Fallback if no rule_engine or method, or validation failed
                   calculated_duration = action_data.get('total_duration', 0.0)


         elif action_type == 'search':
             # Валидация (может искать? что ищет? где ищет?)
             # requires location_manager
             # guild_id = kwargs.get('guild_id')
             # if is_validation_successful and rule_engine and hasattr(rule_engine, 'can_search') and location_manager and guild_id is not None:
             #      # Assumes can_search takes npc, context, and location_manager is in context
             #      if not await rule_engine.can_search(npc, context=rule_context_kwargs):
             #           print(f"NpcActionProcessor: Error starting NPC search action: NPC {npc_id} cannot search now.")
             #           await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта поиска: NPC не может сейчас искать.")
             #           is_validation_successful = False


             # Расчет длительности поиска (нужен rule_engine) - Только если валидация успешна
             # RuleEngine.calculate_npc_action_duration
             if is_validation_successful and rule_engine and hasattr(rule_engine, 'calculate_npc_action_duration'):
                  try:
                       calculated_duration = await rule_engine.calculate_npc_action_duration(action_type, npc=npc, action_context=action_data, **rule_context_kwargs) # Pass context
                  except Exception as e:
                       print(f"NpcActionProcessor: Error calculating search duration for NPC {npc_id}: {e}")
                       traceback.print_exc()
                       calculated_duration = action_data.get('total_duration', 10.0) # Fallback default
             else:
                   # Fallback if no rule_engine or method, or validation failed
                   calculated_duration = action_data.get('total_duration', 10.0)

             # TODO: Сохранить данные для завершения поиска (callback_data: area_searched, skill_check_result)
             # if is_validation_successful:
             #     if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
             #         action_data['callback_data'] = {}
             #     # Example: search area is NPC's current location instance ID
             #     action_data['callback_data']['search_area'] = getattr(npc, 'location_id', None)
             #     # action_data['callback_data']['skill_check_result'] = ... # Example: result of skill check in start logic (if search involves a skill check here)


         elif action_type == 'craft': # Если NPC могут крафтить
             # Requires CraftingManager (если есть), ItemManager, RuleEngine
             # Use kwargs.get for safety
             crafting_manager = kwargs.get('crafting_manager', self._crafting_manager) # type: Optional["CraftingManager"]
             item_manager = kwargs.get('item_manager', self._item_manager) # type: Optional["ItemManager"]
             # Валидация (есть рецепт? есть ингредиенты? есть навык?)
             recipe_id = action_data.get('recipe_id')
             if not recipe_id:
                  print(f"NpcActionProcessor: Error starting NPC craft action: Missing recipe_id.")
                  await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта крафта: не указан рецепт.")
                  is_validation_successful = False
             elif crafting_manager and hasattr(crafting_manager, 'can_craft'):
                  try:
                       # Assuming can_craft takes entity_id, recipe_id, entity_type='NPC', and context
                       # Requires guild_id if CraftingManager is per-guild
                       # guild_id = kwargs.get('guild_id')
                       # if guild_id is not None and not await crafting_manager.can_craft(npc_id, recipe_id, entity_type="NPC", context=rule_context_kwargs): # Pass context
                       if not await crafting_manager.can_craft(npc_id, recipe_id, context=rule_context_kwargs): # Pass context (assume guild_id handled internally)
                            print(f"NpcActionProcessor: Error starting NPC craft action: NPC {npc_id} cannot craft recipe {recipe_id} (validation failed).")
                            await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта крафта: NPC не может крафтить {recipe_id} сейчас.")
                            is_validation_successful = False
                  except Exception as e:
                       print(f"NpcActionProcessor: Error during CraftingManager.can_craft check for NPC {npc_id}: {e}")
                       traceback.print_exc()
                       await self._notify_gm(f"❌ NPC {npc_id}: Ошибка проверки возможности крафта {recipe_id}.")
                       is_validation_successful = False
             else:
                  # Если CraftingManager недоступен, но рецепт указан, считаем ошибкой.
                  print(f"NpcActionProcessor: Error starting NPC craft action: CraftingManager not available but recipe_id '{recipe_id}' specified.")
                  await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта крафта: менеджер крафта недоступен.")
                  is_validation_successful = False


             # Расчет длительности крафта (нужен rule_engine) - Только если валидация успешна
             # RuleEngine.calculate_npc_action_duration
             if is_validation_successful and rule_engine and hasattr(rule_engine, 'calculate_npc_action_duration'):
                  try:
                       calculated_duration = await rule_engine.calculate_npc_action_duration(action_type, npc=npc, action_context=action_data, **rule_context_kwargs) # Pass context
                  except Exception as e:
                       print(f"NpcActionProcessor: Error calculating craft duration for NPC {npc_id}: {e}")
                       traceback.print_exc()
                       calculated_duration = action_data.get('total_duration', 30.0) # Fallback default
             else:
                   # Fallback if no rule_engine or method, or validation failed
                   calculated_duration = action_data.get('total_duration', 30.0)

             # TODO: Сохранить данные для завершения крафта (callback_data: recipe_id, result_item_template_id, used_ingredients)
             if is_validation_successful:
                  if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                      action_data['callback_data'] = {}
                  action_data['callback_data']['recipe_id'] = recipe_id
                  # Assuming rule_engine or crafting_manager can determine the result item template ID based on recipe and skill
                  # action_data['callback_data']['result_item_template_id'] = await rule_engine.determine_craft_result(npc, recipe_id, context=rule_context_kwargs) # Example
                  # action_data['callback_data']['used_ingredients'] = ... # Save ingredients to remove on success


         elif action_type == 'use_item': # Если NPC могут использовать предметы
             # Requires ItemManager, RuleEngine, StatusManager, CharacterManager/NpcManager (для цели)
             # Use kwargs.get for safety
             item_manager = kwargs.get('item_manager', self._item_manager) # type: Optional["ItemManager"]
             rule_engine = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]
             status_manager = kwargs.get('status_manager', self._status_manager) # type: Optional["StatusManager"]
             character_manager = kwargs.get('character_manager', self._character_manager) # type: Optional["CharacterManager"]
             npc_manager_kw = kwargs.get('npc_manager', self._npc_manager) # Use different name to avoid shadowing self._npc_manager # type: Optional["NpcManager"]
             # Валидация (есть предмет? можно использовать? на цель?)
             item_id = action_data.get('item_id')
             target_id = action_data.get('target_id')
             target_type = action_data.get('target_type')

             if not item_id:
                   print(f"NpcActionProcessor: Error starting NPC use_item action: Missing item_id.")
                   await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта use_item: не указан предмет.")
                   is_validation_successful = False
             # TODO: Определить, требуется ли цель для этого предмета. Пока считаем, что требуется.
             elif not target_id or not target_type:
                  print(f"NpcActionProcessor: Error starting NPC use_item action: Missing target_id or target_type.")
                  await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта use_item: не указана цель.")
                  is_validation_successful = False

             # Проверка 2: Наличие предмета в инвентаре NPC
             # Предполагаем, что у объекта NPC есть атрибут 'inventory' типа List[str] или List[Dict]
             if is_validation_successful: # Выполняем только если предыдущие проверки прошли
                  # Assuming NPC inventory is List[Dict[str,Any]] with 'id' or 'item_id'
                  item_in_inventory = False
                  if hasattr(npc, 'inventory') and isinstance(npc.inventory, list):
                      for inv_item in npc.inventory:
                          if isinstance(inv_item, dict) and (inv_item.get('id') == item_id or inv_item.get('item_id') == item_id):
                               item_in_inventory = True
                               break
                          elif isinstance(inv_item, str) and inv_item == item_id: # Support simple list of IDs
                               item_in_inventory = True
                               break

                  if not hasattr(npc, 'inventory') or not isinstance(npc.inventory, list) or not item_in_inventory:
                       print(f"NpcActionProcessor: Error starting NPC use_item action: Item {item_id} not in NPC {npc_id} inventory.")
                       await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта use_item: предмета {item_id} нет в инвентаре NPC.")
                       is_validation_successful = False
                  # TODO: Опционально, проверить, существует ли предмет в ItemManager кеше, если он в инвентаре NPC (на случай рассинхронизации)
                  # elif is_validation_successful and item_manager and hasattr(item_manager, 'get_item') and item_manager.get_item(item_id) is None: # Only check if already successful
                  #      print(f"NpcActionProcessor: Warning: Item {item_id} in NPC {npc_id} inventory list but not found in ItemManager cache.")
                  #      # Решение: считать невалидным? Логировать и пропустить? Для старта, пусть будет невалидным.
                  #      await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта use_item: предмет {item_id} в инвентаре, но данные предмета не найдены.")
                  #      is_validation_successful = False


             # Проверка 3: Возможность использования предмета на цели (RuleEngine)
             # Требует RuleEngine, ItemManager, CharacterManager, NpcManager (для получения объекта цели)
             if is_validation_successful: # Выполняем только если предыдущие проверки прошли
                  if rule_engine and hasattr(rule_engine, 'can_use_item'):
                       try:
                            # Получаем объект предмета (опционально) и объект цели
                            item_obj = item_manager.get_item(item_id) if item_manager and hasattr(item_manager, 'get_item') else None # type: Optional["Any"] # Item object type
                            # ИСПРАВЛЕНИЕ: Используем оператор объединения типов | вместо or
                            target_obj = None # type: Optional["Character" | "NPC"] # Target object type - Use pipe |

                            if target_type == 'Character' and character_manager and hasattr(character_manager, 'get_character'): target_obj = character_manager.get_character(target_id)
                            elif target_type == 'NPC' and npc_manager_kw and hasattr(npc_manager_kw, 'get_npc'): target_obj = npc_manager_kw.get_npc(target_id)
                            # TODO: Get Object if target_type == 'Object' (requires ObjectManager?)

                            if item_obj and target_obj: # Check if item and target objects were successfully retrieved
                                 # can_use_item needs user (npc), item object, target object, context
                                 can_use = await rule_engine.can_use_item(npc, item_obj, target_obj, context=rule_context_kwargs) # Pass all managers in context
                                 if not can_use:
                                      print(f"NpcActionProcessor: Error starting NPC use_item action: RuleEngine validation failed for NPC {npc_id}, item {item_id}, target {target_id}.")
                                      await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта use_item: нельзя использовать предмет {item_id} на {target_id}.")
                                      is_validation_successful = False
                            # What if item doesn't require a target? The validation above assumes target is always required.
                            # If item doesn't require target, target_id/type might be None, and can_use_item check should handle it.
                            # else: print("RuleEngine.can_use_item check was not performed due to missing item or target object.")


                       except Exception as e:
                            print(f"NpcActionProcessor: Error during RuleEngine.can_use_item check for NPC {npc_id}: {e}")
                            traceback.print_exc()
                            await self._notify_gm(f"❌ NPC {npc_id}: Ошибка проверки возможности использования предмета {item_id} на {target_id}.")
                            is_validation_successful = False

                  else:
                       print(f"NpcActionProcessor: Warning: RuleEngine or can_use_item method not available for use_item validation for NPC {npc_id}.")
                       # Decide policy: if RuleEngine is mandatory for this validation, fail. If optional, log warning and proceed.
                       # Assume mandatory for now.
                       await self._notify_gm(f"❌ NPC {npc_id}: Ошибка старта use_item: система правил недоступна для валидации.")
                       is_validation_successful = False


             # Если валидация успешна, сохраняем данные для завершения use_item в callback_data
             if is_validation_successful:
                  if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                      action_data['callback_data'] = {}
                  action_data['callback_data']['item_id'] = item_id
                  if target_id is not None: # Only save target info if target was specified
                       action_data['callback_data']['target_id'] = target_id
                       action_data['callback_data']['target_type'] = target_type
                  # TODO: Сохранить другие данные, нужные для завершения (напр., эффект предмета?)


             # Расчет длительности использования предмета (обычно мгновенная или короткая) - Только если валидация успешна
             # RuleEngine.calculate_npc_action_duration
             if is_validation_successful and rule_engine and hasattr(rule_engine, 'calculate_npc_action_duration'):
                  try:
                       calculated_duration = await rule_engine.calculate_npc_action_duration(action_type, npc=npc, action_context=action_data, **rule_context_kwargs) # Pass context
                  except Exception as e:
                       print(f"NpcActionProcessor: Error calculating use_item duration for NPC {npc_id}: {e}")
                       traceback.print_exc()
                       calculated_duration = action_data.get('total_duration', 1.0) # Fallback default
             else:
                   # Fallback if no rule_engine or method, or validation failed
                   calculated_duration = action_data.get('total_duration', 1.0)


         else: # Обработка неизвестных или дефолтных типов действий
                 print(f"NpcActionProcessor: Info: Handling unknown or default action type '{action_type}' for NPC {npc_id}. Using default duration logic.")

                 # Если total_duration не указан в action_data или равен None, принимаем 0.0 как длительность по умолчанию.
                 # Иначе используем указанное значение.
                 calculated_duration = action_data.get('total_duration', 0.0)
                 # Убедимся, что calculated_duration является числом.
                 try:
                     calculated_duration = float(calculated_duration) if calculated_duration is not None else 0.0
                 except (ValueError, TypeError):
                     calculated_duration = 0.0
                     print(f"NpcActionProcessor: Warning: Invalid format for total_duration ('{action_data.get('total_duration', 'N/A')}', type {type(action_data.get('total_duration')).__name__}) for action '{action_type}'. Expected number. Set calculated_duration to 0.0.")

                 # Для неизвестных типов действий, is_validation_successful остается тем, что было установлено до этого else блока.
                 # Если предыдущих проверок не было или они прошли успешно, is_validation_successful будет True.


         # --- Присваиваем окончательную рассчитанную/валидированную длительность ---
         # Этот блок выполняется после всех if/elif/else, используя значение calculated_duration, определенное выше.
         # Убедимся, что calculated_duration является числом перед присвоением (проверка уже была)
         action_data['total_duration'] = float(calculated_duration) # Гарантируем, что длительность сохраняется как float


         # --- Устанавливаем время начала и прогресс ---
         # Устанавливаем время начала
         if time_manager and hasattr(time_manager, 'get_current_game_time'):
              # Assumes get_current_game_time doesn't need context, or context is implicitly available
              action_data['start_game_time'] = time_manager.get_current_game_time() # Presumed sync or async. If async, need await.
              # Let's assume get_current_game_time is synchronous based on common manager patterns
              if asyncio.iscoroutinefunction(getattr(time_manager, 'get_current_game_time')):
                   # If it's async, use await (handle cases where it's sync)
                   try:
                       action_data['start_game_time'] = await time_manager.get_current_game_time()
                   except Exception as e:
                       print(f"NpcActionProcessor: Error getting current game time (async) for action '{action_type}': {e}")
                       traceback.print_exc()
                       action_data['start_game_time'] = None
              else: # Assume synchronous
                    try:
                        action_data['start_game_time'] = time_manager.get_current_game_time()
                    except Exception as e:
                        print(f"NpcActionProcessor: Error getting current game time (sync) for action '{action_type}': {e}")
                        traceback.print_exc()
                        action_data['start_game_time'] = None

         else:
              print(f"NpcActionProcessor: Warning: Cannot get current game time for NPC action '{action_type}'. TimeManager not available or missing method. Start time is None.")
              action_data['start_game_time'] = None # Или можно считать это ошибкой и вернуть False?


         action_data['progress'] = 0.0 # Прогресс начинается с 0


         # Проверяем флаг is_validation_successful, установленный в if/elif/else блоках
         if not is_validation_successful:
              # Если валидация не пройдена на любом этапе
              return False

         # Если все проверки пройдены
         print(f"NpcActionProcessor: Start logic successful for NPC {npc_id}, action type '{action_type}'. Duration: {action_data.get('total_duration', 0.0):.1f}")
         return True # Validation passed, action_data is ready


    async def add_action_to_queue(self, npc_id: str, action_data: Dict[str, Any], **kwargs: Any) -> bool: # Добавлена аннотация **kwargs
        """
        Добавляет новое ИНДИВИДУАЛЬНОЕ действие в очередь NPC.
        kwargs: Дополнительные менеджеры/сервисы для валидации или расчета длительности.
        Возвращает True, если действие успешно добавлено, False иначе.
        """
        print(f"NpcActionProcessor: Attempting to add action to queue for NPC {npc_id}: {action_data.get('type')}")
        # Получаем NPC из менеджера NPC
        npc = self._npc_manager.get_npc(npc_id) # type: Optional["NPC"]
        if not npc:
             print(f"NpcActionProcessor: Error adding action to queue: NPC {npc_id} not found.")
             return False

        action_type = action_data.get('type')
        if not action_type:
             print(f"NpcActionProcessor: Error adding action to queue: action_data is missing 'type'.")
             await self._notify_gm(f"❌ NPC {npc_id}: Не удалось добавить действие в очередь: не указан тип действия.") # Пример
             return False

        # --- Валидация action_data для добавления в очередь (может быть менее строгой, чем для start_action) ---
        # Получаем необходимые менеджеры из kwargs или из атрибутов __init__ процессора.
        # Используем строковые литералы в аннотациях переменных, извлеченных из kwargs
        rule_engine: Optional["RuleEngine"] = kwargs.get('rule_engine', self._rule_engine)
        location_manager: Optional["LocationManager"] = kwargs.get('location_manager', self._location_manager) # Получаем LocationManager для валидации перемещения
        character_manager: Optional["CharacterManager"] = kwargs.get('character_manager', self._character_manager)
        npc_manager_kw: Optional["NpcManager"] = kwargs.get('npc_manager', self._npc_manager) # Need for get_npc_static or get_npc if not using self._
        item_manager: Optional["ItemManager"] = kwargs.get('item_manager', self._item_manager)
        party_manager: Optional["PartyManager"] = kwargs.get('party_manager', self._party_manager)
        combat_manager: Optional["CombatManager"] = kwargs.get('combat_manager', self._combat_manager)
        status_manager: Optional["StatusManager"] = kwargs.get('status_manager', self._status_manager)
        dialogue_manager: Optional["DialogueManager"] = kwargs.get('dialogue_manager', self._dialogue_manager) # Using self._dialogue_manager
        crafting_manager: Optional["CraftingManager"] = kwargs.get('crafting_manager', self._crafting_manager) # Using self._crafting_manager
        economy_manager: Optional["EconomyManager"] = kwargs.get('economy_manager', self._economy_manager)
        event_stage_processor: Optional["EventStageProcessor"] = kwargs.get('event_stage_processor', self._event_stage_processor)
        event_action_processor: Optional["EventActionProcessor"] = kwargs.get('event_action_processor', self._event_action_processor)
        character_action_processor: Optional["CharacterActionProcessor"] = kwargs.get('character_action_processor', self._character_action_processor)


        # Передаем ВСЕ менеджеры из kwargs в контекст RuleEngine (если нужен)
        rule_context_kwargs: Dict[str, Any] = {}
        rule_context_kwargs.update(kwargs)


        is_validation_successful = True # Флаг успешной валидации для очереди

        # Валидация для move в очереди (basic check if target_location_id exists)
        if action_type == 'move':
             target_location_id = action_data.get('target_location_id')
             if not target_location_id:
                  print(f"NpcActionProcessor: Error adding NPC move action to queue: Missing target_location_id in action_data.")
                  await self._notify_gm(f"❌ NPC {npc_id}: Не удалось добавить перемещение в очередь: не указана целевая локация.") # Пример
                  is_validation_successful = False
             # Optional: Basic validation if target location exists (less strict for queue than for start)
             # requires guild_id
             # guild_id = kwargs.get('guild_id')
             # elif is_validation_successful and location_manager and hasattr(location_manager, 'get_location_static') and guild_id is not None and location_manager.get_location_static(guild_id, target_location_id) is None:
             #    print(f"NpcActionProcessor: Error adding NPC move action to queue: Target location '{target_location_id}' does not exist for guild {guild_id}.")
             #    await self._notify_gm(f"❌ NPC {npc_id}: Не удалось добавить перемещение в очередь: локация '{target_location_id}' не существует для гильдии {guild_id}.") # Пример
             #    is_validation_successful = False

             # Сохраняем target_location_id в callback_data для complete_action (если валидация успешна)
             if is_validation_successful:
                 if 'callback_data' not in action_data or not isinstance(action_data['callback_data'], dict):
                     action_data['callback_data'] = {}
                 action_data['callback_data']['target_location_id'] = action_data.get('target_location_id')

        # Реализация TODO: Валидация для других типов действий в очереди (цель существует? и т.п.)
        # Для поставленных в очередь действий достаточно проверить наличие обязательных ID/параметров в action_data.
        # Полная валидация (существование цели, возможность действия и т.п.) произойдет, когда действие будет начато из очереди в _execute_start_action_logic.
        elif action_type in ['combat_attack', 'ai_dialogue', 'use_item', 'search', 'craft']:
             # Determine required IDs based on action type for minimal queue validation
             required_ids = []
             if action_type in ['combat_attack', 'ai_dialogue']:
                 required_ids.append('target_id')
             if action_type == 'use_item':
                 required_ids.append('target_id')
                 required_ids.append('item_id') # Use item requires both item and target
             if action_type == 'craft':
                 required_ids.append('recipe_id')
             # Note: 'search' action typically doesn't require a specific ID in the action data itself,
             # the search area might be implicit (current location) or defined by other parameters.
             # If 'search' needed a target_id (e.g., search a container), it would be added here.

             # Check if all required IDs are present and not None in action_data
             for req_id in required_ids:
                  if req_id not in action_data or action_data.get(req_id) is None:
                       print(f"NpcActionProcessor: Error adding '{action_type}' action to queue: Missing required parameter '{req_id}'.")
                       await self._notify_gm(f"❌ NPC {npc_id}: Не удалось добавить {action_type} в очередь: не указан обязательный параметр '{req_id}'.")
                       is_validation_successful = False
                       break # Stop checking required_ids for this action once one is missing


        # Note: For action types not explicitly handled above (e.g., 'rest', 'idle', 'interact'),
        # validation_successful remains True by default, as they may not require specific data in action_data.


        # TODO: Реализовать расчет total_duration с помощью RuleEngine (если он проинжектирован и имеет метод)
        # Важно рассчитать длительность ПЕРЕД добавлением в очередь, чтобы она сохранилась.
        # Используем ту же логику, что и в _execute_start_action_logic для расчета, но без полной валидации.
        calculated_duration = action_data.get('total_duration', 0.0) # Default to value in data, if any
        # RuleEngine.calculate_npc_action_duration
        if rule_engine and hasattr(rule_engine, 'calculate_npc_action_duration'): # Use the same duration calculation method as for starting
             try:
                  # Pass context including location_manager for move duration calculation if needed
                  # Pass all kwargs along so RuleEngine can use other managers.
                  calculated_duration = await rule_engine.calculate_npc_action_duration(action_type, npc=npc, action_context=action_data, **rule_context_kwargs) # Pass context
             except Exception as e:
                  print(f"NpcActionProcessor: Error calculating duration for NPC action type '{action_type}' for {npc_id} in queue: {e}")
                  traceback.print_exc()
                  calculated_duration = action_data.get('total_duration', 0.0) # Fallback on error

        # Убедимся, что duration является числом
        try: action_data['total_duration'] = float(calculated_duration) if calculated_duration is not None else 0.0
        except (ValueError, TypeError): action_data['total_duration'] = 0.0; print(f"NpcActionProcessor: Warning: Invalid total_duration for action '{action_type}' in queue. Set to 0.0.")


        # Если валидация не пройдена, не добавляем в очередь
        if not is_validation_successful:
            await self._notify_gm(f"❌ NPC {npc_id}: Валидация действия '{action_type}' для очереди провалена. Действие не добавлено.")
            return False


        action_data['start_game_time'] = None # Начальное время не известно, пока действие в очереди
        action_data['progress'] = 0.0 # Прогресс всегда 0 в очереди


        # Добавляем действие в конец очереди
        # Ensure action_queue exists and is a list in the NPC model
        if not hasattr(npc, 'action_queue') or not isinstance(npc.action_queue, list):
             print(f"NpcActionProcessor: Warning: NPC {npc_id} model has no 'action_queue' list or it's incorrect type. Creating empty list.")
             npc.action_queue = [] # Create an empty queue if it doesn't exist or is incorrect

        npc.action_queue.append(action_data)
        # Помечаем NPC как измененного через его менеджер
        # _npc_manager._dirty_npcs
        if hasattr(self._npc_manager, '_dirty_npcs') and isinstance(self._npc_manager._dirty_npcs, set):
             self._npc_manager._dirty_npcs.add(npc_id)
        else:
             print(f"NpcActionProcessor: Warning: Cannot mark NPC {npc_id} dirty (queue update). _npc_manager._dirty_npcs is not a set or does not exist.")

        # NPC считается "активным" для тика, пока у него есть очередь или действие.
        # _npc_manager._entities_with_active_action
        if hasattr(self._npc_manager, '_entities_with_active_action') and isinstance(self._npc_manager._entities_with_active_action, set):
             self._npc_manager._entities_with_active_action.add(npc_id) # Uses Set (should be defined via typing)
        else:
             print(f"NpcActionProcessor: Warning: Cannot add NPC {npc_id} to active list (queue not empty). _npc_manager._entities_with_active_action is not a set or does not exist.")


        print(f"NpcActionProcessor: Action '{action_data['type']}' added to queue for NPC {npc_id}. Queue length: {len(npc.action_queue)}. Marked as dirty.")

        # Сохранение в БД произойдет при вызове save_all_npcs через PersistenceManager

        # TODO: Уведомить GM об успешном добавлении в очередь NPC?
        await self._notify_gm(f"➡️ NPC {npc_id}: Действие '{action_type}' добавлено в очередь. Длительность: {action_data.get('total_duration', 0.0):.1f} мин. Очередь: {len(npc.action_queue)}")

        return True # Успешно добавлено в очередь


    # Метод обработки тика для ОДНОГО NPC (ПЕРЕНЕСЕН ИЗ NpcManager?)
    # WorldSimulationProcessor будет вызывать этот метод для каждого ID NPC, находящегося в кеше NpcManager._entities_with_active_action.
    async def process_tick(self, npc_id: str, game_time_delta: float, **kwargs: Any) -> None: # Добавлена аннотация **kwargs
        """
        Обрабатывает тик для текущего ИНДИВИДУАЛЬНОГО действия NPC.
        Этот метод вызывается WorldSimulationProcessor для каждого активного NPC.
        Обновляет прогресс, завершает действие при необходимости, начинает следующее из очереди (или выбирает новое).
        kwargs: Дополнительные менеджеры/сервисы (time_manager, send_callback_factory, etc.) passed by WSP.
        """
        # print(f"NpcActionProcessor: Processing tick for NPC {npc_id}...") # Can be very noisy

        # Получаем NPC из менеджера NPC (это синхронный вызов)
        npc = self._npc_manager.get_npc(npc_id) # type: Optional["NPC"]
        # Проверяем, что NPC все еще в кеше. Если нет или у него нет действия И пустая очередь, удаляем из активных (в менеджере NPC) и выходим.
        # Ensure the NPC object has current_action and action_queue attributes before checking
        # Use hasattr checks for safety
        if not npc or (getattr(npc, 'current_action', None) is None and (hasattr(npc, 'action_queue') and not getattr(npc, 'action_queue'))):
             # Удаляем из кеша сущностей с активным действием через менеджер NPC.
             # _entities_with_active_action доступен напрямую для процессора.
             # Use _npc_manager._entities_with_active_action
             if hasattr(self._npc_manager, '_entities_with_active_action') and isinstance(self._npc_manager._entities_with_active_action, set):
                  self._npc_manager._entities_with_active_action.discard(npc_id)
             else:
                  print(f"NpcActionProcessor: Warning: Cannot discard NPC {npc_id} from active list (tick). _npc_manager._entities_with_active_action is not a set or does not exist.")
             # print(f"NpcActionProcessor: Skipping tick for NPC {npc_id} (not found, no action, or empty queue).")
             return

        current_action = getattr(npc, 'current_action', None)
        action_completed = False # Completion flag


        # --- Обновляем прогресс текущего действия (если оно есть) ---
        if current_action is not None:
             duration = current_action.get('total_duration', 0.0)
             # Убедимся, что duration является числом
             if not isinstance(duration, (int, float)):
                  print(f"NpcActionProcessor: Warning: Duration for NPC {npc_id} action '{current_action.get('type', 'Unknown')}' is not a number ({duration}). Treating as 0.0.")
                  duration = 0.0

             if duration <= 0:
                  # Мгновенное действие (длительность <= 0). Считаем его завершенным немедленно.
                  # Прогресс не имеет смысла для мгновенных действий.
                  print(f"NpcActionProcessor: NPC {npc_id} action '{current_action.get('type', 'Unknown')}' is instant (duration <= 0). Marking as completed.")
                  action_completed = True
             else:
                  # Длительное действие. Обновляем прогресс.
                  progress = current_action.get('progress', 0.0)
                  # Убедимся, что progress является числом
                  if not isinstance(progress, (int, float)):
                       print(f"NpcActionProcessor: Warning: Progress for NPC {npc_id} action '{current_action.get('type', 'Unknown')}' is not a number ({progress}). Resetting to 0.0.")
                       progress = 0.0

                  # current_action is a dict, modifying it modifies the reference stored in npc.current_action
                  current_action['progress'] = progress + game_time_delta
                  # current_action['progress'] = min(current_action['progress'], duration) # Опционально: ограничить прогресс длительностью действия

                  # npc.current_action = current_action # Убедимся, что изменение сохраняется в объекте NPC (Это уже так, т.к. dict передан по ссылке)
                  # Помечаем NPC как измененного через его менеджер
                  # _npc_manager._dirty_npcs
                  if hasattr(self._npc_manager, '_dirty_npcs') and isinstance(self._npc_manager._dirty_npcs, set):
                       self._npc_manager._dirty_npcs.add(npc_id)
                  else:
                       print(f"NpcActionProcessor: Warning: Cannot mark NPC {npc_id} dirty (tick update). _npc_manager._dirty_npcs is not a set or does not exist.")


                  # --- Check for action completion ---
                  # Проверяем завершение даже если длительность была <= 0 (мгновенные действия)
                  if current_action['progress'] >= duration:
                       print(f"NpcActionProcessor: NPC {npc_id} action '{current_action.get('type', 'Unknown')}' completed.")
                       action_completed = True


        # --- Обработка завершения действия ---
        # Этот блок выполняется, ЕСЛИ действие завершилось в этом тике.
        if action_completed and current_action is not None: # Check current_action != None in case it was reset externally
             # complete_action сбросит current_action, пометит dirty, и начнет следующее из очереди (если есть) или вызовет select_next_action
             # Передаем все kwargs из WorldTick вместе с менеджерами процессора дальше в complete_action
             # kwargs already contain the necessary managers from WSP
             await self.complete_action(npc_id, current_action, **kwargs) # Pass kwargs

        # --- Проверяем, нужно ли удалить из активных после завершения или если не было действия и очередь пуста ---
        # complete_action уже запустил следующее действие ИЛИ оставил current_action = None ИЛИ вызвал select_next_action.
        # process_tick должен удалить из _entities_with_active_action, если NPC больше не активен после всех этих шагов.
        # Проверяем состояние NPC СНОВА после потенциального завершения действия, запуска следующего или выбора нового.
        # Ensure the NPC object has current_action and action_queue attributes before checking
        if getattr(npc, 'current_action', None) is None and (hasattr(npc, 'action_queue') and not getattr(npc, 'action_queue', [])): # Check action_queue safely
             # Если текущее действие все еще None И очередь пуста, значит, NPC больше не активен.
             # _npc_manager._entities_with_active_action
             if hasattr(self._npc_manager, '_entities_with_active_action') and isinstance(self._npc_manager._entities_with_active_action, set):
                  self._npc_manager._entities_with_active_action.discard(npc_id)
             else:
                  print(f"NpcActionProcessor: Warning: Cannot discard NPC {npc_id} from active list (after completion check). _npc_manager._entities_with_active_action is not a set or does not exist.")
             # print(f"NpcActionProcessor: Skipping tick for NPC {npc_id} (not found, no action, or empty queue).")
             return


        # Сохранение обновленного состояния NPC (если он помечен как dirty) произойдет в save_all_npcs.
        # process_tick пометил NPC как dirty, если прогресс изменился.
        # complete_action пометил NPC как dirty, если действие завершилось и/или очередь изменилась.
        # select_next_action пометит NPC dirty, если начал новое действие или добавил в очередь.


    # Метод для завершения ИНДИВИДУАЛЬНОГО действия NPC
    # Вызывается из process_tick, когда действие завершено.
    async def complete_action(self, npc_id: str, completed_action_data: Dict[str, Any], **kwargs: Any) -> None: # Добавлена аннотация **kwargs
        """
        Обрабатывает завершение ИНДИВИДУАЛЬНОГО действия для NPC.
        Вызывает логику завершения действия, сбрасывает current_action, начинает следующее из очереди или выбирает новое.
        kwargs: Дополнительные менеджеры/сервисы, переданные из WorldTick (send_callback_factory, item_manager, location_manager, etc.).
        """
        print(f"NpcActionProcessor: Completing action for NPC {npc_id}: {completed_action_data.get('type')}")
        # Получаем NPC из менеджера NPC
        npc = self._npc_manager.get_npc(npc_id) # type: Optional["NPC"]
        if not npc:
             print(f"NpcActionProcessor: Error completing action: NPC {npc_id} not found.")
             return # Cannot complete action

        # --- ВЫПОЛНИТЬ ЛОГИКУ ЗАВЕРШЕНИЯ ДЕЙСТВИЯ ---
        action_type = completed_action_data.get('type')
        # callback_data = completed_action_data.get('callback_data', {}) # callback_data passed to handler

        # Get the handler for this action type from the registry
        # Реестр обработчиков проинжектирован в __init__ как self._handler_registry
        handler = self._handler_registry.get_handler(action_type) # type: Optional["NpcActionHandlerRegistry"] # Type hint for handler object

        if handler and hasattr(handler, 'handle'): # Ensure handler exists and has a 'handle' method
            print(f"NpcActionProcessor: Found handler '{type(handler).__name__}' for action '{action_type}'. Executing.")
            try:
                # Pass the NPC object, action data, send_callback_factory,
                # and ALL OTHER managers/services received in **kwargs by process_tick/complete_action
                # The handler will use the managers it needs from **kwargs.
                # kwargs already contain the necessary managers from WSP/WorldTick
                # send_callback_factory is available via self._send_callback_factory
                await handler.handle(npc, completed_action_data, send_callback_factory=self._send_callback_factory, **kwargs) # Pass kwargs
                print(f"NpcActionProcessor: Handler for '{action_type}' executed successfully for NPC {npc.id}.")
            except Exception as e:
                 print(f"NpcActionProcessor: ❌ Error executing handler for action '{action_type}' for NPC {npc_id}: {e}")
                 traceback.print_exc()
                 await self._notify_gm(f"❌ NPC {npc_id}: Ошибка при обработке завершения действия '{action_type}': {e}")
        elif action_type: # Only warn if action_type exists but handler not found
            # Logic for unhandled action types
            print(f"NpcActionProcessor: Warning: No handler registered for individual action type '{action_type}' completed for NPC {npc_id}. No specific completion logic executed.")
            await self._notify_gm(f"☑️ NPC {npc_id}: Действие '{action_type}' завершено (без специфической логики завершения).")
        # If action_type is None, the completion shouldn't have happened like this, already logged earlier.


        # --- (Rest of complete_action method: reset current_action, check queue/AI) ---
        # Ensure npc object has current_action attribute before resetting
        if hasattr(npc, 'current_action'):
            npc.current_action = None # Сбрасываем текущее действие
            # Помечаем NPC как измененного через его менеджер (current_action стал None)
            # _npc_manager._dirty_npcs
            if hasattr(self._npc_manager, '_dirty_npcs') and isinstance(self._npc_manager._dirty_npcs, set):
                 self._npc_manager._dirty_npcs.add(npc_id)
            else:
                 print(f"NpcActionProcessor: Warning: Cannot mark NPC {npc_id} dirty (complete). _npc_manager._dirty_npcs is not a set or does not exist.")


        # Проверяем очередь после завершения текущего действия
        action_queue = getattr(npc, 'action_queue', []) # Get action queue safely
        if action_queue:
             # Получаем следующее действие из очереди
             next_action_data = action_queue.pop(0) # Удаляем из начала очереди (модифицирует npc.action_queue)
             # Помечаем NPC как измененного через его менеджер (очередь изменилась)
             # _npc_manager._dirty_npcs
             if hasattr(self._npc_manager, '_dirty_npcs') and isinstance(self._npc_manager._dirty_npcs, set):
                 self._npc_manager._dirty_npcs.add(npc_id)
             else:
                  print(f"NpcActionProcessor: Warning: Cannot mark NPC {npc_id} dirty (queue pop). _npc_manager._dirty_npcs is not a set or does not exist.")


             print(f"NpcActionProcessor: NPC {npc_id} starting next action from queue: {next_action_data.get('type')}. Queue length remaining: {len(action_queue)}.")

             # Начинаем следующее действие (вызываем start_action этого же процессора)
             # Передаем все необходимые менеджеры из kwargs дальше
             # kwargs contain managers from WSP/WorldTick
             await self.start_action(npc_id, next_action_data, **kwargs) # Pass kwargs

        else:
            # Если очередь пуста после завершения действия, NPC нужно выбрать новое действие (AI логика)
            print(f"NpcActionProcessor: NPC {npc_id}: Action queue empty. Selecting next action via AI.")
            await self.select_next_action(npc_id, **kwargs) # Pass kwargs to AI


    # Метод для выбора следующего действия NPC (логика AI) - НОВЫЙ МЕТОД
    # Вызывается из process_tick или complete_action, если у NPC нет текущего действия и пустая очередь.
    async def select_next_action(self, npc_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]: # Добавлена аннотация **kwargs
        """
        Определяет следующее действие для NPC на основе его AI, состояния мира и окружения.
        kwargs: Все необходимые менеджеры/сервисы для принятия решений AI (из WorldTick).
        Возвращает словарь с данными нового действия (для старта) или None, если действие не выбрано (что приведет к idle).
        """
        print(f"NpcActionProcessor: NPC {npc_id} selecting next action...")
        # Получаем NPC из менеджера NPC
        npc = self._npc_manager.get_npc(npc_id) # type: Optional["NPC"]
        if not npc:
             print(f"NpcActionProcessor: Error selecting next action: NPC {npc_id} not found.")
             # Don't return idle, NPC should be removed from active list
             return None

        # --- ЛОГИКА ВЫБОРА СЛЕДУЮЩЕГО ДЕЙСТВИЯ (AI) ---
        # Используйте self._rule_engine или специализированный AI Manager, если он есть.
        # Используйте другие менеджеры (CharacterManager, NpcManager, LocationManager, CombatManager и т.т.)
        # для получения информации о состоянии мира и сущностей.
        # context для RuleEngine/AI Manager должен включать ВСЕ менеджеры из kwargs.

        next_action_data: Optional[Dict[str, Any]] = None

        # Получаем необходимые менеджеры из kwargs или атрибутов __init__ процессора
        # kwargs уже содержат все менеджеры из WSP/WorldTick
        ai_context: Dict[str, Any] = kwargs # Use kwargs directly as the context dictionary


        rule_engine: Optional["RuleEngine"] = ai_context.get('rule_engine', self._rule_engine)
        char_manager: Optional["CharacterManager"] = ai_context.get('character_manager', self._character_manager)
        loc_manager: Optional["LocationManager"] = ai_context.get('location_manager', self._location_manager)
        combat_manager: Optional["CombatManager"] = ai_context.get('combat_manager', self._combat_manager)
        status_manager: Optional["StatusManager"] = ai_context.get('status_manager', self._status_manager)
        item_manager: Optional["ItemManager"] = ai_context.get('item_manager', self._item_manager)
        party_manager: Optional["PartyManager"] = ai_context.get('party_manager', self._party_manager)
        dialogue_manager: Optional["DialogueManager"] = ai_context.get('dialogue_manager', self._dialogue_manager) # Using self._dialogue_manager
        crafting_manager: Optional["CraftingManager"] = ai_context.get('crafting_manager', self._crafting_manager)
        economy_manager: Optional["EconomyManager"] = ai_context.get('economy_manager', self._economy_manager)
        event_stage_processor: Optional["EventStageProcessor"] = ai_context.get('event_stage_processor', self._event_stage_processor)
        event_action_processor: Optional["EventActionProcessor"] = ai_context.get('event_action_processor', self._event_action_processor)
        character_action_processor: Optional["CharacterActionProcessor"] = ai_context.get('character_action_processor', self._character_action_processor)

        # TODO: Получите другие менеджеры/процессоры, нужные AI


        # TODO: Реализовать сложную логику AI на основе шаблонов AI NPC и RuleEngine.
        # Это может включать:
        # 1. Оценка текущей ситуации (опасность, цели, потребности NPC).
        # 2. Выбор приоритетной цели (атака, отдых, сбор ресурса, диалог, перемещение).
        # 3. Определение конкретного действия для выбранной цели/потребности.


        # Пример базовой AI логики (приоритеты: Бой -> Отдых -> Мирное действие/Бездействие)

        # 1. Если NPC в бою, выбрать боевое действие.
        if combat_manager and hasattr(combat_manager, 'get_combat_by_participant_id'):
             # Assumes get_combat_by_participant_id takes participant_id and context
             current_combat = combat_manager.get_combat_by_participant_id(npc_id, context=ai_context) # Pass context # type: Optional["Combat"]
             if current_combat and rule_engine and hasattr(rule_engine, 'choose_combat_action_for_npc'):
                  # NPC в бою - выбрать боевое действие (атака, защита, использование навыка)
                  try:
                       # Передаем NPC, Combat и контекст. Контекст ai_context включает все менеджеры из kwargs.
                       next_action_data = await rule_engine.choose_combat_action_for_npc(npc, current_combat, context=ai_context) # Pass context
                  except Exception as e: print(f"NpcActionProcessor: Error in RuleEngine.choose_combat_action_for_npc for {npc_id}: {e}"); traceback.print_exc(); next_action_data = None

                  if next_action_data:
                       print(f"NpcActionProcessor: NPC {npc_id} chose combat action: {next_action_data.get('type')}")
                       # Боевое действие должно быть мгновенным или короткой длительности.
                       # Начнем его сразу, чтобы он действовал в этом раунде/тике боя.
                       # start_action ожидает менеджеры в kwargs. Передаем ai_context (все менеджеры из kwargs) дальше.
                       await self.start_action(npc_id, next_action_data, **ai_context)
                       return next_action_data # Возвращаем выбранное действие

        # 2. Если не в бою, но ранен (<50% здоровья) и может отдохнуть.
        # Убедимся, что здоровье числовое перед проверкой
        # Check if npc object has health and max_health attributes and they are numeric
        elif hasattr(npc, 'health') and hasattr(npc, 'max_health') and isinstance(npc.health, (int, float)) and isinstance(npc.max_health, (int, float)) and npc.max_health > 0 and npc.health < npc.max_health * 0.5:
            if rule_engine and hasattr(rule_engine, 'can_rest'):
                 # RuleEngine определяет, может ли NPC отдыхать сейчас (не в опасном месте и т.п.)
                 try:
                      # ai_context включает все менеджеры из kwargs
                      can_rest_now = await rule_engine.can_rest(npc, context=ai_context) # Pass context
                      if can_rest_now:
                           # Выбираем действие отдыха
                           next_action_data = {'type': 'rest'} # total_duration будет рассчитан в start_action
                           print(f"NpcActionProcessor: NPC {npc_id} is wounded ({npc.health}/{npc.max_health}) and decided to rest.")
                           # start_action ожидает менеджеры в kwargs. Передаем ai_context (все менеджеры из kwargs) дальше.
                           await self.start_action(npc_id, next_action_data, **ai_context)
                           return next_action_data
                 except Exception as e: print(f"NpcActionProcessor: Error checking can_rest for {npc_id}: {e}"); traceback.print_exc();

        # 3. Если не в бою и не нуждается в отдыхе (или не может отдыхать), выбрать мирное действие.
        # Мирная логика по умолчанию (bлуждание, взаимодействие, сбор ресурсов, простои и т.д.)
        if rule_engine and hasattr(rule_engine, 'choose_peaceful_action_for_npc'):
             try:
                  # RuleEngine выбирает мирное действие
                  # ai_context включает все менеджеры из kwargs
                  next_action_data = await rule_engine.choose_peaceful_action_for_npc(npc, context=ai_context) # Pass context
             except Exception as e: print(f"NpcActionProcessor: Error in RuleEngine.choose_peaceful_action_for_npc for {npc_id}: {e}"); traceback.print_exc(); next_action_data = None

             if next_action_data:
                  print(f"NpcActionProcessor: NPC {npc_id} chose peaceful action: {next_action_data.get('type')}")
                  # Мирное действие может быть длительным или мгновенным.
                  # Начнем его сразу (или добавим в очередь, если AI планирует несколько шагов).
                  # start_action ожидает менеджеры в kwargs. Передаем ai_context (все менеджеры из kwargs) дальше.
                  await self.start_action(npc_id, next_action_data, **ai_context) # Pass kwargs along
                  return next_action_data


        # Если RuleEngine или AI логика не выбрала следующее действие ИЛИ RuleEngine/метод отсутствуют
        print(f"NpcActionProcessor: NPC {npc_id}: AI did not select a next action or RuleEngine not available. Setting idle.")
        # Если действие не выбрано, NPC останется неактивным до внешнего триггере или следующего тика, когда его снова проверит AI (если он остался в активных).
        # current_action останется None, очередь пуста, NPC будет удален из _entities_with_active_action в process_tick.
        # Чтобы он остался активным для AI, можно добавить ему "бездействующее" действие (idle) с очень большой длительностью или None.
        # Это также гарантирует, что NPC будет "тикаться" и его AI будет перепроверяться.
        # idle_action_data = {'type': 'idle', 'total_duration': None} # Бесконечное бездействие
        # start_action ожидает менеджеры в kwargs. Передаем ai_context (все менеджеры из kwargs) дальше.
        # await self.start_action(npc_id, idle_action_data, **ai_context)

        # Возвращаем None, чтобы WorldSimulationProcessor мог решить, удалить ли NPC из активных.
        # process_tick уже обрабатывает удаление из активных, если current_action=None и очередь пуста.
        # Поэтому просто возвращаем None. AI может выбрать Idle как явное действие.
        return None # Возвращаем None, AI не выбрал специфического действия


    # Вспомогательный метод для отправки сообщений GM (нужен send_callback_factory и GM channel ID)
    # Этот метод остается здесь, т.с. Processor отвечает за логирование действий NPC.
    async def _notify_gm(self, message: str, **kwargs: Any) -> None: # Added **kwargs for potential context
         """
         Отправляет сообщение в GM канал через фабрику callback'ов, если канал определен.
         """
         # send_callback_factory проинжектирован в __init__ процессора
         if self._send_callback_factory is None:
              print(f"NpcActionProcessor: Warning: Cannot send GM notification. SendCallbackFactory not available.")
              # Fallback: log to console
              print(f"NpcActionProcessor (Console Fallback): GM Notification: {message}")
              return

         if self._gm_channel_id is not None:
              # Используем фабрику для получения callback'а для GM канала
              send_callback = self._send_callback_factory(self._gm_channel_id) # type: SendChannelMessageCallback
              try:
                  # Предполагаем, что SendChannelMessageCallback принимает сообщение и опциональный dict
                  await send_callback(message, None) # Use the corrected signature
              except Exception as e:
                  print(f"NpcActionProcessor: Error sending GM notification to channel {self._gm_channel_id}: {e}")
         else:
              # Если GM канал не определен, просто логируем в консоль (уже сделано выше)
              print(f"NpcActionProcessor (Console Fallback): GM Notification: {message}")


    # NOTE: get_entities_with_active_action остается в NpcManager.

    # NOTE: process_tick (для ОДНОГО NPC) перенесен сюда и реализован выше.

# Конец класса NpcActionProcessor

print("DEBUG: npc_action_processor.py module loaded.")
