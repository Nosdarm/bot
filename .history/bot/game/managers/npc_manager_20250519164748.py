# bot/game/managers/npc_manager.py

from __future__ import annotations # Enables using type hints as strings implicitly, simplifying things
import json
import uuid
import traceback
import asyncio
# Импорт базовых типов
from typing import Optional, Dict, Any, List, Set, TYPE_CHECKING, Callable, Awaitable, Union # Added Union for type hints

# Импорт модели NPC (прямой импорт нужен для NPC.from_dict)
from bot.game.models.npc import NPC

# Import built-in types for isinstance checks
# Use lowercase 'dict', 'set', 'list', 'int' for isinstance
from builtins import dict, set, list, int, float, str, bool # Added relevant builtins


# --- Imports needed ONLY for Type Checking ---
# Эти импорты нужны ТОЛЬКО для статического анализа (Pylance/Mypy).
# Это разрывает циклы импорта при runtime и помогает Pylance правильно резолвить типы.
# Используйте строковые литералы ("ClassName") для type hints в init и методах
# для классов, импортированных здесь, ЕСЛИ они импортированы только здесь.
if TYPE_CHECKING:
    # Добавляем адаптер БД
    from bot.database.sqlite_adapter import SqliteAdapter
    # Добавляем модели, используемые в аннотациях или context
    from bot.game.models.npc import NPC # Аннотируем как "NPC"
    # from bot.game.models.character import Character # Если Character объекты передаются в методы NPCManager
    # from bot.game.models.party import Party # Если Party объекты передаются в методы NPCManager
    # Добавляем менеджеры
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.character_manager import CharacterManager # Нужен для clean_up_from_party в PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager

    # Добавляем другие менеджеры, если они передаются в __init__ или используются в аннотациях методов
    # from bot.game.managers.event_manager import EventManager
    from bot.game.managers.location_manager import LocationManager # Нужен для create_npc default location?
    from bot.game.rules.rule_engine import RuleEngine

    # Добавляем процессоры, если они используются в аннотациях методов
    # from bot.game.character_processors.character_action_processor import CharacterActionProcessor

    # Discord types if needed in context hints
    # from discord import Guild # Example


# Type Aliases for callbacks (defined outside TYPE_CHECKING if used in __init__ signature)
# Not needed if only used within methods and hinted via **kwargs context
# SendToChannelCallback = Callable[[str], Awaitable[Any]] # Use Callable[..., Awaitable[Any]] or specific signature if known
# SendCallbackFactory = Callable[[int], SendToChannelCallback] # Use Callable[[int], Callable[..., Awaitable[Any]]]

print("DEBUG: npc_manager.py module loaded.")

