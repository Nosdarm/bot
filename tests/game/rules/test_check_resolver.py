import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Dict, Any, List, Optional

from bot.ai.rules_schema import CoreGameRulesConfig, CheckDefinition
from bot.game.rules.check_resolver import CheckResolver # Changed import
from bot.game.models.check_models import CheckResult # CheckResult is in a different module now
# We will mock bot.game.rules.dice_roller.roll_dice, so direct import not strictly needed here for that.

# --- Mock Effective Stats ---
# This will be used by the patched calculate_effective_stats
MOCK_EFFECTIVE_STATS_DB_FOR_TESTS: Dict[str, Dict[str, Any]] = {
    "player_1": {"strength": 14, "dexterity": 16, "wisdom": 14, "perception": 16, "stealth": 20, "athletics": 12}, # Effective stats (not raw ability scores)
    "npc_1": {"strength": 12, "dexterity": 12, "wisdom": 10, "perception": 12, "stealth": 8},
    "player_high_perception": {"wisdom": 20, "perception": 20},
    "player_crit_tester": {"strength": 10} # Base stat 10 means +0 modifier
}

# This function will be patched in place of the real calculate_effective_stats
async def mock_calculate_effective_stats(entity: Any, guild_id: str, game_manager: Any) -> Dict[str, Any]:
    entity_id_attr = getattr(entity, 'id', None) or getattr(entity, 'discord_id', None) # crude way to get an ID for mock
    return MOCK_EFFECTIVE_STATS_DB_FOR_TESTS.get(str(entity_id_attr), {})


