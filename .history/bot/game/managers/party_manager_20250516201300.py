# bot/game/managers/party_manager.py

from __future__ import annotations
import json
import uuid # Импортируем uuid, т.к. используется для Party ID
import traceback
import asyncio
# Импорт базовых типов
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING # Импортируем Set и TYPE_CHECKING


# --- Imports needed ONLY for Type Checking ---
# Эти импорты нужны ТОЛЬКО для статического анализа (Pylance/Mypy).
# Это разрывает циклы импорта при runtime и помогает Pylance правильно резолвить типы.
# Используйте строковые литералы ("ClassName") для type hints в __init__ и методах
# для классов, импортированных здесь.
if TYPE_CHECKING:
    # Добавляем адаптер БД
    from bot.database.sqlite_adapter import SqliteAdapter # <-- Moved here
    # Добавляем модели
    from bot.game.models.party import Party  # <-- Moved here, Party модель для аннотаций

    # Добавляем менеджеры
    from bot.game.managers.npc_manager import NpcManager # <-- Moved here
    from bot.game.managers.character_manager import CharacterManager # <-- Moved here
    from bot.game.managers.combat_manager import CombatManager # <-- Moved here
    # Добавляем другие менеджеры, если они передаются в __init__ или используются в аннотациях методов
    # from bot.game.managers.event_manager import EventManager # если нужен
    # from bot.game.managers.location_manager import LocationManager
    # from bot.game.managers.rule_engine import RuleEngine
    # from bot.game.managers.item_manager import ItemManager
    # from bot.game.managers.time_manager import TimeManager
    # from bot.game.managers.status_manager import StatusManager
    # from bot.game.managers.crafting_manager import CraftingManager
    # from bot.game.managers.economy_manager import EconomyManager


# --- Imports needed at Runtime ---
# Для PartyManager обычно нужен только прямой импорт модели Party (если она используется для isinstance или from_dict) и утилит.
# from bot.game.models.party import Party # Прямой импорт не нужен, т.к. используется только в аннотациях и from_dict
# from bot.database.sqlite_adapter import SqliteAdapter # Прямой импорт не нужен, т.к. используется self._db_adapter


print("DEBUG: party_manager.py module loaded.")


