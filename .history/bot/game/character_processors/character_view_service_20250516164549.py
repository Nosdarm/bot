# bot/game/character_processors/character_view_service.py

from __future__ import annotations
import discord
import traceback
import json # Может понадобиться для отладки JSON полей
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING

# Модели
from bot.game.models.character import Character # Импортируем модель Character
# from bot.game.models.item import Item # Если есть модель Item
# from bot.game.models.location import Location # Если есть модель Location
# from bot.game.models.party import Party # Если есть модель Party
# from bot.game.models.status import StatusEffect # Если есть модель StatusEffect Template

if TYPE_CHECKING:
    # Импорты менеджеров, которые нужны CharacterViewService для получения данных
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager # Нужен для получения информации о предметах в инвентаре
    from bot.game.managers.location_manager import LocationManager # Нужен для получения названия локации
    from bot.game.managers.status_manager import StatusManager # Нужен для получения информации о статусах
    from bot.game.managers.party_manager import PartyManager # Нужен для получения информации о группе
    from bot.game.rules.rule_engine import RuleEngine


class CharacterViewService:
    """
    Сервис для формирования представлений данных персонажа (например, листа персонажа, инвентаря)
    для отправки в Discord (в основном в виде Embeds).
    """
    def __init__(
        self,
        character_manager: CharacterManager,
        item_manager: Optional[ItemManager] = None,
        location_manager: Optional[LocationManager] = None,
        rule_engine: Optional[RuleEngine] = None,
        status_manager: Optional[StatusManager] = None,
        party_manager: Optional[PartyManager] = None,
        # TODO: Добавить другие нужные менеджеры
    ):
        print("Initializing CharacterViewService...")
        self._character_manager = character_manager
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._party_manager = party_manager
        # TODO: Добавить другие нужные менеджеры

        print("CharacterViewService initialized.")

    async def get_character_sheet_embed(self, character: Character) -> Optional[discord.Embed]:
        """
        Формирует и возвращает Discord Embed с информацией о листе персонажа.
        Принимает объект персонажа (Character).
        """
        print(f"CharacterViewService: Generating sheet embed for character {character.id} ({character.name}).")

        if not isinstance(character, Character):
            print("CharacterViewService: Invalid character object provided.")
            return None

        try:
            embed = discord.Embed(
                title=f"Лист персонажа: {character.name}",
                color=discord.Colour.blue()
            )
            # Добавляем изображение персонажа, если оно есть (например, URL в модели)
            # if hasattr(character, 'image_url') and character.image_url:
            #     embed.set_thumbnail(url=character.image_url)

            # --- Основные данные ---
            embed.add_field(name="Уровень", value=str(character.level), inline=True)
            embed.add_field(name="Опыт", value=str(character.xp), inline=True)
            embed.add_field(name="Здоровье", value=f"{character.health}/{character.max_health}", inline=True)

            # TODO: Добавить валюту, если есть (character.currency)
            # if hasattr(character, 'currency'):
            #      embed.add_field(name="Валюта", value=str(character.currency), inline=True)


            # --- Текущая локация и группа ---
            location_name = "Неизвестно"
            if character.location_id and self._location_manager:
                 try:
                      # Предполагаем, что get_location возвращает объект Location с атрибутом .name
                      location = self._location_manager.get_location(character.location_id)
                      if location and hasattr(location, 'name'):
                           location_name = location.name
                 except Exception as e:
                      print(f"CharacterViewService: Error getting location {character.location_id}: {e}")
                      location_name = f"Ошибка ({character.location_id[:4]}...)"
            embed.add_field(name="Локация", value=location_name, inline=False)

            party_text = "Не состоит в группе."
            if character.party_id and self._party_manager:
                 try:
                      # Предполагаем, что get_party возвращает объект Party с атрибутом .name
                      party = self._party_manager.get_party(character.party_id)
                      if party and hasattr(party, 'name') and party.name:
                           party_text = party.name
                      else:
                          party_text = f"Группа ID: {character.party_id[:4]}..."
                 except Exception as e:
                      print(f"CharacterViewService: Error getting party {character.party_id}: {e}")
                      party_text = f"Ошибка группы ({character.party_id[:4]}...)"
            embed.add_field(name="Группа", value=party_text, inline=False)


            # --- Характеристики ---
            stats_text = "Нет данных."
            if isinstance(character.stats, dict) and character.stats:
                 stats_lines = [f"**{stat.capitalize()}:** {value}" for stat, value in character.stats.items()]
                 stats_text = "\n".join(stats_lines)
            embed.add_field(name="Характеристики", value=stats_text, inline=False)

            # --- Навыки ---
            skills_text = "Нет данных."
            if isinstance(character.skills, dict) and character.skills:
                 skills_lines = [f"**{skill.capitalize()}:** {value}" for skill, value in character.skills.items()]
                 skills_text = "\n".join(skills_lines)
            embed.add_field(name="Навыки", value=skills_text, inline=False)

            # --- Состояния (Статусные эффекты) ---
            status_effects_text = "Нет активных эффектов."
            if isinstance(character.status_effects, list) and character.status_effects and self._status_manager:
                 try:
                     status_names = []
                     # character.status_effects - это список Status IDs (строк)
                     for status_id in character.status_effects:
                         # Предполагаем, что StatusManager может вернуть отображаемое имя по ID
                         # get_status_display_name нужно реализовать в StatusManager
                         # display_name = await self._status_manager.get_status_display_name(status_id)
                         # status_names.append(display_name or f"ID:{status_id[:4]}...")
                         status_names.append(f"ID:{status_id[:4]}...") # Пока используем ID как заглушку

                     if status_names:
                          status_effects_text = ", ".join(status_names)
                 except Exception as e:
                     print(f"CharacterViewService: Error processing status effects for {character.id}: {e}")
                     traceback.print_exc()
                     status_effects_text = "Ошибка загрузки эффектов."

            embed.add_field(name="Состояния", value=status_effects_text, inline=False)


            # --- Инвентарь ---
            inventory_text = "Инвентарь пуст."
            # character.inventory - это список Item IDs (строк)
            if isinstance(character.inventory, list) and character.inventory and self._item_manager:
                 try:
                     # Для отображения в инвентаре обычно нужны названия предметов.
                     # Инвентарь - это список ID, поэтому мы можем получить список названий.
                     # Если есть несколько одинаковых ID, мы можем их посчитать.

                     item_counts: Dict[str, int] = {}
                     item_name_map: Dict[str, str] = {} # Для кэширования названий

                     for item_id in character.inventory:
                         # Предполагаем, что ItemManager может получить шаблон предмета по ID ЭКЗЕМПЛЯРА
                         # или получить название по ID экземпляра.
                         # get_item_template_by_instance_id нужно реализовать в ItemManager,
                         # или просто get_item(item_id) -> Item object, а у Item есть .template_id и .name
                         # А лучше, если ItemManager имеет метод get_item_name(item_id_instance)
                         item_name = f"Предмет (ID:{item_id[:4]}...)" # Заглушка названия
                         # if item_id not in item_name_map:
                         #      # item_template = await self._item_manager.get_item_template_by_instance_id(item_id)
                         #      # if item_template and hasattr(item_template, 'name'):
                         #      #      item_name = item_template.name
                         #      # item_name_map[item_id] = item_name # Кэшируем название по ID экземпляра

                         item_counts[item_name] = item_counts.get(item_name, 0) + 1

                     if item_counts:
                         item_list_lines = []
                         for name, count in item_counts.items():
                             item_list_lines.append(f"{name} x{count}")

                         # Ограничиваем вывод, если инвентарь очень большой
                         max_items_to_show = 10 # Настроить
                         inventory_text = "\n".join(item_list_lines[:max_items_to_show])
                         if len(item_list_lines) > max_items_to_show:
                              inventory_text += f"\n...и еще {len(item_counts) - max_items_to_show} уникальных предметов."
                     else:
                          inventory_text = "Инвентарь пуст."

                 except Exception as e:
                     print(f"CharacterViewService: Error processing inventory for {character.id}: {e}")
                     traceback.print_exc()
                     inventory_text = "Ошибка загрузки инвентаря."
            else:
                 inventory_text = "Инвентарь пуст." # Если inventory_data не список или пустой


            embed.add_field(name="Инвентарь", value=inventory_text, inline=False)


            # TODO: Добавить поле для Текущего действия + Очереди действий
            action_text = "Бездействует"
            if character.current_action:
                 # Пример, если current_action имеет поля 'type', 'progress', 'total_duration'
                 action_type = character.current_action.get('type', 'Неизвестное действие')
                 progress = character.current_action.get('progress', 0)
                 total_duration = character.current_action.get('total_duration', 0)
                 if total_duration > 0:
                      action_text = f"Действие: {action_type.capitalize()} ({progress}/{total_duration} ед. времени)"
                 else:
                      action_text = f"Действие: {action_type.capitalize()}"
            elif character.action_queue:
                 action_text = f"Очередь: {len(character.action_queue)} ожидающих действий."
            embed.add_field(name="Активность", value=action_text, inline=False)


            # Футер (можно добавить ID или другое)
            embed.set_footer(text=f"Персонаж ID: {character.id}")


            return embed

        except Exception as e:
            print(f"CharacterViewService: Critical error generating sheet embed for character {character.id}: {e}")
            traceback.print_exc()
            # Возвращаем None при любой ошибке, CommandRouter обработает это
            return None


    # TODO: Добавить другие методы для просмотра (например, инвентарь отдельно, описание локации, описание NPC)
    # async def get_character_inventory_embed(self, character: Character) -> Optional[discord.Embed]: ...
    # async def get_location_description_embed(self, location_id: str, character_id: str) -> Optional[discord.Embed]: ...
    # async def get_entity_description_embed(self, entity_identifier: str, character_id: str) -> Optional[discord.Embed]: ...
