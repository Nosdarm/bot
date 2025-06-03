# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING # Import TYPE_CHECKING


# TYPE_CHECKING импорты для избежания циклических зависимостей.
# Менеджеры, которые передаются в __init__ CharacterManager,
# должны быть импортированы здесь только для Type Hinting.
if TYPE_CHECKING:
    from bot.database.sqlite_adapter import SqliteAdapter # Add SqliteAdapter here too if you use string literal for it
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.rules.rule_engine import RuleEngine

# Прямой импорт для SqliteAdapter, если он используется в isinstance или не только в аннотациях
# Если SqliteAdapter используется только для аннотаций в __init__ и не импортируется в TYPE_CHECKING,
# тогда аннотация в __init__ должна быть строковым литералом "SqliteAdapter".
# Судя по вашему коду, вы используете self._db_adapter (хранится инстанс), а не класс SqliteAdapter напрямую,
# поэтому безопаснее использовать строковый литерал и в TYPE_CHECKING.
# Если вы *всегда* ожидаете инстанс, то прямой импорт + isinstance OK.
# Давайте оставим прямой импорт, если вы уверены, что он всегда доступен,
# но используем строковый литерал в __init__ для Type Checking robustness.
# Проверим, нужен ли прямой импорт для isinstance проверок. В вашем коде их нет для db_adapter.
# Поэтому переносим SqliteAdapter только в TYPE_CHECKING и используем строковый литерал в __init__.

# from bot.database.sqlite_adapter import SqliteAdapter # Удаляем прямой импорт


