import logging
from typing import Tuple, List, Any, Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Player
from bot.database.crud_utils import get_entity_by_id
from bot.game.rules.dice_roller import roll_dice

if TYPE_CHECKING:
    from bot.game.managers.game_manager import GameManager

logger = logging.getLogger(__name__)

class CheckResolver:
    def __init__(self, game_manager: "GameManager"):
        self.game_manager = game_manager
        if not self.game_manager:
            logger.critical("CheckResolver initialized without a valid GameManager instance!")

    async def resolve_simple_check(
        self,
        db_session: AsyncSession,
        guild_id: str,
        player_id: str,
        skill_name: str,
        difficulty_class: int
    ) -> Tuple[bool, int, int]:
        """
        Resolves a simple skill check for a player against a difficulty class (DC).
        A skill check is typically 1d20 + skill_modifier vs DC.

        Args:
            db_session: The active SQLAlchemy async session.
            guild_id: The ID of the guild where the check is happening.
            player_id: The ID of the player performing the check.
            skill_name: The name of the skill or attribute to use for the modifier
                        (e.g., "perception", "strength", "lockpicking_skill").
            difficulty_class: The DC the player needs to meet or exceed.

        Returns:
            A tuple (success: bool, total_result: int, dice_roll_value: int).
            - success: True if total_result >= difficulty_class, False otherwise.
            - total_result: The sum of the d20 roll and the skill modifier.
            - dice_roll_value: The raw value rolled on the d20.

        Raises:
            ValueError: If the player is not found or guild ID mismatch.
        """
        logger.debug(f"Resolving simple check for player {player_id} in guild {guild_id}: skill '{skill_name}', DC {difficulty_class}.")

        player = await get_entity_by_id(db_session, Player, player_id)
        if not player:
            logger.error(f"Player {player_id} not found while resolving check for guild {guild_id}.")
            raise ValueError(f"Player {player_id} not found.")

        if player.guild_id != guild_id:
            logger.error(f"Player {player_id} (guild {player.guild_id}) does not belong to the specified guild {guild_id} for check.")
            raise ValueError(f"Player {player_id} guild mismatch for check.")

        logger.debug(f"Player {player.id} loaded. Stats: {player.stats}, Skills JSON: {player.skills_data_json}")

        skill_modifier = 0
        # Check skills_data_json first, then fallback to stats
        # This assumes skills_data_json stores final, ready-to-use modifiers for specific skills.
        # And player.stats stores base attributes which might also be used as "skills".
        source_of_modifier = "None"

        if player.skills_data_json and isinstance(player.skills_data_json, dict):
            skill_value_from_json = player.skills_data_json.get(skill_name)
            if isinstance(skill_value_from_json, (int, float)):
                skill_modifier = int(skill_value_from_json)
                source_of_modifier = "skills_data_json"
                logger.debug(f"Retrieved skill modifier {skill_modifier} for '{skill_name}' from player.skills_data_json.")

        if source_of_modifier == "None" and player.stats and isinstance(player.stats, dict):
            # If not found in skills_data_json or skills_data_json is None, check stats
            stat_value = player.stats.get(skill_name)
            if isinstance(stat_value, (int, float)):
                skill_modifier = int(stat_value)
                source_of_modifier = "stats"
                logger.debug(f"Retrieved skill modifier {skill_modifier} for '{skill_name}' from player.stats.")

        if source_of_modifier == "None":
             logger.debug(f"No modifier found for '{skill_name}' in skills_data_json or stats for player {player_id}. Modifier remains 0.")


        try:
            _, d20_rolls = roll_dice("1d20")
            dice_roll_value = d20_rolls[0]
            logger.debug(f"Rolled 1d20: {dice_roll_value}")
        except ValueError as e:
            logger.error(f"Error rolling '1d20' for check: {e}", exc_info=True)
            raise # Re-raise if dice rolling itself fails critically

        total_result = dice_roll_value + skill_modifier
        logger.debug(f"Total check result: {dice_roll_value} (roll) + {skill_modifier} (modifier from {source_of_modifier}) = {total_result}")

        success = total_result >= difficulty_class

        crit_success_on_nat_20 = await self.game_manager.get_rule(guild_id, "crit_success_on_natural_20", default=True)
        crit_failure_on_nat_1 = await self.game_manager.get_rule(guild_id, "crit_failure_on_natural_1", default=True)
        # Example: A rule that says Nat 20 only auto-succeeds if DC is not excessively high
        nat_20_auto_succeeds_max_dc = await self.game_manager.get_rule(guild_id, "natural_20_auto_succeeds_max_dc", default=None)

        if dice_roll_value == 20 and crit_success_on_nat_20:
            if nat_20_auto_succeeds_max_dc is None or difficulty_class <= nat_20_auto_succeeds_max_dc:
                if not success: # If it wasn't already a success (e.g. very high DC but still beatable with high mod)
                    logger.info(f"Natural 20! Overriding check result to SUCCESS for player {player_id} on '{skill_name}' check against DC {difficulty_class}.")
                success = True
            else:
                logger.info(f"Natural 20 rolled by player {player_id}, but DC {difficulty_class} exceeds auto-success threshold {nat_20_auto_succeeds_max_dc}. Standard success rules apply.")

        if dice_roll_value == 1 and crit_failure_on_nat_1:
            if success: # If it somehow would have succeeded (e.g. very low DC and high mod)
                 logger.info(f"Natural 1! Overriding check result to FAILURE for player {player_id} on '{skill_name}' check against DC {difficulty_class}.")
            success = False

        if success:
            logger.info(f"Check SUCCESS for player {player_id}, skill '{skill_name}', DC {difficulty_class}: Roll={dice_roll_value}, Mod={skill_modifier}, Total={total_result}.")
        else:
            logger.info(f"Check FAILED for player {player_id}, skill '{skill_name}', DC {difficulty_class}: Roll={dice_roll_value}, Mod={skill_modifier}, Total={total_result}.")

        return success, total_result, dice_roll_value

