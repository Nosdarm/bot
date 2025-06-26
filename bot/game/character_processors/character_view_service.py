# bot/game/character_processors/character_view_service.py

from __future__ import annotations
import discord
import traceback
import json
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union, TypedDict # Добавлен Union and TypedDict
from collections import Counter # Added Counter for inventory aggregation

# Модели
# Импортируем модели, которые могут понадобиться для проверки isinstance или доступа к атрибутам в менеджерах
from bot.game.models.character import Character
# Импорт моделей, которые возвращают менеджеры и используются в аннотациях или логике
# Убедитесь, что эти модели действительно используются здесь после получения из менеджера
# from bot.game.models.item import Item # Если get_item возвращает объект Item
# from bot.game.models.location import Location # Если get_location возвращает объект Location
# from bot.game.models.party import Party # Если get_party возвращает объект Party
# from bot.game.models.status import StatusEffectInstance # Если get_status_effect_instance возвращает объект StatusEffectInstance
# from bot.game.models.item import ItemTemplate # Если get_item_template возвращает объект ItemTemplate


# Define TypedDict for more specific field data
class EmbedFieldData(TypedDict):
    name: str
    value: str
    inline: bool


if TYPE_CHECKING:
    # Импорты менеджеров, которые нужны CharacterViewService для получения данных
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.rules.rule_engine import RuleEngine
    # TODO: Добавить импорты менеджеров, которые могут быть в context, если они нужны здесь
    # from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.equipment_manager import EquipmentManager
    from bot.game.managers.inventory_manager import InventoryManager
    from bot.game.managers.ability_manager import AbilityManager
    from bot.game.managers.spell_manager import SpellManager


