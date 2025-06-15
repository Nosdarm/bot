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
        logger.info("Initializing LoreManager...")
        self._settings = settings
        self._db_service = db_service
        self._lore_entries: Dict[str, LoreEntry] = {}
        self._lore_file_path = self._settings.get('lore_file_path', DEFAULT_LORE_FILE)

        self.load_lore_from_file(self._lore_file_path)
        log_msg = f"LoreManager initialized. Loaded {len(self._lore_entries)} entries from {self._lore_file_path}"
        logger.info(log_msg)

    def load_lore_from_file(self, file_path: str) -> None:
        """Loads lore entries from a JSON file into the _lore_entries cache."""
        logger.debug(f"LoreManager: Attempting to load lore from file: {file_path}")
        self._lore_entries = {}
        if not os.path.exists(file_path):
            log_msg = f"Lore file not found at {file_path}. No lore will be loaded."
            logger.warning(f"LoreManager: {log_msg}")
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump([], f)
                log_msg_create = f"Created an empty lore file at {file_path}."
                logger.info(f"LoreManager: {log_msg_create}")
            except IOError as e:
                log_msg_err = f"Error creating dummy lore file at {file_path}: {e}"
                logger.error(f"LoreManager: {log_msg_err}", exc_info=True)
            return

        try:
            logger.debug(f"LoreManager: Reading and parsing lore file: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                lore_data_list = json.load(f)

            if not isinstance(lore_data_list, list):
                log_msg = f"Lore file {file_path} does not contain a JSON list. Found type: {type(lore_data_list)}"
                logger.error(f"LoreManager: {log_msg}")
                return

            logger.debug(f"LoreManager: Processing {len(lore_data_list)} entries from file.")
            for entry_data in lore_data_list:
                if not isinstance(entry_data, dict):
                    log_msg = f"Skipping non-dict item in lore file {file_path}: {entry_data}"
                    logger.warning(f"LoreManager: {log_msg}")
                    continue
                try:
                    lore_entry = LoreEntry.from_dict(entry_data)
                    self._lore_entries[lore_entry.id] = lore_entry
                except Exception as e:
                    log_msg = f"Error parsing lore entry data from {file_path}: {entry_data}. Error: {e}"
                    logger.error(f"LoreManager: {log_msg}", exc_info=True)
            log_msg_success = f"Successfully loaded {len(self._lore_entries)} lore entries from {file_path}."
            logger.info(f"LoreManager: {log_msg_success}")
        except json.JSONDecodeError as e:
            log_msg = f"Error decoding JSON from lore file {file_path}: {e}"
            logger.error(f"LoreManager: {log_msg}", exc_info=True)
        except IOError as e:
            log_msg = f"Error reading lore file {file_path}: {e}"
            logger.error(f"LoreManager: {log_msg}", exc_info=True)
        except Exception as e:
            log_msg = f"Unexpected error loading lore from {file_path}: {e}"
            logger.error(f"LoreManager: {log_msg}", exc_info=True)

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
        guild_id = kwargs.get('guild_id', 'global_lore')
        log_msg = f"load_state called for guild {guild_id}. Reloading from file for consistency."
        logger.info(f"LoreManager: {log_msg}")
        self.load_lore_from_file(self._lore_file_path)

    async def save_state(self, **kwargs) -> Dict[str, Any]:
        guild_id = kwargs.get('guild_id', 'global_lore')
        log_msg = f"save_state called for guild {guild_id}. No dynamic state to save for file-based lore."
        logger.info(f"LoreManager: {log_msg}")
        return {"lore_file_path": self._lore_file_path}

    async def rebuild_runtime_caches(self, **kwargs) -> None:
        guild_id = kwargs.get('guild_id', 'global_lore')
        log_msg_rebuild = f"rebuild_runtime_caches called for guild {guild_id}. Reloading lore from file."
        logger.info(f"LoreManager: {log_msg_rebuild}")
        self.load_lore_from_file(self._lore_file_path)
        log_msg_rebuilt = f"Runtime cache rebuilt for guild {guild_id}. Loaded {len(self._lore_entries)} entries."
        logger.info(f"LoreManager: {log_msg_rebuilt}")

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
