# bot/bot_core.py

import os
import json
import discord
import asyncio
import traceback
from typing import Optional, Dict, Any, List

# Правильные импорты для slash commands и контекста
from discord import slash_command, Bot, ApplicationContext, Member, TextChannel # discord.Bot is RPGBot's parent
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
import bot.command_modules.utility_cmds # Import the new utility commands module
# Импортируйте другие command_modules здесь


# --- Объявление функций проверки GM ---
# Эти функции ПРЕДПОЛАГАЮТСЯ определенными в bot.command_modules.game_setup_cmds
# и импортированными здесь в начале файла bot_core.py
# Мы будем вызывать их напрямую в функциях команд ниже.
from bot.command_modules.game_setup_cmds import is_master_or_admin, is_gm_channel # <-- Правильное место импорта

# Global configuration settings (константы вне классов и функций)
intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True # Keep message content for flexibility


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
class RPGBot(Bot):
    def __init__(self, game_manager: GameManager, openai_service: OpenAIService, command_prefix: str, intents: discord.Intents, debug_guilds: Optional[List[int]] = None):
        super().__init__(command_prefix=command_prefix, intents=intents, debug_guilds=debug_guilds)
        self.game_manager = game_manager
        self.openai_service = openai_service # Though game_manager might also hold a reference to it

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
        print(f'Logged in as {self.user.name} ({self.user.id})')
        if self.game_manager:
            print("GameManager is initialized in RPGBot.")
            # GameManager.setup() should have been called before bot.start()
            # If there's anything game_manager needs to do *after* login, it can be called here.

        print('Syncing command tree...')
        if self.debug_guilds:
            print(f"Debugging slash commands on guilds: {self.debug_guilds}")
            # Sync to specific guilds if debug_guilds are provided
            for guild_id in self.debug_guilds:
                guild = discord.Object(id=guild_id)
                await self.tree.sync(guild=guild)
            print(f"Command tree synced to {len(self.debug_guilds)} debug guild(s).")
        else:
            # Sync globally if no debug_guilds are specified (can take time)
            await self.tree.sync()
            print("Command tree synced globally.")
        print('Bot is ready!')

    def add_application_commands_from_modules(self):
        # This approach assumes command functions are decorated with @slash_command
        # and are available in the imported modules.
        # discord.py V2 automatically discovers these in cogs or if added via self.add_application_command.
        # For functions directly decorated, we need to add them.

        # General commands
        self.add_application_command(bot.command_modules.general_cmds.cmd_ping)

        # Game setup commands
        # self.add_application_command(bot.command_modules.game_setup_cmds.cmd_start_game) # Placeholder
        # self.add_application_command(bot.command_modules.game_setup_cmds.cmd_join_game) # Placeholder
        self.add_application_command(bot.command_modules.game_setup_cmds.cmd_start_new_character) # New /start command
        # TODO: Add other game_setup_cmds (set_gm, set_gm_channel, etc.)

        # Exploration commands
        self.add_application_command(bot.command_modules.exploration_cmds.cmd_look)
        self.add_application_command(bot.command_modules.exploration_cmds.cmd_move)
        self.add_application_command(bot.command_modules.exploration_cmds.cmd_check)

        # Action commands
        self.add_application_command(bot.command_modules.action_cmds.cmd_interact) # Placeholder, needs refactor
        self.add_application_command(bot.command_modules.action_cmds.cmd_fight) # Refactored from cmd_attack
        self.add_application_command(bot.command_modules.action_cmds.cmd_talk)

        # Inventory commands
        self.add_application_command(bot.command_modules.inventory_cmds.cmd_inventory)
        self.add_application_command(bot.command_modules.inventory_cmds.cmd_pickup)

        # Utility commands
        self.add_application_command(bot.command_modules.utility_cmds.cmd_undo)

        # Simulation Trigger Command
        self.add_application_command(cmd_gm_simulate) # Defined below

