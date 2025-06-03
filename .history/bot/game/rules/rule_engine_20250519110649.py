# bot/game/rules/rule_engine.py

from __future__ import annotations
import json  # Может понадобиться для работы с данными правил из JSON
import traceback  # Для вывода трассировки ошибок
import asyncio  # Если методы RuleEngine будут асинхронными

# Импорт базовых типов и TYPE_CHECKING
from typing import Optional, Dict, Any, List, Set, Callable, Awaitable, TYPE_CHECKING

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

    # Процессоры, которые могут создавать циклические импорты
    from bot.game.event_processors.event_stage_processor import EventStageProcessor # <-- Added, needed for handle_stage fix
    # from bot.game.event_processors.event_action_processor import EventActionProcessor # Если используется


# --- Imports needed at Runtime ---
# Эти модули необходимы для выполнения кода (например, для создания экземпляров, вызовов статических методов, проверок isinstance)
# Если модуль импортируется здесь, убедитесь, что он НЕ ИМПОРТИРУЕТ RuleEngine напрямую.
from bot.game.models.character import Character # Прямой импорт модели, если она нужна для isinstance или других runtime целей


print("DEBUG: rule_engine.py module loaded.")


class RuleEngine:
    """
    Система правил для вычисления результатов действий, проверок условий,
    расчётов (урон, длительность, проверки) и AI-логики.
    Работает с данными мира, полученными из менеджеров через контекст.
    """
    # required_args_for_load = [] # Если load_rules_data требует аргументов, добавьте сюда
    # required_args_for_save = [] # Если save_state требует аргументов, добавьте сюда

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        print("Initializing RuleEngine...")
        self._settings = settings or {}
        self._rules_data: Dict[str, Any] = {} # Аннотация Dict, внутри Any - нормально
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
