from __future__ import annotations
import uuid
from typing import Dict, Any, List, Optional
from bot.game.models.base_model import BaseModel

class Quest(BaseModel):
    """
    Represents a quest in the game.
    """
    def __init__(self,
                 id: Optional[str] = None,
                 name: str = "Unnamed Quest",
                 description: str = "",
                 status: str = "available",
                 influence_level: str = "local",
                 prerequisites: Optional[List[str]] = None,
                 connections: Optional[Dict[str, List[str]]] = None,
                 stages: Optional[Dict[str, Any]] = None,
                 rewards: Optional[Dict[str, Any]] = None,
                 npc_involvement: Optional[Dict[str, str]] = None,
                 guild_id: str = ""):
        super().__init__(id)
        self.name = name
        self.description = description
        self.status = status
        self.influence_level = influence_level
        self.prerequisites = prerequisites if prerequisites is not None else []
        self.connections = connections if connections is not None else {}
        self.stages = stages if stages is not None else {}
        self.rewards = rewards if rewards is not None else {}
        self.npc_involvement = npc_involvement if npc_involvement is not None else {}
        self.guild_id = guild_id

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the Quest object to a dictionary."""
        data = super().to_dict() # Gets 'id'
        data.update({
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "influence_level": self.influence_level,
            "prerequisites": self.prerequisites,
            "connections": self.connections,
            "stages": self.stages,
            "rewards": self.rewards,
            "npc_involvement": self.npc_involvement,
            "guild_id": self.guild_id,
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Quest:
        """Deserializes a dictionary into a Quest object."""
        # BaseModel.from_dict is too generic, we'll handle instantiation here
        # but leverage its id handling if needed, or just do it directly.
        # For Quest, we have many specific fields with defaults.

        # Ensure 'id' is handled, even if it comes from BaseModel's logic or is directly in data
        quest_id = data.get('id')
        if quest_id is None:
             quest_id = str(uuid.uuid4())


        return cls(
            id=quest_id,
            name=data.get("name", "Unnamed Quest"),
            description=data.get("description", ""),
            status=data.get("status", "available"),
            influence_level=data.get("influence_level", "local"),
            prerequisites=data.get("prerequisites", []),
            connections=data.get("connections", {}),
            stages=data.get("stages", {}),
            rewards=data.get("rewards", {}),
            npc_involvement=data.get("npc_involvement", {}),
            guild_id=data.get("guild_id", "")
        )

# Example usage (optional, for testing)
if __name__ == '__main__':
    # Create a sample quest
    quest_data = {
        "name": "The Lost Artifact",
        "description": "An ancient artifact has been lost, and it's up to you to find it.",
        "guild_id": "guild_123",
        "rewards": {"experience": 100, "items": ["rare_sword_id"]},
        "npc_involvement": {"giver": "npc_elder_1", "target_location": "dungeon_of_shadows"}
    }
    quest1 = Quest.from_dict(quest_data)
    quest1.status = "active"
    quest1.prerequisites.append("previous_quest_completed")

    print("Quest 1 ID:", quest1.id)
    print("Quest 1 Dict:", quest1.to_dict())

    # Create another quest with minimal data to test defaults
    quest2_data = {
        "id": "fixed_quest_id_002",
        "name": "Simple Task",
        "guild_id": "guild_456"
    }
    quest2 = Quest.from_dict(quest2_data)
    print("\nQuest 2 ID:", quest2.id)
    print("Quest 2 Dict:", quest2.to_dict())

    # Test creation with no data (should use all defaults)
    quest3 = Quest()
    print("\nQuest 3 ID:", quest3.id)
    print("Quest 3 Dict:", quest3.to_dict())
    quest3.guild_id = "guild_789" # Set required field if not passed in init
    print("Quest 3 Dict (after guild_id):", quest3.to_dict())

    # Test creation with explicit None for optional fields
    quest4_data = {
        "name": "Test None Quest",
        "guild_id": "guild_abc",
        "prerequisites": None,
        "connections": None,
        "stages": None,
        "rewards": None,
        "npc_involvement": None,
    }
    quest4 = Quest.from_dict(quest4_data)
    print("\nQuest 4 ID:", quest4.id)
    print("Quest 4 Dict:", quest4.to_dict())

    # Verifying BaseModel's id creation
    base_instance = BaseModel()
    print(f"\nBaseModel instance ID: {base_instance.id}")
    base_instance_with_id = BaseModel(id="custom_id_base")
    print(f"BaseModel instance with custom ID: {base_instance_with_id.id}")

    quest_instance_no_id = Quest(guild_id="test_guild")
    print(f"Quest instance (no id provided) ID: {quest_instance_no_id.id}")
    quest_instance_with_id = Quest(id="custom_id_quest", guild_id="test_guild")
    print(f"Quest instance (id provided) ID: {quest_instance_with_id.id}")

    # Checking from_dict behavior with an ID present in the dictionary
    quest_from_dict_with_id = Quest.from_dict({"id": "existing_id_123", "name": "From Dict With ID", "guild_id": "test_guild"})
    print(f"Quest from_dict (id in data) ID: {quest_from_dict_with_id.id}, Name: {quest_from_dict_with_id.name}")

    # Checking from_dict behavior without an ID in the dictionary
    quest_from_dict_no_id = Quest.from_dict({"name": "From Dict No ID", "guild_id": "test_guild"})
    print(f"Quest from_dict (no id in data) ID: {quest_from_dict_no_id.id}, Name: {quest_from_dict_no_id.name}")

```
