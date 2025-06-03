# bot/game/command_router.py

print("--- Начинается загрузка: command_router.py")

import asyncio
import traceback
import shlex # For better argument parsing (handles quotes)
import uuid # Needed for is_uuid_format example
# Import typing components
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING, ClassVar, Union
from collections import Counter


# Import discord types for type hints
from discord import Message 
# Import discord for Embed etc.
import discord

# TOP-LEVEL IMPORT FOR CAMPAIGNLOADER
from bot.services.campaign_loader import CampaignLoader
# TOP-LEVEL IMPORT FOR RELATIONSHIPMANAGER
from bot.game.managers.relationship_manager import RelationshipManager
# TOP-LEVEL IMPORT FOR QUESTMANAGER
from bot.game.managers.quest_manager import QuestManager


if TYPE_CHECKING:
    from bot.game.models.character import Character
    from bot.game.models.party import Party 
    from bot.game.models.relationship import Relationship 
    from bot.game.models.quest import Quest 

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
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.command_handlers.party_handler import PartyCommandHandler


SendToChannelCallback = Callable[..., Awaitable[Any]] 
SendCallbackFactory = Callable[[int], SendToChannelCallback] 

_command_registry: Dict[str, Callable[..., Awaitable[Any]]] = {}

def command(keyword: str) -> Callable:
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        lower_keyword = keyword.lower()
        if lower_keyword in _command_registry:
             print(f"WARNING: Command '{keyword}' is already registered. Overwriting with {func.__name__}")
        _command_registry[lower_keyword] = func
        print(f"DEBUG: Command '{keyword}' registered to {func.__name__}")
        return func
    return decorator

