from dataclasses import dataclass, asdict, fields
from typing import Dict, Any

@dataclass
class LoreEntry:
    id: str
    title_i18n: Dict[str, str]
    text_i18n: Dict[str, str]
    # Optional: Add other fields like category, tags, discovery_conditions, etc.

    def to_dict(self) -> Dict[str, Any]:
        """Converts the LoreEntry instance to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoreEntry":
        """Creates a LoreEntry instance from a dictionary."""
        # Ensure only known fields are passed to the constructor
        class_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in class_fields}
        return cls(**filtered_data)

if __name__ == "__main__":
    print("--- Testing LoreEntry ---")

    # Example Usage
    lore_data_1 = {
        "id": "world_creation_myth",
        "title_i18n": {"en": "The World's Creation", "es": "La Creación del Mundo"},
        "text_i18n": {
            "en": "In the beginning, there was only the Great Serpent...",
            "es": "Al principio, solo existía la Gran Serpiente..."
        }
    }
    entry1 = LoreEntry.from_dict(lore_data_1)
    print(f"Entry 1 ID: {entry1.id}")
    print(f"Entry 1 Title (en): {entry1.title_i18n.get('en')}")
    print(f"Entry 1 Dict: {entry1.to_dict()}")

    lore_data_2 = {
        "id": "ancient_king_story",
        "title_i18n": {"en": "The Lost King"},
        # Missing text_i18n, should still work if handled by consumer
    }
    try:
        # This will fail if text_i18n is required by dataclass.
        # For current definition, it will fail as text_i18n is not optional.
        # Let's make text_i18n optional for this test or provide it.
        # For now, let's assume it's provided.
        lore_data_2_fixed = {
            "id": "ancient_king_story",
            "title_i18n": {"en": "The Lost King"},
            "text_i18n": {"en": "The tale of the lost king is a sad one."}
        }
        entry2 = LoreEntry.from_dict(lore_data_2_fixed)
        print(f"\nEntry 2 ID: {entry2.id}")
        print(f"Entry 2 Title (en): {entry2.title_i18n.get('en')}")
        print(f"Entry 2 Text (en): {entry2.text_i18n.get('en')}")
        print(f"Entry 2 Dict: {entry2.to_dict()}")

        # Test with extra fields in dict
        lore_data_3_extra = {
            "id": "dragon_lore",
            "title_i18n": {"en": "Dragons of Old"},
            "text_i18n": {"en": "Ancient dragons ruled the skies."},
            "category": "Mythical Creatures", # Extra field
            "unlock_level": 10 # Extra field
        }
        entry3 = LoreEntry.from_dict(lore_data_3_extra)
        print(f"\nEntry 3 ID: {entry3.id}")
        print(f"Entry 3 Title (en): {entry3.title_i18n.get('en')}")
        # Check that extra fields are not in the object
        assert not hasattr(entry3, 'category')
        print(f"Entry 3 Dict (should not contain 'category'): {entry3.to_dict()}")


    except TypeError as e:
        print(f"Error during LoreEntry test: {e}")

    print("--- End of LoreEntry tests ---")
