import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio # Required for running async test methods if not using a dedicated async test runner

from bot.game.rules import combat_rules # Module to test
from bot.game.models.check_models import CheckResult, CheckOutcome # Changed DetailedCheckResult to CheckResult
# Import other necessary models if their instances are directly used/checked

class TestCombatRules(unittest.TestCase):

    def setUp(self):
        self.sample_rules_config = {
            "guild_id": "test_guild", # Added for functions that might need it from rules_config
            "combat_rules": {
                "attack_roll": {
                    "base_die": "1d20",
                    "crit_success_threshold": 20,
                    "crit_failure_threshold": 1,
                    "crit_success_multiplier": 2.0,
                    "natural_20_is_always_hit": True, # Changed from natural_20_is_hit
                    "natural_1_is_always_miss": True  # Changed from natural_1_is_miss
                },
                "saving_throws": {
                    "base_die": "1d20",
                    "crit_success_threshold": 20,
                    "crit_failure_threshold": 1,
                    "natural_20_is_always_success": True, # Added for consistency
                    "natural_1_is_always_failure": True,  # Added for consistency
                    "stat_modifiers": {"fortitude": "constitution"}
                },
                "status_effects": {"default_duration_rounds": 3},
                # Add other necessary rule snippets for testing specific functions
            },
            "combat_settings": {"round_duration_seconds": 6.0}
        }
        # Mock managers - use AsyncMock for async manager methods
        self.mock_char_mgr = AsyncMock()
        self.mock_npc_mgr = AsyncMock()
        self.mock_status_mgr = AsyncMock()
        self.mock_log_mgr = AsyncMock()

    def test_roll_dice_simple(self):
        # Test basic rolls (exact values are hard due to random, check if it runs and produces int)
        self.assertIsInstance(combat_rules._roll_dice_simple("1d6"), int)
        self.assertIsInstance(combat_rules._roll_dice_simple("2d4+2"), int)
        roll_1d1_plus_5 = combat_rules._roll_dice_simple("1d1+5")
        self.assertEqual(roll_1d1_plus_5, 6) # 1 (from 1d1) + 5
        roll_1d1_minus_1 = combat_rules._roll_dice_simple("1d1-1")
        self.assertEqual(roll_1d1_minus_1, 0) # 1 (from 1d1) - 1
        self.assertEqual(combat_rules._roll_dice_simple("10"), 10) # Flat number

    @patch('random.randint') # Mock random.randint used by perform_check
    def test_perform_check_dc_success(self, mock_randint):
        mock_randint.return_value = 15 # Control the dice roll
        # Pass only the "combat_rules" part of the config, as perform_check expects that structure
        result: CheckResult = combat_rules.perform_check("actor1", self.sample_rules_config, "attack_roll", modifier=5, dc=20)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.details_log.get('outcome_category'), CheckOutcome.SUCCESS.value)
        self.assertEqual(result.total_roll_value, 20)

    @patch('random.randint')
    def test_perform_check_dc_crit_success(self, mock_randint):
        mock_randint.return_value = 20 # Natural 20
        result: CheckResult = combat_rules.perform_check("actor1", self.sample_rules_config, "attack_roll", modifier=0, dc=25)
        self.assertTrue(result.succeeded) # Nat 20 always hits if rule is true
        self.assertEqual(result.details_log.get('outcome_category'), CheckOutcome.CRITICAL_SUCCESS.value)
        self.assertTrue(result.details_log.get('is_critical'))

    @patch('random.randint')
    def test_perform_check_dc_crit_failure(self, mock_randint):
        mock_randint.return_value = 1 # Natural 1
        result: CheckResult = combat_rules.perform_check("actor1", self.sample_rules_config, "attack_roll", modifier=10, dc=5) # Modifier would make it hit
        self.assertFalse(result.succeeded) # Nat 1 always misses if rule is true
        self.assertEqual(result.details_log.get('outcome_category'), CheckOutcome.CRITICAL_FAILURE.value)
        self.assertTrue(result.details_log.get('is_critical'))

    # For async test methods, we need to run them in an event loop
    def _run_async(self, coro):
        return asyncio.run(coro)

    def test_process_direct_damage(self):
        self._run_async(self._async_test_process_direct_damage())

    async def _async_test_process_direct_damage(self):
        mock_target_char = MagicMock(id="char1", name="TestChar", hp=50.0, stats={"max_health": 100.0})
        self.mock_char_mgr.get_character.return_value = mock_target_char

        with patch('bot.game.rules.combat_rules._roll_dice_simple', return_value=10):
            outcome = await combat_rules.process_direct_damage(
                "attacker_id", "NPC", "char1", "Character", "10", "fire",
                self.sample_rules_config, self.mock_char_mgr, self.mock_npc_mgr, self.mock_log_mgr
            )
        self.assertEqual(outcome["damage_dealt"], 10)
        self.assertEqual(outcome["target_hp_after"], 40.0)
        self.mock_char_mgr.update_character_stats.assert_awaited_once_with("test_guild", "char1", {"hp": 40.0})
        self.assertTrue(any("took 10.0 fire direct damage" in msg for msg in outcome["log_messages"]))


    def test_process_healing(self):
        self._run_async(self._async_test_process_healing())

    async def _async_test_process_healing(self):
        mock_target_char = MagicMock(id="char1", name="TestChar", hp=10.0, stats={"max_health": 50.0})
        self.mock_char_mgr.get_character.return_value = mock_target_char

        with patch('bot.game.rules.combat_rules._roll_dice_simple', return_value=20):
            outcome = await combat_rules.process_healing(
                "char1", "Character", "20", self.sample_rules_config,
                self.mock_char_mgr, self.mock_npc_mgr, self.mock_log_mgr
            )
        self.assertEqual(outcome["healing_done"], 20.0)
        self.assertEqual(outcome["target_hp_after"], 30.0)
        self.mock_char_mgr.update_character_stats.assert_awaited_once_with("test_guild", "char1", {"hp": 30.0})

    def test_apply_status_effect_no_save(self):
        self._run_async(self._async_test_apply_status_effect_no_save())

    async def _async_test_apply_status_effect_no_save(self):
        self.mock_status_mgr.add_status_effect.return_value = "new_status_id_123" # This mock is for StatusManager.add_status_effect

        # combat_rules.apply_status_effect returns a boolean
        success_flag = await combat_rules.apply_status_effect(
            "target1", "Character", "poisoned_test", self.sample_rules_config,
            self.mock_status_mgr, self.mock_char_mgr, self.mock_npc_mgr, self.mock_log_mgr,
            current_game_time=100.0
        )
        self.assertTrue(success_flag) # Check the boolean return value
        # The status_actually_applied_or_resisted logic is now internal to apply_status_effect
        # If it returns True, it means StatusManager.add_status_effect was called and succeeded (or save negated)
        self.mock_status_mgr.add_status_effect.assert_awaited_once_with(
            guild_id="test_guild", target_id="target1", target_type="Character",
            status_type="poisoned_test", duration_seconds=18.0,
            applied_by_source_id=None, applied_by_source_type=None,
            current_game_time=100.0
        )
        # Check that log_event was called with a message indicating success
        self.mock_log_mgr.log_event.assert_awaited()
        # Example of checking for a specific log message (adapt as needed for actual log content)
        # logged_details = self.mock_log_mgr.log_event.call_args.kwargs.get('details', {})
        # self.assertIn("Applied via StatusManager", logged_details.get("message", "")) # This depends on actual logging format

    @patch('bot.game.rules.combat_rules.process_saving_throw', new_callable=AsyncMock)
    async def _async_test_apply_status_effect_with_save_negate(self, mock_process_save):
        # Configure save to be successful
        mock_save_result = CheckResult(
            succeeded=True,
            roll_value=15, # Example roll
            modifier_applied=0, # Example mod
            total_roll_value=15, # Example total
            dc_value=15, # Example DC
            description="Save successful",
            details_log={'outcome_category': CheckOutcome.SUCCESS.value, 'check_type': "saving_throw_fortitude", 'actor_id': "target1"}
        )
        mock_process_save.return_value = mock_save_result

        requires_save_info = {"save_type": "fortitude", "dc": 15, "effect_on_save": "negate"}

        success_flag = await combat_rules.apply_status_effect(
            "target1", "Character", "stun_test", self.sample_rules_config,
            self.mock_status_mgr, self.mock_char_mgr, self.mock_npc_mgr, self.mock_log_mgr,
            requires_save_info=requires_save_info, current_game_time=100.0
        )

        self.assertTrue(success_flag) # Function call itself was successful (save was processed, status negated)
        self.mock_status_mgr.add_status_effect.assert_not_called() # Status was negated
        mock_process_save.assert_awaited_once()
        # Check that log_event was called with a message indicating successful save and negation
        self.mock_log_mgr.log_event.assert_awaited()
        # Example: logged_details = self.mock_log_mgr.log_event.call_args.kwargs.get('details', {})
        # self.assertIn("Successfully saved and negated", logged_details.get("message", ""))

    def test_apply_status_effect_with_save_negate(self):
        self._run_async(self._async_test_apply_status_effect_with_save_negate())

    @patch('bot.game.rules.combat_rules.process_saving_throw', new_callable=AsyncMock)
    async def _async_test_apply_status_effect_with_save_half_duration(self, mock_process_save):
        mock_save_result = CheckResult(
            succeeded=True,
            roll_value=16, # Example roll
            modifier_applied=0, # Example mod
            total_roll_value=16, # Example total
            dc_value=15, # Example DC
            description="Save successful for half duration",
            details_log={'outcome_category': CheckOutcome.SUCCESS.value, 'check_type': "saving_throw_fortitude", 'actor_id': "target1"}
        )
        mock_process_save.return_value = mock_save_result

        self.mock_status_mgr.add_status_effect.return_value = "new_status_id_half"
        requires_save_info = {"save_type": "fortitude", "dc": 15, "effect_on_save": "half_duration"}

        success_flag = await combat_rules.apply_status_effect(
            "target1", "Character", "slow_test", self.sample_rules_config,
            self.mock_status_mgr, self.mock_char_mgr, self.mock_npc_mgr, self.mock_log_mgr,
            duration_override_rounds=10, # Explicit duration to be halved
            requires_save_info=requires_save_info, current_game_time=100.0
        )

        self.assertTrue(success_flag) # Function call was successful, status applied (at half duration)
        self.mock_status_mgr.add_status_effect.assert_awaited_once()
        args, kwargs = self.mock_status_mgr.add_status_effect.call_args
        # Expected duration: 10 rounds / 2 = 5 rounds. 5 rounds * 6s/round = 30s
        self.assertEqual(kwargs.get("duration_seconds"), 30.0)
        # Check that log_event was called with a message indicating save for half duration
        self.mock_log_mgr.log_event.assert_awaited()
        # Example: logged_details = self.mock_log_mgr.log_event.call_args.kwargs.get('details', {})
        # self.assertIn("Saved for half duration", logged_details.get("message", ""))

    def test_apply_status_effect_with_save_half_duration(self):
        self._run_async(self._async_test_apply_status_effect_with_save_half_duration())


if __name__ == '__main__':
    unittest.main()
