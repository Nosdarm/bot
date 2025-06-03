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

    # ID сущности-владельца (Character ID, NPC ID, Event ID, Combat ID, Party ID)
    # None, если предмет ничей
    owner_id: Optional[str]

    # ID локации, где находится предмет, если он не в инвентаре (owner_id is None)
    # Если owner_id IS NOT NULL, location_id может указывать на местоположение ВЛАДЕЛЬЦА
    location_id: Optional[str]

    # Флаг, указывающий, является ли предмет временным (для автоматической очистки)
    is_temporary: bool = False

    # Словарь для любых дополнительных переменных состояния, специфичных для этого экземпляра предмета
    # Например, прочность, количество зарядов, уникальные свойства и т.п.
    state_variables: Dict[str, Any] = field(default_factory=dict)

    # Примечание: name, description и другие статические свойства
    # должны загружаться из шаблона предмета в ItemManager, а не храниться здесь.

    def to_dict(self) -> Dict[str, Any]:
        """Преобразует объект Item в словарь для сериализации."""
        # Используйте dataclasses.asdict() если не нужна спец. логика
        # from dataclasses import asdict
        # return asdict(self)

        data = {
            'id': self.id,
            'template_id': self.template_id,
            'owner_id': self.owner_id,
            'location_id': self.location_id,
            'is_temporary': self.is_temporary,
            'state_variables': self.state_variables,
            # TODO: Включите другие поля, если добавили
        }
        return data


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Item":
        """Создает объект Item из словаря (например, при десериализации из БД)."""
        # Используем .get() с значениями по умолчанию для устойчивости к неполным данным.

        # Обязательные поля
        item_id = data['id'] # Пробрасываем ошибку, если ID нет - критично
        template_id = data['template_id'] # Пробрасываем ошибку, если template_id нет - критично

        # Опциональные поля с значениями по умолчанию
        owner_id = data.get('owner_id') # None по умолчанию
        location_id = data.get('location_id') # None по умолчанию
        is_temporary = bool(data.get('is_temporary', False)) # Преобразуем 0/1 в bool
        state_variables = data.get('state_variables', {}) or {} # Убедимся, что это словарь

        # TODO: Обработайте другие поля, если добавили, используя .get()

        return Item(
            id=item_id,
            template_id=template_id,
            owner_id=owner_id,
            location_id=location_id,
            is_temporary=is_temporary,
            state_variables=state_variables,
            # TODO: Передайте другие поля в конструктор
        )

# Конец класса Item
