# bot/services/config_service.py
import json
from typing import Optional, Any, Dict

class ConfigService:
    """
    Service for reading configuration data from a JSON file.
    """

    def __init__(self, settings_path: str = "data/settings.json"):
        """
        Initializes the ConfigService and loads configuration data.

        Args:
            settings_path: Path to the JSON settings file.
        """
        self.settings_path: str = settings_path
        self._config_data: Optional[Dict[str, Any]] = self._load_config()

    def _load_config(self) -> Optional[Dict[str, Any]]:
        """
        Loads the configuration data from the settings file.

        Returns:
            A dictionary containing the configuration data, or None if loading fails.
        """
        try:
            with open(self.settings_path, 'r') as f:
                data = json.load(f)
            return data
        except FileNotFoundError:
            # TODO: Log this error appropriately
            print(f"Error: Settings file not found at {self.settings_path}")
            return None
        except json.JSONDecodeError:
            # TODO: Log this error appropriately
            print(f"Error: Could not decode JSON from {self.settings_path}")
            return None

    def get_config_section(self, section_name: str) -> Optional[Any]:
        """
        Retrieves a specific section from the loaded configuration data.

        Args:
            section_name: The name of the configuration section to retrieve.

        Returns:
            The data for the requested section, or None if the section
            is not found or if the configuration was not loaded.
        """
        if self._config_data is None:
            return None
        return self._config_data.get(section_name)
