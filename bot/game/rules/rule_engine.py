# bot/game/rules/rule_engine.py

from __future__ import annotations
import json  # Может понадобиться для работы с данными правил из JSON
import random
import re
import traceback  # Для вывода трассировки ошибок
import asyncio  # Если методы RuleEngine будут асинхронными

# Импорт базовых типов и TYPE_CHECKING
from typing import Optional, Dict, Any, List, Set, Tuple, Callable, Awaitable, TYPE_CHECKING, Union # Added Union

from bot.game.models.check_models import CheckOutcome, DetailedCheckResult
from bot.game.models.status_effect import StatusEffect # Added for parsing status effects

# --- Imports used in TYPE_CHECKING for type hints ---
# Эти модули импортируются ТОЛЬКО для статического анализа (Pylance/Mypy).
# Это разрывает циклы импорта при runtime.
if TYPE_CHECKING:
    # Модели, которые вы упоминаете в аннотациях (импорт в TYPE_CHECKING тоже для безопасности,
    # если сами файлы моделей импортируют что-то, что вызывает цикл)
    # from bot.game.models.character import Character # Character модель импортируется напрямую, т.к. используется в runtime (check isinstance)
    from bot.game.models.npc import NPC # Возможно, нужен прямой импорт для isinstance
    from bot.game.models.party import Party # Возможно, нужен прямой импорт для isinstance
    # from bot.game.models.combat import Combat # Already imported directly
    # from bot.game.models.combat import CombatParticipant # Already imported below for runtime
    from bot.game.models.ability import Ability # For Ability logic
    from bot.game.models.item import Item # For Item type hinting
    from bot.game.models.spell import Spell # For spell logic
    from bot.game.models.skill import Skill
    # Item is already listed above, no need to add again
    from bot.game.models.rules_config import RulesConfig # For type hint

    # Менеджеры и процессоры, которые могут создавать циклические импорты
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.services.openai_service import OpenAIService
    from bot.game.managers.spell_manager import SpellManager
    from bot.game.managers.skill_manager import SkillManager


    # Процессоры, которые могут создавать циклические импорты
    from bot.game.event_processors.event_stage_processor import EventStageProcessor # <-- Added, needed for handle_stage fix
    # from bot.game.event_processors.event_action_processor import EventActionProcessor # Если используется
    from bot.game.models.check_models import DetailedCheckResult as DetailedCheckResultHint # For type hinting in methods if needed


