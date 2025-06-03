# bot/game/services/campaign_loader.py

import json
import os # For path operations
import traceback # For more detailed error logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING

# Я предполагаю, что это все содержимое файла, которое вы видите.
# Синтаксическая ошибка на строке 164 должна быть ГДЕ-ТО ПОСЛЕ ЭТОГО КОДА в ВАШЕМ реальном файле.

if TYPE_CHECKING:
    # No specific manager dependencies for basic loader,
    # but could have if it interacts with settings or a DB for campaign sources
    pass

class CampaignLoader:
    """
    Handles loading campaign data from a JSON file.
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None, **kwargs: Any):
        """
        Initializes the CampaignLoader.

        Args:
            settings (Optional[Dict[str, Any]]): Settings dictionary, expected to contain 'campaign_data_path' and 'default_campaign_identifier'.
            **kwargs: Additional keyword arguments (ignored).
        """
        self._settings = settings if settings is not None else {}
        # Default base path can be configured in settings or hardcoded
        self._campaign_base_path = self._settings.get('campaign_data_path', 'data/campaigns')
        # Убедимся, что путь к кампаниям абсолютный, если он относительный к корню проекта
        # Это может потребовать уточнения в зависимости от вашей структуры проекта
        # Предполагаем, что корень проекта находится на один уровень выше 'bot'
        try:
             project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
             if not os.path.isabs(self._campaign_base_path):
                 self._campaign_base_path = os.path.join(project_root, self._campaign_base_path)
             # Также убедимся, что папка существует
             os.makedirs(self._campaign_base_path, exist_ok=True)
        except Exception as e:
             print(f"CampaignLoader: Warning: Could not resolve or create campaign base path '{self._campaign_base_path}'. Using it as is. Error: {e}")


        print(f"CampaignLoader initialized. Base campaign path: '{self._campaign_base_path}'")


    async def load_campaign_data_from_source(self, campaign_identifier: Optional[str] = None) -> Dict[str, Any]:
        """
        Loads campaign data from a source (e.g., JSON file).
        
        Args:
            campaign_identifier: An optional identifier for a specific campaign. 
                                 If None, a default might be loaded.

        Returns:
            A dictionary containing the loaded campaign data, or an empty dict on error.
        """
        effective_campaign_identifier = campaign_identifier
        if effective_campaign_identifier is None:
            effective_campaign_identifier = self._settings.get('default_campaign_identifier', 'default_campaign')
        
        file_name = f"{effective_campaign_identifier}.json"
        file_path = os.path.join(self._campaign_base_path, file_name)
        
        print(f"CampaignLoader: Attempting to load campaign data from '{file_path}'...")
        
        if not os.path.exists(file_path):
            print(f"CampaignLoader: Error - Campaign file not found at '{file_path}'.")
            # If the requested campaign was not found, and it wasn't already the default we're trying,
            # attempt to load the 'default_campaign' as a fallback.
            if campaign_identifier is not None and effective_campaign_identifier != 'default_campaign':
                 print(f"CampaignLoader: Fallback - Attempting to load 'default_campaign.json'.")
                 # Call recursively with 'default_campaign'. Pass explicit identifier to avoid infinite loop check below.
                 return await self.load_campaign_data_from_source(campaign_identifier='default_campaign')
            # If we were already trying the default and it wasn't found
            print(f"CampaignLoader: Default campaign '{effective_campaign_identifier}.json' not found. Returning empty data.")
            return {} # Return empty if default is also missing or if it was the initial request

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"CampaignLoader: Successfully loaded and parsed campaign data from '{file_path}'.")
            self._campaign_data = data # Save loaded data internally
            return data
        except FileNotFoundError: # Should be caught by os.path.exists, but as a safeguard.
            # Эта ветка маловероятна после os.path.exists, но оставлена как двойная проверка
            print(f"CampaignLoader: Error (safeguard) - Campaign file not found at '{file_path}'.")
            self._campaign_data = None # Ensure internal state is cleared on error
            return {}
        except json.JSONDecodeError as e:
            print(f"CampaignLoader: Error - Failed to parse JSON from campaign file '{file_path}': {e}")
            traceback.print_exc()
            self._campaign_data = None # Ensure internal state is cleared on error
            return {}
        except Exception as e:
            print(f"CampaignLoader: Error - Could not read campaign file '{file_path}': {e}")
            traceback.print_exc()
            self._campaign_data = None # Ensure internal state is cleared on error
            return {}

    def get_campaign_data(self) -> Optional[Dict[str, Any]]:
        """Returns all loaded campaign data."""
        if self._campaign_data is None:
             print("Warning: Campaign data not loaded or loading failed. get_campaign_data() returning None.")
        return self._campaign_data

    def get_world_lore(self) -> Optional[Dict[str, Any]]:
        """Retrieves the world lore section from the campaign data."""
        if self._campaign_data is None: # Check against None directly
            print("Warning: Campaign data not loaded. Cannot get world lore.")
            return None
        # Убедимся, что "world_lore" существует и является словарем
        lore = self._campaign_data.get("world_lore")
        if lore is not None and not isinstance(lore, dict):
            print("Warning: 'world_lore' in campaign data is not a dictionary. Returning None.")
            return None
        return lore


    # Оставшиеся методы get_..._templates() и get_npc_archetypes()
    # Убедитесь, что они проверяют self._campaign_data is not None и возвращают [] по умолчанию
    # Вот пример одного из них, остальные должны быть похожи:
    def get_character_templates(self) -> List[Dict[str, Any]]:
        """Retrieves character templates from the campaign data."""
        if self._campaign_data is None:
            print("Warning: Campaign data not loaded. Returning empty list for character templates.")
            return []
        # Убедимся, что "character_templates" существует и является списком
        templates = self._campaign_data.get("character_templates", [])
        if not isinstance(templates, list):
             print("Warning: 'character_templates' in campaign data is not a list. Returning empty list.")
             return []
        return templates

    def get_equipment_templates(self) -> List[Dict[str, Any]]:
        """Retrieves equipment templates from the campaign data."""
        if self._campaign_data is None:
            print("Warning: Campaign data not loaded. Returning empty list for equipment templates.")
            return []
        templates = self._campaign_data.get("equipment_templates", [])
        if not isinstance(templates, list):
             print("Warning: 'equipment_templates' in campaign data is not a list. Returning empty list.")
             return []
        return templates

    def get_skill_templates(self) -> List[Dict[str, Any]]:
        """Retrieves skill templates from the campaign data."""
        if self._campaign_data is None:
            print("Warning: Campaign data not loaded. Returning empty list for skill templates.")
            return []
        templates = self._campaign_data.get("skill_templates", [])
        if not isinstance(templates, list):
             print("Warning: 'skill_templates' in campaign data is not a list. Returning empty list.")
             return []
        return templates

    def get_trait_templates(self) -> List[Dict[str, Any]]:
        """Retrieves trait templates from the campaign data."""
        if self._campaign_data is None:
            print("Warning: Campaign data not loaded. Returning empty list for trait templates.")
            return []
        templates = self._campaign_data.get("trait_templates", [])
        if not isinstance(templates, list):
             print("Warning: 'trait_templates' in campaign data is not a list. Returning empty list.")
             return []
        return templates

    def get_spell_templates(self) -> List[Dict[str, Any]]:
        """Retrieves spell templates from the campaign data."""
        if self._campaign_data is None:
            print("Warning: Campaign data not loaded. Returning empty list for spell templates.")
            return []
        templates = self._campaign_data.get("spell_templates", [])
        if not isinstance(templates, list):
             print("Warning: 'spell_templates' in campaign data is not a list. Returning empty list.")
             return []
        return templates

    def get_quest_templates(self) -> List[Dict[str, Any]]:
        """Retrieves quest templates from the campaign data."""
        if self._campaign_data is None:
            print("Warning: Campaign data not loaded. Returning empty list for quest templates.")
            return []
        templates = self._campaign_data.get("quest_templates", [])
        if not isinstance(templates, list):
             print("Warning: 'quest_templates' in campaign data is not a list. Returning empty list.")
             return []
        return templates

    def get_npc_archetypes(self) -> List[Dict[str, Any]]:
        """Retrieves NPC archetypes from the campaign data."""
        if self._campaign_data is None:
            print("Warning: Campaign data not loaded. Returning empty list for NPC archetypes.")
            return []
        templates = self._campaign_data.get("npc_archetypes", [])
        if not isinstance(templates, list):
             print("Warning: 'npc_archetypes' in campaign data is not a list. Returning empty list.")
             return []
        return templates


    # Метод для получения конкретного шаблона по ID (например, персонажа, предмета и т.п.)
    def get_template_by_id(self, template_type: str, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a specific template by its type and ID from the loaded campaign data.

        Args:
            template_type (str): The type of template (e.g., 'character', 'equipment', 'npc').
                                 Should correspond to a key in the campaign data.
            template_id (str): The 'id' key of the specific template.

        Returns:
            Optional[Dict[str, Any]]: The template dictionary if found, None otherwise.
        """
        if self._campaign_data is None:
            print(f"Warning: Campaign data not loaded. Cannot get template '{template_id}' of type '{template_type}'.")
            return None

        templates_list = self._campaign_data.get(f"{template_type}_templates") # Например, "character_templates"

        if not isinstance(templates_list, list):
            # Если ключа нет или значение не список
            print(f"Warning: Template type '{template_type}' not found or not a list in campaign data.")
            return None

        # Ищем шаблон по полю 'id'
        for template in templates_list:
            if isinstance(template, dict) and template.get('id') == template_id:
                return template

        print(f"Warning: Template '{template_id}' of type '{template_type}' not found in campaign data.")
        return None


