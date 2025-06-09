# tests/services/test_notification_service.py
import unittest
from unittest.mock import MagicMock, AsyncMock

from bot.services.notification_service import NotificationService

class TestNotificationService(unittest.IsolatedAsyncioTestCase): # Changed to IsolatedAsyncioTestCase

    def setUp(self):
        self.mock_send_callback_factory = MagicMock()
        self.mock_settings = {
            "gm_notification_channel_id": "123456789012345678", # Global fallback
            "guild_specific_settings": {
                "guild_specific": {
                    "gm_notification_channel_id": "987654321098765432"
                }
            }
        }
        self.notification_service = NotificationService(
            send_callback_factory=self.mock_send_callback_factory,
            settings=self.mock_settings
        )

    async def test_send_moderation_request_alert_uses_guild_specific_channel(self):
        mock_send_func = AsyncMock()
        self.mock_send_callback_factory.return_value = mock_send_func

        guild_id = "guild_specific"
        request_id = "req_abc"
        content_type = "NPC"
        user_id = "user_xyz"
        content_summary = {"name": "Test NPC", "description": "A cool dude."}
        moderation_link = "Do this: /approve"

        await self.notification_service.send_moderation_request_alert(
            guild_id, request_id, content_type, user_id, content_summary, moderation_link
        )

        self.mock_send_callback_factory.assert_called_once_with(987654321098765432) # Guild specific ID
        mock_send_func.assert_awaited_once()
        args, _ = mock_send_func.call_args
        message_content = args[0] # Assuming content is the first positional arg

        self.assertIn(f"**Type:** `{content_type.capitalize()}`", message_content)
        self.assertIn(f"**Request ID:** `{request_id}`", message_content)
        self.assertIn(f"**Guild ID:** `{guild_id}`", message_content)
        self.assertIn(f"**Initiated by User:** `{user_id}`", message_content)
        self.assertIn("**Name:** Test NPC", message_content) # Note: was "Name" before, "name" is key in dict
        self.assertIn("**Description:** A cool dude.", message_content) # Note: was "Description"
        self.assertIn(f"**Action:** {moderation_link}", message_content)

    async def test_send_moderation_request_alert_uses_global_channel_if_guild_specific_missing(self):
        mock_send_func = AsyncMock()
        self.mock_send_callback_factory.return_value = mock_send_func

        guild_id = "guild_other" # Not in guild_specific_settings
        request_id = "req_def"
        content_type = "Quest"
        user_id = "user_123"
        content_summary = {"title": "Big Adventure"} # Using "title" as an example key
        moderation_link = "/mod quest"


        await self.notification_service.send_moderation_request_alert(
            guild_id, request_id, content_type, user_id, content_summary, moderation_link
        )

        self.mock_send_callback_factory.assert_called_once_with(123456789012345678) # Global ID
        mock_send_func.assert_awaited_once()
        args, _ = mock_send_func.call_args
        message_content = args[0]
        self.assertIn(f"**Type:** `{content_type.capitalize()}`", message_content)
        self.assertIn(f"**Title:** Big Adventure", message_content) # Check formatted summary

    async def test_send_moderation_request_alert_no_channel_configured(self):
        # Test when no channel ID is configured at all
        self.notification_service.settings = {} # Clear settings
        mock_send_func = AsyncMock()
        self.mock_send_callback_factory.return_value = mock_send_func

        # To check logs, you'd typically use self.assertLogs
        # For example:
        # with self.assertLogs(logger='bot.services.notification_service', level='WARNING') as cm:
        #     await self.notification_service.send_moderation_request_alert(
        #         "any_guild", "any_req", "any_type", "any_user", {}, "any_link"
        #     )
        # self.assertTrue(any("No GM notification channel configured" in output for output in cm.output))

        # Call without log capture for simplicity here
        await self.notification_service.send_moderation_request_alert(
            "any_guild", "any_req", "any_type", "any_user", {}, "any_link"
        )

        self.mock_send_callback_factory.assert_not_called()
        mock_send_func.assert_not_called()

if __name__ == '__main__':
   unittest.main()
