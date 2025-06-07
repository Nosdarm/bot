# bot/bot_core.py

import os
import json
import discord
import asyncio
import traceback
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

# Правильные импорты для slash commands и контекста
from discord.ext import commands
from discord import Interaction, Member, TextChannel, Intents, app_commands
from dotenv import load_dotenv

# Импорты наших сервисов и менеджеров.
from bot.services.openai_service import OpenAIService
from bot.game.managers.game_manager import GameManager

from bot.nlu.player_action_parser import parse_player_action
from bot.services.nlu_data_service import NLUDataService

# Direct imports for command modules being converted to Cogs are removed.
# Old style helper imports might be removed if those helpers are now part of Cogs.
# from bot.command_modules.game_setup_cmds import is_master_or_admin, is_gm_channel # Now part of GameSetupCog

LOADED_TEST_GUILD_IDS: List[int] = []


def load_settings_from_file(file_path: str) -> Dict[str, Any]:
    try:
        if os.path.exists(file_path):
            print(f"Loading settings from '{file_path}'...")
            with open(file_path, encoding='utf-8') as f:
                settings_data = json.load(f)
                print(f"Settings loaded successfully from '{file_path}'.")
                return settings_data
        else:
            print(f"Warning: settings file '{file_path}' not found, using empty settings for this file.")
            return {}
    except json.JSONDecodeError:
         print(f"Error: Invalid JSON in settings file '{file_path}'. Using empty settings for this file.")
         return {}
    except Exception as e:
        print(f"Error loading settings from '{file_path}': {e}")
        return {}

