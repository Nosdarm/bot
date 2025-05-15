# bot/game/models/combat.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List # Import List

# Модель Combat не нуждается в импорте других менеджеров или сервисов.
# Она просто хранит данные.

@dataclass
class Combat:
    """
    Модель данных для активного боевого столкновения.
    """
    # Уникальный идентификатор экземпляра боя (UUID)
    id: str

    # Флаг, указывающий, активен ли бой
    is_active: bool = True

    # ID канала Discord, где происходит бой (для отправки сообщений боя)
    channel_id: Optional[int] = None

    # ID события, связанного с этим боем (опционально)
    event_id: Optional[str] = None

    # Текущий раунд боя
    current_round: int = 1

    # Время, прошедшее в текущей фазе/раунде боя (для точного отсчета в тиках)
    time_in_current_phase: float = 0.0

    # Список ID всех участников боя (Character и NPC IDs)
    # Порядок в списке может определять инициативу или порядок хода.
    participants: List[str] = field(default_factory=list)

    # Словарь для любых дополнительных переменных состояния, специфичных для этого боя
    # Например:
    # - 'turn_order': List[str] # Список ID участников в текущем порядке хода
    # - 'current_turn_index': int # Индекс текущего участника в turn_order
    # - 'combat_phase': str # Текущая фаза боя ('initiative', 'action', 'cleanup')
    # - 'combat_start_game_time': float # Игровое время начала боя
    # - 'round_start_game_time': float # Игровое время начала текущего раунда
    # - 'temporary_effects': List[Dict[str, Any]] # Временные эффекты, специфичные для боя (напр., погода, особенности местности)
    # - 'involved_factions': Dict[str, Set[str]] # Фракции в бою и их участники
    state_variables: Dict[str, Any] = field(default_factory=dict)

    # TODO: Добавьте другие поля, если необходимо для вашей логики боя
    # Например:
    # combat_type: Optional[str] # Тип боя (encounter, boss_fight, arena)
    # location_id: Optional[str] # Локация, где происходит бой (может дублировать event.location_id)


    def to_dict(self) -> Dict[str, Any]:
        """Преобразует объект Combat в словарь для сериализации."""
        # Используйте dataclasses.asdict() если не нужна спец. логика
        # from dataclasses import asdict
        # return asdict(self)

        data = {
            'id': self.id,
            'is_active': self.is_active,
            'channel_id': self.channel_id,
            'event_id': self.event_id,
            'current_round': self.current_round,
            'time_in_current_phase': self.time_in_current_phase,
            'participants': self.participants,
            'state_variables': self.state_variables,
            # TODO: Включите другие поля, если добавили
            # 'combat_type': self.combat_type,
            # 'location_id': self.location_id,
        }
        return data


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Combat":
        """Создает объект Combat из словаря (например, при десериализации из БД)."""
        # Используем .get() с значениями по умолчанию для устойчивости к неполным данным.

        # Обязательные поля
        combat_id = data['id'] # Пробрасываем ошибку, если ID нет - критично


        # Опциональные поля с значениями по умолчанию
        is_active = bool(data.get('is_active', True)) # bool (0/1) по умолчанию True
        channel_id_raw = data.get('channel_id') # Может быть None или число
        channel_id = int(channel_id_raw) if channel_id_raw is not None else None # Преобразуем в int
        event_id = data.get('event_id') # None по умолчанию
        current_round = int(data.get('current_round', 1)) # int по умолчанию 1
        time_in_current_phase = float(data.get('time_in_current_phase', 0.0)) # float по умолчанию 0.0

        # participants - список строк
        participants = data.get('participants', []) or [] # Убедимся, что это список
        if not isinstance(participants, list):
             print(f"Combat Model: Warning: Loaded participants for Combat {combat_id} is not a list ({type(participants).__name__}). Initializing as empty list.")
             participants = [] # Исправляем некорректный тип

        state_variables = data.get('state_variables', {}) or {} # Убедимся, что это словарь

        # TODO: Обработайте другие поля, если добавили, используя .get()
        # combat_type = data.get('combat_type')
        # location_id = data.get('location_id')


        return Combat(
            id=combat_id,
            is_active=is_active,
            channel_id=channel_id,
            event_id=event_id,
            current_round=current_round,
            time_in_current_phase=time_in_current_phase,
            participants=participants,
            state_variables=state_variables,
            # TODO: Передайте другие поля в конструктор
            # combat_type=combat_type,
            # location_id=location_id,
        )

# Конец класса Combat