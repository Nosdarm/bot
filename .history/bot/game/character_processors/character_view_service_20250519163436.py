# bot/game/character_processors/character_view_service.py

from __future__ import annotations
import discord
import traceback
import json
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union # Добавлен Union

# Модели
# Импортируем модели, которые могут понадобиться для проверки isinstance или доступа к атрибутам в менеджерах
from bot.game.models.character import Character
# from bot.game.models.item import Item # Если get_item возвращает объект Item
# from bot.game.models.location import Location # Если get_location возвращает объект Location
# from bot.game.models.party import Party # Если get_party возвращает объект Party
# from bot.game.models.status import StatusEffectInstance # Если get_status_effect_instance возвращает объект StatusEffectInstance
# from bot.game.models.item import ItemTemplate # Если get_item_template возвращает объект ItemTemplate


if TYPE_CHECKING:
    # Импорты менеджеров, которые нужны CharacterViewService для получения данных
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.rules.rule_engine import RuleEngine


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
        print(f"CharacterViewService: Generating sheet embed for character {getattr(character, 'id', 'N/A')} ({getattr(character, 'name', 'N/A')}) in guild {context.get('guild_id')}...")

        if not isinstance(character, Character):
            print("CharacterViewService: Invalid character object provided.")
            return None

        try:
            embed = discord.Embed(
                title=f"Лист персонажа: {getattr(character, 'name', 'N/A')}", # Safely get name
                color=discord.Color.blue()
            )
            embed.description = f"ID: `{getattr(character, 'id', 'N/A')}`\nDiscord ID: `{getattr(character, 'discord_user_id', 'N/A')}`" # Add ID to description


            # --- Основные данные ---
            # Используйте getattr для безопасного получения атрибутов, если они могут отсутствовать
            embed.add_field(name="Уровень", value=str(getattr(character, 'level', 1)), inline=True) # Предполагаем атрибут level
            embed.add_field(name="Опыт", value=str(getattr(character, 'xp', 0)), inline=True) # Предполагаем атрибут xp
            embed.add_field(name="Здоровье", value=f"{getattr(character, 'health', 100.0)}/{getattr(character, 'max_health', 100.0)}", inline=True)

            # TODO: Добавить валюту, если есть (character.currency)
            # currency = getattr(character, 'currency', None)
            # if currency is not None:
            #      embed.add_field(name="Валюта", value=str(currency), inline=True)


            # --- Текущая локация и группа ---
            location_name = "Неизвестно"
            loc_id = getattr(character, 'location_id', None)
            # Используем LocationManager из контекста
            loc_manager = context.get('location_manager') # Type: Optional["LocationManager"]
            guild_id = context.get('guild_id') # Получаем guild_id из контекста

            if loc_id and loc_manager and hasattr(loc_manager, 'get_location'): # Предполагаем get_location(guild_id, location_id) -> Optional[Location]
                 try:
                      # Убедитесь в сигнатуре get_location
                      location = loc_manager.get_location(guild_id, loc_id) # Передаем guild_id
                      if location and hasattr(location, 'name'):
                           location_name = location.name
                      elif loc_id: # Если ID локации есть, но объект не найден или без имени
                           location_name = f"Локация ID: {loc_id[:4]}..." # Показываем хотя бы часть ID
                 except Exception as e:
                      print(f"CharacterViewService: Error getting location {loc_id} for char {getattr(character, 'id', 'N/A')} in guild {guild_id}: {e}")
                      traceback.print_exc()
                      location_name = f"Ошибка локации ({loc_id[:4]}...)"
            elif loc_id: # Если location_id есть, но менеджера нет или не нашел
                 location_name = f"Локация ID: {loc_id[:4]}..." # Показываем хотя бы часть ID

            embed.add_field(name="Локация", value=location_name, inline=False)

            # Party info
            party_text = "Не состоит в группе."
            party_id = getattr(character, 'party_id', None)
            # Используем PartyManager из контекста
            party_manager = context.get('party_manager') # Type: Optional["PartyManager"]

            if party_id and party_manager and hasattr(party_manager, 'get_party'): # Предполагаем get_party(guild_id, party_id) -> Optional[Party]
                 try:
                      # Убедитесь в сигнатуре get_party
                      party = party_manager.get_party(guild_id, party_id) # Передаем guild_id
                      if party and hasattr(party, 'name') and party.name:
                           party_text = f"Группа: {party.name}"
                      elif party_id: # Если ID группы есть, но объект не найден или без имени
                          party_text = f"Группа ID: {party_id[:4]}..."
                 except Exception as e:
                      print(f"CharacterViewService: Error getting party {party_id} for char {getattr(character, 'id', 'N/A')} in guild {guild_id}: {e}")
                      traceback.print_exc()
                      party_text = f"Ошибка группы ({party_id[:4]}...)"
            elif party_id: # Если party_id есть, но менеджера нет или не нашел
                 party_text = f"Группа ID: {party_id[:4]}..." # Показываем хотя бы часть ID

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
            # Используем StatusManager из контекста
            status_manager = context.get('status_manager') # Type: Optional["StatusManager"]

            if isinstance(status_effects_data, list) and status_effects_data and status_manager:
                 try:
                     status_names = []
                     # character.status_effects - это список Status ID'ов экземпляров (строк)
                     # StatusManager должен уметь получить информацию об экземпляре статуса по ID экземпляра
                     if hasattr(status_manager, 'get_status_effect_instance') and hasattr(status_manager, 'get_status_display_name'):
                          # Итерируем по копии, если список может меняться
                          for status_id_instance in list(status_effects_data):
                               try:
                                    # Получаем объект экземпляра статуса (get_status_effect_instance может быть async или sync, зависит от реализации StatusManager)
                                    # Если sync:
                                    status_instance = status_manager.get_status_effect_instance(status_id_instance) # Убедитесь в сигнатуре
                                    # Если async:
                                    # status_instance = await status_manager.get_status_effect_instance(status_id_instance) # Если метод асинхронный

                                    if status_instance:
                                        # Получаем отображаемое имя статуса (возможно, из шаблона, связанного с экземпляром)
                                        # get_status_display_name может быть async или sync, зависит от реализации StatusManager
                                        # Если sync:
                                        display_name = status_manager.get_status_display_name(status_instance=status_instance) # Убедитесь в сигнатуре
                                        # Если async:
                                        # display_name = await status_manager.get_status_display_name(status_instance=status_instance) # Если метод асинхронный

                                        status_names.append(display_name or f"ID:{status_id_instance[:4]}...") # Показываем ID если имя не получено
                                    else:
                                         status_names.append(f"ID:{status_id_instance[:4]}... (не найден)") # Если экземпляр статуса не найден

                               except Exception as e:
                                    print(f"CharacterViewService: Error processing status effect instance {status_id_instance} for char {getattr(character, 'id', 'N/A')} in guild {guild_id}: {e}")
                                    traceback.print_exc()
                                    status_names.append(f"ID:{status_id_instance[:4]}... (ошибка)")

                          if status_names:
                               status_effects_text = ", ".join(status_names)

                 except Exception as e: # Ловим ошибки выше уровня итерации
                     print(f"CharacterViewService: Error processing status effects list for {getattr(character, 'id', 'N/A')} in guild {guild_id}: {e}")
                     traceback.print_exc()
                     status_effects_text = "Ошибка загрузки эффектов."
            elif status_effects_data: # Если status_effects_data не пустой список, но менеджера нет или формат не тот
                 status_effects_text = "Есть эффекты (ошибка менеджера?)."
            else: # Если status_effects_data пустой список
                 status_effects_text = "Нет активных эффектов."


            embed.add_field(name="Состояния", value=status_effects_text, inline=False)


            # --- Инвентарь ---
            inventory_text = "Инвентарь пуст."
            inventory_data = getattr(character, 'inventory', []) # Safely get inventory
            # Используем ItemManager из контекста
            item_manager = context.get('item_manager') # Type: Optional["ItemManager"]

            # Предполагаем, что character.inventory - это List[Dict[str, Any]] с полями 'item_id' (template ID), 'quantity'
            # Или List[str] с ID экземпляров предметов?
            # В коде CharacterManager.add_item_to_inventory добавляется {'item_id': template_id, 'quantity': quantity}
            # Значит, character.inventory - это List[Dict[str, Any]]
            if isinstance(inventory_data, list) and inventory_data and item_manager:
                 try:
                     item_display_list: List[str] = []
                     # Нужна мапа {item_template_id: name} для отображения
                     item_template_name_map: Dict[str, str] = {} # Кэш названий шаблонов

                     if hasattr(item_manager, 'get_item_template'): # Предполагаем метод get_item_template(item_template_id) -> Optional[ItemTemplate]
                          # Собираем названия шаблонов
                          item_template_ids_to_fetch = {entry.get('item_id') for entry in inventory_data if isinstance(entry, dict) and 'item_id' in entry}
                          for template_id in item_template_ids_to_fetch:
                               if template_id is None: continue # Пропускаем невалидные ID
                               try:
                                    # get_item_template может быть async или sync
                                    # Если sync:
                                    item_template = item_manager.get_item_template(template_id) # Убедитесь в сигнатуре
                                    # Если async:
                                    # item_template = await item_manager.get_item_template(template_id) # Если метод асинхронный

                                    if item_template and hasattr(item_template, 'name'):
                                         item_template_name_map[template_id] = item_template.name
                                    else:
                                         item_template_name_map[template_id] = f"Шаблон ID:{template_id[:4]}..." # Заглушка названия шаблона

                               except Exception as e:
                                    print(f"CharacterViewService: Error getting item template {template_id} for char {getattr(character, 'id', 'N/A')} in guild {guild_id}: {e}")
                                    traceback.print_exc()
                                    item_template_name_map[template_id] = f"Шаблон ID:{template_id[:4]}... (ошибка)"


                          # Теперь формируем строки инвентаря, используя собранные названия
                          item_counts: Dict[str, int] = {} # {Название_предмета: количество}
                          for item_entry in inventory_data:
                               if isinstance(item_entry, dict) and 'item_id' in item_entry:
                                    item_template_id = item_entry['item_id']
                                    quantity = item_entry.get('quantity', 1)
                                    # Получаем отображаемое имя из кэша названий
                                    item_name = item_template_name_map.get(item_template_id, f"Неизвестный предмет ID:{item_template_id[:4]}...")
                                    # Суммируем количество для одинаковых названий
                                    item_counts[item_name] = item_counts.get(item_name, 0) + quantity

                          # Формируем строки вывода
                          if item_counts:
                              # Сортируем по названию
                              sorted_items = sorted(item_counts.items())
                              item_list_lines = [f"{name} x{count}" for name, count in sorted_items]

                              # Ограничиваем вывод, если инвентарь очень большой
                              max_items_to_show = 10 # Настроить
                              inventory_text = "\n".join(item_list_lines[:max_items_to_show])
                              if len(item_list_lines) > max_items_to_show:
                                   inventory_text += f"\n...и еще {len(item_list_lines) - max_items_to_show} позиций." # Количество позиций, а не уникальных названий
                          else:
                               inventory_text = "Инвентарь пуст." # Список пустой после обработки

                     else:
                          print(f"CharacterViewService: Warning: ItemManager or its required methods not available for inventory processing for char {getattr(character, 'id', 'N/A')} in guild {guild_id}.")
                          inventory_text = "Система предметов недоступна."

                 except Exception as e: # Ловим ошибки выше уровня итерации
                     print(f"CharacterViewService: Error processing inventory list for {getattr(character, 'id', 'N/A')} in guild {guild_id}: {e}")
                     traceback.print_exc()
                     inventory_text = "Ошибка загрузки инвентаря."
            elif inventory_data: # Если inventory_data не пустой список, но менеджера нет или формат не тот
                 # Это может случиться, если инвентарь содержит ID экземпляров, а не Dict[item_id, quantity]
                 # TODO: Обработать инвентарь как List[str] (список ID экземпляров)
                 print(f"CharacterViewService: Info: Inventory data for char {getattr(character, 'id', 'N/A')} in guild {guild_id} is not List[Dict], attempting to process as List[str] if ItemManager available.")
                 if item_manager and hasattr(item_manager, 'get_item'): # Предполагаем get_item(item_instance_id) -> Optional[Item]
                     try:
                         item_instance_ids = [str(item_id) for item_id in inventory_data if item_id is not None] # Ensure strings
                         item_names: List[str] = []
                         for instance_id in item_instance_ids:
                             try:
                                 # get_item может быть async или sync
                                 # item_instance = item_manager.get_item(instance_id) # Убедитесь в сигнатуре
                                 # if item_instance and hasattr(item_instance, 'name') and item_instance.name:
                                 #      item_names.append(item_instance.name)
                                 # elif item_instance and hasattr(item_instance, 'template_id'):
                                 #      # Получить название по шаблону
                                 #      template_id = item_instance.template_id
                                 #      template = item_manager.get_item_template(template_id) # Убедитесь в сигнатуре
                                 #      item_names.append(getattr(template, 'name', f"Item ID:{instance_id[:4]}..."))
                                 # else:
                                      item_names.append(f"Item ID:{instance_id[:4]}...") # Заглушка

                             except Exception as e:
                                print(f"CharacterViewService: Error getting item instance {instance_id} for char {getattr(character, 'id', 'N/A')} in guild {guild_id}: {e}")
                                traceback.print_exc()
                                item_names.append(f"Item ID:{instance_id[:4]}... (ошибка)")


                         if item_names:
                              # Суммируем одинаковые имена/заглушки
                              from collections import Counter
                              name_counts = Counter(item_names)
                              sorted_names = sorted(name_counts.items()) # Сортируем по названию
                              item_list_lines = [f"{name} x{count}" for name, count in sorted_names]
                              max_items_to_show = 10
                              inventory_text = "\n".join(item_list_lines[:max_items_to_show])
                              if len(item_list_lines) > max_items_to_show:
                                   inventory_text += f"\n...и еще {len(item_list_lines) - max_items_to_show} позиций."
                         else: inventory_text = "Инвентарь пуст (нет валидных ID экземпляров?)."

                     except Exception as e:
                         print(f"CharacterViewService: Error processing inventory as List[str] for char {getattr(character, 'id', 'N/A')} in guild {guild_id}: {e}")
                         traceback.print_exc()
                         inventory_text = "Ошибка загрузки инвентаря."
                 else: # ItemManager не доступен или нет нужных методов
                      print(f"CharacterViewService: Warning: ItemManager or its required methods not available for inventory processing (List[str] format) for char {getattr(character, 'id', 'N/A')} in guild {guild_id}.")
                      inventory_text = "Система предметов недоступна."

            else: # Если inventory_data пустой список
                 inventory_text = "Инвентарь пуст."


            embed.add_field(name="Инвентарь", value=inventory_text, inline=False)


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
                      action_text = f"Действие: {action_type.capitalize()} ({progress}/{total_duration} ед. времени)"
                 else:
                      action_text = f"Действие: {action_type.capitalize()}"
            elif action_queue_data: # Проверяем очередь, только если нет текущего действия
                 action_text = f"Очередь: {len(action_queue_data)} ожидающих действий."
            embed.add_field(name="Активность", value=action_text, inline=False)


            # Футер (можно добавить ID или другое)
            embed.set_footer(text=f"Персонаж ID: {getattr(character, 'id', 'N/A')}")


            return embed

        except Exception as e:
            # Логируем с контекстом гильдии и ID персонажа
            print(f"CharacterViewService: Critical error generating sheet embed for character {getattr(character, 'id', 'N/A')} in guild {context.get('guild_id')}: {e}")
            traceback.print_exc()
            return None # Возвращаем None при любой ошибке, CommandRouter обработает это


    # TODO: Добавьте другие методы для просмотра (например, инвентарь отдельно, описание локации, описание NPC)
    # Эти методы также должны принимать context: Dict[str, Any] и, возможно, **kwargs.

    # async def get_character_inventory_embed(self, character: Character, context: Dict[str, Any], **kwargs: Any) -> Optional[discord.Embed]:
    #      # ... логика для инвентаря, используя item_manager из context ...
    #      pass
