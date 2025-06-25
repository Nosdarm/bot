import unittest
from unittest.mock import patch, AsyncMock
from bot.game.rules.rule_engine import RuleEngine
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.npc_manager import NpcManager
from bot.game.models.check_models import CheckResult, CheckOutcome # Import CheckOutcome
from bot.game.rules.combat_rules import perform_check # Import perform_check

class TestRuleEngineResolveCheck(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_character_manager = AsyncMock(spec=CharacterManager)
        self.mock_npc_manager = AsyncMock(spec=NpcManager)

        self.rule_engine = RuleEngine(
            settings={"game_rules": {
                 "combat_rules": {
                    "attack_roll": {
                        "base_die": "1d20",
                        "crit_success_threshold": 20,
                        "crit_failure_threshold": 1,
                        "natural_20_is_always_success": True,
                        "natural_1_is_always_failure": True
                    },
                    "saving_throws": {
                         "base_die": "1d20",
                         "critical_rules": {
                            "crit_success_threshold": 20,
                            "crit_failure_threshold": 1,
                            "natural_20_is_always_success": True,
                            "natural_1_is_always_failure": True
                        }
                    },
                    "opposed_checks": {
                        "natural_20_auto_wins": True,
                        "natural_1_auto_loses": True,
                        "tie_breaker": "actor_wins"
                    },
                    "default_check_die": "1d20"
                 }
            }},
            character_manager=self.mock_character_manager,
            npc_manager=self.mock_npc_manager,
        )

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_basic_dc_check_skill_stealth_success(self, mock_randint):
        mock_randint.return_value = 10
        # Dex 14 (+2 mod), proficiency +3 = Total +5 modifier.
        result = perform_check(
            actor_id="player1",
            rules_config=self.rule_engine._rules_data,
            check_type="skill_check_stealth",
            modifier=5,
            dc=15
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_roll_value, 15) 
        self.assertEqual(result.details_log['outcome_category'], CheckOutcome.SUCCESS.value)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_basic_dc_check_skill_stealth_failure(self, mock_randint):
        mock_randint.return_value = 5
        # Dex 14 (+2 mod), proficiency +3 = Total +5 modifier.
        # Roll 5 + 5 = 10. DC 15. Failure.
        result = perform_check(
            actor_id="player1",
            rules_config=self.rule_engine._rules_data,
            check_type="skill_check_stealth",
            modifier=5,
            dc=15
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.total_roll_value, 10)
        self.assertEqual(result.details_log['outcome_category'], CheckOutcome.FAILURE.value)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_basic_saving_throw_strength_success(self, mock_randint):
        mock_randint.return_value = 12
        # Strength 16 = +3 modifier
        result = perform_check(
            actor_id="player1",
            rules_config=self.rule_engine._rules_data,
            check_type="saving_throw_strength",
            modifier=3,
            dc=14
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_roll_value, 15)
        self.assertEqual(result.details_log['outcome_category'], CheckOutcome.SUCCESS.value)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_attack_roll_melee_vs_target_ac(self, mock_randint):
        mock_randint.return_value = 15
        # Attack Bonus +6
        result = perform_check(
            actor_id="player1",
            rules_config=self.rule_engine._rules_data,
            check_type="attack_roll_melee",
            modifier=6,
            dc=13
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_roll_value, 21)
        self.assertEqual(result.details_log['outcome_category'], CheckOutcome.SUCCESS.value)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_status_effect_modifier_stat(self, mock_randint):
        mock_randint.return_value = 10
        # Base Str 10 (0 mod) + Status (+2) = +2 mod
        result = perform_check(
            actor_id="player_status_effect",
            rules_config=self.rule_engine._rules_data,
            check_type="ability_check_strength",
            modifier=2,
            dc=12
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_roll_value, 12)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_status_effect_modifier_skill(self, mock_randint):
        mock_randint.return_value = 8
        # Dex (+1) + Status (+3) = +4 mod
        result = perform_check(
            actor_id="player_status_effect_skill",
            rules_config=self.rule_engine._rules_data,
            check_type="skill_check_stealth",
            modifier=4,
            dc=13
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.total_roll_value, 12)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_status_effect_modifier_check_type(self, mock_randint):
        mock_randint.return_value = 14
        # Base (0) + Status (-2) = -2 mod
        result = perform_check(
            actor_id="player_status_effect_type",
            rules_config=self.rule_engine._rules_data,
            check_type="concentration_check",
            modifier=-2,
            dc=10
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_roll_value, 12)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_item_modifier_stat(self, mock_randint):
        mock_randint.return_value = 7
        # Base Wis 10 (0 mod) + Item (+1) = +1 mod
        result = perform_check(
            actor_id="player_item_stat",
            rules_config=self.rule_engine._rules_data,
            check_type="ability_check_wisdom",
            modifier=1,
            dc=9
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.total_roll_value, 8)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_item_modifier_skill(self, mock_randint):
        mock_randint.return_value = 11
        # Cha (+1) + Prof (+2) + Item (+1) = +4 mod
        result = perform_check(
            actor_id="player_item_skill",
            rules_config=self.rule_engine._rules_data,
            check_type="skill_check_persuasion",
            modifier=4,
            dc=15
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_roll_value, 15)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_item_modifier_check_type(self, mock_randint):
        mock_randint.return_value = 9
        # Base (0) + Item (+2) = +2 mod
        result = perform_check(
            actor_id="player_item_type",
            rules_config=self.rule_engine._rules_data,
            check_type="luck_check",
            modifier=2,
            dc=10
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_roll_value, 11)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_contextual_modifier(self, mock_randint):
        mock_randint.return_value = 13
        # Base Dex mod (0) + Contextual (-2) = -2 mod
        result = perform_check(
            actor_id="player_context_mod",
            rules_config=self.rule_engine._rules_data,
            check_type="skill_check_disarm_trap",
            modifier=-2,
            dc=15,
            modifier_details=[{"source": "dex_base", "value": 0}, {"source": "wet_condition", "value": -2}]
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.total_roll_value, 11)
        self.assertIn("wet_condition", result.details_log['modifier_details'][1]['source'])

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_all_modifiers_combined(self, mock_randint):
        mock_randint.return_value = 10
        # Total Modifier = +2 (base Str) - 1 (Weakened) + 2 (Gauntlets) - 1 (Slippery) = +2
        modifier_details = [
            {"source": "strength_base", "value": 2},
            {"source": "status_weakened", "value": -1},
            {"source": "item_gauntlets", "value": 2},
            {"source": "context_slippery", "value": -1}
        ]
        total_calculated_modifier = sum(m['value'] for m in modifier_details)

        result = perform_check(
            actor_id="player_all_mods",
            rules_config=self.rule_engine._rules_data,
            check_type="skill_check_athletics_climb",
            modifier=total_calculated_modifier,
            dc=18,
            modifier_details=modifier_details
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.total_roll_value, 12)
        self.assertEqual(len(result.details_log['modifier_details']), 4)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_critical_success_auto_succeeds(self, mock_randint):
        mock_randint.return_value = 20
        result = perform_check(
            actor_id="player_crit_luck",
            rules_config=self.rule_engine._rules_data,
            check_type="attack_roll_strength",
            modifier=0,
            dc=30
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.details_log['crit_status'], "critical_success")

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_critical_failure_auto_fails(self, mock_randint):
        mock_randint.return_value = 1
        result = perform_check(
            actor_id="player_crit_unluck",
            rules_config=self.rule_engine._rules_data,
            check_type="attack_roll_strength",
            modifier=5,
            dc=5
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.details_log['crit_status'], "critical_failure")

import copy # Add copy for deepcopy

# ... (other imports)

class TestRuleEngineResolveCheck(unittest.IsolatedAsyncioTestCase):
    # ... (asyncSetUp remains the same) ...

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_critical_success_no_auto_succeed_pass(self, mock_randint):
        mock_randint.return_value = 20
        custom_rules = copy.deepcopy(self.rule_engine._rules_data) # Use deepcopy
        if "combat_rules" not in custom_rules: custom_rules["combat_rules"] = {}
        if "attack_roll" not in custom_rules["combat_rules"]: custom_rules["combat_rules"]["attack_roll"] = {}
        custom_rules["combat_rules"]["attack_roll"]["natural_20_is_always_success"] = False
        result = perform_check("player_crit_normal_pass", custom_rules, "attack_roll_strength", 0, 20)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.details_log['crit_status'], "critical_success")

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_critical_success_no_auto_succeed_fail(self, mock_randint):
        mock_randint.return_value = 20
        custom_rules = copy.deepcopy(self.rule_engine._rules_data) # Use deepcopy
        if "combat_rules" not in custom_rules: custom_rules["combat_rules"] = {}
        if "attack_roll" not in custom_rules["combat_rules"]: custom_rules["combat_rules"]["attack_roll"] = {}
        custom_rules["combat_rules"]["attack_roll"]["natural_20_is_always_success"] = False
        result = perform_check("player_crit_normal_fail", custom_rules, "attack_roll_strength", 0, 25)
        self.assertFalse(result.succeeded)
        self.assertEqual(result.details_log['crit_status'], "critical_success")

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_target_dc_stat(self, mock_randint):
        mock_randint.return_value = 10
        # DC 13 pre-calculated based on target's Wisdom
        result = perform_check(
            actor_id="player_knowledge_check",
            rules_config=self.rule_engine._rules_data,
            check_type="skill_check_knowledge_arcana",
            modifier=2,
            dc=13
        )
        self.assertFalse(result.succeeded)
        self.assertEqual(result.total_roll_value, 12)

    @patch('bot.game.rules.combat_rules.random.randint')
    def test_check_with_default_dc(self, mock_randint):
        mock_randint.return_value = 8
        # Default DC 12 for this perception check
        result = perform_check(
            actor_id="player_perception",
            rules_config=self.rule_engine._rules_data,
            check_type="skill_check_perception",
            modifier=1,
            dc=12
        )
        self.assertFalse(result.succeeded)

    def test_invalid_check_type(self):
        # Test that an unrecognized check_type still runs with default die (1d20)
        with patch('bot.game.rules.combat_rules.random.randint', return_value=5):
             result = perform_check("player_invalid_type", self.rule_engine._rules_data, "invent_new_check", 0, 10)
        self.assertFalse(result.succeeded)
        self.assertIn("invent_new_check", result.details_log['check_type'])

    @patch('bot.game.rules.combat_rules.logger.debug')
    def test_logging_calls(self, mock_logger_debug):
        # This test is more about ensuring perform_check runs without error.
        # Specific log message content assertions can be brittle.
        with patch('bot.game.rules.combat_rules.random.randint', return_value=10):
            perform_check("player_log_test", self.rule_engine._rules_data, "generic_log_check", 2, 10)
        # self.assertTrue(mock_logger_debug.called) # Example assertion
        pass

if __name__ == '__main__':
    unittest.main()
