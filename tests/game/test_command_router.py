import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call
import json
import uuid
from typing import Optional, Dict, Any


from bot.game.command_router import CommandRouter
from bot.game.managers.npc_manager import NpcManager
from bot.game.managers.quest_manager import QuestManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.status_manager import StatusManager
from bot.game.managers.persistence_manager import PersistenceManager
from bot.services.openai_service import OpenAIService # For type hinting if needed in context
from bot.ai.ai_response_validator import AIResponseValidator # For type hinting
from bot.database.postgres_adapter import PostgresAdapter # For type hinting

# Mock discord.Message
class MockMessage:
    def __init__(self, content, author_id, channel_id, guild_id="test_guild"):
        self.content = content
        self.author = MagicMock()
        self.author.id = author_id
        self.author.bot = False
        self.author.mention = f"<@{author_id}>"
        self.channel = MagicMock()
        self.channel.id = channel_id
        self.guild = MagicMock()
        self.guild.id = guild_id

class MockCharacter:
    def __init__(self, id, discord_id, name="TestChar", location_id="loc1"):
        self.id = id
        self.discord_id = str(discord_id) # Ensure string for comparison consistency
        self.name = name
        self.location_id = location_id

# Helper to simulate aiosqlite.Row for get_pending_moderation_request
class MockDbRow(dict):
    def __init__(self, data):
        super().__init__(data)


