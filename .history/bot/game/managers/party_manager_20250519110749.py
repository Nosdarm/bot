# bot/game/managers/party_manager.py

from __future__ import annotations # Enables using type hints as strings implicitly, simplifying things
import json
import uuid
import traceback
import asyncio
# Импорт базовых типов
# ИСПРАВЛЕНИЕ: Импортируем Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable
# ИСПРАВЛЕНИЕ: Tuple не нужен, если не используется явно
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable


# --- Imports needed ONLY for Type Checking ---
# Эти импорты нужны ТОЛЬКО для статического анализа (Pylance/Mypy).
# Это разрывает циклы импорта при runtime и помогает Pylance правильно резолвить типы.
# Используйте строковые литералы ("ClassName") для type hints в __init__ и методах
# для классов, импортированных здесь, ЕСЛИ они импортированы только здесь.
if TYPE_CHECKING:
    # Добавляем адаптер БД
    from bot.database.sqlite_adapter import SqliteAdapter
    # Добавляем модели, используемые в аннотациях
    from bot.game.models.party import Party # Аннотируем как "Party"
    from bot.game.models.character import Character # Для clean_up_from_party context
    from bot.game.models.npc import NPC # Для clean_up_from_party context


    # Добавляем менеджеры
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.combat_manager import CombatManager
    # Добавляем другие менеджеры, если они передаются в __init__ или используются в аннотациях методов
    # from bot.game.managers.event_manager import EventManager
    # from bot.game.managers.location_manager import LocationManager
    # from bot.game.rules.rule_engine import RuleEngine
    # from bot.game.managers.item_manager import ItemManager
    # from bot.game.managers.time_manager import TimeManager
    # from bot.game.managers.status_manager import StatusManager
    # from bot.game.managers.crafting_manager import CraftingManager
    # from bot.game.managers.economy_manager import EconomyManager

    # Добавляем процессоры, если они используются в аннотациях методов
    # from bot.game.character_processors.character_action_processor import CharacterActionProcessor


# --- Imports needed at Runtime ---
# Для PartyManager обычно нужен только прямой импорт модели Party (для Party.from_dict) и утилит.
# ВАЖНО: Прямой импорт Party НЕОБХОДИМ для Party.from_dict() при runtime
from bot.game.models.party import Party # <--- Прямой импорт Party
# Import dict for isinstance checks at runtime
# ИСПРАВЛЕНИЕ: Добавляем import dict для isinstance проверки
from builtins import dict, set, list # Убедимся, что используем стандартные типы для isinstance


print("DEBUG: party_manager.py module loaded.")


