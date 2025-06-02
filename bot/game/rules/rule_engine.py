# bot/game/rules/rule_engine.py

from __future__ import annotations
import json  # Может понадобиться для работы с данными правил из JSON
import random
import re
import traceback  # Для вывода трассировки ошибок
import asyncio  # Если методы RuleEngine будут асинхронными

# Импорт базовых типов и TYPE_CHECKING
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING, Union # Added Union

from bot.game.models.check_models import CheckOutcome, DetailedCheckResult

# --- Imports used in TYPE_CHECKING for type hints ---
# Эти модули импортируются ТОЛЬКО для статического анализа (Pylance/Mypy).
# Это разрывает циклы импорта при runtime.
if TYPE_CHECKING:
    # Модели, которые вы упоминаете в аннотациях (импорт в TYPE_CHECKING тоже для безопасности,
    # если сами файлы моделей импортируют что-то, что вызывает цикл)
    # from bot.game.models.character import Character # Character модель импортируется напрямую, т.к. используется в runtime (check isinstance)
    from bot.game.models.npc import NPC # Возможно, нужен прямой импорт для isinstance
    from bot.game.models.party import Party # Возможно, нужен прямой импорт для isinstance
    from bot.game.models.combat import Combat # Возможно, нужен прямой импорт для isinstance
    from bot.game.models.ability import Ability # For Ability logic
    from bot.game.models.item import Item # For Item type hinting
    # Spell model is already imported below

    # Менеджеры и процессоры, которые могут создавать циклические импорты
    from bot.game.managers.location_manager import LocationManager # <-- Moved here to break cycle
    from bot.game.managers.character_manager import CharacterManager # <-- Moved here for consistency/safety
    from bot.game.managers.item_manager import ItemManager # <-- Moved here for consistency/safety
    from bot.game.managers.party_manager import PartyManager # <-- Moved here for consistency/safety
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.services.openai_service import OpenAIService # Если используется
    from bot.game.models.spell import Spell # For spell logic

    # Процессоры, которые могут создавать циклические импорты
    from bot.game.event_processors.event_stage_processor import EventStageProcessor # <-- Added, needed for handle_stage fix
    # from bot.game.event_processors.event_action_processor import EventActionProcessor # Если используется
    from bot.game.models.check_models import DetailedCheckResult as DetailedCheckResultHint # For type hinting in methods if needed


# --- Imports needed at Runtime ---
# Эти модули необходимы для выполнения кода (например, для создания экземпляров, вызовов статических методов, проверок isinstance)
# Если модуль импортируется здесь, убедитесь, что он НЕ ИМПОРТИРУЕТ RuleEngine напрямую.
from bot.game.models.character import Character # Прямой импорт модели, если она нужна для isinstance или других runtime целей
# from bot.game.rules.dice_roller import roll_dice as external_roll_dice # Example if using external roller directly
# from bot.game.models.spell import Spell # Not needed for runtime if only used in type hints within methods

print("DEBUG: rule_engine.py module loaded.")


