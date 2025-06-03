# bot/game/command_router.py

print("--- Начинается загрузка: command_router.py")

import asyncio
import traceback
import shlex # For better argument parsing (handles quotes)
# Import typing components
# ИСПРАВЛЕНИЕ: Добавляем ClassVar в импорты typing
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING, ClassVar

# Import discord types for type hints
# Use string literal if these are only used for type hints to avoid import cycles
# from discord import Client # Direct import if Client is instantiated or directly used outside type hints
# ИСПРАВЛЕНИЕ: Message импортируется для type hints в сигнатурах методов
from discord import Message # Used in route method signature, handle_* signatures


if TYPE_CHECKING:
    # --- Imports for Type Checking ---
    # Discord types used in method signatures or context
    # ИСПРАВЛЕНИЕ: Message уже импортирован выше, нет необходимости здесь
    # from discord import Message # Used in handle_discord_message signature
    # from discord import Guild # Example if guild object is passed in context
    from discord import Client # If client is passed in context or needs type hint

    # Models (needed for type hints or isinstance checks if they cause cycles elsewhere)
    # ИСПРАВЛЕНИЕ: Добавляем Character здесь для разрешения строкового литерала в аннотациях
    from bot.game.models.character import Character

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
    # Processors (use string literals)
    from bot.game.event_processors.event_action_processor import EventActionProcessor
    from bot.game.event_processors.event_stage_processor import EventStageProcessor
    from bot.game.world_processors.world_simulation_processor import WorldSimulationProcessor
    from bot.game.character_processors.character_action_processor import CharacterActionProcessor
    from bot.game.character_processors.character_view_service import CharacterViewService
    from bot.game.party_processors.party_action_processor import PartyActionProcessor

    # Type aliases for callbacks (defined below, but referenced in type hints here)
    # SendToChannelCallback = Callable[..., Awaitable[Any]]
    # SendCallbackFactory = Callable[[int], SendToChannelCallback]


# Define Type Aliases for callbacks explicitly if used in type hints
# These are defined outside TYPE_CHECKING because they are used in the __init__ signature
SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


# --- Command Decorator ---
# This decorator is used to register command handler methods
# ИСПРАВЛЕНИЕ: Переименовываем глобальный словарь для ясности
_command_registry: Dict[str, Callable[..., Awaitable[Any]]] = {} # Global command registry

def command(keyword: str) -> Callable:
    """Decorator to register a method as a command handler."""
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        # Store the function in the registry using the keyword
        # Commands are case-insensitive, store lowercase keyword
        # ИСПРАВЛЕНИЕ: Используем новое имя глобального словаря
        _command_registry[keyword.lower()] = func
        print(f"DEBUG: Command '{keyword}' registered to {func.__name__}")
        return func
    return decorator

