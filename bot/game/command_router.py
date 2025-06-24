# bot/game/command_router.py

print("--- Начинается загрузка: command_router.py")

import asyncio
import traceback
import shlex # For better argument parsing (handles quotes)
# import uuid # No longer needed here if is_uuid_format is removed
import json

# Import typing components
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING, ClassVar, Union, Tuple
from collections import Counter


# Import discord types for type hints
from discord import Message
import discord

# TOP-LEVEL IMPORTS
# from bot.services.campaign_loader import CampaignLoaderService # MODIFIED - Removed
from bot.game.managers.relationship_manager import RelationshipManager
from bot.game.managers.quest_manager import QuestManager


# Import specific command handlers
from bot.game.action_processor import ActionProcessor
from bot.game.command_handlers import meta_commands
from bot.game.command_handlers import character_commands
from bot.game.command_handlers import inventory_commands
from bot.game.command_handlers import action_commands
from bot.game.command_handlers import interaction_commands
from bot.game.command_handlers import quest_commands
from bot.game.command_handlers import gm_commands
from bot.game.command_handlers import moderation_commands


if TYPE_CHECKING:
    from discord import Message
    from bot.game.models.character import Character
    from bot.game.models.party import Party
    from bot.game.models.relationship import Relationship
    from bot.game.models.quest import Quest
    from bot.game.models.game_state import GameState
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.managers.character_manager import CharacterManager
    from bot.game.managers.event_manager import EventManager
    from bot.game.managers.location_manager import LocationManager
    from bot.game.rules.rule_engine import RuleEngine
    from bot.game.managers.npc_manager import NpcManager
    from bot.game.managers.combat_manager import CombatManager
    from bot.game.managers.item_manager import ItemManager
    from bot.game.managers.time_manager import TimeManager
    from bot.game.managers.status_manager import StatusManager
    from bot.game.managers.crafting_manager import CraftingManager
    from bot.game.managers.economy_manager import EconomyManager
    from bot.game.managers.party_manager import PartyManager
    from bot.services.openai_service import OpenAIService
    from bot.game.managers.persistence_manager import PersistenceManager
    from bot.game.managers.game_manager import GameManager
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.services.campaign_loader import CampaignLoader # MODIFIED - Corrected path
    from bot.game.conflict_resolver import ConflictResolver
    from bot.ai.ai_response_validator import AIResponseValidator
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
    from bot.game.command_handlers.party_handler import PartyCommandHandler


SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

# _command_registry removed as no longer used by CommandRouter internal methods
# @command decorator removed as no longer used by CommandRouter internal methods

