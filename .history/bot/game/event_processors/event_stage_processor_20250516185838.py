# bot/game/event_processors/event_stage_processor.py

from __future__ import annotations # Keep this
import json
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Callable, Awaitable, TYPE_CHECKING # Ensure TYPE_CHECKING is imported

from bot.game.models.event import Event, EventStage

# Импорт менеджеров для аннотаций и использования (оставляем прямые импорты, т.к. они используются в isinstance и других местах,
# и предполагаем, что они не создают прямой цикл с этим файлом)
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.combat_manager import CombatManager
from bot.game.managers.item_manager import ItemManager
from bot.game.managers.time_manager import TimeManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.party_manager import PartyManager
from bot.game.managers.economy_manager import EconomyManager
from bot.game.managers.dialogue_manager import DialogueManager
from bot.game.managers.crafting_manager import CraftingManager
from bot.game.managers.event_manager import EventManager

# Импopт пpoцессоров
from .on_enter_action_executor import OnEnterActionExecutor
from .stage_description_generator import StageDescriptionGenerator

# --- BREAKING CIRCULAR IMPORTS ---
# EventActionProcessor вызывает EventStageProcessor, и EventStageProcessor вызывает EventActionProcessor.
# Чтобы разорвать этот цикл при выполнении (runtime), мы убираем ПРЯМОЙ импорт EventActionProcessor.
# Оставляем импорт ТОЛЬКО внутри TYPE_CHECKING для статического анализа и аннотаций типов.
# Аннотации типов, использующие EventActionProcessor, должны быть строковыми литералами ("EventActionProcessor").
if TYPE_CHECKING:
    from bot.game.event_processors.event_action_processor import EventActionProcessor

# --- Imports below this point should be checked for potential *new* cycles ---
# Assuming RuleEngine does not directly import EventStageProcessor or ActionProcessor
from bot.game.rules.rule_engine import RuleEngine


# Тип callback для отправки сообщения в канал
SendToChannelCallback = Callable[[str], Awaitable[Any]]


