# bot/game/persistence.py

import json
import os
from typing import Dict, Any, Optional

# Путь к папке для сохранений.
# Убедитесь, что этот путь правилен относительно того, откуда запускается main.py
# Пример пути для папки 'game_data' рядом с папкой 'bot'
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'game_data')

# Убедиться, что папка для данных существует
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)


def get_game_save_path(server_id: int) -> str:
    """Формирует путь к файлу сохранения игры для данного сервера."""
    return os.path.join(DATA_DIR, f'game_state_{server_id}.json')


class PersistenceManager:
    """
    Отвечает за сохранение и загрузку состояния игры в виде словаря.
    Конвертацией в объекты Event, Character и т.д. занимаются Менеджеры.
    """
    def save_game_state_dict(self, server_id: int, game_state_dict: Dict[str, Any]):
        """Сохраняет состояние игры (в виде словаря) в файл JSON."""
        file_path = get_game_save_path(server_id)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(game_state_dict, f, ensure_ascii=False, indent=4)
            # print(f"Состояние игры для сервера {server_id} сохранено в {file_path}") # Опционально логирование
        except Exception as e:
            print(f"Ошибка при сохранении словаря игры для сервера {server_id}: {e}")

    def load_game_state_dict(self, server_id: int) -> Optional[Dict[str, Any]]:
        """Загружает словарь состояния игры из файла JSON."""
        file_path = get_game_save_path(server_id)
        # Если файла нет, значит, сохранений нет, это не ошибка
        if not os.path.exists(file_path):
            # print(f"Нет сохраненного состояния игры для сервера {server_id}.") # Опционально логирование
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                game_state_dict = json.load(f)
            # print(f"Словарь состояния игры для сервера {server_id} загружен из {file_path}") # Опционально логирование
            return game_state_dict
        except Exception as e:
            print(f"Ошибка при загрузке словаря игры для сервера {server_id}: {e}")
            return None

