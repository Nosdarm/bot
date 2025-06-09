# tests/game/commands/test_moderation_commands.py
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from bot.game.command_handlers.moderation_commands import (
    handle_approve_content_command,
    handle_reject_content_command,
    handle_edit_content_command,
    _activate_approved_content_internal # Keep if testing it indirectly via approve/edit
)

class MockMessage:
    def __init__(self, author_id, content):
        self.author = MagicMock()
        self.author.id = author_id
        self.content = content
        self.channel = MagicMock()
        self.channel.send = AsyncMock()

class TestModerationCommands(unittest.IsolatedAsyncioTestCase):

    async def test_handle_approve_content_command_success_npc(self):
        mock_send_callback = AsyncMock()
        mock_db_adapter = AsyncMock()
        mock_persistence_manager = MagicMock()
        mock_persistence_manager._db_adapter = mock_db_adapter

        mock_npc_manager = AsyncMock()
        mock_character_manager = AsyncMock()
        mock_status_manager = AsyncMock()

        request_id = "req_approve_npc_test"
        author_id_str = "gm_user_1"
        author_id_int = 1
        guild_id = "test_guild_approve_npc"
        original_user_id_str = "123456789012345678" # Example Discord ID string
        original_user_id_int = int(original_user_id_str)

        mock_moderation_request = {
            "id": request_id,
            "guild_id": guild_id,
            "user_id": original_user_id_str,
            "content_type": "npc",
            "data": json.dumps({"name": "Approved NPC", "name_i18n": {"en": "Approved NPC"}}),
            "status": "pending"
        }
        mock_db_adapter.get_pending_moderation_request.return_value = mock_moderation_request
        mock_db_adapter.update_pending_moderation_request.return_value = True
        mock_db_adapter.delete_pending_moderation_request.return_value = True

        mock_player_char = MagicMock()
        mock_player_char.id = "char_for_status_removal_npc"
        mock_character_manager.get_character_by_discord_id.return_value = mock_player_char

        mock_created_npc_obj = MagicMock()
        mock_created_npc_obj.name = "Approved NPC Instance"
        mock_created_npc_obj.name_i18n = {"en": "Approved NPC Instance EN"}

        mock_npc_manager.create_npc_from_moderated_data.return_value = "new_npc_id_123"
        mock_npc_manager.get_npc.return_value = mock_created_npc_obj

        context = {
            "send_to_command_channel": mock_send_callback,
            "settings": {"bot_admins": [author_id_str]},
            "command_prefix": "/",
            "persistence_manager": mock_persistence_manager,
            "author_id": author_id_str,
            "npc_manager": mock_npc_manager,
            "character_manager": mock_character_manager,
            "status_manager": mock_status_manager,
            "bot_language": "en"
        }

        message_obj = MockMessage(author_id_int, f"/approve {request_id}")
        args = [request_id]

        await handle_approve_content_command(message_obj, args, context)

        mock_db_adapter.get_pending_moderation_request.assert_awaited_once_with(request_id)
        mock_db_adapter.update_pending_moderation_request.assert_awaited_once_with(
            request_id, 'approved', author_id_str, mock_moderation_request["data"]
        )
        mock_npc_manager.create_npc_from_moderated_data.assert_awaited_once()
        mock_character_manager.get_character_by_discord_id.assert_awaited_once_with(guild_id, original_user_id_int)
        mock_status_manager.remove_status_effects_by_type.assert_awaited_once_with(
            mock_player_char.id, 'Character', 'awaiting_moderation', guild_id, context
        )
        mock_db_adapter.delete_pending_moderation_request.assert_awaited_once_with(request_id)
        sent_messages = [call[0][0] for call in mock_send_callback.call_args_list]
        self.assertTrue(any(f"Request `{request_id}` approved. Activating content..." in msg for msg in sent_messages))
        self.assertTrue(any(f"Content from request `{request_id}` activated." in msg for msg in sent_messages))
        self.assertTrue(any(f"NPC '{mock_created_npc_obj.name_i18n['en']}' (ID: new_npc_id_123)" in msg for msg in sent_messages))

    async def test_handle_approve_content_command_not_found(self):
        mock_send_callback = AsyncMock()
        mock_db_adapter = AsyncMock()
        mock_persistence_manager = MagicMock()
        mock_persistence_manager._db_adapter = mock_db_adapter
        request_id = "req_not_found"
        author_id_str = "gm_user_2"
        author_id_int = 2
        mock_db_adapter.get_pending_moderation_request.return_value = None
        context = {
            "send_to_command_channel": mock_send_callback,
            "settings": {"bot_admins": [author_id_str]},
            "command_prefix": "/",
            "persistence_manager": mock_persistence_manager,
        }
        message_obj = MockMessage(author_id_int, f"/approve {request_id}")
        args = [request_id]
        await handle_approve_content_command(message_obj, args, context)
        mock_db_adapter.get_pending_moderation_request.assert_awaited_once_with(request_id)
        mock_db_adapter.update_pending_moderation_request.assert_not_awaited()
        mock_send_callback.assert_awaited_once_with(f"Error: Request ID `{request_id}` not found.")

    async def test_handle_approve_content_command_already_processed(self):
        mock_send_callback = AsyncMock()
        mock_db_adapter = AsyncMock()
        mock_persistence_manager = MagicMock()
        mock_persistence_manager._db_adapter = mock_db_adapter
        request_id = "req_already_done"
        author_id_str = "gm_user_3"
        author_id_int = 3
        mock_moderation_request = {"id": request_id, "status": "approved"}
        mock_db_adapter.get_pending_moderation_request.return_value = mock_moderation_request
        context = {
            "send_to_command_channel": mock_send_callback,
            "settings": {"bot_admins": [author_id_str]},
            "command_prefix": "/",
            "persistence_manager": mock_persistence_manager,
        }
        message_obj = MockMessage(author_id_int, f"/approve {request_id}")
        args = [request_id]
        await handle_approve_content_command(message_obj, args, context)
        mock_db_adapter.get_pending_moderation_request.assert_awaited_once_with(request_id)
        mock_db_adapter.update_pending_moderation_request.assert_not_awaited()
        mock_send_callback.assert_awaited_once_with(f"Error: Request `{request_id}` status is 'approved'.")

    # --- Tests for handle_reject_content_command ---
    async def test_handle_reject_content_command_success(self):
        mock_send_callback = AsyncMock()
        mock_db_adapter = AsyncMock()
        mock_persistence_manager = MagicMock()
        mock_persistence_manager._db_adapter = mock_db_adapter

        mock_character_manager = AsyncMock()
        mock_status_manager = AsyncMock()
        mock_notification_service = AsyncMock() # For player DM

        request_id = "req_reject_test"
        author_id_str = "gm_user_reject"
        author_id_int = 4
        guild_id = "test_guild_reject"
        original_user_id_str = "player_to_notify_reject" # Stored as string
        original_user_id_int = int(original_user_id_str) if original_user_id_str.isdigit() else 0 # Should be valid int
        reason = "Content not suitable for the game."

        mock_moderation_request = {
            "id": request_id,
            "guild_id": guild_id,
            "user_id": original_user_id_str,
            "content_type": "quest", # Example
            "data": json.dumps({"title": "A Wild Goose Chase"}),
            "status": "pending"
        }
        mock_db_adapter.get_pending_moderation_request.return_value = mock_moderation_request
        mock_db_adapter.update_pending_moderation_request.return_value = True

        mock_player_char = MagicMock()
        mock_player_char.id = "char_for_status_removal_reject"
        mock_character_manager.get_character_by_discord_id.return_value = mock_player_char

        # Mock the send_player_direct_message method if NotificationService has it
        mock_notification_service.send_player_direct_message = AsyncMock()


        context = {
            "send_to_command_channel": mock_send_callback,
            "settings": {"bot_admins": [author_id_str]},
            "command_prefix": "/",
            "persistence_manager": mock_persistence_manager,
            "character_manager": mock_character_manager,
            "status_manager": mock_status_manager,
            "notification_service": mock_notification_service, # Added to context
            # author_id needed by update_pending_moderation_request
            "author_id": author_id_str
        }

        message_obj = MockMessage(author_id_int, f"/reject {request_id} {reason}")
        args = [request_id, reason]

        await handle_reject_content_command(message_obj, args, context)

        mock_db_adapter.get_pending_moderation_request.assert_awaited_once_with(request_id)
        mock_db_adapter.update_pending_moderation_request.assert_awaited_once_with(
            request_id, 'rejected', author_id_str, mock_moderation_request["data"], moderator_notes=reason
        )
        mock_character_manager.get_character_by_discord_id.assert_awaited_once_with(guild_id, original_user_id_int)
        mock_status_manager.remove_status_effects_by_type.assert_awaited_once_with(
            mock_player_char.id, 'Character', 'awaiting_moderation', guild_id, context
        )
        mock_notification_service.send_player_direct_message.assert_awaited_once()
        args_dm, _ = mock_notification_service.send_player_direct_message.call_args
        self.assertEqual(args_dm[0], original_user_id_str)
        self.assertIn(f"Request ID: `{request_id}`", args_dm[1])
        self.assertIn(f"Reason: {reason}", args_dm[1])

        mock_send_callback.assert_awaited_once_with(f"🗑️ Content request `{request_id}` rejected. Reason: {reason}")

    # --- Tests for handle_edit_content_command ---
    async def test_handle_edit_content_command_success(self):
        mock_send_callback = AsyncMock()
        mock_db_adapter = AsyncMock()
        mock_persistence_manager = MagicMock()
        mock_persistence_manager._db_adapter = mock_db_adapter
        mock_ai_validator = AsyncMock()

        # Mocks for _activate_approved_content_internal part
        mock_npc_manager = AsyncMock()
        mock_character_manager = AsyncMock()
        mock_status_manager = AsyncMock()

        request_id = "req_edit_test"
        author_id_str = "gm_user_edit"
        author_id_int = 5
        guild_id = "test_guild_edit"
        original_user_id_str = "player_for_edited_content"
        original_user_id_int = int(original_user_id_str) if original_user_id_str.isdigit() else 0


        original_data = {"name": "Old Name", "description": "Old description."}
        edited_data_dict = {"name": "New Edited Name", "description": "New description.", "name_i18n": {"en": "New Edited Name"}}
        json_edited_data_str = json.dumps(edited_data_dict)

        mock_moderation_request = {
            "id": request_id,
            "guild_id": guild_id,
            "user_id": original_user_id_str,
            "content_type": "npc", # Example
            "data": json.dumps(original_data),
            "status": "pending"
        }
        mock_db_adapter.get_pending_moderation_request.return_value = mock_moderation_request
        mock_ai_validator.validate_ai_response.return_value = {"overall_status": "success"} # Simple success
        mock_db_adapter.update_pending_moderation_request.return_value = True
        mock_db_adapter.delete_pending_moderation_request.return_value = True


        mock_player_char = MagicMock()
        mock_player_char.id = "char_for_edited_status_removal"
        mock_character_manager.get_character_by_discord_id.return_value = mock_player_char

        mock_edited_npc_obj = MagicMock()
        mock_edited_npc_obj.name = edited_data_dict["name"]
        mock_edited_npc_obj.name_i18n = edited_data_dict["name_i18n"]
        mock_npc_manager.create_npc_from_moderated_data.return_value = "edited_npc_id_456"
        mock_npc_manager.get_npc.return_value = mock_edited_npc_obj


        context = {
            "send_to_command_channel": mock_send_callback,
            "settings": {"bot_admins": [author_id_str]},
            "command_prefix": "/",
            "persistence_manager": mock_persistence_manager,
            "ai_validator": mock_ai_validator,
            "author_id": author_id_str,
            "npc_manager": mock_npc_manager,
            "character_manager": mock_character_manager,
            "status_manager": mock_status_manager,
            "bot_language": "en"
        }

        message_obj = MockMessage(author_id_int, f"/edit {request_id} {json_edited_data_str}")
        args = [request_id, json_edited_data_str]

        await handle_edit_content_command(message_obj, args, context)

        mock_db_adapter.get_pending_moderation_request.assert_awaited_once_with(request_id)
        mock_ai_validator.validate_ai_response.assert_awaited_once_with(
            ai_json_string=json_edited_data_str,
            expected_structure="npc",
            guild_id=guild_id,
            **context
        )
        mock_db_adapter.update_pending_moderation_request.assert_awaited_once_with(
            request_id, 'approved_edited', author_id_str, json_edited_data_str
        )

        # Verify activation flow
        mock_npc_manager.create_npc_from_moderated_data.assert_awaited_once()
        mock_character_manager.get_character_by_discord_id.assert_awaited_once_with(guild_id, original_user_id_int)
        mock_status_manager.remove_status_effects_by_type.assert_awaited_once_with(
            mock_player_char.id, 'Character', 'awaiting_moderation', guild_id, context
        )
        mock_db_adapter.delete_pending_moderation_request.assert_awaited_once_with(request_id)

        sent_messages = [call[0][0] for call in mock_send_callback.call_args_list]
        self.assertTrue(any(f"Request `{request_id}` updated to 'approved_edited'. Activating content..." in msg for msg in sent_messages))
        self.assertTrue(any(f"Content from request `{request_id}` (edited) activated." in msg for msg in sent_messages))
        self.assertTrue(any(f"NPC '{edited_data_dict['name_i18n']['en']}' (ID: edited_npc_id_456)" in msg for msg in sent_messages))


    async def test_handle_edit_content_command_validation_failure(self):
        mock_send_callback = AsyncMock()
        mock_db_adapter = AsyncMock()
        mock_persistence_manager = MagicMock()
        mock_persistence_manager._db_adapter = mock_db_adapter
        mock_ai_validator = AsyncMock()

        request_id = "req_edit_fail_validation"
        author_id_str = "gm_user_edit_fail"
        author_id_int = 6
        guild_id = "test_guild_edit_fail"

        edited_data_dict = {"name": "Invalid NPC", "description": "This data will fail validation."}
        json_edited_data_str = json.dumps(edited_data_dict)
        validation_errors = {"errors": ["Field 'required_field' is missing."]}

        mock_moderation_request = {
            "id": request_id,
            "guild_id": guild_id,
            "user_id": "some_player",
            "content_type": "npc",
            "data": json.dumps({"name": "Old Valid Name"}),
            "status": "pending"
        }
        mock_db_adapter.get_pending_moderation_request.return_value = mock_moderation_request
        mock_ai_validator.validate_ai_response.return_value = {"overall_status": "failure", "errors": validation_errors["errors"]}

        context = {
            "send_to_command_channel": mock_send_callback,
            "settings": {"bot_admins": [author_id_str]},
            "command_prefix": "/",
            "persistence_manager": mock_persistence_manager,
            "ai_validator": mock_ai_validator,
            "author_id": author_id_str
        }

        message_obj = MockMessage(author_id_int, f"/edit {request_id} {json_edited_data_str}")
        args = [request_id, json_edited_data_str]

        await handle_edit_content_command(message_obj, args, context)

        mock_db_adapter.get_pending_moderation_request.assert_awaited_once_with(request_id)
        mock_ai_validator.validate_ai_response.assert_awaited_once()
        mock_db_adapter.update_pending_moderation_request.assert_not_awaited() # Should not update if validation fails

        errors_str_expected = json.dumps(validation_errors["errors"])
        mock_send_callback.assert_awaited_once_with(
            f"Error: Edited data failed validation for type 'npc'. Errors: {errors_str_expected}"
        )

if __name__ == '__main__':
   unittest.main()
