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
    name: str

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
    backstory: str = ""  # Краткая предыстория

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
            'name': self.name,
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
            'backstory': self.backstory,
            # TODO: Включите другие поля, если добавили
            # 'description': self.description,
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
        name = data.get('name')
        if name is None:
            raise ValueError("Missing 'name' key in data for NPC.from_dict")


        # Опциональные поля с значениями по умолчанию
        location_id = data.get('location_id') # None по умолчанию
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
        backstory = data.get('backstory', "")

        if not isinstance(traits, list):
            print(f"NPC Model: Warning: Loaded traits for NPC {npc_id} is not a list ({type(traits).__name__}). Initializing as empty list.")
            traits = []
        if not isinstance(desires, list):
            print(f"NPC Model: Warning: Loaded desires for NPC {npc_id} is not a list ({type(desires).__name__}). Initializing as empty list.")
            desires = []
        if not isinstance(motives, list):
            print(f"NPC Model: Warning: Loaded motives for NPC {npc_id} is not a list ({type(motives).__name__}). Initializing as empty list.")
            motives = []

        return NPC(
            id=npc_id,
            template_id=template_id,
            name=name,
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
            backstory=backstory,
            # TODO: Передайте другие поля в конструктор
            # description=description,
            # ai_state=ai_state,
        )

# Конец класса NPC