# bot/game/models/character.py

from dataclasses import dataclass, field, asdict # Добавляем asdict
from typing import Optional, Dict, Any, List

@dataclass
class Character:
    """
    Модель данных для игрового персонажа.
    """
    # Уникальный идентификатор персонажа (UUID)
    id: str

    # Discord User ID, с которым связан этот персонаж (Optional, т.к. может быть NPC в будущем или персонаж без Discord аккаунта)
    discord_user_id: Optional[int]

    # Имя персонажа (может быть задано игроком)
    name: str

    # ID локации, где находится персонаж
    location_id: Optional[str]

    # Словарь характеристик (например, {"сила": 10, "ловкость": 10})
    stats: Dict[str, Any] = field(default_factory=dict)

    # Инвентарь персонажа (список Item IDs). Может быть пустым.
    inventory: List[str] = field(default_factory=list)

    # Текущее индивидуальное действие персонажа (например, 'move', 'craft', 'rest').
    # Словарь с данными действия (type, target_id, total_duration, progress, start_game_time, callback_data и т.п.).
    current_action: Optional[Dict[str, Any]] = None

    # Очередь индивидуальных действий персонажа. Список словарей действий.
    action_queue: List[Dict[str, Any]] = field(default_factory=list)

    # ID партии, если состоит в партии
    party_id: Optional[str] = None

    # Словарь для любых дополнительных переменных состояния, специфичных для этого персонажа
    # Например, флаги квестов, прогресс определенных задач, временные модификаторы.
    state_variables: Dict[str, Any] = field(default_factory=dict)

    # Здоровье, максимальное здоровье, статус жизни
    health: float = 100.0
    max_health: float = 100.0
    is_alive: bool = True

    # Список ID активных статус-эффектов на этом персонаже (StatusEffect IDs)
    status_effects: List[str] = field(default_factory=list)

    # --- Добавленные поля для уровня, опыта и навыков ---
    level: int = 1
    xp: int = 0 # Или float
    skills: Dict[str, Any] = field(default_factory=dict) # Пример: {"взлом": 50, "стрельба": 75}
    # ----------------------------------------------------

    # TODO: Добавьте другие поля, если необходимо для вашей игры (снаряжение, репутация, валюта и т.п.)
    # currency: float = 0.0 # Пример поля для валюты
    # equipment: Dict[str, Optional[str]] = field(default_factory=dict) # Пример: {"head": None, "body": "item_id_of_armor"}


    def to_dict(self) -> Dict[str, Any]:
        """Преобразует объект Character в словарь для сериализации (например, в JSON)."""
        # Используем asdict для простоты и автоматического включения новых полей
        return asdict(self)


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Character":
        """Создает объект Character из словаря (например, при десериализации из JSON или БД)."""
        # Этот метод должен уметь обработать словарь, который может быть загружен,
        # даже если он не содержит всех полей (например, если схема БД или формат JSON изменились).
        # Используем .get() с значениями по умолчанию для устойчивости к неполным данным.

        # Обязательные поля (должны быть в словаре данных, если их нет - это критическая ошибка)
        char_id = data['id'] # Пробрасываем ошибку, если ID нет - это критично
        name = data['name'] # Пробрасываем ошибку, если имени нет


        # Опциональные поля с значениями по умолчанию
        discord_user_id_raw = data.get('discord_user_id')
        discord_user_id = int(discord_user_id_raw) if discord_user_id_raw is not None else None # Убедимся, что это int или None

        location_id = data.get('location_id') # None по умолчанию
        party_id = data.get('party_id') # None по умолчанию

        # Словари и списки - используем get с пустым словарем/списком как значение по умолчанию
        stats = data.get('stats', {}) or {}
        inventory = data.get('inventory', []) or [] # Убедимся, что это список Item IDs
        current_action = data.get('current_action') # None по умолчанию
        action_queue = data.get('action_queue', []) or []
        state_variables = data.get('state_variables', {}) or {}
        status_effects = data.get('status_effects', []) or [] # Убедимся, что это список StatusEffect IDs
        skills = data.get('skills', {}) or {} # Новое поле, по умолчанию пустой dict

        # Числовые поля - используем get с дефолтом и преобразуем
        health = float(data.get('health', 100.0))
        max_health = float(data.get('max_health', 100.0))
        level = int(data.get('level', 1)) # Новое поле, по умолчанию 1
        xp = int(data.get('xp', 0)) # Новое поле, по умолчанию 0 (или float(data.get('xp', 0.0)) если опыт дробный)

        # Булевы поля - используем get с дефолтом и преобразуем в bool
        is_alive = bool(data.get('is_alive', True)) # Default True

        # TODO: Обработайте другие поля, если добавили
        # currency = float(data.get('currency', 0.0))
        # equipment = data.get('equipment', {}) or {}


        return Character(
            id=char_id,
            discord_user_id=discord_user_id,
            name=name,
            location_id=location_id,
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
            level=level, # Передаем новые поля
            xp=xp,
            skills=skills,
            # TODO: Передайте другие поля в конструктор
            # currency=currency,
            # equipment=equipment,
        )

# Конец класса Character
