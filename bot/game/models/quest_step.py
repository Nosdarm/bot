# bot/game/models/quest_step.py
from __future__ import annotations
from typing import Optional, Dict, Any # List removed as it's not needed
import uuid # Required by BaseModel

from bot.game.models.base_model import BaseModel

class QuestStep(BaseModel):
    """
    Represents a single step or task within a quest.
    """
    def __init__(self,
                 id: Optional[str] = None,
                 quest_id: str = "", # Made quest_id mandatory, empty string default might not be ideal
                 title_i18n: Optional[Dict[str, str]] = None,
                 description_i18n: Optional[Dict[str, str]] = None,
                 required_mechanics_json: str = "{}",
                 abstract_goal_json: str = "{}",
                 step_order: int = 0,
                 status: str = 'pending',
                 assignee_type: str = "", # e.g. 'player' or 'party', mandatory ""
                 assignee_id: str = "", # player_id or party_id, mandatory ""
                 consequences_json: str = "{}"):
        super().__init__(id=id)
        self.quest_id: str = quest_id
        self.title_i18n: Dict[str, str] = title_i18n if title_i18n is not None else {}
        self.description_i18n: Dict[str, str] = description_i18n if description_i18n is not None else {}
        self.required_mechanics_json: str = required_mechanics_json
        self.abstract_goal_json: str = abstract_goal_json
        self.step_order: int = step_order
        self.status: str = status
        self.assignee_type: str = assignee_type
        self.assignee_id: str = assignee_id
        self.consequences_json: str = consequences_json

    def __repr__(self) -> str:
        return (f"<QuestStep(id='{self.id}', quest_id='{self.quest_id}', "
                f"title_i18n='{self.title_i18n}', step_order={self.step_order}, "
                f"status='{self.status}', assignee_type='{self.assignee_type}', "
                f"assignee_id='{self.assignee_id}')>")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the quest step to a dictionary."""
        data = super().to_dict()
        data.update({
            'quest_id': self.quest_id,
            'title_i18n': self.title_i18n,
            'description_i18n': self.description_i18n,
            'required_mechanics_json': self.required_mechanics_json,
            'abstract_goal_json': self.abstract_goal_json,
            'step_order': self.step_order,
            'status': self.status,
            'assignee_type': self.assignee_type,
            'assignee_id': self.assignee_id,
            'consequences_json': self.consequences_json,
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> QuestStep:
        """Deserializes a quest step from a dictionary."""
        # BaseModel.from_dict will handle 'id' if it's in data, or generate a new one.
        # However, our BaseModel doesn't have a from_dict, so we handle id here.
        quest_step_id = data.pop('id', None)

        # Extract QuestStep-specific fields
        quest_id = data.get('quest_id', "")
        title_i18n = data.get('title_i18n', {})
        description_i18n = data.get('description_i18n', {})
        required_mechanics_json = data.get('required_mechanics_json', '{}')
        abstract_goal_json = data.get('abstract_goal_json', '{}')
        step_order = data.get('step_order', 0)
        status = data.get('status', 'pending')
        assignee_type = data.get('assignee_type', "")
        assignee_id = data.get('assignee_id', "")
        consequences_json = data.get('consequences_json', '{}')

        return cls(id=quest_step_id,
                   quest_id=quest_id,
                   title_i18n=title_i18n,
                   description_i18n=description_i18n,
                   required_mechanics_json=required_mechanics_json,
                   abstract_goal_json=abstract_goal_json,
                   step_order=step_order,
                   status=status,
                   assignee_type=assignee_type,
                   assignee_id=assignee_id,
                   consequences_json=consequences_json)
