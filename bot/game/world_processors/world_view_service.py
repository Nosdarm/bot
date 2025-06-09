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

from typing import Optional, Dict, Any, List, TYPE_CHECKING # Import needed types

from typing import Optional, Dict, Any, List, TYPE_CHECKING # Import needed types

from typing import Optional, Dict, Any, List, TYPE_CHECKING # Import needed types

# Импорт моделей (для аннотаций)
from bot.game.models.character import Character # noqa F401
from bot.game.models.npc import NPC
from bot.game.models.item import Item
from bot.game.models.party import Party
from bot.game.models.relationship import Relationship # noqa F401
from bot.game.models.quest import Quest # Импорт Quest модели
# from bot.game.models.location import Location # Если Location - это модель, а не Dict static data

# Импорт i18n утилиты
from bot.utils.i18n_utils import get_i18n_text

# Определение языка по умолчанию
DEFAULT_BOT_LANGUAGE = "en"

if TYPE_CHECKING:
    from bot.services.db_service import DBService
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.quest_manager import QuestManager


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
                 db_service: Optional['DBService'] = None,
                 relationship_manager: Optional['RelationshipManager'] = None,
                 quest_manager: Optional['QuestManager'] = None, # Добавляем QuestManager
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
        self._db_service = db_service
        self._relationship_manager = relationship_manager
        self._quest_manager = quest_manager # Сохраняем QuestManager
        # self._combat_manager = combat_manager


        print("WorldViewService initialized.")

    # Метод для получения описания текущей локации и ее содержимого (для команды /look)
    # Вызывается из CommandRouter.
    async def get_location_description(self,
                                       guild_id: str, # ID сервера/гильдии для получения Character
                                       location_id: str,
                                       viewer_entity_id: str, # ID сущности, которая осматривает (Char/NPC)
                                       viewer_entity_type: str, # Тип сущности ('Character', 'NPC')
                                       **kwargs # Дополнительные менеджеры/сервисы, переданные из CommandRouter (если не инжектированы в __init__)
                                      ) -> Optional[str]:
        """
        Генерирует текстовое описание локации и списка сущностей в ней с учетом i18n.
        Использует RuleEngine для определения видимости и OpenAI для описания.
        Возвращает форматированный текст или None при ошибке/локация не найдена.
        """
        print(f"WorldViewService: Generating description for location {location_id} for viewer {viewer_entity_type} ID {viewer_entity_id} in guild {guild_id}.")

        # Определяем язык игрока
        player_lang = DEFAULT_BOT_LANGUAGE
        viewer_char_obj: Optional[Character] = None
        if viewer_entity_type == 'Character':
            viewer_char_obj = self._character_manager.get_character(guild_id, viewer_entity_id)
            if viewer_char_obj and viewer_char_obj.selected_language:
                player_lang = viewer_char_obj.selected_language

        print(f"WorldViewService: Using language '{player_lang}' for viewer {viewer_entity_id}.")

        # --- Получение данных о глобальном состоянии мира ---
        world_state_description_parts = []
        if self._db_service:
            relevant_world_states = [
                "current_era",
                "sky_condition",
                "magical_aura",
                "presence_shadow_lord", # Новый ключ для глобальной сущности
                "holy_aura_active_region_A" # Пример другого ключа
            ]
            # Это можно вынести в константу или конфигурацию
            world_state_consequences_i18n = {
                # Существующие состояния
                "eternal_night": {
                    "description_i18n": {
                        "en": "The land is cast in perpetual twilight.",
                        "ru": "Земля погружена в вечные сумерки."
                    }
                },
                "high_mana_flux": {
                    "description_i18n": {
                        "en": "The air crackles with raw magical energy.",
                        "ru": "Воздух трещит от необузданной магической энергии."
                    }
                },
                "celestial_alignment": {
                     "description_i18n": {
                         "en": "Mystical constellations align in the sky, empowering certain fates.",
                         "ru": "Мистические созвездия выстраиваются в небе, усиливая определенные судьбы."
                     }
                },
                # Новые значения для глобальных сущностей (ключи здесь - это значения из global_state.value)
                "shadow_lord_active_in_region": { # Значение для ключа 'presence_shadow_lord'
                    "description_i18n": {
                        "en": "A chilling sense of dread permeates the area, hinting at a dark power's influence.",
                        "ru": "Леденящее чувство ужаса пронизывает это место, намекая на влияние темной силы."
                    }
                },
                "shadow_lord_dormant": { # Другое значение для 'presence_shadow_lord'
                    "description_i18n": {
                        "en": "The oppressive shadow that once blanketed this land feels distant, almost forgotten.",
                        "ru": "Угнетающая тень, некогда покрывавшая эту землю, кажется далекой, почти забытой."
                    }
                },
                "holy_aura_strong_A": { # Значение для ключа 'holy_aura_active_region_A'
                     "description_i18n": {
                        "en": "A palpable holy aura blesses this area, offering peace and warding off lesser evils.",
                        "ru": "Ощутимая святая аура благословляет это место, даруя мир и отгоняя меньшее зло."
                     }
                }
                # Добавьте другие состояния и их описания здесь
            }

            for key in relevant_world_states:
                raw_value = await self._db_service.get_global_state_value(key)
                if raw_value:
                    consequence_data = world_state_consequences_i18n.get(raw_value)
                    if consequence_data:
                        consequence_desc = get_i18n_text(consequence_data, 'description_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE)
                        # Проверяем, что описание найдено и не является стандартным сообщением об ошибке get_i18n_text
                        if consequence_desc and "not found" not in consequence_desc.lower() and consequence_desc != raw_value : # Добавил проверку consequence_desc != raw_value
                            world_state_description_parts.append(consequence_desc)

        # --- Получаем статические данные локации ---
        location_data = self._location_manager.get_location_static(location_id) # Это dict
        if not location_data:
            print(f"WorldViewService: Error generating location description: Location {location_id} not found.")
            return None # Локация не найдена

        # Получаем динамический список сущностей, находящихся в этой локации.
        entities_in_location: List[Any] = []

        # Используем viewer_char_obj.id для исключения, если он доступен
        excluded_id = viewer_char_obj.id if viewer_char_obj else viewer_entity_id

        all_characters = self._character_manager.get_all_characters()
        for char_obj in all_characters: # Переименовано, чтобы не конфликтовать с Character
             # Убедимся, что viewer_char_obj это Character перед сравнением ID с char_obj.id
             if viewer_entity_type == 'Character' and viewer_char_obj and char_obj.id == viewer_char_obj.id:
                 continue # Пропускаем самого смотрящего персонажа
             if getattr(char_obj, 'location_id', None) == location_id:
                  entities_in_location.append(char_obj)

        all_npcs = self._npc_manager.get_all_npcs()
        for npc_obj in all_npcs: # Переименовано
             # Если смотрящий - NPC, и это текущий NPC в цикле, пропускаем
             if viewer_entity_type == 'NPC' and npc_obj.id == viewer_entity_id:
                 continue
             if getattr(npc_obj, 'location_id', None) == location_id:
                  entities_in_location.append(npc_obj)

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

        # --- Формирование локализованного описания локации ---
        # location_data['name_i18n'] и т.д. - это словари вида {'en': 'Name', 'ru': 'Имя'}
        location_name = get_i18n_text(location_data, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE)
        location_description_base = get_i18n_text(location_data, 'descriptions_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE)

        # Start with the location name
        description_text = f"**{location_name}**\n"

        # Main description block
        main_description_parts = [location_description_base]

        if world_state_description_parts:
            # Each part already ends with \n from previous logic, this might be too much.
            # Let's assume world_state_description_parts contains clean sentences.
            main_description_parts.extend(world_state_description_parts)

        # Add details, atmosphere, features to the main block
        location_details = get_i18n_text(location_data, 'details_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE)
        if location_details and "not found" not in location_details.lower() and location_details != "details_i18n":
            main_description_parts.append(location_details)

        location_atmosphere = get_i18n_text(location_data, 'atmosphere_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE)
        if location_atmosphere and "not found" not in location_atmosphere.lower() and location_atmosphere != "atmosphere_i18n":
            main_description_parts.append(location_atmosphere)

        location_features = get_i18n_text(location_data, 'features_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE)
        if location_features and "not found" not in location_features.lower() and location_features != "features_i18n":
            main_description_parts.append(location_features)

        # Join main description parts with a single newline
        description_text += "\n".join(filter(None, main_description_parts)) # filter(None,...) to remove empty strings

        # TODO: Улучшить описание с помощью OpenAI (опционально) - это остается без изменений

        # Ensure a blank line before the next section if there was any main description content
        if main_description_parts and any(part for part in main_description_parts if part != location_description_base or part): # Check if more than just base description or if base is not empty
             description_text += "\n"


        # --- Список сущностей в локации ---
        if entities_to_list:
            description_text += f"\n{get_i18n_text(None, 'you_see_here_label', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text='Вы видите здесь:')}\n"

            # Определение текстовых подсказок для отношений (остается как есть)
            relationship_cues_i18n = {
                "enemy_hostile": {"text_i18n": {"en": " (glares at you with intense hostility)", "ru": " (смотрит на вас с явной враждебностью)"}},
                "enemy_wary": {"text_i18n": {"en": " (seems wary and distrustful of you)", "ru": " (кажется, относится к вам с подозрением и недоверием)"}},
                "neutral_default": {"text_i18n": {"en": "", "ru": ""}}, # Может быть "" или что-то вроде " (regards you neutrally)"
                "friend_nod": {"text_i18n": {"en": " (offers you a friendly nod)", "ru": " (дружелюбно кивает вам)"}},
                "friend_warm": {"text_i18n": {"en": " (greets you warmly)", "ru": " (тепло приветствует вас)"}},
                # Можно добавить больше градаций и типов
            }

            for entity in entities_to_list:
                entity_name = getattr(entity, 'name', get_i18n_text(None, "unknown_entity_name", player_lang, default_lang=DEFAULT_BOT_LANGUAGE))

                entity_type_display = "???"
                if isinstance(entity, Character): entity_type_display = get_i18n_text(None, "entity_type_character", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Персонаж")
                elif isinstance(entity, NPC): entity_type_display = get_i18n_text(None, "entity_type_npc", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="NPC")
                elif isinstance(entity, Item): entity_type_display = get_i18n_text(None, "entity_type_item", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Предмет")
                elif isinstance(entity, Party): entity_type_display = get_i18n_text(None, "entity_type_party", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Партия")

                faction_display_string = ""
                relationship_text_cue = ""

                if isinstance(entity, NPC):
                    # Отображение фракции NPC
                    faction_data = getattr(entity, 'faction', None) # Ожидаем dict {'id': ..., 'name_i18n': ...}
                    if faction_data and isinstance(faction_data, dict):
                        localized_faction_name = get_i18n_text(faction_data, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE)
                        if localized_faction_name and "not found" not in localized_faction_name.lower() and localized_faction_name != "name_i18n":
                            faction_display_string = f", {localized_faction_name}" # Пример: ", Клан Красного Клыка"

                    # Отображение отношения к NPC
                    if self._relationship_manager and viewer_char_obj:
                        viewer_relationships: List[Relationship] = self._relationship_manager.get_relationships_for_entity(guild_id, viewer_char_obj.id)
                        target_npc_id = entity.id
                        relationship_with_npc: Optional[Relationship] = None
                        for rel in viewer_relationships:
                            if (rel.entity1_id == viewer_char_obj.id and rel.entity2_id == target_npc_id) or \
                               (rel.entity2_id == viewer_char_obj.id and rel.entity1_id == target_npc_id):
                                relationship_with_npc = rel
                                break

                        if relationship_with_npc:
                            cue_key = None
                            if relationship_with_npc.relationship_type == 'enemy':
                                if relationship_with_npc.strength <= -70: cue_key = "enemy_hostile"
                                else: cue_key = "enemy_wary"
                            elif relationship_with_npc.relationship_type == 'friend':
                                if relationship_with_npc.strength >= 70: cue_key = "friend_warm"
                                else: cue_key = "friend_nod"
                            elif relationship_with_npc.relationship_type == 'neutral':
                                 cue_key = "neutral_default"

                            if cue_key: # cue_key может быть None если тип не обработан
                                cue_data = relationship_cues_i18n.get(cue_key)
                                if cue_data:
                                    localized_cue = get_i18n_text(cue_data, 'text_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE)
                                    if localized_cue and "not found" not in localized_cue.lower() and localized_cue != cue_data.get('text_i18n', {}).get(DEFAULT_BOT_LANGUAGE, "text_i18n"):
                                        relationship_text_cue = localized_cue

                description_text += f"- {entity_name} ({entity_type_display}{faction_display_string}){relationship_text_cue}\n"

            # TODO: Добавить информацию о том, кто находится в одной партии со смотрящим (если смотрящий в партии)
            # if viewer_entity_type == 'Character' and self._party_manager and hasattr(self._party_manager, 'get_party_by_member_id'):
            #      viewer_party = self._party_manager.get_party_by_member_id(viewer_entity_id)
            #      if viewer_party:
            #           party_members_in_location = [m for m in entities_to_list if hasattr(m, 'party_id') and m.party_id == viewer_party.id]
            #           if party_members_in_location:
            #                description_text += "\nВ вашей партии здесь:\n"
            #                for member in party_members_in_location:
            #                     description_text += f"- {getattr(member, 'name', 'Неизвестный')}\n"

        # --- Отображение активных квестов ---
        if self._quest_manager and viewer_char_obj:
            active_quest_data_list = self._quest_manager.list_quests_for_character(guild_id, viewer_char_obj.id)
            if active_quest_data_list:
                active_quests_label = get_i18n_text(None, "active_quests_label", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Active Quests")
                # Ensure a blank line before this section if there were entities, or if no entities but there was main description
                if entities_to_list or (not entities_to_list and (main_description_parts and any(part for part in main_description_parts if part != location_description_base or part))):
                    description_text += "\n"
                description_text += f"{active_quests_label}:\n"

                for quest_data_item in active_quest_data_list:
                    # Убедимся, что quest_data_item совместим или преобразуем его.
                    # Для простоты предположим, что Quest.from_dict может работать с данными от QuestManager.
                    quest_obj = Quest.from_dict(quest_data_item)
                    quest_obj.selected_language = player_lang # Устанавливаем язык для i18n свойств Quest

                    quest_name = quest_obj.name # Это свойство должно использовать self.selected_language

                    current_objective_desc = ""
                    current_stage_id = quest_data_item.get('current_stage_id')

                    if current_stage_id:
                        # get_stage_description и get_stage_title должны использовать self.selected_language
                        stage_title = quest_obj.get_stage_title(current_stage_id)
                        stage_desc = quest_obj.get_stage_description(current_stage_id)
                        if stage_title and stage_title != f"Stage {current_stage_id} Title": # Проверка на заглушку
                            current_objective_desc = f"{stage_title}: {stage_desc}"
                        else:
                            current_objective_desc = stage_desc

                    if not current_objective_desc or "not found" in current_objective_desc.lower():
                        current_objective_desc = quest_obj.description # Фоллбэк на общее описание квеста

                    if quest_name and "not found" not in quest_name.lower():
                        if "not found" in current_objective_desc.lower() or not current_objective_desc.strip(): # Added check for empty/whitespace only
                            current_objective_desc = get_i18n_text(None, "objective_not_specified_label", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Objective details not specified.")
                        description_text += f"- {quest_name}: {current_objective_desc}\n"


        # --- Выходы из локации ---
        # или exits: {'exit_name_key': {'target_loc_id': 'id1', 'name_i18n': {'en': 'North', 'ru': 'Север'}}}
        # Предположим, что exits_data.get('exits') возвращает что-то вроде:
        # {'north_exit': {'target_location_id': 'some_loc_id', 'name_i18n': {'en': 'North Gate', 'ru': 'Северные Врата'}}}
        exits_data = location_data.get('exits', {})

        if exits_data:
            exits_label = get_i18n_text(None, 'exits_label', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text='Exits:')
            # Ensure a blank line before this section if there were quests, or entities, or main description
            if (self._quest_manager and viewer_char_obj and active_quest_data_list) or \
               entities_to_list or \
               (main_description_parts and any(part for part in main_description_parts if part != location_description_base or part)):
                description_text += "\n"
            description_text += f"{exits_label}\n"

            sorted_exit_keys = sorted(exits_data.keys())

            for exit_key in sorted_exit_keys:
                exit_info = exits_data[exit_key] # Это словарь {'target_location_id': ..., 'name_i18n': ...}
                target_location_id_exit = exit_info.get('target_location_id')

                # Получаем локализованное имя выхода
                exit_display_name = get_i18n_text(exit_info, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text=exit_key.capitalize())

                # Пытаемся получить имя целевой локации (также локализованное)
                # Это потребует, чтобы get_location_name также поддерживал i18n или возвращал i18n словарь
                # Пока что, если get_location_name возвращает просто строку, используем ее.
                # Для полного i18n, get_location_name должен возвращать объект локации или ее name_i18n.
                # Здесь мы предполагаем, что get_location_static вернет данные с name_i18n для целевой локации.
                target_location_static_data = self._location_manager.get_location_static(target_location_id_exit)
                target_location_name_display = target_location_id_exit # fallback
                if target_location_static_data:
                    target_location_name_display = get_i18n_text(target_location_static_data, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text=target_location_id_exit)

                # TODO: Локализовать "ведет в"
                description_text += f"- **{exit_display_name}** {get_i18n_text(None, 'leads_to_label', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text='ведет в')} '{target_location_name_display}'\n"
        else:
            # TODO: Локализовать "Выходов из этой локации нет."
            description_text += f"\n{get_i18n_text(None, 'no_exits_label', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text='Выходов из этой локации нет.')}\n"

        print(f"WorldViewService: Location description generated for {location_id} in language {player_lang}.")
        return description_text


    # Метод для получения подробного описания конкретной сущности (для команды /look <target>)
    # Вызывается из CommandRouter.
    async def get_entity_details(self,
                                 guild_id: str, # ID сервера/гильдии для получения Character
                                 entity_id: str,
                                 entity_type: str, # Тип сущности ('Character', 'NPC', 'Item', 'Party')
                                 viewer_entity_id: str, # ID сущности, которая осматривает (Char/NPC)
                                 viewer_entity_type: str, # Тип сущности ('Character', 'NPC')
                                 **kwargs # Дополнительные менеджеры/сервисы, переданные из CommandRouter
                                ) -> Optional[str]:
        """
        Генерирует подробное текстовое описание конкретной сущности с учетом i18n.
        Использует RuleEngine для определения глубины деталей и OpenAI для описания.
        Возвращает форматированный текст или None при ошибке/сущность не найдена.
        """
        print(f"WorldViewService: Generating details for entity {entity_type} ID {entity_id} for viewer {viewer_entity_type} ID {viewer_entity_id} in guild {guild_id}.")

        # Определяем язык игрока (аналогично get_location_description)
        player_lang = DEFAULT_BOT_LANGUAGE
        viewer_char_obj_details: Optional[Character] = None # Указываем тип явно
        if viewer_entity_type == 'Character':
            viewer_char_obj_details = self._character_manager.get_character(guild_id, viewer_entity_id)
            if viewer_char_obj_details and viewer_char_obj_details.selected_language:
                player_lang = viewer_char_obj_details.selected_language
        print(f"WorldViewService: Using language '{player_lang}' for entity details {entity_id}.")

        entity: Optional[Any] = None # Объект сущности
        manager: Optional[Any] = None # Менеджер сущности

        # Получаем объект сущности по типу и ID из соответствующего менеджера
        if entity_type == 'Character' and self._character_manager:
             # Предполагаем, что get_character для целевой сущности также может нуждаться в guild_id, если это персонаж игрока
             # Если entity_id это ID персонажа, то guild_id нужен. Если это NPC/Item/Party, то нет.
             # Для простоты, если это Character, передаем guild_id. CharacterManager должен это обработать.
             entity = self._character_manager.get_character(guild_id, entity_id)
             manager = self._character_manager
        elif entity_type == 'NPC' and self._npc_manager:
             entity = self._npc_manager.get_npc(entity_id) # NPCs обычно не привязаны к guild_id так же, как Characters
             manager = self._npc_manager
        elif entity_type == 'Item' and self._item_manager:
             entity = self._item_manager.get_item(entity_id) # Items тоже обычно не привязаны к guild_id
             manager = self._item_manager
        elif entity_type == 'Party' and self._party_manager:
             entity = self._party_manager.get_party(entity_id) # Parties тоже обычно не привязаны к guild_id
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
        #      'status_manager': self._status_manager, # 'combat_manager': self._combat_manager, # Закомментировано в оригинале
        #      'rule_engine': self._rule_engine,
        #      'openai_service': self._openai_service,
        #      **kwargs
        # }
        # observer_obj = viewer_char_obj_details # Уже получили его для языка
        # if not observer_obj and viewer_entity_type == 'NPC': # Если смотрящий - NPC
        #    observer_obj = self._npc_manager.get_npc(viewer_entity_id)

        # observed_details = {}
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
        # Предполагаем, что entity.name может быть словарем name_i18n или строкой
        # Если это объект модели, у него может быть метод to_dict(), который вернет name_i18n
        entity_data_for_i18n = entity
        if hasattr(entity, 'to_dict'): # Если у сущности есть метод to_dict()
            entity_data_for_i18n = entity.to_dict()

        entity_name = get_i18n_text(entity_data_for_i18n, 'name_i18n', player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text=getattr(entity, 'name', 'Unknown Entity'))

        # TODO: Локализовать entity_type, если это еще не сделано
        entity_type_display_details = get_i18n_text(None, f"entity_type_{entity_type.lower()}", player_lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text=entity_type)

        description_text += f"**{entity_name}** ({entity_type_display_details})\n"
        description_text += f"ID: {entity_id}\n" # Для отладки, не требует i18n

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
        # Для i18n, строки типа "Здоровье:", "Жив:", "Да", "Нет" и т.д. должны быть локализованы.
        def _format_basic_entity_details_placeholder(entity_obj: Any, entity_type_str: str, lang: str, observed_details_dict: Dict[str, Any]) -> str:
            details = ""

            # Локализация общих меток
            type_label = get_i18n_text(None, "label_type", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Тип")
            name_label = get_i18n_text(None, "label_name", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Имя")
            health_label = get_i18n_text(None, "label_health", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Здоровье")
            alive_label = get_i18n_text(None, "label_alive", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Жив")
            yes_label = get_i18n_text(None, "label_yes", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Да")
            no_label = get_i18n_text(None, "label_no", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Нет")
            template_label = get_i18n_text(None, "label_template", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Шаблон")
            owner_id_label = get_i18n_text(None, "label_owner_id", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Владелец ID")
            location_id_label = get_i18n_text(None, "label_location_id", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Локация ID")
            leader_id_label = get_i18n_text(None, "label_leader_id", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Лидер ID")
            members_label = get_i18n_text(None, "label_members", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Участники")
            none_label = get_i18n_text(None, "label_none", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="нет")
            unknown_label = get_i18n_text(None, "label_unknown", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="Неизвестно")
            na_label = get_i18n_text(None, "label_na", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text="N/A")

            entity_display_name = get_i18n_text(entity_obj.to_dict() if hasattr(entity_obj, 'to_dict') else entity_obj, 'name_i18n', lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text=getattr(entity_obj, 'name', unknown_label))
            entity_type_display_placeholder = get_i18n_text(None, f"entity_type_{entity_type_str.lower()}", lang, default_lang=DEFAULT_BOT_LANGUAGE, default_text=entity_type_str)

            details += f"{type_label}: {entity_type_display_placeholder}\n"
            details += f"{name_label}: {entity_display_name}\n"

            if entity_type_str in ['Character', 'NPC']:
                 health_val = getattr(entity_obj, 'health', na_label)
                 max_health_val = getattr(entity_obj, 'max_health', na_label)
                 details += f"{health_label}: {health_val}/{max_health_val}\n"
                 is_alive_val = yes_label if getattr(entity_obj, 'is_alive', False) else no_label
                 details += f"{alive_label}: {is_alive_val}\n"
                 # TODO: Статус-эффекты и инвентарь также нуждаются в i18n для названий статусов/предметов

            elif entity_type_str == 'Item':
                 details += f"{template_label}: {getattr(entity_obj, 'template_id', na_label)}\n"
                 details += f"{owner_id_label}: {getattr(entity_obj, 'owner_id', none_label)}\n"
                 details += f"{location_id_label}: {getattr(entity_obj, 'location_id', none_label)}\n"

            elif entity_type_str == 'Party':
                 details += f"{leader_id_label}: {getattr(entity_obj, 'leader_id', none_label)}\n"
                 members = getattr(entity_obj, 'members', [])
                 members_count = len(members)
                 members_list_str = ', '.join(members) if members else none_label
                 details += f"{members_label} ({members_count}): {members_list_str}\n"

            # TODO: observed_details также могут содержать ключи или значения, требующие i18n.

            return details

        # Использование заглушки или реального метода форматирования с передачей языка
        description_text += _format_basic_entity_details_placeholder(entity, entity_type, player_lang, {}) # Пока без RuleEngine деталей

        print(f"WorldViewService: Entity details generated for {entity_type} ID {entity_id} in language {player_lang}.")
        return description_text


    # TODO: Вспомогательный метод для получения краткого описания сущности (для списка в get_location_description)
    # def _get_entity_summary(self, entity: Any) -> Dict[str, Any]: ...
    # Должен возвращать словарь вроде {'id': entity.id, 'type': 'Character', 'name': entity.name, 'status': 'Healthy'}

# Конец класса WorldViewService
