import random
import re

def roll_dice(dice_string: str) -> tuple[int, list[int]]:
    """
    Rolls dice based on a dice string in the format "NdX+M" or "NdX-M".

    Args:
        dice_string: The string representing the dice to roll.
            N is the number of dice (optional, defaults to 1).
            X is the number of sides per die (required).
            M is the modifier (optional, defaults to 0).

    Returns:
        A tuple containing:
            - The total sum of the rolls plus the modifier (integer).
            - A list of individual die results (list of integers).

    Raises:
        ValueError: If the dice_string is invalid.
    """
    # Regex explanation:
    # ^                  : Start of the string
    # (\d*)              : Optional number of dice (Group 1, num_dice_str). Allows empty string e.g. "d20"
    # d                  : Literal 'd' separating number of dice from sides
    # (\d+)              : Number of sides (Group 2, num_sides_str). Must be present.
    # (?:([+-])(\d+))?   : Optional non-capturing group for modifier
    #   ([+-])           : Operator + or - (Group 3, operator)
    #   (\d+)            : Modifier value (Group 4, modifier_str)
    # $                  : End of the string
    pattern = re.compile(r"^(\d*)d(\d+)(?:([+-])(\d+))?$")
    match = pattern.match(dice_string)

    if not match:
        raise ValueError(
            "Invalid dice string format. Expected format: NdX+M or NdX-M"
        )

    num_dice_str, num_sides_str, operator, modifier_str = match.groups()

    num_dice = int(num_dice_str) if num_dice_str else 1
    num_sides = int(num_sides_str)

    if num_sides == 0:
        raise ValueError("Number of sides cannot be zero.")

    modifier = 0
    if operator and modifier_str:
        modifier_value = int(modifier_str)
        if operator == "-":
            modifier = -modifier_value
        else:
            modifier = modifier_value

    rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
    total_sum = sum(rolls) + modifier

    return total_sum, rolls
