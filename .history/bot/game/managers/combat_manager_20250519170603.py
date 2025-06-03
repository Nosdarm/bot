# bot/game/managers/combat_manager.py

from __future__ import annotations
import json
import uuid # Used in start_combat method (hypothetical)
import traceback
import asyncio
# Импорт базовых типов
# ИСПРАВЛЕНИЕ: Импортируем Set, Tuple, Union
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING, Set, Tuple, Union


# Импорт модели Combat (нужен при runtime для кеша и возвращаемых типов)
from bot.game.models.combat import Combat # Прямой импорт

# Import built-in types for isinstance checks
from builtins import dict, set, list, str, int, bool, float # Added relevant builtins


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
    # Добавьте другие менеджеры/сервисы, нужные для type hinting в контексте или напрямую
    from bot.game.managers.location_manager import LocationManager # Needed for location data/channels

    # ИСПРАВЛЕНИЕ: Импортируем Action Processors для Type Checking (если они передаются в context kwargs)
    # Предполагаем, что эти пути верны.
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.npc_processors.npc_action_processor import NpcActionProcessor
    from bot.game.party_processors.party_action_processor import PartyActionProcessor

    # ИСПРАВЛЕНИЕ: Добавляем Combat сюда тоже, несмотря на прямой импорт выше.
    # Это нужно, чтобы Pylance корректно разрешал строковый литерал "Combat" в аннотациях Dict[str, "Combat"].
    from bot.game.models.combat import Combat


# Send Callback Types (Callable types не требуют строковых литералов, если базовые типы определены)
# Не требуются здесь, т.к. send_callback_factory передается в context kwargs.
# SendToChannelCallback = Callable[..., Awaitable[Any]]
# SendCallbackFactory = Callable[[int], SendToChannelCallback]


print("DEBUG: combat_manager.py module loaded.")


