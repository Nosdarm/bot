# bot/bot_core.py

import os
from typing import Optional
import discord
# Правильные импорты для slash commands и контекста
from discord import slash_command, Bot, ApplicationContext, Member, TextChannel
from dotenv import load_dotenv

# Импорты наших сервисов и менеджеров. Bot_core напрямую нужен только GameManager,
# который инкапсулирует ActionProcessor, WorldSimulator, и другие менеджеры/правила.
# Убедитесь, что LocationManager импортирован, т.к. он используется в команде move
from bot.services.openai_service import OpenAIService
from bot.game.managers.game_manager import GameManager
# Если CharacterManager, LocationManager, EventManager используются здесь для аннотаций
# в глобальных переменных, они нужны.
from bot.game.managers.character_manager import CharacterManager
from bot.game.managers.location_manager import LocationManager
from bot.game.managers.event_manager import EventManager
from bot.game.persistence import PersistenceManager

# Импорты функций команд (Они должны быть определены в этих файлах и затем импортированы здесь)
import bot.command_modules.general_cmds
import bot.command_modules.game_setup_cmds
import bot.command_modules.exploration_cmds
import bot.command_modules.action_cmds
import bot.command_modules.inventory_cmds
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


# Global list of Guild IDs for rapid slash command testing (константы вне классов и функций)
TEST_GUILD_IDS = [] # <-- ADD YOUR TEST SERVER ID(s) HERE


# --- Temporary global references (Still needed until proper DI like Cogs) ---
# Эти переменные будут хранить ссылки на экземпляры, созданные в run_bot()
_rpg_bot_instance: Optional[Bot] = None # Instance of this Bot class
global_game_manager: Optional[GameManager] = None
global_openai_service: Optional[OpenAIService] = None # Still used directly by some commands/logic


# Helper function to retrieve the bot instance (outside classes/functions)
def get_bot_instance() -> Optional[Bot]:
    return _rpg_bot_instance

# Temporary global helper to send messages from managers/simulator (outside classes/functions)
# Designed to be passed as a callback
async def _send_message_from_manager(channel_id: int, content: str):
    # Get the bot instance using the temporary global helper
    bot_instance = get_bot_instance()

    if bot_instance:
        # Now use bot_instance to get the channel and send the message
        channel = bot_instance.get_channel(channel_id)
        if channel:
            try:
                await channel.send(content)
            except Exception as e:
                print(f"Error sending message to channel {channel_id}: {e}")
        else:
            print(f"Warning: Channel {channel_id} not found by bot instance.")
    else:
        print(f"Warning: Bot instance not available to send message to channel {channel_id}.")

# --- End temporary global references and helpers ---


# --- Definition of the RPGBot class ---
class RPGBot(Bot):
    # Constructor, takes services/managers needed to start
    def __init__(self, openai_service: OpenAIService, game_manager: GameManager, *args, **kwargs):
        super().__init__(*args, **kwargs) # Initialize parent discord.Bot class

        # Store instances of services/managers as attributes
        self.openai_service = openai_service # Service should ideally be accessed via GameManager or DI
        self.game_manager = game_manager

        # --- Set temporary global references during initialization ---
        global _rpg_bot_instance, global_game_manager, global_openai_service
        _rpg_bot_instance = self # 'self' here is the instance being created
        global_game_manager = self.game_manager
        global_openai_service = self.openai_service # This one is still used globally by some commands/logic

        # Register commands (calls a method to add commands)
        self.add_application_commands()


    # Event: Bot is ready
    async def on_ready(self):
        print(f'Logged in as {self.user.name} ({self.user.id})')
        print('Bot is ready!')
        if self.debug_guilds:
             print(f"Debugging slash commands on guilds: {self.debug_guilds}")

        # Optional: Start a background loop for world simulation
        # Needs 'import asyncio' at top
        # asyncio.create_task(self._simulation_loop())


    # Method to centralize command adding from command modules
    # This method *does* use 'self' because it's inside the class
    def add_application_commands(self):
        # General commands
        self.add_application_command(bot.command_modules.general_cmds.cmd_ping)

        # Game setup commands
        self.add_application_command(bot.command_modules.game_setup_cmds.cmd_start_game)
        self.add_application_command(bot.command_modules.game_setup_cmds.cmd_join_game)
        # Note: GM setup commands (set_gm, set_gm_channel, map_location_channel)
        # are defined in command_modules.game_setup_cmds and should be added here.
        # Make sure they accept the correct arguments and use global_game_manager.
        # Example: self.add_application_command(bot.command_modules.game_setup_cmds.cmd_set_gm)
        # Example: self.add_application_command(bot.command_modules.game_setup_cmds.cmd_set_gm_channel)
        # Example: self.add_application_command(bot.command_modules.game_setup_cmds.cmd_map_location_channel)
        # Example: self.add_application_command(bot.command_modules.game_setup_cmds.cmd_list_locations)
        # Example: self.add_application_command(bot.command_modules.game_setup_cmds.cmd_gm_start_event) # GM start event command


        # Exploration commands
        # Note: Commands like look, move, check are defined in command_modules.exploration_cmds
        # and should be added here. They should use global_game_manager.process_player_action
        self.add_application_command(bot.command_modules.exploration_cmds.cmd_look)
        self.add_application_command(bot.command_modules.exploration_cmds.cmd_move)
        self.add_application_command(bot.command_modules.exploration_cmds.cmd_check)

        # Action commands
        # Note: Interact, Attack commands are defined in command_modules.action_cmds
        # and should be added here. They should use global_game_manager.process_player_action
        self.add_application_command(bot.command_modules.action_cmds.cmd_interact)
        self.add_application_command(bot.command_modules.action_cmds.cmd_attack)

        # Inventory commands
        # Note: Inventory command is defined in command_modules.inventory_cmds and added here.
        self.add_application_command(bot.command_modules.inventory_cmds.cmd_inventory)


        # --- Simulation Trigger Command (GM only) ---
        # This command IS defined as a separate function OUTSIDE the class, below.
        # It is then imported and added here.
        self.add_application_command(cmd_gm_simulate) # <-- ADD THIS LINE TO REGISTER THE COMMAND FUNCTION DEFINED BELOW


    # Optional: Background simulation loop (this IS a method of the RPGBot class)
    # Needs 'import asyncio' at top
    # async def _simulation_loop(self):
    #     await self.wait_until_ready() # Wait until bot is connected
    #     while not self.is_closed():
    #         await asyncio.sleep(SIMULATION_TICK_INTERVAL) # Sleep for desired interval
    #         # Call GameManager to run simulation for ALL servers
    #         # Needs to iterate over game_manager.active_games
    #         # Use self.game_manager.run_simulation_tick(...)
    #         pass