class RPGBot(commands.Bot):
    def __init__(self, game_manager: Optional[GameManager], openai_service: OpenAIService, command_prefix: str, intents: Intents, debug_guild_ids: Optional[List[int]] = None):
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.game_manager = game_manager
        self.debug_guild_ids = debug_guild_ids
        self.openai_service = openai_service

        global global_openai_service
        global_openai_service = self.openai_service
        global global_game_manager
        global_game_manager = self.game_manager

    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command:
            command_name = interaction.data.get('name', 'Unknown Command')
            logging.info(
                f"Received application command '/{command_name}' "
                f"from user {interaction.user.name} ({interaction.user.id}) "
                f"in guild {interaction.guild_id or 'DM'} "
                f"channel {interaction.channel_id or 'DM'}"
            )
        # The command tree will process the interaction further.

    async def setup_hook(self):
        logging.info(f"{datetime.now()} - RPGBot: Entering setup_hook.")
        await self.load_all_cogs()
        logging.info(f"{datetime.now()} - RPGBot: Exiting setup_hook (after load_all_cogs).")

    async def load_all_cogs(self):
        logging.info(f"{datetime.now()} - RPGBot: load_all_cogs waiting for bot to be ready...")
        await self.wait_until_ready() 
        logging.info(f"{datetime.now()} - RPGBot: Bot is ready, proceeding to load cogs.")
        
        cog_list = [
            "bot.command_modules.general_cmds",
            "bot.command_modules.game_setup_cmds",
            "bot.command_modules.exploration_cmds",
            "bot.command_modules.action_cmds",
            "bot.command_modules.gm_app_cmds",
            "bot.command_modules.inventory_cmds",
            "bot.command_modules.party_cmds",
            "bot.command_modules.utility_cmds"
        ]
        
        all_cogs_loaded_successfully = True
        for cog_name in cog_list:
            try:
                logging.info(f"{datetime.now()} - RPGBot: Attempting to load cog '{cog_name}'...")
                await self.load_extension(cog_name)
                logging.info(f"{datetime.now()} - RPGBot: Successfully loaded cog '{cog_name}'.")
            except Exception as e:
                logging.error(f"{datetime.now()} - RPGBot: Failed to load cog '{cog_name}'. Error: {e}", exc_info=True)
                # Print traceback for immediate visibility during development
                import traceback
                traceback.print_exc()
                all_cogs_loaded_successfully = False # Mark that at least one cog failed

        if all_cogs_loaded_successfully:
            logging.info(f"{datetime.now()} - RPGBot: All command module Cogs loaded successfully.")
        else:
            logging.error(f"{datetime.now()} - RPGBot: Finished loading cogs, but one or more cogs failed to load.")

    async def on_tree_command_error(self, interaction: Interaction, error: app_commands.AppCommandError):
        import traceback
        print(f"Unhandled error in command tree for command invoked by {interaction.user.name} ({interaction.user.id}) in guild {interaction.guild_id or 'DM'}")
        print(f"Command: {interaction.command.name if interaction.command else 'Unknown Command'}")
        print(f"Error type: {type(error)}")
        print(f"Error: {error}")
        # Log the full traceback
        traceback_str = traceback.format_exc()
        print("Traceback:")
        print(traceback_str)

        # Optionally, send a generic message to the user
        if interaction.response.is_done():
            await interaction.followup.send("Произошла непредвиденная ошибка при выполнении команды. Администратор был уведомлен.", ephemeral=True)
        else:
            await interaction.response.send_message("Произошла непредвиденная ошибка при выполнении команды. Администратор был уведомлен.", ephemeral=True)

    async def on_connect(self):
        logging.debug(f"{datetime.now()} - RPGBot: Entering on_connect handler...")
        logging.info(f"{datetime.now()} - RPGBot: Discord Bot connected to Gateway!")
        logging.debug(f"{datetime.now()} - RPGBot: Exiting on_connect handler.")

    async def on_disconnect(self):
        # Attempt to determine if the disconnect was clean or not.
        # This is a basic check; discord.py might not always provide explicit flags for unexpected disconnects here.
        # For more detailed analysis, one might need to handle specific exceptions in the main run loop or specific tasks.
        if self.is_closed(): # is_closed() is True if close() was called.
            logging.info(f"{datetime.now()} - RPGBot: Discord Bot disconnected from Gateway (Planned).")
        else:
            logging.warning(f"{datetime.now()} - RPGBot: Discord Bot disconnected from Gateway (Unexpected).")

    async def on_error(self, event_method: str, *args: Any, **kwargs: Any):
        logging.error(f"{datetime.now()} - RPGBot: Unhandled Discord event error in '{event_method}': Args: {args}, Kwargs: {kwargs}", exc_info=True)
        # Also print to console for immediate visibility during development
        print(f"ERROR: {datetime.now()} - RPGBot: Unhandled Discord event error in '{event_method}'. Check logs for details.")
        # You might want to print args and kwargs too, but they can be verbose.
        # print(f"Args: {args}")
        # print(f"Kwargs: {kwargs}")
        import traceback
        traceback.print_exc()

    async def on_ready(self):
        logging.debug(f"{datetime.now()} - RPGBot: Entering on_ready handler...")
        if self.user:
            logging.info(f"{datetime.now()} - RPGBot: Logged in as {self.user.name} ({self.user.id})")
        else:
            logging.warning(f"{datetime.now()} - RPGBot: Bot logged in, but self.user is None.")
        if self.game_manager:
            logging.info(f"{datetime.now()} - RPGBot: GameManager is initialized in RPGBot.")
        else:
            logging.warning(f"{datetime.now()} - RPGBot: GameManager is NOT initialized in RPGBot at on_ready.")

        logging.info(f"{datetime.now()} - RPGBot: Attempting to sync command tree...")
        try:
            if self.debug_guild_ids:
                logging.info(f"{datetime.now()} - RPGBot: Found {len(self.debug_guild_ids)} debug guild(s): {self.debug_guild_ids}")
                for guild_id_val in self.debug_guild_ids:
                    guild = discord.Object(id=guild_id_val)
                    logging.info(f"{datetime.now()} - RPGBot: Syncing command tree for debug guild {guild_id_val}...")
                    await self.tree.sync(guild=guild)
                    logging.info(f"{datetime.now()} - RPGBot: Successfully synced command tree for debug guild {guild_id_val}.")
                logging.info(f"{datetime.now()} - RPGBot: Command tree synced to {len(self.debug_guild_ids)} debug guild(s).")
            else:
                logging.info(f"{datetime.now()} - RPGBot: Syncing command tree globally...")
                await self.tree.sync()
                logging.info(f"{datetime.now()} - RPGBot: Successfully synced command tree globally.")
        except Exception as e:
            logging.error(f"{datetime.now()} - RPGBot: Error during command tree sync: {e}", exc_info=True)
        
        logging.info(f"{datetime.now()} - RPGBot: Command tree synchronization process completed.")
        logging.debug(f"{datetime.now()} - RPGBot: Exiting on_ready handler.")
        logging.info(f"{datetime.now()} - RPGBot: Bot is ready!")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Check if the message starts with the command prefix
        resolved_prefixes = await self.get_prefix(message)
        if resolved_prefixes:
            # Ensure resolved_prefixes is suitable for startswith (str or tuple of str)
            if isinstance(resolved_prefixes, str):
                if message.content.startswith(resolved_prefixes):
                    return  # It's a command, return early
            elif isinstance(resolved_prefixes, list): # Or tuple, though get_prefix typically returns list for multiple
                if message.content.startswith(tuple(p for p in resolved_prefixes if isinstance(p, str))):
                    return  # It's a command, return early

        if not self.game_manager:
            print("RPGBot: GameManager not available.")
            return
        if not message.guild:
            return

        player = await self.game_manager.get_player_by_discord_id(message.author.id, str(message.guild.id))
        if not player:
            return

        player_status = player.current_game_status
        player_language = player.selected_language or 'en'

        game_channels = self.game_manager.get_game_channel_ids(str(message.guild.id))
        if message.channel.id not in game_channels:
            return

        if player_status == 'исследование':
            if not hasattr(self.game_manager, 'nlu_data_service') or not self.game_manager.nlu_data_service:
                print(f"RPGBot: NLUDataService not available for guild {message.guild.id}")
                return

            nlu_data_svc = self.game_manager.nlu_data_service
            parsed_action = await parse_player_action(
                text=message.content,
                language=player_language,
                guild_id=str(message.guild.id),
                game_terms_db=nlu_data_svc
            )

            if parsed_action:
                intent, entities = parsed_action
                action_to_store = {"intent": intent, "entities": entities, "original_text": message.content}

                current_actions_str = player.collected_actions_json
                current_actions_list = []
                if current_actions_str:
                    try:
                        current_actions_list = json.loads(current_actions_str)
                    except json.JSONDecodeError:
                        current_actions_list = []
                    if not isinstance(current_actions_list, list):
                        current_actions_list = []

                current_actions_list.append(action_to_store)
                player.collected_actions_json = json.dumps(current_actions_list)

                if hasattr(self.game_manager, 'db_service') and self.game_manager.db_service:
                    await self.game_manager.db_service.update_player_field(
                        player_id=player.id,
                        field_name='collected_actions_json',
                        value=player.collected_actions_json,
                        guild_id=str(message.guild.id)
                    )
                    await message.add_reaction("👍")
                else:
                    print(f"RPGBot: DBService not available for updating player {player.id} in guild {message.guild.id}")
                    await message.add_reaction("⚠️")
            else:
                await message.add_reaction("❓")

        elif player_status in ['бой', 'диалог', 'торговля']:
            print(f"RPGBot: Message from {message.author.name} in status '{player_status}' ignored by NLU: {message.content}")
        else:
            print(f"RPGBot: Message from {message.author.name} in status '{player_status}' ignored by NLU (pending processing or other): {message.content}")
            await message.add_reaction("⏳")

