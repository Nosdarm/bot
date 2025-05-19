# bot/game/managers/combat_manager.py

from __future__ import annotations
import json
import uuid # Если используется в методах (в текущем коде не видно, но может быть в неполных методах)
import traceback
import asyncio
# Импорт базовых типов
# ИСПРАВЛЕНИЕ: Импортируем Set и Tuple
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING, Set, Tuple # Import Set, Tuple, TYPE_CHECKING


# Импорт модели Combat (нужен при runtime для кеша и возвращаемых типов)
from bot.game.models.combat import Combat # Прямой импорт

# --- Imports needed ONLY for Type Checking ---
# Эти модули импортируются ТОЛЬКО для статического анализа (Pylance/Mypy).
# Это разрывает циклы импорта при runtime и помогает Pylance правильно резолвить типы.
# Используйте строковые литералы ("ClassName") для type hints в __init__ и методах
# для классов, импортированных здесь.
if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.item_manager import ItemManager
    # Add other managers/services needed for type hinting

    # ИСПРАВЛЕНИЕ: Импортируем Action Processors для Type Checking
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.npc_processors.npc_action_processor import NpcActionProcessor # Assuming this path is correct
    from bot.game.party_processors.party_action_processor import PartyActionProcessor

    # ИСПРАВЛЕНИЕ: Добавляем Combat сюда тоже, несмотря на прямой импорт выше.
    # Это нужно, чтобы Pylance корректно разрешал строковый литерал "Combat" в аннотациях.
    from bot.game.models.combat import Combat


# --- Imports needed at Runtime ---
# Для CombatManager обычно нужен только прямой импорт модели Combat и утилит.


# Send Callback Types (Callable types не требуют строковых литералов, если базовые типы определены)
# SendToChannelCallback = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]] # Если используется, но не в __init__ или методах
# SendCallbackFactory = Callable[[int], SendToChannelCallback] # Если используется, но не в __init__ или методах


print("DEBUG: combat_manager.py module loaded.")


