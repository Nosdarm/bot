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
        event_manager: "EventManager",
        persistence_manager: "PersistenceManager",
        settings: Dict[str, Any],
        world_simulation_processor: "WorldSimulationProcessor",
        send_callback_factory: SendCallbackFactory,
        character_action_processor: "CharacterActionProcessor",
        character_view_service: "CharacterViewService",
        location_manager: "LocationManager",
        rule_engine: "RuleEngine",
        # Add the PartyCommandHandler as a required dependency
        party_command_handler: "PartyCommandHandler", # <--- ИНЖЕКТИРУЕМ ОБРАБОТЧИК ПАРТИИ


        # --- Optional Dependencies ---
        openai_service: Optional["OpenAIService"] = None,
        item_manager: Optional["ItemManager"] = None,
        npc_manager: Optional["NpcManager"] = None,
        combat_manager: Optional["CombatManager"] = None,
        time_manager: Optional["TimeManager"] = None,
        status_manager: Optional["StatusManager"] = None,
        party_manager: Optional["PartyManager"] = None, # Still needed for context if PartyCommandHandler needs it there
        crafting_manager: Optional["CraftingManager"] = None,
        economy_manager: Optional["EconomyManager"] = None,
        party_action_processor: Optional["PartyActionProcessor"] = None, # Still needed for context
        event_action_processor: Optional["EventActionProcessor"] = None,
        event_stage_processor: Optional["EventStageProcessor"] = None,
        # Add other optional managers/processors needed for context
        # dialogue_manager: Optional["DialogueManager"] = None,
        # Add View Services needed for context (even if handled by specific handlers)
        # party_view_service: Optional["PartyViewService"] = None, # Needed for PartyCommandHandler if it gets it from context
        # location_view_service: Optional["LocationViewService"] = None, # Needed for handle_look potentially


    ):
        print("Initializing CommandRouter...")
        # Store all injected dependencies
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
        self._party_command_handler = party_command_handler # <--- ХРАНИМ ОБРАБОТЧИК ПАРТИИ

        # Store optional dependencies (still store them even if delegated, they might be needed in context)
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

        # Store View Services (even if delegated, they might be needed in context)
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

        # --- Build Context for the Handler ---
        # This dictionary provides handlers access to all managers and message details
        # Collect *all* manager attributes from self, so handlers get consistent access
        # Note: Some of these might be None if they were optional and not provided during init
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
            'party_manager': self._party_manager, # Include party_manager in context
            'crafting_manager': self._crafting_manager,
            'economy_manager': self._economy_manager,
            'party_action_processor': self._party_action_processor, # Include party_action_processor in context
            'event_action_processor': self._event_action_processor,
            'event_stage_processor': self._event_stage_processor,
            # TODO: Add other optional managers like self._dialogue_manager
            # 'dialogue_manager': self._dialogue_manager,
            # Add view services if stored as attributes and needed in context by handlers
            # 'party_view_service': self._party_view_service, # Include party_view_service in context
            # 'location_view_service': self._location_view_service,
        }


        context: Dict[str, Any] = {
            'message': message,
            'author_id': str(message.author.id), # Ensure string type
            'guild_id': str(message.guild.id) if message.guild else None, # Ensure string type
            'channel_id': message.channel.id,
            'command_keyword': command_keyword,
            'command_args': command_args,
            'command_prefix': self._command_prefix, # Include prefix in context

            # Add SendCallback for the current channel for convenience
            'send_to_command_channel': self._send_callback_factory(message.channel.id),

            # Add all managers/processors gathered above
            **managers_in_context # Expand the dictionary here
        }

        # --- Route the command ---
        # Check for the party command specifically first, as it's handled externally
        if command_keyword == "party":
             if self._party_command_handler:
                  print(f"CommandRouter: Routing 'party' command to PartyCommandHandler...")
                  try:
                      # Delegate handling to the injected PartyCommandHandler instance
                      await self._party_command_handler.handle(message, command_args, context)
                      print(f"CommandRouter: 'party' command handled by PartyCommandHandler for guild {context.get('guild_id')}.")
                  except Exception as e:
                       print(f"CommandRouter ❌ Error executing 'party' command in PartyCommandHandler for guild {context.get('guild_id')}: {e}")
                       traceback.print_exc()
                       # Notify user about execution error via the context callback
                       send_callback = context.get('send_to_command_channel')
                       if send_callback:
                            try:
                                 error_message_content = f"❌ Произошла ошибка при выполнении команды `{self._command_prefix}{command_keyword}` (обработчик партии)."
                                 if e: error_message_content += f" Подробности: {e}"
                                 max_len = 2000
                                 if len(error_message_content) > max_len: error_message_content = error_message_content[:max_len-3] + "..."
                                 await send_callback(error_message_content)
                            except Exception as cb_e:
                                 print(f"CommandRouter Error sending party execution error message: {cb_e}")
                       else:
                            print(f"CommandRouter Error: Could not get send_to_command_channel callback for party error reporting.")
                  return # Exit after handling the party command

             else:
                  # This case indicates a configuration error where PartyCommandHandler was not provided
                  print(f"CommandRouter Error: PartyCommandHandler is not initialized for guild {context.get('guild_id')}.")
                  send_callback = context.get('send_to_command_channel')
                  if send_callback:
                       try:
                           await send_callback("❌ Система партий недоступна из-за ошибки конфигурации бота.")
                       except Exception as cb_e:
                            print(f"CommandRouter Error sending configuration error message: {cb_e}")
                  return # Exit after reporting config error


        # If it's not the party command, look for a handler registered within CommandRouter
        handler = self.__class__._command_handlers.get(command_keyword)

        if not handler:
            print(f"CommandRouter: Unknown command: '{command_keyword}'.")
            try:
                 send_callback = self._send_callback_factory(message.channel.id)
                 await send_callback(f"❓ Неизвестная команда: `{self._command_prefix}{command_keyword}`. Используйте `{self._command_prefix}help` для просмотра доступных команд.")
            except Exception as cb_e:
                 print(f"CommandRouter Error sending unknown command message: {cb_e}")
            return

        # --- Execute the handler found within CommandRouter ---
        try:
            # Handlers within CommandRouter expect self, message, args, context
            await handler(self, message, command_args, context)
            # print(f"CommandRouter: Command '{command_keyword}' handled successfully by router itself for guild {context.get('guild_id')} in channel {context.get('channel_id')}.") # Handlers should log success


        except Exception as e:
            print(f"CommandRouter ❌ Error executing command '{command_keyword}' in router itself for guild {context.get('guild_id')} in channel {context.get('channel_id')}: {e}")
            import traceback
            traceback.print_exc()
            # Notify user about execution error using the channel-specific callback from context
            send_callback = context.get('send_to_command_channel') # Use the callback from context
            if send_callback:
                 try:
                      error_message_content = f"❌ Произошла ошибка при выполнении команды `{self._command_prefix}{command_keyword}`."
                      if e: # Add exception details if available
                          error_message_content += f" Подробности: {e}"
                      max_len = 2000 # Discord message limit
                      if len(error_message_content) > max_len:
                           error_message_content = error_message_content[:max_len-3] + "..."

                      await send_callback(error_message_content)
                 except Exception as cb_e:
                      print(f"CommandRouter Error sending execution error message: {cb_e}")
            else:
                 print(f"CommandRouter Error: Could not get send_to_command_channel callback for error reporting.")


    # --- Command Handler Methods (Now only include commands handled directly here) ---

    @command("help")
    async def handle_help(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает список доступных команд или помощь по конкретной команде."""
        send_callback = context['send_to_command_channel']
        command_prefix = self._command_prefix

        # Get commands from internal registry *and* add commands handled externally
        internal_commands = sorted(self.__class__._command_handlers.keys())
        # Explicitly list commands handled by other handlers
        external_commands = ["party"] # Add other commands handled by separate handlers here
        all_commands = sorted(list(set(internal_commands + external_commands)))


        if not args:
            help_message = f"Доступные команды (префикс `{command_prefix}`):\n"
            help_message += ", ".join([f"`{cmd}`" for cmd in all_commands])
            help_message += f"\nИспользуйте `{command_prefix}help <команда>` для подробностей."
            await send_callback(help_message)
        else:
            target_command = args[0].lower()

            # Check internal handlers first
            handler = self.__class__._command_handlers.get(target_command)

            if handler:
                docstring = handler.__doc__ or "Нет описания для этой команды."
                if isinstance(docstring, str):
                     docstring = docstring.format(prefix=self._command_prefix)
                     if not docstring:
                          docstring = f"Нет описания для команды `{self._command_prefix}{target_command}`."

                await send_callback(docstring)

            # Check external handlers (e.g., PartyCommandHandler)
            elif target_command == "party":
                 # Delegate getting help for the party command to the PartyCommandHandler
                 if self._party_command_handler:
                      # PartyCommandHandler.handle with 'help' argument should return its help message
                      # Need to simulate the context for the subcommand handler
                      # Re-use the main context dictionary
                      temp_party_args = ["help"] + args[1:] # Pass 'help' as the first arg to the party handler
                      temp_context = context.copy() # Copy context to avoid modifying the original
                      temp_context['command_args'] = temp_party_args
                      temp_context['command_keyword'] = 'party' # Ensure keyword is correct in context

                      # Call the party handler's handle method with the 'help' subcommand
                      print(f"CommandRouter: Delegating help request for 'party' to PartyCommandHandler...")
                      try:
                          # PartyCommandHandler.handle expects message, args, context
                          # We need to pass the original message and the modified args/context
                          await self._party_command_handler.handle(message, temp_party_args, temp_context)
                          print(f"CommandRouter: PartyCommandHandler processed help for 'party'.")
                      except Exception as e:
                           print(f"CommandRouter Error while delegating help for 'party' to PartyCommandHandler: {e}")
                           import traceback
                           traceback.print_exc()
                           await send_callback(f"❌ Ошибка при получении справки для команды партии: {e}")
                 else:
                      await send_callback("❌ Обработчик команд партии недоступен.")


            # Command not found internally or externally
            else:
                await send_callback(f"❓ Команда `{self._command_prefix}{target_command}` не найдена.")

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
        guild_id = context.get('guild_id')
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Команды персонажа доступны только на сервере.")
            return

        if not args:
            help_message = self.handle_character.__doc__
            if isinstance(help_message, str):
                 help_message = help_message.format(prefix=self._command_prefix)
                 if not help_message:
                      help_message = "Описание команды 'character' недоступно."
            else:
                 help_message = "Описание команды 'character' недоступно."
                 print(f"CommandRouter Warning: docstring is missing or not a string for handle_character.")
            await send_callback(help_message)
            return

        subcommand = args[0].lower()
        subcommand_args = args[1:]

        char_manager = context.get('character_manager')
        if not char_manager:
             await send_callback("❌ Система персонажей временно недоступна.")
             print(f"CommandRouter Error: character_manager is None in handle_character for guild {guild_id}.")
             return

        # --- Handle Subcommands ---

        if subcommand == "create":
            if not subcommand_args:
                await send_callback(f"Использование: `{self._command_prefix}character create <имя_персонажа>`")
                return

            character_name = subcommand_args[0]

            if len(character_name) < 2 or len(character_name) > 30:
                await send_callback("❌ Имя персонажа должно быть от 2 до 30 символов.")
                return

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

                new_character = await char_manager.create_character(
                    discord_id=author_id_int,
                    name=character_name,
                    **context
                )

                if new_character:
                    char_name = getattr(new_character, 'name', character_name)
                    char_id = getattr(new_character, 'id', 'N/A')
                    await send_callback(f"✨ Ваш персонаж **{char_name}** успешно создан! (ID: `{char_id}`).")
                    print(f"CommandRouter: Character '{char_name}' (ID: {char_id}) created for user {author_id_int} in guild {guild_id}.")
                else:
                    await send_callback(f"❌ Не удалось создать персонажа **{character_name}**. Возможно, имя занято или у вас уже есть персонаж в этой гильдии.")

            except ValueError as ve:
                 await send_callback(f"❌ Ошибка создания персонажа: {ve}")
                 print(f"CommandRouter Error: Validation error creating character: {ve} for user {author_id} in guild {guild_id}.")
            except Exception as e:
                print(f"CommandRouter Error creating character for user {author_id} in guild {guild_id}: {e}")
                import traceback
                traceback.print_exc()
                await send_callback(f"❌ Произошла ошибка при создании персонажа: {e}")

        elif subcommand == "delete":
             char_id_or_name_to_find: Optional[str] = None
             char_id_to_delete: Optional[str] = None
             target_char: Optional["Character"] = None

             if subcommand_args:
                  char_id_or_name_to_find = subcommand_args[0]
                  target_char = char_manager.get_character(guild_id, char_id_or_name_to_find)

                  if not target_char:
                       await send_callback(f"❌ Персонаж с ID `{char_id_or_name_to_find}` не найден в этой гильдии.")
                       return

                  char_id_to_delete = getattr(target_char, 'id', None)

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

                  target_char = char_manager.get_character_by_discord_id(guild_id, author_id_int)

                  if not target_char:
                     await send_callback(f"❌ У вас еще нет персонажа, которого можно было бы удалить в этой гильдии.")
                     return

                  char_id_to_delete = getattr(target_char, 'id', None)
                  char_id_or_name_to_find = char_id_to_delete

             if target_char is None or char_id_to_delete is None:
                  await send_callback("❌ Произошла ошибка при определении персонажа для удаления.")
                  return

             author_id_int_check: Optional[int] = None
             try:
                 if author_id is not None: author_id_int_check = int(author_id)
             except (ValueError, TypeError): pass

             is_gm = False
             settings_data = context.get('settings', {})
             if isinstance(settings_data, dict):
                  admin_users = set(map(str, settings_data.get('bot_admins', [])))
                  if author_id in admin_users:
                       is_gm = True

             if not is_gm and getattr(target_char, 'discord_user_id', None) != author_id_int_check:
                  await send_callback("❌ Вы можете удалить только своего персонажа (или обратитесь к GM).")
                  return

             try:
                 print(f"CommandRouter: Attempting to delete character {char_id_to_delete} ({getattr(target_char, 'name', 'N/A')}) by user {author_id} (is_gm: {is_gm}) in guild {guild_id}...")
                 deleted_char_id = await char_manager.remove_character(
                     character_id=char_id_to_delete,
                     guild_id=guild_id,
                     **context
                 )

                 if deleted_char_id:
                     char_name = getattr(target_char, 'name', 'персонаж')
                     await send_callback(f"🗑️ Персонаж **{char_name}** (ID: `{deleted_char_id}`) успешно удален.")
                     print(f"CommandRouter: Character {deleted_char_id} ({char_name}) deleted by user {author_id} in guild {guild_id}.")
                 else:
                     print(f"CommandRouter: Warning: char_manager.remove_character returned None for {char_id_to_delete} in guild {guild_id}. Check manager logs for details.")
                     await send_callback(f"❌ Не удалось удалить персонажа `{char_id_or_name_to_find}`.")


             except Exception as e:
                 print(f"CommandRouter Error deleting character {char_id_or_name_to_find} for user {author_id} in guild {guild_id}: {e}")
                 import traceback
                 traceback.print_exc()
                 await send_callback(f"❌ Произошла ошибка при удалении персонажа: {e}")


        else:
            usage_message = f"Неизвестное действие для персонажа: `{subcommand}`. Доступные действия: `create`, `delete` (и другие, если реализованы).\nИспользование: `{self._command_prefix}character <действие> [аргументы]`"
            if isinstance(usage_message, str):
                 usage_message = usage_message.format(prefix=self._command_prefix)
            await send_callback(usage_message)
            print(f"CommandRouter: Unknown character subcommand: '{subcommand}' in guild {guild_id}.")


    @command("status")
    async def handle_status(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает лист персонажа (статы, инвентарь, состояние). Использование: `[<ID персонажа>]`"""
        send_callback = context['send_to_command_channel']
        guild_id = context.get('guild_id')
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        char_id_to_view: Optional[str] = None
        target_char: Optional["Character"] = None

        char_manager = context.get('character_manager')
        char_view_service = context.get('character_view_service')

        if not char_manager or not char_view_service:
             await send_callback("❌ Система персонажей или просмотра временно недоступна.")
             print(f"CommandRouter Error: character_manager or character_view_service is None in status handler for guild {guild_id}.")
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
             await send_callback("❌ Не удалось определить, чей лист показать.")
             return

        try:
            sheet_embed = await char_view_service.get_character_sheet_embed(target_char, context=context)

            if sheet_embed:
                 await send_callback(embed=sheet_embed)
                 print(f"CommandRouter: Sent character sheet embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")
            else:
                 print(f"CommandRouter: Failed to generate character sheet embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}. CharacterViewService returned None or invalid.")
                 await send_callback(f"❌ Не удалось сгенерировать лист персонажа **{getattr(target_char, 'name', 'N/A')}**. Проверьте логи бота.")


        except Exception as e:
            print(f"CommandRouter Error generating character sheet embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при получении листа персонажа: {e}")


    @command("inventory")
    async def handle_inventory(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает инвентарь вашего персонажа. Используйте: `[<ID персонажа>]`"""
        send_callback = context['send_to_command_channel']
        guild_id = context.get('guild_id')
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        char_id_to_view: Optional[str] = None
        target_char: Optional["Character"] = None

        char_manager = context.get('character_manager')
        char_view_service = context.get('character_view_service')

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
            inventory_embed = await char_view_service.get_inventory_embed(target_char, context=context)

            if inventory_embed:
                 await send_callback(embed=inventory_embed)
                 print(f"CommandRouter: Sent inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")
            else:
                 print(f"CommandRouter: Failed to generate inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}. CharacterViewService returned None or invalid.")
                 await send_callback(f"❌ Не удалось сгенерировать инвентарь для персонажа **{getattr(target_char, 'name', 'N/A')}**. Проверьте логи бота.")

        except Exception as e:
            print(f"CommandRouter Error generating inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при получении инвентаря: {e}")


    @command("move")
    async def handle_move(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Перемещает вашего персонажа в указанную локацию. Использование: `<ID локации>`"""
        send_callback = context['send_to_command_channel']
        guild_id = context.get('guild_id')
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        if not args:
            await send_callback(f"Использование: `{self._command_prefix}move <ID локации>`")
            return

        target_location_id_arg = args[0]

        char_manager = context.get('character_manager')
        char_action_processor = context.get('character_action_processor')
        loc_manager = context.get('location_manager')

        if not char_manager or not char_action_processor or not loc_manager:
             await send_callback("❌ Система перемещения, локаций или персонажей временно недоступна.")
             print(f"CommandRouter Error: required managers/processors (char_manager, char_action_processor, loc_manager) are None in move handler for guild {guild_id}.")
             return

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

        char_id = getattr(player_char, 'id', None)
        if char_id is None:
             print(f"CommandRouter Error: Player character object has no ID attribute for user {author_id} in guild {guild_id}.")
             await send_callback("❌ Произошла ошибка: Не удалось определить ID вашего персонажа.")
             return

        target_location_instance = loc_manager.get_location_instance(guild_id, target_location_id_arg)
        if not target_location_instance:
             await send_callback(f"❌ Локация с ID `{target_location_id_arg}` не найдена в этой гильдии.")
             return

        try:
            await char_action_processor.process_move_action(
                character_id=char_id,
                target_location_id=getattr(target_location_instance, 'id', str(target_location_id_arg)),
                context=context
            )

        except Exception as e:
            print(f"CommandRouter Error processing move command for character {char_id} to location {target_location_id_arg} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при попытке перемещения: {e}")


    # --- Removed handle_party method and its decorators ---


    # Helper function example (can be defined in this file or a utility module)
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