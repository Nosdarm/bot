import random
import re
from typing import Tuple, List, Optional

def roll_dice(dice_string: str) -> Tuple[int, List[int]]:
    """
    Parses a dice string (e.g., "2d6", "1d20+5", "d100-2") and returns the total sum
    and a list of individual die rolls.

    Args:
        dice_string: The dice string to parse.
                     Examples: "2d6", "d20", "1d20+5", "3d8-2".

    Returns:
        A tuple containing:
            - total_sum (int): The sum of all dice rolls plus any modifiers.
            - individual_rolls (List[int]): A list of the outcomes of each die rolled.

    Raises:
        ValueError: If the dice string format is invalid.
    """
    dice_string = dice_string.lower().strip()

    # Regex to capture (num_dice)d(die_sides)(modifier_sign)(modifier_value)
    # Handles optional num_dice (defaults to 1), optional modifier
    match = re.fullmatch(r'(\d*)d(\d+)([+-]\d+)?', dice_string)

    if not match:
        raise ValueError(f"Invalid dice string format: '{dice_string}'. Examples: '2d6', 'd20+3', '1d100-5'.")

    num_dice_str, die_sides_str, modifier_str = match.groups()

    num_dice = int(num_dice_str) if num_dice_str else 1
    die_sides = int(die_sides_str)

    if num_dice <= 0:
        raise ValueError("Number of dice must be positive.")
    if num_dice > 1000: # Practical limit to prevent abuse/performance issues
        raise ValueError("Cannot roll more than 1000 dice at once.")
    if die_sides <= 0:
        raise ValueError("Die sides must be positive.")
    if die_sides > 1000: # Practical limit
        raise ValueError("Die sides cannot exceed 1000.")

    modifier = 0
    if modifier_str:
        modifier = int(modifier_str)

    individual_rolls: List[int] = []
    current_sum = 0

    for _ in range(num_dice):
        roll = random.randint(1, die_sides)
        individual_rolls.append(roll)
        current_sum += roll

    total_sum = current_sum + modifier

    return total_sum, individual_rolls

if __name__ == '__main__':
    # Test cases
    test_inputs = {
        "2d6": (range(2, 13), 2),
        "d20": (range(1, 21), 1),
        "1d20+5": (range(6, 26), 1),
        "3d8-2": (range(1, 23), 3), # 3*1-2=1, 3*8-2=22
        "1d4": (range(1, 5), 1),
        "d100": (range(1, 101), 1),
        "5d10+10": (range(15, 61), 5) # 5*1+10=15, 5*10+10=60
    }
    for dice_str, (expected_range, num_rolls) in test_inputs.items():
        try:
            total, rolls = roll_dice(dice_str)
            print(f"Rolling {dice_str}: Total = {total}, Rolls = {rolls}")
            assert total >= min(expected_range) and total <= max(expected_range), f"Total out of range for {dice_str}"
            assert len(rolls) == num_rolls, f"Incorrect number of rolls for {dice_str}"
        except ValueError as e:
            print(f"Error rolling {dice_str}: {e}")

    error_cases = ["2d", "d", "2d6+d4", "abc", "1d0", "0d6", "1001d6", "1d1001"]
    for dice_str in error_cases:
        try:
            roll_dice(dice_str)
            print(f"Error: Expected ValueError for '{dice_str}' but got no error.")
        except ValueError as e:
            print(f"Correctly caught error for '{dice_str}': {e}")
