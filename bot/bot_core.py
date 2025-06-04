# bot/bot_core.py

import os
import json
import discord
import asyncio
import traceback
from typing import Optional, Dict, Any, List
from typing import Optional, Dict, Any, List

# Правильные импорты для slash commands и контекста
from discord.ext import commands # Changed to commands.Bot
from discord import Interaction, Member, TextChannel, Intents, app_commands # Specific imports
from dotenv import load_dotenv

# Импорты наших сервисов и менеджеров.
from bot.services.openai_service import OpenAIService
from bot.game.managers.game_manager import GameManager
# Эти импорты могут быть нужны если команды напрямую их используют или для аннотаций.
# Пока оставляем, но если RPGBot инкапсулирует GameManager, то прямые ссылки на
# CharacterManager, LocationManager, EventManager из команд должны идти через GameManager.
# from bot.game.managers.character_manager import CharacterManager
# from bot.game.managers.location_manager import LocationManager
# from bot.game.managers.event_manager import EventManager
# PersistenceManager из main.py не используется, GameManager создает свой SqliteAdapter
# from bot.game.persistence import PersistenceManager

# Импорты функций команд (Они должны быть определены в этих файлах и затем импортированы здесь)
import bot.command_modules.general_cmds
import bot.command_modules.game_setup_cmds
import bot.command_modules.exploration_cmds
import bot.command_modules.action_cmds
import bot.command_modules.inventory_cmds
import bot.command_modules.utility_cmds
# Импортируйте другие command_modules здесь


# --- Объявление функций проверки GM ---
# Эти функции ПРЕДПОЛАГАЮТСЯ определенными в bot.command_modules.game_setup_cmds
# и импортированными здесь в начале файла bot_core.py
# Мы будем вызывать их напрямую в функциях команд ниже.
from bot.command_modules.game_setup_cmds import is_master_or_admin, is_gm_channel # <-- Правильное место импорта

# Global configuration settings (константы вне классов и функций)
# intents = discord.Intents.default() # Now Intents is imported directly
# intents.members = True
# intents.guilds = True
# intents.message_content = True # Keep message content for flexibility
# This will be defined before RPGBot instantiation in start_bot() or passed to it.


# Global list of Guild IDs for rapid slash command testing
# This will be loaded from settings.json or environment variables.
# Example: TEST_GUILD_IDS = [123456789012345678, 987654321098765432]
LOADED_TEST_GUILD_IDS: List[int] = []


# --- Helper function to load settings (moved from main.py) ---
def load_settings_from_file(file_path: str) -> Dict[str, Any]:
    """
    Загружает настройки из JSON-файла.
    Если файла нет или он невалиден — возвращает пустой dict.
    """
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

