# bot/game/world_processors/world_view_service.py

# --- Импорты ---
import traceback
import asyncio # Может понадобиться для асинхронных вызовов менеджеров
from typing import Optional, Dict, Any, List # Import needed types


# Импорт менеджеров, от которых WorldViewService зависит для получения данных
# Эти менеджеры предоставляют доступ к кешам объектов сущностей.
# Используйте строковые аннотации ('ManagerName') для Optional зависимостей.
from bot.game.managers.location_manager import LocationManager # Нужен для описания локации
from bot.game.managers.character_manager import CharacterManager # Нужен для получения Char в локации / описания Char
from bot.game.managers.npc_manager import NpcManager # Нужен для получения NPC в локации / описания NPC
from bot.game.managers.item_manager import ItemManager # Нужен для получения Item в локации / описания Item
from bot.game.managers.party_manager import PartyManager # Нужен для получения Party в локации / описания Party

# Импорт других сервисов или правил, нужных для ФОРМАТИРОВАНИЯ или ФИЛЬТРАЦИИ информации
from bot.services.openai_service import OpenAIService # Опционально, для генерации более богатых описаний
from bot.game.rules.rule_engine import RuleEngine # Опционально, для определения, что видит персонаж (перцепция) или детали (знания)
from bot.game.managers.status_manager import StatusManager # Опционально, для описания статусов у сущностей

# Импорт моделей (для аннотаций)
from bot.game.models.character import Character
from bot.game.models.npc import NPC
from bot.game.models.item import Item
from bot.game.models.party import Party
# from bot.game.models.location import Location # Если Location - это модель, а не Dict static data


