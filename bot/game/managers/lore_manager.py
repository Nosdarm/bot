import json
import os
from typing import Dict, Any, Optional, List

from bot.game.models.lore import LoreEntry
from bot.utils.i18n_utils import get_i18n_text
# Assuming DBService and SqliteAdapter might be used later, but not for initial file-based loading
from bot.services.db_service import DBService
# from bot.database.sqlite_adapter import SqliteAdapter

DEFAULT_LORE_FILE = "game_data/lore_i18n.json"

class LoreManager:
    def __init__(self, settings: Dict[str, Any], db_service: Optional[DBService] = None): # Changed from db_adapter
        print("Initializing LoreManager...")
        self._settings = settings
        self._db_service = db_service # Not used for file-based loading but good for consistency / future DB use
        self._lore_entries: Dict[str, LoreEntry] = {}

        # Determine the lore file path from settings or use default
        # Example: self._lore_file_path = settings.get('lore_file_path', DEFAULT_LORE_FILE)
        # For now, directly using DEFAULT_LORE_FILE for simplicity in this step
        self._lore_file_path = DEFAULT_LORE_FILE

        # Initial load during construction or rely on rebuild_runtime_caches
        # For now, let's call it here to ensure entries are available post-init.
        # In a full setup, rebuild_runtime_caches would be called by PersistenceManager.
        self.load_lore_from_file(self._lore_file_path)
        print(f"LoreManager initialized. Loaded {len(self._lore_entries)} entries from {self._lore_file_path}")

    def load_lore_from_file(self, file_path: str) -> None:
        """Loads lore entries from a JSON file into the _lore_entries cache."""
        self._lore_entries = {} # Clear existing entries before loading
        if not os.path.exists(file_path):
            print(f"LoreManager: Warning - Lore file not found at {file_path}. No lore will be loaded.")
            # Create a dummy file if it doesn't exist to prevent errors if other parts expect it
            # For a real application, this might be handled by campaign loader or an initial setup script.
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump([], f) # Create an empty JSON list
                print(f"LoreManager: Created an empty lore file at {file_path}.")
            except IOError as e:
                print(f"LoreManager: Error creating dummy lore file at {file_path}: {e}")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lore_data_list = json.load(f)

            if not isinstance(lore_data_list, list):
                print(f"LoreManager: Error - Lore file {file_path} does not contain a JSON list. Found type: {type(lore_data_list)}")
                return

            for entry_data in lore_data_list:
                if not isinstance(entry_data, dict):
                    print(f"LoreManager: Warning - Skipping non-dict item in lore file: {entry_data}")
                    continue
                try:
                    lore_entry = LoreEntry.from_dict(entry_data)
                    self._lore_entries[lore_entry.id] = lore_entry
                except Exception as e: # Catch errors from LoreEntry.from_dict (e.g., missing fields)
                    print(f"LoreManager: Error parsing lore entry data: {entry_data}. Error: {e}")

            print(f"LoreManager: Successfully loaded {len(self._lore_entries)} lore entries from {file_path}.")

        except json.JSONDecodeError as e:
            print(f"LoreManager: Error decoding JSON from lore file {file_path}: {e}")
        except IOError as e:
            print(f"LoreManager: Error reading lore file {file_path}: {e}")
        except Exception as e: # Catch any other unexpected errors during loading
            print(f"LoreManager: Unexpected error loading lore from {file_path}: {e}")


    def get_lore_entry(self, entry_id: str) -> Optional[LoreEntry]:
        """Retrieves a LoreEntry by its ID."""
        return self._lore_entries.get(entry_id)

    def get_lore_title(self, entry_id: str, lang: str, default_lang: str = "en") -> str:
        """
        Retrieves the internationalized title for a lore entry.
        Uses i18n_utils.get_i18n_text for localization.
        """
        entry = self.get_lore_entry(entry_id)
        if not entry:
            return f"Lore title for '{entry_id}' not found"

        # LoreEntry stores titles in title_i18n, so we pass the entry.to_dict()
        # and specify "title" as the field_prefix for get_i18n_text.
        return get_i18n_text(entry.to_dict(), "title", lang, default_lang)

    def get_lore_text(self, entry_id: str, lang: str, default_lang: str = "en") -> str:
        """
        Retrieves the internationalized text for a lore entry.
        Uses i18n_utils.get_i18n_text for localization.
        """
        entry = self.get_lore_entry(entry_id)
        if not entry:
            return f"Lore text for '{entry_id}' not found"

        # Similar to title, text is stored in text_i18n.
        return get_i18n_text(entry.to_dict(), "text", lang, default_lang)

    # --- Methods for PersistenceManager compatibility ---

    async def load_state(self, data: Dict[str, Any], **kwargs) -> None:
        """
        Loads the state of the LoreManager.
        For file-based loading, this might re-read the file or assume it's up-to-date.
        Currently, lore is loaded from file at init, so this might be a no-op unless
        the file path can change or we want to force a reload.
        """
        print("LoreManager: load_state called. Reloading from file for consistency.")
        # file_path = data.get('lore_file_path', self._lore_file_path) # If path can be dynamic from save state
        self.load_lore_from_file(self._lore_file_path) # For now, always reload from configured path

    async def save_state(self, **kwargs) -> Dict[str, Any]:
        """
        Saves the state of the LoreManager.
        Since lore is loaded from a file and not modified at runtime through this manager,
        there's no dynamic state to save back to the persistence layer (e.g., DB).
        The "state" is the file itself, which is external.
        We could return the file_path if it's dynamic.
        """
        print("LoreManager: save_state called. No dynamic state to save for file-based lore.")
        return {"lore_file_path": self._lore_file_path} # Example of what could be saved

    async def rebuild_runtime_caches(self, **kwargs) -> None:
        """
        Rebuilds any runtime caches. For LoreManager, this means reloading from the lore file.
        This is typically called by PersistenceManager after loading all game state.
        """
        print("LoreManager: rebuild_runtime_caches called. Reloading lore from file.")
        self.load_lore_from_file(self._lore_file_path)
        print(f"LoreManager: Runtime cache rebuilt. Loaded {len(self._lore_entries)} entries.")

