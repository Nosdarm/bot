# bot/game/rules/rule_engine.py (ИСПРАВЛЕННАЯ ВЕРСИЯ ДЛЯ КРУГОВОГО ИМПОРТА С LOCATION_MANAGER)

from __future__ import annotations
import json
import traceback
import asyncio

from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    # Импорты для статического анализа, особенно для предотвращения циклов
    from bot.game.models.character import Character
    from bot.game.models.npc import NPC
    from bot.game.models.party import Party
    from bot.game.models.combat import Combat
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.npc_manager import NpcManager
    # --- ИСПРАВЛЕНИЕ: Переносим импорт LocationManager в TYPE_CHECKING ---
    from bot.game.managers.location_manager import LocationManager
    # CharacterManager, ItemManager, PartyManager тоже используются через контекст/kwargs.
    # Можно перенести их сюда и использовать строковые литералы в аннотациях ниже
    # если они вызывают циклические импорты с этим файлом. Пока оставляем.
    from bot.game.managers.character_manager import CharacterManager # Оставлен для примера
    from bot.game.managers.item_manager import ItemManager # Оставлен для примера
    from bot.game.managers.party_manager import PartyManager # Оставлен для примера
    # Импорты процессоров, если они используются и создают циклы (как EventStageProcessor)
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.event_processors.event_action_processor import EventActionProcessor # На всякий случай


# Импорты менеджеров, которые могут использоваться напрямую (если не создают циклов с RE)
# Из вашего кода кажется, что эти используются через контекст в check_conditions и move_entity
# но прямые импорты на верхнем уровне были оставлены.
# Чтобы избежать путаницы, я оставляю здесь импорты, как в вашем коде (кроме LocationManager),
# но для более чистого дизайна они тоже могли бы быть только в TYPE_CHECKING.
from bot.game.managers.character_manager import CharacterManager # Возможно, тут цикл
from bot.game.managers.item_manager import ItemManager       # Возможно, тут цикл
from bot.game.managers.party_manager import PartyManager       # Возможно, тут цикл