class WorldViewService:
    """
    Сервис, отвечающий за сбор и форматирование информации об игровом мире,
    локациях и сущностях для представления пользователю.
    Он использует различные менеджеры для доступа к данным в кеше
    и RuleEngine/OpenAIService для адаптации описания.
    WorldViewService не меняет состояние мира.
    """
    def __init__(self,
                 # --- Обязательные зависимости (Менеджеры, предоставляющие базовые данные) ---
                 location_manager: LocationManager,
                 character_manager: CharacterManager,
                 npc_manager: NpcManager,
                 item_manager: ItemManager,
                 party_manager: PartyManager,

                 # --- Опциональные зависимости (Сервисы/Правила для адаптации описания) ---
                 openai_service: Optional[OpenAIService] = None,
                 rule_engine: Optional[RuleEngine] = None,
                 status_manager: Optional[StatusManager] = None, # Для описания статусов
                 # TODO: Добавьте другие менеджеры/сервисы, нужные для получения ДОПОЛНИТЕЛЬНЫХ данных
                 # combat_manager: Optional['CombatManager'] = None, # Если нужно видеть информацию о бое в локации
                ):
        print("Initializing WorldViewService...")
        # --- Сохранение всех переданных аргументов в self._... ---
        # Обязательные
        self._location_manager = location_manager
        self._character_manager = character_manager
        self._npc_manager = npc_manager
        self._item_manager = item_manager
        self._party_manager = party_manager

        # Опциональные
        self._openai_service = openai_service
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        # self._combat_manager = combat_manager


        print("WorldViewService initialized.")

    # Метод для получения описания текущей локации и ее содержимого (для команды /look)
    # Вызывается из CommandRouter.
    async def get_location_description(self,
                                       location_id: str,
                                       viewer_entity_id: str, # ID сущности, которая осматривает (Char/NPC)
                                       viewer_entity_type: str, # Тип сущности ('Character', 'NPC')
                                       **kwargs # Дополнительные менеджеры/сервисы, переданные из CommandRouter (если не инжектированы в __init__)
                                      ) -> Optional[str]:
        """
        Генерирует текстовое описание локации и списка сущностей в ней.
        Использует RuleEngine для определения видимости и OpenAI для описания.
        Возвращает форматированный текст или None при ошибке/локация не найдена.
        """
        print(f"WorldViewService: Generating description for location {location_id} for viewer {viewer_entity_type} ID {viewer_entity_id}.")

        # Получаем статические данные локации
        location_data = self._location_manager.get_location_static(location_id)
        if not location_data:
            print(f"WorldViewService: Error generating location description: Location {location_id} not found.")
            return None # Локация не найдена

        # Получаем динамический список сущностей, находящихся в этой локации.
        # Итерируем по кешам соответствующих менеджеров и фильтруем по location_id.
        entities_in_location: List[Any] = []

        # Добавляем персонажей в этой локации
        # CharacterManager должен иметь метод get_characters_in_location или просто получить всех и отфильтровать.
        # Давайте предположим, что CharacterManager возвращает всех персонажей, а фильтрация по локации происходит здесь.
        # Исключаем смотрящего, если он является персонажем
        all_characters = self._character_manager.get_all_characters() # CharacterManager.get_all_characters() возвращает List[Character]
        for char in all_characters:
             if char.id != viewer_entity_id and getattr(char, 'location_id', None) == location_id:
                  entities_in_location.append(char)

        # Добавляем NPC в этой локации
        # NpcManager должен иметь метод get_npcs_in_location или получить всех и отфильтровать.
        all_npcs = self._npc_manager.get_all_npcs() # NpcManager.get_all_npcs() возвращает List[NPC]
        for npc in all_npcs:
             # Исключаем смотрящего, если он является NPC (редкий случай, но возможен)
             if npc.id != viewer_entity_id and getattr(npc, 'location_id', None) == location_id:
                  entities_in_location.append(npc)

        # Добавляем предметы на земле в этой локации
        # ItemManager должен иметь метод get_items_in_location или получить все и отфильтровать по location_id И owner_id = None.
        all_items = self._item_manager.get_all_items() # ItemManager.get_all_items() возвращает List[Item]
        for item in all_items:
             if getattr(item, 'location_id', None) == location_id and getattr(item, 'owner_id', None) is None:
                  entities_in_location.append(item)

        # Добавляем партии в этой локации? (Если партии имеют location_id)
        # PartyManager должен иметь метод get_parties_in_location или получить все и отфильтровать.
        all_parties = self._party_manager.get_all_parties() # PartyManager.get_all_parties() возвращает List[Party]
        for party in all_parties:
             # Как определить, находится ли партия в локации? По party.location_id? По лидеру? По большинству участников?
             # Предположим, что у Party модели есть location_id
             if getattr(party, 'location_id', None) == location_id:
                  # Решаем, как отображать партию. Как одну сущность? Как список участников?
                  # Пока добавим как одну сущность 'Party'
                  entities_in_location.append(party)


        # TODO: Фильтрация видимости сущностей на основе перцепции смотрящего иRuleEngine.
        # Используйте self._rule_engine. Например, RuleEngine.can_see(viewer, target, context).
        # visible_entities = []
        # if self._rule_engine and hasattr(self._rule_engine, 'can_see'):
        #      viewer_entity = None # Нужно получить объект смотрящего из его менеджера (по viewer_entity_id, viewer_entity_type)
        #      if viewer_entity_type == 'Character': viewer_entity = self._character_manager.get_character(viewer_entity_id)
        #      elif viewer_entity_type == 'NPC': viewer_entity = self._npc_manager.get_npc(viewer_entity_id)
        #      if viewer_entity:
        #           for entity in entities_in_location:
        #                # Передаем все необходимые менеджеры в контекст RuleEngine
        #                rule_context = {
        #                    'location_manager': self._location_manager,
        #                    'character_manager': self._character_manager, 'npc_manager': self._npc_manager,
        #                    'item_manager': self._item_manager, 'party_manager': self._party_manager,
        #                    'status_manager': self._status_manager, 'combat_manager': self._combat_manager,
        #                    # TODO: Добавьте другие менеджеры, нужные RuleEngine.can_see
        #                    # RuleEngine может нуждаться в себе? (маловероятно)
        #                    # 'rule_engine': self._rule_engine,
        #                    **kwargs # Передаем kwargs из CommandRouter
        #                }
        #                if await self._rule_engine.can_see(viewer_entity, entity, context=rule_context):
        #                     visible_entities.append(entity)
        #           entities_to_list = visible_entities
        #      else:
        #           print(f"WorldViewService: Warning: Viewer entity {viewer_entity_id} ({viewer_entity_type}) not found for visibility check.")
        #           entities_to_list = entities_in_location # Если смотрящий не найден, показываем всех? Или никого?
        # else:
        #      print("WorldViewService: Warning: RuleEngine or can_see method not available for visibility check.")
        #      entities_to_list = entities_in_location # Если нет RuleEngine, показываем всех


        # Пока без фильтрации видимости, показываем всех
        entities_to_list = entities_in_location


        # --- Формирование описания локации ---
        location_name = location_data.get('name', 'Неизвестная Локация')
        location_description_base = location_data.get('description', 'Здесь ничего особенного нет.')
        exits_data = location_data.get('exits', {}) # Ожидаем {exit_name: target_location_id}

        description_text = f"**{location_name}**\n"

        # TODO: Улучшить описание с помощью OpenAI (опционально)
        # if self._openai_service and hasattr(self._openai_service, 'generate_location_description'):
        #      try:
        #           # OpenAI может использовать контекст: локацию, список видимых сущностей, погоду (если есть), время дня.
        #           # Передаем все необходимые данные в формате, понятном OpenAI Service.
        #           openai_context = {
        #               'location_data': location_data,
        #               'entities_in_location': [self._get_entity_summary(entity) for entity in entities_to_list], # Нужен вспомогательный метод _get_entity_summary
        #               # TODO: Добавить погоду, время дня и т.п.
        #           }
        #           generated_description = await self._openai_service.generate_location_description(openai_context)
        #           if generated_description:
        #                description_text += generated_description + "\n"
        #           else:
        #                # Если OpenAI не сгенерировал описание, используем базовое
        #                description_text += location_description_base + "\n"
        #      except Exception as e:
        #           print(f"WorldViewService: Error calling OpenAI Service for location description: {e}")
        #           import traceback
        #           print(traceback.format_exc())
        #           # При ошибке OpenAI, используем базовое описание
        #           description_text += location_description_base + "\n"
        # else:
        #      # Если OpenAI Service недоступен, используем базовое описание
        description_text += location_description_base + "\n" # Пока используем только базовое описание


        # --- Список сущностей в локации ---
        if entities_to_list:
            description_text += "\nВы видите здесь:\n"
            # TODO: Форматировать список сущностей более красиво. Возможно, группировать по типу.
            # Например: "Персонажи: Имя1, Имя2", "NPC: Имя NPC", "Предметы: Меч, Зелье"
            for entity in entities_to_list:
                entity_name = getattr(entity, 'name', 'Неизвестная Сущность')
                # Добавить тип сущности для ясности
                entity_type_display = "???"
                if isinstance(entity, Character): entity_type_display = "Персонаж"
                elif isinstance(entity, NPC): entity_type_display = "NPC"
                elif isinstance(entity, Item): entity_type_display = "Предмет"
                elif isinstance(entity, Party): entity_type_display = "Партия"

                description_text += f"- {entity_name} ({entity_type_display})\n"

            # TODO: Добавить информацию о том, кто находится в одной партии со смотрящим (если смотрящий в партии)
            # if viewer_entity_type == 'Character' and self._party_manager and hasattr(self._party_manager, 'get_party_by_member_id'):
            #      viewer_party = self._party_manager.get_party_by_member_id(viewer_entity_id)
            #      if viewer_party:
            #           party_members_in_location = [m for m in entities_to_list if hasattr(m, 'party_id') and m.party_id == viewer_party.id]
            #           if party_members_in_location:
            #                description_text += "\nВ вашей партии здесь:\n"
            #                for member in party_members_in_location:
            #                     description_text += f"- {getattr(member, 'name', 'Неизвестный')}\n"


        # --- Выходы из локации ---
        if exits_data:
            description_text += "\nВыходы:\n"
            # Сортируем выходы по имени для консистентного порядка
            sorted_exits = sorted(exits_data.items())
            for exit_name, target_location_id_exit in sorted_exits:
                 # Пытаемся получить имя целевой локации для более понятного вывода
                 target_location_name = self._location_manager.get_location_name(target_location_id_exit) if hasattr(self._location_manager, 'get_location_name') else target_location_id_exit
                 description_text += f"- **{exit_name.capitalize()}** ведет в '{target_location_name}'\n"
        else:
            description_text += "\nВыходов из этой локации нет.\n"

        print(f"WorldViewService: Location description generated for {location_id}.")
        return description_text


    # Метод для получения подробного описания конкретной сущности (для команды /look <target>)
    # Вызывается из CommandRouter.
    async def get_entity_details(self,
                                 entity_id: str,
                                 entity_type: str, # Тип сущности ('Character', 'NPC', 'Item', 'Party')
                                 viewer_entity_id: str, # ID сущности, которая осматривает (Char/NPC)
                                 viewer_entity_type: str, # Тип сущности ('Character', 'NPC')
                                 **kwargs # Дополнительные менеджеры/сервисы, переданные из CommandRouter
                                ) -> Optional[str]:
        """
        Генерирует подробное текстовое описание конкретной сущности.
        Использует RuleEngine для определения глубины деталей и OpenAI для описания.
        Возвращает форматированный текст или None при ошибке/сущность не найдена.
        """
        print(f"WorldViewService: Generating details for entity {entity_type} ID {entity_id} for viewer {viewer_entity_type} ID {viewer_entity_id}.")

        entity = None # Объект сущности
        manager = None # Менеджер сущности

        # Получаем объект сущности по типу и ID из соответствующего менеджера
        if entity_type == 'Character' and self._character_manager:
             entity = self._character_manager.get_character(entity_id)
             manager = self._character_manager
        elif entity_type == 'NPC' and self._npc_manager:
             entity = self._npc_manager.get_npc(entity_id)
             manager = self._npc_manager
        elif entity_type == 'Item' and self._item_manager:
             entity = self._item_manager.get_item(entity_id)
             manager = self._item_manager
        elif entity_type == 'Party' and self._party_manager:
             entity = self._party_manager.get_party(entity_id)
             manager = self._party_manager
        # TODO: Добавьте другие типы сущностей (Combat?)

        if entity is None:
            print(f"WorldViewService: Error generating entity details: Entity {entity_type} ID {entity_id} not found in manager cache.")
            return None # Сущность не найдена

        # TODO: Фильтрация деталей на основе знаний/навыков смотрящего и RuleEngine.
        # Используйте self._rule_engine. Например, RuleEngine.get_observation_details(viewer, target, context).
        # RuleEngine может вернуть словарь с уровнями детализации (поверхностный, глубокий) или конкретными фактами.
        # Например, проверка навыка 'Medical' может раскрыть информацию о ранах, 'Appraisal' - о ценности предмета.
        # context для RuleEngine должен включать все менеджеры, смотрящего и цель.
        # rule_context = {
        #      'location_manager': self._location_manager,
        #      'character_manager': self._character_manager, 'npc_manager': self._npc_manager,
        #      'item_manager': self._item_manager, 'party_manager': self._party_manager,
        #      'status_manager': self._status_manager, 'combat_manager': self._combat_manager,
        #      'rule_engine': self._rule_engine, # Маловероятно, что RuleEngine нужен себе
        #      'openai_service': self._openai_service, # Может понадобиться для форматирования результата RuleEngine?
        #      # TODO: Добавьте другие менеджеры
        #      **kwargs # Передаем kwargs из CommandRouter
        # }
        # observer_obj = self._character_manager.get_character(viewer_entity_id) if viewer_entity_type == 'Character' else self._npc_manager.get_npc(viewer_entity_id) # Получаем объект смотрящего
        # observed_details = {} # Словарь с деталями, полученными от RuleEngine
        # if self._rule_engine and hasattr(self._rule_engine, 'get_observation_details') and observer_obj:
        #      try:
        #           # RuleEngine.get_observation_details может быть асинхронным
        #           observed_details = await self._rule_engine.get_observation_details(observer_obj, entity, context=rule_context)
        #      except Exception as e:
        #           print(f"WorldViewService: Error calling RuleEngine.get_observation_details for entity {entity_id}: {e}")
        #           import traceback
        #           print(traceback.format_exc())
        #      # print(f"WorldViewService: Details from RuleEngine: {observed_details}") # Debug
        # else:
        #      print("WorldViewService: Warning: RuleEngine or get_observation_details method not available for details filtering.")


        # --- Формирование подробного описания сущности ---
        description_text = ""
        entity_name = getattr(entity, 'name', 'Неизвестная Сущность')
        description_text += f"**{entity_name}** ({entity_type})\n"
        description_text += f"ID: {entity_id}\n" # Для отладки

        # TODO: Улучшить описание с помощью OpenAI (опционально). Передать все собранные детали из RuleEngine.
        # if self._openai_service and hasattr(self._openai_service, 'generate_entity_description'):
        #      try:
        #           # OpenAI может использовать контекст: объект сущности, уровень детализации, детали от RuleEngine.
        #           # Передаем все необходимые данные.
        #           openai_context = {
        #               'entity_object': entity,
        #               'entity_type': entity_type,
        #               'observed_details': observed_details, # Детали, полученные от RuleEngine
        #               'viewer_entity_object': observer_obj, # Объект смотрящего
        #               'viewer_entity_type': viewer_entity_type,
        #               # TODO: Добавить локацию сущности и смотрящего? Время дня?
        #           }
        #           generated_description = await self._openai_service.generate_entity_description(openai_context)
        #           if generated_description:
        #                description_text += generated_description + "\n"
        #           else:
        #                # Если OpenAI не сгенерировал описание, используем базовые детали
        #                description_text += self._format_basic_entity_details(entity, entity_type, observed_details) # Нужен вспомогательный метод
        #      except Exception as e:
        #           print(f"WorldViewService: Error calling OpenAI Service for entity description: {e}")
        #           import traceback
        #           print(traceback.format_exc())
        #           # При ошибке OpenAI, используем базовые детали
        #           description_text += self._format_basic_entity_details(entity, entity_type, observed_details)
        # else:
        #      # Если OpenAI Service недоступен, используем базовые детали
        #      description_text += self._format_basic_entity_details(entity, entity_type, observed_details)


        # TODO: Реализовать вспомогательный метод _format_basic_entity_details(entity, entity_type, observed_details)
        # Этот метод должен форматировать базовые детали сущности (здоровье, статы, инвентарь для персонажей/NPC,
        # состояние/заряд для предметов, участники/лидер для партий), возможно, используя информацию из observed_details
        # и других менеджеров (StatusManager для статусов, ItemManager для инвентаря).
        # Пример заглушки:
        def _format_basic_entity_details_placeholder(entity_obj: Any, entity_type_str: str, observed_details_dict: Dict[str, Any]) -> str:
            details = ""
            details += f"Тип: {entity_type_str}\n"
            details += f"Имя: {getattr(entity_obj, 'name', 'Неизвестно')}\n"

            if entity_type_str in ['Character', 'NPC']:
                 details += f"Здоровье: {getattr(entity_obj, 'health', 'N/A')}/{getattr(entity_obj, 'max_health', 'N/A')}\n"
                 details += f"Жив: {'Да' if getattr(entity_obj, 'is_alive', False) else 'Нет'}\n"
                 # TODO: Добавить статус-эффекты (StatusManager)
                 # if self._status_manager and hasattr(self._status_manager, 'get_status_effects_on_entity'):
                 #      active_statuses = self._status_manager.get_status_effects_on_entity(getattr(entity_obj, 'id', None))
                 #      if active_statuses: details += f"Статусы: {', '.join([s.type for s in active_statuses])}\n" # Предполагаем, что StatusEffect имеет поле type

                 # TODO: Добавить инвентарь (для игрока/NPC)
                 # if entity_type_str == 'Character' and self._character_manager:
                 #     inventory_ids = getattr(entity_obj, 'inventory', [])
                 #     if inventory_ids and self._item_manager and hasattr(self._item_manager, 'get_item_name'):
                 #         item_names = [self._item_manager.get_item_name(item_id) for item_id in inventory_ids if self._item_manager.get_item_name(item_id)]
                 #         if item_names: details += f"Инвентарь: {', '.join(item_names)}\n"

            elif entity_type_str == 'Item':
                 details += f"Шаблон: {getattr(entity_obj, 'template_id', 'N/A')}\n"
                 details += f"Владелец ID: {getattr(entity_obj, 'owner_id', 'None')}\n"
                 details += f"Локация ID: {getattr(entity_obj, 'location_id', 'None')}\n"
                 # TODO: Добавить состояние, заряд и т.п.

            elif entity_type_str == 'Party':
                 details += f"Лидер ID: {getattr(entity_obj, 'leader_id', 'None')}\n"
                 members = getattr(entity_obj, 'members', [])
                 details += f"Участники ({len(members)}): {', '.join(members) if members else 'нет'}\n"
                 # TODO: Добавить текущее действие партии, очередь, location_id партии

            # Добавить детали из observed_details, если они есть (например, "Это существо кажется раненым", "На предмете видна магическая аура")
            # if observed_details_dict:
            #      details += "\n**Наблюдения:**\n"
            #      for key, value in observed_details_dict.items():
            #           details += f"- {key}: {value}\n"


            return details


        # Использование заглушки или реального метода форматирования
        description_text += _format_basic_entity_details_placeholder(entity, entity_type, {}) # Пока без RuleEngine деталей

        print(f"WorldViewService: Entity details generated for {entity_type} ID {entity_id}.")
        return description_text


    # TODO: Вспомогательный метод для получения краткого описания сущности (для списка в get_location_description)
    # def _get_entity_summary(self, entity: Any) -> Dict[str, Any]: ...
    # Должен возвращать словарь вроде {'id': entity.id, 'type': 'Character', 'name': entity.name, 'status': 'Healthy'}

# Конец класса WorldViewService