# Example Usage (for testing purposes) - ЭТОТ БЛОК НАЧИНАЕТСЯ ПОСЛЕ ОСНОВНОГО КОДА КЛАССА
if __name__ == '__main__':
    # ... (ваш тестовый код остается здесь) ...
    loader = CampaignLoader()

    # Create a dummy campaign file for testing
    dummy_campaign_data = {
        "world_lore": {"history": "A long, long time ago...", "regions": ["Elmsworth", "Blackwood"]},
        "character_templates": [{"id": "hero_basic", "name": "Generic Hero", "class": "Warrior"}], # Добавил id
        "equipment_templates": [{"id": "iron_sword", "name": "Iron Sword", "type": "weapon", "damage": 10}], # Добавил id
        "skill_templates": [{"id": "power_attack", "name": "Power Attack", "effect": "Deals extra damage"}], # Добавил id
        "trait_templates": [{"id": "brave", "name": "Brave", "description": "Resists fear"}], # Добавил id
        "spell_templates": [{"id": "fireball", "name": "Fireball", "cost": 10, "damage": 20}], # Добавил id
        "quest_templates": [{"id": "lost_artifact", "title": "The Lost Artifact", "description": "Find the missing relic."}], # Добавил id
        "npc_archetypes": [{"id": "guard_npc", "name": "Guard", "dialogue_greeting": "Halt!"}] # Добавил id
    }
    dummy_file_path = "dummy_campaign.json"
    # Убедимся, что файл создается рядом со скриптом или в известной временной папке
    current_dir = os.path.dirname(__file__)
    dummy_file_path_full = os.path.join(current_dir, dummy_file_path)
    invalid_json_path = "invalid_campaign.json"
    invalid_json_path_full = os.path.join(current_dir, invalid_json_path)


    try: # Добавил блок try/finally для очистки даже при ошибках в тесте
        with open(dummy_file_path_full, 'w', encoding='utf-8') as f:
            json.dump(dummy_campaign_data, f, indent=2)

        # Test loading
        # Используем полный путь к файлу
        loaded_data = loader.load_campaign_from_file(dummy_file_path_full)
        if loaded_data:
            print("\n--- Accessing loaded data ---")
            print("World Lore:", loader.get_world_lore())
            print("Character Templates:", loader.get_character_templates())
            print("Equipment Templates:", loader.get_equipment_templates())
            print("Skill Templates:", loader.get_skill_templates())
            print("Trait Templates:", loader.get_trait_templates())
            print("Spell Templates:", loader.get_spell_templates())
            print("Quest Templates:", loader.get_quest_templates())
            print("NPC Archetypes:", loader.get_npc_archetypes())

            # Тест получения конкретного шаблона по ID
            print("\n--- Testing get_template_by_id ---")
            hero_template = loader.get_template_by_id('character', 'hero_basic')
            print("Hero Template:", hero_template)
            missing_template = loader.get_template_by_id('equipment', 'missing_sword')
            print("Missing Template:", missing_template)
            wrong_type = loader.get_template_by_id('non_existent_type', 'some_id')
            print("Wrong Type:", wrong_type)


        else:
            print("Campaign loading failed.")

        # Test loading non-existent file
        print("\n--- Testing non-existent file ---")
        loader.load_campaign_from_file("non_existent_campaign_xyz.json") # Убедимся, что имя файла отличается
        print("World Lore (after failed load):", loader.get_world_lore()) # Should be None or empty

        # Test loading invalid JSON file
        with open(invalid_json_path_full, 'w', encoding='utf-8') as f:
            f.write("{'name': 'test', 'broken_json': True,") # Invalid JSON
        print("\n--- Testing invalid JSON file ---")
        loader.load_campaign_from_file(invalid_json_path_full)
        print("NPC Archetypes (after invalid JSON load):", loader.get_npc_archetypes()) # Should be empty list

    finally: # Очистка выполняется даже при ошибках в try блоке
        # Clean up dummy files
        if os.path.exists(dummy_file_path_full): os.remove(dummy_file_path_full)
        if os.path.exists(invalid_json_path_full): os.remove(invalid_json_path_full)
        print("\nCleaned up dummy files.")
