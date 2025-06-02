# bot/game/models/quest_step.py
from __future__ import annotations
from typing import Optional, Dict, Any
import uuid # Required by BaseModel

from bot.game.models.base_model import BaseModel

class QuestStep(BaseModel):
    """
    Stub model for quest steps.
    """
    def __init__(self, id: Optional[str] = None, placeholder: Optional[str] = None):
        super().__init__(id=id)
        self.placeholder: Optional[str] = placeholder

    def __repr__(self) -> str:
        return f"<QuestStep(id='{self.id}', placeholder='{self.placeholder}')>"

    # to_dict and from_dict are inherited from BaseModel.