# --- Definition of the RPGBot class ---
class RPGBot(commands.Bot): # Changed base class to commands.Bot
    def __init__(self, game_manager: Optional[GameManager], openai_service: OpenAIService, command_prefix: str, intents: Intents, debug_guild_ids: Optional[List[int]] = None): # debug_guilds not a param for commands.Bot
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.game_manager = game_manager
        self.debug_guild_ids = debug_guild_ids # Store it for later use in on_ready tree sync
        self.openai_service = openai_service # Though game_manager might also hold a reference to it

        # TODO: Review if global_openai_service is still needed by any command module directly
        # If so, they need to be updated to use self.openai_service or self.game_manager.openai_service
        global global_openai_service
        global_openai_service = self.openai_service

        # TODO: Review global_game_manager usage in command modules.
        # Commands should ideally get GameManager via ctx.bot.game_manager
        global global_game_manager
        global_game_manager = self.game_manager

        # self.add_application_commands_from_modules() # This will be handled by setup_hook

    async def setup_hook(self):
        print("RPGBot: Running setup_hook...")
        # TODO: Review if global_openai_service is still needed by any command module directly
        # If so, they need to be updated to use self.openai_service or self.game_manager.openai_service
        global global_openai_service
        global_openai_service = self.openai_service

        # TODO: Review global_game_manager usage in command modules.
        # Commands should ideally get GameManager via ctx.bot.game_manager
        global global_game_manager
        global_game_manager = self.game_manager

        self.add_application_commands_from_modules()

    async def on_ready(self):
        if self.user:
            print(f'Logged in as {self.user.name} ({self.user.id})')
        else:
            print("Bot logged in, but self.user is None.") # Or handle as an error
        if self.game_manager:
            print("GameManager is initialized in RPGBot.")

        print('Syncing command tree...')
        if self.debug_guild_ids:
            print(f"Debugging slash commands on guilds: {self.debug_guild_ids}")
            for guild_id_val in self.debug_guild_ids: # Iterate over the stored list
                guild = discord.Object(id=guild_id_val) # Use discord.Object
                await self.tree.sync(guild=guild)
            print(f"Command tree synced to {len(self.debug_guild_ids)} debug guild(s).")
        else:
            await self.tree.sync()
            print("Command tree synced globally.")
        print('Bot is ready!')

    def add_application_commands_from_modules(self):
        # This approach assumes command functions are decorated with @slash_command
        # and are available in the imported modules.
        # discord.py V2 automatically discovers these in cogs or if added via self.add_application_command.
        # For functions directly decorated, we need to add them to the CommandTree.

        # General commands
        self.tree.add_command(bot.command_modules.general_cmds.cmd_ping)

        # Game setup commands
        # self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_start_game) # Placeholder
        # self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_join_game) # Placeholder
        self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_start_new_character) # New /start command
        self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_set_bot_language) # Add new /set_bot_language command
        # TODO: Verify and restore cmd_set_master_channel and cmd_set_system_channel if they exist in game_setup_cmds.py
        # self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_set_master_channel)
        # self.tree.add_command(bot.command_modules.game_setup_cmds.cmd_set_system_channel)
        # TODO: Add other game_setup_cmds (set_gm, set_gm_channel, etc.)

        # Exploration commands
        self.tree.add_command(bot.command_modules.exploration_cmds.cmd_look)
        self.tree.add_command(bot.command_modules.exploration_cmds.cmd_move)
        self.tree.add_command(bot.command_modules.exploration_cmds.cmd_check)

        # Action commands
        self.tree.add_command(bot.command_modules.action_cmds.cmd_interact) # Placeholder, needs refactor
        self.tree.add_command(bot.command_modules.action_cmds.cmd_fight) # Refactored from cmd_attack
        self.tree.add_command(bot.command_modules.action_cmds.cmd_talk)

        # Inventory commands
        self.tree.add_command(bot.command_modules.inventory_cmds.cmd_inventory)
        self.tree.add_command(bot.command_modules.inventory_cmds.cmd_pickup)

        # Utility commands
        self.tree.add_command(bot.command_modules.utility_cmds.cmd_undo)
        self.tree.add_command(bot.command_modules.utility_cmds.cmd_lang) # Add the new /lang command

        # Simulation Trigger Command
        # cmd_gm_simulate is already an app_command.Command, so it should be added directly.
        self.tree.add_command(cmd_gm_simulate) # Defined below

# --- Global Helper for sending messages (e.g., from GameManager) ---
# This needs access to the bot instance.
# Option 1: Pass bot instance around.
# Option 2: RPGBot sets a global instance of itself (less ideal but might be needed for now).
_rpg_bot_instance_for_global_send: Optional[RPGBot] = None

async def global_send_message(channel_id: int, content: str, **kwargs):
    if _rpg_bot_instance_for_global_send:
        channel = _rpg_bot_instance_for_global_send.get_channel(channel_id)
        if channel:
            # Check if the channel type is appropriate for sending messages
            if isinstance(channel, (discord.TextChannel, discord.Thread, discord.DMChannel, discord.VoiceChannel)):
                try:
                    await channel.send(content, **kwargs)
                except discord.errors.Forbidden:
                    print(f"Error: Bot does not have permissions to send messages to channel {channel_id}.")
                except discord.errors.HTTPException as e:
                    print(f"Error: Failed to send message to channel {channel_id} due to HTTP exception: {e}")
                except Exception as e:
                    print(f"Error sending message via global_send_message to channel {channel_id}: {e}")
            else:
                print(f"Warning: Channel {channel_id} is of type {type(channel).__name__}, which cannot send messages.")
        else:
            print(f"Warning: Channel {channel_id} not found by global_send_message.")
    else:
        print("Warning: _rpg_bot_instance_for_global_send not set. Cannot send message.")


