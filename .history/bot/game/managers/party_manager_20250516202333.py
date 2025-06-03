# bot/game/managers/party_manager.py

from __future__ import annotations
import json
import uuid # Импортируем uuid, т.к. используется для Party ID
import traceback
import asyncio
# Импорт базовых типов
# ИСПРАВЛЕНИЕ: Импортируем Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable # Добавлены Set, TYPE_CHECKING, Callable


# --- Imports needed ONLY for Type Checking ---
# Эти импорты нужны ТОЛЬКО для статического анализа (Pylance/Mypy).
# Это разрывает циклы импорта при runtime и помогает Pylance правильно резолвить типы.
# Используйте строковые литералы ("ClassName") для type hints в __init__ и методах
# для классов, импортированных здесь.
if TYPE_CHECKING:
    # Добавляем адаптер БД
    from bot.database.sqlite_adapter import SqliteAdapter
    # Добавляем модели, используемые в аннотациях
    from bot.game.models.party import Party  # <-- Добавляем Party сюда тоже!

    # Добавляем менеджеры
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.combat_manager import CombatManager
    # Добавляем другие менеджеры, если они передаются в __init__ или используются в аннотациях методов
    # from bot.game.managers.event_manager import EventManager
    # from bot.game.managers.location_manager import LocationManager
    # from bot.game.managers.rule_engine import RuleEngine
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
        self._parties: Dict[str, "Party"] = {}

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
        # Если кеш по гильдиям, этот метод должен принимать guild_id и работать с self._parties.get(guild_id, {})
        # В текущей плоской реализации, Party ID должны быть уникальны глобально.
        return self._parties.get(party_id)

    # Используем строковый литерал в аннотации возвращаемого типа
    def get_all_parties(self) -> List["Party"]: # Аннотация List["Party"]
        """Получить список всех загруженных партий (из кеша)."""
        # Если кеш по гильдиям, этот метод должен возвращать values для всех гильдий или принимать guild_id
        return list(self._parties.values())

    # TODO: Implement get_party_by_member_id(entity_id, context) method (used in RuleEngine)
    # RuleEngine.get_party_by_member_id(entity_id, context) -> Optional["Party"]
    # Нужна реализация, которая ищет party_id по entity_id (Party.member_ids) в кеше партий.
    # Если кеш плоский, нужно перебрать все партии. Если кеш по членам {member_id: party_id}, это быстро.
    # async def get_party_by_member_id(self, entity_id: str, **kwargs: Any) -> Optional["Party"]: # Аннотация Optional["Party"]
    #      # Пример реализации с перебором плоского кеша
    #      for party in self._parties.values():
    #           if entity_id in getattr(party, 'member_ids', []): # getattr для безопасности
    #                return party # Return party object
    #      return None # Not found

    # --- Методы CRUD ---

    async def create_party(self, leader_id: str, member_ids: List[str], **kwargs: Any) -> Optional[str]:
        """
        Создает новую партию с лидером и списком участников.
        Принимает guild_id в kwargs.
        """
        if self._db_adapter is None:
            print("PartyManager: No DB adapter.")
            # TODO: В режиме без DB, возможно, создать партию только в памяти и не сохранять.
            # Решите, что делать в режиме без DB. Пока возвращаем None.
            return None

        # TODO: Валидация (участники существуют, не в других партиях, leader_id в списке member_ids)
        # Используйте self._character_manager (get_character), self._npc_manager (get_npc), self.get_party_by_member_id
        # Это асинхронная валидация, т.к. get_character может быть async.
        guild_id = kwargs.get('guild_id') # Получаем guild_id из kwargs
        if guild_id is None: raise ValueError("Missing 'guild_id' in kwargs for create_party.")

        # Пример валидации: лидер и участники существуют
        # all_members_exist = True
        # if self._character_manager: # Нужен CharacterManager для валидации
        #     leader_char = self._character_manager.get_character(leader_id) # Assuming sync get
        #     if not leader_char or getattr(leader_char, 'guild_id', None) != guild_id:
        #          print(f"PartyManager: Validation Error: Leader {leader_id} not found or not in guild {guild_id}.")
        #          all_members_exist = False
        #     if all_members_exist:
        #          for member_id in member_ids:
        #               # Проверить Character ИЛИ NPC менеджеров для каждого члена
        #               member_char = self._character_manager.get_character(member_id)
        #               member_npc = self._npc_manager.get_npc(member_id) if self._npc_manager else None
        #               if not member_char and not member_npc:
        #                    print(f"PartyManager: Validation Error: Member {member_id} not found.")
        #                    all_members_exist = False; break
        #               if (member_char and getattr(member_char, 'guild_id', None) != guild_id) or (member_npc and getattr(member_npc, 'guild_id', None) != guild_id):
        #                     print(f"PartyManager: Validation Error: Member {member_id} not in guild {guild_id}.")
        #                     all_members_exist = False; break
        #
        # if not all_members_exist: return None # Не удалось создать из-за невалидных участников

        # TODO: Валидация: участники НЕ в других партиях (используйте self.get_party_by_member_id)

        try:
            new_id = str(uuid.uuid4())

            party_data: Dict[str, Any] = { # Аннотация Dict
                'id': new_id,
                'guild_id': str(guild_id), # Сохраняем как строку для консистентности
                'leader_id': leader_id,
                'member_ids': member_ids.copy(), # Копируем список
                # TODO: Добавить другие поля Party модели
                'state_variables': {},
                'current_action': None, # Групповое действие партии
                # TODO: location_id для партии, если применимо?
            }
            # ВАЖНО: Вызываем СТАТИЧЕСКИЙ метод from_dict на классе Party
            party = Party.from_dict(party_data) # Требует прямого импорта Party


            # Добавляем в кеш (per-guild cache?)
            # Если _parties Dict[str, Dict[str, Party]] = {guild_id: {party_id: Party}}, то:
            self._parties.setdefault(str(guild_id), {})[new_id] = party # Если Party ID уникальны per-guild
            # Если кеш плоский {party_id: Party}:
            # self._parties[new_id] = party # НЕПРАВИЛЬНО для многогильдийности, если load_state загружает per-guild. При загрузке следующей гильдии, кеш предыдущей сотрется.


            # Помечаем dirty (per-party или per-guild?)
            # Если _dirty_parties Set[str]:
            # self._dirty_parties.add(new_id) # Неправильно для per-guild dirty state
            # Если _dirty_parties Dict[str, Set[str]] = {guild_id: set()}:
            self._dirty_parties.setdefault(str(guild_id), set()).add(new_id) # Помечаем dirty per-guild


            print(f"PartyManager: Party {new_id} created for guild {guild_id}. Leader: {leader_id}. Members: {member_ids}")
            # TODO: Уведомить участников?

            return new_id # Возвращаем ID созданной партии

        except Exception as e:
            print(f"PartyManager: Error creating party for leader {leader_id} in guild {guild_id}: {e}") # Логируем guild_id
            import traceback
            print(traceback.format_exc())
            return None # Возвращаем None при ошибке


    async def remove_party(self, party_id: str, **kwargs: Any) -> Optional[str]:
        """
        Удаляет партию и помечает для удаления в БД.
        Принимает guild_id в kwargs (для per-guild clean_up/persistence).
        """
        party = self.get_party(party_id) # Type: Optional["Party"]
        if not party:
            print(f"PartyManager: Party {party_id} not found for removal.")
            return None

        # Получаем guild_id из объекта партии (если есть) или из kwargs.
        guild_id = getattr(party, 'guild_id', None) # Safely get guild_id from party object
        if guild_id is None:
             guild_id = kwargs.get('guild_id') # Try to get from kwargs
             if guild_id is None:
                  print(f"PartyManager: Warning: Cannot determine guild_id for party {party_id} removal.")
                  # Если партии per-guild, guild_id ОБЯЗАТЕЛЕН для удаления из кешей и БД.
                  raise ValueError(f"Missing 'guild_id' for remove_party {party_id}.")
             else: guild_id = str(guild_id) # Убедимся, что guild_id строка

        else: guild_id = str(guild_id) # Убедимся, что guild_id из объекта партии - строка


        print(f"PartyManager: Removing party {party_id} for guild {guild_id}. Leader: {getattr(party, 'leader_id', 'N/A')}")

        # Очистка участников (например, сбросить party_id)
        member_ids = getattr(party, 'member_ids', []) # Убедимся, что member_ids существует и получаем его безопасно

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
                     # Нужно запросить их у менеджеров сущностей.
                     # Предполагаем, что CharacterManager и NpcManager имеют методы get_character(id)/get_npc(id).
                     entity_type = None # Determine entity type (Character or NPC)
                     manager = None # type: Optional[Any]
                     clean_up_method_name = 'clean_up_from_party' # Имя метода очистки в менеджере сущностей


                     if self._character_manager and hasattr(self._character_manager, 'get_character'):
                          char = self._character_manager.get_character(entity_id) # Type: Optional["Character"]
                          # Если это персонаж И он в этой партии, используем CharacterManager
                          if char and getattr(char, 'party_id', None) == party_id and hasattr(self._character_manager, clean_up_method_name):
                               entity_type = "Character"
                               manager = self._character_manager

                     if entity_type is None and self._npc_manager and hasattr(self._npc_manager, 'get_npc'):
                          npc = self._npc_manager.get_npc(entity_id) # Type: Optional["NPC"]
                          # Если это NPC И он в этой партии, используем NpcManager
                          if npc and getattr(npc, 'party_id', None) == party_id and hasattr(self._npc_manager, clean_up_method_name):
                               entity_type = "NPC"
                               manager = self._npc_manager

                     # TODO: Другие типы сущностей/менеджеров


                     if manager and clean_up_method_name:
                          await getattr(manager, clean_up_method_name)(entity_id, party_id, context=cleanup_context) # Вызываем метод clean_up, передаем context
                          print(f"PartyManager: Cleaned up member {entity_type} {entity_id} from party {party_id}.") # Логируем тип сущности
                     else:
                          print(f"PartyManager: Warning: Could not find suitable manager or 'clean_up_from_party' method for member {entity_id} (determined type: {entity_type}) in party {party_id}. Skipping cleanup for this member.")

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
        #      except Exception as e: import traceback; print(traceback.format_exc());


        # TODO: Очистка групповых действий партии (например, если партия была в бою как одна сущность?)
        # Если CombatManager поддерживает Party как участника боя, его нужно уведомить, что партия распалась.
        # CombatManager может иметь метод party_disbanded(party_id, context)
        # if self._combat_manager and hasattr(self._combat_manager, 'party_disbanded'):
        #      try: await self._combat_manager.party_disbanded(party_id, context=cleanup_context)
        #      except Exception as e: import traceback; print(traceback.format_exc());


        # TODO: Удаление группового действия партии из очереди или текущего действия
        # Если у Party модели есть action_queue и current_action атрибуты, их нужно сбросить/очистить.
        # Это можно сделать непосредственно в Party объекте, а затем пометить его dirty.
        #party.current_action = None # Если Party модель имеет атрибут
        #party.action_queue = [] # Если Party модель имеет атрибут List


        # Помечаем party dirty для сохранения изменений current_action/action_queue
        self.mark_party_dirty(party_id) # Нужен метод mark_party_dirty


        # Помечаем партию для удаления из БД (PartyManager сам удаляет из БД при save_state)
        # Если PartyManager имеет _deleted_parties Set[str], добавляем ID туда.
        self._deleted_parties.add(party_id) # Добавляем ID в сет для удаления из БД


        # Удаляем из кеша активных партий
        # Если кеш _parties плоский:
        self._parties.pop(party_id, None) # Удаляем из глобального кеша активных партий (если кеш плоский)
        # Если кеш по гильдиям:
        # if guild_id in self._parties: self._parties[guild_id].pop(party_id, None)


        print(f"PartyManager: Party {party_id} fully removed from cache and marked for deletion.")
        return party_id # Возвращаем ID удаленной партии


    # Методы персистенции (вызываются PersistenceManager):
    # Эти методы должны работать per-guild
    # required_args_for_load, required_args_for_save, required_args_for_rebuild уже определены как атрибуты класса

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет активные/измененные партии для определенной гильдии."""
        if self._db_adapter is None:
            print(f"PartyManager: Warning: Cannot save parties for guild {guild_id}, DB adapter missing.")
            return

        print(f"PartyManager: Saving parties for guild {guild_id}...")

        # TODO: Implement saving logic for PartyManager.
        # 1. Соберите партии для этой гильдии, которые нужно сохранить (активные + измененные).
        #    Из кеша _parties фильтруйте по party.guild_id == guild_id.
        #    Добавьте партии из _dirty_parties (Set[str]), которые принадлежат этой гильдии и еще в кеше.
        parties_to_save: List["Party"] = []
        party_ids_to_save_from_dirty: Set[str] = set()
        # Проверяем наличие атрибута _dirty_parties перед использованием.
        if hasattr(self, '_dirty_parties') and isinstance(self._dirty_parties, Set):
             # Filter dirty IDs by guild_id and check if they are in кеше
             party_ids_to_save_from_dirty = {pid for pid in self._dirty_parties if self._parties.get(pid) is not None and getattr(self._parties[pid], 'guild_id', None) == guild_id}
             # Собираем объекты Party для сохранения
             parties_to_save.extend([self._parties[pid] for pid in party_ids_to_save_from_dirty])

        # 2. Соберите IDs партий, помеченных для удаления из DB (из _deleted_parties).
        #    Если _deleted_parties Set[str] глобальный, используем его и фильтруем в SQL.
        #    Если _deleted_parties Dict[str, Set[str]] = {guild_id: set()}, используем этот Set.
        party_ids_to_delete: Set[str] = set()
        if hasattr(self, '_deleted_parties') and isinstance(self._deleted_parties, Set): # Assuming _deleted_parties is global Set
             party_ids_to_delete = set(self._deleted_parties) # Work with a copy


        # Если нет партий для сохранения или удаления, выходим
        if not parties_to_save and not party_ids_to_delete:
             # print(f"PartyManager: No dirty or deleted parties to save for guild {guild_id}.")
             return


        try:
            # 4. Удаление партий, помеченных для удаления
            if party_ids_to_delete:
                 ids_to_delete = list(party_ids_to_delete)
                 placeholders_del = ','.join(['?'] * len(ids_to_delete))
                 # Убеждаемся, что удаляем ТОЛЬКО для данного guild_id и по ID
                 delete_sql = f"DELETE FROM parties WHERE guild_id = ? AND id IN ({placeholders_del})"
                 await self._db_adapter.execute(delete_sql, (str(guild_id), *tuple(ids_to_delete))) # Убедимся, что guild_id строка
                 print(f"PartyManager: Deleted {len(ids_to_delete)} parties from DB for guild {guild_id}.")
                 # Очищаем список после успешного удаления
                 # Если _deleted_parties глобальный Set, удаляем из него те, что успешно удалены
                 if hasattr(self, '_deleted_parties') and isinstance(self._deleted_parties, Set):
                      self._deleted_parties.difference_update(party_ids_to_delete)


            # 5. Сохранение/обновление партий
            if parties_to_save:
                 print(f"PartyManager: Upserting {len(parties_to_save)} parties for guild {guild_id}...")
                 # SQL (INSERT OR REPLACE)
                 # Убеждаемся, что SQL соответствует текущей схеме и полям Party модели, включая guild_id
                 upsert_sql = '''
                 INSERT OR REPLACE INTO parties
                 (id, guild_id, leader_id, member_ids, state_variables, current_action)
                 VALUES (?, ?, ?, ?, ?, ?)
                 '''
                 data_to_upsert = []
                 for party in parties_to_save:
                      try:
                           # Убеждаемся, что у объекта Party есть все нужные атрибуты
                           party_id = getattr(party, 'id', None)
                           party_guild_id = getattr(party, 'guild_id', None)
                           leader_id = getattr(party, 'leader_id', None)
                           member_ids = getattr(party, 'member_ids', [])
                           state_variables = getattr(party, 'state_variables', {})
                           current_action = getattr(party, 'current_action', None)

                           # Дополнительная проверка на критически важные атрибуты
                           if party_id is None or party_guild_id is None or leader_id is None:
                                print(f"PartyManager: Warning: Skipping upsert for party with missing mandatory attributes (ID, Guild ID, Leader ID). Party object: {party}")
                                continue # Пропускаем эту партию

                           # Убедимся, что данные для JSON корректны
                           member_ids_json = json.dumps(member_ids)
                           state_variables_json = json.dumps(state_variables)
                           current_action_json = json.dumps(current_action) if current_action is not None else None

                           data_to_upsert.append((
                               str(party_id),
                               str(party_guild_id), # Убедимся, что guild_id строка
                               str(leader_id),
                               member_ids_json,
                               state_variables_json,
                               current_action_json,
                           ))

                      except Exception as e:
                          print(f"PartyManager: Error preparing data for party {getattr(party, 'id', 'N/A')} for upsert: {e}")
                          import traceback
                          print(traceback.format_exc())
                          # Эта партия не будет сохранена в этой итерации - она останется в _dirty_parties
                          # чтобы попробовать сохранить ее снова


                 if data_to_upsert:
                      if self._db_adapter is None:
                           print(f"PartyManager: Warning: DB adapter is None during upsert batch for guild {guild_id}.")
                      else:
                           await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                           print(f"PartyManager: Successfully upserted {len(data_to_upsert)} parties for guild {guild_id}.")
                           # Только если execute_many успешен, очищаем список "грязных"
                           if hasattr(self, '_dirty_parties') and isinstance(self._dirty_parties, Set):
                                # Очищаем только те ID, которые были в parties_to_save (по которым успешно прошел upsert)
                                upserted_ids = {item[0] for item in data_to_upsert}
                                self._dirty_parties.difference_update(upserted_ids)


            print(f"PartyManager: Save state complete for guild {guild_id}.")

        except Exception as e:
            print(f"PartyManager: ❌ Error during save state for guild {guild_id}: {e}")
            import traceback
            print(traceback.format_exc())
            # TODO: Handle error - do not clear dirty/deleted sets if saving failed


    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает партии для определенной гильдии из базы данных в кеш."""
        if self._db_adapter is None:
            print(f"PartyManager: Warning: Cannot load parties for guild {guild_id}, DB adapter missing.")
            # TODO: Load placeholder data
            return

        print(f"PartyManager: Loading parties for guild {guild_id} from DB...")

        # TODO: Implement loading logic for PartyManager.
        # 1. Очистите кеш партий для этой гильдии (если кеш per-guild).
        #    Если _parties плоский {party_id: Party}, это БАГ при многогильдийности.
        #    self._parties.clear() # <-- ВРЕМЕННО ОЧИЩАЕТ ВСЕХ
        #    Идеально: self._parties.setdefault(str(guild_id), {}).clear()
        #    _dirty_parties и _deleted_parties для этой гильдии тоже очистить.

        # В текущей реализации, load_state для одной гильдии ОЧИЩАЕТ кеши ВСЕХ гильдий.
        self._parties.clear() # <-- ОЧИЩАЕТ ВСЕХ
        if hasattr(self, '_dirty_parties') and isinstance(self._dirty_parties, Set): self._dirty_parties.clear()
        if hasattr(self, '_deleted_parties') and isinstance(self._deleted_parties, Set): self._deleted_parties.clear()


        rows = []
        try:
            # 2. Выполните SQL SELECT FROM parties WHERE guild_id = ?
            # Выберите ВСЕ партии, а не только активные. PersistenceManager загружает ВСЕ, а WorldSimulationProcessor управляет active state.
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
                  # Basic validation
                  if data.get('leader_id') is None: print(f"PartyManager: Warning: Party {party_id} has no leader_id.")
                  if not isinstance(data.get('member_ids'), list): print(f"PartyManager: Warning: Party {party_id} member_ids is not list."); data['member_ids'] = []


                  # Create Party object
                  # Party.from_dict(data: Dict) -> Party
                  party = Party.from_dict(data) # Requires Party.from_dict method

                  # 4. Добавьте объект Party в кеш
                  self._parties[party.id] = party # Добавление в глобальный плоский кеш (_parties: Dict[str, Party])

                  # 5. TODO: Наполнить _entities_with_active_action (в менеджерах сущностей) и другие кеши
                  #    PartyManager сам не наполняет эти кеши для участников. Это делается в CharacterManager/NpcManager
                  #    или в rebuild_runtime_caches менеджеров сущностей, которые получат загруженные Party объекты из PartyManager через kwargs.

                  # TODO: Если партия имеет current_action или action_queue, она активна. PartyManager должен иметь сет _active_parties?
                  #   Или WorldSimulationProcessor сам определяет активные партии на основе Party.current_action?
                  #   WorldSimulationProcessor вызывает PartyActionProcessor.process_tick для *каждой* активной Party.
                  #   WSP должен знать, какие Party активны. Он получает их список от PartyManager?
                  #   PartyManager должен иметь метод get_parties_with_active_action(), который использует атрибуты party.current_action.
                  #   В текущей структуре (см PartyManager.get_parties_with_active_action, который я добавлял ранее) WSP запрашивает список Party у PartyManager.
                  #   Это OK.

                  loaded_count += 1

             except Exception as e:
                 print(f"PartyManager: Error loading party {data.get('id', 'N/A')} for guild {guild_id}: {e}")
                 import traceback
                 print(traceback.format_exc())
                 # Continue loop


                 print(f"PartyManager: Successfully loaded {loaded_count} parties into cache for guild {guild_id}.") # Log guild_id
                # TODO: Reset _dirty_parties and _deleted_parties for this guild if they exist (If these are per-guild)


            # TODO: Implement rebuild_runtime_caches(guild_id, **kwargs)
             def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
                """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
                guild_id_str = str(guild_id)
                print(f"PartyManager: Rebuild runtime caches complete for guild {guild_id_str}. (Not fully implemented)") # Log guild_id

                # Получаем все загруженные партии для этой гильдии (из текущего кеша PartyManager)
                # If _parties flat: parties_for_guild = [p for p in self._parties.values() if getattr(p, 'guild_id', None) == guild_id_str]
                # If _parties per-guild: parties_for_guild = self._parties.get(str(guild_id_str), {}).values()
                # Предполагаем, кеш плоский, фильтруем:
                parties_for_guild = [party for party in self._parties.values() if getattr(party, 'guild_id', None) == guild_id_str]


                # TODO: Построение кешей, например {member_id: party_id} или {location_id: set(party_id)}
                # Пример: построение кеша {member_id: party_id} (требуется новый атрибут self._member_to_party_map)
                if not hasattr(self, '_member_to_party_map'): self._member_to_party_map: Dict[str, str] = {} # Инициализируем если нет
                # Clear entries for this guild if map is global, otherwise clear per-guild map
                # If _member_to_party_map global: Need to clear OLD entries for this guild. Hard if no index {guild_id: member_id}
                # If _member_to_party_map per-guild: Dict[str, Dict[str, str]] = {guild_id: {member_id: party_id}}. clear this guild's dict.

                # Предположим _member_to_party_map глобальный плоский кеш. Перестроить его для одной гильдии сложно.
                # Лучше: build for ALL loaded parties.
                # Перебираем ВСЕ партии в кеше _parties (которые, при load_state, будут только из последней загруженной гильдии).
                # Если load_state корректно загружает ВСЕХ, то здесь перестраиваем ВСЕХ.
                self._member_to_party_map = {} # Очищаем глобальный кеш перед перестройкой всех
                for party in self._parties.values(): # Перебираем ВСЕ загруженные Party объекты
                     # Убеждаемся, что member_ids доступен и это список
                     for member_id in getattr(party, 'member_ids', []):
                          # Добавляем запись в мапу member_id -> party_id
                          if isinstance(member_id, str): # Убедимся, что member_id строка
                               # TODO: Проверка конфликтов - один участник в нескольких партиях?
                               if member_id in self._member_to_party_map:
                                    print(f"PartyManager: Warning: Member {member_id} found in multiple parties during rebuild: {self._member_to_party_map[member_id]} and {party.id}. Keeping {party.id}.")
                               self._member_to_party_map[member_id] = party.id
                          else: print(f"PartyManager: Warning: Invalid member_id format during rebuild: {member_id} in party {party.id}. Skipping.")


                # TODO: Пометить сущности (Character/NPC) как занятые в их менеджерах, если они находятся в активной партии.
                # Это может сделать менеджер сущностей (CharacterManager/NpcManager) в своем rebuild_runtime_caches, получив CombatManager/PartyManager из kwargs.
                # CharacterManager/NpcManager.rebuild_runtime_caches(guild_id, **kwargs):
                #      party_mgr = kwargs.get('party_manager')
                #      if party_mgr:
                #           active_parties = party_mgr.get_active_parties(guild_id) # PartyManager должен иметь get_active_parties per-guild
                #           for party in active_parties:
                #                for member_id in party.member_ids:
                #                     # Найти Character/NPC объект и пометить как busy
                #                     entity = self.get_character(member_id) or self.get_npc(member_id) # CharacterManager/NpcManager methods
                #                     if entity:
                #                          entity.is_busy = True # Или использовать set_busy_status

            # TODO: Implement mark_party_dirty(party_id: str)
            # Нужен Set _dirty_parties (или Dict[str, Set[str]] для per-guild)
             def mark_party_dirty(self, party_id: str) -> None:
                 """Помечает партию как измененной для последующего сохранения."""
                 # Если кеш плоский:
                 if party_id in self._parties:
                      if hasattr(self, '_dirty_parties') and isinstance(self._dirty_parties, Set): # Проверяем наличие атрибута и тип
                           self._dirty_parties.add(party_id)
                      else: print(f"PartyManager: Warning: Cannot mark party {party_id} dirty. _dirty_parties is not a Set or does not exist.")
                 else:
                      print(f"PartyManager: Warning: Attempted to mark non-existent party {party_id} as dirty.")

            # TODO: Implement mark_party_deleted(party_id: str)
            # Needs _deleted_parties Set or Dict[str, Set[str]]
            # def mark_party_deleted(self, party_id: str) -> None: ...


            # TODO: Implement get_party_by_member_id(entity_id, **kwargs) method (used in RuleEngine)
            # Def get_party_by_member_id(self, entity_id: str, **kwargs: Any) -> Optional["Party"]:
            #      """Найти партию по ID участника."""
            #      # Используем мапу {member_id: party_id}
            #      if hasattr(self, '_member_to_party_map') and isinstance(self._member_to_party_map, Dict):
            #           party_id = self._member_to_party_map.get(entity_id)
            #           if party_id: return self.get_party(party_id) # Get Party object
            #      # Fallback: перебрать все партии, если мапы нет или участник не найден в мапе (медленно)
            #      # for party in self._parties.values(): ...
            #      return None


            # TODO: Implement clean_up_for_character(character_id, context) method (used in CharacterManager)
            # async def clean_up_for_character(self, character_id: str, **kwargs: Any) -> None: ...
            # PartyManager должен найти партию по character_id (через get_party_by_member_id), удалить character_id из списка member_ids партии,
            # если партия пустеет - удалить партию.

            # TODO: Implement clean_up_for_npc(npc_id, context) method (used in NpcManager)
            # async def clean_up_for_npc(self, npc_id: str, **kwargs: Any) -> None: ...
            # PartyManager должен найти партию по npc_id (через get_party_by_member_id), удалить npc_id из списка member_ids партии,
            # если партия пустеет - удалить партию.

            # TODO: Implement party_disbanded(party_id, context) method (used in CombatManager)
            # async def party_disbanded(self, party_id: str, **kwargs: Any) -> None: ...

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
            # WorldSimulationProcessor.process_tick запрашивает у PartyManager список активных Party ( PartyManager.get_parties_with_active_action() )

            # TODO: Implement get_parties_with_active_action() method (used by WorldSimulationProcessor)
            # Def get_parties_with_active_action(self) -> List["Party"]:
            #      # Перебирает партии в кеше, проверяет party.current_action, возвращает список Party объектов, у которых current_action is not None.
            #      return [party for party in self._parties.values() if getattr(party, 'current_action', None) is not None]

            # TODO: Implement methods to manage party members (add/remove member)
            # async def add_member(self, party_id: str, entity_id: str, entity_type: str, **kwargs): ... (Check if exists, add to member_ids, update entity's party_id, mark party dirty)
            # async def remove_member(self, party_id: str, entity_id: str, entity_type: str, **kwargs): ... (Remove from member_ids, reset entity's party_id, mark party dirty)


        # --- Конец класса PartyManager ---


print("DEBUG: party_manager.py module loaded.")
