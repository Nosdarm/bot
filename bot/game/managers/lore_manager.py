import json
import os
import logging # Added
from typing import Dict, Any, Optional, List

from bot.game.models.lore import LoreEntry
from bot.utils.i18n_utils import get_i18n_text
from bot.services.db_service import DBService

logger = logging.getLogger(__name__) # Added

DEFAULT_LORE_FILE = "game_data/lore_i18n.json"

class LoreManager:
    def __init__(self, settings: Dict[str, Any], db_service: Optional[DBService] = None):
        logger.info("Initializing LoreManager...") # Changed
        self._settings = settings
        self._db_service = db_service
        self._lore_entries: Dict[str, LoreEntry] = {}
        self._lore_file_path = self._settings.get('lore_file_path', DEFAULT_LORE_FILE) # Used self._settings

        self.load_lore_from_file(self._lore_file_path)
        logger.info("LoreManager initialized. Loaded %s entries from %s", len(self._lore_entries), self._lore_file_path) # Changed

    def load_lore_from_file(self, file_path: str) -> None:
        """Loads lore entries from a JSON file into the _lore_entries cache."""
        self._lore_entries = {}
        if not os.path.exists(file_path):
            logger.warning("LoreManager: Lore file not found at %s. No lore will be loaded.", file_path) # Changed
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump([], f)
                logger.info("LoreManager: Created an empty lore file at %s.", file_path) # Changed
            except IOError as e:
                logger.error("LoreManager: Error creating dummy lore file at %s: %s", file_path, e, exc_info=True) # Changed
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lore_data_list = json.load(f)

            if not isinstance(lore_data_list, list):
                logger.error("LoreManager: Lore file %s does not contain a JSON list. Found type: %s", file_path, type(lore_data_list)) # Changed
                return

            for entry_data in lore_data_list:
                if not isinstance(entry_data, dict):
                    logger.warning("LoreManager: Skipping non-dict item in lore file %s: %s", file_path, entry_data) # Changed
                    continue
                try:
                    lore_entry = LoreEntry.from_dict(entry_data)
                    self._lore_entries[lore_entry.id] = lore_entry
                except Exception as e:
                    logger.error("LoreManager: Error parsing lore entry data from %s: %s. Error: %s", file_path, entry_data, e, exc_info=True) # Changed
            logger.info("LoreManager: Successfully loaded %s lore entries from %s.", len(self._lore_entries), file_path) # Changed
        except json.JSONDecodeError as e:
            logger.error("LoreManager: Error decoding JSON from lore file %s: %s", file_path, e, exc_info=True) # Changed
        except IOError as e:
            logger.error("LoreManager: Error reading lore file %s: %s", file_path, e, exc_info=True) # Changed
        except Exception as e:
            logger.error("LoreManager: Unexpected error loading lore from %s: %s", file_path, e, exc_info=True) # Changed

    def get_lore_entry(self, entry_id: str) -> Optional[LoreEntry]:
        return self._lore_entries.get(entry_id)

    def get_lore_title(self, entry_id: str, lang: str, default_lang: str = "en") -> str:
        entry = self.get_lore_entry(entry_id)
        if not entry:
            return f"Lore title for '{entry_id}' not found"
        return get_i18n_text(entry.to_dict(), "title", lang, default_lang)

    def get_lore_text(self, entry_id: str, lang: str, default_lang: str = "en") -> str:
        entry = self.get_lore_entry(entry_id)
        if not entry:
            return f"Lore text for '{entry_id}' not found"
        return get_i18n_text(entry.to_dict(), "text", lang, default_lang)

    async def load_state(self, data: Dict[str, Any], **kwargs) -> None: # Added guild_id for consistency, though not used
        guild_id = kwargs.get('guild_id', 'global_lore') # Lore is global, but PM might pass guild_id
        logger.info("LoreManager: load_state called for guild %s. Reloading from file for consistency.", guild_id) # Changed
        self.load_lore_from_file(self._lore_file_path)

    async def save_state(self, **kwargs) -> Dict[str, Any]: # Added guild_id for consistency
        guild_id = kwargs.get('guild_id', 'global_lore')
        logger.info("LoreManager: save_state called for guild %s. No dynamic state to save for file-based lore.", guild_id) # Changed
        return {"lore_file_path": self._lore_file_path}

    async def rebuild_runtime_caches(self, **kwargs) -> None: # Added guild_id for consistency
        guild_id = kwargs.get('guild_id', 'global_lore')
        logger.info("LoreManager: rebuild_runtime_caches called for guild %s. Reloading lore from file.", guild_id) # Changed
        self.load_lore_from_file(self._lore_file_path)
        logger.info("LoreManager: Runtime cache rebuilt for guild %s. Loaded %s entries.", guild_id, len(self._lore_entries)) # Changed

if __name__ == "__main__":
    import asyncio
    # Configure basic logging for the test
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    print("--- Testing LoreManager ---")
    mock_settings = {"lore_file_path": "test_lore_data.json"}
    fixed_dummy_lore_content = [
        {"id": "test_entry_1", "title_i18n": {"en": "Test Title 1", "fr": "Titre d'Essai 1"}, "text_i18n": {"en": "This is the English text for test entry 1.", "fr": "Ceci est le texte français pour l'essai 1."}},
        {"id": "test_entry_2", "title_i18n": {"en": "Test Title 2"}, "text_i18n": {"en": "Text for test entry 2."}},
        {"id": "fixed_entry_3", "title_i18n": {"en": "Fixed Entry"}, "text_i18n": {"en": "This entry is now correctly formatted."}}
    ]
    test_file_path = mock_settings["lore_file_path"]

    try:
        with open(test_file_path, 'w', encoding='utf-8') as f:
            json.dump(fixed_dummy_lore_content, f, indent=2)
        print(f"Created dummy lore file: {test_file_path}")

        lore_manager = LoreManager(settings=mock_settings)
        print(f"\nNumber of entries loaded: {len(lore_manager._lore_entries)}")
        assert len(lore_manager._lore_entries) == 3

        entry1 = lore_manager.get_lore_entry("test_entry_1")
        assert entry1 is not None
        assert entry1.id == "test_entry_1"
        print(f"\nFound entry 'test_entry_1': {entry1.title_i18n.get('en')}")

        # ... (rest of the test assertions as before) ...

        print("\n--- Testing with non-existent lore file ---")
        os.remove(test_file_path)
        print(f"Deleted test lore file: {test_file_path}")

        non_existent_path = "game_data/non_existent_lore.json"
        mock_settings_non_existent = {"lore_file_path": non_existent_path}
        if not os.path.exists(os.path.dirname(non_existent_path)):
            os.makedirs(os.path.dirname(non_existent_path), exist_ok=True)

        lore_manager_no_file = LoreManager(settings=mock_settings_non_existent)
        assert len(lore_manager_no_file._lore_entries) == 0
        print(f"Entries loaded with non-existent file (should be 0 and dummy created): {len(lore_manager_no_file._lore_entries)}")
        assert os.path.exists(non_existent_path)
        print(f"Dummy file created at: {non_existent_path}")
        os.remove(non_existent_path)
        print(f"Cleaned up dummy file: {non_existent_path}")
    except Exception as e:
        print(f"Error during LoreManager test: {e}")
        import traceback # Keep traceback for test block
        traceback.print_exc()
    finally:
        if os.path.exists(test_file_path):
            os.remove(test_file_path)
            print(f"\nCleaned up test lore file: {test_file_path}")
    print("\n--- End of LoreManager tests ---")