class TestCheckResolver(unittest.TestCase):

    def setUp(self):
        """Setup common mock objects for tests."""
        self.mock_game_manager = MagicMock(name="GameManager")
        self.mock_game_manager.db_service = AsyncMock(name="DBService")
        self.mock_game_manager.npc_manager = AsyncMock(name="NPCManager")

        # Mock player and NPC objects
        self.mock_player1 = MagicMock(name="Player1")
        self.mock_player1.id = "player_1"
        self.mock_player1.name_i18n = {"en": "Player One"}

        self.mock_npc1 = MagicMock(name="NPC1")
        self.mock_npc1.id = "npc_1"
        self.mock_npc1.name_i18n = {"en": "NPC One"}

        self.mock_player_crit_tester = MagicMock(name="CritTester")
        self.mock_player_crit_tester.id = "player_crit_tester"
        self.mock_player_crit_tester.name_i18n = {"en": "Crit Tester"}

        async def get_player_by_id(guild_id, player_id):
            if player_id == "player_1": return self.mock_player1
            if player_id == "player_crit_tester": return self.mock_player_crit_tester
            return None
        self.mock_game_manager.get_player_model_by_id = AsyncMock(side_effect=get_player_by_id)

        async def get_npc(guild_id, npc_id):
            if npc_id == "npc_1": return self.mock_npc1
            return None
        self.mock_game_manager.npc_manager.get_npc = AsyncMock(side_effect=get_npc)

        # Mock get_rule from game_manager
        # This will return specific parts of a rule based on the key
        # For simplicity, we'll assume keys like "checks.perception_dc15_beat.skill" or "checks.perception_dc15_beat.attribute"
        # and for DC, "checks.perception_dc15_beat.dc" (though DC is passed directly in test)
        self.rules_data = {
            "checks.perception_dc15_beat.skill": "perception", # Primary stat/skill for the check
            # "checks.perception_dc15_beat.attribute": "wisdom", # Alternative if skill not found
            "checks.athletics_dc10_meet.attribute": "athletics",
            "checks.stealth_vs_perception.skill": "stealth",
            "checks.stealth_vs_perception.opposed_by_skill": "perception", # Target uses perception
            "checks.no_mod_crit_check.attribute": "strength",
        }
        async def mock_get_rule(guild_id: str, rule_key: str, default: Any = None):
            return self.rules_data.get(rule_key, default)
        self.mock_game_manager.get_rule = AsyncMock(side_effect=mock_get_rule)

        self.resolver = CheckResolver(game_manager=self.mock_game_manager)

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_simple_check_success_beat_dc(self, mock_roll_dice_func: MagicMock): # Renamed from mock_roll_dice
        mock_roll_dice_func.return_value = (12, [12]) # roll_total, [individual_rolls]

        # player_1 stats: perception=16. Mod = (16-10)//2 = 3.
        # DC = 15.
        # Roll 12 + 3 = 15. For "beat_dc" this is a fail if rule implies strict greater.
        # The actual resolve_check logic is `total_roll_value >= difficulty_dc`
        # Let's assume "perception_dc15_beat" implies DC 15.

        # Adjust rule mock for this specific test to simplify if needed, or rely on generic setup.
        # For perception_dc15_beat, primary stat is "perception" (value 16, mod +3)

        guild_id_for_test = "test_guild"
        check_type_for_test = "perception_dc15_beat"

        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id=guild_id_for_test,
            check_type=check_type_for_test,
            performing_entity_id="player_1",
            performing_entity_type="player",
            difficulty_dc=15
        ))

        self.assertTrue(result.succeeded) # 12(roll) + 3(mod) = 15. 15 >= 15 is success.
        self.assertEqual(result.modifier_applied, 3) # (16-10)//2
        self.assertEqual(result.roll_value, 12)
        self.assertEqual(result.total_roll_value, 15)
        self.assertEqual(result.dc_value, 15)
        # self.assertEqual(result.description, "...") # Check description content

        # Assert that get_rule was called to determine the skill/attribute for the check
        # It will be called for "checks.perception_dc15_beat.skill"
        # and potentially for "checks.perception_dc15_beat.attribute" if skill is not found or is not a string.
        self.mock_game_manager.get_rule.assert_any_call(guild_id_for_test, f"checks.{check_type_for_test}.skill", default=None) # Example check

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_simple_check_fail_beat_dc(self, mock_roll_dice_func: MagicMock):
        mock_roll_dice_func.return_value = (9, [9])
        # player_1 perception mod = +3. DC = 15.
        # Roll 9 + 3 = 12. 12 < 15 = Fail.
        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id="test_guild",
            check_type="perception_dc15_beat",
            performing_entity_id="player_1",
            performing_entity_type="player",
            difficulty_dc=15
        ))
        self.assertFalse(result.succeeded)
        self.assertEqual(result.total_roll_value, 12)

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_simple_check_success_meet_dc(self, mock_roll_dice_func: MagicMock):
        mock_roll_dice_func.return_value = (9, [9])
        # player_1 athletics=12. Mod = (12-10)//2 = +1.
        # DC = 10.
        # Roll 9 + 1 = 10. 10 >= 10 = Success.
        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id="test_guild",
            check_type="athletics_dc10_meet", # Assumes "athletics" is the primary stat via get_rule
            performing_entity_id="player_1",
            performing_entity_type="player",
            difficulty_dc=10
        ))
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_roll_value, 10)
        self.assertEqual(result.dc_value, 10)

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_simple_check_fail_meet_dc(self, mock_roll_dice_func: MagicMock):
        mock_roll_dice_func.return_value = (6, [6])
        # player_1 athletics mod = +1. DC = 10.
        # Roll 6 + 1 = 7. 7 < 10 = Fail.
        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id="test_guild",
            check_type="athletics_dc10_meet",
            performing_entity_id="player_1",
            performing_entity_type="player",
            difficulty_dc=10
        ))
        self.assertFalse(result.succeeded)
        self.assertEqual(result.total_roll_value, 7)

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_contested_check_attacker_wins(self, mock_roll_dice_func: MagicMock):
        # Performer: player_1, effective stealth: 20 -> modifier +5
        # Target: npc_1, effective perception: 12 -> modifier +1, passive defense value: 10 + 1 = 11
        mock_roll_dice_func.return_value = (15, [15]) # Performer's roll

        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id="test_guild",
            check_type="stealth_vs_perception",
            performing_entity_id="player_1",
            performing_entity_type="player",
            target_entity_id="npc_1",
            target_entity_type="npc"
        ))

        # Expected: Roll 15 + Mod 5 = 20. Target Defense 11. 20 >= 11 is True.
        self.assertTrue(result.succeeded)
        self.assertEqual(result.modifier_applied, 5)
        self.assertEqual(result.roll_value, 15)
        self.assertEqual(result.total_roll_value, 20)
        self.assertEqual(result.opposed_roll_value, 11)

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_contested_check_defender_wins(self, mock_roll_dice_func: MagicMock):
        # Performer: player_1, effective stealth: 20 -> modifier +5
        # Target: npc_1, effective perception: 12 -> modifier +1, passive defense value: 10 + 1 = 11
        mock_roll_dice_func.return_value = (5, [5]) # Performer's roll

        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id="test_guild",
            check_type="stealth_vs_perception",
            performing_entity_id="player_1",
            performing_entity_type="player",
            target_entity_id="npc_1",
            target_entity_type="npc"
        ))
        # Expected: Roll 5 + Mod 5 = 10. Target Defense 11. 10 >= 11 is False.
        self.assertFalse(result.succeeded)
        self.assertEqual(result.modifier_applied, 5)
        self.assertEqual(result.roll_value, 5)
        self.assertEqual(result.total_roll_value, 10)
        self.assertEqual(result.opposed_roll_value, 11)

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_natural_20_roll_succeeds(self, mock_roll_dice_func: MagicMock):
        # player_crit_tester strength=10 (mod +0). DC 10 for "no_mod_crit_check" (uses strength)
        mock_roll_dice_func.return_value = (20, [20]) # Natural 20

        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id="test_guild",
            check_type="no_mod_crit_check", # This check type uses strength (mocked player has 10 strength -> +0 mod)
            performing_entity_id="player_crit_tester",
            performing_entity_type="player",
            difficulty_dc=10 # DC is 10
        ))
        # Roll 20 + Mod 0 = 20. 20 >= 10 is True.
        self.assertTrue(result.succeeded)
        self.assertEqual(result.roll_value, 20)
        self.assertEqual(result.total_roll_value, 20)
        self.assertEqual(result.modifier_applied, 0)


    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_natural_1_roll_fails_if_not_meeting_dc(self, mock_roll_dice_func: MagicMock):
        # player_crit_tester strength=10 (mod +0). DC 10.
        mock_roll_dice_func.return_value = (1, [1]) # Natural 1

        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id="test_guild",
            check_type="no_mod_crit_check",
            performing_entity_id="player_crit_tester",
            performing_entity_type="player",
            difficulty_dc=10 # DC is 10
        ))
        # Roll 1 + Mod 0 = 1. 1 >= 10 is False.
        self.assertFalse(result.succeeded)
        self.assertEqual(result.roll_value, 1)
        self.assertEqual(result.total_roll_value, 1)
        self.assertEqual(result.modifier_applied, 0)

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_invalid_check_type_fallback_to_strength(self, mock_roll_dice_func: MagicMock):
        # If a check_type has no rule mapping in self.rules_data, it defaults to "strength".
        # player_1 effective strength=14 (mod +2). DC 10.
        mock_roll_dice_func.return_value = (10, [10])

        with self.assertLogs('bot.game.rules.check_resolver', level='WARNING') as cm:
            result: CheckResult = asyncio.run(self.resolver.resolve_check(
                guild_id="test_guild",
                check_type="non_existent_check_type_for_rules", # This key is not in self.rules_data
                performing_entity_id="player_1",
                performing_entity_type="player",
                difficulty_dc=10
            ))
        # Expected: Roll 10 + Mod 2 (from strength) = 12. 12 >= 10 is True.
        self.assertTrue(result.succeeded)
        self.assertEqual(result.modifier_applied, 2) # (14-10)//2
        self.assertEqual(result.total_roll_value, 12)
        self.assertIn("No RuleConfig for check_type 'non_existent_check_type_for_rules'", cm.output[0])
        self.assertIn("Defaulted to 'strength'", cm.output[0])


    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_entity_not_found_raises_value_error(self, mock_roll_dice_func: MagicMock):
        mock_roll_dice_func.return_value = (10, [10]) # Roll value doesn't matter here

        # Mock get_player_model_by_id to return None for the specific ID
        original_get_player = self.mock_game_manager.get_player_model_by_id
        async def side_effect_get_player(guild_id, player_id):
            if player_id == "player_ghost": return None
            return await original_get_player(guild_id, player_id)
        self.mock_game_manager.get_player_model_by_id.side_effect = side_effect_get_player

        with self.assertRaises(ValueError) as excinfo:
            asyncio.run(self.resolver.resolve_check(
                guild_id="test_guild",
                check_type="perception_dc15_beat",
                performing_entity_id="player_ghost",
                performing_entity_type="player",
                difficulty_dc=15
            ))
        self.assertIn("Performing entity player player_ghost not found", str(excinfo.exception))
        self.mock_game_manager.get_player_model_by_id.side_effect = original_get_player # Restore

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_check_with_additional_modifiers_and_context_notes(self, mock_roll_dice_func: MagicMock):
        mock_roll_dice_func.return_value = (10, [10])
        # player_1 perception mod = +3. DC = 15.
        # Additional mods: +2 (bless), -1 (curse) = +1 total additional
        # Roll 10 + 3 (base) + 1 (additional) = 14. 14 < 15 = Fail.

        additional_mods = {"item_bonus": 2, "spell_malus": -1} # Net +1
        notes = "Under pressure"

        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id="test_guild",
            check_type="perception_dc15_beat",
            performing_entity_id="player_1",
            performing_entity_type="player",
            difficulty_dc=15,
            additional_modifiers=additional_mods,
            context_notes=notes
        ))
        self.assertFalse(result.succeeded)
        self.assertEqual(result.modifier_applied, 3 + 2 - 1) # base_mod + item_bonus + spell_malus
        self.assertEqual(result.total_roll_value, 10 + 3 + 1) # roll + base_mod + net_additional_mod
        self.assertIn(notes, result.description)
        self.assertIn(f"item_bonus: 2", str(result.details_log["modifier_sources"]))
        self.assertIn(f"spell_malus: -1", str(result.details_log["modifier_sources"]))

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    def test_invalid_base_roll_str_raises_error(self, mock_roll_dice_func: MagicMock):
        mock_roll_dice_func.side_effect = ValueError("Test invalid dice string")

        with self.assertRaises(ValueError) as excinfo:
            asyncio.run(self.resolver.resolve_check(
                guild_id="test_guild",
                check_type="perception_dc15_beat",
                performing_entity_id="player_1",
                performing_entity_type="player",
                difficulty_dc=15,
                base_roll_str="invalid_dice"
            ))
        self.assertIn("Invalid base_roll_str 'invalid_dice' for check", str(excinfo.exception))


    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_contested_check_target_not_found(self, mock_roll_dice_func: MagicMock):
        mock_roll_dice_func.return_value = (15, [15]) # Performer's roll doesn't matter as target is not found

        # Mock get_npc to return None for the target ID
        original_get_npc = self.mock_game_manager.npc_manager.get_npc
        async def side_effect_get_npc(guild_id, npc_id):
            if npc_id == "npc_ghost_target": return None
            return await original_get_npc(guild_id, npc_id)
        self.mock_game_manager.npc_manager.get_npc.side_effect = side_effect_get_npc

        result: CheckResult = asyncio.run(self.resolver.resolve_check(
            guild_id="test_guild",
            check_type="stealth_vs_perception",
            performing_entity_id="player_1",
            performing_entity_type="player",
            target_entity_id="npc_ghost_target", # This target won't be found
            target_entity_type="npc"
        ))
        self.assertFalse(result.succeeded) # Should fail if target not found
        self.assertIn("Target npc_ghost_target (Not Found)", result.description)
        self.assertEqual(result.details_log["opposition_type"], "error_target_not_found")
        self.mock_game_manager.npc_manager.get_npc.side_effect = original_get_npc # Restore

    @patch('bot.game.rules.check_resolver.dice_roller.roll_dice')
    @patch('bot.game.rules.check_resolver.calculate_effective_stats', new=mock_calculate_effective_stats)
    def test_contested_check_undefined_opposition_rule(self, mock_roll_dice_func: MagicMock):
        mock_roll_dice_func.return_value = (15, [15])
        # Temporarily remove opposition rules for 'stealth_vs_perception'
        original_opposed_skill_rule = self.rules_data.pop("checks.stealth_vs_perception.opposed_by_skill", None)

        with self.assertLogs('bot.game.rules.check_resolver', level='WARNING') as cm:
            result: CheckResult = asyncio.run(self.resolver.resolve_check(
                guild_id="test_guild",
                check_type="stealth_vs_perception",
                performing_entity_id="player_1",
                performing_entity_type="player",
                target_entity_id="npc_1",
                target_entity_type="npc"
            ))

        self.assertFalse(result.succeeded) # Should fail if opposition is undefined
        self.assertIn("vs Target NPC One (Undefined Opposition)", result.description)
        self.assertEqual(result.details_log["opposition_type"], "undefined")
        self.assertIn("No RuleConfig for opposition for check_type 'stealth_vs_perception'", cm.output[0])

        # Restore rule if it was removed
        if original_opposed_skill_rule:
            self.rules_data["checks.stealth_vs_perception.opposed_by_skill"] = original_opposed_skill_rule


if __name__ == '__main__':
    unittest.main()
