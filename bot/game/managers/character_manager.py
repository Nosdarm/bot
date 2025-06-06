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
# Используйте строковые литералы ("ClassName") для type hints в __init__ и методах
# для классов, импортированных здесь.
if TYPE_CHECKING:
    # Add DBService here
    from bot.services.db_service import DBService
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
    from bot.game.models.npc import NPC # Added for type hinting killer_entity
    # Ensure ItemManager is imported for type hinting
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.managers.npc_manager import NPCManager
    from bot.game.managers.game_manager import GameManager


# --- Imports needed at Runtime ---
# For CharacterManager, you usually need direct import of the Character model and utilities.


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
        db_service: Optional["DBService"] = None, # Changed from db_adapter
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        location_manager: Optional["LocationManager"] = None,
        rule_engine: Optional["RuleEngine"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        npc_manager: Optional["NPCManager"] = None, # Add this
        game_manager: Optional["GameManager"] = None  # Add this
    ):
        print("Initializing CharacterManager...")
        self._db_service = db_service # Changed from _db_adapter
        self._settings = settings
        self._item_manager = item_manager
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager
        self._relationship_manager = relationship_manager
        self._game_log_manager = game_log_manager
        self._npc_manager = npc_manager # Add this
        self._game_manager = game_manager # Add this

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
    # Made synchronous as it does not await anything internally
    def get_character_by_discord_id(self, guild_id: str, discord_user_id: int) -> Optional["Character"]:
        """Получить персонажа по Discord User ID для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ДОБАВЛЕНЫ СТРОКИ ОТЛАДКИ
        # print(f"DEBUG: CharacterManager: Attempting to get character for Discord ID {discord_user_id} in guild {guild_id_str}...") # Too noisy

        # ИСПРАВЛЕНИЕ: Используем per-guild мапу
        guild_discord_map = self._discord_to_char_map.get(guild_id_str) # Type: Optional[Dict[int, str]]

        # ДОБАВЛЕНЫ СТРОКИ ОТЛАДКИ
        # if guild_discord_map:
        #      print(f"DEBUG: CharacterManager: Found guild_discord_map for guild {guild_id_str}. Keys: {list(guild_discord_map.keys()) if isinstance(guild_discord_map, dict) else 'Not a dict'}. Looking for Discord ID {discord_user_id}.") # Too noisy
        # else:
        #      print(f"DEBUG: CharacterManager: No guild_discord_map found for guild {guild_id_str}.") # Too noisy


        if isinstance(guild_discord_map, dict): # Проверяем, что это словарь перед get
             char_id = guild_discord_map.get(discord_user_id) # Type: Optional[str]

             # ДОБАВЛЕНЫ СТРОКИ ОТЛАДКИ
             # if char_id:
             #     print(f"DEBUG: CharacterManager: Found char_id '{char_id}' in map for Discord ID {discord_user_id}. Attempting to get from _characters cache...") # Too noisy
             # else:
             #     print(f"DEBUG: CharacterManager: Char_id not found in map for Discord ID {discord_user_id}.") # Too noisy


             if char_id:
                 # Возвращаем персонажа из основного кеша для этой гильдии
                 # get_character также должен логировать
                 char = self.get_character(guild_id, char_id) # Используем get_character с guild_id
                 # ДОБАВЛЕНЫ СТРОКИ ОТЛАДКИ
                 # if char:
                 #      print(f"DEBUG: CharacterManager: Successfully retrieved character {char_id} from _characters cache.") # Too noisy
                 # else:
                 #      print(f"DEBUG: CharacterManager: Char_id '{char_id}' found in map, but character NOT found in _characters cache for guild {guild_id_str}! Cache inconsistency?") # Critical, keep
                 #      # Это может указывать на несогласованность кешей. Возможно, персонаж в мапе, но не загрузился в основной кеш.
                 #      # ОСТОРОЖНО: Если мапа глобальная, а кеш пер-гильдийный, эта логика может быть сложной.
                 #      # В текущей реализации, мапа и кеш ПРЕДПОЛАГАЮТСЯ пер-гильдийными.
                 #      # Если персонаж в мапе гильдии, но нет в кеше гильдии, это проблема.
                 #      # Удаление из мапы может помочь, но это изменение состояния, требующее mark_dirty мапы?
                 #      # Пока просто логируем предупреждение.
                 if not char: # More concise logging for this critical case
                     print(f"CRITICAL: CharacterManager: Char_id '{char_id}' for Discord ID {discord_user_id} found in map, but character NOT in _characters cache for guild {guild_id_str}! Cache inconsistency.")
                 return char # Возвращает найденный персонаж или None


        # ДОБАВЛЕНЫ СТРОКИ ОТЛАДКИ (уже была, убедитесь, что она там)
        # print(f"DEBUG: CharacterManager: Character not found for Discord ID {discord_user_id} in guild {guild_id_str}.") # Too noisy
        return None

    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Принимаем guild_id
    def get_character_by_name(self, guild_id: str, name: str) -> Optional["Character"]:
         """Получить персонажа по имени для определенной гильдии (может быть медленно)."""
         # ИСПРАВЛЕНИЕ: Итерируем только по персонажам этой гильдии
         guild_chars = self._characters.get(str(guild_id))
         if guild_chars:
              for char in guild_chars.values():
                  # Use getattr for safer access to name, fallback to id if name is missing
                  if isinstance(char, Character) and getattr(char, 'name', char.id) == name:
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
        level: int = 1,
        experience: int = 0,
        unspent_xp: int = 0,
        # Добавляем **kwargs для контекста, хотя guild_id теперь обязателен
        **kwargs: Any
    ) -> Optional["Character"]: # Возвращаем Optional["Character"], т.к. создание может не удасться
        """
        Создает нового персонажа в базе данных, кеширует его и возвращает объект Character.
        Принимает discord_id, name, guild_id.
        """
        if self._db_service is None or self._db_service.adapter is None: # Check adapter too
            print(f"CharacterManager: Error: DB service or adapter missing for guild {guild_id}.")
            # В многогильдийном режиме, возможно, нужно рейзить ошибку, т.к. без DB данные не будут персистировать
            raise ConnectionError("Database service or adapter is not initialized in CharacterManager.")

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
        if resolved_initial_location_id is None and self._location_manager is not None: # Explicit None check
             if hasattr(self._location_manager, 'get_default_location_id'):
                 try:
                     # LocationManager.get_default_location_id(guild_id: str) -> Optional[str]
                     resolved_initial_location_id = self._location_manager.get_default_location_id(guild_id=guild_id_str)
                     if resolved_initial_location_id:
                          print(f"CharacterManager: Using default location ID: {resolved_initial_location_id} for guild {guild_id_str}")
                 except Exception as e:
                     print(f"CharacterManager: Warning: Could not get default location ID for guild {guild_id_str}: {e}")
                     import traceback
                     print(traceback.format_exc())
             else:
                print(f"CharacterManager: Warning: LocationManager is present but missing 'get_default_location_id' method.")


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


        # Determine default player language
        default_player_language = "en" # Fallback default
        if hasattr(self, '_game_manager') and self._game_manager is not None: # Check if GameManager is available
            if hasattr(self._game_manager, 'get_default_bot_language') and callable(getattr(self._game_manager, 'get_default_bot_language')):
                try:
                    # Assuming get_default_bot_language is synchronous as per previous subtask
                    default_player_language = self._game_manager.get_default_bot_language()
                except Exception as lang_e:
                    print(f"CharacterManager: Error calling get_default_bot_language: {lang_e}. Defaulting to 'en'.")
                    default_player_language = "en"
            else:
                print("CharacterManager: Warning: GameManager instance does not have a callable 'get_default_bot_language' method. Defaulting player language to 'en'.")
        else:
            # This case can be common if GameManager is not passed or setup fully.
            # print("CharacterManager: Note: GameManager instance not available in CharacterManager. Defaulting player language to 'en'.") # Can be noisy
            pass


        # Подготавливаем данные для вставки в DB и создания модели
        name_i18n_data = {"en": name, "ru": name} # Basic i18n structure

        data: Dict[str, Any] = {
            'id': new_id, # UUID как TEXT
            'discord_user_id': discord_id, # Значение из параметра discord_id
            'name': name, # Original name for direct use if needed, Character model might store it separately or just use name_i18n
            'name_i18n': name_i18n_data, # NEW
            'guild_id': guild_id_str, # <-- Добавляем guild_id_str
            'location_id': resolved_initial_location_id, # Может быть None
            'stats': stats, # dict
            'inventory': [], # list
            'current_action': None, # null
            'action_queue': [], # list
            'party_id': None, # null
            'state_variables': {}, # dict
            'hp': 100.0,
            'max_health': 100.0,
            'is_alive': True, # bool (сохраняется как integer 0 or 1)
            'status_effects': [], # list
            'level': level,
            'experience': experience,
            'unspent_xp': unspent_xp,
            'selected_language': default_player_language, # Add this
            'collected_actions_json': None, # Default for new character
            # New fields for DB v18+
            'skills_data_json': json.dumps([]), # Default to empty list JSON
            'abilities_data_json': json.dumps([]), # Default to empty list JSON
            'spells_data_json': json.dumps([]), # Default to empty list JSON
            'character_class': kwargs.get('character_class', 'Adventurer'), # Default class
            'flags_json': json.dumps({}) # Default to empty dict JSON
        }

        # Data for Character.from_dict (Python types)
        model_data = data.copy()
        model_data['name_i18n'] = name_i18n_data
        model_data['skills_data'] = []
        model_data['abilities_data'] = []
        model_data['spells_data'] = []
        model_data['flags'] = {}
        # Remove *_json suffixed keys if model attributes don't have them
        del model_data['skills_data_json']
        del model_data['abilities_data_json']
        del model_data['spells_data_json']
        del model_data['flags_json']


        # Преобразуем в JSON для сохранения в DB
        # Note: The 'name' column in DB will store name_i18n JSON.
        sql = """
        INSERT INTO players (
            id, discord_user_id, name, guild_id, location_id, stats, inventory,
            current_action, action_queue, party_id, state_variables,
            hp, max_health, is_alive, status_effects, level, experience, unspent_xp,
            selected_language, collected_actions_json,
            skills_data_json, abilities_data_json, spells_data_json, character_class, flags_json
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25)
        RETURNING id;
        """ # 25 placeholders, changed to $n style, added RETURNING id
        # Убедитесь, что порядок параметров соответствует колонкам в SQL
        db_params = (
            data['id'],
            data['discord_user_id'],
            json.dumps(data['name_i18n']), # Store name_i18n dict as JSON in 'name' column
            data['guild_id'], # <-- Параметр guild_id_str
            data['location_id'],
            json.dumps(data['stats']),
            json.dumps(data['inventory']),
            json.dumps(data['current_action']) if data['current_action'] is not None else None,
            json.dumps(data['action_queue']),
            data['party_id'],
            json.dumps(data['state_variables']),
            data['hp'],
            data['max_health'],
            data['is_alive'], # Boolean directly
            json.dumps(data['status_effects']),
            data['level'],
            data['experience'],
            data['unspent_xp'],
            data['selected_language'],
            data['collected_actions_json'],
            # New fields
            data['skills_data_json'],
            data['abilities_data_json'],
            data['spells_data_json'],
            data['character_class'],
            data['flags_json']
        )

        if self._db_service is None or self._db_service.adapter is None:
             print(f"CharacterManager: Error creating character: DB service or adapter is None for guild {guild_id_str}.")
             raise ConnectionError("Database service or adapter is not initialized in CharacterManager.")

        try:
            # Выполняем INSERT. Используем execute_insert для RETURNING id.
            inserted_id = await self._db_service.adapter.execute_insert(sql, db_params)
            if inserted_id == new_id:
                print(f"CharacterManager: Character '{name}' with ID {new_id} inserted into DB for guild {guild_id_str}.")
            else:
                print(f"CharacterManager: Character '{name}' inserted for guild {guild_id_str}, but returned ID '{inserted_id}' differs from generated '{new_id}'. Using returned ID.")
                # This case should be rare if UUIDs are truly unique.
                # If this happens, it implies the DB might have generated a different ID or there's a logic flaw.
                # For now, we'll proceed with the original new_id for the object, but log this.
                # Consider if model_data['id'] should be updated to inserted_id if they differ.
                # For consistency, let's assume the pre-generated new_id is authoritative for the object.

            # Создаем объект модели Character из данных (данные уже в формате Python объектов)
            # model_data already contains new_id as 'id'
            char = Character.from_dict(model_data) # Use model_data with Python types


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
        if self._db_service is None or self._db_service.adapter is None:
            print(f"CharacterManager: Warning: Cannot save characters for guild {guild_id}, DB service or adapter missing.")
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
            if ids_to_delete: # Ensure there are IDs to delete
                # Dynamically create $2, $3, ... placeholders for player IDs
                placeholders = ', '.join([f'${i+2}' for i in range(len(ids_to_delete))]) # Start from $2
                # Убеждаемся, что удаляем ТОЛЬКО для данного guild_id и по ID из списка
                delete_sql = f"DELETE FROM players WHERE guild_id = $1 AND id IN ({placeholders})"
                try:
                    await self._db_service.adapter.execute(delete_sql, (guild_id_str, *ids_to_delete))
                    print(f"CharacterManager: Deleted {len(ids_to_delete)} characters from DB for guild {guild_id_str}.")
                    # ИСПРАВЛЕНИЕ: Очищаем deleted set для этой гильдии после успешного удаления
                    self._deleted_characters_ids.pop(guild_id_str, None)
                except Exception as e:
                    print(f"CharacterManager: Error deleting characters for guild {guild_id_str}: {e}")
                    import traceback
                    print(traceback.format_exc())
                    # Не очищаем _deleted_characters_ids[guild_id_str], чтобы попробовать удалить снова при следующей сохранке
        else:
            # If the set was empty to begin with for this guild, ensure it's removed from the main dict
            self._deleted_characters_ids.pop(guild_id_str, None)


        # Обновить или вставить измененные персонажи для этого guild_id
        # ИСПРАВЛЕНИЕ: Фильтруем dirty_instances на те, что все еще существуют в per-guild кеше
        guild_chars_cache = self._characters.get(guild_id_str, {})
        characters_to_save = [guild_chars_cache[cid] for cid in list(dirty_char_ids_for_guild_set) if cid in guild_chars_cache]
        if characters_to_save:
             print(f"CharacterManager: Upserting {len(characters_to_save)} characters for guild {guild_id_str}...")
             # INSERT OR REPLACE SQL для обновления существующих или вставки новых.
             # This SQL should now match the save_character method's SQL.
             # PostgreSQL UPSERT syntax
             upsert_sql = '''
             INSERT INTO players (
                id, discord_user_id, name, guild_id, location_id,
                stats, inventory, current_action, action_queue, party_id,
                state_variables, hp, max_health, is_alive, status_effects,
                level, experience, unspent_xp, active_quests, known_spells,
                spell_cooldowns, skills_data_json, abilities_data_json, spells_data_json, flags_json,
                character_class, selected_language, current_game_status, collected_actions_json, current_party_id
             ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30)
             ON CONFLICT (id) DO UPDATE SET
                discord_user_id = EXCLUDED.discord_user_id,
                name = EXCLUDED.name,
                guild_id = EXCLUDED.guild_id,
                location_id = EXCLUDED.location_id,
                stats = EXCLUDED.stats,
                inventory = EXCLUDED.inventory,
                current_action = EXCLUDED.current_action,
                action_queue = EXCLUDED.action_queue,
                party_id = EXCLUDED.party_id,
                state_variables = EXCLUDED.state_variables,
                hp = EXCLUDED.hp,
                max_health = EXCLUDED.max_health,
                is_alive = EXCLUDED.is_alive,
                status_effects = EXCLUDED.status_effects,
                level = EXCLUDED.level,
                experience = EXCLUDED.experience,
                unspent_xp = EXCLUDED.unspent_xp,
                active_quests = EXCLUDED.active_quests,
                known_spells = EXCLUDED.known_spells,
                spell_cooldowns = EXCLUDED.spell_cooldowns,
                skills_data_json = EXCLUDED.skills_data_json,
                abilities_data_json = EXCLUDED.abilities_data_json,
                spells_data_json = EXCLUDED.spells_data_json,
                flags_json = EXCLUDED.flags_json,
                character_class = EXCLUDED.character_class,
                selected_language = EXCLUDED.selected_language,
                current_game_status = EXCLUDED.current_game_status,
                collected_actions_json = EXCLUDED.collected_actions_json,
                current_party_id = EXCLUDED.current_party_id;
             ''' # 30 placeholders, PostgreSQL UPSERT
             data_to_upsert = []
             upserted_char_ids: Set[str] = set() # Track IDs that were successfully prepared for upsert
            # Ensure guild_id_str is used if _deleted_characters_ids was not initialized for this guild before.
            # This pop will not raise an error if the key is missing.
            # The for loop below prepares data for a batch upsert.

             for char_obj in characters_to_save: # Renamed to char_obj to avoid conflict with char module if any
                 try:
                     # Убеждаемся, что у объекта Character есть все нужные атрибуты
                     char_id = getattr(char_obj, 'id', None)
                     discord_user_id = getattr(char_obj, 'discord_user_id', None)
                     # name_i18n is a dict on model, char_name is for logging
                     char_name_i18n_dict = getattr(char_obj, 'name_i18n', {"en": getattr(char_obj, 'name', "Unknown")})
                     char_guild_id = getattr(char_obj, 'guild_id', None)

                     # Дополнительная проверка на критически важные атрибуты и совпадение guild_id
                     if char_id is None or discord_user_id is None or not char_name_i18n_dict or char_guild_id is None or str(char_guild_id) != guild_id_str:
                         print(f"CharacterManager: Warning: Skipping upsert for character with missing mandatory attributes or mismatched guild ({getattr(char_obj, 'id', 'N/A')}, guild {getattr(char_obj, 'guild_id', 'N/A')}). Expected guild {guild_id_str}.")
                         continue # Пропускаем этого персонажа

                     location_id = getattr(char_obj, 'location_id', None)
                     stats = getattr(char_obj, 'stats', {})
                     inventory = getattr(char_obj, 'inventory', [])
                     current_action = getattr(char_obj, 'current_action', None)
                     action_queue = getattr(char_obj, 'action_queue', [])
                     party_id = getattr(char_obj, 'party_id', None) # This is the old party_id field
                     state_variables = getattr(char_obj, 'state_variables', {})
                     hp = getattr(char_obj, 'hp', 100.0)
                     max_health = getattr(char_obj, 'max_health', 100.0)
                     is_alive = getattr(char_obj, 'is_alive', True) # Boolean
                     status_effects = getattr(char_obj, 'status_effects', [])
                     level = getattr(char_obj, 'level', 1)
                     experience = getattr(char_obj, 'experience', 0)
                     unspent_xp = getattr(char_obj, 'unspent_xp', 0)
                     collected_actions_json = getattr(char_obj, 'collected_actions_json', None) # Should be string or None

                     # New fields from Character model (Python types)
                     active_quests = getattr(char_obj, 'active_quests', [])
                     known_spells = getattr(char_obj, 'known_spells', [])
                     spell_cooldowns = getattr(char_obj, 'spell_cooldowns', {})
                     # Assuming model attributes are skills_data, abilities_data, spells_data, flags
                     skills_data = getattr(char_obj, 'skills_data', [])
                     abilities_data = getattr(char_obj, 'abilities_data', [])
                     spells_data = getattr(char_obj, 'spells_data', [])
                     flags = getattr(char_obj, 'flags', {})
                     character_class_val = getattr(char_obj, 'character_class', 'Adventurer')
                     selected_language = getattr(char_obj, 'selected_language', 'en')
                     current_game_status = getattr(char_obj, 'current_game_status', None)
                     current_party_id = getattr(char_obj, 'current_party_id', None)


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
                     # Ensure new list/dict types are correct
                     if not isinstance(active_quests, list): active_quests = []
                     if not isinstance(known_spells, list): known_spells = []
                     if not isinstance(spell_cooldowns, dict): spell_cooldowns = {}
                     if not isinstance(skills_data, (list,dict)): skills_data = [] # Or {} depending on expected structure
                     if not isinstance(abilities_data, (list,dict)): abilities_data = []
                     if not isinstance(spells_data, (list,dict)): spells_data = []
                     if not isinstance(flags, dict): flags = {}


                     data_to_upsert.append((
                         char_id,
                         discord_user_id,
                         json.dumps(char_name_i18n_dict), # Save name_i18n dict as JSON to 'name' column
                         guild_id_str,
                         location_id,
                         json.dumps(stats),
                         json.dumps(inventory),
                         json.dumps(current_action) if current_action is not None else None,
                         json.dumps(action_queue),
                         party_id,
                         json.dumps(state_variables),
                         hp,
                         max_health,
                         is_alive, # Boolean
                         json.dumps(status_effects),
                         level,
                         experience,
                         unspent_xp,
                         json.dumps(active_quests),
                         json.dumps(known_spells),
                         json.dumps(spell_cooldowns),
                         json.dumps(skills_data), # skills_data_json
                         json.dumps(abilities_data), # abilities_data_json
                         json.dumps(spells_data), # spells_data_json
                         json.dumps(flags), # flags_json
                         character_class_val,
                         selected_language,
                         current_game_status,
                         collected_actions_json, # Already JSON string or None
                         current_party_id
                     ))
                     upserted_char_ids.add(char_id) # Track IDs that were prepared for upsert

                 except Exception as e:
                     print(f"CharacterManager: Error preparing data for character {getattr(char_obj, 'id', 'N/A')} ({getattr(char_obj, 'name', 'N/A')}, guild {getattr(char_obj, 'guild_id', 'N/A')}) for upsert: {e}")
                     import traceback
                     print(traceback.format_exc())
                     # Этот персонаж не будет сохранен в этой итерации - он останется в _dirty_characters
                     # чтобы попробовать сохранить его снова

             if data_to_upsert:
                 try:
                     if self._db_service is None or self._db_service.adapter is None:
                          print(f"CharacterManager: Warning: DB service or adapter is None during upsert batch for guild {guild_id_str}.")
                     else:
                          # For PostgreSQL, execute_many with ON CONFLICT needs careful handling
                          # or individual execute calls in a loop if asyncpg's executemany doesn't directly support complex ON CONFLICT logic easily.
                          # However, a standard executemany with a VALUES list for INSERT INTO ... ON CONFLICT ... should work.
                          await self._db_service.adapter.execute_many(upsert_sql, data_to_upsert)
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
        if self._db_service is None or self._db_service.adapter is None:
            print(f"CharacterManager: Warning: Cannot load characters for guild {guild_id}, DB service or adapter missing.")
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
            # Ensure all new columns are selected.
            # 'name' column stores name_i18n. Other new columns: skills_data_json, abilities_data_json, spells_data_json, character_class, flags_json
            sql = '''
            SELECT id, discord_user_id, name, guild_id, location_id, stats, inventory,
                   current_action, action_queue, party_id, state_variables, hp, max_health,
                   is_alive, status_effects, race, mp, attack, defense, level, experience, unspent_xp,
                   collected_actions_json, selected_language, current_game_status, current_party_id,
                   skills_data_json, abilities_data_json, spells_data_json, character_class, flags_json,
                   active_quests, known_spells, spell_cooldowns -- Assuming these are also in Character.to_dict() / DB
            FROM players WHERE guild_id = $1
            ''' # Ensure this matches all fields saved by save_character / save_state
            rows = await self._db_service.adapter.fetchall(sql, (guild_id_str,)) # Changed to db_service
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
            data = {key: row[key] for key in row.keys()} # Correctly convert aiosqlite.Row to dict
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

                # --- Load and Parse JSON fields ---
                # Original name column now stores name_i18n
                data['name_i18n'] = json.loads(data.get('name') or '{}') if isinstance(data.get('name'), (str, bytes)) else {}
                # The plain 'name' field in data for Character.from_dict can be derived or set to a default lang from name_i18n
                default_lang_for_name = data.get('selected_language', 'en')
                data['name'] = data['name_i18n'].get(default_lang_for_name, list(data['name_i18n'].values())[0] if data['name_i18n'] else char_id)


                data['stats'] = json.loads(data.get('stats') or '{}') if isinstance(data.get('stats'), (str, bytes)) else {}
                data['inventory'] = json.loads(data.get('inventory') or '[]') if isinstance(data.get('inventory'), (str, bytes)) else []
                current_action_data = data.get('current_action')
                data['current_action'] = json.loads(current_action_data) if isinstance(current_action_data, (str, bytes)) else None
                data['action_queue'] = json.loads(data.get('action_queue') or '[]') if isinstance(data.get('action_queue'), (str, bytes)) else []
                data['state_variables'] = json.loads(data.get('state_variables') or '{}') if isinstance(data.get('state_variables'), (str, bytes)) else {}
                data['status_effects'] = json.loads(data.get('status_effects') or '[]') if isinstance(data.get('status_effects'), (str, bytes)) else []
                data['collected_actions_json'] = data.get('collected_actions_json') # Already string or None

                # New JSON fields (from DB columns ending in _json)
                data['skills_data'] = json.loads(data.get('skills_data_json') or '[]') if isinstance(data.get('skills_data_json'), (str, bytes)) else []
                data['abilities_data'] = json.loads(data.get('abilities_data_json') or '[]') if isinstance(data.get('abilities_data_json'), (str, bytes)) else []
                data['spells_data'] = json.loads(data.get('spells_data_json') or '[]') if isinstance(data.get('spells_data_json'), (str, bytes)) else []
                data['flags'] = json.loads(data.get('flags_json') or '{}') if isinstance(data.get('flags_json'), (str, bytes)) else {}
                # Remove the original _json keys if Character.from_dict expects non-suffixed names
                for k_json in ['skills_data_json', 'abilities_data_json', 'spells_data_json', 'flags_json']:
                    if k_json in data: del data[k_json]

                # Legacy JSON fields (if they were stored as JSON)
                data['active_quests'] = json.loads(data.get('active_quests') or '[]') if isinstance(data.get('active_quests'), (str, bytes)) else []
                data['known_spells'] = json.loads(data.get('known_spells') or '[]') if isinstance(data.get('known_spells'), (str, bytes)) else []
                data['spell_cooldowns'] = json.loads(data.get('spell_cooldowns') or '{}') if isinstance(data.get('spell_cooldowns'), (str, bytes)) else {}
                # 'skills' field was also a JSON dict in earlier versions, if it's still in DB, parse it.
                # However, skills_data_json is the new primary field. This needs clarification if 'skills' is still used.
                # For now, assume 'skills' is also JSON if present for backward compatibility or specific use.
                data['skills'] = json.loads(data.get('skills') or '{}') if isinstance(data.get('skills'), (str,bytes)) else {}


                # Convert is_alive from DB integer (0 or 1) to boolean
                is_alive_db = data.get('is_alive')
                data['is_alive'] = bool(is_alive_db) if is_alive_db is not None else True

                # Ensure health/max_health are numbers, default if missing or wrong type
                data['hp'] = float(data.get('hp', 100.0)) if isinstance(data.get('hp'), (int, float)) else 100.0
                data['max_health'] = float(data.get('max_health', 100.0)) if isinstance(data.get('max_health'), (int, float)) else 100.0

                # Direct fields
                data['character_class'] = data.get('character_class', 'Adventurer')

                # Update data dict with validated/converted values
                data['id'] = char_id
                data['discord_user_id'] = discord_user_id_int
                data['guild_id'] = loaded_guild_id
                # Ensure list fields are actually lists after potential JSON parsing issues
                for list_field in ['inventory', 'action_queue', 'status_effects', 'skills_data', 'abilities_data', 'spells_data', 'active_quests', 'known_spells']:
                    if not isinstance(data.get(list_field), list): data[list_field] = []
                # Ensure dict fields are actually dicts
                for dict_field in ['name_i18n', 'stats', 'state_variables', 'flags', 'spell_cooldowns', 'skills']:
                     if not isinstance(data.get(dict_field), dict): data[dict_field] = {}

                data['location_id'] = str(data['location_id']) if data.get('location_id') is not None else None
                data['party_id'] = str(data['party_id']) if data.get('party_id') is not None else None
                data['current_party_id'] = str(data.get('current_party_id')) if data.get('current_party_id') is not None else None


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
            if self._party_manager and hasattr(self._party_manager, 'clean_up_for_entity'): # Updated method name
                 await self._party_manager.clean_up_for_entity(character_id, entity_type="Character", context=cleanup_context)
            # CombatManager.clean_up_for_character должен уметь чистить по character_id и guild_id (через context)
            if self._combat_manager and hasattr(self._combat_manager, 'clean_up_for_entity'): # Updated method name
                 await self._combat_manager.clean_up_for_entity(character_id, entity_type="Character", context=cleanup_context)
            # DialogueManager.clean_up_for_character должен уметь чистить по character_id и guild_id (через context)
            if self._dialogue_manager and hasattr(self._dialogue_manager, 'clean_up_for_entity'): # Updated method name
                 await self._dialogue_manager.clean_up_for_entity(character_id, entity_type="Character", context=cleanup_context)

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
    async def update_character_location(self, character_id: str, location_id: Optional[str], guild_id: str, **kwargs: Any) -> Optional["Character"]:
        """Обновляет локацию персонажа для определенной гильдии и возвращает измененный объект Character или None."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем персонажа с учетом guild_id
        char = self.get_character(guild_id_str, character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to update location.")
            return None

        # Убедимся, что у объекта Character есть атрибут location_id перед изменением
        if not hasattr(char, 'location_id'):
             print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'location_id' attribute.")
             return None # Не удалось установить location_id, если атрибут отсутствует

        # Ensure location_id is str or None
        resolved_location_id = str(location_id) if location_id is not None else None

        old_location_id = getattr(char, 'location_id', None) # Get old location for logging/events

        if old_location_id == resolved_location_id:
             # print(f"CharacterManager: Character {character_id} already in location {resolved_location_id}. No update needed.") # Debug
             return char # Already there, return the character object

        char.location_id = resolved_location_id # Set the updated location ID

        self.mark_character_dirty(guild_id_str, character_id) # Помечаем измененным для этой гильдии
        print(f"CharacterManager: Updated location for character {character_id} in guild {guild_id_str} from {old_location_id} to {resolved_location_id}.")

        # TODO: Trigger arrival/departure events here or delegate
        # Example: if self._location_manager and hasattr(self._location_manager, 'handle_entity_departure'):
        # await self._location_manager.handle_entity_departure(char.id, "Character", old_location_id, context=kwargs)
        # if self._location_manager and hasattr(self._location_manager, 'handle_entity_arrival'):
        # await self._location_manager.handle_entity_arrival(char.id, "Character", new_location_id, context=kwargs)

        return char # Возвращаем измененный объект Character

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
         item_entry: Optional[Dict[str, Any]] = None # Initialize item_entry
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
         if not hasattr(char, 'hp') or not isinstance(char.hp, (int, float)):
              print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'hp' attribute or it's not a number ({type(getattr(char, 'hp', None))}). Cannot update health.")
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
         new_hp = char.hp + amount
         # Ограничиваем здоровье между 0 и max_health
         char.hp = max(0.0, min(char.max_health, new_hp)) # Use 0.0 and char.max_health as float

         self.mark_character_dirty(guild_id_str, character_id) # Помечаем измененным для этой гильдии

         # Проверяем смерть после обновления
         # Check against the updated health attribute
         if char.hp <= 0 and char.is_alive: # If health became <= 0 AND character is still marked as alive
              # handle_character_death expects character_id, guild_id and **kwargs
              await self.handle_character_death(guild_id_str, character_id, **kwargs) # Pass guild_id and context to handler

         print(f"CharacterManager: Updated health for character {character_id} in guild {guild_id_str} to {char.hp}. Amount: {amount}.")
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
             'guild_id': guild_id_str, # Передаем guild_id_str
             'character_id': character_id, # Передаем character_id
             'character': char, # Pass the character object for convenience
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
             if self._combat_manager and hasattr(self._combat_manager, 'clean_up_for_entity'): # Updated method name
                  # remove_participant_from_combat might need entity_type
                  await self._combat_manager.clean_up_for_entity(character_id, entity_type="Character", context=base_cleanup_kwargs) # Pass the context dict
             if self._party_manager and hasattr(self._party_manager, 'clean_up_for_entity'): # Updated method name
                  await self._party_manager.clean_up_for_entity(character_id, entity_type="Character", context=base_cleanup_kwargs) # Pass the context dict
             if self._dialogue_manager and hasattr(self._dialogue_manager, 'clean_up_for_entity'): # Updated method name
                  await self._dialogue_manager.clean_up_for_entity(character_id, entity_type="Character", context=base_cleanup_kwargs) # Pass the context dict

             # Drop items (if location_id is available on character)
             # Changed to use clean_up_for_character as it handles dropping inventory
             if self._item_manager and hasattr(self._item_manager, 'clean_up_for_character') and getattr(char, 'location_id', None) is not None:
                  await self._item_manager.clean_up_for_character(character_id, context=base_cleanup_kwargs) # Pass context dict

             # Trigger death logic in RuleEngine
             if self._rule_engine:
                 killer_entity = None
                 # Ensure context (base_cleanup_kwargs) has guild_id, it's already there
                 guild_id_for_fetch = base_cleanup_kwargs.get('guild_id', char.guild_id)
                 if not guild_id_for_fetch: # Should always be present
                     print(f"CharacterManager: CRITICAL - guild_id missing for death processing of {char.id}")

                 # killer_id and killer_type are passed in **kwargs which are part of base_cleanup_kwargs
                 killer_id_from_context = base_cleanup_kwargs.get('killer_id')
                 killer_type_from_context = base_cleanup_kwargs.get('killer_type')

                 if killer_id_from_context and killer_type_from_context and guild_id_for_fetch:
                     # Assuming self._character_manager_ref refers to self for CharacterManager
                     # This part might need adjustment if _character_manager_ref is not standard.
                     # For now, let's assume self can get character if needed.
                     # And CharacterManager needs _npc_manager to fetch NPC killers.
                     if killer_type_from_context == "Character":
                         # The context might already contain a CharacterManager instance (e.g. from GameManager)
                         cm_in_context = base_cleanup_kwargs.get('character_manager')
                         if cm_in_context and hasattr(cm_in_context, 'get_character'):
                             killer_entity = await cm_in_context.get_character(guild_id_for_fetch, killer_id_from_context)
                         else: # Fallback to self.get_character, as self is CharacterManager
                             killer_entity = await self.get_character(guild_id_for_fetch, killer_id_from_context)
                     elif killer_type_from_context == "NPC":
                         # Check if _npc_manager is available and has the method
                         npc_manager_in_context = base_cleanup_kwargs.get('npc_manager') # Prefer NPC manager from context
                         if npc_manager_in_context and hasattr(npc_manager_in_context, 'get_npc'):
                             killer_entity = await npc_manager_in_context.get_npc(guild_id_for_fetch, killer_id_from_context)
                         elif self._npc_manager and hasattr(self._npc_manager, 'get_npc'): # Fallback to self._npc_manager
                             killer_entity = await self._npc_manager.get_npc(guild_id_for_fetch, killer_id_from_context)
                         else:
                             print(f"CharacterManager: NPC killer type specified, but no NPC manager found to fetch NPC {killer_id_from_context}")

                 try:
                     death_report = await self._rule_engine.process_entity_death(
                         entity=char,
                         killer=killer_entity, # This can be None if killer not found
                         context=base_cleanup_kwargs # base_cleanup_kwargs already contains guild_id
                     )
                     death_message_from_engine = death_report.get('message', f"{getattr(char, 'name', char.id)} meets a grim end.")
                     print(f"CharacterManager: Death of {char.id} processed by RuleEngine. Message: {death_message_from_engine}")
                 except Exception as e:
                     print(f"CharacterManager: Error processing entity death for char {char.id} in guild {guild_id_str}: {e}")
                     import traceback
                     print(traceback.format_exc())
             else:
                 print(f"CharacterManager: RuleEngine not available for character {char.id} death processing. Basic death applied.")

            # These print statements are part of the general cleanup process after all specific cleanup actions.
            # Their indentation should align with the outer try block.
            print(f"CharacterManager: Death cleanup initiated for character {character_id} in guild {guild_id_str}.")
            print(f"CharacterManager: Death cleanup process completed for character {character_id} in guild {guild_id_str}.")
         except Exception as e: # This is the except for the outer try block
            print(f"CharacterManager: Error during death cleanup for character {character_id} in guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # Log error, continue


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
        if not char or not hasattr(char, 'action_queue') or not isinstance(char.action_queue, list) or not char.action_queue:
            return None

        next_action = char.action_queue.pop(0) # Removes from start of list (modifies attribute)
        self.mark_character_dirty(guild_id_str, character_id)

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

    async def save_character(self, character: "Character", guild_id: str) -> bool:
        """
        Saves a single character entity to the database using an UPSERT operation.
        Ensures all relevant fields of the Character model are saved.
        Handles serialization of complex types (e.g., to JSON strings).
        """
        if self._db_service is None or not hasattr(self._db_service, 'adapter') or self._db_service.adapter is None:
            print(f"CharacterManager: Error: DB service or adapter missing for guild {guild_id}. Cannot save character {character.id}.")
            # Consider raising an error or returning a more specific status
            return False

        guild_id_str = str(guild_id) # Ensure guild_id is a string

        # Validate that the character belongs to the specified guild
        if str(character.guild_id) != guild_id_str:
            print(f"CharacterManager: Error: Character {character.id} guild_id ({character.guild_id}) "
                  f"does not match provided guild_id ({guild_id_str}) for saving.")
            return False

        try:
            # Convert Character object to dictionary
            # The to_dict() method in Character model should be kept up-to-date
            # This method should return Python dicts/lists for complex fields.
            char_data = character.to_dict()

            # Prepare data for SQL query, ensuring JSON serialization for complex types
            # The order of parameters must match the order of columns in the SQL query.

            # name_i18n from model (dict) to JSON string for 'name' DB column
            name_i18n_json = json.dumps(char_data.get('name_i18n', {}))

            # New JSON fields from model (Python dict/list) to JSON strings for DB
            skills_data_json_str = json.dumps(char_data.get('skills_data', []))
            abilities_data_json_str = json.dumps(char_data.get('abilities_data', []))
            spells_data_json_str = json.dumps(char_data.get('spells_data', []))
            flags_json_str = json.dumps(char_data.get('flags', {}))

            db_params = (
                char_data.get('id'),
                char_data.get('discord_user_id'),
                name_i18n_json, # 'name' column in DB stores name_i18n
                char_data.get('guild_id'),
                char_data.get('location_id'),
                json.dumps(char_data.get('stats', {})),
                json.dumps(char_data.get('inventory', [])),
                json.dumps(char_data.get('current_action')) if char_data.get('current_action') is not None else None,
                json.dumps(char_data.get('action_queue', [])),
                char_data.get('party_id'), # Old party_id
                json.dumps(char_data.get('state_variables', {})),
                float(char_data.get('hp', 0.0)),
                float(char_data.get('max_health', 0.0)),
                char_data.get('is_alive', True), # Boolean directly
                json.dumps(char_data.get('status_effects', [])),
                int(char_data.get('level', 1)),
                int(char_data.get('experience', 0)),
                int(char_data.get('unspent_xp',0)),
                json.dumps(char_data.get('active_quests', [])), # Assuming these are from to_dict
                json.dumps(char_data.get('known_spells', [])),   # Assuming these are from to_dict
                json.dumps(char_data.get('spell_cooldowns', {})),# Assuming these are from to_dict
                skills_data_json_str,       # skills_data_json
                abilities_data_json_str,    # abilities_data_json
                spells_data_json_str,       # spells_data_json
                flags_json_str,             # flags_json
                char_data.get('character_class'),
                char_data.get('selected_language'),
                char_data.get('current_game_status'),
                char_data.get('collected_actions_json'),
                char_data.get('current_party_id') # New party_id
            )

            # SQL for UPSERT (PostgreSQL syntax)
            # Column names must match the 'players' table schema.
            upsert_sql = '''
            INSERT INTO players (
                id, discord_user_id, name, guild_id, location_id,
                stats, inventory, current_action, action_queue, party_id,
                state_variables, hp, max_health, is_alive, status_effects,
                level, experience, unspent_xp, active_quests, known_spells,
                spell_cooldowns, skills_data_json, abilities_data_json, spells_data_json, flags_json,
                character_class, selected_language, current_game_status, collected_actions_json, current_party_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30)
            ON CONFLICT (id) DO UPDATE SET
                discord_user_id = EXCLUDED.discord_user_id,
                name = EXCLUDED.name,
                guild_id = EXCLUDED.guild_id,
                location_id = EXCLUDED.location_id,
                stats = EXCLUDED.stats,
                inventory = EXCLUDED.inventory,
                current_action = EXCLUDED.current_action,
                action_queue = EXCLUDED.action_queue,
                party_id = EXCLUDED.party_id,
                state_variables = EXCLUDED.state_variables,
                hp = EXCLUDED.hp,
                max_health = EXCLUDED.max_health,
                is_alive = EXCLUDED.is_alive,
                status_effects = EXCLUDED.status_effects,
                level = EXCLUDED.level,
                experience = EXCLUDED.experience,
                unspent_xp = EXCLUDED.unspent_xp,
                active_quests = EXCLUDED.active_quests,
                known_spells = EXCLUDED.known_spells,
                spell_cooldowns = EXCLUDED.spell_cooldowns,
                skills_data_json = EXCLUDED.skills_data_json,
                abilities_data_json = EXCLUDED.abilities_data_json,
                spells_data_json = EXCLUDED.spells_data_json,
                flags_json = EXCLUDED.flags_json,
                character_class = EXCLUDED.character_class,
                selected_language = EXCLUDED.selected_language,
                current_game_status = EXCLUDED.current_game_status,
                collected_actions_json = EXCLUDED.collected_actions_json,
                current_party_id = EXCLUDED.current_party_id;
            ''' # 30 columns, 30 placeholders. PostgreSQL UPSERT.

            # Execute the database operation
            await self._db_service.adapter.execute(upsert_sql, db_params)
            # print(f"CharacterManager: Successfully saved character {character.id} for guild {guild_id_str}.") # Debug log

            # If the character was saved, remove it from the dirty set for this guild
            # This is crucial to avoid re-saving unchanged data
            guild_dirty_set = self._dirty_characters.get(guild_id_str)
            if guild_dirty_set:
                guild_dirty_set.discard(character.id)
                if not guild_dirty_set: # If the set becomes empty
                    del self._dirty_characters[guild_id_str]

            return True

        except json.JSONDecodeError as je:
            print(f"CharacterManager: JSON encoding error saving character {character.id} for guild {guild_id_str}: {je}")
            traceback.print_exc()
            return False
        except AttributeError as ae: # Catch issues if char_data is missing expected keys from to_dict
            print(f"CharacterManager: Attribute error preparing data for character {character.id} (guild {guild_id_str}): {ae}. "
                  "This might indicate Character.to_dict() is missing fields or data is malformed.")
            traceback.print_exc()
            return False
        except Exception as e:
            # Log any other errors during the save process
            print(f"CharacterManager: Error saving character {character.id} for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return False

    async def set_current_party_id(self, guild_id: str, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        """Sets the current_party_id for a character for a specific guild."""
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to set current_party_id.")
            return False

        if not hasattr(char, 'current_party_id'):
            print(f"CharacterManager: Warning: Character model for {character_id} in guild {guild_id_str} is missing 'current_party_id' attribute.")
            # Attempt to set it anyway if the model should have it
            # but log that it might be a model definition issue.
            # Or, return False if strict adherence to current model attributes is required.
            # For now, let's assume the attribute should exist or will be dynamically set.
            pass # Allow setting it

        resolved_party_id = str(party_id) if party_id is not None else None

        if getattr(char, 'current_party_id', None) == resolved_party_id:
            return True # No change needed

        char.current_party_id = resolved_party_id
        self.mark_character_dirty(guild_id_str, character_id)
        print(f"CharacterManager: Set current_party_id for character {character_id} in guild {guild_id_str} to {resolved_party_id}.")
        return True

    async def save_character_field(self, guild_id: str, character_id: str, field_name: str, value: Any, **kwargs: Any) -> bool:
        """
        Updates a specific field for a character and saves it to the database.
        This is a convenience method that marks the character dirty and relies on the main save loop,
        OR directly calls DBService if immediate persistence is needed (for now, mark dirty).
        """
        guild_id_str = str(guild_id)
        char = self.get_character(guild_id_str, character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found in guild {guild_id_str} to save field '{field_name}'.")
            return False

        if not hasattr(char, field_name):
            print(f"CharacterManager: Character {character_id} has no field '{field_name}'.")
            return False

        setattr(char, field_name, value)
        self.mark_character_dirty(guild_id_str, character_id)

        # If immediate save is required (e.g., for critical fields not picked up by regular save cycle):
        # if self._db_service:
        #     success = await self._db_service.update_player_field(
        #         player_id=character_id, # Assuming character_id is the player_id in DB
        #         field_name=field_name,
        #         value=value,
        #         guild_id=guild_id_str
        #     )
        #     if success:
        #         print(f"CharacterManager: Immediately saved field '{field_name}' for character {character_id} in guild {guild_id_str}.")
        #         # Optionally, if DB save is direct, you might not need to mark_dirty
        #         # or _dirty_characters set should be cleared for this field/char by DBService.
        #         # For now, relying on mark_character_dirty and main save cycle.
        #         return True
        #     else:
        #         print(f"CharacterManager: Failed to immediately save field '{field_name}' for character {character_id} in guild {guild_id_str}.")
        #         return False
        # else:
        #     print(f"CharacterManager: DBService not available, cannot immediately save field '{field_name}'. Marked dirty.")
        #     return True # Marked dirty, will save later

        print(f"CharacterManager: Updated field '{field_name}' for character {character_id} in guild {guild_id_str}. Marked dirty for next save cycle.")
        return True

# --- Конец класса CharacterManager ---
