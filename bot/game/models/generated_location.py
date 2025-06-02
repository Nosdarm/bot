# bot/game/models/generated_location.py
from __future__ import annotations
from typing import Optional, Dict, Any
import uuid # Required by BaseModel

from bot.game.models.base_model import BaseModel

class GeneratedLocation(BaseModel):
    """
    Stub model for generated locations.
    """
    def __init__(self, id: Optional[str] = None, placeholder: Optional[str] = None):
        super().__init__(id=id)
        self.placeholder: Optional[str] = placeholder

    def __repr__(self) -> str:
        return f"<GeneratedLocation(id='{self.id}', placeholder='{self.placeholder}')>"

    # to_dict and from_dict are inherited from BaseModel.
    # BaseModel.to_dict() will return {'id': self.id, 'placeholder': self.placeholder}
    # if placeholder is added to self.__dict__ by __init__, which it is.
    # BaseModel.from_dict(data) will call cls(**data), so it will correctly pass id and placeholder
    # to __init__ if they are in data.
