# bot/game/managers/character_manager.py

from __future__ import annotations
import json
import uuid
import traceback
import asyncio
from typing import Optional, Dict, Any, List, Set

from bot.game.models.character import Character
from bot.database.sqlite_adapter import SqliteAdapter

# TYPE_CHECKING импорты для избежания циклических зависимостей.
# Менеджеры, которые передаются в __init__ CharacterManager,
# должны быть импортированы здесь только для Type Hinting.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.rules.rule_engine import RuleEngine


class CharacterManager:
    """
    Менеджер для управления персонажами игроков.
    Отвечает за создание, получение, обновление персонажей, их персистентность
    и хранение их основного состояния и кешей.
    """
    def __init__(
        self,
        db_adapter: Optional[SqliteAdapter] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional[ItemManager] = None,
        location_manager: Optional[LocationManager] = None,
        rule_engine: Optional[RuleEngine] = None,
        status_manager: Optional[StatusManager] = None,
        party_manager: Optional[PartyManager] = None,
        combat_manager: Optional[CombatManager] = None,
        dialogue_manager: Optional[DialogueManager] = None,
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
        self._characters: Dict[str, Character] = {}
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
        return self._characters.get(char_id) if char_id else None

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
        # Проверка, занята ли его группа
        if char.party_id and self._party_manager and self._party_manager.is_party_busy(char.party_id):
            return True
        return False

    # --- Методы создания ---

    async def create_character( # Переименован из create_character_for_user
        self,
        discord_id: int,
        name: str,
        initial_location_id: Optional[str] = None,
        # Добавьте другие начальные параметры, которые могут быть переданы при создании
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
        if self.get_character_by_discord_id(discord_id):
             print(f"CharacterManager: Character already exists for discord ID {discord_id}")
             return None # Возвращаем None, если персонаж уже есть

        # Проверка на уникальность имени персонажа (если нужно)
        if self.get_character_by_name(name):
             print(f"CharacterManager: Character with name '{name}' already exists.")
             return None # Возвращаем None, если имя уже занято

        # Генерируем уникальный ID (UUID)
        new_id = str(uuid.uuid4())

        # Определяем начальную локацию
        resolved_initial_location_id = initial_location_id
        if resolved_initial_location_id is None and self._location_manager and hasattr(self._location_manager, 'get_default_location_id'):
             try:
                 resolved_initial_location_id = self._location_manager.get_default_location_id()
                 if resolved_initial_location_id:
                      print(f"CharacterManager: Using default location ID: {resolved_initial_location_id}")
             except Exception as e:
                 print(f"CharacterManager: Warning: Could not get default location ID: {e}")
                 traceback.print_exc()


        # Определяем начальные статы (можно использовать RuleEngine, если он передан)
        stats = {'strength': 10, 'dexterity': 10, 'intelligence': 10}
        if self._rule_engine and hasattr(self._rule_engine, 'generate_initial_character_stats'):
            try:
                # Убедитесь, что generate_initial_character_stats существует и работает как ожидается
                # Если он асинхронный: await self._rule_engine.generate_initial_character_stats()
                generated_stats = self._rule_engine.generate_initial_character_stats() # Предполагаем синхронный вызов по умолчанию
                if isinstance(generated_stats, dict):
                     stats = generated_stats
            except Exception:
                traceback.print_exc()


        # Подготавливаем данные для вставки в DB и создания модели
        # Используем data для консистентности и удобства
        data = {
            'id': new_id, # Вставляем сгенерированный ID (UUID)
            'discord_user_id': discord_id,
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
            data['discord_user_id'],
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
            # Это исправляет ошибку 'SqliteAdapter' object has no attribute 'execute_insert'
            await self._db_adapter.execute(sql, db_params)
            print(f"CharacterManager: Character '{name}' with ID {new_id} inserted into DB.")

            # Создаем объект модели Character из данных (данные уже в формате Python объектов)
            char = Character.from_dict(data) # Character.from_dict должен уметь принимать эти данные

            # Добавляем персонажа в кеши
            self._characters[char.id] = char
            if char.discord_user_id is not None:
                 self._discord_to_char_map[char.discord_user_id] = char.id # Используем char.discord_user_id - исправлено ранее

            # Отмечаем как грязный, чтобы он был сохранен при следующем save (хотя только что вставили)
            self._dirty_characters.add(char.id)

            print(f"CharacterManager: Character '{name}' (ID: {char.id}) created and cached.")
            return char # Возвращаем созданный объект Character

        except Exception as e:
            print(f"CharacterManager: Error creating character '{name}' for discord ID {discord_user_id}: {e}")
            traceback.print_exc()
            raise # Перебрасываем исключение, чтобы CommandRouter мог его поймать и сообщить пользователю


    # --- Методы сохранения/загрузки ---

    async def save_all_characters(self) -> None:
        """Сохраняет все измененные или удаленные персонажи в базу данных."""
        if self._db_adapter is None:
            print("CharacterManager: Warning: Cannot save characters, DB adapter missing.")
            return
        if not self._dirty_characters and not self._deleted_characters_ids:
            # print("CharacterManager: No dirty or deleted characters to save.") # Можно закомментировать, чтобы не спамило
            return

        print(f"CharacterManager: Saving {len(self._dirty_characters)} dirty, {len(self._deleted_characters_ids)} deleted characters...")

        # Удалить помеченные для удаления персонажи
        if self._deleted_characters_ids:
            ids_to_delete = list(self._deleted_characters_ids)
            placeholders = ','.join(['?'] * len(ids_to_delete))
            delete_sql = f"DELETE FROM characters WHERE id IN ({placeholders})"
            try:
                await self._db_adapter.execute(delete_sql, tuple(ids_to_delete))
                print(f"CharacterManager: Deleted {len(ids_to_delete)} characters from DB.")
                self._deleted_characters_ids.clear() # Очищаем список после успешного удаления
            except Exception as e:
                print(f"CharacterManager: Error deleting characters: {e}")
                traceback.print_exc()
                # Не очищаем _deleted_characters_ids, чтобы попробовать удалить снова при следующей сохранке

        # Обновить или вставить измененные персонажи
        characters_to_save = [self._characters[cid] for cid in list(self._dirty_characters) if cid in self._characters]
        if characters_to_save:
             print(f"CharacterManager: Upserting {len(characters_to_save)} characters...")
             # INSERT OR REPLACE SQL для обновления существующих или вставки новых
             upsert_sql = '''
             INSERT OR REPLACE INTO characters
             (id, discord_user_id, name, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                     print(f"CharacterManager: Error preparing data for character {char.id} ({char.name}): {e}")
                     traceback.print_exc()
                     # Этот персонаж не будет сохранен в этой итерации - он останется в _dirty_characters
                     # чтобы попробовать сохранить его снова

             if data_to_upsert:
                 try:
                     # Используем execute_many для пакетной вставки/обновления
                     await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                     print(f"CharacterManager: Successfully upserted {len(data_to_upsert)} characters.")
                     # Только если execute_many успешен, очищаем список "грязных"
                     self._dirty_characters.clear()
                 except Exception as e:
                     print(f"CharacterManager: Error during batch upsert: {e}")
                     traceback.print_exc()
                     # Не очищаем _dirty_characters, чтобы попробовать сохранить снова


    async def load_all_characters(self) -> None:
        """Загружает все персонажи из базы данных в кеш."""
        if self._db_adapter is None:
            print("CharacterManager: Warning: Cannot load characters, DB adapter missing.")
            return

        print("CharacterManager: Loading all characters from DB...")
        # Очищаем кеши перед загрузкой
        self._characters.clear()
        self._discord_to_char_map.clear()
        self._entities_with_active_action.clear()
        self._dirty_characters.clear() # Очищаем, так как все из DB считается чистым
        self._deleted_characters_ids.clear() # Очищаем

        rows = [] # Инициализируем список для строк
        try:
            # ВЫПОЛНЯЕМ fetchall ОДИН РАЗ
            rows = await self._db_adapter.fetchall(
                'SELECT id, discord_user_id, name, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects FROM characters'
            )
            print(f"CharacterManager: Found {len(rows)} characters in DB.")

        except Exception as e:
            # Если произошла ошибка при самом выполнении запроса fetchall
            print(f"CharacterManager: ❌ CRITICAL ERROR executing DB fetchall: {e}")
            traceback.print_exc()
            # В этом случае rows будет пустым списком, и мы просто выйдем из метода после обработки ошибки.
            # Очистка кешей уже была сделана выше.
            return # Прерываем выполнение метода при критической ошибке запроса

        # Теперь обрабатываем каждую строку ВНУТРИ ЦИКЛА
        loaded_count = 0
        for row in rows:
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


                # Создаем объект модели Character
                char = Character.from_dict(data) # Character.from_dict должен уметь принимать эти данные

                # Добавляем в кеш по ID
                self._characters[char.id] = char

                # Добавляем в кеш по Discord ID, только если discord_user_id есть
                if char.discord_user_id is not None:
                    # Исправленная строка из предыдущего ответа
                    self._discord_to_char_map[char.discord_user_id] = char.id

                # Если у персонажа есть активное действие или очередь, помечаем его как занятого
                if char.current_action is not None or char.action_queue:
                    self._entities_with_active_action.add(char.id)

                loaded_count += 1 # Увеличиваем счетчик успешно загруженных

            except json.JSONDecodeError:
                # Ошибка парсинга JSON в ОДНОЙ строке
                print(f"CharacterManager: Error decoding JSON for character row (ID: {data.get('id', 'N/A')}): {traceback.format_exc()}. Skipping this row.")
                # traceback.print_exc() # Печатаем подробный traceback для ошибки JSON
                # Продолжаем цикл для других строк
            except Exception as e:
                # Другая ошибка при обработке ОДНОЙ строки
                print(f"CharacterManager: Error processing character row (ID: {data.get('id', 'N/A')}): {e}. Skipping this row.")
                traceback.print_exc()
                # Продолжаем цикл для других строк

        print(f"CharacterManager: Successfully loaded {loaded_count} characters into cache.")
        if loaded_count < len(rows):
             print(f"CharacterManager: Note: Failed to load {len(rows) - loaded_count} characters due to errors.")


    def mark_character_dirty(self, character_id: str) -> None:
         """Помечает персонажа как измененного для последующего сохранения."""
         if character_id in self._characters:
              self._dirty_characters.add(character_id)
         else:
             print(f"CharacterManager: Warning: Attempted to mark non-existent character {character_id} as dirty.")


    def mark_character_deleted(self, character_id: str) -> None:
        """Помечает персонажа как удаленного."""
        if character_id in self._characters:
             # Удаляем из кеша сразу
             char = self._characters.pop(character_id)
             if char.discord_user_id is not None and self._discord_to_char_map.get(char.discord_user_id) == character_id:
                 self._discord_to_char_map.pop(char.discord_user_id)
             self._entities_with_active_action.discard(character_id)
             self._dirty_characters.discard(character_id) # Если был грязный, то теперь удален
             self._deleted_characters_ids.add(character_id) # Помечаем для удаления из DB
             print(f"CharacterManager: Character {character_id} marked for deletion.")
        elif character_id in self._deleted_characters_ids:
             print(f"CharacterManager: Character {character_id} already marked for deletion.")
        else:
             print(f"CharacterManager: Warning: Attempted to mark non-existent character {character_id} as deleted.")


    # --- Метод удаления (публичный) ---
    async def remove_character(self, character_id: str) -> Optional[str]: # Убрал **kwargs из сигнатуры, если они не используются
        """
        Удаляет персонажа (помечает для удаления из DB) и выполняет очистку
        связанных сущностей (предметы, статусы, группа, бой, диалог).
        """
        char = self.get_character(character_id)
        if not char:
            print(f"CharacterManager: Character {character_id} not found for removal.")
            return None

        print(f"CharacterManager: Removing character {character_id} ({char.name})...")

        # Cleanup via managers (используем менеджеры, переданные в __init__)
        # Убедитесь, что методы clean_up_* существуют в соответствующих менеджерах
        # и что они принимают character_id.
        try:
            if self._item_manager and hasattr(self._item_manager, 'clean_up_for_character'):
                await self._item_manager.clean_up_for_character(character_id)
            if self._status_manager and hasattr(self._status_manager, 'clean_up_for_character'):
                 await self._status_manager.clean_up_for_character(character_id)
            if self._party_manager and char.party_id and hasattr(self._party_manager, 'clean_up_for_character'):
                 # Возможно, party_manager должен уметь чистить по character_id без party_id
                 # или remove_member(char.party_id, character_id) более подходящий метод
                 await self._party_manager.clean_up_for_character(character_id)
            if self._combat_manager and hasattr(self._combat_manager, 'clean_up_for_character'):
                 await self._combat_manager.clean_up_for_character(character_id)
            if self._dialogue_manager and hasattr(self._dialogue_manager, 'clean_up_for_character'):
                 await self._dialogue_manager.clean_up_for_character(character_id)
            print(f"CharacterManager: Cleanup initiated for character {character_id}.")
        except Exception as e:
             print(f"CharacterManager: Error during cleanup for character {character_id}: {e}")
             traceback.print_exc()


        # Отмечаем персонажа как удаленного (удалит из кеша и добавит в список на удаление из DB)
        self.mark_character_deleted(character_id)

        print(f"CharacterManager: Character {character_id} ({char.name}) removal process initiated.")
        return character_id # Возвращаем ID удаленного персонажа

    # --- Методы обновления состояния персонажа ---

    async def set_party_id(self, character_id: str, party_id: Optional[str]) -> bool:
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

    async def update_character_location(self, character_id: str, location_id: Optional[str]) -> bool:
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
    # Например:
    # async def add_item_to_inventory(self, character_id: str, item_id: str, quantity: int = 1) -> bool:
    #      char = self.get_character(character_id)
    #      if not char: return False
    #      # Logic to add item to char.inventory (list of item dictionaries or similar)
    #      # Mark character dirty
    #      self.mark_character_dirty(character_id)
    #      return True
    # async def remove_item_from_inventory(self, character_id: str, item_id: str, quantity: int = 1) -> bool:
    #      char = self.get_character(character_id)
    #      if not char: return False
    #      # Logic to remove item from char.inventory
    #      # Mark character dirty
    #      self.mark_character_dirty(character_id)
    #      return True
    # async def update_health(self, character_id: str, amount: float) -> bool:
    #      char = self.get_character(character_id)
    #      if not char or not char.is_alive: return False
    #      char.health = max(0, min(char.max_health, char.health + amount))
    #      self.mark_character_dirty(character_id)
    #      if char.health <= 0:
    #           await self.handle_character_death(character_id) # Пример вызова хендлера смерти
    #      return True
    # async def handle_character_death(self, character_id: str):
    #      char = self.get_character(character_id)
    #      if not char: return
    #      char.is_alive = False
    #      self.mark_character_dirty(character_id)
    #      print(f"Character {character_id} ({char.name}) has died.")
    #      # Логика смерти: дропнуть предметы, уведомить партию/GM и т.д.
    #      # Возможно, делегировать CharacterActionProcessor или CombatManager


    # --- Вспомогательные методы ---
    # async def notify_character(self, character_id: str, message: str, **kwargs):
    #      """Метод для отправки сообщений конкретному персонажу (через Discord или другие средства)."""
    #      # Этот метод, как отмечалось ранее, лучше реализовать в процессорах,
    #      # которые имеют доступ к Discord колбэкам.
    #      pass