# --- Global Helper for sending messages (e.g., from GameManager) ---
# This needs access to the bot instance.
# Option 1: Pass bot instance around.
# Option 2: RPGBot sets a global instance of itself (less ideal but might be needed for now).
_rpg_bot_instance_for_global_send: Optional[RPGBot] = None

async def global_send_message(channel_id: int, content: str, **kwargs):
    if _rpg_bot_instance_for_global_send:
        channel = _rpg_bot_instance_for_global_send.get_channel(channel_id)
        if channel:
            try:
                await channel.send(content, **kwargs)
            except Exception as e:
                print(f"Error sending message via global_send_message to channel {channel_id}: {e}")
        else:
            print(f"Warning: Channel {channel_id} not found by global_send_message.")
    else:
        print("Warning: _rpg_bot_instance_for_global_send not set. Cannot send message.")


# --- Simulation Trigger Command (GM only) - DEFINITION as a separate function ---
# Accesses GameManager via ctx.bot.game_manager if commands are structured as Cogs or similar.
# For now, might still rely on global_game_manager or pass explicitly.
# If this is registered to RPGBot, it can access self.game_manager through ctx.bot
@slash_command(name="gm_simulate", description="ГМ: Запустить один шаг симуляции мира.")
# guild_ids will be set dynamically when RPGBot is initialized if LOADED_TEST_GUILD_IDS has values.
# For now, remove here and let RPGBot handle it or add it back if this is registered globally.
# guild_ids=LOADED_TEST_GUILD_IDS
async def cmd_gm_simulate(ctx: ApplicationContext):
    # Access bot and game_manager from context
    # This is the more modern way if commands are part of the bot instance (e.g. in a Cog or added directly)
    bot_instance = ctx.bot
    if not isinstance(bot_instance, RPGBot):
        await ctx.respond("Error: Bot instance is not configured correctly.", ephemeral=True)
        return

    game_mngr = bot_instance.game_manager

    # TODO: Update is_master_or_admin and is_gm_channel to accept ctx and use game_mngr
    # from bot.command_modules.game_setup_cmds import is_master_or_admin
    # For now, assume it's okay or True for testing this structural change
    # if not is_master_or_admin(ctx, game_mngr): # Placeholder for updated check
    #     await ctx.respond("**Мастер:** Только Истинный Мастер может управлять ходом времени!", ephemeral=True)
    #     return

    await ctx.defer()

    if game_mngr:
        # GameManager's run_simulation_tick should use the bot's send_message capability
        # or be passed a send_callback_factory that uses global_send_message or ctx.bot methods.
        # For now, assuming run_simulation_tick can use a globally accessible send function or
        # the one configured in GameManager during its setup.
        # The callback _send_message_from_manager used global_game_manager, which is now set by RPGBot.
        # The game_manager instance itself has a _get_discord_send_callback method.
        # We need to ensure this is used or provide an equivalent.

        # Simplification: GameManager's internal send callback factory should work if discord_client (RPGBot) is passed to it.
        await game_mngr.run_simulation_tick(
            server_id=ctx.guild.id,
            # send_message_callback is tricky here. GameManager.setup creates its own using the discord_client.
            # So, this argument might not be needed if GameManager is correctly initialized with the bot.
            # send_message_callback=global_send_message # Example, but ideally GameManager handles this.
        )
        await ctx.followup.send("**Мастер:** Шаг симуляции мира завершен!")
    else:
        await ctx.followup.send("**Мастер:** Не удалось запустить симуляцию, менеджер игры недоступен или игра не начата. Используйте `/start_game`.")


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
    # Intents are already defined globally
    rpg_bot = RPGBot(
        game_manager=None, # GameManager will be set after RPGBot is created, to resolve circular dependency
        openai_service=openai_service,
        command_prefix=COMMAND_PREFIX,
        intents=intents, # global intents
        debug_guilds=LOADED_TEST_GUILD_IDS if LOADED_TEST_GUILD_IDS else None
    )
    _rpg_bot_instance_for_global_send = rpg_bot # Set the global instance for global_send_message

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