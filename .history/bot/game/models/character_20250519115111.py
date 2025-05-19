# В bot/game/models/character.py

from __future__ import annotations # Убедитесь, что это есть
import json
from typing import Dict, Any, List, Optional # Импортируем все необходимые типы

# TODO: Импортировать другие модели, если Character имеет на них ссылки (напр., Item)
# from bot.game.models.item import Item # Если Item используется в аннотациях инвентаря

class Character:
    # Определение атрибутов класса (опционально, но полезно для читаемости и Type Checking)
    # Если используется __future__ annotations и аннотации в __init__, это менее критично,
    # но для ClassVar или дефолтных значений здесь это важно.
    # Example: inventory: List[Dict[str, Any]] # Убедитесь, что тип инвентаря соответствует схеме DB

    def __init__(self,
                 id: str,
                 discord_user_id: int,
                 name: str,
                 guild_id: str, # <-- ДОБАВЬТЕ ЭТОТ АТРИБУТ
                 location_id: Optional[str] = None,
                 stats: Dict[str, Any] = None, # Убедитесь, что default={} или None и обрабатывается
                 inventory: List[Dict[str, Any]] = None, # Убедитесь, что default=[] или None
                 current_action: Optional[Dict[str, Any]] = None,
                 action_queue: List[Dict[str, Any]] = None, # Убедитесь, что default=[]
                 party_id: Optional[str] = None,
                 state_variables: Dict[str, Any] = None, # Убедитесь, что default={}
                 health: float = 100.0,
                 max_health: float = 100.0,
                 is_alive: bool = True,
                 status_effects: List[Dict[str, Any]] = None, # Убедитесь, что default=[]
                 # Примите любые другие атрибуты, которые могут быть в DB схеме или создаются
                 **kwargs: Any # Для гибкости, если появятся новые поля
                ):
        self.id = id
        self.discord_user_id = discord_user_id
        self.name = name
        self.guild_id = guild_id # <-- ПРИСВОЙТЕ АТРИБУТ guild_id
        self.location_id = location_id
        # Инициализация изменяемых атрибутов, если они None (из-за дефолтов в схеме)
        self.stats = stats if stats is not None else {}
        self.inventory = inventory if inventory is not None else []
        self.current_action = current_action
        self.action_queue = action_queue if action_queue is not None else []
        self.party_id = party_id
        self.state_variables = state_variables if state_variables is not None else {}
        self.health = health
        self.max_health = max_health
        self.is_alive = is_alive
        self.status_effects = status_effects if status_effects is not None else []

        # Обработка любых дополнительных kwargs
        for key, value in kwargs.items():
            # Не перезаписывайте существующие атрибуты, если только это не намеренно
            if not hasattr(self, key):
                setattr(self, key, value)


    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Character:
        """Создает объект Character из словаря данных (например, из DB)."""
        # В CharacterManager мы уже парсим JSON и преобразуем типы (например, is_alive в bool).
        # Убедитесь, что словарь `data`, который передается сюда из CharacterManager,
        # уже содержит все поля в правильных типах (str, int, float, bool, list, dict, None).
        # Убедитесь, что он включает ключ 'guild_id'
        if 'guild_id' not in data:
             # Это должно вызывать ошибку, если guild_id обязателен
             raise ValueError("Missing 'guild_id' key in data for Character.from_dict")

        # Вызов конструктора класса, передавая все ключи словаря как аргументы
        # Это сработает корректно, ЕСЛИ __init__ принимает все эти ключи
        # и ЕСЛИ ключи в data совпадают с именами параметров в __init__.
        try:
             # Явное извлечение и передача ключевых аргументов для ясности
             # Убедитесь, что имена ключей соответствуют параметрам __init__
             return cls(
                 id=data.get('id'), # id может быть None если DB вернула что-то странное
                 discord_user_id=data.get('discord_user_id'),
                 name=data.get('name'),
                 guild_id=data.get('guild_id'), # <-- Передайте guild_id
                 location_id=data.get('location_id'),
                 stats=data.get('stats'),
                 inventory=data.get('inventory'),
                 current_action=data.get('current_action'),
                 action_queue=data.get('action_queue'),
                 party_id=data.get('party_id'),
                 state_variables=data.get('state_variables'),
                 health=data.get('health'),
                 max_health=data.get('max_health'),
                 is_alive=data.get('is_alive'),
                 status_effects=data.get('status_effects'),
                 # Передайте любые другие атрибуты, которые __init__ может ожидать
                 # Если в __init__ есть **kwargs, можно передать остальные ключи словаря так:
                 # **{k: v for k, v in data.items() if k not in ['id', 'discord_user_id', 'name', 'guild_id', ...]}
             )
        except Exception as e:
             print(f"Error creating Character object from dict: {data} | Error: {e}")
             import traceback
             traceback.print_exc()
             raise # Перебрасываем ошибку


    # TODO: Другие методы модели Character (например, update_stats, add_status, remove_item и т.д.)
    # Эти методы изменяют состояние объекта Character и должны затем пометить его dirty в CharacterManager.