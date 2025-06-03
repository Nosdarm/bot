# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
# Import typing components
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Union

# --- Imports ---
# Pylance/Mypy needs direct import for Character to understand Character.from_dict
# Runtime also needs direct import for Character.from_dict
from bot.game.models.character import Character

# Import built-in types for isinstance checks
# Use lowercase 'dict', 'set', 'list' for isinstance
from builtins import dict, set, list, int


# --- Imports needed ONLY for Type Checking ---
# These modules are imported ONLY for static analysis (Pylance/Mypy).
# This breaks import cycles at runtime and helps Pylance correctly resolve types.
# Use string literals ("ClassName") for type hints in __init__ and methods
# for classes imported here.
if TYPE_CHECKING:
    # Add SqliteAdapter here
    from bot.database.sqlite_adapter import SqliteAdapter
    # Add other managers and RuleEngine
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.rules.rule_engine import RuleEngine
    # Add Discord types if used in type hints (e.g., in context dicts)
    # from discord import Guild # Example if guild object is passed in context
    # from discord import Client # If client is passed in context

    # !!! Add Character here too, despite direct import above !!!
    # This is necessary for Pylance to resolve string literals in annotations (e.g., Dict[str, "Character"]).
    from bot.game.models.character import Character


# --- Imports needed at Runtime ---
# For CharacterManager, you usually need direct import of the Character model and utilities.


print("DEBUG: character_manager.py module loaded.")


