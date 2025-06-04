# tests/rules/test_rule_engine.py
import unittest
from unittest.mock import MagicMock, patch
import asyncio # Required for IsolatedAsyncioTestCase
from typing import Optional # For type hinting in test methods

from bot.game.rules.rule_engine import RuleEngine
from bot.game.models.character import Character
from bot.game.models.check_models import CheckOutcome, DetailedCheckResult

# If RuleEngine methods are async, test class should inherit from IsolatedAsyncioTestCase
class TestRuleEngine(unittest.IsolatedAsyncioTestCase):

    # Helper for async lambda in mocks if AsyncMock is not directly used for side_effect
    async def _async_return_val(self, val):
        return val

    def test_calculate_attribute_modifier(self):
        rules = {
            "character_stats_rules": {
                "attribute_modifier_formula": "(attribute_value - 10) // 2"
            }
        }
        engine = RuleEngine(rules_data=rules)
        self.assertEqual(engine._calculate_attribute_modifier(10), 0)
        self.assertEqual(engine._calculate_attribute_modifier(12), 1)
        self.assertEqual(engine._calculate_attribute_modifier(15), 2)
        self.assertEqual(engine._calculate_attribute_modifier(7), -2)

        rules_alt_formula = {
            "character_stats_rules": {
                "attribute_modifier_formula": "attribute_value // 3" # Test alternative
            }
        }
        engine_alt = RuleEngine(rules_data=rules_alt_formula)
        self.assertEqual(engine_alt._calculate_attribute_modifier(10), 3)

    def test_generate_initial_character_stats(self):
        expected_stats = {"strength": 12, "dexterity": 11, "constitution": 10, "intelligence": 9, "wisdom": 8, "charisma": 7}
        rules = {
            "character_stats_rules": {
                "default_initial_stats": expected_stats.copy()
            }
        }
        engine = RuleEngine(rules_data=rules)
        initial_stats = engine.generate_initial_character_stats()
        self.assertEqual(initial_stats, expected_stats)
        self.assertIsNot(initial_stats, expected_stats, "Should return a copy") # Check it's a copy

    async def test_resolve_skill_check_success_and_crit(self):
        rules = {
            "skill_rules": {
                "skill_stat_map": {"investigation": "intelligence"}
            },
            "character_stats_rules": {
                "attribute_modifier_formula": "(attribute_value - 10) // 2"
            },
            "check_rules": {
                "default_roll_formula": "1d20",
                "critical_success": {"natural_roll": 20, "auto_succeeds": True},
                "critical_failure": {"natural_roll": 1, "auto_fails": True}
            }
        }
        engine = RuleEngine(rules_data=rules)

        # Mock character
        mock_character = Character(id="char1", discord_user_id=123, name="Tester", name_i18n={"en": "Tester"}, guild_id="test_guild")
        mock_character.stats = {"intelligence": 14} # +2 modifier
        mock_character.skills = {"investigation": 3} # Skill value 3

        # Mock dice roll to control outcome
        # Python's patching of async methods can be tricky.
        # If resolve_dice_roll is async, its mock needs to be an async mock.
        # For simplicity in this example, if resolve_dice_roll is truly async,
        # the test might need adjustment or a more sophisticated mock setup.
        # Assuming resolve_dice_roll can be awaited.

        # Test case 1: Normal success
        with patch.object(engine, 'resolve_dice_roll', new_callable=unittest.mock.AsyncMock, return_value={"total": 15, "rolls": [15]}) as mock_roll_15:
            success, total_val, roll, crit_status = await engine.resolve_skill_check(mock_character, "investigation", 20)
            self.assertTrue(success)
            self.assertEqual(total_val, 20)
            self.assertEqual(roll, 15)
            self.assertIsNone(crit_status)
            mock_roll_15.assert_awaited_once_with("1d20", {}) # context is positional


        # Test case 2: Critical Success
        with patch.object(engine, 'resolve_dice_roll', new_callable=unittest.mock.AsyncMock, return_value={"total": 20, "rolls": [20]}) as mock_roll_20:
            success, _, _, crit_status = await engine.resolve_skill_check(mock_character, "investigation", 25) # DC higher than possible non-crit
            self.assertTrue(success)
            self.assertEqual(crit_status, "critical_success")
            mock_roll_20.assert_awaited_once_with("1d20", {}) # context is positional

        # Test case 3: Critical Failure
        with patch.object(engine, 'resolve_dice_roll', new_callable=unittest.mock.AsyncMock, return_value={"total": 1, "rolls": [1]}) as mock_roll_1:
            success, _, _, crit_status = await engine.resolve_skill_check(mock_character, "investigation", 5) # DC lower than possible non-crit fail
            self.assertFalse(success)
            self.assertEqual(crit_status, "critical_failure")
            mock_roll_1.assert_awaited_once_with("1d20", {}) # context is positional

    async def test_calculate_damage_with_resistance_vulnerability(self):
        rules = {
            "combat_rules": {
                "damage_calculation": {
                    "resistances": {"fire": 0.5},
                    "vulnerabilities": {"cold": 2.0},
                    "immunities": ["poison"]
                }
            },
            "character_stats_rules": { # Needed for stat modifier in damage calc
                "attribute_modifier_formula": "(attribute_value - 10) // 2"
            }
        }
        engine = RuleEngine(rules_data=rules)
        mock_attacker = Character(id="attacker", discord_user_id=124, name="Attacker", name_i18n={"en": "Attacker"}, guild_id="test_guild")
        mock_attacker.stats = {"strength": 10} # +0 modifier for simplicity

        mock_defender = Character(id="defender", discord_user_id=125, name="Defender", name_i18n={"en": "Defender"}, guild_id="test_guild")
        mock_defender.stats = {} # Stats not directly used by defender in this specific test path

        # Mock dice roll for base damage
        with patch.object(engine, 'resolve_dice_roll', new_callable=unittest.mock.AsyncMock, return_value={"total": 10, "rolls": [10]}) as mock_base_damage_roll:
            # Fire damage (resisted)
            damage = await engine.calculate_damage(mock_attacker, mock_defender, "1d10", "fire", False)
            self.assertEqual(damage, 5) # 10 * 0.5
            mock_base_damage_roll.assert_awaited_once_with("1d10", {}) # context is positional
            
            # Cold damage (vulnerable)
            mock_base_damage_roll.reset_mock()
            # Re-patching or ensuring the mock is set up for multiple different return values if needed, or re-assign return_value
            # For this test, return_value is constant, so reset_mock is enough before next assert_awaited_once_with
            damage = await engine.calculate_damage(mock_attacker, mock_defender, "1d10", "cold", False)
            self.assertEqual(damage, 20) # 10 * 2.0
            mock_base_damage_roll.assert_awaited_once_with("1d10", {}) # context is positional

            # Poison damage (immune)
            mock_base_damage_roll.reset_mock()
            damage = await engine.calculate_damage(mock_attacker, mock_defender, "1d10", "poison", False)
            self.assertEqual(damage, 0)
            mock_base_damage_roll.assert_awaited_once_with("1d10", {}) # context is positional


            # Normal damage (unaffected)
            mock_base_damage_roll.reset_mock()
            damage = await engine.calculate_damage(mock_attacker, mock_defender, "1d10", "slashing", False)
            self.assertEqual(damage, 10)
            mock_base_damage_roll.assert_awaited_once_with("1d10", {}) # context is positional
    
    async def test_check_for_level_up(self):
        rules = {
            "general_settings": {"max_character_level": 5},
            "experience_rules": {
                "xp_to_level_up": {
                    "type": "table",
                    "values": {
                        "1": 0, "2": 100, "3": 300, "4": 600, "5": 1000
                    }
                }
            }
        }
        engine = RuleEngine(rules_data=rules)
        # Mock CharacterManager for the mark_character_dirty call
        engine._character_manager = MagicMock()

        char = Character(id="char1", discord_user_id=126, name="LvlUpTester", name_i18n={"en": "LvlUpTester"}, guild_id="test_guild")
        char.level = 1
        char.experience = 0

        # Not enough for level 2
        char.experience = 50
        leveled = await engine.check_for_level_up(char, "test_guild")
        self.assertFalse(leveled)
        self.assertEqual(char.level, 1)

        # Enough for level 2
        char.experience = 100
        leveled = await engine.check_for_level_up(char, "test_guild")
        self.assertTrue(leveled)
        self.assertEqual(char.level, 2)
        self.assertEqual(char.experience, 100)

        # Reset to L1, give enough XP for multiple levels
        char.level = 1
        char.experience = 650 # Enough for L2 (100), L3 (300), L4 (600)

        leveled = await engine.check_for_level_up(char, "test_guild")
        self.assertTrue(leveled)
        self.assertEqual(char.level, 4) # Should reach L4
        self.assertEqual(char.experience, 650)

        # Try to level past max
        char.level = 4 # Start at L4
        char.experience = 2000 # More than enough for level 5 (1000)
        leveled = await engine.check_for_level_up(char, "test_guild")
        self.assertTrue(leveled)
        self.assertEqual(char.level, 5) # Max level

        # Already at max level
        leveled = await engine.check_for_level_up(char, "test_guild")
        self.assertFalse(leveled) # No level up occurred
        self.assertEqual(char.level, 5)

if __name__ == '__main__':
    unittest.main()
