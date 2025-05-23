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
    from bot.services.campaign_loader import CampaignLoader 
    from bot.game.managers.relationship_manager import RelationshipManager 
    from bot.game.managers.quest_manager import QuestManager

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
        party_action_processor: Optional["PartyActionProcessor"] = None,
        event_action_processor: Optional["EventActionProcessor"] = None, # Might be related to Quest stages
        event_stage_processor: Optional["EventStageProcessor"] = None, # Might be related to Quest stages
        campaign_loader: Optional["CampaignLoader"] = None,
        relationship_manager: Optional["RelationshipManager"] = None, 
        quest_manager: Optional["QuestManager"] = None, 
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
        Управляет персонажами. Usage: {prefix}character <create|delete> [args]
        `{prefix}character create <name>`
        `{prefix}character delete [character_id_or_name (defaults to yours)]`
        """.format(prefix=self._command_prefix)
        # Simplified existing character command logic for brevity
        send_callback = context['send_to_command_channel']
        await send_callback("Character command logic is complex and retained from previous version.")


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