class CharacterManager:
    """
    Менеджер для управления персонажами игроков.
    Отвечает за создание, получение, обновление персонажей, их персистентность
    и хранение их основного состояния и кешей.
    Работает на основе guild_id для многогильдийной поддержки.
    """
    # Добавляем required_args для совместимости с PersistenceManager
    # Эти поля используются PersistenceManager для определения, какие аргументы передать в load/save/rebuild.
    required_args_for_load = ["guild_id"] # load_state фильтрует по guild_id
    required_args_for_save = ["guild_id"] # save_state фильтрует по guild_id
    required_args_for_rebuild = ["guild_id"] # rebuild_runtime_caches фильтрует по guild_id

    # --- Class-Level Attribute Annotations ---
    # Объявляем типы инстанс-атрибутов здесь. Это стандартный способ для Pylance/Mypy.
    # ИСПРАВЛЕНИЕ: Кеши должны быть per-guild
    # Кеш всех загруженных объектов персонажей {guild_id: {char_id: Character_object}}
    _characters: Dict[str, Dict[str, "Character"]]
    # Мапа Discord User ID на ID персонажа (UUID) per-guild: {guild_id: {discord_id: char_id}}
    _discord_to_char_map: Dict[str, Dict[int, str]]
    # Set ID сущностей (Character/NPC) с активным действием per-guild: {guild_id: set(entity_ids)}
    # Decided to make this per-guild for consistency, although entity_ids themselves are global UUIDs.
    _entities_with_active_action: Dict[str, Set[str]]
    # ID персонажей, которые были изменены в runtime и требуют сохранения в DB per-guild: {guild_id: set(char_ids)}
    _dirty_characters: Dict[str, Set[str]]
    # ID персонажей, которые были удалены в runtime и требуют удаления из DB per-guild: {guild_id: set(char_ids)}
    _deleted_characters_ids: Dict[str, Set[str]]


    def __init__(
        self,
        # Используем строковые литералы для всех опциональных менеджеров/адаптеров,
        # особенно если они импортируются условно или только в TYPE_CHECKING
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
    ):
        print("Initializing CharacterManager...")
        self._db_adapter = db_adapter
        self._settings = settings
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager

        # Internal caches
        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые outer словари
        self._characters = {} # {guild_id: {char_id: Character_object}}
        self._discord_to_char_map = {} # {guild_id: {discord_id: char_id}}
        self._entities_with_active_action = {} # {guild_id: set(entity_ids)}
        self._dirty_characters = {} # {guild_id: set(char_ids)}
        self._deleted_characters_ids = {} # {guild_id: set(char_ids)}

        print("CharacterManager initialized.")

    # --- Методы получения персонажей ---
    # ИСПРАВЛЕНИЕ: Все геттеры должны принимать guild_id
    # Используем строковый литерал в аннотации возвращаемого типа
    def get_character(self, guild_id: str, character_id: str) -> Optional["Character"]:
        """Получить персонажа по его внутреннему ID (UUID) для определенной гильдии."""
        # ИСПРАВЛЕНИЕ: Получаем из per-guild кеша
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars:
             return guild_chars.get(character_id)
        return None # Гильдия или персонаж не найдены


    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Принимаем guild_id
    def get_character_by_discord_id(self, guild_id: str, discord_user_id: int) -> Optional["Character"]:
        """Получить персонажа по Discord User ID для определенной гильдии."""
        # ИСПРАВЛЕНИЕ: Используем per-guild мапу
        guild_discord_map = self._discord_to_char_map.get(str(guild_id))
        if guild_discord_map:
             char_id = guild_discord_map.get(discord_user_id)
             # Возвращаем персонажа из основного кеша для этой гильдии
             if char_id:
                 return self.get_character(guild_id, char_id) # Используем get_character с guild_id

        return None # Гильдия, мапа, или персонаж не найдены


    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Принимаем guild_id
    def get_character_by_name(self, guild_id: str, name: str) -> Optional["Character"]:
         """Получить персонажа по имени для определенной гильдии (может быть медленно)."""
         # ИСПРАВЛЕНИЕ: Итерируем только по персонажам этой гильдии
         guild_chars = self._characters.get(str(guild_id))
         if guild_chars:
              for char in guild_chars.values():
                  if isinstance(char, Character) and char.name == name:
                      return char
         return None

    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Принимаем guild_id
    def get_all_characters(self, guild_id: str) -> List["Character"]:
        """Получить список всех загруженных персонажей для определенной гильдии (из кеша)."""
        # ИСПРАВЛЕНИЕ: Получаем из per-guild кеша
        guild_chars = self._characters.get(str(guild_id))
        if guild_chars:
             return list(guild_chars.values())
        return [] # Возвращаем пустой список, если для гильдии нет персонажей

    # Метод уже принимает guild_id
    def get_characters_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List["Character"]:
        """Получить список персонажей, находящихся в указанной локации (инстансе) для данной гильдии."""
        # ИСПРАВЛЕНИЕ: Фильтруем только по персонажам этой гильдии
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        characters_in_location = []
        # Получаем всех персонажей для этой гильдии, затем фильтруем по локации
        guild_chars = self._characters.get(guild_id_str)
        if guild_chars:
             for char in guild_chars.values():
                 if isinstance(char, Character) and hasattr(char, 'location_id') and str(getattr(char, 'location_id', None)) == location_id_str:
                      characters_in_location.append(char)

        # print(f"CharacterManager: Found {len(characters_in_location)} characters in location {location_id_str} for guild {guild_id_str}.") # Debug
        return characters_in_location


    # ИСПРАВЛЕНИЕ: Метод должен принимать guild_id
    def get_entities_with_active_action(self, guild_id: str) -> Set[str]:
        """Получить ID сущностей (включая персонажей) с активным действием для определенной гильдии."""
        # ИСПРАВЛЕНИЕ: Получаем из per-guild Set
        return self._entities_with_active_action.get(str(guild_id), set()).copy() # Возвращаем копию для безопасности


    # ИСПРАВЛЕНИЕ: Метод должен принимать guild_id
    def is_busy(self, guild_id: str, character_id: str) -> bool:
        """Проверяет, занят ли персонаж (выполняет действие или состоит в занятой группе)."""
        # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
        char = self.get_character(guild_id, character_id)
        if not char:
            return False
        # Проверка на текущее действие персонажа (эти атрибуты на самом объекте Character, не в менеджере)
        if getattr(char, 'current_action', None) is not None or getattr(char, 'action_queue', []):
            return True
        # Проверка, занята ли его группа (используем инжектированный party_manager, если он есть)
        if getattr(char, 'party_id', None) is not None and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
            # ИСПРАВЛЕНИЕ: Передаем guild_id в PartyManager.is_party_busy
            # Предполагаем, что PartyManager.is_party_busy ожидает guild_id и party_id
            # PartyManager.is_party_busy(guild_id: str, party_id: str) -> bool
            party_id = getattr(char, 'party_id', None)
            if party_id:
                # PartyManager может быть async, поэтому вызов PartyManager.is_party_busy должен быть awaitable?
                # Если is_party_busy синхронный, то все ОК. Если async, этот метод is_busy должен стать async.
                # Большинство проверок занятости - синхронные. Предположим, PartyManager.is_party_busy синхронный.
                return self._party_manager.is_party_busy(str(guild_id), party_id) # Убеждаемся, что guild_id строка
        # Если party_manager нет или нет метода, считаем, что группа не может быть занята через него
        return False


    # --- Методы создания ---

    async def create_character(
        self,
        discord_id: int, # Discord User ID (int)
        name: str, # Имя персонажа (string)
        guild_id: str, # Обязательный аргумент guild_id
        # Опциональная начальная локация (ID инстанса локации)
        initial_location_id: Optional[str] = None,
        # Добавляем **kwargs для контекста, хотя guild_id теперь обязателен
        **kwargs: Any
    ) -> Optional["Character"]: # Возвращаем Optional["Character"], т.к. создание может не удасться
        """
        Создает нового персонажа в базе данных, кеширует его и возвращает объект Character.
        Принимает discord_id, name, guild_id.
        """
        if self._db_adapter is None:
            print(f"CharacterManager: Error: DB adapter missing for guild {guild_id}.")
            # В многогильдийном режиме, возможно, нужно рейзить ошибку, т.к. без DB данные не будут персистировать
            raise ConnectionError("Database adapter is not initialized in CharacterManager.")

        guild_id_str = str(guild_id) # Убедимся, что guild_id строка

        # Проверка на существование персонажа для этого discord_id В ПРЕДЕЛАХ ГИЛЬДИИ
        # ИСПРАВЛЕНИЕ: Используем get_character_by_discord_id с guild_id
        existing_char = self.get_character_by_discord_id(guild_id_str, discord_id)
        if existing_char:
             print(f"CharacterManager: Character already exists for discord ID {discord_id} in guild {guild_id_str} (ID: {existing_char.id}). Creation failed.")
             # В зависимости от логики, можно вернуть None или рейзить ValueЕrror
             # raise ValueError(f"User already has a character (ID: {existing_char.id}) in this guild.")
             return None


        # Проверка на уникальность имени персонажа В ПРЕДЕЛАХ ГИЛЬДИИ
        # ИСПРАВЛЕНИЕ: Используем get_character_by_name с guild_id
        existing_char_by_name = self.get_character_by_name(guild_id_str, name)
        if existing_char_by_name:
             print(f"CharacterManager: Character with name '{name}' already exists in guild {guild_id_str} (ID: {existing_char_by_name.id}). Creation failed.")
             # В зависимости от логики, можно вернуть None или рейзить ValueЕrror
             # raise ValueError(f"Character name '{name}' is already taken in this guild.")
             return None


        # Генерируем уникальный ID (UUID)
        new_id = str(uuid.uuid4())

        # Определяем начальную локацию (используем инжектированный location_manager, если он есть)
        resolved_initial_location_id = initial_location_id
        # Убедимся, что self._location_manager доступен
        if resolved_initial_location_id is None and self._location_manager and hasattr(self._location_manager, 'get_default_location_id'):
             try:
                 # LocationManager.get_default_location_id(guild_id: str) -> Optional[str]
                 resolved_initial_location_id = self._location_manager.get_default_location_id(guild_id=guild_id_str) # Передаем guild_id_str
                 if resolved_initial_location_id:
                      print(f"CharacterManager: Using default location ID: {resolved_initial_location_id} for guild {guild_id_str}")
             except Exception as e:
                 print(f"CharacterManager: Warning: Could not get default location ID for guild {guild_id_str}: {e}")
                 import traceback
                 print(traceback.format_exc())


        # Определяем начальные статы (можно использовать RuleEngine, если он передан)
        stats = {'strength': 10, 'dexterity': 10, 'intelligence': 10} # Default stats
        if self._rule_engine and hasattr(self._rule_engine, 'generate_initial_character_stats'):
            try:
                # RuleEngine.generate_initial_character_stats не ожидает аргументов, согласно его коду.
                # Если ему нужен guild_id или другие параметры для генерации статов (например, на основе расы гильдии),
                # нужно изменить сигнатуру generate_initial_character_stats в RuleEngine и передать kwargs сюда.
                generated_stats = self._rule_engine.generate_initial_character_stats() # Предполагаем синхронный вызов
                if isinstance(generated_stats, dict):
                     stats = generated_stats
            except Exception:
                print("CharacterManager: Error generating initial character stats:")
                traceback.print_exc()


        # Подготавливаем данные для вставки в DB и создания модели
        data: Dict[str, Any] = {
            'id': new_id, # UUID как TEXT
            'discord_user_id': discord_id, # Значение из параметра discord_id
            'name': name,
            'guild_id': guild_id_str, # <-- Добавляем guild_id_str
            'location_id': resolved_initial_location_id, # Может быть None
            'stats': stats, # dict
            'inventory': [], # list
            'current_action': None, # null
            'action_queue': [], # list
            'party_id': None, # null
            'state_variables': {}, # dict
            'health': 100.0,
            'max_health': 100.0,
            'is_alive': True, # bool (сохраняется как integer 0 or 1)
            'status_effects': [], # list
            # ... другие поля из модели Character ...
        }


        # Преобразуем в JSON для сохранения в DB
        sql = """
        INSERT INTO characters (
            id, discord_user_id, name, guild_id, location_id, stats, inventory,
            current_action, action_queue, party_id, state_variables,
            health, max_health, is_alive, status_effects
            -- , ... другие колонки ...
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # Убедитесь, что порядок параметров соответствует колонкам в SQL
        db_params = (
            data['id'],
            data['discord_user_id'],
            data['name'],
            data['guild_id'], # <-- Параметр guild_id_str
            data['location_id'],
            json.dumps(data['stats']),
            json.dumps(data['inventory']),
            json.dumps(data['current_action']) if data['current_action'] is not None else None,
            json.dumps(data['action_queue']),
            data['party_id'],
            json.dumps(data['state_variables']),
            data['health'],
            data['max_health'],
            int(data['is_alive']), # boolean как integer (0 or 1)
            json.dumps(data['status_effects']),
            # ... другие параметры ...
        )

        if self._db_adapter is None:
             print(f"CharacterManager: Error creating character: DB adapter is None for guild {guild_id_str}.")
             raise ConnectionError("Database adapter is not initialized in CharacterManager.")

        try:
            # Выполняем INSERT. Используем execute для вставки с заданным ID (UUID).
            await self._db_adapter.execute(sql, db_params)
            print(f"CharacterManager: Character '{name}' with ID {new_id} inserted into DB for guild {guild_id_str}.")


            # Создаем объект модели Character из данных (данные уже в формате Python объектов)
            char = Character.from_dict(data)


            # ИСПРАВЛЕНИЕ: Добавляем персонажа в per-guild кеши
            self._characters.setdefault(guild_id_str, {})[char.id] = char
            if char.discord_user_id is not None:
                 # Убеждаемся, что discord_user_id является хэшируемым типом (int)
                 self._discord_to_char_map.setdefault(guild_id_str, {})[char.discord_user_id] = char.id # Мапа discord_id -> char_id (per-guild)


            # ИСПРАВЛЕНИЕ: Отмечаем как грязный для этой гильдии
            self.mark_character_dirty(guild_id_str, char.id)


            print(f"CharacterManager: Character '{name}' (ID: {char.id}, Guild: {char.guild_id}) created and cached for guild {guild_id_str}.")
            return char

        except Exception as e:
            print(f"CharacterManager: Error creating character '{name}' for discord ID {discord_id} in guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Перебрасываем исключение, чтобы GameManager/CommandRouter мог его поймать
            raise


    # --- Методы сохранения/загрузки (для PersistenceManager) ---
    # required_args определены в начале класса и указывают, что методы load/save/rebuild ожидают guild_id

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет все измененные или удаленные персонажи для определенного guild_id."""
        if self._db_adapter is None:
            print(f"CharacterManager: Warning: Cannot save characters for guild {guild_id}, DB adapter missing.")
            return
        guild_id_str = str(guild_id)

        # ИСПРАВЛЕНИЕ: Получаем dirty/deleted ID ИЗ per-guild кешей
        dirty_char_ids_for_guild_set = self._dirty_characters.get(guild_id_str, set()).copy() # Рабочая копия Set
        deleted_char_ids_for_guild_set = self._deleted_characters_ids.get(guild_id_str, set()).copy() # Рабочая копия Set

        if not dirty_char_ids_for_guild_set and not deleted_char_ids_for_guild_set:
            # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, очищаем per-guild dirty/deleted сеты
            self._dirty_characters.pop(guild_id_str, None)
            self._deleted_characters_ids.pop(guild_id_str, None)
            # print(f"CharacterManager: No dirty or deleted characters to save for guild {guild_id_str}.") # Debug
            return

        print(f"CharacterManager: Saving {len(dirty_char_ids_for_guild_set)} dirty, {len(deleted_char_ids_for_guild_set)} deleted characters for guild {guild_id_str}...")

        # Удалить помеченные для удаления персонажи для этого guild_id
        if deleted_char_ids_for_guild_set:
            ids_to_delete = list(deleted_char_ids_for_guild_set)
            placeholders = ','.join(['?'] * len(ids_to_delete))
            # Убеждаемся, что удаляем ТОЛЬКО для данного guild_id и по ID из списка
            delete_sql = f"DELETE FROM characters WHERE guild_id = ? AND id IN ({placeholders})"
            try:
                await self._db_adapter.execute(delete_sql, (guild_id_str, *tuple(ids_to_delete)))
                print(f"CharacterManager: Deleted {len(ids_to_delete)} characters from DB for guild {guild_id_str}.")
                # ИСПРАВЛЕНИЕ: Очищаем deleted set для этой гильдии после успешного удаления
                self._deleted_characters_ids.pop(guild_id_str, None)
            except Exception as e:
                print(f"CharacterManager: Error deleting characters for guild {guild_id_str}: {e}")
                import traceback
                print(traceback.format_exc())
                # Не очищаем _deleted_characters_ids[guild_id_str], чтобы попробовать удалить снова при следующей сохранке


        # Обновить или вставить измененные персонажи для этого guild_id
        # ИСПРАВЛЕНИЕ: Фильтруем dirty_instances на те, что все еще существуют в per-guild кеше
        guild_chars_cache = self._characters.get(guild_id_str, {})
        characters_to_save = [guild_chars_cache[cid] for cid in list(dirty_char_ids_for_guild_set) if cid in guild_chars_cache]
        if characters_to_save:
             print(f"CharacterManager: Upserting {len(characters_to_save)} characters for guild {guild_id_str}...")
             # INSERT OR REPLACE SQL для обновления существующих или вставки новых
             upsert_sql = '''
             INSERT OR REPLACE INTO characters
             (id, discord_user_id, name, guild_id, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             '''
             data_to_upsert = []
             upserted_char_ids: Set[str] = set() # Track IDs that were successfully prepared for upsert

             for char in characters_to_save:
                 try:
                     # Убеждаемся, что у объекта Character есть все нужные атрибуты
                     char_id = getattr(char, 'id', None)
                     discord_user_id = getattr(char, 'discord_user_id', None)
                     char_name = getattr(char, 'name', None)
                     char_guild_id = getattr(char, 'guild_id', None)

                     # Дополнительная проверка на критически важные атрибуты и совпадение guild_id
                     if char_id is None or discord_user_id is None or char_name is None or char_guild_id is None or str(char_guild_id) != guild_id_str:
                         print(f"CharacterManager: Warning: Skipping upsert for character with missing mandatory attributes or mismatched guild ({getattr(char, 'id', 'N/A')}, guild {getattr(char, 'guild_id', 'N/A')}). Expected guild {guild_id_str}.")
                         continue # Пропускаем этого персонажа

                     location_id = getattr(char, 'location_id', None)
                     stats = getattr(char, 'stats', {})
                     inventory = getattr(char, 'inventory', [])
                     current_action = getattr(char, 'current_action', None)
                     action_queue = getattr(char, 'action_queue', [])
                     party_id = getattr(char, 'party_id', None)
                     state_variables = getattr(char, 'state_variables', {})
                     health = getattr(char, 'health', 100.0)
                     max_health = getattr(char, 'max_health', 100.0)
                     is_alive = getattr(char, 'is_alive', True)
                     status_effects = getattr(char, 'status_effects', [])

                     # Ensure required fields for DB exist and have correct types before dumping
                     if not isinstance(inventory, list):
                         print(f"CharacterManager: Warning: Char {char_id} inventory is not list. Saving as empty list.")
                         inventory = []
                     if not isinstance(action_queue, list):
                         print(f"CharacterManager: Warning: Char {char_id} action_queue is not list. Saving as empty list.")
                         action_queue = []
                     if not isinstance(stats, dict):
                          print(f"CharacterManager: Warning: Char {char_id} stats is not dict. Saving as empty dict.")
                          stats = {}
                     if not isinstance(state_variables, dict):
                          print(f"CharacterManager: Warning: Char {char_id} state_variables is not dict. Saving as empty dict.")
                          state_variables = {}
                     if not isinstance(status_effects, list):
                         print(f"CharacterManager: Warning: Char {char_id} status_effects is not list. Saving as empty list.")
                         status_effects = []


                     stats_json = json.dumps(stats)
                     inv_json = json.dumps(inventory)
                     curr_json = json.dumps(current_action) if current_action is not None else None
                     queue_json = json.dumps(action_queue)
                     state_json = json.dumps(state_variables)
                     status_json = json.dumps(status_effects)


                     data_to_upsert.append((
                         char_id,
                         discord_user_id,
                         char_name,
                         guild_id_str, # Убедимся, что guild_id строка для DB
                         location_id, # Может быть None
                         stats_json,
                         inv_json,
                         curr_json,
                         queue_json,
                         party_id, # Может быть None
                         state_json,
                         health,
                         max_health,
                         int(is_alive), # boolean как integer
                         status_json,
                     ))
                     upserted_char_ids.add(char_id) # Track IDs that were prepared for upsert

                 except Exception as e:
                     print(f"CharacterManager: Error preparing data for character {getattr(char, 'id', 'N/A')} ({getattr(char, 'name', 'N/A')}, guild {getattr(char, 'guild_id', 'N/A')}) for upsert: {e}")
                     import traceback
                     print(traceback.format_exc())
                     # Этот персонаж не будет сохранен в этой итерации - он останется в _dirty_characters
                     # чтобы попробовать сохранить его снова

             if data_to_upsert:
                 try:
                     if self._db_adapter is None:
                          print(f"CharacterManager: Warning: DB adapter is None during upsert batch for guild {guild_id_str}.")
                     else:
                          await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                          print(f"CharacterManager: Successfully upserted {len(data_to_upsert)} characters for guild {guild_id_str}.")
                          # ИСПРАВЛЕНИЕ: Очищаем dirty set для этой гильдии только для успешно сохраненных ID
                          if guild_id_str in self._dirty_characters:
                                self._dirty_characters[guild_id_str].difference_update(upserted_char_ids)
                                # Если после очистки set пуст, удаляем ключ гильдии
                                if not self._dirty_characters[guild_id_str]:
                                     del self._dirty_characters[guild_id_str]
                 except Exception as e:
                     print(f"CharacterManager: Error during batch upsert for guild {guild_id_str}: {e}")
                     import traceback
                     print(traceback.format_exc())
                     # Не очищаем _dirty_characters, чтобы попробовать сохранить снова

        print(f"CharacterManager: Save state complete for guild {guild_id_str}.")


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает все персонажи для определенного guild_id из базы данных в кеш."""
        if self._db_adapter is None:
            print(f"CharacterManager: Warning: Cannot load characters for guild {guild_id}, DB adapter missing.")
            # TODO: В режиме без DB, нужно загрузить Placeholder персонажи
            return

        guild_id_str = str(guild_id)
        print(f"CharacterManager: Loading characters for guild {guild_id_str} from DB...")

        # ИСПРАВЛЕНИЕ: Очистите кеши ТОЛЬКО для этой гильдии перед загрузкой
        self._characters.pop(guild_id_str, None)
        self._characters[guild_id_str] = {} # Создаем пустой кеш для этой гильдии

        self._discord_to_char_map.pop(guild_id_str, None)
        self._discord_to_char_map[guild_id_str] = {} # Создаем пустой кеш для этой гильдии

        self._entities_with_active_action.pop(guild_id_str, None)
        self._entities_with_active_action[guild_id_str] = set() # Создаем пустой кеш для этой гильгии

        # При загрузке, считаем, что все в DB "чистое", поэтому очищаем dirty/deleted для этой гильдии
        self._dirty_characters.pop(guild_id_str, None)
        self._deleted_characters_ids.pop(guild_id_str, None)

        rows = [] # Инициализируем список для строк
        try:
            # ВЫПОЛНЯЕМ fetchall С ФИЛЬТРОМ по guild_id
            sql = '''
            SELECT id, discord_user_id, name, guild_id, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects
            FROM characters WHERE guild_id = ?
            '''
            rows = await self._db_adapter.fetchall(sql, (guild_id_str,))
            print(f"CharacterManager: Found {len(rows)} characters in DB for guild {guild_id_str}.")

        except Exception as e:
            # Если произошла ошибка при самом выполнении запроса fetchall
            print(f"CharacterManager: ❌ CRITICAL ERROR executing DB fetchall for characters for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # В этом случае rows будет пустым списком, и мы просто выйдем из метода после обработки ошибки.
            # Очистка кешей для этой гильдии уже была сделана выше.
            # Возможно, нужно перебрасывать исключение, чтобы GameManager знал, что загрузка не удалась?
            raise # Пробрасываем критическую ошибку

        # Теперь обрабатываем каждую строку ВНУТРИ ЦИКЛА
        loaded_count = 0
        # Get the cache dicts for this specific guild
        guild_chars_cache = self._characters[guild_id_str]
        guild_discord_map_cache = self._discord_to_char_map[guild_id_str]
        guild_active_action_cache = self._entities_with_active_action[guild_id_str]


        for row in rows:
            # Убеждаемся, что row - это dict-подобный объект
            data = dict(row)
            try:
                # Проверяем наличие обязательных полей
                char_id_raw = data.get('id')
                discord_user_id_raw = data.get('discord_user_id')
                guild_id_raw = data.get('guild_id')

                if char_id_raw is None or discord_user_id_raw is None or guild_id_raw is None:
                    print(f"CharacterManager: Warning: Skipping row with missing mandatory fields (ID, Discord ID, Guild ID) for guild {guild_id_str}. Row data: {data}. ")
                    continue # Пропускаем строку без обязательных полей

                # Проверяем и преобразуем ID в строку
                char_id = str(char_id_raw)
                loaded_guild_id = str(guild_id_raw)

                # Проверяем, что guild_id в данных соответствует тому, который мы загружали
                if loaded_guild_id != guild_id_str:
                     print(f"CharacterManager: Warning: Mismatch guild_id for character {char_id}: Expected {guild_id_str}, got {loaded_guild_id}. Skipping.")
                     continue # Пропускаем строку, если guild_id не совпадает

                # Проверяем и преобразуем discord_user_id в int
                discord_user_id_int = None
                if discord_user_id_raw is not None:
                     try:
                         discord_user_id_int = int(discord_user_id_raw)
                     except (ValueError, TypeError):
                          print(f"CharacterManager: Warning: Invalid discord_user_id format for character {char_id} in guild {guild_id_str}: {discord_user_id_raw}. Skipping mapping.")


                # Преобразуем JSON строки и Integer (для is_alive) обратно в Python объекты
                # Handle potential errors during JSON parsing gracefully
                data['stats'] = json.loads(data.get('stats') or '{}') if isinstance(data.get('stats'), (str, bytes)) else {}
                data['inventory'] = json.loads(data.get('inventory') or '[]') if isinstance(data.get('inventory'), (str, bytes)) else []
                current_action_data = data.get('current_action')
                data['current_action'] = json.loads(current_action_data) if isinstance(current_action_data, (str, bytes)) else None
                data['action_queue'] = json.loads(data.get('action_queue') or '[]') if isinstance(data.get('action_queue'), (str, bytes)) else []
                data['state_variables'] = json.loads(data.get('state_variables') or '{}') if isinstance(data.get('state_variables'), (str, bytes)) else {}
                data['status_effects'] = json.loads(data.get('status_effects') or '[]') if isinstance(data.get('status_effects'), (str, bytes)) else []

                # Convert is_alive from DB integer (0 or 1) to boolean
                is_alive_db = data.get('is_alive')
                data['is_alive'] = bool(is_alive_db) if is_alive_db is not None else True # Default to True if is_alive is None/missing

                # Ensure health/max_health are numbers, default if missing or wrong type
                data['health'] = float(data.get('health', 100.0)) if isinstance(data.get('health'), (int, float)) else 100.0
                data['max_health'] = float(data.get('max_health', 100.0)) if isinstance(data.get('max_health'), (int, float)) else 100.0


                # Update data dict with validated/converted values
                data['id'] = char_id
                data['discord_user_id'] = discord_user_id_int
                data['guild_id'] = loaded_guild_id # Use the string version loaded from DB
                # Ensure list fields are actually lists
                if not isinstance(data['inventory'], list): data['inventory'] = []
                if not isinstance(data['action_queue'], list): data['action_queue'] = []
                if not isinstance(data['status_effects'], list): data['status_effects'] = []
                # Ensure dict fields are actually dicts
                if not isinstance(data['stats'], dict): data['stats'] = {}
                if not isinstance(data['state_variables'], dict): data['state_variables'] = {}

                # Create object ID (Party ID, Location ID) are strings or None
                data['location_id'] = str(data['location_id']) if data.get('location_id') is not None else None
                data['party_id'] = str(data['party_id']) if data.get('party_id') is not None else None


                # Create object model
                char = Character.from_dict(data) # Ln 461 (approx, numbers may shift)

                # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш по ID
                guild_chars_cache[char.id] = char

                # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш по Discord ID, только если discord_user_id валидный int и он не None
                if discord_user_id_int is not None:
                     guild_discord_map_cache[discord_user_id_int] = char.id

                # ИСПРАВЛЕНИЕ: Если у персонажа есть активное действие или очередь, помечаем его как занятого ДЛЯ ЭТОЙ ГИЛЬДИИ
                if getattr(char, 'current_action', None) is not None or getattr(char, 'action_queue', []):
                    guild_active_action_cache.add(char.id)

                loaded_count += 1 # Увеличиваем счетчик успешно загруженных

            except Exception as e:
                # Общая ошибка при обработке ОДНОЙ строки
                print(f"CharacterManager: Error processing character row for guild {guild_id_str} (ID: {data.get('id', 'N/A')}): {e}.")
                import traceback
                print(traceback.format_exc())
                # Continue loop for other rows

        print(f"CharacterManager: Successfully loaded {loaded_count} characters into cache for guild {guild_id_str}.")
        if loaded_count < len(rows):
             print(f"CharacterManager: Note: Failed to load {len(rows) - loaded_count} characters for guild {guild_id_str} due to errors.")

    # Метод rebuild_runtime_caches принимает guild_id
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"CharacterManager: Rebuilding runtime caches for guild {guild_id_str}. (Specific cache logic needed)")

        # Получаем все загруженные персонажи для этой гильдии
        characters_for_guild = list(self._characters.get(guild_id_str, {}).values())

        # ИСПРАВЛЕНИЕ: Пример: Если нужно перестроить кеш занятости, который зависит от PartyManager
        # Этот кеш _entities_with_active_action уже наполняется в load_state, но если он зависел от других менеджеров,
        # логика была бы здесь.
        # guild_active_action_cache = self._entities_with_active_action.setdefault(guild_id_str, set())
        # guild_active_action_cache.clear() # Clear previous state for this guild
        # for char in characters_for_guild:
        #     # Logic to determine if character is busy based on *other* managers' state for this guild
        #     # Example: If character is in a combat according to CombatManager
        #     combat_mgr = kwargs.get('combat_manager') # Type: Optional["CombatManager"]
        #     if combat_mgr and hasattr(combat_mgr, 'is_participating_in_combat') and await combat_mgr.is_participating_in_combat(char.id, "Character", guild_id=guild_id_str):
        #          guild_active_action_cache.add(char.id)
        #     # Other checks...


        # ИСПРАВЛЕНИЕ: Пример: Если PartyManager нуждается в списке персонажей для перестройки кеша партий
        # PartyManager.rebuild_runtime_caches вызывается после всех менеджеров для гильдии.
        # PartyManager получит CharacterManager и запросит у него персонажей для этой гильдии.
        # party_mgr = kwargs.get('party_manager') # Type: Optional["PartyManager"]
        # if party_mgr and hasattr(party_mgr, 'rebuild_cache_from_characters'):
        #      await party_mgr.rebuild_cache_from_characters(characters_for_guild, guild_id=guild_id_str, **kwargs) # Pass needed info

        print(f"CharacterManager: Rebuild runtime caches complete for guild {guild_id_str}.")


    # ИСПРАВЛЕНИЕ: mark_character_dirty должен принимать guild_id
    def mark_character_dirty(self, guild_id: str, character_id: str) -> None:
         """Помечает персонажа как измененного для последующего сохранения для определенной гильдии."""
         guild_id_str = str(guild_id)
         # Добавляем проверку, что ID существует в per-guild кеше
         if guild_id_str in self._characters and character_id in self._characters[guild_id_str]:
              self._dirty_characters.setdefault(guild_id_str, set()).add(character_id)
         # else:
             # print(f"CharacterManager: Warning: Attempted to mark non-existent character {character_id} in guild {guild_id_str} as dirty.") # Too noisy?


    # ИСПРАВЛЕНИЕ: mark_character_deleted должен принимать guild_id
    def mark_character_deleted(self, guild_id: str, character_id: str) -> None:
        """Помечает персонажа как удаленного для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Проверяем, существует ли персонаж в per-guild кеше, прежде чем удалять
        guild_chars_cache = self._characters.get(guild_id_str)
        if guild_chars_cache and character_id in guild_chars_cache:
             char = guild_chars_cache[character_id]
             # Удаляем из per-guild кеша активных персонажей
             del guild_chars_cache[character_id]
             print(f"CharacterManager: Removed character {character_id} from cache for guild {guild_id_str}.")

             # Удаляем из per-guild мапы discord_id -> char_id
             guild_discord_map_cache = self._discord_to_char_map.get(guild_id_str)
             if guild_discord_map_cache:
                 discord_id_to_remove = getattr(char, 'discord_user_id', None)
                 if discord_id_to_remove is not None and discord_id_to_remove in guild_discord_map_cache and guild_discord_map_cache.get(discord_id_to_remove) == character_id:
                     del guild_discord_map_cache[discord_id_to_remove]
                     print(f"CharacterManager: Removed discord mapping for {discord_id_to_remove} in guild {guild_id_str}.")

             # Удаляем из per-guild списка занятых
             guild_active_action_cache = self._entities_with_active_action.get(guild_id_str)
             if guild_active_action_cache:
                  guild_active_action_cache.discard(character_id)


             # Удаляем из per-guild dirty set (если был там)
             guild_dirty_set = self._dirty_characters.get(guild_id_str)
             if guild_dirty_set:
                  guild_dirty_set.discard(character_id)


             # Помечаем для удаления из DB (per-guild)
             self._deleted_characters_ids.setdefault(guild_id_str, set()).add(character_id)
             print(f"CharacterManager: Character {character_id} marked for deletion for guild {guild_id_str}.")

        # Handle case where character was already deleted but mark_deleted is called again
        elif guild_id_str in self._deleted_characters_ids and character_id in self._deleted_characters_ids[guild_id_str]:
             print(f"CharacterManager: Character {character_id} in guild {guild_id_str} already marked for deletion.")
        else:
             print(f"CharacterManager: Warning: Attempted to mark non-existent character {character_id} in guild {guild_id_str} as deleted.")


    # --- Метод удаления (публичный) ---
    # Метод уже принимает guild_id и **kwargs
    async def remove_character(self, character_id: str, guild_id: str, **kwargs: Any) -> Optional[str]:
        """
        Удаляет персонажа (помечает для удаления из DB) и выполняет очистку
        связанных сущностей (предметы, статусы, группа, бой, диалог) для определенной гильдии.
        """
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
        char = self.get_character(guild_id_str, character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found for removal in guild {guild_id_str}.")
            return None

        # Дополнительная проверка guild_id (уже делается в get_character с guild_id, но оставим для явности)
        # char_guild_id = getattr(char, 'guild_id', None)
        # if str(char_guild_id) != guild_id_str: # This check is redundant if get_character works correctly
        #      print(f"CharacterManager: Logic error: Character {character_id} belongs to guild {char_guild_id}, but remove_character called with {guild_id_str}.")
        #      return None # Should not happen if get_character is used correctly


        print(f"CharacterManager: Removing character {character_id} ({getattr(char, 'name', 'N/A')}) from guild {guild_id_str}...")

        # Cleanup via managers (используем менеджеры, переданные в __init__)
        # Передаем context, включая guild_id и character_id
        cleanup_context: Dict[str, Any] = { # Явная аннотация Dict
            'guild_id': guild_id_str, # Передаем guild_id_str
            'character_id': character_id, # Передаем character_id
            'character': char, # Pass the character object for convenience
            # TODO: Добавить другие необходимые менеджеры, сервисы из self._ в cleanup_context
            # Включаем прочие из kwargs, если передаются в remove_character (напр., send_callback_factory)
        }
        cleanup_context.update(kwargs) # Добавляем kwargs через update

        # Add potentially relevant managers to context *from self* if they exist and are not already in kwargs
        # This ensures cleanup methods receive managers they might need, even if GameManager didn't pass them explicitly in kwargs
        if self._item_manager: cleanup_context['item_manager'] = self._item_manager
        if self._status_manager: cleanup_context['status_manager'] = self._status_manager
        if self._party_manager: cleanup_context['party_manager'] = self._party_manager
        if self._combat_manager: cleanup_context['combat_manager'] = self._combat_manager
        if self._dialogue_manager: cleanup_context['dialogue_manager'] = self._dialogue_manager
        if self._location_manager: cleanup_context['location_manager'] = self._location_manager
        if self._rule_engine: cleanup_context['rule_engine'] = self._rule_engine
        # TODO: Add other managers if needed in cleanup methods (Economy? Crafting? Event?)


        try:
            # Убедитесь, что методы clean_up_* существуют в соответствующих менеджерах
            # и что они принимают entity_id ('character_id') и context.
            # Предполагаем, что они принимают entity_id и context.
            if self._item_manager and hasattr(self._item_manager, 'clean_up_for_character'):
                await self._item_manager.clean_up_for_character(character_id, context=cleanup_context)
            if self._status_manager and hasattr(self._status_manager, 'clean_up_for_character'):
                 await self._status_manager.clean_up_for_character(character_id, context=cleanup_context)
            # PartyManager.clean_up_for_character должен уметь чистить по character_id и guild_id (через context)
            if self._party_manager and hasattr(self._party_manager, 'clean_up_for_character'):
                 await self._party_manager.clean_up_for_character(character_id, context=cleanup_context)
            # CombatManager.clean_up_for_character должен уметь чистить по character_id и guild_id (через context)
            if self._combat_manager and hasattr(self._combat_manager, 'clean_up_for_character'):
                 await self._combat_manager.clean_up_for_character(character_id, context=cleanup_context)
            # DialogueManager.clean_up_for_character должен уметь чистить по character_id и guild_id (через context)
            if self._dialogue_manager and hasattr(self._dialogue_manager, 'clean_up_for_character'):
                 await self._dialogue_manager.clean_up_for_character(character_id, context=cleanup_context)

            print(f"CharacterManager: Cleanup initiated for character {character_id} in guild {guild_id_str}.")

        except Exception as e:
             print(f"CharacterManager: Error during cleanup for character {character_id} in guild {guild_id_str}: {e}")
             import traceback
             print(traceback.format_exc())
             # Decide whether to re-raise or just log. Logging allows the core character removal to proceed.


        # Отмечаем персонажа как удаленного (удалит из кеша и добавит в per-guild список на удаление из DB)
        # ИСПРАВЛЕНИЕ: Передаем guild_id в mark_character_deleted
        self.mark_character_deleted(guild_id_str, character_id)

        print(f"CharacterManager: Character {character_id} ({getattr(char, 'name', 'N/A')}) removal process initiated for guild {guild_id_str}. Will be deleted from DB on next save.")
        return character_id # Возвращаем ID удаленного персонажа

    # --- Методы обновления состояния персонажа ---

    # Добавляем guild_id и **kwargs к методам обновления
    async def set_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        """Устанавливает ID группы для персонажа для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
        char = self.get_character(guild_id_str, character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to set party ID.")
            return False
        # Убедимся, что у объекта Character есть атрибут party_id перед изменением
        if not hasattr(char, 'party_id'):
             print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'party_id' attribute.")
             return False # Не удалось установить party_id, если атрибут отсутствует

        # Ensure party_id is str or None
        resolved_party_id = str(party_id) if party_id is not None else None

        if getattr(char, 'party_id', None) == resolved_party_id: # Compare using getattr for safety
            return True # Already in this group or already without group

        char.party_id = resolved_party_id # Set the updated party ID

        self.mark_character_dirty(guild_id_str, character_id) # Помечаем, что персонаж изменен для этой гильдии
        print(f"CharacterManager: Set party ID for character {character_id} in guild {guild_id_str} to {resolved_party_id}.")
        return True

    # Метод уже принимает guild_id и **kwargs
    async def update_character_location(self, character_id: str, location_id: Optional[str], guild_id: str, **kwargs: Any) -> bool:
        """Обновляет локацию персонажа для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
        char = self.get_character(guild_id_str, character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to update location.")
            return False

        # Убедимся, что у объекта Character есть атрибут location_id перед изменением
        if not hasattr(char, 'location_id'):
             print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'location_id' attribute.")
             return False # Не удалось установить location_id, если атрибут отсутствует

        # Ensure location_id is str or None
        resolved_location_id = str(location_id) if location_id is not None else None

        if getattr(char, 'location_id', None) == resolved_location_id:
             return True # Already there

        char.location_id = resolved_location_id # Set the updated location ID

        self.mark_character_dirty(guild_id_str, character_id) # Помечаем измененным для этой гильдии
        print(f"CharacterManager: Updated location for character {character_id} in guild {guild_id_str} to {resolved_location_id}.")

        # TODO: Trigger arrival/departure events here or delegate
        # Example: if self._location_manager and hasattr(self._location_manager, 'handle_entity_departure'):
        # await self._location_manager.handle_entity_departure(char.id, "Character", old_location_id, context=kwargs)
        # if self._location_manager and hasattr(self._location_manager, 'handle_entity_arrival'):
        # await self._location_manager.handle_entity_arrival(char.id, "Character", new_location_id, context=kwargs)


        return True

    # ИСПРАВЛЕНИЕ: Добавляем guild_id и **kwargs
    async def add_item_to_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
         """Добавляет предмет в инвентарь персонажа для определенной гильдии."""
         guild_id_str = str(guild_id)
         # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
         char = self.get_character(guild_id_str, character_id)
         if not char:
             print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to add item.")
             return False

         # Убедимся, что у объекта Character есть атрибут inventory и это список
         if not hasattr(char, 'inventory') or not isinstance(char.inventory, list):
              print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'inventory' list or it's incorrect type ({type(getattr(char, 'inventory', None))}). Initializing empty list.")
              char.inventory = [] # Инициализируем пустой список, если отсутствует/неправильный тип

         # Logic to add/update item quantity
         item_found = False
         resolved_item_id = str(item_id) # Ensure item_id is string
         resolved_quantity = int(quantity) # Ensure quantity is integer

         if resolved_quantity <= 0:
             print(f"CharacterManager: Warning: Attempted to add non-positive quantity ({resolved_quantity}) of item '{resolved_item_id}' to {character_id} in guild {guild_id_str}.")
             return False # Cannot add 0 or negative quantity

         # Assuming char.inventory - это List[Dict[str, Any]] с полями 'item_id', 'quantity'
         # Iterate through a copy if you modify the list structure (add/remove entries)
         for item_entry in char.inventory:
             # Check if item_entry is a dictionary and has 'item_id'
             if isinstance(item_entry, dict) and item_entry.get('item_id') == resolved_item_id:
                 # Check if item_entry contains 'quantity' and it's a number type
                 current_quantity = item_entry.get('quantity', 0)
                 if not isinstance(current_quantity, (int, float)):
                     print(f"CharacterManager: Warning: Invalid quantity type for item '{resolved_item_id}' in inventory of {character_id} ({type(current_quantity)}). Resetting to 0.")
                     current_quantity = 0

                 item_entry['quantity'] = current_quantity + resolved_quantity
                 item_found = True
                 print(f"CharacterManager: Increased quantity of item '{resolved_item_id}' for {character_id} to {item_entry['quantity']} in guild {guild_id_str}.")
                 break # Found and updated, break loop

         if not item_found:
             # Add new item entry if not found
             char.inventory.append({'item_id': resolved_item_id, 'quantity': resolved_quantity})
             print(f"CharacterManager: Added new item '{resolved_item_id}' (x{resolved_quantity}) to {character_id} inventory in guild {guild_id_str}.")


         self.mark_character_dirty(guild_id_str, character_id) # Помечаем персонажа измененным для этой гильдии
         return True


    # ИСПРАВЛЕНИЕ: Добавляем guild_id и **kwargs
    async def remove_item_from_inventory(self, guild_id: str, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
         """Удаляет предмет из инвентаря персонажа для определенной гильдии."""
         guild_id_str = str(guild_id)
         # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
         char = self.get_character(guild_id_str, character_id)
         if not char:
             print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to remove item.")
             return False

         # Убедимся, что у объекта Character есть атрибут inventory и это список
         if not hasattr(char, 'inventory') or not isinstance(char.inventory, list):
             print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'inventory' list or it's incorrect type. Cannot remove item.")
             return False

         resolved_item_id = str(item_id)
         resolved_quantity = int(quantity)

         if resolved_quantity <= 0:
             print(f"CharacterManager: Warning: Attempted to remove non-positive quantity ({resolved_quantity}) of item '{resolved_item_id}' from {character_id} in guild {guild_id_str}.")
             return False # Cannot remove 0 or negative quantity


         item_index_to_remove = -1
         item_found_to_remove = False # Flag if the item entry was found
         item_was_modified = False # Flag if quantity was decreased or item was removed

         # Iterate through a copy if you might remove elements
         inventory_copy = list(char.inventory) # Work on a copy to find index for removal safely
         for i, item_entry in enumerate(inventory_copy):
             # Assuming char.inventory - это List[Dict[str, Any]]
             if isinstance(item_entry, dict) and item_entry.get('item_id') == resolved_item_id:
                 item_found_to_remove = True # Found the item entry

                 current_quantity = item_entry.get('quantity', 0)
                 if not isinstance(current_quantity, (int, float)):
                      print(f"CharacterManager: Warning: Invalid quantity type for item '{resolved_item_id}' in inventory of {character_id} ({type(current_quantity)}). Resetting to 0 for calculation.")
                      current_quantity = 0

                 if current_quantity > 0: # Only remove if quantity is positive
                      new_quantity = max(0.0, current_quantity - resolved_quantity) # Prevent negative quantity
                      if new_quantity < current_quantity: # Check if quantity actually decreased
                           item_was_modified = True
                           # Find the original item entry in the actual inventory list by item_id
                           # Assuming item_id is unique in the inventory list structure
                           for original_entry in char.inventory:
                               if isinstance(original_entry, dict) and original_entry.get('item_id') == resolved_item_id:
                                   original_entry['quantity'] = new_quantity # Update the actual list
                                   if new_quantity <= 0:
                                        # Mark for removal from the actual list AFTER the loop
                                        # This requires a different approach than iterating and modifying the same list
                                        # A common pattern is to rebuild the list or collect indices/items to remove
                                        # Let's rebuild the list after the loop if needed
                                        pass # Mark for removal later
                                   break # Found original entry
                      # else: print(f"CharacterManager: Warning: Attempted to remove {resolved_quantity} of item '{resolved_item_id}' from {character_id}, but only {current_quantity} available.")

                 break # Found the item entry, no need to continue iteration


         # Rebuild the inventory list if items need to be removed (quantity <= 0)
         if item_found_to_remove and item_was_modified:
             new_inventory = []
             removed_any = False
             for original_entry in char.inventory:
                 if isinstance(original_entry, dict) and original_entry.get('item_id') == resolved_item_id:
                     if original_entry.get('quantity', 0) > 0:
                         new_inventory.append(original_entry) # Keep if quantity is positive
                     else:
                         removed_any = True # Item removed
                 else:
                     new_inventory.append(original_entry) # Keep other items

             if removed_any:
                 char.inventory = new_inventory # Replace the inventory list


         # Check if the item was found at all
         if not item_found_to_remove:
              print(f"CharacterManager: Warning: Attempted to remove item '{resolved_item_id}' from character {character_id} in guild {guild_id_str}, but item entry not found in inventory.")
              return False # Item entry not found


         # If we reached here, the item entry was found.
         # item_was_modified indicates if the quantity was decreased.
         # Even if quantity wasn't decreased (e.g. quantity requested was 0),
         # if the item was found, the method technically succeeded in *checking*.
         # But usually, remove_item implies quantity > 0.
         # Let's return True if the item entry was found and quantity requested was > 0.
         # Or better, return True if the item entry was found AND its quantity was updated (or it was removed).
         if item_found_to_remove and item_was_modified:
              self.mark_character_dirty(guild_id_str, character_id) # Mark dirty only if modified
              print(f"CharacterManager: Removed {resolved_quantity} of item '{resolved_item_id}' from character {character_id} inventory (if available) in guild {guild_id_str}.")
              return True # Item was found and potentially modified/removed

         # If found but not modified (e.g., tried to remove 0 quantity, or quantity was already 0)
         if item_found_to_remove:
              print(f"CharacterManager: Item '{resolved_item_id}' found in {character_id}'s inventory, but quantity not decreased (current: {item_entry.get('quantity', 'N/A')}, remove: {resolved_quantity}) in guild {guild_id_str}.")
              return False # Or True, depending on exact desired behavior. Let's return False if quantity wasn't removed.

         # Should not reach here if item_found_to_remove logic is correct
         return False


    # ИСПРАВЛЕНИЕ: Добавляем guild_id и **kwargs
    async def update_health(self, guild_id: str, character_id: str, amount: float, **kwargs: Any) -> bool:
         """Обновляет здоровье персонажа для определенной гильдии."""
         guild_id_str = str(guild_id)
         # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
         char = self.get_character(guild_id_str, character_id)
         if not char:
             print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to update health.")
             return False

         # Убедимся, что у объекта Character есть атрибуты health, max_health, is_alive и что health/max_health числовые
         if not hasattr(char, 'health') or not isinstance(char.health, (int, float)):
              print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'health' attribute or it's not a number ({type(getattr(char, 'health', None))}). Cannot update health.")
              return False
         if not hasattr(char, 'max_health') or not isinstance(char.max_health, (int, float)):
              print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'max_health' attribute or it's not a number ({type(getattr(char, 'max_health', None))}). Cannot update health.")
              return False
         if not hasattr(char, 'is_alive') or not isinstance(char.is_alive, bool):
             print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'is_alive' attribute or it's not boolean ({type(getattr(char, 'is_alive', None))}). Cannot update health.")
             return False

         # If character is already dead and this is not positive healing/resurrection
         # Check against the actual is_alive attribute
         if not char.is_alive and amount <= 0:
             # print(f"CharacterManager: Character {character_id} in guild {guild_id_str} is dead, cannot take non-positive damage/healing.")
             return False # Cannot harm or not heal a dead character


         # Общая логика обновления здоровья
         new_health = char.health + amount
         # Ограничиваем здоровье между 0 и max_health
         char.health = max(0.0, min(char.max_health, new_health)) # Use 0.0 and char.max_health as float

         self.mark_character_dirty(guild_id_str, character_id) # Помечаем измененным для этой гильдии

         # Проверяем смерть после обновления
         # Check against the updated health attribute
         if char.health <= 0 and char.is_alive: # If health became <= 0 AND character is still marked as alive
              # handle_character_death expects character_id, guild_id and **kwargs
              await self.handle_character_death(guild_id_str, character_id, **kwargs) # Pass guild_id and context to handler

         print(f"CharacterManager: Updated health for character {character_id} in guild {guild_id_str} to {char.health}. Amount: {amount}.")
         return True


    # ИСПРАВЛЕНИЕ: handle_character_death должен принимать guild_id
    async def handle_character_death(self, guild_id: str, character_id: str, **kwargs: Any):
         """Обрабатывает смерть персонажа для определенной гильдии."""
         guild_id_str = str(guild_id)
         # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
         char = self.get_character(guild_id_str, character_id)
         # Проверяем, что персонаж существует и еще жив (по атрибуту is_alive)
         # Safely check is_alive, default to False if attribute missing or is None
         if not char or not getattr(char, 'is_alive', False):
             print(f"CharacterManager: handle_character_death called for non-existent ({char is None}) or already dead character {character_id} in guild {guild_id_str}.")
             return

         # Убедимся, что у объекта Character есть атрибут is_alive перед изменением
         if hasattr(char, 'is_alive'):
             char.is_alive = False # Помечаем как мертвого
         else:
             print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'is_alive' attribute. Cannot mark as dead.")
             # Decide if this should stop the death handling process or continue best effort
             # Let's continue best effort for cleanup but log the warning.


         self.mark_character_dirty(guild_id_str, character_id) # Помечаем измененным для этой гильдии

         print(f"Character {character_id} ({getattr(char, 'name', 'N/A')}) has died in guild {guild_id_str}.")

         # TODO: Логика смерти:
         # Используем менеджеры, которые были инжектированы в __init__
         # Получаем колбэк отправки сообщения из kwargs, если он передан (из ActionProcessor or CommandRouter)
         # Если send_callback_factory проинжектирован в GameManager и доступен в kwargs, используем его.
         send_callback_factory = kwargs.get('send_callback_factory') # Type: Optional[Callable[[int], Callable[..., Awaitable[Any]]]]]
         channel_id = kwargs.get('channel_id') # Channel ID might be passed in kwargs

         if send_callback_factory: # Needs factory
             # Попытка получить ID канала смерти из настроек или LocationManager, если channel_id не передан
             death_channel_id = channel_id # Start with channel_id from kwargs
             if death_channel_id is None and self._settings is not None:
                 # Example: Death channel ID in settings, potentially per-guild
                 guild_settings = self._settings.get('guilds', {}).get(guild_id_str, {}) # Try to get guild-specific settings
                 death_channel_id_setting = guild_settings.get('death_channel_id') or self._settings.get('death_channel_id') # Fallback to global setting
                 if death_channel_id_setting is not None:
                      try: death_channel_id = int(death_channel_id_setting) # Attempt conversion
                      except (ValueError, TypeError): print(f"CharacterManager: Warning: Invalid 'death_channel_id' in settings for guild {guild_id_str}: {death_channel_id_setting}. Expected integer."); death_channel_id = None
             # TODO: Get death channel from LocationManager based on location of death (char.location_id)

             if death_channel_id is not None:
                  # Get the callback for the death channel
                  try:
                       send_callback = send_callback_factory(death_channel_id) # Type: Callable[..., Awaitable[Any]]]
                       # Death message (can be templated or generated)
                       char_name = getattr(char, 'name', 'Unknown')
                       death_message = f"☠️ Персонаж **{char_name}** погиб! ☠️" # Template
                       await send_callback(death_message, None)
                  except Exception as e: print(f"CharacterManager: Error sending death message for {character_id} to channel {death_channel_id} in guild {guild_id_str}: {e}"); import traceback; print(traceback.format_exc());
             else:
                  print(f"CharacterManager: Warning: No death channel ID found for guild {guild_id_str}. Cannot send death message.")


         # Cleanup related states (statuses, combat, party, dialogue, etc.)
         # Use injected managers (self._...) and pass the context kwargs.
         cleanup_context: Dict[str, Any] = { # Assemble context for clean_up_* methods
             'guild_id': guild_id_str, # Pass guild_id_str
             'character_id': character_id, # Pass character_id
             'character': char, # Pass the character object
             # Add potentially relevant managers to context *from self* if they exist and are not already in kwargs
             'item_manager': kwargs.get('item_manager', self._item_manager),
             'status_manager': kwargs.get('status_manager', self._status_manager),
             'party_manager': kwargs.get('party_manager', self._party_manager),
             'combat_manager': kwargs.get('combat_manager', self._combat_manager),
             'dialogue_manager': kwargs.get('dialogue_manager', self._dialogue_manager),
             'location_manager': kwargs.get('location_manager', self._location_manager),
             'rule_engine': kwargs.get('rule_engine', self._rule_engine),
             'send_callback_factory': send_callback_factory, # Pass factory if available
             'settings': kwargs.get('settings', self._settings), # Pass settings if available
             'channel_id': channel_id, # Pass the originating channel_id if available
             # TODO: Add other necessary managers/services from self._ or kwargs into cleanup_context
         }
         # Do NOT update cleanup_context with **kwargs here, as it might overwrite essential keys
         # Instead, list the desired keys or handle kwargs individually within each cleanup call if needed.
         # OR, add kwargs first, then overwrite with specific managers from self._ if self._ exists.
         # Example: cleanup_context.update(kwargs) # Add passed kwargs
         # if self._item_manager: cleanup_context['item_manager'] = self._item_manager # Overwrite if self._ is preferred

         # Let's stick to explicitly listing needed managers in context for clarity, prioritizing self._ attributes if available.
         # Re-assemble cleanup_context incorporating kwargs *where appropriate* or just passing all kwargs down.
         # A safer approach is to pass character_id, guild_id, and the essential managers explicitly, then **kwargs for everything else.
         # The cleanup methods themselves should be written to handle the received context.
         # Let's pass the core info explicitly, then the collected managers/context dict as **kwargs.

         base_cleanup_kwargs = {
            'guild_id': guild_id_str,
            'character_id': character_id,
            'character': char,
            # Essential managers for cleanup
            'item_manager': self._item_manager,
            'status_manager': self._status_manager,
            'party_manager': self._party_manager,
            'combat_manager': self._combat_manager,
            'dialogue_manager': self._dialogue_manager,
            'location_manager': self._location_manager,
            'rule_engine': self._rule_engine,
            # Potentially pass send_callback_factory if cleanup needs to send messages
            'send_callback_factory': send_callback_factory,
            'settings': self._settings, # Pass settings if cleanup logic needs them
            'channel_id': channel_id, # Pass originating channel if available
            # Add others needed for cleanup...
         }
         # Add any extra kwargs received by handle_character_death to the context passed to cleanup methods
         base_cleanup_kwargs.update(kwargs) # Safely add remaining kwargs

         # Omit None managers from context passed to cleanup methods if clean_up methods expect Optional
         # cleanup_context_filtered = {k: v for k, v in base_cleanup_kwargs.items() if v is not None} # Optional filtering

         # Call cleanup methods, passing relevant arguments explicitly or via **kwargs
         # Make sure cleanup methods accept these arguments.
         # Assuming cleanup methods accept entity_id (character_id), context (Dict[str, Any]), and potentially other kwargs.
         # Let's pass character_id and the gathered context dict as **context_kwargs
         # Example: clean_up_for_character(character_id: str, context: Dict[str, Any]) -> None

         try:
             if self._status_manager and hasattr(self._status_manager, 'clean_up_for_character'):
                  await self._status_manager.clean_up_for_character(character_id, context=base_cleanup_kwargs) # Pass the context dict
             if self._combat_manager and hasattr(self._combat_manager, 'remove_participant_from_combat'):
                  # remove_participant_from_combat might need entity_type
                  await self._combat_manager.remove_participant_from_combat(character_id, entity_type="Character", context=base_cleanup_kwargs) # Pass the context dict
             if self._party_manager and hasattr(self._party_manager, 'clean_up_for_character'):
                  await self._party_manager.clean_up_for_character(character_id, context=base_cleanup_kwargs) # Pass the context dict
             if self._dialogue_manager and hasattr(self._dialogue_manager, 'clean_up_for_character'):
                  await self._dialogue_manager.clean_up_for_character(character_id, context=base_cleanup_kwargs) # Pass the context dict

             # Drop items (if location_id is available on character)
             if self._item_manager and hasattr(self._item_manager, 'drop_all_inventory') and getattr(char, 'location_id', None) is not None:
                  await self._item_manager.drop_all_inventory(character_id, entity_type="Character", location_id=char.location_id, context=base_cleanup_kwargs) # Pass location_id explicitly, and the context dict

             # Trigger death logic in RuleEngine
             if self._rule_engine and hasattr(self._rule_engine, 'trigger_death'):
                  # Assuming trigger_death accepts entity (Character object) and context
                  await self._rule_engine.trigger_death(char, context=base_cleanup_kwargs) # Pass the character object and context dict

             print(f"CharacterManager: Death cleanup initiated for character {character_id} in guild {guild_id_str}.")

         except Exception as e:
              print(f"CharacterManager: Error during death cleanup for character {character_id} in guild {guild_id_str}: {e}")
              import traceback
              print(traceback.format_exc())
              # Log error, continue


         print(f"CharacterManager: Death cleanup process completed for character {character_id} in guild {guild_id_str}.")


    # --- Методы для управления активностью/занятостью ---

    # ИСПРАВЛЕНИЕ: set_active_action должен принимать guild_id
    def set_active_action(self, guild_id: str, character_id: str, action_details: Optional[Dict[str, Any]]) -> None:
        """Устанавливает текущее активное действие персонажа для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
        char = self.get_character(guild_id_str, character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to set active action.")
            return

        # Убедимся, что у объекта Character есть атрибут current_action
        if hasattr(char, 'current_action'):
            char.current_action = action_details
        else:
            print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'current_action' attribute. Cannot set active action.")
            return # Cannot set if attribute is missing


        # ИСПРАВЛЕНИЕ: Управляем занятостью в per-guild Set
        guild_active_action_cache = self._entities_with_active_action.setdefault(guild_id_str, set())
        if action_details is not None:
            guild_active_action_cache.add(character_id)
        else:
            # Check if there's still something in the queue before marking not busy
            if not getattr(char, 'action_queue', []): # Safely check action_queue attribute
                 guild_active_action_cache.discard(character_id)


        self.mark_character_dirty(guild_id_str, character_id) # Помечаем, что персонаж изменен для этой гильдии


    # ИСПРАВЛЕНИЕ: add_action_to_queue должен принимать guild_id
    def add_action_to_queue(self, guild_id: str, character_id: str, action_details: Dict[str, Any]) -> None:
        """Добавляет действие в очередь персонажа для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
        char = self.get_character(guild_id_str, character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to add action to queue.")
            return

        # Убедимся, что у объекта Character есть атрибут action_queue и это список
        if not hasattr(char, 'action_queue') or not isinstance(char.action_queue, list):
             print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'action_queue' list or it's incorrect type. Initializing empty list.")
             char.action_queue = [] # Initialize empty list if missing/wrong type

        char.action_queue.append(action_details)
        self.mark_character_dirty(guild_id_str, character_id)
        # ИСПРАВЛЕНИЕ: Помечаем занятым в per-guild Set, т.к. есть что-то в очереди
        self._entities_with_active_action.setdefault(guild_id_str, set()).add(character_id)


    # ИСПРАВЛЕНИЕ: get_next_action_from_queue должен принимать guild_id
    def get_next_action_from_queue(self, guild_id: str, character_id: str) -> Optional[Dict[str, Any]]:
        """Извлекает следующее действие из очереди для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
        char = self.get_character(guild_id_str, character_id)
        # Убедимся, что у объекта Character есть атрибут action_queue и это не пустой список
        if not char or not hasattr(char, 'action_queue') or not isinstance(char.action_queue, list) or not char.action_queue:
            return None

        # Извлекаем первое действие из очереди
        next_action = char.action_queue.pop(0) # Removes from start of list (modifies attribute)
        self.mark_character_dirty(guild_id_str, character_id) # Mark character as dirty for this guild

        # ИСПРАВЛЕНИЕ: Если очередь опустела И нет текущего действия, снимаем пометку "занят" для этой гильдии
        if not char.action_queue and getattr(char, 'current_action', None) is None: # Safely check current_action attribute
             guild_active_action_cache = self._entities_with_active_action.get(guild_id_str)
             if guild_active_action_cache:
                  guild_active_action_cache.discard(character_id)

        return next_action


    # --- Вспомогательные методы ---
    # async def notify_character(self, character_id: str, message: str, **kwargs):
    #      """Метод для отправки сообщений конкретному персонажу (через Discord или другие средства)."""
    #      # As noted, this belongs in processors or services that handle communication.
    #      pass

    # TODO: Add clean_up_from_party(character_id, context) method (used by PartyManager)
    # async def clean_up_from_party(self, character_id: str, context: Dict[str, Any]) -> None:
    #      """Сбросить party_id персонажа когда он покидает группу."""
    #      guild_id = context.get('guild_id')
    #      if guild_id is None:
    #           print(f"CharacterManager: Error in clean_up_from_party: Missing guild_id in context for character {character_id}.")
    #           return
    #      guild_id_str = str(guild_id)
    #      char = self.get_character(guild_id_str, character_id)
    #      if not char:
    #           print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} for party cleanup.")
    #           return
    #      if getattr(char, 'party_id', None) is not None:
    #           char.party_id = None # Reset party_id
    #           self.mark_character_dirty(guild_id_str, character_id)
    #           print(f"CharacterManager: Cleaned up party_id for character {character_id} in guild {guild_id_str}.")

    # TODO: Add clean_up_from_combat(character_id, context) method (used by CombatManager)
    # async def clean_up_from_combat(self, character_id: str, context: Dict[str, Any]) -> None:
    #      """Сбросить combat_id персонажа когда он покидает бой."""
    #      # Similar logic to clean_up_from_party
    #      pass

    # TODO: Add clean_up_from_dialogue(character_id, context) method (used by DialogueManager)
    # async def clean_up_from_dialogue(self, character_id: str, context: Dict[str, Any]) -> None:
    #      """Сбросить dialogue_id/state персонажа когда он покидает диалог."""
    #      # Similar logic
    #      pass


# --- Конец класса CharacterManager ---


print("DEBUG: character_manager.py module loaded.")