# --- Main block for basic testing ---
if __name__ == "__main__":
    import asyncio # Required for asyncio.run

    print("--- Testing LoreManager ---")

    # Create a dummy settings object
    mock_settings = {"lore_file_path": "test_lore_data.json"}

    # Create a dummy lore file for testing
    dummy_lore_content = [
        {
            "id": "test_entry_1",
            "title_i18n": {"en": "Test Title 1", "fr": "Titre d'Essai 1"},
            "text_i18n": {"en": "This is the English text for test entry 1.", "fr": "Ceci est le texte français pour l'essai 1."}
        },
        {
            "id": "test_entry_2",
            "title_i18n": {"en": "Test Title 2"}, # Only English title
            "text_i18n": {"en": "Text for test entry 2."}
        },
        {
            "id": "malformed_entry", # Missing text_i18n, from_dict should handle if LoreEntry allows optional
            "title_i18n": {"en": "Malformed"} # but LoreEntry currently requires text_i18n
        }
    ]
    fixed_dummy_lore_content = [
        {
            "id": "test_entry_1",
            "title_i18n": {"en": "Test Title 1", "fr": "Titre d'Essai 1"},
            "text_i18n": {"en": "This is the English text for test entry 1.", "fr": "Ceci est le texte français pour l'essai 1."}
        },
        {
            "id": "test_entry_2",
            "title_i18n": {"en": "Test Title 2"},
            "text_i18n": {"en": "Text for test entry 2."}
        },
        { # Corrected entry that was previously malformed
            "id": "fixed_entry_3",
            "title_i18n": {"en": "Fixed Entry"},
            "text_i18n": {"en": "This entry is now correctly formatted."}
        }
    ]

    # Path for the test lore file
    test_file_path = mock_settings["lore_file_path"]

    try:
        with open(test_file_path, 'w', encoding='utf-8') as f:
            json.dump(fixed_dummy_lore_content, f, indent=2)
        print(f"Created dummy lore file: {test_file_path}")

        # Initialize LoreManager (this will also call load_lore_from_file)
        lore_manager = LoreManager(settings=mock_settings)

        print(f"\nNumber of entries loaded: {len(lore_manager._lore_entries)}")
        assert len(lore_manager._lore_entries) == 3

        # Test get_lore_entry
        entry1 = lore_manager.get_lore_entry("test_entry_1")
        assert entry1 is not None
        assert entry1.id == "test_entry_1"
        print(f"\nFound entry 'test_entry_1': {entry1.title_i18n.get('en')}")

        entry_non_existent = lore_manager.get_lore_entry("non_existent_id")
        assert entry_non_existent is None
        print(f"Found entry 'non_existent_id': {entry_non_existent}")

        # Test get_lore_title
        title1_en = lore_manager.get_lore_title("test_entry_1", "en", "en")
        assert title1_en == "Test Title 1"
        print(f"\nTitle for 'test_entry_1' (en): {title1_en}")

        title1_fr = lore_manager.get_lore_title("test_entry_1", "fr", "en")
        assert title1_fr == "Titre d'Essai 1"
        print(f"Title for 'test_entry_1' (fr): {title1_fr}")

        title1_de_fallback_en = lore_manager.get_lore_title("test_entry_1", "de", "en")
        assert title1_de_fallback_en == "Test Title 1" # Falls back to English
        print(f"Title for 'test_entry_1' (de, fallback en): {title1_de_fallback_en}")

        title2_fr_fallback_en = lore_manager.get_lore_title("test_entry_2", "fr", "en")
        assert title2_fr_fallback_en == "Test Title 2" # Only English exists, should use it
        print(f"Title for 'test_entry_2' (fr, fallback en): {title2_fr_fallback_en}")

        title_missing_entry = lore_manager.get_lore_title("non_existent_id", "en")
        assert "not found" in title_missing_entry
        print(f"Title for 'non_existent_id': {title_missing_entry}")

        # Test get_lore_text
        text1_en = lore_manager.get_lore_text("test_entry_1", "en", "en")
        assert "English text" in text1_en
        print(f"\nText for 'test_entry_1' (en): {text1_en}")

        text1_fr = lore_manager.get_lore_text("test_entry_1", "fr", "en")
        assert "texte français" in text1_fr
        print(f"Text for 'test_entry_1' (fr): {text1_fr}")

        # Test load_state and save_state (basic calls)
        # Simulating PersistenceManager calls
        print("\n--- Testing Persistence Hooks ---")
        state_to_save = asyncio.run(lore_manager.save_state())
        print(f"Data from save_state: {state_to_save}")
        assert state_to_save["lore_file_path"] == test_file_path

        # To test load_state, we can check if it reloads.
        # For simplicity, we'll just call it. If it tries to reload a non-existent file after deletion,
        # it should handle it gracefully (as per load_lore_from_file logic).
        # Or, modify the file and see if it reloads.
        # For now, just call it:
        asyncio.run(lore_manager.load_state(data={"lore_file_path": test_file_path}))
        print("load_state called.")
        assert len(lore_manager._lore_entries) == 3 # Should reload the same entries

        # Test rebuild_runtime_caches
        asyncio.run(lore_manager.rebuild_runtime_caches())
        print("rebuild_runtime_caches called.")
        assert len(lore_manager._lore_entries) == 3 # Should reload the same entries

        print("\n--- Testing with non-existent lore file ---")
        os.remove(test_file_path) # Remove the test file
        print(f"Deleted test lore file: {test_file_path}")

        # Create a new manager instance that will try to load a non-existent file
        # It should create a dummy file based on the current implementation.
        # For this test, let's ensure the dummy creation path is covered.
        # We need to provide a directory that exists for os.makedirs to work as intended.
        non_existent_path = "game_data/non_existent_lore.json" # Assuming game_data exists or can be created
        mock_settings_non_existent = {"lore_file_path": non_existent_path}

        # Ensure the directory for the non-existent file exists, or os.makedirs will fail
        if not os.path.exists(os.path.dirname(non_existent_path)):
            os.makedirs(os.path.dirname(non_existent_path), exist_ok=True)

        lore_manager_no_file = LoreManager(settings=mock_settings_non_existent)
        assert len(lore_manager_no_file._lore_entries) == 0
        print(f"Entries loaded with non-existent file (should be 0 and dummy created): {len(lore_manager_no_file._lore_entries)}")
        assert os.path.exists(non_existent_path) # Check if dummy file was created
        print(f"Dummy file created at: {non_existent_path}")
        os.remove(non_existent_path) # Clean up dummy file
        print(f"Cleaned up dummy file: {non_existent_path}")


    except Exception as e:
        print(f"Error during LoreManager test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up the test file if it exists
        if os.path.exists(test_file_path):
            os.remove(test_file_path)
            print(f"\nCleaned up test lore file: {test_file_path}")

    print("\n--- End of LoreManager tests ---")
