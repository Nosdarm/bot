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


if TYPE_CHECKING:
    # --- Imports for Type Checking ---
    # Discord types used in method signatures or context
    from discord import Message # Already imported above, but good to list here for completeness if needed
    # from discord import Guild # Example if guild object is passed in context
    from discord import Client # If client is passed in context or needs type hint

    # Models (needed for type hints or isinstance checks if they cause cycles elsewhere)
    from bot.game.models.character import Character
    from bot.game.models.party import Party # <--- УБЕДИТЕСЬ, ЧТО ЭТА СТРОКА РАСКОММЕНТИРОВАНА! Needed for "Party" type hint

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
    # Добавляем другие менеджеры, которые могут быть в context kwargs
    # from bot.game.managers.dialogue_manager import DialogueManager


    # Processors (use string literals)
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.party_processors.party_action_processor import PartyActionProcessor
    # Добавляем другие процессоры, которые могут быть в context kwargs
    # from bot.game.npc_processors.npc_action_processor import NpcActionProcessor
    # from bot.game.location_processors.location_view_service import LocationViewService # if you have one
    # from bot.game.party_processors.party_view_service import PartyViewService # if you have one for party info


# Define Type Aliases for callbacks explicitly if used in type hints
SendToChannelCallback = Callable[..., Awaitable[Any]] # Represents a function like ctx.send or channel.send
SendCallbackFactory = Callable[[int], SendToChannelCallback] # Represents the factory that takes channel ID and returns a send callback


# --- Command Decorator ---
_command_registry: Dict[str, Callable[..., Awaitable[Any]]] = {} # Global command registry

def command(keyword: str) -> Callable:
    """Decorator to register a method as a command handler."""
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        # Store the function in the registry using the keyword
        # Commands are case-insensitive, store lowercase keyword
        _command_registry[keyword.lower()] = func
        print(f"DEBUG: Command '{keyword}' registered to {func.__name__}")
        return func
    return decorator