# --- Simulation Trigger Command (GM only) - DEFINITION as a separate function ---
# Accesses GameManager via ctx.bot.game_manager if commands are structured as Cogs or similar.
# For now, might still rely on global_game_manager or pass explicitly.
# If this is registered to RPGBot, it can access self.game_manager through interaction.client
@app_commands.command(name="gm_simulate", description="ГМ: Запустить один шаг симуляции мира.")
# guild_ids will be set dynamically when RPGBot is initialized if LOADED_TEST_GUILD_IDS has values.
# For now, remove here and let RPGBot handle it or add it back if this is registered globally.
# guild_ids=LOADED_TEST_GUILD_IDS
async def cmd_gm_simulate(interaction: Interaction): # Changed ctx to interaction
    # Access bot and game_manager from context
    bot_instance = interaction.client # Correct way to access bot
    if not isinstance(bot_instance, RPGBot):
        await interaction.response.send_message("Error: Bot instance is not configured correctly.", ephemeral=True)
        return

    game_mngr = bot_instance.game_manager

    # TODO: Update is_master_or_admin and is_gm_channel to accept interaction and use game_mngr
    # from bot.command_modules.game_setup_cmds import is_master_or_admin
    # For now, assume it's okay or True for testing this structural change
    # if not is_master_or_admin(interaction, game_mngr): # Placeholder for updated check
    #     await interaction.response.send_message("**Мастер:** Только Истинный Мастер может управлять ходом времени!", ephemeral=True)
    #     return

    # TODO: Update is_master_or_admin and is_gm_channel to accept interaction and use game_mngr
    # from bot.command_modules.game_setup_cmds import is_master_or_admin
    # For now, assume it's okay or True for testing this structural change
    # if not is_master_or_admin(interaction, game_mngr): # Placeholder for updated check
    #     await interaction.response.send_message("**Мастер:** Только Истинный Мастер может управлять ходом времени!", ephemeral=True)
    #     return

    await interaction.response.defer(ephemeral=True) # Defer response

    if not interaction.guild_id:
        await interaction.followup.send("**Мастер:** Эту команду можно использовать только на сервере (в гильдии).", ephemeral=True)
        return

    if game_mngr:
        try:
            await game_mngr.trigger_manual_simulation_tick(server_id=interaction.guild_id)
            await interaction.followup.send("**Мастер:** Шаг симуляции мира (ручной) завершен!")
        except Exception as e:
            print(f"Error in cmd_gm_simulate calling trigger_manual_simulation_tick: {e}")
            traceback.print_exc()
            await interaction.followup.send(f"**Мастер:** Ошибка при выполнении ручного шага симуляции: {e}", ephemeral=True)
    else:
        await interaction.followup.send("**Мастер:** Не удалось запустить симуляцию, менеджер игры недоступен или игра не начата. Используйте `/start_game`.", ephemeral=True)


