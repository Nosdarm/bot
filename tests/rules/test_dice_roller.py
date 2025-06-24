import unittest
from bot.game.rules.dice_roller import roll_dice

class TestDiceRoller(unittest.TestCase):

    def test_simple_roll_no_modifier(self):
        # Test with "1d6"
        total, details = roll_dice("1d6")
        self.assertTrue(1 <= total <= 6, "Total should be between 1 and 6 for 1d6")
        self.assertEqual(len(details), 1, "Should be 1 die rolled for 1d6")
        self.assertEqual(details[0], total, "Roll detail should equal total for 1d6")
        self.assertTrue(1 <= details[0] <= 6, "Roll detail should be between 1 and 6 for 1d6")

        # Test with "d20"
        total, details = roll_dice("d20")
        self.assertTrue(1 <= total <= 20, "Total should be between 1 and 20 for d20")
        self.assertEqual(len(details), 1, "Should be 1 die rolled for d20")
        self.assertEqual(details[0], total, "Roll detail should equal total for d20")
        self.assertTrue(1 <= details[0] <= 20, "Roll detail should be between 1 and 20 for d20")

    def test_multiple_dice_no_modifier(self):
        # Test with "3d6"
        total, details = roll_dice("3d6")
        self.assertTrue(3 <= total <= 18, "Total should be between 3 and 18 for 3d6")
        self.assertEqual(len(details), 3, "Should be 3 dice rolled for 3d6")
        for roll in details:
            self.assertTrue(1 <= roll <= 6, "Each roll should be between 1 and 6 for 3d6")
        self.assertEqual(sum(details), total, "Sum of roll details should equal total for 3d6")

    def test_simple_roll_with_positive_modifier(self):
        # Test with "1d8+4"
        total, details = roll_dice("1d8+4")
        self.assertTrue(1 + 4 <= total <= 8 + 4, "Total should be between 5 and 12 for 1d8+4")
        self.assertEqual(len(details), 1, "Should be 1 die rolled for 1d8+4")
        self.assertEqual(details[0] + 4, total, "Roll detail + modifier should equal total for 1d8+4")
        self.assertTrue(1 <= details[0] <= 8, "Roll detail should be between 1 and 8 for 1d8+4")

        # Test with "d6+2"
        total, details = roll_dice("d6+2")
        self.assertTrue(1 + 2 <= total <= 6 + 2, "Total should be between 3 and 8 for d6+2")
        self.assertEqual(len(details), 1, "Should be 1 die rolled for d6+2")
        self.assertEqual(details[0] + 2, total, "Roll detail + modifier should equal total for d6+2")
        self.assertTrue(1 <= details[0] <= 6, "Roll detail should be between 1 and 6 for d6+2")

    def test_multiple_dice_with_positive_modifier(self):
        # Test with "2d8+4"
        total, details = roll_dice("2d8+4")
        self.assertTrue(2 * 1 + 4 <= total <= 2 * 8 + 4, "Total should be between 6 and 20 for 2d8+4")
        self.assertEqual(len(details), 2, "Should be 2 dice rolled for 2d8+4")
        for roll in details:
            self.assertTrue(1 <= roll <= 8, "Each roll should be between 1 and 8 for 2d8+4")
        self.assertEqual(sum(details) + 4, total, "Sum of roll details + modifier should equal total for 2d8+4")

    def test_simple_roll_with_negative_modifier(self):
        # Test with "1d10-2"
        total, details = roll_dice("1d10-2")
        # Total can be less than 1 if die roll is small, e.g., 1 - 2 = -1
        self.assertTrue(1 - 2 <= total <= 10 - 2, "Total should be between -1 and 8 for 1d10-2")
        self.assertEqual(len(details), 1, "Should be 1 die rolled for 1d10-2")
        self.assertEqual(details[0] - 2, total, "Roll detail - modifier should equal total for 1d10-2")
        self.assertTrue(1 <= details[0] <= 10, "Roll detail should be between 1 and 10 for 1d10-2")

        # Test with "d20-5"
        total, details = roll_dice("d20-5")
        self.assertTrue(1 - 5 <= total <= 20 - 5, "Total should be between -4 and 15 for d20-5")
        self.assertEqual(len(details), 1, "Should be 1 die rolled for d20-5")
        self.assertEqual(details[0] - 5, total, "Roll detail - modifier should equal total for d20-5")
        self.assertTrue(1 <= details[0] <= 20, "Roll detail should be between 1 and 20 for d20-5")

    def test_multiple_dice_with_negative_modifier(self):
        # Test with "3d4-2"
        total, details = roll_dice("3d4-2")
        self.assertTrue(3 * 1 - 2 <= total <= 3 * 4 - 2, "Total should be between 1 and 10 for 3d4-2")
        self.assertEqual(len(details), 3, "Should be 3 dice rolled for 3d4-2")
        for roll in details:
            self.assertTrue(1 <= roll <= 4, "Each roll should be between 1 and 4 for 3d4-2")
        self.assertEqual(sum(details) - 2, total, "Sum of roll details - modifier should equal total for 3d4-2")

    def test_roll_with_implicit_one_die(self):
        # Test with "d20" (already covered in simple_roll_no_modifier, but good for explicit check)
        total, details = roll_dice("d20")
        self.assertTrue(1 <= total <= 20)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0], total)
        self.assertTrue(1 <= details[0] <= 20)

        # Test with "d6+3"
        total, details = roll_dice("d6+3")
        self.assertTrue(1 + 3 <= total <= 6 + 3)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0] + 3, total)
        self.assertTrue(1 <= details[0] <= 6)

    def test_individual_rolls_details(self):
        # Test with "3d6+5"
        total, details = roll_dice("3d6+5")
        self.assertEqual(len(details), 3, "Should be 3 dice rolled for 3d6+5")
        for roll in details:
            self.assertTrue(1 <= roll <= 6, "Each roll should be between 1 and 6 for 3d6+5")
        self.assertEqual(sum(details) + 5, total, "Sum of roll details + 5 should equal total for 3d6+5")

        # Test with "2d4-1"
        total, details = roll_dice("2d4-1")
        self.assertEqual(len(details), 2, "Should be 2 dice rolled for 2d4-1")
        for roll in details:
            self.assertTrue(1 <= roll <= 4, "Each roll should be between 1 and 4 for 2d4-1")
        self.assertEqual(sum(details) - 1, total, "Sum of roll details - 1 should equal total for 2d4-1")

    def test_roll_with_zero_modifier(self):
        # Test with "1d6+0"
        total, details = roll_dice("1d6+0")
        self.assertTrue(1 <= total <= 6, "Total should be between 1 and 6 for 1d6+0")
        self.assertEqual(len(details), 1, "Should be 1 die rolled for 1d6+0")
        self.assertEqual(details[0], total, "Roll detail should equal total for 1d6+0")

        # Test with "d10+0"
        total, details = roll_dice("d10+0")
        self.assertTrue(1 <= total <= 10, "Total should be between 1 and 10 for d10+0")
        self.assertEqual(len(details), 1, "Should be 1 die rolled for d10+0")
        self.assertEqual(details[0], total, "Roll detail should equal total for d10+0")

        # Test with "2d6-0"
        total, details = roll_dice("2d6-0")
        self.assertTrue(2 <= total <= 12, "Total should be between 2 and 12 for 2d6-0")
        self.assertEqual(len(details), 2, "Should be 2 dice rolled for 2d6-0")
        self.assertEqual(sum(details), total, "Sum of roll details should equal total for 2d6-0")

    def test_invalid_format_empty_string(self):
        with self.assertRaisesRegex(ValueError, "Invalid dice string format"):
            roll_dice("")

    def test_invalid_format_just_d(self):
        with self.assertRaisesRegex(ValueError, "Invalid dice string format"):
            roll_dice("d")

    def test_invalid_format_malformed(self):
        with self.assertRaisesRegex(ValueError, "Invalid dice string format"):
            roll_dice("2d6++5")
        with self.assertRaisesRegex(ValueError, "Invalid dice string format"):
            roll_dice("abc")
        with self.assertRaisesRegex(ValueError, "Invalid dice string format"):
            roll_dice("2d") # Missing sides
        with self.assertRaisesRegex(ValueError, "Invalid dice string format"):
            roll_dice("d+3") # Missing sides
        with self.assertRaisesRegex(ValueError, "Invalid dice string format"):
            roll_dice("2d6p3") # Invalid operator

    def test_zero_dice(self):
        with self.assertRaisesRegex(ValueError, "Number of dice must be positive."):
            roll_dice("0d6")
        with self.assertRaisesRegex(ValueError, "Number of dice must be positive."):
            roll_dice("0d20+5")

    def test_zero_sides(self):
        with self.assertRaisesRegex(ValueError, "Die sides must be positive."): # Corrected expected message
            roll_dice("1d0")
        with self.assertRaisesRegex(ValueError, "Die sides must be positive."): # Corrected expected message
            roll_dice("d0")
        with self.assertRaisesRegex(ValueError, "Die sides must be positive."): # Corrected expected message
            roll_dice("2d0+5")

if __name__ == '__main__':
    unittest.main()
