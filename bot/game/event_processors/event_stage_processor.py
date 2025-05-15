# bot/game/event_processors/event_stage_processor.py

from __future__ import annotations
import json
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Callable, Awaitable

from bot.game.models.event import Event, EventStage

# Импорт менеджеров для аннотаций и использования
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



from bot.game.event_processors.event_action_processor import EventActionProcessor


from bot.game.rules.rule_engine import RuleEngine


# Процессоры
from .on_enter_action_executor import OnEnterActionExecutor
from .stage_description_generator import StageDescriptionGenerator

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
        rule_engine: Optional['RuleEngine'] = None,
        character_manager: Optional[CharacterManager] = None,
        loc_manager: Optional[LocationManager] = None,
        npc_manager: Optional[NpcManager] = None,
        combat_manager: Optional[CombatManager] = None,
        item_manager: Optional[ItemManager] = None,
        time_manager: Optional[TimeManager] = None,
        status_manager: Optional[StatusManager] = None,
        party_manager: Optional[PartyManager] = None,
        economy_manager: Optional['EconomyManager'] = None,
        dialogue_manager: Optional['DialogueManager'] = None,
        crafting_manager: Optional['CraftingManager'] = None,
        event_action_processor: Optional['EventActionProcessor'] = None,
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
        self._event_action_processor = event_action_processor

    async def advance_stage(
        self,
        event: Event,
        target_stage_id: str,
        send_message_callback: SendToChannelCallback,
        event_manager: Optional['EventManager'] = None,
        rule_engine: Optional['RuleEngine'] = None,
        character_manager: Optional[CharacterManager] = None,
        loc_manager: Optional[LocationManager] = None,
        npc_manager: Optional[NpcManager] = None,
        combat_manager: Optional[CombatManager] = None,
        item_manager: Optional[ItemManager] = None,
        time_manager: Optional[TimeManager] = None,
        status_manager: Optional[StatusManager] = None,
        party_manager: Optional[PartyManager] = None,
        economy_manager: Optional['EconomyManager'] = None,
        dialogue_manager: Optional['DialogueManager'] = None,
        crafting_manager: Optional['CraftingManager'] = None,
        on_enter_action_executor: Optional[OnEnterActionExecutor] = None,
        stage_description_generator: Optional[StageDescriptionGenerator] = None,
        event_action_processor: Optional['EventActionProcessor'] = None,
        transition_context: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        """
        Обрабатывает переход события на новую стадию.
        """
        # Подготовка контекста
        transition_context = transition_context or {}
        rule_engine = rule_engine or self._rule_engine
        character_manager = character_manager or self._character_manager
        loc_manager = loc_manager or self._loc_manager
        npc_manager = npc_manager or self._npc_manager
        combat_manager = combat_manager or self._combat_manager
        item_manager = item_manager or self._item_manager
        time_manager = time_manager or self._time_manager
        status_manager = status_manager or self._status_manager
        party_manager = party_manager or self._party_manager
        economy_manager = economy_manager or self._economy_manager
        dialogue_manager = dialogue_manager or self._dialogue_manager
        crafting_manager = crafting_manager or self._crafting_manager
        on_enter_action_executor = on_enter_action_executor or self._on_enter_action_executor
        stage_description_generator = stage_description_generator or self._stage_description_generator
        event_action_processor = event_action_processor or self._event_action_processor

        print(f"EventStageProcessor: Advancing event {event.id} from stage '{event.current_stage_id}' "
              f"to '{target_stage_id}'. Trigger: {transition_context.get('trigger', 'Unknown')}")

        # 1. OnExit для старой стадии
        old_stage_id = event.current_stage_id
        old_data = event.stages_data.get(old_stage_id, {})
        on_exit = old_data.get('on_exit_actions', []) or []
        if on_exit and rule_engine:
            print(f"Executing {len(on_exit)} OnExit actions for stage '{old_stage_id}'")
            try:
                await on_enter_action_executor.execute_actions(event, on_exit, **kwargs)
            except Exception as e:
                print(f"Error executing OnExit actions: {e}")
                print(traceback.format_exc())

        # Обновляем стадию
        event.current_stage_id = target_stage_id
        if event_manager and hasattr(event_manager, '_dirty_events'):
            event_manager._dirty_events.add(event.id)

        # 2. OnEnter для новой стадии
        new_data = event.stages_data.get(target_stage_id, {})
        on_enter = new_data.get('on_enter_actions', []) or []
        if on_enter and rule_engine:
            print(f"Executing {len(on_enter)} OnEnter actions for stage '{target_stage_id}'")
            try:
                await on_enter_action_executor.execute_actions(event, on_enter, **kwargs)
            except Exception as e:
                print(f"Error executing OnEnter actions: {e}")
                print(traceback.format_exc())

        # 3. Генерация описания стадии
        if target_stage_id != 'event_end':
            try:
                desc = await stage_description_generator.generate_description(event, target_stage_id, **kwargs)
                if desc:
                    await send_message_callback(desc)
            except Exception as e:
                print(f"Error generating stage description: {e}")
                print(traceback.format_exc())
        else:
            print(f"Event {event.id} reached 'event_end'.")
