# bot/game/models/party.py

import json # Added for JSON serialization/deserialization
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

    # Список ID всех участников партии (Character и NPC IDs) - internal representation
    player_ids_list: List[str] = field(default_factory=list, metadata={"db_column_name": "player_ids"})

    # Новые поля согласно задаче
    current_location_id: Optional[str] = None # FK к locations.id
    turn_status: Optional[str] = None # Например, "collecting", "waiting", "processing"
    
    # Поле для хранения JSON строки player_ids для совместимости с БД (если необходимо)
    # Это поле не будет напрямую использоваться в бизнес-логике так часто, как player_ids_list
    player_ids: Optional[str] = field(default=None, repr=False) # JSON string of player IDs, not shown in default repr

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
            # 'members': self.members, # player_ids_list (serialized as player_ids) is the source of truth
            'current_action': self.current_action,
            'action_queue': self.action_queue,
            'state_variables': self.state_variables,
            # TODO: Включите другие поля, если добавили
            # 'combat_id': self.combat_id,
            'current_location_id': self.current_location_id,
            'turn_status': self.turn_status,
            'player_ids': json.dumps(self.player_ids_list) # Serialize list to JSON string
        }
        return data


    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Party":
        """Создает объект Party из словаря (например, при десериализации из БД)."""
        # Используем .get() с значениями по умолчанию для устойчивости к неполным данным.

        # Обязательные поля
        party_id = data['id'] # Пробрасываем ошибку, если ID нет - критично
        name = data['name'] # Пробрасываем ошибку, если имени нет


        # Опциональные поля с значениями по умолчанию
        leader_id = data.get('leader_id') # None по умолчанию

        # player_ids_list - из поля 'player_ids' (после переименования из 'member_ids') или 'member_ids'
        # Это поле в БД хранится как JSON строка списка ID
        player_ids_json_str = data.get('player_ids', data.get('member_ids', '[]'))
        player_ids_list_internal: List[str] = []
        if player_ids_json_str:
            try:
                loaded_ids = json.loads(player_ids_json_str)
                if isinstance(loaded_ids, list) and all(isinstance(item, str) for item in loaded_ids):
                    player_ids_list_internal = loaded_ids
                else:
                    print(f"Party Model: Warning: Loaded player_ids for Party {party_id} is not a list of strings after JSON parsing. Found: {type(loaded_ids)}. Initializing as empty list.")
            except json.JSONDecodeError:
                print(f"Party Model: Warning: Failed to decode player_ids JSON string for Party {party_id}. Value: '{player_ids_json_str}'. Initializing as empty list.")
        
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
            player_ids_list=player_ids_list_internal, # Use the processed list
            current_action=current_action,
            action_queue=action_queue,
            state_variables=state_variables,
            current_location_id=data.get('current_location_id'),
            turn_status=data.get('turn_status'),
            # player_ids field in dataclass will be default (None), or could be set to player_ids_json_str if needed for exact reconstruction
        )

# Конец класса Party