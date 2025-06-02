import unittest
import os
import json
from unittest.mock import patch, mock_open

# Add parent directory of 'utils' to Python path to allow import
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils import text_utils

class TestTextUtils(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Ensure DATA_DIR in text_utils points to a controlled test data directory
        cls.test_data_dir = os.path.abspath("test_game_data") # Make path absolute
        text_utils.DATA_DIR = cls.test_data_dir # Override DATA_DIR for tests

        if not os.path.exists(cls.test_data_dir):
            os.makedirs(cls.test_data_dir)

        cls.locations_data = {
            "locations": [
                {
                    "id": "loc1",
                    "name_i18n": {"en": "Location 1 EN", "ru": "Локация 1 РУ"},
                    "description_i18n": {"en": "Desc 1 EN", "ru": "Описание 1 РУ"}
                },
                {
                    "id": "loc2",
                    "name_i18n": {"en": "Location 2 EN"}, # No RU version
                    "description_i18n": {"en": "Desc 2 EN"}
                },
                {
                    "id": "loc3_no_default", # No default language (EN)
                    "name_i18n": {"fr": "Location 3 FR"},
                    "description_i18n": {"fr": "Desc 3 FR"}
                }
            ]
        }
        with open(os.path.join(cls.test_data_dir, "locations.descriptions_i18n.json"), 'w', encoding='utf-8') as f:
            json.dump(cls.locations_data, f)

        cls.lore_data = {
            "lore_entries": [
                {
                    "id": "lore1",
                    "title_i18n": {"en": "Lore 1 Title EN", "ru": "Заголовок Лора 1 РУ"},
                    "text_i18n": {"en": "Lore 1 Text EN", "ru": "Текст Лора 1 РУ"}
                },
                {
                    "id": "lore2",
                    "title_i18n": {"en": "Lore 2 Title EN"}, # No RU
                    "text_i18n": {"en": "Lore 2 Text EN"}
                }
            ]
        }
        with open(os.path.join(cls.test_data_dir, "lore_i18n.json"), 'w', encoding='utf-8') as f:
            json.dump(cls.lore_data, f)

        cls.map_data = {
            "map": [
                {
                    "location_id": "loc1",
                    "connections": [
                        {
                            "to_location_id": "loc2",
                            "direction": "north",
                            "description_i18n": {"en": "Path to Loc2 EN", "ru": "Путь к Лок2 РУ"}
                        }
                    ]
                },
                {
                    "location_id": "loc2",
                    "connections": [
                         {
                            "to_location_id": "loc1",
                            "direction": "south",
                            "description_i18n": {"en": "Path to Loc1 EN"} # No RU
                        }
                    ]
                }
            ]
        }
        with open(os.path.join(cls.test_data_dir, "world_map.json"), 'w', encoding='utf-8') as f:
            json.dump(cls.map_data, f)
            
        # Reset caches before each test method group if necessary (or do it in setUp)
        text_utils._location_descriptions_cache = None
        text_utils._lore_entries_cache = None
        text_utils._world_map_cache = None


    @classmethod
    def tearDownClass(cls):
        # Clean up test files and directory
        os.remove(os.path.join(cls.test_data_dir, "locations.descriptions_i18n.json"))
        os.remove(os.path.join(cls.test_data_dir, "lore_i18n.json"))
        os.remove(os.path.join(cls.test_data_dir, "world_map.json"))
        if not os.listdir(cls.test_data_dir): # Check if directory is empty after removing files
             os.rmdir(cls.test_data_dir)
        # Restore original DATA_DIR if it was changed by other modules/tests
        text_utils.DATA_DIR = "game_data"


    def setUp(self):
        # Reset caches before each test to ensure test isolation
        text_utils._location_descriptions_cache = None
        text_utils._lore_entries_cache = None
        text_utils._world_map_cache = None
        # Ensure DEFAULT_LANGUAGE is as expected for tests
        text_utils.DEFAULT_LANGUAGE = "en"


    def test_get_location_name(self):
        self.assertEqual(text_utils.get_location_name("loc1", "en"), "Location 1 EN")
        self.assertEqual(text_utils.get_location_name("loc1", "ru"), "Локация 1 РУ")
        # Test fallback
        self.assertEqual(text_utils.get_location_name("loc2", "ru"), "Location 2 EN")
        # Test missing ID
        self.assertEqual(text_utils.get_location_name("nonexistent", "en"), "Error: Location ID not found.")
        # Test missing default language
        self.assertEqual(text_utils.get_location_name("loc3_no_default", "es"), "Error: No name found for this location in any language.")

    def test_get_location_description(self):
        self.assertEqual(text_utils.get_location_description("loc1", "en"), "Desc 1 EN")
        self.assertEqual(text_utils.get_location_description("loc1", "ru"), "Описание 1 РУ")
        # Test fallback
        self.assertEqual(text_utils.get_location_description("loc2", "ru"), "Desc 2 EN")
        # Test missing ID
        self.assertEqual(text_utils.get_location_description("nonexistent", "en"), "Error: Location ID not found.")
        # Test missing default language
        self.assertEqual(text_utils.get_location_description("loc3_no_default", "es"), "Error: No description found for this location in any language.")

    def test_get_lore_text(self):
        title, text = text_utils.get_lore_text("lore1", "en")
        self.assertEqual(title, "Lore 1 Title EN")
        self.assertEqual(text, "Lore 1 Text EN")

        title, text = text_utils.get_lore_text("lore1", "ru")
        self.assertEqual(title, "Заголовок Лора 1 РУ")
        self.assertEqual(text, "Текст Лора 1 РУ")

        # Test fallback
        title, text = text_utils.get_lore_text("lore2", "ru")
        self.assertEqual(title, "Lore 2 Title EN")
        self.assertEqual(text, "Lore 2 Text EN")

        # Test missing ID
        title, text = text_utils.get_lore_text("nonexistent", "en")
        self.assertEqual(title, "Error: Lore ID not found.")
        self.assertIsNone(text)

    def test_get_connection_description(self):
        self.assertEqual(text_utils.get_connection_description("loc1", "loc2", "en"), "Path to Loc2 EN")
        self.assertEqual(text_utils.get_connection_description("loc1", "loc2", "ru"), "Путь к Лок2 РУ")
        # Test fallback
        self.assertEqual(text_utils.get_connection_description("loc2", "loc1", "ru"), "Path to Loc1 EN")
        # Test missing connection
        self.assertEqual(text_utils.get_connection_description("loc1", "nonexistent_target", "en"), "Error: Target connection not found from this location.")
        # Test missing origin location
        self.assertEqual(text_utils.get_connection_description("nonexistent_origin", "loc1", "en"), "Error: Origin location ID not found in map.")

    def test_file_not_found(self):
        # Temporarily point to a non-existent file
        original_data_dir = text_utils.DATA_DIR
        text_utils.DATA_DIR = "non_existent_dir_for_test"
        text_utils._location_descriptions_cache = None # Clear cache

        # Suppress print output during this specific test for cleaner test logs
        with patch('builtins.print') as mocked_print:
            self.assertEqual(text_utils.get_location_name("loc1", "en"), "Error: Location names not loaded.") # Corrected expected message
            mocked_print.assert_any_call(f"Error: Data file not found at {os.path.join('non_existent_dir_for_test', 'locations.descriptions_i18n.json')}")
        
        text_utils.DATA_DIR = original_data_dir # Restore

    def test_json_decode_error(self):
        # Create a malformed JSON file
        malformed_json_path = os.path.join(self.test_data_dir, "malformed_locations.json") # Use self.test_data_dir
        with open(malformed_json_path, 'w') as f:
            f.write("{'locations': [}") # Invalid JSON

        text_utils._location_descriptions_cache = None # Clear cache
        
        # This test had a bug. get_location_name does not accept _filename_override
        # We need to call _load_json_data directly or modify get_location_name
        # For now, calling _load_json_data directly for this specific test.
        with patch('builtins.print') as mocked_print:
            result = text_utils._load_json_data("malformed_locations.json")
            self.assertIsNone(result)
            mocked_print.assert_any_call(f"Error: Could not decode JSON from {malformed_json_path}")

        # Clean up malformed file
        os.remove(malformed_json_path)


if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
