from __future__ import annotations
import time
import uuid
from typing import Dict, Any, Optional
from bot.game.models.base_model import BaseModel

class GameLogEntry(BaseModel):
    """
    Represents a log entry for game events.
    """
    def __init__(self,
                 id: Optional[str] = None,
                 timestamp: Optional[float] = None,
                 guild_id: str = "",
                 entry_type: str = "generic", # e.g., "player_command", "npc_action", "quest_update"
                 actor_id: Optional[str] = None,
                 actor_type: Optional[str] = None, # e.g., "player", "npc", "system"
                 target_id: Optional[str] = None,
                 target_type: Optional[str] = None, # e.g., "player", "npc", "item", "location"
                 description_i18n: Optional[Dict[str, str]] = None,
                 description: Optional[str] = None, # For backward compatibility
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(id)
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.guild_id = guild_id
        self.entry_type = entry_type
        self.actor_id = actor_id
        self.actor_type = actor_type
        self.target_id = target_id
        self.target_type = target_type
        
        if description_i18n is not None:
            self.description_i18n = description_i18n
        elif description is not None:
            self.description_i18n = {"en": description}
        else:
            self.description_i18n = {"en": ""}
            
        self.details = details if details is not None else {}

        if not self.guild_id:
            # Consider if guild_id is truly optional or should raise error/have default
            # For logging, it's often crucial for partitioning data.
            # Let's assume for now it should ideally be provided.
            # print(f"Warning: GameLogEntry created without guild_id (ID: {self.id})")
            pass # Or raise ValueError("guild_id is required for GameLogEntry")

        if not self.description:
            # print(f"Warning: GameLogEntry created with empty description_i18n (ID: {self.id})")
            pass


    def to_dict(self) -> Dict[str, Any]:
        """Serializes the GameLogEntry object to a dictionary."""
        data = super().to_dict() # Gets 'id'
        data.update({
            "timestamp": self.timestamp,
            "guild_id": self.guild_id,
            "entry_type": self.entry_type,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "description_i18n": self.description_i18n,
            "details": self.details,
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GameLogEntry:
        """Deserializes a dictionary into a GameLogEntry object."""
        log_id = data.get('id') # BaseModel handles None id in its __init__ if not passed

        return cls(
            id=log_id,
            timestamp=data.get("timestamp", time.time()), # Default to now if missing
            guild_id=data.get("guild_id", ""),
            entry_type=data.get("entry_type", "generic"),
            actor_id=data.get("actor_id"), # Optional, defaults to None
            actor_type=data.get("actor_type"), # Optional, defaults to None
            target_id=data.get("target_id"), # Optional, defaults to None
            target_type=data.get("target_type"), # Optional, defaults to None
            description_i18n=data.get("description_i18n"), # Will be handled if None
            description_i18n=data.get("description_i18n"), 
            description=data.get("description"), # For backward compatibility, __init__ will handle logic
            details=data.get("details", {}) # Default to empty dict if missing or None
        )
        return instance

# Example usage (optional, for testing)
if __name__ == '__main__':
    # Entry with most fields
    log1_data = {
        "guild_id": "guild_main_1",
        "entry_type": "player_command",
        "actor_id": "player_alice_123",
        "actor_type": "player",
        "target_id": "loc_forest_path_456",
        "target_type": "location",
        "description_i18n": {"en": "Player 'Alice' (player_alice_123) used command '/move forest_path (loc_forest_path_456)'", "ru": "Игрок 'Алиса' использовала команду '/move forest_path'"},
        "details": {"command": "/move", "args": ["forest_path"]}
    }
    log1 = GameLogEntry(guild_id=log1_data["guild_id"], entry_type=log1_data["entry_type"], actor_id=log1_data["actor_id"], actor_type=log1_data["actor_type"], target_id=log1_data["target_id"],target_type=log1_data["target_type"], description_i18n=log1_data["description_i18n"],details=log1_data["details"])
    print("Log 1 ID:", log1.id)
    print("Log 1 Timestamp:", log1.timestamp)
    print("Log 1 Dict:", log1.to_dict())
    time.sleep(0.01) # Ensure timestamp difference

    # Entry from dict (simulating loading from DB)
    log2_source_data = {
        "id": "log_entry_fixed_id_002",
        "timestamp": time.time() - 3600, # An hour ago
        "guild_id": "guild_test_2",
        "entry_type": "npc_action",
        "actor_id": "npc_goblin_789",
        "actor_type": "npc",
        "description": "NPC 'Goblin Raider' (npc_goblin_789) moved to 'Cave Entrance'.", # Old format for testing
        "details": {"old_location": "deep_cave", "new_location": "cave_entrance"}
    }
    log2 = GameLogEntry.from_dict(log2_source_data)
    # Test that description was converted
    assert log2.description_i18n == {"en": "NPC 'Goblin Raider' (npc_goblin_789) moved to 'Cave Entrance'."}
    print("\nLog 2 ID:", log2.id)
    print("Log 2 Timestamp:", log2.timestamp)
    print("Log 2 Description (i18n):", log2.description_i18n)
    print("Log 2 Dict:", log2.to_dict())

    # Minimal entry (relying on defaults, using new i18n field)
    log3 = GameLogEntry(guild_id="guild_minimal_3", description_i18n={"en": "System initialized."})
    print("\nLog 3 ID:", log3.id)
    print("Log 3 Timestamp (auto):", log3.timestamp)
    print("Log 3 Description (i18n):", log3.description_i18n)
    print("Log 3 Type (default):", log3.entry_type)
    print("Log 3 Details (default):", log3.details)
    print("Log 3 Dict:", log3.to_dict())

    # Test from_dict with missing optional fields and old description field
    log4_source_data = {
        "guild_id": "guild_missing_fields_4",
        "description": "Quest started." # Old format
        # id, timestamp, entry_type, actor_id etc. are missing
    }
    log4 = GameLogEntry.from_dict(log4_source_data)
    print("\nLog 4 ID (auto):", log4.id)
    print("Log 4 Description (i18n from old):", log4.description_i18n)
    assert log4.description_i18n == {"en": "Quest started."}
    print("Log 4 Timestamp (auto from_dict):", log4.timestamp)
    print("Log 4 Entry Type (default from_dict):", log4.entry_type)
    print("Log 4 Actor ID (default None):", log4.actor_id)
    print("Log 4 Details (default {} from_dict):", log4.details)
    print("Log 4 Dict:", log4.to_dict())

    # Test creation with explicit None for description_i18n (should default to {"en":""})
    log5 = GameLogEntry(
        guild_id="guild_explicit_none_5",
        description_i18n=None, # Explicitly None
        actor_id=None,
        actor_type=None,
        target_id=None,
        target_type=None,
        details=None # __init__ should convert this to {}
    )
    print("\nLog 5 ID:", log5.id)
    print("Log 5 Actor ID (was None):", log5.actor_id)
    print("Log 5 Details (was None, now {}):", log5.details)
    print("Log 5 Dict:", log5.to_dict())

