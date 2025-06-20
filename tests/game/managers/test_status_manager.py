import unittest
from unittest.mock import AsyncMock, patch, MagicMock, call
import uuid
import time # For StatusEffect.applied_at

from bot.game.managers.status_manager import StatusManager
from bot.game.models.status_effect import StatusEffect

class TestStatusManager(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_db_adapter = AsyncMock()
        self.mock_settings = {"status_templates": {
            "awaiting_moderation": {"name_i18n": {"en": "Awaiting Moderation"}},
            "poisoned": {"name_i18n": {"en": "Poisoned"}}
        }} # Basic settings with templates

        # Mock other managers that might be in context, though not directly used by remove_status_effects_by_type
        self.mock_rule_engine = AsyncMock()
        self.mock_time_manager = AsyncMock()
        # ... any other managers StatusManager.__init__ might expect

        self.status_manager = StatusManager(
            db_adapter=self.mock_db_adapter,
            settings=self.mock_settings,
            rule_engine=self.mock_rule_engine,
            time_manager=self.mock_time_manager
            # Pass other mocks if StatusManager requires them
        )
        # Clear any effects that might be loaded by _load_status_templates if it did more
        self.status_manager._status_effects = {}

    async def test_remove_status_effects_by_type_removes_correctly(self):
        guild_id = "test_guild_status_remove"
        target_id = "char_with_statuses"
        target_type = "Character"
        status_type_to_remove = "awaiting_moderation"

        # Populate cache with test effects
        effect1_mod_id = str(uuid.uuid4())
        effect1_mod = StatusEffect(effect1_mod_id, status_type_to_remove, target_id, target_type, guild_id, None, time.time(), {})

        effect2_mod_id = str(uuid.uuid4())
        effect2_mod = StatusEffect(effect2_mod_id, status_type_to_remove, target_id, target_type, guild_id, 300.0, time.time(), {})

        effect3_poison_id = str(uuid.uuid4())
        effect3_poison = StatusEffect(effect3_poison_id, "poisoned", target_id, target_type, guild_id, 60.0, time.time(), {})

        effect4_other_target_id = str(uuid.uuid4())
        effect4_other_target = StatusEffect(effect4_other_target_id, status_type_to_remove, "other_char", target_type, guild_id, None, time.time(), {})

        self.status_manager._status_effects[guild_id] = {
            effect1_mod_id: effect1_mod,
            effect2_mod_id: effect2_mod,
            effect3_poison_id: effect3_poison,
            effect4_other_target_id: effect4_other_target
        }

        # Mock the internal self.remove_status_effect to track calls
        self.status_manager.remove_status_effect = AsyncMock(side_effect=lambda sid, gid, **kw: sid) # Return sid on success

        context_arg = {"some_key": "some_value"}
        removed_count = await self.status_manager.remove_status_effects_by_type(
            target_id, target_type, status_type_to_remove, guild_id, context_arg
        )

        self.assertEqual(removed_count, 2)

        # Check calls to remove_status_effect
        expected_calls = [
            call(effect1_mod_id, guild_id, **context_arg),
            call(effect2_mod_id, guild_id, **context_arg)
        ]
        self.status_manager.remove_status_effect.assert_has_calls(expected_calls, any_order=True)
        self.assertEqual(self.status_manager.remove_status_effect.call_count, 2)

        # Verify that the other statuses were not attempted to be removed (by checking they are still in cache or mock not called for them)
        # Note: remove_status_effect (mocked) already removes from cache in the real implementation.
        # Here, because we mocked it, we'd check that the mock was NOT called for effect3_poison_id and effect4_other_target_id.
        # The assert_has_calls with any_order=True for only the expected calls already implies this.

    async def test_remove_status_effects_by_type_no_match(self):
        guild_id = "test_guild_status_no_match"
        target_id = "char_no_statuses_of_type"
        target_type = "Character"

        effect1_poison_id = str(uuid.uuid4())
        effect1_poison = StatusEffect(effect1_poison_id, "poisoned", target_id, target_type, guild_id, 60.0, time.time(), {})
        self.status_manager._status_effects[guild_id] = {effect1_poison_id: effect1_poison}

        self.status_manager.remove_status_effect = AsyncMock()

        removed_count = await self.status_manager.remove_status_effects_by_type(
            target_id, target_type, "awaiting_moderation", guild_id, {}
        )
        self.assertEqual(removed_count, 0)
        self.status_manager.remove_status_effect.assert_not_called()

    async def test_remove_status_effects_by_type_no_statuses_for_guild(self):
        guild_id = "test_guild_no_statuses_at_all"
        target_id = "any_char"
        target_type = "Character"

        self.status_manager.remove_status_effect = AsyncMock()
        removed_count = await self.status_manager.remove_status_effects_by_type(
            target_id, target_type, "awaiting_moderation", guild_id, {}
        )
        self.assertEqual(removed_count, 0)
        self.status_manager.remove_status_effect.assert_not_called()

if __name__ == '__main__':
    unittest.main()
