# bot/game/models/party.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List # Import List


@dataclass
class Party:
    """
    Модель данных для группы сущностей (персонажей и NPC).
    """
    # Уникальный идентификатор партии (UUID)
    id: str

    # Имя партии (может быть задано лидером или сгенерировано)
    name: str

    # ID лидера партии (Optional, может быть None, если партия без лидера)
    leader_id: Optional[str] = None # ID сущности-лидера (Character ID или NPC ID)

    # Список ID всех участников партии (Character и NPC IDs)
    members: List[str] = field(default_factory=list)

    # Текущее групповое действие партии (например, 'move', 'rest', 'explore'). Для координации действий группы.
    current_action: Optional[Dict[str, Any]] = None

    # Очередь групповых действий партии.
    action_queue: List[Dict[str, Any]] = field(default_factory=list)

    # Словарь для любых дополнительных переменных состояния, специфичных для этой партии
    # Например, общий инвентарь партии ( Party Inventory ), бонусы партии, флаги состояний группы.
    state_variables: Dict[str, Any] = field(default_factory=dict)

    # TODO: Добавьте другие поля, если необходимо для вашей логики партий
    # Например:
    # location_id: Optional[str] # Локация, где находится большинство участников партии? Или где находится лидер?
    # combat_id: Optional[str] # ID боя, если партия участвует в бою


    def to_dict(self) -> Dict[str, Any]:
        """Преобразует объект Party в словарь для сериализации."""
        # from dataclasses import asdict
        # return asdict(self) # Можно использовать asdict, если не нужно спец. обработки

        data = {
            'id': self.id,
            'name': self.name,
            'leader_id': self.leader_id,
            'members': self.members,
            'current_action': self.current_action,
            'action_queue': self.action_queue,
            'state_variables': self.state_variables,
            # TODO: Включите другие поля, если добавили
            # 'location_id': self.location_id,
            # 'combat_id': self.combat_id,
        }
        return data


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Party":
        """Создает объект Party из словаря (например, при десериализации из БД)."""
        # Используем .get() с значениями по умолчанию для устойчивости к неполным данным.

        # Обязательные поля
        party_id = data['id'] # Пробрасываем ошибку, если ID нет - критично
        name = data['name'] # Пробрасываем ошибку, если имени нет


        # Опциональные поля с значениями по умолчанию
        leader_id = data.get('leader_id') # None по умолчанию

        # members - список строк (ID сущностей)
        members = data.get('members', []) or [] # Убедимся, что это список
        if not isinstance(members, list):
             print(f"Party Model: Warning: Loaded members list for Party {party_id} is not a list ({type(members).__name__}). Initializing as empty list.")
             members = [] # Исправляем некорректный тип

        # current_action и action_queue могут быть None/пустыми списками
        current_action = data.get('current_action') # None по умолчанию (или {}?)
        # Убедимся, что action_queue - это список
        action_queue = data.get('action_queue', []) or []
        if not isinstance(action_queue, list):
             print(f"Party Model: Warning: Loaded action_queue for Party {party_id} is not a list ({type(action_queue).__name__}). Initializing as empty list.")
             action_queue = [] # Исправляем некорректный тип

        state_variables = data.get('state_variables', {}) or {} # Убедимся, что это словарь

        # TODO: Обработайте другие поля, если добавили, используя .get()
        # location_id = data.get('location_id')
        # combat_id = data.get('combat_id')


        return Party(
            id=party_id,
            name=name,
            leader_id=leader_id,
            members=members,
            current_action=current_action,
            action_queue=action_queue,
            state_variables=state_variables,
            # TODO: Передайте другие поля в конструктор
            # location_id=location_id,
            # combat_id=combat_id,
        )

# Конец класса Party