class EventStageProcessor:
    """
    Процессор, отвечающий за управление стадиями событий.
    Обрабатывает переходы между стадиями (триггеры OnEnter/OnExit, выполнение действий стадии,
    генерация описания стадии).
    """
    def __init__(
        self,
        on_enter_action_executor: OnEnterActionExecutor,
        stage_description_generator: StageDescriptionGenerator,
        rule_engine: Optional['RuleEngine'] = None, # Already using string literal, good.
        character_manager: Optional[CharacterManager] = None, # Direct import allowed if no cycle
        loc_manager: Optional[LocationManager] = None, # Direct import allowed if no cycle
        npc_manager: Optional[NpcManager] = None, # Direct import allowed if no cycle
        combat_manager: Optional[CombatManager] = None, # Direct import allowed if no cycle
        item_manager: Optional[ItemManager] = None, # Direct import allowed if no cycle
        time_manager: Optional[TimeManager] = None, # Direct import allowed if no cycle
        status_manager: Optional[StatusManager] = None, # Direct import allowed if no cycle
        party_manager: Optional[PartyManager] = None, # Direct import allowed if no cycle
        economy_manager: Optional['EconomyManager'] = None, # Already using string literal, good.
        dialogue_manager: Optional['DialogueManager'] = None, # Already using string literal, good.
        crafting_manager: Optional['CraftingManager'] = None, # Already using string literal, good.
        event_action_processor: Optional['EventActionProcessor'] = None, # Already using string literal, and needs to be!
    ):
        # Сохраняем зависимости
        self._on_enter_action_executor = on_enter_action_executor
        self._stage_description_generator = stage_description_generator
        self._rule_engine = rule_engine
        self._character_manager = character_manager
        self._loc_manager = loc_manager
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._item_manager = item_manager
        self._time_manager = time_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._economy_manager = economy_manager
        self._dialogue_manager = dialogue_manager
        self._crafting_manager = crafting_manager
        self._event_action_processor = event_action_processor # Storing the instance is fine.

    async def advance_stage(
        self,
        event: Event,
        target_stage_id: str,
        send_message_callback: SendToChannelCallback,
        event_manager: Optional['EventManager'] = None, # Using string literal
        rule_engine: Optional['RuleEngine'] = None, # Using string literal
        character_manager: Optional[CharacterManager] = None, # Direct import allowed if no cycle
        loc_manager: Optional[LocationManager] = None, # Direct import allowed if no cycle
        npc_manager: Optional[NpcManager] = None, # Direct import allowed if no cycle
        combat_manager: Optional[CombatManager] = None, # Direct import allowed if no cycle
        item_manager: Optional[ItemManager] = None, # Direct import allowed if no cycle
        time_manager: Optional[TimeManager] = None, # Direct import allowed if no cycle
        status_manager: Optional[StatusManager] = None, # Direct import allowed if no cycle
        party_manager: Optional[PartyManager] = None, # Direct import allowed if no cycle
        economy_manager: Optional['EconomyManager'] = None, # Using string literal
        dialogue_manager: Optional['DialogueManager'] = None, # Using string literal
        crafting_manager: Optional['CraftingManager'] = None, # Using string literal
        on_enter_action_executor: Optional[OnEnterActionExecutor] = None, # Direct import allowed if no cycle
        stage_description_generator: Optional[StageDescriptionGenerator] = None, # Direct import allowed if no cycle
        event_action_processor: Optional['EventActionProcessor'] = None, # Needs to be string literal!
        transition_context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        """
        Обрабатывает переход события на новую стадию.
        """
        # Подготовка контекста
        transition_context = transition_context or {}
        # Использование локальных переменных, если переданы, иначе - инжектированные
        rule_engine_inst = rule_engine or self._rule_engine
        character_manager_inst = character_manager or self._character_manager
        loc_manager_inst = loc_manager or self._loc_manager
        npc_manager_inst = npc_manager or self._npc_manager
        combat_manager_inst = combat_manager or self._combat_manager
        item_manager_inst = item_manager or self._item_manager
        time_manager_inst = time_manager or self._time_manager
        status_manager_inst = status_manager or self._status_manager
        party_manager_inst = party_manager or self._party_manager
        economy_manager_inst = economy_manager or self._economy_manager
        dialogue_manager_inst = dialogue_manager or self._dialogue_manager
        crafting_manager_inst = crafting_manager or self._crafting_manager
        on_enter_action_executor_inst = on_enter_action_executor or self._on_enter_action_executor
        stage_description_generator_inst = stage_description_generator or self._stage_description_generator
        event_action_processor_inst = event_action_processor or self._event_action_processor # Using the instance here is fine

        # Создаем словарь менеджеров для передачи в execute_actions/generate_description
        managers_context = {
            'rule_engine': rule_engine_inst,
            'character_manager': character_manager_inst,
            'loc_manager': loc_manager_inst,
            'location_manager': loc_manager_inst, # Alias for consistency
            'npc_manager': npc_manager_inst,
            'combat_manager': combat_manager_inst,
            'item_manager': item_manager_inst,
            'time_manager': time_manager_inst,
            'status_manager': status_manager_inst,
            'party_manager': party_manager_inst,
            'economy_manager': economy_manager_inst,
            'dialogue_manager': dialogue_manager_inst,
            'crafting_manager': crafting_manager_inst,
            'event_stage_processor': self, # Pass self if needed
            'event_action_processor': event_action_processor_inst, # Pass the instance
            'send_message_callback': send_message_callback, # Pass callback directly
            'send_callback_factory': kwargs.get('send_callback_factory'), # Pass factory if available
            'guild_id': event.guild_id, # Common required context
            'event': event, # Pass event object
            **transition_context, # Add transition specific context
            **kwargs, # Include any other kwargs
        }


        print(f"EventStageProcessor: Advancing event {event.id} from stage '{event.current_stage_id}' "
              f"to '{target_stage_id}'. Trigger: {transition_context.get('trigger', 'Unknown')}")

        # 1. OnExit для старой стадии
        old_stage_id = event.current_stage_id
        old_data = event.stages_data.get(old_stage_id, {})
        on_exit = old_data.get('on_exit_actions', []) or []
        # Проверка на наличие исполнителя OnEnter/OnExit
        if on_enter_action_executor_inst and on_exit and rule_engine_inst:
            print(f"Executing {len(on_exit)} OnExit actions for stage '{old_stage_id}'")
            try:
                # Передаем расширенный контекст
                await on_enter_action_executor_inst.execute_actions(event, on_exit, context=managers_context) # Pass context
            except Exception as e:
                print(f"Error executing OnExit actions for event {event.id}, stage '{old_stage_id}': {e}")
                print(traceback.format_exc())

        # Обновляем стадию
        event.current_stage_id = target_stage_id
        # Помечаем событие как "грязное" для сохранения
        if event_manager and hasattr(event_manager, '_dirty_events'): # Используем переданный event_manager, если есть, иначе инжектированный (self._event_manager)
             event_manager_inst_for_dirty = event_manager or getattr(self, '_event_manager', None)
             if event_manager_inst_for_dirty and hasattr(event_manager_inst_for_dirty, '_dirty_events'):
                event_manager_inst_for_dirty._dirty_events.add(event.id)
             else:
                print(f"Warning: Could not mark event {event.id} dirty. EventManager not available.")


        # 2. OnEnter для новой стадии
        new_data = event.stages_data.get(target_stage_id, {})
        on_enter = new_data.get('on_enter_actions', []) or []
        # Проверка на наличие исполнителя OnEnter/OnExit
        if on_enter_action_executor_inst and on_enter and rule_engine_inst:
            print(f"Executing {len(on_enter)} OnEnter actions for stage '{target_stage_id}'")
            try:
                # Передаем расширенный контекст
                await on_enter_action_executor_inst.execute_actions(event, on_enter, context=managers_context) # Pass context
            except Exception as e:
                print(f"Error executing OnEnter actions for event {event.id}, stage '{target_stage_id}': {e}")
                print(traceback.format_exc())


        # 3. Генерация описания стадии (если это не конец события)
        if stage_description_generator_inst and target_stage_id != 'event_end':
            try:
                # Передаем расширенный контекст
                desc = await stage_description_generator_inst.generate_description(event, target_stage_id, context=managers_context) # Pass context
                if desc:
                    await send_message_callback(desc)
            except Exception as e:
                print(f"Error generating stage description for event {event.id}, stage '{target_stage_id}': {e}")
                print(traceback.format_exc())
        elif target_stage_id == 'event_end':
            print(f"Event {event.id} reached 'event_end'.")
            # Возможно, здесь нужно вызвать event_manager для завершения/удаления события