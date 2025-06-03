# bot/game/event_processors/stage_description_generator.py

# --- Импорты ---
import traceback
import asyncio # Возможно, нужен для асинхронных вызовов OpenAI
from typing import Optional, Dict, Any, List # Import Optional, Dict, Any, List


# TODO: Импорт сервисов и менеджеров, которые нужны для генерации описания
# Используйте строковые аннотации ('ManagerName') для Optional зависимостей.
# Например, для генерации описания с помощью OpenAI, для получения деталей сущностей в локации стадии
from bot.services.openai_service import OpenAIService # Нужен для генерации текста
# from bot.game.managers.character_manager import CharacterManager # Нужен для описания персонажей в сцене
# from bot.game.managers.npc_manager import NpcManager # Нужен для описания NPC в сцене
# from bot.game.managers.item_manager import ItemManager # Нужен для описания предметов в сцене
# from bot.game.managers.location_manager import LocationManager # Нужен для описания самой локации
# from bot.game.rules.rule_engine import RuleEngine # Может быть нужен для форматирования или получения данных


# TODO: Импорт моделей, если они используются в аннотациях или логике (Event, EventStage, Character, NPC, Item)
from bot.game.models.event import Event # Нужно для типа аргумента
from bot.game.models.event import EventStage # Нужно для типа данных стадии
# from bot.game.models.character import Character
# from bot.game.models.npc import NPC
# from bot.game.models.item import Item


