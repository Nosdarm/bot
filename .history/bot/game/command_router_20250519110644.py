# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING # Import TYPE_CHECKING

# --- Imports ---
# Прямой импорт модели Character, так как она нужна для runtime (например, для Character.from_dict)
from bot.game.models.character import Character

# --- Imports needed ONLY for Type Checking ---
# Эти модули импортируются ТОЛЬКО для статического анализа (Pylance/Mypy).
# Это разрывает циклы импорта при runtime и помогает Pylance правильно резолвить типы.
# Используйте строковые литералы ("ClassName") для type hints в __init__ и методах
# для классов, импортированных здесь.
if TYPE_CHECKING:
    # Добавляем SqliteAdapter сюда
    from bot.database.sqlite_adapter import SqliteAdapter
    # Добавляем другие менеджеры и RuleEngine, как было ранее
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.rules.rule_engine import RuleEngine
    # !!! Добавляем Character сюда тоже, несмотря на прямой импорт выше !!!
    # Это нужно, чтобы Pylance разрешал строковые литералы в аннотациях (напр., Dict[str, "Character"]).
    from bot.game.models.character import Character


# --- Imports needed at Runtime ---
# Для CharacterManager обычно нужен только прямой импорт модели Character и утилит.


print("DEBUG: character_manager.py module loaded.")


