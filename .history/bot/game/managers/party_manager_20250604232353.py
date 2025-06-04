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

        party_name = kwargs.get('name', f"Party of {leader_id_str}") # Default name if not provided
        current_location_id = kwargs.get('current_location_id', None) # Get from kwargs

        try:
            new_id = str(uuid.uuid4())

            party_data: Dict[str, Any] = {
                'id': new_id,
                'name': party_name,
                'guild_id': guild_id_str, 
                'leader_id': leader_id_str, 
                'player_ids_list': member_ids_str, # Use player_ids_list for Party.from_dict
                'state_variables': kwargs.get('initial_state_variables', {}), 
                'current_action': None,
                'current_location_id': current_location_id,
                'turn_status': "pending_actions" # Default turn status
            }
            # Party.from_dict expects 'player_ids' as JSON string if it's coming from DB,
            # but for creation, we pass player_ids_list directly.
            # The Party model's from_dict handles 'player_ids' (JSON str) or 'member_ids' (JSON str).
            # For direct creation with a list, we should align with the dataclass field name `player_ids_list`.
            # The `Party.from_dict` should be robust enough or we adjust `party_data` key here.
            # The model's `from_dict` expects `player_ids` to be the JSON string.
            # Let's ensure `Party.from_dict` can handle `player_ids_list` directly or modify `party_data`
            # For now, assuming Party.from_dict is flexible or we adjust it later.
            # The model's `player_ids_list` field is what `Party.from_dict` uses internally for the member list.
            # The model's `player_ids` field is for the JSON string.

            party = Party.from_dict(party_data)

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


            print(f"PartyManager: Party {new_id} ('{getattr(party, 'name', new_id)}') created for guild {guild_id_str}. Leader: {leader_id_str}. Members: {member_ids_str}. Location: {current_location_id}")
            # TODO: Notify participants? (Through send_callback_factory from kwargs)

            return party # Return the Party object

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

        # Get a copy of player_ids_list (which should be strings)
        member_ids_list = list(getattr(party, 'player_ids_list', []))
        if not isinstance(member_ids_list, list): member_ids_list = [] # Ensure it's a list

        # Context for CharacterManager calls
        # It's important that self._character_manager is available.
        char_manager = self._character_manager # From __init__
        
        if char_manager and hasattr(char_manager, 'set_party_id'):
            for member_id_str in member_ids_list:
                try:
                    # We assume all members in player_ids_list are characters that need party_id reset.
                    # If NPCs could be in player_ids_list and have a similar field, logic would need adjustment.
                    print(f"PartyManager: Setting party_id to None for character {member_id_str} from disbanded party {party_id_str}.")
                    await char_manager.set_party_id(
                        guild_id=guild_id_str,
                        character_id=member_id_str,
                        party_id=None, # Set to None
                        **kwargs # Pass along other context if needed by set_party_id
                    )
                except Exception as e:
                    print(f"PartyManager: Error setting party_id to None for member {member_id_str} of party {party_id_str}: {e}")
                    print(traceback.format_exc())
        elif not char_manager:
            print(f"PartyManager: Warning: CharacterManager not available in remove_party. Cannot set party_id to None for members of {party_id_str}.")
        
        print(f"PartyManager: Finished setting party_id to None for members of party {party_id_str} in guild {guild_id_str}.")

        # --- Other party-specific cleanup (e.g., combat, statuses on party entity) ---
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
        # Iterate through the list of members we got *before* their party_id was set to None.
        guild_member_map = self._member_to_party_map.get(guild_id_str)
        if guild_member_map:
             for member_id in member_ids_list: # Use the initial list of members
                  if guild_member_map.get(member_id) == party_id_str:
                       del guild_member_map[member_id]
                       # print(f"PartyManager: Removed member {member_id} from _member_to_party_map for guild {guild_id_str} (was in {party_id_str}).")

        # Помечаем партию для удаления из БД (per-guild)
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


    async def update_party_location(self, party_id: str, new_location_id: Optional[str], guild_id: str, context: Dict[str, Any]) -> bool:
        """
        Обновляет местоположение партии.
        """
        guild_id_str = str(guild_id)
        party = self.get_party(guild_id_str, party_id)

        if not party:
            print(f"PartyManager: Error: Party {party_id} not found in guild {guild_id_str} for location update.")
            return False

        # Ensure current_location_id attribute exists
        # ИСПРАВЛЕНИЕ: Используем getattr для безопасного доступа к current_location_id
        if not hasattr(party, 'current_location_id'):
            print(f"PartyManager: Warning: Party {party_id} in guild {guild_id_str} does not have 'current_location_id' attribute. Initializing to None.")
            # Инициализируем атрибут, если он отсутствует, чтобы соответствовать общей логике Party модели
            setattr(party, 'current_location_id', None)
            # Не возвращаем False здесь, а продолжаем обновление, так как атрибут теперь существует.

        # Ensure new_location_id is a string or None
        resolved_new_location_id: Optional[str] = None
        if new_location_id is not None:
            resolved_new_location_id = str(new_location_id)

        # Check if already at the location
        # ИСПРАВЛЕНИЕ: Используем getattr для безопасного доступа к current_location_id при сравнении
        if getattr(party, 'current_location_id', None) == resolved_new_location_id:
            # print(f"PartyManager: Party {party_id} in guild {guild_id_str} is already at location {resolved_new_location_id}.") # Optional: too noisy?
            return True

        # Update the party's current_location_id
        party.current_location_id = resolved_new_location_id # type: ignore # Мы знаем, что атрибут существует
        self.mark_party_dirty(guild_id_str, party_id)

        print(f"PartyManager: Party {party_id} in guild {guild_id_str} location updated to {resolved_new_location_id}. Context: {context}")
        return True


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
                 (id, guild_id, name_i18n, leader_id, player_ids, current_location_id, turn_status, state_variables, current_action)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                 '''
                 # Note: 'member_ids' in DB was renamed to 'player_ids'
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
                           # Use player_ids_list from the Party object for saving
                           member_ids_list = getattr(party, 'player_ids_list', []) 
                           state_variables = getattr(party, 'state_variables', {})
                           current_action = getattr(party, 'current_action', None)
                           name_i18n_dict = getattr(party, 'name_i18n', {"en": f"Party {getattr(party, 'id', 'N/A')}"})
                           current_location_id = getattr(party, 'current_location_id', None)
                           turn_status = getattr(party, 'turn_status', "pending_actions")


                           if leader_id is None:
                                print(f"PartyManager: Warning: Party {party_id} ('{party_name}') (guild {guild_id_str}) has no leader_id during save prep.")

                           if not isinstance(member_ids_list, list):
                               print(f"PartyManager: Warning: Party {party_id} ('{party_name}') (guild {guild_id_str}) player_ids_list is not a list during upsert prep ({type(member_ids_list)}). Saving as empty list.")
                               member_ids_list = []

                           player_ids_json = json.dumps(member_ids_list) # Save player_ids_list as JSON string
                           state_variables_json = json.dumps(state_variables)
                           current_action_json = json.dumps(current_action) if current_action is not None else None

                           data_to_upsert.append((
                               str(party_id),
                               guild_id_str,
                                json.dumps(name_i18n_dict), # Save i18n name as JSON
                               str(leader_id) if leader_id is not None else None,
                               player_ids_json, # This is the 'player_ids' column in DB
                               current_location_id,
                               turn_status,
                               state_variables_json,
                               current_action_json,
                           ))
                           upserted_party_ids.add(str(party_id))

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
            SELECT id, guild_id, name_i18n, leader_id, player_ids, current_location_id, turn_status, state_variables, current_action
            FROM parties
            WHERE guild_id = ?
            '''
            # Note: 'member_ids' in DB was renamed to 'player_ids'
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
                  
                  # Ensure name_i18n is populated correctly
                  name_i18n_from_db = data.get('name_i18n')
                  if isinstance(name_i18n_from_db, str):
                      try:
                          data['name_i18n'] = json.loads(name_i18n_from_db)
                      except json.JSONDecodeError:
                          print(f"PartyManager: Warning: Invalid JSON in name_i18n for party {party_id}. Using default. Data: {name_i18n_from_db}")
                          data['name_i18n'] = {"en": f"Party {party_id}"}
                  elif isinstance(name_i18n_from_db, dict):
                      data['name_i18n'] = name_i18n_from_db # Already a dict
                  else:
                      print(f"PartyManager: Warning: name_i18n for party {party_id} is not a string or dict. Using default. Type: {type(name_i18n_from_db)}")
                      data['name_i18n'] = {"en": f"Party {party_id}"}
                  
                  # Remove the old plain 'name' key if it exists, to avoid confusion if Party.from_dict uses it as a fallback
                  if 'name' in data and 'name_i18n' in data: # If name_i18n was successfully processed
                      data.pop('name', None)


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
    async def clean_up_for_entity(self, entity_id: str, entity_type: str, context: Dict[str, Any]) -> None: # Added context type hint
        """
        Удаляет сущность из партии, если она в ней состоит, когда сущность удаляется.
        Предназначен для вызова менеджерами сущностей (Character, NPC).
        """
        # Get guild_id from context 
        guild_id = context.get('guild_id')
        if guild_id is None:
            print(f"PartyManager: Warning: clean_up_for_entity called for {entity_type} {entity_id} without guild_id in context. Cannot clean up from party.")
            return # Cannot proceed without guild_id

        guild_id_str = str(guild_id)
        entity_id_str = str(entity_id)
        print(f"PartyManager: Cleaning up {entity_type} {entity_id_str} from party in guild {guild_id_str}...")

        # Find the party the entity is in within this guild
        party = await self.get_party_by_member_id(guild_id_str, entity_id_str) 

        if not party:
            return 

        party_id = getattr(party, 'id', None)
        if not party_id:
            print(f"PartyManager: Warning: Found party object with no ID for participant {entity_id_str} in guild {guild_id_str} during cleanup.")
            return 
        party_id_str = str(party_id)


        # Use player_ids_list for internal logic
        member_ids_list = getattr(party, 'player_ids_list', [])
        if isinstance(member_ids_list, list):
            initial_count = len(member_ids_list)
            new_member_ids_list = [mid for mid in member_ids_list if mid != entity_id_str]

            if len(new_member_ids_list) < initial_count:
                party.player_ids_list = new_member_ids_list 
                print(f"PartyManager: Removed {entity_type} {entity_id_str} from member list of party {party_id_str} in guild {guild_id_str}.")
                self.mark_party_dirty(guild_id_str, party_id_str)

                guild_member_map = self._member_to_party_map.get(guild_id_str)
                if guild_member_map and guild_member_map.get(entity_id_str) == party_id_str:
                    del guild_member_map[entity_id_str]

                if not new_member_ids_list:
                    print(f"PartyManager: Party {party_id_str} in guild {guild_id_str} is now empty after {entity_id_str} left. Removing party.")
                    await self.remove_party(party_id_str, guild_id_str, **context) # Pass context
            else:
                print(f"PartyManager: Warning: {entity_type} {entity_id_str} was not found in member list of party {party_id_str} in guild {guild_id_str} during cleanup.")
        else:
            print(f"PartyManager: Warning: Party {party_id_str} player_ids_list data is not a list for guild {guild_id_str}. Cannot clean up participant {entity_id_str}.")


    # --- Methods to manage party members ---

    async def add_member_to_party(self, party_id: str, character_id: str, guild_id: str, context: Dict[str, Any]) -> bool:
        """Adds a character to the specified party."""
        guild_id_str = str(guild_id)
        party_id_str = str(party_id)
        char_id_str = str(character_id)

        party = self.get_party(guild_id_str, party_id_str)
        if not party:
            print(f"PartyManager: Add member failed. Party {party_id_str} not found in guild {guild_id_str}.")
            return False

        # Ensure player_ids_list is being used
        if not hasattr(party, 'player_ids_list') or not isinstance(party.player_ids_list, list):
            print(f"PartyManager: Add member failed. Party {party_id_str} has invalid player_ids_list. Reinitializing.")
            party.player_ids_list = [] # Initialize if missing or wrong type

        if char_id_str in party.player_ids_list:
            print(f"PartyManager: Character {char_id_str} is already in party {party_id_str} (guild {guild_id_str}).")
            return True # Idempotent: already a member

        party.player_ids_list.append(char_id_str)
        
        guild_member_map = self._member_to_party_map.setdefault(guild_id_str, {})
        guild_member_map[char_id_str] = party_id_str
        
        self.mark_party_dirty(guild_id_str, party_id_str)
        print(f"PartyManager: Character {char_id_str} added to party {party_id_str} in guild {guild_id_str}.")
        return True

    async def remove_member_from_party(self, party_id: str, character_id: str, guild_id: str, context: Dict[str, Any]) -> bool:
        """Removes a character from the specified party. Handles leader migration or party disbandment."""
        guild_id_str = str(guild_id)
        party_id_str = str(party_id)
        char_id_str = str(character_id)

        party = self.get_party(guild_id_str, party_id_str)
        if not party:
            print(f"PartyManager: Remove member failed. Party {party_id_str} not found in guild {guild_id_str}.")
            # If char has this party_id, it's an inconsistency. CharacterManager should handle clearing it.
            return False

        if not hasattr(party, 'player_ids_list') or not isinstance(party.player_ids_list, list):
            print(f"PartyManager: Remove member failed. Party {party_id_str} has invalid player_ids_list.")
            return False # Should not happen with proper initialization

        if char_id_str not in party.player_ids_list:
            print(f"PartyManager: Character {char_id_str} not found in party {party_id_str} (guild {guild_id_str}). Cannot remove.")
            return False

        party.player_ids_list.remove(char_id_str)
        
        guild_member_map = self._member_to_party_map.get(guild_id_str)
        if guild_member_map and guild_member_map.get(char_id_str) == party_id_str:
            del guild_member_map[char_id_str]

        print(f"PartyManager: Character {char_id_str} removed from party {party_id_str} player_ids_list in guild {guild_id_str}.")

        if not party.player_ids_list:
            print(f"PartyManager: Party {party_id_str} is now empty. Disbanding party.")
            await self.remove_party(party_id_str, guild_id_str, **context) # remove_party handles full cleanup
            return True # Removal led to disband, so operation is successful in a way

        if getattr(party, 'leader_id', None) == char_id_str:
            # Leader left, assign new leader if members remain
            party.leader_id = party.player_ids_list[0] # Assign first member as new leader
            print(f"PartyManager: Leader {char_id_str} left party {party_id_str}. New leader is {party.leader_id}.")
        
        self.mark_party_dirty(guild_id_str, party_id_str)
        return True

    # async def set_leader(self, party_id: str, entity_id: str, guild_id: str, **kwargs): ... # Change leader, mark dirty. Needs validation (new leader is member).

    async def _get_ready_members_in_location(self, party: "Party", location_id: str, guild_id: str) -> List["Character"]:
        """Helper to get characters in a party at a specific location who are ready for processing."""
        ready_members: List["Character"] = []
        if not self._character_manager:
            print(f"PartyManager: CharacterManager not available in _get_ready_members_in_location for party {party.id} guild {guild_id}.")
            return ready_members

        # Ensure party.player_ids_list is a list of strings
        member_ids = getattr(party, 'player_ids_list', [])
        if not isinstance(member_ids, list):
            print(f"PartyManager: Warning: party {party.id} player_ids_list is not a list in _get_ready_members_in_location.")
            return ready_members

        for member_player_id_str in member_ids:
            if not isinstance(member_player_id_str, str): # Basic type check
                print(f"PartyManager: Warning: Non-string member_id '{member_player_id_str}' in party {party.id} player_ids_list. Skipping.")
                continue

            # Changed get_character_by_player_id to get_character_by_discord_id and removed await
            member_char = self._character_manager.get_character_by_discord_id(discord_user_id=int(member_player_id_str), guild_id=guild_id) # Assuming player_id_str is discord_user_id
            if member_char and member_char.location_id == location_id and member_char.current_game_status == 'ожидание_обработку':
                ready_members.append(member_char)
        return ready_members

    async def check_and_process_party_turn(self, party_id: str, location_id: str, guild_id: str, game_manager: Any) -> None:
        """
        Checks if all party members in a given location are ready for turn processing.
        If so, processes their actions, updates statuses, and notifies them.
        `game_manager` is passed to access other managers like LocationManager and the discord_client.
        """
        print(f"PartyManager: Checking turn for party {party_id} in location {location_id}, guild {guild_id}.")
        party = self.get_party(guild_id=guild_id, party_id=party_id)

        if not party:
            print(f"PartyManager: Party {party_id} not found in guild {guild_id}. Cannot process turn.")
            return

        if not self._character_manager:
            print(f"PartyManager: CharacterManager not available for party {party_id} guild {guild_id}. Cannot process turn.")
            return
        
        # Ensure db_service is available (assuming it's an attribute or accessible via game_manager)
        # For this example, we'll assume self._db_adapter is used for direct DB writes if a service layer isn't specified for party updates.
        if not self._db_adapter: # Changed from self.db_service to self._db_adapter based on existing code
            print(f"PartyManager: DB Adapter not available for party {party_id} guild {guild_id}. Cannot process turn.")
            return

        # Get all members of the party who are in the specified location
        # We need to count total members in location first, then check how many are ready.
        total_members_in_location: List["Character"] = []
        all_member_ids = getattr(party, 'player_ids_list', [])
        if not isinstance(all_member_ids, list): all_member_ids = [] # Ensure it's a list

        for pid_str in all_member_ids:
            if not isinstance(pid_str, str): continue
            # Changed get_character_by_player_id to get_character_by_discord_id and removed await
            char = self._character_manager.get_character_by_discord_id(discord_user_id=int(pid_str), guild_id=guild_id) # Assuming pid_str is discord_user_id
            if char and char.location_id == location_id:
                total_members_in_location.append(char)
        
        if not total_members_in_location:
            print(f"PartyManager: No members of party {party_id} found in location {location_id}. No turn to process here.")
            return

        ready_members_in_location = await self._get_ready_members_in_location(party, location_id, guild_id)

        if len(ready_members_in_location) != len(total_members_in_location):
            print(f"PartyManager: Not all {len(total_members_in_location)} members of party {party.id} in location {location_id} are ready. "
                  f"({len(ready_members_in_location)} are 'ожидание_обработку'). Turn processing deferred.")
            return

        print(f"PartyManager: All {len(ready_members_in_location)} members of party {party.id} in location {location_id} are ready. Processing turn...")

        try:
            # 1. Update party status to 'обработка'
            party.turn_status = 'обработка'
            # Persist: Convert party to dict and update. Assuming DBService has an update_party method
            # or we update the field directly using self._db_adapter.
            # For now, direct update via SQL as other party fields are saved.
            update_sql = "UPDATE parties SET turn_status = ? WHERE id = ? AND guild_id = ?"
            await self._db_adapter.execute(update_sql, (party.turn_status, party.id, guild_id))
            self.mark_party_dirty(guild_id, party.id) # Mark dirty for full save later if needed, though status is directly updated.
            print(f"PartyManager: Party {party.id} status set to 'обработка'.")

            # 2. Prepare actions for ActionProcessor
            # Flatten all submitted actions from all ready members into a single list.
            # Each action will be a dict including character_id, original_input_text, and the action_data itself.
            all_submitted_actions: List[Dict[str, Any]] = []
            for member_char in ready_members_in_location:
                actions_json_str = member_char.collected_actions_json
                member_actions_this_turn: List[Dict[str, Any]] = []
                if actions_json_str:
                    try:
                        member_actions_this_turn = json.loads(actions_json_str)
                        if not isinstance(member_actions_this_turn, list):
                            member_actions_this_turn = []
                    except json.JSONDecodeError:
                        print(f"PartyManager: Could not parse collected_actions_json for char {member_char.id}: {actions_json_str}")
                        member_actions_this_turn = []

                for i, action_data in enumerate(member_actions_this_turn):
                    if isinstance(action_data, dict): # Ensure action_data is a dict
                        all_submitted_actions.append({
                            "character_id": member_char.id,
                            "action_data": action_data, # This is the dict like {'type': 'move', 'target': 'loc_x'}
                            "original_input_text": action_data.get("original_input", action_data.get("type", "N/A")), # Store original text if available
                            "unique_action_id": f"{member_char.id}_action_{i}" # Simple unique ID for this turn
                        })

            print(f"PartyManager: Flattened actions for party {party.id} in location {location_id}: {all_submitted_actions}")

            # --- Placeholder for Conflict Resolution ---
            # conflict_resolver = getattr(game_manager, 'conflict_resolver', None)
            # ordered_actions_to_process = all_submitted_actions # Default to original order
            # if conflict_resolver and hasattr(conflict_resolver, 'analyze_and_order_actions'):
            #     try:
            #         # This method would take the flat list, analyze, and return an ordered list
            #         # It might also modify actions (e.g., mark some as failed due to conflict)
            #         ordered_actions_to_process = await conflict_resolver.analyze_and_order_actions(
            #             guild_id, all_submitted_actions, context
            #         )
            #         print(f"PartyManager: Actions ordered by ConflictResolver: {ordered_actions_to_process}")
            #     except Exception as cr_exc:
            #         print(f"PartyManager: Error during conflict resolution: {cr_exc}")
            #         # Fallback to original order or handle error appropriately
            # else:
            #     print("PartyManager: ConflictResolver not available or method missing, processing in submitted order.")
            actions_to_process_final = all_submitted_actions # Use this list for now

            # 3. Call ActionProcessor
            action_processing_results = {"success": False, "overall_state_changed_for_party": False, "individual_action_results": []}
            # Pass the flat (potentially ordered) list of actions
            # Corrected to use _character_action_processor as per GameManager structure
            if hasattr(game_manager, '_character_action_processor') and game_manager._character_action_processor and actions_to_process_final:
                action_processor = game_manager._character_action_processor
                
                # Determine fallback channel ID for ActionProcessor
                # Using the location's main channel as the primary source.
                location_model_for_ap_chan = await game_manager.location_manager.get_location(location_id, guild_id)
                ctx_channel_id_for_ap = 0 # Default to 0 if no channel found
                if location_model_for_ap_chan and location_model_for_ap_chan.channel_id:
                    try:
                        ctx_channel_id_for_ap = int(location_model_for_ap_chan.channel_id)
                    except ValueError:
                        print(f"PartyManager: Invalid channel_id '{location_model_for_ap_chan.channel_id}' for location {location_id}. Using 0 for AP.")

                print(f"PartyManager: Calling ActionProcessor.process_party_actions for party {party.id}. Fallback Channel ID for AP: {ctx_channel_id_for_ap}")
                
                # Ensure all managers and game_state are correctly passed from game_manager
                if not (hasattr(game_manager, 'game_state') and
                        hasattr(game_manager, 'character_manager') and # Should be self._character_manager
                        hasattr(game_manager, 'location_manager') and
                        hasattr(game_manager, 'event_manager') and
                        hasattr(game_manager, 'rule_engine') and
                        hasattr(game_manager, 'openai_service')):
                    print(f"PartyManager: CRITICAL - GameManager is missing one or more required components for ActionProcessor. Aborting action processing.")
                    # Set party to an error state
                    party.turn_status = 'ошибка_конфиг_АП'
                    await self._db_adapter.execute(update_sql, (party.turn_status, party.id, guild_id))
                    return # Cannot proceed

                # The context dictionary current_context_for_action_processor is no longer needed for this call.
                # Its information (guild_id, party_id, location_id) would be available via game_manager's attributes
                # or game_state if needed by the processor, or passed differently if essential.

                # Prepare context for process_party_actions
                party_action_context = {
                    "report_channel_id": ctx_channel_id_for_ap,
                    # Add any other specific context CharacterActionProcessor.process_party_actions might need
                    # from PartyManager's perspective. For now, report_channel_id is key.
                }

                action_processing_results = await action_processor.process_party_actions(
                    game_manager=game_manager, # Pass the full GameManager
                    guild_id=guild_id,
                    actions_to_process=actions_to_process_final,
                    context=party_action_context
                )
                print(f"PartyManager: ActionProcessor results for party {party.id}: {action_processing_results}")

                # Update overall_state_changed based on the new return structure
                if action_processing_results.get("overall_state_changed_for_party"):
                    pass # overall_state_changed_for_party is already managed by CharacterActionProcessor's return

            elif not actions_to_process_final: # Check if the final list of actions is empty
                print(f"PartyManager: No actions to process for party {party.id}. Skipping ActionProcessor call.")
                action_processing_results["success"] = True # No actions, so technically successful batch
            else: # This case should ideally not be hit if actions_to_process_final is empty or if action_processor is missing
                processor_target_name = '_character_action_processor' if hasattr(game_manager, '_character_action_processor') else 'action_processor (generic)'
                print(f"PartyManager: {processor_target_name} not found on game_manager or no actions. Cannot process for party {party.id}.")
                party.turn_status = 'ошибка_нет_АП_или_действий'
                await self._db_adapter.execute(update_sql, (party.turn_status, party.id, guild_id))
                return

                return # Return early as no action processing can occur


            # Check overall success from ActionProcessor's batch job perspective.
            # This 'success' flag in action_processing_results indicates if the batch processing itself was successful,
            # not necessarily if all individual actions succeeded.
            if not action_processing_results.get("success"):
                print(f"PartyManager: Action processing BATCH FAILED for party {party.id}. Details: {action_processing_results.get('individual_action_results', 'N/A')}. Party status may need manual review or reset.")
                # Consider setting a specific error status for the party if the batch processing itself fails
                # For example, if process_party_actions throws an unhandled exception.
                # party.turn_status = 'ошибка_пакетной_обработки_АП'
                # await self._db_adapter.execute(update_sql, (party.turn_status, party.id, guild_id))
                # The individual_action_results will contain success/failure for each action.

            # 4. Post-Action Processing: Update character statuses and clear actions
            # This happens regardless of individual action successes/failures, as the turn attempt is over.
            # The actual character objects might have been modified by ActionProcessor/RuleEngine and saved.
            # We re-fetch them here to ensure we have the latest state if we need to make further changes
            # or rely on their state for notifications.

            # The modified_entities from action_processing_results.get("final_modified_entities_this_turn", [])
            # contains the Character objects as they were at the end of their respective start_action calls.
            # We need to iterate through ready_members_in_location to reset their game status.

            for member_char_original_state in ready_members_in_location:
                # Re-fetch to ensure we have the latest version if it was modified and replaced in memory
                # (though granular saves should mean the instance is the same or updated)
                member_char_updated = await self._character_manager.get_character(guild_id, member_char_original_state.id)
                if member_char_updated:
                    member_char_updated.current_game_status = 'исследование'
                    member_char_updated.collected_actions_json = '[]'
                    # Save the character after updating status and clearing actions
                    await self._character_manager.save_character(member_char_updated, guild_id)
                else:
                    print(f"PartyManager: WARNING - Character {member_char_original_state.id} not found after action processing for party {party.id} when resetting status.")

            print(f"PartyManager: Characters of party {party.id} in location {location_id} reset to 'исследование' and actions cleared.")

            # 5. Update party status back to 'сбор_действий' (or a default like 'активна')
            party.turn_status = 'сбор_действий'
            await self._db_adapter.execute(update_sql, (party.turn_status, party.id, guild_id))
            self.mark_party_dirty(guild_id, party.id)
            print(f"PartyManager: Party {party.id} status set back to 'сбор_действий'.")

            # 6. Notify Players with a detailed report
            location_name_for_report = location_id # Default
            if hasattr(game_manager, 'location_manager') and game_manager.location_manager:
                loc_name = game_manager.location_manager.get_location_name(guild_id, location_id)
                if loc_name: location_name_for_report = loc_name

            report_message = self.format_turn_report(
                individual_action_results=action_processing_results.get("individual_action_results", []),
                party_name=getattr(party, 'name', party_id),
                location_name=location_name_for_report,
                character_manager=self._character_manager, # Pass character_manager for name resolution
                guild_id=guild_id # Pass guild_id for character name resolution
            )
            
            if game_manager and hasattr(game_manager, 'location_manager') and hasattr(game_manager, 'discord_client'):
                location_model = await game_manager.location_manager.get_location(location_id, guild_id) # This seems to be fetching a dict, not Location model

                # Assuming get_location_instance returns a dict-like structure that might have channel_id
                # Or if game_manager.location_manager.get_location returns Location model instance.
                # For now, let's assume get_location_channel can work with location_id.
                target_channel_id_int = None
                if hasattr(game_manager.location_manager, 'get_location_channel'):
                    target_channel_id_int = game_manager.location_manager.get_location_channel(guild_id, location_id)

                if target_channel_id_int:
                    discord_channel = game_manager.discord_client.get_channel(target_channel_id_int)
                    if discord_channel:
                        # Split long messages if necessary
                        max_len = 1980 # Discord max message length is 2000
                        if len(report_message) > max_len:
                            parts = [report_message[i:i+max_len] for i in range(0, len(report_message), max_len)]
                            for part_num, part in enumerate(parts):
                                await discord_channel.send(f"```\n{part}\n```" + (f" (Part {part_num+1}/{len(parts)})" if len(parts) > 1 else ""))
                        else:
                            await discord_channel.send(f"```\n{report_message}\n```")
                        print(f"PartyManager: Sent turn report to channel {target_channel_id_int} for party {party.id}.")
                    else:
                        print(f"PartyManager: ERROR - Could not find channel {target_channel_id_int} to send report for party {party.id}.")
                else:
                    print(f"PartyManager: ERROR - Location {location_id} channel_id not found for party {party.id} report.")
            else:
                print(f"PartyManager: ERROR - GameManager, LocationManager, or DiscordClient not available. Cannot send report for party {party.id}.")

        except Exception as e:
            print(f"PartyManager: CRITICAL ERROR during check_and_process_party_turn for party {party.id} in location {location_id}: {e}")
            traceback.print_exc()
            # Attempt to set party status to an error state if possible
            try:
                party.turn_status = 'ошибка_обработки_крит'
                update_sql = "UPDATE parties SET turn_status = ? WHERE id = ? AND guild_id = ?"
                await self._db_adapter.execute(update_sql, (party.turn_status, party.id, guild_id))
                print(f"PartyManager: Party {party.id} status set to 'ошибка_обработки_крит' due to exception.")
            except Exception as e_crit:
                print(f"PartyManager: Failed to set party status to error state after critical error: {e_crit}")

    def format_turn_report(
        self,
        individual_action_results: List[Dict[str, Any]],
        party_name: str,
        location_name: str,
        character_manager: "CharacterManager", # Keep this
        guild_id: str # Add this
    ) -> str:
        report_parts = [
            f"Turn Report for Party: {party_name} in {location_name}",
            "----------------------------------------------------"
        ]
        if not individual_action_results:
            report_parts.append("No actions were processed this turn.")
        else:
            for result in individual_action_results:
                char_id = result.get("character_id")
                char_name = char_id # Default to ID
                if char_id and character_manager:
                    # Use guild_id to fetch the character
                    char = character_manager.get_character(guild_id, char_id)
                    if char:
                        char_name = getattr(char, 'name', char_id)

                action_text = result.get("action_original_text", "Unknown action")
                outcome_message = result.get("message", "No outcome message.")
                success_str = "Success" if result.get("success") else "Failure"

                report_parts.append(f"Character: {char_name}")
                report_parts.append(f"Action: {action_text}")
                report_parts.append(f"Status: {success_str}")
                report_parts.append(f"Outcome: {outcome_message}")
                report_parts.append("---")

        report_parts.append("----------------------------------------------------")
        report_parts.append("End of Turn.")
        return "\n".join(report_parts)