class StageDescriptionGenerator:
    """
    Генератор текстового описания стадии события.
    Использует данные стадии и, возможно, внешние сервисы (LLM) для создания описания.
    """
    def __init__(self,
                 # TODO: Добавьте зависимости (менеджеры/сервисы), которые нужны для генерации описания.
                 # Эти менеджеры/сервисы передаются из GameManager при инстанциировании Генератора.
                 openai_service: Optional[OpenAIService] = None, # Нужен для генерации текста через OpenAI
                 # character_manager: Optional['CharacterManager'] = None,
                 # npc_manager: Optional['NpcManager'] = None,
                 # item_manager: Optional['ItemManager'] = None,
                 # location_manager: Optional['LocationManager'] = None,
                 # rule_engine: Optional['RuleEngine'] = None,
                ):
        print("Initializing StageDescriptionGenerator...")
        # --- Сохранение всех переданных аргументов в self._... ---
        self._openai_service = openai_service
        # self._character_manager = character_manager
        # self._npc_manager = npc_manager
        # self._item_manager = item_manager
        # self._location_manager = location_manager
        # self._rule_engine = rule_engine


        print("StageDescriptionGenerator initialized.")


    # Этот метод вызывается EventStageProcessor для генерации описания текущей стадии
    async def generate_description(self, event: Event, current_stage: EventStage, **kwargs) -> Optional[str]:
        """
        Генерирует текстовое описание текущей стадии события.
        Использует данные стадии, контекст события и, возможно, внешние сервисы (LLM).
        event: Объект текущего события.
        current_stage: Объект/словарь данных текущей стадии.
        kwargs: Дополнительные менеджеры/сервисы (CharacterManager, NpcManager и т.п.) для сбора контекста.
        """
        print(f"StageDescriptionGenerator: Generating description for event {event.id}, stage {current_stage.id}...")

        # Получаем необходимые менеджеры из kwargs или атрибутов __init__ генератора.
        # Предпочтительно использовать kwargs, т.к. они приходят из WorldTick/EventStageProcessor
        openai_service = kwargs.get('openai_service', self._openai_service) # Получаем OpenAI Service
        # TODO: Получите другие менеджеры из kwargs или атрибутов (CharacterManager, NpcManager, ItemManager, LocationManager...)
        character_manager = kwargs.get('character_manager', getattr(self, '_character_manager', None))
        npc_manager = kwargs.get('npc_manager', getattr(self, '_npc_manager', None))
        item_manager = kwargs.get('item_manager', getattr(self, '_item_manager', None))
        location_manager = kwargs.get('location_manager', getattr(self, '_location_manager', None))
        # rule_engine = kwargs.get('rule_engine', self._rule_engine)


        # --- Сбор контекста для генерации описания ---
        # Контекст может включать:
        # - Базовое описание из данных стадии (current_stage.description)
        # - Описание локации (LocationManager)
        # - Список и краткое описание сущностей в локации (CharacterManager, NpcManager, ItemManager)
        # - Состояние события (event.state_variables)
        # - Последние действия игроков/NPC (из state_variables события или отдельной логики)

        stage_base_description = getattr(current_stage, 'description', '') # Базовое описание из модели EventStage
        if not stage_base_description:
             print(f"StageDescriptionGenerator: Warning: Stage {current_stage.id} in event {event.id} has no base description.")
             # TODO: Возможно, сгенерировать описание на основе типа стадии?
             stage_base_description = f"Вы находитесь на стадии '{current_stage.id}'." # Заглушка


        # TODO: Собрать контекст о сущностях и окружении
        # entity_context = ""
        # if character_manager and hasattr(character_manager, 'get_characters_in_location'): # Нужен метод
        #     chars_in_loc = character_manager.get_characters_in_location(event.location_id) # Если локация события в модели Event
        #     # TODO: Сформировать строку описания персонажей
        #     pass
        # if npc_manager and hasattr(npc_manager, 'get_npcs_in_location'): # Нужен метод
        #     npcs_in_loc = npc_manager.get_npcs_in_location(event.location_id)
        #     # TODO: Сформировать строку описания NPC (состояние здоровья, статус, заняты ли)
        #     pass
        # if item_manager and hasattr(item_manager, 'get_items_in_location'): # Нужен метод
        #     items_in_loc = item_manager.get_items_in_location(event.location_id)
        #     # TODO: Сформировать строку описания видимых предметов
        #     pass
        # if location_manager and getattr(event, 'location_id', None) and hasattr(location_manager, 'get_location_static'):
        #      location_data = location_manager.get_location_static(event.location_id)
        #      location_description = getattr(location_data, 'description', '') # Описание локации из статики


        # TODO: Сформировать итоговый промпт для LLM, включая базовое описание и собранный контекст.
        # Промпт должен давать LLM инструкции о стиле, объеме и информации, которую нужно включить.
        # stage_prompt = f"""
        # Текущая локация: {location_description}
        # Сущности в локации: {entity_context}
        # Состояние события: {event.state_variables}
        # Базовое описание стадии: {stage_base_description}
        #
        # Напиши подробное, атмосферное описание текущей стадии для текстовой RPG.
        # Включи детали из базового описания стадии и информацию о сущностях/окружении.
        # Укажи, что видят и слышат персонажи.
        # """
        # Для начала, просто используем базовое описание стадии.
        stage_prompt = stage_base_description


        # --- Генерация описания с помощью OpenAI ---
        if openai_service and hasattr(openai_service, 'generate_text'):
            print("StageDescriptionGenerator: Calling OpenAI service to generate description...")
            try:
                # generate_text ожидает промпт и, возможно, контекст (messages)
                # Передаем также настройки генерации (max_tokens, temperature и т.п.)
                description = await openai_service.generate_text(
                    prompt=stage_prompt,
                    # model="gpt-3.5-turbo", # Можно переопределить модель
                    # max_tokens=300, # Можно переопределить макс токены
                    # temperature=0.7, # Можно установить температуру
                    # system_message="Ты игровой мастер текстовой RPG. Пиши атмосферные описания сцен." # Можно задать system message
                    # TODO: Передайте другие параметры генерации
                )

                if description:
                     print(f"StageDescriptionGenerator: Description generated successfully (length: {len(description)}).")
                     return description.strip() # Возвращаем сгенерированное описание

                else:
                     print("StageDescriptionGenerator: OpenAI service returned None or empty string for description.")
                     # Fallback к базовому описанию или сообщение об ошибке
                     return f"```\n{stage_base_description}\n(Не удалось сгенерировать подробное описание.)\n```" # Fallback с заглушкой

            except Exception as e:
                print(f"StageDescriptionGenerator: ❌ Error calling OpenAI service for description generation: {e}")
                import traceback
                print(traceback.format_exc())
                # Fallback к базовому описанию при ошибке генерации
                return f"```\n{stage_base_description}\n(Ошибка генерации описания: {e})\n```" # Fallback с ошибкой


        else:
            print("StageDescriptionGenerator: OpenAI service not available or generate_text method missing. Using base description.")
            # Fallback к базовому описанию, если OpenAI недоступен
            return f"```\n{stage_base_description}\n```" # Просто возвращаем базовое описание

# Конец класса StageDescriptionGenerator
