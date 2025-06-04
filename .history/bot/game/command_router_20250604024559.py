# bot/game/command_router.py

print("--- Начинается загрузка: command_router.py")

import asyncio
import traceback
import shlex # For better argument parsing (handles quotes)
import uuid # Needed for is_uuid_format example
import json # <-- ADDED: Import the json module globally

# Import typing components
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING, ClassVar, Union, Tuple # Добавляем Union для Type Hint
from collections import Counter # Added for example in Party info


# Import discord types for type hints
from discord import Message # Used in route method signature, handle_* signatures
# Import discord for Embed etc.
import discord # Direct import

# TOP-LEVEL IMPORTS
from bot.services.campaign_loader import CampaignLoader
from bot.game.managers.relationship_manager import RelationshipManager
from bot.game.managers.quest_manager import QuestManager


# Import specific command handlers
# Убедитесь, что путь к PartyCommandHandler правильный
# Импорт на уровне TYPE_CHECKING
# from bot.game.command_handlers.party_handler import PartyCommandHandler # Перемещаем в TYPE_CHECKING

# Import ActionProcessor for use in process_party_actions placeholder
from bot.game.action_processor import ActionProcessor # <-- ADDED: Import ActionProcessor


if TYPE_CHECKING:
    # --- Imports for Type Checking ---
    # Discord types used in method signatures or context
    from discord import Message # Already imported above, but good to list here for completeness if needed
    # from discord import Guild # Example if guild object is passed in context
    # from discord import Client # If client is passed in context or needs type hint

    # Models (needed for type hints or isinstance checks if they cause cycles elsewhere)
    from bot.game.models.character import Character
    from bot.game.models.party import Party # Needed for "Party" type hint
    from bot.game.models.relationship import Relationship
    from bot.game.models.quest import Quest
    # Assume GameState model is available for mocking
    from bot.game.models.game_state import GameState


    # Managers (use string literals)
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

    from bot.game.managers.quest_manager import QuestManager # Added for QuestManager
    from bot.game.managers.dialogue_manager import DialogueManager # Added for DialogueManager
    from bot.game.managers.game_log_manager import GameLogManager

    from bot.services.campaign_loader import CampaignLoader
    from bot.game.managers.relationship_manager import RelationshipManager
    from bot.game.managers.quest_manager import QuestManager
    from bot.game.conflict_resolver import ConflictResolver # For type hinting
    from bot.ai.ai_response_validator import AIResponseValidator # For handle_edit_content
    from bot.game.event_processors.event_stage_processor import EventStageProcessor


    # Добавляем другие менеджеры, которые могут быть в context kwargs


    # Processors (use string literals)
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
    # from bot.game.party_processors.party_view_service import PartyViewService

    # Import the PartyCommandHandler for type hinting
    from bot.game.command_handlers.party_handler import PartyCommandHandler # <--- ТИПИЗАЦИЯ ОБРАБОТЧИКА ПАРТИИ


# Define Type Aliases for callbacks explicitly if used in type hints
SendToChannelCallback = Callable[..., Awaitable[Any]] # Represents a function like ctx.send or channel.send
SendCallbackFactory = Callable[[int], SendToChannelCallback] # Represents the factory that takes channel ID and returns a send callback


# --- Command Decorator ---
# NOTE: Commands handled by separate handlers (like 'party') should *not* be registered here.
# Only commands handled directly within CommandRouter should use this decorator.
_command_registry: Dict[str, Callable[..., Awaitable[Any]]] = {} # Global command registry

def command(keyword: str) -> Callable:
    """Decorator to register a method as a command handler within CommandRouter."""
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        # Store the function in the registry using the keyword
        # Commands are case-insensitive, store lowercase keyword
        lower_keyword = keyword.lower()
        if lower_keyword in _command_registry:
             print(f"WARNING: Command '{keyword}' is already registered. Overwriting with {func.__name__}")
        _command_registry[lower_keyword] = func
        print(f"DEBUG: Command '{keyword}' registered to {func.__name__}")
        return func
    return decorator

