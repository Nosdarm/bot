# tests/utils/test_i18n_utils.py
import pytest
from unittest.mock import MagicMock, patch
import json # Добавил json для MOCK_TRANSLATIONS_FILE_CONTENT

from bot.utils.i18n_utils import get_entity_localized_text

# Простой мок для сущности с i18n полями
class MockEntity:
    def __init__(self, name_i18n=None, description_i18n=None, title_i18n=None):
        if name_i18n is not None:
            self.name_i18n = name_i18n
        if description_i18n is not None:
            self.description_i18n = description_i18n
        if title_i18n is not None: # Для примера другого поля
            self.title_i18n = title_i18n

def test_get_entity_localized_text_exact_match():
    entity = MockEntity(name_i18n={"en": "Hello", "ru": "Привет"})
    assert get_entity_localized_text(entity, "name_i18n", "ru") == "Привет"
    assert get_entity_localized_text(entity, "name_i18n", "en") == "Hello"

def test_get_entity_localized_text_fallback_to_default():
    entity = MockEntity(description_i18n={"en": "Description", "de": "Beschreibung"})
    assert get_entity_localized_text(entity, "description_i18n", "ru", default_lang="en") == "Description"

def test_get_entity_localized_text_fallback_to_first_available():
    entity = MockEntity(title_i18n={"de": "Titel", "fr": "Titre"})
    # Порядок в словарях Python 3.7+ сохраняется, но для надежности лучше не полагаться на "первый" без сортировки.
    # Однако, текущая реализация get_entity_localized_text использует next(iter(i18n_data.values())),
    # что вернет значение для одного из ключей.
    result = get_entity_localized_text(entity, "title_i18n", "es", default_lang="it")
    assert result in ["Titel", "Titre"]

def test_get_entity_localized_text_lang_and_default_not_found():
    entity = MockEntity(name_i18n={"de": "Hallo"})
    # Попытка получить "es", фолбэк на "en", но есть только "de"
    # Должен вернуть значение для "de" как единственное доступное
    assert get_entity_localized_text(entity, "name_i18n", "es", default_lang="en") == "Hallo"

def test_get_entity_localized_text_field_not_present():
    entity = MockEntity(name_i18n={"en": "Name"})
    assert get_entity_localized_text(entity, "non_existent_i18n_field", "en") is None

def test_get_entity_localized_text_i18n_data_is_none():
    entity = MockEntity(name_i18n=None)
    assert get_entity_localized_text(entity, "name_i18n", "en") is None

def test_get_entity_localized_text_i18n_data_is_empty_dict():
    entity = MockEntity(name_i18n={})
    assert get_entity_localized_text(entity, "name_i18n", "en") is None

def test_get_entity_localized_text_entity_is_none():
    assert get_entity_localized_text(None, "name_i18n", "en") is None

def test_get_entity_localized_text_non_dict_i18n_data():
    entity = MagicMock()
    entity.name_i18n = "Just a string" # Не словарь
    assert get_entity_localized_text(entity, "name_i18n", "en") is None

def test_get_entity_localized_text_default_lang_used_when_lang_missing():
    entity = MockEntity(name_i18n={"en": "Hello English", "ru": "Привет Русский"})
    assert get_entity_localized_text(entity, "name_i18n", "de", default_lang="ru") == "Привет Русский"

def test_get_entity_localized_text_no_matching_keys_returns_none():
    entity = MockEntity(name_i18n={"fr": "Bonjour"})
    # Запрашиваем 'es', по умолчанию 'it', есть только 'fr'. Должен вернуть "Bonjour" из-за `next(iter(i18n_data.values()))`
    assert get_entity_localized_text(entity, "name_i18n", "es", default_lang="it") == "Bonjour"

    # Чтобы проверить None, если нет совпадений и нет "первого доступного" (т.е. пустой словарь)
    entity_empty = MockEntity(name_i18n={})
    assert get_entity_localized_text(entity_empty, "name_i18n", "es", default_lang="it") is None

# Тесты для функции get_localized_string (если она также используется для локализации данных локаций)
# На данный момент, она загружает из файлов, а не из полей сущности.
# Если она будет использоваться для форматирования строк, полученных из get_entity_localized_text,
# то тесты на форматирование могут быть здесь.

# Пример, если бы мы тестировали load_translations и get_localized_string
# Для этого нужно мокнуть open и json.load
MOCK_TRANSLATIONS_FILE_CONTENT = {
    "en": {
        "location.welcome": "Welcome to {location_name}!",
        "location.danger": "Be careful, danger lurks here."
    },
    "ru": {
        "location.welcome": "Добро пожаловать в {location_name}!",
        "location.danger": "Осторожно, здесь таится опасность."
    }
}

