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
        status_id = data.get('id') 
        if status_id is None: raise ValueError("StatusEffect data missing 'id'")
        
        status_type = data.get('status_type')
        if status_type is None: raise ValueError(f"StatusEffect data for id '{status_id}' missing 'status_type'")

        target_id = data.get('target_id')
        target_type = data.get('target_type')

        # Apply defaults and print warnings if essential fields are missing
        if target_id is None:
            print(f"WARNING: StatusEffect.from_dict: 'target_id' was missing for status_id '{status_id}'. Defaulting to 'unknown_target_for_{status_id}'. Data: {data}")
            target_id = f"unknown_target_for_{status_id}" 
        if target_type is None:
            print(f"WARNING: StatusEffect.from_dict: 'target_type' was missing for status_id '{status_id}'. Defaulting to 'Unknown'. Data: {data}")
            target_type = "Unknown"

        duration_raw = data.get('duration')
        duration = float(duration_raw) if duration_raw is not None else None

        applied_at_raw = data.get('applied_at')
        applied_at = float(applied_at_raw) if applied_at_raw is not None else None

        source_id = data.get('source_id') 
        state_variables = data.get('state_variables', {}) or {} 

        return StatusEffect(
            id=str(status_id), # Ensure ID is string
            status_type=str(status_type),
            target_id=str(target_id),
            target_type=str(target_type),
            duration=duration,
            applied_at=applied_at,
            source_id=str(source_id) if source_id is not None else None,
            state_variables=state_variables,
        )

# Конец класса StatusEffect