class CharacterManager:
    """
    Менеджер для управления персонажами игроков.
    Отвечает за создание, получение, обновление персонажей, их персистентность
    и хранение их основного состояния и кешей.
    """
    def __init__(
        self,
        # Используем строковые литералы для всех опциональных менеджеров/адаптеров,
        # особенно если они импортируются условно или только в TYPE_CHECKING
        db_adapter: Optional["SqliteAdapter"] = None, # Use string literal!
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None, # Use string literal!
        location_manager: Optional["LocationManager"] = None, # Use string literal!
        rule_engine: Optional["RuleEngine"] = None, # Use string literal!
        status_manager: Optional["StatusManager"] = None, # Use string literal!
        party_manager: Optional["PartyManager"] = None, # Use string literal!
        combat_manager: Optional["CombatManager"] = None, # Use string literal!
        dialogue_manager: Optional["DialogueManager"] = None, # Use string literal!
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
        self._characters: Dict[str, Character] = {} # Character Model is directly imported, no string literal needed here
        self._discord_to_char_map: Dict[int, str] = {}
        self._entities_with_active_action: Set[str] = set() # Персонажи/NPC с активным действием
        self._dirty_characters: Set[str] = set() # ID персонажей, которые нужно сохранить
        self._deleted_characters_ids: Set[str] = set() # ID персонажей, которые нужно удалить

        print("CharacterManager initialized.")

    # --- Методы получения персонажей ---
    def get_character(self, character_id: str) -> Optional[Character]:
        """Получить персонажа по его внутреннему ID (UUID)."""
        return self._characters.get(character_id)

    def get_character_by_discord_id(self, discord_user_id: int) -> Optional[Character]:
        """Получить персонажа по Discord User ID."""
        char_id = self._discord_to_char_map.get(discord_user_id)
        # if char_id is None: return None # This check is redundant with .get() default None
        return self._characters.get(char_id) # Returns None if char_id is None or not in _characters

    def get_character_by_name(self, name: str) -> Optional[Character]:
         """Получить персонажа по имени (может быть медленно для большого количества персонажей)."""
         # Реализация: пройтись по self._characters.values()
         for char in self._characters.values():
             if char.name == name:
                 return char
         return None

    def get_all_characters(self) -> List[Character]:
        """Получить список всех загруженных персонажей."""
        return list(self._characters.values())

    def get_entities_with_active_action(self) -> Set[str]:
        """Получить ID сущностей (включая персонажей) с активным действием."""
        return set(self._entities_with_active_action)

    def is_busy(self, character_id: str) -> bool:
        """Проверяет, занят ли персонаж (выполняет действие или состоит в занятой группе)."""
        char = self.get_character(character_id)
        if not char:
            return False
        # Проверка на текущее действие персонажа
        if char.current_action is not None or char.action_queue:
            return True
        # Проверка, занята ли его группа (используем инжектированный party_manager, если он есть)
        if char.party_id and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
            return self._party_manager.is_party_busy(char.party_id) # Предполагаем синхронный метод
        # Если party_manager нет или нет метода, считаем, что группа не может быть занята через него
        return False


    # --- Методы создания ---

    async def create_character( # Переименован из create_character_for_user
        self,
        discord_id: int, # Имя параметра discord_id
        name: str,
        initial_location_id: Optional[str] = None,
        # Добавьте другие начальные параметры, которые могут быть переданы при создании
        # Добавляем **kwargs, так как PersistenceManager может передавать контекст
        **kwargs: Any
    ) -> Optional[Character]: # Возвращаем Optional[Character], так как создание может не удасться
        """
        Создает нового персонажа в базе данных, кеширует его и возвращает объект Character.
        Использует UUID для ID.
        Возвращает Character объект при успехе, None при неудаче (например, персонаж уже существует).
        """
        if self._db_adapter is None:
            print("CharacterManager: Error: DB adapter missing.")
            raise ConnectionError("Database adapter is not initialized.")

        # Проверка на существование персонажа для этого discord_id
        if self.get_character_by_discord_id(discord_id): # Используем параметр discord_id
             print(f"CharacterManager: Character already exists for discord ID {discord_id}") # Используем параметр discord_id
             return None # Возвращаем None, если персонаж уже есть

        # Проверка на уникальность имени персонажа (если нужно)
        if self.get_character_by_name(name):
             print(f"CharacterManager: Character with name '{name}' already exists.")
             return None # Возвращаем None, если имя уже занято

        # Генерируем уникальный ID (UUID)
        new_id = str(uuid.uuid4())

        # Определяем начальную локацию (используем инжектированный location_manager, если он есть)
        resolved_initial_location_id = initial_location_id
        if resolved_initial_location_id is None and self._location_manager and hasattr(self._location_manager, 'get_default_location_id'):
             try:
                 # Предполагаем, что get_default_location_id не требует аргументов
                 resolved_initial_location_id = self._location_manager.get_default_location_id() # Предполагаем синхронный метод
                 if resolved_initial_location_id:
                      print(f"CharacterManager: Using default location ID: {resolved_initial_location_id}")
             except Exception as e:
                 print(f"CharacterManager: Warning: Could not get default location ID: {e}")
                 traceback.print_exc()


        # Определяем начальные статы (можно использовать RuleEngine, если он передан)
        stats = {'strength': 10, 'dexterity': 10, 'intelligence': 10} # Default stats
        if self._rule_engine and hasattr(self._rule_engine, 'generate_initial_character_stats'):
            try:
                # Убедитесь, что generate_initial_character_stats существует и работает как ожидается
                # Если он асинхронный: await self._rule_engine.generate_initial_character_stats()
                # Предполагаем, что метод не требует аргументов
                generated_stats = self._rule_engine.generate_initial_character_stats() # Предполагаем синхронный вызов по умолчанию
                if isinstance(generated_stats, dict):
                     stats = generated_stats
            except Exception:
                # Логируем исключение, если генерация статов не удалась, но продолжаем с дефолтными
                print("CharacterManager: Error generating initial character stats:")
                traceback.print_exc()


        # Подготавливаем данные для вставки в DB и создания модели
        # Используем data для консистентности и удобства
        data: Dict[str, Any] = { # Явная аннотация Dict
            'id': new_id, # Вставляем сгенерированный ID (UUID)
            'discord_user_id': discord_id, # Используем параметр discord_id
            'name': name,
            'location_id': resolved_initial_location_id, # Может быть None
            'stats': stats, # dict
            'inventory': [], # list
            'current_action': None, # null
            'action_queue': [], # list
            'party_id': None, # null
            'state_variables': {}, # dict
            'health': 100.0,
            'max_health': 100.0,
            'is_alive': True, # bool
            'status_effects': [], # list
            # ... другие поля из модели Character, если есть ...
        }

        # Преобразуем в JSON для сохранения в DB
        # Убедитесь, что имена колонок и порядок соответствуют вашей схеме SQLite
        sql = """
        INSERT INTO characters (
            id, discord_user_id, name, location_id, stats, inventory,
            current_action, action_queue, party_id, state_variables,
            health, max_health, is_alive, status_effects
            -- , ... другие колонки, если есть ...
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        db_params = (
            data['id'], # UUID как TEXT
            data['discord_user_id'], # Значение из data
            data['name'],
            data['location_id'],
            json.dumps(data['stats']),
            json.dumps(data['inventory']),
            json.dumps(data['current_action']) if data['current_action'] is not None else None,
            json.dumps(data['action_queue']),
            data['party_id'], # party_id может быть None
            json.dumps(data['state_variables']),
            data['health'],
            data['max_health'],
            int(data['is_alive']), # boolean как integer 0 or 1
            json.dumps(data['status_effects']),
            # ... другие параметры для INSERT в том же порядке, что и колонки в SQL ...
        )

        try:
            # Выполняем INSERT. Используем execute для вставки с заданным ID (UUID).
            await self._db_adapter.execute(sql, db_params)
            print(f"CharacterManager: Character '{name}' with ID {new_id} inserted into DB.")

            # Создаем объект модели Character из данных (данные уже в формате Python объектов)
            char = Character.from_dict(data) # Character.from_dict должен уметь принимать эти данные

            # Добавляем персонажа в кеши
            self._characters[char.id] = char
            if char.discord_user_id is not None:
                 # Убеждаемся, что discord_user_id является хэшируемым типом (int)
                 self._discord_to_char_map[char.discord_user_id] = char.id

            # Отмечаем как грязный, чтобы он был сохранен при следующем save (хотя только что вставили)
            # Это полезно, если save_state вызывается сразу после create.
            # self._dirty_characters.add(char.id) # Можно опционально убрать, если уверены, что save_state вызывается позже

            print(f"CharacterManager: Character '{name}' (ID: {char.id}) created and cached.")
            return char # Возвращаем созданный объект Character

        except Exception as e:
            print(f"CharacterManager: Error creating character '{name}' for discord ID {discord_id}: {e}") # <-- ИСПРАВЛЕНИЕ: Используем discord_id
            traceback.print_exc()
            # Не перебрасываем исключение raise, если хотим, чтобы другие персонажи создались,
            # но GameManager должен проверить результат (возвращает None)
            # Если хотите, чтобы GameManager знал об ошибке создания именно этого персонажа, оставьте raise.
            # Пока оставлю raise, как было в оригинале.
            raise


    # --- Методы сохранения/загрузки (для PersistenceManager) ---
    # Добавляем required_args для совместимости с PersistenceManager
    required_args_for_load = ["guild_id"] # Предполагаем, что load_all_characters будет фильтровать по guild_id
    required_args_for_save = ["guild_id"] # Предполагаем, что save_all_characters будет фильтровать по guild_id

    async def save_state(self, guild_id: str, **kwargs) -> None: # Переименован из save_all_characters и добавил guild_id и kwargs
        """Сохраняет все измененные или удаленные персонажи для определенного guild_id."""
        if self._db_adapter is None:
            print(f"CharacterManager: Warning: Cannot save characters for guild {guild_id}, DB adapter missing.")
            return
        # Фильтруем dirty/deleted по guild_id, если это необходимо для многогильдийности
        # Если персонажи хранятся глобально или guild_id уже в объекте Character:
        # Наша модель Character включает guild_id, но мы не фильтруем кеши по нему.
        # При многогильдийности _characters, _discord_to_char_map и _dirty_characters
        # должны быть словарями словарей: {guild_id: {char_id: char}}.
        # Сейчас они хранят все персонажи вместе.
        # Если это одногильдийный бот или guild_id нужен только для SQL запроса,
        # то текущая структура кеша может быть OK, но SQL должен фильтровать.
        # Предположим, guild_id нужен для SQL запросов.

        dirty_char_ids_for_guild = {cid for cid in self._dirty_characters if cid in self._characters and self._characters[cid].guild_id == guild_id}
        deleted_char_ids_for_guild = {cid for cid in self._deleted_characters_ids if self.get_character(cid) is None} # Проверяем, что его нет в кеше (уже удален из _characters)

        if not dirty_char_ids_for_guild and not deleted_char_ids_for_guild:
            # print(f"CharacterManager: No dirty or deleted characters to save for guild {guild_id}.") # Можно закомментировать
            return

        print(f"CharacterManager: Saving {len(dirty_char_ids_for_guild)} dirty, {len(deleted_char_ids_for_guild)} deleted characters for guild {guild_id}...")

        # Удалить помеченные для удаления персонажи для этого guild_id
        if deleted_char_ids_for_guild:
            ids_to_delete = list(deleted_char_ids_for_guild)
            placeholders = ','.join(['?'] * len(ids_to_delete))
            # Убеждаемся, что удаляем ТОЛЬКО для данного guild_id
            delete_sql = f"DELETE FROM characters WHERE guild_id = ? AND id IN ({placeholders})"
            try:
                await self._db_adapter.execute(delete_sql, (guild_id, *tuple(ids_to_delete)))
                print(f"CharacterManager: Deleted {len(ids_to_delete)} characters from DB for guild {guild_id}.")
                # Очищаем список после успешного удаления
                # Внимание: очищаем только те, которые были в deleted_char_ids_for_guild!
                self._deleted_characters_ids.difference_update(deleted_char_ids_for_guild)
            except Exception as e:
                print(f"CharacterManager: Error deleting characters for guild {guild_id}: {e}")
                traceback.print_exc()
                # Не очищаем _deleted_characters_ids, чтобы попробовать удалить снова при следующей сохранке

        # Обновить или вставить измененные персонажи для этого guild_id
        characters_to_save = [self._characters[cid] for cid in list(dirty_char_ids_for_guild) if cid in self._characters] # Убеждаемся, что они еще в кеше
        if characters_to_save:
             print(f"CharacterManager: Upserting {len(characters_to_save)} characters for guild {guild_id}...")
             # INSERT OR REPLACE SQL для обновления существующих или вставки новых
             upsert_sql = '''
             INSERT OR REPLACE INTO characters
             (id, discord_user_id, name, guild_id, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             '''
             # Формируем список кортежей для execute_many
             data_to_upsert = []
             for char in characters_to_save:
                 try:
                     stats_json = json.dumps(char.stats)
                     inv_json = json.dumps(char.inventory)
                     curr_json = json.dumps(char.current_action) if char.current_action is not None else None
                     queue_json = json.dumps(char.action_queue)
                     state_json = json.dumps(char.state_variables)
                     status_json = json.dumps(char.status_effects)
                     data_to_upsert.append((
                         char.id,
                         char.discord_user_id,
                         char.name,
                         char.guild_id, # Добавляем guild_id
                         char.location_id,
                         stats_json,
                         inv_json,
                         curr_json,
                         queue_json,
                         char.party_id,
                         state_json,
                         char.health,
                         char.max_health,
                         int(char.is_alive),
                         status_json,
                     ))
                 except Exception as e:
                     print(f"CharacterManager: Error preparing data for character {char.id} ({char.name}) for upsert: {e}")
                     traceback.print_exc()
                     # Этот персонаж не будет сохранен в этой итерации - он останется в _dirty_characters
                     # чтобы попробовать сохранить его снова

             if data_to_upsert:
                 try:
                     # Используем execute_many для пакетной вставки/обновления
                     await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                     print(f"CharacterManager: Successfully upserted {len(data_to_upsert)} characters for guild {guild_id}.")
                     # Только если execute_many успешен, очищаем список "грязных"
                     # Внимание: очищаем только те, которые были в dirty_char_ids_for_guild!
                     self._dirty_characters.difference_update(dirty_char_ids_for_guild)
                 except Exception as e:
                     print(f"CharacterManager: Error during batch upsert for guild {guild_id}: {e}")
                     traceback.print_exc()
                     # Не очищаем _dirty_characters, чтобы попробовать сохранить снова

        print(f"CharacterManager: Save state complete for guild {guild_id}.")


    async def load_state(self, guild_id: str, **kwargs) -> None: # Переименован из load_all_characters и добавил guild_id и kwargs
        """Загружает все персонажи для определенного guild_id из базы данных в кеш."""
        if self._db_adapter is None:
            print(f"CharacterManager: Warning: Cannot load characters for guild {guild_id}, DB adapter missing.")
            return

        print(f"CharacterManager: Loading characters for guild {guild_id} from DB...")
        # При многогильдийности, мы не хотим очищать ВЕСЬ кеш, только персонажей для ЭТОГО guild_id.
        # Это требует, чтобы кеш _characters был структурирован по guild_id.
        # Например: _characters = {guild_id: {char_id: Character}}
        # _discord_to_char_map = {guild_id: {discord_id: char_id}}
        # _dirty_characters = {guild_id: Set[str]}
        # _deleted_characters_ids = {guild_id: Set[str]}

        # Текущая структура кеша _characters {char_id: Character} не поддерживает эффективное удаление по guild_id
        # без перебора всего кеша.
        # Если бот одногильдийный, текущий load_all_characters OK (он загружает все).
        # Если многогильдийный, и мы загружаем ОДНУ гильдию, но кеш общий,
        # то load_state для одной гильдии не должен очищать кеш для других гильдий.
        # В текущей реализации, load_state для guild_id фактически загрузит *всех* персонажей
        # из DB, а не только для этого guild_id, если нет WHERE clause в SQL.

        # Давайте предположим многогильдийность и адаптируем SQL.
        # НО! Очистка кеша - проблема для многогильдийности.
        # Если мы при load_state(guild_id='A') очистим _characters, то персонажи гильдии B пропадут из кеша.
        # Возможно, PersistenceManager должен гарантировать, что load_state вызывается только один раз при старте для ВСЕХ гильдий?
        # Или load_state должен загружать только персонажей для данного guild_id ИЛИ *добавлять* их в кеш, не очищая существующие?
        # Последнее опасно, т.к. не удалит из кеша персонажей, удаленных из DB для этой гильдии.
        # Самый безопасный вариант для многогильдийности: PersistenceManager при старте загружает ВСЕХ персонажей один раз.
        # Или CharacterManager кеширует по guild_id.

        # Оставим текущую реализацию load_state с полной очисткой кеша,
        # предполагая, что она вызывается один раз для загрузки всех персонажей
        # ИЛИ что PersistenceManager вызывает ее для каждой гильдии по очереди, но кеш общий
        # (что требует фильтрации в SQL). Добавим фильтрацию в SQL.

        self._characters.clear()
        self._discord_to_char_map.clear()
        self._entities_with_active_action.clear()
        self._dirty_characters.clear() # Очищаем, так как все из DB считается чистым
        self._deleted_characters_ids.clear() # Очищаем

        rows = [] # Инициализируем список для строк
        try:
            # ВЫПОЛНЯЕМ fetchall С ФИЛЬТРОМ по guild_id
            sql = '''
            SELECT id, discord_user_id, name, guild_id, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects
            FROM characters WHERE guild_id = ?
            '''
            rows = await self._db_adapter.fetchall(sql, (guild_id,)) # Передаем guild_id для фильтрации
            print(f"CharacterManager: Found {len(rows)} characters in DB for guild {guild_id}.")

        except Exception as e:
            # Если произошла ошибка при самом выполнении запроса fetchall
            print(f"CharacterManager: ❌ CRITICAL ERROR executing DB fetchall for guild {guild_id}: {e}")
            traceback.print_exc()
            # В этом случае rows будет пустым списком, и мы просто выйдем из метода после обработки ошибки.
            # Очистка кешей уже была сделана выше.
            # Возможно, нужно перебрасывать исключение, чтобы GameManager знал, что загрузка не удалась?
            # Если load_state вызывается для каждой гильдии, перебрасывание исключения остановит загрузку всех гильдий.
            # Лучше просто логировать и не загружать персонажей для этой гильдии.
            return # Прерываем выполнение метода при критической ошибке запроса

        # Теперь обрабатываем каждую строку ВНУТРИ ЦИКЛА
        loaded_count = 0
        for row in rows:
            # Убеждаемся, что row - это dict-подобный объект
            data = dict(row)
            try:
                # Преобразуем JSON строки и Integer (для is_alive) обратно в Python объекты
                data['stats'] = json.loads(data.get('stats') or '{}')
                data['inventory'] = json.loads(data.get('inventory') or '[]')
                # get('current_action') может вернуть None если колонка NULL, json.loads(None) вызовет ошибку.
                current_action_data = data.get('current_action')
                data['current_action'] = json.loads(current_action_data) if current_action_data is not None else None

                data['action_queue'] = json.loads(data.get('action_queue') or '[]')
                data['state_variables'] = json.loads(data.get('state_variables') or '{}')
                data['is_alive'] = bool(data.get('is_alive', 0)) # 0 или 1 в DB -> False или True
                data['status_effects'] = json.loads(data.get('status_effects') or '[]')

                # Проверяем и преобразуем ID в строку, если нужно (предполагаем, что в DB это TEXT/UUID)
                char_id = data.get('id')
                if not isinstance(char_id, str):
                     # print(f"CharacterManager: Warning: Loaded character ID {char_id} is not a string. Converting.")
                     data['id'] = str(char_id) # Убеждаемся, что ID в данных для модели - строка

                # Проверяем, что guild_id в данных соответствует тому, который мы загружали
                # (Не обязательно, если SQL фильтрует, но хорошая доп. проверка)
                loaded_guild_id = data.get('guild_id')
                if str(loaded_guild_id) != str(guild_id):
                     print(f"CharacterManager: Warning: Mismatch guild_id for character {char_id}: Expected {guild_id}, got {loaded_guild_id}. Skipping.")
                     continue # Пропускаем строку, если guild_id не совпадает

                # Создаем объект модели Character
                char = Character.from_dict(data) # Character.from_dict должен уметь принимать эти данные

                # Добавляем в кеш по ID
                self._characters[char.id] = char

                # Добавляем в кеш по Discord ID, только если discord_user_id есть и валидный
                discord_user_id = char.discord_user_id
                if discord_user_id is not None:
                    # Убеждаемся, что discord_user_id является хэшируемым типом (int)
                    if isinstance(discord_user_id, int) or isinstance(discord_user_id, str) and discord_user_id.isdigit(): # Discord IDs can be int or string
                        self._discord_to_char_map[int(discord_user_id)] = char.id # Key is int, value is char_id string
                    else:
                         print(f"CharacterManager: Warning: Invalid discord_user_id for character {char.id}: {discord_user_id}. Cannot map.")


                # Если у персонажа есть активное действие или очередь, помечаем его как занятого
                if char.current_action is not None or char.action_queue:
                    self._entities_with_active_action.add(char.id)

                loaded_count += 1 # Увеличиваем счетчик успешно загруженных

            except json.JSONDecodeError:
                # Ошибка парсинга JSON в ОДНОЙ строке
                print(f"CharacterManager: Error decoding JSON for character row (ID: {data.get('id', 'N/A')}, guild: {data.get('guild_id', 'N/A')}): {traceback.format_exc()}. Skipping this row.")
                # traceback.print_exc() # Печатаем подробный traceback для ошибки JSON
                # Продолжаем цикл для других строк
            except Exception as e:
                # Другая ошибка при обработке ОДНОЙ строки
                print(f"CharacterManager: Error processing character row (ID: {data.get('id', 'N/A')}, guild: {data.get('guild_id', 'N/A')}): {e}. Skipping this row.")
                traceback.print_exc()
                # Продолжаем цикл для других строк

        print(f"CharacterManager: Successfully loaded {loaded_count} characters into cache for guild {guild_id}.")
        if loaded_count < len(rows):
             print(f"CharacterManager: Note: Failed to load {len(rows) - loaded_count} characters for guild {guild_id} due to errors.")

    # Добавляем метод rebuild_runtime_caches для совместимости с PersistenceManager
    def rebuild_runtime_caches(self, guild_id: str, **kwargs) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния."""
        guild_id_str = str(guild_id)
        print(f"CharacterManager: Rebuilding runtime caches for guild {guild_id_str}. (Placeholder)")
        # Если у вас есть кеши, которые нужно построить на основе загруженных персонажей
        # или связей с другими менеджерами (полученными из kwargs), это место для их перестройки.
        # Например, кеш персонажей в локациях, кеш персонажей в группах и т.д.
        # В текущей структуре, _characters и _discord_to_char_map уже построены при загрузке.
        # _entities_with_active_action тоже построен.
        # Возможно, party_manager должен здесь перестроить свои кеши, используя персонажей из этого менеджера.
        # Это может потребовать передачи self в другие менеджеры через kwargs.
        # e.g., party_mgr = kwargs.get('party_manager')
        # if party_mgr and hasattr(party_mgr, 'rebuild_cache_from_characters'):
        #     all_chars_in_guild = [char for char in self._characters.values() if str(char.guild_id) == guild_id_str]
        #     party_mgr.rebuild_cache_from_characters(all_chars_in_guild) # Пример сигнатуры


    def mark_character_dirty(self, character_id: str) -> None:
         """Помечает персонажа как измененного для последующего сохранения."""
         # Добавляем проверку, что ID существует в кеше
         if character_id in self._characters:
              self._dirty_characters.add(character_id)
         else:
             print(f"CharacterManager: Warning: Attempted to mark non-existent character {character_id} as dirty.")


    def mark_character_deleted(self, character_id: str) -> None:
        """Помечает персонажа как удаленного."""
        # Проверяем, существует ли персонаж в кеше, прежде чем удалять
        char = self._characters.get(character_id)
        if char:
             # Удаляем из кеша сразу
             del self._characters[character_id]
             # Удаляем из мапы discord_id -> char_id, если там есть запись об этом персонаже
             if char.discord_user_id is not None:
                 # Ищем discord_id по char_id в мапе и удаляем, если найдено
                 # Это менее эффективно, чем прямая мапа discord_id -> char_id
                 # Лучше сохранить discord_user_id перед удалением char
                 discord_id_to_remove = char.discord_user_id
                 # Проверяем, что мапа указывает именно на этого персонажа
                 if self._discord_to_char_map.get(discord_id_to_remove) == character_id:
                     del self._discord_to_char_map[discord_id_to_remove]

             self._entities_with_active_action.discard(character_id) # Удаляем из списка занятых, если был там
             self._dirty_characters.discard(character_id) # Если был грязный, то теперь удален
             self._deleted_characters_ids.add(character_id) # Помечаем для удаления из DB
             print(f"CharacterManager: Character {character_id} marked for deletion.")
        elif character_id in self._deleted_characters_ids:
             print(f"CharacterManager: Character {character_id} already marked for deletion.")
        else:
             print(f"CharacterManager: Warning: Attempted to mark non-existent character {character_id} as deleted.")


    # --- Метод удаления (публичный) ---
    # Добавляем guild_id и **kwargs, так как PersistenceManager может их передавать
    async def remove_character(self, character_id: str, guild_id: str, **kwargs: Any) -> Optional[str]:
        """
        Удаляет персонажа (помечает для удаления из DB) и выполняет очистку
        связанных сущностей (предметы, статусы, группа, бой, диалог).
        Принимает guild_id для контекста, но использует character_id для поиска.
        """
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found for removal in guild {guild_id}.")
            return None

        # Дополнительная проверка guild_id, если менеджер кеширует все гильдии
        if str(char.guild_id) != str(guild_id):
             print(f"CharacterManager: Character {character_id} belongs to guild {char.guild_id}, not {guild_id}. Removal cancelled.")
             return None


        print(f"CharacterManager: Removing character {character_id} ({char.name}) from guild {guild_id}...")

        # Cleanup via managers (используем менеджеры, переданные в __init__)
        # Передаем context, включая guild_id и character_id
        cleanup_context = {
            'guild_id': guild_id,
            'character_id': character_id,
            'character': char, # Pass the character object for convenience
            # Передаем другие менеджеры, которые могут понадобиться в cleanup методах
            'item_manager': self._item_manager,
            'status_manager': self._status_manager,
            'party_manager': self._party_manager,
            'combat_manager': self._combat_manager,
            'dialogue_manager': self._dialogue_manager,
            # Включаем другие менеджеры из __init__ если они нужны в cleanup методах
            'location_manager': self._location_manager,
            'rule_engine': self._rule_engine,
            # Прочие из kwargs, если передаются в remove_character
            **kwargs
        }

        try:
            # Убедитесь, что методы clean_up_* существуют в соответствующих менеджерах
            # и что они принимают character_id и context (**kwargs или явно).
            # Предполагаем, что они принимают context.
            if self._item_manager and hasattr(self._item_manager, 'clean_up_for_character'):
                await self._item_manager.clean_up_for_character(character_id, context=cleanup_context)
            if self._status_manager and hasattr(self._status_manager, 'clean_up_for_character'):
                 await self._status_manager.clean_up_for_character(character_id, context=cleanup_context)
            if self._party_manager and hasattr(self._party_manager, 'clean_up_for_character'): # Проверка party_id не нужна здесь, clean_up_for_character должна справиться
                 await self._party_manager.clean_up_for_character(character_id, context=cleanup_context)
            if self._combat_manager and hasattr(self._combat_manager, 'clean_up_for_character'):
                 await self._combat_manager.clean_up_for_character(character_id, context=cleanup_context)
            if self._dialogue_manager and hasattr(self._dialogue_manager, 'clean_up_for_character'):
                 await self._dialogue_manager.clean_up_for_character(character_id, context=cleanup_context)
            print(f"CharacterManager: Cleanup initiated for character {character_id} in guild {guild_id}.")
        except Exception as e:
             print(f"CharacterManager: Error during cleanup for character {character_id} in guild {guild_id}: {e}")
             traceback.print_exc()
             # Решите, нужно ли перебрасывать исключение при ошибке очистки.
             # Возможно, лучше просто логировать и продолжить удаление самого персонажа.
             # Пока оставлю логирование без перебрасывания.


        # Отмечаем персонажа как удаленного (удалит из кеша и добавит в список на удаление из DB)
        # Передача guild_id в mark_character_deleted не нужна, т.к. она работает с кешем по ID.
        self.mark_character_deleted(character_id)

        print(f"CharacterManager: Character {character_id} ({char.name}) removal process initiated for guild {guild_id}. Will be deleted from DB on next save.")
        return character_id # Возвращаем ID удаленного персонажа

    # --- Методы обновления состояния персонажа ---

    # Добавляем **kwargs к методам обновления, если они могут быть переданы извне (например, из ActionProcessor)
    async def set_party_id(self, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        """Устанавливает ID группы для персонажа."""
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found to set party ID.")
            return False
        if char.party_id == party_id:
            return True # Уже в этой группе или уже без группы
        char.party_id = party_id
        self.mark_character_dirty(character_id) # Помечаем, что персонаж изменен
        print(f"CharacterManager: Set party ID for character {character_id} to {party_id}.")
        return True

    async def update_character_location(self, character_id: str, location_id: Optional[str], **kwargs: Any) -> bool:
        """Обновляет локацию персонажа."""
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found to update location.")
            return False
        if char.location_id == location_id:
             return True # Уже там
        char.location_id = location_id
        self.mark_character_dirty(character_id)
        print(f"CharacterManager: Updated location for character {character_id} to {location_id}.")
        return True

    # Добавьте другие методы обновления состояния персонажа (инвентарь, статы, здоровье и т.д.)
    # Не забывайте добавлять **kwargs к сигнатуре, если они могут быть переданы
    # и вызывать self.mark_character_dirty(character_id) после изменений.

    async def add_item_to_inventory(self, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
         """Добавляет предмет в инвентарь персонажа."""
         char = self.get_character(character_id)
         if not char:
             print(f"CharacterManager: Character {character_id} not found to add item.")
             return False
         # Логика добавления предмета к char.inventory
         # Пример: найти предмет в инвентаре, если есть, увеличить количество, если нет, добавить новый элемент
         item_found = False
         # Предполагаем, что char.inventory - это List[Dict[str, Any]] с полями 'item_id', 'quantity'
         for item_entry in char.inventory:
             if isinstance(item_entry, dict) and item_entry.get('item_id') == item_id:
                 item_entry['quantity'] = item_entry.get('quantity', 0) + quantity
                 item_found = True
                 break
         if not item_found:
             char.inventory.append({'item_id': item_id, 'quantity': quantity})

         self.mark_character_dirty(character_id) # Помечаем персонажа измененным
         print(f"CharacterManager: Added {quantity} of item '{item_id}' to character {character_id} inventory.")
         return True

    async def remove_item_from_inventory(self, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
         """Удаляет предмет из инвентаря персонажа."""
         char = self.get_character(character_id)
         if not char:
             print(f"CharacterManager: Character {character_id} not found to remove item.")
             return False
         # Логика удаления предмета из char.inventory
         # Пример: найти предмет, уменьшить количество или удалить элемент
         item_index_to_remove = -1
         for i, item_entry in enumerate(char.inventory):
             if isinstance(item_entry, dict) and item_entry.get('item_id') == item_id:
                 item_entry['quantity'] = item_entry.get('quantity', 0) - quantity
                 if item_entry['quantity'] <= 0:
                     item_index_to_remove = i
                 item_found = True # item_found indicates we found the item to remove from
                 break # Found the item, can stop searching

         if item_index_to_remove != -1:
             del char.inventory[item_index_to_remove]
         # else: # If item not found or quantity didn't go below zero, maybe log a warning?
             # print(f"CharacterManager: Warning: Attempted to remove {quantity} of non-existent or insufficient item '{item_id}' from character {character_id}.")
             # return False # Or return False if removal didn't happen as requested

         self.mark_character_dirty(character_id) # Помечаем персонажа измененным
         print(f"CharacterManager: Removed {quantity} of item '{item_id}' from character {character_id} inventory (if available).")
         # Возвращаем True, если логика удаления прошла, даже если предмет не найден или количество не уменьшилось ниже нуля?
         # Или возвращаем True только если количество > 0 после удаления?
         # Давайте вернем True, если персонаж найден, иначе False. Логика внутри уже обрабатывает наличие предмета.
         return True # Assume success if char found


    async def update_health(self, character_id: str, amount: float, **kwargs: Any) -> bool:
         """Обновляет здоровье персонажа."""
         char = self.get_character(character_id)
         if not char:
             print(f"CharacterManager: Character {character_id} not found to update health.")
             return False
         # Если персонаж уже мертв, возможно, не обновляем здоровье, если это не воскрешение
         # if not char.is_alive and amount < 0: return False # Нельзя навредить мертвому
         # if char.is_alive and amount < 0 and char.health + amount <= 0: # Если умрет от этого урона
         #      char.health = 0
         #      self.mark_character_dirty(character_id)
         #      await self.handle_character_death(character_id, **kwargs) # Передаем контекст в хендлер смерти
         #      return True # Возвращаем True, т.к. здоровье было обновлено (до 0)

         # Общая логика обновления здоровья
         new_health = char.health + amount
         # Ограничиваем здоровье между 0 и max_health
         char.health = max(0.0, min(char.max_health, new_health)) # Используем 0.0 и char.max_health как float

         self.mark_character_dirty(character_id) # Помечаем измененным

         # Проверяем смерть после обновления
         if char.health <= 0 and char.is_alive: # Если здоровье стало <= 0 И персонаж еще не помечен как мертвый
              await self.handle_character_death(character_id, **kwargs) # Передаем контекст в хендлер смерти

         print(f"CharacterManager: Updated health for character {character_id} to {char.health}. Amount: {amount}.")
         return True

    async def handle_character_death(self, character_id: str, **kwargs: Any):
         """Обрабатывает смерть персонажа."""
         char = self.get_character(character_id)
         if not char or not char.is_alive: # Проверяем, что персонаж существует и еще жив
             print(f"CharacterManager: handle_character_death called for non-existent or already dead character {character_id}.")
             return

         char.is_alive = False # Помечаем как мертвого
         self.mark_character_dirty(character_id) # Помечаем измененным

         print(f"Character {character_id} ({char.name}) has died.")

         # TODO: Логика смерти:
         # 1. Уведомить игрока/гильдию (через колбэк, который может быть в kwargs)
         # 2. Очистить статусы (status_manager.clean_up_for_character) - это уже делается в remove_character, но смерть это не всегда удаление
         #    Возможно, нужен отдельный метод clean_up_on_death в StatusManager
         # 3. Убрать из боя (combat_manager.remove_from_combat)
         # 4. Убрать из группы (party_manager.remove_member)
         # 5. Возможно, переместить в специальную локацию "Загробный мир" или "Место смерти"
         # 6. Возможно, дропнуть предметы из инвентаря (item_manager.drop_inventory)
         # 7. Триггеры смерти (RuleEngine?)
         # 8. Логика воскрешения (возможно, отдельный метод или через статус-эффект)

         # Примеры использования менеджеров из kwargs:
         # send_callback = kwargs.get('send_message_callback') # Или фабрика send_callback_factory
         # if send_callback:
         #      guild_id = kwargs.get('guild_id')
         #      channel_id = kwargs.get('channel_id') # Или получить из event/location
         #      if guild_id and channel_id:
         #          # Предполагаем, что send_callback_factory есть в kwargs или в self
         #          send_factory = kwargs.get('send_callback_factory') or getattr(self, '_send_callback_factory', None)
         #          if send_factory:
         #              await send_factory(channel_id)(f"{char.name} пал в бою!", None)

         # combat_mgr = kwargs.get('combat_manager') or self._combat_manager
         # if combat_mgr and hasattr(combat_mgr, 'remove_from_combat'):
         #      await combat_mgr.remove_from_combat(character_id, context=kwargs)

         # party_mgr = kwargs.get('party_manager') or self._party_manager
         # if party_mgr and char.party_id and hasattr(party_mgr, 'remove_member'):
         #      await party_mgr.remove_member(char.party_id, character_id, context=kwargs)


    # --- Методы для управления активностью/занятостью ---

    def set_active_action(self, character_id: str, action_details: Optional[Dict[str, Any]]) -> None:
        """Устанавливает текущее активное действие персонажа."""
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found to set active action.")
            return
        char.current_action = action_details
        if action_details is not None:
            self._entities_with_active_action.add(character_id)
        else:
            self._entities_with_active_action.discard(character_id) # Удаляем, если действие завершено
        self.mark_character_dirty(character_id)


    def add_action_to_queue(self, character_id: str, action_details: Dict[str, Any]) -> None:
        """Добавляет действие в очередь персонажа."""
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found to add action to queue.")
            return
        if not isinstance(char.action_queue, list): char.action_queue = [] # Убеждаемся, что это список
        char.action_queue.append(action_details)
        self.mark_character_dirty(character_id)
        self._entities_with_active_action.add(character_id) # Помечаем занятым, если что-то есть в очереди/текущем действии

    def get_next_action_from_queue(self, character_id: str) -> Optional[Dict[str, Any]]:
        """Извлекает следующее действие из очереди."""
        char = self.get_character(character_id)
        if not char or not isinstance(char.action_queue, list) or not char.action_queue:
            return None
        # Извлекаем первое действие из очереди
        next_action = char.action_queue.pop(0)
        self.mark_character_dirty(character_id)
        # Если очередь опустела и нет текущего действия, можно снять пометку "занят"
        if not char.action_queue and char.current_action is None:
             self._entities_with_active_action.discard(character_id)
        return next_action


    # --- Вспомогательные методы ---
    # async def notify_character(self, character_id: str, message: str, **kwargs):
    #      """Метод для отправки сообщений конкретному персонажу (через Discord или другие средства)."""
    #      # Как отмечалось ранее, это лучше делать в процессорах или сервисах,
    #      # которые имеют доступ к механизмам отправки сообщений (например, Discord боту).
    #      # Менеджер персонажей хранит данные, но не должен напрямую взаимодействовать с Discord API.
    #      pass
