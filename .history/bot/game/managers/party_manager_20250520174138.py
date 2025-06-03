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
# Используйте строковые литералы ("ClassName") для type hints в init и методах
# для классов, импортированных здесь, ЕСЛИ они импортированы только здесь.
if TYPE_CHECKING:
    # Добавляем адаптер БД
    from bot.database.sqlite_adapter import SqliteAdapter
    # Добавляем модели, используемые в аннотациях
    from bot.game.models.party import Party # Аннотируем как "Party"
    from bot.game.models.character import Character # Для clean_up_for_entity, rebuild_runtime_caches context
    from bot.game.models.npc import NPC # Для clean_up_for_entity, rebuild_runtime_caches context


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
    # Добавляем DialogueManager, если Party может быть в диалоге или PartyManager должен чистить диалог
    # from bot.game.managers.dialogue_manager import DialogueManager


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
    Отвечает за создание, получение, обновление партий, их персистентность
    и хранение их основного состояния и кешей.
    Работает на основе guild_id для многогильдийной поддержки.
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
                 # dialogue_manager: Optional["DialogueManager"] = None, # если Party может быть в диалоге
                ):
        print("Initializing PartyManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        # Инжектированные зависимости
        self._npc_manager = npc_manager
        self._character_manager = character_manager
        self._combat_manager = combat_manager
        # self._event_manager = event_manager
        # self._dialogue_manager = dialogue_manager


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
        guild_id_str = str(guild_id) # Убедимся, что guild_id строка
        guild_parties = self._parties.get(guild_id_str) # Get per-guild cache
        if guild_parties:
             return guild_parties.get(str(party_id)) # Ensure party_id is string
        return None # Guild or party not found

    # Используем строковый литерал в аннотации возвращаемого типа
    # ИСПРАВЛЕНИЕ: Метод get_all_parties должен принимать guild_id
    def get_all_parties(self, guild_id: str) -> List["Party"]:
        """Получить список всех загруженных партий для определенной гильдии (из кеша)."""
        guild_id_str = str(guild_id) # Убедимся, что guild_id строка
        guild_parties = self._parties.get(guild_id_str) # Get per-guild cache
        if guild_parties:
             return list(guild_parties.values())
        return [] # Возвращаем пустой список, если для гильдии нет партий


    # ИСПРАВЛЕНИЕ: Реализация get_party_by_member_id
    async def get_party_by_member_id(self, guild_id: str, entity_id: str, **kwargs: Any) -> Optional["Party"]: # Changed order to guild_id first
         """Найти партию по ID участника для определенной гильдии."""
         guild_id_str = str(guild_id)
         entity_id_str = str(entity_id)

         # Используем мапу {guild_id: {member_id: party_id}}
         guild_member_map = self._member_to_party_map.get(guild_id_str) # Type: Optional[Dict[str, str]]
         if guild_member_map:
              party_id = guild_member_map.get(entity_id_str) # Use string entity_id for map lookup # Type: Optional[str]
              if party_id:
                   # Получаем Party объект из основного кеша PartyManager (уже с guild_id)
                   return self.get_party(guild_id_str, party_id) # Use party_id from map and guild_id


         # Fallback: перебрать все партии в кеше для этой гильдии (медленно, но надежно)
         # This fallback is less necessary if the map rebuild is robust, but can be a safety net.
         parties_for_guild = self.get_all_parties(guild_id_str) # Use get_all_parties with guild_id
         for party in parties_for_guild:
              # Check if the party object is valid and has member_ids attribute
              if isinstance(party, Party) and hasattr(party, 'member_ids'):
                   member_ids = getattr(party, 'member_ids', [])
                   # Ensure member_ids is a list and check if entity_id is in it
                   if isinstance(member_ids, list) and entity_id_str in member_ids:
                        return party # Return party object

         return None # Not found in map or fallback


    # TODO: Implement get_parties_with_active_action(guild_id) method (used by WorldSimulationProcessor)
    def get_parties_with_active_action(self, guild_id: str) -> List["Party"]: # Аннотация List["Party"]
         """Возвращает список Party объектов для гильдии, у которых party.current_action is not None."""
         guild_id_str = str(guild_id)
         guild_parties_cache = self._parties.get(guild_id_str, {})
         # Filter for valid Party objects with a non-None current_action
         return [party for party in guild_parties_cache.values() if isinstance(party, Party) and getattr(party, 'current_action', None) is not None]


    # TODO: Implement is_party_busy method (used by CharacterManager.is_busy)
    # This method should be implemented within PartyManager.
    def is_party_busy(self, guild_id: str, party_id: str) -> bool:
         """Проверяет, занята ли партия (выполняет групповое действие и т.п.) для определенной гильдии."""
         guild_id_str = str(guild_id)
         party = self.get_party(guild_id_str, party_id) # Get party using guild_id
         if not party:
              # print(f"PartyManager: Warning: is_party_busy called for non-existent party {party_id} in guild {guild_id_str}.") # Too noisy?
              return False # Cannot be busy if it doesn't exist

         # Assuming Party object has 'current_action' and 'action_queue' attributes for group actions
         if getattr(party, 'current_action', None) is not None or getattr(party, 'action_queue', []):
              return True

         # TODO: Add other criteria for party busy status (e.g., leader is busy, key members are busy, in combat)
         # This might require checking the status of members via CharacterManager/NpcManager
         # and checking combat status via CombatManager.
         # Getting managers from self._ requires them to be injected in __init__.
         # Getting managers from kwargs is not possible here as this is a synchronous method.
         # If busy status depends on other managers' dynamic state, this method might need to become async.
         # For now, let's assume busy status is only determined by the party's own action state.


         return False # Not busy based on current criteria


    # --- Методы CRUD ---

    async def create_party(self, leader_id: str, member_ids: List[str], guild_id: str, **kwargs: Any) -> Optional[str]:
        """
        Создает новую партию с лидером и списком участников для определенной гильдии.
        """
        if self._db_adapter is None:
            print(f"PartyManager: No DB adapter for guild {guild_id}. Cannot create party.")
            return None # Cannot proceed without DB for persistence

        guild_id_str = str(guild_id) # Убедимся, что guild_id строка
        leader_id_str = str(leader_id) # Ensure leader_id is string
        member_ids_str = [str(mid) for mid in member_ids if mid is not None] # Ensure member_ids are strings

        # Ensure leader_id is in the member_ids list (or add it?)
        # Depending on rules, leader might be included or separate. Let's assume leader is also a member.
        if leader_id_str not in member_ids_str:
             print(f"PartyManager: Warning: Leader {leader_id_str} not included in member_ids list for new party in guild {guild_id_str}. Adding leader to members.")
             member_ids_str.append(leader_id_str)


        # TODO: Валидация (участники существуют, не в других партиях, leader_id в списке member_ids)
        # Use self._character_manager, self._npc_manager, self.get_party_by_member_id (with guild_id)
        # This validation can be asynchronous.
        # char_mgr = self._character_manager or kwargs.get('character_manager') # Get manager from self or kwargs
        # npc_mgr = self._npc_manager or kwargs.get('npc_manager') # Get manager from self or kwargs
        # for entity_id in member_ids_str:
        #      is_already_in_party = await self.get_party_by_member_id(guild_id_str, entity_id) is not None # Check if already in party for this guild
        #      if is_already_in_party:
        #           print(f"PartyManager: Error creating party: Member {entity_id} is already in a party in guild {guild_id_str}.")
        #           # TODO: Send feedback?
        #           return None # Cannot create party if member is already in one


        try:
            new_id = str(uuid.uuid4())

            party_data: Dict[str, Any] = {
                'id': new_id,
                'guild_id': guild_id_str, # Сохраняем как строку
                'leader_id': leader_id_str, # Store leader_id as string
                'member_ids': member_ids_str, # Store member_ids as list of strings
                # TODO: Добавить другие поля Party модели
                'state_variables': kwargs.get('initial_state_variables', {}), # Allow initial state
                'current_action': None, # Групповое действие партии
                # TODO: location_id для партии, если применимо? (Например, Party Location = Leader Location)
                # 'location_id': kwargs.get('initial_location_id'), # If passed
            }
            party = Party.from_dict(party_data) # Требует прямого импорта Party при runtime

            # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш
            self._parties.setdefault(guild_id_str, {})[new_id] = party

            # ИСПРАВЛЕНИЕ: Обновляем _member_to_party_map для этой гильдии
            guild_member_map = self._member_to_party_map.setdefault(guild_id_str, {})
            for member_id in member_ids_str: # Use the validated list of strings
                 # This will overwrite if a member was added to a new party without leaving the old one.
                 # The validation step above should ideally prevent this.
                 if member_id in guild_member_map:
                      print(f"PartyManager: Warning: Overwriting member_to_party map entry for member {member_id} in guild {guild_id_str}. Was in party {guild_member_map[member_id]}, now in {new_id}.")
                 guild_member_map[member_id] = new_id


            # ИСПРАВЛЕНИЕ: Помечаем party dirty (per-guild)
            self.mark_party_dirty(guild_id_str, new_id)


            print(f"PartyManager: Party {new_id} created for guild {guild_id_str}. Leader: {leader_id_str}. Members: {member_ids_str}")
            # TODO: Notify participants? (Through send_callback_factory from kwargs)

            return new_id

        except Exception as e:
            print(f"PartyManager: Error creating party for leader {leader_id_str} in guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            # TODO: Rollback if creation failed after map update?
            return None


    # remove_party needs guild_id
    async def remove_party(self, party_id: str, guild_id: str, **kwargs: Any) -> Optional[str]:
        """
        Удаляет партию и помечает для удаления в БД для определенной гильдии.
        Выполняет очистку участников.
        """
        guild_id_str = str(guild_id) # Убедимся, что guild_id строка
        party_id_str = str(party_id) # Ensure party_id is string


        # ИСПРАВЛЕНИЕ: Получаем партию с учетом guild_id
        party = self.get_party(guild_id_str, party_id_str) # Use string party_id
        if not party:
            # Check if it's already marked for deletion for this guild
            if guild_id_str in self._deleted_parties and party_id_str in self._deleted_parties[guild_id_str]:
                 print(f"PartyManager: Party {party_id_str} in guild {guild_id_str} was already marked for deletion.")
                 return party_id_str # Return ID if already marked

            print(f"PartyManager: Party {party_id_str} not found for removal in guild {guild_id_str}.")
            return None

        # Check that party belongs to this guild (already implicitly done by get_party, but belt and suspenders)
        if str(getattr(party, 'guild_id', None)) != guild_id_str:
            print(f"PartyManager: Error: Mismatched guild_id for party {party_id_str} removal. Expected {guild_id_str}, found {getattr(party, 'guild_id', None)}.")
            return None


        print(f"PartyManager: Removing party {party_id_str} for guild {guild_id_str}. Leader: {getattr(party, 'leader_id', 'N/A')}")

        # Get a copy of member_ids (which should be strings)
        member_ids = list(getattr(party, 'member_ids', []))
        if not isinstance(member_ids, list): member_ids = [] # Ensure it's a list


        # Передаем context в cleanup методы
        cleanup_context: Dict[str, Any] = {
            'party_id': party_id_str, # Pass string party_id
            'party': party,
            'guild_id': guild_id_str, # Передаем guild_id_str

            # Pass injected managers/processors from self._ or kwargs
            'character_manager': self._character_manager or kwargs.get('character_manager'),
            'npc_manager': self._npc_manager or kwargs.get('npc_manager'),
            'combat_manager': self._combat_manager or kwargs.get('combat_manager'),
            # Add others that might need cleanup related to party disbanding (e.g., DialogueManager, StatusManager)
            # 'dialogue_manager': self._dialogue_manager or kwargs.get('dialogue_manager'),
            # 'status_manager': self._status_manager or kwargs.get('status_manager'),
        }
        cleanup_context.update(kwargs) # Add any extra kwargs passed to remove_party

        if member_ids:
            print(f"PartyManager: Cleaning up {len(member_ids)} members for party {party_id_str} in guild {guild_id_str}.")
            # Iterate over a copy of member_ids list
            for entity_id in list(member_ids): # Use a copy for iteration safety if members are removed from the list during cleanup
                 try:
                     entity_type = None
                     manager = None # type: Optional[Any]
                     # Get managers from cleanup context
                     char_mgr = cleanup_context.get('character_manager') # type: Optional["CharacterManager"]
                     npc_mgr = cleanup_context.get('npc_manager') # type: Optional["NpcManager"]

                     # Determine entity type and get the appropriate manager
                     if char_mgr and hasattr(char_mgr, 'get_character') and char_mgr.get_character(guild_id_str, entity_id):
                          entity_type = "Character" ; manager = char_mgr
                     elif npc_mgr and hasattr(npc_mgr, 'get_npc') and npc_mgr.get_npc(guild_id_str, entity_id):
                          entity_type = "NPC" ; manager = npc_mgr
                     # TODO: Add other entity types (e.g., if Parties can contain other Parties)


                     # Check for cleanup methods on the entity manager
                     # Prioritize generic clean_up_for_entity, then specific clean_up_from_party
                     clean_up_method_name = None
                     if manager:
                          if hasattr(manager, 'clean_up_for_entity'):
                                clean_up_method_name = 'clean_up_for_entity'
                          elif hasattr(manager, 'clean_up_from_party'): # Fallback to specific method name
                                clean_up_method_name = 'clean_up_from_party'


                     if manager and clean_up_method_name and entity_type:
                          # Call the cleanup method, passing entity_id, entity_type (for generic), and context
                          if clean_up_method_name == 'clean_up_for_entity':
                               # Generic method: clean_up_for_entity(entity_id, entity_type, context)
                               await getattr(manager, clean_up_method_name)(entity_id, entity_type, context=cleanup_context)
                          else: # Specific method: clean_up_from_party(entity_id, context)
                               await getattr(manager, clean_up_method_name)(entity_id, context=cleanup_context)

                          print(f"PartyManager: Cleaned up participant {entity_type} {entity_id} from party {party_id_str} in guild {guild_id_str} via {type(manager).__name__}.{clean_up_method_name}.")
                     # else: // Warning logged below

                 except Exception as e:
                    print(f"PartyManager: ❌ Error during cleanup for member {entity_id} in party {party_id_str} (guild {guild_id_str}): {e}")
                    import traceback
                    print(traceback.format_exc())
                    # Do not re-raise error, continue cleanup for other members.
            # After iterating, the member_ids list on the 'party' object *in cache* might have been modified
            # if clean_up_for_entity/clean_up_from_party also update the entity object's party_id attribute.
            # This is fine, as the party object will be removed from cache below anyway.

        print(f"PartyManager: Finished member cleanup process for party {party_id_str} in guild {guild_id_str}.")


        # --- Other party-specific cleanup ---
        # Remove status effects on the party entity itself (if Party can have statuses)
        # status_mgr = cleanup_context.get('status_manager') # type: Optional["StatusManager"]
        # if status_mgr and hasattr(status_mgr, 'remove_status_effects_by_target'):
        #      try: await status_mgr.remove_status_effects_by_target(party_id_str, 'Party', context=cleanup_context)
        #      except Exception as e: ...

        # Handle combat ending if the party disbanding ends a combat? (Unlikely, usually other way around)
        # combat_mgr = cleanup_context.get('combat_manager') # type: Optional["CombatManager"]
        # if combat_mgr and hasattr(combat_mgr, 'party_disbanded_in_combat'): # Assuming such a method
        #      try: await combat_mgr.party_disbanded_in_combat(party_id_str, context=cleanup_context)
        #      except Exception as e: ...

        # Handle dialogue ending if the party leader/members being in dialogue tied the dialogue to the party?
        # dialogue_mgr = cleanup_context.get('dialogue_manager') # type: Optional["DialogueManager"]
        # if dialogue_mgr and hasattr(dialogue_mgr, 'clean_up_for_party'): # Assuming such a method
        #      try: await dialogue_mgr.clean_up_for_party(party_id_str, context=cleanup_context)
        #      except Exception as e: ...


        # TODO: Clear party's current action and queue
        # if hasattr(party, 'current_action'): party.current_action = None
        # if hasattr(party, 'action_queue'): party.action_queue = []
        # Mark dirty if action state changed - not needed if removing from cache anyway.

        print(f"PartyManager: Party {party_id_str} cleanup processes complete for guild {guild_id_str}.")


        # --- Remove party from cache and mark for deletion from DB ---

        # ИСПРАВЛЕНИЕ: Удаляем записи из _member_to_party_map для этой гильдии for the *members who were in the party*
        # Iterate through the list of members we got *before* cleanup (in case cleanup removed them from the list on the object)
        guild_member_map = self._member_to_party_map.get(guild_id_str)
        if guild_member_map:
             for member_id in member_ids: # Use the list of members before cleanup
                  # Only remove the mapping if it still points to this specific party
                  if guild_member_map.get(member_id) == party_id_str:
                       del guild_member_map[member_id]
                       # print(f"PartyManager: Removed member {member_id} from _member_to_party_map for guild {guild_id_str} (was in {party_id_str}).") # Debug

             # Optional: Clean up leader mapping if distinct
             # leader_id = getattr(party, 'leader_id', None)
             # if leader_id is not None and str(leader_id) not in member_ids and guild_member_map.get(str(leader_id)) == party_id_str:
             #      del guild_member_map[str(leader_id)]


        # ИСПРАВЛЕНИЕ: Помечаем партию для удаления из БД (per-guild)
        # Use the correct per-guild deleted set
        self._deleted_parties.setdefault(guild_id_str, set()).add(party_id_str)

        # ИСПРАВЛЕНИЕ: Удаляем из per-guild кеша активных партий
        # Use the correct per-guild active parties cache
        guild_parties = self._parties.get(guild_id_str)
        if guild_parties:
             guild_parties.pop(party_id_str, None) # Remove from per-guild cache


        # Убираем из dirty set, если там была (удален -> не dirty anymore for upsert)
        # Use the correct per-guild dirty set
        self._dirty_parties.get(guild_id_str, set()).discard(party_id_str)


        print(f"PartyManager: Party {party_id_str} fully removed from cache and marked for deletion for guild {guild_id_str}.")
        return party_id_str # Return the ID of the removed party


    # Methods for persistence (called by PersistenceManager):
    # These methods should work per-guild
    # required_args_for_load, required_args_for_save, required_args_for_rebuild уже определены как атрибуты класса

    # save_state(guild_id, **kwargs) - called by PersistenceManager
    # Needs to save ACTIVE parties for the specific guild, AND delete marked-for-deletion ones.
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет активные/измененные партии для определенной гильдии."""
        if self._db_adapter is None:
            print(f"PartyManager: Warning: Cannot save parties for guild {guild_id}, DB adapter missing.")
            return

        guild_id_str = str(guild_id)
        print(f"PartyManager: Saving parties for guild {guild_id_str}...")

        # ИСПРАВЛЕНИЕ: Собираем партии для сохранения ИЗ per-guild dirty set и per-guild cache
        # Собираем party_ids, помеченные как dirty для этой гильдии
        dirty_party_ids_for_guild_set = self._dirty_parties.get(guild_id_str, set()).copy() # Рабочая копия dirty IDs
        # Теперь получаем объекты Party из кеша, используя эти ID
        parties_to_save: List["Party"] = []
        guild_parties_cache = self._parties.get(guild_id_str, {})
        # Filter for IDs that are dirty AND still in the cache
        parties_to_save = [guild_parties_cache[pid] for pid in dirty_party_ids_for_guild_set if pid in guild_parties_cache]


        # ИСПРАВЛЕНИЕ: Собираем IDs партий, помеченных для удаления для этой гильдии
        deleted_party_ids_for_guild_set = self._deleted_parties.get(guild_id_str, set()).copy() # Рабочая копия deleted IDs


        # Если нет партий для сохранения или удаления, выходим
        if not parties_to_save and not deleted_party_ids_for_guild_set:
             # print(f"PartyManager: No dirty or deleted parties to save for guild {guild_id_str}.") # Debug
             # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, просто очищаем dirty/deleted сеты для этой гильдии
             # (они должны быть уже пусты, но это безопасная очистка)
             self._dirty_parties.pop(guild_id_str, None)
             self._deleted_parties.pop(guild_id_str, None)
             return


        try:
            # 4. Удаление партий, помеченных для удаления для этой гильдии
            if deleted_party_ids_for_guild_set:
                 ids_to_delete = list(deleted_party_ids_for_guild_set)
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 delete_sql = f"DELETE FROM parties WHERE guild_id = ? AND id IN ({placeholders_del})"
                 try:
                     await self._db_adapter.execute(sql=delete_sql, params=(guild_id_str, *tuple(ids_to_delete))); # Use keyword args
                     print(f"PartyManager: Deleted {len(ids_to_delete)} parties from DB for guild {guild_id_str}.")
                     # ИСПРАВЛЕНИЕ: Очищаем deleted set для этой гильдии после успешного удаления
                     self._deleted_parties.pop(guild_id_str, None)
                 except Exception as e:
                     print(f"PartyManager: Error deleting parties for guild {guild_id_str}: {e}")
                     import traceback
                     print(traceback.format_exc())
                     # Do NOT clear _deleted_parties[guild_id_str], to try again next save


            # 5. Сохранение/обновление партий для этой гильдии
            if parties_to_save:
                 print(f"PartyManager: Upserting {len(parties_to_save)} parties for guild {guild_id_str}...")
                 # INSERT OR REPLACE SQL для обновления существующих или вставки новых
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
                           await self._db_adapter.execute_many(sql=upsert_sql, data=data_to_upsert); # Use keyword args
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
                      data['member_ids'] = json.loads(data.get('member_ids') or '[]') if isinstance(data.get('member_ids'), (str, bytes)) else []
                  except (json.JSONDecodeError, TypeError):
                      print(f"PartyManager: Warning: Failed to parse member_ids for party {party_id}. Setting to []. Data: {data.get('member_ids')}")
                      data['member_ids'] = []

                  try:
                      data['state_variables'] = json.loads(data.get('state_variables') or '{}') if isinstance(data.get('state_variables'), (str, bytes)) else {}
                  except (json.JSONDecodeError, TypeError):
                      print(f"PartyManager: Warning: Failed to parse state_variables for party {party_id}. Setting to {{}}. Data: {data.get('state_variables')}")
                      data['state_variables'] = {}

                  try:
                      current_action_data = data.get('current_action')
                      data['current_action'] = json.loads(current_action_data) if isinstance(current_action_data, (str, bytes)) else None
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

                  # Ensure leader_id is string or None
                  data['leader_id'] = str(data['leader_id']) if data.get('leader_id') is not None else None


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
             party_id_str = str(party_id) # Ensure party_id is string

             member_ids = getattr(party, 'member_ids', [])
             if isinstance(member_ids, list):
                  for member_id in member_ids:
                       if isinstance(member_id, str):
                             # TODO: Проверка конфликтов - один участник в нескольких партиях?
                             # During rebuild, this scenario indicates DB inconsistency if an entity is listed in multiple parties' member_ids.
                             # The map will store the LATEST party encountered for that member.
                             if member_id in guild_member_map:
                                  print(f"PartyManager: Warning: Member {member_id} found in multiple parties during rebuild for guild {guild_id_str}: previously mapped to {guild_member_map[member_id]}, now mapping to {party_id_str}.")
                             guild_member_map[member_id] = party_id_str # Store party ID (str)
                       else: print(f"PartyManager: Warning: Invalid member_id format during rebuild for guild {guild_id_str}: {member_id} in party {party_id_str}. Skipping.")
             else: print(f"PartyManager: Warning: member_ids for party {party_id_str} (guild {guild_id_str}) is not a list during rebuild ({type(member_ids)}). Skipping members.")

             # Optional: Add leader_id to the map if it's not already covered in member_ids
             leader_id = getattr(party, 'leader_id', None)
             if leader_id is not None and isinstance(leader_id, str) and leader_id not in member_ids:
                  if leader_id in guild_member_map:
                       print(f"PartyManager: Warning: Leader {leader_id} found in multiple parties/roles during rebuild for guild {guild_id_str}: previously mapped to {guild_member_map[leader_id]}, now mapping to {party_id_str} (as leader). Keeping {party_id_str}.")
                  guild_member_map[leader_id] = party_id_str


        # TODO: Notify entity managers (Character/NPC) if they need to update their busy status cache based on party membership.
        # This is typically done in the CharacterManager/NpcManager rebuild_runtime_caches,
        # which receives PartyManager in kwargs and uses get_party_by_member_id(guild_id, entity_id).
        # char_mgr = kwargs.get('character_manager') # type: Optional["CharacterManager"]
        # npc_mgr = kwargs.get('npc_manager') # type: Optional["NpcManager"]
        # if char_mgr and hasattr(char_mgr, 'rebuild_runtime_caches'):
        #      # The entity manager gets *this* PartyManager instance via kwargs and queries it.
        #      # No direct call back into entity managers from here needed for this purpose.
        #      pass # The entity manager will handle this side of the rebuild


        print(f"PartyManager: Rebuild runtime caches complete for guild {guild_id_str}. Member map size: {len(guild_member_map)}")


    # mark_party_dirty needs guild_id
    # Needs _dirty_parties Set (per-guild)
    # Implemented correctly above.
    def mark_party_dirty(self, guild_id: str, party_id: str) -> None:
        """Помечает партию как измененной для последующего сохранения для определенной гильдии."""
        guild_id_str = str(guild_id)
        party_id_str = str(party_id)
        # Party ID должен существовать в кеше активных партий
        guild_parties_cache = self._parties.get(guild_id_str)
        if guild_parties_cache and party_id_str in guild_parties_cache:
             self._dirty_parties.setdefault(guild_id_str, set()).add(party_id_str) # Добавляем в per-guild Set
        # else: print(f"PartyManager: Warning: Attempted to mark non-existent party {party_id_str} in guild {guild_id_str} as dirty.") # Too noisy?


    # TODO: Implement clean_up_for_entity method (used by Character/NPC Managers)
    # This method is called by CharacterManager.remove_character, NpcManager.remove_npc etc.
    # It should remove the entity from the party they are in, and potentially disband the party if it becomes empty.
    async def clean_up_for_entity(self, entity_id: str, entity_type: str, **kwargs: Any) -> None:
        """
        Удаляет сущность из партии, если она в ней состоит, когда сущность удаляется.
        Предназначен для вызова менеджерами сущностей (Character, NPC).
        """
        # Get guild_id from context kwargs
        guild_id = kwargs.get('guild_id')
        if guild_id is None:
             print(f"PartyManager: Warning: clean_up_for_entity called for {entity_type} {entity_id} without guild_id in context. Cannot clean up from party.")
             return # Cannot proceed without guild_id

        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)
        print(f"PartyManager: Cleaning up {entity_type} {entity_id} from party in guild {guild_id_str}...")

        # Find the party the entity is in within this guild
        # Use the updated get_party_by_member_id that takes guild_id
        party = await self.get_party_by_member_id(guild_id_str, entity_id_str) # Use async method with guild_id and string entity_id

        if not party:
            # print(f"PartyManager: {entity_type} {entity_id_str} is not in a party in guild {guild_id_str}.") # Too noisy?
            return # Entity is not in any party

        party_id = getattr(party, 'id', None)
        if not party_id:
             print(f"PartyManager: Warning: Found party object with no ID for participant {entity_id_str} in guild {guild_id_str} during cleanup.")
             return # Cannot clean up from party without party ID
        party_id_str = str(party_id) # Ensure party_id is string


        # Remove the entity from the party object's member_ids list
        member_ids_list = getattr(party, 'member_ids', [])
        if isinstance(member_ids_list, list):
            initial_count = len(member_ids_list)
            # Create a new list excluding the entity ID
            # Ensure we remove the correct string ID
            new_member_ids_list = [mid for mid in member_ids_list if mid != entity_id_str]

            # If the list size changed, the entity was found and removed
            if len(new_member_ids_list) < initial_count:
                 party.member_ids = new_member_ids_list # Update the party object
                 print(f"PartyManager: Removed {entity_type} {entity_id_str} from member list of party {party_id_str} in guild {guild_id_str}.")
                 self.mark_party_dirty(guild_id_str, party_id_str) # Mark party as dirty (per-guild)


                 # Remove the entity's entry from the _member_to_party_map for this guild
                 guild_member_map = self._member_to_party_map.get(guild_id_str)
                 if guild_member_map and guild_member_map.get(entity_id_str) == party_id_str:
                      del guild_member_map[entity_id_str]
                      # print(f"PartyManager: Removed member {entity_id_str} from _member_to_party_map for guild {guild_id_str} (was in {party_id_str}).") # Debug


                 # Check if the party became empty after removing the member
                 if not new_member_ids_list:
                      print(f"PartyManager: Party {party_id_str} in guild {guild_id_str} is now empty after {entity_id_str} left. Removing party.")
                      # Call remove_party to fully disband the party, passing context
                      await self.remove_party(party_id_str, guild_id_str, **kwargs) # Pass party_id, guild_id, and context


            else:
                 print(f"PartyManager: Warning: {entity_type} {entity_id_str} was not found in member list of party {party_id_str} in guild {guild_id_str} during cleanup.")
        else:
             print(f"PartyManager: Warning: Party {party_id_str} member_ids data is not a list for guild {guild_id_str}. Cannot clean up participant {entity_id_str}.")


    # TODO: Implement methods to manage party members (add/remove member)
    # async def add_member(self, party_id: str, entity_id: str, entity_type: str, guild_id: str, **kwargs): ... # Add member to list, update map, mark dirty. Needs validation.
    # async def remove_member(self, party_id: str, entity_id: str, guild_id: str, **kwargs): ... # Remove member from list, update map, mark dirty. Doesn't disband.
    # async def set_leader(self, party_id: str, entity_id: str, guild_id: str, **kwargs): ... # Change leader, mark dirty. Needs validation (new leader is member).

# --- Конец класса PartyManager ---

print("DEBUG: party_manager.py module loaded.")