# --- Imports needed at Runtime ---
# Эти модули необходимы для выполнения кода (например, для создания экземпляров, вызовов статических методов, проверок isinstance)
# Если модуль импортируется здесь, убедитесь, что он НЕ ИМПОРТИРУЕТ RuleEngine напрямую.
from bot.game.models.character import Character # Прямой импорт модели, если она нужна для isinstance или других runtime целей
from bot.game.models.combat import Combat, CombatParticipant # Added Combat for method signature
from bot.game.managers.time_manager import TimeManager # Added for runtime
import bot.game.rules.combat_rules as combat_rules # Import the module
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
                 rules_data: Optional[Dict[str, Any]] = None, # Added rules_data
                 game_log_manager: Optional["GameLogManager"] = None # Added GameLogManager
                 ):
        print("Initializing RuleEngine...")
        self._settings = settings or {}
        self._game_log_manager = game_log_manager # Store GameLogManager
        
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
            self._rules_data = self._settings.get('game_rules', {}) # Fallback to settings
        
        print("RuleEngine initialized.")

    async def load_rules_data(self) -> None:
        """
        Загружает правила из настроек или других источников.
        """
        print("RuleEngine: Loading rules data...")
        # Предполагаем, что правила не зависят от guild_id и загружаются глобально
        self._rules_data = self._settings.get('game_rules', {})
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
                item_template_id_condition = data.get('item_template_id')
                item_id_condition = data.get('item_id') # Instance ID
                quantity_condition = data.get('quantity', 1)

                if entity_id and entity_type and (item_template_id_condition or item_id_condition):
                    # ItemManager does not have check_entity_has_item. We need to implement the logic here.
                    # guild_id should be in context
                    guild_id_from_context = context.get('guild_id')
                    if guild_id_from_context:
                        owned_items = im.get_items_by_owner(guild_id_from_context, entity_id)
                        found_item_count = 0
                        for item_instance_dict in owned_items:
                            matches_template = (item_template_id_condition and
                                                item_instance_dict.get('template_id') == item_template_id_condition)
                            matches_instance_id = (item_id_condition and
                                                   item_instance_dict.get('id') == item_id_condition)

                            if item_id_condition: # If checking for a specific instance
                                if matches_instance_id:
                                    found_item_count += item_instance_dict.get('quantity', 0)
                                    # If specific instance ID is checked, typically quantity check is against this one item.
                                    # Break if this specific item is found, sum its quantity.
                                    break
                            elif matches_template: # If checking by template, sum quantities of all matching
                                found_item_count += item_instance_dict.get('quantity', 0)

                        if found_item_count >= quantity_condition:
                            met = True
                    else:
                        print(f"RuleEngine: Warning: guild_id not in context for 'has_item' check.")
                else:
                    print(f"RuleEngine: Warning: Insufficient data for 'has_item' check (entity_id, entity_type, item_template_id/item_id).")

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
                    # StatusManager does not have get_status_effects_on_entity_by_type.
                    # We need to iterate through all statuses for the entity in the guild.
                    guild_id_from_context = context.get('guild_id')
                    if guild_id_from_context:
                        # Accessing protected member _status_effects as there's no public getter for all statuses of an entity by type.
                        guild_statuses_cache = sm._status_effects.get(guild_id_from_context, {})
                        for effect_instance in guild_statuses_cache.values():
                            if (effect_instance.target_id == entity_id and
                                effect_instance.target_type == entity_type and
                                effect_instance.status_type == status_type):
                                met = True
                                break # Found at least one instance of the status type
                    else:
                        print(f"RuleEngine: Warning: guild_id not in context for 'has_status' check.")
                else:
                    print(f"RuleEngine: Warning: Insufficient data for 'has_status' check (entity_id, entity_type, status_type).")
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
        print("RuleEngine: Generating initial character stats.")
        default_stats = self._rules_data.get("character_stats_rules", {}).get("default_initial_stats", {'strength': 10, 'dexterity': 10, 'constitution': 10, 'intelligence': 10, 'wisdom': 10, 'charisma': 10})
        return default_stats.copy()  # Return a copy to prevent modification of the original rules data

    def _calculate_attribute_modifier(self, attribute_value: int) -> int:
        """
        Calculates the modifier for a given attribute value based on the formula in rules_data.
        """
        char_stats_rules = self._rules_data.get("character_stats_rules", {})
        formula_str = char_stats_rules.get("attribute_modifier_formula", "(attribute_value - 10) // 2")

        # Basic sanitization/validation for the formula string to prevent arbitrary code execution.
        # This is a simplified approach. For production, a more robust expression parser/evaluator is recommended.
        allowed_chars = "attribute_value()+-*/0123456789 " # Whitelist characters
        if not all(char in allowed_chars for char in formula_str):
            print(f"RuleEngine: Warning: Invalid characters in attribute_modifier_formula: '{formula_str}'. Using default.")
            formula_str = "(attribute_value - 10) // 2"

        try:
            # Replace placeholder and evaluate.
            # Ensure 'attribute_value' is the only variable available in the eval scope.
            # Using a limited globals/locals dict for eval.
            modifier = eval(formula_str, {"__builtins__": {}}, {"attribute_value": attribute_value})
            return int(modifier)
        except Exception as e:
            print(f"RuleEngine: Error evaluating attribute_modifier_formula '{formula_str}': {e}. Using default calculation.")
            # Fallback to default if formula is malformed or causes error
            return (attribute_value - 10) // 2

    def get_base_dc(self, relevant_stat_value: int, difficulty_modifier: Optional[str] = None) -> int:
        """
        Calculates a base Difficulty Class (DC) for a check, considering a relevant stat
        and an optional difficulty modifier string (e.g., "easy", "hard").
        """
        check_rules = self._rules_data.get("check_rules", {})
        base_dc_config = check_rules.get("base_dc_calculation", {})
        difficulty_modifiers_config = check_rules.get("difficulty_modifiers", {})

        base_dc_value = base_dc_config.get("base_value", 10)
        stat_contribution_formula = base_dc_config.get("stat_contribution_formula", "(relevant_stat_value - 10) // 2")

        stat_contribution = 0
        try:
            # Evaluate the formula with relevant_stat_value in its scope
            # Ensure 'relevant_stat_value' is the only variable available.
            stat_contribution = eval(stat_contribution_formula, {"__builtins__": {}}, {"relevant_stat_value": relevant_stat_value})
        except Exception as e:
            print(f"RuleEngine: Error evaluating stat_contribution_formula '{stat_contribution_formula}': {e}. Using default calculation.")
            # Fallback to default calculation
            stat_contribution = (relevant_stat_value - 10) // 2

        difficulty_mod_value = 0
        if difficulty_modifier:
            difficulty_mod_value = difficulty_modifiers_config.get(difficulty_modifier.lower(), 0)

        final_dc = base_dc_value + stat_contribution + difficulty_mod_value

        print(f"RuleEngine.get_base_dc: relevant_stat={relevant_stat_value}, difficulty_mod_key='{difficulty_modifier}', base_val={base_dc_value}, stat_contrib={stat_contribution} (from formula: '{stat_contribution_formula}'), diff_mod_val={difficulty_mod_value} -> Final DC={final_dc}")

        return int(final_dc)

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
        if cman: # cman is CombatManager instance from context
            # CombatManager does not have get_living_participants.
            # Combat object (passed as `combat`) has `combat.participants` (List[CombatParticipant])
            # CombatParticipant has `hp` attribute.
            living_participants_in_combat = [
                p_obj for p_obj in combat.participants
                if isinstance(p_obj, CombatParticipant) and p_obj.hp > 0
            ]

            # Ищем первую живую цель, которая не является этим NPC
            for p_target_obj in living_participants_in_combat:
                if p_target_obj.entity_id != npc.id: # npc is the one choosing action
                    print(f"RuleEngine: NPC {npc.id} choosing attack on {p_target_obj.entity_id} (Type: {p_target_obj.entity_type}) in combat {combat.id}.")
                    # Возвращаем словарь, описывающий действие
                    return {'type': 'combat_attack', 'target_id': p_target_obj.entity_id, 'target_type': p_target_obj.entity_type, 'attack_type': 'basic_attack'}

        # Если не найдена цель или нет CombatManager, NPC может бездействовать
        print(f"RuleEngine: NPC {npc.id} not choosing combat action (no living targets or CombatManager not available).")
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
        original_roll_string = roll_string # Keep original for return

        # Attempt to get guild_id from context for logging, if available
        guild_id_for_log = "UNKNOWN_GUILD"
        if context and isinstance(context, dict) and 'guild_id' in context:
            guild_id_for_log = str(context['guild_id'])

        if self._game_log_manager:
            # Using await here as log_event is async
            await self._game_log_manager.log_event(
                guild_id=guild_id_for_log, # May be "UNKNOWN_GUILD" if not in context
                event_type="dice_roll_start",
                message=f"Attempting to resolve dice roll: '{original_roll_string}'.",
                metadata={"roll_string": original_roll_string}
            )

        # This method is now async, but random.randint is synchronous.
        # For a truly async dice roller (e.g., using an external service or for complex simulation),
        # this would involve `await` calls. For now, it's async for API consistency.
        
        # Using the parsing logic from the existing method, which is more complete
        # than the external dice_roller.py's current simple NdX+M.
        
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

        result_payload = {
            'roll_string': original_roll_string,
            'num_dice': num_dice,
            'dice_sides': calculated_dice_sides,
            'rolls': rolls,
            'modifier': modifier,
            'total': total,
        }

        if self._game_log_manager:
            await self._game_log_manager.log_event(
                guild_id=guild_id_for_log,
                event_type="dice_roll_result",
                message=f"Dice roll '{original_roll_string}' resolved. Total: {total}. Rolls: {rolls}, Mod: {modifier}.",
                metadata=result_payload # Log the full result
            )

        return result_payload

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
        Returns a dict with outcomes and a list of modified_entities.
        """
        modified_entities: List[Any] = []
        if not self._character_manager or not self._npc_manager or not self._status_manager:
            return {"success": False, "message": "Core managers not available in RuleEngine for spell processing.", "outcomes": [], "modified_entities": modified_entities}

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
                return {"success": False, "message": f"Spell '{spell.name}' requires a target, but none was provided or resolved.", "outcomes": [], "modified_entities": modified_entities}


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
                        if actual_target not in modified_entities: modified_entities.append(actual_target)
                        print(f"RuleEngine: Applied {actual_damage} {damage_type} damage to {target_id_for_effect}. New health: {actual_target.stats['health']}")
                        
                        if target_type_for_effect == "Character":
                            self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                        elif target_type_for_effect == "NPC":
                            self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)
                        
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
                        if actual_target not in modified_entities: modified_entities.append(actual_target)
                        
                        outcome_details["healed_amount"] = healed_amount # Store actual amount healed
                        print(f"RuleEngine: Applied {healed_amount} healing to {target_id_for_effect}. New health: {new_health}")

                        if target_type_for_effect == "Character":
                            self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                        elif target_type_for_effect == "NPC":
                            self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)
                    else:
                        outcome_details["message"] = "Target has no health attribute or target is invalid."
                        print(f"RuleEngine: Spell '{spell.name}' heal effect: Target {target_id_for_effect} has no health or is invalid.")

                elif effect_type == "apply_status_effect":
                    status_effect_id = effect_data.get('status_effect_id')
                    duration = effect_data.get('duration') # Can be None for default or permanent

                    if status_effect_id and target_id_for_effect and target_type_for_effect:
                        if not self._status_manager:
                             outcome_details["message"] = "StatusManager not available."
                             print(f"RuleEngine: Spell '{spell.name}' apply_status_effect: StatusManager not configured.")
                        else:
                            new_status_id = await self._status_manager.add_status_effect_to_entity(
                                guild_id=guild_id,
                                target_id=target_id_for_effect, # Corrected: was entity_id
                                target_type=target_type_for_effect, # Corrected: was entity_type
                                status_type=status_effect_id, # Assuming this is the status_type/template_id
                                duration=duration, # Corrected: was duration_seconds
                                source_id=caster_id,
                                **kwargs # Pass full context
                            )
                            if new_status_id and actual_target: # If status applied and target exists
                                if actual_target not in modified_entities: modified_entities.append(actual_target)
                                # StatusManager internally marks the new StatusEffect object dirty if needed.
                                # Character/NPC that received the status effect also needs to be marked dirty if its status_effects list changed.
                                if hasattr(actual_target, 'status_effects') and isinstance(actual_target.status_effects, list):
                                    if new_status_id not in actual_target.status_effects:
                                        actual_target.status_effects.append(new_status_id) # Add to list if not already (should be handled by StatusManager or entity)
                                if target_type_for_effect == "Character":
                                    self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                                elif target_type_for_effect == "NPC":
                                    self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)

                            outcome_details.update({"status_effect_id": status_effect_id, "duration": duration, "applied_status_instance_id": new_status_id})
                            print(f"RuleEngine: Applied status effect '{status_effect_id}' to {target_id_for_effect} for {duration}s. Instance ID: {new_status_id}")
                    else:
                        outcome_details["message"] = "Missing status_effect_id, target_id, or target_type."
                        print(f"RuleEngine: Spell '{spell.name}' apply_status_effect: Missing data: status_id={status_effect_id}, target_id={target_id_for_effect}, target_type={target_type_for_effect}")
                
                elif effect_type == "summon":
                    npc_archetype_id = effect_data.get('summon_npc_archetype_id')
                    count = effect_data.get('count', 1)
                    summon_location_id = getattr(caster, 'location_id', None)

                    if npc_archetype_id and summon_location_id and self._npc_manager:
                        summoned_npcs_ids = []
                        for _ in range(count):
                            # NpcManager.create_npc returns NPC ID string
                            new_npc_id = await self._npc_manager.create_npc( # Changed from create_npc_instance_from_template
                                guild_id=guild_id,
                                npc_template_id=npc_archetype_id, # This is the archetype_id
                                location_id=summon_location_id,
                                name=f"{spell.name}'s Summon", # Corrected: was name_override
                                is_temporary=True, # Summons are often temporary
                                owner_id=caster_id, # Optional: caster owns the summon
                                owner_type="Character" # Optional
                            )
                            if new_npc_id:
                                summoned_npcs_ids.append(new_npc_id)
                                new_npc_obj = self._npc_manager.get_npc(guild_id, new_npc_id)
                                if new_npc_obj and new_npc_obj not in modified_entities: modified_entities.append(new_npc_obj)
                                print(f"RuleEngine: Summoned NPC '{new_npc_id}' (Archetype: {npc_archetype_id}) at location {summon_location_id}.")
                            else:
                                print(f"RuleEngine: Failed to summon NPC of archetype {npc_archetype_id}.")
                        outcome_details.update({"npc_archetype_id": npc_archetype_id, "count": count, "summoned_ids": summoned_npcs_ids, "location_id": summon_location_id})
                    else:
                        outcome_details["message"] = "Missing npc_archetype_id, summon_location_id, or NpcManager."
                        print(f"RuleEngine: Spell '{spell.name}' summon effect: Missing data or NpcManager.")

                elif effect_type in ["buff_stat", "debuff_stat"]:
                    stat_to_modify = effect_data.get('stat')
                    amount = effect_data.get('amount')
                    duration = effect_data.get('duration', 60)

                    if stat_to_modify and amount is not None and target_id_for_effect and target_type_for_effect and self._status_manager:
                        status_effect_properties = {
                            "modifies_stat": stat_to_modify,
                            "modifier_amount": amount if effect_type == "buff_stat" else -amount,
                            "is_multiplier": effect_data.get("is_multiplier", False)
                        }
                        status_template_id_for_mod = effect_data.get("status_effect_template_id_override", f"mod_{stat_to_modify}_{'buff' if effect_type == 'buff_stat' else 'debuff'}")

                        new_status_id = await self._status_manager.add_status_effect_to_entity(
                            guild_id=guild_id,
                            target_id=target_id_for_effect, # Corrected
                            target_type=target_type_for_effect, # Corrected
                            status_type=status_template_id_for_mod, # Corrected: status_type
                            duration=duration, # Corrected
                            source_id=caster_id,
                            state_variables=status_effect_properties, # Pass as state_variables directly
                            **kwargs # Pass full context
                        )
                        if new_status_id and actual_target:
                            if actual_target not in modified_entities: modified_entities.append(actual_target)
                            # Mark target dirty as its status list might have changed (or StatusManager handles this)
                            if target_type_for_effect == "Character":
                                self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                            elif target_type_for_effect == "NPC":
                                self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)

                        outcome_details.update({
                            "stat_modified": stat_to_modify, 
                            "modification_amount": status_effect_properties["modifier_amount"], 
                            "duration": duration,
                            "applied_status_instance_id": new_status_id
                        })
                        print(f"RuleEngine: Applied {effect_type} to {stat_to_modify} for {target_id_for_effect} by {status_effect_properties['modifier_amount']} for {duration}s.")
                    else:
                        outcome_details["message"] = "Missing data for stat modification or StatusManager unavailable."
                        print(f"RuleEngine: Spell '{spell.name}' {effect_type} effect: Missing data or StatusManager.")
                
                else:
                    outcome_details["message"] = f"Unknown or unhandled spell effect type: '{effect_type}'."
                    print(f"RuleEngine: Warning: Unknown spell effect type '{effect_type}' in spell '{spell.name}'.")
            
            except Exception as e:
                print(f"RuleEngine: Error processing effect type '{effect_type}' for spell '{spell.name}': {e}")
                traceback.print_exc()
                outcome_details["error"] = str(e)
            
            outcomes.append(outcome_details)

        return {"success": True, "message": "Spell effects processed.", "outcomes": outcomes, "modified_entities": modified_entities}

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
        modified_entities: List[Any] = []
        if not self._character_manager or not self._npc_manager or not self._status_manager:
            return {"success": False, "message": "Core managers not available in RuleEngine for ability processing.", "outcomes": [], "modified_entities": modified_entities}

        outcomes: List[Dict[str, Any]] = []
        caster_id = getattr(caster, 'id', 'UnknownCaster')
        
        # Determine default target if none provided based on ability's target_type
        actual_target = target_entity
        if not actual_target and ability.target_type:
            if ability.target_type == "self":
                actual_target = caster
            # Add more complex target resolution if needed (e.g., for "area" effects originating from caster)
        
        if not actual_target and ability.target_type not in ["self", "no_target", "area_around_caster"]:
            return {"success": False, "message": f"Ability '{ability.name}' requires a target, but none was provided or resolved.", "outcomes": [], "modified_entities": modified_entities}

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
                        new_status_id = await self._status_manager.add_status_effect_to_entity(
                            guild_id=guild_id,
                            target_id=target_id_for_effect,
                            target_type=target_type_for_effect,
                            status_type=status_effect_id, # Assuming template ID
                            duration=duration,
                            source_id=caster_id,
                            **kwargs # Pass full context
                        )
                        if new_status_id and actual_target:
                            if actual_target not in modified_entities: modified_entities.append(actual_target)
                            if target_type_for_effect == "Character":
                                self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                            elif target_type_for_effect == "NPC":
                                self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)

                        outcome_details.update({"status_effect_id": status_effect_id, "duration": duration, "applied_status_instance_id": new_status_id})
                        print(f"RuleEngine (Ability): Applied status effect '{status_effect_id}' to {target_id_for_effect} for {duration}s.")
                    else:
                        outcome_details["message"] = "Missing status_effect_id, target, type, or StatusManager for apply_status_effect."
                        print(f"RuleEngine (Ability) apply_status_effect: Missing data or StatusManager. StatusID: {status_effect_id}, TargetID: {target_id_for_effect}, TargetType: {target_type_for_effect}")
                
                elif effect_type == "modify_stat":
                    stat_to_modify = effect_data.get('stat')
                    amount = effect_data.get('amount')
                    duration = effect_data.get('duration', 60)
                    status_template_id_for_mod = effect_data.get("status_effect_template_id", f"temp_mod_{stat_to_modify}")

                    if stat_to_modify and amount is not None and target_id_for_effect and target_type_for_effect and self._status_manager:
                        status_effect_properties = {
                            "modifies_stat": stat_to_modify,
                            "modifier_amount": amount,
                            "is_multiplier": effect_data.get("is_multiplier", False),
                            "modifier_type": effect_data.get("modifier_type", "flat")
                        }
                        new_status_id = await self._status_manager.add_status_effect_to_entity(
                            guild_id=guild_id,
                            target_id=target_id_for_effect,
                            target_type=target_type_for_effect,
                            status_type=status_template_id_for_mod, # Corrected
                            duration=duration, # Corrected
                            source_id=caster_id,
                            state_variables=status_effect_properties, # Corrected
                            **kwargs # Pass full context
                        )
                        if new_status_id and actual_target:
                            if actual_target not in modified_entities: modified_entities.append(actual_target)
                            if target_type_for_effect == "Character":
                                self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                            elif target_type_for_effect == "NPC":
                                self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)

                        outcome_details.update({"stat_modified": stat_to_modify, "modification_amount": amount, "duration": duration, "applied_status_instance_id": new_status_id})
                        print(f"RuleEngine (Ability): Applied temporary stat modification '{stat_to_modify}' to {target_id_for_effect} by {amount} for {duration}s.")
                    else:
                        outcome_details["message"] = "Missing data for modify_stat or StatusManager."
                        print(f"RuleEngine (Ability) modify_stat: Missing data or StatusManager. Stat: {stat_to_modify}, Amount: {amount}, TargetID: {target_id_for_effect}")

                elif effect_type == "grant_flag":
                    flag_to_grant = effect_data.get('flag')
                    if flag_to_grant and actual_target:
                        if not hasattr(actual_target, 'flags') or actual_target.flags is None:
                            print(f"RuleEngine (Ability): Target '{target_id_for_effect}' missing 'flags' attribute. Initializing.")
                            actual_target.flags = []
                        
                        if flag_to_grant not in actual_target.flags:
                            actual_target.flags.append(flag_to_grant)
                            if actual_target not in modified_entities: modified_entities.append(actual_target)
                            if target_type_for_effect == "Character":
                                self._character_manager.mark_character_dirty(guild_id, target_id_for_effect)
                            elif target_type_for_effect == "NPC":
                                self._npc_manager.mark_npc_dirty(guild_id, target_id_for_effect)
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
                        print(f"RuleEngine (Ability): Playing SFX '{sfx_id}' for ability '{ability.name}'.")
                    else:
                        outcome_details["message"] = "Missing sfx_id for play_sfx effect."
                
                elif effect_type == "deal_weapon_damage_modifier":
                    status_effect_id = effect_data.get("status_effect_id", f"empowered_attack_{ability.id}")
                    duration = effect_data.get("duration_seconds", 6)
                    
                    if self._status_manager and caster_id:
                        status_properties = {
                            "damage_multiplier": effect_data.get("damage_multiplier", 1.0),
                            "accuracy_penalty": effect_data.get("accuracy_penalty", 0),
                        }
                        new_status_id = await self._status_manager.add_status_effect_to_entity(
                            guild_id=guild_id,
                            target_id=caster_id,
                            target_type="Character",
                            status_type=status_effect_id, # Corrected
                            duration=duration, # Corrected
                            source_id=caster_id,
                            state_variables=status_properties, # Corrected
                            **kwargs # Pass full context
                        )
                        if new_status_id and caster: # Caster is the target here
                             if caster not in modified_entities: modified_entities.append(caster)
                             self._character_manager.mark_character_dirty(guild_id, caster_id)

                        outcome_details.update({
                            "status_applied_to_caster": status_effect_id, 
                            "details": status_properties,
                            "duration": duration,
                            "applied_status_instance_id": new_status_id
                        })
                        print(f"RuleEngine (Ability): Applied '{status_effect_id}' to caster {caster_id} for ability '{ability.name}'.")
                    else:
                        outcome_details["message"] = "StatusManager not available or caster_id missing for deal_weapon_damage_modifier."
                        print(f"RuleEngine (Ability) deal_weapon_damage_modifier: StatusManager or caster_id missing.")
                
                else:
                    outcome_details["message"] = f"Unknown or unhandled ability effect type: '{effect_type}'."
                    print(f"RuleEngine (Ability): Warning: Unknown ability effect type '{effect_type}' in ability '{ability.name}'.")
            
            except Exception as e:
                print(f"RuleEngine (Ability): Error processing effect type '{effect_type}' for ability '{ability.name}': {e}")
                traceback.print_exc()
                outcome_details["error"] = str(e)
            
            outcomes.append(outcome_details)

        return {"success": True, "message": "Ability effects processed.", "outcomes": outcomes, "modified_entities": modified_entities}

    # --- Core Combat and Skill Resolution Methods ---

    async def resolve_skill_check(
        self, 
        character: "Character", 
        skill_name: str, 
        difficulty_class: int, 
        situational_modifier: int = 0, 
        associated_stat: Optional[str] = None, # e.g., "strength" for Athletics
        **kwargs: Any
    ) -> tuple[bool, int, int, Optional[str]]:
        """
        Resolves a generic skill check for a character.
        Returns: (success: bool, total_skill_value: int, d20_roll: int, crit_status: Optional[str])
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
            skill_stat_map = self._rules_data.get("skill_rules", {}).get("skill_stat_map", {})
            associated_stat = skill_stat_map.get(skill_name.lower())

        if associated_stat:
            stat_value = character_stats.get(associated_stat, 10) # Default to 10 if stat not present
            stat_modifier = self._calculate_attribute_modifier(stat_value)

        try:
            roll_result_dict = await self._resolve_dice_roll("1d20", context=kwargs) # Pass context if _resolve_dice_roll uses it
            d20_roll = roll_result_dict['total']
        except ValueError: # Handle potential error from _resolve_dice_roll
            print(f"RuleEngine: Error resolving 1d20 for skill check. Defaulting roll to 10.")
            d20_roll = 10 # Fallback roll

        total_skill_value = d20_roll + skill_value + stat_modifier + situational_modifier

        crit_rules = self._rules_data.get("check_rules", {})
        crit_success_roll = crit_rules.get("critical_success", {}).get("natural_roll", 20)
        crit_failure_roll = crit_rules.get("critical_failure", {}).get("natural_roll", 1)

        crit_status: Optional[str] = None
        success: bool # Declare success here to be assigned in conditional block
        if d20_roll == crit_success_roll and crit_rules.get("critical_success", {}).get("auto_succeeds", True):
            success = True
            crit_status = "critical_success"
        elif d20_roll == crit_failure_roll and crit_rules.get("critical_failure", {}).get("auto_fails", True):
            success = False
            crit_status = "critical_failure"
        else:
            success = total_skill_value >= difficulty_class

        print(f"RuleEngine: Skill Check ({skill_name.capitalize()} DC {difficulty_class}): Roll={d20_roll}, SkillVal={skill_value}, StatMod({associated_stat or 'N/A'})={stat_modifier}, SitMod={situational_modifier} -> Total={total_skill_value}. Success: {success} (Crit: {crit_status})")
        return success, total_skill_value, d20_roll, crit_status

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
        stat_modifier = self._calculate_attribute_modifier(primary_stat_value)
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

        # crit_status: Optional[str] = None # Already defined
        # if d20_roll == 20:
        #     crit_status = "critical_hit"
        # elif d20_roll == 1:
        #     crit_status = "critical_miss"
        crit_rules = self._rules_data.get("check_rules", {})
        crit_success_roll = crit_rules.get("critical_success", {}).get("natural_roll", 20)
        crit_failure_roll = crit_rules.get("critical_failure", {}).get("natural_roll", 1)

        crit_status: Optional[str] = None
        if d20_roll == crit_success_roll:
            crit_status = "critical_hit"
            # hit = True # Crit success usually auto-hits, specific game rule
        elif d20_roll == crit_failure_roll:
            crit_status = "critical_miss"
            # hit = False # Crit failure usually auto-misses

        total_attack_value = d20_roll + attack_bonus + situational_modifiers
        
        hit = False
        if crit_status == "critical_hit": # If it's a critical hit (e.g. nat 20), it's a hit.
            hit = True
        elif crit_status == "critical_miss": # If it's a critical miss (e.g. nat 1), it's a miss.
            hit = False
        else: # Otherwise, compare total against AC.
            hit = total_attack_value >= defender_ac
            
        print(f"RuleEngine: Attack Roll ({attack_type}): AttackerBonus={attack_bonus}, DefenderAC={defender_ac} | Roll={d20_roll} -> Total={total_attack_value}. Hit: {hit} (Crit: {crit_status})")
        return hit, total_attack_value, d20_roll, crit_status

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
        stat_damage_modifier = self._calculate_attribute_modifier(attacker_stats.get("strength", 10)) # Example for melee
        # if weapon and weapon.type == "ranged": stat_damage_modifier = self._calculate_attribute_modifier(attacker_stats.get("dexterity", 10))
        # if spell: stat_damage_modifier = self._calculate_attribute_modifier(attacker_stats.get(spell.casting_stat, 10))
        
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

            damage_calc_rules = self._rules_data.get("combat_rules", {}).get("damage_calculation", {})
            resistances = damage_calc_rules.get("resistances", {}) # e.g. {"fire": 0.5}
            vulnerabilities = damage_calc_rules.get("vulnerabilities", {}) # e.g. {"cold": 1.5}
            immunities = damage_calc_rules.get("immunities", []) # e.g. ["poison"]

            if damage_type in immunities:
                total_damage = 0
                print(f"RuleEngine: Target is immune to {damage_type}.")
            else:
                if damage_type in resistances:
                    total_damage *= resistances[damage_type]
                if damage_type in vulnerabilities:
                    total_damage *= vulnerabilities[damage_type]

        final_damage = max(0, int(round(total_damage))) # Ensure damage is not negative and is an integer
        
        print(f"RuleEngine: Calculated Damage: BaseRoll='{base_damage_roll}', RolledDmg={rolled_damage}, StatMod={stat_damage_modifier}, Crit={is_critical_hit} -> FinalDmg={final_damage} ({damage_type})")
        return final_damage

    # --- Stubs for Other Key Missing Mechanics ---

    async def process_entity_death(self, entity: Any, killer: Optional[Any] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # entity is the one that died (Character or NPC model)
        # killer is Optional, could be another entity or environment
        # context should contain managers like item_manager, location_manager, etc.

        entity_name = getattr(entity, 'name_i18n', {}).get('en', getattr(entity, 'id', 'Unknown Entity'))
        entity_id = getattr(entity, 'id', 'UnknownID')
        entity_type = type(entity).__name__

        print(f"RuleEngine: Processing death for {entity_type} {entity_name} (ID: {entity_id})...")

        death_outcomes = {"message": f"{entity_name} has died."}

        killer_name = "Unknown Killer"
        killer_id = "N/A"
        killer_type_name = "N/A"

        if killer:
            killer_name = getattr(killer, 'name_i18n', {}).get('en', getattr(killer, 'id', 'Unknown Killer'))
            killer_id = getattr(killer, 'id', 'N/A')
            killer_type_name = type(killer).__name__
            death_outcomes["message"] += f" Slain by {killer_name}."

        # TODO: Implement actual death mechanics:
        # 1. Drop items (use item_manager from context to move items to location or killer)
        # 2. Create corpse item/marker (use item_manager/location_manager)
        # 3. Apply reputation changes (use relationship_manager from context)
        # 4. Trigger 'on_death' events/scripts associated with this entity type or specific entity.
        # 5. Determine XP rewards for killer if applicable.

        # Log the death
        game_log_mgr = context.get('game_log_manager') if context else None
        guild_id = context.get('guild_id') if context else None

        if game_log_mgr and guild_id:
            log_msg = f"{entity_name} (ID: {entity_id}, Type: {entity_type}) has died."
            if killer:
                log_msg += f" Slain by {killer_name} (ID: {killer_id}, Type: {killer_type_name})."

            related_entities_list = [{"id": str(entity_id), "type": entity_type}]
            if killer:
                related_entities_list.append({"id": str(killer_id), "type": killer_type_name})

            channel_id_for_log = None
            loc_mgr = context.get('location_manager') if context else None
            char_loc_id = getattr(entity, 'location_id', None)
            if loc_mgr and char_loc_id and guild_id:
                # Ensure get_location_instance is called correctly
                location_instance_data = loc_mgr.get_location_instance(guild_id=str(guild_id), instance_id=str(char_loc_id))
                if location_instance_data:
                     channel_id_for_log = location_instance_data.get('channel_id')

            try:
                # Ensure related_entities is passed as a JSON string if the method expects that.
                # Based on previous usage in exploration_cmds, it seems to expect a JSON string.
                # However, if game_log_manager.log_event can handle a list of dicts, that's cleaner.
                # For now, assuming it can handle a list of dicts. If not, json.dumps(related_entities_list)
                await game_log_mgr.log_event(
                    guild_id=str(guild_id),
                    event_type="entity_death",
                    message=log_msg,
                    related_entities=related_entities_list, # Passing as list of dicts
                    channel_id=channel_id_for_log,
                    metadata={"killer_details": getattr(killer, 'to_dict', lambda: str(killer))() if killer else None}
                )
            except Exception as log_e:
                print(f"RuleEngine: Error logging entity death: {log_e}")
                traceback.print_exc()

        return death_outcomes

    async def check_combat_end_conditions(self, combat: "Combat", context: Dict[str, Any]) -> bool:
        """
        Checks if the combat has met conditions to end (e.g., all members of one team defeated).
        This is a placeholder and should be implemented with actual game logic.
        """
        # Basic placeholder: Check if one team has no living participants
        if not combat or not combat.participants:
            return True # No participants, combat ends

        teams: Dict[str, List[CombatParticipant]] = {}
        for p in combat.participants:
            if isinstance(p, CombatParticipant) and p.hp > 0: # Consider only living participants
                team_id = getattr(p, 'team_id', 'default_team') # Assuming CombatParticipant might have a team_id
                if team_id not in teams:
                    teams[team_id] = []
                teams[team_id].append(p)

        # If only one team (or zero teams with living members) remains, combat ends.
        # This definition of "team" is loose; real logic would use factions or player vs NPC.
        # For now, if all living participants are on the same conceptual "team" (or no one is left), it ends.
        # A more robust check would compare distinct team_ids of living participants.

        living_teams_with_members = [team_id for team_id, members in teams.items() if members]

        if len(living_teams_with_members) <= 1:
            print(f"RuleEngine: Combat {combat.id} end condition met. Teams remaining with living members: {len(living_teams_with_members)}")
            return True

        return False

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

    async def award_experience(self, character: "Character", amount: int, source_type: str, guild_id: str, source_id: Optional[str] = None,  **kwargs: Any) -> None:
        char_id = getattr(character, 'id', 'UnknownCharacter')
        current_xp = getattr(character, 'experience', 0)

        # Placeholder: could use xp_awards from rules to scale 'amount' based on source_type
        # For example:
        # xp_awards_config = self._rules_data.get("experience_rules", {}).get("xp_awards", {})
        # if source_type == "combat" and source_id: # source_id could be CR of monster
        #    amount = int(amount * xp_awards_config.get("combat",{}).get("cr_scaling_factor", 1.0))

        if amount <= 0: # No XP to award or invalid amount
            # print(f"RuleEngine: No XP awarded to character {char_id} (Amount: {amount}).")
            return

        character.experience = current_xp + amount
        print(f"RuleEngine: Awarded {amount} XP to character {char_id} (Source: {source_type}). Total XP: {character.experience}")

        leveled_up = await self.check_for_level_up(character, guild_id, **kwargs)
        # check_for_level_up will mark dirty if level up occurs. If no level up, but XP changed, mark dirty here.
        if not leveled_up and self._character_manager:
            self._character_manager.mark_character_dirty(guild_id, char_id)


    async def check_for_level_up(self, character: "Character", guild_id: str, **kwargs: Any) -> bool:
        char_id = getattr(character, 'id', 'UnknownCharacter')
        xp_rules = self._rules_data.get("experience_rules", {})
        xp_to_level_config = xp_rules.get("xp_to_level_up", {})
        xp_table = xp_to_level_config.get("values", {}) # This should be like {"2": 1000, "3": 3000, ...}

        general_settings = self._rules_data.get("general_settings", {})
        max_level = general_settings.get("max_character_level", 20)

        if not hasattr(character, 'level'): character.level = 1
        if not hasattr(character, 'experience'): character.experience = 0

        leveled_up_this_check = False

        while getattr(character, 'level', 1) < max_level:
            current_level = getattr(character, 'level', 1)
            next_level_str = str(current_level + 1) # XP table is often indexed by the level to reach

            xp_needed_for_next = xp_table.get(next_level_str)
            # The GAME_RULES_STRUCTURE implies xp_table stores total XP to reach a level.
            # Example: Level 1 needs 0 XP. To reach Level 2, needs 1000 TOTAL XP. To reach Level 3, needs 3000 TOTAL XP.

            if xp_needed_for_next is None:
                print(f"RuleEngine: XP requirement for level {next_level_str} not found in rules. Cannot level up {char_id} further this way.")
                break

            if character.experience >= xp_needed_for_next:
                character.level = current_level + 1
                # No XP subtraction if table is total XP needed. If it were XP *from previous level*, then subtract.

                print(f"RuleEngine: Character {char_id} leveled up to level {character.level}!")
                leveled_up_this_check = True

                # Placeholder: Apply actual level up benefits (stats, skills, abilities)
                # This would likely call another method: await self.apply_level_up_benefits(character, guild_id, **kwargs)

                if self._character_manager: # Mark dirty for each level gained
                    self._character_manager.mark_character_dirty(guild_id, char_id)
            else:
                # Not enough XP for the *next* level
                break
        
        if leveled_up_this_check:
            print(f"RuleEngine: Character {char_id} finished level up checks. Current level: {character.level}, XP: {character.experience}")

        return leveled_up_this_check

    async def apply_combat_action_effects(
        self,
        combat: Combat, # Pass the Combat object directly
        actor_id: str,
        action_data: Dict[str, Any], # Contains action type, target, etc.
        context: Dict[str, Any] # Contains managers, rules_config, guild_id, current_game_time
    ) -> List[str]: # Returns a list of log messages summarizing effects
        """
        Applies the effects of a combat action using the new combat_rules module.
        Updates the Combat object passed in.
        """
        log_messages: List[str] = []

        # Extract necessary components from context
        character_manager: Optional['CharacterManager'] = context.get('character_manager')
        npc_manager: Optional['NpcManager'] = context.get('npc_manager')
        game_log_manager: Optional['GameLogManager'] = context.get('game_log_manager')
        status_manager: Optional['StatusManager'] = context.get('status_manager')
        item_manager: Optional['ItemManager'] = context.get('item_manager')
        spell_manager: Optional['SpellManager'] = context.get('spell_manager')
        skill_manager: Optional['SkillManager'] = context.get('skill_manager')

        rules_config: Optional[Dict[str, Any]] = context.get('rules_config') # This is settings["rules_config"]
        guild_id: Optional[str] = context.get('guild_id', combat.guild_id)
        current_game_time: float = context.get('current_game_time', 0.0)

        if not all([character_manager, npc_manager, game_log_manager, status_manager, item_manager, spell_manager, skill_manager, rules_config, guild_id is not None]):
            log_messages.append("RuleEngine Error: Missing required managers, rules_config, or guild_id in context for apply_combat_action_effects.")
            if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
            return log_messages

        if "guild_id" not in rules_config: # Ensure guild_id is in rules_config for combat_rules
             rules_config["guild_id"] = guild_id

        actor_participant_data = combat.get_participant_data(actor_id)
        if not actor_participant_data:
            log_messages.append(f"RuleEngine Error: Actor {actor_id} not found in combat {combat.id}.")
            if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
            return log_messages
        actor_type = actor_participant_data.entity_type
        actor_name = getattr(actor_participant_data, 'name', actor_id) # For logging

        action_type = action_data.get("type")
        log_messages.append(f"RuleEngine: Processing combat action '{action_type}' by {actor_name} ({actor_id}).")


        if action_type == "attack":
            target_id = action_data.get("target_id")
            if not target_id:
                log_messages.append(f"RuleEngine: Attack action by {actor_id} missing target_id.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
                return log_messages

            target_participant_data = combat.get_participant_data(target_id)
            if not target_participant_data:
                log_messages.append(f"RuleEngine Error: Target {target_id} not found in combat {combat.id}.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
                return log_messages
            target_type = target_participant_data.entity_type
            target_name = getattr(target_participant_data, 'name', target_id)

            log_messages.append(f"RuleEngine: {actor_name} ({actor_type}) attacks {target_name} ({target_type}).")

            attack_outcome = await combat_rules.process_attack(
                actor_id=actor_id,
                actor_type=actor_type,
                target_id=target_id,
                target_type=target_type,
                rules_config=rules_config, # This is settings["rules_config"]
                character_manager=character_manager,
                npc_manager=npc_manager,
                game_log_manager=game_log_manager
            )

            log_messages.extend(attack_outcome.get("log_messages", []))

            if attack_outcome.get("hit", False):
                # Update combat participant's HP directly from the combat object's data
                # The Combat object should be the source of truth for participant state during combat.
                current_target_hp = target_participant_data.hp
                new_target_hp = attack_outcome.get("target_hp_after", current_target_hp)
                target_participant_data.hp = new_target_hp

                # Log HP change
                hp_change_log = f"{target_name} HP: {current_target_hp} -> {new_target_hp} (Damage: {attack_outcome.get('damage_dealt', 0)})."
                log_messages.append(hp_change_log)
                if game_log_manager: await game_log_manager.add_log_entry(hp_change_log, "combat_flow")


                if new_target_hp <= 0:
                    log_messages.append(f"{target_name} has been defeated.")
                    # Further death processing (e.g., marking as defeated in combat, XP) would be handled by CombatManager
                    # or a subsequent call based on this outcome. RuleEngine focuses on direct effects.
                    target_participant_data.is_alive = False # Mark as not alive in combat data

            combat.update_participant_data(target_id, target_participant_data) # Persist changes to combat object

        elif action_type == "cast_spell":
            spell_id = action_data.get("spell_id")
            target_id = action_data.get("target_id") # Spells can have targets

            if not spell_id:
                log_messages.append(f"RuleEngine: Cast spell action by {actor_id} missing spell_id.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
                return log_messages

            spell_template = await spell_manager.get_spell(guild_id, spell_id)
            if not spell_template:
                log_messages.append(f"RuleEngine: Spell template {spell_id} not found for guild {guild_id}.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
                return log_messages

            log_messages.append(f"{actor_name} attempts to cast {spell_template.name}.")

            # Spell effects are defined in spell_template.effects
            if hasattr(spell_template, 'effects') and spell_template.effects:
                for effect_detail in spell_template.effects:
                    effect_type = effect_detail.get("type")

                    current_target_id_for_effect = target_id
                    if effect_detail.get("target_rule") == "self":
                        current_target_id_for_effect = actor_id

                    # Some effects might not need a specific target initially (e.g. AoE centered on caster)
                    if not current_target_id_for_effect and effect_type not in ["area_effect_no_target"]: # Example of an effect type that might not need initial target
                        log_messages.append(f"RuleEngine: Spell '{spell_template.name}' effect type '{effect_type}' requires a target, but none specified or resolved.")
                        if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "warning_rule_engine")
                        continue

                    target_participant_for_effect = None
                    target_type_for_effect = None
                    if current_target_id_for_effect: # Ensure we have a target ID before trying to get participant data
                        target_participant_for_effect = combat.get_participant_data(current_target_id_for_effect)
                        if not target_participant_for_effect:
                            log_messages.append(f"RuleEngine: Target participant {current_target_id_for_effect} for spell '{spell_template.name}' effect not found in combat.")
                            if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "warning_rule_engine")
                            continue
                        target_type_for_effect = target_participant_for_effect.entity_type

                    if effect_type == "damage" and current_target_id_for_effect and target_type_for_effect:
                        damage_amount_str = effect_detail.get("amount", "0")
                        damage_type_str = effect_detail.get("damage_type", "arcane") # Default to arcane for spells

                        damage_outcome = await combat_rules.process_direct_damage(
                            actor_id=actor_id, # Spell caster is the source/actor of damage
                            actor_type=actor_type,
                            target_id=current_target_id_for_effect,
                            target_type=target_type_for_effect,
                            damage_amount_str=damage_amount_str,
                            damage_type=damage_type_str,
                            rules_config=rules_config,
                            character_manager=character_manager,
                            npc_manager=npc_manager,
                            game_log_manager=game_log_manager
                        )
                        log_messages.extend(damage_outcome.get("log_messages", []))
                        if damage_outcome.get("damage_dealt", 0) > 0 and target_participant_for_effect:
                            target_participant_for_effect.hp = damage_outcome.get("target_hp_after", target_participant_for_effect.hp)
                            if target_participant_for_effect.hp <= 0:
                                target_participant_for_effect.is_alive = False
                                log_messages.append(f"{target_participant_for_effect.name} was defeated by spell damage!")
                            # Combat object is mutated directly; CombatManager will save it.

                    elif effect_type == "heal" and current_target_id_for_effect and target_type_for_effect:
                        heal_amount_str = effect_detail.get("amount", "0")
                        heal_outcome = await combat_rules.process_healing(
                            target_id=current_target_id_for_effect,
                            target_type=target_type_for_effect,
                            heal_amount_str=heal_amount_str,
                            rules_config=rules_config,
                            character_manager=character_manager,
                            npc_manager=npc_manager,
                            game_log_manager=game_log_manager
                        )
                        log_messages.extend(heal_outcome.get("log_messages", []))
                        if heal_outcome.get("healing_done", 0) > 0 and target_participant_for_effect:
                            target_participant_for_effect.hp = heal_outcome.get("target_hp_after", target_participant_for_effect.hp)
                            # Combat object is mutated directly

                    elif effect_type == "status_effect" and current_target_id_for_effect and target_type_for_effect:
                        status_template_id = effect_detail.get("status_template_id")
                        if status_template_id:
                            status_applied = await combat_rules.apply_status_effect(
                                 target_id=current_target_id_for_effect,
                                 target_type=target_type_for_effect,
                                 status_template_id=status_template_id,
                                 rules_config=rules_config,
                                 status_manager=status_manager,
                                 character_manager=character_manager,
                                 npc_manager=npc_manager,
                                 game_log_manager=game_log_manager,
                                 source_id=actor_id,
                                 source_type=actor_type,
                                 duration_override_rounds=effect_detail.get("duration_rounds"),
                                 requires_save_info=effect_detail.get("requires_save_info"),
                                 current_game_time=current_game_time
                             )
                            log_msg_status = f"Spell '{spell_template.name}' attempted to apply status '{status_template_id}' to {target_participant_for_effect.name if target_participant_for_effect else current_target_id_for_effect}: {'Processed (applied or resisted)' if status_applied else 'Failed (e.g. invalid input to apply_status_effect)'}"
                            log_messages.append(log_msg_status)
                        else:
                            log_messages.append(f"RuleEngine: Spell '{spell_template.name}' status_effect detail missing 'status_template_id'.")
                            if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "warning_rule_engine")
                    else:
                        log_messages.append(f"RuleEngine: Spell '{spell_template.name}' has unhandled effect type '{effect_type}' or missing target information for the effect.")
                        if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "warning_rule_engine")
            else:
                log_messages.append(f"RuleEngine: Spell '{spell_template.name}' has no defined effects.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "info_rule_engine")

        elif action_type == "use_skill":
            skill_id = action_data.get("skill_id")
            target_id = action_data.get("target_id") # Skills can have targets

            if not skill_id:
                log_messages.append(f"RuleEngine: Use skill action by {actor_id} missing skill_id.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
                return log_messages

            skill_template: Optional['Skill'] = await skill_manager.get_skill_template(guild_id, skill_id)

            if not skill_template:
                log_messages.append(f"RuleEngine: Skill template {skill_id} not found for guild {guild_id}.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
                return log_messages

            skill_name = skill_template.name_i18n.get('en', skill_id)
            log_messages.append(f"{actor_name} uses skill: {skill_name}.")

            if skill_template.effects:
                for effect_detail in skill_template.effects:
                    effect_type = effect_detail.get("type")

                    current_target_id_for_effect = target_id
                    if effect_detail.get("target_rule") == "self": # Example target rule for skills
                        current_target_id_for_effect = actor_id

                    if not current_target_id_for_effect and effect_type not in ["area_effect_no_target"]:
                        log_messages.append(f"RuleEngine: Skill '{skill_name}' effect type '{effect_type}' requires a target.")
                        if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "warning_rule_engine")
                        continue

                    target_participant_for_effect = None
                    target_type_for_effect = None
                    if current_target_id_for_effect:
                        target_participant_for_effect = combat.get_participant_data(current_target_id_for_effect)
                        if not target_participant_for_effect:
                            log_messages.append(f"RuleEngine: Target {current_target_id_for_effect} for skill '{skill_name}' effect not found in combat.")
                            if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "warning_rule_engine")
                            continue
                        target_type_for_effect = target_participant_for_effect.entity_type

                    if effect_type == "damage" and current_target_id_for_effect and target_type_for_effect:
                        damage_amount_str = effect_detail.get("amount", "0")
                        damage_type_str = effect_detail.get("damage_type", "physical")

                        # Base damage from dice string
                        damage_outcome = await combat_rules.process_direct_damage(
                            actor_id=actor_id, actor_type=actor_type,
                            target_id=current_target_id_for_effect, target_type=target_type_for_effect,
                            damage_amount_str=damage_amount_str, damage_type=damage_type_str,
                            rules_config=rules_config, character_manager=character_manager,
                            npc_manager=npc_manager, game_log_manager=game_log_manager
                        )

                        current_total_damage = damage_outcome.get("damage_dealt", 0.0)
                        log_messages.extend(damage_outcome.get("log_messages", []))

                        # Add stat modifier bonus if specified by skill effect
                        if effect_detail.get("add_primary_stat_modifier", False): # e.g. {"add_primary_stat_modifier": true, "primary_stat": "strength"}
                            primary_stat_for_damage = effect_detail.get("primary_stat", "strength") # Default to strength
                            actor_entity = None
                            if actor_type == "Character": actor_entity = await character_manager.get_character(guild_id, actor_id)
                            elif actor_type == "NPC": actor_entity = await npc_manager.get_npc(guild_id, actor_id)

                            if actor_entity and hasattr(actor_entity, 'stats'):
                                stat_val = actor_entity.stats.get(primary_stat_for_damage, 10)
                                stat_mod_damage = self._calculate_attribute_modifier(stat_val) # Use existing helper
                                current_total_damage += stat_mod_damage
                                log_messages.append(f"Skill '{skill_name}' adding {stat_mod_damage} from {primary_stat_for_damage} to damage.")

                        if current_total_damage > 0 and target_participant_for_effect:
                            # Recalculate HP based on potentially modified total damage
                            hp_after_dice_damage = damage_outcome.get("target_hp_after", target_participant_for_effect.hp)
                            # If stat mod was added, it means previous damage_dealt was only dice. We need to apply the stat_mod part now.
                            # The damage_outcome.target_hp_after already reflects dice damage.
                            # So, we subtract the additional stat_mod_damage from this HP.
                            final_hp = hp_after_dice_damage - (current_total_damage - damage_outcome.get("damage_dealt", 0.0))

                            target_participant_for_effect.hp = max(0, final_hp) # Ensure HP doesn't go below 0 from this adjustment
                            damage_outcome["target_hp_after"] = target_participant_for_effect.hp # Update for logging
                            damage_outcome["damage_dealt"] = current_total_damage # Update total damage dealt

                            if target_participant_for_effect.hp <= 0:
                                target_participant_for_effect.is_alive = False
                                log_messages.append(f"{target_participant_for_effect.name} was defeated by skill '{skill_name}'!")
                        # Log updated damage
                        if game_log_manager and current_total_damage != damage_outcome.get("damage_dealt", 0.0): # If stat mod changed damage
                             await game_log_manager.add_log_entry(f"Skill '{skill_name}' total damage on {target_participant_for_effect.name}: {current_total_damage}", "combat_skill_damage")


                    elif effect_type == "heal" and current_target_id_for_effect and target_type_for_effect:
                        heal_amount_str = effect_detail.get("amount", "0")
                        heal_outcome = await combat_rules.process_healing(
                            target_id=current_target_id_for_effect, target_type=target_type_for_effect,
                            heal_amount_str=heal_amount_str, rules_config=rules_config,
                            character_manager=character_manager, npc_manager=npc_manager, game_log_manager=game_log_manager
                        )
                        log_messages.extend(heal_outcome.get("log_messages", []))
                        if heal_outcome.get("healing_done", 0) > 0 and target_participant_for_effect:
                            target_participant_for_effect.hp = heal_outcome.get("target_hp_after", target_participant_for_effect.hp)

                    elif effect_type == "status_effect" and current_target_id_for_effect and target_type_for_effect:
                        status_template_id = effect_detail.get("status_template_id")
                        if status_template_id:
                            status_applied = await combat_rules.apply_status_effect(
                                 target_id=current_target_id_for_effect, target_type=target_type_for_effect,
                                 status_template_id=status_template_id, rules_config=rules_config,
                                 status_manager=status_manager, character_manager=character_manager,
                                 npc_manager=npc_manager, game_log_manager=game_log_manager,
                                 source_id=actor_id, source_type=actor_type,
                                 duration_override_rounds=effect_detail.get("duration_rounds"),
                                 requires_save_info=effect_detail.get("requires_save_info"),
                                 current_game_time=current_game_time
                             )
                            log_msg = f"Skill '{skill_name}' attempted to apply status '{status_template_id}' to {target_participant_for_effect.name if target_participant_for_effect else current_target_id_for_effect}: {'Processed' if status_applied else 'Failed'}"
                            log_messages.append(log_msg)
                        else:
                            log_messages.append(f"RuleEngine: Skill '{skill_name}' status_effect detail missing 'status_template_id'.")
                            if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "warning_rule_engine")
                    else:
                        log_messages.append(f"RuleEngine: Skill '{skill_name}' has unhandled effect type '{effect_type}'.")
                        if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "warning_rule_engine")
            else:
                log_messages.append(f"RuleEngine: Skill '{skill_name}' has no defined effects.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "info_rule_engine")

        elif action_type == "use_item":
            item_instance_id = action_data.get("item_instance_id") # This is the ID of the item IN THE INVENTORY
            explicit_target_id = action_data.get("target_id") # Target specified in the command

            if not item_instance_id:
                log_messages.append(f"RuleEngine: 'use_item' action by {actor_id} missing item_instance_id.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
                return log_messages

            # Call ItemManager to handle item usage and consumption
            item_use_outcome = await item_manager.use_item_in_combat(
                guild_id=guild_id,
                actor_id=actor_id,
                item_instance_id=item_instance_id,
                target_id=explicit_target_id,
                game_log_manager=game_log_manager
            )

            log_messages.append(item_use_outcome.get("message", f"Processing use of item {item_instance_id}."))

            if item_use_outcome.get("success") and item_use_outcome.get("consumed"):
                effects_to_apply = item_use_outcome.get("effects", [])
                item_name_for_log = item_use_outcome.get("item_name", item_instance_id)

                for effect_detail in effects_to_apply:
                    effect_type = effect_detail.get("type")

                    target_for_this_effect_id = item_use_outcome.get("resolved_target_id", actor_id)
                    if effect_detail.get("target_rule") == "self":
                        target_for_this_effect_id = actor_id
                    elif effect_detail.get("target_rule") == "chosen_target" and explicit_target_id:
                        target_for_this_effect_id = explicit_target_id

                    if not target_for_this_effect_id:
                        log_messages.append(f"RuleEngine: Item '{item_name_for_log}' effect '{effect_type}' could not determine target.")
                        continue

                    target_participant_for_effect = combat.get_participant_data(target_for_this_effect_id)
                    if not target_participant_for_effect:
                        log_messages.append(f"RuleEngine: Target {target_for_this_effect_id} for item '{item_name_for_log}' effect not found in combat.")
                        continue
                    target_type_for_effect = target_participant_for_effect.entity_type

                    if effect_type == "damage" and target_type_for_effect:
                        damage_outcome = await combat_rules.process_direct_damage(
                            actor_id=actor_id, actor_type=actor_type,
                            target_id=target_for_this_effect_id, target_type=target_type_for_effect,
                            damage_amount_str=effect_detail.get("amount", "0"),
                            damage_type=effect_detail.get("damage_type", "physical"),
                            rules_config=rules_config, character_manager=character_manager,
                            npc_manager=npc_manager, game_log_manager=game_log_manager
                        )
                        log_messages.extend(damage_outcome.get("log_messages", []))
                        if damage_outcome.get("damage_dealt", 0) > 0:
                            target_participant_for_effect.hp = damage_outcome.get("target_hp_after", target_participant_for_effect.hp)
                            if target_participant_for_effect.hp <= 0:
                                target_participant_for_effect.is_alive = False
                                log_messages.append(f"{target_participant_for_effect.name} was defeated by item damage!")
                        if game_log_manager:
                            details = {
                                "user_id": actor_id, "user_type": actor_type, "user_name": actor_name,
                                "item_name": item_name_for_log, "item_instance_id": item_instance_id,
                                "effect_detail": effect_detail,
                                "target_id": target_for_this_effect_id, "target_type": target_type_for_effect,
                                "target_name": target_participant_for_effect.name if target_participant_for_effect else target_for_this_effect_id,
                                "damage_dealt": damage_outcome.get("damage_dealt", 0),
                                "target_hp_after": damage_outcome.get("target_hp_after"),
                                "summary_logs_from_rule": damage_outcome.get("log_messages", [])
                            }
                            await game_log_manager.log_event(
                                guild_id, "COMBAT_ITEM_EFFECT_DAMAGE", details, player_id=actor_id if actor_type == "Character" else None
                            )

                    elif effect_type == "heal" and target_type_for_effect:
                        heal_outcome = await combat_rules.process_healing(
                            target_id=target_for_this_effect_id, target_type=target_type_for_effect,
                            heal_amount_str=effect_detail.get("amount", "0"), rules_config=rules_config,
                            character_manager=character_manager, npc_manager=npc_manager, game_log_manager=game_log_manager
                        )
                        log_messages.extend(heal_outcome.get("log_messages", []))
                        if heal_outcome.get("healing_done", 0) > 0:
                            target_participant_for_effect.hp = heal_outcome.get("target_hp_after", target_participant_for_effect.hp)
                        if game_log_manager:
                            details = {
                                "user_id": actor_id, "user_type": actor_type, "user_name": actor_name,
                                "item_name": item_name_for_log, "item_instance_id": item_instance_id,
                                "effect_detail": effect_detail,
                                "target_id": target_for_this_effect_id, "target_type": target_type_for_effect,
                                "target_name": target_participant_for_effect.name if target_participant_for_effect else target_for_this_effect_id,
                                "healing_done": heal_outcome.get("healing_done", 0),
                                "target_hp_after": heal_outcome.get("target_hp_after"),
                                "summary_logs_from_rule": heal_outcome.get("log_messages", [])
                            }
                            await game_log_manager.log_event(
                                guild_id, "COMBAT_ITEM_EFFECT_HEAL", details, player_id=actor_id if actor_type == "Character" else None
                            )

                    elif effect_type == "status_effect" and target_type_for_effect:
                        status_template_id = effect_detail.get("status_template_id")
                        if status_template_id:
                            status_applied_outcome = await combat_rules.apply_status_effect( # Ensure this returns the dict
                                 target_id=target_for_this_effect_id, target_type=target_type_for_effect,
                                 status_template_id=status_template_id, rules_config=rules_config,
                                 status_manager=status_manager, character_manager=character_manager,
                                 npc_manager=npc_manager, game_log_manager=game_log_manager,
                                 source_id=actor_id, source_type=actor_type,
                                 duration_override_rounds=effect_detail.get("duration_rounds"),
                                 requires_save_info=effect_detail.get("requires_save_info"),
                                 current_game_time=current_game_time
                             )
                            log_messages.extend(status_applied_outcome.get("log_messages", []))
                            if game_log_manager:
                                details = {
                                    "user_id": actor_id, "user_type": actor_type, "user_name": actor_name,
                                    "item_name": item_name_for_log, "item_instance_id": item_instance_id,
                                    "effect_detail": effect_detail,
                                    "target_id": target_for_this_effect_id, "target_type": target_type_for_effect,
                                    "target_name": target_participant_for_effect.name if target_participant_for_effect else target_for_this_effect_id,
                                    "status_template_id": status_template_id,
                                    "processed_successfully": status_applied_outcome.get("success", False),
                                    "actually_applied_or_resisted": status_applied_outcome.get("status_actually_applied_or_resisted", False),
                                    "summary_logs_from_rule": status_applied_outcome.get("log_messages", [])
                                }
                                await game_log_manager.log_event(
                                    guild_id, "COMBAT_ITEM_EFFECT_STATUS", details, player_id=actor_id if actor_type == "Character" else None
                                )
                        else:
                            log_messages.append(f"RuleEngine: Item '{item_name_for_log}' status_effect detail missing 'status_template_id'.")
                    else:
                        log_messages.append(f"RuleEngine: Item '{item_name_for_log}' has unhandled effect type '{effect_type}'.")
            elif not item_use_outcome.get("success"):
                pass

        else:
            log_messages.append(f"RuleEngine: Unknown or unsupported action type '{action_type}' for actor {actor_id}.")
            if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
            explicit_target_id = action_data.get("target_id")

            if not item_instance_id:
                log_messages.append(f"RuleEngine: 'use_item' action by {actor_id} missing item_instance_id.")
                if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")
                return log_messages

            item_use_outcome = await item_manager.use_item_in_combat(
                guild_id=guild_id,
                actor_id=actor_id,
                item_instance_id=item_instance_id,
                target_id=explicit_target_id,
                game_log_manager=game_log_manager
            )

            log_messages.append(item_use_outcome.get("message", f"Processing use of item {item_instance_id}."))

            if item_use_outcome.get("success") and item_use_outcome.get("consumed"):
                effects_to_apply = item_use_outcome.get("effects", [])
                item_name_for_log = item_use_outcome.get("item_name", item_instance_id)

                for effect_detail in effects_to_apply:
                    effect_type = effect_detail.get("type")

                    target_for_this_effect_id = item_use_outcome.get("resolved_target_id", actor_id)
                    if effect_detail.get("target_rule") == "self":
                        target_for_this_effect_id = actor_id
                    elif effect_detail.get("target_rule") == "chosen_target" and explicit_target_id:
                        target_for_this_effect_id = explicit_target_id

                    if not target_for_this_effect_id:
                        log_messages.append(f"RuleEngine: Item '{item_name_for_log}' effect '{effect_type}' could not determine target.")
                        continue

                    target_participant_for_effect = combat.get_participant_data(target_for_this_effect_id)
                    if not target_participant_for_effect:
                        log_messages.append(f"RuleEngine: Target {target_for_this_effect_id} for item '{item_name_for_log}' effect not found in combat.")
                        continue
                    target_type_for_effect = target_participant_for_effect.entity_type

                    if effect_type == "damage" and target_type_for_effect:
                        damage_outcome = await combat_rules.process_direct_damage(
                            actor_id=actor_id, actor_type=actor_type,
                            target_id=target_for_this_effect_id, target_type=target_type_for_effect,
                            damage_amount_str=effect_detail.get("amount", "0"),
                            damage_type=effect_detail.get("damage_type", "physical"),
                            rules_config=rules_config, character_manager=character_manager,
                            npc_manager=npc_manager, game_log_manager=game_log_manager
                        )
                        log_messages.extend(damage_outcome.get("log_messages", []))
                        if damage_outcome.get("damage_dealt", 0) > 0:
                            target_participant_for_effect.hp = damage_outcome.get("target_hp_after", target_participant_for_effect.hp)
                            if target_participant_for_effect.hp <= 0:
                                target_participant_for_effect.is_alive = False
                                log_messages.append(f"{target_participant_for_effect.name} was defeated by item damage!")

                    elif effect_type == "heal" and target_type_for_effect:
                        heal_outcome = await combat_rules.process_healing(
                            target_id=target_for_this_effect_id, target_type=target_type_for_effect,
                            heal_amount_str=effect_detail.get("amount", "0"), rules_config=rules_config,
                            character_manager=character_manager, npc_manager=npc_manager, game_log_manager=game_log_manager
                        )
                        log_messages.extend(heal_outcome.get("log_messages", []))
                        if heal_outcome.get("healing_done", 0) > 0:
                            target_participant_for_effect.hp = heal_outcome.get("target_hp_after", target_participant_for_effect.hp)

                    elif effect_type == "status_effect" and target_type_for_effect:
                        status_template_id = effect_detail.get("status_template_id")
                        if status_template_id:
                            status_applied = await combat_rules.apply_status_effect(
                                 target_id=target_for_this_effect_id, target_type=target_type_for_effect,
                                 status_template_id=status_template_id, rules_config=rules_config,
                                 status_manager=status_manager, character_manager=character_manager,
                                 npc_manager=npc_manager, game_log_manager=game_log_manager,
                                 source_id=actor_id, source_type=actor_type,
                                 duration_override_rounds=effect_detail.get("duration_rounds"),
                                 requires_save_info=effect_detail.get("requires_save_info"),
                                 current_game_time=current_game_time
                             )
                            log_msg = f"Item '{item_name_for_log}' attempted to apply status '{status_template_id}' to {target_participant_for_effect.name}: {'Processed' if status_applied else 'Failed'}"
                            log_messages.append(log_msg)
                        else:
                            log_messages.append(f"RuleEngine: Item '{item_name_for_log}' status_effect detail missing 'status_template_id'.")
                    else:
                        log_messages.append(f"RuleEngine: Item '{item_name_for_log}' has unhandled effect type '{effect_type}'.")
            elif not item_use_outcome.get("success"):
                pass # Message already added from item_use_outcome

            else:
             log_messages.append(f"RuleEngine: Unknown or unsupported action type '{action_type}' for actor {actor_id}.")
            if game_log_manager: await game_log_manager.add_log_entry(log_messages[-1], "error_rule_engine")

        if game_log_manager:
            summary_log = f"RuleEngine: Finished processing action '{action_type}' for {actor_name}. Summary: {', '.join(log_messages[-3:])}" # Log last few messages
            await game_log_manager.add_log_entry(summary_log, "combat_flow_summary")

        return log_messages

    async def calculate_initiative(self, combatants: List[Union["Character", "NPC"]], guild_id: str, **kwargs: Any) -> List[tuple[str, int]]:
        print(f"RuleEngine: Calculating initiative for {len(combatants)} combatants using configured formula.")
        initiative_list: List[tuple[str, float]] = [] # Store float for precision with tie_breaker

        combat_rules = self._rules_data.get("combat_rules", {})
        formula_str = combat_rules.get("initiative_formula", "dexterity_modifier") # Default to dex_mod
        tie_breaker_roll_str = combat_rules.get("initiative_tie_breaker_die", "1d4")
        initiative_base_die = combat_rules.get("initiative_base_die_roll", "1d20")

        for i, combatant in enumerate(combatants):
            combatant_id = getattr(combatant, 'id', f"unknown_combatant_{i}")
            entity_stats = getattr(combatant, 'stats', {})
            if not isinstance(entity_stats, dict): entity_stats = {}

            calculated_initiative_from_formula = 0.0 # Use float for potential division

            # Simplified formula parsing: "stat1_modifier [+-] stat2_modifier/K [+-] K2"
            # Handles terms separated by '+' or '-', with optional division by a constant for a term.
            # Example: "dexterity_modifier + wisdom_modifier / 2 - 1"

            # Normalize formula: remove spaces and ensure it starts with a sign for parsing
            normalized_formula = formula_str.replace(" ", "")
            if not (normalized_formula.startswith('+') or normalized_formula.startswith('-')):
                normalized_formula = '+' + normalized_formula

            # Split by operators while keeping them
            tokens = re.split(r'([+\-])', normalized_formula)
            if not tokens[0]: # If starts with an operator, re.split might produce an empty first element
                tokens = tokens[1:]

            current_value = 0.0
            idx = 0
            while idx < len(tokens):
                operator = tokens[idx]
                term_str = tokens[idx+1]
                idx += 2

                term_val = 0.0
                term_parts = term_str.split('/')
                main_term = term_parts[0]
                divisor = 1.0

                if len(term_parts) > 1:
                    try:
                        divisor = float(term_parts[1])
                        if divisor == 0:
                            print(f"RuleEngine: Warning: Division by zero in initiative formula term: {term_str}. Ignoring division.")
                            divisor = 1.0
                    except ValueError:
                        print(f"RuleEngine: Warning: Could not parse divisor in initiative formula term: {term_str}. Ignoring division.")

                if "_modifier" in main_term:
                    stat_name = main_term.split("_modifier")[0]
                    stat_value = entity_stats.get(stat_name, 10)
                    term_val = float(self._calculate_attribute_modifier(stat_value))
                else:
                    try:
                        term_val = float(main_term) # If it's a constant
                    except ValueError:
                        print(f"RuleEngine: Warning: Could not parse constant in initiative formula term: {main_term}")

                term_val /= divisor

                if operator == '+':
                    current_value += term_val
                elif operator == '-':
                    current_value -= term_val

            calculated_initiative_from_formula = current_value

            tie_breaker_value = 0.0
            if tie_breaker_roll_str:
                try:
                    roll_res = await self.resolve_dice_roll(tie_breaker_roll_str, context=kwargs) # resolve_dice_roll is already async
                    tie_breaker_value = float(roll_res.get('total', 0))
                except ValueError:
                    print(f"RuleEngine: Warning: Invalid tie_breaker_die format '{tie_breaker_roll_str}'. Defaulting to random float.")
                    tie_breaker_value = random.random()

            base_roll_obj = await self.resolve_dice_roll(initiative_base_die, context=kwargs) # resolve_dice_roll is already async
            d_roll_value = base_roll_obj.get('total', 10)

            initiative_score = float(d_roll_value) + calculated_initiative_from_formula + (tie_breaker_value / 100.0)

            initiative_list.append((combatant_id, initiative_score))
        
        initiative_list.sort(key=lambda x: x[1], reverse=True)

        final_initiative_list = [(id_val, int(round(score))) for id_val, score in initiative_list]

        print(f"RuleEngine: Initiative order: {final_initiative_list}")
        return final_initiative_list

    async def apply_equipment_effects(self, character: "Character", item_data: Dict[str, Any], equipping: bool, guild_id: str, **kwargs: Any) -> None:
        char_id = getattr(character, 'id', 'UnknownCharacter')
        item_id = item_data.get('id', 'UnknownItem')
        item_template_id = item_data.get('template_id')

        action = "equipping" if equipping else "unequipping"
        print(f"RuleEngine: Applying equipment effects for character {char_id} {action} item {item_id} (Template: {item_template_id}).")

        if not self._item_manager:
            print("RuleEngine: ItemManager not available. Cannot apply equipment effects.")
            return
        if not item_template_id:
            print("RuleEngine: Item template ID missing. Cannot apply equipment effects.")
            return

        item_template = self._item_manager.get_item_template(guild_id, item_template_id)
        if not item_template:
            print(f"RuleEngine: Item template {item_template_id} not found.")
            return

        properties = getattr(item_template, 'properties', {})
        if not isinstance(properties, dict): properties = {}

        bonuses = properties.get("bonuses") # Expecting format like {"strength": 1, "stealth_skill": 5, "armor_class": 2}

        if not bonuses or not isinstance(bonuses, dict):
            # print(f"RuleEngine: No valid bonuses found on item {item_template_id} for {action}.")
            return

        # Ensure character has stats and skills attributes
        if not hasattr(character, 'stats') or not isinstance(character.stats, dict):
            character.stats = {}
        if not hasattr(character, 'skills') or not isinstance(character.skills, dict):
            character.skills = {} # Assuming skills are Dict[str, int]

        for key, value in bonuses.items():
            try:
                bonus_value = int(value)
                multiplier = 1 if equipping else -1

                if key in character.stats:
                    character.stats[key] = character.stats.get(key, 0) + (bonus_value * multiplier)
                    print(f"RuleEngine: {action} item {item_id} changed stat {key} by {bonus_value * multiplier} for char {char_id}. New value: {character.stats[key]}")
                elif key.endswith("_skill") and key.split("_skill")[0] in self._rules_data.get("skill_rules", {}).get("skill_stat_map", {}):
                    skill_name = key.split("_skill")[0]
                    character.skills[skill_name] = character.skills.get(skill_name, 0) + (bonus_value * multiplier)
                    print(f"RuleEngine: {action} item {item_id} changed skill {skill_name} by {bonus_value * multiplier} for char {char_id}. New value: {character.skills[skill_name]}")
                elif key == "armor_class": # AC is often a direct bonus, not a base stat to modify this way
                     # Special handling for AC might be needed if it's not a simple addition to a base stat
                     # For now, assume it's a direct modification to an 'armor_class' stat if it exists.
                     # A more robust system would recalculate AC based on armor, dex, etc.
                    character.stats[key] = character.stats.get(key, 0) + (bonus_value * multiplier)
                    print(f"RuleEngine: {action} item {item_id} changed stat {key} by {bonus_value * multiplier} for char {char_id}. New value: {character.stats[key]}")
                else:
                    # print(f"RuleEngine: Unknown bonus key '{key}' on item {item_template_id}.")
                    pass # Silently ignore unknown bonus types for now

            except ValueError:
                print(f"RuleEngine: Invalid bonus value '{value}' for key '{key}' on item {item_template_id}.")

        if self._character_manager:
            self._character_manager.mark_character_dirty(guild_id, char_id)

    async def resolve_saving_throw(
        self, 
        character: Union["Character", "NPC"], 
        stat_to_save_with: str, 
        difficulty_class: int, 
        situational_modifier: int = 0,
        **kwargs: Any
    ) -> tuple[bool, int, int, Optional[str]]:
        """
        Resolves a saving throw for a character against a DC.
        Returns: (success: bool, total_save_value: int, d20_roll: int, crit_status: Optional[str])
        """
        entity_stats = getattr(character, 'stats', {})
        if not isinstance(entity_stats, dict): entity_stats = {}

        stat_value = entity_stats.get(stat_to_save_with.lower(), 10) # Default to 10 if stat not present
        stat_modifier = self._calculate_attribute_modifier(stat_value)

        try:
            roll_result_dict = await self._resolve_dice_roll("1d20", context=kwargs)
            d20_roll = roll_result_dict['total']
        except ValueError:
            d20_roll = 10 # Fallback

        total_save_value = d20_roll + stat_modifier + situational_modifier

        crit_rules = self._rules_data.get("check_rules", {})
        crit_success_roll = crit_rules.get("critical_success", {}).get("natural_roll", 20)
        crit_failure_roll = crit_rules.get("critical_failure", {}).get("natural_roll", 1)

        crit_status: Optional[str] = None
        success: bool # Declare success here
        if d20_roll == crit_success_roll and crit_rules.get("critical_success", {}).get("auto_succeeds", True):
            success = True
            crit_status = "critical_success"
        elif d20_roll == crit_failure_roll and crit_rules.get("critical_failure", {}).get("auto_fails", True):
            success = False
            crit_status = "critical_failure"
        else:
            success = total_save_value >= difficulty_class
        
        char_id = getattr(character, 'id', 'UnknownEntity')
        print(f"RuleEngine: Saving Throw ({stat_to_save_with.capitalize()} DC {difficulty_class}) for {char_id}: Roll={d20_roll}, StatMod={stat_modifier}, SitMod={situational_modifier} -> Total={total_save_value}. Success: {success} (Crit: {crit_status})")
        return success, total_save_value, d20_roll, crit_status

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

        guild_id_for_log = context.get('guild_id', "UNKNOWN_GUILD")
        # Ensure guild_id_for_log is a string for the logger
        if not isinstance(guild_id_for_log, str): guild_id_for_log = str(guild_id_for_log)


        if self._game_log_manager:
            await self._game_log_manager.log_event(
                guild_id=guild_id_for_log,
                event_type="resolve_check_start",
                message=f"Starting resolve_check. Type: '{check_type}', Actor: {entity_doing_check_type} ID {entity_doing_check_id}, Target: {target_entity_type} ID {target_entity_id}, DC: {difficulty_dc}.",
                related_entities=[
                    {"id": entity_doing_check_id, "type": entity_doing_check_type},
                    {"id": str(target_entity_id), "type": str(target_entity_type)} if target_entity_id else None
                ],
                metadata={
                    "check_type": check_type,
                    "actor_id": entity_doing_check_id, "actor_type": entity_doing_check_type,
                    "target_id": target_entity_id, "target_type": target_entity_type,
                    "initial_dc": difficulty_dc, "context_keys": list(context.keys())
                }
            )

        # Initialize DetailedCheckResult using the new structure
        result = DetailedCheckResult(
            check_type=check_type,
            entity_doing_check_id=entity_doing_check_id,
            target_entity_id=target_entity_id,
            difficulty_dc=difficulty_dc # Will be updated if not provided but resolved internally
        )

        guild_id = context.get('guild_id') if context else None
        if not guild_id:
            result.description = "Error: guild_id missing from context for resolve_check."
            return result

        if not self._rules_data or 'checks' not in self._rules_data:
            result.description = "Error: RuleEngine rules_data not loaded or 'checks' key missing."
            return result
        
        check_config = self._rules_data.get('checks', {}).get(check_type)
        if not check_config:
            result.description = f"Error: No configuration found for check_type '{check_type}'."
            return result

        # --- Actor's Roll ---
        actor_roll_config = check_config.get("actor_roll_details", check_config) # Fallback to main for simple checks
        (
            result.actor_total_roll_value,
            result.actor_rolls,
            result.actor_modifier_applied,
            result.actor_modifier_details,
            result.actor_crit_status,
            result.actor_roll_formula # Store the actual formula used
        ) = await self._resolve_single_entity_check_roll(
            entity_doing_check_id, entity_doing_check_type, actor_roll_config, guild_id, context
        )
        
        if not result.actor_modifier_details or (len(result.actor_modifier_details) == 1 and result.actor_modifier_details[0]['source'] == 'entity_not_found'):
            result.description = f"Error: Actor {entity_doing_check_type} ID {entity_doing_check_id} not found or failed to roll."
            result.outcome = CheckOutcome.FAILURE
            return result

        # --- Resolution Method ---
        resolution_method = check_config.get("resolution_method", "DC").upper()

        if resolution_method == "OPPOSED_ROLL":
            if not target_entity_id or not target_entity_type:
                result.description = "Error: Opposed roll selected, but target_entity_id or target_entity_type missing."
                result.outcome = CheckOutcome.FAILURE # Actor fails if target is invalid for opposed
                return result

            target_roll_config = check_config.get("target_roll_details")
            if not target_roll_config:
                result.description = f"Error: Opposed roll for '{check_type}', but 'target_roll_details' missing in check_config."
                result.outcome = CheckOutcome.FAILURE
                return result
            
            (
                result.target_total_roll_value,
                result.target_rolls,
                result.target_modifier_applied,
                result.target_modifier_details,
                result.target_crit_status,
                result.target_roll_formula
            ) = await self._resolve_single_entity_check_roll(
                target_entity_id, target_entity_type, target_roll_config, guild_id, context
            )

            if not result.target_modifier_details or (len(result.target_modifier_details) == 1 and result.target_modifier_details[0]['source'] == 'entity_not_found'):
                 result.description = f"Error: Target {target_entity_type} ID {target_entity_id} for opposed roll not found or failed to roll. Actor wins by default."
                 result.is_success = True # Actor considered successful if target is invalid for opposed roll
                 result.outcome = CheckOutcome.ACTOR_WINS_OPPOSED
                 # Actor's crit status determines if the overall check is critical
                 result.is_critical = bool(result.actor_crit_status == "critical_success" or result.actor_crit_status == "critical_failure")
                 # No target_value (DC) in this case
            else:
                # Compare actor vs target
                if result.actor_total_roll_value > result.target_total_roll_value:
                    result.is_success = True
                    result.outcome = CheckOutcome.ACTOR_WINS_OPPOSED
                elif result.actor_total_roll_value < result.target_total_roll_value:
                    result.is_success = False
                    result.outcome = CheckOutcome.TARGET_WINS_OPPOSED
                else: # Tie
                    result.is_success = False # Or based on tie-breaking rule, default actor fails on tie
                    result.outcome = CheckOutcome.TIE_OPPOSED
                    # Tie-breaking logic from rules_config can be applied here by ConflictResolver or higher level.
                
                # Overall critical status for opposed checks:
                # Can be true if either actor OR target had a critical roll that influences the outcome.
                # For simplicity, let's say if actor's roll was critical, it's a critical outcome.
                # Game-specific rules might differ (e.g. only actor's crit matters, or target's crit negates actor's).
                result.is_critical = bool(result.actor_crit_status or result.target_crit_status) # If either had a crit

        elif resolution_method == "DC":
            actual_dc = difficulty_dc
            if actual_dc is None: # Try to get from check_config or target's passive stat
                if target_entity_id and target_entity_type:
                    target_entity_obj = None
                    if self._character_manager and target_entity_type == "Character":
                        target_entity_obj = await self._character_manager.get_character(guild_id, target_entity_id)
                    elif self._npc_manager and target_entity_type == "NPC":
                        target_entity_obj = await self._npc_manager.get_npc(guild_id, target_entity_id)

                    if target_entity_obj:
                        dc_stat_name = check_config.get('target_dc_stat')
                        if dc_stat_name and hasattr(target_entity_obj, 'stats') and isinstance(target_entity_obj.stats, dict):
                            actual_dc = target_entity_obj.stats.get(dc_stat_name, check_config.get('default_dc', 15))
                        else: actual_dc = check_config.get('default_dc', 15)
                    else: actual_dc = check_config.get('default_dc', 15)
                else: actual_dc = check_config.get('default_dc', 15)
            
            result.difficulty_dc = actual_dc # Store the DC that was used

            # Standard DC check outcome based on actor's roll
            if result.actor_crit_status == "critical_success":
                result.is_success = check_config.get("critical_success", {}).get("auto_succeeds", True)
                result.outcome = CheckOutcome.CRITICAL_SUCCESS
                result.is_critical = True
            elif result.actor_crit_status == "critical_failure":
                result.is_success = not check_config.get("critical_failure", {}).get("auto_fails", True) # Success is false if auto_fails is true
                result.outcome = CheckOutcome.CRITICAL_FAILURE
                result.is_critical = True
            else:
                result.is_success = result.actor_total_roll_value >= actual_dc
                result.outcome = CheckOutcome.SUCCESS if result.is_success else CheckOutcome.FAILURE
                result.is_critical = False
        else:
            result.description = f"Error: Unknown resolution_method '{resolution_method}' in check_config for '{check_type}'."
            result.outcome = CheckOutcome.FAILURE # Default to failure for unknown methods
            return result

        # Populate final description
        actor_name = getattr(result, 'entity_doing_check_id', 'Unknown Actor') # Should be populated from actor object if found
        # Fetch actor object again to get name for description, or pass actor object through
        actor_obj_for_name = None
        if entity_doing_check_type == "Character" and self._character_manager: actor_obj_for_name = await self._character_manager.get_character(guild_id, entity_doing_check_id)
        elif entity_doing_check_type == "NPC" and self._npc_manager: actor_obj_for_name = await self._npc_manager.get_npc(guild_id, entity_doing_check_id)
        if actor_obj_for_name: actor_name = getattr(actor_obj_for_name, 'name', entity_doing_check_id)
        
        description_parts = [f"{check_type.replace('_', ' ').capitalize()} by {actor_name}:"]
        description_parts.append(f"Actor Roll ({result.actor_roll_formula}): {result.actor_rolls} + Mod: {result.actor_modifier_applied} = Total: {result.actor_total_roll_value}.")
        if result.actor_crit_status: description_parts.append(f"Actor Crit: {result.actor_crit_status}.")

        if resolution_method == "OPPOSED_ROLL":
            target_name = target_entity_id
            target_obj_for_name = None
            if target_entity_type == "Character" and self._character_manager: target_obj_for_name = await self._character_manager.get_character(guild_id, target_entity_id)
            elif target_entity_type == "NPC" and self._npc_manager: target_obj_for_name = await self._npc_manager.get_npc(guild_id, target_entity_id)
            if target_obj_for_name: target_name = getattr(target_obj_for_name, 'name', target_entity_id)

            description_parts.append(f"VS Target ({target_name}) Roll ({result.target_roll_formula}): {result.target_rolls} + Mod: {result.target_modifier_applied} = Total: {result.target_total_roll_value}.")
            if result.target_crit_status: description_parts.append(f"Target Crit: {result.target_crit_status}.")
        else: # DC Check
            description_parts.append(f"Target DC: {result.difficulty_dc}.")
        
        description_parts.append(f"Outcome: {result.outcome.name}{' (Overall Critical)' if result.is_critical and resolution_method == 'DC' else ''}.") # is_critical for DC check is actor's crit
        result.description = " ".join(description_parts)

        if self._game_log_manager:
            log_message = f"Resolve_check completed for Type: '{check_type}', Actor: {entity_doing_check_id}. Outcome: {result.outcome.name}."
            if result.is_critical : log_message += " (Critical involved)"

            try: result_dict_for_log = result.model_dump() if hasattr(result, 'model_dump') else vars(result)
            except Exception: result_dict_for_log = {"description": result.description, "is_success": result.is_success}

            await self._game_log_manager.log_event(
                guild_id=guild_id_for_log, event_type="resolve_check_end", message=log_message,
                related_entities=[
                    {"id": entity_doing_check_id, "type": entity_doing_check_type},
                    {"id": str(target_entity_id), "type": str(target_entity_type)} if target_entity_id else None
                ],
                metadata={"detailed_check_result": result_dict_for_log}
            )
        else:
            print(f"RuleEngine.resolve_check: {result.description}")

        return result

    async def _resolve_single_entity_check_roll(
        self,
        entity_id: str,
        entity_type: str,
        roll_config: Dict[str, Any], # Contains primary_stat, relevant_skill, base_roll_formula
        guild_id: str,
        context: Dict[str, Any]
    ) -> Tuple[int, List[int], int, List[Dict[str, Any]], Optional[str], str]: # total_value, rolls, modifier, mod_details, crit_status, roll_formula_used
        """
        Helper to perform a roll for a single entity (actor or target).
        Fetches entity, calculates modifiers, rolls dice, determines critical status.
        """
        entity_obj: Optional[Union[Character, NPC]] = None
        if entity_type == "Character" and self._character_manager:
            entity_obj = await self._character_manager.get_character(guild_id, entity_id)
        elif entity_type == "NPC" and self._npc_manager:
            entity_obj = await self._npc_manager.get_npc(guild_id, entity_id)

        if not entity_obj:
            # Return default failure values if entity not found
            return 0, [], 0, [{"value": 0, "source": "entity_not_found"}], None, roll_config.get('roll_formula', '1d20')

        calculated_modifier = 0
        modifier_details_list: List[Dict[str, Any]] = []

        # Stat modifier
        primary_stat = roll_config.get('primary_stat')
        if primary_stat and hasattr(entity_obj, 'stats') and isinstance(entity_obj.stats, dict):
            stat_value = entity_obj.stats.get(primary_stat, 10)
            stat_mod = self._calculate_attribute_modifier(stat_value)
            if stat_mod != 0:
                calculated_modifier += stat_mod
                modifier_details_list.append({"value": stat_mod, "source": f"stat:{primary_stat}"})

        # Skill modifier
        relevant_skill = roll_config.get('relevant_skill')
        if relevant_skill and hasattr(entity_obj, 'skills') and isinstance(entity_obj.skills, dict):
            skill_value = entity_obj.skills.get(relevant_skill, 0)
            if skill_value != 0:
                calculated_modifier += skill_value
                modifier_details_list.append({"value": skill_value, "source": f"skill:{relevant_skill}"})

        # Status effect modifiers (simplified, adapt full logic from main resolve_check if needed)
        if self._status_manager and hasattr(entity_obj, 'status_effects'):
            # This is a simplified version. The main resolve_check has more detailed status effect parsing.
            # For this helper, it might be acceptable if roll_config can specify direct status modifiers
            # or if a more generic approach is taken.
            # For now, let's assume roll_config might have a 'status_modifiers_for_check_type' list or similar.
            pass # Placeholder for status effect logic

        # Item effect modifiers (simplified)
        # Placeholder for item effect logic

        # Contextual modifiers (from context passed to this helper, if any specific to this entity's roll)
        # These would typically be part of the broader 'context' passed to resolve_check,
        # and then filtered/applied here if roll_config specifies.

        roll_formula_to_use = roll_config.get('roll_formula', '1d20')

        base_roll_value = 0
        rolls_list: List[int] = []
        try:
            roll_result_data = await self.resolve_dice_roll(roll_formula_to_use, context)
            rolls_list = roll_result_data.get('rolls', [])
            base_roll_value = roll_result_data.get('total', 0)
        except ValueError: # Should not happen if resolve_dice_roll is robust
            rolls_list = [1] # Default roll
            base_roll_value = 1

        total_roll_value = base_roll_value + calculated_modifier

        # Critical status for this specific roll
        crit_status: Optional[str] = None
        d20_roll_for_crit_check = 0
        if rolls_list and (roll_formula_to_use.startswith("1d20") or "d20" in roll_formula_to_use):
             d20_roll_for_crit_check = rolls_list[0]

        main_check_rules = self._rules_data.get("check_rules", {})
        # Use crit config from the entity's roll_config if present, else main rules
        crit_success_config = roll_config.get("critical_success", main_check_rules.get("critical_success", {}))
        crit_failure_config = roll_config.get("critical_failure", main_check_rules.get("critical_failure", {}))

        crit_success_roll_val = crit_success_config.get("natural_roll", 20)
        crit_failure_roll_val = crit_failure_config.get("natural_roll", 1)

        if d20_roll_for_crit_check == crit_success_roll_val:
            crit_status = "critical_success"
        elif d20_roll_for_crit_check == crit_failure_roll_val:
            crit_status = "critical_failure"

        return total_roll_value, rolls_list, calculated_modifier, modifier_details_list, crit_status, roll_formula_to_use

    # --- Stubs for Other Key Missing Mechanics ---