# --- Конец класса PartyManager ---

    async def save_party(self, party: "Party", guild_id: str) -> bool:
        """
        Saves a single party to the database using an UPSERT operation.
        """
        if self._db_adapter is None:
            print(f"PartyManager: Error: DB adapter missing for guild {guild_id}. Cannot save party {getattr(party, 'id', 'N/A')}.")
            return False

        guild_id_str = str(guild_id)
        party_id = getattr(party, 'id', None)

        if not party_id:
            print(f"PartyManager: Error: Party object is missing an 'id'. Cannot save.")
            return False

        party_internal_guild_id = getattr(party, 'guild_id', None)
        if party_internal_guild_id and str(party_internal_guild_id) != guild_id_str:
            print(f"PartyManager: Error: Party {party_id} guild_id ({party_internal_guild_id}) does not match provided guild_id ({guild_id_str}).")
            return False
        # If party object doesn't have guild_id, we assume it's correct for the given guild_id context.

        try:
            party_data = party.to_dict() # This already JSONifies player_ids_list into 'player_ids'

            # Prepare data for DB columns based on 'parties' table schema
            # Columns: id, guild_id, name, leader_id, player_ids, current_location_id,
            #          turn_status, state_variables, current_action

            # action_queue is in party_data from to_dict(), but not in DB schema from save_state.
            # We'll merge it into state_variables if it's not None.
            final_state_variables = party_data.get('state_variables', {})
            if not isinstance(final_state_variables, dict): final_state_variables = {}

            action_queue_data = party_data.get('action_queue')
            if action_queue_data is not None: # Only add if it exists and is not None
                final_state_variables['action_queue'] = action_queue_data


            db_params = (
                party_data.get('id'),
                guild_id_str, # Explicitly use the provided guild_id
                json.dumps(party_data.get('name_i18n', {})), # Save i18n name as JSON
                party_data.get('leader_id'),
                party_data.get('player_ids'), # This is already a JSON string from party.to_dict()
                party_data.get('current_location_id'),
                party_data.get('turn_status'),
                json.dumps(final_state_variables),
                json.dumps(party_data.get('current_action')) # Can be None
            )

            upsert_sql = '''
            INSERT OR REPLACE INTO parties (
                id, guild_id, name_i18n, leader_id, player_ids,
                current_location_id, turn_status, state_variables, current_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            # 9 columns, 9 placeholders.

            await self._db_adapter.execute(upsert_sql, db_params)
            print(f"PartyManager: Successfully saved party {party_id} for guild {guild_id_str}.")

            if guild_id_str in self._dirty_parties and party_id in self._dirty_parties[guild_id_str]:
                self._dirty_parties[guild_id_str].discard(party_id)
                if not self._dirty_parties[guild_id_str]:
                    del self._dirty_parties[guild_id_str]

            # PartyManager cache _parties stores Party objects.
            # Ensure the cached object is the one that was passed and now saved.
            self._parties.setdefault(guild_id_str, {})[party_id] = party

            # Also, update the _member_to_party_map if members changed.
            # This requires comparing old vs new state or just rebuilding for this party.
            # For simplicity, let's remove old mappings for this party's previous members (if known)
            # and add new mappings. This is tricky without old state.
            # A safer bet is that if save_party is called, the Party object `party` is the source of truth.
            current_members = getattr(party, 'player_ids_list', [])
            if isinstance(current_members, list):
                guild_member_map = self._member_to_party_map.setdefault(guild_id_str, {})
                # Remove old mappings that might point to this party_id but member is no longer in party
                # This is not perfect as it doesn't capture members removed from other parties to join this one.
                # A full rebuild of map or more complex diffing would be needed for 100% accuracy on complex member changes.
                keys_to_remove = [m_id for m_id, p_id in guild_member_map.items() if p_id == party_id and m_id not in current_members]
                for k in keys_to_remove:
                    del guild_member_map[k]
                # Add/update mappings for current members
                for member_id_str in current_members:
                    guild_member_map[member_id_str] = party_id

            return True

        except Exception as e:
            print(f"PartyManager: Error saving party {party_id} for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            return False

print("DEBUG: party_manager.py module loaded.")
