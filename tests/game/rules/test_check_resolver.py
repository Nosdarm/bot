import asyncio
import unittest
from unittest.mock import patch, MagicMock # For mocking roll_dice
from typing import Dict, Any, List, Optional

from bot.ai.rules_schema import CoreGameRulesConfig, CheckDefinition
from bot.game.rules.check_resolver import resolve_check, CheckResult
# We will mock bot.game.rules.dice_roller.roll_dice, so direct import not strictly needed here for that.

# --- Mock Effective Stats ---
MOCK_EFFECTIVE_STATS_DB_FOR_TESTS: Dict[str, Dict[str, Any]] = {
    "player_1": {"strength": 2, "dexterity": 3, "wisdom": 2, "perception": 3, "stealth": 5, "athletics": 1},
    "npc_1": {"strength": 1, "dexterity": 1, "wisdom": 0, "perception": 1, "stealth": -1},
    "player_high_perception": {"wisdom": 5, "perception": 5}, # For opposed perception
    "player_crit_tester": {"strength": 0} # For crit tests with no modifier
}

def get_mock_entity_effective_stats(entity_id: str, entity_type: str) -> Dict[str, Any]:
    # entity_type is ignored for this mock for simplicity in tests
    return MOCK_EFFECTIVE_STATS_DB_FOR_TESTS.get(entity_id, {})