class NpcManager:
    """
    Менеджер для управления NPC: создание, хранение, обновление и персистенция.
    Работает на основе guild_id для многогильдийной поддержки.
    Логика действий вынесена в NpcActionProcessor.
    """
    # Required args для PersistenceManager
    required_args_for_load: List[str] = ["guild_id"] # Загрузка per-guild
    required_args_for_save: List[str] = ["guild_id"] # Сохранение per-guild
    # ИСПРАВЛЕНИЕ: Добавляем guild_id для rebuild_runtime_caches
    required_args_for_rebuild: List[str] = ["guild_id"] # Rebuild per-guild

    # --- Class-Level Attribute Annotations ---
    # ИСПРАВЛЕНИЕ: Кеши должны быть per-guild
    # Кеш всех загруженных объектов NPC {guild_id: {npc_id: NPC_object}}
    _npcs: Dict[str, Dict[str, "NPC"]] # Аннотация кеша использует строковый литерал "NPC"
    # Сет NPC с активным действием {guild_id: set(npc_ids)}
    _entities_with_active_action: Dict[str, Set[str]]
    # Изменённые NPC для персистенции {guild_id: set(npc_ids)}
    _dirty_npcs: Dict[str, Set[str]]
    # Удалённые NPC для персистенции {guild_id: set(npc_ids)}
    _deleted_npc_ids: Dict[str, Set[str]]


    def __init__(
        self,
        # Используем строковые литералы для всех инжектированных зависимостей
        db_adapter: Optional["SqliteAdapter"] = None,
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        character_manager: Optional["CharacterManager"] = None, # Potential need for cleanup?
        rule_engine: Optional["RuleEngine"] = None,
        combat_manager: Optional["CombatManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
        # event_manager: Optional["EventManager"] = None, # if needed
        # location_manager: Optional["LocationManager"] = None, # if needed for default loc logic
    ):
        print("Initializing NpcManager...")
        self._db_adapter = db_adapter
        self._settings = settings

        # Инжектированные зависимости
        self._item_manager = item_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._character_manager = character_manager # Store CharacterManager if needed
        self._rule_engine = rule_engine
        self._combat_manager = combat_manager
        self._dialogue_manager = dialogue_manager
        # self._event_manager = event_manager
        # self._location_manager = location_manager # Store LocationManager if needed


        # ИСПРАВЛЕНИЕ: Инициализируем кеши как пустые outer словари
        self._npcs = {} # {guild_id: {npc_id: NPC}}
        self._entities_with_active_action = {} # {guild_id: set(npc_ids)}
        self._dirty_npcs = {} # {guild_id: set(npc_ids)}
        self._deleted_npc_ids = {} # {guild_id: set(npc_ids)}

        print("NpcManager initialized.")

    # --- Методы получения ---
    # ИСПРАВЛЕНИЕ: Метод get_npc должен принимать guild_id
    def get_npc(self, guild_id: str, npc_id: str) -> Optional["NPC"]:
        """Получить объект NPC по ID для определенной гильдии (из кеша)."""
        guild_id_str = str(guild_id)
        guild_npcs = self._npcs.get(guild_id_str) # Get per-guild cache
        if guild_npcs:
             return guild_npcs.get(npc_id)
        return None # Guild or NPC not found

    # ИСПРАВЛЕНИЕ: Метод get_all_npcs должен принимать guild_id
    def get_all_npcs(self, guild_id: str) -> List["NPC"]:
        """Получить список всех загруженных NPC для определенной гильдии (из кеша)."""
        guild_id_str = str(guild_id)
        guild_npcs = self._npcs.get(guild_id_str) # Get per-guild cache
        if guild_npcs:
             return list(guild_npcs.values())
        return [] # Return empty list if no NPCs for guild

    # ИСПРАВЛЕНИЕ: Метод get_npcs_in_location должен принимать guild_id
    def get_npcs_in_location(self, guild_id: str, location_id: str, **kwargs: Any) -> List["NPC"]:
        """Получить список NPC, находящихся в указанной локации (инстансе) для данной гильдии."""
        guild_id_str = str(guild_id)
        location_id_str = str(location_id)
        npcs_in_location = []
        # ИСПРАВЛЕНИЕ: Итерируем только по NPC этой гильдии
        guild_npcs = self._npcs.get(guild_id_str)
        if guild_npcs:
             for npc in guild_npcs.values():
                 # Убеждаемся, что npc имеет атрибут location_id и сравниваем
                 if isinstance(npc, NPC) and hasattr(npc, 'location_id') and str(getattr(npc, 'location_id', None)) == location_id_str:
                      npcs_in_location.append(npc)
        return npcs_in_location


    # ИСПРАВЛЕНИЕ: Метод get_entities_with_active_action должен принимать guild_id
    def get_entities_with_active_action(self, guild_id: str) -> Set[str]:
        """Получить ID сущностей (включая NPC) с активным действием для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем из per-guild Set
        return self._entities_with_active_action.get(guild_id_str, set()).copy() # Return a copy for safety

    # ИСПРАВЛЕНИЕ: Метод is_busy должен принимать guild_id
    def is_busy(self, guild_id: str, npc_id: str) -> bool:
        """Проверяет, занят ли NPC (выполняет действие или состоит в занятой группе) для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем NPC с учетом guild_id
        npc = self.get_npc(guild_id_str, npc_id)
        if not npc:
            return False
        # Проверка на текущее действие NPC
        if getattr(npc, 'current_action', None) is not None or getattr(npc, 'action_queue', []):
            return True
        # Проверка, занята ли его группа (используем инжектированный party_manager, если он есть)
        if getattr(npc, 'party_id', None) is not None and self._party_manager and hasattr(self._party_manager, 'is_party_busy'):
            # ИСПРАВЛЕНИЕ: Передаем guild_id в PartyManager.is_party_busy
            party_id = getattr(npc, 'party_id', None)
            if party_id:
                # Предполагаем, что PartyManager.is_party_busy(guild_id: str, party_id: str) -> bool (синхронный)
                return self._party_manager.is_party_busy(guild_id_str, party_id)
        # Если party_manager нет или нет метода, считаем, что группа не может быть занята через него
        return False

    # --- Методы CRUD ---

    # ИСПРАВЛЕНИЕ: Метод create_npc должен принимать guild_id
    async def create_npc(
        self,
        guild_id: str, # Обязательный аргумент guild_id
        npc_template_id: str,
        location_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        """Создает нового NPC для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"NpcManager: Creating NPC from template '{npc_template_id}' at location {location_id} for guild {guild_id_str}...")

        if self._db_adapter is None:
            print(f"NpcManager: No DB adapter available for guild {guild_id_str}.")
            # In multi-guild, this might require different handling if DB is crucial
            return None

        # Генерация статов через RuleEngine (используем инжектированный, если есть, иначе из kwargs)
        rule_engine = self._rule_engine or kwargs.get('rule_engine') # type: Optional["RuleEngine"]
        stats: Dict[str, Any] = {"strength":5,"dexterity":5,"intelligence":5} # Default stats
        if rule_engine and hasattr(rule_engine, 'generate_initial_npc_stats'):
            try:
                # Assume generate_initial_npc_stats accepts template_id, guild_id, and context
                # RuleEngine.generate_initial_npc_stats(npc_template_id: str, guild_id: str, **kwargs: Any) -> Dict[str, Any]
                generated_stats = await rule_engine.generate_initial_npc_stats(
                    npc_template_id=npc_template_id,
                    guild_id=guild_id_str, # Pass guild_id
                    **kwargs # Pass remaining context
                )
                if isinstance(generated_stats, dict):
                    stats = generated_stats
            except Exception as e:
                print(f"NpcManager: Error generating NPC stats for guild {guild_id_str}: {e}")
                traceback.print_exc() # Log the error but proceed with default stats

        try:
            npc_id = str(uuid.uuid4())
            data: Dict[str, Any] = {
                'id': npc_id,
                'template_id': npc_template_id,
                'name': kwargs.get('name', f"NPC_{npc_id[:8]}"), # Optional name override from kwargs
                'guild_id': guild_id_str, # <--- Add guild_id
                'location_id': location_id, # Can be None
                'stats': stats,
                'inventory': [], # List of item IDs or objects? Needs consistency. Assuming List[str] (item IDs) based on remove_item_from_inventory.
                'current_action': None,
                'action_queue': [],
                'party_id': None, # Can be None
                'state_variables': kwargs.get('state_variables', {}), # Allow initial state from kwargs
                'health': kwargs.get('health', 50.0), # Allow initial health from kwargs
                'max_health': kwargs.get('max_health', 50.0), # Allow initial max_health from kwargs
                'is_alive': kwargs.get('is_alive', True), # Allow initial is_alive from kwargs
                'status_effects': [], # List of status effect IDs? Needs consistency. Assuming List[str].
                'is_temporary': bool(kwargs.get('is_temporary', False)),
            }
            npc = NPC.from_dict(data) # Requires NPC.from_dict

            # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш
            self._npcs.setdefault(guild_id_str, {})[npc_id] = npc

            # ИСПРАВЛЕНИЕ: Помечаем NPC dirty (per-guild)
            self.mark_npc_dirty(guild_id_str, npc_id)

            print(f"NpcManager: NPC {npc_id} ('{getattr(npc, 'name', 'N/A')}') created for guild {guild_id_str}.")
            return npc_id

        except Exception as e:
            print(f"NpcManager: Error creating NPC from template '{npc_template_id}' for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            return None

    # ИСПРАВЛЕНИЕ: Метод remove_npc должен принимать guild_id
    async def remove_npc(self, guild_id: str, npc_id: str, **kwargs: Any) -> Optional[str]:
        """Удаляет NPC и помечает для удаления в БД для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"NpcManager: Removing NPC {npc_id} from guild {guild_id_str}...")

        # ИСПРАВЛЕНИЕ: Получаем NPC с учетом guild_id
        npc = self.get_npc(guild_id_str, npc_id) # Type: Optional["NPC"]
        if not npc:
            # Check if it's already marked for deletion for this guild
            if guild_id_str in self._deleted_npc_ids and npc_id in self._deleted_npc_ids[guild_id_str]:
                 print(f"NpcManager: NPC {npc_id} in guild {guild_id_str} was already marked for deletion.")
                 return npc_id # Return ID if already marked
            print(f"NpcManager: NPC {npc_id} not found for removal in guild {guild_id_str}.")
            return None

        # Optional: Additional check if NPC guild_id matches passed guild_id
        # char_guild_id = getattr(char, 'guild_id', None)
        # if str(char_guild_id) != guild_id_str:
        #      print(f"NpcManager: Logic error: NPC {npc_id} belongs to guild {char_guild_id}, but remove_npc called with {guild_id_str}.")
        #      return None # Should not happen if get_npc works correctly

        # Передаем context в cleanup методы
        cleanup_context: Dict[str, Any] = {
            'npc_id': npc_id, # Use npc_id as the entity_id
            'entity': npc, # Pass the NPC object itself
            'entity_type': "NPC", # Specify entity type
            'guild_id': guild_id_str, # Pass guild_id_str
            # Pass injected managers/processors from self._ or kwargs
            'item_manager': self._item_manager or kwargs.get('item_manager'),
            'status_manager': self._status_manager or kwargs.get('status_manager'),
            'party_manager': self._party_manager or kwargs.get('party_manager'),
            'character_manager': self._character_manager or kwargs.get('character_manager'), # CharacterManager might be needed for cleanups
            'combat_manager': self._combat_manager or kwargs.get('combat_manager'),
            'dialogue_manager': self._dialogue_manager or kwargs.get('dialogue_manager'),
            'rule_engine': self._rule_engine or kwargs.get('rule_engine'),
            # Add other relevant context from kwargs (e.g., channel_id, send_callback_factory)
        }
        cleanup_context.update(kwargs) # Add any extra kwargs passed to remove_npc

        try:
            print(f"NpcManager: Cleaning up related data for NPC {npc_id} in guild {guild_id_str}...")
            # Use clean_up_for_entity pattern on other managers if available
            # Many managers will have a generic clean_up_for_entity(entity_id, entity_type, context)
            # or specific clean_up_for_npc(npc_id, context). Prioritize specific if they exist.

            # Item Cleanup (Items owned by this NPC)
            im = cleanup_context.get('item_manager') # type: Optional["ItemManager"]
            if im and hasattr(im, 'remove_items_by_owner'):
                 try: await im.remove_items_by_owner(npc_id, 'NPC', context=cleanup_context)
                 except Exception: traceback.print_exc(); print(f"NpcManager: Error during item cleanup for NPC {npc_id} in guild {guild_id_str}.")

            # Status Cleanup (Statuses on this NPC)
            sm = cleanup_context.get('status_manager') # type: Optional["StatusManager"]
            if sm and hasattr(sm, 'remove_status_effects_by_target'): # Or clean_up_for_entity
                try: await sm.remove_status_effects_by_target(npc_id, 'NPC', context=cleanup_context) # Assumes method handles guild_id via context
                except Exception: traceback.print_exc(); print(f"NpcManager: Error during status cleanup for NPC {npc_id} in guild {guild_id_str}.")

            # Party Cleanup (Remove NPC from their party)
            pm = cleanup_context.get('party_manager') # type: Optional["PartyManager"]
            # Assuming PartyManager has clean_up_for_entity or remove_member
            if pm:
                 party_id = getattr(npc, 'party_id', None)
                 if party_id:
                      if hasattr(pm, 'clean_up_for_entity'): # Preferred generic cleanup
                           try: await pm.clean_up_for_entity(npc_id, 'NPC', context=cleanup_context) # Assumes method handles guild_id via context
                           except Exception: traceback.print_exc(); print(f"PartyManager: Error during generic party cleanup for NPC {npc_id} in guild {guild_id_str}.")
                      elif hasattr(pm, 'remove_member'): # Fallback specific method
                           try: await pm.remove_member(party_id, npc_id, guild_id=guild_id_str, **cleanup_context) # remove_member needs party_id, entity_id, guild_id
                           except Exception: traceback.print_exc(); print(f"PartyManager: Error during specific party cleanup for NPC {npc_id} in guild {guild_id_str}.")
                      else:
                           print(f"PartyManager: Warning: No suitable party cleanup method found for NPC {npc_id} in guild {guild_id_str}.")


            # Combat Cleanup (Remove NPC from combat)
            cm = cleanup_context.get('combat_manager') # type: Optional["CombatManager"]
            # Assuming CombatManager has clean_up_for_entity or remove_participant
            if cm:
                 if hasattr(cm, 'clean_up_for_entity'): # Preferred generic cleanup
                      try: await cm.clean_up_for_entity(npc_id, 'NPC', context=cleanup_context) # Assumes method handles guild_id via context
                      except Exception: traceback.print_exc(); print(f"CombatManager: Error during generic combat cleanup for NPC {npc_id} in guild {guild_id_str}.")
                 elif hasattr(cm, 'remove_participant_from_combat'): # Fallback specific method
                      try: # remove_participant_from_combat needs entity_id, entity_type, context
                          await cm.remove_participant_from_combat(npc_id, 'NPC', context=cleanup_context)
                      except Exception: traceback.print_exc(); print(f"CombatManager: Error during specific combat cleanup for NPC {npc_id} in guild {guild_id_str}.")
                 else:
                      print(f"CombatManager: Warning: No suitable combat cleanup method found for NPC {npc_id} in guild {guild_id_str}.")


            # Dialogue Cleanup (End any active dialogue involving this NPC)
            dm = cleanup_context.get('dialogue_manager') # type: Optional["DialogueManager"]
            # Assuming DialogueManager has clean_up_for_entity or end_dialogue_by_participant
            if dm:
                 if hasattr(dm, 'clean_up_for_entity'): # Preferred generic cleanup
                      try: await dm.clean_up_for_entity(npc_id, 'NPC', context=cleanup_context) # Assumes method handles guild_id via context
                      except Exception: traceback.print_exc(); print(f"DialogueManager: Error during generic dialogue cleanup for NPC {npc_id} in guild {guild_id_str}.")
                 elif hasattr(dm, 'end_dialogue_by_participant'): # Fallback specific method
                      try: # end_dialogue_by_participant needs participant_id, participant_type, context
                          await dm.end_dialogue_by_participant(npc_id, 'NPC', context=cleanup_context)
                      except Exception: traceback.print_exc(); print(f"DialogueManager: Error during specific dialogue cleanup for NPC {npc_id} in guild {guild_id_str}.")
                 else:
                      print(f"DialogueManager: Warning: No suitable dialogue cleanup method found for NPC {npc_id} in guild {guild_id_str}.")


            # TODO: Trigger death logic / rule engine hooks if needed (if not handled by StatusManager/CombatManager)
            rule_engine = cleanup_context.get('rule_engine') # type: Optional["RuleEngine"]
            # if rule_engine and hasattr(rule_engine, 'trigger_npc_removal'):
            #      try: await rule_engine.trigger_npc_removal(npc, context=cleanup_context)
            #      except Exception: traceback.print_exc();

            print(f"NpcManager: Related data cleanup complete for NPC {npc_id} in guild {guild_id_str}.")

        except Exception as e:
             print(f"NpcManager: Error during cleanup process for NPC {npc_id} in guild {guild_id_str}: {e}")
             import traceback
             print(traceback.format_exc())
             # Decide whether to re-raise or just log. Logging allows core removal to proceed.


        # Reset actions on the object (should already be removed from cache, but belt and suspenders)
        # These attributes won't be saved if the object is removed from the cache
        # but good practice if the object is kept temporarily.
        # getattr(npc, 'current_action', None) = None # Does nothing as getattr returns value
        # Setting attributes directly on the object from cache:
        if hasattr(npc, 'current_action'): npc.current_action = None
        if hasattr(npc, 'action_queue'): npc.action_queue = []


        # İSPRAVLENIE: Удаляем из per-guild кеша активных NPC
        guild_npcs = self._npcs.get(guild_id_str)
        if guild_npcs:
            guild_npcs.pop(npc_id, None)
            print(f"NpcManager: Removed NPC {npc_id} from cache for guild {guild_id_str}.")

        # ИСПРАВЛЕНИЕ: Удаляем из per-guild списка занятых
        guild_active_action_cache = self._entities_with_active_action.get(guild_id_str)
        if guild_active_action_cache:
             guild_active_action_cache.discard(npc_id)


        # ИСПРАВЛЕНИЕ: Убираем из dirty set, если там была
        self._dirty_npcs.get(guild_id_str, set()).discard(npc_id)

        # ИСПРАВЛЕНИЕ: Помечаем для удаления из DB (per-guild)
        self._deleted_npc_ids.setdefault(guild_id_str, set()).add(npc_id)
        print(f"NpcManager: NPC {npc_id} marked for deletion for guild {guild_id_str}.")


        return npc_id # Return the ID of the removed NPC


    # ИСПРАВЛЕНИЕ: Методы инвентаря должны принимать guild_id
    async def add_item_to_inventory(self, guild_id: str, npc_id: str, item_id: str, quantity: int = 1, **kwargs: Any) -> bool:
        """Добавляет предмет в инвентарь NPC для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"NpcManager: Adding item '{item_id}' (x{quantity}) to NPC {npc_id} in guild {guild_id_str}")

        # ИСПРАВЛЕНИЕ: Получаем NPC с учетом guild_id
        npc = self.get_npc(guild_id_str, npc_id) # Type: Optional["NPC"]
        im = self._item_manager or kwargs.get('item_manager') # Type: Optional["ItemManager"] # Use injected or from kwargs

        if not npc:
            print(f"NpcManager: NPC {npc_id} not found in guild {guild_id_str} to add item.")
            return False

        # Basic validation
        resolved_item_id = str(item_id)
        resolved_quantity = int(quantity)
        if resolved_quantity <= 0:
            print(f"NpcManager: Warning: Attempted to add non-positive quantity ({resolved_quantity}) of item '{resolved_item_id}' to {npc_id} in guild {guild_id_str}.")
            return False # Cannot add 0 or negative quantity


        # Determine inventory structure (assuming List[str] of item IDs based on remove_item_from_inventory)
        # If inventory stores quantity, this logic needs adjustment similar to CharacterManager
        if not hasattr(npc, 'inventory') or not isinstance(npc.inventory, list):
            print(f"NpcManager: Warning: NPC {npc_id} inventory is not list or missing. Initializing empty list.")
            npc.inventory = [] # Initialize empty list

        # Check if item is already in inventory (assuming unique item IDs per slot, not stackable by default)
        # If inventory should stack, logic needs adjustment. Current implementation seems to treat inventory as list of unique item instances.
        if resolved_item_id in npc.inventory:
             print(f"NpcManager: Warning: Item ID '{resolved_item_id}' already exists in NPC {npc_id} inventory. Skipping add.")
             # Depending on game rules, maybe return True if item is already there? Or return False.
             # Let's return False if item instance ID is already present.
             return False # Assuming inventory stores unique item instance IDs


        # Attempt to add the item ID to the inventory list
        npc.inventory.append(resolved_item_id)
        self.mark_npc_dirty(guild_id_str, npc_id) # Mark NPC as dirty (per-guild)

        print(f"NpcManager: Added item ID '{resolved_item_id}' to NPC {npc_id} inventory in guild {guild_id_str}.")


        # OPTIONAL: If ItemManager is responsible for tracking item location/ownership, update it
        # Assumes ItemManager.move_item(item_id: str, new_owner_id: Optional[str] = None, new_location_id: Optional[str] = None, guild_id: str, **kwargs: Any) -> bool
        if im and hasattr(im, 'move_item'):
            try:
                # Pass guild_id to ItemManager method
                success = await im.move_item(
                    item_id=resolved_item_id, # Item *instance* ID
                    new_owner_id=npc_id, # NPC is the new owner
                    new_location_id=None, # No longer in a location if owned
                    guild_id=guild_id_str, # Pass guild_id
                    **kwargs # Pass remaining context
                )
                if not success:
                    print(f"NpcManager: Warning: Failed to update item ownership for item {resolved_item_id} to NPC {npc_id} in guild {guild_id_str} via ItemManager. Item might be lost or duplicated!")
                    # Decide error handling: roll back inventory change? Log severe error?
                    # For now, just log and continue. NPC inventory list is updated.
                    # If ItemManager is the source of truth for location/owner, this is a problem.
                    # If NPC inventory list is the source of truth, the move_item call is secondary.
                    # Let's assume NPC inventory list is the source of truth here for simplicity.
                # else: print(f"NpcManager: ItemManager successfully updated ownership for {resolved_item_id} to {npc_id} in guild {guild_id_str}.") # Debug

            except Exception as e:
                print(f"NpcManager: Error calling ItemManager.move_item for item {resolved_item_id} to NPC {npc_id} in guild {guild_id_str}: {e}")
                traceback.print_exc()
                # Log error, but NPC inventory list is already updated.

        # Return True if the item ID was successfully added to the NPC's inventory list
        return resolved_item_id in npc.inventory # Check if it's actually in the list now


    # ИСПРАВЛЕНИЕ: Методы инвентаря должны принимать guild_id
    async def remove_item_from_inventory(self, guild_id: str, npc_id: str, item_id: str, **kwargs: Any) -> bool:
        """Удаляет предмет из инвентаря NPC для определенной гильдии. item_id здесь - ID инстанса предмета."""
        guild_id_str = str(guild_id)
        print(f"NpcManager: Removing item instance '{item_id}' from NPC {npc_id} inventory in guild {guild_id_str}")

        # ИСПРАВЛЕНИЕ: Получаем NPC с учетом guild_id
        npc = self.get_npc(guild_id_str, npc_id) # Type: Optional["NPC"]
        im = self._item_manager or kwargs.get('item_manager') # Type: Optional["ItemManager"] # Use injected or from kwargs
        loc_manager = self._location_manager or kwargs.get('location_manager') # Type: Optional["LocationManager"] # Need location for dropping item

        if not npc:
            print(f"NpcManager: NPC {npc_id} not found in guild {guild_id_str} to remove item.")
            return False

        # Check if NPC has an inventory list and the item ID is in it
        if not hasattr(npc, 'inventory') or not isinstance(npc.inventory, list) or item_id not in npc.inventory:
            print(f"NpcManager: Item instance '{item_id}' not found in NPC {npc_id} inventory list in guild {guild_id_str}.")
            return False # Item not found in the list


        try:
            # Remove the item ID from the inventory list
            npc.inventory.remove(item_id) # Remove the first occurrence
            self.mark_npc_dirty(guild_id_str, npc_id) # Mark NPC as dirty (per-guild)

            print(f"NpcManager: Removed item instance '{item_id}' from NPC {npc_id} inventory list in guild {guild_id_str}.")

            # OPTIONAL: If ItemManager is responsible for tracking item location/ownership, update it
            # By default, drop the item at the NPC's current location if ItemManager is available
            if im and hasattr(im, 'move_item'):
                 # Get the NPC's current location
                 current_location_id = getattr(npc, 'location_id', None) # Type: Optional[str]

                 if current_location_id:
                      # Pass guild_id and location_id to ItemManager method
                      try:
                          success = await im.move_item(
                              item_id=item_id, # Item *instance* ID
                              new_owner_id=None, # No owner
                              new_location_id=current_location_id, # Drop at current location
                              guild_id=guild_id_str, # Pass guild_id
                              **kwargs # Pass remaining context
                          )
                          if not success:
                               print(f"NpcManager: Warning: Failed to update item location for item {item_id} to location {current_location_id} for NPC {npc_id} in guild {guild_id_str} via ItemManager. Item might be lost or duplicated!")
                          # else: print(f"NpcManager: ItemManager successfully updated location for {item_id} to {current_location_id} in guild {guild_id_str}.") # Debug

                      except Exception as e:
                           print(f"NpcManager: Error calling ItemManager.move_item (drop) for item {item_id} from NPC {npc_id} in guild {guild_id_str}: {e}")
                           traceback.print_exc()
                 else:
                      print(f"NpcManager: Warning: NPC {npc_id} has no location_id in guild {guild_id_str}. Item instance '{item_id}' removed from inventory list, but cannot be dropped anywhere via ItemManager.")
                      # The item is effectively gone unless other cleanup logic handles it.

            # Return True as the item was successfully removed from the NPC's inventory list
            return True

        except Exception as e:
            print(f"NpcManager: Error removing item instance '{item_id}' from NPC {npc_id} inventory in guild {guild_id_str}: {e}")
            traceback.print_exc()
            # Decide if you should re-raise or return False on error.
            # Returning False indicates failure, but the item might have been partially removed (e.g., from list but move_item failed).
            # Let's return False on error during the core process.
            return False


    # ИСПРАВЛЕНИЕ: Методы статусов должны принимать guild_id
    async def add_status_effect(self, guild_id: str, npc_id: str, status_type: str, duration: Optional[float], source_id: Optional[str] = None, **kwargs: Any) -> Optional[str]:
        """Добавляет статус-эффект к NPC для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"NpcManager: Adding status '{status_type}' to NPC {npc_id} in guild {guild_id_str}...")

        # ИСПРАВЛЕНИЕ: Получаем NPC с учетом guild_id
        npc = self.get_npc(guild_id_str, npc_id) # Type: Optional["NPC"]
        sm = self._status_manager or kwargs.get('status_manager') # Type: Optional["StatusManager"]

        if not npc:
            print(f"NpcManager: NPC {npc_id} not found in guild {guild_id_str} to add status.")
            return None
        if not sm or not hasattr(sm, 'add_status_effect_to_entity'):
             print(f"NpcManager: StatusManager or add_status_effect_to_entity method not available for guild {guild_id_str}.")
             return None

        try:
            # Call StatusManager method, passing target details and guild_id
            # Assumes StatusManager.add_status_effect_to_entity(target_id, target_type, status_type, duration, source_id, guild_id, **kwargs) -> Optional[str]
            status_effect_id = await sm.add_status_effect_to_entity(
                target_id=npc_id,
                target_type='NPC',
                status_type=str(status_type), # Ensure type is string
                duration=duration, # Can be float or None
                source_id=str(source_id) if source_id is not None else None, # Ensure source_id is string or None
                guild_id=guild_id_str, # Pass guild_id
                **kwargs # Pass remaining context (includes time_manager etc.)
            )

            if status_effect_id:
                # Add the new status effect ID to the NPC's status_effects list
                if not hasattr(npc, 'status_effects') or not isinstance(npc.status_effects, list):
                    print(f"NpcManager: Warning: NPC {npc_id} status_effects is not list or missing. Initializing empty list.")
                    npc.status_effects = []
                if status_effect_id not in npc.status_effects: # Avoid duplicates if adding same effect ID twice
                    npc.status_effects.append(status_effect_id)
                    self.mark_npc_dirty(guild_id_str, npc_id) # Mark NPC as dirty (per-guild)
                    print(f"NpcManager: Added status effect '{status_type}' (ID: {status_effect_id}) to NPC {npc_id} in guild {guild_id_str}.")
                else:
                    # Status effect ID already in the list, but the StatusManager might have updated it
                    # Mark as dirty just in case (if the StatusManager call modified the NPC object directly, though it shouldn't)
                    self.mark_npc_dirty(guild_id_str, npc_id)
                    print(f"NpcManager: Status effect ID {status_effect_id} for '{status_type}' already in NPC {npc_id} status_effects list in guild {guild_id_str}.")

            return status_effect_id

        except Exception as e:
            print(f"NpcManager: Error adding status effect '{status_type}' to NPC {npc_id} in guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            return None


    # ИСПРАВЛЕНИЕ: Методы статусов должны принимать guild_id
    async def remove_status_effect(self, guild_id: str, npc_id: str, status_effect_id: str, **kwargs: Any) -> Optional[str]:
        """Удаляет статус-эффект с NPC по его ID инстанса для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"NpcManager: Removing status effect instance '{status_effect_id}' from NPC {npc_id} in guild {guild_id_str}...")

        # ИСПРАВЛЕНИЕ: Получаем NPC с учетом guild_id
        npc = self.get_npc(guild_id_str, npc_id) # Type: Optional["NPC"]
        sm = self._status_manager or kwargs.get('status_manager') # Type: Optional["StatusManager"]

        if not npc:
            print(f"NpcManager: NPC {npc_id} not found in guild {guild_id_str} to remove status.")
            return None
        if not sm or not hasattr(sm, 'remove_status_effect'):
             print(f"NpcManager: StatusManager or remove_status_effect method not available for guild {guild_id_str}.")
             return None

        # Remove the status effect ID from the NPC's status_effects list
        removed_from_list = False
        if hasattr(npc, 'status_effects') and isinstance(npc.status_effects, list):
            try:
                npc.status_effects.remove(status_effect_id) # Remove the first occurrence
                removed_from_list = True
                self.mark_npc_dirty(guild_id_str, npc_id) # Mark NPC as dirty (per-guild)
                print(f"NpcManager: Removed status effect instance '{status_effect_id}' from NPC {npc_id} status_effects list in guild {guild_id_str}.")
            except ValueError:
                # Item ID not found in the list
                print(f"NpcManager: Warning: Status effect ID '{status_effect_id}' not found in NPC {npc_id} status_effects list in guild {guild_id_str}.")
                # Status effect might exist in StatusManager but not on NPC list, or vice versa.
                # Proceed with removing from StatusManager anyway.
        else:
             print(f"NpcManager: Warning: NPC {npc_id} status_effects is not list or missing. Cannot remove from list.")


        try:
            # Call StatusManager method to remove the status effect instance
            # Assumes StatusManager.remove_status_effect(status_effect_id, guild_id, **kwargs) -> Optional[str]
            removed_id = await sm.remove_status_effect(
                status_effect_id=status_effect_id,
                guild_id=guild_id_str, # Pass guild_id
                **kwargs # Pass remaining context
            )

            if removed_id:
                 print(f"NpcManager: StatusManager successfully removed status effect instance '{removed_id}' for NPC {npc_id} in guild {guild_id_str}.")
                 return removed_id # Return the ID that was removed
            else:
                 # StatusManager didn't find/remove it, but it might have been removed from the NPC's list
                 print(f"NpcManager: StatusManager failed to remove status effect instance '{status_effect_id}' for NPC {npc_id} in guild {guild_id_str}. Was removed from NPC list: {removed_from_list}.")
                 # Return None if StatusManager failed, even if removed from NPC list?
                 # Or return status_effect_id if removed_from_list is True?
                 # Let's return removed_id (which is None if StatusManager failed) for clarity.
                 return None

        except Exception as e:
            print(f"NpcManager: Error calling StatusManager.remove_status_effect for ID '{status_effect_id}' on NPC {npc_id} in guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            return None


    # Methods for persistence (called by PersistenceManager):
    # These methods must work per-guild
    # required_args_for_load, required_args_for_save, required_args_for_rebuild already defined as class attributes

    # ИСПРАВЛЕНИЕ: save_state должен принимать guild_id
    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет активные/измененные NPC для определенной гильдии."""
        guild_id_str = str(guild_id)
        print(f"NpcManager: Saving NPC state for guild {guild_id_str}...")

        if self._db_adapter is None:
            print(f"NpcManager: Warning: Cannot save NPC state for guild {guild_id_str}, DB adapter missing.")
            return

        # ИСПРАВЛЕНИЕ: Собираем dirty/deleted ID ИЗ per-guild кешей
        dirty_npc_ids_for_guild_set = self._dirty_npcs.get(guild_id_str, set()).copy() # Рабочая копия Set
        deleted_npc_ids_for_guild_set = self._deleted_npc_ids.get(guild_id_str, set()).copy() # Рабочая копия Set

        if not dirty_npc_ids_for_guild_set and not deleted_npc_ids_for_guild_set:
             # print(f"NpcManager: No dirty or deleted NPCs to save for guild {guild_id_str}.") # Too noisy
             # ИСПРАВЛЕНИЕ: Если нечего сохранять/удалять, очищаем per-guild dirty/deleted сеты
             self._dirty_npcs.pop(guild_id_str, None)
             self._deleted_npc_ids.pop(guild_id_str, None)
             return

        print(f"NpcManager: Saving {len(dirty_npc_ids_for_guild_set)} dirty, {len(deleted_npc_ids_for_guild_set)} deleted NPCs for guild {guild_id_str}...")

        # 4. Удаление NPC, помеченных для удаления для этой гильдии
        if deleted_npc_ids_for_guild_set:
            ids_to_delete = list(deleted_npc_ids_for_guild_set)
            placeholders_del = ','.join(['?'] * len(ids_to_delete))
            # Убеждаемся, что удаляем ТОЛЬКО для данного guild_id и по ID из списка
            delete_sql = f"DELETE FROM npcs WHERE guild_id = ? AND id IN ({placeholders_del})"
            try:
                await self._db_adapter.execute(delete_sql, (guild_id_str, *tuple(ids_to_delete)))
                print(f"NpcManager: Deleted {len(ids_to_delete)} NPCs from DB for guild {guild_id_str}.")
                # ИСПРАВЛЕНИЕ: Очищаем deleted set для этой гильдии после успешного удаления
                self._deleted_npc_ids.pop(guild_id_str, None)
            except Exception as e:
                print(f"NpcManager: Error deleting NPCs for guild {guild_id_str}: {e}")
                import traceback
                print(traceback.format_exc())
                # Do NOT clear _deleted_npc_ids[guild_id_str], try again next save

        # 5. Сохранение/обновление NPC для этой гильдии
        # ИСПРАВЛЕНИЕ: Фильтруем dirty_instances на те, что все еще существуют в per-guild кеше
        guild_npcs_cache = self._npcs.get(guild_id_str, {})
        npcs_to_save: List["NPC"] = [guild_npcs_cache[nid] for nid in list(dirty_npc_ids_for_guild_set) if nid in guild_npcs_cache]

        if npcs_to_save:
             print(f"NpcManager: Upserting {len(npcs_to_save)} NPCs for guild {guild_id_str}...")
             upsert_sql = '''
             INSERT OR REPLACE INTO npcs
             (id, template_id, name, guild_id, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects, is_temporary)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             '''
             data_to_upsert = []
             upserted_npc_ids: Set[str] = set() # Keep track of successfully prepared IDs

             for npc in npcs_to_save:
                  try:
                       # Убеждаемся, что у объекта NPC есть все нужные атрибуты
                       npc_id = getattr(npc, 'id', None)
                       npc_guild_id = getattr(npc, 'guild_id', None)

                       if npc_id is None or str(npc_guild_id) != guild_id_str:
                           print(f"NpcManager: Warning: Skipping upsert for NPC with invalid ID ('{npc_id}') or mismatched guild ('{npc_guild_id}') during save for guild {guild_id_str}. Expected guild {guild_id_str}.")
                           continue # Skip this NPC if invalid or wrong guild

                       template_id = getattr(npc, 'template_id', None)
                       name = getattr(npc, 'name', 'Unnamed NPC')
                       location_id = getattr(npc, 'location_id', None)
                       stats = getattr(npc, 'stats', {})
                       inventory = getattr(npc, 'inventory', [])
                       current_action = getattr(npc, 'current_action', None)
                       action_queue = getattr(npc, 'action_queue', [])
                       party_id = getattr(npc, 'party_id', None)
                       state_variables = getattr(npc, 'state_variables', {})
                       health = getattr(npc, 'health', 50.0)
                       max_health = getattr(npc, 'max_health', 50.0)
                       is_alive = getattr(npc, 'is_alive', True)
                       status_effects = getattr(npc, 'status_effects', [])
                       is_temporary = getattr(npc, 'is_temporary', False)

                       # Ensure data types are suitable for JSON dumping
                       if not isinstance(stats, dict): stats = {}
                       if not isinstance(inventory, list): inventory = []
                       if not isinstance(action_queue, list): action_queue = []
                       if not isinstance(state_variables, dict): state_variables = {}
                       if not isinstance(status_effects, list): status_effects = []


                       stats_json = json.dumps(stats)
                       inv_json = json.dumps(inventory)
                       curr_json = json.dumps(current_action) if current_action is not None else None
                       queue_json = json.dumps(action_queue)
                       state_json = json.dumps(state_variables)
                       status_json = json.dumps(status_effects)


                       data_to_upsert.append((
                           str(npc_id),
                           str(template_id) if template_id is not None else None, # Ensure template_id is str or None
                           str(name),
                           guild_id_str, # Ensure guild_id is string
                           str(location_id) if location_id is not None else None, # Ensure location_id is str or None
                           stats_json,
                           inv_json,
                           curr_json,
                           queue_json,
                           str(party_id) if party_id is not None else None, # Ensure party_id is str or None
                           state_json,
                           float(health),
                           float(max_health),
                           int(bool(is_alive)), # Save bool as integer (0 or 1)
                           status_json,
                           int(bool(is_temporary)), # Save bool as integer (0 or 1)
                       ))
                       upserted_npc_ids.add(str(npc_id)) # Track IDs prepared for upsert

                  except Exception as e:
                      print(f"NpcManager: Error preparing data for NPC {getattr(npc, 'id', 'N/A')} ('{getattr(npc, 'name', 'N/A')}', guild {getattr(npc, 'guild_id', 'N/A')}) for upsert: {e}")
                      import traceback
                      print(traceback.format_exc())
                      # This NPC won't be saved in this batch but remains in _dirty_npcs

             if data_to_upsert:
                  if self._db_adapter is None:
                       print(f"NpcManager: Warning: DB adapter is None during NPC upsert batch for guild {guild_id_str}.")
                  else:
                       await self._db_adapter.execute_many(upsert_sql, data_to_upsert)
                       print(f"NpcManager: Successfully upserted {len(data_to_upsert)} NPCs for guild {guild_id_str}.")
                       # ИСПРАВЛЕНИЕ: Очищаем dirty set для этой гильдии только для успешно сохраненных ID
                       if guild_id_str in self._dirty_npcs:
                            self._dirty_npcs[guild_id_str].difference_update(upserted_npc_ids)
                            # Если после очистки set пуст, удаляем ключ гильдии
                            if not self._dirty_npcs[guild_id_str]:
                                 del self._dirty_npcs[guild_id_str]


        print(f"NpcManager: Save state complete for guild {guild_id_str}.")

    # ИСПРАВЛЕНИЕ: load_state должен принимать guild_id
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает NPC для определенной гильдии из базы данных в кеш."""
        guild_id_str = str(guild_id)
        print(f"NpcManager: Loading NPCs for guild {guild_id_str} from DB...")

        if self._db_adapter is None:
            print(f"NpcManager: Warning: Cannot load NPCs for guild {guild_id_str}, DB adapter missing.")
            # TODO: In non-DB mode, load placeholder data or raise
            return

        # ИСПРАВЛЕНИЕ: Очистите кеши ТОЛЬКО для этой гильдии перед загрузкой
        self._npcs.pop(guild_id_str, None)
        self._npcs[guild_id_str] = {} # Создаем пустой кеш для этой гильдии

        self._entities_with_active_action.pop(guild_id_str, None)
        self._entities_with_active_action[guild_id_str] = set() # Создаем пустой кеш для этой гильгии

        # При загрузке, считаем, что все в DB "чистое", поэтому очищаем dirty/deleted для этой гильдии
        self._dirty_npcs.pop(guild_id_str, None)
        self._deleted_npc_ids.pop(guild_id_str, None)

        rows = []
        try:
            # ВЫПОЛНЯЕМ fetchall С ФИЛЬТРОМ по guild_id
            sql = '''
            SELECT id, template_id, name, guild_id, location_id, stats, inventory, current_action, action_queue, party_id, state_variables, health, max_health, is_alive, status_effects, is_temporary
            FROM npcs WHERE guild_id = ?
            '''
            rows = await self._db_adapter.fetchall(sql, (guild_id_str,))
            print(f"NpcManager: Found {len(rows)} NPCs in DB for guild {guild_id_str}.")

        except Exception as e:
            print(f"NpcManager: ❌ CRITICAL ERROR executing DB fetchall for NPCs for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            raise # Пробрасываем критическую ошибку


        loaded_count = 0
        guild_npcs_cache = self._npcs[guild_id_str] # Get the cache dict for this specific guild
        guild_active_action_cache = self._entities_with_active_action[guild_id_str] # Get the active action set for this guild

        for row in rows:
            data = dict(row)
            try:
                # Validate and parse data
                npc_id_raw = data.get('id')
                loaded_guild_id_raw = data.get('guild_id')

                if npc_id_raw is None or loaded_guild_id_raw is None:
                     print(f"NpcManager: Warning: Skipping row with missing mandatory fields (ID, Guild ID) for guild {guild_id_str}. Row data: {data}. ")
                     continue # Skip row missing critical data

                npc_id = str(npc_id_raw)
                loaded_guild_id = str(loaded_guild_id_raw)

                # Verify guild ID match
                if loaded_guild_id != guild_id_str:
                    print(f"NpcManager: Warning: Mismatch guild_id for NPC {npc_id}: Expected {guild_id_str}, got {loaded_guild_id}. Skipping.")
                    continue # Skip row with wrong guild ID


                # Parse JSON fields, handle None/malformed data gracefully
                try:
                    data['stats'] = json.loads(data.get('stats') or '{}') if isinstance(data.get('stats'), (str, bytes)) else {}
                except (json.JSONDecodeError, TypeError):
                     print(f"NpcManager: Warning: Failed to parse stats for NPC {npc_id} in guild {guild_id_str}. Setting to {{}}. Data: {data.get('stats')}")
                     data['stats'] = {}

                try:
                    data['inventory'] = json.loads(data.get('inventory') or '[]') if isinstance(data.get('inventory'), (str, bytes)) else []
                except (json.JSONDecodeError, TypeError):
                    print(f"NpcManager: Warning: Failed to parse inventory for NPC {npc_id} in guild {guild_id_str}. Setting to []. Data: {data.get('inventory')}")
                    data['inventory'] = []

                try:
                    current_action_data = data.get('current_action')
                    data['current_action'] = json.loads(current_action_data) if isinstance(current_action_data, (str, bytes)) else None
                except (json.JSONDecodeError, TypeError):
                     print(f"NpcManager: Warning: Failed to parse current_action for NPC {npc_id} in guild {guild_id_str}. Setting to None. Data: {data.get('current_action')}")
                     data['current_action'] = None

                try:
                    data['action_queue'] = json.loads(data.get('action_queue') or '[]') if isinstance(data.get('action_queue'), (str, bytes)) else []
                except (json.JSONDecodeError, TypeError):
                     print(f"NpcManager: Warning: Failed to parse action_queue for NPC {npc_id} in guild {guild_id_str}. Setting to []. Data: {data.get('action_queue')}")
                     data['action_queue'] = []

                try:
                    data['state_variables'] = json.loads(data.get('state_variables') or '{}') if isinstance(data.get('state_variables'), (str, bytes)) else {}
                except (json.JSONDecodeError, TypeError):
                     print(f"NpcManager: Warning: Failed to parse state_variables for NPC {npc_id} in guild {guild_id_str}. Setting to {{}}. Data: {data.get('state_variables')}")
                     data['state_variables'] = {}

                try:
                    data['status_effects'] = json.loads(data.get('status_effects') or '[]') if isinstance(data.get('status_effects'), (str, bytes)) else []
                except (json.JSONDecodeError, TypeError):
                     print(f"NpcManager: Warning: Failed to parse status_effects for NPC {npc_id} in guild {guild_id_str}. Setting to []. Data: {data.get('status_effects')}")
                     data['status_effects'] = []

                # Convert boolean/numeric types, handle potential None/malformed data
                data['health'] = float(data.get('health', 50.0)) if isinstance(data.get('health'), (int, float)) else 50.0
                data['max_health'] = float(data.get('max_health', 50.0)) if isinstance(data.get('max_health'), (int, float)) else 50.0
                data['is_alive'] = bool(data.get('is_alive', 0)) if data.get('is_alive') is not None else True # Default to True
                data['is_temporary'] = bool(data.get('is_temporary', 0)) if data.get('is_temporary') is not None else False # Default to False


                # Ensure required object IDs are strings or None
                data['id'] = npc_id
                data['guild_id'] = loaded_guild_id
                data['template_id'] = str(data['template_id']) if data.get('template_id') is not None else None
                data['location_id'] = str(data['location_id']) if data.get('location_id') is not None else None
                data['party_id'] = str(data['party_id']) if data.get('party_id') is not None else None


                # Create NPC object
                npc = NPC.from_dict(data) # Requires NPC.from_dict method

                # Add NPC object to the per-guild cache
                guild_npcs_cache[npc.id] = npc

                # If NPC has active action or queue, add to per-guild active set
                if getattr(npc, 'current_action', None) is not None or getattr(npc, 'action_queue', []):
                    guild_active_action_cache.add(npc.id)


                loaded_count += 1

            except Exception as e:
                print(f"NpcManager: Error loading NPC {data.get('id', 'N/A')} for guild {guild_id_str}: {e}")
                import traceback
                print(traceback.format_exc())
                # Continue loop for other rows

        print(f"NpcManager: Successfully loaded {loaded_count} NPCs into cache for guild {guild_id_str}.")
        if loaded_count < len(rows):
             print(f"NpcManager: Note: Failed to load {len(rows) - loaded_count} NPCs for guild {guild_id_str} due to errors.")


    # ИСПРАВЛЕНИЕ: rebuild_runtime_caches должен принимать guild_id
    async def rebuild_runtime_caches(self, guild_id: str, **kwargs: Any) -> None:
        """Перестройка кешей, специфичных для выполнения, после загрузки состояния для гильдии."""
        guild_id_str = str(guild_id)
        print(f"NpcManager: Rebuilding runtime caches for guild {guild_id_str}...")

        # Rebuild the per-guild active action set based on the loaded NPCs for this guild
        guild_npcs_cache = self._npcs.get(guild_id_str, {})
        guild_active_action_cache = self._entities_with_active_action.setdefault(guild_id_str, set())
        guild_active_action_cache.clear() # Clear previous state for this guild

        for npc_id, npc in guild_npcs_cache.items():
             # Check if NPC has active action or queue
             if getattr(npc, 'current_action', None) is not None or getattr(npc, 'action_queue', []):
                  guild_active_action_cache.add(npc_id)

             # TODO: Optional: Check for busyness via other managers if needed for this cache
             # Example: If NPC is in a combat according to CombatManager for THIS guild
             # combat_mgr = kwargs.get('combat_manager') # Type: Optional["CombatManager"]
             # if combat_mgr and hasattr(combat_mgr, 'is_participating_in_combat'):
             #      if await combat_mgr.is_participating_in_combat(npc_id, "NPC", guild_id=guild_id_str):
             #           guild_active_action_cache.add(npc_id)

        print(f"NpcManager: Rebuild runtime caches complete for guild {guild_id_str}. Active action set size: {len(guild_active_action_cache)}")


    # ИСПРАВЛЕНИЕ: mark_npc_dirty должен принимать guild_id
    def mark_npc_dirty(self, guild_id: str, npc_id: str) -> None:
        """Помечает NPC как измененного для последующего сохранения для определенной гильдии."""
        guild_id_str = str(guild_id)
        # Add check that the NPC ID exists in the per-guild cache
        guild_npcs_cache = self._npcs.get(guild_id_str)
        if guild_npcs_cache and npc_id in guild_npcs_cache:
             self._dirty_npcs.setdefault(guild_id_str, set()).add(npc_id) # Add to per-guild Set
        # else: print(f"NpcManager: Warning: Attempted to mark non-existent NPC {npc_id} in guild {guild_id_str} as dirty.") # Too noisy?

    # ИСПРАВЛЕНИЕ: mark_npc_deleted не нужен как отдельный метод, логика в remove_npc


    # --- Методы для управления активностью/занятостью ---
    # These methods operate on the NPC object and the per-guild active action set

    # ИСПРАВЛЕНИЕ: set_active_action должен принимать guild_id
    def set_active_action(self, guild_id: str, npc_id: str, action_details: Optional[Dict[str, Any]]) -> None:
        """Устанавливает текущее активное действие NPC для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем NPC с учетом guild_id
        npc = self.get_npc(guild_id_str, npc_id) # Type: Optional["NPC"]
        if not npc:
            print(f"NpcManager: NPC {npc_id} not found in guild {guild_id_str} to set active action.")
            return

        # Убедимся, что у объекта NPC есть атрибут current_action
        if hasattr(npc, 'current_action'):
            npc.current_action = action_details
        else:
            print(f"NpcManager: Warning: NPC model for {npc_id} in guild {guild_id_str} is missing 'current_action' attribute. Cannot set active action.")
            return # Cannot set if attribute is missing


        # ИСПРАВЛЕНИЕ: Управляем занятостью в per-guild Set
        guild_active_action_cache = self._entities_with_active_action.setdefault(guild_id_str, set())
        if action_details is not None:
            guild_active_action_cache.add(npc_id)
        else:
            # Check if there's still something in the queue before marking not busy
            if not getattr(npc, 'action_queue', []): # Safely check action_queue attribute
                 guild_active_action_cache.discard(npc_id)


        self.mark_npc_dirty(guild_id_str, npc_id) # Mark as dirty (per-guild)


    # ИСПРАВЛЕНИЕ: add_action_to_queue должен принимать guild_id
    def add_action_to_queue(self, guild_id: str, npc_id: str, action_details: Dict[str, Any]) -> None:
        """Добавляет действие в очередь NPC для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем NPC с учетом guild_id
        npc = self.get_npc(guild_id_str, npc_id) # Type: Optional["NPC"]
        if not npc:
            print(f"NpcManager: NPC {npc_id} not found in guild {guild_id_str} to add action to queue.")
            return

        # Убедимся, что у объекта NPC есть атрибут action_queue и это список
        if not hasattr(npc, 'action_queue') or not isinstance(npc.action_queue, list):
             print(f"NpcManager: Warning: NPC model for {npc_id} in guild {guild_id_str} is missing 'action_queue' list or it's incorrect type. Initializing empty list.")
             npc.action_queue = [] # Initialize empty list if missing/wrong type

        npc.action_queue.append(action_details)
        self.mark_npc_dirty(guild_id_str, npc_id) # Mark as dirty (per-guild)
        # ИСПРАВЛЕНИЕ: Помечаем занятым в per-guild Set, т.к. есть что-то в очереди
        self._entities_with_active_action.setdefault(guild_id_str, set()).add(npc_id)


    # ИСПРАВЛЕНИЕ: get_next_action_from_queue должен принимать guild_id
    def get_next_action_from_queue(self, guild_id: str, npc_id: str) -> Optional[Dict[str, Any]]:
        """Извлекает следующее действие из очереди NPC для определенной гильдии."""
        guild_id_str = str(guild_id)
        # ИСПРАВЛЕНИЕ: Получаем NPC с учетом guild_id
        npc = self.get_npc(guild_id_str, npc_id) # Type: Optional["NPC"]
        # Убедимся, что у объекта NPC есть атрибут action_queue и это не пустой список
        if not npc or not hasattr(npc, 'action_queue') or not isinstance(npc.action_queue, list) or not npc.action_queue:
            return None

        # Извлекаем первое действие из очереди
        next_action = npc.action_queue.pop(0) # Removes from start of list (modifies attribute)
        self.mark_npc_dirty(guild_id_str, npc_id) # Mark as dirty (per-guild)

        # ИСПРАВЛЕНИЕ: Если очередь опустела И нет текущего действия, снимаем пометку "занят" для этой гильдии
        if not npc.action_queue and getattr(npc, 'current_action', None) is None: # Safely check current_action attribute
             guild_active_action_cache = self._entities_with_active_action.get(guild_id_str)
             if guild_active_action_cache:
                  guild_active_action_cache.discard(npc_id)

        return next_action

    # TODO: Implement clean_up_for_party(entity_id, entity_type, context) if PartyManager calls this
    # async def clean_up_from_party(self, npc_id: str, context: Dict[str, Any]) -> None:
    #      """Сбросить party_id NPC когда он покидает группу."""
    #      guild_id = context.get('guild_id') # Get guild_id from context
    #      if guild_id is None:
    #           print(f"NpcManager: Error in clean_up_from_party: Missing guild_id in context for NPC {npc_id}.")
    #           return
    #      guild_id_str = str(guild_id)
    #      npc = self.get_npc(guild_id_str, npc_id) # Get NPC with guild_id
    #      if not npc:
    #           print(f"NpcManager: NPC {npc_id} not found in guild {guild_id_str} for party cleanup.")
    #           return
    #      if getattr(npc, 'party_id', None) is not None:
    #           npc.party_id = None # Reset party_id
    #           self.mark_npc_dirty(guild_id_str, npc_id) # Mark dirty
    #           print(f"NpcManager: Cleaned up party_id for NPC {npc_id} in guild {guild_id_str}.")

    # TODO: Implement clean_up_for_combat(entity_id, entity_type, context) if CombatManager calls this
    # async def clean_up_from_combat(self, npc_id: str, context: Dict[str, Any]) -> None:
    #      """Сбросить combat_id/status для NPC когда он покидает бой."""
    #      guild_id = context.get('guild_id') # Get guild_id from context
    #      if guild_id is None:
    #           print(f"NpcManager: Error in clean_up_from_combat: Missing guild_id in context for NPC {npc_id}.")
    #           return
    #      guild_id_str = str(guild_id)
    #      npc = self.get_npc(guild_id_str, npc_id) # Get NPC with guild_id
    #      if not npc:
    #           print(f"NpcManager: NPC {npc_id} not found in guild {guild_id_str} for combat cleanup.")
    #           return
    #      # TODO: Reset combat-specific state on NPC if any (e.g. is_in_combat flag, combat_id)
    #      # For now, basic cleanup might just involve marking dirty if state changed
    #      # self.mark_npc_dirty(guild_id_str, npc_id)
    #      print(f"NpcManager: Cleaned up combat state for NPC {npc_id} in guild {guild_id_str}.")


    # TODO: Implement clean_up_for_dialogue(entity_id, entity_type, context) if DialogueManager calls this
    # async def clean_up_from_dialogue(self, npc_id: str, context: Dict[str, Any]) -> None:
    #      """Сбросить dialogue_id/state NPC когда он покидает диалог."""
    #      guild_id = context.get('guild_id') # Get guild_id from context
    #      if guild_id is None:
    #           print(f"NpcManager: Error in clean_up_from_dialogue: Missing guild_id in context for NPC {npc_id}.")
    #           return
    #      guild_id_str = str(guild_id)
    #      npc = self.get_npc(guild_id_str, npc_id) # Get NPC with guild_id
    #      if not npc:
    #           print(f"NpcManager: NPC {npc_id} not found in guild {guild_id_str} for dialogue cleanup.")
    #           return
    #      # TODO: Reset dialogue-specific state on NPC if any (e.g. current_dialogue_id, dialogue_state)
    #      # For now, basic cleanup might just involve marking dirty if state changed
    #      # self.mark_npc_dirty(guild_id_str, npc_id)
    #      print(f"NpcManager: Cleaned up dialogue state for NPC {npc_id} in guild {guild_id_str}.")

# --- Конец класса NpcManager ---

print("DEBUG: npc_manager.py module loaded.")
