import unittest
from typing import Dict, Any
# Adjust import path based on where the test file is relative to the bot package
# Assuming tests/ is at the same level as bot/
import sys
import os

# Add the project root to the Python path to allow imports from 'bot'
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from bot.utils.i18n_utils import get_i18n_text

class TestGetI18nText(unittest.TestCase):

    def test_fetch_primary_language(self):
        data = {"name_i18n": {"en": "Hello", "es": "Hola"}}
        self.assertEqual(get_i18n_text(data, "name", "en", "es"), "Hello")
        self.assertEqual(get_i18n_text(data, "name", "es", "en"), "Hola")

    def test_fallback_to_default_language(self):
        data = {"name_i18n": {"en": "Hello", "es": "Hola"}}
        self.assertEqual(get_i18n_text(data, "name", "fr", "en"), "Hello") # fr not present, fallback to en
        self.assertEqual(get_i18n_text(data, "name", "de", "es"), "Hola") # de not present, fallback to es

    def test_fallback_to_first_available(self):
        data1 = {"title_i18n": {"fr": "Bonjour", "de": "Guten Tag"}}
        # Request 'it', default 'en' (neither present), should pick first from title_i18n (fr or de)
        # Order of items in dict prior to Python 3.7 is not guaranteed.
        # For 3.7+ it's insertion order. Let's assume 'fr' is "first" for this test.
        # To make it robust, we check if it's one of the available ones.
        self.assertIn(get_i18n_text(data1, "title", "it", "en"), ["Bonjour", "Guten Tag"])

        data2 = {"text_i18n": {"ru": "Привет"}}
        self.assertEqual(get_i18n_text(data2, "text", "en", "fr"), "Привет")


    def test_fallback_to_plain_field(self):
        data1 = {"name": "Plain Name"} # No name_i18n
        self.assertEqual(get_i18n_text(data1, "name", "en", "es"), "Plain Name")

        data2 = {"description_i18n": {}, "description": "Plain Description"} # Empty i18n dict
        self.assertEqual(get_i18n_text(data2, "description", "en", "es"), "Plain Description")

        data3 = {"info_i18n": "not a dict", "info": "Plain Info"} # Malformed i18n field
        self.assertEqual(get_i18n_text(data3, "info", "en", "es"), "Plain Info")

    def test_handling_missing_fields(self):
        data = {"name_i18n": {"en": "Hello"}}
        self.assertEqual(get_i18n_text(data, "unknown_field", "en"), "unknown_field not found")

    def test_handling_empty_or_none_data(self):
        self.assertEqual(get_i18n_text({}, "name", "en"), "name not found (empty data)")
        self.assertEqual(get_i18n_text(None, "name", "en"), "name not found (empty data)")

    def test_i18n_dict_exists_but_no_matching_lang_and_no_plain_field(self):
        data = {"name_i18n": {"fr": "Bonjour"}}
        # lang 'en', default_lang 'es' -> neither in name_i18n. Falls back to first in name_i18n.
        self.assertEqual(get_i18n_text(data, "name", "en", "es"), "Bonjour")
        # If name_i18n was empty, and no plain 'name', it would be "name not found"
        data_empty_i18n = {"name_i18n": {}}
        self.assertEqual(get_i18n_text(data_empty_i18n, "name", "en", "es"), "name not found")

    def test_i18n_field_not_dict_no_plain_field(self):
        data = {"name_i18n": "just a string"}
        self.assertEqual(get_i18n_text(data, "name", "en", "es"), "name not found")

    def test_complex_item_examples(self):
        complex_item = {
            "id": "sword_001",
            "name_i18n": {"en": "Magic Sword", "ru": "Волшебный Меч"},
            "description_i18n": {"en": "A sword pulsing with arcane energy.", "ru": "Меч, пульсирующий тайной энергией."},
            "type": "weapon",
        }
        self.assertEqual(get_i18n_text(complex_item, 'name', 'en', 'ru'), "Magic Sword")
        self.assertEqual(get_i18n_text(complex_item, 'name', 'ru', 'en'), "Волшебный Меч")
        self.assertEqual(get_i18n_text(complex_item, 'name', 'fr', 'en'), "Magic Sword") # Fallback to default_lang 'en'
        self.assertEqual(get_i18n_text(complex_item, 'description', 'ru', 'en'), "Меч, пульсирующий тайной энергией.")
        self.assertEqual(get_i18n_text(complex_item, 'type', 'en', 'ru'), "weapon") # Plain field
        self.assertEqual(get_i18n_text(complex_item, 'color', 'en', 'ru'), "color not found") # Missing field


if __name__ == '__main__':
    unittest.main()