# --- Main Bot Entry Point ---
async def start_bot():
    global _rpg_bot_instance_for_global_send, LOADED_TEST_GUILD_IDS # Allow modification

    print("--- RPG Bot Core: Starting ---")
    load_dotenv()
    print(f"DEBUG: Value from os.getenv('DISCORD_TOKEN') AFTER load_dotenv(): {os.getenv('DISCORD_TOKEN')}")

    # 1. Load all settings
    # Primary settings file
    settings = load_settings_from_file('settings.json')
    # Override/supplement with data/settings.json if it exists
    data_settings = load_settings_from_file('data/settings.json')
    settings.update(data_settings) # data_settings will overwrite common keys from settings.json

    # 2. Consolidate critical configurations (Env > settings.json > data/settings.json)
    TOKEN = os.getenv('DISCORD_TOKEN') or settings.get('discord_token')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') or settings.get('openai_api_key')
    COMMAND_PREFIX = os.getenv('COMMAND_PREFIX') or settings.get('discord_command_prefix', '!') # Default '!'
    DATABASE_PATH = os.getenv('DATABASE_PATH') or settings.get('database_path', 'game_state.db') # Default 'game_state.db'
    print(f"CRITICAL_DEBUG: Bot is using database at absolute path: {os.path.abspath(DATABASE_PATH)}")


    # Load TEST_GUILD_IDS from settings (env var could be a comma-separated string)
    test_guild_ids_str = os.getenv('TEST_GUILD_IDS')
    if test_guild_ids_str:
        LOADED_TEST_GUILD_IDS = [int(gid.strip()) for gid in test_guild_ids_str.split(',')]
    else:
        LOADED_TEST_GUILD_IDS = settings.get('test_guild_ids', []) # Expect a list in JSON

    if not TOKEN:
        print("❌ FATAL: Discord token not provided (env DISCORD_TOKEN or settings.json). Cannot start bot.")
        return

    # Prepare OpenAI settings for GameManager
    if 'openai_settings' not in settings:
        settings['openai_settings'] = {}
    if OPENAI_API_KEY:
        settings['openai_settings']['api_key'] = OPENAI_API_KEY
        print("OpenAI API Key configured for GameManager.")
    else:
        print("Warning: OpenAI API Key not found. OpenAI features will be disabled.")
        settings['openai_settings']['api_key'] = None # Ensure it's explicitly None if not found

    # 3. Initialize services
    # OpenAIService is initialized within GameManager's setup based on settings.
    # So, we don't need to create a separate global one here if GM handles it.
    # However, RPGBot constructor takes one, and some commands might still expect a global one.
    # For now, let's initialize one here and pass it.
    openai_service = OpenAIService(api_key=OPENAI_API_KEY)
    if not openai_service.is_available():
        print("OpenAIService is not available (key missing or invalid).")

    # 4. Initialize RPGBot (which is the discord client)
        # Define intents here before passing to RPGBot
    bot_intents = Intents.default()
    bot_intents.members = True
    bot_intents.guilds = True
    bot_intents.message_content = True

    rpg_bot = RPGBot(
        game_manager=None,
        openai_service=openai_service,
        command_prefix=COMMAND_PREFIX,
        intents=bot_intents,
        debug_guild_ids=LOADED_TEST_GUILD_IDS if LOADED_TEST_GUILD_IDS else None # Pass debug_guild_ids
    )
    _rpg_bot_instance_for_global_send = rpg_bot

    # 5. Initialize GameManager
    # GameManager needs the discord client (RPGBot instance)
    game_manager = GameManager(
        discord_client=rpg_bot, # Pass the bot instance
        settings=settings,      # Pass consolidated settings
        db_path=DATABASE_PATH
    )
    rpg_bot.game_manager = game_manager # Now set the game_manager in RPGBot

    # Update the global_game_manager reference now that it's fully initialized
    # TODO: phase this out by updating command modules
    global global_game_manager
    global_game_manager = game_manager
    # Update the global_game_manager reference now that it's fully initialized
    # TODO: phase this out by updating command modules
    global global_game_manager
    global_game_manager = game_manager

    print("GameManager instantiated. Running setup...")
    try:
        await game_manager.setup() # This also loads game state
        print("GameManager setup() successful.")
    except Exception as e:
        print(f"❌ FATAL: GameManager.setup() failed: {e}")
        traceback.print_exc()
        # Consider not starting the bot if GM setup fails
        return

    # 6. Start the bot
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
        if not rpg_bot.is_closed():
            print("Closing Discord connection...")
            await rpg_bot.close()
            print("Discord connection closed.")

# --- Synchronous wrapper to run the bot ---
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