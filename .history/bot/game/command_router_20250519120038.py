# bot/game/command_router.py

print("--- Начинается загрузка: command_router.py")

import asyncio
import traceback
import shlex # For better argument parsing (handles quotes)
# Import typing components
from typing import Optional, Dict, Any, Callable, Awaitable, List, Set, TYPE_CHECKING, ClassVar, Union # Добавляем Union для Type Hint

# Import discord types for type hints
from discord import Message # Used in route method signature, handle_* signatures


if TYPE_CHECKING:
    # --- Imports for Type Checking ---
    # Discord types used in method signatures or context
    from discord import Message # Already imported above, but good to list here for completeness if needed elsewhere
    # from discord import Guild # Example if guild object is passed in context
    from discord import Client # If client is passed in context or needs type hint

    # Models (needed for type hints or isinstance checks if they cause cycles elsewhere)
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
SendToChannelCallback = Callable[..., Awaitable[Any]]
SendCallbackFactory = Callable[[int], SendToChannelCallback]


# --- Command Decorator ---
_command_registry: Dict[str, Callable[..., Awaitable[Any]]] = {} # Global command registry

def command(keyword: str) -> Callable:
    """Decorator to register a method as a command handler."""
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
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
        send_callback_factory: SendCallbackFactory,
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
        # TODO: Add DialogueManager etc.
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

        self._command_prefix: str = self._settings.get('command_prefix', '/')
        if not isinstance(self._command_prefix, str) or not self._command_prefix:
            print(f"CommandRouter Warning: Invalid command prefix in settings: '{self._settings.get('command_prefix')}'. Defaulting to '/'.")
            self._command_prefix = '/'


        print("CommandRouter initialized.")

    async def route(self, message: Message) -> None:
        """Routes a Discord message to the appropriate command handler."""
        if not message.content or not message.content.startswith(self._command_prefix):
            return

        try:
            command_line = message.content[len(self._command_prefix):].strip()
            if not command_line:
                 return

            split_command = shlex.split(command_line)
            command_keyword = split_command[0].lower()
            command_args = split_command[1:]

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
        context: Dict[str, Any] = {
            'message': message,
            'author_id': str(message.author.id),
            'guild_id': str(message.guild.id) if message.guild else None,
            'channel_id': message.channel.id,
            'command_keyword': command_keyword,
            'command_args': command_args,

            # Pass all stored managers and processors
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

            # Optional managers/processors
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
            # TODO: Add dialogue_manager etc.
        }

        # --- Execute the handler ---
        try:
            await handler(self, message, command_args, context)

        except Exception as e:
            print(f"CommandRouter ❌ Error executing command '{command_keyword}': {e}")
            import traceback
            traceback.print_exc()
            try:
                 send_callback = context['send_callback_factory'](message.channel.id) # Use context['send_callback_factory']
                 await send_callback(f"❌ Произошла ошибка при выполнении команды `{self._command_prefix}{command_keyword}`: {e}")
            except Exception as cb_e:
                 print(f"CommandRouter Error sending execution error message: {cb_e}")

    # --- Command Handler Methods ---

    @command("help")
    async def handle_help(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает список доступных команд или помощь по конкретной команде."""
        send_callback = context['send_callback_factory'](context['channel_id'])
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
                await send_callback(f"Помощь по команде `{command_prefix}{target_command}`:\n{docstring}")
            else:
                await send_callback(f"❓ Команда `{target_command}` не найдена.")
        print(f"CommandRouter: Processed help command for guild {context.get('guild_id')}.")


    @command("character") # Handler for "/character" commands
    async def handle_character(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """
        Управляет персонажами (создание, статы, инвентарь и т.д.).
        Использование:
        `{prefix}character create <имя_персонажа>` - Создать нового персонажа.
        `{prefix}character stats [<ID персонажа>]` - Показать статистику.
        `{prefix}character inventory [<ID персонажа>]` - Показать инвентарь.
        `{prefix}character delete [<ID персонажа>]` - Удалить персонажа.
        (И другие, если реализованы)
        """.format(prefix=self._command_prefix)

        send_callback = context['send_callback_factory'](context['channel_id'])
        guild_id = context['guild_id']
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Команды персонажа доступны только на сервере.")
            return

        if not args:
            await send_callback(self.handle_character.__doc__) # Show usage if no subcommand
            return

        subcommand = args[0].lower()
        subcommand_args = args[1:]

        char_manager = context.get('character_manager') # Type: Optional["CharacterManager"]
        # Need other managers for specific subcommands, get them within the subcommand blocks
        # char_view_service = context.get('character_view_service')
        # char_action_processor = context.get('character_action_processor')

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

                # FIX: Removed the explicit 'guild_id=guild_id' argument here
                # Guild ID is already in the context dictionary and will be passed via **context
                new_character = await char_manager.create_character(
                    discord_id=author_id_int,
                    name=character_name,
                    # guild_id=guild_id,  # <-- REMOVED THIS REDUNDANT ARGUMENT
                    **context # Pass entire context dictionary (which includes guild_id)
                )

                if new_character:
                    char_name = getattr(new_character, 'name', character_name)
                    char_id = getattr(new_character, 'id', 'N/A')
                    await send_callback(f"✨ Ваш персонаж **{char_name}** успешно создан! (ID: `{char_id}`).") # Use Ваш for user's char
                    print(f"CommandRouter: Character '{char_name}' (ID: {char_id}) created for user {author_id_int} in guild {guild_id}.")
                else:
                    # Creation failed (e.g., name taken, already has a char) - Manager should print detailed reason
                    await send_callback(f"❌ Не удалось создать персонажа **{character_name}**. Возможно, имя занято или у вас уже есть персонаж в этой гильдии.")
                    print(f"CommandRouter: Failed to create character '{character_name}' for user {author_id_int} in guild {guild_id}.")

            except ValueError as ve:
                 await send_callback(f"❌ Ошибка создания персонажа: {ve}")
                 print(f"CommandRouter Error: Validation error creating character: {ve} for user {author_id} in guild {guild_id}.")
            except Exception as e:
                print(f"CommandRouter Error creating character for user {author_id} in guild {guild_id}: {e}")
                import traceback
                traceback.print_exc()
                await send_callback(f"❌ Произошла ошибка при создании персонажа: {e}")

        elif subcommand == "delete":
            # Handle /character delete [<char_id>]
            # If no char_id is provided, attempt to delete the user's own character

            char_id_to_delete: Optional[str] = None
            target_char: Optional["Character"] = None # Store the target character object

            if subcommand_args:
                 # Assume first subcommand arg is a character ID
                 char_id_to_delete = subcommand_args[0]
                 # Get the character object by the provided ID (use get_character with guild_id)
                 target_char = char_manager.get_character(guild_id, char_id_to_delete)

                 if not target_char:
                      await send_callback(f"❌ Персонаж с ID `{char_id_to_delete}` не найден в этой гильдии.")
                      return # Exit if character by ID is not found
            else:
                 # No ID provided, get player's own character by Discord ID
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
                     target_char = player_char # Found player's character
                     char_id_to_delete = getattr(player_char, 'id', 'N/A') # Get character ID safely for logging
                 else:
                     await send_callback("❌ У вас еще нет персонажа, который можно было бы удалить.")
                     return # Cannot delete if no character

            # At this point, target_char should be a Character object if found, otherwise we returned early.
            if target_char is None: # This check is technically redundant due to returns above, but safe.
                 await send_callback("❌ Не удалось определить, какого персонажа удалить.")
                 return

            # Double-check that the character belongs to this guild (already done in get_character, but reinforce)
            char_guild_id = getattr(target_char, 'guild_id', None)
            if str(char_guild_id) != str(guild_id):
                 # This should not happen if get_character is used correctly, but defensive
                 print(f"CommandRouter Error: Mismatched guild_id for deletion: Char {getattr(target_char, 'id', 'N/A')} is in guild {char_guild_id}, but command is from guild {guild_id}.")
                 await send_callback("❌ Произошла ошибка: Персонаж найден, но не принадлежит к этому серверу.") # More user-friendly message
                 return


            # Check if the user has permission to delete this character (e.g., is it their character? is it a GM command?)
            # For simplicity, let's assume a user can only delete their OWN character for now.
            # You would add GM permission checks if needed.
            author_id_int_check: Optional[int] = None
            try:
                if author_id is not None: author_id_int_check = int(author_id)
            except (ValueError, TypeError): pass # Already handled above, but defensive

            if author_id_int_check is None or getattr(target_char, 'discord_user_id', None) != author_id_int_check:
                 # Check if the user is the owner of the character
                 await send_callback("❌ Вы можете удалить только своего персонажа.")
                 return # User is not the owner

            # Now we can safely call the manager's remove_character method
            try:
                # CharacterManager.remove_character expects character_id, guild_id, **kwargs
                # It handles cleanup and marking for DB deletion
                deleted_char_id = await char_manager.remove_character(
                    character_id=getattr(target_char, 'id'), # Use the actual char ID from the object
                    guild_id=guild_id, # Pass guild_id string
                    **context # Pass full context (including send_callback_factory if needed by cleanup)
                )

                if deleted_char_id:
                    char_name = getattr(target_char, 'name', 'персонаж')
                    await send_callback(f"🗑️ Ваш персонаж **{char_name}** (ID: `{deleted_char_id}`) успешно удален.")
                    print(f"CommandRouter: Character {deleted_char_id} ({char_name}) deleted by user {author_id} in guild {guild_id}.")
                else:
                    # Should ideally not happen if target_char was found, but fallback
                    await send_callback(f"❌ Не удалось удалить персонажа с ID `{char_id_to_delete}`.")
                    print(f"CommandRouter: remove_character returned None for {char_id_to_delete} in guild {guild_id}.")

            except Exception as e:
                print(f"CommandRouter Error deleting character {char_id_to_delete} for user {author_id} in guild {guild_id}: {e}")
                import traceback
                traceback.print_exc()
                await send_callback(f"❌ Произошла ошибка при удалении персонажа: {e}")


        # Add other subcommands for "character" here if needed (rename, etc.)
        # elif subcommand == "rename": ...
        # elif subcommand == "equip": ...
        # elif subcommand == "use": ...


        else:
            # Unknown subcommand for /character
            await send_callback(f"Неизвестное действие для персонажа: `{subcommand}`. Доступные действия: `create`, `delete` (и другие, если реализованы).\nИспользование: `{self._command_prefix}character <действие> [аргументы]`")
            print(f"CommandRouter: Unknown character subcommand: '{subcommand}' in guild {guild_id}.")


    # --- Implement Stats as a TOP-LEVEL command ---
    @command("status") # Handler for "/status"
    async def handle_status(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает статистику вашего персонажа или персонажа по ID. Использование: `[<ID персонажа>]`"""
        send_callback = context['send_callback_factory'](context['channel_id'])
        guild_id = context['guild_id']
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
            # Assuming get_character signature is get_character(guild_id: str, character_id: str)
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

            # Assuming get_character_by_discord_id signature is get_character_by_discord_id(guild_id: str, discord_user_id: int)
            player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int)
            if player_char:
                target_char = player_char
            else:
                await send_callback(f"❌ У вас еще нет персонажа. Создайте его командой `{self._command_prefix}character create <имя>`")
                return

        if target_char is None:
             await send_callback("❌ Не удалось определить, чьи статы показать.")
             return

        try:
            # ИСПРАВЛЕНО ЗДЕСЬ: Изменено имя метода на get_character_sheet_embed
            stats_embed = await char_view_service.get_character_sheet_embed(target_char, context=context) # <-- ИСПРАВЛЕНО

            if stats_embed:
                 await send_callback(embed=stats_embed)
                 print(f"CommandRouter: Sent status embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")
            else:
                 await send_callback(f"❌ Не удалось сгенерировать статистику для персонажа **{getattr(target_char, 'name', 'N/A')}**.")
                 print(f"CommandRouter: Failed to generate status embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")

        except Exception as e:
            print(f"CommandRouter Error generating status embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при получении статистики: {e}")


    # --- Implement Inventory as a TOP-LEVEL command ---
    @command("inventory") # Handler for "/inventory"
    async def handle_inventory(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Показывает инвентарь вашего персонажа или персонажа по ID. Использование: `[<ID персонажа>]`"""
        send_callback = context['send_callback_factory'](context['channel_id'])
        guild_id = context['guild_id']
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
                 await send_callback(f"❌ Не удалось сгенерировать инвентарь для персонажа **{getattr(target_char, 'name', 'N/A')}**.")
                 print(f"CommandRouter: Failed to generate inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}.")

        except Exception as e:
            print(f"CommandRouter Error generating inventory embed for character {getattr(target_char, 'id', 'N/A')} in guild {guild_id}: {e}")
            import traceback
            traceback.print_exc()
            await send_callback(f"❌ Произошла ошибка при получении инвентаря: {e}")


    # --- Implement Move as a TOP-LEVEL command ---
    @command("move") # Handler for "/move"
    async def handle_move(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
        """Перемещает вашего персонажа в указанную локацию. Использование: `<ID локации>`"""
        send_callback = context['send_callback_factory'](context['channel_id'])
        guild_id = context['guild_id']
        author_id = context['author_id']

        if guild_id is None:
            await send_callback("❌ Эту команду можно использовать только на сервере.")
            return

        if not args:
            await send_callback(f"Использование: `{self._command_prefix}move <ID локации>`")
            return

        target_location_id = args[0]

        char_manager = context.get('character_manager')
        char_action_processor = context.get('character_action_processor')

        if not char_manager or not char_action_processor:
             await send_callback("❌ Система перемещения или персонажей временно недоступна.")
             print(f"CommandRouter Error: character_manager or character_action_processor is None in move handler for guild {guild_id}.")
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
            await send_callback("❌ У вас еще нет персонажа.")
            return

        char_id = getattr(player_char, 'id', None)
        if char_id is None:
             await send_callback("❌ Не удалось определить ID вашего персонажа.")
             return

        try:
            # CharacterActionProcessor.process_move_action expects character_id, target_location_id, context
            # Processor is expected to send feedback messages directly.
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
            await send_callback(f"❌ Произошла ошибка при попытке перемещения: {e}")


    # @command("join_party") # Example command handler
    # async def handle_join_party(self, message: Message, args: List[str], context: Dict[str, Any]) -> None:
    #     """Присоединиться к партии. Использование: `[<ID партии>]`"""
    #     send_callback = context['send_callback_factory'](context['channel_id'])
    #     guild_id = context['guild_id']
    #     author_id = context['author_id']
    #
    #     if guild_id is None:
    #         await send_callback("❌ Эту команду можно использовать только на сервере.")
    #         return
    #
    #     char_manager = context.get('character_manager')
    #     party_manager = context.get('party_manager')
    #     party_action_processor = context.get('party_action_processor')
    #
    #     if not char_manager or not party_manager or not party_action_processor:
    #          await send_callback("❌ Система партий временно недоступна.")
    #          print(f"CommandRouter Error: party system managers/processors are None in join_party handler for guild {guild_id}.")
    #          return
    #
    #     author_id_int: Optional[int] = None
    #     try:
    #         if author_id is not None: author_id_int = int(author_id)
    #     except (ValueError, TypeError):
    #          await send_callback("❌ Не удалось определить ваш ID пользователя Discord.")
    #          print(f"CommandRouter Error: Invalid author_id format: {author_id}")
    #          return
    #
    #     if author_id_int is None:
    #          await send_callback("❌ Не удалось получить ваш ID пользователя Discord.")
    #          print(f"CommandRouter Error: author_id is None.")
    #          return
    #
    #
    #     player_char = char_manager.get_character_by_discord_id(guild_id, author_id_int)
    #     if not player_char:
    #         await send_callback("❌ У вас еще нет персонажа.")
    #         return
    #
    #     char_id = getattr(player_char, 'id', None)
    #     if char_id is None:
    #          await send_callback("❌ Не удалось определить ID вашего персонажа.")
    #          return
    #
    #     target_party_id: Optional[str] = None
    #     if args:
    #          target_party_id = args[0] # Assume first arg is party ID
    #     else:
    #          # TODO: Logic to find or create a party if no ID is provided?
    #          await send_callback(f"Использование: `{self._command_prefix}join_party <ID партии>`")
    #          return
    #
    #     target_party = party_manager.get_party(guild_id, target_party_id)
    #     if not target_party:
    #          await send_callback(f"❌ Партия с ID `{target_party_id}` не найдена в этой гильдии.")
    #          return
    #
    #     try:
    #         # PartyActionProcessor.process_join_party expects character_id, party_id, context
    #         # Processor is expected to send feedback messages directly.
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
    #         await send_callback(f"❌ Произошла ошибка при попытке присоединиться к партии: {e}")


    # TODO: Implement other top-level command handlers if needed (e.g., @command("party"), @command("event"), @command("look"), @command("interact"), @command("attack"), @command("use"), @command("craft"), etc.)
    # For commands that take subcommands (like "/party create", "/event start"), register the top-level keyword (@command("party"), @command("event"))
    # and handle the subcommand logic within the handler method (similar to how handle_character now works for "create").


# --- End of CommandRouter Class ---

print("DEBUG: command_router.py module loaded.")
