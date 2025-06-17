from typing import Optional, Dict, Any, List # Ensure List is imported if any field uses it
from pydantic import BaseModel

class CheckResult(BaseModel):
    """
    Represents the outcome of a dice roll check (e.g., skill check, attack roll).
    """
    succeeded: bool
    roll_value: int  # The raw value from the die (e.g., from 1d20)
    modifier_applied: int  # The sum of all modifiers applied to the roll
    total_roll_value: int  # roll_value + modifier_applied

    dc_value: Optional[int] = None  # The difficulty class if it was a check against a DC
    opposed_roll_value: Optional[int] = None # The result of an opponent's roll if it was an opposed check

    description: str  # A human-readable summary of the check and its outcome
                      # e.g., "Stealth Check: 12 (roll) + 3 (mod) = 15 vs DC 18 -> Failure"
                      # e.g., "Attack Roll: 18 (roll) + 7 (mod) = 25 vs AC 20 -> Success"

    # Structured details for logging or more detailed feedback
    # Example: {"base_stat_name": "dexterity", "base_stat_value": 16, "base_modifier": 3,
    #           "bonuses": {"item_boots_of_elvenkind": 2, "status_blessed": 1}, "penalties": {},
    #           "final_modifier_calc": "3 (base) + 2 (item) + 1 (status) = 6"}
    # For this task, an empty dict is fine as a default or if details are simple.
    # The CheckResolver will be responsible for populating this.
    details_log: Dict[str, Any] = {}

    # Optional: Could add individual_rolls if it's useful to store them here too
    # individual_dice_rolls: Optional[List[int]] = None

    class Config:
        # Pydantic V2 Config
        # extra = 'forbid' # Or 'ignore' if you want to be less strict about extra fields from an internal dict

        # Pydantic V1 Config (if project uses V1)
        # anystr_strip_whitespace = True
        pass

if __name__ == '__main__':
    # Example Usage:
    # Success against DC
    success_dc = CheckResult(
        succeeded=True,
        roll_value=15,
        modifier_applied=2,
        total_roll_value=17,
        dc_value=15,
        description="Strength Check: 15 (roll) + 2 (mod) = 17 vs DC 15 -> Success",
        details_log={"base_stat": "strength", "modifier_sources": ["base_str_mod"]}
    )
    print("Success DC Check:", success_dc.model_dump_json(indent=2))

    # Failure against DC
    failure_dc = CheckResult(
        succeeded=False,
        roll_value=8,
        modifier_applied=1,
        total_roll_value=9,
        dc_value=12,
        description="Dexterity Check: 8 (roll) + 1 (mod) = 9 vs DC 12 -> Failure"
    )
    print("\nFailure DC Check:", failure_dc.model_dump_json(indent=2))

    # Opposed check example (assuming success)
    opposed_success = CheckResult(
        succeeded=True,
        roll_value=16,
        modifier_applied=4,
        total_roll_value=20,
        opposed_roll_value=18,
        description="Grapple Check: 16 (roll) + 4 (mod) = 20 vs Opponent's 18 -> Success",
        details_log={"skill": "athletics"}
    )
    print("\nOpposed Success Check:", opposed_success.model_dump_json(indent=2))
