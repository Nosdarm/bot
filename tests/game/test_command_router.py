import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call
import json
import uuid
from typing import Optional, Dict, Any, cast


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
        self.mock_db_adapter = AsyncMock(spec=PostgresAdapter)

        # Setup mock_persistence_manager._db_service.adapter
        self.mock_persistence_manager._db_service = MagicMock()
        self.mock_persistence_manager._db_service.adapter = self.mock_db_adapter
        self.mock_persistence_manager._db_adapter = self.mock_db_adapter

        self.mock_settings = {
            "command_prefix": "/",
            "bot_admins": ["100"], # For GM access control
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
            ai_validator=self.mock_ai_validator
        )
        self.command_router._conflict_resolver = AsyncMock()

    def _get_mock_context(self, message: MockMessage, additional_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        mock_send_to_channel = AsyncMock()
        self.mock_send_callback_factory.return_value = mock_send_to_channel

        context = {
            'message': message,
            'author_id': str(message.author.id),
            'guild_id': str(message.guild.id),
            'channel_id': message.channel.id,
            'command_keyword': message.content.split(' ')[0][1:],
            'command_args': message.content.split(' ')[1:],
            'command_prefix': '/',
            'send_to_command_channel': mock_send_to_channel,
            'persistence_manager': self.mock_persistence_manager,
            'settings': self.mock_settings,
            'character_manager': self.mock_character_manager,
            'status_manager': self.mock_status_manager,
            'npc_manager': self.mock_npc_manager,
            'quest_manager': self.mock_quest_manager,
            'location_manager': self.mock_location_manager,
            'ai_validator': self.mock_ai_validator,
            'send_callback_factory': self.mock_send_callback_factory,
            'event_manager': self.mock_event_manager,
            'world_simulation_processor': self.mock_world_simulation_processor,
            'character_action_processor': self.mock_character_action_processor,
            'character_view_service': self.mock_character_view_service,
            'rule_engine': self.mock_rule_engine,
            'openai_service': None,
            'item_manager': None,
            'combat_manager': None,
            'time_manager': None,
            'party_manager': None,
            'crafting_manager': None,
            'economy_manager': None,
            'party_action_processor': None,
            'event_action_processor': None,
            'event_stage_processor': None,
            'dialogue_manager': None,
            'game_log_manager': None,
            'campaign_loader': None,
            'relationship_manager': None,
            'conflict_resolver': self.command_router._conflict_resolver,
            'game_manager': None,
            'all_command_keywords': ['approve', 'buy', 'character', 'craft', 'edit', 'fight', 'gm', 'help', 'hide', 'inventory', 'move', 'npc', 'party', 'quest', 'reject', 'resolve_conflict', 'roll', 'status', 'steal', 'use'],
            'command_docstrings': {
                'help': 'Отображает список доступных команд или подробную информацию о конкретной команде. Usage: {prefix}help [команда]',
                'roll': 'Rolls dice based on standard dice notation (e.g., /roll 2d6+3, /roll d20). Usage: {prefix}roll <notation>',
                'character': '''
    Управляет персонажем. Usage: {prefix}character <create|delete> [args]
    `{prefix}character create <name>`
    `{prefix}character delete [character_id_or_name (defaults to yours)]`
    ''',
                'status': 'Показывает ваш статус. Usage: {prefix}status [character_id_or_name]',
                'inventory': 'Показывает инвентарь. Usage: {prefix}inventory [character_id_or_name]',
                'npc': 'Initiates a dialogue with an NPC. Usage: {prefix}npc talk <npc_id_or_name> [initial_message]',
                'buy': 'Allows the player to buy an item. Usage: {prefix}buy <item_template_id> [quantity]',
                'craft': 'Allows the player to craft an item. Usage: {prefix}craft <recipe_id> [quantity]',
                'quest': '''
    Manages character quests. Usage: {prefix}quest <action> [args]
    {prefix}quest list
    {prefix}quest start <quest_template_id>
    {prefix}quest complete <active_quest_id>
    {prefix}quest fail <active_quest_id>
    {prefix}quest objectives <active_quest_id> # Optional: To view current objectives
    ''',
                'gm': 'GM-level commands. Usage: {prefix}gm <subcommand> [args]',
                'resolve_conflict': 'Allows a Master to manually resolve a pending conflict. Usage: {prefix}resolve_conflict <conflict_id> <outcome_type> [<params_json>]',
                'approve': 'Approves AI-generated content. Usage: {prefix}approve <request_id>',
                'reject': 'Rejects AI-generated content. Usage: {prefix}reject <request_id> [reason...]',
                'edit': 'Edits and approves AI-generated content. Usage: {prefix}edit <request_id> <json_edited_data>'
            } 
        }
        if additional_context:
            context.update(additional_context)
        return context

    async def test_handle_approve_content_gm_access(self):
        """Test /approve requires GM access."""
        message = MockMessage("/approve req123", "non_gm_user", "channel", "guild")
        context = self._get_mock_context(message)
        await self.command_router.route(cast(Any, message))
        context['send_to_command_channel'].assert_called_once_with("Access Denied.")

    async def test_approve_activates_npc_success(self):
        request_id = "activate_npc_req"
        original_user_id = "300"
        gm_user_id = "100"
        guild_id = "test_guild_activate"
        npc_data = {"name": "Activated NPC", "id": "new_npc_id_123"}

        message = MockMessage(f"/approve {request_id}", gm_user_id, "master_channel", guild_id)
        context = self._get_mock_context(message)
        context['guild_id'] = guild_id

        self.mock_db_adapter.get_pending_moderation_request.return_value = MockDbRow({
            "id": request_id, "user_id": original_user_id, "guild_id": guild_id,
            "content_type": "npc", "data": json.dumps(npc_data), "status": "pending"
        })
        self.mock_npc_manager.create_npc_from_moderated_data.return_value = "new_npc_id_123"
        self.mock_npc_manager.get_npc = AsyncMock(return_value=MockCharacter(id="new_npc_id_123", discord_id=int(original_user_id), name="Activated NPC"))
        mock_player_char = MockCharacter(id="char_for_npc_creator", discord_id=int(original_user_id))
        self.mock_character_manager.get_character_by_discord_id.return_value = mock_player_char
        self.mock_status_manager.remove_status_effects_by_type.return_value = 1
        self.mock_db_adapter.delete_pending_moderation_request.return_value = True
        self.mock_db_adapter.update_pending_moderation_request.return_value = True

        await self.command_router.route(cast(Any, message))

        self.mock_db_adapter.update_pending_moderation_request.assert_called_once_with(request_id, 'approved', gm_user_id, json.dumps(npc_data))
        self.mock_npc_manager.create_npc_from_moderated_data.assert_called_once_with(guild_id, npc_data, context)
        self.mock_status_manager.remove_status_effects_by_type.assert_called_once_with(
            mock_player_char.id, 'Character', 'awaiting_moderation', guild_id, context
        )
        self.mock_db_adapter.delete_pending_moderation_request.assert_called_once_with(request_id)
        context['send_to_command_channel'].assert_any_call(f"🚀 Content from request `{request_id}` activated.")

if __name__ == '__main__':
    unittest.main()