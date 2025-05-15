# bot/game/models/status_effect.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

# Модель StatusEffect не нуждается в импорте других менеджеров или сервисов.
# Она просто хранит данные.

@dataclass
class StatusEffect:
    """
    Модель данных для активного статус-эффекта, наложенного на сущность.
    """
    # Уникальный идентификатор экземпляра статус-эффекта (UUID)
    id: str

    # Тип статуса (например, "Bleeding", "Poisoned", "Stunned", "BuffStrength")
    # Ссылается на статические данные шаблона статуса.
    status_type: str

    # ID сущности, на которую наложен статус-эффект
    target_id: str

    # Тип сущности-цели ('Character', 'NPC', 'Location', 'Item', 'Combat', 'Party')
    target_type: str

    # Оставшаяся длительность статус-эффекта в игровом времени (например, в минутах или тиках).
    # None, если статус перманентный.
    duration: Optional[float] = None

    # Игровое время, когда статус был наложен.
    # Используется для пересчета оставшейся длительности, если статус сохранялся/загружался.
    # Требуется только если duration не None.
    applied_at: Optional[float] = None

    # ID сущности/источника, который наложил статус (например, NPC ID, Item ID, Skill ID, Event ID).
    # Optional, может быть None.
    source_id: Optional[str] = None

    # Словарь для любых дополнительных переменных состояния, специфичных для этого экземпляра статуса
    # Например, накопленный урон от яда/кровотечения, количество стаков, сила эффекта и т.п.
    state_variables: Dict[str, Any] = field(default_factory=dict)

    # TODO: Добавьте другие поля, если необходимо для вашей логики статусов
    # Например:
    # is_active: bool = True # Флаг для логического удаления
    # applied_by_type: Optional[str] = None # Тип источника ('NPC', 'Item', 'Skill')


    def to_dict(self) -> Dict[str, Any]:
        """Преобразует объект StatusEffect в словарь для сериализации."""
        # Используйте dataclasses.asdict() если не нужна спец. логика
        # from dataclasses import asdict
        # return asdict(self)

        data = {
            'id': self.id,
            'status_type': self.status_type,
            'target_id': self.target_id,
            'target_type': self.target_type,
            'duration': self.duration,
            'applied_at': self.applied_at,
            'source_id': self.source_id,
            'state_variables': self.state_variables,
            # TODO: Включите другие поля, если добавили
            # 'is_active': self.is_active,
            # 'applied_by_type': self.applied_by_type,
        }
        return data


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "StatusEffect":
        """Создает объект StatusEffect из словаря (например, при десериализации из БД)."""
        # Используем .get() с значениями по умолчанию для устойчивости к неполным данным.

        # Обязательные поля (должны быть в словаре данных)
        status_id = data['id'] # Пробрасываем ошибку, если ID нет - критично
        status_type = data['status_type'] # Пробрасываем ошибку, если типа нет
        target_id = data['target_id'] # Пробрасываем ошибку, если цели нет
        target_type = data['target_type'] # Пробрасываем ошибку, если типа цели нет


        # Опциональные поля с значениями по умолчанию
        duration_raw = data.get('duration') # Может быть None или число
        duration = float(duration_raw) if duration_raw is not None else None # Преобразуем в float

        applied_at_raw = data.get('applied_at') # Может быть None или число
        applied_at = float(applied_at_raw) if applied_at_raw is not None else None # Преобразуем в float

        source_id = data.get('source_id') # None по умолчанию
        state_variables = data.get('state_variables', {}) or {} # Убедимся, что это словарь

        # TODO: Обработайте другие поля, если добавили, используя .get()
        # is_active = bool(data.get('is_active', True)) # По умолчанию активен
        # applied_by_type = data.get('applied_by_type')

        return StatusEffect(
            id=status_id,
            status_type=status_type,
            target_id=target_id,
            target_type=target_type,
            duration=duration,
            applied_at=applied_at,
            source_id=source_id,
            state_variables=state_variables,
            # TODO: Передайте другие поля в конструктор
            # is_active=is_active,
            # applied_by_type=applied_by_type,
        )

# Конец класса StatusEffect