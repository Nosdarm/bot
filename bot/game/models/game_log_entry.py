from __future__ import annotations
import time
import uuid
from typing import Dict, Any, Optional, List # Added List
from bot.game.models.base_model import BaseModel

class GameLogEntry(BaseModel):
    """
    Represents a log entry for game events, aligned with the GameLog SQLAlchemy model.
    """
    def __init__(self,
                 id: Optional[str] = None,
                 timestamp: Optional[float] = None, # Consider aligning with DB (datetime)
                 guild_id: str = "",
                 event_type: str = "generic", # Renamed from entry_type
                 player_id: Optional[str] = None,
                 party_id: Optional[str] = None,
                 location_id: Optional[str] = None,
                 involved_entities_ids: Optional[List[str]] = None, # Or Dict[str, Any]
                 message_key: Optional[str] = None, # Replaces description_i18n
                 message_params: Optional[Dict[str, Any]] = None,
                 details: Optional[Dict[str, Any]] = None, # For structured JSON data
                 channel_id: Optional[str] = None): # Added channel_id from DB model
        super().__init__(id if id is not None else str(uuid.uuid4())) # Ensure ID is generated if None
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.guild_id = guild_id
        self.event_type = event_type
        self.player_id = player_id
        self.party_id = party_id
        self.location_id = location_id
        self.involved_entities_ids = involved_entities_ids if involved_entities_ids is not None else []
        self.message_key = message_key
        self.message_params = message_params if message_params is not None else {}
        self.details = details if details is not None else {}
        self.channel_id = channel_id

        if not self.guild_id:
            # Consider raising ValueError if guild_id is essential
            pass

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the GameLogEntry object to a dictionary."""
        data = super().to_dict() # Gets 'id'
        data.update({
            "timestamp": self.timestamp,
            "guild_id": self.guild_id,
            "event_type": self.event_type,
            "player_id": self.player_id,
            "party_id": self.party_id,
            "location_id": self.location_id,
            "involved_entities_ids": self.involved_entities_ids,
            "message_key": self.message_key,
            "message_params": self.message_params,
            "details": self.details,
            "channel_id": self.channel_id,
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GameLogEntry:
        """Deserializes a dictionary into a GameLogEntry object."""
        return cls(
            id=data.get('id'), # BaseModel's __init__ handles None id
            timestamp=data.get("timestamp", time.time()),
            guild_id=data.get("guild_id", ""),
            event_type=data.get("event_type", "generic"),
            player_id=data.get("player_id"),
            party_id=data.get("party_id"),
            location_id=data.get("location_id"),
            involved_entities_ids=data.get("involved_entities_ids", []),
            message_key=data.get("message_key"),
            message_params=data.get("message_params", {}),
            details=data.get("details", {}),
            channel_id=data.get("channel_id")
        )

# Example usage (optional, for testing - needs to be updated for new fields)
if __name__ == '__main__':
    # Example reflecting new structure
    log1_data = {
        "guild_id": "guild_main_1",
        "event_type": "player_action",
        "player_id": "player_hero_001",
        "location_id": "loc_town_square",
        "message_key": "player.action.move", # Example message key
        "message_params": {"direction": "north", "destination": "market_street"},
        "involved_entities_ids": ["player_hero_001"],
        "details": {"action_cost": 1, "previous_location": "city_gate"},
        "channel_id": "channel_town_chat"
    }
    log1 = GameLogEntry(**log1_data) # Using kwargs for cleaner instantiation
    print("Log 1 ID:", log1.id)
    print("Log 1 Timestamp:", log1.timestamp)
    print("Log 1 Dict:", log1.to_dict())
    time.sleep(0.01)

    # Entry from dict (simulating loading from DB)
    log2_source_data = {
        "id": "log_entry_fixed_id_002",
        "timestamp": time.time() - 3600, # An hour ago
        "guild_id": "guild_test_2",
        "event_type": "system_event",
        "message_key": "system.world.weather_change",
        "message_params": {"new_weather": "rainy", "duration_hours": 2},
        "details": {"severity": "light_rain"},
        "channel_id": "channel_world_events"
    }
    log2 = GameLogEntry.from_dict(log2_source_data)
    print("\nLog 2 ID:", log2.id)
    print("Log 2 Timestamp:", log2.timestamp)
    print("Log 2 Message Key:", log2.message_key)
    print("Log 2 Dict:", log2.to_dict())

    # Minimal entry
    log3 = GameLogEntry(guild_id="guild_minimal_3", event_type="debug", message_key="debug.test.ping")
    print("\nLog 3 ID:", log3.id)
    print("Log 3 Event Type:", log3.event_type)
    print("Log 3 Message Key:", log3.message_key)
    print("Log 3 Details (default):", log3.details)
    print("Log 3 Involved Entities (default):", log3.involved_entities_ids)
    print("Log 3 Dict:", log3.to_dict())

    # Test from_dict with missing optional fields
    log4_source_data = {
        "guild_id": "guild_missing_fields_4",
        "event_type": "quest_update"
        # Most fields missing, should use defaults
    }
    log4 = GameLogEntry.from_dict(log4_source_data)
    print("\nLog 4 ID (auto):", log4.id)
    print("Log 4 Message Key (default None):", log4.message_key)
    print("Log 4 Player ID (default None):", log4.player_id)
    print("Log 4 Involved Entities (default []):", log4.involved_entities_ids)
    print("Log 4 Details (default {}):", log4.details)
    print("Log 4 Dict:", log4.to_dict())