_rpg_bot_instance_for_global_send: Optional[RPGBot] = None

async def global_send_message(channel_id: int, content: str, **kwargs):
    if _rpg_bot_instance_for_global_send:
        channel = _rpg_bot_instance_for_global_send.get_channel(channel_id)
        if channel:
            if isinstance(channel, discord.abc.Messageable):
                try:
                    await channel.send(content, **kwargs)
                except Exception as e:
                    print(f"Error sending message via global_send_message to channel {channel_id}: {e}")
            else:
                print(f"Warning: Channel {channel_id} is not Messageable (type: {type(channel)}). Cannot send message.")
        else:
            print(f"Warning: Channel {channel_id} not found by global_send_message.")
    else:
        print("Warning: _rpg_bot_instance_for_global_send not set. Cannot send message.")

async def start_bot():
    print("DEBUG_PRINT: Entered start_bot() function.") # New diagnostic print

    global _rpg_bot_instance_for_global_send, LOADED_TEST_GUILD_IDS, global_game_manager
    
    print("DEBUG_PRINT: About to configure logging.") # New diagnostic print
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True # Add force=True to ensure reconfiguration if already configured by another module
    )
    # Ensure this log is right after basicConfig
    logging.info(f"{datetime.now()} - RPGBot Core: start_bot() called.") # Existing, ensure it's here

    discord_logger = logging.getLogger('discord')
    discord_logger.setLevel(logging.DEBUG)
    discord_http_logger = logging.getLogger('discord.http')
    discord_http_logger.setLevel(logging.DEBUG)

    print("--- RPG Bot Core: Starting ---") # Existing print
    # logging.info(f"{datetime.now()} - RPGBot Core: --- RPG Bot Core: Starting ---") # This was moved up or duplicated by the required log line
    load_dotenv()
    # print(f"DEBUG: Value from os.getenv('DISCORD_TOKEN') AFTER load_dotenv(): {os.getenv('DISCORD_TOKEN')}") # Keep for debug if needed

    settings = load_settings_from_file('settings.json')
    data_settings = load_settings_from_file('data/settings.json')
    settings.update(data_settings)

    TOKEN = os.getenv('DISCORD_TOKEN') or settings.get('discord_token')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') or settings.get('openai_api_key')
    COMMAND_PREFIX = os.getenv('COMMAND_PREFIX') or settings.get('discord_command_prefix', '!')

    test_guild_ids_str = os.getenv('TEST_GUILD_IDS')
    if test_guild_ids_str:
        LOADED_TEST_GUILD_IDS = [int(gid.strip()) for gid in test_guild_ids_str.split(',')]
    else:
        LOADED_TEST_GUILD_IDS = settings.get('test_guild_ids', [])

    if not TOKEN:
        print("❌ FATAL: Discord token not provided (env DISCORD_TOKEN or settings.json). Cannot start bot.")
        return

    if 'openai_settings' not in settings:
        settings['openai_settings'] = {}
    if OPENAI_API_KEY:
        settings['openai_settings']['api_key'] = OPENAI_API_KEY
        print("OpenAI API Key configured for GameManager.")
    else:
        print("Warning: OpenAI API Key not found. OpenAI features will be disabled.")
        settings['openai_settings']['api_key'] = None

    openai_service = OpenAIService(api_key=OPENAI_API_KEY)
    if not openai_service.is_available():
        print("OpenAIService is not available (key missing or invalid).")

    bot_intents = Intents.default()
    bot_intents.members = True
    bot_intents.guilds = True
    bot_intents.message_content = True
    bot_intents.presences = True

    rpg_bot = RPGBot(
        game_manager=None,
        openai_service=openai_service,
        command_prefix=COMMAND_PREFIX,
        intents=bot_intents,
        debug_guild_ids=LOADED_TEST_GUILD_IDS if LOADED_TEST_GUILD_IDS else None
    )
    _rpg_bot_instance_for_global_send = rpg_bot

    game_manager = GameManager(
        discord_client=rpg_bot,
        settings=settings
    )
    rpg_bot.game_manager = game_manager
    global_game_manager = game_manager

    print("GameManager instantiated. Running setup...")
    game_manager_setup_successful = False
    try:
        await game_manager.setup() # Ensure global_game_manager is used if game_manager is local
        game_manager_setup_successful = True
        if game_manager_setup_successful: # Redundant check, if setup fails it raises
            print("GameManager setup() successful.")
            logging.info(f"{datetime.now()} - RPGBot Core: GameManager setup() successful.") # Added
    except Exception as e:
        print(f"❌ FATAL: GameManager.setup() failed: {e}")
        logging.exception("RPGBot Core: FATAL - GameManager.setup() failed.")
        return # Crucial: if GM setup fails, don't try to start the bot

    print("Starting Discord bot (RPGBot)...")
    # Avoid logging full token
    print(f"RPGBot: Calling rpg_bot.start(TOKEN) with token: {'******' if TOKEN else 'None'}") 
    
    try:
        logging.info(f"{datetime.now()} - RPGBot Core: PRE - Attempting await rpg_bot.start(TOKEN)...")
        await rpg_bot.start(TOKEN)
    except discord.errors.LoginFailure:
        print("❌ FATAL: Invalid Discord token. Please check your DISCORD_TOKEN.")
        logging.error("RPGBot Core: Discord login failure. Invalid token.")
    except asyncio.CancelledError:
        print("RPGBot Core: Bot startup was cancelled (e.g., KeyboardInterrupt).")
        logging.info("RPGBot Core: Bot startup was cancelled.")
    except Exception as e:
        print(f"❌ FATAL: RPGBot.start() exited with error: {e}")
        logging.exception("RPGBot Core: Error during rpg_bot.start() or general bot operation.")
    finally:
        print("RPGBot Core: Entered finally block for start_bot. Performing cleanup...")
        logging.info("RPGBot Core: Entered finally block for start_bot. Performing cleanup...")
        
        # Use global_game_manager for consistency as it's set up for this
        if global_game_manager: 
            print("Shutting down GameManager...")
            logging.info("RPGBot Core: Shutting down GameManager...")
            try:
                await global_game_manager.shutdown()
                print("GameManager shutdown complete.")
                logging.info("RPGBot Core: GameManager shutdown complete.")
            except Exception as e_gm:
                print(f"Error during GameManager shutdown: {e_gm}")
                logging.exception("RPGBot Core: Error during GameManager shutdown.")
        
        # Use _rpg_bot_instance_for_global_send for consistency
        if _rpg_bot_instance_for_global_send and not _rpg_bot_instance_for_global_send.is_closed():
            print("Closing Discord connection...")
            logging.info("RPGBot Core: Closing Discord connection...")
            try:
                await _rpg_bot_instance_for_global_send.close()
                print("Discord connection closed.")
                logging.info("RPGBot Core: Discord connection closed.")
            except Exception as e_dc:
                print(f"Error during Discord connection close: {e_dc}")
                logging.exception("RPGBot Core: Error during Discord connection close.")
        logging.info("RPGBot Core: Cleanup in start_bot's finally block finished.")

def run_bot():
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("run_bot: KeyboardInterrupt caught by run_bot. asyncio.run() should handle task cancellation.")
        logging.info("run_bot: KeyboardInterrupt caught by run_bot.")
    except Exception as e:
        print(f"run_bot: Unexpected error at top level: {e}")
        logging.exception("run_bot: Unexpected error at top level.")
    finally:
        print("run_bot: Application finished.")
        logging.info("run_bot: Application finished (from run_bot finally).") # Clarified source


if __name__ == "__main__":
    run_bot()