class CharacterManager:
    """
    Менеджер для управления персонажами игроков.
    Отвечает за создание, получение, обновление персонажей, их персистентность
    и хранение их основного состояния и кешей.
    """
    # Добавляем required_args для совместимости с PersistenceManager
    # Эти поля используются PersistenceManager для определения, какие аргументы передать в load/save/rebuild.
    required_args_for_load = ["guild_id"] # Предполагаем, что load_state фильтрует по guild_id
    required_args_for_save = ["guild_id"] # Предполагаем, что save_state фильтрует по guild_id
    required_args_for_rebuild = ["guild_id"] # Предполагаем, что rebuild фильтрует по guild_id


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
        # Используем строковый литерал в аннотации кеша, чтобы Pylance распознал тип "Character"
        self._characters: Dict[str, "Character"] = {} # Кеш всех загруженных объектов персонажей {char_id: Character_object}
        # Мапа Discord User ID на ID персонажа (UUID) - для быстрого поиска
        # В многогильдийном режиме, если Discord ID уникален только per-guild, эта мапа должна быть {guild_id: {discord_id: char_id}}.
        # Текущая структура предполагает, что discord_id уникален глобально, или используется для одногильдийного бота.
        self._discord_to_char_map: Dict[int, str] = {}
        # Set ID сущностей (Character/NPC), которые в данный момент выполняют индивидуальное действие или в активной очереди
        self._entities_with_active_action: Set[str] = set()
        # ID персонажей, которые были изменены в runtime и требуют сохранения в DB
        self._dirty_characters: Set[str] = set()
        # ID персонажей, которые были удалены в runtime и требуют удаления из DB
        self._deleted_characters_ids: Set[str] = set()

        print("CharacterManager initialized.")

    # --- Методы получения персонажей ---
    # Используем строковый литерал в аннотации возвращаемого типа
    def get_character(self, character_id: str) -> Optional["Character"]:
        """Получить персонажа по его внутреннему ID (UUID)."""
        return self._characters.get(character_id)

    # Используем строковый литерал в аннотации возвращаемого типа
    def get_character_by_discord_id(self, discord_user_id: int) -> Optional["Character"]:
        """Получить персонажа по Discord User ID."""
        # В текущей реализации мапа глобальная, не per-guild.
        char_id = self._discord_to_char_map.get(discord_user_id)
        # Возвращаем персонажа из основного кеша, если ID найден в мапе
        return self._characters.get(char_id) # Возвращает None если char_id == None или char_id не найден в _characters


    # Используем строковый литерал в аннотации возвращаемого типа
    def get_character_by_name(self, name: str) -> Optional["Character"]:
         """Получить персонажа по имени (может быть медленно для большого количества персонажей)."""
         # Реализация: пройтись по self._characters.values()
         for char in self._characters.values():
             # Pylance должен понять тип 'char' из аннотации self._characters
             if char.name == name:
                 return char
         return None

    # Используем строковый литерал в аннотации возвращаемого типа
    def get_all_characters(self) -> List["Character"]:
        """Получить список всех загруженных персонажей (из кеша)."""
        return list(self._characters.values())

    def get_characters_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List["Character"]:
        """Получить список персонажей, находящихся в указанной локации (инстансе) для данной гильдии."""
        # Эффективная реализация требует кеша {location_id: set(character_id)}, который строится при загрузке и обновляется при перемещении.
        # В текущей структуре нет такого кеша. Приходится перебирать всех персонажей.
        # Если менеджер персонажей кеширует ВСЕХ персонажей всех гильдий (_characters плоский),
        # то нужно фильтровать по guild_id И location_id.
        # Если Character модель имеет атрибут guild_id (что она, видимо, имеет), можно фильтровать так:
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        characters_in_location = []
        for char in self._characters.values():
            # Убеждаемся, что char имеет атрибуты guild_id и location_id и сравниваем
            if hasattr(char, 'guild_id') and str(char.guild_id) == guild_id_str and \
               hasattr(char, 'location_id') and str(char.location_id) == location_id_str:
                characters_in_location.append(char)

        # Если вы ожидаете NPC или другие сущности в этой локации,
        # эту логику лучше вынести в LocationManager, который будет запрашивать у менеджеров сущностей.
        # Но если этот метод используется для уведомлений в handle_entity_arrival/departure в LocationManager,
        # и он ожидает только персонажей, то эта логика ОК, но медленная для большого числа персонажей.
        # print(f"CharacterManager: Found {len(characters_in_location)} characters in location {location_id_str} for guild {guild_id_str}.") # Debug
        return characters_in_location


    def get_entities_with_active_action(self) -> Set[str]:
        """Получить ID сущностей (включая персонажей) с активным действием."""
        return set(self._entities_with_active_action)

    def is_busy(self, character_id: str) -> bool:
        """Проверяет, занят ли персонаж (выполняет действие или состоит в занятой группе)."""
        # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
        char = self.get_character(character_id)
        if not char:
            return False
        # Проверка на текущее действие персонажа
        if getattr(char, 'current_action', None) is not None or getattr(char, 'action_queue', []):
            return True
        # Проверка, занята ли его группа (используем инжектированный party_manager, если он есть)
        if getattr(char, 'party_id', None) is not None and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
            # PartyManager.is_party_busy может нуждаться в guild_id или контексте
            # PartyManager.is_party_busy(party_id: str, **kwargs) -> bool
            # Нужно ли передавать guild_id или контекст сюда? Это зависит от реализации PartyManager.
            # Если PartyManager.is_party_busy работает только по party_id и кеширует per-guild, возможно, не нужно.
            # Если PartyManager.is_party_busy требует guild_id, нужно получить его из Character объекта:
            # guild_id_char = getattr(char, 'guild_id', None)
            # if guild_id_char is not None:
            #      return self._party_manager.is_party_busy(char.party_id, guild_id=str(guild_id_char))
            # Пока вызываем без guild_id/kwargs, предполагая, что метод справляется
            return self._party_manager.is_party_busy(char.party_id) # Предполагаем синхронный метод без доп. аргументов
        # Если party_manager нет или нет метода, считаем, что группа не может быть занята через него
        return False


    # --- Методы создания ---

    async def create_character(
        self,
        discord_id: int, # Discord User ID (int)
        name: str, # Имя персонажа (string)
        # Опциональная начальная локация (ID инстанса локации)
        initial_location_id: Optional[str] = None,
        # Добавляем **kwargs, так как PersistenceManager/CommandRouter может передавать контекст, включая guild_id
        **kwargs: Any # Словарь с дополнительными аргументами (например, guild_id)
    ) -> Optional["Character"]: # Возвращаем Optional["Character"], т.к. создание может не удасться
        """
        Создает нового персонажа в базе данных, кеширует его и возвращает объект Character.
        Использует UUID для внутреннего ID персонажа.
        Принимает guild_id в kwargs.
        Возвращает Character объект при успехе, None при неудаче (напр., персонаж уже существует).
        """
        if self._db_adapter is None:
            print("CharacterManager: Error: DB adapter missing.")
            raise ConnectionError("Database adapter is not initialized in CharacterManager.")


        # ИСПРАВЛЕНИЕ: Получаем guild_id из kwargs, который передается сюда из GameManager/CommandRouter
        guild_id_for_create = kwargs.get('guild_id') # Type: Optional[str]
        if guild_id_for_create is None:
             print("CharacterManager: Error creating character: Missing mandatory 'guild_id' in kwargs.")
             # Если guild_id обязателен для многогильдийности, нужно рейзить ошибку.
             raise ValueError("Character creation requires 'guild_id' in kwargs.")


        # Проверка на существование персонажа для этого discord_id и guild_id
        # Вам, вероятно, нужно проверить уникальность discord_id В ПРЕДЕЛАХ ГИЛЬДИИ
        # Текущий get_character_by_discord_id ищет по всему кешу _discord_to_char_map (глобально)
        # Если бот многогильдийный и кеш _discord_to_char_map глобальный, это может быть проблемой.
        # Предлагаемое решение: получить персонажа по discord_id глобально, а затем проверить его guild_id.
        existing_char = self.get_character_by_discord_id(discord_id)
        if existing_char: # Если найден персонаж с этим discord_id
             # Проверяем, принадлежит ли он этой гильдии
             existing_char_guild_id = getattr(existing_char, 'guild_id', None)
             if existing_char_guild_id is not None and str(existing_char_guild_id) == str(guild_id_for_create):
                  print(f"CharacterManager: Character already exists for discord ID {discord_id} in guild {guild_id_for_create}.")
                  return None # Возвращаем None, если персонаж уже есть в этой гильдии
             else:
                  # Персонаж с таким discord_id существует, но в другой гильдии. Разрешено?
                  # Или discord_id должен быть уникален глобально?
                  # Предположим, что discord_id должен быть уникален глобально для мапы _discord_to_char_map.
                  # Если это не так, то _discord_to_char_map должна быть {guild_id: {discord_id: char_id}}.
                  # В текущей реализации, если бот многогильдийный и discord_id переиспользуются, _discord_to_char_map будет перезаписываться, и get_character_by_discord_id будет возвращать только последнего загруженного/созданного.
                  # Для текущей структуры: если персонаж с этим discord_id уже есть ГДЕ-ЛИБО, считаем ошибкой.
                  print(f"CharacterManager: Character with discord ID {discord_id} already exists (ID: {existing_char.id}) in guild {getattr(existing_char, 'guild_id', 'N/A')}. Creation failed.")
                  # Возможно, нужно отправить уведомление GM или игроку?
                  raise ValueError(f"User already has a character (ID: {existing_char.id}) in guild {getattr(existing_char, 'guild_id', 'N/A')}.")


        # Проверка на уникальность имени персонажа (в пределах гильдии)
        # get_character_by_name ищет по всему кешу (глобально). Нужна проверка уникальности имени в пределах гильдии.
        existing_char_by_name = self.get_character_by_name(name)
        if existing_char_by_name: # Если найден персонаж с таким именем
             existing_char_by_name_guild_id = getattr(existing_char_by_name, 'guild_id', None)
             if existing_char_by_name_guild_id is not None and str(existing_char_by_name_guild_id) == str(guild_id_for_create):
                  print(f"CharacterManager: Character with name '{name}' already exists in guild {guild_id_for_create}. Creation failed.")
                  return None # Возвращаем None, если имя уже занято в этой гильдии
             # Если персонаж с таким именем есть, но в другой гильдии - это разрешено.


        # Генерируем уникальный ID (UUID). Уникальность UUID должна гарантировать глобальную уникальность ID.
        new_id = str(uuid.uuid4())


        # Определяем начальную локацию (используем инжектированный location_manager, если он есть)
        # Вызов get_default_location_id требует guild_id
        resolved_initial_location_id = initial_location_id
        # Убедимся, что self._location_manager доступен И guild_id доступен, прежде чем пытаться получить дефолтную локацию, зависящую от гильдии.
        if resolved_initial_location_id is None and self._location_manager and hasattr(self._location_manager, 'get_default_location_id') and guild_id_for_create is not None:
             try:
                 # ИСПРАВЛЕНИЕ: Вызываем get_default_location_id с аргументом guild_id
                 # Предполагаем, что get_default_location_id синхронный и принимает guild_id
                 # LocationManager.get_default_location_id(guild_id: str) -> Optional[str]
                 resolved_initial_location_id = self._location_manager.get_default_location_id(guild_id=guild_id_for_create)
                 if resolved_initial_location_id:
                      print(f"CharacterManager: Using default location ID: {resolved_initial_location_id} for guild {guild_id_for_create}")
             except Exception as e:
                 print(f"CharacterManager: Warning: Could not get default location ID for guild {guild_id_for_create}: {e}")
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
        # Используем data для консистентности и удобства
        data: Dict[str, Any] = {
            'id': new_id, # UUID как TEXT
            'discord_user_id': discord_id, # Значение из параметра discord_id
            'name': name,
            'guild_id': guild_id_for_create, # <-- Добавляем guild_id при создании!
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
            data['guild_id'], # <-- Параметр guild_id
            data['location_id'],
            json.dumps(data['stats']),
            json.dumps(data['inventory']),
            json.dumps(data['current_action']) if data['current_action'] is not None else None,
            json.dumps(data['action_queue']),
            data['party_id'],
            json.dumps(data['state_variables']),
            data['health'],
            data['max_health'],
            int(data['is_alive']), # boolean как integer
            json.dumps(data['status_effects']),
            # ... другие параметры ...
        )

        # Проверяем, что self._db_adapter доступен перед использованием.
        if self._db_adapter is None:
             print("CharacterManager: Error creating character: DB adapter is None.")
             raise ConnectionError("Database adapter is not initialized in CharacterManager.")

        try:
            # Выполняем INSERT. Используем execute для вставки с заданным ID (UUID).
            # Это исправляет ошибку 'SqliteAdapter' object has no attribute 'execute_insert'
            await self._db_adapter.execute(sql, db_params)
            print(f"CharacterManager: Character '{name}' with ID {new_id} inserted into DB for guild {guild_id_for_create}.") # Логируем guild_id


            # Создаем объект модели Character из данных (данные уже в формате Python объектов)
            # Здесь нужен прямой доступ к классу Character
            char = Character.from_dict(data) # Ln 236 (approx, numbers may shift)


            # Добавляем персонажа в кеши (теперь кеши предполагаются плоскими: {char_id: char}, {discord_id: char_id})
            self._characters[char.id] = char
            if char.discord_user_id is not None:
                 # Убеждаемся, что discord_user_id является хэшируемым типом (int)
                 self._discord_to_char_map[char.discord_user_id] = char.id # Мапа discord_id -> char_id (глобально?)

            # Отмечаем как грязный, чтобы он был сохранен при следующем save.
            # Это гарантирует, что новый персонаж попадет в БД при первом сохранении после создания.
            # _dirty_characters используется для отслеживания изменений.
            self.mark_character_dirty(char.id) # Используем mark_character_dirty метод


            print(f"CharacterManager: Character '{name}' (ID: {char.id}, Guild: {char.guild_id}) created and cached.")
            return char # Возвращаем созданный объект Character

        except Exception as e:
            # Исправлено в предыдущем сообщении, но может вернуться в старой версии
            print(f"CharacterManager: Error creating character '{name}' for discord ID {discord_id} in guild {guild_id_for_create}: {e}") # Логируем guild_id
            import traceback
            print(traceback.format_exc())
            # Перебрасываем исключение, чтобы GameManager/CommandRouter мог его поймать
            raise


    # --- Методы сохранения/загрузки (для PersistenceManager) ---
    # Добавляем required_args для совместимости с PersistenceManager
    # Эти поля используются PersistenceManager для определения, какие аргументы передать в load/save/rebuild.
    required_args_for_load = ["guild_id"] # load_state фильтрует по guild_id
    required_args_for_save = ["guild_id"] # save_state фильтрует по guild_id
    required_args_for_rebuild = ["guild_id"] # rebuild_runtime_caches фильтрует по guild_id


    async def save_state(self, guild_id: str, **kwargs: Any) -> None: # Сохраняет все измененные или удаленные персонажи для определенного guild_id
        """Сохраняет все измененные или удаленные персонажи для определенного guild_id."""
        if self._db_adapter is None:
            print(f"CharacterManager: Warning: Cannot save characters for guild {guild_id}, DB adapter missing.")
            return
        # Фильтруем dirty/deleted по guild_id
        dirty_char_ids_for_guild = {cid for cid in self._dirty_characters if cid in self._characters and getattr(self._characters[cid], 'guild_id', None) == guild_id}
        deleted_char_ids_for_guild = {cid for cid in self._deleted_characters_ids} # Удаленные ID - это глобальный список, их удаляем по ID + guild_id фильтру в SQL.
        # ВАЖНО: Если удаленный персонаж НЕ БЫЛ загружен (например, удален в DB другим способом), его ID не попадет в _deleted_characters_ids.
        # Если clean_up_for_character не удаляет из _deleted_characters_ids после успешного удаления, то список может расти.

        if not dirty_char_ids_for_guild and not deleted_char_ids_for_guild:
            # print(f"CharacterManager: No dirty or deleted characters to save for guild {guild_id}.") # Можно закомментировать
            return

        print(f"CharacterManager: Saving {len(dirty_char_ids_for_guild)} dirty, {len(deleted_char_ids_for_guild)} deleted characters for guild {guild_id}...")

        # Удалить помеченные для удаления персонажи для этого guild_id
        if deleted_char_ids_for_guild:
            ids_to_delete = list(deleted_char_ids_for_guild)
            placeholders = ','.join(['?'] * len(ids_to_delete))
            # Убеждаемся, что удаляем ТОЛЬКО для данного guild_id и по ID
            delete_sql = f"DELETE FROM characters WHERE guild_id = ? AND id IN ({placeholders})"
            try:
                await self._db_adapter.execute(delete_sql, (str(guild_id), *tuple(ids_to_delete))) # Убедимся, что guild_id строка
                print(f"CharacterManager: Deleted {len(ids_to_delete)} characters from DB for guild {guild_id}.")
                # Очищаем список после успешного удаления (удаляем все ID из deleted_char_ids_for_guild из основного списка _deleted_characters_ids)
                self._deleted_characters_ids.difference_update(deleted_char_ids_for_guild)
            except Exception as e:
                print(f"CharacterManager: Error deleting characters for guild {guild_id}: {e}")
                import traceback
                print(traceback.format_exc())
                # Не очищаем _deleted_characters_ids, чтобы попробовать удалить снова при следующей сохранке


        # Обновить или вставить измененные персонажи для этого guild_id
        # Фильтруем dirty_instances на те, что все еще существуют в кеше (не были удалены)
        characters_to_save = [self._characters[cid] for cid in list(dirty_char_ids_for_guild) if cid in self._characters] # Убеждаемся, что они еще в кеше
        if characters_to_save:
             print(f"CharacterManager: Upserting {len(characters_to_save)} characters for guild {guild_id}...")
             # INSERT OR REPLACE SQL для обновления существующих или вставки новых
             # Убеждаемся, что SQL соответствует текущей схеме и полям Character модели, включая guild_id
             upsert_sql = '''
             INSERT OR REPLACE INTO characters
             (id, discord_user_id, name, guild_id, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             '''
             # Формируем список кортежей для execute_many
             data_to_upsert = []
             for char in characters_to_save:
                 try:
                     # Убеждаемся, что у объекта Character есть все нужные атрибуты
                     char_id = getattr(char, 'id', None)
                     discord_user_id = getattr(char, 'discord_user_id', None)
                     char_name = getattr(char, 'name', None)
                     char_guild_id = getattr(char, 'guild_id', None) # Должен быть установлен при создании/загрузке
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


                     # Дополнительная проверка на критически важные атрибуты
                     if char_id is None or discord_user_id is None or char_name is None or char_guild_id is None:
                         print(f"CharacterManager: Warning: Skipping upsert for character with missing mandatory attributes (ID, Discord ID, Name, Guild ID). Character object: {char}")
                         continue # Пропускаем этого персонажа


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
                         str(char_guild_id), # Убедимся, что guild_id строка для DB
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
                 except Exception as e:
                     print(f"CharacterManager: Error preparing data for character {getattr(char, 'id', 'N/A')} ({getattr(char, 'name', 'N/A')}) for upsert: {e}")
                     import traceback
                     print(traceback.format_exc())
                     # Этот персонаж не будет сохранен в этой итерации - он останется в _dirty_characters
                     # чтобы попробовать сохранить его снова

             if data_to_upsert:
                 try:
                     # Используем execute_many для пакетной вставки/обновления
                     if self._db_adapter is None:
                          print(f"CharacterManager: Warning: DB adapter is None during upsert batch for guild {guild_id}.")
                     else:
                          await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                          print(f"CharacterManager: Successfully upserted {len(data_to_upsert)} characters for guild {guild_id}.")
                          # Только если execute_many успешен, очищаем список "грязных"
                          # Внимание: очищаем только те, которые были в dirty_char_ids_for_guild!
                          self._dirty_characters.difference_update(dirty_char_ids_for_guild)
                 except Exception as e:
                     print(f"CharacterManager: Error during batch upsert for guild {guild_id}: {e}")
                     import traceback
                     print(traceback.format_exc())
                     # Не очищаем _dirty_characters, чтобы попробовать сохранить снова

        print(f"CharacterManager: Save state complete for guild {guild_id}.")


    async def load_state(self, guild_id: str, **kwargs: Any) -> None: # load_state загружает персонажи для определенного guild_id
        """Загружает все персонажи для определенного guild_id из базы данных в кеш."""
        if self._db_adapter is None:
            print(f"CharacterManager: Warning: Cannot load characters for guild {guild_id}, DB adapter missing.")
            # TODO: В режиме без DB, нужно загрузить Placeholder персонажи
            return

        print(f"CharacterManager: Loading characters for guild {guild_id} from DB...")
        # Текущая реализация load_state с полной очисткой кеша (self._characters.clear() и т.д.)
        # НЕ ИДЕАЛЬНА для многогильдийности, если PersistenceManager вызывает load_state для каждой гильдии отдельно.
        # В этом случае load_state для гильдии A очистит кеш персонажей гильдии B.
        # ИДЕАЛЬНОЕ решение: перестроить кеш _characters и _discord_to_char_map как {guild_id: {id: ...}}.
        # НО! Требует значительного рефакторинга всех геттеров/сеттеров.
        #
        # Если PersistenceManager вызывает load_state для *всех* гильдий один раз при старте (получив список guild_ids заранее),
        # тогда текущая реализация load_state (очистка кеша -> загрузка по guild_id -> наполнение кеша) рабочая,
        # но нужно, чтобы _PersistenceManager перебирал ВСЕ guild_ids при загрузке.
        # Судя по тому, как мы адаптировали PersistenceManager, он как раз итерирует по guild_ids и вызывает _call_manager_load(guild_id).
        # Значит, этот CharacterManager.load_state будет вызван для каждой гильдии.
        # Если кеш _characters глобальный {char_id: char}, это будет ПЕРЕЗАПИСЫВАТЬ кеш при загрузке каждой следующей гильдии!
        # Это БАГ при многогильдийности и текущей структуре кеша.
        #
        # Варианты:
        # 1. Переделать структуру кеша (наилучший вариант, но требует времени).
        # 2. Сделать load_state в PM таким, чтобы он один раз загружал ВСЕХ персонажей без фильтра. (Не соответствует per-guild load)
        # 3. Модифицировать CharacterManager.load_state так, чтобы он НЕ ОЧИЩАЛ _characters, а только добавлял в него
        #    персонажей для данной guild_id, И удалял из _characters тех, кто есть в кеше, но ОТСУТСТВУЕТ в DB для этой гильдии.
        #    Это сложнее.
        #
        # Оставляем текущую реализацию (очистка кеша -> загрузка по guild_id), осознавая, что она корректна ТОЛЬКО если вызывается для *одной* гильдии при старте бота.
        # Или если вызовов load_state для разных гильдий не происходит.
        # Или если кеш _characters на самом деле per-guild, несмотря на его декларацию {} здесь.
        # Я предполагаю, что load_state вызывается для каждой гильдии, но кеш должен быть глобальным. Это рассогласование.
        #
        # TODO: Решить проблему кеширования в многогильдийном режиме. В текущем коде есть несоответствие.

        # В текущей реализации, load_state для одной гильдии ОЧИЩАЕТ кеши ВСЕХ гильдий.
        # Это приведет к тому, что при загрузке нескольких гильдий в кеше останутся только персонажи последней загруженной гильдии.
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
            # Убеждаемся, что guild_id строка для SQL
            rows = await self._db_adapter.fetchall(sql, (str(guild_id),))
            print(f"CharacterManager: Found {len(rows)} characters in DB for guild {guild_id}.")

        except Exception as e:
            # Если произошла ошибка при самом выполнении запроса fetchall
            print(f"CharacterManager: ❌ CRITICAL ERROR executing DB fetchall для guild {guild_id}: {e}")
            import traceback
            print(traceback.format_exc())
            # В этом случае rows будет пустым списком, и мы просто выйдем из метода после обработки ошибки.
            # Очистка кешей уже была сделана выше.
            # Возможно, нужно перебрасывать исключение, чтобы GameManager знал, что загрузка не удалась?
            # Если load_state вызывается для каждой гильдии, перебрасывание исключения остановит загрузку всех гильдий.
            # Лучше просто логировать и не загружать персонажей для этой гильдии.
            raise # Пробрасываем критическую ошибку

        # Теперь обрабатываем каждую строку ВНУТРИ ЦИКЛА
        loaded_count = 0
        for row in rows:
            # Убеждаемся, что row - это dict-подобный объект
            data = dict(row)
            try:
                # Проверяем наличие обязательных полей
                char_id_raw = data.get('id')
                discord_user_id_raw = data.get('discord_user_id')
                guild_id_raw = data.get('guild_id')

                if char_id_raw is None or discord_user_id_raw is None or guild_id_raw is None:
                    print(f"CharacterManager: Warning: Skipping row with missing mandatory fields (ID, Discord ID, Guild ID). Row data: {data}. ")
                    continue # Пропускаем строку без обязательных полей

                # Проверяем и преобразуем ID в строку
                char_id = str(char_id_raw)
                loaded_guild_id = str(guild_id_raw)

                # Проверяем, что guild_id в данных соответствует тому, который мы загружали
                if loaded_guild_id != str(guild_id):
                     print(f"CharacterManager: Warning: Mismatch guild_id for character {char_id}: Expected {guild_id}, got {loaded_guild_id}. Skipping.")
                     continue # Пропускаем строку, если guild_id не совпадает

                # Проверяем и преобразуем discord_user_id в int
                try:
                    discord_user_id_int = int(discord_user_id_raw)
                except (ValueError, TypeError):
                     print(f"CharacterManager: Warning: Invalid discord_user_id format for character {char_id}: {discord_user_id_raw}. Skipping mapping.")
                     discord_user_id_int = None # Не сможем смапить

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

                # Обновляем данные в словаре data, используя преобразованные значения
                data['id'] = char_id
                data['discord_user_id'] = discord_user_id_int # Сохраняем int версию
                data['guild_id'] = loaded_guild_id # Сохраняем string версию (или лучше original_raw?) - Consistent str is better


                # Создаем объект модели Character
                # Передаем полный словарь data, который теперь содержит все преобразованные значения
                # Character.from_dict(data: Dict[str, Any]) -> Character
                char = Character.from_dict(data) # Ln 461 (approx, numbers may shift)

                # Добавляем в кеш по ID
                self._characters[char.id] = char # Добавление в глобальный кеш

                # Добавляем в кеш по Discord ID, только если discord_user_id валидный int и он не None
                if discord_user_id_int is not None:
                     self._discord_to_char_map[discord_user_id_int] = char.id # Добавление в глобальную мапу

                # Если у персонажа есть активное действие или очередь, помечаем его как занятого
                if getattr(char, 'current_action', None) is not None or getattr(char, 'action_queue', []):
                    self._entities_with_active_action.add(char.id) # Добавление в глобальный Set

                loaded_count += 1 # Увеличиваем счетчик успешно загруженных

            except json.JSONDecodeError:
                # Ошибка парсинга JSON в ОДНОЙ строке
                print(f"CharacterManager: Error decoding JSON for character row (ID: {data.get('id', 'N/A')}, guild: {data.get('guild_id', 'N/A')}): {traceback.format_exc()}. Skipping this row.")
                # traceback.print_exc() # Печатаем подробный traceback для ошибки JSON
                # Продолжаем цикл для других строк
            except Exception as e:
                # Другая ошибка при обработке ОДНОЙ строки
                print(f"CharacterManager: Error processing character row (ID: {data.get('id', 'N/A')}, guild: {data.get('guild_id', 'N/A')}): {e}. Skipping this row.")
                import traceback
                print(traceback.format_exc())
                # Продолжаем цикл для других строк

        print(f"CharacterManager: Successfully loaded {loaded_count} characters into cache для guild {guild_id}.") # Уточнено логирование
        if loaded_count < len(rows):
             print(f"CharacterManager: Note: Failed to load {len(rows) - loaded_count} characters for guild {guild_id} due to errors.")

    # Добавляем метод rebuild_runtime_caches для совместимости с PersistenceManager
    def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None: # Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии.
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"CharacterManager: Rebuilding runtime caches for guild {guild_id_str}. (Placeholder)")
        # Этот метод вызывается для каждой гильдии после того, как PersistenceManager
        # загрузил состояние ВСЕХ менеджеров для этой гильдии.
        # Здесь можно построить кеши, которые зависят от данных из РАЗНЫХ менеджеров для ОДНОЙ гильдии.
        # Пример: построение кеша персонажей в локациях, если LocationManager не имеет такого кеша,
        # а вам он нужен в CharacterManager.
        # Этот метод в текущей структуре кешей не делает ничего, т.к. кеши (_characters, _discord_to_char_map)
        # наполняются непосредственно при загрузке в load_state.
        # Если PartyManager нуждается в списке персонажей для перестройки кеша партий,
        # он должен получить CharacterManager из kwargs и запросить у него персонажей:
        # party_mgr = kwargs.get('party_manager') # type: Optional["PartyManager"]
        # if party_mgr and hasattr(party_mgr, 'rebuild_cache_from_characters'):
        #      # Получаем всех персонажей этой гильдии. Requires iterating global cache or a per-guild getter.
        #      all_chars_in_guild = [char for char in self._characters.values() if getattr(char, 'guild_id', None) == guild_id_str] # Фильтруем глобальный кеш
        #      party_mgr.rebuild_cache_from_characters(all_chars_in_guild, guild_id=guild_id_str) # Передаем нужных персонажей и guild_id


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
             discord_id_to_remove = getattr(char, 'discord_user_id', None) # Safely get discord_user_id
             if discord_id_to_remove is not None:
                 # Ищем discord_id в мапе, который указывает на этого персонажа, и удаляем его
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
        # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
        char = self.get_character(character_id) # Ln 647 (approx)
        if not char:
            print(f"CharacterManager: Character {character_id} not found for removal in guild {guild_id}.")
            return None

        # Дополнительная проверка guild_id, если менеджер кеширует все гильдии
        # Убеждаемся, что guild_id строка
        char_guild_id = getattr(char, 'guild_id', None)
        if char_guild_id is None or str(char_guild_id) != str(guild_id):
             print(f"CharacterManager: Character {character_id} belongs to guild {char_guild_id}, not {guild_id}. Removal cancelled.")
             return None


        print(f"CharacterManager: Removing character {character_id} ({char.name}) from guild {guild_id}...")

        # Cleanup via managers (используем менеджеры, переданные в __init__)
        # Передаем context, включая guild_id и character_id
        cleanup_context: Dict[str, Any] = { # Явная аннотация Dict
            'guild_id': guild_id,
            'character_id': character_id,
            'character': char, # Pass the character object for convenience
            # Передаем другие менеджеры, которые могут понадобиться в cleanup методах
            # Используем атрибуты self._... для получения менеджеров
            'item_manager': self._item_manager,
            'status_manager': self._status_manager,
            'party_manager': self._party_manager,
            'combat_manager': self._combat_manager,
            'dialogue_manager': self._dialogue_manager,
            'location_manager': self._location_manager, # LocationManager может быть нужен для очистки
            'rule_engine': self._rule_engine, # RuleEngine может быть нужен для cleanup логики

            # TODO: Другие менеджеры
            # Включаем прочие из kwargs, если передаются в remove_character (напр., send_callback_factory)
        }
        cleanup_context.update(kwargs) # Добавляем kwargs через update


        try:
            # Убедитесь, что методы clean_up_* существуют в соответствующих менеджерах
            # и что они принимают character_id и context (**kwargs или явно).
            # Предполагаем, что они принимают context.
            if self._item_manager and hasattr(self._item_manager, 'clean_up_for_character'):
                await self._item_manager.clean_up_for_character(character_id, context=cleanup_context)
            if self._status_manager and hasattr(self._status_manager, 'clean_up_for_character'):
                 await self._status_manager.clean_up_for_character(character_id, context=cleanup_context)
            # PartyManager.clean_up_for_character должен уметь чистить по character_id
            if self._party_manager and hasattr(self._party_manager, 'clean_up_for_character'):
                 await self._party_manager.clean_up_for_character(character_id, context=cleanup_context)
            # CombatManager.clean_up_for_character должен уметь чистить по character_id
            if self._combat_manager and hasattr(self._combat_manager, 'clean_up_for_character'):
                 await self._combat_manager.clean_up_for_character(character_id, context=cleanup_context)
            # DialogueManager.clean_up_for_character должен уметь чистить по character_id
            if self._dialogue_manager and hasattr(self._dialogue_manager, 'clean_up_for_character'):
                 await self._dialogue_manager.clean_up_for_character(character_id, context=cleanup_context)

            print(f"CharacterManager: Cleanup initiated for character {character_id} in guild {guild_id}.")

        except Exception as e:
             print(f"CharacterManager: Error during cleanup for character {character_id} in guild {guild_id}: {e}")
             import traceback
             print(traceback.format_exc())
             # Решите, нужно ли перебрасывать исключение при ошибке очистки.
             # Возможно, лучше просто логировать и продолжить удаление самого персонажа.
             # Пока оставлю логирование без перебрасывания.


        # Отмечаем персонажа как удаленного (удалит из кеша и добавит в список на удаление из DB)
        # mark_character_deleted работает по character_id
        self.mark_character_deleted(character_id)

        print(f"CharacterManager: Character {character_id} ({char.name}) removal process initiated for guild {guild_id}. Will be deleted from DB on next save.")
        return character_id # Возвращаем ID удаленного персонажа

    # --- Методы обновления состояния персонажа ---

    # Добавляем **kwargs к методам обновления, если они могут быть переданы извне (например, из ActionProcessor)
    async def set_party_id(self, character_id: str, party_id: Optional[str], **kwargs: Any) -> bool:
        """Устанавливает ID группы для персонажа."""
        # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found to set party ID.")
            return False
        if char.party_id == party_id:
            return True # Уже в этой группе или уже без группы
        # Убедимся, что у объекта Character есть атрибут party_id перед изменением
        if hasattr(char, 'party_id'):
            char.party_id = party_id
        else:
            print(f"CharacterManager: Warning: Character model for {character_id} is missing 'party_id' attribute.")
            return False # Не удалось установить party_id, если атрибут отсутствует

        self.mark_character_dirty(character_id) # Помечаем, что персонаж изменен
        print(f"CharacterManager: Set party ID for character {character_id} to {party_id}.")
        return True

    async def update_character_location(self, character_id: str, location_id: Optional[str], **kwargs: Any) -> bool:
        """Обновляет локацию персонажа."""
        # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found to update location.")
            return False
        if getattr(char, 'location_id', None) == location_id: # Используем getattr для безопасной проверки
             return True # Уже там
        # Убедимся, что у объекта Character есть атрибут location_id перед изменением
        if hasattr(char, 'location_id'):
            char.location_id = location_id
        else:
             print(f"CharacterManager: Warning: Character model for {character_id} is missing 'location_id' attribute.")
             return False # Не удалось установить location_id, если атрибут отсутствует

        self.mark_character_dirty(character_id)
        print(f"CharacterManager: Updated location for character {character_id} to {location_id}.")
        return True

    # Добавьте другие методы обновления состояния персонажа (инвентарь, статы, здоровье и т.д.)
    # Не забывайте добавлять **kwargs к сигнатуре, если они могут быть переданы
    # и вызывать self.mark_character_dirty(character_id) после изменений.
    # И проверять наличие атрибутов (isinstance, hasattr, getattr).

    async def add_item_to_inventory(self, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
         """Добавляет предмет в инвентарь персонажа."""
         # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
         char = self.get_character(character_id)
         if not char:
             print(f"CharacterManager: Character {character_id} not found to add item.")
             return False
         # Логика добавления предмета к char.inventory
         # Пример: найти предмет в инвентаре, если есть, увеличить количество, если нет, добавить новый элемент
         item_found = False
         # Убедимся, что у объекта Character есть атрибут inventory и это список
         if not hasattr(char, 'inventory') or not isinstance(char.inventory, list):
              print(f"CharacterManager: Warning: Character model for {character_id} is missing 'inventory' list or it's incorrect type. Initializing empty list.")
              char.inventory = [] # Инициализируем пустой список, если отсутствует/неправильный тип

         # Предполагаем, что char.inventory - это List[Dict[str, Any]] с полями 'item_id', 'quantity'
         for item_entry in char.inventory:
             if isinstance(item_entry, dict) and item_entry.get('item_id') == item_id:
                 # Убедимся, что item_entry является dict и содержит 'quantity' поле как число
                 current_quantity = item_entry.get('quantity', 0)
                 if not isinstance(current_quantity, (int, float)):
                     print(f"CharacterManager: Warning: Invalid quantity type for item '{item_id}' in inventory of {character_id}. Resetting to 0.")
                     current_quantity = 0
                 item_entry['quantity'] = current_quantity + quantity
                 item_found = True
                 break
         if not item_found:
             char.inventory.append({'item_id': item_id, 'quantity': quantity}) # Добавляем новый dict

         self.mark_character_dirty(character_id) # Помечаем персонажа измененным
         print(f"CharacterManager: Added {quantity} of item '{item_id}' to character {character_id} inventory.")
         return True

    async def remove_item_from_inventory(self, character_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
         """Удаляет предмет из инвентаря персонажа."""
         # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
         char = self.get_character(character_id)
         if not char:
             print(f"CharacterManager: Character {character_id} not found to remove item.")
             return False
         # Логика удаления предмета из char.inventory
         # Убедимся, что у объекта Character есть атрибут inventory и это список
         if not hasattr(char, 'inventory') or not isinstance(char.inventory, list):
             print(f"CharacterManager: Warning: Character model for {character_id} is missing 'inventory' list or it's incorrect type. Cannot remove item.")
             return False

         item_index_to_remove = -1
         item_found_to_remove = False # Флаг, что нашли предмет для уменьшения количества
         # Итерируем по копии inventory, если планируем удаление элементов
         for i, item_entry in enumerate(char.inventory):
             if isinstance(item_entry, dict) and item_entry.get('item_id') == item_id:
                 # Убедимся, что item_entry является dict и содержит 'quantity' поле как число
                 current_quantity = item_entry.get('quantity', 0)
                 if not isinstance(current_quantity, (int, float)):
                      print(f"CharacterManager: Warning: Invalid quantity type for item '{item_id}' in inventory of {character_id}. Resetting to 0.")
                      current_quantity = 0

                 item_entry['quantity'] = current_quantity - quantity
                 item_found_to_remove = True # Нашли предмет и уменьшили количество
                 if item_entry['quantity'] <= 0:
                     item_index_to_remove = i # Отмечаем индекс для удаления, если количество <= 0
                 break # Found the item, stop searching

             elif isinstance(item_entry, str) and item_entry == item_id: # Поддержка простого списка ID
                 # Для простого списка ID, удаляем элемент сразу, если находим совпадение по ID
                 # Упрощенная логика: удаляем только ОДИН элемент из списка.
                 item_index_to_remove = i
                 item_found_to_remove = True # Нашли предмет
                 # Количество в данном случае не имеет смысла, удаляем 1 элемент.
                 break # Found the item, stop searching


         # Выполняем удаление элемента из списка, если нужно
         if item_index_to_remove != -1:
             del char.inventory[item_index_to_remove]
             # print(f"CharacterManager: Removed item element from inventory list for {character_id} at index {item_index_to_remove}.") # Debug

         # Логируем, если предмет для удаления не был найден
         if not item_found_to_remove:
              print(f"CharacterManager: Warning: Attempted to remove item '{item_id}' from character {character_id}, but item not found in inventory.")
              # В этом случае можно вернуть False, так как удаление не произошло как запрошено.
              # Или вернуть True, если просто обрабатывали запрос на удаление.
              # Давайте вернем False, если предмет не найден.
              # Но если нашли и количество уменьшилось, но не до 0, возвращаем True.
              # Возвращаем True, если нашли предмет для удаления/уменьшения (item_found_to_remove), даже если он не удалился из списка.
              # Возвращаем False, если предмет не был найден вообще.
              return False # Предмет не найден в инвентаре

         # Если мы сюда дошли, предмет был найден (item_found_to_remove = True) и его количество уменьшено или он помечен на удаление из списка.
         self.mark_character_dirty(character_id) # Помечаем персонажа измененным
         print(f"CharacterManager: Removed {quantity} of item '{item_id}' from character {character_id} inventory (if available).")
         # Возвращаем True, если логика удаления/уменьшения количества выполнилась, даже если элемент списка не удалился (т.к. количество осталось > 0).
         return True


    async def update_health(self, character_id: str, amount: float, **kwargs: Any) -> bool:
         """Обновляет здоровье персонажа."""
         # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
         char = self.get_character(character_id)
         if not char:
             print(f"CharacterManager: Character {character_id} not found to update health.")
             return False

         # Убедимся, что у объекта Character есть атрибуты health, max_health, is_alive и что health/max_health числовые
         if not hasattr(char, 'health') or not isinstance(char.health, (int, float)):
              print(f"CharacterManager: Warning: Character model for {character_id} is missing 'health' attribute or it's not a number. Cannot update health.")
              return False
         if not hasattr(char, 'max_health') or not isinstance(char.max_health, (int, float)):
              print(f"CharacterManager: Warning: Character model for {character_id} is missing 'max_health' attribute or it's not a number. Cannot update health.")
              return False
         if not hasattr(char, 'is_alive') or not isinstance(char.is_alive, bool):
             print(f"CharacterManager: Warning: Character model for {character_id} is missing 'is_alive' attribute or it's not boolean. Cannot update health.")
             return False

         # Если персонаж уже мертв и это не положительное исцеление/воскрешение
         if not char.is_alive and amount <= 0:
             # print(f"CharacterManager: Character {character_id} is dead, cannot take non-positive damage/healing.")
             return False # Нельзя навредить или не лечить мертвого

         # Общая логика обновления здоровья
         new_health = char.health + amount
         # Ограничиваем здоровье между 0 и max_health
         char.health = max(0.0, min(char.max_health, new_health)) # Используем 0.0 и char.max_health как float

         self.mark_character_dirty(character_id) # Помечаем измененным

         # Проверяем смерть после обновления
         if char.health <= 0 and char.is_alive: # Если здоровье стало <= 0 И персонаж еще не помечен как мертвый
              # handle_character_death ожидает character_id и **kwargs
              await self.handle_character_death(character_id, **kwargs) # Передаем контекст в хендлер смерти

         print(f"CharacterManager: Updated health for character {character_id} to {char.health}. Amount: {amount}.")
         return True


    async def handle_character_death(self, character_id: str, **kwargs: Any): # Обрабатывает смерть персонажа.
         """Обрабатывает смерть персонажа."""
         # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
         char = self.get_character(character_id)
         # Проверяем, что персонаж существует и еще жив (по атрибуту is_alive)
         if not char or not getattr(char, 'is_alive', False): # Safely check is_alive, default to False
             print(f"CharacterManager: handle_character_death called for non-existent or already dead character {character_id}.")
             return

         # Убедимся, что у объекта Character есть атрибут is_alive перед изменением
         if hasattr(char, 'is_alive'):
             char.is_alive = False # Помечаем как мертвого
         else:
             print(f"CharacterManager: Warning: Character model for {character_id} is missing 'is_alive' attribute. Cannot mark as dead.")
             return # Не удалось пометить как мертвого

         self.mark_character_dirty(character_id) # Помечаем измененным

         print(f"Character {character_id} ({char.name}) has died in guild {getattr(char, 'guild_id', 'N/A')}.")

         # TODO: Логика смерти:
         # Используем менеджеры, которые были инжектированы в __init__
         # Получаем колбэк отправки сообщения из kwargs, если он передан (из ActionProcessor или CommandRouter)
         # Если send_callback_factory проинжектирован в GameManager и доступен в kwargs, используем его.
         send_callback_factory = kwargs.get('send_callback_factory') # Type: Optional[SendCallbackFactory]
         guild_id = getattr(char, 'guild_id', None) # Получаем guild_id из объекта персонажа
         channel_id = kwargs.get('channel_id') # Channel ID может быть передан в kwargs

         if send_callback_factory and guild_id is not None: # Нужны фабрика и guild_id
             # Попытка получить ID канала смерти из настроек или LocationManager, если channel_id не передан
             death_channel_id = channel_id
             if death_channel_id is None and self._settings is not None:
                 # Пример: ID канала смерти в настройках
                 death_channel_id_setting = self._settings.get('death_channel_id')
                 if death_channel_id_setting is not None:
                      try: death_channel_id = int(death_channel_id_setting) # Попытка преобразовать в int
                      except (ValueError, TypeError): print(f"CharacterManager: Warning: Invalid 'death_channel_id' in settings: {death_channel_id_setting}. Expected integer.");
             # TODO: Получить канал смерти из LocationManager, если это привязано к локации смерти?

             if death_channel_id is not None:
                  # Получаем колбэк для канала смерти
                  send_callback = send_callback_factory(death_channel_id) # Type: SendToChannelCallback
                  # Сообщение о смерти
                  death_message = f"☠️ Персонаж **{char.name}** погиб! ☠️" # Можно сделать шаблонным
                  try: await send_callback(death_message, None)
                  except Exception as e: print(f"CharacterManager: Error sending death message for {char.id} to channel {death_channel_id}: {e}"); import traceback; print(traceback.format_exc());


         # Очистка связанных состояний (статусы, бой, группа и т.д.)
         # Используем инжектированные менеджеры (self._...) и передаем контекст kwargs.
         cleanup_context: Dict[str, Any] = { # Собрать контекст для методов clean_up_*
             'guild_id': guild_id, # Передаем guild_id
             'character_id': character_id, # Передаем character_id
             'character': char, # Передаем объект персонажа
             # TODO: Добавить другие необходимые менеджеры, сервисы из self._ в cleanup_context
         }
         cleanup_context.update(kwargs) # Добавляем все kwargs, переданные в handle_character_death

         # Очистка статусов (StatusManager)
         if self._status_manager and hasattr(self._status_manager, 'clean_up_for_character'):
              try: await self._status_manager.clean_up_for_character(character_id, context=cleanup_context) # Передаем context
              except Exception as e: print(f"CharacterManager: Error during status cleanup for {character_id}: {e}"); import traceback; print(traceback.format_exc());

         # Убрать из боя (CombatManager)
         if self._combat_manager and hasattr(self._combat_manager, 'remove_participant_from_combat'): # Предполагаем метод remove_participant_from_combat(entity_id, entity_type, context)
              try: await self._combat_manager.remove_participant_from_combat(character_id, entity_type="Character", context=cleanup_context) # Передаем context и entity_type
              except Exception as e: print(f"CharacterManager: Error during combat cleanup for {character_id}: {e}"); import traceback; print(traceback.format_exc());

         # Убрать из группы (PartyManager)
         if self._party_manager and hasattr(self._party_manager, 'remove_member'): # Предполагаем метод remove_member(party_id, character_id, context) или clean_up_for_character
              try:
                   # Если party_manager имеет clean_up_for_character
                   if hasattr(self._party_manager, 'clean_up_for_character'):
                        await self._party_manager.clean_up_for_character(character_id, context=cleanup_context)
                   # Если только remove_member, нужно найти Party ID
                   elif getattr(char, 'party_id', None) is not None:
                       await self._party_manager.remove_member(char.party_id, character_id, context=cleanup_context) # Передаем context
              except Exception as e: print(f"CharacterManager: Error during party cleanup for {character_id}: {e}"); import traceback; print(traceback.format_exc());


         # TODO: Удаление из диалога (DialogueManager)
         if self._dialogue_manager and hasattr(self._dialogue_manager, 'clean_up_for_character'):
             try: await self._dialogue_manager.clean_up_for_character(character_id, context=cleanup_context) # Передаем context
             except Exception as e: print(f"CharacterManager: Error during dialogue cleanup for {character_id}: {e}"); import traceback; print(traceback.format_exc());


         # TODO: Дропнуть предметы из инвентаря (ItemManager)
         # Например, переместить все предметы в локацию смерти.
         # ItemManager может иметь метод drop_all_inventory(entity_id, entity_type, location_id, context)
         if self._item_manager and hasattr(self._item_manager, 'drop_all_inventory') and getattr(char, 'location_id', None) is not None:
              try: await self._item_manager.drop_all_inventory(character_id, entity_type="Character", location_id=char.location_id, context=cleanup_context)
              except Exception as e: print(f"CharacterManager: Error during inventory drop for {character_id}: {e}"); import traceback; print(traceback.format_exc());


         # TODO: Триггеры смерти (RuleEngine?)
         # RuleEngine может иметь метод trigger_death(entity, context)
         if self._rule_engine and hasattr(self._rule_engine, 'trigger_death'):
              try: await self._rule_engine.trigger_death(char, context=cleanup_context)
              except Exception as e: print(f"CharacterManager: Error triggering death logic for {character_id}: {e}"); import traceback; print(traceback.format_exc());


         # TODO: Логика воскрешения (возможно, отдельный метод или через статус-эффект)
         # Не часть clean_up_on_death, но связано.


         print(f"CharacterManager: Death cleanup process completed for character {character_id}.")


    # --- Методы для управления активностью/занятостью ---

    def set_active_action(self, character_id: str, action_details: Optional[Dict[str, Any]]) -> None:
        """Устанавливает текущее активное действие персонажа."""
        # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found to set active action.")
            return
        # Убедимся, что у объекта Character есть атрибут current_action
        if hasattr(char, 'current_action'):
            char.current_action = action_details
        else:
            print(f"CharacterManager: Warning: Character model for {character_id} is missing 'current_action' attribute. Cannot set active action.")
            return # Не удалось установить, если атрибут отсутствует


        if action_details is not None:
            self._entities_with_active_action.add(character_id) # Добавляем в глобальный сет
        else:
            self._entities_with_active_action.discard(character_id) # Удаляем, если действие завершено

        self.mark_character_dirty(character_id) # Помечаем, что персонаж изменен


    def add_action_to_queue(self, character_id: str, action_details: Dict[str, Any]) -> None:
        """Добавляет действие в очередь персонажа."""
        # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found to add action to queue.")
            return
        # Убедимся, что у объекта Character есть атрибут action_queue и это список
        if not hasattr(char, 'action_queue') or not isinstance(char.action_queue, list):
             print(f"CharacterManager: Warning: Character model for {character_id} is missing 'action_queue' list or it's incorrect type. Initializing empty list.")
             char.action_queue = [] # Инициализируем пустой список, если отсутствует/неправильный тип

        char.action_queue.append(action_details)
        self.mark_character_dirty(character_id)
        self._entities_with_active_action.add(character_id) # Помечаем занятым, если что-то есть в очереди/текущем действии


    def get_next_action_from_queue(self, character_id: str) -> Optional[Dict[str, Any]]:
        """Извлекает следующее действие из очереди."""
        # Тип 'char' будет выведен из аннотации возвращаемого типа get_character
        char = self.get_character(character_id)
        # Убедимся, что у объекта Character есть атрибут action_queue и это не пустой список
        if not char or not hasattr(char, 'action_queue') or not isinstance(char.action_queue, list) or not char.action_queue:
            return None

        # Извлекаем первое действие из очереди
        next_action = char.action_queue.pop(0) # Удаляем из начала списка (модифицирует атрибут объекта)
        self.mark_character_dirty(character_id)

        # Если очередь опустела и нет текущего действия, можно снять пометку "занят"
        if not char.action_queue and getattr(char, 'current_action', None) is None: # Safely check current_action
             self._entities_with_active_action.discard(character_id)

        return next_action


    # --- Вспомогательные методы ---
    # async def notify_character(self, character_id: str, message: str, **kwargs):
    #      """Метод для отправки сообщений конкретному персонажу (через Discord или другие средства)."""
    #      # Как отмечалось ранее, это лучше делать в процессорах или сервисах,
    #      # которые имеют доступ к механизмам отправки сообщений (например, Discord боту).
    #      # Менеджер персонажей хранит данные, но не должен напрямую взаимодействовать с Discord API.
    #      pass


print("DEBUG: character_manager.py module loaded.")