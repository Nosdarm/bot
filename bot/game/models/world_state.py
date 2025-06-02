# bot/game/models/world_state.py
from __future__ import annotations # For type hinting Party in from_dict
from typing import Optional, Dict, Any
import uuid # Required by BaseModel, even if we override id usage

from bot.game.models.base_model import BaseModel

class WorldState(BaseModel):
    """
    Represents a key-value pair for storing global game world state.
    The 'key' attribute serves as the primary key in the database.
    """

    def __init__(self, key: str, value: Optional[str] = None):
        """
        Initializes a WorldState instance.
        The 'key' is used as the identifier for the BaseModel.
        """
        super().__init__(id=key)  # Use 'key' as the 'id' in BaseModel
        self.value: Optional[str] = value
        # Note: self.id from BaseModel now holds the 'key'

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the WorldState instance to a dictionary for serialization.
        Overrides BaseModel.to_dict to use 'key' instead of 'id'.
        """
        return {
            'key': self.id,  # self.id stores the key
            'value': self.value
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorldState:
        """
        Creates a WorldState instance from a dictionary (e.g., from database).
        Overrides BaseModel.from_dict.
        """
        if 'key' not in data:
            raise ValueError("Missing 'key' in data for WorldState.from_dict")
        
        return cls(
            key=data['key'],
            value=data.get('value')
        )

    # If self.key is needed as a separate attribute for some reason, uncomment below
    # @property
    # def key(self) -> str:
    #     return self.id
    
    # @key.setter
    # def key(self, value: str):
    #     self.id = value

    def __repr__(self) -> str:
        return f"<WorldState(key='{self.id}', value='{self.value}')>"