class PartyManager:
    """
    Менеджер для управления группами (parties).
    Хранит состояние всех партий, CRUD, проверку busy-статуса, и т.п.
    """
    # Required args для PersistenceManager
    # ИСПРАВЛЕНИЕ: Добавляем аннотацию типа List[str]
    required_args_for_load: List[str] = ["guild_id"] # Если загрузка per-guild
    # ИСПРАВЛЕНИЕ: Добавляем аннотацию типа List[str]
    required_args_for_save: List[str] = ["guild_id"] # Если сохранение per-guild
    # ИСПРАВЛЕНИЕ: Добавляем аннотацию типа List[str]
    required_args_for_rebuild: List[str] = ["guild_id"] # Если rebuild per-guild


    def __init__(self,
                 # Используем строковые литералы для всех инжектированных зависимостей
                 db_adapter: Optional["SqliteAdapter"] = None, # <-- Use string literal!
                 settings: Optional[Dict[str, Any]] = None,
                 npc_manager: Optional["NpcManager"] = None, # <-- Use string literal!
                 character_manager: Optional["CharacterManager"] = None, # <-- Use string literal!
                 combat_manager: Optional["CombatManager"] = None, # <-- Use string literal!
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

        # Кеш партий: {party_id: Party}
        # ИСПРАВЛЕНИЕ: Аннотация кеша использует строковый литерал "Party"
        # Если кеш по гильдиям, _parties: Dict[str, Dict[str, "Party"]] = {guild_id: {party_id: Party_object}}
        self._parties: Dict[str, "Party"] = {} # Party модель теперь только для аннотаций

        # Для оптимизации персистенции
        # ИСПРАВЛЕНИЕ: Добавляем аннотацию типа Set[str]
        self._dirty_parties: Set[str] = set()
        # ИСПРАВЛЕНИЕ: Добавляем аннотацию типа Set[str]
        self._deleted_parties: Set[str] = set()

        print("PartyManager initialized.")

    # --- Методы получения ---
    # Используем строковый литерал в аннотации возвращаемого типа
    def get_party(self, party_id: str) -> Optional["Party"]: # Аннотация Optional["Party"]
        """Получить объект партии по ID (из кеша)."""
        return self._parties.get(party_id)

    # Используем строковый литерал в аннотации возвращаемого типа
    def get_all_parties(self) -> List["Party"]: # Аннотация List["Party"]
        """Получить список всех загруженных партий (из кеша)."""
        return list(self._parties.values())

    # TODO: Implement get_party_by_member_id(entity_id, context) method (used in RuleEngine)
    # def get_party_by_member_id(self, entity_id: str, **kwargs: Any) -> Optional["Party"]: ...


    # --- Методы CRUD ---

    async def create_party(self, leader_id: str, member_ids: List[str], **kwargs: Any) -> Optional[str]: # Добавлена аннотация **kwargs
        """
        Создает новую партию с лидером и списком участников.
        """
        if self._db_adapter is None:
            print("PartyManager: No DB adapter.")
            # TODO: В режиме без DB, возможно, создать партию только в памяти и не сохранять.
            # Сейчас возвращаем None, т.к. нет куда сохранять.
            return None

        # TODO: Валидация (участники существуют, не в других партиях, leader_id в списке member_ids)
        # Используйте self._character_manager, self._npc_manager, self.get_party_by_member_id

        try:
            new_id = str(uuid.uuid4())
            # Добавляем guild_id, если партии per-guild
            guild_id = kwargs.get('guild_id')
            if guild_id is None: raise ValueError("Missing 'guild_id' in kwargs for create_party.")

            party_data = {
                'id': new_id,
                'guild_id': guild_id, # Добавляем guild_id при создании
                'leader_id': leader_id,
                'member_ids': member_ids.copy(),
                # TODO: Добавить другие поля Party модели
                'state_variables': {},
                'current_action': None, # Групповое действие партии
                # TODO: location_id для партии, если применимо?
            }
            # Party.from_dict(data: Dict) -> Party
            party = Party.from_dict(party_data) # Создание объекта модели Party (нужен прямой доступ к классу Party здесь)
            # Однако, мы перенесли Party в TYPE_CHECKING. Значит, from_dict ДОЛЖЕН БЫТЬ СТАТИЧЕСКИМ МЕТОДОМ КЛАССА, И ЕГО НУЖНО ВЫЗЫВАТЬ ЧЕРЕЗ МОДУЛЬ ИЛИ ДИНАМИЧЕСКИ.
            # Или Party не должна быть только в TYPE_CHECKING, если ее статические методы нужны.
            # Наилучший подход: импортировать модели напрямую, если они используются при runtime (from_dict, isinstance).
            # ОТКАТИМ перемещение Party в TYPE_CHECKING, импортируем напрямую.

        # ВОЗВРАЩАЕМ ПРЯМОЙ ИМПОРТ Party
        except ImportError:
            print("PartyManager: CRITICAL: Party model not found.")
            # TODO: Обработка ошибки импорта модели
            return None # Cannot proceed without Party model


        # ВАЖНО: Прямой импорт Party НЕОБХОДИМ для Party.from_dict()


        # ВОЗВРАЩАЕМ ПРЯМОЙ ИМПОРТ Party:
        from bot.game.models.party import Party


        class PartyManager:
            # ... (остальная часть класса PartyManager, как до этого сообщения) ...
            # ... (методы __init__, get_party, get_all_parties, get_party_by_member_id, is_party_busy) ...


            async def create_party(self, leader_id: str, member_ids: List[str], **kwargs: Any) -> Optional[str]:
                # ... (начало create_party, валидация, получение guild_id) ...

                try:
                    new_id = str(uuid.uuid4())
                    # Добавляем guild_id, если партии per-guild
                    guild_id = kwargs.get('guild_id')
                    if guild_id is None: raise ValueError("Missing 'guild_id' in kwargs for create_party.")

                    party_data = {
                        'id': new_id,
                        'guild_id': str(guild_id), # Сохраняем как строку для консистентности
                        'leader_id': leader_id,
                        'member_ids': member_ids.copy(),
                        # TODO: Добавить другие поля Party модели
                        'state_variables': {},
                        'current_action': None, # Групповое действие партии
                        # TODO: location_id для партии, если применимо?
                    }
                    # ВАЖНО: Вызываем СТАТИЧЕСКИЙ метод from_dict на классе Party
                    party = Party.from_dict(party_data) # Требует прямого импорта Party


                    # Добавляем в кеш (per-guild cache?)
                    # Если _parties Dict[str, Dict[str, Party]] = {guild_id: {party_id: Party}}, то:
                    self._parties.setdefault(str(guild_id), {})[new_id] = party
                    # Если кеш плоский {party_id: Party}:
                    # self._parties[new_id] = party # Неправильно для многогильдийности, если load_state загружает per-guild

                    # Предполагаем, что кеш _parties per-guild:
                    # self._parties.setdefault(str(guild_id), {})[new_id] = party


                    # Помечаем dirty (per-party или per-guild?)
                    # Если _dirty_parties Set[str]:
                    # self._dirty_parties.add(new_id) # Неправильно для per-guild dirty state
                    # Если _dirty_parties Dict[str, Set[str]] = {guild_id: set()}:
                    self._dirty_parties.setdefault(str(guild_id), set()).add(new_id) # Помечаем dirty per-guild


                    print(f"PartyManager: Party {new_id} created for guild {guild_id}. Leader: {leader_id}. Members: {member_ids}")
                    # TODO: Уведомить участников?

                    return new_id # Возвращаем ID созданной партии

                except Exception as e:
                    print(f"PartyManager: Error creating party for leader {leader_id}: {e}")
                    import traceback
                    print(traceback.format_exc())
                    return None # Возвращаем None при ошибке


            async def remove_party(self, party_id: str, **kwargs: Any) -> Optional[str]: # Добавлена аннотация **kwargs
                """
                Удаляет партию и помечает для удаления в БД.
                Принимает guild_id в kwargs (для per-guild clean_up/persistence).
                """
                party = self.get_party(party_id) # Type: Optional["Party"]
                if not party:
                    print(f"PartyManager: Party {party_id} not found.")
                    return None

                # Получаем guild_id из объекта партии (если есть) или из kwargs.
                guild_id = getattr(party, 'guild_id', None)
                if guild_id is None:
                     guild_id = kwargs.get('guild_id')
                     if guild_id is None: # Если нет ни в объекте, ни в kwargs
                          print(f"PartyManager: Warning: Cannot determine guild_id for party {party_id} removal.")
                          # Решите, что делать, если guild_id неизвестен при удалении партии.
                          # Возможно, нужно просто удалить по ID без фильтрации по гильдии в БД? ОПАСНО!
                          # Если партии per-guild, guild_id ОБЯЗАТЕЛЕН для удаления из кешей и БД.
                          raise ValueError("Missing 'guild_id' for remove_party.")
                     else: guild_id = str(guild_id) # Убедимся, что guild_id строка

                else: guild_id = str(guild_id) # Убедимся, что guild_id из объекта партии - строка


                print(f"PartyManager: Removing party {party_id} for guild {guild_id}. Leader: {getattr(party, 'leader_id', 'N/A')}")

                # Очистка участников (например, сбросить party_id)
                # Используем self._npc_manager, self._character_manager
                member_ids = getattr(party, 'member_ids', []) # Убедимся, что member_ids существует

                # Передаем context в cleanup методы
                cleanup_context: Dict[str, Any] = {
                    'party_id': party_id,
                    'party': party, # Передаем объект партии
                    'guild_id': guild_id, # Передаем guild_id
                    # TODO: Добавить другие необходимые менеджеры, сервисы из self._ в cleanup_context
                    'character_manager': self._character_manager, # Нужен для чистки персонажей
                    'npc_manager': self._npc_manager, # Нужен для чистки NPC
                    'combat_manager': self._combat_manager, # Участники партии могут быть в бою - PartyManager должен снять их оттуда?
                                                             # Или это делают менеджеры сущностей при cleanup_from_party?
                }
                cleanup_context.update(kwargs) # Добавляем kwargs переданные в remove_party

                if member_ids:
                    print(f"PartyManager: Cleaning up {len(member_ids)} members for party {party_id}.")
                    # Итерируем по копии списка member_ids, т.к. менеджеры сущностей могут менять атрибуты party_id
                    for entity_id in list(member_ids):
                         try:
                             # Определяем тип сущности и находим соответствующий менеджер.
                             # В Party модели участники могут быть Character или NPC.
                             # Нужна мапа entity_id -> entity_type или структура participants как в Combat.
                             # Предполагаем, что member_ids это список ID, и их тип определяется тем, в каком менеджере они зарегистрированы.
                             # Или участники в Party модели хранятся как [{entity_id, entity_type}, ...].
                             # Если member_ids - просто список ID, нужно запросить их у менеджеров сущностей.
                             # Давайте предположим, что CharacterManager и NpcManager имеют методы типа get_entity(id) или get_by_party_id(party_id).
                             entity_type = None # Determine entity type (Character or NPC)

                             if self._character_manager and hasattr(self._character_manager, 'get_character'):
                                  char = self._character_manager.get_character(entity_id) # type: Optional["Character"]
                                  if char and getattr(char, 'party_id', None) == party_id: entity_type = "Character"

                             if entity_type is None and self._npc_manager and hasattr(self._npc_manager, 'get_npc'):
                                  npc = self._npc_manager.get_npc(entity_id) # type: Optional["NPC"]
                                  if npc and getattr(npc, 'party_id', None) == party_id: entity_type = "NPC"

                             if entity_type:
                                  # Находим менеджер для сущности и вызываем clean_up_from_party.
                                  # Менеджеры сущностей (CharacterManager, NpcManager) должны иметь метод clean_up_from_party(entity_id, party_id, context).
                                  manager = None # type: Optional[Any]
                                  if entity_type == "Character" and self._character_manager and hasattr(self._character_manager, 'clean_up_from_party'): manager = self._character_manager
                                  elif entity_type == "NPC" and self._npc_manager and hasattr(self._npc_manager, 'clean_up_from_party'): manager = self._npc_manager
                                  # TODO: Другие типы сущностей/менеджеров

                                  if manager:
                                       await getattr(manager, 'clean_up_from_party')(entity_id, party_id, context=cleanup_context) # Вызываем clean_up_from_party
                                       #print(f"PartyManager: Cleaned up member {entity_type} {entity_id} from party {party_id}.") # Debug
                                  else:
                                       print(f"PartyManager: Warning: No suitable manager found for party member {entity_type} {entity_id} for cleanup from party {party_id}. Skipping cleanup for this member.")
                             else:
                                print(f"PartyManager: Warning: Could not determine type or find entity object for member {entity_id} in party {party_id} during cleanup. Skipping cleanup for this member.")

                         except Exception as e:
                            print(f"PartyManager: Error during cleanup for member {entity_id} in party {party_id}: {e}")
                            import traceback
                            print(traceback.format_exc())
                            # Не пробрасываем ошибку, чтобы очистить других участников.

                print(f"PartyManager: Finished member cleanup for party {party_id}.")

                # TODO: Дополнительная очистка Party-специфичных эффектов (например, Party-wide статусы?)
                # StatusManager может иметь метод clean_up_for_party(party_id, context)
                # if self._status_manager and hasattr(self._status_manager, 'clean_up_for_party'):
                #      try: await self._status_manager.clean_up_for_party(party_id, context=cleanup_context)
                #      except Exception as e: ... error handling ...


                # TODO: Очистка групповых действий партии (например, если партия была в бою как одна сущность?)
                # Если CombatManager поддерживает Party как участника боя, его нужно уведомить, что партия распалась.
                # CombatManager может иметь метод party_disbanded(party_id, context)
                # if self._combat_manager and hasattr(self._combat_manager, 'party_disbanded'):
                #      try: await self._combat_manager.party_disbanded(party_id, context=cleanup_context)
                #      except Exception as e: ... error handling ...


                # TODO: Удаление группового действия партии из очереди или текущего действия
                # Если у Party модели есть action_queue и current_action атрибуты, их нужно сбросить/очистить.
                # Это можно сделать непосредственно в Party объекте, а затем пометить его dirty.
                if hasattr(party, 'current_action'): party.current_action = None
                if hasattr(party, 'action_queue'): party.action_queue = []


                # Помечаем dirty (state_variables, current_action, action_queue)
                self.mark_party_dirty(party_id) # Нужен метод mark_party_dirty


                # Удаляем из кеша активных партий
                # Если _parties плоский:
                self._parties.pop(party_id, None) # Удаляем из глобального кеша активных партий
                # Если _parties по гильдиям:
                # if guild_id in self._parties: self._parties[guild_id].pop(party_id, None)

                # Помечаем партию для удаления из БД (PartyManager сам удаляет из БД при save_state)
                # Если PartyManager имеет _deleted_parties Set[str], добавляем ID туда.
                # Если _deleted_parties Set[str] глобальный:
                self._deleted_parties.add(party_id)
                # Если _deleted_parties Dict[str, Set[str]] = {guild_id: set()}:
                # self._deleted_parties.setdefault(guild_id, set()).add(party_id)


                print(f"PartyManager: Party {party_id} fully removed from cache and marked for deletion.")


            def is_party_busy(self, party_id: str) -> bool:
                """
                Считает, занята ли партия групповым действием.
                """
                party = self.get_party(party_id) # Type: Optional["Party"]
                if not party:
                    # Партия не найдена - не может быть занята. Лог предупреждения, т.к. вызов для несуществующей партии.
                    print(f"PartyManager: Warning: is_party_busy called for non-existent party {party_id}.")
                    return False
                # Party модель должна иметь атрибут current_action
                return getattr(party, 'current_action', None) is not None


            # Methods for managing Party Group Actions (process_tick, start, add_to_queue)
            # Эти методы вызываются WorldSimulationProcessor
            # TODO: Implement process_tick(party_id, game_time_delta, **kwargs)
            # TODO: Implement start_group_action(party_id, action_data, **kwargs)
            # TODO: Implement add_group_action_to_queue(party_id, action_data, **kwargs)
            # TODO: Implement complete_group_action(party_id, completed_action_data, **kwargs) - Delegates to PartyActionHandlerRegistry
            # TODO: Implement select_next_group_action(party_id, **kwargs) - AI logic for Party

            # Party Action Processor process_tick logic might be here, or delegated to PartyActionProcessor.
            # Судя по GameManager, WorldSimulationProcessor вызывает PartyActionProcessor.process_tick.
            # PartyManager сам не обрабатывает тик действия группы, он только хранит party.current_action и party.action_queue.

            # TODO: Implement methods to manage party members (add/remove member)


            # Methods for persistence (called by PersistenceManager):
            # Эти методы должны работать per-guild
            # required_args_for_load, required_args_for_save, required_args_for_rebuild уже определены как атрибуты класса

            async def save_state(self, guild_id: str, **kwargs: Any) -> None:
                """Сохраняет измененные/удаленные партии для определенной гильдии."""
                if self._db_adapter is None:
                    print(f"PartyManager: Warning: Cannot save parties for guild {guild_id}, DB adapter missing.")
                    return

                print(f"PartyManager: Saving parties for guild {guild_id}...")

                # TODO: Implement saving logic for PartyManager.
                # 1. Соберите партии для этой гильдии, которые нужно сохранить (активные + измененные).
                #    Если кеш _parties плоский, фильтруйте по party.guild_id == guild_id.
                #    Если кеш по гильдиям, используйте self._parties.get(guild_id, {}).values()
                #    Добавьте партии из _dirty_parties (Set[str]), которые принадлежат этой гильдии и еще в кеше.
                parties_to_save: List["Party"] = []
                # party_ids_to_save_from_dirty: Set[str] = set()
                # if hasattr(self, '_dirty_parties') and isinstance(self._dirty_parties, Set):
                #      # Filter dirty IDs by guild_id and check if they are in кеше
                #      party_ids_to_save_from_dirty = {pid for pid in self._dirty_parties if self.get_party(pid) and getattr(self.get_party(pid), 'guild_id', None) == guild_id}
                #      parties_to_save.extend([self.get_party(pid) for pid in party_ids_to_save_from_dirty if self.get_party(pid) is not None])

                # 2. Соберите IDs партий, помеченных для удаления из DB (из _deleted_parties).
                #    Если _deleted_parties Set[str] глобальный, нужно проверять guild_id при удалении SQL.
                #    Если _deleted_parties Dict[str, Set[str]] = {guild_id: set()}, используйте этот Set для guild_id.
                party_ids_to_delete: Set[str] = set()
                # if hasattr(self, '_deleted_parties') and isinstance(self._deleted_parties, Set): # Assuming _deleted_parties is global
                #      party_ids_to_delete = {pid for pid in self._deleted_parties if self.get_party(pid) is None or getattr(self.get_party(pid), 'guild_id', None) == guild_id} # Удаляем только удаленные И принадлежащие гильдии.
                #      # Если _deleted_parties по гильдиям:
                #      # party_ids_to_delete = self._deleted_parties.get(str(guild_id), set())


                # 3. Используйте self._db_adapter.execute/execute_many с SQL (INSERT OR REPLACE, DELETE).
                #    Для INSERT OR REPLACE: SQL с колонками id, guild_id, leader_id, member_ids, state_variables, current_action
                #    Для DELETE: SQL "WHERE guild_id = ? AND id IN (...)"

                print(f"PartyManager: Save state complete for guild {guild_id}. (Not implemented)") # Placeholder


            async def load_state(self, guild_id: str, **kwargs: Any) -> None:
                """Загружает партии для определенной гильдии."""
                if self._db_adapter is None:
                    print(f"PartyManager: Warning: Cannot load parties for guild {guild_id}, DB adapter missing.")
                    # TODO: Load placeholder data
                    return

                print(f"PartyManager: Loading parties for guild {guild_id}...")

                # TODO: Implement loading logic for PartyManager.
                # 1. Очистите кеш партий для этой гильдии (если кеш per-guild).
                #    Если _parties плоский {party_id: Party}, это БАГ при многогильдийности.
                #    self._parties.clear() # <-- ВРЕМЕННО ОЧИЩАЕТ ВСЕХ
                #    _dirty_parties и _deleted_parties для этой гильдии тоже очистить.


                rows = []
                try:
                    # 2. Выполните SQL SELECT FROM parties WHERE guild_id = ?
                    sql = '''
                    SELECT id, guild_id, leader_id, member_ids, state_variables, current_action
                    FROM parties
                    WHERE guild_id = ?
                    '''
                    rows = await self._db_adapter.fetchall(sql, (str(guild_id),)) # Filter by guild_id
                    print(f"PartyManager: Found {len(rows)} parties in DB for guild {guild_id}.")

                except Exception as e:
                    print(f"PartyManager: ❌ CRITICAL ERROR executing DB fetchall for parties for guild {guild_id}: {e}")
                    import traceback
                    print(traceback.format_exc())
                    # TODO: Handle critical error
                    raise # Пробрасываем критическую ошибку

                # 3. Для каждой строки создайте объект Party (Party.from_dict)
                loaded_count = 0
                # Если _parties плоский, загружаем в него
                # Если per-guild: guild_parties_cache = self._parties.setdefault(str(guild_id), {})
                for row in rows:
                     data = dict(row)
                     try:
                          # Validate and parse data
                          party_id = data.get('id')
                          loaded_guild_id = data.get('guild_id')

                          if party_id is None or str(loaded_guild_id) != str(guild_id):
                              print(f"PartyManager: Warning: Skipping party with invalid ID ('{party_id}') or mismatched guild ('{loaded_guild_id}') during load for guild {guild_id}.")
                              continue

                          # Parse JSON fields
                          data['member_ids'] = json.loads(data.get('member_ids') or '[]')
                          data['state_variables'] = json.loads(data.get('state_variables') or '{}')
                          # current_action can be None
                          current_action_data = data.get('current_action')
                          data['current_action'] = json.loads(current_action_data) if current_action_data is not None else None

                          # Ensure required fields exist and have correct types after parsing
                          data['id'] = str(party_id)
                          data['guild_id'] = str(loaded_guild_id)
                          if data.get('leader_id') is None: print(f"PartyManager: Warning: Party {party_id} has no leader_id.")
                          if not isinstance(data.get('member_ids'), list): print(f"PartyManager: Warning: Party {party_id} member_ids is not list."); data['member_ids'] = []


                          # Create Party object
                          # Party.from_dict(data: Dict) -> Party
                          party = Party.from_dict(data) # Requires Party.from_dict method

                          # 4. Добавьте объект Party в кеш
                          self._parties[party.id] = party # Добавление в глобальный плоский кеш

                          # 5. Наполните _entities_with_active_action (в менеджерах сущностей) и другие кеши
                          #    Это делается в rebuild_runtime_caches в менеджерах сущностей и здесь.

                          loaded_count += 1

                     except Exception as e:
                         print(f"PartyManager: Error loading party {data.get('id', 'N/A')} for guild {guild_id}: {e}")
                         import traceback
                         print(traceback.format_exc())
                         # Continue loop


                print(f"PartyManager: Successfully loaded {loaded_count} parties into cache for guild {guild_id}.")
                # TODO: Reset _dirty_parties and _deleted_parties for this guild if they exist


            # TODO: Implement rebuild_runtime_caches(guild_id, **kwargs)
            def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
                """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
                print(f"PartyManager: Rebuild runtime caches complete for guild {guild_id}. (Not fully implemented)") # Placeholder
                # Получаем загруженные партии для этой гильдии
                # If _parties flat: parties_for_guild = [p for p in self._parties.values() if getattr(p, 'guild_id', None) == guild_id_str]
                # If _parties per-guild: parties_for_guild = self._parties.get(str(guild_id), {}).values()

                # TODO: Построение кешей, например {member_id: party_id} или {location_id: set(party_id)}
                # Если нужен кеш {member_id: party_id}, его нужно построить, перебрав все party.member_ids
                # Example: self._member_to_party_map: Dict[str, str] = {}
                # for party in parties_for_guild:
                #      for member_id in getattr(party, 'member_ids', []):
                #           self._member_to_party_map[member_id] = party.id

                # TODO: Пометить сущности (Character/NPC) как занятые в их менеджерах, если они находятся в активной партии.
                # Это может сделать менеджер сущностей (CharacterManager/NpcManager) в своем rebuild_runtime_caches, получив CombatManager/PartyManager из kwargs.


            # TODO: Implement mark_party_dirty(party_id: str)
            # Needs _dirty_parties Set or Dict[str, Set[str]]
            # def mark_party_dirty(self, party_id: str) -> None: ...

            # TODO: Implement mark_party_deleted(party_id: str)
            # Needs _deleted_parties Set or Dict[str, Set[str]]
            # def mark_party_deleted(self, party_id: str) -> None: ...


            # TODO: Implement get_party_by_member_id(entity_id, **kwargs) method (used in RuleEngine)
            # def get_party_by_member_id(self, entity_id: str, **kwargs: Any) -> Optional["Party"]: ...

            # TODO: Implement clean_up_for_character(character_id, context) method (used in CharacterManager)
            # async def clean_up_for_character(self, character_id: str, **kwargs: Any) -> None: ... PartyManager должен найти партию по character_id и удалить его из членов партии.

            # TODO: Implement clean_up_for_npc(npc_id, context) method (used in NpcManager)
            # async def clean_up_for_npc(self, npc_id: str, **kwargs: Any) -> None: ... PartyManager должен найти партию по npc_id и удалить его из членов партии.

            # TODO: Implement party_disbanded(party_id, context) method (used in CombatManager)
            # async def party_disbanded(self, party_id: str, **kwargs: Any) -> None: ...

            # Methods for managing Party Group Actions (process_tick, start, add_to_queue)
            # Эти методы вызываются WorldSimulationProcessor
            # TODO: Implement process_tick(party_id, game_time_delta, **kwargs)
            # TODO: Implement start_group_action(party_id, action_data, **kwargs)
            # TODO: Implement add_group_action_to_queue(party_id, action_data, **kwargs)
            # TODO: Implement complete_group_action(party_id, completed_action_data, **kwargs) - Delegates to PartyActionHandlerRegistry
            # TODO: Implement select_next_group_action(party_id, **kwargs) - AI logic for Party


        # --- Конец класса PartyManager ---


print("DEBUG: party_manager.py module loaded.")
