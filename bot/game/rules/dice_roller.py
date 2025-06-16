import re
import random
from typing import Tuple, List, Optional

def roll_dice(dice_string: str) -> Tuple[int, List[int]]:
    """
    Rolls dice based on a dice string notation (e.g., "2d6", "1d20+5", "d8-1").

    The format is XdY[+|-Z], where:
    - X is the number of dice (optional, defaults to 1).
    - Y is the number of sides on each die (required).
    - Z is a modifier to be added to or subtracted from the total sum (optional).

    Args:
        dice_string: A string representing the dice to roll.
                     Examples: "d6", "2d10", "1d20+5", "3d8-2".

    Returns:
        A tuple containing:
        - total (int): The sum of all dice rolls plus/minus the modifier.
        - rolls (List[int]): A list of individual dice roll results.

    Raises:
        ValueError: If the dice_string format is invalid, or if the number of
                    dice or sides is not a positive integer.
    """
    # Regex to capture: (num_dice)d(sides)(modifier_group(modifier_sign)(modifier_value))
    # It allows for optional spaces around components.
    pattern = re.compile(r"^\s*(\d*)d(\d+)\s*(([+\-])\s*(\d+))?\s*$", re.IGNORECASE)
    match = pattern.fullmatch(dice_string.strip())

    if not match:
        raise ValueError(f"Invalid dice string format: '{dice_string}'. Expected format like 'XdY[+/-Z]'.")

    num_dice_str, sides_str, modifier_group, modifier_sign, modifier_val_str = match.groups()

    try:
        num_dice = int(num_dice_str) if num_dice_str else 1
        sides = int(sides_str)
    except ValueError:
        # This should ideally not be reached if regex is correct and inputs are digits
        raise ValueError("Number of dice and sides must be integers.")

    if num_dice <= 0:
        raise ValueError(f"Number of dice must be positive. Got: {num_dice_str or 1}")
    if sides <= 0:
        raise ValueError(f"Number of sides on a die must be positive. Got: {sides}")
    if sides == 1 and num_dice > 100: # d1 can be abused for large sums quickly
        raise ValueError("Cannot roll more than 100 dice if sides is 1.")
    if num_dice > 1000: # General sanity limit for number of dice
        raise ValueError("Cannot roll more than 1000 dice at once.")


    modifier = 0
    if modifier_group: # If the entire modifier group (e.g., "+5", "- 2") exists
        try:
            modifier_val = int(modifier_val_str)
            if modifier_sign == '-':
                modifier = -modifier_val
            else:
                modifier = modifier_val
        except ValueError:
            # This should ideally not be reached if regex ensures modifier_val_str is digits
            raise ValueError("Modifier value must be an integer.")

    rolls: List[int] = []
    current_sum = 0

    for _ in range(num_dice):
        roll = random.randint(1, sides)
        rolls.append(roll)
        current_sum += roll

    total_after_modifier = current_sum + modifier

    return total_after_modifier, rolls

if __name__ == '__main__':
    # Test cases
    test_dice_strings = [
        "2d6", "d20", "1d20+5", "3d8-2", "d6+1", " d100 ", "4d4 + 3", "1d6 - 1",
        "10d1", # 10 dice, 1 side each
    ]
    print("Running test cases for roll_dice():")
    for ds in test_dice_strings:
        try:
            total, rolls = roll_dice(ds)
            print(f"'{ds}': Total = {total}, Rolls = {rolls}")
        except ValueError as e:
            print(f"Error rolling '{ds}': {e}")

    print("\nTesting invalid formats:")
    invalid_dice_strings = [
        "d", "2d", "d6+", "2d6-", "abc", "1d0", "0d6", "-1d6", "d-6", "1d20+5-2", "1d6+ 2d4",
        "1001d6", "101d1", "1d20 + foo"
    ]
    for ds_invalid in invalid_dice_strings:
        try:
            roll_dice(ds_invalid)
            print(f"Error: Invalid string '{ds_invalid}' was not caught.")
        except ValueError as e:
            print(f"Correctly caught error for '{ds_invalid}': {e}")

    # Example of large number of dice rolls (within limits)
    try:
        total, rolls = roll_dice("100d6")
        print(f"'100d6': Total = {total}, Rolls count = {len(rolls)} (first 10: {rolls[:10]})")
    except ValueError as e:
        print(f"Error rolling '100d6': {e}")

    # Example of d1
    try:
        total, rolls = roll_dice("5d1+2") # Should be 5*1 + 2 = 7
        print(f"'5d1+2': Total = {total}, Rolls = {rolls}")
    except ValueError as e:
        print(f"Error rolling '5d1+2': {e}")