# --- CommandRouter Class ---
class CommandRouter:
    _command_handlers: ClassVar[Dict[str, Callable[..., Awaitable[Any]]]] = _command_registry


    def __init__(
        self,
        # --- Required Dependencies ---
        character_manager: "CharacterManager",
        event_manager: "EventManager",
        persistence_manager: "PersistenceManager",
        settings: Dict[str, Any],
        world_simulation_processor: "WorldSimulationProcessor",
        send_callback_factory: SendCallbackFactory, # This should be the factory function, not a callback
        character_action_processor: "CharacterActionProcessor",
        character_view_service: "CharacterViewService",
        location_manager: "LocationManager",
        rule_engine: "RuleEngine",

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
        party_action_processor: Optional["PartyActionProcessor"] = None,
        event_action_processor: Optional["EventActionProcessor"] = None,
        event_stage_processor: Optional["EventStageProcessor"] = None,
        # TODO: Add DialogueManager etc. here if they are injected dependencies
        # dialogue_manager: Optional["DialogueManager"] = None,

        # Add View Services that might be called by Command Router directly
        # party_view_service: Optional["PartyViewService"] = None, # If you have one
        # location_view_service: Optional["LocationViewService"] = None, # If you have one

    ):
        print("Initializing CommandRouter...")
        # Store all injected dependencies
        self._character_manager = character_manager
        self._event_manager = event_manager
        self._persistence_manager = persistence_manager
        self._settings = settings
        self._world_simulation_processor = world_simulation_processor
        self._send_callback_factory = send_callback_factory # Store the factory
        self._character_action_processor = character_action_processor
        self._character_view_service = character_view_service
        self._location_manager = location_manager
        self._rule_engine = rule_engine

        # Store optional dependencies
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
        self._event_stage_processor = event_stage_processor # Assuming event_stage_processor might be optional

        # Store View Services
        # self._party_view_service = party_view_service
        # self._location_view_service = location_view_service


        # Get command prefix from settings, default to '/'
        self._command_prefix: str = self._settings.get('command_prefix', '/')
        if not isinstance(self._command_prefix, str) or not self._command_prefix:
            print(f"CommandRouter Warning: Invalid command prefix in settings: '{self._settings.get('command_prefix')}'. Defaulting to '/'.")
            self._command_prefix = '/'


        print("CommandRouter initialized.")

    async def route(self, message: Message) -> None:
        """Routes a Discord message to the appropriate command handler."""
        # Ignore messages without content or that don't start with the prefix
        if not message.content or not message.content.startswith(self._command_prefix):
            return
        # Ignore messages from bots
        if message.author.bot:
             return


        try:
            command_line = message.content[len(self._command_prefix):].strip()
            if not command_line:
                 # Ignore just the prefix (e.g. sending '/')
                 return

            split_command = shlex.split(command_line)
            if not split_command: # Should not happen if command_line is not empty, but safety check
                return

            command_keyword = split_command[0].lower() # Command keyword is case-insensitive
            command_args = split_command[1:] # Remaining parts are arguments

        except Exception as e:
            print(f"CommandRouter Error: Failed to parse command '{message.content}': {e}")
            import traceback
            traceback.print_exc()
            try:
                 send_callback = self._send_callback_factory(message.channel.id)
                 await send_callback(f"❌ Ошибка при разборе команды: {e}")
            except Exception as cb_e:
                 print(f"CommandRouter Error sending parsing error message: {cb_e}")
            return


        print(f"CommandRouter: Routing command '{command_keyword}' with args {command_args} from user {message.author.id} in guild {message.guild.id if message.guild else 'DM'}.")

        # Find the corresponding handler
        handler = self.__class__._command_handlers.get(command_keyword)

        if not handler:
            print(f"CommandRouter: Unknown command: '{command_keyword}'.")
            try:
                 send_callback = self._send_callback_factory(message.channel.id)
                 await send_callback(f"❓ Неизвестная команда: `{self._command_prefix}{command_keyword}`. Используйте `{self._command_prefix}help` для просмотра доступных команд.")
            except Exception as cb_e:
                 print(f"CommandRouter Error sending unknown command message: {cb_e}")
            return

        # --- Build Context for the Handler ---
        # This dictionary provides handlers access to all managers and message details
        # Collect *all* manager attributes from self, so handlers get consistent access
        managers_in_context = {
            'character_manager': self._character_manager,
            'event_manager': self._event_manager,
            'persistence_manager': self._persistence_manager,
            'settings': self._settings, # Keep settings directly
            'world_simulation_processor': self._world_simulation_processor,
            'send_callback_factory': self._send_callback_factory, # Pass the factory
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
            # TODO: Add other optional managers like self._dialogue_manager
            # 'dialogue_manager': self._dialogue_manager,
            # Add view services if stored as attributes
            # 'party_view_service': self._party_view_service,
            # 'location_view_service': self._location_view_service,
        }


        context: Dict[str, Any] = {
            'message': message,
            'author_id': str(message.author.id),
            'guild_id': str(message.guild.id) if message.guild else None,
            'channel_id': message.channel.id,
            'command_keyword': command_keyword,
            'command_args': command_args,

            # Add SendCallback for the current channel for convenience
            'send_to_command_channel': self._send_callback_factory(message.channel.id),

            # Add all managers/processors gathered above
            **managers_in_context # Expand the dictionary here
        }

        # --- Execute the handler ---
        try:
            await handler(self, message, command_args, context)
            # print(f"CommandRouter: Command '{command_keyword}' handled successfully for guild {context.get('guild_id')} in channel {context.get('channel_id')}.") # Handlers should log success


        except Exception as e:
            print(f"CommandRouter ❌ Error executing command '{command_keyword}' for guild {context.get('guild_id')} in channel {context.get('channel_id')}: {e}")
            import traceback
            traceback.print_exc()
            # Notify user about execution error using the channel-specific callback from context
            send_callback = context.get('send_to_command_channel') # Use the callback from context
            if send_callback:
                 try:
                      # Ensure the error message content is never empty or None
                      error_message_content = f"❌ Произошла ошибка при выполнении команды `{self._command_prefix}{command_keyword}`."
                      if e: # Add exception details if available
                          error_message_content += f" Подробности: {e}"
                      # Truncate if necessary to fit Discord limits (though HTTPException usually isn't that long)
                      max_len = 2000 # Discord message limit
                      if len(error_message_content) > max_len:
                           error_message_content = error_message_content[:max_len-3] + "..."

                      await send_callback(error_message_content)
                 except Exception as cb_e:
                      print(f"CommandRouter Error sending execution error message: {cb_e}")
            else:
                 print(f"CommandRouter Error: Could not get send_to_command_channel callback for error reporting.")


    # --- Command Handler Methods ---

    @command("help")
    async def handle_help(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает список доступных команд или помощь по конкретной команде."""
        send_callback = context['send_to_command_channel'] # Use the callback from context
        command_prefix = self._command_prefix

        if not args:
            command_list = sorted(self.__class__._command_handlers.keys())
            help_message = f"Доступные команды (префикс `{command_prefix}`):\n"
            help_message += ", ".join([f"`{cmd}`" for cmd in command_list])
            help_message += f"\nИспользуйте `{command_prefix}help <команда>` для подробностей."
            await send_callback(help_message)
        else:
            target_command = args[0].lower()
            handler = self.__class__._command_handlers.get(target_command)
            if handler:
                docstring = handler.__doc__ or "Нет описания для этой команды."
                # Отформатировать docstring, если он содержит {prefix}
                if docstring and isinstance(docstring, str) and '{prefix}' in docstring:
                     docstring = docstring.format(prefix=self._command_prefix)
                # Check if docstring is still valid after formatting
                if not docstring:
                     docstring = f"Нет описания для команды `{self._command_prefix}{target_command}`." # Fallback if formatting results in empty string or None

                await send_callback(docstring)
            else:
                await send_callback(f"❓ Команда `{self._command_prefix}{target_command}` не найдена.") # Format prefix in feedback
        print(f"CommandRouter: Processed help command for guild {context.get('guild_id')}.")


    @command("character") # Handler for "/character" commands
    async def handle_character(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        Управляет персонажами (создание, удаление, etc.).
        Использование:
        `{prefix}character create <имя_персонажа>` - Создать нового персонажа.
        `{prefix}character delete [<ID персонажа>]` - Удалить персонажа (по умолчанию своего).
        (И другие, если реализованы)
        """.format(prefix=self._command_prefix) # Format docstring here

        send_callback = context['send_to_command_channel'] # Use the callback from context
        guild_id = context.get('guild_id') # Use get for safety, although it should exist for guild commands
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Команды персонажа доступны только на сервере.")
            return

        if not args:
            # Отформатировать docstring перед отправкой
            help_message = self.handle_character.__doc__
            if isinstance(help_message, str):
                 help_message = help_message.format(prefix=self._command_prefix)
                 if not help_message: # Ensure not empty after formatting
                      help_message = "Описание команды 'character' недоступно." # Fallback
                 await send_callback(help_message)
            else:
                 await send_callback("Описание команды 'character' недоступно.") # Fallback if docstring is None/not a string
                 print(f"CommandRouter Warning: docstring is missing or not a string for handle_character.")

            return

        subcommand = args[0].lower()
        subcommand_args = args[1:]

        char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
        # Need other managers for specific subcommands, get them within the subcommand blocks
        # char_view_service = context.get('character_view_service')
        # char_action_processor = context.get('character_action_processor')

        # Central check for essential manager for character commands
        if not char_manager:
             await send_callback("❌ Система персонажей временно недоступна.")
             print(f"CommandRouter Error: character_manager is None in handle_character for guild {guild_id}.")
             return

        # --- Handle Subcommands ---

        if subcommand == "create":
            # Handle /character create <name>
            if not subcommand_args:
                await send_callback(f"Использование: `{self._command_prefix}character create <имя_персонажа>`")
                return

            character_name = subcommand_args[0]

            # Validate character name constraints here before calling manager if needed (length, symbols etc.)
            # Example basic check:
            if len(character_name) < 2 or len(character_name) > 30: # Name length constraint
                await send_callback("❌ Имя персонажа должно быть от 2 до 30 символов.")
                return
            # Add other checks (e.g. invalid characters)

            try:
                author_id_int: Optional[int] = None
                try:
                    if author_id is not None: author_id_int = int(author_id)
                except (ValueError, TypeError):
                    await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
                    print(f"CommandRouter Error: Invalid author_id format: {author_id}")
                    return

                if author_id_int is None:
                     await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
                     print(f"CommandRouter Error: author_id is None.")
                     return

                # CharacterManager.create_character needs discord_id (int), name (str), guild_id (str), **kwargs
                # Pass context dictionary which includes guild_id and other managers
                new_character = await char_manager.create_character(
                    discord_id=author_id_int,
                    name=character_name,
                    **context # Pass entire context dictionary (includes other managers etc.)
                )

                if new_character:
                    # Get name and ID from the returned character object, defaulting if None
                    char_name = getattr(new_character, 'name', character_name)
                    char_id = getattr(new_character, 'id', 'N/A')
                    await send_callback(f"✨ Ваш персонаж **{char_name}** успешно создан! (ID: `{char_id}`).") # Use Ваш for user's char
                    print(f"CommandRouter: Character '{char_name}' (ID: {char_id}) created for user {author_id_int} in guild {guild_id}.")
                else:
                    # Creation failed (e.g., name taken, already has a char) - Manager should print detailed reason
                    # Manager returns None if character already exists for user/name taken in guild.
                    await send_callback(f"❌ Не удалось создать персонажа **{character_name}**. Возможно, имя занято или у вас уже есть персонаж в этой гильдии.")
                    # Manager should log the specific reason

            except ValueError as ve: # Catch specific validation errors from manager
                 await send_callback(f"❌ Ошибка создания персонажа: {ve}")
                 print(f"CommandRouter Error: Validation error creating character: {ve} for user {author_id} in guild {guild_id}.")
            except Exception as e:
                print(f"CommandRouter Error creating character for user {author_id} in guild {guild_id}: {e}")
                import traceback
                traceback.print_exc()
                await send_callback(f"❌ Произошла ошибка при создании персонажа: {e}")

        elif subcommand == "delete":
             # Handle /character delete [<ID персонажа>]
             # If argument is provided, attempt to find character by ID. If no argument, delete user's own character.
             # Optional: Add search by name if argument is not a UUID.
             # For now, support deletion by ID (arg) OR by user's Discord ID (no arg).

             char_id_or_name_to_find: Optional[str] = None # For user feedback/logging
             char_id_to_delete: Optional[str] = None # The actual character ID (UUID) to pass to manager
             target_char: Optional["Character"] = None # The character object to delete

             if subcommand_args:
                  # If argument is provided, assume it's a character ID
                  char_id_or_name_to_find = subcommand_args[0]
                  # Attempt to get character object by this ID and guild_id
                  target_char = char_manager.get_character(guild_id, char_id_or_name_to_find)

                  # TODO: Optional: Implement getting char by name for deletion if arg is not UUID-like and not found by ID.
                  # Need a helper function is_uuid_format(string)
                  # if not target_char and char_id_or_name_to_find and isinstance(char_id_or_name_to_find, str) and not is_uuid_format(char_id_or_name_to_find): # Вам нужна is_uuid_format функция
                  #     target_char = char_manager.get_character_by_name(guild_id, char_id_or_name_to_find)
                  #     if target_char:
                  #          print(f"CommandRouter: Found character '{char_id_or_name_to_find}' by name for deletion (ID: {target_char.id}) in guild {guild_id}.")


                  if not target_char:
                       # If not found by ID (and no name search), report failure.
                       await send_callback(f"❌ Персонаж с ID `{char_id_or_name_to_find}` не найден в этой гильдии.")
                       return # Exit if character not found by ID/name

                  char_id_to_delete = getattr(target_char, 'id', None) # Get the actual ID from the object


             else:
                  # If no argument, delete the command author's character in this guild
                  author_id_int: Optional[int] = None
                  try:
                      if author_id is not None: author_id_int = int(author_id)
                  except (ValueError, TypeError):
                       await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
                       print(f"CommandRouter Error: Invalid author_id format: {author_id}")
                       return

                  if author_id_int is None:
                       await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
                       print(f"CommandRouter Error: author_id is None.")
                       return

                  # Get user's character object by Discord ID and guild_id
                  target_char = char_manager.get_character_by_discord_id(guild_id, author_id_int)

                  if not target_char:
                     await send_callback(f"❌ У вас еще нет персонажа, которого можно было бы удалить в этой гильдии.")
                     return # Cannot delete if no character

                  char_id_to_delete = getattr(target_char, 'id', None) # Get the actual ID from the object
                  char_id_or_name_to_find = char_id_to_delete # For logging purposes


             # At this point, target_char is the character object to be deleted, and char_id_to_delete is its ID.
             if target_char is None or char_id_to_delete is None: # Double check existence and ID
                  await send_callback("❌ Произошла ошибка при определении персонажа для удаления.")
                  return


             # Check if the user has permission to delete this character (assumes owner only for now)
             author_id_int_check: Optional[int] = None
             try:
                 if author_id is not None: author_id_int_check = int(author_id)
             except (ValueError, TypeError): pass # Already handled above, but defensive

             # Compare Discord ID of the character's owner with the command author's Discord ID
             # Also, add a check for GM/Admin role if GMs should be able to delete any character
             # is_gm = ... check GM role in Discord context? Check is_bot_admin in settings based on author_id?
             is_gm = False # Placeholder for GM check
             # Example GM check based on settings and author_id:
             settings_data = context.get('settings', {})
             if settings_data and isinstance(settings_data, dict): # Ensure settings_data is a dictionary
                  admin_users = set(map(str, settings_data.get('bot_admins', []))) # Assuming bot_admins is a list of user IDs in settings
                  if author_id in admin_users:
                       is_gm = True # Consider bot admins as GMs for this purpose


             # Permission check: Must be the owner OR a GM/Admin
             if not is_gm and getattr(target_char, 'discord_user_id', None) != author_id_int_check:
                  await send_callback("❌ Вы можете удалить только своего персонажа (или обратитесь к GM).")
                  return


             # Now call the manager's remove_character method using the found target_char's actual ID
             try:
                 print(f"CommandRouter: Attempting to delete character {char_id_to_delete} ({getattr(target_char, 'name', 'N/A')}) by user {author_id} (is_gm: {is_gm}) in guild {guild_id}...")
                 # remove_character needs character_id (str), guild_id (str), **kwargs
                 deleted_char_id = await char_manager.remove_character(
                     character_id=char_id_to_delete, # Use the actual char ID
                     guild_id=guild_id, # Pass guild_id explicitly as remove_character signature expects it
                     **context # Pass rest of context
                 )

                 if deleted_char_id:
                     char_name = getattr(target_char, 'name', 'персонаж')
                     # Confirmation message uses the original name and ID
                     await send_callback(f"🗑️ Персонаж **{char_name}** (ID: `{deleted_char_id}`) успешно удален.")
                     print(f"CommandRouter: Character {deleted_char_id} ({char_name}) deleted by user {author_id} in guild {guild_id}.")
                 else:
                     # remove_character should handle detailed logging if it fails internally,
                     # but we provide a generic user feedback here.
                     print(f"CommandRouter: Warning: char_manager.remove_character returned None for {char_id_to_delete} in guild {guild_id}. Check manager logs for details.")
                     await send_callback(f"❌ Не удалось удалить персонажа `{char_id_or_name_to_find}`.")


             except Exception as e:
                 print(f"CommandRouter Error deleting character {char_id_or_name_to_find} for user {author_id} in guild {guild_id}: {e}")
                 import traceback
                 traceback.print_exc()
                 await send_callback(f"❌ Произошла ошибка при удалении персонажа: {e}")


        # Add other subcommands for "character" here if needed (rename, etc.)
        # elif subcommand == "rename": ...
        # elif subcommand == "equip": ...
        # elif subcommand == "use": ...


        else:
            # Unknown subcommand for /character
            # Отформатировать сообщение перед отправкой
            usage_message = f"Неизвестное действие для персонажа: `{subcommand}`. Доступные действия: `create`, `delete` (и другие, если реализованы).\nИспользование: `{self._command_prefix}character <действие> [аргументы]`"
            if isinstance(usage_message, str): # Safety check although f-string is str
                 usage_message = usage_message.format(prefix=self._command_prefix) # Format usage
            await send_callback(usage_message)
            print(f"CommandRouter: Unknown character subcommand: '{subcommand}' in guild {guild_id}.")


    # --- Implement Status as a TOP-LEVEL command ---
    @command("status") # Handler for "/status"
    async def handle_status(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает лист персонажа (статы, инвентарь, состояние). Использование: `[<ID персонажа>]`"""
        # Changed docstring slightly to reflect it's more than just stats, but the whole sheet
        send_callback = context['send_to_command_channel'] # Use the callback from context
        guild_id = context.get('guild_id')
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        char_id_to_view: Optional[str] = None
        target_char: Optional["Character"] = None

        char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
        char_view_service = context.get('character_view_service') # Type: Optional["CharacterViewService"]

        if not char_manager or not char_view_service:
             await send_callback("❌ Система персонажей или просмотра временно недоступна.")
             print(f"CommandRouter Error: character_manager or character_view_service is None in status handler for guild {guild_id}.")
             return

        if args:
            # If args are provided, assume the first one is a character ID
            char_id_to_view = args[0]
            # Assuming get_character signature is get_character(guild_id: str, character_id: str)
            target_char = char_manager.get_character(guild_id, char_id_to_view)

            if not target_char:
                 await send_callback(f"❌ Персонаж с ID `{char_id_to_view}` не найден в этой гильдии.")
                 return
        else:
            # If no args, try to get the player's own character by Discord ID
            author_id_int: Optional[int] = None
            try:
                if author_id is not None: author_id_int = int(author_id)
            except (ValueError, TypeError):
                 await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
                 print(f"CommandRouter Error: Invalid author_id format: {author_id}")
                 return

            if author_id_int is None:
                 await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
                 print(f"CommandRouter Error: author_id is None.")
                 return

            # Assuming get_character_by_discord_id signature is get_character_by_discord_id(guild_id: str, discord_user_id: int)
            player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int)
            if player_char:
                target_char = player_char
            else:
                await send_callback(f"❌ У вас еще нет персонажа. Создайте его командой `{self._command_prefix}character create <имя>`")
                return

        if target_char is None:
             await send_callback("❌ Не удалось определить, чей лист показать.") # Changed feedback slightly
             return

        try:
            # Calling get_character_sheet_embed as intended for the full sheet view.
            # Ensure your CharacterViewService has this method and it returns a discord.Embed or similar.
            sheet_embed = await char_view_service.get_character_sheet_embed(target_char, context=context)


            if sheet_embed: # Check if method returned something usable (like discord.Embed)
                 await send_callback(embed=sheet_embed) # Send the embed
                 print(f"CommandRouter: Sent character sheet embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")
            else:
                 # Feedback if embed generation failed (e.g., returned None)
                 print(f"CommandRouter: Failed to generate character sheet embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}. CharacterViewService returned None or invalid.")
                 await send_callback(f"❌ Не удалось сгенерировать лист персонажа **{getattr(target_char, 'name', 'N/A')}**. Проверьте логи бота.")


        except Exception as e:
            print(f"CommandRouter Error generating character sheet embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при получении листа персонажа: {e}")


    # --- Implement Inventory as a TOP-LEVEL command ---
    @command("inventory") # Handler for "/inventory"
    async def handle_inventory(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает инвентарь вашего персонажа. Используйте: `[<ID персонажа>]`"""
        send_callback = context['send_to_command_channel'] # Use the callback from context
        guild_id = context.get('guild_id')
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        char_id_to_view: Optional[str] = None
        target_char: Optional["Character"] = None

        char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
        char_view_service = context.get('character_view_service') # Type: Optional["CharacterViewService"]

        if not char_manager or not char_view_service:
             await send_callback("❌ Система персонажей или просмотра временно недоступна.")
             print(f"CommandRouter Error: character_manager or character_view_service is None in inventory handler for guild {guild_id}.")
             return

        if args:
            char_id_to_view = args[0]
            target_char = char_manager.get_character(guild_id, char_id_to_view)

            if not target_char:
                 await send_callback(f"❌ Персонаж с ID `{char_id_to_view}` не найден в этой гильдии.")
                 return
        else:
            author_id_int: Optional[int] = None
            try:
                if author_id is not None: author_id_int = int(author_id)
            except (ValueError, TypeError):
                 await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
                 print(f"CommandRouter Error: Invalid author_id format: {author_id}")
                 return

            if author_id_int is None:
                 await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
                 print(f"CommandRouter Error: author_id is None.")
                 return

            player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int)
            if player_char:
                target_char = player_char
            else:
                await send_callback(f"❌ У вас еще нет персонажа. Создайте его командой `{self._command_prefix}character create <имя>`")
                return

        if target_char is None:
             await send_callback("❌ Не удалось определить, чей инвентарь показать.")
             return

        try:
            # Call get_inventory_embed directly from CharacterViewService
            inventory_embed = await char_view_service.get_inventory_embed(target_char, context=context) # Pass context dict

            if inventory_embed: # Check if method returned something usable
                 await send_callback(embed=inventory_embed) # Send the embed
                 print(f"CommandRouter: Sent inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")
            else:
                 # Provide feedback even if embed is None
                 print(f"CommandRouter: Failed to generate inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}. CharacterViewService returned None or invalid.")
                 # Provide user feedback indicating failure to generate the embed
                 await send_callback(f"❌ Не удалось сгенерировать инвентарь для персонажа **{getattr(target_char, 'name', 'N/A')}**. Проверьте логи бота.")


        except Exception as e:
            print(f"CommandRouter Error generating inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при получении инвентаря: {e}")


    # --- Implement Move as a TOP-LEVEL command ---
    @command("move") # Handler for "/move"
    async def handle_move(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Перемещает вашего персонажа в указанную локацию. Использование: `<ID локации>`"""
        send_callback = context['send_to_command_channel'] # Use the callback from context
        guild_id = context.get('guild_id')
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        if not args:
            await send_callback(f"Использование: `{self._command_prefix}move <ID локации>`")
            return

        target_location_id_arg = args[0] # First argument is the target location ID (as provided by user)

        char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
        char_action_processor = context.get('character_action_processor') # Type: Optional["CharacterActionProcessor"]
        loc_manager = context.get('location_manager') # Type: Optional["LocationManager"] # Need LocationManager for validation (though processor might do it)

        if not char_manager or not char_action_processor or not loc_manager: # Check all required managers
             await send_callback("❌ Система перемещения, локаций или персонажей временно недоступна.") # Updated feedback
             print(f"CommandRouter Error: required managers/processors (char_manager, char_action_processor, loc_manager) are None in move handler for guild {guild_id}.")
             return

        # Get the player's own character by Discord ID
        author_id_int: Optional[int] = None
        try:
            if author_id is not None: author_id_int = int(author_id)
        except (ValueError, TypeError):
             await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
             print(f"CommandRouter Error: Invalid author_id format: {author_id}")
             return

        if author_id_int is None:
             await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
             print(f"CommandRouter Error: author_id is None.")
             return


        player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int)
        if not player_char:
            await send_callback("❌ У вас еще нет персонажа, которого можно перемещать.")
            return

        char_id = getattr(player_char, 'id', None) # Get character ID safely
        if char_id is None:
             print(f"CommandRouter Error: Player character object has no ID attribute for user {author_id} in guild {guild_id}.")
             await send_callback("❌ Произошла ошибка: Не удалось определить ID вашего персонажа.")
             return

        # Validate target_location_id_arg - check if it's a valid location instance ID for this guild.
        # This can be done here or in the processor. Doing it here provides earlier feedback.
        # Use LocationManager.get_location_instance (needs guild_id)
        target_location_instance = loc_manager.get_location_instance(guild_id, target_location_id_arg)
        if not target_location_instance:
             await send_callback(f"❌ Локация с ID `{target_location_id_arg}` не найдена в этой гильдии.")
             return # Location instance not found

        # TODO: Also validate if the target location is reachable from the character's current location.
        # This might require walking the exit graph using LocationManager and RuleEngine.
        # This complex validation is better done in the CharacterActionProcessor.

        try:
            # CharacterActionProcessor.process_move_action expects character_id, target_location_id (str), context
            # Processor handles validation (location exists, reachable, character is not busy)
            # Processor should send feedback messages directly to the user via context['send_to_command_channel'].
            await char_action_processor.process_move_action(
                character_id=char_id,
                target_location_id=getattr(target_location_instance, 'id', str(target_location_id_arg)), # Pass the validated ID from instance object, fallback to arg
                context=context # Pass full context dictionary (includes required managers, callbacks etc.)
            )
            # print(f"CommandRouter: Move action request processed for character {char_id} to location {target_location_id_arg} in guild {guild_id}. Processor handles feedback.") # Logging handled in processor

        except Exception as e:
            print(f"CommandRouter Error processing move command for character {char_id} to location {target_location_id_arg} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            # Generic error feedback
            await send_callback(f"❌ Произошла ошибка при попытке перемещения: {e}")


    # --- Example: Party Command (using subcommand pattern) ---
    @command("party") # Handler for "/party" commands
    async def handle_party(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
         """
         Управляет группами персонажей (пати).
         Использование:
         `{prefix}party create` - Создать новую партию (вы становитесь лидером).
         `{prefix}party join <ID партии>` - Присоединиться к существующей партии.
         `{prefix}party leave` - Покинуть текущую партию.
         `{prefix}party info [<ID партии>]` - Показать информацию о вашей партии или партии по ID.
         """.format(prefix=self._command_prefix) # Format docstring here

         send_callback = context['send_to_command_channel']
         guild_id = context.get('guild_id')
         author_id = context['author_id']

         if guild_id is None:
             await send_callback("❌ Команды партии доступны только на сервере.")
             return

         if not args:
             # Отформатировать docstring перед отправкой
             help_message = self.handle_party.__doc__
             if isinstance(help_message, str):
                 help_message = help_message.format(prefix=self._command_prefix)
                 if not help_message: # Ensure not empty after formatting
                      help_message = "Описание команды 'party' недоступно." # Fallback
                 await send_callback(help_message)
             else:
                 await send_callback("Описание команды 'party' недоступно.") # Fallback if docstring is None/not str
                 print(f"CommandRouter Warning: docstring is missing or not a string for handle_party.")
             return

         subcommand = args[0].lower()
         subcommand_args = args[1:]

         # Get managers needed for party commands
         char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
         party_manager = context.get('party_manager') # Type: Optional["PartyManager"]
         party_action_processor = context.get('party_action_processor') # Type: Optional["PartyActionProcessor"]
         # Add other managers that might be needed by party subcommands (e.g., LocationManager, CombatManager)
         # loc_manager = context.get('location_manager')
         # combat_manager = context.get('combat_manager')
         npc_manager = context.get('npc_manager') # Added npc_manager for party info fallback


         # Central check for essential managers for party commands
         if not char_manager or not party_manager or not party_action_processor: # All three seem essential for party actions
              await send_callback("❌ Система партий временно недоступна.")
              print(f"CommandRouter Error: required party managers/processors are None in handle_party for guild {guild_id}.")
              return


         # Get the player's own character (most party commands are player-initiated)
         # Need character ID for party actions
         author_id_int: Optional[int] = None
         try:
             if author_id is not None: author_id_int = int(author_id)
         except (ValueError, TypeError):
              await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
              print(f"CommandRouter Error: Invalid author_id format: {author_id}")
              return

         if author_id_int is None:
              await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
              print(f"CommandRouter Error: author_id is None.")
              return

         player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int)
         # Check for character existence only for subcommands that require a character
         # 'create' technically *could* create a party first, then assign a leader character,
         # but simpler if leader char must exist first. Let's require character for most.
         if player_char is None and subcommand not in ["help", "info"]: # Commands that might not need player char (help/info without args check char later)
              # Re-check existence below for specific subcommands that might allow no char or char ID arg.
              pass # Allow some subcommands if player_char is None

         # Get the player's character ID if character exists
         player_char_id: Optional[str] = getattr(player_char, 'id', None) if player_char else None


         # --- Handle Party Subcommands ---

         if subcommand == "create":
              # Handle /party create
              # Check if player already in a party
              if player_char_id is None: # Creating requires a character
                   await send_callback("❌ Для создания партии необходим персонаж.")
                   return # Cannot create party without character

              # Get player's current party using PartyManager.get_party_by_member_id (needs entity_id, guild_id)
              player_current_party = await party_manager.get_party_by_member_id(player_char_id, guild_id)
              if player_current_party:
                   await send_callback(f"❌ Вы уже состоите в партии (ID `{getattr(player_current_party, 'id', 'N/A')}`). Сначала покиньте ее (`{self._command_prefix}party leave`).".format(prefix=self._command_prefix)) # Format prefix in feedback
                   return

              # Create the party with the player as leader
              try:
                   # party_manager.create_party(leader_id, member_ids, guild_id, **kwargs) -> Optional[str] (returns party ID)
                   if player_char_id is None: # Create requires a character
                        await send_callback("❌ Для создания партии необходим персонаж.") # This line is unreachable due to check above
                        return

                   new_party_id = await party_manager.create_party(
                       leader_id=player_char_id,
                       member_ids=[player_char_id], # Initial member list includes leader
                       guild_id=guild_id, # Pass guild_id string
                       **context # Pass context dictionary (includes character_manager for internal use if needed)
                   )

                   if new_party_id:
                        # Also update character's party_id via CharacterManager
                        if char_manager and hasattr(char_manager, 'set_party_id'):
                            # set_party_id needs guild_id, character_id, party_id, **kwargs
                            # It marks character dirty.
                            await char_manager.set_party_id(
                                guild_id=guild_id, # Pass guild_id string
                                character_id=player_char_id,
                                party_id=new_party_id,
                                **context # Pass context
                            )
                            # set_party_id logs internally, no need for redundant log here

                        await send_callback(f"🎉 Вы успешно создали новую партию! ID партии: `{new_party_id}`")
                        print(f"CommandRouter: Party {new_party_id} created by user {author_id} (char {player_char_id}) in guild {guild_id}.")

                   else:
                        # PartyManager failed to create party (it should log reason internally)
                        await send_callback("❌ Не удалось создать партию. Возможно, произошла внутренняя ошибка.") # More generic feedback
                        print(f"CommandRouter: party_manager.create_party returned None for user {author_id} (char {player_char_id}) in guild {guild_id}.")

              except Exception as e:
                   print(f"CommandRouter Error creating party for user {author_id} (char {player_char_id}) in guild {guild_id}: {e}")
                   import traceback
                   traceback.print_exc()
                   await send_callback(f"❌ Произошла ошибка при создании партии: {e}")


         elif subcommand == "join":
              # Handle /party join <ID партии>
              if not subcommand_args:
                   await send_callback(f"Использование: `{self._command_prefix}party join <ID партии>`".format(prefix=self._command_prefix))
                   return
              if player_char_id is None: # Joining requires a character
                  await send_callback("❌ Для присоединения к партии необходим персонаж.")
                  return

              target_party_id_arg = subcommand_args[0] # The potential party ID provided by the user

              # Check if party exists with PartyManager.get_party (needs guild_id, party_id)
              target_party = party_manager.get_party(guild_id, target_party_id_arg)
              if not target_party:
                   await send_callback(f"❌ Партия с ID `{target_party_id_arg}` не найдена в этой гильдии.")
                   return

              # Check if player is already in this or another party using PartyManager.get_party_by_member_id (needs entity_id, guild_id)
              player_current_party = await party_manager.get_party_by_member_id(player_char_id, guild_id)
              if player_current_party:
                   # Compare actual party IDs from objects
                   if getattr(player_current_party, 'id', None) == getattr(target_party, 'id', None):
                        await send_callback(f"❌ Вы уже состоите в этой партии (ID `{target_party_id_arg}`).")
                   else:
                        await send_callback(f"❌ Вы уже состоите в другой партии (ID `{getattr(player_current_party, 'id', 'N/A')}`). Сначала покиньте ее (`{self._command_prefix}party leave`).".format(prefix=self._command_prefix))
                   return

              # Call PartyActionProcessor to handle joining logic
              try:
                   # process_join_party needs character_id (str), party_id (str), context (Dict)
                   # Processor handles adding member to party, updating char's party_id, sending feedback.
                   join_successful = await party_action_processor.process_join_party(
                       character_id=player_char_id,
                       party_id=getattr(target_party, 'id'), # Use the actual party ID from the object
                       context=context # Pass full context (includes needed managers like CharacterManager)
                   )
                   # PartyActionProcessor should send confirmation/error messages directly via context.
                   # This method returns True on success, False on failure (e.g. party full).
                   if join_successful:
                        print(f"CommandRouter: Join party action processed successfully in processor for char {player_char_id} to party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}.")
                        # Success message is sent by processor
                   else:
                        # Processor should send reason for failure (e.g. party full, player busy)
                        print(f"CommandRouter: Join party action failed in processor for char {player_char_id} to party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}.")
                        # Error message is sent by processor


              except Exception as e:
                   print(f"CommandRouter Error joining party for char {player_char_id} to party {target_party_id_arg} in guild {guild_id}: {e}")
                   import traceback
                   traceback.print_exc()
                   await send_callback(f"❌ Произошла ошибка при присоединении к партии: {e}")


         elif subcommand == "leave":
             # Handle /party leave
             if player_char_id is None: # Player needs a character to leave a party
                 await send_callback("❌ У вас нет персонажа.") # Removed "или вы не состоите в партии" as check comes next
                 return

             # Find the player's current party using PartyManager.get_party_by_member_id (needs entity_id, guild_id)
             player_current_party = await party_manager.get_party_by_member_id(player_char_id, guild_id)
             if not player_current_party:
                  await send_callback("❌ Вы не состоите в партии.")
                  return

             # Call PartyActionProcessor to handle leaving logic
             try:
                  party_id_to_leave = getattr(player_current_party, 'id')
                  if party_id_to_leave is None:
                       print(f"CommandRouter Error: Player's party object has no ID attribute for char {player_char_id} in guild {guild_id}. Party object: {player_current_party}")
                       await send_callback("❌ Произошла ошибка: Не удалось получить ID вашей партии.")
                       return

                  # process_leave_party needs character_id (str), party_id (str), context (Dict)
                  # Processor handles removing member, updating char's party_id, checking if party is empty, sending feedback.
                  leave_successful = await party_action_processor.process_leave_party(
                      character_id=player_char_id,
                      party_id=party_id_to_leave,
                      context=context # Pass full context (includes needed managers like CharacterManager)
                  )
                  # PartyActionProcessor should send confirmation/error messages directly.
                  # This method returns True on success, False on failure.
                  if leave_successful:
                       print(f"CommandRouter: Leave party action processed successfully in processor for char {player_char_id} from party {party_id_to_leave} in guild {guild_id}.")
                       # Success message is sent by processor
                  else:
                       print(f"CommandRouter: Leave party action failed in processor for char {player_char_id} from party {party_id_to_leave} in guild {guild_id}.")
                       # Error message is sent by processor


             except Exception as e:
                   print(f"CommandRouter Error leaving party for char {player_char_id} from party {getattr(player_current_party, 'id', 'N/A')} in guild {guild_id}: {e}")
                   import traceback
                   traceback.print_exc()
                   await send_callback(f"❌ Произошла ошибка при попытке покинуть партию: {e}")


         elif subcommand == "info":
             # Handle /party info [<ID партии>]
             # If arg provided, show info for that party ID. If no arg, show info for player's party.
             target_party: Optional["Party"] = None # Use string literal Party from TYPE_CHECKING
             party_id_arg: Optional[str] = None # For feedback

             if subcommand_args:
                  # Argument provided, try to find party by ID
                  party_id_arg = subcommand_args[0]
                  target_party = party_manager.get_party(guild_id, party_id_arg) # Needs guild_id, party_id

                  if not target_party:
                       await send_callback(f"❌ Партия с ID `{party_id_arg}` не найдена в этой гильдии.")
                       return
             else:
                  # No argument, show info for player's current party
                  if player_char_id is None:
                       # Removed "или вы не состоите в партии" as check comes next
                       await send_callback(f"❌ У вас нет персонажа. Укажите ID партии для просмотра (`{self._command_prefix}party info <ID партии>`).".format(prefix=self._command_prefix))
                       return
                  # Find player's party using PartyManager.get_party_by_member_id (needs entity_id, guild_id)
                  target_party = await party_manager.get_party_by_member_id(player_char_id, guild_id)
                  if not target_party:
                       await send_callback(f"❌ Вы не состоите в партии. Укажите ID партии для просмотра (`{self._command_prefix}party info <ID партии>`).".format(prefix=self._command_prefix)) # Added prefix to usage hint
                       return
                  party_id_arg = getattr(target_party, 'id', 'N/A') # Get ID for feedback


             # At this point, target_party should be the party object.
             if target_party is None: # Redundant check
                 await send_callback("❌ Произошла ошибка при определении партии для просмотра.")
                 return

             # TODO: Call a PartyViewService method to generate party info embed
             party_view_service = context.get('party_view_service') # Type: Optional["PartyViewService"]

             if party_view_service and hasattr(party_view_service, 'get_party_info_embed'): # Check manager and method
                  try:
                      # get_party_info_embed needs Party object and context
                      party_embed = await party_view_service.get_party_info_embed(target_party, context=context)
                      if party_embed: # Check if method returned something usable
                           await send_callback(embed=party_embed) # Send the embed
                           print(f"CommandRouter: Sent party info embed for party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}.")
                      else:
                           print(f"CommandRouter: Failed to generate party info embed for party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}. PartyViewService returned None or invalid.")
                           await send_callback(f"❌ Не удалось сгенерировать информацию для партии **{getattr(target_party, 'name', 'N/A')}**. Проверьте логи бота.")

                  except Exception as e:
                       print(f"CommandRouter Error generating party info embed for party {getattr(target_party, 'id', 'N/A')} in guild {guild_id}: {e}")
                       import traceback
                       traceback.print_exc()
                       await send_callback(f"❌ Произошла ошибка при получении информации о партии: {e}")

             else: # Fallback if PartyViewService is not available
                  # Example: Using a placeholder message for now
                  party_id = getattr(target_party, 'id', 'N/A')
                  leader_id = getattr(target_party, 'leader_id', 'N/A')
                  member_ids = getattr(target_party, 'member_ids', [])
                  party_name = getattr(target_party, 'name', 'Безымянная партия')

                  member_names = []
                  if isinstance(member_ids, list) and member_ids: # Ensure member_ids is list and not empty
                       # Attempt to get character/NPC names from managers (needs managers in context)
                       char_mgr = context.get('character_manager') # Type: Optional["CharacterManager"]
                       npc_mgr = context.get('npc_manager') # Type: Optional["NpcManager"]
                       for member_id in member_ids:
                            name = str(member_id) # Default to ID string
                            if char_mgr and isinstance(member_id, str):
                                 # Need guild_id for get_character
                                 char = char_mgr.get_character(guild_id, member_id)
                                 if char: name = getattr(char, 'name', name)
                            # Only check NPC if not found as Character and member_id is string
                            if name == str(member_id) and npc_mgr and isinstance(member_id, str):
                                 # Need guild_id for get_npc
                                 npc = npc_mgr.get_npc(guild_id, member_id)
                                 if npc: name = getattr(npc, 'name', name)
                            # Truncate and format the ID for display
                            truncated_id = str(member_id)[:6] if isinstance(member_id, (str, int)) else 'N/A'
                            member_names.append(f"`{truncated_id}` ({name})")


                  info_message = f"Информация о партии **{party_name}** (ID: `{party_id}`).\n"
                  # Display truncated leader ID safely
                  truncated_leader_id = str(leader_id)[:6] if isinstance(leader_id, (str, int)) and leader_id is not None else 'Нет'
                  info_message += f"Лидер: `{truncated_leader_id}`\n"
                  info_message += f"Участники ({len(member_ids)}): " + (", ".join(member_names) if member_names else "Нет.")

                  await send_callback(info_message) # Send the plain message
                  print(f"CommandRouter: Sent fallback party info for party {party_id} in guild {guild_id}.")


         # TODO: Add other party subcommands (invite, kick, promote, disband)
         # elif subcommand == "invite": ...
         # elif subcommand == "kick": ...
         # elif subcommand == "disband": ...


         else:
              # Unknown party subcommand
              await send_callback(f"Неизвестное действие для партии: `{subcommand}`. Доступные действия: `create`, `join`, `leave`, `info`.\nИспользование: `{self._command_prefix}party <действие> [аргументы]`".format(prefix=self._command_prefix)) # Format usage in feedback
              print(f"CommandRouter: Unknown party subcommand: '{subcommand}' in guild {guild_id}.")


    # --- Example: World Command (using subcommand pattern) ---
    # This could contain commands like /world status, /world time, /world look
    # Decided to make /status, /inventory, /move top-level based on user's preference shown in logs/screenshot.
    # But other world-related actions could be here.

    # @command("world")
    # async def handle_world(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
    #      """Управляет миром (время, статус и т.e.)."""
    #      send_callback = context['send_to_command_channel']
    #      guild_id = context.get('guild_id')
    #      if guild_id is None: return await send_callback("❌ Команды мира доступны только на сервере.")
    #      if not args: return await send_callback("Использование: `{prefix}world <действие> [аргументы]`".format(prefix=self._command_prefix))
    #      subcommand = args[0].lower()
    #      subcommand_args = args[1:]
    #      # Get managers: time_manager, world_simulation_processor, rule_engine, location_manager
    #      time_mgr = context.get('time_manager')
    #      # ... get other managers ...
    #      if not time_mgr: return await send_callback("❌ Система времени недоступна.")
    #
    #      if subcommand == "time":
    #           # Handle /world time
    #           # Needs guild_id
    #           current_time = await time_mgr.get_game_time(guild_id)
    #           await send_callback(f"Игровое время в гильдии {guild_id}: {current_time:.2f}")
    #      elif subcommand == "look": # Could be here, or top level /look
    #           # Handle /world look [<location_id>] or just use player's current location
    #           # Needs LocationManager, CharacterManager (to get player location), LocationViewService
    #           char_mgr = context.get('character_manager')
    #           loc_mgr = context.get('location_manager')
    #           # Need to convert author_id to int for get_character_by_discord_id and handle potential errors
    #           author_id_int: Optional[int] = None
    #           try:
    #               if author_id is not None: author_id_int = int(author_id)
    #           except (ValueError, TypeError):
    #               await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
    #               print(f"CommandRouter Error: Invalid author_id format: {author_id}")
    #               return
    #           if author_id_int is None:
    #               await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
    #               print(f"CommandRouter Error: author_id is None.")
    #               return
    #
    #           # Needs guild_id, int discord ID
    #           player_char = char_mgr.get_character_by_discord_id(guild_id, author_id_int)
    #           if not char: return await send_callback("❌ У вас нет персонажа.") # Need a character to look
    #           current_location_id = getattr(char, 'location_id', None)
    #           if not current_location_id: return await send_callback("❌ Ваш персонаж не находится в локации.")
    #           # Needs guild_id
    #           location_instance = loc_mgr.get_location_instance(guild_id, current_location_id)
    #           if not location_instance: return await send_callback("❌ Информация о текущем местоположении недоступна.")
    #           # Need LocationViewService to format location info
    #           # loc_view_service = context.get('location_view_service')
    #           # if not loc_view_service or not hasattr(loc_view_service, 'get_location_info_embed'):
    #           #      return await send_callback("❌ Система просмотра локаций недоступна.")
    #
    #           try:
    #                # get_location_info_embed needs Location object and context
    #                location_embed = await loc_view_service.get_location_info_embed(location_instance, context=context)
    #                if location_embed:
    #                     await send_callback(embed=location_embed)
    #                else:
    #                     print(f"CommandRouter: Failed to generate location info embed for {current_location_id} in guild {guild_id}.")
    #                     await send_callback("❌ Не удалось сгенерировать описание локации.")
    #           except Exception as e:
    #               print(f"CommandRouter Error generating location info embed for {current_location_id} in guild {guild_id}: {e}")
    #               import traceback
    #               traceback.print_exc()
    #               await send_callback(f"❌ Произошла ошибка при получении информации о локации: {e}")
    #
    #
    #      else:
    #          await send_callback(f"Неизвестное действие для мира: `{subcommand}`. Доступные действия: `time`, `look`.")


    # --- Other potential top-level commands ---

    # @command("look") # Alternative: Top-level /look command
    # async def handle_look(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
    #     """Показывает описание текущей локации или объекта."""
    #     # Needs LocationManager, CharacterManager, LocationViewService (as shown in world look)
    #     # Also potentially NpcManager, ItemManager if looking at specific objects
    #     # Get player character and location.
    #     # If args: find target object in location (NPC, item). If no args, target is current location.
    #     # Use view service (e.g. LocationViewService, NpcViewService, ItemViewService) to get embed.
    #     pass # Implement calling a view service


    # @command("interact")
    # async def handle_interact(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
    #     """Взаимодействует с объектом в текущей локации. Использование: `<объект_ID или имя>`"""
    #     # Needs LocationManager (to find target), CharacterManager (player location), NpcManager, ItemManager
    #     # RuleEngine (for interaction logic), DialogueManager, CharacterActionProcessor
    #     # Get player character and location.
    #     # Find target object by ID or name in current location (search character, NPC, items in location)
    #     # Call RuleEngine.process_interaction(player_char, target_object, context)
    #     pass # Implement calling a processor/rule engine


    # @command("attack")
    # async def handle_attack(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
    #     """Атакует цель в текущей локации. Использование: `<объект_ID или имя>`"""
    #     # Needs CombatManager, CharacterManager, NpcManager, LocationManager, RuleEngine, CharacterActionProcessor
    #     # Get player character and location first.
    #     # Find target creature (Character/NPC) in current location.
    #     # Call CombatManager.initiate_combat or add_participant(player_char, target_object, context)
    #     pass # Implement calling CombatManager/processor


    # @command("use")
    # async def handle_use(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
    #     """Использует предмет из инвентаря. Использование: `<ID предмета> [цель_ID]`"""
    #     # Needs ItemManager, CharacterManager, RuleEngine, CharacterActionProcessor, StatusManager
    #     # Get player character and item instance from inventory by ID.
    #     # Find target object (another entity, location).
    #     # Call RuleEngine.process_item_use(player_char, item_instance, target_object, context)
    #     pass # Implement calling RuleEngine/processor


    # @command("craft")
    # async def handle_craft(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
    #     """Запускает процесс крафтинга или показывает доступные рецепты. Использование: `[рецепт_ID]`"""
    #     # Needs CraftingManager, ItemManager, CharacterManager, RuleEngine, TimeManager (for duration)
    #     # Needs Inventory and potentially Location state (for crafting station).
    #     # If no args, show available recipes (from RuleEngine/CraftingManager, filtered by location/skills)
    #     # If args provided, start crafting process via CraftingManager.
    #     pass # Implement calling CraftingManager


    # @command("trade")
    # async def handle_trade(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
    #     """Инициирует или совершает торговую операцию на рынке. Использование: `<покупка/продажа> <ID предмета> <количество> [цель_ID]`"""
    #     # Needs EconomyManager, ItemManager, CharacterManager/NpcManager, LocationManager (to find market)
    #     # Needs Character's current location to determine market.
    #     # Get player character and location.
    #     # Determine market location (often player's current location if it has a market).
    #     # Call EconomyManager.buy_item or EconomyManager.sell_item with template_id/item_id, quantity, location_id, buyer/seller entity.
    #     pass # Implement calling EconomyManager


# Helper function example (can be defined in this file or a utility module)
def is_uuid_format(s: str) -> bool:
     """Проверяет, выглядит ли строка как UUID (простая проверка формата)."""
     # Simple check for length and presence of hyphens in expected positions
     # A more robust check uses try/except uuid.UUID(s)
     if not isinstance(s, str):
          return False
     # Check basic length and hyphen count/position for standard UUID formats
     # v4 format: 8-4-4-4-12 (32 hex chars + 4 hyphens = 36 total)
     if len(s) == 36 and s.count('-') == 4 and s[8] == '-' and s[13] == '-' and s[18] == '-' and s[23] == '-':
          # Check if segments are hexadecimal (optional but better)
          try:
               uuid.UUID(s) # Use uuid(s) to handle different versions or canonical forms
               return True
          except ValueError:
               return False # Looks like UUID but invalid hex
     return False # Does not match expected format

# --- End of CommandRouter Class ---

print("DEBUG: command_router.py module loaded.")