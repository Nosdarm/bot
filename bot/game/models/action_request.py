import uuid
import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class ActionRequest(BaseModel):
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    guild_id: str
    actor_id: str  # Player character ID or NPC ID
    action_type: str  # e.g., "MOVE", "ATTACK", "USE_SKILL", "NPC_THINK"
    action_data: Dict[str, Any] = Field(default_factory=dict)  # Specific parameters for the action
    priority: int = 10  # Lower numbers execute first
    requested_at: float = Field(default_factory=time.time)
    execute_at: float = Field(default_factory=time.time)  # Timestamp for delayed actions
    dependencies: List[str] = Field(default_factory=list)  # List of action_ids
    status: str = "pending"  # pending, processing, completed, failed, cancelled
    result: Optional[Dict[str, Any]] = None

    class Config:
        # For Pydantic V2, use model_config instead of Config class if applicable
        # Pydantic V1 example:
        # anystr_strip_whitespace = True # Removed as it's not standard and depends on Pydantic version features
        validate_assignment = True

    def __lt__(self, other: "ActionRequest") -> bool:
        # Ensures sorting by execute_at time first, then by priority (lower number is higher priority)
        if self.execute_at != other.execute_at:
            return self.execute_at < other.execute_at
        # For same execute_at time, sort by priority. Lower priority number means earlier execution.
        return self.priority < other.priority
