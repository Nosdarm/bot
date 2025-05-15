# bot/game/models/crafting_task.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List # Импортируем List, хотя в этой модели он напрямую не нужен, это просто хорошая практика

# Модель CraftingTask не нуждается в импорте других менеджеров или сервисов.
# Она просто хранит данные.

@dataclass
class CraftingTask:
    """
    Модель данных для одной задачи крафтинга в очереди сущности (например, персонажа).
    """
    # Уникальный идентификатор задачи крафтинга (генерируется менеджером при создании)
    id: str

    # ID рецепта, который используется
    recipe_id: str

    # ID шаблона предмета, который будет создан в результате
    # Может быть None, если рецепт создает не предмет (например, эффект)
    item_template_id: Optional[str]

    # Текущий прогресс выполнения задачи (например, в единицах игрового времени)
    progress: float

    # Общая длительность, необходимая для завершения задачи (в тех же единицах)
    total_duration: float

    # Игровое время, когда задача была начата (None, пока задача в очереди)
    start_game_time: Optional[float]

    # Флаг, указывающий, завершена ли задача (используется для логического удаления или отслеживания)
    is_completed: bool = False

    # Словарь для любых дополнительных переменных состояния, специфичных для этой задачи
    # Например, случайные модификаторы качества, ссылки на использованные временные ингредиенты и т.п.
    state_variables: Dict[str, Any] = field(default_factory=dict)

    # TODO: Добавьте другие поля, если необходимо для вашей логики крафтинга
    # Например:
    # entity_id: str # ID сущности, которая крафтит (персонаж, NPC, локация) - если CraftingManager хранит все задачи в одном кеше
    # entity_type: str # Тип сущности ("Character", "NPC", "Location") - если нужно
    # used_ingredients: List[str] = field(default_factory=list) # Список ID конкретных использованных ингредиентов


    def to_dict(self) -> Dict[str, Any]:
        """Преобразует объект CraftingTask в словарь для сериализации."""
        # Используйте dataclasses.asdict() для простоты, если не нужно специальной логики
        # from dataclasses import asdict
        # return asdict(self)

        # Или вручную, чтобы иметь больше контроля над форматом (например, обработка Optional, Decimal и т.п.)
        data = {
            'id': self.id,
            'recipe_id': self.recipe_id,
            'item_template_id': self.item_template_id,
            'progress': self.progress,
            'total_duration': self.total_duration,
            'start_game_time': self.start_game_time,
            'is_completed': self.is_completed,
            'state_variables': self.state_variables,
            # TODO: Включите другие поля, если добавили
            # 'entity_id': self.entity_id,
            # 'entity_type': self.entity_type,
            # 'used_ingredients': self.used_ingredients,
        }
        # Optional: Удалить None или пустые словари/списки для оптимизации размера JSON
        # return {k: v for k, v in data.items() if v is not None and v != {} and v != []}
        return data


    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "CraftingTask":
        """Создает объект CraftingTask из словаря (например, при десериализации из БД)."""
        # Этот метод должен уметь обработать словарь, который может быть загружен из БД,
        # даже если он не содержит всех полей (например, если схема БД изменилась).
        # Используем .get() с значениями по умолчанию.

        # Обязательные поля (должны быть в словаре данных)
        task_id = data['id'] # Пробрасываем ошибку, если ID нет - это критично
        recipe_id = data['recipe_id']
        progress = float(data.get('progress', 0.0)) # Преобразуем в float на случай, если в БД хранилось как int
        total_duration = float(data.get('total_duration', 0.0)) # Преобразуем в float


        # Опциональные поля (с значениями по умолчанию)
        item_template_id = data.get('item_template_id') # None по умолчанию
        start_game_time = data.get('start_game_time')
        # is_completed может прийти из БД как 0/1, преобразуем в bool
        is_completed = bool(data.get('is_completed', False))
        state_variables = data.get('state_variables', {}) or {} # Убедимся, что это словарь, даже если загружено None или {}

        # TODO: Обработайте другие поля, если добавили, используя .get()

        return CraftingTask(
            id=task_id,
            recipe_id=recipe_id,
            item_template_id=item_template_id,
            progress=progress,
            total_duration=total_duration,
            start_game_time=start_game_time,
            is_completed=is_completed,
            state_variables=state_variables,
            # TODO: Передайте другие поля в конструктор
            # entity_id=data.get('entity_id'),
            # entity_type=data.get('entity_type'),
            # used_ingredients=data.get('used_ingredients', []) or [],
        )

# Конец класса CraftingTask