class RuleEngine:
    """
    Система правил для вычисления результатов действий, проверок условий,
    расчётов (урон, длительность, проверки) и AI-логики.
    Работает с данными мира, полученными из менеджеров через контекст.
    """
    # required_args_for_load = [] # Если load_rules_data требует аргументов, добавьте сюда
    # required_args_for_save = [] # Если save_state требует аргументов, добавьте сюда

    def __init__(self,
                 settings: Optional[Dict[str, Any]] = None,
                 character_manager: Optional["CharacterManager"] = None,
                 npc_manager: Optional["NpcManager"] = None,
                 status_manager: Optional["StatusManager"] = None,
                 item_manager: Optional["ItemManager"] = None,
                 location_manager: Optional["LocationManager"] = None,
                 party_manager: Optional["PartyManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                 dialogue_manager: Optional["DialogueManager"] = None,
                 time_manager: Optional["TimeManager"] = None, # Added TimeManager
                 rules_data: Optional[Dict[str, Any]] = None # Added rules_data
                 ):
        print("Initializing RuleEngine...")
        self._settings = settings or {}
        
        # Store manager instances
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._status_manager = status_manager
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._party_manager = party_manager
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager
        self._time_manager = time_manager # Store TimeManager
        
        # Load rules_data if provided, otherwise load from settings or keep empty
        if rules_data is not None:
            self._rules_data = rules_data
        else:
            self._rules_data = self._settings.get('rules_data', {}) # Fallback to settings
        
        print("RuleEngine initialized.")

    async def load_rules_data(self) -> None:
        """
        Загружает правила из настроек или других источников.
        """
        print("RuleEngine: Loading rules data...")
        # Предполагаем, что правила не зависят от guild_id и загружаются глобально
        self._rules_data = self._settings.get('rules_data', {})
        print(f"RuleEngine: Loaded {len(self._rules_data)} rules entries.")

    # Добавляем методы load_state и save_state для совместимости с PersistenceManager
    # Если load_rules_data/save_rules_data вызываются из PersistenceManager
    async def load_state(self, **kwargs: Any) -> None: # Аннотация **kwargs
         """Загружает правила (данные состояния RuleEngine)."""
         # Если правила зависят от guild_id, здесь нужно обработать guild_id из kwargs
         # Например: guild_id = kwargs.get('guild_id')
         # и загружать self._rules_data на гильдию: self._rules_data[guild_id] = ...
         await self.load_rules_data() # Вызываем основную логику загрузки

    async def save_state(self, **kwargs: Any) -> None: # Аннотация **kwargs
         """Сохраняет правила (данные состояния RuleEngine), если они изменяются в runtime."""
         # Если RuleEngine изменяет свое состояние в runtime (кроме _rules_data, которое загружается при старте),
         # и это состояние нужно сохранять, добавьте сюда логику сохранения в DB через db_adapter из kwargs.
         # Если _rules_data никогда не изменяется после загрузки, или изменяется, но не сохраняется в DB,
         # этот метод может быть пустым.
         print("RuleEngine: Save state method called. (Placeholder - does RuleEngine have state to save?)")
         pass # Placeholder

    # Добавляем метод rebuild_runtime_caches
    def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None: # Аннотация **kwargs
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния. (Если применимо для правил)"""
        print(f"RuleEngine: Rebuilding runtime caches for guild {guild_id}. (Placeholder)")
        pass # Placeholder


    async def calculate_action_duration(
        self,
        action_type: str,
        action_context: Dict[str, Any],
        character: Optional["Character"] = None, # Используем строковый литерал!
        npc: Optional["NPC"] = None, # Используем строковый литерал!
        party: Optional["Party"] = None, # Используем строковый литерал!
        # Добавляем аннотацию для **context
        **context: Dict[str, Any],
    ) -> float:
        """
        Рассчитывает длительность действия в игровых минутах.
        Менеджеры доступны через context.
        """
        # Получение менеджера из контекста, используем строковый литерал в аннотации переменной
        lm: Optional["LocationManager"] = context.get('location_manager')

        # Убеждаемся, что 'curr' определена в этом блоке, как и 'target'
        curr = getattr(character or npc, 'location_id', None) # Берем location_id у character или npc, если они есть
        target = action_context.get('target_location_id')

        # Пример: перемещение
        if action_type == 'move':
            if curr is not None and target is not None and lm: # Проверяем, что все необходимые данные и менеджер есть
                base = float(self._rules_data.get('base_move_duration_per_location', 5.0))
                # Можно добавить более сложную логику расчета дистанции/длительности между локациями, используя lm
                # dist = lm.calculate_distance(curr, target) # Пример
                # return base * dist
                return base # Возвращаем базовую длительность пока без расчета дистанции
            # Если перемещение невозможно (нет текущей/целевой локации, нет менеджера), длительность 0?
            # Или лучше поднять ошибку или вернуть -1, чтобы ActionProcessor понял?
            # Возвращаем 0.0, как и в оригинале
            print(f"RuleEngine: Warning: Cannot calculate duration for move from {curr} to {target} (lm: {lm is not None}). Returning 0.0.")
            return 0.0 # Убеждаемся, что возвращаем float


        # Пример: атака
        if action_type == 'combat_attack':
            # Используем контекст для более точного расчета, например, скорость атаки персонажа
            # char_mgr: Optional["CharacterManager"] = context.get('character_manager')
            # combat_mgr: Optional["CombatManager"] = context.get('combat_manager')
            # if char_mgr and combat_mgr:
            #     attacker = context.get('character') or context.get('npc') # Получаем атакующую сущность из контекста
            #     if attacker:
            #          attack_speed = getattr(attacker, 'attack_speed', 1.0) # Пример: скорость атаки из статов
            #          base_duration = float(self._rules_data.get('base_attack_duration', 1.0))
            #          return base_duration / attack_speed
            return float(self._rules_data.get('base_attack_duration', 1.0)) # Возвращаем базовую, если нет менеджеров/данных

        # Другие действия (возвращают базовые значения из правил или defaults)
        # Используем .get() с fallback на action_context или default из кода
        if action_type == 'rest':
            # action_context может содержать запрошенную игроком длительность отдыха
            return float(action_context.get('duration', self._rules_data.get('default_rest_duration', 10.0)))
        if action_type == 'search':
            return float(self._rules_data.get('base_search_duration', 5.0))
        if action_type == 'craft':
             # Возможно, здесь нужно брать длительность из рецепта, который можно получить через ItemManager/CraftingManager из контекста
            return float(self._rules_data.get('base_craft_duration', 30.0))
        if action_type == 'use_item':
             # Возможно, длительность зависит от типа предмета, который можно получить через ItemManager
            return float(self._rules_data.get('base_use_item_duration', 1.0))
        if action_type == 'ai_dialogue':
            return float(self._rules_data.get('base_dialogue_step_duration', 0.1))
        if action_type == 'idle':
             # Длительность idle обычно определяется AI или внешней системой, здесь можно вернуть 0 или дефолт
            return float(self._rules_data.get('default_idle_duration', 60.0))


        print(f"RuleEngine: Warning: Unknown action type '{action_type}' for duration calculation. Returning 0.0.")
        return 0.0 # Убеждаемся, что возвращаем float


    async def check_conditions(
        self,
        conditions: List[Dict[str, Any]],
        context: Dict[str, Any] # Контекст со всеми менеджерами и данными
    ) -> bool:
        """
        Проверяет список условий; возвращает True, если все выполнены.
        """
        if not conditions:
            return True
        # Получение менеджеров из context, используем строковые литералы в аннотациях переменных
        cm: Optional["CharacterManager"] = context.get('character_manager') # Ln 247 (approx - from previous screen)
        nm: Optional["NpcManager"] = context.get('npc_manager')
        lm: Optional["LocationManager"] = context.get('location_manager')
        im: Optional["ItemManager"] = context.get('item_manager')
        pm: Optional["PartyManager"] = context.get('party_manager')
        sm: Optional["StatusManager"] = context.get('status_manager')
        combat_mgr: Optional["CombatManager"] = context.get('combat_manager') # Renamed 'combat' to 'combat_mgr' to avoid confusion with Combat model

        for cond in conditions:
            ctype = cond.get('type')
            data = cond.get('data', {})
            met = False # Флаг выполнения условия

            # Получение сущности (character/npc/party) из контекста для удобства
            entity = context.get('character') or context.get('npc') or context.get('party')
            entity_id = data.get('entity_id') or getattr(entity, 'id', None)
            entity_type = data.get('entity_type') or (type(entity).__name__ if entity else None) # Попытка определить тип

            print(f"RuleEngine: Checking condition type '{ctype}' for entity '{entity_id}' ({entity_type}) with data: {data}")

            if ctype == 'has_item' and im:
                if entity_id and entity_type: # Нужны ID и тип сущности
                    met = await im.check_entity_has_item(
                        entity_id, # Передаем ID
                        entity_type, # Передаем тип
                        item_template_id=data.get('item_template_id'),
                        item_id=data.get('item_id'),
                        quantity=data.get('quantity', 1),
                        context=context # Передаем контекст дальше
                    )
            elif ctype == 'in_location' and lm: # Ln 260 (approx - from previous screen)
                loc_id_in_cond = data.get('location_id')
                # Использование curr_loc = getattr(entity, 'location_id', None) в цикле может вызвать проблемы Pylance
                # Лучше получить персонажа/NPC заново или убедиться, что location_id корректно вложена в entity объект в контексте.
                # Проверим location_id на самой сущности, полученной из контекста
                if entity and loc_id_in_cond:
                     # Pylance жаловался на curr_loc, возможно, потому что проверял getattr до проверки entity.
                     # Явная проверка 'if entity' перед использованием getattr может помочь,
                     # но правильнее убедиться, что context передает полные объекты с нужными атрибутами.
                     entity_location_id = getattr(entity, 'location_id', None)
                     if entity_location_id is not None and str(entity_location_id) == str(loc_id_in_cond):
                        met = True
            elif ctype == 'has_status' and sm:
                status_type = data.get('status_type')
                if entity_id and entity_type and status_type:
                    # Предполагаем, что get_status_effects_on_entity_by_type принимает id, type, status_type и context
                    statuses = sm.get_status_effects_on_entity_by_type(entity_id, entity_type, status_type, context=context) # Предполагаем синхронный метод
                    met = bool(statuses) # Условие выполнено, если найдены статусы данного типа
            elif ctype == 'stat_check':
                stat_name = data.get('stat')
                threshold = data.get('threshold')
                operator = data.get('operator', '>=')
                if entity and stat_name and threshold is not None and operator: # Нужна сущность и параметры проверки
                     # Pylance жаловался на curr_loc = getattr(entity, 'location_id', None)
                     # Возможно, эта ошибка накладывалась на проблему со stat_check.
                     # Передача объекта сущности целиком и проверка атрибута внутри метода perform_stat_check более надежна.
                    # Предполагаем, что perform_stat_check существует и принимает сущность, стат, порог, оператор и контекст.
                    if hasattr(self, 'perform_stat_check'): # Проверяем, есть ли такой метод в RuleEngine
                         met = await self.perform_stat_check(entity, stat_name, threshold, operator, context=context)
                    else:
                        print(f"RuleEngine: Warning: 'stat_check' condition used, but 'perform_stat_check' method is not implemented.")
                        # Неизвестное условие или нереализовано
                        # Вернуть False или поднять ошибку? Давайте вернем False.
                        return False # Условие не выполнено, если метод не найден

            elif ctype == 'is_in_combat' and combat_mgr: # Используем переименованный combat_mgr
                if entity_id and entity_type: # Нужны ID и тип сущности
                    # Предполагаем, что get_combat_by_participant_id принимает ID и context
                    combat_instance = combat_mgr.get_combat_by_participant_id(entity_id, context=context) # Предполагаем синхронный метод
                    met = bool(combat_instance) # Условие выполнено, если найдена битва

            elif ctype == 'is_leader_of_party' and pm:
                if entity_id and entity_type == 'Character': # Проверка лидера применима к персонажам
                     # Предполагаем, что get_party_by_member_id принимает ID и context
                     party_instance = pm.get_party_by_member_id(entity_id, context=context) # Предполагаем синхронный метод
                     if party_instance and getattr(party_instance, 'leader_id', None) == entity_id:
                         met = True

            # TODO: Добавить другие типы условий здесь (например, has_status_type, compare_variables, time_of_day)
            # Пример 'compare_variables':
            # elif ctype == 'compare_variables' and context.get('state_variables') is not None: # Предполагаем, что state_variables переданы в контексте
            #     variable_name = data.get('variable_name')
            #     comparison_value = data.get('value')
            #     operator = data.get('operator', '>=')
            #     # Здесь нужно реализовать логику сравнения state_variables[variable_name] с comparison_value по оператору
            #     # используя отдельный метод сравнения, если нужно
            #     current_value = context.get('state_variables', {}).get(variable_name)
            #     if current_value is not None:
            #          met = self._compare_values(current_value, comparison_value, operator) # Предполагаем приватный синхронный хелпер

            else:
                print(f"RuleEngine: Warning: Unknown or unhandled condition type '{ctype}'.")
                # Если встретили неизвестное условие, вся проверка должна провалиться?
                return False # Неизвестное условие -> не выполнено

            if not met:
                print(f"RuleEngine: Condition '{ctype}' not met for entity '{entity_id}' ({entity_type}).")
                return False # Если хотя бы одно условие не выполнено, вся проверка проваливается

        # Если все условия в списке были проверены и все выполнены
        print(f"RuleEngine: All conditions met.")
        return True

    # TODO: Implement _compare_values helper method if needed for 'compare_variables' condition


    # TODO: Implement perform_stat_check method
    async def perform_stat_check(self, entity: Any, stat_name: str, threshold: Any, operator: str = '>=', **context: Any) -> bool: # Аннотация **context
        """
        Выполняет проверку характеристики сущности против порога.
        Возвращает True, если проверка успешна.
        """
        # Получаем значение характеристики из сущности (Character/NPC object)
        entity_stats = getattr(entity, 'stats', {})
        stat_value = entity_stats.get(stat_name)

        if stat_value is None:
            print(f"RuleEngine: Warning: Entity '{getattr(entity, 'id', 'N/A')}' ({type(entity).__name__}) has no stat '{stat_name}'. Stat check fails.")
            return False # Нельзя проверить характеристику, которой нет

        try:
            # Пытаемся привести значение стата и порог к числовому типу для сравнения
            stat_value_numeric = float(stat_value)
            threshold_numeric = float(threshold)

            # Выполняем сравнение на основе оператора
            if operator == '>=':
                return stat_value_numeric >= threshold_numeric
            elif operator == '>':
                return stat_value_numeric > threshold_numeric
            elif operator == '<=':
                return stat_value_numeric <= threshold_numeric
            elif operator == '<':
                return stat_value_numeric < threshold_numeric
            elif operator == '==':
                return stat_value_numeric == threshold_numeric
            elif operator == '!=':
                return stat_value_numeric != threshold_numeric
            else:
                print(f"RuleEngine: Warning: Unknown operator '{operator}' for stat check. Check fails.")
                return False # Неизвестный оператор

        except (ValueError, TypeError):
            print(f"RuleEngine: Warning: Cannot convert stat value '{stat_value}' or threshold '{threshold}' to number for comparison. Stat check fails.")
            traceback.print_exc()
            return False # Не удалось сравнить из-за нечисловых значений
        except Exception as e:
            print(f"RuleEngine: Error during stat check comparison: {e}")
            traceback.print_exc()
            return False


    # TODO: Implement generate_initial_character_stats method
    # Аннотация возвращаемого типа Dict[str, Any] или более специфичная для статов
    def generate_initial_character_stats(self) -> Dict[str, Any]:
        """
        Генерирует начальные характеристики для нового персонажа.
        Использует _rules_data.
        """
        # Здесь можно добавить логику, например, на основе расы/класса, если они есть в данных
        # или просто вернуть дефолтные, как сейчас в CharacterManager
        print("RuleEngine: Generating initial character stats. (Placeholder)")
        return self._rules_data.get('initial_stats_template', {'strength': 10, 'dexterity': 10, 'intelligence': 10})


    async def choose_combat_action_for_npc(
        self,
        npc: "NPC", # Используем строковый литерал!
        combat: "Combat", # Используем строковый литерал!
        # Добавляем аннотацию для **context
        **context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Простая AI-логика боевого действия NPC.
        Менеджеры доступны через context.
        """
        # Получение менеджеров из context, используем строковые литералы
        cm: Optional["CharacterManager"] = context.get('character_manager')
        nm: Optional["NpcManager"] = context.get('npc_manager')
        cman: Optional["CombatManager"] = context.get('combat_manager') # Renamed 'combat' to 'cman' to avoid confusion with Combat model

        # Получаем участников боя через CombatManager из контекста
        if cman:
            # Предполагаем, что get_living_participants принимает combat.id и context
            living = await cman.get_living_participants(combat.id, context=context) # Предполагаем async метод
            # Ищем первую живую цель, которая не является этим NPC
            for p in living:
                if p.entity_id != npc.id:
                    print(f"RuleEngine: NPC {npc.id} choosing attack on {p.entity_id} in combat {combat.id}.")
                    # Возвращаем словарь, описывающий действие
                    return {'type': 'combat_attack', 'target_id': p.entity_id, 'target_type': p.entity_type, 'attack_type': 'basic_attack'} # Пример структуры действия

        # Если не найдена цель или нет менеджера, NPC может бездействовать
        print(f"RuleEngine: NPC {npc.id} not choosing combat action (no targets or combat manager).")
        return {'type': 'idle', 'total_duration': None} # Пример структуры действия "бездействие"


    async def can_rest(
        self,
        # Используем строковый литерал для NPC
        npc: "NPC",
        # Добавляем аннотацию для **context
        **context: Dict[str, Any]
    ) -> bool:
        """Проверяет возможность отдыха NPC. Менеджеры доступны через context."""
        # Получение менеджеров из context, используем строковые литералы
        cman: Optional["CombatManager"] = context.get('combat_manager')
        # lm: Optional["LocationManager"] = context.get('location_manager') # Пример использования LM
        # sm: Optional["StatusManager"] = context.get('status_manager') # Пример использования SM

        # Проверяем, находится ли NPC в бою
        if cman and hasattr(cman, 'get_combat_by_participant_id') and cman.get_combat_by_participant_id(npc.id, context=context): # Предполагаем синхронный метод
            print(f"RuleEngine: NPC {npc.id} cannot rest: is in combat.")
            return False

        # TODO: Дополнительные проверки по локации (безопасная зона?) и статусам (не истощен?)
        # if lm and hasattr(lm, 'is_location_safe'):
        #     loc_id = getattr(npc, 'location_id', None)
        #     if loc_id and not await lm.is_location_safe(loc_id, context=context): # Пример async метода LM
        #          print(f"RuleEngine: NPC {npc.id} cannot rest: location is not safe.")
        #          return False

        # if sm and hasattr(sm, 'has_status_effect'):
        #      # Пример: проверка наличия статуса "Истощение"
        #      if sm.has_status_effect(npc.id, "Exhausted", entity_type="NPC", context=context): # Предполагаем синхронный метод SM
        #           print(f"RuleEngine: NPC {npc.id} cannot rest: is exhausted.")
        #           return False

        print(f"RuleEngine: NPC {npc.id} can rest (based on basic checks).")
        return True # Возвращаем True, если базовые проверки пройдены


    # Refactored handle_stage to receive processor from context
    async def handle_stage(self, stage: Any, **context: Dict[str, Any]) -> None: # Сделаем async для согласованности с другими методами и потенциальными async вызовами внутри
        """
        Обработка стадии (вызов EventStageProcessor для действий стадии).
        RuleEngine не создает EventStageProcessor, а получает его через контекст.
        """
        # Получаем EventStageProcessor из контекста
        # Используем строковый литерал в аннотации переменной
        proc: Optional["EventStageProcessor"] = context.get('event_stage_processor')
        event = context.get('event') # Получаем объект события из контекста
        send_message_callback: Optional[Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]] = context.get('send_message_callback') # Получаем callback

        if proc and event and send_message_callback:
            # Assuming the goal was to advance to a new stage defined in 'stage' data
            # This structure seems to assume 'stage' object passed here contains info about the *next* stage
            # or how to transition. This conflicts slightly with advance_stage signature (target_stage_id).
            # If handle_stage is meant to process triggers/actions *of* the current stage,
            # this seems out of place here.
            # Let's assume handle_stage IS meant to process some kind of stage transition logic
            # and 'stage' somehow provides the target_stage_id.
            # Example: If 'stage' has a 'next_stage_id' attribute or key
            target_stage_id = getattr(stage, 'next_stage_id', None) or stage.get('next_stage_id') # Пример получения ID следующей стадии

            if target_stage_id:
                 print(f"RuleEngine: Handling stage, attempting to advance event {getattr(event, 'id', 'N/A')} to stage '{target_stage_id}'.")
                 # Вызываем advance_stage на полученном инстансе EventStageProcessor
                 await proc.advance_stage(
                     event=event,
                     target_stage_id=str(target_stage_id), # Убедимся, что ID - строка
                     send_message_callback=send_message_callback,
                     # Передаем ВЕСЬ контекст, который RuleEngine получил
                     **context
                 )
                 print("RuleEngine: EventStageProcessor.advance_stage called from handle_stage.")
            else:
                 print(f"RuleEngine: Warning: Cannot handle stage. Could not determine target stage ID from stage data: {stage}")
                 # Возможно, нужно как-то уведомить о проблеме
                 # await send_message_callback("Ошибка обработки стадии.", None) # Если callback доступен

        elif not proc:
             print("RuleEngine: Error: EventStageProcessor not available in context for handle_stage.")
        elif not event:
             print("RuleEngine: Error: Event object not available in context for handle_stage.")
        elif not send_message_callback:
             print("RuleEngine: Warning: send_message_callback not available in context for handle_stage. Cannot send feedback.")
             # Можем вызвать advance_stage без callback, если это приемлемо

    # TODO: Implement _compare_values helper method if needed for 'compare_variables' condition
    def _compare_values(self, value1: Any, value2: Any, operator: str) -> bool:
        """Helper to compare two values based on an operator."""
        try:
            # Попробуем привести к числу для числового сравнения
            num1 = float(value1)
            num2 = float(value2)
            if operator == '>=': return num1 >= num2
            elif operator == '>': return num1 > num2
            elif operator == '<=': return num1 <= num2
            elif operator == '<': return num1 < num2
            elif operator == '==': return num1 == num2
            elif operator == '!=': return num1 != num2
            # Если оператор не числовой (например, 'is', 'is not', 'in', 'not in'), обрабатываем здесь
            # if operator == 'is': return value1 is value2
            # elif operator == 'in': return value1 in value2
            else:
                 print(f"RuleEngine: Warning: Unknown comparison operator '{operator}'. Comparison fails.")
                 return False
        except (ValueError, TypeError):
            # Если приведение к числу не удалось, выполняем строковое сравнение или другие типы сравнения
            if operator == '==' : return str(value1) == str(value2)
            elif operator == '!=': return str(value1) != str(value2)
            # Добавьте другие операторы, которые имеют смысл для нечисловых типов
            # elif operator == 'in': return value1 in value2 # Если value2 - это список или строка

            print(f"RuleEngine: Warning: Cannot perform non-numeric comparison with operator '{operator}'. Comparison fails.")
            return False
        except Exception as e:
            print(f"RuleEngine: Error during comparison: {e}")
            traceback.print_exc()
            return False



    async def choose_peaceful_action_for_npc(
        self,
        npc: "NPC", # Используем строковый литерал!
        # Добавляем аннотацию для **context
        **context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        AI-логика спокойного поведения NPC.
        Менеджеры доступны через context.
        """
        # Получение менеджеров из context, используем строковые литералы
        lm: Optional["LocationManager"] = context.get('location_manager')
        cm: Optional["CharacterManager"] = context.get('character_manager')
        nm: Optional["NpcManager"] = context.get('npc_manager')
        dm: Optional["DialogueManager"] = context.get('dialogue_manager') # DialogueManager from context

        print(f"RuleEngine: Choosing peaceful action for NPC {npc.id}...")

        # Попытка диалога
        curr_loc = getattr(npc, 'location_id', None) # Текущая локация NPC
        # Проверяем, что все менеджеры есть и NPC находится в локации
        if dm and cm and lm and curr_loc:
             # Предполагаем, что get_characters_in_location принимает ID локации и context
            chars_in_loc = cm.get_characters_in_location(curr_loc, context=context) # Предполагаем синхронный метод
            # Ищем персонажа для диалога (исключая самого NPC, если он почему-то в списке персонажей)
            for ch in chars_in_loc:
                # Убедитесь, что ch является объектом с атрибутом id и методом can_start_dialogue у DialogueManager
                if isinstance(ch, Character) and ch.id != npc.id: # Проверка типа Character
                     # Предполагаем, что can_start_dialogue принимает NPC и Character объекты и context
                     if hasattr(dm, 'can_start_dialogue') and dm.can_start_dialogue(npc, ch, context=context): # Предполагаем синхронный метод DM
                        print(f"RuleEngine: NPC {npc.id} choosing dialogue with Character {ch.id}.")
                        # Возвращаем словарь, описывающий действие "диалог с AI"
                        return {'type': 'ai_dialogue', 'target_id': ch.id, 'target_type': 'Character'} # Пример структуры действия

        # Блуждание
        # Проверяем, что LocationManager доступен и у NPC есть локация
        if curr_loc and lm:
             # Предполагаем, что get_connected_locations принимает ID локации
            exits = lm.get_connected_locations(curr_loc) # Предполагаем синхронный метод, возвращает Dict[str, str] или List[str]
            if exits:
                import random # Импортируем random локально, если он нужен только здесь
                # Выбираем случайный выход. exits может быть dict (exit_name: location_id) или list (location_id).
                if isinstance(exits, dict):
                    _, dest_location_id = random.choice(list(exits.items())) # Выбираем случайный item (name, id)
                elif isinstance(exits, list):
                    dest_location_id = random.choice(exits) # Выбираем случайный ID
                else:
                    dest_location_id = None
                    print(f"RuleEngine: Warning: Invalid format for exits from location {curr_loc}: {exits}")


                if dest_location_id:
                    print(f"RuleEngine: NPC {npc.id} choosing to move to location {dest_location_id} from {curr_loc}.")
                    # Возвращаем словарь, описывающий действие "перемещение"
                    return {'type': 'move', 'target_location_id': dest_location_id} # Пример структуры действия


        # Если ни диалог, ни перемещение невозможны, NPC бездействует
        print(f"RuleEngine: NPC {npc.id} not choosing peaceful action (no dialogue targets or valid exits). Choosing idle.")
        return {'type': 'idle', 'total_duration': None} # Пример структуры действия "бездействие"

    async def resolve_dice_roll(self, roll_string: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Parses a dice roll string (e.g., "2d6+3", "d20-1", "4dF"), simulates the roll,
        and returns a structured result.

        Args:
            roll_string: The dice notation string.
            context: Optional game context (unused in this method but included for consistency).

        Returns:
            A dictionary with roll details:
            {
                'roll_string': str,      # The original roll string.
                'num_dice': int,         # Number of dice rolled.
                'dice_sides': Union[int, str], # Sides per die (e.g., 6, 20, or "F" for Fudge).
                'rolls': List[int],      # List of individual die results.
                'modifier': int,         # The modifier applied to the sum of rolls.
                'total': int             # The final total (sum of rolls + modifier).
            }

        Raises:
            ValueError: If the roll_string is invalid.
        """
        # This method is now async, but random.randint is synchronous.
        # For a truly async dice roller (e.g., using an external service or for complex simulation),
        # this would involve `await` calls. For now, it's async for API consistency.
        
        # Using the parsing logic from the existing method, which is more complete
        # than the external dice_roller.py's current simple NdX+M.
        
        original_roll_string = roll_string # Keep original for return
        roll_string = roll_string.lower().strip().replace(" ", "") # Normalize

        # Regex to parse dice notation:
        # (?P<num_dice>\d+)? - Optional number of dice
        # d                       - The 'd' separator
        # (?P<dice_sides>\d+|f)  - Number of sides (digits) or 'f' for Fudge/Fate dice
        # ((?P<modifier_op>[+\-])(?P<modifier_val>\d+))? - Optional modifier group with operator and value
        match = re.fullmatch(r"(?P<num_dice>\d*)d(?P<dice_sides>\d+|f)(?P<modifier_str>(?:[+\-]\d+)*)", roll_string)
        # Modifier_str now captures multiple modifiers like +2-1

        if not match:
            # Try a simpler pattern if the main one fails (e.g. for just "d20")
             match = re.fullmatch(r"d(?P<dice_sides>\d+|f)(?P<modifier_str>(?:[+\-]\d+)*)", roll_string)
             if match: # Prepend num_dice = 1 if it's this simpler format
                 parts_temp = match.groupdict()
                 parts = {'num_dice': '1', **parts_temp}
             else: # If still no match
                 raise ValueError(f"Invalid dice roll string format: '{original_roll_string}'")
        else:
            parts = match.groupdict()


        num_dice_str = parts.get('num_dice')
        num_dice = int(num_dice_str) if num_dice_str else 1 # Default to 1 die if not specified (e.g. "d20")
        
        dice_sides_str = parts['dice_sides']
        
        # Parse complex modifiers like +2-1+5
        modifier = 0
        modifier_str_captured = parts.get('modifier_str', "")
        if modifier_str_captured:
            # Find all occurrences of operator and number (e.g., "+5", "-2")
            modifier_parts = re.findall(r"([+\-])(\d+)", modifier_str_captured)
            for op, val_str in modifier_parts:
                val = int(val_str)
                if op == '+':
                    modifier += val
                elif op == '-':
                    modifier -= val
        
        rolls = []
        calculated_dice_sides: Union[int, str] = 0

        if dice_sides_str == 'f': # Fudge/Fate dice
            calculated_dice_sides = "F"
            for _ in range(num_dice):
                # Standard Fudge dice roll: 3dF -> 3 dice, each -1, 0, or +1
                roll = random.randint(1, 3) - 2 
                rolls.append(roll)
        else:
            calculated_dice_sides = int(dice_sides_str)
            if calculated_dice_sides <= 0:
                raise ValueError("Dice sides must be a positive integer.")
            for _ in range(num_dice):
                rolls.append(random.randint(1, calculated_dice_sides))
        
        total = sum(rolls) + modifier

        return {
            'roll_string': original_roll_string, # Return the original, non-normalized string
            'num_dice': num_dice,
            'dice_sides': calculated_dice_sides,
            'rolls': rolls,
            'modifier': modifier,
            'total': total,
        }

    async def resolve_steal_attempt(self, stealer_char: Character, target_entity: Any, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolves a steal attempt from a target entity.
        Calculates success chance based on stats and determines if an item is stolen.
        Does NOT move the item, only determines outcome.
        """
        print(f"RuleEngine: Resolving steal attempt by {stealer_char.id} on target {getattr(target_entity, 'id', 'Unknown Target')}")

        item_manager: Optional["ItemManager"] = context.get('item_manager')
        # npc_manager: Optional["NpcManager"] = context.get('npc_manager') # Not directly used in this version
        # character_manager: Optional["CharacterManager"] = context.get('character_manager') # Not directly used

        stealer_dex = stealer_char.stats.get('dexterity', 10)
        
        # Get target perception, robustly handling different entity types
        target_stats = getattr(target_entity, 'stats', {})
        if not isinstance(target_stats, dict): # Ensure target_stats is a dict
            target_stats = {}
        target_perc = target_stats.get('perception', 10)
        
        target_name = getattr(target_entity, 'name', 'The target')

        # Calculate success chance
        base_chance = self._rules_data.get('steal_base_chance_percent', 30.0)
        dex_factor = self._rules_data.get('steal_dex_factor_percent', 2.0)
        min_chance = self._rules_data.get('steal_min_chance_percent', 5.0)
        max_chance = self._rules_data.get('steal_max_chance_percent', 95.0)

        success_chance = base_chance + (stealer_dex - target_perc) * dex_factor
        success_chance = max(min_chance, min(success_chance, max_chance)) # Clamp chance

        print(f"RuleEngine: Steal attempt: Stealer Dex={stealer_dex}, Target Perc={target_perc}, Success Chance={success_chance:.2f}%")

        roll = random.uniform(0, 100) # Roll d100

        if roll <= success_chance:
            print(f"RuleEngine: Steal attempt SUCCEEDED (Roll: {roll:.2f} <= Chance: {success_chance:.2f})")
            
            target_inventory = getattr(target_entity, 'inventory', None)
            if isinstance(target_inventory, list) and target_inventory:
                stolen_item_id = random.choice(target_inventory)
                
                item_name = stolen_item_id # Default to ID
                if item_manager and hasattr(item_manager, 'get_item_template_by_instance_id'): # More robust check
                    # To get the name, we might need the item template from the item instance ID
                    # This assumes item_manager can get template details from an instance ID
                    # Or if inventory stores template_ids, this is simpler.
                    # For now, let's assume inventory stores item_instance_ids and ItemManager can get details.
                    # This part is a bit hand-wavy as ItemManager details are not fully specified here.
                    # A more robust approach might be to have ItemManager.get_item_details(item_id)
                    guild_id = getattr(stealer_char, 'guild_id', context.get('guild_id')) # Get guild_id if possible
                    
                    item_instance = None
                    if guild_id and hasattr(item_manager, 'get_item'):
                        item_instance = item_manager.get_item(guild_id, stolen_item_id) # Assumes get_item exists
                    
                    if item_instance and hasattr(item_instance, 'template_id'):
                        item_template = item_manager.get_item_template(guild_id, item_instance.template_id)
                        if item_template and hasattr(item_template, 'name'):
                            item_name = item_template.name
                    elif item_instance and hasattr(item_instance, 'name'): # Fallback if item has name directly
                        item_name = item_instance.name

                print(f"RuleEngine: Stolen item ID: {stolen_item_id} (Name: {item_name})")
                return {"success": True, "stolen_item_id": stolen_item_id, "stolen_item_name": item_name, "message": f"You skillfully pilfered {item_name}!"}
            else:
                print(f"RuleEngine: Steal success, but target {target_name} has no items or invalid inventory.")
                return {"success": False, "message": f"{target_name} has nothing to steal."} # Success but no items
        else:
            print(f"RuleEngine: Steal attempt FAILED (Roll: {roll:.2f} > Chance: {success_chance:.2f})")
            # Optional: Add logic for being caught here based on another roll or margin of failure
            # For now, simple failure.
            return {"success": False, "message": "Your attempt to steal was unsuccessful."}

    async def resolve_hide_attempt(self, character: Character, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolves a character's attempt to hide in their current location.
        Calculates success based on stealth vs. NPC perception and location modifiers.
        """
        print(f"RuleEngine: Resolving hide attempt for character {character.id}")

        guild_id = getattr(character, 'guild_id', context.get('guild_id'))
        if not guild_id:
            return {"success": False, "message": "Cannot determine guild for hide attempt."}

        # Use stored managers
        location_manager = self._location_manager
        npc_manager = self._npc_manager

        if not location_manager:
            return {"success": False, "message": "Location system unavailable, cannot attempt to hide."}
        if not npc_manager:
            return {"success": False, "message": "NPC system unavailable, cannot check for observers."} # Or allow hiding if no NPCs? Game design choice.

        character_location_id = getattr(character, 'location_id', None)
        if not character_location_id:
            return {"success": False, "message": "You are not in a valid location to hide."}

        # Get location details for hiding bonus
        # Assuming LocationManager.get_location_instance or similar exists
        # For simplicity, let's assume location properties are directly accessible or fetched if needed.
        # This part might need adjustment based on how LocationManager provides location properties.
        current_location_instance = location_manager.get_location_instance(guild_id, character_location_id)
        hiding_bonus = 0
        if current_location_instance and hasattr(current_location_instance, 'properties'):
            hiding_bonus = current_location_instance.properties.get('hiding_bonus', 0)
        
        character_stealth = character.stats.get('stealth', 5)

        # Check against NPCs in the same location
        npcs_in_location = npc_manager.get_npcs_in_location(guild_id, character_location_id)
        
        detected_by_npc_name = None

        for npc_observer in npcs_in_location:
            if not getattr(npc_observer, 'is_alive', True): # Skip dead NPCs
                continue

            npc_perception = npc_observer.stats.get('perception', 5)
            
            # Calculate detection chance for this NPC
            base_detection_chance = self._rules_data.get('hide_base_detection_chance_percent', 20.0)
            perception_factor = self._rules_data.get('hide_perception_factor_percent', 5.0)
            min_detection_chance = self._rules_data.get('hide_min_detection_chance_percent', 5.0)
            max_detection_chance = self._rules_data.get('hide_max_detection_chance_percent', 95.0)

            # Higher stealth, lower hiding_bonus = harder to detect
            # Higher perception = easier to detect
            detection_chance = base_detection_chance + (npc_perception - character_stealth - hiding_bonus) * perception_factor
            detection_chance = max(min_detection_chance, min(detection_chance, max_detection_chance)) # Clamp

            roll = random.uniform(0, 100)
            
            print(f"RuleEngine: Hide check against NPC {npc_observer.id} ({getattr(npc_observer, 'name', 'NPC')}): CharStealth={character_stealth}, NPCPerc={npc_perception}, LocBonus={hiding_bonus}, DetectChance={detection_chance:.2f}%, Roll={roll:.2f}")

            if roll <= detection_chance:
                detected_by_npc_name = getattr(npc_observer, 'name', npc_observer.id)
                print(f"RuleEngine: Hide attempt FAILED. Detected by {detected_by_npc_name}.")
                return {"success": False, "message": f"You couldn't find a good hiding spot; {detected_by_npc_name} noticed you!"}
        
        if detected_by_npc_name is None: # Not detected by any NPC
            print(f"RuleEngine: Hide attempt SUCCEEDED for character {character.id}.")
            # Actual application of "Hidden" status effect should be done by StatusManager via CharacterActionProcessor.complete_action
            return {"success": True, "message": "You are now hidden."}
        else:
            # This case should technically be caught above, but as a fallback.
            return {"success": False, "message": "You failed to hide effectively."}

    async def resolve_item_use(self, character: Character, item_instance_data: Dict[str, Any], target_entity: Optional[Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolves the use of an item, determining its effects.
        Does NOT apply effects directly, but returns them for CharacterActionProcessor.
        """
        guild_id = getattr(character, 'guild_id', context.get('guild_id'))
        item_id = item_instance_data.get('id', 'Unknown Item ID') # Instance ID
        item_template_id = item_instance_data.get('template_id')

        print(f"RuleEngine: Resolving use of item instance {item_id} (Template: {item_template_id}) by char {character.id} in guild {guild_id}.")

        # Use stored manager
        item_manager = self._item_manager
        # status_manager = self._status_manager # Not used directly here, effects are returned

        if not item_manager:
            return {"success": False, "message": "Item system unavailable.", "consumed": False}
        if not guild_id:
            return {"success": False, "message": "Cannot determine guild for item use.", "consumed": False}
        if not item_template_id:
            return {"success": False, "message": "Item data is corrupted (missing template ID).", "consumed": False}

        item_template = item_manager.get_item_template(guild_id, item_template_id)
        if not item_template:
            return {"success": False, "message": "Unknown item template.", "consumed": False}

        item_name = getattr(item_template, 'name', item_template_id)
        item_properties = getattr(item_template, 'properties', {})
        if not isinstance(item_properties, dict): item_properties = {} # Ensure it's a dict

        effect_type = item_properties.get('effect_type')
        target_required = item_properties.get('target_required', False) # Does the item need a target?

        if target_required and not target_entity:
            return {"success": False, "message": f"The {item_name} must be used on a target.", "consumed": False}

        # Example 1: Health Potion (targets self, or target_entity if specified and item allows)
        if effect_type == 'heal':
            heal_amount = item_properties.get('heal_amount', 25)
            # Default target is the character using the item
            actual_target_id = character.id
            if target_entity and item_properties.get('can_target_others', False): # Check if item can target others
                actual_target_id = getattr(target_entity, 'id', character.id)
            
            message = f"You use the {item_name}."
            if actual_target_id == character.id:
                message += " You feel refreshed."
            else:
                target_name_str = getattr(target_entity, 'name', 'the target')
                message += f" You use it on {target_name_str}."


            return {
                "success": True, 
                "consumed": True, 
                "message": message,
                "effects": [{"type": "heal", "amount": heal_amount, "target_id": actual_target_id}]
            }

        # Example 2: Targeted status effect item
        elif effect_type == 'apply_status':
            if not target_entity: # Should have been caught by target_required, but double check
                 return {"success": False, "message": f"The {item_name} must be used on a target.", "consumed": False}

            status_to_apply = item_properties.get('status_type')
            duration = item_properties.get('duration') # Can be None for permanent or default duration
            
            if not status_to_apply:
                return {"success": False, "message": f"The {item_name} has an unknown status effect.", "consumed": False}

            target_name_str = getattr(target_entity, 'name', 'the target')
            return {
                "success": True,
                "consumed": True,
                "message": f"You use the {item_name} on {target_name_str}.",
                "effects": [{
                    "type": "status", 
                    "status_type": status_to_apply, 
                    "duration": duration, 
                    "target_id": getattr(target_entity, 'id', None),
                    "source_id": character.id # User is the source
                }]
            }
        
        # TODO: Add more item effect types (e.g., 'damage', 'learn_recipe', 'summon_npc', 'modify_env')

        # Default/Unusable
        return {"success": False, "message": f"You can't figure out how to use the {item_name} right now.", "consumed": False}

    # --- Spell Related Methods ---

    async def check_spell_learning_requirements(self, character: "Character", spell: "Spell", **kwargs: Any) -> tuple[bool, Optional[str]]:
        """
        Checks if a character meets the requirements to learn a specific spell.
        Called by SpellManager.learn_spell.
        Returns a tuple: (can_learn: bool, reason: Optional[str])
        """
        if not spell.requirements:
            return True, None # No requirements, can always learn

        # Ensure character has stats and skills attributes
        character_stats = getattr(character, 'stats', {})
        if not isinstance(character_stats, dict): character_stats = {}
        
        character_skills = getattr(character, 'skills', {})
        if not isinstance(character_skills, dict): character_skills = {}

        for req_key, req_value in spell.requirements.items():
            if req_key.startswith("min_"): # e.g., "min_intelligence"
                stat_name = req_key.split("min_")[1]
                if character_stats.get(stat_name, 0) < req_value:
                    return False, f"Requires {stat_name} {req_value}, has {character_stats.get(stat_name, 0)}."
            
            elif req_key == "required_skill":
                skill_name = req_value
                required_level = spell.requirements.get("skill_level", 1) # Default required skill level is 1
                if character_skills.get(skill_name, 0) < required_level:
                    return False, f"Requires skill '{skill_name}' level {required_level}, has {character_skills.get(skill_name, 0)}."
            
            elif req_key == "skill_level": # Already handled by "required_skill"
                continue

            # TODO: Add other requirement types like "required_class", "required_faction", etc.
            # elif req_key == "required_class":
            #     if getattr(character, 'class_id', None) != req_value: # Assuming character has 'class_id'
            #         return False, f"Requires class '{req_value}'."
            
            else:
                # Unknown requirement, for now, assume it's not met or log a warning
                print(f"RuleEngine: Warning: Unknown spell requirement key '{req_key}' for spell '{spell.id}'.")
                # return False, f"Unknown requirement: {req_key}." # Stricter: fail on unknown reqs

        return True, None

    async def _resolve_dice_roll(self, roll_string: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Internal wrapper for resolve_dice_roll, ensuring consistent signature.
        (Original resolve_dice_roll already matches this, but for clarity)
        """
        # The existing resolve_dice_roll is fine, just ensure it's called correctly.
        # It was previously defined as: async def resolve_dice_roll(self, roll_string: str, context: Dict[str, Any])
        # We can call it directly. The context argument is not strictly needed by resolve_dice_roll itself
        # but providing it if available is harmless.
        return await self.resolve_dice_roll(roll_string, context if context else {})


    async def process_spell_effects(self, caster: "Character", spell: "Spell", target_entity: Optional[Any], guild_id: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Processes the effects of a cast spell.
        Called by SpellManager.cast_spell.
        """
        if not self._character_manager or not self._npc_manager or not self._status_manager:
            return {"success": False, "message": "Core managers not available in RuleEngine for spell processing.", "outcomes": []}

        outcomes: List[Dict[str, Any]] = []
        caster_id = getattr(caster, 'id', 'UnknownCaster')
        
        # Determine default target if none provided based on spell
        actual_target = target_entity
        if not actual_target:
            if spell.target_type == "self":
                actual_target = caster
            # Other target_types like "area" or "closest_enemy" would need more complex logic here
            # or be resolved before calling this method (e.g., in SpellManager or CombatManager)

        if not actual_target and spell.target_type not in ["self", "area_around_caster"]: # Area spells might not have a specific target_entity initially
             # Some spells might require a target that wasn't provided or resolved
            if spell.target_type not in ["self", "area_around_caster", "no_target"]: # Allow spells with no specific target
                return {"success": False, "message": f"Spell '{spell.name}' requires a target, but none was provided or resolved.", "outcomes": []}


        for effect_data in spell.effects:
            effect_type = effect_data.get('type')
            target_id_for_effect = getattr(actual_target, 'id', None) # Get ID of the current target for this effect
            target_type_for_effect = None
            if actual_target:
                target_type_for_effect = type(actual_target).__name__ # "Character" or "NPC"

            outcome_details: Dict[str, Any] = {"effect_type": effect_type, "target_id": target_id_for_effect}

            try:
                if effect_type == "damage":
                    damage_str = effect_data.get('amount', "0")
                    damage_type = effect_data.get('damage_type', "physical")
                    
                    roll_result = await self._resolve_dice_roll(damage_str)
                    actual_damage = roll_result.get('total', 0)
                    
                    outcome_details.update({"amount": actual_damage, "damage_type": damage_type, "roll_details": roll_result})

                    if actual_target and hasattr(actual_target, 'stats') and 'health' in actual_target.stats:
                        # TODO: Add resistance/vulnerability checks based on damage_type
                        actual_target.stats['health'] -= actual_damage
                        print(f"RuleEngine: Applied {actual_damage} {damage_type} damage to {target_id_for_effect}. New health: {actual_target.stats['health']}")
                        
                        if target_type_for_effect == "Character":
                            await self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                        elif target_type_for_effect == "NPC":
                            await self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)
                        
                        # Check for death
                        if actual_target.stats['health'] <= 0:
                            outcome_details["killed"] = True
                            print(f"RuleEngine: Target {target_id_for_effect} killed by {damage_type} damage from spell '{spell.name}'.")
                            # Further death processing (e.g., CombatManager.handle_death) might be needed
                    else:
                        outcome_details["message"] = "Target has no health attribute or target is invalid."
                        print(f"RuleEngine: Spell '{spell.name}' damage effect: Target {target_id_for_effect} has no health or is invalid.")

                elif effect_type == "heal":
                    heal_str = effect_data.get('amount', "0")
                    roll_result = await self._resolve_dice_roll(heal_str)
                    actual_heal = roll_result.get('total', 0)

                    outcome_details.update({"amount": actual_heal, "roll_details": roll_result})

                    if actual_target and hasattr(actual_target, 'stats') and 'health' in actual_target.stats:
                        max_health = actual_target.stats.get('max_health', actual_target.stats['health']) # Assume max_health if present
                        current_health = actual_target.stats['health']
                        new_health = min(current_health + actual_heal, max_health)
                        healed_amount = new_health - current_health
                        actual_target.stats['health'] = new_health
                        
                        outcome_details["healed_amount"] = healed_amount # Store actual amount healed
                        print(f"RuleEngine: Applied {healed_amount} healing to {target_id_for_effect}. New health: {new_health}")

                        if target_type_for_effect == "Character":
                            await self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                        elif target_type_for_effect == "NPC":
                            await self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)
                    else:
                        outcome_details["message"] = "Target has no health attribute or target is invalid."
                        print(f"RuleEngine: Spell '{spell.name}' heal effect: Target {target_id_for_effect} has no health or is invalid.")

                elif effect_type == "apply_status_effect":
                    status_effect_id = effect_data.get('status_effect_id')
                    duration = effect_data.get('duration') # Can be None for default or permanent

                    if status_effect_id and target_id_for_effect and target_type_for_effect:
                        # Ensure StatusManager is available
                        if not self._status_manager:
                             outcome_details["message"] = "StatusManager not available."
                             print(f"RuleEngine: Spell '{spell.name}' apply_status_effect: StatusManager not configured.")
                        else:
                            # Call StatusManager to apply the effect
                            # Assuming add_status_effect_to_entity is an async method
                            # It will handle creation of StatusEffect instance and adding to entity
                            # Need to pass: target_id, target_type, status_type (id), duration, guild_id, source_id
                            # status_data might be needed if the status effect definition is not globally available to StatusManager
                            # For now, assume status_effect_id is enough for StatusManager to find the template.
                            
                            # The target_type needs to be derived from target_entity
                            # e.g. target_type = "Character" or "NPC"

                            await self._status_manager.add_status_effect_to_entity(
                                guild_id=guild_id,
                                entity_id=target_id_for_effect,
                                entity_type=target_type_for_effect,
                                status_effect_template_id=status_effect_id, # Assuming template ID
                                duration_seconds=duration,
                                source_id=caster_id,
                                context_managers=kwargs.get('context_managers', {}) # Pass context if StatusManager needs it
                            )
                            outcome_details.update({"status_effect_id": status_effect_id, "duration": duration})
                            print(f"RuleEngine: Applied status effect '{status_effect_id}' to {target_id_for_effect} for {duration}s.")
                    else:
                        outcome_details["message"] = "Missing status_effect_id, target_id, or target_type."
                        print(f"RuleEngine: Spell '{spell.name}' apply_status_effect: Missing data: status_id={status_effect_id}, target_id={target_id_for_effect}, target_type={target_type_for_effect}")
                
                elif effect_type == "summon":
                    npc_archetype_id = effect_data.get('summon_npc_archetype_id')
                    count = effect_data.get('count', 1)
                    summon_location_id = getattr(caster, 'location_id', None) # Summon at caster's location by default

                    if npc_archetype_id and summon_location_id and self._npc_manager:
                        summoned_npcs_ids = []
                        for _ in range(count):
                            # Assuming NpcManager.create_npc_instance_from_template or similar
                            # This method would handle NPC creation, assigning an ID, and saving.
                            # It might need guild_id, archetype_id, location_id.
                            # For simplicity, let's assume it returns the new NPC's ID or the NPC object
                            new_npc = await self._npc_manager.create_npc_instance_from_template(
                                guild_id=guild_id,
                                npc_template_id=npc_archetype_id,
                                location_id=summon_location_id,
                                name_override=f"{spell.name}'s Summon" # Optional: give summoned creature a special name
                            )
                            if new_npc and hasattr(new_npc, 'id'):
                                summoned_npcs_ids.append(new_npc.id)
                                print(f"RuleEngine: Summoned NPC '{new_npc.id}' (Archetype: {npc_archetype_id}) at location {summon_location_id}.")
                            else:
                                print(f"RuleEngine: Failed to summon NPC of archetype {npc_archetype_id}.")
                        outcome_details.update({"npc_archetype_id": npc_archetype_id, "count": count, "summoned_ids": summoned_npcs_ids, "location_id": summon_location_id})
                    else:
                        outcome_details["message"] = "Missing npc_archetype_id, summon_location_id, or NpcManager."
                        print(f"RuleEngine: Spell '{spell.name}' summon effect: Missing data or NpcManager.")

                elif effect_type in ["buff_stat", "debuff_stat"]:
                    stat_to_modify = effect_data.get('stat')
                    amount = effect_data.get('amount') # Can be positive (buff) or negative (debuff via amount)
                    duration = effect_data.get('duration', 60) # Default duration for stat mods

                    if stat_to_modify and amount is not None and target_id_for_effect and target_type_for_effect and self._status_manager:
                        # This translates to applying a generic "stat_modifier" status effect.
                        # StatusManager would need to know how to interpret its properties.
                        status_effect_properties = {
                            "modifies_stat": stat_to_modify,
                            "modifier_amount": amount if effect_type == "buff_stat" else -amount, # Ensure debuffs are negative
                            "is_multiplier": effect_data.get("is_multiplier", False) # Optional: for percentage buffs
                        }
                        
                        # We need a unique status effect ID for this, or a generic one that StatusManager parses
                        # For example, "generic_stat_buff" or "generic_stat_debuff"
                        # Or, the status_effect_id could be part of the spell's effect_data
                        status_template_id_for_mod = effect_data.get("status_effect_template_id_override", f"mod_{stat_to_modify}_{'buff' if effect_type == 'buff_stat' else 'debuff'}")

                        await self._status_manager.add_status_effect_to_entity(
                            guild_id=guild_id,
                            entity_id=target_id_for_effect,
                            entity_type=target_type_for_effect,
                            status_effect_template_id=status_template_id_for_mod, 
                            duration_seconds=duration,
                            source_id=caster_id,
                            # Pass the specific modifications as part of the status effect instance data
                            # This assumes StatusManager can take 'instance_properties' or similar
                            # and merge them with the template for this specific application.
                            instance_properties=status_effect_properties, 
                            context_managers=kwargs.get('context_managers', {})
                        )
                        outcome_details.update({
                            "stat_modified": stat_to_modify, 
                            "modification_amount": status_effect_properties["modifier_amount"], 
                            "duration": duration
                        })
                        print(f"RuleEngine: Applied {effect_type} to {stat_to_modify} for {target_id_for_effect} by {status_effect_properties['modifier_amount']} for {duration}s.")
                    else:
                        outcome_details["message"] = "Missing data for stat modification or StatusManager unavailable."
                        print(f"RuleEngine: Spell '{spell.name}' {effect_type} effect: Missing data or StatusManager.")
                
                # Add more effect types here (e.g., teleport, create_item, etc.)

                else:
                    outcome_details["message"] = f"Unknown or unhandled spell effect type: '{effect_type}'."
                    print(f"RuleEngine: Warning: Unknown spell effect type '{effect_type}' in spell '{spell.name}'.")
            
            except Exception as e:
                print(f"RuleEngine: Error processing effect type '{effect_type}' for spell '{spell.name}': {e}")
                traceback.print_exc()
                outcome_details["error"] = str(e)
            
            outcomes.append(outcome_details)

        return {"success": True, "message": "Spell effects processed.", "outcomes": outcomes}

    # --- Ability Related Methods ---

    async def check_ability_learning_requirements(self, character: "Character", ability: "Ability", **kwargs: Any) -> tuple[bool, Optional[str]]:
        """
        Checks if a character meets the requirements to learn a specific ability.
        Called by AbilityManager.learn_ability.
        Returns a tuple: (can_learn: bool, reason: Optional[str])
        """
        if not ability.requirements:
            return True, None # No requirements, can always learn

        character_stats = getattr(character, 'stats', {})
        if not isinstance(character_stats, dict): character_stats = {}
        
        character_skills = getattr(character, 'skills', {}) # Assuming Character model has 'skills: Dict[str, int]'
        if not isinstance(character_skills, dict): character_skills = {}
        
        character_level = getattr(character, 'level', 1)
        if not isinstance(character_level, int): character_level = 1

        # Conceptual: Assuming Character model might have 'char_class' or similar
        character_class = getattr(character, 'char_class', None) 
        if character_class and not isinstance(character_class, str): character_class = str(character_class)


        for req_key, req_value in ability.requirements.items():
            if req_key.startswith("min_"): # e.g., "min_strength"
                stat_name = req_key.split("min_")[1]
                if character_stats.get(stat_name, 0) < req_value:
                    return False, f"Requires {stat_name} {req_value}, has {character_stats.get(stat_name, 0)}."
            
            elif req_key == "required_skill":
                skill_name = req_value
                # Default required skill level is 1 if not specified in ability.requirements
                required_level = ability.requirements.get("skill_level", 1) 
                if character_skills.get(skill_name, 0) < required_level:
                    return False, f"Requires skill '{skill_name}' level {required_level}, has {character_skills.get(skill_name, 0)}."
            
            elif req_key == "skill_level": # Already handled by "required_skill" logic above
                continue

            elif req_key == "level": # Character level requirement
                if character_level < req_value:
                    return False, f"Requires character level {req_value}, current level is {character_level}."

            elif req_key == "required_class":
                if character_class is None or character_class.lower() != str(req_value).lower():
                    return False, f"Requires class '{req_value}', character class is '{character_class or 'None'}'."
            
            # TODO: Add other requirement types like "required_race", "required_faction_rank", "required_ability_id" (prerequisite)
            
            else:
                print(f"RuleEngine: Warning: Unknown ability requirement key '{req_key}' for ability '{ability.id}'.")
                # Depending on game design, unknown requirements could either fail or be ignored.
                # Failing is safer to prevent unintended learning.
                # return False, f"Unknown requirement: {req_key}." 

        return True, None

    async def process_ability_effects(self, caster: "Character", ability: "Ability", target_entity: Optional[Any], guild_id: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Processes the effects of an activated ability.
        Called by AbilityManager.activate_ability.
        """
        if not self._character_manager or not self._npc_manager or not self._status_manager:
            return {"success": False, "message": "Core managers not available in RuleEngine for ability processing.", "outcomes": []}

        outcomes: List[Dict[str, Any]] = []
        caster_id = getattr(caster, 'id', 'UnknownCaster')
        
        # Determine default target if none provided based on ability's target_type
        actual_target = target_entity
        if not actual_target and ability.target_type:
            if ability.target_type == "self":
                actual_target = caster
            # Add more complex target resolution if needed (e.g., for "area" effects originating from caster)
        
        # Some abilities might not require a target (e.g. self-buffs that are already handled by actual_target = caster)
        # Or abilities that affect the environment (not yet supported)
        if not actual_target and ability.target_type not in ["self", "no_target", "area_around_caster"]:
            return {"success": False, "message": f"Ability '{ability.name}' requires a target, but none was provided or resolved.", "outcomes": []}

        for effect_data in ability.effects:
            effect_type = effect_data.get('type')
            target_id_for_effect = getattr(actual_target, 'id', None)
            target_type_for_effect = type(actual_target).__name__ if actual_target else None

            outcome_details: Dict[str, Any] = {"effect_type": effect_type, "target_id": target_id_for_effect}

            try:
                if effect_type == "apply_status_effect":
                    status_effect_id = effect_data.get('status_effect_id')
                    duration = effect_data.get('duration') 

                    if status_effect_id and target_id_for_effect and target_type_for_effect and self._status_manager:
                        await self._status_manager.add_status_effect_to_entity(
                            guild_id=guild_id,
                            entity_id=target_id_for_effect,
                            entity_type=target_type_for_effect,
                            status_effect_template_id=status_effect_id,
                            duration_seconds=duration,
                            source_id=caster_id,
                            context_managers=kwargs.get('context_managers', {}) 
                        )
                        outcome_details.update({"status_effect_id": status_effect_id, "duration": duration})
                        print(f"RuleEngine (Ability): Applied status effect '{status_effect_id}' to {target_id_for_effect} for {duration}s.")
                    else:
                        outcome_details["message"] = "Missing status_effect_id, target, type, or StatusManager for apply_status_effect."
                        print(f"RuleEngine (Ability) apply_status_effect: Missing data or StatusManager. StatusID: {status_effect_id}, TargetID: {target_id_for_effect}, TargetType: {target_type_for_effect}")
                
                elif effect_type == "modify_stat": # For temporary activated buffs/debuffs via a status effect
                    stat_to_modify = effect_data.get('stat')
                    amount = effect_data.get('amount')
                    duration = effect_data.get('duration', 60) # Default duration for temp stat mods if not specified
                    
                    # This assumes a "generic_stat_modifier" status effect template exists,
                    # or StatusManager can handle dynamically generated ones based on properties.
                    status_template_id_for_mod = effect_data.get("status_effect_template_id", f"temp_mod_{stat_to_modify}")

                    if stat_to_modify and amount is not None and target_id_for_effect and target_type_for_effect and self._status_manager:
                        status_effect_properties = {
                            "modifies_stat": stat_to_modify,
                            "modifier_amount": amount,
                            "is_multiplier": effect_data.get("is_multiplier", False),
                            "modifier_type": effect_data.get("modifier_type", "flat") # flat, percentage_base, percentage_total
                        }
                        await self._status_manager.add_status_effect_to_entity(
                            guild_id=guild_id,
                            entity_id=target_id_for_effect,
                            entity_type=target_type_for_effect,
                            status_effect_template_id=status_template_id_for_mod,
                            duration_seconds=duration,
                            source_id=caster_id,
                            instance_properties=status_effect_properties,
                            context_managers=kwargs.get('context_managers', {})
                        )
                        outcome_details.update({"stat_modified": stat_to_modify, "modification_amount": amount, "duration": duration})
                        print(f"RuleEngine (Ability): Applied temporary stat modification '{stat_to_modify}' to {target_id_for_effect} by {amount} for {duration}s.")
                    else:
                        outcome_details["message"] = "Missing data for modify_stat or StatusManager."
                        print(f"RuleEngine (Ability) modify_stat: Missing data or StatusManager. Stat: {stat_to_modify}, Amount: {amount}, TargetID: {target_id_for_effect}")

                elif effect_type == "grant_flag":
                    flag_to_grant = effect_data.get('flag')
                    if flag_to_grant and actual_target: # Typically targets self (caster)
                        if not hasattr(actual_target, 'flags') or actual_target.flags is None:
                            print(f"RuleEngine (Ability): Target '{target_id_for_effect}' missing 'flags' attribute. Initializing.")
                            actual_target.flags = [] # type: ignore
                        
                        if flag_to_grant not in actual_target.flags: # type: ignore
                            actual_target.flags.append(flag_to_grant) # type: ignore
                            if target_type_for_effect == "Character":
                                await self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                            elif target_type_for_effect == "NPC":
                                await self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)
                            outcome_details.update({"flag_granted": flag_to_grant})
                            print(f"RuleEngine (Ability): Granted flag '{flag_to_grant}' to {target_id_for_effect}.")
                        else:
                            outcome_details["message"] = f"Target already has flag '{flag_to_grant}'."
                    else:
                        outcome_details["message"] = "Missing flag or target for grant_flag effect."
                        print(f"RuleEngine (Ability) grant_flag: Missing flag or target. Flag: {flag_to_grant}, Target: {target_id_for_effect}")

                elif effect_type == "play_sfx":
                    sfx_id = effect_data.get('sfx_id', ability.sfx_on_activation)
                    if sfx_id:
                        outcome_details.update({"sfx_played": sfx_id})
                        print(f"RuleEngine (Ability): Playing SFX '{sfx_id}' for ability '{ability.name}'.") # Log for now
                    else:
                        outcome_details["message"] = "Missing sfx_id for play_sfx effect."
                
                elif effect_type == "deal_weapon_damage_modifier":
                    # This is complex. For now, apply a temporary status effect that modifies the next relevant attack.
                    # CombatManager or a revised RuleEngine.calculate_damage would check for this status.
                    # E.g., status_effect_id="empowered_attack_power_attack_martial"
                    status_effect_id = effect_data.get("status_effect_id", f"empowered_attack_{ability.id}")
                    duration = effect_data.get("duration_seconds", 6) # Short duration, e.g., for the next attack or turn
                    
                    if self._status_manager and caster_id: # This effect typically targets the caster
                        status_properties = {
                            "damage_multiplier": effect_data.get("damage_multiplier", 1.0),
                            "accuracy_penalty": effect_data.get("accuracy_penalty", 0),
                            # Add other relevant modifiers like "critical_chance_bonus", etc.
                        }
                        await self._status_manager.add_status_effect_to_entity(
                            guild_id=guild_id,
                            entity_id=caster_id, # Targets caster
                            entity_type="Character", # Assuming caster is Character
                            status_effect_template_id=status_effect_id,
                            duration_seconds=duration,
                            source_id=caster_id, # Ability itself is the source via caster
                            instance_properties=status_properties
                        )
                        outcome_details.update({
                            "status_applied_to_caster": status_effect_id, 
                            "details": status_properties,
                            "duration": duration
                        })
                        print(f"RuleEngine (Ability): Applied '{status_effect_id}' to caster {caster_id} for ability '{ability.name}'.")
                    else:
                        outcome_details["message"] = "StatusManager not available or caster_id missing for deal_weapon_damage_modifier."
                        print(f"RuleEngine (Ability) deal_weapon_damage_modifier: StatusManager or caster_id missing.")
                
                # --- Notes on Passive Ability Integration ---
                # 1. Direct Stat Modification Passives (e.g., +10 max_health from "Toughness"):
                #    - These are typically applied once when the ability is learned.
                #    - Logic would reside in AbilityManager.learn_ability or CharacterManager.update_character_after_ability_learn.
                #    - RuleEngine would see the already modified stats. E.g., character.stats['max_health'] would be higher.

                # 2. Flag-Based Passives (e.g., "Darkvision", "Immunity:Poison"):
                #    - AbilityManager.learn_ability would add a flag like "darkvision" to character.flags (List[str]).
                #    - RuleEngine methods would check for these flags:
                #      - In perception checks: if "darkvision" in character.flags and current_light == "dim": bonus += ...
                #      - In damage application: if "immunity_poison" in character.flags and damage_type == "poison": damage = 0
                #      - These checks would be embedded within existing or new RuleEngine logic for specific game mechanics.

                # 3. Conditional Trigger Passives (e.g., "Retaliate: When hit in melee, make a free attack"):
                #    - These are event-driven. The game's main event loop or combat turn processor would:
                #      a. Detect a trigger (e.g., "character_is_hit_melee_event").
                #      b. Check if the affected character has abilities that trigger on this event.
                #      c. If so, call a method like RuleEngine.process_triggered_ability_effects(character, ability, trigger_event_data).
                #    - This is outside the scope of process_ability_effects for activated abilities.

                else:
                    outcome_details["message"] = f"Unknown or unhandled ability effect type: '{effect_type}'."
                    print(f"RuleEngine (Ability): Warning: Unknown ability effect type '{effect_type}' in ability '{ability.name}'.")
            
            except Exception as e:
                print(f"RuleEngine (Ability): Error processing effect type '{effect_type}' for ability '{ability.name}': {e}")
                traceback.print_exc()
                outcome_details["error"] = str(e)
            
            outcomes.append(outcome_details)

        return {"success": True, "message": "Ability effects processed.", "outcomes": outcomes}

    # --- Core Combat and Skill Resolution Methods ---

    async def resolve_skill_check(
        self, 
        character: "Character", 
        skill_name: str, 
        difficulty_class: int, 
        situational_modifier: int = 0, 
        associated_stat: Optional[str] = None, # e.g., "strength" for Athletics
        **kwargs: Any
    ) -> tuple[bool, int, int]:
        """
        Resolves a generic skill check for a character.
        Returns: (success: bool, total_skill_value: int, d20_roll: int)
        """
        # Ensure character has skills and stats attributes
        character_skills = getattr(character, 'skills', {})
        if not isinstance(character_skills, dict): character_skills = {}
        
        character_stats = getattr(character, 'stats', {})
        if not isinstance(character_stats, dict): character_stats = {}

        skill_value = character_skills.get(skill_name.lower(), 0) # Default to 0 if skill not present

        stat_modifier = 0
        # Determine associated stat if not provided
        if not associated_stat:
            # Simple default mapping (can be expanded or moved to rules_data)
            skill_stat_map = {
                "athletics": "strength", "acrobatics": "dexterity", "stealth": "dexterity",
                "perception": "wisdom", "insight": "wisdom", "survival": "wisdom", "medicine": "wisdom",
                "persuasion": "charisma", "deception": "charisma", "intimidation": "charisma", "performance": "charisma",
                "investigation": "intelligence", "lore": "intelligence", "arcana": "intelligence", "religion": "intelligence",
                # Add more skill-stat mappings as needed
            }
            associated_stat = skill_stat_map.get(skill_name.lower())

        if associated_stat:
            stat_value = character_stats.get(associated_stat, 10) # Default to 10 if stat not present
            stat_modifier = (stat_value - 10) // 2 # Standard D&D modifier calculation

        try:
            roll_result_dict = await self._resolve_dice_roll("1d20", context=kwargs) # Pass context if _resolve_dice_roll uses it
            d20_roll = roll_result_dict['total']
        except ValueError: # Handle potential error from _resolve_dice_roll
            print(f"RuleEngine: Error resolving 1d20 for skill check. Defaulting roll to 10.")
            d20_roll = 10 # Fallback roll

        total_skill_value = d20_roll + skill_value + stat_modifier + situational_modifier
        success = total_skill_value >= difficulty_class

        print(f"RuleEngine: Skill Check ({skill_name.capitalize()} DC {difficulty_class}): Roll={d20_roll}, SkillVal={skill_value}, StatMod({associated_stat or 'N/A'})={stat_modifier}, SitMod={situational_modifier} -> Total={total_skill_value}. Success: {success}")
        return success, total_skill_value, d20_roll

    async def resolve_attack_roll(
        self, 
        attacker: Union["Character", "NPC"], 
        defender: Union["Character", "NPC"], 
        weapon: Optional["Item"] = None, # Can be dict or Item model instance
        ability_or_spell: Optional[Union["Ability", "Spell"]] = None, # Can be dict or model instance
        attack_type: str = "melee_weapon", # "melee_weapon", "ranged_weapon", "unarmed", "spell_melee", "spell_ranged"
        situational_modifiers: int = 0,
        **kwargs: Any
    ) -> tuple[bool, int, int, Optional[str]]:
        """
        Resolves an attack roll.
        Returns: (hit: bool, attack_total: int, d20_roll: int, crit_status: Optional[str]) 
                 crit_status can be "critical_hit", "critical_miss", or None.
        """
        attacker_stats = getattr(attacker, 'stats', {})
        if not isinstance(attacker_stats, dict): attacker_stats = {}
        
        attacker_skills = getattr(attacker, 'skills', {}) # Assuming skills for weapon proficiency
        if not isinstance(attacker_skills, dict): attacker_skills = {}

        defender_stats = getattr(defender, 'stats', {})
        if not isinstance(defender_stats, dict): defender_stats = {}

        # --- Determine Attacker's Bonus ---
        # This is a placeholder and needs significant expansion based on game rules.
        # It should consider: weapon proficiency, specific weapon bonuses, spell attack bonuses, abilities.
        attack_bonus = attacker_stats.get("attack_bonus", 0) # Generic attack bonus from stats
        
        # Placeholder for stat modifier (e.g., Strength for melee, Dexterity for ranged)
        primary_stat_name = "strength" # Default for melee
        if attack_type == "ranged_weapon": primary_stat_name = "dexterity"
        elif attack_type.startswith("spell_"): primary_stat_name = "intelligence" # Or based on spell's casting stat
        
        primary_stat_value = attacker_stats.get(primary_stat_name, 10)
        stat_modifier = (primary_stat_value - 10) // 2
        attack_bonus += stat_modifier
        
        # Placeholder for proficiency bonus (e.g., from skills or character level)
        # attack_bonus += getattr(attacker, 'proficiency_bonus', 2) # Example

        # --- Determine Defender's Defense Value (AC) ---
        # Placeholder: Assume a base Armor Class (AC) or use a stat.
        defender_ac = defender_stats.get("armor_class", 10) # Default AC if not specified

        # --- Resolve Attack Roll ---
        try:
            d20_roll_result = await self._resolve_dice_roll("1d20", context=kwargs)
            d20_roll = d20_roll_result['total']
        except ValueError:
            d20_roll = 10 # Fallback

        crit_status: Optional[str] = None
        if d20_roll == 20:
            crit_status = "critical_hit"
        elif d20_roll == 1:
            crit_status = "critical_miss"

        attack_total = d20_roll + attack_bonus + situational_modifiers
        
        hit = False
        if crit_status == "critical_hit":
            hit = True
        elif crit_status == "critical_miss":
            hit = False
        else:
            hit = attack_total >= defender_ac
            
        print(f"RuleEngine: Attack Roll ({attack_type}): AttackerBonus={attack_bonus}, DefenderAC={defender_ac} | Roll={d20_roll} -> Total={attack_total}. Hit: {hit} (Crit: {crit_status})")
        return hit, attack_total, d20_roll, crit_status

    async def calculate_damage(
        self, 
        attacker: Union["Character", "NPC"], 
        defender: Optional[Union["Character", "NPC"]], 
        base_damage_roll: str, # e.g., "1d8", "2d6+3"
        damage_type: str, 
        is_critical_hit: bool = False,
        weapon: Optional["Item"] = None, # For potential weapon properties like versatile
        ability_or_spell: Optional[Union["Ability", "Spell"]] = None, # For spell/ability specific damage mods
        **kwargs: Any
    ) -> int:
        """
        Calculates damage dealt by an attack or effect.
        """
        attacker_stats = getattr(attacker, 'stats', {})
        if not isinstance(attacker_stats, dict): attacker_stats = {}

        # 1. Roll base damage
        try:
            rolled_damage_dict = await self._resolve_dice_roll(base_damage_roll, context=kwargs)
            rolled_damage = rolled_damage_dict['total']
        except ValueError:
            print(f"RuleEngine: Error resolving base damage roll '{base_damage_roll}'. Defaulting to 1.")
            rolled_damage = 1

        # 2. Add attacker's relevant stat modifier (placeholder)
        # This needs to be determined by weapon type (str for melee, dex for finesse/ranged) or spell casting stat.
        # For simplicity, let's assume a generic "damage_modifier" stat or use strength.
        stat_damage_modifier = (attacker_stats.get("strength", 10) - 10) // 2 # Example for melee
        # if weapon and weapon.type == "ranged": stat_damage_modifier = (attacker_stats.get("dexterity", 10) - 10) // 2
        # if spell: stat_damage_modifier = (attacker_stats.get(spell.casting_stat, 10) - 10) // 2
        
        total_damage = rolled_damage + stat_damage_modifier

        # 3. Handle critical hit
        if is_critical_hit:
            # Simple crit: roll damage dice again and add.
            # More complex: max base dice then roll again, or other rules.
            try:
                crit_roll_dict = await self._resolve_dice_roll(base_damage_roll.split('+')[0].split('-')[0], context=kwargs) # Reroll only dice part
                crit_damage_bonus = crit_roll_dict['total'] 
                # For "max damage + roll" crit:
                # max_base_damage = (num_dice * dice_sides) from base_damage_roll (needs parsing)
                # crit_damage_bonus = max_base_damage + crit_roll_dict['total'] - rolled_damage_dict['num_dice'] * 1 # if min roll was 1
                total_damage += crit_damage_bonus
                print(f"RuleEngine: Critical Hit! Added {crit_damage_bonus} damage.")
            except ValueError:
                print(f"RuleEngine: Error resolving critical hit damage for '{base_damage_roll}'.")


        # 4. Apply resistances/vulnerabilities (Placeholder)
        if defender:
            defender_stats = getattr(defender, 'stats', {})
            if not isinstance(defender_stats, dict): defender_stats = {}
            # Example:
            # resistances = defender_stats.get("resistances", {}) # e.g., {"fire": 0.5, "slashing": 0.75}
            # vulnerabilities = defender_stats.get("vulnerabilities", {}) # e.g., {"bludgeoning": 1.5}
            # if damage_type in resistances: total_damage *= resistances[damage_type]
            # if damage_type in vulnerabilities: total_damage *= vulnerabilities[damage_type]
            pass # Placeholder for resistance/vulnerability logic

        final_damage = max(0, int(round(total_damage))) # Ensure damage is not negative and is an integer
        
        print(f"RuleEngine: Calculated Damage: BaseRoll='{base_damage_roll}', RolledDmg={rolled_damage}, StatMod={stat_damage_modifier}, Crit={is_critical_hit} -> FinalDmg={final_damage} ({damage_type})")
        return final_damage

    # --- Stubs for Other Key Missing Mechanics ---

    async def get_game_time(self, context: Optional[Dict[str, Any]] = None) -> float:
        """
        Returns the current in-game time.
        Relies on TimeManager if provided during initialization.
        """
        if self._time_manager and hasattr(self._time_manager, 'get_current_game_time'):
            # Assuming get_current_game_time in TimeManager might be async
            try:
                # If get_current_game_time is async, it should be awaited.
                # For now, let's assume it could be either, and if it's async,
                # the TimeManager type hint should reflect Awaitable[float].
                # If it's synchronous, direct call is fine.
                # Given the task is about async/await, let's assume it *could* be async.
                current_time = await self._time_manager.get_current_game_time(context=context)
                return float(current_time)
            except Exception as e:
                print(f"RuleEngine: Error getting game time from TimeManager: {e}")
                traceback.print_exc()
                return 0.0 # Fallback time
        else:
            # Fallback if TimeManager is not available or doesn't have the method
            # This might be a placeholder (e.g., always noon) or an error
            print("RuleEngine: Warning: TimeManager not available or get_current_game_time missing. Returning 0.0 as game time.")
            return 0.0

    async def award_experience(self, character: "Character", amount: int, **kwargs: Any) -> None:
        """Awards experience points to a character."""
        # TODO: Actual XP logic, check for level up
        char_id = getattr(character, 'id', 'UnknownCharacter')
        print(f"RuleEngine (Stub): Awarding {amount} XP to character {char_id}.")
        # character.experience += amount
        # self.check_for_level_up(character, **kwargs)
        # if self._character_manager: await self._character_manager.mark_character_dirty(character.guild_id, character.id)
        pass

    async def check_for_level_up(self, character: "Character", **kwargs: Any) -> bool:
        """Checks if a character has enough XP to level up and handles the process."""
        # TODO: Implement XP thresholds, stat increases, new abilities/spells.
        char_id = getattr(character, 'id', 'UnknownCharacter')
        print(f"RuleEngine (Stub): Checking for level up for character {char_id}. Returning False.")
        return False

    async def calculate_initiative(self, combatants: List[Union["Character", "NPC"]], **kwargs: Any) -> List[tuple[str, int]]:
        """Calculates initiative for combatants."""
        # TODO: Implement initiative based on Dexterity, feats, etc.
        print(f"RuleEngine (Stub): Calculating initiative for {len(combatants)} combatants. Shuffling for now.")
        
        initiative_list: List[tuple[str, int]] = []
        # Shuffle for randomness, assign placeholder scores
        random.shuffle(combatants) 
        for i, combatant in enumerate(combatants):
            combatant_id = getattr(combatant, 'id', f"unknown_combatant_{i}")
            # Placeholder initiative score (e.g., d20 + dex_mod)
            # For now, just use index or a random number
            initiative_score = random.randint(1, 20) + i 
            initiative_list.append((combatant_id, initiative_score))
        
        # Sort by initiative score, descending
        initiative_list.sort(key=lambda x: x[1], reverse=True)
        print(f"RuleEngine (Stub): Initiative order: {initiative_list}")
        return initiative_list

    async def apply_equipment_effects(self, character: "Character", item: "Item", equipping: bool, **kwargs: Any) -> None:
        """Applies or removes effects of equipping/unequipping an item."""
        # TODO: Modify character stats, grant/remove abilities/status effects based on item properties.
        char_id = getattr(character, 'id', 'UnknownCharacter')
        item_id = getattr(item, 'id', 'UnknownItem') if not isinstance(item, dict) else item.get('id', 'UnknownItem')
        action = "equipping" if equipping else "unequipping"
        print(f"RuleEngine (Stub): Applying equipment effects for character {char_id} {action} item {item_id}.")
        # Example:
        # if equipping:
        #     if item.properties.get("bonus_strength"): character.stats["strength"] += item.properties["bonus_strength"]
        # else:
        #     if item.properties.get("bonus_strength"): character.stats["strength"] -= item.properties["bonus_strength"]
        # if self._character_manager: await self._character_manager.mark_character_dirty(character.guild_id, character.id)
        pass

    async def resolve_saving_throw(
        self, 
        character: Union["Character", "NPC"], 
        stat_to_save_with: str, 
        difficulty_class: int, 
        situational_modifier: int = 0,
        **kwargs: Any
    ) -> bool:
        """Resolves a saving throw for a character against a DC."""
        entity_stats = getattr(character, 'stats', {})
        if not isinstance(entity_stats, dict): entity_stats = {}

        stat_value = entity_stats.get(stat_to_save_with.lower(), 10) # Default to 10 if stat not present
        stat_modifier = (stat_value - 10) // 2

        try:
            roll_result_dict = await self._resolve_dice_roll("1d20", context=kwargs)
            d20_roll = roll_result_dict['total']
        except ValueError:
            d20_roll = 10 # Fallback

        total_save_value = d20_roll + stat_modifier + situational_modifier
        success = total_save_value >= difficulty_class
        
        char_id = getattr(character, 'id', 'UnknownEntity')
        print(f"RuleEngine: Saving Throw ({stat_to_save_with.capitalize()} DC {difficulty_class}) for {char_id}: Roll={d20_roll}, StatMod={stat_modifier}, SitMod={situational_modifier} -> Total={total_save_value}. Success: {success}")
        return success

    # --- End of Core Combat and Skill Resolution Methods ---

    async def _get_entity_data_for_check(
        self, 
        entity_id: str, 
        entity_type: str, 
        requested_data_keys: List[str], 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Fetches various data points for a given entity (Character or NPC) 
        using the appropriate manager.

        Args:
            entity_id: The ID of the entity.
            entity_type: The type of the entity ("Character" or "NPC").
            requested_data_keys: A list of keys for the data points to retrieve 
                                 (e.g., "stats", "skills", "inventory", "name").
            context: The game context, potentially containing guild_id for manager calls.

        Returns:
            A dictionary containing the requested data.
        """
        entity_data_payload: Dict[str, Any] = {"id": entity_id, "type": entity_type}
        entity_obj: Optional[Any] = None # Holds Character or NPC object
        
        guild_id_from_context = context.get('guild_id') if context else None

        if entity_type == "Character":
            if not self._character_manager:
                print(f"RuleEngine._get_entity_data_for_check: Warning: CharacterManager not available. Cannot fetch data for Character {entity_id}.")
                return entity_data_payload
            if not guild_id_from_context:
                print(f"RuleEngine._get_entity_data_for_check: Warning: guild_id not in context. Cannot fetch Character {entity_id}.")
                return entity_data_payload
            entity_obj = self._character_manager.get_character(guild_id=guild_id_from_context, character_id=entity_id)
        elif entity_type == "NPC":
            if not self._npc_manager:
                print(f"RuleEngine._get_entity_data_for_check: Warning: NpcManager not available. Cannot fetch data for NPC {entity_id}.")
                return entity_data_payload
            if not guild_id_from_context:
                print(f"RuleEngine._get_entity_data_for_check: Warning: guild_id not in context. Cannot fetch NPC {entity_id}.")
                return entity_data_payload
            entity_obj = self._npc_manager.get_npc(guild_id=guild_id_from_context, npc_id=entity_id)
        else:
            print(f"RuleEngine._get_entity_data_for_check: Error: Unsupported entity_type '{entity_type}' for ID {entity_id}.")
            return entity_data_payload

        if entity_obj is None:
            print(f"RuleEngine._get_entity_data_for_check: Warning: Entity {entity_type} with ID {entity_id} not found.")
            return entity_data_payload

        # Retrieve requested data points
        for key in requested_data_keys:
            if key == "stats":
                entity_data_payload["stats"] = getattr(entity_obj, 'stats', {})
            elif key == "skills":
                entity_data_payload["skills"] = getattr(entity_obj, 'skills', {})
            elif key == "status_effects":
                # This usually returns a list of StatusEffect objects or dictionaries
                entity_data_payload["status_effects"] = getattr(entity_obj, 'status_effects', []) 
            elif key == "items" or key == "inventory":
                entity_data_payload["inventory"] = getattr(entity_obj, 'inventory', [])
            elif key == "name":
                entity_data_payload["name"] = getattr(entity_obj, 'name', 'Unknown Entity')
            elif key == "location_id":
                entity_data_payload["location_id"] = getattr(entity_obj, 'location_id', None)
            elif key == "current_hp":
                # Assuming stats dict contains 'health' or 'current_hp'
                entity_stats = getattr(entity_obj, 'stats', {})
                entity_data_payload["current_hp"] = entity_stats.get('health', entity_stats.get('current_hp', 0))
            elif key == "max_hp":
                entity_stats = getattr(entity_obj, 'stats', {})
                entity_data_payload["max_hp"] = entity_stats.get('max_health', entity_stats.get('max_hp', 0))
            elif key == "is_alive":
                entity_stats = getattr(entity_obj, 'stats', {})
                current_hp = entity_stats.get('health', entity_stats.get('current_hp', 0))
                entity_data_payload["is_alive"] = current_hp > 0 # Basic check
            # Add more data points as they become necessary for checks (e.g., "level", "race").
            # else:
            #     print(f"RuleEngine._get_entity_data_for_check: Warning: Unknown requested_data_key '{key}' for entity {entity_id}.")

        return entity_data_payload

    async def resolve_check(
        self, 
        check_type: str, 
        entity_doing_check_id: str, 
        entity_doing_check_type: str, # e.g. "Character", "NPC"
        target_entity_id: Optional[str] = None, 
        target_entity_type: Optional[str] = None, # e.g. "Character", "NPC", "Item", "Location"
        difficulty_dc: Optional[int] = None, # Explicit DC for the check
        context: Optional[Dict[str, Any]] = None
    ) -> "DetailedCheckResult":
        """
        Resolves a generic check (skill check, saving throw, attack roll, etc.) 
        based on rules defined in _rules_data.

        This method orchestrates fetching entity data, calculating modifiers, 
        rolling dice, comparing against a target (DC or opposed check), 
        and determining the outcome including critical success/failure.

        Args:
            check_type: The key for the check configuration in rules_data (e.g., "athletics_check", "spell_attack", "perception_dc").
            entity_doing_check_id: ID of the entity performing the check.
            entity_doing_check_type: Type of the entity performing the check.
            target_entity_id: Optional ID of the entity being targeted by the check (for opposed checks or checks against target properties).
            target_entity_type: Optional type of the target entity.
            difficulty_dc: Optional explicit Difficulty Class for the check. If not provided, DC might come from target or check_config.
            context: Optional dictionary for additional context, could include temporary modifiers or environmental factors.

        Returns:
            A DetailedCheckResult object containing all information about the check and its outcome.
        """
        if context is None:
            context = {}

        # Initialize DetailedCheckResult with defaults/placeholders
        # Most of these will be populated as the method progresses.
        result = DetailedCheckResult(
            check_type=check_type,
            entity_doing_check_id=entity_doing_check_id,
            target_entity_id=target_entity_id,
            difficulty_dc=difficulty_dc,
            roll_formula="1d20", # Default, will be updated by check_config
            rolls=[],
            modifier_applied=0,
            modifier_details={},
            total_roll_value=0,
            target_value=difficulty_dc, # Initial target value is the provided DC
            outcome=CheckOutcome.FAILURE,
            is_success=False,
            is_critical=False,
            description="Check resolution has not started."
        )

        guild_id = context.get('guild_id') if context else None
        if not guild_id:
            result.description = "Error: guild_id missing from context for resolve_check."
            # print(result.description) # For server logs
            return result # Cannot proceed without guild_id for data fetching

        # 1. Get Check Configuration from self.rules_data
        # Ensure self.rules_data is loaded, e.g., in __init__ or a load_state method
        if not self._rules_data or 'checks' not in self._rules_data:
            result.description = "Error: RuleEngine rules_data not loaded or 'checks' key missing."
            return result
        
        check_config = self._rules_data.get('checks', {}).get(check_type)
        if not check_config:
            result.description = f"Error: No configuration found for check_type '{check_type}'."
            return result

        result.roll_formula = check_config.get('roll_formula', '1d20') # Update from config

        # 2. Fetch Actor Data
        actor = None
        if self._character_manager and entity_doing_check_type == "Character":
            actor = self._character_manager.get_character(guild_id, entity_doing_check_id)
        elif self._npc_manager and entity_doing_check_type == "NPC":
            actor = self._npc_manager.get_npc(guild_id, entity_doing_check_id)
        
        if not actor:
            result.description = f"Error: Actor {entity_doing_check_type} ID {entity_doing_check_id} not found."
            return result

        # 3. Calculate Modifier based on actor's stats/skills and check_config
        calculated_modifier = 0
        modifier_details_dict: Dict[str, Any] = {"base": 0}
        
        primary_stat = check_config.get('primary_stat') # e.g., "dexterity"
        if primary_stat and hasattr(actor, 'stats') and isinstance(actor.stats, dict):
            stat_value = actor.stats.get(primary_stat, 10)
            stat_mod = (stat_value - 10) // 2
            calculated_modifier += stat_mod
            modifier_details_dict[primary_stat] = stat_mod

        relevant_skill = check_config.get('relevant_skill') # e.g., "stealth"
        if relevant_skill and hasattr(actor, 'skills') and isinstance(actor.skills, dict):
            skill_value = actor.skills.get(relevant_skill, 0)
            calculated_modifier += skill_value
            modifier_details_dict[relevant_skill] = skill_value
        
        # TODO: Add modifiers from status effects, items, context, etc.
        result.modifier_applied = calculated_modifier
        result.modifier_details = modifier_details_dict

        # 4. Perform Dice Roll
        try:
            # Use the roll_formula from check_config
            roll_result_data = await self.resolve_dice_roll(result.roll_formula, context)
            result.rolls = roll_result_data.get('rolls', [])
            base_roll_value = roll_result_data.get('total', 0) # This total already includes modifiers from dice string itself
        except ValueError as e:
            result.description = f"Error during dice roll for '{result.roll_formula}': {e}"
            return result
        
        result.total_roll_value = base_roll_value + calculated_modifier # Add character/skill mods to dice string's total

        # 5. Determine Target Value (DC)
        actual_dc = difficulty_dc # Use provided DC if any
        
        if actual_dc is None: # If no explicit DC, try to get from check_config or target
            if target_entity_id and target_entity_type:
                target_entity = None
                if self._character_manager and target_entity_type == "Character":
                    target_entity = self._character_manager.get_character(guild_id, target_entity_id)
                elif self._npc_manager and target_entity_type == "NPC":
                    target_entity = self._npc_manager.get_npc(guild_id, target_entity_id)

                if target_entity:
                    # Example: DC could be a specific stat of the target
                    dc_stat_name = check_config.get('target_dc_stat') # e.g., "passive_perception" or "armor_class"
                    if dc_stat_name and hasattr(target_entity, 'stats') and isinstance(target_entity.stats, dict):
                        actual_dc = target_entity.stats.get(dc_stat_name, check_config.get('default_dc', 15))
                    else:
                        actual_dc = check_config.get('default_dc', 15) # Fallback DC from config
                else: # Target not found, use default DC
                    actual_dc = check_config.get('default_dc', 15)
            else: # No target and no explicit DC, use default from config
                actual_dc = check_config.get('default_dc', 15)
        
        result.target_value = actual_dc
        if result.difficulty_dc is None: result.difficulty_dc = actual_dc # Store the DC used if not explicit

        # 6. Determine Outcome
        result.is_success = result.total_roll_value >= actual_dc
        
        # Critical success/failure logic (simple d20 based for now)
        d20_roll = result.rolls[0] if result.rolls and result.roll_formula.startswith("1d20") else 0
        
        if d20_roll == 20 and check_config.get('allow_critical_success', True):
            result.is_critical = True
            result.is_success = True # Crit success is always a success
            result.outcome = CheckOutcome.CRITICAL_SUCCESS
        elif d20_roll == 1 and check_config.get('allow_critical_failure', True):
            result.is_critical = True
            result.is_success = False # Crit failure is always a failure
            result.outcome = CheckOutcome.CRITICAL_FAILURE
        else:
            result.outcome = CheckOutcome.SUCCESS if result.is_success else CheckOutcome.FAILURE

        # 7. Populate Description
        result.description = (
            f"{check_type.replace('_', ' ').capitalize()} by {getattr(actor, 'name', entity_doing_check_id)}: "
            f"Roll ({result.roll_formula}): {result.rolls} + Mod: {result.modifier_applied} = Total: {result.total_roll_value}. "
            f"Target DC: {actual_dc}. Outcome: {result.outcome.name}{' (Critical)' if result.is_critical else ''}."
        )
        
        print(f"RuleEngine.resolve_check: {result.description}")
        return result

    # --- Stubs for Other Key Missing Mechanics ---