class CommandRouter:
    _command_handlers: ClassVar[Dict[str, Callable[..., Awaitable[Any]]]] = _command_registry

    def __init__(
        self,
        character_manager: "CharacterManager",
        event_manager: "EventManager", 
        persistence_manager: "PersistenceManager",
        settings: Dict[str, Any],
        world_simulation_processor: "WorldSimulationProcessor", # type: ignore
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
        event_action_processor: Optional["EventActionProcessor"] = None, # type: ignore
        event_stage_processor: Optional["EventStageProcessor"] = None, # type: ignore
        quest_manager: Optional["QuestManager"] = None, 
        dialogue_manager: Optional["DialogueManager"] = None, 
        campaign_loader: Optional["CampaignLoader"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
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

        self._command_prefix: str = self._settings.get('command_prefix', '/')
        if not isinstance(self._command_prefix, str) or not self._command_prefix:
            print(f"CommandRouter Warning: Invalid command prefix in settings: '{self._settings.get('command_prefix')}'. Defaulting to '/'.")
            self._command_prefix = '/'
        print("CommandRouter initialized.")

    async def route(self, message: Message) -> None:
        if not message.content or not message.content.startswith(self._command_prefix) or message.author.bot:
            return

        try:
            command_line = message.content[len(self._command_prefix):].strip()
            if not command_line: return
            split_command = shlex.split(command_line)
            if not split_command: return
            command_keyword = split_command[0].lower()
            command_args = split_command[1:]
        except Exception as e:
            print(f"CommandRouter Error: Failed to parse command '{message.content}': {e}")
            traceback.print_exc()
            try:
                 await self._send_callback_factory(message.channel.id)(f"❌ Ошибка при разборе команды: {e}")
            except Exception as cb_e:
                 print(f"CommandRouter Error sending parsing error message: {cb_e}")
            return

        print(f"CommandRouter: Routing command '{command_keyword}' with args {command_args} from user {message.author.id} in guild {message.guild.id if message.guild else 'DM'}.")

        managers_in_context = {
            k: v for k, v in self.__dict__.items() 
            if not k.startswith('__') and not callable(v) and k != '_command_prefix' and k != '_command_handlers' # type: ignore
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
            **managers_in_context # type: ignore
        }

        if command_keyword == "party":
             if self._party_command_handler:
                  try:
                      await self._party_command_handler.handle(message, command_args, context)
                  except Exception as e:
                       print(f"CommandRouter ❌ Error executing 'party' command: {e}")
                       traceback.print_exc()
                       await context['send_to_command_channel'](f"❌ Error in party command: {e}")
             else:
                  await context['send_to_command_channel']("❌ Party system unavailable.")
             return

        handler = self._command_handlers.get(command_keyword)
        if not handler:
            await context['send_to_command_channel'](f"❓ Unknown command: `{self._command_prefix}{command_keyword}`.")
            return

        try:
            await handler(self, message, command_args, context)
        except Exception as e:
            print(f"CommandRouter ❌ Error executing command '{command_keyword}': {e}")
            traceback.print_exc()
            await context['send_to_command_channel'](f"❌ Error executing command `{command_keyword}`: {e}")


# bot/game/command_router.py

print("--- Начинается загрузка: command_router.py")

import asyncio
import traceback
import shlex # For better argument parsing (handles quotes)
import uuid # Needed for is_uuid_format example
# Import typing components
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING, ClassVar, Union
from collections import Counter


# Import discord types for type hints
from discord import Message
# Import discord for Embed etc.
import discord

# TOP-LEVEL IMPORT FOR CAMPAIGNLOADER
from bot.services.campaign_loader import CampaignLoader
# TOP-LEVEL IMPORT FOR RELATIONSHIPMANAGER
from bot.game.managers.relationship_manager import RelationshipManager
# TOP-LEVEL IMPORT FOR QUESTMANAGER
from bot.game.managers.quest_manager import QuestManager


if TYPE_CHECKING:
    from bot.game.models.character import Character
    from bot.game.models.party import Party
    from bot.game.models.relationship import Relationship
    from bot.game.models.quest import Quest

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
    from bot.game.managers.dialogue_manager import DialogueManager
    from bot.game.managers.game_log_manager import GameLogManager
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.command_handlers.party_handler import PartyCommandHandler


SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]

_command_registry: Dict[str, Callable[..., Awaitable[Any]]] = {}

def command(keyword: str) -> Callable:
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        lower_keyword = keyword.lower()
        if lower_keyword in _command_registry:
             print(f"WARNING: Command '{keyword}' is already registered. Overwriting with {func.__name__}")
        _command_registry[lower_keyword] = func
        print(f"DEBUG: Command '{keyword}' registered to {func.__name__}")
        return func
    return decorator

class CommandRouter:
    _command_handlers: ClassVar[Dict[str, Callable[..., Awaitable[Any]]]] = _command_registry

    def __init__(
        self,
        character_manager: "CharacterManager",
        event_manager: "EventManager",
        persistence_manager: "PersistenceManager",
        settings: Dict[str, Any],
        world_simulation_processor: "WorldSimulationProcessor", # type: ignore
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
        event_action_processor: Optional["EventActionProcessor"] = None, # type: ignore
        event_stage_processor: Optional["EventStageProcessor"] = None, # type: ignore
        quest_manager: Optional["QuestManager"] = None,
        dialogue_manager: Optional["DialogueManager"] = None,
        campaign_loader: Optional["CampaignLoader"] = None,
        relationship_manager: Optional["RelationshipManager"] = None,
        game_log_manager: Optional["GameLogManager"] = None,
    ):
        print("Initializing CommandRouter...")
        self._character_manager = character_manager
        # ... (rest of __init__ will be in Part 2)


        # ... (continuation of __init__) ...
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

        self._command_prefix: str = self._settings.get('command_prefix', '/')
        if not isinstance(self._command_prefix, str) or not self._command_prefix:
            print(f"CommandRouter Warning: Invalid command prefix in settings: '{self._settings.get('command_prefix')}'. Defaulting to '/'.")
            self._command_prefix = '/'
        print("CommandRouter initialized.")

    async def route(self, message: Message) -> None:
        if not message.content or not message.content.startswith(self._command_prefix) or message.author.bot:
            return

        try:
            command_line = message.content[len(self._command_prefix):].strip()
            if not command_line: return
            split_command = shlex.split(command_line)
            if not split_command: return
            command_keyword = split_command[0].lower()
            command_args = split_command[1:]
        except Exception as e:
            print(f"CommandRouter Error: Failed to parse command '{message.content}': {e}")
            traceback.print_exc()
            try:
                 await self._send_callback_factory(message.channel.id)(f"❌ Ошибка при разборе команды: {e}")
            except Exception as cb_e:
                 print(f"CommandRouter Error sending parsing error message: {cb_e}")
            return

        print(f"CommandRouter: Routing command '{command_keyword}' with args {command_args} from user {message.author.id} in guild {message.guild.id if message.guild else 'DM'}.")

        managers_in_context = {
            k: v for k, v in self.__dict__.items() 
            if not k.startswith('__') and not callable(v) and k != '_command_prefix' and k != '_command_handlers' # type: ignore
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
            **managers_in_context # type: ignore
        }

        if command_keyword == "party":
             if self._party_command_handler:
                  try:
                      await self._party_command_handler.handle(message, command_args, context)
                  except Exception as e:
                       print(f"CommandRouter ❌ Error executing 'party' command: {e}")
                       traceback.print_exc()
                       await context['send_to_command_channel'](f"❌ Error in party command: {e}")
             else:
                  await context['send_to_command_channel']("❌ Party system unavailable.")
             return

        handler = self._command_handlers.get(command_keyword)
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
        # ... (help logic will be in Part 3) ...


    # ... (continuation of handle_help) ...
        send_callback = context['send_to_command_channel']
        command_prefix = self._command_prefix
        internal_commands = sorted(self._command_handlers.keys())
        external_commands = ["party"]
        all_commands = sorted(list(set(internal_commands + external_commands)))

        if not args:
            help_message = f"Доступные команды (префикс `{command_prefix}`):\n"
            help_message += ", ".join([f"`{cmd}`" for cmd in all_commands])
            help_message += f"\nИспользуйте `{command_prefix}help <команда>` для подробностей."
            await send_callback(help_message)
        else:
            target_command = args[0].lower()
            handler_method = self._command_handlers.get(target_command)
            if handler_method:
                # Accessing __doc__ from the method instance itself
                docstring = (getattr(handler_method, '__doc__', "Нет описания.") or "Нет описания.").format(prefix=self._command_prefix)
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
    async def handle_character(self, message: Message, args_list: List[str], context: Dict[str, Any]) -> None: # Renamed args to args_list
        """
        Manages player characters.
        Usage:
        `{prefix}character create <name>` - Creates a new character.
        `{prefix}character delete [character_name_or_id]` - Deletes your character, or specified if admin.
        `{prefix}character view [character_name_or_id]` - Views character sheet (alias: sheet).
        """.format(prefix=self._command_prefix) # Ensure this format works or adjust prefix manually in string
        send_callback = context['send_to_command_channel']
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')

        if not guild_id:
            await send_callback("Character commands can only be used in a server.")
            return
        if not author_id_str:
            await send_callback("Could not identify your user ID.")
            return

        try:
            # Ensure discord_user_id is an int for CharacterManager, but author_id_str is used for admin checks
            discord_user_id = int(author_id_str)
        except ValueError:
            await send_callback("Invalid user ID format.")
            return

        char_manager: Optional["CharacterManager"] = context.get('character_manager')
        if not char_manager:
            await send_callback("❌ Character system is currently unavailable.")
            return

        if not args_list:
            # Correctly access docstring for the method instance
            doc = (getattr(self.handle_character, '__doc__', "Character commands.") or "Character commands.").format(prefix=self._command_prefix)
            await send_callback(f"Please specify an action. Usage:\n{doc}") # Using \n for newline in f-string for safety
            return

        action = args_list[0].lower()
        action_args_list = args_list[1:] # Renamed variable to avoid conflict

        if action == "create":
            if not action_args_list:
                await send_callback(f"Usage: `{self._command_prefix}character create <name>`")
                return
            character_name = " ".join(action_args_list)
            if not (3 <= len(character_name) <= 32): # Example length validation
                await send_callback("⚠️ Character name must be between 3 and 32 characters.")
                return
            try:
                # THE FIX IS HERE: guild_id is NOT passed explicitly anymore
                new_char_id = await char_manager.create_character(
                    discord_id=discord_user_id,
                    name=character_name,
                    # guild_id=guild_id, # REMOVED - already in context
                    **context # context dictionary contains guild_id and other necessary managers
                )
                if new_char_id:
                    await send_callback(f"✅ Character '{character_name}' created successfully with ID `{new_char_id}`!")
                else:
                    await send_callback(f"⚠️ Could not create character. You might already have one, or the name '{character_name}' is taken.")
            except ValueError as ve: # Specific error from CharacterManager
                await send_callback(f"⚠️ Error: {ve}")
            except Exception as e:
                print(f"CommandRouter: Error in handle_character create: {e}\n{traceback.format_exc()}")
                await send_callback(f"❌ An unexpected error occurred while creating character '{character_name}'.")
        # ... (elif action in ["view", "sheet"] will be in Part 4) ...


        # ... (continuation of handle_character) ...
        elif action in ["view", "sheet"]:
            target_char: Optional["Character"] = None # Type hint for clarity
            view_target_msg = "your character"
            if not action_args_list: # Viewing self
                target_char = char_manager.get_character_by_discord_id(guild_id, discord_user_id)
                if not target_char:
                    await send_callback("You don't have a character to view.")
                    return
            else: # Viewing self by ID/name or viewing other (if admin)
                identifier = " ".join(action_args_list)
                # Check if user is trying to view their own character by providing an identifier
                self_char_check = char_manager.get_character_by_discord_id(guild_id, discord_user_id)
                if self_char_check and (self_char_check.id == identifier or self_char_check.name.lower() == identifier.lower()):
                    target_char = self_char_check
                else: # Viewing other, requires admin rights
                    admin_ids = {str(admin_id) for admin_id in self._settings.get('bot_admins', [])}
                    if author_id_str not in admin_ids:
                        await send_callback("❌ You can only view your own character or specify your own character's name/ID. To view others, you need admin rights.")
                        return
                    view_target_msg = f"character '{identifier}'"
                    target_char = char_manager.get_character(guild_id, identifier) if is_uuid_format(identifier) else char_manager.get_character_by_name(guild_id, identifier)
                    if not target_char:
                        await send_callback(f"Character '{identifier}' not found.")
                        return
            
            if not target_char: # Safeguard, should have been caught by conditions above
                 await send_callback("Character not found.")
                 return

            view_service: Optional["CharacterViewService"] = context.get('character_view_service')
            if not view_service:
                await send_callback("Character sheet viewing service is unavailable.")
                return
            try:
                sheet_text = await view_service.get_character_sheet_view(target_char, context)
                await send_callback(sheet_text)
            except Exception as e:
                print(f"CommandRouter: Error in handle_character view for {view_target_msg}: {e}\n{traceback.format_exc()}")
                await send_callback(f"❌ Error generating sheet for {view_target_msg}.")

        elif action == "delete":
            target_char_to_delete: Optional["Character"] = None # Type hint
            delete_target_msg = "your character"
            if not action_args_list: # Deleting self
                target_char_to_delete = char_manager.get_character_by_discord_id(guild_id, discord_user_id)
                if not target_char_to_delete:
                    await send_callback("You don't have a character to delete.")
                    return
                delete_target_msg = f"your character '{target_char_to_delete.name}'"
            else: # Admin deleting other
                admin_ids = {str(admin_id) for admin_id in self._settings.get('bot_admins', [])}
                if author_id_str not in admin_ids:
                    await send_callback("❌ You can only delete your own character (with no arguments). To delete other characters, you need admin rights.")
                    return
                identifier = " ".join(action_args_list)
                delete_target_msg = f"character '{identifier}'"
                target_char_to_delete = char_manager.get_character(guild_id, identifier) if is_uuid_format(identifier) else char_manager.get_character_by_name(guild_id, identifier)
                if not target_char_to_delete:
                    await send_callback(f"Character '{identifier}' not found to delete.")
                    return
            
            if not target_char_to_delete: # Safeguard
                await send_callback("Could not identify character to delete.")
                return
            
            try:
                name_before_delete = target_char_to_delete.name
                id_before_delete = target_char_to_delete.id
                # remove_character expects character_id (which is Character.id, not discord_id)
                deleted_id = await char_manager.remove_character(character_id=id_before_delete, guild_id=guild_id, **context)
                if deleted_id:
                    await send_callback(f"🗑️ Character '{name_before_delete}' (ID: `{deleted_id}`) has been deleted.")
                else:
                    await send_callback(f"Could not delete {delete_target_msg}. The character might have already been removed or an internal error occurred.")
            except Exception as e:
                print(f"CommandRouter: Error in handle_character delete for {delete_target_msg}: {e}\n{traceback.format_exc()}")
                await send_callback(f"❌ Error deleting {delete_target_msg}.")
        else:
            doc = (getattr(self.handle_character, '__doc__', "Character commands.") or "Character commands.").format(prefix=self._command_prefix)
            await send_callback(f"Unknown character action: '{action}'. Usage:\n{doc}")

    @command("status")
    async def handle_status(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает лист персонажа. Usage: {prefix}status [character_id_or_name]""".format(prefix=self._command_prefix)
        await self.handle_character(message, ["view"] + args, context)

    @command("inventory")
    async def handle_inventory(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает инвентарь. Usage: {prefix}inventory [character_id_or_name]""".format(prefix=self._command_prefix)
        send_callback = context['send_to_command_channel']
        await send_callback("Inventory command logic needs full implementation with ItemManager.")

    @command("move")
    async def handle_move(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Перемещает персонажа. Usage: {prefix}move <location_id>""".format(prefix=self._command_prefix)
        send_callback = context['send_to_command_channel']
        await send_callback("Move command logic needs full implementation with CharacterManager and LocationManager.")

    # ... (GM methods will be in Part 5) ...


    # ... (continuation: GM methods) ...
    async def _gm_action_load_campaign(self, message: Message, sub_args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context['send_to_command_channel']
        campaign_loader: Optional["CampaignLoader"] = context.get('campaign_loader')
        guild_id = context.get('guild_id')
        persistence_manager: Optional["PersistenceManager"] = context.get('persistence_manager')

        if not campaign_loader or not guild_id or not persistence_manager:
            await send_callback("❌ CampaignLoader, Guild ID, or PersistenceManager service unavailable.")
            return
        if not sub_args:
            await send_callback(f"Usage: `{context['command_prefix']}gm load_campaign <campaign_id_from_data_campaigns_dir>`")
            return
        
        campaign_identifier = sub_args[0]
        
        try:
            if hasattr(persistence_manager, 'trigger_campaign_load_and_distribution'):
                await send_callback(f"Initiating campaign load for '{campaign_identifier}' in guild {guild_id}...")
                await persistence_manager.trigger_campaign_load_and_distribution(guild_id, campaign_identifier, **context)
                await send_callback(f"✅ Campaign data for '{campaign_identifier}' processed for guild {guild_id}.")
            else:
                campaign_data = await campaign_loader.load_campaign_data_from_source(campaign_identifier) # type: ignore
                if campaign_data:
                    await send_callback(f"✅ Campaign data for '{campaign_identifier}' loaded from source. Further processing depends on PersistenceManager.")
                else:
                    await send_callback(f"❌ Failed to load campaign data for '{campaign_identifier}' from source.")
        except Exception as e:
            await send_callback(f"❌ Error loading campaign '{campaign_identifier}': {e}")
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
            relationships = await relationship_manager.get_relationships_for_entity(guild_id, entity_id_to_inspect, context=context) # type: ignore
            if not relationships:
                await send_callback(f"ℹ️ No relationships found for entity `{entity_id_to_inspect}` in this guild.")
                return

            response_lines = [f"Relationships for Entity `{entity_id_to_inspect}`:"]
            for rel_data in relationships: # Assuming rel is now a dict from manager
                target_id_val = rel_data.get('target_id', 'Unknown Target')
                target_name_str = target_id_val # Simplified
                rel_type = rel_data.get('type', 'unknown')
                strength = float(rel_data.get('strength', 0.0))
                response_lines.append(
                    f"- With `{target_name_str}` (`{target_id_val}`): Type: `{rel_type}`, Strength: `{strength:.1f}`"
                )
            if len(response_lines) > 1:
                full_response = "\n".join(response_lines)
                if len(full_response) > 1950 : full_response = full_response[:1950] + "\n... (truncated)"
                await send_callback(full_response)
            else: 
                 await send_callback(f"ℹ️ No specific relationship details found for entity `{entity_id_to_inspect}` in this guild, though the entity might exist.")

        except Exception as e:
            print(f"CommandRouter Error in _gm_action_inspect_relationships: {e}")
            traceback.print_exc()
            await send_callback(f"❌ Error inspecting relationships: {e}")

    @command("gm")
    async def handle_gm(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        GM-level commands for managing the game.
        Usage:
        `{prefix}gm save_state` - Manually triggers a save of the current guild's game state.
        `{prefix}gm create_npc <template_id> [location_id] [name] [is_temporary (true/false)]` - Creates an NPC.
        `{prefix}gm delete_npc <npc_id>` - Deletes an NPC.
        `{prefix}gm relationships inspect <entity_id>` - Inspects relationships for an entity.
        `{prefix}gm load_campaign <campaign_id>` - Loads campaign data for the current guild.
        """.format(prefix=self._command_prefix)
        send_callback = context.get('send_to_command_channel')
        author_id_str = str(message.author.id) 

        gm_ids = [str(gm_id) for gm_id in self._settings.get('bot_admins', [])] 
        if author_id_str not in gm_ids:
            await send_callback("Access Denied: This command is for GMs only.")
            return

        if not args:
            doc_string = (getattr(self.handle_gm, '__doc__', "GM commands.") or "GM commands.").format(prefix=self._command_prefix)
            await send_callback(f"Usage: {self._command_prefix}gm <subcommand> [arguments]\nAvailable subcommands:\n{doc_string}")
            return

        subcommand = args[0].lower()
        gm_args = args[1:] 
        guild_id = context.get('guild_id') 

        if subcommand == "save_state":
            persistence_manager = context.get('persistence_manager') 
            if not guild_id: 
                await send_callback("Error: This GM command must be used in a server channel.")
                return
            if not persistence_manager:
                await send_callback("Error: PersistenceManager is not available. Cannot save state.")
                return
            try:
                await persistence_manager.save_game_state(guild_ids=[guild_id], **context)
                await send_callback(f"✅ Game state saving process initiated for this guild ({guild_id}).")
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
            created_npc_id = await npc_manager.create_npc( 
                guild_id=guild_id, npc_template_id=template_id,
                location_id=loc_id, name=npc_name_arg, 
                is_temporary=is_temporary_bool, **context
            )
            if created_npc_id:
                new_npc = npc_manager.get_npc(guild_id, created_npc_id)
                display_name = getattr(new_npc, 'name', template_id) if new_npc else template_id
                await send_callback(f"NPC '{display_name}' (ID: `{created_npc_id}`) created successfully at location `{getattr(new_npc, 'location_id', 'N/A')}`.")
            else:
                await send_callback(f"Failed to create NPC from template '{template_id}'.")

        # ... (elif subcommand == "delete_npc" will be in Part 6) ...


        # ... (continuation of handle_gm) ...
        elif subcommand == "delete_npc":
            if not guild_id:
                await send_callback("Error: This GM command must be used in a server channel.")
                return
            if not gm_args:
                await send_callback(f"Usage: {self._command_prefix}gm delete_npc <npc_id>")
                return
            npc_id_to_delete = gm_args[0]
            npc_manager: Optional["NpcManager"] = context.get('npc_manager')
            if not npc_manager:
                await send_callback("Error: NpcManager is not available.")
                return
            removed_id = await npc_manager.remove_npc(guild_id, npc_id_to_delete, **context)
            if removed_id:
                await send_callback(f"NPC `{removed_id}` has been removed.")
            else:
                await send_callback(f"Failed to remove NPC `{npc_id_to_delete}`.")

        elif subcommand in ["relationships", "rel"] :
            if not gm_args or gm_args[0].lower() != "inspect" or len(gm_args) < 2:
                await send_callback(f"Usage: {self._command_prefix}gm {subcommand} inspect <entity_id>")
                return
            await self._gm_action_inspect_relationships(message, gm_args[1:], context) 

        elif subcommand == "load_campaign":
            if not guild_id: 
                await send_callback("Error: Campaign loading is guild-specific.")
                return
            await self._gm_action_load_campaign(message, gm_args, context)
            
        else:
            await send_callback(f"Unknown GM subcommand: '{subcommand}'. Use `{self._command_prefix}gm` for help.")
    
    @command("roll")
    async def handle_roll(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context.get('send_to_command_channel')
        if not send_callback: return
        if not args:
            await send_callback(f"Usage: {self._command_prefix}roll <dice_notation>")
            return
        roll_string = "".join(args) 
        rule_engine: Optional["RuleEngine"] = context.get('rule_engine')
        if not rule_engine:
            await send_callback("Error: RuleEngine not available.")
            return
        try:
            roll_result = await rule_engine.resolve_dice_roll(roll_string, context=context)
            rolls_str = ", ".join(map(str, roll_result.get('rolls', [])))
            result_message = f"🎲 {message.author.mention} rolled **{roll_result.get('roll_string', roll_string)}**:\n" 
            if roll_result.get('dice_sides') == 'F': 
                result_message += f"Rolls: [{rolls_str}] (Symbols: {' '.join(['+' if r > 0 else '-' if r < 0 else '0' for r in roll_result.get('rolls', [])])})"
            else:
                result_message += f"Rolls: [{rolls_str}]"
            modifier_val = roll_result.get('modifier', 0)
            if modifier_val != 0: 
                result_message += f" Modifier: {modifier_val:+}" 
            result_message += f"\n**Total: {roll_result.get('total')}**" 
            await send_callback(result_message)
        except ValueError as ve:
            await send_callback(f"Error: Invalid dice notation for '{roll_string}'. {ve}")
        except Exception as e:
            print(f"CommandRouter: Error in handle_roll for '{roll_string}': {e}\n{traceback.format_exc()}")
            await send_callback(f"An error occurred.")

    @command("quest") 
    async def handle_quest(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context.get('send_to_command_channel')
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id') 
        if not send_callback or not guild_id or not author_id_str:
            # Use message.channel.send as a fallback if send_callback is None for some reason
            # though it should always be populated by the route method.
            await (send_callback or message.channel.send)("Command prerequisites not met (channel, guild, or user ID).")
            return

        char_manager: Optional["CharacterManager"] = context.get('character_manager')
        quest_manager: Optional["QuestManager"] = context.get('quest_manager') 
        if not char_manager or not quest_manager:
            await send_callback("Character or Quest system is unavailable.")
            return

        try:
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You do not have an active character. Use `{self._command_prefix}character create <name>`.")
                return
            character_id = player_char.id # type: ignore
        except ValueError:
            await send_callback("Invalid user ID format.")
            return
        except Exception as e:
            await send_callback(f"Error fetching your character: {e}")
            return

        if not args:
            doc = (getattr(self.handle_quest, '__doc__', "Quest commands.") or "Quest commands.").format(prefix=self._command_prefix)
            await send_callback(f"Please specify a quest action. Usage:\n{doc}")
            return

        subcommand = args[0].lower()
        quest_action_args = args[1:]

        try:
            if subcommand == "list":
                quest_list_data = await quest_manager.list_quests_for_character(character_id, guild_id, context)
                if not quest_list_data:
                    await send_callback("No quests currently available or active for you.")
                    return
                response = f"**Your Quests, {player_char.name}:**\n" # type: ignore
                for q_data in quest_list_data: 
                    response += f"- **{q_data.get('name', q_data.get('id'))}** ({q_data.get('status', 'unknown')})\n  _{q_data.get('description', 'No description.')}_\n"
                await send_callback(response)
            elif subcommand == "start":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest start <quest_template_id>")
                    return
                quest_template_id = quest_action_args[0]
                started_quest = await quest_manager.start_quest(character_id, quest_template_id, guild_id, context)
                if started_quest:
                    await send_callback(f"Quest '{started_quest.get('name', quest_template_id)}' started!")
                else:
                    await send_callback(f"Failed to start quest '{quest_template_id}'.")
            # ... (elif for complete, fail, objectives will be in Part 7) ...


            # ... (continuation of handle_quest) ...
            elif subcommand == "complete":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest complete <active_quest_id>")
                    return
                active_quest_id = quest_action_args[0]
                success = await quest_manager.complete_quest(character_id, active_quest_id, guild_id, context)
                await send_callback(f"Quest '{active_quest_id}' completed!" if success else f"Failed to complete quest '{active_quest_id}'.")
            elif subcommand == "fail":
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest fail <active_quest_id>")
                    return
                active_quest_id = quest_action_args[0]
                success = await quest_manager.fail_quest(character_id, active_quest_id, guild_id, context)
                await send_callback(f"Quest '{active_quest_id}' marked as failed." if success else f"Failed to mark quest '{active_quest_id}' as failed.")
            elif subcommand in ["objectives", "details"]:
                if not quest_action_args:
                    await send_callback(f"Usage: {self._command_prefix}quest {subcommand} <active_quest_id>")
                    return
                active_quest_id = quest_action_args[0]
                # Placeholder for QuestManager.get_active_quest_details
                # This would ideally fetch the quest object and format its objectives.
                # For now, just acknowledging the command.
                q_obj = quest_manager.get_active_quest(guild_id, character_id, active_quest_id) # Assuming such a method
                if q_obj:
                    objectives_text = f"Objectives for {q_obj.get('name', active_quest_id)}:\n"
                    for i, obj_detail in enumerate(q_obj.get('objectives', [])):
                        obj_status = "Complete" if q_obj.get('progress', {}).get(obj_detail.get('id')) == obj_detail.get('count') else "In Progress"
                        objectives_text += f"  {i+1}. {obj_detail.get('description')} ({obj_status} - {q_obj.get('progress', {}).get(obj_detail.get('id'), 0)}/{obj_detail.get('count')})\n"
                    await send_callback(objectives_text)
                else:
                    await send_callback(f"Active quest '{active_quest_id}' not found or no details available.")
            else:
                doc = (getattr(self.handle_quest, '__doc__', "Quest commands.") or "Quest commands.").format(prefix=self._command_prefix)
                await send_callback(f"Unknown quest action: '{subcommand}'. Usage:\n{doc}")
        except Exception as e:
            print(f"CommandRouter: Error in handle_quest '{subcommand}': {e}\n{traceback.format_exc()}")
            await send_callback(f"An error occurred processing quest command.")

    @command("npc")
    async def handle_npc(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context.get('send_to_command_channel')
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')
        channel_id = message.channel.id
        if not send_callback or not guild_id or not author_id_str:
            await (send_callback or message.channel.send)("Command prerequisites not met.")
            return

        if not args:
            doc = (getattr(self.handle_npc, '__doc__', "NPC commands.") or "NPC commands.").format(prefix=self._command_prefix)
            await send_callback(f"Please specify an NPC action. Usage:\n{doc}")
            return

        subcommand = args[0].lower()
        action_args = args[1:]
        char_manager: Optional["CharacterManager"] = context.get('character_manager')
        npc_manager: Optional["NpcManager"] = context.get('npc_manager')
        dialogue_manager: Optional["DialogueManager"] = context.get('dialogue_manager')
        if not char_manager or not npc_manager or not dialogue_manager:
            await send_callback("Error: Required systems unavailable.")
            return

        try:
            player_char = char_manager.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You need an active character. Use `{self._command_prefix}character create <name>`.")
                return
        except Exception as e:
            await send_callback(f"Error fetching character: {e}")
            return

        if subcommand == "talk":
            if not action_args:
                await send_callback(f"Usage: {self._command_prefix}npc talk <npc_id_or_name> [message]")
                return
            npc_identifier = action_args[0]
            initiator_message = " ".join(action_args[1:]) if len(action_args) > 1 else None
            target_npc = npc_manager.get_npc(guild_id, npc_identifier) or \
                         (npc_manager.get_npc_by_name(guild_id, npc_identifier) if hasattr(npc_manager, 'get_npc_by_name') else None)
            if not target_npc:
                await send_callback(f"NPC '{npc_identifier}' not found.")
                return
            
            location_manager: Optional["LocationManager"] = context.get('location_manager') # type: ignore
            if location_manager and player_char.location_id != target_npc.location_id: # type: ignore
                npc_name = getattr(target_npc, 'name', npc_identifier)
                player_loc_name = location_manager.get_location_name(guild_id, player_char.location_id) or "Unknown Location" # type: ignore
                npc_loc_name = location_manager.get_location_name(guild_id, target_npc.location_id) or "an unknown place" # type: ignore
                await send_callback(f"{npc_name} is not here. You are in {player_loc_name}, and they are in {npc_loc_name}.")
                return
                
            dialogue_template_id = getattr(target_npc, 'dialogue_template_id', 'generic_convo')
            if not dialogue_manager.get_dialogue_template(guild_id, dialogue_template_id) and \
               not dialogue_manager.get_dialogue_template(guild_id, 'generic_convo'):
                await send_callback(f"Cannot start conversation with {target_npc.name} (no dialogue).") # type: ignore
                return
            if not dialogue_manager.get_dialogue_template(guild_id, dialogue_template_id):
                dialogue_template_id = 'generic_convo'

            try:
                dialogue_id = await dialogue_manager.start_dialogue(
                    guild_id=guild_id, template_id=dialogue_template_id,
                    participant1_id=player_char.id, participant2_id=target_npc.id, # type: ignore
                    channel_id=channel_id, initiator_message=initiator_message, **context
                )
                if not dialogue_id: await send_callback(f"Could not start conversation with {target_npc.name}.") # type: ignore
            except Exception as e:
                print(f"CommandRouter: Error in NPC talk: {e}\n{traceback.format_exc()}")
                await send_callback(f"Error talking to {target_npc.name}.") # type: ignore
        else:
            doc = (getattr(self.handle_npc, '__doc__', "NPC commands.") or "NPC commands.").format(prefix=self._command_prefix)
            await send_callback(f"Unknown NPC action: '{subcommand}'. Usage:\n{doc}")

    # ... (buy, craft, fight, hide, steal, use methods will be in Part 8) ...


    # ... (continuation: buy, craft, etc.) ...
    @command("buy")
    async def handle_buy(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context.get('send_to_command_channel')
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')
        if not send_callback or not guild_id or not author_id_str:
            await (send_callback or message.channel.send)("Command prerequisites not met.") # type: ignore
            return
        if not args:
            await send_callback(f"Usage: {self._command_prefix}buy <item_template_id> [quantity]")
            return
        item_template_id, quantity = args[0], int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        if quantity <= 0:
            await send_callback("Quantity must be positive.")
            return

        char_m: Optional["CharacterManager"] = context.get('character_manager')
        eco_m: Optional["EconomyManager"] = context.get('economy_manager')
        item_m: Optional["ItemManager"] = context.get('item_manager')
        if not char_m or not eco_m or not item_m:
            await send_callback("Required systems unavailable.")
            return

        try:
            player_char = char_m.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You need an active character (`{self._command_prefix}character create <name>`).")
                return
            if not player_char.location_id:
                await send_callback("You are not in a location to buy items.")
                return
            
            created_ids = await eco_m.buy_item(
                guild_id, player_char.id, "Character", player_char.location_id,
                item_template_id, quantity, **context
            )
            # Item templates are global, so guild_id might not be needed for get_item_template
            item_tpl_data = item_m.get_item_template(item_template_id) 
            name = item_tpl_data.get('name', item_template_id) if item_tpl_data else item_template_id

            if created_ids:
                await send_callback(f"🛍️ Bought {len(created_ids)}x {name}." if len(created_ids) == quantity else f"🛍️ Managed to buy {len(created_ids)}x {name}.")
            else:
                await send_callback(f"Could not buy {name}. Out of stock or insufficient funds?")
        except Exception as e:
            print(f"CommandRouter: Error in handle_buy: {e}\n{traceback.format_exc()}")
            await send_callback("Error during purchase.")


    @command("craft")
    async def handle_craft(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context.get('send_to_command_channel')
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')
        if not send_callback or not guild_id or not author_id_str:
            await (send_callback or message.channel.send)("Command prerequisites not met.") # type: ignore
            return
        if not args:
            await send_callback(f"Usage: {self._command_prefix}craft <recipe_id> [quantity]")
            return
        recipe_id, quantity = args[0], int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        if quantity <= 0:
            await send_callback("Quantity must be positive.")
            return

        char_m: Optional["CharacterManager"] = context.get('character_manager')
        craft_m: Optional["CraftingManager"] = context.get('crafting_manager')
        if not char_m or not craft_m:
            await send_callback("Required systems unavailable.")
            return
        try:
            player_char = char_m.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You need an active character (`{self._command_prefix}character create <name>`).")
                return
            result = await craft_m.add_recipe_to_craft_queue(
                guild_id, player_char.id, "Character", recipe_id, quantity, context
            )
            await send_callback(f"🛠️ {result.get('message', 'Crafting started!')}" if result and result.get("success") else f"⚠️ {result.get('message', 'Could not start crafting.')}")
        except Exception as e:
            print(f"CommandRouter: Error in handle_craft: {e}\n{traceback.format_exc()}")
            await send_callback("Error during crafting.")

    @command("fight")
    async def handle_fight(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context.get('send_to_command_channel')
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')
        channel_id = message.channel.id
        if not send_callback or not guild_id or not author_id_str:
             await (send_callback or message.channel.send)("Command prerequisites not met.") # type: ignore
             return
        if not args:
            await send_callback(f"Usage: {self._command_prefix}fight <target_npc_id_or_name>")
            return
        
        target_identifier = args[0]
        char_m: Optional["CharacterManager"] = context.get('character_manager')
        npc_m: Optional["NpcManager"] = context.get('npc_manager')
        loc_m: Optional["LocationManager"] = context.get('location_manager')
        combat_m: Optional["CombatManager"] = context.get('combat_manager')
        if not char_m or not npc_m or not loc_m or not combat_m:
            await send_callback("Required systems unavailable for combat.")
            return

        try:
            player_char = char_m.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char or not player_char.location_id: # type: ignore
                await send_callback("Your character is not ready for combat (no character or location).")
                return

            target_npc = npc_m.get_npc(guild_id, target_identifier) or \
                         (npc_m.get_npc_by_name(guild_id, target_identifier) if hasattr(npc_m, 'get_npc_by_name') else None)
            if not target_npc:
                await send_callback(f"NPC '{target_identifier}' not found.")
                return
            
            if target_npc.location_id != player_char.location_id: # type: ignore
                await send_callback(f"{target_npc.name} is not here.") # type: ignore
                return
            if combat_m.get_combat_by_participant_id(guild_id, player_char.id) or \
               combat_m.get_combat_by_participant_id(guild_id, target_npc.id): # type: ignore
                await send_callback("One of the participants is already in combat.")
                return

            combat_instance = await combat_m.start_combat(
                guild_id, player_char.location_id, [(player_char.id, "Character"), (target_npc.id, "NPC")], channel_id, **context # type: ignore
            )
            if not combat_instance: await send_callback(f"Could not start combat with {target_npc.name}.") # type: ignore
            # start_combat should send its own confirmation.
        except Exception as e:
            print(f"CommandRouter: Error in handle_fight: {e}\n{traceback.format_exc()}")
            await send_callback("Error initiating combat.")

    # ... (hide, steal, use methods will be in Part 9) ...


    # ... (continuation: hide, steal, use) ...
    @command("hide")
    async def handle_hide(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context.get('send_to_command_channel')
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')
        if not send_callback or not guild_id or not author_id_str:
            await (send_callback or message.channel.send)("Command prerequisites not met.") # type: ignore
            return

        char_m: Optional["CharacterManager"] = context.get('character_manager')
        char_ap: Optional["CharacterActionProcessor"] = context.get('character_action_processor')
        if not char_m or not char_ap:
            await send_callback("Required systems unavailable.")
            return
        try:
            player_char = char_m.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You need an active character (`{self._command_prefix}character create <name>`).")
                return
            if not await char_ap.process_hide_action(player_char.id, context):
                await send_callback("Could not attempt to hide now.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_hide: {e}\n{traceback.format_exc()}")
            await send_callback("Error trying to hide.")

    @command("steal")
    async def handle_steal(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context.get('send_to_command_channel')
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')
        if not send_callback or not guild_id or not author_id_str:
            await (send_callback or message.channel.send)("Command prerequisites not met.") # type: ignore
            return
        if not args:
            await send_callback(f"Usage: {self._command_prefix}steal <target_npc_id_or_name>")
            return

        target_identifier = args[0]
        char_m: Optional["CharacterManager"] = context.get('character_manager')
        npc_m: Optional["NpcManager"] = context.get('npc_manager')
        char_ap: Optional["CharacterActionProcessor"] = context.get('character_action_processor')
        # loc_m: Optional["LocationManager"] = context.get('location_manager') # Not strictly needed if NPCs have location_id

        if not char_m or not npc_m or not char_ap:
            await send_callback("Required systems unavailable.")
            return

        try:
            player_char = char_m.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You need an active character (`{self._command_prefix}character create <name>`).")
                return

            target_npc = npc_m.get_npc(guild_id, target_identifier) or \
                         (npc_m.get_npc_by_name(guild_id, target_identifier) if hasattr(npc_m, 'get_npc_by_name') else None)
            if not target_npc:
                await send_callback(f"NPC '{target_identifier}' not found.")
                return
            if player_char.location_id != target_npc.location_id: # type: ignore
                await send_callback(f"{target_npc.name} is not here.") # type: ignore
                return
            if not await char_ap.process_steal_action(player_char.id, target_npc.id, "NPC", context): # type: ignore
                await send_callback(f"Could not attempt to steal from {target_npc.name}.") # type: ignore
        except Exception as e:
            print(f"CommandRouter: Error in handle_steal: {e}\n{traceback.format_exc()}")
            await send_callback("Error during steal attempt.")

    @command("use")
    async def handle_use(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        send_callback = context.get('send_to_command_channel')
        guild_id = context.get('guild_id')
        author_id_str = context.get('author_id')
        if not send_callback or not guild_id or not author_id_str:
            await (send_callback or message.channel.send)("Command prerequisites not met.") # type: ignore
            return
        if not args:
            await send_callback(f"Usage: {self._command_prefix}use <item_instance_id> [target_id]")
            return

        item_instance_id = args[0]
        target_id: Optional[str] = args[1] if len(args) > 1 else None
        target_type: Optional[str] = None

        char_m: Optional["CharacterManager"] = context.get('character_manager')
        npc_m: Optional["NpcManager"] = context.get('npc_manager')
        char_ap: Optional["CharacterActionProcessor"] = context.get('character_action_processor')
        if not char_m or not npc_m or not char_ap:
            await send_callback("Required systems unavailable.")
            return

        try:
            player_char = char_m.get_character_by_discord_id(guild_id, int(author_id_str))
            if not player_char:
                await send_callback(f"You need an active character (`{self._command_prefix}character create <name>`).")
                return

            character_id = player_char.id
            if target_id:
                if target_id.lower() == "self" or target_id == character_id:
                    target_id, target_type = character_id, "Character"
                elif npc_m.get_npc(guild_id, target_id): target_type = "NPC"
                elif char_m.get_character(guild_id, target_id): target_type = "Character"

            if not await char_ap.process_use_item_action(
                character_id, item_instance_id, target_id, target_type, context
            ):
                await send_callback(f"Could not use item '{item_instance_id}'.")
        except Exception as e:
            print(f"CommandRouter: Error in handle_use: {e}\n{traceback.format_exc()}")
            await send_callback("Error using item.")

def is_uuid_format(s: str) -> bool:
     if not isinstance(s, str): return False
     try:
          uuid.UUID(s)
          return True
     except ValueError:
          return False

print("DEBUG: command_router.py module loaded.")
