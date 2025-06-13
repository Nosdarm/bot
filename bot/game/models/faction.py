from __future__ import annotations
import uuid
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from bot.game.models.base_model import BaseModel

@dataclass
class Faction(BaseModel):
    """
    Represents a faction or organization within the game.
    """
    name_i18n: Dict[str, str] = field(default_factory=dict)
    description_i18n: Dict[str, str] = field(default_factory=dict)
    guild_id: str = ""
    member_ids: List[str] = field(default_factory=list)  # List of NPC/Character IDs
    leader_id: Optional[str] = None
    alignment: Optional[str] = None  # e.g., "lawful_good", "chaotic_evil", "neutral"
    state_variables: Dict[str, Any] = field(default_factory=dict)  # For any other dynamic data

    def __post_init__(self):
        if not self.guild_id:
            raise ValueError("guild_id cannot be empty for a Faction.")
        if not self.name_i18n or not any(self.name_i18n.values()):
            # Assuming at least one language entry for name is required
            raise ValueError("name_i18n cannot be empty and must have at least one entry.")


    def to_dict(self) -> Dict[str, Any]:
        """Serializes the Faction object to a dictionary."""
        data = super().to_dict()  # Gets 'id'
        data.update({
            "name_i18n": self.name_i18n,
            "description_i18n": self.description_i18n,
            "guild_id": self.guild_id,
            "member_ids": self.member_ids,
            "leader_id": self.leader_id,
            "alignment": self.alignment,
            "state_variables": self.state_variables,
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Faction:
        """Deserializes a dictionary into a Faction object."""
        faction_id = data.get('id') # If id is not in data, BaseModel will generate one

        # Required fields for __init__ (or __post_init__)
        guild_id = data.get("guild_id")
        if guild_id is None:
            raise ValueError("Missing 'guild_id' in data for Faction.from_dict")

        name_i18n = data.get("name_i18n")
        if name_i18n is None or not isinstance(name_i18n, dict) or not any(name_i18n.values()):
             # Fallback or error if name_i18n is crucial and missing/invalid
             # For now, let's allow it to be potentially empty if from_dict is called before validation
             # but __post_init__ will catch it if it's truly empty.
             # However, the prompt implies it's a required field.
             # Let's assume if it's None from data, it means it wasn't set, so default_factory should kick in.
             # Or, if it must be in data:
            raise ValueError("Missing or invalid 'name_i18n' in data for Faction.from_dict")


        return cls(
            id=faction_id,
            name_i18n=name_i18n, # Ensure this is a dict
            description_i18n=data.get("description_i18n", {}), # Default to empty dict if missing
            guild_id=guild_id,
            member_ids=data.get("member_ids", []), # Default to empty list
            leader_id=data.get("leader_id"),
            alignment=data.get("alignment"),
            state_variables=data.get("state_variables", {}), # Default to empty dict
        )

# Example Usage (Optional, for testing)
if __name__ == '__main__':
    try:
        # Test successful creation
        faction_data1 = {
            "name_i18n": {"en": "The Noble Guard", "es": "La Guardia Noble"},
            "description_i18n": {"en": "Sworn protectors of the realm.", "es": "Protectores jurados del reino."},
            "guild_id": "guild_123",
            "member_ids": ["char_1", "char_2", "npc_1"],
            "leader_id": "char_1",
            "alignment": "lawful_good",
            "state_variables": {"influence": 100, "territories_controlled": 5}
        }
        faction1 = Faction.from_dict(faction_data1)
        faction1_dict = faction1.to_dict()
        print("Faction 1 ID:", faction1.id)
        print("Faction 1 Dict:", faction1_dict)
        assert faction1_dict["name_i18n"]["en"] == "The Noble Guard"
        assert "char_1" in faction1_dict["member_ids"]

        # Test creation with minimal data (relying on defaults and __post_init__ for guild_id)
        faction2 = Faction(guild_id="guild_456", name_i18n={"en": "Shadow Syndicate"})
        print("\nFaction 2 ID:", faction2.id)
        print("Faction 2 Member IDs (defaulted):", faction2.member_ids) # Should be []
        assert faction2.member_ids == []
        faction2_dict = faction2.to_dict()
        print("Faction 2 Dict:", faction2_dict)

        # Test from_dict with minimal data
        faction_data3_min = {
            "id": "fixed_faction_id_003",
            "guild_id": "guild_789",
            "name_i18n": {"en": "Traders Collective"}
            # description_i18n, member_ids etc., will use defaults from from_dict/Faction's defaults
        }
        faction3 = Faction.from_dict(faction_data3_min)
        print("\nFaction 3 ID:", faction3.id)
        print("Faction 3 Description (defaulted i18n):", faction3.description_i18n) # Should be {}
        assert faction3.description_i18n == {}
        print("Faction 3 Dict:", faction3.to_dict())


        # Test missing required field: guild_id in constructor
        print("\nTesting missing required field (guild_id) in constructor:")
        try:
            Faction(name_i18n={"en": "No Guild Faction"})
        except ValueError as e:
            print(f"Caught expected error: {e}")

        # Test missing required field: name_i18n in constructor
        print("\nTesting missing required field (name_i18n) in constructor:")
        try:
            Faction(guild_id="some_guild")
        except ValueError as e:
            print(f"Caught expected error: {e}")

        # Test missing required field: guild_id in from_dict
        print("\nTesting missing required field (guild_id) in from_dict:")
        try:
            Faction.from_dict({"name_i18n": {"en": "Faction without guild"}})
        except ValueError as e:
            print(f"Caught expected error: {e}")

        # Test missing required field: name_i18n in from_dict
        print("\nTesting missing required field (name_i18n) in from_dict:")
        try:
            Faction.from_dict({"guild_id": "some_guild_id"})
        except ValueError as e:
            print(f"Caught expected error: {e}")

    except Exception as e:
        print(f"An unexpected error occurred during Faction testing: {e}")
        import traceback
        traceback.print_exc()
