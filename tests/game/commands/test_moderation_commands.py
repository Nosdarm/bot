# tests/game/commands/test_moderation_commands.py
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from bot.game.command_handlers.moderation_commands import handle_approve_content_command, _activate_approved_content_internal
# Assuming discord.Message is a simple mockable object or you have a way to create a test double
# from discord import Message # This would be the actual discord.py Message

class MockMessage:
    def __init__(self, author_id, content):
        self.author = MagicMock()
        self.author.id = author_id
        self.content = content
        # Add other attributes if the command handler uses them, e.g., channel for send_callback
        self.channel = MagicMock()
        self.channel.send = AsyncMock() # If send_callback is message.channel.send

class TestModerationCommands(unittest.IsolatedAsyncioTestCase):

    async def test_handle_approve_content_command_success_npc(self):
        mock_send_callback = AsyncMock() # This will be context['send_to_command_channel']

        mock_db_adapter = AsyncMock()
        mock_persistence_manager = MagicMock()
        mock_persistence_manager._db_adapter = mock_db_adapter

        mock_npc_manager = AsyncMock()
        mock_character_manager = AsyncMock() # For _activate_approved_content_internal
        mock_status_manager = AsyncMock()    # For _activate_approved_content_internal


        request_id = "req_approve_npc_test"
        author_id_str = "gm_user_1" # String, as used in gm_ids check
        author_id_int = 1 # If message.author.id is int
        guild_id = "test_guild_approve_npc"
        original_user_id_str = "original_player_npc" # String, as stored in DB
        original_user_id_int = int(original_user_id_str) if original_user_id_str.isdigit() else 0


        mock_moderation_request = {
            "id": request_id,
            "guild_id": guild_id,
            "user_id": original_user_id_str, # Stored as string
            "content_type": "npc",
            "data": json.dumps({"name": "Approved NPC", "name_i18n": {"en": "Approved NPC"}}),
            "status": "pending"
        }
        mock_db_adapter.get_pending_moderation_request.return_value = mock_moderation_request
        mock_db_adapter.update_pending_moderation_request.return_value = True
        mock_db_adapter.delete_pending_moderation_request.return_value = True # For _activate_approved_content_internal

        # Mocks for _activate_approved_content_internal
        mock_player_char = MagicMock()
        mock_player_char.id = "char_for_status_removal_npc"
        mock_character_manager.get_character_by_discord_id.return_value = mock_player_char

        mock_created_npc_obj = MagicMock()
        mock_created_npc_obj.name = "Approved NPC Instance" # Fallback if name_i18n is missing
        mock_created_npc_obj.name_i18n = {"en": "Approved NPC Instance EN", "ru": "Одобренный НПС"}

        mock_npc_manager.create_npc_from_moderated_data.return_value = "new_npc_id_123" # Returns ID
        mock_npc_manager.get_npc.return_value = mock_created_npc_obj # get_npc returns the object


        context = {
            "send_to_command_channel": mock_send_callback,
            "settings": {"bot_admins": [author_id_str]}, # GM IDs are strings
            "command_prefix": "/",
            "persistence_manager": mock_persistence_manager,
            "author_id": author_id_str, # For _activate_approved_content_internal moderator_id
            "npc_manager": mock_npc_manager,
            "character_manager": mock_character_manager,
            "status_manager": mock_status_manager,
            "bot_language": "en"
        }

        message_obj = MockMessage(author_id_int, f"/approve {request_id}") # author.id is typically int
        args = [request_id]

        await handle_approve_content_command(message_obj, args, context)

        # Verify DB interactions
        mock_db_adapter.get_pending_moderation_request.assert_awaited_once_with(request_id)
        mock_db_adapter.update_pending_moderation_request.assert_awaited_once_with(
            request_id,
            'approved',
            author_id_str, # moderator_id is string
            mock_moderation_request["data"]
        )

        # Verify calls within _activate_approved_content_internal
        mock_npc_manager.create_npc_from_moderated_data.assert_awaited_once()
        # Ensure original_user_id is correctly converted to int for get_character_by_discord_id
        mock_character_manager.get_character_by_discord_id.assert_awaited_once_with(guild_id, original_user_id_int)
        mock_status_manager.remove_status_effects_by_type.assert_awaited_once_with(
            mock_player_char.id, 'Character', 'awaiting_moderation', guild_id, context
        )
        mock_db_adapter.delete_pending_moderation_request.assert_awaited_once_with(request_id)

        # Verify feedback messages
        sent_messages = [call[0][0] for call in mock_send_callback.call_args_list]
        self.assertTrue(any(f"Request `{request_id}` approved. Activating content..." in msg for msg in sent_messages))
        self.assertTrue(any(f"Content from request `{request_id}` activated." in msg for msg in sent_messages))
        # Check that the entity info in the activation message is correct
        self.assertTrue(any(f"NPC '{mock_created_npc_obj.name_i18n['en']}' (ID: new_npc_id_123)" in msg for msg in sent_messages))


    async def test_handle_approve_content_command_not_found(self):
        mock_send_callback = AsyncMock()
        mock_db_adapter = AsyncMock()
        mock_persistence_manager = MagicMock()
        mock_persistence_manager._db_adapter = mock_db_adapter

        request_id = "req_not_found"
        author_id_str = "gm_user_2"
        author_id_int = 2

        mock_db_adapter.get_pending_moderation_request.return_value = None # Request not found

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

        mock_moderation_request = {
            "id": request_id,
            "status": "approved" # Already approved
        }
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


if __name__ == '__main__':
   unittest.main()
