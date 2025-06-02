from bot.game.models.base_model import BaseModel
from typing import Dict, Any, Optional, List

class EventOutcome: # Simple placeholder class for event outcomes
    def __init__(self, next_stage_id: str, condition: Optional[Dict[str, Any]] = None):
        self.next_stage_id = next_stage_id
        self.condition = condition or {}

class EventStage(BaseModel): # Represents a stage within an event
    def __init__(self, id: Optional[str] = None, 
                 name_i18n: Optional[Dict[str, str]] = None, 
                 description_template_i18n: Optional[Dict[str, str]] = None, 
                 **kwargs):
        super().__init__(id=id)

        # Handle name_i18n and backward compatibility for 'name'
        if name_i18n is not None:
            self.name_i18n = name_i18n
        elif 'name' in kwargs:
            self.name_i18n = {"en": kwargs.pop('name')}
        else:
            self.name_i18n = {"en": "Initial Stage"}

        # Handle description_template_i18n and backward compatibility for 'description_template'
        if description_template_i18n is not None:
            self.description_template_i18n = description_template_i18n
        elif 'description_template' in kwargs:
            self.description_template_i18n = {"en": kwargs.pop('description_template')}
        else:
            self.description_template_i18n = {"en": "..."}
            
        self.duration: Optional[int] = kwargs.pop('duration', None) # Auto advance after X ticks?
        self.on_enter_actions: List[Dict[str, Any]] = kwargs.pop('on_enter_actions', []) # Actions when entering this stage
        self.outcomes: Dict[str, EventOutcome] = {k: EventOutcome(**v) for k, v in kwargs.pop('outcomes', {}).items()} # Possible outcomes

        self.__dict__.update(kwargs)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data['name_i18n'] = self.name_i18n
        data['description_template_i18n'] = self.description_template_i18n
        data['duration'] = self.duration
        data['on_enter_actions'] = self.on_enter_actions
        # Outcomes need custom to_dict
        data['outcomes'] = {k: {'next_stage_id': v.next_stage_id, 'condition': v.condition} for k, v in self.outcomes.items()}
        # Include any other attributes dynamically added via kwargs
        for key, value in self.__dict__.items():
            if key not in data and key not in ['id', '_id', 'name_i18n', 'description_template_i18n', 'duration', 'on_enter_actions', 'outcomes']:
                data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        data_copy = data.copy()
        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {"en": data_copy.pop("name")}
        if "description_template" in data_copy and "description_template_i18n" not in data_copy:
            data_copy["description_template_i18n"] = {"en": data_copy.pop("description_template")}
        return cls(**data_copy)


class Event(BaseModel): # Represents an active event in the world
    def __init__(self, id: Optional[str] = None, template_id: str = "unknown_event", 
                 name_i18n: Optional[Dict[str, str]] = None,
                 location_id: str = "unknown", channel_id: Optional[int] = None, **kwargs):
        super().__init__(id=id)
        self.template_id = template_id
        
        if name_i18n is not None:
            self.name_i18n = name_i18n
        elif 'name' in kwargs:
            self.name_i18n = {"en": kwargs.pop('name')}
        else:
            # Attempt to get 'name' if it was passed as a direct argument in older versions
            name_arg = kwargs.pop('name', None) if 'name' not in self.__dict__ else self.__dict__.get('name')
            if name_arg:
                 self.name_i18n = {"en": name_arg}
            else:
                 self.name_i18n = {"en": "Unnamed Event"}
                 
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
            'name_i18n': self.name_i18n,
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
        data_copy = data.copy()
        if "name" in data_copy and "name_i18n" not in data_copy:
            data_copy["name_i18n"] = {"en": data_copy.pop("name")}
        
        instance = cls(**data_copy)
        # stages_data is explicitly set as it might not be in kwargs if data_copy was manipulated
        instance.stages_data = data_copy.get('stages_data', {}) 
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