from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

class CheckOutcome(Enum):
    CRITICAL_SUCCESS = "critical_success"  # Actor achieved critical success
    SUCCESS = "success"  # Actor succeeded
    FAILURE = "failure"  # Actor failed
    CRITICAL_FAILURE = "critical_failure"  # Actor critically failed

    # Specific outcomes for opposed checks, can be used to clarify
    # Alternatively, is_success = True/False and actor_crit_status/target_crit_status can convey this
    ACTOR_WINS_OPPOSED = "actor_wins_opposed"
    TARGET_WINS_OPPOSED = "target_wins_opposed"
    TIE_OPPOSED = "tie_opposed"

@dataclass
class DetailedCheckResult:
    check_type: str
    entity_doing_check_id: str # Actor
    target_entity_id: Optional[str] # Target of the check (can be an entity or an object/DC)

    # For DC-based checks
    difficulty_dc: Optional[int] = None

    # Actor's roll details (entity_doing_check)
    actor_roll_formula: str = "1d20"
    actor_rolls: List[int] = field(default_factory=list)
    actor_modifier_applied: int = 0
    actor_modifier_details: List[Dict[str, Any]] = field(default_factory=list)
    actor_total_roll_value: int = 0
    actor_crit_status: Optional[str] = None # e.g., "critical_success", "critical_failure", None

    # Target's roll details (for opposed checks)
    target_roll_formula: Optional[str] = None
    target_rolls: Optional[List[int]] = field(default_factory=list) # Use default_factory for mutable types
    target_modifier_applied: Optional[int] = None
    target_modifier_details: Optional[List[Dict[str, Any]]] = field(default_factory=list) # Use default_factory
    target_total_roll_value: Optional[int] = None
    target_crit_status: Optional[str] = None # e.g., "critical_success", "critical_failure", None

    # Overall outcome
    outcome: CheckOutcome = CheckOutcome.FAILURE # Default outcome
    is_success: bool = False # From the perspective of the actor (entity_doing_check)
    is_critical: bool = False # Was there any critical effect in the check (either actor or target if applicable)?

    description: str = "Check result pending."
