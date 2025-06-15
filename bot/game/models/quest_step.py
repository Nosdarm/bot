# bot/game/models/quest_step.py
from __future__ import annotations
from typing import Optional, Dict, Any, List # List might be needed for type hints if not already used indirectly
import uuid # Required by BaseModel

from bot.game.models.base_model import BaseModel

class QuestStep(BaseModel):
    """
    Represents a single step or task within a quest.
    """
    def __init__(self,
                 id: Optional[str] = None,
                 quest_id: str, # Mandatory
                 guild_id: str, # Mandatory
                 title_i18n: Optional[Dict[str, str]] = None,
                 description_i18n: Optional[Dict[str, str]] = None,
                 requirements_i18n: Optional[Dict[str, str]] = None, # Added
                 required_mechanics_json: str = "{}",
                 abstract_goal_json: str = "{}",
                 conditions_json: str = "{}", # Added
                 step_order: int = 0,
                 status: str = 'pending',
                 assignee_type: str = "",
                 assignee_id: str = "",
                 consequences_json: str = "{}",
                 linked_location_id: Optional[str] = None, # Added
                 linked_npc_id: Optional[str] = None, # Added
                 linked_item_id: Optional[str] = None, # Added
                 linked_guild_event_id: Optional[str] = None): # Added
        super().__init__(id=id)
        self.quest_id: str = quest_id
        self.guild_id: str = guild_id # ADDED
        self.title_i18n: Dict[str, str] = title_i18n if title_i18n is not None else {}
        self.description_i18n: Dict[str, str] = description_i18n if description_i18n is not None else {}
        self.requirements_i18n: Dict[str, str] = requirements_i18n if requirements_i18n is not None else {} # ADDED
        self.required_mechanics_json: str = required_mechanics_json
        self.abstract_goal_json: str = abstract_goal_json
        self.conditions_json: str = conditions_json # ADDED
        self.step_order: int = step_order
        self.status: str = status
        self.assignee_type: str = assignee_type
        self.assignee_id: str = assignee_id
        self.consequences_json: str = consequences_json
        self.linked_location_id: Optional[str] = linked_location_id # ADDED
        self.linked_npc_id: Optional[str] = linked_npc_id # ADDED
        self.linked_item_id: Optional[str] = linked_item_id # ADDED
        self.linked_guild_event_id: Optional[str] = linked_guild_event_id # ADDED

    def __repr__(self) -> str:
        return (f"<QuestStep(id='{self.id}', quest_id='{self.quest_id}', guild_id='{self.guild_id}', " # Added guild_id
                f"title_i18n='{self.title_i18n}', step_order={self.step_order}, "
                f"status='{self.status}', assignee_type='{self.assignee_type}', "
                f"assignee_id='{self.assignee_id}')>")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the quest step to a dictionary."""
        data = super().to_dict()
        data.update({
            'quest_id': self.quest_id,
            'guild_id': self.guild_id, # ADDED
            'title_i18n': self.title_i18n,
            'description_i18n': self.description_i18n,
            'requirements_i18n': self.requirements_i18n, # ADDED
            'required_mechanics_json': self.required_mechanics_json,
            'abstract_goal_json': self.abstract_goal_json,
            'conditions_json': self.conditions_json, # ADDED
            'step_order': self.step_order,
            'status': self.status,
            'assignee_type': self.assignee_type,
            'assignee_id': self.assignee_id,
            'consequences_json': self.consequences_json,
            'linked_location_id': self.linked_location_id, # ADDED
            'linked_npc_id': self.linked_npc_id, # ADDED
            'linked_item_id': self.linked_item_id, # ADDED
            'linked_guild_event_id': self.linked_guild_event_id, # ADDED
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> QuestStep:
        """Deserializes a quest step from a dictionary."""
        quest_step_id = data.pop('id', None)

        # Mandatory fields (Quest.from_dict is responsible for injecting these)
        quest_id = data.pop('quest_id')
        guild_id = data.pop('guild_id')

        # Optional fields
        title_i18n = data.get('title_i18n', {})
        description_i18n = data.get('description_i18n', {})
        requirements_i18n = data.get('requirements_i18n', {}) # ADDED
        required_mechanics_json = data.get('required_mechanics_json', '{}')
        abstract_goal_json = data.get('abstract_goal_json', '{}')
        conditions_json = data.get('conditions_json', '{}') # ADDED
        step_order = data.get('step_order', 0)
        status = data.get('status', 'pending')
        assignee_type = data.get('assignee_type', "")
        assignee_id = data.get('assignee_id', "")
        consequences_json = data.get('consequences_json', '{}')
        linked_location_id = data.get('linked_location_id') # ADDED (default None)
        linked_npc_id = data.get('linked_npc_id') # ADDED (default None)
        linked_item_id = data.get('linked_item_id') # ADDED (default None)
        linked_guild_event_id = data.get('linked_guild_event_id') # ADDED (default None)


        return cls(id=quest_step_id,
                   quest_id=quest_id,
                   guild_id=guild_id, # ADDED
                   title_i18n=title_i18n,
                   description_i18n=description_i18n,
                   requirements_i18n=requirements_i18n, # ADDED
                   required_mechanics_json=required_mechanics_json,
                   abstract_goal_json=abstract_goal_json,
                   conditions_json=conditions_json, # ADDED
                   step_order=step_order,
                   status=status,
                   assignee_type=assignee_type,
                   assignee_id=assignee_id,
                   consequences_json=consequences_json,
                   linked_location_id=linked_location_id, # ADDED
                   linked_npc_id=linked_npc_id, # ADDED
                   linked_item_id=linked_item_id, # ADDED
                   linked_guild_event_id=linked_guild_event_id) # ADDED