class CombatManager:
    """
    Менеджер для управления боевыми сценами.
    Отвечает за запуск, ведение и завершение боев,
    хранит активные бои и координирует взаимодействие менеджеров.
    Работает на основе guild_id для многогильдийной поддержки.
    """
    # Required args для PersistenceManager (если CombatManager хранит динамические бои и сохраняет их)
    # Судя по save/load_state и кешу _active_combats, он хранит динамику.
    # Если бои по гильдиям, PersistenceManager будет вызывать save/load/rebuild_state(guild_id, **kwargs)
    required_args_for_load: List[str] = ["guild_id"] # Загрузка per-guild
    required_args_for_save: List[str] = ["guild_id"] # Сохранение per-guild
    # ИСПРАВЛЕНИЕ: Добавляем guild_id для rebuild_runtime_caches
    required_args_for_rebuild: List[str] = ["guild_id"] # Rebuild per-guild


    # --- Class-Level Attribute Annotations ---
    # Кеш активных боев {guild_id: {combat_id: Combat_object}}
    # ИСПРАВЛЕНИЕ: Кеш активных боев должен быть per-guild
    _active_combats: Dict[str, Dict[str, "Combat"]] # Аннотация кеша использует строковый литерал "Combat"

    # Для оптимизации персистенции (если CombatManager сохраняет динамические бои)
    # ИСПРАВЛЕНИЕ: _dirty_combats и _deleted_combats также должны быть per-guild
    _dirty_combats: Dict[str, Set[str]] # {guild_id: {combat_id}}
    _deleted_combats_ids: Dict[str, Set[str]] # {guild_id: {combat_id}}

    # TODO: Возможно, кеш {participant_id: combat_id} если часто нужно найти бой по участнику
    # _participant_to_combat_map: Dict[str, Dict[str, str]] # {guild_id: {participant_id: combat_id}}


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
        location_manager: Optional["LocationManager"] = None, # Added LocationManager dependency
        # Add other injected dependencies here with Optional and string literals
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
        self._location_manager = location_manager # Store LocationManager

        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые outer словари
        # Кеш активных боев: {guild_id: {combat_id: Combat}}
        self._active_combats = {} # Инициализируем как пустой dict, тип определен выше

        # Для оптимизации персистенции
        self._dirty_combats = {} # Инициализируем как пустой dict, тип определен выше
        self._deleted_combats_ids = {} # Инициализируем как пустой dict, тип определен выше

        # TODO: Инициализировать кеш {participant_id: combat_id} если нужен
        # self._participant_to_combat_map = {}

        print("CombatManager initialized.")

    # --- Методы получения ---
    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Метод get_combat должен принимать guild_id (или combat_id должен быть глобально уникальным, а менеджер фильтровать по guild_id?)
    # PersistenceManager работает per-guild, поэтому удобнее, чтобы менеджер работал per-guild.
    # Давайте переделаем get_combat, чтобы принимал guild_id.
    def get_combat(self, guild_id: str, combat_id: str) -> Optional["Combat"]: # Аннотация Optional["Combat"]
        """Получить объект боя по ID для определенной гильдии (из кеша активных)."""
        guild_id_str = str(guild_id)
        guild_combats = self._active_combats.get(guild_id_str) # Get per-guild cache
        if guild_combats:
             return guild_combats.get(combat_id)
        return None # Guild or combat not found


    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Метод get_active_combats должен принимать guild_id
    def get_active_combats(self, guild_id: str) -> List["Combat"]: # Аннотация List["Combat"]
        """Получить список всех активных боев для определенной гильдии (из кеша)."""
        guild_id_str = str(guild_id)
        guild_combats = self._active_combats.get(guild_id_str) # Get per-guild cache
        if guild_combats:
             return list(guild_combats.values())
        return [] # Return empty list if no active combats for guild


    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Метод get_combat_by_participant_id должен принимать guild_id
    def get_combat_by_participant_id(self, guild_id: str, entity_id: str) -> Optional["Combat"]: # Аннотация Optional["Combat"]
        """Найти бой, в котором участвует сущность для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Iterate only through active combats for this guild
        guild_combats = self._active_combats.get(guild_id_str)
        if guild_combats:
             for combat in guild_combats.values():
                 # Убеждаемся, что у объекта боя есть атрибут participants и это список словарей
                 participants = getattr(combat, 'participants', [])
                 if isinstance(participants, list):
                     # Participants expected format: List[Dict[str, Any]] where Dict contains 'entity_id'
                     for info in participants:
                         if isinstance(info, dict) and info.get('entity_id') == entity_id:
                             # Found the participant in this combat
                             return combat
        return None # Participant not found in any active combat for this guild


    # TODO: Implement get_combats_by_event_id(guild_id: str, event_id: str) -> List["Combat"] if needed for event cleanup
    def get_combats_by_event_id(self, guild_id: str, event_id: str) -> List["Combat"]:
         """Найти бои, связанные с определенным событием для данной гильдии."""
         guild_id_str = str(guild_id)
         combats_in_event = []
         guild_combats = self._active_combats.get(guild_id_str)
         if guild_combats:
              for combat in guild_combats.values():
                   # Assuming combat object has an 'event_id' attribute
                   if getattr(combat, 'event_id', None) == event_id:
                        combats_in_event.append(combat)
         return combats_in_event


    # TODO: Implement start_combat method
    # ИСПРАВЛЕНИЕ: start_combat должен принимать guild_id
    async def start_combat(self, guild_id: str, location_id: Optional[str], participant_ids: List[Tuple[str, str]], **kwargs: Any) -> Optional["Combat"]: # <-- Аннотация возвращаемого типа
         """Начинает новый бой в локации с участниками для определенной гильдии."""
         guild_id_str = str(guild_id)
         print(f"CombatManager: Starting new combat in location {location_id} for guild {guild_id_str} with participants: {participant_ids}...")

         if self._db_adapter is None:
             print(f"CombatManager: No DB adapter available for guild {guild_id_str}. Cannot start combat that requires persistence.")
             # Should starting combat require persistence? Maybe temporary combats don't.
             # For now, assume active combats should be persistent.
             return None

         # TODO: Validation: location_id exists, participants exist and belong to this guild etc.
         # Use injected managers (character_manager, npc_manager, party_manager) with guild_id checks.

         try:
             new_combat_id = str(uuid.uuid4()) # Uses uuid

             # Prepare participant data structure
             combat_participants_data: List[Dict[str, Any]] = []
             for p_id, p_type in participant_ids:
                  # TODO: Add validation and gather initial state/attributes for combat participants
                  # Use char_manager.get_character(guild_id_str, p_id), npc_manager.get_npc(guild_id_str, p_id) etc.
                  combat_participants_data.append({'entity_id': p_id, 'entity_type': p_type}) # Simple structure for now


             combat_data: Dict[str, Any] = {
                 'id': new_combat_id,
                 'guild_id': guild_id_str, # <--- Add guild_id
                 'location_id': str(location_id) if location_id is not None else None, # Store location instance ID
                 'is_active': True,
                 # TODO: Determine channel_id? Maybe from location_id via LocationManager?
                 'channel_id': kwargs.get('channel_id'), # Try to get channel_id from context kwargs
                 'event_id': kwargs.get('event_id'), # Link to event if applicable
                 'current_round': 1, # Start at round 1
                 'time_in_current_phase': 0.0, # Start timer at 0
                 'participants': combat_participants_data, # List of participant dicts
                 'combat_log': [], # Start with empty log
                 'state_variables': kwargs.get('initial_state_variables', {}), # Allow initial state from kwargs
             }

             # Create Combat object instance
             combat = Combat.from_dict(combat_data) # Requires Combat.from_dict


             # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш активных боев
             self._active_combats.setdefault(guild_id_str, {})[new_combat_id] = combat


             # ИСПРАВЛЕНИЕ: Помечаем новый бой dirty (per-guild)
             self.mark_combat_dirty(guild_id_str, new_combat_id)


             print(f"CombatManager: Combat {new_combat_id} started in location {location_id} for guild {guild_id_str}.")

             # TODO: Notify participants / location channel about combat start?
             # Use send_callback_factory from kwargs
             send_cb_factory = kwargs.get('send_callback_factory')
             combat_channel_id = getattr(combat, 'channel_id', None)
             if send_cb_factory and combat_channel_id is not None:
                  try:
                      send_cb = send_cb_factory(int(combat_channel_id))
                      location_name = "Неизвестная локация"
                      loc_mgr = kwargs.get('location_manager', self._location_manager)
                      if loc_mgr and location_id is not None:
                           location_name = loc_mgr.get_location_name(guild_id_str, location_id) or location_name

                      start_message = self._settings.get('combat_settings', {}).get('combat_start_message_template', f"Начинается бой в локации {location_name}!")
                      # TODO: Format message with participant names/factions?
                      await send_cb(start_message)
                  except Exception as e:
                       print(f"CombatManager: Error sending combat start message for {new_combat_id} to channel {combat_channel_id}: {e}"); traceback.print_exc();


             return combat # Return the created Combat object

         except Exception as e:
             print(f"CombatManager: Error starting combat in location {location_id} for guild {guild_id_str}: {e}")
             import traceback
             print(traceback.format_exc())
             return None


    # process_tick method - called by WorldSimulationProcessor
    # Already takes combat_id, game_time_delta, and **kwargs
    async def process_tick(
        self,
        combat_id: str,
        game_time_delta: float,
        **kwargs: Dict[str, Any], # Context with managers from WorldSimulationProcessor
    ) -> bool:
        """
        Обрабатывает один "тик" боя для определенной гильдии (guild_id находится в combat object).
        Возвращает True, если бой завершен, False иначе.
        """
        # ИСПРАВЛЕНИЕ: Получаем guild_id из kwargs или combat object (если load_state проставил его)
        guild_id = kwargs.get('guild_id') # Try get from context kwargs
        if guild_id is None:
             combat_obj = self.get_combat("_fallback_guild_id_", combat_id) # Try to get combat to check its guild_id if guild_id missing
             if combat_obj:
                  guild_id = getattr(combat_obj, 'guild_id', None)

        if guild_id is None:
             print(f"CombatManager: Warning: process_tick called for combat {combat_id} without guild_id in context or combat object. Cannot process.")
             # This indicates a problem upstream (WSP not passing guild_id or combat not loaded correctly).
             # To prevent this combat from being stuck, might return True to remove it from tick.
             return True # Indicate finished due to missing context


        guild_id_str = str(guild_id)
        combat = self.get_combat(guild_id_str, combat_id) # Get combat using guild_id and combat_id

        if not combat or not getattr(combat, 'is_active', False):
            # Combat is already inactive or not found for this guild - remove from WSP tick.
            # Log if it was expected to be active.
            # if combat: print(f"CombatManager: Combat {combat_id} in guild {guild_id_str} is inactive. Removing from tick.")
            # else: print(f"CombatManager: Combat {combat_id} not found for guild {guild_id_str}. Removing from tick.")
            return True # Indicate combat is finished/invalid


        # print(f"CombatManager: Processing tick for combat {combat_id} in guild {guild_id_str} (Round {getattr(combat, 'current_round', 'N/A')}, Timer {getattr(combat, 'round_timer', 'N/A'):.2f})...") # Debug


        # Убеждаемся, что у объекта Combat есть необходимые атрибуты для тика: round_timer, current_round
        if not hasattr(combat, 'round_timer') or not isinstance(getattr(combat, 'round_timer', None), (int, float)): combat.round_timer = 0.0 # Use getattr, validate type
        if not hasattr(combat, 'current_round') or not isinstance(getattr(combat, 'current_round', None), int): combat.current_round = 1


        # --- 1. Обновление таймера раунда ---
        combat.round_timer += game_time_delta

        # Get round duration from settings (use guild_id_str for per-guild settings if applicable)
        combat_settings = self._settings.get('combat_settings', {})
        round_duration = float(combat_settings.get('round_duration_seconds', 6.0))
        # TODO: Consider per-guild settings: self._settings.get('guilds', {}).get(guild_id_str, {}).get('combat_settings', {}).get('round_duration_seconds', ...)


        if combat.round_timer >= round_duration:
            # Round finished - handle end of round
            print(f"CombatManager: Round {combat.current_round} finished for combat {combat_id} in guild {guild_id_str}. Starting new round.")
            combat.round_timer = 0.0 # Reset round timer
            combat.current_round += 1 # Increment round number
            # TODO: End of round logic: reset "has acted" states, resolve delayed effects, notify new round.
            # Call internal method _handle_end_of_round(combat, **kwargs)
            # This internal method would also need guild_id or get it from combat object.


        # --- 2. Check if combat ends ---
        # Get RuleEngine from kwargs (WSP passed it)
        rule_engine = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]

        combat_finished = False
        # Check if RuleEngine and method are available
        if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
            try:
                # check_combat_end_conditions needs the combat object and context with managers.
                # Pass the combat object and the full kwargs context (which includes guild_id, managers, etc.).
                # RuleEngine should use guild_id from the combat object or context for per-guild logic.
                combat_finished = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs)
            except Exception as e:
                print(f"CombatManager: Error during RuleEngine.check_combat_end_conditions for combat {combat_id} in guild {guild_id_str}: {e}")
                import traceback
                print(traceback.format_exc())
                # If check fails, assume combat does not end to avoid infinite loop or unexpected state
                combat_finished = False
        # else: // Log warning already in RuleEngine or elsewhere


        # Mark combat dirty if any state was changed during the tick (round_timer, current_round, or by RuleEngine)
        # Assuming RuleEngine updates the combat object directly or returns changes to be applied.
        self.mark_combat_dirty(guild_id_str, combat_id) # Use method mark_combat_dirty with guild_id


        if combat_finished:
             # Combat is over. Signal WSP to call end_combat.
             print(f"CombatManager: Combat {combat_id} in guild {guild_id_str} meets end conditions. Signaling WSP.")
             return True # Indicate combat is finished (should be removed from active processing)


        # Combat did not finish
        return False # Indicate combat is ongoing


    # handle_participant_action_complete - called by Action Processors
    # Already takes combat_id, participant_id, completed_action_data, and **kwargs
    async def handle_participant_action_complete(
        self,
        combat_id: str,
        participant_id: str, # ID сущности, которая завершила действие
        completed_action_data: Dict[str, Any], # Данные о завершенном действии (тип, цель, callback_data и т.д.)
        **kwargs: Any, # Контекст с менеджерами и данными, переданный от ActionProcessor (includes guild_id)
    ) -> None:
        """
        Обрабатывает завершение ИНДИВИДУАЛЬНОГО действия участника боя.
        Этот метод вызывается ИЗ CharacterActionProcessor, NpcActionProcessor, PartyActionProcessor.
        Применяет боевые эффекты действия для боя в соответствующей гильдии.
        """
        # ИСПРАВЛЕНИЕ: Получаем guild_id из kwargs
        guild_id = kwargs.get('guild_id')
        if guild_id is None:
             print(f"CombatManager: Warning: handle_participant_action_complete called for combat {combat_id}, participant {participant_id} without guild_id in context. Cannot process.")
             return # Cannot process without guild_id

        guild_id_str = str(guild_id)
        print(f"CombatManager: Action complete for participant {participant_id} ({completed_action_data.get('type')}) in combat {combat_id} for guild {guild_id_str}.")

        # ИСПРАВЛЕНИЕ: Получаем бой с учетом guild_id
        combat = self.get_combat(guild_id_str, combat_id) # Type: Optional["Combat"]

        # Если бой не активен или не найден для этой гильдии, выходим.
        if not combat or not getattr(combat, 'is_active', False) or str(getattr(combat, 'guild_id', None)) != guild_id_str: # Use getattr safely, check guild_id
             print(f"CombatManager: Warning: Action completed for participant {participant_id} in non-active/missing/mismatched-guild combat {combat_id} (guild {guild_id_str}). Ignoring.")
             return # Ignore action in inactive, missing, or wrong-guild combat


        # Check if participant is actually listed in this combat's participants
        # Assume participant_info is a dict with 'entity_id'
        participants_list = getattr(combat, 'participants', [])
        is_participant_in_combat = False
        if isinstance(participants_list, list):
             is_participant_in_combat = any(isinstance(info, dict) and info.get('entity_id') == participant_id for info in participants_list)

        if not is_participant_in_combat:
            print(f"CombatManager: Warning: Action completed for non-participant {participant_id} in combat {combat_id} for guild {guild_id_str}. Ignoring.")
            return # Ignore actions from entities not listed as participants in this combat


        action_type = completed_action_data.get('type')

        # TODO: Применение боевых эффектов действия с помощью RuleEngine
        # RuleEngine.apply_combat_action_effects
        rule_engine = kwargs.get('rule_engine', self._rule_engine) # Get RuleEngine from kwargs (passed by Action Processor) # type: Optional["RuleEngine"]

        # Проверяем наличие RuleEngine и метода перед вызовом
        if rule_engine and hasattr(rule_engine, 'apply_combat_action_effects'):
            print(f"CombatManager: Applying effects via RuleEngine for action '{action_type}' by {participant_id} in combat {combat_id} for guild {guild_id_str}...")
            try:
                 # apply_combat_action_effects needs combat object, participant ID, action data, and context with managers.
                 # Pass combat object, participant ID, action data, and ALL kwargs received by this method as context for RuleEngine.
                 # RuleEngine is expected to use guild_id from the combat object or context for per-guild logic.
                 await rule_engine.apply_combat_action_effects(
                     combat=combat,
                     participant_id=participant_id,
                     completed_action_data=completed_action_data,
                     context=kwargs # Pass all kwargs received by handle_participant_action_complete
                 )
                 print(f"CombatManager: RuleEngine.apply_combat_action_effects executed successfully for {participant_id} in combat {combat_id} for guild {guild_id_str}.")
                 # After applying effects, the state of Combat object might change.
                 # We should mark combat as dirty.
                 self.mark_combat_dirty(guild_id_str, combat_id) # Use method mark_combat_dirty with guild_id

            except Exception as e:
                 print(f"CombatManager: ❌ Error applying combat action effects via RuleEngine for {participant_id} in {combat_id} for guild {guild_id_str}: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # TODO: Обработка ошибки применения эффектов (логирование, оповещение GM)
        # else:
             # print(f"CombatManager: Warning: RuleEngine or apply_combat_action_effects method not available for applying combat action effects for {participant_id} in combat {combat_id} for guild {guild_id_str}. No effects applied.")

        # Checking combat end conditions again after effects can be done here,
        # but it's usually handled by WSP in the next combat tick cycle for consistency.


    # end_combat method - called by WorldSimulationProcessor when process_tick returns True
    # Already takes combat_id and **kwargs
    async def end_combat(
        self,
        combat_id: str,
        **kwargs: Any, # Context with managers and data, passed by WSP or trigger logic (includes guild_id)
    ) -> None:
        """
        Координирует завершение боя для определенной гильдии.
        Удаляет бой из активных, запускает cleanup логику для участников, помечает для сохранения.
        """
        # ИСПРАВЛЕНИЕ: Получаем guild_id из kwargs
        guild_id = kwargs.get('guild_id')
        if guild_id is None:
             print(f"CombatManager: Warning: end_combat called for combat {combat_id} without guild_id in context. Cannot end combat.")
             return # Cannot end combat without guild_id

        guild_id_str = str(guild_id)
        print(f"CombatManager: Ending combat {combat_id} for guild {guild_id_str}...")

        # ИСПРАВЛЕНИЕ: Получаем бой с учетом guild_id
        combat = self.get_combat(guild_id_str, combat_id) # Type: Optional["Combat"]

        if not combat or str(getattr(combat, 'guild_id', None)) != guild_id_str: # Check guild_id match
            # If combat is not found for this guild, or guild_id mismatch, nothing to do.
            print(f"CombatManager: Warning: Attempted to end non-existent/mismatched-guild combat {combat_id} for guild {guild_id_str}.")
            return


        # Check if combat is already in the process of ending or ended
        if not getattr(combat, 'is_active', False): # Use getattr safely
             print(f"CombatManager: Combat {combat_id} in guild {guild_id_str} is already marked as ended. Skipping end process.")
             return


        # --- 1. Помечаем бой как неактивный ---
        # Убедимся, что у объекта Combat есть атрибут is_active
        if hasattr(combat, 'is_active'):
            combat.is_active = False # Mark as inactive in the object
        else:
             print(f"CombatManager: Warning: Combat object {combat_id} in guild {guild_id_str} is missing 'is_active' attribute. Cannot mark as inactive.")
             pass # Log and proceed


        # Помечаем бой dirty для сохранения финального состояния (is_active = False)
        self.mark_combat_dirty(guild_id_str, combat_id) # Use method mark_combat_dirty with guild_id

        # --- 2. Выполнение Cleanup Логики для участников и боя ---
        # Cобрать контекст для методов clean_up_*
        # Ensure essential managers are in context, preferring injected over kwargs if both exist.
        cleanup_context: Dict[str, Any] = {
             **kwargs, # Start with all incoming kwargs
             'combat_id': combat_id,
             'combat': combat, # Pass the combat object
             'guild_id': guild_id_str, # Ensure guild_id_str is in context

             # Critical managers for cleanup
             'character_manager': self._character_manager or kwargs.get('character_manager'),
             'npc_manager': self._npc_manager or kwargs.get('npc_manager'),
             'party_manager': self._party_manager or kwargs.get('party_manager'),
             'status_manager': self._status_manager or kwargs.get('status_manager'),
             'item_manager': self._item_manager or kwargs.get('item_manager'),
             'rule_engine': self._rule_engine or kwargs.get('rule_engine'),
             'location_manager': self._location_manager or kwargs.get('location_manager'), # Might need location manager for item drops
             # Add others...
        }


        # --- Cleanup participants ---
        # Iterate over a copy of the participants list
        participants_list = list(getattr(combat, 'participants', []))
        if participants_list:
             print(f"CombatManager: Cleaning up {len(participants_list)} participants for combat {combat_id} in guild {guild_id_str}.")
             for participant_info in participants_list:
                  if not isinstance(participant_info, dict) or participant_info.get('entity_id') is None or participant_info.get('entity_type') is None:
                       print(f"CombatManager: Warning: Invalid participant data during cleanup for combat {combat_id}: {participant_info}. Skipping.")
                       continue

                  p_id = participant_info['entity_id']
                  p_type = participant_info['entity_type']

                  try:
                       # Find the manager for the participant type and call clean_up_from_combat or clean_up_for_entity
                       manager = None # type: Optional[Any]
                       clean_up_method_name = 'clean_up_from_combat' # Specific method name
                       clean_up_entity_method_name = 'clean_up_for_entity' # Generic method name (preferred)

                       if p_type == 'Character' and (mgr := (cleanup_context.get('character_manager'))): # Get manager from context
                            if hasattr(mgr, clean_up_entity_method_name): manager = mgr ; clean_up_method_name = clean_up_entity_method_name
                            elif hasattr(mgr, 'clean_up_from_combat'): manager = mgr; clean_up_method_name = 'clean_up_from_combat' # Fallback specific

                       elif p_type == 'NPC' and (mgr := (cleanup_context.get('npc_manager'))): # Get manager from context
                            if hasattr(mgr, clean_up_entity_method_name): manager = mgr ; clean_up_method_name = clean_up_entity_method_name
                            elif hasattr(mgr, 'clean_up_from_combat'): manager = mgr; clean_up_method_name = 'clean_up_from_combat' # Fallback specific

                       elif p_type == 'Party' and (mgr := (cleanup_context.get('party_manager'))): # Get manager from context
                            if hasattr(mgr, clean_up_entity_method_name): manager = mgr ; clean_up_method_name = clean_up_entity_method_name
                            elif hasattr(mgr, 'clean_up_from_combat'): manager = mgr; clean_up_method_name = 'clean_up_from_combat' # Fallback specific

                       # TODO: Add other entity types

                       # If manager found and has a suitable cleanup method
                       if manager and clean_up_method_name and hasattr(manager, clean_up_method_name):
                            # Call the cleanup method, passing entity_id and context
                            if clean_up_method_name == clean_up_entity_method_name:
                                 # Generic method: clean_up_for_entity(entity_id, entity_type, context)
                                 await getattr(manager, clean_up_method_name)(p_id, p_type, context=cleanup_context)
                            else: # Specific method: clean_up_from_combat(entity_id, context)
                                 await getattr(manager, clean_up_method_name)(p_id, context=cleanup_context)

                            print(f"CombatManager: Cleaned up participant {p_type} {p_id} from combat {combat_id} in guild {guild_id_str} via {type(manager).__name__}.{clean_up_method_name}.")
                       # else: // Warning logged within manager lookup logic above

                  except Exception as e:
                       print(f"CombatManager: ❌ Error during cleanup for participant {p_type} {p_id} in combat {combat_id} for guild {guild_id_str}: {e}")
                       import traceback
                       print(traceback.format_exc())
                       # Do not re-raise error, continue cleanup for other participants.

        print(f"CombatManager: Finished participant cleanup for combat {combat_id} in guild {guild_id_str}.")


        # --- Other combat-specific cleanup ---
        # Omit party_id/combat_id from entities (done by entity managers' clean_up_from_combat)
        # Remove combat statuses (StatusManager)
        sm = cleanup_context.get('status_manager') # type: Optional["StatusManager"]
        if sm:
             if hasattr(sm, 'clean_up_for_combat'): # Preferred generic cleanup method for CombatManager
                  try: await sm.clean_up_for_combat(combat_id, context=cleanup_context)
                  except Exception as e: print(f"CombatManager: Error during status cleanup for combat {combat_id} in guild {guild_id_str}: {e}"); import traceback; print(traceback.format_exc());
             elif hasattr(sm, 'remove_combat_statuses_from_participants'): # Fallback specific method
                  try: await sm.remove_combat_statuses_from_participants(combat_id, context=cleanup_context)
                  except Exception as e: print(f"CombatManager: Error during combat status cleanup for {combat_id} in guild {guild_id_str}: {e}"); import traceback; print(traceback.format_exc());
             # else: // Log warning?

        # Handle dropped items? (ItemManager) - Might be handled by entity cleanup (e.g. character death drops items)
        # Or if combat itself causes items to drop (e.g., temporary combat loot)
        # item_mgr = cleanup_context.get('item_manager') # type: Optional["ItemManager"]
        # if item_mgr and hasattr(item_mgr, 'clean_up_for_combat'): # Assuming ItemManager has a method
        #      try: await item_mgr.clean_up_for_combat(combat_id, context=cleanup_context)
        #      except Exception as e: ...

        # TODO: Trigger combat end logic (RuleEngine?)
        rule_engine = cleanup_context.get('rule_engine') # type: Optional["RuleEngine"]
        if rule_engine and hasattr(rule_engine, 'trigger_combat_end'): # Assuming RuleEngine method
             try: await rule_engine.trigger_combat_end(combat, context=cleanup_context)
             except Exception as e: print(f"CombatManager: Error triggering combat end logic for {combat_id} in guild {guild_id_str}: {e}"); import traceback; print(traceback.format_exc());


        print(f"CombatManager: Combat {combat_id} cleanup processes complete for guild {guild_id_str}.")


        # --- 3. Удаляем бой из кеша активных и помечаем для удаления из DB ---

        # ИСПРАВЛЕНИЕ: Помечаем бой для удаления из DB (per-guild)
        # Use the correct per-guild deleted set
        self._deleted_combats_ids.setdefault(guild_id_str, set()).add(combat_id)


        # ИСПРАВЛЕНИЕ: Удаляем бой из per-guild кеша активных боев.
        # Use the correct per-guild active combats cache
        guild_combats_cache = self._active_combats.get(guild_id_str)
        if guild_combats_cache:
             guild_combats_cache.pop(combat_id, None) # Remove from per-guild cache


        # Убираем из dirty set, если там был (удален -> не dirty anymore for upsert)
        # Use the correct per-guild dirty set
        self._dirty_combats.get(guild_id_str, set()).discard(combat_id)


        print(f"CombatManager: Combat {combat_id} fully ended, removed from active cache, and marked for deletion for guild {guild_id_str}.")


    # load_state(guild_id, **kwargs) - called by PersistenceManager
    # Needs to load ACTIVE combats for the specific guild.
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает активные бои для определенной гильдии из базы данных в кеш."""
        guild_id_str = str(guild_id)
        print(f"CombatManager: Loading active combats for guild {guild_id_str} from DB...")

        if self._db_adapter is None:
            print(f"CombatManager: Warning: Cannot load combats for guild {guild_id_str}, DB adapter missing.")
            # TODO: In non-DB mode, load placeholder data
            return

        # ИСПРАВЛЕНИЕ: Очистите кеш активных боев ТОЛЬКО для этой гильдии перед загрузкой
        self._active_combats.pop(guild_id_str, None) # Remove old cache for this guild
        self._active_combats[guild_id_str] = {} # Create an empty cache for this guild

        # При загрузке, считаем, что все в DB "чистое", поэтому очищаем dirty/deleted для этой гильдии
        self._dirty_combats.pop(guild_id_str, None)
        self._deleted_combats_ids.pop(guild_id_str, None)


        rows = []
        try:
            # 2. Выполните SQL SELECT FROM combats WHERE guild_id = ? AND is_active = 1
            # ИСПРАВЛЕНИЕ: Исправлен SQL, добавлен combat_log и state_variables, удален round_timer (уже есть)
            # Исправлена ошибка "no such column: location_id" из лога - колонка location_id должна быть в схеме БД.
            sql = '''
            SELECT id, guild_id, location_id, is_active, participants, round_timer, current_round, combat_log, state_variables, channel_id, event_id
            FROM combats
            WHERE guild_id = ? AND is_active = 1
            '''
            rows = await self._db_adapter.fetchall(sql, (guild_id_str,)) # Filter by guild_id and active
            print(f"CombatManager: Found {len(rows)} active combats in DB for guild {guild_id_str}.")

        except Exception as e:
            print(f"CombatManager: ❌ CRITICAL ERROR executing DB fetchall for combats for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Clear cache for this guild on critical error
            self._active_combats.pop(guild_id_str, None)
            raise # Re-raise critical error


        loaded_count = 0
        # Get the cache dict for this specific guild
        guild_combats_cache = self._active_combats[guild_id_str]

        for row in rows:
             data = dict(row)
             try:
                 # Validate and parse data
                 combat_id_raw = data.get('id')
                 loaded_guild_id_raw = data.get('guild_id') # Should match guild_id_str due to WHERE clause

                 if combat_id_raw is None or loaded_guild_id_raw is None or str(loaded_guild_id_raw) != guild_id_str:
                     # This check is mostly redundant due to WHERE clause but safe.
                     print(f"CombatManager: Warning: Skipping combat row with invalid ID ('{combat_id_raw}') or mismatched guild ('{loaded_guild_id_raw}') during load for guild {guild_id_str}. Row: {row}.")
                     continue

                 combat_id = str(combat_id_raw)

                 # Parse JSON fields, handle None/malformed data gracefully
                 try:
                     data['participants'] = json.loads(data.get('participants') or '[]') if isinstance(data.get('participants'), (str, bytes)) else []
                 except (json.JSONDecodeError, TypeError):
                     print(f"CombatManager: Warning: Failed to parse participants for combat {combat_id} in guild {guild_id_str}. Setting to []. Data: {data.get('participants')}")
                     data['participants'] = []
                 else: # Ensure participant entries have required keys
                     data['participants'] = [p for p in data['participants'] if isinstance(p, dict) and p.get('entity_id') is not None and p.get('entity_type') is not None]


                 try:
                     data['combat_log'] = json.loads(data.get('combat_log') or '[]') if isinstance(data.get('combat_log'), (str, bytes)) else []
                 except (json.JSONDecodeError, TypeError):
                      print(f"CombatManager: Warning: Failed to parse combat_log for combat {combat_id} in guild {guild_id_str}. Setting to []. Data: {data.get('combat_log')}")
                      data['combat_log'] = []

                 try:
                     data['state_variables'] = json.loads(data.get('state_variables') or '{}') if isinstance(data.get('state_variables'), (str, bytes)) else {}
                 except (json.JSONDecodeError, TypeError):
                      print(f"CombatManager: Warning: Failed to parse state_variables for combat {combat_id} in guild {guild_id_str}. Setting to {{}}. Data: {data.get('state_variables')}")
                      data['state_variables'] = {}

                 # Convert boolean/numeric/string types, handle potential None/malformed data
                 data['is_active'] = bool(data.get('is_active', 0)) if data.get('is_active') is not None else True # Default True if None/missing
                 data['round_timer'] = float(data.get('round_timer', 0.0)) if isinstance(data.get('round_timer'), (int, float)) else 0.0
                 data['current_round'] = int(data.get('current_round', 1)) if isinstance(data.get('current_round'), int) else 1
                 data['location_id'] = str(data.get('location_id')) if data.get('location_id') is not None else None
                 data['channel_id'] = int(data.get('channel_id')) if data.get('channel_id') is not None else None # Store channel_id as int or None
                 data['event_id'] = str(data.get('event_id')) if data.get('event_id') is not None else None

                 # Update data dict with validated/converted values
                 data['id'] = combat_id
                 data['guild_id'] = guild_id_str # Ensure guild_id is string


                 # Create Combat object
                 combat = Combat.from_dict(data) # Requires Combat.from_dict method

                 # Add Combat object to the per-guild cache of active combats
                 guild_combats_cache[combat.id] = combat


                 # Participants' busy status is managed by Character/NPC Manager, not here during load.
                 # This happens in entity managers' rebuild_runtime_caches.


                 loaded_count += 1

             except Exception as e:
                 print(f"CombatManager: Error loading combat {data.get('id', 'N/A')} for guild {guild_id_str}: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # Continue loop for other rows


        print(f"CombatManager: Successfully loaded {loaded_count} active combats into cache for guild {guild_id_str}.")


    # save_state(guild_id, **kwargs) - called by PersistenceManager
    # Needs to save ACTIVE combats for the specific guild, AND delete marked-for-deletion ones.
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет активные/измененные бои для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"CombatManager: Saving combats for guild {guild_id_str}...")

        if self._db_adapter is None:
            print(f"CombatManager: Warning: Cannot save combats for guild {guild_id_str}, DB adapter missing.")
            return

        # ИСПРАВЛЕНИЕ: Соберите dirty/deleted ID ИЗ per-guild кешей
        # Note: Currently, only active combats marked dirty are saved.
        # If you need to save *all* ended combats (is_active=False) for logging/history,
        # adjust this logic to include non-active combats from cache belonging to this guild.
        dirty_combat_ids_for_guild_set = self._dirty_combats.get(guild_id_str, set()).copy() # Use a copy
        deleted_combat_ids_for_guild_set = self._deleted_combats_ids.get(guild_id_str, set()).copy() # Use a copy

        # Filter active combats by guild_id AND dirty status
        guild_combats_cache = self._active_combats.get(guild_id_str, {})
        combats_to_save: List["Combat"] = [
             combat for combat_id, combat in guild_combats_cache.items()
             if combat_id in dirty_combat_ids_for_guild_set # Only save if marked dirty
             and getattr(combat, 'guild_id', None) == guild_id_str # Double check guild_id
             # Note: This approach saves active, dirty combats. If an ended combat needs saving (is_active=False),
             # it must still be in _active_combats OR be retrieved specifically for saving.
             # The current logic saves only active combats marked dirty.
        ]


        if not combats_to_save and not deleted_combat_ids_for_guild_set:
            # print(f"CombatManager: No dirty or deleted combats to save for guild {guild_id_str}.") # Too noisy
            # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, очищаем per-guild dirty/deleted сеты
            self._dirty_combats.pop(guild_id_str, None)
            self._deleted_combats_ids.pop(guild_id_str, None)
            return

        print(f"CombatManager: Saving {len(combats_to_save)} dirty active, {len(deleted_combat_ids_for_guild_set)} deleted combats for guild {guild_id_str}...")


        try:
            # 1. Удаление боев, помеченных для удаления для этой гильдии
            if deleted_combat_ids_for_guild_set:
                 ids_to_delete = list(deleted_combat_ids_for_guild_set)
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 # Ensure deleting only for this guild and these IDs
                 delete_sql = f"DELETE FROM combats WHERE guild_id = ? AND id IN ({placeholders_del})"
                 try:
                     await self._db_adapter.execute(delete_sql, (guild_id_str, *tuple(ids_to_delete)))
                     print(f"CombatManager: Deleted {len(ids_to_delete)} combats from DB for guild {guild_id_str}.")
                     # ИСПРАВЛЕНИЕ: Очищаем per-guild deleted set after successful deletion
                     self._deleted_combats_ids.pop(guild_id_str, None)
                 except Exception as e:
                     print(f"CombatManager: Error deleting combats for guild {guild_id_str}: {e}")
                     import traceback
                     print(traceback.format_exc())
                     # Do NOT clear deleted set on error


            # 2. Обновить или вставить измененные бои для этого guild_id
            if combats_to_save:
                 print(f"CombatManager: Upserting {len(combats_to_save)} active combats for guild {guild_id_str}...")
                 # Use correct column names based on schema
                 upsert_sql = '''
                 INSERT OR REPLACE INTO combats
                 (id, guild_id, location_id, is_active, participants, round_timer, current_round, combat_log, state_variables, channel_id, event_id)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                 '''
                 data_to_upsert = []
                 upserted_combat_ids: Set[str] = set() # Track IDs successfully prepared

                 for combat in combats_to_save:
                      try:
                           # Ensure combat object has all required attributes
                           combat_id = getattr(combat, 'id', None)
                           combat_guild_id = getattr(combat, 'guild_id', None)

                           # Double check required fields and guild ID match
                           if combat_id is None or str(combat_guild_id) != guild_id_str:
                               print(f"CombatManager: Warning: Skipping upsert for combat with invalid ID ('{combat_id}') or mismatched guild ('{combat_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                               continue

                           location_id = getattr(combat, 'location_id', None)
                           is_active = getattr(combat, 'is_active', True)
                           participants = getattr(combat, 'participants', [])
                           round_timer = getattr(combat, 'round_timer', 0.0)
                           current_round = getattr(combat, 'current_round', 1)
                           combat_log = getattr(combat, 'combat_log', [])
                           state_variables = getattr(combat, 'state_variables', {})
                           channel_id = getattr(combat, 'channel_id', None)
                           event_id = getattr(combat, 'event_id', None)

                           # Ensure data types are suitable for JSON dumping
                           if not isinstance(participants, list): participants = []
                           if not isinstance(combat_log, list): combat_log = []
                           if not isinstance(state_variables, dict): state_variables = {}

                           participants_json = json.dumps(participants)
                           combat_log_json = json.dumps(combat_log)
                           state_variables_json = json.dumps(state_variables)


                           data_to_upsert.append((
                               str(combat_id),
                               guild_id_str, # Ensure guild_id string
                               str(location_id) if location_id is not None else None, # Ensure str or None
                               int(bool(is_active)), # Save bool as integer
                               participants_json,
                               float(round_timer),
                               int(current_round),
                               combat_log_json,
                               state_variables_json,
                               int(channel_id) if channel_id is not None else None, # Ensure int or None
                               str(event_id) if event_id is not None else None, # Ensure str or None
                           ))
                           upserted_combat_ids.add(str(combat_id)) # Track ID

                      except Exception as e:
                           print(f"CombatManager: Error preparing data for combat {getattr(combat, 'id', 'N/A')} (guild {getattr(combat, 'guild_id', 'N/A')}) for upsert: {e}")
                           import traceback
                           print(traceback.format_exc())
                           # This combat won't be saved but remains in _dirty_combats


                 if data_to_upsert:
                      if self._db_adapter is None:
                           print(f"CombatManager: Warning: DB adapter is None during combat upsert batch for guild {guild_id_str}.")
                      else:
                           await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                           print(f"CombatManager: Successfully upserted {len(data_to_upsert)} active combats for guild {guild_id_str}.")
                           # ИСПРАВЛЕНИЕ: Очищаем dirty set для этой гильдии только для успешно сохраненных ID
                           if guild_id_str in self._dirty_combats:
                                self._dirty_combats[guild_id_str].difference_update(upserted_combat_ids)
                                # If set is empty after update, remove the guild key
                                if not self._dirty_combats[guild_id_str]:
                                     del self._dirty_combats[guild_id_str]

                 # Note: Ended combats (is_active=False) are *not* saved by this logic, only deleted.
                 # If you need to save ended combats for history/logging, adjust the selection logic for combats_to_save.

        except Exception as e:
            print(f"CombatManager: ❌ Error during saving state for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Do NOT clear dirty/deleted sets on error to allow retry.
            # raise # Re-raise if critical


        print(f"CombatManager: Save state complete for guild {guild_id_str}.")


    # rebuild_runtime_caches(guild_id, **kwargs) - called by PersistenceManager
    # Rebuilds runtime caches specific to the guild after loading.
    # Already takes guild_id and **kwargs
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"CombatManager: Rebuilding runtime caches for guild {guild_id_str}. (Combat specific caches)")

        # Get all active combats loaded for this guild
        # Use the per-guild cache
        guild_combats = self._active_combats.get(guild_id_str, {}).values()

        # Example: Rebuild {participant_id: combat_id} map for this guild
        # if hasattr(self, '_participant_to_combat_map'): # Check if the attribute exists
        #      guild_participant_map = self._participant_to_combat_map.setdefault(guild_id_str, {})
        #      guild_participant_map.clear() # Clear old map for this guild
        #      for combat in guild_combats: # Iterate through combats loaded for THIS guild
        #           combat_id = getattr(combat, 'id', None)
        #           if combat_id is None:
        #                print(f"CombatManager: Warning: Skipping combat with no ID during rebuild for guild {guild_id_str}.")
        #                continue
        #           participants = getattr(combat, 'participants', [])
        #           if isinstance(participants, list):
        #                for participant_info in participants:
        #                     if isinstance(participant_info, dict) and participant_info.get('entity_id') is not None:
        #                          p_id = participant_info['entity_id']
        #                          # TODO: Check conflicts - one participant in multiple combats? (Shouldn't happen for active)
        #                          if p_id in guild_participant_map:
        #                               print(f"CombatManager: Warning: Participant {p_id} found in multiple active combats during rebuild for guild {guild_id_str}: was in {guild_participant_map[p_id]}, now in {combat_id}.")
        #                          guild_participant_map[p_id] = combat_id


        # Entity managers (Character, NPC, Party) need to know if their entities are busy in combat.
        # They will typically get CombatManager from kwargs and iterate through active combats (using get_active_combats(guild_id))
        # to rebuild *their own* per-guild busy status caches.
        # Example in CharacterManager.rebuild_runtime_caches:
        # combat_mgr = kwargs.get('combat_manager') # type: Optional["CombatManager"]
        # if combat_mgr and hasattr(combat_mgr, 'get_active_combats'):
        #      active_combats_for_guild = combat_mgr.get_active_combats(guild_id_str) # Get active combats for THIS guild
        #      # Iterate through these combats and update character busy status...


        print(f"CombatManager: Rebuild runtime caches complete for guild {guild_id_str}. (Combat specific caches)")


    # TODO: Implement mark_combat_dirty method
    # Needs _dirty_combats Set (per-guild)
    # ИСПРАВЛЕНИЕ: mark_combat_dirty должен принимать guild_id
    def mark_combat_dirty(self, guild_id: str, combat_id: str) -> None:
         """Помечает бой как измененный для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         # Add check that the combat ID exists in the per-guild active cache
         guild_combats_cache = self._active_combats.get(guild_id_str)
         if guild_combats_cache and combat_id in guild_combats_cache:
              # Add to the per-guild dirty set
              self._dirty_combats.setdefault(guild_id_str, set()).add(combat_id)
         # else: print(f"CombatManager: Warning: Attempted to mark non-existent combat {combat_id} in guild {guild_id_str} as dirty.") # Too noisy?


    # TODO: Implement clean_up_for_entity(entity_id, entity_type, context) method (used by Character/NPC/Party Managers)
    # This method is called by CharacterManager.remove_character, NpcManager.remove_npc etc.
    # or by PartyManager.remove_member, NOT by CombatManager itself.
    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
         """
         Удаляет сущность из любого боя, в котором она участвует.
         Предназначен для вызова менеджерами сущностей (Character, NPC, Party).
         """
         # ИСПРАВЛЕНИЕ: Получаем guild_id из kwargs
         guild_id = kwargs.get('guild_id')
         if guild_id is None:
              print(f"CombatManager: Warning: clean_up_for_entity called for {entity_type} {entity_id} without guild_id in context. Cannot clean up from combat.")
              return # Cannot clean up without guild_id

         guild_id_str = str(guild_id)
         print(f"CombatManager: Cleaning up {entity_type} {entity_id} from combat in guild {guild_id_str}...")

         # Find the combat the entity is in within this guild
         # Use the updated get_combat_by_participant_id that takes guild_id
         combat = self.get_combat_by_participant_id(guild_id_str, entity_id) # Type: Optional["Combat"]

         if combat:
              combat_id = getattr(combat, 'id', None)
              if not combat_id:
                   print(f"CombatManager: Warning: Found combat object with no ID for participant {entity_id} in guild {guild_id_str} during cleanup.")
                   return # Cannot clean up without combat ID

              # Remove the participant from the combat object's participants list
              participants_list = getattr(combat, 'participants', [])
              if isinstance(participants_list, list):
                  initial_count = len(participants_list)
                  # Create a new list excluding the participant
                  new_participants_list = [
                      info for info in participants_list
                      if not (isinstance(info, dict) and info.get('entity_id') == entity_id and info.get('entity_type') == entity_type)
                  ]
                  # If the list size changed, the participant was found and removed
                  if len(new_participants_list) < initial_count:
                       combat.participants = new_participants_list # Update the combat object
                       print(f"CombatManager: Removed {entity_type} {entity_id} from participant list of combat {combat_id} in guild {guild_id_str}.")
                       self.mark_combat_dirty(guild_id_str, combat_id) # Mark combat as dirty


                       # Check if combat ends after removing the participant
                       # Get RuleEngine from kwargs (passed by entity manager cleanup context)
                       rule_engine = kwargs.get('rule_engine', self._rule_engine) # type: Optional["RuleEngine"]
                       if rule_engine and hasattr(rule_engine, 'check_combat_end_conditions'):
                            try:
                                 # Check conditions for the modified combat object
                                 # Pass the potentially modified combat object and the context
                                 combat_finished = await rule_engine.check_combat_end_conditions(combat=combat, context=kwargs)
                                 if combat_finished:
                                      print(f"CombatManager: Combat {combat_id} in guild {guild_id_str} meets end conditions after {entity_type} {entity_id} was removed.")
                                      # Call end_combat directly if it ends here, passing context
                                      await self.end_combat(combat_id, **kwargs) # Pass combat_id and context

                            except Exception as e:
                                 print(f"CombatManager: Error checking combat end after participant removal ({entity_id}) for combat {combat_id} in guild {guild_id_str}: {e}")
                                 import traceback
                                 print(traceback.format_exc())
                       # else: // Warning logged elsewhere


                  else:
                       print(f"CombatManager: Warning: {entity_type} {entity_id} was not found in participant list of combat {combat_id} in guild {guild_id_str} during cleanup.")
              else:
                   print(f"CombatManager: Warning: Combat {combat_id} participants data is not a list for guild {guild_id_str}. Cannot clean up participant {entity_id}.")


         # else: print(f"CombatManager: {entity_type} {entity_id} is not in any active combat in guild {guild_id_str}.") # Too noisy


    # TODO: Implement remove_participant_from_combat(combat_id, entity_id, entity_type, context) method
    # This is a more specific version of clean_up_for_entity that takes combat_id directly.
    # Might be useful for other managers or internal combat logic.
    # async def remove_participant_from_combat(self, combat_id: str, entity_id: str, entity_type: str, **kwargs: Any) -> None:
    #      """Удаляет конкретного участника из конкретного боя."""
    #      # Similar logic to clean_up_for_entity but uses provided combat_id
    #      # Get guild_id from kwargs
    #      guild_id = kwargs.get('guild_id')
    #      if guild_id is None: ... error ...
    #      guild_id_str = str(guild_id)
    #      # Get combat using guild_id and combat_id
    #      combat = self.get_combat(guild_id_str, combat_id)
    #      if not combat: ... warning ...
    #      # Remove participant from combat.participants list
    #      # Check if combat ends after removal
    #      # Mark combat dirty
    #      pass


# Конец класса CombatManager

print("DEBUG: combat_manager.py module loaded.")