class CombatManager:
    """
    Менеджер для управления боевыми сценами.
    Отвечает за запуск, ведение и завершение боев,
    хранит активные бои и координирует взаимодействие менеджеров.
    """
    # Required args для PersistenceManager (если CombatManager хранит динамические бои и сохраняет их)
    # Судя по save/load_all_combats (которые не реализованы) и кешу _active_combats, он хранит динамику.
    # Если бои по гильдиям, PersistenceManager будет вызывать save/load/rebuild_state(guild_id, **kwargs)
    # ИСПРАВЛЕНИЕ: Добавляем аннотацию типа List[str]
    required_args_for_load: List[str] = ["guild_id"] # Если загрузка per-guild
    # ИСПРАВЛЕНИЕ: Добавляем аннотацию типа List[str]
    required_args_for_save: List[str] = ["guild_id"] # Если сохранение per-guild
    # ИСПРАВЛЕНИЕ: Добавляем аннотацию типа List[str]
    required_args_for_rebuild: List[str] = ["guild_id"] # Если rebuild per-guild


    def __init__(
        self,
        # Используем строковые литералы для всех инжектированных зависимостей
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        rule_engine: Optional["RuleEngine"] = None,
        character_manager: Optional["CharacterManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        item_manager: Optional["ItemManager"] = None,
        # Добавьте другие инжектированные зависимости с Optional и строковыми литералами
    ):
        print("Initializing CombatManager...")
        # Сохраняем инжектированные зависимости как атрибуты
        self._db_adapter = db_adapter
        self._settings = settings
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._party_manager = party_manager
        self._status_manager = status_manager
        self._item_manager = item_manager

        # Кеш активных боев {combat_id: Combat_object}
        # ИСПРАВЛЕНИЕ: Аннотация кеша использует строковый литерал "Combat"
        # Если бои по гильдиям, кеш должен быть Dict[str, Dict[str, Combat]] = {guild_id: {combat_id: Combat_object}}
        self._active_combats: Dict[str, "Combat"] = {}

        # TODO: Добавить Set _dirty_combats и _deleted_combats_ids если CombatManager сохраняет динамику
        # self._dirty_combats: Set[str] = set() # {combat_id}
        # self._deleted_combats_ids: Set[str] = set() # {combat_id}


        print("CombatManager initialized.")

    # --- Методы получения ---
    # Используем строковый литерал в аннотации возвращаемого типа
    def get_combat(self, combat_id: str) -> Optional["Combat"]: # Аннотация Optional["Combat"]
        """Получить объект боя по ID (из кеша активных)."""
        return self._active_combats.get(combat_id)

    # Используем строковый литерал в аннотации возвращаемого типа
    def get_active_combats(self) -> List["Combat"]: # Аннотация List["Combat"]
        """Получить список всех активных боев (из кеша)."""
        return list(self._active_combats.values())

    # Используем строковый литерал в аннотации возвращаемого типа
    def get_combat_by_participant_id(self, entity_id: str) -> Optional["Combat"]: # Аннотация Optional["Combat"]
        """Найти бой, в котором участвует сущность."""
        for combat in self._active_combats.values():
            # Убеждаемся, что у объекта боя есть атрибут participants
            participants = getattr(combat, 'participants', [])
            # Participants ожидается быть списком словарей {'entity_id': ..., 'entity_type': ...}
            for info in participants:
                if isinstance(info, dict) and info.get('entity_id') == entity_id:
                    return combat
        return None

    # TODO: Implement get_combats_by_event_id(event_id: str) -> List["Combat"] if needed for event cleanup


    # TODO: Implement start_combat method
    # async def start_combat(self, guild_id: str, location_id: str, participant_ids: List[Tuple[str, str]], **kwargs: Any) -> Optional["Combat"]: # <-- Аннотация возвращаемого типа
    #      """Начинает новый бой в локации с участниками."""
    #      print(f"CombatManager: Starting new combat in location {location_id} for guild {guild_id} with participants: {participant_ids}...")
    #      # ... (логика создания боя) ...
    #      # self._active_combats.setdefault(guild_id, {})[new_combat_id] = new_combat # Пример per-guild кеша
    #      # self.mark_combat_dirty(new_combat_id) # Если dirty state per-combat
    #      return new_combat # Возвращаем созданный объект Combat


    # TODO: Переименовать process_combat_round в process_tick, чтобы соответствовать интерфейсу WSP
    async def process_tick(
        self,
        # Combat ID, который обрабатывается в этом тике
        combat_id: str,
        game_time_delta: float,
        # Контекст с менеджерами из WorldSimulationProcessor
        # ИСПРАВЛЕНИЕ: Добавляем аннотацию для **kwargs с типами процессоров
        **kwargs: Dict[str, Any],
    ) -> bool: # Возвращает True, если бой завершен, False иначе.
        """
        Обрабатывает один "тик" боя.
        Обновляет таймеры, обрабатывает действия участников, проверяет условия завершения раунда/боя.
        Этот метод вызывается WorldSimulationProcessor для каждого активного боя.
        """
        combat = self.get_combat(combat_id) # Type: Optional["Combat"]
        if not combat or not getattr(combat, 'is_active', False): # Use getattr safely
            # Бой уже не активен или не найден - можно считать, что его нужно удалить из тика WorldSimulationProcessor.
            # Возвращаем True, чтобы WSP знал, что этот бой завершен/недействителен.
            return True # Indicate combat is finished (should be removed from active processing)


        # print(f"CombatManager: Processing tick for combat {combat_id} (Round {getattr(combat, 'current_round', 'N/A')}, Timer {getattr(combat, 'round_timer', 'N/A'):.2f})...") # Debug


        # Убеждаемся, что у объекта Combat есть необходимые атрибуты для тика: round_timer, current_round
        if not hasattr(combat, 'round_timer') or not isinstance(getattr(combat, 'round_timer', None), (int, float)): combat.round_timer = 0.0 # Use getattr, validate type
        if not hasattr(combat, 'current_round') or not isinstance(getattr(combat, 'current_round', None), int): combat.current_round = 1

        # --- 1. Обновление таймера раунда ---
        combat.round_timer += game_time_delta

        # TODO: Проверка завершения раунда (например, по таймеру или всем участникам сходили?)
        # Получаем duration из settings (не передается в kwargs process_tick?) - да, Settings проинжектированы в __init__
        round_duration = float(self._settings.get('combat_settings', {}).get('round_duration_seconds', 6.0))


        if combat.round_timer >= round_duration:
            # Раунд завершен - обработка конца раунда
            print(f"CombatManager: Round {combat.current_round} finished for combat {combat_id}. Starting new round.")
            combat.round_timer = 0.0 # Сбрасываем таймер раунда
            combat.current_round += 1 # Увеличиваем номер раунда
            # TODO: Логика конца раунда: сброс состояний "сходил", разрешение отложенных эффектов, уведомление о начале нового раунда.
            # Можно вызвать внутренний метод _handle_end_of_round(combat, **kwargs)


        # --- 2. Check if combat ends ---
        # RuleEngine.check_combat_end_conditions(combat, context) -> bool (True if combat ends)
        # Get RuleEngine from kwargs (WSP passed it)
        rule_engine = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]

        combat_finished = False
        # Проверяем наличие RuleEngine и метода перед вызовом
        if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
            try:
                # check_combat_end_conditions needs the combat object and context with managers
                combat_finished = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs) # Pass combat and kwargs
            except Exception as e:
                print(f"CombatManager: Error during RuleEngine.check_combat_end_conditions for combat {combat_id}: {e}")
                import traceback
                print(traceback.format_exc())
                # If check fails, assume combat does not end to avoid infinite loop or unexpected state
                combat_finished = False
        # else: print(f"CombatManager: Warning: RuleEngine or check_combat_end_conditions method not available for combat end check in combat {combat_id}.")


        if combat_finished:
             # Combat is over. WSP will call end_combat after tick processing of all managers.
             # We just return True to signal WSP that this combat should be removed from the tick loop and ended by WSP.
             print(f"CombatManager: Combat {combat_id} meets end conditions. Signaling WSP.")
             return True # Indicate combat is finished (should be removed from active processing)


        # If combat did not finish in this tick and no end of round processing within CombatManager itself
        # Mark combat dirty if any state was changed during the tick (round_timer, current_round)
        self.mark_combat_dirty(combat_id) # Need method mark_combat_dirty


        # Combat did not finish
        return False # Indicate combat is ongoing

    # TODO: Implement mark_combat_dirty method
    # Needs _dirty_combats Set
    # def mark_combat_dirty(self, combat_id: str) -> None:
    #      """Помечает бой как измененный для последующего сохранения."""
    #      if combat_id in self._active_combats: # Mark only active combats as dirty? Or inactive ones too?
    #           if hasattr(self, '_dirty_combats') and isinstance(self._dirty_combats, Set): # Check attribute exists and is a Set
    #                self._dirty_combats.add(combat_id)
    #           else: print(f"CombatManager: Warning: Cannot mark combat {combat_id} dirty. _dirty_combats is not a Set or does not exist.")
    #      # Note: if combat is not in _active_combats, it might be a deleted combat. Should deleted be in _dirty_combats? Probably not.


    # --- Methods for handling participant actions completed during the tick ---
    # This method is expected to be called BY the Action Processors (CharAP, NPCAP, PartyAP)
    # when an entity's action (like attack, use item) finishes during their process_tick.
    # CombatManager then applies the combat-specific effects.
    async def handle_participant_action_complete(
        self,
        combat_id: str,
        participant_id: str, # ID сущности, которая завершила действие
        completed_action_data: Dict[str, Any], # Данные о завершенном действии (тип, цель, callback_data и т.д.)
        # TODO: Добавьте аннотацию для **kwargs
        **kwargs: Any, # Контекст с менеджерами и данными, переданный от ActionProcessor
    ) -> None:
        """
        Обрабатывает завершение ИНДИВИДУАЛЬНОГО действия участника боя.
        Этот метод вызывается ИЗ CharacterActionProcessor, NpcActionProcessor, PartyActionProcessor.
        Применяет боевые эффекты действия.
        """
        print(f"CombatManager: Action complete for participant {participant_id} ({completed_action_data.get('type')}) in combat {combat_id}.")
        combat = self.get_combat(combat_id) # Type: Optional["Combat"]
        # Если бой не активен или не найден, выходим.
        if not combat or not getattr(combat, 'is_active', False): # Use getattr safely
             print(f"CombatManager: Warning: Action completed for participant {participant_id} in non-active combat {combat_id}. Ignoring.")
             return # Не обрабатываем действие в неактивном бою

        # Убедимся, что участник действительно в этом бою
        # Assume participant_info is a dict with 'entity_id'
        is_participant_in_combat = any(info.get('entity_id') == participant_id for info in getattr(combat, 'participants', [])) # Use getattr safely
        if not is_participant_in_combat:
            print(f"CombatManager: Warning: Action completed for non-participant {participant_id} in combat {combat_id}. Ignoring.")
            return # Игнорируем действия сущностей, которые не являются участниками этого боя


        action_type = completed_action_data.get('type')
        # callback_data = completed_action_data.get('callback_data', {}) # callback_data from action data

        # TODO: Применение боевых эффектов действия с помощью RuleEngine
        # RuleEngine.apply_combat_action_effects
        rule_engine = kwargs.get('rule_engine', self._rule_engine) # Get RuleEngine from kwargs (passed by Action Processor) # type: Optional["RuleEngine"]

        # Проверяем наличие RuleEngine и метода перед вызовом
        if rule_engine and hasattr(rule_engine, 'apply_combat_action_effects'):
            print(f"CombatManager: Applying effects via RuleEngine for action '{action_type}' by {participant_id} in combat {combat_id}...")
            try:
                 # apply_combat_action_effects needs combat object, participant ID, action data, and context with managers.
                 # Pass combat object, participant ID, action data, and ALL kwargs received by this method as context for RuleEngine.
                 await rule_engine.apply_combat_action_effects(
                     combat=combat,
                     participant_id=participant_id,
                     completed_action_data=completed_action_data,
                     context=kwargs # Pass all kwargs received by handle_participant_action_complete
                 )
                 print(f"CombatManager: RuleEngine.apply_combat_action_effects executed successfully for {participant_id} in combat {combat_id}.")
                 # After applying effects, the state of Combat object might change.
                 # We should mark combat as dirty.
                 self.mark_combat_dirty(combat_id)

            except Exception as e:
                 print(f"CombatManager: ❌ Error applying combat action effects via RuleEngine for {participant_id} in {combat_id}: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # TODO: Обработка ошибки применения эффектов (логирование, оповещение GM)
        # else:
             # print(f"CombatManager: Warning: RuleEngine or apply_combat_action_effects method not available for applying combat action effects for {participant_id} in combat {combat_id}. No effects applied.")

        # TODO: Проверка условий завершения боя СНОВА после применения эффектов, если эффект может завершить бой (например, смерть последнего противника)
        # RuleEngine.check_combat_end_conditions
        # WSP отвечает за вызов end_combat на основе возвращаемого значения CombatManager.process_tick.
        # Здесь мы только помечаем бой dirty и обновляем его состояние.
        # WSP проверит состояние боя при следующем тике CombatManager.

        # Если бой не завершился после применения эффектов
        # Already marked dirty in the try block if apply_combat_action_effects was successful.


    # TODO: Implement end_combat method
    async def end_combat(
        self,
        combat_id: str,
        # TODO: Добавьте аннотацию для **kwargs
        **kwargs: Any, # Контекст с менеджерами и данными, переданный от WSP или handle_participant_action_complete
    ) -> None:
        """
        Координирует завершение боя.
        Удаляет бой из активных, запускает cleanup логику для участников, сохраняет финальное состояние.
        """
        print(f"CombatManager: Ending combat {combat_id}...")
        combat = self.get_combat(combat_id) # Type: Optional["Combat"]
        if not combat:
            print(f"CombatManager: Warning: Attempted to end non-existent combat {combat_id}.")
            return # Нечего завершать


        # Проверяем, не находится ли бой уже в процессе завершения или завершен
        if not getattr(combat, 'is_active', False): # Use getattr safely
             print(f"CombatManager: Combat {combat_id} is already marked as ended. Skipping end process.")
             return


        # --- 1. Помечаем бой как неактивный ---
        # Убедимся, что у объекта Combat есть атрибут is_active
        if hasattr(combat, 'is_active'):
            combat.is_active = False
        else:
             print(f"CombatManager: Warning: Combat object {combat_id} is missing 'is_active' attribute. Cannot mark as inactive.")
             # Решаем, что делать, если не можем пометить как неактивный. Log and proceed? Raise?
             # Продолжаем процесс завершения, даже если не удалось пометить is_active.
             pass

        # Помечаем бой dirty для сохранения финального состояния
        # Нужен метод mark_combat_dirty
        self.mark_combat_dirty(combat_id) # Помечаем бой как измененный

        # --- 2. Выполнение Cleanup Логики для участников ---
        # Проходим по всем участникам боя и запускаем их cleanup через их менеджеры.
        # Используем инжектированные менеджеры (self._...) и передаем контекст kwargs.
        # Cобрать контекст для методов clean_up_from_combat
        cleanup_context: Dict[str, Any] = { # Собрать контекст для методов clean_up_*
             'combat_id': combat_id,
             'combat': combat, # Передаем объект боя
             'guild_id': getattr(combat, 'guild_id', None), # Передаем guild_id боя (предполагаем, что у Combat есть такой атрибут)
             # TODO: Добавить другие необходимые менеджеры, сервисы из self._ в cleanup_context
             'character_manager': self._character_manager, # CharacterManager.clean_up_from_combat(char_id, context)
             'npc_manager': self._npc_manager, # NpcManager.clean_up_from_combat(npc_id, context)
             'party_manager': self._party_manager, # PartyManager.clean_up_from_combat(party_id, context)
             'status_manager': self._status_manager, # StatusManager.remove_combat_statuses_from_participants(combat_id, context)
             'item_manager': self._item_manager, # ItemManager.drop_items / clean_up_from_combat
             'rule_engine': self._rule_engine, # RuleEngine может быть нужен для cleanup логики (death triggers?)
             # Включаем прочие из kwargs, если передаются в end_combat (напр., send_callback_factory)
        }
        cleanup_context.update(kwargs) # Добавляем kwargs через update

        # Итерируем по копии списка участников, т.к. их менеджеры могут удалять из своих кешей
        participants_to_clean = list(getattr(combat, 'participants', [])) # Use getattr safely

        if participants_to_clean:
             print(f"CombatManager: Cleaning up {len(participants_to_clean)} participants for combat {combat_id}.")
             for participant_info in participants_to_clean:
                  # Убедимся, что participant_info - это словарь с entity_id и entity_type
                  if not isinstance(participant_info, dict) or participant_info.get('entity_id') is None or participant_info.get('entity_type') is None:
                       print(f"CombatManager: Warning: Invalid participant data during cleanup for combat {combat_id}: {participant_info}. Skipping.")
                       continue

                  p_id = participant_info['entity_id']
                  p_type = participant_info['entity_type']

                  try:
                       # Находим менеджер для типа участника и вызываем clean_up_from_combat
                       manager = None # type: Optional[Any]
                       clean_up_method_name = 'clean_up_from_combat' # Имя метода очистки в менеджере сущностей

                       if p_type == 'Character' and self._character_manager and hasattr(self._character_manager, clean_up_method_name):
                           manager = self._character_manager
                       elif p_type == 'NPC' and self._npc_manager and hasattr(self._npc_manager, clean_up_method_name):
                           manager = self._npc_manager
                       elif p_type == 'Party' and self._party_manager and hasattr(self._party_manager, clean_up_method_name):
                           manager = self._party_manager
                       # TODO: Добавить другие типы сущностей, если они могут быть участниками боя

                       # Если менеджер найден и имеет нужный метод очистки
                       if manager and clean_up_method_name:
                            await getattr(manager, clean_up_method_name)(p_id, context=cleanup_context) # Вызываем метод clean_up, передаем context
                            print(f"CombatManager: Cleaned up participant {p_type} {p_id} from combat {combat_id}.")
                       # else: // Log warning already done implicitly or can add explicit checks here

                  except Exception as e:
                       print(f"CombatManager: Error during cleanup for participant {p_type} {p_id} in combat {combat_id}: {e}")
                       import traceback
                       print(traceback.format_exc())
                       # Не пробрасываем ошибку, чтобы очистить других участников.

        # TODO: Очистка статусов боя со всех участников (StatusManager) - можно сделать одним вызовом
        if self._status_manager and hasattr(self._status_manager, 'remove_combat_statuses_from_participants'): # Предполагаем метод
             try: await self._status_manager.remove_combat_statuses_from_participants(combat_id, context=cleanup_context)
             except Exception as e: print(f"CombatManager: Error during combat status cleanup for {combat_id}: {e}"); import traceback; print(traceback.format_exc());
         # Или если StatusManager имеет более универсальный clean_up_for_entity или по event_id (если бой привязан к event)


        # TODO: Очистка временных предметов, брошенных в бою (ItemManager)
        # Если ItemManager имеет метод remove_items_dropped_in_combat(combat_id, context)
        # if self._item_manager and hasattr(self._item_manager, 'remove_items_dropped_in_combat'):
        #      try: await self._item_manager.remove_items_dropped_in_combat(combat_id, context=cleanup_context)
        #      except Exception as e: ... error handling ...

        # --- 3. Оповещение о завершении боя (опционально) ---
        # Если нужно отправить сообщение о завершении боя в канал
        send_callback_factory = cleanup_context.get('send_callback_factory') # Получаем фабрику из контекста
        combat_channel_id = getattr(combat, 'channel_id', None) # Получаем channel_id из объекта боя
        if send_callback_factory and combat_channel_id is not None:
             send_callback = send_callback_factory(int(combat_channel_id)) # Убеждаемся, что channel_id - int
             end_message_template: str = self._settings.get('combat_settings', {}).get('combat_end_message_template', f"Бой завершился в локации {getattr(combat, 'location_id', 'N/A')}.") # Шаблон сообщения
             # TODO: Определить результат боя (победа/поражение) и использовать в сообщении.
             # Можно получить из state_variables боя или определить RuleEngine.
             combat_result_text = "неопределен" # Placeholder
             # if hasattr(self._rule_engine, 'determine_combat_result'):
             #      try: combat_result_text = await self._rule_engine.determine_combat_result(combat, context=cleanup_context)
             #      except Exception as e: print(f"CombatManager: Error determining combat result for {combat_id}: {e}");

             end_message_content = end_message_template.format(combat_id=combat_id, location_id=getattr(combat, 'location_id', 'N/A'), result=combat_result_text) # Форматируем сообщение
             try:
                  await send_callback(end_message_content, None)
                  print(f"CombatManager: Sent combat end message for {combat_id} to channel {combat_channel_id}.")
             except Exception as e:
                  print(f"CombatManager: Error sending combat end message for {combat_id} to channel {combat_channel_id}: {e}")
                  import traceback
                  print(traceback.format_exc())


        # --- 4. Удаляем бой из кеша активных ---
        # Помечаем бой для удаления из БД, если CombatManager поддерживает это
        # self.mark_combat_deleted(combat_id) # Нужен метод mark_combat_deleted

        # Удаляем из кеша активных боев.
        # Если кеш плоский:
        self._active_combats.pop(combat_id, None) # Удаляем из глобального кеша активных боев
        # Если кеш по гильдиям:
        # guild_id = getattr(combat, 'guild_id', None)
        # if guild_id is not None and str(guild_id) in self._active_combats:
        #      self._active_combats[str(guild_id)].pop(combat_id, None)


        print(f"CombatManager: Combat {combat_id} fully ended and removed from active cache.")


    # TODO: Implement load_state(guild_id, **kwargs)
    # load_state загружает активные бои для определенной гильдии
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает активные бои для определенной гильдии."""
        if self._db_adapter is None:
            print(f"CombatManager: Warning: Cannot load combats for guild {guild_id}, DB adapter missing.")
            # TODO: Load placeholder data (e.g., create placeholder combats)
            return

        print(f"CombatManager: Loading combats for guild {guild_id}...")

        # TODO: Implement loading logic for CombatManager.
        # 1. Очистите кеш активных боев для этой гильдии (если кеш per-guild).
        #    Если _active_combats плоский {combat_id: Combat}, это БАГ при многогильдийности.
        #    self._active_combats.clear() # Очищает весь кеш - НЕПРАВИЛЬНО для многогильдийности.
        #    Идеально: _active_combats.setdefault(str(guild_id), {}).clear()
        self._active_combats.clear() # <-- ВРЕМЕННО ОЧИЩАЕТ ВСЕХ
        #    Нужен Set _dirty_combats и _deleted_combats_ids для этой гильдии - очистить их тоже.


        rows = []
        try:
            # 2. Выполните SQL SELECT FROM combats WHERE guild_id = ? AND is_active = 1
            sql = '''
            SELECT id, guild_id, location_id, is_active, participants, round_timer, current_round, combat_log, state_variables
            FROM combats
            WHERE guild_id = ? AND is_active = 1
            '''
            rows = await self._db_adapter.fetchall(sql, (str(guild_id),)) # Filter by guild_id and active
            print(f"CombatManager: Found {len(rows)} active combats in DB for guild {guild_id}.")

        except Exception as e:
            print(f"CombatManager: ❌ CRITICAL ERROR executing DB fetchall for combats for guild {guild_id}: {e}")
            import traceback
            print(traceback.format_exc())
            # TODO: Handle critical error (e.g., clear cache for this guild)
            raise # Пробрасываем критическую ошибку

        # 3. Для каждой строки создайте объект Combat (Combat.from_dict)
        loaded_count = 0
        # Если _active_combats плоский, загружаем в него
        # Если per-guild: guild_combats_cache = self._active_combats.setdefault(str(guild_id), {})
        for row in rows:
             data = dict(row)
             try:
                 # Validate and parse data
                 combat_id = data.get('id')
                 loaded_guild_id = data.get('guild_id')

                 if combat_id is None or str(loaded_guild_id) != str(guild_id):
                     print(f"CombatManager: Warning: Skipping combat with invalid ID ('{combat_id}') or mismatched guild ('{loaded_guild_id}') during load for guild {guild_id}.")
                     continue

                 # Parse JSON fields
                 data['participants'] = json.loads(data.get('participants') or '[]')
                 data['combat_log'] = json.loads(data.get('combat_log') or '[]')
                 data['state_variables'] = json.loads(data.get('state_variables') or '{}')
                 data['is_active'] = bool(data.get('is_active', 0))
                 data['round_timer'] = float(data.get('round_timer', 0.0)) # Convert to float
                 data['current_round'] = int(data.get('current_round', 1)) # Convert to int

                 # Create Combat object
                 combat = Combat.from_dict(data) # Requires Combat.from_dict method

                 # 4. Добавьте объект Combat в кеш активных боев.
                 self._active_combats[combat.id] = combat # Добавление в глобальный плоский кеш

                 # 5. Наполните Set _entities_with_active_action на основе участников загруженных боев.
                 # Это делается в CharacterManager/NpcManager/PartyManager, не в CombatManager.
                 # Менеджеры сущностей должны иметь метод (например, add_entities_from_combats(combats)).
                 # Это должно происходить в rebuild_runtime_caches этих менеджеров, которые получат загруженные бои из CombatManager через kwargs.

                 loaded_count += 1

             except Exception as e:
                 print(f"CombatManager: Error loading combat {data.get('id', 'N/A')} for guild {guild_id}: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # Continue loop for other rows


        print(f"CombatManager: Successfully loaded {loaded_count} active combats into cache for guild {guild_id}.")
        # TODO: Reset _dirty_combats and _deleted_combats_ids for this guild if they exist

    # TODO: Implement save_state(guild_id, **kwargs)
    # save_state сохраняет активные/измененные бои для определенной гильдии
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет активные/измененные бои для определенной гильдии."""
        if self._db_adapter is None:
            print(f"CombatManager: Warning: Cannot save combats for guild {guild_id}, DB adapter missing.")
            return

        print(f"CombatManager: Saving combats for guild {guild_id}...")

        # TODO: Implement saving logic for CombatManager.
        # 1. Соберите бои для этой гильдии, которые нужно сохранить.
        #    Из кеша _active_combats фильтруйте по guild_id. + Из _dirty_combats.
        #    Если кеш плоский, перебирайте values и фильтруйте по combat.guild_id.
        combats_to_save: List[Combat] = [
             combat for combat in self._active_combats.values()
             if getattr(combat, 'guild_id', None) == guild_id # Filter active combats by guild_id
             # TODO: Add filtering/inclusion of combats from _dirty_combats if they are not active
             # and need saving (e.g. ended combats with is_active=False)
             # Need to check if combat.id is in _dirty_combats
        ]
        # TODO: Collect IDs from _deleted_combats_ids that belong to this guild for deletion


        # 2. Используйте self._db_adapter.execute/execute_many с SQL (INSERT OR REPLACE, DELETE).
        #    Для INSERT OR REPLACE используйте upsert_sql как в CharacterManager
        #    Для DELETE используйте delete_sql как в CharacterManager (WHERE guild_id = ? AND id IN (...))

        print(f"CombatManager: Save state complete for guild {guild_id}. (Not fully implemented)") # Placeholder


    # TODO: Implement rebuild_runtime_caches(guild_id, **kwargs)
    def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        print(f"CombatManager: Rebuild runtime caches complete for guild {guild_id}. (Not fully implemented)") # Placeholder
        # Если у вас есть кеши, которые строятся на основе loaded combats (например, index participants by ID), это место.
        # Получаем все активные бои, загруженные для этой гильдии.
        # Если кеш _active_combats плоский, нужно его фильтровать.
        # loaded_combats_for_guild = [c for c in self._active_combats.values() if getattr(c, 'guild_id', None) == guild_id]
        # Постройте здесь кеши {participant_id: combat_id} или {location_id: set(combat_id)}.

    # TODO: Implement mark_combat_dirty method if saving edited but inactive combats
    # Needs _dirty_combats Set
    # def mark_combat_dirty(self, combat_id: str) -> None: ...


    # TODO: Implement mark_combat_deleted method if deleting from DB via PM.save_state
    # Needs _deleted_combats_ids Set
    # def mark_combat_deleted(self, combat_id: str) -> None: ...

# Конец класса CombatManager

print("DEBUG: combat_manager.py module loaded.")