# --- Simulation Trigger Command (GM only) - DEFINITION as a separate function ---
# This function is NOT a method of the RPGBot class, so it does NOT use 'self'
# It USES global variables/functions
@slash_command(name="gm_simulate", description="ГМ: Запустить один шаг симуляции мира.", guild_ids=TEST_GUILD_IDS)
# Using ApplicationContext for type hinting is good practice
async def cmd_gm_simulate(ctx: ApplicationContext):
    # !!! YAVNO OBYAVLYAYEM, CHTO SSYLAYEMSYA NA GLOBAL'NYE IMENA !!!
    # Tell Python that we're using the global variables/functions defined outside this function
    global global_game_manager, _send_message_from_manager

    # is_master_or_admin and is_gm_channel functions are used here.
    # They are assumed imported at the top of bot_core.py and accept ctx.
    # Check if the user is the GM or an admin using the imported helper function.
    if not is_master_or_admin(ctx): # This function is correctly called with ctx
         await ctx.respond("**Мастер:** Только Истинный Мастер может управлять ходом времени!", ephemeral=True) # Respond ephemerally to not clutter chat
         return

    # Optional: Check if the command is used in the designated GM channel
    # If not is_gm_channel(ctx):
    #     await ctx.respond("**Мастер:** Эту команду можно использовать только в GM-канале.", ephemeral=True)
    #     return

    # Defer the response, as simulation might take time
    await ctx.defer()

    # Check if the game manager is available (meaning a game has been started)
    if global_game_manager: # Use the global variable
         # Call the simulation method on the global game manager instance
         # Pass server ID and the callback function for sending messages
         await global_game_manager.run_simulation_tick(
              server_id=ctx.guild.id, # Pass the ID of the server where command was used
              send_message_callback=_send_message_from_manager # Pass the global callback function
          )
         # Messages generated by the simulation logic (e.g. event updates)
         # will be sent via the _send_message_from_manager callback provided.

         # Send a confirmation message back to the user who used the command (likely the GM)
         await ctx.followup.send("**Мастер:** Шаг симуляции мира завершен!")
    else:
         # If the game manager is not initialized, the game hasn't started
         await ctx.followup.send("**Мастер:** Не удалось запустить симуляцию, менеджер игры недоступен или игра не начата. Используйте `/start_game`.")


# --- run_bot function (Initializes and starts the bot) ---
# This function is also outside the RPGBot class
def run_bot():
    # Load environment variables from .env file
    load_dotenv()

    # Get essential tokens and keys
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    # --- Validation checks for tokens/keys ---
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN environment variable not found.")
        # It's critical to have the Discord token, so exit if missing.
        return

    if not OPENAI_API_KEY:
         print("Warning: OPENAI_API_KEY environment variable not found.")
         print("OpenAI dependent features (like most descriptions and AI simulation) will not work.")
         # Decide if the bot should still run without AI - our OpenAIService class handles this.


    # --- Initialize Services and the GameManager ---
    # These are the main components that manage game logic and external APIs.
    openai_service = OpenAIService(OPENAI_API_KEY)
    persistence_manager = PersistenceManager()
    # GameManager is the main orchestrator of game state and other managers/processors/rules.
    # It's initialized by run_bot. It will *internally* create its ActionProcessor and WorldSimulator instances.
    game_manager = GameManager(persistence_manager)

    # --- Create the Discord Bot instance ---
    # Pass the initialized services and managers to the Bot class constructor.
    # The Bot class will store these and potentially use them to set up
    # the temporary global variables or prepare for proper Dependency Injection (like Cogs).
    # Pass basic bot configuration: intents, command_prefix, debug_guilds.
    bot = RPGBot(
        openai_service=openai_service, # Pass the instance
        game_manager=game_manager,     # Pass the instance
        intents=intents,           # Use the global intents variable defined above
        command_prefix="!",        # Set the prefix for traditional commands (slash commands don't use this prefix)
        debug_guilds=TEST_GUILD_IDS # Use the global TEST_GUILD_IDS for fast testing
    )

    # --- Start the bot ---
    # This call connects the bot to Discord and starts its event loop.
    # This method is blocking - it runs indefinitely until the bot is stopped.
    try:
        bot.run(DISCORD_TOKEN)
    # --- Error Handling for startup ---
    # Specific login failure error
    except discord.errors.LoginFailure:
        print("Login Error: Invalid bot token. Check your DISCORD_TOKEN in the .env file.")
    # Catch any other exception during the bot's runtime start
    except Exception as e:
        print(f"An unexpected error occurred during bot startup: {e}")


# --- Entry point of the script ---
# This standard Python construct checks if the script is being run directly.
# If it is, call the run_bot function to start the application.
if __name__ == "__main__":
    run_bot()