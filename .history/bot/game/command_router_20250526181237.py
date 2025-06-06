# bot/game/command_router.py

print("--- Начинается загрузка: command_router.py")

import asyncio
import traceback
import shlex # For better argument parsing (handles quotes)
import uuid # Needed for is_uuid_format example
# Import typing components
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING, ClassVar, Union # Добавляем Union для Type Hint
from collections import Counter # Added for example in Party info


# Import discord types for type hints
from discord import Message # Used in route method signature, handle_* signatures
# Import discord for Embed etc.
import discord # Direct import

# TOP-LEVEL IMPORT FOR CAMPAIGNLOADER
from bot.services.campaign_loader import CampaignLoader
# TOP-LEVEL IMPORT FOR RELATIONSHIPMANAGER
from bot.game.managers.relationship_manager import RelationshipManager
# TOP-LEVEL IMPORT FOR QUESTMANAGER
from bot.game.managers.quest_manager import QuestManager


# Import specific command handlers
# Убедитесь, что путь к PartyCommandHandler правильный
# Импорт на уровне TYPE_CHECKING
# from bot.game.command_handlers.party_handler import PartyCommandHandler # Перемещаем в TYPE_CHECKING

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
        event_stage_processor: Optional["EventStageProcessor"] = None,
        quest_manager: Optional["QuestManager"] = None, # Added QuestManager
        dialogue_manager: Optional["DialogueManager"] = None, # Added DialogueManager
        # Add other optional managers/processors needed for context
        # Add View Services needed for context (even if handled by specific handlers)
        # party_view_service: Optional["PartyViewService"] = None, # Needed for PartyCommandHandler if it gets it from context
        # location_view_service: Optional["LocationViewService"] = None, # Needed for handle_look potentially
        campaign_loader: Optional["CampaignLoader"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,

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
        self._quest_manager = quest_manager # Added QuestManager
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

        if command_keyword == "party":
             if self._party_command_handler:
                  try:
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

        handler = self.__class__._command_handlers.get(command_keyword)
        if not handler:
            await context['send_to_command_channel'](f"❓ Unknown command: `{self._command_prefix}{command_keyword}`.")
            return

        try:
            await handler(self, message, command_args, context)
        except Exception as e:
            print(f"CommandRouter ❌ Error executing command '{command_keyword}': {e}")
            traceback.print_exc()
            await context['send_to_command_channel'](f"❌ Error executing command `{command_keyword}`: {e}")

    @command("help")
    async def handle_help(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает список доступных команд или помощь по конкретной команде."""
        send_callback = context['send_to_command_channel']
        command_prefix = self._command_prefix
        internal_commands = sorted(self.__class__._command_handlers.keys())
        external_commands = ["party"] 
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
                temp_party_args = ["help"] + args[1:]
                temp_context = context.copy()
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
        Manages player characters.
        Usage:
        `{prefix}character create <name>` - Creates a new character with the given name.
        `{prefix}character delete` - Deletes your character in this guild.
        (Note: Delete functionality is conceptual and needs full implementation with confirmation.)
        """.format(prefix=self._command_prefix)
        send_callback = context['send_to_command_channel']
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id') # This is discord_user_id as string

        if not guild_id:
            await send_callback("Character commands can only be used in a server (guild).")
            return
        
        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return
        
        try:
            discord_user_id = int(author_id_str)
        except ValueError:
            await send_callback("Invalid user ID format.")
            return

        char_manager: Optional["CharacterManager"] = context.get('character_manager')
        if not char_manager:
            await send_callback("Character system is currently unavailable.")
            print("CommandRouter Error: CharacterManager not found in context for handle_character.")
            return

        if not args:
            help_text = (self.handle_character.__doc__ or "Character management commands.").format(prefix=self._command_prefix)
            await send_callback(f"Please specify an action. Usage:\n{help_text}")
            return

        subcommand = args[0].lower()
        action_args = args[1:]

        if subcommand == "create":
            if not action_args:
                await send_callback(f"Usage: `{self._command_prefix}character create <name>`")
                return
            
            character_name = " ".join(action_args) # Allow names with spaces

            if not character_name or len(character_name) < 3 or len(character_name) > 32: # Basic name validation
                await send_callback("Character name must be between 3 and 32 characters.")
                return
            
            try:
                # CharacterManager.create_character expects discord_id as int
                new_char = await char_manager.create_character(
                    discord_id=discord_user_id, 
                    name=character_name,
                    guild_id=guild_id,
                    # initial_location_id can be omitted to use default from CharacterManager
                    **context # Pass context for RuleEngine, etc.
                )
                if new_char:
                    await send_callback(f"✅ Character '{new_char.name}' created successfully with ID `{new_char.id}`!")
                else:
                    # create_character might return None if char exists or name taken,
                    # or could raise an exception for other reasons.
                    # Assuming it returns None for "already exists" type errors for now.
                    await send_callback(f"⚠️ Could not create character. You might already have a character in this guild, or the name '{character_name}' might be taken.")
            except ValueError as ve: # Catch specific errors if CharacterManager raises them
                await send_callback(f"⚠️ Error creating character: {ve}")
            except ConnectionError as ce: # DB connection issues
                await send_callback(f"⚠️ Database error: Could not save character. Please try again later. {ce}")
            except Exception as e:
                print(f"CommandRouter: Error in handle_character create: {e}")
                traceback.print_exc()
                await send_callback(f"An unexpected error occurred while creating character: {e}")

        elif subcommand in ["view", "sheet"]:
            target_char_to_view: Optional[Character] = None
            char_identifier_for_msg = "your character" # Default message for self-view

            if not action_args: # User wants to view their own character
                target_char_to_view = char_manager.get_character_by_discord_id(guild_id, discord_user_id)
                if not target_char_to_view:
                    await send_callback("You don't have a character in this guild to view.")
                    return
                # char_identifier_for_msg is already "your character"
            
            else: # Admin potentially viewing another character OR user specifying their own char name/id
                target_identifier = " ".join(action_args)
                
                # First, check if the user is trying to view their own character by providing an identifier
                # This is a common use case, e.g. /char view MyCharName
                potential_self_char = char_manager.get_character_by_discord_id(guild_id, discord_user_id)
                if potential_self_char:
                    if is_uuid_format(target_identifier) and potential_self_char.id == target_identifier:
                        target_char_to_view = potential_self_char
                    elif potential_self_char.name.lower() == target_identifier.lower(): # Case-insensitive name check
                        target_char_to_view = potential_self_char

                # If not viewing self by identifier, then it's an attempt to view others, requiring admin rights
                if not target_char_to_view:
                    admin_users_list = self._settings.get('bot_admins', [])
                    if not isinstance(admin_users_list, list): admin_users_list = []
                    admin_ids = {str(admin_id) for admin_id in admin_users_list}

                    if author_id_str not in admin_ids:
                        await send_callback("❌ You are not authorized to view other characters' sheets. You can only view your own character, either with or without specifying your character's name/ID.")
                        return

                    char_identifier_for_msg = f"character '{target_identifier}'" # Update for admin viewing message
                    
                    if is_uuid_format(target_identifier): 
                        target_char_to_view = char_manager.get_character(guild_id, target_identifier)
                    
                    if not target_char_to_view: 
                        target_char_to_view = char_manager.get_character_by_name(guild_id, target_identifier)

                    if not target_char_to_view:
                        await send_callback(f"Character '{target_identifier}' not found in this guild.")
                        return
            
            # At this point, target_char_to_view is the Character object to be viewed.
            if not self._character_view_service:
                await send_callback("Character sheet viewing service is currently unavailable.")
                print("CommandRouter Error: CharacterViewService not available in context for handle_character view.")
                return

            try:
                # get_character_sheet_view should return a string (plain text or pre-formatted for Discord)
                # It needs the character object and the context (for other managers if needed by the view service)
                sheet_view_text = await self._character_view_service.get_character_sheet_view(target_char_to_view, context)
                await send_callback(sheet_view_text)
            except Exception as e:
                print(f"CommandRouter: Error in handle_character view/sheet for {char_identifier_for_msg}: {e}")
                traceback.print_exc()
                await send_callback(f"An unexpected error occurred while generating the sheet for {char_identifier_for_msg}: {e}")
        
        elif subcommand == "delete":
            target_char_to_delete: Optional[Character] = None
            char_identifier_for_msg = "your character"

            if not action_args: # User wants to delete their own character
                target_char_to_delete = char_manager.get_character_by_discord_id(guild_id, discord_user_id)
                if not target_char_to_delete:
                    await send_callback("You don't have a character in this guild to delete.")
                    return
                char_identifier_for_msg = f"your character '{target_char_to_delete.name}'"
            
            else: # Admin potentially deleting another character
                admin_users_list = self._settings.get('bot_admins', [])
                if not isinstance(admin_users_list, list): admin_users_list = [] # Ensure it's a list
                admin_ids = {str(admin_id) for admin_id in admin_users_list} # Convert to set of strings

                if author_id_str not in admin_ids:
                    await send_callback("❌ You are not authorized to delete other characters. You can only delete your own character by using `/character delete` with no arguments.")
                    return

                target_identifier = " ".join(action_args)
                char_identifier_for_msg = f"character '{target_identifier}'"
                
                # Try resolving by ID first, then by name
                if is_uuid_format(target_identifier): # is_uuid_format is defined at the end of CommandRouter
                    target_char_to_delete = char_manager.get_character(guild_id, target_identifier)
                
                if not target_char_to_delete: # If not found by ID or not a UUID, try by name
                    target_char_to_delete = char_manager.get_character_by_name(guild_id, target_identifier)

                if not target_char_to_delete:
                    await send_callback(f"Character '{target_identifier}' not found in this guild.")
                    return
            
            # At this point, target_char_to_delete is the Character object to be deleted.
            # For non-admin self-delete, confirmation is recommended but skipped for this sub-task.
            # Example confirmation:
            # if not action_args and (len(args) < 2 or args[1].lower() != 'confirm'):
            #     await send_callback(f"Are you sure you want to delete {char_identifier_for_msg}? This action cannot be undone. Type `{self._command_prefix}character delete confirm` to proceed.")
            #     return
            # elif not action_args and len(args) >1 and args[1].lower() == 'confirm':
            #    pass # Proceed with self-deletion confirmed

            try:
                char_name_before_delete = target_char_to_delete.name
                char_id_before_delete = target_char_to_delete.id
                
                deleted_char_id_result = await char_manager.remove_character(
                    character_id=char_id_before_delete, 
                    guild_id=guild_id, 
                    **context
                )
                
                if deleted_char_id_result:
                    await send_callback(f"🗑️ Character '{char_name_before_delete}' (ID: `{deleted_char_id_result}`) has been deleted.")
                else:
                    # This case might happen if remove_character had an internal issue but didn't raise an exception
                    await send_callback(f"Could not delete {char_identifier_for_msg}. It might have already been removed or an error occurred.")
            
            except Exception as e:
                print(f"CommandRouter: Error in handle_character delete for {char_identifier_for_msg}: {e}")
                traceback.print_exc()
                await send_callback(f"An unexpected error occurred while deleting {char_identifier_for_msg}: {e}")

        else:
            help_text = (self.handle_character.__doc__ or "Character management commands.").format(prefix=self._command_prefix)
            await send_callback(f"Unknown character action: '{subcommand}'. Usage:\n{help_text}")


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
        await send_callback("Move command logic is complex and retained from previous version.")

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
            campaign_data = campaign_loader.load_campaign_from_file(file_path)
            if campaign_data:
                await send_callback(f"✅ Campaign data loaded from `{file_path}`.")
            else:
                await send_callback(f"❌ Failed to load campaign data from `{file_path}`.")
        except Exception as e:
            await send_callback(f"❌ Error loading campaign: {e}")

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
            relationships = relationship_manager.get_relationships_for_entity(guild_id, entity_id_to_inspect)
            if not relationships:
                await send_callback(f"ℹ️ No relationships found for entity `{entity_id_to_inspect}` in this guild.")
                return

            response_lines = [f"Relationships for Entity `{entity_id_to_inspect}`:"]
            for rel in relationships:
                other_entity_id = rel.entity2_id if rel.entity1_id == entity_id_to_inspect else rel.entity1_id
                other_entity_type = rel.entity2_type if rel.entity1_type == entity_id_to_inspect else rel.entity1_type
                response_lines.append(
                    f"- With `{other_entity_id}` ({other_entity_type}): **{rel.relationship_type}** (Strength: {rel.strength:.2f}). Details: _{rel.details or 'N/A'}_"
                )
            await send_callback("\n".join(response_lines))
        except Exception as e:
            print(f"CommandRouter Error in _gm_action_inspect_relationships: {e}")
            traceback.print_exc()
            await send_callback(f"❌ Error inspecting relationships: {e}")


    @command("gm")
    async def handle_gm(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        GM command dispatcher.
        Usage:
        `{prefix}gm load_campaign <file_path>`
        `{prefix}gm relationships inspect <entity_id>` 
        """.format(prefix=self._command_prefix)
        send_callback = context['send_to_command_channel']
        author_id = context['author_id']

        if not isinstance(self._settings, dict) or 'bot_admins' not in self._settings:
            await send_callback("❌ Bot config error: Admin list missing.")
            return
        admin_users_list = self._settings.get('bot_admins', [])
        if not isinstance(admin_users_list, list): 
            await send_callback("❌ Bot config error: Admin list format.")
            return
        admin_users = set(map(str, admin_users_list))

        if author_id not in admin_users:
            await send_callback("❌ Unauthorized.")
            return

        if not args:
            help_text = (self.handle_gm.__doc__ or "GM commands. Usage: {prefix}gm <subcommand> [args]").format(prefix=context['command_prefix'])
            await send_callback(help_text)
            return

        gm_subcommand = args[0].lower()
        gm_sub_args = args[1:]

        if gm_subcommand == "load_campaign":
            await self._gm_action_load_campaign(message, gm_sub_args, context)
        elif gm_subcommand == "relationships" and gm_sub_args and gm_sub_args[0].lower() == "inspect":
            await self._gm_action_inspect_relationships(message, gm_sub_args[1:], context) # Pass args after "inspect"
        else:
            await send_callback(f"❓ Unknown GM subcommand or missing arguments for 'relationships inspect'. Usage: {context['command_prefix']}gm <load_campaign|relationships inspect> [args]")
    
    @command("quest")
    async def handle_quest(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        Manages quests.
        Usage:
        `{prefix}quest list` - Lists your active quests.
        `{prefix}quest start <quest_id>` - Starts an available quest.
        `{prefix}quest complete <quest_id>` - Marks an active quest as successfully completed.
        `{prefix}quest fail <quest_id>` - Marks an active quest as failed.
        """.format(prefix=self._command_prefix)

        send_callback = context['send_to_command_channel']
        guild_id = context.get('guild_id')
        author_id = context.get('author_id') 

        if not guild_id:
            await send_callback("❌ Quest commands can only be used in a guild.")
            return

        quest_manager: Optional["QuestManager"] = context.get('quest_manager')
        character_manager: Optional["CharacterManager"] = context.get('character_manager')

        if not quest_manager:
            await send_callback("❌ Quest system is currently unavailable.")
            print("CommandRouter Error: QuestManager not found in context for handle_quest.")
            return
        
        if not character_manager:
            await send_callback("❌ Character system is currently unavailable.")
            print("CommandRouter Error: CharacterManager not found in context for handle_quest.")
            return

        player_char: Optional["Character"] = None
        player_char_game_id: Optional[str] = None
        try:
            if author_id: 
                player_char_id_int = int(author_id)
                player_char = character_manager.get_character_by_discord_id(guild_id, player_char_id_int)
                if not player_char:
                    await send_callback(f"❌ You don't have a character in this guild. Use `{context['command_prefix']}character create <name>` to create one.")
                    return
                player_char_game_id = player_char.id
            else: 
                await send_callback("❌ Could not identify your user ID.")
                return
        except ValueError:
            await send_callback("❌ Invalid author ID format.")
            return
        except Exception as e:
            await send_callback(f"❌ Error fetching your character: {e}")
            return

        if not player_char_game_id: 
            await send_callback("❌ Could not determine your character ID.")
            return

        if not args:
            help_text = (self.handle_quest.__doc__ or "Quest management commands.").format(prefix=context['command_prefix'])
            await send_callback(help_text)
            return

        subcommand = args[0].lower()
        quest_id_arg = args[1] if len(args) > 1 else None

        if subcommand == "list":
            active_quest_objects = quest_manager.get_active_quests_for_character(guild_id, player_char_game_id, character_manager)
            if not active_quest_objects:
                await send_callback("You have no active quests.")
                return
            response = "Your active quests:\n"
            for q_obj in active_quest_objects:
                response += f"- `{q_obj.id}`: {q_obj.name} ({q_obj.status})\n"
            await send_callback(response)

        elif subcommand == "start":
            if not quest_id_arg:
                await send_callback(f"Usage: `{context['command_prefix']}quest start <quest_id>`")
                return
            success = await quest_manager.start_quest(guild_id, quest_id_arg, player_char_game_id, character_manager)
            if success:
                await send_callback(f"Quest `{quest_id_arg}` started!")
            else:
                await send_callback(f"❌ Could not start quest `{quest_id_arg}`. It might not be available or already active.")
        
        elif subcommand == "complete":
            if not quest_id_arg:
                await send_callback(f"Usage: `{context['command_prefix']}quest complete <quest_id>`")
                return
            success = await quest_manager.complete_quest(guild_id, quest_id_arg, player_char_game_id, character_manager, success=True)
            if success:
                await send_callback(f"Quest `{quest_id_arg}` marked as completed successfully!")
            else:
                await send_callback(f"❌ Could not complete quest `{quest_id_arg}`. It might not be active or found.")

        elif subcommand == "fail":
            if not quest_id_arg:
                await send_callback(f"Usage: `{context['command_prefix']}quest fail <quest_id>`")
                return
            success = await quest_manager.fail_quest(guild_id, quest_id_arg, player_char_game_id, character_manager)
            if success:
                await send_callback(f"Quest `{quest_id_arg}` marked as failed.")
            else:
                await send_callback(f"❌ Could not mark quest `{quest_id_arg}` as failed. It might not be active or found.")
        
        else:
            await send_callback(f"❓ Unknown quest subcommand: `{subcommand}`. Valid are: list, start, complete, fail.")


    # --- Removed handle_party method and its decorators ---


    @command("roll")
    async def handle_roll(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Rolls dice based on standard dice notation (e.g., /roll 2d6+3, /roll d20)."""
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
            roll_result = await rule_engine.resolve_dice_roll(roll_string, context=context)
            
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

    @command("quest")
    async def handle_quest(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        Manages character quests.
        Usage:
        {prefix}quest list
        {prefix}quest start <quest_template_id>
        {prefix}quest complete <active_quest_id>
        {prefix}quest fail <active_quest_id>
        {prefix}quest objectives <active_quest_id> # Optional: To view current objectives
        """
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
                quest_list = await quest_manager.list_quests_for_character(character_id, guild_id, context)
                if not quest_list:
                    await send_callback("No quests currently available or active for you.")
                    return
                
                response = f"**Your Quests, {player_char.name}:**\n"
                for q_data in quest_list: # Assuming q_data is a dict with 'name', 'description', 'status'
                    response += f"- **{q_data.get('name', q_data.get('id'))}** ({q_data.get('status', 'unknown')})\n"
                    response += f"  _{q_data.get('description', 'No description.')}_\n"
                await send_callback(response)

            elif subcommand == "start":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest start <quest_template_id>")
                    return
                quest_template_id = quest_action_args[0]
                success = await quest_manager.start_quest(character_id, quest_template_id, guild_id, context)
                if success:
                    # QuestManager should ideally return quest name or details for a better message
                    await send_callback(f"Quest '{quest_template_id}' started!")
                else:
                    await send_callback(f"Failed to start quest '{quest_template_id}'. You may not meet prerequisites, or the quest is already active/completed, or it doesn't exist.")
            
            elif subcommand == "complete":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest complete <active_quest_id>")
                    return
                active_quest_id = quest_action_args[0]
                success = await quest_manager.complete_quest(character_id, active_quest_id, guild_id, context)
                if success:
                    await send_callback(f"Quest '{active_quest_id}' completed! Consequences and rewards (if any) have been applied.")
                else:
                    await send_callback(f"Failed to complete quest '{active_quest_id}'. Make sure all objectives are met or the quest ID is correct.")

            elif subcommand == "fail":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest fail <active_quest_id>")
                    return
                active_quest_id = quest_action_args[0]
                success = await quest_manager.fail_quest(character_id, active_quest_id, guild_id, context)
                if success:
                    await send_callback(f"Quest '{active_quest_id}' marked as failed.")
                else:
                    await send_callback(f"Failed to mark quest '{active_quest_id}' as failed. It might not be an active quest for you.")
            
            # Optional: /quest objectives <active_quest_id>
            elif subcommand == "objectives" or subcommand == "details":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest {subcommand} <active_quest_id>")
                    return
                active_quest_id = quest_action_args[0]
                # QuestManager needs a method like get_active_quest_details(char_id, q_id, guild_id)
                # active_quest_details = await quest_manager.get_active_quest_details(character_id, active_quest_id, guild_id, context)
                # For now, basic feedback:
                await send_callback(f"Displaying objectives for quest '{active_quest_id}' is not fully implemented yet, but your QuestManager would handle this.")


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
        Interact with Non-Player Characters.
        Usage:
        {prefix}npc talk <npc_id_or_name> [initial_message]
        """
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
                if player_char.location_id != target_npc.location_id:
                    npc_name = getattr(target_npc, 'name', npc_identifier)
                    player_loc_name = location_manager.get_location_name(guild_id, player_char.location_id) or "Unknown Location"
                    npc_loc_name = location_manager.get_location_name(guild_id, target_npc.location_id) or "an unknown place"
                    await send_callback(f"{npc_name} is not here. You are in {player_loc_name}, and they are in {npc_loc_name}.")
                    return
            
            # Determine dialogue template ID (this is game-specific logic)
            # Example: use a default template or one specified on the NPC model
            dialogue_template_id = getattr(target_npc, 'dialogue_template_id', 'generic_convo')

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
        """Allows the player to buy an item from the current location's market.
        Usage: {prefix}buy <item_template_id> [quantity]
        """
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
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return
            
            character_id = player_char.id
            current_location_id = getattr(player_char, 'location_id', None)
            if not current_location_id:
                await send_callback("Your character doesn't seem to be in any specific location to buy items.")
                return

            # Attempt to purchase the item
            # The EconomyManager.buy_item method handles most of the logic
            # (checking market stock, price, player currency, item creation, inventory update)
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
                # Get item name for a nicer message
                item_template = item_manager.get_item_template(guild_id, item_template_id_to_buy)
                item_name = getattr(item_template, 'name', item_template_id_to_buy) if item_template else item_template_id_to_buy
                
                if len(created_item_ids) == quantity_to_buy:
                    await send_callback(f"🛍️ You successfully bought {quantity_to_buy}x {item_name}!")
                elif created_item_ids: # Partial success
                    await send_callback(f"🛍️ You managed to buy {len(created_item_ids)}x {item_name} (requested {quantity_to_buy}).")
                else: # Should ideally be caught by buy_item returning None, but as a fallback
                    await send_callback(f"Purchase of {item_name} seems to have failed despite initial checks.")

            else:
                # EconomyManager.buy_item should ideally provide a reason for failure.
                # For now, a generic message.
                item_template = item_manager.get_item_template(guild_id, item_template_id_to_buy)
                item_name = getattr(item_template, 'name', item_template_id_to_buy) if item_template else item_template_id_to_buy
                await send_callback(f"Could not buy {item_name}. It might be out of stock, or you may not have enough currency.")
                
        except Exception as e:
            print(f"CommandRouter: Error in handle_buy for item '{item_template_id_to_buy}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to buy the item: {e}")


    @command("craft")
    async def handle_craft(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows the player to craft an item from a recipe.
        Usage: {prefix}craft <recipe_id> [quantity]
        """
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
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return
            
            character_id = player_char.id
            
            # Call CraftingManager to add the recipe to the character's queue
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


    @command("steal")
    async def handle_steal(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows the player to attempt to steal from a target NPC.
        Usage: {prefix}steal <target_npc_id_or_name>
        """
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

        if not char_manager or not npc_manager or not char_action_processor:
            await send_callback("Error: Required game systems (character, NPC, or action processing) are unavailable.")
            print("CommandRouter: Missing one or more managers/processors for handle_steal.")
            return

        try:
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return
            
            character_id = player_char.id

            # Find the target NPC
            target_npc = npc_manager.get_npc(guild_id, target_identifier)
            if not target_npc:
                if hasattr(npc_manager, 'get_npc_by_name'):
                    target_npc = npc_manager.get_npc_by_name(guild_id, target_identifier)
                if not target_npc:
                    await send_callback(f"NPC '{target_identifier}' not found in this realm.")
                    return
            
            target_npc_id = target_npc.id
            target_npc_name = getattr(target_npc, 'name', target_identifier)

            # Call CharacterActionProcessor to initiate the steal attempt
            success = await char_action_processor.process_steal_action(
                character_id=character_id,
                target_id=target_npc_id,
                target_type="NPC", # Currently only supporting NPC targets
                context=context
            )

            # process_steal_action itself will notify "You attempt to steal..."
            # The actual success/failure message comes when the action completes.
            if not success:
                await send_callback(f"Could not initiate steal attempt on {target_npc_name}.")
                
        except ValueError: # For int(author_id_str)
            await send_callback("Invalid user ID format.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_steal for target '{target_identifier}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to steal: {e}")


    @command("fight")
    async def handle_fight(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Initiates combat with a target NPC.
        Usage: {prefix}fight <target_npc_id_or_name>
        """
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
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return
            
            character_id = player_char.id
            current_location_id = getattr(player_char, 'location_id', None)
            if not current_location_id:
                await send_callback("Your character isn't in a location where combat can occur.")
                return

            # Find the target NPC
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
                player_loc_name = loc_manager.get_location_name(guild_id, current_location_id) if loc_manager else current_location_id
                npc_loc_name = loc_manager.get_location_name(guild_id, npc_location_id) if loc_manager else npc_location_id
                await send_callback(f"{target_npc_name} is not here. You are in {player_loc_name}, and they are in {npc_loc_name}.")
                return

            # 2. Eligibility Check (Already in combat?)
            if combat_manager.get_combat_by_participant_id(guild_id, character_id):
                await send_callback("You are already in combat!")
                return
            if combat_manager.get_combat_by_participant_id(guild_id, target_npc_id):
                await send_callback(f"{target_npc_name} is already in combat with someone else.")
                return
            
            # 3. (Optional) RuleEngine check for combat permissibility
            # if hasattr(rule_engine, 'can_initiate_combat') and \
            #    not await rule_engine.can_initiate_combat(player_char, target_npc, context=context):
            #     await send_callback(f"You cannot initiate combat with {target_npc_name} at this time or place.")
            #     return

            # Initiate combat
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
        """Allows the player to attempt to hide in their current location."""
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
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return
            
            character_id = player_char.id

            # Call CharacterActionProcessor to initiate the hide attempt
            success = await char_action_processor.process_hide_action(
                character_id=character_id,
                context=context
            )

            # process_hide_action itself will notify "You attempt to find a hiding spot..."
            # The actual success/failure message comes when the action completes.
            if not success:
                # This might occur if the character is busy or another pre-check in process_hide_action fails.
                await send_callback("Could not attempt to hide at this time. You might be busy or in an unsuitable location.")
                
        except ValueError: # For int(author_id_str)
            await send_callback("Invalid user ID format.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_hide: {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to hide: {e}")


    @command("steal")
    async def handle_steal(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows the player to attempt to steal from a target NPC.
        Usage: {prefix}steal <target_npc_id_or_name>
        """
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
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return
            
            character_id = player_char.id

            # Find the target NPC
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
            player_loc_id = getattr(player_char, 'location_id', None)
            target_loc_id = getattr(target_npc, 'location_id', None)

            if not player_loc_id:
                await send_callback("You don't seem to be in any location.")
                return
            if player_loc_id != target_loc_id:
                await send_callback(f"{target_npc_name} is not in your current location.")
                return

            # Call CharacterActionProcessor to initiate the steal attempt
            success = await char_action_processor.process_steal_action(
                character_id=character_id,
                target_id=target_npc_id,
                target_type="NPC", # Currently only supporting NPC targets
                context=context
            )

            # process_steal_action itself will notify "You attempt to steal..."
            # The actual success/failure message comes when the action completes.
            if not success:
                # This might occur if the character is busy or another pre-check in process_steal_action fails.
                await send_callback(f"Could not attempt to steal from {target_npc_name} at this time. You might be busy.")
                
        except ValueError: # For int(author_id_str)
            await send_callback("Invalid user ID format.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_steal for target '{target_identifier}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to steal: {e}")


    @command("use")
    async def handle_use(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Allows the player to use an item from their inventory, optionally on a target.
        Usage: {prefix}use <item_instance_id> [target_id]
        Note: If target_id is an NPC, it will be assumed. If it's another player, that needs specific handling or target_type.
        """
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
                elif npc_manager.get_npc(guild_id, target_id): # Check if it's a known NPC ID
                    target_type = "NPC"
                # else, could be another player character ID - CharacterActionProcessor would need to handle that
                # For now, if not self and not a known NPC, we can leave target_type as None or default to Character
                # and let RuleEngine validate if the item can be used on that type of target.
                # If target_type remains None, RuleEngine must be able to handle it (e.g. for items that don't need specific typed target).
                # For simplicity, if a target_id is given and it's not 'self' or a known NPC, we'll assume it's a Character ID.
                # This is a simplification; more robust target validation is needed for a full system.
                elif char_manager.get_character(guild_id, target_id): # Check if it's another character
                     target_type = "Character"
                else:
                    # If target_id is provided but not identified as self, NPC, or other Character, it's ambiguous
                    # For items that *require* a specific type of target, RuleEngine will fail it.
                    # For items that don't care or can target "environment", this might be fine.
                    print(f"CommandRouter: Target '{target_id}' for /use command is not self, a known NPC, or another known Character. Target type remains undetermined by CommandRouter.")
                    # We'll pass target_id, and target_type as None or its current value. RuleEngine must validate.


            success = await char_action_processor.process_use_item_action(
                character_id=character_id,
                item_instance_id=item_instance_id,
                target_id=target_id,
                target_type=target_type,
                context=context
            )

            if not success:
                # process_use_item_action should have sent a specific reason if it could.
                await send_callback(f"Could not use item '{item_instance_id}'. You might be busy, not own the item, or the target is invalid.")
                
        except ValueError: # For int(author_id_str)
            await send_callback("Invalid user ID format.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_use for item '{item_instance_id}': {e}")
            traceback.print_exc()
            await send_callback(f"An error occurred while trying to use the item: {e}")


    @command("gm")
    async def handle_gm(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """GM-level commands for managing the game.
        Usage:
        {prefix}gm save_state - Manually triggers a save of the current guild's game state.
        {prefix}gm create_npc <template_id> [location_id] [name] [is_temporary (true/false)] - Creates an NPC.
        {prefix}gm delete_npc <npc_id> - Deletes an NPC.
        {prefix}gm relationships inspect <entity_id> - Inspects relationships for an entity.
        {prefix}gm load_campaign [campaign_id] - Loads campaign data for the current guild.
        """
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
            await send_callback(f"Usage: {self._command_prefix}gm <subcommand> [arguments]\nAvailable subcommands:\n{doc_string}")
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

            npc_manager = context.get('npc_manager')
            if not npc_manager:
                await send_callback("Error: NpcManager is not available.")
                return
            
            # Optional: Spawn at GM's character current location if loc_id is None
            # char_manager = context.get('character_manager')
            # if loc_id is None and char_manager and author_id_str:
            #    gm_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            #    if gm_char: loc_id = getattr(gm_char, 'location_id', None)

            created_npc_id = await npc_manager.create_npc(
                guild_id=guild_id,
                npc_template_id=template_id,
                location_id=loc_id,
                name=npc_name_arg, 
                is_temporary=is_temporary_bool,
                # state_variables={}, # Example: if NpcManager.create_npc supports more kwargs
                **context # Pass full context
            )
            if created_npc_id:
                new_npc = npc_manager.get_npc(guild_id, created_npc_id)
                display_name = getattr(new_npc, 'name', template_id) if new_npc else template_id
                await send_callback(f"NPC '{display_name}' (ID: `{created_npc_id}`) created successfully at location `{getattr(new_npc, 'location_id', 'N/A')}`.")
            else:
                await send_callback(f"Failed to create NPC from template '{template_id}'.")

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

            removed_id = await npc_manager.remove_npc(guild_id, npc_id_to_delete, **context)
            if removed_id:
                await send_callback(f"NPC `{removed_id}` has been removed.")
            else:
                await send_callback(f"Failed to remove NPC `{npc_id_to_delete}`. It might not exist or an error occurred.")

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
                    # Attempt to get entity name for better message
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
                    
                    relations = await relationship_manager.get_relationships_for_entity(guild_id, entity_id_to_inspect, context=context)
                    
                    if relations:
                        response = f"**Relationships for {entity_name} (`{entity_id_to_inspect}`):**\n"
                        for rel in relations:
                            target_id_val = rel.get('target_id', 'Unknown Target') 
                            # Attempt to get target name for better display
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
                    await send_callback(f"An error occurred: {e}")
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

def is_uuid_format(s: str) -> bool:
     """Проверяет, выглядит ли строка как UUID (простая проверка формата)."""
     if not isinstance(s, str):
          return False
     if len(s) == 36 and s.count('-') == 4 and s[8] == '-' and s[13] == '-' and s[18] == '-' and s[23] == '-':
          try:
               uuid.UUID(s)
               return True
          except ValueError:
               return False
     return False

# --- End of CommandRouter Class ---

print("DEBUG: command_router.py module loaded.")