class RuleEngine:
    # ... (весь остальной код класса RuleEngine, как в вашем предоставленном коде) ...
    """
    Система правил для вычисления результатов действий, проверок условий,
    расчётов (урон, длительность, проверки) и AI-логики.
    Работает с данными мира, полученными из менеджеров через контекст.
    """
    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        print("Initializing RuleEngine...")
        self._settings = settings or {}
        self._rules_data: Dict[str, Any] = {}
        print("RuleEngine initialized.")

    # calculate_action_duration method
    async def calculate_action_duration(
        self,
        action_type: str,
        action_context: Dict[str, Any],
        character: Optional[Character] = None,
        npc: Optional[NPC] = None,
        party: Optional[Party] = None,
        **context,
    ) -> float:
        """
        Рассчитывает длительность действия в игровых минутах.
        Менеджеры доступны через context.
        """
        # Аннотация Optional[LocationManager] требует импорта в TYPE_CHECKING
        # runtime использование (получение из context) не требует импорта здесь, если не вызываются методы lm
        # Если вызываются методы lm, потребуется ЛОКАЛЬНЫЙ импорт
        lm: Optional[LocationManager] = context.get('location_manager') # Аннотация с TYPE_CHECKING

        # ... (ваша логика метода calculate_action_duration) ...
        # Пример для move, где LocationManager используется, но не вызывается его метод:
        if action_type == 'move':
             # ... ваш код ...
             pass # Остальное тело метода


        # ... (остальная часть calculate_action_duration) ...
        if action_type == 'combat_attack':
            return float(self._rules_data.get('base_attack_duration', 1.0))

        # Other actions
        if action_type == 'rest': return float(action_context.get('duration', 10.0))
        if action_type == 'search': return float(self._rules_data.get('base_search_duration', 5.0))
        if action_type == 'craft': return float(self._rules_data.get('base_craft_duration', 30.0))
        if action_type == 'use_item': return float(self._rules_data.get('base_use_item_duration', 1.0))
        if action_type == 'ai_dialogue': return float(self._rules_data.get('base_dialogue_step_duration', 0.1))
        if action_type == 'idle': return float(self._rules_data.get('default_idle_duration', 60.0))

        print(f"RuleEngine: Warning: Unknown action type '{action_type}'. Returning 0.0.")
        return 0.0


    # check_conditions method
    async def check_conditions(self, conditions: List[Dict[str, Any]], context: Dict[str, Any]) -> bool:
        # Аннотации менеджеров из context используют TYPE_CHECKING импорты
        # Методы этих менеджеров вызываются, но т.к. они получаются из context,
        # прямой импорт на верхнем уровне в RE НЕ НУЖЕН для использования ИНСТАНСОВ.
        cm: Optional[CharacterManager] = context.get('character_manager')
        nm: Optional[NpcManager] = context.get('npc_manager')
        lm_ctx: Optional[LocationManager] = context.get('location_manager') # Annotation with TYPE_CHECKING
        # ... остальные менеджеры ...
        im: Optional[ItemManager] = context.get('item_manager')
        pm: Optional[PartyManager] = context.get('party_manager')
        sm: Optional[StatusManager] = context.get('status_manager')
        combat: Optional[CombatManager] = context.get('combat_manager')

        if not conditions: return True

        for cond in conditions:
            ctype = cond.get('type')
            data = cond.get('data', {})
            met = False

            # Ваша логика проверок условий. Вызываете методы менеджеров через переменные из контекста.
            # Example:
            if ctype == 'has_item' and im:
                 # ... (ваш код проверки has_item) ...
                 pass

            elif ctype == 'in_location':
                 # Здесь ваш оригинальный код использовал переменную lm для аннотации,
                 # но не вызывал его методы. Это OK. Просто проверял location_id сущности.
                 # Этот if ctype == 'in_location' может использовать менеджеры из context
                 # (cm или nm) чтобы найти сущность и проверить ее location_id.
                 eid = data.get('entity_id') or getattr(context.get('character') or context.get('npc'), 'id', None)
                 loc = data.get('location_id')
                 if eid and loc:
                     # Need cm or nm to get the entity object
                     entity_obj = None
                     if context.get('character_manager') and data.get('entity_type') == 'Character':
                         entity_obj = context.get('character_manager').get_character(context.get('guild_id'), eid) # Need guild_id
                     elif context.get('npc_manager') and data.get('entity_type') == 'NPC':
                          entity_obj = context.get('npc_manager').get_npc(context.get('guild_id'), eid) # Need guild_id

                     if entity_obj and getattr(entity_obj, 'location_id', None) == loc:
                         met = True
                 # Original code didn't actually use lm_ctx instance methods here, just the var for annotation
                 # This check logic might need the LM instance if comparing to dynamic location properties

            # ... (остальная часть check_conditions) ...
            elif ctype == 'has_status' and sm: # Use sm
                 pass # ... Ваш код

            elif ctype == 'stat_check': # Use methods from RuleEngine itself (self) or other managers from context
                 pass # ... Ваш код perform_stat_check logic

            elif ctype == 'is_in_combat' and combat: # Use combat
                 pass # ... Ваш код

            elif ctype == 'is_leader_of_party' and pm: # Use pm
                 pass # ... Ваш код

            else:
                print(f"RuleEngine: Warning: Unknown condition '{ctype}'.")
                return False # Unknown condition means it's not met

            if not met:
                return False

        return True


    # choose_combat_action_for_npc method
    async def choose_combat_action_for_npc(self, npc: NPC, combat: Combat, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
         # ... (ваш код choose_combat_action_for_npc) ...
         pass # Placeholder

    # can_rest method
    async def can_rest(self, npc: NPC, context: Dict[str, Any]) -> bool:
         # ... (ваш код can_rest) ...
         pass # Placeholder

    # perform_stat_check method (Assumed helper for check_conditions)
    async def perform_stat_check(self, entity: Any, stat: str, threshold: Any, operator: str, context: Dict[str, Any]) -> bool:
        # ... (ваш код perform_stat_check) ...
        pass # Placeholder

    # execute_effects method (Assumed helper for triggers)
    async def execute_effects(self, guild_id: str, effects: List[Dict[str, Any]], context: Dict[str, Any]) -> None:
        # ... (ваш код execute_effects) ...
        pass # Placeholder

    # execute_triggers method (Assumed method called by managers/processors)
    async def execute_triggers(self, guild_id: str, triggers: List[Dict[str, Any]], context: Dict[str, Any]) -> None:
        # Calls self.check_conditions and self.execute_effects
        # ... (ваш код execute_triggers) ...
        pass # Placeholder

    # handle_stage method (Assumed helper called by EventStageProcessor)
    def handle_stage(self, stage: Any, **context) -> None:
        # --- ИСПРАВЛЕНИЕ: Локальный импорт EventStageProcessor ---
        # У вас в оригинальном коде здесь был закомментирован локальный импорт EventStageProcessor.
        # Если RuleEngine вызывает EventStageProcessor (или он нужен здесь),
        # а EventStageProcessor вызывает RuleEngine, то здесь нужен локальный импорт.
        try:
             # Импорт внутри функции
             from bot.game.event_processors.event_stage_processor import EventStageProcessor
             proc = EventStageProcessor() # Создание экземпляра
             proc.process(stage, **context) # Вызов метода (assuming process takes context)
        except ImportError:
             print("RuleEngine: Error: Could not import EventStageProcessor locally in handle_stage. Circular import still not fully resolved or file missing.")
             # Decide how to handle failure (log, raise, skip stage).
        except Exception as e:
             print(f"RuleEngine: Error processing stage {stage}: {e}")
             traceback.print_exc()


    # choose_peaceful_action_for_npc method
    async def choose_peaceful_action_for_npc(
        self,
        npc: NPC,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        AI-логика спокойного поведения NPC.
        """
        # --- ИСПРАВЛЕНИЕ: Локальный импорт LocationManager ---
        # Этот импорт будет выполнен только при вызове данной асинхронной функции,
        # потому что здесь вызывается метод LocationManager.get_connected_locations().
        try:
            # Импорт внутри функции, где реально нужен класс LocationManager для вызова его методов
            from bot.game.managers.location_manager import LocationManager
        except ImportError:
            print("RuleEngine: Error: Could not import LocationManager locally in choose_peaceful_action_for_npc. Circular import not fully resolved or file missing.")
            return None # Cannot proceed without LocationManager


        lm_ctx: Optional[LocationManager] = context.get('location_manager') # Get instance from context. Annotation with TYPE_CHECKING
        # Access other managers from context. Use annotations with TYPE_CHECKING.
        cm_ctx: Optional[CharacterManager] = context.get('character_manager')
        nm_ctx: Optional[NpcManager] = context.get('npc_manager')
        dm_ctx = context.get('dialogue_manager') # Annotation Optional["DialogueManager"] with string literal might be needed

        # ... (ваша логика choose_peaceful_action_for_npc) ...

        # Пример использования lm_ctx (если оно получено из контекста) и вызова его метода
        # Это требует, чтобы lm_ctx был экземпляром LocationManager, а не None
        if curr_loc and lm_ctx:
            try:
                # Need to pass guild_id to get_connected_locations method. Get guild_id from npc or context.
                guild_id_str = getattr(npc, 'guild_id', context.get('guild_id'))
                if guild_id_str:
                     exits = lm_ctx.get_connected_locations(str(guild_id_str), curr_loc) # <-- Вызов метода LocationManager
                     if exits:
                         import random
                         # Assuming exits is a dict like {exit_name: target_location_id}
                         if isinstance(exits, dict) and exits:
                            _, dest = random.choice(list(exits.items()))
                            return {'type': 'move', 'target_location_id': dest}
                         elif isinstance(exits, list) and exits:
                            dest = random.choice(exits)
                            return {'type': 'move', 'target_location_id': dest}


            except Exception as e:
                 print(f"RuleEngine: Error getting connected locations for NPC {npc.id} in location {curr_loc}: {e}")
                 traceback.print_exc()
                 return {'type': 'idle', 'total_duration': None} # Fallback on error


        return {'type': 'idle', 'total_duration': None} # Fallback if no action found


# End of RuleEngine class (or other classes in this file)