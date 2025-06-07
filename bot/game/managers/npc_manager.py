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
    from bot.services.db_service import DBService # Changed
    # Добавляем модели, используемые в аннотациях или context
    from bot.game.models.npc import NPC # Аннотируем как "NPC"
    # from bot.game.models.character import Character # Если Character объекты передаются в методы NPCManager
    # from bot.game.models.party import Party # Если Party объекты передаются в методы NPCManager
    # Добавляем менеджеры
    # from bot.game.models.party import Party # Если Party объекты передаются в методы NPCManager
    # Добавляем менеджеры
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.party_manager import PartyManager
    from bot.game.managers.character_manager import CharacterManager # Нужен для clean_up_from_party в PartyManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.managers.game_log_manager import GameLogManager

    # Добавляем другие менеджеры, если они передаются в __init__ или используются в аннотациях методов
    # from bot.game.managers.event_manager import EventManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.services.campaign_loader import CampaignLoader # Added for type hint
    from bot.ai.multilingual_prompt_generator import MultilingualPromptGenerator
    from bot.services.openai_service import OpenAIService
    from bot.ai.ai_response_validator import AIResponseValidator # Added import

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
        db_service: Optional["DBService"] = None, # Changed
        settings: Optional[Dict[str, Any]] = None,
        item_manager: Optional["ItemManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        character_manager: Optional["CharacterManager"] = None, # Potential need for cleanup?
        rule_engine: Optional["RuleEngine"] = None,
        combat_manager: Optional["CombatManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
        # event_manager: Optional["EventManager"] = None, # if needed
        location_manager: Optional["LocationManager"] = None, # if needed for default loc logic
        game_log_manager: Optional["GameLogManager"] = None,
        multilingual_prompt_generator: Optional["MultilingualPromptGenerator"] = None, # New
        openai_service: Optional["OpenAIService"] = None, # New
        ai_validator: Optional["AIResponseValidator"] = None # New for validation
    ):
        print("Initializing NpcManager...")
        self._db_service = db_service # Changed
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
        self._location_manager = location_manager # Store LocationManager if needed
        self._game_log_manager = game_log_manager
        self._multilingual_prompt_generator = multilingual_prompt_generator
        self._openai_service = openai_service
        self._ai_validator = ai_validator # Store the validator instance


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
        npc_template_id: str, # This will be used as archetype_id if campaign_loader is present
        location_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[Union[str, Dict[str, str]]]: # Updated return type
        """
        Создает нового NPC для определенной гильдии.
        If AI generation is used and successful, it saves the content for moderation
        and returns a dict with status 'pending_moderation' and 'request_id'.
        Otherwise, it creates the NPC directly from an archetype/template and saves to 'npcs' table.
        Returns NPC ID on success, or dict for moderation, or None on failure.
        """
        guild_id_str = str(guild_id)
        archetype_id_to_load = npc_template_id
        archetype_data_loaded: Optional[Dict[str, Any]] = None  # Initialize archetype_data_loaded
        ai_generated_data: Optional[Dict[str, Any]] = None  # Initialize ai_generated_data

        # Base values - these will be used if not overridden by archetype, AI, or kwargs
        base_name: str = "Mysterious Stranger"
        base_inventory: List[str] = []
        base_stats: Dict[str, Any] = {"strength": 5, "dexterity": 5, "intelligence": 5, "max_health": 50.0}
        base_archetype_name: str = "commoner"
        base_traits: List[str] = ["cautious"]
        base_desires: List[str] = ["survival"]
        base_motives: List[str] = ["self-preservation"]
        base_backstory: str = "A person with a past they don't speak of."
        
        print(f"NpcManager: Creating NPC from template/archetype '{archetype_id_to_load}' at location {location_id} for guild {guild_id_str}...")

        if self._db_service is None or self._db_service.adapter is None: # Changed
            print(f"NpcManager: No DB service or adapter available for guild {guild_id_str}.")
            return None

        npc_id = str(uuid.uuid4()) # Common ID for both paths initially

        # Determine if AI generation should be triggered
        trigger_ai_generation = False
        campaign_loader: Optional["CampaignLoader"] = kwargs.get('campaign_loader')

        if npc_template_id.startswith("AI:"):
            trigger_ai_generation = True
        elif campaign_loader and hasattr(campaign_loader, 'get_npc_archetypes'):
            try:
                all_archetypes: List[Dict[str, Any]] = campaign_loader.get_npc_archetypes()
                found_archetype = next((arch for arch in all_archetypes if isinstance(arch, dict) and arch.get('id') == archetype_id_to_load), None)
                if found_archetype:
                    archetype_data_loaded = found_archetype
                    print(f"NpcManager: Archetype '{archetype_id_to_load}' found and loaded.")
                else:
                    trigger_ai_generation = True
                    print(f"NpcManager: Archetype '{archetype_id_to_load}' not found. Triggering AI generation.")
            except Exception as e:
                print(f"NpcManager: Error loading NPC archetypes: {e}. Triggering AI generation.")
                trigger_ai_generation = True
        else: # No campaign loader or method means we can't load archetype, so try AI
            trigger_ai_generation = True
            print(f"NpcManager: No CampaignLoader to verify archetype '{archetype_id_to_load}'. Triggering AI generation.")


        if trigger_ai_generation:
            npc_id_concept = npc_template_id.replace("AI:", "", 1) if npc_template_id.startswith("AI:") else npc_template_id
            # ai_generated_data is already initialized to None
            ai_generated_data = await self.generate_npc_details_from_ai(
                guild_id=guild_id_str,
                npc_id_concept=npc_id_concept,
                player_level_for_scaling=kwargs.get('player_level')
            )
            if ai_generated_data is None:
                print(f"NpcManager: AI generation failed for concept '{npc_id_concept}'. NPC creation aborted.")
                return None # AI generation failed, abort NPC creation

            # --- Moderation Step for AI Generated Content ---
            user_id = kwargs.get('user_id')
            if not user_id:
                print(f"NpcManager: CRITICAL - user_id not found in kwargs for AI NPC generation. Aborting moderation save.")
                # Depending on policy, you might allow creation without moderation record, or abort.
                # For now, let's abort as user_id is crucial for moderation tracking.
                return None

            request_id = str(uuid.uuid4())
            content_type = 'npc'
            try:
                data_json = json.dumps(ai_generated_data)
                await self._db_service.adapter.save_pending_moderation_request( # Changed
                    request_id, guild_id_str, str(user_id), content_type, data_json
                )
                print(f"NpcManager: AI-generated NPC data for '{npc_id_concept}' saved for moderation. Request ID: {request_id}")
                return {"status": "pending_moderation", "request_id": request_id}
            except Exception as e_mod_save:
                print(f"NpcManager: ERROR saving AI NPC content for moderation: {e_mod_save}")
                traceback.print_exc()
                return None # Failed to save for moderation, abort NPC creation

        # --- This part below is now only for NON-AI generated NPCs (i.e., from archetype_data_loaded) ---
        # Layering: kwargs > archetype_data > generated/default (AI data path now returns above)
        # Start with base values, potentially overridden by archetype, then AI, then kwargs
        final_data: Dict[str, Any] = {
            'name': base_name, # Default name
            'name_i18n': {"en": base_name, "ru": base_name}, # Default i18n name
            'stats': base_stats.copy(), # Default stats
            'inventory': base_inventory.copy(), # Default inventory
            'archetype': base_archetype_name, # Default archetype
            'traits': base_traits.copy(), # Default traits
            'desires': base_desires.copy(), # Default desires
            'motives': base_motives.copy(), # Default motives
            'backstory': base_backstory, # Default backstory
            'backstory_i18n': {"en": base_backstory, "ru": base_backstory}, # Default i18n backstory
            # Add other i18n fields with defaults
            'role_i18n': {"en": "", "ru": ""},
            'personality_i18n': {"en": "", "ru": ""},
            'motivation_i18n': {"en": "", "ru": ""},
            'dialogue_hints_i18n': {"en": "", "ru": ""},
            'visual_description_i18n': {"en": "", "ru": ""},
        }

        # 1. Apply RuleEngine generated stats (if no AI stats and no archetype stats)
        rule_engine = self._rule_engine or kwargs.get('rule_engine')
        # L332: RuleEngine has generate_initial_character_stats, not generate_initial_npc_stats.
        if rule_engine and hasattr(rule_engine, 'generate_initial_character_stats') and \
           not (ai_generated_data and 'stats' in ai_generated_data) and \
           not (archetype_data_loaded and 'stats' in archetype_data_loaded): # Only if no AI/Archetype stats
            try:
                generated_stats = rule_engine.generate_initial_character_stats() # Synchronous call
                if isinstance(generated_stats, dict):
                    final_data['stats'].update(generated_stats)
                    print(f"NpcManager: Applied RuleEngine initial stats for NPC concept '{archetype_id_to_load}'.")
            except Exception as e:
                print(f"NpcManager: Error generating NPC stats via RuleEngine: {e}")
                traceback.print_exc()

        # 2. Layer Archetype Data (if loaded)
        if archetype_data_loaded:
            final_data['name'] = archetype_data_loaded.get('name', final_data['name'])
            if isinstance(archetype_data_loaded.get('name_i18n'), dict):
                 final_data['name_i18n'].update(archetype_data_loaded['name_i18n'])
            elif 'name' in archetype_data_loaded: # If only plain name, update i18n from it
                 final_data['name_i18n'] = {lang: archetype_data_loaded['name'] for lang in final_data['name_i18n']}

            if isinstance(archetype_data_loaded.get('stats'), dict):
                final_data['stats'].update(archetype_data_loaded['stats'])
            final_data['inventory'] = archetype_data_loaded.get('inventory', final_data['inventory'])
            final_data['archetype'] = archetype_data_loaded.get('archetype', final_data['archetype'])
            final_data['traits'] = archetype_data_loaded.get('traits', final_data['traits'])
            final_data['desires'] = archetype_data_loaded.get('desires', final_data['desires'])
            final_data['motives'] = archetype_data_loaded.get('motives', final_data['motives'])
            final_data['backstory'] = archetype_data_loaded.get('backstory', final_data['backstory'])
            if isinstance(archetype_data_loaded.get('backstory_i18n'), dict):
                 final_data['backstory_i18n'].update(archetype_data_loaded['backstory_i18n'])
            elif 'backstory' in archetype_data_loaded:
                 final_data['backstory_i18n'] = {lang: archetype_data_loaded['backstory'] for lang in final_data['backstory_i18n']}

            # Update other i18n fields from archetype if present
            for key in ['role_i18n', 'personality_i18n', 'motivation_i18n', 'dialogue_hints_i18n', 'visual_description_i18n']:
                if isinstance(archetype_data_loaded.get(key), dict):
                    final_data[key].update(archetype_data_loaded[key])


        # 3. Layer AI Generated Data (if available)
        if ai_generated_data:
            final_data['name'] = ai_generated_data.get('name', final_data['name'])
            if isinstance(ai_generated_data.get('name_i18n'), dict):
                 final_data['name_i18n'].update(ai_generated_data['name_i18n'])
            elif 'name' in ai_generated_data:
                 final_data['name_i18n'] = {lang: ai_generated_data['name'] for lang in final_data['name_i18n']}
                 if final_data['name'] and not final_data['name_i18n'].get('en'): # Ensure 'en' is set if possible
                     final_data['name_i18n']['en'] = final_data['name']


            if isinstance(ai_generated_data.get('stats'), dict):
                final_data['stats'].update(ai_generated_data['stats'])
            final_data['inventory'] = ai_generated_data.get('inventory', final_data['inventory'])
            final_data['archetype'] = ai_generated_data.get('archetype', final_data['archetype'])
            final_data['traits'] = ai_generated_data.get('traits', final_data['traits'])
            final_data['desires'] = ai_generated_data.get('desires', final_data['desires'])
            final_data['motives'] = ai_generated_data.get('motives', final_data['motives'])
            final_data['backstory'] = ai_generated_data.get('backstory', final_data['backstory'])
            if isinstance(ai_generated_data.get('backstory_i18n'), dict):
                 final_data['backstory_i18n'].update(ai_generated_data['backstory_i18n'])
            elif 'backstory' in ai_generated_data:
                 final_data['backstory_i18n'] = {lang: ai_generated_data['backstory'] for lang in final_data['backstory_i18n']}

            # Update other i18n fields from AI if present
            for key in ['description_i18n', 'visual_description_i18n', 'personality_i18n', 'role_i18n',
                        'motivation_i18n', 'dialogue_hints_i18n', 'roleplaying_notes_i18n',
                        'knowledge_i18n', 'npc_goals_i18n', 'relationships_i18n', 'speech_patterns_i18n']:
                if isinstance(ai_generated_data.get(key), dict):
                    final_data.setdefault(key, {}).update(ai_generated_data[key])


        # 4. Layer kwargs (specific overrides)
        if 'name' in kwargs:
            final_data['name'] = kwargs['name']
            # Update i18n name from plain name kwarg if no specific i18n kwarg
            if 'name_i18n' not in kwargs:
                 final_data['name_i18n'] = {lang: kwargs['name'] for lang in final_data['name_i18n']}
        if isinstance(kwargs.get('name_i18n'), dict):
            final_data['name_i18n'].update(kwargs['name_i18n'])

        if 'stats' in kwargs and isinstance(kwargs['stats'], dict): # Correctly apply stats from kwargs
            final_data['stats'].update(kwargs['stats'])
        if 'inventory' in kwargs:
            final_data['inventory'] = kwargs['inventory']
        if 'archetype' in kwargs:
            final_data['archetype'] = kwargs['archetype']
        if 'traits' in kwargs:
            final_data['traits'] = kwargs['traits']
        if 'desires' in kwargs:
            final_data['desires'] = kwargs['desires']
        if 'motives' in kwargs:
            final_data['motives'] = kwargs['motives']
        if 'backstory' in kwargs:
            final_data['backstory'] = kwargs['backstory']
            if 'backstory_i18n' not in kwargs: # Update i18n from plain backstory kwarg
                 final_data['backstory_i18n'] = {lang: kwargs['backstory'] for lang in final_data['backstory_i18n']}
        if isinstance(kwargs.get('backstory_i18n'), dict):
            final_data['backstory_i18n'].update(kwargs['backstory_i18n'])

        # Update other i18n fields from kwargs
        for key in ['role_i18n', 'personality_i18n', 'motivation_i18n', 'dialogue_hints_i18n', 'visual_description_i18n']:
            if isinstance(kwargs.get(key), dict):
                final_data[key].update(kwargs[key])


        # Ensure stats has max_health for health calculation
        if 'max_health' not in final_data['stats'] or not isinstance(final_data['stats']['max_health'], (int, float)):
             final_data['stats']['max_health'] = 50.0

        try:
            # Prepare the full data dictionary for NPC.from_dict
            data_for_npc_object: Dict[str, Any] = {
                'id': npc_id,
                'template_id': archetype_id_to_load,
                'guild_id': guild_id_str,
                'location_id': location_id, # from method args
                'current_action': None,
                'action_queue': [],
                'party_id': None,
                'state_variables': kwargs.get('state_variables', {}), # from kwargs or default
                'health': float(final_data['stats'].get('max_health', 50.0)), # Calculated from final_data stats
                'max_health': float(final_data['stats'].get('max_health', 50.0)), # Calculated from final_data stats
                'is_alive': True, # New NPCs are alive
                'status_effects': [],
                'is_temporary': bool(kwargs.get('is_temporary', False)), # from kwargs or default
            }
            # Add all fields from final_data (name, name_i18n, stats, inventory, archetype, traits, etc.)
            # This ensures all processed and layered data is included.
            data_for_npc_object.update(final_data)

            # Ensure all i18n fields from final_data are in data_for_npc_object for NPC.from_dict
            # This is implicitly handled by data_for_npc_object.update(final_data) if final_data contains them.

            npc = NPC.from_dict(data_for_npc_object)

            # If AI provided i18n fields and they are in final_data, they will be passed to NPC.from_dict
            # Example: if 'name_i18n' is in final_data, it's passed.
            # NPC.from_dict needs to be able to handle these i18n fields.

            npc = NPC.from_dict(data_for_npc_object)

            # ИСПРАВЛЕНИЕ: Добавляем в per-guild кеш
            self._npcs.setdefault(guild_id_str, {})[npc_id] = npc

            # ИСПРАВЛЕНИЕ: Помечаем NPC dirty (per-guild)
            self.mark_npc_dirty(guild_id_str, npc_id)

            print(f"NpcManager: NPC {npc_id} ('{getattr(npc, 'name', 'N/A')}') created from campaign/default for guild {guild_id_str}.")
            return npc_id # Return npc_id for non-AI path

        except Exception as e:
            print(f"NpcManager: Error creating NPC from template (non-AI path) '{npc_template_id}' for guild {guild_id_str}: {e}")
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
            # L537: remove_status_effects_by_target does not exist. Iterate and remove.
            if sm and hasattr(sm, 'remove_status_effect') and hasattr(npc, 'status_effects') and isinstance(npc.status_effects, list):
                # npc.status_effects should be a list of status_effect_ids if populated by StatusManager
                status_ids_to_remove = list(npc.status_effects) # Iterate over a copy
                if status_ids_to_remove:
                    print(f"NpcManager: Removing {len(status_ids_to_remove)} status effects from NPC {npc_id} in guild {guild_id_str}.")
                    for status_id_to_remove_from_list in status_ids_to_remove:
                        try:
                            await sm.remove_status_effect(status_effect_id=str(status_id_to_remove_from_list), guild_id=guild_id_str, **cleanup_context)
                        except Exception as e_stat_rem:
                             print(f"NpcManager: Error removing status effect {status_id_to_remove_from_list} during NPC cleanup: {e_stat_rem}")
                             traceback.print_exc()
            elif sm:
                 print(f"NpcManager: StatusManager available but NPC {npc_id} has no status_effects list or it's invalid, or remove_status_effect method missing.")


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

    async def generate_npc_details_from_ai(self, guild_id: str, npc_id_concept: str, player_level_for_scaling: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Uses MultilingualPromptGenerator and OpenAIService to generate detailed
        NPC profile data based on an ID or concept.

        Args:
            guild_id: The ID of the guild.
            npc_id_concept: An ID of an existing NPC to flesh out, or a string concept for a new NPC.
            player_level_for_scaling: Optional player level to guide content difficulty/scale.

        Returns:
            A dictionary containing the structured, multilingual NPC data from the AI,
            or None if generation fails.
        """
        if not self._multilingual_prompt_generator:
            print("NpcManager ERROR: MultilingualPromptGenerator is not available.")
            return None
        if not self._openai_service:
            print("NpcManager ERROR: OpenAIService is not available.")
            return None

        print(f"NpcManager: Generating AI details for NPC concept '{npc_id_concept}' in guild {guild_id}.")

        # 1. Get the structured prompt from MultilingualPromptGenerator
        prompt_messages = await self._multilingual_prompt_generator.generate_npc_profile_prompt(
            guild_id=guild_id,
            npc_id_idea=npc_id_concept,
            player_level_override=player_level_for_scaling
        )

        system_prompt = prompt_messages["system"]
        user_prompt = prompt_messages["user"]

        # 2. Call OpenAIService
        npc_generation_settings = self._settings.get("npc_generation_ai_settings", {})
        max_tokens = npc_generation_settings.get("max_tokens", 2000)
        temperature = npc_generation_settings.get("temperature", 0.6)

        generated_data = await self._openai_service.generate_structured_multilingual_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )

        if not generated_data or "error" in generated_data or not isinstance(generated_data.get("json_string"), str):
            error_detail = generated_data.get("error") if generated_data else "Unknown error or invalid format from AI service"
            raw_text = generated_data.get("raw_text", "") if generated_data else ""
            print(f"NpcManager ERROR: Failed to generate AI details for NPC '{npc_id_concept}'. Error: {error_detail}")
            if raw_text:
                print(f"NpcManager: Raw response from AI was: {raw_text[:500]}...")
            return None

        generated_content_str = generated_data["json_string"]

        if not self._ai_validator:
            print(f"NpcManager WARNING: AIResponseValidator not available for guild {guild_id}. Returning raw AI data for NPC '{npc_id_concept}'. This may be unsafe.")
            # Depending on policy, either return raw (less safe) or None
            # For now, let's assume raw JSON string is what this method used to return conceptually.
            # However, the goal is to return a Dict[str, Any] for NPC.from_dict().
            # So, if no validator, we might try to parse it, but it's risky.
            # Let's return None if validator is critical path.
            print("NpcManager ERROR: AIResponseValidator is critical but not available. Cannot proceed with NPC generation.")
            return None

        # For single_npc generation, existing IDs are usually not needed unless the NPC links to pre-existing entities.
        # These are placeholders for now.
        validation_result = await self._ai_validator.validate_ai_response(
            ai_json_string=generated_content_str,
            expected_structure="single_npc",
            existing_npc_ids=set(),
            existing_quest_ids=set(),
            existing_item_template_ids=set()
        )

        if validation_result.get('global_errors'):
            print(f"NpcManager ERROR: AI content validation failed with global errors for NPC '{npc_id_concept}': {validation_result['global_errors']}")
            return None

        if not validation_result.get('entities'):
            print(f"NpcManager ERROR: AI content validation produced no entities for NPC '{npc_id_concept}'.")
            return None

        npc_validation_details = validation_result['entities'][0]

        if npc_validation_details.get('errors'):
            print(f"NpcManager WARNING: Validation errors for NPC '{npc_id_concept}': {npc_validation_details['errors']}")

        if npc_validation_details.get('notifications'):
            print(f"NpcManager INFO: Validation notifications for NPC '{npc_id_concept}': {npc_validation_details['notifications']}")

        if npc_validation_details.get('requires_moderation'):
            print(f"NpcManager CRITICAL: NPC data for '{npc_id_concept}' requires moderation. Raw data: {generated_content_str[:500]}...")
            # In a full system, this data might be saved to a moderation queue.
            # For now, returning None to prevent use of unmoderated problematic data.
            return None
            # Alternative: return {"requires_moderation": True, "data": npc_validation_details.get('validated_data')}

        overall_status = validation_result.get("overall_status")
        if overall_status == "success" or overall_status == "success_with_autocorrections":
            print(f"NpcManager: Successfully validated AI details for NPC '{npc_id_concept}'. Status: {overall_status}")
            return npc_validation_details.get('validated_data')
        else:
            print(f"NpcManager ERROR: Unhandled validation status '{overall_status}' for NPC '{npc_id_concept}'.")
            return None

    async def save_state(self, guild_id: str, **kwargs: Any) -> None:
        """Сохраняет все измененные или удаленные NPC для определенной гильдии."""
        guild_id_str = str(guild_id)
        # print(f"NpcManager: Saving NPC state for guild {guild_id_str}...") # Can be noisy

        if self._db_service is None or self._db_service.adapter is None: # Changed
            print(f"NpcManager: Warning: Cannot save NPC state for guild {guild_id_str}, DB service or adapter missing.")
            return

        dirty_npc_ids_for_guild = self._dirty_npcs.get(guild_id_str, set()).copy()
        deleted_npc_ids_for_guild = self._deleted_npc_ids.get(guild_id_str, set()).copy()

        if not dirty_npc_ids_for_guild and not deleted_npc_ids_for_guild:
            return

        print(f"NpcManager: Saving {len(dirty_npc_ids_for_guild)} dirty, {len(deleted_npc_ids_for_guild)} deleted NPCs for guild {guild_id_str}...")

        # Handle deletions first
        if deleted_npc_ids_for_guild:
            ids_to_delete_list = list(deleted_npc_ids_for_guild)
            placeholders = ','.join(['?'] * len(ids_to_delete_list))

            # Attempt to delete from both tables, as we don't know the source table just from ID
            # Or, if NPC objects are still in cache when marked deleted, check 'is_ai_generated' then.
            # For simplicity now, try deleting from both if ID matches.
            # This assumes IDs are unique across npcs and generated_npcs, or it's fine if one of the DELETEs affects 0 rows.
            if ids_to_delete_list: # Check if list is not empty
                pg_placeholders = ','.join([f'${i+2}' for i in range(len(ids_to_delete_list))]) # $2, $3, ...
                sql_delete_npcs = f"DELETE FROM npcs WHERE guild_id = $1 AND id IN ({pg_placeholders})" # Changed
                sql_delete_generated_npcs = f"DELETE FROM generated_npcs WHERE guild_id = $1 AND id IN ({pg_placeholders})" # Changed

                try:
                    await self._db_service.adapter.execute(sql_delete_npcs, (guild_id_str, *ids_to_delete_list)) # Changed
                    await self._db_service.adapter.execute(sql_delete_generated_npcs, (guild_id_str, *ids_to_delete_list)) # Changed
                    print(f"NpcManager: Attempted deletion for {len(ids_to_delete_list)} IDs from 'npcs' and 'generated_npcs' tables for guild {guild_id_str}.")
                    self._deleted_npc_ids.pop(guild_id_str, None) # Clear after attempting deletion
                except Exception as e:
                    print(f"NpcManager: Error deleting NPCs for guild {guild_id_str}: {e}")
                    traceback.print_exc() # Keep IDs in _deleted_npc_ids to retry next time
            else: # If deleted_npc_ids_for_guild was empty for this guild, or if ids_to_delete_list was empty
                self._deleted_npc_ids.pop(guild_id_str, None)

        # Handle dirty NPCs
        guild_npcs_cache = self._npcs.get(guild_id_str, {})
        if dirty_npc_ids_for_guild:
            for npc_id in list(dirty_npc_ids_for_guild): # Iterate copy as save_npc might modify the set
                npc = guild_npcs_cache.get(npc_id)
                if npc:
                    # save_npc now determines the target table internally
                    await self.save_npc(npc, guild_id_str)
                else:
                    # NPC was in dirty set but not in cache, means it was deleted and then un-dirtied.
                    # Or some other logic error. For safety, remove from dirty set.
                    self._dirty_npcs.get(guild_id_str, set()).discard(npc_id)


        # Clean up empty sets from dictionaries to save memory
        if not self._dirty_npcs.get(guild_id_str):
            self._dirty_npcs.pop(guild_id_str, None)
        if not self._deleted_npc_ids.get(guild_id_str): # Should have been popped if successful
            self._deleted_npc_ids.pop(guild_id_str, None)

        print(f"NpcManager: Save state complete for guild {guild_id_str}.")

    # ИСПРАВЛЕНИЕ: load_state должен принимать guild_id
    async def load_state(self, guild_id: str, **kwargs: Any) -> None:
        """Загружает NPC для определенной гильдии из базы данных в кеш."""
        guild_id_str = str(guild_id)
        
        campaign_data: Optional[Dict[str, Any]] = kwargs.get('campaign_data')
        # ... (campaign data logging remains the same) ...
        if campaign_data and isinstance(campaign_data.get("npc_archetypes"), list):
            npc_archetypes_data = campaign_data["npc_archetypes"]
            loaded_archetype_count = len(npc_archetypes_data)
            print(f"NpcManager (load_state): Received {loaded_archetype_count} NPC archetypes from campaign_data for guild {guild_id_str}.")
            if loaded_archetype_count > 0:
                print("NpcManager (load_state): Example NPC archetypes received:")
                for i, archetype_data in enumerate(npc_archetypes_data):
                    if i < 3:
                        print(f"  - ID: {archetype_data.get('id', 'N/A')}, Name: {archetype_data.get('name', 'N/A')}, Archetype: {archetype_data.get('archetype', 'N/A')}")
                    else:
                        break
                if loaded_archetype_count > 3:
                    print(f"  ... and {loaded_archetype_count - 3} more.")
        else:
            print(f"NpcManager (load_state): No NPC archetypes found in campaign_data for guild {guild_id_str} or format is incorrect.")

        print(f"NpcManager: Loading NPC instances for guild {guild_id_str} from DB...")

        if self._db_service is None or self._db_service.adapter is None: # Changed
            print(f"NpcManager: Warning: Cannot load NPC instances for guild {guild_id_str}, DB service or adapter missing.")
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
            # ВЫПОЛНЯЕМ fetchall С ФИЛЬТРОМ по guild_id for 'npcs' table
            # Ensure all columns as per migration v16 are fetched (name_i18n, description_i18n, backstory_i18n, persona_i18n)
            sql_npcs = '''
            SELECT id, template_id, name_i18n, description_i18n, backstory_i18n, persona_i18n,
                   guild_id, location_id, stats, inventory, current_action, action_queue, party_id,
                   state_variables, health, max_health, is_alive, status_effects, is_temporary, archetype,
                   traits, desires, motives
            FROM npcs WHERE guild_id = $1
            ''' # 23 columns for 'npcs' table, changed placeholder
            rows = await self._db_service.adapter.fetchall(sql_npcs, (guild_id_str,)) # Changed
            print(f"NpcManager: Found {len(rows)} NPCs in 'npcs' table for guild {guild_id_str}.")

            # TODO: Add loading logic for 'generated_npcs' table if NpcManager should handle them.
            # This would involve a separate SQL query and potentially merging or differentiating these NPCs.
            # For now, this method only loads from the 'npcs' table.

        except Exception as e:
            print(f"NpcManager: ❌ CRITICAL ERROR executing DB fetchall for NPCs for guild {guild_id_str}: {e}")
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
                     continue

                npc_id = str(npc_id_raw)
                loaded_guild_id = str(loaded_guild_id_raw)

                if loaded_guild_id != guild_id_str:
                    print(f"NpcManager: Warning: Mismatch guild_id for NPC {npc_id}: Expected {guild_id_str}, got {loaded_guild_id}. Skipping.")
                    continue

                # --- Parse all fields from 'npcs' table row ---
                # i18n fields (already named *_i18n in SELECT, should be JSON strings from DB)
                for field_name in ['name_i18n', 'description_i18n', 'backstory_i18n', 'persona_i18n']:
                    try:
                        json_str = data.get(field_name)
                        data[field_name] = json.loads(json_str or '{}') if isinstance(json_str, (str, bytes)) else (json_str if isinstance(json_str, dict) else {})
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"NpcManager: Warning: Failed to parse {field_name} for NPC {npc_id}. Data: '{data.get(field_name)}'. Error: {e}. Defaulting to empty dict.")
                        data[field_name] = {}
                
                # Derive plain 'name' for model
                selected_lang = data.get('selected_language', 'en') # Assuming NPC might have a lang or use guild default
                data['name'] = data['name_i18n'].get(selected_lang, list(data['name_i18n'].values())[0] if data['name_i18n'] else npc_id)


                # Standard JSON fields
                for field_name, default_val_str, default_type in [
                    ('stats', '{}', dict), ('inventory', '[]', list),
                    ('action_queue', '[]', list), ('state_variables', '{}', dict),
                    ('status_effects', '[]', list), ('traits', '[]', list),
                    ('desires', '[]', list), ('motives', '[]', list)
                ]:
                    try:
                        json_str = data.get(field_name)
                        data[field_name] = json.loads(json_str or default_val_str) if isinstance(json_str, (str, bytes)) else (json_str if isinstance(json_str, default_type) else (default_type()))
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"NpcManager: Warning: Failed to parse {field_name} for NPC {npc_id}. Data: '{data.get(field_name)}'. Error: {e}. Defaulting.")
                        data[field_name] = default_type()

                # Current action can be None
                try:
                    current_action_json = data.get('current_action')
                    data['current_action'] = json.loads(current_action_json) if isinstance(current_action_json, (str, bytes)) else (current_action_json if isinstance(current_action_json, dict) else None)
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"NpcManager: Warning: Failed to parse current_action for NPC {npc_id}. Data: '{data.get('current_action')}'. Error: {e}. Defaulting to None.")
                    data['current_action'] = None

                # Numeric and boolean fields
                data['health'] = float(data.get('health', 0.0))
                data['max_health'] = float(data.get('max_health', 0.0))
                data['is_alive'] = bool(data.get('is_alive', True)) # DB stores 0/1
                data['is_temporary'] = bool(data.get('is_temporary', False)) # DB stores 0/1
                data['archetype'] = data.get('archetype', "commoner")

                # Ensure required object IDs are strings or None
                data['id'] = npc_id # Already str
                data['guild_id'] = loaded_guild_id
                data['template_id'] = str(data['template_id']) if data.get('template_id') is not None else None
                data['location_id'] = str(data['location_id']) if data.get('location_id') is not None else None
                data['party_id'] = str(data['party_id']) if data.get('party_id') is not None else None


                # Create NPC object
                npc = NPC.from_dict(data) # Requires NPC.from_dict method
                npc.is_ai_generated = False # Mark as NOT AI-generated

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

        # --- Load from 'generated_npcs' table ---
        rows_generated = []
        try:
            # Updated query for new generated_npcs schema
            sql_generated_npcs = '''
            SELECT id, placeholder
            FROM generated_npcs
            ''' # Removed WHERE guild_id = $1 as column is gone
            rows_generated = await self._db_service.adapter.fetchall(sql_generated_npcs) # No params needed now
            print(f"NpcManager: Found {len(rows_generated)} NPCs in 'generated_npcs' table (loaded all).") # Updated log
        except Exception as e:
            print(f"NpcManager: ❌ CRITICAL ERROR executing DB fetchall for 'generated_npcs' table: {e}") # Updated log
            import traceback # Ensure traceback is imported
            traceback.print_exc()
            # Continue even if this part fails, 'npcs' might have loaded.

        loaded_generated_count = 0
        selected_lang = "en" # Default language for deriving plain 'name'
        # Attempt to get guild default language if available (e.g. from settings in kwargs)
        # This part is conceptual as settings access might be structured differently.
        if 'settings' in kwargs and isinstance(kwargs['settings'], dict):
            selected_lang = kwargs['settings'].get('guilds', {}).get(guild_id_str, {}).get('default_language', selected_lang)


        for row_gen in rows_generated:
            data_gen_db = dict(row_gen) # Raw data from DB
            model_data_gen = {} # Data to be passed to NPC.from_dict()
            try:
                npc_id_gen_raw = data_gen_db.get('id')
                # loaded_guild_id_gen_raw = data_gen_db.get('guild_id') # guild_id no longer in generated_npcs

                if npc_id_gen_raw is None: # Only check npc_id now
                    print(f"NpcManager: Warning: Skipping generated_npcs row with missing ID. Data: {data_gen_db}")
                    continue

                npc_id_gen = str(npc_id_gen_raw)
                # Since guild_id is removed from generated_npcs, we cannot filter by it here.
                # All generated_npcs are loaded. If they need to be guild-specific,
                # this needs a different design (e.g., placeholder stores guild_id or a linking table).

                if npc_id_gen in guild_npcs_cache: # Check against already loaded standard NPCs
                    print(f"NpcManager: Warning: NPC ID {npc_id_gen} from 'generated_npcs' already loaded from 'npcs' table. Skipping duplicate from 'generated_npcs'.")
                    continue

                model_data_gen['id'] = npc_id_gen
                # model_data_gen['guild_id'] = guild_id_str # Cannot set guild_id from this table anymore

                # All other i18n and JSON fields are gone from generated_npcs.
                # We only have 'id' and 'placeholder'.
                # The NPC object will be very minimal.
                placeholder_text = data_gen_db.get('placeholder', f"Generated NPC {npc_id_gen}")
                model_data_gen['name'] = placeholder_text # Use placeholder as name
                model_data_gen['name_i18n'] = {"en": placeholder_text, "ru": placeholder_text}

                # Fill with defaults for other required NPC fields
                model_data_gen['stats'] = {"max_health": 10, "strength": 5} # Minimal stats
                model_data_gen['inventory'] = []
                model_data_gen['archetype'] = "generated_placeholder"
                model_data_gen['description_i18n'] = {"en": placeholder_text}
                model_data_gen['persona_i18n'] = {}
                model_data_gen['backstory_i18n'] = {}
                model_data_gen['traits'] = []
                model_data_gen['desires'] = []
                model_data_gen['motives'] = []
                model_data_gen['health'] = float(model_data_gen['stats'].get('max_health', 10.0))
                model_data_gen['max_health'] = float(model_data_gen['stats'].get('max_health', 10.0))
                model_data_gen['is_alive'] = model_data_gen['health'] > 0
                model_data_gen['status_effects'] = []
                model_data_gen['action_queue'] = []
                model_data_gen['state_variables'] = {}
                model_data_gen['is_temporary'] = True # Generated NPCs might be temporary
                model_data_gen['template_id'] = "generated_placeholder_template"
                # Ensure guild_id is set for the NPC object, even if not from this table.
                # This is problematic if generated NPCs are meant to be global.
                # For now, assign to the current guild to satisfy NPC model if it requires guild_id.
                model_data_gen['guild_id'] = guild_id_str


                # Fill in other NPC model fields with defaults if not provided by generated_npcs schema
                model_data_gen.setdefault('description_i18n', model_data_gen.get('personality_i18n', {})) # Use personality if description is missing
                model_data_gen.setdefault('persona_i18n', model_data_gen.get('personality_i18n', {}))
                model_data_gen.setdefault('traits', [])
                model_data_gen.setdefault('desires', [])
                model_data_gen.setdefault('motives', []) # Motives from motivation_i18n if needed
                model_data_gen.setdefault('health', float(model_data_gen['stats'].get('max_health', 50.0)))
                model_data_gen.setdefault('max_health', float(model_data_gen['stats'].get('max_health', 50.0)))
                model_data_gen.setdefault('is_alive', model_data_gen['health'] > 0)
                model_data_gen.setdefault('status_effects', [])
                model_data_gen.setdefault('action_queue', [])
                model_data_gen.setdefault('state_variables', {})
                model_data_gen.setdefault('faction_affiliations', model_data_gen.get('faction_affiliations_data',[]))
                model_data_gen.setdefault('relationships', model_data_gen.get('relationships_data',{}))


                npc_gen = NPC.from_dict(model_data_gen)
                setattr(npc_gen, 'is_ai_generated', True) # Mark as generated

                guild_npcs_cache[npc_gen.id] = npc_gen
                if getattr(npc_gen, 'current_action', None) is not None or getattr(npc_gen, 'action_queue', []):
                    guild_active_action_cache.add(npc_gen.id)
                loaded_generated_count += 1

            except Exception as e:
                print(f"NpcManager: Error loading generated NPC {data_gen_db.get('id', 'N/A')} for guild {guild_id_str}: {e}")
                traceback.print_exc()

        total_loaded = loaded_count + loaded_generated_count
        print(f"NpcManager: Successfully loaded {total_loaded} NPCs ({loaded_count} standard, {loaded_generated_count} generated) into cache for guild {guild_id_str}.")
        if total_loaded < (len(rows) + len(rows_generated)): # Compare with sum of rows from both queries
             print(f"NpcManager: Note: Failed to load some NPCs for guild {guild_id_str} due to errors.")


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

    async def save_npc(self, npc: "NPC", guild_id: str) -> bool:
        """
        Saves a single NPC to the database using an UPSERT operation.
        """
        if self._db_service is None or self._db_service.adapter is None: # Changed
            print(f"NpcManager: Error: DB service or adapter missing for guild {guild_id}. Cannot save NPC {getattr(npc, 'id', 'N/A')}.")
            return False

        guild_id_str = str(guild_id)
        npc_id = getattr(npc, 'id', None)

        if not npc_id:
            print(f"NpcManager: Error: NPC object is missing an 'id'. Cannot save.")
            return False

        # Ensure the NPC's internal guild_id matches the provided guild_id
        # The NPC object from NPC.from_dict in create_npc already gets guild_id.
        npc_internal_guild_id = getattr(npc, 'guild_id', None)
        if str(npc_internal_guild_id) != guild_id_str:
            print(f"NpcManager: Error: NPC {npc_id} guild_id ({npc_internal_guild_id}) does not match provided guild_id ({guild_id_str}).")
            return False

        try:
            npc_data = npc.to_dict() # Get all data from the NPC model instance

            # Helper functions for ensuring correct types for JSON serialization
            def _ensure_dict(val, default_key="en"):
                if isinstance(val, dict): return val
                if val is None: return {} # Default to empty dict if None
                return {default_key: str(val)} # Convert simple values to basic i18n

            def _ensure_list(val):
                if isinstance(val, list): return val
                if val is None: return [] # Default to empty list if None
                return [val] # Wrap single non-list value in a list

            target_table: str
            if getattr(npc, 'is_ai_generated', False): # Check the flag on the NPC object
                target_table = 'generated_npcs'
            else:
                target_table = 'npcs'

            if target_table == 'generated_npcs':
                # generated_npcs table now only has id and placeholder
                db_params = (
                    str(npc_id), # id
                    # Use English name as placeholder, or a default if not available
                    npc_data.get('name_i18n', {}).get('en', f"Generated NPC {str(npc_id)[:8]}")
                )
                upsert_sql = """
                INSERT INTO generated_npcs (id, placeholder)
                VALUES ($1, $2)
                ON CONFLICT (id) DO UPDATE SET
                    placeholder = EXCLUDED.placeholder
                """ # PostgreSQL UPSERT for generated_npcs (simplified)
            else: # target_table is 'npcs'
                db_params = (
                    str(npc_id), # id
                    str(npc_data.get('template_id')) if npc_data.get('template_id') is not None else None, # template_id
                    json.dumps(_ensure_dict(npc_data.get('name_i18n', {}))), # name_i18n
                    json.dumps(_ensure_dict(npc_data.get('description_i18n', {}))), # description_i18n
                    json.dumps(_ensure_dict(npc_data.get('backstory_i18n', {}))), # backstory_i18n
                    json.dumps(_ensure_dict(npc_data.get('persona_i18n', {}))), # persona_i18n
                    guild_id_str, # guild_id
                    str(npc_data.get('location_id')) if npc_data.get('location_id') is not None else None, # location_id
                    json.dumps(_ensure_dict(npc_data.get('stats', {}), "strength")), # stats (JSON)
                    json.dumps(_ensure_list(npc_data.get('inventory', []))), # inventory (JSON, simple list of IDs)
                    json.dumps(npc_data.get('current_action')) if npc_data.get('current_action') is not None else None, # current_action (JSON or NULL)
                    json.dumps(_ensure_list(npc_data.get('action_queue', []))), # action_queue (JSON)
                    str(npc_data.get('party_id')) if npc_data.get('party_id') is not None else None, # party_id
                    json.dumps(_ensure_dict(npc_data.get('state_variables', {}), "default_state_key")), # state_variables (JSON)
                    float(npc_data.get('health', 0.0)), # health
                    float(npc_data.get('max_health', 0.0)), # max_health
                    bool(npc_data.get('is_alive', False)), # is_alive (boolean)
                    json.dumps(_ensure_list(npc_data.get('status_effects', []))), # status_effects (JSON)
                    bool(npc_data.get('is_temporary', False)), # is_temporary (boolean)
                    npc_data.get('archetype', "commoner"), # archetype
                    json.dumps(_ensure_list(npc_data.get('traits', []))), # traits (JSON)
                    json.dumps(_ensure_list(npc_data.get('desires', []))), # desires (JSON)
                    json.dumps(_ensure_list(npc_data.get('motives', []))) # motives (JSON)
                )
                upsert_sql = """
                INSERT INTO npcs (
                    id, template_id, name_i18n, description_i18n, backstory_i18n, persona_i18n,
                    guild_id, location_id, stats, inventory, current_action, action_queue, party_id,
                    state_variables, health, max_health, is_alive, status_effects, is_temporary, archetype,
                    traits, desires, motives
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23)
                ON CONFLICT (id) DO UPDATE SET
                    template_id=EXCLUDED.template_id, name_i18n=EXCLUDED.name_i18n, description_i18n=EXCLUDED.description_i18n,
                    backstory_i18n=EXCLUDED.backstory_i18n, persona_i18n=EXCLUDED.persona_i18n, guild_id=EXCLUDED.guild_id,
                    location_id=EXCLUDED.location_id, stats=EXCLUDED.stats, inventory=EXCLUDED.inventory,
                    current_action=EXCLUDED.current_action, action_queue=EXCLUDED.action_queue, party_id=EXCLUDED.party_id,
                    state_variables=EXCLUDED.state_variables, health=EXCLUDED.health, max_health=EXCLUDED.max_health,
                    is_alive=EXCLUDED.is_alive, status_effects=EXCLUDED.status_effects, is_temporary=EXCLUDED.is_temporary,
                    archetype=EXCLUDED.archetype, traits=EXCLUDED.traits, desires=EXCLUDED.desires, motives=EXCLUDED.motives
                """ # PostgreSQL UPSERT for npcs

            await self._db_service.adapter.execute(upsert_sql, db_params) # Changed
            # print(f"NpcManager: Successfully saved NPC {npc_id} to table '{target_table}' for guild {guild_id_str}.") # Debug

            # If this NPC was marked as dirty, clean it from the dirty set for this guild
            if guild_id_str in self._dirty_npcs and npc_id in self._dirty_npcs[guild_id_str]:
                self._dirty_npcs[guild_id_str].discard(npc_id)
                if not self._dirty_npcs[guild_id_str]: # If set becomes empty
                    del self._dirty_npcs[guild_id_str]

            # Ensure the cached object is the one that was saved, if it's a different instance.
            # NpcManager's cache _npcs stores NPC objects directly.
            self._npcs.setdefault(guild_id_str, {})[npc_id] = npc

            return True

        except Exception as e:
            print(f"NpcManager: Error saving NPC {npc_id} for guild {guild_id_str}: {e}")
            import traceback
            print(traceback.format_exc())
            return False

    async def create_npc_from_moderated_data(self, guild_id: str, npc_data: Dict[str, Any], context: Dict[str, Any]) -> Optional[str]:
        """
        Creates a new NPC from already validated and approved moderated data.
        This method bypasses AI generation and direct validation steps.
        """
        guild_id_str = str(guild_id)
        print(f"NpcManager: Creating NPC from moderated data for guild {guild_id_str}...")

        if self._db_adapter is None:
            print(f"NpcManager: No DB adapter available for guild {guild_id_str}. Cannot create NPC from moderated data.")
            return None

        # Ensure npc_data has an ID, or assign a new one.
        # The moderated data should ideally retain any ID it was assigned during AI generation,
        # or the moderation request ID could even be used if it's unique and suitable.
        # For now, let's assume npc_data might or might not have 'id'.
        # If 'id' is missing or seems like a placeholder (e.g., from a template_id), generate a new one.
        npc_id = npc_data.get('id')
        if not npc_id or npc_id == npc_data.get('template_id'): # Basic check if ID might be a template ID
            npc_id = str(uuid.uuid4())
            print(f"NpcManager: Assigned new ID {npc_id} to NPC from moderated data.")

        # Ensure core fields are present and correctly typed from npc_data
        # The npc_data should be the dictionary that was originally validated.
        data_for_npc_object: Dict[str, Any] = {
            'id': npc_id,
            'guild_id': guild_id_str,
            'template_id': npc_data.get('template_id', npc_data.get('archetype')), # Fallback to archetype for template_id if needed
            'name': npc_data.get('name', f"NPC_{npc_id[:8]}"), # Default name if missing
            'location_id': npc_data.get('location_id'), # Can be None
            'stats': npc_data.get('stats', {"strength":5,"dexterity":5,"intelligence":5, "max_health": 50.0}),
            'inventory': npc_data.get('inventory', []),
            'current_action': None, # Fresh NPC starts with no action
            'action_queue': [],
            'party_id': None, # Fresh NPC not in a party
            'state_variables': npc_data.get('state_variables', {}),
            'health': float(npc_data.get('stats', {}).get('max_health', 50.0)), # Full health
            'max_health': float(npc_data.get('stats', {}).get('max_health', 50.0)),
            'is_alive': True,
            'status_effects': [], # Fresh NPC starts with no status effects
            'is_temporary': npc_data.get('is_temporary', False),
            'archetype': npc_data.get('archetype', "commoner"),
            'traits': npc_data.get('traits', []),
            'desires': npc_data.get('desires', []),
            'motives': npc_data.get('motives', []),
            'backstory': npc_data.get('backstory', ""),
            # Include i18n fields if they exist in npc_data
        }

        # Add i18n fields if present in npc_data to data_for_npc_object
        for i18n_key in ['name_i18n', 'description_i18n', 'visual_description_i18n',
                         'personality_description_i18n', 'roleplaying_notes_i18n',
                         'knowledge_i18n', 'npc_goals_i18n', 'relationships_i18n',
                         'speech_patterns_i18n', 'backstory_i18n']:
            if i18n_key in npc_data:
                data_for_npc_object[i18n_key] = npc_data[i18n_key]

        try:
            npc = NPC.from_dict(data_for_npc_object)
            # npc.is_ai_generated = False # Explicitly non-AI <- This was the original line for this path
            npc.is_ai_generated = True # This should be set based on whether AI data was used or if it's from moderation of AI content.

            # Add to cache
            self._npcs.setdefault(guild_id_str, {})[npc.id] = npc

            # Mark as dirty for persistence
            # This will use the regular save_npc or save_state logic which handles i18n fields
            self.mark_npc_dirty(guild_id_str, npc.id)

            # Explicitly save now to ensure it's in DB (save_state might be deferred)
            # The `save_npc` method handles i18n fields correctly if NPC model's to_dict provides them.
            # However, the current save_state in NpcManager uses a simpler direct mapping for npcs table.
            # For consistency, it's better if save_npc is robust for all fields including i18n,
            # or save_state is enhanced.
            # Given save_npc's structure, it should handle i18n if npc.to_dict() includes them.
            # Let's assume save_npc handles it. If not, save_state is the fallback.
            # For now, relying on mark_npc_dirty and the next save_state cycle.
            # To ensure it's saved immediately, we could call self.save_npc(npc, guild_id_str)
            # but that requires npc.to_dict() to be comprehensive.
            # The current save_state in NpcManager actually handles the full schema including i18n name/backstory.

            print(f"NpcManager: NPC {npc.id} ('{getattr(npc, 'name', 'N/A')}') created from moderated data for guild {guild_id_str} and marked dirty.")
            return npc.id

        except Exception as e:
            print(f"NpcManager: Error creating NPC from moderated data for guild {guild_id_str}: {e}")
            traceback.print_exc()
            return None

# --- Конец класса NpcManager ---

print("DEBUG: npc_manager.py module loaded.")