# --- CommandRouter Class ---
class CommandRouter:
    # _command_handlers will only contain handlers *within* CommandRouter now
    _command_handlers: ClassVar[Dict[str, Callable[..., Awaitable[Any]]]] = _command_registry


    def __init__(
        self,
        # --- Required Dependencies ---
        character_manager: "CharacterManager",
        event_manager: "EventManager", # This might eventually be replaced or supplemented by QuestManager
        persistence_manager: "PersistenceManager",
        settings: Dict[str, Any],
        world_simulation_processor: "WorldSimulationProcessor",
        send_callback_factory: SendCallbackFactory,
        character_action_processor: "CharacterActionProcessor",
        character_view_service: "CharacterViewService",
        location_manager: "LocationManager",
        rule_engine: "RuleEngine",
        party_command_handler: "PartyCommandHandler",


        # --- Optional Dependencies ---
        openai_service: Optional["OpenAIService"] = None,
        item_manager: Optional["ItemManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        time_manager: Optional["TimeManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None,
        crafting_manager: Optional["CraftingManager"] = None,
        economy_manager: Optional["EconomyManager"] = None,

        party_action_processor: Optional["PartyActionProcessor"] = None, # Still needed for context
        event_action_processor: Optional["EventActionProcessor"] = None,
        event_stage_processor: Optional["EventStage_processor"] = None, # Typo corrected? Or expected? Assuming expected.
        quest_manager: Optional["QuestManager"] = None, # Added QuestManager
        dialogue_manager: Optional["DialogueManager"] = None, # Added DialogueManager
        # Add other optional managers/processors needed for context
        # Add View Services needed for context (even if handled by specific handlers)
        # party_view_service: Optional["PartyViewService"] = None, # Needed for PartyCommandHandler if it gets it from context
        # location_view_service: Optional["LocationViewService"] = None, # Needed for handle_look potentially
        campaign_loader: Optional["CampaignLoader"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
        conflict_resolver: Optional["ConflictResolver"] = None, # Added ConflictResolver

    ):
        print("Initializing CommandRouter...")
        # Store all injected dependencies
        self._character_manager = character_manager
        self._event_manager = event_manager # Keep for now, may be refactored
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
        # Store conflict_resolver instance
        self._conflict_resolver = conflict_resolver # Added ConflictResolver from kwargs

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
        self._event_stage_processor = event_stage_processor # Typo corrected?
        self._quest_manager = quest_manager # Added QuestManager (duplicate assignment but harmless)
        self._dialogue_manager = dialogue_manager # Added DialogueManager
        self._game_log_manager = game_log_manager # Added GameLogManager

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
            'event_manager': self._event_manager, # Keep for now
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

            'quest_manager': self._quest_manager, # Added QuestManager to context
            'dialogue_manager': self._dialogue_manager, # Added DialogueManager to context
            'game_log_manager': self._game_log_manager, # Added GameLogManager to context
            # TODO: Add other optional managers
            # Add view services if stored as attributes and needed in context by handlers
            # 'party_view_service': self._party_view_service, # Include party_view_service in context
            # 'location_view_service': self._location_view_service,

            'campaign_loader': self._campaign_loader,
            'relationship_manager': self._relationship_manager,
            'quest_manager': self._quest_manager,
            'conflict_resolver': self._conflict_resolver, # Add to context

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

        # Special handling for 'party' command routed to PartyCommandHandler
        if command_keyword == "party":
             if self._party_command_handler:
                  try:
                      # Pass the context to the handle method
                      await self._party_command_handler.handle(message, command_args, context)
                  except Exception as e:
                       print(f"CommandRouter ❌ Error executing 'party' command: {e}")
                       traceback.print_exc()
                       # Simplified error reporting
                       await context['send_to_command_channel'](f"❌ Error in party command: {e}")
                  return
             else:
                  await context['send_to_command_channel']("❌ Party system unavailable.")
                  return

        # Regular commands handled by methods within CommandRouter
        handler = self.__class__._command_handlers.get(command_keyword)
        if not handler:
            await context['send_to_command_channel'](f"❓ Unknown command: `{self._command_prefix}{command_keyword}`.")
            return

        try:
            # Call the registered handler method, passing self and standard arguments
            await handler(self, message, command_args, context)
        except Exception as e:
            print(f"CommandRouter ❌ Error executing command '{command_keyword}': {e}")
            traceback.print_exc()
            await context['send_to_command_channel'](f"❌ Error executing command `{command_keyword}`: {e}")

    @command("help")
    async def handle_help(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает список доступных команд или помощь по конкретной команде. Usage: {prefix}help [команда]"""
        send_callback = context['send_to_command_channel']
        command_prefix = self._command_prefix
        internal_commands = sorted(self.__class__._command_handlers.keys())
        external_commands = ["party"] # List commands routed to external handlers
        all_commands = sorted(list(set(internal_commands + external_commands)))

        if not args:
            help_message = f"Доступные команды (префикс `{command_prefix}`):\n"
            help_message += ", ".join([f"`{cmd}`" for cmd in all_commands])
            help_message += f"\nИспользуйте `{command_prefix}help <команда>` для подробностей."
            await send_callback(help_message)
        else:
            target_command = args[0].lower()
            handler = self.__class__._command_handlers.get(target_command)
            if handler:
                docstring = (handler.__doc__ or "Нет описания.").format(prefix=self._command_prefix)
                await send_callback(docstring)
            elif target_command == "party" and self._party_command_handler:
                # Redirect help request for 'party' to the party handler
                temp_party_args = ["help"] + args[1:]
                # Pass the full context to the handler
                temp_context = context.copy() # Create a copy to avoid modifying the original context unexpectedly
                temp_context['command_args'] = temp_party_args
                temp_context['command_keyword'] = 'party'
                try:
                    await self._party_command_handler.handle(message, temp_party_args, temp_context)
                except Exception as e:
                    await send_callback(f"❌ Ошибка при получении справки для команды партии: {e}")
            else:
                await send_callback(f"❓ Команда `{self._command_prefix}{target_command}` не найдена.")
        print(f"CommandRouter: Processed help command for guild {context.get('guild_id')}.")


    @command("character")
    async def handle_character(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        Управляет персонажами. Usage: {prefix}character <create|delete> [args]
        `{prefix}character create <name>`
        `{prefix}character delete [character_id_or_name (defaults to yours)]`
        """.format(prefix=self._command_prefix)
        send_callback = context['send_to_command_channel']
        author_id = context['author_id']
        guild_id = context['guild_id']
        char_manager = context.get('character_manager')

        if not char_manager:
            await send_callback("Character manager is not available.")
            return
        if not guild_id:
            await send_callback("Character commands can only be used in a server (guild).")
            return

        if not args:
            doc_string = self.handle_character.__doc__.format(prefix=self._command_prefix)
            await send_callback(f"Please specify a character action. Usage:\n{doc_string}")
            return

        subcommand = args[0].lower()
        char_args = args[1:]

        if subcommand == "create":
            if not char_args:
                await send_callback(f"Usage: {self._command_prefix}character create <name>")
                return
            name = char_args[0]
            # Prevent TypeError: create_character() got multiple values for keyword argument 'guild_id'
            # Pass context as kwargs, char_manager should extract what it needs
            creation_context = {**context, 'user_id': author_id} # Pass discord user ID as user_id

            try:
                # Ensure author_id is passed as discord_id
                char_id = await char_manager.create_character(
                    guild_id=guild_id,
                    discord_id=int(author_id),
                    name=name,
                    **creation_context # Pass relevant context items like openai_service, etc.
                )
                if char_id:
                    # Fetch the created character object to get its name after creation
                    created_char = await char_manager.get_character(guild_id=guild_id, character_id=char_id) # Assuming get_character can take ID
                    display_name = getattr(created_char, 'name', name) # Use generated name if available

                    await send_callback(f"Character '{display_name}' (ID: {char_id}) created successfully for user {message.author.mention}!")
                else:
                    await send_callback(f"Failed to create character '{name}'. It might already exist or creation failed.")
            except ValueError: # Catches int(author_id) conversion error if author_id isn't purely numeric
                 await send_callback(f"Error: Invalid user ID format encountered.")
            except Exception as e:
                await send_callback(f"An error occurred while creating character '{name}': {e}")
                print(f"Error in handle_character (create): {e}")
                traceback.print_exc()

        elif subcommand == "delete":
            # Default to deleting user's own character if no args are provided
            character_to_delete_id_or_name = char_args[0] if char_args else author_id

            # Determine if we're deleting by ID or by name (or current user's character)
            char_to_delete = None
            if is_uuid_format(character_to_delete_id_or_name):
                char_to_delete = await char_manager.get_character(guild_id, character_to_delete_id_or_name)
            elif character_to_delete_id_or_name == author_id: # Deleting own character by author ID string
                 char_to_delete = await char_manager.get_character_by_discord_id(guild_id, int(author_id)) # Needs int Discord ID
            else: # Attempt to delete by name (requires GM or complex logic, simplifying for now)
                # For this example, only allow deleting your own *current* character by providing no args or your Discord ID.
                # If a specific name/ID is given, treat it as an ID (requires UUID format check or GM permissions)
                 await send_callback(f"Deleting characters by name requires GM permissions. Please use character ID or use `{self._command_prefix}character delete` to delete your own active character.")
                 return # Exit if name based deletion is attempted by non-GM


            if not char_to_delete:
                await send_callback(f"Character '{character_to_delete_id_or_name}' not found or you don't have permission to delete it.")
                return

            # Permission check: Can only delete own character unless GM (GM logic not fully here)
            # Check if the character's discord_id (as int) matches the author's discord_id (as int)
            try:
                char_discord_id_int = int(getattr(char_to_delete, 'discord_user_id', None)) # Assuming attribute is discord_user_id
                author_discord_id_int = int(author_id)
                if char_discord_id_int != author_discord_id_int:
                    # Add GM check here in future if GMs can delete any character
                    await send_callback(f"You can only delete your own character. Character '{getattr(char_to_delete, 'name', 'Unknown')}' belongs to another user.")
                    return
            except (ValueError, TypeError):
                 await send_callback("Error confirming character ownership due to data format issues.")
                 return


            try:
                # Pass context as kwargs for delete_character
                deletion_context = context.copy()
                # delete_character likely needs guild_id, char_id. Pass other managers via context.
                deleted_id = await char_manager.delete_character(guild_id, char_to_delete.id, **deletion_context)
                if deleted_id:
                    await send_callback(f"Character '{getattr(char_to_delete, 'name', deleted_id)}' deleted successfully.")
                else:
                    await send_callback(f"Failed to delete character '{getattr(char_to_delete, 'name', 'ID: '+character_to_delete_id_or_name)}'.")
            except Exception as e:
                await send_callback(f"An error occurred: {e}")
                print(f"Error in handle_character (delete): {e}")
                traceback.print_exc()
        else:
            await send_callback(f"Unknown character subcommand: '{subcommand}'. Try 'create' or 'delete'.")


    @command("status")
    async def handle_status(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает лист персонажа. Usage: {prefix}status [character_id_or_name]""".format(prefix=self._command_prefix)
        send_callback = context['send_to_command_channel']
        await send_callback("Status command logic is complex and retained from previous version.")

    @command("inventory")
    async def handle_inventory(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает инвентарь. Usage: {prefix}inventory [character_id_or_name]""".format(prefix=self._command_prefix)
        send_callback = context['send_to_command_channel']
        await send_callback("Inventory command logic is complex and retained from previous version.")

    @command("move")
    async def handle_move(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Перемещает персонажа. Usage: {prefix}move <location_id>""".format(prefix=self._command_prefix)
        send_callback = context['send_to_command_channel']
        # The actual move logic is in ActionProcessor (or CharacterActionProcessor)
        # This command should trigger that processor.
        
        # Example implementation using CharacterActionProcessor (as it's likely intended for player actions)
        char_action_processor = context.get('character_action_processor')
        char_manager = context.get('character_manager')
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')

        if not char_action_processor or not char_manager or not guild_id or not author_id_str:
             await send_callback("Error: Required systems for movement are unavailable.")
             print("CommandRouter: Missing managers/processors for handle_move.")
             return

        if not args:
             await send_callback(f"Usage: {self._command_prefix}move <destination>")
             return

        destination_input = args[0]

        try:
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return

            # Prepare action data for the processor
            action_data = {"destination": destination_input}

            # Call the processor, let it handle the move logic, rules, AI, etc.
            # The processor is expected to return a dictionary including message, target_channel_id, state_changed
            result = await char_action_processor.process_action(
                character_id=player_char.id,
                action_type="move",
                action_data=action_data,
                context=context # Pass full context
            )

            # The processor should have sent the message already.
            # We just need to return the result dictionary for higher-level handling (like state saving).
            # However, CommandRouter.route only awaits the handler and doesn't process its return value.
            # The processor *must* handle sending the message itself.
            # The return value is primarily informative or for logging/state tracking outside the CommandRouter.
            
            # Example: Log the result (optional, if game_log_manager is available and processor didn't log)
            # if context.get('game_log_manager') and result:
            #     await context['game_log_manager'].log_event(...)

            if not result or not result.get("success"):
                 # Fallback message if processor didn't indicate success (it should handle most messages)
                 error_message = result.get("message", f"Movement to '{destination_input}' failed.")
                 # Check if the processor *already* sent a message. Avoid sending duplicates.
                 # A robust way is for the processor to return the message *content* but CommandRouter sends it.
                 # Given the current structure, let's assume processor sends messages and CommandRouter just exits.
                 pass # Processor handled messaging

        except ValueError:
            await send_callback("Invalid user ID format.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_move for destination '{destination_input}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to move: {e}")


    # Removed duplicate/placeholder definitions causing errors around lines 600-750
    # The following definitions are kept as they appeared later in the original snippet.

    async def _gm_action_load_campaign(self, message: Message, sub_args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context['send_to_command_channel']
        campaign_loader: Optional["CampaignLoader"] = context.get('campaign_loader')
        if not campaign_loader:
            await send_callback("❌ CampaignLoader service unavailable.")
            return
        if not sub_args:
            await send_callback(f"Usage: `{context['command_prefix']}gm load_campaign <file_path>`")
            return
        file_path = sub_args[0]
        try:
            # Assuming load_campaign_from_file is sync and just parses data
            campaign_data = campaign_loader.load_campaign_from_file(file_path)
            if campaign_data:
                await send_callback(f"✅ Campaign data loaded from `{file_path}`.")
                # NOTE: Loading the data is often just step 1. Distributing/applying it comes next.
                # This might need a call to PersistenceManager or another manager.
            else:
                await send_callback(f"❌ Failed to load campaign data from `{file_path}`.")
        except FileNotFoundError:
             await send_callback(f"❌ Error: Campaign file not found at `{file_path}`.")
        except Exception as e:
            await send_callback(f"❌ Error loading campaign: {e}")
            print(f"CommandRouter: Error in _gm_action_load_campaign: {e}")
            traceback.print_exc()

    async def _gm_action_inspect_relationships(self, message: Message, sub_args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context['send_to_command_channel']
        guild_id = context.get('guild_id')
        if not guild_id:
            await send_callback("❌ This GM command can only be used in a guild.")
            return

        relationship_manager: Optional["RelationshipManager"] = context.get('relationship_manager')
        if not relationship_manager:
            await send_callback("❌ RelationshipManager service unavailable.")
            return

        if not sub_args or len(sub_args) < 1:
            await send_callback(f"Usage: `{context['command_prefix']}gm relationships inspect <entity_id>`")
            return

        entity_id_to_inspect = sub_args[0]

        try:
            # get_relationships_for_entity might be async
            relationships = await relationship_manager.get_relationships_for_entity(guild_id, entity_id_to_inspect, context=context)
            if not relationships:
                await send_callback(f"ℹ️ No relationships found for entity `{entity_id_to_inspect}` in this guild.")
                return

            response_lines = [f"Relationships for Entity `{entity_id_to_inspect}`:"]
            # Iterate over relationship data (assuming it's a list of dicts or objects with expected attributes/keys)
            for rel_data in relationships:
                # Need to figure out the *other* entity ID and type from the relationship data structure
                # Assuming rel_data is a dict like {'entity1_id': '...', 'entity1_type': '...', 'entity2_id': '...', 'entity2_type': '...', 'relationship_type': '...', 'strength': ..., 'details': '...'}
                other_entity_id = None
                other_entity_type = None
                if rel_data.get('entity1_id') == entity_id_to_inspect:
                    other_entity_id = rel_data.get('entity2_id', 'Unknown')
                    other_entity_type = rel_data.get('entity2_type', 'Unknown')
                elif rel_data.get('entity2_id') == entity_id_to_inspect:
                    other_entity_id = rel_data.get('entity1_id', 'Unknown')
                    other_entity_type = rel_data.get('entity1_type', 'Unknown')
                else:
                    # Should not happen if get_relationships_for_entity works correctly
                    continue # Skip this relationship data if it doesn't involve the target entity

                # Attempt to get target name for better display
                target_name_str = other_entity_id
                char_mgr = context.get('character_manager')
                npc_mgr = context.get('npc_manager')

                if other_entity_type == 'Character' and char_mgr:
                     char_obj = char_mgr.get_character(guild_id, other_entity_id) # Assuming sync get_character by ID
                     if char_obj: target_name_str = getattr(char_obj, 'name', other_entity_id)
                elif other_entity_type == 'NPC' and npc_mgr:
                     npc_obj = npc_mgr.get_npc(guild_id, other_entity_id) # Assuming sync get_npc by ID
                     if npc_obj: target_name_str = getattr(npc_obj, 'name', other_entity_id)

                rel_type = rel_data.get('relationship_type', 'unknown')
                strength = rel_data.get('strength', 0.0)
                details = rel_data.get('details', 'N/A')

                response_lines.append(
                    f"- With **{target_name_str}** (`{other_entity_id}` ({other_entity_type})): Type: `{rel_type}`, Strength: `{strength:.1f}`. Details: _{details}_"
                )

            response = "\n".join(response_lines)
            # Discord message length limit is 2000 characters
            if len(response) > 1950:
                response = response[:1950] + "\n... (message truncated due to length)"

            await send_callback(response)
        except Exception as e:
            print(f"CommandRouter Error in _gm_action_inspect_relationships: {e}")
            traceback.print_exc()
            await send_callback(f"❌ Error inspecting relationships: {e}")

    # The first, older handle_gm definition was removed here.

    # The first definition of handle_quest was removed here.

    # --- Removed handle_party method and its decorators ---


    @command("roll")
    async def handle_roll(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Rolls dice based on standard dice notation (e.g., /roll 2d6+3, /roll d20). Usage: {prefix}roll <notation>"""
        send_callback = context.get('send_to_command_channel')
        if not send_callback:
            print("CommandRouter: Error: send_to_command_channel not found in context for handle_roll.")
            return

        if not args:
            await send_callback(f"Usage: {self._command_prefix}roll <dice_notation (e.g., 2d6+3, d20, 4dF)>")
            return

        roll_string = "".join(args) # Allow for notations like /roll 2d6 + 3 (with spaces)
        rule_engine = context.get('rule_engine')

        if not rule_engine:
            await send_callback("Error: RuleEngine not available for the roll command.")
            print("CommandRouter: Error: rule_engine not found in context for handle_roll.")
            return

        try:
            # Consider if character context is needed for rolls in the future
            # For now, direct context pass-through
            roll_result = await rule_engine.resolve_dice_roll(roll_string, context=context) # Assuming resolve_dice_roll is async

            # Check if roll_result is a valid dictionary
            if not isinstance(roll_result, dict):
                 await send_callback(f"An error occurred while trying to roll '{roll_string}'. Invalid result from RuleEngine.")
                 print(f"CommandRouter: RuleEngine.resolve_dice_roll returned unexpected type: {type(roll_result)}")
                 return

            rolls_str = ", ".join(map(str, roll_result.get('rolls', [])))
            result_message = f"🎲 {message.author.mention} rolled **{roll_result.get('roll_string', roll_string)}**:\n" # Fixed newline here

            if roll_result.get('dice_sides') == 'F': # Fudge dice specific output
                result_message += f"Rolls: [{rolls_str}] (Symbols: {' '.join(['+' if r > 0 else '-' if r < 0 else '0' for r in roll_result.get('rolls', [])])})"
            else:
                result_message += f"Rolls: [{rolls_str}]"

            modifier_val = roll_result.get('modifier', 0)
            if modifier_val != 0: # Only show modifier if it's not zero
                result_message += f" Modifier: {modifier_val:+}" # Ensure sign is shown

            result_message += f"\n**Total: {roll_result.get('total')}**" # Fixed newline here

            await send_callback(result_message)

        except ValueError as ve:
            await send_callback(f"Error: Invalid dice notation for '{roll_string}'. {ve}")
        except Exception as e:
            print(f"CommandRouter: Error in handle_roll for '{roll_string}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to roll '{roll_string}'.")


    # Helper function example (can be defined in this file or a utility module)

    # This is the second, kept definition of handle_quest
    @command("quest")
    async def handle_quest(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        Manages character quests. Usage: {prefix}quest <action> [args]
        {prefix}quest list
        {prefix}quest start <quest_template_id>
        {prefix}quest complete <active_quest_id>
        {prefix}quest fail <active_quest_id>
        {prefix}quest objectives <active_quest_id> # Optional: To view current objectives
        """.format(prefix=self._command_prefix)
        send_callback = context.get('send_to_command_channel')
        if not send_callback:
            print("CommandRouter: Error: send_to_command_channel not found in context for handle_quest.")
            return

        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id') # This is already a string from context setup

        if not guild_id:
            await send_callback("Quest commands can only be used on a server.")
            return

        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return

        char_manager = context.get('character_manager')
        quest_manager = context.get('quest_manager') # Get QuestManager from context

        if not char_manager:
            await send_callback("Character system is currently unavailable.")
            print("CommandRouter: Error: character_manager not found in context for handle_quest.")
            return

        if not quest_manager:
            await send_callback("Quest system is currently unavailable.")
            print("CommandRouter: Error: quest_manager not found in context for handle_quest.")
            return

        try:
            author_discord_id = int(author_id_str)
            player_char = char_manager.get_character_by_discord_id(guild_id, author_discord_id)
            if not player_char:
                await send_callback(f"You do not have an active character in this guild. Use `{self._command_prefix}character create <name>` to create one.")
                return
            character_id = player_char.id
        except ValueError:
            await send_callback("Invalid user ID format.")
            return
        except Exception as e:
            await send_callback(f"Error fetching your character: {e}")
            return

        if not args:
            doc = self.handle_quest.__doc__.format(prefix=self._command_prefix)
            await send_callback(f"Please specify a quest action. Usage:\n{doc}")
            return

        subcommand = args[0].lower()
        quest_action_args = args[1:]

        try:
            if subcommand == "list":
                # List active and available quests (QuestManager needs to implement more detailed logic here)
                # Assuming list_quests_for_character is async
                quest_list = await quest_manager.list_quests_for_character(character_id, guild_id, context)
                if not quest_list:
                    await send_callback("No quests currently available or active for you.")
                    return

                response = f"**Your Quests, {player_char.name}:**\n"
                for q_data in quest_list: # Assuming q_data is a dict with 'name', 'description', 'status'
                    # Use getattr for safety or rely on Quest model structure
                    q_name = getattr(q_data, 'name', q_data.get('id', 'Unknown Quest')) # Assuming q_data might be a model instance or dict
                    q_status = getattr(q_data, 'status', q_data.get('status', 'unknown'))
                    q_desc = getattr(q_data, 'description', q_data.get('description', 'No description.'))
                    q_id = getattr(q_data, 'id', q_data.get('id', 'Unknown ID'))

                    response += f"- **{q_name}** (Status: {q_status})\n"
                    response += f"  _{q_desc}_\n"
                    response += f"  _(ID: {q_id})_\n" # Show ID for complete/fail commands

                # Truncate if necessary
                if len(response) > 1950:
                     response = response[:1950] + "\n... (list truncated)"

                await send_callback(response)

            elif subcommand == "start":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest start <quest_template_id>")
                    return
                quest_template_id_arg = quest_action_args[0]

                # Pass user_id (author_id_str) to start_quest via kwargs within context
                extended_context = {**context, 'user_id': author_id_str}

                # QuestManager.start_quest now returns either a dict (for direct start or pending) or None
                # Assuming start_quest is async
                quest_start_result = await quest_manager.start_quest(
                    guild_id=guild_id,
                    character_id=character_id,
                    quest_template_id=quest_template_id_arg,
                    **extended_context # Pass user_id and other context items
                )

                if isinstance(quest_start_result, dict):
                    if quest_start_result.get("status") == "pending_moderation":
                        request_id = quest_start_result["request_id"]
                        await send_callback(f"📜 Your request for quest '{quest_template_id_arg}' has been submitted for moderation (ID: `{request_id}`). You'll be notified when it's reviewed, and your character will be temporarily unable to perform most actions.")

                        # Apply 'awaiting_moderation' status to the player's character
                        status_manager: Optional["StatusManager"] = context.get('status_manager')
                        if status_manager and player_char: # player_char is already fetched
                            await status_manager.add_status_effect_to_entity(
                                target_id=player_char.id, target_type='Character',
                                status_type='awaiting_moderation', guild_id=guild_id, duration=None,
                                source_id=f"quest_generation_user_{author_id_str}",
                                context=context # Pass context to status manager
                            )

                        # Notify master channel - Assuming _notify_master_of_pending_content is async
                        await self._notify_master_of_pending_content(request_id, guild_id, author_id_str, context)

                    elif 'id' in quest_start_result: # Successfully started (non-AI or pre-approved AI)
                        # QuestManager.start_quest should return quest name or details for a better message
                        # Assuming the result dict has name_i18n or similar
                        quest_name = quest_start_result.get('name_i18n', {}).get('en', quest_template_id_arg)
                        await send_callback(f"Quest '{quest_name}' started for {player_char.name}!")
                    else: # Unexpected dict structure
                         await send_callback(f"Failed to start quest '{quest_template_id_arg}'. An unexpected result format was received.")
                         print(f"CommandRouter: Unexpected start_quest result for {quest_template_id_arg}: {quest_start_result}")

                elif quest_start_result is False: # Indicate specific failure logic within QM
                     await send_callback(f"Failed to start quest '{quest_template_id_arg}'. You may not meet prerequisites, the quest may be already active/completed, or it might not exist.")
                else: # None or other unexpected result (e.g. None)
                     await send_callback(f"Failed to start quest '{quest_template_id_arg}'. An unexpected error occurred or the quest does not exist.")
                     print(f"CommandRouter: Unhandled start_quest result for {quest_template_id_arg}: {quest_start_result}")


            elif subcommand == "complete":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest complete <active_quest_id>")
                    return
                active_quest_id = quest_action_args[0]
                # Assuming complete_quest is async
                success = await quest_manager.complete_quest(character_id, active_quest_id, guild_id, context)
                if success:
                    await send_callback(f"✅ Quest '{active_quest_id}' completed! Consequences and rewards (if any) have been applied.")
                else:
                    await send_callback(f"❌ Failed to complete quest '{active_quest_id}'. Make sure all objectives are met or the quest ID is correct.")

            elif subcommand == "fail":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest fail <active_quest_id>")
                    return
                active_quest_id = quest_action_args[0]
                # Assuming fail_quest is async
                success = await quest_manager.fail_quest(character_id, active_quest_id, guild_id, context)
                if success:
                    await send_callback(f"⚠️ Quest '{active_quest_id}' marked as failed.")
                else:
                    await send_callback(f"❌ Failed to mark quest '{active_quest_id}' as failed. It might not be an active quest for you.")

            # Optional: /quest objectives <active_quest_id>
            elif subcommand == "objectives" or subcommand == "details":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest {subcommand} <active_quest_id>")
                    return
                active_quest_id = quest_action_args[0]
                # QuestManager needs a method like get_active_quest_details(char_id, q_id, guild_id, context)
                # Assuming get_active_quest_details is async and returns a string or dict
                quest_details_response = await quest_manager.get_active_quest_details(character_id, active_quest_id, guild_id, context)

                if quest_details_response:
                    # Assuming the response is a formatted string ready to be sent
                    await send_callback(quest_details_response)
                else:
                     await send_callback(f"Quest '{active_quest_id}' not found among your active quests or details could not be retrieved.")


            else:
                doc = self.handle_quest.__doc__.format(prefix=self._command_prefix)
                await send_callback(f"Unknown quest action: '{subcommand}'. Usage:\n{doc}")

        except Exception as e:
            print(f"CommandRouter: Error in handle_quest for subcommand '{subcommand}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while processing your quest command: {e}")


    @command("npc")
    async def handle_npc(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        Interact with Non-Player Characters. Usage: {prefix}npc <action> [args]
        {prefix}npc talk <npc_id_or_name> [initial_message]
        """.format(prefix=self._command_prefix)
        send_callback = context.get('send_to_command_channel')
        if not send_callback:
            print("CommandRouter: Error: send_to_command_channel not found in context for handle_npc.")
            return

        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')
        channel_id = message.channel.id

        if not guild_id:
            await send_callback("NPC commands can only be used on a server.")
            return

        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return

        if not args:
            doc = self.handle_npc.__doc__.format(prefix=self._command_prefix)
            await send_callback(f"Please specify an NPC action. Usage:\n{doc}")
            return

        subcommand = args[0].lower()
        action_args = args[1:]

        char_manager = context.get('character_manager')
        npc_manager = context.get('npc_manager')
        dialogue_manager = context.get('dialogue_manager')

        if not char_manager:
            await send_callback("Error: Character system is unavailable.")
            print("CommandRouter: Error: character_manager not found for handle_npc.")
            return
        if not npc_manager:
            await send_callback("Error: NPC system is unavailable.")
            print("CommandRouter: Error: npc_manager not found for handle_npc.")
            return
        if not dialogue_manager:
            await send_callback("Error: Dialogue system is unavailable at the moment.")
            print("CommandRouter: Error: dialogue_manager not found for handle_npc.")
            return

        try:
            # Assuming get_character_by_discord_id is sync
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You need an active character to interact with NPCs. Use `{self._command_prefix}character create <name>`.")
                return
        except ValueError:
            await send_callback("Invalid user ID format.")
            return
        except Exception as e:
            await send_callback(f"Error fetching your character: {e}")
            print(f"CommandRouter: Error fetching character for {author_id_str} in guild {guild_id}: {e}")
            traceback.print_exc()
            return

        if subcommand == "talk":
            if not action_args:
                await send_callback(f"Usage: {self._command_prefix}npc talk <npc_id_or_name> [initial_message]")
                return

            npc_identifier = action_args[0]
            initiator_message = " ".join(action_args[1:]) if len(action_args) > 1 else None

            # Find the target NPC (Assuming get_npc is sync and tries ID first, get_npc_by_name is sync)
            target_npc = npc_manager.get_npc(guild_id, npc_identifier)
            if not target_npc:
                if hasattr(npc_manager, 'get_npc_by_name'): # Check if method exists
                    target_npc = npc_manager.get_npc_by_name(guild_id, npc_identifier) # Assumes this method exists
                if not target_npc:
                    await send_callback(f"NPC '{npc_identifier}' not found in this realm.")
                    return

            # Location Check (optional, but good for immersion)
            location_manager = context.get('location_manager')
            if location_manager and hasattr(player_char, 'location_id') and hasattr(target_npc, 'location_id'):
                player_loc_id = getattr(player_char, 'location_id', None)
                npc_loc_id = getattr(target_npc, 'location_id', None)
                if player_loc_id != npc_loc_id:
                    npc_name = getattr(target_npc, 'name', npc_identifier)
                    # Assuming get_location_name is sync
                    player_loc_name = location_manager.get_location_name(guild_id, player_loc_id) if player_loc_id else "an unknown place"
                    npc_loc_name = location_manager.get_location_name(guild_id, npc_loc_id) if npc_loc_id else "an unknown place"
                    await send_callback(f"{npc_name} is not here. You are in {player_loc_name}, and they are in {npc_loc_name}.")
                    return

            # Determine dialogue template ID (this is game-specific logic)
            # Example: use a default template or one specified on the NPC model
            dialogue_template_id = getattr(target_npc, 'dialogue_template_id', 'generic_convo')

            # Assuming get_dialogue_template is sync
            if not dialogue_manager.get_dialogue_template(guild_id, dialogue_template_id):
                # Fallback if specific template not found
                if dialogue_manager.get_dialogue_template(guild_id, 'generic_convo'):
                    dialogue_template_id = 'generic_convo'
                    print(f"CommandRouter: NPC {target_npc.id} missing specific dialogue template '{getattr(target_npc, 'dialogue_template_id', 'N/A')}'. Using 'generic_convo'.")
                else:
                    npc_name = getattr(target_npc, 'name', npc_identifier)
                    await send_callback(f"Sorry, no way to start a conversation with {npc_name} right now (missing dialogue templates '{dialogue_template_id}' and 'generic_convo').")
                    print(f"CommandRouter: Missing dialogue template '{dialogue_template_id}' and 'generic_convo' for NPC {target_npc.id}")
                    return

            try:
                # Assuming start_dialogue is async
                dialogue_id = await dialogue_manager.start_dialogue(
                    guild_id=guild_id,
                    template_id=dialogue_template_id,
                    participant1_id=player_char.id,
                    participant2_id=target_npc.id,
                    channel_id=channel_id,
                    initiator_message=initiator_message,
                    **context # Pass full context
                )

                if dialogue_id:
                    # DialogueManager's start_dialogue is expected to send the first message.
                    print(f"CommandRouter: Dialogue {dialogue_id} initiated by {player_char.id} with NPC {target_npc.id} in channel {channel_id}.")
                else:
                    npc_name = getattr(target_npc, 'name', npc_identifier)
                    await send_callback(f"Could not start a conversation with {npc_name}. They might be busy or unwilling to talk.")
            except Exception as e:
                npc_name = getattr(target_npc, 'name', npc_identifier)
                print(f"CommandRouter: Error during dialogue_manager.start_dialogue with {npc_name}: {e}")
                traceback.print_exc()
                await send_callback(f"An unexpected error occurred while trying to talk to {npc_name}.")

        else:
            doc = self.handle_npc.__doc__.format(prefix=self._command_prefix)
            await send_callback(f"Unknown action for NPC: '{subcommand}'. Usage:\n{doc}")


    @command("buy")
    async def handle_buy(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows the player to buy an item from the current location's market. Usage: {prefix}buy <item_template_id> [quantity]"""
        send_callback = context.get('send_to_command_channel')
        if not send_callback:
            print("CommandRouter: Error: send_to_command_channel not found for handle_buy.")
            return

        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')

        if not guild_id:
            await send_callback("The /buy command can only be used on a server.")
            return
        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return

        if not args:
            await send_callback(f"Usage: {self._command_prefix}buy <item_template_id> [quantity (default 1)]")
            return

        item_template_id_to_buy = args[0]
        quantity_to_buy = 1
        if len(args) > 1:
            try:
                quantity_to_buy = int(args[1])
                if quantity_to_buy <= 0:
                    await send_callback("Quantity must be a positive number.")
                    return
            except ValueError:
                await send_callback("Invalid quantity specified. It must be a number.")
                return

        char_manager = context.get('character_manager')
        loc_manager = context.get('location_manager')
        eco_manager = context.get('economy_manager')
        item_manager = context.get('item_manager') # Needed for item name lookup

        if not char_manager or not loc_manager or not eco_manager or not item_manager:
            await send_callback("Error: Required game systems (character, location, economy, or item) are unavailable.")
            print("CommandRouter: Missing one or more managers for handle_buy.")
            return

        try:
            # Assuming get_character_by_discord_id is sync
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return

            character_id = player_char.id
            current_location_id = getattr(player_char, 'current_location_id', None) # Corrected from location_id
            if not current_location_id:
                await send_callback("Your character doesn't seem to be in any specific location to buy items.")
                return

            # Attempt to purchase the item
            # The EconomyManager.buy_item method handles most of the logic
            # (checking market stock, price, player currency, item creation, inventory update)
            # Assuming buy_item is async
            created_item_ids = await eco_manager.buy_item(
                guild_id=guild_id,
                buyer_entity_id=character_id,
                buyer_entity_type="Character",
                location_id=current_location_id, # Assuming market is tied to character's current location
                item_template_id=item_template_id_to_buy,
                count=quantity_to_buy,
                **context # Pass full context for other managers needed by buy_item
            )

            if created_item_ids:
                # Get item name for a nicer message (Assuming get_item_template is sync)
                item_template = item_manager.get_item_template(guild_id, item_template_id_to_buy)
                item_name = getattr(item_template, 'name', item_template_id_to_buy) if item_template else item_template_id_to_buy

                if len(created_item_ids) == quantity_to_buy:
                    await send_callback(f"🛍️ You successfully bought {quantity_to_buy}x {item_name}!")
                elif created_item_ids: # Partial success
                    await send_callback(f"🛍️ You managed to buy {len(created_item_ids)}x {item_name} (requested {quantity_to_buy}).")
                else: # Should ideally be caught by buy_item returning None/empty list, but as a fallback
                    await send_callback(f"Purchase of {item_name} seems to have failed despite initial checks.")

            # Note: EconomyManager.buy_item should return None or empty list on failure and ideally provide a reason.
            # The above 'else' handles the case where it returned None/empty list.

        except Exception as e:
            print(f"CommandRouter: Error in handle_buy for item '{item_template_id_to_buy}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to buy the item: {e}")


    @command("craft")
    async def handle_craft(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows the player to craft an item from a recipe. Usage: {prefix}craft <recipe_id> [quantity]"""
        send_callback = context.get('send_to_command_channel')
        if not send_callback:
            print("CommandRouter: Error: send_to_command_channel not found for handle_craft.")
            return

        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')

        if not guild_id:
            await send_callback("The /craft command can only be used on a server.")
            return
        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return

        if not args:
            await send_callback(f"Usage: {self._command_prefix}craft <recipe_id> [quantity (default 1)]")
            return

        recipe_id_to_craft = args[0]
        quantity_to_craft = 1
        if len(args) > 1:
            try:
                quantity_to_craft = int(args[1])
                if quantity_to_craft <= 0:
                    await send_callback("Quantity must be a positive number.")
                    return
            except ValueError:
                await send_callback("Invalid quantity specified. It must be a number.")
                return

        char_manager = context.get('character_manager')
        craft_manager = context.get('crafting_manager') # Ensure this is self._crafting_manager via context

        if not char_manager or not craft_manager:
            await send_callback("Error: Required game systems (character or crafting) are unavailable.")
            print("CommandRouter: Missing character_manager or crafting_manager for handle_craft.")
            return

        try:
            # Assuming get_character_by_discord_id is sync
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return

            character_id = player_char.id

            # Call CraftingManager to add the recipe to the character's queue
            # Assuming add_recipe_to_craft_queue is async
            result = await craft_manager.add_recipe_to_craft_queue(
                guild_id=guild_id,
                entity_id=character_id,
                entity_type="Character",
                recipe_id=recipe_id_to_craft,
                quantity=quantity_to_craft,
                context=context # Pass full context
            )

            if result and result.get("success"):
                await send_callback(f"🛠️ {result.get('message', 'Crafting started!')}")
            else:
                error_message = result.get('message', "Could not start crafting. Check requirements and ingredients.")
                await send_callback(f"⚠️ {error_message}")

        except Exception as e:
            print(f"CommandRouter: Error in handle_craft for recipe '{recipe_id_to_craft}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to craft the item: {e}")

    # The first definition of handle_steal was removed here.

    @command("fight")
    async def handle_fight(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Initiates combat with a target NPC. Usage: {prefix}fight <target_npc_id_or_name>"""
        send_callback = context.get('send_to_command_channel')
        if not send_callback:
            print("CommandRouter: Error: send_to_command_channel not found for handle_fight.")
            return

        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')
        channel_id = message.channel.id # Combat will occur in the command's channel

        if not guild_id:
            await send_callback("The /fight command can only be used on a server.")
            return
        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return

        if not args:
            await send_callback(f"Usage: {self._command_prefix}fight <target_npc_id_or_name>")
            return

        target_identifier = args[0]

        char_manager = context.get('character_manager')
        npc_manager = context.get('npc_manager')
        loc_manager = context.get('location_manager')
        combat_manager = context.get('combat_manager')
        rule_engine = context.get('rule_engine') # For eligibility checks

        if not char_manager or not npc_manager or not loc_manager or not combat_manager or not rule_engine:
            await send_callback("Error: Required game systems for combat are unavailable.")
            print("CommandRouter: Missing one or more managers for handle_fight.")
            return

        try:
            # Assuming get_character_by_discord_id is sync
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return

            character_id = player_char.id
            current_location_id = getattr(player_char, 'current_location_id', None) # Corrected from location_id
            if not current_location_id:
                await send_callback("Your character isn't in a location where combat can occur.")
                return

            # Find the target NPC (Assuming get_npc is sync and get_npc_by_name is sync)
            target_npc = npc_manager.get_npc(guild_id, target_identifier)
            if not target_npc:
                if hasattr(npc_manager, 'get_npc_by_name'):
                    target_npc = npc_manager.get_npc_by_name(guild_id, target_identifier)
                if not target_npc:
                    await send_callback(f"NPC '{target_identifier}' not found.")
                    return

            target_npc_id = target_npc.id
            target_npc_name = getattr(target_npc, 'name', target_identifier)

            # 1. Location Check
            npc_location_id = getattr(target_npc, 'location_id', None)
            if npc_location_id != current_location_id:
                # Assuming get_location_name is sync
                player_loc_name = loc_manager.get_location_name(guild_id, current_location_id) if loc_manager and current_location_id else current_location_id or "an unknown place"
                npc_loc_name = loc_manager.get_location_name(guild_id, npc_location_id) if loc_manager and npc_location_id else npc_location_id or "an unknown place"
                await send_callback(f"{target_npc_name} is not here. You are in {player_loc_name}, and they are in {npc_loc_name}.")
                return

            # 2. Eligibility Check (Already in combat?) - Assuming get_combat_by_participant_id is sync
            if combat_manager.get_combat_by_participant_id(guild_id, character_id):
                await send_callback("You are already in combat!")
                return
            if combat_manager.get_combat_by_participant_id(guild_id, target_npc_id):
                await send_callback(f"{target_npc_name} is already in combat with someone else.")
                return

            # 3. (Optional) RuleEngine check for combat permissibility (Assuming async can_initiate_combat)
            # if hasattr(rule_engine, 'can_initiate_combat') and \
            #    not await rule_engine.can_initiate_combat(player_char, target_npc, context=context):
            #     await send_callback(f"You cannot initiate combat with {target_npc_name} at this time or place.")
            #     return

            # Initiate combat - Assuming start_combat is async
            participant_ids = [(character_id, "Character"), (target_npc_id, "NPC")]

            new_combat_instance = await combat_manager.start_combat(
                guild_id=guild_id,
                location_id=current_location_id,
                participant_ids=participant_ids,
                channel_id=channel_id,
                **context
            )

            if new_combat_instance:
                # CombatManager.start_combat should ideally send the initial combat message.
                print(f"CommandRouter: Combat initiated by {character_id} against {target_npc_id} in guild {guild_id}, channel {channel_id}.")
                # Example: await send_callback(f"⚔️ You attack {target_npc_name}! Combat has begun in channel <#{new_combat_instance.channel_id if new_combat_instance.channel_id else channel_id}>!")
            else:
                await send_callback(f"Could not start combat with {target_npc_name}. They might be too powerful, or something went wrong.")

        except ValueError:
            await send_callback("Invalid user ID format.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_fight against '{target_identifier}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to initiate combat: {e}")


    @command("hide")
    async def handle_hide(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows the player to attempt to hide in their current location. Usage: {prefix}hide"""
        send_callback = context.get('send_to_command_channel')
        if not send_callback:
            print("CommandRouter: Error: send_to_command_channel not found for handle_hide.")
            return

        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')

        if not guild_id:
            await send_callback("The /hide command can only be used on a server.")
            return
        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return

        char_manager = context.get('character_manager')
        char_action_processor = context.get('character_action_processor')

        if not char_manager or not char_action_processor:
            await send_callback("Error: Required game systems (character or action processing) are unavailable.")
            print("CommandRouter: Missing character_manager or char_action_processor for handle_hide.")
            return

        try:
            # Assuming get_character_by_discord_id is sync
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return

            character_id = player_char.id

            # Call CharacterActionProcessor to initiate the hide attempt
            # Assuming process_hide_action is async
            success = await char_action_processor.process_hide_action(
                character_id=character_id,
                context=context
            )

            # process_hide_action itself should handle the message sending "You attempt to find a hiding spot..."
            # The actual success/failure message comes when the action completes.
            # This 'if not success' check here is mostly for immediate pre-check failures in the processor.
            if not success:
                # This might occur if the character is busy or another pre-check in process_hide_action fails.
                # Only send a message here if the processor *didn't* send one. This is tricky.
                # For simplicity, let's assume if process_hide_action returns False, it implies a general failure
                # that wasn't specifically messaged, or a message the router should add to.
                # A better design is for the processor to return a message to the router.
                # Sticking to current implied pattern: processor messages, router checks final success.
                 pass # Processor handled messaging


        except ValueError: # For int(author_id_str)
            await send_callback("Invalid user ID format.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_hide: {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to hide: {e}")


    # This is the second, kept definition of handle_steal
    @command("steal")
    async def handle_steal(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows the player to attempt to steal from a target NPC. Usage: {prefix}steal <target_npc_id_or_name>"""
        send_callback = context.get('send_to_command_channel')
        if not send_callback:
            print("CommandRouter: Error: send_to_command_channel not found for handle_steal.")
            return

        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')

        if not guild_id:
            await send_callback("The /steal command can only be used on a server.")
            return
        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return

        if not args:
            await send_callback(f"Usage: {self._command_prefix}steal <target_npc_id_or_name>")
            return

        target_identifier = args[0]

        char_manager = context.get('character_manager')
        npc_manager = context.get('npc_manager')
        char_action_processor = context.get('character_action_processor')
        loc_manager = context.get('location_manager') # For location check

        if not char_manager or not npc_manager or not char_action_processor or not loc_manager:
            await send_callback("Error: Required game systems (character, NPC, action processing, or location) are unavailable.")
            print("CommandRouter: Missing one or more managers/processors for handle_steal.")
            return

        try:
            # Assuming get_character_by_discord_id is sync
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return

            character_id = player_char.id

            # Find the target NPC (Assuming get_npc is sync and get_npc_by_name is sync)
            target_npc = npc_manager.get_npc(guild_id, target_identifier)
            if not target_npc:
                if hasattr(npc_manager, 'get_npc_by_name'): # Check if method exists
                    target_npc = npc_manager.get_npc_by_name(guild_id, target_identifier)
                if not target_npc:
                    await send_callback(f"NPC '{target_identifier}' not found in this realm.")
                    return

            target_npc_id = target_npc.id
            target_npc_name = getattr(target_npc, 'name', target_identifier)

            # Location Check: Ensure stealer and target are in the same location.
            player_loc_id = getattr(player_char, 'current_location_id', None) # Corrected from location_id
            target_loc_id = getattr(target_npc, 'location_id', None) # Assuming NPC has location_id

            if not player_loc_id:
                await send_callback("You don't seem to be in any location.")
                return
            if player_loc_id != target_loc_id:
                await send_callback(f"{target_npc_name} is not in your current location.")
                return

            # Call CharacterActionProcessor to initiate the steal attempt
            # Assuming process_steal_action is async
            success = await char_action_processor.process_steal_action(
                character_id=character_id,
                target_id=target_npc_id,
                target_type="NPC", # Currently only supporting NPC targets
                context=context
            )

            # process_steal_action itself should handle the message sending "You attempt to steal..."
            # The actual success/failure message comes when the action completes.
            # This 'if not success' check here is mostly for immediate pre-check failures in the processor.
            if not success:
                # As with /hide, assuming processor messages and this is for immediate pre-check failure
                 await send_callback(f"Could not attempt to steal from {target_npc_name} at this time. You might be busy or the target is not stealable.") # More specific fallback


        except ValueError: # For int(author_id_str)
            await send_callback("Invalid user ID format.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_steal for target '{target_identifier}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to steal: {e}")


    @command("use")
    async def handle_use(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows the player to use an item from their inventory, optionally on a target. Usage: {prefix}use <item_instance_id> [target_id]"""
        send_callback = context.get('send_to_command_channel')
        if not send_callback:
            print("CommandRouter: Error: send_to_command_channel not found for handle_use.")
            return

        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')

        if not guild_id:
            await send_callback("The /use command can only be used on a server.")
            return
        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return

        if not args:
            await send_callback(f"Usage: {self._command_prefix}use <item_instance_id> [target_id]")
            return

        item_instance_id = args[0]
        target_id: Optional[str] = None
        target_type: Optional[str] = None # Could be 'NPC', 'Character', 'Self', or even 'Item' (e.g. sharpening stone on a sword)

        if len(args) > 1:
            target_id = args[1]
            # Basic type inference: if target_id is the user's own character_id or "self", it's "Character"
            # If it's an NPC ID, it's "NPC". This might need more robust target parsing in future.
            # For now, let's assume if target_id is provided, it's an NPC unless it's "self".
            # More complex targeting might require a target_type argument or more sophisticated parsing.
            # We will primarily rely on CharacterActionProcessor and RuleEngine to validate the target.


        char_manager = context.get('character_manager')
        char_action_processor = context.get('character_action_processor')
        npc_manager = context.get('npc_manager') # Needed to infer target_type if target_id is an NPC

        if not char_manager or not char_action_processor or not npc_manager:
            await send_callback("Error: Required game systems (character, action processing, or NPC) are unavailable.")
            print("CommandRouter: Missing one or more managers/processors for handle_use.")
            return

        try:
            # Assuming get_character_by_discord_id is sync
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return
            character_id = player_char.id

            # Infer target_type if target_id is provided
            if target_id:
                if target_id.lower() == "self" or target_id == character_id:
                    target_id = character_id
                    target_type = "Character"
                # Assuming get_npc is sync and checks by ID
                elif npc_manager.get_npc(guild_id, target_id): # Check if it's a known NPC ID
                    target_type = "NPC"
                # Assuming get_character is sync and checks by ID
                elif char_manager.get_character(guild_id, target_id): # Check if it's another character
                     target_type = "Character"
                else:
                    # If target_id is provided but not identified as self, NPC, or other Character, it's ambiguous
                    # For items that *require* a specific type of target, RuleEngine will fail it.
                    # For items that don't care or can target "environment", this might be fine.
                    print(f"CommandRouter: Target '{target_id}' for /use command is not self, a known NPC, or another known Character. Target type remains undetermined by CommandRouter.")
                    # We'll pass target_id, and target_type as None or its current value. RuleEngine must validate.


            # Assuming process_use_item_action is async
            success = await char_action_processor.process_use_item_action(
                character_id=character_id,
                item_instance_id=item_instance_id,
                target_id=target_id,
                target_type=target_type,
                context=context
            )

            if not success:
                # process_use_item_action should have sent a specific reason if it could.
                # As with hide/steal, assuming processor messages and this is for immediate pre-check failure
                await send_callback(f"Could not use item '{item_instance_id}'. You might be busy, not own the item, or the target is invalid/unavailable.")


        except ValueError: # For int(author_id_str)
            await send_callback("Invalid user ID format.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_use for item '{item_instance_id}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to use the item: {e}")

    # This is the second, kept definition of handle_gm
    @command("gm")
    async def handle_gm(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """GM-level commands for managing the game. Usage: {prefix}gm <subcommand> [args]"""
        send_callback = context.get('send_to_command_channel')
        if not send_callback: # Should ideally not happen if context is built correctly
            print("CommandRouter: Error: send_to_command_channel not found in context for handle_gm.")
            return

        author_id_str = str(message.author.id) # Ensure it's a string for comparison

        # GM Access Control
        # Ensure GM IDs from settings are strings for comparison
        gm_ids = [str(gm_id) for gm_id in self._settings.get('bot_admins', [])]
        if author_id_str not in gm_ids:
            await send_callback("Access Denied: This command is for GMs only.")
            return

        if not args:
            doc_string = self.handle_gm.__doc__.format(prefix=self._command_prefix)
            await send_callback(f"Usage: {self._command_prefix}gm <subcommand> [arguments]\nAvailable subcommands:\n"
                                f"- `save_state` - Manually triggers a save of the current guild's game state.\n"
                                f"- `create_npc <template_id> [location_id] [name] [is_temporary (true/false)]` - Creates an NPC.\n"
                                f"- `delete_npc <npc_id>` - Deletes an NPC.\n"
                                f"- `relationships inspect <entity_id>` - Inspects relationships for an entity.\n"
                                f"- `load_campaign [campaign_id]` - Loads campaign data for the current guild.\n"
                                f"- `ai_create_quest <idea|AI:template_id> [char_id]` - Asks AI to create a quest.\n"
                                f"- `ai_create_location <idea|AI:template_id>` - Asks AI to create a location.\n"
                                # Add other GM commands here as they are implemented
                               )
            return

        subcommand = args[0].lower()
        gm_args = args[1:] # Arguments for the GM subcommand

        guild_id = context.get('guild_id') # Most GM commands will be guild-specific

        if subcommand == "save_state":
            # guild_id is already fetched
            persistence_manager = context.get('persistence_manager') # Type: Optional["PersistenceManager"]

            if not guild_id: # This command must be used in a server context
                await send_callback("Error: This GM command must be used in a server channel.")
                return

            if not persistence_manager:
                await send_callback("Error: PersistenceManager is not available. Cannot save state.")
                print("CommandRouter: GM save_state failed - PersistenceManager missing from context.")
                return

            try:
                # Pass the full context as kwargs for save_game_state, as it might need other managers.
                # save_game_state expects a list of guild_ids.
                # Assuming save_game_state is async
                await persistence_manager.save_game_state(guild_ids=[guild_id], **context)
                await send_callback(f"✅ Game state saving process initiated for this guild ({guild_id}).")
                print(f"CommandRouter: GM {author_id_str} initiated save_state for guild {guild_id}.")
            except Exception as e:
                print(f"CommandRouter: Error during GM save_state for guild {guild_id}: {e}")
                traceback.print_exc()
                await send_callback(f"❌ An error occurred during game state save: {e}")


        elif subcommand == "create_npc":
            if not guild_id:
                await send_callback("Error: This GM command must be used in a server channel.")
                return
            if not gm_args:
                await send_callback(f"Usage: {self._command_prefix}gm create_npc <template_id> [location_id] [name] [is_temporary (true/false)]")
                return

            template_id = gm_args[0]
            loc_id = gm_args[1] if len(gm_args) > 1 else None
            npc_name_arg = gm_args[2] if len(gm_args) > 2 else None
            is_temp_str = gm_args[3].lower() if len(gm_args) > 3 else "false"
            is_temporary_bool = is_temp_str == "true"

            npc_manager: Optional["NpcManager"] = context.get('npc_manager')
            if not npc_manager:
                await send_callback("Error: NpcManager is not available.")
                return

            char_manager: Optional["CharacterManager"] = context.get('character_manager')
            status_manager: Optional["StatusManager"] = context.get('status_manager')

            # Pass user_id for moderation tracking
            creation_kwargs = {**context, 'user_id': author_id_str}

            # Assuming create_npc is async and returns specific result formats
            created_npc_info = await npc_manager.create_npc(
                guild_id=guild_id,
                npc_template_id=template_id,
                location_id=loc_id,
                name=npc_name_arg,
                is_temporary=is_temporary_bool,
                **creation_kwargs
            )

            if isinstance(created_npc_info, dict) and created_npc_info.get("status") == "pending_moderation":
                request_id = created_npc_info["request_id"]
                await send_callback(f"NPC data for '{template_id}' generated and submitted for moderation. Request ID: `{request_id}`. You (GM) will be notified in the Master channel.")
                # Assuming _notify_master_of_pending_content is async
                await self._notify_master_of_pending_content(request_id, guild_id, author_id_str, context)
                # Optionally apply 'awaiting_moderation' to GM's character if they have one and it's desired
                if char_manager and status_manager:
                    # Assuming get_character_by_discord_id is sync
                    gm_character = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
                    if gm_character:
                        # Assuming add_status_effect_to_entity is async
                        await status_manager.add_status_effect_to_entity(
                            target_id=gm_character.id, target_type='Character',
                            status_type='awaiting_moderation', guild_id=guild_id, duration=None,
                            source_id="gm_command_npc_creation",
                            context=context # Pass context
                        )
                        await send_callback(f"Note: Your character has been temporarily marked as 'Awaiting Moderation'. This status may restrict actions.")
            elif isinstance(created_npc_info, str): # Actual NPC ID returned (non-AI path or direct creation)
                npc_id = created_npc_info
                # Assuming get_npc is sync
                new_npc = npc_manager.get_npc(guild_id, npc_id)
                display_name = getattr(new_npc, 'name', template_id) if new_npc else template_id
                await send_callback(f"✅ NPC '{display_name}' (ID: `{npc_id}`) created successfully at location `{getattr(new_npc, 'location_id', 'N/A')}`.")
            else: # None or unexpected result
                await send_callback(f"❌ Failed to create NPC from template '{template_id}'. It might not exist, failed AI generation/validation, or an unexpected error occurred.")

        elif subcommand == "ai_create_quest":
            if not guild_id:
                await send_callback("Error: This GM command must be used in a server channel.")
                return
            if not gm_args:
                await send_callback(f"Usage: {self._command_prefix}gm ai_create_quest <quest_idea_or_ai_template_id> [triggering_character_id (optional, defaults to GM's char if exists)]")
                return

            quest_idea_or_template_id = gm_args[0]
            # Optional: allow specifying a character ID for whom the quest is generated, or default to GM's character
            # For now, let's assume it's for the GM or a general quest not tied to a specific character at generation time via command
            # The QuestManager.start_quest takes character_id, so if this is for a specific player, it should be provided.
            # If it's a general world quest template being generated, start_quest might not be the right direct call,
            # but it was modified to handle "AI:" prefix. Let's assume "AI:new_world_quest" could be a template_id.
            # For player-initiated quest generation, the player's char_id would be used.
            # For GM, if they want to assign to someone, they'd pass char_id. If not, how to handle?
            # Let's assume for now, if GM uses this, the quest is generated and the GM is notified.
            # The actual assignment to a character might be a separate step or if quest_manager.start_quest implies it needs a character.
            # The current `start_quest` requires a `character_id`.

            triggering_char_id_arg = gm_args[1] if len(gm_args) > 1 else None
            char_manager: Optional["CharacterManager"] = context.get('character_manager')
            status_manager: Optional["StatusManager"] = context.get('status_manager')
            quest_manager: Optional["QuestManager"] = context.get('quest_manager')

            if not quest_manager:
                await send_callback("Error: QuestManager is not available.")
                return
            if not char_manager: # Needed to resolve triggering_char_id_arg or GM's char
                await send_callback("Error: CharacterManager is not available.")
                return

            final_triggering_char_id = None
            if triggering_char_id_arg:
                # Assuming get_character is sync and takes ID
                char_to_assign = char_manager.get_character(guild_id, triggering_char_id_arg)
                if not char_to_assign:
                    await send_callback(f"Error: Specified character ID '{triggering_char_id_arg}' not found.")
                    return
                final_triggering_char_id = char_to_assign.id
            else: # Default to GM's character if one exists
                # Assuming get_character_by_discord_id is sync
                gm_character = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
                if gm_character:
                    final_triggering_char_id = gm_character.id

            if not final_triggering_char_id:
                await send_callback("Error: A triggering character ID is required to start/generate a quest, and neither a specific one was provided nor could the GM's character be found.")
                return

            creation_kwargs = {**context, 'user_id': author_id_str}

            # start_quest expects character_id, quest_template_id, guild_id, **kwargs
            # We use quest_idea_or_template_id as the quest_template_id for start_quest
            # If it starts with "AI:", QuestManager will treat it as an AI generation request.
            # Assuming start_quest is async
            quest_info = await quest_manager.start_quest(
                guild_id=guild_id,
                character_id=final_triggering_char_id,
                quest_template_id=quest_idea_or_template_id,
                **creation_kwargs
            )

            if isinstance(quest_info, dict):
                if quest_info.get("status") == "pending_moderation":
                    request_id = quest_info["request_id"]
                    await send_callback(f"Quest data for '{quest_idea_or_template_id}' generated for character '{final_triggering_char_id}' and submitted for moderation. Request ID: `{request_id}`.")
                    # Assuming _notify_master_of_pending_content is async
                    await self._notify_master_of_pending_content(request_id, guild_id, author_id_str, context)
                    if status_manager and char_manager: # Apply to GM's char if they are the requester
                        # Assuming get_character_by_discord_id is sync
                        gm_character = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
                        if gm_character:
                            # Assuming add_status_effect_to_entity is async
                            await status_manager.add_status_effect_to_entity(
                                target_id=gm_character.id, target_type='Character',
                                status_type='awaiting_moderation', guild_id=guild_id, duration=None,
                                source_id="gm_command_quest_creation",
                                context=context # Pass context
                            )
                            await send_callback(f"Note: Your (GM) character has been temporarily marked as 'Awaiting Moderation'.")
                elif 'id' in quest_info : # Quest started directly (non-AI path from template or pre-approved)
                    # Assuming quest_info dict has name_i18n
                    quest_name = quest_info.get('name_i18n',{}).get('en', quest_info['id'])
                    await send_callback(f"✅ Quest '{quest_name}' started directly for character '{final_triggering_char_id}'.")
                else: # Unexpected dict format
                     await send_callback(f"❌ Failed to start or generate quest '{quest_idea_or_template_id}'. An unexpected result format was received.")
                     print(f"CommandRouter: Unexpected start_quest result for {quest_idea_or_template_id}: {quest_info}")

            elif quest_info is False: # Specific failure logic from QuestManager
                 await send_callback(f"❌ Failed to start or generate quest '{quest_idea_or_template_id}'. It might not exist or character doesn't meet requirements.")
            else: # None or other unexpected
                 await send_callback(f"❌ Failed to start or generate quest '{quest_idea_or_template_id}'. It might have failed AI generation, validation, or an unexpected error occurred.")
                 print(f"CommandRouter: Unhandled start_quest result for {quest_idea_or_template_id}: {quest_info}")


        elif subcommand == "ai_create_location":
            if not guild_id:
                await send_callback("Error: This GM command must be used in a server channel.")
                return
            if not gm_args:
                await send_callback(f"Usage: {self._command_prefix}gm ai_create_location <location_idea_or_ai_template_id>")
                return

            location_idea_or_template_id = gm_args[0]
            # For simplicity, explicit overrides like initial_state, name, etc., for AI generated locations are not handled here.
            # The AI should generate these. If these need to be forced, the moderation "edit" step is more appropriate.

            location_manager: Optional["LocationManager"] = context.get('location_manager')
            char_manager: Optional["CharacterManager"] = context.get('character_manager')
            status_manager: Optional["StatusManager"] = context.get('status_manager')

            if not location_manager:
                await send_callback("Error: LocationManager is not available.")
                return

            creation_kwargs = {**context, 'user_id': author_id_str}

            # create_location_instance expects template_id as the main identifier
            # If it starts with "AI:", LocationManager will treat it as AI generation.
            # Assuming create_location_instance is async and returns specific result formats
            location_info = await location_manager.create_location_instance(
                guild_id=guild_id,
                template_id=location_idea_or_template_id,
                # Optional params like initial_state, instance_name etc. are not passed here for AI path
                # as AI is expected to generate them. They are used for template-based creation.
                **creation_kwargs
            )

            if isinstance(location_info, dict):
                if location_info.get("status") == "pending_moderation":
                    request_id = location_info["request_id"]
                    await send_callback(f"Location data for '{location_idea_or_template_id}' generated and submitted for moderation. Request ID: `{request_id}`.")
                    # Assuming _notify_master_of_pending_content is async
                    await self._notify_master_of_pending_content(request_id, guild_id, author_id_str, context)
                    if status_manager and char_manager: # Apply to GM's char if they are the requester
                        # Assuming get_character_by_discord_id is sync
                        gm_character = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
                        if gm_character:
                            # Assuming add_status_effect_to_entity is async
                            await status_manager.add_status_effect_to_entity(
                                target_id=gm_character.id, target_type='Character',
                                status_type='awaiting_moderation', guild_id=guild_id, duration=None,
                                source_id="gm_command_location_creation",
                                context=context # Pass context
                            )
                            await send_callback(f"Note: Your (GM) character has been temporarily marked as 'Awaiting Moderation'.")
                elif 'id' in location_info: # Location instance created directly (non-AI or pre-approved)
                    # Assuming location_info dict has name_i18n
                    loc_name = location_info.get('name_i18n',{}).get('en', location_info['id'])
                    await send_callback(f"✅ Location '{loc_name}' (ID: {location_info['id']}) created successfully.")
                else: # Unexpected dict format
                     await send_callback(f"❌ Failed to create or generate location '{location_idea_or_template_id}'. An unexpected result format was received.")
                     print(f"CommandRouter: Unexpected create_location_instance result for {location_idea_or_template_id}: {location_info}")

            elif location_info is False: # Specific failure logic from LocationManager
                 await send_callback(f"❌ Failed to create or generate location '{location_idea_or_template_id}'. It might not exist or generation failed.")
            else: # None or other unexpected
                 await send_callback(f"❌ Failed to create or generate location '{location_idea_or_template_id}'. It might have failed AI generation, validation, or an unexpected error occurred.")
                 print(f"CommandRouter: Unhandled create_location_instance result for {location_idea_or_template_id}: {location_info}")


        elif subcommand == "delete_npc":
            if not guild_id:
                await send_callback("Error: This GM command must be used in a server channel.")
                return
            if not gm_args:
                await send_callback(f"Usage: {self._command_prefix}gm delete_npc <npc_id>")
                return

            npc_id_to_delete = gm_args[0]
            npc_manager = context.get('npc_manager')
            if not npc_manager:
                await send_callback("Error: NpcManager is not available.")
                return

            # Assuming remove_npc is async
            removed_id = await npc_manager.remove_npc(guild_id, npc_id_to_delete, **context)
            if removed_id:
                await send_callback(f"✅ NPC `{removed_id}` has been removed.")
            else:
                await send_callback(f"❌ Failed to remove NPC `{npc_id_to_delete}`. It might not exist or an error occurred.")

        elif subcommand == "relationships" or subcommand == "rel":
            if not gm_args:
                await send_callback(f"Usage: {self._command_prefix}gm {subcommand} inspect <entity_id>")
                return

            operation = gm_args[0].lower()
            if operation == "inspect":
                if len(gm_args) < 2:
                    await send_callback(f"Usage: {self._command_prefix}gm {subcommand} inspect <entity_id>")
                    return
                entity_id_to_inspect = gm_args[1]

                relationship_manager = context.get('relationship_manager')
                if not relationship_manager:
                    await send_callback("Error: RelationshipManager is not available.")
                    return

                if not guild_id:
                    await send_callback("Error: This command must be used in a server context.")
                    return

                try:
                    # Attempt to get entity name for better message (Assuming get_character and get_npc are sync)
                    entity_name = entity_id_to_inspect
                    char_mgr = context.get('character_manager')
                    npc_mgr = context.get('npc_manager')
                    # Check if it's a character
                    char_obj = char_mgr.get_character(guild_id, entity_id_to_inspect) if char_mgr else None
                    if char_obj:
                        entity_name = getattr(char_obj, 'name', entity_id_to_inspect)
                    else: # If not a character, check if it's an NPC
                        npc_obj = npc_mgr.get_npc(guild_id, entity_id_to_inspect) if npc_mgr else None
                        if npc_obj:
                            entity_name = getattr(npc_obj, 'name', entity_id_to_inspect)

                    # Assuming get_relationships_for_entity is async and returns list of dicts
                    relations = await relationship_manager.get_relationships_for_entity(guild_id, entity_id_to_inspect, context=context)

                    if relations:
                        response = f"**Relationships for {entity_name} (`{entity_id_to_inspect}`):**\n"
                        for rel in relations:
                            target_id_val = rel.get('target_id', 'Unknown Target')
                            # Attempt to get target name for better display (Assuming get_character and get_npc are sync)
                            target_name_str = target_id_val
                            if char_mgr and char_mgr.get_character(guild_id, target_id_val):
                                target_name_str = getattr(char_mgr.get_character(guild_id, target_id_val), 'name', target_id_val)
                            elif npc_mgr and npc_mgr.get_npc(guild_id, target_id_val):
                                target_name_str = getattr(npc_mgr.get_npc(guild_id, target_id_val), 'name', target_id_val)

                            rel_type = rel.get('type', 'unknown')
                            strength = rel.get('strength', 0.0)
                            response += f"- With **{target_name_str}** (`{target_id_val}`): Type: `{rel_type}`, Strength: `{strength:.1f}`\n"

                        # Discord message length limit is 2000 characters
                        if len(response) > 1950:
                            response = response[:1950] + "\n... (message truncated due to length)"
                        await send_callback(response)
                    else:
                        await send_callback(f"No specific relationships found for {entity_name} (`{entity_id_to_inspect}`).")
                except Exception as e:
                    print(f"CommandRouter: Error during GM relationships inspect for {entity_id_to_inspect}: {e}")
                    traceback.print_exc()
                    await send_callback(f"❌ An error occurred: {e}")
            else:
                await send_callback(f"Unknown operation for relationships: '{operation}'. Try 'inspect'.")

        elif subcommand == "load_campaign":
            if not guild_id: # Requires a guild context for campaign loading
                await send_callback("Error: Campaign loading is guild-specific and must be run in a server channel.")
                return

            campaign_identifier = gm_args[0] if gm_args else None # Optional: specific campaign file/ID

            persistence_manager = context.get('persistence_manager')
            if not persistence_manager:
                await send_callback("Error: PersistenceManager is not available. Cannot load campaign.")
                return

            try:
                # This method name is a placeholder for what will be implemented in PersistenceManager (Task V.2)
                # Assuming trigger_campaign_load_and_distribution is async
                if hasattr(persistence_manager, 'trigger_campaign_load_and_distribution'):
                    await send_callback(f"Initiating campaign load for '{campaign_identifier or 'default'}' in guild {guild_id}...")
                    # The actual heavy lifting is in Task V.2. This is just the command hook.
                    # The context here includes all managers for distribution by PersistenceManager.
                    await persistence_manager.trigger_campaign_load_and_distribution(guild_id, campaign_identifier, **context)
                    await send_callback(f"✅ Campaign data for '{campaign_identifier or 'default'}' processed for guild {guild_id}.")
                else:
                    await send_callback("Error: Campaign loading functionality is not fully implemented in PersistenceManager yet.")
                    print(f"CommandRouter: GM load_campaign: PersistenceManager missing 'trigger_campaign_load_and_distribution'.")

            except Exception as e:
                print(f"CommandRouter: Error during GM load_campaign for guild {guild_id}: {e}")
                traceback.print_exc()
                await send_callback(f"❌ An error occurred during campaign load: {e}")

        else:
            await send_callback(f"Unknown GM subcommand: '{subcommand}'. Use `{self._command_prefix}gm` for help.")

    @command("party_submit_actions_placeholder")
    async def handle_party_submit_actions_placeholder(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        Placeholder for submitting party actions. Usage: {prefix}party_submit_actions_placeholder <party_id> <char1_id> '<actions_json1>' [<char2_id> '<actions_json2>'...]
        Example: {prefix}party_submit_actions_placeholder party_xyz char1_id '[{{\"intent\":\"move\",\"entities\":{{\"target_space\":\"A2\"}}}}]' char2_id '[{{\"intent\":\"look\",\"entities\":{{}}}}]'
        Note: JSON strings need escaping in Discord commands.
        """
        send_callback = context['send_to_command_channel']
        guild_id = context.get('guild_id')

        if not guild_id:
            await send_callback("This command must be used in a server.")
            return

        if len(args) < 3 or len(args) % 2 == 0: # Needs party_id and at least one pair of (char_id, actions_json)
            await send_callback(f"Usage: {self._command_prefix}party_submit_actions_placeholder <party_id> <char1_id> '<actions_json1>' [<char2_id> '<actions_json2>'...]")
            return

        party_id_arg = args[0]
        party_actions_data: List[Tuple[str, str]] = []

        for i in range(1, len(args), 2):
            char_id = args[i]
            actions_json_string = args[i+1]
            party_actions_data.append((char_id, actions_json_string))

        # Retrieve necessary managers from context
        char_manager = context.get('character_manager')
        loc_manager = context.get('location_manager')
        event_manager = context.get('event_manager')
        rule_engine = context.get('rule_engine')
        openai_service = context.get('openai_service')
        game_log_manager = context.get('game_log_manager') # Get game_log_manager from context

        # The conflict_resolver is already part of self from __init__
        conflict_resolver_instance = self._conflict_resolver


        if not all([char_manager, loc_manager, event_manager, rule_engine]): # openai_service and conflict_resolver are optional dependencies for the *processor*
            await send_callback("Error: One or more required managers (Character, Location, Event, RuleEngine) are not available.")
            return

        # Import ActionProcessor here or at top of file if preferred
        # from bot.game.action_processor import ActionProcessor # Moved to top-level

        # Instantiate ActionProcessor. It does NOT take conflict_resolver in its __init__ based on previous task.
        action_processor_instance = ActionProcessor() # Corrected instantiation

        # Mock GameState for now
        # from bot.game.models.game_state import GameState # Moved to TYPE_CHECKING

        # Need actual game state object, not a mock. Assuming CommandRouter needs GameState passed somehow,
        # or it can retrieve it via PersistenceManager or GameManager.
        # For this placeholder, we'll use a simple mock based on guild_id as provided.
        # In a real system, you'd retrieve the actual game_state for the guild.
        mock_game_state = context.get('game_state') # Try to get from context
        if not mock_game_state:
            # If not in context, create a basic one (may lack data the processor expects)
             print(f"CommandRouter: Warning - GameState not found in context for party_submit. Creating mock GameState for guild {guild_id}.")
             from bot.game.models.game_state import GameState # Need runtime import if used here
             mock_game_state = GameState(guild_id=guild_id)


        try:
            # Assuming process_party_actions is async and returns dict
            result = await action_processor_instance.process_party_actions(
                game_state=mock_game_state, # Pass the game_state object (mock or real)
                char_manager=char_manager,
                loc_manager=loc_manager,
                event_manager=event_manager,
                rule_engine=rule_engine,
                openai_service=openai_service, # Pass optional service
                party_actions_data=party_actions_data,
                ctx_channel_id_fallback=message.channel.id,
                conflict_resolver=conflict_resolver_instance, # Pass the resolver instance
                game_log_manager=game_log_manager # Pass game_log_manager
            )

            response_message = f"Party actions submitted for party '{party_id_arg}'. Result:\n"
            response_message += f"Success: {result.get('success')}\n"
            response_message += f"Message: {result.get('message', 'N/A')}\n"
            if 'identified_conflicts' in result:
                response_message += f"Identified Conflicts: {len(result['identified_conflicts'])}\n"
                # Format conflicts nicely
                for idx, conflict in enumerate(result['identified_conflicts'][:5]): # Limit conflict list output
                    involved_players_str = ", ".join(conflict.get('involved_players', []))
                    response_message += f"  Conflict {idx+1}: Type: `{conflict.get('type', 'unknown')}`, Players: `{involved_players_str}`\n"
                if len(result['identified_conflicts']) > 5:
                    response_message += f"  ... and {len(result['identified_conflicts']) - 5} more conflicts.\n"

            if result.get('overall_state_changed'):
                response_message += "Overall game state changed.\n"

            # For individual results (if not using conflict resolver path)
            # if result.get('individual_action_results'):
            #     response_message += f"Individual Action Results: {len(result['individual_action_results'])}\n"
            #     # Example: Add snippets of individual results
            #     for ind_res in result['individual_action_results'][:5]:
            #         char_id = ind_res.get('character_id', 'N/A')
            #         action_text = ind_res.get('action_original_text', 'N/A')
            #         ind_success = ind_res.get('success', False)
            #         ind_msg = ind_res.get('message', 'No message').split('\n')[0] # Take first line
            #         response_message += f"  - Char `{char_id}` ({action_text}) Success: {ind_success}, Msg: \"{ind_msg}\"\n"


            await send_callback(response_message[:1990]) # Trim if too long

        except Exception as e:
            print(f"CommandRouter: Error in handle_party_submit_actions_placeholder: {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while processing party actions: {e}")


    @command("resolve_conflict")
    async def handle_resolve_conflict(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows a Master to manually resolve a pending conflict. Usage: {prefix}resolve_conflict <conflict_id> <outcome_type> [<params_json>]"""
        send_callback = context['send_to_command_channel']
        author_id_str = str(message.author.id)

        # GM Access Control (or specific conflict resolution permission)
        gm_ids = [str(gm_id) for gm_id in self._settings.get('bot_admins', [])]
        if author_id_str not in gm_ids:
            await send_callback("Access Denied: This command is for GMs/Masters only.")
            return

        if len(args) < 2:
            await send_callback(f"Usage: {self._command_prefix}resolve_conflict <conflict_id> <outcome_type> [<params_json>]")
            return

        conflict_id_arg = args[0]
        outcome_type_arg = args[1]
        params_json_arg = " ".join(args[2:]) if len(args) > 2 else None # Join remaining args for JSON
        parsed_params: Optional[Dict[str, Any]] = None

        if params_json_arg:
            try:
                # import json # json is already imported at the top level of the module
                parsed_params = json.loads(params_json_arg)
                if not isinstance(parsed_params, dict):
                    await send_callback("Error: params_json must be a valid JSON object (dictionary).")
                    return
            except json.JSONDecodeError as e:
                await send_callback(f"Error parsing params_json: {e}")
                return

        # Retrieve ConflictResolver from context (passed from GameManager to CommandRouter.__init__)
        conflict_resolver_instance: Optional["ConflictResolver"] = self._conflict_resolver # Relies on it being stored in __init__

        if not conflict_resolver_instance:
            await send_callback("Error: ConflictResolver service is not available.")
            print("CommandRouter: Error in handle_resolve_conflict - ConflictResolver not found in self._conflict_resolver.")
            return

        try:
            # Assuming process_master_resolution is sync (often conflict resolution is a GM action, might not need await)
            # Or it could be async if it updates DB or triggers other async events.
            # Let's assume it's synchronous for now based on the original code snippet's pattern.
            # If it needs to be async, add await here.
            resolution_result = conflict_resolver_instance.process_master_resolution(
                conflict_id=conflict_id_arg,
                outcome_type=outcome_type_arg,
                params=parsed_params
            )

            # resolution_result is expected to be a dict
            if not isinstance(resolution_result, dict):
                 await send_callback(f"An error occurred while resolving conflict '{conflict_id_arg}'. Invalid result from ConflictResolver.")
                 print(f"CommandRouter: ConflictResolver.process_master_resolution returned unexpected type: {type(resolution_result)}")
                 return


            response_msg = resolution_result.get("message", "Conflict resolution processed.")
            if resolution_result.get("success"):
                await send_callback(f"✅ {response_msg}")
                # Potentially log resolution_details or trigger further game events based on them
                print(f"Conflict {conflict_id_arg} resolved. Details: {resolution_result.get('resolution_details')}")
                # TODO: Notify involved players about the resolution outcome. This might be done by ConflictResolver itself.
            else:
                await send_callback(f"❌ {response_msg}")

        except Exception as e:
            print(f"CommandRouter: Error in handle_resolve_conflict for ID '{conflict_id_arg}': {e}")
            traceback.print_exc()
            await send_callback(f"An unexpected error occurred while resolving conflict: {e}")

    async def _notify_master_of_pending_content(self, request_id: str, guild_id: str, user_id: str, context: Dict[str, Any]):
        """Helper to notify Master channel about content awaiting moderation."""
        persistence_manager: Optional["PersistenceManager"] = context.get('persistence_manager')
        if not persistence_manager:
             print("CommandRouter: ERROR - PersistenceManager not in context for _notify_master_of_pending_content.")
             return # Cannot proceed without persistence

        # Assuming PersistenceManager provides a way to access the DB adapter
        if not hasattr(persistence_manager, 'get_db_adapter') or not persistence_manager.get_db_adapter():
            print("CommandRouter: ERROR - DB adapter not available via PersistenceManager for Master notification.")
            return

        db_adapter = persistence_manager.get_db_adapter() # Assuming PM provides DB adapter

        master_channel_id_str = self._settings.get('guild_specific_settings', {}).get(guild_id, {}).get('master_notification_channel_id')
        if not master_channel_id_str:
            master_channel_id_str = self._settings.get('default_master_notification_channel_id')

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
            # Assuming get_pending_moderation_request is async
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
                    # Import generate_summary from bot.utils.text_utils
                    try:
                        from bot.utils.text_utils import generate_summary
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
                f"`{self._command_prefix}approve {request_id}`\n" # Use instance prefix
                f"`{self._command_prefix}reject {request_id}`\n" # Use instance prefix
                f"`{self._command_prefix}edit {request_id} <json_data>` (use with caution, ensure valid JSON)" # Use instance prefix
            )
            await send_to_master_channel(notif_message)
            print(f"CommandRouter: Master notification sent for request {request_id} to channel {master_channel_id}.")

        except Exception as e:
            print(f"CommandRouter: ERROR - Failed to send Master notification for request {request_id}: {e}")
            traceback.print_exc()
            try:
                await send_to_master_channel(f"Critical Error: Failed to process and send notification for moderation request {request_id}. Check logs.")
            except Exception:
                pass # Avoid error loops

    async def _activate_approved_content(self, request_id: str, context: Dict[str, Any]) -> bool:
        """
        Activates content from an approved moderation request.
        Fetches request, calls relevant manager, removes status, notifies user, deletes request.
        """
        send_to_master_channel = context['send_to_command_channel'] # For feedback to the master using the command
        persistence_manager: Optional["PersistenceManager"] = context.get('persistence_manager')
        if not persistence_manager:
             print("CommandRouter:_activate_approved_content ERROR - PersistenceManager not in context.")
             await send_to_master_channel(f"Error: PersistenceManager unavailable during content activation for {request_id}.")
             return False # Cannot proceed without persistence

        if not hasattr(persistence_manager, 'get_db_adapter') or not persistence_manager.get_db_adapter():
            print("CommandRouter:_activate_approved_content ERROR - DB adapter not available.")
            await send_to_master_channel(f"Error: DB adapter unavailable during content activation for {request_id}.")
            return False

        db_adapter = persistence_manager.get_db_adapter()

        # Assuming get_pending_moderation_request is async
        moderation_request = await db_adapter.get_pending_moderation_request(request_id)
        if not moderation_request:
            print(f"CommandRouter:_activate_approved_content ERROR - Request {request_id} not found in DB for activation.")
            await send_to_master_channel(f"Error: Request {request_id} not found for activation.")
            return False

        original_user_id = moderation_request.get("user_id") # This is Discord User ID (string)
        guild_id = moderation_request.get("guild_id")
        content_type = moderation_request.get("content_type")
        data_json_str = moderation_request.get("data") # The JSON string from DB

        if not original_user_id or not guild_id or not content_type or not data_json_str:
             await send_to_master_channel(f"Error: Malformed moderation request data for {request_id}.")
             print(f"CommandRouter:_activate_approved_content ERROR - Malformed request data for {request_id}: {moderation_request}")
             return False


        try:
            approved_data = json.loads(data_json_str) # Load the JSON string into a dict
        except json.JSONDecodeError:
            await send_to_master_channel(f"Error: Invalid JSON data in moderation request {request_id}. Cannot activate.")
            print(f"CommandRouter:_activate_approved_content ERROR - Invalid JSON data in request {request_id}: {data_json_str[:100]}...")
            return False


        npc_manager: Optional["NpcManager"] = context.get('npc_manager')
        quest_manager: Optional["QuestManager"] = context.get('quest_manager')
        location_manager: Optional["LocationManager"] = context.get('location_manager')
        character_manager: Optional["CharacterManager"] = context.get('character_manager')
        status_manager: Optional["StatusManager"] = context.get('status_manager')

        entity_id_or_data: Any = None # Variable to hold the result from the manager's activation method
        activation_successful = False
        entity_info_for_user_notification = "N/A"

        try:
            if content_type == 'npc':
                if npc_manager:
                    # Assuming create_npc_from_moderated_data is async
                    entity_id_or_data = await npc_manager.create_npc_from_moderated_data(guild_id, approved_data, context)
                    if entity_id_or_data: # Should return the created NPC ID (string)
                        # Assuming get_npc is sync
                        npc_obj = npc_manager.get_npc(guild_id, entity_id_or_data)
                        entity_info_for_user_notification = f"NPC '{getattr(npc_obj, 'name', entity_id_or_data)}' (ID: {entity_id_or_data})"
                        activation_successful = True # Mark successful if ID is returned
                else: await send_to_master_channel("Error: NpcManager not available for NPC activation.")

            elif content_type == 'quest':
                if quest_manager and character_manager:
                    # Assuming get_character_by_discord_id is sync
                    player_char = character_manager.get_character_by_discord_id(guild_id, int(original_user_id))
                    if not player_char:
                        await send_to_master_channel(f"Error: Original user {original_user_id} does not have an active character in guild {guild_id} to assign the quest to. Quest {request_id} cannot be activated.")
                        # Optionally update moderation request status to 'activation_failed'
                        await db_adapter.update_pending_moderation_request(request_id, 'activation_failed_no_char', context.get('author_id', 'System')) # Assuming author_id is GM's ID
                        return False

                    # Pass the resolved character_id to start_quest_from_moderated_data
                    # Assuming start_quest_from_moderated_data is async and returns a dict
                    entity_id_or_data = await quest_manager.start_quest_from_moderated_data(guild_id, player_char.id, approved_data, context)
                    if entity_id_or_data and isinstance(entity_id_or_data, dict) and 'id' in entity_id_or_data:
                         # Assuming the dict has name_i18n
                         quest_name = entity_id_or_data.get('name_i18n',{}).get('en', entity_id_or_data.get('id'))
                         entity_info_for_user_notification = f"Quest '{quest_name}' (ID: {entity_id_or_data.get('id')}) for character {player_char.name}"
                         activation_successful = True # Mark successful if dict with ID is returned
                else: await send_to_master_channel("Error: QuestManager or CharacterManager not available for Quest activation.")

            elif content_type == 'location':
                if location_manager:
                    # create_location_instance_from_moderated_data takes user_id (Discord ID) for the generated_locations table
                    # Assuming create_location_instance_from_moderated_data is async and returns a dict
                    entity_id_or_data = await location_manager.create_location_instance_from_moderated_data(guild_id, approved_data, original_user_id, context)
                    if entity_id_or_data and isinstance(entity_id_or_data, dict) and 'id' in entity_id_or_data:
                        # Assuming the dict has name_i18n
                        loc_name = entity_id_or_data.get('name_i18n',{}).get('en', entity_id_or_data.get('id'))
                        entity_info_for_user_notification = f"Location '{loc_name}' (ID: {entity_id_or_data.get('id')})"
                        activation_successful = True # Mark successful if dict with ID is returned
                else: await send_to_master_channel("Error: LocationManager not available for Location activation.")

            # Add other content types here (e.g., item_template, encounter, etc.)

        except Exception as e_activate:
            print(f"CommandRouter:_activate_approved_content ERROR activating content for request {request_id}: {e_activate}")
            traceback.print_exc()
            await send_to_master_channel(f"❌ Critical error during content activation for request {request_id}: {e_activate}. Content remains in moderation queue with status '{moderation_request.get('status', 'unknown')}'.")
            # Update status to reflect activation failure if not already done by manager
            await db_adapter.update_pending_moderation_request(request_id, 'activation_failed', context.get('author_id', 'System'))
            return False # Do not proceed to delete moderation request or notify user of success

        if activation_successful:
            print(f"CommandRouter: Content from request {request_id} (Type: {content_type}) successfully activated.")

            # Remove 'awaiting_moderation' status from the user's character
            if character_manager and status_manager:
                # Assuming get_character_by_discord_id is sync
                player_char_to_update = character_manager.get_character_by_discord_id(guild_id, int(original_user_id))
                if player_char_to_update:
                    # Assuming remove_status_effects_by_type is async
                    removed_count = await status_manager.remove_status_effects_by_type(
                        player_char_to_update.id, 'Character', 'awaiting_moderation', guild_id, context
                    )
                    print(f"CommandRouter: Removed {removed_count} 'awaiting_moderation' statuses from character {player_char_to_update.id} (User: {original_user_id}).")
                    # Notify user of approval and status removal (placeholder)
                    print(f"PLACEHOLDER: Notify user {original_user_id} that content '{entity_info_for_user_notification}' was approved and 'awaiting_moderation' status removed.")
                    # Example actual notification (would require user object or DM channel):
                    # try:
                    #     # Assuming self._client is available (e.g. passed in __init__ or context)
                    #     user_discord_obj = await self._client.fetch_user(int(original_user_id))
                    #     if user_discord_obj:
                    #         await user_discord_obj.send(f"🎉 Your content submission '{entity_info_for_user_notification}' (Request ID: {request_id}) has been approved and is now active! Your 'Awaiting Moderation' status has been lifted.")
                    # except Exception as e_notify:
                    #     print(f"CommandRouter: Failed to send DM notification to user {original_user_id}: {e_notify}")
                else:
                    print(f"CommandRouter: WARNING - Could not find character for user {original_user_id} in guild {guild_id} to remove 'awaiting_moderation' status.")
            else:
                print("CommandRouter: WARNING - CharacterManager or StatusManager not available for status removal.")

            # Delete the moderation request after successful activation
            # Assuming delete_pending_moderation_request is async
            await db_adapter.delete_pending_moderation_request(request_id)
            print(f"CommandRouter: Moderation request {request_id} deleted after successful activation.")
            return True
        else:
            # Activation failed *within* the manager method, but no exception was raised.
            # The manager should have handled messaging the master channel about its specific failure.
            # This branch is mostly a safety net.
            await send_to_master_channel(f"⚠️ Activation failed for content type '{content_type}' from request {request_id}. Check logs. Content remains in moderation queue with status '{moderation_request.get('status', 'unknown')}'.")
            print(f"CommandRouter:_activate_approved_content - Activation failed for {content_type} from request {request_id}. Entity data was None or manager returned unexpected result.")
            # Consider updating status to 'activation_failed' if manager didn't do it
            await db_adapter.update_pending_moderation_request(request_id, 'activation_failed', context.get('author_id', 'System'))
            return False


    @command("approve")
    async def handle_approve_content(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Approves AI-generated content that is pending moderation. Usage: {prefix}approve <request_id>"""
        send_callback = context['send_to_command_channel']
        author_id_str = str(message.author.id)
        guild_id = context.get('guild_id') # Guild context of the command

        # GM Access Control
        gm_ids = [str(gm_id) for gm_id in self._settings.get('bot_admins', [])]
        if author_id_str not in gm_ids:
            await send_callback("Access Denied: This command is for Masters only.")
            return

        if not guild_id:
            await send_callback("Error: This command should be used in a server channel.")
            return

        if not args:
            await send_callback(f"Usage: {self._command_prefix}approve <request_id>")
            return

        request_id = args[0]
        persistence_manager: Optional["PersistenceManager"] = context.get('persistence_manager')

        if not persistence_manager:
            await send_callback("Error: Database service is unavailable.")
            print("CommandRouter: ERROR - PersistenceManager not in context for handle_approve_content.")
            return

        if not hasattr(persistence_manager, 'get_db_adapter') or not persistence_manager.get_db_adapter():
            await send_callback("Error: Database service is unavailable.")
            print("CommandRouter: ERROR - DB adapter not available for handle_approve_content.")
            return
        db_adapter = persistence_manager.get_db_adapter()


        try:
            # Assuming get_pending_moderation_request is async
            moderation_request = await db_adapter.get_pending_moderation_request(request_id)

            if not moderation_request:
                await send_callback(f"Error: Moderation request ID `{request_id}` not found.")
                return

            # request_guild_id = moderation_request.get("guild_id") # Guild ID from the request itself (useful if command isn't in request's guild)

            if moderation_request.get("status") != 'pending': # Use .get for safety
                await send_callback(f"Error: Request `{request_id}` is already actioned (status: {moderation_request.get('status', 'unknown')}).")
                return

            # Update status to 'approved'
            # Assuming update_pending_moderation_request is async
            update_success = await db_adapter.update_pending_moderation_request(
                request_id,
                status='approved',
                moderator_id=author_id_str
            )

            if update_success:
                await send_callback(f"✅ Request `{request_id}` status updated to 'approved'. Attempting content activation...")
                # Activation needs the guild_id from the request itself, not the command context guild_id
                request_guild_id = moderation_request.get("guild_id")
                if not request_guild_id:
                    await send_callback(f"Error: Request `{request_id}` is missing guild ID data. Cannot activate.")
                    # Update status to indicate activation failed due to missing data
                    await db_adapter.update_pending_moderation_request(request_id, 'activation_failed_no_guild', author_id_str)
                    return

                # Pass the full context to activation, it contains all managers
                activation_success = await self._activate_approved_content(request_id, context)
                if activation_success:
                    await send_callback(f"🚀 Content from request `{request_id}` successfully activated and request removed.")
                else:
                    # _activate_approved_content should have already updated status and sent a message
                    await send_callback(f"⚠️ Request `{request_id}` was marked 'approved', but content activation failed. Check logs for details.") # Avoid duplicate "check logs" if _activate already said it
            else:
                await send_callback(f"Error: Failed to update status for request `{request_id}` in the database.")

        except Exception as e:
            print(f"CommandRouter: Error in handle_approve_content for ID '{request_id}': {e}")
            traceback.print_exc()
            await send_callback(f"An unexpected error occurred while approving content: {e}")


    @command("reject")
    async def handle_reject_content(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Rejects AI-generated content that is pending moderation. Usage: {prefix}reject <request_id> [reason...]"""
        send_callback = context['send_to_command_channel']
        author_id_str = str(message.author.id)
        guild_id = context.get('guild_id')

        # GM Access Control
        gm_ids = [str(gm_id) for gm_id in self._settings.get('bot_admins', [])]
        if author_id_str not in gm_ids:
            await send_callback("Access Denied: This command is for Masters only.")
            return

        if not guild_id:
            await send_callback("Error: This command should be used in a server channel.")
            return

        if not args:
            await send_callback(f"Usage: {self._command_prefix}reject <request_id> [reason...]")
            return

        request_id = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else "No reason provided."

        persistence_manager: Optional["PersistenceManager"] = context.get('persistence_manager')

        if not persistence_manager:
            await send_callback("Error: Database service is unavailable.")
            print("CommandRouter: ERROR - PersistenceManager not in context for handle_reject_content.")
            return

        if not hasattr(persistence_manager, 'get_db_adapter') or not persistence_manager.get_db_adapter():
            await send_callback("Error: Database service is unavailable.")
            print("CommandRouter: ERROR - DB adapter not available for handle_reject_content.")
            return
        db_adapter = persistence_manager.get_db_adapter()


        try:
            # Assuming get_pending_moderation_request is async
            moderation_request = await db_adapter.get_pending_moderation_request(request_id)

            if not moderation_request:
                await send_callback(f"Error: Moderation request ID `{request_id}` not found.")
                return

            if moderation_request.get("status") != 'pending': # Use .get for safety
                await send_callback(f"Error: Request `{request_id}` is already actioned (status: {moderation_request.get('status', 'unknown')}).")
                return

            original_user_id = moderation_request.get("user_id")
            request_guild_id = moderation_request.get("guild_id")
            content_type = moderation_request.get("content_type")

            # Update status to 'rejected' instead of deleting immediately (better for tracking)
            # Assuming update_pending_moderation_request is async
            update_success = await db_adapter.update_pending_moderation_request(
                 request_id,
                 status='rejected',
                 moderator_id=author_id_str,
                 moderator_notes=reason # Store the rejection reason
             )

            if update_success:
                await send_callback(f"🗑️ Content request `{request_id}` rejected.")
                print(f"MASTER ACTION: Request {request_id} (User: {original_user_id}, Type: {content_type}) rejected by Master {author_id_str}. Reason: {reason}")

                # Actual removal of status and notification to user
                character_manager: Optional["CharacterManager"] = context.get('character_manager')
                status_manager: Optional["StatusManager"] = context.get('status_manager')
                if character_manager and status_manager and original_user_id and request_guild_id:
                    try:
                        # Assuming get_character_by_discord_id is sync
                        player_char_to_update = character_manager.get_character_by_discord_id(request_guild_id, int(original_user_id))
                        if player_char_to_update:
                             # Assuming remove_status_effects_by_type is async
                            removed_count = await status_manager.remove_status_effects_by_type(
                                player_char_to_update.id, 'Character', 'awaiting_moderation', request_guild_id, context
                            )
                            print(f"CommandRouter: Removed {removed_count} 'awaiting_moderation' statuses from character {player_char_to_update.id} (User: {original_user_id}) due to rejection.")
                            # Notify user of rejection (placeholder)
                            print(f"PLACEHOLDER: Notify user {original_user_id} that content request {request_id} was rejected. Reason: {reason}")
                            # Example actual notification:
                            # try:
                            #     # Assuming self._client is available
                            #     user_discord_obj = await self._client.fetch_user(int(original_user_id))
                            #     if user_discord_obj:
                            #         await user_discord_obj.send(f"😢 Your content submission (Request ID: {request_id}, Type: {content_type}) was rejected by a Master. Reason: {reason}. Your 'Awaiting Moderation' status has been lifted.")
                            # except Exception as e_notify:
                            #     print(f"CommandRouter: Failed to send DM notification for rejection to user {original_user_id}: {e_notify}")
                        else:
                            print(f"CommandRouter: WARNING - Could not find character for user {original_user_id} in guild {request_guild_id} to remove 'awaiting_moderation' status after rejection.")
                    except ValueError:
                         print(f"CommandRouter: WARNING - Invalid original_user_id format in request {request_id} ({original_user_id}). Cannot remove status or notify user.")
                else:
                    print("CommandRouter: WARNING - CharacterManager or StatusManager not available for status removal after rejection.")

            else:
                await send_callback(f"Error: Failed to update status for request `{request_id}` in the database.")

        except Exception as e:
            print(f"CommandRouter: Error in handle_reject_content for ID '{request_id}': {e}")
            traceback.print_exc()
            await send_callback(f"An unexpected error occurred while rejecting content: {e}")


    @command("edit")
    async def handle_edit_content(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Edits and approves AI-generated content that is pending moderation. Usage: {prefix}edit <request_id> <json_edited_data>"""
        send_callback = context['send_to_command_channel']
        author_id_str = str(message.author.id)
        guild_id = context.get('guild_id')

        # GM Access Control
        gm_ids = [str(gm_id) for gm_id in self._settings.get('bot_admins', [])]
        if author_id_str not in gm_ids:
            await send_callback("Access Denied: This command is for Masters only.")
            return

        if not guild_id:
            await send_callback("Error: This command should be used in a server channel.")
            return

        if len(args) < 2:
            await send_callback(f"Usage: {self._command_prefix}edit <request_id> <json_edited_data>")
            return

        request_id = args[0]
        json_edited_data_str = " ".join(args[1:]) # Join all remaining args to form the JSON string

        persistence_manager: Optional["PersistenceManager"] = context.get('persistence_manager')
        ai_validator: Optional["AIResponseValidator"] = context.get('ai_validator') # Get from main context

        if not persistence_manager:
            await send_callback("Error: Database service is unavailable.")
            print("CommandRouter: ERROR - PersistenceManager not in context for handle_edit_content.")
            return

        if not hasattr(persistence_manager, 'get_db_adapter') or not persistence_manager.get_db_adapter():
            await send_callback("Error: Database service is unavailable.")
            print("CommandRouter: ERROR - DB adapter not available for handle_edit_content.")
            return
        db_adapter = persistence_manager.get_db_adapter()

        if not ai_validator:
            await send_callback("Error: AIResponseValidator service is unavailable. Cannot validate edits.")
            print("CommandRouter: ERROR - AIResponseValidator not in context for handle_edit_content.")
            return

        try:
            # Assuming get_pending_moderation_request is async
            moderation_request = await db_adapter.get_pending_moderation_request(request_id)

            if not moderation_request:
                await send_callback(f"Error: Moderation request ID `{request_id}` not found.")
                return

            if moderation_request.get("status") != 'pending': # Use .get for safety
                await send_callback(f"Error: Request `{request_id}` is already actioned (status: {moderation_request.get('status', 'unknown')}). Cannot edit.")
                return

            original_content_type = moderation_request.get("content_type")
            request_guild_id = moderation_request.get("guild_id") # Get guild ID from the request

            if not original_content_type or not request_guild_id:
                 await send_callback(f"Error: Moderation request `{request_id}` is missing content type or guild ID.")
                 print(f"CommandRouter: ERROR - Malformed request data for {request_id}: Missing type/guild.")
                 return


            try:
                edited_data_dict = json.loads(json_edited_data_str)
                if not isinstance(edited_data_dict, dict):
                    await send_callback("Error: Edited data must be a valid JSON object (dictionary).")
                    return
            except json.JSONDecodeError as e_json:
                await send_callback(f"Error parsing JSON for edited data: {e_json}. Please ensure it's valid JSON.")
                return

            # Validate the edited data
            # This assumes the validator needs existing IDs for context, which is complex.
            # For a simpler case, it might just validate structure and type consistency.
            # If it needs IDs for cross-referencing (e.g., NPC location_id must exist),
            # you'd need to fetch relevant IDs for request_guild_id here.
            # For now, providing minimal sets - adjust if validator needs real data.
            location_manager: Optional["LocationManager"] = context.get('location_manager')
            existing_location_template_ids = set()
            if location_manager and hasattr(location_manager, '_location_templates') and request_guild_id in location_manager._location_templates:
                 existing_location_template_ids = set(location_manager._location_templates[request_guild_id].keys())


            # Assuming validate_ai_response is async
            validation_result = await ai_validator.validate_ai_response(
                ai_json_string=json_edited_data_str, # Pass the string directly
                expected_structure=original_content_type, # e.g., "single_npc", "single_quest"
                # Pass existing IDs relevant to the *request's* guild, not the command's guild if different.
                # This requires managers to be able to query for a specific guild.
                # Assuming managers in context can work with the request_guild_id passed in context.
                existing_npc_ids=set(),      # Placeholder
                existing_quest_ids=set(),    # Placeholder
                existing_item_template_ids=set(), # Placeholder
                existing_location_template_ids=existing_location_template_ids # Example
                # Pass context as kwargs if validator needs managers
                # **context
            )

            if not validation_result.get('overall_status', '').startswith("success"):
                errors = validation_result.get('global_errors', [])
                # Attempt to get entity errors from the structure used in validator
                entity_errors = []
                entities_list = validation_result.get('entities', [])
                if entities_list and isinstance(entities_list, list) and len(entities_list) > 0 and isinstance(entities_list[0], dict):
                     entity_errors = entities_list[0].get('errors', [])

                all_errors = errors + entity_errors
                error_msg = "\n".join(all_errors) if all_errors else 'Unknown validation error.'

                await send_callback(f"Error: Edited data failed validation for type '{original_content_type}'. Errors:\n```\n{error_msg}\n```")
                return

            # Update status to 'approved_edited' (or similar) and save the edited data
            # Assuming update_pending_moderation_request is async
            success = await db_adapter.update_pending_moderation_request(
                request_id,
                status='approved_edited', # Use a distinct status for edited content
                moderator_id=author_id_str,
                data_json=json_edited_data_str # Save the validated, edited JSON string
            )

            if success:
                # original_user_id = moderation_request.get("user_id") # Fetched from the original request
                # request_guild_id = moderation_request.get("guild_id") # Already fetched

                await send_callback(f"✅ Request `{request_id}` status updated to 'approved_edited'. Attempting content activation with edits...")
                # Pass the full context to activation, it contains all managers
                activation_success = await self._activate_approved_content(request_id, context)
                if activation_success:
                    await send_callback(f"🚀 Content from request `{request_id}` (edited) successfully activated and request removed.")
                else:
                    # _activate_approved_content should have already updated status and sent a message
                    await send_callback(f"⚠️ Request `{request_id}` was marked 'approved_edited', but content activation failed. Check logs for details.") # Avoid duplicate "check logs" if _activate already said it
            else:
                await send_callback(f"Error: Failed to update status/data for request `{request_id}` in the database.")

        except Exception as e:
            print(f"CommandRouter: Error in handle_edit_content for ID '{request_id}': {e}")
            traceback.print_exc()
            await send_callback(f"An unexpected error occurred while editing content: {e}")

# Helper function example (can be defined in this file or a utility module)
def is_uuid_format(s: str) -> bool:
     """Проверяет, выглядит ли строка как UUID (простая проверка формата)."""
     if not isinstance(s, str):
          return False
     # Basic check for length and dashes
     if len(s) == 36 and s[8] == '-' and s[13] == '-' and s[18] == '-' and s[23] == '-':
          try:
               # Attempt to parse as UUID to confirm format
               uuid.UUID(s)
               return True
          except ValueError:
               return False # Looks like UUID but parsing failed
     return False # Does not look like a standard UUID format


# --- End of CommandRouter Class ---

print("DEBUG: command_router.py module loaded.")
