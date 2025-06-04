from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

class CheckOutcome(Enum):
    CRITICAL_SUCCESS = "critical_success"
    SUCCESS = "success"
    FAILURE = "failure"
    CRITICAL_FAILURE = "critical_failure"

@dataclass
class DetailedCheckResult:
    check_type: str
    entity_doing_check_id: str
    target_entity_id: Optional[str]
    difficulty_dc: Optional[int]
    roll_formula: str
    rolls: List[int]
    modifier_applied: int  # The total modifier value that was applied
    modifier_details: List[Dict[str, Any]]  # Breakdown of how the modifier was calculated, e.g., [{"value": 2, "source": "stat:strength"}, {"value": 1, "source": "item:magic_sword"}]
    total_roll_value: int  # sum(rolls) + modifier_applied
    target_value: Optional[int]  # The DC or the result of the target's opposed check
    outcome: CheckOutcome  # Enum value
    is_success: bool
    is_critical: bool
    description: str  # A human-readable summary of the check and its result.
