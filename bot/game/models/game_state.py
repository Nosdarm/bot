from bot.game.models.base_model import BaseModel
from typing import Dict, Any, Optional
from bot.game.models.event import Event # Import Event model

class GameState(BaseModel):
    def __init__(self, id: Optional[str] = None, server_id: int = 0, start_location_id: str = "unknown", **kwargs):
        super().__init__(id=id)
        self.server_id: int = server_id
        self.start_location_id: str = start_location_id

        # --- New Fields for GM and Channel Mapping ---
        self.gm_user_id: Optional[int] = kwargs.pop('gm_user_id', None)
        self.gm_channel_id: Optional[int] = kwargs.pop('gm_channel_id', None)
        self.location_channel_map: Dict[str, int] = kwargs.pop('location_channel_map', {}) # location_id -> channel_id


        # Data containers managed by child managers.
        # Stored here for persistence.
        self.characters_data: Dict[str, Dict[str, Any]] = {}
        self.locations_data: Dict[str, Dict[str, Any]] = {}
        self.npcs_data: Dict[str, Dict[str, Any]] = {} # Placeholder
        self.items_data: Dict[str, Dict[str, Any]] = {} # Placeholder
        self.active_events_data: Dict[str, Dict[str, Any]] = kwargs.pop('active_events_data', {}) # Event data
        # Add data containers for other entities: combat, status effects list, etc.

        self.__dict__.update(kwargs)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data.update({
            'server_id': self.server_id,
            'start_location_id': self.start_location_id,
            'gm_user_id': self.gm_user_id,
            'gm_channel_id': self.gm_channel_id,
            'location_channel_map': self.location_channel_map,
            'characters': self.characters_data, # Save the data containers
            'locations': self.locations_data,
            'npcs': self.npcs_data, # Placeholder
            'items': self.items_data, # Placeholder
            'active_events': self.active_events_data, # Save event data
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        instance = cls(**data)
        instance.characters_data = data.get('characters', {})
        instance.locations_data = data.get('locations', {})
        instance.npcs_data = data.get('npcs', {}) # Placeholder
        instance.items_data = data.get('items', {}) # Placeholder
        instance.active_events_data = data.get('active_events', {}) # Load event data
        return instance