# --- CommandRouter Class ---
class CommandRouter:
    # Access the global registry via a class variable
    # ИСПРАВЛЕНИЕ: Используем ClassVar для аннотации class-level атрибута
    # Присваиваем глобальный словарь _command_registry этому атрибуту класса
    _command_handlers: ClassVar[Dict[str, Callable[..., Awaitable[Any]]]] = _command_registry # FIX: Used ClassVar here and assigned the global registry


    def __init__(
        self,
        # --- Required Dependencies ---
        # These are expected to be always available based on GameManager setup
        character_manager: "CharacterManager", # Use string literal!
        event_manager: "EventManager", # Use string literal!
        persistence_manager: "PersistenceManager", # Use string literal!
        settings: Dict[str, Any],
        world_simulation_processor: "WorldSimulationProcessor", # Use string literal!
        send_callback_factory: SendCallbackFactory, # Callable type alias
        character_action_processor: "CharacterActionProcessor", # Use string literal!
        character_view_service: "CharacterViewService", # Use string literal!
        location_manager: "LocationManager", # Use string literal!
        rule_engine: "RuleEngine", # Use string literal!

        # --- Optional Dependencies ---
        # These might be None if their setup failed or they are disabled
        openai_service: Optional["OpenAIService"] = None, # Use string literal!
        item_manager: Optional["ItemManager"] = None, # Use string literal!
        npc_manager: Optional["NpcManager"] = None, # Use string literal!
        combat_manager: Optional["CombatManager"] = None, # Use string literal!
        time_manager: Optional["TimeManager"] = None, # Use string literal!
        status_manager: Optional["StatusManager"] = None, # Use string literal!
        party_manager: Optional["PartyManager"] = None, # Use string literal!
        crafting_manager: Optional["CraftingManager"] = None, # Use string literal!
        economy_manager: Optional["EconomyManager"] = None, # Use string literal!
        party_action_processor: Optional["PartyActionProcessor"] = None, # Use string literal!
        event_action_processor: Optional["EventActionProcessor"] = None, # Use string literal!
        event_stage_processor: Optional["EventStageProcessor"] = None, # Use string literal!
        # TODO: Add DialogueManager etc. if needed
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
        self._event_stage_processor = event_stage_processor
        # TODO: Store dialogue_manager if added

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
            # print(f"DEBUG: Ignoring non-command message: '{message.content}'") # Too noisy
            return

        # Extract command and arguments
        # Use shlex.split to handle quoted arguments correctly
        try:
            # Remove prefix and split
            command_line = message.content[len(self._command_prefix):].strip()
            if not command_line: # Message was just the prefix
                 # Optional: Send help message or brief instruction here
                 # await self._send_callback_factory(message.channel.id)(f"Привет! Я бот {self._discord_client.user.name}. Используй `{self._command_prefix} help` для списка команд.") # FIX: Removed , None
                 return # Ignore just the prefix

            # Split into command keyword and arguments
            # shlex.split handles quotes and spaces properly
            split_command = shlex.split(command_line)
            command_keyword = split_command[0].lower() # Command keyword is case-insensitive
            command_args = split_command[1:] # Remaining parts are arguments

        except Exception as e:
            print(f"CommandRouter Error: Failed to parse command '{message.content}': {e}")
            import traceback
            traceback.print_exc()
            # Notify user about parsing error
            try:
                 send_callback = self._send_callback_factory(message.channel.id)
                 # FIX: Removed , None
                 await send_callback(f"❌ Ошибка при разборе команды: {e}")
            except Exception as cb_e:
                 print(f"CommandRouter Error sending parsing error message: {cb_e}")
            return


        print(f"CommandRouter: Routing command '{command_keyword}' with args {command_args} from user {message.author.id} in guild {message.guild.id if message.guild else 'DM'}.")

        # Find the corresponding handler
        # Access the class-level registry directly
        handler = self.__class__._command_handlers.get(command_keyword) # Use self.__class__ to access the class variable


        if not handler:
            print(f"CommandRouter: Unknown command: '{command_keyword}'.")
            # Notify user about unknown command
            try:
                 send_callback = self._send_callback_factory(message.channel.id)
                 # FIX: Removed , None
                 await send_callback(f"❓ Неизвестная команда: `{self._command_prefix}{command_keyword}`. Используйте `{self._command_prefix}help` для просмотра доступных команд.")
            except Exception as cb_e:
                 # The error "takes from 0 to 1 positional arguments but 2 were given"
                 # was likely triggered by this block, specifically the line above.
                 print(f"CommandRouter Error sending unknown command message: {cb_e}")
            return

        # --- Build Context for the Handler ---
        # This dictionary provides handlers access to all managers and message details
        context: Dict[str, Any] = {
            'message': message, # Full discord.Message object
            'author_id': str(message.author.id), # Discord User ID (string)
            'guild_id': str(message.guild.id) if message.guild else None, # Guild ID (string or None for DMs)
            'channel_id': message.channel.id, # Channel ID (integer)
            'command_keyword': command_keyword,
            'command_args': command_args, # Raw arguments list

            # Pass all stored managers and processors (include None ones, handlers should check)
            'character_manager': self._character_manager,
            'event_manager': self._event_manager,
            'persistence_manager': self._persistence_manager,
            'settings': self._settings,
            'world_simulation_processor': self._world_simulation_processor,
            'send_callback_factory': self._send_callback_factory, # Pass the factory
            'character_action_processor': self._character_action_processor,
            'character_view_service': self._character_view_service,
            'location_manager': self._location_manager,
            'rule_engine': self._rule_engine,

            # Optional managers/processors (handlers must check if None)
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
            # TODO: Add dialogue_manager etc. to context if stored
        }

        # Optional: Try to get the player's character object and add to context if needed by many handlers
        # Note: This might not be needed for all commands (e.g., GM commands, create_character).
        # Handlers that need the character should get it themselves from the manager via context.
        # Example:
        # if context['guild_id'] and context['character_manager']:
        #      # Assume get_character_by_discord_id now takes guild_id first
        #      # Check if author_id is not None and can be converted to int
        #      author_id_int: Optional[int] = None
        #      try:
        #          if context['author_id'] is not None: author_id_int = int(context['author_id'])
        #      except (ValueError, TypeError): pass # Ignore if conversion fails
        #
        #      player_char = None
        #      if author_id_int is not None:
        #          # Use get_character_by_discord_id with guild_id and the integer discord ID
        #          player_char = context['character_manager'].get_character_by_discord_id(context['guild_id'], author_id_int)
        #
        #      context['player_character'] = player_char # Add to context if found


        # --- Execute the handler ---
        try:
            # Call the handler method, passing message, args, and the context
            # Handlers are async methods on the CommandRouter instance
            await handler(self, message, command_args, context)
            # print(f"CommandRouter: Command '{command_keyword}' handled successfully.") # Moved inside handler or logging better placed


        except Exception as e:
            print(f"CommandRouter ❌ Error executing command '{command_keyword}': {e}")
            import traceback
            traceback.print_exc()
            # Notify user about execution error
            try:
                 send_callback = self._send_callback_factory(message.channel.id)
                 # FIX: Removed , None
                 await send_callback(f"❌ Произошла ошибка при выполнении команды `{self._command_prefix}{command_keyword}`: {e}")
            except Exception as cb_e:
                 print(f"CommandRouter Error sending execution error message: {cb_e}")

    # --- Command Handler Methods ---
    # These methods are decorated with @command and will be called by route()
    # They should be async and accept (self, message, args, context)

    @command("help")
    async def handle_help(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает список доступных команд или помощь по конкретной команде."""
        send_callback = context['send_callback_factory'](context['channel_id'])
        command_prefix = self._command_prefix # Use the stored prefix

        if not args:
            # List all available commands from the class-level registry
            command_list = sorted(self.__class__._command_handlers.keys()) # Access via self.__class__
            help_message = f"Доступные команды (префикс `{command_prefix}`):\n"
            help_message += ", ".join([f"`{cmd}`" for cmd in command_list])
            help_message += f"\nИспользуйте `{command_prefix}help <команда>` для подробностей."
            # FIX: Removed , None
            await send_callback(help_message)
        else:
            # Provide help for a specific command
            target_command = args[0].lower()
            # Look up in the class-level registry
            handler = self.__class__._command_handlers.get(target_command) # Access via self.__class__
            if handler:
                # Get docstring for help message
                docstring = handler.__doc__ or "Нет описания для этой команды."
                # FIX: Removed , None
                await send_callback(f"Помощь по команде `{command_prefix}{target_command}`:\n{docstring}")
            else:
                # FIX: Removed , None
                await send_callback(f"❓ Команда `{target_command}` не найдена.")
        print(f"CommandRouter: Processed help command for guild {context['guild_id']}.")


    # ИСПРАВЛЕНИЕ: Команда создания персонажа должна быть @command("create_character"), а не @command("character")
    # Если вы хотите использовать "/character create", то вам нужна команда @command("character"),
    # а логика "create" должна обрабатываться внутри handle_character.
    # Согласно логу, вы отправили "/character create", но команда @command("create_character") зарегистрирована.
    # Для команды "/character create", вам нужно:
    # 1. Зарегистрировать @command("character").
    # 2. Реализовать async def handle_character(self, message, args, context) -> None:
    # 3. В handle_character, проверить args[0] (должно быть "create").
    # 4. Если args[0] == "create", вызвать логику создания персонажа, передав args[1:] как аргументы для создания имени.
    #
    # Поскольку в логе показано, что вы отправили "/character create", а у вас зарегистрирована @command("create_character"),
    # я предполагаю, что либо вы опечатались в команде, либо регистрация команды не соответствует желаемому использованию.
    # Я ОСТАВЛЮ регистрацию как @command("create_character"), предполагая, что команда должна быть "/create_character Самаэль".
    # Если вы хотите "/character create", нужно изменить декоратор на @command("character") и перенести логику в handle_character.

    @command("create_character")
    async def handle_create_character(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Создает нового персонажа для игрока. Использование: `<имя_персонажа>`"""
        send_callback = context['send_callback_factory'](context['channel_id'])
        guild_id = context['guild_id'] # Must be in a guild to create a character
        author_id = context['author_id'] # Discord user ID as string

        if guild_id is None:
            # FIX: Removed , None
            await send_callback("❌ Создание персонажа возможно только на сервере.")
            return

        if not args:
            # FIX: Removed , None
            await send_callback(f"Использование: `{self._command_prefix}create_character <имя_персонажа>`")
            return

        character_name = args[0] # First argument is the name

        char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
        if not char_manager:
             # FIX: Removed , None
             await send_callback("❌ Система персонажей временно недоступна.")
             print(f"CommandRouter Error: character_manager is None in create_character handler for guild {guild_id}.")
             return

        try:
            # CharacterManager.create_character(discord_id, name, guild_id, **kwargs) -> Optional[Character]
            # Pass discord_id as int, guild_id as str, and include context kwargs
            # Ensure author_id can be converted to int
            author_id_int: Optional[int] = None
            try:
                if author_id is not None: author_id_int = int(author_id)
            except (ValueError, TypeError):
                # FIX: Removed , None
                await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
                print(f"CommandRouter Error: Invalid author_id format: {author_id}")
                return

            if author_id_int is None:
                 # FIX: Removed , None
                 await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
                 print(f"CommandRouter Error: author_id is None.")
                 return


            new_character = await char_manager.create_character(
                discord_id=author_id_int, # Convert author_id to int for manager
                name=character_name,
                guild_id=guild_id, # Pass guild_id string
                **context # Pass entire context dictionary
            )

            if new_character:
                char_name = getattr(new_character, 'name', character_name)
                char_id = getattr(new_character, 'id', 'N/A')
                # FIX: Removed , None
                await send_callback(f"✨ Персонаж **{char_name}** успешно создан! (ID: `{char_id}`)")
                print(f"CommandRouter: Character '{char_name}' (ID: {char_id}) created for user {author_id_int} in guild {guild_id}.")
            else:
                # Creation failed (e.g., name taken, already has a char) - Manager should print detailed reason
                # FIX: Removed , None
                await send_callback(f"❌ Не удалось создать персонажа **{character_name}**. Возможно, имя занято или у вас уже есть персонаж в этой гильдии.")
                print(f"CommandRouter: Failed to create character '{character_name}' for user {author_id_int} in guild {guild_id}.")


        except ValueError as ve: # Catch specific validation errors from manager
             # FIX: Removed , None
             await send_callback(f"❌ Ошибка создания персонажа: {ve}")
             print(f"CommandRouter Error: Validation error creating character: {ve} for user {author_id} in guild {guild_id}.")
        except Exception as e:
            print(f"CommandRouter Error creating character for user {author_id} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            # FIX: Removed , None
            await send_callback(f"❌ Произошла ошибка при создании персонажа: {e}")


    @command("stats")
    async def handle_stats(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает статистику вашего персонажа или персонажа по ID. Использование: `[<ID персонажа>]`"""
        send_callback = context['send_callback_factory'](context['channel_id'])
        guild_id = context['guild_id']
        author_id = context['author_id'] # Discord user ID as string

        if guild_id is None:
            # FIX: Removed , None
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        char_id_to_view: Optional[str] = None
        # Type hint for target_char resolved by adding import in TYPE_CHECKING
        target_char: Optional["Character"] = None # Store the target character object

        char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
        char_view_service = context.get('character_view_service') # Type: Optional["CharacterViewService"]

        if not char_manager or not char_view_service:
             # FIX: Removed , None
             await send_callback("❌ Система персонажей или просмотра временно недоступна.")
             print(f"CommandRouter Error: character_manager or character_view_service is None in stats handler for guild {guild_id}.")
             return

        if args:
            # If args are provided, assume the first one is a character ID
            char_id_to_view = args[0]
            # Get the character object by the provided ID (use get_character with guild_id)
            # Assuming get_character signature is get_character(guild_id: str, character_id: str)
            target_char = char_manager.get_character(guild_id, char_id_to_view) # Need guild_id

            if not target_char:
                 # FIX: Removed , None
                 await send_callback(f"❌ Персонаж с ID `{char_id_to_view}` не найден в этой гильдии.")
                 return # Exit if character by ID is not found
        else:
            # If no args, try to get the player's own character by Discord ID
            # Ensure author_id can be converted to int
            author_id_int: Optional[int] = None
            try:
                if author_id is not None: author_id_int = int(author_id)
            except (ValueError, TypeError):
                 # FIX: Removed , None
                 await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
                 print(f"CommandRouter Error: Invalid author_id format: {author_id}")
                 return

            if author_id_int is None:
                 # FIX: Removed , None
                 await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
                 print(f"CommandRouter Error: author_id is None.")
                 return

            # Assume get_character_by_discord_id now takes guild_id first
            # Assuming get_character_by_discord_id signature is get_character_by_discord_id(guild_id: str, discord_user_id: int)
            player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int) # Need guild_id and convert author_id to int
            if player_char:
                target_char = player_char # Found player's character
                char_id_to_view = getattr(player_char, 'id', 'N/A') # Get character ID safely for logging
            else:
                # FIX: Removed , None
                await send_callback(f"❌ У вас еще нет персонажа. Создайте его командой `{self._command_prefix}create_character <имя>`")
                return # Cannot view stats if no character

        # At this point, target_char should be a Character object if found, otherwise we returned early.
        if target_char is None: # This check is technically redundant due to returns above, but safe.
             # FIX: Removed , None
             await send_callback("❌ Не удалось определить, чьи статы показать.")
             return


        try:
            # CharacterViewService.get_character_stats_embed expects Character object and context
            # Pass the target_char object and the full context
            stats_embed = await char_view_service.get_character_stats_embed(target_char, context=context) # Pass context dict

            if stats_embed:
                 # Send the embed (send_callback accepts embed in kwargs)
                 await send_callback(embed=stats_embed)
                 print(f"CommandRouter: Sent stats embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")
            else:
                 # FIX: Removed , None
                 await send_callback(f"❌ Не удалось сгенерировать статистику для персонажа **{getattr(target_char, 'name', 'N/A')}**.")
                 print(f"CommandRouter: Failed to generate stats embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")


        except Exception as e:
            print(f"CommandRouter Error generating stats embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            # FIX: Removed , None
            await send_callback(f"❌ Произошла ошибка при получении статистики: {e}")


    @command("inventory")
    async def handle_inventory(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает инвентарь вашего персонажа или персонажа по ID. Использование: `[<ID персонажа>]`"""
        send_callback = context['send_callback_factory'](context['channel_id'])
        guild_id = context['guild_id']
        author_id = context['author_id'] # Discord user ID as string

        if guild_id is None:
            # FIX: Removed , None
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        char_id_to_view: Optional[str] = None
        # Type hint for target_char resolved by adding import in TYPE_CHECKING
        target_char: Optional["Character"] = None # Store the target character object

        char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
        char_view_service = context.get('character_view_service') # Type: Optional["CharacterViewService"]

        if not char_manager or not char_view_service:
             # FIX: Removed , None
             await send_callback("❌ Система персонажей или просмотра временно недоступна.")
             print(f"CommandRouter Error: character_manager or character_view_service is None in inventory handler for guild {guild_id}.")
             return

        if args:
            # If args are provided, assume the first one is a character ID
            char_id_to_view = args[0]
            # Get the character object by the provided ID (use get_character with guild_id)
            # Assuming get_character signature is get_character(guild_id: str, character_id: str)
            target_char = char_manager.get_character(guild_id, char_id_to_view) # Need guild_id

            if not target_char:
                 # FIX: Removed , None
                 await send_callback(f"❌ Персонаж с ID `{char_id_to_view}` не найден в этой гильдии.")
                 return # Exit if character by ID is not found
        else:
            # If no args, try to get the player's own character by Discord ID
            # Ensure author_id can be converted to int
            author_id_int: Optional[int] = None
            try:
                if author_id is not None: author_id_int = int(author_id)
            except (ValueError, TypeError):
                 # FIX: Removed , None
                 await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
                 print(f"CommandRouter Error: Invalid author_id format: {author_id}")
                 return

            if author_id_int is None:
                 # FIX: Removed , None
                 await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
                 print(f"CommandRouter Error: author_id is None.")
                 return

            # Assume get_character_by_discord_id now takes guild_id first
            # Assuming get_character_by_discord_id signature is get_character_by_discord_id(guild_id: str, discord_user_id: int)
            player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int) # Need guild_id and convert author_id to int
            if player_char:
                target_char = player_char # Found player's character
                char_id_to_view = getattr(player_char, 'id', 'N/A') # Get character ID safely for logging
            else:
                # FIX: Removed , None
                await send_callback(f"❌ У вас еще нет персонажа. Создайте его командой `{self._command_prefix}create_character <имя>`")
                return # Cannot view inventory if no character

        # At this point, target_char should be a Character object if found, otherwise we returned early.
        if target_char is None: # This check is technically redundant due to returns above, but safe.
             # FIX: Removed , None
             await send_callback("❌ Не удалось определить, чей инвентарь показать.")
             return


        try:
            # CharacterViewService.get_inventory_embed expects Character object and context
            # Pass the target_char object and the full context
            inventory_embed = await char_view_service.get_inventory_embed(target_char, context=context) # Pass context dict

            if inventory_embed:
                 # Send the embed
                 await send_callback(embed=inventory_embed)
                 print(f"CommandRouter: Sent inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")
            else:
                 # FIX: Removed , None
                 await send_callback(f"❌ Не удалось сгенерировать инвентарь для персонажа **{getattr(target_char, 'name', 'N/A')}**.")
                 print(f"CommandRouter: Failed to generate inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")


        except Exception as e:
            print(f"CommandRouter Error generating inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            # FIX: Removed , None
            await send_callback(f"❌ Произошла ошибка при получении инвентаря: {e}")


    @command("move")
    async def handle_move(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Перемещает вашего персонажа в указанную локацию. Использование: `<ID локации>`"""
        send_callback = context['send_callback_factory'](context['channel_id'])
        guild_id = context['guild_id']
        author_id = context['author_id']

        if guild_id is None:
            # FIX: Removed , None
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        if not args:
            # FIX: Removed , None
            await send_callback(f"Использование: `{self._command_prefix}move <ID локации>`")
            return

        target_location_id = args[0] # First argument is the target location ID

        char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
        char_action_processor = context.get('character_action_processor') # Type: Optional["CharacterActionProcessor"]

        if not char_manager or not char_action_processor:
             # FIX: Removed , None
             await send_callback("❌ Система перемещения или персонажей временно недоступна.")
             print(f"CommandRouter Error: character_manager or character_action_processor is None in move handler for guild {guild_id}.")
             return

        # Get the player's own character by Discord ID
        # Ensure author_id can be converted to int
        author_id_int: Optional[int] = None
        try:
            if author_id is not None: author_id_int = int(author_id)
        except (ValueError, TypeError):
             # FIX: Removed , None
             await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
             print(f"CommandRouter Error: Invalid author_id format: {author_id}")
             return

        if author_id_int is None:
             # FIX: Removed , None
             await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
             print(f"CommandRouter Error: author_id is None.")
             return


        # Assume get_character_by_discord_id now takes guild_id first
        player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int) # Need guild_id and convert author_id to int
        if not player_char:
            # FIX: Removed , None
            await send_callback("❌ У вас еще нет персонажа.")
            return

        char_id = getattr(player_char, 'id', None) # Get character ID safely
        if char_id is None:
             # FIX: Removed , None
             await send_callback("❌ Не удалось определить ID вашего персонажа.")
             return

        try:
            # CharacterActionProcessor.process_move_action expects character_id, target_location_id, context
            # Pass character_id, target_location_id, and the full context
            # The processor will handle validation (location exists, accessible), busy status, setting location, etc.
            # It is expected to send feedback messages directly.
            await char_action_processor.process_move_action(
                character_id=char_id,
                target_location_id=target_location_id,
                context=context # Pass full context dictionary
            )
            # print(f"CommandRouter: Move action processed for character {char_id} to location {target_location_id} in guild {guild_id}.") # Logging handled in processor

        except Exception as e:
            print(f"CommandRouter Error processing move command for character {char_id} to location {target_location_id} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            # FIX: Removed , None
            await send_callback(f"❌ Произошла ошибка при попытке перемещения: {e}")


    # @command("join_party") # Example command handler
    # async def handle_join_party(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
    #     """Присоединиться к партии. Использование: `[<ID партии>]`"""
    #     send_callback = context['send_callback_factory'](context['channel_id'])
    #     guild_id = context['guild_id']
    #     author_id = context['author_id']
    #
    #     if guild_id is None:
    #         # FIX: Removed , None
    #         await send_callback("❌ Эту команду можно использовать только на сервере.")
    #         return
    #
    #     char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
    #     party_manager = context.get('party_manager') # Type: Optional["PartyManager"]
    #     party_action_processor = context.get('party_action_processor') # Type: Optional["PartyActionProcessor"]
    #
    #     if not char_manager or not party_manager or not party_action_processor:
    #          # FIX: Removed , None
    #          await send_callback("❌ Система партий временно недоступна.")
    #          print(f"CommandRouter Error: party system managers/processors are None in join_party handler for guild {guild_id}.")
    #          return
    #
    #     # Get player's character
    #     # Ensure author_id can be converted to int
    #     author_id_int: Optional[int] = None
    #     try:
    #         if author_id is not None: author_id_int = int(author_id)
    #     except (ValueError, TypeError):
    #          # FIX: Removed , None
    #          await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
    #          print(f"CommandRouter Error: Invalid author_id format: {author_id}")
    #          return
    #
    #     if author_id_int is None:
    #          # FIX: Removed , None
    #          await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
    #          print(f"CommandRouter Error: author_id is None.")
    #          return
    #
    #
    #     player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int) # Need guild_id and convert author_id
    #     if not player_char:
    #         # FIX: Removed , None
    #         await send_callback("❌ У вас еще нет персонажа.")
    #         return
    #
    #     char_id = getattr(player_char, 'id', None) # Get character ID safely
    #     if char_id is None:
    #          # FIX: Removed , None
    #          await send_callback("❌ Не удалось определить ID вашего персонажа.")
    #          return
    #
    #     target_party_id: Optional[str] = None
    #     if args:
    #          target_party_id = args[0] # Assume first arg is party ID
    #     else:
    #          # TODO: Logic to find or create a party if no ID is provided?
    #          # FIX: Removed , None
    #          await send_callback(f"Использование: `{self._command_prefix}join_party <ID партии>`")
    #          return
    #
    #     # Check if the party exists (use party_manager with guild_id)
    #     # Assuming get_party signature is get_party(guild_id: str, party_id: str)
    #     target_party = party_manager.get_party(guild_id, target_party_id) # Need guild_id
    #     if not target_party:
    #          # FIX: Removed , None
    #          await send_callback(f"❌ Партия с ID `{target_party_id}` не найдена в этой гильдии.")
    #          return
    #
    #     try:
    #         # PartyActionProcessor.process_join_party expects character_id, party_id, context
    #         # Pass character_id, target_party_id, and the full context
    #         # The processor handles adding to party, updating char.party_id, sending feedback etc.
    #         # It is expected to send feedback messages directly.
    #         await party_action_processor.process_join_party(
    #             character_id=char_id,
    #             party_id=target_party_id,
    #             context=context # Pass full context dictionary
    #         )
    #         # print(f"CommandRouter: Join party action processed for character {char_id} to party {target_party_id} in guild {guild_id}.") # Logging handled in processor
    #
    #     except Exception as e:
    #         print(f"CommandRouter Error processing join_party command for character {char_id} to party {target_party_id} in guild {guild_id}: {e}")
    #         import traceback
    #         traceback.print_exc()
    #         # FIX: Removed , None
    #         await send_callback(f"❌ Произошла ошибка при попытке присоединиться к партии: {e}")


    # TODO: Implement other command handlers as needed (e.g., leave_party, party_stats, look, interact, attack, use_item, craft, etc.)
    # Remember to decorate them with @command("keyword")
    # Each handler should:
    # 1. Get send_callback from context['send_callback_factory'](context['channel_id'])
    # 2. Get necessary managers/processors from context. Check if they are not None.
    # 3. Get message/user/guild info from context. Ensure guild_id exists for guild-specific commands.
    # 4. Get player's character if it's a player command (using char_manager.get_character_by_discord_id with guild_id). Handle case where player has no character.
    # 5. Parse specific arguments from `args`. Handle missing/invalid arguments. Use shlex.split in route, so args are already split by spaces/quotes.
    # 6. Call the appropriate manager/processor method with necessary IDs and the context dictionary.
    # 7. The called method should ideally handle the core logic and potentially send feedback messages.
    # 8. Handle exceptions during processing. Send error feedback to the user.


print("DEBUG: command_router.py module loaded.")