class PartyManager:
    """
    Менеджер для управления группами (parties).
    Хранит состояние всех партий, CRUD, проверку busy-статуса, и т.п.
    """
    # Required args для PersistenceManager
    # ИСПРАВЛЕНИЕ: Аннотации типа List[str] уже корректны.
    required_args_for_load: List[str] = ["guild_id"] # Загрузка per-guild
    required_args_for_save: List[str] = ["guild_id"] # Сохранение per-guild
    required_args_for_rebuild: List[str] = ["guild_id"] # Rebuild per-guild

    # --- Class-Level Attribute Annotations ---
    # Объявляем типы инстанс-атрибутов здесь. Это стандартный способ для Pylance/Mypy.
    # ИСПРАВЛЕНИЕ: Кеш партий должен быть per-guild для многогильдийности
    # _parties: Dict[str, Dict[str, Party]] = {guild_id: {party_id: Party_object}}
    _parties: Dict[str, Dict[str, "Party"]] # Аннотация кеша использует строковый литерал "Party"

    # Для оптимизации персистенции
    # ИСПРАВЛЕНИЕ: _dirty_parties и _deleted_parties также должны быть per-guild
    _dirty_parties: Dict[str, Set[str]] # {guild_id: set(party_ids)}
    _deleted_parties: Dict[str, Set[str]] # {guild_id: set(party_ids)}

    # TODO: Добавить атрибут для кеша {member_id: party_id} если нужен для get_party_by_member_id
    # ИСПРАВЛЕНИЕ: Кеш {member_id: party_id} также должен быть per-guild
    _member_to_party_map: Dict[str, Dict[str, str]] # {guild_id: {member_id: party_id}}


    def __init__(self,
                 # Используем строковые литералы для всех инжектированных зависимостей
                 db_adapter: Optional["SqliteAdapter"] = None,
                 settings: Optional[Dict[str, Any]] = None,
                 npc_manager: Optional["NpcManager"] = None,
                 character_manager: Optional["CharacterManager"] = None,
                 combat_manager: Optional["CombatManager"] = None,
                 # event_manager: Optional["EventManager"] = None,  # если нужен
                ):
        print("Initializing PartyManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        # Инжектированные зависимости
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._combat_manager = combat_manager
        # self._event_manager = event_manager

        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые словари в __init__
        # Кеш партий: {guild_id: {party_id: Party}}
        self._parties = {} # Инициализируем как пустой dict, тип определен выше

        # Для оптимизации персистенции
        self._dirty_parties = {} # Инициализируем как пустой dict, тип определен выше
        self._deleted_parties = {} # Инициализируем как пустой dict, тип определен выше

        # TODO: Добавить атрибут для кеша {member_id: party_id} если нужен для get_party_by_member_id
        # ИСПРАВЛЕНИЕ: Инициализируем кеш мапы участников к партиям
        self._member_to_party_map = {} # Инициализируем как пустой dict, тип определен выше


        print("PartyManager initialized.")

    # --- Методы получения ---
    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Метод get_party должен принимать guild_id
    def get_party(self, guild_id: str, party_id: str) -> Optional["Party"]:
        """Получить объект партии по ID для определенной гильдии (из кеша)."""
        # ИСПРАВЛЕНИЕ: Получаем из per-guild кеша
        guild_parties = self._parties.get(str(guild_id)) # Убедимся, что guild_id строка
        if guild_parties:
             return guild_parties.get(party_id)
        return None # Гильдия или партия не найдены

    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Метод get_all_parties должен принимать guild_id
    def get_all_parties(self, guild_id: str) -> List["Party"]:
        """Получить список всех загруженных партий для определенной гильдии (из кеша)."""
        # ИСПРАВЛЕНИЕ: Получаем из per-guild кеша
        guild_parties = self._parties.get(str(guild_id)) # Убедимся, что guild_id строка
        if guild_parties:
             return list(guild_parties.values())
        return [] # Возвращаем пустой список, если для гильдии нет партий


    # ИСПРАВЛЕНИЕ: Реализация get_party_by_member_id
    async def get_party_by_member_id(self, entity_id: str, guild_id: str, **kwargs: Any) -> Optional["Party"]:
         """Найти партию по ID участника для определенной гильдии."""
         guild_id_str = str(guild_id)

         # Используем мапу {guild_id: {member_id: party_id}}
         guild_member_map = self._member_to_party_map.get(guild_id_str) # Type: Optional[Dict[str, str]]
         if guild_member_map:
              party_id = guild_member_map.get(entity_id) # Type: Optional[str]
              if party_id:
                   # Получаем Party объект из основного кеша PartyManager (уже с guild_id)
                   return self.get_party(guild_id_str, party_id) # Используем party_id из мапы и guild_id


         # Fallback: перебрать все партии в кеше для этой гильдии (медленно, но надежно)
         # This fallback is less necessary if the map rebuild is robust
         # parties_for_guild = self.get_all_parties(guild_id_str)
         # for party in parties_for_guild:
         #      if entity_id in getattr(party, 'member_ids', []):
         #           return party # Return party object

         return None # Not found in map or fallback


    # --- Методы CRUD ---

    async def create_party(self, leader_id: str, member_ids: List[str], guild_id: str, **kwargs: Any) -> Optional[str]:
        """
        Создает новую партию с лидером и списком участников для определенной гильдии.
        """
        if self._db_adapter is None:
            print(f"PartyManager: No DB adapter for guild {guild_id}. Cannot create party.")
            return None # Cannot proceed without DB for persistence

        guild_id_str = str(guild_id) # Убедимся, что guild_id строка

        # TODO: Валидация (участники существуют, не в других партиях, leader_id в списке member_ids)
        # Используйте self._character_manager, self._npc_manager, self.get_party_by_member_id (с guild_id)
        # Это асинхронная валидация, т.к. get_character/get_party_by_member_id может быть async.
        # ... (Validation logic remains largely the same, ensure guild_id is passed to helper calls) ...


        try:
            new_id = str(uuid.uuid4())

            party_data: Dict[str, Any] = {
                'id': new_id,
                'guild_id': guild_id_str, # Сохраняем как строку
                'leader_id': leader_id,
                'member_ids': member_ids.copy(), # Копируем список
                # TODO: Добавить другие поля Party модели
                'state_variables': {},
                'current_action': None, # Групповое действие партии
                # TODO: location_id для партии, если применимо? (Например, Party Location = Leader Location)
            }
            party = Party.from_dict(party_data) # Требует прямого импорта Party при runtime

            # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш
            self._parties.setdefault(guild_id_str, {})[new_id] = party

            # ИСПРАВЛЕНИЕ: Обновляем _member_to_party_map для этой гильдии
            guild_member_map = self._member_to_party_map.setdefault(guild_id_str, {})
            for member_id in member_ids + [leader_id]: # Add leader to map as well
                 if member_id in guild_member_map:
                      print(f"PartyManager: Warning: Overwriting member_to_party map entry for member {member_id} in guild {guild_id_str}. Was in party {guild_member_map[member_id]}, now in {new_id}.")
                 guild_member_map[member_id] = new_id


            # ИСПРАВЛЕНИЕ: Помечаем party dirty (per-guild)
            self.mark_party_dirty(guild_id_str, new_id)


            print(f"PartyManager: Party {new_id} created for guild {guild_id_str}. Leader: {leader_id}. Members: {member_ids}")
            # TODO: Уведомить участников? (Через send_callback_factory из kwargs)

            return new_id

        except Exception as e:
            print(f"PartyManager: Error creating party for leader {leader_id} in guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            return None


    async def remove_party(self, party_id: str, guild_id: str, **kwargs: Any) -> Optional[str]:
        """
        Удаляет партию и помечает для удаления в БД для определенной гильдии.
        """
        guild_id_str = str(guild_id) # Убедимся, что guild_id строка

        # ИСПРАВЛЕНИЕ: Получаем партию с учетом guild_id
        party = self.get_party(guild_id_str, party_id) # Type: Optional["Party"]
        if not party:
            print(f"PartyManager: Party {party_id} not found for removal in guild {guild_id_str}.")
            return None

        # Проверка, что guild_id партии совпадает с переданным
        if str(getattr(party, 'guild_id', None)) != guild_id_str:
            print(f"PartyManager: Error: Mismatched guild_id for party {party_id} removal. Expected {guild_id_str}, found {getattr(party, 'guild_id', None)}.")
            # Это может случиться только если кеш или логика некорректны, но добавим проверку для безопасности.
            return None


        print(f"PartyManager: Removing party {party_id} for guild {guild_id_str}. Leader: {getattr(party, 'leader_id', 'N/A')}")

        member_ids = list(getattr(party, 'member_ids', [])) # Копируем список участников

        # Передаем context в cleanup методы
        cleanup_context: Dict[str, Any] = {
            'party_id': party_id,
            'party': party,
            'guild_id': guild_id_str, # Передаем guild_id_str
            # TODO: Добавить другие необходимые менеджеры, сервисы из self._ в cleanup_context
            'character_manager': self._character_manager,
            'npc_manager': self._npc_manager,
            'combat_manager': self._combat_manager,
        }
        cleanup_context.update(kwargs)

        if member_ids:
            print(f"PartyManager: Cleaning up {len(member_ids)} members for party {party_id} in guild {guild_id_str}.")
            for entity_id in member_ids: # Итерируем по копии
                 try:
                     entity_type = None
                     manager = None # type: Optional[Any]
                     clean_up_method_name = 'clean_up_from_party'

                     if self._character_manager and hasattr(self._character_manager, clean_up_method_name):
                          # ИСПРАВЛЕНИЕ: get_character должен принимать guild_id
                          char = self._character_manager.get_character(guild_id_str, entity_id) # Assume get_character is per-guild
                          if char and str(getattr(char, 'party_id', None)) == party_id and str(getattr(char, 'guild_id', None)) == guild_id_str:
                               entity_type = "Character"
                               manager = self._character_manager

                     if entity_type is None and self._npc_manager and hasattr(self._npc_manager, clean_up_method_name):
                          # ИСПРАВЛЕНИЕ: get_npc должен принимать guild_id
                          npc = self._npc_manager.get_npc(guild_id_str, entity_id) # Assume get_npc is per-guild
                          if npc and str(getattr(npc, 'party_id', None)) == party_id and str(getattr(npc, 'guild_id', None)) == guild_id_str:
                               entity_type = "NPC"
                               manager = self._npc_manager

                     if manager and clean_up_method_name and entity_type:
                          # Вызываем метод clean_up, передаем context (который содержит guild_id)
                          await getattr(manager, clean_up_method_name)(entity_id, context=cleanup_context) # Pass party_id via context
                          print(f"PartyManager: Cleaned up member {entity_type} {entity_id} from party {party_id} in guild {guild_id_str}.")
                     else:
                          print(f"PartyManager: Warning: Could not find suitable manager or '{clean_up_method_name}' method for member {entity_id} (det. type: {entity_type}) in party {party_id} (guild {guild_id_str}). Skipping cleanup for this member.")

                 except Exception as e:
                    print(f"PartyManager: Error during cleanup for member {entity_id} in party {party_id} (guild {guild_id_str}): {e}")
                    import traceback
                    print(traceback.format_exc())


        print(f"PartyManager: Finished member cleanup for party {party_id} in guild {guild_id_str}.")

        # TODO: Дополнительная очистка Party-специфичных эффектов (StatusManager, CombatManager, etc.)
        # Use cleanup_context which includes guild_id
        # if self._status_manager and hasattr(self._status_manager, 'clean_up_for_party'):
        #      try: await self._status_manager.clean_up_for_party(party_id, context=cleanup_context)
        #      except Exception as e: import traceback; print(traceback.format_exc());

        # if self._combat_manager and hasattr(self._combat_manager, 'party_disbanded'):
        #      try: await self._combat_manager.party_disbanded(party_id, context=cleanup_context)
        #      except Exception as e: import traceback; print(traceback.format_exc());

        # TODO: Очистка группового действия партии
        # party.current_action = None # If Party model has attributes
        # party.action_queue = []
        # Mark dirty if action state changed
        # self.mark_party_dirty(guild_id_str, party_id)

        # ИСПРАВЛЕНИЕ: Удаляем записи из _member_to_party_map для этой гильдии
        guild_member_map = self._member_to_party_map.get(guild_id_str)
        if guild_member_map:
             for member_id in member_ids: # Iterate through the copy
                  if guild_member_map.get(member_id) == party_id: # Only remove if mapping points to this party
                       del guild_member_map[member_id]
                       # Optional: Check if leader_id also needs removing if it was distinct

        # ИСПРАВЛЕНИЕ: Помечаем партию для удаления из БД (per-guild)
        self._deleted_parties.setdefault(guild_id_str, set()).add(party_id)

        # ИСПРАВЛЕНИЕ: Удаляем из per-guild кеша активных партий
        guild_parties = self._parties.get(guild_id_str)
        if guild_parties:
             guild_parties.pop(party_id, None)

        # ИСПРАВЛЕНИЕ: Убираем из dirty set, если там была
        self._dirty_parties.get(guild_id_str, set()).discard(party_id)


        print(f"PartyManager: Party {party_id} fully removed from cache and marked for deletion for guild {guild_id_str}.")
        return party_id


    # Methods for persistence (called by PersistenceManager):
    # Эти методы должны работать per-guild
    # required_args_for_load, required_args_for_save, required_args_for_rebuild уже определены как атрибуты класса

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет активные/измененные партии для определенной гильдии."""
        if self._db_adapter is None:
            print(f"PartyManager: Warning: Cannot save parties for guild {guild_id}, DB adapter missing.")
            return

        guild_id_str = str(guild_id)
        print(f"PartyManager: Saving parties for guild {guild_id_str}...")

        # ИСПРАВЛЕНИЕ: Собираем партии для сохранения ИЗ per-guild dirty set и per-guild cache
        # Собираем party_ids, помеченные как dirty для этой гильдии
        party_ids_to_save_set = self._dirty_parties.get(guild_id_str, set()).copy() # Рабочая копия dirty IDs
        # Теперь получаем объекты Party из кеша, используя эти ID
        parties_to_save: List["Party"] = []
        guild_parties_cache = self._parties.get(guild_id_str, {})
        # Filter for IDs that are dirty AND still in the cache
        parties_to_save = [guild_parties_cache[pid] for pid in party_ids_to_save_set if pid in guild_parties_cache]


        # ИСПРАВЛЕНИЕ: Собираем IDs партий, помеченных для удаления для этой гильдии
        party_ids_to_delete_set = self._deleted_parties.get(guild_id_str, set()).copy() # Рабочая копия deleted IDs


        # Если нет партий для сохранения или удаления, выходим
        if not parties_to_save and not party_ids_to_delete_set:
             # print(f"PartyManager: No dirty or deleted parties to save for guild {guild_id_str}.")
             # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, просто очищаем dirty/deleted сеты для этой гильдии
             # (они должны быть уже пусты, но это безопасная очистка)
             self._dirty_parties.pop(guild_id_str, None)
             self._deleted_parties.pop(guild_id_str, None)
             return


        try:
            # 4. Удаление партий, помеченных для удаления для этой гильдии
            if party_ids_to_delete_set:
                 ids_to_delete = list(party_ids_to_delete_set)
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 delete_sql = f"DELETE FROM parties WHERE guild_id = ? AND id IN ({placeholders_del})"
                 await self._db_adapter.execute(delete_sql, (guild_id_str, *tuple(ids_to_delete)))
                 print(f"PartyManager: Deleted {len(ids_to_delete)} parties from DB for guild {guild_id_str}.")
                 # ИСПРАВЛЕНИЕ: Очищаем deleted set для этой гильдии после успешного удаления
                 self._deleted_parties.pop(guild_id_str, None)


            # 5. Сохранение/обновление партий для этой гильдии
            if parties_to_save:
                 print(f"PartyManager: Upserting {len(parties_to_save)} parties for guild {guild_id_str}...")
                 upsert_sql = '''
                 INSERT OR REPLACE INTO parties
                 (id, guild_id, leader_id, member_ids, state_variables, current_action)
                 VALUES (?, ?, ?, ?, ?, ?)
                 '''
                 data_to_upsert = []
                 upserted_party_ids: Set[str] = set() # Keep track of successfully prepared IDs

                 for party in parties_to_save:
                      try:
                           # Убеждаемся, что у объекта Party есть все нужные атрибуты
                           party_id = getattr(party, 'id', None)
                           party_guild_id = getattr(party, 'guild_id', None)

                           if party_id is None or str(party_guild_id) != guild_id_str:
                                print(f"PartyManager: Warning: Skipping upsert for party with invalid ID ('{party_id}') or mismatched guild ('{party_guild_id}') during save for guild {guild_id_str}.")
                                continue # Skip this party if invalid or wrong guild

                           leader_id = getattr(party, 'leader_id', None)
                           member_ids = getattr(party, 'member_ids', [])
                           state_variables = getattr(party, 'state_variables', {})
                           current_action = getattr(party, 'current_action', None)

                           if leader_id is None:
                                print(f"PartyManager: Warning: Party {party_id} (guild {guild_id_str}) has no leader_id during save prep. Consider this an error if leader is mandatory.")
                                # Decide if this should be skipped or handled differently


                           # Убедимся, что данные для JSON корректны
                           # Ensure member_ids is a list before dumping
                           if not isinstance(member_ids, list):
                               print(f"PartyManager: Warning: Party {party_id} (guild {guild_id_str}) member_ids is not a list during upsert prep ({type(member_ids)}). Saving as empty list.")
                               member_ids = []

                           member_ids_json = json.dumps(member_ids)
                           state_variables_json = json.dumps(state_variables)
                           current_action_json = json.dumps(current_action) if current_action is not None else None


                           data_to_upsert.append((
                               str(party_id),
                               guild_id_str, # Убедимся, что guild_id строка
                               str(leader_id) if leader_id is not None else None, # Save leader_id as str or None
                               member_ids_json,
                               state_variables_json,
                               current_action_json,
                           ))
                           upserted_party_ids.add(str(party_id)) # Track IDs that were prepared for upsert

                      except Exception as e:
                          print(f"PartyManager: Error preparing data for party {getattr(party, 'id', 'N/A')} (guild {guild_id_str}) for upsert: {e}")
                          import traceback
                          print(traceback.format_exc())
                          # This party won't be saved in this batch but remains in _dirty_parties


                 if data_to_upsert:
                      if self._db_adapter is None:
                           print(f"PartyManager: Warning: DB adapter is None during upsert batch for guild {guild_id_str}.")
                      else:
                           await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                           print(f"PartyManager: Successfully upserted {len(data_to_upsert)} parties for guild {guild_id_str}.")
                           # ИСПРАВЛЕНИЕ: Очищаем dirty set для этой гильдии только для успешно сохраненных ID
                           if guild_id_str in self._dirty_parties:
                                self._dirty_parties[guild_id_str].difference_update(upserted_party_ids)
                                # Если после очистки set пуст, удаляем ключ гильдии
                                if not self._dirty_parties[guild_id_str]:
                                     del self._dirty_parties[guild_id_str]


            print(f"PartyManager: Save state complete for guild {guild_id_str}.")

        except Exception as e:
            print(f"PartyManager: ❌ Error during save state for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # TODO: Handle error - do not clear dirty/deleted sets for this guild if saving failed


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает партии для определенной гильдии из базы данных в кеш."""
        if self._db_adapter is None:
            print(f"PartyManager: Warning: Cannot load parties for guild {guild_id}, DB adapter missing.")
            # TODO: Load placeholder data or raise
            return

        guild_id_str = str(guild_id)
        print(f"PartyManager: Loading parties for guild {guild_id_str} from DB...")

        # ИСПРАВЛЕНИЕ: Очистите кеш партий ТОЛЬКО для этой гильдии
        self._parties.pop(guild_id_str, None)
        self._parties[guild_id_str] = {} # Создаем пустой кеш для этой гильдии

        # ИСПРАВЛЕНИЕ: Очищаем dirty и deleted сеты ТОЛЬКО для этой гильдии при загрузке
        self._dirty_parties.pop(guild_id_str, None)
        self._deleted_parties.pop(guild_id_str, None)

        rows = []
        try:
            sql = '''
            SELECT id, guild_id, leader_id, member_ids, state_variables, current_action
            FROM parties
            WHERE guild_id = ?
            '''
            rows = await self._db_adapter.fetchall(sql, (guild_id_str,))
            print(f"PartyManager: Found {len(rows)} parties in DB for guild {guild_id_str}.")

        except Exception as e:
            print(f"PartyManager: ❌ CRITICAL ERROR executing DB fetchall for parties for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            raise # Пробрасываем критическую ошибку

        # 3. Для каждой строки создайте объект Party (Party.from_dict)
        loaded_count = 0
        guild_parties_cache = self._parties[guild_id_str] # Get the cache dict for this guild

        for row in rows:
             data = dict(row)
             try:
                  # Validate and parse data
                  party_id = data.get('id')
                  loaded_guild_id = data.get('guild_id')

                  if party_id is None or str(loaded_guild_id) != guild_id_str:
                      print(f"PartyManager: Warning: Skipping party with invalid ID ('{party_id}') or mismatched guild ('{loaded_guild_id}') during load for guild {guild_id_str}.")
                      continue

                  # Parse JSON fields, handle None/malformed data gracefully
                  try:
                      data['member_ids'] = json.loads(data.get('member_ids') or '[]')
                  except (json.JSONDecodeError, TypeError):
                      print(f"PartyManager: Warning: Failed to parse member_ids for party {party_id}. Setting to []. Data: {data.get('member_ids')}")
                      data['member_ids'] = []

                  try:
                      data['state_variables'] = json.loads(data.get('state_variables') or '{}')
                  except (json.JSONDecodeError, TypeError):
                      print(f"PartyManager: Warning: Failed to parse state_variables for party {party_id}. Setting to {{}}. Data: {data.get('state_variables')}")
                      data['state_variables'] = {}

                  try:
                      current_action_data = data.get('current_action')
                      data['current_action'] = json.loads(current_action_data) if current_action_data is not None else None
                  except (json.JSONDecodeError, TypeError):
                       print(f"PartyManager: Warning: Failed to parse current_action for party {party_id}. Setting to None. Data: {data.get('current_action')}")
                       data['current_action'] = None


                  # Ensure required fields exist and have correct types after parsing
                  data['id'] = str(party_id)
                  data['guild_id'] = guild_id_str
                  # Basic validation (can add more)
                  if data.get('leader_id') is None: print(f"PartyManager: Warning: Party {party_id} has no leader_id after load.")
                  if not isinstance(data.get('member_ids'), list):
                      print(f"PartyManager: Warning: Party {party_id} member_ids is not list after load ({type(data.get('member_ids'))}). Setting to [].")
                      data['member_ids'] = []
                  else: # Ensure all members are strings
                       data['member_ids'] = [str(m) for m in data['member_ids'] if m is not None]


                  # Create Party object
                  party = Party.from_dict(data) # Requires Party.from_dict method

                  # 4. Добавьте объект Party в per-guild кеш
                  guild_parties_cache[party.id] = party

                  loaded_count += 1

             except Exception as e:
                 print(f"PartyManager: Error loading party {data.get('id', 'N/A')} for guild {guild_id_str}: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # Continue loop

        print(f"PartyManager: Successfully loaded {loaded_count} parties into cache for guild {guild_id_str}.")


    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"PartyManager: Rebuilding runtime caches for guild {guild_id_str}...")

        # Получаем все загруженные партии для этой гильдии (из текущего кеша PartyManager)
        parties_for_guild = list(self._parties.get(guild_id_str, {}).values())

        # ИСПРАВЛЕНИЕ: Перестроение per-guild кеша {member_id: party_id}
        guild_member_map = self._member_to_party_map.setdefault(guild_id_str, {})
        guild_member_map.clear() # Очищаем старые записи для этой гильдии

        for party in parties_for_guild: # Iterate through parties loaded for THIS guild
             party_id = getattr(party, 'id', None)
             if party_id is None:
                  print(f"PartyManager: Warning: Skipping party with no ID during rebuild for guild {guild_id_str}.")
                  continue

             member_ids = getattr(party, 'member_ids', [])
             if isinstance(member_ids, list):
                  for member_id in member_ids:
                       if isinstance(member_id, str):
                             # TODO: Проверка конфликтов - один участник в нескольких партиях?
                             if member_id in guild_member_map:
                                  print(f"PartyManager: Warning: Member {member_id} found in multiple parties during rebuild for guild {guild_id_str}: was in {guild_member_map[member_id]}, now in {party_id}. Keeping {party_id}.")
                             guild_member_map[member_id] = party_id # Store party ID (str)
                       else: print(f"PartyManager: Warning: Invalid member_id format during rebuild for guild {guild_id_str}: {member_id} in party {party_id}. Skipping.")
             else: print(f"PartyManager: Warning: member_ids for party {party_id} (guild {guild_id_str}) is not a list during rebuild ({type(member_ids)}). Skipping members.")


        # TODO: Пометить сущности (Character/NPC) как занятые в их менеджерах, если они находятся в активной партии/бою.
        # This is typically done in the CharacterManager/NpcManager rebuild_runtime_caches,
        # which receives PartyManager and CombatManager in kwargs and uses them to check status.
        # char_mgr = kwargs.get('character_manager') # type: Optional["CharacterManager"]
        # npc_mgr = kwargs.get('npc_manager') # type: Optional["NpcManager"]
        # if char_mgr and hasattr(char_mgr, 'rebuild_runtime_caches'):
        #      await char_mgr.rebuild_runtime_caches(guild_id_str, **kwargs)
        # if npc_mgr and hasattr(npc_mgr, 'rebuild_runtime_caches'):
        #      await npc_mgr.rebuild_runtime_caches(guild_id_str, **kwargs)


        print(f"PartyManager: Rebuild runtime caches complete for guild {guild_id_str}.")


    # ИСПРАВЛЕНИЕ: Реализация mark_party_dirty(guild_id, party_id)
    def mark_party_dirty(self, guild_id: str, party_id: str) -> None:
        """Помечает партию как измененной для последующего сохранения для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Party ID должен существовать в кеше активных партий
        guild_parties_cache = self._parties.get(guild_id_str)
        if guild_parties_cache and party_id in guild_parties_cache:
             self._dirty_parties.setdefault(guild_id_str, set()).add(party_id) # Добавляем в per-guild Set
        # else: print(f"PartyManager: Warning: Attempted to mark non-existent party {party_id} in guild {guild_id_str} as dirty.")


    # TODO: Implement clean_up_for_character(character_id, context) method (used in CharacterManager)
    # async def clean_up_for_character(self, character_id: str, context: Dict[str, Any]) -> None:
    #     """Удаляет персонажа из партии при его удалении."""
    #     guild_id = context.get('guild_id')
    #     if guild_id is None:
    #          print(f"PartyManager: Error in clean_up_for_character: Missing guild_id in context for character {character_id}.")
    #          return # Cannot proceed without guild_id
    #
    #     # Найти партию, в которой состоит персонаж
    #     party = await self.get_party_by_member_id(character_id, guild_id) # Use async method
    #     if not party:
    #          print(f"PartyManager: Character {character_id} not in a party in guild {guild_id}.")
    #          return # Character is not in any party
    #
    #     # Удалить персонажа из списка участников партии
    #     if character_id in getattr(party, 'member_ids', []):
    #          getattr(party, 'member_ids', []).remove(character_id)
    #          print(f"PartyManager: Removed character {character_id} from party {getattr(party, 'id', 'N/A')} in guild {guild_id}.")
    #          # Помечаем партию как измененную
    #          party_id = getattr(party, 'id')
    #          if party_id: self.mark_party_dirty(guild_id, party_id)
    #
    #     # Удалить запись из _member_to_party_map
    #     guild_member_map = self._member_to_party_map.get(str(guild_id))
    #     if guild_member_map and guild_member_map.get(character_id) == getattr(party, 'id', None):
    #          del guild_member_map[character_id]
    #          print(f"PartyManager: Removed member {character_id} from _member_to_party_map for guild {guild_id}.")
    #
    #     # Если партия стала пустой, удалить ее
    #     if not getattr(party, 'member_ids', []):
    #          print(f"PartyManager: Party {getattr(party, 'id', 'N/A')} in guild {guild_id} is now empty. Removing party.")
    #          party_id = getattr(party, 'id', None)
    #          if party_id:
    #              await self.remove_party(party_id, guild_id, **context) # Recursively call remove_party


    # TODO: Implement clean_up_for_npc(npc_id, context) method (similar to clean_up_for_character)
    # async def clean_up_for_npc(self, npc_id: str, context: Dict[str, Any]) -> None: ...

    # TODO: Implement get_parties_with_active_action(guild_id) method (used by WorldSimulationProcessor)
    # Def get_parties_with_active_action(self, guild_id: str) -> List["Party"]:
    #      """Возвращает список Party объектов для гильдии, у которых party.current_action is not None."""
    #      guild_id_str = str(guild_id)
    #      guild_parties_cache = self._parties.get(guild_id_str, {})
    #      return [party for party in guild_parties_cache.values() if getattr(party, 'current_action', None) is not None]

    # TODO: Implement methods to manage party members (add/remove member)
    # async def add_member(self, party_id: str, entity_id: str, guild_id: str, **kwargs): ...
    # async def remove_member(self, party_id: str, entity_id: str, guild_id: str, **kwargs): ... # Removes from party.member_ids, updates map, marks dirty. Doesn't delete party.


# --- Конец класса PartyManager ---


print("DEBUG: party_manager.py module loaded.")
