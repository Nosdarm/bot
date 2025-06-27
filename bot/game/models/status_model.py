from __future__ import annotations
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import uuid
import time # For applied_at, current_tick if it represents a timestamp

class StatusEffect(BaseModel): # Renamed to StatusEffect to avoid direct clash if Status is used elsewhere
    """
    Represents an active status effect on an entity.
    This is a Pydantic model for game logic, distinct from the SQLAlchemy DB model.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    static_id: str # Corresponds to the StatusEffectDefinition's static_id or a template ID
    name_i18n: Dict[str, str] = Field(default_factory=dict)
    description_i18n: Optional[Dict[str, str]] = Field(default_factory=dict)

    target_entity_id: str
    target_entity_type: str # E.g., "character", "npc"

    duration_turns: Optional[float] = None # Duration in game turns, if applicable
    max_duration_seconds: Optional[float] = None # Max duration in real-time seconds, if applicable
    applied_at_timestamp: float = Field(default_factory=time.time) # Timestamp when applied

    current_tick: int = 0 # For effects that tick over time/turns

    # Specific effects of this status instance (e.g., actual damage per turn, stat mods)
    # This might be derived from a StatusEffectDefinition template
    effects_data: Dict[str, Any] = Field(default_factory=dict)

    source_ability_id: Optional[str] = None
    source_item_id: Optional[str] = None
    source_entity_id: Optional[str] = None # ID of the entity that applied the status

    is_dispellable: bool = True
    is_visible: bool = True # Whether it shows up on UI

    # For Pydantic model configuration
    class Config:
        extra = 'allow' # Allow extra fields if needed, or change to 'ignore' or 'forbid'

    def get_remaining_duration_turns(self, current_game_turn: Optional[int] = None) -> Optional[float]:
        # This is just an example, actual turn tracking might be more complex
        if self.duration_turns is None:
            return None
        # If current_game_turn is provided and status has an applied_at_turn, calculate remaining
        # For now, assume duration_turns is decremented elsewhere or current_tick tracks progress
        return self.duration_turns - self.current_tick # Simplistic

    def get_remaining_duration_seconds(self) -> Optional[float]:
        if self.max_duration_seconds is None:
            return None
        elapsed = time.time() - self.applied_at_timestamp
        remaining = self.max_duration_seconds - elapsed
        return max(0, remaining)

    def is_expired(self, current_game_turn: Optional[int] = None) -> bool:
        if self.max_duration_seconds is not None:
            if self.get_remaining_duration_seconds() is not None and self.get_remaining_duration_seconds() <= 0: # type: ignore
                return True
        if self.duration_turns is not None:
            # This requires knowing how turns are tracked relative to application
            # For simplicity, if current_tick >= duration_turns, it's expired
            if self.get_remaining_duration_turns(current_game_turn) is not None and self.get_remaining_duration_turns(current_game_turn) <= 0: # type: ignore
                 return True
        return False

    def increment_tick(self):
        self.current_tick += 1

[end of bot/game/models/status_model.py]