class TestCheckResolver(unittest.TestCase):

    def _create_sample_rules_config(self) -> CoreGameRulesConfig:
        """Helper to create a CoreGameRulesConfig with sample check definitions."""
        return CoreGameRulesConfig(
            checks={
                "perception_dc15_beat": CheckDefinition(
                    dice_formula="1d20", base_dc=15, affected_by_stats=["wisdom", "perception"],
                    crit_success_threshold=20, crit_fail_threshold=1, success_on_beat_dc=True
                ),
                "athletics_dc10_meet": CheckDefinition(
                    dice_formula="1d20", base_dc=10, affected_by_stats=["strength", "athletics"],
                    crit_success_threshold=20, crit_fail_threshold=1, success_on_beat_dc=False
                ),
                "stealth_vs_perception": CheckDefinition( # For contested
                    dice_formula="1d20", affected_by_stats=["dexterity", "stealth"],
                    opposed_check_type="perception_dc15_beat", # Target rolls this
                    crit_success_threshold=20, crit_fail_threshold=1, success_on_beat_dc=True
                ),
                "no_mod_crit_check": CheckDefinition( # For testing crits without modifiers
                    dice_formula="1d20", base_dc=10, affected_by_stats=["strength"], # strength is 0 for crit_tester
                    crit_success_threshold=20, crit_fail_threshold=1, success_on_beat_dc=True
                ),
            },
            # Other parts of CoreGameRulesConfig can be empty or minimal for these tests
            damage_types={}, xp_rules=None, loot_tables={}, action_conflicts=[],
            location_interactions={}, base_stats={}, equipment_slots={},
            item_effects={}, status_effects={}
        )

    @patch('bot.game.rules.check_resolver.roll_dice') # Path to roll_dice as used in check_resolver.py
    def test_simple_check_success_beat_dc(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()
        mock_roll_dice.return_value = (12, [12]) # roll_total, [individual_rolls]

        # player_1 stats: wisdom=2, perception=3. Total mod = 5.
        # DC = 15. success_on_beat_dc = True.
        # Roll 12 + 5 = 17. 17 > 15 = Success.
        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="perception_dc15_beat",
            entity_doing_check_id="player_1", entity_doing_check_type="player"
        ))

        self.assertEqual(result['outcome'], "success")
        self.assertTrue(result['succeeded'])
        self.assertEqual(result['modifier'], 5)
        self.assertEqual(result['roll_details']['total'], 12)
        self.assertEqual(result['final_result'], 17)
        self.assertEqual(result['dc_or_vs_result'], 15)

    @patch('bot.game.rules.check_resolver.roll_dice')
    def test_simple_check_fail_beat_dc(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()
        mock_roll_dice.return_value = (9, [9])
        # player_1 mod = 5. DC = 15. success_on_beat_dc = True.
        # Roll 9 + 5 = 14. 14 not > 15 = Fail.
        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="perception_dc15_beat",
            entity_doing_check_id="player_1", entity_doing_check_type="player"
        ))
        self.assertEqual(result['outcome'], "fail")
        self.assertFalse(result['succeeded'])
        self.assertEqual(result['final_result'], 14)

    @patch('bot.game.rules.check_resolver.roll_dice')
    def test_simple_check_success_meet_dc(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()
        mock_roll_dice.return_value = (9, [9])
        # player_1 stats: strength=2, athletics=1. Total mod = 3.
        # DC = 10. success_on_beat_dc = False (so >= is success).
        # Roll 9 + 3 = 12. 12 >= 10 = Success.
        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="athletics_dc10_meet",
            entity_doing_check_id="player_1", entity_doing_check_type="player"
        ))
        self.assertEqual(result['outcome'], "success")
        self.assertTrue(result['succeeded'])
        self.assertEqual(result['final_result'], 12)
        self.assertEqual(result['dc_or_vs_result'], 10)

    @patch('bot.game.rules.check_resolver.roll_dice')
    def test_simple_check_fail_meet_dc(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()
        mock_roll_dice.return_value = (6, [6])
        # player_1 mod = 3. DC = 10. success_on_beat_dc = False.
        # Roll 6 + 3 = 9. 9 not >= 10 = Fail.
        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="athletics_dc10_meet",
            entity_doing_check_id="player_1", entity_doing_check_type="player"
        ))
        self.assertEqual(result['outcome'], "fail")
        self.assertFalse(result['succeeded'])
        self.assertEqual(result['final_result'], 9)

    @patch('bot.game.rules.check_resolver.roll_dice')
    @patch('bot.game.rules.check_resolver.get_entity_effective_stats', new=get_mock_entity_effective_stats) # Patch get_entity_effective_stats for this test
    def test_contested_check_attacker_wins(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()

        # Attacker (player_1, stealth) rolls 15. Mod = dex(3)+stealth(5) = 8. Final = 23
        # Defender (npc_1, perception) rolls 10. Mod = wis(0)+perception(1) = 1. Final = 11
        # DC for attacker becomes 11. 23 > 11 = Success for attacker.
        mock_roll_dice.side_effect = [
            (15, [15]), # Attacker's roll (stealth)
            (10, [10])  # Defender's roll (perception)
        ]

        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="stealth_vs_perception",
            entity_doing_check_id="player_1", entity_doing_check_type="player",
            target_entity_id="npc_1", target_entity_type="npc"
        ))

        self.assertEqual(result['outcome'], "success")
        self.assertTrue(result['succeeded'])
        self.assertEqual(result['modifier'], 8) # player_1's stealth mod
        self.assertEqual(result['final_result'], 23) # 15 (roll) + 8 (mod)
        self.assertEqual(result['dc_or_vs_result'], 11) # npc_1's perception result: 10 (roll) + 1 (mod)

    @patch('bot.game.rules.check_resolver.roll_dice')
    @patch('bot.game.rules.check_resolver.get_entity_effective_stats', new=get_mock_entity_effective_stats)
    def test_contested_check_defender_wins(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()
        # Attacker (player_1, stealth) rolls 5. Mod = 8. Final = 13
        # Defender (npc_1, perception) rolls 15. Mod = 1. Final = 16
        # DC for attacker becomes 16. 13 not > 16 = Fail for attacker.
        mock_roll_dice.side_effect = [(5, [5]), (15, [15])]

        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="stealth_vs_perception",
            entity_doing_check_id="player_1", entity_doing_check_type="player",
            target_entity_id="npc_1", target_entity_type="npc"
        ))
        self.assertEqual(result['outcome'], "fail")
        self.assertFalse(result['succeeded'])
        self.assertEqual(result['final_result'], 13)
        self.assertEqual(result['dc_or_vs_result'], 16)

    @patch('bot.game.rules.check_resolver.roll_dice')
    @patch('bot.game.rules.check_resolver.get_entity_effective_stats', new=get_mock_entity_effective_stats)
    def test_critical_success(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()
        # Rule: no_mod_crit_check, crit_success_threshold: 20. DC 10.
        # player_crit_tester has strength: 0, so mod is 0.
        mock_roll_dice.return_value = (20, [20]) # Natural 20

        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="no_mod_crit_check",
            entity_doing_check_id="player_crit_tester", entity_doing_check_type="player"
        ))
        self.assertEqual(result['outcome'], "crit_success")
        self.assertTrue(result['succeeded'])
        self.assertEqual(result['roll_details']['raw_roll'], 20)

    @patch('bot.game.rules.check_resolver.roll_dice')
    @patch('bot.game.rules.check_resolver.get_entity_effective_stats', new=get_mock_entity_effective_stats)
    def test_critical_failure(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()
        # Rule: no_mod_crit_check, crit_fail_threshold: 1. DC 10.
        mock_roll_dice.return_value = (1, [1]) # Natural 1

        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="no_mod_crit_check",
            entity_doing_check_id="player_crit_tester", entity_doing_check_type="player"
        ))
        self.assertEqual(result['outcome'], "crit_fail")
        self.assertFalse(result['succeeded'])
        self.assertEqual(result['roll_details']['raw_roll'], 1)

    @patch('bot.game.rules.check_resolver.roll_dice')
    @patch('bot.game.rules.check_resolver.get_entity_effective_stats', new=get_mock_entity_effective_stats)
    def test_invalid_check_type(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()
        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="non_existent_check",
            entity_doing_check_id="player_1", entity_doing_check_type="player"
        ))
        self.assertEqual(result['outcome'], "fail")
        self.assertFalse(result['succeeded'])
        self.assertIn("Invalid check_type", result.get('error', ''))

    @patch('bot.game.rules.check_resolver.roll_dice')
    @patch('bot.game.rules.check_resolver.get_entity_effective_stats', new=get_mock_entity_effective_stats)
    def test_missing_stats_for_modifiers(self, mock_roll_dice: MagicMock):
        rules = self._create_sample_rules_config()
        # perception_dc15_beat uses "wisdom", "perception"
        # "player_missing_stats" won't be in MOCK_EFFECTIVE_STATS_DB_FOR_TESTS
        mock_roll_dice.return_value = (10, [10]) # Roll doesn't matter as much here

        result = asyncio.run(resolve_check(
            rules_config_data=rules, check_type="perception_dc15_beat",
            entity_doing_check_id="player_missing_stats", entity_doing_check_type="player"
        ))
        self.assertEqual(result['outcome'], "fail")
        self.assertFalse(result['succeeded'])
        self.assertIn("Stats not found for entity", result.get('error', ''))
        self.assertEqual(result['modifier'], 0) # Should be 0 as no stats were found to apply


if __name__ == '__main__':
    unittest.main()
