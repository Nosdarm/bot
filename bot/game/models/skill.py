# bot/game/models/skill.py
from __future__ import annotations
from typing import Optional, Dict, Any
import uuid # Required by BaseModel

from bot.game.models.base_model import BaseModel

class Skill(BaseModel):
    """
    Stub model for skills.
    """
    def __init__(self, id: Optional[str] = None, placeholder: Optional[str] = None):
        super().__init__(id=id)
        self.placeholder: Optional[str] = placeholder

    def __repr__(self) -> str:
        return f"<Skill(id='{self.id}', placeholder='{self.placeholder}')>"

    # to_dict and from_dict are inherited from BaseModel.