# Example usage (for testing, not part of the class itself)
async def example_check_resolver_usage(game_manager_mock, session_mock, player_id_mock):
    if not game_manager_mock:
        print("Mock GameManager not provided for example.")
        return

    resolver = CheckResolver(game_manager=game_manager_mock)
    try:
        print("\n--- Example Check Resolver Usage ---")

        test_cases = [
            {"skill": "perception", "dc": 15, "expected_source": "stats"},
            {"skill": "lockpicking", "dc": 18, "expected_source": "skills_data_json"},
            {"skill": "strength", "dc": 10, "expected_source": "stats"},
            {"skill": "diplomacy", "dc": 12, "expected_source": "None"}, # Assuming diplomacy isn't in stats or skills_data_json
        ]

        for tc in test_cases:
            print(f"\nTest Case: Player {player_id_mock}, Skill: {tc['skill']}, DC: {tc['dc']}")
            success, total, roll = await resolver.resolve_simple_check(session_mock, "test_guild", player_id_mock, tc['skill'], tc['dc'])
            print(f"  Result: Success={success}, Total={total} (Roll={roll})")
            # For more detailed testing, one could assert the modifier source based on tc['expected_source']
            # by inspecting logs or enhancing return value for tests.

    except ValueError as ve:
        print(f"ValueError in example: {ve}")
    except Exception as e:
        print(f"An unexpected error occurred in example: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    import asyncio # Added import for asyncio.run
    logging.basicConfig(level=logging.DEBUG) # Ensure logging is configured for the test output

    # Mock Player and GameManager for standalone testing
    class MockPlayer(Player): # Define a more complete mock Player
        def __init__(self, id, guild_id, stats, skills_data_json): # Match expected attributes
            self.id = id
            self.guild_id = guild_id
            self.stats = stats
            self.skills_data_json = skills_data_json # This was the attribute name used in resolve_simple_check
            self.selected_language = "en" # Default language for any i18n needs

    class MockGameManager:
        def __init__(self):
            self._rules = {
                ("test_guild", "crit_success_on_natural_20"): True,
                ("test_guild", "crit_failure_on_natural_1"): True,
                ("test_guild", "natural_20_auto_succeeds_max_dc"): 25, # e.g. Nat 20 won't beat a DC 30
            }
        async def get_rule(self, guild_id, key, default=None):
            return self._rules.get((guild_id, key), default)

    # Mock database session and get_entity_by_id
    mock_player_instance = MockPlayer(
        id="test_player_1",
        guild_id="test_guild",
        stats={"perception": 3, "strength": 2}, # Base attributes
        skills_data_json={"lockpicking": 5, "stealth": 1} # Specific skill modifiers
    )

    async def mock_get_entity_by_id_for_test(session, model, entity_id, **kwargs):
        if model == Player and entity_id == "test_player_1":
            return mock_player_instance
        return None

    # Temporarily patch the actual get_entity_by_id for this test run
    original_get_entity_by_id = get_entity_by_id
    # Need to assign to the module where CheckResolver imports it from
    import bot.database.crud_utils as crud_utils_module
    crud_utils_module.get_entity_by_id = mock_get_entity_by_id_for_test

    class MockAsyncSession: # Minimal mock for 'async with'
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): pass

    async def main_test_run():
        gm_mock = MockGameManager()
        session_mock = MockAsyncSession()
        await example_check_resolver_usage(gm_mock, session_mock, "test_player_1")

    try:
        asyncio.run(main_test_run())
    finally:
        # Restore original function
        crud_utils_module.get_entity_by_id = original_get_entity_by_id