class CharacterViewService:
    """
    Сервис для формирования представлений данных персонажа (например, листа персонажа, инвентаря)
    для отправки в Discord (в основном в виде Embeds).
    """
    def __init__(
        self,
        character_manager: "CharacterManager", # Use string literal for __init__
        item_manager: Optional["ItemManager"] = None, # Use string literal
        location_manager: Optional["LocationManager"] = None, # Use string literal
        rule_engine: Optional["RuleEngine"] = None, # Use string literal
        status_manager: Optional["StatusManager"] = None, # Use string literal
        party_manager: Optional["PartyManager"] = None, # Use string literal
        equipment_manager: Optional["EquipmentManager"] = None,
        inventory_manager: Optional["InventoryManager"] = None,
        ability_manager: Optional["AbilityManager"] = None,
        spell_manager: Optional["SpellManager"] = None,
        # TODO: Добавить другие нужные менеджеры, если они инжектируются
        # npc_manager: Optional["NpcManager"] = None, # Пример: если нужен здесь
    ):
        print("Initializing CharacterViewService...")
        self._character_manager = character_manager
        self._item_manager = item_manager # Храним инжектированные менеджеры
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._equipment_manager = equipment_manager
        self._inventory_manager = inventory_manager
        self._ability_manager = ability_manager
        self._spell_manager = spell_manager
        # self._npc_manager = npc_manager # Храним инжектированные менеджеры

        print("CharacterViewService initialized.")


    # ИСПРАВЛЕНО: Добавляем context и **kwargs в сигнатуру
    async def get_character_sheet_embed(
        self,
        character: Character, # Принимает объект персонажа
        context: Dict[str, Any], # <-- ДОБАВЛЕННЫЙ ПАРАМЕТР context
        **kwargs: Any # <-- ДОБАВЛЕННЫЙ ПАРАМЕТР для других ключевых аргументов
    ) -> Optional[discord.Embed]: # Убедитесь, что discord.Embed импортирован
        """
        Формирует и возвращает Discord Embed с информацией о листе персонажа.
        character: Объект Character для отображения.
        context: Словарь контекста (содержит менеджеры, channel_id, guild_id и т.д.).
        """
        # Исправлено логирование, чтобы использовать безопасный доступ и получать guild_id из контекста
        char_id = getattr(character, 'id', 'N/A')
        char_name = getattr(character, 'name', 'Без имени')
        guild_id = context.get('guild_id', 'N/A')
        print(f"CharacterViewService: Generating sheet embed for character {char_id} ({char_name}) in guild {guild_id}...")


        if not isinstance(character, Character):
            print(f"CharacterViewService: Invalid character object provided for sheet embed: {character}")
            return None

        try:
            embed = discord.Embed(
                title=f"Лист персонажа: {char_name}",
                color=discord.Color.blue()
            )
            embed.description = f"ID: `{char_id}`\nDiscord ID: `{getattr(character, 'discord_user_id', 'N/A')}`"


            # --- Основные данные ---
            embed.add_field(name="Уровень", value=str(getattr(character, 'level', 1)), inline=True)
            embed.add_field(name="Опыт", value=str(getattr(character, 'xp', 0)), inline=True)
            embed.add_field(name="Здоровье", value=f"{getattr(character, 'health', 100.0)}/{getattr(character, 'max_health', 100.0)}", inline=True)

            # TODO: Добавить валюту, если есть (character.currency)
            # currency = getattr(character, 'currency', None)
            # if currency is not None:
            #      embed.add_field(name="Валюта", value=str(currency), inline=True)


            # --- Текущая локация и группа ---
            location_name = "Неизвестно"
            loc_id = getattr(character, 'location_id', None)
            # Используем LocationManager из контекста или инжектированный self._
            loc_manager = context.get('location_manager', self._location_manager) # Use manager from context first, then self._

            if loc_id and loc_manager and hasattr(loc_manager, 'get_location'): # Предполагаем get_location(guild_id, location_id) -> Optional[Location]
                 try:
                      # Убедитесь в сигнатуре get_location - требует guild_id
                      location = loc_manager.get_location(guild_id, loc_id) # Передаем guild_id из контекста
                      if location and hasattr(location, 'name') and location.name:
                           location_name = getattr(location, 'name')
                      elif loc_id: # Если ID локации есть, но объект не найден или без имени
                           location_name = f"Локация ID: {str(loc_id)[:4]}..." # Показываем хотя бы часть ID
                 except Exception as e:
                      print(f"CharacterViewService: Error getting location {loc_id} for char {char_id} in guild {guild_id}: {e}")
                      traceback.print_exc()
                      location_name = f"Ошибка локации ({str(loc_id)[:4]}...)"
            elif loc_id: # Если location_id есть, но менеджера нет или не нашел
                 location_name = f"Локация ID: {str(loc_id)[:4]}..." # Показываем хотя бы часть ID

            embed.add_field(name="Локация", value=location_name, inline=False)

            # Party info
            party_text = "Не состоит в группе."
            party_id = getattr(character, 'party_id', None)
            # Используем PartyManager из контекста или инжектированный self._
            party_manager = context.get('party_manager', self._party_manager) # Use manager from context first, then self._

            if party_id and party_manager and hasattr(party_manager, 'get_party'): # Предполагаем get_party(guild_id, party_id) -> Optional[Party]
                 try:
                      # Убедитесь в сигнатуре get_party - требует guild_id
                      party = party_manager.get_party(guild_id, party_id) # Передаем guild_id из контекста
                      if party and hasattr(party, 'name') and party.name:
                           party_text = f"Группа: {getattr(party, 'name')}"
                      elif party_id: # Если ID группы есть, но объект не найден или без имени
                          party_text = f"Группа ID: {str(party_id)[:4]}..."
                 except Exception as e:
                      print(f"CharacterViewService: Error getting party {party_id} for char {char_id} in guild {guild_id}: {e}")
                      traceback.print_exc()
                      party_text = f"Ошибка группы ({str(party_id)[:4]}...)"
            elif party_id: # Если party_id есть, но менеджера нет или не нашел
                 party_text = f"Группа ID: {str(party_id)[:4]}..." # Показываем хотя бы часть ID

            embed.add_field(name="Группа", value=party_text, inline=False)


            # --- Характеристики ---
            stats_text = "Нет данных."
            stats_data = getattr(character, 'stats', {}) # Safely get stats
            if isinstance(stats_data, dict) and stats_data:
                 # Сортируем характеристики по имени для стабильного порядка
                 sorted_stats = sorted(stats_data.items())
                 stats_lines = [f"**{stat.capitalize()}:** {value}" for stat, value in sorted_stats]
                 stats_text = "\n".join(stats_lines)
            embed.add_field(name="Характеристики", value=stats_text, inline=False)

            # --- Навыки ---
            skills_text = "Нет данных."
            skills_data = getattr(character, 'skills', {}) # Safely get skills
            if isinstance(skills_data, dict) and skills_data:
                 # Сортируем навыки
                 sorted_skills = sorted(skills_data.items())
                 skills_lines = [f"**{skill.capitalize()}:** {value}" for skill, value in sorted_skills]
                 skills_text = "\n".join(skills_lines)
            embed.add_field(name="Навыки", value=skills_text, inline=False)

            # --- Состояния (Статусные эффекты) ---
            status_effects_text = "Нет активных эффектов."
            status_effects_data = getattr(character, 'status_effects', []) # Safely get status_effects
            # Используем StatusManager из контекста или инжектированный self._
            status_manager = context.get('status_manager', self._status_manager) # Use manager from context first, then self._

            if isinstance(status_effects_data, list) and status_effects_data and status_manager:
                 try:
                     status_names = []
                     # character.status_effects - это список Status ID'ов экземпляров (строк)
                     # StatusManager должен уметь получить информацию об экземпляре статуса по ID экземпляра
                     # get_status_effect_instance is likely sync
                     if hasattr(status_manager, 'get_status_effect_instance') and hasattr(status_manager, 'get_status_display_name'):
                          # Итерируем по копии, если список может меняться во время отображения
                          for status_id_instance in list(status_effects_data):
                               try:
                                    if not isinstance(status_id_instance, str):
                                         print(f"CharacterViewService: Warning: Invalid status effect ID format for char {char_id}: {status_id_instance} ({type(status_id_instance)}). Skipping.")
                                         continue

                                    # Убедитесь в сигнатуре get_status_effect_instance - возможно, тоже требуется guild_id?
                                    # Если метод async, нужно await
                                    status_instance = status_manager.get_status_effect_instance(status_id_instance) # Assume sync and takes instance ID

                                    if status_instance:
                                        # Получаем отображаемое имя статуса
                                        # get_status_display_name может быть async или sync, зависит от реализации StatusManager
                                        # Если sync:
                                        display_name = status_manager.get_status_display_name(status_instance=status_instance) # Assume sync and takes instance object
                                        # Если async:
                                        # display_name = await status_manager.get_status_display_name(status_instance=status_instance)

                                        status_names.append(display_name or f"ID:{status_id_instance[:4]}...") # Показываем ID если имя не получено
                                    else:
                                         status_names.append(f"ID:{status_id_instance[:4]}... (не найден)") # Если экземпляр статуса не найден

                               except Exception as e:
                                    print(f"CharacterViewService: Error processing status effect instance {status_id_instance} for char {char_id} in guild {guild_id}: {e}")
                                    traceback.print_exc()
                                    status_names.append(f"ID:{status_id_instance[:4]}... (ошибка)")

                          if status_names:
                               status_effects_text = ", ".join(status_names)

                 except Exception as e: # Ловим ошибки выше уровня итерации
                     print(f"CharacterViewService: Error processing status effects list for {char_id} in guild {guild_id}: {e}")
                     traceback.print_exc()
                     status_effects_text = "Ошибка загрузки эффектов."
            elif isinstance(status_effects_data, list) and not status_effects_data: # Если список пустой
                 status_effects_text = "Нет активных эффектов."
            else: # Если status_effects_data не список или не доступен
                 print(f"CharacterViewService: Warning: status_effects data is not a list ({type(status_effects_data)}) for char {char_id}.")
                 status_effects_text = "Нет данных о состояниях." # Более точное сообщение

            embed.add_field(name="Состояния", value=status_effects_text, inline=False)


            # --- Инвентарь (Вызываем отдельный метод для получения ПОЛЯ) ---
            # Вызываем вспомогательный метод для получения данных поля инвентаря
            inventory_embed_field_data = await self._get_inventory_embed_field_data(character, context, **kwargs) # <-- ИСПРАВЛЕНО ИМЯ МЕТОДА ИЗ LOGA
            if inventory_embed_field_data:
                 # Если метод вернул данные поля (словарь), добавляем их в основной embed
                 embed.add_field(**inventory_embed_field_data) # Добавляем поле инвентаря
            # Если метод вернул None (хотя он должен возвращать dict даже для пустого инвентаря),
            # то произошла ошибка в _get_inventory_embed_field_data (она там логируется).
            # Добавление поля-заглушки в этом случае уже делается внутри _get_inventory_embed_field_data.


            # TODO: Добавить поле для Текущего действия + Очереди действий
            action_text = "Бездействует"
            current_action_data = getattr(character, 'current_action', None) # Safely get current_action
            action_queue_data = getattr(character, 'action_queue', []) # Safely get action_queue

            if current_action_data:
                 # Пример, если current_action имеет поля 'type', 'progress', 'total_duration'
                 action_type = current_action_data.get('type', 'Неизвестное действие')
                 progress = current_action_data.get('progress', 0)
                 total_duration = current_action_data.get('total_duration', 0)
                 if total_duration > 0:
                      action_text = f"Действие: {str(action_type).capitalize()} ({progress}/{total_duration} ед. времени)" # Ensure string type for safety
                 else:
                      action_text = f"Действие: {str(action_type).capitalize()}"
            elif isinstance(action_queue_data, list) and action_queue_data: # Проверяем очередь, только если нет текущего действия
                 # Показываем тип следующего действия, если есть
                 next_action = action_queue_data[0].get('type', 'Неизвестно') if action_queue_data and isinstance(action_queue_data[0], dict) else 'Неизвестно'
                 action_text = f"В очереди: {len(action_queue_data)} ({str(next_action)}...)" # Ensure string type for safety
            else: # Если current_action is None и action_queue is empty list
                 action_text = "Бездействует." # Убедимся, что строка с точкой для консистентности

            embed.add_field(name="Активность", value=action_text, inline=False)


            # Футер (можно добавить ID или другое)
            embed.set_footer(text=f"Персонаж ID: {char_id}") # Use local char_id var


            return embed

        except Exception as e:
            # Логируем с контекстом гильдии и ID персонажа
            print(f"CharacterViewService: Critical error generating sheet embed for character {char_id} in guild {guild_id}: {e}")
            traceback.print_exc()
            return None # Возвращаем None при любой ошибке, CommandRouter обработает это


    # --- Метод для инвентаря (ВЫНЕСЕН В ОТДЕЛЬНЫЙ МЕТОД ДЛЯ КОМАНДЫ /inventory) ---
    # Этот метод генерирует полный Embed для инвентаря
    async def get_inventory_embed(self, character: Character, context: Dict[str, Any], **kwargs: Any) -> Optional[discord.Embed]:
         """
         Генерирует и возвращает Discord Embed с содержимым инвентаря персонажа.
         Используется командой /inventory.
         """
         char_id = getattr(character, 'id', 'N/A')
         print(f"CharacterViewService: Generating standalone inventory embed for character {char_id}...")

         if not isinstance(character, Character):
             print(f"CharacterViewService: Invalid character object provided for standalone inventory embed: {character}")
             return None

         # Вызываем вспомогательный метод для получения данных поля инвентаря
         # (Этот метод генерирует контент для поля, а не весь Embed)
         inventory_field_data = await self._get_inventory_embed_field_data(character, context, **kwargs)

         # Создаем основной Embed
         embed = discord.Embed(
              title=f"Инвентарь: {getattr(character, 'name', 'Без имени')}",
              color=discord.Color.blue()
         )

         # Добавляем данные поля инвентаря в Embed
         if inventory_field_data:
              embed.add_field(**inventory_field_data)
         # else: _get_inventory_embed_field_data already handles empty/error text within its value


         embed.set_footer(text=f"Персонаж ID: {char_id}") # Use local char_id var

         print(f"CharacterViewService: Finished generating standalone inventory embed for character {char_id}.")
         return embed


    # --- Вспомогательный метод для получения данных ПОЛЯ инвентаря ---
    # Возвращает данные поля (name, value, inline) для вставки в другой Embed (например, в лист персонажа).
    # Возвращает dict {name, value, inline}.
    # (Не возвращает None, чтобы всегда было поле, пусть даже с сообщением "Инвентарь пуст")
    async def _get_inventory_embed_field_data(self, character: Character, context: Dict[str, Any], **kwargs: Any) -> EmbedFieldData:
         """
         Вспомогательный метод для генерации данных для поля Embed с инвентарем.
         Возвращает dict с ключами 'name', 'value', 'inline'.
         Всегда возвращает словарь поля, даже если инвентарь пуст или ошибка.
         """
         char_id = getattr(character, 'id', 'N/A')
         guild_id = context.get('guild_id', 'N/A')
         print(f"CharacterViewService: Generating inventory embed field data for character {char_id} in guild {guild_id}...")


         inventory_text = "Инвентарь пуст."
         inventory_data = getattr(character, 'inventory', []) # Safely get inventory data
         # Используем ItemManager из контекста или инжектированный self._
         item_manager = context.get('item_manager', self._item_manager) # Use manager from context first, then self._


         # Предполагаем, что character.inventory - это List[Dict[str, Any]] с полями 'item_id' (template ID), 'quantity'
         if isinstance(inventory_data, list) and item_manager: # Нужен item_manager для получения названий
              try:
                  item_display_list: List[str] = []
                  item_template_name_map: Dict[str, str] = {} # Кэш названий шаблонов

                  # Filter out non-dict entries before processing
                  valid_inventory_entries = [entry for entry in inventory_data if isinstance(entry, dict) and 'item_id' in entry]


                  if hasattr(item_manager, 'get_item_template'): # Предполагаем метод get_item_template(guild_id, item_template_id) -> Optional[ItemTemplate]
                       # Собираем названия шаблонов
                       item_template_ids_to_fetch = {str(entry['item_id']) for entry in valid_inventory_entries if entry.get('item_id') is not None} # Use str() to ensure string IDs for lookup
                       for template_id_str in item_template_ids_to_fetch:
                            try:
                                 # get_item_template может быть async или sync. Должен принимать guild_id
                                 # Если sync:
                                 item_template = item_manager.get_item_template(guild_id, template_id_str) # <- Pass guild_id!

                                 if item_template and hasattr(item_template, 'name'):
                                      item_template_name_map[template_id_str] = getattr(item_template, 'name') # Use str ID as key
                                 else:
                                      item_template_name_map[template_id_str] = f"Шаблон ID:{template_id_str[:4]}..." # Заглушка названия шаблона

                            except Exception as e:
                                 print(f"CharacterViewService: Error getting item template {template_id_str} for char {char_id} in guild {guild_id}: {e}")
                                 traceback.print_exc()
                                 item_template_name_map[template_id_str] = f"Шаблон ID:{template_id_str[:4]}... (ошибка)"


                       # Теперь формируем строки инвентаря, используя собранные названия
                       item_counts: Dict[str, Union[int, float]] = {} # Используем Union т.к. количество может быть REAL
                       for item_entry in valid_inventory_entries:
                             item_template_id_str = str(item_entry['item_id']) # Ensure template ID is string
                             quantity = item_entry.get('quantity', 1.0) # Get quantity, default to 1.0 (REAL)
                             if not isinstance(quantity, (int, float)):
                                 print(f"CharacterViewService: Warning: Invalid quantity type for item entry {item_entry} ({type(quantity)}). Defaulting to 1.0.")
                                 quantity = 1.0
                             # Получаем отображаемое имя из кэша названий
                             item_name = item_template_name_map.get(item_template_id_str, f"Неизвестный предмет ID:{item_template_id_str[:4]}...")
                             # Суммируем количество для одинаковых названий
                             item_counts[item_name] = item_counts.get(item_name, 0.0) + quantity # Use float default

                       # Формируем строки вывода
                       if item_counts:
                           # Сортируем по названию
                           sorted_items = sorted(item_counts.items())
                           # Форматируем количество (целое если без дроби, иначе с .2f)
                           item_list_lines = []
                           for name, count in sorted_items:
                               formatted_count = int(count) if count == int(count) else f"{count:.2f}" # Форматируем как целое или с .2f
                               item_list_lines.append(f"{name} x{formatted_count}")

                           # Ограничиваем вывод, если инвентарь очень большой
                           max_items_to_show = 10 # Настроить
                           inventory_text = "\n".join(item_list_lines[:max_items_to_show])
                           if len(item_list_lines) > max_items_to_show:
                                inventory_text += f"\n...и еще {len(item_list_lines) - max_items_to_show} позиций."
                       else:
                            inventory_text = "Инвентарь пуст." # Список пустой после обработки

                  else:
                       print(f"CharacterViewService: Warning: ItemManager or its required method 'get_item_template' not available for inventory processing for char {char_id} in guild {guild_id}.")
                       inventory_text = "Система предметов недоступна." # Или другой менеджер/метод отсутствует


              except Exception as e: # Ловим ошибки выше уровня итерации
                  print(f"CharacterViewService: Error processing inventory list for {char_id} in guild {guild_id}: {e}")
                  traceback.print_exc()
                  inventory_text = "Ошибка загрузки инвентаря."

         elif isinstance(inventory_data, list) and not inventory_data: # Если inventory_data пустой список
              inventory_text = "Инвентарь пуст."
         else: # Если inventory_data не список
              print(f"CharacterViewService: Warning: Inventory data is not a list ({type(inventory_data)}) for char {char_id}.")
              inventory_text = "Нет данных об инвентаре." # Более точное сообщение


         # Всегда возвращаем поле с данными инвентаря, даже если оно говорит "Инвентарь пуст" или "Ошибка",
         # чтобы у команды /status всегда было поле "Инвентарь".
         return {
             "name": "Инвентарь",
             "value": inventory_text,
             "inline": False # Обычно инвентарь не inline
         }


    # TODO: Добавьте другие методы для просмотра (например, описание локации, описание NPC)
    # Эти методы также должны принимать context: Dict[str, Any] и, возможно, **kwargs.

    # async def get_location_info_embed(self, location: Location, context: Dict[str, Any], **kwargs: Any) -> Optional[discord.Embed]: ...
    # async def get_npc_info_embed(self, npc: NPC, context: Dict[str, Any], **kwargs: Any) -> Optional[discord.Embed]: ...
    # async def get_party_info_embed(self, party: Party, context: Dict[str, Any], **kwargs: Any) -> Optional[discord.Embed]: ...


# --- Конец класса CharacterViewService ---

print("DEBUG: character_processors/character_view_service.py module loaded.")