class CommandRouter:
    # _command_handlers is now empty as all commands are routed to external handlers
    _command_handlers: ClassVar[Dict[str, Callable[..., Awaitable[Any]]]] = {}

    def __init__(
        self,
        character_manager: "CharacterManager",
        event_manager: "EventManager",
        persistence_manager: "PersistenceManager",
        settings: Dict[str, Any],
        world_simulation_processor: "WorldSimulationProcessor",
        send_callback_factory: SendCallbackFactory,
        character_action_processor: "CharacterActionProcessor",
        character_view_service: "CharacterViewService",
        location_manager: "LocationManager",
        rule_engine: "RuleEngine",
        party_command_handler: "PartyCommandHandler",
        openai_service: Optional["OpenAIService"] = None,
        item_manager: Optional["ItemManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        time_manager: Optional["TimeManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        crafting_manager: Optional["CraftingManager"] = None,
        economy_manager: Optional["EconomyManager"] = None,
        party_action_processor: Optional["PartyActionProcessor"] = None,
        event_action_processor: Optional["EventActionProcessor"] = None,
        event_stage_processor: Optional["EventStageProcessor"] = None,
        quest_manager: Optional["QuestManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
        campaign_loader: Optional["CampaignLoader"] = None, # MODIFIED
        relationship_manager: Optional["RelationshipManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        conflict_resolver: Optional["ConflictResolver"] = None,
        game_manager: Optional["GameManager"] = None,
        ai_validator: Optional["AIResponseValidator"] = None,
    ):
        print("Initializing CommandRouter...")
        self._character_manager = character_manager
        self._event_manager = event_manager
        self._persistence_manager = persistence_manager
        self._settings = settings
        self._world_simulation_processor = world_simulation_processor
        self._send_callback_factory = send_callback_factory
        self._character_action_processor = character_action_processor
        self._character_view_service = character_view_service
        self._location_manager = location_manager
        self._rule_engine = rule_engine
        self._party_command_handler = party_command_handler
        self._campaign_loader = campaign_loader
        self._relationship_manager = relationship_manager
        self._quest_manager = quest_manager
        self._conflict_resolver = conflict_resolver
        self._ai_validator = ai_validator
        self._openai_service = openai_service
        self._item_manager = item_manager
        self._npc_manager = npc_manager
        self._combat_manager = combat_manager
        self._time_manager = time_manager
        self._status_manager = status_manager
        self._party_manager = party_manager
        self._crafting_manager = crafting_manager
        self._economy_manager = economy_manager
        self._party_action_processor = party_action_processor
        self._event_action_processor = event_action_processor
        self._event_stage_processor = event_stage_processor
        self._dialogue_manager = dialogue_manager
        self._game_log_manager = game_log_manager
        self._game_manager = game_manager
        self._command_prefix: str = self._settings.get('command_prefix', '/')
        if not isinstance(self._command_prefix, str) or not self._command_prefix:
            print(f"CommandRouter Warning: Invalid command prefix in settings: '{self._settings.get('command_prefix')}'. Defaulting to '/'.")
            self._command_prefix = '/'
        print("CommandRouter initialized.")

    async def route(self, message: Message) -> None:
        if not message.content or not message.content.startswith(self._command_prefix):
            return
        if message.author.bot:
             return

        try:
            command_line = message.content[len(self._command_prefix):].strip()
            if not command_line:
                 return
            split_command = shlex.split(command_line)
            if not split_command:
                return
            command_keyword = split_command[0].lower()
            command_args = split_command[1:]
        except Exception as e:
            print(f"CommandRouter Error: Failed to parse command '{message.content}': {e}")
            traceback.print_exc()
            try:
                 send_callback = self._send_callback_factory(message.channel.id)
                 await send_callback(f"❌ Ошибка при разборе команды: {e}")
            except Exception as cb_e:
                 print(f"CommandRouter Error sending parsing error message: {cb_e}")
            return

        print(f"CommandRouter: Routing command '{command_keyword}' with args {command_args} from user {message.author.id} in guild {message.guild.id if message.guild else 'DM'}.")

        managers_in_context = {
            'character_manager': self._character_manager,
            'event_manager': self._event_manager,
            'persistence_manager': self._persistence_manager,
            'settings': self._settings,
            'world_simulation_processor': self._world_simulation_processor,
            'send_callback_factory': self._send_callback_factory,
            'character_action_processor': self._character_action_processor,
            'character_view_service': self._character_view_service,
            'location_manager': self._location_manager,
            'rule_engine': self._rule_engine,
            'openai_service': self._openai_service,
            'item_manager': self._item_manager,
            'npc_manager': self._npc_manager,
            'combat_manager': self._combat_manager,
            'time_manager': self._time_manager,
            'status_manager': self._status_manager,
            'party_manager': self._party_manager,
            'crafting_manager': self._crafting_manager,
            'economy_manager': self._economy_manager,
            'party_action_processor': self._party_action_processor,
            'event_action_processor': self._event_action_processor,
            'event_stage_processor': self._event_stage_processor,
            'quest_manager': self._quest_manager,
            'dialogue_manager': self._dialogue_manager,
            'game_log_manager': self._game_log_manager,
            'campaign_loader': self._campaign_loader,
            'relationship_manager': self._relationship_manager,
            'conflict_resolver': self._conflict_resolver,
            'ai_validator': self._ai_validator,
            'game_manager': self._game_manager,
        }

        context: Dict[str, Any] = {
            'message': message,
            'author_id': str(message.author.id),
            'guild_id': str(message.guild.id) if message.guild else None,
            'channel_id': message.channel.id,
            'command_keyword': command_keyword,
            'command_args': command_args,
            'command_prefix': self._command_prefix,
            'send_to_command_channel': self._send_callback_factory(message.channel.id),
            **managers_in_context
        }
        
        # all_internal_cmds is now empty as CommandRouter._command_handlers is empty
        all_internal_cmds = list(self.__class__._command_handlers.keys()) # Should be empty now
        known_external_handler_cmds = [
            "help", "roll", "character", "status", "inventory", "move", "fight",
            "hide", "steal", "use", "npc", "buy", "craft", "quest",
            "gm", "resolve_conflict", "approve", "reject", "edit"
        ]
        # "party" is handled separately and added here.
        all_cmds_list = sorted(list(set(all_internal_cmds + known_external_handler_cmds + ["party"])))
        context["all_command_keywords"] = all_cmds_list

        current_cmd_docs = {} # Start with empty as _command_handlers is empty
        # Populate docstrings from all external handlers
        for mod, cmd_names in [
            (meta_commands, ["help", "roll"]),
            (character_commands, ["character", "status"]),
            (inventory_commands, ["inventory"]),
            (action_commands, ["move", "fight", "hide", "steal", "use"]),
            (interaction_commands, ["npc", "buy", "craft"]),
            (quest_commands, ["quest"]),
            (gm_commands, ["gm", "resolve_conflict"]),
            (moderation_commands, ["approve", "reject", "edit"])
        ]:
            for cmd_name in cmd_names:
                handler_func_name = f"handle_{cmd_name}_command"
                if cmd_name == "npc":
                    handler_func_name = "handle_npc_talk_command"
                elif cmd_name == "resolve_conflict":
                     handler_func_name = "handle_resolve_conflict_command"
                elif cmd_name in ["approve", "reject", "edit"]:
                    handler_func_name = f"handle_{cmd_name}_content_command"

                if hasattr(mod, handler_func_name):
                    doc = getattr(mod, handler_func_name).__doc__
                    if doc:
                        current_cmd_docs[cmd_name] = doc
        context["command_docstrings"] = current_cmd_docs

        # --- Routing Logic ---

        if command_keyword == "help":
            await meta_commands.handle_help_command(message, command_args, context)
            return
        if command_keyword == "roll":
            await meta_commands.handle_roll_command(message, command_args, context)
            return

        if command_keyword == "character":
            await character_commands.handle_character_command(message, command_args, context)
            return
        if command_keyword == "status":
            await character_commands.handle_status_command(message, command_args, context)
            return

        if command_keyword == "inventory":
            await inventory_commands.handle_inventory_command(message, command_args, context)
            return

        if command_keyword == "move":
            await action_commands.handle_move_command(message, command_args, context)
            return
        if command_keyword == "fight":
            await action_commands.handle_fight_command(message, command_args, context)
            return
        if command_keyword == "hide":
            await action_commands.handle_hide_command(message, command_args, context)
            return
        if command_keyword == "steal":
            await action_commands.handle_steal_command(message, command_args, context)
            return
        if command_keyword == "use":
            await action_commands.handle_use_command(message, command_args, context)
            return

        if command_keyword == "npc":
            await interaction_commands.handle_npc_talk_command(message, command_args, context)
            return
        if command_keyword == "buy":
            await interaction_commands.handle_buy_command(message, command_args, context)
            return
        if command_keyword == "craft":
            await interaction_commands.handle_craft_command(message, command_args, context)
            return

        if command_keyword == "quest":
            context["_notify_master_of_pending_content_func"] = self._notify_master_of_pending_content
            await quest_commands.handle_quest_command(message, command_args, context)
            return

        if command_keyword == "gm":
            context["_notify_master_of_pending_content_func"] = self._notify_master_of_pending_content
            await gm_commands.handle_gm_command(message, command_args, context)
            return
        if command_keyword == "resolve_conflict": # This was previously under @command in CommandRouter
            await gm_commands.handle_resolve_conflict_command(message, command_args, context)
            return
        if command_keyword == "approve": # This was previously under @command in CommandRouter
            await moderation_commands.handle_approve_content_command(message, command_args, context)
            return
        if command_keyword == "reject": # This was previously under @command in CommandRouter
            await moderation_commands.handle_reject_content_command(message, command_args, context)
            return
        if command_keyword == "edit": # This was previously under @command in CommandRouter
            await moderation_commands.handle_edit_content_command(message, command_args, context)
            return

        if command_keyword == "party":
             if self._party_command_handler: # PartyCommandHandler is injected, not a standard module
                  try:
                      await self._party_command_handler.handle(message, command_args, context)
                  except Exception as e:
                       print(f"CommandRouter ❌ Error executing 'party' command: {e}")
                       traceback.print_exc()
                       await context['send_to_command_channel'](f"❌ Error in party command: {e}")
                  return
             else:
                  await context['send_to_command_channel']("❌ Party system unavailable.")
                  return

        # If no specific handler matched, and it's not in the (now empty) _command_handlers
        await context['send_to_command_channel'](f"❓ Unknown command: `{self._command_prefix}{command_keyword}`.")

    async def _notify_master_of_pending_content(self, request_id: str, guild_id: str, user_id: str, context: Dict[str, Any]):
        persistence_manager: Optional["PersistenceManager"] = context.get('persistence_manager')
        if not persistence_manager or not hasattr(persistence_manager, '_db_service') or \
           not persistence_manager._db_service or not hasattr(persistence_manager._db_service, 'adapter') or \
           not persistence_manager._db_service.adapter:
             print("CommandRouter: ERROR - PersistenceManager, its DBService, or DB adapter not in context for _notify_master_of_pending_content.")
             return
        db_adapter = persistence_manager._db_service.adapter
        master_channel_id_str_template = self._settings.get('guild_specific_settings', {}).get(guild_id, {}).get('master_notification_channel_id')
        master_channel_id_str = master_channel_id_str_template if master_channel_id_str_template else self._settings.get('default_master_notification_channel_id')

        if not master_channel_id_str:
            print(f"CommandRouter: WARNING - Master notification channel ID not configured for guild {guild_id} or globally.")
            return
        try:
            master_channel_id = int(master_channel_id_str)
        except ValueError:
            print(f"CommandRouter: ERROR - Invalid Master notification channel ID format: {master_channel_id_str}")
            return

        send_to_master_channel = self._send_callback_factory(master_channel_id)
        try:
            moderation_request = await db_adapter.get_pending_moderation_request(request_id)
            if not moderation_request:
                print(f"CommandRouter: ERROR - Could not fetch moderation request {request_id} for notification.")
                await send_to_master_channel(f"Error: Could not retrieve details for moderation request {request_id}.")
                return

            content_type = moderation_request.get("content_type", "Unknown")
            data_json_str = moderation_request.get("data")
            summary = "Could not generate summary."
            if data_json_str:
                try:
                    data_dict = json.loads(data_json_str)
                    try:
                        from bot.utils.text_utils import generate_summary # Ensure this util is available
                        summary = generate_summary(data_dict, content_type)
                    except ImportError:
                        print("CommandRouter: ERROR - Could not import generate_summary. Summary will be basic.")
                        summary = f"Raw Data: {data_json_str[:150]}..."
                    except Exception as e_summary:
                        print(f"CommandRouter: ERROR generating summary for request {request_id}: {e_summary}")
                        summary = f"Error generating summary. Raw Data: {data_json_str[:150]}..."
                except json.JSONDecodeError:
                     summary = f"Invalid JSON data. Raw Data: {data_json_str[:150]}..."
            else:
                 summary = "No data provided."

            notif_message = (
                f"📢 **New Content Awaiting Moderation!**\n"
                f"---------------------------------------\n"
                f"**Request ID:** `{request_id}`\n"
                f"**User:** <@{user_id}> (ID: `{user_id}`)\n"
                f"**Type:** `{content_type.capitalize()}`\n"
                f"**Guild ID:** `{guild_id}`\n"
                f"**Content Summary:**\n```\n{summary}\n```\n"
                f"---------------------------------------\n"
                f"**Actions (example):**\n"
                f"`{self._command_prefix}approve {request_id}`\n"
                f"`{self._command_prefix}reject {request_id}`\n"
                f"`{self._command_prefix}edit {request_id} <json_data>` (use with caution, ensure valid JSON)"
            )
            await send_to_master_channel(notif_message)
            print(f"CommandRouter: Master notification sent for request {request_id} to channel {master_channel_id}.")

        except Exception as e:
            print(f"CommandRouter: ERROR - Failed to send Master notification for request {request_id}: {e}")
            traceback.print_exc()
            try:
                await send_to_master_channel(f"Critical Error: Failed to process and send notification for moderation request {request_id}. Check logs.")
            except Exception:
                pass

# is_uuid_format function removed

print("DEBUG: command_router.py module loaded.")
