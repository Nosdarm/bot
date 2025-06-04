import unittest
import json
import os
import shutil # For robust directory cleanup
import sys
from typing import Dict, Any, Optional

# Add project root to sys.path for imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from bot.game.managers.lore_manager import LoreManager, DEFAULT_LORE_FILE
from bot.game.models.lore import LoreEntry # For type hinting and direct use if needed

# Define a path for temporary test data
TEST_DATA_DIR = os.path.join(project_root, "tests", "temp_test_data")
CUSTOM_LORE_FILE_NAME = "test_lore_data.json"
CUSTOM_LORE_FILE_PATH = os.path.join(TEST_DATA_DIR, CUSTOM_LORE_FILE_NAME)

class TestLoreManager(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Create the temporary directory for test files if it doesn't exist."""
        if not os.path.exists(TEST_DATA_DIR):
            os.makedirs(TEST_DATA_DIR)

    @classmethod
    def tearDownClass(cls):
        """Remove the temporary directory after all tests."""
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)

    def _write_dummy_lore_file(self, data: list, file_path: str = CUSTOM_LORE_FILE_PATH):
        """Helper to write data to the dummy lore file."""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def setUp(self):
        """Set up for each test method."""
        # Ensure the specific test lore file is clean before each test
        if os.path.exists(CUSTOM_LORE_FILE_PATH):
            os.remove(CUSTOM_LORE_FILE_PATH)

        self.dummy_lore_data = [
            {
                "id": "entry1",
                "title_i18n": {"en": "Title 1 EN", "fr": "Titre 1 FR"},
                "text_i18n": {"en": "Text 1 EN", "fr": "Texte 1 FR"}
            },
            {
                "id": "entry2",
                "title_i18n": {"en": "Title 2 EN"},
                "text_i18n": {"en": "Text 2 EN", "de": "Text 2 DE"}
            },
            {
                "id": "entry_malformed_no_text", # Valid from_dict if text_i18n is optional or defaults
                "title_i18n": {"en": "Malformed Title"}
                # LoreEntry expects text_i18n, so this would need text_i18n: {} to be valid by current model
            }
        ]
        # Correcting entry_malformed_no_text for current LoreEntry model
        self.dummy_lore_data[2]["text_i18n"] = {"en":"Default text for malformed"}


        self.mock_settings = {'lore_file_path': CUSTOM_LORE_FILE_PATH}
        # We don't pass a real db_adapter for these file-based tests
        self.lore_manager_instance: Optional[LoreManager] = None


    def test_load_lore_from_file_success(self):
        self._write_dummy_lore_file(self.dummy_lore_data)
        self.lore_manager_instance = LoreManager(settings=self.mock_settings, db_adapter=None)
        self.assertEqual(len(self.lore_manager_instance._lore_entries), 3)
        entry1 = self.lore_manager_instance.get_lore_entry("entry1")
        self.assertIsNotNone(entry1)
        self.assertEqual(entry1.id, "entry1")
        self.assertEqual(entry1.title_i18n.get("fr"), "Titre 1 FR")

    def test_load_lore_from_non_existent_file(self):
        # Ensure file does not exist
        if os.path.exists(CUSTOM_LORE_FILE_PATH):
            os.remove(CUSTOM_LORE_FILE_PATH)

        # LoreManager constructor calls load_lore_from_file.
        # It should create a dummy file if the specified one doesn't exist.
        self.lore_manager_instance = LoreManager(settings=self.mock_settings, db_adapter=None)
        self.assertEqual(len(self.lore_manager_instance._lore_entries), 0)
        self.assertTrue(os.path.exists(CUSTOM_LORE_FILE_PATH)) # Check dummy file creation
        with open(CUSTOM_LORE_FILE_PATH, 'r') as f:
            content = json.load(f)
            self.assertEqual(content, []) # Dummy file should be an empty list

    def test_load_lore_from_empty_json_list_file(self):
        self._write_dummy_lore_file([]) # Write an empty list
        self.lore_manager_instance = LoreManager(settings=self.mock_settings, db_adapter=None)
        self.assertEqual(len(self.lore_manager_instance._lore_entries), 0)

    def test_load_lore_from_malformed_json_file(self):
        # Write a file that is not a valid JSON
        with open(CUSTOM_LORE_FILE_PATH, 'w', encoding='utf-8') as f:
            f.write("this is not json {")

        self.lore_manager_instance = LoreManager(settings=self.mock_settings, db_adapter=None)
        self.assertEqual(len(self.lore_manager_instance._lore_entries), 0)
        # The file itself might still exist but be empty or in its malformed state.
        # LoreManager's load method should handle the JSONDecodeError gracefully.

    def test_load_lore_from_json_not_a_list(self):
        self._write_dummy_lore_file({"not": "a list"}) # Write a JSON object instead of list
        self.lore_manager_instance = LoreManager(settings=self.mock_settings, db_adapter=None)
        self.assertEqual(len(self.lore_manager_instance._lore_entries), 0)

    def test_get_lore_entry(self):
        self._write_dummy_lore_file(self.dummy_lore_data)
        self.lore_manager_instance = LoreManager(settings=self.mock_settings, db_adapter=None)

        entry1 = self.lore_manager_instance.get_lore_entry("entry1")
        self.assertIsNotNone(entry1)
        self.assertEqual(entry1.id, "entry1")

        non_existent_entry = self.lore_manager_instance.get_lore_entry("non_existent_id")
        self.assertIsNone(non_existent_entry)

    def test_get_lore_title(self):
        self._write_dummy_lore_file(self.dummy_lore_data)
        manager = LoreManager(settings=self.mock_settings, db_adapter=None)

        # Primary language
        self.assertEqual(manager.get_lore_title("entry1", "en", "fr"), "Title 1 EN")
        self.assertEqual(manager.get_lore_title("entry1", "fr", "en"), "Titre 1 FR")

        # Fallback to default language
        self.assertEqual(manager.get_lore_title("entry1", "de", "en"), "Title 1 EN") # de missing, fallback to en
        self.assertEqual(manager.get_lore_title("entry2", "fr", "en"), "Title 2 EN") # fr missing, fallback to en

        # Fallback to first available (if primary and default missing)
        # entry2 has {"en": "Title 2 EN"}. Request "it", default "es". Should give "Title 2 EN".
        self.assertEqual(manager.get_lore_title("entry2", "it", "es"), "Title 2 EN")

        # Non-existent entry
        self.assertIn("not found", manager.get_lore_title("non_existent_id", "en"))

    def test_get_lore_text(self):
        self._write_dummy_lore_file(self.dummy_lore_data)
        manager = LoreManager(settings=self.mock_settings, db_adapter=None)

        # Primary language
        self.assertEqual(manager.get_lore_text("entry1", "en", "fr"), "Text 1 EN")
        self.assertEqual(manager.get_lore_text("entry1", "fr", "en"), "Texte 1 FR")

        # Fallback to default language
        self.assertEqual(manager.get_lore_text("entry2", "fr", "en"), "Text 2 EN") # fr missing, fallback to en
        self.assertEqual(manager.get_lore_text("entry2", "es", "de"), "Text 2 DE") # es missing, fallback to de (default)

        # Fallback to first available
        # entry2 has {"en": "Text 2 EN", "de": "Text 2 DE"}. Request "it", default "es". Should give "Text 2 EN" or "Text 2 DE".
        self.assertIn(manager.get_lore_text("entry2", "it", "es"), ["Text 2 EN", "Text 2 DE"])

        # Non-existent entry
        self.assertIn("not found", manager.get_lore_text("non_existent_id", "en"))

    def test_persistence_hooks_noop(self):
        """Test that persistence hooks run without error (they are no-ops for file-based manager)."""
        self._write_dummy_lore_file(self.dummy_lore_data)
        manager = LoreManager(settings=self.mock_settings, db_adapter=None)
        initial_count = len(manager._lore_entries)

        # These are async methods in LoreManager
        async def run_async_hooks():
            await manager.load_state(data={}) # Should reload from file
            self.assertEqual(len(manager._lore_entries), initial_count)

            saved_state = await manager.save_state()
            self.assertEqual(saved_state.get("lore_file_path"), CUSTOM_LORE_FILE_PATH)

            await manager.rebuild_runtime_caches() # Should reload from file
            self.assertEqual(len(manager._lore_entries), initial_count)

        import asyncio
        asyncio.run(run_async_hooks())


if __name__ == '__main__':
    unittest.main()
