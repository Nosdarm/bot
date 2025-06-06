from __future__ import annotations
import uuid
from typing import Dict, Any, Optional
from bot.game.models.base_model import BaseModel

class Relationship(BaseModel):
    """
    Represents a relationship between two entities in the game.
    """
    def __init__(self,
                 id: Optional[str] = None,
                 entity1_id: str = "",
                 entity1_type: str = "", # e.g., "player", "npc", "faction"
                 entity2_id: str = "",
                 entity2_type: str = "", # e.g., "player", "npc", "faction"
                 relationship_type: str = "neutral",
                 strength: Optional[float] = 0.0,
                  details_i18n: Optional[Dict[str, str]] = None,
                  guild_id: str = "",
                  details: Optional[str] = None): # For backward compatibility
        super().__init__(id)
        self.entity1_id = entity1_id
        self.entity1_type = entity1_type
        self.entity2_id = entity2_id
        self.entity2_type = entity2_type
        self.relationship_type = relationship_type
        self.strength = strength if strength is not None else 0.0
        
        if details_i18n is not None:
            self.details_i18n = details_i18n
        elif details is not None:
            self.details_i18n = {"en": details}
        else:
            self.details_i18n = {"en": ""}
            
        self.guild_id = guild_id

        # Basic validation for required fields (can be expanded)
        if not self.entity1_id:
            raise ValueError("entity1_id cannot be empty.")
        if not self.entity1_type:
            raise ValueError("entity1_type cannot be empty.")
        if not self.entity2_id:
            raise ValueError("entity2_id cannot be empty.")
        if not self.entity2_type:
            raise ValueError("entity2_type cannot be empty.")
        if not self.guild_id:
            # Depending on game logic, guild_id might be optional or have a global default
            # For now, let's assume it's required for a scoped relationship.
            raise ValueError("guild_id cannot be empty for a relationship.")


    def to_dict(self) -> Dict[str, Any]:
        """Serializes the Relationship object to a dictionary."""
        data = super().to_dict() # Gets 'id'
        data.update({
            "entity1_id": self.entity1_id,
            "entity1_type": self.entity1_type,
            "entity2_id": self.entity2_id,
            "entity2_type": self.entity2_type,
            "relationship_type": self.relationship_type,
            "strength": self.strength,
            "details_i18n": self.details_i18n,
            "guild_id": self.guild_id,
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Relationship:
        """Deserializes a dictionary into a Relationship object."""
        relationship_id = data.get('id')
        # If id is not in data, BaseModel will generate one in __init__

        # Required fields - raise error if missing in data, as __init__ expects them
        entity1_id = data.get("entity1_id")
        if entity1_id is None:
            raise ValueError("Missing 'entity1_id' in data for Relationship.from_dict")
        entity1_type = data.get("entity1_type")
        if entity1_type is None:
            raise ValueError("Missing 'entity1_type' in data for Relationship.from_dict")
        entity2_id = data.get("entity2_id")
        if entity2_id is None:
            raise ValueError("Missing 'entity2_id' in data for Relationship.from_dict")
        entity2_type = data.get("entity2_type")
        if entity2_type is None:
            raise ValueError("Missing 'entity2_type' in data for Relationship.from_dict")
        guild_id = data.get("guild_id")
        if guild_id is None:
            raise ValueError("Missing 'guild_id' in data for Relationship.from_dict")


        return cls(
            id=relationship_id, # Pass it to __init__; BaseModel handles None if not in data
            entity1_id=entity1_id,
            entity1_type=entity1_type,
            entity2_id=entity2_id,
            entity2_type=entity2_type,
            relationship_type=data.get("relationship_type", "neutral"),
            strength=data.get("strength", 0.0), # Handles None from data by defaulting
            details_i18n=data.get("details_i18n"), # Will be handled by __init__ if None
            details=data.get("details"), # For backward compatibility, handled by __init__
            guild_id=guild_id
        )
        # Post-hoc processing for details_i18n if it came from old field and new field was absent
        # This ensures that if details_i18n was passed as None, and details (old) was present, it gets converted.
        # However, __init__ should ideally handle this logic based on its parameters.
        # Let's refine __init__ and from_dict to make this cleaner.
        # The current __init__ logic for details_i18n already covers this:
        # if details_i18n is not None: self.details_i18n = details_i18n
        # elif details is not None: self.details_i18n = {"en": details}
        # else: self.details_i18n = {"en": ""}
        # So, as long as from_dict passes both details_i18n (from new field) and details (from old field)
        # to __init__, it should be fine.
        # return instance # Removed unreachable and incorrect code

# Example usage (optional, for testing)
if __name__ == '__main__':
    # Test successful creation
    try:
        rel1_data = {
            "entity1_id": "player_1",
            "entity1_type": "player",
            "entity2_id": "npc_1",
            "entity2_type": "npc",
            "relationship_type": "friend",
            "strength": 0.75,
            "details_i18n": {"en": "Met in the tavern, shared a drink.", "ru": "Встретились в таверне, выпили."},
            "guild_id": "guild_123"
        }
        # Pass specific known args to from_dict, then to __init__
        rel1 = Relationship.from_dict(rel1_data) 
        print("Relationship 1 ID:", rel1.id)
        print("Relationship 1 Dict:", rel1.to_dict())

        rel2_data = {
            "id": "fixed_rel_id_002",
            "entity1_id": "faction_A",
            "entity1_type": "faction",
            "entity2_id": "faction_B",
            "entity2_type": "faction",
            "relationship_type": "foe",
            "strength": -0.9,
            # details is missing, guild_id is present
            "guild_id": "global_events"
        }
        rel2 = Relationship.from_dict(rel2_data) # details is missing, guild_id present
        print("\nRelationship 2 ID:", rel2.id)
        print("Relationship 2 Details (defaulted i18n):", rel2.details_i18n)
        assert rel2.details_i18n == {"en": ""} # Default from __init__ when details and details_i18n are missing
        print("Relationship 2 Dict:", rel2.to_dict())
        
        # Test backward compatibility: old 'details' field in from_dict data
        rel2_old_format_data = {
            "id": "fixed_rel_id_002_old",
            "entity1_id": "faction_A",
            "entity1_type": "faction",
            "entity2_id": "faction_B",
            "entity2_type": "faction",
            "relationship_type": "foe",
            "strength": -0.9,
            "details": "Long-standing feud.", # Old format
            "guild_id": "global_events"
        }
        rel2_old = Relationship.from_dict(rel2_old_format_data)
        print("\nRelationship 2 (old format) ID:", rel2_old.id)
        print("Relationship 2 Details (i18n from old):", rel2_old.details_i18n)
        assert rel2_old.details_i18n == {"en": "Long-standing feud."}


        # Test creation with minimal data (relying on defaults in __init__)
        rel3 = Relationship(entity1_id="npc_2", entity1_type="npc", entity2_id="player_1", entity2_type="player", guild_id="guild_123")
        print("\nRelationship 3 ID:", rel3.id)
        print("Relationship 3 Type (defaulted):", rel3.relationship_type)
        print("Relationship 3 Strength (defaulted):", rel3.strength)
        print("Relationship 3 Dict:", rel3.to_dict())

        # Test handling of None for optional fields in constructor
        rel4 = Relationship(
            entity1_id="player_2", entity1_type="player",
            entity2_id="item_1", entity2_type="item_owner", # Example
            guild_id="guild_456",
            strength=None, # Explicitly testing None
            details_i18n=None,   # Explicitly testing None for i18n field
            details=None # Explicitly testing None for old field (should result in {"en":""})
        )
        print("\nRelationship 4 ID:", rel4.id)
        print("Relationship 4 Strength (defaulted from None):", rel4.strength)
        print("Relationship 4 Details (i18n defaulted from None):", rel4.details_i18n)
        assert rel4.details_i18n == {"en": ""}
        print("Relationship 4 Dict:", rel4.to_dict())


        # Test missing required field in from_dict
        print("\nTesting missing required field (entity1_id):")
        try:
            Relationship.from_dict({
                "entity1_type": "player",
                "entity2_id": "npc_1",
                "entity2_type": "npc",
                "guild_id": "guild_123"
            })
        except ValueError as e:
            print(f"Caught expected error: {e}")

        print("\nTesting missing required field (guild_id) in constructor:")
        try:
            Relationship(entity1_id="p1", entity1_type="player", entity2_id="p2", entity2_type="player")
        except ValueError as e:
            print(f"Caught expected error: {e}")

    except ValueError as e:
        print(f"An unexpected error occurred during testing: {e}")

