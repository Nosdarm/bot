from bot.game.models.base_model import BaseModel
from typing import Dict, Any, Optional, List

class EventOutcome: # Simple placeholder class for event outcomes
    def __init__(self, next_stage_id: str, condition: Optional[Dict[str, Any]] = None):
        self.next_stage_id = next_stage_id
        self.condition = condition or {}

class EventStage(BaseModel): # Represents a stage within an event
    def __init__(self, id: Optional[str] = None, name: str = "Initial Stage", description_template: str = "...", **kwargs):
        super().__init__(id=id)
        self.name = name
        self.description_template = description_template # For AI
        self.duration: Optional[int] = kwargs.pop('duration', None) # Auto advance after X ticks?
        self.on_enter_actions: List[Dict[str, Any]] = kwargs.pop('on_enter_actions', []) # Actions when entering this stage
        self.outcomes: Dict[str, EventOutcome] = {k: EventOutcome(**v) for k, v in kwargs.pop('outcomes', {}).items()} # Possible outcomes

        self.__dict__.update(kwargs)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        # Outcomes need custom to_dict
        data['outcomes'] = {k: {'next_stage_id': v.next_stage_id, 'condition': v.condition} for k, v in self.outcomes.items()}
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
         return cls(**data)


class Event(BaseModel): # Represents an active event in the world
    def __init__(self, id: Optional[str] = None, template_id: str = "unknown_event", name: str = "Unnamed Event",
                 location_id: str = "unknown", channel_id: Optional[int] = None, **kwargs):
        super().__init__(id=id)
        self.template_id = template_id
        self.name = name
        self.location_id = location_id
        self.channel_id: Optional[int] = channel_id # Discord channel where event updates are posted

        self.current_stage_id: str = kwargs.pop('current_stage_id', 'initial')
        self.stages_data: Dict[str, Dict[str, Any]] = kwargs.pop('stages_data', {}) # Raw data for persistence
        self.involved_entities: Dict[str, List[str]] = kwargs.pop('involved_entities', {}) # e.g. {'npcs': [...], 'players': [...]}
        self.state_variables: Dict[str, Any] = kwargs.pop('state_variables', {}) # Event-specific variables (goblin count, etc.)

        self.__dict__.update(kwargs)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            'template_id': self.template_id,
            'name': self.name,
            'location_id': self.location_id,
            'channel_id': self.channel_id,
            'current_stage_id': self.current_stage_id,
            'stages_data': self.stages_data,
            'involved_entities': self.involved_entities,
            'state_variables': self.state_variables,
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        instance = cls(**data)
        instance.stages_data = data.get('stages_data', {})
        return instance

    def get_current_stage(self) -> Optional[EventStage]:
        stage_data = self.stages_data.get(self.current_stage_id)
        if stage_data:
            return EventStage.from_dict(stage_data)
        return None

    def get_stage(self, stage_id: str) -> Optional[EventStage]:
         stage_data = self.stages_data.get(stage_id)
         if stage_data:
              return EventStage.from_dict(stage_data)
         return None