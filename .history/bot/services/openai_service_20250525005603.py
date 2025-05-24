import json
from typing import Dict, Any, Optional, List

class CampaignLoader:
    """
    Handles loading campaign data from a JSON file.
    """

    def __init__(self, file_path: Optional[str] = None):
        """
        Initializes the CampaignLoader.

        Args:
            file_path (Optional[str]): An optional path to a campaign file.
                                       Loading is not done automatically on init.
        """
        self._campaign_data: Optional[Dict[str, Any]] = None
        self._file_path: Optional[str] = file_path # Store if provided, for potential future use
        print(f"CampaignLoader initialized. Optional file path: {file_path}")

    def load_campaign_from_file(self, file_path: str) -> Dict[str, Any]:
        """
        Reads and parses a JSON campaign file.

        Args:
            file_path (str): The path to the JSON campaign file.

        Returns:
            Dict[str, Any]: The parsed campaign data as a dictionary.
                            Returns an empty dictionary if loading fails.
        """
        print(f"Attempting to load campaign data from: {file_path}")
        self._file_path = file_path # Update file path
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self._campaign_data = json.load(f)
            print(f"Successfully loaded campaign data from: {file_path}")
            return self._campaign_data if self._campaign_data is not None else {}
        except FileNotFoundError:
            print(f"Error: Campaign file not found at {file_path}")
            self._campaign_data = None
            return {}
        except json.JSONDecodeError as e:
            print(f"Error: Failed to decode JSON from {file_path}. Details: {e}")
            self._campaign_data = None
            return {}
        except Exception as e:
            print(f"An unexpected error occurred while loading {file_path}: {e}")
            self._campaign_data = None
            return {}

    def get_campaign_data(self) -> Optional[Dict[str, Any]]:
        """Returns all loaded campaign data."""
        return self._campaign_data

    def get_world_lore(self) -> Optional[Dict[str, Any]]:
        """Retrieves the world lore section from the campaign data."""
        if not self._campaign_data:
            print("Warning: Campaign data not loaded. Cannot get world lore.")
            return None
        return self._campaign_data.get("world_lore")

    def get_character_templates(self) -> List[Dict[str, Any]]:
        """Retrieves character templates from the campaign data."""
        if not self._campaign_data:
            print("Warning: Campaign data not loaded. Returning empty list for character templates.")
            return []
        return self._campaign_data.get("character_templates", [])

    def get_equipment_templates(self) -> List[Dict[str, Any]]:
        """Retrieves equipment templates from the campaign data."""
        if not self._campaign_data:
            print("Warning: Campaign data not loaded. Returning empty list for equipment templates.")
            return []
        return self._campaign_data.get("equipment_templates", [])

    def get_skill_templates(self) -> List[Dict[str, Any]]:
        """Retrieves skill templates from the campaign data."""
        if not self._campaign_data:
            print("Warning: Campaign data not loaded. Returning empty list for skill templates.")
            return []
        return self._campaign_data.get("skill_templates", [])

    def get_trait_templates(self) -> List[Dict[str, Any]]:
        """Retrieves trait templates from the campaign data."""
        if not self._campaign_data:
            print("Warning: Campaign data not loaded. Returning empty list for trait templates.")
            return []
        return self._campaign_data.get("trait_templates", [])

    def get_spell_templates(self) -> List[Dict[str, Any]]:
        """Retrieves spell templates from the campaign data."""
        if not self._campaign_data:
            print("Warning: Campaign data not loaded. Returning empty list for spell templates.")
            return []
        return self._campaign_data.get("spell_templates", [])

    def get_quest_templates(self) -> List[Dict[str, Any]]:
        """Retrieves quest templates from the campaign data."""
        if not self._campaign_data:
            print("Warning: Campaign data not loaded. Returning empty list for quest templates.")
            return []
        return self._campaign_data.get("quest_templates", [])

    def get_npc_archetypes(self) -> List[Dict[str, Any]]:
        """Retrieves NPC archetypes from the campaign data."""
        if not self._campaign_data:
            print("Warning: Campaign data not loaded. Returning empty list for NPC archetypes.")
            return []
        return self._campaign_data.get("npc_archetypes", [])

# Example Usage (for testing purposes)
if __name__ == '__main__':
    loader = CampaignLoader()

    # Create a dummy campaign file for testing
    dummy_campaign_data = {
        "world_lore": {"history": "A long, long time ago...", "regions": ["Elmsworth", "Blackwood"]},
        "character_templates": [{"name": "Generic Hero", "class": "Warrior"}],
        "equipment_templates": [{"name": "Iron Sword", "type": "weapon", "damage": 10}],
        "skill_templates": [{"name": "Power Attack", "effect": "Deals extra damage"}],
        "trait_templates": [{"name": "Brave", "description": "Resists fear"}],
        "spell_templates": [{"name": "Fireball", "cost": 10, "damage": 20}],
        "quest_templates": [{"title": "The Lost Artifact", "description": "Find the missing relic."}],
        "npc_archetypes": [{"name": "Guard", "dialogue_greeting": "Halt!"}]
    }
    dummy_file_path = "dummy_campaign.json"
    with open(dummy_file_path, 'w', encoding='utf-8') as f:
        json.dump(dummy_campaign_data, f, indent=2)

    # Test loading
    loaded_data = loader.load_campaign_from_file(dummy_file_path)
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
    else:
        print("Campaign loading failed.")

    # Test loading non-existent file
    print("\n--- Testing non-existent file ---")
    loader.load_campaign_from_file("non_existent_campaign.json")
    print("World Lore (after failed load):", loader.get_world_lore()) # Should be None or empty

    # Test loading invalid JSON file
    invalid_json_path = "invalid_campaign.json"
    with open(invalid_json_path, 'w', encoding='utf-8') as f:
        f.write("{'name': 'test', 'broken_json': True,") # Invalid JSON
    print("\n--- Testing invalid JSON file ---")
    loader.load_campaign_from_file(invalid_json_path)
    print("NPC Archetypes (after invalid JSON load):", loader.get_npc_archetypes()) # Should be empty list

    # Clean up dummy files
    import os
    os.remove(dummy_file_path)
    os.remove(invalid_json_path)
    print("\nCleaned up dummy files.")
