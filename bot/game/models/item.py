# bot/game/models/item.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

# Модель Item не нуждается в импорте других менеджеров или сервисов.
# Она просто хранит данные.

@dataclass
class Item:
    """
    Модель данных для игрового предмета (экземпляра предмета в мире).
    Состояние предмета (owner_id, location_id, state_variables) - персистентное.
    Базовые данные (name, description, template_id) берутся из шаблона.
    """
    # Уникальный идентификатор экземпляра предмета (генерируется менеджером при создании)
    id: str

    # ID шаблона предмета, на основе которого создан этот экземпляр
    template_id: str

    # ID гильдии, которой принадлежит этот инстанс предмета
    guild_id: str

    # Количество (для стакабельных предметов)
    quantity: float = 1.0

    # ID сущности-владельца (Character ID, NPC ID, Event ID, Combat ID, Party ID)
    # None, если предмет ничей
    owner_id: Optional[str] = None # Default to None

    # Тип владельца, чтобы различать ID из разных таблиц (character, npc, etc.)
    owner_type: Optional[str] = None # Default to None

    # ID локации, где находится предмет, если он не в инвентаре (owner_id is None)
    # Если owner_id IS NOT NULL, location_id может указывать на местоположение ВЛАДЕЛЬЦА
    location_id: Optional[str] = None # Default to None

    # Флаг, указывающий, является ли предмет временным (для автоматической очистки)
    is_temporary: bool = False

    # Словарь для любых дополнительных переменных состояния, специфичных для этого экземпляра предмета
    # Например, прочность, количество зарядов, уникальные свойства и т.п.
    state_variables: Dict[str, Any] = field(default_factory=dict)

    # Примечание: name, description и другие статические свойства
    # должны загружаться из шаблона предмета в ItemManager, а не храниться здесь.

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует объект Item в словарь для сериализации."""
        data = {
            'id': self.id,
            'template_id': self.template_id,
            'guild_id': self.guild_id,
            'quantity': self.quantity,
            'owner_id': self.owner_id,
            'owner_type': self.owner_type,
            'location_id': self.location_id,
            'is_temporary': self.is_temporary,
            'state_variables': self.state_variables,
        }
        return data


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Item":
        """Создает объект Item из словаря (например, при десериализации из БД)."""
        # Обязательные поля
        item_id = data['id']
        template_id = data['template_id']
        guild_id = data['guild_id'] # guild_id is now mandatory

        # Опциональные поля с значениями по умолчанию
        quantity = float(data.get('quantity', 1.0)) # Default to 1.0, ensure float
        owner_id = data.get('owner_id')
        owner_type = data.get('owner_type')
        location_id = data.get('location_id')
        is_temporary = bool(data.get('is_temporary', False))
        state_variables = data.get('state_variables', {}) or {}

        return Item(
            id=item_id,
            template_id=template_id,
            guild_id=str(guild_id), # Ensure guild_id is string
            quantity=quantity,
            owner_id=str(owner_id) if owner_id is not None else None,
            owner_type=str(owner_type) if owner_type is not None else None,
            location_id=str(location_id) if location_id is not None else None,
            is_temporary=is_temporary,
            state_variables=state_variables,
        )

# Конец класса Item