@patch("builtins.open", new_callable=MagicMock) # Используем MagicMock напрямую для mock_open
@patch("json.load")
@patch("os.path.exists", return_value=True) # Предполагаем, что файл существует
def test_get_localized_string_loaded_from_file(mock_exists, mock_json_load, mock_file_open_builtin, monkeypatch):
    # Настраиваем mock_open, чтобы он вел себя как файловый объект
    mock_file_open_builtin.return_value.__enter__.return_value.read.return_value = json.dumps(MOCK_TRANSLATIONS_FILE_CONTENT)
    mock_json_load.return_value = MOCK_TRANSLATIONS_FILE_CONTENT

    # Перезагружаем переводы, так как они могли быть загружены при импорте модуля
    from bot.utils import i18n_utils # Импорт внутри, чтобы повлиять на _loaded

    # Сохраняем и восстанавливаем исходные значения, чтобы не влиять на другие тесты
    original_translations = i18n_utils._translations
    original_loaded = i18n_utils._loaded
    original_i18n_files = i18n_utils._i18n_files

    i18n_utils._translations = {}
    i18n_utils._loaded = False
    # Указываем, какой файл должен быть "загружен"
    # Этот путь должен соответствовать тому, что ожидает `load_translations` внутри
    # Если `_i18n_files` не меняется, то `load_translations` будет пытаться загрузить стандартные файлы.
    # Для этого теста лучше явно указать, какой файл мокается.
    # Пусть `load_translations` вызовется с путем, который мы мокаем.
    # Однако, `load_translations` вызывается без аргументов при первом вызове `get_localized_string`.
    # Поэтому мы мокаем `_i18n_files`
    monkeypatch.setattr(i18n_utils, '_i18n_files', ["dummy_path/feedback_i18n.json"])

    # Первый вызов get_localized_string вызовет load_translations
    welcome_en = i18n_utils.get_localized_string("location.welcome", "en", location_name="Tavern")
    assert welcome_en == "Welcome to Tavern!"
    # Проверяем, что open был вызван с ожидаемым путем из _i18n_files
    mock_file_open_builtin.assert_called_with("dummy_path/feedback_i18n.json", 'r', encoding='utf-8')

    welcome_ru = i18n_utils.get_localized_string("location.welcome", "ru", location_name="Таверна")
    assert welcome_ru == "Добро пожаловать в Таверна!"

    danger_de_fallback_en = i18n_utils.get_localized_string("location.danger", "de", default_lang="en")
    assert danger_de_fallback_en == "Be careful, danger lurks here."

    non_existent_key = i18n_utils.get_localized_string("non.existent.key", "en")
    assert non_existent_key == "non.existent.key" # Возвращает ключ, если не найден

    # Восстанавливаем исходные значения
    monkeypatch.setattr(i18n_utils, '_translations', original_translations)
    monkeypatch.setattr(i18n_utils, '_loaded', original_loaded)
    monkeypatch.setattr(i18n_utils, '_i18n_files', original_i18n_files)

# Исправляем использование mock_open из unittest.mock, если pytest.helpers.mock_open недоступен
# или если хотим использовать стандартный mock_open.
from unittest.mock import mock_open as unittest_mock_open

@patch("builtins.open", new_callable=unittest_mock_open) # Используем unittest.mock.mock_open
@patch("json.load")
@patch("os.path.exists", return_value=True)
def test_get_localized_string_loaded_from_file_unittest_mock(mock_exists, mock_json_load, mock_file_open_builtin, monkeypatch):
    mock_file_open_builtin.return_value.read.return_value = json.dumps(MOCK_TRANSLATIONS_FILE_CONTENT)
    mock_json_load.return_value = MOCK_TRANSLATIONS_FILE_CONTENT

    from bot.utils import i18n_utils
    original_translations = i18n_utils._translations
    original_loaded = i18n_utils._loaded
    original_i18n_files = i18n_utils._i18n_files

    i18n_utils._translations = {}
    i18n_utils._loaded = False
    monkeypatch.setattr(i18n_utils, '_i18n_files', ["dummy_path_unittest/feedback_i18n.json"])

    welcome_en = i18n_utils.get_localized_string("location.welcome", "en", location_name="Tavern")
    assert welcome_en == "Welcome to Tavern!"
    mock_file_open_builtin.assert_called_with("dummy_path_unittest/feedback_i18n.json", 'r', encoding='utf-8')

    monkeypatch.setattr(i18n_utils, '_translations', original_translations)
    monkeypatch.setattr(i18n_utils, '_loaded', original_loaded)
    monkeypatch.setattr(i18n_utils, '_i18n_files', original_i18n_files)
