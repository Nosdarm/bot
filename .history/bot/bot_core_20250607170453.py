# bot/bot_core.py

import os
import json
import discord
import asyncio
import traceback
import logging
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
        await self.load_all_cogs()

    async def load_all_cogs(self):
        await self.wait_until_ready()
        print("RPGBot: Loading Cogs...")
        try:
            await self.load_extension("bot.command_modules.general_cmds")
            await self.load_extension("bot.command_modules.game_setup_cmds")
            await self.load_extension("bot.command_modules.exploration_cmds")
            await self.load_extension("bot.command_modules.action_cmds")
            await self.load_extension("bot.command_modules.gm_app_cmds")
            await self.load_extension("bot.command_modules.inventory_cmds")
            await self.load_extension("bot.command_modules.party_cmds")
            await self.load_extension("bot.command_modules.utility_cmds")
            print("RPGBot: All command module Cogs loaded.")
        except Exception as e:
            print(f"RPGBot: Error loading cogs: {e}")
            import traceback
            traceback.print_exc()

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

    async def on_ready(self):
        if self.user:
            print(f'Logged in as {self.user.name} ({self.user.id})')
        else:
            print("Bot logged in, but self.user is None.")
        if self.game_manager:
            print("GameManager is initialized in RPGBot.")

        print('Syncing command tree...')
        if self.debug_guild_ids:
            print(f"Debugging slash commands on guilds: {self.debug_guild_ids}")
            for guild_id_val in self.debug_guild_ids:
                guild = discord.Object(id=guild_id_val)
                await self.tree.sync(guild=guild)
            print(f"Command tree synced to {len(self.debug_guild_ids)} debug guild(s).")
        else:
            await self.tree.sync()
            print("Command tree synced globally.")
        print('Bot is ready!')

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
    global _rpg_bot_instance_for_global_send, LOADED_TEST_GUILD_IDS, global_game_manager

    print("--- RPG Bot Core: Starting ---")
    load_dotenv()
    print(f"DEBUG: Value from os.getenv('DISCORD_TOKEN') AFTER load_dotenv(): {os.getenv('DISCORD_TOKEN')}")

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
        await game_manager.setup()
        game_manager_setup_successful = True # Set flag on successful setup
        if game_manager_setup_successful:
            print("GameManager setup() successful.")
    except Exception as e:
        print(f"❌ FATAL: GameManager.setup() failed: {e}")
        traceback.print_exc()
        return

    print("Starting Discord bot (RPGBot)...")
    try:
        await rpg_bot.start(TOKEN)
    except discord.errors.LoginFailure:
        print("❌ FATAL: Invalid Discord token. Please check your DISCORD_TOKEN.")
    except Exception as e:
        print(f"❌ FATAL: RPGBot.start() error: {e}")
        traceback.print_exc()
    finally:
        print("Application shutting down...")
        if game_manager:
            print("Shutting down GameManager...")
            await game_manager.shutdown()
            print("GameManager shutdown complete.")
        if rpg_bot and not rpg_bot.is_closed():
            print("Closing Discord connection...")
            await rpg_bot.close()
            print("Discord connection closed.")

def run_bot():
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("Interrupted by user (KeyboardInterrupt), exiting.")
    except Exception as e:
        print(f"Error running bot: {e}")
        traceback.print_exc()
    finally:
        print("Application finished.")


if __name__ == "__main__":
    run_bot()
