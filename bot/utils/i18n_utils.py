import json
import os
from typing import Dict, Any, List

_translations: Dict[str, Dict[str, str]] = {}
_i18n_files: List[str] = [
    "game_data/feedback_i18n.json"
    # Add other i18n files here if needed, e.g., "game_data/ui_i18n.json"
]
_loaded = False

def load_translations(base_dir: str = "") -> None:
    """
    Loads translation strings from specified JSON files.
    Merges new translations into the existing _translations dictionary.
    """
    global _translations, _loaded
    if not base_dir: # Simple fallback if not running from a specific project root.
        # This might need adjustment based on actual execution context.
        # Assuming game_data is in the same directory or a sub-directory of where Python is run from.
        # For a robust solution, use absolute paths or paths relative to this file's location.
        # Example for path relative to this file:
        # base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # Assuming this file is in bot/utils/
        pass


    for file_path_rel in _i18n_files:
        actual_file_path = os.path.join(base_dir, file_path_rel) if base_dir else file_path_rel
        try:
            with open(actual_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for lang_code, lang_strings in data.items():
                    if lang_code not in _translations:
                        _translations[lang_code] = {}
                    _translations[lang_code].update(lang_strings)
            print(f"i18n_utils: Successfully loaded translations from {actual_file_path}")
        except FileNotFoundError:
            print(f"i18n_utils: Warning - Translation file not found: {actual_file_path}")
        except json.JSONDecodeError:
            print(f"i18n_utils: Warning - Error decoding JSON from file: {actual_file_path}")
        except Exception as e:
            print(f"i18n_utils: Error loading translation file {actual_file_path}: {e}")
    _loaded = True

def get_localized_string(key: str, lang: str, default_lang: str = "en", **kwargs: Any) -> str:
    """
    Retrieves a localized string by key and language, and formats it with kwargs.

    Args:
        key: The i18n key for the string (e.g., "feedback.relationship.price_discount_faction").
        lang: The desired language code (e.g., "en", "ru").
        default_lang: The fallback language if the desired language or key is not found.
        **kwargs: Placeholder arguments for string formatting.

    Returns:
        The localized and formatted string, or the key itself if not found.
    """
    if not _loaded:
        load_translations() # Load on first use if not already loaded

    lang_strings = _translations.get(lang)
    if lang_strings and key in lang_strings:
        try:
            return lang_strings[key].format(**kwargs)
        except KeyError as e: # Catch missing key in format string
            print(f"i18n_utils: Formatting KeyError for key '{key}', lang '{lang}'. Missing placeholder: {e}")
            return lang_strings[key] # Return unformatted string

    # Fallback to default language
    default_lang_strings = _translations.get(default_lang)
    if default_lang_strings and key in default_lang_strings:
        try:
            return default_lang_strings[key].format(**kwargs)
        except KeyError as e:
            print(f"i18n_utils: Formatting KeyError for key '{key}', lang '{default_lang}' (fallback). Missing placeholder: {e}")
            return default_lang_strings[key]

    print(f"i18n_utils: Warning - Key '{key}' not found for language '{lang}' or default '{default_lang}'.")
    return key # Return the key itself as a last resort

def get_i18n_text(data_dict: Dict[str, Any], field_prefix: str, lang: str, default_lang: str = "en") -> str:
    """
    Retrieves internationalized text from a dictionary field (e.g., name_i18n).
    (Existing function from the file)
    """
    if not data_dict:
        return f"{field_prefix} not found (empty data)"

    i18n_field_name = f"{field_prefix}_i18n"
    i18n_data = data_dict.get(i18n_field_name)

    if isinstance(i18n_data, dict) and i18n_data:
        if lang in i18n_data:
            return str(i18n_data[lang])
        if default_lang in i18n_data:
            return str(i18n_data[default_lang])
        try:
            return str(next(iter(i18n_data.values())))
        except StopIteration:
            pass

    plain_field_value = data_dict.get(field_prefix)
    if plain_field_value is not None:
        return str(plain_field_value)

    return f"{field_prefix} not found"

# Load translations when the module is imported.
# This assumes that the script's working directory is the project root
# or that game_data/ is accessible from where it's run.
# For a more robust solution, especially in complex project structures or tests,
# consider passing an absolute base_path to load_translations() explicitly when initializing services.
if not _loaded:
     load_translations()