class TestCommandRouterModeration(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_character_manager = AsyncMock(spec=CharacterManager)
        self.mock_event_manager = AsyncMock()
        self.mock_persistence_manager = AsyncMock(spec=PersistenceManager)
        self.mock_db_adapter = AsyncMock(spec=PostgresAdapter) # Mock for DB adapter
        self.mock_persistence_manager.get_db_adapter.return_value = self.mock_db_adapter

        self.mock_settings = {
            "command_prefix": "/",
            "bot_admins": ["gm_user_id"], # For GM access control
            "guild_specific_settings": {
                "test_guild": {"master_notification_channel_id": "master_channel_id"}
            },
            "default_master_notification_channel_id": "default_master_channel_id"
        }
        self.mock_world_simulation_processor = AsyncMock()
        self.mock_send_callback_factory = MagicMock()
        self.mock_character_action_processor = AsyncMock()
        self.mock_character_view_service = AsyncMock()
        self.mock_location_manager = AsyncMock(spec=LocationManager)
        self.mock_rule_engine = AsyncMock()
        self.mock_party_command_handler = AsyncMock()

        self.mock_npc_manager = AsyncMock(spec=NpcManager)
        self.mock_quest_manager = AsyncMock(spec=QuestManager)
        # LocationManager already mocked as self.mock_location_manager
        self.mock_status_manager = AsyncMock(spec=StatusManager)
        self.mock_ai_validator = AsyncMock(spec=AIResponseValidator) # For /edit command

        # Instantiate CommandRouter with mocked dependencies
        self.command_router = CommandRouter(
            character_manager=self.mock_character_manager,
            event_manager=self.mock_event_manager,
            persistence_manager=self.mock_persistence_manager,
            settings=self.mock_settings,
            world_simulation_processor=self.mock_world_simulation_processor,
            send_callback_factory=self.mock_send_callback_factory,
            character_action_processor=self.mock_character_action_processor,
            character_view_service=self.mock_character_view_service,
            location_manager=self.mock_location_manager,
            rule_engine=self.mock_rule_engine,
            party_command_handler=self.mock_party_command_handler,
            npc_manager=self.mock_npc_manager,
            quest_manager=self.mock_quest_manager,
            status_manager=self.mock_status_manager,
            # Pass AI Validator here as it's used by /edit directly in CommandRouter
            # and also available in context for other methods if needed.
            # It's passed via **kwargs to __init__ if not a named param.
            # Let's assume it's available in the context if GameManager provides it.
            # For testing _activate_approved_content, we'll ensure it's in the context dict directly.
        )
        # Add ai_validator to the context that CommandRouter builds internally for handlers
        # This simulates GameManager providing it.
        self.command_router._conflict_resolver = AsyncMock() # Ensure this is mocked if used by a command
        # If CommandRouter.__init__ doesn't take ai_validator, but it's expected in context:
        # We'll add it to the 'context' dict in each test method before calling router.route()

    def _get_mock_context(self, message: MockMessage, additional_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # Basic context setup, similar to what CommandRouter.route would build
        # Ensure all managers used by the commands are here
        mock_send_to_channel = AsyncMock()
        self.mock_send_callback_factory.return_value = mock_send_to_channel

        context = {
            'message': message,
            'author_id': str(message.author.id),
            'guild_id': str(message.guild.id),
            'channel_id': message.channel.id,
            'command_prefix': '/',
            'send_to_command_channel': mock_send_to_channel,
            'persistence_manager': self.mock_persistence_manager, # For DB adapter access
            'settings': self.mock_settings,
            'character_manager': self.mock_character_manager,
            'status_manager': self.mock_status_manager,
            'npc_manager': self.mock_npc_manager,
            'quest_manager': self.mock_quest_manager,
            'location_manager': self.mock_location_manager,
            'ai_validator': self.mock_ai_validator, # Crucial for /edit
            'send_callback_factory': self.mock_send_callback_factory # For _notify_master
        }
        if additional_context:
            context.update(additional_context)
        return context

    # --- Part 1: Player-Initiated Generation Flow ---
    async def test_gm_ai_create_npc_pending_moderation(self):
        """Test /gm ai_create_npc successfully leads to pending moderation."""
        author_id = "gm_user_id"
        guild_id = "test_guild"
        channel_id = "test_channel"
        request_id = str(uuid.uuid4())

        message = MockMessage(f"/gm create_npc AI:cool_robot", author_id, channel_id, guild_id)
        context = self._get_mock_context(message)

        self.mock_npc_manager.create_npc.return_value = {"status": "pending_moderation", "request_id": request_id}

        mock_gm_char = MockCharacter(id="gm_char_id", discord_id=author_id)
        self.mock_character_manager.get_character_by_discord_id.return_value = mock_gm_char
        self.mock_status_manager.add_status_effect_to_entity = AsyncMock(return_value="status_effect_id")

        # For _notify_master_of_pending_content
        self.mock_db_adapter.get_pending_moderation_request.return_value = MockDbRow({
            "id": request_id, "guild_id": guild_id, "user_id": author_id,
            "content_type": "npc", "data": json.dumps({"name": "AI Robot"}), "status": "pending"
        })

        await self.command_router.route(message)

        self.mock_npc_manager.create_npc.assert_called_once()
        self.mock_status_manager.add_status_effect_to_entity.assert_called_once_with(
            target_id=mock_gm_char.id, target_type='Character',
            status_type='awaiting_moderation', guild_id=guild_id, duration=None,
            source_id="gm_command_npc_creation"
        )
        context['send_to_command_channel'].assert_any_call(f"NPC data for 'AI:cool_robot' generated and submitted for moderation. Request ID: `{request_id}`. You (GM) will be notified in the Master channel.")
        self.mock_db_adapter.get_pending_moderation_request.assert_called_once_with(request_id)
        # Check that master notification was attempted (mock_send_callback_factory for master channel was called)
        self.mock_send_callback_factory.assert_any_call("master_channel_id")


    async def test_player_quest_start_ai_pending_moderation(self):
        author_id = "player_user_id"
        guild_id = "test_guild"
        channel_id = "player_channel"
        request_id = str(uuid.uuid4())
        quest_template_id_arg = "AI:my_epic_adventure"

        message = MockMessage(f"/quest start {quest_template_id_arg}", author_id, channel_id, guild_id)
        context = self._get_mock_context(message)

        mock_player_char = MockCharacter(id="player_char_id_123", discord_id=author_id)
        self.mock_character_manager.get_character_by_discord_id.return_value = mock_player_char

        self.mock_quest_manager.start_quest.return_value = {"status": "pending_moderation", "request_id": request_id}
        self.mock_status_manager.add_status_effect_to_entity = AsyncMock(return_value="status_effect_id")
        self.mock_db_adapter.get_pending_moderation_request.return_value = MockDbRow({
            "id": request_id, "guild_id": guild_id, "user_id": author_id,
            "content_type": "quest", "data": json.dumps({"name_i18n": {"en": "My Epic Adventure"}}), "status": "pending"
        })

        await self.command_router.route(message)

        self.mock_quest_manager.start_quest.assert_called_once()
        # Check that user_id was passed in kwargs of the call to start_quest
        _, call_kwargs = self.mock_quest_manager.start_quest.call_args
        self.assertEqual(call_kwargs.get('user_id'), author_id)

        self.mock_status_manager.add_status_effect_to_entity.assert_called_once_with(
            target_id=mock_player_char.id, target_type='Character',
            status_type='awaiting_moderation', guild_id=guild_id, duration=None,
            source_id=f"quest_generation_user_{author_id}"
        )
        context['send_to_command_channel'].assert_any_call(f"📜 Your request for quest '{quest_template_id_arg}' has been submitted for moderation (ID: `{request_id}`). You'll be notified when it's reviewed, and your character will be temporarily unable to perform most actions.")
        self.mock_db_adapter.get_pending_moderation_request.assert_called_once_with(request_id)
        self.mock_send_callback_factory.assert_any_call("master_channel_id")


    # --- Part 2: Master Moderation Commands ---
    async def test_handle_approve_content_gm_access(self):
        """Test /approve requires GM access."""
        message = MockMessage("/approve req123", "non_gm_user", "channel", "guild")
        context = self._get_mock_context(message)
        await self.command_router.route(message)
        context['send_to_command_channel'].assert_called_once_with("Access Denied: This command is for Masters only.")

    async def test_handle_approve_content_success(self):
        author_id = "gm_user_id"
        request_id = "req_approve_1"
        original_user_id = "player_who_requested"
        guild_id_from_request = "test_guild"

        message = MockMessage(f"/approve {request_id}", author_id, "master_channel", guild_id_from_request) # GM uses in correct guild
        context = self._get_mock_context(message)

        self.mock_db_adapter.get_pending_moderation_request.return_value = MockDbRow({
            "id": request_id, "status": "pending", "user_id": original_user_id,
            "guild_id": guild_id_from_request, "content_type": "npc", "data": "{}"
        })
        self.mock_db_adapter.update_pending_moderation_request.return_value = True # DB update successful

        # Mock _activate_approved_content to test its call
        self.command_router._activate_approved_content = AsyncMock(return_value=True)

        await self.command_router.route(message)

        self.mock_db_adapter.update_pending_moderation_request.assert_called_once_with(request_id, 'approved', author_id)
        self.command_router._activate_approved_content.assert_called_once_with(request_id, context)
        context['send_to_command_channel'].assert_any_call(f"🚀 Content from request `{request_id}` successfully activated and request removed.")

    async def test_handle_reject_content_success(self):
        author_id = "gm_user_id"
        request_id = "req_reject_1"
        original_user_id = "player_to_notify"
        guild_id_from_request = "test_guild"
        reason = "Not suitable for the game."

        message = MockMessage(f"/reject {request_id} {reason}", author_id, "master_channel", guild_id_from_request)
        context = self._get_mock_context(message)

        self.mock_db_adapter.get_pending_moderation_request.return_value = MockDbRow({
            "id": request_id, "status": "pending", "user_id": original_user_id,
            "guild_id": guild_id_from_request, "content_type": "npc", "data": "{}"
        })
        self.mock_db_adapter.delete_pending_moderation_request.return_value = True

        mock_player_char = MockCharacter(id="char_id_for_reject", discord_id=int(original_user_id))
        self.mock_character_manager.get_character_by_discord_id.return_value = mock_player_char
        self.mock_status_manager.remove_status_effects_by_type = AsyncMock(return_value=1)

        await self.command_router.route(message)

        self.mock_db_adapter.delete_pending_moderation_request.assert_called_once_with(request_id)
        self.mock_status_manager.remove_status_effects_by_type.assert_called_once_with(
            mock_player_char.id, 'Character', 'awaiting_moderation', guild_id_from_request, context
        )
        context['send_to_command_channel'].assert_any_call(f"🗑️ Content request `{request_id}` rejected and deleted.")
        # Placeholder for user notification is internal to CommandRouter, check via print log or further mocking if needed.

    async def test_handle_edit_content_success(self):
        author_id = "gm_user_id"
        request_id = "req_edit_1"
        original_user_id = "player_edit_notify"
        guild_id_from_request = "test_guild"
        original_content_type = "npc"
        edited_data_json = json.dumps({"name": "Edited NPC Name"})

        message = MockMessage(f"/edit {request_id} {edited_data_json}", author_id, "master_channel", guild_id_from_request)
        context = self._get_mock_context(message)

        self.mock_db_adapter.get_pending_moderation_request.return_value = MockDbRow({
            "id": request_id, "status": "pending", "user_id": original_user_id,
            "guild_id": guild_id_from_request, "content_type": original_content_type, "data": "{}"
        })
        self.mock_ai_validator.validate_ai_response = AsyncMock(return_value={"overall_status": "success", "entities": [{"validated_data": json.loads(edited_data_json)}]})
        self.mock_db_adapter.update_pending_moderation_request.return_value = True
        self.command_router._activate_approved_content = AsyncMock(return_value=True)

        await self.command_router.route(message)

        self.mock_ai_validator.validate_ai_response.assert_called_once()
        self.mock_db_adapter.update_pending_moderation_request.assert_called_once_with(
            request_id, 'approved_edited', author_id_str=author_id, data_json=edited_data_json
        )
        self.command_router._activate_approved_content.assert_called_once_with(request_id, context)
        context['send_to_command_channel'].assert_any_call(f"🚀 Content from request `{request_id}` (edited) successfully activated and request removed.")

    # --- Part 3: Test _activate_approved_content ---
    async def test_activate_approved_content_npc_success(self):
        request_id = "activate_npc_req"
        original_user_id = "discord_user_npc" # This is Discord ID
        guild_id = "test_guild_activate"
        npc_data = {"name": "Activated NPC", "id": "new_npc_id_123"} # id might be in approved_data

        context = self._get_mock_context(MagicMock()) # Dummy message
        context['guild_id'] = guild_id # Ensure guild_id is in context for manager calls

        self.mock_db_adapter.get_pending_moderation_request.return_value = MockDbRow({
            "id": request_id, "user_id": original_user_id, "guild_id": guild_id,
            "content_type": "npc", "data": json.dumps(npc_data), "status": "approved"
        })
        self.mock_npc_manager.create_npc_from_moderated_data = AsyncMock(return_value="new_npc_id_123")

        mock_player_char = MockCharacter(id="char_for_npc_creator", discord_id=int(original_user_id))
        self.mock_character_manager.get_character_by_discord_id.return_value = mock_player_char
        self.mock_status_manager.remove_status_effects_by_type = AsyncMock(return_value=1)
        self.mock_db_adapter.delete_pending_moderation_request = AsyncMock(return_value=True)

        success = await self.command_router._activate_approved_content(request_id, context)
        self.assertTrue(success)
        self.mock_npc_manager.create_npc_from_moderated_data.assert_called_once_with(guild_id, npc_data, context)
        self.mock_status_manager.remove_status_effects_by_type.assert_called_once_with(
            mock_player_char.id, 'Character', 'awaiting_moderation', guild_id, context
        )
        self.mock_db_adapter.delete_pending_moderation_request.assert_called_once_with(request_id)

    async def test_activate_approved_content_location_move_player(self):
        request_id = "activate_loc_req"
        original_user_id = "discord_user_loc" # Discord ID
        guild_id = "test_guild_loc_activate"
        new_location_id = "newly_activated_loc_id"
        location_data = {"name_i18n": {"en":"New Zone"}, "id": new_location_id}

        context = self._get_mock_context(MagicMock())
        context['guild_id'] = guild_id

        self.mock_db_adapter.get_pending_moderation_request.return_value = MockDbRow({
            "id": request_id, "user_id": original_user_id, "guild_id": guild_id,
            "content_type": "location", "data": json.dumps(location_data), "status": "approved"
        })
        # create_location_instance_from_moderated_data returns the instance data dict
        self.mock_location_manager.create_location_instance_from_moderated_data = AsyncMock(return_value=location_data)

        mock_player_char = MockCharacter(id="char_for_loc_creator", discord_id=int(original_user_id), location_id="old_loc")
        self.mock_character_manager.get_character_by_discord_id.return_value = mock_player_char
        self.mock_status_manager.remove_status_effects_by_type = AsyncMock(return_value=1)
        self.mock_location_manager.move_entity = AsyncMock(return_value=True)
        self.mock_db_adapter.delete_pending_moderation_request = AsyncMock(return_value=True)

        success = await self.command_router._activate_approved_content(request_id, context)
        self.assertTrue(success)
        self.mock_location_manager.create_location_instance_from_moderated_data.assert_called_once_with(
            guild_id, location_data, original_user_id, context
        )
        self.mock_location_manager.move_entity.assert_called_once_with(
            guild_id, entity_id=mock_player_char.id, entity_type='Character',
            from_location_id="old_loc", to_location_id=new_location_id, **context
        )
        self.mock_status_manager.remove_status_effects_by_type.assert_called_once()
        self.mock_db_adapter.delete_pending_moderation_request.assert_called_once()

    async def test_activate_approved_content_quest_char_not_found(self):
        """Test quest activation fails if the original user's character is not found."""
        request_id = "activate_quest_no_char_req"
        original_user_id = "discord_user_no_char"
        guild_id = "test_guild_quest_no_char"
        quest_data = {"name": "A Quest"}

        context = self._get_mock_context(MagicMock())
        context['guild_id'] = guild_id

        self.mock_db_adapter.get_pending_moderation_request.return_value = MockDbRow({
            "id": request_id, "user_id": original_user_id, "guild_id": guild_id,
            "content_type": "quest", "data": json.dumps(quest_data), "status": "approved"
        })
        self.mock_character_manager.get_character_by_discord_id.return_value = None # Character not found

        success = await self.command_router._activate_approved_content(request_id, context)
        self.assertFalse(success)
        self.mock_quest_manager.start_quest_from_moderated_data.assert_not_called()
        self.mock_db_adapter.delete_pending_moderation_request.assert_not_called()
        context['send_to_command_channel'].assert_any_call(f"Error: Original user {original_user_id} does not have an active character in guild {guild_id} to assign the quest to. Quest {request_id} cannot be activated.")


if __name__ == '__main__':
    unittest.main()
