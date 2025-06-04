# bot/game/models/npc.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

# Модель NPC не нуждается в импорте других менеджеров или сервисов.
# Она просто хранит данные.

@dataclass
class NPC:
    """
    Модель данных для неигрового персонажа (экземпляра NPC в мире).
    """
    # Уникальный идентификатор экземпляра NPC (UUID)
    id: str

    # ID шаблона NPC, на основе которого создан этот экземпляр
    template_id: str

    # Отображаемое имя NPC (может отличаться от имени в шаблоне для уникальных NPC)
    name: str # Derived from name_i18n by NpcManager or from_dict
    name_i18n: Dict[str, str] # e.g. {"en": "Guard", "ru": "Стражник"}
    description_i18n: Dict[str, str] = field(default_factory=lambda: {"en": "", "ru": ""})
    persona_i18n: Dict[str, str] = field(default_factory=lambda: {"en": "", "ru": ""}) # For npcs table

    # ID локации, где находится NPC, если он не в инвентаре/партии
    location_id: Optional[str]

    # ID сущности-владельца (например, ID события, если NPC создан событием)
    owner_id: Optional[str]

    # Флаг, указывающий, является ли NPC временным (например, для автоматической очистки после события)
    is_temporary: bool = False

    # Словарь характеристик (может быть скопирован из шаблона при создании, но может меняться)
    stats: Dict[str, Any] = field(default_factory=dict)

    # Инвентарь NPC (список Item IDs). Может быть пустым.
    inventory: List[str] = field(default_factory=list)

    # Текущее индивидуальное действие NPC (например, 'patrol', 'dialogue', 'attack'). Для AI.
    current_action: Optional[Dict[str, Any]] = None

    # Очередь индивидуальных действий NPC. Для AI.
    action_queue: List[Dict[str, Any]] = field(default_factory=list)

    # ID партии, если NPC состоит в партии (с игроками или другими NPC)
    party_id: Optional[str] = None

    # Словарь для любых дополнительных переменных состояния, специфичных для этого экземпляра NPC
    # Например, агрессия, отношение к игрокам, флаги квестов, прогресс диалога и т.п.
    state_variables: Dict[str, Any] = field(default_factory=dict)

    # Здоровье, максимальное здоровье, статус жизни (похоже на Character)
    health: float = 0.0
    max_health: float = 0.0
    is_alive: bool = True

    # Список ID активных статус-эффектов на этом NPC
    status_effects: List[str] = field(default_factory=list)

    # Новые поля для личности NPC
    archetype: str = "commoner"  # Например: "merchant", "guard", "hermit"
    traits: List[str] = field(default_factory=list)  # Личностные черты
    desires: List[str] = field(default_factory=list)  # Желания NPC
    motives: List[str] = field(default_factory=list)  # Мотивы NPC
    backstory_i18n: Dict[str, str] = field(default_factory=lambda: {"en": "", "ru": ""}) # For npcs table

    # New fields for AI generation (generated_npcs table):
    role_i18n: Dict[str, str] = field(default_factory=lambda: {"en": "", "ru": ""}) # generated_npcs
    personality_i18n: Dict[str, str] = field(default_factory=lambda: {"en": "", "ru": ""}) # generated_npcs (was also for npcs)
    motivation_i18n: Dict[str, str] = field(default_factory=lambda: {"en": "", "ru": ""}) # generated_npcs
    dialogue_hints_i18n: Dict[str, str] = field(default_factory=lambda: {"en": "", "ru": ""}) # generated_npcs

    # Data fields (often from *_json columns in generated_npcs)
    stats_data: Dict[str, Any] = field(default_factory=dict) # For generated_npcs.stats_json, complements existing 'stats'
    skills_data: List[Dict[str, Any]] = field(default_factory=list) # For generated_npcs.skills_json
    abilities_data: List[Dict[str, Any]] = field(default_factory=list) # For generated_npcs.abilities_json
    spells_data: List[Dict[str, Any]] = field(default_factory=list) # For generated_npcs.spells_json
    inventory_data: List[Dict[str, Any]] = field(default_factory=list) # For generated_npcs.inventory_json, complements existing 'inventory' (List[str])
    faction_affiliations_data: List[Dict[str, Any]] = field(default_factory=list) # For generated_npcs.faction_affiliations_json, complements existing 'faction_affiliations'
    relationships_data: Dict[str, Any] = field(default_factory=dict) # For generated_npcs.relationships_json, complements existing 'relationships'
    ai_prompt_context_data: Dict[str, Any] = field(default_factory=dict) # For generated_npcs.ai_prompt_context_json

    # Legacy/Simplified fields (can be derived or used for non-generated NPCs)
    known_abilities: List[str] = field(default_factory=list)
    known_spells: List[str] = field(default_factory=list)
    skills: Dict[str, int] = field(default_factory=dict)
    faction_affiliations: List[Dict[str, Any]] = field(default_factory=list) # Already existed, might be populated from faction_affiliations_data

    # Visual description
    visual_description_i18n: Dict[str, str] = field(default_factory=lambda: {"en": "", "ru": ""})

    # Guild ID
    guild_id: Optional[str] = None

    # Relationships with other entities
    relationships: Dict[str, Any] = field(default_factory=dict)

    # Optional: Store raw AI generated data if needed for debugging or regeneration
    # raw_ai_data: Optional[Dict[str, Any]] = None

    is_ai_generated: bool = False # Flag to distinguish NPC type for DB operations

    # TODO: Добавьте другие поля, если необходимо для вашей логики NPC
    # Например:
    # description: Optional[str] # Описание экземпляра NPC
    # ai_state: Optional[Dict[str, Any]] # Словарь для состояния AI


    def to_dict(self) -> Dict[str, Any]:
        """Преобразует объект NPC в словарь для сериализации."""
        # Используйте dataclasses.asdict() если не нужна спец. логика
        # from dataclasses import asdict
        # return asdict(self)

        data = {
            'id': self.id,
            'template_id': self.template_id,
            'name': self.name, # Derived name
            'name_i18n': self.name_i18n,
            'description_i18n': self.description_i18n,
            'persona_i18n': self.persona_i18n,
            'location_id': self.location_id,
            'owner_id': self.owner_id,
            'is_temporary': self.is_temporary,
            'stats': self.stats,
            'inventory': self.inventory,
            'current_action': self.current_action,
            'action_queue': self.action_queue,
            'party_id': self.party_id,
            'state_variables': self.state_variables,
            'health': self.health,
            'max_health': self.max_health,
            'is_alive': self.is_alive,
            'status_effects': self.status_effects,
            'archetype': self.archetype,
            'traits': self.traits,
            'desires': self.desires,
            'motives': self.motives,
            'backstory_i18n': self.backstory_i18n,

            # Add new fields
            'role_i18n': self.role_i18n,
            'personality_i18n': self.personality_i18n,
            'motivation_i18n': self.motivation_i18n,
            'dialogue_hints_i18n': self.dialogue_hints_i18n,

            # New structured data fields
            'stats_data': self.stats_data,
            'skills_data': self.skills_data,
            'abilities_data': self.abilities_data,
            'spells_data': self.spells_data,
            'inventory_data': self.inventory_data,
            'faction_affiliations_data': self.faction_affiliations_data,
            'relationships_data': self.relationships_data,
            'ai_prompt_context_data': self.ai_prompt_context_data,

            # Legacy/Simplified fields
            'known_abilities': self.known_abilities,
            'known_spells': self.known_spells,
            'skills': self.skills,
            'faction_affiliations': self.faction_affiliations, # Already existed

            'visual_description_i18n': self.visual_description_i18n,
            'guild_id': self.guild_id,
            'relationships': self.relationships, # Already existed
            'is_ai_generated': self.is_ai_generated,
            # 'ai_state': self.ai_state,
        }
        return data


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "NPC":
        """Создает объект NPC из словаря (например, при десериализации из БД)."""
        # Используем .get() с значениями по умолчанию для устойчивости к неполным данным.

        # Обязательные поля
        npc_id = data.get('id')
        if npc_id is None:
            raise ValueError("Missing 'id' key in data for NPC.from_dict")
        template_id = data.get('template_id')
        if template_id is None:
            raise ValueError("Missing 'template_id' key in data for NPC.from_dict")
        
        # Handle name_i18n and backward compatibility for 'name'
        name_i18n_val = data.get('name_i18n')
        plain_name_val = data.get('name')

        if name_i18n_val is None:
            if plain_name_val is None:
                raise ValueError("Missing 'name' or 'name_i18n' key in data for NPC.from_dict")
            name_i18n_val = {"en": plain_name_val, "ru": plain_name_val} # Default i18n from plain name

        if plain_name_val is None: # If only name_i18n is present, derive plain_name
            selected_lang = data.get('selected_language', 'en') # Assume a way to get preferred lang
            plain_name_val = name_i18n_val.get(selected_lang, list(name_i18n_val.values())[0] if name_i18n_val else npc_id)

        description_i18n_val = data.get('description_i18n')
        if description_i18n_val is None and 'description' in data: # Backward compatibility for plain description
            description_i18n_val = {"en": data.get('description',""), "ru": data.get('description',"")}
        elif description_i18n_val is None:
            description_i18n_val = {"en": "", "ru": ""}

        persona_i18n_val = data.get('persona_i18n')
        if persona_i18n_val is None and 'persona' in data: # Backward compatibility for plain persona
            persona_i18n_val = {"en": data.get('persona',""), "ru": data.get('persona',"")}
        elif persona_i18n_val is None:
            persona_i18n_val = {"en": "", "ru": ""}

        # Опциональные поля с значениями по умолчанию
        location_id = data.get('location_id')
        owner_id = data.get('owner_id') # None по умолчанию
        is_temporary = bool(data.get('is_temporary', False)) # Преобразуем 0/1 в bool

        stats = data.get('stats', {}) or {} # Убедимся, что это словарь
        inventory = data.get('inventory', []) or [] # Убедимся, что это список

        # current_action и action_queue могут быть None/пустыми списками
        current_action = data.get('current_action') # None по умолчанию (или {}?)
        # Убедимся, что action_queue - это список
        action_queue = data.get('action_queue', []) or []
        if not isinstance(action_queue, list):
             print(f"NPC Model: Warning: Loaded action_queue for NPC {npc_id} is not a list ({type(action_queue).__name__}). Initializing as empty list.")
             action_queue = [] # Исправляем некорректный тип

        party_id = data.get('party_id') # None по умолчанию
        state_variables = data.get('state_variables', {}) or {} # Убедимся, что это словарь

        # Здоровье, максимальное здоровье, жизнь - могут быть числами или 0/1
        health = float(data.get('health', 0.0)) # float по умолчанию
        max_health = float(data.get('max_health', 0.0)) # float по умолчанию
        is_alive = bool(data.get('is_alive', False)) # bool (0/1) по умолчанию

        status_effects = data.get('status_effects', []) or [] # Убедимся, что это список
        if not isinstance(status_effects, list):
             print(f"NPC Model: Warning: Loaded status_effects for NPC {npc_id} is not a list ({type(status_effects).__name__}). Initializing as empty list.")
             status_effects = [] # Исправляем некорректный тип


        # TODO: Обработайте другие поля, если добавили, используя .get()
        # description = data.get('description')
        # ai_state = data.get('ai_state', {}) or {}

        # Новые поля личности
        archetype = data.get('archetype', "commoner")
        traits = data.get('traits', []) or []
        desires = data.get('desires', []) or []
        motives = data.get('motives', []) or []
        
        # Handle backstory_i18n and backward compatibility for 'backstory'
        backstory_i18n = data.get('backstory_i18n')
        if backstory_i18n is None:
            backstory = data.get('backstory', "") # Default to empty string if old field is missing
            backstory_i18n = {"en": backstory}
        elif not isinstance(backstory_i18n, dict):
            backstory_i18n = {"en": str(backstory_i18n)}


        if not isinstance(traits, list): traits = []
        if not isinstance(desires, list): desires = []
        if not isinstance(motives, list): motives = []

        # Handle new fields (expecting parsed Python objects from manager)
        role_i18n = data.get('role_i18n', {"en": "", "ru": ""}) or {"en": "", "ru": ""}
        personality_i18n = data.get('personality_i18n', {"en": "", "ru": ""}) or {"en": "", "ru": ""}
        motivation_i18n = data.get('motivation_i18n', {"en": "", "ru": ""}) or {"en": "", "ru": ""}
        dialogue_hints_i18n = data.get('dialogue_hints_i18n', {"en": "", "ru": ""}) or {"en": "", "ru": ""}

        stats_data_val = data.get('stats_data', {}) or {}
        skills_data_val = data.get('skills_data', []) or []
        abilities_data_val = data.get('abilities_data', []) or []
        spells_data_val = data.get('spells_data', []) or []
        inventory_data_val = data.get('inventory_data', []) or []
        faction_affiliations_data_val = data.get('faction_affiliations_data', []) or []
        relationships_data_val = data.get('relationships_data', {}) or {}
        ai_prompt_context_data_val = data.get('ai_prompt_context_data', {}) or {}

        known_abilities = data.get('known_abilities', []) or []
        if not isinstance(known_abilities, list): known_abilities = []

        known_spells = data.get('known_spells', []) or []
        if not isinstance(known_spells, list): known_spells = []

        skills = data.get('skills', {}) or {} # Legacy skills
        if not isinstance(skills, dict): skills = {}

        # Legacy faction_affiliations, ensure it's a list
        faction_affiliations = data.get('faction_affiliations', []) or []
        if not isinstance(faction_affiliations, list): faction_affiliations = []

        visual_description_i18n = data.get('visual_description_i18n', {"en": "", "ru": ""}) or {"en": "", "ru": ""}

        guild_id_val = data.get('guild_id')
        relationships_val = data.get('relationships', {}) or {} # Legacy relationships
        is_ai_generated_val = bool(data.get('is_ai_generated', False))


        return NPC(
            id=npc_id,
            template_id=template_id,
            name=plain_name_val,
            name_i18n=name_i18n_val,
            description_i18n=description_i18n_val,
            persona_i18n=persona_i18n_val,
            location_id=location_id,
            owner_id=owner_id,
            is_temporary=is_temporary,
            stats=stats,
            inventory=inventory,
            current_action=current_action,
            action_queue=action_queue,
            party_id=party_id,
            state_variables=state_variables,
            health=health,
            max_health=max_health,
            is_alive=is_alive,
            status_effects=status_effects,
            archetype=archetype,
            traits=traits,
            desires=desires,
            motives=motives,
            backstory_i18n=backstory_i18n,

            # Pass new fields to constructor
            role_i18n=role_i18n,
            personality_i18n=personality_i18n,
            motivation_i18n=motivation_i18n,
            dialogue_hints_i18n=dialogue_hints_i18n,
            known_abilities=known_abilities,
            known_spells=known_spells,
            skills=skills,
            faction_affiliations=faction_affiliations,
            visual_description_i18n=visual_description_i18n,
            # raw_ai_data=raw_ai_data,

            guild_id=guild_id_val, # Use the value extracted earlier
            relationships=relationships_val, # Use the value extracted earlier
            is_ai_generated=is_ai_generated_val,
            # TODO: Передайте другие поля в конструктор
            # description=description,
            # ai_state=ai_state,
        )

# Конец класса NPC
